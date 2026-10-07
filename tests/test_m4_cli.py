"""M4 命令面：`aggregate` / `compare` 从"返回 3"转真跑（退出码、--json 结构、口径声明）。

内置包下如实降级（1），台账里没有对应年度时落 2；数值通路的正证在
`test_m4_mqi.py` / `test_m4_strategy.py`（夹具包），这里锁的是命令面与内核不漂移。
"""

import io
import json
import os
import sys

import pytest

from road_mqi_checker import cli
from road_mqi_checker.exit_codes import EXIT_DEGRADED, EXIT_INPUT_UNUSABLE, EXIT_OK
from road_mqi_checker.ruleset import loader

BUILTIN_COMPUTABLE = None


@pytest.fixture
def run_cli(monkeypatch, repo_root):
    def _run(argv, db_path=None):
        monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
        full = (["--db", db_path] if db_path else []) + argv
        out, err = io.StringIO(), io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            rc = cli.main(full)
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 2
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        return rc, out.getvalue(), err.getvalue()

    return _run


@pytest.fixture
def loaded_ledger(tmp_path, run_cli, repo_root):
    """按 README 的命令顺序把两个年度导进同一个台账（真实通路，不自建第二套取数）。"""
    db_path = str(tmp_path / "ledger.sqlite")
    rc, _out, err = run_cli(["ledger", "init"], db_path=db_path)
    assert rc == EXIT_OK, err
    raw_dir = os.path.join(repo_root, "data", "raw")
    for year in (2022, 2023):
        path = os.path.join(raw_dir, "S99-%d.csv" % year)
        rc, _out, err = run_cli(["import", "--file", path, "--year", str(year)], db_path=db_path)
        # 2022 有注入的重复导入行（拒入 → 1），2023 是干净年度（0）；两者都不该失败
        assert rc in (EXIT_OK, EXIT_DEGRADED), (year, rc, err)
    return db_path


def builtin():
    return loader.load_file(os.path.join(loader._BUILTIN_DIR, "base-jtg5210-2018.json"))


# ---- aggregate ----


def test_aggregate_now_runs_and_degrades_instead_of_returning_three(loaded_ledger, run_cli):
    rc, out, err = run_cli(["aggregate", "--year", "2022"], db_path=loaded_ledger)
    assert rc == EXIT_DEGRADED, (rc, err)
    assert "MQI 汇总" in out and "blocked" in out
    assert "不冒充完整 MQI" in out


@pytest.mark.parametrize("level", ["segment", "route", "network"])
def test_aggregate_all_three_levels_are_blocked_under_builtin(loaded_ledger, run_cli, level):
    rc, out, _err = run_cli(["--json", "aggregate", "--year", "2022", "--level", level], db_path=loaded_ledger)
    assert rc == EXIT_DEGRADED
    payload = json.loads(out)
    ruleset = builtin()
    assert payload["level"] == level
    assert payload["counts"]["blocked"] == len(payload["results"]) > 0
    assert payload["counts"]["ok"] == 0
    for row in payload["results"]:
        assert row["mqi"] is None and row["grade"] is None
        assert row["weighted_length_m"] is None
        # 拒算原因来自上游 PCI 的系数门（PCI 没数，汇总就不碰加权），必须逐格点名
        assert "未进入评定路径" in row["blocked_reason"], row["blocked_reason"]
        assert "pending" in row["blocked_reason"]
    # 出数判据 = 必需格全生效（§9 第 23 条），不是"本包生效了几格"
    assert sorted(payload["pending_keys"]) == sorted(payload["required_keys"])
    assert ruleset.summary()["computable"] > 0, "内置包有生效格也不该让汇总出数"


def test_aggregate_json_carries_the_priority_list_with_reasons(loaded_ledger, run_cli):
    rc, out, _err = run_cli(["--json", "aggregate", "--year", "2022"], db_path=loaded_ledger)
    assert rc == EXIT_DEGRADED
    payload = json.loads(out)
    rows = payload["priority_list"]
    assert len(rows) == 4, "对策清单必须逐个列出进入评定路径的对象（含拒算项）"
    for row in rows:
        assert row["status"] == "blocked"
        assert row["action_class"] is None and row["clause"] == ""
        assert "action_rule.maintenance_trigger" in row["blocked_reason"]
    assert all(row["pci"] is None for row in rows)


