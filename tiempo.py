#!/usr/bin/env python3
"""
tiempo.py -- Prevision de AEMET para cualquier municipio de Espana.

Antes esta seccion le preguntaba a Claude con busqueda web: 15-20
segundos, una llamada de API por consulta y unos numeros que salian de
la pagina que le tocara leer. AEMET publica la prevision oficial a siete
dias en XML, gratis y sin clave. Es la misma decision de siempre en este
proyecto: para datos, una fuente de datos.

Como se localiza un municipio
-----------------------------
AEMET publica un XML por municipio en una URL con el codigo INE de cinco
digitos (dos de provincia, tres de municipio):

    https://www.aemet.es/xml/municipios/localidad_22035.xml   -> Aren

Ese codigo esta en la tabla de municipios de la AEAT que hay al lado de
este fichero, en la SEGUNDA columna. Cuidado con esto, que es la trampa
del formato:

    22 22035 22044 AREN

La tercera columna es OTRO codigo y no sirve: para Aren vale 22044, que
en AEMET es Bailo. Coinciden en muchos municipios, que es justo lo que
lo hace peligroso. Comprobado contra AEMET sobre una muestra al azar: la
segunda columna acierta siempre, la tercera falla en cuanto las dos
difieren (devuelve otro municipio o un 404).

Solo libreria estandar: en la Raspberry no hay que instalar nada.
"""

import re
import socket
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

import config

CABECERAS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "*/*",
}

URL_MUNICIPIO = "https://www.aemet.es/xml/municipios/localidad_{codigo}.xml"

# Los dos primeros digitos del codigo INE son la provincia. La tabla de
# la AEAT no trae el nombre, solo el numero, y hace falta para distinguir
# los muchos municipios que se llaman igual en provincias distintas.
PROVINCIAS = {
    "01": "Alava",          "02": "Albacete",     "03": "Alicante",
    "04": "Almeria",        "05": "Avila",        "06": "Badajoz",
    "07": "Baleares",       "08": "Barcelona",    "09": "Burgos",
    "10": "Caceres",        "11": "Cadiz",        "12": "Castellon",
    "13": "Ciudad Real",    "14": "Cordoba",      "15": "A Coruna",
    "16": "Cuenca",         "17": "Girona",       "18": "Granada",
    "19": "Guadalajara",    "20": "Guipuzcoa",    "21": "Huelva",
    "22": "Huesca",         "23": "Jaen",         "24": "Leon",
    "25": "Lleida",         "26": "La Rioja",     "27": "Lugo",
    "28": "Madrid",         "29": "Malaga",       "30": "Murcia",
    "31": "Navarra",        "32": "Ourense",      "33": "Asturias",
    "34": "Palencia",       "35": "Las Palmas",   "36": "Pontevedra",
    "37": "Salamanca",      "38": "S.C. Tenerife", "39": "Cantabria",
    "40": "Segovia",        "41": "Sevilla",      "42": "Soria",
    "43": "Tarragona",      "44": "Teruel",       "45": "Toledo",
    "46": "Valencia",       "47": "Valladolid",   "48": "Vizcaya",
    "49": "Zamora",         "50": "Zaragoza",     "51": "Ceuta",
    "52": "Melilla",
}

DIAS = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]

_municipios = None          # lista de dicts, cargada al primer uso
_cache = {}                 # codigo -> (momento, prevision)


class TiempoError(Exception):
    """No se ha podido consultar la prevision."""


# --------------------------------------------------------------------------
# La tabla de municipios
# --------------------------------------------------------------------------

def _sin_acentos(texto: str) -> str:
    """
    Para buscar: mayusculas y sin tildes.

    En el 286 no se pueden teclear acentos (CHAT.EXE solo acepta ASCII
    imprimible), asi que buscar "avila" tiene que encontrar "AVILA".
    """
    descompuesto = unicodedata.normalize("NFD", texto.upper())
    return "".join(c for c in descompuesto
                   if unicodedata.category(c) != "Mn")


def _variantes(nombre: str):
    """
    Formas por las que se puede buscar un municipio.

    La tabla escribe el articulo detras y entre parentesis: "NAVA (LA)",
    "BARCO DE AVILA (EL)". Nadie escribe eso en el 286, escribe "la nava"
    o directamente "nava", asi que se indexan las dos formas.
    """
    limpio = _sin_acentos(nombre)
    formas = {limpio}

    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", limpio)
    if m:
        cuerpo, articulo = m.group(1).strip(), m.group(2).strip()
        formas.add(cuerpo)
        formas.add(f"{articulo} {cuerpo}")

    return formas


