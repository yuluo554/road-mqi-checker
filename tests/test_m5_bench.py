"""M5 基准评测：两通路四态指标、门禁语义与 README 表格同源。

双向门纪律（同 M2/M4）：
- 内置包通路必须**如实不可判**（分母 0），不许为了表格好看挤成达标；
- 夹具包通路必须**真出数并复算**，数字只说明算术与口径自洽；
- 门禁只红于"未达标 / 不可用 / 名单外新不可判"，三类都要有正证与反证。
"""

import json
import os

import pytest

from road_mqi_checker import cli, privacy
from road_mqi_checker.bench import evaluation, generator
from road_mqi_checker.exit_codes import (
    EXIT_DEGRADED,
    EXIT_INPUT_UNUSABLE,
    EXIT_OK,
    EXIT_UNIMPLEMENTED,
)
from road_mqi_checker.ledger import checks as ledger_checks

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def payload():
    """整基准跑一次：两通路 × 8 指标 = 16 行（本文件的断言都读这份实测结果）。"""
    return evaluation.run()


def rows_for(payload, path_key):
    return dict((row["metric"], row) for row in payload["metrics"] if row["path"] == path_key)


def find_row(payload, metric, path_key):
    for row in payload["metrics"]:
        if row["metric"] == metric and row["path"] == path_key:
            return row
    raise AssertionError("缺行：%s/%s" % (metric, path_key))


# ---- 指标清单本身 ----


def test_metric_vocabulary_is_consistent():
    assert set(evaluation.METRICS) == set(evaluation.METRIC_NAMES)
    assert set(evaluation.METRICS) == set(evaluation.TARGETS)
    assert len(evaluation.METRICS) == 8
    for path_key in evaluation.PATH_ORDER:
        assert path_key in evaluation.PATH_LABELS and path_key in evaluation.PATH_HONESTY


def test_declared_indeterminate_pairs_are_known_metrics_and_paths():
    for metric, path_key in evaluation.DECLARED_INDETERMINATE:
        assert metric in evaluation.METRICS, metric
        assert path_key in evaluation.PATH_ORDER, path_key


def test_expected_kind_by_issue_uses_the_check_layer_vocabulary():
    """注入类别 → 校验项的映射只能指向真实存在的校验项（否则召回分母会指向空气）。"""
    injected_issues = set(case["issue"] for case in generator.INJECTIONS)
    for issue, kind in evaluation.EXPECTED_KIND_BY_ISSUE.items():
        assert issue in injected_issues, issue
        assert kind in ledger_checks.CHECK_KINDS, "%s → %s 不在校验项词汇里" % (issue, kind)
    assert evaluation.PARTITION_ISSUE in injected_issues


# ---- 两通路各出一组，且互不顶替 ----


def test_both_paths_report_every_metric(payload):
    assert len(payload["metrics"]) == 2 * len(evaluation.METRICS)
    keys = set((row["metric"], row["path"]) for row in payload["metrics"])
    assert keys == set((m, p) for m in evaluation.METRICS for p in evaluation.PATH_ORDER)


def test_every_row_states_numerator_denominator_and_basis(payload):
    for row in payload["metrics"]:
        assert row["basis"] and row["note"], row
        assert row["state"] in evaluation.METRIC_STATES, row
        assert row["target"] == evaluation.TARGETS[row["metric"]], row
        assert row["path_label"] == evaluation.PATH_LABELS[row["path"]], row
        assert row["exit"] == evaluation.STATE_TO_EXIT[row["state"]], row
        if row["state"] == evaluation.METRIC_UNAVAILABLE:
            assert row["numerator"] is None and row["denominator"] is None, row
        else:
            assert isinstance(row["numerator"], int) and isinstance(row["denominator"], int), row


