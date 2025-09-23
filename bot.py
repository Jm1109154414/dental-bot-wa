"""
Servidor Flask que recibe los mensajes de WhatsApp (webhook)
y ejecuta el flujo: bienvenida → elegir tratamiento → pedir fecha → agendar → recordatorio
"""
import os, json, datetime, re, pytz
from flask import Flask, request
from dotenv import load_dotenv
from config import VERIFIC_TOKEN, ZONA_HORARIA, LABORABLES, APERTURA, CIERRE, SLOT_MIN
from calendar import buscar_huecos, crear_evento, cancelar_evento
from whatsapp import enviar_mensaje
from bloqueos import FESTIVOS

load_dotenv()
app = Flask(__name__)

# Carga catálogo y textos
with open("tratamientos.json", encoding="utf-8") as f:
    TRATAMIENTOS = {t["id"]: t for t in json.load(f)}
with open("templates.json", encoding="utf-8") as f:
    TEMPLATES = json.load(f)

# Memoria temporal (puedes cambiar por Redis o Google Sheets si escalas)
temp_cache = {}

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
    # 1. Saludo inicial
    if texto in ["hola", "ola", "buenas", "hello"]:
        botones = [{"type": "reply", "reply": {"id": k, "title": v["nombre"]}} for k, v in list(TRATAMIENTOS.items())]
        enviar_mensaje(tel, TEMPLATES["bienvenida"], botones)
        temp_cache[tel] = {}
        return

    # 2. Usuario eligió tratamiento (llegó por ID)
    if texto in TRATAMIENTOS:
        temp_cache[tel] = {"tratamiento": TRATAMIENTOS[texto]}
        enviar_mensaje(tel, TEMPLATES["pedir_fecha"])
        return

    # 3. Usuario envió fecha/hora
    fecha_hora = extraer_fecha_hora(texto)
    if fecha_hora and temp_cache.get(tel, {}).get("tratamiento"):
        tratamiento = temp_cache[tel]["tratamiento"]
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
            temp_cache[tel]["event_id"] = event_id
            fecha_str = fecha_hora.strftime("%d/%m/%Y")
            hora_str  = fecha_hora.strftime("%I:%M %p")
            msg = TEMPLATES["confirmada"].replace("{fecha}", fecha_str).replace("{hora}", hora_str)
            enviar_mensaje(tel, msg)
        else:
            alternativas = sugerir_alternativas(fecha_hora, duracion)
            alt1 = alternativas[0].strftime("%d/%m %I:%M %p")
            alt2 = alternativas[1].strftime("%d/%m %I:%M %p")
            msg = TEMPLATES["no_hay_hueco"].replace("{alt1}", alt1).replace("{alt2}", alt2)
            enviar_mensaje(tel, msg)
        return

    # 4. Botones de recordatorio
    if texto in ["conf", "confirmar"]:
        enviar_mensaje(tel, TEMPLATES["confirmado_ok"])
        return
    if texto in ["canc", "cancelar"]:
        event_id = temp_cache.get(tel, {}).get("event_id")
        if event_id:
            cancelar_evento(event_id)
        enviar_mensaje(tel, TEMPLATES["cancelado_ok"])
        return

    # Default
    enviar_mensaje(tel, "No entendí. Por favor escribe *Hola* para comenzar.")

# --------------------------
# FUNCIONES AUXILIARES
# --------------------------
def extraer_fecha_hora(texto):
    """
    Detecta patrones como:
    "mañana 4 pm", "hoy 3pm", "15/07 10am"
    Devuelve objeto datetime con zona horaria
    """
    try:
        texto = texto.lower()
        ahora = datetime.datetime.now(pytz.timezone(ZONA_HORARIA))
        dias = {"hoy": 0, "mañana": 1, "pasado": 2}
        offset = 0
        for k, v in dias.items():
            if k in texto:
                offset = v
                break
        fecha = ahora.date() + datetime.timedelta(days=offset)
        match = re.search(r"(\d{1,2})\s*([ap]m?)", texto)
        if not match:
            return None
        hora   = int(match.group(1))
        sufijo = match.group(2)
        if sufijo == "pm" and hora != 12:
            hora += 12
        if sufijo == "am" and hora == 12:
            hora = 0
        fecha_hora = datetime.datetime(fecha.year, fecha.month, fecha.day, hora, 0, 0, tzinfo=pytz.timezone(ZONA_HORARIA))
        return fecha_hora
    except Exception:
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