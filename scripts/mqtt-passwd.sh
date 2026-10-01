#!/usr/bin/env bash
# Generate config/mosquitto/passwd from MQTT_USER / MQTT_PASSWORD in .env.
#
# Ownership: the file ends up owned by uid/gid 1883 (the `mosquitto` user inside
# the image) with mode 0600, as Mosquitto 2 expects. Under rootless Podman that
# uid maps to a host subuid, so your own user cannot read it directly; use
# `podman unshare cat config/mosquitto/passwd` or just re-run this script.
# To delete it: `podman unshare rm config/mosquitto/passwd`.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${ENV_FILE:-$repo_root/.env}"
image="docker.io/library/eclipse-mosquitto:2"

if [[ ! -f "$env_file" ]]; then
  echo "ERROR: $env_file not found. Run: cp .env.example .env" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

: "${MQTT_USER:?MQTT_USER is not set in $env_file}"
: "${MQTT_PASSWORD:?MQTT_PASSWORD is not set in $env_file}"

if [[ "$MQTT_PASSWORD" == "cambiar" ]]; then
  echo "WARN: MQTT_PASSWORD still has the example value; change it in $env_file." >&2
fi

# Credentials travel as env vars (not argv of `podman run`).
# SELinux labeling is disabled for this one-shot container so it does not
# relabel the directory out from under a running mosquitto container.
podman run --rm \
  --security-opt label=disable \
  -e MQTT_USER -e MQTT_PASSWORD \
  -v "$repo_root/config/mosquitto:/mosquitto/config" \
  "$image" \
  sh -c 'set -e
    f=/mosquitto/config/passwd
    rm -f "$f"
    mosquitto_passwd -b -c "$f" "$MQTT_USER" "$MQTT_PASSWORD"
    chown 1883:1883 "$f"
    chmod 0600 "$f"'

echo "OK: config/mosquitto/passwd generated for user '$MQTT_USER'."
echo "    Restart the broker to load it: podman restart mosquitto"
