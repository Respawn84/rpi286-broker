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

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import config

API_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
API_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"

# Yahoo responde 403 a los clientes que no mandan User-Agent de navegador.
CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "application/json",
}


class MercadoError(Exception):
    """No se ha podido consultar la cotizacion."""


# --------------------------------------------------------------------------
# Acceso a la API
# --------------------------------------------------------------------------

def _pedir(url: str, params: dict) -> dict:
    peticion = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params), headers=CABECERAS)
    try:
        with urllib.request.urlopen(peticion, timeout=config.MERCADOS_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise MercadoError(f"el servidor de mercados responde {e.code}")
    except (urllib.error.URLError, socket.timeout):
        raise MercadoError("sin respuesta del servidor de mercados")
    except ValueError:
        raise MercadoError("respuesta ilegible del servidor de mercados")


def cotizacion(simbolo: str, etiqueta: str = None) -> dict:
    """
    Precio y variacion del dia de un simbolo de Yahoo.

    Devuelve un diccionario con lo justo para pintar una linea de la
    tabla. El 'tipo' (EQUITY / INDEX / CRYPTOCURRENCY / CURRENCY) es lo
    que decide luego cuantos decimales y que unidad se ensenan.
    """
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

    return {
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


def lista(valores) -> list:
    """
    Cotizaciones de una lista de pares (simbolo, etiqueta).

    Un valor que falle no tumba el cuadro entero: vuelve con la clave
    'error' puesta y su linea de la tabla dira "sin datos".
    """
    filas = []
    for simbolo, etiqueta in valores:
        try:
            filas.append(cotizacion(simbolo, etiqueta))
        except MercadoError as e:
            filas.append({"etiqueta": etiqueta, "simbolo": simbolo, "error": str(e)})
    return filas


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


def cuadro(titulo: str, valores) -> list:
    """Cabecera y una linea por valor. Devuelve la lista de lineas."""
    lineas = [titulo.upper(), "-" * len(titulo)]
    lineas.extend(linea_tabla(fila) for fila in lista(valores))
    return lineas


def pie() -> str:
    """Aviso de la hora: los datos gratuitos van con retraso."""
    return (f"Datos de Yahoo Finance a las {time.strftime('%H:%M')}, "
            "pueden llevar 15 min de retraso.")
