"""桌面壳（模块交付层，M6 转真）。

页签结构 = 业务链条顺序（导入→评定→汇总→对比→基准→依据→导出）。
GUI **只转发**：每个页面上的"运行内核"按钮走的都是 `road_mqi_checker.cli.main(argv)`，
不在此模块里重算任何数字、不自建第二套取数通路，所以 GUI 里看到的值与命令行里逐字一致。
PySide6 走惰性导入 —— 缺依赖时给出 extras 安装提示并降级退出（退出码 1），不崩栈；
基准评测与 CLI 通路必须能在零 GUI 依赖的机器上跑完。
"""

import contextlib
import io
import os
import sys
from collections import namedtuple

from road_mqi_checker import cli
from road_mqi_checker.errors import OptionalDependencyMissing, RmqcError
from road_mqi_checker.exit_codes import EXIT_DEGRADED, EXIT_OK
from road_mqi_checker.report import disclaimer

MODULE_KEY = "road_mqi_checker.gui.app"
MILESTONE = "M6"

#: 页签顺序 = 业务链条顺序（导入→评定→汇总→对比→基准→依据→导出）
PAGE_TITLES = (
    "台账与导入",
    "路面 PCI 评定",
    "MQI 汇总与等级",
    "年对比与优先序",
    "基准评测",
    "依据登记与规则集",
    "导出与声明",
)

#: 页签 → 内核命令（`rmqc` 之后的子命令串，用于对账与展示）
PAGE_COMMANDS = (
    "rmqc import",
    "rmqc assess",
    "rmqc aggregate",
    "rmqc compare",
    "rmqc bench run",
    "rmqc ruleset list",
    "rmqc report",
)

#: 所有页面共享的台账参数（全局 `--db`，省略即内存库）

Field = namedtuple("Field", "name label default kind choices")
# kind: text / int / choice / flag
PageSpec = namedtuple("PageSpec", "title command args fields")


def _field(name, label, default="", kind="text", choices=()):
    return Field(name, label, default, kind, tuple(choices))


DB_FIELD = _field("db", "台账 SQLite 路径（留空 = 内存库，不落盘）", "")


#: 每个页面的参数表单 + 对应的内核 argv 模板（flag, 字段名）。
#: 这里只声明"传哪些参数"，参数语义与校验全在 `cli.build_parser` 那一侧。
PAGE_SPECS = (
    PageSpec(
        "台账与导入",
        ("import",),
        (("--file", "file"), ("--year", "year"), ("--data-class", "data_class"), ("--dry-run", "dry_run")),
        (
            DB_FIELD,
            _field("file", "年度检测表 CSV 路径", "", "text"),
            _field("year", "年度", "2022", "int"),
            _field("data_class", "数据类别", "SYNTHETIC", "choice", ("SYNTHETIC", "user")),
            _field("dry_run", "只预检不落库", False, "flag"),
        ),
    ),
    PageSpec(
        "路面 PCI 评定",
        ("assess",),
        (("--year", "year"), ("--segment", "segment")),
        (DB_FIELD, _field("year", "年度", "2022", "int"), _field("segment", "路段号（留空 = 全部）", "", "text")),
    ),
    PageSpec(
        "MQI 汇总与等级",
        ("aggregate",),
        (("--year", "year"), ("--level", "level")),
        (
            DB_FIELD,
            _field("year", "年度", "2022", "int"),
            _field("level", "汇总层级", "route", "choice", ("segment", "route", "network")),
        ),
    ),
    PageSpec(
        "年对比与优先序",
        ("compare",),
        (("--from-year", "year_from"), ("--to-year", "year_to"), ("--segment", "segment")),
        (
            DB_FIELD,
            _field("year_from", "基准年度", "2022", "int"),
            _field("year_to", "对比年度", "2023", "int"),
            _field("segment", "路段号（留空 = 全部）", "", "text"),
        ),
    ),
    PageSpec(
        "基准评测",
        ("bench", "run"),
        (("--seed", "seed"),),
        (DB_FIELD, _field("seed", "留空即冻结基准 seed（非默认值按内核口径退出 2）", "", "int")),
    ),
    PageSpec(
        "依据登记与规则集",
        ("ruleset", "list"),
        (),
        (_field("note", "系数核对状态与依据条款登记在 data/README.md 登记表，逐格可回指原文行号", "", "note"),),
    ),
    PageSpec(
        "导出与声明",
        ("report",),
        (
            ("--year", "year"),
            ("--scope", "scope"),
            ("--level", "level"),
            ("--format", "format"),
            ("--out", "out"),
            ("--from-year", "year_from"),
        ),
        (
            DB_FIELD,
            _field("year", "年度", "2022", "int"),
            _field("scope", "导出内容", "assessment", "choice", ("assessment", "plan")),
            _field("level", "汇总层级", "route", "choice", ("segment", "route", "network")),
            _field("format", "格式", "md", "choice", ("csv", "md", "docx")),
            _field("out", "导出文件名", "report.md", "text"),
            _field("year_from", "变化率基准年度（留空 = 不出变化率）", "", "int"),
        ),
    ),
)


