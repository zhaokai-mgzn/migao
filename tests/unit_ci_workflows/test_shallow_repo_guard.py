# case_ids: MC-371
"""浅仓污染（issue #9081）：`doctor` 的浅仓自检 + 「深度拉取必须登记」台账式元守卫。

## 病灶（2026-11-23 实测，不是理论风险）

某个并行子包/会话在**共享 clone** 上跑过一次 `git fetch --depth` / `--shallow-since` ⇒ 共享
`.git/shallow` 被写 ⇒ **整个 clone 变浅**（`.git/shallow` 是 clone 级别的属性，**不在任何 worktree 里**，
所有 worktree 共享同一个 common git dir）⇒ 浅仓下 `git merge-base` / `git rev-list --is-ancestor` /
`git cherry` **静默给出错误答案**（不报错）。

当天读数：`git rev-list --count origin/main` = **9**（正常 4800+）、`git merge-base 748575d43 origin/main`
无结果、`git merge` 报 `fatal: refusing to merge unrelated histories` —— 并据此差点得出
「main 历史被重写」的错误结论。修法：`git fetch --unshallow origin` ⇒ `origin/main` 恢复 4873 个提交。
⇒ 本文件钉的是「**病根入口**（深度拉取）+ **开工哨兵**（浅仓自检）」两道闸，每条都带注入式红证。

## 判据与红证（红证都真的跑一遍，不是叙述）

| # | 判据 | 红证（注入形态） |
|---|---|---|
| 1 | 浅仓夹具上 `doctor` **非零退出**、**点名 `.git/shallow`**、并给出口 `git fetch --unshallow origin` | 把 `wt_shallow_doctor` 的调用摘掉 ⇒ 同一夹具**转绿**（`test_the_doctor_check_is_what_makes_it_red`）；证明判据 1 的红来自这条检查本身 |
| 2 | `git fetch --unshallow` 之后同一夹具**转绿**（不是恒红 —— 恒红的判据同样没用） | 同判据 1（红/绿两面都要有读数） |
| 3 | 读不到浅仓状态 ⇒ 退出码 **`3` 无法判定**，**不得当 0 读** | 非 git 目录里跑 `doctor` |
| 4 | 这条检查**不进**开工路径（`wt_registry_assert_for_entry` 体内不许出现它） | 往体内加一行调用 ⇒ 判据具名红 |
| 5 | 仓库**执行面**里任何「改 clone 形状的拉取」（`git fetch`/`pull` + `--depth` / `--shallow-since` / `--shallow-exclude` / `--filter`）**必须登记**；台账**不腐烂**（0 命中 / 命中数变了 ⇒ 红） | 在临时副本里注一条未登记的 ⇒ **具名**红 |
| 6 | 禁止面写进了 `AGENTS.md`（含出口命令与台账路径） | ——（文档面，判据 = 关键词必须在场） |

## 覆盖不到什么（照实登记，§19.1）

- ❌ **管不住「谁在命令行里手敲了一次」**：本判据只守**仓库脚本面**（`scripts/**`、仓库根 `*.sh`、
  `.github/workflows/**`、`.github/scripts/**`）；人类/agent 在终端里临时敲的 `git fetch --depth=1`
  不在任何静态面上。那一段靠 `doctor` 的哨兵**事后**发现（判据 1）。
- ❌ **`git clone --depth` 不在射程**：它建的是**新**仓，不写共享 `.git/shallow`（病只在 `fetch`/`pull`
  改既有 clone 形状）；`actions/checkout` 的 `fetch-depth` / `filter` 同理（临时 CI 检出，藏在 runner 里回收）。
- ❌ **`tests/**` 不在扫描面**：判据夹具只跑 tmp 临时仓（`file://` 深克隆不写共享 `.git`），其中出现的
  命令串是**样本 / 断言引用**，不是对共享 clone 的拉取。这条边界写在台账 `_scope.excluded` 里，**不是**静默豁免。
- ❌ **判不了「历史上已经被污染的 clone」**：`doctor` 只在有人跑它时说话；本包不装 cron（铁律 10）。
- ❌ 只跑定点：不跑 `verify-all.sh gate` / 全量 pytest（重活串行，见 `migao-dev-flow` §27）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev-worktree.sh"
AGENTS = REPO_ROOT / "AGENTS.md"
LEDGER = REPO_ROOT / "tests" / "unit_ci_workflows" / "shallow_fetch_ledger.json"
GIT = shutil.which("git")

#: 浅仓判定函数名（`doctor` 的唯一挂载点）。
SHALLOW_FN = "wt_shallow_doctor"
#: 开工路径上的前置断言函数（浅仓**不许**挂进它 —— issue #9081 要的是「开工自检」，不是阻断开工）。
ENTRY_ASSERT_FN = "wt_registry_assert_for_entry"
#: `doctor` 输出里必须出现的两样东西：**点名病灶** + **出口命令**。
NAMED_SHALLOW_FILE = ".git/shallow"
EXIT_COMMAND = "git fetch --unshallow origin"
#: 三态的具名读数（「无法判定」不许长得像「通过」）。
INDETERMINATE_MARK = "不当成通过"
ALL_HISTORY_MARK = "全史仓库"

#: 会被扫的执行面（`tests/**` 与 `.github/cases/**` 的边界理由见台账 `_scope.excluded`）。
SCAN_ROOTS = ("scripts/", ".github/workflows/", ".github/scripts/")
SCAN_SUFFIXES = (".sh", ".bash", ".py", ".yml", ".yaml", ".js", ".mjs")
#: 注释行前缀 —— 「只写在注释里」必须能与真执行区分（实测 `pr-check.yml` 里就有一句注释提及 depth）。
COMMENT_PREFIXES = ("#", "//")
#: 形状改变型拉取：`git ... fetch|pull ... --depth/--shallow-since/--shallow-exclude/--filter`。
SHAPE_PATTERN = re.compile(
    r"git\b[^\n]*?\b(?:fetch|pull)\b[^\n]*?(?:--depth|--shallow-since|--shallow-exclude|--filter)"
)
#: 台账条目必填字段（缺任一项 ⇒ 红：登记了却说不清「为什么不可避免」等于没登记）。
REQUIRED_ENTRY_FIELDS = ("file", "purpose", "why_unavoidable", "evidence_anchor", "hits")


# ── 纯函数：扫描 / 判定本体（可在内存里注入，不依赖仓内文件）───────────────────
def in_scan_scope(rel: str) -> bool:
    """`rel`（仓库相对路径）是否落在**执行面**扫描范围内。"""
    if rel.startswith(("tests/", ".github/cases/")):
        return False
    if "/" not in rel:  # 仓库根脚本（如 check-ui-regression.sh / verify-all.sh）
        return rel.endswith((".sh", ".bash"))
    return rel.endswith(SCAN_SUFFIXES) and any(rel.startswith(r) for r in SCAN_ROOTS)


def count_shape_changing_fetches(text: str) -> int:
    """数「真执行」的形状改变型拉取（整行注释不算 —— 说明文字不是拉取）。"""
    return sum(
        1
        for line in text.splitlines()
        if not line.strip().startswith(COMMENT_PREFIXES) and SHAPE_PATTERN.search(line)
    )


def ledger_violations(sources: dict[str, str], ledger: dict) -> list[str]:
    """判定本体：未登记即红 + 台账不腐烂（双向核）。返回**具名**问题清单，空 = 绿。"""
    problems: list[str] = []
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        return ["台账缺 `entries` 数组（fail-closed：判据对象没了，不许当成通过）"]
    registered: dict[str, dict] = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"台账第 {i + 1} 条不是对象")
            continue
        missing = [f for f in REQUIRED_ENTRY_FIELDS if not entry.get(f)]
        if missing:
            problems.append(f"台账条目 {entry.get('file') or f'第 {i + 1} 条'} 缺字段 {missing}")
        rel = entry.get("file")
        if isinstance(rel, str) and rel:
            if not in_scan_scope(rel):
                problems.append(f"台账条目 {rel} 不在扫描面内 ⇒ 陈旧登记，只许缩短")
            registered[rel] = entry

    live = {rel: count_shape_changing_fetches(text) for rel, text in sources.items()}
    live = {rel: n for rel, n in live.items() if n}
    for rel, n in sorted(live.items()):
        if rel not in registered:
            problems.append(
                f"未登记的深度拉取：{rel}（{n} 处）—— 会写**共享** `.git/shallow`，"
                f"必须登记进 {LEDGER.relative_to(REPO_ROOT)} 并写清「为什么不可避免」"
            )
        elif registered[rel].get("hits") != n:
            problems.append(
                f"台账条目 {rel} 的命中数登记为 {registered[rel].get('hits')}，现取 {n} "
                f"⇒ 新加的深度拉取必须同批改台账并写理由（台账只许缩短，不许悄悄长）"
            )
    for rel in sorted(set(registered) - set(live)):
        problems.append(f"台账条目 {rel} 在仓里 0 命中 ⇒ 陈旧登记，只许缩短（删掉它）")
    return problems


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
    """去掉**注释行**与空行后的可执行行 —— 「只写在注释里」必须能被判出来。"""
    return [s for s in (raw.strip() for raw in body.splitlines()) if s and not s.startswith("#")]


def entry_assert_calls_shallow_check(src: str) -> bool:
    """开工路径的前置断言里是否（错误地）挂上了浅仓判定。"""
    return any(SHALLOW_FN in line for line in executable_lines(function_body(src, ENTRY_ASSERT_FN)))


# ── 真仓读数（坐标纪律：只读 HEAD 里的已跟踪文件，不猜路径、不读别的快照）────────
def repo_sources() -> dict[str, str]:
    """扫描面内的**全部已跟踪文件** → 源码文本（现取，新增脚本自动进面）。"""
    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout.split("\0")
    return {
        rel: (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for rel in sorted(filter(None, listed))
        if in_scan_scope(rel)
    }


def load_ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


# ── fixture：**自己在临时目录里造裸仓**（绝不依赖本仓、绝不碰本仓 .git）──────────
def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True, text=True)


def build_shallow_fixture(base: Path, *, script_text: str | None = None) -> dict:
    """造「临时裸仓 + 源仓 + `--depth=1` 浅克隆」，浅克隆里带上**真脚本**（或其注入变体）。

    `script_text=None` ⇒ 现役脚本逐字节副本；非 None ⇒ 注入变体（**红证的唯一入口**）。
    """
    live = SCRIPT.read_text(encoding="utf-8")
    text = live if script_text is None else script_text
    if script_text is not None and text == live:
        raise AssertionError("注入没生效（变体与现役脚本逐字相同）⇒ 下面的判红会变成空断言")

    src = base / "src"
    (src / "scripts").mkdir(parents=True)
    script = src / "scripts" / "dev-worktree.sh"
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    (src / "README.md").write_text("init\n", encoding="utf-8")
    _git(src, "init", "-q")
    _git(src, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(src, "config", "user.email", "t@example.invalid")
    _git(src, "config", "user.name", "t")
    _git(src, "add", "README.md", "scripts/dev-worktree.sh")
    _git(src, "commit", "-qm", "init")
    # 第二个提交 ⇒ `--depth=1` 才留下一个**真实的** shallow 边界
    (src / "README.md").write_text("init\nsecond\n", encoding="utf-8")
    _git(src, "add", "README.md")
    _git(src, "commit", "-qm", "second")

    bare = base / "origin.git"
    _git(base, "init", "--bare", "-q", str(bare))
    # 裸仓自己的 HEAD 默认指向 `master` ⇒ 不对齐到 `main` 会克隆出一个**空**仓库（`--depth` 随之失效）
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(src, "push", "-q", str(bare), "main")

    clone = base / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth=1", f"file://{bare}", str(clone)],
        check=True, capture_output=True, text=True,
    )
    return {"base": base, "bare": bare, "src": src, "clone": clone, "script_text": text}


def run_doctor(target: Path, *args: str) -> subprocess.CompletedProcess:
    """在 `target` 里跑它自己的 `scripts/dev-worktree.sh`（`target` 必须是 git 仓或纯目录）。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("MIGAO_WT_")}
    script = target / "scripts" / "dev-worktree.sh"
    return subprocess.run(
        ["bash", str(script), "doctor", *args],
        capture_output=True, text=True, env=env, timeout=300, cwd=str(target),
    )


