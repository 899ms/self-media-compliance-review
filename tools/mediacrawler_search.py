#!/usr/bin/env python3
"""Wrap a local MediaCrawler checkout as the free live-search route.

TikHub (`tools/tikhub/`) is a paid REST adapter. This wrapper is the
no-cost alternative: the user clones MediaCrawler, logs in with their own
platform account once, and this script drives a keyword search run, then
normalizes the crawled rows into the record shape used by this project
(`{"id", "title", "nick", "comments", "likes", "date", "url", "platform"}`).

MediaCrawler is NOT bundled here (its license forbids commercial use and
redistribution terms differ from this repo). Point ``--mc-dir`` or the
``MEDIACRAWLER_HOME`` environment variable at a local clone:

    git clone https://github.com/NanmiCoder/MediaCrawler
    cd MediaCrawler && uv sync          # first setup, see tools/mediacrawler/README.md

Typical invocation (first run opens a browser for QR login; the session is
cached inside the MediaCrawler checkout for later runs):

    python tools/mediacrawler_search.py --platform xiaohongshu \
        --keywords "小红书 限流 申诉,小红书 封号 经验" --max-notes 20

Outputs land in a gitignored local directory (default
``local/mc_output/<platform>-<timestamp>/``): raw JSONL written by
MediaCrawler plus normalized ``records.json`` and a compact ``digest.md``.
Never commit them, the account cookies, or the MediaCrawler browser data.

Compliance: use your own account, small samples, low frequency, public
content only, for learning and research. MediaCrawler ships a
non-commercial learning license; respect it and the target platforms'
terms. Account restriction is exactly what this repository documents —
prefer a throwaway account.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# Project-style platform name -> MediaCrawler platform code.
PLATFORMS = {
    "xiaohongshu": "xhs",
    "xhs": "xhs",
    "douyin": "dy",
    "dy": "dy",
    "kuaishou": "ks",
    "ks": "ks",
    "bilibili": "bili",
    "bili": "bili",
    "weibo": "wb",
    "wb": "wb",
    "tieba": "tieba",
    "zhihu": "zhihu",
}

PROFILE_URL = {
    "xhs": "https://www.xiaohongshu.com/explore/{id}",
    "dy": "https://www.douyin.com/video/{id}",
    "ks": "https://www.kuaishou.com/short-video/{id}",
    "bili": "https://www.bilibili.com/video/{id}",
}

ID_KEYS = ("comment_id", "note_id", "aweme_id", "video_id", "photo_id",
           "bvid", "post_id", "mblog_id", "content_id", "id")
TITLE_KEYS = ("title", "desc", "content", "text")
NICK_KEYS = ("nickname", "nick_name", "user_name", "name")
COMMENT_KEYS = ("comment_count", "comment_count_singlenotes", "commentCnt")
LIKE_KEYS = ("liked_count", "like_count", "digg_count", "likedCount")
TIME_KEYS = ("time", "create_time", "publish_time", "last_update_time")
URL_KEYS = ("note_url", "aweme_url", "content_url", "video_url", "noteUrl")


def _first(row: dict, keys: Iterable[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", 0, "0"):
            return value
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _as_date(value: Any) -> str | None:
    """MediaCrawler stores unix seconds or milliseconds depending on platform."""
    ts = _as_int(value)
    if ts is None or ts <= 0:
        return None
    if ts > 10**12:  # milliseconds
        ts //= 1000
    try:
        return datetime.datetime.fromtimestamp(
            ts, datetime.timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def normalize_row(row: dict, platform: str) -> dict | None:
    """Map one crawled row to the project record shape; None when unusable."""
    if not isinstance(row, dict):
        return None
    rid = _first(row, ID_KEYS)
    if rid is None:
        return None
    rid = str(rid)
    # Link comment rows back to their parent note/video, not the comment id.
    url = _first(row, URL_KEYS)
    if not url:
        url_id = _first(row, ("note_id", "aweme_id", "video_id", "photo_id",
                              "bvid")) or rid
        url = PROFILE_URL.get(platform, "").format(id=url_id) or None
    title = _first(row, TITLE_KEYS)
    return {
        "id": rid,
        "title": (str(title)[:80] if title else "(无标题)"),
        "nick": _first(row, NICK_KEYS),
        "comments": _as_int(_first(row, COMMENT_KEYS)),
        "likes": _as_int(_first(row, LIKE_KEYS)),
        "date": _as_date(_first(row, TIME_KEYS)),
        "url": url,
        "platform": platform,
        "keyword": row.get("source_keyword"),
    }


def load_rows(path: Path) -> list[dict]:
    """Read one MediaCrawler output file (.jsonl or a .json array)."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    rows: list[Any]
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        decoded = json.loads(text)
        rows = decoded if isinstance(decoded, list) else [decoded]
    return [row for row in rows if isinstance(row, dict)]


