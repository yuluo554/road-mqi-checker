"""全离线 + 确定性纪律门。

两条通道各管一半：
- 词法扫描管"绝对禁止"（联网客户端、LLM 客户端、stdlib random 进生成路径）；
- 行为探针管"实际没联网"（把 socket 连接换成抛异常后 selfcheck 照常跑完）。
数值通路用探针证伪而不是只写静态断言 —— 静态禁令容易误伤真实依赖。
"""

import os
import re
import socket
import sys

import pytest

from road_mqi_checker import cli

NETWORK_TOKENS = (
    "urllib.request",
    "urllib.error",
    "http.client",
    "import socket",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
)
LLM_TOKENS = ("openai", "anthropic", "langchain", "ollama", "dashscope")


def _src_py_files(repo_root):
    root = os.path.join(repo_root, "src")
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".py"):
                out.append(os.path.join(dirpath, name))
    assert out, "src 下一个 .py 都没有，测试对象不存在"
    return sorted(out)


def _scan(path, tokens):
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for token in tokens:
            if token in line:
                hits.append((lineno, token, line.strip()))
    return hits


def test_no_network_or_llm_tokens_in_kernel(repo_root):
    offenders = []
    for path in _src_py_files(repo_root):
        for lineno, _token, line in _scan(path, NETWORK_TOKENS + LLM_TOKENS):
            offenders.append("%s:%d %s" % (path, lineno, line))
    assert not offenders, "内核出现网络/LLM 引用：%s" % offenders


def test_stdlib_random_not_used(repo_root):
    """合成数据与评定的随机源只能是 bench.rng（stdlib random 序列不承诺跨版本一致）。"""
    offenders = []
    for path in _src_py_files(repo_root):
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        if re.search(r"^\s*(?:import\s+random|from\s+random\s+import)", text, re.M):
            offenders.append(path)
    assert not offenders, "禁用 stdlib random：%s" % offenders


def test_selfcheck_runs_with_network_disabled(monkeypatch, repo_root):
    """行为探针：网络被切断时 selfcheck 仍应跑完并返回 0。"""

    def _blocked(*args, **kwargs):
        raise AssertionError("内核试图联网")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setenv("RMQC_DATA_DIR", os.path.join(repo_root, "data"))
    rc = cli.main(["selfcheck"])
    assert rc == 0, "selfcheck 断网下应返回 0，实际 %r" % rc
    assert os.path.abspath(repo_root) in os.path.abspath(sys.modules["road_mqi_checker"].__file__)
