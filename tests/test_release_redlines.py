"""发布前红线的常驻闸门（M0 就能锁住的部分）。

脱敏全量扫描属 M6，但"夹具值不得混进数据/规则集"、"导出必带免责声明"、
"README 不许吹已实现"这三条现在就能当硬门，越晚立越容易漏。
"""

import os
import shutil

import pytest

from road_mqi_checker.errors import PrivacyViolation
from road_mqi_checker.report import disclaimer
from road_mqi_checker.ruleset import loader
from support_git import BINARY_SUFFIXES, git_lines, tracked_files, walk_files


def _walk_files(root, suffixes):
    return walk_files(root, suffixes)


def test_fixture_channel_never_appears_in_data_or_shipped_rulesets(repo_root):
    """夹具档只允许出现在 tests/fixtures —— 数据载荷或内置规则集里出现即判污染。

    只扫数据载荷（json/csv/txt）与内置规则集；data/README.md 是台账文档，
    描述机制名称不构成数据污染。
    """
    scanned = _walk_files(os.path.join(repo_root, "data"), (".json", ".csv", ".tsv", ".txt"))
    scanned += _walk_files(loader._BUILTIN_DIR, (".json",))
    offenders = []
    for path in scanned:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        if "fixture" in text.lower():
            offenders.append(path)
    assert not offenders, "夹具字样进入交付面：%s" % offenders


def test_shipped_rulesets_all_load_without_fixture_flag():
    """内置包必须能在 allow_fixture=False 下加载，否则夹具混进了交付物。"""
    for path in loader.list_ruleset_files():
        loader.load_file(path, allow_fixture=False)


def test_exported_document_ends_with_disclaimer():
    lines = disclaimer.compose_document("某路线评定意见", ["路段 SYN-01：PCI 未评定（扣分比率待核对，应核实）"])
    assert lines[-2] == disclaimer.DISCLAIMER
    assert lines[-1] == disclaimer.DATA_CLASS_NOTE


def test_export_refuses_over_claimed_conclusion():
    with pytest.raises(PrivacyViolation):
        disclaimer.compose_document("评定意见", ["该扣分表已与原文核对并已确认"])


def test_disclaimer_states_auxiliary_positioning():
    text = disclaimer.DISCLAIMER
    for phrase in ("辅助定位", "不替代", "应核实"):
        assert phrase in text


def test_readme_declares_skeleton_status(repo_root):
    """README 不许在项目未做完时自称可用：状态行跟随当前里程碑，未实现清单必须还在。

    断言用 `_meta.MILESTONE` 而不是写死 "M0"，否则每交付一个里程碑都要回来改这条测试，
    而那种"顺手把测试改成能过"正是文档与代码漂移的入口。
    """
    from road_mqi_checker import _meta

    with open(os.path.join(repo_root, "README.md"), "r", encoding="utf-8") as handle:
        text = handle.read()
    assert _meta.MILESTONE in text, "README 状态行没写当前里程碑 %s" % _meta.MILESTONE
    assert "未实现" in text or "尚未实现" in text
    for section in ("快速开始", "限制", "免责声明", "评测"):
        assert section in text, "README 缺章节：%s" % section


def test_readme_exit_codes_match_code(repo_root):
    """README 写的退出码语义要与 exit_codes 单点定义一致（文档不许自己编）。"""
    from road_mqi_checker import exit_codes

    with open(os.path.join(repo_root, "README.md"), "r", encoding="utf-8") as handle:
        text = handle.read()
    for code, meaning in exit_codes.EXIT_CODE_MEANINGS.items():
        assert meaning in text, "README 未描述退出码 %d（%s）" % (code, meaning)


def test_license_is_mit(repo_root):
    with open(os.path.join(repo_root, "LICENSE"), "r", encoding="utf-8") as handle:
        head = handle.read(200)
    assert head.startswith("MIT License")


def test_every_source_and_test_file_is_git_tracked(repo_root):
    """.gitignore 的通配会悄悄吞掉源码包（写规则时实测：`ledger/` 会命中 src/**/ledger/）。

    漏跟踪的文件在开发机上一切正常，只有全新 clone 才会 ImportError —— 所以这里直接拿
    `git ls-files` 与工作树对账，并把误吞它的 ignore 规则一起报出来。
    """
    if shutil.which("git") is None:
        pytest.skip("环境无 git")
    if not os.path.isdir(os.path.join(repo_root, ".git")):
        pytest.skip("不在 git 仓库内（例如只拷贝了源码树）")
    # git 输出仓库相对路径且永远用正斜杠，与工作树比较时要换成本地分隔符
    names = tracked_files(repo_root)
    tracked = set(name.replace("/", os.sep) for name in names or [])
    assert tracked, "git ls-files 返回空清单（多半是编码或仓库状态问题，见 support_git）"

    untracked = []
    for root_name in ("src", "tests"):
        root = os.path.join(repo_root, root_name)
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if not name.endswith((".py", ".json")):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, name), repo_root)
                if rel not in tracked:
                    untracked.append(rel)
    if not untracked:
        return

    probe = git_lines(repo_root, ["check-ignore", "-v", "--"] + untracked)
    raise AssertionError(
        "以下源码/测试文件未被 git 跟踪，新 clone 会缺件：%s\n误吞它们的 ignore 规则：%s"
        % (untracked, (probe.stdout or "").strip() or "（check-ignore 未命中，可能是未曾 add）")
    )


def test_no_binary_samples_without_ledger_entry(repo_root):
    """仓库里不该有未登记的二进制样例；将来出现就要同步 data/README 台账（M6 白名单的前身）。

    口径是**已跟踪文件**，不是工作树：装在仓库里的 `.venv/`（README 快速开始就是这么写的）
    和本地跑的 `ledger.sqlite` 都是 gitignore 掉的运行期产物，把它们算进交付面会让这条门
    在任何一台照 README 做过干净环境验证的机器上假红。
    """
    names = tracked_files(repo_root) if shutil.which("git") is not None else None
    if names is None:
        candidates = _walk_files(repo_root, BINARY_SUFFIXES)
    else:
        candidates = [os.path.join(repo_root, name.replace("/", os.sep)) for name in names]
    offenders = [path for path in candidates if path.endswith(BINARY_SUFFIXES)]
    assert not offenders, "出现二进制文件，需同步 data/README 台账与脱敏白名单：%s" % offenders