def discover(out_dir: Path) -> tuple[list[Path], list[Path]]:
    """Find content and comment files written by one run into a fresh dir.

    MediaCrawler names output files
    ``{crawler_type}_{item_type}_{date}.{ext}`` under
    ``<out>/<platform>/<ext>/`` — e.g. ``search_contents_2026-09-16.jsonl``
    and ``search_comments_2026-09-16.jsonl``.
    """
    contents: list[Path] = []
    comments: list[Path] = []
    if out_dir.is_dir():
        for path in sorted(out_dir.rglob("*")):
            if not path.is_file() or path.suffix not in (".json", ".jsonl"):
                continue
            name = path.name.lower()
            if "comments" in name:
                comments.append(path)
            elif "contents" in name:
                contents.append(path)
    return contents, comments


def collect_records(out_dir: Path, platform: str) -> tuple[list[dict], list[dict]]:
    """Normalize all rows from one run; records and comments deduped by id."""
    content_files, comment_files = discover(out_dir)
    records: dict[str, dict] = {}
    for path in content_files:
        for row in load_rows(path):
            rec = normalize_row(row, platform)
            if rec and rec["id"] not in records:
                records[rec["id"]] = rec
    comments: dict[str, dict] = {}
    for path in comment_files:
        for row in load_rows(path):
            rec = normalize_row(row, platform)
            if rec and rec["id"] not in comments:
                comments[rec["id"]] = rec
    ordered = sorted(
        records.values(),
        key=lambda r: (r["comments"] if r["comments"] is not None else -1),
        reverse=True,
    )
    return ordered, list(comments.values())


def build_cmd(mc_dir: Path, args: argparse.Namespace) -> tuple[list[str], Path]:
    """Compose the MediaCrawler command line for one search run."""
    platform = PLATFORMS[args.platform]
    argv = list(args.keywords.split(","))
    cmd: list[str]
    uv = shutil.which("uv")
    if uv and (mc_dir / "uv.lock").is_file():
        cmd = [uv, "run", "main.py"]
    else:
        cmd = [sys.executable, str(mc_dir / "main.py")]
    cmd += [
        "--platform", platform,
        "--lt", args.login,
        "--type", "search",
        "--keywords", ",".join(argv),
        "--crawler_max_notes_count", str(args.max_notes),
        "--save_data_option", "jsonl",
        "--save_data_path", str(args.out),
        "--get_comment", "true" if args.with_comments else "false",
    ]
    if args.headless:
        cmd += ["--headless", "true"]
    return cmd, mc_dir


