# 04 · Home Assistant

## Configuración base

`config/homeassistant/configuration.yaml`:

```yaml
default_config:

homeassistant:
  name: Casa Yarumo (demo)
  time_zone: America/Bogota
  unit_system: metric
  currency: COP
  country: CO
  packages: !include_dir_named packages

automation: !include automations.yaml   # aquí escribe Savi sus automatizaciones aprobadas
script: !include scripts.yaml

recorder:
  purge_keep_days: 30
  include:
    entities:
      - sensor.casa_potencia_total   # el dashboard grafica sus últimas 6 h
  exclude:
    entity_globs:
      - sensor.*_potencia      # la potencia cambia mucho; Savi la lee en vivo
```

Organizar todo lo propio en `packages/`:

| Paquete | Contenido |
|---|---|
| `yarumo_presencia.yaml` | Sensores de presencia por residente, `casa_ocupada`, publicación a MQTT |
| `yarumo_energia.yaml` | Consumo total de la casa (W y kWh) |
| `yarumo_demo.yaml` | Controles del modo demo y scripts de escena |

## Pasos manuales únicos (no automatizables, documentar en README)

1. Onboarding de HA en `http://<HOST_IP>:8123`: usuario administrador, ubicación de la casa (zona `home`).
2. Agregar la integración **MQTT** (broker `127.0.0.1`, puerto 1883, usuario y clave de `.env`).
3. Crear las **Áreas**: Sala, Cocina, Habitación principal, Habitación 2, Estudio.
4. Crear un **token de larga duración** (perfil → seguridad) y ponerlo en `.env` como `HA_TOKEN`.
5. Instalar la app **Home Assistant Companion** en el Android y en el iPhone, iniciar sesión con la URL local, dar permiso de ubicación "Siempre" (necesario para leer el nombre de la Wi-Fi) y permitir notificaciones.
6. Crear las personas `residente_1` (Android) y `residente_2` (iPhone) y asignarles el `device_tracker` de cada app.
7. Escribir en `packages/yarumo_presencia.yaml` los `entity_id` reales de los sensores de Wi-Fi de cada celular (ver abajo) y poner el nombre de la Wi-Fi de la casa en `secrets.yaml` (`wifi_casa_ssid`, plantilla en `secrets.yaml.example`; no se versiona).

## Presencia

Señal principal: **nombre de la Wi-Fi** conectada (rápida y local). Respaldo: `device_tracker` en zona `home`. Encima, un **override de demo** por si un celular se demora en vivo.

| Celular | Sensor de Wi-Fi que expone Companion (verificar nombre exacto al instalar) |
|---|---|
| Android | `sensor.<dispositivo>_wifi_connection` (SSID) |
| iPhone | `sensor.<dispositivo>_ssid` |

Entidades a crear:

| Entidad | Tipo | Lógica |
|---|---|---|
| `input_select.presencia_residente_1` | helper | `auto` / `en_casa` / `fuera` |
| `input_select.presencia_residente_2` | helper | igual |
| `input_text.wifi_casa_ssid` | helper (`mode: password`) | SSID de la casa, inicializado con `!secret wifi_casa_ssid` (los templates no pueden leer `!secret`) |
| `binary_sensor.residente_1_en_casa` | template | si el select ≠ `auto`, manda el select; si no, SSID == `input_text.wifi_casa_ssid`; el tracker == `home` solo se usa si el sensor de Wi-Fi está `unknown`/`unavailable` (con un "o" simple, el GPS mantendría al residente en casa al apagar la Wi-Fi) |
| `binary_sensor.residente_2_en_casa` | template | igual |
| `binary_sensor.casa_ocupada` | template | algún residente en casa; `delay_off` configurable (`input_number.retardo_casa_vacia_s`, por defecto 30 s en demo, 300 s en uso normal) |