def test_aggregate_counts_are_the_same_three_states_assess_uses(loaded_ledger, run_cli):
    _rc, assess_out, _e = run_cli(["--json", "assess", "--year", "2022"], db_path=loaded_ledger)
    _rc, agg_out, _e = run_cli(["--json", "aggregate", "--year", "2022", "--level", "segment"], db_path=loaded_ledger)
    assert json.loads(agg_out)["counts"]["blocked"] == json.loads(assess_out)["counts"]["blocked"]


def test_aggregate_without_rows_for_that_year_is_input_unavailable(loaded_ledger, run_cli):
    rc, _out, err = run_cli(["aggregate", "--year", "2031"], db_path=loaded_ledger)
    assert rc == EXIT_INPUT_UNUSABLE, (rc, err)


def test_aggregate_network_level_reports_one_object_per_year(loaded_ledger, run_cli):
    rc, out, _err = run_cli(["--json", "aggregate", "--year", "2022", "--level", "network"], db_path=loaded_ledger)
    payload = json.loads(out)
    assert len(payload["results"]) == 1
    assert payload["results"]
    assert payload["results"][0]["object_id"] == "network" and payload["results"][0]["status"] == "blocked"


# ---- compare ----


def test_compare_now_runs_and_refuses_numbers_under_builtin(loaded_ledger, run_cli):
    rc, out, err = run_cli(["compare", "--from-year", "2022", "--to-year", "2023"], db_path=loaded_ledger)
    assert rc == EXIT_DEGRADED, (rc, err)
    assert "年对比 2022→2023" in out
    assert "PCI 未出数" in out


def test_compare_json_lists_every_segment_seen_in_either_year(loaded_ledger, run_cli):
    rc, out, _err = run_cli(
        ["--json", "compare", "--from-year", "2022", "--to-year", "2023"], db_path=loaded_ledger
    )
    assert rc == EXIT_DEGRADED
    payload = json.loads(out)
    assert payload["year_from"] == 2022 and payload["year_to"] == 2023
    assert payload["results"]
    assert any(row["status"] in ("blocked", "uncomparable") for row in payload["results"])
    for row in payload["results"]:
        assert row["delta"] is None and row["deterioration_rate_per_year"] is None
        assert row["top_contributors"] == []
    counts = payload["counts"]
    assert sum(counts.values()) == len(payload["results"])


def test_compare_single_segment_filter(loaded_ledger, run_cli):
    rc, out, _err = run_cli(
        ["--json", "compare", "--from-year", "2022", "--to-year", "2023", "--segment", "S99-A1"],
        db_path=loaded_ledger,
    )
    assert rc == EXIT_DEGRADED
    payload = json.loads(out)
    assert [row["segment_id"] for row in payload["results"]] == ["S99-A1"]


def test_compare_without_two_years_of_rows_is_input_unavailable(loaded_ledger, run_cli):
    rc, _out, err = run_cli(["compare", "--from-year", "2022", "--to-year", "2029"], db_path=loaded_ledger)
    assert rc == EXIT_INPUT_UNUSABLE, (rc, err)


def test_selfcheck_reports_path_gates_by_required_cells(run_cli):
    """selfcheck 的对外措辞也必须按"必需格"说话（§9 第 23 条）：生效 1 格 ≠ 某条路径可出数。"""
    rc, out, _err = run_cli(["--json", "selfcheck"])
    assert rc == EXIT_OK
    gates = json.loads(out)["path_gates"]
    assert set(gates) == {"assess", "aggregate", "actions"}
    for name, gate in gates.items():
        assert gate["can_emit_numbers"] is (len(gate["pending_keys"]) == 0), name
    assert sorted(gates["aggregate"]["pending_keys"]) == ["grade_threshold.mqi", "mqi_weight.pavement"]
    assert gates["actions"]["pending_keys"] == ["action_rule.maintenance_trigger"]
    assert all(gate["can_emit_numbers"] is False for gate in gates.values())

    _rc, text, _e = run_cli(["selfcheck"])
    assert "出数判据" in text and "生效格数不等于可出数" in text


def test_two_cold_runs_of_aggregate_and_compare_are_byte_identical(loaded_ledger, run_cli):
    """确定性：同一台账两次冷跑，--json 输出逐字节一致（M2 的门延续到 M4 的两个命令）。"""
    for argv in (["--json", "aggregate", "--year", "2022"], ["--json", "compare", "--from-year", "2022", "--to-year", "2023"]):
        rc_a, out_a, _ea = run_cli(argv, db_path=loaded_ledger)
        rc_b, out_b, _eb = run_cli(argv, db_path=loaded_ledger)
        assert (rc_a, out_a) == (rc_b, out_b), argv
