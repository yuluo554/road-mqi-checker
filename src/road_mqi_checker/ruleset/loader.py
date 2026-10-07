"""versioned 扣分规则集：结构、校验与选取。

一个规则集包（ruleset）= 一组带条款依据的系数 + 适用口径（省份/年度/路面类型）。
首期内置一个基础包（JTG 5210-2018 口径），全部系数 status=pending、values=null，
用来验证"无生效系数时结构仍然跑得通、并且坚决不出数"。
"""

import json
import os
from typing import Dict, List, Optional

from road_mqi_checker.errors import InputUnavailable, SchemaViolation
from road_mqi_checker.ruleset import status as st

SCHEMA_VERSION = 1

# 系数用途三分类：扣分比率、分项权重、分级阈值 —— 题目纪律要求逐格登记来源
KINDS = ("deduct_ratio", "component_weight", "grade_threshold", "action_rule")

#: 内置规则集目录在包根（road_mqi_checker/rulesets），不是本子包目录 —— 冻结打包时按包根收
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BUILTIN_DIR = os.path.join(_PACKAGE_ROOT, "rulesets")
_USER_DIR_ENV = "RMQC_RULESET_DIR"


class Basis(object):
    """一条系数的依据登记：标准号 + 条款/表号 + 查证渠道 + 该条款自身的核对状态。

    条款状态单独记：构造式条款可能已核对而限值条款未核对，系数的生效档位要取
    两者最弱一档（见 Coefficient.effective_status 的反向索引）。
    """

    __slots__ = ("standard_id", "clause", "channel", "verified_at", "locator", "note", "status")

    def __init__(self, standard_id, clause, channel, verified_at, locator, note="", status=st.PENDING):
        self.standard_id = standard_id
        self.clause = clause
        self.channel = channel
        self.verified_at = verified_at
        self.locator = locator
        self.note = note
        self.status = st.check_status(status)

    @classmethod
    def from_dict(cls, payload):
        if not isinstance(payload, dict):
            raise SchemaViolation("basis 必须是对象，实际 %r" % type(payload).__name__)
        status = payload.get("status")
        if status is None:
            status = st.PENDING
        return cls(
            standard_id=_require_str(payload, "standard_id", "basis"),
            clause=_optional_str(payload, "clause"),
            channel=_optional_str(payload, "channel"),
            verified_at=_optional_str(payload, "verified_at"),
            locator=_optional_str(payload, "locator"),
            note=_optional_str(payload, "note"),
            status=status,
        )

    def to_dict(self):
        return {
            "standard_id": self.standard_id,
            "clause": self.clause,
            "channel": self.channel,
            "verified_at": self.verified_at,
            "locator": self.locator,
            "note": self.note,
            "status": self.status,
        }


