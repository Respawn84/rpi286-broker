#!/usr/bin/env python3
"""
mercados.py -- Cotizaciones sacadas de una API publica, sin pasar por la IA.

Por que no la IA: pedirle a Claude que componga un cuadro de precios
sale caro, tarda 15-20 segundos y, sobre todo, no es fiable. Con la
busqueda web se cuela en la respuesta su propio proceso ("necesito el
precio exacto de AAPL para completar el cuadro...") y las cifras bailan
segun la pagina que le toque leer. Una API de datos devuelve un numero
y ya.

La fuente es el endpoint de graficos de Yahoo Finance:

    https://query1.finance.yahoo.com/v8/finance/chart/SAN.MC

No es una API oficial con contrato, pero no pide clave ni registro, va
por HTTPS y devuelve JSON, que es justo lo que necesitamos: en 'meta'
vienen precio, variacion del dia, moneda y nombre del valor. Sirve
igual para acciones, indices (^IBEX), cripto (BTC-EUR) y divisas
(EURUSD=X), asi que todo el cuadro se resuelve con una sola fuente.

Solo usa la libreria estandar (urllib + json): en la Raspberry no hay
que instalar nada nuevo.
"""

import http.cookiejar
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import config

API_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
API_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"
# Pedir esto una vez hace que Yahoo suelte sus cookies de sesion. No
# devuelve nada util (contesta 404), pero sin cookie la API empieza a
# responder 429 aunque no estes pidiendo casi nada.
URL_COOKIE = "https://fc.yahoo.com/"

# Yahoo responde 403 o 429 a los clientes que no mandan User-Agent de
# navegador.
CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "application/json",
}

# Un solo opener para todo el modulo, con su tarro de cookies. Asi las
# once peticiones del cuadro van como las once de un navegador que ya
# ha estado en la web, en vez de como once desconocidos seguidos.
_cookies = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookies))
_con_cookies = False

# Precios ya pedidos: simbolo -> (momento, fila). Abrir el menu de
# cotizaciones no deberia costar once peticiones nuevas si acabas de
# mirarlo hace un minuto; eso es justo lo que dispara el 429.
_cache = {}


class MercadoError(Exception):
    """No se ha podido consultar la cotizacion."""


# --------------------------------------------------------------------------
# Acceso a la API
# --------------------------------------------------------------------------

def _coger_cookies() -> None:
    """
    Primera visita, para que Yahoo nos de sus cookies.

    Contesta 404 y da igual: lo que interesa son las cabeceras
    Set-Cookie, que se quedan en _cookies y viajan en las siguientes
    peticiones. Si esto falla no se aborta nada, solo se intentara la
    consulta a pelo.
    """
    global _con_cookies
    _con_cookies = True
    try:
        peticion = urllib.request.Request(URL_COOKIE, headers=CABECERAS)
        _opener.open(peticion, timeout=config.MERCADOS_TIMEOUT).read()
    except Exception:
        pass


