# Sistema de Vixilancia con IA

Sistema de vixilancia automatizado que usa YOLO para detectar persoas, cans e gatos en tempo real mediante unha cámara RTSP, e envía alertas con foto a Telegram. A detección usa un pre-filter de movemento para evitar executar YOLO en frames sen actividade, e o envío a Telegram está desacoplado cun cooldown. Tamén inclúe gravación continua en disco con FFmpeg e un visor web para consultar as gravacións.

## Arquitectura

```
Cámara RTSP ──┬── objectDetention.py
                │     ├── VideoStream → frame → movemento? → YOLO → detectado? → msg_queue + foto
                │     └── sender_loop → Telegram (alertas con foto, cooldown 10s)
                │
                ├── record_cam.sh ── /srv/vixilancia/YYYY-MM-DD/ (gravación continua)
                │
                └── web.py ── Visor web (Flask)
                      ├── Lista de días con gravacións
                      ├── Concatena fragmentos do día nun só vídeo
                      └── Reprodutor de vídeo integrado
```

## Requisitos

- Python 3.10+
- FFmpeg
- Cámara IP con stream RTSP
- Raspberry Pi 5 (ou similar)

## Instalación

```bash
# Clonar o repositorio
git clone <url-do-repo> /opt/vixilancia_ia
cd /opt/vixilancia_ia

# Executar o script de instalación (require root)
sudo ./install.sh
```

O script `install.sh` encárgase de:

1. Instalar as dependencias do sistema (Python 3, FFmpeg, etc.)
2. Crear o entorno virtual Python e instalar dependencias
3. Copiar os `.env.example` a `.env` se non existen
4. Pedir as variables obrigatorias interactivamente (Token Telegram, Chat ID, URLs RTSP)
5. Crear o directorio de gravación
6. Instalar e iniciar os servizos systemd

### Instalación manual

```bash
# Crear entorno virtual e instalar dependencias
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copiar e configurar as variables de entorno
cp .env.example.deteccion .env.deteccion
cp .env.example.gravacion .env.gravacion
cp .env.example.web .env.web
# Editar os .env coas túas credenciais
nano .env.deteccion
nano .env.gravacion
nano .env.web
```

## Variables de entorno

### Detección (.env.deteccion)

| Variable | Descrición | Por defecto |
|---|---|---|
| `TELEGRAM_TOKEN` | Token do bot de Telegram | (obrigatorio) |
| `TELEGRAM_CHAT_ID` | ID do chat de Telegram | (obrigatorio) |
| `RTSP_URL_DETECCION` | URL do stream RTSP para detección | (obrigatorio) |
| `YOLO_MODEL` | Ruta ao modelo YOLO | `yolo11s.pt` |
| `YOLO_DEVICE` | Dispositivo para inferencia (`cpu`, `cuda`, etc.) | `cpu` |
| `COOLDOWN` | Segundos entre envíos a Telegram | `10` |
| `MAX_QUEUE` | Máximo de alertas na cola | `20` |
| `CONF_THRESHOLD` | Umbral de confianza da detección | `0.25` |
| `MOTION_THRESHOLD` | Proporción mínima de movemento para activar YOLO | `0.005` |
| `RECONNECT_DELAY` | Segundos antes de reconectar | `5` |
| `READ_TIMEOUT` | Timeout de lectura do stream RTSP (segundos) | `10` |
| `PHOTO_DIR` | Cartafol para fotos temporais de alerta | `/tmp` |
| `JPEG_QUALITY` | Calidade JPEG das fotos (1-100) | `75` |
| `YOLO_IMG_SZ` | Tamaño de imaxe para YOLO | `480` |

### Gravación (.env.gravacion)

| Variable | Descrición | Por defecto |
|---|---|---|
| `RTSP_URL` | URL do stream RTSP para gravación | (obrigatorio) |
| `REC_BASE_DEST` | Carpeta destino das gravacións | `/srv/vixilancia` |
| `REC_SEGMENT_TIME` | Duración de cada fragmento (segundos) | `900` |
| `REC_FILENAME` | Prefixo dos arquivos de gravación | `cam` |
| `REC_RECONNECT_DELAY` | Segundos antes de reconectar | `5` |
| `REC_STIMEOUT` | Timeout RTSP (microsegundos) | `5000000` |

