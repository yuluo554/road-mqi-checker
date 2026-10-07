"""SQLite 台账：建表、元信息、连接。

结构层属 M0（现在就建得起来），入库与校验逻辑在 M1 落地（`ledger.importer` / `ledger.checks`）。

两点刻意的设计：
1. 表里不加 CHECK(quantity >= 0) 之类的约束 —— 负值/超范围/单位错是**要入库并被检出**
   的对象，被数据库拒掉就丢掉了"导入回执 + 异常识别召回"这条主证据链；
2. 表不带 created_at/updated_at 默认时间戳 —— 基准产物要求两次运行逐字节一致，
   时钟进表就会永远对不齐（回执里记录的是"来源文件 + 行号"，不是时间）。

schema v2（M1）：`segment` 增加 lane_count / segment_width_m / panel_count 三个可空列。
理由是"破损数量的几何上界"（超范围检出的判据）与水泥路面按板数扣分都必须能从台账本身复算，
不能只活在 CSV 里；三列可空，缺就判"未判定"而不是判合格。
"""

import sqlite3
from typing import List, Tuple

SCHEMA_VERSION = "2"
META_SCHEMA_KEY = "schema_version"

#: 建表顺序固定（决定 sqlite_master 里的顺序，位级复现的前提之一）
DDL = (
    (
        "meta",
        """
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
    ),
    (
        "route",
        """
        CREATE TABLE IF NOT EXISTS route (
            route_id       TEXT NOT NULL,
            year           INTEGER NOT NULL,
            route_name     TEXT NOT NULL,
            admin_grade    TEXT NOT NULL,
            tech_grade     TEXT NOT NULL,
            start_stake_m  INTEGER NOT NULL,
            end_stake_m    INTEGER NOT NULL,
            adcode         TEXT,
            note           TEXT,
            PRIMARY KEY (route_id, year)
        )
        """,
    ),
    (
        "segment",
        """
        CREATE TABLE IF NOT EXISTS segment (
            segment_id     TEXT NOT NULL,
            route_id       TEXT NOT NULL,
            year           INTEGER NOT NULL,
            segment_name   TEXT NOT NULL,
            start_stake_m  INTEGER NOT NULL,
            end_stake_m    INTEGER NOT NULL,
            surface_type   TEXT NOT NULL,
            note           TEXT,
            lane_count     INTEGER,
            segment_width_m REAL,
            panel_count    INTEGER,
            PRIMARY KEY (segment_id, year)
        )
        """,
    ),
    (
        "survey",
        """
        CREATE TABLE IF NOT EXISTS survey (
            segment_id          TEXT NOT NULL,
            route_id            TEXT NOT NULL,
            year                INTEGER NOT NULL,
            surface_type        TEXT NOT NULL,
            rqi                 REAL,
            rut_depth_mm        REAL,
            skid_indicator      REAL,
            skid_indicator_kind TEXT,
            report_no           TEXT,
            detect_org          TEXT,
            note                TEXT,
            PRIMARY KEY (segment_id, year)
        )
        """,
    ),
    (
        "distress",
        """
        CREATE TABLE IF NOT EXISTS distress (
            row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            segment_id    TEXT NOT NULL,
            year          INTEGER NOT NULL,
            distress_type TEXT NOT NULL,
            severity      TEXT NOT NULL,
            quantity      REAL NOT NULL,
            quantity_unit TEXT NOT NULL,
            area_m2       REAL,
            lane_no       INTEGER,
            source_row_no INTEGER NOT NULL,
            note          TEXT
        )
        """,
    ),
    (
        "import_receipt",
        """
        CREATE TABLE IF NOT EXISTS import_receipt (
            receipt_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file    TEXT NOT NULL,
            source_digest  TEXT NOT NULL,
            rows_total     INTEGER NOT NULL,
            rows_accepted  INTEGER NOT NULL,
            rows_rejected  INTEGER NOT NULL,
            reject_summary TEXT
        )
        """,
    ),
    (
        "partition_change",
        """
        CREATE TABLE IF NOT EXISTS partition_change (
            route_id     TEXT NOT NULL,
            year_from    INTEGER NOT NULL,
            year_to      INTEGER NOT NULL,
            change_kind  TEXT NOT NULL,
            segment_id   TEXT NOT NULL,
            detail       TEXT,
            PRIMARY KEY (route_id, year_from, year_to, change_kind, segment_id)
        )
        """,
    ),
)  # type: Tuple[Tuple[str, str], ...]

INDEX_DDL = (
    ("idx_segment_route_year", "CREATE INDEX IF NOT EXISTS idx_segment_route_year ON segment (route_id, year)"),
    ("idx_distress_segment_year", "CREATE INDEX IF NOT EXISTS idx_distress_segment_year ON distress (segment_id, year)"),
    ("idx_survey_route_year", "CREATE INDEX IF NOT EXISTS idx_survey_route_year ON survey (route_id, year)"),
)

#: 跨年度划分变更类别：显式标记不可比，不做静默摊分
CHANGE_KINDS = ("new", "disappeared", "merged", "split", "shifted", "unchanged")


def connect(path=":memory:"):
    # type: (str) -> sqlite3.Connection
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(conn):
    # type: (sqlite3.Connection) -> None
    """建表并写入 schema 版本；幂等（IF NOT EXISTS）。"""
    for _name, statement in DDL:
        conn.execute(statement)
    for _name, statement in INDEX_DDL:
        conn.execute(statement)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (META_SCHEMA_KEY, SCHEMA_VERSION)
    )
    conn.commit()


def table_names(conn):
    # type: (sqlite3.Connection) -> List[str]
    """本工具建的用户表（sqlite_sequence 这类引擎内部表不算）。"""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row["name"] for row in rows]


def expected_tables():
    # type: () -> List[str]
    return sorted([name for name, _ddl in DDL])


def read_meta(conn, key):
    # type: (sqlite3.Connection, str) -> str
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""