class Coefficient(object):
    """一格可数字化系数（带状态、依据、以及仅在已核对时才允许存在的数值）。"""

    __slots__ = (
        "key",
        "kind",
        "surface_type",
        "status",
        "values",
        "unit",
        "basis",
        "register_ref",
        "note",
    )

    def __init__(
        self,
        key,          # type: str
        kind,         # type: str
        surface_type, # type: Optional[str]
        status,       # type: str
        values,       # type: Optional[Dict[str, object]]
        unit,         # type: Optional[str]
        basis,        # type: List[Basis]
        register_ref, # type: Optional[str]
        note,         # type: str
    ):
        self.key = key
        self.kind = kind
        self.surface_type = surface_type
        self.status = status
        self.values = values
        self.unit = unit
        self.basis = basis
        self.register_ref = register_ref
        self.note = note

    # ---- 校验：违反即拒绝整包加载，不做"降级忽略" ----

    def validate(self, allow_fixture=False):
        # type: (bool) -> None
        st.check_status(self.status)
        if self.kind not in KINDS:
            raise SchemaViolation("系数 %s 的 kind=%r 非法，合法值 %s" % (self.key, self.kind, ", ".join(KINDS)))
        if not self.basis:
            raise SchemaViolation("系数 %s 没有任何依据登记（basis 为空）" % self.key)
        for basis in self.basis:
            if not basis.standard_id:
                raise SchemaViolation("系数 %s 的某条 basis 缺 standard_id" % self.key)
        if st.provenance_required(self.status):
            for basis in self.basis:
                missing = [
                    name
                    for name, value in (
                        ("clause", basis.clause),
                        ("channel", basis.channel),
                        ("verified_at", basis.verified_at),
                        ("locator", basis.locator),
                    )
                    if not value
                ]
                if missing:
                    raise SchemaViolation(
                        "系数 %s 自称 %s，但依据缺 %s —— 未核对不得以确定语气落库"
                        % (self.key, self.status, "/".join(missing))
                    )
        if self.status == st.FIXTURE and not allow_fixture:
            raise SchemaViolation(
                "系数 %s 使用夹具档（fixture），只允许在 tests/fixtures 通路上加载" % self.key
            )
        if self.status in (st.PENDING, st.LOCATED) and self.values not in (None, {}, []):
            raise SchemaViolation(
                "系数 %s 状态为 %s 却带数值 —— 未核对的阈值一律写 null" % (self.key, self.status)
            )
        if self.status in (st.VERIFIED, st.FIXTURE) and self.values in (None, {}, []):
            raise SchemaViolation(
                "系数 %s 自称 %s 但 values 为空" % (self.key, self.status)
            )

    @property
    def effective_status(self):
        # type: () -> str
        """本系数可参与计算的真实档位 = min(自身状态, 各依据条款状态)。"""
        return st.effective_status([self.status] + [b.status for b in self.basis])

    @property
    def computable(self):
        # type: () -> bool
        return st.is_computable(self.effective_status)

    def block_reason(self):
        # type: () -> str
        return st.blocked_reason(self.effective_status, self.key)

    @classmethod
    def from_dict(cls, payload, allow_fixture=False):
        if not isinstance(payload, dict):
            raise SchemaViolation("系数条目必须是对象，实际 %r" % type(payload).__name__)
        key = _require_str(payload, "key", "coefficient")
        kind = _require_str(payload, "kind", "coefficient " + key)
        status = _require_str(payload, "status", "coefficient " + key)
        basis_raw = payload.get("basis")
        if not isinstance(basis_raw, list):
            raise SchemaViolation("系数 %s 的 basis 必须是数组" % key)
        coef = cls(
            key=key,
            kind=kind,
            surface_type=_optional_str(payload, "surface_type"),
            status=status,
            values=payload.get("values"),
            unit=_optional_str(payload, "unit"),
            basis=[Basis.from_dict(b) for b in basis_raw],
            register_ref=_optional_str(payload, "register_ref"),
            note=_optional_str(payload, "note"),
        )
        coef.validate(allow_fixture=allow_fixture)
        return coef


