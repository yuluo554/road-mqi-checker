"""年度检测数据入库与导入回执（模块 1 的入口，逻辑属 M1）。

回执是硬要求：入库行数 / 拒入行数 / 逐条拒因（文件、行号、字段、拒因代码）。
回执对象不带时间戳（同 ledger.db 的字节一致纪律）。
"""

from road_mqi_checker.errors import MilestoneNotImplemented

MODULE_KEY = "road_mqi_checker.ledger.importer"
MILESTONE = "M1"

#: 回执列名 —— 真值/评测与 GUI 展示都按这套字段（既定口径，改名要同步 plan/03 与测试）
RECEIPT_COLUMNS = (
    "source_file",
    "source_digest",
    "rows_total",
    "rows_accepted",
    "rows_rejected",
    "rejected_row_no",
    "rejected_field",
    "reject_code",
    "reject_detail",
)

#: 拒入原因代码（M1 逐项落地，与 CHECK_KINDS 一一对应或更细）
REJECT_CODES = (
    "R001_UNKNOWN_ROUTE",
    "R002_STAKE_GAP",
    "R003_STAKE_OVERLAP",
    "R004_CLOSURE_EXCEEDED",
    "R005_BAD_DICTIONARY",
    "R006_UNIT_MISMATCH",
    "R007_OUT_OF_RANGE",
    "R008_DUPLICATE",
    "R009_MALFORMED_ROW",
    "R010_PRIVACY_WHITELIST",
)


def import_csv(conn, path, year, ruleset, dry_run=False):
    """把一份年度检测表导入台账并返回回执。"""
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="CSV 年度检测表入库与回执")


def plan_import(conn, path):
    """只读预检：返回将要入库/拒入的行数，不落库（GUI 导入向导先跑这一步）。"""
    raise MilestoneNotImplemented(MODULE_KEY, MILESTONE, what="导入预检")
