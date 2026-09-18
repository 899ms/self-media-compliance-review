import datetime
import json
import os
import time
from pathlib import Path

import pytest

from tools.mediacrawler_search import (
    FAILURE_COOLDOWN_SECONDS,
    PLATFORMS,
    CooldownError,
    VolumeError,
    _as_date,
    _as_int,
    _acquire_crawl_lock,
    _cooldown_expiry,
    _lock_file,
    build_cmd,
    check_cooldown,
    check_keyword_cap,
    clone_url_candidates,
    collect_records,
    default_out,
    discover,
    load_rows,
    main,
    mark_cooldown,
    normalize_row,
    patch_config,
    patch_pacing,
    pacing_patched,
    pip_index_args,
    playwright_mirror_env,
    status,
    write_bridge_records,
)

FIXTURE_DIR = Path("tests/fixtures/mc/xhs")


def test_platform_aliases_map_to_mediacrawler_codes():
    assert PLATFORMS["xiaohongshu"] == "xhs"
    assert PLATFORMS["douyin"] == "dy"
    assert PLATFORMS["kuaishou"] == "ks"
    assert PLATFORMS["bilibili"] == "bili"
    assert PLATFORMS["xhs"] == "xhs"


def test_as_int_parses_chinese_magnitude_counts():
    assert _as_int("1234") == 1234
    assert _as_int("1,234") == 1234
    assert _as_int("10万+") == 100_000
    assert _as_int("9.3万") == 93_000
    assert _as_int("1.2亿") == 120_000_000
    assert _as_int(89) == 89
    assert _as_int("n/a") is None
    assert _as_int(None) is None


def test_as_date_handles_seconds_and_milliseconds():
    assert _as_date(1758002400000) == "2025-09-16"
    assert _as_date(1758002400) == "2025-09-16"
    assert _as_date(0) is None
    assert _as_date("bad") is None


def test_normalize_row_maps_xhs_note_fields():
    row = {
        "note_id": "661f8b0c000000001e022222",
        "type": "video",
        "title": "被限流了怎么办",
        "desc": "申诉复盘",
        "time": 1726272000000,
        "nickname": "某创作者",
        "liked_count": "1.2万",
        "comment_count": "10万+",
        "note_url": "https://www.xiaohongshu.com/explore/661f8b0c",
        "source_keyword": "小红书 限流 申诉",
    }
    rec = normalize_row(row, "xhs")
    assert rec["id"] == "661f8b0c000000001e022222"
    assert rec["title"] == "被限流了怎么办"
    assert rec["comments"] == 100_000
    assert rec["likes"] == 12_000
    assert rec["date"] is not None and rec["date"].startswith("2024-")
    assert rec["url"] == "https://www.xiaohongshu.com/explore/661f8b0c"
    assert rec["platform"] == "xhs"
    assert rec["keyword"] == "小红书 限流 申诉"


def test_normalize_row_builds_url_and_reads_desc_when_title_missing():
    row = {
        "aweme_id": "7400000000000000000",
        "desc": "抖音违规申诉经验",
        "create_time": 1726272000,
        "nickname": "抖音用户",
        "liked_count": "99",
        "comment_count": "7",
    }
    rec = normalize_row(row, "dy")
    assert rec["url"] == "https://www.douyin.com/video/7400000000000000000"
    assert rec["title"] == "抖音违规申诉经验"
    assert rec["date"] == "2024-09-14"


def test_normalize_row_keeps_comment_id_and_links_to_note():
    row = {"comment_id": "c9", "note_id": "n1", "content": "同款经历",
           "nickname": "路人"}
    rec = normalize_row(row, "xhs")
    assert rec["id"] == "c9"
    assert rec["title"] == "同款经历"
    assert rec["url"].endswith("/n1")


def test_normalize_row_returns_none_without_id():
    assert normalize_row({"title": "no id"}, "xhs") is None


def test_load_rows_supports_jsonl_and_json_array(tmp_path):
    jsonl = tmp_path / "search_contents_2026-09-16.jsonl"
    jsonl.write_text(
        '{"note_id": "a", "title": "t1"}\n\n{"note_id": "b", "title": "t2"}\n',
        encoding="utf-8",
    )
    js = tmp_path / "search_comments_2026-09-16.json"
    js.write_text(json.dumps([{"comment_id": "c1", "content": "x"}]),
                  encoding="utf-8")
    assert [r["note_id"] for r in load_rows(jsonl)] == ["a", "b"]
    assert [r["comment_id"] for r in load_rows(js)] == ["c1"]