def _cargar():
    """
    Lee la tabla de la AEAT una vez y la deja en memoria.

    Son unas 8.100 filas de ancho fijo; el fichero va en cp1252 (lo que
    escupe la AEAT) y no en UTF-8. Ocupa poco y se consulta muchas veces,
    asi que se carga entera en vez de releer el fichero en cada busqueda.
    """
    global _municipios
    if _municipios is not None:
        return _municipios

    ruta = config.municipios_file()
    if ruta is None:
        raise TiempoError(
            "no encuentro la tabla de municipios en la carpeta del broker")

    try:
        crudo = ruta.read_bytes().decode("cp1252")
    except OSError as e:
        raise TiempoError(f"no puedo leer {ruta.name}: {e}")

    municipios = []
    for linea in crudo.splitlines():
        if not linea.strip():
            continue
        campos = linea.split(None, 3)
        if len(campos) < 4:
            continue

        codigo = campos[1]
        nombre = campos[3].strip()

        # "00000" = municipio sin prevision publicada en AEMET.
        if not codigo.isdigit() or codigo == "00000" or not nombre:
            continue

        municipios.append({
            "codigo": codigo,
            "nombre": nombre,
            "provincia": PROVINCIAS.get(codigo[:2], "?"),
            "busqueda": _variantes(nombre),
        })

    if not municipios:
        raise TiempoError(f"{ruta.name} no tiene ninguna fila valida")

    _municipios = municipios
    return _municipios


def buscar(consulta: str):
    """
    Municipios cuyo nombre contiene 'consulta'.

    Ordenados por lo cerca que estan de lo que se ha escrito: primero el
    nombre exacto, luego los que empiezan igual y por ultimo los que solo
    lo contienen. Asi "madrid" saca Madrid antes que "Colmenar de
    Oreja"... y sobre todo antes que los veinte municipios que llevan
    "Madrid" en mitad del nombre.
    """
    texto = _sin_acentos(consulta).strip()
    if not texto:
        return []

    exactos, empiezan, contienen = [], [], []
    for m in _cargar():
        if texto in m["busqueda"]:
            exactos.append(m)
        elif any(f.startswith(texto) for f in m["busqueda"]):
            empiezan.append(m)
        elif any(texto in f for f in m["busqueda"]):
            contienen.append(m)

    orden = lambda x: (x["nombre"], x["provincia"])   # noqa: E731
    return (sorted(exactos, key=orden) + sorted(empiezan, key=orden)
            + sorted(contienen, key=orden))[:config.TIEMPO_MAX_RESULTADOS]


# --------------------------------------------------------------------------
# El XML de AEMET
# --------------------------------------------------------------------------

def _reparar_nombre(texto: str) -> str:
    """
    Arregla el nombre del municipio, que AEMET manda mal codificado.

    El XML declara ISO-8859-15 en la cabecera y casi todo el documento lo
    cumple, pero el campo <nombre> lleva bytes UTF-8 sin convertir. Se ve
    comparando los bytes crudos del mismo fichero:

        <productor> ... Meteorolog\\xed a       <- latin-1, correcto
        <nombre>    Ar\\xc3\\xa9n                 <- UTF-8 colado dentro

    Como el parser hace caso a la cabecera, "Aren" llega como "ArA©n".
    Deshacerlo es volver a bytes por latin-1 y releer como UTF-8. Si no
    cuela (municipio sin acentos, o el dia que AEMET lo arregle), se
    devuelve lo que habia: la reparacion nunca debe estropear un nombre
    que ya estaba bien.
    """
    try:
        return texto.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texto


def _periodo(dia, etiqueta: str):
    """
    Un dato del dia, buscando primero el resumen de 24 horas.

    AEMET reparte el dia de dos maneras distintas dentro del MISMO
    fichero, y hay que aguantar las dos:

    - Los cuatro primeros dias vienen troceados en tramos ('00-24',
      '00-12', '12-18'...). Ademas, el dia de HOY trae el '00-24' vacio,
      porque la jornada ya va empezada y solo se rellenan los tramos que
      quedan por delante.
    - Del quinto dia en adelante hay un solo bloque para toda la jornada
      y AEMET **quita el atributo periodo**. Filtrar por nombre de tramo
      los dejaba fuera, y los tres ultimos dias de la tabla salian sin
      cielo ni probabilidad de lluvia.

    Asi que: primero el resumen de 24 horas, luego los tramos de mas
    amplio a mas estrecho, y por ultimo cualquier nodo con datos, que es
    lo que recoge los dias sin 'periodo'.
    """
    def con_datos(nodo):
        return bool((nodo.text or "").strip()
                    or (nodo.get("descripcion") or "").strip())

    nodos = dia.findall(etiqueta)

    for periodo in ("00-24", "12-24", "00-12", "12-18", "06-12", "18-24", "00-06"):
        for nodo in nodos:
            if nodo.get("periodo") == periodo and con_datos(nodo):
                return nodo

    for nodo in nodos:
        if con_datos(nodo):
            return nodo
    return None


def _entero(texto):
    try:
        return int((texto or "").strip())
    except (TypeError, ValueError):
        return None


