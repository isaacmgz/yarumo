# 05 · Savi-IA (servicio `savi`)

Savi es la inteligencia que habita Yarumo. En esta demo hace cinco cosas: **observa** la casa, **encuentra patrones** de desperdicio, **propone** automatizaciones con evidencia, **las crea** cuando un humano aprueba y **cuenta** lo que se ahorra. Además **conversa** en español.

Principio de diseño: **la lógica es determinista y auditable; el LLM solo redacta y conversa.** Si Ollama se cae, Savi sigue funcionando con textos de plantilla.

## Módulos

```
services/savi/src/savi/
├─ main.py            # FastAPI, arranque de tareas
├─ config.py          # variables de entorno (pydantic-settings)
├─ ha_client.py       # WebSocket (eventos) + REST (estados, servicios, automatizaciones)
├─ mqtt_out.py        # sensores de Savi hacia HA por MQTT discovery
├─ store.py           # SQLite: eventos, sugerencias, ahorros, chat
├─ ingest.py          # suscripción a state_changed y caché de estados
├─ seed.py            # generador de rutina sintética
├─ detectors/
│  ├─ olvido_al_salir.py
│  ├─ luz_sin_movimiento.py
│  ├─ consumo_nocturno.py
│  └─ reglas_seguridad.py
├─ suggestions.py     # ciclo de vida, deduplicación, plantillas de automatización
├─ savings.py         # cálculo contrafactual de energía evitada
├─ llm.py             # cliente Ollama + plantillas de respaldo
├─ chat.py            # intenciones y respuestas
└─ web/               # panel (Jinja2 + HTMX, sin paso de build)
```

## Datos (SQLite en `/data/savi.db`)

| Tabla | Campos clave |
|---|---|
| `events` | `ts`, `entity_id`, `old_state`, `new_state`, `attributes_json`, `synthetic` (0/1) |
| `suggestions` | `id`, `detector`, `title`, `entities_json`, `evidence_json`, `est_kwh_month`, `est_cop_month`, `confidence` (`alta`/`media`), `status`, `automation_id`, `explanation`, `created_at`, `decided_at`, `decided_via` (`panel`/`celular`/`chat`) |
| `savings` | `id`, `suggestion_id`, `started_at`, `ended_at`, `devices_json`, `power_w`, `hours`, `kwh`, `cop`, `status` (`en_curso`/`cerrado`) |
| `chat_messages` | `ts`, `role`, `content` |

Estados de una sugerencia: `nueva → notificada → aprobada → activa` · o `rechazada` · y luego `desactivada` si alguien la apaga.

## 1. Ingesta

- Conexión WebSocket a `HA_URL/api/websocket`, autenticación con `HA_TOKEN`, `subscribe_events` de `state_changed`, `automation_triggered` y `mobile_app_notification_action`.
- Lista blanca de entidades: `light.*` y `switch.*` del contrato, `binary_sensor.movimiento_*`, `binary_sensor.puerta_principal`, `binary_sensor.residente_*_en_casa`, `binary_sensor.casa_ocupada`, `sensor.*_potencia`.
- Al arrancar, `GET /api/states` llena la caché de estados actuales.
- Reconexión con backoff exponencial (1 s → 30 s). Los eventos de potencia no se guardan en `events`; solo se mantiene el último valor en caché.

## 2. Siembra de rutina sintética

`POST /admin/seed?days=21&seed=42` genera eventos con `synthetic=1`, terminando ayer a medianoche. Con la misma semilla siempre sale la misma historia (la demo es reproducible).

Rutina modelada (parámetros en `seed.py`, no en el código de los detectores):

| Parámetro | Valor |
|---|---|
| `residente_1` sale entre semana | 7:10 ± 10 min, vuelve 18:30 ± 40 min |
| `residente_2` sale entre semana | 7:40 ± 15 min, vuelve 17:45 ± 30 min |
| Fin de semana | en casa, 1–2 salidas aleatorias de 1–4 h |
| Mañanas laborales | cocina, TV y PC encendidos entre 6:00 y la salida |
| Al salir el último, queda encendido | TV p = 0,7 · PC p = 0,6 · luz del estudio p = 0,3 |
| Luces sin movimiento ≥ 20 min con gente en casa | ~1 episodio cada 2 días |
| PC encendido toda la noche | p = 0,35 por noche |
| Plancha olvidada | 0 veces (se demuestra en vivo como regla de seguridad) |

Los eventos de movimiento se generan de forma coherente con la ocupación y con los dispositivos encendidos.

## 3. Detectores

Corren al arrancar, cada hora y con `POST /api/detectores/run`. Ventana de análisis: últimos 14 días.

### D1 · `olvido_al_salir` (el protagonista de la demo)

