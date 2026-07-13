# Tipi

Instalación reproducible de OpenClaw para PC y Raspberry Pi con conversación por voz. Tipi escucha la palabra de activación localmente y solo abre una sesión de OpenAI Realtime cuando oye “Tipi” o una variante configurada.

## Qué incluye

- OpenClaw con `openai/gpt-5.6-sol`, razonamiento `medium` y acceso mediante código de dispositivo.
- Codex actualizado dentro de la imagen `tipi-openclaw` para poder ejecutar GPT-5.6 Sol.
- OpenClaw Talk con `gpt-realtime-2.1`, voz `cedar` y razonamiento `medium`.
- Realtime responde directamente a saludos y conversación sencilla; consulta OpenClaw cuando necesita identidad ampliada, memoria, archivos, estado real, herramientas, acciones o verificaciones.
- Las respuestas de voz tienden a una o dos frases, pero pueden ampliarse sin límite fijo cuando la persona lo pide o la explicación lo requiere. El puente bloquea una segunda respuesta de Realtime si no ha habido una nueva intervención.
- Transcripción guiada para español de España y catalán, con reducción de ruido configurable para micrófonos cercanos o de sala.
- Personalidad en `workspace/IDENTITY.md` y `workspace/SOUL.md`, sin instrucciones sobre una tarea concreta.
- Activación offline mediante Vosk: `tipi`, `tipy`, `tip`, `tippi` y `tippy`.
- Sonido ascendente al terminar el arranque y un pitido corto distinto al detectar la activación.
- Si se dice “Tipi” mientras está respondiendo, corta la voz y vuelve a escuchar tras el pitido.
- Si se dice “cállate”, “para”, “silencio”, “prou” o una variante inequívoca, cierra la conversación y no vuelve a escuchar hasta oír “Tipi”.
- Volumen de salida y sensibilidad del micrófono ajustables hablando, con valores persistentes.
- Cierre de Realtime después de cinco segundos sin actividad.
- Actualización al arrancar con comprobación de salud y recuperación de la imagen anterior si falla.
- Sincronización de los ajustes administrados de OpenClaw al actualizar, conservando autenticación y datos locales.
- Modo cuidador de OpenClaw: revisa, diagnostica, repara, prueba, revierte y aprende tanto al arrancar como periódicamente.

## Primera instalación

El instalador actúa como asistente y pide, en orden:

1. autorización de la cuenta de OpenAI mediante URL y código;
2. API key para OpenAI Realtime, oculta mientras se escribe;
3. micrófono y altavoces.

El acceso por código se utiliza para GPT-5.6 Sol. La API key queda aislada como `OPENAI_REALTIME_API_KEY` y solo la consume Talk Realtime. Ambos datos se guardan en `data/` y `.env`, que están excluidos de Git y de las imágenes.

El instalador intenta descargar las imágenes publicadas. Si el registro no está disponible o requiere permisos, construye automáticamente las imágenes locales desde la base oficial y continúa la instalación. En los arranques posteriores también comprueba y aplica las actualizaciones de esa base.

Después de autenticar el modelo, el instalador inicia el ritual oficial de primera ejecución de OpenClaw. El agente pregunta quién es, quién es Andreu y para qué fue creado; el instalador responde automáticamente con `config/tipi-bootstrap-answers.md`. Es el propio agente quien genera su identidad, perfil de usuario y memoria dentro de `data/openclaw/workspace/`, y el instalador verifica el resultado antes de arrancar la voz.

A continuación, el propio OpenClaw crea sus órdenes permanentes de autocuidado en `AGENTS.md`, `BOOT.md` y `HEARTBEAT.md` y ejecuta una primera revisión real. Sus intervenciones quedan en `data/maintenance/actions.jsonl`; los aciertos, errores, correcciones, pruebas y reglas aprendidas se conservan en `CARETAKER_LESSONS.md` para que no repita fallos ni reescriba la historia como si siempre hubiera acertado. En esta instalación Andreu le concede acceso administrativo completo al dispositivo: puede modificar el sistema, Docker, el proyecto y sus servicios sin confirmaciones. No se debe desplegar esta configuración en un equipo que contenga datos o servicios que no se quiera poner bajo el control de Tipi.

### Windows 11

Requiere Docker Desktop y Python 3.12:

