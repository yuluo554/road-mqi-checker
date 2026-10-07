"""结果对象与拒算契约。

评定的每个输出对象自带状态；blocked/uncomparable 状态下数值字段必须全空 ——
不是 0、不是 NaN、不是"仅供参考"。契约由 check_contract() 强制，守门测试逐类对账，
所以"未核对系数不生效"是代码事实，不是文档承诺。
"""

from typing import Dict, List, Optional

from road_mqi_checker.errors import ContractViolation

STATUS_OK = "ok"
STATUS_BLOCKED = "blocked"
STATUS_PARTIAL = "partial"
STATUS_UNCOMPARABLE = "uncomparable"

ALL_RESULT_STATUSES = (STATUS_OK, STATUS_BLOCKED, STATUS_PARTIAL, STATUS_UNCOMPARABLE)

# 允许携带数值的状态：ok 全量；partial 只允许"已注明口径"的部分值
NUMERIC_ALLOWED_STATUSES = (STATUS_OK, STATUS_PARTIAL)


class _BaseResult(object):
    """结果对象基类：NUMERIC_FIELDS 声明哪些字段是数值，拒算时必须为空。"""

    NUMERIC_FIELDS = ()  # type: tuple
    LABEL_FIELDS = ()  # type: tuple

    def _numeric_values(self):
        out = []
        for name in self.NUMERIC_FIELDS:
            value = getattr(self, name)
            if isinstance(value, dict):
                out.extend(list(value.values()))
            else:
                out.append(value)
        return out

    def check_contract(self):
        # type: () -> None
        if self.status not in ALL_RESULT_STATUSES:
            raise ContractViolation("%s 的 status=%r 非法" % (self.__class__.__name__, self.status))
        if self.status in (STATUS_BLOCKED, STATUS_UNCOMPARABLE):
            leaked = [v for v in self._numeric_values() if v is not None]
            if leaked:
                raise ContractViolation(
                    "%s 处于 %s 却携带数值 %r —— 未核对不出数、不可比不出变化率"
                    % (self.__class__.__name__, self.status, leaked)
                )
            if not self.blocked_reason:
                raise ContractViolation(
                    "%s 处于 %s 但没有拒算/不可比原因" % (self.__class__.__name__, self.status)
                )
        if self.status == STATUS_BLOCKED:
            for name in self.LABEL_FIELDS:
                if getattr(self, name) not in (None, "", [], {}):
                    raise ContractViolation(
                        "%s blocked 却给出了等级/类别结论字段 %s" % (self.__class__.__name__, name)
                    )
        if self.status == STATUS_PARTIAL and not self.scope_note:
            raise ContractViolation("%s 部分口径结果必须声明口径（scope_note）" % self.__class__.__name__)
        for value in self._numeric_values():
            if isinstance(value, float) and value != value:
                raise ContractViolation("%s 出现 NaN —— 缺值必须是 None" % self.__class__.__name__)


class DeductContribution(object):
    """一条破损/一个实测指标对得分的贡献（模块 2 的"可追溯"就落在这个对象上）。"""

    __slots__ = (
        "source_kind",
        "distress_type",
        "severity",
        "quantity",
        "quantity_unit",
        "coefficient_key",
        "clause",
        "deducted_points",
        "share",
        "source_row_no",
    )

    def __init__(
        self,
        source_kind,          # "distress" | "measured_indicator"
        distress_type="",     # type: str
        severity="",          # type: str
        quantity=None,        # type: Optional[float]
        quantity_unit="",     # type: str
        coefficient_key="",   # type: str
        clause="",            # type: str
        deducted_points=None, # type: Optional[float]
        share=None,           # type: Optional[float]
        source_row_no=None,   # type: Optional[int]
    ):
        self.source_kind = source_kind
        self.distress_type = distress_type
        self.severity = severity
        self.quantity = quantity
        self.quantity_unit = quantity_unit
        self.coefficient_key = coefficient_key
        self.clause = clause
        self.deducted_points = deducted_points
        self.share = share
        # 台账行号即原始检测表的数据行序（ledger.importer.read_table 的编号语义），
        # 展开视图靠它回指到用户手里的那份文件
        self.source_row_no = source_row_no

    def check_contract(self):
        # type: () -> None
        if not self.coefficient_key:
            raise ContractViolation("扣分贡献项必须挂规则集系数 key（可追溯到某一格系数）")
        if not self.clause:
            raise ContractViolation("扣分贡献项必须挂条款号/表号")
        if self.source_kind == "distress" and self.source_row_no is None:
            raise ContractViolation("破损贡献项必须回指台账行号，否则无法核到原始检测表的哪一行")


class PciResult(_BaseResult):
    NUMERIC_FIELDS = ("pci", "component_scores", "deducted_total")
    LABEL_FIELDS = ("grade",)

    def __init__(
        self,
        segment_id,
        route_id,
        year,
        surface_type,
        status=STATUS_BLOCKED,
        blocked_reason="",
        scope_note="",
        component_scores=None,
        deducted_total=None,
        pci=None,
        grade=None,
        contributions=None,
        ruleset_id="",
        ruleset_version="",
    ):
        self.segment_id = segment_id
        self.route_id = route_id
        self.year = year
        self.surface_type = surface_type
        self.status = status
        self.blocked_reason = blocked_reason
        self.scope_note = scope_note
        self.component_scores = component_scores if component_scores is not None else {}
        self.deducted_total = deducted_total
        self.pci = pci
        self.grade = grade
        self.contributions = contributions if contributions is not None else []  # type: List[DeductContribution]
        self.ruleset_id = ruleset_id
        self.ruleset_version = ruleset_version

    def check_contract(self):
        # type: () -> None
        super(PciResult, self).check_contract()
        for item in self.contributions:
            item.check_contract()


