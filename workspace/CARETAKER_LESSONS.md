# CARETAKER_LESSONS — diario de aprendizaje

Este archivo conserva el aprendizaje técnico del modo cuidador. No se borran los errores que después se resolvieron: se documenta la secuencia completa para no repetirlos.

## Plantilla de incidente

- Fecha y desencadenante:
- Observación y evidencia:
- Qué se hizo bien:
- Qué se hizo mal o se asumió sin pruebas:
- Impacto real o potencial:
- Corrección aplicada:
- Prueba final:
- Regla reutilizable:
- Estado: vigente o superada por otra lección.

## 2026-07-13 — procesos de Python aparentemente duplicados en Windows

- Fecha y desencadenante: primera prueba real del modo cuidador al investigar reinicios y transcripciones anómalas.
- Observación y evidencia: Windows mostraba `.venv\\Scripts\\python.exe -m tipi_voice` y el Python 3.12 global con la misma orden.
- Qué se hizo bien: se inspeccionaron procesos, Docker, salud y estado deseado antes de tocar el audio; se anunció la corrección prevista antes de ejecutarla.
- Qué se hizo mal o se asumió sin pruebas: se concluyó prematuramente que eran dos ejecuciones independientes sin comprobar `ParentProcessId`.
- Impacto real o potencial: terminar el supuesto duplicado habría terminado el proceso hijo de la única voz sana.
- Corrección aplicada: se canceló la acción y se comprobó el árbol completo: PowerShell → Python del entorno virtual → Python 3.12 real.
- Prueba final: el archivo de salud seguía actualizándose y los tres procesos formaban una única cadena padre-hijo.
- Regla reutilizable: en Windows, antes de terminar un supuesto proceso duplicado, comparar PID, ParentProcessId, hora de inicio, línea de comandos y ejecución raíz; una cadena del lanzador del entorno virtual cuenta como una sola instancia.
- Estado: vigente.

## 2026-07-15 — un diagnóstico recreó el gateway y aisló la voz

- Fecha y desencadenante: ejecución de `scripts/doctor.sh` sobre una instalación que usaba imágenes locales.
- Observación y evidencia: el script forzaba `compose.registry.yaml`, inició un CLI que no terminó y sustituyó el gateway. La voz compartía su namespace con el contenedor anterior mediante `network_mode: service:openclaw-gateway`, por lo que quedó reiniciándose aunque el gateway nuevo estaba sano.
- Qué se hizo mal o se asumió sin pruebas: distintas rutas operativas elegían combinaciones de Compose diferentes y el diagnóstico ejecutaba un comando interno lento y mutable.
- Impacto real o potencial: pérdida total de conversación después de una comprobación que debía ser de solo lectura.
- Corrección aplicada: todos los scripts usan un único `compose.yaml`; la voz usa la red normal y resuelve `openclaw-gateway`; el diagnóstico inspecciona salud, configuración, modelo, autenticación y estado JSON sin recrear contenedores. El actualizador identifica las imágenes realmente activas y evita reintentar un par ya rechazado.
- Prueba final: Compose validado, conexión real desde otro contenedor por DNS interno y emparejamiento exacto por `deviceId` completados sin afectar al servicio activo.
- Regla reutilizable: diagnósticos de solo lectura no deben cambiar overlays, imágenes ni namespaces; la recuperación debe referirse al ID ejecutado, no a una etiqueta mutable.
- Estado: vigente.

## 2026-07-15 — la interrupción por «Tipi» era frágil durante la reproducción

