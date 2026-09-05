#!/usr/bin/env python3
"""
noticias.py -- Titulares de Europa Press por RSS, sin pasar por la IA.

Por que RSS y no Claude, que es lo que habia antes: las noticias las
escribe una redaccion, no un modelo. Pidiendoselas a la IA con busqueda
web se pagaban 15-20 segundos y una llamada por consulta para acabar
con un resumen de segunda mano, sin fecha fiable y sin forma de saber
de donde salia cada cosa. El RSS da el titular tal cual lo publico el
medio, con su hora, gratis y en un segundo.

Es la misma decision que se tomo con las cotizaciones (ver mercados.py):
para datos, una fuente de datos; a la IA se le pregunta el porque, no el
que.

La estructura del menu no la inventamos: viene del OPML que publica
Europa Press, que es un indice de todos sus feeds ya agrupado por
temas (Secciones Principales, Actualidad Autonomica, Lenguas,
Innovacion). Se lee en caliente, asi que si manana anaden una seccion
aparece sola en el 286 sin tocar codigo.

    https://www.europapress.es/rss/europapress.opml.xml

Solo libreria estandar (urllib + ElementTree): en la Raspberry no hay
que instalar nada.
"""

import html
import re
import socket
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import config
import emojis

# El mismo User-Agent generico corto que en mercados.py. Ver alli la
# explicacion larga: prometer ser un Chrome sin mandar las cabeceras
# que manda Chrome de verdad es lo que hace que te frenen.
CABECERAS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "*/*",
}

# El indice de feeds cambia como mucho cada varios meses, asi que se
# guarda en memoria y no se vuelve a pedir en toda la sesion salvo que
# pase OPML_CACHE. Los feeds en si cambian cada pocos minutos y tienen
# su propia cache, mas corta.
_cache_opml = None          # (momento, [Grupo, ...])
_cache_feeds = {}           # xml_url -> (momento, [articulo, ...])


class NoticiasError(Exception):
    """No se ha podido leer el indice o un feed."""


class Grupo:
    """Un grupo del OPML: 'Actualidad Autonomica' y sus 17 feeds."""

    def __init__(self, nombre, feeds):
        self.nombre = nombre
        self.feeds = feeds          # lista de Feed


class Feed:
    """Un canal concreto: 'Madrid' -> su URL de RSS."""

    def __init__(self, nombre, url):
        self.nombre = nombre
        self.url = url


# --------------------------------------------------------------------------
# Descarga
# --------------------------------------------------------------------------

def _descargar(url: str, timeout: int) -> bytes:
    peticion = urllib.request.Request(url, headers=CABECERAS)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise NoticiasError(f"el servidor responde {e.code} {e.reason}")
    except urllib.error.URLError as e:
        raise NoticiasError(f"no se puede conectar: {e.reason}")
    except socket.timeout:
        raise NoticiasError(f"la peticion ha tardado mas de {timeout} s")
    except OSError as e:
        raise NoticiasError(f"error de red: {e}")


# --------------------------------------------------------------------------
# Limpieza de texto para el 286
# --------------------------------------------------------------------------

_TAGS = re.compile(r"<[^>]+>")
_ESPACIOS = re.compile(r"\s+")


def _limpiar(texto: str) -> str:
    """
    Deja un trozo de RSS listo para mandarlo por el cable.

    Los feeds traen HTML dentro de las descripciones (enlaces, <p>,
    imagenes) y entidades como &amp; o &#8220;. Nada de eso se puede
    pintar en modo texto, asi que se quita el marcado, se resuelven las
    entidades y se pasa por emojis.traducir(), que es quien sabe cambiar
    las comillas tipograficas y las rayas largas de los teletipos por
    algo que exista en CP437.

    Las entidades se resuelven ANTES de quitar etiquetas: al reves, un
    &lt;b&gt; escrito como entidad se convertiria en <b> y desapareceria
    en el paso siguiente, comiendose texto de verdad.
    """
    if not texto:
        return ""
    texto = html.unescape(texto)
    texto = _TAGS.sub(" ", texto)
    texto = _ESPACIOS.sub(" ", texto).strip()
    return emojis.traducir(texto)


