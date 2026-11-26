# 🎵 BGM-Radar

**An AI Agent Skill & CLI for identifying background music (BGM) in Bilibili, YouTube, and local videos — even under heavy narration, dialogue, and sound effects.**

一个专为 **B站 / YouTube / 本地视频** 打造的背景音乐（BGM）雷达工具与标准 **Agent Skill**（兼容 Antigravity、Claude Code、Codex、Cursor 等）。

---

## ✨ Why BGM-Radar? / 为什么做这个工具？

Most BGM scripts simply download a video and run a single Shazam call, which often fails or hallucinates on Chinese commentary/movie-recap videos where narration and explosions drown out the music. **BGM-Radar** solves this with a 3-layer verification pipeline:

1. **⚡ Zero-Download Bilibili Danmaku & Metadata Mining（B站弹幕零下载秒查）**
   - Automatically inspects Bilibili video metadata, official BGM tags, and **public Danmaku XML (`comment.bilibili.com/{cid}.xml`)** without needing cookies — catching viewer answers like `bgm 以马内利` in ~2 seconds.
2. **🎯 Multi-Point Acoustic Fingerprinting & Cross-Verification（多点切片 + 交叉投票防误报）**
   - Extracts audio-only streams via `yt-dlp` and slices timeline windows via `ffmpeg`, then runs `shazamio` with concurrency + retries.
   - Tracks matched across **2+ timestamps** are marked `HIGH` confidence; single noisy hits are flagged as `CANDIDATE` to eliminate false positives.
3. **🎙️ Optional Vocal Attenuation & Multimodal Review（人声压制 + 多模态复听）**
   - Supports `--suppress-vocals` (`ffmpeg` center-channel attenuation) when narration covers the melody, plus `--keep-clips` so multimodal AI agents can listen directly to verify.

---

## 🏗️ Pipeline / 工作流程

```text
Video URL / Local File
   │
   ├─► [1] Bilibili Fast Clues (Zero Download)
   │       ├─ Official BGM tags
   │       ├─ Danmaku XML keyword scan (bgm / 配乐 / 歌名 / 求歌...)
   │       └─ Top comments scan
   │
   ├─► [2] Audio Extraction & Slicing
   │       ├─ yt-dlp -f bestaudio (audio-only, fast & small)
   │       └─ ffmpeg timeline grid or targeted --time clips (+ optional --suppress-vocals)
   │
   └─► [3] Multi-Point Shazam Fingerprinting & Voting
           ├─ HIGH CONFIDENCE: matched >= 2 timestamps (or corroborated by danmaku)
           └─ CANDIDATE: single hit (flag for manual / multimodal verification)
```

---

## 🚀 Installation / 安装

### Prerequisites
- Python 3.10+
- `ffmpeg` and `ffprobe` available in `PATH`

### Install Python dependencies
```bash
git clone https://github.com/Toki22520/bgm-radar.git
cd bgm-radar
pip install -r requirements.txt
```

---

## 💻 CLI Usage / 命令行用法

```bash
# 1. Zero-download Bilibili clues check (metadata + danmaku + comments)
python scripts/bgm_radar.py "https://www.bilibili.com/video/BV1hxT3zSEZE/" --clues-only

# 2. Full timeline scan (8 evenly spaced 15s samples)
python scripts/bgm_radar.py "https://www.bilibili.com/video/BV1hxT3zSEZE/" --samples 8

# 3. Inspect specific timestamps (MM:SS) and keep clips for verification
python scripts/bgm_radar.py "https://www.bilibili.com/video/BV1hxT3zSEZE/" --time 00:05,08:35,14:00 --keep-clips ./bgm_clips

# 4. Heavy narration? Enable vocal suppression + HTTP proxy
python scripts/bgm_radar.py "https://www.bilibili.com/video/BV1hxT3zSEZE/" --time 00:05,08:35 --suppress-vocals --proxy http://127.0.0.1:7890

# 5. Machine-readable JSON output for AI Agents
python scripts/bgm_radar.py "https://www.bilibili.com/video/BV1hxT3zSEZE/" --clues-only --json
```

---

## 🤖 Use as an AI Agent Skill / 作为 Agent Skill 安装

This repo follows the standard `SKILL.md` format:

- **Antigravity (AGY)**: Copy this folder to `~/.gemini/config/skills/bgm-radar/`
- **Claude Code / Codex / Cursor**: Copy this folder into your agent's global or project `skills/` directory (e.g. `.agents/skills/bgm-radar/` or `~/.claude/skills/bgm-radar/`).

Then simply ask your agent:
> "帮我找出这个视频的背景音乐是什么：https://www.bilibili.com/video/BV1hxT3zSEZE/"

---

## ⚠️ Disclaimer / 免责声明

This project is intended solely for personal music discovery, learning, and research. Please respect platform terms of service and music copyrights.

## 📄 License

[MIT](LICENSE)
