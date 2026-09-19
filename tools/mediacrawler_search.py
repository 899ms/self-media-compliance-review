#!/usr/bin/env python3
"""Wrap a local MediaCrawler checkout as the free live-search route.

Channel priority (2026-09): agent computer use > agent browser automation
> opencli > TikHub > this wrapper. MediaCrawler has been flagged by
platform anti-crawl in practice, so it is the LAST-resort channel: propose
it only when nothing above is available and the user accepts the account
risk.

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
terms. Account protection (same as social-account-doctor's mc adapter,
where comment-bearing detail runs are the norm — this repo needs comments
as evidence, so instead of turning them off every run is bounded):

- same-platform cooldown, default 30 min (failure backs off 10 min);
- one crawl process machine-wide (the lock guards the browser profile);
- per-run volume caps (keywords per run) — volume is what risk control
  actually watches over days, not a single run's pace;
- request pacing patched to a random 3-6 s jitter (fixed intervals are
  the classic bot fingerprint).

Account restriction is exactly what this repository documents — prefer a
throwaway account.

Design notes shared with social-account-doctor's mc adapter: default
install under gitignored ``vendor/``, patch ``ENABLE_CDP_MODE=False``
(CDP needs a manually-configured local Chrome; standard Playwright mode
keeps its login state in ``browser_data/``), and pin the upstream commit
the parser was verified against. Setup picks the fastest of official /
mirror download sources automatically (PyPI, Playwright chromium, GitHub
clone); ``--no-mirror`` or ``MC_NO_MIRROR=1`` disables that, and the
usual env vars (``PIP_INDEX_URL``, ``PLAYWRIGHT_DOWNLOAD_HOST``,
``MC_GIT_URL``) always win.
"""

from __future__ import annotations

import argparse
import concurrent.futures
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
import urllib.error
import urllib.request
from collections import deque
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
# 同平台两次抓取的最小间隔（秒）。用户账号登录抓取，抓太密会触发平台风控；
# 30 分钟对应「同账号同平台每天 ≤ 4-6 次」的安全预算，可用 MC_COOLDOWN_SECONDS
# 覆盖。本项目需要评论证据，单次 run 请求量比纯搜索大，频率上限不能更宽。
COOLDOWN_SECONDS = int(os.environ.get("MC_COOLDOWN_SECONDS", "1800"))
# 抓取失败的退避间隔（秒）。失败往往发生在风控敏感期（验证码 / 登录失效 /
# 被限流），立即重试只会继续加压，所以失败也写冷却标记，只是短一截。
FAILURE_COOLDOWN_SECONDS = int(
    os.environ.get("MC_FAILURE_COOLDOWN_SECONDS", "600"))
# 抓取锁超过此时长（秒）视为崩溃残留，可被新进程抢占
CRAWL_LOCK_STALE_SECONDS = 7200
# 单次 run 的关键词硬上限（超了直接拒绝，拆多次跑会被冷却拦住）。风控看的是
# 长期总量，不是单次频率；要更多数据就分天抓或改走 TikHub。
MAX_KEYWORDS_PER_RUN = int(os.environ.get("MC_MAX_KEYWORDS", "3"))


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


# 上游固定 2s 间隔是典型机器特征；快手 core 自带抖动，其余平台靠这个补丁
PACING_CORE_FILES = (
    "media_platform/xhs/core.py",
    "media_platform/douyin/core.py",
    "media_platform/kuaishou/core.py",
    "media_platform/bilibili/core.py",
)
_JITTER = "config.CRAWLER_MAX_SLEEP_SEC + random.uniform(0, config.CRAWLER_MAX_SLEEP_SEC)"


def _patch_jitter(text: str) -> str:
    # 确保有 import random（bilibili core 没有）；幂等
    if not re.search(r"^import random$", text, re.M):
        text = text.replace("import asyncio\n", "import asyncio\nimport random\n", 1)
    # 两种节奏形态都打上抖动：直接 sleep 和先赋值再 sleep
    text = text.replace("asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)",
                        f"asyncio.sleep({_JITTER})")
    text = text.replace("crawl_interval = config.CRAWLER_MAX_SLEEP_SEC",
                        f"crawl_interval = {_JITTER}")
    return text