def test_discover_splits_content_and_comment_files(tmp_path):
    # Real MediaCrawler layout: <out>/<platform>/jsonl/<type>_<item>_<date>.jsonl
    (tmp_path / "xhs" / "jsonl").mkdir(parents=True)
    (tmp_path / "xhs" / "jsonl" / "search_contents_2026-09-16.jsonl").write_text(
        '{"note_id": "a"}\n', encoding="utf-8"
    )
    (tmp_path / "xhs" / "jsonl" / "search_comments_2026-09-16.jsonl").write_text(
        '{"comment_id": "c"}\n', encoding="utf-8"
    )
    (tmp_path / "xhs" / "jsonl" / "unrelated.txt").write_text("skip")
    contents, comments = discover(tmp_path)
    assert len(contents) == 1 and len(comments) == 1


def test_collect_records_parses_real_mediacrawler_fixture():
    records, comments = collect_records(FIXTURE_DIR, "xhs")
    assert len(records) == 2
    top = records[0]
    assert top["id"] == "661f2b44000000001e021234"
    assert top["likes"] == 1234 and top["comments"] == 89
    assert top["keyword"] == "低卡便当"
    assert top["url"].startswith("https://www.xiaohongshu.com/explore/")
    # comment rows keep their own id and link back to the note
    assert {c["id"] for c in comments} == {"a_comment_1", "a_comment_2"}
    assert all(c["url"].endswith("661f2b44000000001e021234") for c in comments)


def test_collect_records_dedupes_and_sorts_by_comments(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "search_contents.jsonl").write_text(
        '{"note_id": "a", "title": "low", "comment_count": 1}\n'
        '{"note_id": "b", "title": "high", "comment_count": 30}\n'
        '{"note_id": "a", "title": "dup", "comment_count": 2}\n'
        '{"title": "no id"}\n',
        encoding="utf-8",
    )
    records, comments = collect_records(tmp_path / "out", "xhs")
    assert [r["id"] for r in records] == ["b", "a"]
    assert records[0]["title"] == "high"
    assert comments == []


def _fake_install(tmp_path, patched=False):
    mc = tmp_path / "vendor" / "MediaCrawler"
    (mc / "config").mkdir(parents=True)
    (mc / "main.py").write_text("# placeholder\n")
    cfg = mc / "config" / "base_config.py"
    cfg.write_text(
        "ENABLE_CDP_MODE = %s\n" % ("False" if patched else "True"),
        encoding="utf-8",
    )
    venv = tmp_path / "vendor" / "mc-venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("# placeholder\n")
    return mc


def test_patch_config_disables_cdp_idempotently(tmp_path):
    mc = tmp_path / "MediaCrawler"
    (mc / "config").mkdir(parents=True)
    cfg = mc / "config" / "base_config.py"
    cfg.write_text("HEADLESS = False\nENABLE_CDP_MODE = True\n",
                   encoding="utf-8")
    assert patch_config(mc) is True
    assert "ENABLE_CDP_MODE = False" in cfg.read_text(encoding="utf-8")
    assert patch_config(mc) is False  # second run changes nothing


def test_status_reports_install_readiness(tmp_path):
    mc = _fake_install(tmp_path)
    info = status(mc)
    assert info["ok"] is False  # not patched yet
    assert info["cloned"] is True and info["venv_ready"] is True
    assert "视频号" in info["unsupported_platforms"]["wechat-channels"]
    patch_config(mc)
    assert status(mc)["ok"] is True


def test_cooldown_blocks_same_platform_repeats(tmp_path, monkeypatch):
    from tools.mediacrawler_search import _cooldown_marker

    monkeypatch.setattr("tools.mediacrawler_search.vendor_data_dir",
                        lambda: tmp_path / "mc-data")
    check_cooldown("xhs")  # no marker yet -> pass
    mark_cooldown("xhs")
    try:
        check_cooldown("xhs")
        raise AssertionError("expected CooldownError")
    except CooldownError as exc:
        assert "冷却" in str(exc) and "--force" in str(exc)
    # an expired marker does not block
    marker = _cooldown_marker("xhs")
    marker.write_text(str(time.time() - 3600), encoding="utf-8")
    check_cooldown("xhs")


def test_protection_defaults_match_doctor_adapter(monkeypatch):
    """冷却/退避/体量默认值与 social-account-doctor 的 mc adapter 对齐。"""
    monkeypatch.delenv("MC_COOLDOWN_SECONDS", raising=False)
    monkeypatch.delenv("MC_FAILURE_COOLDOWN_SECONDS", raising=False)
    monkeypatch.delenv("MC_MAX_KEYWORDS", raising=False)
    import importlib.util
    source = Path(__file__).resolve().parents[1] / "tools" / "mediacrawler_search.py"
    spec = importlib.util.spec_from_file_location("mcs_fresh", source)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    assert fresh.COOLDOWN_SECONDS == 1800
    assert fresh.FAILURE_COOLDOWN_SECONDS == 600
    assert fresh.MAX_KEYWORDS_PER_RUN == 3
    assert fresh.CRAWL_LOCK_STALE_SECONDS == 7200


