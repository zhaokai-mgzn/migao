# case_ids: MC-012
"""`scripts/sync-main.sh` 的 merge 模式不得**静默回退** main 的用例销账（issue #4984）。

## 缺陷形态（**静默**才是要害，不是「merge 本身错」）

分支分叉期间 main 侧把 case-trust 销账（`must_succeed` / `namespaces` / `precondition`
等**块**）新增进 `.github/cases/*.yml`；本分支没有这些块 ⇒ 三方合并把「本分支缺少该块」
当成**有意删除**，**无冲突**接受 ⇒ 合并结果相对 `origin/main` **净删**内容
（实测 #4965：5 个文件 −27/−25/−20/−3/−2 行），随后 Case Trust 门禁判红，而**归因指向
错误方向**（看起来像「你这个 PR 新增了违规」）。危害是**不红、不报错**：没有任何东西会
因为这次损坏变红。⇒ 处置的核心是**把静默换成响亮**，不是「让 merge 更聪明」。

## 两层防护（缺一层就有漏网形态）

| # | 层 | 判据 | 粒度 |
|---|---|---|---|
| 1 | **前置拒绝**（仅 merge 模式） | `git merge-base HEAD origin/main` 之后**两侧都改过**受管用例面（`.github/cases/**` + `.github/case-trust-baseline.json`）⇒ 非零退出 + 理由 + `--rebase` 命令 | **路径级**（粗） |
| 2 | **合并后内容级校验** | `origin/main` 在受管用例面上新增的**每一行**（用例条目 `- id:`、销账字段块 `must_succeed`/`namespaces`…）必须仍在合并结果里；缺 ⇒ 非零退出 + 指名文件与缺失内容 | **行级**（细） |

第 2 层是第 1 层的兜底：它判的是**内容**（不是「有没有冲突」），所以能判红「merge 无冲突
却把 main 的新增内容丢掉」这一形态 —— 第 1 层被绕过时（`-X ours` / 自定义 merge driver /
人工 merge / 未来收窄前置判据）它是唯一会红的东西。

## 实测订正（夹具是按实测选的，不是照抄 issue 措辞）

issue 原文称「双方只动**同一文件的不同块**」会被三方合并静默接受。**裸 `git merge` 不成立**：
夹具 A（本分支加用例 / main 给另一个 case 加销账块，两块相距很远）⇒ **两块都在**（干净合并，
没有回退）；把两块挪到相邻位置 ⇒ **CONFLICT**（响亮）。即：只要本分支的 diff 相对
merge-base 里**没有**「删除该块」，main 的新增内容在干净合并里**不可能**消失。
实测会**静默**丢内容的形态有三类，本文件各钉一条：

| 夹具 | 形态 | 谁拦得住 |
|---|---|---|
| **A** | 两侧都动受管用例面（issue 描述的**组合**） | 第 1 层拒绝（裸 merge 其实安全，但**不赌**这一次） |
| **B** | merge-base 已含该块，**本分支的提交把它丢了**（旧快照覆盖，同族 #3851）⇒ main 又在同文件别处前进 ⇒ 合并**干净**却丢内容 | 第 1 层拒绝（修前实测：退出码 0 + 块消失，见 PR 报告） |
| **C** | 仓库配了 `.gitattributes` + `merge=ours` 驱动（或 `-X ours`）⇒ 合并**强制取我方**，main 的新增块/新用例条目**静默消失** | 第 2 层判红（第 1 层被绕过时唯一会红的东西） |

## 已登记的边界（照实，别把「登记了」读成「治住了」）

第 2 层的判据是**单向**的（只断言「main 侧**新增**内容仍在」）：夹具 B 那种
「**本分支侧**删掉了 base 里已有的内容」它**不覆盖**（判 `silent`），由第 1 层拦。
`test_registered_boundary_content_check_is_one_directional` 把这条边界钉成**可执行的死亡条件**
—— 将来若有人把第 2 层加强到能拦 B，那条测试会翻红，逼登记同步更新。

## 守卫怎么证明自己不是空判据

* **注入式红证**（常驻）：`_inject()` 把两层分别/同时从脚本里去掉 ⇒ `_verdict()` 从
  `rejected`/`red` 变成 **`silent`**（同一份判据、同一份夹具，只有防护层变了）
  —— 若把判据删掉这些测试仍绿，说明它们是空断言。
* **内容指纹自证**（`scripts/red_proof.py`，issue #4260）：注入必须**真的改变文件内容**
  （内容指纹，**禁** mtime/size），且注入后的脚本 `bash -n` 必须通过
  —— 否则「脚本非零退出」可能只是语法错误的假象，不是守卫判红。
* **反空跑锚点**：夹具必须真的造出「分叉 + 两侧都动受管用例面 + main 侧有销账块而本分支
  没有」；临时仓库/目标文件缺失 ⇒ 红（不得静默跳过）。
* **真文件注入**（人工，见 PR 报告）：把两层从 `scripts/sync-main.sh` 真去掉 ⇒ 本文件必红；
  注入前后用 `python3 scripts/red_proof.py fingerprint|injected|restored` 清缓存 + 指纹自证。

## 边界（照实登记）

* 夹具**自造仓库**（`git init` + 本地 bare origin），**不读真仓库的 `origin/main` 历史**
  ⇒ 在 CI 的 `fetch-depth` 环境下同样可跑（不依赖任何既有历史）。
* 前置拒绝是**路径级**的：两侧都碰过受管用例面就停手（哪怕这次 merge 恰好安全）——
  这是有意的粗粒度（宁可让人改用 `--rebase`，也不要赌这一次没丢内容）。
* 夹具 C 的 merge driver 写在**临时仓库的本地配置**里（`merge.ours.driver`），
  不改本仓库任何配置；它只是「强制取我方」这一机制的可复现载体。
* 不改任何 `.github/workflows/**`（本机 token 无 `workflow` scope，属保留类）；
  **不追溯**已发生的回退（那些已被各自 PR 修正），只堵未来的静默。
"""
from __future__ import annotations