1. Encontrar cada **salida**: transición de `casa_ocupada` `on → off`.
2. En cada salida, anotar qué dispositivos controlables estaban `ON` (o se quedaron `ON` 2 min después).
3. Para cada dispositivo: `frecuencia = salidas con el dispositivo encendido / salidas totales`.
4. Proponer si `salidas ≥ 5` y `frecuencia ≥ 0,5`. Agrupar los dispositivos que pasen en **una** sugerencia.
5. Confianza `alta` si frecuencia ≥ 0,75; si no, `media`.

Evidencia guardada: número de salidas, frecuencia por dispositivo, fechas de ejemplo, mediana de horas de ausencia.

Ahorro mensual estimado:

```
salidas_mes   = salidas_en_ventana × 30 / 14
kWh_mes       = Σ_d ( potencia_d × frecuencia_d × mediana_horas_ausencia × salidas_mes ) / 1000
COP_mes       = kWh_mes × TARIFA_COP_KWH
```

Automatización que propone:

```yaml
alias: "Savi · Apagar lo que queda encendido al salir"
description: "Propuesta por Savi el <fecha>. Evidencia: en 12 de 15 salidas la TV quedó encendida…"
mode: single
triggers:
  - trigger: state
    entity_id: binary_sensor.casa_ocupada
    to: "off"          # el retardo ya está en el delay_off de casa_ocupada
actions:
  - action: homeassistant.turn_off
    target:
      entity_id: [switch.tv_sala, switch.pc_estudio]
  - action: notify.residentes
    data:
      title: "Savi"
      message: "Nadie quedó en casa. Apagué la TV y el PC del estudio."
```

### D2 · `luz_sin_movimiento`

Luz encendida con la casa ocupada y sin movimiento en su área durante ≥ 20 min. Proponer si hay ≥ 6 episodios en 14 días. Automatización: apagar esa luz tras 20 min sin movimiento en el área. El ahorro será pequeño (LED de 9 W) y **así se muestra**: es parte de ser honestos.

### D3 · `consumo_nocturno`

`pc_estudio` o `tv_sala` encendidos entre 00:00 y 05:00 sin movimiento en su área durante ≥ 30 min. Proponer si ocurre en ≥ 4 de 14 noches. Automatización: a partir de la 1:00, apagar si no hay movimiento en el área durante 30 min.

### R1 · `plancha_olvidada` (regla de seguridad, no aprendida)

No sale de patrones: es una regla que Savi ofrece desde el primer día y así se presenta ("esta no la aprendí, la traigo de fábrica"). Igual pasa por aprobación; en la demo queda aprobada desde `demo-reset.sh`.

Dos disparadores: `casa_ocupada` pasa a `off` con la plancha `ON`, **o** la plancha pasa a `ON` con la casa vacía. Acción: apagar de inmediato y notificar con prioridad alta.

### Reglas comunes

- **Deduplicación:** mismo detector + mismo conjunto de entidades → se actualiza la sugerencia existente, no se crea otra.
- **Respeto al "no":** una sugerencia rechazada no se vuelve a proponer en 14 días.
- **Nunca** proponer apagar algo que no esté en el contrato MQTT.

## 4. Aprobación y creación de la automatización

Vías para aprobar: botón en el panel, notificación accionable en el celular (`SAVI_APROBAR::<id>`) o el chat (con confirmación explícita).

Creación en HA:

1. `POST {HA_URL}/api/config/automation/config/savi_<id>` con la automatización en JSON. Es el endpoint que usa el editor de automatizaciones de HA; **no está en la documentación pública de la API REST**, así que va aislado en `ha_client.py` con un test de integración contra el HA real del stack.
2. Plan B si ese endpoint falla: escribir en `automations.yaml` (volumen compartido) y llamar `automation.reload`.
3. Verificar: buscar en `GET /api/states` la entidad `automation.*` cuyo atributo `id` sea `savi_<id>` (el `entity_id` lo deriva HA del alias, no del id). Guardarla en `suggestions.automation_id`.
4. Pasar la sugerencia a `activa` y avisar: "Listo, ya quedó. Te cuento cuando actúe."

Desactivar: `automation.turn_off` sobre esa entidad y estado `desactivada`.

## 5. Ahorro (energía evitada)

Supuesto contrafactual, visible en el panel: **"si Savi no hubiera apagado, el dispositivo habría seguido encendido hasta que alguien volviera, con un máximo de 8 h"**. Ese supuesto se sostiene en el historial (es justo lo que mostró el detector).

1. Al llegar `automation_triggered` de una automatización `savi_*`, tomar de la caché los dispositivos que estaban `ON` y su última potencia → registro `en_curso` en `savings`.
2. Cerrar el registro cuando ocurra el evento de fin según el detector (D1: `casa_ocupada → on`; D2: movimiento en el área; D3: 06:00), o a las 8 h.
3. `kWh = Σ potencia × horas / 1000` · `COP = kWh × TARIFA_COP_KWH`.
4. Mientras está `en_curso`, mostrar el acumulado en vivo (crece cada minuto).

