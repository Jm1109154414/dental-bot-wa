"""
Configuración general del bot.
Aquí puedes cambiar horarios, zona, días laborables, etc.
"""
import os
from dotenv import load_dotenv
load_dotenv()

# Zona horaria de tu clínica (para que las citas se guarden correctamente)
ZONA_HORARIA   = os.getenv("ZONA_HORARIA", "America/Mexico_City")

# Días que atiendes: 0=lunes ... 4=viernes (cambiar si trabajas sábados)
LABORABLES     = [0,1,2,3,4]

# Horario de atención (formato 24 h)
APERTURA       = "09:00"
CIERRE         = "19:00"

# Tamaño de franja (30 o 60 min). Se usa para buscar huecos
SLOT_MIN       = int(os.getenv("SLOT_MIN", 30))

# Token que WhatsApp enviará al webhook para verificar que eres tú
VERIFIC_TOKEN  = "dentalbot2025"