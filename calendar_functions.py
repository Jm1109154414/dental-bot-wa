"""
Funciones para leer y escribir eventos en Google Calendar.
No necesitas tocar nada aquí salvo que quieras usar un calendario diferente.
"""
import os, json, datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Cargamos el JSON de la cuenta de servicio que metiste en .env
SERVICE_ACCOUNT_INFO = json.loads(os.getenv("GCLOUD_SERVICE_ACCOUNT"))
SCOPES = ["https://www.googleapis.com/auth/calendar"]
creds = service_account.Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
service = build("calendar", "v3", credentials=creds)

# "primary" = calendario principal del usuario que compartiste
# Si usas otro calendario, pon su ID (está en Configuración → Calendario → ID)
CAL_ID = "primary"

def buscar_huecos(fecha_hora, duracion_min=60):
    """
    Devuelve True si hay hueco libre entre fecha_hora y fecha_hora + duracion_min
    """
    fin = fecha_hora + datetime.timedelta(minutes=duracion_min)
    events = service.events().list(calendarId=CAL_ID,
                                   timeMin=fecha_hora.isoformat(),
                                   timeMax=fin.isoformat(),
                                   singleEvents=True,
                                   orderBy="startTime").execute()
    return len(events.get("items", [])) == 0

def crear_evento(tratamiento, fecha_hora, telefono, duracion_min=60):
    """
    Crea la cita en Google Calendar y devuelve su ID (para cancelar después si hace falta)
    """
    fin = fecha_hora + datetime.timedelta(minutes=duracion_min)
    event = {
        "summary": f"{tratamiento} - {telefono}",
        "start": {"dateTime": fecha_hora.isoformat()},
        "end": {"dateTime": fin.isoformat()},
        "reminders": {"useDefault": False}   # nosotros enviamos el recordatorio
    }
    return service.events().insert(calendarId=CAL_ID, body=event).execute()["id"]

def cancelar_evento(event_id):
    """
    Borra la cita cuando el usuario cancela
    """
    service.events().delete(calendarId=CAL_ID, eventId=event_id).execute()

def listar_eventos_dia(fecha):
    """
    Devuelve todos los eventos de un día (lo usa reminders.py)
    """
    inicio = fecha.isoformat()
    fin = (fecha + datetime.timedelta(days=1)).isoformat()
    events = service.events().list(calendarId=CAL_ID, timeMin=inicio, timeMax=fin, singleEvents=True, orderBy="startTime").execute()
    return events.get("items", [])