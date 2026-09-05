# Broker v2 -- capa de menu para el 286

Puente serie entre `CHAT.EXE` (Intel 286, MS-DOS) y la Raspberry Pi,
con un menu navegable delante de la API de Claude.

## Que cambia respecto al v1

`broker_v1.py` mandaba a la API cualquier linea que llegara del 286.
`broker_v2.py` mete un menu delante: la conversacion libre pasa a ser
la opcion 5, y aparecen secciones con prompts preparados y
aplicaciones que se ejecutan en la propia Raspberry.

**El protocolo serie no cambia**: lineas de texto terminadas en CR LF,
8N1. `broker_v1.py` se deja tal cual por si hace falta volver atras.

## Velocidad del enlace: 28800 y recepcion por IRQ

El enlace iba a 9600, pero lo que hacia lentos los menus no era el
baudrate: era `CHAR_DELAY = 0.003` en [config.py](config.py). El broker
mandaba **byte a byte con 3 ms de pausa entre cada uno**, o sea ~330
bytes/s: el cable iba a 9600 pero el caudal real era el de unos 3300
baudios. Un menu de 800 caracteres tardaba mas de dos segundos y medio.

Ese freno tenia su motivo. `CHAT.EXE` recibia por **sondeo** contra una
UART 8250/16450, que no tiene FIFO: si el bucle principal no pasaba por
el registro de estado antes de que llegara el siguiente byte, ese byte
se perdia. Y el bucle tiene que pintar en pantalla y hacer scroll.

La solucion es cambiar el lado del 286, no el del broker:

- `serial.c` recibe ahora **por interrupciones** (IRQ4 en COM1, IRQ3 en
  COM2) y mete los bytes en un buffer circular de 4 KB. El bucle
  principal se puede entretener un scroll entero sin perder nada.
- Si la UART es una 16550A, se activa su FIFO de 16 bytes.
- El 286 baja RTS al llenarse el buffer a 3/4, por si el cable lleva
  RTS/CTS cruzados. Viene desactivado (`RTSCTS` en `config.py`): un
  adaptador null modem barato cruza solo TX/RX, y activarlo sin tener
  los pines 7-8 cruzados deja al broker escribiendo contra un CTS que
  nunca sube. Ahi se explica como comprobarlo.
- Con eso, `CHAR_DELAY` y `LINE_DELAY` pasan a 0 y el baudrate sube a
  **28800**. El caudal real pasa de ~330 a ~2900 bytes/s: los menus
  salen unas ocho o nueve veces mas rapido.

**Hay que recompilar `CHAT.EXE`** (`build_chat.bat` en el repo del
286): los dos extremos tienen que ir a la misma velocidad. `BAUDRATE`
en `config.py` y `BAUDIOS` en `chat.c` son el mismo numero. Si el 286
pinta basura, es que no coinciden.

Si hiciera falta volver atras con un `CHAT.EXE` antiguo, `broker_v1.py`
sigue con sus 9600 y su envio frenado, sin tocar.

## Ficheros

| Fichero        | Que hace                                                   |
|----------------|------------------------------------------------------------|
| `broker_v2.py` | Bucle principal, menu y secciones                          |
| `terminal.py`  | Capa de pantalla/teclado sobre el puerto serie             |
| `ia.py`        | Cliente de la API de Claude (consultas sueltas y chat)     |
| `prompts.py`   | Prompts de las secciones que si usan la IA                 |
| `tiempo.py`    | Prevision de AEMET por municipio (opcion 2)                |
| `noticias.py`  | Titulares por RSS de Europa Press (opcion 1)               |
| `mercados.py`  | Cotizaciones via API publica (Yahoo Finance)               |
| `telegrama.py` | Cliente de Telegram (Bot API), opcion 6                    |
| `emojis.py`    | Tabla de emoji -> CP437, para mantener a mano              |
| `apps.py`      | Aplicaciones locales de la Raspberry                       |
| `actualizar.py`| git pull desde el menu Configuracion (opcion 7)            |
| `config.py`    | Configuracion por defecto: puerto, ciudad, valores, modelo |
| `api.env`      | Claves y lo que cambia de una maquina a otra (sin git)     |
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

