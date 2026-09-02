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


def leer_env(clave: str, defecto: str = "") -> str:
    """
    Lee una clave de api.env (formato CLAVE=valor, # para comentarios).

    ia.py tiene su propio lector porque sin la clave de Claude no hay
    broker que valga y sale con error. Este es el lector blando, para
    lo opcional: si no esta la clave, se devuelve el valor por defecto
    y la seccion que la necesite ya avisara.
    """
    if not ENV_FILE.exists():
        return defecto

    for linea in ENV_FILE.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        nombre, _, valor = linea.partition("=")
        if nombre.strip() == clave:
            return valor.strip().strip('"').strip("'")
    return defecto

# --------------------------------------------------------------------------
# Datos personales de las secciones del menu
# --------------------------------------------------------------------------

# Opcion 3 - Prevision del tiempo
CIUDAD = "Madrid"
PAIS = "Espana"

# Opcion 4 - Cotizaciones. Pares (simbolo de Yahoo, nombre que sale en
# la tabla del 286). El simbolo es el que usa finance.yahoo.com: los
# indices llevan ^ delante (^IBEX, ^GSPC), las acciones de Madrid
# acaban en .MC, la cripto se pide contra una moneda (BTC-EUR) y las
# divisas son un par con =X detras (EURUSD=X). Si no sabes el simbolo
# de un valor, buscalo desde el 286 con "Consultar un valor suelto":
# el broker lo resuelve por nombre y te lo ensena.
ACCIONES = [
    ("^IBEX", "IBEX 35"),
    ("SAN.MC", "Banco Santander"),
    ("ITX.MC", "Inditex"),
    ("TEF.MC", "Telefonica"),
    ("AAPL", "Apple"),
    ("NVDA", "Nvidia"),
]
CRYPTOS = [
    ("BTC-EUR", "Bitcoin"),
    ("ETH-EUR", "Ethereum"),
    ("SOL-EUR", "Solana"),
]
DIVISAS = [
    ("EURUSD=X", "EUR/USD"),
    ("EURGBP=X", "EUR/GBP"),
]
# Tope por peticion a la API de mercados. Son once peticiones seguidas
# para el cuadro entero, asi que conviene que ninguna se eternice.
MERCADOS_TIMEOUT = 12

# Opcion 1 y 2 - Noticias
PAIS_NOTICIAS = "Espana"
NUM_NOTICIAS = 6

# --------------------------------------------------------------------------
# Aplicaciones locales
# --------------------------------------------------------------------------

NOTAS_FILE = BASE_DIR / "notas.txt"
MAX_NOTAS = 100

# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------

# Conversaciones fijadas: pares (chat_id, nombre que sale en la lista).
# El chat_id lo da el propio broker: escribe al bot desde el movil y
# entra en Telegram -> "Ver chats que han escrito al bot"; ahi sale el
# numero para pegarlo aqui. Los grupos llevan el id en negativo.
TELEGRAM_CHATS = [
    # (123456789, "Movil de Daniel"),
    # (-100123456789, "Familia"),
]
# Cada cuanto se le pregunta a Telegram si hay respuesta, en segundos,
# mientras estas dentro de una conversacion. Bajarlo mucho no gana
# nada: el 286 tarda mas en pintar el mensaje que la Pi en pedirlo.
TELEGRAM_POLL = 5
TELEGRAM_TIMEOUT = 15
# Por donde iba la lectura de mensajes. Lo escribe el broker solo.
TELEGRAM_OFFSET_FILE = BASE_DIR / "telegram_offset.txt"

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
