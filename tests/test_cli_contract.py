"""CLI 命令面与退出码语义（定稿即锁，后续重构不漂移）。

同时锁定"四态"到退出码的映射：达标 0 / 未达标 1 / 不可判 2 / 不可用 3。
"""

import io
import json
import os
import sys

import pytest

from road_mqi_checker import cli
from road_mqi_checker.bench import evaluation
from road_mqi_checker.exit_codes import (
    EXIT_CODE_MEANINGS,
    EXIT_DEGRADED,
    EXIT_INPUT_UNUSABLE,
    EXIT_OK,
    EXIT_UNIMPLEMENTED,
)


@pytest.fixture
def run_cli(monkeypatch, repo_root):
    """在指定 data 目录下跑 CLI，返回 (rc, stdout, stderr)。"""

    def _run(argv, env_data_dir=True):
        if env_data_dir:
            monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
        else:
            monkeypatch.delenv("RMQC_DATA_DIR", raising=False)
        out, err = io.StringIO(), io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            rc = cli.main(argv)
        except SystemExit as exc:  # argparse 参数错误
            rc = exc.code if isinstance(exc.code, int) else 2
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        return rc, out.getvalue(), err.getvalue()

    return _run


def test_exit_code_meanings_are_four_and_distinct():
    assert len(EXIT_CODE_MEANINGS) == 4
    assert set(EXIT_CODE_MEANINGS) == {EXIT_OK, EXIT_DEGRADED, EXIT_INPUT_UNUSABLE, EXIT_UNIMPLEMENTED}


def test_version_and_selfcheck_succeed(run_cli):
    rc, out, _err = run_cli(["version"])
    assert rc == EXIT_OK and "road-mqi-checker" in out
    rc, out, _err = run_cli(["selfcheck"])
    assert rc == EXIT_OK, out
    assert "系数门" in out


def test_selfcheck_json_shape_is_stable(run_cli):
    rc, out, _err = run_cli(["--json", "selfcheck"])
    assert rc == EXIT_OK
    payload = json.loads(out)
    for key in ("rulesets", "coefficient_gate", "ledger_schema", "placeholders", "gui_pages", "failures"):
        assert key in payload, key
    # 系数门按"有无生效系数"说话，数值必须与内置包自身一致（不写死 0，也不写死 1）
    from road_mqi_checker.ruleset import loader

    builtin = loader.load_file(os.path.join(loader._BUILTIN_DIR, "base-jtg5210-2018.json"))
    gate = payload["coefficient_gate"]
    assert gate["active"] == len(builtin.computable_coefficients())
    assert gate["blocked"] == len(builtin.blocked_coefficients())
    assert gate["active"] + gate["blocked"] == len(builtin.coefficients)
    assert gate["open"] is (gate["active"] > 0)
    assert payload["ledger_schema"]["ok"] is True


def test_selfcheck_fails_when_data_dir_missing(run_cli, tmp_path, monkeypatch):
    """数据目录找不到要落 1（降级），不能报 0 —— 否则 CI 会绿着漏掉环境缺件。"""
    monkeypatch.chdir(tmp_path)
    rc, _out, _err = run_cli(["selfcheck"], env_data_dir=False)
    assert rc == EXIT_DEGRADED


def test_placeholder_commands_return_unimplemented(run_cli):
    """M5 之后仍未实现的命令必须返回 3 并指明里程碑（不许假成功）。

    M1 交付 `import` / `bench generate`、M2 交付 `assess`、M4 交付 `aggregate` / `compare`、
    M5 交付 `bench run`（真跑语义见 `test_m5_bench.py`），均不在此列。
    """
    for argv in (
        ["report", "--out", "x.csv"],
    ):
        rc, _out, err = run_cli(argv)
        assert rc == EXIT_UNIMPLEMENTED, (argv, rc, err)
        assert "计划交付里程碑" in err, (argv, err)


def test_unimplemented_message_names_the_milestone(run_cli):
    _rc, _out, err = run_cli(["report", "--out", "x.csv"])
    assert "M6" in err


def test_gui_command_reports_dependency_or_unimplemented(run_cli, repo_root):
    """装了 PySide6 → 3（未实现）；没装 → 1（缺可选依赖，给安装提示）。两个分支都要有明确码。"""
    from road_mqi_checker.gui import app as gui_app

    try:
        gui_app._import_qt()
        installed = True
    except Exception:
        installed = False
    rc, _out, err = run_cli(["gui"])
    assert rc == (EXIT_UNIMPLEMENTED if installed else EXIT_DEGRADED), (rc, err)
    if not installed:
        assert "[gui]" in err


def test_missing_pyside6_gives_install_hint(monkeypatch):
    """把 PySide6 标记为不可导入，验证降级路径给出 extras 提示而不是崩栈。"""
    from road_mqi_checker.errors import OptionalDependencyMissing
    from road_mqi_checker.gui import app as gui_app

    monkeypatch.setitem(sys.modules, "PySide6", None)
    with pytest.raises(OptionalDependencyMissing) as info:
        gui_app._import_qt()
    assert "pip install road-mqi-checker[gui]" in str(info.value)


