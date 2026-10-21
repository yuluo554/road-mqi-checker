# -*- coding: utf-8 -*-
"""cli 包形态守门（2026-10-22 修复回归）。

背景：`rmqc-cli-win64.zip` 曾把一个没有 Qt 的 `rmqc-gui.exe` 留在包里，
在中立目录跑 `--probe` 抛 `ImportError: shiboken6\\libshoken6 does not exist`
→ exit 1（GUI 包内同名 exe 是 exit 0）。本文件把三条形态约束锁死：

  1. cli 包不得含任何 Qt/shiboken 载荷；
  2. cli 包不得含窗口壳 `rmqc-gui.exe`；
  3. cli 包有且只有 `rmqc.exe` 一个可执行件。

重建器与判据同源：`packaging/pack_cli_zip.py`。
本测试用合成 zip 断言判据本身可证伪（正控 + 负控），不依赖真实发布资产在不在本机。
"""

import importlib.util
import os
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MODULE_PATH = os.path.join(REPO, "packaging", "pack_cli_zip.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("pack_cli_zip", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pci = _load_module()


def _make_zip(path, entries):
    """entries: [(name, bytes)]，全部用固定时间戳，保证可复现。"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 8, 8, 10, 2))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return path


GUI_ENTRIES = [
    ("rmqc.exe", b"MZ-cli"),
    ("rmqc-gui.exe", b"MZ-gui"),
    ("_internal/PySide6/Qt6Core.dll", b"qt"),
    ("_internal/shiboken6/libshiboken6.dll", b"sb"),
    ("_internal/python312.dll", b"py"),
    ("_internal/data/raw/manifest.json", b"{}"),
]


class TestCliZipShape:
    def test_build_strips_qt_and_gui_exe(self, tmp_path):
        """正控：重建后只剩 rmqc.exe、无 Qt 载荷、无窗口壳。"""
        src = _make_zip(tmp_path / "gui.zip", GUI_ENTRIES)
        out = tmp_path / "cli.zip"
        info = pci.build_cli_zip(str(src), str(out))

        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        assert "rmqc.exe" in names
        assert "rmqc-gui.exe" not in names, "窗口壳必须被剔除"
        assert not [n for n in names if pci.is_qt_payload(n)], "Qt 载荷必须被剔除"
        assert "_internal/python312.dll" in names, "非 Qt 依赖必须保留"
        assert "_internal/data/raw/manifest.json" in names, "内嵌数据必须保留"
        assert info["entries"] == len(names)
        assert pci.assert_cli_zip_shape(str(out)) == []

    def test_rebuild_is_deterministic(self, tmp_path):
        """同输入两次重建逐字节一致（条目元数据沿用源包）。"""
        src = _make_zip(tmp_path / "gui.zip", GUI_ENTRIES)
        a, b = tmp_path / "a.zip", tmp_path / "b.zip"
        ia = pci.build_cli_zip(str(src), str(a))
        ib = pci.build_cli_zip(str(src), str(b))
        assert ia["sha256"] == ib["sha256"]

    def test_gate_rejects_windowed_shell(self, tmp_path):
        """负控：把 rmqc-gui.exe 塞回 cli 包，判据必须报出来。"""
        bad = _make_zip(tmp_path / "bad.zip", [
            ("rmqc.exe", b"MZ-cli"),
            ("rmqc-gui.exe", b"MZ-gui"),
        ])
        problems = pci.assert_cli_zip_shape(str(bad))
        assert problems, "缺 Qt 的窗口壳混进 cli 包必须被判违规"
        assert any("窗口壳" in p for p in problems), problems

    def test_gate_rejects_qt_payload(self, tmp_path):
        """负控：cli 包内出现 Qt 载荷必须被判违规。"""
        bad = _make_zip(tmp_path / "bad.zip", [
            ("rmqc.exe", b"MZ-cli"),
            ("_internal/PySide6/Qt6Core.dll", b"qt"),
        ])
        problems = pci.assert_cli_zip_shape(str(bad))
        assert any("Qt" in p for p in problems), problems

    def test_gate_rejects_missing_cli_exe(self, tmp_path):
        """负控：只有窗口壳、没有控制台壳，必须被判违规。"""
        bad = _make_zip(tmp_path / "bad.zip", [("rmqc-gui.exe", b"MZ-gui")])
        problems = pci.assert_cli_zip_shape(str(bad))
        assert any("缺控制台壳" in p for p in problems), problems