### Que va en `api.env` y que en `config.py`

**Regla: lo que cambie de una maquina a otra o sea personal, a
`api.env`.** Ese fichero esta en `.gitignore`; `config.py` no, y
editarlo en la Raspberry deja el repo sucio, con lo que el `git pull`
de "Actualizar Broker" se planta y el 286 se queda sin poder
actualizarse solo.

Claves que reconoce `api.env`, todas opcionales menos la primera:

| Clave | Para que | Por defecto |
|-------|----------|-------------|
| `ANTHROPIC_API_KEY` | La clave de Claude | (obligatoria) |
| `PORT` | Puerto serie del conversor USB | `/dev/ttyUSB0` |
| `CIUDAD` | Municipio por defecto del tiempo (opcion 2) | `Madrid` |
| `TELEGRAM_TOKEN` | Bot de Telegram (opcion 6) | sin Telegram |
| `TELEGRAM_CHATS` | Conversaciones fijadas | lista vacia |

Lo demas (ritmo del cable, ancho de pantalla, lista de valores de
bolsa, modelo de IA) sigue en `config.py`: son decisiones del
proyecto, iguales en cualquier maquina. Si algun dia quieres
personalizar una de ellas en la Pi, sacala a `api.env` con
`leer_env()` en vez de editarla ahi.

Si cambias `PORT`, vuelve a pasar `sudo ./instalar_servicio.sh`: el
nombre del aparato va escrito dentro de la unidad de systemd.

## El menu

```
1. Noticias                     RSS de Europa Press, sin pasar por la IA
2. Prevision del tiempo         AEMET, 7 dias, cualquier municipio
3. Cotizaciones                 precios via API, sin pasar por la IA
4. Aplicaciones                 submenu, todo local en la Pi
5. Chat con Claude              el comportamiento del broker v1
6. Telegram                     enviar y recibir, via bot
7. Configuracion                actualizar el broker y reiniciar
0. Apagar la sesion
```

Aplicaciones (opcion 4): reloj para poner en hora el 286, calculadora,
conversor de unidades, bloc de notas guardado en la Pi, estado de la
Raspberry, adivina el numero y efemerides del dia.

## Noticias (opcion 1): RSS de Europa Press

Antes esto eran dos opciones del menu (economicas y politicas) que le
preguntaban a Claude con busqueda web. Ahora es una sola que lee el RSS
de Europa Press. Es la misma decision que se tomo con las cotizaciones:
**para datos, una fuente de datos**; a la IA se le pregunta el porque,
no el que. Los titulares los escribe una redaccion, salen en un segundo
en vez de veinte, traen hora de publicacion y no cuestan una llamada a
la API. La opcion 2 desaparecio porque la politica ya viene dentro del
feed de Nacional.

**Los menus no estan escritos en el codigo.** Salen del OPML que publica
el propio medio, un indice de todos sus feeds ya agrupado por temas:

```
https://www.europapress.es/rss/europapress.opml.xml
```

Son cuatro grupos y unos 44 canales. Si Europa Press anade una seccion
manana, aparece sola en el 286 sin tocar nada. Para leer otro periodico
basta con cambiar `NOTICIAS_OPML` (en `config.py` o en `api.env`),
siempre que publique un OPML con feeds RSS estandar.

La navegacion son tres niveles, y la cabecera del marco lleva las migas
de pan para saber siempre donde estas:

```
╔════════════════════════════════════════════════════════════════════╗
║ NOTICIAS > Actualidad Autonomica > Islas Canarias                  ║
╠════════════════════════════════════════════════════════════════════╣
║   1. Dominguez (PP) reclama al Gobierno "cerrar las fronteras" ... ║
║   2. Detienen a un padre y a su hijo por gestionar un punto de ... ║
║   0. Volver a los canales                                          ║
╠════════════════════════════════════════════════════════════════════╣
║ 10 titulares                                                       ║
╚════════════════════════════════════════════════════════════════════╝
```

Grupo -> canal -> titular -> el resumen del feed, paginado. Como el
grupo autonomico tiene 18 canales y en la ventana de `CHAT.EXE` solo
caben unas doce lineas de menu, los menus largos se parten en paginas y
se navega con `S` (siguiente) y `A` (anterior). El "0. Volver" sale en
todas las paginas, no solo en la ultima.

