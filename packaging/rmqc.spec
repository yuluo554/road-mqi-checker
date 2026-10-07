# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir 双 exe 打包规格（M6 交付层）。

一次构建产出两个可执行文件、共用同一份 `_internal`（标准多包 onedir 写法：
两次 Analysis + 两个 EXE(exclude_binaries=True) + 一个 COLLECT）：

- `rmqc.exe`     控制台壳（console=True），等价 `rmqc` CLI。入口 packaging/entry_cli.py。
- `rmqc-gui.exe` 桌面壳（console=False / windowed），等价 `rmqc gui`。入口 packaging/entry_gui.py。

PyInstaller 6 的 onedir 布局是 `dist/rmqc/rmqc.exe` + `dist/rmqc/_internal/...`，
冻结态 `sys._MEIPASS` 指向 `_internal`，故 `data_paths.find_data_dir()` 的第 3 优先级
分支（`sys._MEIPASS/data`）会命中下面 datas 白名单落到 `data/...` 的内嵌数据。

datas 白名单逐条列出（不整目录一把梭）；绝不放 tests/ 与 tests/fixtures/（常驻红线，
见 tests/test_release_redlines.py::test_fixture_channel_never_appears_in_data_or_shipped_rulesets）。
"""

import glob
import os

# SPECPATH 是 PyInstaller 注入的、本 spec 文件所在目录（= <repo>/packaging）。
HERE = os.path.abspath(SPECPATH)
REPO = os.path.dirname(HERE)
SRC = os.path.join(REPO, "src")
DATA = os.path.join(REPO, "data")
RULESET_SRC_DIR = os.path.join(SRC, "road_mqi_checker", "rulesets")

# ---- datas 白名单：逐条列出，落到内嵌相对路径 ----
# 演示数据 raw 12 份 + manifest.json 1 份 + truth 12 份 + data/README.md 1 份 + 内置规则集 1 份。
ROUTE_IDS = ("S99", "X990", "Y999")
YEARS = (2022, 2023, 2024, 2025)

RAW_NAMES = ["%s-%d.csv" % (route, year) for route in ROUTE_IDS for year in YEARS]           # 12
TRUTH_NAMES = ["%s-%d.truth.csv" % (route, year) for route in ROUTE_IDS for year in YEARS]    # 12

# 构建期自校验：白名单必须与仓库现状逐条对得上（少列/多列都在打包阶段炸，而不是留到交付后）
_actual_raw = sorted(os.path.basename(p) for p in glob.glob(os.path.join(DATA, "raw", "*.csv")))
_actual_truth = sorted(os.path.basename(p) for p in glob.glob(os.path.join(DATA, "truth", "*.truth.csv")))
assert sorted(RAW_NAMES) == _actual_raw, "raw 白名单与 data/raw/ 现状不符：%s vs %s" % (
    sorted(RAW_NAMES), _actual_raw)
assert sorted(TRUTH_NAMES) == _actual_truth, "truth 白名单与 data/truth/ 现状不符：%s vs %s" % (
    sorted(TRUTH_NAMES), _actual_truth)

_ruleset_jsons = sorted(os.path.basename(p) for p in glob.glob(os.path.join(RULESET_SRC_DIR, "*.json")))
assert _ruleset_jsons, "内置规则集目录为空，打包口径要求必须带上 rulesets/*.json"

DATAS = []
for _name in RAW_NAMES:
    DATAS.append((os.path.join(DATA, "raw", _name), "data/raw"))
DATAS.append((os.path.join(DATA, "raw", "manifest.json"), "data/raw"))
for _name in TRUTH_NAMES:
    DATAS.append((os.path.join(DATA, "truth", _name), "data/truth"))
# data/README.md 既是 find_data_dir() 认的目录标记文件，也是内嵌数据台账（verify_build 逐份对 sha256）
DATAS.append((os.path.join(DATA, "README.md"), "data"))
# 内置规则集由包数据带上，逐条列出到包内原相对路径（口径要求白名单可见，故不用 collect_data_files）
for _name in _ruleset_jsons:
    DATAS.append((os.path.join(RULESET_SRC_DIR, _name), "road_mqi_checker/rulesets"))

# ---- 排除：本项目内核零第三方依赖，绝不该被拖进来的大件 ----
EXCLUDES = [
    "numpy", "scipy", "pandas", "matplotlib", "PIL", "tkinter",
    "IPython", "PyQt5", "PyQt6", "PySide2", "PySide6.QtWebEngineCore",
]

# 惰性/函数级导入的子模块显式登记为 hiddenimports，防止模块图静态分析漏收（命令体里的 import）
HIDDEN = [
    "road_mqi_checker.bench.generator",
    "road_mqi_checker.bench.evaluation",
    "road_mqi_checker.pci.engine",
    "road_mqi_checker.pci.trace",
    "road_mqi_checker.mqi.engine",
    "road_mqi_checker.strategy.rules",
    "road_mqi_checker.strategy.compare",
    "road_mqi_checker.ruleset.loader",
    "road_mqi_checker.ruleset.status",
    "road_mqi_checker.report.exporters",
    "road_mqi_checker.report.disclaimer",
    "road_mqi_checker.ledger.db",
    "road_mqi_checker.ledger.importer",
    "road_mqi_checker.ledger.checks",
    "road_mqi_checker.gui.app",
    "road_mqi_checker.data_paths",
    "road_mqi_checker.privacy",
    "road_mqi_checker.results",
    "road_mqi_checker.errors",
    "road_mqi_checker.exit_codes",
]


def _dedup_toc(*tocs):
    """合并多个 TOC 并按条目名去重（多包 onedir 里 a1/a2 的 binaries/datas 大量同名，不去重会报 duplicate）。"""
    merged = {}
    for toc in tocs:
        for item in toc:
            merged[item[0]] = item
    return list(merged.values())


# ================= 控制台壳 rmqc.exe =================
a1 = Analysis(
    [os.path.join(HERE, "entry_cli.py")],
    pathex=[SRC],
    binaries=[],
    datas=DATAS,             # 内嵌数据只挂一次；两个 exe 共用同一份 _internal
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz1 = PYZ(a1.pure)
exe1 = EXE(
    pyz1,
    a1.scripts,
    # 冻结态 sys.stdout 默认用控制台/locale 编码（本机 cp936），会因 '⇒' 等非 gbk 字符崩溃；
    # 内嵌解释器运行期选项 `-X utf8` 让 stdout/stderr 走 UTF-8，与源码态口径一致（否则命令面数字/符号打不全）。
    [("X utf8", None, "OPTION")],
    exclude_binaries=True,
    name="rmqc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,            # 控制台壳
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ================= 桌面壳 rmqc-gui.exe =================
a2 = Analysis(
    [os.path.join(HERE, "entry_gui.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],                # 数据已在 a1 里挂过，共享 _internal；此处只让 Qt 的 binaries 进来
    hiddenimports=HIDDEN + ["PySide6"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz2 = PYZ(a2.pure)
exe2 = EXE(
    pyz2,
    a2.scripts,
    [("X utf8", None, "OPTION")],   # 与 console 壳一致的解释器运行期 UTF-8 模式
    exclude_binaries=True,
    name="rmqc-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # 窗口壳（windowed）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ================= 共用一份 _internal =================
coll = COLLECT(
    exe1,
    exe2,
    _dedup_toc(a1.binaries, a2.binaries),
    _dedup_toc(a1.datas, a2.datas),
    strip=False,
    upx=False,
    upx_exclude=[],
    name="rmqc",
)