import difflib
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "sync-main.sh"
RED_PROOF = REPO_ROOT / "scripts" / "red_proof.py"
SURFACE_REL = ".github/cases"
CASES_REL = ".github/cases/x.yml"
CASES_BASELINE_REL = ".github/case-trust-baseline.json"
DOCS = (REPO_ROOT / "docs" / "wiki" / "DEV-FLOW.md",
        REPO_ROOT / "docs" / "wiki" / "Development.md")

LEDGER_BLOCK = '    must_succeed: true\n    namespaces:\n      - "ns-main"\n'
OUR_ADDITION = ('  - id: OR-002\n    title: "case B (ours)"\n'
                '    data_checks:\n      - "check ours"\n')
MAIN_NEW_ENTRY = ('  - id: OR-901\n    title: "case NEW (main)"\n'
                  '    data_checks:\n      - "check new"\n')
MAIN_MID_EDIT = '      - "check m"\n      - "check m2 (main)"\n'
GITATTRIBUTES = ".github/cases/** merge=ours\n"

# 注入锚点（脚本里各出现一次；去掉哪一层就改哪一行）
PREFLIGHT_CONDITION = 'if [ -n "$OUR_CASE_CHANGES" ] && [ -n "$MAIN_CASE_CHANGES" ]; then'
CONTENT_CHECK_CALL = 'case_surface_content_check "$BASE"'


def _load_red_proof():
    """按**路径**加载 `scripts/red_proof.py`（不往 `sys.path` 塞东西，与既有契约测试同款）。"""
    spec = importlib.util.spec_from_file_location("red_proof_sync_main_guard", RED_PROOF)
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
    return subprocess.run(["bash", "scripts/sync-main.sh", *args],
                          cwd=str(repo), capture_output=True, text=True, env=_env())


def _cases_yaml(*, base_has_ledger_block: bool) -> str:
    """受管用例面样本：OR-001（可含销账块）+ 大段 filler + OR-500 + OR-900。

    filler 是**判据的一部分**：它保证「本分支的改动区」与「main 的改动区」相距足够远，
    从而让 merge 走**干净合并**（= 静默）而不是冲突 —— 这正是缺陷形态成立的前提。
    """
    block = LEDGER_BLOCK if base_has_ledger_block else ""
    return ("cases:\n"
            '  - id: OR-001\n    title: "case A"\n    data_checks:\n      - "check 1"\n'
            + block
            + "".join(f"  # filler {i}\n" for i in range(1, 41))
            + '  - id: OR-500\n    title: "case M"\n    data_checks:\n      - "check m"\n'
            + "".join(f"  # filler {i}\n" for i in range(41, 81))
            + '  - id: OR-900\n    title: "case Z"\n    data_checks:\n      - "check z"\n')