Detalles de como se reparte el sitio, que en 70 columnas es lo que hay:

- **En la lista no salen fecha ni hora.** Ocupaban trece caracteres de
  los pocos que hay y hacian que se cortara casi cualquier titular. La
  fecha se ve al abrir la noticia, que es donde de verdad se mira.
- **Lo que se corta acaba en `...`**, para que un titular recortado no
  parezca el titular entero.
- **Al abrir una noticia el titular ocupa hasta cuatro lineas** en vez
  de cortarse: los de prensa pasan casi siempre de 70 caracteres y el
  corte se llevaba justo la parte que dice de que va la cosa.
- **No se pinta el enlace.** En el 286 no hay navegador ni forma de
  copiarlo a ningun sitio; solo gastaba lineas de pantalla.

Del RSS se quita el HTML y las entidades (`&amp;`, `&#8220;`) y se pasa
por [emojis.py](emojis.py), que es quien sabe cambiar las comillas
tipograficas y las rayas largas de los teletipos por algo que exista en
CP437. Los acentos y la ene no se tocan: CP437 los tiene.

El indice de canales se cachea un dia y cada feed cinco minutos, para
que moverse por los menus no sea una descarga por pantalla.

## Prevision del tiempo (opcion 2): AEMET, tampoco por la IA

AEMET publica la prevision oficial a siete dias en XML, gratis y sin
clave, con una URL por municipio:

```
https://www.aemet.es/xml/municipios/localidad_22035.xml   -> Aren
```

Ese numero es el codigo INE de cinco digitos (dos de provincia, tres de
municipio). Sale de la tabla de municipios de la AEAT que esta en esta
misma carpeta. El usuario escribe el nombre, [tiempo.py](tiempo.py) lo
busca, compone la URL y pinta la semana:

```
AREN (HUESCA)
-------------

DIA        CIELO                              MIN/MAX  LLUV  VIENTO
-------------------------------------------------------------------
Sab 05/09  Poco nuboso                         18/38    0%  S 10
Mie 09/09  Intervalos nubosos con lluvia       15/30   90%  flojo
```

**La columna buena de la tabla de la AEAT es la SEGUNDA.** Es la trampa
del formato y conviene dejarla escrita:

```
22 22035 22044 AREN
```

La tercera columna es otro codigo distinto: para Aren vale `22044`, que
en AEMET es Bailo. Coinciden en muchisimos municipios, que es justo lo
que lo hace peligroso. Comprobado contra AEMET sobre una muestra al
azar, la segunda acierta siempre y la tercera falla en cuanto las dos
difieren (otro municipio, o un 404).

Dos rarezas del XML de AEMET que hay que sortear:

- **Declara `ISO-8859-15` pero el campo `<nombre>` va en UTF-8.** Se ve
  en los bytes del mismo fichero: `<productor>` trae `Meteorologí a`
  (latin-1 correcto) y `<nombre>` trae `ArÃ©n` (UTF-8 crudo). Si se
  hace caso a la cabecera, Aren sale como "ArA©n".
- **El dia reparte los datos de dos formas distintas.** Los cuatro
  primeros vienen troceados en tramos (`00-24`, `12-18`...) y el de HOY
  trae el `00-24` vacio porque la jornada ya va empezada; del quinto en
  adelante hay un solo bloque **sin atributo `periodo`**. Filtrar solo
  por tramo dejaba los tres ultimos dias sin cielo ni lluvia.

Como hay 8.086 municipios con prevision y los nombres se repiten mucho
entre provincias, la busqueda ensena la lista con la provincia al lado
y se elige. Se busca sin acentos y sin el articulo: `la nava`, `nava` y
`NAVA (LA)` llevan al mismo sitio.

La tabla de municipios se actualiza dejando caer el fichero nuevo de la
AEAT en la carpeta: `config.MUNICIPIOS_GLOB` lo busca por patron
(`Tabla_Municipios*.txt`), no por nombre exacto, porque la AEAT le pone
la fecha al nombre.

## Cotizaciones (opcion 3): datos de API, no de la IA

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

