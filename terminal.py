#!/usr/bin/env python3
"""
terminal.py -- Capa de "pantalla" sobre el puerto serie del 286.

Encapsula todo lo que tiene que ver con hablar con CHAT.EXE: leer
lineas, escribirlas al ritmo que aguanta la UART sin FIFO del 286,
dibujar marcos ASCII en CP437 y paginar texto largo.

El protocolo con el 286 NO cambia respecto al broker v1:
  - del 286 llega una linea de texto ASCII terminada en CR LF
  - hacia el 286 se mandan lineas de texto CP437 terminadas en CR LF

Diferencia importante frente al v1: aqui si distinguimos una linea
vacia (el usuario pulso ENTER sin escribir nada) de "no ha llegado
nada en todo el timeout". El v1 devolvia b"" en los dos casos, asi
que el "-- MAS (pulsa ENTER) --" de la paginacion nunca avanzaba con
un ENTER a secas. Un menu depende de poder leer ese ENTER vacio.
"""

import re
import time
import textwrap

import config

# --------------------------------------------------------------------------
# Caracteres de marco (CP437). CHAT.EXE escribe directamente en la VRAM
# en modo texto, asi que la zona alta de CP437 se ve tal cual.
# --------------------------------------------------------------------------

ESQ_SI, ESQ_SD, ESQ_II, ESQ_ID = "╔", "╗", "╚", "╝"
BORDE_H, BORDE_V = "═", "║"
CONECTOR_I, CONECTOR_D = "╠", "╣"

# Secuencias de escape ANSI/VT100 tipicas: ESC seguido de '[' o ']' y una
# cadena de parametros terminada en una letra (CSI) o en BEL/ST (OSC).
_ANSI_ESCAPE_RE = re.compile(
    rb"""
    \x1b            # ESC
    (?:
        \[ [0-?]* [ -/]* [@-~]     # secuencia CSI: ESC [ ... letra final
        |
        \] .*? (?:\x07|\x1b\\)     # secuencia OSC: ESC ] ... BEL o ESC\
        |
        [@-Z\\-_]                  # secuencias cortas de 2 bytes (ESC + letra)
    )
    """,
    re.VERBOSE,
)


def sanitize_bytes(raw: bytes) -> bytes:
    """
    Deja pasar solo lo que CHAT.EXE es capaz de mandar de verdad.

    El filtro se define por lo que hace el bucle de teclado del 286:

        } else if (tecla >= 32 && tecla < 127) {     // chat.c
            input_buf[input_len++] = (char)tecla;

    O sea ASCII imprimible y nada mas: ni acentos, ni bytes altos, ni
    caracteres de control. Cualquier otra cosa que aparezca en el cable
    es ruido por definicion, porque no hay forma de teclearla.

    Antes esto aceptaba 0x20..0xFF, es decir toda la mitad alta de
    CP437, y por ahi se colaban bytes de ruido que acababan enviados a
    la API como si fueran un mensaje ('\\x80\\x80' llegaba como 'CC').
    La mitad alta hace falta para lo que se manda HACIA el 286 (los
    marcos de los menus), no para lo que llega DESDE el.
    """
    raw = _ANSI_ESCAPE_RE.sub(b"", raw)
    return bytes(b for b in raw if b == 0x09 or 0x20 <= b <= 0x7E)


def ruta(*partes) -> str:
    """
    Migas de pan para el titulo de la caja: "NOTICIAS > Autonomica > Madrid".

    Con menus anidados tres niveles, un titulo fijo como "NOTICIAS" deja
    de decir donde estas: dentro de "Madrid" y dentro de "Deportes" la
    pantalla se ve igual. Esto pone el camino entero en la cabecera del
    marco, que es el unico sitio que siempre esta a la vista.

    Si no cabe en BOX_WIDTH se recortan tramos por la IZQUIERDA, no por
    la derecha: el ultimo tramo es donde estas ahora, que es justo el
    dato que no se puede perder.
    """
    partes = [str(p).strip() for p in partes if p]
    if not partes:
        return ""

    # caja() escribe f" {titulo}" dentro de un interior de BOX_WIDTH - 2.
    ancho = config.BOX_WIDTH - 3

    texto = " > ".join(partes)
    while len(texto) > ancho and len(partes) > 1:
        partes.pop(0)
        texto = "... > " + " > ".join(partes)

    return texto[:ancho]


