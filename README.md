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

Follow the steps for your computer: [Mac](#mac), [Windows](#windows), or
[Linux](#linux). You only do this once.

You don't need to install Python. The installer downloads its own private copy
into the app's folder and leaves any Python you already have alone.

### Mac

**1. Open Terminal.** Press **⌘ Command + Space**, type `Terminal`, and press
**Return**.

**2. Install Node.js if you'll use YouTube links.** YouTube needs Node.js to
download its videos. Skip this step if you'll never paste a YouTube link.

1. Go to [nodejs.org/en/download](https://nodejs.org/en/download).
2. Click **macOS Installer (.pkg)**.
3. Open the file that downloads. Click **Continue** on each screen, click
   **Agree**, then click **Install**. Enter your Mac password when it asks.
4. Click **Close**.

**3. Install the app.** Paste this into Terminal and press **Return**:

```bash
curl -fsSL https://raw.githubusercontent.com/mkiser/wtf-transcription-factory/main/install.sh | bash
```

The first install takes a few minutes. When it finishes, a new Terminal
window opens and the app opens in your browser.

**4. Next time, double-click “WTF Transcription Factory” on your Desktop.**
Keep the Terminal window it opens while you use the app. Close that window
to stop the app.

### Windows

**1. Open PowerShell.** Click **Start**, type `PowerShell`, and press
**Enter**. Windows 10 and 11 include it. If nothing called PowerShell shows
up, [install PowerShell](https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell-on-windows?view=powershell-7.6)
first, then open it.

**2. Install Node.js if you'll use YouTube links.** YouTube needs Node.js to
download its videos. Skip this step if you'll never paste a YouTube link.

1. Go to [nodejs.org/en/download](https://nodejs.org/en/download).
2. Click **Windows Installer (.msi)**.
3. Open the file that downloads. Click **Next** on each screen, accept the
   license, and leave every option as it is.
4. Click **Install**. If Windows asks whether to allow changes, click **Yes**.
5. Click **Finish**.

**3. Restart PowerShell if you installed Node.js.** Close the PowerShell window
completely, then open a new one as in step 1. The new window finds Node.js.

**4. Install the app.** Paste this into PowerShell and press **Enter**:

```powershell
irm https://raw.githubusercontent.com/mkiser/wtf-transcription-factory/main/install.ps1 | iex
```

The first install takes a few minutes. When it finishes, a small window
opens and the app opens in your browser.

**5. Next time, open “WTF Transcription Factory” from the Start menu or your
Desktop.** Keep the small window open while you use the app. Close it to
stop the app.

### Linux

Open a terminal and run the command from Mac step 3. The installer starts the
app and prints the command to start it again. Linux gets no launcher.

**No security warnings:** the launcher is built on your own
machine, so it's never quarantined, and a script piped into `bash`/`iex`
isn't quarantined either.

---

## Using it

Paste a link and pick what you want:

| Mode | What you get |
|------|--------------|
| **Transcript** | A transcript. The audio is fetched, used, and deleted. |
| **Audio only** | Just the MP3 — stereo, ~190 kbps, saved to `audio/`. No speech model is downloaded, so it finishes as fast as the download. |
| **Both** | The MP3 *and* a transcript, from the same file. |

The text streams in live; when it's done you get download buttons and **Open folder**.

### Doing a whole batch

You can paste **more than one link**. The box takes a list — newlines, commas,
numbered lines, or just a chunk of text you copied with links in it. It finds
every `http`/`https` link, tells you how many, and works through them one at a
time. A queue appears listing each one, and finished items keep their own
download buttons.

Paste a **playlist or channel** link and it expands into the individual videos
first. A `watch?v=…&list=…` link — what you get clicking a video from *inside*
a playlist — stays a single video, so you never queue 200 things by accident.
Channels are capped at 200 videos, and it says so when it hits the cap.

While the queue runs you can **✕** anything that hasn't started yet, press
**Stop** to halt everything including the item in progress, and keep adding
more links — the button turns into **Add to queue**. Closing or reloading the
page doesn't interrupt anything; reopening reattaches to the run.

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

**Update** the app itself by re-running the install command (Mac step 3,
Windows step 4). **Uninstall:** delete the app
shortcuts and the app folder (`~/.wtf-transcription-factory` on macOS/Linux, or
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
