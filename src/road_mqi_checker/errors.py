"""异常族：把"拒算"做成类型级事实，而不是文案约定。"""

from road_mqi_checker.exit_codes import EXIT_CODE_FOR_EXCEPTION


class RmqcError(Exception):
    """本包所有可预期异常的基类。CLI 统一捕获并按 exit_code() 退出。"""

    exit_code = 1

    def exit_code_value(self):
        # type: () -> int
        return EXIT_CODE_FOR_EXCEPTION.get(type(self), self.__class__.exit_code)


class InputUnavailable(RmqcError):
    """输入不可用：文件缺失、格式非法、规则集选不出、台账 schema 不符。"""

    exit_code = 2


class SchemaViolation(RmqcError):
    """规则集/依据登记的结构违反（缺渠道档、空值自称已核对等）—— 一律拒绝加载。"""

    exit_code = 2


class PrivacyViolation(RmqcError):
    """合成数据标识符不在白名单内（真实路线号/真实行政代码/真实号段等）。"""

    exit_code = 2


class ContractViolation(RmqcError):
    """结果对象违反拒算契约：blocked 却带数值、结论无依据条款号等。"""

    exit_code = 1


class MilestoneNotImplemented(RmqcError):
    """骨架期占位符：领域逻辑属于哪个里程碑，未到该里程碑即拒绝执行。

    刻意不用 Python 内置 NotImplementedError —— 必须携带里程碑号，
    让"没做"与"做错了"在退出码与报告里区分开。
    """

    exit_code = 3

    def __init__(self, module_key, milestone, what=None, planned_artifact=None):
        # type: (str, str, Optional[str], Optional[str]) -> None
        self.module_key = module_key
        self.milestone = milestone
        self.what = what
        self.planned_artifact = planned_artifact
        message = "%s 尚未实现，计划交付里程碑 %s" % (module_key, milestone)
        if what:
            message = "%s 尚未实现：%s，计划交付里程碑 %s" % (module_key, what, milestone)
        if planned_artifact:
            message += "（依据文档 %s）" % planned_artifact
        super(MilestoneNotImplemented, self).__init__(message)


class BlockedByUnverifiedCoefficient(RmqcError):
    """用户强制要求出数值、但相关系数未核对时抛出（拒绝冒充全口径结果）。"""

    exit_code = 1


class OptionalDependencyMissing(RmqcError):
    """可选交付层（GUI/打包）依赖缺失：给出安装提示并降级退出，不崩栈。"""

    exit_code = 1

    def __init__(self, package, extra_hint):
        # type: (str, str) -> None
        self.package = package
        self.extra_hint = extra_hint
        super(OptionalDependencyMissing, self).__init__(
            "缺少可选依赖 %s，请执行 pip install road-mqi-checker[%s]" % (package, extra_hint)
        )
