"""pyproject 纪律门：核心零依赖、extras 覆盖真实导入、重依赖按解释器双向标记。

不引 tomllib（3.11+ 才有），用行级解析就够 —— 要断言的是纪律，不是 TOML 语义。
"""

import os
import re

import pytest


def _read_pyproject(repo_root):
    path = os.path.join(repo_root, "pyproject.toml")
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _extras_block(text):
    lines = text.splitlines()
    if "[project.optional-dependencies]" not in lines:
        pytest.fail("pyproject 缺 [project.optional-dependencies]")
    start = lines.index("[project.optional-dependencies]") + 1
    block = []
    for line in lines[start:]:
        if line.startswith("["):
            break
        block.append(line)
    return "\n".join(block)


def _extra_list(extras_text, name):
    """按行取一个 extras 数组（每条一行，允许带 PEP 508 marker 里的逗号）。"""
    lines = extras_text.splitlines()
    header = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(name + " ="):
            header = index
            break
    assert header is not None, "extras 缺少分组 %s" % name
    entries = []
    for line in lines[header + 1 :]:
        stripped = line.strip()
        if stripped.startswith("]"):
            break
        if not stripped or stripped.startswith("#"):
            continue
        entries.append(stripped.rstrip(",").strip('"'))
    assert entries, "extras 分组 %s 为空" % name
    return entries


def test_core_dependencies_are_empty(repo_root):
    text = _read_pyproject(repo_root)
    assert re.search(r"^dependencies\s*=\s*\[\s*\]", text, re.M), "核心内核必须零第三方依赖"


def test_requires_python_floor(repo_root):
    text = _read_pyproject(repo_root)
    assert 'requires-python = ">=3.8"' in text


def test_dev_extras_cover_test_imports(repo_root):
    """dev 组必须覆盖测试期真实 import（漏装会让 CI 静默少跑而不是报错）。"""
    entries = " ".join(_extra_list(_extras_block(_read_pyproject(repo_root)), "dev")).lower()
    for needed in ("pytest", "yaml"):
        assert needed in entries, "dev extras 缺 %s" % needed


def test_gui_extras_capped_on_old_python(repo_root):
    """3.8 上 PySide6 必须写上界：只写下限会让干净环境解析到装不上的新破坏版本。"""
    entries = _extra_list(_extras_block(_read_pyproject(repo_root)), "gui")
    old = [item for item in entries if 'python_version < "3.9"' in item or "python_version < '3.9'" in item]
    assert old, "gui extras 缺 3.8 分档"
    assert any("<6.7" in item for item in old), old


def test_pkg_extras_capped_on_old_python(repo_root):
    entries = _extra_list(_extras_block(_read_pyproject(repo_root)), "pkg")
    old = [item for item in entries if "3.9" in item and "<" in item]
    assert old, "pkg extras 缺 3.8 分档上界"
    assert any("<6" in item for item in old), old


def test_console_scripts_point_to_same_cli(repo_root):
    text = _read_pyproject(repo_root)
    assert 'rmqc = "road_mqi_checker.cli:main"' in text
    assert 'road-mqi-checker = "road_mqi_checker.cli:main"' in text


def test_package_data_includes_rulesets(repo_root):
    """规则集必须随包（exe 内嵌依赖 package-data 白名单）。"""
    text = _read_pyproject(repo_root)
    assert "rulesets/*.json" in text


def test_third_party_imports_are_declared_or_optional(repo_root):
    """src 里出现的第三方顶层 import，只能来自 gui/pkg 可选组；核心不得有。"""
    banned_third_party = {
        "numpy",
        "pandas",
        "scipy",
        "requests",
        "httpx",
        "pydantic",
        "openai",
        "anthropic",
        "faiss",
        "sklearn",
        "lxml",
        "docx",
    }
    src_root = os.path.join(repo_root, "src")
    hits = []
    for dirpath, _dirnames, filenames in os.walk(src_root):
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, "r", encoding="utf-8") as handle:
                for lineno, line in enumerate(handle, 1):
                    match = re.match(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", line)
                    if not match:
                        continue
                    top = match.group(1).split(".")[0]
                    if top in banned_third_party:
                        hits.append("%s:%d %s" % (path, lineno, top))
    assert not hits, "核心包引入了未声明的第三方依赖：%s" % hits
