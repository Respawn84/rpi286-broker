#!/usr/bin/env bash
#
# poner_hora.sh -- Pone en hora la placa sin depender de HTTPS.
#
# El problema que resuelve es el huevo y la gallina de una placa sin
# pila de reloj (la Orange Pi y la Raspberry no la tienen): al arrancar
# puede estar en 1970, y con la fecha mal TODA conexion TLS falla con
# "certificate is not yet valid". Eso deja fuera a apt, git, la API de
# Claude y Telegram a la vez, asi que no se puede arreglar descargando
# nada. Hay que poner la hora con algo que no use TLS.
#
# Dos fuentes, en este orden:
#
#   1. La cabecera Date de una peticion HTTP normal, sin cifrar. Da la
#      hora al segundo, que sobra para que los certificados vuelvan a
#      validar. Es lo unico que funciona cuando el reloj esta tan mal
#      que ni el propio NTP arranca a tiempo.
#   2. NTP (systemd-timesyncd), que va por UDP y le da igual la hora
#      que lleves puesta. Es el que deja el reloj fino y lo mantiene.
#
# Y si hay RTC, se le escribe la hora buena de paso: sin pila no la
# guarda con el equipo apagado, pero si entre reinicios calientes.
#
# Uso:
#     sudo ./poner_hora.sh            a mano, hablando
#     sudo ./poner_hora.sh --auto     para el timer de systemd
#
# En modo --auto no toca nada si el reloj ya esta sincronizado por NTP
# o si el desvio es de pocos segundos: asi se puede lanzar cada cinco
# minutos sin pelearse con systemd-timesyncd, que es mas preciso que
# una cabecera HTTP (un segundo de resolucion). Y como al arrancar la
# red puede tardar en estar lista, reintenta un rato antes de rendirse.
#
# No necesita nada instalado: usa curl o wget si los hay y, si no,
# habla HTTP con /dev/tcp de bash.

set -uo pipefail

AUTO=0
[[ "${1:-}" == "--auto" ]] && AUTO=1

# Desvio por debajo del cual no merece la pena tocar el reloj en modo
# automatico: la cabecera HTTP solo da el segundo, asi que corregir por
# menos de esto es empeorar lo que haya hecho el NTP.
UMBRAL_SEGUNDOS=5
# Rondas de reintento en modo automatico, y espera entre ellas. Cubre
# el minuto y medio que puede tardar la wifi en levantar al arrancar.
RONDAS_AUTO=4
ESPERA_AUTO=15

# Por http:// a proposito: si usaramos https volveriamos al problema
# que venimos a resolver. Solo se lee la cabecera Date de la respuesta,
# no el contenido, asi que da igual lo que sirvan estos hosts.
HOSTS=(deb.debian.org www.google.com 1.1.1.1)

