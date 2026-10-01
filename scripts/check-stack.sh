#!/usr/bin/env bash
# Report the status of every service in the Yarumo stack.
# Each check prints OK, FAIL or WARN; the script exits non-zero if any check FAILs.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${ENV_FILE:-$repo_root/.env}"

if [[ -f "$env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
else
  echo "WARN: $env_file not found; using defaults (cp .env.example .env)."
fi

HOST_IP="${HOST_IP:-127.0.0.1}"
HA_URL="${HA_URL:-http://127.0.0.1:8123}"
HA_TOKEN="${HA_TOKEN:-}"
MQTT_PORT="${MQTT_PORT:-1883}"
MQTT_USER="${MQTT_USER:-}"
MQTT_PASSWORD="${MQTT_PASSWORD:-}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:4b}"

failures=0

ok()   { printf '  [ OK ] %s\n' "$1"; }
fail() { printf '  [FAIL] %s\n' "$1"; failures=$((failures + 1)); }
warn() { printf '  [WARN] %s\n' "$1"; }

# HTTP status code of a GET, or 000 if unreachable. Extra args go to curl.
http_code() {
  local url="$1"; shift
  curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$@" "$url" 2>/dev/null || true
}

container_running() {
  local name="$1" state
  state="$(podman container inspect -f '{{.State.Running}}' "$name" 2>/dev/null || true)"
  [[ "$state" == "true" ]]
}

echo "== Containers"
for svc in mosquitto homeassistant ollama; do
  if container_running "$svc"; then
    ok "$svc is running"
  else
    fail "$svc is not running (podman compose up -d)"
  fi
done

echo "== Mosquitto"
if container_running mosquitto; then
  # $SYS/broker/version is retained by the broker, so one message arrives on subscribe.
  if [[ -z "$MQTT_USER" || -z "$MQTT_PASSWORD" ]]; then
    fail "MQTT_USER/MQTT_PASSWORD not set in .env"
  elif podman exec mosquitto mosquitto_sub -h 127.0.0.1 -p "$MQTT_PORT" \
      -u "$MQTT_USER" -P "$MQTT_PASSWORD" -t '$SYS/broker/version' -C 1 -W 5 >/dev/null 2>&1; then
    ok "subscribe with credentials works"
  else
    fail "subscribe with credentials failed (did you run scripts/mqtt-passwd.sh?)"
  fi

  if podman exec mosquitto mosquitto_sub -h 127.0.0.1 -p "$MQTT_PORT" \
      -t '$SYS/broker/version' -C 1 -W 5 >/dev/null 2>&1; then
    fail "anonymous subscribe was accepted (allow_anonymous must be false)"
  else
    ok "anonymous subscribe is rejected"
  fi
else
  fail "skipping auth checks: mosquitto is not running"
fi

echo "== Home Assistant"
ha_lan_url="http://${HOST_IP}:8123"
code="$(http_code "$ha_lan_url/")"
if [[ "$code" =~ ^[23] ]]; then
  ok "HTTP $code at $ha_lan_url (LAN)"
else
  fail "no response at $ha_lan_url (HTTP $code); check HOST_IP and firewall"
fi

if [[ -z "$HA_TOKEN" || "$HA_TOKEN" == "pegar_token_de_larga_duracion" ]]; then
  warn "HA_TOKEN not set; skipping API checks (create a long-lived token after onboarding)"
else
  config_json="$(curl -s --max-time 5 -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/config" 2>/dev/null || true)"
  if [[ "$config_json" == *'"components"'* ]]; then
    ok "API at $HA_URL accepts HA_TOKEN"
    if [[ "$config_json" == *'"mqtt"'* ]]; then
      ok "MQTT integration is loaded"
    else
      fail "MQTT integration is not loaded (Settings > Devices & services > Add MQTT)"
    fi
  else
    fail "API at $HA_URL rejected HA_TOKEN or did not respond"
  fi
fi

echo "== Ollama"
tags_json="$(curl -s --max-time 5 "$OLLAMA_URL/api/tags" 2>/dev/null || true)"
if [[ "$tags_json" == *'"models"'* ]]; then
  ok "API responds at $OLLAMA_URL"
  model="$OLLAMA_MODEL"
  [[ "$model" == *:* ]] || model="$model:latest"
  if [[ "$tags_json" == *"\"name\":\"$model\""* ]]; then
    ok "model $model is pulled"
  else
    fail "model $model is not pulled (podman exec ollama ollama pull $OLLAMA_MODEL)"
  fi
else
  fail "no response at $OLLAMA_URL/api/tags"
fi

echo
if (( failures > 0 )); then
  echo "Result: $failures check(s) failed."
  exit 1
fi
echo "Result: all checks passed."
