# Sistema de Turnos con WhatsApp

Sistema web para gestionar turnos, clientes y profesionales, con reserva de turnos automatizada vía WhatsApp usando inteligencia artificial.

## Stack Tecnológico

| Componente | Tecnología |
|---|---|
| Backend | FastAPI (Python 3.11) |
| Base de datos | PostgreSQL 15 |
| Cola / caché | Redis 7 |
| Frontend | Jinja2 + HTMX + Tailwind CSS + FullCalendar |
| IA | Gemini 2.5 Flash (clasificación de mensajes) |
| WhatsApp | Meta Graph API v17.0 |
| Infra | Docker + Docker Compose |

## Estructura del Proyecto

```
.
├── app/
│   ├── main.py              # Punto de entrada de la API
│   ├── api/                 # Endpoints REST
│   │   ├── admin.py         # Panel de administración (CRUD, calendario, reservas)
│   │   ├── auth.py          # Autenticación JWT
│   │   ├── professional.py  # Panel de profesionales
│   │   └── whatsapp.py      # Webhook de recepción de mensajes
│   ├── core/                # Configuración, base de datos, dependencias
│   ├── models/              # Modelos SQLAlchemy y schemas Pydantic
│   ├── services/            # Lógica de negocio y acceso a datos
│   ├── templates/           # Templates Jinja2 con HTMX
│   └── worker/
│       └── main.py          # Worker de procesamiento de mensajes y envío
├── docker-compose.yml
├── Dockerfile
├── init.sql                 # Esquema inicial de la base de datos
├── requirements.txt
└── .env.example             # Plantilla de variables de entorno
```

## Cómo Compilar y Desplegar

### Requisitos

