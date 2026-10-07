"""发布前脱敏扫描（M6 第 5 项的"四步"，一条命令跑完并出可核对的判定）。

四步各自回答一个问题：
1. **提交身份**：全历史的作者名 / 邮箱是不是同一条公开身份（不泄漏真实姓名与公司邮箱）；
2. **交付面字面**：已跟踪文本文件里有没有个人信息形态（邮箱/手机/身份证）、
   密钥 token、本机绝对路径、真实路线编号、真实行政区划代码；
3. **数据载荷结构**：演示数据的标识符逐字段过 `privacy` 白名单（结构判定，比正则可靠），
   依据登记 `register_ref` 指向的行是否真的存在；
4. **构建产物本体**：`dist/` 里的每一份载荷与仓库逐份 sha 对账，并按同一套字面规则扫一遍
   —— 打包会把数据搬进 exe 目录，只扫仓库会漏掉交付物的真身。

第 2/4 步的"命中"必须逐条给豁免理由才允许放行：合成数据项目里大量出现的是
**白名单反例语料**（测试里断言"这种形态必须被拒"）与 **保留号段示例**，
一律删字面就会删掉证据本身。豁免台账见 `EXEMPTIONS`，理由与来源写在那里。
"""

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from road_mqi_checker.privacy import PATTERNS, WHITELIST_HINTS  # noqa: E402
from road_mqi_checker.ruleset import loader  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_SUFFIXES = (".png", ".jpg", ".jpeg", ".ico", ".pdf", ".zip", ".gz", ".xlsx", ".exe", ".dll", ".pyd", ".so")

#: 字面扫描规则：名称 → (正则, 是否算违规的判定)
LITERAL_CHECKS = (
    ("邮箱（非 GitHub noreply）", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), lambda v: "noreply.github.com" not in v),
    ("手机号 11 位（白名单外）", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), lambda v: not PATTERNS["phone"].match(v)),
    ("身份证形态 18 位", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), lambda v: True),
    ("本机绝对路径/家目录", re.compile(r"[A-Za-z]:[\\/](?:Users|home|ProgramData|program)|/home/[a-z]+/"), lambda v: True),
    ("密钥/Token 形态", re.compile(r"(gh[po]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|xox[baprs]-|AKIA[0-9A-Z]{16}|-{5}BEGIN)"), lambda v: True),
    # 白名单内的虚构编号（S99 / X990 / Y999 / Z9901）不算违规；G/S 开头的真实国道省道才算
    ("真实形态路线编号", re.compile(r"(?<![A-Za-z0-9])[GSXYZ]\d{2,4}(?![A-Za-z0-9])"),
     lambda v: not PATTERNS["route_id"].match(v)),
)

#: 豁免台账：(规则名, 路径正则) → 理由。命中且被豁免的必须能在这里找到出处。
EXEMPTIONS = (
    (
        "邮箱（非 GitHub noreply）",
        r"tests/",
        "RFC 2606 保留示例域 `example.invalid`，是拒入用例的语料，不是可投递地址",
    ),
    (
        "手机号 11 位（白名单外）",
        r"tests/",
        "白名单反例语料：这些测试断言的正是「真实号段必须被 privacy 闸门拒绝」，删掉就没证据了",
    ),
    (
        "身份证形态 18 位",
        r"tests/test_determinism_rng\.py",
        "splitmix64 冻结向量（19~20 位 u64 数字串）撞上 18 位形态，见 plan/HANDOFF-M1 §一 第 2 条",
    ),
    (
        "本机绝对路径/家目录",
        r"tests/",
        "导出闸门的负向用例：斜杠 home 形态与盘符 Users 形态的构造字符串（本文件与用例都不写原样形态，"
        "否则扫描器会被自己的示例文本自命中），用来证明导出层会拒绝绝对路径（test_m6_report.py）",
    ),
    (
        "真实形态路线编号",
        r"^(tests/|data/README\.md|plan/)",
        "白名单反例语料：这些位置写的是「真实国道/高速编号一律拒绝入库」，属登记与测试证据",
    ),
    (
        "真实形态路线编号",
        r"^README\.md",
        "同上：README 的限制说明里引用反例形态",
    ),
)


