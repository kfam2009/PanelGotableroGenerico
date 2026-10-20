# Panel Club Estrella

Panel web de básquet con reloj, período, local y visita. El lector se instala en la **misma PC que OBS**. Consulta `127.0.0.1:4455` y envía únicamente los cuatro datos a Render por HTTPS. No requiere ZeroTier ni abrir puertos de la PC del cliente. Opcionalmente, el lector puede correr en otra PC y leer OBS por ZeroTier.

Incluye las correcciones de décimas (`05.4`) y de la confusión entre el `3` y el `1` en el marcador de visita, verificadas con capturas reales del tablero.

## Desplegar el panel en Render

1. Abrir [Crear Blueprint](https://dashboard.render.com/blueprint/new?repo=https://github.com/kfam2009/Clubestrella).
2. Seleccionar la cuenta/workspace correcto, conectar este repositorio y revisar el servicio `clubestrella-panel` antes de aplicar.
3. El archivo `render.yaml` configura un Web Service Node, plan gratuito, build `npm ci --ignore-scripts`, inicio `npm start` y salud `/healthz`.
4. Cuando el servicio esté activo, guardar su URL `https://....onrender.com`.
5. En **Environment** del servicio, copiar el valor privado de `INGEST_TOKEN` para configurar el lector. El Blueprint genera esa clave; no se guarda en este repositorio ni se muestra en el panel público.

Si se crea el Web Service manualmente en lugar de usar el Blueprint, configurar esos mismos comandos y una variable `INGEST_TOKEN` con una clave aleatoria de al menos 32 caracteres. El servidor se niega a iniciar sin clave.

La configuración debe tener **una sola instancia**: el último estado se mantiene en memoria. Después de un reinicio del servicio, vuelve a aparecer al reconectar el lector. No necesita base de datos. Consultar las condiciones actuales del [plan gratuito](https://render.com/docs/free) para uso durante una transmisión.

## Instalar en la PC del cliente

1. Descargar este repositorio como ZIP y extraerlo.
2. Instalar Python 3.10 o posterior desde [python.org](https://www.python.org/downloads/windows/) si todavía no está instalado. Activar **Add Python to PATH**.
3. En OBS, habilitar el servidor WebSocket en el puerto `4455` y desmarcar **Habilitar autenticación** para esta instalación local sin clave. La cámara del tablero debe estar activa y conservar el encuadre actual. La fuente usada por defecto se llama `Camara 2`.
4. En la carpeta `client`, ejecutar `INSTALAR.cmd`. Crea el entorno Python y solicita la URL de Render, `INGEST_TOKEN`, el nombre exacto de las fuentes (OBS local sin clave).
5. Ejecutar `client/INICIAR.cmd`. Abre un monitor local en `http://127.0.0.1:8771/` y empieza a enviar lecturas a Render.
6. Mantener abierta la consola del lector durante el partido. Cerrar la consola detiene el lector. Si ya hay otro panel usando el puerto `8771`, detenerlo antes de iniciar este.

El monitor local muestra el tablero y la **salida de programa de OBS** uno al lado del otro. El segundo recuadro incluye todas las capas visibles de la escena de programa, incluido el marcador cuando se active. Se actualiza mediante capturas de 960×540 cada 1,25 segundos aproximadamente, sin audio; no es un retorno de la plataforma de transmisión. Sigue los cambios de escena de programa sin cambiar nada en OBS. La lectura del marcador funciona por separado.

Para monitorear la cámara del juego en video continuo en vez de programa, configurar `monitor_mode: "camera"`. Ese modo usa RTSP mediante go2rtc y MSE/WebSocket. La fuente debe ser RTSP, preferentemente H.264; la compatibilidad depende del códec y del navegador. Usar Chrome o Edge actualizado. La cámara debe admitir una conexión adicional desde la PC. `PREPARAR-PRUEBA.cmd` configura ese modo para la prueba de video continuo. Render recibe únicamente los datos del marcador.

El instalador obtiene go2rtc 1.9.14 de su repositorio oficial y verifica SHA-256. El reproductor y la licencia MIT se incluyen en `client/vendor`. El servicio de video escucha solo en localhost y su API requiere una clave aleatoria. El navegador accede únicamente al stream del juego a través del lector; no recibe la dirección ni las credenciales de la cámara. `client/.runtime` contiene la configuración privada temporal y está excluida de Git.

## Lector en otra PC con OBS por ZeroTier

El lector también puede correr en una PC distinta de la de OBS, si ambas están en la misma red de ZeroTier. Así la PC del club solo necesita OBS.

1. En la PC de OBS, habilitar el servidor WebSocket. La autenticación es opcional: sin clave, cualquier equipo de la red ZeroTier puede controlar OBS, así que conviene que esa red tenga solo equipos de confianza.
2. Anotar las dos IP de ZeroTier: la de la PC de OBS y la de la PC del lector.
3. En la PC del lector, ejecutar `client/PREPARAR-ZEROTIER.cmd`. Instala lo necesario si falta y pide la IP de OBS, la contraseña (opcional) y la IP de ZeroTier de esta PC (la detecta sola). También se pueden editar `obs_host`, `obs_password` y `bridge_address` en `client/config.json`.
4. En el firewall de Windows, permitir solo lo necesario (PowerShell como administrador):
   - PC de OBS: `New-NetFirewallRule -DisplayName "OBS WebSocket ZeroTier" -Direction Inbound -Protocol TCP -LocalPort 4455 -RemoteAddress IP_DEL_LECTOR -Action Allow`
   - PC del lector: `New-NetFirewallRule -DisplayName "Panel Go salida ZeroTier" -Direction Inbound -Protocol TCP -LocalPort 8772 -RemoteAddress IP_DE_OBS -Action Allow`
5. Ejecutar `client/INICIAR.cmd` en la PC del lector. La consola muestra la dirección de la salida para OBS.

**Preparar en OBS** crea la fuente apuntando a `http://IP_DEL_LECTOR:8772/graphics.html`. Ese puerto solo responde a la IP de OBS y entrega únicamente la gráfica y los datos del marcador, sin cámaras ni controles. El monitor local sigue abierto solo en la PC del lector. Para este modo conviene `monitor_mode: "program"`; el modo `camera` requiere que la cámara RTSP también sea accesible desde la PC del lector. La lectura depende de la calidad de la conexión: si ZeroTier se corta, el lector reintenta y conserva los últimos datos.

## Probar video sin configurar Render

En la misma PC de OBS, ejecutar `client/PREPARAR-PRUEBA.cmd` una vez y luego `client/PROBAR-VIDEO.cmd`. El primero instala los componentes y pide los nombres de las fuentes; OBS se usa localmente sin clave. El segundo abre `http://127.0.0.1:8771/` en modo local, sin enviar datos a Render. Detener primero otro lector si está usando ese puerto. Mantener OBS abierto y la consola del lector abierta durante la prueba. Para detener, pulsar Ctrl+C en esa consola.

Comparar el reloj, ambos puntajes y el período durante 2 o 3 minutos, mientras se comprueba el movimiento continuo del juego. El indicador muestra los fps reproducidos; su valor depende de la cámara y la PC. Ver `client/LEEME-PRUEBA.txt`. La reproducción se validó localmente con una señal sintética H.264 de 25 fps; falta la prueba de la cámara real desde la red del club. No se necesita ZeroTier.

Para cambiar la configuración, ejecutar `client/CONFIGURAR.ps1` con PowerShell o editar el archivo local `client/config.json`. Ese archivo contiene claves privadas: está excluido de Git y no debe compartirse. Los valores de ejemplo están en `client/config.example.json`.

## Abrir panel y salida

El panel usa la identidad de Panel Go, muestra los datos del partido en tarjetas y adapta los ajustes a pantallas pequeñas. En el lector local, **Preparar en OBS** crea la fuente `Panel Go - Marcador Estrella` apagada en la escena actual. Luego el mismo botón permite **Mostrar en OBS** y **Ocultar de OBS**. Consultar el estado no cambia la visibilidad. El control escucha únicamente en localhost y solo permite modificar esa fuente; no cambia escenas ni inicia o detiene la emisión. La fuente se debe validar fuera del vivo antes de usarla durante una transmisión. Si existe `client/.obs-safety-lock`, se bloquea su activación desde el panel.

El monitor instalado en la PC incluye el mismo diseño y las cámaras. El ZIP del lector incluye los archivos web en `client/panel`; al ejecutar desde el repositorio se usa `public`. El control de OBS se inicia junto al lector. La versión en Render muestra los datos recibidos; la operación de OBS se realiza desde el panel local de la PC del club.

En el panel local, **Aplicar nombres y escudos a OBS** comparte nombres, escudos, torneo y categoría con la fuente de OBS. Hay que pulsarlo una vez desde el navegador que contiene los ajustes deseados; luego sus cambios se envían automáticamente. Los ajustes se guardan en `.graphic-settings.json`, excluido de Git y de los paquetes. Así la fuente puede recibir las imágenes cargadas desde archivos, aunque OBS use un navegador separado. Los puntajes y el reloj siguen procediendo del lector. La salida `graphics.html` usa un renderizador independiente y liviano que consulta los datos y ajustes sin cargar los controles del panel.

- Control: `https://TU-SERVICIO.onrender.com/index.html`
- Salida limpia 1920×1080: `https://TU-SERVICIO.onrender.com/graphics.html`
- Estado: `/api/state`
- Salud del servicio: `/healthz`

Cambiar nombres, logos y textos desde el panel. **Abrir salida limpia** conserva esos ajustes en el enlace. También se guardan en el navegador; las pestañas del mismo navegador se sincronizan. No son ajustes globales compartidos entre navegadores.

Las cifras se leen de capturas; no se extrapola un cronómetro. Cuando el tablero permanece visible con todos sus dígitos apagados durante al menos dos segundos, el lector muestra **Local 0, Visita 0 y reloj 10:00**. Al encenderse, retoma las lecturas confirmadas. Una imagen negra o uniforme de la cámara y la pérdida de conexión no disparan ese reinicio. Si se pierde la lectura, se conservan los datos y el panel informa su estado; la gráfica de transmisión no muestra el aviso de último dato. Al volver OBS o internet, el lector reintenta automáticamente y envía el estado más reciente.

## Alcance de la calibración

La lectura está calibrada para la fuente actual a 1920×1080. Si cambia el encuadre, zoom o posición del tablero, hay que ajustar `client/reader.py`. Admite `MM:SS` y el formato de tres dígitos `SS:T` del último minuto, mostrado como `SS.T`. Falta validar todos los dígitos y períodos durante un partido completo.

Las capturas de cámara y la clave de OBS permanecen en la PC del cliente. El servidor público recibe puntajes, reloj, período y datos de frescura, nunca video ni imágenes. OBS se consulta en modo de lectura: no se cambia la escena, las fuentes ni la emisión.

## Desarrollo y validación

Node 22 o posterior, sin dependencias de terceros:

```sh
npm ci --ignore-scripts
npm test
```

Para iniciar el servidor, definir `INGEST_TOKEN` en el entorno y ejecutar `npm start`. `PORT` es opcional fuera de Render y usa `10000` por defecto.

El lector requiere Pillow y NumPy, indicados en `client/requirements.txt`. Pruebas del código Python:

```sh
python -m unittest discover -s client -p "test_*.py"
```

Las pruebas con capturas originales se realizaron localmente; esas imágenes no se publican en el repositorio.
