"""隐私与合成数据白名单校验（题目红线：演示数据不得出现真实路线/行政代码/号段）。

白名单以 data/README.md §三 为准；新增形式要先在该文件登记，再来这里加一条正则。
校验是"拒绝式"的：不在白名单内即 PrivacyViolation，生成器与导入器都不得放行。
"""

import re
from typing import Dict, Iterable, Mapping, Optional

from road_mqi_checker.errors import PrivacyViolation

SYNTHETIC_FILE_MARK = "SYNTHETIC"

#: 允许的标识符形态；kind 名与 data/README §三 的类别一一对应
PATTERNS = {
    # 虚构路线编号：字母限 S/X/Y/Z，数字段必须"明显虚构"（全 9 或以 99 开头）
    "route_id": re.compile(r"^[SXYZ](?:9{2,3}|99[0-9]{1,2})$"),
    # 保留/虚构行政区划代码：99 开头
    "adcode": re.compile(r"^99\d{4}$"),
    # 桩号区间端点：K0+000 ~ K99+999
    "stake": re.compile(r"^K(?:[0-9]|[1-8][0-9]|9[0-9])\+[0-9]{3}$"),
    # 路段名：SYN 前缀
    "segment_name": re.compile(r"^SYN-.+$"),
    # 单位名：明显非实名
    "org_name": re.compile(r"^(?:示例|某某|虚拟|SYN).*$"),
    # 手机号：199 保留号段的虚构段
    "phone": re.compile(r"^1990000\d{4}$"),
    # 报告/委托编号
    "report_no": re.compile(r"^SYN-[A-Z]{2,3}-\d{4}-\d{4}$"),
    # DOI：保留前缀
    "doi": re.compile(r"^10\.9999/.+$"),
}  # type: Dict[str, re.Pattern]

#: kind → 人类可读的白名单说明（拒因要能指出去哪一条登记加形式）
WHITELIST_HINTS = {
    "route_id": "S99 / X990 / Y999 / Z9901 一类的全 9 或 99 开头编号",
    "adcode": "990000 / 9901xx 一类的 99 开头代码",
    "stake": "K0+000～K99+999 区间内的桩号",
    "segment_name": "SYN- 前缀 + 虚构地名",
    "org_name": "示例 / 某某 / 虚拟 / SYN 开头的明显非实名单位",
    "phone": "19900000000～19900009999 保留号段",
    "report_no": "SYN-XX-2026-0001 式编号",
    "doi": "10.9999/ 前缀",
}

#: kind → 是否必填（None 表示允许缺省，缺省不校验）
_OPTIONAL_KINDS = ("phone", "doi", "report_no", "org_name")

# 结论纪律：异常只能报"应核实"，未核对的东西不得写成确定语气
BANNED_ASSERTIONS = ("已确认", "已核实", "最终确定", "必定")
HONEST_SUFFIX = "（应核实）"


def is_synthetic(kind, value):
    # type: (str, Optional[str]) -> bool
    pattern = PATTERNS.get(kind)
    if pattern is None:
        raise PrivacyViolation("未知的标识符类别 %r，先在 data/README.md 登记再来这里加" % kind)
    if value is None:
        return kind in _OPTIONAL_KINDS
    return bool(pattern.match(value))


def assert_synthetic(kind, value):
    # type: (str, Optional[str]) -> str
    """不在白名单内即拒绝；返回原值便于链式使用。"""
    if is_synthetic(kind, value):
        return value  # type: ignore[return-value]
    if value is None:
        raise PrivacyViolation("标识符 %s 必填（类别 %s）" % (kind, WHITELIST_HINTS.get(kind, "")))
    raise PrivacyViolation(
        "合成数据标识符越界：%s=%r 不符合白名单（允许形式：%s）" % (kind, value, WHITELIST_HINTS.get(kind, ""))
    )


def check_row(row, kinds=None):
    # type: (Mapping[str, object], Optional[Iterable[str]]) -> None
    """按字段名后缀推断类别做整行校验（生成器落盘前的闸门）。

    字段名约定：route_id / adcode / segment_name / start_stake / end_stake /
    org_name / phone / report_no / doi。其余字段不校验。
    """
    for name, value in sorted(row.items()):
        kind = _kind_for_field(name)
        if kind is None:
            continue
        if kinds is not None and kind not in kinds:
            continue
        assert_synthetic(kind, None if value is None else str(value))


def _kind_for_field(field_name):
    # type: (str) -> Optional[str]
    if field_name == "route_id":
        return "route_id"
    if field_name == "adcode":
        return "adcode"
    if field_name == "segment_name":
        return "segment_name"
    if field_name in ("start_stake", "end_stake"):
        return "stake"
    if field_name in ("org_name", "detect_org", "client_org"):
        return "org_name"
    if field_name == "phone":
        return "phone"
    if field_name in ("report_no", "commission_no"):
        return "report_no"
    if field_name == "doi":
        return "doi"
    return None


def assert_honest_wording(text):
    # type: (str) -> None
    """未核对项在报告里只能写"应核实/待核对"，出现确定语气词即拒绝导出。"""
    hits = [word for word in BANNED_ASSERTIONS if word in text]
    if hits:
        raise PrivacyViolation(
            "结论文本出现确定语气词 %s —— 本题结论纪律只允许'应核实/待核对'表述未核对项" % "、".join(hits)
        )
