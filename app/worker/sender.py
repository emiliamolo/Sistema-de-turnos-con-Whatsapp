import logging

import httpx

from ..core.config import settings

logger = logging.getLogger("turnos_worker")

WHATSAPP_CONFIG = {
    "phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID,
    "access_token": settings.WHATSAPP_ACCESS_TOKEN,
}


def send_whatsapp_buttons(to_phone: str, text: str, buttons: list):
    if not WHATSAPP_CONFIG["phone_number_id"] or not WHATSAPP_CONFIG["access_token"]:
        logger.error("No hay configuración de WhatsApp disponible. No se puede enviar el mensaje.")
        return

    logger.info(f"ENVIANDO MENSAJE A {to_phone}: '{text}' con opciones {buttons}")
    url = f"https://graph.facebook.com/v17.0/{WHATSAPP_CONFIG['phone_number_id']}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_CONFIG['access_token']}", "Content-Type": "application/json"}

    if buttons and len(buttons) <= 3:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": f"btn_{i}", "title": boton_titulo}}
                        for i, boton_titulo in enumerate(buttons)
                    ]
                },
            },
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {"body": text},
        }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        if response.status_code != 200:
            logger.error(f"Error de Meta API ({response.status_code}): {response.text}")
    except Exception as e:
        logger.error(f"Fallo crítico al conectar con Meta Graph API: {e}")


def send_whatsapp_template(to_phone: str, template_name: str, language_code: str, body_params: list):
    if not WHATSAPP_CONFIG["phone_number_id"] or not WHATSAPP_CONFIG["access_token"]:
        logger.error("No hay configuración de WhatsApp disponible. No se puede enviar el template.")
        return

    logger.info(f"ENVIANDO TEMPLATE '{template_name}' A {to_phone} con params {body_params}")
    url = f"https://graph.facebook.com/v17.0/{WHATSAPP_CONFIG['phone_number_id']}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_CONFIG['access_token']}", "Content-Type": "application/json"}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(p)} for p in body_params
                    ],
                },
            ],
        },
    }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        if response.status_code != 200:
            logger.error(f"Error de Meta API ({response.status_code}): {response.text}")
    except Exception as e:
        logger.error(f"Fallo crítico al conectar con Meta Graph API: {e}")
