"""
Envía mensajes de texto o botones a través de la API oficial de WhatsApp.
No toques nada salvo que quieras agregar más tipos de mensaje (lista, ubicación, etc.)
"""
import os, requests

ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN")
PHONE_ID     = os.getenv("WA_PHONE_NUMBER_ID")
URL = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"

def enviar_mensaje(to, text, botones=None):
    """
    to: número del paciente (con código de país, sin +)
    text: mensaje
    botones: lista [{"type": "reply", "reply": {"id": "limpieza", "title": "Limpieza"}}]
    Si botones=None → envía texto simple
    """
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    if botones:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {"buttons": botones}
            }
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": text}
        }
    r = requests.post(URL, headers=headers, json=payload)
    # Opcional: imprime el código de respuesta para debug
    print("WhatsApp API status:", r.status_code, r.text)
    return r.status_code, r.text