def test_builtin_numeric_metrics_are_indeterminate_with_zero_denominator(payload):
    builtin = rows_for(payload, evaluation.PATH_BUILTIN)
    for metric in ("rescore_drift", "contribution_order", "aggregation_consistency", "change_contribution_order"):
        row = builtin[metric]
        assert row["state"] == evaluation.METRIC_INDETERMINATE, row
        assert row["denominator"] == 0 and row["numerator"] == 0, row
        assert row["value"] is None, row


def test_grade_accuracy_is_indeterminate_on_both_paths(payload):
    for path_key in evaluation.PATH_ORDER:
        row = find_row(payload, "grade_accuracy", path_key)
        assert row["state"] == evaluation.METRIC_INDETERMINATE, row
        assert row["numerator"] == 0 and row["denominator"] == 0, row
        assert "独立规范等级真值 0 份" in row["note"], row


def test_indeterminate_rows_are_all_declared(payload):
    assert payload["coverage"]["undeclared_indeterminate"] == []
    declared = set(payload["coverage"]["declared_indeterminate"])
    for row in payload["metrics"]:
        if row["state"] == evaluation.METRIC_INDETERMINATE:
            assert "%s/%s" % (row["metric"], row["path"]) in declared, row
            assert row["declared_indeterminate"] is True, row


def test_path_wordings_do_not_substitute_for_each_other(payload):
    """夹具通路的实测次数不得写进内置包那行（两条通路的措辞各说各的）。"""
    builtin = rows_for(payload, evaluation.PATH_BUILTIN)
    for metric in ("rescore_drift", "contribution_order", "change_contribution_order"):
        row = builtin[metric]
        text = "%s %s" % (row["basis"], row["note"])
        assert row["path_label"] == "内置包（交付面）", row
        for number in ("214", "231", "144"):
            assert number not in text, (row["metric"], text)


def test_builtin_path_states_the_refusal_basis(payload):
    """内置包不可判的理由必须是"必需格未齐"，不是"没实现"。"""
    info = payload["paths"][evaluation.PATH_BUILTIN]
    assert info["path_gates"]["assess"] and info["path_gates"]["aggregate"] and info["path_gates"]["actions"]
    assert info["ruleset"]["blocked"] > 0
    for row in rows_for(payload, evaluation.PATH_BUILTIN).values():
        assert row["state"] != evaluation.METRIC_UNAVAILABLE, row


def test_fixture_path_measured_values(payload):
    fixture = rows_for(payload, evaluation.PATH_FIXTURE)
    assert fixture["rescore_drift"]["numerator"] == fixture["rescore_drift"]["denominator"] == 144
    assert fixture["rescore_drift"]["value"] == 0.0
    assert fixture["contribution_order"]["denominator"] == 214
    assert fixture["change_contribution_order"]["denominator"] == 231
    assert fixture["aggregation_consistency"]["denominator"] == 32
    assert fixture["byte_reproducible"]["denominator"] == 25
    for metric in ("rescore_drift", "contribution_order", "aggregation_consistency", "change_contribution_order", "byte_reproducible"):
        assert fixture[metric]["state"] == evaluation.METRIC_PASS, fixture[metric]


def test_anomaly_metrics_are_measured_on_both_paths(payload):
    for path_key in evaluation.PATH_ORDER:
        recall = find_row(payload, "anomaly_recall", path_key)
        alarm = find_row(payload, "anomaly_false_alarm", path_key)
        assert recall["denominator"] == 19 and recall["numerator"] == 19, recall
        assert recall["value"] == 1.0, recall
        assert alarm["numerator"] == 0 and alarm["denominator"] == 30, alarm
        assert alarm["value"] == 0.0, alarm


def test_blocked_objects_are_not_silently_dropped_from_denominators(payload):
    """复算误差的分母只计出数格，但同一行必须报出拒算格数（令牌与拒算相符 24/24 或 168/168）。"""
    for path_key in evaluation.PATH_ORDER:
        row = find_row(payload, "rescore_drift", path_key)
        assert "真值令牌与台账拒算相符" in row["note"], row
        assert "拒算对象不混进误差分母" in row["note"], row


