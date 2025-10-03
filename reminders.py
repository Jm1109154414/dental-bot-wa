"""
Se ejecuta cada 5-10 min (cron) y envía recordatorios a los pacientes que tengan cita en 5 h.
"""
import os, datetime, pytz, re
from dotenv import load_dotenv
from calendar_functions import service, CAL_ID  # <-- NUEVO: Importamos el servicio y el ID del calendario
from whatsapp import enviar_mensaje
from config import ZONA_HORARIA

load_dotenv()
tz = pytz.timezone(ZONA_HORARIA)
ahora = datetime.datetime.now(tz)

# 1. Calcular el momento exacto del recordatorio (5 horas desde ahora)
momento_objetivo = ahora + datetime.timedelta(hours=5)

# 2. Definir una ventana de búsqueda (ej. 15 min antes, 15 min después)
inicio_busqueda = momento_objetivo - datetime.timedelta(minutes=15)
fin_busqueda = momento_objetivo + datetime.timedelta(minutes=15)

print(f"[{ahora.strftime('%Y-%m-%d %H:%M')}] Buscando citas para recordar entre {inicio_busqueda.strftime('%H:%M')} y {fin_busqueda.strftime('%H:%M')}")

# 3. Buscar eventos en Google Calendar en esa ventana futura
try:
    events_result = service.events().list(
        calendarId=CAL_ID,
        timeMin=inicio_busqueda.isoformat(),
        timeMax=fin_busqueda.isoformat(),
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    eventos = events_result.get('items', [])
except Exception as e:
    print(f"Error fatal al buscar eventos de recordatorio: {e}")
    eventos = [] # Evita que el script se rompa

for ev in eventos:
    # Ignorar eventos de día completo
    if 'dateTime' not in ev['start']:
        continue

    # 4. Evitar enviar recordatorios duplicados
    if '[REMINDED]' in ev['summary'] or '[CONFIRMED]' in ev['summary']:
        print(f"Recordatorio ya enviado o confirmado para: {ev['summary']}")
        continue

    # Extraer el teléfono del summary
    match = re.search(r'(\+\d+)', ev['summary'])
    if not match:
        print(f"No se encontró teléfono en el evento: {ev['summary']}")
        continue
        
    telefono = match.group(1)
    evento_id = ev['id']
    
    # 5. Enviar el mensaje de recordatorio
    print(f"Enviando recordatorio a {telefono} para su cita {ev['summary']}")
    enviar_mensaje(telefono,
                   "⏰ Recordatorio: Tu cita es en 5 horas. ¿Confirmas o cancelas?",
                   botones=[
                       {"type": "reply", "reply": {"id": "conf", "title": "Confirmar"}},
                       {"type": "reply", "reply": {"id": "canc", "title": "Cancelar"}}
                   ])
    
    # 6. Marcar el evento para no recordarlo de nuevo
    try:
        nuevo_summary = ev['summary'] + ' [REMINDED]'
        service.events().patch(
            calendarId=CAL_ID,
            eventId=evento_id,
            body={'summary': nuevo_summary}
        ).execute()
        print(f"Evento {evento_id} marcado como [REMINDED]")
    except Exception as e:
        print(f"Error al marcar el evento {evento_id} como [REMINDED]: {e}")