---
name: bgm-radar
description: Identify background music (BGM) in Bilibili, YouTube, Douyin, or local videos — even under heavy narration or sound effects. Combines zero-download Bilibili danmaku/metadata/tag mining with yt-dlp audio extraction, ffmpeg timeline slicing, Shazam multi-point cross-verification, and multimodal audio confirmation. Use when the user shares a video link or file and asks what the BGM/song/music is.
---

# BGM-Radar

Identify background music (BGM) from online videos (especially Bilibili commentary/edit videos) or local media files with high accuracy and low false-positive rates.

## Core Principles (Anti-Hallucination & Anti-False-Positive)

1. **Never guess BGM from web search or movie titles alone.** Commentary videos frequently use third-party BGM unrelated to the movie's official OST.
2. **Always mine Bilibili Danmaku first (zero download).** For Bilibili links, B站弹幕 XML (`comment.bilibili.com/{cid}.xml`) is public without login and often contains exact BGM answers right when the track starts.
3. **Never trust a single Shazam hit blindly on noisy/narrated audio.** Require either:
   - **2+ matches** of the same track across different timestamps, OR
   - **Corroboration** with Bilibili danmaku/comments/official tags, OR
   - **Direct multimodal audio review** of the extracted clip (`--keep-clips` + `read_file` on the `.mp3`).

## Workflow

### Step 1 — Fast Clues Check (Bilibili)

For Bilibili URLs, run `--clues-only` first (completes in ~2 seconds, no download):

```bash
python scripts/bgm_radar.py "<VIDEO_URL>" --clues-only
```

Check:
- Official BGM tags (`music_tags`)
- Danmaku BGM mentions (`danmaku_clues`) with timestamps
- Top comments (`comment_clues`)

### Step 2 — Acoustic Multi-Point Recognition

Run full timeline sampling (or targeted `--time` if the user specified a timestamp or danmaku pointed to a specific moment):

```bash
# Full timeline scan (8 evenly spaced 15s clips)
python scripts/bgm_radar.py "<VIDEO_URL>" --samples 8

# Targeted timestamp inspection (e.g. 00:05 and 08:35)
python scripts/bgm_radar.py "<VIDEO_URL>" --time 00:05,08:35 --keep-clips ./bgm_clips
```

Tips:
- **Heavy narration / dialogue covering the BGM?** Add `--suppress-vocals` to attenuate center-panned speech before fingerprinting.
- **Network timeout / China mainland environment?** Pass an HTTP proxy via `--proxy http://127.0.0.1:7890` (avoid passing `socks5h://` to `pip`/`aiohttp` unless `PySocks` is installed).
- **Machine-readable output?** Add `--json`.

### Step 3 — Cross-Verify & Report

Before answering the user:
1. Combine **Danmaku clues** + **Shazam multi-point hits** (`HIGH` confidence).
2. Discard single-hit noise matches (e.g. random tracks matched during explosions/dialogue) unless verified by listening to the saved clip (`--keep-clips`).
3. Present:
   - Confirmed track **Title** and **Artist**
   - **Timestamps** where it appears
   - **Evidence source** (e.g. Shazam multi-point match + Bilibili danmaku confirmation)
   - Offer to pinpoint any other specific `MM:SS` timestamp if the video contains multiple tracks.

## Prerequisites

- Python 3.10+
- `ffmpeg` and `ffprobe` in `PATH`
- Python packages: `pip install -r requirements.txt` (`yt-dlp`, `shazamio`, `aiohttp`)
