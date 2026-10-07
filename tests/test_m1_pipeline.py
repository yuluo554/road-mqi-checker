"""M1 数据通路：导入回执、八类校验的召回/误报实测、跨年划分变更与不可比标记。

召回与误报是 M1 DoD 里唯一要出**实测数字**的两项，所以期望集从真值文件与注入声明独立推出
（不拿校验层的输出自证），再与实际检出对账。
"""

import json
import os
import re

import pytest

from road_mqi_checker import cli, privacy
from road_mqi_checker.bench import evaluation, generator
from road_mqi_checker.errors import InputUnavailable, PrivacyViolation
from road_mqi_checker.ledger import checks, db, importer
from road_mqi_checker.ruleset import loader as ruleset_loader

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO, "data", "raw")
TRUTH_DIR = os.path.join(REPO, "data", "truth")
SCRATCH = os.path.join(REPO, ".tmp_m1")

#: 真值注入类别 → 该由哪一项校验（或哪条拒因）检出。
#: 词汇单点定义在 `bench.evaluation`（M5 起 `bench run` 的召回分母用同一张表）。
CELL_KIND_BY_ISSUE = evaluation.EXPECTED_KIND_BY_ISSUE
CELL_KINDS = set(CELL_KIND_BY_ISSUE.values())

#: 跨年划分变更的期望集：按 PARTITION_PLAN 的几何逐对推出（写在测试里，不从校验器输出反推）
EXPECTED_TRANSITIONS = {
    ("S99", 2022, 2023): {("shifted", "S99-A2")},
    ("S99", 2023, 2024): {("split", "S99-A2"), ("split", "S99-A2A"), ("split", "S99-A2B")},
    ("S99", 2024, 2025): {("disappeared", "S99-A4"), ("new", "S99-A5"), ("shifted", "S99-A3")},
    ("X990", 2022, 2023): {("shifted", "X990-B3")},
    ("X990", 2023, 2024): {("merged", "X990-B23")},
    ("X990", 2024, 2025): set(),
    ("Y999", 2022, 2023): {("shifted", "Y999-C2")},
    ("Y999", 2023, 2024): {("new", "Y999-C4")},
    ("Y999", 2024, 2025): {("shifted", "Y999-C1"), ("shifted", "Y999-C2")},
}


# ---- 辅助 ----


def _raw_path(route_id, year):
    return os.path.join(RAW_DIR, generator.raw_file_name(route_id, year))


def _raw_header(path):
    with open(path, "r", encoding="utf-8", newline="") as handle:
        for line in handle:
            if not line.startswith("#"):
                return line.strip().split(",")
    raise AssertionError("%s 没有表头" % path)


def _variant(source_route, source_year, name, columns=None, rows=None):
    """从冻结演示数据派生变体 CSV（只测拒入路径），落在 .tmp_m1/ 临时目录。

    `columns={列: 新值}` 改所有行；`rows=[(行号, 列, 新值)]` 只改指定行 —— 用来造
    "同一对象前后矛盾"与"一份表里混进第二条路线"。
    """
    source = _raw_path(source_route, source_year)
    header = _raw_header(source)
    all_rows = {column: value for column, value in (columns or {}).items()}
    per_row = rows or []
    os.makedirs(os.path.join(SCRATCH, "variants"), exist_ok=True)
    path = os.path.join(SCRATCH, "variants", name)
    lines = [generator.FILE_MARK_LINE, ",".join(header)]
    for row in importer.read_table(source):
        cells = []
        for column in header:
            value = all_rows.get(column, row.get(column, ""))
            for row_no, target_column, new_value in per_row:
                if row["_row_no"] == row_no and column == target_column:
                    value = new_value
            cells.append(str(value))
        lines.append(",".join(cells))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def _import_all(conn):
    receipts = []
    for route_id in generator.ROUTE_IDS:
        for year in generator.plan_years():
            receipts.append(importer.import_csv(conn, _raw_path(route_id, year), year))
    return receipts