def test_failure_backoff_shorter_than_full_cooldown(tmp_path, monkeypatch):
    """失败退避 ~10 分钟，成功冷却 ~30 分钟；退避期内同样被拦。"""
    monkeypatch.setattr("tools.mediacrawler_search.vendor_data_dir",
                        lambda: tmp_path / "mc-data")
    mark_cooldown("xhs", seconds=FAILURE_COOLDOWN_SECONDS)
    expiry = _cooldown_expiry("xhs")
    assert expiry is not None
    assert 500 < expiry - time.time() < 700
    with pytest.raises(CooldownError):
        check_cooldown("xhs")
    mark_cooldown("dy")
    assert _cooldown_expiry("dy") - time.time() > 1700


def test_main_failure_marks_backoff_cooldown(tmp_path, monkeypatch):
    """run 失败（浏览器已拉起）也写失败退避，防止零间隔循环重试；锁被释放。"""
    monkeypatch.setattr("tools.mediacrawler_search.vendor_data_dir",
                        lambda: tmp_path / "mc-data")
    monkeypatch.setattr("tools.mediacrawler_search.run_crawl",
                        lambda cmd, mc_dir, timeout, log=print: (2, False))
    argv = [
        "--platform", "xhs", "--keywords", "限流",
        "--mc-dir", str(_fake_install(tmp_path)),
        "--out", str(tmp_path / "out"),
    ]
    assert main(argv) == 2
    expiry = _cooldown_expiry("xhs")
    assert expiry is not None and 500 < expiry - time.time() < 700
    assert not (tmp_path / "mc-data" / "crawl.lock").exists()
    assert main(argv) == 4  # 退避期内重跑被拦


def test_main_success_marks_full_cooldown(tmp_path, monkeypatch):
    """成功 run 写完整冷却（不是失败退避），锁释放，bridge 落盘。"""
    monkeypatch.setattr("tools.mediacrawler_search.vendor_data_dir",
                        lambda: tmp_path / "mc-data")
    monkeypatch.setattr("tools.mediacrawler_search.REPO_ROOT", tmp_path)
    monkeypatch.setattr("tools.mediacrawler_search.run_crawl",
                        lambda cmd, mc_dir, timeout, log=print: (0, False))
    (tmp_path / "local").mkdir()
    out = tmp_path / "out"
    plat_dir = out / "xhs" / "jsonl"
    plat_dir.mkdir(parents=True)
    (plat_dir / "search_contents_2026-09-18.jsonl").write_text(
        '{"note_id": "n1", "title": "t", "liked_count": "3"}\n',
        encoding="utf-8")
    assert main([
        "--platform", "xhs", "--keywords", "限流",
        "--mc-dir", str(_fake_install(tmp_path)),
        "--out", str(out),
    ]) == 0
    assert _cooldown_expiry("xhs") - time.time() > 1700
    assert not (tmp_path / "mc-data" / "crawl.lock").exists()
    today = datetime.datetime.now(datetime.timezone.utc).astimezone() \
        .date().isoformat()
    bridge = tmp_path / "local" / f"records-mc-{today}.json"
    assert [r["id"] for r in json.loads(bridge.read_text(encoding="utf-8"))] \
        == ["n1"]


def test_crawl_lock_rejects_concurrent_and_releases(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.mediacrawler_search.vendor_data_dir",
                        lambda: tmp_path / "mc-data")
    lock = _acquire_crawl_lock()
    assert lock is not None
    assert _acquire_crawl_lock() is None  # already held
    lock.unlink()
    assert _acquire_crawl_lock() is not None  # released -> re-acquirable


def test_crawl_lock_steals_stale_lock(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.mediacrawler_search.vendor_data_dir",
                        lambda: tmp_path / "mc-data")
    stale = _lock_file()
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("999999 123", encoding="utf-8")
    old = time.time() - 3 * 3600
    os.utime(stale, (old, old))
    assert _acquire_crawl_lock() is not None


def test_keyword_cap_rejects_bulk_runs(monkeypatch):
    monkeypatch.delenv("MC_MAX_KEYWORDS", raising=False)
    check_keyword_cap("词1,词2,词3")  # exactly at the cap -> pass
    with pytest.raises(VolumeError):
        check_keyword_cap("词1,词2,词3,词4")


