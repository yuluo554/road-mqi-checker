"""占位符登记表与计划文档双向对账：不许有"文档写了但代码没有"或"代码拒了但文档没记"。

同时锁住占位符的抛错语义（MilestoneNotImplemented 带里程碑号），
避免骨架期出现"静悄悄返回 None"的假成功。
"""

import ast
import importlib
import inspect
import os

import pytest

from road_mqi_checker import _meta
from road_mqi_checker.errors import MilestoneNotImplemented


def _registry():
    return dict(_meta.PLACEHOLDER_MILESTONES)


def _raised_keys():
    """扫描 src，收集 MilestoneNotImplemented( 调用里传出的 module key 与里程碑。"""
    found = {}
    src_root = os.path.join(os.path.dirname(os.path.abspath(_meta.__file__)))
    for dirpath, _dirs, files in os.walk(src_root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name_str = getattr(func, "id", None) or getattr(func, "attr", None)
                if name_str != "MilestoneNotImplemented" or len(node.args) < 2:
                    continue
                key, milestone = node.args[0], node.args[1]
                key_value = _resolve_const(key, path)
                milestone_value = _resolve_const(milestone, path)
                if key_value and milestone_value:
                    found[key_value] = milestone_value
    return found


def _resolve_const(node, path):
    literal = _string_constant(node)
    if literal is not None:
        return literal
    if isinstance(node, ast.Name):
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, filename=path)
        return _module_constants(tree).get(node.id)
    return None


def _module_source(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _string_constant(node):
    """3.8 与 3.12 通用的字符串字面量取法（ast.Str/.s 已弃用）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _module_constants(tree):
    """收集 MODULE_KEY / MILESTONE 这类模块常量，供 AST 解析抛错参数。"""
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value = _string_constant(node.value)
            if value is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = value
    return constants


def _milestone_of(call, constants):
    if len(call.args) < 2:
        return None
    second = call.args[1]
    literal = _string_constant(second)
    if literal is not None:
        return literal
    if isinstance(second, ast.Name):
        return constants.get(second.id)
    return None


def _placeholder_functions(module):
    """模块内会抛 MilestoneNotImplemented 的顶层函数：[(函数名, 里程碑)]。"""
    path = inspect.getsourcefile(module)
    tree = ast.parse(_module_source(path), filename=path)
    constants = _module_constants(tree)
    out = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = getattr(child.func, "id", None) or getattr(child.func, "attr", None)
                if name == "MilestoneNotImplemented":
                    out.append((node.name, _milestone_of(child, constants)))
                    break
    return out


def test_registry_keys_are_importable_modules():
    for key in _registry():
        module = importlib.import_module(key)
        assert module is not None, key


def test_every_registered_module_has_placeholders_with_right_milestone():
    """登记表中每个模块确有占位函数，且占位函数声明的里程碑与登记表一致。"""
    for key, milestone in _registry().items():
        module = importlib.import_module(key)
        found = _placeholder_functions(module)
        assert found, "%s 里没有任何 MilestoneNotImplemented，登记表多余" % key
        for func_name, declared in found:
            assert declared == milestone, "%s.%s 声明 %s，登记表写 %s" % (key, func_name, declared, milestone)


def test_registry_and_source_agree():
    """双向：登记过的键确有抛错、抛出的键都已登记。"""
    raised = _raised_keys()
    registry = _registry()
    assert set(raised) == set(registry), (
        "仅代码有：%s / 仅登记表有：%s" % (sorted(set(raised) - set(registry)), sorted(set(registry) - set(raised)))
    )


def test_milestones_are_valid_tags():
    for milestone in _registry().values():
        assert milestone in _meta.VALID_MILESTONES, milestone


def test_registry_modules_appear_in_dev_plan(plan02):
    """每个占位符模块都要在 plan/02 的模块映射表里有一行 —— 防文档与树漂移。"""
    for key in _registry():
        relative = key.replace("road_mqi_checker.", "")
        assert relative in plan02, "%s 未写进 plan/02" % relative


def test_milestone_docs_are_declared():
    for milestone in sorted(set(_registry().values()) | {"M0"}):
        assert milestone in _meta.MILESTONE_DOCS, milestone
        assert os.path.isabs(_meta.MILESTONE_DOCS[milestone]) is False, "文档路径要写成仓库相对路径"


def test_current_milestone_matches_delivered_work():
    """M2 评定内核已交付：PCI 换算、贡献展开、assess 命令都真跑，里程碑指针随之前进。"""
    assert _meta.MILESTONE == "M2"


def test_pci_kernel_is_no_longer_a_placeholder():
    """M2 交付的模块必须从登记表移除，且真不再抛占位异常（双向对账的显式那一半）。"""
    from road_mqi_checker.pci import engine, trace

    for key in ("road_mqi_checker.pci.engine", "road_mqi_checker.pci.trace"):
        assert key not in _registry(), "%s 仍登记为占位符" % key
        assert key not in _raised_keys(), "%s 里还有 MilestoneNotImplemented" % key
    assert callable(engine.compute_pci) and callable(trace.expand_contributions)


def test_placeholder_message_is_actionable():
    exc = MilestoneNotImplemented("road_mqi_checker.pci.engine", "M2", what="逐路段 PCI 评定")
    text = str(exc)
    assert "M2" in text and "尚未实现" in text and "PCI" in text


def test_no_ghost_modules_in_package():
    """包内 .py 文件要么被登记、要么已实现 —— 不允许存在无人认领的模块。"""
    package_dir = os.path.dirname(os.path.abspath(_meta.__file__))
    implemented = {
        "",
        "cli",
        "__main__",
        "_meta",
        "errors",
        "exit_codes",
        "results",
        "privacy",
        "data_paths",
        "ruleset",
        "ruleset.status",
        "ruleset.loader",
        "ledger",
        "ledger.models",
        "ledger.db",
        "ledger.importer",
        "ledger.checks",
        "pci",
        "pci.engine",
        "pci.trace",
        "report",
        "report.disclaimer",
        "gui",
        "bench",
        "bench.rng",
        "bench.generator",
        "bench.evaluation",
    }
    for dirpath, _dirs, files in os.walk(package_dir):
        for name in files:
            if not name.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), package_dir)
            module = rel[:-3].replace(os.sep, ".")
            if module == "__init__" or module.endswith("__init__"):
                continue
            key = "road_mqi_checker." + module
            assert module in implemented or key in _registry(), "未登记模块：%s" % key
