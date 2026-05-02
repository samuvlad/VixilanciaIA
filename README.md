# Sistema de Vixilancia con IA

Sistema de vixilancia automatizado que usa YOLO para detectar persoas, cans e gatos en tempo real mediante unha cámara RTSP, e envía alertas con foto a Telegram. A detección e o envío están desacoplados: as deteccións gárdanse nunha cola e envíase a Telegram respectando un cooldown. Tamén inclúe gravación continua en disco con FFmpeg.

## Arquitectura

```
Cámara RTSP ──┬── objectDetention.py
               │     ├── [cada 5s] YOLO → detectado? → cola + foto
               │     └── [cada 30s] consumidor cola → Telegram (alertas con foto)
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
| `DETECTION_INTERVAL` | Segundos entre deteccións | `5` |
| `COOLDOWN` | Segundos entre envíos a Telegram | `30` |
| `MAX_COLA` | Máximo de alertas na cola | `20` |
| `CONF_THRESHOLD` | Umbral de confianza da detección | `0.5` |
| `RECONNECT_DELAY` | Segundos antes de reconectar | `5` |
| `READ_TIMEOUT` | Timeout de lectura do stream RTSP (segundos) | `10` |
| `FOTO_DIR` | Cartafol para fotos temporais de alerta | `/tmp` |
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

## Como funciona a detección

1. **Detección continua** — Cada `DETECTION_INTERVAL` segundos (5 por defecto) analízase un frame do stream RTSP con YOLO.
2. **Cola de alertas** — Cando se detecta un obxecto de interese, gárdase a foto e métese na cola. Se a cola está chea, descártase a alerta máis antiga.
3. **Envío a Telegram** — Un thread consumidor envía as alertas da cola a Telegram, esperando `COOLDOWN` segundos (30 por defecto) entre envíos.
4. **Resiliencia** — Se a conexión RTSP se perde, reconéctase automaticamente. Se `cap.read()` se bloquea, un timeout de `READ_TIMEOUT` segundos forza a reconexión.

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