def _truth_rows():
    rows = []
    for route_id in generator.ROUTE_IDS:
        for year in generator.plan_years():
            rows.extend(importer.read_table(os.path.join(TRUTH_DIR, generator.truth_file_name(route_id, year))))
    return rows


def _expected_cell_set():
    return {
        (CELL_KIND_BY_ISSUE[row["injected_issue"]], row["segment_id"], int(row["year"]))
        for row in _truth_rows()
        if row["injected_issue"] in CELL_KIND_BY_ISSUE
    }


def _detected_cell_set(receipts, findings):
    detected = {
        (finding.kind, finding.segment_id, int(finding.year))
        for finding in findings
        if finding.verdict == checks.VERDICT_FOUND and finding.kind in CELL_KINDS
    }
    for receipt in receipts:
        year = int(receipt.source_file.split("-")[1].split(".")[0])
        for line in receipt.lines:
            if line.code == "R008_DUPLICATE" and line.segment_id:
                detected.add(("duplicate_import", line.segment_id, year))
    return detected


def _expected_partition_detections():
    """由 EXPECTED_TRANSITIONS + 几何推出检出对象：父侧记 year_from，子侧记 year_to。"""
    expected = set()
    for (route_id, year_from, year_to), cases in EXPECTED_TRANSITIONS.items():
        parents = {spec[0] for spec in generator.PARTITION_PLAN[(route_id, year_from)]}
        for kind, segment_id in cases:
            parent_side = kind == "disappeared" or (kind == "split" and segment_id in parents)
            expected.add((segment_id, year_from if parent_side else year_to))
    return expected


@pytest.fixture
def ledger():
    conn = db.connect(":memory:")
    db.initialize(conn)
    checks.reset_ruleset_cache()
    yield conn
    conn.close()
    checks.reset_ruleset_cache()


@pytest.fixture(scope="module")
def full_ledger():
    """整套演示数据入库 + 四个年度全量校验，供需要真实计数的断言复用。"""
    conn = db.connect(":memory:")
    db.initialize(conn)
    checks.reset_ruleset_cache()
    receipts = _import_all(conn)
    ruleset = ruleset_loader.select_ruleset()
    findings = []
    for year in generator.plan_years():
        findings.extend(checks.run_all_checks(conn, year, ruleset))
    yield conn, receipts, findings
    conn.close()
    checks.reset_ruleset_cache()


# ---- 导入：结构、内容与安全边界 ----


def test_import_fills_the_ledger(ledger):
    receipts = _import_all(ledger)
    assert len(receipts) == 12
    assert db.table_names(ledger) == db.expected_tables()
    assert ledger.execute("SELECT COUNT(*) FROM segment").fetchone()[0] == 42
    assert ledger.execute("SELECT COUNT(*) FROM survey").fetchone()[0] == 42
    assert ledger.execute("SELECT COUNT(*) FROM route").fetchone()[0] == 12


def test_only_in_file_duplicates_are_rejected(ledger):
    rejected = [receipt for receipt in _import_all(ledger) if receipt.rows_rejected]
    assert [r.source_file for r in rejected] == ["S99-2022.csv", "X990-2024.csv"]
    for receipt in rejected:
        assert receipt.reject_counts() == {"R008_DUPLICATE": 1}
        assert receipt.lines[0].segment_id in ("S99-A1", "X990-B1")


