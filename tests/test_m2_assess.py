"""M2 `rmqc assess` 真跑、数值真值接线，以及"演示数据里的异常对象出的是 blocked"。

这里刻意把三件事放在一起验：
1. CLI 通路与生成器真值通路用的是**同一个内核**（同一份数据两条通路逐字段相同）；
2. M1 注入的负值/超范围/单位错对象，在评定通路上出的是 blocked + 数值字段全空，
   不是"跳过那条破损行后算出来的一个数"；
3. 数值真值只能来自评定引擎（用 spy 证明被调用，不是文档承诺）。
"""

import io
import json
import os
import subprocess
import sys

import pytest

import support_pci as sup
from road_mqi_checker import cli, results as res
from road_mqi_checker.bench import generator
from road_mqi_checker.exit_codes import EXIT_DEGRADED, EXIT_INPUT_UNUSABLE, EXIT_OK
from road_mqi_checker.ledger import checks as ledger_checks
from road_mqi_checker.ledger import db as ledger_db
from road_mqi_checker.ledger import importer
from road_mqi_checker.pci import engine, trace

#: 让扣分不可解释的注入类别（其余注入影响里程账与跨年可比性，不影响本段扣分）
ABNORMAL_ISSUES = ("negative_value", "out_of_range", "unit_error")
#: 只影响里程/可比性的注入类别：评定照常出数，交给 M4 处理不可比
NON_BLOCKING_ISSUES = ("gap_chain", "overlap_chain", "partition_change", "duplicate_import")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO_ROOT, "data", "raw")
TRUTH_DIR = os.path.join(REPO_ROOT, "data", "truth")


@pytest.fixture
def run_cli(monkeypatch):
    """在指定台账上跑 CLI，返回 (rc, stdout, stderr)；规则集走内置包（全 pending）。"""

    def _run(argv):
        monkeypatch.delenv("RMQC_RULESET_DIR", raising=False)
        out, err = io.StringIO(), io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            rc = cli.main(argv)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 2
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        return rc, out.getvalue(), err.getvalue()

    return _run


def _import_cells(conn, raw_dir, cells):
    for route_id, year in cells:
        importer.import_csv(conn, os.path.join(raw_dir, generator.raw_file_name(route_id, year)), year)
    return conn


@pytest.fixture(scope="module")
def frozen_ledger():
    """整套演示数据入内存台账 + 真值行 + 该年度"让扣分不可解释"的检出项。"""
    conn = ledger_db.connect(":memory:")
    ledger_db.initialize(conn)
    ledger_checks.reset_ruleset_cache()
    cells = sorted(generator.PARTITION_PLAN.keys())
    raw_dir = RAW_DIR
    receipts = {
        cell: importer.import_csv(conn, os.path.join(raw_dir, generator.raw_file_name(*cell)), cell[1])
        for cell in cells
    }
    truth = {}
    for route_id, year in cells:
        path = os.path.join(TRUTH_DIR, generator.truth_file_name(route_id, year))
        for row in importer.read_table(path):
            truth[(row["segment_id"], int(row["year"]))] = row
    blockers = {}
    for year in sorted({year for _route, year in cells}):
        blockers[year] = engine.blocking_findings(conn, year)
    yield conn, truth, blockers, receipts
    conn.close()
    ledger_checks.reset_ruleset_cache()


# ---- assess 命令面 ----


def test_assess_with_builtin_ruleset_degrades_to_exit_one(run_cli, data_dir, tmp_path):
    path = str(tmp_path / "ledger.sqlite")
    conn = ledger_db.connect(path)
    ledger_db.initialize(conn)
    _import_cells(conn, os.path.join(data_dir, "raw"), [("S99", 2022)])
    conn.close()

    rc, out, err = run_cli(["--db", path, "--json", "assess", "--year", "2022"])
    assert rc == EXIT_DEGRADED, (out, err)
    payload = json.loads(out)
    assert payload["year"] == 2022
    assert payload["ruleset"]["ruleset_id"] == "base-jtg5210-2018"
    assert payload["counts"][res.STATUS_BLOCKED] == len(payload["results"])
    for row in payload["results"]:
        assert row["status"] == res.STATUS_BLOCKED
        assert row["pci"] is None and row["deducted_total"] is None
        assert row["grade"] is None and row["component_scores"] == {}
        assert row["contributions"] == []
        assert "应核实" in row["blocked_reason"]


