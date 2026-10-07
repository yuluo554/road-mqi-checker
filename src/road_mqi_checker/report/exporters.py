"""报告导出（模块 4 的可交付物 + 全模块汇总报告，M6 转真）。

导出层三条结构约束：
1. 只能通过 report.disclaimer.compose_document 拼文档 —— 免责声明必在末尾；
2. 产物不带时间戳与绝对路径、不带本机用户名（字节一致 + 脱敏双重需要）；
3. blocked/uncomparable 项必须原样出现在导出表里，不得为"报表好看"而过滤。

字段口径：本模块**不自建取数通路**，输入一律是各引擎 `result_payload()` 已经给出的
结构（`pci.engine` / `mqi.engine` / `strategy.rules` / `strategy.compare`），
导出层只做"选列 + 排版 + 纪律闸门"。
"""

import csv
import io
import os
import re
from zipfile import ZipInfo, ZipFile

from road_mqi_checker.errors import InputUnavailable, PrivacyViolation
from road_mqi_checker.privacy import assert_honest_wording
from road_mqi_checker.report import disclaimer

MODULE_KEY = "road_mqi_checker.report.exporters"
MILESTONE = "M6"

FORMATS = ("csv", "md", "docx")

#: 优先序清单的导出列（题目材料 3/4：可导出的建议计划表）
PLAN_COLUMNS = (
    "rank",
    "route_id",
    "segment_id",
    "year",
    "pci",
    "mqi_partial",
    "grade",
    "delta",
    "deterioration_rate_per_year",
    "action_class",
    "scale_band",
    "rule_id",
    "clause",
    "triggered_by",
    "status",
    "blocked_reason",
)

#: PCI 评定表列（字段全部来自 `pci.engine.result_payload`）
PCI_COLUMNS = (
    "segment_id",
    "route_id",
    "year",
    "surface_type",
    "status",
    "pci",
    "grade",
    "deducted_total",
    "scope_note",
    "blocked_reason",
    "ruleset_id",
    "ruleset_version",
)

#: MQI 汇总表列（字段全部来自 `mqi.engine.result_payload`）
MQI_COLUMNS = (
    "level",
    "object_id",
    "year",
    "status",
    "mqi",
    "grade",
    "weighted_length_m",
    "included_components",
    "excluded_components",
    "scope_note",
    "blocked_reason",
    "ruleset_id",
    "ruleset_version",
)

#: 台账概况表的列（值全部来自 `build_ledger_snapshot`）
SNAPSHOT_COLUMNS = ("item", "value")

#: 概况计数要查的表与年度列名（`partition_change` 按"起始年度"归属，与 `strategy.compare` 同口径）
_SNAPSHOT_YEAR_COLUMNS = (
    ("route", "year"),
    ("segment", "year"),
    ("survey", "year"),
    ("distress", "year"),
    ("partition_change", "year_from"),
)

#: 空值在导出里的形态：空串（不是 0、不是 NaN、不是 "None"）
EMPTY = ""

_ABS_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|(^|[\s,\"'：（])/(?:home|Users|mnt|var|usr|tmp)/)")
_TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\b")

#: docx 包内的固定时间戳（1980-01-01 00:00:00，zip 的最小可表达值）—— 保证两次导出逐字节一致
_DOCX_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_DOCX_ORDER = ("[Content_Types].xml", "_rels/.rels", "word/document.xml")

CONTENT_TYPES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)

RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    "</Relationships>"
)


def _scalar(value):
    # type: (object) -> str
    """把 payload 里的标量转成导出文本：None→空串，容器→`/` 连接，其余→原样 str。

    引擎已经按 `PCI_DECIMALS` / `SHARE_DECIMALS` 舍入过，导出层不再二次舍入 ——
    否则同一个数字在 CLI 与报告里会出现两种写法（口径漂移）。
    """
    if value is None:
        return EMPTY
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (list, tuple)):
        return "/".join(_scalar(item) for item in value)
    if isinstance(value, dict):
        return "/".join("%s=%s" % (key, _scalar(value[key])) for key in sorted(value))
    return str(value)


def _clean_cell(text):
    # type: (str) -> str
    """表格单元格内的换行会打挂 csv/md 两种行式渲染，统一折成空格。"""
    return _scalar(text).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _md_escape(text):
    # type: (str) -> str
    return _clean_cell(text).replace("|", "\\|")