def test_anomalous_values_are_stored_not_rejected(ledger):
    """负值/超范围/单位错是"要入库并被检出"的对象：表上没有 CHECK 约束，导入层也不拒。"""
    for route_id, year in (
        ("S99", 2025),
        ("Y999", 2022),
        ("X990", 2023),
        ("S99", 2024),
        ("X990", 2022),
        ("Y999", 2025),
    ):
        receipt = importer.import_csv(ledger, _raw_path(route_id, year), year)
        assert receipt.rows_rejected == 0, (route_id, year, receipt.reject_summary())
    assert ledger.execute("SELECT COUNT(*) FROM distress WHERE quantity < 0").fetchone()[0] == 2
    assert ledger.execute("SELECT COUNT(*) FROM survey WHERE rqi > 100").fetchone()[0] == 1
    mismatched = ledger.execute(
        "SELECT COUNT(*) FROM distress WHERE (distress_type = '坑洞' AND quantity_unit = 'm')"
        " OR (distress_type = '网状裂缝' AND quantity_unit = 'm')"
    ).fetchone()[0]
    assert mismatched == 2, mismatched


def test_missing_measurement_stays_null_not_zero(ledger):
    """水泥路面未采集车辙 → 入库是 NULL：填 0 会被加权当成真值。"""
    importer.import_csv(ledger, _raw_path("X990", 2022), 2022)
    rows = ledger.execute("SELECT surface_type, rut_depth_mm FROM survey WHERE route_id = 'X990'").fetchall()
    assert rows and all(row["surface_type"] == "cement" for row in rows)
    assert all(row["rut_depth_mm"] is None for row in rows)


def test_dry_run_writes_nothing(ledger):
    receipt = importer.import_csv(ledger, _raw_path("S99", 2022), 2022, dry_run=True)
    assert receipt.rows_rejected == 1 and receipt.rows_accepted == 11
    for table in ("route", "segment", "survey", "distress", "import_receipt"):
        assert ledger.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0] == 0, table


def test_reimport_same_file_is_deduped_by_digest(ledger):
    first = importer.import_csv(ledger, _raw_path("S99", 2022), 2022)
    assert first.rows_accepted > 0
    segments_before = ledger.execute("SELECT COUNT(*) FROM segment").fetchone()[0]
    again = importer.import_csv(ledger, _raw_path("S99", 2022), 2022)
    assert again.duplicate_file is True
    assert again.rows_accepted == 0
    # 整份重复：行数按行计，拒因给一条文件级说明（逐行重复拒因没有额外信息量）
    assert again.rows_rejected == again.rows_total
    assert len(again.lines) == 1 and again.lines[0].code == "R008_DUPLICATE"
    assert ledger.execute("SELECT COUNT(*) FROM segment").fetchone()[0] == segments_before
    # 去重也要留下证据：回执表里两条，且第二行的入库行数记 0
    receipts = ledger.execute("SELECT rows_accepted, rows_rejected FROM import_receipt ORDER BY receipt_id").fetchall()
    assert len(receipts) == 2 and receipts[1]["rows_accepted"] == 0


def test_receipt_rows_use_the_locked_columns(ledger):
    receipt = importer.import_csv(ledger, _raw_path("S99", 2022), 2022)
    rows = receipt.to_rows()
    assert rows
    for row in rows:
        assert tuple(sorted(row)) == tuple(sorted(importer.RECEIPT_COLUMNS))


def test_year_mismatch_rows_are_rejected(ledger):
    path = _variant("S99", 2022, "wrong_year.csv", columns={"year": 2023})
    receipt = importer.import_csv(ledger, path, 2022)
    assert receipt.rows_accepted == 0
    assert receipt.reject_counts()["R009_MALFORMED_ROW"] == receipt.rows_total
    assert "2023" in receipt.lines[0].detail


def test_segment_field_conflict_within_one_file_is_rejected(ledger):
    """宽表里同一对象的各列必须一致：只改一行的 surface_type 就要被拒，不静默取首行值。"""
    target_no = [
        row["_row_no"] for row in importer.read_table(_raw_path("S99", 2022)) if row["segment_id"] == "S99-A2"
    ][1]
    path = _variant("S99", 2022, "conflict.csv", rows=[(target_no, "surface_type", "cement")])
    receipt = importer.import_csv(ledger, path, 2022)
    conflict = [line for line in receipt.lines if line.field == "surface_type"]
    assert len(conflict) == 1, [line.as_dict() for line in receipt.lines]
    assert conflict[0].code == "R009_MALFORMED_ROW"
    assert conflict[0].segment_id == "S99-A2"


