# Broker v2 -- capa de menu para el 286

Puente serie entre `CHAT.EXE` (Intel 286, MS-DOS) y la Raspberry Pi,
con un menu navegable delante de la API de Claude.

## Que cambia respecto al v1

`broker_v1.py` mandaba a la API cualquier linea que llegara del 286.
`broker_v2.py` mete un menu delante: la conversacion libre pasa a ser
la opcion 6, y aparecen secciones con prompts preparados y
aplicaciones que se ejecutan en la propia Raspberry.

**El protocolo serie no cambia**: lineas de texto terminadas en CR LF,
9600 8N1. No hay que recompilar nada en el 286. `broker_v1.py` se deja
tal cual por si hace falta volver atras.

## Ficheros

| Fichero        | Que hace                                                   |
|----------------|------------------------------------------------------------|
| `broker_v2.py` | Bucle principal, menu y secciones                          |
| `terminal.py`  | Capa de pantalla/teclado sobre el puerto serie             |
| `ia.py`        | Cliente de la API de Claude (consultas sueltas y chat)     |
| `prompts.py`   | Prompts de cada seccion del menu                           |
| `mercados.py` | Cotizaciones via API publica (Yahoo Finance)                |
| `apps.py`      | Aplicaciones locales de la Raspberry                       |
| `actualizar.py`| git pull desde el menu Configuracion (opcion 7)            |
| `config.py`    | Toda la configuracion: puerto, ciudad, valores, modelo     |
| `simulador.py` | Prueba el menu en la consola, sin 286 ni cable             |
| `broker_v1.py` | Version anterior (eco directo a la API), intacta           |

## Uso

```bash
pip3 install pyserial anthropic --break-system-packages
cp api.env.example api.env      # y pon dentro tu ANTHROPIC_API_KEY
python3 broker_v2.py
```

Para probar sin el 286 (no necesita pyserial ni api.env):

```bash
python3 simulador.py
```

## El menu

```
1. Noticias Economicas          prompt + busqueda web
2. Noticias Politicas           prompt + busqueda web
3. Prevision del tiempo         ciudad de config.py u otra
4. Cotizaciones                 precios via API, sin pasar por la IA
5. Aplicaciones                 submenu, todo local en la Pi
6. Chat con Claude              el comportamiento del broker v1
7. Configuracion                actualizar el broker desde GitHub
0. Apagar la sesion
```

Aplicaciones (opcion 5): reloj para poner en hora el 286, calculadora,
conversor de unidades, bloc de notas guardado en la Pi, estado de la
Raspberry, adivina el numero y efemerides del dia.

## Cotizaciones (opcion 4): datos de API, no de la IA

Los precios los da [mercados.py](mercados.py) contra el endpoint
publico de graficos de Yahoo Finance (`query1.finance.yahoo.com`), que
no pide clave ni registro y solo necesita `urllib` de la libreria
estandar: en la Raspberry no hay que instalar nada.