- Fecha y desencadenante: varias conversaciones en las que la persona repetía «Tipi» y la respuesta seguía reproduciéndose.
- Observación y evidencia: el detector exigía dos hipótesis parciales, aunque un «Tipi» real puede aparecer una sola vez y mutar enseguida a «ti». Con habla solapada, el reconocedor abierto llegó a oír «tv», mientras una gramática limitada recuperó «tipi» pero también forzó falsos positivos con «sí», «tipo», «típico» y «para ti». Además, audio ya recibido podía volver a entrar en la cola después de cancelarla.
- Corrección aplicada: una coincidencia exacta del reconocedor abierto interrumpe con el primer parcial. Bajo solapamiento se usa un segundo reconocedor sensible, pero requiere dos muestras y una pista fonética independiente y poco común del reconocedor abierto. El bloqueo durante playback baja a 450 ms y todo audio antiguo se suprime hasta la siguiente transcripción humana. Interrumpir ya no abandona una consulta activa, por lo que la nueva frase puede dirigirla.
- Prueba final: 57 pruebas ARM64 y una prueba con Vosk real: «Tipi» limpio detectado a 1120 ms, mezclado con habla detectado a 2300 ms y frase de fondo sin activación. También se verificaron cooldown, descarte de audio atrasado, conservación de tool call y orden estricto de eventos del gateway.
- Regla reutilizable: los parciales de ASR son acumulativos, no estables; una gramática pequeña nunca debe decidir sola y una cancelación local debe incluir una barrera contra datos que ya estaban en tránsito.
- Estado: vigente.

## 2026-07-15 — la consulta del agente bloqueaba su propio resultado

- Fecha y desencadenante: consultas habladas que respondían «Un momento» y agotaban 120 segundos aunque OpenClaw ya estaba trabajando.
- Observación y evidencia: el manejador de `talk.event` esperaba el resultado final del agente dentro del mismo bucle que recibía los eventos `chat`; mientras esperaba, el resultado que debía desbloquearlo no podía procesarse.
- Impacto real o potencial: pausas de dos minutos, respuestas de espera repetidas, cierre por silencio y errores `TimeoutError` o `Ejecución aborted` al decir «cállate».
- Corrección aplicada: el receptor WebSocket resuelve inmediatamente respuestas y resultados `chat`; los eventos Talk pasan a una cola ordenada independiente y cada consulta se ejecuta en su propia tarea. El timeout hablado es configurable y una cancelación esperada ya no genera un traceback de error.
- Prueba final: una sesión Talk real con audio sintético produjo transcripción, tool call, ejecución de `date`, resultado de OpenClaw y una única respuesta final en 31,5 segundos. Una prueba unitaria mantiene ocupado el manejador Talk y confirma que el resultado `chat` sigue llegando.
- Regla reutilizable: ningún manejador puede esperar un evento que solo el mismo bucle receptor es capaz de despachar; separar siempre recepción, correlación de respuestas y trabajo potencialmente lento.
- Estado: vigente.

## 2026-07-15 — Codex estaba instalado pero no era ejecutable por nombre

- Fecha y desencadenante: inspección de la imagen ARM64 exacta antes de publicarla.
- Observación y evidencia: `@openai/codex` 0.144.4 y su enlace existían en `/app/node_modules/.bin`, pero ese directorio no formaba parte de `PATH`; `codex --version` fallaba mientras OpenClaw, Docker y Compose sí respondían.
- Impacto real o potencial: una herramienta o tarea de autocuidado que invoque `codex` por nombre habría fallado pese a que la construcción de la imagen terminaba correctamente.
- Corrección aplicada: la imagen añade el directorio de binarios npm a `PATH` y durante cada build ejecuta Codex, Docker y Compose para comprobar que los tres son utilizables.
- Prueba final: dentro de la imagen ARM64, `codex --version` devolvió 0.144.4, Docker 29.6.1, Compose 5.2.0 y OpenClaw 2026.7.1.
- Regla reutilizable: comprobar el ejecutable desde el entorno final y con el usuario final; la presencia del paquete o de un enlace no demuestra que el comando esté accesible.
- Estado: vigente.

## 2026-07-15 — un control ALSA simple podía activar retorno de micrófono