# ---- 门禁 ----


def test_gate_is_green_when_only_declared_indeterminate(payload):
    assert payload["gate"]["exit"] == EXIT_OK
    assert payload["gate"]["issues"] == []
    assert payload["coverage"]["by_state"][evaluation.METRIC_UNAVAILABLE] == 0


def test_gate_reds_on_failed_metric():
    rows = [
        {
            "metric": "anomaly_recall",
            "name": evaluation.METRIC_NAMES["anomaly_recall"],
            "path": evaluation.PATH_FIXTURE,
            "path_label": evaluation.PATH_LABELS[evaluation.PATH_FIXTURE],
            "state": evaluation.METRIC_FAIL,
            "numerator": 9,
            "denominator": 19,
            "note": "漏报 10 例",
            "declared_indeterminate": False,
        }
    ]
    result = evaluation.gate(rows)
    assert result["exit"] == EXIT_DEGRADED == evaluation.STATE_TO_EXIT[evaluation.METRIC_FAIL]
    assert result["triggered_by"] == evaluation.METRIC_FAIL
    assert "anomaly_recall" in result["issues"][0]


def test_gate_reds_on_undeclared_indeterminate():
    """名单外的新不可判按数据门事故处理（2）：分母为 0 通常是有对象被悄悄摘掉。"""
    rows = [
        {
            "metric": "anomaly_recall",
            "name": evaluation.METRIC_NAMES["anomaly_recall"],
            "path": evaluation.PATH_BUILTIN,
            "path_label": evaluation.PATH_LABELS[evaluation.PATH_BUILTIN],
            "state": evaluation.METRIC_INDETERMINATE,
            "numerator": 0,
            "denominator": 0,
            "note": "期望集没推出来",
            "declared_indeterminate": False,
        },
        {
            "metric": "grade_accuracy",
            "name": evaluation.METRIC_NAMES["grade_accuracy"],
            "path": evaluation.PATH_FIXTURE,
            "path_label": evaluation.PATH_LABELS[evaluation.PATH_FIXTURE],
            "state": evaluation.METRIC_INDETERMINATE,
            "numerator": 0,
            "denominator": 0,
            "note": "名单内的不可判，不红",
            "declared_indeterminate": True,
        },
    ]
    result = evaluation.gate(rows)
    assert result["exit"] == EXIT_INPUT_UNUSABLE
    assert len(result["issues"]) == 1 and "anomaly_recall" in result["issues"][0]


def test_gate_reds_on_unavailable_path():
    rows = [
        {
            "metric": "contribution_order",
            "name": "扣分贡献项排序一致性",
            "path": evaluation.PATH_FIXTURE,
            "path_label": "夹具包（数值通路）",
            "state": evaluation.METRIC_UNAVAILABLE,
            "numerator": None,
            "denominator": None,
            "note": "夹具包不在通路上",
            "declared_indeterminate": False,
        }
    ]
    assert evaluation.gate(rows)["exit"] == EXIT_UNIMPLEMENTED


def test_gate_precedence_prefers_failed_over_unavailable():
    rows = [
        {
            "metric": "contribution_order",
            "name": "x",
            "path": evaluation.PATH_FIXTURE,
            "path_label": "x",
            "state": evaluation.METRIC_UNAVAILABLE,
            "numerator": None,
            "denominator": None,
            "note": "x",
            "declared_indeterminate": False,
        },
        {
            "metric": "anomaly_recall",
            "name": "x",
            "path": evaluation.PATH_BUILTIN,
            "path_label": "x",
            "state": evaluation.METRIC_FAIL,
            "numerator": 0,
            "denominator": 19,
            "note": "x",
            "declared_indeterminate": False,
        },
    ]
    assert evaluation.gate(rows)["exit"] == EXIT_DEGRADED


