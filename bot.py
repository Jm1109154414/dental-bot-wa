"""
Servidor Flask que recibe los mensajes de WhatsApp (webhook)
y ejecuta el flujo: bienvenida → elegir tratamiento → pedir fecha → agendar → recordatorio
"""
import os, json, datetime, re, pytz
from flask import Flask, request
from dotenv import load_dotenv
from config import VERIFIC_TOKEN, ZONA_HORARIA, LABORABLES, APERTURA, CIERRE, SLOT_MIN
from calendar_functions import buscar_huecos, crear_evento, cancelar_evento, service, CAL_ID # <-- NUEVO: importar service y CAL_ID
from whatsapp import enviar_mensaje
from bloqueos import FESTIVOS
from sheets import insertar_cita

# <-- NUEVO: Configuración de Redis para persistencia -->
import redis
import json

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

if REDIS_PASSWORD:
    r = redis.from_url(REDIS_URL, password=REDIS_PASSWORD)
else:
    r = redis.from_url(REDIS_URL)

def guardar_estado(tel, datos):
    """Guarda el estado de la conversación en Redis con un TTL (Time To Live) de 1 hora."""
    r.setex(tel, 3600, json.dumps(datos))

def obtener_estado(tel):
    """Obtiene el estado de la conversación desde Redis."""
    datos = r.get(tel)
    return json.loads(datos) if datos else {}

def borrar_estado(tel):
    """Borra el estado de la conversación."""
    r.delete(tel)
# <-- FIN DE CONFIGURACIÓN REDIS -->

load_dotenv()
app = Flask(__name__)

# Carga catálogo y textos
with open("tratamientos.json", encoding="utf-8") as f:
    TRATAMIENTOS = {t["id"]: t for t in json.load(f)}
with open("templates.json", encoding="utf-8") as f:
    TEMPLATES = json.load(f)

# --------------------------
# RUTA DE VERIFICACIÓN (GET)
# --------------------------
@app.route("/webhook", methods=["GET"])
def verify():
    """
    WhatsApp manda un token para verificar que es tu servidor.
    Debe responder el challenge si el token coincide.
    """
    mode  = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode and token:
        if mode == "subscribe" and token == VERIFIC_TOKEN:
            return challenge, 200
        else:
            return "Forbidden", 403
    return "Not Found", 404