- Fecha y desencadenante: validación del nuevo control de volumen Linux antes de desplegarlo.
- Observación y evidencia: el control simple `Mic` del USB contiene a la vez volumen de reproducción y captura; usar `sset Mic ... unmute` habría activado sidetone y posible realimentación.
- Impacto real o potencial: no llegó a producción; podía causar eco fuerte y falsos despertares.
- Corrección aplicada: se usan exclusivamente `Mic Capture Volume/Switch` y `Speaker Playback Volume/Switch` mediante `amixer cset`; si no existen, se conserva el control digital.
- Prueba final: prueba real en el USB manteniendo `Mic Playback` al 52 % y apagado, captura al 57 % y altavoces al 100 % encendidos.
- Regla reutilizable: no usar un control mixer agregado cuando el dispositivo expone direcciones separadas; comprobar siempre volumen y switch de playback y capture después del cambio.
- Estado: vigente.

## 2026-07-13 — consulta obligatoria demasiado lenta para conversación social

- Fecha y desencadenante: una prueba con un simple “Hola” tardó 6,7 segundos porque `force-agent-consult` envió incluso el saludo a GPT-5.6 Sol.
- Observación y evidencia: los logs mostraron una consulta forzada, un aviso “Un momento, lo consulto” y una respuesta final equivalente al saludo que Realtime podía resolver con su contexto local.
- Qué se hizo bien: la consulta forzada demostró que identidad, memoria, resultados y herramientas llegaban correctamente a la voz.
- Qué se hizo mal o se asumió sin pruebas: se trató la falta previa de identidad como motivo para obligar a consultar todos los turnos, aunque el problema original también se podía resolver inyectando una identidad breve en Realtime.
- Impacto real o potencial: latencia innecesaria, mayor consumo de API y una conversación poco natural en saludos y frases sociales.
- Corrección aplicada: se restauró el enrutamiento `provider-direct` conservando el contexto completo de identidad en Realtime y se definieron criterios explícitos: respuesta directa para conversación sencilla; consulta para memoria, archivos, información actual, estado real, herramientas, acciones, verificación o duda.
- Prueba final: configuración JSON validada y reglas híbridas presentes; pendiente de validación conversacional continuada en el entorno de exposición.
- Regla reutilizable: separar contexto de identidad de capacidad operativa; la voz puede resolver lo social con un contexto pequeño y delegar únicamente lo que necesita conocimiento persistente o acciones verificables.
- Estado: vigente.

## 2026-07-13 — Realtime emitió dos respuestas para una sola intervención

- Fecha y desencadenante: prueba del enrutamiento híbrido después de saludar y preguntar por la identidad de Tipi.
- Observación y evidencia: el primer saludo se respondió directamente en aproximadamente un segundo, pero Realtime generó después otro «Hola de nuevo» sin una nueva transcripción de la persona. La respuesta de identidad describió el robot sin mencionar con claridad su nombre ni tipdata.
- Qué se hizo bien: el modo híbrido evitó una consulta innecesaria a GPT-5.6 Sol y redujo la latencia y el consumo en conversación social.
- Qué se hizo mal o se asumió sin pruebas: se confió únicamente en la instrucción de emitir una respuesta por turno; no existía una protección local contra una segunda salida espontánea. La identidad breve tampoco obligaba a empezar por el nombre y la empresa.
- Impacto real o potencial: sensación de mantener dos conversaciones, consumo innecesario de Realtime y pérdida de identidad durante una presentación.
- Corrección aplicada: el puente marca como terminada la primera respuesta directa y cancela cualquier audio posterior mientras no llegue una nueva intervención. Las respuestas posteriores a una consulta de OpenClaw siguen permitidas. También se fijó una presentación inequívoca y una preferencia por una o dos frases, sin imponer un límite de longitud cuando se pide una explicación extensa.
- Prueba final: las pruebas cubren tanto el bloqueo de la segunda respuesta directa como la conservación de la respuesta final de OpenClaw.
- Regla reutilizable: las instrucciones de estilo no sustituyen a las garantías del programa; bloquear duplicados en el puente, pero expresar la brevedad como preferencia y no como un tope que impida responder completamente.
- Estado: vigente.

## 2026-07-13 — comando de Windows anidado incorrectamente

