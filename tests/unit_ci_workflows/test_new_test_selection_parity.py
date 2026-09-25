# case_ids: MC-012
r"""新增测试文件**选取口径**的两侧一致性守卫（issue #5477）。

## 缺陷（#5474 / PR #5476 交付方主动登记 + 本单取证，非推断）

**同一批判据、两侧输入集不同** —— 同一批改动在 CI 与本地得到**不同的判据集合**：

| 侧 | 改动前的实现 | 匹配对象 |
|---|---|---|
| CI（`pr-check.yml` 的 `Check weak asserts in new tests`） | `git diff --diff-filter=A --name-only origin/main...HEAD \| grep -E '\\.(py\|java\|ts\|tsx)$' \| grep -iE 'test\|spec'` | **全路径** |
| 本地（`verify-all.sh gate`） | `growth_gate.py --check-weak --new-tests-only` ⇒ `_is_test_file` | **只看文件名** |

实测差集（口径可复算，见本文件 `test_two_sides_select_the_same_files` 的 docstring）：
已跟踪文件 **3118** → CI 选中 **1250** / 本地选中 **1165** ⇒ **85 个文件只在 CI 侧**（本地侧独有 **0** 个）。
最小反例：`backend/ai-agent-service/tests/contract_snapshot_registry.py`（全路径含 `tests`、文件名不含
test/spec）⇒ 旧 CI **选中**、旧本地**漏掉** —— 这正是「本地绿 / CI 红」的形态，且差异来源在两侧都看不出来。

## 本守卫锁什么（零 LLM、零网络、不跑真实 LLM 评测）

1. **单一定义**：选取集只有 `growth_gate.select_weak_scan_files` 一份实现，且两侧的**内联副本**
   （`grep -iE 'test|spec'`）必须消失（剥注释后再判，避免「注释里提到」被当实现）。
2. **两侧一致（真跑两个入口）**：同一批探针文件 —— CI 侧走真 CLI（`--select-weak-files --base`）、
   本地侧走真 `./verify-all.sh gate` 的**同一份清单** ⇒ 两个集合必须**逐字相等**；
   且探针的预期归属（全路径型 ⇒ 两侧都选中；源文件 ⇒ 两侧都不选）必须成立。
3. **反向不丢**（防归一化把该选的漏掉）：两棵测试树里 `_is_test_file` 选中的文件必须全部落在
   选取集内（真 CLI 普查 + 计数非空）。
4. **红证非空（两条变异，实跑）**：① 摘掉本地侧的共享选取 ⇒ 本地把源文件也交给扫描器、两侧不等；
   ② 把选取口径**收窄**成「只看文件名」⇒ 路径型探针掉出集合、判据 2 的期望归属当场红。

⚠️ 本文件自身会被 CI 的 `--check-weak` 扫描（新增测试文件），故正文不得出现字面弱断言模式；
探针正文一律**不含**弱断言（红/绿必须只由「选没选中」决定，与其他判据解耦）。
"""
import os
import re
import subprocess
import sys
from pathlib import Path

