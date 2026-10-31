#!/usr/bin/env python3
"""
system.py -- Cosas del sistema operativo que se pueden pedir desde el 286.

De momento solo poner el reloj en hora, que en estas placas no es un
capricho: ni la Orange Pi ni la Raspberry tienen pila de reloj, asi que
tras un corte de luz pueden arrancar en 1970. Con la fecha mal, TODA
conexion TLS falla con "certificate is not yet valid", y eso tumba a la
vez la API de Claude, Telegram, las cotizaciones y hasta el git pull de
"Actualizar Broker". Es el fallo que mas veces deja el 286 mudo, y el
mas desconcertante, porque parece que no hay red.

Como se pone en hora sin red de confianza: se lee la cabecera Date de
una peticion HTTP **sin cifrar**. Da la hora al segundo, que es mas que
suficiente para que los certificados vuelvan a validar, y no necesita
que el reloj ya este bien (que es justo el problema). Lo mismo que hace
poner_hora.sh, pero desde dentro del broker.

Y para escribir el reloj NO se usa sudo. El servicio corre con
NoNewPrivileges=true, asi que sudo no puede escalar ni habiendo regla
de sudoers; en vez de eso la unidad le da al proceso la unica
capacidad que necesita:

    AmbientCapabilities=CAP_SYS_TIME

con lo que time.clock_settime() funciona siendo un usuario normal y sin
poder hacer nada mas. Si algun dia alguien mete ProtectClock=true en la
unidad, esto deja de funcionar: esa opcion existe precisamente para
prohibir lo que aqui queremos.
"""

import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

# Por http:// a proposito: con https volveriamos al problema que
# venimos a resolver. Solo se lee la cabecera Date, no el contenido.
HOSTS = ("deb.debian.org", "www.google.com", "1.1.1.1")
TIMEOUT = 8


class HoraError(Exception):
    """No se ha podido poner el reloj en hora."""


def hora_de_la_red() -> float:
    """Epoch segun la cabecera Date del primer host que contesta."""
    ultimo = ""

    for host in HOSTS:
        peticion = urllib.request.Request(
            f"http://{host}/", method="HEAD",
            headers={"User-Agent": "rpi286-broker"})
        try:
            with urllib.request.urlopen(peticion, timeout=TIMEOUT) as r:
                cabecera = r.headers.get("Date")
        except urllib.error.HTTPError as e:
            # Un 403 o un 301 tambien traen Date, y nos vale igual.
            cabecera = e.headers.get("Date") if e.headers else None
        except (urllib.error.URLError, OSError) as e:
            ultimo = f"{host}: {e}"
            continue

        if not cabecera:
            ultimo = f"{host}: no manda cabecera Date"
            continue

        try:
            # La cabecera es RFC 1123 y lleva la zona dentro ("... GMT"),
            # asi que el epoch sale bien sea cual sea la zona de la placa.
            return parsedate_to_datetime(cabecera).timestamp()
        except (TypeError, ValueError):
            ultimo = f"{host}: fecha ilegible ({cabecera})"

    raise HoraError(ultimo or "no ha contestado ningun servidor")


def actualizar_hora() -> str:
    """
    Pone el reloj en hora y devuelve un resumen para la pantalla del 286.

    Lanza HoraError con el motivo si no se puede, que es lo que espera
    la opcion del menu de Configuracion.
    """
    if not hasattr(time, "clock_settime"):
        raise HoraError("en este sistema no se puede poner el reloj "
                        "desde Python (no es Unix)")

    antes = time.time()
    epoch = hora_de_la_red()
    desvio = epoch - antes

    try:
        time.clock_settime(time.CLOCK_REALTIME, epoch)
    except PermissionError:
        raise HoraError(
            "me falta el permiso para tocar el reloj (CAP_SYS_TIME).\n"
            "Si el broker corre como servicio, vuelve a pasar "
            "instalar_servicio.sh; a mano, lanzalo con sudo.")
    except OSError as e:
        raise HoraError(f"el kernel no me deja poner la hora: {e}")

    return (f"Desvio corregido: {desvio:+.0f} segundos\n"
            f"Antes: {time.strftime('%d/%m/%Y %H:%M:%S', time.localtime(antes))}\n"
            f"Ahora: {time.strftime('%d/%m/%Y %H:%M:%S')}\n"
            "\n"
            "Si el desvio era grande, conviene reiniciar el broker para "
            "que las caches y los timeouts no se queden descuadrados.")
