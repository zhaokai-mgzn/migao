# case_ids: MC-236
"""`scripts/resolve_cases_conflict.py` 的 L0 守卫（离线 / 零 LLM / 秒级；本 PR 无关联 issue，标 N/A（基建））。

## 病（2026-11-05 一晚实测 8+ 次手写同一段脚本）

`.github/cases/*.yml` 是**单一共享写面**：每个包都在文件末尾追加自己的 case 块
⇒ main 一前进，所有在飞分支都冲突。手写解法每次都踩同一批坑，本文件把**四条判据**锁住：

| # | 判据 | 红证（本文件注入的坏形态） |
|---|---|---|
| 1 | 选块 = **id 集合差**，按前缀分组 / 组内按数字排序 | 改回**字符串比较号段** ⇒ 误抓 `PK-*` / `SP-*` / `WH-*` / `QC-*` |
| 2 | 残缺块（无 `title:`）**不追加**、非零退出、点名 id | 放宽成「跳过继续」⇒ 写出一份半截用例 |
| 3 | **main 的 id 不许丢**（main ⊆ 结果） | 去掉该检查 ⇒ 丢 main 的用例静默通过 |
| 4 | 重号**拒绝**并说明「让号」 | 去掉该检查 ⇒ 重号被当成新用例写进去 |
| 5 | 生成物刷新失败 ⇒ **逐字节回滚** | 不注入：用替身生成器真的失败一次 |
| 6 | 端到端：`git init` + 两分支 + **真 merge** ⇒ 冲突消失且语义正确 | — |

## 一处实测得到的额外判据（写在这里防下一次误判）

按「从**工作树**的带标记文件按行区间取块」会**结构性**产生残缺块：git 把两侧追加区按公共行
对齐，常拆成**多个 hunk**（`- id:`/`legacy_id:`/`title:` 落在第一个，`user_inputs:` 之后落在
第二个）⇒ 块在第一个 `=======` 处被截断成「只有 id + title 的半块」，而 `title:` 检查**照样通过**。
⇒ 实现改读索引 `:2:` / `:3:`（未冲突的双方完整体）；判据 6 的真冲突夹具覆盖这条路径。

红证卫生（同 `migao-dev-flow` §19.1 元规则 ③）：注入走 `unit_ci_workflows.injection.inject`
（0 命中 / 命中数不符 / 换了等于没换都**当场抛错**），注入前后逐条自证 `mutated != src`。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

from unit_ci_workflows.injection import inject

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "resolve_cases_conflict.py"
REAL_SOURCE = SCRIPT.read_text(encoding="utf-8")

CASES_REL = Path(".github/cases/misc.yml")
HEADER = 'schema: "case-contract/1.0"\ndomain: misc\n\ncases:\n'

#: 底（main）里的 id：`MC` 号段 + **别人的四个前缀**（同一个文件里的邻居）
MAIN_IDS = [f"MC-{i:03d}" for i in range(1, 221)]
FOREIGN_IDS = ["PK-100", "SP-050", "WH-7", "QC-2"]


# ═══════════════════════════════════════════════════════════════════════════
# 夹具构造（纯字符串 + 临时 git 仓；不碰真仓的 cases 文件）
# ═══════════════════════════════════════════════════════════════════════════


def _case(cid: str, *, with_title: bool = True) -> str:
    """一个最小但**完整**的 case 块（字段形态照抄 `.github/cases/misc.yml`）。"""
    lines = [f"  - id: {cid}", '    legacy_id: ""']
    if with_title:
        lines.append(f'    title: "用例 {cid}"')
    lines += [
        "    domains:", "      - misc", "    tier: normal",
        "    user_inputs:", f'      - "u {cid}"',
        "    expectations:", "      - tool: direct_reply",
        "    data_checks:", f'      - "d {cid}"',
    ]
    return "\n".join(lines) + "\n"


def _doc(*cids: str) -> str:
    return HEADER + "".join(_case(cid) for cid in cids)


def _load(source: str = REAL_SOURCE) -> types.ModuleType:
    """把被测脚本当模块加载（源码可注入变异；不 import 变异体，无缓存污染）。"""
    mod = types.ModuleType("resolve_cases_conflict_under_test")
    mod.__file__ = str(SCRIPT)
    exec(compile(source, str(SCRIPT), "exec"), mod.__dict__)
    return mod


def _mutant(old: str, new: str) -> types.ModuleType:
    """注入坏形态并**自证注入生效**（`inject` 已含 0 命中 / 歧义 / 空操作三道闸）。"""
    mutated = inject(REAL_SOURCE, old, new, where=str(SCRIPT))
    assert mutated != REAL_SOURCE
    return _load(mutated)


MOD = _load()


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          check=False)


def _append(path: Path, chunk: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + chunk, encoding="utf-8")


def _init_repo(tmp_path: Path) -> Path:
    """一个带 base 提交的临时仓（`main` 分支 + `origin` 裸库 + `origin/main` 远端引用）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for key, value in (("user.email", "case@test.local"), ("user.name", "case"),
                       ("commit.gpgsign", "false")):
        _git(repo, "config", key, value)
    (repo / ".github" / "cases").mkdir(parents=True)
    (repo / CASES_REL).write_text(_doc(*MAIN_IDS[:5]), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "-M", "main")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def _build_conflict(tmp_path: Path, *, ours: str, theirs: str) -> Path:
    """造一个**真冲突**：两条分支都往 `misc.yml` 末尾追加，`feat` 上 `git merge origin/main`。

    ⚠️ 这是判据 6 的承载体，也是判据 2/5 的现场：真 merge 会造出索引 stage 2/3，
    而**工作树**里的块会被 git 拆成多个 hunk 截断 —— 实现必须不受其影响。
    """
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feat")
    _append(repo / CASES_REL, ours)
    _git(repo, "commit", "-qam", "feat: ours")
    _git(repo, "checkout", "-q", "main")
    _append(repo / CASES_REL, theirs)
    _git(repo, "commit", "-qam", "main: theirs")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", "feat")
    merged = _git(repo, "merge", "origin/main")
    assert merged.returncode != 0, "夹具无效：merge 没有冲突"
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *args],
                          capture_output=True, text=True, check=False)