class MqiResult(_BaseResult):
    NUMERIC_FIELDS = ("mqi", "weighted_length_m", "component_scores")
    LABEL_FIELDS = ("grade",)

    def __init__(
        self,
        level,                # "segment" | "route" | "network"
        object_id,
        year,
        status=STATUS_BLOCKED,
        blocked_reason="",
        scope_note="",
        mqi=None,
        grade=None,
        component_scores=None,
        included_components=None,
        excluded_components=None,
        weighted_length_m=None,
        ruleset_id="",
        ruleset_version="",
    ):
        self.level = level
        self.object_id = object_id
        self.year = year
        self.status = status
        self.blocked_reason = blocked_reason
        self.scope_note = scope_note
        self.mqi = mqi
        self.grade = grade
        self.component_scores = component_scores if component_scores is not None else {}  # type: Dict[str, float]
        self.included_components = included_components if included_components is not None else []
        self.excluded_components = excluded_components if excluded_components is not None else []
        self.weighted_length_m = weighted_length_m
        self.ruleset_id = ruleset_id
        self.ruleset_version = ruleset_version


class CompareResult(_BaseResult):
    """年对比：跨年划分不可比时只能出 uncomparable，禁止按比例摊分后给变化率。"""

    NUMERIC_FIELDS = ("delta", "deterioration_rate_per_year", "length_overlap_m")
    LABEL_FIELDS = ("grade_from", "grade_to")

    def __init__(
        self,
        segment_id,
        route_id,
        year_from,
        year_to,
        status=STATUS_UNCOMPARABLE,
        blocked_reason="",
        scope_note="",
        delta=None,
        deterioration_rate_per_year=None,
        length_overlap_m=None,
        grade_from=None,
        grade_to=None,
        top_contributors=None,
        comparability_reason="",
    ):
        self.segment_id = segment_id
        self.route_id = route_id
        self.year_from = year_from
        self.year_to = year_to
        self.status = status
        self.blocked_reason = blocked_reason
        self.scope_note = scope_note
        self.delta = delta
        self.deterioration_rate_per_year = deterioration_rate_per_year
        self.length_overlap_m = length_overlap_m
        self.grade_from = grade_from
        self.grade_to = grade_to
        self.top_contributors = top_contributors if top_contributors is not None else []  # type: List[DeductContribution]
        #: 不可比因素代码（取值见 `strategy.compare.UNCOMPARABLE_REASONS`，与 COMPARE_COLUMNS 同列）
        self.comparability_reason = comparability_reason

    def check_contract(self):
        # type: () -> None
        super(CompareResult, self).check_contract()
        if self.status == STATUS_UNCOMPARABLE and not self.comparability_reason:
            raise ContractViolation("uncomparable 必须给出不可比因素代码，否则清单里无法归类")
        if self.status == STATUS_OK and not self.top_contributors:
            raise ContractViolation("对比结论必须能回答由哪个指标的哪次变化触发（top_contributors 为空）")


class ActionSuggestion(_BaseResult):
    NUMERIC_FIELDS = ("scale_band_value",)
    LABEL_FIELDS = ("action_class",)

    #: 从评定/汇总结果**复制**过来的上下文（是事实转述，不是本对象的新结论，
    #: 因此不进 NUMERIC_FIELDS：对策 blocked 时 PCI 仍是一个已核对口径下的事实数字）
    CONTEXT_FIELDS = ("pci", "mqi_partial", "start_stake_m")

    def __init__(
        self,
        segment_id,
        route_id,
        year,
        status=STATUS_BLOCKED,
        blocked_reason="",
        scope_note="",
        rule_id="",
        clause="",
        condition_text="",
        action_class=None,
        scale_band=None,
        scale_band_value=None,
        triggered_by=None,
        rank_key="",
        pci=None,
        mqi_partial=None,
        start_stake_m=None,
    ):
        self.segment_id = segment_id
        self.route_id = route_id
        self.year = year
        self.status = status
        self.blocked_reason = blocked_reason
        self.scope_note = scope_note
        self.rule_id = rule_id
        self.clause = clause
        self.condition_text = condition_text
        self.action_class = action_class
        self.scale_band = scale_band
        self.scale_band_value = scale_band_value
        self.triggered_by = triggered_by
        self.rank_key = rank_key
        self.pci = pci
        self.mqi_partial = mqi_partial
        self.start_stake_m = start_stake_m

    def check_contract(self):
        # type: () -> None
        super(ActionSuggestion, self).check_contract()
        if self.status in NUMERIC_ALLOWED_STATUSES:
            if not self.rule_id or not self.clause:
                raise ContractViolation("对策建议必须挂规则 id 与条款号（无出处的结论不得确定表述）")
            if not self.triggered_by:
                raise ContractViolation("对策建议必须写明由哪个指标的哪一次变化触发")
