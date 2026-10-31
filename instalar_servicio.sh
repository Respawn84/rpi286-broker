#!/usr/bin/env bash
#
# instalar_servicio.sh -- Deja el broker arrancando solo en la Raspberry.
#
# Instala systemd/broker286.service rellenando la plantilla con el
# usuario, la ruta y el puerto reales de esta maquina. Ejecutar en la
# Raspberry (no en el Mac):
#
#     sudo ./instalar_servicio.sh
#
# Para quitarlo:  sudo ./instalar_servicio.sh --desinstalar

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLANTILLA="$DIR/systemd/broker286.service"
DESTINO="/etc/systemd/system/broker286.service"
SERVICIO="broker286.service"

# Segunda unidad, independiente del broker: el reloj. Ver la seccion
# del README sobre certificados; en una placa sin pila de RTC esto es
# lo que evita que un arranque en 1970 deje el cacharro incomunicado.
HORA_SERVICIO="poner-hora.service"
HORA_TIMER="poner-hora.timer"

rojo()  { printf '\033[31m%s\033[0m\n' "$*"; }
verde() { printf '\033[32m%s\033[0m\n' "$*"; }
info()  { printf '  %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
    rojo "Hay que ejecutarlo con sudo:  sudo $0"
    exit 1
fi

# ---------------------------------------------------------------- desinstalar

if [[ "${1:-}" == "--desinstalar" ]]; then
    systemctl disable --now "$SERVICIO" 2>/dev/null || true
    systemctl disable --now "$HORA_TIMER" 2>/dev/null || true
    rm -f "$DESTINO" \
          "/etc/systemd/system/$HORA_SERVICIO" \
          "/etc/systemd/system/$HORA_TIMER"
    systemctl daemon-reload
    verde "Servicios desinstalados. El broker ya no arranca solo"
    verde "y el reloj ya no se pone en hora por su cuenta."
    exit 0
fi

# ------------------------------------------------------------------ deteccion

USUARIO="${SUDO_USER:-$(id -un)}"
if [[ "$USUARIO" == "root" ]]; then
    rojo "No conviene correr el broker como root. Ejecuta el script con"
    rojo "sudo desde tu usuario normal, no desde una sesion de root."
    exit 1
fi

PYTHON="$(command -v python3 || true)"
if [[ -z "$PYTHON" ]]; then
    rojo "No encuentro python3."
    exit 1
fi

# El puerto se le pregunta al propio config.py para que la plantilla y
# el broker no puedan quedar descuadrados. Se hace importandolo con
# Python y no leyendolo con sed porque PORT ya no es un literal: sale
# de api.env si esta puesto ahi, y un sed no se entera de eso.
# config.py solo importa libreria estandar, asi que esto no necesita
# tener instaladas las dependencias del broker.
PUERTO="$("$PYTHON" -c "import sys; sys.path.insert(0, '$DIR'); import config; print(config.PORT)" 2>/dev/null)"
PUERTO="${PUERTO:-/dev/ttyUSB0}"

# Nombre de la unidad .device que corresponde a ese /dev/... Por ejemplo
# /dev/ttyUSB0 -> dev-ttyUSB0.device
DEVUNIT="$(systemd-escape -p --suffix=device "$PUERTO")"

echo
echo "Voy a instalar el servicio con esta configuracion:"
info "Usuario:   $USUARIO"
info "Carpeta:   $DIR"
info "Python:    $PYTHON"
info "Puerto:    $PUERTO  (unidad $DEVUNIT)"
echo

# ----------------------------------------------------------------- revisiones

if [[ ! -f "$DIR/api.env" ]]; then
    rojo "AVISO: no existe $DIR/api.env"
    info "El broker arrancara y saldra con error hasta que la crees:"
    info "  cp api.env.example api.env && nano api.env"
fi

if ! sudo -u "$USUARIO" "$PYTHON" -c "import serial, anthropic" 2>/dev/null; then
    rojo "AVISO: a $USUARIO le faltan dependencias de Python."
    info "  pip3 install pyserial anthropic --break-system-packages"
fi

if ! id -nG "$USUARIO" | tr ' ' '\n' | grep -qx dialout; then
    info "Anadiendo $USUARIO al grupo dialout (acceso al puerto serie)..."
    usermod -aG dialout "$USUARIO"
    info "Hecho. El cambio solo afecta a sesiones nuevas, pero el"
    info "servicio ya lo coge por SupplementaryGroups."
fi

# El puerto serie integrado de la placa lo ocupa por defecto una
# consola de login; el conversor USB (ttyUSB*) no tiene ese problema.
if [[ "$PUERTO" == *ttyAMA* || "$PUERTO" == *serial0* || "$PUERTO" == *ttyS[0-9]* ]]; then
    DISPOSITIVO="$(basename "$PUERTO")"
    rojo "AVISO: $PUERTO es el puerto serie integrado de la placa."
    info "Desactiva antes la consola serie o se pelearan por el puerto:"
    info "  sudo systemctl disable --now serial-getty@$DISPOSITIVO.service"
    info "Y quita la consola de los parametros de arranque:"
    if [[ -f /boot/armbianEnv.txt ]]; then
        info "  en Armbian, la linea console= de /boot/armbianEnv.txt"
    elif [[ -f /boot/firmware/cmdline.txt ]]; then
        info "  en Raspberry Pi OS, 'console=serial0,115200' de"
        info "  /boot/firmware/cmdline.txt"
    else
        info "  (no encuentro ni /boot/armbianEnv.txt ni"
        info "  /boot/firmware/cmdline.txt; mira la configuracion de"
        info "  arranque de tu distribucion)"
    fi
fi

# Brltty (lector braille) reclama varios conversores USB-serie, el
# PL2303 entre ellos, y hace que /dev/ttyUSB0 aparezca y desaparezca a
# los pocos segundos. Viene instalado en bastantes imagenes de escritorio.
if [[ "$PUERTO" == *ttyUSB* ]] && dpkg -s brltty >/dev/null 2>&1; then
    rojo "AVISO: brltty esta instalado y suele robar los conversores USB-serie."
    info "Si $PUERTO aparece y se va solo, quitalo:  sudo apt purge -y brltty"
fi

# ModemManager sondea los puertos serie al enchufarlos, y esos sondeos
# llegan al 286 como basura en pantalla.
if [[ "$PUERTO" == *ttyUSB* ]] && systemctl list-unit-files ModemManager.service >/dev/null 2>&1 \
   && systemctl is-enabled ModemManager.service >/dev/null 2>&1; then
    rojo "AVISO: ModemManager esta activo y sondea los puertos serie."
    info "  sudo systemctl mask --now ModemManager"
fi

# El reloj: sin pila de RTC, una placa recien encendida puede estar en
# 1970, y con la fecha mal falla todo lo que vaya por TLS (la API, git,
# Telegram). Mas vale decirlo aqui que dejar que el broker arranque y
# falle sin explicar por que.
if [[ "$(date +%Y)" -lt 2025 ]]; then
    rojo "AVISO: el reloj de esta placa marca $(date +%Y). Con la fecha mal"
    rojo "no validan los certificados y no funcionara nada que use red."
    info "Arreglalo antes de arrancar el broker:  sudo $DIR/poner_hora.sh"
fi

# ----------------------------------------------------------------- instalacion

sed -e "s|@USUARIO@|$USUARIO|g" \
    -e "s|@DIR@|$DIR|g" \
    -e "s|@PYTHON@|$PYTHON|g" \
    -e "s|@DEVUNIT@|$DEVUNIT|g" \
    "$PLANTILLA" > "$DESTINO"

# El reloj: un oneshot y un timer que lo lanza al arrancar y cada cinco
# minutos. Van aparte del broker a proposito; el reloj tiene que estar
# bien aunque el broker este parado o el cable desenchufado.
for UNIDAD in "$HORA_SERVICIO" "$HORA_TIMER"; do
    sed -e "s|@DIR@|$DIR|g" \
        "$DIR/systemd/$UNIDAD" > "/etc/systemd/system/$UNIDAD"
done

chmod +x "$DIR/poner_hora.sh" 2>/dev/null || true

systemctl daemon-reload
systemctl enable "$SERVICIO"
systemctl enable --now "$HORA_TIMER"

# fake-hwclock es la otra mitad del arreglo del reloj, y la que importa
# cuando la wifi no levanta sin hora: guarda la hora al apagar y la
# restaura al arrancar, asi la placa empieza en una fecha razonable en
# vez de en 1970 y los certificados validan desde el primer segundo.
if ! dpkg -s fake-hwclock >/dev/null 2>&1; then
    echo
    rojo "RECOMENDADO: instala fake-hwclock."
    info "Esta placa no tiene pila de reloj, asi que cada arranque"
    info "empieza en 1970 hasta que haya red. fake-hwclock guarda la"
    info "hora al apagar y la restaura al arrancar:"
    info "  sudo apt install -y fake-hwclock"
fi

if [[ -e "$PUERTO" ]]; then
    systemctl restart "$SERVICIO"
    sleep 2
    systemctl --no-pager --lines=0 status "$SERVICIO" || true
    echo
    verde "Servicio instalado y en marcha."
else
    echo
    verde "Servicio instalado."
    info "$PUERTO no esta conectado ahora mismo: el broker arrancara"
    info "solo en cuanto enchufes el conversor USB-serie."
fi

echo
echo "Comandos utiles:"
info "Ver el log en vivo:   journalctl -u $SERVICIO -f"
info "Parar / arrancar:     sudo systemctl stop|start $SERVICIO"
info "Tras tocar el codigo: sudo systemctl restart $SERVICIO"
info "Quitarlo del arranque: sudo $0 --desinstalar"
echo
echo "Y para el reloj:"
info "Cuando toca:          systemctl list-timers $HORA_TIMER"
info "Que paso la ultima:   journalctl -u $HORA_SERVICIO -n 20"
info "Ponerlo en hora ya:   sudo systemctl start $HORA_SERVICIO"