# ── 判据 1/2：浅仓 ⇒ 红且点名；unshallow ⇒ 转绿 ────────────────────────────────
def test_a_shallow_clone_makes_doctor_red_and_names_the_shallow_file(tmp_path):
    fx = build_shallow_fixture(tmp_path)
    clone = fx["clone"]
    assert (clone / ".git" / "shallow").is_file(), "夹具不是浅克隆 ⇒ 后面的判红是空断言"
    shallow_before = _git(clone, "rev-parse", "--is-shallow-repository").stdout.strip()
    assert shallow_before == "true", f"夹具的浅仓读数不是 true 而是 {shallow_before!r}"

    red = run_doctor(clone)
    assert red.returncode != 0, (
        f"浅仓下 `doctor` 竟然返回 0（这就是「静默失真」本身）\nstdout:\n{red.stdout}"
    )
    out = red.stdout + red.stderr
    assert NAMED_SHALLOW_FILE in out, f"`doctor` 没点名 {NAMED_SHALLOW_FILE}\n输出:\n{out}"
    assert EXIT_COMMAND in out, f"`doctor` 没给出口 `{EXIT_COMMAND}`\n输出:\n{out}"

    # 判据 2：出口命令真的能修好，且修好后**转绿**（不是恒红）
    _git(clone, "fetch", "--unshallow", "origin")
    after = _git(clone, "rev-parse", "--is-shallow-repository").stdout.strip()
    assert after == "false", f"`{EXIT_COMMAND}` 之后仍是浅仓（读数 {after!r}）"
    green = run_doctor(clone)
    assert green.returncode == 0, (
        f"全史仓库下 `doctor` 仍非零（{green.returncode}）⇒ 判据恒红，没有判别力\n"
        f"stdout:\n{green.stdout}"
    )
    assert ALL_HISTORY_MARK in green.stdout, f"转绿时没有具名读数 `{ALL_HISTORY_MARK}`\n{green.stdout}"


