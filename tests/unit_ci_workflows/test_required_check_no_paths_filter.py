# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012。）
r"""**required 检查不得被 workflow 级 `paths:` 过滤遮住**（issue #3507 ① / #4786 / #5101 的类级锁）。

## 病根（一类缺陷：**required 检查永不报告 ⇒ PR 永久 BLOCKED，且没有任何东西会变红**）

GitHub 的分支保护按「**检查名**」要 required 状态。若提供该检查名的 workflow 在
`on.pull_request` 上带 `paths:` / `paths-ignore:` 过滤，那么**不碰这些路径的 PR 上该 workflow
根本不触发** ⇒ 那条 required 检查**永远不会被上报** ⇒ PR 卡在
`Expected — waiting for status to be reported`，**既不合也并不变红**（"全绿却合不了"，
排查极易被引向 CI / 冲突 / label —— 与 #4231 同族）。

本仓**已被这个形态烧过两次**（`docs/wiki/CI-CD.md`「变更门控」+ `migao-dev-flow` §2.2）：
**翻一条 job 成 required 有两条前置，缺一不可** —— ① 它在每个 PR 上都会被上报
（该 workflow 的 `on.pull_request` **不得**有 `paths:` 过滤）② 它的判定方式是确定的。
**实证**：#5101 上把 `worker-h5 unit tests` 与 `Mini-app e2e static contract preflight`
翻成 required 后**立刻 `BLOCKED`**；撤回两条后立刻 `MERGEABLE/CLEAN`（零代码改动）。

## 本判据（三条腿，各自能单独变红）

| # | 判据 | 红证（只改一处即翻转） |
|---|---|---|
| 1 | **凡上报 required 检查名的 workflow，其 `on.pull_request` 不得有 `paths` / `paths-ignore`** | 往 `.github/workflows/mini-app.yml` 的 `on.pull_request` 加一行 `paths: ['frontend/mini-app/**']` ⇒ 必红（红证实跑记录见 PR body） |
| 2 | **snapshot 的每个 required 名都必须真被某个 PR 触发 job 上报**（陈旧检测：job 改名 / 删除 / 从未上报 ⇒ 红） | 把 snapshot 里某个名改一个字 ⇒ 必红 |
| 3 | **snapshot 与成本台账的 `required` 口径必须一致**（两个数据文件不许各说各话） | 把 `ci_cost_ledger.json` 里某条 `required` 翻转 ⇒ 必红 |
| 5 | **凡上报 required 检查名的 job，一律不得带 job 级 `needs:`**（依赖面 ⇒ 上游被跳过 / 取消时它整层不跑） | 往 `pr-check.yml::ui-regression-check` 的 `name:` 下插一行 `needs: detect` ⇒ 必红 |
| 6 | **凡上报 required 检查名的 job，其 job 级 `if:` 只许写「恒真」形态**（无条件 / `always()` / 常量比较）—— 任何引用 `github.*` / `needs.*` / `steps.*` / `env.*` / `vars.*` / `secrets.*` 的谓词一律判红 | 往同一条 required 腿加 `if: github.event_name == 'schedule'` ⇒ 必红 |

> 判据 5/6 与判据 1 是**同一形态的姊妹**（本包 P1-5，关联 #6144；承 #6051 的窄口径）：
> 判据 1 防**workflow 级** `paths:`（整个 workflow 不触发），5/6 防 **job 级** `needs` / `if`
> （该 job 被整层跳过）—— 三者的后果**逐字相同**：required context **永不到来** ⇒ PR 永久
> `BLOCKED`，**没有任何东西变红**。判据 5/6 的允许形态与理由见下一节。

## 为什么 required 腿只能**步骤级**门控（issue #6099 / #6052 实测）

GitHub 对**被 job 级 `if` 跳过**的 job **不创建/不上报**该 context（只有 job 真创建了才上报；
**步骤**级 `if` 跳过照旧上报 `success`）⇒ required 腿一旦挂上 job 级门控，在不命中该面的 PR 上
该检查**永不出现**，页面只剩 `Expected — waiting for status to be reported`。

- **实证（#6099）**：15 条 required 腿现取**没有一条**用 job 级 `if` 跳过 —— 这不是「运气」，
  是「一旦如此就**永久 BLOCK 且无红信号**」；而窗口内 required 的缺席**全部**来自「并发取消
  （`cancel-in-progress`）导致 job 未创建」，**不是** job 级跳过 ⇒ **风险尚未发生，但此前没有判据拦它**。
- **实证（#6052 / issue #6051）**：`E2E quality gate` / `xiaobu H5 visual regression` /
  `bmini-app build (h5 + weapp)` / `bmini H5 tabBar geometry (e2e)` 这 **4 条非 required** 重腿
  被改成 `needs: <面判定 job>` + `if: … needs.<job>.outputs.run == 'true'` ⇒ 被跳过时 **context
  根本不创建**（实测 65 条新格式 run 里 **17 条被跳 = 26.2%**）。那是**有意**的（它们**不是**
  required，且面判定 job 会播报「未跑」）⇒ 本判据**只对 required 名生效，不许误伤它们**。
- ⇒ **required 腿的门控必须写在 step 上**（`if: steps.detect_xx.outputs.run == 'true'`，job 照常创建、
  照常上报 `success`），范式见 `pr-check.yml` 的 `Detect admin-web changes` 一族；口径与登记册见
  `docs/wiki/CI-CD.md`「变更门控」与 `tests/unit_ci_workflows/declaration_gate_registry.json`。

## job 级 `if:` 的**逐条口径**（允许 / 禁止）

- ✅ **允许**：**完全没有** job 级 `if`；`always()` / `'always()'` / `true` / `'true'` / `''`（空 ⇒ 恒真）；
  两侧都是**字符串字面量**的比较（`'a' == 'a'`，GH Actions 里**非 `${{ }}` 包裹的 `if:` 是表达式**，
  所以 `'a' == 'a'` 求值为真）；`always() && 'a' == 'a'` 这类**不引用任何上下文**的布尔组合。
- ⛔ **禁止**：任何引用 `needs.*` / `steps.*` / `env.*` / `vars.*` / `secrets.*` / `runner.*` /
  `strategy.*` / `matrix.*` / `job.*` / `inputs.*` 的谓词 —— 典型禁形 = **面判定输出**
  （`needs.detect.outputs.run == 'true'`）、**actor / 标签 / 草稿态**（`github.actor != 'x'`）
  ⇒ 它们**可能是假** ⇒ 为假时该 job 不创建 ⇒ required context 永不到来。
- ⛔ **`event_name` 白名单（`if: github.event_name == '<事件>'` 一族）单独一条规则**：
  **唯一**的安全条件 = 「该 workflow 声明的**每一个自动触发面**都出现在白名单字符串里」
  （判定式 = `自动触发面 ⊆ 白名单字面量集`）。`on:` 是**唯一真值** —— 这条是**静态可判**的。
  - **人为触发面**（`workflow_dispatch` / `workflow_call`）**不**计入覆盖面：它们不会自动落到
    PR / main 上（现取实测：`pr-check.yml` 的 9 条 required 腿 + 它的 `workflow_dispatch` 若计入就是**假红**）。
  - 典型禁形 = 白名单**没覆盖**某个自动触发面（含**新加触发面却没同步改谓词**这一形态）；
    也含“白名单里的那个事件**根本不在** `on:` 里”这种恒假谓词（`if: github.event_name == 'schedule'`
    写在只有 `pull_request` 的 workflow 里 ⇒ job 永远不创建）。
  - 🔴 **读不出 `on:` ⇒ 判红（fail-closed）**，不许当成「没有要覆盖的触发面」。

## job 级 `needs:` 的**逐条口径**

- ⛔ **禁止任何** job 级 `needs:`（不区分上游是不是面判定 job）。理由 = 「上游被跳过 / 取消 ⇒
  本 job 不跑」是**运行期**行为，静态 YAML **判不了** ⇒ 对 required 腿只能禁掉整个依赖面。
  现取：15 条 required 腿**一条 `needs` 都没有** ⇒ 这条禁令**零误伤**。
- ✅ **允许**：`.`（没有 `needs`）。步骤级依赖（`if: steps.x.outputs.y == 'true'`）**照旧允许**
  —— 那是**步骤**被跳过，job 仍创建、仍上报 `success`，required 永不悬空。
- ⛔ **禁止**：**任何** job 级 `needs:`（不区分上游是不是面判定 job）。理由 = 判据 5 的判定逻辑：
  `needs` 是**依赖面**，「上游被跳过 / 取消 ⇒ 本 job 不跑」是**运行期行为**（本判据读的是静态 YAML，
  **判不了**上游会不会被跳）⇒ 对 required 腿**只能禁掉整个依赖面**，不能靠"上游看起来稳定"放行。
  （现取：15 条 required 腿**一条 `needs` 都没有**，所以这条禁令**零误伤**。）
- 🔴 **「今天恒真」≠「永远恒真」—— 这一类本判据**判红**（照实登记）**：`pr-check.yml` 里 9 条
  required 腿带 `if: github.event_name == 'pull_request'`。`pr-check` 现取的**自动**触发面只有
  `pull_request`（另有 `workflow_dispatch`，属人为触发面、不计入覆盖面）⇒ 现在**是绿的**。
  **但这不是豁免**：往里加**任何自动触发面**（`push` / `schedule` / `merge_group` / `pull_request_target` …）
  而不同步改这些谓词，就会让这 9 条 context 在**那条触发面**上永久不到来 —— 而**没有任何东西会红**。
  本判据的判定式 = 「`event_name` 白名单 ⊇ 该 workflow 的**全部自动**触发面」，**静态可判**，
  所以「今天恒真」与「永远恒真」在这里被**分开**了（加自动触发面的那一刻当场红）。
  ⚠️ **同一条规则的第二个方向**也在面内：把白名单换成**不在 `on:` 里**的事件
  （如给 required 腿写 `if: github.event_name == 'schedule'`）⇒ **恒假** ⇒ 同样当场红。

## required 集合 + context → workflow/job 映射（**取法，不许硬编码名单**）

- **首选（attended / 本机）：现取 API** ——
  `gh api repos/<owner>/<repo>/branches/main/protection`（复用 `scripts/merge_gate.py` 的
  `gh_repo` / `fetch_required`，**不另写一套读法**）。现取成功时与 snapshot **逐字比对**：
  不一致 ⇒ **红**（判据 4，逼你刷新 snapshot），并打印可复制的刷新命令。
- **退路（CI）：checked-in snapshot** —— `ci workflow tests` job **读不到**该 API：
  `GET /branches/main/protection` **需 admin**，而 CI 只有 `secrets.GITHUB_TOKEN`
  （该事实在本仓 `tests/unit_ci_workflows/test_automerge_bot_safe_path.py` 与
  `.github/workflows/automerge.yml` 里都已实测登记）。此时退回
  `required_status_snapshot.json`，并**大字打印**「当前走的是 snapshot 形态」+ 捕获时间 +
  年龄 + 刷新命令。
- **映射方法（现取，不写名单）**：对 `.github/workflows/*.yml` 逐个 `yaml.safe_load`，取
  **`on.pull_request` 存在的** workflow 的每个 job，把 `job.get("name") or <job id>` 当**上报的
  检查名**（GitHub 的上报名是 job 的 `display name`；本仓现取**逐字** = 该 `name:`，无 workflow
  前缀 —— 由判据 2「每个 required 名都能被某个 PR 触发 job 上报」当场核，对不上就红）⇒
  得到 `检查名 → [(workflow 文件, job id, job 定义)]`。**required 集合里的每个名字**经这张表反查
  到它的 job；查不到 = 判据 2 红（陈旧 / 非 PR 触发面），**不是**在这里静默跳过。
- **读的是哪一份 workflow 文本（自证坐标）**：默认读**工作树**（CI = 该 PR 的 merge ref，
  与 GitHub 实际执行的那份**同一份**）；可用环境变量 **`MIGAO_WORKFLOW_REF=<git ref>`** 指定读
  `git show <ref>:<path>`（本机主检出落后 `origin/main` 时，用它拿到线上真值）。每次运行都打印
  **来源 + 文件字节哈希** —— 「我读到的那个东西，是不是它声称的那个对象？」（AGENTS.md 铁律 11）。
  ⚠️ 本仓 `.agent-presets/**` 已迁出业务仓，故本文件**不**读它。

## required 集合从哪来（**取法选择与边界，照实登记**）

- **首选（attended / 本机）：现取 API** ——
  `gh api repos/<owner>/<repo>/branches/main/protection`（复用 `scripts/merge_gate.py` 的
  `gh_repo` / `fetch_required`，**不另写一套读法**）。现取成功时与 snapshot **逐字比对**：
  不一致 ⇒ **红**（判据 4，逼你刷新 snapshot），并打印可复制的刷新命令。
- **退路（CI）：checked-in snapshot** —— `ci workflow tests` job **读不到**该 API：
  `GET /branches/main/protection` **需 admin**，而 CI 只有 `secrets.GITHUB_TOKEN`
  （该事实在本仓 `tests/unit_ci_workflows/test_automerge_bot_safe_path.py` 与
  `.github/workflows/automerge.yml` 里都已实测登记）。此时退回
  `required_status_snapshot.json`，并**大字打印**「当前走的是 snapshot 形态」+ 捕获时间 +
  年龄 + 刷新命令。
- 🔴 **退路不覆盖什么（不许读成"已覆盖"）**：CI 里**无法**发现「分支保护新增了一条 required、
  而 snapshot 还不知道」—— 那条新 required 若恰好带 `paths:` 过滤，CI **不会**红。
  覆盖它的唯一形态是 **attended 现取比对**（判据 4）⇒ 引入/变更分支保护后**必须**在本机
  （或任何能读该 API 的环境）跑一次本文件，并按提示刷新 snapshot。
  判据 2/3 在 CI 里仍然有效：**已知** required 名一旦失去上报来源、或与台账口径脱节，都会红。

## 一键复算 / 刷新

    python3 -m pytest tests/unit_ci_workflows/test_required_check_no_paths_filter.py -q -s
    python3 tests/unit_ci_workflows/test_required_check_no_paths_filter.py --refresh   # 现取 API 重写 snapshot

（`--refresh` 需要能读分支保护的凭据；读不到即**非零退出**，绝不静默写空集合。）
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO / ".github" / "workflows"
SNAPSHOT_PATH = REPO / "tests" / "unit_ci_workflows" / "required_status_snapshot.json"
LEDGER_PATH = REPO / "tests" / "unit_ci_workflows" / "ci_cost_ledger.json"
MERGE_GATE_PATH = REPO / "scripts" / "merge_gate.py"
SELF_REL = "tests/unit_ci_workflows/test_required_check_no_paths_filter.py"

REPO_SLUG = "zhaokai-mgzn/migao"
BRANCH = "main"
REFRESH_CMD = f"python3 {SELF_REL} --refresh"

#: **job 级**面门控的结构签名（issue #6051）：`if:` 里引用另一个 job 的输出
#: （`needs.<job>.outputs.<名>`）。这种 job 会被**整层跳过**，而 GitHub 对**被 job 级 `if` 跳过**
#: 的 job **不上报**该 context ⇒ 若该 job 提供 required 检查，该检查在非命中面的 PR 上永不到来。
JOB_GATE_RE = re.compile(r"needs\.[A-Za-z0-9_-]+\.outputs\.[A-Za-z0-9_-]+")

#: job 级 `if:` 里**引用任何运行时上下文**的形态（issue #6144 P1-5，本包加严）。
#: 代价 = 该 job 被**整层跳过** ⇒ 它上报的 required context **不创建** ⇒ 永久 `Expected — waiting…`。
#: 口径见 docstring「job 级 `if:` 的逐条口径」：**允许** = 无条件 / `always()` / 常量比较；
#: **禁止** = 任何 `github.*` / `needs.*` / `steps.*` / `env.*` / `vars.*` / `secrets.*` 引用。
CONTEXT_REF_RE = re.compile(
    r"\b(github|needs|steps|env|vars|secrets|runner|strategy|matrix|job|inputs)\."
)

#: 「恒真」`if:` 的**全部**允许形态（先剥行注释、再剥字符串字面量，剩下的必须是其中之一）。
_VACUOUS_IF_FORMS = {"", "always()", "true", "success()"}
#: 「两侧都是字符串字面量」的常量比较（`'a' == 'a'`）。⚠️ 收紧到**只许两侧** —— 否则
#: `'false() && 'a' == 'a'` 这类「表达式 + 常量比较」会被误判为恒真（实测过的抓法）。
_CONST_COMPARISON_RE = re.compile(r"^''\s*==\s*''$")
#: `event_name` 白名单：**唯一**因「触发面」而可能为假的谓词，故单独一条规则（见 `_if_verdict`）。
EVENT_NAME_RE = re.compile(r"\bgithub\.event_name\b")
_STRING_LITERAL_RE = re.compile(r"'([^']*)'")


def _declared_events(doc: dict) -> set[str]:
    """该 workflow 的**全部**触发面（事件名集合）—— 唯一真值 = `on:` 的键（不按文案猜）。"""
    on = doc.get("on") if isinstance(doc.get("on"), dict) else doc.get(True)
    if isinstance(on, str):          # `on: push` 这一形态（YAML 里 `on` 是字符串）
        return {on}
    if isinstance(on, list):
        return {str(k) for k in on}
    if not isinstance(on, dict):     # `on:` 缺失 / 读不出来 ⇒ 返回空集（下游判红，fail-closed）
        return set()
    return {str(k) for k in on}


#: **人为**触发面（`workflow_dispatch` / `workflow_call`）—— 它们**不会自动落到 main / PR**，
#: 故对「required 腿会不会在 PR 闸门上缺席」无贡献 ⇒ `event_name` 白名单**只**须覆盖**自动**触发面。
#: （现取实测：`pr-check.yml` 9 条 required 腿带 `if: github.event_name == 'pull_request'` 而该 workflow
#:  另有 `workflow_dispatch` ⇒ 把 `workflow_dispatch` 算进覆盖面就是**假红**；实测的 `gap` 正是它。）
_MANUAL_EVENTS = {"workflow_dispatch", "workflow_call"}


# ══════════════════════════════════════════════════════════════════════════════
# 现取 required 集合（复用 scripts/merge_gate.py 的读法，不另写一套）
# ══════════════════════════════════════════════════════════════════════════════


def _merge_gate():
    spec = importlib.util.spec_from_file_location("merge_gate_for_required_guard", MERGE_GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _live_required() -> set[str] | None:
    """现取 required 集合；**读不到 ⇒ `None`**（`None` 不是空集合 —— 空集合会被读成"没有 required"）。"""
    mg = _merge_gate()
    gh_bin = os.environ.get("MG_GH_BIN", "gh")
    try:
        return set(mg.fetch_required(mg.gh_repo(gh_bin), BRANCH, gh_bin))
    except mg.Undecidable:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 读真实 YAML（不按文件名/文案清单枚举）
# ══════════════════════════════════════════════════════════════════════════════


def _pr_config(doc: dict) -> dict | None:
    on = doc.get("on") if isinstance(doc.get("on"), dict) else doc.get(True)
    if not isinstance(on, dict) or on.get("pull_request") is None:
        return None
    pr = on["pull_request"]
    return pr if isinstance(pr, dict) else {}


def _workflows() -> dict[str, dict]:
    return {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(WORKFLOWS_DIR.glob("*.yml"))}


# ── workflow 文本的**来源自证**（AGENTS.md 铁律 11：先问「我读到的是不是它声称的那个对象」）──
# 默认读**工作树**：CI 里它就是该 PR 的 merge ref（与 GitHub 实际执行的那份同一份）；
# 配 `MIGAO_WORKFLOW_REF=<git ref>` 则读 `git show <ref>:<path>` —— 本机主检出落后 `origin/main`
# 时用它拿线上真值（本仓 #6144 审计现场就是这个坑）。两种来源都在读数里具名 + 打哈希。
WORKFLOW_READ_REF = os.environ.get("MIGAO_WORKFLOW_REF", "").strip()


def _workflow_texts() -> dict[str, str]:
    """→ {workflow 文件名: YAML 文本}（来源见 `WORKFLOW_READ_REF`；读不到即抛，fail-closed）。"""
    if not WORKFLOW_READ_REF:
        return {p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS_DIR.glob("*.yml"))}
    listing = subprocess.run(
        ["git", "-C", str(REPO), "ls-tree", "--name-only", f"{WORKFLOW_READ_REF}:.github/workflows"],
        capture_output=True, text=True,
    )
    if listing.returncode != 0:
        raise RuntimeError(
            f"读不到 `{WORKFLOW_READ_REF}:.github/workflows`（{listing.stderr.strip()}）"
            " ⇒ 拒绝静默退回工作树（那正是「读的东西不是它声称的对象」）"
        )
    out: dict[str, str] = {}
    for name in listing.stdout.split():
        if not name.endswith((".yml", ".yaml")):
            continue
        blob = subprocess.run(
            ["git", "-C", str(REPO), "show", f"{WORKFLOW_READ_REF}:.github/workflows/{name}"],
            capture_output=True, text=True,
        )
        if blob.returncode != 0:
            raise RuntimeError(f"读不到 `{WORKFLOW_READ_REF}:.github/workflows/{name}`：{blob.stderr.strip()}")
        out[name] = blob.stdout
    return out


def _workflow_docs(texts: dict[str, str] | None = None) -> dict[str, dict]:
    """→ {workflow 文件名: 解析后的 YAML}（不按文件名 / 文案清单枚举；判据 5/6 与判别力试验共用）。"""
    src = _workflow_texts() if texts is None else texts
    return {name: yaml.safe_load(text) for name, text in sorted(src.items())}


def _describe_source(texts: dict[str, str]) -> str:
    """读数自证：来源标注 + 每个文件的字节哈希（「我读到的那个东西，是不是它声称的对象」）。"""
    import hashlib

    where = f"`git show {WORKFLOW_READ_REF}:…`" if WORKFLOW_READ_REF else "工作树（CI = 该 PR 的 merge ref）"
    total = sum(len(t) for t in texts.values())
    digest = hashlib.sha256("".join(f"{n}:{hashlib.sha256(t.encode()).hexdigest()}"
                                    for n, t in sorted(texts.items())).encode()).hexdigest()[:12]
    return f"workflow 读源 = {where}；{len(texts)} 个文件 / {total} 字节 / 集合哈希 {digest}"


# ── 「job 级门控」的静态判定（判据 5/6 的唯一判定本体；判别力试验直接调它，不写第二份）──


def _strip_quoted_spans(line: str) -> str:
    """剥掉单引号字面量（GH Actions 表达式里的字符串**只能用单引号**）。

    目的：让两条判定都**不把字符串内容当代码** —— ① 注释识别（`echo "# …"` 里的 `#`）
    ② 上下文引用识别（`github.sha == 'github.ref'` 是常量比较，不是引用）。
    """
    out, i = [], 0
    while i < len(line):
        if line[i] == "'":
            j = i + 1
            while j < len(line) and line[j] != "'":
                j += 1
            if j >= len(line):  # 单数个引号（异常形态）⇒ 余下全是字面量，不越界
                out.append("''")
                break
            out.append("''")  # 保留一个字面量占位符 ⇒ 常量比较形态仍可判
            i = j + 1
        else:
            out.append(line[i])
            i += 1
    return "".join(out)


def _condition_code(cond: object) -> str:
    """job 级 `if:` 的**代码面**：逐行剥尾注释 + 剥字符串字面量、再把空白归一成单空格。

    ⚠️ `None`（**没有 `if:`**）必须归到空串 —— 写成 `str(None)` 会让「无条件」被判成
    非法形态（'None'），那是**假红**（写完当场实测抓到的）。
    """
    if cond is None:
        return ""
    kept = []
    for raw in str(cond).splitlines():
        line = _strip_quoted_spans(raw)
        pos = line.find("#")
        if pos != -1:
            line = line[:pos]
        kept.append(line)
    return " ".join(" ".join(kept).split())


def _condition_text_no_comments(cond: object) -> str:
    """同 `_condition_code`，但**保留字符串字面量**（只剥行注释）—— 取白名单 / 常量比对的字面量用。"""
    if cond is None:
        return ""
    kept = []
    for raw in str(cond).splitlines():
        line = _strip_quoted_spans(raw)
        pos = line.find("#")
        kept.append(raw[: pos] if pos != -1 else raw)
    return " ".join(" ".join(kept).split())


def _literal_pair(text: str) -> tuple[str, str] | None:
    """`'a' == 'b'` 形态 ⇒ `('a', 'b')`；不是两侧字面量 ⇒ `None`。"""
    m = re.fullmatch(r"'([^']*)'\s*==\s*'([^']*)'", text.strip())
    return (m.group(1), m.group(2)) if m else None


def _if_verdict(cond: object, declared_events: set[str]) -> tuple[bool, str]:
    """job 级 `if:` 是否**恒真** ⇒ (允许?, 归因)。形态口径见 docstring；**fail-closed**（判不了 ⇒ 不许）。

    `declared_events` = 该 workflow 的**全部**触发面（事件名集合）；只有 `event_name` 白名单
    需要它 —— 那条规则的**唯一**安全条件 = 「每个声明触发面都出现在白名单里」，
    交付期是**静态可判**的（这正是本判据能把「今天恒真」与「永远恒真」分开的地方）。
    """
    code = _condition_code(cond)
    if code in _VACUOUS_IF_FORMS:
        return True, ""
    if _CONST_COMPARISON_RE.fullmatch(code):
        # 两侧都是字符串字面量（`'a' == 'a'`）⇒ 恒真；`'a' == 'b'` ⇒ 恒假（fail-closed）。
        pair = _literal_pair(_condition_text_no_comments(cond))
        if pair and pair[0] == pair[1]:
            return True, ""
        return False, f"常量比较两侧不相等（{code!r}）⇒ 恒假 ⇒ job 永不创建"
    if EVENT_NAME_RE.search(code):
        # ⚠️ 白名单字面量要从不剥字符串的版本里取（`_condition_code` 把字面量换成了占位符）。
        whitelist = {m.group(1).strip() for m in _STRING_LITERAL_RE.finditer(_condition_text_no_comments(cond))}
        # 只有**自动**触发面需要被白名单覆盖（人为触发面不会自己落到主线上；见 `_MANUAL_EVENTS`）。
        auto_events = declared_events - _MANUAL_EVENTS
        gap = sorted(auto_events - whitelist)
        if gap:
            return False, (
                f"`event_name` 白名单没覆盖**自动**触发面 {gap}"
                f"（白名单={sorted(whitelist)}，自动触发面={sorted(auto_events)}）"
                " —— 换成这些触发面时该 job 不创建 ⇒ context 永不到来"
            )
        if not declared_events:
            return False, "读不出 `on:` 触发面 ⇒ 无法判定白名单是否覆盖（fail-closed）"
        return True, ""
    hit = CONTEXT_REF_RE.search(code)
    if hit:
        return False, f"引用运行时上下文 `{hit.group(0)}`（可能为假 ⇒ job 被整层跳过 ⇒ context 不创建）"
    return False, f"形态不在允许清单内（{code!r}）—— required 腿只许恒真形态"


def _job_gating_offenders(
    required: set[str],
    docs: dict[str, dict] | None = None,
) -> tuple[list[str], int, int]:
    """→ (违规定位清单, PR 触发 workflow 数, **非 required** 但带 job 级门控的 job 数)。

    只对**现取 required 名字**生效；非 required 腿的 job 级门控是**有意**的（#6051/#6052）⇒ 只计数、不判红。
    """
    docs = _workflow_docs() if docs is None else docs
    offenders: list[str] = []
    pr_workflows = 0
    non_required_gated = 0
    for wf, doc in sorted(docs.items()):
        if _pr_config(doc) is None:
            continue
        pr_workflows += 1
        events = _declared_events(doc)
        for jid, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            check = str(job.get("name") or jid)
            if check not in required:
                # **非 required** 腿：job 级门控是**有意**的（#6051/#6052 的 4 条重腿）⇒ 不判红。
                if job.get("needs") or str(job.get("if") or "").strip():
                    non_required_gated += 1
                continue
            needs = job.get("needs")
            if needs:
                upstream = [needs] if isinstance(needs, str) else list(needs)
                offenders.append(
                    f"{wf}::{jid}（{check}）：job 级 `needs: {needs!r}` —— 依赖上游 {upstream}"
                    "（上游被跳过 / 取消 ⇒ 本 required context **不创建**）"
                )
            ok, why = _if_verdict(job.get("if"), events)
            if not ok:
                offenders.append(
                    f"{wf}::{jid}（{check}）：job 级 `if: {job.get('if')!r}` —— {why}"
                    f"（声明触发面={sorted(events)}）"
                )
    return offenders, pr_workflows, non_required_gated


def _matrix_values(matrix: dict | None) -> dict[str, list[str]]:
    """`strategy.matrix` → `{键: [取值…]}`（`include` 里的键值也收；`exclude` 不收）。"""
    out: dict[str, list[str]] = {}
    for key, val in (matrix or {}).items():
        if key == "include":
            for entry in val or []:
                if not isinstance(entry, dict):
                    continue
                for k, v in entry.items():
                    out.setdefault(str(k), [])
                    if str(v) not in out[str(k)]:
                        out[str(k)].append(str(v))
        elif key == "exclude":
            continue
        elif isinstance(val, list):
            out[str(key)] = [str(v) for v in val]
    return out


def job_check_names(job: dict, jid: str) -> list[str]:
    """该 job 在 PR 事件上**会上报的检查名**（**matrix 展开**，issue #6164）。

    一个 job id 可以上报**多个**检查名：`name:` 里的 `${{ matrix.<键> }}` 由 GitHub 按 matrix
    每个取值各渲染一次。现取：拆腿后的 `ci-workflow-tests` 有 2 片 ⇒ 两个名
    （`ci workflow helper unit tests` / `ci workflow helper unit tests（后半）`）。
    不展开 ⇒ snapshot 里第二片那个名会「找不到上报它的 job」⇒ 被判成陈旧（**假红**）。
    """
    raw = str(job.get("name") or jid)
    keys = re.findall(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}", raw)
    if not keys:
        return [raw]
    values = _matrix_values((job.get("strategy") or {}).get("matrix") or {})
    parts = re.split(r"\$\{\{\s*matrix\.[A-Za-z0-9_-]+\s*\}\}", raw)
    names = [parts[0]]
    for i, key in enumerate(keys):
        choices = values.get(key) or [""]
        names = [n + v + parts[i + 1] for n in names for v in choices]
    seen: list[str] = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def _pr_reported_checks() -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    """→ (workflow 文件 → 它在 PR 事件上**会上报**的检查名集合, 检查名 → 上报它的 `workflow::job` 清单)。"""
    by_workflow: dict[str, set[str]] = {}
    by_check: dict[str, list[str]] = {}
    for name, doc in _workflows().items():
        if _pr_config(doc) is None:
            continue
        names: set[str] = set()
        for jid, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for check in job_check_names(job, jid):
                names.add(check)
                by_check.setdefault(check, []).append(f"{name}::{jid}")
        by_workflow[name] = names
    return by_workflow, by_check


def _snapshot() -> dict:
    assert SNAPSHOT_PATH.exists(), (
        f"缺 required 集合 snapshot：{SNAPSHOT_PATH.relative_to(REPO)}（fail-closed —— 没有它本判据会静默空跑）"
    )
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _snapshot_contexts() -> list[str]:
    ctx = _snapshot().get("contexts")
    assert isinstance(ctx, list), "snapshot 的 `contexts` 必须是数组（形态漂移 ⇒ 红）"
    assert len(ctx) > 0, "snapshot 的 `contexts` 是**空集** ⇒ 本判据会在空集上恒真（空跑成绿）"
    assert len(set(ctx)) == len(ctx), f"snapshot 的 `contexts` 有重复项 ⇒ 同名 required 被登记两次：{sorted(ctx)}"
    for name in ctx:
        assert isinstance(name, str) and name.strip() == name and name, f"snapshot 里的检查名不合规：{name!r}"
    return [str(c) for c in ctx]


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1（承重）：required 检查不得被 workflow 级 paths 过滤遮住
# ══════════════════════════════════════════════════════════════════════════════


def test_no_pr_paths_filter_on_a_workflow_reporting_a_required_check() -> None:
    """🔴 承重判据：上报 required 检查名的 workflow 不得在 `on.pull_request` 上带 `paths` / `paths-ignore`。"""
    required = set(_snapshot_contexts())
    by_workflow, _ = _pr_reported_checks()
    scanned = 0
    offenders: list[str] = []
    filtered_but_not_required: list[str] = []
    for wf, names in sorted(by_workflow.items()):
        pr = _pr_config(_workflows()[wf]) or {}
        paths = list(pr.get("paths") or [])
        ignored = list(pr.get("paths-ignore") or [])
        scanned += 1
        if not (paths or ignored):
            continue
        hit = sorted(names & required)
        if hit:
            offenders.append(
                f"{wf}：`on.pull_request` 带过滤 paths={paths} paths-ignore={ignored}，"
                f"而它上报 required 检查 {hit} ⇒ 不碰这些路径的 PR **永远拿不到该检查**"
                "（GitHub 报 `Expected — waiting for status to be reported`，且**不会变红**）"
            )
        else:
            filtered_but_not_required.append(wf)
    print(f"扫到 PR 触发 workflow {scanned} 个；其中 PR 级路径过滤 {len(filtered_but_not_required) + len(offenders)} 个"
          f"（**非 required** 的过滤属合法例外：{filtered_but_not_required}）；"
          f"snapshot required 名 {len(required)} 条")
    assert scanned > 0, "一个 PR 触发 workflow 都没扫到 ⇒ 读法失效（本判据会静默空跑成绿）"
    assert not offenders, (
        "「required 检查被 workflow 级 paths 过滤遮住」—— 这是**永久 BLOCKED 且无红信号**的形态"
        "（issue #3507 ①；实证据 #5101 / #4786）：\n"
        + "\n".join("  " + o for o in offenders)
        + "\n修法（二选一）：① **删掉** workflow 级 `paths:`，改成 job 内 diff 门控"
        "（`git diff --name-only origin/main...HEAD` + `$GITHUB_OUTPUT`，同 `pr-check.yml` 的"
        " `Detect admin-web changes` 步，登记册见 tests/unit_ci_workflows/declaration_gate_registry.json）；"
        "② 真的不需要它当 required ⇒ **从分支保护里撤掉**这条检查（不是留着 paths 过滤）。"
        "⚠️ 顺序不可换：**先删 paths、再改分支保护**（见 docs/wiki/CI-CD.md「变更门控」）。"
    )


def test_no_job_level_needs_on_a_job_reporting_a_required_check() -> None:
    """🔴 承重判据 5（issue #6144 P1-5）：required 腿**不得**带 job 级 `needs:`（依赖面）。

    `needs` 是**依赖面**：上游 job 被跳过 / 取消 / 失败时它整层不跑 ⇒ 该 context **不创建**
    ⇒ PR 永久 `Expected — waiting for status to be reported`，而**没有任何东西会红**。
    「上游看起来稳定」**不是**豁免理由（上游会不会被跳是**运行期**行为，静态 YAML 判不了）
    ⇒ 对 required 腿只能禁掉整个依赖面。现取：15 条 required 腿**一条 `needs` 都没有**（零误伤）。
    """
    required = set(_snapshot_contexts())
    texts = _workflow_texts()
    docs = _workflow_docs(texts)
    offenders, pr_workflows, non_required_gated = _job_gating_offenders(required, docs)
    needs_offenders = [o for o in offenders if "job 级 `needs" in o]
    # fail-closed 哨兵（承 #6051 的窄口径）：真语料里**必须**还存在「面判定输出」形态的门控
    # （4 条非 required 重腿）。它一旦消失 ⇒ 本文件的语料假设漂移 ⇒ 让**这里**红，
    # 而不是让任何断言在空语料上静默恒绿。
    output_gated = [
        f"{wf}::{jid}"
        for wf, doc in docs.items()
        for jid, job in (doc.get("jobs") or {}).items()
        if isinstance(job, dict) and JOB_GATE_RE.search(str(job.get("if") or ""))
    ]
    print(f"{_describe_source(texts)}；PR 触发 workflow={pr_workflows} 个；required 名={len(required)} 条；"
          f"required 腿带 `needs` 的={len(needs_offenders)} 条；"
          f"（对照）非 required 腿带 job 级门控={non_required_gated} 条 —— **有意**，不判红；"
          f"语料里「面判定输出」形态={len(output_gated)} 条 {output_gated}")
    assert pr_workflows > 0 and required, "一个 PR 触发 workflow / 一条 required 都没读到 ⇒ 读法失效（会静默空跑成绿）"
    assert output_gated, (
        "真语料里一条「`needs.<job>.outputs.<名>`」形态的 job 级门控都没有 ⇒ 语料漂移（#6051/#6052 的 4 条"
        "非 required 重腿或已消失/改名）⇒ 本文件的读法假设需要重新核对；**不许**让判据在空语料上静默恒绿。"
    )
    assert not needs_offenders, (
        "**required 腿被 job 级 `needs` 门控** —— 上游被跳过 / 取消 ⇒ 该 context 不创建 ⇒ PR 永久 BLOCKED"
        "且无红信号（issue #6144 P1-5；与 #3507 ① / #4786 / #5101 / #6051 同族）：\n"
        + "\n".join("  " + o for o in needs_offenders)
        + "\n修法（二选一）：① required 腿改用**步骤级**门控（job 保持创建、结论照常上报，口径见"
        " pr-check.yml 的 `Detect admin-web changes` 一族；登记册 ="
        " tests/unit_ci_workflows/declaration_gate_registry.json）；② 从分支保护里撤掉该 required"
        "（顺序不可换：**先改门控、再改分支保护**，见 docs/wiki/CI-CD.md「变更门控」）。"
    )


def test_no_context_dependent_if_on_a_job_reporting_a_required_check() -> None:
    """🔴 承重判据 6（issue #6144 P1-5）：required 腿的 job 级 `if:` 只许**恒真**形态。

    允许 = 无条件 / `always()` / `'true'` / 两侧都是字符串字面量的常量比较；
    禁止 = 任何引用 `github.*` / `needs.*` / `steps.*` / `env.*` / `vars.*` / `secrets.*` 的谓词
    （面判定输出、`event_name` 白名单、分支名、actor / 标签 / 草稿态 … 它们**都可能是假**）。

    为什么这条比「当前是否恒真」更严：`pr-check.yml` 的 9 条 required 腿带
    `if: github.event_name == 'pull_request'`，而该 workflow 现取只有 `pull_request` + `workflow_dispatch`
    ⇒ **今天恒真、无害**；但**换任何触发面就会让这 9 条 context 永久不到来**。
    「现在恒真」≠「永远恒真」，后者此前没有任何东西会红 —— 这正是本判据要拦的形态。
    """
    required = set(_snapshot_contexts())
    texts = _workflow_texts()
    offenders, _, _ = _job_gating_offenders(required, _workflow_docs(texts))
    if_offenders = [o for o in offenders if "job 级 `if" in o]
    print(f"{_describe_source(texts)}；required 名={len(required)} 条；"
          f"job 级 `if:` 非恒真的 required 腿={len(if_offenders)} 条")
    assert required, "一条 required 都没读到 ⇒ 读法失效（会静默空跑成绿）"
    assert not if_offenders, (
        "**required 腿的 job 级 `if:` 不是恒真形态** —— 它为假时该 job 不创建 ⇒ context 永不到来"
        " ⇒ PR 永久 BLOCKED 且无红信号（issue #6144 P1-5；#6052 实测：被跳过的 job **context 不创建**）：\n"
        + "\n".join("  " + o for o in if_offenders)
        + "\n修法：① required 腿删掉 job 级 `if:`，把门控**下沉到步骤**（`if: steps.detect_xx.outputs.run == 'true'`，"
        "job 照常创建 ⇒ 照常上报 success）；② 或从分支保护里撤掉该 required"
        "（顺序不可换：**先改门控、再改分支保护**，见 docs/wiki/CI-CD.md「变更门控」）。"
    )


#: 判别力试验的**注入点**（在真实 workflow 文本上做行级变异；三条各只让对应的一条判红）。
#: `(用例名, 语料文件, 锚行, 注入的 YAML 行, 期望的坏形态, 该形态必须命中, 该形态必须不命中)`
_INJECTION_CASES = (
    ("required_needs_gate_red", "pr-check.yml", "name: UI Regression Check",
     "needs: detect", "needs", ("UI Regression Check",), ("E2E quality gate",)),
    ("required_event_whitelist_red", "pr-check.yml", "name: UI Regression Check",
     "if: github.event_name == 'schedule'", "if", ("UI Regression Check",), ("E2E quality gate",)),
    ("non_required_gate_control_green", "pr-check.yml", "name: E2E quality gate",
     "if: github.event_name == 'schedule'", "if", (), ("E2E quality gate",)),
)


@pytest.mark.parametrize(
    "case_id,corpus,anchor,injection,shape,must_hit,must_miss",
    _INJECTION_CASES,
    ids=[c[0] for c in _INJECTION_CASES],
)
def test_discriminating_power_on_injected_job_gates(
    case_id: str, corpus: str, anchor: str, injection: str, shape: str,
    must_hit: tuple[str, ...], must_miss: tuple[str, ...],
) -> None:
    """判据 7：**注入式判别力自证** —— 在真语料文本上注入门控，只有对应那条判红。

    三条（真实读数见 PR body）：① required 腿加 `needs: <面判定 job>` ⇒ 判据 5 **必红**；
    ② required 腿加 `if: github.event_name == 'schedule'` ⇒ 判据 6 **必红**；
    ③ 对照：**非 required** 腿（`E2E quality gate`，它的 job 级门控是**有意**的）加同样的 `if:` ⇒
    **必须仍然绿**（防误伤 —— 这正是本包不改任何 workflow 的证明面）。
    """
    texts = _workflow_texts()
    base = _workflow_docs(texts)
    required = set(_snapshot_contexts())
    # 自证注入生效：按「job 的 `name:` 行」插入（该行在真实语料里唯一 ⇒ 只命中一条腿）
    lines = texts[corpus].splitlines(keepends=True)
    hits = [i for i, ln in enumerate(lines) if ln.strip() == anchor]
    assert len(hits) == 1, (
        f"注入点 `{anchor}` 在 .github/workflows/{corpus} 里命中 {len(hits)} 处（必须恰好 1 处）"
        " ⇒ 语料漂移，本判别力试验会静默失效（先修注入点，别把「没注入」读成「判据没判别力」）"
    )
    at = hits[0]
    # ⚠️ **就地替换**该 job 自己的 `if:`（含 `>-` 折行块），不能「插一行」——两种空跑都实测到了：
    #   ① YAML 重复键里 PyYAML 取**后者** ⇒ 原地插入被原 `if:` 吃掉；
    #   ② 插在 `name:` 之后时，会被紧随的 `if: >-` **折行块**当成它自己的一行吃掉。
    # job 块边界 = 下一个**顶格两空格**的 job 键（不能用「下一个非缩进行」——`needs:` 就在那之前）。
    end = next((j for j in range(at + 1, len(lines)) if re.fullmatch(r"  [A-Za-z0-9_-]+:\s*", lines[j])),
               len(lines))
    key = next((j for j in range(at + 1, end) if lines[j].startswith("    if:")), None)
    mutated = list(lines)
    if key is not None:
        stop = key + 1
        while stop < end and (not lines[stop].strip() or lines[stop].startswith("      ")):
            stop += 1
        mutated = mutated[:key] + [f"    {injection}\n"] + mutated[stop:]
    else:
        mutated = mutated[: at + 1] + [f"    {injection}\n"] + mutated[at + 1:]
    mutated_text = "".join(mutated)
    assert mutated_text != texts[corpus], f"注入未改变 {corpus} 的文本（锚点 `{anchor}` 处没插进去）⇒ 本试验是空跑"
    docs = dict(base)
    docs[corpus] = yaml.safe_load(mutated_text)
    injected = docs[corpus] != base[corpus]
    assert injected, (
        f"注入改变了 {corpus} 的文本但**没改变解析结果** ⇒ 注入落到了无效位置（本试验是空跑）\n"
        f"   注入行：{injection!r}；锚点行：{lines[at]!r}；既有 `if:` 起始行={key}"
    )
    # 反向对照：未注入的语料必须**干净**（否则「红」分不清是注入还是存量）
    clean, _, _ = _job_gating_offenders(required, base)
    assert not [o for o in clean if f"job 级 `{shape}" in o], (
        f"未注入的真语料上已存在 job 级 `{shape}` 违规 ⇒ 本试验的对照不成立：\n" + "\n".join("  " + o for o in clean)
    )
    offenders, _, _ = _job_gating_offenders(required, docs)
    shaped = [o for o in offenders if f"job 级 `{shape}" in o]
    print(f"[{case_id}] 注入 .github/workflows/{corpus} 的 `{anchor}` 后 +{injection!r} ⇒ "
          f"命中 `{shape}` 违规 {len(shaped)} 条：{shaped}")
    for check in must_hit:
        assert any(check in o for o in shaped), (
            f"注入后 `{check}` **没有**被判红 ⇒ 判据 5/6 对这个形态无判别力（空断言）：{shaped}"
        )
    for check in must_miss:
        assert not any(check in o for o in shaped), (
            f"`{check}` **被误伤** —— 非 required 腿的 job 级门控是**有意**的"
            f"（#6051/#6052），本判据只对 required 名生效：{shaped}"
        )
    if not must_hit:  # 对照用例：整份语料在注入后必须**零**违规
        assert not offenders, "对照用例（非 required 腿）竟判红 ⇒ 判据射程越界：\n" + "\n".join("  " + o for o in offenders)


def test_every_snapshot_context_is_reported_by_a_pr_triggered_job() -> None:
    """判据 2：snapshot 里每个 required 名都必须真被某个 PR 触发 job 上报（陈旧 ⇒ 红）。"""
    required = _snapshot_contexts()
    _, by_check = _pr_reported_checks()
    missing = [c for c in required if c not in by_check]
    print(f"snapshot required={len(required)} 条；能在 PR 触发 workflow 里找到上报者的={len(required) - len(missing)} 条")
    assert not missing, (
        "snapshot 里的检查名**在 PR 触发 workflow 里找不到任何上报它的 job** ⇒ snapshot 陈旧"
        "（job 被改名/删除），或该 required 检查由非 PR 触发面提供（那本身就是 PR 永久 BLOCKED 形态）：\n"
        + "\n".join(f"  {c}" for c in missing)
        + f"\n修法：本机跑 `{REFRESH_CMD}` 用现取 API 重写 snapshot；"
        "若该名字仍存在但 job 改了名，说明**分支保护与新名字脱节** ⇒ 先对齐分支保护。"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：snapshot 与成本台账口径一致（两个数据文件不许各说各话）
# ══════════════════════════════════════════════════════════════════════════════


def test_snapshot_and_cost_ledger_agree_on_required_set() -> None:
    """判据 3：台账里 `required: true` 的检查名集合 ≡ snapshot 的 required 集合。"""
    assert LEDGER_PATH.exists(), f"缺成本台账：{LEDGER_PATH.relative_to(REPO)}（issue #3507 ②）"
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    legs = ledger.get("legs") or []
    in_ledger = {str(leg["check_name"]) for leg in legs if leg.get("required") is True}
    required = set(_snapshot_contexts())
    print(f"台账 required 腿={len(in_ledger)} 条；snapshot required={len(required)} 条")
    assert len(legs) >= len(required), (
        f"台账只有 {len(legs)} 条腿 < required {len(required)} 条 ⇒ 台账漏登记（漏掉的腿不会被任何判据看到）"
    )
    assert in_ledger == required, (
        "台账的 `required` 口径与分支保护 snapshot **不一致**（两边必须同源）：\n"
        f"  只在台账里：{sorted(in_ledger - required)}\n"
        f"  只在 snapshot 里：{sorted(required - in_ledger)}\n"
        f"修法：本机跑 `{REFRESH_CMD}` 刷新 snapshot，或把台账按现取 required 重算"
        "（`python3 scripts/ci_cost_ledger.py --measure`）。"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 4：现取可用时，snapshot 必须与现取**逐字**一致（陈旧 ⇒ 红）
# ══════════════════════════════════════════════════════════════════════════════


def test_snapshot_matches_live_required_set_when_readable() -> None:
    """判据 4：能读到分支保护时，snapshot 必须与现取一致；读不到 ⇒ **大字退路横幅**（不谎报成通过）。"""
    snap = _snapshot()
    live = _live_required()
    if live is None:
        captured = str(snap.get("captured_at") or "")
        age = _age_days(captured)
        print(
            "\n" + "=" * 78 + "\n"
            f"⚠️ 退路形态：现取分支保护**读不到**（CI 的 GITHUB_TOKEN 无 admin，见 .github/workflows/automerge.yml）\n"
            f"   判据走 checked-in snapshot：captured_at={captured!r}（{age}）\n"
            f"   snapshot 覆盖：已知 required 名 {len(snap.get('contexts') or [])} 条 —— 判据 1/2/3 照常生效\n"
            f"   snapshot **不**覆盖：分支保护**新增**了某条 required 而 snapshot 还不知道（那条若带 paths 过滤，CI 不会红）\n"
            f"   ⇒ 引入/变更分支保护后，请在能读该 API 的环境跑一次 `{REFRESH_CMD}`\n"
            + "=" * 78
        )
        # 退路形态下 snapshot 就是唯一真值 ⇒ 必须自证「它真的可被刷新」：
        # 刷新命令漂移（改了文件/入口却没人改 snapshot）⇒ 读者按记录去刷会失败 ⇒
        # 只能手抄 ⇒ 这正是「陈旧且无人刷新」的形态（本判据存在的意义会被掏空）。
        assert str(snap.get("refresh_command") or "") == REFRESH_CMD, (
            f"snapshot 记录的刷新命令与现取入口不一致：{snap.get('refresh_command')!r} != {REFRESH_CMD!r}"
            " ⇒ 照它刷新会失败（读者只能手抄 ⇒ 必然腐烂）"
        )
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", captured), (
            f"snapshot 的 `captured_at` 不是可解析的 UTC 时间戳（{captured!r}）"
            " ⇒ 「读数有多旧」不可判（陈旧就会被读成新鲜）"
        )
        return
    assert set(live) == set(_snapshot_contexts()), (
        "现取 required 集合与 snapshot **不一致** ⇒ snapshot 陈旧（CI 退路会按旧集合判，新集合的 paths 遮盖查不出来）：\n"
        f"  只在现取里（snapshot 缺）：{sorted(set(live) - set(_snapshot_contexts()))}\n"
        f"  只在 snapshot 里（现取已无）：{sorted(set(_snapshot_contexts()) - set(live))}\n"
        f"修法：`{REFRESH_CMD}`（会重写 snapshot 的 contexts 与 captured_at）。"
    )
    print(f"现取 required={len(live)} 条，与 snapshot 逐字一致 ✅")


def _age_days(captured: str) -> str:
    try:
        when = datetime.strptime(captured, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return f"捕获时间无法解析（{captured!r}）"
    days = (datetime.now(timezone.utc) - when).total_seconds() / 86400.0
    return f"{days:.1f} 天前"


# ══════════════════════════════════════════════════════════════════════════════
# 一键刷新（`--refresh`）：现取 API → 重写 snapshot
# ══════════════════════════════════════════════════════════════════════════════


def refresh_snapshot() -> int:
    """现取分支保护 required 集合并重写 snapshot。**读不到即非零退出**（绝不写空集合）。"""
    live = _live_required()
    if live is None:
        print(f"❌ 读不到分支保护 required 集合（需 admin 凭据；gh 是否已登录？）⇒ **不写** snapshot。\n"
              f"   命令：gh api repos/{REPO_SLUG}/branches/{BRANCH}/protection --jq '.required_status_checks.contexts[]'",
              file=sys.stderr)
        return 3
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {
        "schema": "required-status-snapshot/v1",
        "what": (
            "分支保护 required 检查名的**只读快照**（issue #3507 ①）。用途：CI 里读不到 "
            "`GET /branches/main/protection`（需 admin）时，判据仍能对「已知 required 名」执行"
            "「不得被 workflow 级 paths 过滤遮住」这条类级锁。"
        ),
        "repo": REPO_SLUG,
        "branch": BRANCH,
        "captured_at": now,
        "capture_command": f"gh api repos/{REPO_SLUG}/branches/{BRANCH}/protection --jq '.required_status_checks.contexts[]'",
        "refresh_command": REFRESH_CMD,
        "contexts": sorted(live),
    }
    SNAPSHOT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ 已重写 {SNAPSHOT_PATH.relative_to(REPO)}：required {len(live)} 条 @ {now}")
    return 0


if __name__ == "__main__":  # pragma: no cover —— 刷新入口，不参与 pytest 收集
    if "--refresh" in sys.argv:
        raise SystemExit(refresh_snapshot())
    print(f"用法：python3 {SELF_REL} --refresh", file=sys.stderr)
    raise SystemExit(2)
