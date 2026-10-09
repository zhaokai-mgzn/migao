# case_ids: MC-089
"""`dev-worktree.sh list` 在 `$LOCK_DIR` 存在任何 `*.lock` 时退出码 = 1（issue #6243）。

## 病（主会话 2026-10-09 22:43 +08 现取读数，可复算）

```
$ ls .git/sessions            # 5 把锁，全部是失效锁（💀 进程已退出）
$ ./scripts/dev-worktree.sh list
…（worktree 表 + 会话锁清单，内容全都正常打出）…
$ echo $?                     # ← 1
1
```

口径：**不是「有活锁才 1」，而是「只要 `$LOCK_DIR` 里存在任何 `*.lock` 文件（哪怕全部失效）就 1」**。

## 根因（`scripts/dev-worktree.sh` 的 `lock_list`）

```bash
lock_list() {
  [ -d "$LOCK_DIR" ] || { echo "（无会话锁）"; return 0; }   # 无锁目录这条**有**显式 return 0 ✅
  …
  [ "$found" = "0" ] && echo "（无会话锁）"        # ← 函数**最后一条命令**
}
```

`found=1` ⇒ `[ ]` 为假 ⇒ `&&` 短路 ⇒ **该复合命令退出码 = 1**；它就是 `lock_list` 的返回值，
而 `lock_list` 是 `cmd_list` 的最后一条命令 ⇒ **脚本 exit 1**。

## 本文件判的五条

| # | 判据 | 会怎么红 |
|---|---|---|
| 1 | **实例判据（行为，真 fixture + 真 git）**：造 `$LOCK_DIR` + 至少一个 `*.lock`（**失效锁**）⇒ `list` 必须 **exit 0**，且锁按名列出 | 旧实现 exit **1**（红证逐字见下） |
| 2 | **修前红（注入变体，双向对照）**：把末行还原成 `[ "$found" = "0" ] && echo …` ⇒ 同 fixture 必须 exit **1**（否则判据 1 的绿是空断言） | 注入未生效 / 注入后仍 0 ⇒ 判红（fail-closed） |
| 3 | **负向对照（防「一律 return 0」吞错）**：① 不存在的子命令 ⇒ 仍**非零**；② `git worktree list` **真失败**（注入式 `git` 垫片只让这一个子命令 rc=128）⇒ 仍**非零** | 「修法」写成无条件 0 ⇒ 判红 |
| 4 | **类级元守卫**：`scripts/*.sh` 里**任何函数体**的最后一条可执行命令都不得是「退出码会被当成返回值」的复合形态（`[ … ] && …`）—— 未登记即红；豁免台账 `scripts_locked_tail_ledger.json` **只许缩短**（条数**现取**，写死在判据里）、**登记必须兑现**、陈旧登记即红 | 新增一处 / 改回旧形态 ⇒ 具名判红 |
| 5 | **判别力自证 + 射程钉住**：扫描器在内存造的坏形态上判红、在对照形态上不红；射程内每个脚本都真被扫到（不是 0 个函数 = 假绿）；`if …; then …; fi` 形态（退出码来自块尾）**不**误报 | 扫描器退化成绿 / 射程变空 ⇒ 判红 |

## 边界（照实登记，§19.1）

- ❌ **只治退出码，不治锁的生命周期**：`add` 用 `$$`（`add` 自己的 PID）写锁，`add` 一结束该 PID 就退出
  ⇒ 正常流程产出的锁**立刻变失效**、且只在 `rm` 时才释放（正是本单 `list` 长期 exit 1 的成因）。
  那是**另一个问题**，本单登记为「顺带发现」，不在本判据射程内。
- ❌ **类级守卫只扫 `scripts/*.sh`**（issue 的判据面就是这一族）；其它目录下的 shell 脚本不在射程。
- ❌ **只看「函数体最后一条可执行命令」这一个位置**（退出码唯一会被继承成返回值的地方）：
  `&&` 出现在函数中部、后面还有别的命令时**无害**（退出码由最后一条决定），本判据**有意不报**
  —— 这是刻意的窄射程，避免把合法写法误报成违规。
- ❌ **块结构尾部**（`fi` / `done` / `esac` / `}` 结尾）**不在射程**：那时退出码来自块内最后一条命令，
  静态行扫描判定不了（需要 AST）。**已核过的对照读数**：现扫 `scripts/*.sh` 只有 3 处行尾命中，
  其中 1 处是 `if …; then …; fi`（退出码来自块尾，**不是**本缺陷）⇒ 被 `if` 起始行排除，**不登记**。
- ❌ 只跑定点判据：不跑 `verify-all.sh gate` / 全量 pytest（重活串行，见 `migao-dev-flow` §27）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCRIPT = SCRIPTS_DIR / "dev-worktree.sh"
LEDGER = Path(__file__).with_name("scripts_locked_tail_ledger.json")

#: 台账条数冻结上界（**只许缩短**，写死在判据里 ⇒ 台账自己改不大）。
LEDGER_MAX = 1

#: 函数体最后一条命令 = `[ … ] && …`（开始行是 `if`/`while`/`until`/`for`/`case` 的**不算**：
#: 那种形态的退出码来自块尾 `fi`/`done`/`esac`，静态行扫描判不了，见文件头「边界」）。
BANG_TAIL = re.compile(r"^\s*(?:\[\[?|test\b|\(\().*?(\]\]?|\)\))\s*&&\s*\S")
FUNC_HEAD = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{")
BLOCK_HEAD = re.compile(r"^\s*(if|while|until|for|case)\b")
#: 台账 key 形态 `<脚本文件名>::<函数名>`（不写行号 —— 行号会漂，见 §16.7 引用纪律）。
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+\.sh::[A-Za-z_][A-Za-z0-9_]*$")


def function_tails(text: str) -> dict[str, str]:
    """每个函数体**最后一条可执行命令**（按大括号深度配平；返回 `<函数名> -> 该行原文>`）。"""
    lines = text.splitlines()
    out: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = FUNC_HEAD.match(lines[i])
        if not m:
            i += 1
            continue
        depth = lines[i].count("{") - lines[i].count("}")
        body: list[str] = []
        j = i + 1
        while j < len(lines) and depth > 0:
            body.append(lines[j])
            depth += lines[j].count("{") - lines[j].count("}")
            j += 1
        body = [ln for ln in body if ln.strip() not in ("}", "})")]
        k = len(body) - 1
        while k >= 0 and (not body[k].strip() or body[k].strip().startswith("#")):
            k -= 1
        out[m.group(1)] = body[k] if k >= 0 else ""
        i = j
    return out


def bang_tail_hits(text: str) -> list[tuple[str, str]]:
    """`scripts/*.sh` 里「末命令是 `[ … ] && …`」的位置（含脚本级尾行）。"""
    hits: list[tuple[str, str]] = []
    for name, line in function_tails(text).items():
        if BANG_TAIL.match(line) and not BLOCK_HEAD.match(line):
            hits.append((name, line.strip()))
    lines = text.splitlines()
    k = len(lines) - 1
    while k >= 0 and (not lines[k].strip() or lines[k].strip().startswith("#")):
        k -= 1
    if k >= 0 and BANG_TAIL.match(lines[k]):
        hits.append(("<脚本级尾行>", lines[k].strip()))
    return hits


def expired_in(ledger: dict, keys: list[str]) -> list[str]:
    """登记了、但那个位置现在已经不是该形态（陈旧登记）。"""
    return [k for k in ledger["exemptions"] if k not in keys]


def load_ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


# ── 真 fixture：真 git 仓库 + 真脚本副本（不 mock；红证只在 tmp_path 上跑）────────
def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def build_fixture(base: Path, *, script_text: str | None = None) -> dict:
    """造真仓库 + 真 worktree（脚本用被测脚本的副本，字节相同）；`script_text` = 注入变体入口。"""
    repo = base / "main-repo"
    (repo / "scripts").mkdir(parents=True)
    live = SCRIPT.read_text(encoding="utf-8")
    text = live if script_text is None else script_text
    if script_text is not None and text == live:
        raise AssertionError("注入没生效（源码与现役逐字相同）⇒ 下面的判红会变成空断言")
    (repo / "scripts" / "dev-worktree.sh").write_text(text, encoding="utf-8")
    (repo / "scripts" / "dev-worktree.sh").chmod(0o755)
    # `add` 会以 `|| echo` 调用它（best-effort）；给个 rc=0 的最小桩，别让夹具里出现无关噪声。
    stub = repo / "scripts" / "issue-lifecycle.sh"
    stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")
    return {"repo": repo, "script": repo / "scripts" / "dev-worktree.sh"}


def run_list(fx: dict, *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(fx["script"]), "list"],
        capture_output=True, text=True, timeout=120,
        cwd=str(cwd or fx["repo"]),
    )


def seed_stale_lock(fx: dict, branch: str = "stale-branch") -> Path:
    """造一个**只含失效锁**的锁状态，且**真实分支不被任何 worktree 占用**。

    手法与真实成因同形（`添加工作区 → 会话结束/工作区被清掉 → 锁留下`），但**不依赖时序**：
    `lock_register` 写的是当时那个进程的 PID，`add` 一返回该 PID 必已退出 ⇒ 造出的锁**必然失效**；
    随后把 worktree 解绑（`remove --force`）⇒ 锁留下的同时分支空出来（可反复造）。
    """
    lock_dir = fx["repo"] / ".git" / "sessions"
    subprocess.run(["git", "-C", str(fx["repo"]), "branch", branch, "main"], check=True, capture_output=True)
    add = subprocess.run(
        ["bash", str(fx["script"]), "add", branch],
        capture_output=True, text=True, timeout=180, cwd=str(fx["repo"]),
    )
    if add.returncode != 0:  # fail-closed：夹具没造出来就不许往下走
        raise AssertionError(f"夹具 add 失败（rc={add.returncode}）：\n{add.stdout}\n{add.stderr}")
    locks = sorted(lock_dir.glob("*.lock"))
    if len(locks) != 1:
        raise AssertionError(f"夹具没造出唯一一把锁：{locks}")
    subprocess.run(
        ["git", "-C", str(fx["repo"]), "worktree", "remove", str(fx["repo"].parent / "migao-wt" / branch), "--force"],
        check=True, capture_output=True,
    )
    return locks[0]


# ── 判据 1：实例判据（行为，真 fixture）
def test_list_exits_zero_with_stale_session_lock_present(tmp_path: Path) -> None:
    """判据 1：`$LOCK_DIR` 里有 `*.lock`（失效锁）⇒ `list` 必须 **exit 0**，且锁按名列出。"""
    fx = build_fixture(tmp_path)
    lock = seed_stale_lock(fx)
    proc = run_list(fx)
    assert lock.exists() and lock.read_text(encoding="utf-8").strip(), "失效锁没造出来（判据会变空断言）"
    assert "stale-branch" in proc.stdout, f"锁没被列出：\n{proc.stdout}"
    assert proc.returncode == 0, (
        f"存在会话锁时 `list` 退出码 = {proc.returncode}（应为 0）—— 这就是 issue #6243 的形态。\n"
        f"stdout 尾部：\n{proc.stdout[-400:]}"
    )


# ── 判据 2：修前红（注入变体，双向对照）
def test_injected_old_tail_makes_list_exit_nonzero(tmp_path: Path) -> None:
    """判据 2：把末行还原成旧形态 `[ "$found" = "0" ] && echo …` ⇒ 同 fixture 必须 exit 1。"""
    live = SCRIPT.read_text(encoding="utf-8")
    marker = '[ "$found" = "0" ] && echo "（无会话锁）"'
    head = 'if [ "$found" = "0" ]; then'
    lines = live.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if ln.strip() == head]
    if len(starts) != 1:
        raise AssertionError(f"注入锚（`{head}`）在现役脚本里出现 {len(starts)} 次（应为 1）⇒ 注入点漂了")
    start = starts[0]
    end = start
    while end < len(lines) and lines[end].strip() != "}":
        end += 1
    if end >= len(lines):
        raise AssertionError("注入锚后的 `}` 找不到 ⇒ 注入点漂了，先核对脚本")
    injected = "".join(lines[:start] + ['  [ "$found" = "0" ] && echo "（无会话锁）"\n}\n'] + lines[end + 1:])
    assert injected != live, "注入没生效 ⇒ 下面的判红会变成空断言"
    injected_tail = '  [ "$found" = "0" ] && echo "（无会话锁）"'
    assert sum(1 for ln in injected.splitlines() if ln == injected_tail) == 1, (
        "注入后旧形态那一行不唯一 ⇒ 旧实现没被真正还原，判红会变成空断言"
    )
    assert subprocess.run(["bash", "-n"], input=injected, capture_output=True, text=True).returncode == 0, (
        "注入变体语法坏掉了（判红会变成「语法错」而不是「退出码错」）⇒ 先修注入"
    )

    fx = build_fixture(tmp_path, script_text=injected)
    seed_stale_lock(fx)
    proc = run_list(fx)
    assert proc.returncode == 1, (
        f"旧形态注入后 `list` 退出码 = {proc.returncode}（应为 1）—— 判据 1 的红证就是它。\n"
        f"stdout 尾部：\n{proc.stdout[-400:]}"
    )


# ── 判据 3：负向对照（防「一律 return 0」吞错）
#: 只让 `worktree list` 失败的 `git` 垫片（其余子命令透传真 git）—— 用于造「git 真出错」。
FAILING_GIT_SHIM = """#!/usr/bin/env bash
if [ "$1" = "-C" ]; then shift 2; fi
if [ "$1" = "worktree" ] && [ "$2" = "list" ]; then
  echo "fatal: 注入式 git 失败（判据 3 的对照）" >&2
  exit 128
