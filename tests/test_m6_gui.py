"""M6 桌面壳守门：七页签接通同一 CLI 内核，GUI 只转发、不另起第二套行为。

前一半测试**不需要 Qt**（页签结构、argv 映射、内核转发对账），所以零 GUI 依赖的机器
也能验到交付层的结构；后一半标 `@pytest.mark.gui`，需要 PySide6 时真建窗口（offscreen）。
"""

import io
import os
import contextlib

import pytest

from road_mqi_checker import cli
from road_mqi_checker.gui import app as gui_app

MARKER = pytest.mark.gui


def _qt_available():
    try:
        gui_app._import_qt()
    except Exception:
        return False
    return True


NEEDS_QT = pytest.mark.skipif(not _qt_available(), reason="缺 PySide6（pip install road-mqi-checker[gui]）")


# ---------------------------------------------------------------- 结构（无需 Qt）

def test_page_titles_are_the_seven_business_steps():
    assert gui_app.PAGE_TITLES == (
        "台账与导入",
        "路面 PCI 评定",
        "MQI 汇总与等级",
        "年对比与优先序",
        "基准评测",
        "依据登记与规则集",
        "导出与声明",
    )


def test_page_map_is_titles_paired_with_kernel_commands():
    pairs = gui_app.build_page_map()
    assert len(pairs) == len(gui_app.PAGE_TITLES) == len(gui_app.PAGE_COMMANDS)
    assert [title for title, _ in pairs] == list(gui_app.PAGE_TITLES)
    assert [command for _, command in pairs] == list(gui_app.PAGE_COMMANDS)


def test_specs_match_titles_in_order():
    assert [spec.title for spec in gui_app.PAGE_SPECS] == list(gui_app.PAGE_TITLES)


def test_command_tokens_agree_with_page_map():
    """页面上写的命令与 spec 真发的 argv 前缀必须同源（防"显示一条、执行另一条"）。"""
    for spec, (_title, command) in zip(gui_app.PAGE_SPECS, gui_app.build_page_map()):
        assert command.split() == ["rmqc"] + list(spec.command)


def test_spec_flags_all_exist_in_the_cli_parser():
    """GUI 不许发明内核没有的参数：每个 flag 都要能在 `build_parser` 里找到。"""
    parser = cli.build_parser()
    options = set()
    for action in parser._actions:
        options.update(action.option_strings)
    subparsers = next(action for action in parser._actions if isinstance(action, cli.argparse._SubParsersAction))
    for _name, sub in subparsers.choices.items():
        for action in sub._actions:
            options.update(action.option_strings)
    for spec in gui_app.PAGE_SPECS:
        for flag, field_name in spec.args:
            assert flag in options, "%s 页要发 %s，但内核没有这个参数" % (spec.title, flag)
            assert any(field_name == field.name for field in spec.fields), "%s 缺字段 %s" % (spec.title, field_name)


def test_default_values_cover_declared_fields():
    for spec in gui_app.PAGE_SPECS:
        values = gui_app.default_values(spec)
        assert set(values) == set(field.name for field in spec.fields)
        assert gui_app.spec_for(spec.title) is spec
    with pytest.raises(KeyError):
        gui_app.spec_for("不存在的页签")


def test_build_argv_omits_empty_and_keeps_db_first():
    spec = gui_app.spec_for("路面 PCI 评定")
    assert gui_app.build_argv(spec, {"db": "", "year": "2022", "segment": ""}) == ["assess", "--year", "2022"]
    assert gui_app.build_argv(spec, {"db": "ledger.sqlite", "year": "2022", "segment": "S99-A1"}) == [
        "--db",
        "ledger.sqlite",
        "assess",
        "--year",
        "2022",
        "--segment",
        "S99-A1",
    ]


def test_build_argv_treats_flag_fields_as_booleans():
    spec = gui_app.spec_for("台账与导入")
    base = {"db": "", "file": "S99-2022.csv", "year": "2022", "data_class": "SYNTHETIC", "dry_run": False}
    assert "--dry-run" not in gui_app.build_argv(spec, base)
    assert "--dry-run" in gui_app.build_argv(spec, dict(base, dry_run=True))


@pytest.mark.parametrize("title", gui_app.PAGE_TITLES)
def test_default_argv_parses_with_the_real_parser(title):
    """页面默认参数拼出的 argv 必须能被内核 argparse 接受（不产生"GUI 点了才报错"）。"""
    spec = gui_app.spec_for(title)
    parser = cli.build_parser()
    values = gui_app.default_values(spec)
    if not values.get("file"):
        values["file"] = "S99-2022.csv"  # 文件路径必须由用户选，这里只补"已选"这个事实
    argv = gui_app.build_argv(spec, values)
    args = parser.parse_args(argv)
    assert args.command == spec.command[0]


