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
from road_mqi_checker.results import STATUS_BLOCKED, STATUS_OK, STATUS_PARTIAL, STATUS_UNCOMPARABLE
from road_mqi_checker.ruleset import loader as ruleset_loader

PKG_NAME = "road-mqi-checker"


def ensure_utf8_stream(stream):
    """把输出流钉成 UTF-8，让同一句话在源码态、`python -m`、管道与重定向里落成同样的字节。

    Windows 控制台/管道默认按 ANSI 代码页编码（CI 的 windows runner 是 cp1252），
    本项目的拒因与结论里全是中文与箭头字符，跟随代码页会直接抛 UnicodeEncodeError——
    打包态已由 spec 的 `-X utf8` 解决，源码态在这里补上同一尺度。
    真控制台不接受重编码时退回 `errors="replace"`：宁可丢一个字，也不让命令崩在输出那一步。
    """
    encoding = (getattr(stream, "encoding", None) or "").lower().replace("_", "-")
    if encoding in ("utf-8", "") or not hasattr(stream, "reconfigure"):
        return stream
    for kwargs in ({"encoding": "utf-8"}, {"errors": "replace"}):
        try:
            stream.reconfigure(**kwargs)
            return stream
        except (ValueError, OSError, LookupError):
            continue
    return stream


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

    assess_p = sub.add_parser("assess", help="逐路段 PCI 评定与扣分展开（M2 已可用）")
    assess_p.add_argument("--year", required=True, type=int)
    assess_p.add_argument("--segment", default=None, help="只评定该路段；省略则评定该年度全部路段")

    aggregate_p = sub.add_parser("aggregate", help="MQI 汇总与分级（M4）")
    aggregate_p.add_argument("--year", required=True, type=int)
    aggregate_p.add_argument("--level", default="route", choices=list(mqi_engine.AGGREGATION_LEVELS))

    compare_p = sub.add_parser("compare", help="年对比与优先序（M4）")
    compare_p.add_argument("--from-year", required=True, type=int, dest="year_from")
    compare_p.add_argument("--to-year", required=True, type=int, dest="year_to")
    compare_p.add_argument("--segment", default=None, help="只对比该路段；省略则对比两个年度都在台账里的路段")

    bench_p = sub.add_parser("bench", help="合成数据（M1 已可用）与基准评测（M5 已可用）")
    bench_p.add_argument("action", choices=["generate", "run"])
    bench_p.add_argument("--seed", type=int, default=None)
    bench_p.add_argument("--out", default=None)
    bench_p.add_argument("--force", action="store_true", help="覆盖已存在的演示数据（冻结 fixtures 需显式解锁）")

    report_p = sub.add_parser("report", help="报告与清单导出（M6）")
    report_p.add_argument("--format", default="csv", choices=list(exporters.FORMATS))
    report_p.add_argument("--out", default=None, required=True, help="导出文件路径")
    report_p.add_argument("--year", required=True, type=int, help="导出对象所属年度")
    report_p.add_argument(
        "--level", default="route", choices=list(mqi_engine.AGGREGATION_LEVELS), help="汇总表用的汇总层级"
    )
    report_p.add_argument(
        "--scope",
        default="assessment",
        choices=["assessment", "plan"],
        help="assessment=评定结果报告（台账概况+PCI+MQI）；plan=对策优先序清单",
    )
    report_p.add_argument(
        "--from-year",
        default=None,
        type=int,
        dest="year_from",
        help="优先序清单的变化率列取该年度→--year 的对比结果；省略则这两列留空",
    )

    gui_p = sub.add_parser("gui", help="启动桌面壳（M6，需 [gui] extras）")
    gui_p.add_argument(
        "--probe",
        action="store_true",
        help="只构建主窗口与七页签并立即退出（CI / 干净环境存活探针，不进事件循环）",
    )
    return parser


def _connect(args):
    return ledger_db.connect(args.db if args.db else ":memory:")


