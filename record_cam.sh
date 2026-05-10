#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env.gravacion"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

CAMERA_URL="${RTSP_URL:-rtsp://camara:camara@192.168.1.42:554/stream1}"
BASE_DEST="${REC_BASE_DEST:-/srv/vixilancia}"
SEGMENT_TIME="${REC_SEGMENT_TIME:-900}"
FILENAME="${REC_FILENAME:-cam}"
RECONNECT_DELAY="${REC_RECONNECT_DELAY:-5}"
STIMEOUT="${REC_STIMEOUT:-5000000}"

mkdir -p "$BASE_DEST"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] $*"
}

MIN_SIZE_KB="${REC_MIN_SIZE_KB:-300}"

cleanup_small_files() {
    while true; do
        find "$BASE_DEST" -name "*.mkv" -size -${MIN_SIZE_KB}k ! -newermt "now -1 minute" -printf 'Descartando: %p (%s bytes)\n' -delete 2>/dev/null
        sleep 60
    done
}

CLEANUP_PID=""

cleanup() {
    log "Sinal recibido. Pechando gravación..."
    [ -n "$CLEANUP_PID" ] && kill "$CLEANUP_PID" 2>/dev/null
    kill $(jobs -p) 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

log "Sistema de gravación iniciado"
log "Cámara: $CAMERA_URL"
log "Destino: $BASE_DEST"
log "Tamaño mínimo por segmento: ${MIN_SIZE_KB}KB"

cleanup_small_files &
CLEANUP_PID=$!

while true; do
    DEST="$BASE_DEST/$(date +%Y-%m-%d)"
    mkdir -p "$DEST"

    log "Conectando a $CAMERA_URL (Modo Fluidez MKV)..."

    # Engadimos flags de sincronización agresiva
    ffmpeg -y -loglevel warning \
    -use_wallclock_as_timestamps 1 \
    -fflags +genpts+nobuffer+igndts \
    -rtsp_transport tcp \
    -thread_queue_size 1024 \
    -i "$CAMERA_URL" \
    -c:v copy \
    -map 0 \
    -an \
    -f segment \
    -segment_time "$SEGMENT_TIME" \
    -segment_format matroska \
    -reset_timestamps 1 \
    -strftime 1 "$DEST/${FILENAME}_%Y%m%d_%H%M%S.mkv"

    log "Conexión perdida. Reintentando en ${RECONNECT_DELAY}s..."
    sleep "$RECONNECT_DELAY"
done