def _fecha(pub_date: str) -> str:
    """'Fri, 05 Sep 2025 18:00:00 +0200' -> '05/09 18:00'."""
    if not pub_date:
        return ""
    try:
        return parsedate_to_datetime(pub_date).strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return ""


# --------------------------------------------------------------------------
# El indice de feeds (OPML)
# --------------------------------------------------------------------------

def _parsear_opml(datos: bytes):
    """
    Saca los grupos del OPML.

    El formato anida un <outline> de grupo (sin xmlUrl) con los feeds
    dentro (con xmlUrl). Algun feed podria venir suelto en la raiz, sin
    grupo: esos se juntan en uno llamado "Otros" en vez de perderlos.
    """
    try:
        raiz = ET.fromstring(datos)
    except ET.ParseError as e:
        raise NoticiasError(f"el indice de feeds no se entiende: {e}")

    cuerpo = raiz.find("body")
    if cuerpo is None:
        raise NoticiasError("el indice de feeds viene sin body")

    grupos = []
    sueltos = []

    for nodo in cuerpo.findall("outline"):
        nombre = _limpiar(nodo.get("text") or nodo.get("title") or "")

        if nodo.get("xmlUrl"):
            sueltos.append(Feed(nombre, nodo.get("xmlUrl")))
            continue

        feeds = []
        for hijo in nodo.findall("outline"):
            url = hijo.get("xmlUrl")
            if not url:
                continue
            etiqueta = _limpiar(hijo.get("text") or hijo.get("title") or url)
            feeds.append(Feed(etiqueta, url))

        if feeds:
            grupos.append(Grupo(nombre or "Sin nombre", feeds))

    if sueltos:
        grupos.append(Grupo("Otros", sueltos))

    if not grupos:
        raise NoticiasError("el indice de feeds ha venido vacio")

    return grupos


def grupos(forzar: bool = False):
    """Los grupos de feeds, del OPML. Cacheado en memoria."""
    global _cache_opml

    if not forzar and _cache_opml:
        momento, valor = _cache_opml
        if time.time() - momento < config.NOTICIAS_OPML_CACHE:
            return valor

    datos = _descargar(config.NOTICIAS_OPML, config.NOTICIAS_TIMEOUT)
    valor = _parsear_opml(datos)
    _cache_opml = (time.time(), valor)
    return valor


# --------------------------------------------------------------------------
# Los articulos de un feed
# --------------------------------------------------------------------------

def _parsear_rss(datos: bytes):
    try:
        raiz = ET.fromstring(datos)
    except ET.ParseError as e:
        raise NoticiasError(f"el feed no se entiende: {e}")

    articulos = []
    # findall(".//item") y no channel/item: algunos feeds meten los
    # items un nivel mas abajo de lo esperado y asi da igual.
    for item in raiz.findall(".//item"):
        titulo = _limpiar(item.findtext("title") or "")
        if not titulo:
            continue
        articulos.append({
            "titulo": titulo,
            "resumen": _limpiar(item.findtext("description") or ""),
            "fecha": _fecha(item.findtext("pubDate") or ""),
            "enlace": (item.findtext("link") or "").strip(),
        })
        if len(articulos) >= config.NOTICIAS_MAX_ARTICULOS:
            break

    if not articulos:
        raise NoticiasError("este canal no trae ninguna noticia ahora mismo")

    return articulos


def articulos(url: str, forzar: bool = False):
    """
    Los titulares de un feed. Cacheado unos minutos: volver atras en el
    menu y entrar otra vez no deberia costar otra descarga.
    """
    if not forzar and url in _cache_feeds:
        momento, valor = _cache_feeds[url]
        if time.time() - momento < config.NOTICIAS_CACHE:
            return valor

    datos = _descargar(url, config.NOTICIAS_TIMEOUT)
    valor = _parsear_rss(datos)
    _cache_feeds[url] = (time.time(), valor)
    return valor
