"""M6 交付层守门：报告导出（csv / md / docx）的口径、纪律与字节一致性。

这些门存在的理由：导出是**交付面**，用户拿到的就是这些文件，所以
"免责声明必在末尾""blocked 数值留空""措辞不许过强""夹具不进交付面""无时间戳"
必须在导出层自己把关，不能指望上游命令面已经拦干净。
"""

import io
import json
import os
import re
import zipfile

import pytest

from road_mqi_checker.errors import InputUnavailable, PrivacyViolation
from road_mqi_checker.report import disclaimer
from road_mqi_checker.report import exporters

BANNED = ("已确认", "已核实", "最终确定", "必定")

#: 一条"引擎已拒算"的清单行：字段全部按 result_payload 的形状给（导出层不自己算数）
def _suggestion(segment_id="S99-A1", year=2022, **overrides):
    row = {
        "segment_id": segment_id,
        "route_id": "S99",
        "year": year,
        "start_stake_m": 0,
        "status": "blocked",
        "blocked_reason": "系数 action_rule.maintenance_trigger 核对状态为 pending，未进入评定路径，应核实原文后再算",
        "scope_note": "",
        "pci": None,
        "mqi_partial": None,
        "rule_id": "",
        "clause": "",
        "condition_text": "",
        "action_class": None,
        "scale_band": None,
        "scale_band_value": None,
        "triggered_by": None,
        "rank_key": "",
        "coefficient_key": "action_rule.maintenance_trigger",
    }
    row.update(overrides)
    return row


def _pci(segment_id="S99-A1", year=2022, **overrides):
    row = {
        "segment_id": segment_id,
        "route_id": "S99",
        "year": year,
        "surface_type": "asphalt",
        "status": "blocked",
        "blocked_reason": "系数未核对，应核实",
        "scope_note": "",
        "pci": None,
        "grade": None,
        "deducted_total": None,
        "component_scores": {},
        "ruleset_id": "base-jtg5210-2018",
        "ruleset_version": "0.0.0-draft",
        "contributions": [],
    }
    row.update(overrides)
    return row


def _compare(segment_id="S99-A1", year_from=2022, year_to=2023, **overrides):
    row = {
        "segment_id": segment_id,
        "route_id": "S99",
        "year_from": year_from,
        "year_to": year_to,
        "status": "uncomparable",
        "delta": None,
        "deterioration_rate_per_year": None,
        "grade_from": None,
        "grade_to": None,
        "comparability_reason": "partition_shifted",
        "top_contributors": [],
        "length_overlap_m": None,
        "blocked_reason": "跨年划分不可比，不出变化率",
        "scope_note": "",
    }
    row.update(overrides)
    return row


def _rows(tmp_path=None, count=2):
    return exporters.plan_rows(
        [_suggestion(segment_id="S99-A%d" % i, year=2023) for i in range(1, count + 1)],
        pci_results=[_pci(segment_id="S99-A%d" % i, year=2023, pci=None, grade=None) for i in range(1, count + 1)],
        compare_results=[_compare(segment_id="S99-A%d" % i) for i in range(1, count + 1)],
        from_year=2022,
    )


def _out(tmp_path, name):
    return str(tmp_path / name)


def _read(path):
    with open(path, "rb") as handle:
        return handle.read()


def docx_text(path):
    """解包 docx 正文，把每个 `<w:t>` 文本还原成行，供与 md/csv 同一套断言。"""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    cells = re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", xml, re.S)
    unescaped = (
        lambda s: s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    )
    return [unescaped(cell) for cell in cells]


# ---------------------------------------------------------------- 格式与入参闸门

def test_formats_are_the_three_declared():
    assert exporters.FORMATS == ("csv", "md", "docx")


@pytest.mark.parametrize("fmt", exporters.FORMATS)
def test_plan_columns_are_the_export_header(fmt, tmp_path):
    path = _out(tmp_path, "plan." + fmt)
    result = exporters.export_priority_list(path, fmt, _rows())
    assert result["format"] == fmt and result["bytes"] > 0
    if fmt == "csv":
        lines = _read(path).decode("utf-8").splitlines()
        assert lines[0] == "养护对策优先序清单"  # 首行是文档标题（prose 行），表头紧随其后
        assert lines[1] == ",".join(exporters.PLAN_COLUMNS)
        assert len([line for line in lines if line == ",".join(exporters.PLAN_COLUMNS)]) == 1
    elif fmt == "md":
        assert "| rank | route_id |" in _read(path).decode("utf-8")
    else:
        assert docx_text(path).count("rank") == 1


