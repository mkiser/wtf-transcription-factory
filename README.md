# 🎙️ WTF Transcription Factory

_Paste a video or podcast link — find out WTF was said._

A tiny local app: paste a URL into a web page, and it identifies the video/audio
and pulls it down. Keep the audio as an MP3, transcribe it with a Whisper
speech-to-text model, or both — entirely on your own machine. Nothing is
uploaded to any third-party service.

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

Either installer sets everything up. On **macOS** it puts a **“WTF Transcription
Factory”** launcher on your **Desktop** — double-click it to run, and close its
window to stop. On **Windows** it adds **Start Menu / Desktop** shortcuts. **No
security warnings:** the launcher is built on your own machine, so it's never
quarantined, and a script piped into `bash`/`iex` isn't quarantined either.

The only prerequisite is **Python**. If it's missing, the installer opens the
download page and tells you what to do, then you re-run the one line.

Then paste a link and pick what you want:

| Mode | What you get |
|------|--------------|
| **Transcript** | A transcript. The audio is fetched, used, and deleted. |
| **Audio only** | Just the MP3 — stereo, ~190 kbps, saved to `audio/`. No speech model is downloaded, so it finishes as fast as the download. |
| **Both** | The MP3 *and* a transcript, from the same file. |

The text streams in live; when it's done you get download buttons and **Open folder**.

**YouTube needs a JavaScript runtime.** YouTube requires solving a signature
challenge, which needs **Node.js** ([nodejs.org](https://nodejs.org)) or
**Deno**. The app finds one automatically — including Homebrew and nvm installs
that aren't on the launcher's `PATH`. Without one, YouTube reports perfectly
good videos as *"This video is not available"*; the app will tell you so rather
than blaming your link. Other sites are unaffected.

**Staying current:** yt-dlp is in a constant arms race with the sites it
supports, so the app quietly refreshes it in the background at most once a day.
If you're offline it keeps the copy it has and tries again next time. The other
components are left alone so a working install doesn't change under you.

**Update** the app itself by re-running the one-liner. **Uninstall:** delete the app
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

Everything lands in **`~/Downloads/WTF Transcription Factory/`** — a normal,
visible folder, not buried inside the app:

```
~/Downloads/WTF Transcription Factory/
├─ audio/         one dated MP3 per "Audio only" run
└─ transcripts/   one dated folder per transcription run
```

Set `WTF_OUTPUT_DIR` to put them somewhere else.

Whisper produces short caption-sized chunks; the app merges them into readable
paragraphs and gives you: `transcript.txt` (readable, no timestamps),
`transcript_timestamps.txt` (one timestamp per paragraph), and `transcript.srt`
(subtitles). On the page you can toggle timestamps and hit **Copy all**. Old
transcript runs auto-delete after 30 days (`RETAIN_DAYS` to change).

Saved audio is **never auto-deleted** — only `transcripts/` is swept. It's
encoded for listening (stereo, ~190 kbps, roughly 90 MB per hour) rather than
the mono 16 kHz the speech model needs; in **Both** mode Whisper reads that same
file and resamples internally, so there's only ever one copy.

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
