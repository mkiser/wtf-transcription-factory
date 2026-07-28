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
import itertools
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
def output_root():
    """Where the user's files go.

    Deliberately NOT inside the app folder: that lives at ~/.wtf-transcription-
    factory, which is hidden, absent from the Finder sidebar, and deleted on
    uninstall — a bad home for a 90 MB MP3 you want to keep. Downloads is
    visible, is where downloaded media belongs, and is never cloud-synced.
    """
    override = os.environ.get("WTF_OUTPUT_DIR")
    if override:
        return Path(override).expanduser()
    downloads = Path.home() / "Downloads"
    return (downloads if downloads.is_dir() else Path.home()) / "WTF Transcription Factory"


OUT_ROOT = output_root()
OUT = OUT_ROOT / "transcripts"
OUT.mkdir(parents=True, exist_ok=True)
AUDIO_OUT = OUT_ROOT / "audio"
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
_seq = itertools.count(1)               # stable display order for the queue
# Pages watching the whole queue, as opposed to one job. The page holds this
# open for its whole life, so a reload reattaches to whatever is running.
queue_listeners = set()
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
    ev = {"kind": kind, "text": text, "job": job["id"], "t": round(time.time(), 3)}
    ev.update(extra)
    if kind == "download":
        # Live-only. Replaying thousands of progress lines on reconnect is pure
        # noise, and across a long queue it is a lot of memory holding nothing.
        job["dlog"].append(ev)
    else:
        job["events"].append(ev)
    for q in list(job["listeners"]) + list(queue_listeners):
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
# The queue
# --------------------------------------------------------------------------- #
class Cancelled(Exception):
    """Raised inside a job when the user stops it. Not an error."""


_URL_RE = re.compile(r"https?://\S+")
# Sentence punctuation that can't end a URL. Brackets are handled separately,
# because plenty of real URLs legitimately end in ")".
_TRAILING = ".,;:!?\"'<>"
_PAIRS = {")": "(", "]": "["}


def _trim_url(u: str) -> str:
    while u:
        if u[-1] in _TRAILING:
            u = u[:-1]
        elif u[-1] in _PAIRS and u.count(u[-1]) > u.count(_PAIRS[u[-1]]):
            u = u[:-1]
        else:
            break
    return u


def extract_urls(text):
    """Pull every http(s) link out of arbitrary pasted text, in order, deduped.

    Deliberately forgiving about what surrounds the links, so a newline list, a
    comma list, a numbered list, or a chunk of copied prose with links buried
    in it all work without anyone having to think about format.
    """
    seen, out = set(), []
    for raw in _URL_RE.findall(text or ""):
        u = _trim_url(raw)
        if len(u) > 8 and u not in seen:
            seen.add(u)
            out.append(u)
    return out


# Only patterns that are unambiguously a *collection*. A "watch?v=X&list=Y" URL
# is one video that happens to sit in a playlist — that's what you get when you
# click a video from inside one — and expanding it would silently queue a few
# hundred videos off a single pasted link.
_COLLECTION_RE = re.compile(r"(?i)/playlist\b|/channel/|/c/|/user/|/@[^/\s]+|/videos/?$")


def is_collection_url(url: str) -> bool:
    if re.search(r"[?&]v=", url):        # a specific video always wins
        return False
    return bool(_COLLECTION_RE.search(url))


def short_title(url: str) -> str:
    """A readable placeholder until yt-dlp tells us the real title."""
    u = re.sub(r"^https?://(www\.)?", "", url)
    return u[:70] + ("…" if len(u) > 70 else "")


def make_job(url, opts):
    job = {
        "id": uuid.uuid4().hex[:12],
        "seq": next(_seq),
        "url": url,
        "title": short_title(url),
        "mode": opts["mode"],
        "model": opts["model"],
        "language": opts["language"],
        "srt": opts["srt"],
        "status": "queued",
        "cancelled": False,
        "proc": None,
        "events": [],
        "dlog": deque(maxlen=40),
        "listeners": set(),
        "result": None,
        "error": None,
        "dir": None,
        "audio_path": None,
    }
    with jobs_lock:
        jobs[job["id"]] = job
    return job