from unit_ci_workflows.test_growth_gate_fail_closed import (
    _GIT_ENV,
    _git,
    _make_repo,
    _run_gate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"
PR_CHECK = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
VERIFY_ALL = REPO_ROOT / "verify-all.sh"

# 「同一份清单」的行形态（`print_weak_scan_manifest`，两侧共用同一打印函数）
SELECTED_RE = re.compile(r"^\s*✔ 选中: (\S+)$", re.M)
SCANNED_RE = re.compile(r"^📄 (\S+): \d+ 处弱断言$", re.M)

# 探针（提交进临时仓库 ⇒ CI 侧的 `--diff-filter=A` 能看到它们）
#   · 路径型：**只在全路径层面像测试** —— issue #5477 的最小反例形态（改前本地侧会漏掉）；
#   · conftest：文件名像测试而 `_is_test_file` 排除（CI 现口径收它 —— 本单不缩小 CI 的射程）；
#   · 源文件：两层都不像（两侧都不得扫 —— #4077 的不变量）。
_PROBES = (
    "tests/probe_registry.py",
    "backend/ai-agent-service/tests/probe_registry.py",
    "tests/unit_ci_workflows/test_probe_case.py",
    "tests/conftest.py",
    "backend/ai-agent-service/app/services/greeting.py",
)
_NOT_SELECTED = ("backend/ai-agent-service/app/services/greeting.py",)

# 变异点：选取实现的**唯一一行判据**（改实现就得同步本守卫 —— 命中数 0 会大声报红）
_SELECTION_BODY = 'if f.endswith(TEST_FILE_EXTS) and re.search(r"(test|spec)", f, re.I)]'


def _load_gate():
    """加载被测模块（零依赖文件加载；供「单一定义」「两口径判别性」判定用）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("growth_gate_parity_under_test", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_strip_comment():
    """**共享**剥注释实现（`.github/danger_scan.py::strip_comment`，issue #5268）。

    「剥注释」也是判据的一部分：本文件**不自己写** `#` 截断 —— 朴素截断在字符串内的 `#`
    会吃掉行尾（属假绿形态），`tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py`
    的 RULE_HASH 对此有常驻判据、台账**只许缩短**。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "danger_scan_shared_under_test", REPO_ROOT / ".github" / "danger_scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.strip_comment


def _write_probe(repo, rel):
    """写探针文件（**不含**弱断言；测试型文件带上 case_ids 让 G5 不插一脚）。"""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if rel.endswith("conftest.py"):
        path.write_text("import pytest\n", encoding="utf-8")
    else:
        path.write_text("# case_ids: MC-012\ndef probe():\n    assert 1 + 1 == 2\n",
                        encoding="utf-8")
    return rel


def _cli_select(paths, cwd=REPO_ROOT):
    """真 CLI（= `pr-check.yml` 现在调的那一条）：`--select-weak-files --files …`。

    返回 (stdout 的选中集, stderr 清单里的选中集)。两者必须一致 —— 打印给日志的
    「同一份清单」与交给扫描器的那一份不得是两套。
    """
    r = subprocess.run(
        [sys.executable, str(GATE_PY), "--select-weak-files", "--files", *paths],
        cwd=str(cwd), capture_output=True, text=True,
        env={**os.environ, **_GIT_ENV}, timeout=180,
    )
    assert r.returncode == 0, f"--select-weak-files 必须成功（fail-closed）：\n{r.stderr}"
    return set(r.stdout.split()), set(SELECTED_RE.findall(r.stderr))


def _ci_selection(repo):
    """CI 侧的真入口：在临时仓库里按 `--base origin/main` 取**新增文件**再选（diff-filter=A）。"""
    r = subprocess.run(
        [sys.executable, str(repo / ".github" / "growth_gate.py"),
         "--select-weak-files", "--base", "origin/main"],
        cwd=str(repo), capture_output=True, text=True,
        env={**os.environ, **_GIT_ENV}, timeout=120,
    )
    assert r.returncode == 0, f"CI 侧选取 CLI 必须成功（fail-closed）：\n{r.stderr}"
    return set(r.stdout.split())


def _probe_repo(tmp_path):
    """最小仓库 + 探针已提交（`_make_repo` 复用 fail_closed 的既有 harness）。"""
    repo = _make_repo(tmp_path)
    for rel in _PROBES:
        _write_probe(repo, rel)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "probe: 两侧选取口径")
    return repo


# ── 判据 1：选取集只有一份实现，两侧的内联副本必须消失 ──────────────────────────