rojo()  { printf '\033[31m%s\033[0m\n' "$*"; }
verde() { printf '\033[32m%s\033[0m\n' "$*"; }
info()  { printf '  %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
    rojo "Hay que ejecutarlo con sudo:  sudo $0"
    exit 1
fi

# ------------------------------------------------- leer la hora por HTTP

fecha_con_curl() {
    curl -sI --max-time 8 "http://$1" 2>/dev/null \
        | awk -F': ' 'tolower($1)=="date"{print $2; exit}' | tr -d '\r'
}

fecha_con_wget() {
    wget -q -S --timeout=8 --tries=1 -O /dev/null "http://$1" 2>&1 \
        | awk -F': ' 'tolower($1)~/date$/{print $2; exit}' | tr -d '\r'
}

fecha_con_bash() {
    # Ultimo recurso, sin ningun programa externo: HTTP a mano sobre el
    # /dev/tcp de bash. El read lleva timeout para no quedarse colgado
    # si el host no contesta.
    local host=$1 linea
    exec 3<>"/dev/tcp/$host/80" 2>/dev/null || return 1
    printf 'HEAD / HTTP/1.0\r\nHost: %s\r\nConnection: close\r\n\r\n' "$host" >&3
    while IFS= read -t 8 -r linea <&3; do
        linea=${linea%$'\r'}
        [[ -z "$linea" ]] && break
        if [[ ${linea,,} == date:* ]]; then
            printf '%s\n' "${linea#*: }"
            exec 3<&- 3>&-
            return 0
        fi
    done
    exec 3<&- 3>&-
    return 1
}

leer_fecha_http() {
    local metodo host fecha

    # Se elige el metodo una vez y se prueban los hosts con el, en vez
    # de probar las tres formas con cada host: si el primero no
    # contesta, lo que falla es la red, no el programa.
    if command -v curl >/dev/null 2>&1; then
        metodo=fecha_con_curl
    elif command -v wget >/dev/null 2>&1; then
        metodo=fecha_con_wget
    else
        metodo=fecha_con_bash
    fi

    for host in "${HOSTS[@]}"; do
        fecha="$("$metodo" "$host")" || true
        if [[ -n "${fecha:-}" ]]; then
            printf '%s\n' "$fecha"
            return 0
        fi
    done
    return 1
}

# ------------------------------------------------------------- aplicarla

# En automatico, si el NTP ya ha sincronizado no hay nada que hacer:
# systemd-timesyncd es mas preciso que esto y ademas mantiene el reloj.
if (( AUTO )) && command -v timedatectl >/dev/null 2>&1; then
    if [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" == "yes" ]]; then
        exit 0
    fi
fi

if (( ! AUTO )); then
    echo "Hora actual del sistema: $(date)"
    echo
fi

FECHA=""
RONDAS=1
(( AUTO )) && RONDAS=$RONDAS_AUTO

for ((ronda = 1; ronda <= RONDAS; ronda++)); do
    FECHA="$(leer_fecha_http || true)"
    [[ -n "${FECHA:-}" ]] && break
    if (( ronda < RONDAS )); then
        # Tipico al arrancar: el timer salta antes de que la wifi este
        # lista. Se espera y se vuelve a probar.
        info "Sin red todavia; reintento en ${ESPERA_AUTO}s ($ronda/$RONDAS)."
        sleep "$ESPERA_AUTO"
    fi
done

if [[ -z "${FECHA:-}" ]]; then
    rojo "No he podido leer la hora por HTTP."
    info "Revisa que haya red (ip a, ping -c1 1.1.1.1) y vuelve a probar."
    info "Si hay red pero no DNS, prueba: sudo date -s 'AAAA-MM-DD HH:MM:SS'"
    exit 1
fi

# En automatico, no corregir desvios minimos.
if (( AUTO )); then
    EPOCH_RED="$(date -d "$FECHA" +%s 2>/dev/null || echo 0)"
    if [[ "$EPOCH_RED" != 0 ]]; then
        DESVIO=$(( EPOCH_RED - $(date +%s) ))
        if (( DESVIO > -UMBRAL_SEGUNDOS && DESVIO < UMBRAL_SEGUNDOS )); then
            # El reloj ya esta bien; solo se asegura el NTP y se sale.
            command -v timedatectl >/dev/null 2>&1 \
                && timedatectl set-ntp true 2>/dev/null || true
            exit 0
        fi
        echo "Desvio detectado: ${DESVIO} s. Corrigiendo."
    fi
fi

# La cabecera Date viene en GMT y lo dice en la propia cadena, asi que
# date la interpreta bien sea cual sea la zona horaria de la placa.
if ! date -s "$FECHA" >/dev/null; then
    rojo "La fecha que he leido no me vale: '$FECHA'"
    exit 1
fi

verde "Hora puesta por HTTP: $(date)"

# ------------------------------------------- y ahora el NTP, que la afina

if command -v timedatectl >/dev/null 2>&1; then
    timedatectl set-ntp true 2>/dev/null || true
    # Con el reloj ya en el siglo correcto, timesyncd sincroniza en
    # segundos; se reinicia para que no espere a su proximo intento.
    systemctl restart systemd-timesyncd 2>/dev/null || true
    sleep 3
    if (( ! AUTO )); then
        echo
        timedatectl | sed 's/^/  /'
    fi
fi

# El RTC sin pila no guarda la hora con el equipo apagado, pero si
# sobrevive a un reinicio caliente, asi que escribirla es gratis.
if [[ -e /dev/rtc0 || -e /dev/rtc ]] && command -v hwclock >/dev/null 2>&1; then
    hwclock -w 2>/dev/null && info "Hora escrita tambien en el RTC."
fi

# Y si esta fake-hwclock (el apano para placas sin pila: guarda la hora
# en un fichero y la restaura al arrancar), se le deja la hora buena
# para que el proximo arranque no empiece en 1970.
if command -v fake-hwclock >/dev/null 2>&1; then
    fake-hwclock save 2>/dev/null && info "Hora guardada en fake-hwclock."
fi

if (( ! AUTO )); then
    echo
    verde "Listo. Ya se puede usar apt, git y las APIs."
else
    verde "Reloj puesto en hora: $(date)"
fi
