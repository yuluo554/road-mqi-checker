"""测试基座：把 src 放进导入路径，并断言"测的就是这个树里的代码"。

第二项很关键 —— 系统 Python 里可能装过同名的已发布包，
不核对 __file__ 就会出现"改了源码测试还是绿"的假结果。
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import road_mqi_checker  # noqa: E402


def pytest_configure(config):
    resolved = os.path.abspath(road_mqi_checker.__file__)
    if not resolved.startswith(SRC):
        raise ImportError(
            "road_mqi_checker 解析到 %s，不在本仓库 src/ 内 —— 会测错对象" % resolved
        )


@pytest.fixture
def repo_root():
    return ROOT


@pytest.fixture
def data_dir(repo_root):
    return os.path.join(repo_root, "data")


@pytest.fixture
def plan_dir(repo_root):
    return os.path.join(repo_root, "plan")


@pytest.fixture
def plan02(plan_dir):
    path = os.path.join(plan_dir, "02-开发计划与架构.md")
    if not os.path.isfile(path):
        pytest.fail(
            "plan/02-开发计划与架构.md 缺失：占位符登记表必须与计划文档同批入库（不是可跳过的可选项）"
        )
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()