class RuleSet(object):
    """一个 versioned 规则集包。"""

    __slots__ = ("ruleset_id", "version", "title", "applies_to", "coefficients", "notes", "source_path")

    def __init__(self, ruleset_id, version, title, applies_to, coefficients, notes, source_path):
        self.ruleset_id = ruleset_id
        self.version = version
        self.title = title
        self.applies_to = applies_to
        self.coefficients = coefficients
        self.notes = notes
        self.source_path = source_path

    @classmethod
    def from_dict(cls, payload, source_path=None, allow_fixture=False):
        if not isinstance(payload, dict):
            raise SchemaViolation("规则集文件必须是 JSON 对象")
        schema_version = payload.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise SchemaViolation(
                "规则集 schema_version=%r 与本内核支持的 %r 不符" % (schema_version, SCHEMA_VERSION)
            )
        applies_to = payload.get("applies_to")
        if not isinstance(applies_to, dict):
            raise SchemaViolation("规则集缺 applies_to 对象（province/year 选取依赖它）")
        coef_raw = payload.get("coefficients")
        if not isinstance(coef_raw, list) or not coef_raw:
            raise SchemaViolation("规则集 coefficients 必须是非空数组（哪怕全为 pending）")
        coefficients = [Coefficient.from_dict(c, allow_fixture=allow_fixture) for c in coef_raw]
        seen = set()
        for coef in coefficients:
            if coef.key in seen:
                raise SchemaViolation("规则集内系数 key 重复：%s" % coef.key)
            seen.add(coef.key)
        return cls(
            ruleset_id=_require_str(payload, "ruleset_id", "ruleset"),
            version=_require_str(payload, "version", "ruleset"),
            title=_optional_str(payload, "title"),
            applies_to={
                "province": _optional_str(applies_to, "province") or "*",
                "year": _optional_str(applies_to, "year") or "*",
                "surface_type": _optional_str(applies_to, "surface_type") or "*",
            },
            coefficients=coefficients,
            notes=_optional_str(payload, "notes"),
            source_path=source_path,
        )

    def find(self, key):
        # type: (str) -> Optional[Coefficient]
        for coef in self.coefficients:
            if coef.key == key:
                return coef
        return None

    def computable_coefficients(self):
        # type: () -> List[Coefficient]
        return [c for c in self.coefficients if c.computable]

    def blocked_coefficients(self):
        # type: () -> List[Coefficient]
        return [c for c in self.coefficients if not c.computable]

    def summary(self):
        # type: () -> Dict[str, object]
        counts = {}  # type: Dict[str, int]
        for coef in self.coefficients:
            counts[coef.effective_status] = counts.get(coef.effective_status, 0) + 1
        return {
            "ruleset_id": self.ruleset_id,
            "version": self.version,
            "applies_to": self.applies_to,
            "total_coefficients": len(self.coefficients),
            "by_status": counts,
            "computable": len(self.computable_coefficients()),
            "blocked": len(self.blocked_coefficients()),
            "source_path": self.source_path,
        }


# ---- 加载与选取 ----


def ruleset_search_dirs():
    # type: () -> List[str]
    """内置包目录 + 用户目录（环境变量指定，用于地方细则/用户自定规则）。"""
    dirs = [_BUILTIN_DIR]
    user_dir = os.environ.get(_USER_DIR_ENV)
    if user_dir:
        dirs.append(user_dir)
    return dirs


def list_ruleset_files():
    # type: () -> List[str]
    found = []  # type: List[str]
    for directory in ruleset_search_dirs():
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if name.endswith(".json"):
                found.append(os.path.join(directory, name))
    return found


def load_file(path, allow_fixture=False):
    # type: (str, bool) -> RuleSet
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except ValueError as exc:
        raise SchemaViolation("规则集 %s 不是合法 JSON：%s" % (path, exc))
    return RuleSet.from_dict(payload, source_path=path, allow_fixture=allow_fixture)


def select_ruleset(province=None, year=None, surface_type=None, allow_fixture=False):
    # type: (Optional[str], Optional[str], Optional[str], bool) -> RuleSet
    """按省份/年度/路面类型选最具体的规则集包；口径优先级见 plan/02 §4。

    匹配规则：通配 * 视为最低优先级，显式匹配数多者胜；同分时按 ruleset_id 字典序，
    保证"选取过程本身也是确定的"（不允许依赖 os.listdir 顺序）。
    """
    candidates = []
    for path in list_ruleset_files():
        ruleset = load_file(path, allow_fixture=allow_fixture)
        score = _match_score(ruleset.applies_to, province, year, surface_type)
        if score is None:
            continue
        candidates.append((score, ruleset.ruleset_id + "|" + ruleset.version, ruleset))
    if not candidates:
        raise InputUnavailable(
            "没有可用规则集包覆盖该口径（province=%s year=%s surface=%s）"
            % (province, year, surface_type)
        )
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def _match_score(applies, province, year, surface_type):
    # type: (Dict[str, str], Optional[str], Optional[str], Optional[str]) -> Optional[int]
    score = 0
    for field, requested in (("province", province), ("year", year), ("surface_type", surface_type)):
        declared = applies.get(field, "*")
        if requested in (None, "", declared):
            if declared != "*":
                score += 1
            continue
        if declared == "*":
            continue
        return None
    return score


def _require_str(payload, name, where):
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise SchemaViolation("%s 缺必填字段 %s" % (where, name))
    return value


def _optional_str(payload, name):
    value = payload.get(name)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SchemaViolation("字段 %s 必须是字符串，实际 %r" % (name, type(value).__name__))
    return value
