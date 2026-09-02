#!/usr/bin/env python3
"""
broker_v2.py -- Puente serie 286 <-> Raspberry <-> Claude API,
                con capa de menu.

Diferencia con el v1: el v1 mandaba a la API cualquier linea que
llegara del 286 y devolvia la respuesta. El v2 mete delante un menu
navegable; la conversacion libre con Claude pasa a ser una opcion mas
(la 6), y ademas hay secciones con prompts preparados (noticias,
tiempo, cotizaciones) y aplicaciones que se ejecutan en la propia
Raspberry sin tocar la API.

El protocolo serie con CHAT.EXE es EXACTAMENTE el mismo que en el v1
(lineas de texto terminadas en CR LF, 9600 8N1), asi que no hay que
recompilar nada en el 286.

Requisitos:
    pip3 install pyserial anthropic --break-system-packages

Configuracion:
    - api.env con tu ANTHROPIC_API_KEY (igual que en el v1).
    - config.py para puerto, ciudad del tiempo, valores de bolsa, etc.

Uso:
    python3 broker_v2.py
"""

import sys
import time

import actualizar
import apps
import config
import ia
import mercados
import prompts
from terminal import Terminal

MENU_PRINCIPAL = [
    ("1", "Noticias Economicas"),
    ("2", "Noticias Politicas"),
    ("3", "Prevision del tiempo"),
    ("4", "Cotizaciones - Acciones y Cryptos"),
    ("5", "Aplicaciones"),
    ("6", "Chat con Claude"),
    ("7", "Configuracion"),
    ("0", "Apagar la sesion"),
]

BANNER = [
    "",
    "   PERELLASOFT / RASPBERRY PI  --  ENLACE SERIE 9600 8N1",
    "   Broker v2 conectado.",
    "",
]


# --------------------------------------------------------------------------
# Secciones que consultan a la IA
# --------------------------------------------------------------------------

def seccion_ia(term, titulo: str, prompt: str, aviso: str) -> None:
    """
    Patron comun a las opciones 1-4: avisar de que va a tardar (una
    consulta con busqueda web son 10-20 segundos y el 286 se queda
    mudo mientras tanto), preguntar, y volcar el resultado paginado.
    """
    term.aviso(aviso)
    try:
        texto = ia.consulta(prompt)
    except ia.IAError:
        term.print("ERROR: no he podido consultar la IA.")
        term.print("Revisa la red de la Raspberry e intentalo de nuevo.")
        term.pausa()
        return

    term.titulo(titulo)
    term.page(texto)
    term.pausa()


def seccion_noticias_economicas(term):
    seccion_ia(term, "Noticias economicas", prompts.noticias_economicas(),
               "Buscando noticias economicas, espera unos segundos...")


def seccion_noticias_politicas(term):
    seccion_ia(term, "Noticias politicas", prompts.noticias_politicas(),
               "Buscando noticias politicas, espera unos segundos...")


def seccion_tiempo(term):
    """El tiempo de la ciudad por defecto, o de otra si la piden."""
    sel = term.menu("PREVISION DEL TIEMPO", [
        ("1", f"{config.CIUDAD} (por defecto)"),
        ("2", "Otra ciudad"),
        ("0", "Volver"),
    ])
    if sel == "0":
        return

    lugar = None
    if sel == "2":
        lugar = term.ask("Ciudad (sin acentos):")
        if not lugar:
            return

    seccion_ia(term, "Prevision del tiempo", prompts.tiempo(lugar),
               "Consultando la prevision, espera unos segundos...")


def _cuadro_cotizaciones(term):
    """
    El cuadro de precios, sacado de la API de mercados (no de la IA).

    Son once peticiones HTTP seguidas, unos pocos segundos; lo que de
    verdad se nota es el volcado por el cable, asi que se manda todo de
    golpe y ya lo pagina el Terminal.
    """
    term.aviso("Consultando mercados, espera unos segundos...")

    lineas = []
    for titulo, valores in (("Acciones e indices", config.ACCIONES),
                            ("Criptomonedas", config.CRYPTOS),
                            ("Divisas", config.DIVISAS)):
        if not valores:
            continue
        if lineas:
            lineas.append("")
        lineas.extend(mercados.cuadro(titulo, valores))

    term.titulo(f"Cotizaciones {time.strftime('%d/%m/%Y')}")
    term.page("\n".join(lineas))
    term.print("")
    term.print_wrapped(mercados.pie())
    term.pausa()


