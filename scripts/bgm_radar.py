#!/usr/bin/env python3
"""
BGM-Radar: Find background music (BGM) in Bilibili, YouTube, and local videos.
Combines zero-download Bilibili danmaku/metadata mining with yt-dlp + ffmpeg +
Shazam multi-point cross-verification.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BGM_KEYWORDS = re.compile(
    r"(bgm|背景音乐|背景音|插曲|配乐|纯音乐|歌名|什么歌|求歌|求bgm|曲名|原声|ost)",
    re.IGNORECASE,
)

BVID_PATTERN = re.compile(r"(BV[0-9A-Za-z]{10})")


@dataclass
class DanmakuClue:
    timestamp_sec: float
    timestamp_str: str
    text: str


@dataclass
class RecognitionHit:
    timestamp_sec: int
    timestamp_str: str
    title: str
    artist: str
    clip_path: str | None = None
    error: str | None = None


def fmt_time(seconds: float) -> str:
    sec = max(0, int(round(seconds)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def parse_timestamp(raw: str) -> int:
    parts = [int(p) for p in raw.strip().split(":")]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"Invalid timestamp: {raw}")


def http_get_bytes(url: str, referer: str = "https://www.bilibili.com/", timeout: int = 15) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": referer,
            "Accept-Encoding": "gzip, deflate",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        enc = (resp.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip":
            return zlib.decompress(data, 16 + zlib.MAX_WBITS)
        if enc == "deflate":
            try:
                return zlib.decompress(data)
            except zlib.error:
                return zlib.decompress(data, -zlib.MAX_WBITS)
        return data


def http_get_json(url: str, referer: str = "https://www.bilibili.com/", timeout: int = 15) -> dict[str, Any]:
    raw = http_get_bytes(url, referer=referer, timeout=timeout)
    return json.loads(raw.decode("utf-8", errors="replace"))


def fetch_bilibili_clues(url: str) -> dict[str, Any]:
    """Fetch Bilibili video metadata, official BGM tags, and danmaku BGM clues."""
    m = BVID_PATTERN.search(url)
    if not m:
        return {}
    bvid = m.group(1)
    referer = f"https://www.bilibili.com/video/{bvid}/"
    result: dict[str, Any] = {
        "bvid": bvid,
        "title": "",
        "owner": "",
        "duration": 0,
        "desc": "",
        "music_tags": [],
        "danmaku_clues": [],
        "comment_clues": [],
    }

    try:
        view = http_get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", referer=referer)
        data = view.get("data") or {}
        result["title"] = data.get("title", "")
        result["owner"] = (data.get("owner") or {}).get("name", "")
        result["duration"] = int(data.get("duration") or 0)
        result["desc"] = data.get("desc", "")
        cid = data.get("cid")
        aid = data.get("aid")
    except Exception as e:
        result["error"] = f"Failed to fetch Bilibili metadata: {e}"
        return result

    # 1. Check official BGM tags
    if cid:
        try:
            tags_resp = http_get_json(
                f"https://api.bilibili.com/x/web-interface/view/detail/tag?bvid={bvid}&cid={cid}",
                referer=referer,
            )
            for tag in tags_resp.get("data") or []:
                if tag.get("music_id") or tag.get("tag_type") == "bgm":
                    result["music_tags"].append(tag.get("tag_name", ""))
        except Exception:
            pass

    # 2. Scan Bilibili Danmaku XML (public, no login required)
    if cid:
        try:
            dm_raw = http_get_bytes(f"https://comment.bilibili.com/{cid}.xml", referer=referer)
            # Some endpoints return raw deflate even without Content-Encoding header
            if not dm_raw.lstrip().startswith(b"<"):
                try:
                    dm_raw = zlib.decompress(dm_raw, -zlib.MAX_WBITS)
                except zlib.error:
                    dm_raw = zlib.decompress(dm_raw, 16 + zlib.MAX_WBITS)
            root = ET.fromstring(dm_raw.decode("utf-8", errors="replace"))
            clues: list[DanmakuClue] = []
            seen: set[str] = set()
            for elem in root.findall("d"):
                text = (elem.text or "").strip()
                if not text or not BGM_KEYWORDS.search(text):
                    continue
                p_attr = (elem.attrib.get("p") or "0").split(",")
                t_sec = float(p_attr[0]) if p_attr else 0.0
                dedup_key = text.lower()
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                clues.append(DanmakuClue(t_sec, fmt_time(t_sec), text))
            clues.sort(key=lambda c: c.timestamp_sec)
            result["danmaku_clues"] = [asdict(c) for c in clues[:30]]
        except Exception as e:
            result["danmaku_error"] = str(e)

    # 3. Scan first page of hot comments (best-effort)
    if aid:
        try:
            rep = http_get_json(
                f"https://api.bilibili.com/x/v2/reply?type=1&oid={aid}&sort=2&ps=20&pn=1",
                referer=referer,
            )
            replies = (rep.get("data") or {}).get("replies") or []
            for r in replies:
                msg = ((r.get("content") or {}).get("message") or "").replace("\n", " ").strip()
                if BGM_KEYWORDS.search(msg):
                    result["comment_clues"].append(msg)
        except Exception:
            pass

    return result


def get_audio_duration(audio_path: Path) -> int:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
        return int(float(out))
    except Exception:
        return 0


def download_audio(url: str, work_dir: Path, proxy: str | None = None) -> Path:
    out_tpl = str(work_dir / "source_audio.%(ext)s")
    cmd = ["yt-dlp", "-f", "bestaudio", "--no-playlist", "-o", out_tpl]
    if proxy:
        cmd += ["--proxy", proxy]
    cmd.append(url)
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    files = list(work_dir.glob("source_audio.*"))
    if not files:
        raise RuntimeError("yt-dlp finished but no audio file was created.")
    return files[0]


def extract_clip(
    src: Path,
    dst: Path,
    start_sec: int,
    duration_sec: int = 15,
    suppress_vocals: bool = False,
) -> Path:
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", str(start_sec), "-t", str(duration_sec), "-i", str(src)]
    if suppress_vocals:
        # Attenuate center-panned speech while preserving stereo/ambient music
        cmd += ["-af", "stereotools=mlev=0.35:slev=1.2"]
    cmd += ["-c:a", "libmp3lame", "-q:a", "4", str(dst)]
    subprocess.run(cmd, check=True)
    return dst


def resolve_http_proxy(cli_proxy: str | None) -> str | None:
    if cli_proxy:
        return cli_proxy
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        val = os.environ.get(key, "").strip()
        if val.startswith(("http://", "https://")):
            return val
    return None


async def recognize_clips(
    clips: list[tuple[int, Path]],
    proxy: str | None = None,
    concurrency: int = 3,
    retries: int = 2,
) -> list[RecognitionHit]:
    try:
        from shazamio import Shazam
        from shazamio.client import HTTPClient
    except ImportError as e:
        raise RuntimeError(
            "shazamio is not installed. Run: pip install shazamio"
        ) from e

    # Configure aiohttp client with proxy support when provided
    client_kwargs: dict[str, Any] = {}
    if proxy and proxy.startswith(("http://", "https://")):
        # shazamio's HTTPClient forwards requests via aiohttp_retry; setting env + trust_env
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy

    shazam = Shazam()
    sem = asyncio.Semaphore(concurrency)

    async def _one(sec: int, clip_path: Path) -> RecognitionHit:
        t_str = fmt_time(sec)
        last_err: str | None = None
        async with sem:
            for attempt in range(retries + 1):
                try:
                    out = await shazam.recognize(str(clip_path))
                    track = out.get("track")
                    if track:
                        return RecognitionHit(
                            timestamp_sec=sec,
                            timestamp_str=t_str,
                            title=track.get("title", ""),
                            artist=track.get("subtitle", ""),
                            clip_path=str(clip_path),
                        )
                    return RecognitionHit(
                        timestamp_sec=sec,
                        timestamp_str=t_str,
                        title="",
                        artist="",
                        clip_path=str(clip_path),
                    )
                except Exception as exc:
                    last_err = str(exc)
                    if attempt < retries:
                        await asyncio.sleep(1.5 * (attempt + 1))
        return RecognitionHit(
            timestamp_sec=sec,
            timestamp_str=t_str,
            title="",
            artist="",
            clip_path=str(clip_path),
            error=last_err,
        )

    hits = await asyncio.gather(*(_one(sec, p) for sec, p in clips))
    return sorted(hits, key=lambda h: h.timestamp_sec)


def summarize_hits(hits: list[RecognitionHit]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for h in hits:
        if h.title:
            grouped[(h.title, h.artist)].append(h.timestamp_str)
    summary = []
    for (title, artist), times in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        confidence = "HIGH (multi-point verified)" if len(times) >= 2 else "CANDIDATE (single hit - verify by ear)"
        summary.append(
            {
                "title": title,
                "artist": artist,
                "hits": len(times),
                "timestamps": times,
                "confidence": confidence,
            }
        )
    return summary


def build_sample_times(duration: int, num_samples: int, explicit_times: str | None) -> list[int]:
    if explicit_times:
        return sorted({parse_timestamp(t) for t in explicit_times.split(",") if t.strip()})
    if duration <= 20:
        return [0]
    usable = max(1, duration - 16)
    if num_samples <= 1:
        return [min(10, usable)]
    step = usable / num_samples
    times = [int(round(i * step + min(5, step / 3))) for i in range(num_samples)]
    return sorted({max(0, min(t, usable)) for t in times})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BGM-Radar: Identify background music in Bilibili, YouTube, or local videos."
    )
    parser.add_argument("source", help="Video URL (Bilibili, YouTube, etc.) or local audio/video file path")
    parser.add_argument("--clues-only", action="store_true", help="Only fetch Bilibili metadata/danmaku/comments (no download)")
    parser.add_argument("--time", dest="times", help="Comma-separated timestamps to inspect (e.g. 00:05,08:35,14:00)")
    parser.add_argument("--samples", type=int, default=8, help="Number of timeline samples when --time is omitted (default: 8)")
    parser.add_argument("--duration", type=int, default=15, help="Clip duration in seconds (default: 15)")
    parser.add_argument("--proxy", help="HTTP/HTTPS proxy URL (e.g. http://127.0.0.1:7890)")
    parser.add_argument("--suppress-vocals", action="store_true", help="Attenuate center-channel narration before recognition")
    parser.add_argument("--keep-clips", help="Directory to save extracted clips for manual/multimodal verification")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output structured JSON")
    args = parser.parse_args()

    is_url = args.source.startswith(("http://", "https://"))
    bili_clues = fetch_bilibili_clues(args.source) if is_url and "bilibili.com" in args.source else {}

    report: dict[str, Any] = {
        "source": args.source,
        "bilibili_clues": bili_clues,
        "summary": [],
        "timeline": [],
    }

    if args.clues_only:
        _print_report(report, args.as_json)
        return 0

    proxy = resolve_http_proxy(args.proxy)
    tmp_dir = Path(args.keep_clips) if args.keep_clips else Path(tempfile.mkdtemp(prefix="bgm_radar_"))
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        if is_url:
            audio_path = download_audio(args.source, tmp_dir, proxy=proxy)
        else:
            audio_path = Path(args.source).resolve()
            if not audio_path.exists():
                raise FileNotFoundError(f"Local file not found: {audio_path}")

        duration = bili_clues.get("duration") or get_audio_duration(audio_path)
        sample_times = build_sample_times(duration, args.samples, args.times)

        clips: list[tuple[int, Path]] = []
        for sec in sample_times:
            clip_path = tmp_dir / f"clip_{sec:05d}.mp3"
            extract_clip(audio_path, clip_path, sec, args.duration, args.suppress_vocals)
            clips.append((sec, clip_path))

        hits = asyncio.run(recognize_clips(clips, proxy=proxy))
        report["summary"] = summarize_hits(hits)
        report["timeline"] = [asdict(h) for h in hits]
    finally:
        if not args.keep_clips:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    _print_report(report, args.as_json)
    return 0


def _print_report(report: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    bili = report.get("bilibili_clues") or {}
    if bili:
        print(f"=== Bilibili Clues ({bili.get('bvid')}) ===")
        print(f"Title : {bili.get('title')}")
        print(f"Author: {bili.get('owner')} | Duration: {fmt_time(bili.get('duration', 0))}")
        if bili.get("music_tags"):
            print(f"Official BGM Tags: {', '.join(bili['music_tags'])}")
        dm = bili.get("danmaku_clues") or []
        if dm:
            print(f"\nDanmaku BGM mentions ({len(dm)}):")
            for c in dm[:15]:
                print(f"  [{c['timestamp_str']}] {c['text']}")
        else:
            print("Danmaku BGM mentions: none")
        print()

    summary = report.get("summary") or []
    if summary:
        print("=== Acoustic Recognition Summary ===")
        for item in summary:
            times = ", ".join(item["timestamps"])
            print(
                f"  - {item['title']} — {item['artist']} "
                f"[{item['confidence']}] (hits={item['hits']} at {times})"
            )
        print()

    timeline = report.get("timeline") or []
    if timeline:
        print("=== Timeline Details ===")
        for h in timeline:
            if h.get("title"):
                print(f"  [{h['timestamp_str']}] MATCH: {h['title']} - {h['artist']}")
            elif h.get("error"):
                print(f"  [{h['timestamp_str']}] ERROR: {h['error']}")
            else:
                print(f"  [{h['timestamp_str']}] NO MATCH")


if __name__ == "__main__":
    sys.exit(main())