def parece_ruido(texto: str) -> bool:
    """
    Dice si una linea es demasiado corta para ser algo que alguien haya
    escrito a proposito. Pensado SOLO para el chat libre.

    No vale como filtro general: las opciones de menu son de un
    caracter ('1', '0'), la paginacion avanza con un ENTER vacio, y en
    "consultar un valor suelto" hay tickers reales de una o dos letras
    (F de Ford, V de Visa, KO, BA). Por eso esto se aplica unicamente
    donde cualquier texto es valido y equivocarse cuesta una llamada a
    la API: la conversacion con Claude.
    """
    t = texto.strip()
    if len(t) >= config.CHAT_MIN_LONGITUD:
        return False
    if t.upper() in config.CHAT_CORTAS_VALIDAS:
        return False
    if t.isdigit():
        return False
    return True


class Terminal:
    """Pantalla y teclado del 286, vistos desde la Raspberry."""

    def __init__(self, ser):
        self.ser = ser
        # Tras un CR hay que tragarse el LF que viene detras sin
        # contarlo como una segunda linea (vacia).
        self._skip_lf = False

    # ---------------------------------------------------------------- lectura

    def read_line(self):
        """
        Devuelve la siguiente linea del 286 ya limpia y sin espacios:
          - None  -> no ha llegado nada: timeout del puerto, o lo que
                     llego era ruido entero y se ha descartado
          - ""    -> el usuario pulso ENTER sin escribir nada
          - "..." -> texto
        """
        buf = bytearray()
        while True:
            b = self.ser.read(1)

            if not b:
                if buf:
                    # Llego texto pero se corto sin CR/LF: lo damos por bueno.
                    return self._decode(buf)
                return None

            if b == b"\n" and self._skip_lf:
                self._skip_lf = False
                continue
            self._skip_lf = False

            if b in (b"\r", b"\n"):
                self._skip_lf = (b == b"\r")
                return self._decode(buf)

            buf += b

    def wait_line(self) -> str:
        """Como read_line pero bloquea hasta que el 286 diga algo."""
        while True:
            linea = self.read_line()
            if linea is not None:
                return linea

    def _decode(self, buf: bytearray):
        """
        Devuelve el texto de la linea, o None si lo que llego era ruido
        entero.

        La distincion importa: una linea que se queda vacia DESPUES de
        filtrar no es lo mismo que un ENTER a secas. Si se devolviera ""
        el menu se repintaria solo, la paginacion avanzaria de pagina y
        el chat se comeria un turno, todo por un chispazo en el cable.
        Devolviendo None queda como "no ha llegado nada", que es
        exactamente lo que ha pasado, y wait_line sigue esperando.

        Un ENTER de verdad llega con buf vacio, asi que sale por el
        camino de "" y se sigue distinguiendo bien.
        """
        raw = bytes(buf)
        limpio = sanitize_bytes(raw)
        if limpio != raw:
            print(f"[term] (filtrado ruido/ANSI: {raw!r} -> {limpio!r})")

        texto = limpio.decode("cp437", errors="replace").strip()

        if raw and not texto:
            print("[term] (linea descartada: era ruido entero)")
            return None

        return texto

    def drain(self) -> None:
        """Tira lo que hubiera pendiente en el buffer de entrada."""
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass
        self._skip_lf = False

    # --------------------------------------------------------------- escritura

    def _write_paced(self, data: bytes) -> None:
        """
        Escribe la linea entera de un write() cuando CHAR_DELAY es 0, y
        byte a byte con esa pausa entre cada uno cuando no lo es.

        El envio byte a byte era obligatorio mientras CHAT.EXE recibia
        por sondeo: la UART del 286 no tiene FIFO, algunos adaptadores
        USB-serie sueltan los primeros bytes en rafaga, y un byte no
        leido a tiempo se perdia. Ahora el 286 recibe por interrupciones
        y guarda en un buffer de 4 KB, asi que la rafaga ya no molesta y
        el freno solo costaba tiempo: con CHAR_DELAY = 0.003 el caudal
        real eran ~330 bytes/s pasara lo que pasara con el baudrate.

        Se deja el camino lento porque no cuesta nada mantenerlo y es la
        vuelta atras si algun dia hay que hablar con un CHAT.EXE viejo.
        """
        if config.CHAR_DELAY <= 0:
            self.ser.write(data)
            return

        for b in data:
            self.ser.write(bytes((b,)))
            time.sleep(config.CHAR_DELAY)

    def write_line(self, texto: str = "") -> None:
        self._write_paced(texto.encode("cp437", errors="replace") + b"\r\n")
        if config.LINE_DELAY > 0:
            time.sleep(config.LINE_DELAY)

    def print(self, texto: str = "") -> None:
        """Manda texto tal cual, linea a linea, sin reformatear."""
        if texto == "":
            self.write_line("")
            return
        for linea in texto.splitlines():
            self.write_line(linea)

    def print_wrapped(self, texto: str) -> None:
        """Manda texto ajustandolo al ancho de pantalla, sin paginar."""
        for linea in self._wrap(texto):
            self.write_line(linea)

    def _wrap(self, texto: str):
        salida = []
        for parrafo in texto.split("\n"):
            if not parrafo.strip():
                salida.append("")
                continue
            salida.extend(textwrap.wrap(parrafo, width=config.SCREEN_WIDTH) or [""])
        return salida

    # --------------------------------------------------------------- paginado

    def page(self, texto: str) -> None:
        """
        Envia texto largo troceado a SCREEN_WIDTH columnas, en bloques de
        LINES_PER_PAGE, esperando ENTER desde el 286 entre bloque y
        bloque (estilo 'more' de BBS). Escribir 0 corta el volcado.
        """
        lineas = self._wrap(texto)
        total = len(lineas)

        for i in range(0, total, config.LINES_PER_PAGE):
            for linea in lineas[i:i + config.LINES_PER_PAGE]:
                self.write_line(linea)

            if i + config.LINES_PER_PAGE >= total:
                break

            self.write_line("-- MAS (ENTER para seguir, 0 para cortar) --")
            if self.wait_line() == "0":
                self.write_line("(cortado)")
                return

    # ----------------------------------------------------------------- marcos

    def caja(self, titulo: str, lineas, pie: str = None) -> None:
        """Dibuja un marco de doble linea CP437 con titulo y contenido."""
        ancho = config.BOX_WIDTH
        interior = ancho - 2

        self.write_line(ESQ_SI + BORDE_H * interior + ESQ_SD)
        self.write_line(BORDE_V + f" {titulo}"[:interior].ljust(interior) + BORDE_V)
        self.write_line(CONECTOR_I + BORDE_H * interior + CONECTOR_D)

        for linea in lineas:
            self.write_line(BORDE_V + f" {linea}"[:interior].ljust(interior) + BORDE_V)

        if pie is not None:
            self.write_line(CONECTOR_I + BORDE_H * interior + CONECTOR_D)
            self.write_line(BORDE_V + f" {pie}"[:interior].ljust(interior) + BORDE_V)

        self.write_line(ESQ_II + BORDE_H * interior + ESQ_ID)

    def titulo(self, texto: str) -> None:
        """
        Cabecera ligera para las pantallas de resultado.

        Se pasa a mayusculas solo si el resultado sigue existiendo en
        CP437. CP437 tiene las minusculas acentuadas (a, e, i, o, u) y
        la ene, pero de las mayusculas solo trae E, N, C y las del
        aleman; A, I, O y U acentuadas no existen. Un titular de prensa
        en espanol como "Reforma de la Gran Via" se convertiria en
        "GRAN V?A" al codificar. Cuando pasa eso se deja tal cual vino,
        que se lee peor de cabecera pero se lee.
        """
        encabezado = texto.upper()
        try:
            encabezado.encode("cp437")
        except UnicodeEncodeError:
            encabezado = texto

        self.write_line("")
        self.write_line(encabezado)
        self.write_line("-" * min(len(encabezado), config.SCREEN_WIDTH))

    def aviso(self, texto: str) -> None:
        self.write_line(f"[{texto}]")

    # -------------------------------------------------------------- preguntas

    def ask(self, prompt: str) -> str:
        """Pregunta y espera respuesta (puede volver cadena vacia)."""
        self.write_line(prompt)
        return self.wait_line()

    def pausa(self, texto: str = "Pulsa ENTER para volver...") -> None:
        self.write_line("")
        self.write_line(texto)
        self.wait_line()

    def menu(self, titulo: str, opciones, pie: str = None, fijas=None) -> str:
        """
        Pinta un menu y espera una opcion valida.

        'opciones' es una lista de tuplas (clave, etiqueta). Devuelve la
        clave elegida en mayusculas. Un ENTER a secas repinta el menu
        (util cuando el 286 arranca CHAT.EXE despues del broker y se ha
        perdido el menu inicial); cualquier otra cosa avisa sin repintar
        el marco entero, que cuesta lo suyo en el cable.

        Si hay mas opciones de las que caben en la ventana del 286, el
        menu se parte en paginas y se navega con S (siguiente) y A
        (anterior). Sin esto, los 17 canales autonomicos de Europa Press
        se saldrian por arriba y la mitad de la lista ya no estaria en
        pantalla justo cuando toca elegir.

        'fijas' son opciones que salen en TODAS las paginas: el "0.
        Volver" tiene que ir aqui, no en 'opciones'. Si se pagina y el
        volver es una opcion mas, acaba solo en la ultima pagina y desde
        la primera no hay forma de salir sin recorrerselas todas.

        Aviso para quien anada menus: en un menu que pagine, las claves
        S y A quedan reservadas. Los menus largos los genera el propio
        broker con claves numericas, asi que hoy no choca con nada.
        """
        opciones = list(opciones)
        fijas = list(fijas or [])

        # Cuentas de altura: la zona de contenido de CHAT.EXE son 18
        # filas y el marco se lleva seis (borde, titulo, separador,
        # separador del pie, pie y borde de abajo), asi que MENU_MAX_
        # OPCIONES lineas de opciones es lo que cabe sin desbordar.
        hueco = config.MENU_MAX_OPCIONES - len(fijas)

        if len(opciones) <= hueco:
            return self._menu_pagina(titulo, opciones + fijas, pie)

        # Al paginar hay que reservar sitio para S y A, que ocupan linea
        # igual que cualquier otra opcion.
        por_pagina = max(1, hueco - 2)
        paginas = [opciones[i:i + por_pagina]
                   for i in range(0, len(opciones), por_pagina)]
        actual = 0

        while True:
            navegacion = []
            if actual < len(paginas) - 1:
                navegacion.append(("S", "Siguiente pagina"))
            if actual > 0:
                navegacion.append(("A", "Pagina anterior"))

            pie_pagina = f"Pagina {actual + 1} de {len(paginas)}"
            if pie:
                pie_pagina = f"{pie}  ({pie_pagina})"

            sel = self._menu_pagina(
                titulo, list(paginas[actual]) + navegacion + fijas, pie_pagina)

            if sel == "S" and actual < len(paginas) - 1:
                actual += 1
            elif sel == "A" and actual > 0:
                actual -= 1
            else:
                return sel

    def _menu_pagina(self, titulo: str, opciones, pie: str = None) -> str:
        """Una sola pantalla de menu. La paginacion la pone menu()."""
        claves = {c.upper() for c, _ in opciones}
        lineas = [f"  {c}. {etiqueta}" for c, etiqueta in opciones]

        self.caja(titulo, lineas, pie)
        while True:
            sel = self.wait_line().upper()
            if sel in claves:
                return sel
            if sel == "":
                self.caja(titulo, lineas, pie)
                continue
            self.write_line(f"Opcion no valida: '{sel}'. Pulsa ENTER para ver el menu.")
