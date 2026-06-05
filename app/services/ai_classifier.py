import json
import logging
from typing import Optional

logger = logging.getLogger("ai_classifier")

GENAI_AVAILABLE = False
try:
    from google import genai
    from google.genai import types

    GENAI_AVAILABLE = True
except ImportError:
    pass

SYSTEM_PROMPT = """Sos un clasificador de intenciones para un sistema de turnos por WhatsApp.
Tu única función es decidir a cuál de las opciones predefinidas corresponde el mensaje del usuario.
Sé flexible y permisivo: si el mensaje se aproxima a una opción aunque use palabras distintas, asignala.
Reglas importantes:
- El usuario escribe coloquialmente, con errores de tipeo, variaciones de preposiciones ("a la", "por la", "en la", "de la"), o usando sinónimos.
- Siempre respondé con la opción EXACTA tal cual aparece en la lista, no la modifiques.
- Si el mensaje no se relaciona con ninguna opción, marcá matched como false.
- Afirmaciones: "si", "dale", "bueno", "ok", "de una", "confirmo", "acepto" → opción de confirmar.
- Negaciones: "no", "nop", "cancelar", "dejá", "no quiero", "me arrepentí" → opción de cancelar.
- Horarios mañana: "a la mañana", "por la mañana", "en la mañana", "temprano", "AM", "mañana temprano", "durante la mañana" → Mañana (9-13hs).
- Horarios tarde: "a la tarde", "por la tarde", "en la tarde", "tardecito", "PM", "después del mediodía", "a la siesta" → Tarde (13-18hs).
- Semanas: "esta", "ahora", "esta misma", "ya", "cuanto antes" → esta semana. "la que viene", "próxima", "siguiente", "semana próxima", "semana que viene" → la próxima. "dentro de 2", "la otra", "en dos semanas", "en 3 semanas", "en un mes", "el mes que viene", "más adelante", "la próxima próxima" → en 2 semanas (es la opción más lejana disponible).
- Pedir turno: cualquier mensaje que exprese deseo de reservar/agendar/sacar/pedir turno/cita/hora → Pedir Nuevo Turno.
- Ver turnos: "ver turnos", "mis turnos", "qué turnos tengo", "consultar", "turnos activos", "mis citas" → Ver Mis Turnos.
- Reprogramar: "cambiar", "mover", "reprogramar", "modificar turno", "cambiar horario", "otro día", "otro horario" → Reprogramar.
- IMPORTANTE: Si las únicas opciones son "Pedir Nuevo Turno" y "Ver Mis Turnos" (menú principal o primer contacto), entonces cualquier mensaje sobre reprogramar, cancelar, modificar, mover o consultar turnos existentes debe mapearse a "Ver Mis Turnos". Solo mapeá a "Pedir Nuevo Turno" cuando el usuario claramente quiere crear/reservar/sacar un turno nuevo.
- Elegir otra opción: "otro período", "otro horario", "cambiar período" → Otro período. "otra semana", "cambiar semana" → Otra semana. "volver", "inicio", "atrás", "menú", "principal", "empezar de nuevo" → Volver al inicio.
- Elegir otra fecha: "otra fecha", "elegir otra", "cambiar fecha", "otro día" → Elegir otra fecha.
- Profesional: si el usuario dice un nombre de la lista de profesionales lo matchea exactamente, pero también acepta "cualquiera", "el que sea", "no me importa", "me da igual" → elegí el primer profesional de la lista.
- Servicio: si el usuario describe un servicio con otras palabras pero claramente se refiere a uno de la lista, machealo al más similar.
- Si el mensaje pide un turno para una fecha lejana (más de 2 semanas), igual respondé con la opción disponible más lejana (En 2 semanas)."""


class IntentClassifier:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = None
        if GENAI_AVAILABLE and api_key:
            self.client = genai.Client(api_key=api_key)
            logger.info("AI IntentClassifier inicializado con Gemini 2.5 Flash")
        elif not GENAI_AVAILABLE:
            logger.warning("google-genai no instalado. Clasificación AI deshabilitada.")
        else:
            logger.info("GEMINI_API_KEY no configurada. Clasificación AI deshabilitada.")

    def classify(self, message: str, options: list[str], context: str = "") -> Optional[str]:
        if not self.client or not options:
            return None

        options_list = "\n".join(f'- "{opt}"' for opt in options)

        prompt = f"""Contexto: {context if context else "Menú principal"}
Usuario: "{message}"
Opciones:
{options_list}

Elegí la mejor opción. Solo devolvé JSON, sin texto adicional.
{{"option":"opcion exacta","matched":true}} o {{"matched":false,"option":null}}"""

        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.1,
                    max_output_tokens=100,
                    response_mime_type="application/json",
                ),
            )
            raw = response.text.strip()
            raw = raw.removeprefix("Here").strip()
            raw = raw.removeprefix("here").strip()
            raw = raw.removeprefix("JSON:").strip()
            raw = raw.removeprefix("json:").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            if "{" in raw and "}" in raw:
                start = raw.index("{")
                end = raw.rindex("}") + 1
                raw = raw[start:end]
            result = json.loads(raw)
            if result.get("matched") and result.get("option") in options:
                return result["option"]
            return None
        except json.JSONDecodeError:
            logger.warning(f"AI response no fue JSON: {response.text[:150] if hasattr(response, 'text') else 'N/A'}")
            return None
        except Exception as e:
            logger.warning(f"AI classification error: {e}")
            return None


_classifier: Optional[IntentClassifier] = None


def get_classifier() -> Optional[IntentClassifier]:
    global _classifier
    if _classifier is None:
        from ..core.config import settings

        api_key = settings.GEMINI_API_KEY
        if api_key:
            _classifier = IntentClassifier(api_key)
        else:
            _classifier = None
    return _classifier


def ai_or_exact(
    message_text: str,
    options: list[str],
    classifier: Optional[IntentClassifier],
    context: str = "",
) -> Optional[str]:
    if not options:
        return None

    lower = message_text.strip().lower()
    normalized = lower

    try:
        import unicodedata

        normalized = unicodedata.normalize("NFKD", lower).encode("ascii", "ignore").decode()
    except Exception:
        pass

    for opt in options:
        opt_lower = opt.lower()
        opt_normalized = opt_lower
        try:
            import unicodedata

            opt_normalized = unicodedata.normalize("NFKD", opt_lower).encode("ascii", "ignore").decode()
        except Exception:
            pass
        if lower == opt_lower or normalized == opt_normalized:
            return opt

    if classifier:
        result = classifier.classify(message_text, options, context)
        if result:
            return result

    return None
