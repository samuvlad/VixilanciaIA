import cv2
import time
import signal
import logging
import asyncio
import os
from pathlib import Path
from ultralytics import YOLO
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RTSP_URL = os.getenv("RTSP_URL")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

MODELO_PATH = os.getenv("YOLO_MODEL", "yolo11n.pt")
MODELO = YOLO(MODELO_PATH)

OBXECTOS = [0, 15, 16]
COOLDOWN = int(os.getenv("COOLDOWN", "30"))
FRAME_SKIP = int(os.getenv("FRAME_SKIP", "10"))
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.5"))
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "5"))
FOTO_PATH = Path(os.getenv("FOTO_PATH", "/tmp/alerta.jpg"))

ultima_alerta = 0
executar = True

if not all([TOKEN, CHAT_ID, RTSP_URL]):
    logger.error("Faltan variables de entorno. Revisa o arquivo .env")
    raise SystemExit(1)

bot = Bot(token=TOKEN)


async def enviar_alerta(foto_path: Path, etiqueta: str):
    try:
        async with bot:
            with open(foto_path, "rb") as foto:
                await bot.send_photo(
                    chat_id=CHAT_ID,
                    photo=foto,
                    caption=f"Detectado: {etiqueta}\nHora: {time.strftime('%H:%M:%S')}",
                )
        logger.info("Alerta enviada a Telegram: %s", etiqueta)
    except Exception as e:
        logger.error("Erro enviando a Telegram: %s", e)


def limpar_foto():
    try:
        FOTO_PATH.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("Erro eliminando foto temporal: %s", e)


def signal_handler(signum, frame):
    global executar
    logger.info("Sinal %s recibido. Pechando...", signal.Signals(signum).name)
    executar = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def detectar():
    global ultima_alerta, executar

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    frame_count = 0

    while executar:
        logger.info("Conectando a %s ...", RTSP_URL)
        cap = cv2.VideoCapture(RTSP_URL)

        if not cap.isOpened():
            logger.error("Non se puido conectar ao stream. Reintentando en %ds...", RECONNECT_DELAY)
            time.sleep(RECONNECT_DELAY)
            continue

        logger.info("Conectado. Sistema de vixilancia activo (frame_skip=%d, cooldown=%ds)...", FRAME_SKIP, COOLDOWN)

        try:
            while executar and cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    logger.warning("Perdeuse a conexión co stream. Reintentando...")
                    break

                frame_count += 1
                if frame_count % FRAME_SKIP != 0:
                    continue

                results = MODELO(frame, conf=CONF_THRESHOLD, verbose=False)

                alerta_enviada = False
                for r in results:
                    for box in r.boxes:
                        cls = int(box.cls[0])
                        if cls in OBXECTOS and not alerta_enviada:
                            agora = time.time()
                            if agora - ultima_alerta > COOLDOWN:
                                etiqueta = r.names[cls]
                                logger.info("Deteccion: %s", etiqueta.upper())

                                cv2.imwrite(str(FOTO_PATH), r.plot())
                                loop.run_until_complete(enviar_alerta(FOTO_PATH, etiqueta))
                                limpar_foto()

                                ultima_alerta = agora
                                alerta_enviada = True
        except Exception as e:
            logger.error("Erro inesperado: %s", e)
        finally:
            cap.release()

        if executar:
            logger.info("Reconectando en %ds...", RECONNECT_DELAY)
            time.sleep(RECONNECT_DELAY)

    loop.close()
    logger.info("Sistema de vixilancia pechado.")


if __name__ == "__main__":
    detectar()