def test_build_cmd_runs_venv_python_with_jsonl_output(tmp_path):
    import argparse

    mc = _fake_install(tmp_path)
    args = argparse.Namespace(
        platform="xiaohongshu", keywords="限流 申诉, 封号", max_notes=20,
        login="qrcode", out=tmp_path / "out", with_comments=False,
    )
    cmd = build_cmd(mc, args)
    assert cmd[0].endswith("mc-venv/bin/python")
    assert cmd[1] == "main.py"
    assert cmd[cmd.index("--platform") + 1] == "xhs"
    assert cmd[cmd.index("--get_comment") + 1] == "false"
    assert cmd[cmd.index("--save_data_option") + 1] == "jsonl"
    assert cmd[cmd.index("--max_concurrency_num") + 1] == "1"


def test_build_cmd_pins_conservative_comment_caps(tmp_path):
    """本项目要评论作证据：打开评论时一级评论 ≤10、二级评论关闭。"""
    import argparse

    mc = _fake_install(tmp_path)
    args = argparse.Namespace(
        platform="xhs", keywords="限流", max_notes=20, login="qrcode",
        out=tmp_path / "out", with_comments=True,
    )
    cmd = build_cmd(mc, args)
    assert cmd[cmd.index("--get_comment") + 1] == "true"
    assert cmd[cmd.index("--get_sub_comment") + 1] == "false"
    assert cmd[cmd.index("--max_comments_count_singlenotes") + 1] == "10"
    args.max_comments = 5
    cmd = build_cmd(mc, args)
    assert cmd[cmd.index("--max_comments_count_singlenotes") + 1] == "5"


def test_patch_pacing_adds_jitter_idempotently(tmp_path):
    mc = tmp_path / "MediaCrawler"
    (mc / "config").mkdir(parents=True)
    (mc / "media_platform" / "xhs").mkdir(parents=True)
    (mc / "config" / "base_config.py").write_text(
        "CRAWLER_MAX_SLEEP_SEC = 2\n", encoding="utf-8")
    core = mc / "media_platform" / "xhs" / "core.py"
    core.write_text(
        "import asyncio\n\nasync def pause():\n"
        "    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)\n",
        encoding="utf-8")
    result = patch_pacing(mc)
    assert result["base_sleep_3s"] is True
    assert result["xhs"] is True
    text = core.read_text(encoding="utf-8")
    assert "import random" in text
    assert "asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC + random.uniform" in text
    assert patch_pacing(mc) == result  # second run changes nothing
    assert pacing_patched(mc) is True
    assert pacing_patched(tmp_path / "empty") is False


# ---------------------------------------------------------------------------
# setup download-source selection (probes monkeypatched — no network)
# ---------------------------------------------------------------------------

def _clear_mirror_env(monkeypatch):
    for var in ("MC_NO_MIRROR", "PIP_INDEX_URL", "PIP_INDEX",
                "PLAYWRIGHT_DOWNLOAD_HOST", "MC_GIT_URL"):
        monkeypatch.delenv(var, raising=False)


def test_pip_index_picks_fastest_mirror(monkeypatch):
    _clear_mirror_env(monkeypatch)
    speeds = {
        "https://pypi.org/simple": 300.0,
        "https://pypi.tuna.tsinghua.edu.cn/simple": 60.0,
        "https://mirrors.aliyun.com/pypi/simple": 600.0,
    }
    monkeypatch.setattr("tools.mediacrawler_search._probe_ms",
                        lambda url, timeout=4.0: speeds[url])
    args, label = pip_index_args(log=lambda m: None)
    assert args == ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
    assert "清华" in label


def test_pip_index_keeps_official_when_fastest(monkeypatch):
    _clear_mirror_env(monkeypatch)
    monkeypatch.setattr("tools.mediacrawler_search._probe_ms",
                        lambda url, timeout=4.0: 50.0)
    args, label = pip_index_args(log=lambda m: None)
    assert args == []
    assert "官方" in label


def test_pip_index_env_and_no_mirror_override(monkeypatch):
    _clear_mirror_env(monkeypatch)
    monkeypatch.setattr("tools.mediacrawler_search._probe_ms",
                        lambda url, timeout=4.0: 50.0)
    monkeypatch.setenv("PIP_INDEX_URL", "https://example.com/simple")
    assert pip_index_args(log=lambda m: None) == ([], "env")
    monkeypatch.delenv("PIP_INDEX_URL")
    monkeypatch.setenv("MC_NO_MIRROR", "1")
    assert pip_index_args(log=lambda m: None) == ([], "direct")