def _build_repo(tmp_path: Path, *, script_text: str, base_has_ledger_block: bool = False,
                main_merge_driver_ours: bool = False, name: str = "repo") -> Path:
    """造分叉：`main`（origin）与 `feature` 都改过受管用例面，且 main 侧有销账块。

    * `base_has_ledger_block=True` ⇒ 夹具 B：merge-base 已含销账块，**本分支的提交把它丢了**
      （旧快照覆盖），main 又在同一文件的**别处**前进。
    * `main_merge_driver_ours=True` ⇒ 夹具 C：base 带 `.gitattributes`（`merge=ours`）+
      本地 `merge.ours.driver` ⇒ 两侧都改该文件时合并**强制取我方**，main 的新增块与新用例
      条目**静默消失**（无冲突）。
    """
    work = tmp_path / name
    (work / ".github" / "cases").mkdir(parents=True)
    (work / "scripts").mkdir(parents=True)
    (work / "scripts" / "sync-main.sh").write_text(script_text, encoding="utf-8")
    (work / CASES_REL).write_text(_cases_yaml(base_has_ledger_block=base_has_ledger_block),
                                  encoding="utf-8")
    _git(work, "init", "-q", ".")
    _git(work, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(work, "config", "user.email", "sync-main-guard@example.invalid")
    _git(work, "config", "user.name", "sync-main guard")
    if main_merge_driver_ours:
        (work / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8")
        _git(work, "config", "merge.ours.driver", "true")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "base")
    origin = tmp_path / f"{name}.origin.git"
    _git(work, "init", "-q", "--bare", str(origin))
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "main")

    _git(work, "checkout", "-qb", "feature")
    ours = (work / CASES_REL).read_text(encoding="utf-8")
    if base_has_ledger_block:
        ours = ours.replace(LEDGER_BLOCK, "")          # 旧快照覆盖：丢掉 base 里已有的销账块
    (work / CASES_REL).write_text(ours + OUR_ADDITION, encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "ours: 新增用例")

    _git(work, "checkout", "-q", "main")
    theirs = (work / CASES_REL).read_text(encoding="utf-8")
    theirs = theirs.replace('      - "check m"\n', MAIN_MID_EDIT)
    if LEDGER_BLOCK not in theirs:
        theirs = theirs.replace('      - "check 1"\n', '      - "check 1"\n' + LEDGER_BLOCK)
    if main_merge_driver_ours:
        theirs = theirs + MAIN_NEW_ENTRY
    (work / CASES_REL).write_text(theirs, encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "main: 销账块 + 用例内容前进")
    _git(work, "push", "-q", "origin", "main")

    _git(work, "checkout", "-q", "feature")
    return work


def _inject(text: str, *, preflight: bool = True, content_check: bool = True) -> str:
    """把指定防护层从脚本里**去掉**（注入缺陷）；`False` = 该层被移除。

    每层都是一行 ⇒ 注入的差异是**可枚举**的（`test_injection_is_content_level_...` 会数它），
    避免「注入了一大片、红的是别的原因」这种错归因。
    """
    if not preflight:
        assert PREFLIGHT_CONDITION in text, "注入锚点没命中（前置拒绝条件行已变）⇒ 红证不成立"
        text = text.replace(PREFLIGHT_CONDITION, "if false; then  # 注入：前置拒绝已移除")
    if not content_check:
        assert text.count(CONTENT_CHECK_CALL) == 1, "注入锚点没命中（内容级校验调用行已变）⇒ 红证不成立"
        text = text.replace(CONTENT_CHECK_CALL, "true  # 注入：内容级校验已移除")
    return text


def _verdict(returncode: int, out: str) -> str:
    """脚本对「受管用例面可能被回退」的判定：`rejected` / `red` / **`silent`**。

    `silent` = 脚本既不拒绝也不判红（= 缺陷形态：损坏了但没有任何东西变红）。
    `error` = 别的原因非零退出（如真冲突）—— 那是**响亮**的，但不是本单的两层判据。
    """
    if "拒绝 merge" in out:
        return "rejected"
    if "合并后内容级校验失败" in out:
        return "red"
    if returncode != 0:
        return "error"
    return "silent"


def _real_script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


# ── 反空跑锚点：夹具必须真的造出缺陷形态 ──────────────────────────────────────

def test_fixture_anchors_are_real(tmp_path):
    """临时仓库没造出来 / 目标文件不存在 / 两侧没都动受管用例面 ⇒ 红（不得静默跳过）。"""
    work = _build_repo(tmp_path, script_text=_real_script())
    assert work.is_dir()
    assert (work / CASES_REL).is_file()
    assert (work / "scripts" / "sync-main.sh").is_file()
    # 临时仓库里的脚本 == 仓库真脚本（**内容指纹**，不看 mtime/size，issue #4260）
    assert (red_proof.content_fingerprint(work / "scripts" / "sync-main.sh")
            == red_proof.content_fingerprint(SCRIPT))
    base = _out(work, "merge-base", "HEAD", "origin/main")
    assert _out(work, "diff", "--name-only", base, "HEAD", "--", SURFACE_REL) == CASES_REL
    assert _out(work, "diff", "--name-only", base, "origin/main", "--", SURFACE_REL) == CASES_REL
    # main 侧有销账块、本分支没有（缺陷的原料）
    assert "must_succeed: true" in _out(work, "show", f"origin/main:{CASES_REL}")
    assert "must_succeed: true" not in (work / CASES_REL).read_text(encoding="utf-8")


