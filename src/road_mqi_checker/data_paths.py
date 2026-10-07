"""数据目录与内嵌资源的查找优先级（打包态与源码态共用一套内核的根）。

优先级是既定口径，改动会打挂 exe 验证，因此由测试逐分支锁死：

    显式参数 > 环境变量 RMQC_DATA_DIR > 冻结态内嵌（sys._MEIPASS/data）
    > exe 目录 _internal/data（PyInstaller 5 兼容）> 从起始目录上溯找 data/

冻结分支必须存在：exe 在中立目录（无仓库树）运行时，只允许命中内嵌数据；
若在仓库树内跑验证，上溯分支会命中仓库 data/，"内嵌数据"就验了个寂寞。
"""

import os
import sys
from typing import List, Optional

from road_mqi_checker.errors import InputUnavailable

ENV_DATA_DIR = "RMQC_DATA_DIR"
_DIR_NAME = "data"
_MARKER_FILE = "README.md"


def is_frozen():
    # type: () -> bool
    return bool(getattr(sys, "frozen", False))


def _meipass_dir():
    return getattr(sys, "_MEIPASS", None)


def candidate_dirs(explicit=None, start=None, env=None):
    # type: (Optional[str], Optional[str], Optional[str]) -> List[str]
    """按优先级返回候选目录（不保证存在），供 find_data_dir 与测试共用。"""
    if env is None:
        env = os.environ.get(ENV_DATA_DIR)
    candidates = []  # type: List[str]
    if explicit:
        candidates.append(explicit)
    if env:
        candidates.append(env)
    meipass = _meipass_dir()
    if meipass:
        candidates.append(os.path.join(meipass, _DIR_NAME))
    if is_frozen():
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, "_internal", _DIR_NAME))
        candidates.append(os.path.join(exe_dir, _DIR_NAME))
    base = os.path.abspath(start or os.getcwd())
    current = base
    while True:
        candidates.append(os.path.join(current, _DIR_NAME))
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return candidates


def find_data_dir(explicit=None, start=None, require_marker=True):
    # type: (Optional[str], Optional[str], bool) -> str
    """返回第一个存在（且可选地含标记文件）的 data 目录。"""
    for candidate in candidate_dirs(explicit=explicit, start=start):
        if not os.path.isdir(candidate):
            continue
        if require_marker and not os.path.isfile(os.path.join(candidate, _MARKER_FILE)):
            continue
        return candidate
    raise InputUnavailable(
        "找不到数据目录：已按优先级尝试（显式参数 / 环境变量 %s / 冻结内嵌 / 上溯查找），"
        "源码态请在仓库根运行或设置 %s" % (ENV_DATA_DIR, ENV_DATA_DIR)
    )


def resolve_relative(relative_path, explicit=None, start=None):
    # type: (str, Optional[str], Optional[str]) -> str
    return os.path.join(find_data_dir(explicit=explicit, start=start), *relative_path.split("/"))