def test_the_doctor_check_is_what_makes_it_red(tmp_path):
    """注入式红证：摘掉 `wt_shallow_doctor` 的调用 ⇒ **同一浅仓夹具转绿**。"""
    live = SCRIPT.read_text(encoding="utf-8")
    call_line = "    rc_shallow=0;  wt_shallow_doctor || rc_shallow=$?"
    assert call_line in live, (
        "定位 `doctor` 里的浅仓判定调用失败（锚点漂移）⇒ 本红证会因为「注入没落上」而失效"
    )
    mutated = live.replace(call_line, "    rc_shallow=0", 1)
    assert call_line not in mutated, "注入没落上（变体里仍留着那行调用）⇒ 红证会变成空断言"

    fx = build_shallow_fixture(tmp_path, script_text=mutated)
    assert (fx["clone"] / ".git" / "shallow").is_file(), "夹具不是浅克隆 ⇒ 本红证无意义"
    res = run_doctor(fx["clone"])
    assert res.returncode == 0, (
        f"摘掉浅仓判定后 `doctor` 仍非零（{res.returncode}）⇒ 那个红不是本检查造成的，"
        f"判据 1 归因错误\nstdout:\n{res.stdout}"
    )
    assert NAMED_SHALLOW_FILE not in (res.stdout + res.stderr), (
        "摘掉判定后仍有 `.git/shallow` 的具名读数 ⇒ 注入没落上"
    )