def test_pip_index_falls_back_when_all_probes_fail(monkeypatch):
    _clear_mirror_env(monkeypatch)
    monkeypatch.setattr("tools.mediacrawler_search._probe_ms",
                        lambda url, timeout=4.0: None)
    assert pip_index_args(log=lambda m: None) == ([], "default")


def test_playwright_mirror_only_when_clearly_faster(monkeypatch):
    _clear_mirror_env(monkeypatch)
    mirror = "https://registry.npmmirror.com/-/binary/playwright"
    # mirror * 2 >= official -> stay on the official CDN
    monkeypatch.setattr(
        "tools.mediacrawler_search._probe_ms",
        lambda url, timeout=4.0: 500.0 if "npmmirror" in url else 200.0)
    assert playwright_mirror_env(log=lambda m: None) == {}
    monkeypatch.setattr(
        "tools.mediacrawler_search._probe_ms",
        lambda url, timeout=4.0: 50.0 if "npmmirror" in url else 400.0)
    assert playwright_mirror_env(log=lambda m: None) == {
        "PLAYWRIGHT_DOWNLOAD_HOST": mirror}


def test_clone_url_candidates_order(monkeypatch):
    _clear_mirror_env(monkeypatch)
    direct = "https://github.com/NanmiCoder/MediaCrawler.git"
    monkeypatch.setattr("tools.mediacrawler_search._probe_ms",
                        lambda url, timeout=5.0: 100.0)  # github reachable
    cands = clone_url_candidates(log=lambda m: None)
    assert cands[0] == (direct, "github 直连")
    assert len(cands) == 3
    monkeypatch.setattr("tools.mediacrawler_search._probe_ms",
                        lambda url, timeout=5.0: None)  # github unreachable
    cands = clone_url_candidates(log=lambda m: None)
    assert cands[0][0].startswith("https://gh-proxy.com/")
    assert cands[-1] == (direct, "github 直连")
    monkeypatch.setenv("MC_GIT_URL", "https://example.com/MediaCrawler.git")
    assert clone_url_candidates(log=lambda m: None) == [
        ("https://example.com/MediaCrawler.git", "MC_GIT_URL")]


def test_dry_run_prints_command_without_browser(tmp_path, capsys):
    rc = main([
        "--platform", "xiaohongshu",
        "--keywords", "小红书 限流",
        "--mc-dir", str(_fake_install(tmp_path)),
        "--out", str(tmp_path / "out"),
        "--dry-run",
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "--platform xhs" in captured.out
    assert "--keywords" in captured.out


def test_main_reports_missing_install(tmp_path, capsys):
    rc = main([
        "--platform", "xhs",
        "--keywords", "限流",
        "--mc-dir", str(tmp_path / "vendor" / "MediaCrawler"),
        "--out", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "--setup" in capsys.readouterr().err


def test_status_flag_prints_json(tmp_path, capsys):
    rc = main(["--status", "--mc-dir", str(_fake_install(tmp_path))])
    captured = capsys.readouterr()
    assert rc == 0
    assert json.loads(captured.out)["cloned"] is True


def test_default_out_lives_under_gitignored_local():
    out = default_out("xhs")
    assert "local" in out.parts
    assert "mc_output" in out.parts


def test_bridge_records_mirror_into_local_pipeline(tmp_path):
    (tmp_path / "local").mkdir()
    bridge = write_bridge_records(
        [{"id": "a1", "title": "t", "platform": "xhs"},
         {"id": "a2", "title": "t2", "platform": "xhs"}],
        "xhs", repo_root=tmp_path,
    )
    expected = tmp_path / "local" / (
        "records-mc-"
        + datetime.datetime.now(datetime.timezone.utc).astimezone()
        .date().isoformat() + ".json"
    )
    assert bridge == expected
    data = json.loads(expected.read_text(encoding="utf-8"))
    assert {r["id"] for r in data} == {"a1", "a2"}
    assert data[0]["src"] == "xhs"
    # a second same-day run merges by id instead of duplicating
    write_bridge_records(
        [{"id": "a2", "title": "t2b", "platform": "xhs"},
         {"id": "a3", "title": "t3", "platform": "xhs"}],
        "xhs", repo_root=tmp_path,
    )
    data = json.loads(expected.read_text(encoding="utf-8"))
    assert {r["id"] for r in data} == {"a1", "a2", "a3"}
    assert data[0]["title"] == "t"  # earlier run's row is preserved
    # outside a repo layout there is nothing to mirror into
    assert write_bridge_records([], "xhs",
                                repo_root=tmp_path / "nope") is None
