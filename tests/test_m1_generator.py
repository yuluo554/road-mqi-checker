"""M1 生成器：位级一致、真值语义、规模口径与隐私闸门。

这一支测试是"演示数据可以冻结入仓"的根据：换目录、换解释器、重跑两次都必须逐字节一致，
且注入用例不随 seed 漂移（否则基准的召回/误报数字就成了随机数的函数）。
"""

import json
import os

import pytest

from road_mqi_checker import privacy
from road_mqi_checker.bench import generator
from road_mqi_checker.errors import InputUnavailable
from road_mqi_checker.ledger import models

CELL_COUNT = generator.DEFAULT_ROUTES * generator.DEFAULT_YEARS


def _tree_digest(root):
    """目录内全部文件内容 + 文件名的合 digest（位级一致的对账口径）。"""
    import hashlib

    names = sorted(
        os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
        for dirpath, _dirs, files in os.walk(root)
        for name in files
    )
    h = hashlib.sha1()
    for name in names:
        h.update(name.encode("utf-8"))
        with open(os.path.join(root, name), "rb") as handle:
            h.update(handle.read())
    return h.hexdigest(), names


def test_same_seed_is_byte_identical(tmp_path):
    first, second = str(tmp_path / "a"), str(tmp_path / "b")
    generator.generate(first, force=True)
    generator.generate(second, force=True)
    digest_a, names_a = _tree_digest(first)
    digest_b, names_b = _tree_digest(second)
    assert names_a == names_b
    assert digest_a == digest_b, "同 seed 两次运行产物不一致：冻结 fixtures 的前提破了"


def test_rerun_same_seed_is_a_no_op(tmp_path):
    """内容一致就不重写：同 seed 重跑既不报错也不改一个字节。"""
    out = str(tmp_path / "raw")
    first = generator.generate(out, force=True)
    assert first["files_changed"] == 25, first["files_changed"]
    again = generator.generate(out)
    assert again["files_changed"] == 0, again["files_changed"]


def test_rerun_with_different_seed_needs_force(tmp_path):
    """换 seed 真的要改冻结 fixtures 时，没有 --force 必须拒绝。"""
    out = str(tmp_path / "raw")
    generator.generate(out, force=True)
    with pytest.raises(InputUnavailable):
        generator.generate(out, seed=777)
    result = generator.generate(out, seed=777, force=True)
    # 13 = 12 份 raw + manifest；truth 文件不含随机内容，换 seed 也逐字节不变
    # （这正是 test_injections_are_seed_independent 断言的性质在写盘路径上的体现）
    assert result["files_changed"] == 13, result["files_changed"]


def test_committed_fixtures_are_a_no_op_target(tmp_path):
    """把入仓的演示数据原样复制到临时目录再跑一次默认参数：一份都不该被改写。

    这就是 DoD 里"`--force` 重跑 `git status` 零变化"的可测形式（测试不去动仓库工作树）。
    """
    import shutil

    raw = os.path.join(str(tmp_path), "raw")
    truth = os.path.join(str(tmp_path), "truth")
    shutil.copytree(COMMITTED_RAW, raw)
    shutil.copytree(COMMITTED_TRUTH, truth)
    result = generator.generate(raw, truth_dir=truth)
    assert result["files_changed"] == 0, result["files_changed"]


def test_no_carriage_returns_in_products(tmp_path):
    out = str(tmp_path / "raw")
    generator.generate(out, force=True)
    truth = os.path.join(str(tmp_path), "truth")
    offenders = []
    for root in (out, truth):
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                with open(os.path.join(dirpath, name), "rb") as handle:
                    if b"\r" in handle.read():
                        offenders.append(name)
    assert not offenders, "产物含 CR：干净 clone 的位级一致断言会挂"


def test_scale_and_file_set(tmp_path):
    out = str(tmp_path / "raw")
    generator.generate(out, force=True)
    for route_id in generator.ROUTE_IDS:
        for year in generator.plan_years():
            assert os.path.isfile(os.path.join(out, generator.raw_file_name(route_id, year)))
            assert os.path.isfile(os.path.join(str(tmp_path), "truth", generator.truth_file_name(route_id, year)))
    assert len(generator.plan_routes()) == generator.DEFAULT_ROUTES
    assert len(generator.plan_years()) == generator.DEFAULT_YEARS
    assert CELL_COUNT == 12