Sensores que Savi publica en HA por MQTT discovery (dispositivo "Savi"):

| Entidad | Unidad | Clase |
|---|---|---|
| `sensor.savi_energia_evitada` | kWh | energy, `total_increasing` |
| `sensor.savi_ahorro_estimado` | COP | monetary, `total` |
| `sensor.savi_ahorro_mensual_proyectado` | COP | monetary |
| `sensor.savi_automatizaciones_activas` | — | — |
| `sensor.savi_sugerencias_pendientes` | — | — |

Si `TARIFA_VERIFICADA=false`, todo valor en COP lleva en el panel la marca "tarifa sin verificar".

## 6. LLM y chat

Cliente de Ollama (`/api/chat`) con `OLLAMA_MODEL`, temperatura 0,3, timeout 15 s. Si el modelo tiene modo de razonamiento (por ejemplo, Qwen3), desactivarlo para bajar latencia.

Usos:

1. **Redactar la explicación** de cada sugerencia (título de ≤ 8 palabras + 2–3 frases). Entrada: la evidencia en JSON. Respaldo: plantilla con los mismos datos.
2. **Conversar** en el panel.

Prompt de sistema (resumen; versión completa en `llm.py`):

> Eres Savi, la inteligencia de la casa Yarumo. Hablas español de Colombia, cálido y breve (máximo 3 frases salvo que te pidan detalle). Solo usas las cifras que vienen en el CONTEXTO; nunca inventes números. Cuando hables del historial, aclara que en esta demo es simulado. Los ahorros son estimados y lo dices así. Si no sabes algo, lo dices.

En cada turno se inyecta un CONTEXTO en JSON: estado actual de la casa, sugerencias con su evidencia, ahorro acumulado y proyectado, tarifa y si está verificada, últimos 20 eventos relevantes.

Acciones desde el chat: el LLM devuelve primero un JSON de intención (formato JSON forzado de Ollama, sin depender de *tool calling* de modelos pequeños):

| Intención | Efecto |
|---|---|
| `responder` | Solo texto |
| `explicar_sugerencia(id)` | Texto con evidencia |
| `aprobar_sugerencia(id)` | Pide confirmación ("¿La activo?"); ejecuta solo tras un "sí" en el siguiente turno |
| `rechazar_sugerencia(id)` | Igual, con confirmación |
| `resumen_hoy` | Consumo de hoy, lo que apagó Savi, ahorro |

Controlar dispositivos desde el chat queda fuera del MVP (hito extra, con lista blanca).

Preguntas que el chat debe responder bien en la demo:

- "¿Qué has aprendido de nosotros?"
- "¿Por qué apagaste la TV?"
- "¿Cuánto nos hemos ahorrado?"
- "¿De dónde sale ese número?" → explica la fórmula y el supuesto.

## 7. API HTTP (puerto 8088)

| Ruta | Uso |
|---|---|
| `GET /health` | Estado de HA (WS), MQTT y Ollama |
| `GET /panel` | Panel web (también embebido en el dashboard de HA) |
| `GET /api/sugerencias` | Lista con estado y evidencia |
| `POST /api/sugerencias/{id}/aprobar` · `/rechazar` · `/desactivar` | Ciclo de vida |
| `GET /api/ahorro` | Acumulado, en curso, proyectado, fórmula y supuestos |
| `POST /api/chat` `{ "mensaje": "..." }` | `{ "respuesta": "...", "accion": {...} }` |
| `POST /api/detectores/run` | Forzar análisis |
| `POST /admin/seed` · `POST /admin/reset` | Preparar la demo (solo con `DEMO_MODE=true`) |

## 8. Panel web

- Una sola página, apta para celular y para el iframe del dashboard.
- Arriba: contador de ahorro (kWh y COP, "estimado"), con un enlace "¿cómo se calcula?" que despliega la fórmula.
- Tarjetas de sugerencias: título, explicación, evidencia en una línea ("12 de 15 salidas"), ahorro mensual estimado, confianza, botones **Activar** / **Ahora no**.
- Etiquetas visibles: "datos simulados" si la evidencia viene de eventos sintéticos; "tarifa sin verificar" cuando aplique.
- Chat abajo.
- Sin definir identidad visual de marca (eso es otra decisión); usar estilo sobrio y neutro.

## 9. Tests

- Detectores sobre la historia sembrada con `seed=42`: deben producir exactamente D1 (TV + PC), al menos una D2 y una D3; ninguna sugerencia con la plancha salvo R1. Si con esa semilla no sale así, se cambia la semilla, nunca los umbrales de los detectores.
- Cálculo de ahorro con casos de borde: regreso antes de 1 min, ausencia > 8 h, varios dispositivos.
- LLM simulado (mock) y prueba de respaldo con Ollama apagado.
- Cliente de HA: test de integración que crea, verifica y borra una automatización `savi_test`.
- Chat: aprobar desde el chat no ejecuta nada sin el "sí" de confirmación.
