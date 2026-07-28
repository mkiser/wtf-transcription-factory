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
AUDIO_OUT = PKG / "audio"                       # saved audio lives beside it
# AUDIO_OUT is created on first use, so people who never save audio never get
# an empty folder. It is deliberately outside the RETAIN_DAYS sweep below.

MODES = ("transcript", "audio", "both")

# Auto-delete run folders older than this many days (set to 0 to keep forever).
RETAIN_DAYS = int(os.environ.get("RETAIN_DAYS", "30"))

# yt-dlp is in a constant arms race with the sites it supports, so a stale copy
# is the most common cause of "couldn't download that link". Refresh it at most
# once a day, in the background, and never let a failure block the app.
UPDATE_STAMP = PKG / ".last-update"
UPDATE_INTERVAL = 86400


def sanitize(name, maxlen=80):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("._-")
    return name[:maxlen] or "transcript"


def unique_path(path: Path) -> Path:
    """`path`, or the same name with a _2/_3 suffix if it's already taken."""
    i, cand = 2, path
    while cand.exists():
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        i += 1
    return cand


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
# Set unless a background yt-dlp upgrade is actually in flight.
_ytdlp_ready = threading.Event()
_ytdlp_ready.set()


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


def maybe_update_ytdlp():
    """Once a day, quietly upgrade yt-dlp in this app's own environment.

    Runs in the background so launching stays instant, and is deliberately
    best-effort: an offline machine simply keeps the version it has and tries
    again next launch. `_ytdlp_ready` lets a download that starts immediately
    wait for the upgrade instead of racing it.
    """
    try:
        if UPDATE_STAMP.exists() and \
                time.time() - UPDATE_STAMP.stat().st_mtime < UPDATE_INTERVAL:
            return
    except OSError:
        return

    def run():
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "install",
                                "--quiet", "--upgrade", "yt-dlp"],
                               capture_output=True, timeout=180)
            if r.returncode == 0:
                UPDATE_STAMP.touch()          # only on success, so retry if offline
        except Exception:                     # noqa: BLE001
            pass
        finally:
            _ytdlp_ready.set()

    _ytdlp_ready.clear()
    threading.Thread(target=run, daemon=True).start()


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
def find_js_runtime():
    """Locate a JavaScript runtime, returning (name, path) or (None, None).

    Checks PATH first, then the usual install locations: the double-click
    launcher runs a non-interactive shell, so PATH there is missing the
    Homebrew and nvm entries that work fine in a terminal.
    """
    for rt in ("deno", "node", "bun"):
        found = shutil.which(rt)
        if found:
            return rt, found

    spots = [("deno", Path.home() / ".deno/bin/deno"),
             ("bun", Path.home() / ".bun/bin/bun")]
    for base in ("/opt/homebrew/bin", "/usr/local/bin"):
        spots += [(rt, Path(base) / rt) for rt in ("deno", "node", "bun")]
    for rt, p in spots:
        if p.exists():
            return rt, str(p)

    # nvm keeps versioned installs well outside any non-interactive PATH
    def ver(p):
        return tuple(int(x) for x in re.findall(r"\d+", p.parent.parent.name)[:3])
    nvm = sorted((Path.home() / ".nvm/versions/node").glob("*/bin/node"), key=ver)
    if nvm:
        return "node", str(nvm[-1])
    return None, None


def js_runtime_args():
    """YouTube now needs a JS runtime to solve its signature challenges. Without
    one, extraction falls back to a client that reports perfectly good videos as
    "not available" — so this is the difference between working and not.

    The challenge-solver script ships separately from the runtime; yt-dlp fetches
    and caches it on demand via --remote-components.
    """
    rt, path = find_js_runtime()
    if not rt:
        return []
    return ["--js-runtimes", f"{rt}:{path}", "--remote-components", "ejs:github"]


def ytdlp_cmd(job, jobdir, ffdir):
    """Build the download command. Encoding depends on whether we keep the audio:
    a transcript-only run makes the small mono 16 kHz file Whisper wants and then
    deletes it; a run that keeps the audio makes something worth listening to."""
    # Run yt-dlp as a module, not as a bare command: the launcher doesn't put
    # this venv's bin/ on PATH, so "yt-dlp" would find a stale system copy or
    # nothing at all.
    cmd = [sys.executable, "-m", "yt_dlp",
           "-f", "bestaudio/worst", "-x", "--audio-format", "mp3"]
    if job["mode"] == "transcript":
        cmd += ["--postprocessor-args", "ffmpeg:-ac 1 -ar 16000"]
    else:
        cmd += ["--audio-quality", "2"]      # LAME VBR ~190 kbps, stereo kept
    cmd += js_runtime_args()
    cmd += ["--no-playlist", "--restrict-filenames", "--newline",
            "-o", str(jobdir / "%(title).150B.%(ext)s"), job["url"]]
    if ffdir:
        cmd += ["--ffmpeg-location", ffdir]
    return cmd


