#!/usr/bin/env python3
"""
WTF Transcription Factory — local web app.

Paste a video URL in the browser → it identifies the video (yt-dlp), downloads
the smallest audio stream as a mono 16 kHz MP3, transcribes it with a Whisper
model (faster-whisper), and streams progress + the transcript live to the page.

The ONLY thing the user needs installed is Python. ffmpeg is provisioned
automatically (via the bundled static-ffmpeg package, falling back to a system
ffmpeg if one is present).

Don't run this directly — open the "WTF Transcription Factory" app (or re-run
the installer). It opens your browser for you.
"""
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from collections import deque
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

BASE = Path(__file__).resolve().parent          # the app/ folder
PKG = BASE.parent                               # the package root
OUT = PKG / "transcripts"                       # output lives at the top level
OUT.mkdir(exist_ok=True)

# Auto-delete run folders older than this many days (set to 0 to keep forever).
RETAIN_DAYS = int(os.environ.get("RETAIN_DAYS", "30"))


def sanitize(name, maxlen=80):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("._-")
    return name[:maxlen] or "transcript"


def cleanup_old_runs():
    """Remove transcript run folders older than RETAIN_DAYS."""
    if RETAIN_DAYS <= 0:
        return
    cutoff = time.time() - RETAIN_DAYS * 86400
    try:
        for d in OUT.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
    except FileNotFoundError:
        pass

app = Flask(__name__)

jobs = {}
jobs_lock = threading.Lock()
work_q: "queue.Queue" = queue.Queue()
_models = {}
_models_lock = threading.Lock()
_ffmpeg_dir = None


# --------------------------------------------------------------------------- #
# One-time provisioning
# --------------------------------------------------------------------------- #
def ensure_ffmpeg_dir():
    global _ffmpeg_dir
    if _ffmpeg_dir is not None:
        return _ffmpeg_dir or None
    found = shutil.which("ffmpeg")
    if found:
        _ffmpeg_dir = str(Path(found).parent)
        return _ffmpeg_dir
    try:
        print("Setting up audio tools (ffmpeg) — one-time download…")
        import static_ffmpeg
        static_ffmpeg.add_paths()
        found = shutil.which("ffmpeg")
        if found:
            _ffmpeg_dir = str(Path(found).parent)
            print("  ffmpeg ready.")
            return _ffmpeg_dir
    except Exception as e:                       # noqa: BLE001
        print(f"  Could not auto-provision ffmpeg: {e}")
    _ffmpeg_dir = ""
    return None


def get_model(name):
    with _models_lock:
        if name not in _models:
            from faster_whisper import WhisperModel
            _models[name] = WhisperModel(name, device="auto", compute_type="int8",
                                         cpu_threads=os.cpu_count() or 4)
        return _models[name]


def emit(job, kind, text, **extra):
    ev = {"kind": kind, "text": text, "t": round(time.time(), 3)}
    ev.update(extra)
    job["events"].append(ev)
    for q in list(job["listeners"]):
        try:
            q.put_nowait(ev)
        except Exception:
            pass


