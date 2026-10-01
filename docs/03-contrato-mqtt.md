# 03 · Contrato MQTT del simulador (`sim-casa`)

Este contrato es la frontera entre la casa simulada y todo lo demás. Cuando lleguen dispositivos reales (Bloque 1), deben quedar con los **mismos `entity_id`** para que Savi y las automatizaciones sigan funcionando sin cambios.

## Convenciones

- Prefijo propio: `yarumo/casa/<object_id>/...`
- Discovery de Home Assistant por entidad: `homeassistant/<component>/yarumo/<object_id>/config` (retenido).
- Disponibilidad común (LWT): `yarumo/casa/disponible` → `online` / `offline` (retenido).
- Estados retenidos; comandos no retenidos.
- QoS 1 para comandos y estados.
- Todas las entidades se agrupan en un dispositivo HA por cuarto (`device.identifiers = ["yarumo_<cuarto>"]`, `manufacturer = "Yarumo (simulado)"`, `model = "sim-casa"`).

## Dispositivos controlables (9)

Las potencias son **supuestos nominales** para la simulación, no mediciones. Se documentan aquí para que todo cálculo de ahorro sea trazable.

| object_id | Componente HA | Cuarto | Potencia encendido (W) | Standby (W) | Nota |
|---|---|---|---|---|---|
| `luz_sala` | light | sala | 9 | 0 | LED |
| `luz_cocina` | light | cocina | 9 | 0 | LED |
| `luz_habitacion_principal` | light | habitacion_principal | 9 | 0 | LED |
| `luz_habitacion_2` | light | habitacion_2 | 9 | 0 | LED |
| `luz_estudio` | light | estudio | 9 | 0 | LED |
| `tv_sala` | switch | sala | 90 | 1 | TV 43" aprox. |
| `pc_estudio` | switch | estudio | 150 | 2 | PC de escritorio + monitor |
| `ventilador_habitacion_principal` | switch | habitacion_principal | 55 | 0 | Ventilador de pedestal |
| `plancha_ropa` | switch | habitacion_2 | 1000 | 0 | Promedio con termostato (ciclo ~1200 W) |

Cada dispositivo controlable expone **tres entidades**:

| Entidad | Tópico de estado | Tópico de comando | Payload |
|---|---|---|---|
| `light.<id>` o `switch.<id>` | `yarumo/casa/<id>/estado` | `yarumo/casa/<id>/set` | `ON` / `OFF` |
| `sensor.<id>_potencia` | `yarumo/casa/<id>/potencia` | — | número en W, ej. `90.0` |
| `sensor.<id>_energia` | `yarumo/casa/<id>/energia` | — | número en kWh acumulado, 4 decimales |

- `potencia`: `device_class: power`, `unit_of_measurement: W`, `state_class: measurement`. Se publica en cada cambio de estado y cada 30 s.
- `energia`: `device_class: energy`, `unit_of_measurement: kWh`, `state_class: total_increasing`. Se integra cada segundo y se publica cada 30 s. El acumulado se persiste en disco para sobrevivir reinicios.

## Sensores (7)

| object_id | Componente HA | device_class | Tópico | Payload |
|---|---|---|---|---|
| `movimiento_sala` | binary_sensor | motion | `yarumo/casa/movimiento_sala/estado` | `ON`/`OFF` |
| `movimiento_cocina` | binary_sensor | motion | `yarumo/casa/movimiento_cocina/estado` | `ON`/`OFF` |
| `movimiento_habitacion_principal` | binary_sensor | motion | `.../movimiento_habitacion_principal/estado` | `ON`/`OFF` |
| `movimiento_habitacion_2` | binary_sensor | motion | `.../movimiento_habitacion_2/estado` | `ON`/`OFF` |
| `movimiento_estudio` | binary_sensor | motion | `.../movimiento_estudio/estado` | `ON`/`OFF` |
| `puerta_principal` | binary_sensor | door | `yarumo/casa/puerta_principal/estado` | `ON` (abierta) / `OFF` |
| `temperatura_sala` | sensor | temperature | `yarumo/casa/temperatura_sala/estado` | °C, ej. `23.4` |

Comportamiento simulado:

- **Movimiento:** si la casa está ocupada (ver abajo), genera pulsos `ON` → `OFF` (30 s) en los cuartos con dispositivos encendidos, con probabilidad configurable. Si la casa está vacía, no genera movimiento.
- **Puerta:** pulso `ON` de 5 s cuando cambia la ocupación (alguien entra o sale).
- **Temperatura:** curva diaria suave para Medellín (mín. ~18 °C a las 5:00, máx. ~27 °C a las 14:00) con ruido de ±0,3 °C.

## Entrada desde Home Assistant hacia el simulador