def _cases_path(repo: Path) -> Path:
    return repo / CASES_REL


# ═══════════════════════════════════════════════════════════════════════════
# 判据 1：选块 = id 集合差（不是字符串比较号段）+ 前缀分组 / 数字排序
# ═══════════════════════════════════════════════════════════════════════════


def test_only_ids_absent_from_main_are_selected() -> None:
    main = _doc(*MAIN_IDS, *FOREIGN_IDS)
    blocks, problems = MOD.select_branch_blocks(main, [("stage2", main + _case("MC-221"))])
    assert problems == []
    assert [b.cid for b in blocks] == ["MC-221"], "别的前缀（PK/SP/WH/QC）被误抓成「我的」"


def test_appended_blocks_are_grouped_by_prefix_then_sorted_by_number() -> None:
    main = _doc(*MAIN_IDS, *FOREIGN_IDS)
    ours = main + _case("MC-1000") + _case("ZZ-1") + _case("MC-999") + _case("AA-2")
    blocks, _problems = MOD.select_branch_blocks(main, [("stage2", ours)])
    # 字典序会把 MC-1000 排在 MC-999 前面；正确口径 = 前缀分组 + 数字比较
    assert [b.cid for b in blocks] == ["AA-2", "MC-999", "MC-1000", "ZZ-1"]


def test_red_proof_string_threshold_grabs_other_prefixes() -> None:
    """红证 ①：把选块改回 `cid >= "MC-221"` ⇒ 判据 1 红，并点名误抓的四个前缀。"""
    mutant = _mutant(
        "    main_set = set(main_ids)\n    return [b for b in side_blocks if b.cid not in main_set]",
        '    return [b for b in side_blocks if b.cid >= "MC-221"]',
    )
    main = _doc(*MAIN_IDS, *FOREIGN_IDS)
    ours = main + _case("MC-221")

    mutant_ids = {b.cid for b in mutant.select_branch_blocks(main, [("stage2", ours)])[0]}
    assert mutant_ids == {"MC-221", "PK-100", "SP-050", "WH-7", "QC-2"}
    assert {"PK-100", "SP-050", "WH-7", "QC-2"} <= mutant_ids, "注入未复现「误抓别的前缀」"

    # 对照：真实现只取 MC-221（这就是判据 1 的牙）
    real_ids = [b.cid for b in MOD.select_branch_blocks(main, [("stage2", ours)])[0]]
    assert real_ids == ["MC-221"]

    # 第二道防线：把误抓的结果落盘 ⇒ 因「重复 id」被拒（不是静默写进来）
    grabbed = mutant.select_branch_blocks(main, [("stage2", ours)])[0]
    problems = MOD.check_document(main, grabbed, MOD.build_document(main, grabbed))
    assert any("重复 id" in p for p in problems)


# ═══════════════════════════════════════════════════════════════════════════
# 判据 2：残缺块（无 title:）不追加
# ═══════════════════════════════════════════════════════════════════════════