@pytest.mark.parametrize("fmt", exporters.FORMATS)
def test_unknown_format_or_suffix_mismatch_is_refused(fmt, tmp_path):
    with pytest.raises(InputUnavailable):
        exporters.export_priority_list(_out(tmp_path, "plan.csv"), "rtf", _rows())
    with pytest.raises(InputUnavailable):
        exporters.export_priority_list(_out(tmp_path, "plan.txt"), fmt, _rows())


def test_empty_or_foreign_rows_are_refused(tmp_path):
    with pytest.raises(InputUnavailable):
        exporters.export_priority_list(_out(tmp_path, "plan.csv"), "csv", [])
    with pytest.raises(InputUnavailable):
        # 行必须来自 plan_rows()：少列就不许导出（防止交付面出现"半张表"）
        exporters.export_priority_list(_out(tmp_path, "plan.csv"), "csv", [{"segment_id": "S99-A1"}])


# ---------------------------------------------------------------- 免责声明与结构

@pytest.mark.parametrize("fmt", exporters.FORMATS)
def test_every_export_ends_with_the_fixed_disclaimer(fmt, tmp_path):
    path = _out(tmp_path, "plan." + fmt)
    exporters.export_priority_list(path, fmt, _rows())
    if fmt == "docx":
        lines = [line for line in docx_text(path) if line.strip()]
    else:
        lines = [line for line in _read(path).decode("utf-8").splitlines() if line.strip()]
    assert lines[-2] == disclaimer.DISCLAIMER
    assert lines[-1] == disclaimer.DATA_CLASS_NOTE


@pytest.mark.parametrize("fmt", exporters.FORMATS)
def test_assessment_report_carries_three_sections_and_disclaimer(fmt, tmp_path):
    path = _out(tmp_path, "rep." + fmt)
    snapshot = {
        "year": 2022,
        "db_name": "ledger.sqlite",
        "ruleset_id": "base-jtg5210-2018",
        "ruleset_version": "0.0.0-draft",
        "route_rows": 1,
        "segment_rows": 2,
        "survey_rows": 2,
        "distress_rows": 6,
        "partition_change_rows": 0,
        "receipts": [{"source_file": "S99-2022.csv", "data_class": "SYNTHETIC", "rows_accepted": 2, "rows_rejected": 1}],
        "checks_summary": {"total": 3, "found": 2, "undetermined": 1},
    }
    result = exporters.export_assessment_report(path, fmt, snapshot, [_pci()], [_mqi_row()])
    assert result["tables"] == 3
    text = "\n".join(docx_text(path)) if fmt == "docx" else _read(path).decode("utf-8")
    for phrase in ("台账概况", "路段 PCI 评定", "MQI 汇总与分级", disclaimer.DISCLAIMER):
        assert phrase in text


def _mqi_row():
    return {
        "level": "route",
        "object_id": "S99",
        "year": 2022,
        "status": "blocked",
        "blocked_reason": "该路线全部成员都未出数，不做任何平均（应核实系数后再算）",
        "scope_note": "",
        "mqi": None,
        "grade": None,
        "component_scores": {},
        "included_components": [],
        "excluded_components": [],
        "weighted_length_m": None,
        "ruleset_id": "base-jtg5210-2018",
        "ruleset_version": "0.0.0-draft",
        "grade_threshold_key": "grade_threshold.mqi",
        "weight_keys": [],
    }


def test_report_refuses_missing_snapshot_or_empty_results(tmp_path):
    with pytest.raises(InputUnavailable):
        exporters.export_assessment_report(_out(tmp_path, "a.md"), "md", {}, [_pci()], [_mqi_row()])
    with pytest.raises(InputUnavailable):
        exporters.export_assessment_report(_out(tmp_path, "a.md"), "md", {"year": 2022}, [], [])


# ---------------------------------------------------------------- 纪律闸门

@pytest.mark.parametrize("word", BANNED)
@pytest.mark.parametrize("fmt", exporters.FORMATS)
def test_over_claimed_wording_is_refused_in_row_text(word, fmt, tmp_path):
    rows = _rows()
    rows[0]["blocked_reason"] = "该系数原文与表格已%s" % word
    with pytest.raises(PrivacyViolation):
        exporters.export_priority_list(_out(tmp_path, "plan." + fmt), fmt, rows)