def _bench_out_dir():
    """`bench generate` 缺省落点：源码态写仓库 `data/raw`，冻结态写当前工作目录。

    打包态的 `find_data_dir()` 命中的是包内只读的演示数据副本（交付面），
    把重生成结果写进自己的包里会让"内嵌数据与仓库逐份一致"这条红线失效。
    """
    from road_mqi_checker.data_paths import is_frozen

    if is_frozen():
        return os.path.join(os.getcwd(), "data", "raw")
    return os.path.join(find_data_dir(start=os.getcwd()), "raw")


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

    # 出数判据 = 必需格全生效，不是生效格总数（plan/02 §9 第 23 条）。
    # 三条路径各自点名还缺哪几格，避免"生效 1 格"被读成"某条路径已可出数"。
    from road_mqi_checker.bench import generator

    working = ruleset_loader.select_ruleset()
    path_gates = {
        "assess": generator.scoring_gate_pending_keys(working),
        "aggregate": generator.aggregation_gate_pending_keys(working),
        "actions": generator.action_gate_pending_keys(working),
    }
    report["path_gates"] = {
        name: {"pending_keys": keys, "can_emit_numbers": not keys} for name, keys in path_gates.items()
    }

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
        "出数判据（必需格是否全生效）："
        + " / ".join(
            "%s %s"
            % (
                name,
                "可出数" if report["path_gates"][name]["can_emit_numbers"] else "缺 %d 格不出数" % len(report["path_gates"][name]["pending_keys"]),
            )
            for name in ("assess", "aggregate", "actions")
        )
        + "（生效格数不等于可出数）",
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
        out_dir = args.out if args.out else _bench_out_dir()
        result = generator.generate(out_dir, seed=seed, force=args.force)
        scoring_pending = generator.scoring_gate_pending_keys(ruleset_loader.select_ruleset())
        gate_notes = generator.truth_gate_notes(ruleset_loader.select_ruleset())
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
            "真值四列："
            + (
                "评分列由评定引擎算出数值；引擎拒算的对象仍写 pending 令牌。"
                if not scoring_pending
                else "评分列仍为 pending 令牌（必需系数还缺 %d 格：%s）—— "
                     "本包生效系数 %d 格，但未核对不进评定路径。"
                     % (
                         len(scoring_pending),
                         "、".join(scoring_pending),
                         ruleset_loader.select_ruleset().summary()["computable"],
                     )
            ),
            "汇总列 mqi_partial_truth：" + gate_notes["mqi_partial_truth"]["note"],
            "对策列 recommended_action_truth：" + gate_notes["recommended_action_truth"]["note"],
        ]
        _print(payload, args.as_json, lines=lines)
        return EXIT_OK
    from road_mqi_checker.bench import generator as bench_generator

    if args.seed is not None and args.seed != bench_generator.DEFAULT_SEED:
        raise InputUnavailable(
            "基准评测定义在冻结演示数据上（seed=%d）；换 seed 要先把演示数据一起重生成并单独提交"
            % bench_generator.DEFAULT_SEED
        )
    payload = evaluation.run()
    _print(payload, args.as_json, lines=evaluation.report_lines(payload))
    return payload["gate"]["exit"]


def cmd_assess(args):
    from road_mqi_checker.pci import engine, trace

    conn, ruleset = _prepared(args)
    results = engine.assess_year(conn, args.year, ruleset, segment_id=args.segment)
    counts = engine.summarize_status(results)
    payload = {
        "year": args.year,
        "segment": args.segment,
        "ruleset": {"ruleset_id": ruleset.ruleset_id, "version": ruleset.version},
        "counts": counts,
        "results": [engine.result_payload(result) for result in results],
    }
    lines = [
        "PCI 评定：%s 年度共 %d 个路段（ok %d / partial %d / blocked %d），规则集 %s v%s"
        % (
            args.year,
            len(results),
            counts[STATUS_OK],
            counts[STATUS_PARTIAL],
            counts[STATUS_BLOCKED],
            ruleset.ruleset_id,
            ruleset.version,
        )
    ]
    for result in results:
        if result.status == STATUS_OK or result.status == STATUS_PARTIAL:
            lines.append(
                "  %s/%s %s PCI=%s 等级=%s 扣分合计=%s%s"
                % (
                    result.segment_id,
                    result.year,
                    result.status,
                    result.pci,
                    result.grade,
                    result.deducted_total,
                    "（%s）" % result.scope_note if result.scope_note else "",
                )
            )
            lines.extend(trace.report_lines(result, limit=3))
        else:
            lines.append("  %s/%s %s：%s" % (result.segment_id, result.year, result.status, result.blocked_reason))
    if counts[STATUS_BLOCKED]:
        lines.append("注：blocked 项的数值字段一律为空，不是 0 —— 系数未核对或台账含检出异常行时不出数。")
    _print(payload, args.as_json, lines=lines)
    # 退出码口径（plan/02 §6）：存在 blocked/partial/uncomparable = 1 降级完成
    return EXIT_DEGRADED if any(result.status != STATUS_OK for result in results) else EXIT_OK