def _valor_suelto(term):
    """Un valor cualquiera: se busca por nombre o por simbolo y se detalla."""
    consulta = term.ask("Valor a consultar (ej: Repsol, BTC-EUR, AAPL):")
    if not consulta:
        return

    term.aviso("Buscando el valor...")
    try:
        # Primero se prueba tal cual por si han escrito el simbolo
        # exacto (AAPL); si no existe, se busca por nombre (repsol).
        try:
            fila = mercados.cotizacion(consulta.upper())
        except mercados.MercadoError:
            encontrado = mercados.buscar(consulta)
            fila = mercados.cotizacion(encontrado["simbolo"], encontrado["nombre"])
    except mercados.MercadoError as e:
        term.print(f"No he podido consultar '{consulta}': {e}")
        term.pausa()
        return

    term.titulo(fila["nombre"][:config.SCREEN_WIDTH])
    term.print(mercados.linea_tabla(fila))
    term.print("")
    term.print(f"Simbolo:  {fila['simbolo']}")
    if fila.get("minimo") and fila.get("maximo"):
        term.print(f"Hoy:      {fila['minimo']:.4g} - {fila['maximo']:.4g} "
                   f"{fila['moneda']}")
    if fila.get("min52") and fila.get("max52"):
        term.print(f"52 sem.:  {fila['min52']:.4g} - {fila['max52']:.4g} "
                   f"{fila['moneda']}")
    if fila.get("hora"):
        term.print("Dato de:  " + time.strftime("%d/%m/%Y %H:%M",
                                                time.localtime(fila["hora"])))
    term.pausa()


def seccion_cotizaciones(term):
    sel = term.menu("COTIZACIONES", [
        ("1", "Mi lista (acciones, cryptos y divisas)"),
        ("2", "Consultar un valor suelto"),
        ("3", "Que ha pasado hoy en los mercados (Claude)"),
        ("0", "Volver"),
    ])
    if sel == "0":
        return

    if sel == "1":
        _cuadro_cotizaciones(term)
    elif sel == "2":
        _valor_suelto(term)
    else:
        # Los precios ya los da la API; a la IA se le pide el porque.
        seccion_ia(term, "Mercados hoy", prompts.cotizaciones(),
                   "Preguntando a Claude, espera unos segundos...")


# --------------------------------------------------------------------------
# Menu de aplicaciones
# --------------------------------------------------------------------------

def seccion_aplicaciones(term):
    opciones = [(clave, nombre) for clave, nombre, _ in apps.APPS]
    opciones.append(("0", "Volver al menu principal"))

    while True:
        sel = term.menu("APLICACIONES", opciones)
        if sel == "0":
            return

        funcion = next(f for clave, _, f in apps.APPS if clave == sel)
        try:
            funcion(term)
        except Exception as e:               # una app rota no tumba el broker
            print(f"[broker v2] ERROR en la aplicacion {sel}: {e}", file=sys.stderr)
            term.print("La aplicacion ha fallado. Vuelvo al menu.")


# --------------------------------------------------------------------------
# Chat libre (el comportamiento del broker v1)
# --------------------------------------------------------------------------

def seccion_chat(term):
    """Conversacion con historial. Se sale escribiendo 0 o MENU."""
    conversacion = []

    term.titulo("Chat con Claude")
    term.print("Escribe lo que quieras. 0 o MENU para volver al menu.")
    term.print("")

    while True:
        texto = term.wait_line()
        if not texto:
            continue
        if texto == "0" or texto.upper() in ("MENU", "SALIR", "FIN"):
            return

        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] 286 dice: {texto!r}")

        conversacion.append({"role": "user", "content": texto})
        try:
            respuesta = ia.chat(conversacion)
        except ia.IAError:
            conversacion.pop()               # no dejamos el turno fallido
            term.print("ERROR: fallo al consultar la IA. Intenta de nuevo.")
            continue

        print(f"[{ts}] Claude responde: {respuesta[:200]}...")
        conversacion.append({"role": "assistant", "content": respuesta})

        term.page(respuesta)

        # Limitar historial para no disparar coste ni latencia.
        if len(conversacion) > 20:
            conversacion = conversacion[-20:]


# --------------------------------------------------------------------------
# Configuracion / mantenimiento
# --------------------------------------------------------------------------

def _mostrar_version(term):
    datos = actualizar.version()
    term.titulo("Version instalada")
    term.print(f"Rama:   {datos['rama']}")
    term.print(f"Commit: {datos['commit']}  ({datos['fecha']})")
    if datos["asunto"]:
        term.print_wrapped(f"Ultimo: {datos['asunto']}")
    if datos["sucio"]:
        term.print("")
        term.print("AVISO: hay cambios locales sin guardar en la Raspberry.")
    term.print(f"Carpeta: {config.REPO_DIR}")


