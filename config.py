#!/usr/bin/env python3
"""
config.py -- Configuracion del broker v2.

Todo lo ajustable en un solo sitio: puerto serie, ritmo de escritura,
modelo de IA y los datos personales que usan las opciones del menu
(ciudad para el tiempo, valores a seguir en bolsa, etc.).
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent

# --------------------------------------------------------------------------
# Lo que cambia de una maquina a otra: api.env
# --------------------------------------------------------------------------
#
# Regla del proyecto: lo que dependa de la maquina o sea personal va en
# api.env, que NO esta en git. config.py si esta versionado, asi que
# editarlo en la Raspberry deja el repo sucio y el "Actualizar Broker"
# del 286 se planta con "Your local changes would be overwritten by
# merge", que es justo romper el flujo que ese menu venia a resolver.
#
# Lo de aqui abajo son los valores POR DEFECTO. Para cambiar uno en una
# maquina concreta, se pone la clave en su api.env y listo.

ENV_FILE = BASE_DIR / "api.env"


def leer_env(clave: str, defecto: str = "") -> str:
    """
    Lee una clave de api.env (formato CLAVE=valor, # para comentarios).

    ia.py tiene su propio lector porque sin la clave de Claude no hay
    broker que valga y sale con error. Este es el lector blando, para
    lo opcional: si no esta la clave, se devuelve el valor por defecto.
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
# Enlace serie con el 286
# --------------------------------------------------------------------------

# El conversor USB-serie no siempre cae en el mismo /dev/, y en otra
# maquina puede ser ttyUSB1 o un /dev/tty.usbserial del Mac.
PORT = leer_env("PORT", "/dev/ttyUSB0")

# La velocidad NO va en api.env a proposito: no es una preferencia de
# maquina, es parte del protocolo. Tiene que coincidir con BAUDIOS en
# chat.c del 286, y si los dos numeros no son el mismo no hay
# configuracion que arregle nada, sale basura en pantalla.
#
# Divisores exactos de la UART (115200/n): 9600 (n=12), 14400 (n=8),
# 28800 (n=4), 38400 (n=3), 57600 (n=2).
#
# Nota sobre 28800: no es una velocidad estandar de termios, asi que en
# Linux pyserial la pide por el camino de baudrate a medida (TCSETS2).
# El conversor que hay puesto es un PL2303, y 28800 esta en la tabla de
# velocidades nativas de su driver (75, 150, ... 19200, 28800, 38400,
# 57600, 115200...), asi que sale exacta y no redondeada.
# Si algun dia se cambia de conversor por uno mas quisquilloso, 38400 es
# velocidad estandar, va mas rapido y tambien es divisor exacto: seria
# el cambio de una linea aqui y otra en chat.c.
#
BAUDRATE = 28800
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

# Ritmo de escritura, en segundos por caracter. Durante mucho tiempo
# esto valio 0.003, y era el verdadero cuello de botella de los menus:
# 3 ms por byte son ~330 bytes/s, o sea que el cable iba a 9600 pero el
# caudal real era el de unos 3300 baudios. Un menu de 800 caracteres
# tardaba mas de dos segundos y medio.
#
# El freno estaba ahi por una razon buena: CHAT.EXE recibia por sondeo
# contra una UART sin FIFO, y un byte no recogido a tiempo se perdia.
# Desde que serial.c del 286 recibe por interrupciones y amortigua en
# un buffer de 4 KB, ya no hace falta: se escribe la linea entera de
# una vez y manda el baudrate, no el sleep.
#
# Si alguna vez hubiera que volver a frenar (un cable muy largo, un
# adaptador raro), poner aqui un valor > 0 vuelve a activar el envio
# byte a byte tal cual estaba.
CHAR_DELAY = 0.0
# Margen extra tras el CRLF de cada linea. Existia porque CHAT.EXE
# mueve la VRAM una fila hacia arriba (scroll) antes de poder leer el
# siguiente byte; ahora ese scroll ocurre mientras la ISR sigue
# metiendo bytes en el buffer, asi que tampoco hace falta.
LINE_DELAY = 0.0

# Control de flujo por hardware. El 286 baja RTS cuando su buffer de
# recepcion se llena a 3/4 y lo vuelve a subir al bajar de 1/4; con
# esto activado, la Pi le hace caso y para.
#
# Solo sirve si el cable cruza de verdad RTS/CTS (pines 7-8). Un
# adaptador "null modem" barato cruza solo TX/RX y realimenta el RTS de
# cada lado a su propio CTS; uno completo cruza ademas 7-8 y 4-6. Por
# fuera son identicos, asi que hay que medirlo, no suponerlo: CHAT.EXE
# sube DTR y RTS al arrancar y los baja al salir, asi que se ve mirando
# si el CTS de la Pi se mueve al entrar y salir del chat.
#
# Y aunque el cable los cruce, activarlo tiene un efecto secundario:
# con el 286 en el prompt del DOS (sin CHAT.EXE cargado) su RTS esta
# bajo, asi que el write() de la Pi se bloquea hasta agotar el
# write_timeout de 5 s y salta SerialTimeoutException. Antes, sin
# control de flujo, el broker escribia al vacio tan tranquilo.
#
# Con el buffer de 4 KB del 286 no hace falta a estas velocidades: es
# una red de seguridad, no un requisito.
RTSCTS = False

# --------------------------------------------------------------------------
# Filtro de ruido de linea
# --------------------------------------------------------------------------

# El grueso del ruido lo paran dos filtros que no se configuran aqui:
# la ISR del 286 tira los bytes con error de trama o paridad, y
# sanitize_bytes() en terminal.py solo deja pasar ASCII imprimible,
# que es lo unico que CHAT.EXE puede enviar. Esto es la ultima red,
# para el ruido que casualmente salga como texto legible.
#
# Se aplica SOLO al chat libre (opcion 6), que es el unico sitio donde
# cualquier texto es valido y donde equivocarse cuesta una llamada a la
# API. En los menus no hace falta: ya validan contra las teclas que
# existen. Y en "consultar un valor suelto" seria un estorbo, porque
# hay tickers reales de una y dos letras (F, V, KO, BA).
#
# Nunca descarta en silencio: lo que se ignora se dice en pantalla,
# para poder repetirlo si de verdad era del usuario.
CHAT_MIN_LONGITUD = 3
CHAT_CORTAS_VALIDAS = {
    "SI", "NO", "OK", "YA", "VA", "EH", "AH", "HM", "?", "??",
}

# --------------------------------------------------------------------------
# API de Claude
# --------------------------------------------------------------------------

# La clave (ANTHROPIC_API_KEY) tambien esta en ENV_FILE, arriba; la
# lee ia.py con su propio lector.
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1200

# --------------------------------------------------------------------------
# Datos personales de las secciones del menu
# --------------------------------------------------------------------------

# Opcion 3 - Prevision del tiempo. En api.env por si el 286 cambia de
# casa. PAIS va con CIUDAD porque se usan juntos ("Madrid, Espana") y
# separarlos solo serviria para pedir el tiempo de la ciudad
# equivocada.
CIUDAD = leer_env("CIUDAD", "Madrid")
PAIS = leer_env("PAIS", "Espana")

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
# Yahoo corta con un 429 (Too Many Requests) a quien le pide mucho de
# golpe, y el cuadro entero son once peticiones. Estos tres numeros
# estan para no llegar a eso:
#   - CACHE: segundos que vale un precio ya pedido. Reabrir el menu de
#     cotizaciones dentro de este rato no gasta ni una peticion.
#   - PAUSA: respiro entre valor y valor del cuadro.
#   - REINTENTO: espera antes del unico reintento tras un 429, cuando
#     Yahoo no dice el suyo en la cabecera Retry-After.
MERCADOS_CACHE = 180
MERCADOS_PAUSA = 0.4
MERCADOS_REINTENTO = 3

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

# Las conversaciones fijadas NO se ponen aqui: van en api.env, que no
# esta en git. Dos motivos, y el segundo es el importante:
#
#   - los chat_id son datos personales y no pintan nada en un
#     repositorio publico;
#   - config.py si esta versionado, asi que editarlo en la Raspberry
#     dejaba el repo sucio y el "Actualizar Broker" del 286 se plantaba
#     con "Your local changes would be overwritten by merge".
#
# El formato en api.env es una sola linea, con las conversaciones
# separadas por ; y el nombre detras del id, separado por dos puntos:
#
#   TELEGRAM_CHATS=-1001234567890:Los colegas;123456789:Movil de Daniel
#
# Los grupos llevan el id en negativo. El id lo da el propio broker:
# Telegram -> "Ver chats que han escrito al bot".


def _leer_chats() -> list:
    chats = []
    for trozo in leer_env("TELEGRAM_CHATS").split(";"):
        trozo = trozo.strip()
        if not trozo:
            continue
        ident, _, nombre = trozo.partition(":")
        ident = ident.strip()
        try:
            chats.append((int(ident), nombre.strip() or ident))
        except ValueError:
            # Una entrada mal escrita no deja sin Telegram a las demas;
            # se avisa por el journal y se sigue.
            print(f"[config] TELEGRAM_CHATS: no entiendo '{trozo}', lo salto",
                  file=sys.stderr)
    return chats


TELEGRAM_CHATS = _leer_chats()
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