### Visor web (.env.web)

| Variable | Descrición | Por defecto |
|---|---|---|
| `REC_BASE_DEST` | Carpeta destino das gravacións | `/srv/vixilancia` |
| `WEB_HOST` | Enderezo de escoita do servidor web | `0.0.0.0` |
| `WEB_PORT` | Porto do servidor web | `5000` |
| `SEGMENT_MIN_AGE` | Segundos mínimos para considerar un fragmento completo | `10` |
| `MIN_SEGMENT_SIZE` | Tamaño mínimo de fragmento en bytes para incluír | `10240` |

## Uso manual

```bash
# Activar entorno virtual
source venv/bin/activate

# Executar detección
python objectDetention.py

# Executar gravación (noutra terminal)
./record_cam.sh

# Executar visor web (noutra terminal)
python web.py
```

O visor web estará dispoñible en `http://<IP>:5000`.

## Visor web

O visor web permite consultar as gravacións gardadas no disco. Funcionalidades:

- Lista de días con gravacións (máis recentes primeiro)
- Concatenación automática de todos os fragmentos do día nun só vídeo
- Caché dos vídeos concatenados ( rexenérase automáticamente se hai fragmentos novos)
- Reprodutor de vídeo integrado con controls de navegación
- Información de fragmentos e tamaño por día

A concatenación usa FFmpeg con `-c copy` (sen recodificar), polo que é moi rápida. Os vídeos concatenados gárdanse en `/srv/vixilancia/.cache/YYYY-MM-DD.mp4`.

## Obxectos detectados

O sistema detecta por defecto:

| ID | Obxecto |
|---|---|
| 0 | Persoa |
| 15 | Gato |
| 16 | Can |

Para modificar os obxectos detectados, edita a lista `OBJECTS` en `objectDetention.py`.

## Como funciona a detección

1. **Lectura de stream** — O thread `VideoStream` le frames do RTSP con baixa latencia (UDP, nobuffer, low_delay), descartando frames antigos do buffer con `grab()` 3x antes de `retrieve()`.
2. **Pre-filter de movemento** — Antes de executar YOLO, compróbase se hai movemento no frame usando `BackgroundSubtractorMOG2`. Se a proporción de píxeles en movemento é menor que `MOTION_THRESHOLD`, sáltase a inferencia. Isto reduce drasticamente o uso de CPU.
3. **Inferencia YOLO** — Cando hai movemento, executase YOLO (`yolo11s` por defecto) coa confianza mínima `CONF_THRESHOLD`.
4. **Cola de alertas** — Cando se detecta un obxecto de interese, gárdase a foto e métese na cola. Se a cola está chea, descártase a alerta máis antiga.
5. **Envío a Telegram** — Un thread consumidor envía as alertas da cola a Telegram, esperando `COOLDOWN` segundos (10 por defecto) entre envíos.
6. **Resiliencia** — Se a conexión RTSP se perde, reconéctase automaticamente. Se `cap.read()` se bloquea, un timeout de `READ_TIMEOUT` segundos forza a reconexión.

## Estrutura do proxecto

```
vixilancia_ia/
├── .env.deteccion                 # Variables de entorno (detección)
├── .env.gravacion                 # Variables de entorno (gravación)
├── .env.web                       # Variables de entorno (visor web)
├── .env.example.deteccion         # Exemplo de config para detección
├── .env.example.gravacion         # Exemplo de config para gravación
├── .env.example.web               # Exemplo de config para visor web
├── .gitignore
├── install.sh                     # Script de instalación automática
├── objectDetention.py              # Detección con YOLO + alertas Telegram
├── record_cam.sh                   # Gravación continua con FFmpeg
├── requirements.txt                # Dependencias Python
├── templates/
│   └── index.html                  # Plantilla HTML do visor web
├── web.py                          # Visor web (Flask)
└── yolo11s.pt                      # Modelo YOLO
```