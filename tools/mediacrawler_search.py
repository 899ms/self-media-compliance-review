#!/usr/bin/env python3
"""Wrap a local MediaCrawler checkout as the free live-search route.

TikHub (`tools/tikhub/`) is a paid REST adapter. This wrapper is the
no-cost alternative: the user's own platform account logs in once in a
real browser, then keyword searches run locally and normalize into the
record shape used by this project
(`{"id", "title", "nick", "comments", "likes", "date", "url", "platform",
"keyword"}`).

MediaCrawler is NOT bundled (its license forbids commercial use and
redistribution terms differ from this repo). `--setup` installs it
automatically:

    python tools/mediacrawler_search.py --setup          # clone + venv +
                                                         # chromium + config
    python tools/mediacrawler_search.py --status         # readiness JSON

Then run searches (first run opens a browser for QR login; the session is
reused afterwards):

    python tools/mediacrawler_search.py --platform xiaohongshu \
        --keywords "小红书 限流 申诉,小红书 封号 经验" --max-notes 20

Outputs land in a gitignored directory (default
``local/mc_output/<platform>-<timestamp>/``): raw JSON written by
MediaCrawler plus normalized ``records.json`` and a ``digest.md``. Never
commit them, the account cookies, or the MediaCrawler browser data.

Compliance: use your own account, small samples, low frequency, public
content only, for learning and research. MediaCrawler ships a
non-commercial learning license; respect it and the target platforms'
terms. Runs of the same platform are rate-limited by a cooldown to
protect the logged-in account (`--force` overrides). Account restriction
is exactly what this repository documents — prefer a throwaway account.

Design notes shared with social-account-doctor's mc adapter: default
install under gitignored ``vendor/``, patch ``ENABLE_CDP_MODE=False``
(CDP needs a manually-configured local Chrome; standard Playwright mode
keeps its login state in ``browser_data/``), and pin the upstream commit
the parser was verified against.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
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
NODE_REQUIRED = {"dy", "zhihu"}  # signing needs local Node.js >= 16

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

# ---------------------------------------------------------------------------
# MediaCrawler install layout (under gitignored vendor/, like the
# social-account-doctor adapter; MEDIACRAWLER_HOME / --mc-dir override)
# ---------------------------------------------------------------------------
MC_GIT_URL = "https://github.com/NanmiCoder/MediaCrawler.git"
# Upstream commit the output parsing below was verified against; setup
# prefers it, and falls back to the default branch if the fetch fails.
PINNED_COMMIT = "60e66f2a925816960bbd44af5d6c9b8385d79335"
COOLDOWN_SECONDS = int(os.environ.get("MC_COOLDOWN_SECONDS", "300"))


def default_vendor_dir() -> Path:
    return REPO_ROOT / "vendor"


def resolve_mc_dir(cli_value: Path | None) -> Path:
    if cli_value:
        return cli_value
    env = os.environ.get("MEDIACRAWLER_HOME", "")
    if env:
        return Path(env)
    return default_vendor_dir() / "MediaCrawler"


def vendor_data_dir() -> Path:
    return default_vendor_dir() / "mc-data"


def venv_python(mc_dir: Path) -> Path:
    venv = mc_dir.parent / "mc-venv"
    suffix = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return venv / suffix


# ---------------------------------------------------------------------------
# record normalization
# ---------------------------------------------------------------------------

def _first(row: dict, keys: Iterable[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", 0, "0"):
            return value
    return None


def _as_int(value: Any) -> int | None:
    """Parse counts; platforms emit '10万+', '9.3万', '1.2亿', '1,234'."""
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text.isdigit():
        return int(text)
    match = re.fullmatch(r"([\d.]+)\s*(万|w|亿)?\+?", text, re.IGNORECASE)
    if match:
        number = float(match.group(1))
        unit = match.group(2)
        if unit:
            number *= 100_000_000 if unit.lower() == "亿" else 10_000
        return int(number)
    return None


def _as_date(value: Any) -> str | None:
    """MediaCrawler stores unix seconds or milliseconds depending on platform."""
    ts = _as_int(value)
    if ts is None or ts <= 0:
        return None
    if ts > 10_000_000_000:  # milliseconds
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


# ---------------------------------------------------------------------------
# setup / status
# ---------------------------------------------------------------------------

class SetupError(Exception):
    """Raised when the MediaCrawler install cannot be completed."""


def _python_search_paths() -> list[Path]:
    home = Path.home()
    roots = [
        home / "opt" / "miniconda3" / "bin",
        home / "opt" / "anaconda3" / "bin",
        home / "miniconda3" / "bin",
        home / "anaconda3" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ]
    out: list[Path] = []
    for root in roots:
        if root.is_dir():
            out.extend(sorted(root.glob("python3.*")))
            out.append(root / "python3")
    return out


def find_python() -> Path | None:
    """Find a Python >= 3.10 for the dedicated venv (MediaCrawler targets 3.11)."""
    candidates: list[Path] = []
    env_bin = os.environ.get("MC_PYTHON")
    if env_bin:
        candidates.append(Path(env_bin))
    candidates.append(Path(sys.executable))
    for name in ("python3.12", "python3.11", "python3.13", "python3.10",
                 "python3"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    candidates.extend(_python_search_paths())
    seen: set[str] = set()
    for py in candidates:
        key = str(py)
        if key in seen or not py.is_file():
            continue
        seen.add(key)
        try:
            out = subprocess.run(
                [key, "-c", "import sys; print(sys.version_info[:2])"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            if out.returncode != 0:
                continue
            major, minor = json.loads(
                out.stdout.strip().replace("(", "[").replace(")", "]"))
            if (major, minor) >= (3, 10):
                return py
        except (subprocess.TimeoutExpired, ValueError, OSError):
            continue
    return None


def patch_config(mc_dir: Path) -> bool:
    """Disable CDP mode so runs use the bundled Playwright chromium.

    CDP needs a manually-configured local Chrome (remote debugging) and is
    uncontrollable from automation; standard Playwright mode keeps the
    login state in browser_data/ for reuse. Idempotent.
    """
    path = mc_dir / "config" / "base_config.py"
    if not path.is_file():
        raise SetupError(f"config not found: {path}")
    text = path.read_text(encoding="utf-8")
    patched = text.replace("ENABLE_CDP_MODE = True", "ENABLE_CDP_MODE = False")
    if patched != text:
        path.write_text(patched, encoding="utf-8")
        return True
    return False


def login_state_platforms(mc_dir: Path) -> list[str]:
    """Platforms that already have a saved login (browser_data profile dir)."""
    browser_data = mc_dir / "browser_data"
    if not browser_data.is_dir():
        return []
    states = []
    for mc_plat in ("xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"):
        if any(browser_data.glob(f"{mc_plat}_user_data_dir*")):
            states.append(mc_plat)
    return states


def status(mc_dir: Path) -> dict:
    vpy = venv_python(mc_dir)
    node = shutil.which("node")
    cloned = (mc_dir / "main.py").is_file()
    info: dict[str, Any] = {
        "ok": False,
        "mediacrawler_dir": str(mc_dir),
        "cloned": cloned,
        "venv_ready": vpy.is_file(),
        "login_state_platforms": login_state_platforms(mc_dir),
        "node_found": node is not None,
        "platforms": dict(sorted({v: k for k, v in PLATFORMS.items()
                                  }.items())),
        "unsupported_platforms": {
            "wechat-channels": "视频号不支持 MediaCrawler；用 TikHub 或本地视频",
        },
    }
    version_file = mc_dir.parent / "mc-version.txt"
    if version_file.is_file():
        try:
            info["version"] = json.loads(
                version_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    if cloned and vpy.is_file():
        cfg = mc_dir / "config" / "base_config.py"
        info["config_patched"] = (
            cfg.is_file()
            and "ENABLE_CDP_MODE = False" in cfg.read_text(encoding="utf-8")
        )
        info["ok"] = bool(info["config_patched"])
    return info


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, timeout=600, check=False)


def setup(mc_dir: Path, force: bool = False,
          log: Any = print) -> dict:
    """Clone MediaCrawler, build a venv, install chromium, patch config."""
    vendor = mc_dir.parent
    vendor.mkdir(parents=True, exist_ok=True)
    steps: dict[str, Any] = {}

    py = find_python()
    if py is None:
        raise SetupError(
            "需要 Python >= 3.10 创建 MediaCrawler 虚拟环境；"
            "用 MC_PYTHON 指定解释器后重试")
    steps["python"] = str(py)

    if (mc_dir / "main.py").is_file() and not force:
        steps["clone"] = "skipped (already cloned)"
    else:
        if mc_dir.exists():
            shutil.rmtree(mc_dir)
        cloned = False
        last_err = ""
        for attempt in range(1, 4):
            log(f"[mc] 克隆 MediaCrawler → {mc_dir}（第 {attempt}/3 次）")
            result = _git(["clone", "--depth", "1", MC_GIT_URL, str(mc_dir)])
            if result.returncode == 0:
                cloned = True
                break
            last_err = result.stderr.strip()[:300]
            if mc_dir.exists():
                shutil.rmtree(mc_dir, ignore_errors=True)
            time.sleep(2 * attempt)
        if not cloned:
            raise SetupError(
                f"git clone 失败（重试 3 次）: {last_err}。检查到 github.com 的"
                "网络；或手动克隆后放到该目录再重跑 --setup")
        actual = _git(["rev-parse", "HEAD"], cwd=mc_dir).stdout.strip()
        if actual != PINNED_COMMIT:
            pin = _git(["fetch", "--depth", "1", "origin", PINNED_COMMIT],
                       cwd=mc_dir)
            if pin.returncode == 0 and _git(
                    ["checkout", "--quiet", PINNED_COMMIT],
                    cwd=mc_dir).returncode == 0:
                steps["clone"] = f"pinned {PINNED_COMMIT[:12]}"
            else:
                steps["clone"] = "default branch (pin failed, upstream moved)"
        else:
            steps["clone"] = f"pinned {PINNED_COMMIT[:12]}"

    vpy = venv_python(mc_dir)
    if vpy.is_file() and not force:
        steps["venv"] = "skipped (already exists)"
    else:
        log(f"[mc] 创建虚拟环境 → {vpy.parent}")
        result = subprocess.run([str(py), "-m", "venv", str(vpy.parent)],
                                capture_output=True, text=True, timeout=300,
                                check=False)
        if result.returncode != 0:
            raise SetupError(f"venv 创建失败: {result.stderr.strip()[:300]}")
        steps["venv"] = "created"

    log("[mc] 安装 MediaCrawler 依赖（首次较慢，几分钟）")
    result = subprocess.run(
        [str(vpy), "-m", "pip", "install", "--timeout", "120",
         "-r", str(mc_dir / "requirements.txt")],
        capture_output=True, text=True, timeout=1800, check=False)
    if result.returncode != 0:
        raise SetupError(f"pip install 失败: {result.stderr.strip()[-500:]}")
    steps["pip"] = "installed"

    log("[mc] 安装 Playwright chromium")
    result = subprocess.run([str(vpy), "-m", "playwright", "install",
                             "chromium"], capture_output=True, text=True,
                            timeout=1200, check=False)
    if result.returncode != 0:
        raise SetupError(
            f"playwright install 失败: {result.stderr.strip()[-300:]}")
    steps["playwright"] = "chromium installed"

    steps["config_patch"] = ("applied" if patch_config(mc_dir)
                             else "already patched")
    (mc_dir.parent / "mc-version.txt").write_text(json.dumps({
        "pinned_commit": PINNED_COMMIT,
        "actual_commit": _git(["rev-parse", "HEAD"],
                              cwd=mc_dir).stdout.strip(),
        "setup_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    result = subprocess.run([str(vpy), "main.py", "--help"], cwd=mc_dir,
                            capture_output=True, text=True, timeout=120,
                            check=False)
    if result.returncode != 0:
        raise SetupError(
            f"main.py --help 自检失败: {result.stderr.strip()[:300]}")
    steps["smoke_test"] = "main.py --help OK"

    return {"ok": True, "steps": steps, "status": status(mc_dir)}


# ---------------------------------------------------------------------------
# cooldown (protect the logged-in account from rate-limiting)
# ---------------------------------------------------------------------------

class CooldownError(Exception):
    """Same-platform crawl requested inside the cooldown window."""


def _cooldown_marker(platform: str) -> Path:
    return vendor_data_dir() / f".last-run-{platform}"


def check_cooldown(platform: str, seconds: int = COOLDOWN_SECONDS) -> None:
    marker = _cooldown_marker(platform)
    if not marker.is_file() or seconds <= 0:
        return
    try:
        last = float(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    elapsed = time.time() - last
    if elapsed < seconds:
        raise CooldownError(
            f"同平台（{platform}）两次抓取需间隔 {seconds // 60} 分钟"
            f"（上次结束于 {int(elapsed // 60)} 分钟前）——保护登录账号不触发"
            "风控。多个关键词合并进一次 --keywords；确有必要立即重抓时加 --force。")


def mark_cooldown(platform: str) -> None:
    marker = _cooldown_marker(platform)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# crawl execution
# ---------------------------------------------------------------------------

def build_cmd(mc_dir: Path, args: argparse.Namespace) -> list[str]:
    """Compose the MediaCrawler command line for one search run."""
    platform = PLATFORMS[args.platform]
    return [
        str(venv_python(mc_dir)), "main.py",
        "--platform", platform,
        "--lt", args.login,
        "--type", "search",
        "--keywords", args.keywords,
        "--crawler_max_notes_count", str(args.max_notes),
        "--save_data_option", "jsonl",
        "--save_data_path", str(args.out),
        "--get_comment", "true" if args.with_comments else "false",
        "--max_concurrency_num", "1",
    ]


def run_crawl(cmd: list[str], mc_dir: Path, timeout: int,
              log: Any = print) -> tuple[int | None, bool]:
    """Run in the MediaCrawler venv; pump logs, kill the process group on
    timeout so Playwright's chromium dies too. Returns (returncode, timed_out).
    """
    log("[mc] 启动 MediaCrawler（首次运行会弹出浏览器，请在窗口里扫码登录；"
        "登录态保存后免扫码）")
    proc = subprocess.Popen(
        cmd, cwd=mc_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        start_new_session=True,
    )

    def _pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log(f"[MediaCrawler] {line}")

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()
    deadline = time.time() + timeout
    while pump.is_alive() and time.time() < deadline:
        pump.join(timeout=1.0)
    timed_out = pump.is_alive()
    if timed_out:
        log(f"[mc] 超过 {timeout}s，终止爬取（已抓到的数据仍会解析）")
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait(timeout=30)
        pump.join(timeout=5)
        return proc.returncode, True
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        return proc.returncode, True
    return proc.returncode, False


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

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
            "(免费路线, non-commercial learning use only). 昵称为平台脱敏值，"
            "不要写进对外报告。\n"
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


def write_bridge_records(records: list[dict], platform: str,
                         repo_root: Path | None = None) -> Path | None:
    """Mirror a run's records into local/records-mc-<date>.json.

    The maintainer's local pipeline (``local/collect.py`` dedup →
    ``triage_new_items.sh`` → ``references/cases/``) scans these files, so
    on-demand MediaCrawler runs feed the same knowledge-deposition loop as
    the scheduled TikHub crawls; seen_ids.txt keeps repeated scans
    idempotent. Returns the bridge path, or None outside the repo layout.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    local_dir = root / "local"
    if not local_dir.is_dir():
        return None
    today = (datetime.datetime.now(datetime.timezone.utc).astimezone()
             .date().isoformat())
    path = local_dir / f"records-mc-{today}.json"
    merged: dict[str, dict] = {}
    if path.is_file():
        try:
            for row in json.loads(path.read_text(encoding="utf-8")):
                if isinstance(row, dict) and row.get("id"):
                    merged[str(row["id"])] = row
        except (OSError, json.JSONDecodeError):
            pass
    for rec in records:
        row = dict(rec)
        row.setdefault("src", platform)
        merged[str(row["id"])] = row
    path.write_text(
        json.dumps(list(merged.values()), ensure_ascii=False, indent=0),
        encoding="utf-8",
    )
    return path


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
        epilog="MediaCrawler setup is automated: run with --setup first.",
    )
    parser.add_argument("--platform", choices=sorted(set(PLATFORMS)),
                        help="xiaohongshu/xhs, douyin/dy, kuaishou/ks, "
                             "bilibili/bili, weibo/wb, tieba, zhihu")
    parser.add_argument("--keywords",
                        help="comma-separated search keywords")
    parser.add_argument("--max-notes", type=int, default=20,
                        help="max notes per run (default 20; keep it small)")
    parser.add_argument("--login", default="qrcode",
                        choices=("qrcode", "phone", "cookie"),
                        help="first-run login type (session is cached)")
    parser.add_argument("--with-comments", action="store_true",
                        help="also crawl first-level comments (slower)")
    parser.add_argument("--mc-dir", type=Path, default=None,
                        help="path to the MediaCrawler checkout "
                             "(default: vendor/MediaCrawler or "
                             "MEDIACRAWLER_HOME)")
    parser.add_argument("--out", type=Path, default=None,
                        help="output directory (default: gitignored local/)")
    parser.add_argument("--timeout", type=int, default=900,
                        help="run timeout in seconds (default 900)")
    parser.add_argument("--force", action="store_true",
                        help="skip the same-platform cooldown window")
    parser.add_argument("--setup", action="store_true",
                        help="install MediaCrawler under vendor/ "
                             "(clone + venv + chromium + config patch)")
    parser.add_argument("--status", action="store_true",
                        help="print install/login readiness as JSON")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the MediaCrawler command and exit")
    args = parser.parse_args(argv)

    mc_dir = resolve_mc_dir(args.mc_dir)

    if args.setup:
        try:
            result = setup(mc_dir, force=args.force)
        except SetupError as exc:
            print(json.dumps({"ok": False, "error": str(exc)},
                             ensure_ascii=False))
            return 2
        print(json.dumps(result, ensure_ascii=False))
        print("[mc] 安装完成。下一步：用 --platform <平台> --keywords <词> "
              "做一次小样本搜索，并在弹出的浏览器里扫码登录。", file=sys.stderr)
        return 0

    if args.status:
        print(json.dumps(status(mc_dir), ensure_ascii=False))
        return 0

    if not args.platform or not args.keywords:
        parser.error("--platform 和 --keywords 是必需的（或使用 --setup/--status）")
    if args.platform not in PLATFORMS:
        parser.error(f"unsupported platform: {args.platform}")
    args.platform = PLATFORMS.get(args.platform, args.platform)
    args.out = args.out or default_out(args.platform)

    if args.dry_run:
        cmd = list(build_cmd(mc_dir, args))
        cmd[0] = "<venv-python>" if not venv_python(mc_dir).is_file() else cmd[0]
        print(" ".join(cmd))
        print(f"# output -> {args.out}")
        return 0

    if not (mc_dir / "main.py").is_file() or not venv_python(mc_dir).is_file():
        print("[mc] MediaCrawler 未安装；先运行: "
              "python tools/mediacrawler_search.py --setup",
              file=sys.stderr)
        return 2
    if args.platform in NODE_REQUIRED and shutil.which("node") is None:
        print(f"[mc] 警告: 平台 {args.platform} 需要本机 Node.js >= 16 做"
              "签名，未检测到 node，本次可能失败", file=sys.stderr)

    if not args.force:
        try:
            check_cooldown(args.platform)
        except CooldownError as exc:
            print(f"[mc] {exc}", file=sys.stderr)
            return 4

    print(f"[mc] platform={args.platform} keywords={args.keywords!r} "
          f"out={args.out}", file=sys.stderr)
    print("[mc] 仅限学习研究：小样本、低频率、只取公开内容；账号处置风险自负。",
          file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    cmd = build_cmd(mc_dir, args)
    returncode, timed_out = run_crawl(cmd, mc_dir, args.timeout)
    if returncode not in (0, None) and not timed_out:
        print(f"[mc] MediaCrawler failed (exit {returncode})", file=sys.stderr)
        return 2

    records, comments = collect_records(args.out, args.platform)
    if not records:
        print(f"[mc] no records parsed from {args.out}; 常见原因：浏览器弹出后"
              "没有完成扫码登录 / 触发风控 / 关键词无结果", file=sys.stderr)
        return 3
    if timed_out:
        print("[mc] 注意：本次因超时被终止，以上是部分结果", file=sys.stderr)
    mark_cooldown(args.platform)
    digest = write_digest(args.out, args.platform, args, records, comments)
    bridge = write_bridge_records(records, args.platform)
    print(f"records={len(records)} comments={len(comments)}")
    print(f"Digest: {digest}")
    print(f"Records: {args.out / 'records.json'}")
    if bridge:
        print(f"Bridge (沉淀管道输入): {bridge}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
