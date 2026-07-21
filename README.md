# Tipi

Instalación reproducible de OpenClaw para PC y Raspberry Pi con conversación por voz. Tipi escucha localmente y solo abre OpenAI Realtime cuando detecta «Tipi» o una variante configurada.

## Componentes

- OpenClaw con `openai/gpt-5.6-luna`, razonamiento `low` y autenticación de OpenAI por código de dispositivo.
- OpenClaw Talk con `gpt-realtime-2.1-mini`, voz `cedar`, razonamiento `low`, reducción de ruido y transcripción guiada para español y catalán.
- Puente de voz Python 3.12 para Linux/ARM64, Linux/AMD64 y Windows.
- Activación offline mediante Vosk. Durante la reproducción correlaciona un reconocedor abierto con una gramática contrastiva que incluye los confusores, y solo recupera alias finales largos con un cierre abierto reciente y seguro. Así oye «Tipi» bajo voz solapada sin confiar ciegamente en «tipo», «típico», «sí» o «para ti».
- Consulta híbrida: Realtime resuelve conversación sencilla y delega en OpenClaw cuando necesita memoria, archivos, información actual, herramientas, acciones o verificación.
- Interrupción local: decir «Tipi» durante una respuesta detiene inmediatamente el audio atrasado y abre un nuevo turno. La consulta activa se conserva para poder corregirla o ampliarla.
- Cierre local con «cállate», «para», «silencio», «prou» y variantes inequívocas.
- Control hablado y persistente del volumen y de la sensibilidad del micrófono. En Linux se usan controles ALSA separados para no activar retorno del micrófono.
- Cambio hablado y persistente de voz: por ejemplo, «pon Marin» la prepara para la siguiente conversación sin editar archivos ni reiniciar el robot.
- Registro legible y JSONL de conversaciones, tool calls, latencias, interrupciones y errores, con redacción de credenciales reconocibles.
- Servicio `systemd`, actualización de imágenes, healthchecks y recuperación automática de la versión anterior.
- Modo cuidador de OpenClaw con identidad, memoria y revisiones de arranque y heartbeat.

## Credenciales

Se utilizan dos mecanismos independientes:

1. La autorización por código permite a OpenClaw usar GPT-5.6 Luna.
2. `OPENAI_REALTIME_API_KEY` se usa exclusivamente para Talk Realtime.

La autorización, la API key, el token del gateway, la memoria y los logs permanecen en `.env` y `data/`. Esas rutas están excluidas de Git y no se incorporan a las imágenes.

## Raspberry Pi

Recomendado: Raspberry Pi 4 o 5, sistema de 64 bits, Docker Engine con Compose v2 y audio visible en `/dev/snd`.

```bash
git clone https://github.com/AndreuSerraSastre/tipi-docker.git
cd tipi-docker
chmod +x scripts/*.sh
./scripts/install.sh
```

El asistente:

1. valida Docker, arquitectura y audio;
2. solicita la API key sin mostrarla;
3. presenta la URL y el código de autorización de OpenAI;
4. descarga Vosk y selecciona automáticamente un USB inequívoco, o pregunta si hay varios candidatos;
5. configura Luna con razonamiento bajo, identidad, memoria y autocuidado;
6. aprueba el cliente de voz, arranca los contenedores y habilita `tipi.service`;
7. no termina hasta verificar contenedores, autenticación, modelo, Talk y dispositivos.

Las imágenes públicas se descargan primero. Si no están disponibles, el asistente construye una copia local desde los Dockerfiles del repositorio.

### Operación

```bash
./scripts/doctor.sh
./scripts/smoke-agent.sh
./scripts/show-logs.sh
docker compose --profile linux-audio logs -f --tail=100 tipi-voice
journalctl -u tipi.service -f
```

`doctor.sh` es no destructivo: no recrea servicios ni ejecuta el asistente interno de OpenClaw. Comprueba salud, configuración efectiva, Luna autenticado, Talk, audio y autoinicio.

Para validar la palabra de activación a través de los altavoces, la sala y el micrófono reales:

```bash
./scripts/test-wake-room.sh
```

La activación admite decir la pregunta seguida, por ejemplo «Tipi, ¿qué hora es?», sin esperar al pitido. El audio capturado mientras Realtime termina de abrirse se conserva y se envía antes de reproducir la señal de listo.

Si ALSA recupera un adaptador USB después de una parada o reconexión, Tipi refresca la enumeración interna de PortAudio antes de declarar que el dispositivo ha desaparecido.