Se hizo asi porque pedirle el cuadro a Claude no funcionaba: con la
busqueda web se colaba en la respuesta su propio proceso ("necesito el
precio exacto de AAPL para completar el cuadro..."), las cifras no
cuadraban entre si y cada consulta costaba dinero y 15-20 segundos.

La salida es una tabla con puntos de relleno, calculada para que todas
las cifras caigan en la misma columna dentro de los 70 caracteres de
`SCREEN_WIDTH`:

```
ACCIONES E INDICES
------------------
IBEX 35............................19.779,00 pts .............  -0,23%
Banco Santander........................12,71 EUR .............  +1,02%
```

El submenu tiene tres opciones:

1. **Mi lista**: los valores de `ACCIONES`, `CRYPTOS` y `DIVISAS` de
   `config.py`, ahora pares `(simbolo, nombre)`. El simbolo es el de
   Yahoo: `^IBEX` para indices, `.MC` para Madrid, `BTC-EUR` para
   cripto, `EURUSD=X` para divisas. Un valor que falle sale como
   "sin datos" y no tumba el resto del cuadro.
2. **Consultar un valor suelto**: acepta el simbolo (`AAPL`) o el
   nombre (`repsol`), que resuelve con el buscador de Yahoo, y ademas
   del precio da maximo y minimo del dia y de 52 semanas.
3. **Que ha pasado hoy en los mercados**: esta si es Claude, pero ya no
   le pedimos numeros, solo el porque del movimiento.

## Configuracion -> Actualizar Broker (opcion 7)

Para no tener que abrir un SSH cada vez que se toca el codigo. El flujo
es: `git push` desde el PC o el Mac, y en el 286 **Configuracion ->
Actualizar Broker**. La Raspberry hace el `git pull` sola y, si ha
entrado codigo nuevo, ofrece reiniciarse para aplicarlo.

Detalles que conviene saber:

- Se hace `git pull --ff-only` y, antes, se comprueba que no haya
  cambios locales. Si los hay, el broker se planta y avisa: un merge a
  ciegas no se puede resolver desde una pantalla de 286.
- El reinicio **no usa `sudo systemctl restart`**: el servicio corre con
  `NoNewPrivileges=true` y no puede escalar privilegios. En vez de eso
  el proceso sale con codigo 0 y `Restart=always` hace que systemd lo
  vuelva a levantar en `RestartSec` (5 s) ya con el codigo nuevo. Desde
  el 286 se ve como unos segundos de silencio; luego un ENTER repinta el
  menu.
- Si el broker se ha arrancado a mano (sin systemd) no hay quien lo
  relance, asi que en ese caso avisa y no se sale.
- La opcion 2 del submenu ensena rama, commit y fecha del codigo que
  esta corriendo, util para comprobar que la actualizacion ha entrado.
- La carpeta del repositorio es la del propio broker (`config.REPO_DIR`,
  que es donde estan estos ficheros); en la Raspberry de casa,
  `/home/daniel/286/rpi286-broker`.

Como el servicio lleva `ProtectHome=read-only` con `ReadWritePaths` a su
propia carpeta, el `git pull` puede escribir ahi y en ningun otro sitio.

Convenios de navegacion, iguales en todo el arbol:

- `0` vuelve al menu anterior.
- **ENTER a secas repinta el menu actual.** Importante: el broker manda
  el menu al arrancar, asi que si el 286 lanza `CHAT.EXE` despues, ese
  primer menu se pierde; basta con pulsar ENTER para recuperarlo.
- En los volcados largos, `ENTER` pasa de pagina y `0` corta.

## Detalles del enlace que conviene no romper

- **CHAT.EXE solo manda ASCII 32..126** ([chat.c](../Watcom/chat.c),
  filtro del bucle de teclado): al escribir desde el 286 no hay
  acentos. De vuelta si se puede usar **CP437 completo**, porque
  `rx_agregar_char` vuelca el byte directamente en la VRAM en modo
  texto; de ahi que los marcos de los menus se vean bien.
- **La UART del 286 no tiene FIFO** y se sondea sin interrupciones, asi
  que se sigue escribiendo byte a byte con `CHAR_DELAY`, mas un
  `LINE_DELAY` extra tras cada CR LF (el scroll de la ventana de
  CHAT.EXE es trabajo real que tarda). Ver los comentarios largos en
  `config.py`.
- **Un ENTER en vacio es un mensaje**: `CHAT.EXE` manda un CR LF suelto
  aunque el buffer de entrada este vacio. El v1 no lo distinguia de un
  timeout del puerto (los dos daban `b""`), asi que su "-- MAS (pulsa
  ENTER) --" no avanzaba nunca con un ENTER a secas. En el v2,
  `Terminal.read_line()` devuelve `None` para el timeout y `""` para el
  ENTER vacio, y el menu se apoya en esa diferencia.

## Anadir una aplicacion nueva

Escribe una funcion que reciba el `Terminal` y metela en `APPS`, al
final de [apps.py](apps.py):

```python
def app_saludo(term):
    nombre = term.ask("Como te llamas?")
    term.print(f"Hola, {nombre}.")
    term.pausa()

APPS = [
    ...
    ("8", "Saludo", app_saludo),
]
```

Metodos utiles de `Terminal`: `print`, `print_wrapped`, `page` (volcado
paginado), `titulo`, `aviso`, `caja`, `ask`, `pausa`, `menu` y
`wait_line`. Todo es bloqueante y secuencial: el 286 es el unico
cliente, no hace falta maquina de estados. Si una aplicacion revienta,
el broker lo caza y vuelve al menu sin cerrarse.

Para una seccion nueva que consulte a la IA, escribe el prompt en
`prompts.py` y llama a `seccion_ia(term, titulo, prompt, aviso)` desde
`broker_v2.py`.

## Arranque automatico en la Raspberry

En la Raspberry (no en el Mac), desde la carpeta del broker:

```bash
sudo ./instalar_servicio.sh
```

El script detecta solo el usuario, la ruta y el puerto (lo lee de
`config.py`), rellena la plantilla `systemd/broker286.service`, la
instala en `/etc/systemd/system/` y la activa. De paso avisa si falta
`api.env` o alguna dependencia de Python, y anade el usuario al grupo
`dialout` si no estaba.

El servicio va **atado al conversor USB-serie**, no a `multi-user.target`:

- Si arrancas la Pi con el cable enchufado, el broker sale con el
  sistema.
- Si arrancas sin el cable, no queda ningun servicio en `failed`: el
  broker se pone en marcha solo en cuanto lo enchufas.
- Si lo desenchufas, el servicio se para en vez de quedarse dando
  vueltas contra un `/dev/` que ya no existe.

Que el broker arranque antes que el 286 no es problema: el menu inicial
se pierde, pero desde `CHAT.EXE` basta con pulsar ENTER para repintarlo.

```bash
journalctl -u broker286 -f            # ver el log en vivo
sudo systemctl restart broker286      # tras tocar el codigo
sudo systemctl stop broker286         # antes de lanzarlo a mano
sudo ./instalar_servicio.sh --desinstalar
```

Solo puede haber un proceso con el puerto abierto: **para el servicio
antes de ejecutar `broker_v2.py` a mano**, o el que arranque segundo
fallara al abrir el puerto.

Si algun dia cambias `PORT` en `config.py`, vuelve a pasar el script:
el nombre del aparato esta escrito dentro de la unidad y no se entera
solo.