# ── 判据 3：读不到 ⇒ 3（无法判定，不得当 0 读）─────────────────────────────────
def test_unreadable_shallow_state_is_indeterminate_not_green(tmp_path):
    plain = tmp_path / "not-a-repo"
    (plain / "scripts").mkdir(parents=True)
    script = plain / "scripts" / "dev-worktree.sh"
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(0o755)
    res = run_doctor(plain)
    assert res.returncode == 3, (
        f"非 git 目录下 `doctor` 的退出码是 {res.returncode}（期望 3 = 无法判定，**不得当 0 读**）\n"
        f"stdout:\n{res.stdout}"
    )
    assert INDETERMINATE_MARK in res.stdout, f"无法判定时没有出声（缺 `{INDETERMINATE_MARK}`）\n{res.stdout}"


# ── 判据 4：浅仓检查**不进**开工路径（否则会阻断正常开工）──────────────────────
def test_the_shallow_check_is_not_on_the_startup_assertion_path():
    src = SCRIPT.read_text(encoding="utf-8")
    body = function_body(src, ENTRY_ASSERT_FN)
    assert "前置自查（worktree 登记表 × 磁盘" in body, (
        f"`{ENTRY_ASSERT_FN}` 的函数体里没有它自己的具名输出 ⇒ 取到的可能不是那个函数（fail-closed）"
    )
    offpath = [line for line in executable_lines(body) if SHALLOW_FN in line]
    assert offpath == [], (
        f"浅仓判定被挂进了开工路径 `{ENTRY_ASSERT_FN}`（{offpath}）⇒ 一个浅仓会让 `add`/`rm`/`rebase` "
        f"全部拒绝开工；issue #9081 要的是「开工自检」，不是 fail-closed 阻断"
    )


