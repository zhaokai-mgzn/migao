# case_ids: MC-055
"""`dev-worktree.sh rm` 绝不让删除动作穿过软链 + 禁止「跨工作区 node_modules 软链」成为约定（issue #5930）。

## 病灶（2026-10-01 22:18 现场事故，本机实测）

主工作区 `tests/node_modules` 变成**空目录**（`frontend/admin-web/node_modules` 幸存）。
成因是**一个类**，两个候选动作并列（如实并列，不强行二选一）：

- **候选 ①「`rm` 穿过软链」**（issue 原文的假设）—— 本次取证**在 git 2.54.0 上不复现**：
  真 fixture 里 `git worktree remove --force` 对 worktree 内的软链走的是 `lstat` + `unlink`，
  **不跟随**（目标 2 个文件前后完好，读数见 PR body）。⇒ 该假设**不足以**解释现场。
- **候选 ②「`npm ci` 删/重建 node_modules」** —— **实测复现**，且读数与现场**逐字同形**：
  worktree 的 `tests/node_modules` 是指向主工作区的软链时，在它所在目录跑一次 `npm ci`
  ⇒ 目标目录仍在、**内容全空**（fixture：3 → 0 个文件）。这就是「变成空目录」的机制。

⇒ 共同根因 = **「跨工作区共享 `node_modules` 的软链」×「任何会删/重建 `node_modules` 的动作」**。
这类破坏**在仓库外发生、git 里看不见**（软链不入库）⇒ **静默**，没有任何判据会报。

## 本文件判的八条（每条都带注入式红证；红证**只在 `tmp_path` 自造 fixture 上跑**，不碰真工作区）

| # | 判据 | 红证（注入） |
|---|---|---|
| 1 | **控制流（元守卫）**：`cmd_rm` 里对解链函数的**可执行**调用必须**先于** `git … worktree remove`，且不许只存在于注释里 | 删掉调用 / 挪到后面 / 改成注释 ⇒ 各自判红 |
| 2 | **行为（真 fixture + 真 git）**：解链必须发生在删除**之前** —— 用 `PATH` 上的 `git` 见证器记录「真正执行 `worktree remove` 的那一刻，worktree 里还有没有那条软链」；且外部目标逐字节完好 | 删掉调用 ⇒ 见证器读到 `LINK_PRESENT_AT_REMOVE=yes` ⇒ 判红（对照：修后读 `no`） |
| 3 | **反向对照**：不带软链的 worktree 仍能正常移除；`--delete-branch` 语义不变 | ——（对照读数，防「为了安全把 rm 弄坏」） |
| 4 | **危险面钉住**：仍**活着**的跨工作区软链一旦遇上**解引用式删除**，目标被清空 | 断言「清空」确实发生（否则第 2 条的绿可能是空断言） |
| 5 | **类级元守卫（教法扫描）**：仓内没有任何**脚本/文档**把「软链到主工作区 node_modules」教成步骤 | 内存语料里加一行配方 ⇒ 判红；豁免台账**只许缩短**、**条数现取**、陈旧登记即红 |
| 6 | **同源**：`add` 输出与 `docs/wiki/Development.md` 必须带**同一句**规范（不许两处各写一份） | 任一侧删掉该句 ⇒ 判红 |
| 7 | **判别力自证**：判据函数在内存构造的坏形态上各自判红、在对照形态上**不红** | 六种坏形态 + 两条对照 |
| 8 | **可见提示（issue 要求 ①）**：两种危险形态各自**具名**点出 —— 指向**本仓库工作区** / 指向**工作区之外**，且提示里带「路径 → 目标」 | 把「工作区之外」那句 ⚠️ 文案从脚本里**抽掉**（注入变体真跑 `rm`）⇒ 判据 8 当场判红 |

## 「fail-closed 与否」的裁定（issue 原文要求给出理由）

**`rm` 不 fail-closed**（解链后照常删除，只打**具名可见提示**）。三条理由：

1. **解链之后破坏动作已经结构安全** —— 无论 remover 是 git / rm / npm / find，都**没有可穿越的软链面**了；
   拒绝只会增加摩擦，不增加安全。
2. **fail-closed 反而把暴露面重新打开**：worktree 里出现软链是**常态**（`.env` 软链、编辑器目录…）。
   一旦 `rm` 因软链拒跑，人就会改用 `rm -rf <worktree>` —— **那一条不解链**，正是事故形态的入口。
3. **信号由可见提示承担**：每一条软链都**具名**打出「路径 → 目标」，指向**仓库外 / 本仓库工作区**的形态
   另加 ⚠️ 点名（后者正是 #5930 的成因）；真正的"教法"闭环在判据 5 / 6（非破坏面，**那两条才是 fail-closed**）。

## 覆盖不到什么（照实登记，§19.1）

- ❌ **射程只到 `dev-worktree.sh rm` 这一条删除路径**：`prune` 只打印清单、不删（其语义不在本文件）；
  别的会删/重建 `node_modules` 的动作（`npm ci` / `npm install` / 人手 `rm -rf`）**不在本判据的机械射程内**
  —— 它们由判据 5/6 的「不许教这个姿势」+ 文档正确姿势来防，**不是**被拦。
- ❌ **判据 2 的见证器只认 `git … worktree remove` 这一种调用形态**（脚本用 `-C <repo> worktree remove <path> --force`）；
  脚本若改用 `cd <wt> && git worktree remove .` 之类写法，见证器取不到路径 ⇒ **判据 2 会 fail-closed 判红**
  （漏报方向被换成"误报方向"，刻意如此：宁可红也不许静默变空断言）。
- ❌ **教法扫描只认「行首 `ln` + `-s` 族旗标 + 该行含 `node_modules`」这一种配方形态**：
  用 `os.symlink` / `cp -s` / `mklink` / 变量拼接 / 行内穿插其它内容来教同一件事 ⇒ **不入册、也不会红**
  （漏报方向；发现方式只能是人工复核）。
- ❌ **本判据守的消费点是 shell 脚本，登记不进 §28.2.1 的 `wiring_claims_ledger.json`**：那个台账的判据 3
  要求 `::` 左边以 `.py` 结尾（防与「裸文件名 + 冒号 + 行号」禁令混淆）⇒ `scripts/dev-worktree.sh::cmd_rm`
  **结构上登记不进去**。本包**不放宽那个门禁**（放宽 = 降门禁），改由本文件自带的控制流判据 + 真 fixture
  见证承担这一半；缺口照实登记在此。
- ❌ **它判不了「有人过去已经建好的软链」**：仓外文件系统的存量状态不在任何判据的射程内
  （本单范围明确不做追溯修复；拦的是**下一次**）。
- ❌ **判据 4 用的解引用式删除是 POSIX 的 `rm -rf <链接>/`**（带尾斜杠 ⇒ 操作数被解引用），
  **不是** `npm ci` 本身（CI 的 `ci workflow helper tests` 腿不装前端依赖、也不该联网装）。
  现场那一个（`npm ci`）的读数写在 PR body 与用例 MC-054 的 `data_checks` 里，可离线复算。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev-worktree.sh"
DEV_DOC = REPO_ROOT / "docs" / "wiki" / "Development.md"
LEDGER = Path(__file__).with_name("worktree_dep_symlink_ledger.json")

UNLINK_FN = "unlink_symlinks_before_remove"
REMOVE_MARKER = "worktree remove"
#: `add` 输出与 `docs/wiki/Development.md` 必须**逐字**共用的那一句（同源 ⇒ 不许两处各写一份）。
CANON_RULE = "依赖一律在本工作区内安装（npm ci）；禁止把 node_modules 软链到主工作区或其他工作区"
#: 文档侧承载该句的节标题（定位用；取不到即 fail-closed）。
DOC_SECTION = "### worktree 依赖准备"
#: 豁免台账**条数上界**（现取：冻结在判据里 ⇒ 台账自己改不大；只许缩短）。
FROZEN_MAX_EXEMPTIONS = 1
#: 见证器（PATH 上的 `git` 垫片）落盘的口径。
WITNESS_YES = "LINK_PRESENT_AT_REMOVE=yes"
WITNESS_NO = "LINK_PRESENT_AT_REMOVE=no"

GIT = shutil.which("git")

WITNESS_SHIM = """#!/usr/bin/env bash
# 删除时点见证：记录「git 真正执行 worktree remove 的那一刻，worktree 里还有没有那条软链」。
# 目的 = 把「解链先于删除」从"注释里写了"变成**可观测的行为**（issue #5930 判据 2）。
wt=""
prev=""
for a in "$@"; do
  if [ "${prev}" = "remove" ]; then wt="$a"; fi
  prev="$a"
