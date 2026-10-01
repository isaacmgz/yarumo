# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Yarumo Demo

Este repo es la **mini demo de Yarumo**: una casa virtual que aprende las rutinas de sus residentes y apaga lo que nadie está usando. Corre completa en un solo computador Linux, sin hardware domótico, con Home Assistant y contenedores Podman.

Lee los specs en `docs/` antes de escribir código. Son la fuente de verdad; si algo del código contradice un spec, gana el spec (o se actualiza el spec primero, de forma explícita).

**Estado actual:** solo existen los specs en `docs/`. Aún no hay `compose.yaml`, `services/`, `config/` ni `scripts/`; la estructura objetivo está en `docs/02-arquitectura.md`. Se construye por hitos (H0 → H6) en orden estricto: no se empieza un hito sin que el anterior cumpla sus criterios de aceptación contra el stack corriendo. Al cerrar un hito, marcarlo como hecho (con fecha) en `docs/07-plan-de-hitos.md`.

## Arquitectura (visión general)

Todo corre en PC-A con `network_mode: host` (decisión de demo, no de producción). Flujo de datos:

- `sim-casa` (:8090, API de escenarios) publica estado y MQTT discovery de los dispositivos simulados → **Mosquitto** (:1883, con usuario/contraseña).
- **Home Assistant** (:8123) descubre las entidades vía MQTT; maneja presencia (apps Companion de los celulares), dashboard "Yarumo", energía y notificaciones.
- `savi` (FastAPI :8088, SQLite en `/data/savi.db`) escucha eventos de HA por **WebSocket**, llama servicios por **REST**, crea automatizaciones `automation.savi_<id>`, y publica sus propios sensores `sensor.savi_*` de vuelta por **MQTT**.
- `savi` usa **Ollama** (solo `127.0.0.1:11434`) únicamente para redactar/conversar; los detectores y el ahorro son deterministas y tienen plantilla de respaldo si el LLM falla.
- PC-B muestra el dashboard de HA y el panel de Savi en modo kiosko.

| Documento | Para qué |
|---|---|
| `docs/01-vision-y-alcance.md` | Qué demuestra la demo, qué queda fuera |
| `docs/02-arquitectura.md` | Servicios, red, puertos, compose, hardware |
| `docs/03-contrato-mqtt.md` | Dispositivos simulados: tópicos, payloads, discovery |
| `docs/04-home-assistant.md` | Entidades, presencia, dashboard, energía |
| `docs/05-savi-ia.md` | Ingesta, detectores, sugerencias, ahorro, chat |
| `docs/06-guion-demo.md` | Guion de 5 minutos con plan B por paso |
| `docs/07-plan-de-hitos.md` | Orden de construcción y criterios de aceptación |

## Nombres (no cambiar)

- **Yarumo** es el nombre del proyecto/producto. No es la empresa, ni la SAS, ni una marca madre. No escribir "Yarumo S.A.S." ni similares.
- **Savi-IA** es la inteligencia que habita Yarumo. En la UI se presenta como "Savi". No es el nombre del proyecto.
- Eslogan base: *"Tu casa aprende tus rutinas y deja de gastar energía cuando nadie la está usando."*

## Stack

- Linux (Fedora o Ubuntu), **Podman** rootless + `podman compose` (compatible con Docker Compose).
- Home Assistant Container (`ghcr.io/home-assistant/home-assistant:stable`), Mosquitto 2, Ollama.
- Servicios propios en **Python 3.12**: `sim-casa` (simulador de dispositivos) y `savi` (Savi-IA). FastAPI, paho-mqtt 2.x, httpx, websockets, SQLite. Gestión con `uv`.
- Tests con `pytest`. Lint/format con `ruff`.

## Convenciones

- Código, nombres de funciones y variables: inglés. Textos que ve el usuario (UI, notificaciones, respuestas de Savi): **español de Colombia, cálido y breve**.
- `entity_id`, `object_id` y tópicos MQTT: español en snake_case, tal como están en `docs/03-contrato-mqtt.md`. No inventar entidades nuevas sin agregarlas primero al contrato.
- Configuración por variables de entorno (`.env`, nunca commiteado; hay `.env.example`).
- Volúmenes de Podman con `:Z` (SELinux en Fedora).
- Todo servicio expone `GET /health` si tiene HTTP.

## Reglas de honestidad (importantes para la demo y el pitch)

1. **Nada de cifras inventadas.** Toda cifra de energía o pesos sale de un cálculo trazable (potencia nominal × tiempo × tarifa). Las potencias son supuestos nominales documentados en el contrato MQTT.
2. **Lo simulado se dice.** Los datos históricos sembrados llevan `synthetic=1` y la UI muestra la etiqueta "datos simulados". El ahorro se muestra como "estimado".
3. **La tarifa se marca.** Mientras `TARIFA_COP_KWH` no venga de una factura real, la UI muestra "tarifa sin verificar".
4. **El LLM no calcula.** Los detectores y el ahorro son código determinista. El LLM solo redacta y conversa con números que se le entregan; si el LLM falla, se usa una plantilla de texto.

## Comandos

```bash
podman compose up -d            # levantar todo
podman compose logs -f savi     # ver logs de un servicio
uv run pytest                   # tests (desde services/sim-casa o services/savi)
uv run pytest tests/test_x.py::test_name   # un solo test
./scripts/check-stack.sh        # estado de cada servicio del stack
uv run ruff check . && uv run ruff format .
./scripts/seed-history.sh       # sembrar 21 días de rutina sintética en Savi
./scripts/demo-reset.sh         # dejar la casa en estado inicial de demo
```

## Lo que NO se hace en este repo

- No comprar ni asumir hardware domótico (Zigbee, enchufes reales, etc.). Eso es Bloque 1.
- No depender de internet para la funcionalidad central (excepción conocida: push a celulares).
- No exponer Home Assistant a internet ni abrir puertos en el router.
- No guardar tokens ni contraseñas en el repo.

## Cómo verificar antes de decir "listo"

Cada hito de `docs/07-plan-de-hitos.md` tiene criterios de aceptación. Un hito está listo cuando sus tests pasan y sus criterios se comprobaron contra el stack corriendo, no solo en tests unitarios.