La prueba reproduce tres «Tipi» solapados y seis frases conflictivas, detiene solo la voz durante la captura y siempre restaura su estado anterior. Si falla, conserva las grabaciones bajo `/tmp/tipi-wake-room-test`; también admite dispositivos explícitos, por ejemplo `./scripts/test-wake-room.sh hw:1,0 hw:1,0`.

Desde otro PC:

```bash
ssh USUARIO@IP_DE_LA_RASPBERRY
cd /ruta/a/tipi-docker
docker compose --profile linux-audio logs -f --tail=100 tipi-voice
```

### Actualizar una instalación existente

```bash
cd /ruta/a/tipi-docker
git pull --ff-only
./scripts/update-and-start.sh
```

Las correcciones del runtime de voz y del gateway se publican en Docker. Los cambios de Compose, instalación, diagnóstico y configuración viven en Git; por eso un robot existente debe actualizar ambas capas. Los datos locales se conservan.

## Windows 11

Requiere Docker Desktop y Python 3.12:

```powershell
.\scripts\setup-windows.ps1
.\scripts\start-windows.ps1
```

OpenClaw se ejecuta en Docker y el puente de voz en Windows para acceder de forma fiable al audio. El modo cuidador utiliza un puente local sin puertos de red y limitado a la carpeta privada del proyecto.

Logs:

```powershell
.\scripts\show-logs-windows.ps1
.\scripts\show-logs-windows.ps1 -Follow
```

## Ajustes principales

- `TIPI_OPENCLAW_MODEL=openai/gpt-5.6-luna`: agente consultado por Talk.
- `TIPI_OPENCLAW_THINKING=low`: razonamiento del agente y de las consultas.
- `TIPI_REALTIME_REASONING=low`: razonamiento de Realtime.
- `TIPI_REALTIME_SPEAKER_VOICE=cedar`: voz inicial. También existen `marin`, `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer` y `verse`; `marin` y `cedar` suelen dar mejor calidad. Una preferencia elegida hablando se guarda en `data/voice/speaker-voice.json` y prevalece en sesiones posteriores.
- `TIPI_WAKE_WORDS=tipi,tipy,tip,tippi,tippy`: variantes exactas de activación.
- `TIPI_IDLE_TIMEOUT_SECONDS=5`: silencio antes de cerrar una conversación.
- `TIPI_AGENT_TIMEOUT_SECONDS=75`: límite de una consulta hablada a OpenClaw.
- `TIPI_BARGE_IN=false`: modo semidúplex recomendado con altavoces; «Tipi» siempre puede interrumpir.
- `TIPI_OUTPUT_ECHO_GUARD_SECONDS=0.45`: cola residual descartada después de reproducir audio.
- `TIPI_VAD_MODE=0..3`: sensibilidad de actividad de voz; `3` es la más estricta.
- `TIPI_REALTIME_NOISE_REDUCTION=near_field|far_field|off`: `far_field` es apropiado para el micrófono de sala del robot.
- `TIPI_REALTIME_TRANSCRIPTION_LANGUAGE=es`: idioma principal del transcriptor.
- `TIPI_INPUT_DEVICE` y `TIPI_OUTPUT_DEVICE`: índice o parte estable del nombre. Es preferible `USB Audio Device` a un índice ALSA que pueda cambiar al reiniciar.

Durante una conversación se pueden decir «sube el volumen», «pon los altavoces al 60 %», «sube la sensibilidad del micrófono» o «pon la voz Marin». La salida se limita a 0-100 % y la sensibilidad a 25-300 %.

## Publicación y pruebas

GitHub Actions ejecuta pruebas Python, validación de Compose/JSON/Node, `shellcheck` y construcción multi-arquitectura con SBOM y procedencia:

- `ghcr.io/andreuserrasastre/tipi-openclaw:latest`
- `ghcr.io/andreuserrasastre/tipi-voice:latest`

El workflow se ejecuta en cada cambio de `main`, al crear una etiqueta y diariamente. Las imágenes base de OpenClaw y Docker CLI están fijadas por digest multi-arquitectura para que una reconstrucción sea reproducible; su actualización es explícita y debe probarse antes de cambiar esos digests. Una publicación solo continúa si todas las verificaciones pasan.

El repositorio público es <https://github.com/AndreuSerraSastre/tipi-docker>. Nunca deben incorporarse `.env`, `data/`, copias de seguridad, claves, sesiones ni logs.

La configuración concede a OpenClaw control administrativo del dispositivo dedicado. No debe instalarse sin revisar ese alcance en un equipo con datos o servicios ajenos a Tipi.
