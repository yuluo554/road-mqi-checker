"""闸门自身的环境稳健性回归（M1 干净环境验证实测到的三个坑）。

这三条只在"全新 clone + 装在仓库里的 .venv + GBK locale + 中文文件名"同时出现时才复现，
开发机常驻目录永远测不到 —— 正是 `support_git` 存在的原因。
"""

import os
import shutil
import subprocess

import pytest

from support_git import BINARY_SUFFIXES, git_lines, tracked_files, walk_files

CHINESE_NAME = "说明与数据表.md"
NON_ASCII_CONTENT = "闭合差容差：待核对，未判定"  # 含 GBK 解码不了的字节序列


def _run_git(root, args):
    return subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "user.email=t@example.invalid", "-c", "user.name=t"] + args,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture
def temp_repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("环境无 git，本回归由 CI 覆盖")
    root = str(tmp_path / "repo")
    os.makedirs(os.path.join(root, "data"))
    os.makedirs(os.path.join(root, "src", "pkg"))
    os.makedirs(os.path.join(root, "tests"))
    os.makedirs(os.path.join(root, ".venv", "Scripts"))
    # 让"源码/测试是否被跟踪"这条门也真的走一遍分隔符换算（git 永远输出正斜杠）
    for path in (
        os.path.join("src", "pkg", "__init__.py"),
        os.path.join("src", "pkg", "模块.py"),
        os.path.join("tests", "test_sample.py"),
    ):
        with open(os.path.join(root, path), "w", encoding="utf-8", newline="\n") as handle:
            handle.write("x = 1\n")
    # 与真实仓库一致的忽略规则：本地虚拟环境与台账文件都不进交付面
    with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(".venv/\n*.sqlite\n.tmp_*/\n__pycache__/\n")
    with open(os.path.join(root, CHINESE_NAME), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# 说明\n\n%s\n" % NON_ASCII_CONTENT)
    with open(os.path.join(root, "data", "S99-2022.csv"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("segment_id,quantity\nS99-A1,6.5\n")
    # 两个"看起来像二进制交付物"的运行期产物：一个在 .venv 里，一个是本地台账
    with open(os.path.join(root, ".venv", "Scripts", "rmqc.exe"), "wb") as handle:
        handle.write(b"MZ\x00\x00")
    with open(os.path.join(root, "ledger.sqlite"), "wb") as handle:
        handle.write(b"SQLite format 3\x00")
    _run_git(root, ["init", "-q"])
    _run_git(root, ["add", "-A"])
    added = _run_git(root, ["commit", "-q", "-m", "seed"])
    assert added.returncode == 0, added.stderr
    return root


def test_tracked_listing_survives_non_ascii_names(temp_repo):
    """中文文件名必须出现在清单里，且 stdout 不能是 None。

    旧写法（`universal_newlines=True` 不指定编码）在这台机器上会让 git 的读线程抛
    UnicodeDecodeError，`proc.stdout` 变成 None，两条闸门接着以 AttributeError 假死。
    """
    names = tracked_files(temp_repo)
    assert names is not None
    assert CHINESE_NAME in names, names
    proc = git_lines(temp_repo, ["ls-files"])
    assert proc.stdout is not None, "git 输出没被按 UTF-8 解码"
    assert CHINESE_NAME in proc.stdout


def test_local_venv_and_sqlite_are_not_delivery_surface(temp_repo):
    """.venv 里的 exe 与本地 ledger.sqlite 都不算交付面；交付面只看已跟踪文件。"""
    tracked = tracked_files(temp_repo)
    assert not [name for name in tracked if name.endswith(BINARY_SUFFIXES)]
    # 工作树里确实有这些文件 —— 证明"没报"不是因为它们不存在
    assert os.path.isfile(os.path.join(temp_repo, ".venv", "Scripts", "rmqc.exe"))
    assert os.path.isfile(os.path.join(temp_repo, "ledger.sqlite"))


def test_walk_files_skips_venv_and_temp_dirs(temp_repo):
    os.makedirs(os.path.join(temp_repo, ".tmp_verify"), exist_ok=True)
    with open(os.path.join(temp_repo, ".tmp_verify", "junk.db"), "wb") as handle:
        handle.write(b"x")
    found = walk_files(temp_repo, BINARY_SUFFIXES)
    assert not any(".venv" in path for path in found), found
    assert not any(".tmp_verify" in path for path in found), found
    assert os.path.join(temp_repo, "ledger.sqlite") in found  # 直接扫树时才看得见


def test_the_two_gates_pass_on_a_fresh_clone_shape(temp_repo):
    """把两条真实闸门跑在这个形状上：不崩、不误报。"""
    import test_gates_eol
    import test_release_redlines

    test_gates_eol.test_tracked_text_files_have_no_cr(temp_repo)
    test_release_redlines.test_no_binary_samples_without_ledger_entry(temp_repo)
    test_release_redlines.test_every_source_and_test_file_is_git_tracked(temp_repo)