def write_digest(out_dir: Path, platform: str, args: argparse.Namespace,
                 records: list[dict], comments: list[dict]) -> Path:
    lines = [
        (
            f"# MediaCrawler search digest {platform} "
            f"{datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec='seconds')}\n"
        ),
        (
            f"\nKeywords: `{args.keywords}` | max notes: {args.max_notes} | "
            f"records: {len(records)} | comments: {len(comments)}\n"
        ),
        (
            "\nSource: user's own logged-in local browser via MediaCrawler "
            "(免费路线, non-commercial learning use only).\n"
        ),
    ]
    for rec in records[:60]:
        kw = f" | {rec['keyword']}" if rec.get("keyword") else ""
        lines.append(
            f"- id={rec['id']} 💬{rec['comments']} 👍{rec['likes']} "
            f"| {rec['date']} | {rec['nick']}{kw} | {rec['title']}\n"
        )
    digest = out_dir / "digest.md"
    digest.write_text("".join(lines), encoding="utf-8")
    (out_dir / "records.json").write_text(
        json.dumps({"records": records, "comments": comments},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return digest


def default_out(platform: str) -> Path:
    stamp = datetime.datetime.now(datetime.timezone.utc).astimezone().strftime(
        "%Y%m%d-%H%M%S"
    )
    base = REPO_ROOT / "local" / "mc_output"
    fallback = Path.cwd() / "mc_output"
    root = base if (REPO_ROOT / ".git").exists() else fallback
    return root / f"{platform}-{stamp}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="MediaCrawler clone is required: see tools/mediacrawler/README.md",
    )
    parser.add_argument("--platform", required=True,
                        help="xiaohongshu/xhs, douyin/dy, kuaishou/ks, "
                             "bilibili/bili, weibo/wb, tieba, zhihu")
    parser.add_argument("--keywords", required=True,
                        help="comma-separated search keywords")
    parser.add_argument("--max-notes", type=int, default=20,
                        help="max notes per run (default 20; keep it small)")
    parser.add_argument("--login", default="qrcode",
                        choices=("qrcode", "phone", "cookie"),
                        help="first-run login type (session is cached)")
    parser.add_argument("--with-comments", action="store_true",
                        help="also crawl first-level comments (slower)")
    parser.add_argument("--headless", action="store_true",
                        help="run the browser headless (more detection risk)")
    parser.add_argument("--mc-dir", type=Path,
                        default=Path(os.environ.get("MEDIACRAWLER_HOME", "")),
                        help="path to the local MediaCrawler checkout "
                             "(or set MEDIACRAWLER_HOME)")
    parser.add_argument("--out", type=Path, default=None,
                        help="output directory (default: gitignored local/)")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="run timeout in seconds (default 1800)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the MediaCrawler command and exit")
    args = parser.parse_args(argv)

    if args.platform not in PLATFORMS:
        parser.error(f"unsupported platform: {args.platform}")
    args.platform = PLATFORMS.get(args.platform, args.platform)
    args.out = args.out or default_out(args.platform)
    if not args.mc_dir or not args.mc_dir.is_dir():
        parser.error(
            "MediaCrawler checkout not found; pass --mc-dir or set "
            "MEDIACRAWLER_HOME (see tools/mediacrawler/README.md)"
        )
    if not (args.mc_dir / "main.py").is_file():
        parser.error(f"main.py not found under {args.mc_dir}")

    cmd, mc_dir = build_cmd(args.mc_dir, args)
    if args.dry_run:
        print(" ".join(cmd))
        print(f"# output -> {args.out}")
        return 0

    print(f"[mc] platform={args.platform} keywords={args.keywords!r} "
          f"out={args.out}", file=sys.stderr)
    print("[mc] 仅限学习研究：小样本、低频率、只取公开内容；账号处置风险自负。",
          file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(cmd, cwd=mc_dir, timeout=args.timeout,
                              capture_output=True, text=True, check=False)
    except subprocess.TimeoutExpired:
        print(f"[mc] run exceeded {args.timeout}s; partial files kept in "
              f"{args.out}", file=sys.stderr)
        proc = None
    if proc is not None and proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-2000:]
        print(f"[mc] MediaCrawler failed (exit {proc.returncode}):\n{tail}",
              file=sys.stderr)
        return 2

    records, comments = collect_records(args.out, args.platform)
    if not records:
        print(f"[mc] no records parsed from {args.out}; check the browser "
              f"window for login or CAPTCHA prompts", file=sys.stderr)
        return 3
    digest = write_digest(args.out, args.platform, args, records, comments)
    print(f"records={len(records)} comments={len(comments)}")
    print(f"Digest: {digest}")
    print(f"Records: {args.out / 'records.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