@pytest.mark.parametrize("fmt", exporters.FORMATS)
def test_fixture_contamination_is_refused(fmt, tmp_path):
    rows = _rows()
    rows[0]["clause"] = "来自 fixture 包的表 5.2.1"
    with pytest.raises(PrivacyViolation):
        exporters.export_priority_list(_out(tmp_path, "plan." + fmt), fmt, rows)


@pytest.mark.parametrize("fmt", exporters.FORMATS)
def test_absolute_path_and_timestamp_are_refused(fmt, tmp_path):
    for payload in ("D:\\Users\\someone\\ledger.sqlite", "2026-10-07 15:00:00", "/home/example/data/raw"):
        rows = _rows()
        rows[0]["triggered_by"] = payload
        with pytest.raises(PrivacyViolation):
            exporters.export_priority_list(_out(tmp_path, "plan." + fmt), fmt, rows)


def test_export_gate_is_reachable_for_direct_calls():
    with pytest.raises(PrivacyViolation):
        exporters.assert_export_safe("本结论已确认无误")
    assert exporters.assert_export_safe("本结论待核对（应核实）") is None


# ---------------------------------------------------------------- 字段口径

def test_plan_rows_only_relay_fields_from_payloads():
    rows = exporters.plan_rows(
        [_suggestion(status="ok", year=2023, pci=84.0, action_class="日常养护", rule_id="R01", clause="表 5.2.1")],
        pci_results=[_pci(status="ok", year=2023, pci=84.0, grade="良")],
        compare_results=[_compare(status="ok", delta=-3.5, deterioration_rate_per_year=-1.75)],
        from_year=2022,
    )
    row = rows[0]
    assert set(row) == set(exporters.PLAN_COLUMNS)
    assert row["rank"] == 1
    assert row["pci"] == 84.0            # 来自对策 payload
    assert row["grade"] == "良"           # 来自评定 payload（转述，不重算）
    assert row["delta"] == -3.5           # 来自对比 payload
    assert row["deterioration_rate_per_year"] == -1.75
    assert row["clause"] == "表 5.2.1"


def test_numbers_are_not_re_rounded_by_the_export_layer(tmp_path):
    rows = exporters.plan_rows(
        [_suggestion(status="ok", year=2023, pci=84.05, mqi_partial=None)],
        pci_results=[_pci(status="ok", year=2023, pci=84.05, grade="良")],
    )
    path = _out(tmp_path, "plan.csv")
    exporters.export_priority_list(path, "csv", rows)
    text = _read(path).decode("utf-8")
    assert "84.05" in text and "84.1" not in text


def test_without_from_year_change_columns_stay_empty():
    rows = exporters.plan_rows(
        [_suggestion(year=2023)],
        pci_results=[_pci(year=2023)],
        compare_results=[_compare(delta=-3.5)],
        from_year=None,
    )
    assert rows[0]["delta"] is None and rows[0]["deterioration_rate_per_year"] is None
    rows_with = exporters.plan_rows(
        [_suggestion(year=2023)], pci_results=[_pci(year=2023)], compare_results=[_compare(delta=-3.5)], from_year=2022
    )
    assert rows_with[0]["delta"] == -3.5


@pytest.mark.parametrize("fmt", exporters.FORMATS)
def test_blocked_rows_stay_on_the_sheet_with_empty_numbers(fmt, tmp_path):
    path = _out(tmp_path, "plan." + fmt)
    rows = _rows(count=3)
    exporters.export_priority_list(path, fmt, rows)
    text = "\n".join(docx_text(path)) if fmt == "docx" else _read(path).decode("utf-8")
    for segment_id in ("S99-A1", "S99-A2", "S99-A3"):
        assert segment_id in text
    assert "None" not in text and "NaN" not in text
    assert "blocked" in text and "应核实" in text


# ---------------------------------------------------------------- 字节一致性

@pytest.mark.parametrize("fmt", exporters.FORMATS)
def test_two_exports_are_byte_identical(fmt, tmp_path):
    first = _out(tmp_path, "one." + fmt)
    second = _out(tmp_path, "two." + fmt)
    rows = _rows(count=4)
    exporters.export_priority_list(first, fmt, rows)
    exporters.export_priority_list(second, fmt, rows)
    assert _read(first) == _read(second)