def _pedir(url: str, params: dict) -> dict:
    if not _con_cookies:
        _coger_cookies()

    peticion = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params), headers=CABECERAS)

    for intento in (1, 2):
        try:
            with _opener.open(peticion, timeout=config.MERCADOS_TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and intento == 1:
                # Nos han frenado. Se reintenta una vez, renovando las
                # cookies y esperando lo que digan (o un par de
                # segundos): insistir mas seria empeorarlo.
                espera = e.headers.get("Retry-After")
                time.sleep(min(int(espera), 10) if (espera or "").isdigit()
                           else config.MERCADOS_REINTENTO)
                _coger_cookies()
                continue
            raise MercadoError(f"el servidor responde {e.code} {e.reason}")
        except urllib.error.URLError as e:
            # El motivo de un URLError es lo mas util que hay aqui: dice
            # si es DNS, si no hay ruta o si ha fallado el certificado
            # (en una Pi sin RTC suele ser que va con la hora cambiada).
            raise MercadoError(f"no se puede conectar: {e.reason}")
        except socket.timeout:
            raise MercadoError(f"sin respuesta en {config.MERCADOS_TIMEOUT} s")
        except ValueError:
            raise MercadoError("respuesta ilegible del servidor de mercados")


def cotizacion(simbolo: str, etiqueta: str = None) -> dict:
    """
    Precio y variacion del dia de un simbolo de Yahoo.

    Devuelve un diccionario con lo justo para pintar una linea de la
    tabla. El 'tipo' (EQUITY / INDEX / CRYPTOCURRENCY / CURRENCY) es lo
    que decide luego cuantos decimales y que unidad se ensenan.
    """
    guardado = _cache.get(simbolo)
    if guardado and time.time() - guardado[0] < config.MERCADOS_CACHE:
        fila = dict(guardado[1])
        # La etiqueta no se cachea: el mismo simbolo puede pedirse desde
        # la lista (con su nombre de config.py) o suelto (con el de Yahoo).
        fila["etiqueta"] = etiqueta or fila["etiqueta"]
        return fila

    datos = _pedir(API_CHART + urllib.parse.quote(simbolo),
                   {"range": "1d", "interval": "1d"})

    resultado = (datos.get("chart") or {}).get("result")
    if not resultado:
        error = ((datos.get("chart") or {}).get("error") or {}).get("description")
        raise MercadoError(error or f"{simbolo}: valor desconocido")

    meta = resultado[0].get("meta") or {}
    precio = meta.get("regularMarketPrice")
    if precio is None:
        raise MercadoError(f"{simbolo}: sin precio")

    # regularMarketChangePercent no siempre viene; si falta se saca del
    # cierre anterior, que si esta siempre en el 'meta' del grafico.
    variacion = meta.get("regularMarketChangePercent")
    cierre = meta.get("chartPreviousClose") or meta.get("previousClose")
    if variacion is None and cierre:
        variacion = (precio - cierre) / cierre * 100

    fila = {
        "simbolo": meta.get("symbol") or simbolo,
        "etiqueta": etiqueta or meta.get("shortName") or simbolo,
        "nombre": meta.get("longName") or meta.get("shortName") or simbolo,
        "precio": float(precio),
        "moneda": meta.get("currency") or "",
        "variacion": variacion,
        "tipo": meta.get("instrumentType") or "",
        "hora": meta.get("regularMarketTime"),
        "maximo": meta.get("regularMarketDayHigh"),
        "minimo": meta.get("regularMarketDayLow"),
        "max52": meta.get("fiftyTwoWeekHigh"),
        "min52": meta.get("fiftyTwoWeekLow"),
        "cierre": cierre,
    }
    _cache[simbolo] = (time.time(), fila)
    return dict(fila)


def lista(valores) -> list:
    """
    Cotizaciones de una lista de pares (simbolo, etiqueta).

    Un valor que falle no tumba el cuadro entero: vuelve con la clave
    'error' puesta y su linea de la tabla dira "sin datos".
    """
    filas = []
    for numero, (simbolo, etiqueta) in enumerate(valores):
        # Un respiro entre peticion y peticion. Once seguidas a pelo son
        # justo lo que hace que Yahoo empiece a contestar 429, y a 9600
        # baudios estos segundos no se notan: el 286 tarda mucho mas en
        # pintar la tabla que nosotros en pedirla.
        if numero and simbolo not in _cache:
            time.sleep(config.MERCADOS_PAUSA)
        try:
            filas.append(cotizacion(simbolo, etiqueta))
        except MercadoError as e:
            # En el 286 solo cabe "sin datos", pero el motivo hace falta
            # para poder arreglarlo: al journal (journalctl -u broker286).
            print(f"[mercados] {simbolo}: {e}", file=sys.stderr)
            filas.append({"etiqueta": etiqueta, "simbolo": simbolo, "error": str(e)})
    return filas


def primer_error(filas) -> str:
    """El motivo del primer fallo, para poder ensenarlo en el 286."""
    for fila in filas:
        if fila.get("error"):
            return fila["error"]
    return ""


def buscar(texto: str) -> dict:
    """Busca un valor por nombre ("repsol") y devuelve el mejor simbolo."""
    datos = _pedir(API_SEARCH, {"q": texto, "quotesCount": 5, "newsCount": 0})
    for q in datos.get("quotes") or []:
        if q.get("symbol"):
            return {"simbolo": q["symbol"],
                    "nombre": q.get("longname") or q.get("shortname") or q["symbol"],
                    "mercado": q.get("exchDisp") or ""}
    raise MercadoError(f"no encuentro ningun valor que se llame '{texto}'")


# --------------------------------------------------------------------------
# Formato para la pantalla del 286
# --------------------------------------------------------------------------

# Columnas de la tabla, contadas sobre SCREEN_WIDTH. El numero se pega a
# la derecha de COL_NUMERO para que todas las cifras caigan alineadas
# aunque los nombres midan distinto.
COL_NUMERO = 44      # columna donde termina el precio
ANCHO_UNIDAD = 4     # "EUR", "pts", "USD"...
ANCHO_VARIACION = 8  # "-12,34%"


def _numero(valor: float, decimales: int) -> str:
    """Numero al estilo espanol: 19.779,00 (punto de millar, coma decimal)."""
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "@").replace(".", ",").replace("@", ".")