def patch_pacing(mc_dir: Path) -> dict[str, bool]:
    """请求间隔随机化 + 基础间隔 2s→3s（抖动后 3-6s 随机停顿）。

    固定间隔是平台异常检测最经典的机器特征。幂等、非致命：某个文件找不到
    匹配模式就保持原样（跑起来仍是安全的固定间隔，只是少了随机性）。
    """
    result: dict[str, bool] = {}
    cfg = mc_dir / "config" / "base_config.py"
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8")
        patched = text.replace("CRAWLER_MAX_SLEEP_SEC = 2", "CRAWLER_MAX_SLEEP_SEC = 3")
        if patched != text:
            cfg.write_text(patched, encoding="utf-8")
        result["base_sleep_3s"] = "CRAWLER_MAX_SLEEP_SEC = 3" in cfg.read_text(encoding="utf-8")
    for rel in PACING_CORE_FILES:
        path = mc_dir / rel
        if not path.is_file():
            continue
        patched = _patch_jitter(path.read_text(encoding="utf-8"))
        if patched != path.read_text(encoding="utf-8"):
            path.write_text(patched, encoding="utf-8")
        result[rel.split("/")[1]] = _JITTER in path.read_text(encoding="utf-8")
    return result


def pacing_patched(mc_dir: Path) -> bool:
    """抖动补丁是否已应用（任一平台 core 带抖动即视为已打）。"""
    return any(
        _JITTER in (mc_dir / rel).read_text(encoding="utf-8")
        for rel in PACING_CORE_FILES if (mc_dir / rel).is_file()
    )


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
        info["pacing_patched"] = pacing_patched(mc_dir)
        info["ok"] = bool(info["config_patched"])
    return info


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, timeout=600, check=False)


# ---------------------------------------------------------------------------
# setup download-source selection: 国内裸连 GitHub/PyPI/Playwright CDN 常常只有
# 几十 KB/s，镜像源能快一到两个数量级。所有选择都可被用户环境变量覆盖。
# ---------------------------------------------------------------------------

PIP_INDEX_CANDIDATES: list[tuple[str, str]] = [
    ("官方 PyPI", "https://pypi.org/simple"),
    ("清华 PyPI 镜像", "https://pypi.tuna.tsinghua.edu.cn/simple"),
    ("阿里 PyPI 镜像", "https://mirrors.aliyun.com/pypi/simple"),
]
PLAYWRIGHT_OFFICIAL_HOST = "https://cdn.playwright.dev"
PLAYWRIGHT_MIRROR_HOST = "https://registry.npmmirror.com/-/binary/playwright"
GIT_MIRROR_PREFIXES = [
    "https://gh-proxy.com/",
    "https://ghfast.top/",
]
LEAN_REQUIREMENTS = REPO_ROOT / "tools" / "mediacrawler" / "requirements-lean.txt"


def _no_mirror() -> bool:
    return os.environ.get("MC_NO_MIRROR") == "1"


def _probe_ms(url: str, timeout: float = 4.0) -> float | None:
    """HEAD 探测往返毫秒数；连不上返回 None。

    任何 HTTP 状态码（含 4xx）都算可达——比的是到源站链路的快慢，
    不是业务路径是否存在（cdn.playwright.dev 根路径就返回 400）。
    """
    started = time.time()
    try:
        req = urllib.request.Request(
            url, method="HEAD",
            headers={"User-Agent": "self-media-compliance-review"})
        urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError:
        pass
    except Exception:
        return None
    return round((time.time() - started) * 1000, 1)