# ---------------------------------------------------------------- 只转发（无需 Qt）

def test_run_kernel_is_the_same_code_path_as_the_cli(monkeypatch, repo_root):
    """GUI 的取数就是 `cli.main`：退出码与输出文本必须与命令行逐字一致。"""
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    rc_gui, text_gui = gui_app.run_kernel(["version"])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc_cli = cli.main(["version"])
    assert rc_gui == rc_cli == 0
    assert text_gui == out.getvalue()
    assert "road-mqi-checker" in text_gui


def test_run_kernel_reports_degraded_exit_for_blocked_assess(monkeypatch, repo_root, tmp_path):
    """内置系数包下评定全 blocked → GUI 显示退出码 1，不改判成"成功"。"""
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    db = str(tmp_path / "ledger.sqlite")
    assert gui_app.run_kernel(["--db", db, "ledger", "init"])[0] == 0
    rc, _text = gui_app.run_kernel(
        ["--db", db, "import", "--file", os.path.join(repo_root, "data", "raw", "S99-2022.csv"), "--year", "2022"]
    )
    assert rc in (0, 1)
    rc, text = gui_app.run_kernel(["--db", db, "assess", "--year", "2022"])
    assert rc == 1 and "blocked" in text


def test_run_kernel_turns_missing_required_args_into_a_readable_exit(monkeypatch, repo_root):
    """导入页留空文件路径 → 内核 argparse 口径退出 2，页面拿到原因文本而不是崩栈。"""
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    rc, text = gui_app.run_kernel(["import", "--year", "2022"])
    assert rc == 2
    assert "参数不完整" in text


def test_run_kernel_survives_unknown_command(monkeypatch, repo_root):
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    rc, text = gui_app.run_kernel(["no-such-command"])
    assert rc in (1, 2) and text


# ---------------------------------------------------------------- 真窗口（需 Qt）

@pytest.fixture(scope="module")
def qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets

    yield QtWidgets


@pytest.fixture(scope="module")
def qapp(qt):
    return qt.QApplication.instance() or qt.QApplication([])


@MARKER
@NEEDS_QT
def test_window_has_seven_pages_with_the_declared_titles(qt, qapp):
    window = gui_app.build_window(qt, on_run=lambda spec, values: (0, "stub"))
    assert window.tab_count == len(gui_app.PAGE_TITLES)
    labels = [window.tabs.tabText(index) for index in range(window.tab_count)]
    assert labels == list(gui_app.PAGE_TITLES)
    assert window.disclaimer_text


@MARKER
@NEEDS_QT
def test_page_button_forwards_exactly_build_argv(qt, qapp):
    """注入假 runner：页面必须把 `build_argv(spec, 表单值)` 原样交给内核，不改参数、不自算。"""
    seen = []

    def fake_runner(spec, values):
        seen.append((spec.title, gui_app.build_argv(spec, values)))
        return 1, "退出码 1（降级完成）"

    window = gui_app.build_window(qt, on_run=fake_runner)
    for page in window.pages:
        page.run_once()
    assert [title for title, _argv in seen] == list(gui_app.PAGE_TITLES)
    by_title = dict(seen)
    assert by_title["路面 PCI 评定"] == ["assess", "--year", "2022"]
    assert by_title["MQI 汇总与等级"] == ["aggregate", "--year", "2022", "--level", "route"]
    assert by_title["年对比与优先序"] == ["compare", "--from-year", "2022", "--to-year", "2023"]
    assert by_title["基准评测"] == ["bench", "run"]
    assert by_title["依据登记与规则集"] == ["ruleset", "list"]
    assert "--db" not in by_title["导出与声明"]  # 台账留空即内存库，GUI 不猜路径
    assert gui_app.PAGE_COMMANDS[6].split()[1:] == ["report"]


@MARKER
@NEEDS_QT
def test_probe_returns_zero_and_each_page_really_called_the_kernel(monkeypatch, repo_root):
    """`--probe` 是交付探针：真建窗口、真跑七页内核，返回 0 才算 GUI 活着。"""
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    calls = []
    original = gui_app.run_kernel

    def spy(argv):
        rc, text = original(argv)
        calls.append((list(argv), rc))
        return rc, text

    monkeypatch.setattr(gui_app, "run_kernel", spy)
    assert gui_app.main(["--probe"]) == 0
    assert calls[0][0] == ["version"]
    assert len(calls) == 1 + len(gui_app.PAGE_TITLES)


@MARKER
@NEEDS_QT
def test_probe_refuses_when_a_page_produces_no_output(monkeypatch, repo_root, tmp_path):
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    monkeypatch.setattr(gui_app, "run_kernel", lambda argv: (0, ""))
    assert gui_app.main(["--probe"]) == 1
