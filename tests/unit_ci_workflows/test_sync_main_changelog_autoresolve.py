# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI / 流程结构类 L0 不变式统一挂 MC-012 —— 见
#   `.github/cases/misc.yml` 的 MC-012 登记。本 PR 不新建用例族：塞进行为用例库会污染覆盖矩阵。）
"""`scripts/sync-main.sh` 的「CHANGELOG.md 冲突自动解」（铁律 10 收敛；**fail-closed**）。

## 病：一晚 4 次、逐字相同的动作串（#5884 / #5888 / #5896 / #5907）

`./scripts/sync-main.sh --rebase` 停下 ⇒ 冲突文件**恰好只有** `CHANGELOG.md` ⇒ 保留两侧条目、
去掉 `<<<<<<<` / `=======` / `>>>>>>>` ⇒ 复核「条目一条不丢、无重复」⇒ `git add` ⇒
`rebase --continue` ⇒ 重跑 sync-main。动作串固定且逐字相同 ⇒ 按铁律 10 折叠进**既有命令**
（`sync-main.sh` 的冲突路径），**不是**新加一条命令（那只是把重复挪个地方）。

## 三条判据（各自能单独变红）

| # | 判据 | 变红的形态 |
|---|---|---|
| 1 | 冲突集合**恰好** `{CHANGELOG.md}` ⇒ 自动解：两侧条目都在、无残留标记、非冲突区逐字不变、rebase / merge 真的走完（收尾两步不跳） | 解完丢条目 / 留标记 / 停在半路 |
| 2 | **判别力自证**：把「只保留一侧」注入脚本副本 ⇒ **必须**判红（退回人工路径 + 工作树一个字节没动） | 注入后仍绿 = 空断言 |
| 3 | 冲突集合 **>** `{CHANGELOG.md}` ⇒ **不**自动解（提示与 exit 1 与自动解引入前逐字一致、冲突原样） | 多文件冲突被顺手接管 |

## 关键读数（本机实测；写进 PR body）

* 🔴 **`git rebase --continue` 在非交互环境下必须给 editor**：`GIT_EDITOR` 未设时 git 直接
  `error: Terminal is dumb, but EDITOR unset` + `error: could not commit staged changes`（rc=1）
  ⇒ 自动解里必须 `GIT_EDITOR=true git ${MODE} --continue`，否则每一次都卡在这一步
  （人工在终端里做同一件事不会暴露它 —— 这正是「手工 4 次都没踩到」的原因）。
* 三条验证在**写盘之前**跑完（不过 ⇒ python 非零退出，工作树没被改过）；写盘后**回读自证**。
* 备份 + 还原：任何一步失败都 `cp` 冲突态备份回工作树 ⇒ 人工按老办法接手。

## 边界（照实登记，别把「登记了」读成「治住了」）

* `test_registered_boundary_legit_deletion_outside_conflict_falls_back_to_human` 把**已知假红**
  钉成死亡条件：某侧在冲突区**之外**合法删掉一行 ⇒ 第 C 条判据（两侧原版按原序保留）判红 ⇒
  退回人工路径（**不产错内容**，只是不接管）。将来若把 C 收窄成「只判冲突区」，那条测试会翻红
  ⇒ 必须同步更新本条登记。
* 夹具是**自造仓库**（`git init` + 本地 bare origin），**不读真仓库历史** ⇒ CI 的 `fetch-depth`
  环境下同样可跑。真脚本以**副本**形式进夹具（内容指纹比对，与真脚本逐字节一致）。
* 注入是**内容级**的（`red_proof.content_fingerprint`，禁 mtime/size），且注入后脚本 `bash -n`
  必须通过 —— 否则「非零退出」可能只是语法错误的假象（错归因）。
* 射程外：夹具里没有 `.github/render_cases.py`，脚本按既有分支打印「跳过重渲染」后 `exit 0`；
  本文件只断言第 5 步（合并后内容级校验）**确实跑了**，**不复制**它的判据（同脚本同参数）。
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "sync-main.sh"
RED_PROOF = REPO_ROOT / "scripts" / "red_proof.py"

CHANGELOG = "CHANGELOG.md"
SCRIPT_REL = "scripts/sync-main.sh"
OTHER_REL = "README.md"

#: 冲突标记（判据 1/2/3 的「无残留」口径；含 diff3 的基线标记）
MARKER_RE = re.compile(r"^(<{7}|={7}|>{7}|\|{7})", re.M)

BASE_CHANGELOG = (
    "# Changelog\n"
    "\n"
    "本项目遵循 Keep a Changelog 格式。\n"
    "\n"
    "## [Unreleased]\n"
    "\n"
    "### 旧条目 A（2026-09-28，issue #5700）\n"
    "\n"
    "- 正文 A\n"
    "\n"
    "### 旧条目 B（2026-09-29，issue #5711）\n"
    "\n"
    "- 正文 B\n"
    "\n"
    "## [1.95.0] - 2026-09-27\n"
    "\n"
    "### 已发布条目（2026-09-27，issue #5600）\n"
    "\n"
    "- 正文 R\n"
)

#: main 侧（rebase 下 = 索引 `:2:`）一次加两条 —— 用来钉「各侧原有相对顺序」这条规则。
MAIN_ENTRIES = ("### main 侧新条目一（2026-10-01，issue #6001）",
                "### main 侧新条目二（2026-10-01，issue #6002）")
#: 本分支侧（rebase 下 = 索引 `:3:`）同样加两条。
BRANCH_ENTRIES = ("### 本分支新条目一（2026-10-01，issue #5999）",
                  "### 本分支新条目二（2026-10-01，issue #5998）")
#: 冲突区**之外**的一行（分支侧删掉它、main 侧保留 ⇒ 冲突区外的合法删除）
OUTSIDE_LINE = "- 正文 B"

#: 注入锚点：把「两侧都保留」改成「只保留 `:2:` 侧」⇒ 解完必然丢 `:3:` 侧的全部条目。
DROP_THEIRS_OLD = '    kept = [s for s in (sides["ours"], sides["theirs"]) if s]'
DROP_THEIRS_NEW = '    kept = [s for s in (sides["ours"],) if s]'


def _load_red_proof():
    """按**路径**加载 `scripts/red_proof.py`（不往 `sys.path` 塞东西，与既有契约测试同款）。"""
    spec = importlib.util.spec_from_file_location("red_proof_changelog_autoresolve", RED_PROOF)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


red_proof = _load_red_proof()


# ── 夹具：临时 git 仓库（真 git，不 mock —— 判据本体就是 git 语义）───────────────

def _env() -> dict:
    """剥掉外部 `GIT_*`（防宿主的 `GIT_DIR` / `GIT_WORK_TREE` 把临时仓库指到别处）。"""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, env=_env())


def _out(repo: Path, *args: str) -> str:
    """跑一条 git 命令并返回 strip 后的 stdout（失败即抛，绝不静默当空）。"""
    proc = _git(repo, *args)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败（{proc.returncode}）：{proc.stderr}")
    return proc.stdout.strip()


def _run_sync(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """跑被测脚本（脚本在临时仓库里是**受版本控制的副本**，与真脚本逐字节一致）。"""
    return subprocess.run(["bash", SCRIPT_REL, *args],
                          cwd=str(repo), capture_output=True, text=True, env=_env())


def _entries_block(entries) -> str:
    return "".join(f"{e}\n\n- {e[:24]} 的正文\n\n" for e in entries)


def _with_entries(text: str, entries) -> str:
    """把条目块插在 `## [Unreleased]` 之后（两侧都这么做 ⇒ 同一个位置冲突）。"""
    anchor = "## [Unreleased]\n\n"
    assert anchor in text, "夹具锚点没命中（CHANGELOG 样本已变）⇒ 夹具造不出冲突"
    return text.replace(anchor, anchor + _entries_block(entries), 1)


def _build_repo(tmp_path: Path, *, script_text: str | None = None,
                extra_conflict_file: bool = False, drop_outside_line: bool = False,
                name: str = "repo") -> Path:
    """造分叉：`main`（origin）与 `feature` **都在 `## [Unreleased]` 顶部加条目**。

    * `extra_conflict_file=True` ⇒ 另一个文件也冲突（判据 3：射程不许扩大）。
    * `drop_outside_line=True` ⇒ 本分支删掉冲突区**之外**的一行（已知假红的死亡条件）。
    """
    work = tmp_path / name
    (work / "scripts").mkdir(parents=True)
    (work / SCRIPT_REL).write_text(
        _real_script() if script_text is None else script_text, encoding="utf-8")
    (work / CHANGELOG).write_text(BASE_CHANGELOG, encoding="utf-8")
    if extra_conflict_file:
        (work / OTHER_REL).write_text("base line\n", encoding="utf-8")

    _git(work, "init", "-q", ".")
    _git(work, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(work, "config", "user.email", "sync-main-changelog@example.invalid")
    _git(work, "config", "user.name", "sync-main changelog guard")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "base")
    origin = tmp_path / f"{name}.origin.git"
    _git(work, "init", "-q", "--bare", str(origin))
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "main")

    _git(work, "checkout", "-qb", "feature")
    ours = _with_entries(BASE_CHANGELOG, BRANCH_ENTRIES)
    if drop_outside_line:
        ours = ours.replace(OUTSIDE_LINE + "\n\n", "", 1)
    (work / CHANGELOG).write_text(ours, encoding="utf-8")
    if extra_conflict_file:
        (work / OTHER_REL).write_text("branch line\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "feat: 本分支条目")

    _git(work, "checkout", "-q", "main")
    (work / CHANGELOG).write_text(_with_entries(BASE_CHANGELOG, MAIN_ENTRIES), encoding="utf-8")
    if extra_conflict_file:
        (work / OTHER_REL).write_text("main line\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "feat: main 条目")
    _git(work, "push", "-q", "origin", "main")

    _git(work, "checkout", "-q", "feature")
    return work


def _real_script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _heads(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith("### ")]


def _unmerged(repo: Path) -> set[str]:
    return set(_out(repo, "diff", "--name-only", "--diff-filter=U").split())


def _rebase_in_progress(repo: Path) -> bool:
    """rebase 是否**仍停在原处**（判据 2/3 的「没替人做决定」口径）。

    ⚠️ rebase 进行中 HEAD 是**分离**在 onto（origin/main）上的 ⇒ 不能用 `git log -1` 判进展，
    要看分支 ref 有没有被推进（`.git/rebase-merge` 目录在不在）。
    """
    path = Path(_out(repo, "rev-parse", "--git-path", "rebase-merge"))
    return (path if path.is_absolute() else repo / path).is_dir()


# ── 反空跑锚点：夹具必须真的造出「恰好 CHANGELOG.md 冲突」这一形态 ─────────────

def test_fixture_really_produces_a_changelog_only_conflict(tmp_path):
    """夹具没造出冲突 / 冲突不止一个文件 / 副本≠真脚本 ⇒ 红（不得静默跳过）。"""
    work = _build_repo(tmp_path)
    assert (work / CHANGELOG).is_file() and (work / SCRIPT_REL).is_file()
    # 临时仓库里的脚本 == 仓库真脚本（**内容指纹**，不看 mtime/size，issue #4260）
    assert (red_proof.content_fingerprint(work / SCRIPT_REL)
            == red_proof.content_fingerprint(SCRIPT))
    base = _out(work, "merge-base", "HEAD", "origin/main")
    assert _out(work, "diff", "--name-only", base, "HEAD") == CHANGELOG
    assert _out(work, "diff", "--name-only", base, "origin/main") == CHANGELOG
    # 手工 rebase 一次：冲突确实发生、且**只有** CHANGELOG.md（否则判据 1 是空跑）
    rebase = _git(work, "rebase", "origin/main")
    assert rebase.returncode != 0, f"夹具没造出冲突：{rebase.stdout}{rebase.stderr}"
    assert _unmerged(work) == {CHANGELOG}, _unmerged(work)
    conflict_text = (work / CHANGELOG).read_text(encoding="utf-8")
    assert MARKER_RE.search(conflict_text), "冲突态文件里没有标记 ⇒ 夹具形态不对"
    # 两侧各自的原版（索引第 2 / 第 3 侧）都真的带上了自己那两条
    for stage in (2, 3):
        entries = MAIN_ENTRIES if stage == 2 else BRANCH_ENTRIES
        blob = _out(work, "show", f":{stage}:{CHANGELOG}")
        assert all(e in blob for e in entries), f"索引第 {stage} 侧缺自己的条目"


# ── 判据 1：恰好 {CHANGELOG.md} ⇒ 自动解（rebase 与 merge 两条路各跑一遍）──────

@pytest.mark.parametrize("mode", ["--rebase", "merge"])
def test_changelog_only_conflict_is_auto_resolved(tmp_path, mode):
    """两侧各有条目 ⇒ 解完**并集完整**、无残留标记、非冲突区逐字不变、走完收尾两步。"""
    work = _build_repo(tmp_path, name=f"repo-{mode.strip('-')}")
    args = (mode,) if mode == "--rebase" else ()
    result = _run_sync(work, *args)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "自动解" in out, f"没有走自动解路径（判据失去对象）：{out}"

    text = (work / CHANGELOG).read_text(encoding="utf-8")
    # ① 无残留标记
    assert not MARKER_RE.search(text), f"解完仍有冲突标记：{text[:400]}"
    # ② 并集完整（一条不丢）+ 各侧原有相对顺序
    for entry in MAIN_ENTRIES + BRANCH_ENTRIES:
        assert entry in text, f"解完丢了条目：{entry}"
    for a, b in ((MAIN_ENTRIES[0], MAIN_ENTRIES[1]), (BRANCH_ENTRIES[0], BRANCH_ENTRIES[1])):
        assert text.index(a) < text.index(b), "同一侧的两条相对顺序被打乱"
    assert set(_heads(text)) == set(_heads(BASE_CHANGELOG)) | set(MAIN_ENTRIES + BRANCH_ENTRIES)
    # ③ 非冲突区逐字不变（冲突区之外）与块之间空行分隔
    assert "## [1.95.0] - 2026-09-27\n\n### 已发布条目（2026-09-27，issue #5600）\n\n- 正文 R\n" in text
    assert "### 旧条目 A（2026-09-28，issue #5700）\n\n- 正文 A\n\n### 旧条目 B" in text
    assert re.search(r"[^\n]\n### ", text) is None, "两个块之间没有空行分隔"
    # ④ 收尾两步**没有被跳过**（第 5 步内容级校验真的跑了）
    assert "合并后内容级校验通过" in out, f"第 5 步被跳过（收尾不许跳）：{out}"
    # ⑤ rebase / merge 真的走完了：工作树干净、提交在
    assert _out(work, "status", "--porcelain") == ""
    subject = _out(work, "log", "-1", "--format=%s")
    if mode == "--rebase":
        assert subject == "feat: 本分支条目", f"rebase 没走完（停在半路）：{subject}"
    else:
        assert subject.startswith("Merge"), f"merge 没走完（没有 merge 提交）：{subject}"
        assert len(_out(work, "log", "-1", "--format=%P").split()) == 2


# ── 判据 2：判别力自证（注入「只保留一侧」⇒ 必须判红）─────────────────────────

def test_injected_drop_of_one_side_is_detected(tmp_path):
    """把 union 改成「只留 `:2:` 侧」⇒ 同一夹具下**必须**退回人工路径，且工作树没被动过。

    没有这一条，判据 1 可能是「不管解成什么样都绿」的空断言。
    """
    src = _real_script()
    assert DROP_THEIRS_OLD in src, "注入锚点没命中（解法行已变）⇒ 红证不成立"
    injected = src.replace(DROP_THEIRS_OLD, DROP_THEIRS_NEW)
    assert injected != src, "注入未生效（自证失败 ⇒ 本判据的红证是空断言）"

    work = _build_repo(tmp_path, script_text=injected)
    result = _run_sync(work, "--rebase")
    out = result.stdout + result.stderr
    assert result.returncode != 0, f"解完丢了「索引 :3:」侧条目却仍然绿 ⇒ 判据 1 是空断言：{out}"
    assert "未通过" in out and "丢了" in out, f"判红必须指名「丢了条目」这个原因：{out}"
    assert "❌ rebase 冲突，请解决后重跑本脚本" in out, "人工路径的原话必须还在"
    # 冲突态**原样**：文件still带标记、rebase 仍停在原处（没有替人做决定）
    text = (work / CHANGELOG).read_text(encoding="utf-8")
    assert MARKER_RE.search(text), "验证不过却把文件改了（必须逐字节还原成冲突态）"
    assert _unmerged(work) == {CHANGELOG}
    assert _rebase_in_progress(work), "验证不过却把 rebase 推走了（必须停在原处交人工）"
    assert _out(work, "log", "-1", "--format=%s", "feature") == "feat: 本分支条目"


def test_injection_is_content_level_and_syntactically_valid(tmp_path):
    """红证卫生：注入是**内容级**的（指纹变化）且注入后的脚本 `bash -n` 通过。"""
    orig = _real_script()
    baseline_fp = red_proof.content_fingerprint(SCRIPT)
    injected = orig.replace(DROP_THEIRS_OLD, DROP_THEIRS_NEW)
    path = tmp_path / "sync-main-injected.sh"
    path.write_text(injected, encoding="utf-8")
    red_proof.assert_injection_effective(baseline_fp, red_proof.content_fingerprint(path), True,
                                         label="只保留一侧")
    syntax = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, env=_env())
    assert syntax.returncode == 0, syntax.stderr
    assert red_proof.content_fingerprint(SCRIPT) == baseline_fp, "注入只许发生在副本上"
    assert _real_script() == orig


# ── 判据 3：冲突集合 > {CHANGELOG.md} ⇒ 不自动解（射程不许扩大）───────────────

def test_extra_conflicted_file_is_not_auto_resolved(tmp_path):
    """另一个文件也冲突 ⇒ 与自动解引入前**逐字一致**：提示 + exit 1 + 冲突原样。"""
    work = _build_repo(tmp_path, extra_conflict_file=True)
    result = _run_sync(work, "--rebase")
    out = result.stdout + result.stderr
    assert result.returncode == 1, out
    assert "❌ rebase 冲突，请解决后重跑本脚本" in out, "既有提示必须逐字保留"
    assert "不自动解" in out, "不接管时也要说清（fail-closed 必须可见，不能静默）"
    assert _unmerged(work) == {CHANGELOG, OTHER_REL}, _unmerged(work)
    text = (work / CHANGELOG).read_text(encoding="utf-8")
    assert MARKER_RE.search(text), "多文件冲突时不许顺手改 CHANGELOG.md（一个字节都不许动）"
    assert _rebase_in_progress(work), "不接管时必须停在原处（不许替人推进 rebase）"
    assert _out(work, "log", "-1", "--format=%s", "feature") == "feat: 本分支条目"


# ── 已登记的边界（死亡条件）：冲突区**之外**的合法删除会退回人工路径 ──────────

def test_registered_boundary_legit_deletion_outside_conflict_falls_back_to_human(tmp_path):
    """某侧在冲突区外**合法删掉**一行 ⇒ 第 C 条判据判红 ⇒ 不接管（**假红**，但绝不产错内容）。

    这是**如实登记的边界**，不是「通过」：收回它的唯一方式是让 C 只判冲突区，
    而那会放开「冲突区之外被换掉」这一形态 ⇒ 那时本测试会翻红，逼登记同步更新。
    """
    work = _build_repo(tmp_path, drop_outside_line=True)
    result = _run_sync(work, "--rebase")
    out = result.stdout + result.stderr
    assert result.returncode == 1, out
    assert "未通过" in out and "对不上" in out, f"必须指名是 C 条判据判红：{out}"
    assert "❌ rebase 冲突，请解决后重跑本脚本" in out
    assert MARKER_RE.search((work / CHANGELOG).read_text(encoding="utf-8")), "必须还原成冲突态"


# ── 注释漂移锁：改了行为必须同改脚本文件头的「行为」节 ─────────────────────────

def test_script_header_documents_the_autoresolve():
    """文件头缺「自动解 / 验证 / 还原」这三件事 ⇒ 红（行为改了、注释没改 = 假绿来源）。"""
    header = _real_script().split("set -euo pipefail", 1)[0]
    for token in ("CHANGELOG.md 冲突", "自动解", "内容级验证", "还原"):
        assert token in header, f"脚本文件头「行为」节缺 {token}"
    # 既有两条防护的注释漂移锁（同族，别被本次改动挤掉）
    for token in ("前置拒绝", "合并后内容级校验", "--rebase", "静默回退"):
        assert token in header, f"脚本文件头丢了既有登记 {token}"