def test_row_builder_refuses_over_claimed_wording():
    """结论纪律在指标行构造时就把关：出现"已确认/已核实"这类词即拒绝（导出路径同一道门）。"""
    with pytest.raises(privacy.PrivacyViolation):
        evaluation._row(
            "rescore_drift",
            evaluation.PATH_FIXTURE,
            1,
            1,
            evaluation.METRIC_PASS,
            0.0,
            "判据",
            "扣分表已与原文核对并已确认",
        )


# ---- 通路拿不到的那一档（不可用）----


def test_missing_fixture_pack_reports_unavailable(monkeypatch):
    monkeypatch.setattr(evaluation, "find_fixture_pack", lambda name, start=None: None)
    assert evaluation.merged_fixture_ruleset() is None
    result = evaluation.run(paths=(evaluation.PATH_FIXTURE,))
    assert len(result["metrics"]) == len(evaluation.METRICS)
    for row in result["metrics"]:
        assert row["state"] == evaluation.METRIC_UNAVAILABLE, row
        assert "夹具包" in row["note"] and "不可用" in row["note"], row
    assert result["gate"]["exit"] == EXIT_UNIMPLEMENTED
    assert result["coverage"]["by_state"][evaluation.METRIC_UNAVAILABLE] == len(evaluation.METRICS)


def test_unknown_path_is_input_error():
    with pytest.raises(ValueError):
        evaluation.build_context("nope")


def test_run_does_not_leave_scratch_in_repo(payload):
    assert payload["scratch_dir"] is None
    assert os.path.isdir(os.path.join(REPO, ".tmp_bench")) is False


# ---- CLI 接通 ----


def test_cli_bench_run_real_and_json_agree(capsys, monkeypatch):
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(REPO, "data"))
    assert cli.main(["bench", "run"]) == EXIT_OK
    text = capsys.readouterr().out
    assert "基准评测：" in text and "退出码 0" in text
    assert cli.main(["--json", "bench", "run"]) == EXIT_OK
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["milestone"] == "M5"
    for key in ("paths", "metrics", "coverage", "gate"):
        assert key in data, key
    assert data["gate"]["exit"] == EXIT_OK
    assert len(data["metrics"]) == 16
    # 两个命令面必须说同一份出数判据：`selfcheck` 的 path_gates 与 `bench run` 逐路径相等，
    # 都是 `generator` 的必需格函数，不许评测面自建第二套判据（plan/02 §9 第 23/28/32 条）。
    assert cli.main(["--json", "selfcheck"]) == EXIT_OK
    selfcheck = json.loads(capsys.readouterr().out)
    gates = dict((name, info["pending_keys"]) for name, info in selfcheck["path_gates"].items())
    assert gates == data["paths"]["builtin"]["path_gates"], gates
    assert all(selfcheck["path_gates"][name]["can_emit_numbers"] is False for name in gates)


@pytest.mark.parametrize("metric", evaluation.METRICS)
def test_every_metric_has_both_a_positive_and_a_negative_denominator_proof(metric):
    """每条指标都要有"分子分母都对"的正证与"分母为 0 如实报不可判"的反证。

    真实通路上的正证见 `test_fixture_path_measured_values`，反证见
    `test_builtin_numeric_metrics_are_indeterminate_with_zero_denominator`；
    这里再把判据函数本身的两端钉住（召回 / 误报 / 位级一致在两通路都出数，
    真实样本里没有"分母为 0"的那一档，只能在判据层证它确实会报不可判）。
    """
    assert evaluation._ratio_state(metric, 0, 0) == evaluation.METRIC_INDETERMINATE, metric
    if metric == "anomaly_false_alarm":
        # 越低越好：零误报才是达标；误报一条都不许按"相符率"算成满分
        assert evaluation._ratio_state(metric, 0, 30) == evaluation.METRIC_PASS, metric
        assert evaluation._ratio_state(metric, 1, 30) == evaluation.METRIC_FAIL, metric
    elif metric in evaluation.RATIO_TARGETS:
        assert evaluation._ratio_state(metric, 7, 7) == evaluation.METRIC_PASS, metric
        assert evaluation._ratio_state(metric, 0, 30) == evaluation.METRIC_FAIL, metric
    else:
        # rescore_drift / aggregation_consistency 没有阈值：相符即达标，
        # 它们的"分母为 0 → 不可判"分支由内置包真实行覆盖
        assert evaluation._ratio_state(metric, 7, 7) == evaluation.METRIC_PASS, metric