fi
exec "$MIGAO_WT_REAL_GIT" "$@"
"""


def run_list_with_failing_git(fx: dict, base: Path) -> subprocess.CompletedProcess:
    shim_dir = base / "shim"
    shim_dir.mkdir(parents=True)
    shim = shim_dir / "git"
    shim.write_text(FAILING_GIT_SHIM, encoding="utf-8")
    shim.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    env["MIGAO_WT_REAL_GIT"] = shutil.which("git") or "git"
    return subprocess.run(
        ["bash", str(fx["script"]), "list"],
        capture_output=True, text=True, timeout=120, cwd=str(fx["repo"]), env=env,
    )


def test_negative_controls_stay_nonzero(tmp_path: Path) -> None:
    """判据 3：① 不存在的子命令 ⇒ 非零；② `git worktree list` 真失败 ⇒ 仍**非零**（修法不许吞错）。"""
    fx = build_fixture(tmp_path)
    bogus = subprocess.run(
        ["bash", str(fx["script"]), "definitely-not-a-subcommand"],
        capture_output=True, text=True, timeout=120, cwd=str(fx["repo"]),
    )
    assert bogus.returncode != 0, "不存在的子命令退出码 = 0（「一律 return 0」把用法错误吞了）"

    broken = run_list_with_failing_git(fx, tmp_path / "shim-base")
    assert "注入式 git 失败" in broken.stderr, f"垫片没生效（判据会变空断言）：{broken.stderr!r}"
    assert broken.returncode != 0, (
        "`git worktree list` 真失败时 `list` 仍 exit 0 —— 修法把真出错也吞掉了"
        f"（stdout：\n{broken.stdout[-300:]}\nstderr：\n{broken.stderr[-300:]}）"
    )


# ── 判据 4：类级元守卫（未登记即红 / 台账只许缩短 / 登记必须兑现 / 陈旧登记即红）
def test_no_unregistered_exit_code_tail_in_scripts() -> None:
    """判据 4：`scripts/*.sh` 里末命令为 `[ … ] && …` 的位置必须已登记豁免，否则判红。"""
    ledger = load_ledger()
    hits: dict[str, list[str]] = {}
    scanned: dict[str, int] = {}
    for path in sorted(SCRIPTS_DIR.glob("*.sh")):
        text = path.read_text(encoding="utf-8")
        scanned[path.name] = len(function_tails(text))
        found = bang_tail_hits(text)
        if found:
            hits[path.name] = found

    problems: list[str] = []
    # 台账**只许缩短**：条数现取 + 写死上界（台账自己改不大）。
    if len(ledger["exemptions"]) > LEDGER_MAX:
        problems.append(f"豁免台账条数 = {len(ledger['exemptions'])} > 冻结上界 {LEDGER_MAX}（台账只许缩短）")
    flat: list[str] = []
    for name, found in hits.items():
        for func, line in found:
            key = f"{name}::{func}"
            flat.append(key)
            why = ledger["exemptions"].get(key)
            if not why:
                problems.append(f"未登记的退出码陷阱：{key} —— 末命令 `{line}`")
            elif len(str(why).strip()) < 8:
                problems.append(f"{key} 的 why 太短（等于没写理由）")
    for key in ledger["exemptions"]:
        if not KEY_RE.match(key):
            problems.append(f"台账 key 形态非法（应 `<脚本>.sh::<函数名>`）：{key}")
        elif key not in flat:
            problems.append(f"陈旧登记（该位置已不是该形态 ⇒ 台账该缩短）：{key}")
    assert problems == [], "；".join(problems)


# ── 判据 5：判别力自证 + 射程钉住
def test_guard_has_teeth_and_a_nonempty_scope() -> None:
    """判据 5：坏形态各判红、对照形态不红；射程内每个脚本都真被扫到（0 个函数 = 假绿）。"""
    bad = (
        "#!/usr/bin/env bash\nf() {\n  echo hi\n  [ -n \"$x\" ] && echo yes\n}\n"
    )
    assert bang_tail_hits(bad) == [("f", '[ -n "$x" ] && echo yes')], "坏形态没被判红（守卫退化成绿）"
    bad2 = "#!/usr/bin/env bash\ng() {\n  [ -f a ] && rm -f a\n}\n"
    assert bang_tail_hits(bad2), "第二个坏形态没被判红"
    bad3 = "#!/usr/bin/env bash\n[ -n \"$x\" ] && echo yes\n"
    assert bang_tail_hits(bad3) == [("<脚本级尾行>", '[ -n "$x" ] && echo yes')], "脚本级尾行没被判红"

    good = (
        "#!/usr/bin/env bash\n"
        "h() {\n  [ -n \"$x\" ] && echo yes\n  echo done\n}\n"          # 中部 `&&`：无害，不报
        "k() {\n  if [ -n \"$x\" ]; then\n    echo yes\n  fi\n  return 0\n}\n"
        "m() {\n  [ -n \"$x\" ] && echo yes\n  if [ -n \"$x\" ]; then printf 'a'; else printf 'b'; fi\n}\n"  # 块尾，退出码不来自 `&&`
    )
    assert bang_tail_hits(good) == [], f"对照形态被误报：{bang_tail_hits(good)}"

    total = sum(len(function_tails(p.read_text(encoding="utf-8"))) for p in SCRIPTS_DIR.glob("*.sh"))
    assert total >= 20, f"射程内只解析出 {total} 个函数 —— 扫描器可能整体失效（假绿），先修它"

    # 事故本体必须真被扫到：`dev-worktree.sh` 的 `lock_list` 在射程内（否则判据 1 的绿无抓手）。
    tails = function_tails(SCRIPT.read_text(encoding="utf-8"))
    assert "lock_list" in tails, "`lock_list` 没被解析到 ⇒ 消费者不在射程内"
    assert tails["lock_list"].strip() == "return 0", f"`lock_list` 末命令 = {tails['lock_list'].strip()!r}（应为 return 0）"
