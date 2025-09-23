"""
Se ejecuta cada 5 min (cron) y envía recordatorios a los pacientes que tengan cita en 5 h.
"""
import os, datetime, pytz
from dotenv import load_dotenv
from calendar import listar_eventos_dia
from whatsapp import enviar_mensaje
from config import ZONA_HORARIA

load_dotenv()
tz = pytz.timezone(ZONA_HORARIA)
ahora = datetime.datetime.now(tz)
ventana = ahora + datetime.timedelta(hours=5)
inicio = ventana.replace(minute=0, second=0, microsecond=0)
fin = (inicio + datetime.timedelta(minutes=59)).replace(minute=59)

# Trae todos los eventos del día
eventos = listar_eventos_dia(inicio.date())
for ev in eventos:
    start = datetime.datetime.fromisoformat(ev["start"]["dateTime"])
    # Si la cita está entre ventana ± 59 min
    if inicio <= start <= fin:
        # El teléfono está al final del summary (ver crear_evento)
        telefono = ev["summary"].split(" - ")[-1]
        enviar_mensaje(telefono,
                       "⏰ Recordatorio: tu cita es en 5 h. ¿Confirmas o cancelas?",
                       botones=[
                           {"type": "reply", "reply": {"id": "conf", "title": "Confirmar"}},
                           {"type": "reply", "reply": {"id": "canc", "title": "Cancelar"}}
                       ])