def test_second_route_in_one_file_is_unknown_route(ledger):
    """一份检测表只覆盖一条路线：混进别的路线编号的行按 R001 拒入。"""
    target_no = [
        row["_row_no"] for row in importer.read_table(_raw_path("S99", 2022)) if row["segment_id"] == "S99-A3"
    ][0]
    path = _variant("S99", 2022, "two_routes.csv", rows=[(target_no, "route_id", "X990")])
    receipt = importer.import_csv(ledger, path, 2022)
    offenders = [line for line in receipt.lines if line.code == "R001_UNKNOWN_ROUTE"]
    assert len(offenders) == 1, [line.as_dict() for line in receipt.lines]
    assert offenders[0].segment_id == "S99-A3"


def test_unmarked_file_refuses_without_declaration(ledger, tmp_path):
    """没有 data_class 标记又没显式声明 → 拒读：红线不能靠"猜这是不是演示数据"。"""
    source = _raw_path("S99", 2022)
    header = _raw_header(source)
    path = os.path.join(str(tmp_path), "plain.csv")
    lines = [",".join(header)]
    for row in importer.read_table(source):
        lines.append(",".join(str(row.get(column, "")) for column in header))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    with pytest.raises(InputUnavailable):
        importer.import_csv(ledger, path, 2022)
    # 显式声明是用户自己的真实台账时才不走合成白名单
    assert importer.plan_import(ledger, path, 2022, data_class=importer.DATA_CLASS_USER).rows_accepted > 0


def test_real_form_identifiers_are_refused_in_synthetic_data(ledger):
    """真实形态标识符（G25 / 110101 / 实名单位 / 真实报告号）在声称合成的数据里逐行拒入。"""
    path = _variant(
        "S99",
        2022,
        "real_form.csv",
        columns={
            "route_id": "G25",
            "adcode": "110101",
            "segment_name": "清河县东段",
            "detect_org": "河北省公路工程有限公司",
            "report_no": "JC20220113",
        },
    )
    receipt = importer.import_csv(ledger, path, 2022)
    assert receipt.rows_accepted == 0
    assert receipt.reject_counts().get("R010_PRIVACY_WHITELIST") == receipt.rows_total
    assert "白名单" in receipt.lines[0].detail


def test_mark_conflicting_with_declaration_is_refused(ledger):
    with pytest.raises(InputUnavailable):
        importer.import_csv(ledger, _raw_path("S99", 2022), 2022, data_class=importer.DATA_CLASS_USER)


def test_whitelist_classes_reject_real_forms():
    """138 一类真实号段一律拒；只有登记的保留形式才过。"""
    for value in ("13800138000", "13912345678"):
        with pytest.raises(PrivacyViolation):
            privacy.assert_synthetic("phone", value)
    assert privacy.assert_synthetic("phone", "19900001234") == "19900001234"
    for kind, value in (("route_id", "G25"), ("adcode", "110101"), ("segment_name", "清河县东段")):
        with pytest.raises(PrivacyViolation):
            privacy.assert_synthetic(kind, value)


def test_committed_data_identifiers_all_pass_the_whitelist():
    """入仓演示数据的每个标识符列都要落在登记过的白名单形态里（不是"看着像虚构"）。"""
    offenders = []
    for name in sorted(os.listdir(RAW_DIR)):
        if not name.endswith(".csv"):
            continue
        for row in importer.read_table(os.path.join(RAW_DIR, name)):
            for column, kind in (
                ("route_id", "route_id"),
                ("adcode", "adcode"),
                ("segment_name", "segment_name"),
                ("seg_start_stake", "stake"),
                ("seg_end_stake", "stake"),
                ("route_start_stake", "stake"),
                ("route_end_stake", "stake"),
                ("detect_org", "org_name"),
                ("report_no", "report_no"),
            ):
                if not privacy.is_synthetic(kind, row.get(column)):
                    offenders.append((name, row["_row_no"], column, row.get(column)))
    assert not offenders, offenders