def assert_export_safe(text):
    # type: (str) -> None
    """导出内容的三条硬闸门：措辞纪律、夹具污染、本机痕迹（绝对路径 / 用户名 / 时间戳）。

    上游命令面的文案不该被假定为干净 —— 导出层是交付面，必须在自己的通路上再查一遍。
    """
    assert_honest_wording(text)
    if "fixture" in text.lower():
        raise PrivacyViolation("导出内容出现夹具（fixture）字样 —— 夹具值不进交付面")
    hit = _ABS_PATH_RE.search(text)
    if hit:
        raise PrivacyViolation("导出内容出现绝对路径：%s" % hit.group(0).strip()[:60])
    username = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if username and username not in ("root", "admin") and username in text:
        raise PrivacyViolation("导出内容出现本机用户名：%s" % username)
    stamp = _TIMESTAMP_RE.search(text)
    if stamp:
        raise PrivacyViolation("导出内容出现时间戳：%s —— 落盘产物必须无时间戳" % stamp.group(0))


def _base_name(path):
    # type: (object) -> str
    """台账/来源文件只保留文件名，绝对路径不进交付面。"""
    if not path:
        return EMPTY
    return os.path.basename(str(path).replace("\\", "/"))


def build_ledger_snapshot(conn, year, ruleset, db=None, receipts=None, checks_summary=None):
    # type: (object, int, object, object, object, object) -> dict
    """台账概况（评定报告的"数据从哪来"一节），只出计数与文件名，不出绝对路径。"""
    counts = {}
    for table, column in _SNAPSHOT_YEAR_COLUMNS:
        row = conn.execute("SELECT COUNT(1) FROM %s WHERE %s = ?" % (table, column), (year,)).fetchone()
        counts[table] = int(row[0])
    snapshot = {
        "year": year,
        "db_name": _base_name(db) if db else ":memory:",
        "ruleset_id": ruleset.ruleset_id,
        "ruleset_version": ruleset.version,
        "route_rows": counts["route"],
        "segment_rows": counts["segment"],
        "survey_rows": counts["survey"],
        "distress_rows": counts["distress"],
        "partition_change_rows": counts["partition_change"],
        "receipts": [
            {
                "source_file": _base_name(item.get("source_file")),
                "data_class": item.get("data_class"),
                "rows_accepted": item.get("rows_accepted"),
                "rows_rejected": item.get("rows_rejected"),
            }
            for item in (receipts or [])
        ],
        "checks_summary": dict(checks_summary or {}),
    }
    return snapshot


def plan_rows(suggestions, pci_results=None, compare_results=None, from_year=None):
    # type: (object, object, object, object) -> list
    """把对策/评定/对比三份 payload 合成优先序清单行（列 = `PLAN_COLUMNS`）。

    `grade` 取自 PCI payload、`delta` 与 `deterioration_rate_per_year` 取自对比 payload ——
    导出层不重算任何数字，只做同 (segment_id, year) 的字段转述。
    """
    pci_index = {}
    for item in pci_results or []:
        pci_index[(item.get("segment_id"), item.get("year"))] = item
    cmp_index = {}
    for item in compare_results or []:
        cmp_index[(item.get("segment_id"), item.get("year_to"), item.get("year_from"))] = item

    rows = []
    for rank, suggestion in enumerate(suggestions or [], 1):
        segment_id = suggestion.get("segment_id")
        year = suggestion.get("year")
        pci = pci_index.get((segment_id, year), {})
        compare = cmp_index.get((segment_id, year, from_year), {}) if from_year is not None else {}
        row = {"rank": rank}
        for column in PLAN_COLUMNS:
            if column == "rank":
                continue
            if column == "grade":
                row[column] = pci.get("grade")
            elif column in ("delta", "deterioration_rate_per_year"):
                row[column] = compare.get(column)
            else:
                row[column] = suggestion.get(column)
        row = {column: row.get(column) for column in PLAN_COLUMNS}
        assert_honest_wording(
            " ".join(_clean_cell(row[column]) for column in ("status", "blocked_reason", "triggered_by", "clause"))
        )
        rows.append(row)
    return rows


def _table(heading, columns, records):
    # type: (str, tuple, list) -> tuple
    headers = list(columns)
    body = []
    for record in records:
        body.append([_clean_cell(record.get(name)) for name in headers])
    return (heading, headers, body)


