"""系数三态语义与"生效口径"：把"数据未核对"落进引擎，而不是文档承诺。"""

import copy
import json
import os

import pytest

from road_mqi_checker.errors import SchemaViolation
from road_mqi_checker.ruleset import loader
from road_mqi_checker.ruleset import status as st

FIXTURE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "fixture-ruleset.json")


def _coefficient(status=st.PENDING, values=None, kind="deduct_ratio", basis_status=None, **overrides):
    payload = {
        "key": "k.test",
        "kind": kind,
        "surface_type": "asphalt",
        "status": status,
        "values": values,
        "unit": "扣分比率",
        "basis": [
            {
                "standard_id": "JTG 5210-2018",
                "status": basis_status or status,
                "clause": "表 4.2.1" if status in (st.LOCATED, st.VERIFIED, st.FIXTURE) else "",
                "channel": "交通运输部公告" if status in (st.VERIFIED, st.FIXTURE) else "",
                "verified_at": "2026-10-07" if status in (st.VERIFIED, st.FIXTURE) else "",
                "locator": "原文页码 31" if status in (st.VERIFIED, st.FIXTURE) else "",
            }
        ],
        "register_ref": "data/README.md#1",
        "note": "",
    }
    payload.update(overrides)
    return payload


def _load(payload, allow_fixture=False):
    return loader.Coefficient.from_dict(payload, allow_fixture=allow_fixture)


# ---- 状态词汇 ----


def test_status_vocabulary_is_three_plus_fixture():
    assert set(st.ALL_STATUSES) == {"pending", "located", "verified", "fixture"}
    assert set(st.STATUS_RANK) == set(st.ALL_STATUSES)
    assert len(st.ALL_STATUSES) == 4


def test_unknown_status_rejected():
    with pytest.raises(SchemaViolation):
        st.check_status("guessed")


def test_located_and_pending_both_block_computation():
    """located（知道条号）与 pending（一无所知）都不放行计算，但两档必须并存。"""
    assert not st.is_computable(st.PENDING)
    assert not st.is_computable(st.LOCATED)
    assert st.is_computable(st.VERIFIED)
    assert st.STATUS_RANK[st.PENDING] < st.STATUS_RANK[st.LOCATED]


def test_effective_status_takes_weakest_link():
    assert st.effective_status([st.VERIFIED, st.LOCATED, st.VERIFIED]) == st.LOCATED
    assert st.effective_status([st.VERIFIED]) == st.VERIFIED
    assert st.effective_status([]) == st.PENDING


def test_coefficient_effective_status_follows_its_clause():
    """规则自称已核对但依据条款只是 located → 整格不可用（反向索引，补 M1 真实漏洞）。"""
    coef = _load(_coefficient(st.VERIFIED, {"light": 0.1}, basis_status=st.LOCATED))
    assert coef.effective_status == st.LOCATED
    assert not coef.computable


# ---- schema 硬门 ----


def test_verified_with_empty_values_is_error():
    with pytest.raises(SchemaViolation) as info:
        _load(_coefficient(st.VERIFIED, {}))
    assert "values 为空" in str(info.value)


def test_pending_with_values_is_error():
    """未核对的阈值一律写 null，带数值即拒绝加载。"""
    with pytest.raises(SchemaViolation):
        _load(_coefficient(st.PENDING, {"light": 0.5}))


def test_located_with_values_is_error():
    with pytest.raises(SchemaViolation):
        _load(_coefficient(st.LOCATED, {"light": 0.5}))


def test_located_without_channel_is_error():
    """located 也必须挂渠道档（渠道+日期+可定位载体），缺即校验失败。"""
    payload = _coefficient(st.LOCATED, None)
    payload["basis"][0]["channel"] = ""
    with pytest.raises(SchemaViolation) as info:
        _load(payload)
    assert "channel" in str(info.value)


def test_coefficient_without_basis_is_error():
    payload = _coefficient(st.PENDING, None)
    payload["basis"] = []
    with pytest.raises(SchemaViolation):
        _load(payload)


def test_unknown_kind_is_error():
    with pytest.raises(SchemaViolation):
        _load(_coefficient(st.PENDING, None, kind="vibes"))


# ---- 夹具档的双通路纪律 ----


def test_fixture_status_rejected_outside_test_path():
    with pytest.raises(SchemaViolation) as info:
        _load(_coefficient(st.FIXTURE, {"light": 0.42}), allow_fixture=False)
    assert "tests/fixtures" in str(info.value)


