#!/usr/bin/env python3
"""
actualizar.py -- Actualizacion del broker desde GitHub sin abrir un SSH.

La idea: se hace git push desde el PC o el Mac, y en el 286 basta con
entrar en Configuracion -> Actualizar Broker para que la Raspberry haga
el git pull y se reinicie con el codigo nuevo.

Sobre el reinicio: el servicio corre con NoNewPrivileges=true, asi que
no puede hacer 'sudo systemctl restart' ni aunque hubiera una regla de
sudoers. En vez de eso el proceso se limita a salir: la unidad lleva
Restart=always, o sea que systemd lo vuelve a levantar en RestartSec y
el codigo nuevo entra solo. Fuera de systemd (arrancado a mano) no hay
quien lo relance, asi que ahi se avisa y no se sale.
"""

import os
import subprocess

import config


class GitError(Exception):
    """El comando git no se pudo ejecutar o devolvio error."""


def _git(*args, timeout=None):
    """
    Lanza git dentro de la carpeta del broker y devuelve su salida.

    Se fuerza el ingles (LC_ALL=C) para que los mensajes de error que
    acaban en la pantalla del 286 no dependan del idioma de la
    Raspberry, y se apagan los prompts de credenciales: el repositorio
    es publico, pero si algun dia pidiera usuario y contrasena el
    proceso se quedaria colgado esperando algo que nadie va a teclear
    en el 286.
    """
    entorno = dict(os.environ,
                   LC_ALL="C",
                   LANG="C",
                   GIT_TERMINAL_PROMPT="0")

    try:
        proceso = subprocess.run(
            ["git", "-C", str(config.REPO_DIR), *args],
            capture_output=True, text=True, env=entorno,
            stdin=subprocess.DEVNULL,
            timeout=timeout or config.GIT_TIMEOUT,
        )
    except FileNotFoundError:
        raise GitError("no encuentro el programa git en la Raspberry")
    except subprocess.TimeoutExpired:
        raise GitError(f"git ha tardado mas de {timeout or config.GIT_TIMEOUT} s")

    salida = (proceso.stdout + proceso.stderr).strip()
    if proceso.returncode != 0:
        raise GitError(salida or f"git {args[0]} ha fallado")
    return salida


def bajo_systemd() -> bool:
    """
    True si nos ha arrancado systemd, o sea que al salir nos relanza.

    INVOCATION_ID lo pone systemd en todos los servicios desde la v232;
    JOURNAL_STREAM esta cuando la salida va al journal, que es nuestro
    caso (StandardOutput=journal).
    """
    return bool(os.environ.get("INVOCATION_ID") or os.environ.get("JOURNAL_STREAM"))


def version() -> dict:
    """Rama, commit y fecha del codigo que hay ahora mismo instalado."""
    datos = {"rama": "?", "commit": "?", "fecha": "?", "asunto": "", "sucio": False}
    try:
        datos["rama"] = _git("rev-parse", "--abbrev-ref", "HEAD", timeout=10)
        datos["commit"] = _git("rev-parse", "--short", "HEAD", timeout=10)
        datos["fecha"] = _git("log", "-1", "--format=%cd",
                              "--date=format:%d/%m/%Y %H:%M", timeout=10)
        datos["asunto"] = _git("log", "-1", "--format=%s", timeout=10)
        datos["sucio"] = bool(_git("status", "--porcelain", timeout=15))
    except GitError:
        pass
    return datos


def pull() -> tuple:
    """
    Trae los cambios de GitHub.

    Devuelve (hubo_cambios, texto_para_el_286). Se usa --ff-only a
    proposito: si en la Raspberry hay commits o cambios locales, es
    mejor que git se plante y avise a que se monte un merge a ciegas
    que nadie va a poder resolver desde el 286.
    """
    if _git("status", "--porcelain", timeout=15):
        raise GitError(
            "hay cambios locales sin guardar en la Raspberry.\n"
            "Entra por SSH y resuelvelo (git status) antes de actualizar."
        )

    antes = _git("rev-parse", "HEAD", timeout=10)
    salida = _git("pull", "--ff-only")
    despues = _git("rev-parse", "HEAD", timeout=10)

    if antes == despues:
        return False, "Ya estabas en la ultima version. No hay nada que traer."

    resumen = _git("log", "--oneline", "--no-decorate", "-10",
                   f"{antes}..{despues}", timeout=15)
    texto = "Actualizado.\n\nCambios que han entrado:\n" + resumen
    if salida:
        texto += "\n\n" + salida
    return True, texto