# ── 判据 5：元守卫（未登记即红 / 台账不腐烂），含注入式红证 ──────────────────────
def test_unregistered_shape_changing_fetch_is_named_red():
    ledger = {"entries": [{"file": "scripts/ok.sh", "purpose": "p", "why_unavoidable": "w",
                           "evidence_anchor": "e", "hits": 1}]}
    baseline = {"scripts/ok.sh": 'git fetch --depth=1 origin main --quiet\n'}
    assert ledger_violations(baseline, ledger) == [], "对照形态就判红 ⇒ 判据没有判别力"

    injected = dict(baseline)
    injected["scripts/new-tool.sh"] = "#!/bin/bash\ngit fetch --shallow-since=2026-11-01 origin\n"
    problems = ledger_violations(injected, ledger)
    assert any("未登记的深度拉取：scripts/new-tool.sh" in p for p in problems), (
        f"注入未登记的深度拉取后没有**具名**判红：{problems}"
    )

    grown = dict(baseline)
    grown["scripts/ok.sh"] = baseline["scripts/ok.sh"] + "git fetch --filter=blob:none origin\n"
    assert any("scripts/ok.sh" in p and "现取 2" in p for p in ledger_violations(grown, ledger)), (
        "已在台账里的文件**悄悄多一处**深度拉取时没判红 ⇒ 台账可以被当成免死金牌"
    )

    stale = {"scripts/other.sh": "echo hi\n"}
    assert any("scripts/ok.sh" in p and "0 命中" in p for p in ledger_violations(stale, ledger)), (
        "台账里 0 命中的陈旧条目没判红 ⇒ 台账只许缩短的纪律没有牙齿"
    )

    thin = {"entries": [{"file": "scripts/ok.sh", "hits": 1}]}
    assert any("缺字段" in p for p in ledger_violations(baseline, thin)), (
        "登记了却不写「为什么不可避免」也算过 ⇒ 台账退化成一张名单"
    )


def test_the_repo_ledger_covers_the_live_script_surface():
    ledger = load_ledger()
    scope_excluded = ledger.get("_scope", {}).get("excluded")
    assert isinstance(scope_excluded, dict) and scope_excluded, (
        "台账没写 `_scope.excluded`（扫描面外的边界必须**出声**登记，不是静默豁免）"
    )
    sources = repo_sources()
    assert len(sources) > 20, f"扫描面只取到 {len(sources)} 个文件 ⇒ 扫描面塌了，判据变空断言"
    problems = ledger_violations(sources, ledger)
    assert problems == [], "仓库执行面与台账不一致：\n" + "\n".join(problems)
    # 反证：台账不是空的（可空的台账 = 恒绿）
    live_hits = {rel for rel, text in sources.items() if count_shape_changing_fetches(text)}
    registered = {e["file"] for e in ledger["entries"]}
    assert live_hits == registered, f"台账 {sorted(registered)} 与现取命中 {sorted(live_hits)} 不同"


# ── 判据 6：文档面（禁止 + 出口 + 台账路径都在场）──────────────────────────────
def test_agents_md_documents_the_prohibition_and_the_exit():
    body = AGENTS.read_text(encoding="utf-8")
    for needle in ("禁止深度拉取", ".git/shallow", EXIT_COMMAND, "shallow_fetch_ledger.json"):
        assert needle in body, f"`AGENTS.md` 缺 `{needle}` ⇒ 下一个人不知道这条禁令（issue #9081 第 3 条）"
