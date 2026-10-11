#!/usr/bin/env python3
"""
system.py -- Funciones de sistema para el broker.

La idea es poder lanzar mandatos desde el 286 y que se ejecuten en el Raspberry.
"""

import os
import subprocess

def actualizar_hora():
    """
    Actualiza la hora del sistema desde la red. debría hacer algo como : date -s "$(curl -sI http://google.com | grep -i '^date:' | sed 's/date: //I')"
    """

    proceso = subprocess.run(['sudo', 'date', '-s', '"$(curl -sI http://google.com | grep -i \'^date:\' | sed \'s/date: //I\')"'], capture_output=True, text=True)
    salida = (proceso.stdout + proceso.stderr).strip()
    if proceso.returncode != 0:
        raise Exception(f"Error al actualizar la hora: {salida}")

    return salida

    