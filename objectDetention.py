import cv2
import time
import signal
import logging
import asyncio
import os
import queue
import threading
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
DETECTION_INTERVAL = int(os.getenv("DETECTION_INTERVAL", "5"))
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.5"))
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "5"))
READ_TIMEOUT = int(os.getenv("READ_TIMEOUT", "10"))
FOTO_DIR = Path(os.getenv("FOTO_DIR", "/tmp"))
MAX_COLA = int(os.getenv("MAX_COLA", "20"))

executar = True
cola = queue.Queue(maxsize=MAX_COLA)

if not all([TOKEN, CHAT_ID, RTSP_URL]):
    logger.error("Faltan variables de entorno. Revisa o arquivo .env")
    raise SystemExit(1)

bot = Bot(token=TOKEN)


async def _enviar_telegram(foto_path: Path, etiqueta: str, timestamp: float):
    try:
        async with bot:
            with open(foto_path, "rb") as foto:
                await bot.send_photo(
                    chat_id=CHAT_ID,
                    photo=foto,
                    caption=f"Detectado: {etiqueta}\nHora: {time.strftime('%H:%M:%S', time.localtime(timestamp))}",
                )
        logger.info("Alerta enviada a Telegram: %s", etiqueta)
        return True
    except Exception as e:
        logger.error("Erro enviando a Telegram: %s", e)
        return False


def consumidor_envios():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    while executar or not cola.empty():
        try:
            foto_path, etiqueta, timestamp = cola.get(timeout=1)
        except queue.Empty:
            continue

        ok = loop.run_until_complete(_enviar_telegram(foto_path, etiqueta, timestamp))

        try:
            foto_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Erro eliminando foto %s: %s", foto_path, e)

        if ok:
            logger.info("Cooldown de %ds antes de seguinte envio...", COOLDOWN)
            end_time = time.time() + COOLDOWN
            while executar and time.time() < end_time:
                time.sleep(min(1, end_time - time.time()))
        else:
            time.sleep(5)

    loop.close()
    logger.info("Consumidor de envios pechado.")


def signal_handler(signum, frame):
    global executar
    logger.info("Sinal %s recibido. Pechando...", signal.Signals(signum).name)
    executar = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def _ler_frame(cap, resultado):
    ret, frame = cap.read()
    resultado.append((ret, frame))


def detectar():
    global executar

    hilo_envios = threading.Thread(target=consumidor_envios, daemon=True)
    hilo_envios.start()

    while executar:
        logger.info("Conectando a %s ...", RTSP_URL)
        cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, READ_TIMEOUT * 1000)
        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT * 1000)

        if not cap.isOpened():
            logger.error("Non se puido conectar ao stream. Reintentando en %ds...", RECONNECT_DELAY)
            time.sleep(RECONNECT_DELAY)
            continue

        logger.info("Conectado. Sistema de vixilancia activo (intervalo=%ds, cooldown=%ds, cola_max=%d)...", DETECTION_INTERVAL, COOLDOWN, MAX_COLA)

        ultima_deteccion = 0.0

        try:
            while executar and cap.isOpened():
                resultado = []
                hilo = threading.Thread(target=_ler_frame, args=(cap, resultado), daemon=True)
                hilo.start()
                hilo.join(timeout=READ_TIMEOUT)

                if not resultado:
                    logger.warning("Timeout lendo frame (%ds). Reconectando...", READ_TIMEOUT)
                    break

                ret, frame = resultado[0]
                if not ret or frame is None:
                    logger.warning("Perdeuse a conexión co stream. Reintentando...")
                    break

                agora = time.time()
                if agora - ultima_deteccion < DETECTION_INTERVAL:
                    continue

                results = MODELO(frame, conf=CONF_THRESHOLD, verbose=False)

                for r in results:
                    for box in r.boxes:
                        cls = int(box.cls[0])
                        if cls in OBXECTOS:
                            etiqueta = r.names[cls]
                            logger.info("Deteccion: %s", etiqueta.upper())

                            ts = int(agora * 1000)
                            foto_path = FOTO_DIR / f"alerta_{ts}.jpg"
                            cv2.imwrite(str(foto_path), r.plot())

                            try:
                                cola.put_nowait((foto_path, etiqueta, agora))
                                logger.info("Enviado a cola (tamano=%d)", cola.qsize())
                            except queue.Full:
                                logger.warning("Cola chea, descartando deteccion mais antiga")
                                try:
                                    old_path, _, _ = cola.get_nowait()
                                    old_path.unlink(missing_ok=True)
                                except Exception:
                                    pass
                                cola.put_nowait((foto_path, etiqueta, agora))

                            ultima_deteccion = agora
                            break
                    else:
                        continue
                    break

        except Exception as e:
            logger.error("Erro inesperado: %s", e)
        finally:
            cap.release()

        if executar:
            logger.info("Reconectando en %ds...", RECONNECT_DELAY)
            time.sleep(RECONNECT_DELAY)

    hilo_envios.join(timeout=COOLDOWN + 5)
    logger.info("Sistema de vixilancia pechado.")


if __name__ == "__main__":
    detectar()