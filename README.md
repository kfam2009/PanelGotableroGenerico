# Panel Go · Tablero

Panel web de básquet con lectura automática del tablero (reloj, período, local y visita) y gráfica de marcador para **vMix** u **OBS**. Funciona en la misma PC que el software de producción o en otra PC conectada por **ZeroTier**.

## Cómo funciona

- El **lector** corre en la PC del panel. Toma imágenes de la cámara del tablero, reconoce los números y los muestra en el panel local `http://127.0.0.1:8771/`.
- La **gráfica** (`graphics.html`) se carga en vMix (entrada Web Browser) u OBS (fuente de navegador) y toma los datos del lector.
- **Mostrar en vMix/OBS** envía los nombres, escudos, torneo y categoría del panel y lo deja como fuente de la gráfica. El último panel que pulsa **Mostrar** es el que se ve. Mientras la gráfica está visible, los cambios se envían solos.

## Instalar

1. Descargar el repositorio como ZIP y extraerlo.
2. Instalar [Python 3.10 o posterior](https://www.python.org/downloads/windows/) con **Add Python to PATH**, si todavía no está.
3. Ejecutar `client/INSTALAR.cmd`. Instala las dependencias y el componente de video, y abre el asistente.
4. Ejecutar `client/INICIAR.cmd` para abrir el panel.

Para cambiar de vMix a OBS, las IP o el origen del tablero: `client/CONFIGURAR.cmd`.

## Asistente de configuración

1. **¿vMix u OBS?**
2. **IP de ZeroTier de esta PC** (la detecta sola) y **de la PC con vMix/OBS**. Si son iguales, todo está en esta misma PC.
3. **Origen del video del tablero:**
   - **vMix:** salida SRT de vMix (`IP:puerto`), o una cámara RTSP.
   - **OBS:** captura de una fuente de OBS (como siempre), o un video SRT/RTSP.
4. **Monitor de programa** (opcional): en vMix, una segunda salida SRT con el programa; en OBS, la captura del programa.

Cuando el tablero llega por SRT o RTSP, el asistente instala **ffmpeg** con `winget` (Gyan.FFmpeg) si todavía no está.

## vMix

En la PC de vMix:

- **Settings → Web Controller**: activado, puerto `8088`. El panel usa la API web de vMix para crear y mostrar la gráfica.
- **Settings → Outputs/NDI/SRT → Output 2** (o 3/4): Source = la cámara del tablero, **SRT** activado, Type **Listener**, puerto `9000`, H.264, 2500 kbps, **1920×1080**.
- Firewall: permitir el puerto `8088` (TCP) y el puerto SRT (UDP) para la IP de la PC del panel.

**Preparar en vMix** agrega una entrada Web Browser llamada `Panel Go - Marcador`. **Mostrar/Ocultar** la pone o la saca del overlay configurado (1 por defecto). El panel no cambia Program, Preview, grabación ni streaming.

Si la lectura falla por la compresión, subir el bitrate a 4000–5000 kbps. Con ZeroTier entre dos lugares, conviene una latencia SRT de 400–800 ms (`srt_latency_ms`).

## OBS

- **Herramientas → Ajustes del servidor WebSocket**: activado, puerto `4455`. La contraseña es opcional; sin clave, cualquier equipo de la red ZeroTier puede controlar OBS.
- **Preparar en OBS** crea la fuente `Panel Go - Marcador` apagada en la escena actual. **Mostrar/Ocultar** cambia solo esa fuente.

## PC del panel y PC de producción por ZeroTier

Cuando las IP son distintas, la gráfica se sirve desde la PC del panel en `http://IP_DEL_PANEL:8772/graphics.html`. Ese puerto solo responde a la IP de la PC de producción y entrega únicamente la gráfica y los datos del marcador, sin cámaras ni controles.

Firewall de la PC del panel (PowerShell como administrador):

```powershell
New-NetFirewallRule -DisplayName "Panel Go grafica" -Direction Inbound -Protocol TCP -LocalPort 8772 -RemoteAddress IP_DE_PRODUCCION -Action Allow
```

## Configuración (`client/config.json`)

| Clave | Uso |
|---|---|
| `switcher` | `"vmix"` u `"obs"` |
| `production_host` | IP de ZeroTier de la PC con vMix/OBS (`127.0.0.1` si es esta PC) |
| `bridge_address` | IP de ZeroTier de esta PC |
| `board_mode` | `"obs"` (captura de fuente de OBS) o `"stream"` (SRT/RTSP) |
| `board_url` | `IP:puerto` (SRT, modo caller) o `srt://...` / `rtsp://...` |
| `source` | Fuente del tablero en OBS (modo `obs`) |
| `game_url` | Monitor de programa por SRT/RTSP (opcional) |
| `vmix_port`, `vmix_overlay` | API de vMix (8088) y canal de overlay (1–4) |
| `obs_port`, `obs_password` | WebSocket de OBS |
| `srt_latency_ms` | Latencia SRT (400 por defecto) |
| `ffmpeg_path` | Ruta de ffmpeg (la completa el asistente) |

`config.json` es privado y está excluido de Git. Los valores de ejemplo están en `client/config.example.json`.

## Alcance de la calibración

La lectura está calibrada para un tablero y encuadre concretos a 1920×1080 (`client/reader.py`). El video SRT/RTSP se escala a 1920×1080 antes de leer, pero si cambia el encuadre, el zoom o el tablero, hay que recalibrar. Admite `MM:SS` y el formato `SS.T` del último minuto.

Cuando el tablero permanece visible con los dígitos apagados al menos dos segundos, el lector muestra **Local 0, Visita 0 y reloj 10:00**. Si se pierde la señal, se conservan los últimos datos y el lector reintenta solo.

## Render (opcional)

El servidor `server.mjs` puede publicar el panel en Render con `render.yaml` (Node 22, plan gratuito, `INGEST_TOKEN` generado por el Blueprint). Con `client/INICIAR-RENDER.cmd` el lector envía solo los cuatro datos del marcador; nunca video ni imágenes.

## Desarrollo y validación

```sh
npm ci --ignore-scripts
npm test
python -m unittest discover -s client -p "test_*.py"
```

El lector requiere Pillow y NumPy (`client/requirements.txt`) y, para SRT/RTSP, ffmpeg con soporte SRT.