def _parsear(datos: bytes) -> dict:
    try:
        raiz = ET.fromstring(datos)
    except ET.ParseError as e:
        raise TiempoError(f"el XML de AEMET no se entiende: {e}")

    prediccion = raiz.find("prediccion")
    if prediccion is None:
        raise TiempoError("el XML viene sin prediccion")

    dias = []
    for dia in prediccion.findall("dia"):
        temperatura = dia.find("temperatura")
        cielo = _periodo(dia, "estado_cielo")
        lluvia = _periodo(dia, "prob_precipitacion")
        viento = None
        for nodo in dia.findall("viento"):
            direccion = (nodo.findtext("direccion") or "").strip()
            velocidad = (nodo.findtext("velocidad") or "").strip()
            if direccion and velocidad and direccion != "C":
                viento = (direccion, _entero(velocidad))
                break

        dias.append({
            "fecha": dia.get("fecha", ""),
            "cielo": (cielo.get("descripcion") or "").strip() if cielo is not None else "",
            "lluvia": _entero(lluvia.text) if lluvia is not None else None,
            "maxima": _entero(temperatura.findtext("maxima")) if temperatura is not None else None,
            "minima": _entero(temperatura.findtext("minima")) if temperatura is not None else None,
            "viento": viento,
        })

    if not dias:
        raise TiempoError("la prediccion ha venido vacia")

    return {
        "nombre": _reparar_nombre((raiz.findtext("nombre") or "").strip()),
        "provincia": (raiz.findtext("provincia") or "").strip(),
        "elaborado": (raiz.findtext("elaborado") or "").strip(),
        "dias": dias,
    }


def prevision(codigo: str, forzar: bool = False) -> dict:
    """La prevision a siete dias de un municipio. Cacheada un rato."""
    if not forzar and codigo in _cache:
        momento, valor = _cache[codigo]
        if time.time() - momento < config.TIEMPO_CACHE:
            return valor

    url = URL_MUNICIPIO.format(codigo=codigo)
    peticion = urllib.request.Request(url, headers=CABECERAS)
    try:
        with urllib.request.urlopen(peticion, timeout=config.TIEMPO_TIMEOUT) as r:
            datos = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise TiempoError("AEMET no publica prevision para ese municipio")
        raise TiempoError(f"AEMET responde {e.code} {e.reason}")
    except urllib.error.URLError as e:
        raise TiempoError(f"no se puede conectar con AEMET: {e.reason}")
    except socket.timeout:
        raise TiempoError(f"AEMET tarda mas de {config.TIEMPO_TIMEOUT} s")
    except OSError as e:
        raise TiempoError(f"error de red: {e}")

    valor = _parsear(datos)
    _cache[codigo] = (time.time(), valor)
    return valor


# --------------------------------------------------------------------------
# Presentacion para el 286
# --------------------------------------------------------------------------

def _dia_corto(fecha: str) -> str:
    """'2026-09-05' -> 'Sab 05/09'."""
    try:
        anio, mes, dia = (int(x) for x in fecha.split("-"))
    except (ValueError, AttributeError):
        return fecha[:9].ljust(9)

    nombre = DIAS[date(anio, mes, dia).weekday()]
    return f"{nombre} {dia:02d}/{mes:02d}"


def tabla(datos: dict):
    """
    La semana en una tabla que cabe en los 70 caracteres del 286.

        DIA        CIELO                                MIN/MAX  LLUV  VIENTO
        ---------------------------------------------------------------------
        Sab 05/09  Poco nuboso                           18/38    0%  S 10

    El ancho de la columna del cielo esta puesto para que quepan las
    descripciones largas de AEMET ("Intervalos nubosos con lluvia") sin
    partirlas: con menos sitio se cortaban justo en la parte que dice si
    llueve o no, que es lo que se va a mirar.
    """
    ancho_cielo = 34

    cabecera = f"DIA        {'CIELO'.ljust(ancho_cielo)} MIN/MAX  LLUV  VIENTO"
    lineas = [cabecera, "-" * len(cabecera)]

    for d in datos["dias"]:
        cielo = d["cielo"] or "-"
        if len(cielo) > ancho_cielo:
            cielo = cielo[:ancho_cielo - 3].rstrip() + "..."
        cielo = cielo.ljust(ancho_cielo)

        if d["minima"] is not None and d["maxima"] is not None:
            temps = f"{d['minima']:>3}/{d['maxima']:<3}"
        else:
            temps = "  -/-  "

        lluvia = f"{d['lluvia']:>3}%" if d["lluvia"] is not None else "   -"

        if d["viento"] and d["viento"][1] is not None:
            viento = f"{d['viento'][0]} {d['viento'][1]}"
        else:
            viento = "flojo"

        lineas.append(f"{_dia_corto(d['fecha']):<9}  {cielo} {temps} {lluvia}  {viento}")

    return lineas


def pie(datos: dict) -> str:
    elaborado = datos["elaborado"].replace("T", " ")[:16]
    return f"AEMET, elaborado {elaborado}. Velocidad del viento en km/h."
