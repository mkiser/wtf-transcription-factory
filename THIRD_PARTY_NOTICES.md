# Third-Party Notices

This project is a thin wrapper that stands on the shoulders of excellent
open-source software. It does **not** bundle these tools in the repository —
they are installed on first run (via `pip` and, for ffmpeg, downloaded at
runtime). Each is the property of its respective authors and is governed by its
own license.

| Tool | Purpose | License |
|------|---------|---------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Identify & download the source media | The Unlicense (public domain) |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Speech-to-text engine | MIT |
| [OpenAI Whisper](https://github.com/openai/whisper) | Speech-recognition models & method | MIT |
| [FFmpeg](https://ffmpeg.org) | Audio extraction | LGPL-2.1+/GPL (see note) |
| [static-ffmpeg](https://github.com/zackees/static_ffmpeg) | Fetches official FFmpeg builds at runtime | BSD/MIT |
| [Flask](https://github.com/pallets/flask) | Local web server | BSD-3-Clause |

**FFmpeg note:** this project does not redistribute FFmpeg binaries. They are
downloaded from their official source on first use by `static-ffmpeg`. FFmpeg is
licensed under the LGPL/GPL; your use of the downloaded binaries is subject to
those licenses.

Trademarks (including any platform, product, or company names) belong to their
respective owners and are used for identification only.
