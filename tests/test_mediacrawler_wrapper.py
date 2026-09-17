import datetime
import json
import time
from pathlib import Path

from tools.mediacrawler_search import (
    PLATFORMS,
    CooldownError,
    _as_date,
    _as_int,
    build_cmd,
    check_cooldown,
    collect_records,
    default_out,
    discover,
    load_rows,
    main,
    mark_cooldown,
    normalize_row,
    patch_config,
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
        check_cooldown("xhs", seconds=300)
        raise AssertionError("expected CooldownError")
    except CooldownError as exc:
        assert "300" in str(exc) or "5" in str(exc)
    # an old marker does not block
    marker = _cooldown_marker("xhs")
    marker.write_text(str(time.time() - 3600), encoding="utf-8")
    check_cooldown("xhs", seconds=300)


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
