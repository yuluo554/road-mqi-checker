# -*- coding: utf-8 -*-
"""README 自述测试计数守门（2026-10-22 新增）。

## 为什么有这个文件

README 里两处写死了测试项数（「490 项守门测试断言…」与「各收集 490 项、各 490 通过」）。
这个数字**没有任何门盯着**，于是每加一个测试它就漂一次：本次修复前是 489，
新增 5 项 `test_cli_zip_shape.py` 后实测 490，而 README 仍是 489。

本文件把"自述计数 == 实际收集数"变成硬门：改测试而不改 README（或反过来）都会红。

## 口径

- 取 `pytest --collect-only -q` 的 collected 数（含 skipped，因为 README 的措辞是"收集"）；
- 只认 README 里 `N 项守门测试` 与 `各收集 N 项` 两种句式，两处必须相等且等于实际值。
"""

import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
README = os.path.join(REPO, "README.md")


def _collected_count():
    """实际收集数（含 skip）。"""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    # 末行形如 "490 tests collected in 0.30s" 或 "490/490 tests collected"
    m = re.search(r"(\d+)\s+tests?\s+collected", out.stdout)
    assert m, "无法从 pytest --collect-only 输出里解析收集数：\n%s" % out.stdout[-800:]
    return int(m.group(1))


def test_readme_test_count_matches_collected():
    """README 两处自述计数必须相等，且等于实际收集数。"""
    readme = open(README, encoding="utf-8").read()

    claims = []
    for pattern, label in (
        (r"(\d+)\s*项守门测试", "「N 项守门测试」"),
        (r"各收集\s*(\d+)\s*项", "「各收集 N 项」"),
    ):
        found = re.findall(pattern, readme)
        assert found, "README 里找不到 %s 这句自述（句式变了就要同步改本门）" % label
        for value in set(found):
            claims.append((label, int(value)))

    distinct = {value for _, value in claims}
    assert len(distinct) == 1, "README 内部自述计数不一致：%s" % sorted(claims)

    actual = _collected_count()
    assert distinct.pop() == actual, (
        "README 自述 %s 项，实际收集 %d 项。"
        "新增/删除测试后必须同步 README 的两处数字。"
        % (sorted({v for _, v in claims})[0], actual)
    )