def _pick_fastest(candidates: list[tuple[str, str]]) -> tuple[str, str, float | None]:
    """并发探测候选源，返回 (名字, URL, 最快耗时 ms)；全部不可达时耗时为 None。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        latencies = list(pool.map(lambda c: _probe_ms(c[1]), candidates))
    paired = [(ms if ms is not None else float("inf"), name, url)
              for (name, url), ms in zip(candidates, latencies)]
    ms, name, url = min(paired, key=lambda item: item[0])
    return name, url, (None if ms == float("inf") else ms)


def pip_index_args(log: Any = print) -> tuple[list[str], str]:
    """pip install 的额外参数；返回 (args, 源标签)。已设 PIP_INDEX_URL/PIP_INDEX 时尊重 pip 原生行为。"""
    if os.environ.get("PIP_INDEX_URL") or os.environ.get("PIP_INDEX"):
        log("[mc] 检测到 PIP_INDEX_URL/PIP_INDEX，pip 源以环境变量为准")
        return [], "env"
    if _no_mirror():
        return [], "direct"
    name, url, ms = _pick_fastest(PIP_INDEX_CANDIDATES)
    if ms is None:
        log("[mc] 所有 pip 源探测失败，回退 pip 默认源")
        return [], "default"
    log(f"[mc] pip 源: {name}（探测 {ms:.0f}ms，自动择优）")
    if url == PIP_INDEX_CANDIDATES[0][1]:
        return [], name
    return ["-i", url], name


def playwright_mirror_env(log: Any = print) -> dict[str, str]:
    """需要注入 PLAYWRIGHT_DOWNLOAD_HOST 时返回它，否则空 dict（走官方 CDN）。"""
    if os.environ.get("PLAYWRIGHT_DOWNLOAD_HOST"):
        log("[mc] 检测到 PLAYWRIGHT_DOWNLOAD_HOST，Chromium 下载源以环境变量为准")
        return {}
    if _no_mirror():
        return {}
    official = _probe_ms(PLAYWRIGHT_OFFICIAL_HOST)
    mirror = _probe_ms(PLAYWRIGHT_MIRROR_HOST)
    if mirror is not None and (official is None or mirror * 2 < official):
        log(f"[mc] Chromium 下载走 npmmirror 镜像（{mirror:.0f}ms vs 官方 "
            f"{'不可达' if official is None else f'{official:.0f}ms'}）")
        return {"PLAYWRIGHT_DOWNLOAD_HOST": PLAYWRIGHT_MIRROR_HOST}
    return {}


def clone_url_candidates(log: Any = print) -> list[tuple[str, str]]:
    """按尝试顺序返回 (URL, 标签)。MC_GIT_URL 一票优先；github 可达时直连优先、镜像垫后。"""
    env_url = os.environ.get("MC_GIT_URL")
    if env_url:
        log(f"[mc] 使用 MC_GIT_URL={env_url}")
        return [(env_url, "MC_GIT_URL")]
    direct = (MC_GIT_URL, "github 直连")
    if _no_mirror():
        return [direct]
    mirrors = [(prefix + MC_GIT_URL, f"gh 代理 {prefix}")
               for prefix in GIT_MIRROR_PREFIXES]
    if _probe_ms("https://github.com", timeout=5.0) is None:
        log("[mc] github.com 探测不可达，优先尝试 gh 代理镜像")
        return mirrors + [direct]
    return [direct] + mirrors


def _run_stream(cmd: list[str], log: Any = print, timeout: int = 1800,
                env: dict[str, str] | None = None,
                cwd: Path | None = None,
                tail_lines: int = 25) -> tuple[int | None, list[str]]:
    """跑长下载命令（pip / playwright install）：输出逐行转发到 stderr 日志，
    保持 stdout 纯 JSON 契约；返回 (returncode, 尾部输出) 供错误报告。超时杀进程组。"""
    started = time.time()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        env=env, cwd=cwd, start_new_session=True,
    )
    tail: deque[str] = deque(maxlen=tail_lines)
    done = threading.Event()

    def _pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                tail.append(line)
                log(f"    {line}")
        done.set()

    threading.Thread(target=_pump, daemon=True).start()
    deadline = started + timeout
    while not done.wait(timeout=1.0) and time.time() < deadline:
        pass
    if not done.is_set():
        log(f"[mc] 超过 {timeout}s，终止下载进程")
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
        done.wait(timeout=5)
    else:
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass
    log(f"[mc] 下载命令完成（{time.time() - started:.0f}s，exit {proc.returncode}）")
    return proc.returncode, list(tail)


def _pip_install(vpy: Path, req_file: Path, index_args: list[str],
                 log: Any = print) -> None:
    cmd = [str(vpy), "-m", "pip", "install", "--timeout", "60",
           "--disable-pip-version-check", *index_args, "-r", str(req_file)]
    rc, tail = _run_stream(cmd, log=log, timeout=1800)
    if rc != 0:
        raise SetupError(f"pip install 失败（{req_file.name}）: "
                         f"{' | '.join(tail[-3:])}")


def setup(mc_dir: Path, force: bool = False, no_mirror: bool = False,
          log: Any = print) -> dict:
    """Clone MediaCrawler, build a venv, install chromium, patch config.

    下载源自动择优（pip / Playwright chromium / git clone），``no_mirror``
    或环境变量 ``MC_NO_MIRROR=1`` 可整体禁用；用户已设
    PIP_INDEX_URL / PLAYWRIGHT_DOWNLOAD_HOST / MC_GIT_URL 时一律尊重。
    """
    vendor = mc_dir.parent
    vendor.mkdir(parents=True, exist_ok=True)
    if no_mirror:
        os.environ["MC_NO_MIRROR"] = "1"
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
        cloned_from = ""
        last_err = ""
        # github 直连重试 2 次、gh 代理镜像各试 1 次；github 探测不可达时镜像优先
        for url, label in clone_url_candidates(log):
            tries = 2 if url == MC_GIT_URL else 1
            for attempt in range(1, tries + 1):
                log(f"[mc] 克隆 MediaCrawler ← {label}（第 {attempt}/{tries} 次）")
                result = _git(["clone", "--depth", "1", url, str(mc_dir)])
                if result.returncode == 0:
                    cloned, cloned_from = True, label
                    break
                last_err = result.stderr.strip()[:300]
                if mc_dir.exists():
                    shutil.rmtree(mc_dir, ignore_errors=True)
                time.sleep(2 * attempt)
            if cloned:
                break
        if not cloned:
            raise SetupError(
                f"git clone 失败: {last_err}。可任选其一：设 MC_GIT_URL 指向"
                "可达的克隆地址；手动克隆后放到 vendor/MediaCrawler 再重跑"
                " --setup；或配置 HTTPS_PROXY 后重试")
        steps["clone"] = f"ok via {cloned_from}"
        actual = _git(["rev-parse", "HEAD"], cwd=mc_dir).stdout.strip()
        if actual != PINNED_COMMIT:
            pin = _git(["fetch", "--depth", "1", "origin", PINNED_COMMIT],
                       cwd=mc_dir)
            if pin.returncode == 0 and _git(
                    ["checkout", "--quiet", PINNED_COMMIT],
                    cwd=mc_dir).returncode == 0:
                steps["clone"] += f", pinned {PINNED_COMMIT[:12]}"
            else:
                steps["clone"] += " (pin failed, upstream may have moved)"
        else:
            steps["clone"] += f", pinned {PINNED_COMMIT[:12]}"

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

    # 精简 requirements 优先（本 wrapper 只用 search + jsonl 落盘），smoke
    # test 不过就回退上游全量安装，保证行为不比原来差
    index_args, index_name = pip_index_args(log)
    if LEAN_REQUIREMENTS.is_file():
        log(f"[mc] 安装精简依赖（{LEAN_REQUIREMENTS.name}，输出逐行转发在下方）")
        try:
            _pip_install(vpy, LEAN_REQUIREMENTS, index_args, log)
            smoke = subprocess.run(
                [str(vpy), "main.py", "--help"], cwd=mc_dir,
                capture_output=True, text=True, timeout=120, check=False)
            if smoke.returncode != 0:
                raise SetupError(
                    f"精简依赖自检失败: {smoke.stderr.strip()[:200]}")
            steps["pip"] = f"lean via {index_name}"
        except SetupError as exc:
            log(f"[mc] {exc}；回退上游全量 requirements.txt")
            _pip_install(vpy, mc_dir / "requirements.txt", index_args, log)
            steps["pip"] = f"full via {index_name} (lean fallback)"
    else:
        log("[mc] 安装 MediaCrawler 依赖（输出逐行转发在下方）")
        _pip_install(vpy, mc_dir / "requirements.txt", index_args, log)
        steps["pip"] = f"full via {index_name}"

    log("[mc] 安装 Playwright chromium（约 200MB，取决于网速需要几分钟）")
    pw_env = os.environ.copy()
    pw_env.update(playwright_mirror_env(log))
    rc, tail = _run_stream(
        [str(vpy), "-m", "playwright", "install", "chromium"],
        log=log, timeout=1800, env=pw_env)
    if rc != 0:
        raise SetupError(f"playwright install 失败: {' | '.join(tail[-3:])}")
    steps["playwright"] = "chromium installed"

    steps["config_patch"] = ("applied" if patch_config(mc_dir)
                             else "already patched")
    steps["pacing_patch"] = patch_pacing(mc_dir)
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
# account protection: cooldown + failure backoff + single-instance lock +
# per-run volume caps (protect the logged-in account from rate-limiting)
# ---------------------------------------------------------------------------

class CooldownError(Exception):
    """Same-platform crawl requested inside the cooldown window."""


class VolumeError(Exception):
    """One run requests more keywords than the per-run cap allows."""


def _cooldown_marker(platform: str) -> Path:
    return vendor_data_dir() / f".last-run-{platform}"


def _cooldown_expiry(platform: str) -> float | None:
    """读冷却标记里存的「到期时间戳」（epoch 秒）；无标记 / 损坏返回 None。"""
    marker = _cooldown_marker(platform)
    if not marker.is_file():
        return None
    try:
        return float(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def check_cooldown(platform: str) -> None:
    """Reject a new crawl on the same platform inside the cooldown window."""
    if COOLDOWN_SECONDS <= 0:  # MC_COOLDOWN_SECONDS=0 当作显式关闭
        return
    expiry = _cooldown_expiry(platform)
    if expiry is None:
        return
    remaining = expiry - time.time()
    if remaining > 0:
        raise CooldownError(
            f"同平台（{platform}）抓取冷却中，还需等 {int(remaining // 60) + 1} 分钟"
            "——保护登录账号不触发风控。注意：抓取失败也会进入退避，连续失败通常"
            "是登录失效或风控信号（先 --status 检查登录态），不要拿 --force 硬闯。"
            "多个关键词合并进一次 --keywords；确有必要立即重抓时加 --force。")


def mark_cooldown(platform: str, seconds: int | None = None) -> None:
    """Stamp the cooldown expiry; 成功抓取用完整间隔，失败退避用短间隔。"""
    duration = COOLDOWN_SECONDS if seconds is None else seconds
    marker = _cooldown_marker(platform)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(time.time() + duration), encoding="utf-8")
    except OSError:
        pass


def _lock_file() -> Path:
    """全局单实例锁：同一时间全机只允许一个抓取进程。跨平台并行同样拒绝——
    虽然各平台风控相互独立，但单实例最简单也最稳：不会出现两个 chromium、
    也不会同时盯多个扫码窗口。"""
    return vendor_data_dir() / "crawl.lock"


def _acquire_crawl_lock() -> Path | None:
    """O_CREAT|O_EXCL 原子创建；崩溃残留超时的锁可抢占。
    返回锁文件路径（调用方负责 finally 释放），拿不到返回 None。"""
    data_dir = vendor_data_dir()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    lock = _lock_file()
    for _attempt in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                return None
            if age <= CRAWL_LOCK_STALE_SECONDS or _attempt:
                return None
            try:  # 崩溃残留的陈旧锁，清掉重试一次
                lock.unlink()
            except OSError:
                return None
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()} {time.time()}")
        return lock
    return None


def check_keyword_cap(keywords: str) -> None:
    """单次 run 体量硬上限。超了直接拒绝并说明出路（分天 / 走 TikHub），
    而不是靠自觉遵守文档里的数字。"""
    count = len([k for k in keywords.split(",") if k.strip()])
    if count > MAX_KEYWORDS_PER_RUN:
        raise VolumeError(
            f"单次 search 最多 {MAX_KEYWORDS_PER_RUN} 个关键词（当前 {count}）——"
            "体量是风控的首要信号，且本项目抓取常带评论、单次请求数更多。"
            "要更多数据分天抓或改走 TikHub；确有特殊需要时设 MC_MAX_KEYWORDS "
            "提高上限（自担风险）。")


# ---------------------------------------------------------------------------
# crawl execution
# ---------------------------------------------------------------------------

def build_cmd(mc_dir: Path, args: argparse.Namespace) -> list[str]:
    """Compose the MediaCrawler command line for one search run.

    本项目需要评论作证据，`--with-comments` 打开时仍显式钉住上游的保守
    默认值：单条内容一级评论 ≤ 10 条、二级评论关闭——逐层翻评论页会让
    单次 run 的请求数翻数倍，是最容易触发风控的行为。
    """
    platform = PLATFORMS[args.platform]
    max_comments = max(1, getattr(args, "max_comments", 10))
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
        "--get_sub_comment", "false",
        "--max_comments_count_singlenotes", str(max_comments),
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
                        help="also crawl first-level comments as evidence "
                             "(multiplies request volume; capped at "
                             "--max-comments per note)")
    parser.add_argument("--max-comments", type=int, default=10,
                        help="max first-level comments per note when "
                             "--with-comments is on (default 10)")
    parser.add_argument("--mc-dir", type=Path, default=None,
                        help="path to the MediaCrawler checkout "
                             "(default: vendor/MediaCrawler or "
                             "MEDIACRAWLER_HOME)")
    parser.add_argument("--out", type=Path, default=None,
                        help="output directory (default: gitignored local/)")
    parser.add_argument("--timeout", type=int, default=900,
                        help="run timeout in seconds (default 900)")
    parser.add_argument("--force", action="store_true",
                        help="skip the same-platform cooldown window "
                             "(still respects the single-instance lock)")
    parser.add_argument("--no-mirror", action="store_true",
                        help="disable setup mirror auto-selection "
                             "(same as MC_NO_MIRROR=1)")
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
            result = setup(mc_dir, force=args.force, no_mirror=args.no_mirror)
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

    try:
        check_keyword_cap(args.keywords)
    except VolumeError as exc:
        print(f"[mc] {exc}", file=sys.stderr)
        return 4

    # 全机单实例锁（--force 也不绕过：锁保护的是浏览器 profile，不是频率）
    lock = _acquire_crawl_lock()
    if lock is None:
        print(f"[mc] 已有另一个抓取进程在跑（全机单实例锁，跨平台也算并行）——"
              "并行会抢浏览器登录 profile、可能损坏登录态。等它跑完再试；"
              f"确认是残留锁时删除 {_lock_file()} 后重试。", file=sys.stderr)
        return 4
    try:
        if not args.force:
            try:
                check_cooldown(args.platform)
            except CooldownError as exc:
                print(f"[mc] {exc}", file=sys.stderr)
                return 4
        if not pacing_patched(mc_dir):
            print("[mc] 警告：请求节奏未打抖动补丁（固定间隔是典型机器特征），"
                  "建议重跑 --setup 应用补丁", file=sys.stderr)

        print(f"[mc] platform={args.platform} keywords={args.keywords!r} "
              f"out={args.out}", file=sys.stderr)
        print("[mc] 仅限学习研究：小样本、低频率、只取公开内容；账号处置风险自负。",
              file=sys.stderr)
        args.out.mkdir(parents=True, exist_ok=True)
        cmd = build_cmd(mc_dir, args)
        returncode, timed_out = run_crawl(cmd, mc_dir, args.timeout)
        if returncode not in (0, None) and not timed_out:
            print(f"[mc] MediaCrawler failed (exit {returncode})", file=sys.stderr)
            # 失败退避：浏览器已拉起、请求已发出，即使没抓到数据也要冷却一截，
            # 防止在风控敏感期零间隔循环重试
            mark_cooldown(args.platform, seconds=FAILURE_COOLDOWN_SECONDS)
            return 2

        records, comments = collect_records(args.out, args.platform)
        if not records:
            print(f"[mc] no records parsed from {args.out}; 常见原因：浏览器弹出后"
                  "没有完成扫码登录 / 触发风控 / 关键词无结果", file=sys.stderr)
            mark_cooldown(args.platform, seconds=FAILURE_COOLDOWN_SECONDS)
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
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
