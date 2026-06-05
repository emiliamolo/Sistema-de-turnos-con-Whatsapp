from fastapi import APIRouter, Request, HTTPException, Depends, Response
from ..models.schemas import WhatsAppWebhookRequest
from ..core.redis import get_redis
from ..core.config import settings
import json
import logging

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
logger = logging.getLogger(__name__)

# Esta ruta sirve exclusivamente para configurar y validar el webhook en el panel de Meta for Developers.
@router.get("/webhook")
async def verify_webhook(
    request: Request,
):
    query_params = request.query_params
    hub_mode = query_params.get("hub.mode")
    hub_challenge = query_params.get("hub.challenge")
    hub_verify_token = query_params.get("hub.verify_token")

    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
        
    logger.warning(f"Failed webhook verification attempt: mode={hub_mode}, token_match={hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN}")
    raise HTTPException(status_code=403, detail="Verification failed")

@router.post("/webhook")
async def receive_message(
    payload: WhatsAppWebhookRequest,
    redis=Depends(get_redis)
):
    logger.debug(f"Received WhatsApp webhook payload: {payload}")
    
    if not payload.entry:
        return {"status": "success"}

    for entry in payload.entry:
        if not entry.changes:
            continue
            
        for change in entry.changes:
            value = getattr(change, "value", None)
            if not value or not getattr(value, "messages", None):
                continue
            contacts = getattr(value, "contacts", None) or []
            for message in value.messages:
                msg_type = getattr(message, "type", None)
                body = ""
                
                # 2. SOPORTAR TEXTO LIBRE O INTERACCIONES DE BOTONES
                if msg_type == "text":
                    text_data = getattr(message, "text", {})
                    body = text_data.get("body") if isinstance(text_data, dict) else getattr(text_data, "body", "")
                
                elif msg_type == "interactive":
                    # Cuando tocan un botón, Meta envía la info en message.interactive['button_reply']['title']
                    interactive_data = getattr(message, "interactive", {})
                    if isinstance(interactive_data, dict) and "button_reply" in interactive_data:
                        body = interactive_data["button_reply"].get("title", "")
                
                # Si no es ninguno de los dos (ej: envió una foto o un sticker), ignoramos el mensaje
                if not body:
                    continue
                
                from_number = getattr(message, "from_number", None) or getattr(message, "from_", None)
                profile_name = None
                for contact in contacts:
                    if isinstance(contact, dict):
                        wa_id = contact.get("wa_id", "")
                        if wa_id == from_number:
                            profile = contact.get("profile", {})
                            if isinstance(profile, dict):
                                profile_name = profile.get("name")
                            break
                    
                task_data = {
                    "id": getattr(message, "id", None),
                    "from": from_number,
                    "text": body.strip(),
                    "timestamp": getattr(message, "timestamp", None),
                    "profile_name": profile_name,
                }
                
                try:
                    # Encolamos la tarea en Redis
                    redis.lpush("whatsapp_queue", json.dumps(task_data))
                    logger.info(f"Enqueued message ID {task_data['id']} from {task_data['from']}")
                except Exception as e:
                    logger.error(f"Failed to enqueue message to Redis: {e}")
    
    return {"status": "success"}