def cmd_aggregate(args):
    from road_mqi_checker.bench import generator
    from road_mqi_checker.pci import engine as pci_engine
    from road_mqi_checker.strategy import rules as action_rules

    conn, ruleset = _prepared(args)
    pci_results = pci_engine.assess_year(conn, args.year, ruleset)
    results = mqi_engine.aggregate_year(conn, args.year, pci_results, ruleset, level=args.level)
    counts = mqi_engine.summarize_status(results)
    suggestions = action_rules.suggest_actions(conn, args.year, pci_results, results, ruleset)
    ranked = action_rules.rank_priority(suggestions, "pci", ascending=True)
    # 出数判据只走生成器那一份"必需格"实现（plan/02 §9 第 23 条），命令面不自建判据
    pending_keys = generator.aggregation_gate_pending_keys(ruleset)
    payload = {
        "year": args.year,
        "level": args.level,
        "ruleset": {"ruleset_id": ruleset.ruleset_id, "version": ruleset.version},
        "required_keys": list(mqi_engine.aggregation_required_keys()),
        "pending_keys": pending_keys,
        "counts": counts,
        "results": [mqi_engine.result_payload(result) for result in results],
        "priority_list": [action_rules.result_payload(item) for item in ranked],
    }
    lines = [
        "MQI 汇总（%s 级）：%s 年度共 %d 个对象（ok %d / partial %d / blocked %d / uncomparable %d），规则集 %s v%s"
        % (
            args.level,
            args.year,
            len(results),
            counts[STATUS_OK],
            counts[STATUS_PARTIAL],
            counts[STATUS_BLOCKED],
            counts[STATUS_UNCOMPARABLE],
            ruleset.ruleset_id,
            ruleset.version,
        )
    ]
    for result in results:
        if result.mqi is None:
            lines.append("  %s/%s %s：%s" % (result.level, result.object_id, result.status, result.blocked_reason))
        else:
            lines.append(
                "  %s/%s %s MQI=%s 等级=%s 加权里程=%s m 纳入分项=%s"
                % (
                    result.level,
                    result.object_id,
                    result.status,
                    result.mqi,
                    result.grade if result.grade is not None else "不判定（部分口径）",
                    result.weighted_length_m,
                    "/".join(result.included_components) or "-",
                )
            )
            if result.scope_note:
                lines.append("    口径：%s" % result.scope_note)
    for item in ranked[:10]:
        if item.action_class:
            lines.append(
                "  对策 %s/%s PCI=%s → %s（规则 %s，依据 %s）"
                % (item.segment_id, item.year, item.pci, item.action_class, item.rule_id, item.clause)
            )
        else:
            lines.append("  对策 %s/%s %s：%s" % (item.segment_id, item.year, item.status, item.blocked_reason))
    if counts[STATUS_BLOCKED] or counts[STATUS_PARTIAL]:
        lines.append(
            "注：blocked 的数值字段一律为空，不是 0；partial 只给已注明口径的部分值，"
            "不冒充完整 MQI，也不套用完整 MQI 的分级表述。"
        )
    _print(payload, args.as_json, lines=lines)
    # 退出码口径（plan/02 §6）：存在非 ok 对象 = 1 降级完成
    return EXIT_DEGRADED if any(result.status != STATUS_OK for result in results) else EXIT_OK


def cmd_compare(args):
    from road_mqi_checker.pci import engine as pci_engine
    from road_mqi_checker.strategy import compare

    conn, ruleset = _prepared(args)
    pci_results = list(pci_engine.assess_year(conn, args.year_from, ruleset))
    pci_results.extend(pci_engine.assess_year(conn, args.year_to, ruleset))
    if args.segment:
        segment_ids = [args.segment]
    else:
        segment_ids = compare.segment_ids_in_ledger(conn, args.year_from, args.year_to)
        if not segment_ids:
            raise InputUnavailable(
                "台账里 %s 与 %s 两个年度都没有路段行，无从对比（先 rmqc import）" % (args.year_from, args.year_to)
            )
    results = [
        compare.compare_years(conn, segment_id, args.year_from, args.year_to, pci_results, ruleset)
        for segment_id in segment_ids
    ]
    counts = compare.summarize_status(results)
    payload = {
        "year_from": args.year_from,
        "year_to": args.year_to,
        "segment": args.segment,
        "ruleset": {"ruleset_id": ruleset.ruleset_id, "version": ruleset.version},
        "counts": counts,
        "results": [compare.result_payload(result) for result in results],
    }
    lines = [
        "年对比 %s→%s：%d 个对象（ok %d / partial %d / blocked %d / uncomparable %d）"
        % (
            args.year_from,
            args.year_to,
            len(results),
            counts[STATUS_OK],
            counts[STATUS_PARTIAL],
            counts[STATUS_BLOCKED],
            counts[STATUS_UNCOMPARABLE],
        )
    ]
    for result in results:
        if result.delta is None:
            lines.append(
                "  %s %s：%s%s"
                % (
                    result.segment_id,
                    result.status,
                    result.blocked_reason,
                    "（因素 %s）" % result.comparability_reason if result.comparability_reason else "",
                )
            )
        else:
            lines.append(
                "  %s Δ=%s 劣化速率=%s/年 等级 %s→%s"
                % (
                    result.segment_id,
                    result.delta,
                    result.deterioration_rate_per_year,
                    result.grade_from,
                    result.grade_to,
                )
            )
            for row in compare.explain_change_rows(result):
                lines.append(
                    "    %s（%s）扣分变化 %s（系数 %s，依据 %s）"
                    % (
                        row["distress_type"],
                        row["severity"],
                        row["deducted_points"],
                        row["coefficient_key"],
                        row["clause"],
                    )
                )
    if counts[STATUS_UNCOMPARABLE]:
        lines.append("注：不可比对象不出变化率、不按重叠里程摊分，只出原因代码与说明。")
    _print(payload, args.as_json, lines=lines)
    return EXIT_DEGRADED if any(result.status != STATUS_OK for result in results) else EXIT_OK