def test_fixture_status_accepted_on_test_path():
    coef = _load(_coefficient(st.FIXTURE, {"light": 0.42}), allow_fixture=True)
    assert coef.computable


def test_fixture_ruleset_file_loads_only_with_flag():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    with pytest.raises(SchemaViolation):
        loader.RuleSet.from_dict(payload)
    ruleset = loader.RuleSet.from_dict(payload, allow_fixture=True)
    assert len(ruleset.computable_coefficients()) == 1


def test_ruleset_schema_version_guard():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    bad = copy.deepcopy(payload)
    bad["schema_version"] = 99
    with pytest.raises(SchemaViolation):
        loader.RuleSet.from_dict(bad, allow_fixture=True)


def test_ruleset_rejects_duplicate_keys():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    bad = copy.deepcopy(payload)
    bad["coefficients"] = bad["coefficients"] * 2
    with pytest.raises(SchemaViolation):
        loader.RuleSet.from_dict(bad, allow_fixture=True)


def test_ruleset_requires_nonempty_coefficients():
    with pytest.raises(SchemaViolation):
        loader.RuleSet.from_dict(
            {
                "schema_version": loader.SCHEMA_VERSION,
                "ruleset_id": "x",
                "version": "1",
                "applies_to": {},
                "coefficients": [],
            }
        )


# ---- 选取口径 ----


def _pending_coefficient(key="tolerance.length_closure"):
    return {
        "key": key,
        "kind": "grade_threshold",
        "status": st.PENDING,
        "values": None,
        "basis": [{"standard_id": "user-defined", "status": st.PENDING}],
        "register_ref": "data/README.md#7",
    }


def _ruleset_payload(ruleset_id, applies_to, keys):
    return {
        "schema_version": loader.SCHEMA_VERSION,
        "ruleset_id": ruleset_id,
        "version": "1",
        "applies_to": applies_to,
        "coefficients": [_pending_coefficient(key) for key in keys],
    }


def test_base_ruleset_lives_at_package_root():
    """内置包目录在包根而不是子包目录 —— 冻结打包时靠它收 package-data。"""
    assert os.path.basename(loader._BUILTIN_DIR) == "rulesets"
    assert os.path.basename(os.path.dirname(loader._BUILTIN_DIR)) == "road_mqi_checker"


def test_select_prefers_most_specific_coverage(tmp_path, monkeypatch):
    for name, payload in (
        ("base.json", _ruleset_payload("base-star", {"province": "*", "year": "*", "surface_type": "*"}, ["k_base"])),
        (
            "prov.json",
            _ruleset_payload("prov-99", {"province": "99", "year": "*", "surface_type": "*"}, ["k_prov"]),
        ),
        ("both.json", _ruleset_payload("prov-99-2026", {"province": "99", "year": "2026"}, ["k_both"])),
    ):
        (tmp_path / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(loader, "_BUILTIN_DIR", str(tmp_path))
    monkeypatch.delenv(loader._USER_DIR_ENV, raising=False)

    assert loader.select_ruleset(province="99", year="2026").ruleset_id == "prov-99-2026"
    assert loader.select_ruleset(province="99", year="2020").ruleset_id == "prov-99"
    assert loader.select_ruleset(province="88", year="2020").ruleset_id == "base-star"


def test_selection_is_independent_of_directory_order(tmp_path, monkeypatch):
    """选取过程本身也必须确定：不允许靠 os.listdir 的顺序决胜。"""
    names = ["a-base.json", "z-base.json"]
    for name in names:
        (tmp_path / name).write_text(
            json.dumps(_ruleset_payload("same-id-" + name[0], {"province": "*", "year": "*"}, ["k"])),
            encoding="utf-8",
        )
    monkeypatch.setattr(loader, "_BUILTIN_DIR", str(tmp_path))
    monkeypatch.delenv(loader._USER_DIR_ENV, raising=False)
    first = loader.select_ruleset(province="99")
    second = loader.select_ruleset(province="99")
    assert first.ruleset_id == second.ruleset_id


def test_select_raises_input_unavailable_when_nothing_covers(tmp_path, monkeypatch):
    (tmp_path / "only.json").write_text(
        json.dumps(_ruleset_payload("prov-99-only", {"province": "99", "year": "2026"}, ["k"])),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "_BUILTIN_DIR", str(tmp_path))
    monkeypatch.delenv(loader._USER_DIR_ENV, raising=False)
    from road_mqi_checker.errors import InputUnavailable

    with pytest.raises(InputUnavailable):
        loader.select_ruleset(province="88")
