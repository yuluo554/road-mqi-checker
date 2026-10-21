# -*- coding: utf-8 -*-
"""Release 两份 zip 的形态守门 + cli 包重建器（2026-10-22 修复）。

## 为什么有这个文件

`rmqc-cli-win64.zip` 此前是用临时脚本从 `~gui` 包剔除 Qt/shiboken 得到的（147 个文件），
但**漏掉了 `rmqc-gui.exe`** —— 于是一个"没有 Qt 的窗口壳"被留在 CLI 包里，
在中立目录跑 `rmqc-gui.exe --probe` 会 `ImportError: shiboken6\\libshiboken does not exist`
→ `OptionalDependencyMissing` → exit 1（该结果与 GUI 包内同名 exe 的 exit 0 相反）。

本文件把"cli 包只许有控制台壳"从口头约定变成：
  1. `build_cli_zip()` —— 唯一重建入口（剔除 Qt/shiboken + 窗口壳，其余条目元数据原样保留）；
  2. 三条 pytest 断言 —— 无 Qt 载荷、无窗口壳、仅一个 exe。

用法（重建资产）：
    python packaging/pack_cli_zip.py <gui.zip> <out-cli.zip>
"""

import hashlib
import os
import sys
import zipfile

#: 判定 Qt 载荷的路径 token（不区分大小写，统一用 '/' 归一后比对）
QT_TOKENS = ("/pyside6/", "/shiboken6/", "qt6")

#: cli 包唯一允许的可执行件
CLI_EXE = "rmqc.exe"
#: 窗口壳——cli 包内**不得**出现（剥掉 Qt 后它必然跑不起来）
GUI_EXE = "rmqc-gui.exe"


def _norm(name):
    return name.replace("\\", "/").lower()


def is_qt_payload(name):
    """该条目是否属 Qt/shiboken 载荷（cli 包一律剔除）。"""
    low = _norm(name)
    return any(tok in low for tok in QT_TOKENS)


def build_cli_zip(src_gui_zip, out_cli_zip):
    """从 gui zip 重建 cli zip。

    保留规则：gui 包中**非 Qt 载荷**且**非窗口壳**的条目；
    条目元数据（date_time / compress_type / external_attr）原样沿用，保证可复现。

    Returns:
        dict: {"entries": n, "size": bytes, "sha256": hex}
    """
    with zipfile.ZipFile(src_gui_zip) as gz:
        keep = [i for i in gz.infolist()
                if not is_qt_payload(i.filename)
                and _norm(i.filename) != GUI_EXE]
        with zipfile.ZipFile(out_cli_zip, "w", compression=zipfile.ZIP_DEFLATED) as zo:
            for info in keep:
                zo.writestr(info, gz.read(info.filename))

    data = open(out_cli_zip, "rb").read()
    return {
        "entries": len(keep),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def assert_cli_zip_shape(path):
    """cli 包形态断言：返回违规列表（空 = 合规）。"""
    problems = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        qt = [n for n in names if is_qt_payload(n)]
        exes = [n for n in names if _norm(n).endswith(".exe")]
        if qt:
            problems.append("cli 包含 Qt/shiboken 载荷 %d 个（例：%s）" % (len(qt), qt[0]))
        if GUI_EXE in [_norm(n) for n in exes]:
            problems.append("cli 包含窗口壳 %s（剥掉 Qt 后它必然跑不起来）" % GUI_EXE)
        if [e for e in exes if _norm(e) != CLI_EXE]:
            problems.append("cli 含非预期可执行件：%s" % exes)
        if CLI_EXE not in [_norm(n) for n in exes]:
            problems.append("cli 缺控制台壳 %s" % CLI_EXE)
        if z.testzip() is not None:
            problems.append("zip 自校验失败")
    return problems


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 2:
        print("用法: python packaging/pack_cli_zip.py <gui.zip> <out-cli.zip>")
        return 2
    src, out = argv
    if not os.path.isfile(src):
        print("输入不存在: %s" % src)
        return 2
    info = build_cli_zip(src, out)
    print("已生成 %s" % out)
    print("  条目数: %(entries)d" % info)
    print("  大小:   %(size)d B" % info)
    print("  sha256: %(sha256)s" % info)
    problems = assert_cli_zip_shape(out)
    if problems:
        for p in problems:
            print("  ❌ " + p)
        return 1
    print("  ✅ 形态合规（无 Qt 载荷 / 无窗口壳 / 仅 %s）" % CLI_EXE)
    return 0


if __name__ == "__main__":
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.exit(main())
