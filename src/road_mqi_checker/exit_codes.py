"""CLI 退出码语义（定稿即锁进测试，重构不得漂移 —— plan/02 §6）。

四个码各自回答一个问题，混用即口径漂移：

0  完成：全部请求的评定/汇总/对比均按已核对系数算出，无降级。
1  降级完成：跑通了，但存在 blocked/uncomparable/partial 项（系数未核对、分项不全、
   跨年划分不可比），报告已注明口径。
2  输入不可用：文件、台账或规则集本身不可解析/选不出，未进入评定路径。
3  尚未实现：请求的功能属于未来里程碑，骨架期明确拒绝（不假装成功）。
"""

EXIT_OK = 0
EXIT_DEGRADED = 1
EXIT_INPUT_UNUSABLE = 2
EXIT_UNIMPLEMENTED = 3

EXIT_CODE_MEANINGS = {
    EXIT_OK: "完成",
    EXIT_DEGRADED: "降级完成（存在 blocked/uncomparable/partial 项）",
    EXIT_INPUT_UNUSABLE: "输入不可用（未进入评定路径）",
    EXIT_UNIMPLEMENTED: "尚未实现（属未来里程碑）",
}

ALL_EXIT_CODES = (EXIT_OK, EXIT_DEGRADED, EXIT_INPUT_UNUSABLE, EXIT_UNIMPLEMENTED)


def _build_exception_code_map():
    # type: () -> dict
    # 延迟导入避免包初始化期循环依赖
    from road_mqi_checker import errors

    return {
        errors.InputUnavailable: EXIT_INPUT_UNUSABLE,
        errors.SchemaViolation: EXIT_INPUT_UNUSABLE,
        errors.PrivacyViolation: EXIT_INPUT_UNUSABLE,
        errors.MilestoneNotImplemented: EXIT_UNIMPLEMENTED,
        errors.ContractViolation: EXIT_DEGRADED,
        errors.BlockedByUnverifiedCoefficient: EXIT_DEGRADED,
        errors.OptionalDependencyMissing: EXIT_DEGRADED,
    }


_EXIT_CODE_CACHE = None


def _resolve_map():
    # type: () -> dict
    global _EXIT_CODE_CACHE
    if _EXIT_CODE_CACHE is None:
        _EXIT_CODE_CACHE = _build_exception_code_map()
    return _EXIT_CODE_CACHE


class _ExitCodeLookup(object):
    """EXIT_CODE_FOR_EXCEPTION 的只读映射视图：按异常类查退出码。"""

    def get(self, key, default=1):
        return _resolve_map().get(key, default)


EXIT_CODE_FOR_EXCEPTION = _ExitCodeLookup()
