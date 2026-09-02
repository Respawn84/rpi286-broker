#!/usr/bin/env python3
"""
config.py -- Configuracion del broker v2.

Todo lo ajustable en un solo sitio: puerto serie, ritmo de escritura,
modelo de IA y los datos personales que usan las opciones del menu
(ciudad para el tiempo, valores a seguir en bolsa, etc.).
"""

from pathlib import Path

BASE_DIR = Path(__file__).parent

# --------------------------------------------------------------------------
# Enlace serie con el 286
# --------------------------------------------------------------------------

PORT = "/dev/ttyUSB0"
BAUDRATE = 9600
# Valores tal cual los acepta serial.Serial (8N1). Se ponen literales
# para que este fichero no necesite importar pyserial: asi el simulador
# y las aplicaciones locales se pueden probar en cualquier maquina.
BYTESIZE = 8
PARITY = "N"
STOPBITS = 1

# Ancho util de la ventana de CHAT.EXE (74 - margenes). Se deja algo por
# debajo para que el cliente DOS no tenga que partir lineas por su cuenta.
SCREEN_WIDTH = 70
# Ancho de los marcos ASCII de los menus (mas estrecho = se pinta antes:
# cada caracter cuesta CHAR_DELAY en el cable).
BOX_WIDTH = 62
# Lineas por pagina antes de parar y esperar ENTER.
LINES_PER_PAGE = 16

# Ritmo de escritura. Ver la explicacion larga en broker_v1.py: la UART
# del 286 no tiene FIFO y algunos adaptadores USB-serie sueltan los
# primeros bytes en rafaga, asi que forzamos un ritmo mas lento que el
# baudrate real.
CHAR_DELAY = 0.003
# Margen extra tras el CRLF de cada linea: CHAT.EXE mueve la VRAM una
# fila hacia arriba (scroll) antes de poder leer el siguiente byte.
LINE_DELAY = 0.015

# --------------------------------------------------------------------------
# API de Claude
# --------------------------------------------------------------------------

ENV_FILE = BASE_DIR / "api.env"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1200

# --------------------------------------------------------------------------
# Datos personales de las secciones del menu
# --------------------------------------------------------------------------

# Opcion 3 - Prevision del tiempo
CIUDAD = "Madrid"
PAIS = "Espana"

# Opcion 4 - Cotizaciones. Nombres tal cual se los pasamos al buscador.
ACCIONES = [
    "IBEX 35",
    "Banco Santander (SAN.MC)",
    "Inditex (ITX.MC)",
    "Telefonica (TEF.MC)",
    "Apple (AAPL)",
    "Nvidia (NVDA)",
]
CRYPTOS = ["Bitcoin (BTC)", "Ethereum (ETH)", "Solana (SOL)"]
DIVISAS = ["EUR/USD", "EUR/GBP"]

# Opcion 1 y 2 - Noticias
PAIS_NOTICIAS = "Espana"
NUM_NOTICIAS = 6

# --------------------------------------------------------------------------
# Aplicaciones locales
# --------------------------------------------------------------------------

NOTAS_FILE = BASE_DIR / "notas.txt"
MAX_NOTAS = 100

# --------------------------------------------------------------------------
# Actualizacion desde GitHub (menu Configuracion)
# --------------------------------------------------------------------------

# El repositorio es la propia carpeta del broker: se instala haciendo
# git clone, asi que el .git ya esta al lado de estos ficheros.
REPO_DIR = BASE_DIR
# Tope para cualquier git. Un pull contra GitHub con la Pi en wifi
# flojo puede tardar, pero si pasa de aqui es que algo esta colgado y
# preferimos volver al menu antes que dejar mudo al 286.
GIT_TIMEOUT = 120