def download_audio(job, jobdir):
    """Fetch the media's audio into jobdir and return the resulting MP3."""
    emit(job, "status", "Finding the video and downloading its audio…")
    _ytdlp_ready.wait(timeout=180)      # don't race a background yt-dlp upgrade
    cmd = ytdlp_cmd(job, jobdir, ensure_ffmpeg_dir())

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
        if "ffmpeg" in tail:
            hint = " (Audio tool problem — try installing ffmpeg, or re-launch.)"
        elif not js_runtime_args() and ("javascript runtime" in tail
                                        or "not available" in tail):
            # Don't blame the URL for this — the video is usually fine.
            hint = (" YouTube needs a JavaScript runtime to unlock its video "
                    "formats, and reports videos as unavailable without one. "
                    "Install Node.js (nodejs.org) or Deno, then re-launch.")
        else:
            hint = ""
        raise RuntimeError("Couldn't download from that link. Check that it's the "
                           "correct video page URL." + hint)

    mp3s = sorted(jobdir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    if not mp3s:
        raise RuntimeError("Download finished but no audio file was produced.")
    return mp3s[-1]


def run_job(job):
    job["status"] = "running"
    jobdir = OUT / job["id"]
    jobdir.mkdir(parents=True, exist_ok=True)
    job["dir"] = str(jobdir)

    audio = download_audio(job, jobdir)
    nice = f"{sanitize(audio.stem)}_{time.strftime('%Y-%m-%d')}"

    if job["mode"] == "audio":
        # Nothing to transcribe: move the one file out and drop the scratch folder.
        AUDIO_OUT.mkdir(parents=True, exist_ok=True)
        final = unique_path(AUDIO_OUT / f"{nice}.mp3")
        shutil.move(str(audio), str(final))
        shutil.rmtree(jobdir, ignore_errors=True)
        mb = final.stat().st_size / 1e6
        job["dir"] = str(AUDIO_OUT)
        job["audio_path"] = str(final)
        job["result"] = {"audio": final.name, "mb": round(mb, 1)}
        job["status"] = "done"
        emit(job, "done", f"Audio saved — {final.name} ({mb:.0f} MB)")
        return

    # Rename the run folder to a readable "<title>_<date>" (kept unique)
    target = unique_path(OUT / nice)
    if target != jobdir:
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

    if job["mode"] == "both":
        job["audio_path"] = str(audio)
    else:
        try:
            audio.unlink()
        except OSError:
            pass

    job["result"] = {"txt": "transcript.txt",
                     "ts": "transcript_timestamps.txt",
                     "srt": "transcript.srt" if job["srt"] else None,
                     "audio": audio.name if job["mode"] == "both" else None,
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
    mode = data.get("mode")
    if mode is None:
        # A browser holding a cached copy of the old page still posts keep_audio.
        mode = "both" if data.get("keep_audio") else "transcript"
    if mode not in MODES:
        return jsonify({"error": f"Unknown mode '{mode}'."}), 400
    job = {
        "id": uuid.uuid4().hex[:12],
        "url": url,
        "mode": mode,
        "model": data.get("model", "small.en"),
        "language": data.get("language", "en"),
        "srt": bool(data.get("srt", True)),
        "status": "queued",
        "events": [],
        "listeners": set(),
        "result": None,
        "dir": None,
        "audio_path": None,
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


_DOWNLOAD_KEYS = {"txt": "transcript.txt",
                  "ts": "transcript_timestamps.txt",
                  "srt": "transcript.srt"}


@app.route("/api/jobs/<jid>/download/<key>")
def download(jid, key):
    # Audio filenames vary per video, so the URL carries a logical key and the
    # path is resolved here — there is no user-controlled path segment at all.
    job = jobs.get(jid)
    if not job:
        abort(404)
    if key == "audio":
        p = Path(job["audio_path"]) if job.get("audio_path") else None
    elif key in _DOWNLOAD_KEYS:
        p = Path(job.get("dir") or (OUT / jid)) / _DOWNLOAD_KEYS[key]
    else:
        abort(404)
    if p is None or not p.exists():
        abort(404)
    return send_file(p, as_attachment=True, download_name=p.name)


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
    maybe_update_ytdlp()
    ensure_ffmpeg_dir()
    print(f"\n  WTF Transcription Factory is running →  {url}\n  (Close this window to stop.)\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, threaded=True)
