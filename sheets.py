"""
Autollenado de Google Sheets cada vez que se agenda o cancela una cita.
Usa la misma cuenta de servicio que Google Calendar.
"""
import os, json, datetime
import gspread
from google.oauth2.service_account import Credentials
from config import ZONA_HORARIA
import pytz

# Credenciales y scope
SERVICE_ACCOUNT_INFO = json.loads(os.getenv("GCLOUD_SERVICE_ACCOUNT"))
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
gc = gspread.authorize(creds)

# ID de la hoja (lo pondrás en la variable SHEET_ID de Render)
SHEET_ID = os.getenv("SHEET_ID", "1Bxi...XxX")   # <-- cambia aquí o en Render
sheet = gc.open_by_key(SHEET_ID).sheet1

# Crear encabezados si está vacía
if not sheet.get_all_values():
    sheet.append_row(["Fecha", "Hora", "Paciente", "Tratamiento", "Teléfono", "Estado", "Registrado"])

def insertar_cita(fecha_hora, tratamiento, telefono, estado="Agendada"):
    """Inserta una fila con los datos de la cita."""
    fecha_str = fecha_hora.strftime("%d/%m/%Y")
    hora_str  = fecha_hora.strftime("%I:%M %p")
    sheet.append_row([fecha_str, hora_str, "", tratamiento, telefono, estado, datetime.datetime.now(pytz.timezone(ZONA_HORARIA)).strftime("%d/%m/%Y %H:%M")])