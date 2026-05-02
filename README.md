# Sistema de Vixilancia con IA

Sistema de vixilancia automatizado que usa YOLO para detectar persoas, cans e gatos en tempo real mediante unha cámara RTSP, e envía alertas con foto a Telegram. Tamén inclúe gravación continua en disco con FFmpeg.

## Arquitectura

```
Cámara RTSP ──┬── objectDetention.py ── Telegram (alertas con foto)
               │
               └── record_cam.sh ── /mnt/usb/YYYY-MM-DD/ (gravación continua)
```

## Requisitos

- Python 3.10+
- FFmpeg
- Cámara IP con stream RTSP
- Raspberry Pi 5 (ou similar)

## Instalación

```bash
# Clonar o repositorio
cd /home/samuel/Documentos/vixilancia_ia

# Crear entorno virtual e instalar dependencias
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copiar e configurar as variables de entorno
cp .env.example .env
# Editar .env coas túas credenciais
nano .env
```

## Variables de entorno (.env)

| Variable | Descrición | Por defecto |
|---|---|---|
| `TELEGRAM_TOKEN` | Token do bot de Telegram | (obrigatorio) |
| `TELEGRAM_CHAT_ID` | ID do chat de Telegram | (obrigatorio) |
| `RTSP_URL` | URL do stream RTSP da cámara | (obrigatorio) |
| `YOLO_MODEL` | Ruta ao modelo YOLO | `yolo11n.pt` |
| `FRAME_SKIP` | Procesar 1 de cada N frames | `10` |
| `COOLDOWN` | Segundos entre alertas repetidas | `30` |
| `CONF_THRESHOLD` | Umbral de confianza da detección | `0.5` |
| `RECONNECT_DELAY` | Segundos antes de reconectar | `5` |
| `FOTO_PATH` | Ruta da foto temporal | `/tmp/alerta.jpg` |
| `REC_BASE_DEST` | Carpeta destino das gravacións | `/mnt/usb` |
| `REC_SEGMENT_TIME` | Duración de cada fragmento (segundos) | `300` |
| `REC_FILENAME` | Prefixo dos arquivos de gravación | `cam` |

## Uso manual

```bash
# Activar entorno virtual
source venv/bin/activate

# Executar detección
python objectDetention.py

# Executar gravación (noutra terminal)
./record_cam.sh
```

## Servizos systemd

###Instalación dos servizos

```bash
# Copiar os arquivos de servizo
sudo cp vixilancia-deteccion.service /etc/systemd/system/
sudo cp vixilancia-gravacion.service /etc/systemd/system/

# Recargar systemd
sudo systemctl daemon-reload

# Activar e iniciar os servizos
sudo systemctl enable --now vixilancia-deteccion
sudo systemctl enable --now vixilancia-gravacion
```

### Xestión dos servizos

```bash
# Ver estado
sudo systemctl status vixilancia-deteccion
sudo systemctl status vixilancia-gravacion

# Ver logs en tempo real
sudo journalctl -u vixilancia-deteccion -f
sudo journalctl -u vixilancia-gravacion -f

# Parar servizos
sudo systemctl stop vixilancia-deteccion
sudo systemctl stop vixilancia-gravacion

# Reiniciar servizos
sudo systemctl restart vixilancia-deteccion
sudo systemctl restart vixilancia-gravacion

# Desactivar (non se iniciarán ao arrancar)
sudo systemctl disable vixilancia-deteccion
sudo systemctl disable vixilancia-gravacion
```

## Obxectos detectados

O sistema detecta por defecto:

| ID | Obxecto |
|---|---|
| 0 | Persoa |
| 15 | Gato |
| 16 | Can |

Para modificar os obxectos detectados, edita a lista `OBXECTOS` en `objectDetention.py`.

## Estrutura do proxecto

```
vixilancia_ia/
├── .env                          # Credenciais (non subir a git)
├── .env.example                  # Plantilla de Variables
├── .gitignore
├── objectDetention.py             # Detección con YOLO + alertas Telegram
├── record_cam.sh                  # Gravación continua con FFmpeg
├── requirements.txt               # Dependencias Python
├── vixilancia-deteccion.service   # Servizo systemd (detección)
├── vixilancia-gravacion.service   # Servizo systemd (gravación)
└── yolo11n.pt                     # Modelo YOLO
```