def test_byte_state_covers_all_three_branches():
    """位级一致走自己的判据：没文件可比 = 不可判，全同 = 达标，有一份不同 = 未达标。"""
    assert evaluation._byte_state(0, 0) == evaluation.METRIC_INDETERMINATE
    assert evaluation._byte_state(25, 25) == evaluation.METRIC_PASS
    assert evaluation._byte_state(24, 25) == evaluation.METRIC_FAIL


def test_byte_metric_is_not_a_ratio_of_unknown_denominator(payload):
    """位级一致这一项用"文件数 / 文件数"，不出一个看着像比率的 1.00 值（值列留空）。"""
    row = find_row(payload, "byte_reproducible", evaluation.PATH_BUILTIN)
    assert row["value"] is None and row["state"] == evaluation.METRIC_PASS, row


def test_cli_bench_run_refuses_other_seed(capsys, monkeypatch):
    """基准定义在冻结演示数据上：换 seed 要先生成数据并单独提交，这里落 2 而不是给个假数。"""
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(REPO, "data"))
    assert cli.main(["bench", "run", "--seed", "777"]) == EXIT_INPUT_UNUSABLE
    assert "冻结演示数据" in capsys.readouterr().err


def test_bench_run_json_is_byte_identical_across_cold_processes():
    """两次进程冷启动的 `--json` 输出必须逐字节一致（落盘产物无时间戳这条纪律的评测面）。"""
    import subprocess
    import sys

    env = dict(os.environ)
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": os.path.join(REPO, "src"),
            "RMQC_DATA_DIR": os.path.join(REPO, "data"),
        }
    )
    runs = []
    for _attempt in range(2):
        done = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "road_mqi_checker", "--json", "bench", "run"],
            cwd=REPO,
            env=env,
            capture_output=True,
        )
        assert done.returncode == EXIT_OK, done.stderr.decode("utf-8", "replace")
        runs.append(done.stdout)
    assert runs[0] == runs[1], "两次冷启动的 --json 输出不一致"
    assert b"timestamp" not in runs[0].lower()


# ---- README 评测表由命令生成 ----


def test_readme_metric_table_is_generated_from_bench_run(payload):
    with open(os.path.join(REPO, "README.md"), "r", encoding="utf-8") as handle:
        text = handle.read()
    begin, end = evaluation.TABLE_BEGIN, evaluation.TABLE_END
    assert text.count(begin) == 1 and text.count(end) == 1, "README 评测表标记重复"

    def inner(source):
        return source.split(begin, 1)[1].split(end, 1)[0].strip("\n")

    rendered = inner(evaluation.render_readme_block(payload))
    assert inner(text) == rendered, "README 评测表与 bench run 输出不一致"


def test_readme_table_has_eight_rows(payload):
    rows = evaluation.readme_table(payload)
    assert len(rows) == 8
    assert all(row.startswith("| ") and row.endswith(" |") for row in rows)
    names = [row.split("|")[1].strip() for row in rows]
    assert names == [evaluation.METRIC_NAMES[metric] for metric in evaluation.METRICS]


def test_readme_table_keeps_both_path_labels_in_every_row(payload):
    for row in evaluation.readme_table(payload):
        assert "内置包（交付面）" in row and "夹具包（数值通路）" in row, row
        assert "不可判（分母为 0）" in row or "达标" in row, row
