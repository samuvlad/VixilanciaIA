import cv2
import time
import signal
import logging
import asyncio
import os
import queue
import threading
import numpy as np
from pathlib import Path
from ultralytics import YOLO
from telegram import Bot
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env.deteccion")

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RTSP_URL = os.getenv("RTSP_URL_DETECCION")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

MODEL_PATH = os.getenv("YOLO_MODEL", "yolo11s.pt")
YOLO_IMG_SZ = int(os.getenv("YOLO_IMG_SZ", "480"))
YOLO_DEVICE = os.getenv("YOLO_DEVICE", "cpu")
_model = None

OBJECTS = {0, 15, 16}
COOLDOWN = int(os.getenv("COOLDOWN", "30"))
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.25"))
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "5"))
READ_TIMEOUT = int(os.getenv("READ_TIMEOUT", "10"))
PHOTO_DIR = Path(os.getenv("PHOTO_DIR", "/tmp"))
PHOTO_DIR.mkdir(parents=True, exist_ok=True)
MAX_QUEUE = int(os.getenv("MAX_QUEUE", "20"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "75"))
MOTION_THRESHOLD = float(os.getenv("MOTION_THRESHOLD", "0.005"))


def get_model():
    global _model
    if _model is None:
        logger.info("Cargando modelo %s en device=%s ...", MODEL_PATH, YOLO_DEVICE)
        _model = YOLO(MODEL_PATH)
    return _model


if not all([TOKEN, CHAT_ID, RTSP_URL]):
    logger.error("Faltan variables de entorno. Revisa o arquivo .env.deteccion")
    raise SystemExit(1)

bot = Bot(token=TOKEN)

_stop = threading.Event()
msg_queue = queue.Queue(maxsize=MAX_QUEUE)


async def _send_telegram(photo_path, label, timestamp):
    try:
        async with bot:
            with open(photo_path, "rb") as photo:
                await bot.send_photo(
                    chat_id=CHAT_ID,
                    photo=photo,
                    caption=f"Detectado: {label}\nDeteccion: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))}",
                )
        logger.info("Alerta enviada a Telegram: %s", label)
        return True
    except Exception as e:
        logger.error("Erro enviando a Telegram: %s", e)
        return False


def sender_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    while not _stop.is_set() or not msg_queue.empty():
        try:
            photo_path, label, timestamp = msg_queue.get(timeout=1)
        except queue.Empty:
            continue

        ok = loop.run_until_complete(_send_telegram(photo_path, label, timestamp))

        try:
            photo_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Erro eliminando foto %s: %s", photo_path, e)

        if ok:
            logger.info("Cooldown de %ds antes de seguinte envio...", COOLDOWN)
            _stop.wait(timeout=COOLDOWN)
        else:
            _stop.wait(timeout=5)

    loop.close()
    logger.info("Consumidor de envios pechado.")


def signal_handler(signum, frame):
    logger.info("Sinal %s recibido. Pechando...", signal.Signals(signum).name)
    _stop.set()


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class VideoStream:
    def __init__(self, url, timeout_ms):
        self.url = url
        self.timeout_ms = timeout_ms
        self._cap = None
        self._frame = None
        self._lock = threading.Lock()
        self._connected = False
        self._thread = None

    def connect(self):
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp|fflags;nobuffer|flags;low_delay"
        self._cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
            self._cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.timeout_ms)
        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
            self._cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.timeout_ms)
        self._connected = self._cap.isOpened()
        return self._connected

    def start(self):
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self):
        while self._connected and not _stop.is_set():
            for _ in range(3):
                if not self._cap.grab():
                    self._connected = False
                    return
            ret, frame = self._cap.retrieve()
            if not ret or frame is None:
                self._connected = False
                break
            with self._lock:
                self._frame = frame

    def get_latest(self):
        with self._lock:
            return self._frame

    def close(self):
        self._connected = False
        if self._thread:
            self._thread.join(timeout=3)
        if self._cap:
            self._cap.release()