- Docker y Docker Compose
- Una cuenta de [Meta for Developers](https://developers.facebook.com/) con una app de WhatsApp Business configurada (opcional para integración con WhatsApp)
- Una API key de [Gemini](https://aistudio.google.com/apikey) (opcional para IA)

### 1. Configurar variables de entorno

```bash
cp .env.example .env
```

Editar `.env` con los valores reales. Las variables mínimas obligatorias:

- `SECRET_KEY`: clave secreta para firmar tokens JWT
- `SUPERADMIN_EMAIL` y `SUPERADMIN_PASSWORD`: credenciales del admin inicial

### 2. Levantar los servicios

```bash
docker compose up -d
```

Esto levanta 5 contenedores:

| Servicio | Puerto | Descripción |
|---|---|---|
| `turnos_api` | 8000 | API FastAPI + frontend web |
| `turnos_worker` | - | Worker de WhatsApp (procesa cola Redis) |
| `turnos_db` | 5432 | PostgreSQL |
| `turnos_redis` | 6379 | Redis (cola de mensajes + caché de sesiones) |
| `turnos_pgadmin` | 5050 | Interfaz gráfica para explorar y administrar la base de datos. Login: `admin@admin.com` / `admin` |

### 3. Acceder

- **Panel de administración**: http://localhost:8000/admin
- **Panel de profesionales**: http://localhost:8000/professional
- **pgAdmin** (explorar la DB): http://localhost:5050
- **Webhook de WhatsApp**: http://localhost:8000/whatsapp/webhook (para configurar en Meta)

---

## Integración con Meta API (WhatsApp)

### Flujo de Mensajes

```
Cliente WhatsApp
       │
       ▼
Meta Graph API ──POST──▶ /whatsapp/webhook (FastAPI)
       │                        │
       │                  Encola en Redis
       │                  "whatsapp_queue"
       │                        │
       │                        ▼
       │                  turnos_worker (blpop)
       │                        │
       │                  process_message()
       │                   ├── ai_or_exact() → Gemini 2.5 Flash
       │                   ├── check_booking_conflicts()
       │                   └── send_whatsapp_buttons()
       │                        │
       ◀────────────────────────┘
         Mensaje / botones
```

### Recepción de Mensajes (`app/api/whatsapp.py`)

1. Meta envía un POST al webhook `/whatsapp/webhook` con el mensaje del cliente
2. Se valida el token de verificación (configurado en `WHATSAPP_VERIFY_TOKEN`)
3. Se parsea el mensaje (texto libre o respuesta de botón interactivo)
4. Se encola en Redis bajo la clave `whatsapp_queue`
5. Se responde `200 OK` a Meta inmediatamente

### Procesamiento de Mensajes (`app/worker/main.py`)

El worker hace `BLPOP` sobre `whatsapp_queue` y procesa cada mensaje con una máquina de estados que maneja hasta 14 fases de conversación: menú principal, selección de servicio, profesional, semana, período, horario, confirmación de reserva, ver turnos, reprogramar, cancelar.

El estado de la conversación se persiste en Redis (`flow_state:{phone}`) con TTL de 30 minutos.

### Clasificación con IA (`app/services/ai_classifier.py`)

Los mensajes del usuario se clasifican con Gemini 2.5 Flash para matchearlos a las opciones disponibles del menú. Si Gemini no está configurado o no matchea, hay un fallback a matching exacto/normalizado. La IA entiende lenguaje coloquial, errores de tipeo, variaciones regionales y sinónimos.

### Envío de Mensajes

El worker envía respuestas al cliente usando la Meta Graph API v17.0:

- **Mensajes con botones**: `POST /{phone_number_id}/messages` con `type: interactive` y hasta 3 botones de respuesta rápida
- **Plantillas (templates)**: `POST /{phone_number_id}/messages` con `type: template` para recordatorios de turnos
- **Textos planos**: `POST /{phone_number_id}/messages` con `type: text`

La autenticación se hace con `Authorization: Bearer {WHATSAPP_ACCESS_TOKEN}`.

### Configuración en Meta for Developers

1. Crear una app de tipo Business en [developers.facebook.com](https://developers.facebook.com)
2. Agregar el producto WhatsApp
3. Configurar el webhook apuntando a `https://tu-dominio.com/whatsapp/webhook`
4. Usar el `WHATSAPP_VERIFY_TOKEN` definido en `.env`
5. Suscribirse a los eventos `messages`
6. Generar un token de acceso permanente en la configuración del número de teléfono

### Template de Recordatorios

Para que los recordatorios automáticos funcionen, hay que crear un **template de marketing** en el panel de Meta:

1. Ir a **WhatsApp > Gestor de plantillas** en el panel de Meta for Developers
2. Crear una plantilla con categoría **Marketing**
3. Definir el cuerpo con placeholders para los parámetros dinámicos, por ejemplo:

   ```
   Hola {{1}}, te recordamos tu turno del día {{2}} a las {{3}}. ¡Te esperamos!
   ```

4. Los placeholders `{{1}}`, `{{2}}` y `{{3}}` serán reemplazados automáticamente con el nombre del cliente, la fecha (`DD/MM/AAAA`) y la hora (`HH:MM hs`) de cada turno
5. Una vez aprobada por Meta, actualizar el nombre de la plantilla en el código (`app/worker/main.py`) para que coincida

---

## Recordatorios Automáticos

El worker ejecuta `check_and_send_reminders()` cada 5 minutos. Busca turnos próximos a comenzar y envía un recordatorio vía template de WhatsApp al cliente con los datos del turno.

---

## Usuarios y Roles

| Rol | Acceso |
|---|---|
| `superadmin` | Acceso total al panel de administración |
| `admin` | Gestión de turnos, clientes, servicios, salas, staff |
| `professional` | Ve solo sus turnos, puede cancelarlos y moverlos (con restricciones) |

El primer inicio crea automáticamente un superadmin con las credenciales definidas en `SUPERADMIN_EMAIL` y `SUPERADMIN_PASSWORD`.

---

## Endpoints Principales

### Web
- `GET /admin` — Panel de administración
- `GET /professional` — Panel de profesionales
- `GET /auth/login` — Login
- `GET /whatsapp/webhook` — Verificación del webhook (Meta)

### API REST
- `GET/POST /admin/api/bookings` — CRUD de turnos
- `GET/PUT /admin/api/calendar/events` — Eventos del calendario
- `GET /admin/api/available-slots` — Slots disponibles para una fecha
- `POST /whatsapp/webhook` — Recepción de mensajes de WhatsApp

---

## Concurrencia en PostgreSQL

El sistema usa una estrategia de **tres capas** para evitar doble reserva del mismo horario:

### Capa 1: Aplicación — `SELECT ... FOR UPDATE`

Antes de crear o modificar un turno, la función `check_booking_conflicts()` (`app/services/db_service.py:499`) busca si hay turnos solapados en sala o profesional usando:

```sql
WHERE room_id = :room AND start_time < :end AND end_time > :start
  AND status IN ('pending', 'confirmed')
FOR UPDATE
```

La cláusula `FOR UPDATE` bloquea las filas que coinciden con la búsqueda hasta que la transacción termine, impidiendo que otra operación concurrente inserte en el mismo rango antes de que se confirme el bloqueo. Esto garantiza que dos usuarios no puedan reservar el mismo slot simultáneamente sin que uno de los dos detecte el conflicto.

### Capa 2: Aplicación — Captura de `IntegrityError`

Si por alguna razón dos transacciones pasan la verificación de conflictos al mismo tiempo (race condition extrema), PostgreSQL lanza una `IntegrityError` al intentar insertar porque la constraint de exclusión de la base de datos lo rechaza. El código captura esta excepción y devuelve un error 409 al usuario:

```python
except IntegrityError:
    raise HTTPException(status_code=409, detail="El horario ya no está disponible.")
```

### Capa 3: Base de Datos — Exclusion Constraints

Como última barrera, `init.sql` define constraints de exclusión con `btree_gist` que impiden físicamente solapamientos a nivel de base de datos:

```sql
ALTER TABLE bookings ADD CONSTRAINT no_overlap_room
  EXCLUDE USING GIST (
    room_id WITH =,
    tstzrange(start_time, end_time) WITH &&
  ) WHERE (status IN ('pending', 'confirmed'));

ALTER TABLE bookings ADD CONSTRAINT no_overlap_staff
  EXCLUDE USING GIST (
    staff_id WITH =,
    tstzrange(start_time, end_time) WITH &&
  ) WHERE (status IN ('pending', 'confirmed'));
```

Estas constraints garantizan integridad de datos incluso si la lógica de aplicación falla o si se insertan datos directamente en la base de datos. El operador `&&` verifica solapamiento de rangos de tiempo, y solo aplica a reservas activas (`pending` o `confirmed`), permitiendo que turnos cancelados puedan solaparse sin problema.

**Índices de soporte** para rendimiento:
```sql
CREATE INDEX idx_bookings_time ON bookings (start_time, end_time);
CREATE INDEX idx_bookings_room_time ON bookings (room_id, start_time, end_time);
CREATE INDEX idx_bookings_staff_time ON bookings (staff_id, start_time, end_time);
```
