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
    assert payload["coefficient_gate"]["open"] is False  # M0 常态：无生效系数
    assert payload["ledger_schema"]["ok"] is True


def test_selfcheck_fails_when_data_dir_missing(run_cli, tmp_path, monkeypatch):
    """数据目录找不到要落 1（降级），不能报 0 —— 否则 CI 会绿着漏掉环境缺件。"""
    monkeypatch.chdir(tmp_path)
    rc, _out, _err = run_cli(["selfcheck"], env_data_dir=False)
    assert rc == EXIT_DEGRADED


def test_placeholder_commands_return_unimplemented(run_cli):
    for argv in (
        ["import", "--file", "x.csv", "--year", "2025"],
        ["assess", "--year", "2025"],
        ["aggregate", "--year", "2025"],
        ["compare", "--from-year", "2024", "--to-year", "2025"],
        ["bench", "generate"],
        ["bench", "run"],
        ["report", "--out", "x.csv"],
    ):
        rc, _out, err = run_cli(argv)
        assert rc == EXIT_UNIMPLEMENTED, (argv, rc, err)
        assert "计划交付里程碑" in err, (argv, err)


def test_unimplemented_message_names_the_milestone(run_cli):
    _rc, _out, err = run_cli(["assess", "--year", "2025"])
    assert "M2" in err


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


def test_ruleset_show_json_marks_every_cell_uncomputable(run_cli):
    rc, out, _err = run_cli(["--json", "ruleset", "show"])
    assert rc == EXIT_OK
    rows = json.loads(out)["coefficients"]
    assert rows and all(row["computable"] is False for row in rows)


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


def test_skeleton_metric_table_is_all_unavailable():
    table = evaluation.initial_metric_table()
    assert table and all(row["state"] == evaluation.METRIC_UNAVAILABLE for row in table)
    assert all(row["value"] is None for row in table)