def test_committed_data_has_no_phone_shaped_numbers():
    """199 保留号段之外的十位以上连续数字（手机号形态）不得出现在演示数据里。"""
    offenders = []
    for folder in (RAW_DIR, TRUTH_DIR):
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".csv"):
                continue
            with open(os.path.join(folder, name), "r", encoding="utf-8") as handle:
                for match in re.finditer(r"1[3-9]\d{9}", handle.read()):
                    if not match.group(0).startswith("1990"):
                        offenders.append((name, match.group(0)))
    assert not offenders, offenders


# ---- 校验：召回与误报（M1 DoD 的实测数字）----


def test_anomaly_recall_is_measured_and_full(full_ledger):
    _conn, receipts, findings = full_ledger
    expected = _expected_cell_set()
    detected = _detected_cell_set(receipts, findings)
    assert len(expected) == 12, "真值里格级注入用例应为 12 例，实得 %d" % len(expected)
    assert expected <= detected, "未检出：%s" % sorted(expected - detected)
    assert len(expected & detected) / float(len(expected)) == 1.0


def test_anomaly_false_alarm_is_measured_and_zero(full_ledger):
    conn, receipts, findings = full_ledger
    expected = _expected_cell_set()
    extra = sorted(_detected_cell_set(receipts, findings) - expected)
    total_objects = conn.execute("SELECT COUNT(*) FROM segment").fetchone()[0]
    marked_objects = len({key[1] for key in expected})
    assert extra == [], "误报：%s" % extra
    assert total_objects - marked_objects > 0
    assert len(extra) / float(total_objects - marked_objects) == 0.0


def test_clean_control_cells_produce_no_findings(full_ledger):
    _conn, _receipts, findings = full_ledger
    marks = {(row["segment_id"], int(row["year"])) for row in _truth_rows() if row["injected_issue"] != "none"}
    wrongly_flagged = [
        finding.report_line()
        for finding in findings
        if finding.kind in CELL_KINDS and (finding.segment_id, int(finding.year)) not in marks
    ]
    assert wrongly_flagged == [], wrongly_flagged


def test_partition_detections_are_fully_explained(full_ledger):
    """划分变更的检出必须逐条对得上声明的几何，既不漏也不多报。"""
    _conn, _receipts, findings = full_ledger
    detected = {(finding.segment_id, int(finding.year)) for finding in findings if finding.kind == "partition_change"}
    assert detected == _expected_partition_detections(), (
        "多出：%s 缺失：%s" % (sorted(detected - _expected_partition_detections()), sorted(_expected_partition_detections() - detected))
    )
    marks = {
        (row["segment_id"], int(row["year"]))
        for row in _truth_rows()
        if row["injected_issue"] == "partition_change"
    }
    assert marks <= detected


def test_distress_dictionary_is_clean_in_frozen_data_but_catches_intruders(full_ledger, ledger):
    _conn, _receipts, findings = full_ledger
    assert [f for f in findings if f.kind == "distress_dictionary"] == []

    importer.import_csv(ledger, _raw_path("S99", 2022), 2022)
    ledger.execute(
        "INSERT INTO distress (segment_id, year, distress_type, severity, quantity, quantity_unit, source_row_no)"
        " VALUES (?,?,?,?,?,?,?)",
        ("S99-A3", 2022, "沉陷未知型", "特重", 3.0, "m2", 99),
    )
    ledger.commit()
    caught = checks.check_distress_dictionary(ledger, 2022)
    assert len(caught) == 2, [f.detail for f in caught]
    assert all(f.reject_code == "R005_BAD_DICTIONARY" for f in caught)


