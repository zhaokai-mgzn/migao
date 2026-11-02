# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI / 流程结构类 L0 不变式统一挂 MC-012 —— 见
#   `.github/cases/misc.yml` 的 MC-012 登记。本 PR 不新建用例族：塞进行为用例库会污染覆盖矩阵。）
"""`scripts/sync-main.sh` 的「CHANGELOG.md 冲突自动解」（铁律 10 收敛；**fail-closed**）。

## 病：一晚 4 次、逐字相同的动作串（#5884 / #5888 / #5896 / #5907）

`./scripts/sync-main.sh --rebase` 停下 ⇒ 冲突文件**恰好只有** `CHANGELOG.md` ⇒ 保留两侧条目、
去掉 `<<<<<<<` / `=======` / `>>>>>>>` ⇒ 复核「条目一条不丢、无重复」⇒ `git add` ⇒
`rebase --continue` ⇒ 重跑 sync-main。动作串固定且逐字相同 ⇒ 按铁律 10 折叠进**既有命令**
（`sync-main.sh` 的冲突路径），**不是**新加一条命令（那只是把重复挪个地方）。

## 判据（各自能单独变红）

| # | 判据 | 变红的形态 |
|---|---|---|
| 1 | 冲突集合**恰好** `{CHANGELOG.md}` ⇒ 自动解：两侧条目都在、无残留标记、非冲突区逐字不变、rebase / merge 真的走完（收尾两步不跳） | 解完丢条目 / 留标记 / 停在半路 |
| 2 | **判别力自证**：把「只保留一侧」注入脚本副本 ⇒ **必须**判红（退回人工路径 + 工作树一个字节没动） | 注入后仍绿 = 空断言 |
| 3 | 冲突集合 **>** `{CHANGELOG.md}` ⇒ **不**自动解（提示与 exit 1 与自动解引入前逐字一致、冲突原样） | 多文件冲突被顺手接管 |
| 4 | **另一侧在冲突块之外合法改写 / 删除**（issue #7861 的复现语料）⇒ 仍自动解，rebase 与 merge 两条路都走完 | 判据射程退回「整文件」⇒ 假红 |
| 5 | **冲突里一侧删了别人的小节** ⇒ 解后**不许**静默丢（另一侧还在的那条必须还在）；注入「只保留删除方」⇒ 必须判红 | 静默丢内容 / 丢内容仍绿 |
| 6 | **红证：判据射程改回整文件**（`check_scope` 返回 `[(ours, theirs, 0, len(out))]`）⇒ 判据 4 的语料**必红** | 旧形态在这份语料上仍是绿 ⇒ 判据 4 与 #7861 无关 |

## issue #7861：判据射程从「整文件」收窄到「冲突块」（判据 4/5/6 的来历）

**病**：旧判据 B/C 拿 `git show :2:` / `:3:` 的**全文**当参照面 —— 只要另一侧在**冲突块之外**改写或
删掉过任何一行（真实仓库里几乎每次都有：main 一直在往前改 CHANGELOG），本侧那份旧文本就会消失 ⇒ 报
「索引第 :2: 侧原版的这一行在解后文本里对不上（丢了或次序被打乱）」/「丢了 N 条 `### ` 条目」⇒
**每次都假红**，而人工解**同一份**冲突一次就过（#7861 实测 4/4）。自动解**只接管冲突块** ⇒
判据的射程也只能是冲突块（块内判据一条没放松，见脚本文件头的 A/B/C）。

**本机实测对照**（真 CHANGELOG 语料 + 真 `git rebase origin/main` 造冲突，同一份语料跑两版判据）：

| 语料 | 修前（判据整文件） | 修后（判据只判冲突块） |
|---|---|---|
| 两侧只在 `## [Unreleased]` 顶部加条目 | ✅ 自动解 | ✅ 自动解 |
| 另一侧在**别处**改一行正文 | ⛔ 「:3: 侧原版的这一行…对不上」 | ✅ 自动解 |
| 另一侧在**别处**改一条 `### ` 标题 | ⛔ 「丢了 1 条 `### ` 条目」+ 上一条 | ✅ 自动解 |
| 另一侧在**别处**删一条小节 | ⛔ 同上 | ✅ 自动解 |
| 分支落后 40 个 CHANGELOG 提交 | ⛔ 同上 | ✅ 自动解 |

## 关键读数（本机实测；写进 PR body）

* 🔴 **`git rebase --continue` 在非交互环境下必须给 editor**：`GIT_EDITOR` 未设时 git 直接
  `error: Terminal is dumb, but EDITOR unset` + `error: could not commit staged changes`（rc=1）
  ⇒ 自动解里必须 `GIT_EDITOR=true git ${MODE} --continue`，否则每一次都卡在这一步
  （人工在终端里做同一件事不会暴露它 —— 这正是「手工 4 次都没踩到」的原因）。
* 三条验证在**写盘之前**跑完（不过 ⇒ python 非零退出，工作树没被改过）；写盘后**回读自证**。
* 备份 + 还原：任何一步失败都 `cp` 冲突态备份回工作树 ⇒ 人工按老办法接手。

## 边界（照实登记，别把「登记了」读成「治住了」）

* `test_one_side_rewriting_outside_the_conflict_block_is_auto_resolved` 与
  `test_one_side_deleting_a_line_outside_the_conflict_block_is_auto_resolved` 钉**判据的射程**：
  冲突块**之外**被另一侧合法改写 / 删除 ⇒ **不影响**自动解（issue #7861）。旧版这里登记的是
  「某侧在冲突区之外合法删一行 ⇒ C 判红（**已知假红**，退回人工）」—— 那条死亡条件已被 #7861
  兑现，判据改判冲突块；**块内**的严格度没变（判据 1/2/5 都还在）。
* 射程**只剩冲突块** ⇒ 「块外被换掉」不再由本判据兜（旧版也只是假红，并不是拦住了什么）：
  块外内容由脚本的解法保证（解 = 冲突态逐行原样，只替换块），并在 C 条判据里**逐字比对**
  （`out` 去掉各块区间 == 冲突态去掉冲突块）—— 那一条才是「块外没被改」的真判据。
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
#: 冲突区**之外**的一行（分支侧删掉它、main 侧保留 ⇒ 冲突区外的合法删除；issue #7861 的假红形态）
OUTSIDE_LINE = "- 正文 B"
#: main 侧在冲突区**之外**合法改写的两处（一条正文 + 一条 `### ` 标题）—— issue #7861 的复现语料：
#: 旧判据 C 在正文那行假红、旧判据 B 在标题那行假红（实测两种报错都出现过）。
OUTSIDE_BODY = "- 正文 R"
OUTSIDE_HEADING = "### 已发布条目（2026-09-27，issue #5600）"
#: 冲突里「一侧（分支）删掉了别人的整条小节」：删的就是这一条（另一侧 main 还在改它）
SECTION_B = ("### 旧条目 B（2026-09-29，issue #5711）", "- 正文 B")

#: 注入锚点：把「两侧都保留」改成「只保留 `:2:` 侧」⇒ 解完必然丢 `:3:` 侧的全部条目。
DROP_THEIRS_OLD = '    kept = [s for s in (sides["ours"], sides["theirs"]) if s]'
DROP_THEIRS_NEW = '    kept = [s for s in (sides["ours"],) if s]'
#: 反向注入：只保留 `:3:` 侧（= 冲突里**删除方**那侧）⇒ 另一侧还在的小节被静默丢掉。
DROP_OURS_NEW = '    kept = [s for s in (sides["theirs"],) if s]'
#: 注入锚点：把判据射程改回**整文件**（旧形态，issue #7861 的病）⇒ 判据 4 的语料必须判红。
OLD_SCOPE_OLD = "    return list(hunks)"
OLD_SCOPE_NEW = "    return [(ours, theirs, 0, len(out))]"


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
                main_rewrites_outside: bool = False, branch_deletes_section: bool = False,
                name: str = "repo") -> Path:
    """造分叉：`main`（origin）与 `feature` **都在 `## [Unreleased]` 顶部加条目**。

    * `extra_conflict_file=True` ⇒ 另一个文件也冲突（判据 3：射程不许扩大）。
    * `drop_outside_line=True` ⇒ 本分支删掉冲突块**之外**的一行（判据 4：合法删除不许假红）。
    * `main_rewrites_outside=True` ⇒ main 在冲突块**之外**改一行正文 + 一条 `### ` 标题
      （判据 4 + 6：旧判据在 C / B 两条上都假红，issue #7861 的复现语料）。
    * `branch_deletes_section=True` ⇒ 本分支删掉整条 `旧条目 B` 小节（main 还在改它）⇒
      冲突块里出现「一侧删了别人的小节」（判据 5：解后不许静默丢）。
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
    if branch_deletes_section:
        section = f"{SECTION_B[0]}\n\n{SECTION_B[1]}\n\n"
        assert section in ours, "夹具锚点没命中（SECTION_B 已不在样本里）"
        ours = ours.replace(section, "", 1)
    (work / CHANGELOG).write_text(ours, encoding="utf-8")
    if extra_conflict_file:
        (work / OTHER_REL).write_text("branch line\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "feat: 本分支条目")

    _git(work, "checkout", "-q", "main")
    main_text = _with_entries(BASE_CHANGELOG, MAIN_ENTRIES)
    if main_rewrites_outside:
        main_text = main_text.replace(OUTSIDE_BODY + "\n", OUTSIDE_BODY + "（main 改后）\n", 1)
        main_text = main_text.replace(OUTSIDE_HEADING, OUTSIDE_HEADING[:-1] + "，改后口径）", 1)
    if branch_deletes_section:
        main_text = main_text.replace(SECTION_B[1] + "\n", SECTION_B[1] + "（main 改后）\n", 1)
    (work / CHANGELOG).write_text(main_text, encoding="utf-8")
    if extra_conflict_file:
        (work / OTHER_REL).write_text("main line\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "feat: main 条目")
    _git(work, "push", "-q", "origin", "main")

    _git(work, "checkout", "-q", "feature")
    return work


def _real_script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _write_copy(tmp_path: Path, text: str) -> Path:
    """把注入后的脚本写成副本（注入只许发生在副本上；真脚本逐次由 `_real_script()` 现取）。"""
    path = tmp_path / "sync-main-injected.sh"
    path.write_text(text, encoding="utf-8")
    return path


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


# ── 判据 4：冲突块**之外**的合法改写 / 删除 ⇒ 不许假红（issue #7861）──────────

def _assert_auto_resolved(work: Path, out: str) -> str:
    """自动解成功的四件套：走自动解路径、无标记残留、收尾两步没跳、工作树干净。"""
    text = (work / CHANGELOG).read_text(encoding="utf-8")
    assert "自动解" in out, f"没有走自动解路径（判据失去对象）：{out}"
    assert not MARKER_RE.search(text), f"解完仍有冲突标记：{text[:400]}"
    assert "合并后内容级校验通过" in out, f"第 5 步被跳过（收尾不许跳）：{out}"
    assert _out(work, "status", "--porcelain") == ""
    return text


@pytest.mark.parametrize("mode", ["--rebase", "merge"])
def test_one_side_rewriting_outside_the_conflict_block_is_auto_resolved(tmp_path, mode):
    """另一侧在冲突块**之外**改过正文与标题 ⇒ 自动解**仍然成功**（issue #7861 的复现语料）。

    旧判据拿 `:2:` / `:3:` 的**全文**做「按原序保留」与「标题并集一条不丢」⇒ 被另一侧改写过的
    旧正文 / 旧标题在解后文本里对不上 ⇒ 报「索引第 :2: 侧原版的这一行…对不上（丢了或次序被打乱）」
    或「丢了 N 条 `### ` 条目」⇒ 每次都退回人工（#7861 实测 4/4，人工解同一份一次就过）。
    本判据钉住「判据的射程 = 冲突块」这个修法。
    """
    work = _build_repo(tmp_path, main_rewrites_outside=True, name=f"rewrite-{mode.strip('-')}")
    args = (mode,) if mode == "--rebase" else ()
    result = _run_sync(work, *args)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    text = _assert_auto_resolved(work, out)
    for entry in MAIN_ENTRIES + BRANCH_ENTRIES:          # 两侧条目一条不丢
        assert entry in text, f"解完丢了条目：{entry}"
    # 块外的合法改写**原样保留**（没有被「按本侧原版」回退掉）
    assert OUTSIDE_BODY + "（main 改后）" in text, "块外的正文改写被回退了"
    assert OUTSIDE_HEADING[:-1] + "，改后口径）" in text, "块外的标题改写被回退了"


def test_one_side_deleting_a_line_outside_the_conflict_block_is_auto_resolved(tmp_path):
    """本分支删掉冲突块**之外**的一行 ⇒ 解后那一行确实没了、且自动解成功（同一类假红）。

    旧版把这一形态登记成「已知假红 / 死亡条件」（C 判红 ⇒ 退回人工）；#7861 兑现了那条条件。
    """
    work = _build_repo(tmp_path, drop_outside_line=True)
    result = _run_sync(work, "--rebase")
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    text = _assert_auto_resolved(work, out)
    assert (SECTION_B[1] + "\n") not in text, "块外那行合法删除没生效（夹具形态不对）"
    for entry in MAIN_ENTRIES + BRANCH_ENTRIES:
        assert entry in text, f"解完丢了条目：{entry}"


# ── 判据 6：把判据射程改回整文件（旧形态）⇒ 判据 4 的语料必红 ─────────────────

def test_old_whole_file_scope_reds_the_rewrite_corpus(tmp_path):
    """红证：`check_scope` 返回整文件区间（旧形态）⇒ issue #7861 的语料**必须**判红。

    没有这一条，「判据只判冲突块」可能只是被写宽了 —— 这份语料在旧形态下红、在新形态下绿，
    两者同时成立才说明收窄的是**射程**而不是**严格度**。注入是内容级的（指纹）+ `bash -n` 自证。
    """
    src = _real_script()
    assert OLD_SCOPE_OLD in src, "注入锚点没命中（判据射程那行已变）⇒ 红证不成立"
    injected = src.replace(OLD_SCOPE_OLD, OLD_SCOPE_NEW)
    assert injected != src, "注入未生效（自证失败 ⇒ 本判据的红证是空断言）"
    syntax = subprocess.run(["bash", "-n"], input=injected, capture_output=True, text=True, env=_env())
    assert syntax.returncode == 0, syntax.stderr

    work = _build_repo(tmp_path, main_rewrites_outside=True, script_text=injected)
    result = _run_sync(work, "--rebase")
    out = result.stdout + result.stderr
    assert result.returncode != 0, f"旧形态（整文件判据）在这份语料上仍然绿 ⇒ 判据 4 与 #7861 无关：{out}"
    assert "未通过" in out, f"判红必须指名内容级验证：{out}"
    assert "❌ rebase 冲突，请解决后重跑本脚本" in out, "人工路径的原话必须还在"
    assert MARKER_RE.search((work / CHANGELOG).read_text(encoding="utf-8")), "判红必须逐字节还原成冲突态"
    assert _rebase_in_progress(work), "判红却把 rebase 推走了（必须停在原处交人工）"


# ── 判据 5：冲突里一侧删了别人的小节 ⇒ 解后不许静默丢 ─────────────────────────

def test_deleted_section_inside_a_conflict_is_not_silently_dropped(tmp_path):
    """分支删掉整条小节、main 还在改它 ⇒ 冲突块里 ours 有、theirs 没有 ⇒ 解后**必须还在**。"""
    work = _build_repo(tmp_path, branch_deletes_section=True)
    result = _run_sync(work, "--rebase")
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    text = _assert_auto_resolved(work, out)
    assert SECTION_B[0] in text, "另一侧还在的小节被静默丢了（判据 5 失效）"
    assert SECTION_B[1] + "（main 改后）" in text, "小节正文被静默丢了"


def test_injected_keep_of_the_deleting_side_is_detected(tmp_path):
    """反向注入：只保留**删除方**（`:3:`）⇒ 另一侧还在的小节被丢 ⇒ 判据必须判红。"""
    src = _real_script()
    assert DROP_THEIRS_OLD in src, "注入锚点没命中"
    injected = src.replace(DROP_THEIRS_OLD, DROP_OURS_NEW)
    assert injected != src, "注入未生效"
    assert red_proof.content_fingerprint(SCRIPT) != red_proof.content_fingerprint(
        _write_copy(tmp_path, injected)), "注入不是内容级的（指纹没变）⇒ 红证不成立"
    work = _build_repo(tmp_path, branch_deletes_section=True, script_text=injected)
    result = _run_sync(work, "--rebase")
    out = result.stdout + result.stderr
    assert result.returncode != 0, f"丢了另一侧还在的小节却仍然绿 ⇒ 判据 5 是空断言：{out}"
    assert "未通过" in out and ("丢了" in out or "少了" in out), f"判红必须指名丢了内容：{out}"
    assert "❌ rebase 冲突，请解决后重跑本脚本" in out
    assert MARKER_RE.search((work / CHANGELOG).read_text(encoding="utf-8"))


# ── 注释漂移锁：改了行为必须同改脚本文件头的「行为」节 ─────────────────────────

def test_script_header_documents_the_autoresolve():
    """文件头缺「自动解 / 验证 / 还原」这三件事 ⇒ 红（行为改了、注释没改 = 假绿来源）。"""
    header = _real_script().split("set -euo pipefail", 1)[0]
    for token in ("CHANGELOG.md 冲突", "自动解", "内容级验证", "还原"):
        assert token in header, f"脚本文件头「行为」节缺 {token}"
    # issue #7861 的登记：判据射程 = 冲突块 + 「能自动解到什么形态 / 什么形态必须人工」
    for token in ("issue #7861", "冲突块", "必须人工"):
        assert token in header, f"脚本文件头缺 #7861 的登记 {token}"
    # 既有两条防护的注释漂移锁（同族，别被本次改动挤掉）
    for token in ("前置拒绝", "合并后内容级校验", "--rebase", "静默回退"):
        assert token in header, f"脚本文件头丢了既有登记 {token}"