def snapshot():
    """The whole queue, small enough to broadcast on every status change.

    'removed' jobs stay in `jobs` (so their download URLs 404 cleanly instead
    of raising) but are filtered out here — they never ran, so there is nothing
    to show. A job stopped mid-run is 'cancelled' and stays visible.
    """
    with jobs_lock:
        items = sorted(jobs.values(), key=lambda j: j["seq"])
        return [{"id": j["id"], "seq": j["seq"], "title": j["title"],
                 "url": j["url"], "status": j["status"], "mode": j["mode"],
                 "result": j["result"], "error": j["error"]}
                for j in items if j["status"] != "removed"]


def push_state():
    ev = {"kind": "state", "items": snapshot(), "t": round(time.time(), 3)}
    for q in list(queue_listeners):
        try:
            q.put_nowait(ev)
        except Exception:                     # noqa: BLE001
            pass


def cancel_job(jid) -> bool:
    """Remove a pending item, or kill the running one."""
    job = jobs.get(jid)
    if not job or job["status"] in ("done", "error", "cancelled", "removed"):
        return False
    job["cancelled"] = True
    if job["status"] == "running":
        proc = job.get("proc")
        if proc and proc.poll() is None:
            try:
                proc.terminate()              # the transcribe loop checks the flag
            except Exception:                 # noqa: BLE001
                pass
    else:
        job["status"] = "removed"
    push_state()
    return True


def stop_all() -> int:
    return sum(cancel_job(j["id"]) for j in list(jobs.values())
               if j["status"] in ("queued", "resolving", "running"))


# A playlist is a reasonable thing to paste; a channel's entire back catalogue
# usually isn't what anyone meant. Queue a generous slice and say so, rather
# than silently dropping the rest or filling the list with 3,000 rows.
EXPAND_LIMIT = 200


def expand_collection(job, opts):
    """Turn a playlist/channel URL into one queued job per video.

    --flat-playlist lists entries without extracting each video, so this is one
    request rather than N. Runs on its own thread: a long channel listing must
    never hold up the POST that submitted it.
    """
    _ytdlp_ready.wait(timeout=180)
    cmd = [sys.executable, "-m", "yt_dlp", "--flat-playlist", "-J",
           "--ignore-errors"] + js_runtime_args() + [job["url"]]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        data = json.loads(r.stdout or "{}")
        entries = [e for e in (data.get("entries") or []) if e]
    except Exception:                              # noqa: BLE001
        entries = []

    if job["cancelled"]:
        job["status"] = "removed"
        push_state()
        return

    if not entries:
        job["status"] = "error"
        job["error"] = ("Couldn't read that playlist. Check the link, or paste "
                        "the individual video links instead.")
        emit(job, "error", job["error"])
        push_state()
        return

    total = len(entries)
    for e in entries[:EXPAND_LIMIT]:
        url = e.get("url") or e.get("webpage_url") or e.get("id")
        if not url:
            continue
        if not str(url).startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"
        child = make_job(url, opts)
        if e.get("title"):
            child["title"] = e["title"]
        work_q.put(child)

    if total > EXPAND_LIMIT:
        # Keep the row, as a standing note. Silently queueing 200 of 3,000
        # would look exactly like having queued all of them.
        job["status"] = "notice"
        job["title"] = (f"{total} videos found — queued the first "
                        f"{EXPAND_LIMIT}. Paste the rest separately.")
    else:
        job["status"] = "removed"              # replaced by its children
    push_state()


def enqueue(urls, opts):
    made = []
    for u in urls:
        job = make_job(u, opts)
        if is_collection_url(u):
            job["status"] = "resolving"
            job["title"] = f"Playlist — {short_title(u)}"
            threading.Thread(target=expand_collection, args=(job, opts),
                             daemon=True).start()
        else:
            work_q.put(job)
        made.append(job)
    cleanup_old_runs()
    push_state()
    return made


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
    job["proc"] = proc                  # so Stop can terminate the download
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
        # Check this first: a terminated yt-dlp also exits non-zero, and
        # blaming the user's URL for their own Stop would be nonsense.
        if job["cancelled"]:
            raise Cancelled()
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


def discard_scratch(job, only_if_empty=False):
    """Remove a job's run folder. Guarded: in audio mode job["dir"] points at
    the shared audio folder, which must never be touched."""
    d = Path(job["dir"]) if job.get("dir") else None
    if not d or d == OUT or OUT not in d.parents or not d.is_dir():
        return
    if only_if_empty and any(d.iterdir()):
        return
    shutil.rmtree(d, ignore_errors=True)