## Telegram (opcion 6)

Enviar y recibir mensajes de Telegram desde MS-DOS, con un bot de la
Bot API. Es HTTPS y JSON, igual que las cotizaciones, asi que **no hay
que instalar nada** en la Raspberry.

Puesta en marcha:

1. En Telegram, habla con `@BotFather` y manda `/newbot`. Te da un
   token.
2. Pega el token en `api.env`: `TELEGRAM_TOKEN=1234567890:AA...`
   (`api.env` esta en `.gitignore`, no se sube).
3. Escribele algo al bot desde el movil. Un bot no puede empezar una
   conversacion, tiene que hablarle alguien primero.
4. En el 286, `Telegram -> Ver chats que han escrito al bot`: sale el
   `chat_id` de quien te ha escrito.
5. Copia ese numero en `api.env` (no en `config.py`), en una linea
   `TELEGRAM_CHATS`. Los grupos llevan el id negativo:

```
TELEGRAM_CHATS=-1001234567890:Los colegas;123456789:Movil de Daniel
```

Las conversaciones van en `api.env` y no en `config.py` por dos
motivos: son datos personales que no pintan nada en un repositorio
publico, y sobre todo porque **`config.py` esta versionado**. Editarlo
en la Raspberry dejaba el repo sucio y el `git pull` de "Actualizar
Broker" se plantaba con *Your local changes would be overwritten by
merge*, que es justo romper el flujo de actualizacion desde el 286.
Regla general: lo que cambie de una maquina a otra, a `api.env`.

Como funciona por dentro:

- **Solo se ven mensajes mientras la seccion esta abierta.** No hay
  hilo de fondo ni avisos en el menu principal: el 286 tiene una sola
  pantalla y ningun modo de decir "esto va aparte", asi que escribir
  desde dos sitios a la vez es basura asegurada, vaya el cable a la
  velocidad que vaya. Al entrar se descarta lo atrasado.
- Dentro de una conversacion, lo que escribas se envia con ENTER y cada
  `TELEGRAM_POLL` segundos (5 por defecto) se mira si han contestado.
  El truco para hacer las dos cosas sin hilos es que
  `Terminal.read_line()` devuelve `None` cuando vence el timeout del
  puerto sin que el 286 haya dicho nada: ese hueco es el que se
  aprovecha para preguntarle a Telegram.
- Lo que llegue de otro chat mientras estas dentro de uno no se cuela
  en medio: se queda en el buzon y avisa con una linea, y se ensena
  entero cuando entras en esa conversacion.
- El `update_id` por el que va la lectura se guarda en
  `telegram_offset.txt` para que un reinicio del broker no vuelva a
  soltar todo lo antiguo.
- Fotos, audios y stickers no se pueden ver, pero se anuncian
  (`[una foto] pie de foto`).

Los emoji no existen en CP437, asi que se traducen en
[emojis.py](emojis.py), que esta aparte justo para que sea comodo
mantenerlo. De momento estan los cinco mas evidentes y las comillas y
rayas raras que meten los moviles; para anadir otro basta con una linea
mas en `TABLA`. Los acentos y la ene NO se tocan: CP437 los tiene y se
ven bien en el 286.

## Configuracion -> Actualizar Broker (opcion 7)

Para no tener que abrir un SSH cada vez que se toca el codigo. El flujo
es: `git push` desde el PC o el Mac, y en el 286 **Configuracion ->
Actualizar Broker**. La Raspberry hace el `git pull` sola y, si ha
entrado codigo nuevo, **se reinicia sola** para aplicarlo.

Detalles que conviene saber:

- Se hace `git pull --ff-only` y, antes, se comprueba que no haya
  cambios locales. Si los hay, el broker se planta y avisa: un merge a
  ciegas no se puede resolver desde una pantalla de 286.
- El reinicio **no se pregunta**: si el `git pull` trae algo, se aplica.
  Poder quedarse con el codigo viejo era la forma facil de acabar con un
  broker que dice estar actualizado y no lo esta, y desde el 286 no hay
  manera de notar la diferencia. Ademas el codigo recien traido puede no
  casar con el que ya esta en memoria (un `config.py` con claves nuevas,
  por ejemplo).
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