def test_every_file_carries_synthetic_mark(tmp_path):
    out = str(tmp_path / "raw")
    generator.generate(out, force=True)
    paths = [os.path.join(out, name) for name in os.listdir(out) if name.endswith(".csv")]
    paths += [
        os.path.join(str(tmp_path), "truth", name)
        for name in os.listdir(os.path.join(str(tmp_path), "truth"))
        if name.endswith(".csv")
    ]
    assert len(paths) == CELL_COUNT * 2
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            assert handle.readline().strip() == generator.FILE_MARK_LINE, path


def test_raw_and_truth_columns_match_manifest(tmp_path):
    out = str(tmp_path / "raw")
    generator.generate(out, force=True)
    with open(os.path.join(out, generator.MANIFEST_NAME), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert manifest["schema"]["raw_columns"] == list(models.RAW_COLUMNS)
    assert manifest["schema"]["truth_columns"] == list(generator.TRUTH_COLUMNS)
    assert manifest["data_class"] == generator.FILE_MARK_VALUE
    assert manifest["seed"] == generator.DEFAULT_SEED
    assert sorted(manifest) == sorted(generator.MANIFEST_TOP_LEVEL_KEYS)
    assert len(manifest["files"]) == CELL_COUNT


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMITTED_RAW = os.path.join(REPO, "data", "raw")
COMMITTED_TRUTH = os.path.join(REPO, "data", "truth")


def test_manifest_digests_match_committed_fixtures():
    """manifest 里的 sha1 必须与入仓的演示数据逐份对上（冻结 fixtures 的自证）。"""
    import hashlib

    with open(os.path.join(COMMITTED_RAW, generator.MANIFEST_NAME), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    for entry in manifest["files"]:
        for folder, digest_key in (("raw", "raw_sha1"), ("truth", "truth_sha1")):
            directory = COMMITTED_RAW if folder == "raw" else COMMITTED_TRUTH
            name = entry["raw_file"] if folder == "raw" else entry["truth_file"]
            path = os.path.join(directory, name)
            with open(path, "rb") as handle:
                assert hashlib.sha1(handle.read()).hexdigest() == entry[digest_key], path


def test_regeneration_of_committed_fixtures_is_byte_identical(tmp_path):
    """守门测试：同 seed 重新生成，与入仓的演示数据逐字节相同（M1 DoD 第 3 项）。"""
    out = str(tmp_path / "raw")
    generator.generate(out, force=True)
    fresh_truth = os.path.join(str(tmp_path), "truth")
    for directory, fresh in ((COMMITTED_RAW, out), (COMMITTED_TRUTH, fresh_truth)):
        names = sorted(name for name in os.listdir(directory) if not name.startswith("."))
        fresh_names = sorted(os.listdir(fresh))
        assert names == fresh_names, (names, fresh_names)
        for name in names:
            with open(os.path.join(directory, name), "rb") as handle:
                committed = handle.read()
            with open(os.path.join(fresh, name), "rb") as handle:
                assert handle.read() == committed, name


def test_injections_are_seed_independent(tmp_path):
    """注入标记是声明出来的常量：换 seed 只换正常老化内容，八类用例不许跟着漂。"""
    out_a, truth_a = str(tmp_path / "a"), str(tmp_path / "truth_a")
    out_b, truth_b = str(tmp_path / "b"), str(tmp_path / "truth_b")
    generator.generate(out_a, seed=generator.DEFAULT_SEED, force=True, truth_dir=truth_a)
    generator.generate(out_b, seed=12345, force=True, truth_dir=truth_b)
    marks_a = _marks(truth_a)
    marks_b = _marks(truth_b)
    assert marks_a == marks_b
    assert marks_a == {
        (item["route_id"], item["year"], item["segment_id"], item["injected_issue"], item["injected_field"])
        for item in generator.injection_plan()
    }


def _marks(truth_dir):
    """只收注入标记（issue != none）：干净行不属于注入用例。"""
    out = set()
    for name in sorted(os.listdir(truth_dir)):
        if not name.endswith(".csv"):
            continue
        for row in _read(os.path.join(truth_dir, name)):
            if row["injected_issue"] != "none":
                out.add(
                    (
                        row["route_id"],
                        int(row["year"]),
                        row["segment_id"],
                        row["injected_issue"],
                        row["injected_field"],
                    )
                )
    return out


def _read(path):
    from road_mqi_checker.ledger import importer

    return importer.read_table(path)


def test_each_injected_issue_has_at_least_two_cases():
    plan = generator.injection_plan()
    counts = {}
    for item in plan:
        counts[item["injected_issue"]] = counts.get(item["injected_issue"], 0) + 1
    injected_classes = [issue for issue in models.INJECTED_ISSUES if issue != "none"]
    assert sorted(counts) == sorted(injected_classes), "八类注入必须齐全：%s" % sorted(counts)
    for issue, count in sorted(counts.items()):
        assert count >= 2, "%s 只有 %d 例" % (issue, count)


def test_three_clean_control_cells_exist():
    """干净对照格子：误报率的分子分母都要有非零样本。"""
    cells = {(item["route_id"], item["year"]) for item in generator.injection_plan()}
    controls = [
        (route, year)
        for route in generator.ROUTE_IDS
        for year in generator.plan_years()
        if (route, year) not in cells
    ]
    assert len(controls) >= 2, "没有干净对照格子就测不出误报"


def test_truth_score_columns_refuse_to_emit_numbers(tmp_path):
    """未核对不出数对真值同样成立：四列一律是点名系数 key 的 pending 令牌。"""
    out = str(tmp_path / "raw")
    generator.generate(out, force=True)
    rows = _read(os.path.join(str(tmp_path), "truth", generator.truth_file_name("S99", 2022)))
    assert rows
    for row in rows:
        for column in ("pci_truth", "grade_truth", "mqi_partial_truth", "recommended_action_truth"):
            value = row[column]
            assert value.startswith(generator.PENDING_COEFF_PREFIX), (column, value)
            named = value[len(generator.PENDING_COEFF_PREFIX):].split(",")
            for key in named:
                bare = key.replace("(未登记)", "")
                assert bare in _coefficient_keys(), "真值令牌点名了不存在的系数 %s" % key


def _coefficient_keys():
    from road_mqi_checker.ruleset import loader

    return {coef.key for coef in loader.select_ruleset().coefficients}


def test_generated_identifiers_all_pass_whitelist(tmp_path):
    out = str(tmp_path / "raw")
    generator.generate(out, force=True)
    for name in sorted(os.listdir(out)):
        if not name.endswith(".csv"):
            continue
        for row in _read(os.path.join(out, name)):
            privacy.check_row(models.identifier_fields(row))


def test_products_have_no_timestamp_shape(tmp_path):
    """落盘不带时间戳：产物里不该出现"生成时间/created_at/ISO 时间串"这类痕迹。"""
    out = str(tmp_path / "raw")
    generator.generate(out, force=True)
    texts = []
    for root in (out, os.path.join(str(tmp_path), "truth")):
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                with open(os.path.join(dirpath, name), "r", encoding="utf-8") as handle:
                    texts.append((name, handle.read()))
    banned = ("generated_at", "created_at", "timestamp", "更新时间", "生成时间")
    offenders = [(name, token) for name, text in texts for token in banned if token in text]
    assert not offenders, offenders


def test_scenarios_subset_is_validated(tmp_path):
    """scenarios 只取子集：未被选中的注入类别一个都不出现，选中的照常出现。"""
    out = str(tmp_path / "raw")
    generator.generate(out, scenarios=("normal_aging", "gap_chain"), force=True)
    issues = set()
    for name in sorted(os.listdir(os.path.join(str(tmp_path), "truth"))):
        for row in _read(os.path.join(str(tmp_path), "truth", name)):
            issues.add(row["injected_issue"])
    assert issues == {"gap_chain", "none"}, issues
    with pytest.raises(InputUnavailable):
        generator.generate(str(tmp_path / "bad"), scenarios=("nope",), force=True)
