#!/usr/bin/env sh
set -e

OPTS="/data/options.json"

BROKER=$(jq -r '.broker' "$OPTS")
PORT=$(jq -r '.port' "$OPTS")
USERNAME=$(jq -r '.username // empty' "$OPTS")
PASSWORD=$(jq -r '.password // empty' "$OPTS")
IN_TOPIC=$(jq -r '.in_topic' "$OPTS")
DISCOVERY_PREFIX=$(jq -r '.discovery_prefix' "$OPTS")
STATE_PREFIX=$(jq -r '.state_prefix' "$OPTS")
CLIENT_ID=$(jq -r '.client_id' "$OPTS")
CLEANUP=$(jq -r '.cleanup' "$OPTS")

USE_LOCAL=$(jq -r '.use_local_api // false' "$OPTS")
BASE_URL=$(jq -r '.gateway_base_url // empty' "$OPTS")
LAN_TIMEOUT=$(jq -r '.lan_timeout // 3.0' "$OPTS")
MAP_REFRESH=$(jq -r '.map_refresh_sec // 600' "$OPTS")

CMD="python3 /app/ecowitt_mqtt_bridge.py \
  --broker \"$BROKER\" --port \"$PORT\" \
  --in-topic \"$IN_TOPIC\" \
  --discovery-prefix \"$DISCOVERY_PREFIX\" \
  --state-prefix \"$STATE_PREFIX\" \
  --client-id \"$CLIENT_ID\""

[ -n "$USERNAME" ] && CMD="$CMD --username \"$USERNAME\""
[ -n "$PASSWORD" ] && CMD="$CMD --password \"$PASSWORD\""
[ "$CLEANUP" = "true" ] && CMD="$CMD --cleanup"
if [ "$USE_LOCAL" = "true" ] && [ -n "$BASE_URL" ]; then
  CMD="$CMD --use-local-api --gateway-base-url \"$BASE_URL\" --lan-timeout \"$LAN_TIMEOUT\" --map-refresh-sec \"$MAP_REFRESH\""
fi

echo "Starting Ecowitt MQTT Bridge..."
sh -c "$CMD"