done
if [ -n "${wt}" ] && [ -n "${MIGAO_WT_WITNESS_LOG:-}" ]; then
  if [ -L "${wt}/tests/node_modules" ]; then
    echo "LINK_PRESENT_AT_REMOVE=yes" >> "${MIGAO_WT_WITNESS_LOG}"
  else
    echo "LINK_PRESENT_AT_REMOVE=no" >> "${MIGAO_WT_WITNESS_LOG}"
  fi
fi
exec "${MIGAO_WT_REAL_GIT}" "$@"
"""


# ── 静态面：控制流 / 同源 / 教法扫描 的判定本体（纯函数 ⇒ 可内存注入）──────────────
def function_body(src: str, name: str) -> str:
    """取 shell 函数体（`name() {` → 顶格 `}`）。取不到即 fail-closed（不许静默返回空串）。"""
    start = src.find(f"\n{name}() {{\n")
    if start < 0:
        raise AssertionError(f"定位 `{name}()` 失败（fail-closed）：判据对象没了，不许当成通过")
    end = src.find("\n}\n", start)
    if end < 0:
        raise AssertionError(f"定位 `{name}()` 的结尾失败（fail-closed）")
    return src[start:end]


def executable_lines(body: str) -> list[str]:
    """去掉**注释行**与空行后的可执行行 —— 「解链只写在注释里」必须能被判出来。"""
    return [s for s in (raw.strip() for raw in body.splitlines()) if s and not s.startswith("#")]


def unlink_order_problems(body: str) -> list[str]:
    """判据 1 的判定本体：解链调用必须**可执行**且**先于** `git … worktree remove`。"""
    lines = executable_lines(body)
    remove_idx = next((i for i, l in enumerate(lines) if REMOVE_MARKER in l), None)
    if remove_idx is None:
        return [f"`cmd_rm` 里找不到可执行的 `git … {REMOVE_MARKER}`（fail-closed：判据对象没了）"]
    unlink_idx = next((i for i, l in enumerate(lines) if UNLINK_FN in l and "()" not in l), None)
    if unlink_idx is None:
        return [
            f"`cmd_rm` 里找不到对 `{UNLINK_FN}` 的**可执行**调用"
            f"（只写在注释里 = 没解链）⇒ 删除动作仍可能穿过软链打到仓库外"
        ]
    if unlink_idx > remove_idx:
        return [
            f"顺序反了：`{UNLINK_FN}` 在第 {unlink_idx + 1} 条可执行行、"
            f"`{REMOVE_MARKER}` 在第 {remove_idx + 1} 条 ⇒ **删除动作先跑**（解链必须先于删除）"
        ]
    return []


def same_source_problems(script_text: str, doc_text: str) -> list[str]:
    """判据 6 的判定本体：`add` 输出与文档必须带**同一句**规范（同源，不许两处各写一份）。"""
    problems: list[str] = []
    if CANON_RULE not in doc_text:
        problems.append(f"`docs/wiki/Development.md` 里缺那句规范（同源句）：{CANON_RULE}")
    if CANON_RULE not in script_text:
        problems.append(f"`scripts/dev-worktree.sh` 里缺那句规范（同源句）：{CANON_RULE}")
    try:
        add_body = function_body(script_text, "cmd_add")
    except AssertionError as exc:  # fail-closed：定位不到就报出来，不许静默跳过
        problems.append(str(exc))
        return problems
    if CANON_RULE not in add_body:
        problems.append("规范句不在 `cmd_add` 的**输出**里（写在别处 = 建工作区的人看不到）")
    start = doc_text.find(DOC_SECTION)
    if start < 0:
        problems.append(f"`docs/wiki/Development.md` 里找不到承载节 `{DOC_SECTION}`（fail-closed）")
    elif CANON_RULE not in doc_text[start:]:
        problems.append(f"规范句不在 `docs/wiki/Development.md` 的 `{DOC_SECTION}` 节里")
    return problems


def recipe_hits(text: str) -> list[str]:
    """配方形态：**行首** `ln` + `-s` 族旗标 + 该行含 `node_modules`（注释行不算 —— `#` 开头）。"""
    hits: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s.startswith("ln ") or "node_modules" not in s:
            continue
        if not any(tok.startswith("-") and "s" in tok for tok in s.split()):
            continue
        hits.append(s)
    return hits


def teaching_problems(hits: dict[tuple[str, str], int], exemptions: list) -> list[str]:
    """判据 5 的判定本体：每条命中都必须**已登记豁免**；陈旧登记与超上界各自判红。"""
    problems: list[str] = []
    registered: set[tuple[str, str]] = set()
    for e in exemptions:
        if not isinstance(e, dict):
            problems.append(f"豁免条目不是对象：{e!r}")
            continue
        key = (str(e.get("path", "")), str(e.get("snippet", "")).strip())
        if not key[1]:
            problems.append(f"豁免条目缺 `snippet`（跨行会烂 ⇒ 必须逐字记那一行）：{key[0]}")
            continue
        if not str(e.get("reason", "")).strip():
            problems.append(f"豁免条目缺 `reason`（豁免必须写明理由）：{key[0]}")
        registered.add(key)
    if len(exemptions) > FROZEN_MAX_EXEMPTIONS:
        problems.append(
            f"豁免条数 {len(exemptions)} > 冻结上界 {FROZEN_MAX_EXEMPTIONS} ⇒ 台账**只许缩短**"
            f"（要新增豁免 = 先改判据里的上界，那是一次显式的放宽）"
        )
    for key, count in sorted(hits.items()):
        if key not in registered:
            problems.append(
                f"未登记的「跨工作区 node_modules 软链」配方：{key[0]} ⇒ 逐字一行：{key[1]}"
                f"（共 {count} 处）—— 出口 = 删掉它，或登记进豁免台账并写明理由"
            )
    for key in sorted(registered):
        if key not in hits:
            problems.append(
                f"陈旧豁免：台账登记了 {key[0]} 的 {key[1]!r}，但仓内已无此命中 ⇒ 必须销账（台账只许缩短）"
            )
    return problems


# ── 语料读取 ────────────────────────────────────────────────────────────────
def tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", "surrogateescape")
    files = [REPO_ROOT / p for p in out.split("\0") if p]
    keep: list[Path] = []
    for f in files:
        if not f.is_file() or f.stat().st_size > 1_000_000:
            continue
        keep.append(f)
    return keep


def corpus_hits() -> dict[tuple[str, str], int]:
    hits: dict[tuple[str, str], int] = {}
    for f in tracked_text_files():
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # 二进制 / 读不了 ⇒ 不在文本面内
        for line in recipe_hits(text):
            key = (str(f.relative_to(REPO_ROOT)), line)
            hits[key] = hits.get(key, 0) + 1
    return hits


def load_ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


# ── 真 fixture：真 git 仓库 + 真脚本副本（不 mock；红证只在 tmp_path 上跑）────────
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def build_fixture(base: Path, *, with_link: bool, script_text: str | None = None,
                  external_target: bool = False) -> dict:
    """造一个**真的**仓库 + 一个**真的** worktree（脚本用被测脚本的副本，字节相同）。

    `script_text=None` ⇒ 用仓库里的现役脚本；否则写入给定源码（**注入变体**的唯一入口）。
    """
    repo = base / "main-repo"
    (repo / "scripts").mkdir(parents=True)
    live = SCRIPT.read_text(encoding="utf-8")
    text = live if script_text is None else script_text
    if script_text is not None and text == live:
        raise AssertionError("注入没生效（源码与现役逐字相同）⇒ 下面的判红会变成空断言")
    (repo / "scripts" / "dev-worktree.sh").write_text(text, encoding="utf-8")
    (repo / "scripts" / "dev-worktree.sh").chmod(0o755)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")

    # 「主工作区」侧的依赖；`external_target=True` ⇒ 把它放到**仓库之外**（两种 ⚠️ 形态各自取证）
    target = (base / "outside" / "node_modules") if external_target else (repo / "tests" / "node_modules")
    (target / "pkg").mkdir(parents=True)
    (target / "pkg" / "a.js").write_text("PAYLOAD\n", encoding="utf-8")
    (target / "pkg" / "b.js").write_text("PAYLOAD2\n", encoding="utf-8")
    (target / "KEEP.txt").write_text("keep\n", encoding="utf-8")

    wt = base / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feat-x", str(wt))
    if with_link:
        (wt / "tests").mkdir(parents=True, exist_ok=True)
        # 只用 os.symlink 造链（**刻意不写 shell 配方** —— 否则本文件自己会被判据 5 命中）
        os.symlink(target, wt / "tests" / "node_modules")
    return {"repo": repo, "wt": wt, "target": target, "script": repo / "scripts" / "dev-worktree.sh"}


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def run_rm(fx: dict, base: Path, *extra: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    """跑**真脚本的 rm**，并用 PATH 上的 `git` 垫片见证「删除那一刻还有没有软链」。"""
    shim_dir = base / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text(WITNESS_SHIM, encoding="utf-8")
    shim.chmod(0o755)
    log = base / "witness.log"
    env = dict(os.environ)
    env.update({
        "PATH": f"{shim_dir}{os.pathsep}{env.get('PATH', '')}",
        "MIGAO_WT_REAL_GIT": GIT,
        "MIGAO_WT_WITNESS_LOG": str(log),
    })
    proc = subprocess.run(
        ["bash", str(fx["script"]), "rm", str(fx["wt"]), *extra],
        capture_output=True, text=True, env=env, timeout=180,
        cwd=str(fx["repo"]),  # 脚本按文件头约定「在仓库根目录执行」（它按 cwd 解析 `.git/..`）
    )
    witness = log.read_text(encoding="utf-8").split() if log.exists() else []
    return proc, witness


# ── 判据 ───────────────────────────────────────────────────────────────────
def test_unlink_call_precedes_worktree_remove_and_is_not_a_comment() -> None:
    """判据 1（控制流元守卫）：`cmd_rm` 里解链必须是**可执行**调用且**先于**删除。"""
    src = SCRIPT.read_text(encoding="utf-8")
    problems = unlink_order_problems(function_body(src, "cmd_rm"))
    assert problems == [], "；".join(problems)


def test_injected_control_flow_bad_shapes_are_all_red() -> None:
    """判据 1 的红证 + 判别力自证：三种坏形态各自判红，对照形态不红。"""
    src = SCRIPT.read_text(encoding="utf-8")
    body = function_body(src, "cmd_rm")
    call = f'  {UNLINK_FN} "$path"\n'
    raw = "  git -C \"$REPO_ROOT\" worktree remove \"$path\" --force\n"
    assert call in body, f"注入无从构造：`cmd_rm` 里找不到解链调用行 {call!r}（fail-closed）"
    assert raw in body, "注入无从构造：`cmd_rm` 里找不到删除调用行（fail-closed）"

    removed = body.replace(call, "")
    assert removed != body, "变异没生效（删掉解链调用）⇒ 下面会变成空断言"
    assert unlink_order_problems(removed) != []

    moved = body.replace(call, "").replace(raw, raw + call)
    assert moved != body, "变异没生效（把解链挪到删除之后）"
    assert unlink_order_problems(moved) != []

    commented = body.replace(call, "  # " + call.strip() + "\n")
    assert commented != body, "变异没生效（把解链改成注释）"
    assert unlink_order_problems(commented) != []

    assert unlink_order_problems(body) == []  # 对照：未注入 ⇒ 不红


def test_rm_unlinks_before_removing_and_keeps_the_external_target_intact(tmp_path: Path) -> None:
    """判据 2（行为，真 fixture）：解链先行 + 外部目标逐字节完好 + worktree 正常消失。"""
    fx = build_fixture(tmp_path, with_link=True)
    before = snapshot(fx["target"])
    proc, witness = run_rm(fx, tmp_path)

    assert proc.returncode == 0, f"rm 非零退出：stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert witness == [WITNESS_NO], (
        f"删除那一刻 worktree 里**还有**软链（见证读数 {witness}）⇒ 解链没有先于删除；"
        f"stdout={proc.stdout!r}"
    )
    assert snapshot(fx["target"]) == before, "外部目标被改动/清空 —— 删除动作穿过了软链"
    assert not fx["wt"].exists(), f"worktree 没被移除：{fx['wt']}"
    assert UNLINK_FN in fx["script"].read_text(encoding="utf-8"), "被测副本与现役脚本不同源"
    assert "🔗" in proc.stdout and str(fx["wt"] / "tests" / "node_modules") in proc.stdout, (
        f"解链没有**具名可见**地打出来（issue 要求可见提示）：stdout={proc.stdout!r}"
    )


def visible_warning_problems(stdout: str, wt: Path, target: Path, marker: str) -> list[str]:
    """判据 8 的判定本体（纯函数 ⇒ 可在**注入变体**上证明它有判别力）。"""
    problems: list[str] = []
    if marker not in stdout:
        problems.append(f"没有**具名**点出该形态（期望 {marker!r}）")
    if f"{wt}/tests/node_modules → {target}" not in stdout:
        problems.append("提示里没有「路径 → 目标」")
    return problems


def test_visible_warning_distinguishes_outside_repo_from_cross_workspace(tmp_path: Path) -> None:
    """判据 8（issue 要求 ①「对软链指向本仓库之外/主工作区给出**可见提示**」）+ **注入红证**：

    两种形态必须各自被**具名**点出来（而不是只打一行「发现软链」）：
    指向**本仓库工作区** = 跨工作区共享依赖的典型形态（本事故成因）；指向**仓库之外** = 删除动作若穿过它，
    打到的是**仓库外的数据**。两条都必须在输出里逐字出现，且各自带上「路径 → 目标」。
    """
    inside = build_fixture(tmp_path / "inside", with_link=True)
    proc_in, _ = run_rm(inside, tmp_path / "inside")
    assert proc_in.returncode == 0, f"rm 非零退出：{proc_in.stderr!r}"
    assert visible_warning_problems(
        proc_in.stdout, inside["wt"], inside["target"], "指向**本仓库工作区**"
    ) == [], f"指向本仓库工作区的软链没有被具名点出来：{proc_in.stdout!r}"

    outside = build_fixture(tmp_path / "outside-fixture", with_link=True, external_target=True)
    proc_out, _ = run_rm(outside, tmp_path / "outside-fixture")
    assert proc_out.returncode == 0, f"rm 非零退出：{proc_out.stderr!r}"
    assert visible_warning_problems(
        proc_out.stdout, outside["wt"], outside["target"], "指向**工作区之外**"
    ) == [], f"指向仓库之外的软链没有被具名点出来：{proc_out.stdout!r}"

    # 注入：把那句 ⚠️ 文案从脚本里抽掉 ⇒ 判据必须判红（自证不是恒真断言）
    src = SCRIPT.read_text(encoding="utf-8")
    marker_text = "指向**工作区之外** —— 删除动作若穿过它，打到的是仓库外的数据"
    assert src.count(marker_text) == 1, f"注入无从构造（fail-closed）：count={src.count(marker_text)}"
    injected = src.replace(marker_text, "指向外部", 1)
    assert injected != src, "变异没生效 ⇒ 下面这条会变成空断言"
    fx = build_fixture(tmp_path / "inj", with_link=True, external_target=True, script_text=injected)
    proc_inj, _ = run_rm(fx, tmp_path / "inj")
    assert visible_warning_problems(
        proc_inj.stdout, fx["wt"], fx["target"], "指向**工作区之外**"
    ) != [], "注入后判据仍判绿 ⇒ 判据 8 是空断言"


def test_injected_missing_unlink_leaves_the_link_live_at_removal_time(tmp_path: Path) -> None:
    """判据 2 的红证：删掉解链那一步 ⇒ 见证器读到 `yes`（= 删除动作暴露在活链上）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    body = function_body(src, "cmd_rm")
    call = f'  {UNLINK_FN} "$path"\n'
    assert call in body, "注入无从构造（fail-closed）"
    injected = src.replace(body, body.replace(call, ""), 1)
    assert injected != src, "变异没生效 ⇒ 下面的判红会变成空断言"
    assert f'  {UNLINK_FN} "$path"\n' not in function_body(injected, "cmd_rm"), "变异没清干净"

    fx = build_fixture(tmp_path, with_link=True, script_text=injected)
    proc, witness = run_rm(fx, tmp_path)
    assert witness == [WITNESS_YES], (
        f"注入后本该看到活链进入删除时点（见证读数 {witness}）—— 若为 no，说明这条红证是空的："
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


def test_dereferencing_removal_on_a_live_cross_workspace_link_empties_the_target(tmp_path: Path) -> None:
    """判据 4：**活着的**跨工作区软链遇上解引用式删除 ⇒ 目标被清空（事故的可执行同形）。"""
    fx = build_fixture(tmp_path, with_link=True)
    before = snapshot(fx["target"])
    assert before, "fixture 造空了（fail-closed）"

    link = fx["wt"] / "tests" / "node_modules"
    # POSIX：操作数带尾斜杠 ⇒ 解引用。现场真实的那一个是 `npm ci`（读数 3 → 0，见模块 docstring）。
    proc = subprocess.run(["rm", "-rf", f"{link}/"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"解引用式删除没跑成：{proc.stderr!r}"

    after = snapshot(fx["target"])
    assert after != before, "解引用式删除没有打到目标 ⇒ 判据 2 的「完好」会变成空断言（先修 fixture）"
    assert after == {}, f"目标未被清空（{sorted(after)}）⇒ 危险面没被钉住"


def test_worktree_without_links_still_removes_normally(tmp_path: Path) -> None:
    """判据 3（反向对照）：不带软链的 worktree 仍能正常移除，`--delete-branch` 语义不变。"""
    fx = build_fixture(tmp_path, with_link=False)
    before = snapshot(fx["target"])
    proc, witness = run_rm(fx, tmp_path, "--delete-branch")

    assert proc.returncode == 0, f"rm 非零退出：stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert not fx["wt"].exists(), f"worktree 没被移除：{fx['wt']}"
    assert snapshot(fx["target"]) == before, "无软链形态下外部目标也被动了（不该发生）"
    assert witness == [WITNESS_NO], f"无软链形态的对照读数应为 `no`：{witness}"
    branches = subprocess.run(
        ["git", "-C", str(fx["repo"]), "branch", "--list", "feat-x"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert branches == "", f"--delete-branch 没删掉分支：{branches!r}"


def test_no_script_or_doc_teaches_cross_workspace_node_modules_symlink() -> None:
    """判据 5（类级元守卫）：仓内没有脚本/文档把这个姿势教成步骤；豁免台账只许缩短。"""
    ledger = load_ledger()
    problems = teaching_problems(corpus_hits(), ledger.get("exemptions") or [])
    assert problems == [], "\n".join(problems)


def test_teaching_scan_has_teeth_on_injected_corpora() -> None:
    """判据 5 的红证 + 判别力自证（内存构造，不落盘）。"""
    ledger = load_ledger()
    exempt = ledger.get("exemptions") or []
    injected = {("docs/wiki/Development.md", "ln -s /main/repo/tests/node_modules /wt/tests/node_modules"): 1}
    assert teaching_problems(injected, []) != []  # 未登记 ⇒ 红

    live = corpus_hits()
    assert live, "真语料里一条命中都没有 ⇒ 下面的「陈旧登记 ⇒ 红」无从判别（fail-closed）"
    live_key = next(iter(live))
    assert teaching_problems(live, []) != []  # 真语料未登记 ⇒ 红（牙齿）
    assert teaching_problems({}, exempt) != []  # 台账未兑现（陈旧登记）⇒ 红
    assert teaching_problems({}, []) == []  # 对照：都空 ⇒ 不红

    over = exempt + [{"path": "docs/wiki/Development.md", "snippet": "ln -s a b", "reason": "r"}]
    assert teaching_problems({}, over) != []  # 超冻结上界 ⇒ 红
    assert teaching_problems(live, exempt) == []  # 对照：真语料 + 现台账 ⇒ 不红


def test_add_output_and_development_doc_share_one_canonical_rule() -> None:
    """判据 6（同源）：`add` 输出与文档带的必须是**同一句**规范，且不许两处各写一份。"""
    script_text = SCRIPT.read_text(encoding="utf-8")
    doc_text = DEV_DOC.read_text(encoding="utf-8")
    problems = same_source_problems(script_text, doc_text)
    assert problems == [], "；".join(problems)

    missing_doc = doc_text.replace(CANON_RULE, "")
    assert missing_doc != doc_text, "注入没生效（文档侧）"
    assert same_source_problems(script_text, missing_doc) != []

    missing_add = script_text.replace(f'  echo "   🔴 {CANON_RULE}"', "", 1)
    assert missing_add != script_text, "注入没生效（add 输出侧）⇒ 会变成空断言"
    assert same_source_problems(missing_add, doc_text) != []


def test_add_output_reaches_the_operator_with_the_discouragement(tmp_path: Path) -> None:
    """判据 6 的**行为面**（§28.2「判据本体绿 ≠ 接线在」）：`add` 的输出必须真的打出来。

    为什么不能只做字符串搜索：本包第一版把 `echo` 里的占位符写坏成 `${'$'}{path}` ——
    **`bash -n` 抓不到**（bad substitution 是运行期错误），字符串搜索也抓不到（那句规范在，
    只是它**后面的**一段炸了）⇒ `add` 会在建完工作区之后**中途非零退出**，而操作者看不到后半段提示。
    这条判据真跑一次 `add`（真 git 仓库、真 worktree，全在 `tmp_path` 里）。
    """
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "dev-worktree.sh").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "branch", "feat-demo")

    env = dict(os.environ, MIGAO_WT_BASE=str(tmp_path / "wt-base"))
    proc = subprocess.run(
        ["bash", str(repo / "scripts" / "dev-worktree.sh"), "add", "feat-demo"],
        capture_output=True, text=True, env=env, timeout=180, cwd=str(repo),
    )
    assert proc.returncode == 0, (
        f"`add` 非零退出（输出半截 = 操作者看不到提示）：stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "bad substitution" not in proc.stderr, f"脚本里有运行期语法错误：{proc.stderr!r}"
    out = proc.stdout
    assert CANON_RULE in out, f"`add` 的输出里没有那句规范：{out!r}"
    assert "worktree 依赖准备" in out, f"`add` 的输出没把正确姿势指向文档同名节：{out!r}"
    assert "工作区就绪" in out, f"`add` 的输出没有走到最后（半截输出）：{out!r}"


def test_the_guarded_consumption_point_resolves() -> None:
    """本判据守的消费点（`cmd_rm` 的函数体）必须在**真实文件**里逐字可解析 —— 摘掉它判据 1 当场判红。

    ⚠️ 为何**不**用 §28.2.1 的 `wiring_claims_ledger.json` 登记：那个台账的判据 3 要求 `::` 左边以 `.py`
    结尾（防与 Case Trust 规则 G 的「裸文件名 + 冒号 + 行号」既有禁令混淆），而本判据的消费点住在
    `scripts/dev-worktree.sh` 里 ⇒ **结构上登记不进去**。那里是**别人的门禁**，本包**不为迁就自己放宽它**
    （放宽 = 降门禁）。⇒ 这一半由本文件自带的判据 1（控制流）+ 判据 2（真 fixture 见证）承担。
    """
    text = SCRIPT.read_text(encoding="utf-8")
    assert "\ncmd_rm() {\n" in text, "消费点解析不到：scripts/dev-worktree.sh::cmd_rm"
    assert "\nunlink_symlinks_before_remove() {\n" in text, f"解链函数定义不在了：{UNLINK_FN}"


def test_helper_declares_no_recipe_shape_itself() -> None:
    """自证：本文件（判据 5 的扫描面之一）自己**不能**包含配方形态 —— 否则守卫会被自己的语料喂红。"""
    assert recipe_hits(Path(__file__).read_text(encoding="utf-8")) == []