def test_assess_text_output_names_the_degradation_reason(run_cli, data_dir, tmp_path):
    path = str(tmp_path / "ledger2.sqlite")
    conn = ledger_db.connect(path)
    ledger_db.initialize(conn)
    _import_cells(conn, os.path.join(data_dir, "raw"), [("S99", 2023)])
    conn.close()
    rc, out, _err = run_cli(["--db", path, "assess", "--year", "2023"])
    assert rc == EXIT_DEGRADED
    assert "blocked 4" in out
    assert "blocked 项的数值字段一律为空" in out


def test_assess_missing_year_is_input_unavailable(run_cli, tmp_path):
    path = str(tmp_path / "empty.sqlite")
    conn = ledger_db.connect(path)
    ledger_db.initialize(conn)
    conn.close()
    rc, _out, err = run_cli(["--db", path, "assess", "--year", "2022"])
    assert rc == EXIT_INPUT_UNUSABLE
    assert "没有路段" in err


def test_assess_segment_filter_and_unknown_segment(run_cli, data_dir, tmp_path):
    path = str(tmp_path / "ledger3.sqlite")
    conn = ledger_db.connect(path)
    ledger_db.initialize(conn)
    _import_cells(conn, os.path.join(data_dir, "raw"), [("S99", 2023)])
    conn.close()
    rc, out, _err = run_cli(["--db", path, "--json", "assess", "--year", "2023", "--segment", "S99-A2"])
    assert rc == EXIT_DEGRADED
    rows = json.loads(out)["results"]
    assert [row["segment_id"] for row in rows] == ["S99-A2"]
    rc, _out, err = run_cli(["--db", path, "assess", "--year", "2023", "--segment", "S99-NOPE"])
    assert rc == EXIT_INPUT_UNUSABLE and "S99-NOPE" in err


def test_assess_payload_shape_is_consumable_by_aggregate_and_gui(frozen_ledger):
    conn, truth, _blockers, _receipts = frozen_ledger
    results = engine.assess_year(conn, 2022, sup.asphalt_ruleset())
    assert results
    for row in (engine.result_payload(item) for item in results):
        for key in ("segment_id", "route_id", "year", "surface_type", "status", "pci", "grade", "component_scores", "contributions"):
            assert key in row, key
        for contribution in row["contributions"]:
            assert tuple(contribution.keys()) == trace.TRACE_COLUMNS
    assert set(engine.summarize_status(results)) == set(res.ALL_RESULT_STATUSES)