# ── 第 1 层：前置拒绝（夹具 A —— issue 描述的形态，路径级停手）─────────────────

def test_merge_mode_rejects_when_both_sides_touch_case_surface(tmp_path):
    work = _build_repo(tmp_path, script_text=_real_script())
    result = _run_sync(work)
    out = result.stdout + result.stderr
    assert _verdict(result.returncode, out) == "rejected", out
    assert "--rebase" in out, "拒绝必须给出可执行的替代命令（否则人只会手工绕过）"
    assert CASES_REL in out, "拒绝必须指名是哪些文件触发的"
    assert CASES_BASELINE_REL in out, "拒绝必须说清受管用例面的范围"
    # 拒绝发生在 merge **之前**：HEAD 未动、没有 merge 提交、工作树还是我方那份
    assert _out(work, "rev-parse", "HEAD") == _out(work, "rev-parse", "refs/heads/feature")
    assert not _out(work, "log", "-1", "--format=%s").startswith("Merge")
    assert _out(work, "status", "--porcelain") == ""


def test_merge_mode_rejects_stale_snapshot_silent_revert(tmp_path):
    """夹具 B：修前实测「退出码 0 + main 的销账块消失」（静默），现在必须被前置拒绝。"""
    work = _build_repo(tmp_path, script_text=_real_script(), base_has_ledger_block=True)
    result = _run_sync(work)
    out = result.stdout + result.stderr
    assert _verdict(result.returncode, out) == "rejected", out
    assert not _out(work, "log", "-1", "--format=%s").startswith("Merge")
    assert _out(work, "status", "--porcelain") == ""


# ── `--rebase` 是文档化的替代路径，且真的保住 main 的销账块 ─────────────────────

def test_rebase_mode_keeps_main_ledger_block(tmp_path):
    work = _build_repo(tmp_path, script_text=_real_script())
    result = _run_sync(work, "--rebase")
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "拒绝 merge" not in out
    text = (work / CASES_REL).read_text(encoding="utf-8")
    assert "must_succeed: true" in text, "rebase 后 main 的销账块丢了 —— 替代路径不成立"
    assert '      - "ns-main"' in text
    assert "OR-002" in text, "本分支自己的用例必须在（rebase 不是「丢掉本分支的改动」）"
    assert "合并后内容级校验通过" in out


# ── 第 2 层：内容级校验兜住「前置拒绝被绕过」的静默回退（夹具 C）─────────────────

def test_content_check_reds_when_merge_driver_drops_main_additions(tmp_path):
    """去掉前置拒绝（注入）后，`merge=ours` 会把 main 的新增块与新用例条目**静默**丢掉 ⇒ 判红。"""
    injected = _inject(_real_script(), preflight=False)
    work = _build_repo(tmp_path, script_text=injected, main_merge_driver_ours=True)
    result = _run_sync(work)
    out = result.stdout + result.stderr
    assert _verdict(result.returncode, out) == "red", out
    assert "静默回退" in out
    assert CASES_REL in out, "判红必须指名文件"
    assert "must_succeed: true" in out, "判红必须指名缺失的**销账字段块**内容"
    assert "- id: OR-901" in out, "判红必须指名缺失的**用例条目**内容"
    # 这次 merge 确实**静默**（无冲突、产生了 merge 提交）—— 缺陷形态成立
    assert "CONFLICT" not in out
    assert _out(work, "log", "-1", "--format=%s").startswith("Merge")
    # 回退是真的：合并结果相对 origin/main 少了 main 的新增内容
    diff = _out(work, "diff", "origin/main", "--", SURFACE_REL)
    assert "-    must_succeed: true" in diff
    assert "-  - id: OR-901" in diff


# ── 注入式红证：两层都去掉 ⇒ 同一判据变 `silent`（守卫不是空判据）────────────

