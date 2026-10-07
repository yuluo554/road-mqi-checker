"""系数三态（+ 测试夹具档）与"生效口径"判定。

本题风险集中在每一格数字上：扣分比率、分项权重、分级阈值若凭记忆填写必然错。
所以核对状态不是文档注释，而是进引擎的计算门：

    pending   一无所知（条号与数值都未落实）        → 不可参与计算
    located   条号/表号已按渠道原文逐字定位，数值未取到 → 不可参与计算
    verified  数值已按官方原文核对并登记渠道         → 可参与计算
    fixture   仅允许出现在 tests/fixtures 的夹具值    → 仅测试内可参与计算

两态与三态的区别是要害：located 与 pending 都不放行计算，但它们在核对队列里
信息量完全不同（"知道该翻哪张表" vs "连表号都没有"），所以绝不挤成同一个值。
"""

PENDING = "pending"
LOCATED = "located"
VERIFIED = "verified"
FIXTURE = "fixture"

ALL_STATUSES = (PENDING, LOCATED, VERIFIED, FIXTURE)

# 可信度排序：数值越小越不可信，effective_status 取 min
STATUS_RANK = {PENDING: 0, LOCATED: 1, FIXTURE: 2, VERIFIED: 3}

# 需要挂渠道档（渠道 + 日期 + 可定位载体）才能成立的状态
PROVENANCE_REQUIRED = (LOCATED, VERIFIED)

# 允许驱动数值计算的状态（FIXTURE 另受"只出现在测试通路"约束）
COMPUTABLE = (VERIFIED, FIXTURE)

FIXTURE_CHANNEL_MARK = "tests/fixtures"


def check_status(value):
    # type: (str) -> str
    if value not in ALL_STATUSES:
        from road_mqi_checker.errors import SchemaViolation

        raise SchemaViolation(
            "未知核对状态 %r，合法值只有 %s" % (value, ", ".join(ALL_STATUSES))
        )
    return value


def effective_status(statuses):
    # type: (list) -> str
    """规则自身状态与其全部依据条款状态取最弱一档（min）。

    缺这一条，限值类检查就能在所有依据未核对的情况下自称已核对。
    """
    if not statuses:
        return PENDING
    ranked = sorted(statuses, key=lambda s: STATUS_RANK[check_status(s)])
    return ranked[0]


def is_computable(status):
    # type: (str) -> bool
    return check_status(status) in COMPUTABLE


def provenance_required(status):
    # type: (str) -> bool
    return check_status(status) in PROVENANCE_REQUIRED


def blocked_reason(status, key, missing=None):
    # type: (str, str, str) -> str
    """统一拒算措辞：只说"应核实"，不写"已确认"（结论纪律）。"""
    base = "系数 %s 核对状态为 %s，未进入评定路径" % (key, status)
    if missing:
        base += "（缺 %s）" % missing
    return base + "，应核实原文后再算"