def _md_table_lines(block):
    # type: (tuple) -> list
    _heading, headers, body = block
    lines = ["| " + " | ".join(_md_escape(name) for name in headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for record in body:
        lines.append("| " + " | ".join(_md_escape(cell) for cell in record) + " |")
    return lines


def _csv_row(writer, values):
    writer.writerow(list(values))


def _render_csv(flat, title):
    # type: (list, str) -> str
    """csv 用真正的 CSV 写入器；小节标题与说明行以 `#` 前缀（表体本身保持严格 CSV）。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for kind, payload in flat:
        if kind == "comment":
            for line in payload:
                writer.writerow(["# " + line])
        elif kind == "table":
            _heading, headers, body = payload
            writer.writerow(headers)
            for record in body:
                writer.writerow(record)
        elif kind == "para":
            if not payload:  # 排版空行不进 CSV，避免解析出无意义的空记录
                continue
            writer.writerow([payload])
    return buffer.getvalue()


def _xml_text(value):
    # type: (str) -> str
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _docx_paragraph(text, bold=False, size=None):
    # type: (str, bool, object) -> str
    props = []
    if bold:
        props.append("<w:b/>")
    if size:
        props.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size, size))
    run_props = "<w:rPr>%s</w:rPr>" % "".join(props) if props else ""
    return (
        '<w:p><w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>'
        % (run_props, _xml_text(_clean_cell(text)))
    )


def _docx_table(block):
    # type: (tuple) -> str
    _heading, headers, body = block
    columns = len(headers)
    width = max(1, int(9000 / max(columns, 1)))
    parts = [
        "<w:tbl><w:tblPr><w:tblW w:w=\"0\" w:type=\"auto\"/>"
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="C0C0C0"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="C0C0C0"/>'
        "</w:tblBorders></w:tblPr>",
        "<w:tblGrid>%s</w:tblGrid>" % ("".join('<w:gridCol w:w="%d"/>' % width for _ in range(columns))),
    ]

    def row_xml(cells, header):
        cells_xml = []
        for cell in cells:
            shading = "<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"EFEFEF\"/>" if header else ""
            cells_xml.append(
                '<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>%s</w:tcPr>%s</w:tc>'
                % (width, shading, _docx_paragraph(cell, bold=header))
            )
        return "<w:tr>%s</w:tr>" % "".join(cells_xml)

    parts.append(row_xml(headers, True))
    for record in body:
        parts.append(row_xml(record, False))
    parts.append("</w:tbl>")
    # Word 规范：表格后必须跟一个空段，否则相邻表格会被合并
    parts.append("<w:p><w:r><w:t xml:space=\"preserve\"> </w:t></w:r></w:p>")
    return "".join(parts)


def _render_docx(flat, title):
    # type: (list, str) -> bytes
    blocks = []
    for kind, payload in flat:
        if kind == "para":
            blocks.append(_docx_paragraph(payload, bold=payload == title))
        elif kind == "comment":
            for line in payload:
                blocks.append(_docx_paragraph(line))
        elif kind == "table":
            blocks.append(_docx_table(payload))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>%s"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="851" w:footer="992"'
        ' w:gutter="0"/></w:sectPr>'
        "</w:body></w:document>" % "".join(blocks)
    )
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in zip(
            _DOCX_ORDER, (CONTENT_TYPES_XML.encode("utf-8"), RELS_XML.encode("utf-8"), document.encode("utf-8"))
        ):
            info = ZipInfo(name, date_time=_DOCX_ZIP_DATE)
            info.compress_type = 8  # ZIP_DEFLATED，固定值避免不同 zip 实现的 extra 字段差异
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def _flatten(title, tables, extra_notes):
    # type: (str, list, list) -> list
    """把（标题 + 表格 + 说明 + 免责声明）拼成按格式渲染用的块序列。

    正文与末尾一律经 `disclaimer.compose_document`，这样"免责声明必在最后"是结构事实；
    同时用它的纯文本结果过一次导出闸门，任何一块不干净都拒绝落盘。
    """
    body_lines = []  # type: list
    flat_body = []  # type: list
    for block in tables:
        if block[0] != title:  # 单表文档不再重复一次小节标题
            flat_body.append(("comment", [block[0]]))
            flat_body.append(("para", ""))
        flat_body.append(("table", block))
        flat_body.append(("para", ""))
        body_lines.extend(_md_table_lines(block))
        body_lines.append("")
    notes = list(extra_notes or [])
    composed = disclaimer.compose_document(title, body_lines, notes)
    flat = [("para", title)] + flat_body
    for note in notes:
        flat.append(("para", note))
    flat.append(("para", ""))
    for line in disclaimer.disclaimer_block():
        flat.append(("para", line))
    assert_export_safe("\n".join(composed))
    return flat


def _write(path, fmt, flat, title):
    # type: (str, str, list, str) -> dict
    if fmt == "docx":
        data = _render_docx(flat, title)
    else:
        if fmt == "csv":
            text = _render_csv(flat, title)
        elif fmt == "md":
            text = "\n".join(_lines_from_flat(flat)) + "\n"
        else:
            raise InputUnavailable("未知导出格式 %r，可选：%s" % (fmt, "/".join(FORMATS)))
        assert_export_safe(text)
        data = text.encode("utf-8")
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        raise InputUnavailable("导出目录不存在：%s" % _base_name(directory))
    with open(path, "wb") as handle:
        handle.write(data)
    return {
        "path": _base_name(path),
        "format": fmt,
        "bytes": len(data),
        "tables": len([item for item in flat if item[0] == "table"]),
        "columns": [item[1][1] for item in flat if item[0] == "table"],
    }


def _lines_from_flat(flat):
    # type: (list) -> list
    """md 渲染：说明性标题走粗体，表格块走原 md 行。"""
    lines = []
    for kind, payload in flat:
        if kind == "para":
            lines.append(payload)
        elif kind == "comment":
            lines.append("**%s**" % payload[0])
        elif kind == "table":
            lines.extend(_md_table_lines(payload))
    return lines


def _normalize_format(path, fmt):
    # type: (str, str) -> str
    fmt = (fmt or "").lower()
    if fmt not in FORMATS:
        raise InputUnavailable("未知导出格式 %r，可选：%s" % (fmt, "/".join(FORMATS)))
    suffix = "." + fmt
    if not path.lower().endswith(suffix):
        raise InputUnavailable("导出文件后缀与格式不符：%s 应为 %s" % (_base_name(path), suffix))
    return fmt


def export_priority_list(path, fmt, rows):
    # type: (str, str, list) -> dict
    """优先序清单导出（列 = `PLAN_COLUMNS`，blocked 行原样保留）。"""
    fmt = _normalize_format(path, fmt)
    if not rows:
        raise InputUnavailable("优先序清单为空：先跑 assess/aggregate/compare 再导出")
    for row in rows:
        missing = [name for name in PLAN_COLUMNS if name not in row]
        if missing:
            raise InputUnavailable("清单行缺少列 %s —— 行必须由 plan_rows() 生成" % "/".join(missing))
    block = _table("养护对策优先序清单", PLAN_COLUMNS, list(rows))
    notes = [
        "行序 = 引擎 `rank_priority` 的排序结果，导出层不再重排。",
        "blocked 行的数值列一律留空（不是 0）：未核对系数不进评定路径，拒算原因见 status/blocked_reason 列。",
        "grade 来自评定结果、delta 与劣化速率来自年对比结果；未提供对比年度时这两列留空。",
    ]
    flat = _flatten("养护对策优先序清单", [block], notes)
    return _write(path, fmt, flat, "养护对策优先序清单")


def export_assessment_report(path, fmt, ledger_snapshot, pci_results, mqi_results, extra_notes=None):
    # type: (str, str, dict, list, list, list) -> dict
    """评定结果报告：台账概况 + PCI 表 + MQI 表 + 固定免责声明。"""
    fmt = _normalize_format(path, fmt)
    if not ledger_snapshot:
        raise InputUnavailable("缺少台账概况，报告无法说明数据从哪来")
    snapshot = ledger_snapshot
    pci_results = list(pci_results or [])
    mqi_results = list(mqi_results or [])
    if not pci_results and not mqi_results:
        raise InputUnavailable("该年度没有任何评定/汇总结果，报告无内容可导（先 rmqc import）")

    snapshot_rows = []
    for key in (
        "year",
        "db_name",
        "ruleset_id",
        "ruleset_version",
        "route_rows",
        "segment_rows",
        "survey_rows",
        "distress_rows",
        "partition_change_rows",
    ):
        snapshot_rows.append({"item": key, "value": snapshot.get(key)})
    for receipt in snapshot.get("receipts") or []:
        snapshot_rows.append(
            {
                "item": "receipt:%s" % receipt.get("source_file"),
                "value": "入库 %s / 拒入 %s / 类别 %s"
                % (receipt.get("rows_accepted"), receipt.get("rows_rejected"), receipt.get("data_class")),
            }
        )
    checks = snapshot.get("checks_summary") or {}
    if checks:
        snapshot_rows.append(
            {
                "item": "checks",
                "value": "共 %s 条（检出 %s / 待核对未判定 %s）"
                % (checks.get("total"), checks.get("found"), checks.get("undetermined")),
            }
        )

    tables = [
        _table("台账概况", SNAPSHOT_COLUMNS, snapshot_rows),
        _table("路段 PCI 评定", PCI_COLUMNS, pci_results),
        _table("MQI 汇总与分级", MQI_COLUMNS, mqi_results),
    ]
    notes = [
        "本报告由同一离线内核算出：数字来自评定/汇总引擎的 `result_payload`，导出层不重算、不重排。",
        "status 为 blocked/uncomparable 的对象数值列留空并给出拒算原因；partial 只给已注明口径的部分值。",
        "系数未核对的格子一律未参与计算，相应结论待核对（应核实），不作为确定表述。",
    ]
    notes.extend(extra_notes or [])
    flat = _flatten("公路技术状况评定报告", tables, notes)
    return _write(path, fmt, flat, "公路技术状况评定报告")