def test_value_range_stays_undetermined_when_bounds_are_unknown(ledger):
    """缺车道数/路面宽/板块总数就算不出几何上界 → 只能判"未判定"，不许默认合格。"""
    importer.import_csv(ledger, _raw_path("S99", 2022), 2022)
    ledger.execute("UPDATE segment SET lane_count = NULL, segment_width_m = NULL WHERE segment_id = 'S99-A1'")
    ledger.execute("UPDATE distress SET quantity = 1000000 WHERE segment_id = 'S99-A1' AND quantity_unit = 'm2'")
    ledger.commit()
    findings = [f for f in checks.check_value_range(ledger, 2022) if f.segment_id == "S99-A1"]
    assert findings, "上界未知时应给出未判定"
    assert all(f.verdict == checks.VERDICT_UNDETERMINED for f in findings), [f.detail for f in findings]


# ---- 闭合差：判据依赖容差这一格系数；M3 起该格已显式登记，判与不判都要有证据 ----


def _tolerance_pending_ruleset(tmp_path):
    """把内置包的容差格退回 pending，用来继续守住"未核对只报差值不判定"这条门。"""
    src = os.path.join(ruleset_loader._BUILTIN_DIR, "base-jtg5210-2018.json")
    with open(src, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    for coef in payload["coefficients"]:
        if coef["key"] == "tolerance.length_closure":
            coef["status"] = "pending"
            coef["values"] = None
            coef["basis"][0].update({"status": "pending", "clause": "", "channel": "", "verified_at": "", "locator": ""})
    path = os.path.join(str(tmp_path), "tolerance-pending.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return ruleset_loader.load_file(path)


def test_length_closure_never_hard_judges_while_tolerance_pending(tmp_path):
    """容差退回 pending → 同一批数据只能出"未判定"，且差值仍然报得出来。"""
    ruleset = _tolerance_pending_ruleset(tmp_path)
    conn = db.connect(":memory:")
    db.initialize(conn)
    checks.reset_ruleset_cache()
    try:
        _import_all(conn)
        findings = []
        for year in generator.plan_years():
            findings.extend(checks.run_all_checks(conn, year, ruleset))
    finally:
        conn.close()
        checks.reset_ruleset_cache()
    closure = [f for f in findings if f.kind == "length_closure"]
    assert closure, "闭合差校验项没有输出"
    assert all(f.verdict == checks.VERDICT_UNDETERMINED for f in closure), [f.detail for f in closure]
    assert all("未判定" in f.detail and "闭合差" in f.detail for f in closure)
    # 差值本身要看得见：4 个非零闭合差一个都不能少（只是不判定）
    assert len(closure) == 4, [f.detail for f in closure]


def test_length_closure_is_judged_under_the_registered_builtin_tolerance(full_ledger):
    """M3 之后内置包容差已生效 → 同一判据真的在判：4 个非零闭合差全部转为检出，无一条未判定。"""
    _conn, _receipts, findings = full_ledger
    closure = [f for f in findings if f.kind == "length_closure"]
    assert len(closure) == 4, [f.detail for f in closure]
    assert all(f.verdict == checks.VERDICT_FOUND for f in closure), [f.detail for f in closure]
    assert all("超出已核对容差" in f.detail for f in closure), [f.detail for f in closure]
    assert not any("未判定" in f.detail for f in closure)


def test_zero_closure_is_not_reported(ledger):
    """闭合差为 0 时没有要判的东西：任何非负容差都容得下 0，不需要未核对的容差来背书。"""
    importer.import_csv(ledger, _raw_path("S99", 2023), 2023)
    assert checks.check_length_closure(ledger, "S99", 2023) == []


def test_closure_becomes_judged_once_tolerance_is_verified(ledger, tmp_path):
    """容差这一格转成可计算状态后，同一判据真的能判 —— 证明"未判定"是系数门挡的，不是没实现。

    夹具档规则集只在测试里构造（不进 data/、不进内置包），容差取明显非规范的夹具值 50。
    """
    path = os.path.join(str(tmp_path), "fixture-tolerance.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(_tolerance_ruleset_fixture(), ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    loaded = ruleset_loader.load_file(path, allow_fixture=True)
    assert loaded.find("tolerance.length_closure").computable is True
    checks.set_ruleset(loaded)
    importer.import_csv(ledger, _raw_path("S99", 2022), 2022)
    findings = checks.check_length_closure(ledger, "S99", 2022)
    assert len(findings) == 1 and findings[0].verdict == checks.VERDICT_FOUND, [f.as_dict() for f in findings]


def _tolerance_ruleset_fixture():
    return {
        "schema_version": 1,
        "ruleset_id": "fixture-tolerance",
        "version": "0",
        "applies_to": {"province": "*", "year": "*", "surface_type": "*"},
        "coefficients": [
            {
                "key": "tolerance.length_closure",
                "kind": "grade_threshold",
                "status": "fixture",
                "values": {"meters": 50},
                "basis": [
                    {
                        "standard_id": "fixture-only",
                        "status": "fixture",
                        "clause": "n/a",
                        "channel": "tests/fixtures",
                        "verified_at": "n/a",
                        "locator": "n/a",
                    }
                ],
                "register_ref": "tests/fixtures/fixture-ruleset.json",
            }
        ],
    }


# ---- 重复导入的两层口径 ----


def test_duplicate_content_across_files_is_found_by_checks(ledger, tmp_path):
    """换一份文件（digest 不同、破损内容完全相同）再导 → 导入层看不见，check_duplicate_import 必须看见。"""
    clone = _variant("Y999", 2023, "copy2.csv", columns={"adcode": "990199"})
    first = importer.import_csv(ledger, _raw_path("Y999", 2023), 2023)
    second = importer.import_csv(ledger, clone, 2023)
    assert second.duplicate_file is False
    assert first.rows_accepted == second.rows_accepted and second.rows_rejected == 0
    findings = checks.check_duplicate_import(ledger)
    assert len(findings) == second.rows_accepted, [f.detail for f in findings]
    assert all(f.kind == "duplicate_import" and f.reject_code == "R008_DUPLICATE" for f in findings)


# ---- 跨年划分变更：四类都有用例，且显式标不可比 ----


def test_partition_transitions_match_the_declared_geometry(full_ledger):
    conn, _receipts, _findings = full_ledger
    rows = conn.execute(
        "SELECT route_id, year_from, year_to, change_kind, segment_id FROM partition_change"
    ).fetchall()
    actual = {
        (row["route_id"], row["year_from"], row["year_to"], row["change_kind"], row["segment_id"]) for row in rows
    }
    expected = set()
    for (route_id, year_from, year_to), cases in EXPECTED_TRANSITIONS.items():
        for kind, segment_id in cases:
            expected.add((route_id, year_from, year_to, kind, segment_id))
    assert actual == expected, "多出：%s 缺失：%s" % (sorted(actual - expected), sorted(expected - actual))


def test_all_four_partition_kinds_are_present(full_ledger):
    conn, _receipts, _findings = full_ledger
    kinds = {row["change_kind"] for row in conn.execute("SELECT DISTINCT change_kind FROM partition_change")}
    assert {"new", "disappeared", "merged", "split"} <= kinds, kinds


def test_partition_change_is_marked_uncomparable_without_reallocation(full_ledger):
    conn, _receipts, _findings = full_ledger
    rows = conn.execute("SELECT detail FROM partition_change").fetchall()
    assert rows
    for row in rows:
        assert "不可比" in row["detail"] and "摊分" in row["detail"], row["detail"]
        assert not re.search(r"\d+(\.\d+)?\s*%", row["detail"]), "不可比里不该出现摊分比例：%s" % row["detail"]


def test_run_all_checks_summary_after_tolerance_is_registered(full_ledger):
    _conn, _receipts, findings = full_ledger
    summary = checks.summarize(findings)
    assert summary["total"] == len(findings)
    assert summary["found"] + summary["undetermined"] == len(findings)
    assert summary["by_kind"]["partition_change"][checks.VERDICT_FOUND] == sum(
        len(cases) for cases in EXPECTED_TRANSITIONS.values()
    )
    nonzero_closure_cells = 4  # 两个悬空 + 两个重叠格子的长度和与里程不等
    # M3 起内置包容差已显式登记 → 这 4 格从"未判定"转为检出，四年度全量校验不再留未判定项
    assert summary["undetermined"] == 0, summary
    assert summary["by_kind"]["length_closure"][checks.VERDICT_FOUND] == nonzero_closure_cells, summary


# ---- CLI 接通 ----


def test_cli_bench_generate_is_idempotent_and_guarded(tmp_path, monkeypatch):
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(REPO, "data"))
    out = os.path.join(str(tmp_path), "raw")
    assert cli.main(["bench", "generate", "--out", out, "--seed", str(generator.DEFAULT_SEED)]) == 0
    assert os.path.isfile(os.path.join(out, generator.MANIFEST_NAME))
    # 同 seed 重跑：幂等，不改写
    assert cli.main(["bench", "generate", "--out", out]) == 0
    # 换 seed 会真的改动产物：没有 --force 要落 2（输入不可用），给了才放行
    assert cli.main(["bench", "generate", "--out", out, "--seed", "777"]) == 2
    assert cli.main(["bench", "generate", "--out", out, "--seed", "777", "--force"]) == 0


def test_cli_bench_generate_on_repo_data_is_no_op(tmp_path, monkeypatch):
    """README 里那条重生成命令在干净 clone 上直接可跑：入仓数据一致时不报错也不改字节。"""
    import shutil

    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(REPO, "data"))
    raw = os.path.join(str(tmp_path), "raw")
    truth = os.path.join(str(tmp_path), "truth")
    shutil.copytree(os.path.join(REPO, "data", "raw"), raw)
    shutil.copytree(os.path.join(REPO, "data", "truth"), truth)
    before = _dir_bytes(raw), _dir_bytes(truth)
    assert cli.main(["bench", "generate", "--out", raw]) == 0
    assert (before[0], before[1]) == (_dir_bytes(raw), _dir_bytes(truth)), "重跑改了入仓演示数据的字节"


def _dir_bytes(root):
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as handle:
                out[os.path.relpath(path, root)] = handle.read()
    return out


def test_cli_import_exit_codes_and_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(REPO, "data"))
    database = os.path.join(str(tmp_path), "ledger.sqlite")
    assert cli.main(["--db", database, "import", "--file", _raw_path("S99", 2022), "--year", "2022"]) == 1, (
        "有拒入行要落 1（降级完成）"
    )
    capsys.readouterr()

    rc = cli.main(
        ["--db", database, "--json", "import", "--file", _raw_path("X990", 2022), "--year", "2022", "--dry-run"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["receipt"]["rows_total"] > 0
    assert "checks" not in payload, "预检不写库，也就不该假装跑过校验"
    assert [sorted(row) for row in payload["receipt_rows"]][0] == sorted(importer.RECEIPT_COLUMNS)

    # 校验只查"上一年 → 本年度"这一对：2024 年看到的是 2023→2024 的拆分（父段 + 两个子段）
    assert cli.main(["--db", database, "import", "--file", _raw_path("S99", 2023), "--year", "2023"]) == 0
    capsys.readouterr()
    assert cli.main(["--db", database, "--json", "import", "--file", _raw_path("S99", 2024), "--year", "2024"]) == 0
    payload = json.loads(capsys.readouterr().out)
    by_kind = payload["checks"]["by_kind"]
    assert by_kind["partition_change"][checks.VERDICT_FOUND] == 3, by_kind["partition_change"]
    assert by_kind["value_range"][checks.VERDICT_FOUND] == 1, by_kind["value_range"]
    assert by_kind["length_closure"][checks.VERDICT_UNDETERMINED] == 0, "2024 年链条闭合，不该报未判定"
