import json

from tools.mediacrawler_search import (
    PLATFORMS,
    build_cmd,
    collect_records,
    default_out,
    discover,
    load_rows,
    main,
    normalize_row,
)


def test_platform_aliases_map_to_mediacrawler_codes():
    assert PLATFORMS["xiaohongshu"] == "xhs"
    assert PLATFORMS["douyin"] == "dy"
    assert PLATFORMS["kuaishou"] == "ks"
    assert PLATFORMS["bilibili"] == "bili"
    assert PLATFORMS["xhs"] == "xhs"


def test_normalize_row_maps_xhs_note_fields():
    row = {
        "note_id": "661f8b0c000000001e022222",
        "type": "video",
        "title": "被限流了怎么办",
        "desc": "申诉复盘",
        "time": 1726272000000,
        "nickname": "某创作者",
        "liked_count": "1234",
        "comment_count": 42,
        "note_url": "https://www.xiaohongshu.com/explore/661f8b0c",
        "source_keyword": "小红书 限流 申诉",
    }
    rec = normalize_row(row, "xhs")
    assert rec["id"] == "661f8b0c000000001e022222"
    assert rec["title"] == "被限流了怎么办"
    assert rec["comments"] == 42
    assert rec["likes"] == 1234
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


def test_normalize_row_returns_none_without_id():
    assert normalize_row({"title": "no id"}, "xhs") is None


def test_normalize_row_keeps_comment_id_and_links_to_note():
    row = {"comment_id": "c9", "note_id": "n1", "content": "同款经历",
           "nickname": "路人"}
    rec = normalize_row(row, "xhs")
    assert rec["id"] == "c9"
    assert rec["title"] == "同款经历"
    assert rec["url"].endswith("/n1")


def test_load_rows_supports_jsonl_and_json_array(tmp_path):
    jsonl = tmp_path / "search_contents_2026-09-16.jsonl"
    jsonl.write_text(
        '{"note_id": "a", "title": "t1"}\n\n{"note_id": "b", "title": "t2"}\n',
        encoding="utf-8",
    )
    js = tmp_path / "comments_2026-09-16.json"
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


def _mc_dir(tmp_path):
    mc = tmp_path / "MediaCrawler"
    mc.mkdir()
    (mc / "main.py").write_text("# placeholder\n")
    return mc


def test_build_cmd_prefers_uv_and_passes_output_dir(tmp_path, monkeypatch):
    import argparse

    monkeypatch.setattr(
        "shutil.which", lambda name: "/fake/uv" if name == "uv" else None
    )
    mc = _mc_dir(tmp_path)
    (mc / "uv.lock").write_text("")
    args = argparse.Namespace(
        platform="xiaohongshu", keywords="限流 申诉, 封号", max_notes=20,
        login="qrcode", out=tmp_path / "out", with_comments=False,
        headless=False,
    )
    cmd, _ = build_cmd(mc, args)
    assert cmd[0] == "/fake/uv"
    assert "--platform" in cmd and cmd[cmd.index("--platform") + 1] == "xhs"
    assert cmd[cmd.index("--get_comment") + 1] == "false"
    assert cmd[cmd.index("--save_data_option") + 1] == "jsonl"


def test_dry_run_prints_command_without_browser(tmp_path, capsys):
    rc = main([
        "--platform", "xiaohongshu",
        "--keywords", "小红书 限流",
        "--mc-dir", str(_mc_dir(tmp_path)),
        "--out", str(tmp_path / "out"),
        "--dry-run",
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "--platform xhs" in captured.out
    assert "--keywords" in captured.out


def test_main_requires_mediacrawler_checkout(tmp_path, capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main([
            "--platform", "xhs",
            "--keywords", "限流",
            "--mc-dir", str(tmp_path / "missing"),
        ])
    assert exc.value.code == 2


def test_default_out_lives_under_gitignored_local():
    out = default_out("xhs")
    assert "local" in out.parts
    assert "mc_output" in out.parts