def seccion_actualizar(term):
    """
    git pull en la Raspberry y, si ha entrado codigo nuevo, reinicio
    para que el broker corra ya con el.
    """
    term.aviso("Buscando actualizaciones en GitHub, espera unos segundos...")
    try:
        hubo_cambios, texto = actualizar.pull()
    except actualizar.GitError as e:
        print(f"[broker v2] ERROR actualizando: {e}", file=sys.stderr)
        term.titulo("Actualizar broker")
        term.print("No he podido actualizar:")
        term.page(str(e))
        term.pausa()
        return

    print(f"[broker v2] git pull: {'cambios' if hubo_cambios else 'sin cambios'}")
    term.titulo("Actualizar broker")
    term.page(texto)

    if not hubo_cambios:
        term.pausa()
        return

    if not actualizar.bajo_systemd():
        # Arrancado a mano: si saliera aqui, nadie lo volveria a
        # levantar y el 286 se quedaria sin broker.
        term.print("")
        term.print("El broker no lo lleva systemd: reinicialo tu para")
        term.print("que el codigo nuevo entre en marcha.")
        term.pausa()
        return

    sel = term.menu("REINICIAR EL BROKER", [
        ("1", "Reiniciar ahora y aplicar la actualizacion"),
        ("0", "Luego (sigo con el codigo viejo)"),
    ])
    if sel == "0":
        term.print("Vale. La actualizacion entrara en el proximo reinicio.")
        term.pausa()
        return

    term.print("")
    term.print("Reiniciando el broker. Espera unos segundos y pulsa")
    term.print("ENTER para que vuelva a salir el menu.")
    print("[broker v2] Saliendo para que systemd relance con el codigo nuevo.")
    # Restart=always en la unidad: salir es la forma de reiniciarse
    # sin necesitar permisos de root desde dentro del servicio.
    raise SystemExit(0)


def seccion_configuracion(term):
    while True:
        sel = term.menu("CONFIGURACION", [
            ("1", "Actualizar Broker (git pull)"),
            ("2", "Ver version instalada"),
            ("0", "Volver al menu principal"),
        ])
        if sel == "0":
            return
        if sel == "1":
            seccion_actualizar(term)
        elif sel == "2":
            _mostrar_version(term)
            term.pausa()


# --------------------------------------------------------------------------
# Bucle principal
# --------------------------------------------------------------------------

SECCIONES = {
    "1": seccion_noticias_economicas,
    "2": seccion_noticias_politicas,
    "3": seccion_tiempo,
    "4": seccion_cotizaciones,
    "5": seccion_aplicaciones,
    "6": seccion_chat,
    "7": seccion_configuracion,
}


def open_port():
    # Import aqui dentro (y no arriba) para que simulador.py, que
    # sustituye esta funcion entera, no necesite pyserial instalado.
    import serial

    return serial.Serial(
        port=config.PORT,
        baudrate=config.BAUDRATE,
        bytesize=config.BYTESIZE,
        parity=config.PARITY,
        stopbits=config.STOPBITS,
        timeout=1,
        write_timeout=5,
    )


def main():
    ia.init()

    print(f"[broker v2] Abriendo {config.PORT} a {config.BAUDRATE} baudios 8N1...")
    try:
        ser = open_port()
    except OSError as e:   # serial.SerialException hereda de OSError
        print(f"[broker v2] ERROR abriendo el puerto: {e}", file=sys.stderr)
        sys.exit(1)

    term = Terminal(ser)
    print("[broker v2] Puerto abierto. Menu activo (Ctrl+C para salir)...")

    for linea in BANNER:
        term.print(linea)

    try:
        while True:
            # El menu se repinta solo con un ENTER a secas, asi que si el
            # 286 arranca CHAT.EXE despues del broker y se ha perdido este
            # primer menu, basta con pulsar ENTER para verlo.
            opcion = term.menu("MENU PRINCIPAL", MENU_PRINCIPAL,
                               pie="Elige una opcion y pulsa ENTER")

            if opcion == "0":
                term.print("Sesion cerrada. Pulsa ENTER para volver al menu.")
                term.wait_line()
                continue

            print(f"[broker v2] Opcion elegida: {opcion}")
            SECCIONES[opcion](term)

    except KeyboardInterrupt:
        print("\n[broker v2] Cerrando por Ctrl+C.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
