"""find_data_dir 优先级锁死（exe 冻结分支的验证前提）。

优先级属"动了会打挂测试"的口径：显式 > 环境变量 > _MEIPASS 内嵌 > exe 目录 _internal > 上溯。
"""

import os

import pytest

from road_mqi_checker import data_paths
from road_mqi_checker.errors import InputUnavailable


def _make_data(root, name="data"):
    path = os.path.join(str(root), name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("# synthetic\n")
    return path


def test_priority_order_is_documented_and_enforced(tmp_path, monkeypatch):
    explicit = _make_data(tmp_path / "explicit")
    env = _make_data(tmp_path / "env")
    meipass_root = tmp_path / "meipass"
    _make_data(meipass_root)
    monkeypatch.setenv(data_paths.ENV_DATA_DIR, env)
    monkeypatch.setattr(data_paths.sys, "_MEIPASS", str(meipass_root), raising=False)

    assert data_paths.find_data_dir(explicit=explicit, start=str(tmp_path)) == explicit
    assert data_paths.find_data_dir(start=str(tmp_path)) == env
    monkeypatch.delenv(data_paths.ENV_DATA_DIR)
    assert data_paths.find_data_dir(start=str(tmp_path)) == os.path.join(str(meipass_root), "data")


def test_frozen_internal_layout_is_a_candidate(tmp_path, monkeypatch):
    exe_dir = tmp_path / "appdir"
    internal = _make_data(exe_dir / "_internal")
    monkeypatch.setattr(data_paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(data_paths.sys, "executable", os.path.join(str(exe_dir), "rmqc.exe"))
    monkeypatch.delenv(data_paths.ENV_DATA_DIR, raising=False)
    monkeypatch.delattr(data_paths.sys, "_MEIPASS", raising=False)
    candidates = data_paths.candidate_dirs(start=str(tmp_path))
    assert internal in candidates
    assert candidates.index(internal) < candidates.index(os.path.join(str(tmp_path), "data"))


def test_upward_search_finds_repo_data(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    data = _make_data(repo)
    nested = os.path.join(str(repo), "src", "deep")
    os.makedirs(nested, exist_ok=True)
    monkeypatch.delenv(data_paths.ENV_DATA_DIR, raising=False)
    monkeypatch.delattr(data_paths.sys, "_MEIPASS", raising=False)
    assert data_paths.find_data_dir(start=nested) == data


def test_missing_data_dir_raises_input_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv(data_paths.ENV_DATA_DIR, raising=False)
    monkeypatch.delattr(data_paths.sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(data_paths.sys, "frozen", False, raising=False)
    empty = tmp_path / "nothing_here"
    os.makedirs(str(empty))
    # 上溯到根都不该有带 README.md 的 data 目录；若宿主环境本身有，就跳过而不是假失败
    if any(os.path.isdir(c) and os.path.isfile(os.path.join(c, "README.md")) for c in data_paths.candidate_dirs(start=str(empty))):
        pytest.skip("临时目录的上溯路径上存在 data 目录，无法在此环境验证缺失分支")
    with pytest.raises(InputUnavailable):
        data_paths.find_data_dir(start=str(empty))


def test_marker_file_requirement(tmp_path, monkeypatch):
    bare = os.path.join(str(tmp_path), "data")
    os.makedirs(bare, exist_ok=True)
    monkeypatch.delenv(data_paths.ENV_DATA_DIR, raising=False)
    monkeypatch.delattr(data_paths.sys, "_MEIPASS", raising=False)
    assert data_paths.find_data_dir(start=str(tmp_path), require_marker=False) == bare
    with pytest.raises(InputUnavailable):
        data_paths.find_data_dir(start=str(tmp_path), require_marker=True)


def test_repo_itself_resolves_data_dir(repo_root):
    assert os.path.isdir(data_paths.find_data_dir(start=repo_root))
