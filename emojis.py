#!/usr/bin/env python3
"""
emojis.py -- Traduccion de emoji y simbolos raros a algo que el 286 pueda pintar.

Este fichero esta aparte a proposito: es el unico que hay que tocar
para anadir un emoji nuevo. Ni el modulo de Telegram ni el broker
saben nada de lo que hay aqui dentro.

Que hace falta traducir y que no:

- Los ACENTOS y la ene NO hay que tocarlos: CP437 los tiene (a = 0xA0,
  n = 0xA4), y CHAT.EXE vuelca el byte directamente en la VRAM, asi que
  se ven bien.
- Los EMOJI no existen en CP437. Sin traducir, el .encode("cp437",
  errors="replace") del Terminal los convierte en '?' y el mensaje
  pierde el tono. De ahi la tabla de abajo.
- Las COMILLAS TIPOGRAFICAS y las rayas largas que meten los moviles
  tampoco estan en CP437, y esas si molestan de verdad porque salen en
  mensajes normales todo el rato.

Para anadir uno nuevo: metelo en TABLA con lo que quieras que salga en
el 286. Solo ASCII o CP437; nada de mas emoji, obviamente.
"""

# Los cinco de siempre, que son el 90 por ciento de lo que llega.
TABLA = {
    "\U0001F602": ":-D",      # cara llorando de risa
    "\U0001F604": ":-)",      # cara sonriendo
    "❤": "<3",           # corazon rojo
    "\U0001F44D": "(OK)",     # pulgar arriba
    "\U0001F62D": ":'(",      # cara llorando

    # Puntuacion de movil que no existe en CP437. Esto no es un emoji,
    # pero llega en casi todos los mensajes y sin ello salen '?'.
    "‘": "'", "’": "'",          # comillas simples curvas
    "“": '"', "”": '"',          # comillas dobles curvas
    "–": "-", "—": "-",          # guion medio y raya
    "…": "...",                       # puntos suspensivos
}


def traducir(texto: str) -> str:
    """
    Pasa un mensaje de Telegram a algo pintable en el 286.

    Lo que este en TABLA se sustituye; lo que no y ademas no exista en
    CP437 (el resto de emoji, alfabetos no latinos...) se cambia por un
    punto, que se lee mejor que el '?' que pondria el Terminal.
    """
    for original, sustituto in TABLA.items():
        texto = texto.replace(original, sustituto)

    salida = []
    for caracter in texto:
        if caracter in ("\n", "\t"):
            salida.append(caracter)
            continue
        try:
            caracter.encode("cp437")
        except UnicodeEncodeError:
            salida.append(".")
        else:
            salida.append(caracter)
    return "".join(salida)