def test_assess_is_byte_identical_across_two_cold_process_starts(data_dir, tmp_path):
    """零漂移含"两次进程冷启动"：同一份台账文件、同一套规则集，stdout 必须逐字节相同。"""
    path = str(tmp_path / "drift.sqlite")
    conn = ledger_db.connect(path)
    ledger_db.initialize(conn)
    _import_cells(conn, os.path.join(data_dir, "raw"), [("S99", 2022), ("X990", 2022)])
    conn.close()
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    env = dict(os.environ, PYTHONPATH=src, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    outputs = []
    for _attempt in range(2):
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "road_mqi_checker", "--db", path, "--json", "assess", "--year", "2022"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        outputs.append((proc.returncode, proc.stdout))
        assert proc.returncode == EXIT_DEGRADED, proc.stderr.decode("utf-8", "replace")
    assert outputs[0] == outputs[1]


def test_assess_with_computed_ruleset_produces_numbers_only_for_clean_objects(frozen_ledger):
    conn, truth, _blockers, _receipts = frozen_ledger
    rulesets = {"asphalt": sup.asphalt_ruleset(), "cement": sup.cement_ruleset()}
    results = {}
    for year in (2022, 2023, 2024, 2025):
        for segment_id in sorted({key[0] for key in truth if key[1] == year}):
            surface = truth[(segment_id, year)]["surface_type"]
            results[(segment_id, year)] = engine.compute_segment_pci(conn, segment_id, year, rulesets[surface])
    numeric = [key for key, item in results.items() if item.pci is not None]
    blocked = [key for key, item in results.items() if item.status == res.STATUS_BLOCKED]
    assert numeric and blocked
    assert len(numeric) + len(blocked) == len(results)


# ---- 含异常数据即拒算（DoD 第 5 条）----


def test_every_abnormal_object_in_the_frozen_data_is_refused(frozen_ledger):
    conn, truth, blockers, _receipts = frozen_ledger
    rulesets = {"asphalt": sup.asphalt_ruleset(), "cement": sup.cement_ruleset()}
    expected_kinds = {
        "negative_value": "value_range",
        "out_of_range": "value_range",
        "unit_error": "unit_consistency",
    }
    refused = 0
    for (segment_id, year), row in sorted(truth.items()):
        issue = row["injected_issue"]
        if issue not in ABNORMAL_ISSUES:
            continue
        refused += 1
        result = engine.compute_segment_pci(conn, segment_id, year, rulesets[row["surface_type"]])
        assert result.status == res.STATUS_BLOCKED, (segment_id, year, issue, result.pci)
        assert (result.pci, result.deducted_total, result.grade, result.component_scores) == (
            None,
            None,
            None,
            {},
        ), (segment_id, year)
        assert result.contributions == []
        kinds = [kind for kind, _detail in blockers.get(year, {}).get(segment_id, [])]
        assert expected_kinds[issue] in kinds, (segment_id, year, issue, kinds)
        assert "M1 检出项" in result.blocked_reason
        result.check_contract()
    assert refused >= 6, "三类异常对象在演示数据里各 ≥2 例，实际只找到 %d 例" % refused


def test_objects_with_only_mileage_issues_still_get_numbers(frozen_ledger):
    """悬空/重叠/划分变更/文件内重复不改本段扣分的可解释性：出数，不可比交给 M4。"""
    conn, truth, blockers, _receipts = frozen_ledger
    rulesets = {"asphalt": sup.asphalt_ruleset(), "cement": sup.cement_ruleset()}
    checked = 0
    for (segment_id, year), row in sorted(truth.items()):
        if row["injected_issue"] not in NON_BLOCKING_ISSUES:
            continue
        result = engine.compute_segment_pci(conn, segment_id, year, rulesets[row["surface_type"]])
        assert result.status in (res.STATUS_OK, res.STATUS_PARTIAL), (segment_id, result.blocked_reason)
        assert result.pci is not None
        checked += 1
    assert checked >= 7, "演示数据里这类对象应有多个用例，实际 %d" % checked


def test_clean_objects_have_no_blocking_findings_and_get_numbers(frozen_ledger):
    conn, truth, blockers, _receipts = frozen_ledger
    rulesets = {"asphalt": sup.asphalt_ruleset(), "cement": sup.cement_ruleset()}
    for (segment_id, year), row in sorted(truth.items()):
        if row["injected_issue"] != "none":
            continue
        assert blockers.get(year, {}).get(segment_id, []) == [], (segment_id, year)
        result = engine.compute_segment_pci(conn, segment_id, year, rulesets[row["surface_type"]])
        if row["surface_type"] == "cement":
            # 演示数据的水泥路段不测车辙（缺测是 None，不填 0）：只能出带口径声明的部分分项结果
            assert result.status == res.STATUS_PARTIAL, (segment_id, year, result.blocked_reason)
            assert "rutting" in result.scope_note
        else:
            assert result.status == res.STATUS_OK, (segment_id, year, result.blocked_reason)
        assert 0.0 <= result.pci <= 100.0
        assert result.grade in ("优", "良", "中", "次", "差")


# ---- 数值真值接线 ----


def test_truth_probe_delegates_to_the_assessment_engine(monkeypatch, data_dir, tmp_path):
    calls = []
    real = engine.compute_pci

    def spy(segment, ruleset, blockers=()):
        calls.append((segment["segment_id"], segment["year"]))
        return real(segment, ruleset, blockers)

    monkeypatch.setattr(engine, "compute_pci", spy)
    expected = {
        (row["segment_id"], int(row["year"]))
        for row in importer.read_table(
            os.path.join(data_dir, "truth", generator.truth_file_name("S99", 2022))
        )
    }
    assert expected
    generator.generate(str(tmp_path / "raw"), ruleset=sup.asphalt_ruleset(), force=True)
    assert calls, "数值真值通路没有调用评定引擎 —— 说明接线没生效"
    assert expected <= set(calls), sorted(expected - set(calls))


def test_truth_columns_are_numeric_and_match_the_ledger_path(data_dir, tmp_path):
    """夹具规则集下：真值四列里的评分两列变数值，且与台账通路复算逐字段相同。"""
    out = str(tmp_path / "raw")
    ruleset = sup.asphalt_ruleset()
    generator.generate(out, ruleset=ruleset, force=True)
    truth_dir = os.path.join(str(tmp_path), "truth")

    conn = ledger_db.connect(":memory:")
    ledger_db.initialize(conn)
    cells = [cell for cell in sorted(generator.PARTITION_PLAN.keys()) if cell[0] in ("S99", "Y999")]
    _import_cells(conn, out, cells)

    compared = 0
    for route_id, year in cells:
        rows = importer.read_table(os.path.join(truth_dir, generator.truth_file_name(route_id, year)))
        for row in rows:
            if row["surface_type"] != "asphalt":
                continue
            segment_id = row["segment_id"]
            result = engine.compute_segment_pci(conn, segment_id, year, ruleset)
            pci_truth = row["pci_truth"]
            if result.status in (res.STATUS_OK, res.STATUS_PARTIAL):
                assert float(pci_truth) == pytest.approx(result.pci), (segment_id, year, pci_truth, result.pci)
                assert row["grade_truth"] == result.grade, (segment_id, year)
            else:
                assert pci_truth == generator.PENDING_ENGINE_PREFIX + "pci.engine.blocked"
                assert row["grade_truth"] == pci_truth
            compared += 1
    assert compared >= 10, "只比对了 %d 个沥青对象，样本不足以证明接线" % compared


def test_mqi_and_action_truth_columns_stay_pending_until_m4(tmp_path):
    """系数门过了、但所属模块还是占位符：这两列如实点名 mqi.engine@M4 / strategy.rules@M4。"""
    ruleset = sup.patched_ruleset(sup.ASPHALT_FIXTURE, sup.append_coefficients(*sup.mqi_and_action_cells()))
    for coef in sup.mqi_and_action_cells():
        assert ruleset.find(coef["key"]).computable
    out = str(tmp_path / "raw")
    generator.generate(out, ruleset=ruleset, force=True)
    rows = importer.read_table(os.path.join(str(tmp_path), "truth", generator.truth_file_name("S99", 2022)))
    for row in rows:
        assert row["mqi_partial_truth"] == generator.PENDING_ENGINE_PREFIX + "mqi.engine@M4"
        assert row["recommended_action_truth"] == generator.PENDING_ENGINE_PREFIX + "strategy.rules@M4"


def test_cement_truth_stays_pending_under_the_asphalt_fixture(tmp_path):
    """夹具包没覆盖水泥：真值那一列仍是点名系数的 pending 令牌，而不是借沥青的格子凑一个数。"""
    out = str(tmp_path / "raw")
    generator.generate(out, ruleset=sup.asphalt_ruleset(), force=True)
    rows = importer.read_table(os.path.join(str(tmp_path), "truth", generator.truth_file_name("X990", 2022)))
    assert rows
    for row in rows:
        assert row["surface_type"] == "cement"
        assert row["pci_truth"].startswith(generator.PENDING_COEFF_PREFIX)
        assert "deduct_ratio.cement_distress(未登记)" in row["pci_truth"]


def test_cement_fixture_produces_cement_truth(tmp_path, frozen_ledger):
    """换成水泥夹具包，同一格子的真值就变数值 —— 系数门是按规则集包生效的，不是硬编码。

    出数还是拒算不由路面类型决定，而由"该对象有没有检出异常"决定，所以这里逐对象与台账通路对账。
    """
    conn, _truth, blockers, _receipts = frozen_ledger
    ruleset = sup.cement_ruleset()
    for key in engine.surface_table_keys("cement"):
        assert ruleset.find(key) is not None and ruleset.find(key).computable, key
    out = str(tmp_path / "raw")
    generator.generate(out, ruleset=ruleset, force=True)
    blocked_token = generator.PENDING_ENGINE_PREFIX + "pci.engine.blocked"
    rows = importer.read_table(os.path.join(str(tmp_path), "truth", generator.truth_file_name("X990", 2022)))
    assert rows
    numeric = 0
    for route_id, year in [cell for cell in sorted(generator.PARTITION_PLAN.keys()) if cell[0] == "X990"]:
        for row in importer.read_table(os.path.join(str(tmp_path), "truth", generator.truth_file_name(route_id, year))):
            segment_id = row["segment_id"]
            assert row["surface_type"] == "cement"
            result = engine.compute_segment_pci(conn, segment_id, year, ruleset)
            if blockers.get(year, {}).get(segment_id, []):
                assert row["pci_truth"] == blocked_token and row["grade_truth"] == blocked_token, (segment_id, year)
                assert result.pci is None
                continue
            numeric += 1
            assert float(row["pci_truth"]) == pytest.approx(result.pci), (segment_id, year)
            assert row["grade_truth"] == result.grade, (segment_id, year)
            assert result.grade in ("优", "良", "中", "次", "差")
    assert numeric >= 5, "水泥夹具下出数的对象太少，接线断言失去意义（实际 %d）" % numeric


def test_pci_and_cement_fixtures_do_not_leak_into_shipped_paths(repo_root):
    """夹具包只多出两个 JSON 文件，内置包与演示数据不受影响（交付面红线）。"""
    from road_mqi_checker.ruleset import loader

    builtin = loader.load_file(os.path.join(loader._BUILTIN_DIR, "base-jtg5210-2018.json"))
    assert builtin.computable_coefficients() == []
    for name in ("pci-fixture-asphalt.json", "pci-fixture-cement.json"):
        with pytest.raises(Exception):
            loader.load_file(os.path.join(sup.FIXTURE_DIR, name), allow_fixture=False)
