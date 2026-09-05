#!/usr/bin/env python3
"""
prompts.py -- Prompts de cada seccion del menu.

Todos comparten SYSTEM_TERMINAL, que impone el estilo que necesita una
pantalla de texto DOS de 80 columnas: sin markdown, sin acentos raros,
frases cortas. Las funciones de abajo construyen el prompt de usuario
de cada opcion metiendo la fecha de hoy y los datos de config.py.
"""

import time

import config

SYSTEM_TERMINAL = """Estas escribiendo en la pantalla de un ordenador
Intel 286 de 1990 con MS-DOS, conectado por RS232 a 9600 baudios a una
Raspberry Pi que hace de puente. La pantalla es de texto, 80 columnas.

Reglas de estilo, MUY IMPORTANTES:
- Texto plano. NADA de markdown: ni **negrita**, ni `codigo`, ni #
  titulos, ni tablas, ni listas con guiones o asteriscos. Si necesitas
  enumerar, usa "1) ", "2) " al principio de linea.
- No uses emojis ni simbolos raros. Solo ASCII y acentos normales.
- Lineas cortas: nunca pases de 68 caracteres por linea.
- Se conciso y directo. El texto tarda en llegar: cada caracter viaja
  por un cable serie lento. Sobra todo lo que no sea informacion.
- No digas que has buscado en internet ni describas tu proceso. Da el
  resultado y ya.
"""

SYSTEM_CHAT = SYSTEM_TERMINAL + """
Estas en el modo de conversacion libre. Puedes charlar de lo que sea,
opinar y bromear. Para CUALQUIER dato factual verificable (fechas,
cifras, nombres, eventos, noticias, tiempo, resultados deportivos)
usa SIEMPRE la busqueda web antes de responder, aunque creas saber la
respuesta.
"""


def _hoy() -> str:
    return time.strftime("%d/%m/%Y")



def cotizaciones() -> str:
    """
    Prompt del comentario de mercado.

    Ojo: los PRECIOS ya no salen de aqui, los da mercados.py contra una
    API de datos. A la IA se le piden ahora las listas solo para que
    sepa de que valores hablar; pedirle numeros era justo lo que hacia
    que se colara su proceso ("necesito el precio exacto de AAPL...")
    y que las cifras no cuadraran entre si.
    """
    acciones = "\n".join(f"- {nombre} ({simbolo})" for simbolo, nombre in config.ACCIONES)
    cryptos = "\n".join(f"- {nombre} ({simbolo})" for simbolo, nombre in config.CRYPTOS)
    divisas = "\n".join(f"- {nombre}" for _, nombre in config.DIVISAS)
    return f"""Hoy es {_hoy()}. Busca en internet que ha pasado hoy en
los mercados y explicamelo en pocas lineas. Estos son los valores que
sigo:

ACCIONES E INDICES:
{acciones}

CRIPTOMONEDAS:
{cryptos}

DIVISAS:
{divisas}

NO hagas una tabla de precios: los precios ya los tengo. Lo que quiero
es el porque. Formato exacto:

1) Una frase sobre como ha cerrado (o como va) el mercado espanol.
2) Una frase sobre Wall Street.
3) Dos o tres lineas, cada una empezando por el nombre de uno de mis
   valores, solo para los que hayan tenido un movimiento destacable o
   una noticia detras. Si ninguno la tiene, dilo en una linea y ya.
4) Una linea sobre cripto solo si ha habido algun movimiento fuerte.

Sin introduccion ni conclusion."""


def valor_suelto(consulta: str) -> str:
    return f"""Hoy es {_hoy()}. Busca en internet la cotizacion actual
de: {consulta}

Responde en pocas lineas: precio, variacion del dia, y una frase de
contexto si ha pasado algo destacable. Nada mas."""



def efemerides() -> str:
    return f"""Hoy es {_hoy()}. Busca que paso un dia como hoy en la
historia. Dame 5 efemerides interesantes, una por linea, con este
formato exacto:

1795 - Lo que paso, en una frase.

Ordenadas de mas antigua a mas reciente. Sin introduccion ni
conclusion."""