def test_red_proof_removing_both_layers_lets_the_silent_revert_through(tmp_path):
    """把两层都去掉 ⇒ 脚本既不拒绝也不判红，且**静默回退真的发生**。

    这条就是「守卫必红」的证明：主判据用的 `_verdict()` 在这里拿不到
    `rejected`/`red` ⇒ 若删掉防护层而它们仍绿，说明那两条是空断言。
    """
    injected = _inject(_real_script(), preflight=False, content_check=False)
    work = _build_repo(tmp_path, script_text=injected, main_merge_driver_ours=True)
    result = _run_sync(work)
    out = result.stdout + result.stderr
    assert _verdict(result.returncode, out) == "silent", out
    assert "拒绝 merge" not in out
    assert "合并后内容级校验失败" not in out
    assert "CONFLICT" not in out, "注入后仍必须是**静默**回退（冲突就成了另一种形态）"
    text = (work / CASES_REL).read_text(encoding="utf-8")
    assert "must_succeed: true" not in text
    assert "OR-901" not in text
    diff = _out(work, "diff", "origin/main", "--", SURFACE_REL)
    assert "-    must_succeed: true" in diff


# ── 已登记的边界（死亡条件）：第 2 层判据是**单向**的 ─────────────────────────

def test_registered_boundary_content_check_is_one_directional(tmp_path):
    """夹具 B 的丢失发生在**本分支侧**（删掉了 base 已有内容），第 2 层不覆盖它 ⇒ `silent`。

    这是**如实登记的边界**，不是「通过」：该形态由第 1 层拦
    （`test_merge_mode_rejects_stale_snapshot_silent_revert`）。
    死亡条件：将来若第 2 层被加强到能拦 B，本测试会翻红 ⇒ 必须同步更新 docstring 里的边界表。
    """
    injected = _inject(_real_script(), preflight=False)
    work = _build_repo(tmp_path, script_text=injected, base_has_ledger_block=True)
    result = _run_sync(work)
    out = result.stdout + result.stderr
    assert _verdict(result.returncode, out) == "silent", out
    assert "CONFLICT" not in out
    assert "must_succeed: true" not in (work / CASES_REL).read_text(encoding="utf-8")


# ── 红证卫生：注入是**内容级**的，且注入后的脚本语法有效 ─────────────────────

@pytest.mark.parametrize("removed_layers", [1, 2])
def test_injection_is_content_level_and_syntactically_valid(tmp_path, removed_layers):
    """内容指纹自证（禁 mtime/size）+ 注入差异可枚举 + `bash -n` 通过。

    没有这一条，「脚本非零退出」可能是**语法错误**的假象而不是守卫判红（错归因）。
    """
    orig = _real_script()
    baseline_fp = red_proof.content_fingerprint(SCRIPT)
    injected = _inject(orig, preflight=False, content_check=(removed_layers == 1))
    path = tmp_path / f"sync-main-injected-{removed_layers}.sh"
    path.write_text(injected, encoding="utf-8")
    # ① 注入真的改变了内容（指纹不同；同秒同长度也照样变）
    red_proof.assert_injection_effective(baseline_fp, red_proof.content_fingerprint(path), True,
                                         label=f"去掉 {removed_layers} 层")
    # ② 注入只动了守卫本身（每层 = 1 行删除 + 1 行新增）
    changed = [ln for ln in difflib.unified_diff(orig.splitlines(), injected.splitlines(),
                                                 lineterm="", n=0)
               if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    assert len(changed) == removed_layers * 2, changed
    # ③ 注入后的脚本语法有效（否则非零退出是假象）
    syntax = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, env=_env())
    assert syntax.returncode == 0, syntax.stderr
    # ④ 真脚本**没被动过**（注入只发生在副本上）
    assert red_proof.content_fingerprint(SCRIPT) == baseline_fp
    assert _real_script() == orig


# ── 注释漂移锁：改行为必须同改脚本文件头「行为」节（issue #4984 交付清单）─────

def test_script_header_documents_both_layers():
    header = _real_script().split("set -euo pipefail", 1)[0]
    for token in ("前置拒绝", "合并后内容级校验", "--rebase", "静默回退"):
        assert token in header, f"脚本文件头「行为」节缺 {token}（行为改了、注释没改 = 假绿来源）"


def test_docs_require_rebase_for_case_library_branches():
    """`docs/wiki/DEV-FLOW.md` / `Development.md` 提到 `sync-main.sh` 处必须说清「改用例库要 --rebase」。"""
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        hits = [ln for ln in text.splitlines() if "sync-main.sh" in ln]
        assert len(hits) >= 1, f"{doc} 未提到 sync-main.sh（文档补句缺失）"
        ok = [ln for ln in hits if "--rebase" in ln and "用例" in ln]
        assert len(ok) >= 1, (f"{doc} 提到 sync-main.sh 却没写「改用例库的分支必须用 --rebase」+ 理由：\n"
                              + "\n".join(hits))
