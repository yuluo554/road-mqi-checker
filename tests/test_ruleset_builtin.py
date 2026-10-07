"""内置基础规则集的 M0 状态必须是"一格已核对系数都没有"。

这条测试是本题核心纪律的落点：骨架期评定路径无生效系数，
若有人凭记忆往 JSON 里填了数字，这里就会红。
"""

import json
import os

import pytest

from road_mqi_checker.ruleset import loader
from road_mqi_checker.ruleset import status as st

BASE_NAME = "base-jtg5210-2018.json"


@pytest.fixture
def base_ruleset():
    path = os.path.join(loader._BUILTIN_DIR, BASE_NAME)
    assert os.path.isfile(path), "内置基础规则集缺失：%s" % path
    return loader.load_file(path)


def test_builtin_package_has_no_fixture_status(base_ruleset):
    assert all(coef.status != st.FIXTURE for coef in base_ruleset.coefficients)


def test_all_coefficients_start_pending(base_ruleset):
    assert base_ruleset.computable_coefficients() == []
    assert len(base_ruleset.blocked_coefficients()) == len(base_ruleset.coefficients)


def test_no_numeric_values_anywhere_in_pending_package(base_ruleset):
    """未核对 → values 一律 null；出现任何数字即视为"凭记忆填表"。"""
    offenders = [coef.key for coef in base_ruleset.coefficients if coef.values is not None]
    assert not offenders, offenders
    with open(os.path.join(loader._BUILTIN_DIR, BASE_NAME), "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    for coef in raw["coefficients"]:
        assert coef.get("values") is None, coef["key"]


def test_every_coefficient_declares_a_register_ref(base_ruleset):
    """每格系数都要指向依据台账的某一行（data/README.md#N）。"""
    missing = [coef.key for coef in base_ruleset.coefficients if not coef.register_ref]
    assert not missing, "无出处的系数：%s" % missing
    bad = [coef.key for coef in base_ruleset.coefficients if not coef.register_ref.startswith("data/README.md#")]
    assert not bad, "出处格式必须是 data/README.md#N：%s" % bad


def _verification_ledger_rows(repo_root):
    """取 data/README.md §一 的依据查证记录表数据行（#N 就是这张表的行号）。"""
    with open(os.path.join(repo_root, "data", "README.md"), "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## 一、"))
    rows = []
    for line in lines[start:]:
        if line.startswith("## ") and rows:
            break
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("#", "") or set(cells[0]) <= set("-: "):
            continue
        rows.append(cells)
    assert rows, "依据查证记录表解析为空，#N 编号失去意义"
    return rows


def test_register_refs_point_at_existing_ledger_rows(base_ruleset, repo_root):
    rows = _verification_ledger_rows(repo_root)
    for coef in base_ruleset.coefficients:
        row_no = int(coef.register_ref.split("#")[1])
        assert 1 <= row_no <= len(rows), "%s 指向台账第 %d 行，超出依据表行数 %d" % (coef.key, row_no, len(rows))
        referenced = rows[row_no - 1]
        assert referenced[1], "%s 指向的依据行没有标准/依据名称" % coef.key


def test_register_refs_match_their_coefficient_kind(base_ruleset, repo_root):
    """扣分/权重/分级三态系数都挂在同一条依据行上，防止指向已查证失败的那行。"""
    rows = _verification_ledger_rows(repo_root)
    for coef in base_ruleset.coefficients:
        row_no = int(coef.register_ref.split("#")[1])
        referenced = " ".join(rows[row_no - 1])
        if coef.kind in ("deduct_ratio", "component_weight", "grade_threshold"):
            if coef.basis[0].standard_id.startswith("JTG"):
                assert "JTG 5210-2018" in referenced, "%s 的依据行不含它所引用的标准" % coef.key


def test_required_cells_cover_the_whole_assessment_path(base_ruleset):
    """评定 + 汇总 + 分级 + 对策四类系数都得有位置，缺类就是范围漏了。"""
    kinds = set(coef.kind for coef in base_ruleset.coefficients)
    assert {"deduct_ratio", "component_weight", "grade_threshold", "action_rule"} <= kinds


def test_both_surface_types_have_deduct_tables(base_ruleset):
    surfaces = set(coef.surface_type for coef in base_ruleset.coefficients if coef.kind == "deduct_ratio")
    assert surfaces == {"asphalt", "cement"}


def test_blocked_reason_wording_is_honest(base_ruleset):
    for coef in base_ruleset.blocked_coefficients():
        reason = coef.block_reason()
        assert "应核实" in reason
        assert "已确认" not in reason


def test_ruleset_json_is_utf8_clean_and_lf_only():
    path = os.path.join(loader._BUILTIN_DIR, BASE_NAME)
    with open(path, "rb") as handle:
        raw = handle.read()
    assert b"\r" not in raw, "规则集含 CR，会打挂位级一致断言"
    assert raw.decode("utf-8")
