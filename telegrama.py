#!/usr/bin/env python3
"""
telegrama.py -- Cliente de Telegram para el 286, sobre la Bot API.

Se llama telegrama.py y no telegram.py a proposito: hay un paquete de
pip que se llama telegram y, si algun dia se instala en la Raspberry,
un fichero nuestro con ese nombre lo taparia.

Como funciona: la Bot API es HTTPS y JSON, igual que mercados.py, asi
que no hace falta instalar nada. El bot se crea con @BotFather y su
token va en api.env, al lado de la clave de Anthropic.

Limitacion de un bot (no es un fallo, es como funciona Telegram): solo
ve los chats en los que esta metido, y no puede escribir el primero a
alguien que no le haya hablado antes. Para lo que queremos vale: le
escribes al bot desde el movil, o lo metes en un grupo, y el 286 es un
participante mas.

Decision de diseno importante: aqui NO hay hilos ni nada que escriba
en el puerto serie por su cuenta. Este modulo solo sabe hablar con
Telegram; quien decide cuando se pinta algo en el 286 es el broker,
y solo mientras estas dentro de la seccion de Telegram. Si no estas,
los mensajes se quedan en Telegram, que para eso es un servidor.
"""

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import config
import emojis

API = "https://api.telegram.org/bot{token}/{metodo}"

# Mensajes que aun no se han ensenado, por chat. Se llenan en sondear()
# y se vacian al entrar en la conversacion: asi, si llega algo de otro
# chat mientras estas escribiendo, no se pierde ni se cuela en medio.
_buzon = {}
_offset = None
# chat_id -> nombre, sacado de los mensajes que van llegando. Sirve
# para dos cosas: poner nombre a los avisos de otros chats y, sobre
# todo, para que puedas averiguar el chat_id que hay que poner en
# config.py sin buscarlo por internet.
_conocidos = {}


class TelegramError(Exception):
    """No se ha podido hablar con Telegram."""


# --------------------------------------------------------------------------
# Acceso a la Bot API
# --------------------------------------------------------------------------

def token() -> str:
    valor = config.leer_env("TELEGRAM_TOKEN")
    if not valor:
        raise TelegramError(
            "no hay TELEGRAM_TOKEN en api.env.\n"
            "Crea un bot con @BotFather en Telegram y pega su token ahi."
        )
    return valor


def disponible() -> bool:
    """Para poder avisar en el menu sin reventar si no esta configurado."""
    return bool(config.leer_env("TELEGRAM_TOKEN"))


def _api(metodo: str, params: dict = None, timeout: int = None) -> dict:
    url = API.format(token=token(), metodo=metodo)
    datos = urllib.parse.urlencode(params or {}).encode("utf-8")

    try:
        with urllib.request.urlopen(url, data=datos,
                                    timeout=timeout or config.TELEGRAM_TIMEOUT) as r:
            respuesta = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Telegram explica el motivo en el cuerpo aunque devuelva 4xx,
        # y ese texto ("chat not found") es mas util que el codigo.
        try:
            detalle = json.loads(e.read().decode("utf-8")).get("description", "")
        except Exception:
            detalle = ""
        raise TelegramError(detalle or f"Telegram responde {e.code}")
    except (urllib.error.URLError, socket.timeout):
        raise TelegramError("sin respuesta de Telegram (revisa la red de la Pi)")
    except ValueError:
        raise TelegramError("respuesta ilegible de Telegram")

    if not respuesta.get("ok"):
        raise TelegramError(respuesta.get("description", "Telegram ha dicho que no"))
    return respuesta.get("result")


# --------------------------------------------------------------------------
# Envio
# --------------------------------------------------------------------------

def enviar(chat_id, texto: str) -> None:
    _api("sendMessage", {"chat_id": chat_id, "text": texto})


# --------------------------------------------------------------------------
# Recepcion
# --------------------------------------------------------------------------

def _quien(mensaje: dict) -> str:
    autor = mensaje.get("from") or {}
    nombre = autor.get("first_name") or autor.get("username") or "?"
    return emojis.traducir(nombre)


