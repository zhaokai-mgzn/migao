# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012，见同目录
#   `test_gate_coverage_and_same_source.py` 头部的同款声明。本 PR 不新建用例族：仓库没有「开发工具链」
#   用例族，塞进行为用例库会污染覆盖矩阵；且 case-trust 的 burn-down 要求每个 PR 净消减 ≥1 条。）
r"""本地门禁覆盖矩阵 + bmini 腿接线守卫（issue #4221 族；本单新增 bmini 腿）。

## 病根（实测读数，不是推断）

`frontend/bmini-app`（Taro 一源双编译，B 端 h5 + 小程序）在 `./verify-all.sh` 里**没有任何腿**：
改 bmini 的包在本地拿不到 `tsc --noEmit` / `jest` / `build:h5` / `build:weapp` 的自动覆盖 ⇒
只能手工跑（最近两个 bmini 包的回报里逐字写着「手工跑了三条」）；而 CI 侧有两条腿
（`.github/workflows/bmini-app.yml` 的 `bmini-app typecheck + unit tests` 与
`bmini-app build (h5 + weapp)`）⇒ **缺口只在本地**，代价 = 一轮 CI 往返。

**类**（本判据的类级视角）= 「某个模块被改动，但本地门禁矩阵里没有它的腿 ⇒ 只能靠 CI 兜」。
故本文件把「模块 → 本地哪一档 / 哪条腿 / 覆盖形态」变成一张**具名登记的矩阵**
（`local_gate_matrix.json`，`_judged_by` 指向本文件），并机械核对：

| # | 判据 | 红证（怎么让它**单独**变红） |
|---|---|---|
| C1 | 模块**发现**（口径冻结在本文件）⊆ 登记 | 造一个 `frontend/zz-ghost/` 目录 ⇒ 判据**指名**它 |
| C2 | 登记 ⊆ 发现（陈旧即红） | 登记一个不存在的模块 ⇒ 红 |
| C3 | 登记的腿**活着**：腿名逐字出现在 `verify-all.sh` 的派发分支里，且**声称的档位 == 腿名实际出现的档位集合** | 把 bmini 腿从 gate 分支删掉 ⇒ 红 |
| C4 | `fail-closed` 条目必须走 `report_strict`（**不是** `report_env` 的「未就绪跳过」那条路）；该分支要显式声明「未跑」且不得出现 ✅ | 把 `report_strict` 换成 `report_env` ⇒ 红 |
| C5 | **触发面闭包**：谓词必须命中模块目录本身；模块源码里逃到本模块之外的**仓内输入**必须被谓词命中，或登记在 `trigger_face_uncovered_inputs` | 新增一个 `../` 逃逸字面量（临时树）⇒ 红；谓词收窄 ⇒ 红 |
| C6 | 未覆盖台账**只许缩短**（上限冻结在本文件）+ 每条带 reason/issue/owner + 条目**活着**（未覆盖模块要能指认兜它的 CI 腿） | 加一条未覆盖模块 ⇒ 超上限即红 |
| C7 | **行为**：缺依赖 ⇒ fail-closed（❌ + 非零，**不是** ⏭️）；命中触发面 ⇒ 腿被派发；未命中 ⇒ 不派发、且打印「未跑」 | 藏掉 `node_modules` 后跑 harness ⇒ 必须 ❌；谓词收窄 ⇒ 不派发 |
| C8 | 与 CI **逐字一致**：本地腿的四条命令 == CI 两条腿的 `run` 原文（现取 YAML），且本地按同序执行 | 改一条命令（`build:h5` → `build:swan`）⇒ 红 |
| C9 | **快循环档的 fail-closed**（`kind=diff-face-gated-deps`，本单新增）：五条模块腿必须由 `report_gated` 在档位分支**顶层无条件**派发（命中 ⇒ `report_strict`、未命中 ⇒ `report_env`）；行为三态 = 命中+缺依赖 ⇒ ❌/`FAIL=1`、未命中+缺依赖 ⇒ ⏭️/`READY=1`（**不计通过**）、命中+就绪 ⇒ 照旧真跑（**覆盖强度不变**） | 换回 `report_env` ⇒ 红；把腿套进 `if` ⇒ 红；未命中时静默 ✅ ⇒ 红；`if face_hit` 改成 `if false` ⇒ 红 |
| C10 | **覆盖面登记与事实自洽**：`fail_closed_scope` 要写明「改了什么 / 没改什么 / 覆盖不到什么」，且「redproof 档 9 条实跑腿**未**门控」这一条被**现取**钉住（条数 + 该档无 `report_gated`/`report_strict`） | 把 redproof 某条腿改走 strict ⇒ 红；条数不符 ⇒ 红；删掉登记块 ⇒ 红 |

## 判别力自证（变异**当场在内存/临时目录里构造**，不靠"改磁盘再改回来"）

每条红证都：① 断言变异真的生效（`mutated != src`）；② 断言**被变异的那份文本真的被读到**
（把变异后的文本喂给同一个判定函数，看它报出预期的条目）；③ 给「只改注释」的**对照读数**
（注释层改动不得让判据变红 —— 否则判据是被任何改动喂红的，不是被真形态喂红的）。

## 边界（明确的，不要把本判据读成覆盖面更大）

本判据机械保证「每个被发现的模块都被**显式裁定**」+「登记的腿真的活在它声称的档位里」+
「相对路径字面量形态的跨目录输入都被裁定过」+「快循环档那五条腿的『依赖缺』判定按变更集分派、
且派发是**无条件**的」；它**不保证覆盖强度**（一条弱腿与一条强腿在矩阵里
长得一样），**不保证**触发面 = 全部输入闭包（tsconfig paths / 运行期拼路径 / 环境变量指向的输入
不在面内 —— 假绿方向，不会误伤），也**不保证**「模块内的腿够不够」。
🔴 **C9/C10 只管一件事**：「依赖**缺**时记 ❌ 还是 ⏭️」——它们**不改覆盖强度**（依赖齐备时这些腿照旧
每次都跑；判据读的是**接线与派发深度**，不判腿的强弱），也不改任何档位 / 命令 / CI 面。
覆盖不到的面逐条登记在台账 `fail_closed_scope.not_covered`（redproof 档实跑腿未门控 · 闭包形态 ·
「装了但装错」· CI 侧）。
自查清单（可复制）：
`python3 -m pytest tests/unit_ci_workflows/test_local_gate_matrix.py -q -s`。
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "verify-all.sh"
LEDGER_PATH = Path(__file__).resolve().parent / "local_gate_matrix.json"
BMINI_WORKFLOW = REPO / ".github" / "workflows" / "bmini-app.yml"
BMINI = "frontend/bmini-app"

#: 触发面登记的**两种**形态（C5 的输入闭包对两者都判；派发形态见各自的 C 行）：
#: · `diff-face-hit`（bmini 范式，gate 档）：**腿本身**按变更集派发 —— 未命中 ⇒ 不派发 + 显式「未跑」；
#: · `diff-face-gated-deps`（本单新增，快循环档）：腿**照旧每次都跑**（覆盖强度不变），
#:   只有「依赖**缺**」这一态的判定按变更集分派（命中 ⇒ ❌ fail-closed / 未命中 ⇒ ⏭️ 未就绪）。
#: ⚠️ 两者都要求 `fail_closed: true` —— 登记的意义就是「这条腿不许静默绿」。
FACE_TRIGGER_KINDS = ("diff-face-hit", "diff-face-gated-deps")
#: 档位分支里每行的控制流**开体 / 闭体**（只做词法配对：判据要的是「这条腿在不在条件里」）。
_OPEN_RE = re.compile(r"^\s*(?:if|for|while)\b")
_CLOSE_RE = re.compile(r"^\s*(?:fi|done)\b")

#: 快循环档 fail-closed 三态读数用的变更集（命中 / 未命中 `frontend/ai-agent-service` 的触发面，
#: 都由**脚本里真实的谓词**判定 —— 不是喂给判据的常量）。
GATED_HIT_PATH = "backend/ai-agent-service/app/graph.py"
GATED_MISS_PATH = "frontend/worker-h5/src/render.mjs"
GATED_ENV = "ai-agent"
GATED_FACE_FN = "ai_agent_face_paths"

#: 模块**发现**口径（本文件冻结）：`backend/*` 与 `frontend/*` 的第一层目录（不以 `.` 开头）。
#: 用「目录」而不是「有 package.json 的目录」：worker-h5 / shared 没有声明物却**有腿 / 有消费方**，
#: 按标记文件发现会把它们变成幽灵（登记了却"不存在"）。
MODULE_ROOTS = ("backend", "frontend")
#: 覆盖形态的**冻结**枚举（自由文本无法核对 ⇒ 形态必须是可枚举的词）。
FORMS = ("typecheck", "单测", "构建")
#: 档位 = verify-all.sh 顶层 `case "$MODE" in` 的分支名（矩阵声称的档位必须落在其中）。
TIERS = ("quick", "full", "frontend", "backend", "agent", "gate", "redproof")
#: 未覆盖台账的**现取**上限（只许缩短）：要加一条必须在本文件里显式改这个数（diff 里看得见）。
UNCOVERED_MODULE_CAP = 1
UNCOVERED_INPUT_CAP = 1
NON_MODULE_CAP = 0
#: 输入闭包的扫描面（只认这些扩展名里的相对路径字面量；二进制/产物不在面内）。
SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json")
_REL_SPEC_RE = re.compile(r"""["']((?:\.\./)+[^"'\s]+)["']""")
_RUN_TIMEOUT = 180

# CI `bmini-app.yml` 两条腿的 **run 原文**（按步骤顺序）—— 本地腿必须与这四条逐字一致，
# 不许自创第三套口径（CI 改了命令而这里没跟 ⇒ 本判据红）。
# 「逐字一致」= 同源声明：判据 = 本文件 :: test_local_leg_commands_match_ci（现取 YAML 逐条比对）。
CI_LEG_COMMANDS = (
    "npx tsc --noEmit",
    "npm test",
    "npm run build:h5",
    "npm run build:weapp",
)


# ══════════════════════════════════════════════════════════════════════════════
# 读法：shell 脚本的代码行 / 函数体 / 档位分支（沿用同目录既有守卫的形态，不另立一套）
# ══════════════════════════════════════════════════════════════════════════════


def _code_of(text: str) -> str:
    """剥掉行内注释后的**代码行**（注释里会引用这些写法，裸 grep 会假绿，#5477 同族）。

    ⚠️ **不许**写成朴素截断（先按井号切一刀取前段，未考虑引号）：字符串字面量里出现井号时它会把
    **行尾**一起吃进"注释" ⇒ 判据读到的"代码"比真实代码短（**假绿方向**，属 `#5323` 那一族）。
    这正是元守卫 `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py` 的
    `naive-hash-cut` 面，其台账（`guard_parsing_allowlist.json`）明写「**新增**原文口径解析
    **不许**靠往台账加条目吸收 —— 必须改走语法单元，或**先剥注释与字符串**（顺序不许反）」。
    故本函数走**引号状态机**：只在**引号之外**把 `#` 当注释起点（`echo "a#b"` 里的 `#` 保留）。
    """
    out = []
    for line in text.splitlines():
        quote = ""
        cut = len(line)
        i = 0
        while i < len(line):
            ch = line[i]
            if quote:
                if ch == "\\" and quote == '"':   # 双引号内的转义不结束字符串
                    i += 2
                    continue
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch == "#":
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


def _extract(text: str, name: str) -> str:
    """抽出 `name() { ... }` 的函数体（结束于第 0 列的 `}`）；抽不到 = fail-closed 报错。"""
    m = re.search(rf"^{name}\(\) \{{[\s\S]*?^\}}", text, re.M)
    assert m, f"未能从 verify-all.sh 抽出 {name}() —— 结构变了就同步更新本守卫"
    return m.group(0)


def _mode_branch(text: str, mode: str) -> str:
    """抽出顶层 `case "$MODE" in` 里 `mode)` 分支的代码（到 `;;` 为止，已剥注释）。"""
    lines = _code_of(text).splitlines()
    start = next((i for i, ln in enumerate(lines) if 'case "$MODE" in' in ln), -1)
    assert start >= 0, 'verify-all.sh 里找不到顶层 `case "$MODE" in`'
    for i in range(start, len(lines)):
        if lines[i].strip() == f"{mode})":
            body = []
            j = i + 1
            while j < len(lines) and lines[j].strip() != ";;":
                body.append(lines[j])
                j += 1
            assert j < len(lines), f"`{mode})` 分支没有被 `;;` 结束"
            return "\n".join(body)
    raise AssertionError(f"verify-all.sh 顶层 case 里找不到 `{mode})` 分支")


def _ledger() -> dict:
    """矩阵台账（缺文件 ⇒ fail-closed 抛错：缺台账 = 覆盖无人管，不是「无需登记」）。"""
    assert LEDGER_PATH.is_file(), (
        f"本地门禁覆盖矩阵台账不存在：{LEDGER_PATH} —— 本判据 fail-closed"
        "（缺台账 ≠ 无需登记：模块的本地覆盖面必须有人裁定并在 diff 里可见）"
    )
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _mutate(text: str, old: str, new: str) -> str:
    """在**内存里**构造变异形态（不碰磁盘）：定位失败 / 变异未生效都 fail-closed。"""
    assert old in text, f"变异锚点不在文本里（fail-closed，锚点随重构漂移）：{old!r}"
    mutated = text.replace(old, new, 1)
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 该红证是空断言）"
    return mutated


def _run(code: str, *, cwd: Path = REPO, env: dict = None) -> subprocess.CompletedProcess:
    import os

    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(
        ["bash", "-c", code], capture_output=True, text=True, env=e,
        cwd=str(cwd), timeout=_RUN_TIMEOUT,
    )


# ══════════════════════════════════════════════════════════════════════════════
# C1/C2/C6：登记面（发现 ⊆ 登记 ⊆ 发现）+ 未覆盖台账只许缩短
# ══════════════════════════════════════════════════════════════════════════════


def discovered_modules(repo: Path = REPO) -> list[str]:
    """现取模块清单（口径见 `MODULE_ROOTS` 注释）。临时树同样适用（红证要在临时树上跑）。"""
    out: list[str] = []
    for root in MODULE_ROOTS:
        base = repo / root
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if p.is_dir() and not p.name.startswith("."):
                out.append(f"{root}/{p.name}")
    return out


def registration_problems(ledger: dict, discovered: list[str], repo: Path = REPO) -> list[str]:
    """C1/C2/C6：未登记即红 / 陈旧即红 / 台账条目形态与上限。**纯函数**（红证直接喂变异台账）。"""
    problems: list[str] = []
    modules = ledger.get("modules") or {}
    uncovered = ledger.get("uncovered_modules") or {}
    non_modules = ledger.get("non_modules") or {}
    registered = set(modules) | set(uncovered) | set(non_modules)
    for rel in sorted(set(discovered) - registered):
        problems.append(
            f"模块 {rel} **未登记**本地覆盖面（矩阵 {LEDGER_PATH.name}）："
            "出口 = ① 有本地腿 ⇒ 登记进 modules（tiers / leg_names / forms）；"
            "② 没有本地腿 ⇒ 登记进 uncovered_modules（reason + issue + owner + 兜它的 CI 腿）；"
            "③ 确实不是模块 ⇒ 登记进 non_modules（并显式抬高 NON_MODULE_CAP）"
        )
    for rel in sorted(registered - set(discovered)):
        problems.append(f"登记项 {rel} 已陈旧（仓库里没有这个模块目录）⇒ 销账（台账只许缩短）")
    if len(uncovered) > UNCOVERED_MODULE_CAP:
        problems.append(
            f"未覆盖模块 {len(uncovered)} 条 > 现取上限 {UNCOVERED_MODULE_CAP} 条"
            "（只许缩短：要扩豁免面必须在同 PR 显式改本文件的 UNCOVERED_MODULE_CAP）"
        )
    if len(non_modules) > NON_MODULE_CAP:
        problems.append(
            f"「非模块目录」登记 {len(non_modules)} 条 > 现取上限 {NON_MODULE_CAP} 条"
            "（同上：扩面要显式改 NON_MODULE_CAP）"
        )
    frozen = ledger.get("uncovered_frozen") or {}
    live_counts = {
        "modules": len(uncovered),
        "trigger_face_uncovered_inputs": len(ledger.get("trigger_face_uncovered_inputs") or {}),
        "non_modules": len(non_modules),
    }
    for key, count in sorted(live_counts.items()):
        if frozen.get(key) != count:
            problems.append(
                f"uncovered_frozen.{key} = {frozen.get(key)!r} 与实际条数 {count} 不一致"
                "（涨跌都要在同 PR 更新这个现取读数）"
            )
    for rel, entry in sorted(modules.items()):
        for key in ("tiers", "leg_names", "forms"):
            if not entry.get(key):
                problems.append(f"{rel}：登记缺 {key!r}（覆盖面必须写清「哪一档 / 哪条腿 / 什么形态」）")
        for tier in entry.get("tiers") or []:
            if tier not in TIERS:
                problems.append(f"{rel}：档位 {tier!r} 不是 verify-all.sh 的档位（现取 {TIERS}）")
        for form in entry.get("forms") or []:
            if form not in FORMS:
                problems.append(f"{rel}：覆盖形态 {form!r} 不在冻结枚举 {FORMS} 里")
    return problems


def uncovered_problems(ledger: dict, repo: Path = REPO) -> list[str]:
    """C6/C6b：未覆盖台账每条要有人看（reason/issue/owner）+ 要能指认兜它的 CI 腿。"""
    problems: list[str] = []
    for rel, entry in sorted((ledger.get("uncovered_modules") or {}).items()):
        for key in ("reason", "issue", "owner"):
            if not entry.get(key):
                problems.append(f"uncovered_modules[{rel}] 缺 {key!r}（缺口不许匿名存在）")
        wf_rel = entry.get("ci_workflow") or ""
        wf = repo / wf_rel
        if not wf.is_file():
            problems.append(f"uncovered_modules[{rel}] 的 ci_workflow 不存在：{wf_rel!r}")
            continue
        data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        names = {(job or {}).get("name") or "" for job in (data.get("jobs") or {}).values()}
        for leg in entry.get("ci_leg_names") or []:
            if leg not in names:
                problems.append(
                    f"uncovered_modules[{rel}] 声明由 CI 腿 {leg!r} 兜，但 {wf_rel} 里没有这个 job name"
                    f"（现取 {sorted(n for n in names if n)}）—— 「靠 CI 兜」必须是真的"
                )
        if not entry.get("ci_leg_names"):
            problems.append(f"uncovered_modules[{rel}] 没写 ci_leg_names（未覆盖的出口必须点名）")
    return problems


# ══════════════════════════════════════════════════════════════════════════════
# C3/C4：登记的腿必须活在它声称的档位里；fail-closed 条目必须真走 report_strict
# ══════════════════════════════════════════════════════════════════════════════


def leg_problems(script_text: str, ledger: dict) -> list[str]:
    """**纯函数**：吃「脚本原文 + 台账」→ 问题清单（红证直接喂变异文本 / 变异台账）。"""
    problems: list[str] = []
    code = _code_of(script_text)
    branches = {mode: _mode_branch(script_text, mode) for mode in TIERS}
    declared_envs = set(re.findall(r"^\s{4}([A-Za-z0-9_-]+)\)", _extract(script_text, "probe_ready"), re.M))
    for rel, entry in sorted((ledger.get("modules") or {}).items()):
        actual_tiers = [m for m in TIERS if any(f'"{leg}"' in branches[m] for leg in entry.get("leg_names") or [])]
        for leg in entry.get("leg_names") or []:
            if f'"{leg}"' not in code:
                problems.append(
                    f"{rel}：登记的腿 {leg!r} 在 verify-all.sh 里**不存在**（腿名未逐字出现）—— "
                    "登记必须活着：要么把腿接回去，要么销账"
                )
        if sorted(actual_tiers) != sorted(entry.get("tiers") or []):
            problems.append(
                f"{rel}：声称的档位 {sorted(entry.get('tiers') or [])} != 腿名实际出现的档位 {sorted(actual_tiers)}"
                "（挪档位/改腿名必须同改台账）"
            )
        trigger = entry.get("trigger") or {}
        if trigger.get("kind") == "diff-face-gated-deps":
            problems += gated_trigger_problems(rel, entry, trigger, branches, declared_envs)
            continue
        if trigger and trigger.get("kind") not in FACE_TRIGGER_KINDS:
            problems.append(
                f"{rel}：trigger.kind={trigger.get('kind')!r} 不在冻结枚举 {FACE_TRIGGER_KINDS} 里"
                "（触发面形态必须可枚举 —— 否则本判据看不见它的射程）"
            )
            continue
        if trigger.get("kind") != "diff-face-hit":
            continue
        env = trigger.get("env") or ""
        hit_fn = trigger.get("hit_fn") or ""
        if env not in declared_envs:
            problems.append(f"{rel}：触发条目的 env {env!r} 未在 probe_ready() 里声明（未声明的 key ⇒ 运行时记脚本配置错误）")
        for mode in entry.get("tiers") or []:
            branch = branches[mode]
            if f"if {hit_fn}; then" not in branch:
                problems.append(f"{rel}：{mode} 档的派发没有按 `if {hit_fn}; then` 判定就派发（会卡住不碰该模块的 PR，或漏跑）")
            if f"report_strict {env} " not in branch:
                problems.append(
                    f"{rel}：{mode} 档没有用 `report_strict {env}` 派发 —— fail-closed 条目**不许**走 "
                    "report_env 的「未就绪 ⇒ ⏭️ 跳过」那条路（跳过会被读成通过）"
                )
            if f"report_env {env} " in branch:
                problems.append(f"{rel}：{mode} 档同时存在 `report_env {env}`（⏭️ 那条路）—— 两条路并存 ⇒ 缺依赖时行为不确定")
            if "未跑" not in branch:
                problems.append(f"{rel}：{mode} 档未命中触发面时必须显式声明「未跑」（不许静默 ✅）")
            if "✅" in branch:
                problems.append(f"{rel}：{mode} 档的「未命中」声明里出现 ✅ —— 「没跑」与「通过」必须可区分")
    return problems


def control_flow_depths(branch: str) -> list[tuple[int, str]]:
    """分支里每行的「**进入该行时**的控制流嵌套深度」（0 = 无条件区）。

    ⚠️ 只做**词法**配对（`if|for|while` 开体 / `fi|done` 闭体；`elif`/`else` 不改深度）——
    本判据要的不是完整 shell 解析，而是「这条腿**是不是被套在某个条件里**」（`FM-C` 族：
    判据不许自证，故这里判的是**派发语句的位置**，不是它的措辞）。
    """
    depth, out = 0, []
    for raw in branch.splitlines():
        out.append((depth, raw))
        if _OPEN_RE.match(raw):
            depth += 1
        elif _CLOSE_RE.match(raw):
            depth = max(0, depth - 1)
    return out


def gated_trigger_problems(rel: str, entry: dict, trigger: dict,
                           branches: dict, declared_envs: set) -> list[str]:
    """C9（静态）：`kind=diff-face-gated-deps` 的条目必须**逐档逐腿**由 `report_gated` 顶层派发。

    三条不变量：① 派发语句是 `report_gated <env> <predicate_fn> "<腿名>"`；
    ② 它落在**控制流深度 0**（不在任何 `if`/`for` 里 ⇒ 依赖齐备时照旧每次都跑 = 覆盖强度不变）；
    ③ 该 env key 已在 `probe_ready()` 里声明、且同一档位分支里**不许**再直写 `report_env`/`report_strict`
    （依赖缺时的判定必须**单点**表达，两条路并存 ⇒ 行为不确定）。
    """
    problems: list[str] = []
    face_fn = trigger.get("predicate_fn") or ""
    if trigger.get("hit_fn") != "face_hit":
        problems.append(
            f"{rel}：trigger.hit_fn 应为共享的 `face_hit`（现取 {trigger.get('hit_fn')!r}）—— "
            "A/B 两条路（命中判据）必须单点实现"
        )
    if trigger.get("fail_closed") is not True:
        problems.append(f"{rel}：trigger.fail_closed 必须显式为 true（登记的意义就是「这条腿不许静默绿」）")
    for leg in entry.get("leg_names") or []:
        # ⚠️ 逐腿的「活着」检查是**必须**的：C3 的档位判定是**条目级**的（`any(leg in branch)`）⇒
        #    同一模块的另一条腿还在时，把某一条腿的整行派发**删掉**它看不见（实测：删掉三档的
        #    admin-web tsc 派发行 ⇒ C3 全绿）。这里按「该腿至少在一个声称的档位里出现」兜住。
        present = [m for m in entry.get("tiers") or [] if f'"{leg}"' in branches[m]]
        if not present:
            problems.append(
                f"{rel}：腿 {leg!r} 在它声称的档位 {entry.get('tiers')} 里**一处都没有** —— "
                "要么派发行被删了（腿死了），要么档位声明陈旧（同改台账）"
            )
    for mode in entry.get("tiers") or []:
        branch = branches[mode]
        depths = control_flow_depths(branch)
        for leg in entry.get("leg_names") or []:
            if f'"{leg}"' not in branch:
                continue      # 该腿不在此档（逐腿「至少出现一次」已由上面那条兜住）
            pat = re.compile(
                rf'^[ ]{{4}}report_gated\s+(\S+)\s+{re.escape(face_fn)}\s+"{re.escape(leg)}"'
            )
            hits = [(d, ln) for d, ln in depths if pat.match(ln)]
            if not hits:
                problems.append(
                    f"{rel}：{mode} 档的腿 {leg!r} 不是由 `report_gated <env> {face_fn} \"{leg}\"`"
                    " 在**分支顶层**派发的 —— 依赖缺时的判定必须走 report_gated"
                    "（命中 ⇒ report_strict / 未命中 ⇒ report_env）"
                )
                continue
            depth, line = hits[0]
            if depth != 0:
                problems.append(
                    f"{rel}：{mode} 档的腿 {leg!r} 被套在条件里（控制流深度 {depth}）—— "
                    "快循环档的腿必须**无条件**派发（按变更集决定跑不跑 = 选择集变成失败开放，issue #3680）"
                )
            env = pat.match(line).group(1)
            if env not in declared_envs:
                problems.append(f"{rel}：{mode} 档派发用的 env key {env!r} 未在 probe_ready() 里声明")
            for other in ("report_env", "report_strict"):
                if f"{other} {env} " in branch:
                    problems.append(
                        f"{rel}：{mode} 档里同时存在 `{other} {env}` —— 依赖缺时的判定必须**单点**由"
                        " report_gated 表达（两条路并存 ⇒ 行为不确定）"
                    )
    return problems


def gated_wrapper_problems(script_text: str) -> list[str]:
    """C9（静态）：`report_gated()` 必须是「命中 ⇒ `report_strict` / 未命中 ⇒ `report_env`」的单点实现。

    就绪探测与逐检查项的 ⏭️ 标记**仍只属于** `report_env()`（三态单一实现）—— 包装里出现
    `probe_ready` 或 ⏭️ 都算它把三态拆散了。
    """
    problems: list[str] = []
    # ⚠️ 只看**代码行**：本判据自己就在包装的注释里写着 `probe_ready` / `⏭️`（说明单一实现的边界）
    #    ⇒ 不剥注释会把**说明文字**读成「包装自己探测/自己打标记」（`FM-A11` 举例即实例）。
    body = _code_of(_extract(script_text, "report_gated"))
    if 'if face_hit "$face_fn"; then' not in body:
        problems.append(
            "report_gated() 的命中判定不是 `if face_hit \"$face_fn\"; then` —— 形态变了就同步本判据"
            "（否则本判据看不见它的判定对象）"
        )
    for need, why in (("report_strict", "命中 ⇒ fail-closed（❌ + 可行动文案）"),
                      ("report_env", "未命中 ⇒ ⏭️ 未就绪（不计通过）")):
        if need not in body:
            problems.append(f"report_gated() 里没有 `{need}` —— {why} 这一半丢了")
    if "⏭️" in body:
        problems.append(
            "report_gated() 自己打了 ⏭️ —— 「逐检查项的未就绪标记」只能由 report_env() 打印"
            "（散到调用点/包装里 = 可绕过 probe_ready() 直接标跳过）"
        )
    if "probe_ready" in body:
        problems.append("report_gated() 自己探测运行环境 —— 就绪探测必须单一实现（report_env/report_strict 里）")
    return problems


def dispatch_stdout(script_text: str, change_set: str) -> str:
    """用**脚本里真实的 gate 档派发文本**跑一遍（report/report_strict 换替身，其余真函数）。"""
    harness = (
        "set -uo pipefail\n"
        f"CHANGE_SET={shlex.quote(change_set)}\n"
        + _extract(script_text, "bmini_face_paths") + "\n"
        + _extract(script_text, "bmini_face_hit") + "\n"
        + "gate_check() { return 0; }\n"
        + "cases_face_hit() { return 1; }\n"
        + "cases_face_gate() { return 0; }\n"
        + "redproof_face_hit() { return 1; }\n"
        + "redproof_preflight() { return 0; }\n"
        + 'report() { echo "REPORT $1"; }\n'
        + 'report_strict() { echo "STRICT $1 $2"; }\n'
        + _mode_branch(script_text, "gate") + "\n"
    )
    return _run(harness).stdout


# ══════════════════════════════════════════════════════════════════════════════
# C5：触发面闭包（谓词必须命中模块目录；跨目录输入必须被命中或登记）
# ══════════════════════════════════════════════════════════════════════════════


def escaping_inputs(module_rel: str, repo: Path = REPO) -> dict[str, list[str]]:
    """模块源码里解析到**本模块之外**的仓内相对路径 → `{仓内相对路径: [消费文件, …]}`。

    只认**字符串字面量**里的 `../` 相对路径（注释不算 —— 注释里会引用别的模块的路径）；
    逃到仓库之外的（`../../../node_modules/...`）不属「仓内跨目录输入」，不入册。
    """
    base = repo / module_rel
    out: dict[str, list[str]] = {}
    root = repo.resolve()
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix not in SOURCE_EXTS or "node_modules" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for m in _REL_SPEC_RE.finditer(text):
            target = (p.parent / m.group(1)).resolve()
            try:
                rel = target.relative_to(root).as_posix()
            except ValueError:
                continue
            if rel == module_rel or rel.startswith(module_rel + "/"):
                continue
            out.setdefault(rel, []).append(p.relative_to(root).as_posix())
    return out


def predicate_pattern(script_text: str, fn: str) -> str:
    """从谓词函数体里读出那条 `grep -E '<谓词>'`（读不出 ⇒ fail-closed 报错）。"""
    m = re.search(r"grep -E '([^']+)'", _extract(script_text, fn))
    assert m, f"{fn}() 里找不到 `grep -E '<谓词>'` —— 谓词必须是可读出的正则（否则本判据看不见射程）"
    return m.group(1)


def trigger_face_problems(script_text: str, ledger: dict, repo: Path = REPO) -> list[str]:
    """C5：谓词命中模块目录本身；跨目录输入 ∈ 谓词 ∪ 已登记的触发面外输入（两个方向都判）。"""
    problems: list[str] = []
    registered_inputs = ledger.get("trigger_face_uncovered_inputs") or {}
    computed_all: set[str] = set()
    for rel, entry in sorted((ledger.get("modules") or {}).items()):
        trigger = entry.get("trigger") or {}
        if trigger.get("kind") not in FACE_TRIGGER_KINDS:
            continue
        fn = trigger.get("predicate_fn") or ""
        pattern = predicate_pattern(script_text, fn)
        if not re.search(pattern, rel + "/"):
            problems.append(
                f"{rel}：《{pattern}》命中不了模块目录本身（判据 = {fn}()）—— "
                "触发面必须至少覆盖它自己判的那个模块"
            )
        inputs = escaping_inputs(rel, repo)
        computed_all |= set(inputs)
        for path, consumers in sorted(inputs.items()):
            if re.search(pattern, path):
                continue
            if path in registered_inputs:
                continue
            problems.append(
                f"{rel} 的跨目录输入 {path}（被 {sorted(set(consumers))} 引用）既不在触发面"
                f"《{pattern}》内、也没有登记为触发面外输入 —— 它变了而这条腿不跑 = 漏面；"
                "出口 = ① 把路径纳入谓词；② 登记进 trigger_face_uncovered_inputs（reason + issue + owner）"
            )
    for path in sorted(set(registered_inputs) - computed_all):
        problems.append(f"trigger_face_uncovered_inputs 里的 {path} 已陈旧（现取没有这个跨目录输入）⇒ 销账")
    if len(registered_inputs) > UNCOVERED_INPUT_CAP:
        problems.append(
            f"触发面外输入 {len(registered_inputs)} 条 > 现取上限 {UNCOVERED_INPUT_CAP} 条（只许缩短）"
        )
    return problems


# ══════════════════════════════════════════════════════════════════════════════
# C7/C8：行为（fail-closed / 派发）+ 与 CI 逐字一致 + 空跑防线
# ══════════════════════════════════════════════════════════════════════════════


def _bmini_root(tmp_path: Path, *, tools: tuple[str, ...], with_pkg: bool = True) -> Path:
    """造一个最小 ROOT（只影响 `probe_ready` 的探测结果），用于确定性地演练两种环境。"""
    root = tmp_path / "root"
    if with_pkg:
        (root / BMINI).mkdir(parents=True, exist_ok=True)
    bin_dir = root / BMINI / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for tool in tools:
        f = bin_dir / tool
        f.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        f.chmod(0o755)
    return root


def _wrapper_harness(script_text: str, root: Path, wrapper: str, name: str) -> str:
    """把 probe_ready()+report()+wrapper 装进最小 harness（可注入 ROOT：伪造依赖有无）。"""
    return (
        "set -uo pipefail\n"
        f"ROOT={shlex.quote(str(root))}\n"
        "PASS=0; FAIL=0; READY=0; declare -a FAILED; declare -a NOT_READY\n"
        + _extract(script_text, "probe_ready") + "\n"
        + _extract(script_text, "report") + "\n"
        + _extract(script_text, wrapper) + "\n"
        + f'{wrapper} bmini-app "{name}" true\n'
        + 'echo "COUNTERS PASS=$PASS FAIL=$FAIL READY=$READY"\n'
        + "rm -f /tmp/verify-all-$$-*.log\n"
    )


def _ci_leg_commands() -> tuple[str, ...]:
    """现取 CI 两条腿的 run 原文（`npm ci` 不是判定内容，剔除；detect 步骤是多行 bash，不匹配）。"""
    data = yaml.safe_load(BMINI_WORKFLOW.read_text(encoding="utf-8")) or {}
    out: list[str] = []
    for job in (data.get("jobs") or {}).values():
        for step in (job.get("steps") or []):
            run = (step.get("run") or "").strip()
            if re.match(r"^(npx|npm) ", run) and run != "npm ci":
                out.append(run)
    return tuple(out)


def _jest_test_files() -> list[Path]:
    """按 jest 配置的 `testMatch` 现取测试文件（配置形态变了 ⇒ fail-closed 报错要人同步）。"""
    cfg = (REPO / BMINI / "jest.config.js").read_text(encoding="utf-8")
    m = re.search(r"testMatch:\s*\[\s*'<rootDir>/([^']+)'", cfg)
    assert m, "jest.config.js 的 testMatch 形态变了 —— 同步本守卫（否则「测试面非空」这条判据会假绿）"
    raw = m.group(1)
    pats = [raw.replace("{ts,tsx}", ext) for ext in ("ts", "tsx")]
    hits: list[Path] = []
    for pat in pats:
        hits += sorted((REPO / BMINI).glob(pat))
    return hits


# ── C9/C10：快循环档 fail-closed 的**行为**读数 + 覆盖面登记 ────────────────────────


def _fake_module_root(tmp_path: Path, *, env: str, ready: bool) -> Path:
    """造一个最小 ROOT：`env` 的就绪探测**确定性**地要么满足、要么不满足。

    ⚠️ 只用**只依赖文件**的 env key（`ai-agent` / `admin-web-vitest` / `admin-web-tsc`）：
    `admin-api`（要 java 在 PATH）与 `worker-h5-node-tests`（要 node 在 PATH）在不同机器上读数不同
    ⇒ 判据会变得不确定（`FM-E15` 同族：判据不许依赖"本机恰好装了什么"）。
    """
    root = tmp_path / ("ready" if ready else "missing")
    if env == "ai-agent":
        bin_dir = root / "backend" / "ai-agent-service" / ".venv" / "bin"
        tool = bin_dir / "python"
    elif env in ("admin-web-vitest", "admin-web-tsc"):
        bin_dir = root / "frontend" / "admin-web" / "node_modules" / ".bin"
        tool = bin_dir / ("vitest" if env == "admin-web-vitest" else "tsc")
    else:
        raise AssertionError(f"本 helper 只支持「只依赖文件」的 env key，收到 {env!r}")
    bin_dir.mkdir(parents=True, exist_ok=True)
    if ready:
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
    return root


def _gated_harness(script_text: str, root: Path, *, env: str, face_fn: str, change_set: str) -> str:
    """把**脚本里真实的** probe_ready / report / report_env / report_strict / report_gated /
    face_hit / 谓词装进最小 harness（只注入 ROOT 与 CHANGE_SET）。

    ⚠️ 刻意**不**替身掉任何被测函数：判据判的是「命中 ⇒ report_strict / 未命中 ⇒ report_env」
    这条**真实现**；替身掉就等于自证（`FM-C1` 族）。
    """
    return (
        "set -uo pipefail\n"
        f"ROOT={shlex.quote(str(root))}\n"
        f"CHANGE_SET={shlex.quote(change_set)}\n"
        "PASS=0; FAIL=0; READY=0; declare -a FAILED; declare -a NOT_READY\n"
        + _extract(script_text, "probe_ready") + "\n"
        + _extract(script_text, "report") + "\n"
        + _extract(script_text, "report_strict") + "\n"
        + _extract(script_text, "report_env") + "\n"
        + _extract(script_text, "report_gated") + "\n"
        + _extract(script_text, "face_hit") + "\n"
        + _extract(script_text, face_fn) + "\n"
        + f'report_gated {env} {face_fn} "腿名" true\n'
        + 'echo "COUNTERS PASS=$PASS FAIL=$FAIL READY=$READY"\n'
        + "rm -f /tmp/verify-all-$$-*.log\n"
    )


def gated_behavior_reading(script_text: str, tmp_path: Path) -> dict:
    """三态**实跑**读数：① 命中+缺依赖 ② 未命中+缺依赖 ③ 命中+就绪（三种环境各起一个进程）。"""
    ready = _fake_module_root(tmp_path / "env-ready", env=GATED_ENV, ready=True)
    missing = _fake_module_root(tmp_path / "env-missing", env=GATED_ENV, ready=False)
    return {
        "hit_missing": _run(_gated_harness(script_text, missing, env=GATED_ENV,
                                           face_fn=GATED_FACE_FN, change_set=GATED_HIT_PATH)).stdout,
        "miss_missing": _run(_gated_harness(script_text, missing, env=GATED_ENV,
                                            face_fn=GATED_FACE_FN, change_set=GATED_MISS_PATH)).stdout,
        "hit_ready": _run(_gated_harness(script_text, ready, env=GATED_ENV,
                                         face_fn=GATED_FACE_FN, change_set=GATED_HIT_PATH)).stdout,
    }


def gated_behavior_problems(reading: dict) -> list[str]:
    """**纯函数**：三态读数 → 问题清单（红证直接喂变异后的读数）。"""
    problems: list[str] = []
    hit = reading.get("hit_missing", "")
    miss = reading.get("miss_missing", "")
    ready = reading.get("hit_ready", "")
    if "COUNTERS PASS=0 FAIL=1 READY=0" not in hit or "❌" not in hit:
        problems.append(
            "命中触发面 + 依赖缺：必须记 ❌（`PASS=0 FAIL=1 READY=0`）—— 「没跑」不得等于「通过」：\n" + hit
        )
    if "⏭️" in hit:
        problems.append("命中触发面 + 依赖缺：出现了 ⏭️（跳过被读成「这项没事」）：\n" + hit)
    if "python3 -m venv" not in hit:
        problems.append("命中触发面 + 依赖缺：文案不可行动（必须给出实测可跑通的恢复命令）：\n" + hit)
    if "COUNTERS PASS=0 FAIL=0 READY=1" not in miss:
        problems.append(
            "未命中触发面 + 依赖缺：必须仍是 ⏭️ 未就绪、且**不计通过**"
            "（也不许为不碰该模块的 PR 制造假红）：\n" + miss
        )
    if "⏭️" not in miss or "不是通过" not in miss:
        problems.append("未命中触发面 + 依赖缺：控制台必须显式说清「未就绪 / 不是通过」：\n" + miss)
    if "✅" in miss:
        problems.append("未命中触发面 + 依赖缺：出现了 ✅（未跑的检查被记成通过）：\n" + miss)
    if "COUNTERS PASS=1 FAIL=0 READY=0" not in ready:
        problems.append("命中触发面且依赖齐备：必须**照旧真跑**（`PASS=1` ⇒ 覆盖强度不变）：\n" + ready)
    return problems


def _redproof_env_legs(script_text: str) -> list[str]:
    """`redproof` 档里用 `report_env` 派发的**实跑**腿名（现取）。"""
    return re.findall(r'^[ ]{4}report_env\s+\S+\s+"([^"]+)"', _mode_branch(script_text, "redproof"), re.M)


def fail_closed_scope_problems(script_text: str, ledger: dict) -> list[str]:
    """C10：覆盖面登记与**事实**自洽 —— 登记里写的每一条都要能被现取核对，不是散文。"""
    problems: list[str] = []
    scope = ledger.get("fail_closed_scope") or {}
    if not scope:
        problems.append(
            "台账缺 `fail_closed_scope`（覆盖面登记：改了什么 / 没改什么 / 覆盖不到什么 —— "
            "本单的边界必须写明并**被判据钉住**）"
        )
        return problems
    for key in ("_what", "not_changed", "not_covered"):
        if not scope.get(key):
            problems.append(f"fail_closed_scope 缺 {key!r}（三件事：改了什么 · 没改什么 · 覆盖不到什么）")
    if not any("覆盖强度" in s for s in scope.get("not_changed") or []):
        problems.append("fail_closed_scope.not_changed 没有点名「覆盖强度」—— 这是本单最容易被读错的一条")
    for item in scope.get("not_covered") or []:
        if len(item) < 20:
            problems.append(f"fail_closed_scope.not_covered 有一条太短（说不清边界）：{item!r}")
    tier = scope.get("redproof_tier") or {}
    branch = _mode_branch(script_text, "redproof")
    legs = _redproof_env_legs(script_text)
    if tier.get("gated") is not False:
        problems.append("fail_closed_scope.redproof_tier.gated 必须是 false（本单**有意不**门控实跑腿）")
    if "report_gated" in branch or "report_strict" in branch:
        problems.append(
            "redproof 档里出现了 report_gated / report_strict —— 与登记「未门控」不符"
            "（要么撤掉，要么同批改 fail_closed_scope 与下半段的核对）"
        )
    if tier.get("leg_count") != len(legs):
        problems.append(
            f"fail_closed_scope.redproof_tier.leg_count = {tier.get('leg_count')!r} ≠ "
            f"redproof 档 report_env 实跑腿**现取** {len(legs)} 条（涨跌都要同批更新）"
        )
    if len(legs) < 2:
        problems.append(f"redproof 档的实跑腿现取只有 {len(legs)} 条 —— 抽出失效或腿被删（本判据 fail-closed）")
    return problems


# ══════════════════════════════════════════════════════════════════════════════
# 常驻判据
# ══════════════════════════════════════════════════════════════════════════════


def test_discovered_modules_are_all_registered():
    """C1/C2/C6：模块发现（冻结口径）⊆ 登记，且登记项活着、形态合法、台账不超上限。"""
    ledger = _ledger()
    discovered = discovered_modules()
    print(f"[矩阵] 现取模块 {len(discovered)} 个：{discovered}")
    print(f"[矩阵] 登记模块 {len(ledger.get('modules') or {})} 个 / "
          f"未覆盖模块 {len(ledger.get('uncovered_modules') or {})} 个")
    assert discovered, "模块发现为空 ⇒ 本判据恒绿（fail-closed：发现口径写错了）"
    problems = registration_problems(ledger, discovered)
    assert problems == [], "本地门禁覆盖矩阵不合格：\n" + "\n".join(f"  · {p}" for p in problems)


def test_declared_legs_are_alive_in_declared_tiers():
    """C3/C4：登记的腿必须逐字活在它声称的档位里；fail-closed 条目必须走 `report_strict`。"""
    problems = leg_problems(SCRIPT.read_text(encoding="utf-8"), _ledger())
    assert problems == [], "登记的腿与 verify-all.sh 的实际派发不一致：\n" + "\n".join(f"  · {p}" for p in problems)


def test_trigger_face_covers_module_and_registers_out_of_face_inputs():
    """C5：谓词命中模块目录本身；跨目录输入必须被命中或登记为触发面外输入（两向）。"""
    text = SCRIPT.read_text(encoding="utf-8")
    problems = trigger_face_problems(text, _ledger())
    for rel, entry in sorted((_ledger().get("modules") or {}).items()):
        if (entry.get("trigger") or {}).get("kind") == "diff-face-hit":
            print(f"[触发面] {rel} 的跨目录输入现取 = {sorted(escaping_inputs(rel))}")
            print(f"[触发面] {rel} 的谓词 = {predicate_pattern(text, entry['trigger']['predicate_fn'])!r}")
    assert problems == [], "触发面不闭合：\n" + "\n".join(f"  · {p}" for p in problems)


def test_uncovered_inventory_only_shrinks_and_stays_live():
    """C6/C6b：未覆盖模块台账只许缩短 + 每条带 reason/issue/owner + 兜它的 CI 腿是真的。"""
    problems = uncovered_problems(_ledger())
    assert problems == [], "未覆盖台账不合格：\n" + "\n".join(f"  · {p}" for p in problems)


def test_indirect_coverage_names_a_real_consumer():
    """C7b：声明 `indirect` 的模块必须给出**真的 import 它**的消费文件（否则「间接覆盖」是空话）。"""
    problems: list[str] = []
    for rel, entry in sorted((_ledger().get("modules") or {}).items()):
        if not entry.get("indirect"):
            continue
        if not entry.get("note"):
            problems.append(f"{rel}：声明 indirect 却没写 note（说清「谁覆盖它 / 怎么覆盖」）")
        consumers = entry.get("consumed_by") or []
        if not consumers:
            problems.append(f"{rel}：声明 indirect 却没写 consumed_by")
        for consumer in consumers:
            p = REPO / consumer
            if not p.is_file():
                problems.append(f"{rel}：consumed_by 里的消费文件不存在：{consumer}")
                continue
            if not any(t.startswith(rel + "/") for t in escaping_inputs_for_file(p)):
                problems.append(
                    f"{rel}：{consumer} 里找不到指向本模块的相对路径字面量 ⇒ 「间接覆盖」的证据不成立"
                )
    assert problems == [], "间接覆盖声明无证据：\n" + "\n".join(f"  · {p}" for p in problems)


def escaping_inputs_for_file(path: Path) -> list[str]:
    """单个文件里 `../` 相对路径字面量解析出的仓内路径（与 `escaping_inputs` 同一读法）。"""
    root = REPO.resolve()
    out: list[str] = []
    for m in _REL_SPEC_RE.finditer(path.read_text(encoding="utf-8")):
        try:
            out.append((path.parent / m.group(1)).resolve().relative_to(root).as_posix())
        except ValueError:
            continue
    return out


def test_report_strict_is_fail_closed_on_missing_deps(tmp_path):
    """C7：缺依赖 ⇒ **fail-closed**（❌ + 非零），**不是** ⏭️ —— 且文案可行动（含恢复命令）。

    对照：同一个「未就绪」环境用 `report_env` 跑 ⇒ ⏭️（READY=1）—— 证明本判据判的是**两条路的差别**，
    不是被任何输入喂红（fixture 真的处在「未就绪」态）。
    """
    text = SCRIPT.read_text(encoding="utf-8")
    root = _bmini_root(tmp_path, tools=("jest", "taro"))  # 缺 tsc ⇒ 未就绪（装不全）
    strict = _run(_wrapper_harness(text, root, "report_strict", "bmini 腿"))
    print("[fail-closed] report_strict 控制台：\n" + strict.stdout)
    assert "❌" in strict.stdout, f"缺依赖时没有记 ❌（fail-closed 失效）：\n{strict.stdout}"
    assert "COUNTERS PASS=0 FAIL=1 READY=0" in strict.stdout, (
        f"fail-closed 必须记「失败」而不是「未就绪」：\n{strict.stdout}"
    )
    assert "⏭️" not in strict.stdout, f"fail-closed 路径不允许出现 ⏭️（跳过会被读成通过）：\n{strict.stdout}"
    assert "npm ci" in strict.stdout, f"缺依赖的文案不可行动（必须给出恢复命令）：\n{strict.stdout}"
    control = _run(_wrapper_harness(text, root, "report_env", "bmini 腿"))
    print("[fail-closed] 对照（report_env 同一环境）：\n" + control.stdout)
    assert "⏭️" in control.stdout and "COUNTERS PASS=0 FAIL=0 READY=1" in control.stdout, (
        f"对照失效：同一环境必须能被 report_env 判成「未就绪」（否则本判据分不清对象）：\n{control.stdout}"
    )
    ready_root = _bmini_root(tmp_path / "ready", tools=("tsc", "jest", "taro"))
    ready = _run(_wrapper_harness(text, ready_root, "report_strict", "bmini 腿"))
    assert "COUNTERS PASS=1 FAIL=0 READY=0" in ready.stdout, (
        f"依赖齐全时没真跑（探测把一切都吞掉了）：\n{ready.stdout}"
    )


def test_gate_dispatch_follows_the_trigger_face():
    """C7：命中触发面 ⇒ 腿被派发；未命中 ⇒ 不派发且打印「未跑」（都用脚本里真实的派发文本）。"""
    text = SCRIPT.read_text(encoding="utf-8")
    hit = dispatch_stdout(text, f"{BMINI}/src/app.tsx\nREADME.md\n")
    print("[派发] 命中触发面：\n" + hit)
    assert "STRICT bmini-app " in hit, f"变更集命中 bmini ⇒ gate 档没有派发这条腿：\n{hit}"
    miss = dispatch_stdout(text, "backend/admin-api/src/main/java/com/migao/Demo.java\n")
    print("[派发] 未命中触发面：\n" + miss)
    assert "STRICT bmini-app " not in miss, f"不碰 bmini 的 PR 被这条腿卡住了：\n{miss}"
    assert "未跑" in miss, f"未命中时必须显式声明「未跑」：\n{miss}"


def test_local_leg_commands_match_ci():
    """C8（同源声明 `CI_LEG_COMMANDS` 的判据）：本地腿的四条命令 == CI 两条腿的 run 原文。"""
    ci = _ci_leg_commands()
    print(f"[同源] CI 侧现取 = {ci}")
    assert ci == CI_LEG_COMMANDS, (
        "CI `bmini-app.yml` 的腿命令与 `CI_LEG_COMMANDS` 不再逐字一致（不要自创第三套口径）：\n"
        f"  CI 现取：{ci}\n  本地声明：{CI_LEG_COMMANDS}\n"
        "  同一 PR 里把两边对齐（改 CI ⇒ 同改本声明与 verify-all.sh 的本地腿）"
    )
    local = _extract(SCRIPT.read_text(encoding="utf-8"), "bmini_leg")
    missing = [cmd for cmd in CI_LEG_COMMANDS if cmd not in local]
    assert missing == [], (
        f"本地腿没有跑这些 CI 同款命令：{missing}\n  （本地腿现取：\n{local}）"
    )


def test_local_leg_runs_them_in_order():
    """C8：本地腿按 CI 的**同序**执行（h5 先于 weapp —— 顺序坏了失败归因会指向错的阶段）。"""
    local = _extract(SCRIPT.read_text(encoding="utf-8"), "bmini_leg")
    positions = []
    for cmd in CI_LEG_COMMANDS:
        positions.append(local.index(f"&& {cmd}"))
    assert positions == sorted(positions), (
        f"本地腿的命令顺序与 CI 不一致（h5 必须先于 weapp）：现取位置 {positions}"
    )


def test_bmini_test_face_is_not_empty():
    """C7（空跑防线）：`npm test` = `jest --passWithNoTests` —— 测试面被清空也不会红，
    故这里给测试面一个「现取非空」的判据（清空测试 = 本腿退化成空跑）。"""
    files = _jest_test_files()
    print(f"[空跑防线] jest testMatch 现取测试文件 {len(files)} 个")
    assert files, (
        "frontend/bmini-app 的 jest 测试面为空 —— `jest --passWithNoTests` 仍会 exit 0 ⇒ "
        "本腿变成空跑（绿了但没跑）"
    )


def test_gated_legs_dispatch_through_report_gated():
    """C9（静态）：五条快循环档模块腿必须由 `report_gated` 在档位分支**顶层无条件**派发。"""
    text = SCRIPT.read_text(encoding="utf-8")
    problems = leg_problems(text, _ledger()) + gated_wrapper_problems(text)
    print(f"[快循环 fail-closed] 登记的 gated 条目 = "
          f"{sorted(r for r, e in _ledger()['modules'].items() if (e.get('trigger') or {}).get('kind') == 'diff-face-gated-deps')}")
    assert problems == [], "快循环档 fail-closed 接线不合格：\n" + "\n".join(f"  · {p}" for p in problems)


def test_gated_legs_are_fail_closed_on_hit_and_not_on_miss(tmp_path):
    """C9（行为）：命中+缺依赖 ⇒ ❌/`FAIL=1`；未命中+缺依赖 ⇒ ⏭️/`READY=1`（**不计通过**）；命中+就绪 ⇒ 照旧真跑。"""
    reading = gated_behavior_reading(SCRIPT.read_text(encoding="utf-8"), tmp_path)
    for name in ("hit_missing", "miss_missing", "hit_ready"):
        print(f"[快循环 fail-closed] {name}：\n{reading[name]}")
    problems = gated_behavior_problems(reading)
    assert problems == [], "快循环档 fail-closed 行为不合格：\n" + "\n".join(f"  · {p}" for p in problems)


def test_fail_closed_scope_is_pinned_to_the_facts():
    """C10：覆盖面登记（`fail_closed_scope`）与现取事实自洽（redproof 档「未门控」这一条被钉住）。"""
    problems = fail_closed_scope_problems(SCRIPT.read_text(encoding="utf-8"), _ledger())
    scope = _ledger().get("fail_closed_scope") or {}
    print(f"[覆盖面登记] 不改动的 = {scope.get('not_changed')}")
    print(f"[覆盖面登记] 覆盖不到 = {scope.get('not_covered')}")
    print(f"[覆盖面登记] redproof 档 = {scope.get('redproof_tier')}")
    assert problems == [], "覆盖面登记不合格：\n" + "\n".join(f"  · {p}" for p in problems)


# ══════════════════════════════════════════════════════════════════════════════
# 判别力自证（红证：变异在内存 / 临时目录里当场构造；含「只改注释」的对照）
# ══════════════════════════════════════════════════════════════════════════════


def test_ghost_module_is_caught(tmp_path):
    """C1 的判别力自证：临时树里多一个未登记模块 ⇒ 判据**指名**它；对照（不加目录）不红。"""
    ledger = _ledger()
    tmp_repo = tmp_path / "repo"
    for root in MODULE_ROOTS:
        (tmp_repo / root).mkdir(parents=True, exist_ok=True)
    for rel in ledger["modules"]:
        (tmp_repo / rel).mkdir(parents=True, exist_ok=True)
    for rel in ledger["uncovered_modules"]:
        (tmp_repo / rel).mkdir(parents=True, exist_ok=True)
    for rel in ledger.get("non_modules") or {}:
        (tmp_repo / rel).mkdir(parents=True, exist_ok=True)
    baseline = registration_problems(ledger, discovered_modules(tmp_repo), tmp_repo)
    assert baseline == [], f"对照失效：登记齐备的临时树不该红：{baseline}"
    (tmp_repo / "frontend" / "zz-ghost").mkdir()
    (tmp_repo / "frontend" / "zz-ghost" / "package.json").write_text("{}", encoding="utf-8")
    problems = registration_problems(ledger, discovered_modules(tmp_repo), tmp_repo)
    assert any("frontend/zz-ghost" in p and "未登记" in p for p in problems), (
        f"新加一个模块却不登记 ⇒ 判据没有指名它（判别力不足）：{problems}"
    )


def test_new_escaping_input_is_caught(tmp_path):
    """C5 的判别力自证：临时树里新增一个逃逸到别模块的字面量 ⇒ 判据报出该路径。

    同时给「只改注释」的对照：把同一个路径写进**注释**不得被读成输入闭包（否则所有引用
    别的模块路径的注释都会被拖成红）。
    """
    tmp_repo = tmp_path / "repo"
    bmini_src = tmp_repo / BMINI / "src" / "utils" / "inbound"
    bmini_src.mkdir(parents=True)
    (tmp_repo / "frontend" / "admin-web" / "src" / "lib").mkdir(parents=True)
    (tmp_repo / "frontend" / "admin-web" / "src" / "lib" / "matrix.json").write_text("{}", encoding="utf-8")
    comment_only = bmini_src / "probe.ts"
    comment_only.write_text(
        "// 说明：本文件与 ../../../../admin-web/src/lib/matrix.json 同源（注释不算输入）\n"
        "export const a = 1\n",
        encoding="utf-8",
    )
    assert escaping_inputs(BMINI, tmp_repo) == {}, (
        f"只改注释（把路径写进说明）被读成了输入闭包 ⇒ 假红方向：{escaping_inputs(BMINI, tmp_repo)}"
    )
    real = bmini_src / "importer.ts"
    real.write_text(
        "import matrix from '../../../../admin-web/src/lib/matrix.json'\nexport default matrix\n",
        encoding="utf-8",
    )
    found = escaping_inputs(BMINI, tmp_repo)
    assert found == {"frontend/admin-web/src/lib/matrix.json": [f"{BMINI}/src/utils/inbound/importer.ts"]}, (
        f"新增一个跨目录 import 却没被输入闭包抓到（漏面）：{found}"
    )
    text = SCRIPT.read_text(encoding="utf-8")
    problems = trigger_face_problems(text, _ledger(), tmp_repo)
    assert any("frontend/admin-web/src/lib/matrix.json" in p for p in problems), (
        f"未登记的跨目录输入没有让判据变红：{problems}"
    )


def test_removed_leg_is_detected_as_dead():
    """C3 的判别力自证：把 bmini 腿从 gate 分支删掉（内存变异）⇒ 判据报「腿不存在 / 档位不符」。

    对照：只改注释（同样的字面量写进注释）⇒ 不红 —— 证明判据读的是**代码行**，不是文本巧合。
    """
    text = SCRIPT.read_text(encoding="utf-8")
    assert leg_problems(text, _ledger()) == [], "真实脚本必须先是合规的（否则本红证分不清对象）"
    leg = "bmini-app 类型检查 + 单测 + 构建（h5 + weapp）"
    comment_only = text + f'\n# 说明：gate 档会跑 "{leg}"（注释不是派发）\n'
    assert leg_problems(comment_only, _ledger()) == [], (
        "「只改注释」的对照红了 ⇒ 本判据被文本巧合喂红，而不是被真形态喂红"
    )
    dead = _mutate(text, f'"{leg}"', '"bmini-app 腿（改名了）"')
    problems = leg_problems(dead, _ledger())
    assert any("不存在" in p or "档位" in p for p in problems), (
        f"腿被删除/改名后判据没有报「登记已死」：{problems}"
    )


def test_report_env_substitution_is_detected_as_not_fail_closed():
    """C4 的判别力自证：把 fail-closed 派发换成 `report_env` ⇒ 判据报「不许走 ⏭️ 那条路」。"""
    text = SCRIPT.read_text(encoding="utf-8")
    mutated = _mutate(text, "report_strict bmini-app ", "report_env bmini-app ")
    problems = leg_problems(mutated, _ledger())
    assert any("report_strict" in p for p in problems), (
        f"换成 report_env（缺依赖会被跳过）却没让判据变红 ⇒ C4 是空断言：{problems}"
    )
    assert leg_problems(text, _ledger()) == [], "真实脚本必须先是合规的（否则分不清对象）"


def test_narrowed_predicate_would_not_dispatch():
    """C5/C7 的判别力自证：谓词被收窄成命中不了 bmini ⇒ ① C5 报红 ② 派发 harness 不再派发。"""
    text = SCRIPT.read_text(encoding="utf-8")
    pattern = predicate_pattern(text, "bmini_face_paths")
    narrowed = _mutate(text, pattern, "^frontend/zz-nope/")
    print(f"[变异] 谓词 {pattern!r} → '^frontend/zz-nope/'")
    problems = trigger_face_problems(narrowed, _ledger())
    assert any("命中不了模块目录本身" in p for p in problems), (
        f"谓词收窄后 C5 没红（触发面闭包是空断言）：{problems}"
    )
    out = dispatch_stdout(narrowed, f"{BMINI}/src/app.tsx\n")
    assert "STRICT bmini-app " not in out, (
        f"谓词收窄后仍派发了这条腿 ⇒ 派发不受触发面控制（判据读错了对象）：\n{out}"
    )
    assert "STRICT bmini-app " in dispatch_stdout(text, f"{BMINI}/src/app.tsx\n"), (
        "对照组失效：真实脚本在命中触发面时必须派发"
    )


# ── C9/C10 的判别力自证（变异**在内存里**当场构造；含「只改注释」对照与「锚唯一」自证）──────


def test_gated_report_env_substitution_is_detected():
    """C9 判别力：把 `report_gated <env> <face>` 换回 `report_env <env>` ⇒ 判据变红。

    对照：**只改注释**（把同一串写进注释）⇒ **不红** —— 证明判据读的是**代码行的派发形态**，
    不是「文件变了没有」（`FM-C3`：红证打偏的形态）。
    """
    text = SCRIPT.read_text(encoding="utf-8")
    anchor = f'report_gated {GATED_ENV} {GATED_FACE_FN} "ai-agent 单测"'
    assert text.count(anchor) == 1, (
        f"锚点必须唯一（带腿名才唯一：前缀锚在 quick/full/agent 三档都命中 ⇒ 红证会打偏）："
        f"现取 {text.count(anchor)} 处"
    )
    assert leg_problems(text, _ledger()) == [], "真实脚本必须先是合规的（否则本红证分不清对象）"
    comment_only = text + f'\n# 说明：两档都用 `{anchor}"ai-agent 单测"` 派发（注释不是派发）\n'
    assert leg_problems(comment_only, _ledger()) == [], (
        "「只改注释」的对照红了 ⇒ 本判据被文本巧合喂红，而不是被真形态喂红"
    )
    mutated = _mutate(text, anchor, f'report_env {GATED_ENV} "ai-agent 单测"')
    problems = leg_problems(mutated, _ledger())
    assert any("report_gated" in p and "分支顶层" in p for p in problems), (
        f"换回 report_env（依赖缺 ⇒ ⏭️ 跳过）却没让判据变红 ⇒ C9 是空断言：{problems}"
    )


def test_gated_leg_wrapped_in_a_condition_is_detected():
    """C9 判别力：把一条腿套进 `if …; then`（= 按变更集决定跑不跑）⇒ 判据报「被套在条件里」。

    这一条守的是**覆盖强度**那一半：套进条件后，不碰该模块的改动连腿都不跑了（issue #3680 的失败开放形态）。
    """
    text = SCRIPT.read_text(encoding="utf-8")
    anchor = f'    report_gated {GATED_ENV} {GATED_FACE_FN} "ai-agent 单测"'
    assert text.count(anchor) == 1, f"锚点必须唯一（只有 quick 档用短腿名）：现取 {text.count(anchor)} 处"
    mutated = _mutate(text, anchor, f'    if face_hit {GATED_FACE_FN}; then\n{anchor}\n    fi')
    problems = leg_problems(mutated, _ledger())
    assert any("被套在条件里" in p for p in problems), (
        f"把腿套进条件里却没红 ⇒ 「无条件派发」是空断言（覆盖强度可被静默改小）：{problems}"
    )
    assert leg_problems(text, _ledger()) == [], "对照组失效：真实脚本必须先是合规的"


def test_removed_gated_dispatch_is_detected():
    """C9 判别力（**删掉必红**自证）：把三档里的 `admin-web tsc` 派发行全删 ⇒ 判据报档位不符。"""
    text = SCRIPT.read_text(encoding="utf-8")
    line = '    report_gated admin-web-tsc admin_web_face_paths "admin-web tsc"'
    assert text.count(line) == 3, f"锚点必须唯一可数（quick/full/frontend 三处）：现取 {text.count(line)}"
    mutated = text.replace(line, "")
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 该红证是空断言）"
    problems = leg_problems(mutated, _ledger())
    assert any("admin-web tsc" in p for p in problems), (
        f"整条派发行被删却没红（腿死了没人管）：{problems}"
    )


def test_gated_wrapper_silent_pass_and_never_hit_are_detected(tmp_path):
    """C9 判别力（行为面两条）：① 未命中时**静默通过**；② 命中判定恒假（`if false`）——都必须变红。"""
    text = SCRIPT.read_text(encoding="utf-8")
    assert gated_behavior_problems(gated_behavior_reading(text, tmp_path / "base")) == [], (
        "真实脚本必须先是合规的（否则本红证分不清对象）"
    )
    # ① 「未命中 + 依赖缺」这条路上把它改成静默 ✅（直接 report 一个恒真命令）
    env_call = 'report_env "$env_key" "$name" "$@"'
    assert text.count(env_call) == 1, f"锚点必须唯一（只在 report_gated 里）：现取 {text.count(env_call)} 处"
    silent = _mutate(text, env_call, 'report "$name" true')
    p1 = gated_behavior_problems(gated_behavior_reading(silent, tmp_path / "silent"))
    assert any("未命中触发面 + 依赖缺" in p for p in p1), (
        f"未命中时静默通过（✅ / 计成通过）却没红 ⇒ C9 的「不计通过」那一半是空断言：{p1}"
    )
    # ② 命中判定恒假 ⇒ 命中的腿退回 ⏭️（fail-closed 永不生效）
    hit_guard = 'if face_hit "$face_fn"; then'
    assert text.count(hit_guard) == 1, f"锚点必须唯一（只在 report_gated 里）：现取 {text.count(hit_guard)} 处"
    never = _mutate(text, hit_guard, "if false; then")
    p2 = gated_behavior_problems(gated_behavior_reading(never, tmp_path / "never"))
    assert any("命中触发面 + 依赖缺" in p for p in p2), (
        f"命中判定恒假（fail-closed 永不生效）却没红：{p2}"
    )


def test_narrowed_module_face_is_detected(tmp_path):
    """C5/C9 判别力：把 ai-agent 的谓词收窄成命中不了自己 ⇒ ① C5 报红 ② 命中场景退回 ⏭️（fail-closed 失效）。"""
    text = SCRIPT.read_text(encoding="utf-8")
    pattern = predicate_pattern(text, GATED_FACE_FN)
    assert pattern == "^backend/ai-agent-service/", f"谓词现取变了（同步本判据）：{pattern!r}"
    narrowed = _mutate(text, pattern, "^backend/zz-nope/")
    problems = trigger_face_problems(narrowed, _ledger())
    assert any("命中不了模块目录本身" in p for p in problems), (
        f"谓词收窄后 C5 没红（触发面闭包是空断言）：{problems}"
    )
    p2 = gated_behavior_problems(gated_behavior_reading(narrowed, tmp_path))
    assert any("命中触发面 + 依赖缺" in p for p in p2), (
        f"谓词收窄后「命中」场景静默退回 ⏭️ 却没红：{p2}"
    )


def test_admin_web_face_covers_its_cross_directory_inputs():
    """C5 判别力（本单最容易漏的一处）：admin-web 的**测试**会读后端源码 ⇒ 那些文件必须在谓词里。

    对照：只改注释（把路径写进注释）不算输入（`escaping_inputs` 只认字符串字面量）。
    """
    text = SCRIPT.read_text(encoding="utf-8")
    pattern = predicate_pattern(text, "admin_web_face_paths")
    inputs = escaping_inputs("frontend/admin-web")
    print(f"[触发面] frontend/admin-web 的跨目录输入现取 {len(inputs)} 条：{sorted(inputs)}")
    assert len(inputs) >= 8, f"现取跨目录输入少了（源码变了就同步本判据的下限）：{sorted(inputs)}"
    uncovered = [p for p in inputs if not re.search(pattern, p)]
    assert uncovered == [], (
        f"admin-web 的跨目录输入没有全在触发面里：{uncovered}\n"
        "（出口 = 把它们加进 verify-all.sh 的 admin_web_face_paths —— 它们是这条腿判定对象的输入）"
    )
    assert any("migration-archive" in p for p in inputs), (
        "现取的跨目录输入里没有目录形态（`migration-archive`）—— 判据的形态覆盖与现场不符，同步本判据"
    )