def _decimales(fila: dict) -> int:
    if fila.get("tipo") == "CURRENCY":
        return 4                      # un cambio EUR/USD se mira al cuarto decimal
    if fila["precio"] < 1:
        return 4                      # cripto pequena, centimos de dolar
    return 2


def _unidad(fila: dict) -> str:
    if fila.get("tipo") == "INDEX":
        return "pts"                  # un indice no cotiza en euros
    # En una divisa, 'moneda' es la de destino: EUR/USD a 1,1592 USD.
    return fila.get("moneda") or ""


def formatear_variacion(variacion) -> str:
    if variacion is None:
        return "n/d"
    return f"{variacion:+.2f}%".replace(".", ",")


def linea_tabla(fila: dict, ancho: int = None) -> str:
    """
    Una linea del cuadro, con puntos de relleno:

    IBEX 35.......................... 19.779,00 pts .......... -0,23%
    """
    ancho = ancho or config.SCREEN_WIDTH
    nombre = fila["etiqueta"]

    if fila.get("error"):
        # Se deja la linea puesta para que se vea que ese valor ha
        # fallado, en vez de que parezca que se ha olvidado.
        derecha = "sin datos"
        relleno = max(2, ancho - len(nombre) - len(derecha))
        return (nombre + "." * relleno + derecha)[:ancho]

    numero = _numero(fila["precio"], _decimales(fila))
    hueco = COL_NUMERO - len(nombre) - len(numero)
    if hueco < 2:                     # nombre largo: se recorta antes que descuadrar
        nombre = nombre[:max(1, COL_NUMERO - len(numero) - 2)]
        hueco = 2

    izquierda = (nombre + "." * hueco + numero + " "
                 + _unidad(fila).ljust(ANCHO_UNIDAD))
    var = formatear_variacion(fila.get("variacion"))
    relleno = max(1, ancho - len(izquierda) - ANCHO_VARIACION)
    return izquierda + "." * relleno + var.rjust(ANCHO_VARIACION)


def cuadro(titulo: str, valores) -> tuple:
    """
    Un bloque de la tabla: cabecera y una linea por valor.

    Devuelve (lineas, filas). Las filas van aparte de las lineas porque
    el broker necesita saber si ha fallado todo para poder decir por
    que, en vez de dejar una pantalla entera de "sin datos".
    """
    filas = lista(valores)
    lineas = [titulo.upper(), "-" * len(titulo)]
    lineas.extend(linea_tabla(fila) for fila in filas)
    return lineas, filas


def pie() -> str:
    """Aviso de la hora: los datos gratuitos van con retraso."""
    return (f"Datos de Yahoo Finance a las {time.strftime('%H:%M')}, "
            "pueden llevar 15 min de retraso.")
