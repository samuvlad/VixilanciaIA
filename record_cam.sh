#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

CAMERA_URL="${RTSP_URL:-rtsp://camara:camara@192.168.1.42:554/stream1}"
BASE_DEST="${REC_BASE_DEST:-/mnt/usb}"
SEGMENT_TIME="${REC_SEGMENT_TIME:-300}"
FILENAME="${REC_FILENAME:-cam}"
RECONNECT_DELAY="${REC_RECONNECT_DELAY:-5}"

mkdir -p "$BASE_DEST"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] $*"
}

cleanup() {
    log "Sinal recibido. Pechando gravación..."
    kill $(jobs -p) 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

log "Sistema de gravación iniciado"
log "Cámara: $CAMERA_URL"
log "Destino: $BASE_DEST"

while true; do
    DEST="$BASE_DEST/$(date +%Y-%m-%d)"
    mkdir -p "$DEST"

    log "Conectando a $CAMERA_URL ..."

    ffmpeg -i "$CAMERA_URL" \
        -c:v copy \
        -c:a aac -b:a 64k \
        -f segment -segment_time "$SEGMENT_TIME" \
        -reset_timestamps 1 \
        -strftime 1 \
        "$DEST/${FILENAME}_%Y%m%d_%H%M%S.mp4"

    log "Conexión perdida. Reintentando en ${RECONNECT_DELAY}s..."
    sleep "$RECONNECT_DELAY"
done