def _que(mensaje: dict) -> str:
    """
    El texto del mensaje, o una descripcion de lo que sea que han
    mandado. Un 286 no puede ensenar una foto, pero si decir que la hay.
    """
    if mensaje.get("text"):
        return emojis.traducir(mensaje["text"])

    for clave, etiqueta in (("photo", "una foto"),
                            ("sticker", "un sticker"),
                            ("voice", "un audio"),
                            ("video", "un video"),
                            ("document", "un fichero"),
                            ("location", "una ubicacion")):
        if mensaje.get(clave):
            pie = mensaje.get("caption")
            if pie:
                return f"[{etiqueta}] {emojis.traducir(pie)}"
            return f"[{etiqueta}, no se puede ver aqui]"

    return "[mensaje de un tipo que no se ensenar]"


def sondear() -> int:
    """
    Pregunta a Telegram si hay algo nuevo y lo guarda en el buzon.

    Devuelve cuantos mensajes han entrado. Se usa timeout=0 (sondeo
    corto, no long polling) porque el broker tiene que volver enseguida
    a leer el puerto serie: mientras esta esperando a Telegram no puede
    atender al 286.
    """
    global _offset

    params = {"timeout": 0, "limit": 20, "allowed_updates": '["message"]'}
    if _offset is not None:
        params["offset"] = _offset

    entrados = 0
    for update in _api("getUpdates", params) or []:
        _offset = update["update_id"] + 1

        mensaje = update.get("message")
        if not mensaje:
            continue

        chat = mensaje.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue

        _conocidos[chat_id] = emojis.traducir(
            chat.get("title") or chat.get("first_name")
            or chat.get("username") or str(chat_id))

        _buzon.setdefault(chat_id, []).append({
            "autor": _quien(mensaje),
            "texto": _que(mensaje),
            "hora": time.strftime("%H:%M", time.localtime(mensaje.get("date", time.time()))),
        })
        entrados += 1

    _guardar_offset()
    return entrados


def recoger(chat_id) -> list:
    """Saca del buzon los mensajes de un chat (y los quita de ahi)."""
    return _buzon.pop(chat_id, [])


def pendientes() -> dict:
    """Cuantos mensajes esperan en cada chat, para avisar en el menu."""
    return {chat: len(lista) for chat, lista in _buzon.items() if lista}


def conocidos() -> dict:
    """chat_id -> nombre de todo lo que ha escrito al bot en esta sesion."""
    return dict(_conocidos)


def nombre_de(chat_id, defecto: str = None) -> str:
    """Nombre de un chat: el de config.py manda; si no, el que dio Telegram."""
    for fijado, nombre in config.TELEGRAM_CHATS:
        if fijado == chat_id:
            return nombre
    return _conocidos.get(chat_id) or defecto or str(chat_id)


# --------------------------------------------------------------------------
# El offset, en disco
# --------------------------------------------------------------------------
#
# Telegram guarda los mensajes hasta que dices por que update_id vas.
# Si el offset viviera solo en memoria, cada reinicio del broker
# volveria a soltar en el 286 todo lo que hubiera pendiente.

def _guardar_offset() -> None:
    if _offset is None:
        return
    try:
        config.TELEGRAM_OFFSET_FILE.write_text(str(_offset), encoding="utf-8")
    except OSError:
        pass                          # no poder guardarlo no es motivo de caerse


def cargar_offset() -> None:
    global _offset
    try:
        _offset = int(config.TELEGRAM_OFFSET_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        _offset = None


def descartar_atrasados() -> None:
    """
    Tira lo que hubiera pendiente sin ensenarlo.

    Se llama al entrar en la seccion: el modulo solo ensena mensajes
    mientras esta abierto, asi que lo que llego mientras estabas en el
    menu de cotizaciones no tiene por que aparecer de golpe.
    """
    try:
        sondear()
    except TelegramError:
        pass
    _buzon.clear()
