# 🎙️ WTF Transcription Factory

_Paste a video or podcast link — find out WTF was said._

A tiny local app: paste a URL into a web page, and it identifies the video/audio,
downloads it, and transcribes it with a Whisper speech-to-text model — entirely
on your own machine. Nothing is uploaded to any third-party service.

Under the hood it wraps three open-source tools:

- **yt-dlp** — identifies and downloads the video (1000+ sites, plus a generic
  extractor that finds HLS/MP4 streams embedded in most pages).
- **ffmpeg** — extracts the audio (provisioned automatically — you don't
  install it).
- **faster-whisper** — runs OpenAI's Whisper model locally; handles multi-hour
  files via built-in voice-activity detection.

---

## Install & run

### macOS / Linux — one line

Open **Terminal** and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/mkiser/wtf-transcription-factory/main/install.sh | bash
```

### Windows — one line

Open **PowerShell** and paste:

```powershell
irm https://raw.githubusercontent.com/mkiser/wtf-transcription-factory/main/install.ps1 | iex
```

Either installer sets everything up and creates a **“WTF Transcription Factory”**
app — launch it from **Launchpad / Spotlight** (macOS) or the **Start Menu /
Desktop** (Windows). **No security warnings:** the launcher is built on your own
machine, so it's never quarantined, and a script piped into `bash`/`iex` isn't
quarantined either.

The only prerequisite is **Python**. If it's missing, the installer opens the
download page and tells you what to do, then you re-run the one line.

Then paste a link → **Transcribe**. The text streams in live; when done you get
**Download transcript**, **Download .srt**, and **Open folder** buttons.

**Update** later by re-running the one-liner. **Uninstall:** delete the app
shortcut and the app folder (`~/.wtf-transcription-factory` on macOS/Linux, or
`%LOCALAPPDATA%\WTF Transcription Factory` on Windows).

---

## Choosing quality vs. speed

| UI label               | Model       | Notes                                |
|------------------------|-------------|--------------------------------------|
| Fastest                | `tiny.en`   | rough; quick gist                    |
| Fast                   | `base.en`   |                                      |
| Balanced (recommended) | `small.en`  | good default                         |
| High quality           | `medium.en` | slower                               |
| Best quality           | `large-v3`  | best, slowest; works in any language |

> **Speed note:** the model runs on the **CPU**. Rough time per **1 hour of
> audio**: Fastest ≈ a few min, Balanced ≈ 10–20 min, Best ≈ an hour-plus. For
> long videos use Fastest or Balanced.

---

## Output files

Whisper produces short caption-sized chunks; the app merges them into readable
paragraphs and gives you: `transcript.txt` (readable, no timestamps),
`transcript_timestamps.txt` (one timestamp per paragraph), and `transcript.srt`
(subtitles). On the page you can toggle timestamps and hit **Copy all**. Each
run is saved in its own dated folder under `transcripts/`; old runs auto-delete
after 30 days (`RETAIN_DAYS` to change).

---

## Privacy

Everything runs locally. The only outbound traffic is yt-dlp fetching the video
you asked for, plus one-time downloads of ffmpeg and the speech model. Your
audio and transcripts never leave your machine.

## ⚠️ Disclaimer & responsible use

This tool downloads and transcribes **only the URLs you provide**. **You** are
responsible for complying with copyright and each site's Terms of Service, and
for only using content you have the right to. Provided **"as is", without
warranty**; the authors are **not liable** for misuse. Not affiliated with any
platform. Full text: [`DISCLAIMER.md`](DISCLAIMER.md). _(Not legal advice.)_

## License

[MIT](LICENSE). Third-party components: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