def test_incomplete_block_is_refused_by_name() -> None:
    half = "  - id: MC-902\n    legacy_id: \"\"\n    domains:\n      - misc\n"
    main = _doc(*MAIN_IDS[:5])
    blocks, problems = MOD.select_branch_blocks(main, [("stage2", main + half)])
    assert [b.cid for b in blocks] == ["MC-902"]
    assert any("MC-902" in p and "title" in p for p in problems), "残缺块必须点名 + 说清缺什么"


def test_half_block_with_title_only_is_refused() -> None:
    """🔴 半块形态（`migao-dev-flow` §34.16 ③）：git 拆多 hunk ⇒ 截断后**含 `title:`** 却丢了其余。

    只查 `title:` 会放行这种块 ⇒ 必须按**必需字段**判（现取语料：`title:` / `user_inputs:`
    各缺 0 条；`expectations:` 有 1 条合法缺 ⇒ **不收**它，避免假红）。
    """
    half = ('  - id: MC-903\n    legacy_id: ""\n    title: "半块"\n    domains:\n      - misc\n')
    main = _doc(*MAIN_IDS[:5])
    blocks, problems = MOD.select_branch_blocks(main, [("stage2", main + half)])
    assert [b.cid for b in blocks] == ["MC-903"]
    assert any("MC-903" in p and "user_inputs" in p for p in problems), "半块必须点名缺 user_inputs"
    assert not any("title" in p for p in problems), "该块**有** title，别报缺 title（假红）"


def test_block_missing_expectations_is_accepted() -> None:
    """负控：语料里 `expectations:` 有 1 条合法缺（`MC-139`）⇒ 本工具**不许**把它判成残缺。"""
    main = _doc(*MAIN_IDS[:5])
    no_expect = ('  - id: MC-904\n    legacy_id: ""\n    title: "只有 data_checks"\n'
                 '    domains:\n      - misc\n    user_inputs:\n      - "u"\n'
                 '    data_checks:\n      - "d"\n')
    blocks, problems = MOD.select_branch_blocks(main, [("stage2", main + no_expect)])
    assert [b.cid for b in blocks] == ["MC-904"]
    assert problems == []


def test_red_proof_skipping_incomplete_block_writes_a_half_case() -> None:
    """红证 ②：放宽成「跳过继续」⇒ 判据 2 红（问题列表空 ⇒ CLI 会把它写进去）。"""
    mutant = _mutant("        if missing:", "        if False:")
    half = "  - id: MC-902\n    legacy_id: \"\"\n    domains:\n      - misc\n"
    main = _doc(*MAIN_IDS[:5])
    blocks, problems = mutant.select_branch_blocks(main, [("stage2", main + half)])
    assert problems == [], "注入未放宽（仍有问题 ⇒ 造不出「半截用例被写进去」的形态）"
    assert [b.cid for b in blocks] == ["MC-902"]
    # 半截块能通过 YAML 解析 ⇒ 只有 title 判据能拦住它（这就是它存在的理由）
    assert mutant.check_document(main, blocks, mutant.build_document(main, blocks)) == []


# ═══════════════════════════════════════════════════════════════════════════
# 判据 3：main 的 id 不许丢
# ═══════════════════════════════════════════════════════════════════════════


def test_losing_a_main_id_is_refused() -> None:
    main = _doc("MC-001", "MC-002", "MC-221")
    blocks = [MOD.Block("MC-222", _case("MC-222").rstrip("\n"))]
    result = _doc("MC-001", "MC-002", "MC-222")
    problems = MOD.check_document(main, blocks, result)
    assert any("丢了 main" in p and "MC-221" in p for p in problems)


def test_red_proof_dropping_the_main_subset_check_passes_silently() -> None:
    """红证 ③：去掉「main ⊆ 结果」⇒ 丢 main 的用例也判绿。"""
    mutant = _mutant(
        "    lost = [c for c in main_ids if c not in result_set]",
        "    lost = []",
    )
    main = _doc("MC-001", "MC-002", "MC-221")
    blocks = [MOD.Block("MC-222", _case("MC-222").rstrip("\n"))]
    result = _doc("MC-001", "MC-002", "MC-222")
    assert [p for p in mutant.check_document(main, blocks, result) if "丢了 main" in p] == []
    assert any("丢了 main" in p for p in MOD.check_document(main, blocks, result))


# ═══════════════════════════════════════════════════════════════════════════
# 判据 4：重号拒绝 + 说明「让号」
# ═══════════════════════════════════════════════════════════════════════════


def test_clashing_id_is_refused_with_let_number_advice() -> None:
    main = _doc("MC-001", "MC-221")
    blocks = [MOD.Block("MC-221", _case("MC-221").rstrip("\n"))]
    result = MOD.build_document(main, blocks)
    problems = MOD.check_document(main, blocks, result)
    assert any("已在 main 里" in p and "让号" in p and "MC-221" in p for p in problems)
    assert any("重复 id" in p for p in problems)


