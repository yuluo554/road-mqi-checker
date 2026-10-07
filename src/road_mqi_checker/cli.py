"""同一内核的命令行入口（交付材料 2：exe 之外的脚本化验证通路）。

退出码语义见 exit_codes 模块，定稿即锁进测试：
0 完成 / 1 降级完成 / 2 输入不可用 / 3 属未来里程碑未实现。
"""

import argparse
import json
import os
import platform
import sys

from road_mqi_checker._meta import MILESTONE, PLACEHOLDER_MILESTONES, __version__
from road_mqi_checker.bench import evaluation
from road_mqi_checker.data_paths import find_data_dir
from road_mqi_checker.errors import InputUnavailable, RmqcError
from road_mqi_checker.exit_codes import EXIT_DEGRADED, EXIT_OK
from road_mqi_checker.gui import app as gui_app
from road_mqi_checker.ledger import checks as ledger_checks
from road_mqi_checker.ledger import db as ledger_db
from road_mqi_checker.ledger import importer
from road_mqi_checker.mqi import engine as mqi_engine
from road_mqi_checker.report import exporters
from road_mqi_checker.ruleset import loader as ruleset_loader

PKG_NAME = "road-mqi-checker"


def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = argparse.ArgumentParser(
        prog="rmqc",
        description="公路技术状况评定与养护决策支持工具（离线内核 CLI）",
    )
    parser.add_argument("--db", default=None, help="SQLite 台账路径；省略时用内存库（不落盘）")
    parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    sub.add_parser("version", help="打印版本与里程碑状态")
    sub.add_parser("selfcheck", help="内核自检：数据目录、规则集、系数门、台账 schema")

    ruleset_p = sub.add_parser("ruleset", help="规则集包查看与选取")
    ruleset_p.add_argument("action", choices=["list", "show"])
    ruleset_p.add_argument("--province", default=None)
    ruleset_p.add_argument("--year", default=None)
    ruleset_p.add_argument("--surface", default=None, choices=["asphalt", "cement"])

    ledger_p = sub.add_parser("ledger", help="台账建库与结构检查")
    ledger_p.add_argument("action", choices=["init", "tables"])

    import_p = sub.add_parser("import", help="年度检测表入库 + 导入回执 + 八类确定性校验")
    import_p.add_argument("--file", required=True)
    import_p.add_argument("--year", required=True, type=int)
    import_p.add_argument("--dry-run", action="store_true", help="只预检不落库")
    import_p.add_argument(
        "--data-class",
        default=None,
        dest="data_class",
        choices=list(importer.DATA_CLASSES),
        help="数据类别声明：SYNTHETIC 受白名单约束，user 是你自己的真实台账；文件头有标记时以此为准",
    )

    assess_p = sub.add_parser("assess", help="逐路段 PCI 评定（M2）")
    assess_p.add_argument("--year", required=True, type=int)
    assess_p.add_argument("--segment", default=None, help="只评定该路段；省略则评定该年度全部路段")

    aggregate_p = sub.add_parser("aggregate", help="MQI 汇总与分级（M4）")
    aggregate_p.add_argument("--year", required=True, type=int)
    aggregate_p.add_argument("--level", default="route", choices=list(mqi_engine.AGGREGATION_LEVELS))

    compare_p = sub.add_parser("compare", help="年对比与优先序（M4）")
    compare_p.add_argument("--from-year", required=True, type=int, dest="year_from")
    compare_p.add_argument("--to-year", required=True, type=int, dest="year_to")

    bench_p = sub.add_parser("bench", help="合成数据（M1 已可用）与基准评测（M5）")
    bench_p.add_argument("action", choices=["generate", "run"])
    bench_p.add_argument("--seed", type=int, default=None)
    bench_p.add_argument("--out", default=None)
    bench_p.add_argument("--force", action="store_true", help="覆盖已存在的演示数据（冻结 fixtures 需显式解锁）")

    report_p = sub.add_parser("report", help="报告与清单导出（M6）")
    report_p.add_argument("--format", default="csv", choices=list(exporters.FORMATS))
    report_p.add_argument("--out", default=None, required=True, help="导出文件路径")

    sub.add_parser("gui", help="启动桌面壳（M6，需 [gui] extras）")
    return parser


def _connect(args):
    return ledger_db.connect(args.db if args.db else ":memory:")


def _prepared(args):
    """打开台账（必要时建表）并选好规则集 —— 所有下游命令共用同一套前置。"""
    conn = _connect(args)
    ledger_db.initialize(conn)
    return conn, ruleset_loader.select_ruleset()