Automatización fija `yarumo_publicar_ocupacion`: cuando cambia `binary_sensor.casa_ocupada`, publica `true`/`false` retenido en `yarumo/presencia/ocupada`.

> Momento de demo: en el Android, apagar la Wi-Fi equivale a "salir de casa" en segundos. El iPhone puede tardar más en reportar en segundo plano; para él, usar el override.

## Energía

| Entidad | Tipo | Lógica |
|---|---|---|
| `sensor.casa_potencia_total` | template, W | suma de los 9 `sensor.*_potencia` |
| `sensor.casa_energia_total` | template, kWh, `total_increasing` | suma de los 9 `sensor.*_energia` |

Panel de **Energía** de HA:

- Consumo de red: `sensor.casa_energia_total` (rotulado en el dashboard como "medición simulada").
- Dispositivos individuales: los 9 `sensor.*_energia`.
- Precio: tarifa fija igual a `TARIFA_COP_KWH`. Si vale `0` (sin definir), el panel queda sin precio en vez de mostrar costo cero.
- Se configura por WebSocket (`energy/save_prefs`) con `./scripts/ha-energia.sh`; se puede repetir sin problema.

## Notificaciones

- Servicios `notify.mobile_app_<android>` y `notify.mobile_app_<iphone>`, agrupados en `notify.residentes` (grupo de notificación).
- Savi envía **notificaciones accionables** con acciones `SAVI_APROBAR::<sugerencia_id>` y `SAVI_RECHAZAR::<sugerencia_id>`. Al tocar, HA emite el evento `mobile_app_notification_action`, que Savi escucha por WebSocket.
- Sin internet, el push no llega: Savi además crea una `persistent_notification` y muestra el aviso en su panel.

## Automatizaciones de Savi

- Las crea Savi tras una aprobación, con `id: savi_<sugerencia_id>` y `alias: "Savi · <título>"`. Ver mecanismo en `05-savi-ia.md`.
- Siempre incluyen en `description` la evidencia y la fecha de aprobación, para que cualquiera entienda por qué existen.
- Nunca se edita a mano una automatización `savi_*`; se desactiva desde Savi o desde HA.

## Dashboard "Yarumo" (panel de pared en PC-B)

Dashboard en modo *secciones*, pensado para pantalla horizontal de portátil. Orden:

1. **Casa ahora:** tarjetas de los dos residentes (en casa / fuera), `casa_ocupada`, temperatura de la sala, hora.
2. **Consumo ahora:** `sensor.casa_potencia_total` grande (gauge), gráfico de las últimas 6 h.
3. **Savi:** `sensor.savi_energia_evitada` (kWh), `sensor.savi_ahorro_estimado` (COP) con la leyenda "estimado", número de automatizaciones activas, y una tarjeta *webpage* (iframe) con `http://<HOST_IP>:8088/panel`.
4. **Cuartos:** una tarjeta por área con sus luces, enchufes y movimiento.
5. **Modo demo** (visible solo si `input_boolean.modo_demo` está activo): selects de presencia, botones de escenas (llaman a la API de `sim-casa` con `rest_command`), botón "reiniciar demo".

`rest_command` necesarios: `sim_escenario` (POST a `http://127.0.0.1:8090/escenarios/{{ nombre }}`).

## Criterios de aceptación

- Las 34 entidades del simulador (9 dispositivos con su potencia y energía, más 7 sensores) aparecen solas por discovery, asignadas a sus áreas.
- Encender `switch.tv_sala` desde el dashboard cambia la potencia total en < 2 s.
- Apagar la Wi-Fi del Android pone `binary_sensor.residente_1_en_casa` en `off` en < 30 s.
- Con ambos residentes fuera, `binary_sensor.casa_ocupada` pasa a `off` tras el retardo y el simulador deja de generar movimiento.
- El panel de Energía muestra consumo por dispositivo después de 1 h de uso.
- Una notificación accionable de prueba llega a ambos celulares y su acción se ve como evento en HA.