def build_page_map():
    # type: () -> list
    """页签 → 对应内核命令，GUI 只做转发（测试可不依赖 Qt 直接对账）。"""
    return list(zip(PAGE_TITLES, PAGE_COMMANDS))


def spec_for(title):
    # type: (str) -> PageSpec
    for spec in PAGE_SPECS:
        if spec.title == title:
            return spec
    raise KeyError("没有页签 %r，现有页签：%s" % (title, "/".join(PAGE_TITLES)))


def default_values(spec):
    # type: (PageSpec) -> dict
    return dict((field.name, field.default) for field in spec.fields)


def build_argv(spec, values):
    # type: (PageSpec, dict) -> list
    """页面参数 → CLI argv。空值一律不传（交给内核的默认值与校验），不做本地猜测。"""
    argv = []
    db = (values.get("db") or "").strip()
    if db:
        argv.extend(["--db", db])
    argv.extend(spec.command)
    for flag, name in spec.args:
        value = values.get(name)
        if isinstance(value, bool):
            if value:
                argv.append(flag)
            continue
        if value is None or str(value).strip() == "":
            continue
        argv.extend([flag, str(value).strip()])
    return argv


def run_kernel(argv):
    # type: (list) -> tuple
    """把参数交给同一个 CLI 内核，收回（退出码, 文本）。

    这里刻意调 `cli.main` 而不是引擎函数：GUI 与命令行走的是同一条码路，
    退出码语义（0/1/2/3）也直接显示在页面上，不另起"GUI 专用成功判定"。
    """
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv))
    except SystemExit as exc:  # argparse 参数错误的既有口径（与 CLI 契约测试同一取法）
        rc = exc.code if isinstance(exc.code, int) else 2
        err.write("参数不完整：该命令的必填项未填（按内核 argparse 口径退出）\n")
    except Exception as exc:  # noqa: BLE001  （桌面壳不能因内核异常整窗消失）
        rc = EXIT_DEGRADED
        err.write("内核异常：%s: %s\n" % (exc.__class__.__name__, exc))
    text = out.getvalue()
    error_text = err.getvalue()
    if error_text:
        text = (text + "\n" + error_text) if text else error_text
    return rc, text


def _import_qt():
    try:
        from PySide6 import QtWidgets  # noqa: F401  （惰性导入：仅交付层需要）
    except ImportError as exc:
        raise OptionalDependencyMissing("PySide6", "gui")
    return QtWidgets


