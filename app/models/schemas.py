from pydantic import BaseModel, Field
from typing import List, Optional, Any

class WhatsAppMessage(BaseModel):
    from_number: str = Field(..., alias="from")
    id: str
    timestamp: str
    text: Optional[dict] = None
    interactive: Optional[dict] = None
    type: str

class WhatsAppValue(BaseModel):
    messaging_product: str
    metadata: dict
    contacts: Optional[List[dict]] = None
    messages: Optional[List[WhatsAppMessage]] = None

class WhatsAppChange(BaseModel):
    value: WhatsAppValue
    field: str

class WhatsAppEntry(BaseModel):
    id: str
    changes: List[WhatsAppChange]

class WhatsAppWebhookRequest(BaseModel):
    object: str
    entry: List[WhatsAppEntry]

class BookingTask(BaseModel):
    customer_phone: str
    message_text: str
    timestamp: str