def test_docx_package_is_a_valid_fixed_timestamp_zip(tmp_path):
    path = _out(tmp_path, "plan.docx")
    exporters.export_priority_list(path, "docx", _rows())
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert names[0] == "[Content_Types].xml"
        for part in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
            assert part in names
        # 落盘产物无时间戳：zip 条目时间固定为 1980-01-01 00:00:00
        assert set(info.date_time for info in archive.infolist()) == {(1980, 1, 1, 0, 0, 0)}
        rels = archive.read("_rels/.rels").decode("utf-8")
        assert "Override" not in rels
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "<w:tbl>" in xml and "<w:sectPr>" in xml


# ---------------------------------------------------------------- CLI 接线

@pytest.fixture
def ledger(tmp_path, monkeypatch, repo_root):
    """建一份真台账（2022 + 2023 两年入库），供 CLI 导出路径真跑。"""
    from road_mqi_checker import cli

    db = str(tmp_path / "ledger.sqlite")
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    for argv in (
        ["--db", db, "ledger", "init"],
        ["--db", db, "import", "--file", os.path.join(repo_root, "data", "raw", "S99-2022.csv"), "--year", "2022"],
        ["--db", db, "import", "--file", os.path.join(repo_root, "data", "raw", "S99-2023.csv"), "--year", "2023"],
    ):
        assert cli.main(argv) in (0, 1)
    return db, tmp_path


def _cli(argv):
    """跑一次 CLI 内核并收回（退出码, 输出文本）—— 与 CLI 契约测试同一取法。"""
    import contextlib

    from road_mqi_checker import cli

    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        return cli.main(list(argv)), out.getvalue()


@pytest.mark.parametrize("fmt", exporters.FORMATS)
def test_cli_report_real_run_codes_and_files(fmt, ledger, monkeypatch, repo_root):
    db, tmp_path = ledger
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    path = str(tmp_path / ("rep." + fmt))
    rc, out = _cli(["--db", db, "report", "--year", "2022", "--format", fmt, "--out", path])
    # 内置系数包下全 blocked ⇒ 导出成功但降级完成（1），不是 3（占位符时代）
    assert rc == 1, out
    assert os.path.isfile(path) and os.path.getsize(path) > 0
    # 命令行只报路径与统计，不复述声明全文（全文只在交付物里）
    assert disclaimer.DISCLAIMER not in out


def test_cli_report_json_and_plan_scope(ledger, monkeypatch, repo_root):
    db, tmp_path = ledger
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    path = str(tmp_path / "plan.md")
    rc, out = _cli(
        ["--db", db, "--json", "report", "--year", "2023", "--scope", "plan", "--from-year", "2022",
         "--format", "md", "--out", path]
    )
    assert rc == 1, out
    payload = json.loads(out)
    assert payload["scope"] == "plan" and payload["row_count"] == 4
    assert payload["export"]["format"] == "md" and payload["export"]["bytes"] > 0
    text = _read(path).decode("utf-8")
    assert "rank,route_id" not in text  # md 是竖线表头，不是 csv
    assert "| rank | route_id |" in text


def test_cli_report_without_rows_is_input_unavailable(ledger, monkeypatch, repo_root):
    db, tmp_path = ledger
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    rc, out = _cli(["--db", db, "report", "--year", "2031", "--out", str(tmp_path / "x.csv")])
    assert rc == 2 and "2031" in out


def test_cli_report_is_byte_reproducible(ledger, monkeypatch, repo_root):
    db, tmp_path = ledger
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    for fmt in exporters.FORMATS:
        a, b = str(tmp_path / ("a." + fmt)), str(tmp_path / ("b." + fmt))
        rc_a, _ = _cli(["--db", db, "report", "--year", "2022", "--format", fmt, "--out", a])
        rc_b, _ = _cli(["--db", db, "report", "--year", "2022", "--format", fmt, "--out", b])
        assert (rc_a, rc_b) == (1, 1)
        assert _read(a) == _read(b), fmt


def test_exports_never_leak_the_local_absolute_paths(ledger, monkeypatch, repo_root):
    db, tmp_path = ledger
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    for fmt in exporters.FORMATS:
        path = str(tmp_path / ("leak." + fmt))
        _cli(["--db", db, "report", "--year", "2022", "--format", fmt, "--out", path])
        text = _read(path).decode("utf-8", "replace") if fmt != "docx" else "\n".join(docx_text(path))
        assert repo_root not in text.replace("\\", "/")
        assert db not in text
        assert not re.search(r"[A-Za-z]:[\\/]", text)
        username = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        if username:
            assert username not in text