- Fecha y desencadenante: intento de recargar una mejora de la voz desde el modo cuidador.
- Observación y evidencia: las pruebas de código pasaban, pero el comando enviado al puente produjo errores de sintaxis y no llegó a cambiar procesos.
- Qué se hizo bien: se ejecutaron 16 pruebas antes del despliegue, se anunció el alcance y el fallo impidió una modificación parcial.
- Qué se hizo mal o se asumió sin pruebas: se añadió `powershell -Command` aunque `host-exec.mjs` ya ejecuta PowerShell en Windows; las capas de comillas permitieron además que el shell del contenedor alterara expresiones como `$_.CommandLine`. También se dejó un ayudante temporal con PID fijos, que habrían quedado obsoletos o podrían haber señalado otros procesos.
- Impacto real o potencial: no hubo impacto real porque PowerShell rechazó el comando antes de actuar; reintentarlo a ciegas habría podido terminar procesos equivocados.
- Corrección aplicada: se canceló la revisión antigua, se reinició solo el gateway para detener la tarea, se eliminó el ayudante de PID fijos y se dejó documentado que tras `--` debe pasarse PowerShell directamente.
- Prueba final: una ejecución directa de `Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version` mediante `host-exec.mjs` devolvió Windows 11 y código 0, sin CLIXML ni PowerShell anidado.
- Regla reutilizable: si una herramienta ya define el intérprete, no volver a envolver el comando en ese intérprete; ante un error de quoting, detener los reintentos mutables y validar primero con una orden de solo lectura. Nunca guardar PID concretos como mecanismo permanente: descubrir y validar el árbol en cada ejecución.
- Estado: vigente.

## 2026-07-13 — Realtime contestaba sin identidad y el ruido impedía el cierre

- Fecha y desencadenante: conversación de prueba en la que aparecieron transcripciones en polaco, chino, vietnamita y otros idiomas; Tipi dijo no tener nombre, no obedeció una orden de silencio y mantuvo una sesión abierta durante varios minutos.
- Observación y evidencia: los registros marcaban `consulto_openclaw=no` en las respuestas sobre identidad. La configuración usaba `consultRouting=provider-direct`, la transcripción no recibía idioma ni vocabulario, y el contador de inactividad se renovaba en cada trama que el VAD local confundía con voz. Consultas nacidas de transcripciones falsas tardaron entre 31 y 82 segundos y mantenían la sesión ocupada.
- Qué se hizo bien: se detuvo primero el proceso de voz, se conservaron los logs, se inspeccionó la implementación instalada de OpenClaw y se contrastaron los campos de transcripción con la referencia oficial de OpenAI antes de modificar el contenedor.
- Qué se hizo mal o se asumió sin pruebas: se había supuesto que `brain=agent-consult` obligaba a usar OpenClaw, aunque `consultRouting=provider-direct` permitía contestar directamente. También se trató cualquier trama marcada como voz como actividad humana confirmada.
- Impacto real o potencial: pérdida de identidad y memoria, respuestas inventadas sin herramientas, acciones de audio no verificadas, mayor consumo de API y una experiencia confusa en la exposición.
- Corrección aplicada: se activó `force-agent-consult`, se añadió la identidad completa a Realtime, se habilitaron idioma, vocabulario y reducción de ruido configurables, se endureció el VAD, se dejó de renovar el temporizador con ruido continuo y se implementaron órdenes locales de cierre en español y catalán. También se evita enviar texto vacío al control de consultas.
- Prueba final: 18 pruebas automáticas superadas; la imagen aplicó sus cinco parches; el Gateway quedó sano; una sesión Realtime real abrió y cerró con idioma `es`, reducción `near_field` y consulta forzada; GPT-5.6 Sol respondió que es Tipi, representa a tipdata y dispone de herramientas, con los archivos de identidad y contexto inyectados.
- Regla reutilizable: distinguir entre “tener disponible” un agente y “obligar a consultarlo”; no usar señales VAD crudas como actividad humana ilimitada; en voz multilingüe proporcionar idioma principal, vocabulario y reducción de ruido, y ejecutar las órdenes críticas de parada localmente antes de delegar en un modelo.
- Estado: vigente.