def test_selection_is_a_single_implementation():
    """「哪些新增文件算测试文件」只许有**一份**实现（复制一份必然漂移 —— #5477 的病根）。"""
    gate_text = GATE_PY.read_text(encoding="utf-8")
    assert len(re.findall(r"^def select_weak_scan_files\(", gate_text, re.M)) == 1, (
        "select_weak_scan_files 必须恰好定义一次")
    strip = _load_strip_comment()   # 共享剥注释实现（本文件不自己写 `#` 截断）
    for path in (PR_CHECK, VERIFY_ALL):
        # 剥注释后再判：注释里**提到**旧 grep 不算实现（「说明 vs 实现」同族陷阱）
        code = "\n".join(strip(ln) for ln in path.read_text(encoding="utf-8").splitlines())
        assert not re.search(r"grep[^\n]*test\|spec", code), (
            f"{path.name} 里仍有「哪些文件算测试文件」的内联副本 —— "
            "改判定口径请改 `select_weak_scan_files`，勿在别处再写一套")
    ci_text = PR_CHECK.read_text(encoding="utf-8")
    assert "--select-weak-files" in ci_text and "--check-weak" in ci_text, (
        "CI 的弱断言步骤必须经共享选取集取集合、再交给同一扫描器")
    assert "--check-weak --new-tests-only" in VERIFY_ALL.read_text(encoding="utf-8"), (
        "本地脚本必须把共享选取集施加下去（`--new-tests-only`）")


# ── 判据 2：两侧选取集逐字相等（真跑两个入口）─────────────────────────────────

def test_two_sides_select_the_same_files(tmp_path):
    """两侧必须选中**同一批**文件 —— 改前读数（复算命令见下）两侧差 **85** 个文件。

    复算（口径，一条命令；`<ref>` = 任一提交）：
      `git ls-tree -r --name-only <ref> > /tmp/all.txt`
      旧 CI 侧：`grep -E '\\.(py|java|ts|tsx)$' /tmp/all.txt | grep -iE 'test|spec'`
      旧本地侧：按 `_is_test_file` 过滤同一份清单（`python3 -c` 调 origin/main 的实现）
    ⇒ `3118` 个已跟踪文件里：CI 选中 `1250` / 本地选中 `1165` / **只在 CI 侧 85** / 只在本地侧 0。
    """
    repo = _probe_repo(tmp_path)
    ci = _ci_selection(repo)
    rc, out, log = _run_gate(repo)
    assert SELECTED_RE.search(log), (
        f"本地侧必须打印选取清单（否则「两侧同一份清单」无从对比）：\n{out}\n{log}")
    local = set(SELECTED_RE.findall(log))
    assert ci == local, (
        f"两侧选取集必须逐字相等（issue #5477）：\n只在 CI 侧 {sorted(ci - local)}\n"
        f"只在本地侧 {sorted(local - ci)}\n本地日志：\n{log}")
    expected = {p for p in _PROBES if p not in _NOT_SELECTED}
    assert ci == expected, (
        f"选取口径 = CI 现射程（**本单不得缩小它**）：期望 {sorted(expected)}，实得 {sorted(ci)}")
    # 最小反例形态：**只在全路径层面像测试**的探针必须两侧都选中（改前本地侧漏掉它）
    assert "tests/probe_registry.py" in ci and "tests/probe_registry.py" in local, (
        "路径型探针必须两侧都选中（改前本地侧漏掉 —— 就是本单要修的那一格）")
    # 源文件两侧都不选（#4077 的反向不变量：过滤只许缩小扫描集，不许把源文件当测试文件扫）
    for src in _NOT_SELECTED:
        assert src not in local, f"源文件不得进入本地扫描集：{src}"


def test_probe_is_discriminating_between_the_two_scopes():
    """探针的**判别性自证**：它在「只看文件名」口径下不被选中、在全路径口径下被选中。

    没有这条，判据 2 可能只是「两边都空/都全」的恒真断言（本仓 G7：红证前提自证）。
    """
    gate = _load_gate()
    probe = "tests/probe_registry.py"
    assert gate._is_test_file(probe) is False, "该探针在文件名口径下**必须**不被选中（判别性前提）"
    assert probe in gate.select_weak_scan_files([probe]), "该探针在全路径口径下必须被选中"


# ── 判据 3：反向 —— 两棵测试树里该选的必须还在（防归一化漏掉）────────────────