def test_ruleset_list_and_show(run_cli):
    rc, out, _err = run_cli(["ruleset", "list"])
    assert rc == EXIT_OK and "base-jtg5210-2018" in out
    rc, out, _err = run_cli(["ruleset", "show"])
    assert rc == EXIT_OK and "pending" in out


def test_ruleset_show_json_reports_per_cell_computability(run_cli):
    """逐格 computable 标记必须与包内状态一致：规范来源格未拿到原文前一律 False。"""
    rc, out, _err = run_cli(["--json", "ruleset", "show"])
    assert rc == EXIT_OK
    rows = json.loads(out)["coefficients"]
    assert rows
    from road_mqi_checker.ruleset import loader

    builtin = loader.load_file(os.path.join(loader._BUILTIN_DIR, "base-jtg5210-2018.json"))
    by_key = {coef.key: coef for coef in builtin.coefficients}
    for row in rows:
        assert row["computable"] is by_key[row["key"]].computable, row["key"]
    standard_cells = [
        row["key"] for row in rows if by_key[row["key"]].basis[0].standard_id.startswith("JTG")
    ]
    assert standard_cells and all(not by_key[key].computable for key in standard_cells), (
        "有规范来源格在未见原文的情况下生效：%s" % standard_cells
    )


def test_ledger_tables_listing(run_cli):
    rc, out, _err = run_cli(["ledger", "tables"])
    assert rc == EXIT_OK
    for table in ("route", "segment", "survey", "distress", "import_receipt", "partition_change", "meta"):
        assert table in out


def test_bad_arguments_exit_two(run_cli):
    rc, _out, _err = run_cli(["nope"])
    assert rc == EXIT_INPUT_UNUSABLE
    rc, _out, _err = run_cli(["assess"])
    assert rc == EXIT_INPUT_UNUSABLE


def test_metric_state_to_exit_mapping_is_locked():
    """四态到退出码的映射是口径，改动会让 CI 门失效。"""
    assert evaluation.STATE_TO_EXIT[evaluation.METRIC_PASS] == EXIT_OK
    assert evaluation.STATE_TO_EXIT[evaluation.METRIC_FAIL] == EXIT_DEGRADED
    assert evaluation.STATE_TO_EXIT[evaluation.METRIC_INDETERMINATE] == EXIT_INPUT_UNUSABLE
    assert evaluation.STATE_TO_EXIT[evaluation.METRIC_UNAVAILABLE] == EXIT_UNIMPLEMENTED


def test_metric_table_is_four_states_with_two_paths_of_numbers():
    """M5 重写的骨架门：原先断言"全部不可用"，现在断言两通路的真实四态与实测值。

    骨架期这张表全填"不可用"（内核未实现）。M5 之后必须换成：
    内置包 = 通路存在但不出数（数值类不可判、分母 0）；夹具包 = 出数并可复算；
    一行都不许停在"不可用"上，也不许把不可判挤成达标。
    """
    table = evaluation.run()
    rows = dict((evaluation.row_key(row), row) for row in table["metrics"])
    assert len(table["metrics"]) == 2 * len(evaluation.METRICS)
    assert [row for row in table["metrics"] if row["state"] == evaluation.METRIC_UNAVAILABLE] == []

    for metric in ("rescore_drift", "contribution_order", "aggregation_consistency", "change_contribution_order"):
        row = rows["%s|%s" % (metric, evaluation.PATH_BUILTIN)]
        assert row["state"] == evaluation.METRIC_INDETERMINATE, row
        assert row["numerator"] == 0 and row["denominator"] == 0, row
        assert row["declared_indeterminate"] is True, row
    for metric in ("anomaly_recall", "anomaly_false_alarm", "byte_reproducible"):
        assert rows["%s|%s" % (metric, evaluation.PATH_BUILTIN)]["state"] == evaluation.METRIC_PASS, metric
    assert rows["grade_accuracy|%s" % evaluation.PATH_BUILTIN]["state"] == evaluation.METRIC_INDETERMINATE
    assert rows["grade_accuracy|%s" % evaluation.PATH_FIXTURE]["state"] == evaluation.METRIC_INDETERMINATE

    fixture = dict(
        (row["metric"], row)
        for row in table["metrics"]
        if row["path"] == evaluation.PATH_FIXTURE
    )
    assert fixture["rescore_drift"]["value"] == 0.0, fixture["rescore_drift"]
    assert fixture["contribution_order"]["state"] == evaluation.METRIC_PASS, fixture["contribution_order"]
    assert fixture["change_contribution_order"]["state"] == evaluation.METRIC_PASS
    assert fixture["aggregation_consistency"]["state"] == evaluation.METRIC_PASS
    assert fixture["byte_reproducible"]["state"] == evaluation.METRIC_PASS
    assert table["gate"]["exit"] == evaluation.STATE_TO_EXIT[evaluation.METRIC_PASS]
