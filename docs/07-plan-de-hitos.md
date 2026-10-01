# 07 · Plan de hitos

Pensado para sesiones de trabajo con Claude Code de 2–3 horas, a ritmo de 10–15 h por semana. Cada hito cierra con algo que se puede mostrar. Estimado total: **4–5 semanas** dentro del Bloque 0.

Regla: no se empieza un hito sin que el anterior cumpla sus criterios de aceptación contra el stack corriendo.

## H0 · Base del stack (1 sesión) — ✅ Hecho (2026-09-30)

Construir: `compose.yaml`, `.env.example`, `config/mosquitto` con usuario, `configuration.yaml` base, `scripts/check-stack.sh`, README con los pasos manuales de `04-home-assistant.md`.

Aceptación:
- `podman compose up -d` levanta Mosquitto, HA y Ollama sin errores en un Linux limpio.
- HA responde en `http://<HOST_IP>:8123` desde PC-B y desde ambos celulares.
- Integración MQTT conectada; `mosquitto_sub` con credenciales funciona y sin credenciales falla.
- `check-stack.sh` reporta el estado de cada servicio.

## H1 · Casa simulada (1–2 sesiones) — ✅ Hecho (2026-09-30)

Construir: servicio `sim-casa` según `03-contrato-mqtt.md`, con API de escenarios y tests de contrato.

Aceptación:
- Las 34 entidades (9 dispositivos × 3 entidades + 7 sensores) aparecen solas en HA, en sus áreas, con los `entity_id` del contrato.
- Encender y apagar desde HA funciona en < 1 s; la potencia cambia y la energía se integra bien (test de 1 %).
- Reiniciar `sim-casa` no reinicia los acumulados de energía.
- Matar el proceso deja las entidades como "no disponible" (LWT).

## H2 · Presencia, energía y dashboard (1–2 sesiones)

Construir: paquetes `yarumo_presencia`, `yarumo_energia`, `yarumo_demo`; dashboard "Yarumo"; grupo `notify.residentes`; panel de Energía.

Aceptación: los criterios de `04-home-assistant.md`. Prueba real con los dos celulares: salir y entrar de la Wi-Fi cambia la ocupación y el simulador responde.

## H3 · Savi: ingesta, siembra y detectores (2 sesiones)

Construir: `store`, `ingest`, `seed`, detectores D1–D3 y R1, `suggestions`, API de sugerencias y un panel mínimo (lista sin estilo).

Aceptación:
- `POST /admin/seed` con `seed=42` crea 21 días de eventos marcados como sintéticos.
- Los detectores producen exactamente las sugerencias esperadas (ver tests en `05-savi-ia.md`).
- Correr los detectores dos veces no duplica sugerencias.
- Cada sugerencia trae su evidencia y su ahorro mensual estimado con la fórmula reproducible a mano.

## H4 · Savi actúa y cuenta (2 sesiones)

Construir: creación de automatizaciones en HA (con plan B), notificaciones accionables, escucha de acciones, cálculo de ahorro, sensores MQTT de Savi.

Aceptación:
- Aprobar desde el celular crea `automation.*` con `id: savi_<id>` y la sugerencia pasa a `activa`.
- Con la casa vacía, la automatización apaga lo indicado y se abre un registro de ahorro `en_curso` que crece en vivo.
- Al volver alguien, el registro se cierra con kWh y COP correctos (comprobado a mano una vez).
- Los sensores `sensor.savi_*` aparecen en HA y en el dashboard.
- Antes de cerrar el hito: elegir el modelo de Ollama según calidad del español y latencia en PC-A, y anotarlo en `05-savi-ia.md`.

## H5 · Savi conversa + panel final (1–2 sesiones)

Construir: `llm.py` con plantillas de respaldo, `chat.py` con intenciones y confirmación, panel final (tarjetas, contador, fórmula, chat, etiquetas de honestidad).

Aceptación:
- Las cuatro preguntas de la demo se responden bien en < 10 s y sin cifras inventadas (comparar contra `/api/ahorro`).
- Con Ollama detenido, el panel y las explicaciones siguen funcionando con plantillas.
- Aprobar por chat exige el "sí" de confirmación.
- El panel se ve bien en el celular y dentro del iframe de HA.

## H6 · Ensayo general (1 sesión)

Construir: `scripts/demo-reset.sh`, ajustes finales de tiempos, checklist de `06-guion-demo.md`.

Aceptación:
- Tres corridas completas del guion seguidas, con reinicio entre ellas, sin intervención en la terminal.
- Prueba sin internet (paso 6) superada.
- Una toma de video completa grabada.

## Extras (solo después de H6)

- **Voz:** Whisper + Piper (protocolo Wyoming) y Assist de HA desde el celular, con Ollama como agente de conversación.
- **Cámara:** el Android viejo o uno prestado como cámara IP (app IP Webcam + integración Android IP Webcam) con detección de movimiento para la sala.
- **Control por chat** con lista blanca de dispositivos.
- **Prueba de reemplazo:** documentar cómo un enchufe Zigbee real tomaría el `entity_id` de `switch.tv_sala` (preparación del Bloque 1).

## Cómo arrancar con Claude Code

1. Crear la carpeta del repo, copiar `CLAUDE.md` y `docs/`, y hacer `git init`.
2. Abrir Claude Code en esa carpeta.
3. Primer mensaje sugerido:

> Lee CLAUDE.md y todos los archivos de docs/. Luego propón el plan para el hito H0 de docs/07-plan-de-hitos.md: archivos que vas a crear y cómo vamos a verificar cada criterio de aceptación. No escribas código hasta que apruebe el plan.

4. Al cerrar cada hito: commit con el nombre del hito y actualizar este archivo marcando el hito como hecho, con la fecha.