def test_case_files_in_both_test_trees_stay_selected():
    """`_is_test_file`（文件名口径）选中的文件 ⊆ 选取集（全路径口径）—— 真 CLI 普查。

    这是「归一化不许把该选的漏掉」的机械形态：路径口径是**超集**，任何收窄都会在这里红。
    """
    gate = _load_gate()
    for tree in ("tests/", "backend/ai-agent-service/tests/"):
        tracked = _git(REPO_ROOT, "ls-files", tree).stdout.split()
        named = [f for f in tracked if gate._is_test_file(f)]
        assert named, f"{tree} 里没有「文件名像测试」的文件 —— 普查空跑，判据不成立"
        selected, manifest = _cli_select(tracked, cwd=REPO_ROOT)
        assert selected == manifest, (
            "日志清单（stderr）与交给扫描器的那一份（stdout）必须是同一份")
        missed = [f for f in named if f not in selected]
        assert not missed, f"{tree} 有该选未选的文件（归一化漏掉了该选的）：{missed[:5]}"
        print(f"[#5477] {tree}: 已跟踪 {len(tracked)}｜文件名像测试 {len(named)}｜漏掉 {len(missed)}")


# ── 判据 4：两条变异红证（实跑，证明上面两条断言非空）─────────────────────────

def test_mutation_without_shared_selection_breaks_parity(tmp_path):
    """变异①：摘掉本地侧的共享选取（= 改前「本地自己一套」的形态）⇒ 两侧结论立刻不同。

    `--new-tests-only` 摘掉后，本地把**源文件**也交给扫描器（`scanned` 里出现 src，
    而 CI 侧不含它）—— 与 #4077 的假红现场同形。
    """
    repo = _probe_repo(tmp_path)
    script = repo / "verify-all.sh"
    text = script.read_text(encoding="utf-8")
    mutated, hits = re.subn(r"--check-weak --new-tests-only ", "--check-weak ", text)
    assert hits == 1, (
        f"变异点丢失（命中 {hits} 处）：本地脚本没在弱断言扫描上施加共享选取集？")
    script.write_text(mutated, encoding="utf-8")
    ci = _ci_selection(repo)
    rc, out, log = _run_gate(repo)
    scanned = set(SCANNED_RE.findall(log))
    src = _NOT_SELECTED[0]
    assert src in scanned, (
        f"摘掉共享选取后本地必须把源文件也交给扫描器（否则这条红证是空断言）：\n{out}\n{log}")
    assert src not in ci, "CI 侧本就不扫源文件 —— 两侧结论因此不同（= 本单要消除的形态）"
    assert scanned - ci, "两侧结论必须出现差异（变异生效）"


def test_mutation_narrowing_to_filename_breaks_expected_scope(tmp_path):
    """变异②：把选取口径**收窄**成「只看文件名」（= 改前本地那侧）⇒ 路径型探针掉出集合。

    这条锁的是**方向**：本单的归一化取「不缩小任何一侧」的那一侧（CI 现射程）。
    谁把口径收窄回只看文件名，判据 2 的期望归属断言立刻红。
    """
    repo = _probe_repo(tmp_path)
    gate_copy = repo / ".github" / "growth_gate.py"
    text = gate_copy.read_text(encoding="utf-8")
    mutated, hits = re.subn(re.escape(_SELECTION_BODY), "if _is_test_file(f)]", text)
    assert hits == 1, (
        f"变异点丢失（命中 {hits} 处）：选取实现变了，请同步本守卫（{_SELECTION_BODY!r}）")
    gate_copy.write_text(mutated, encoding="utf-8")
    ci = _ci_selection(repo)
    expected = {p for p in _PROBES if p not in _NOT_SELECTED}
    lost = expected - ci
    assert lost, (
        "收窄到「只看文件名」必须让全路径型探针掉出选取集（否则判据 2 是空断言）；"
        f"实得 {sorted(ci)}")
    assert "tests/probe_registry.py" in lost, (
        f"最小反例形态必须掉出（改前本地侧漏掉的正是它）：{sorted(lost)}")