def build_window(QtWidgets, on_run=None):
    """构建主窗口：七页签 + 每页参数表单 + 内核输出区。

    `on_run(spec, values)` 是内核调用注入点，测试传入假实现即可在不跑真内核的情况下
    验证"页面只转发参数"；缺省用 `run_kernel`。
    """
    runner = on_run or (lambda spec, values: run_kernel(build_argv(spec, values)))
    window = QtWidgets.QMainWindow()
    window.setWindowTitle("公路技术状况评定与养护决策支持工具（离线内核）")
    tabs = QtWidgets.QTabWidget()
    window.setCentralWidget(tabs)
    window.pages = []

    for spec in PAGE_SPECS:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        form = QtWidgets.QFormLayout()
        editors = {}
        for field in spec.fields:
            if field.kind == "note":
                # 静态说明：只呈现，不进参数表也不进 argv（GUI 不发明内核没有的参数）
                layout.addWidget(QtWidgets.QLabel(field.label))
                continue
            if field.kind == "flag":
                editor = QtWidgets.QCheckBox()
                editor.setChecked(bool(field.default))
                editors[field.name] = editor
            elif field.kind == "choice":
                editor = QtWidgets.QComboBox()
                editor.addItems(list(field.choices))
                if field.default in field.choices:
                    editor.setCurrentText(field.default)
                editors[field.name] = editor
            elif field.kind == "int":
                editor = QtWidgets.QLineEdit(str(field.default))
                editors[field.name] = editor
            else:
                editor = QtWidgets.QLineEdit(str(field.default))
                editors[field.name] = editor
            form.addRow(field.label, editor)
        layout.addLayout(form)

        row = QtWidgets.QHBoxLayout()
        run_button = QtWidgets.QPushButton("运行内核")
        argv_label = QtWidgets.QLabel(" ".join(["rmqc"] + list(spec.command)))
        row.addWidget(run_button)
        row.addWidget(argv_label)
        layout.addLayout(row)

        output = QtWidgets.QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlaceholderText("内核输出（与命令行 rmqc %s 的输出逐字一致）" % " ".join(spec.command))
        layout.addWidget(output)

        def handler(spec=spec, editors=editors, output=output, page=page):
            values = {}
            for name, editor in editors.items():
                if isinstance(editor, QtWidgets.QCheckBox):
                    values[name] = editor.isChecked()
                elif isinstance(editor, QtWidgets.QComboBox):
                    values[name] = editor.currentText()
                else:
                    values[name] = editor.text()
            rc, text = runner(spec, values)
            output.setPlainText("退出码 %d\n\n%s" % (rc, text))
            page.last_rc = rc
            page.last_output = text

        run_button.clicked.connect(handler)
        page.run_once = handler
        tabs.addTab(page, spec.title)
        window.pages.append(page)

    notice = disclaimer.disclaimer_block()
    status = window.statusBar()
    status.showMessage(notice[1] if len(notice) > 1 else "")
    window.disclaimer_text = "\n".join(notice)
    window.tab_count = tabs.count()
    window.tabs = tabs
    return window


def main(argv=None):
    """启动桌面壳。

    `--probe` 为交付验证用的存活探针：建窗口、数页签、跑一次内核 `version` 转发，
    并逐页触发内核，然后立刻退出（不进事件循环），因此可在无显示环境与 CI 里常驻执行。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    probe = "--probe" in argv
    _import_qt()
    if probe:
        # 探针跑在无头环境（CI / 干净 venv / exe 中立目录）：强制 offscreen 平台插件
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets as qt

    app = qt.QApplication.instance() or qt.QApplication([])
    window = build_window(qt)
    if window.tab_count != len(PAGE_TITLES):
        return EXIT_DEGRADED
    if probe:
        rc, text = run_kernel(["version"])
        if rc != EXIT_OK or "road-mqi-checker" not in text:
            return EXIT_DEGRADED
        for page in window.pages:
            page.run_once()
            if not getattr(page, "last_output", ""):
                return EXIT_DEGRADED
        return EXIT_OK
    window.show()
    return app.exec()