def run_job(job):
    """Run one job, cleaning up after itself if it's stopped or fails."""
    job["status"] = "running"
    push_state()
    try:
        _run_job(job)
    except Cancelled:
        discard_scratch(job)            # don't leave a half-downloaded MP3
        raise
    except Exception:                   # noqa: BLE001
        # A link that couldn't be downloaded otherwise leaves an empty folder
        # behind — barely noticeable once, but a queue makes a mess of it.
        discard_scratch(job, only_if_empty=True)
        raise


def _run_job(job):
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

    if job["cancelled"]:            # covers a Stop during the model download
        raise Cancelled()
    model = get_model(job["model"])
    lang = None if job["language"] == "auto" else job["language"]
    segments, info = model.transcribe(
        str(audio), language=lang, vad_filter=True,
        beam_size=1, condition_on_previous_text=False)   # greedy = faster on CPU
    emit(job, "status", f"Transcribing about {info.duration / 3600:.1f} hours of "
                        f"audio. Text appears below as it goes…")

    segs, srt_blocks, n = [], [], 0
    for seg in segments:
        if job["cancelled"]:        # segments arrive continuously, so this is quick
            raise Cancelled()
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
            if job["cancelled"]:
                # Removed or stopped while it sat in the queue.
                if job["status"] != "removed":
                    job["status"] = "cancelled"
                continue
            run_job(job)
        except Cancelled:
            job["status"] = "cancelled"
            emit(job, "cancelled", "Stopped.")
        except Exception as e:                       # noqa: BLE001
            job["status"] = "error"
            job["error"] = str(e)
            emit(job, "error", str(e))
        finally:
            job["proc"] = None
            push_state()
            work_q.task_done()


threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return send_file(BASE / "index.html")


def read_opts(data):
    mode = data.get("mode")
    if mode is None:
        # A browser holding a cached copy of the old page still posts keep_audio.
        mode = "both" if data.get("keep_audio") else "transcript"
    if mode not in MODES:
        raise ValueError(f"Unknown mode '{mode}'.")
    return {"mode": mode,
            "model": data.get("model", "small.en"),
            "language": data.get("language", "en"),
            "srt": bool(data.get("srt", True))}


@app.route("/api/queue", methods=["GET"])
def get_queue():
    return jsonify({"items": snapshot()})


@app.route("/api/queue", methods=["POST"])
def post_queue():
    data = request.get_json(force=True, silent=True) or {}
    # Accept a raw paste, an explicit list, or the old single-url field, and
    # run all three through the same extraction — never trust the client's split.
    text = str(data.get("text") or "")
    if data.get("urls"):
        text += "\n" + "\n".join(str(u) for u in data["urls"])
    if data.get("url"):
        text += "\n" + str(data["url"])
    urls = extract_urls(text)
    if not urls:
        return jsonify({"error": "No links found — each link needs to start "
                                 "with http:// or https://."}), 400
    try:
        opts = read_opts(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    made = enqueue(urls, opts)
    # No "Queued…" event: the row in the queue says so, and broadcasting it
    # would let a newly-appended job overwrite the running one's status line.
    return jsonify({"items": snapshot(), "added": len(made),
                    "job_id": made[0]["id"]})


@app.route("/api/queue/<jid>", methods=["DELETE"])
def delete_queue_item(jid):
    if jid not in jobs:
        abort(404)
    return jsonify({"ok": cancel_job(jid), "items": snapshot()})


@app.route("/api/queue/stop", methods=["POST"])
def stop_queue():
    return jsonify({"stopped": stop_all(), "items": snapshot()})


@app.route("/api/queue/events")
def queue_events():
    """One stream for the whole app, held open for the life of the page.

    Unlike the per-job stream this never self-terminates, which is what lets a
    reload reattach to a run instead of orphaning it.
    """
    def stream():
        q: "queue.Queue" = queue.Queue()
        queue_listeners.add(q)
        try:
            yield f"data: {json.dumps({'kind': 'state', 'items': snapshot()})}\n\n"
            # Replay only the running job's transcript. Finished ones are on
            # disk and reachable from their row.
            running = next((j for j in sorted(jobs.values(), key=lambda j: j["seq"])
                            if j["status"] == "running"), None)
            if running:
                for ev in list(running["events"]):
                    yield f"data: {json.dumps(ev)}\n\n"
            while True:
                try:
                    ev = q.get(timeout=15)
                    yield f"data: {json.dumps(ev)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            queue_listeners.discard(q)

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/jobs", methods=["POST"])
def create_job():
    # Kept so a browser holding a cached copy of the old page keeps working.
    return post_queue()


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
