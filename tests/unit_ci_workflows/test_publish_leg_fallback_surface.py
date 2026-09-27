# case_ids: MC-039
"""发布 / 守护腿的**自走触发面**必须有兜底面 —— `FM-E17` 的收口（issue #5707；用户 2026-09-27 逐字裁定 = 方案 A）。

## 病（两次现场实证，不是推断）

| 事实 | 现取读数（2026-09-27，可复算） |
|---|---|
| 自走触发面 == {`push`} 的腿 | **2 条**：`.github/workflows/worker-h5-publish.yml` · `.github/workflows/bmini-h5-publish.yml` |
| 那个 `push` 真的会跑吗 | **基本不会**：最近 200 条 `push` run 覆盖 2026-09-25T09:41Z~2026-09-27T07:23Z、去重后 43 个 sha；同一窗口 `git log origin/main -40` 的 40 个 commit 里**只有 1 个**在其中 ⇒ **39/40 零 push run**（auto-merge 用 `GITHUB_TOKEN` 合并 ⇒ push run 被吞） |
| 后果 | 合并后 `/w/` `/b/` **静默停在旧产物**（无红无告警）；两次都靠人工 `workflow_dispatch` 补，其中一次 = 2026-09-27 02:25Z 的 `/b/index.html` |

⇒ 病根 = **腿的自动触发面只有 `push`**，而本仓的 `push` 是被吞的。

## 判据（每条都能单独变红；红证**全部内存构造**，见 `test_discriminating_power_in_memory`）

| # | 判据 | 语义 / 变红的形态 |
|---|---|---|
| 1 | 语料与登记表**非空**，读数现取打印 | 空语料 / 空 `legs` ⇒ 红（fail-closed：「没东西可判」不是通过） |
| 2 | 登记的腿**文件存在** | 登记表点名一个不存在的 workflow ⇒ 红（陈旧登记） |
| 3 | **未登记即红** | 全仓自走面 == {push} 的 workflow 必须在登记表里 ⇒ 新造一条 push-only 腿 ⇒ 红 |
| 4 | 条数**只许缩短** | 登记表 `frozen_max` 与判据里的上限两处不符 / 条数超上限 ⇒ 红 |
| 5 | **兜底面必须在位** | 每条登记腿的自走面 ∩ {`schedule`, `workflow_run`} ≠ ∅ ⇒ 删掉兜底面、或换成 `workflow_dispatch`（**手动面冒充兜底**）⇒ 红 |
| 6 | 登记表**声明 == 现取**（双向） | 声明的 `event` + `cron` 必须逐字出现在该 workflow 的 `on:` 里 ⇒ 台账不许「给不存在的保护盖章」 |
| 7 | `workflow_run` 上游名**可解析** | 上游名必须命中仓内某 workflow 的 `name:` ⇒ 上游改名后该兜底面**静默脱钩**（永不触发），判红 |
| 8 | 登记表 ⇄ 判据里的冻结元组 | 删一条登记（或加一条）⇒ 红（两处一起改才生效，diff 里可见） |

## 判定方式是确定的（零网络、零时钟）

本判据**只读仓内文件**（`.github/workflows/*.yml` + 本目录的登记表 JSON）⇒ 同一份代码在任何时刻给出**同一读数**。
反例（**刻意不进判据**）：`gh run list …` 这类运行期计数会随时刻变 ⇒ 它只作为**当时的读数 + 复算命令**写在
登记表与 `docs/wiki/CI-CD.md` 的 `FM-E17` 节里。

## 覆盖面（照实登记，**不是**「已全覆盖」）

逐条写在登记表 `coverage_boundary` 里：cron 节流 / concurrency 顶掉 / 「腿跑了但内容不对」/ `workflow_run` 上游自己没跑 /
`push` 被吞这一运行期事实 / 「兜底面在位」≠「线上字节 == main HEAD」/ 已登记腿之外的新族 / `deploy-reconcile` 那层不重复判。
`test_coverage_boundary_is_registered` 逐条核「有 face + reason + recompute」⇒ 删掉任一条 ⇒ 红。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Mapping

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO / ".github" / "workflows"
LEDGER_PATH = Path(__file__).with_name("publish_leg_fallback_ledger.json")

# 手动面与被调面：它们**不能**让一条腿自己跑起来，故不计入「自走面」。
MANUAL_EVENTS = frozenset({"workflow_dispatch", "workflow_call"})
# 兜底面认的事件（`FM-E17` 口径：`schedule` 或 `workflow_run` 之一）。
FALLBACK_EVENTS = frozenset({"schedule", "workflow_run"})
# 触发面只有它 ⇒ 需要兜底（这就是要判的形状本身）。
PUSH_ONLY = frozenset({"push"})
# 发布 / 守护腿的冻结元组（现取 2 条）。改它必须同批改登记表 ⇒ diff 里看得见。
PUBLISH_LEG_FILES_FROZEN = ("worker-h5-publish.yml", "bmini-h5-publish.yml")
# 登记条数上限（只许缩短）；与登记表 `frozen_max` 两处一起改才生效。
LEGS_FROZEN = 2
#: 覆盖面登记每条必须带的键（缺一 ⇒ 红；「缺口不许匿名存在」）。
BOUNDARY_KEYS = ("face", "reason", "recompute")


def on_block(wf: object) -> dict:
    """`on:` 的**真 YAML** 形态（裸 `on:` 会被 yaml 解析成布尔键 `True`；也兼容列表 / 字符串写法）。"""
    if not isinstance(wf, dict):
        return {}
    on = wf.get("on")
    if on is None and True in wf:
        on = wf.get(True)
    if isinstance(on, str):
        return {on: {}}
    if isinstance(on, list):
        return {str(e): {} for e in on}
    return on if isinstance(on, dict) else {}


def self_starting_surface(wf: object) -> frozenset[str]:
    """「自走面」= 不需要人手点、也不需要别的 workflow 调用就能起跑的顶层事件。"""
    return frozenset(e for e in on_block(wf) if e not in MANUAL_EVENTS)


def schedule_crons(wf: object) -> list[str]:
    sched = on_block(wf).get("schedule")
    if not isinstance(sched, list):
        return []
    return [str(e.get("cron")) for e in sched if isinstance(e, dict) and e.get("cron")]


def workflow_run_upstreams(wf: object) -> list[str]:
    wr = on_block(wf).get("workflow_run")
    if not isinstance(wr, dict):
        return []
    ups = wr.get("workflows")
    if isinstance(ups, str):
        return [ups]
    return [str(u) for u in ups] if isinstance(ups, list) else []


def workflow_name(wf: object) -> str:
    return str(wf.get("name")) if isinstance(wf, dict) and wf.get("name") else ""


def _parse(value: object, rel: str, bad: list[str]) -> dict | None:
    """语料值 → 解析后的 mapping。

    **可以**直接喂解析后的 dict：红证因此不必做「序列化往返 / 改磁盘再读」——
    依据 `docs/wiki/CI-CD.md` 的「红证机具的可靠性：改磁盘文件的变异**可能不被读到**」节。
    真跑一律喂原文（`str`）。
    """
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        bad.append(f"{rel}：语料既不是原文也不是 mapping（{type(value).__name__}）⇒ 红")
        return None
    try:
        doc = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        bad.append(f"{rel}：YAML 解析失败（{exc.__class__.__name__}）⇒ 判据无从判定（fail-closed）")
        return None
    if not isinstance(doc, dict):
        bad.append(f"{rel}：顶层不是 mapping（{type(doc).__name__}）⇒ 红")
        return None
    return doc


def fallback_problems(*, workflows: Mapping[str, object], registry: object) -> list[str]:
    """全部违规（空列表 = 全绿）。**纯函数**：只吃语料 + 登记表，不读盘、不触网、不看时钟。"""
    bad: list[str] = []

    # ── 判据 1：语料与登记表非空（fail-closed）───────────────────────────────
    if not workflows:
        bad.append("workflow 语料为空 ⇒ 判据无从判定（**未跑 ≠ 通过**，fail-closed）")
    reg = registry if isinstance(registry, dict) else {}
    if not isinstance(registry, dict):
        bad.append(f"登记表顶层不是 mapping（{type(registry).__name__}）⇒ fail-closed")
    raw_legs = reg.get("legs")
    if not isinstance(raw_legs, list) or not raw_legs:
        bad.append("登记表 `legs` 为空 ⇒ 「未登记即红」的另一半无从判定（fail-closed）")
        raw_legs = []
    legs = [leg for leg in raw_legs if isinstance(leg, dict)]
    if len(legs) != len(raw_legs):
        bad.append("登记表 `legs` 里有条目不是 mapping ⇒ 形态不合法")

    # 语料解析
    parsed: dict[str, dict] = {}
    for rel in sorted(workflows):
        doc = _parse(workflows[rel], rel, bad)
        if doc is not None:
            parsed[rel] = doc
    names = {workflow_name(d) for d in parsed.values()} - {""}

    # ── 判据 2：登记的腿必须**存在**（陈旧登记 ⇒ 红）─────────────────────────
    live_files = {leg.get("file") for leg in legs}
    for leg in legs:
        rel = leg.get("file")
        if not isinstance(rel, str) or rel not in parsed:
            bad.append(
                f"登记表的腿 {rel!r} 在 `.github/workflows/` 的语料里不存在 ⇒ 陈旧登记"
                f"（现取语料 {len(parsed)} 个文件）"
            )

    # ── 判据 3：未登记即红（自走面 == {push} 的形状必须登记）────────────────
    for rel, doc in parsed.items():
        if self_starting_surface(doc) == PUSH_ONLY and rel not in live_files:
            bad.append(
                f"{rel}：自走触发面 == {{push}}（手动面不算）而登记表里没有它 ⇒ **未登记即红**"
                f" —— 本仓的 push 会被 GITHUB_TOKEN 合并吞掉 ⇒ 这条腿不会跑且无红"
            )

    # ── 判据 4：只许缩短（上限两处一起改才生效）─────────────────────────────
    cap = reg.get("frozen_max")
    if cap != LEGS_FROZEN:
        bad.append(
            f"登记表 `frozen_max`={cap!r} 与判据里的 `LEGS_FROZEN`={LEGS_FROZEN} 不符 ⇒ "
            f"改上限必须同批改两处（只在 diff 里可见）"
        )
    if len(legs) > LEGS_FROZEN:
        bad.append(f"登记条数 {len(legs)} > 冻结上限 {LEGS_FROZEN} ⇒ 只许缩短")

    # ── 判据 5/6：兜底面必须在位；登记表的声明必须 == 现取（双向）─────────────
    for leg in legs:
        rel = leg.get("file")
        doc = parsed.get(rel) if isinstance(rel, str) else None
        if doc is None:
            continue
        surface = self_starting_surface(doc)
        if not (surface & FALLBACK_EVENTS):
            bad.append(
                f"{rel}：自走触发面 = {sorted(surface)}，**没有兜底面**"
                f"（{sorted(FALLBACK_EVENTS)} 至少要有其一）⇒ 本仓 push 被吞时这条腿不会跑且无红"
            )
            continue
        decl = leg.get("fallback")
        if not isinstance(decl, dict):
            bad.append(f"{rel}：登记表缺 `fallback`（声明的兜底面）⇒ 台账不许只写「有兜底」")
            continue
        event = decl.get("event")
        if event not in surface:
            bad.append(
                f"{rel}：登记表声明兜底面 `{event}`，而现取自走面 {sorted(surface)} 里**没有**它 ⇒ "
                f"台账在**给不存在的保护盖章**"
            )
            continue
        if event == "schedule":
            want = decl.get("cron")
            got = schedule_crons(doc)
            if want not in got:
                bad.append(
                    f"{rel}：登记表声明 cron `{want}`，现取 schedule = {got} ⇒ 声明与现取脱钩"
                    f"（改 cron 必须同批改登记表）"
                )

    # ── 判据 7：`workflow_run` 的上游名必须能解析（**全仓面**，不限于已登记腿）──
    # 上游改名 ⇒ 这个兜底面**永远不会触发**，而任何东西都不会红（静默脱钩）。
    for rel, doc in parsed.items():
        for up in workflow_run_upstreams(doc):
            if up not in names:
                bad.append(
                    f"{rel}：`workflow_run` 的上游名 `{up}` 命中不了 `.github/workflows/` 里任何 `name:` "
                    f"⇒ 该兜底面静默脱钩（上游改名 / 拼错后本 workflow **永不触发**）"
                )

    # ── 判据 8：登记表与判据里的冻结元组双向相等 ──────────────────────────────
    frozen = set(PUBLISH_LEG_FILES_FROZEN)
    live = {f for f in live_files if isinstance(f, str)}
    if live != frozen:
        bad.append(
            f"登记表与判据里的冻结元组不一致：登记表 {sorted(live)} / 冻结 {sorted(frozen)} ⇒ "
            f"删一条（或加一条）必须同批改两处，不许只改一侧"
        )

    # ── 覆盖面登记：每条必须点名「盖不到什么 + 怎么复算」──────────────────────
    boundary = reg.get("coverage_boundary")
    if not isinstance(boundary, list) or not boundary:
        bad.append("登记表缺 `coverage_boundary`（覆盖面登记）⇒ 「覆盖面」不许缺席")
    else:
        for i, item in enumerate(boundary):
            if not isinstance(item, dict):
                bad.append(f"`coverage_boundary[{i}]` 不是 mapping")
                continue
            for key in BOUNDARY_KEYS:
                if not str(item.get(key) or "").strip():
                    bad.append(f"`coverage_boundary[{i}]` 缺 `{key}`（缺口不许匿名存在）")

    return bad


# ──────────────────────────────────────────────────────────────────────────────
# 读盘 + 断言层
# ──────────────────────────────────────────────────────────────────────────────

def _live() -> tuple[dict, dict]:
    """真语料 + 登记表（缺一 ⇒ 抛错，**不是**静默跳过：路径漂移必须判红）。"""
    workflows: dict[str, object] = {}
    for pattern in ("*.yml", "*.yaml"):
        for path in sorted(WORKFLOWS_DIR.glob(pattern)):
            workflows[path.name] = path.read_text(encoding="utf-8")
    if not workflows:
        raise AssertionError(f"workflow 语料为空：{WORKFLOWS_DIR}（路径漂移 ⇒ 红，不得静默跳过）")
    if not LEDGER_PATH.exists():
        raise AssertionError(f"登记表不存在：{LEDGER_PATH}（fail-closed）")
    return workflows, json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def test_real_workflows_and_ledger_are_clean() -> None:
    """判据 1~8 在**当前仓库**上全绿；红 = 逐条问题见断言文案。"""
    workflows, registry = _live()
    bad = fallback_problems(workflows=workflows, registry=registry)
    assert bad == [], "发布腿兜底面判据未通过：\n" + "\n".join(f"  - {p}" for p in bad)


def test_live_counts_are_printed_and_not_empty() -> None:
    """反空跑读数：语料 / 登记条数 / 现取 push-only 形状条数**现取**打印；取空 ⇒ 红。"""
    workflows, registry = _live()
    legs = registry.get("legs")
    push_only = sorted(
        rel for rel, raw in workflows.items()
        if self_starting_surface(yaml.safe_load(raw)) == PUSH_ONLY
    )
    print(
        f"[publish-leg-fallback] workflows={len(workflows)} legs={len(legs or [])} "
        f"push_only_now={len(push_only)} → {push_only}"
    )
    assert workflows, "workflow 语料为空 ⇒ 判据空跑（**未跑 ≠ 通过**）"
    assert legs, "登记表 `legs` 为空 ⇒ 判据空跑"
    assert not push_only, (
        f"仍有自走面 == {{push}} 的腿 ⇒ 兜底面没补上（现取：{push_only}）"
    )


def check_discriminating_power(*, workflows: dict, registry: dict) -> dict[str, list[str]]:
    """每种坏形态**当场在内存里构造**（不改磁盘），逐个喂给纯函数。

    依据 `docs/wiki/CI-CD.md` 的「红证机具的可靠性：改磁盘文件的变异**可能不被读到**」节：
    坏形态直接喂**解析后的结构**，不做「改磁盘 → 重新读」的往返。
    """
    # 现取：第一条登记腿 + 一份真的带兜底面的 workflow（都不写死文件名以外的东西）
    leg_rel = str(registry["legs"][0]["file"])
    fallback_event = str(registry["legs"][0]["fallback"]["event"])
    assert fallback_event == "schedule", f"本次红证只覆盖 schedule 兜底，现取 {fallback_event!r}"

    # ⚠️ **必须用 `copy.deepcopy`，不许用 JSON 往返**（`json.dumps` 会把裸 `on:` 解析出的
    # **布尔键 `True` 变成字符串 `"true"`** ⇒ 变异体的事件集当场变空 ⇒ 判据看的已经不是原对象，
    # 红证会变成空断言。本机实测：用 JSON 往返时 `on_block(doc)` 取不到 `workflow_run`（KeyError）。
    def _mutate_wf(rel: str, fn) -> dict:
        doc = copy.deepcopy(yaml.safe_load(workflows[rel]))
        on = on_block(doc)
        fn(on)
        return {**workflows, rel: doc}

    def _discard_fallback(on: dict) -> None:
        on.pop("schedule", None)

    def _manual_instead(on: dict) -> None:
        on.pop("schedule", None)
        on["workflow_dispatch"] = None

    # 只改注释（对照读数）：走**原文**路径，证明注释不进判定
    comment_only = {**workflows}
    comment_only[leg_rel] = workflows[leg_rel] + "\n# 只加一条注释：不改任何事件、不改任何 cron\n"
    assert comment_only[leg_rel] != workflows[leg_rel], "内存构造的变异体与原文本逐字相同（变异没生效）"

    # 登记表坏形态
    ledger_minus_one = copy.deepcopy(registry)
    ledger_minus_one["legs"] = ledger_minus_one["legs"][1:]
    empty_ledger = copy.deepcopy(registry)
    empty_ledger["legs"] = []
    missing_file = copy.deepcopy(registry)
    missing_file["legs"][0]["file"] = "no-such-workflow.yml"
    declared_not_actual = copy.deepcopy(registry)
    declared_not_actual["legs"][0]["fallback"]["cron"] = "0 0 * * *"
    no_boundary = copy.deepcopy(registry)
    no_boundary["coverage_boundary"] = []

    # 新造一条 push-only 腿（未登记）
    new_leg = f"{leg_rel}.fake"
    ghost = {**workflows, new_leg: "name: 新造的 push-only 腿\non:\n  push:\n    branches: [main]\n  workflow_dispatch:\n"}

    # `workflow_run` 上游名解析不到（全仓面）
    dangling = None
    for rel, raw in workflows.items():
        if workflow_run_upstreams(yaml.safe_load(raw)):
            doc = copy.deepcopy(yaml.safe_load(raw))
            on_block(doc)["workflow_run"]["workflows"] = ["No Such Upstream Workflow"]
            dangling = {**workflows, rel: doc}
            break
    assert dangling, "语料里找不到任何带 `workflow_run` 的 workflow ⇒ 判据 7 的红证无从构造"

    return {
        "no_fallback": fallback_problems(workflows=_mutate_wf(leg_rel, _discard_fallback), registry=registry),
        "manual_only": fallback_problems(workflows=_mutate_wf(leg_rel, _manual_instead), registry=registry),
        "ledger_minus_one": fallback_problems(workflows=workflows, registry=ledger_minus_one),
        "empty_ledger": fallback_problems(workflows=workflows, registry=empty_ledger),
        "missing_file": fallback_problems(workflows=workflows, registry=missing_file),
        "declared_not_actual": fallback_problems(workflows=workflows, registry=declared_not_actual),
        "no_boundary": fallback_problems(workflows=workflows, registry=no_boundary),
        "new_push_only_leg": fallback_problems(workflows=ghost, registry=registry),
        "dangling_upstream": fallback_problems(workflows=dangling, registry=registry),
        "control_comment_only": fallback_problems(workflows=comment_only, registry=registry),
    }


def test_discriminating_power_in_memory() -> None:
    """**判别力自证**：每种坏形态各自判红，且「只改注释」**不**判红（对照读数）。"""
    workflows, registry = _live()
    r = check_discriminating_power(workflows=workflows, registry=registry)

    assert any("没有兜底面" in p for p in r["no_fallback"]), r["no_fallback"]
    assert any("没有兜底面" in p for p in r["manual_only"]), r["manual_only"]
    assert any("给不存在的保护盖章" not in p for p in r["manual_only"]), r["manual_only"]
    assert any("不一致" in p for p in r["ledger_minus_one"]), r["ledger_minus_one"]
    assert any("`legs` 为空" in p for p in r["empty_ledger"]), r["empty_ledger"]
    assert any("陈旧登记" in p for p in r["missing_file"]), r["missing_file"]
    assert any("声明与现取脱钩" in p for p in r["declared_not_actual"]), r["declared_not_actual"]
    assert any("coverage_boundary" in p for p in r["no_boundary"]), r["no_boundary"]
    assert any("未登记即红" in p for p in r["new_push_only_leg"]), r["new_push_only_leg"]
    assert any("静默脱钩" in p for p in r["dangling_upstream"]), r["dangling_upstream"]

    # 对照：只改注释 ⇒ **不**判红（红证必须能区分「改了判定对象」与「改了说明」）
    assert r["control_comment_only"] == [], r["control_comment_only"]


def test_discriminating_power_is_not_vacuous() -> None:
    """变异自证：每种坏形态的读数**确实与原读数不同**（防「变异没生效 ⇒ 空断言」）。"""
    workflows, registry = _live()
    r = check_discriminating_power(workflows=workflows, registry=registry)
    for name in ("no_fallback", "manual_only", "ledger_minus_one", "empty_ledger",
                 "missing_file", "declared_not_actual", "no_boundary",
                 "new_push_only_leg", "dangling_upstream"):
        assert r[name], f"坏形态 {name!r} 没被判红 ⇒ 那条红证是空断言"
        assert r[name] != fallback_problems(workflows=workflows, registry=registry), (
            f"坏形态 {name!r} 的读数与基线逐字相同 ⇒ 变异没被读到"
        )


def test_coverage_boundary_is_registered() -> None:
    """覆盖面登记（**正向**）：每条必须点名 face + reason + recompute；删掉任一条 ⇒ 红。"""
    _, registry = _live()
    boundary = registry.get("coverage_boundary") or []
    assert boundary, "覆盖面登记缺失 ⇒ 「盖不到什么」没写出来（不许读成已全覆盖）"
    for item in boundary:
        for key in BOUNDARY_KEYS:
            assert str(item.get(key) or "").strip(), f"覆盖面登记缺 `{key}`：{item.get('face')!r}"
    # 判据 5 的边界必须**具名**（本单的核心：兜底面在位 ≠ 它真跑）
    faces = " ".join(str(i.get("face")) for i in boundary)
    for marker in ("节流", "concurrency", "发布内容不对", "上游自己没跑", "push", "心跳"):
        assert marker in faces, f"覆盖面登记缺 `{marker}` 这一面"


def test_self_starting_surface_semantics() -> None:
    """判据 1 的口径自证：手动面 / 被调面**不**算自走面；裸 `on:` 的布尔键形态也要认。"""
    assert self_starting_surface({"on": {"push": None, "workflow_dispatch": None}}) == {"push"}
    assert self_starting_surface({"on": {"push": None, "schedule": [{"cron": "0 0 * * *"}]}}) == {"push", "schedule"}
    assert self_starting_surface({True: {"push": None}}) == {"push"}
    assert self_starting_surface({"on": ["push", "workflow_call"]}) == {"push"}
    assert self_starting_surface({"on": "workflow_dispatch"}) == frozenset()
    assert schedule_crons({"on": {"schedule": [{"cron": "23 18 * * *"}]}}) == ["23 18 * * *"]
    assert schedule_crons({"on": {"push": None}}) == []
    assert workflow_run_upstreams({"on": {"workflow_run": {"workflows": ["X"], "types": ["completed"]}}}) == ["X"]
    assert workflow_run_upstreams({"on": {"push": None}}) == []
