# -*- coding: utf-8 -*-
"""README 自述测试计数守门（2026-10-22 新增，同日补第二批）。

## 为什么有这个文件

README 里写死了测试项数（「N 项守门测试断言…」、「各收集 N 项」与「各 N 通过」）。
这个数字**没有任何门盯着**，于是每加一个测试它就漂一次：本次修复前是 489，
新增 5 项 `test_cli_zip_shape.py` 后实测 490，而 README 仍是 489。

本文件把"自述计数 == 实际收集数"变成硬门：改测试而不改 README（或反过来）都会红。

## 第二批补的盲区（2026-10-22 第二轮复验发现）

第一版只认 `N 项守门测试` 与 `各收集 N 项` 两种句式，锁的是**收集数**；
同一句里的「各 490 通过」（实际 491）**完全裸奔**——把它改成荒谬的「各 999 通过」门仍然绿。

所以本版追加：
- 第三种句式 `各 N 通过`，锁**通过数**；
- 「N 项声明式跳过」的跳过数；
- **算术一致性**断言：`收集数 == 通过数 + 跳过数`（495 == 491 + 4）。
  这比"各自等于某个固定值"更难绕过：只改一个数字必然破坏等式。

## 口径

- 取 `pytest --collect-only -q` 的 collected 数（含 skipped，因为 README 的措辞是"收集"）；
- 断言全在一个测试函数里，这样本门自身不会改变收集数（否则每次改门都要改 README，递归）。
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
    # 末行形如 "495 tests collected in 0.30s" 或 "495/495 tests collected"
    m = re.search(r"(\d+)\s+tests?\s+collected", out.stdout)
    assert m, "无法从 pytest --collect-only 输出里解析收集数：\n%s" % out.stdout[-800:]
    return int(m.group(1))


def _claims(readme):
    """把 README 里各句式自述的数字取成 {label: {值集合}}。"""
    patterns = (
        (r"(\d+)\s*项守门测试", "项守门测试"),
        (r"各收集\s*(\d+)\s*项", "各收集N项"),
        (r"各\s*(\d+)\s*通过", "各N通过"),
        (r"(\d+)\s*项声明式跳过", "项声明式跳过"),
    )
    out = {}
    for pattern, label in patterns:
        found = set(re.findall(pattern, readme))
        assert found, "README 里找不到「%s」这句自述（句式变了就要同步改本门）" % label
        assert len(found) == 1, "README 里「%s」出现多个不同值：%s" % (label, sorted(found))
        out[label] = int(found.pop())
    return out


def test_readme_test_count_matches_collected():
    """README 自述的收集数必须等于实际收集数，且 收集 == 通过 + 跳过。"""
    readme = open(README, encoding="utf-8").read()
    claims = _claims(readme)

    # 1) 收集数：两处自述必须相等
    assert claims["项守门测试"] == claims["各收集N项"], (
        "README 内部收集数不一致：「N 项守门测试」= %d、「各收集 N 项」= %d"
        % (claims["项守门测试"], claims["各收集N项"])
    )

    # 2) 收集数：自述必须等于实际（新增/删除测试后要同步 README）
    actual = _collected_count()
    assert claims["各收集N项"] == actual, (
        "README 自述收集 %d 项，实际收集 %d 项。"
        "新增/删除测试后必须同步 README 的三处数字。"
        % (claims["各收集N项"], actual)
    )

    # 3) 算术一致性：收集 == 通过 + 跳过。
    #    只锁"各自等于某个值"会被单点改动绕过（把 491 改成 999 就漏），
    #    等式会同时锁住两个数字之间的关系。
    total = claims["各收集N项"]
    passed = claims["各N通过"]
    skipped = claims["项声明式跳过"]
    assert total == passed + skipped, (
        "README 自述算术不自洽：收集 %d ≠ 通过 %d + 跳过 %d（差 %d）。"
        "改通过数或跳过数时必须同步收集数。"
        % (total, passed, skipped, total - passed - skipped)
    )
