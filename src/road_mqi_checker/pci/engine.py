"""路面 PCI 评定引擎（模块 2，本题核心，逻辑属 M2）。

规则优先、纯算术、无概率无模型。三个硬约束：
1. 每一格扣分比率/权重都来自规则集并挂条款号，未核对（pending/located）即整段 blocked；
2. 浮点比较一律走固定舍入（ROUND_HALF_UP + 固定小数位），杜绝"同一套数据两次算分不同"；
3. 同一台账 + 同一规则集重跑，结果必须完全一致（零漂移是基准指标之一）。
"""

from decimal import ROUND_HALF_UP, Decimal

from road_mqi_checker.errors import MilestoneNotImplemented

MODULE_KEY = "road_mqi_checker.pci.engine"
MILESTONE = "M2"

#: 得分保留位数（既定口径：改动会让所有基准数字漂移）
PCI_DECIMALS = 1


def quantize(value, decimals=PCI_DECIMALS):
    # type: (float, int) -> float
    """固定舍入规则：十进制半值向上，不用 Python 内置 round 的银行家舍入。

    M0 就实现并锁死，避免 M2 之后再改口径打挂"零漂移"这条指标。
    """
    quant = Decimal(1).scaleb(-decimals)
    return float(Decimal(repr(value)).quantize(quant, rounding=ROUND_HALF_UP))


def compute_segment_pci(conn, segment_id, year, ruleset):
    """返回 PciResult：分项得分、合成得分、等级，以及可展开的扣分贡献清单。

    系数不全时返回 blocked 的 PciResult（数值字段全空 + 拒算原因），不出数。
    """
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="逐路段 PCI 评定")


def surface_table_keys(surface_type):
    # type: (str) -> tuple
    """给定路面类型，返回评定路径必须生效的系数 key 集合（缺任一即 blocked）。"""
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="路面类型→必需系数集合映射")