def detect():
    sender_thread = threading.Thread(target=sender_loop, daemon=True)
    sender_thread.start()

    while not _stop.is_set():
        logger.info("Conectando a %s ...", RTSP_URL)
        stream = VideoStream(RTSP_URL, READ_TIMEOUT * 1000)

        if not stream.connect():
            logger.error("Non se puido conectar ao stream. Reintentando en %ds...", RECONNECT_DELAY)
            _stop.wait(timeout=RECONNECT_DELAY)
            continue

        stream.start()
        logger.info("Conectado. Sistema de vixilancia activo (cooldown=%ds, imgsz=%d, model=%s, motion_threshold=%.4f)...",
                     COOLDOWN, YOLO_IMG_SZ, MODEL_PATH, MOTION_THRESHOLD)

        last_sent = 0.0
        last_frame_ref = None
        bg_sub = cv2.createBackgroundSubtractorMOG2(history=50, varThreshold=25, detectShadows=False)
        motion_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        yolo_skipped = 0

        try:
            while not _stop.is_set() and stream._connected:
                frame = stream.get_latest()
                if frame is None or frame is last_frame_ref:
                    time.sleep(0.01)
                    continue
                last_frame_ref = frame

                now = time.time()

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)
                fg_mask = bg_sub.apply(gray)
                fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, motion_kernel)
                motion_ratio = cv2.countNonZero(fg_mask) / (fg_mask.shape[0] * fg_mask.shape[1])

                if motion_ratio < MOTION_THRESHOLD:
                    yolo_skipped += 1
                    if yolo_skipped % 50 == 0:
                        logger.info("Sen movemento (%d frames saltados, ratio=%.6f)", yolo_skipped, motion_ratio)
                    continue

                yolo_skipped = 0
                t0 = time.time()
                logger.info("Movemento detectado (ratio=%.4f). Executando inferencia...", motion_ratio)

                results = get_model()(frame, imgsz=YOLO_IMG_SZ, conf=CONF_THRESHOLD, device=YOLO_DEVICE, verbose=False)
                infer_ms = (time.time() - t0) * 1000

                all_boxes = []
                for r in results:
                    for box in r.boxes:
                        all_boxes.append((int(box.cls[0]), float(box.conf)))

                if all_boxes:
                    logger.info("Inferencia: %.0fms | Caixas: %s", infer_ms, all_boxes)
                else:
                    logger.info("Inferencia: %.0fms | Sen deteccions", infer_ms)

                for r in results:
                    for box in r.boxes:
                        cls = int(box.cls[0])
                        if cls in OBJECTS:
                            label = r.names[cls]
                            logger.info("Deteccion: %s", label.upper())

                            if now - last_sent >= COOLDOWN:
                                ts = int(now * 1000)
                                photo_path = PHOTO_DIR / f"alerta_{ts}.jpg"
                                cv2.imwrite(str(photo_path), frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])

                                try:
                                    msg_queue.put_nowait((photo_path, label, now))
                                    logger.info("Enviado a cola (tamano=%d)", msg_queue.qsize())
                                except queue.Full:
                                    logger.warning("Cola chea, descartando deteccion mais antiga")
                                    try:
                                        old_path, _, _ = msg_queue.get_nowait()
                                        old_path.unlink(missing_ok=True)
                                    except Exception:
                                        pass
                                    msg_queue.put_nowait((photo_path, label, now))

                                last_sent = now
                            else:
                                logger.info("Deteccion validada pero en cooldown (faltan %.1fs)", COOLDOWN - (now - last_sent))

                            break
                    else:
                        continue
                    break

        except Exception as e:
            logger.error("Erro inesperado: %s", e)
        finally:
            stream.close()

        if not _stop.is_set():
            logger.info("Reconectando en %ds...", RECONNECT_DELAY)
            _stop.wait(timeout=RECONNECT_DELAY)

    sender_thread.join(timeout=COOLDOWN + 5)
    logger.info("Sistema de vixilancia pechado.")


if __name__ == "__main__":
    detect()