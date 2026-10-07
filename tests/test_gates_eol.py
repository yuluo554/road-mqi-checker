"""EOL 门：Windows 开发机 core.autocrlf=true 会把检出写成 CRLF，
位级冻结产物与字节一致断言就会在"全新 clone"里全挂 —— 而开发机目录永远测不到。
所以这里对**已跟踪文本文件**逐份查 CR 字节，出现即大声失败。
"""

import os
import shutil
import subprocess

import pytest


def _git(args, cwd):
    return subprocess.run(
        ["git", "-c", "core.quotepath=false"] + args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def test_gitattributes_declares_lf(repo_root):
    path = os.path.join(repo_root, ".gitattributes")
    assert os.path.isfile(path), "缺 .gitattributes"
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    assert "* text=auto eol=lf" in text, "必须显式声明 eol=lf"


@pytest.mark.skipif(shutil.which("git") is None, reason="环境无 git，EOL 门由 CI 覆盖")
def test_tracked_text_files_have_no_cr(repo_root):
    if not os.path.isdir(os.path.join(repo_root, ".git")):
        pytest.skip("不在 git 仓库内（例如只拷贝了源码树）")
    proc = _git(["ls-files", "-z"], repo_root)
    assert proc.returncode == 0, proc.stderr
    names = [name for name in proc.stdout.split("\0") if name]
    text_suffix = (".py", ".md", ".toml", ".yml", ".yaml", ".json", ".txt", ".cfg", ".ini", ".csv")
    binaries = (".pdf", ".png", ".jpg", ".ico", ".exe", ".dll", ".zip", ".docx", ".xlsx", ".db", ".sqlite")
    offenders = []
    for name in names:
        if name.endswith(binaries):
            continue
        if not name.endswith(text_suffix):
            continue
        full = os.path.join(repo_root, name)
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as handle:
            if b"\r" in handle.read():
                offenders.append(name)
    assert not offenders, "跟踪文本文件含 CR（会让位级一致断言在干净 clone 里挂）：%s" % offenders


def test_data_subdirectories_exist(repo_root):
    """data/ 四类目录是台账约定的骨架，缺一个就意味着数据纪律没有落点。"""
    for name in ("raw", "truth", "golden", "standards"):
        path = os.path.join(repo_root, "data", name)
        assert os.path.isdir(path), "缺目录 %s" % path


def test_standards_pdf_is_ignored(repo_root):
    """版权红线：标准全文/扫描件不得入库。"""
    path = os.path.join(repo_root, ".gitignore")
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    assert "data/standards/*.pdf" in text
