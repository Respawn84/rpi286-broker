#!/usr/bin/env python3
"""
ia.py -- Envoltorio de la API de Claude para el broker.

Dos usos:
  consulta()  -> una pregunta suelta con busqueda web (noticias, tiempo,
                 cotizaciones, efemerides). Sin historial.
  chat()      -> conversacion libre con historial, la opcion 6 del menu.

La clave se lee de api.env igual que en el broker v1.
"""

import sys

import config
import prompts

_client = None

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


class IAError(Exception):
    """Fallo al hablar con la API (red, cuota, clave...)."""


def load_api_key() -> str:
    if not config.ENV_FILE.exists():
        print(f"[ia] ERROR: no encuentro {config.ENV_FILE}", file=sys.stderr)
        print("[ia] Copia api.env.example a api.env y pon tu clave.", file=sys.stderr)
        sys.exit(1)

    for line in config.ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            if key.strip() == "ANTHROPIC_API_KEY":
                value = value.strip()
                if not value or "tu-clave-aqui" in value:
                    print("[ia] ERROR: rellena tu clave real en api.env", file=sys.stderr)
                    sys.exit(1)
                return value

    print("[ia] ERROR: ANTHROPIC_API_KEY no encontrada en api.env", file=sys.stderr)
    sys.exit(1)


def init() -> None:
    """Crea el cliente una sola vez, al arrancar el broker."""
    global _client
    if _client is None:
        # Import tardio: asi el simulador y las aplicaciones locales
        # funcionan en una maquina sin el paquete anthropic instalado.
        from anthropic import Anthropic
        _client = Anthropic(api_key=load_api_key())


def _texto(response) -> str:
    """
    Devuelve SOLO el ultimo bloque de texto de la respuesta.

    Con la tool de busqueda web, Claude suele soltar un bloque de texto
    ANTES de llamar a la tool ("Voy a buscar X..."), y otro DESPUES con
    la respuesta final ya con los datos. El primero es narracion del
    proceso, no la respuesta; unirlos con join() los pegaba sin
    separacion. Nos quedamos solo con el ultimo, que es el que llega
    tras el web_search_tool_result.
    """
    bloques = [b.text for b in response.content if b.type == "text"]
    return bloques[-1].strip() if bloques else "(sin respuesta de texto)"


def _create(system: str, messages, web: bool, max_tokens: int):
    kwargs = {
        "model": config.MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if web:
        kwargs["tools"] = [WEB_SEARCH_TOOL]

    try:
        return _client.messages.create(**kwargs)
    except Exception as e:
        print(f"[ia] ERROR llamando a la API: {e}", file=sys.stderr)
        raise IAError(str(e)) from e


def consulta(prompt: str, system: str = None, web: bool = True,
             max_tokens: int = None) -> str:
    """Pregunta suelta, sin historial. Lanza IAError si falla."""
    respuesta = _create(
        system=system or prompts.SYSTEM_TERMINAL,
        messages=[{"role": "user", "content": prompt}],
        web=web,
        max_tokens=max_tokens or config.MAX_TOKENS,
    )
    return _texto(respuesta) or "(sin respuesta de texto)"


def chat(conversacion) -> str:
    """
    Turno de conversacion libre. 'conversacion' es la lista de mensajes
    ya con el turno del usuario al final; no se modifica aqui.
    """
    respuesta = _create(
        system=prompts.SYSTEM_CHAT,
        messages=conversacion,
        web=True,
        max_tokens=config.MAX_TOKENS,
    )
    return _texto(respuesta) or "(sin respuesta de texto)"