def cmd_report(args):
    from road_mqi_checker.pci import engine as pci_engine
    from road_mqi_checker.strategy import compare, rules

    conn, ruleset = _prepared(args)
    pci_results = list(pci_engine.assess_year(conn, args.year, ruleset))
    if not pci_results:
        raise InputUnavailable(
            "台账里 %s 年度没有路段行，报告无内容可导（先 rmqc import --file ... --year %s）"
            % (args.year, args.year)
        )
    mqi_results = list(mqi_engine.aggregate_year(conn, args.year, pci_results, ruleset, level=args.level))
    suggestions = rules.rank_priority(
        rules.suggest_actions(conn, args.year, pci_results, mqi_results, ruleset), "pci", True
    )
    payload = {
        "scope": args.scope,
        "format": args.format,
        "year": args.year,
        "level": args.level,
        "ruleset": {"ruleset_id": ruleset.ruleset_id, "version": ruleset.version},
        "counts": pci_engine.summarize_status(pci_results),
    }
    if args.scope == "plan":
        compare_results = []
        if args.year_from is not None:
            combined = list(pci_engine.assess_year(conn, args.year_from, ruleset))
            combined.extend(pci_results)
            segment_ids = compare.segment_ids_in_ledger(conn, args.year_from, args.year)
            compare_results = [
                compare.result_payload(
                    compare.compare_years(conn, segment_id, args.year_from, args.year, combined, ruleset)
                )
                for segment_id in segment_ids
            ]
        rows = exporters.plan_rows(
            [rules.result_payload(item) for item in suggestions],
            pci_results=[pci_engine.result_payload(item) for item in pci_results],
            compare_results=compare_results,
            from_year=args.year_from,
        )
        result = exporters.export_priority_list(args.out, args.format, rows)
        payload["from_year"] = args.year_from
        payload["export"] = result
        payload["row_count"] = len(rows)
        lines = [
            "优先序清单导出：%s（%s 格式，%d 行，%d 字节）"
            % (result["path"], args.format, len(rows), result["bytes"]),
            "行序来自 `rank_priority`，导出层不重排；blocked 行原样保留、数值列留空。",
        ]
        if args.year_from is None:
            lines.append("未给 --from-year：delta 与 deterioration_rate_per_year 两列留空（不做推测性摊分）。")
    else:
        snapshot = exporters.build_ledger_snapshot(conn, args.year, ruleset, db=args.db)
        result = exporters.export_assessment_report(
            args.out,
            args.format,
            snapshot,
            [pci_engine.result_payload(item) for item in pci_results],
            [mqi_engine.result_payload(item) for item in mqi_results],
        )
        payload["export"] = result
        lines = [
            "评定报告导出：%s（%s 格式，%d 张表，%d 字节）"
            % (result["path"], args.format, result["tables"], result["bytes"]),
            "内容：台账概况 + %d 个路段 PCI + %d 个 %s 级汇总对象，末尾挂固定免责声明。"
            % (len(pci_results), len(mqi_results), args.level),
        ]
    for item in pci_results:
        if item.status != STATUS_OK:
            lines.append("注：blocked/partial 对象的数值列在导出里留空（不是 0），拒算原因随行给出。")
            break
    _print(payload, args.as_json, lines=lines)
    # 退出码口径（plan/02 §6）：导出成功但存在降级对象 = 1
    degraded = any(item.status != STATUS_OK for item in pci_results) or any(
        item.status != STATUS_OK for item in mqi_results
    )
    return EXIT_DEGRADED if degraded else EXIT_OK


def cmd_gui(args):
    return gui_app.main(["--probe"] if args.probe else [])


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
    ensure_utf8_stream(sys.stdout)
    ensure_utf8_stream(sys.stderr)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except RmqcError as exc:
        sys.stderr.write("%s: %s\n" % (exc.__class__.__name__, exc))
        return exc.exit_code_value()


if __name__ == "__main__":
    sys.exit(main())