def srt_ts(t: float) -> str:
    h, rem = divmod(float(t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def hms(t: float) -> str:
    total = int(float(t))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_paragraphs(segs, target=280, max_gap=1.0):
    """Merge Whisper's short caption-sized segments into readable paragraphs.
    Starts a new paragraph on a clear pause, or after a sentence end once the
    paragraph is long enough. Returns a list of (start_seconds, text)."""
    paras, buf, start, last_end = [], [], None, None
    for s in segs:
        t = s["text"].strip()
        if not t:
            continue
        if buf and last_end is not None and (s["start"] - last_end) > max_gap \
                and len(" ".join(buf)) > 120:
            paras.append((start, " ".join(buf)))
            buf, start = [], None
        if start is None:
            start = s["start"]
        buf.append(t)
        last_end = s["end"]
        joined = " ".join(buf)
        if len(joined) >= target and joined[-1] in ".?!":
            paras.append((start, joined))
            buf, start = [], None
    if buf:
        paras.append((start or 0, " ".join(buf)))
    return paras


_MODEL_SIZE = {
    "tiny.en": "~75 MB", "base.en": "~145 MB", "small.en": "~480 MB",
    "medium.en": "~1.5 GB", "large-v3": "~3 GB",
}


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def run_job(job):
    job["status"] = "running"
    jobdir = OUT / job["id"]
    jobdir.mkdir(parents=True, exist_ok=True)
    job["dir"] = str(jobdir)

    emit(job, "status", "Finding the video and downloading its audio…")
    ffdir = ensure_ffmpeg_dir()
    template = str(jobdir / "%(title).150B.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bestaudio/worst",
        "-x", "--audio-format", "mp3",
        "--postprocessor-args", "ffmpeg:-ac 1 -ar 16000",
        "--no-playlist", "--restrict-filenames", "--newline",
        "-o", template, job["url"],
    ]
    if ffdir:
        cmd += ["--ffmpeg-location", ffdir]

    recent = deque(maxlen=12)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    last = ""
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            recent.append(line)
            if line != last:
                emit(job, "download", line)
                last = line
    proc.wait()
    if proc.returncode != 0:
        tail = " | ".join(recent).lower()
        hint = " (Audio tool problem — try installing ffmpeg, or re-launch.)" if "ffmpeg" in tail else ""
        raise RuntimeError("Couldn't download from that link. Check that it's the "
                           "correct video page URL." + hint)

    mp3s = sorted(jobdir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    if not mp3s:
        raise RuntimeError("Download finished but no audio file was produced.")
    audio = mp3s[-1]

    # Rename the run folder to a readable "<title>_<date>" (kept unique)
    nice = f"{sanitize(audio.stem)}_{time.strftime('%Y-%m-%d')}"
    target = OUT / nice
    if target != jobdir:
        i = 2
        while target.exists():
            target = OUT / f"{nice}_{i}"
            i += 1
        try:
            jobdir.rename(target)
            jobdir = target
            audio = jobdir / audio.name
            job["dir"] = str(jobdir)
        except OSError:
            pass

    mb = audio.stat().st_size / 1e6
    size = _MODEL_SIZE.get(job["model"], "")
    emit(job, "status", f"Got the audio ({mb:.0f} MB). Loading the '{job['model']}' "
                        f"model — first time only, it downloads once ({size}) and "
                        f"may take a few minutes…")

    model = get_model(job["model"])
    lang = None if job["language"] == "auto" else job["language"]
    segments, info = model.transcribe(
        str(audio), language=lang, vad_filter=True,
        beam_size=1, condition_on_previous_text=False)   # greedy = faster on CPU
    emit(job, "status", f"Transcribing about {info.duration / 3600:.1f} hours of "
                        f"audio. Text appears below as it goes…")

    segs, srt_blocks, n = [], [], 0
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        n += 1
        segs.append({"start": seg.start, "end": seg.end, "text": text})
        emit(job, "segment", text, start=round(float(seg.start), 2))
        srt_blocks.append(f"{n}\n{srt_ts(seg.start)} --> {srt_ts(seg.end)}\n{text}\n")

    # Build readable paragraphs from the short caption segments
    paras = build_paragraphs(segs)
    jobdir.mkdir(parents=True, exist_ok=True)   # defensive: never write into a missing folder
    (jobdir / "transcript.txt").write_text(
        "\n\n".join(text for _, text in paras) + "\n")
    (jobdir / "transcript_timestamps.txt").write_text(
        "\n\n".join(f"[{hms(start)}] {text}" for start, text in paras) + "\n")
    if job["srt"]:
        (jobdir / "transcript.srt").write_text("\n".join(srt_blocks))

    if not job["keep_audio"]:
        try:
            audio.unlink()
        except OSError:
            pass

    job["result"] = {"txt": "transcript.txt",
                     "ts": "transcript_timestamps.txt",
                     "srt": "transcript.srt" if job["srt"] else None,
                     "segments": n, "paragraphs": len(paras)}
    job["status"] = "done"
    emit(job, "done", f"All done — {n} lines transcribed.")


def worker():
    while True:
        job = work_q.get()
        try:
            run_job(job)
        except Exception as e:                       # noqa: BLE001
            job["status"] = "error"
            emit(job, "error", str(e))
        finally:
            work_q.task_done()


threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return send_file(BASE / "index.html")


@app.route("/api/jobs", methods=["POST"])
def create_job():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Please paste a video URL."}), 400
    job = {
        "id": uuid.uuid4().hex[:12],
        "url": url,
        "model": data.get("model", "small.en"),
        "language": data.get("language", "en"),
        "srt": bool(data.get("srt", True)),
        "keep_audio": bool(data.get("keep_audio", False)),
        "status": "queued",
        "events": [],
        "listeners": set(),
        "result": None,
        "dir": None,
    }
    cleanup_old_runs()
    with jobs_lock:
        jobs[job["id"]] = job
    emit(job, "status", "Queued…")
    work_q.put(job)
    return jsonify({"job_id": job["id"]})


@app.route("/api/jobs/<jid>")
def job_status(jid):
    job = jobs.get(jid)
    if not job:
        abort(404)
    return jsonify({"id": jid, "status": job["status"], "result": job["result"]})


@app.route("/api/jobs/<jid>/events")
def job_events(jid):
    job = jobs.get(jid)
    if not job:
        abort(404)

    def stream():
        q: "queue.Queue" = queue.Queue()
        job["listeners"].add(q)
        try:
            for ev in list(job["events"]):
                yield f"data: {json.dumps(ev)}\n\n"
            while True:
                if job["status"] in ("done", "error") and q.empty():
                    break
                try:
                    ev = q.get(timeout=15)
                    yield f"data: {json.dumps(ev)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            job["listeners"].discard(q)

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/jobs/<jid>/download/<name>")
def download(jid, name):
    job = jobs.get(jid)
    if not job or name not in ("transcript.txt", "transcript_timestamps.txt", "transcript.srt"):
        abort(404)
    p = Path(job.get("dir") or (OUT / jid)) / name
    if not p.exists():
        abort(404)
    return send_file(p, as_attachment=True, download_name=name)


@app.route("/api/jobs/<jid>/reveal", methods=["POST"])
def reveal(jid):
    job = jobs.get(jid)
    if not job:
        abort(404)
    d = Path(job.get("dir") or (OUT / jid))
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(d)])
        elif os.name == "nt":
            os.startfile(str(d))                     # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(d)])
    except Exception as e:                           # noqa: BLE001
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


def pick_port(start=8765):
    for p in range(start, start + 25):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


if __name__ == "__main__":
    port = pick_port(int(os.environ.get("PORT", "8765")))
    url = f"http://127.0.0.1:{port}"
    cleanup_old_runs()
    ensure_ffmpeg_dir()
    print(f"\n  WTF Transcription Factory is running →  {url}\n  (Close this window to stop.)\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, threaded=True)
