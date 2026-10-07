"""测试共用的 git 与工作树扫描原语。

放在这里而不是各测试文件里抄一份，是因为这两件事都踩过环境坑：

1. **编码**：`git ls-files` 输出 UTF-8 路径。用 `universal_newlines=True` 而不指定编码时，
   Windows 会按本地代码页（这台机器是 GBK）解码，中文文件名一多就在读线程里抛
   UnicodeDecodeError，`proc.stdout` 变成 None —— 只在"全新 clone + GBK locale"里复现，
   开发机常驻目录反而测不到（M1 干净环境验证实测）。
2. **交付面 ≠ 工作树**：`.venv/`（README 快速开始就把虚拟环境建在仓库里）和 `ledger.sqlite`
   这类运行期产物都被 gitignore 掉了。扫描交付面时必须按**已跟踪文件**来，
   否则任何照 README 做过干净环境验证的机器都会假红。
"""

import os
import subprocess

BINARY_SUFFIXES = (".pdf", ".docx", ".xlsx", ".zip", ".exe", ".png", ".jpg", ".db", ".sqlite")
TEXT_SUFFIXES = (".py", ".md", ".toml", ".yml", ".yaml", ".json", ".txt", ".cfg", ".ini", ".csv")


def is_scanned_dir(name):
    """会话内临时产物（.tmp_*）与本地虚拟环境都不属于交付面。"""
    return (
        name not in (".git", "__pycache__", "build", "dist", ".venv", "venv")
        and not name.startswith(".tmp_")
    )


def git_lines(root, args):
    return subprocess.run(
        ["git", "-c", "core.quotepath=false"] + list(args),
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )


def tracked_files(root):
    """已跟踪文件清单（仓库相对路径，正斜杠）。git 不可用或不在仓库内时返回 None。"""
    if not os.path.isdir(os.path.join(root, ".git")):
        return None
    proc = git_lines(root, ["ls-files"])
    if proc.returncode != 0 or proc.stdout is None:
        raise AssertionError("git ls-files 失败：%r" % (proc.stderr,))
    return [name for name in proc.stdout.splitlines() if name.strip()]


def walk_files(root, suffixes):
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if is_scanned_dir(d)]
        for name in files:
            if name.endswith(suffixes):
                out.append(os.path.join(dirpath, name))
    return out