| Tópico | Publica | Payload | Uso |
|---|---|---|---|
| `yarumo/presencia/ocupada` | automatización de HA | `true` / `false` (retenido) | El simulador genera movimiento y pulsos de puerta |

## Ejemplos de discovery

`homeassistant/switch/yarumo/tv_sala/config`

```json
{
  "name": "TV",
  "unique_id": "yarumo_tv_sala",
  "object_id": "tv_sala",
  "state_topic": "yarumo/casa/tv_sala/estado",
  "command_topic": "yarumo/casa/tv_sala/set",
  "availability_topic": "yarumo/casa/disponible",
  "icon": "mdi:television",
  "device": {
    "identifiers": ["yarumo_sala"],
    "name": "Sala",
    "manufacturer": "Yarumo (simulado)",
    "model": "sim-casa",
    "suggested_area": "Sala"
  }
}
```

`homeassistant/sensor/yarumo/tv_sala_energia/config`

```json
{
  "name": "TV energía",
  "unique_id": "yarumo_tv_sala_energia",
  "object_id": "tv_sala_energia",
  "state_topic": "yarumo/casa/tv_sala/energia",
  "availability_topic": "yarumo/casa/disponible",
  "device_class": "energy",
  "unit_of_measurement": "kWh",
  "state_class": "total_increasing",
  "device": { "identifiers": ["yarumo_sala"] }
}
```

> Nota para la implementación: confirmar contra la documentación vigente de la integración MQTT de Home Assistant que `object_id` sigue fijando el `entity_id`. Si cambió, ajustar el campo equivalente; el `entity_id` final es lo que no puede cambiar.
>
> Verificado en H1 (2026-09-30): Home Assistant reemplazó `object_id` por `default_entity_id` (`"<component>.<object_id>"`) y dejó de usarlo en 2026.4. `sim-casa` envía ambos campos; los 34 `entity_id` del contrato se comprobaron en Home Assistant.

## Sensores de Savi (publica `savi`, no el simulador)

Savi publica sus cifras como sensores MQTT de HA, en un dispositivo propio "Savi" (`device.identifiers = ["yarumo_savi"]`, `manufacturer = "Yarumo"`, `model = "savi"`). Las cifras son **estimadas** (ver `05-savi-ia.md` §5).

- Prefijo: `yarumo/savi/<object_id>/estado` (retenido, QoS 1).
- Discovery: `homeassistant/sensor/yarumo/<object_id>/config` (retenido), con `unique_id = "yarumo_<object_id>"` y `default_entity_id = "sensor.<object_id>"`.
- Disponibilidad (LWT): `yarumo/savi/disponible` → `online` / `offline` (retenido).
- Si un valor no se puede calcular (por ejemplo, COP sin tarifa), se publica `None` y HA lo muestra como desconocido; nunca se publica un cero inventado.

| object_id | Unidad | device_class | state_class | Valor |
|---|---|---|---|---|
| `savi_energia_evitada` | kWh | energy | total_increasing | kWh evitados: registros cerrados + en curso |
| `savi_ahorro_estimado` | COP | monetary | total | `energia_evitada × TARIFA_COP_KWH` (`None` si la tarifa es 0) |
| `savi_ahorro_mensual_proyectado` | COP | monetary | total | Σ COP/mes estimado de las sugerencias activas |
| `savi_automatizaciones_activas` | — | — | measurement | Sugerencias en estado `activa` |
| `savi_sugerencias_pendientes` | — | — | measurement | Sugerencias `nueva` o `notificada` |

## API HTTP de escenarios (`sim-casa`, puerto 8090)

Para preparar y controlar la demo sin tocar Home Assistant.

| Método y ruta | Efecto |
|---|---|
| `GET /health` | `{"ok": true, "mqtt": "connected"}` |
| `GET /dispositivos` | Estado, potencia y energía de cada dispositivo |
| `POST /dispositivos/{id}` con `{"estado": "ON"}` | Cambia el estado (equivale al comando MQTT) |
| `POST /escenarios/manana_laboral` | Luces de cocina y habitación, TV y PC encendidos |
| `POST /escenarios/olvido_salida` | Deja TV, PC y luz del estudio encendidos; el resto apagado |
| `POST /escenarios/plancha_olvidada` | Enciende la plancha |
| `POST /escenarios/noche` | Solo luz de habitación principal y ventilador |
| `POST /escenarios/reset` | Todo apagado, contadores de energía intactos |

## Tests de contrato (obligatorios)

- Cada dispositivo publica su discovery con `unique_id` y `object_id` esperados.
- `ON` en `/set` → estado `ON` y potencia nominal en menos de 1 s.
- La energía crece de forma monótona y coincide con potencia × tiempo (tolerancia 1 %).
- Con `yarumo/presencia/ocupada = false` no se publica movimiento.
- El LWT publica `offline` si el proceso muere.
