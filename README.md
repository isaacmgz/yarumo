# Yarumo · demo

Casa virtual que aprende las rutinas de sus residentes y apaga lo que nadie está usando. Corre completa en un solo computador Linux con Home Assistant y contenedores Podman, sin hardware domótico.

Los specs están en [`docs/`](docs/) y son la fuente de verdad.

## Requisitos

- Linux (Fedora o Ubuntu) con IP fija en la red local (ver `HOST_IP`).
- Podman rootless y `podman compose` (en Fedora: `sudo dnf install podman podman-compose`).
- `curl` (lo usa `scripts/check-stack.sh`).
- Internet solo la primera vez, para descargar imágenes y el modelo.

## Puesta en marcha

```bash
cp .env.example .env              # editar HOST_IP, MQTT_PASSWORD, etc.
./scripts/mqtt-passwd.sh          # genera config/mosquitto/passwd desde .env
podman compose up -d              # Mosquitto, Home Assistant y Ollama
podman exec ollama ollama pull llama3.2:3b   # o el valor de OLLAMA_MODEL
./scripts/check-stack.sh          # estado de cada servicio
```

Sobre `config/mosquitto/passwd`: no se versiona. El script lo deja con dueño uid 1883 (el usuario `mosquitto` de la imagen) y permisos `0600`. Con Podman rootless ese uid corresponde a un subuid del host, así que no se puede leer directamente; para verlo o borrarlo use `podman unshare cat|rm config/mosquitto/passwd`. Si cambia la clave en `.env`, vuelva a correr el script y `podman restart mosquitto`.

## Firewall

Abrir solo Home Assistant (8123) y Savi (8088) a la red local. Ollama escucha solo en `127.0.0.1`.

```bash
# Fedora (firewalld)
sudo firewall-cmd --permanent --add-port=8123/tcp --add-port=8088/tcp
sudo firewall-cmd --reload

# Ubuntu (ufw)
sudo ufw allow 8123/tcp && sudo ufw allow 8088/tcp
```

Nada se expone a internet ni se abren puertos en el router.

## Pasos manuales en Home Assistant (una sola vez)

Detalle en [`docs/04-home-assistant.md`](docs/04-home-assistant.md).

1. Onboarding en `http://<HOST_IP>:8123`: usuario administrador y ubicación de la casa (zona `home`).
2. Agregar la integración **MQTT**: broker `127.0.0.1`, puerto `1883`, usuario y clave de `.env`.
3. Crear las **Áreas**: Sala, Cocina, Habitación principal, Habitación 2, Estudio.
4. Crear un **token de larga duración** (perfil → seguridad) y ponerlo en `.env` como `HA_TOKEN`.
5. Instalar la app **Home Assistant Companion** en el Android y en el iPhone, iniciar sesión con la URL local, dar permiso de ubicación "Siempre" (necesario para leer el nombre de la Wi-Fi) y permitir notificaciones.
6. Crear las personas `residente_1` (Android) y `residente_2` (iPhone) y asignarles el `device_tracker` de cada app.
7. Escribir en `config/homeassistant/packages/yarumo_presencia.yaml` los `entity_id` reales de los sensores de Wi-Fi de cada celular (hito H2) y crear `config/homeassistant/secrets.yaml` a partir de `secrets.yaml.example` con el nombre exacto de la Wi-Fi de la casa (`wifi_casa_ssid`). Ese archivo no se versiona.
8. Panel de **Energía**: `./scripts/ha-energia.sh` (consumo total, los 9 dispositivos y la tarifa de `TARIFA_COP_KWH`; con `0` queda sin precio). Se puede repetir; vuelva a correrlo si cambia la tarifa.

Dashboard: "Yarumo" en la barra lateral (`/yarumo-panel`), definido en `config/homeassistant/dashboards/yarumo.yaml`. La sección "Modo demo" solo aparece con `input_boolean.modo_demo` encendido. El iframe de Savi apunta a `http://192.168.20.40:8088/panel`; si cambia `HOST_IP`, actualizar esa línea.

Después de editar YAML de Home Assistant:

```bash
podman exec homeassistant python -m homeassistant --script check_config -c /config
podman restart homeassistant
```

Después de los pasos 2 y 4, `./scripts/check-stack.sh` también verifica el token y que la integración MQTT esté cargada.

## Comandos útiles

```bash
podman compose logs -f homeassistant   # logs de un servicio
podman compose down                    # detener todo (los volúmenes se conservan)
```