```powershell
.\scripts\setup-windows.ps1
.\scripts\start-windows.ps1
```

En Windows, OpenClaw se ejecuta en Docker y el pequeño puente de audio se ejecuta en el host para acceder de forma fiable a los cascos.
El instalador inicia además un puente local oculto que permite al modo cuidador administrar Windows. Solo acepta peticiones desde la carpeta privada del proyecto y no expone ningún puerto de red.

### Logs de conversación

Tipi crea un registro diario legible en `data/logs/`. Incluye la transcripción final de la persona, la respuesta de Realtime, las consultas y resultados de OpenClaw y los tiempos en milisegundos. También genera un archivo `.jsonl` equivalente para análisis automático. Las credenciales reconocibles se ocultan antes de escribir.

Abrir el último registro en el Bloc de notas:

```powershell
.\scripts\show-logs-windows.ps1
```

Seguirlo en directo:

```powershell
.\scripts\show-logs-windows.ps1 -Follow
```

### Controles de audio hablados

Durante una conversación se pueden usar órdenes como “sube el volumen”, “pon los auriculares al 60 %”, “baja la sensibilidad del micrófono” o “pon el micro al 150 %”. Los cambios se aplican al audio de Tipi, funcionan igual en Windows y Raspberry Pi y se conservan después de reiniciar. El micrófono se limita entre 25 % y 300 % para que una orden no lo deje inutilizable; la salida se limita entre 0 % y 100 %.

### Raspberry Pi

Recomendado: Raspberry Pi 4 o 5, Raspberry Pi OS de 64 bits, Docker Engine con Compose v2 y audio visible en `/dev/snd`.

```bash
git clone https://github.com/AndreuSerraSastre/tipi-docker.git
cd tipi-docker
chmod +x scripts/*.sh
./scripts/install.sh
```

El instalador activa `tipi.service`. En cada arranque busca imágenes nuevas, espera a que estén sanas y recupera las anteriores si una actualización falla.

Diagnóstico:

```bash
./scripts/doctor.sh
journalctl -u tipi.service -f
docker compose -f compose.yaml -f compose.registry.yaml --profile linux-audio logs -f
./scripts/show-logs.sh
```

## Publicación

`.github/workflows/publish.yml` prueba el proyecto y publica dos imágenes para `linux/amd64` y `linux/arm64`:

- `ghcr.io/andreuserrasastre/tipi-openclaw:latest`
- `ghcr.io/andreuserrasastre/tipi-voice:latest`

El workflow se ejecuta al cambiar el proyecto y una vez al día. La Raspberry solo necesita descargar el repositorio, ejecutar el instalador y completar sus propios datos; nunca se publica ninguna credencial.

El repositorio público es <https://github.com/AndreuSerraSastre/tipi-docker>. La publicación pública contiene únicamente código, configuración base e imágenes; `.env`, claves, autenticación, memoria, sesiones y registros permanecen locales en cada instalación.

## Ajustes

- `TIPI_IDLE_TIMEOUT_SECONDS=5`: tiempo sin actividad antes de cerrar Realtime.
- `TIPI_WAKE_WORDS=tipi,tipy,tip,tippi,tippy`: variantes de activación.
- `TIPI_BARGE_IN=false`: semidúplex recomendado con altavoces para evitar eco.
- `TIPI_VAD_MODE=0..3`: sensibilidad local; `3` es la más estricta.
- `TIPI_REALTIME_NOISE_REDUCTION=near_field|far_field|off`: `near_field` para cascos y `far_field` para el micrófono de sala del robot.
- `TIPI_REALTIME_TRANSCRIPTION_LANGUAGE=es`: idioma principal enviado al transcriptor; el contexto permite contestar también en catalán.
- `TIPI_REALTIME_TRANSCRIPTION_PROMPT=...`: vocabulario y contexto que ayudan a evitar transcripciones en idiomas aleatorios.
- `TIPI_OUTPUT_CHANNELS=1|2`: salida mono o estéreo; en PC se recomienda `2` para evitar audio deformado en dispositivos estéreo.

Documentación relacionada: [Docker en OpenClaw](https://docs.openclaw.ai/install/docker), [OpenAI en OpenClaw](https://docs.openclaw.ai/providers/openai) y [OpenClaw en Raspberry Pi](https://docs.openclaw.ai/install/raspberry-pi).
