import logging
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from flask import Flask, render_template, send_file, jsonify, abort, request
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env.web")

app = Flask(__name__)

BASE_DEST = Path(os.getenv("REC_BASE_DEST", "/srv/vixilancia"))
CACHE_DIR = BASE_DEST / ".cache"
HOST = os.getenv("WEB_HOST", "0.0.0.0")
PORT = int(os.getenv("WEB_PORT", "5000"))
SEGMENT_MIN_AGE = int(os.getenv("SEGMENT_MIN_AGE", "10"))
MIN_SEGMENT_SIZE = int(os.getenv("MIN_SEGMENT_SIZE", "10240"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_concat_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_lock(key):
    with _locks_lock:
        if key not in _concat_locks:
            _concat_locks[key] = threading.Lock()
        return _concat_locks[key]


def get_days():
    if not BASE_DEST.exists():
        return []
    return sorted(
        [d.name for d in BASE_DEST.iterdir() if d.is_dir() and not d.name.startswith(".")],
        reverse=True,
    )


def get_segments(date_str):
    day_dir = BASE_DEST / date_str
    if not day_dir.exists():
        return []
    now = time.time()
    segments = []
    for s in sorted(day_dir.glob("*.mkv")):
        try:
            st = s.stat()
        except OSError:
            continue
        if s.stat().st_size < MIN_SEGMENT_SIZE:
            logger.debug("Segmento descartado por tamaño: %s (%d bytes)", s.name, st.st_size)
            continue
        if now - st.st_mtime <= SEGMENT_MIN_AGE:
            logger.debug("Segmento descartado por idade: %s (%.1fs)", s.name, now - st.st_mtime)
            continue
        segments.append(s)
    logger.info("Dia %s: %d segmentos validos de %d totais", date_str, len(segments), len(list(day_dir.glob("*.mkv"))))
    return segments


def format_size(num):
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.1f} {unit}" if unit != "B" else f"{num} B"
        num /= 1024
    return f"{num:.2f} TB"


def concat_day(date_str):
    segments = get_segments(date_str)
    if not segments:
        return None

    lock = _get_lock(date_str)
    with lock:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = CACHE_DIR / f"{date_str}.mp4"

        newest_mtime = max(s.stat().st_mtime for s in segments)
        if cache_path.exists() and cache_path.stat().st_mtime >= newest_mtime:
            logger.info("Usando cache para %s (%s)", date_str, format_size(cache_path.stat().st_size))
            return cache_path

        logger.info("Concatenando %d segmentos para %s...", len(segments), date_str)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for seg in segments:
                f.write(f"file '{seg}'\n")
            list_path = f.name

        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    list_path,
                    "-c",
                    "copy",
                    "-avoid_negative_ts",
                    "make_zero",
                    "-movflags",
                    "+faststart",
                    str(cache_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-5:]:
                    logger.debug("FFmpeg: %s", line)
        except subprocess.CalledProcessError as e:
            logger.error("FFmpeg fallou para %s: %s", date_str, (e.stderr or "")[-300:])
            cache_path.unlink(missing_ok=True)
            return None
        finally:
            os.unlink(list_path)

        if cache_path.exists():
            logger.info("Vídeo xerado para %s: %s", date_str, format_size(cache_path.stat().st_size))
            return cache_path

        logger.error("FFmpeg rematou pero non se xerou o ficheiro para %s", date_str)
        return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video/<date_str>")
def video(date_str):
    force = request.args.get("force", "0") == "1"
    if force:
        cache_path = CACHE_DIR / f"{date_str}.mp4"
        if cache_path.exists():
            cache_path.unlink()
            logger.info("Cache eliminado para %s (forzado)", date_str)
    path = concat_day(date_str)
    if path is None:
        abort(404)
    return send_file(str(path), mimetype="video/mp4", conditional=True)


@app.route("/api/days")
def api_days():
    result = []
    for d in get_days():
        segments = get_segments(d)
        total_size = sum(s.stat().st_size for s in segments) if segments else 0
        result.append(
            {
                "date": d,
                "segments": len(segments),
                "total_size": total_size,
                "total_size_human": format_size(total_size),
            }
        )
    return jsonify(result)


@app.route("/api/segments/<date_str>")
def api_segments(date_str):
    segments = get_segments(date_str)
    all_raw = sorted((BASE_DEST / date_str).glob("*.mkv")) if (BASE_DEST / date_str).exists() else []
    result = []
    excluded = []
    now = time.time()
    for s in all_raw:
        try:
            st = s.stat()
        except OSError:
            continue
        entry = {"name": s.name, "size": st.st_size, "size_human": format_size(st.st_size)}
        if s in segments:
            result.append(entry)
        else:
            reason = []
            if st.st_size < MIN_SEGMENT_SIZE:
                reason.append(f"tamaño {st.st_size} < {MIN_SEGMENT_SIZE}")
            if now - st.st_mtime <= SEGMENT_MIN_AGE:
                reason.append(f"idade {now - st.st_mtime:.0f}s <= {SEGMENT_MIN_AGE}s")
            entry["excluded"] = True
            entry["reason"] = "; ".join(reason)
            excluded.append(entry)
    return jsonify({"included": result, "excluded": excluded})


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, threaded=True)