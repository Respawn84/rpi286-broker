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
    rm -f "$DESTINO"
    systemctl daemon-reload
    verde "Servicio desinstalado. El broker ya no arranca solo."
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

# El puerto serie integrado de la Pi lo ocupa por defecto una consola de
# login; el conversor USB (ttyUSB*) no tiene ese problema.
if [[ "$PUERTO" == *ttyAMA* || "$PUERTO" == *serial0* ]]; then
    rojo "AVISO: $PUERTO es el puerto serie integrado de la Pi."
    info "Desactiva antes la consola serie o se pelearan por el puerto:"
    info "  sudo systemctl disable --now serial-getty@ttyAMA0.service"
    info "  y quita 'console=serial0,115200' de /boot/firmware/cmdline.txt"
fi

# ----------------------------------------------------------------- instalacion

sed -e "s|@USUARIO@|$USUARIO|g" \
    -e "s|@DIR@|$DIR|g" \
    -e "s|@PYTHON@|$PYTHON|g" \
    -e "s|@DEVUNIT@|$DEVUNIT|g" \
    "$PLANTILLA" > "$DESTINO"

systemctl daemon-reload
systemctl enable "$SERVICIO"

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