def _exempt(rule, rel):
    for name, pattern, reason in EXEMPTIONS:
        if name == rule and re.search(pattern, rel.replace(os.sep, "/")):
            return reason
    return None


def _tracked_text_files():
    raw = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True).stdout.decode("utf-8")
    out = []
    for rel in [name for name in raw.split("\0") if name]:
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(path) or rel.lower().endswith(BIN_SUFFIXES):
            continue
        out.append((rel, path))
    return out


def step_identity():
    """第 1 步：全历史提交身份。"""
    lines = subprocess.run(
        ["git", "log", "--format=%an|%ae"], cwd=ROOT, capture_output=True
    ).stdout.decode("utf-8").splitlines()
    identities = sorted(set(lines))
    bad = [item for item in identities if not item.split("|")[1].endswith("@users.noreply.github.com")]
    print("[1] 提交身份 %d 条：%s" % (len(identities), "; ".join(identities)))
    print("    提交总数 %d；非 noreply 邮箱 %d 条" % (len(lines), len(bad)))
    for item in bad:
        print("    !! 未通过：", item)
    return len(bad) == 0


def _literal_scan(items, label):
    hits = []
    for rel, path in items:
        try:
            text = open(path, "r", encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        for rule, pattern, predicate in LITERAL_CHECKS:
            for match in pattern.finditer(text):
                value = match.group(0)
                if not predicate(value):
                    continue
                line = text[: match.start()].count("\n") + 1
                reason = _exempt(rule, rel)
                hits.append((rule, "%s:%d %s" % (rel, line, value[:36]), reason))
    total = len(hits)
    waived = len([item for item in hits if item[2]])
    print("[%s] 命中 %d 处，其中已豁免 %d 处，未豁免 %d 处" % (label, total, waived, total - waived))
    for rule, where, reason in hits:
        if reason is None:
            print("    !! %s @ %s" % (rule, where))
    for rule, _where, reason in hits:
        if reason:
            print("    · 豁免「%s」：%s" % (rule, reason))
            break
    return total - waived == 0


def step_tracked():
    """第 2 步：交付面字面扫描（已跟踪文本文件）。"""
    items = _tracked_text_files()
    print("[2] 已跟踪文本文件 %d 份" % len(items))
    big = [
        (rel, os.path.getsize(path))
        for rel, path in items
        if rel.endswith((".txt", ".md")) and os.path.getsize(path) > 200 * 1024
    ]
    print("    超 200KB 的 txt/md（标准全文嫌疑）：%d 份 %s" % (len(big), big or "无"))
    binaries = [
        rel for rel in subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True)
        .stdout.decode("utf-8", "replace").splitlines() if rel.lower().endswith(BIN_SUFFIXES)
    ]
    print("    已跟踪二进制文件：%d 份 %s" % (len(binaries), binaries or "无"))
    return _literal_scan(items, "2b") and not big and not binaries


