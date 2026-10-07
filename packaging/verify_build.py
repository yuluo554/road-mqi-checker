# -*- coding: utf-8 -*-
"""构建后递归红线断言（M6 交付层，纯标准库，py3.8 / py3.12 均可跑）。

对 PyInstaller onedir 产物 `dist/rmqc/`（含 `rmqc.exe` / `rmqc-gui.exe` / `_internal/`）逐条真做四类红线断言，
外加 exe 自带数据可用性检查。任何一条不过 -> 非零退出码；全过 -> 打印每步实测数字。

    [1] 内嵌数据与仓库逐份 sha256 对账：raw 12 + manifest.json + truth 12 + README.md = 26 份，
        数量与内容都要对得上（少一份 / 多一份 / 内容不一致都算失败）。
    [2] 无夹具字样：递归扫包内 .json/.csv/.txt/.md 载荷，出现 fixture（不分大小写）即失败。
        data/README.md 是数据台账文档（其 fixture 提及只是机制/测试名引用），按
        tests/test_release_redlines.py 的常驻红线口径豁免该台账文档，其余载荷一律实扫。
    [3] 无真实形态标识符：从包内 CSV/JSON 载荷抽 route / 6 位行政代码 / 手机号形态 token，
        逐个反查合成白名单（镜像 road_mqi_checker.privacy.PATTERNS），任何不在白名单内即失败。
    [4] 无标准全文：包内不得有 .pdf/.doc/.docx；交付文本载荷（内嵌 data/ + rulesets/）不得有
        单文件 > 200KB 的 .txt/.md。
    [5] exe 自带数据可用：在中立空目录（%LOCALAPPDATA%\\Temp 下、绝不在仓库树里）跑
        rmqc.exe --json selfcheck（--json 是顶层全局选项，须排在子命令前），断言 data_dir 指向包内路径且不是仓库路径。

用法：python packaging/verify_build.py [PACKAGE_DIR]
      PACKAGE_DIR 默认 = <repo>/dist/rmqc
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

# ---- 路径根（脚本在 <repo>/packaging/ 下）----
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
REPO_DATA = os.path.join(REPO, "data")
PKG_DIR = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(REPO, "dist", "rmqc")

# ---- 内嵌数据白名单（与 packaging/rmqc.spec 同一份口径）----
ROUTE_IDS = ("S99", "X990", "Y999")
YEARS = (2022, 2023, 2024, 2025)
RAW_NAMES = sorted("%s-%d.csv" % (r, y) for r in ROUTE_IDS for y in YEARS)
TRUTH_NAMES = sorted("%s-%d.truth.csv" % (r, y) for r in ROUTE_IDS for y in YEARS)

# ---- 合成白名单镜像（口径来自 road_mqi_checker.privacy.PATTERNS）----
# 纯标准库自检不依赖包能被 import（冻结态/中立目录无 PYTHONPATH），故逐字复刻白名单。
WL_ROUTE = re.compile(r"^[SXYZ](?:9{2,3}|99[0-9]{1,2})$")
WL_ADCODE = re.compile(r"^99\d{4}$")
WL_PHONE = re.compile(r"^1990000\d{4}$")

# 真实形态抽取（反查用）：路线形态含 G/S（国道/省道），行政代码 6 位，手机 11 位。
FORM_ROUTE = re.compile(r"\b[GSG]\d{1,4}\b")
FORM_ADCODE = re.compile(r"\b\d{6}\b")
FORM_PHONE = re.compile(r"\b1\d{10}\b")

PAYLOAD_TEXT_EXTS = (".json", ".csv", ".txt", ".md")
PAYLOAD_DATA_EXTS = (".csv", ".json")          # 真实形态只从 CSV/JSON 载荷抽
STANDARD_DOC_EXTS = (".pdf", ".doc", ".docx")  # 全包禁入
BIG_TEXT_LIMIT = 200 * 1024                    # 200KB

_failures = []
_notes = []


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def _inside(child, parent):
    child, parent = _norm(child), _norm(parent)
    return child == parent or child.startswith(parent + os.sep)


def _fail(msg):
    _failures.append(msg)
    print("  [FAIL] %s" % msg)


def _ok(msg):
    print("  [ok]   %s" % msg)


def locate_internal():
    """PyInstaller 6 onedir：数据在 <PKG>/_internal/；兼容 <PKG>/data 布局。"""
    internal = os.path.join(PKG_DIR, "_internal")
    if os.path.isdir(os.path.join(internal, "data")):
        return internal
    if os.path.isdir(os.path.join(PKG_DIR, "data")):
        return PKG_DIR
    return internal


def find_exe(stem):
    for suffix in (".exe", ""):
        cand = os.path.join(PKG_DIR, stem + suffix)
        if os.path.isfile(cand):
            return cand
    for name in os.listdir(PKG_DIR):
        if name.lower() == (stem + ".exe"):
            return os.path.join(PKG_DIR, name)
    return None


def check_1_sha256(internal):
    print("[1] 内嵌数据与仓库逐份 sha256 对账")
    embedded_data = os.path.join(internal, "data")
    if not os.path.isdir(embedded_data):
        _fail("包内找不到 data/：%s" % embedded_data)
        return

    def compare_pair(rel_under_data, expected_present=True):
        repo_path = os.path.join(REPO_DATA, rel_under_data.replace("/", os.sep))
        emb_path = os.path.join(embedded_data, rel_under_data.replace("/", os.sep))
        if not os.path.isfile(repo_path):
            _fail("仓库侧缺少基线文件：%s" % rel_under_data)
            return None
        if not os.path.isfile(emb_path):
            _fail("包内缺少内嵌文件：%s" % rel_under_data)
            return None
        repo_sha = _sha256(repo_path)
        emb_sha = _sha256(emb_path)
        if repo_sha != emb_sha:
            _fail("sha256 不一致：%s (repo=%s pkg=%s)" % (rel_under_data, repo_sha[:12], emb_sha[:12]))
            return None
        return emb_sha

    # raw：逐份 + 数量对账
    raw_ok = 0
    for name in RAW_NAMES:
        if compare_pair("raw/" + name) is not None:
            raw_ok += 1
    if compare_pair("raw/manifest.json") is not None:
        raw_ok += 1
    _check_no_extras(os.path.join(embedded_data, "raw"),
                     set(RAW_NAMES + ["manifest.json"]), "data/raw")

    # truth：逐份 + 数量对账
    truth_ok = 0
    for name in TRUTH_NAMES:
        if compare_pair("truth/" + name) is not None:
            truth_ok += 1
    _check_no_extras(os.path.join(embedded_data, "truth"), set(TRUTH_NAMES), "data/truth")

    # README.md 标记 / 台账
    readme_ok = compare_pair("README.md") is not None
    _check_no_extras(embedded_data, {"README.md"}, "data(top-level entries below are allowed as dirs)")

    total_expected = len(RAW_NAMES) + 1 + len(TRUTH_NAMES) + 1
    print("  期望 26 份（raw %d + manifest 1 + truth %d + README 1），实际匹配 sha256：raw/manifest %d 份、truth %d 份、README %s"
          % (len(RAW_NAMES), len(TRUTH_NAMES), raw_ok, truth_ok, "对" if readme_ok else "缺/不一致"))
    if raw_ok + truth_ok + (1 if readme_ok else 0) != total_expected:
        _fail("对账份数不足：应为 %d，实得 %d" % (total_expected, raw_ok + truth_ok + (1 if readme_ok else 0)))
    else:
        _ok("全部 %d 份内嵌数据与仓库逐字节 sha256 一致，且无多余文件" % total_expected)


def _check_no_extras(dirpath, allowed_files, label):
    """目录里出现白名单外的文件即失败（.gitkeep 之类未列入交付白名单，出现即判多余）。"""
    if not os.path.isdir(dirpath):
        _fail("目录缺失：%s (%s)" % (dirpath, label))
        return
    if label.startswith("data(top-level"):
        # data 顶层允许 raw/ truth/ 两个子目录 + README.md
        present = sorted(os.listdir(dirpath))
        subdirs = [n for n in present if os.path.isdir(os.path.join(dirpath, n))]
        files = [n for n in present if not os.path.isdir(os.path.join(dirpath, n))]
        extra_files = [n for n in files if n not in allowed_files]
        extra_dirs = [n for n in subdirs if n not in ("raw", "truth")]
        if extra_files or extra_dirs:
            _fail("data 顶层出现交付白名单外的条目：文件%s 目录%s" % (extra_files, extra_dirs))
        else:
            _ok("data 顶层条目符合白名单：文件=%s 子目录=%s" % (files, subdirs))
        return
    present = sorted(os.listdir(dirpath))
    extra = [n for n in present if n not in allowed_files]
    if extra:
        _fail("%s 出现白名单外/多余文件：%s" % (label, extra))
    else:
        _ok("%s 文件数=%d（与白名单一致，无多余）" % (label, len(present)))


def _iter_payload_files(internal, exts):
    roots = [os.path.join(internal, "data"), os.path.join(internal, "road_mqi_checker", "rulesets")]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if name.lower().endswith(exts):
                    yield os.path.join(root, dirpath, name)


def check_2_fixture(internal):
    print("[2] 无夹具字样（递归扫 .json/.csv/.txt/.md 载荷）")
    scanned = 0
    exempt = 0
    hits = []
    for path in _iter_payload_files(internal, PAYLOAD_TEXT_EXTS):
        rel = os.path.relpath(path, internal).replace(os.sep, "/")
        if rel == "data/README.md":
            # 数据台账文档：按常驻红线 test_release_redlines 口径豁免（其 fixture 提及是机制/测试名引用，非数据污染）
            exempt += 1
            continue
        scanned += 1
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except Exception as exc:  # noqa: BLE001
            _fail("读取失败：%s (%s)" % (rel, exc))
            continue
        if "fixture" in text.lower():
            hits.append(rel)
    print("  扫描载荷文本文件 %d 份，豁免台账文档 data/README.md %d 份，夹具字样命中 %d 处"
          % (scanned, exempt, len(hits)))
    if hits:
        for h in hits:
            _fail("夹具字样出现在交付载荷：%s" % h)
    else:
        _ok("交付载荷（csv/json/txt/md，除台账文档）无 fixture 字样")


def check_3_real_identifiers(internal):
    print("[3] 无真实形态标识符（CSV/JSON 载荷反查合成白名单）")
    files = 0
    route_tokens = 0
    adcode_tokens = 0
    phone_tokens = 0
    offenders = []
    for path in _iter_payload_files(internal, PAYLOAD_DATA_EXTS):
        files += 1
        rel = os.path.relpath(path, internal).replace(os.sep, "/")
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for tok in FORM_ROUTE.findall(text):
            route_tokens += 1
            if not WL_ROUTE.match(tok):
                offenders.append("%s: route %r 不在白名单" % (rel, tok))
        for tok in FORM_ADCODE.findall(text):
            adcode_tokens += 1
            if not WL_ADCODE.match(tok):
                offenders.append("%s: adcode %r 不在白名单（非 99 开头）" % (rel, tok))
        for tok in FORM_PHONE.findall(text):
            phone_tokens += 1
            if not WL_PHONE.match(tok):
                offenders.append("%s: phone %r 不在白名单（非 1990000 开头）" % (rel, tok))
    print("  扫描 CSV/JSON 载荷 %d 份；route 形态 token %d 个、6 位码 token %d 个、手机号 token %d 个；越界 %d 个"
          % (files, route_tokens, adcode_tokens, phone_tokens, len(offenders)))
    if offenders:
        for o in offenders:
            _fail(o)
    else:
        _ok("全部 route/行政代码/手机号形态 token 均在合成白名单内，无真实形态标识符")


def check_4_no_standard_text(internal):
    print("[4] 无标准全文（禁 .pdf/.doc/.docx + 载荷 .txt/.md <=200KB）")
    # 4a 全包禁标准原文档
    doc_hits = []
    for dirpath, _dirs, files in os.walk(PKG_DIR):
        for name in files:
            if name.lower().endswith(STANDARD_DOC_EXTS):
                doc_hits.append(os.path.relpath(os.path.join(dirpath, name), PKG_DIR).replace(os.sep, "/"))
    print("  全包扫描 .pdf/.doc/.docx：%d 个（要求 0）" % len(doc_hits))
    if doc_hits:
        for h in doc_hits:
            _fail("包内出现标准原文档类文件：%s" % h)
    else:
        _ok("包内无 .pdf/.doc/.docx 标准原文档")

    # 4b 交付文本载荷大小（只查内嵌 data/ + rulesets/，Qt 运行期许可文本不属交付文本）
    big = []
    max_bytes = 0
    max_name = ""
    count = 0
    for path in _iter_payload_files(internal, (".txt", ".md")):
        count += 1
        size = os.path.getsize(path)
        rel = os.path.relpath(path, internal).replace(os.sep, "/")
        if size > max_bytes:
            max_bytes, max_name = size, rel
        if size > BIG_TEXT_LIMIT:
            big.append("%s (%d bytes)" % (rel, size))
    print("  交付文本载荷 .txt/.md %d 份，最大单文件 %d bytes (%s)，>200KB %d 份"
          % (count, max_bytes, max_name or "-", len(big)))
    if big:
        for b in big:
            _fail("交付文本载荷超 200KB，疑似标准全文：%s" % b)
    else:
        _ok("交付文本载荷均 <=200KB")


def check_5_frozen_data(internal):
    print("[5] exe 自带数据可用（中立空目录跑 rmqc --json selfcheck）")
    exe = find_exe("rmqc")
    if exe is None:
        _fail("找不到 rmqc.exe（在 %s）" % PKG_DIR)
        return
    base = os.environ.get("LOCALAPPDATA")
    tmp_root = os.path.join(base, "Temp") if base else tempfile.gettempdir()
    neutral = tempfile.mkdtemp(prefix="rmqc-verify-neutral-", dir=tmp_root)
    if _inside(neutral, REPO):
        _fail("中立目录落到了仓库树里：%s" % neutral)
        return
    print("  中立目录（仓库外空目录）：%s" % neutral)
    try:
        env = dict(os.environ)
        env.pop("RMQC_DATA_DIR", None)
        env.pop("PYTHONPATH", None)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # --json 是顶层全局选项，argparse 口径必须排在子命令之前：rmqc --json selfcheck
        proc = subprocess.Popen([exe, "--json", "selfcheck"], cwd=neutral, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
    finally:
        import shutil
        shutil.rmtree(neutral, ignore_errors=True)
    if proc.returncode != 0:
        _fail("rmqc selfcheck --json 退出码=%d（期望 0）；stderr=%s"
              % (proc.returncode, err.decode("utf-8", "replace")[:400]))
        return
    try:
        payload = json.loads(out.decode("utf-8", "replace"))
    except ValueError as exc:
        _fail("selfcheck --json 无法解析：%s；前 400 字节=%s" % (exc, out[:400]))
        return
    data_dir = payload.get("data_dir")
    print("  selfcheck 报告 data_dir = %r（frozen=%s）" % (data_dir, payload.get("frozen")))
    if not data_dir:
        _fail("data_dir 为空，内嵌数据未命中")
        return
    resolved = os.path.realpath(data_dir)
    # 关键判据：data_dir 不能是仓库源码数据目录 <repo>/data（上溯分支会命中它，让"内嵌"验了个寂寞）。
    # 注意产物目录 dist/rmqc 本身也在仓库根之下，所以只针对 <repo>/data 做"仓库态"判定，不能拿仓库根比。
    if _inside(resolved, REPO_DATA):
        _fail("data_dir 落到了仓库源数据目录（内嵌验了个寂寞）：%s" % data_dir)
    elif _inside(resolved, internal) or _inside(resolved, PKG_DIR):
        _ok("data_dir 指向包内路径且非仓库源 data/，确认是 exe 自带数据：%s" % data_dir)
    else:
        _fail("data_dir 既不在包内也不是可解释的仓库源数据，来源不明：%s" % data_dir)


def main():
    print("=" * 72)
    print("PyInstaller 构建后红线断言")
    print("  PKG_DIR = %s" % PKG_DIR)
    print("  REPO    = %s" % REPO)
    if not os.path.isdir(PKG_DIR):
        print("[FATAL] 产物目录不存在：%s（先跑 PyInstaller 构建）" % PKG_DIR)
        return 2
    internal = locate_internal()
    print("  _internal = %s" % internal)
    print("=" * 72)

    check_1_sha256(internal)
    check_2_fixture(internal)
    check_3_real_identifiers(internal)
    check_4_no_standard_text(internal)
    check_5_frozen_data(internal)

    print("=" * 72)
    if _failures:
        print("结论：失败（%d 项）" % len(_failures))
        for f in _failures:
            print("  - %s" % f)
        return 1
    print("结论：全部 5 类红线断言通过")
    for n in _notes:
        print("  · %s" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