def _print(payload, as_json, lines=None):
    if as_json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    else:
        for line in (lines if lines is not None else [str(payload)]):
            sys.stdout.write(line + "\n")


def cmd_version(args):
    _print(
        {"package": PKG_NAME, "version": __version__, "milestone": MILESTONE, "python": platform.python_version()},
        args.as_json,
        lines=["%s %s (milestone %s) / Python %s" % (PKG_NAME, __version__, MILESTONE, platform.python_version())],
    )
    return EXIT_OK


def cmd_selfcheck(args):
    report = {
        "package": PKG_NAME,
        "version": __version__,
        "milestone": MILESTONE,
        "python": platform.python_version(),
        "platform": platform.system().lower(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
    failures = []

    try:
        report["data_dir"] = find_data_dir(start=os.getcwd())
    except RmqcError as exc:
        report["data_dir"] = None
        failures.append("data_dir: %s" % exc)

    summaries = []
    active = 0
    blocked = 0
    for path in ruleset_loader.list_ruleset_files():
        ruleset = ruleset_loader.load_file(path)
        summaries.append(ruleset.summary())
        active += ruleset.summary()["computable"]
        blocked += ruleset.summary()["blocked"]
    report["rulesets"] = summaries
    # 系数门：M0 常态是 closed（一格已核对系数都没有），这是诚实状态而非故障
    report["coefficient_gate"] = {"open": active > 0, "active": active, "blocked": blocked}

    conn = _connect(args)
    ledger_db.initialize(conn)
    tables = ledger_db.table_names(conn)
    report["ledger_schema"] = {
        "expected": ledger_db.expected_tables(),
        "present": tables,
        "ok": tables == ledger_db.expected_tables(),
    }
    if not report["ledger_schema"]["ok"]:
        failures.append("ledger_schema: %s" % report["ledger_schema"])
    conn.close()

    report["gui_pages"] = list(gui_app.PAGE_TITLES)
    report["placeholders"] = dict(PLACEHOLDER_MILESTONES)
    report["failures"] = failures
    report["exit"] = EXIT_OK if not failures else 1

    lines = [
        "road-mqi-checker %s (milestone %s), Python %s on %s"
        % (__version__, MILESTONE, report["python"], report["platform"]),
        "data_dir: %s" % report["data_dir"],
        "ruleset 包: %d 个，生效系数 %d 格，拒算系数 %d 格 → 系数门 %s"
        % (len(summaries), active, blocked, "开" if active else "关（未核对系数不进评定路径）"),
        "台账 schema: %s" % ("ok" if report["ledger_schema"]["ok"] else "FAIL"),
        "GUI 页签: %s" % " / ".join(report["gui_pages"]),
        "待实现模块: %d 个（见 plan/02 §8）" % len(report["placeholders"]),
    ]
    _print(report, args.as_json, lines=lines)
    return report["exit"]


def cmd_ruleset(args):
    if args.action == "list":
        rows = []
        for path in ruleset_loader.list_ruleset_files():
            rows.append(ruleset_loader.load_file(path).summary())
        lines = [
            "%s v%s 覆盖 %s 系数 %d 格（生效 %d / 拒算 %d）"
            % (
                row["ruleset_id"],
                row["version"],
                row["applies_to"],
                row["total_coefficients"],
                row["computable"],
                row["blocked"],
            )
            for row in rows
        ]
        _print(rows, args.as_json, lines=lines)
        return EXIT_OK
    ruleset = ruleset_loader.select_ruleset(args.province, args.year, args.surface)
    rows = [
        {
            "key": coef.key,
            "kind": coef.kind,
            "surface_type": coef.surface_type,
            "status": coef.status,
            "effective_status": coef.effective_status,
            "computable": coef.computable,
            "register_ref": coef.register_ref,
        }
        for coef in ruleset.coefficients
    ]
    lines = ["%s %s" % (ruleset.ruleset_id, ruleset.version)] + [
        "%-40s %-18s %-9s %-10s %s"
        % (row["key"], row["kind"], row["surface_type"] or "-", row["effective_status"], row["register_ref"])
        for row in rows
    ]
    _print({"ruleset": ruleset.summary(), "coefficients": rows}, args.as_json, lines=lines)
    return EXIT_OK


def cmd_ledger(args):
    conn = _connect(args)
    ledger_db.initialize(conn)
    tables = ledger_db.table_names(conn)
    payload = {"tables": tables, "persisted": bool(args.db)}
    lines = ["表: %s" % ", ".join(tables)]
    if not args.db:
        lines.append("（内存库，未落盘；--db PATH 才写文件）")
    _print(payload, args.as_json, lines=lines)
    conn.close()
    return EXIT_OK


def cmd_import(args):
    conn, ruleset = _prepared(args)
    receipt = importer.import_csv(
        conn, args.file, args.year, data_class=args.data_class, dry_run=args.dry_run
    )
    payload = {"receipt": receipt.summary(), "receipt_rows": receipt.to_rows()}
    lines = ["导入回执："] + receipt.report_lines()
    if args.dry_run:
        lines.append("（--dry-run：未写库）")
    elif not receipt.duplicate_file:
        findings = ledger_checks.run_all_checks(conn, args.year, ruleset)
        summary = ledger_checks.summarize(findings)
        payload["checks"] = summary
        payload["findings"] = [finding.as_dict() for finding in findings]
        lines.append("确定性校验：")
        lines.extend(ledger_checks.report_lines(findings, summary)[1:])
        lines.append("注：拒入行只说明该行未进台账；被检出的异常行仍在台账里，等 M2 的评定通路对其拒算。")
    _print(payload, args.as_json, lines=lines)
    # 退出码口径（plan/02 §6）：有拒入行 = 1 降级完成；校验检出项本身不改退出码
    return EXIT_DEGRADED if receipt.rows_rejected else EXIT_OK


def cmd_bench(args):
    if args.action == "generate":
        from road_mqi_checker.bench import generator

        seed = generator.DEFAULT_SEED if args.seed is None else args.seed
        if seed < 0:
            raise InputUnavailable("seed 必须是非负整数，收到 %d" % seed)
        out_dir = args.out if args.out else os.path.join(find_data_dir(start=os.getcwd()), "raw")
        result = generator.generate(out_dir, seed=seed, force=args.force)
        totals = result["totals"]
        payload = dict(result)
        payload["seed"] = seed
        lines = [
            "合成数据：%s 与 truth/ 共 %d 份文件（本次实际改写 %d 份，其余逐字节一致未重写）"
            % (result["raw_dir"], result["files_written"], result["files_changed"]),
            "规模口径：3 条虚拟路线 × 4 个年度，seed=%d" % seed,
            "raw 行 %d / truth 行 %d / 注入用例 %d" % (
                totals["raw_rows"], totals["truth_rows"], totals["injected_cases"]
            ),
            "注入分布：" + ", ".join("%s x%d" % (key, totals["by_issue"][key]) for key in sorted(totals["by_issue"])),
            "干净对照格子：" + ", ".join(totals["clean_cells"]),
            "真值四列当前一律为 pending 令牌（生效系数 0 格，未核对不出数）。",
        ]
        _print(payload, args.as_json, lines=lines)
        return EXIT_OK
    evaluation.gate(evaluation.initial_metric_table())
    return EXIT_OK


def cmd_assess(args):
    from road_mqi_checker.pci import engine

    conn, ruleset = _prepared(args)
    engine.compute_segment_pci(conn, args.segment or "", args.year, ruleset)
    return EXIT_OK


def cmd_aggregate(args):
    conn, ruleset = _prepared(args)
    by_level = {
        "segment": lambda: mqi_engine.aggregate_segment_mqi(conn, "", args.year, [], ruleset),
        "route": lambda: mqi_engine.aggregate_route_mqi(conn, "", args.year, [], ruleset),
        "network": lambda: mqi_engine.aggregate_network_mqi(conn, args.year, [], ruleset),
    }
    by_level[args.level]()
    return EXIT_OK


def cmd_compare(args):
    from road_mqi_checker.strategy import compare

    conn, ruleset = _prepared(args)
    compare.compare_years(conn, "", args.year_from, args.year_to, [], ruleset)
    return EXIT_OK


def cmd_report(args):
    exporters.export_priority_list(args.out, args.format, [])
    return EXIT_OK


def cmd_gui(args):
    gui_app.main()
    return EXIT_OK


_HANDLERS = {
    "version": cmd_version,
    "selfcheck": cmd_selfcheck,
    "ruleset": cmd_ruleset,
    "ledger": cmd_ledger,
    "import": cmd_import,
    "assess": cmd_assess,
    "aggregate": cmd_aggregate,
    "compare": cmd_compare,
    "bench": cmd_bench,
    "report": cmd_report,
    "gui": cmd_gui,
}


def dispatch(args):
    return _HANDLERS[args.command](args)


def main(argv=None):
    # type: (list) -> int
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except RmqcError as exc:
        sys.stderr.write("%s: %s\n" % (exc.__class__.__name__, exc))
        return exc.exit_code_value()


if __name__ == "__main__":
    sys.exit(main())