def step_data_structure():
    """第 3 步：数据载荷逐字段过白名单 + 依据登记行存在。"""
    import csv
    import json

    data_dir = os.path.join(ROOT, "data")
    checked = 0
    violations = []
    for name in sorted(os.listdir(os.path.join(data_dir, "raw"))):
        if not name.endswith(".csv"):
            continue
        with open(os.path.join(data_dir, "raw", name), "r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                checked += 1
                for field, value in row.items():
                    kind = _kind_for(field)
                    if kind is None:
                        continue
                    if value in (None, ""):
                        continue
                    if not PATTERNS[kind].match(str(value)):
                        violations.append("%s %s=%s" % (name, field, value))
    with open(os.path.join(data_dir, "raw", "manifest.json"), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    print("[3] 演示数据行 %d 条，标识符白名单越界 %d 处 %s" % (checked, len(violations), violations[:5]))
    print("    manifest 数据类别：%s / 文件数：%s" % (manifest.get("data_class"), len(manifest.get("files", []))))
    ref_bad = []
    for path in loader.list_ruleset_files():
        ruleset = loader.load_file(path, allow_fixture=False)
        ref_bad.extend(
            coef.key for coef in ruleset.coefficients if coef.register_ref and not _ref_line_exists(coef.register_ref)
        )
    print("    register_ref 指向的行不存在：%d 个 %s" % (len(ref_bad), ref_bad[:5]))
    print("    白名单形式说明：%s" % WHITELIST_HINTS["route_id"])
    return not violations and not ref_bad and manifest.get("data_class") == "SYNTHETIC"


def _kind_for(field_name):
    mapping = {
        "route_id": "route_id",
        "adcode": "adcode",
        "segment_name": "segment_name",
        "start_stake": "stake",
        "end_stake": "stake",
        "detect_org": "org_name",
        "client_org": "org_name",
        "phone": "phone",
        "report_no": "report_no",
        "commission_no": "report_no",
        "doi": "doi",
    }
    return mapping.get(field_name)


def _ref_line_exists(register_ref):
    """`data/README.md#N`：该行必须真的存在（题目要求的可回指）。"""
    if "#" not in register_ref:
        return False
    relative, line_no = register_ref.split("#", 1)
    path = os.path.join(ROOT, relative.replace("/", os.sep))
    if not os.path.isfile(path):
        return False
    try:
        index = int(line_no)
    except ValueError:
        return False
    with open(path, "r", encoding="utf-8") as handle:
        for position, _line in enumerate(handle, 1):
            if position == index:
                return True
    return False


def step_build(dist_dir):
    """第 4 步：构建产物本体扫描 + 与仓库逐份 sha 对账。"""
    import hashlib

    if not os.path.isdir(dist_dir):
        print("[4] 构建目录不存在：%s（先跑 PyInstaller）" % dist_dir)
        return False
    embedded = []
    for dirpath, dirs, files in os.walk(dist_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            embedded.append(os.path.relpath(os.path.join(dirpath, name), dist_dir).replace(os.sep, "/"))
    payloads = [rel for rel in embedded if rel.endswith((".csv", ".json", ".md", ".txt"))]
    print("[4] 构建目录内文件 %d 份，其中数据/文本载荷 %d 份" % (len(embedded), len(payloads)))
    fixture = [rel for rel in payloads if "fixture" in rel.lower()]
    print("    路径含 fixture 的载荷：%d 份 %s" % (len(fixture), fixture or "无"))
    docs = [rel for rel in embedded if rel.lower().endswith((".pdf", ".doc", ".docx"))]
    print("    标准原文类二进制（pdf/doc）：%d 份 %s" % (len(docs), docs or "无"))
    mismatch = []
    missing = 0
    for rel in payloads:
        if "/data/" not in "/" + rel:
            continue
        tail = rel.split("/data/", 1)[1]
        repo_path = os.path.join(ROOT, "data", tail.replace("/", os.sep))
        if not os.path.isfile(repo_path):
            missing += 1
            continue
        build_sha = hashlib.sha256(open(os.path.join(dist_dir, rel.replace("/", os.sep)), "rb").read()).hexdigest()
        repo_sha = hashlib.sha256(open(repo_path, "rb").read()).hexdigest()
        if build_sha != repo_sha:
            mismatch.append(tail)
    expected = sum(
        len([name for name in os.listdir(os.path.join(ROOT, "data", sub)) if name.endswith((".csv", ".json", ".md"))])
        for sub in ("raw", "truth")
    ) + 1  # data/README.md
    print(
        "    与仓库逐份 sha 对账：比对 %d 份，不一致 %d 份 %s；包内 data 载荷缺仓库对应 %d 份"
        % (len(payloads) - missing, len(mismatch), mismatch[:5], missing)
    )
    print("    仓库应内嵌的数据载荷 %d 份（raw+truth+manifest+README）" % expected)
    items = [(rel, os.path.join(dist_dir, rel.replace("/", os.sep))) for rel in payloads]
    literal_ok = _literal_scan(items, "4b")
    return literal_ok and not fixture and not docs and not mismatch and not missing


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dist_dir = argv[0] if argv else os.path.join(ROOT, "dist")
    print("== road-mqi-checker 发布前脱敏扫描（仓库：%s）==" % ROOT)
    results = {
        "1 提交身份": step_identity(),
        "2 交付面字面": step_tracked(),
        "3 数据结构": step_data_structure(),
        "4 构建产物": step_build(dist_dir),
    }
    for name, ok in results.items():
        print("%-12s %s" % (name, "通过" if ok else "未通过"))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
