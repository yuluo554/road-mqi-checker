"""CI workflow 的 YAML 必须真能解析（发票台账实录：非法 YAML 会让 GitHub 一个 job 都不建，
而 workflow 的 state 仍显示 active、文件字节也洁净，只有真解析才暴露）。"""

import glob
import os

import pytest

yaml = pytest.importorskip("yaml", reason="dev extras 未装 pyyaml，无法解析 workflow")

from road_mqi_checker.cli import PKG_NAME  # noqa: E402


def _workflow_files(repo_root):
    return sorted(glob.glob(os.path.join(repo_root, ".github", "workflows", "*.yml")))


def test_workflows_exist_and_parse(repo_root):
    files = _workflow_files(repo_root)
    assert files, "仓库必须有至少一个 CI workflow"
    for path in files:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        assert "\t" not in text, "%s 含 Tab 缩进" % path
        loaded = yaml.safe_load(text)
        assert isinstance(loaded, dict), "%s 解析结果不是映射" % path
        assert loaded.get("jobs"), "%s 没有 jobs" % path


def test_every_job_declares_runner_and_steps(repo_root):
    for path in _workflow_files(repo_root):
        with open(path, "r", encoding="utf-8") as handle:
            doc = yaml.safe_load(handle)
        for job_id, job in doc["jobs"].items():
            assert job.get("runs-on"), "%s 的 job %s 缺 runs-on" % (path, job_id)
            assert job.get("steps"), "%s 的 job %s 缺 steps" % (path, job_id)


def test_matrix_covers_python_floor_and_latest(repo_root):
    """3.8 是本仓库的兼容下限（plan/02 §1），矩阵必须同时含下限与最新版、两个 OS。"""
    doc = yaml.safe_load(_read_first_workflow(repo_root))
    matrix = doc["jobs"]["test"]["strategy"]["matrix"]
    assert "3.8" in matrix["python-version"], "矩阵缺 3.8 下限"
    assert "3.12" in matrix["python-version"], "矩阵缺最新版"
    assert set(["ubuntu-latest", "windows-latest"]) <= set(matrix["os"])


def test_install_lines_upgrade_pip_and_setuptools_before_editable(repo_root):
    """3.8 自带 pip 20.x 装不了 pyproject-only 项目；升级步骤必须在安装之前出现。"""
    text = _read_first_workflow(repo_root)
    doc = yaml.safe_load(text)
    steps = doc["jobs"]["test"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    upgrade = next((i for i, name in enumerate(names) if "Upgrade build tooling" in name), None)
    install = next((i for i, name in enumerate(names) if "Install package" in name), None)
    assert upgrade is not None and install is not None and upgrade < install, names


def test_ci_runs_the_same_kernel_cli(repo_root):
    """CI 必须跑真实入口（同一内核），而不是只跑 pytest。"""
    doc = yaml.safe_load(_read_first_workflow(repo_root))
    commands = [str(step.get("run", "")) for step in doc["jobs"]["test"]["steps"]]
    assert any(PKG_NAME.replace("-", "_") in cmd for cmd in commands), commands


def _read_first_workflow(repo_root):
    files = _workflow_files(repo_root)
    assert files, "缺少 workflow"
    with open(files[0], "r", encoding="utf-8") as handle:
        return handle.read()
