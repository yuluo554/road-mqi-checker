"""固定免责声明与结论措辞（导出的每个文件都要带，属交付红线）。"""

from road_mqi_checker.privacy import assert_honest_wording

DISCLAIMER = (
    "本工具输出的是“按已核对规则算出的评定值与规则链建议”，属辅助定位："
    "不替代养护科学决策，不替代正式评定报告，不用于设计、造价与验收。"
    "标注为待核对（pending/located）的系数一律未参与计算，相应结果只给出拒算原因与应核实提示。"
)

DATA_CLASS_NOTE = "演示与评测数据为程序合成的虚构数据（SYNTHETIC），不代表任何真实路线。"


def disclaimer_block():
    # type: () -> list
    return [DISCLAIMER, DATA_CLASS_NOTE]


def compose_document(title, body_lines, extra_notes=None):
    # type: (str, list, list) -> list
    """把标题、正文、附加说明与固定免责声明拼成导出文本行。

    导出层（M6）只允许通过本函数拼文档，这样"免责声明必在末尾"是结构性事实。
    结论文本先过措辞纪律：未核对项只能写"应核实/待核对"。
    """
    notes = list(extra_notes or [])
    lines = [title, ""]
    lines.extend(body_lines)
    lines.extend(notes)
    lines.append("")
    lines.extend(disclaimer_block())
    assert_honest_wording("\n".join(lines))
    return lines