def test_red_proof_without_the_clash_check_the_duplicate_slips_in() -> None:
    """红证 ④：去掉重号检查 ⇒ 只剩「重复 id」这条，不再说明该怎么处置（让号）。"""
    mutant = _mutant(
        "    clash = [c for c in block_ids if c in set(main_ids)]",
        "    clash = []",
    )
    main = _doc("MC-001", "MC-221")
    blocks = [MOD.Block("MC-221", _case("MC-221").rstrip("\n"))]
    result = MOD.build_document(main, blocks)
    assert [p for p in mutant.check_document(main, blocks, result) if "已在 main 里" in p] == []
    assert any("已在 main 里" in p and "让号" in p
               for p in MOD.check_document(main, blocks, result))


# ═══════════════════════════════════════════════════════════════════════════
# 判据 5：生成物刷新失败 ⇒ 逐字节回滚
# ═══════════════════════════════════════════════════════════════════════════


def test_generation_leg_is_really_invoked(tmp_path: Path) -> None:
    """正控：生成腿**真被调用**（否则「回滚」判据是空跑）。"""
    repo = _build_conflict(tmp_path, ours=_case("MC-221"), theirs=_case("PK-100"))
    marker = tmp_path / "generator.marker"
    generator = tmp_path / "generator_ok.py"
    generator.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('ok', encoding='utf-8')\n"
        "sys.exit(0)\n", encoding="utf-8")
    proc = _run(repo, "--generator", str(generator))
    assert proc.returncode == MOD.RC_OK, proc.stdout
    assert marker.read_text(encoding="utf-8") == "ok"
    assert "MC-221" in _cases_path(repo).read_text(encoding="utf-8")


def test_generation_failure_rolls_the_file_back_byte_identical(tmp_path: Path) -> None:
    repo = _build_conflict(tmp_path, ours=_case("MC-221"), theirs=_case("PK-100"))
    before = _cases_path(repo).read_bytes()
    generator = tmp_path / "generator_fail.py"
    generator.write_text("import sys\nprint('boom: 渲染器坏了')\nsys.exit(3)\n", encoding="utf-8")

    proc = _run(repo, "--generator", str(generator))
    assert proc.returncode == MOD.RC_PROBLEM, proc.stdout
    assert "回滚" in proc.stdout
    assert _cases_path(repo).read_bytes() == before, "回滚不是逐字节还原"
    assert _git(repo, "diff", "--name-only", "--diff-filter=U", "--", ".github/cases/*.yml"
                ).stdout.strip() == str(CASES_REL), "回滚后该文件应仍是未解决状态"


# ═══════════════════════════════════════════════════════════════════════════
# 判据 6：端到端（真 merge）
# ═══════════════════════════════════════════════════════════════════════════


def test_end_to_end_real_merge_conflict_is_resolved_semantically(tmp_path: Path) -> None:
    repo = _build_conflict(tmp_path, ours=_case("MC-221"),
                           theirs=_case("PK-100") + _case("SP-050"))
    path = _cases_path(repo)
    before = path.read_bytes()
    assert b"<<<<<<<" in before, "夹具无效：工作树里没有冲突标记"

    checked = _run(repo, "--check")
    assert checked.returncode == MOD.RC_OK, checked.stdout
    assert path.read_bytes() == before, "--check 必须只读"

    applied = _run(repo, "--no-generate")
    assert applied.returncode == MOD.RC_OK, applied.stdout

    text = path.read_text(encoding="utf-8")
    for marker in ("<<<<<<<", "=======", ">>>>>>>"):
        assert marker not in text, f"冲突标记 {marker} 没清干净"
    assert MOD.ids_in_order(text) == [f"MC-{i:03d}" for i in range(1, 6)] + [
        "PK-100", "SP-050", "MC-221"]
    assert len(yaml.safe_load(text)["cases"]) == 8

    main_text = _git(repo, "show", "origin/main:.github/cases/misc.yml").stdout
    assert set(MOD.ids_in_order(main_text)) <= set(MOD.ids_in_order(text))
    assert _git(repo, "diff", "--name-only", "--diff-filter=U", "--", ".github/cases/*.yml"
                ).stdout.strip() == str(CASES_REL), "工具**不动索引**（该由人 git add）"


def test_no_conflict_is_a_definite_zero(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    proc = _run(repo, "--check")
    assert proc.returncode == MOD.RC_OK, proc.stdout
    assert "没有未解决的" in proc.stdout
