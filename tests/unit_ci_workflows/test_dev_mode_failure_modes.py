# case_ids: MC-028
"""**容易犯的问题必须固化进研发模式**：技能里的每一条纪律都要有「判别动作 / 判据 / 台账」三选一。

## 病根（不是「文档写得不够好」，而是**散文拦不住任何东西**）

本会话实测：一句写着「与种子矩阵逐值同步」的注释（`RoleService` 的 `issue #5291` 那处）**骗过了两个包**，
其中一个据此把错误归因写进了 `origin/main` 的代码注释。⇒ **「写一段劝告」不是交付**：
劝告不会被任何判据读，收窄它、删掉它、让它腐烂，**都不会有东西变红**。

同族（同一份转述被独立复核推翻的两条，见 `docs/design/rbac-single-source.md` §1.4 与 issue #5687）：

- **转述 ≠ 复核**：一份清单里的 13 件事，逐条去 `origin/main` 读一遍才发现有若干条**读错了对象**
  （典型：「验收协议 v1.11 的三问」其实住在 `.agent-presets/migao/skills/migao-acceptance/SKILL.md`
  的「交付物可达性判据（v1.11 新增）」，而 `docs/testing/acceptance-protocol.md` 里**没有**这一节）；
- **计数对象不等价**：用 `grep -c '^### '` 判「casebook 摘要跟没跟上」时，现取差值是
  `case_blocks + 1`（那 1 条是 `### 真值缺口用例（truths_ref 为空…）` 这个**非用例标题**）
  ⇒ **两个计数不是同一个对象**，必须先把那 1 条具名扣掉再比。

## 本文件锁什么（十条判据，逐条都有能单独变红的负向夹具）

| # | 判据 | 取法（**结构化，不读散文**） | 红证 |
|---|---|---|---|
| 1 | 技能里那一节**存在且非空** | 按标题字面定位 `## ` 节 | 删掉整节 ⇒ 红 |
| 2 | **覆盖面登记（边界）小节存在且非空** | 按标题字面定位 `### ` 子节 | 删掉边界子节 ⇒ 红 |
| 3 | 台账条目 ⇄ 技能节里的 `FM-xN` 记号 **双向相等** | 正则取记号；两个方向都判 | 技能里加一条未登记 ⇒ 红；台账里有而技能没写 ⇒ 红 |
| 4 | 每条**三选一**（`criterion` / `action` / `ledger_ref`）且**可解析** | `kind` 决定必须给哪个字段；`criterion`=`<path>::<symbol>`，symbol 必须在文件里**逐字出现** | 只写劝告（kind 缺失）⇒ 红；判据指到不存在的符号 ⇒ 红 |
| 5 | 每条至少有一条**机器可核的 evidence**（`<path>` 或 `<path>::<symbol>`） | 逐条解析到磁盘 | 锚点写错（符号漂移）⇒ 红 |
| 6 | **判别动作行（现取）**：边界节里列出的 id 集合 == 台账里 `kind=action` 的 id 集合 | 正则取 backtick 里的 id | 新增一条只靠人执行的条目而不登记 ⇒ 红；把 action 条目升级成判据后不移出边界 ⇒ 红 |
| 7 | CI 面的每条 `FM-EN` 必须**具名出现在 `docs/wiki/CI-CD.md`**，且 `guarded` 必须有可解析判据、`registered` 必须有可解析台账引用、`gap` **必须有 owner + 显形条件且不得带判据** | 双向 + 按 state 分派 | 「已修的又登记一遍」⇒ 红；「gap 却带着判据」= 陈旧 ⇒ 红 |
| 8 | **未守护台账只许缩短**：`state=gap` 条数 ≤ **本文件冻结的上限** | 上限**写在本文件里**（台账改不动它） | 新增一条 gap 而不动上限 ⇒ 红 |
| 9 | **本单未固化项只许缩短**：条数 ≤ 本文件冻结上限，每条须带 `reason` + `restart_when` | 同上 | 加一条「未固化」⇒ 红 |
| 10 | **fail-closed**：语料为空 / 节为空 ⇒ **非空违规**，不得静默放行 | 空串喂进纯函数 | 空技能文本 ⇒ 红（不许「没东西可判 ⇒ 绿」） |

## 为什么判据 3/6/7 要**双向**

单向（只判「台账里的条目在技能里有没有写」）会被两种形态绕过：
① **在技能里写一条永不被判的纪律**（记账本没记 ⇒ 下一个人删台账条目时它照样烂在技能里）；
② **把已修的东西又登记一遍**（用户点名要避免的「重复登记」）—— 只有反向判据拦得住。

## 🔴 明确的边界（**不要**把本守卫读成覆盖面更大的东西）

- **它只保证「每条纪律都有承载体」，不保证「承载体本身是对的」**：`criterion` 解析成的是
  「文件里逐字出现这个名字」，**不是**「该判据真的会为这条纪律变红」。红是那条判据自己的事
  （本仓的口径在 `migao-dev-flow` §23 的 G7 与 `docs/wiki/CI-CD.md` 的「红证机具的可靠性」节）；
- **`kind=action` 条目靠人执行** —— 判据只能保证它**列在边界节里**、有可复制命令，
  **没有任何东西**会拦住「人不去执行它」（边界节的存在是给下一个人看的账，不是门禁）；
- **只覆盖 `FM-` 记号这一种形态**：一条**完全不写记号**的新纪律（纯散文加进技能）在本判据面内
  **看不见** —— 它不会命中判据 3（记号集合没变），也不会命中判据 4（台账里没有它）。
  这是**已知残余**（识别散文纪律需要有语义判定，本仓刻意不做文本层的一刀切）；
- **`evidence` 只核到「路径/符号存在」**：`refs` 里的 `#NNNN` / `PR #NNNN` 是**叙述性引用**，
  本判据**不联网核**（离线判据不连 GitHub）；
- **判据 7 只要求 `FM-EN` 具名出现在 `docs/wiki/CI-CD.md` 的**那一节**里 ——
  它**不**保证 CI 面的每一条旧纪律都已入册（存量不在本单射程）；
- 🔴 **判据 11/12（取号）的边界（本单自己踩到，如实登记）**：只看**已合并状态** ⇒ 拦不住『main + 在飞分支』的撞号
  ⇒ 那条唯一性判据给人一个它**并不具备**的保护感。**实证**：本单写侧先取 `MC-026`（当时现取最大号 = `MC-025`），
  而 #5705 在 2026-09-27 11:41:05 合并时已占 `MC-026` / `MC-027` ⇒ 本单**顺延为 `MC-028`**。
  **为什么不"加强"它**：能看到的在飞分支只有本地已 fetch 的 remote refs（CI 的 `actions/checkout` 只取当前分支
  ⇒ 同一份代码在 CI 与本机会得到**不同读数**），走 GitHub API 则引入网络依赖 ⇒ 违反「翻 required / 写判据要先
  确认**判定方式是确定的**」（`migao-dev-flow` §2.2）。⇒ **选择显式登记边界**，不硬凑。
  **显形条件**：main 上已合并占号 且 某个在飞分支同号（本会话用例号已撞 7~8 次、迁移号 1 次）。
- 本判据**不改任何门禁的通过条件、不新增豁免**。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]

SKILL_REL = ".agent-presets/migao/skills/migao-dev-flow/SKILL.md"
LEDGER_REL = "tests/unit_ci_workflows/dev_mode_failure_modes_ledger.json"
CICD_REL = "docs/wiki/CI-CD.md"
LEDGER_PATH = REPO_ROOT / LEDGER_REL

#: 技能里承载本清单的节标题（字面；台账 `skill.section` 必须与它逐字相同）。
SECTION_HEADING = "## 25. 判别动作：读数与它声称的对象"
#: 覆盖面登记（边界）子节标题。
BOUNDARY_HEADING = "### 25.6 覆盖面登记：本清单**覆盖不到**什么"
#: 「判别动作行」在边界节里的取法（backtick 里的 `FM-xN` 记号）。
ACTION_LINE_PREFIX = "**判别动作行（现取）**："

#: 记号形态：`FM-` + 族字母 + 序号。
#: **技能面只用 A~D**（清单 A~D 落在 §25）；**CI 面单独一个族（E）**，落在 `docs/wiki/CI-CD.md`。
#: 两个面**分开取**：否则 §25 正文里引用一句 `FM-E2`（"登记见 CI-CD.md 的 FM-E2"）会被当成
#: "技能里写了一条未登记的纪律" ⇒ 假红（本单实测踩到，正是本文件要治的「读数与它声称的对象不是同一个」）。
ENTRY_ID_RE = re.compile(r"\bFM-[A-D]\d+\b")
CI_ID_RE = re.compile(r"\bFM-E\d+\b")
#: `criterion` / `evidence` 的 `<path>::<symbol>` 形态。
ANCHOR_SEP = "::"

#: 判据 8：`state=gap` 的**上限**（**冻结在本文件里** —— 台账改不动它；只许缩短）。
GAPS_FROZEN = 4
#: 判据 9：`not_solidified` 的**上限**（同上）。
NOT_SOLIDIFIED_FROZEN = 3
#: 本单新增的两条 CI 判据的**射程**（判据 11/12；收窄射程要先改这里）。
CASE_CORPUS_DIR = ".github/cases"
LIVE_MIGRATION_DIR = "backend/admin-api/src/main/resources/db/migration"
#: 判据 12 的**已登记**存量（`migration-archive/` 里版本号重复的 V 号，**只许缩短**）。
ARCHIVE_DUP_VERSIONS_FROZEN = 2
#: 取号判据（判据 11/12）的**已登记边界** —— 逐字出现在本文件的模块 docstring 里，由
#: `test_case_id_allocation_boundary_is_registered` 钉住（删掉 ⇒ 红）。**本单自己踩到过**：
#: 写侧取 MC-026 时现取最大号是 MC-025，而 #5705 合并后已占 MC-026/MC-027 ⇒ 顺延为 MC-028。
CASE_ID_ALLOCATION_BOUNDARY = "只看**已合并状态** ⇒ 拦不住『main + 在飞分支』的撞号"
#: 该边界必须随身携带的**实证锚**（撞号涉及的单号；少一个 ⇒ 红）。
CASE_ID_ALLOCATION_EVIDENCE = ("MC-026", "MC-027", "MC-028")


# ──────────────────────────────────────────────────────────────────────────────
# 纯函数层：**判据吃文本**（红证当场在内存里构造坏形态，不改磁盘）
# ──────────────────────────────────────────────────────────────────────────────

def real_file_text(rel: str) -> str | None:
    """默认读盘器：仓库相对路径 ⇒ 文本；不存在 ⇒ None（**不抛**，交给判据判红）。"""
    p = REPO_ROOT / rel
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8")


def section_text(doc: str, heading: str) -> str | None:
    """按**标题前缀**取一节（到下一个同级或更高级标题为止）；取不到 ⇒ None。

    取**前缀**而不是全等：节标题后面常挂「（vX.Y.Z 新增，<日期> 用户裁定「…逐字…」）」这类
    会随版本变长的尾巴 —— 用全等会让判据在**每次抬版本号**时假红（把判据钉在易变的对象上）。
    """
    lines = doc.split("\n")
    level = len(heading) - len(heading.lstrip("#"))
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(heading):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        s = lines[j].lstrip("#")
        if lines[j].startswith("#") and (len(lines[j]) - len(s)) <= level:
            end = j
            break
    return "\n".join(lines[start:end])


def ids_in(text: str, pattern: "re.Pattern[str]" = ENTRY_ID_RE) -> set[str]:
    return set(pattern.findall(text or ""))


def action_ids(ledger: dict) -> set[str]:
    return {e["id"] for e in ledger.get("entries", []) if e.get("kind") == "action"}


def _resolve_anchor(spec: object, file_text: Callable[[str], str | None]) -> str | None:
    """`<path>` 或 `<path>::<symbol>` ⇒ None（可解析）／违规原因。"""
    if not isinstance(spec, str) or not spec.strip():
        return f"锚点为空：{spec!r}"
    path, _, symbol = spec.partition(ANCHOR_SEP)
    text = file_text(path)
    if text is None:
        return f"锚点指向的文件不存在：{path}"
    if symbol and symbol not in text:
        return f"锚点在文件里逐字找不到：{spec}"
    return None


def ledger_violations(
    *,
    skill_text: str,
    cicd_text: str,
    ledger: dict,
    file_text: Callable[[str], str | None] = real_file_text,
) -> list[str]:
    """全部违规（空列表 = 全绿）。**纯函数**：只吃文本 + 读盘器，红证可当场构造坏形态。"""
    bad: list[str] = []

    # ── 判据 1/2/10：节存在、边界子节存在、空语料 fail-closed ───────────────────
    sec = section_text(skill_text, SECTION_HEADING)
    if not skill_text.strip():
        bad.append("技能语料为空 ⇒ 判据无从判定（**未跑 ≠ 通过**，fail-closed）")
    if sec is None:
        bad.append(f"技能里找不到节标题：{SECTION_HEADING!r}（整节被删 ⇒ 固化失效）")
        sec = ""
    elif not sec.strip():
        bad.append(f"技能节 {SECTION_HEADING!r} 是空的 ⇒ 固化失效")
    bnd = section_text(skill_text, BOUNDARY_HEADING)
    if bnd is None:
        bad.append(f"技能里找不到覆盖面登记子节：{BOUNDARY_HEADING!r}（删掉边界 ⇒ 红）")
        bnd = ""
    elif not bnd.strip():
        bad.append(f"覆盖面登记子节 {BOUNDARY_HEADING!r} 是空的（「无边界」= 声称覆盖一切）")

    skill_ids = ids_in(sec)
    ledger_ids = {e.get("id") for e in ledger.get("entries", [])}
    if not ledger_ids:
        bad.append("台账 `entries` 为空 ⇒ 未登记即红的另一半无从判定（fail-closed）")

    # ── 判据 3：条目 ⇄ 技能记号 双向相等 ──────────────────────────────────────
    for missing in sorted(ledger_ids - skill_ids):
        bad.append(f"{missing}：台账里有，技能节里**没有**写 ⇒ 纪律没有落到研发模式")
    for extra in sorted(skill_ids - ledger_ids):
        bad.append(f"{extra}：技能节里写了，台账里**未登记** ⇒ 未登记即红")

    # ── 判据 4/5：每条三选一 + 至少一条机器可核 evidence ───────────────────────
    for e in ledger.get("entries", []):
        eid = e.get("id", "?")
        kind = e.get("kind")
        if kind not in {"criterion", "action", "ledger"}:
            bad.append(
                f"{eid}：`kind`={kind!r} 不在 {{criterion, action, ledger}} 里 "
                f"⇒ 这一条**只写了劝告**（没有判别动作 / 判据 / 台账）"
            )
            continue
        if kind == "criterion":
            problems = [_resolve_anchor(c, file_text) for c in e.get("criteria") or []]
            problems = [p for p in problems if p]
            if not e.get("criteria"):
                bad.append(f"{eid}：kind=criterion 但没给 `criteria`")
            bad += [f"{eid}：{p}" for p in problems]
        elif kind == "action":
            if not str(e.get("action") or "").strip():
                bad.append(f"{eid}：kind=action 但 `action` 为空 ⇒ 离散文只有一步之遥")
        else:
            ref = e.get("ledger_ref")
            if not isinstance(ref, str) or ANCHOR_SEP not in ref:
                bad.append(f"{eid}：kind=ledger 但 `ledger_ref` 不是 `<path>::<记号>` 形态：{ref!r}")
            else:
                reason = _resolve_anchor(ref, file_text)
                if reason:
                    bad.append(f"{eid}：台账引用失效 —— {reason}")
        if not e.get("evidence"):
            bad.append(f"{eid}：没有任何 `evidence` ⇒ 这条固化**不可复核**")
        for ev in e.get("evidence") or []:
            reason = _resolve_anchor(ev, file_text)
            if reason:
                bad.append(f"{eid}：evidence 失效 —— {reason}")

    # ── 判据 6：判别动作行（现取）── 边界节列出的 id == kind=action 的 id ────────
    declared: set[str] = set()
    hit_line = False
    for line in bnd.split("\n"):
        if line.strip().startswith(ACTION_LINE_PREFIX):
            hit_line = True
            declared |= ids_in(line)
    if not hit_line:
        bad.append(
            f"覆盖面登记子节里没有 `{ACTION_LINE_PREFIX}` 行 ⇒ "
            f"「哪些条目只靠人执行」没有现取登记"
        )
    else:
        live = action_ids(ledger)
        for missing in sorted(live - declared):
            bad.append(f"{missing}：只靠人执行的条目不写在边界节 ⇒ 下一个人读不到这条账")
        for extra in sorted(declared - live):
            bad.append(
                f"{extra}：边界节把它登记成「只靠人执行」，而台账里它不是 kind=action ⇒ 陈旧"
            )

    # ── 判据 7：CI 面具名出现在 docs/wiki/CI-CD.md + 按 state 分派 ─────────────
    ci_ids = ids_in(cicd_text, CI_ID_RE)
    findings = ledger.get("ci_findings", [])
    for f in findings:
        fid = f.get("id", "?")
        if fid not in ci_ids:
            bad.append(f"{fid}：未具名出现在 `{CICD_REL}` ⇒ CI 面的纪律没有落点（只写散文）")
        state = f.get("state")
        if state not in {"guarded", "registered", "gap"}:
            bad.append(f"{fid}：`state`={state!r} 不在 {{guarded, registered, gap}} 里")
            continue
        if state == "guarded":
            crit = f.get("criteria") or []
            if not crit:
                bad.append(f"{fid}：state=guarded 却没给 `criteria`（守护为匿名 ⇒ 不可复核）")
            for c in crit:
                reason = _resolve_anchor(c, file_text)
                if reason:
                    bad.append(f"{fid}：守护判据不可解析 —— {reason}")
        elif state == "registered":
            ref = f.get("ledger_ref")
            reason = _resolve_anchor(ref, file_text) if isinstance(ref, str) else "缺 `ledger_ref`"
            if reason:
                bad.append(f"{fid}：state=registered 但登记引用不可解析 —— {reason}")
        else:
            if f.get("criteria") or f.get("ledger_ref"):
                bad.append(
                    f"{fid}：state=gap 却带着判据/台账引用 ⇒ **陈旧**（要么改成 guarded/registered，"
                    f"要么它已经不是缺口）"
                )
            if not str(f.get("gap_owner") or "").strip():
                bad.append(f"{fid}：gap 没有 `gap_owner`（缺口不许匿名存在）")
            if not str(f.get("gap_shows_when") or "").strip():
                bad.append(f"{fid}：gap 没有 `gap_shows_when`（无守护时的**显形条件**必须写出来）")

    # ── 判据 8：未守护台账只许缩短 ────────────────────────────────────────────
    gaps = [f for f in findings if f.get("state") == "gap"]
    if len(gaps) > GAPS_FROZEN:
        bad.append(
            f"未守护（gap）条数 {len(gaps)} > 上限 {GAPS_FROZEN}（上限冻结在本判据里）⇒ "
            f"新增缺口必须先把它做成判据或并入既有台账，不许默默加"
        )

    # ── 判据 9b：抬上限这类**决策**必须留痕，且条目不可静默删除 ──────────────────
    pd = ledger.get("policy_decisions", [])
    if not pd:
        bad.append(
            "台账缺 `policy_decisions` ⇒「**抬上限**」这类决策没有留痕"
            "（条目只许缩短 ⇒ 不可静默删除）"
        )
    for d in pd:
        for key in ("what", "decided_by", "why", "invariant", "targets"):
            if not str(d.get(key) or "").strip():
                bad.append(f"决策 {d.get('id', '?')}：缺 `{key}`（决策必须写清 谁裁的 / 为什么 / 不变式 / 靶子）")

    # ── 判据 9：本单未固化项只许缩短 ──────────────────────────────────────────
    ns = ledger.get("not_solidified", [])
    if len(ns) > NOT_SOLIDIFIED_FROZEN:
        bad.append(f"未固化项 {len(ns)} > 上限 {NOT_SOLIDIFIED_FROZEN} ⇒ 只许缩短")
    for item in ns:
        if not str(item.get("reason") or "").strip():
            bad.append(f"未固化项 {item.get('id', '?')}：缺 `reason`")
        if not str(item.get("restart_when") or "").strip():
            bad.append(f"未固化项 {item.get('id', '?')}：缺 `restart_when`（重启条件）")

    return bad


def check_discriminating_power(*, skill_text: str, cicd_text: str, ledger: dict,
                              file_text: Callable[[str], str | None] = real_file_text) -> dict:
    """判别力自证：三种坏形态**各自**必须在内存里判红（本仓 §17.3 的口径）。"""
    base = json.loads(json.dumps(ledger))          # 深拷贝：变异发生在内存对象上

    no_boundary = skill_text.replace(BOUNDARY_HEADING, "### 25.6 （标题被删）", 1)

    dropped_id = sorted({e["id"] for e in ledger["entries"]})[0]
    skill_without_one = re.sub(rf"\b{re.escape(dropped_id)}\b", "FM-X0", skill_text)

    unregistered = skill_text.replace(SECTION_HEADING, SECTION_HEADING + "\n\n- `FM-A99` 一条没登记的纪律\n", 1)

    prose_only = json.loads(json.dumps(base))
    prose_only["entries"][0]["kind"] = "prose"

    new_gap = json.loads(json.dumps(base))
    new_gap["ci_findings"].append({
        "id": "FM-E99", "state": "gap", "gap_owner": "x", "gap_shows_when": "y",
    })

    return {
        "no_boundary": ledger_violations(skill_text=no_boundary, cicd_text=cicd_text,
                                         ledger=base, file_text=file_text),
        "dropped_id": ledger_violations(skill_text=skill_without_one, cicd_text=cicd_text,
                                        ledger=base, file_text=file_text),
        "unregistered": ledger_violations(skill_text=unregistered, cicd_text=cicd_text,
                                          ledger=base, file_text=file_text),
        "prose_only": ledger_violations(skill_text=skill_text, cicd_text=cicd_text,
                                        ledger=prose_only, file_text=file_text),
        "new_gap": ledger_violations(skill_text=skill_text, cicd_text=cicd_text,
                                     ledger=new_gap, file_text=file_text),
        "empty_skill": ledger_violations(skill_text="", cicd_text=cicd_text,
                                         ledger=base, file_text=file_text),
        "control_comment_only": ledger_violations(
            skill_text=skill_text + "\n<!-- 只加一条注释：不改任何记号、不改任何声明 -->\n",
            cicd_text=cicd_text, ledger=base, file_text=file_text),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 断言层
# ──────────────────────────────────────────────────────────────────────────────

def _require(text: str | None, rel: str) -> str:
    """路径漂移 ⇒ 红（**不得静默跳过**：判据依赖的语料读不到时，「没东西可判」不是通过）。"""
    if text is None:
        raise AssertionError(f"判据依赖的语料不存在：{rel}（路径漂移 ⇒ 红，不得静默跳过）")
    return text


def _live() -> tuple[str, str, dict]:
    skill_text = _require(real_file_text(SKILL_REL), SKILL_REL)
    cicd_text = _require(real_file_text(CICD_REL), CICD_REL)
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return skill_text, cicd_text, ledger


def test_real_files_are_clean() -> None:
    """判据 1~9 在**当前仓库**上全绿；红 = 逐条问题见断言文案。"""
    skill_text, cicd_text, ledger = _live()
    bad = ledger_violations(skill_text=skill_text, cicd_text=cicd_text, ledger=ledger)
    assert bad == [], "研发模式固化台账未通过：\n" + "\n".join(f"  - {p}" for p in bad)


def test_policy_decision_record_is_load_bearing() -> None:
    """判别力自证：删掉 `policy_decisions`（抬上限的决策留痕）⇒ 必红。"""
    skill_text, cicd_text, ledger = _live()
    folded = json.loads(json.dumps(ledger))
    folded.pop("policy_decisions", None)
    bad = ledger_violations(skill_text=skill_text, cicd_text=cicd_text, ledger=folded)
    assert any("policy_decisions" in p for p in bad), bad
    stripped = json.loads(json.dumps(ledger))
    stripped["policy_decisions"][0]["decided_by"] = "  "
    bad2 = ledger_violations(skill_text=skill_text, cicd_text=cicd_text, ledger=stripped)
    assert any("decided_by" in p for p in bad2), bad2


def test_empty_skill_corpus_is_not_silently_green() -> None:
    """判据 10：空语料 ⇒ 非空违规（「没东西可判 ⇒ 绿」是被明确拒绝的形态）。"""
    _, cicd_text, ledger = _live()
    bad = ledger_violations(skill_text="", cicd_text=cicd_text, ledger=ledger)
    assert bad != [], "空技能文本被判绿 ⇒ 判据会静默空跑"


def test_discriminating_power_in_memory() -> None:
    """**判别力自证**：每种坏形态各自判红，且只改注释**不**判红（对照读数）。

    三种坏形态**当场在内存里构造**（不改磁盘）—— 依据 = `docs/wiki/CI-CD.md` 的
    「红证机具的可靠性：改磁盘文件的变异**可能不被读到**」节。
    """
    skill_text, cicd_text, ledger = _live()
    r = check_discriminating_power(skill_text=skill_text, cicd_text=cicd_text, ledger=ledger)

    assert any("覆盖面登记子节" in p for p in r["no_boundary"]), r["no_boundary"]
    assert any("技能节里**没有**写" in p for p in r["dropped_id"]), r["dropped_id"]
    assert any("未登记即红" in p for p in r["unregistered"]), r["unregistered"]
    assert any("只写了劝告" in p for p in r["prose_only"]), r["prose_only"]
    assert any("未守护（gap）条数" in p for p in r["new_gap"]), r["new_gap"]
    assert r["empty_skill"] != [], r["empty_skill"]
    assert r["control_comment_only"] == [], (
        "只加一条注释就判红 ⇒ 判据在误伤（对照读数必须为空）"
    )


def test_mutation_harness_really_changes_the_text() -> None:
    """证明「变异真的被读到了」（否则上面那条自证也可能是空断言）。"""
    skill_text, cicd_text, ledger = _live()
    deep = json.loads(json.dumps(ledger))
    r = check_discriminating_power(skill_text=skill_text, cicd_text=cicd_text, ledger=deep)
    assert r["control_comment_only"] != r["no_boundary"], "对照读数与注入读数相同 ⇒ 变异没生效"
    mutated_skill = skill_text.replace(BOUNDARY_HEADING, "### 25.6 （标题被删）", 1)
    assert mutated_skill != skill_text, "内存构造的变异体与原文本逐字相同"
    assert BOUNDARY_HEADING not in mutated_skill
    assert deep == ledger, "变异泄漏进了基准台账对象"


def test_boundary_section_names_the_out_of_scope_forms() -> None:
    """边界节必须写清「本清单覆盖不到什么」（不是一句「见上文」）。"""
    skill_text, _, _ = _live()
    bnd = _require(section_text(skill_text, BOUNDARY_HEADING), BOUNDARY_HEADING)
    for marker in ("kind=action", "FM-", "evidence"):
        assert marker in bnd, f"覆盖面登记缺 `{marker}` 这一面"


# ──────────────────────────────────────────────────────────────────────────────
# 判据 11/12：本单补的两条「反复出错点」判据（清单 E 的 E7 / E8）
# ──────────────────────────────────────────────────────────────────────────────

def case_id_lines(text: str) -> list[str]:
    return re.findall(r"^\s*-\s*id:\s*([A-Z]+-\d+)\s*$", text, re.MULTILINE)


def migration_versions(names: list[str]) -> list[str]:
    return [m.group(1) for n in names if (m := re.match(r"V(\d+)__", n))]


def duplicate_ids(texts: list[str]) -> dict[str, int]:
    seen: dict[str, int] = {}
    for t in texts:
        for cid in case_id_lines(t):
            seen[cid] = seen.get(cid, 0) + 1
    return {k: v for k, v in seen.items() if v > 1}


def test_case_ids_are_unique_across_the_corpus() -> None:
    """判据 11（**抢号即红**）：用例号在 `.github/cases/**` 里全局唯一。

    **治的形态**：两个并行包各自「取现取最大号 + 1」⇒ 双双写成同一个新号；先合的那个无事，
    **后合的**把重号带进 main（本会话实测 7 次：UI-061 / UI-064 / MC-022 / MC-023 / BM-019 …）。
    修法不是「rebase 后再查一次」这句劝告 —— 而是**把唯一性变成判据**：重号一进 PR，
    这条判据在那个 PR 上就红（**红在后合的那一个**，正是它需要改号的那一个）。
    """
    lines = []
    for p in sorted((REPO_ROOT / CASE_CORPUS_DIR).glob("*.yml")):
        lines.append(p.read_text(encoding="utf-8"))
    assert lines, f"{CASE_CORPUS_DIR} 下没有语料 ⇒ 判据会静默空跑（fail-closed）"
    total = sum(len(case_id_lines(t)) for t in lines)
    assert total > 0, "语料里一个用例号都没取到 ⇒ 解析口径失效"
    dups = duplicate_ids(lines)
    assert dups == {}, f"用例号重号（抢号形态）：{dups}"


def test_case_id_duplicate_is_detected_in_memory() -> None:
    """判据 11 的判别力自证：内存里构造两处同号 ⇒ 必被抓到。"""
    a = "cases:\n  - id: MC-001\n  - id: MC-002\n"
    b = "cases:\n  - id: MC-002\n  - id: MC-003\n"
    assert duplicate_ids([a, b]) == {"MC-002": 2}
    assert duplicate_ids([a, "cases:\n  - id: MC-003\n"]) == {}


def test_migration_versions_are_unique_in_the_live_dir() -> None:
    """判据 12（**抢号即红**，射程 = **活的**迁移目录）：版本号在 `db/migration` 里唯一。

    **射程为什么只到 `db/migration`（明确的边界）**：`db/migration-archive/` 里**存量**就有
    版本号重复（实测 `ARCHIVE_DUP_VERSIONS_FROZEN` 个 V 号各两份、文件名不同）——
    它已冻结、不再新增 ⇒ 把唯一性套到归档上会是**存量假红**。抢号只发生在**新写的**那一个目录里。
    与既有判据的分工：`tests/unit_ci_workflows/test_migration_immutability.py` 判的是
    **文件名**在两个载体目录间不重复 + 已登记文件逐字节冻结，**不判版本号**。
    """
    d = REPO_ROOT / LIVE_MIGRATION_DIR
    names = sorted(p.name for p in d.glob("V*.sql"))
    assert names, f"{LIVE_MIGRATION_DIR} 下没有迁移 ⇒ 判据会静默空跑（fail-closed）"
    versions = migration_versions(names)
    counts: dict[str, int] = {}
    for v in versions:
        counts[v] = counts.get(v, 0) + 1
    dups = {k: v for k, v in counts.items() if v > 1}
    assert dups == {}, f"活的迁移目录里版本号重号（抢号形态）：{dups} —— Flyway 会在应用时炸"


def test_archive_duplicate_versions_are_registered_and_only_shrink() -> None:
    """判据 12 的边界台账：归档目录里的重号**只许缩短**（现取 ≤ 冻结值）。"""
    d = REPO_ROOT / "backend/admin-api/src/main/resources/db/migration-archive"
    names = sorted(p.name for p in d.glob("V*.sql"))
    counts: dict[str, int] = {}
    for v in migration_versions(names):
        counts[v] = counts.get(v, 0) + 1
    live_dups = sorted(k for k, v in counts.items() if v > 1)
    assert len(live_dups) <= ARCHIVE_DUP_VERSIONS_FROZEN, (
        f"归档目录重号 V 号 {live_dups} 多于冻结上限 {ARCHIVE_DUP_VERSIONS_FROZEN}"
    )


def registered_anchor_problems(*, ledger: dict,
                              file_text: Callable[[str], str | None] = real_file_text) -> list[str]:
    """每条 `state=registered` 的 `ledger_ref` 必须**可被打断**：删掉锚的**全部**出现 ⇒ 必须判红。

    🔴 **实测教训（本单第一次写错了，红证当场抓住）**：我原先按「锚在该文件里**恰好出现 1 次**」判，
    而真实失效形态是「**只删其中一处** ⇒ 仍解析得到 ⇒ 0 条违规」⇒ 那句「删掉这段 ⇒ 红」是**空断言**。
    ⇒ 语义改成 **删掉锚的全部出现**（这才是「删掉这条登记 ⇒ 红」的正确读法），
    并要求**面内 ≥1 条**（0 条 = 判据空跑，**未跑 ≠ 通过**）。
    """
    bad: list[str] = []
    applicable = 0
    for f in ledger.get("ci_findings", []):
        if f.get("state") != "registered":
            continue
        fid = str(f.get("id", "?"))
        ref = str(f.get("ledger_ref") or "")
        path, _, anchor = ref.partition(ANCHOR_SEP)
        if not path or not anchor:
            bad.append(f"{fid}：state=registered 但 `ledger_ref` 不是 `<path>::<锚>` 形态：{ref!r}")
            continue
        text = file_text(path)
        if text is None:
            bad.append(f"{fid}：`ledger_ref` 的载体不存在：{path}")
            continue
        if anchor not in text:
            bad.append(f"{fid}：`ledger_ref` 的锚在载体里找不到：{ref}")
            continue
        applicable += 1
        stripped = text.replace(anchor, "")
        reader = (lambda rel, _p=path, _s=stripped, _f=file_text: _s if rel == _p else _f(rel))
        viol = ledger_violations(skill_text=reader(SKILL_REL) or "", cicd_text=reader(CICD_REL) or "",
                                 ledger=ledger, file_text=reader)
        if not any(fid in p for p in viol):
            bad.append(
                f"{fid}：删掉锚「{anchor}」的**全部**出现后不判红 ⇒ 这条登记挂在**打不断**的锚上（空断言）"
            )
    if applicable == 0:
        bad.append("面内 0 条 `state=registered` 条目 ⇒ 判据空跑（**未跑 ≠ 通过**，fail-closed）")
    return bad


def test_registered_anchors_are_breakable() -> None:
    """常驻自证：每条 `registered` 的登记锚都**可被打断**（本单实测踩过「删一处不红」）。"""
    _, _, ledger = _live()
    bad = registered_anchor_problems(ledger=ledger)
    assert bad == [], "registered 登记锚不可打断：\n" + "\n".join(f"  - {p}" for p in bad)


def test_registered_anchor_check_has_discriminating_power() -> None:
    """判别力自证（内存构造）：① 面内 0 条 ⇒ 红（防空跑）；② 载体不存在 ⇒ 红；③ 正常 ⇒ 绿。"""
    _, _, ledger = _live()
    assert registered_anchor_problems(ledger=ledger) == []
    empty = json.loads(json.dumps(ledger))
    empty["ci_findings"] = [f for f in empty["ci_findings"] if f.get("state") != "registered"]
    assert registered_anchor_problems(ledger=empty) != []
    broken = json.loads(json.dumps(ledger))
    nxt = next(f for f in broken["ci_findings"] if f.get("state") == "registered")
    nxt["ledger_ref"] = "docs/wiki/NO_SUCH_CARRIER.md::whatever"
    assert registered_anchor_problems(ledger=broken) != []


def boundary_problems(doc_text: str, boundary: str = CASE_ID_ALLOCATION_BOUNDARY) -> list[str]:
    """取号判据的**边界声明**必须写在文件里并带实证锚（删掉声明或删掉实证 ⇒ 红）。"""
    bad: list[str] = []
    if boundary not in doc_text:
        bad.append(f"取号判据的边界声明不在文件里：{boundary!r}")
    for marker in CASE_ID_ALLOCATION_EVIDENCE:
        if marker not in doc_text:
            bad.append(f"边界声明缺少撞号实证锚 `{marker}`（实证不许匿名）")
    return bad


def test_case_id_allocation_boundary_is_registered() -> None:
    """判据 11/12 的**覆盖面登记**：只看已合并状态 ⇒ 拦不住「main + 在飞分支」的撞号。

    没有这一条，那两条唯一性判据会给人一个它**并不具备**的保护感
    （「既不加强也不登记」正是本单要治的形态）。
    """
    bad = boundary_problems(__doc__ or "")
    assert bad == [], "取号判据的边界未登记：\n" + "\n".join(f"  - {p}" for p in bad)


def test_boundary_registration_has_discriminating_power() -> None:
    """边界登记的判别力自证（内存构造，不改磁盘）。"""
    doc = __doc__ or ""
    assert boundary_problems(doc) == []
    assert boundary_problems(doc.replace(CASE_ID_ALLOCATION_BOUNDARY, "（声明被删）")) != []
    assert boundary_problems(doc.replace("MC-027", "MC-0XX")) != []


def test_migration_duplicate_is_detected_in_memory() -> None:
    """判据 12 的判别力自证：内存里构造同号两个文件 ⇒ 必被抓到。"""
    assert migration_versions(["V133__a.sql", "V133__b.sql"]) == ["133", "133"]
    counts: dict[str, int] = {}
    for v in migration_versions(["V133__a.sql", "V133__b.sql", "V134__c.sql"]):
        counts[v] = counts.get(v, 0) + 1
    assert {k: v for k, v in counts.items() if v > 1} == {"133": 2}
    assert migration_versions(["V132__x.sql"]) == ["132"]