# --------------------------
# RUTA DE MENSAJES (POST)
# --------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Cada vez que un paciente escribe, WhatsApp envía un JSON aquí.
    """
    body = request.get_json()
    if not body:
        return "ok", 200
    entry = body.get("entry", [{}])[0]
    changes = entry.get("changes", [{}])[0]
    value = changes.get("value", {})
    if "messages" not in value:
        return "ok", 200
    msg = value["messages"][0]
    telefono = msg["from"]
    tipo      = msg.get("type")
    texto     = (msg.get("text", {}).get("body") or "").strip().lower()
    procesar_mensaje(telefono, texto)
    return "ok", 200

# --------------------------
# LÓGICA DEL CHAT
# --------------------------
def procesar_mensaje(tel, texto):
    # <-- NUEVO: Manejo de errores general -->
    try:
        # 1. Saludo inicial
        if texto in ["hola", "ola", "buenas", "hello"]:
            botones = [{"type": "reply", "reply": {"id": k, "title": v["nombre"]}} for k, v in list(TRATAMIENTOS.items())]
            enviar_mensaje(tel, TEMPLATES["bienvenida"], botones)
            guardar_estado(tel, {}) # <-- MODIFICADO: Usar Redis
            return

        # 2. Usuario eligió tratamiento (llegó por ID)
        if texto in TRATAMIENTOS:
            guardar_estado(tel, {"tratamiento": TRATAMIENTOS[texto]}) # <-- MODIFICADO: Usar Redis
            enviar_mensaje(tel, TEMPLATES["pedir_fecha"])
            return

        # 3. Usuario envió fecha/hora
        fecha_hora = extraer_fecha_hora(texto)
        estado_usuario = obtener_estado(tel) # <-- MODIFICADO: Usar Redis
        if fecha_hora and estado_usuario.get("tratamiento"):
            tratamiento = estado_usuario["tratamiento"]
            duracion = tratamiento["duracion"]

            # Validaciones
            if not es_habil(fecha_hora):
                enviar_mensaje(tel, "Solo atendemos de lunes a viernes. Por favor elige otro día.")
                return
            if es_feriado(fecha_hora):
                enviar_mensaje(tel, "Ese día estamos cerrados. Elige otro día.")
                return

            # ¿Hay hueco?
            if buscar_huecos(fecha_hora, duracion):
                event_id = crear_evento(tratamiento["nombre"], fecha_hora, tel, duracion)
                if event_id: # <-- MODIFICADO: Verificar que el evento se creó
                    guardar_estado(tel, {"event_id": event_id}) # <-- MODIFICADO: Guardar ID del evento
                    insertar_cita(fecha_hora, tratamiento["nombre"], tel, "Agendada")
                    fecha_str = fecha_hora.strftime("%d/%m/%Y")
                    hora_str  = fecha_hora.strftime("%I:%M %p")
                    msg = TEMPLATES["confirmada"].replace("{fecha}", fecha_str).replace("{hora}", hora_str)
                    enviar_mensaje(tel, msg)
                    borrar_estado(tel) # <-- MODIFICADO: Limpiar estado al finalizar
                else:
                    enviar_mensaje(tel, "Ocurrió un error al agendar en el calendario. Por favor, intenta con otra fecha/hora.")
            else:
                alternativas = sugerir_alternativas(fecha_hora, duracion)
                if alternativas:
                    alt1 = alternativas[0].strftime("%d/%m %I:%M %p")
                    alt2 = alternativas[1].strftime("%d/%m %I:%M %p")
                    msg = TEMPLATES["no_hay_hueco"].replace("{alt1}", alt1).replace("{alt2}", alt2)
                    enviar_mensaje(tel, msg)
                else:
                    enviar_mensaje(tel, "No encontramos horarios disponibles cerca de la fecha que solicitaste. Por favor, intenta con otro día.")
            return

        # 4. Manejo de respuestas a recordatorios <-- NUEVO: Lógica completa
        if texto in ["conf", "confirmar", "canc", "cancelar"]:
            print(f"Usuario {tel} respondió '{texto}' a un posible recordatorio.")
            
            ahora = datetime.datetime.now(pytz.timezone(ZONA_HORARIA))
            fin_busqueda = ahora + datetime.timedelta(hours=6)
            
            try:
                events_result = service.events().list(
                    calendarId=CAL_ID,
                    timeMin=ahora.isoformat(),
                    timeMax=fin_busqueda.isoformat(),
                    q=tel, # Busca por número de teléfono en el evento
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                
                eventos = events_result.get('items', [])
                if not eventos:
                    enviar_mensaje(tel, "No encontré ninguna cita próxima para confirmar o cancelar. Si quieres agendar, escribe *Hola*.")
                    return

                ev = eventos[0]
                evento_id = ev['id']
                
                if texto in ["conf", "confirmar"]:
                    enviar_mensaje(tel, "¡Perfecto! Tu cita ha sido confirmada. ¡Te esperamos! 😊")
                    nuevo_summary = ev['summary'].replace('[REMINDED]', '[CONFIRMED]')
                    service.events().patch(calendarId=CAL_ID, eventId=evento_id, body={'summary': nuevo_summary}).execute()
                    print(f"Cita {evento_id} confirmada para {tel}")

                elif texto in ["canc", "cancelar"]:
                    tratamiento = ev['summary'].split(' - ')[0]
                    cancelar_evento(evento_id)
                    insertar_cita(ahora, tratamiento, tel, "Cancelada")
                    enviar_mensaje(tel, "Entendido. Hemos cancelado tu cita. Si quieres reagendar, solo escribe *Hola*.")
                    print(f"Cita {evento_id} cancelada para {tel}")
            except Exception as e:
                print(f"Error al procesar confirmación/cancelación para {tel}: {e}")
                enviar_mensaje(tel, "No pude procesar tu solicitud. Por favor, intenta de nuevo.")
            
            return

        # Default
        enviar_mensaje(tel, "No entendí. Por favor escribe *Hola* para comenzar.")

    except Exception as e:
        # <-- NUEVO: Bloque catch general -->
        print(f"❌ Error inesperado procesando mensaje de {tel}: {e}")
        enviar_mensaje(tel, "Lo siento, tuve un problema técnico. Por favor, intenta de nuevo en unos momentos o escribe *Hola* para empezar de nuevo.")
        borrar_estado(tel) # Limpiar estado por si acaso

# --------------------------
# FUNCIONES AUXILIARES
# --------------------------
def extraer_fecha_hora(texto):
    """
    Detecta patrones como:
    "mañana 4 pm", "hoy 3pm", "15/07 10am", "lunes 10am"
    Devuelve objeto datetime con zona horaria o None si no entiende.
    """
    try:
        texto = texto.lower()
        ahora = datetime.datetime.now(pytz.timezone(ZONA_HORARIA))
        
        # 1. Manejar días relativos (hoy, mañana)
        dias_relativos = {"hoy": 0, "mañana": 1, "pasado": 2}
        offset = None
        for k, v in dias_relativos.items():
            if k in texto:
                offset = v
                break
        
        # 2. Si no es un día relativo, buscar día de la semana <-- NUEVO
        if offset is None:
            dias_semana_map = {
                "lunes": 0, "martes": 1, "miércoles": 2, "jueves": 3, 
                "viernes": 4, "sábado": 5, "domingo": 6
            }
            for dia_nombre, dia_num in dias_semana_map.items():
                if dia_nombre in texto:
                    hoy_dia_num = ahora.weekday()
                    dias_hasta = (dia_num - hoy_dia_num + 7) % 7
                    if dias_hasta == 0: # Si es hoy, asumimos que se refiere a la semana que viene
                        dias_hasta = 7
                    offset = dias_hasta
                    break
        
        if offset is None:
            return None

        fecha_objetivo = ahora + datetime.timedelta(days=offset)
        
        # 3. Extraer la hora
        match = re.search(r"(\d{1,2})\s*([ap]m?)", texto)
        if not match:
            return None
        hora = int(match.group(1))
        sufijo = match.group(2)
        if "pm" in sufijo and hora != 12:
            hora += 12
        if "am" in sufijo and hora == 12:
            hora = 0
            
        fecha_hora = datetime.datetime(
            fecha_objetivo.year, fecha_objetivo.month, fecha_objetivo.day, 
            hora, 0, 0, tzinfo=pytz.timezone(ZONA_HORARIA)
        )
        return fecha_hora

    except Exception as e:
        print(f"Error al extraer fecha/hora de '{texto}': {e}")
        return None

def es_habil(fecha_hora):
    return fecha_hora.weekday() in LABORABLES

def es_feriado(fecha_hora):
    return fecha_hora.strftime("%Y-%m-%d") in FESTIVOS

def sugerir_alternativas(fecha_hora, duracion):
    """
    Busca 2 huecos siguientes (mismo día o día siguiente)
    """
    alternativas = []
    t = fecha_hora + datetime.timedelta(minutes=SLOT_MIN)
    for _ in range(20):
        if es_habil(t) and not es_feriado(t) and buscar_huecos(t, duracion):
            alternativas.append(t)
            if len(alternativas) == 2:
                break
        t += datetime.timedelta(minutes=SLOT_MIN)
    if len(alternativas) < 2:
        t = fecha_hora.replace(hour=int(APERTURA.split(":")[0]), minute=0) + datetime.timedelta(days=1)
        for _ in range(20):
            if es_habil(t) and not es_feriado(t) and buscar_huecos(t, duracion):
                alternativas.append(t)
                if len(alternativas) == 2:
                    break
            t += datetime.timedelta(minutes=SLOT_MIN)
    return alternativas or [fecha_hora + datetime.timedelta(hours=1)] * 2

# Arrancar servidor solo si ejecutas bot.py directamente
if __name__ == "__main__":
    app.run(debug=True)