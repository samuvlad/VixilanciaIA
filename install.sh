#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "Este script debe executarse como root (sudo ./install.sh)"
    fi
}

install_deps() {
    info "Instalando dependencias do sistema..."
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip ffmpeg
}

setup_venv() {
    info "Creando entorno virtual Python..."
    python3 -m venv "$SCRIPT_DIR/venv"
    "$SCRIPT_DIR/venv/bin/pip" install --upgrade pip --quiet
    "$SCRIPT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" --quiet
    info "Dependencias Python instaladas."
}

make_executable() {
    info "Dando permisos de execución a record_cam.sh..."
    chmod +x "$SCRIPT_DIR/record_cam.sh"
}

ask_var() {
    local var_name="$1"
    local prompt_text="$2"
    local env_file="$3"
    local current_val
    current_val=$(grep -E "^${var_name}=" "$env_file" 2>/dev/null | head -1 | cut -d= -f2-)

    if [[ -n "$current_val" && "$current_val" != "-" ]]; then
        return 0
    fi

    while true; do
        echo -e "${YELLOW}[CONFIG]${NC} ${prompt_text}"
        read -p "  Valor: " new_val
        if [[ -z "$new_val" || "$new_val" == "-" ]]; then
            warn "O valor non pode estar baleiro. Introdúceo de novo."
            continue
        fi
        break
    done

    if grep -qE "^${var_name}=" "$env_file" 2>/dev/null; then
        sed -i "s|^${var_name}=.*|${var_name}=${new_val}|" "$env_file"
    else
        echo "${var_name}=${new_val}" >> "$env_file"
    fi
    info "${var_name} configurado en $(basename "$env_file")"
}

check_env_files() {
    if [[ ! -f "$SCRIPT_DIR/.env.deteccion" ]]; then
        warn "Non se atopou .env.deteccion. Copiando desde .env.example.deteccion"
        cp "$SCRIPT_DIR/.env.example.deteccion" "$SCRIPT_DIR/.env.deteccion"
    fi

    if [[ ! -f "$SCRIPT_DIR/.env.gravacion" ]]; then
        warn "Non se atopou .env.gravacion. Copiando desde .env.example.gravacion"
        cp "$SCRIPT_DIR/.env.example.gravacion" "$SCRIPT_DIR/.env.gravacion"
    fi

    echo ""
    info "Configurando variables obrigatorias..."
    echo ""

    ask_var "TELEGRAM_TOKEN" \
        "Introduce o token do bot de Telegram:" \
        "$SCRIPT_DIR/.env.deteccion"

    ask_var "TELEGRAM_CHAT_ID" \
        "Introduce o ID do chat de Telegram:" \
        "$SCRIPT_DIR/.env.deteccion"

    ask_var "RTSP_URL_DETECCION" \
        "Introduce a URL RTSP para detección (ex: rtsp://user:pass@192.168.1.42:554/stream2):" \
        "$SCRIPT_DIR/.env.deteccion"

    ask_var "RTSP_URL" \
        "Introduce a URL RTSP para gravación (ex: rtsp://user:pass@192.168.1.42:554/stream1):" \
        "$SCRIPT_DIR/.env.gravacion"

    echo ""
    info "Configuración completada."
}

create_rec_dir() {
    local dest
    dest=$(grep -E '^REC_BASE_DEST=' "$SCRIPT_DIR/.env.gravacion" 2>/dev/null | cut -d= -f2-)
    dest="${dest:-/srv/vixilancia}"
    info "Creando directorio de gravación: $dest"
    mkdir -p "$dest"
}

install_services() {
    info "Instalando servizos systemd..."

    cat > /etc/systemd/system/vixilancia-deteccion.service <<EOF
[Unit]
Description=Vixilancia IA - Detección con YOLO
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${SCRIPT_DIR}/venv/bin/python objectDetention.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    cat > /etc/systemd/system/vixilancia-gravacion.service <<EOF
[Unit]
Description=Vixilancia IA - Gravación continua
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${SCRIPT_DIR}
ExecStart=/usr/bin/bash ${SCRIPT_DIR}/record_cam.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable vixilancia-deteccion.service
    systemctl enable vixilancia-gravacion.service

    info "Iniciando servizos..."
    systemctl start vixilancia-deteccion.service
    systemctl start vixilancia-gravacion.service

    sleep 2

    echo ""
    info "Estado dos servizos:"
    systemctl status vixilancia-deteccion.service --no-pager -l || true
    echo ""
    systemctl status vixilancia-gravacion.service --no-pager -l || true
}

main() {
    check_root
    install_deps
    setup_venv
    make_executable
    check_env_files
    create_rec_dir
    install_services

    echo ""
    info "Instalación completada."
    echo ""
    echo "Comandos útiles:"
    echo "  sudo systemctl status vixilancia-deteccion"
    echo "  sudo systemctl status vixilancia-gravacion"
    echo "  sudo journalctl -u vixilancia-deteccion -f"
    echo "  sudo journalctl -u vixilancia-gravacion -f"
    echo "  sudo systemctl restart vixilancia-deteccion"
    echo "  sudo systemctl restart vixilancia-gravacion"
    echo "  sudo systemctl stop vixilancia-deteccion"
    echo "  sudo systemctl stop vixilancia-gravacion"
}

main "$@"