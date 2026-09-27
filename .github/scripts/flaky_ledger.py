#!/usr/bin/env python3
"""CI failed-job **重跑分流** + **flaky 台账**（issue #4717）。

背景（本会话真实发生两次，别再重新猜）
--------------------------------------
- **#4713**：`new Date()` 造期望值 vs 消息时间戳 ⇒ **跨分钟边界必红**（~10~15% 随机红），
  且落在 **required** 的 `mini-app typecheck + unit tests` 里 ⇒ 随机卡住**任何** PR
  （实证 #4712：一个与 mini-app 毫无关系的 drift-audit 改动被卡）。
- **#4717**：`task-card-qr`「等 A 后**同步**断言 B」的 **commit 竞态**（晚一次 commit）。
两者同形：**随机红 ⇒ 告警疲劳 ⇒ 归因层失效**（`migao-acceptance` 点名形态）。

本模块只做 **CI 层两件事**（测试层的机械守卫 (C) 项由另一单承担）：
  ① failed job **重跑分流**：首次失败 ⇒ 自动重跑 **1 次（上限，绝不无限重跑）**；
     第二次绿 ⇒ 标 flaky（可见标注 + 记账）；第二次仍红 ⇒ **照常失败**。
  ② flaky **台账**（`.github/flaky-ledger.json`）：**只追加**、幂等、可被后续单消费；
     **推前先与 main 对齐**（并集 + 最新 main 之上重放 + `--force-with-lease` 推送，见 #5100）。

三条不变量（判据的骨头；每条都有反向红证，见
`tests/unit_ci_workflows/test_flaky_triage.py`）
------------------------------------------------
  **A. 绝不静默放行** —— 「第二次绿」**不等于**「通过」：分流只产出「标注 + 记账」，
     并由 workflow 侧**卸下 auto-merge**（`gh pr merge --disable-auto` + `block/merge`）。
     判据形态：`mark_flaky` 只可能来自 `rerun_result == "success"`（纯函数可证）。
  **B. 绝不误判 infra** —— `cancelled` / `timed_out` / `startup_failure` / `stale` /
     `action_required` 的运行，以及**从未真正跑起来的 job**（无 steps）、
     只在「取代码 · 装依赖」步骤失败的 job ⇒ **既不算 flaky、也不重跑**。
  **C. 绝不重复记账** —— 幂等键 = `(workflow, run_id, job)`：同一次失败被重跑/重判多次
     只留 **一条**（`append_entries` 对批内 + 存量都去重）。

⚠️ **判据方向一律 fail-safe**：分类不确定时倾向 **infra_suspect**（= 不打 flaky 标、
不卸 auto-merge、但**仍然记账**）—— 宁可漏标一条 flaky（可见、可补），
不可把 infra 抖动记成 flaky（那会把台账本身变成噪音源）。

#5307：回填路径**曾经不存在** ⇒ 台账自我死锁（本单修）
-------------------------------------------------------
台账 schema 逐字写着 `follow_up`「CI 生成时为 null，由**分诊方**回填」，但**回填路径不存在**：
`append_entries` 对同幂等键**跳过**（幂等：重复追加是**无副作用**的空操作）⇒ 用 append 回填 = 无效；
CLI 又没有回填子命令 ⇒ 回填变成「**文档要求做、却没有合法工具做**」的动作。而 **required** 测试
`tests/unit_ci_workflows/test_flaky_triage.py::TestReconcile::test_shipped_ledger_reconciles_clean`
判「台账必须 reconcile 干净」⇒ 只要存在一条 `kind=flaky` / `status=open` / `follow_up=null`，
**台账分支永远绿不了** ⇒ **台账永远落不了 main**（实测：分支 4 条欠账 ⇒ 4 次尝试同形确定性失败、
台账停摆约 40 小时且**无人发现**）。
⇒ ① 新增 `follow-up` 子命令（**字段级**回填：只改 `follow_up`(/`status`/`fixed_by`)，
**不**新增/删除/重排条目）；② 欠账清单 + **可直接复制**的回填命令落进 `reconcile` 输出与
`flaky-ledger-reconcile.yml` 的 job summary（可见性：那条红此前**没有任何消费面**）。

#5310：判据不许跨时刻读数（本单修）
----------------------------------
`ledger-drift` 的 main 侧旧口径 = `--main-file`（= 工作区 = **job 启动时的检出快照**），
而 PR 侧是**实时** `gh pr list` ⇒ 台账 PR 在这个窗口里被合并，就得到「落后 N 条 + 无 PR」的**假红**
（实测 run `35951257498`：启动 03:23:37、报错 03:23:55，而台账 PR #5139 在 03:23:46 合并；
它报「24 条未落仓」= 分支 72 − **旧快照** main 48，而真实 key 差 = **ahead 0 / behind 0**）。
⇒ main 侧改**实时**读（`--main-live`：`gh api` 取 `main` 上的该文件）；`ahead == 0` ⇒ **零动作**
（与既有的「无漂移 ⇒ 零动作」同一条），报错文案给**真能改变结果**的出口。

#5301 判据②：台账分支的失败 job **必须有自动重跑**（本单修）
----------------------------------------------------------
「**可见 ≠ 有救援**」：#5307 把台账分支的欠账写进了 job summary（可见），但那条红**依然没人救** ——
台账分支的 CI 失败**没有任何自动重跑路径**：
  ① `decide()` 的**自指守卫**逐字判 `head_branch == LEDGER_BRANCH` ⇒ `skip`（防自指递归：
     台账 PR 又被分流）⇒ `flaky-triage.yml` **结构上**不救它；
  ② 本兜底原先只补 approve + arm、**不读失败原因更不重跑**。
**实测**：台账 PR #5139 的 required 测试 4 次尝试同形失败（7m32s~8m16s）⇒ 台账停摆约 40 小时，
解阻靠**人工** `gh run rerun <id> --failed`。
⇒ `runs_needing_rerun`（纯函数：判据）+ `rerun-failed`（CLI：动作）：
   · **上限 1 次**，事实源是 **GitHub 的 `run_attempt`**（重跑一次必 +1），**不是**自己记的计数器
     （计数器随进程消失 ⇒ 每 20 分钟触发一轮的兜底迟早变成无限重跑）；
   · 只作用于**台账分支**（`head_branch` 是纯函数里的**硬条件**，不是调用方约定），且只作用于
     **分支 tip** 的 run（陈旧 push 的 run 重跑对「PR 能否合并」零贡献，却真烧 CI 分钟）；
   · 重跑后**回读** `run_attempt` 并如实记账（job summary + `::notice::`）——「我以为重跑了」不算读数；
     额度用尽仍失败 ⇒ `::error::` + 人工出口（**可见**，不许静默降级成「没事」）。

#5088：`kind` **不是归因层**（本单修：语义收紧 + fail-closed）
------------------------------------------------------------
旧口径把 `kind` 由 `rerun_result` 推出（`build_entries`：第二次绿 ⇒ `flaky` / 两次都红 ⇒
`confirmed_failure`）⇒ 「重跑仍红」被读成「**确定性失败**」。按 #5088 的包**逐条拉两次尝试的
job 日志**取证（读数见该 PR body）：21 条里 **7 条判错**（issue 的 9 条错 2 · 后增 12 条错 5）：

  · 4 条 `confirmed_failure` 的两次尝试**红的不是同一条断言**（run `35866618242` / `35891090972`
    / `35927546366` / `35942147403`）⇒ 同一 SHA 下失败不一致，**不是**稳定复现的同一个失败；
  · 2 条是**宽窗口竞态**（`ship-order` 的 `#4882` 那条用例：一个 run 里 a1 红 / a2 绿 ⇒ 记 `flaky`，
    另一个 run 里同一条用例、同一条报错 a1/a2 都红 ⇒ 记 `confirmed_failure`）——
    真实机制与「确定性」**相反**；
  · 1 条 `infra_suspect`（dependabot 的 `npm ERESOLVE`）两次尝试逐字同一个错误 ⇒ 那是该 PR 的
    依赖**不可解析**（确定性的），不是环境抖动。

⇒ 新口径（**fail-closed：事实不够判就不给结论**）：
  · `flaky` —— 同 SHA 重跑绿（该失败**不可复现**，事实够判）；
  · 两次都红 ⇒ **自动路径一律 `unknown`**（CI 只有**步骤级**事实：GitHub 的 jobs API 只给步骤名，
    不给断言文本 ⇒ 不足以判断「是否同一断言」），同时把两次尝试的**原始事实**记进 `attempts`
    （`step` 逐字），并用 `unknown_reason` 逐字写明**为什么不归因**；
  · `deterministic` **只能由 `attest` 写入**：分诊方按 #5088 的口径拉两次尝试的 job 日志
    （`gh api repos/{repo}/actions/jobs/<job_id>/logs`），把断言摘要逐字回填 ——
    两次**同一断言同一错误** ⇒ `deterministic`；**不同 ⇒ 仍 `unknown`**（#5088 的建议口径）；
    且必须带 `attested_evidence`（凭据）⇒「**归因必须有凭据**」；
  · **「禁止用 `unknown` 归因」的机械形态** = `ATTRIBUTABLE_KINDS`（单一事实源，`unknown` 不在其中），
    `aggregate()` 的 `attributed` 计数只统计它；
  · **历史条目一字未改**（93 条 `confirmed_failure` 照旧）：台账是**证据**，不许用改写历史来「洗」数据；
    旧值的语义在台账顶层 `_schema` 里**显式登记**为「旧口径，已知会过度声称」，且新写入
    **不再产生**该值（判据：`tests/unit_ci_workflows/test_flaky_ledger_kind_semantics.py`）。

退出码（三态，照本仓库 `merge_gate.py` / `llm_sink_check.py` 口径）
------------------------------------------------------------------
`0` = 正常；`1` = 违规（台账不自洽 / 参数非法 / 重跑动作失败 / 额度用尽）；`3` = **无法判定**（取不到事实）。

#5687：`kind=suspect-window-deterministic`（跨时间桶的「重跑通过」）
------------------------------------------------------------------
**窗口型确定性缺陷**：失败与重跑落在**不同时间桶**（桶 = UTC 日期 × **+08 业务日** × UTC 小时）
⇒ 「重跑通过」**不再是**「与本次改动无关」的证据。本条的目的是**堵住一条可以无限循环的链**：
重跑落到窗口外就绿 ⇒ 旧口径判 `flaky` ⇒ PR 的红被消掉 ⇒ 缺陷仍在 main 上 ⇒ 明天同一时段
对所有人**再红一次** ⇒ 回到起点。
本类**不是定罪**（判 `deterministic` 仍要两次尝试**同一断言同一错误**的日志取证）、
**不进** `ATTRIBUTABLE_KINDS`（同 #5088 的 `unknown`：未取证的 kind 不得用于归因计数），
且**强制跟踪**（必须带 `follow_up`，由 `triage-follow-up` **机械**落单；缺 ⇒ `selftest` / `append`
判**违规**）。覆盖面（含**覆盖不到**的形态）与「任何以重跑结果为唯一依据来消红/降级的路径
都必须**具名登记**」的类级 meta-guard：`tests/unit_ci_workflows/test_rerun_to_clear_paths.py`。

#5687 顺带登记（**不修**）：`Flaky Ledger Reconcile` **仍未接 required 门禁** —— 它的红是
**给人看的**，**判红不等于阻塞合并**（把阻塞换可见性不划算，人已裁定不把它翻成 required）。
⇒ 别把「它没红」读成「没问题」；真正的门禁在 required 集合里。
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 常量（单一事实源；workflow 侧只引用，不复制） ───────────────────────────────

LEDGER_PATH = Path(__file__).resolve().parents[1] / "flaky-ledger.json"
#: 台账在仓库里的**相对**路径（git / `gh api` 侧按相对路径取分支与 main 副本；由 LEDGER_PATH 派生，
#: 不写死副本）。定义在常量区（不是 #4825 节里）：`render_reconcile_report` 的默认参数要用它。
LEDGER_REL = "/".join(LEDGER_PATH.parts[-2:])
LEDGER_BRANCH = "chore/flaky-ledger"
FLAKY_LABEL = "flaky/rerun-green"
BLOCK_LABEL = "block/merge"

#: 参与分流的 workflow **白名单**（按 workflow `name` 匹配，不是文件名）。
#: 只收「PR 上跑测试、且重跑无副作用」的 CI：
#:   · 故意**不收** `Drift Audit` / `Agent Behavior Eval` / `Demo Evidence Gate`（报告型，不阻塞）；
#:   · 故意**不收** `Deploy Reconcile` / `deploy-*`（**重跑有副作用**：会真的部署）；
#:   · 故意**不收** `Post-Deploy Eval` 等真实 LLM workflow（重跑 = 重复烧 token，见 #4262）。
TRIAGED_WORKFLOWS = (
    "PR Check",
    "Mini-App CI",
    "AI Agent Service Unit Tests",
    "Bmini-App CI",
)

#: **上限**：首次 + 最多 1 次重跑。改大这个数 = 允许无限重跑 ⇒ 守卫测试会红。
MAX_ATTEMPTS = 2

#: #5301 判据②：**台账分支**兜底重跑的**上限（次数）** —— 与上面的 `MAX_ATTEMPTS = 2`（首次 + 最多 1 次）
#: **同口径**（由它派生，不写第二份数字：写死两份必然有一处先腐烂）。
#: ⚠️ 上限的**事实源是 GitHub 的 `run_attempt`**（重跑一次它必 +1），**不是**本兜底自己记的计数器 ——
#: 计数器随进程消失 ⇒ 每 20 分钟触发一轮的兜底迟早变成**无限重跑**（那是红线）。
MAX_LEDGER_RERUNS = MAX_ATTEMPTS - 1

#: 这些 conclusion **不是测试失败**：取消 / 超时 / 基础设施 / 启动失败 / 过期。
#: 命中 ⇒ 不重跑、不记账、不打标（「不许把 infra 抖动记成 flaky」）。
NOT_TEST_FAILURE_CONCLUSIONS = frozenset({
    "cancelled",
    "timed_out",
    "startup_failure",
    "stale",
    "action_required",
    "skipped",
    "neutral",
})

#: 「基础设施步骤」的名字形态：这些步骤失败 = 环境/依赖问题，**不是被测对象的问题**。
#: 方向是 fail-safe（多认 ⇒ 少打 flaky 标），故含较宽的 `^install `。
INFRA_STEP_PATTERNS = tuple(re.compile(p) for p in (
    r"^set up job$",
    r"^complete job$",
    r"^initialize containers$",
    r"^start container",
    r"^stop container",
    r"^run actions/",              # uses: actions/checkout@v7 → 步骤名 "Run actions/checkout@v7"
    r"^set ?up (node|python|java|jdk|go|ruby|php|dotnet)",
    r"^setup (node|python|java|jdk|go|ruby|php|dotnet)",
    r"^(npm|yarn|pnpm) (ci|install)",
    r"^install ",                  # Install dependencies / Install test deps / Install Playwright deps …
    r"^pip install",
    r"^(restore|save) cache",
    r"^cache ",
))

LEDGER_TOP_KEYS = ("version", "note", "_schema", "entries")
ENTRY_REQUIRED = {
    "workflow": str,
    "job": str,
    "run_id": int,
    "rerun_result": str,
    "kind": str,
    "observed_at": str,
    # 「每条带**可行动**信息」（照 #4757 `time_flaky_baseline.json` 的形态）：
    # 只有 kind 的条目是**不可行动**的 —— 读的人不知道下一步该干什么。
    "reason": str,
    "remedy": str,
    "status": str,
}
#: `kind` 的**全部取值**（读侧白名单）。前四个是 **#5088 之后**的口径（`unknown` = 事实不足以归因）；
#: 最后一个是**旧口径的存量值** —— 保留在白名单里是「**历史不得改写**」（台账是证据）的必要条件，
#: 不是允许新写入：`build_entries` 只产出新口径（判据 `test_decide_never_emits_legacy_kind`）。
ENTRY_KINDS = ("flaky", "suspect-window-deterministic", "deterministic", "unknown",
               "infra_suspect", "confirmed_failure")
#: 旧口径的存量值（**只读**；新写入一律不产生）。
LEGACY_ENTRY_KINDS = frozenset({"confirmed_failure"})
#: **可以用于归因**的 kind（单一事实源）。`unknown` 不在其中 ⇒「禁止用 unknown 归因」的机械形态：
#: 读侧的归因计数（`aggregate()['attributed']`）只统计本集合，`unknown` 永远单独成列。
ATTRIBUTABLE_KINDS = frozenset({"flaky", "deterministic", "infra_suspect"})
#: 必须带**原始事实**（`attempts`）的新口径 kind；`deterministic` 另需 `attested_evidence`（凭据）。
FACT_BACKED_KINDS = frozenset({"deterministic", "unknown"})
#: **为什么**「原事实」是承重的（而不是装饰）：`attempts[k].timestamp` 才是「失败时刻 / 重跑时刻」
#: 的**取数面** —— `bucket_of()` / `classify_rerun_green()` 读的就是它。把 `attempts` 从
#: `FACT_BACKED_KINDS` 的必填里摘出来，本条判据（跨时间桶 ⇒ `suspect-window-deterministic`）
#: 就**无从复算**（读的人只能看到一个结论，看不到得出它的两个时刻）。

#: 🔴 **窗口型确定性缺陷**（issue #5687）= **失败时刻与重跑时刻不在同一个时间桶**。
#:
#: 病灶（本会话真实读数）：测试侧裸 `LocalDate.now()`（runner 的 JVM 默认时区 = UTC）取业务日，
#: 而生产按 **+08**（`BusinessClock.today()`）⇒ 两侧只在「UTC 日期 ≠ +08 日期」时分叉
#: ⇒ **UTC 16:00–24:00（北京 00:00–08:00）每天必红**。run `36280962072` 在窗口内红（22:12Z），
#: 为让部署落地而重跑落在窗口外（00:0xZ）⇒ 绿 —— 旧口径**只凭「重跑通过」**就判 `flaky`、
#: 消掉 PR 的红，而缺陷仍在 main 上，明天同一时段对所有人**再红一次**（可无限循环）。
SUSPECT_WINDOW_KIND = "suspect-window-deterministic"
#: ⚠️ **不是定罪**：时间桶不同**只**意味着「重跑通过」不再是充分证据 ⇒ 降级为「需人看」。
#: 它**不**宣称该失败是确定性的（`deterministic` 仍只能由 `attest` 按两次**同一断言同一错误**写入）。
#: `ATTRIBUTABLE_KINDS` 有意**不含**它 —— 与本仓 #5088 的 `unknown` 同一条纪律：
#: 「**禁止**用一个未取证的 kind 做归因计数」。
SUSPECT_WINDOW_REASON = (
    "首次失败与重跑通过落在**不同的时间桶**（跨了 UTC 日期 / +08 业务日的时段边界；两个时刻见"
    "条目的 `failed_at` / `rerun_at`）⇒ 「重跑通过」**不再**是「与本次改动无关」的证据"
    "（窗口型确定性缺陷 —— 如 UTC 16:00–24:00 必红 —— 正是这样被重跑掩盖的，issue #5687）。"
    "**不是定罪**：本条只说「需人看」，不宣称它是确定性失败"
)
SUSPECT_WINDOW_REMEDY = (
    "先**按时间维度复核**（不是先重跑）：拿条目的 `failed_at` / `rerun_at` 与失败 job 的日志"
    "复算「同一 commit 在失败那一段时刻是否稳定地红」（窗口型缺陷的特征 = **每天同一时段必红**）；"
    "确认是窗口型 ⇒ 修根因（冻结时钟 / 注入业务时钟 / 两侧同源取日），修后**必须给红证**"
    "（把机制注回 ⇒ 必红），再把条目标 `status=fixed` + `fixed_by`。"
    "⚠️ **不许**把本类当普通 flaky 消红（它必须带 `follow_up` 跟踪单）；"
    "确属真 flaky（同桶内不可复现）⇒ 按 `flaky` 的 remedy 处理并说明为什么该跨桶是巧合"
)

#: 「**怎么给 `suspect-window-deterministic` 落跟踪单**」的权威口径（单一事实源）：
#: `triage-follow-up` 的 `--help` epilog 与 workflow 的步骤注释都从它取值。为什么它必须是**机械动作**
#: 而不是「文档要求人记得做」：`ledger_violations` 把「该类条目缺 `follow_up`」判成**违规**
#: （`append`/`selftest` 直接非零退出）⇒ 没有机械动作时，分流会在**第一步**就死给你看 ——
#: 这与 #5307 的教训同形（「文档要求做、却没有合法工具做」= 自我死锁）。
FOLLOW_UP_TRACKING_HOWTO = (
    "窗口型疑似条目的跟踪单由 CI **机械**落（不靠人记得）："
    "`python3 .github/scripts/flaky_ledger.py triage-follow-up --repo <owner/repo> "
    "--entries <decide 写出的条目文件> --job '<job>'` —— 同 job 已有 open 的跟踪单则**复用**"
    "（按 body 里的 marker 精确匹配，不新建噪音），否则新建一张并打 `flaky/tracking` 标签；"
    "它把单号**注入条目的 `follow_up`**。⇒ 台账里 `kind=suspect-window-deterministic` 的条目"
    "**必然带跟踪单**（缺 ⇒ `selftest` / `append` 判违规）。"
)
ENTRY_STATUSES = ("open", "fixed")
RERUN_RESULTS = ("success", "failure", "not_rerun")
#: 台账里**禁止**出现的顶层键：硬编码计数会随追加而腐烂（#4701/#4714/#4742 纪律）。
FORBIDDEN_LEDGER_KEYS = ("count", "total", "entries_count", "n_entries", "num_entries")

#: 「**怎么回填** `follow_up`」的权威口径（#5307）。台账 schema 原话只写「由分诊方回填」、
#: **没说用哪个命令** —— 那正是死锁的一半（另一半 = 台账分支的确定性失败没有消费面）。
#: 单一事实源在这里：CLI 的 `--help` epilog、`reconcile` 的欠账报告、required 测试的失败消息
#: 都从它取值（**不复制第二份措辞**）。
FOLLOW_UP_HOWTO = (
    "回填跟踪单号（**字段级**：只改 `follow_up`(/`status`/`fixed_by`)，不新增/删除/重排条目）："
    "`python3 .github/scripts/flaky_ledger.py follow-up "
    "--ledger .github/flaky-ledger.json --run-id <run_id> --issue <跟踪单号>`；"
    "同一 run 有多个 job 时加 `--job '<job>'`；销账加 `--status fixed --fixed-by '<PR/run/用例>'`。"
    "`run_id` 不在台账里 / 单号非正整数 / 命中多条却不给 `--job` ⇒ **非零退出**（fail-closed，"
    "绝不静默无操作）；重复回填同一值 = **无副作用**（幂等）。"
)

#: 「**怎么把断言级事实回填**」的权威口径（#5088）—— `unknown` 条目的 remedy、`attest` 的帮助文本、
#: 守卫测试的失败消息都从它取值（**不复制第二份措辞**）。
ATTEST_HOWTO = (
    "取证（#5088 口径）：`gh api repos/<owner>/<repo>/actions/runs/<run_id>/attempts/<n>/jobs` 取失败 job 的 "
    "id，再 `gh api repos/<owner>/<repo>/actions/jobs/<job_id>/logs` 拉**两次尝试**的日志，"
    "比对是否**同一断言同一错误**；然后回填（**字段级**，不新增/删除/重排条目）："
    "`python3 .github/scripts/flaky_ledger.py attest --ledger .github/flaky-ledger.json "
    "--run-id <run_id> --job '<job>' --attempt1-assertion '<断言+错误>' "
    "--attempt2-assertion '<断言+错误>' --evidence '<凭据：run/attempt 与日志取法>'`；"
    "两次同一 ⇒ `deterministic`；不同 ⇒ 仍 `unknown`（**不许**凭 `kind` 归因）。"
)

#: 每个 kind 的**可行动**说明（生成时即写入，读的人不必回查脚本）。
KIND_REASON = {
    "flaky": "首次失败、**重跑后通过**（随机波动）——**不是**本次改动修好了它",
    # issue #5687：见 `SUSPECT_WINDOW_REASON`（单一事实源，不在这里写第二份措辞）。
    SUSPECT_WINDOW_KIND: SUSPECT_WINDOW_REASON,
    # ⚠️ 旧口径的存量值：**只出现在历史条目里**（那些 `reason`/`remedy` 是当时逐字写入的证据，不许改写）。
    "confirmed_failure": "同一 commit **两次都失败** ⇒ 确定性失败（已用「第二次真实结果」排除 flaky）",
    "infra_suspect": "失败落在「取代码 · 装依赖 · 配环境」步骤（或 job 从未跑起来）⇒ 环境/基础设施问题",
    "deterministic": ("同一 SHA 两次尝试红的**同一条断言、同一个错误**（分诊方按日志取证后 `attest`）"
                      "⇒ 可复现的确定性失败"),
    "unknown": ("两次尝试都失败，但**事实不足以归因** ⇒ fail-closed：**既不判 flaky、也不判确定性**"
                "（同一 SHA 两跑都红也可能是宽窗口竞态；见条目的 `unknown_reason` 与 `attempts`）"),
}
KIND_REMEDY = {
    "flaky": ("按 `migao-acceptance`「随机红 = 归因层失效」**定位机制**（不许只加 waitFor/sleep）："
              "时间相关 ⇒ 冻结时钟（`jest.setSystemTime` / 注入时钟）；并行或共享状态 ⇒ 显式隔离或独立 fixture；"
              "修后**必须给红证**（把机制注回 ⇒ 必红）"),
    SUSPECT_WINDOW_KIND: SUSPECT_WINDOW_REMEDY,
    "confirmed_failure": "按真实失败排查（本机制已用「同 commit 第二次结果」排除 flaky 可能）",
    "infra_suspect": ("**先区分「环境抖动」与「确定性不可解析」**（#5088 实证：dependabot 的 "
                      "`npm ERESOLVE` 两次尝试逐字同一个错误 ⇒ 是依赖冲突，不是环境抖动）："
                      "两次报错逐字相同 ⇒ 查依赖锁定 / peer 冲突；偶发一次 ⇒ runner 容量 / 依赖源 / 网络"),
    "deterministic": "按真实失败排查（两次尝试同一断言同一错误 ⇒ 可复现；证据在条目的 `attempts` 里）",
    "unknown": ATTEST_HOWTO,
}


# ── 纯函数：事实 → 分流决定（无 IO、无网络，故可离线红证） ─────────────────────


def _conclusion(obj) -> str:
    return str((obj or {}).get("conclusion") or "").strip().lower()


def is_failed(job) -> bool:
    return _conclusion(job) == "failure"


def failed_step_name(job) -> str:
    """该 job **第一个失败步骤**的名字（空串 = 没有任何步骤失败 ⇒ runner 级失败）。"""
    for step in (job or {}).get("steps") or []:
        if _conclusion(step) == "failure":
            return str(step.get("name") or "").strip()
    return ""


def job_is_infra(job) -> bool:
    """该失败 job 是否属**基础设施/环境**失败（⇒ 不算 flaky、不重跑）。

    四个判据，任一命中即 infra（全部 fail-safe 方向）：
      ① job conclusion ∈ {timed_out, cancelled, startup_failure}；
      ② job **没有任何 steps** ⇒ 它从未真正跑起来（runner 分配/启动失败）；
      ③ 失败了但**没有任何步骤**被判失败 ⇒ runner 级失败（非测试断言）；
      ④ 唯一失败的步骤名命中「取代码 · 装依赖 · 配环境」形态。
    """
    if _conclusion(job) in {"timed_out", "cancelled", "startup_failure"}:
        return True
    steps = (job or {}).get("steps") or []
    if not steps:
        return True
    step = failed_step_name(job)
    if not step:
        return True
    low = step.lower()
    return any(p.search(low) for p in INFRA_STEP_PATTERNS)


def pr_number(run) -> int | None:
    for pr in (run or {}).get("pull_requests") or []:
        if isinstance(pr, dict) and isinstance(pr.get("number"), int):
            return pr["number"]
    return None


def entry_key(entry) -> tuple:
    """幂等键：**同一次失败**（同 run 的同一个 job）无论被判多少次，都只算一条。"""
    return (entry.get("workflow"), entry.get("run_id"), entry.get("job"))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ── #5687：时间桶（「失败时刻 / 重跑时刻」落到哪一格） ───────────────────────────
#
# 取数面：**job 自己的时刻**（`completed_at` → `started_at` → 该 job **首个失败步骤**的
# `completed_at`）。⚠️ **有意不**回落到 `run.updated_at`：那是 **run 级**时刻（重跑会改写它）
# ⇒ 拿它当「首次失败时刻」会把两个不同的时刻读成同一个（本单要治的正是**读数与事实不一致**）。
# 取不到 ⇒ `""`（`bucket_of("")` 返回 `None` ⇒ 判「跨桶证据不足」⇒ 不降级）。

def utc_iso(value) -> str:
    """任意 ISO8601 时刻 → `YYYY-MM-DDTHH:MM:SSZ`（UTC）；取不到/畸形 ⇒ `""`（**不猜**）。"""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed.astimezone(timezone.utc).replace(microsecond=0)
            .isoformat().replace("+00:00", "Z"))


def job_timestamp(job) -> str:
    """该 job 的**完成时刻**（UTC，`YYYY-MM-DDTHH:MM:SSZ`）；取不到 ⇒ `""`。

    取数顺序（**每一步都只取事实，不猜**）：
      ① job 级 `completed_at` → `started_at`；
      ② 否则取**最后一个带 `completed_at` 的步骤** —— ⚠️ **不能只认失败的步骤**：重跑那一次
         的 job 是**全绿**的（没有任何失败步骤），只认失败步骤会让「重跑时刻」恒为空
         ⇒ 跨桶判定永远得不到证据（本单的判据会静默退化成旧口径）。
    """
    for candidate in ((job or {}).get("completed_at"), (job or {}).get("started_at")):
        iso = utc_iso(candidate)
        if iso:
            return iso
    for step in reversed((job or {}).get("steps") or []):
        iso = utc_iso((step or {}).get("completed_at"))
        if iso:
            return iso
    return ""


#: 业务时区（本仓口径 = **+08**；生产侧 `BusinessClock` 同此）。写成 timedelta 而非 `ZoneInfo`
#: 是有意的：本脚本要能在**零第三方依赖**的 job 里跑（照 #5170 的「零依赖退路」纪律）。
BUSINESS_TZ = timezone(timedelta(hours=8))

#: **时间桶的粒度** = 「UTC 日期 × **+08 业务日** × **UTC 小时**」三键逐字相等。
#:
#: 为什么是这三键（**每一条都对着一个已发生的形态**）：
#:   · `utc_date` —— runner 的 JVM 默认时区 = **UTC** ⇒ 裸 `LocalDate.now()` 取到的日子按 UTC 翻页；
#:   · `biz_date` —— 生产按 **+08** 业务日算（`BusinessClock.today()`）⇒ 两侧只在
#:     「UTC 日期 ≠ +08 日期」（= **UTC 16:00–24:00**）时分叉，那正是本单实测的窗口；
#:   · `utc_hour` —— 把**时段**也纳入：窗口型缺陷不必跨日（`time_flaky_baseline.json` 的存量里
#:     就有**跨月边界**的窄窗口竞态，同一个 UTC 日之内）；只比日期会**漏**它。
#:
#: 为什么**不**细到秒（**本判据的第一版就是秒，过度包含，已收窄**）：真 flaky 的重跑常在
#: 数十秒内完成，秒级相等会把**绝大多数真 flaky** 判成 `suspect`（把安全边界一起关掉）。
#: 相反方向也不会漏掉本单的病灶 —— 跨小时**必然**同时跨 `utc_hour`。
#:
#: ⚠️ **已知的过度包含 / 欠包含（照实登记，不粉饰）**（口径 = 「跨桶 ⇒ 降级为需人看 + 强制跟踪」，
#: **不是**定罪 ⇒ 两侧都判错时宁可多要一次人看，因为漏判的代价是**缺陷留在 main 上每天再红一次**）：
#:   · 过度包含：真 flaky 的两次尝试各跨一次**日期边界**（如 +08 23:59:52 红 / 次日 00:00:08 绿）
#:     —— 它与时间无关却被降级。出口 = 在跟踪单里如实记「同桶复算为巧合」后销账；
#:   · 欠包含：**同一 UTC 小时、同一 UTC 日、同一 +08 业务日之内的跨时段**（如半小时级窗口）
#:     判不出来 —— 它仍走 `flaky`（本单只处理**可静态判定**的时间桶维度，其余走类级登记表）。
def bucket_of(iso_utc: str) -> dict | None:
    """`iso_utc` 落在哪个时间桶（三键）；取不到时刻 ⇒ `None`（= **证据不足**，不是「同桶」）。"""
    if not iso_utc:
        return None
    try:
        parsed = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    utc = parsed.astimezone(timezone.utc)
    biz = parsed.astimezone(BUSINESS_TZ)
    return {"utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "utc_date": utc.strftime("%Y-%m-%d"),
            "biz_date": biz.strftime("%Y-%m-%d"),
            "utc_hour": utc.strftime("%H")}


def same_bucket(failure_utc: str, rerun_utc: str) -> bool | None:
    """两次尝试是否落在**同一个时间桶**。三态：

      · `True`  —— 实测相同（三键逐字相等）⇒ 「重跑通过」仍是 flaky 的合法证据；
      · `False` —— 实测不同（跨了 UTC 日期 / +08 业务日 / UTC 小时）⇒ **跨桶**；
      · `None`  —— **取不到时刻 ⇒ 无法判定**（**不是** `False`：不许拿「读不到」当降级理由，
                  否则本判据会在**缺字段的历史调用点**上自己变成噪音源）。
    """
    a, b = bucket_of(failure_utc), bucket_of(rerun_utc)
    if a is None or b is None:
        return None
    return (a["utc_date"], a["biz_date"], a["utc_hour"]) == (b["utc_date"], b["biz_date"], b["utc_hour"])


def classify_rerun_green(failure_utc: str, rerun_utc: str) -> tuple:
    """**「重跑通过」还能推出什么** —— 本模块唯一的「重跑绿」判据（返回 `(kind, reason)`）。

    issue #5687 的病根就是这里**原本不存在**：`rerun_result == "success"` **单独**就足以判 `flaky`
    ⇒ 窗口型确定性缺陷被重跑掩盖。三层（**顺序即优先级**）：

      · 刻**都取不到**（缺 `completed_at` 的历史 fixture / 调用点）⇒ `flaky` + **显式声明证据不足**
        —— 这是**向后兼容**层，不是「同桶已证」；
      · 同桶 ⇒ `flaky`（**安全边界**：同一 commit / 同一 job / 同一时间桶内的失败→重跑通过
        仍然是 flaky 的合法证据 —— 收紧不能把真 flaky 一起关掉）；
      · 跨桶 ⇒ `SUSPECT_WINDOW_KIND`（**降级**：不许据此把 PR 的红当成"已澄清"）。

    ⚠️ 判据**只**读两个时刻，不读任何计数/阈值（照本仓「阈值不进仓库」的既有纪律）。
    """
    if not failure_utc and not rerun_utc:
        return "flaky", ("失败与重跑的时刻**都取不到**（缺 `completed_at`）⇒ 无法按时间桶判定；"
                         "沿用「重跑通过 ⇒ flaky」的**旧口径**并在此**显式声明证据不足**"
                         "（不是「已证同桶」）")
    verdict = same_bucket(failure_utc, rerun_utc)
    if verdict is True:
        return "flaky", (f"失败（{failure_utc}）与重跑通过（{rerun_utc}）落在**同一时间桶**"
                         f"⇒ 「重跑通过」仍是 flaky 的合法证据")
    if verdict is False:
        return SUSPECT_WINDOW_KIND, (f"失败（{failure_utc}）与重跑通过（{rerun_utc}）落在"
                                     f"**不同时间桶**（UTC 日期 / +08 业务日 / 时钟任一不同）"
                                     f"⇒ 不许凭「重跑通过」判 flaky")
    return "flaky", ("失败与重跑的时刻**不齐**（只有一个取得到）⇒ 判不了跨桶；"
                     "沿用「重跑通过 ⇒ flaky」的**旧口径**并在此**显式声明证据不足**"
                     "（不是「已证同桶」）")


def attempt_facts(job, attempt: int, assertion=None) -> dict:
    """**一条原始事实**：第 `attempt` 次尝试里这个 job 的失败读数（不经解释）。

    `step` = `failed_step_name`（逐字的失败步骤名，空串 = runner 级失败）；
    `assertion` = 断言摘要 —— **CI 自动路径取不到**（GitHub 的 jobs API 只给步骤名，不给断言文本），
    故自动写入 `None`；由 `attest` 按 #5088 的日志取证口径**逐字**回填（`attempt1`/`attempt2` 各一份）。
    `timestamp` = 该次尝试的**完成时刻**（UTC；#5687 的「失败时刻 / 重跑时刻」取数面，见 `job_timestamp`）。
    """
    return {"attempt": attempt, "job": job.get("name"),
            "step": failed_step_name(job), "assertion": assertion,
            "timestamp": job_timestamp(job)}


def classify_both_red(a1, a2) -> tuple:
    """**两次都红**时能得出的结论（fail-closed：事实不够判 ⇒ `unknown` + 逐字理由）。

    这是本模块**唯一**的归因判据（`build_entries` 与 `attest` 共用，**不写第二份规则**）。
    返回 `(kind, unknown_reason)`；`kind == "unknown"` 时 `unknown_reason` 必非空。

    判据（按事实强度从上到下；**每一条都给得出它的读数**）：
      · 两次的断言摘要都非空、**逐字相同**且步骤相同 ⇒ `deterministic`（同一个失败**复现**两次）；
      · 两次的断言摘要都非空但**不同** ⇒ `unknown`（同一 SHA 下失败不一致 ⇒ 不是同一个失败）
        —— 这正是 #5088 的建议口径「两次尝试红的不是同一条断言 ⇒ 不得记确定性」；
      · 只有步骤级事实（自动路径的常态）⇒ `unknown`（步骤名（`Run unit tests` 一类）**不足以**
        判断是否同一断言；同一 SHA 两跑都红也可能是宽窗口竞态 —— #5088 实测 2 条正是如此）；
      · 第一次尝试的事实缺失（`prior_jobs` 取不到 / job 只存在于后一次尝试）⇒ `unknown`（无从比较）。
    """
    if a1 is None or a2 is None:
        return "unknown", ("第一次尝试的失败事实不在本次取数范围内（`prior_jobs` 缺失 / 该 job 只出现在"
                           "后一次尝试）⇒ 无从比较两次是否同一失败，**不归因**")
    if a1.get("step") != a2.get("step"):
        return "unknown", (f"两次尝试红的**不是同一个步骤**（attempt1={a1.get('step')!r} / "
                           f"attempt2={a2.get('step')!r}）⇒ 同一 SHA 下失败不一致，**不归因**")
    s1, s2 = a1.get("assertion"), a2.get("assertion")
    if s1 and s2:
        if s1 == s2:
            return "deterministic", ""
        return "unknown", (f"同一 SHA 两次尝试红的**不是同一条断言**（attempt1={s1!r} / "
                           f"attempt2={s2!r}）⇒ 不是稳定复现的同一个失败，**不归因**")
    return "unknown", ("两次尝试都红、且落在同一个步骤，但**只有步骤级事实**（GitHub 的 jobs API 只给"
                       "步骤名，不给断言文本）⇒ 不足以判断是否同一断言（同一 SHA 两跑都红也可能是"
                       "宽窗口竞态），**不归因**。要归因：" + ATTEST_HOWTO)


def build_entries(run, failed_jobs, rerun_result: str, prior_failed_jobs=None,
                  failed_attempt=None, *, facts_attempt=None, prev_attempt=None,
                  rerun_jobs=None) -> list:
    """把「失败 job 列表 + 重跑结果」变成台账条目（**只追加**，不修改既有条目）。

    #5088：`kind` **不再由 `rerun_result` 单独推出** —— 两次都红 ⇒ `unknown`（fail-closed），
    并把**原始事实**同时记下（`attempts`：每次尝试的失败步骤逐字、断言摘要待 `attest` 回填），
    让读的人**自己判**，而不是替它下结论。

    `prior_failed_jobs` = **上一次**尝试的失败 job（用于比较两次的失败事实）；
    `failed_attempt` = `failed_jobs` 所属的尝试序号（默认取 run 的 `run_attempt`）。

    ⚠️ **#5687：`rerun_jobs` 是第三个取数面**（缺它 ⇒ 时间桶判据是空断言）：
      · `failed_jobs`    —— 被记账的**首次失败**那批 job（`first_failure_step` / `attempts` 由它出）；
      · `rerun_jobs`     —— **重跑那次**（= 本次 run 的 `jobs`）的 job。重跑绿那条路径上它是**全绿**
        的 ⇒ 它**不是**失败 job ⇒ **必须单独传**，否则「重跑时刻」只能回落到失败 job 自己
        ⇒ 两个时刻恒相等 ⇒ 跨桶永远判不出来（实测踩过：`failed_at == rerun_at` 恒成立）。
    """
    out = []
    prior = list(prior_failed_jobs or [])
    rerun = list(rerun_jobs or [])
    current = _attempt(run) if failed_attempt is None else int(failed_attempt)
    #: `failed_jobs` 这次尝试的序号与 `prior_failed_jobs` 那次尝试的序号（**分开**，见 docstring）
    facts_attempt = current if facts_attempt is None else int(facts_attempt)
    prev_attempt = max(facts_attempt - 1, 1) if prev_attempt is None else int(prev_attempt)
    for job in failed_jobs:
        name = job.get("name")
        facts = attempt_facts(job, facts_attempt)
        # 上一次尝试的同一 job（用于把**两次的原始事实**都记下来 —— 供读者自己复核）
        prev_job = next((j for j in prior if j.get("name") == name), None)
        prev_facts = (attempt_facts(prev_job, prev_attempt)
                      if prev_job is not None else None)
        attempts = [prev_facts, facts] if prev_facts is not None else [facts]
        unknown_reason = None
        #: #5687：本条**为什么**是这个 kind（不是「同桶已证」时必须逐字写明 —— 否则读的人
        #: 会把「证据不足」读成「已排除窗口型缺陷」，那正是本单要治的读数与事实不一致）。
        kind_reason, rerun_verdict = None, None
        #: **重跑那次**的同一 job 的时刻（只有 `rerun_result == "success"` 路径才有意义）
        rerun_iso = ""
        if rerun_result == "success":
            # 🔴 #5687：**不许**只凭 `rerun_result == "success"` 判 flaky —— 唯一判据是
            # 「失败时刻与重跑时刻是否落在同一个时间桶」（`classify_rerun_green`，单一实现）。
            #
            # ⚠️ **两个时刻从两个不同的取数面来**（本单踩过，别再合并）：
            #   · **失败时刻** = **首次失败那次**的同一 job（`prev_job`，`prior_failed_jobs` 里的）
            #     —— 也就是循环变量 `job` 本身（本路径的 `failed_jobs` **就是**首次失败那批 job）；
            #   · **重跑时刻** = **重跑那次**的同一 job（`rerun_jobs`，= 本次 run 的 `jobs`，
            #     全绿 ⇒ 它**不是**失败 job，故必须**单独**传进来）。
            # 旧实现在这条路径上根本没有第二个取数面 ⇒ 「重跑时刻」只能回落到失败 job 自己
            # ⇒ 两个时刻恒相等 ⇒ 时间桶判据**恒判同桶**（= 空断言，实测踩过）。
            if rerun_jobs:
                rerun_job = next((j for j in rerun_jobs if j.get("name") == name), None)
                rerun_iso = job_timestamp(rerun_job)
            failure_iso = job_timestamp(job)
            rerun_verdict = same_bucket(failure_iso, rerun_iso)
            # 「首次失败是不是 infra」的**唯一**取数面 = 首次失败那次的 job（= 循环变量 `job`）
            if job_is_infra(job):
                kind = "infra_suspect"
                kind_reason = ("重跑通过，但**首次失败**落在「取代码 · 装依赖 · 配环境」步骤"
                               "（或那次 job 从未跑起来）⇒ 环境/基础设施问题，**不记成 flaky**"
                               "（把 infra 抖动记成 flaky 会把台账本身变成噪音源）")
            else:
                kind, kind_reason = classify_rerun_green(failure_iso, rerun_iso)
        elif job_is_infra(job):
            # #5088 实测：`infra_suspect` 里有一条实为 dependabot 的 `npm ERESOLVE`
            # （两次尝试逐字同一个错误 = 确定性的依赖不可解析）⇒ 也把两次的事实都记下，
            # 读的人一眼能看出「两次是否逐字相同」（本判据**不**替它分类）。
            kind = "infra_suspect"
        else:
            kind, unknown_reason = classify_both_red(prev_facts, facts)
        #: 失败时刻 = 首次失败那次的 job 时刻；重跑时刻 = 重跑那次的 job 时刻（见上两条注释）。
        failed_iso = job_timestamp(job) if rerun_result == "success" else ""
        rerun_only = rerun_iso if rerun_result == "success" else ""
        entry = {
            "workflow": run.get("name"),
            "job": name,
            "run_id": run.get("id"),
            "run_attempt": run.get("run_attempt"),
            "run_url": run.get("html_url"),
            "pr": pr_number(run),
            "head_sha": run.get("head_sha"),
            "head_branch": run.get("head_branch"),
            "first_failure_step": failed_step_name(job),
            "rerun_result": rerun_result,
            "kind": kind,
            # #5088：**原始事实**（可核、逐字；结论由它推出，读的人也能自己复核）
            "attempts": attempts,
            # #5687：**判定所依据的两个时刻**（UTC）+ 它们各自落在哪个时间桶 —— 直接写进条目
            # ⇒ 「为什么判成这一类」可**离线复算**（不必回查 run / 不必信 `kind` 这个结论）。
            "failed_at": failed_iso,
            "rerun_at": rerun_only,
            "failed_bucket": bucket_of(failed_iso),
            "rerun_bucket": bucket_of(rerun_only),
            "rerun_bucket_verdict": rerun_verdict,
            "observed_at": run.get("updated_at") or run.get("created_at") or _now(),
            # 可行动信息：生成时即写入（读的人不必回查脚本 / 不必翻日志）
            "reason": kind_reason or KIND_REASON[kind],
            "remedy": KIND_REMEDY[kind],
            "status": "open",
            # 跟踪单号由**分诊方**回填（CI 生成时不知道单号）——
            # `reconcile` 会把「kind=flaky 且 status=open 但没 follow_up」判成欠账（红）。
            "follow_up": None,
        }
        if unknown_reason:
            entry["unknown_reason"] = unknown_reason
        out.append(entry)
    return out


def decide(bundle, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """**唯一**的分流判据（纯函数）。返回 `{action, reason, kind, entries, pr, attempt}`。

    `bundle` = `{"run": {...}, "jobs": [...], "prior_jobs": [...] | None}`
    （形状与 GitHub REST `/actions/runs/{id}` 与 `/attempts/{n}/jobs` 同源）。

    action 四态：
      · `skip`                   —— 不动作（含 infra/取消/超时/非 PR/不在白名单）
      · `rerun`                  —— 首次失败 ⇒ 重跑失败 job **1 次**
      · `mark_flaky`             —— 第二次绿 ⇒ 标 flaky（**并卸 auto-merge**）
      · `record_infra`           —— 第二次绿但全是 infra ⇒ 只记账（不打 flaky 标、不卸）
      · `record_both_red`        —— 第二次仍红 ⇒ **照常失败**（不再重跑第三次）；条目 `kind=unknown`
        （#5088：两次都红**不足以**判定「确定性失败」⇒ 只记事实、不归因）
    """
    run = (bundle or {}).get("run") or {}
    jobs = (bundle or {}).get("jobs") or []
    prior_jobs = (bundle or {}).get("prior_jobs") or []

    def skip(reason: str) -> dict:
        return {"action": "skip", "reason": reason, "kind": None,
                "entries": [], "pr": pr_number(run), "attempt": _attempt(run)}

    name = str(run.get("name") or "")
    if name not in TRIAGED_WORKFLOWS:
        return skip(f"workflow `{name}` 不在分流白名单（重跑无副作用才收）")
    if str(run.get("event") or "") != "pull_request":
        return skip(f"非 PR 运行（event={run.get('event')!r}）—— 部署/定时/手动不参与分流")
    branch = str(run.get("head_branch") or "")
    if branch == LEDGER_BRANCH:
        return skip("台账分支自身的 CI 不参与分流（防自指递归：台账 PR 又被分流）")

    attempt = _attempt(run)
    conclusion = _conclusion(run)
    if conclusion in NOT_TEST_FAILURE_CONCLUSIONS:
        return skip(f"conclusion={conclusion} 属取消/超时/基础设施失败 —— 不算 flaky、也不重跑")
    if conclusion == "success":
        if attempt < 2:
            return skip("首次尝试即绿 —— 无需分流")
        first_failed = [j for j in prior_jobs if is_failed(j)]
        if not first_failed:
            return skip("重跑绿，但**首次尝试没有失败 job**（可能被取消后重跑）⇒ 无 flaky 证据")
        return _terminal(run, first_failed, "success", attempt,
                         # ⚠️ 三个参数缺一不可（#5687 实测各踩过一次，每一处的失效形态都一样：
                         # **时间桶判据静默退化成「恒判同桶」**）：
                         # ① `prior_failed_jobs` —— 首次失败那批 job（`attempts` / 首个失败步骤的
                         #    取数面）；
                         # ② `rerun_jobs` —— **重跑那次**的 job（= 本次 `jobs`，全绿）⇒「重跑时刻」
                         #    的**唯一**取数面。缺它 ⇒ 重跑时刻回落到失败 job 自己 ⇒ `failed_at
                         #    == rerun_at` 恒成立（实测）；
                         # ③ `failed_attempt=attempt - 1` —— 失败那批 job 的**尝试序号**（缺它会被
                         #    标成 `attempt=2`，于是 `build_entries` 去找不存在的 attempt 1
                         #    ⇒ `prev_facts=None`）。
                         prior_failed_jobs=prior_jobs,
                         rerun_jobs=jobs,
                         failed_attempt=max(attempt - 1, 1))
    if conclusion != "failure":
        return skip(f"conclusion={conclusion} 不是测试失败")

    failed = [j for j in jobs if is_failed(j)]
    if not failed:
        return skip("conclusion=failure 但没有任何失败 job（workflow 级失败）—— 无 job 可重跑")
    if attempt >= max_attempts:
        return _terminal(run, failed, "failure", attempt,
                         prior_failed_jobs=prior_jobs, failed_attempt=attempt)
    return {
        "action": "rerun",
        "reason": (f"首次失败（attempt={attempt}）⇒ 自动重跑失败 job "
                   f"（上限 {max_attempts - 1} 次，绝不无限重跑）"),
        "kind": None,
        "failed_jobs": [j.get("name") for j in failed],
        "entries": [],
        "pr": pr_number(run),
        "attempt": attempt,
    }


def _attempt(run) -> int:
    try:
        return int(run.get("run_attempt") or 1)
    except (TypeError, ValueError):
        return 1


def _terminal(run, failed_jobs, rerun_result: str, attempt: int, prior_failed_jobs=None,
              failed_attempt=None, *, rerun_jobs=None, facts_attempt=None,
              prev_attempt=None) -> dict:
    entries = build_entries(run, failed_jobs, rerun_result, prior_failed_jobs,
                            failed_attempt=failed_attempt,
                            facts_attempt=facts_attempt, prev_attempt=prev_attempt,
                            rerun_jobs=rerun_jobs)
    kinds = {e["kind"] for e in entries}
    # 🔴 #5687：**动作由条目的 kind 派生**，不由 `rerun_result` 单独派生 —— 旧口径
    # `if rerun_result == "success" and "flaky" in kinds: mark_flaky` 会让「跨时间桶的
    # 重跑通过」也走 `mark_flaky`，而 workflow 侧那一步会**卸 auto-merge + 打 flaky 标**
    # （= 把 PR 的红当成"已澄清"）。两类的**动作不同、可见标注不同**（见 `DECISION_ACTIONS`）。
    if rerun_result == "success" and SUSPECT_WINDOW_KIND in kinds:
        action, kind = "mark_suspect", SUSPECT_WINDOW_KIND
        reason = ("第二次绿但**跨了时间桶** ⇒ 判 `suspect-window-deterministic`（**不是** flaky）："
                  "「重跑通过」不再是「与本次改动无关」的证据（#5687）。"
                  "**强制跟踪**：条目必带 `follow_up`（`triage-follow-up` 机械落单），"
                  "**不**把 PR 的红当成已澄清")
    elif rerun_result == "success" and "flaky" in kinds:
        action, kind = "mark_flaky", "flaky"
        reason = "第二次绿 ⇒ **flaky**（标注 + 记账 + 卸 auto-merge；第二次绿 ≠ 通过）"
    elif rerun_result == "success":
        action, kind = "record_infra", "infra_suspect"
        reason = "第二次绿，但失败 job 全属 infra/环境 ⇒ 只记账（**不**记成 flaky）"
    else:
        action, kind = "record_both_red", "unknown"
        reason = (f"第 {attempt} 次仍失败 ⇒ **照常失败**（不再重跑第 {attempt + 1} 次）"
                  f"；两次尝试都红 **≠** 确定性失败（#5088 实测：21 条里 7 条被旧口径这样判错）"
                  f"⇒ 记 `kind=unknown` + 原始事实，**不归因**（归因需先按 #5088 口径取证再 `attest`）")
    return {"action": action, "reason": reason, "kind": kind,
            "entries": entries, "pr": pr_number(run), "attempt": attempt}


# ── 台账：只追加 + 幂等 ───────────────────────────────────────────────────────


def append_entries(ledger: dict, entries: list) -> tuple:
    """**只追加**、**幂等**。返回 `(added, skipped_keys)`。

    幂等判据 = `entry_key` 在「存量 ∪ 本批已收」里出现过 ⇒ 跳过。
    故「同一次失败被重跑多次 / 重判多次」只留一条；重复追加是**无副作用**的空操作。
    """
    existing = {entry_key(e) for e in (ledger.get("entries") or [])}
    added, skipped = [], []
    for entry in entries:
        key = entry_key(entry)
        if key in existing:
            skipped.append(key)
            continue
        existing.add(key)
        added.append(entry)
    ledger.setdefault("entries", []).extend(added)
    return added, skipped


def union_ledgers(main_ledger, branch_ledger) -> dict:
    """**并集**（幂等、不丢条目）：以 main 台账为基线，幂等并入分支侧条目。

    **复用** `append_entries`（幂等键 `entry_key` 的去重逻辑只有一份，不新写第二套并集）。

    #5100 为什么需要它：台账分支的追加路径**不自愈** —— 旧实现在**分支自己的 HEAD**（旧基线）
    上追加，而台账 PR 走 **squash 合并** ⇒ 分支历史**永不含** main 上那个 squash 提交
    ⇒ **只追加**的分支**每轮都会再冲突**（实测 `diverged, ahead_by 34, behind_by 16`）。
    根治 = 推前先与 main 对齐：**先并集，再在最新 main 之上重放**（见 `align_with_main`）。

    三条不变量（判据：`tests/unit_ci_workflows/test_flaky_ledger_append_selfheal.py`）：
      · **幂等** —— 同一 key 只留一条（重复并集是无副作用的空操作）；
      · **不丢条目** —— 结果 ⊇ main ∪ 分支 ⇒ 条目数 ≥ `max(main, 分支)`；
      · **同 key 内容不同时以 main 为准**（main 是**已合并的权威态**；只追加写者不产生这种差异）。
    """
    merged = copy.deepcopy(main_ledger or {})
    append_entries(merged, list((branch_ledger or {}).get("entries") or []))
    return merged


def load_ledger(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_ledger(path: Path, ledger: dict) -> None:
    Path(path).write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _show_json(rev_path: str, what: str):
    """读 `git show <rev>:<path>` 并解析 JSON。**fail-closed**：读不到/不是 JSON ⇒ 抛错。

    绝不许把「读不到」当「空台账」继续 —— 那会**丢**掉那一侧的条目（并集的全部意义）。
    """
    out = _git("show", rev_path)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"读不到{what}（{rev_path}）：{(out.stderr or '空内容').strip()[:200]}")
    try:
        return json.loads(out.stdout)
    except ValueError as exc:
        raise RuntimeError(f"{what}（{rev_path}）不是合法 JSON：{exc}")


def align_with_main(ledger_path, branch: str = LEDGER_BRANCH) -> dict:
    """**推前先与 main 对齐**（#5100 根治）：并集 + 在**最新 main 之上**重放（并写回台账文件）。

    步骤（**全 fail-closed**：任一步取不到事实 ⇒ 抛 `RuntimeError`，绝不「当作空台账」继续）：
      ① `git fetch origin main` → 读 `origin/main:<台账相对路径>`（main 侧 = **权威态**）；
      ② 分支存在 ⇒ 读 `FETCH_HEAD:<台账相对路径>`，并记下它的 HEAD（= 推送要用的 **lease 期望值**）；
      ③ `union_ledgers(main, 分支)`（幂等 + 不丢条目）；
      ④ `git checkout -B <branch> origin/main` ⇒ 把并集**写回** `ledger_path`
         —— 此后调用方的 `git diff` 基线是 **main**（不再是旧分支），提交落在**最新 main 之上**。

    返回 `{"lease": "<branch>:<sha>" | "", "branch_head": …, "main_total": n,
    "branch_total": n, "merged_total": n}`；`lease` 供调用方做 `--force-with-lease`
    （lease 失败 = 别人刚推 ⇒ **重取重算，绝不强推**）。

    ⚠️ `ledger_path` 必须是**仓库相对**路径：本函数要对 git 说 `origin/main:<该路径>`。
    """
    rel = Path(ledger_path).as_posix()
    if Path(rel).is_absolute():
        raise RuntimeError(f"`--ledger` 必须是**仓库相对**路径（要用于 `origin/main:<路径>`），"
                           f"实际 {str(ledger_path)!r}")

    fetch = _git("fetch", "--quiet", "origin", "main")
    if fetch.returncode != 0:
        raise RuntimeError(f"git fetch origin main 失败：{(fetch.stderr or '').strip()[:200]}")
    main_ledger = _show_json(f"origin/main:{rel}", "main 侧台账")

    branch_head, branch_ledger = None, None
    # #5649：存在性走**唯一读数**（此前这里与 `read_branch_ledger` 各有一份 `ls-remote` 副本
    # —— 「同一真值两处投影」，两份副本迟早给出两套读数）。
    presence = branch_presence(branch)
    if presence == BRANCH_UNKNOWN:
        raise RuntimeError(f"git ls-remote 失败（无法判定分支 `{branch}` 是否存在）")
    if presence == BRANCH_EXISTS:
        got = _git("fetch", "--quiet", "origin", branch)
        if got.returncode != 0:
            raise RuntimeError(f"git fetch origin {branch} 失败：{(got.stderr or '').strip()[:200]}")
        branch_head = _git("rev-parse", "FETCH_HEAD").stdout.strip() or None
        branch_ledger = _show_json(f"FETCH_HEAD:{rel}", "分支侧台账")

    merged = union_ledgers(main_ledger, branch_ledger)
    co = _git("checkout", "-B", branch, "origin/main")
    if co.returncode != 0:
        raise RuntimeError(
            f"git checkout -B {branch} origin/main 失败：{(co.stderr or '').strip()[:200]}")
    save_ledger(ledger_path, merged)
    return {
        "lease": f"{branch}:{branch_head}" if branch_head else "",
        "branch_head": branch_head,
        "main_total": len(ledger_keys(main_ledger)),
        "branch_total": len(ledger_keys(branch_ledger or {})),
        "merged_total": len(ledger_keys(merged)),
    }


def ledger_violations(ledger: dict) -> list:
    """台账自洽性判据（空 = 合规）。`selftest` 与 CI 守卫共用同一实现。"""
    bad = []
    for key in LEDGER_TOP_KEYS:
        if key not in ledger:
            bad.append(f"台账缺顶层键 `{key}`")
    for key in FORBIDDEN_LEDGER_KEYS:
        if key in ledger:
            bad.append(f"台账出现硬编码计数键 `{key}`（会随追加而腐烂 ⇒ 条数一律现取）")
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        return bad + ["`entries` 必须是列表"]
    seen = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            bad.append(f"entries[{i}] 不是对象")
            continue
        for key, typ in ENTRY_REQUIRED.items():
            if key not in entry:
                bad.append(f"entries[{i}] 缺字段 `{key}`")
            elif not isinstance(entry[key], typ):
                bad.append(f"entries[{i}].{key} 类型应为 {typ.__name__}")
        if entry.get("kind") not in ENTRY_KINDS:
            bad.append(f"entries[{i}].kind={entry.get('kind')!r} 不在 {ENTRY_KINDS}")
        if entry.get("status") not in ENTRY_STATUSES:
            bad.append(f"entries[{i}].status={entry.get('status')!r} 不在 {ENTRY_STATUSES}")
        if entry.get("rerun_result") not in RERUN_RESULTS:
            bad.append(f"entries[{i}].rerun_result={entry.get('rerun_result')!r} 不在 {RERUN_RESULTS}")
        # 「可行动信息」不许是空壳（空字符串 = 有字段但不可行动，等于没有）
        for key in ("reason", "remedy"):
            if isinstance(entry.get(key), str) and not entry[key].strip():
                bad.append(f"entries[{i}].{key} 是空串 ⇒ 条目不可行动（照 #4757 形态：每条带 reason+remedy）")
        fu = entry.get("follow_up", None)
        if fu is not None and not isinstance(fu, int):
            bad.append(f"entries[{i}].follow_up 必须是整数跟踪单号或 null，实际 {fu!r}")
        # 「第二次绿 ⇒ flaky」的**方向**也必须自洽：重跑没绿就不许标 flaky
        if entry.get("kind") == "flaky" and entry.get("rerun_result") != "success":
            bad.append(f"entries[{i}] kind=flaky 但 rerun_result≠success —— 放行了未复现的失败")
        # #5088：新口径的 kind 必须**带原始事实**（只给结论不给读数 = 不可核 ⇒ 会被当成归因层用）
        if entry.get("kind") in FACT_BACKED_KINDS:
            attempts = entry.get("attempts")
            if not isinstance(attempts, list) or not attempts:
                bad.append(f"entries[{i}].kind={entry.get('kind')!r} 必须带原始事实 `attempts`"
                           f"（至少一条：这次尝试的失败步骤逐字）")
            else:
                for k, fact in enumerate(attempts):
                    if (not isinstance(fact, dict) or not isinstance(fact.get("attempt"), int)
                            or not isinstance(fact.get("step"), str)
                            or not (fact.get("assertion") is None
                                    or isinstance(fact.get("assertion"), str))):
                        bad.append(f"entries[{i}].attempts[{k}] 形状应为 "
                                   f"{{attempt:int, job:str, step:str, assertion:str|null}}")
                    # #5687：`timestamp` 是「失败时刻 / 重跑时刻」的取数面（承重字段，见
                    # `FACT_BACKED_KINDS` 的注释）—— 有它才复算得了跨桶判定。
                    elif not (fact.get("timestamp") is None or isinstance(fact.get("timestamp"), str)):
                        bad.append(f"entries[{i}].attempts[{k}].timestamp 应为 UTC ISO8601 字符串"
                                   f"或 null（#5687 的「失败时刻 / 重跑时刻」取数面）")
        # 🔴 #5687 判据③：`suspect-window-deterministic` **强制跟踪** —— 必须落跟踪单。
        # 机械形态（不是「文档要求人记得填」）：`append` / `selftest` / `reconcile` 都先跑本函数，
        # ⇒ 没有跟踪单的该类条目**根本写不进台账**（fail-closed），而不是「写进去之后靠人发现」。
        if entry.get("kind") == SUSPECT_WINDOW_KIND:
            fu = entry.get("follow_up")
            if not (isinstance(fu, int) and fu > 0):
                bad.append(
                    f"entries[{i}] kind={SUSPECT_WINDOW_KIND} 但 follow_up={fu!r} ⇒ "
                    f"**窗口型疑似必须强制跟踪**（#5687）：该类的全部意义是「需人看」，"
                    f"没有跟踪单就退化成一条没人看的记录。落单口径：{FOLLOW_UP_TRACKING_HOWTO}")
        # #5687 判据①②③：时间桶字段的形状/自洽（有它才复算得了「凭什么判这一类」）。
        for key in ("failed_at", "rerun_at"):
            if key in entry and not isinstance(entry.get(key), str):
                bad.append(f"entries[{i}].{key} 应为 UTC ISO8601 字符串（#5687 的判定依据）")
        if "rerun_bucket_verdict" in entry and entry.get("rerun_bucket_verdict") not in (True, False, None):
            bad.append(f"entries[{i}].rerun_bucket_verdict 应为 true/false/null（三态，"
                       f"null = 取不到时刻 ⇒ 证据不足，不得当 false 读）")
        # 「结论与依据不许自相矛盾」：`rerun_bucket_verdict` 是**取数面**，`kind` 是由它推出的
        # **结论** ⇒ 两者不一致 = 判据被绕过（或条目被人手改过）。
        verdict, entry_kind = entry.get("rerun_bucket_verdict"), entry.get("kind")
        if verdict is False and entry_kind not in (SUSPECT_WINDOW_KIND, "infra_suspect"):
            bad.append(f"entries[{i}] rerun_bucket_verdict=false（跨桶）却 kind={entry_kind!r} "
                       f"⇒ 跨桶的重跑通过**不得**判为普通 flaky（#5687：那正是缺陷被重跑掩盖的路径）")
        if verdict is True and entry_kind == SUSPECT_WINDOW_KIND:
            bad.append(f"entries[{i}] rerun_bucket_verdict=true（同桶）却 kind={SUSPECT_WINDOW_KIND!r} "
                       f"⇒ 把真 flaky 判成了窗口型疑似（#5687 的安全边界）")
        if entry.get("kind") == "unknown" and not str(entry.get("unknown_reason") or "").strip():
            bad.append(f"entries[{i}] kind=unknown 但 `unknown_reason` 为空 ⇒ 读的人不知道"
                       f"**为什么不归因**（fail-closed 也必须写明理由）")
        if entry.get("kind") == "deterministic":
            # 「归因必须有凭据」的机械形态：两次断言级事实（逐字）+ `attest` 凭据，缺一 ⇒ 违规
            facts = [f for f in (entry.get("attempts") or []) if isinstance(f, dict)]
            sigs = [f.get("assertion") for f in facts]
            if (len(facts) != 2
                    or len([s for s in sigs if isinstance(s, str) and s.strip()]) != 2
                    or len(set(sigs)) != 1):
                bad.append(f"entries[{i}] kind=deterministic 但两次尝试的断言摘要不齐/不同 "
                           f"⇒ **无凭据的归因**（deterministic 只能由 `attest` 写入）")
            if not str(entry.get("attested_evidence") or "").strip():
                bad.append(f"entries[{i}] kind=deterministic 缺 `attested_evidence`（日志取证凭据）"
                           f"⇒ 无凭据的归因")
        key = entry_key(entry)
        if key in seen:
            bad.append(f"entries[{i}] 幂等键重复 {key}（同一次失败记了多条）")
        seen.add(key)
    return bad


def reconcile(ledger: dict) -> dict:
    """**三态对账**（照 #4757 存量账本的口径，适配「事件追加日志」语义）。返回三个清单。

    | 态 | 判据 | 为什么必须能红 |
    |---|---|---|
    | `new_events` | `kind=flaky` 且 `status=open` 却**没有 `follow_up` 跟踪单** | 新 flaky 事件没登记修复路径 = 随机红照旧变成噪音（正是 #4717 要治的形态） |
    | `duplicates` | 幂等键 `(workflow, run_id, job)` 重复 | 同一次失败被记多条 ⇒ 计数被灌水（「N 次标 flaky」的 N 不可信） |
    | `fixed_not_deducted` | `status=fixed` 却（a）缺 `fixed_by` 凭据，或（b）同一 `(workflow, job)` 在它**之后**又出现 flaky 事件 | 销账不成立 / **修了又复发** ⇒ 「已修」是假账 |

    键全空 = 无欠账。**本判据不设阈值、不写死计数**；也**未接 required 门禁**（照实登记：
    它是**消费接口**，由后续单 / agent 按需调用）。
    """
    entries = ledger.get("entries") or []
    new_events, duplicates, fixed_not_deducted = [], [], []

    seen = set()
    for i, entry in enumerate(entries):
        key = entry_key(entry)
        if key in seen:
            duplicates.append({"index": i, "key": list(key),
                               "why": "幂等键重复 ⇒ 同一次失败记了多条（计数被灌水）"})
        seen.add(key)

    latest_flaky = {}
    for i, entry in enumerate(entries):
        if entry.get("kind") == "flaky":
            latest_flaky[f"{entry.get('workflow')} :: {entry.get('job')}"] = i

    for i, entry in enumerate(entries):
        group = f"{entry.get('workflow')} :: {entry.get('job')}"
        # #5687：`suspect-window-deterministic` **同样**要求跟踪单 —— 它比 `flaky` 更不能没人看
        # （`flaky` 至少被重跑复现过「不可复现」，而它是「**没修就会每天再红一次**」的形态）。
        # ⚠️ 这一行**有意**保持单行（与 `test_flaky_triage.py` 的注入式红证锚逐字一致）：
        # 锚失配会让那条红证变成**空断言**（本单已踩过一次，见该测试的 docstring）。
        if entry.get("kind") in ("flaky", SUSPECT_WINDOW_KIND) and entry.get("status") != "fixed" and not entry.get("follow_up"):
            new_events.append({
                "index": i, "key": list(entry_key(entry)),
                "why": (f"kind={entry.get('kind')} 且 status=open 但没有 follow_up 跟踪单 "
                        f"⇒ 未登记修复路径"),
                "remedy": entry.get("remedy"),
            })
        if entry.get("status") == "fixed":
            if not entry.get("fixed_by"):
                fixed_not_deducted.append({
                    "index": i, "key": list(entry_key(entry)),
                    "why": "status=fixed 但缺 fixed_by（修复凭据）⇒ 销账不成立",
                })
            elif latest_flaky.get(group, -1) > i:
                fixed_not_deducted.append({
                    "index": i, "key": list(entry_key(entry)),
                    "why": "已标 fixed，但同一 (workflow, job) 之后**又出现 flaky 事件** ⇒ "
                           "修复不成立（复发）",
                })
    return {"new_events": new_events, "duplicates": duplicates,
            "fixed_not_deducted": fixed_not_deducted}


# ── #5307：`follow_up` 的**回填路径**（字段级；不破坏「条目只追加」） ─────────────


class FollowUpError(Exception):
    """回填的 fail-closed 出口（CLI 捕获它 ⇒ 非零退出 + 明确报错，**绝不**静默无操作）。"""


def _positive_int(value, what: str) -> int:
    """正整数解析（fail-closed：`0` / 负数 / 非数字 ⇒ 抛 `ValueError`，**不**静默取默认值）。"""
    try:
        num = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{what}={value!r} 不是整数")
    if num <= 0:
        raise ValueError(f"{what}={value!r} 不是正整数")
    return num


def follow_up_index(ledger, run_id: int, job=None) -> list:
    """**定位**要回填的条目下标（只定位，不改任何东西）。任一条 fail-closed ⇒ 抛 `FollowUpError`。

    幂等键是 `(workflow, run_id, job)`，而 CLI 按 `run_id`(+`job`) 定位 ⇒ 同一 run 有**多个**
    job 的条目时会命中多条：此时**必须**由人给 `--job`，本函数**不猜**（猜错 = 把单号回填到
    另一个 job 上，比不回填更坏）。
    """
    entries = (ledger or {}).get("entries") or []
    hits = [i for i, e in enumerate(entries)
            if e.get("run_id") == run_id and (job is None or e.get("job") == job)]
    if not hits:
        where = f"run_id={run_id}" + (f" job={job!r}" if job is not None else "")
        recent = sorted({str(e.get("run_id")) for e in entries})[-5:]
        raise FollowUpError(
            f"{where} 不在台账里（台账共 {len(entries)} 条）⇒ **拒绝回填** —— 本命令只回填"
            f"**已存在条目**（不新增条目；新增走 `append`）。最近几条 run_id："
            f"{'、'.join(recent) if recent else '（空台账）'}")
    if len(hits) > 1 and job is None:
        lines = [f"run_id={run_id} 命中 {len(hits)} 条（同一 run 的**不同 job**）⇒ 必须用 "
                 f"`--job` 指定（本命令不猜：回填到错的 job 上比不回填更坏）："]
        for i in hits:
            lines.append(f"   · --job {shlex.quote(str(entries[i].get('job')))}"
                         f"（entries[{i}] kind={entries[i].get('kind')}）")
        raise FollowUpError("\n".join(lines))
    return hits


def apply_follow_up(ledger, indices, *, issue=None, status=None, fixed_by=None) -> dict:
    """把跟踪单号（及可选的 `status=fixed` + `fixed_by`）回填到**已存在条目**上。

    **只改指定条目的这三个字段** —— 不新增、不删除、不重排条目。「条目只追加」的语义由
    `append_entries` 承担，本函数是唯一的**字段级**例外（#5307 的验收判据明确要求它只改字段）。

    返回 `{"changed": [...], "idempotent": bool}`；每个 change 带 `index / key / before / after`
    （逐字记录 ⇒ 可审计，也是「条目数与顺序不变」的取证材料）。

    fail-closed（抛 `FollowUpError`，全部**不写盘**）：
      · 不给 `--issue` 且该条目 `follow_up` 本就为空 ⇒ 拒绝（本命令不替它编单号）；
      · `--status fixed` 却不给 `--fixed-by` ⇒ 拒绝（否则 `reconcile` 判「销账不成立」）；
      · 只给 `--fixed-by` 不给 `--status fixed` ⇒ 拒绝（那会写出无凭据的销账）。
    """
    entries = (ledger or {}).get("entries") or []
    changed = []
    for i in indices:
        entry = entries[i]
        before = {k: entry.get(k) for k in ("follow_up", "status", "fixed_by")}
        target = dict(before)
        if issue is not None:
            target["follow_up"] = issue
        elif not isinstance(before["follow_up"], int) or before["follow_up"] <= 0:
            raise FollowUpError(
                f"entries[{i}]（run_id={entry.get('run_id')} job={entry.get('job')!r}）的 "
                f"follow_up={before['follow_up']!r} ⇒ 必须显式给 `--issue <跟踪单号>`"
                f"（本命令不替它编单号）")
        if status == "fixed":
            if not str(fixed_by or "").strip():
                raise FollowUpError(
                    "`--status fixed` 必须同时给 `--fixed-by '<PR / run / 用例>'` ⇒ 否则会写出"
                    "**无凭据的销账**（`reconcile` 判「销账不成立」，比不改更坏）")
            target["status"] = "fixed"
            target["fixed_by"] = str(fixed_by).strip()
        elif fixed_by:
            raise FollowUpError("`--fixed-by` 只能与 `--status fixed` 一起用"
                                "（否则会写出无凭据的销账）")
        if target == before:
            continue
        for field in ("follow_up", "status", "fixed_by"):
            if target[field] != before[field]:
                entry[field] = target[field]
        changed.append({"index": i, "key": list(entry_key(entry)),
                        "before": before, "after": target})
    return {"changed": changed, "idempotent": not changed}


# ── #5088：`attest` —— 用**日志取证**回填断言级事实并给结论（「归因必须有凭据」） ──────


class AttestError(Exception):
    """`attest` 的 fail-closed 出口（CLI 捕获 ⇒ 非零退出 + 明确报错，**绝不**静默无操作）。"""


def apply_attestation(ledger, indices, *, attempt1_assertion, attempt2_assertion, evidence) -> dict:
    """把**日志取证**得到的两次尝试断言摘要写进**已存在条目**，并据唯一判据给结论。

    **字段级**（与 #5307 的 `follow-up` 同口径）：只改 `attempts` / `kind` / `reason` / `remedy` /
    `unknown_reason` / `attested_evidence`，**不**新增、不删除、不重排条目、不碰其它字段。

    为什么必须有它（**#5088 的病灶是「结论没有凭据、也没人能补凭据」**）：自动路径只有步骤级事实
    （GitHub 的 jobs API 不给断言文本）⇒ 两次都红只能记 `unknown`；要让台账给出 `deterministic`，
    必须有人把两次尝试的**日志读数**逐字回填 —— 本命令就是那个**合法工具**
    （#5307 的教训：文档要求做、却没有工具做的动作 = 自我死锁）。

    fail-closed（抛 `AttestError`，全部**不写盘**）：
      · 两次断言摘要或 `--evidence` 为空 ⇒ 拒绝（凭据为空 = 无凭据的归因，比不归因更坏）；
      · 条目 `rerun_result != "failure"` ⇒ 拒绝（重跑绿（`flaky`）/ 没重跑过的条目**不适用**本判据）；
      · 条目缺 `attempt=2` 的原始事实 ⇒ 拒绝（不知第二次尝试的失败步骤，回填会写出不自洽的事实）。

    结论 = `classify_both_red`（**唯一**判据，不写第二份）：两次同一断言同一错误 ⇒ `deterministic`；
    不同 ⇒ 仍 `unknown`（#5088 的建议口径「两次红的不是同一条断言 ⇒ 不得记确定性」）。
    """
    entries = (ledger or {}).get("entries") or []
    fields = ("attempts", "kind", "reason", "remedy", "unknown_reason", "attested_evidence")
    changed = []
    for i in indices:
        entry = entries[i]
        where = (f"entries[{i}]（run_id={entry.get('run_id')} "
                 f"job={entry.get('job')!r}）")
        if entry.get("rerun_result") != "failure":
            raise AttestError(
                f"{where} 的 rerun_result={entry.get('rerun_result')!r} ⇒ 本判据**只适用于"
                f"「两次都红」**的条目（重跑绿的 `flaky` 条目与没重跑过的条目不适用）")
        facts = [f for f in (entry.get("attempts") or []) if isinstance(f, dict)]
        if not any(int(f.get("attempt") or 0) == 2 for f in facts):
            raise AttestError(
                f"{where} 缺 `attempt=2` 的原始事实（`attempts` 现取 = "
                f"{[f.get('attempt') for f in facts]!r}）⇒ 拒绝回填（不知第二次尝试的失败步骤，"
                f"回填会写出不自洽的事实）")
        before = {k: copy.deepcopy(entry.get(k)) for k in fields}
        for fact in facts:
            if int(fact.get("attempt") or 0) == 1:
                fact["assertion"] = str(attempt1_assertion)
            elif int(fact.get("attempt") or 0) == 2:
                fact["assertion"] = str(attempt2_assertion)
        a1 = next((f for f in facts if int(f.get("attempt") or 0) == 1), None)
        a2 = next((f for f in facts if int(f.get("attempt") or 0) == 2), None)
        kind, unknown_reason = classify_both_red(a1, a2)
        entry["kind"] = kind
        entry["reason"] = KIND_REASON[kind]
        entry["remedy"] = KIND_REMEDY[kind]
        if unknown_reason:
            entry["unknown_reason"] = unknown_reason
        elif "unknown_reason" in entry:
            del entry["unknown_reason"]
        entry["attested_evidence"] = str(evidence).strip()
        after = {k: copy.deepcopy(entry.get(k)) for k in fields}
        if after == before:
            continue
        changed.append({"index": i, "key": list(entry_key(entry)),
                        "before": before, "after": after})
    return {"changed": changed, "idempotent": not changed}


def render_reconcile_report(ledger, result, ledger_path: str = LEDGER_REL) -> str:
    """把 `reconcile` 的欠账渲染成**可行动**清单 + **可直接复制**的回填命令（#5307 判据②）。

    为什么必须有它（本单病灶的权利人一侧）：required 测试
    `test_shipped_ledger_reconciles_clean` 失败时输出只有 `assert {...} == {...}` 的 diff，
    读的人**不知道下一步做什么**；而台账 schema 只写「由分诊方回填」、没写**用哪个命令**
    ⇒ 回填是「文档要求做、却没有合法工具做」的动作（死锁的一半）。

    每条欠账都给出 `workflow` / `run_id` / `job` **三个定位键**，再给一条可复制的命令
    （命令口径 = `FOLLOW_UP_HOWTO`，单一事实源，不在这里另写一套措辞）。
    """
    entries = (ledger or {}).get("entries") or []

    def entry_at(row) -> dict:
        i = row.get("index")
        return entries[i] if isinstance(i, int) and 0 <= i < len(entries) else {}

    def where(entry) -> str:
        return (f"{entry.get('workflow')} / run {entry.get('run_id')} / "
                f"job `{entry.get('job')}`")

    def cmd(entry, extra: str = "") -> str:
        return (f"python3 .github/scripts/flaky_ledger.py follow-up --ledger {ledger_path} "
                f"--run-id {entry.get('run_id')} "
                f"--job {shlex.quote(str(entry.get('job')))}{extra}")

    lines = ["❌ 台账欠账（#5307）—— 每条都给出 `workflow` / `run_id` / `job` 与**可直接复制**的回填命令："]
    for row in result.get("new_events") or []:
        entry = entry_at(row)
        lines += [
            f"  · [未登记修复路径] {where(entry)}"
            f"（kind={entry.get('kind')} · status={entry.get('status')} · "
            f"follow_up={entry.get('follow_up')!r}）",
            f"    ⇒ {cmd(entry, ' --issue <跟踪单号>')}",
        ]
    for row in result.get("fixed_not_deducted") or []:
        entry = entry_at(row)
        if "fixed_by" in str(row.get("why") or ""):
            hint = "    ⇒ " + cmd(entry, " --status fixed --fixed-by '<修复凭据：PR / run / 用例>'")
        else:
            hint = (f"    ⇒ 该 (workflow, job) 之后**又出现 flaky 事件**（修复不成立）："
                    f"先按条目 `remedy` 重新定位机制并给红证，**不许**只改 status")
        lines += [f"  · [已修未销账] {where(entry)}（{row.get('why')}）", hint]
    for row in result.get("duplicates") or []:
        entry = entry_at(row)
        lines += [
            f"  · [重复记账] {where(entry)}（幂等键重复 ⇒ 同一次失败记了多条）",
            f"    ⇒ **无对应子命令**（本命令只回填已存在条目、不删条目）：需人工核对该键的重复项后"
            f"手工删除多余条目（台账「只追加」的语义由人核账兜底）",
        ]
    lines += [
        f"回填口径（单一事实源）：{FOLLOW_UP_HOWTO}",
        "回填位置 = **持有该条目的那份台账**（同幂等键以 main 为准 ⇒ 已落 main 的条目要在 main 的"
        "副本上改；分支台账上的条目在台账分支上改）；回填后 `reconcile` 与本清单应归零。",
    ]
    return "\n".join(lines)


def aggregate(ledger: dict) -> dict:
    """按 `(workflow, job)` 聚合 —— **计数一律现取**（台账里不存任何计数，故不会腐烂）。

    这是台账的**消费接口**：后续单要判「某用例连续 N 次标 flaky ⇒ 必须修」时，
    拿这里的 `flaky` 计数自己定阈值 —— **阈值不写进本仓库**（#4701/#4714/#4742 纪律：
    硬编码计数/阈值会随追加而腐烂；本仓库 `time_flaky_guard.py` 的存量账本同此口径）。

    #5088：`unknown`（= 事实不足以归因）**单独成列**，且 `attributed` 只统计
    `ATTRIBUTABLE_KINDS` ⇒ 消费方**结构上**拿不到「把 unknown 当归因」的计数
    （「禁止用 unknown 归因」的机械形态；`confirmed_failure` 是旧口径存量值，同样单列、不作归因依据）。
    """
    groups: dict = {}
    for entry in ledger.get("entries") or []:
        key = f"{entry.get('workflow')} :: {entry.get('job')}"
        slot = groups.setdefault(key, {
            "workflow": entry.get("workflow"), "job": entry.get("job"),
            "total": 0, "flaky": 0, "confirmed_failure": 0, "infra_suspect": 0,
            "deterministic": 0, "unknown": 0, "attributed": 0,
            "last_run_id": None, "last_observed_at": None,
        })
        slot["total"] += 1
        if entry.get("kind") in ENTRY_KINDS:
            slot[entry["kind"]] += 1
        if entry.get("kind") in ATTRIBUTABLE_KINDS:
            slot["attributed"] += 1
        slot["last_run_id"] = entry.get("run_id")
        slot["last_observed_at"] = entry.get("observed_at")
    return groups


# ── 网络薄封装（只取事实；判据不在这里） ────────────────────────────────────────


def _merge_pages(pages) -> dict:
    """**纯函数**：把 `gh api --paginate --slurp` 的多页浅合并成**一个**对象。

    合并口径（按**值的形状**分派，不按字段名）：值是 `list` 的字段 ⇒ **跨页累加**；
    标量（`total_count` 等，各页同值）⇒ **覆盖**。

    🔴 **#5264 的病根就在这个函数的旧口径**（实测，别再重新猜）：旧实现写成
    `merged.update({k: v for k, v in page.items() if k != "jobs"})` + **只**把 `jobs` 累加
    ⇒ **列表字段被每页覆盖** ⇒ 分页后**只剩最后一页**。实测（2026-09-24，`gh` 复算）：

        gh api "repos/zhaokai-mgzn/migao/actions/runs?event=pull_request\
    &branch=chore/flaky-ledger&per_page=100" --paginate --slurp
        ⇒ 3 页（100/100/11），total_count=211
        而旧口径的 `_gh_api(同一 URL)` ⇒ **11** 条，且全是**最老**的
        （created_at ≤ 2026-09-20T06:13:26Z）
        ⇒ `runs_needing_approval()` 只看得到那 11 条早已作废的 run ⇒ 恒返回 `[]`
        ⇒ `approve` 一次都没发出去 ⇒ 台账 PR #5139 的 run 永远停在 `action_required`
        （0 个 job、0 条 check）⇒ auto-merge 永不触发 ⇒ 台账冻结。

    ⚠️ 历史注记：**#4804 当年「实测有效」是真的** —— 那时该分支的 PR run 数 < 100 ⇒
    `--slurp` 返回**单页** ⇒ 走 `_gh_api` 的「单页短路」分支（那条路径**正确**）。
    **跨过一页之后**这个机制才**静默失效**（没有任何东西会因此变红）。⇒ 单页短路**保留**，
    多页合并按上面的形状分派修好。

    刻意**不**在标量冲突时报错：本函数只做浅合并（判据不在这里），且 `total_count` 各页必然同值。
    """
    merged: dict = {}
    for page in pages or []:
        if not isinstance(page, dict):
            continue
        for key, value in page.items():
            if isinstance(value, list):
                prev = merged.get(key)
                merged[key] = (prev if isinstance(prev, list) else []) + list(value)
            else:
                merged[key] = value
    return merged


def _gh_api(path: str, *, method: str = "GET", fields=None) -> dict:
    """`gh api` 薄封装。默认 **GET**（`--paginate --slurp` ⇒ 多页合并，见 `_merge_pages`）。

    #5687：另支持**写**（`method="POST"` + `fields`）—— 目前唯一调用方是「窗口型疑似的跟踪单」
    的创建（`ensure_tracking_issue`）。写路径**不带** `--paginate`（分页是读侧的语义）。
    """
    cmd = ["gh", "api", "--paginate", "--slurp"]
    if method != "GET":
        cmd = ["gh", "api", "-X", method]
    for key, value in (fields or {}).items():
        # `-f` 走字符串语义（`-F` 会把 `@`/数字做强转 —— 跟踪单的 body 里正好有 `#`/`@` 形态）
        cmd += ["-f", f"{key}={value}"]
    cmd.append(path)
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    # --slurp 对单页返回 [obj]；对分页返回 [obj, obj…]（jobs 走 per_page=100 单页即可）
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, list):
        return _merge_pages(data)
    return data


def fetch_bundle(repo: str, run_id: int) -> dict:
    run = _gh_api(f"repos/{repo}/actions/runs/{run_id}")
    attempt = _attempt(run)
    jobs = (_gh_api(f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs")
            .get("jobs") or [])
    prior_jobs = None
    if attempt >= 2:
        prior_jobs = (_gh_api(f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt - 1}/jobs")
                      .get("jobs") or [])
    return {"run": run, "jobs": jobs, "prior_jobs": prior_jobs}


# ── #4804：批准被 GITHUB_TOKEN 抑制的台账 PR run（台账落 main 的唯一通路） ──────


def runs_needing_approval(runs, workflows=None) -> list:
    """**纯函数**：挑出「被 GITHUB_TOKEN 抑制、需显式 approve 才能跑」的 run id（升序）。

    病根（#4804，实测）：本 workflow 用 `GITHUB_TOKEN` 建台账 PR ⇒ GitHub **抑制**该 PR
    的 `pull_request` 事件所引发的 workflow ⇒ 那批 run 全部停在 `conclusion=action_required`
    （**run 被创建了、但一个 job 都没有**，`check-runs` 为空）⇒ `gh pr checks` 报
    「no checks reported」⇒ required 集合永远不满足 ⇒ `--auto` **永不触发** ⇒ 台账停在分支上。
    （与「条件没满足」的区别：条件没满足时 run 会**真的跑**并给出结论；这里是**零 job**。）

    判据只看**事实**：`event == pull_request` ∧ `conclusion == action_required`
    ∧（给了 `workflows` 时）`name ∈ workflows`。

    ⚠️ **为什么要 `workflows` 白名单**（越权面收敛）：同一分支上的 run 不止本 workflow 分流的
    那几个 —— **实测**台账分支上还有 `Drift Audit (真相源契约)` / `PR Issue Link Check` /
    `Deploy Reconcile (PR 对账补偿)`。批准**别的** workflow 的运行不属本机制职责。
    白名单**由调用方传入**（单一事实源 = `TRIAGED_WORKFLOWS`），本函数不硬编码副本。

    故意**不**按 `head_branch` 过滤 —— 过滤是调用方的事（本函数保持可单测的纯粹性），
    且 run 一旦被批准，`run_attempt` 会 +1、`conclusion` 变 null ⇒ **天然幂等**（不会重复 approve）。
    """
    allowed = None if workflows is None else set(workflows)
    out = []
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        if run.get("event") != "pull_request":
            continue
        if run.get("conclusion") != "action_required":
            continue
        if allowed is not None and run.get("name") not in allowed:
            continue
        rid = run.get("id")
        if isinstance(rid, int):
            out.append(rid)
    return sorted(out)


def branch_tip(listing) -> str | None:
    """**纯函数**：从 `GET /repos/{owner}/{repo}/branches/{branch}` 的响应里取分支 tip 的 sha。

    **实测（2026-09-24，读源不是猜）**：`gh api repos/zhaokai-mgzn/migao/branches/chore/flaky-ledger`
    ⇒ `{"name": "chore/flaky-ledger", "commit": {"sha": "519250fe9bf175bcf0a735a0b08969e376382409"}, …}`
    —— 分支名里的 `/` **不编码也能用**（返回的 `name` 逐字就是 `chore/flaky-ledger`，证明它没被
    解析成别的路径）；`chore%2Fflaky-ledger` 拿到**同一个** sha。本函数只认**响应形状**，
    不管调用方的 URL 怎么拼（故两种写法都兼容）。

    取不到 ⇒ `None`（调用方 **fail-closed**；**不许**退回「最新可见的待批准 run 的 sha」——
    见 `runs_for_head` 的说明）。
    """
    if not isinstance(listing, dict):
        return None
    commit = listing.get("commit")
    sha = commit.get("sha") if isinstance(commit, dict) else None
    return sha if isinstance(sha, str) and sha else None


def runs_for_head(runs, head_sha) -> list:
    """**纯函数**：只保留 `head_sha == head_sha`（= **分支 tip 那一次推送**）的候选 run。

    为什么必须收窄（**实测**）：分页修好后候选从 11 个涨到几十上百个 —— 实测该分支 211 个 run 里
    白名单口径命中 **74** 个 ⇒ 全批准 = 74 个 workflow 真的跑起来（**CI 雪崩**），而**只有 tip 那一批**
    的 check-run 能决定 PR 的 required 状态（陈旧 push 的 check 挂在旧 commit 上，required 判定看 head）。

    为什么 tip 要**从分支事实**取（`branch_tip`），而不是「最新可见的待批准 run 的 sha」：
    `flaky-triage.yml` 步骤④ **刚 push 完台账分支就立刻 approve**，而 GitHub 创建 run 是**异步**的 ⇒
    此刻可见的「最新 run」可能还是**上一次**推送的 ⇒ 拿它当 tip 会把**陈旧 SHA** 的 run 批准起来，
    且日志会把「批准了陈旧 SHA」说成「批准了本次推送」—— 正是本仓最忌的**读数与事实不一致**。

    空/畸形输入（含 `head_sha` 为空）⇒ 空集（**不是**「通过」）。
    """
    if not head_sha:
        return []
    return [r for r in (runs or [])
            if isinstance(r, dict) and r.get("head_sha") == head_sha]


# ── #5417：审批队列的**幂等重试**与**可归因读数**（停在 action_required 的 run 不许静默） ──
#
# 病根（**实测**，2026-09-25 台账 PR #5563 / push `425732992`）：`approve` 在 push 之后
# **单发一次**，而 GitHub 创建 run 是**异步**的 ⇒ 那一刻 tip 上「暂无待批准 run」⇒ 脚本按
# 「诚实读数」退出 **0**（workflow 跟着绿）⇒ 台账 PR 停在 `check 数=0 / mergeStateStatus=BLOCKED`
# —— 实测 **18 分钟**（09:07:26 → 09:25:31）后才被**另一条** workflow 的兜底轮次顺手批上。
# 逐字证据（triage run 36116623413 步骤⑤ 日志）：
#   `ℹ️ tip=425732992180fada5f187ae10e4f67ea49c61904 暂无待批准 run（尚未创建或已批准）⇒ 本轮零动作`
#   同刻（09:08:04）读数：`state=OPEN mergeStateStatus=BLOCKED autoMerge=armed / check 数=0`
# ⇒ 修法 = **幂等重试**（`--wait-seconds`）：轮询到 tip 的审批队列**清空**为止；窗口用尽仍非空 ⇒
# **非零退出**（fail-closed）。⚠️ 「批准是异步的」不等于「批准没生效」：窗口内的残余**不算失败**。
#: 轮询间隔（秒）；取小值只为让窗口尽量贴合「GitHub 把 run 标成 action_required」的延迟。
APPROVE_POLL_SECONDS = 5


def _monotonic() -> float:
    """单调时钟读数（**单测可替换**：窗口判据不该真等满 90 秒 —— 见
    `tests/unit_ci_workflows/test_flaky_ledger_approval_wait.py` 的假时钟）。"""
    return time.monotonic()


def run_url(repo: str, run_id: int) -> str:
    """run 的**可点击出口**：读数要「可归因」，就必须带得上链接（否则只说了一半）。"""
    return f"https://github.com/{repo}/actions/runs/{run_id}"


def _age_minutes(created_at, now=None):
    """`created_at`（ISO8601 / `Z` 结尾）→ 分钟；解析不了 ⇒ `None`（**不许**猜成 0 = 刚创建）。"""
    if not isinstance(created_at, str) or not created_at:
        return None
    try:
        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - ts).total_seconds() / 60.0


def approval_queue_reading(runs, *, repo, head_sha=None, min_age_minutes=0.0,
                           now=None, limit=10) -> dict:
    """**纯函数**（零 IO）：把「停在 `action_required` 的 run」分成三类并给出出口。

    三类必须**分开报**（#5417 判据 1）—— 否则「机制没生效」与「按设计不批」会长得一样：
      · `in_scope` —— `TRIAGED_WORKFLOWS` 内、且挂在分支 tip 上：它们停在队列 = **机制失效**
        （台账 PR 拿不到 required 的 check ⇒ 落不了 main），必须处置；
      · `out_of_scope` —— 白名单外：机制**故意不批**（白名单口径 = 「重跑无副作用」，报告型 /
        有仓外副作用的 workflow 不在其中），它们**不在 required 集合** ⇒ 批了只会给台账 PR 添红；
      · `stale` —— 非分支 tip 的陈旧推送：**只计数**（tip 收窄的必然结果：批准它们对 required
        判定零贡献、只会放大 CI）。

    `min_age_minutes` 只过滤**读得出年龄**的条目：年龄未知（`created_at` 畸形）⇒ **保留**
    （fail-closed：不许把「读不出」当「刚创建」滤掉）。`head_sha=None` ⇒ 不按 tip 分流（全算 in/out）。
    """
    now = now or datetime.now(timezone.utc)
    allowed = set(TRIAGED_WORKFLOWS)
    buckets: dict = {"in_scope": [], "out_of_scope": [], "stale": 0, "unaged": 0}
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        if run.get("event") != "pull_request" or run.get("conclusion") != "action_required":
            continue
        rid = run.get("id")
        if not isinstance(rid, int):
            continue
        if head_sha and run.get("head_sha") != head_sha:
            buckets["stale"] += 1
            continue
        age = _age_minutes(run.get("created_at"), now)
        if age is None:
            buckets["unaged"] += 1
        elif min_age_minutes and age < float(min_age_minutes):
            continue
        entry = {"id": rid, "name": run.get("name"),
                 "age_minutes": None if age is None else round(age, 1),
                 "url": run_url(repo, rid)}
        buckets["in_scope" if run.get("name") in allowed else "out_of_scope"].append(entry)
    for key in ("in_scope", "out_of_scope"):
        buckets[key] = sorted(buckets[key], key=lambda e: (e["age_minutes"] is None, e["id"]))
        buckets[key + "_total"] = len(buckets[key])
        buckets[key] = buckets[key][:limit]
    return buckets


def approve_runs(repo: str, run_ids) -> list:
    """逐个 `POST …/actions/runs/{id}/approve`（走 `gh api`，`GH_TOKEN` 来自环境）。

    需要 `actions: write`（本 workflow 已声明）。**fail-closed**：任一 approve 失败 ⇒
    抛 `RuntimeError` ⇒ CLI 非零 ⇒ workflow 红（「批准没发出去」不许装成「已经放行」）。
    """
    failed = []
    for rid in run_ids:
        proc = subprocess.run(
            ["gh", "api", "-X", "POST", f"repos/{repo}/actions/runs/{rid}/approve"],
            capture_output=True, text=True)
        if proc.returncode != 0:
            failed.append((rid, (proc.stderr or proc.stdout or "").strip()[:200]))
    if failed:
        raise RuntimeError("；".join(f"run {rid}：{why}" for rid, why in failed))
    return list(run_ids)


# ── #5301 判据②：台账分支失败 job 的**兜底重跑**（上限 1 次；只作用于台账分支） ──────
#
# 为什么必须有它（**实测**，不要重新猜）：台账分支的 CI 失败此前**没有任何自动重跑路径** ——
#   · `decide()` 的**自指守卫**逐字判 `head_branch == LEDGER_BRANCH` ⇒ skip（防自指递归：
#     台账 PR 又被分流）⇒ `flaky-triage.yml` **结构上**不救它；
#   · 本兜底原先只补 approve + arm、**不读失败原因更不重跑**（#5307 只补了**可见性**）。
# 实测形态：台账 PR #5139 的 required 测试 4 次尝试同形失败（7m32s~8m16s）⇒ 台账停摆约 40 小时，
# 解阻靠**人工** `gh run rerun <id> --failed`。
#
# ⚠️ 上限的**事实源是 GitHub 的 `run_attempt`**（重跑一次必 +1），**不是**本兜底记的计数器：
#    计数器随进程消失 ⇒ 每 20 分钟触发一轮的兜底迟早变成**无限重跑**（红线）。
#    以 `run_attempt` 为判据 ⇒ 天然幂等：同一 run 只会被重跑一次，且「已重跑过」与「首次」**可判**。


def runs_needing_rerun(runs, *, head_branch: str = LEDGER_BRANCH, workflows=None,
                       head_sha=None, max_reruns: int = MAX_LEDGER_RERUNS) -> dict:
    """**纯函数**：从 run 列表分出「可重跑」与「重跑额度已用尽」两类（只取事实，零 IO）。

    返回 `{"rerun": [...], "exhausted": [...], "out_of_scope": int}`；每条 =
    `{id, name, attempt, head_sha, head_branch}`。

    判据（缺一不可，且都是**硬条件**，不是调用方约定）：
      · `head_branch == head_branch` —— **只作用于台账分支**（#5301 判据④：注入放宽 ⇒ 守卫必红）；
      · `event == pull_request` —— 同 `decide()`（部署 / 定时 / 手动的 run 不参与分流）；
      · `name ∈ workflows` —— 复用 `TRIAGED_WORKFLOWS` 白名单（「PR 上跑测试、重跑无副作用」才收；
        白名单**由调用方传入** ⇒ 本函数不硬编码副本）；
      · `head_sha == head_sha`（给了才判）—— **只救分支 tip 的 run**：陈旧 push 的 check 挂在旧
        commit 上，重跑它对「PR 能否合并」零贡献，却真烧 CI 分钟（#5264 实测：该分支 211 个 run 里
        白名单口径命中 **74** 个 ⇒ 全重跑 = CI 雪崩）；
      · `conclusion == failure` —— 只有失败才有「重跑失败 job」可言（取消 / 超时 / 基础设施一族
        同 `NOT_TEST_FAILURE_CONCLUSIONS` 的口径 ⇒ 不重跑）；
      · **上限**：`attempt <= max_reruns`（= 1）⇒ 可重跑；否则 ⇒ `exhausted`（**已重跑过**，
        不论由谁发起：本兜底 / 人 / 别的路径）—— 这就是「首次」与「已重跑过」的**可判**区分。
    """
    allowed = None if workflows is None else set(workflows)
    out = {"rerun": [], "exhausted": [], "out_of_scope": 0}
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        if str(run.get("head_branch") or "") != head_branch:
            out["out_of_scope"] += 1
            continue
        if str(run.get("event") or "") != "pull_request":
            out["out_of_scope"] += 1
            continue
        if allowed is not None and run.get("name") not in allowed:
            out["out_of_scope"] += 1
            continue
        if head_sha and run.get("head_sha") != head_sha:
            out["out_of_scope"] += 1
            continue
        if _conclusion(run) != "failure":
            out["out_of_scope"] += 1
            continue
        rid = run.get("id")
        if not isinstance(rid, int):
            continue
        entry = {"id": rid, "name": run.get("name"), "attempt": _attempt(run),
                 "head_sha": run.get("head_sha"), "head_branch": run.get("head_branch")}
        (out["rerun"] if entry["attempt"] <= max_reruns else out["exhausted"]).append(entry)
    return out


def rerun_failed_run(repo: str, run_id: int) -> None:
    """`gh run rerun <run-id> --failed`（**只重跑失败的 job**，不重跑整个 run）。

    形态与 `flaky-triage.yml` 的重跑步骤是**同一条命令**（判据只有一处，不复制规则）。需要
    `actions: write`（本兜底已声明）。**fail-closed**：非零 ⇒ 抛 `RuntimeError` ⇒ CLI 非零 ⇒
    workflow 红（「重跑没发出去」不许装成「兜底已生效」）。
    """
    proc = subprocess.run(
        ["gh", "run", "rerun", str(run_id), "--failed", "--repo", repo],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh run rerun {run_id} --failed 失败（rc={proc.returncode}）："
            f"{(proc.stderr or proc.stdout or '').strip()[:200]}")


def run_attempt_after_rerun(repo: str, run_id: int):
    """重跑**之后回读** `run_attempt`（读数必须来自动作之后的事实）；取不到 ⇒ `None`（不假装成功）。"""
    try:
        return _attempt(_gh_api(f"repos/{repo}/actions/runs/{run_id}"))
    except (subprocess.CalledProcessError, ValueError):
        return None


# ── #4825：台账落仓的**状态级对账**（独立兜底；不依赖 flaky-triage.yml 还活着） ────
#
# 为什么需要它（**实测**，别照抄 issue 文本）：#4804 的修法（上面的 `approve`）是
# `flaky-triage.yml` 的一个**步骤** ⇒ 该 workflow 一停（被禁用 / 语法坏 / `actions: write` 丢），
# 台账就**静默**停在 `chore/flaky-ledger` 分支上 —— 它不参与 required 集合，台账停在分支上
# 不会让任何 PR 变红，**没有任何东西会因此告警**。
# 本节的判据只看**状态**（分支内容 vs main 内容），不看事件 ⇒ 与 `workflow_run` 触发面正交，
# 故可作为独立兜底（形态照抄 `.github/workflows/deploy-reconcile.yml` 的「独立对账」先例）。

#: 台账的**相对**路径见常量区（`LEDGER_REL`；`read_main_ledger_live` / `read_branch_ledger` 都用它）


def _key_str(key) -> str:
    """幂等键的可读/可比较形态（`workflow/run_id/job`）—— 报告与对账都用它，避免元组排序问题。"""
    return "/".join(str(part) for part in key)


def ledger_keys(ledger) -> set:
    """台账条目的幂等键集合（`(workflow, run_id, job)`）。计数一律**现取**。"""
    return {entry_key(e) for e in (ledger or {}).get("entries") or []}


def ledger_drift(main_ledger, branch_ledger) -> dict:
    """**纯函数**（无 IO）：#4825 兜底的判据本体 —— 台账分支相对 main 的漂移。

    期望状态由台账语义决定（**只追加** ⇒ main 的条目集恒为分支的子集）：
      · `ahead`  = 分支有、main 没有 ⇒ **已记账却没落到 main**（本单要治的形态：
        台账停在分支上，而谁也不会因此变红）；
      · `behind` = main 有、分支没有 ⇒ 分支被改写/回退（**不该出现**：只追加语义被破坏）。

    返回的 `ahead`/`behind` 是**排好序的字符串键**（幂等键的可读形态），不是计数 ——
    本文件与 workflow 都**不写死任何条数/阈值**（硬编码计数会随追加腐烂，见 #4701/#4714/#4742）。
    """
    main_keys = ledger_keys(main_ledger)
    branch_keys = ledger_keys(branch_ledger)
    return {
        "ahead": sorted(_key_str(k) for k in branch_keys - main_keys),
        "behind": sorted(_key_str(k) for k in main_keys - branch_keys),
        "main_total": len(main_keys),
        "branch_total": len(branch_keys),
    }


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


# ── #5649：台账分支**存在性**的唯一读数（防「同一条件两套读数」） ─────────────────────
#
# 病根（2026-09-26 **实测**，run 36237750162 的 CI 日志逐字）：同一个条件（台账分支不存在），
# 两个子命令给出**两套读数** ——
#   · `reconcile --branch` ⇒ `ℹ️ 台账分支 \`chore/flaky-ledger\` 不存在 ⇒ 没有可对账的台账（非欠账）`
#     ⇒ 退 **0**（该步骤**已过** ✅）；
#   · `approval-queue` 去取分支 tip（`GET /repos/{repo}/branches/{head_branch}`）撞 **404**
#     ⇒ 与「gh 真失败」**同一分支**被读成「无法判定」⇒ 退 **3** ⇒ 步骤 `::error::` ❌。
# ⇒ `Flaky Ledger Reconcile`（**不在 required 集合**）**对每个 PR 都红**：不拦合并，但持续
#   稀释「红 = 有事」的信号。此前的 #5438 / #5417 覆盖的是「欠账」与「审批队列被抑制」，
#   **「分支已被删」这个形态没被覆盖**。
#
# 修法 = **一处读数 + 一张判定表**（不是两处各修一遍，也不是把「无法判定」放宽）：
#   · `branch_presence()` —— 分支存在性的**唯一读数**（三态 `exists` / `absent` / `unknown`）；
#   · `BRANCH_PRESENCE_VERDICT` —— **唯一口径表**（状态 → 退出码），两个子命令都查它。
# ⇒ 两个子命令**结构上不可能**再对同一状态给出两套读数（类级守卫见
#   `tests/unit_ci_workflows/test_flaky_ledger_branch_presence_consistency.py`）。
#
# ⚠️ **不许**把「无法判定」降级成「通过」：只有 `absent`（**确定**不存在）判「无内容」（退 0）；
#    `unknown`（网络 / 权限 / 命令失败 / 取不到 tip）**照旧退 3**，且两个子命令**同判**。
BRANCH_EXISTS = "exists"
BRANCH_ABSENT = "absent"
BRANCH_UNKNOWN = "unknown"

#: 状态 → 两个子命令**共用**的退出码（`exists` **不在表里** ⇒ 各子命令按自己的语义继续）。
BRANCH_PRESENCE_VERDICT = {
    BRANCH_ABSENT: 0,     # 分支都没有 ⇒ 没有属于它的内容：无台账可对账 / 无待批准 run
    BRANCH_UNKNOWN: 3,    # 读不出 ⇒ 无法判定（**未跑 ≠ 通过**）—— 不许降级成 0
}


def branch_presence(branch: str = LEDGER_BRANCH) -> str:
    """台账分支存在性的**唯一读数**（三态）—— `git ls-remote --heads origin <branch>`：

    · 命令退出非零 ⇒ `unknown`（**读不出**：网络 / 权限 / 远端不可达 ⇒ fail-closed）；
    · 输出为空     ⇒ `absent`（**确定**不存在 —— 远端命令正常跑过、它就是没有这一条）；
    · 否则         ⇒ `exists`。

    唯一读数**只此一处**（本仓的反模式是「同一真值两处投影」：`craft-display` 三份副本 #4393）
    ⇒ `git ls-remote` 在本模块里**只允许出现一次**，由类级元守卫
    （`tests/unit_ci_workflows/test_flaky_ledger_branch_presence_consistency.py`）钉住。
    """
    ls = _git("ls-remote", "--heads", "origin", branch)
    if ls.returncode != 0:
        return BRANCH_UNKNOWN
    return BRANCH_EXISTS if ls.stdout.strip() else BRANCH_ABSENT


def read_branch_ledger(branch: str = LEDGER_BRANCH):
    """取**远端台账分支**上的台账。三态，不许把「读不到」当「无漂移」：

    · `dict`  —— 读到了；
    · `None`  —— 分支**不存在**（还没记过账 ⇒ 没有「已记账却未落 main」的内容 ⇒ 非漂移）；
    · 抛 `RuntimeError` —— **无法判定**（网络/权限/文件缺失）⇒ CLI 退 `3`，调用方必须当红读。

    存在性走**唯一读数** `branch_presence()`（#5649）—— 与 `approval-queue` 同源。
    """
    presence = branch_presence(branch)          # **一次**读数：同一次调用里不许读两遍（两遍可打架）
    if presence == BRANCH_UNKNOWN:
        raise RuntimeError(f"git ls-remote 失败（无法判定分支 `{branch}` 是否存在）")
    if presence == BRANCH_ABSENT:
        return None
    fetch = _git("fetch", "--quiet", "origin", branch)
    if fetch.returncode != 0:
        raise RuntimeError(
            f"git fetch origin {branch} 失败：{(fetch.stderr or '').strip()[:200]}")
    show = _git("show", f"FETCH_HEAD:{LEDGER_REL}")
    if show.returncode != 0:
        raise RuntimeError(
            f"读不到 {branch}:{LEDGER_REL}：{(show.stderr or '').strip()[:200]}")
    return json.loads(show.stdout)


def read_main_ledger_live(repo: str, rel: str = LEDGER_REL) -> dict:
    """**实时**读 `main` 上的台账内容（API），而不是 job 启动时的**检出快照**（#5310 判据①）。

    病根（**实测**，不是推断）：`ledger-drift` 的 main 侧旧口径 = `--main-file`（= 工作区
    = **job 启动时的检出快照**），而 PR 侧是**实时** `gh pr list` ⇒ 两个读数跨了两个时刻：
    台账 PR 只要在这个窗口里被合并，就会得到「落后 N 条 + 无 PR」的**假红**。
    实测 run `35951257498`：启动 **03:23:37**、报错 **03:23:55**，而台账 PR #5139 在
    **03:23:46** 合并 ⇒ 它报「**24 条未落仓**」= 分支 72 − **旧快照** main 48，
    而真实 key 差（事后用 `ledger_drift` 复算）= **ahead 0 / behind 0**。

    判据读的都必须是「**现在**」：main 侧改实时读，与本 workflow 里 PR 侧的实时查询同源。
    fail-closed：取不到 / 不是 JSON ⇒ 抛 `RuntimeError`（调用方退 `3`，**不得**当「无漂移」读）。
    """
    proc = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github.raw",
         f"repos/{repo}/contents/{rel}?ref=main"],
        capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(
            f"取不到 main 上的台账（repos/{repo}/contents/{rel}?ref=main）："
            f"{(proc.stderr or '空内容').strip()[:200]}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError(f"main 上的台账不是合法 JSON（实时读，`?ref=main`）：{exc}")


def branch_head_age_minutes():
    """台账分支 HEAD（= 刚 fetch 的 `FETCH_HEAD`）的提交年龄（分钟）；取不到 ⇒ `None`。

    用途：区分「兜底刚发出、check 还在产出（异步窗口）」与「推上去了却久久落不到 main」。
    """
    out = _git("log", "-1", "--format=%ct", "FETCH_HEAD")
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        ct = int(out.stdout.strip())
    except ValueError:
        return None
    return max(0, int((datetime.now(timezone.utc).timestamp() - ct) // 60))


# ── #5687：窗口型疑似的**跟踪单**（机械落单；「必须跟踪」不能靠人记得） ─────────────

TRACKING_LABEL = "flaky/tracking"


def tracking_marker(job: str) -> str:
    """跟踪单的唯一身份标记（HTML 注释，写进 body）。

    ⚠️ **按 job 收敛，不按 run / 日期收敛**：同一 job 反复判 `suspect` ⇒ **复用同一张单**
    （新建单只会造噪音，而噪音正是「随机红 ⇒ 告警疲劳」的起点）；换 job ⇒ 换单。
    ⚠️ 与 PR 评论的 `<!-- flaky-triage:` marker **不同前缀**：两者都是 HTML 注释，
    同前缀会让「找 PR 评论」和「找跟踪单」的机械判据互相误命中。
    """
    return f"<!-- flaky-window-tracking: job={str(job or '').strip()} -->"


def find_tracking_issue(repo: str, job: str):
    """**只读**：找该 job 已存在的 **open** 跟踪单号（没有 ⇒ `None`）。**不创建任何东西**。"""
    marker = tracking_marker(job)
    listing = _gh_api(f"repos/{repo}/issues?state=open&labels={TRACKING_LABEL}&per_page=100")
    for issue in listing if isinstance(listing, list) else []:
        if not isinstance(issue, dict):
            continue
        if marker in str(issue.get("body") or ""):
            number = issue.get("number")
            if isinstance(number, int):
                return number
    return None


def ensure_tracking_issue(repo: str, job: str, *, subject: str = "") -> dict:
    """**保证**该 job 有一张 open 跟踪单；返回 `{"number": int|None, "created": bool, "url": str}`。

    **幂等**：已有 ⇒ 复用（`_gh_api` 只读路径）；没有 ⇒ 新建（`issues` write 权限已在
    `flaky-triage.yml` 的 `permissions:` 里，不新增任何 secret）。

    fail-closed（抛 `RuntimeError`）：拿不到事实 / 建不出来 ⇒ 调用方必须红 —— 否则
    「强制跟踪」会静默退化成「没有跟踪单也照样记一条」（正是 #5307 治过的形态）。
    """
    existing = find_tracking_issue(repo, job)
    if existing is not None:
        return {"number": existing, "created": False,
                "url": f"https://github.com/{repo}/issues/{existing}"}
    marker = tracking_marker(job)
    body = (
        f"{marker}\n"
        f"### 窗口型疑似（`suspect-window-deterministic`）—— 由 CI 机械开单（issue #5687）\n\n"
        f"**job**：`{job}`{f'（workflow {subject}）' if subject else ''}\n\n"
        "**为什么有这张单**：某次失败被自动重跑后**通过**，但**失败时刻与重跑时刻不在同一个"
        "时间桶**（跨了 UTC 日期 / +08 业务日的时段边界）⇒ 「重跑通过」**不再**是「与本次改动"
        "无关」的证据。典型形态 = **窗口型确定性缺陷**（如「UTC 16:00–24:00 必红」）：重跑恰好"
        "落到窗口外就绿，缺陷却仍在 main 上，**明天同一时段对所有人再红一次**。\n\n"
        "⚠️ **本单不是定罪**：跨桶只说明「需人看」，不宣称它是确定性失败"
        "（`deterministic` 要两次尝试**同一断言同一错误**的日志取证）。\n\n"
        "**怎么处置**：\n"
        "1. 拿台账条目里的 `failed_at` / `rerun_at` 与失败 job 日志复算「同一 commit 在失败那段"
        "时刻是否**稳定地红**」（窗口型缺陷的特征 = 每天同一时段必红）；\n"
        "2. 确认窗口型 ⇒ 修根因（冻结时钟 / 注入业务时钟 / 两侧同源取日），修后**必须给红证**"
        "（把机制注回 ⇒ 必红）；\n"
        "3. 确属真 flaky（同桶复算为巧合）⇒ 在台账条目上逐字说明理由，再 "
        "`follow-up --status fixed --fixed-by '<凭据>'` 销账；\n"
        "4. 本单**修好即关**（同一 job 下次再判 `suspect` 会**复用**本单，不会另开新单）。\n\n"
        "**台账**：`.github/flaky-ledger.json`（条目按 `(workflow, run_id, job)` 幂等键定位）。\n"
    )
    # ⚠️ 参数是 **`title=`/`body=`**（`gh api -f` 语义）；`labels` 用 CSV 字符串（同 `gh` CLI 口径）。
    listing = _gh_api(f"repos/{repo}/issues", method="POST", fields={
        "title": f"窗口型疑似：`{job}` 的失败被跨时间桶的重跑掩盖（#5687）",
        "body": body,
        "labels": TRACKING_LABEL,
    })
    number = listing.get("number") if isinstance(listing, dict) else None
    if not isinstance(number, int):
        raise RuntimeError(f"创建跟踪单后取不到 `number`（响应={str(listing)[:200]!r}）⇒ fail-closed")
    return {"number": number, "created": True,
            "url": f"https://github.com/{repo}/issues/{number}"}


def apply_tracking_issue(entries: list, issue) -> list:
    """把跟踪单号**注入** `suspect-window-deterministic` 条目的 `follow_up`（返回被改的条目）。

    幂等：已填同一个号 ⇒ 无改动；已填**别的**号 ⇒ 抛 `FollowUpError`（不猜、不覆盖别人填的值）；
    `issue` 非正整数 ⇒ 抛 `FollowUpError`（本函数**不替它编单号**）。
    """
    if not (isinstance(issue, int) and issue > 0):
        raise FollowUpError(f"--issue 必须是正整数（窗口型疑似必须有跟踪单），实际 {issue!r}")
    changed = []
    for i, entry in enumerate(entries if isinstance(entries, list) else []):
        if not isinstance(entry, dict) or entry.get("kind") != SUSPECT_WINDOW_KIND:
            continue
        before = entry.get("follow_up")
        if isinstance(before, int) and before > 0:
            if before != issue:
                raise FollowUpError(
                    f"entries[{i}]（run_id={entry.get('run_id')} job={entry.get('job')!r}）"
                    f"已填 follow_up={before}，与本次跟踪单 #{issue} 不同 ⇒ 拒绝覆盖"
                    f"（人工填过的值优先；要改请走 `follow-up` 子命令）")
            continue
        entry["follow_up"] = issue
        changed.append({"index": i, "key": list(entry_key(entry)),
                        "before": before, "after": issue})
    return changed


# ── 报告（可见性：结论必须落在 PR / run summary 上，不许只在日志深处） ───────────


def render_comment(decision: dict) -> str:
    """PR 评论：**为什么被停**（哪个 job · 第几次才绿 · 台账条目 id）+ **人工恢复路径**。

    ⚠️ 恢复路径必须是**人工/agent 显式**动作 —— 本机制**绝不自动恢复**（那等于自动放行）。
    ⚠️ #5687：`mark_suspect` 是**第三种动作**，它的评论必须与 `mark_flaky` **长得不一样**
    （否则读的人会把「跨桶的疑似」当成「已经查清是 flaky」= 本单要治的读数与事实不一致）。
    """
    entries = decision.get("entries") or []
    first = entries[0] if entries else {}
    lines = [
        f"<!-- flaky-triage: action={decision.get('action')} "
        f"kind={decision.get('kind')} pr={decision.get('pr')} "
        f"run={first.get('run_id', '')} -->",
        "",
    ]

    def attempt_cell(entry: dict) -> str:
        """把条目的**原始事实**（每次尝试的失败步骤）渲染进表格 —— 结论由读者复核，不靠 `kind` 断言。"""
        facts = entry.get("attempts") or []
        if not facts:
            return entry.get("first_failure_step") or "（runner 级，无步骤失败）"
        return " · ".join(
            f"a{f.get('attempt')}：「{f.get('step') or '（runner 级，无步骤失败）'}」"
            f"{'｜' + str(f.get('assertion')) if f.get('assertion') else ''}"
            for f in facts)

    def table(first_col: str) -> list:
        out = [f"| job | {first_col} | 重跑结果 | 结论 | 台账条目（幂等键） |", "|---|---|---|---|---|"]
        for e in entries:
            out.append(f"| `{e['job']}` | {attempt_cell(e)} | `{e['rerun_result']}` | "
                       f"**`{e['kind']}`** | `{e['workflow']}/{e['run_id']}/{e['job']}` |")
        return out

    why = (f"`{first.get('job')}` 在第 **1** 次尝试（run "
           f"[{first.get('run_id')}]({first.get('run_url')})，失败步骤"
           f"「{first.get('first_failure_step') or '（runner 级）'}」）失败")

    if decision.get("action") == "mark_flaky":
        lines += [
            "## 🎈 Flaky Triage —— **这次是「重跑才绿」，不等于通过**",
            "",
            f"**为什么被停**：{why}，**第 2 次尝试通过** ⇒ 判为 **flaky**（随机波动），"
            "**不是**本次改动把它修好了。",
            "",
            "已按「标注 + 记账」处理：",
            "",
            "- 🏷️ `flaky/rerun-green` —— 可见标注（读作「**重跑才绿**」，不是「通过」）",
            "- 🔒 `block/merge` + **已 `gh pr merge --disable-auto`** —— 第二次绿 ≠ 通过，"
            "auto-merge 已卸下（#4248 实证：光靠 `block/merge` 标签拦不住**已 arm** 的 auto-merge）",
            "- 📒 已追加 `.github/flaky-ledger.json`（只追加 · 幂等 · 可审计）",
            "",
            *table("首次失败步骤"),
            "",
            "**下一步（可行动）**：",
            "",
            f"> {first.get('remedy') or '按 `migao-acceptance` 定位机制并给红证'}",
            "",
            "### 🔧 人工恢复路径（**不是**自动恢复）",
            "",
            "本机制**只标注 + 记账，绝不自动放行、也绝不自动恢复**。要恢复合并，由维护者/agent 显式两步：",
            "",
            "1. **修根因**（首选）：按上面的 `remedy` 定位机制并给出红证（注回机制 ⇒ 必红），"
            "再把台账条目标 `status=fixed` + `fixed_by`；或**确认它确为真 flaky 且与本次改动无关**；",
            "2. **显式放行**：移除 `flaky/rerun-green` 与 `block/merge` 两个标签，再 "
            "`gh pr merge --auto --squash` 重新 arm。",
            "",
            f"判据：{decision.get('reason')}",
        ]
    elif decision.get("action") == "mark_suspect":
        # 🔴 #5687：跨时间桶的「重跑通过」**不是** flaky —— 这一节的存在本身就是判据
        # （旧口径会把这种情形渲染成 flaky 那一段：「重跑才绿」+ 卸 auto-merge）。
        buckets = []
        for e in entries:
            buckets.append(f"| `{e['job']}` | `{e.get('failed_at') or '（取不到）'}` | "
                           f"`{e.get('rerun_at') or '（取不到）'}` | "
                           f"{(e.get('failed_bucket') or {}) and (e.get('failed_bucket') or {}).get('utc_date', '—')}"
                           f" / {(e.get('rerun_bucket') or {}).get('utc_date', '—')} | "
                           f"`{e.get('follow_up')}` |")
        lines += [
            "## 🕒 Flaky Triage —— **跨了时间桶的「重跑通过」**（判 `suspect-window-deterministic`）",
            "",
            f"**为什么不停在「flaky」这个结论上**：{why}，**第 2 次尝试通过**；但"
            "**失败时刻与重跑时刻不在同一个时间桶**（跨了 UTC 日期 / +08 业务日的时段边界）"
            "⇒ 「重跑通过」**不再是**「与本次改动无关」的证据。",
            "",
            "这正是**窗口型确定性缺陷**（如「UTC 16:00–24:00 必红」）被重跑掩盖的路径"
            "（issue #5687）：重跑恰好落到窗口外就绿，而缺陷**仍在 main 上**，"
            "明天同一时段对所有人**再红一次** —— 不设限就**可以无限循环**。",
            "",
            "**本条不是定罪**：跨桶只说明「需人看」，**不**宣称它是确定性失败"
            "（判 `deterministic` 仍要两次尝试**同一断言同一错误**的日志取证）。",
            "",
            *table("尝试 → 失败步骤"),
            "",
            "| job | 首次失败时刻（UTC） | 重跑时刻（UTC） | UTC 日期（失败→重跑） | 跟踪单 |",
            "|---|---|---|---|---|",
            *buckets,
            "",
            "**下一步（可行动）**：",
            "",
            f"> {first.get('remedy') or ''}",
            "",
            f"🔴 本类条目**强制跟踪**：跟踪单 = #{first.get('follow_up')}"
            "（由 `flaky_ledger.py triage-follow-up` 机械落；缺它 ⇒ `selftest`/`append` 判违规）。",
            "",
            "⚠️ **不许**把本次的红当成「已澄清」：`block/merge` 与 auto-merge 的处置见下面两节 —— "
            "本类**不**打 `flaky/rerun-green`（它不是 flaky），但同样**不**自动放行。",
            "",
            f"判据：{decision.get('reason')}",
        ]
    elif decision.get("action") == "record_infra":
        lines += [
            "## 🧰 Flaky Triage —— 重跑绿，但属**基础设施/环境**失败",
            "",
            f"**为什么只记账不打标**：{why}，第 2 次通过；但失败落在"
            "「取代码 · 装依赖 · 配环境」步骤（或 job 从未跑起来）⇒ **环境问题，不是被测对象 flaky**"
            "（把 infra 抖动记成 flaky 会把台账本身变成噪音源）。",
            "",
            *table("首次失败步骤"),
            "",
            f"**下一步（可行动）**：{first.get('remedy') or ''}",
            "",
            "⚠️ 本条**未**卸 auto-merge、**未**打 `flaky/rerun-green`（它不是 flaky）；仅登记台账。",
            "",
            f"判据：{decision.get('reason')}",
        ]
    else:
        lines += [
            "## ❌ Flaky Triage —— 重跑**仍然失败**（两次尝试都红；**不归因**）",
            "",
            f"**为什么照常失败**：{why}，**第 2 次尝试仍然失败**。"
            "已按「照常失败」处理：**不重跑第三次**、**不放行**、**不卸 auto-merge**"
            "（required 检查自己就是红的）。",
            "",
            "⚠️ **「两次都红」不是「确定性失败」**（#5088 实测：把前者读成后者会在 21 条里错 7 条；"
            "同一 SHA 两跑都红也可能是**宽窗口竞态**）。故本条记为 **`unknown`（不归因）**，"
            "并附**两次尝试的原始事实**：",
            "",
            *table("尝试 → 失败步骤"),
            "",
            f"**下一步（可行动）**：{first.get('remedy') or ''}",
            "",
            f"判据：{decision.get('reason')}",
        ]
    lines += ["", "<sub>机制见 `migao` issue #4717（CI 层两项：重跑分流 + flaky 台账）；"
                  "`kind` 的语义收紧见 #5088；判据 `tests/unit_ci_workflows/test_flaky_triage.py` + "
                  "`tests/unit_ci_workflows/test_flaky_ledger_kind_semantics.py`</sub>"]
    return "\n".join(lines) + "\n"


def render_summary(decision: dict) -> str:
    return (f"action=`{decision.get('action')}` kind=`{decision.get('kind')}` "
            f"attempt={decision.get('attempt')} pr={decision.get('pr')} "
            f"entries={len(decision.get('entries') or [])} —— {decision.get('reason')}")


# ── CLI ──────────────────────────────────────────────────────────────────────


def _write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CI 失败重跑分流 + flaky 台账（issue #4717）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch", help="取 run + 本次/上次尝试的 job 事实（只读网络）")
    p.add_argument("--repo", required=True)
    p.add_argument("--run-id", required=True, type=int)
    p.add_argument("--out", required=True)

    p = sub.add_parser("decide", help="纯函数分流判定（不判定 = 不改任何状态）")
    p.add_argument("--bundle", required=True)
    p.add_argument("--entries-out")
    p.add_argument("--comment-out")
    p.add_argument("--gh-output")
    p.add_argument("--json-out")

    p = sub.add_parser("approve", help="批准被 GITHUB_TOKEN 抑制（action_required）的 PR run")
    p.add_argument("--repo", required=True)
    p.add_argument("--head-branch", required=True,
                   help="只看该分支的 pull_request run（台账分支）")
    p.add_argument("--json-out", help="写出被批准的 run id 列表（供复核/审计）")
    p.add_argument("--wait-seconds", type=float, default=0.0,
                   help="#5417：**幂等重试**窗口（秒）。GitHub 创建 run 是异步的 ⇒ 单发一次会"
                        "「暂无待批准 run」而静默退出 0（实测空窗 18 分钟）。>0 ⇒ 轮询到 tip 的"
                        "审批队列清空为止；窗口用尽仍非空 ⇒ **非零退出**（fail-closed）")

    p = sub.add_parser("approval-queue",
                       help="#5417：**只读**读数 —— 停在 `action_required` 的 run 分类清单"
                            "（机制面 / 按设计不批 / 陈旧推送）+ 人工出口命令")
    p.add_argument("--repo", required=True)
    p.add_argument("--head-branch", default=LEDGER_BRANCH)
    p.add_argument("--min-age-minutes", type=float, default=0.0,
                   help="只报「停了 ≥ 该分钟数」的 run（年龄读不出的条目一律保留）")
    p.add_argument("--limit", type=int, default=10, help="每类最多列出多少条（其余只报计数）")
    p.add_argument("--json-out")

    p = sub.add_parser("triage-follow-up",
                       help="#5687：给 `suspect-window-deterministic` 条目**机械落跟踪单**"
                            "（幂等复用 open 单；缺它 ⇒ 该类条目写不进台账）",
                       epilog=FOLLOW_UP_TRACKING_HOWTO,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", required=True)
    p.add_argument("--entries", required=True,
                   help="`decide --entries-out` 写出的条目文件（本命令**原地**补 `follow_up`）")
    p.add_argument("--issue", type=int,
                   help="复用指定跟踪单号（缺省 ⇒ 按 job 找 open 的既有单，没有才新建）")
    p.add_argument("--job", help="条目里多个 job 时只处理它（缺省 ⇒ 处理全部该类条目）")
    p.add_argument("--json-out")
    p.add_argument("--gh-output", help="写出 `issue=<号>` / `created=<0|1>` 供 workflow 引用")

    p = sub.add_parser("ledger-drift",
                       help="台账落仓对账（#4825 兜底判据）：台账分支是否领先 main")
    p.add_argument("--branch", default=LEDGER_BRANCH, help="台账分支名")
    p.add_argument("--main-file", default=str(LEDGER_PATH),
                   help="main 侧台账（**检出快照**；生产请用 `--main-live` —— #5310 判据①）")
    p.add_argument("--main-live", action="store_true",
                   help="#5310：main 侧台账**实时**读（`gh api` 取 main 上该文件），"
                        "而不是 job 启动时的检出快照（判据与 PR 侧查询必须同一时刻）")
    p.add_argument("--repo", help="`--main-live` 需要（`owner/repo`）")
    p.add_argument("--branch-file", help="离线：直接读该文件当分支台账（测试 / 本地复跑）")
    p.add_argument("--json-out")
    p.add_argument("--gh-output")

    p = sub.add_parser("follow-up",
                       help="回填**已存在条目**的 follow_up（跟踪单号）/ status=fixed + fixed_by（#5307）",
                       epilog=FOLLOW_UP_HOWTO,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ledger", default=str(LEDGER_PATH))
    p.add_argument("--run-id", required=True, type=int,
                   help="**已存在条目**的 run_id（不存在 ⇒ 非零退出，绝不静默无操作）")
    p.add_argument("--job", help="同一 run 有多个 job 的条目时用它定位（缺省且命中多条 ⇒ 非零退出）")
    p.add_argument("--issue", help="跟踪单号（必须**正整数**；条目 follow_up 已非空时可省略）")
    p.add_argument("--status", choices=["fixed"], help="可选：同时销账（必须配 `--fixed-by`）")
    p.add_argument("--fixed-by", help="销账凭据（PR / run / 用例），仅 `--status fixed` 需要")

    p = sub.add_parser("attest",
                       help="#5088：回填两次尝试的**断言摘要**（日志取证）并据「同一断言同一错误」"
                            "给结论（deterministic / 仍 unknown）",
                       epilog=ATTEST_HOWTO,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ledger", default=str(LEDGER_PATH))
    p.add_argument("--run-id", required=True, type=int,
                   help="**已存在条目**的 run_id（不存在 ⇒ 非零退出，绝不静默无操作）")
    p.add_argument("--job", help="同一 run 有多个 job 的条目时用它定位（缺省且命中多条 ⇒ 非零退出）")
    p.add_argument("--attempt1-assertion", required=True,
                   help="第一次尝试的失败断言摘要（**逐字**：失败断言 + 错误文本）")
    p.add_argument("--attempt2-assertion", required=True,
                   help="第二次尝试的失败断言摘要（**逐字**）")
    p.add_argument("--evidence", required=True,
                   help="取证凭据（run / attempt / 日志取法）；为空 ⇒ 拒绝（归因必须有凭据）")

    p = sub.add_parser("append", help="只追加 + 幂等地写入台账（`--align-main`：推前先与 main 对齐）")
    p.add_argument("--ledger", default=str(LEDGER_PATH))
    p.add_argument("--entries", required=True)
    p.add_argument("--align-main", action="store_true",
                   help="#5100：推前先与 main 对齐（并集 + 在最新 main 之上重放）；"
                        "需**仓库相对**的 --ledger")
    p.add_argument("--branch", default=LEDGER_BRANCH, help="台账分支名（仅 `--align-main` 用）")
    p.add_argument("--gh-output", help="写出 `lease=<branch>:<sha>`（供 `--force-with-lease` 用）")

    p = sub.add_parser("selftest", help="台账自洽性判据（fail-closed）")
    p.add_argument("--ledger", default=str(LEDGER_PATH))

    p = sub.add_parser("report", help="按 (workflow, job) 聚合（**计数现取**，供后续单消费）")
    p.add_argument("--ledger", default=str(LEDGER_PATH))
    p.add_argument("--json-out")

    p = sub.add_parser("reconcile", help="三态对账：新事件 / 重复计数 / 已修未销账（0/1）")
    p.add_argument("--ledger", default=str(LEDGER_PATH))
    p.add_argument("--branch",
                   help="#5307：改为对账**台账分支**上的台账（那份 CI 不在 required 集合、"
                        "欠账此前没有任何消费面）；读不到分支 ⇒ 退 3（未跑 ≠ 通过）")

    p = sub.add_parser("rerun-failed",
                       help="#5301 判据②：重跑**台账分支**上失败的 job（上限 1 次，如实记账）")
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", default=LEDGER_BRANCH,
                   help="台账分支名 —— **只作用于该分支**（别的分支的 run 一律不重跑）")
    p.add_argument("--json-out", help="写出本轮的重跑 / 额度用尽清单（供审计）")

    args = ap.parse_args(argv)

    if args.cmd == "fetch":
        bundle = fetch_bundle(args.repo, args.run_id)
        _write(args.out, json.dumps(bundle, ensure_ascii=False))
        run = bundle["run"]
        print(f"📥 run {run.get('id')} `{run.get('name')}` attempt={run.get('run_attempt')} "
              f"conclusion={run.get('conclusion')} event={run.get('event')} "
              f"jobs={len(bundle['jobs'])} prior_jobs="
              f"{'—' if bundle['prior_jobs'] is None else len(bundle['prior_jobs'])}")
        return 0

    if args.cmd == "decide":
        bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        decision = decide(bundle)
        print(render_summary(decision))
        if args.json_out:
            _write(args.json_out, json.dumps(decision, ensure_ascii=False, indent=2))
        if args.entries_out:
            _write(args.entries_out, json.dumps(decision.get("entries") or [], ensure_ascii=False))
        if args.comment_out:
            _write(args.comment_out, render_comment(decision))
        if args.gh_output:
            with open(args.gh_output, "a", encoding="utf-8") as fh:
                fh.write(f"action={decision['action']}\n")
                fh.write(f"kind={decision['kind'] or ''}\n")
                fh.write(f"pr={decision['pr'] or ''}\n")
                fh.write(f"entry_count={len(decision.get('entries') or [])}\n")
        return 0

    if args.cmd == "approve":
        # ⚠️ 参数名是 **`branch=`**，不是 `head_branch=`（实测：`head_branch=` 被 API **静默忽略**
        #    ⇒ 返回**全仓** 11867 个 run，而不是本分支的 13 个）。写错的失效形态 = 批准一堆无关 run。
        wait = max(0.0, float(getattr(args, "wait_seconds", 0.0) or 0.0))
        deadline = _monotonic() + wait
        attempted: list = []
        tip = None
        round_no = 0
        while True:
            round_no += 1
            all_runs = (_gh_api(f"repos/{args.repo}/actions/runs"
                                f"?event=pull_request&branch={args.head_branch}&per_page=100")
                        .get("workflow_runs") or [])
            needing = set(runs_needing_approval(all_runs, workflows=TRIAGED_WORKFLOWS))
            if not needing and not attempted and not wait:
                # 快速路径（**只在没给窗口时**）：候选为空 ⇒ **不查 tip**（少一次 API 调用，
                # 且与既有读数逐字一致）。⚠️ 给了窗口就**不许**走这里：候选为空正是
                # 「GitHub 还没创建这批 run」的实测形态（#5417），此时退出 0 = 静默 0 动作。
                print("✅ 无 `action_required` 的 pull_request run（无需 approve —— 可能已批准或已被正常触发）")
                if args.json_out:
                    _write(args.json_out, json.dumps([], ensure_ascii=False))
                return 0
            # #5264：候选**非空** ⇒ 只批准**分支 tip 那一次推送**的 run（收窄理由见 `runs_for_head`）。
            # ⚠️ tip 必须从**分支事实**取：本步骤在 push 台账分支之后**立刻**执行，而 GitHub 创建 run 是
            #    **异步**的 ⇒ 「此刻可见的最新 run」可能还是**上一次**推送的。拿它当 tip = 批准**陈旧 SHA**
            #    却把日志说成「批准了本次推送」（读数与事实不一致）⇒ 故意**不**做这个退回：
            #    解析不到 tip 就 fail-closed（非零退出，workflow 侧会 `::error::` 显性化）。
            candidates = [r for r in all_runs
                          if r.get("id") in needing and r.get("id") not in attempted]
            if tip is None:
                tip = branch_tip(_gh_api(f"repos/{args.repo}/branches/{args.head_branch}"))
                if not tip:
                    print(f"⛔ 无法确定台账分支 `{args.head_branch}` 的 tip（`GET /repos/{{repo}}/branches/…` "
                          f"取不到 `commit.sha`）⇒ 不敢用「最新可见推送」代替 —— 那会把**陈旧 SHA** 的 run "
                          f"批准起来、并把读数说成「批准了本次推送」。**本轮零动作、fail-closed**"
                          f"（历史待批准 {len(needing)} 个一个不批；下一轮触发会重试）。", file=sys.stderr)
                    return 1
            pending = sorted(runs_for_head(candidates, tip), key=lambda r: r["id"])
            if pending:
                ids = [r["id"] for r in pending]
                print(f"🔓 历史待批准 {len(needing)} 个，其中属于分支 tip={tip} 的 {len(ids)} 个"
                      f" ⇒ 只批准这 {len(ids)} 个（被 GITHUB_TOKEN 抑制 ⇒ 无 job ⇒ 无 check）：{ids}")
                # #5417 判据 2：读数必须**可行动** —— 每条带 run 链接（人工出口见日志尾）。
                for run in pending:
                    print(f"   · run {run['id']}  {run.get('name')}  → {run_url(args.repo, run['id'])}")
                try:
                    approve_runs(args.repo, ids)
                except RuntimeError as exc:
                    print(f"⛔ approve 失败 ⇒ 台账 PR 仍无 check、`--auto` 仍不会触发（**不许静默**）：{exc}",
                          file=sys.stderr)
                    return 1
                attempted += ids
                print(f"✅ 已 approve {len(ids)} 个 run —— 它们将真正执行并产出 check-runs")
            elif not attempted and round_no == 1:
                # 诚实读数：tip 上确实没有待批准 run（GitHub 尚未创建、或已批准）。
                # **不许**在此时改去批准陈旧 SHA（见上）—— 它们对 required 判定零贡献。
                print(f"ℹ️ tip={tip} 暂无待批准 run（尚未创建或已批准）⇒ 本轮零动作，下一轮触发会重试"
                      f"（历史待批准 {len(needing)} 个均为**陈旧推送**，批准它们对 required 判定无贡献）")
            if _monotonic() >= deadline:
                break
            time.sleep(min(APPROVE_POLL_SECONDS, max(0.05, deadline - _monotonic())))
        if not wait:
            if args.json_out:
                _write(args.json_out, json.dumps(attempted, ensure_ascii=False))
            return 0
        # 终态复核（#5417）：窗口用尽 ⇒ tip 的审批队列**必须已清空**
        # （队列非空 = 那些 run 仍在 `action_required` ⇒ 它们永远不产出 check-run ⇒ required 不满足）。
        # ⚠️ 只有**给了窗口**才做这一步：窗口内的残余属「批准尚未生效」的异步，不是失败。
        # ⚠️ 判据必须**按 dict 过滤后再取 id**：`runs_needing_approval` 返回的是 **id**，
        #    直接喂给 `runs_for_head`（按 dict 的 `head_sha` 过滤）会恒得空集 ⇒ 这条 fail-closed
        #    变成**空断言**（本单的红证 `test_window_exhausted_is_fail_closed` 就是钉这个）。
        all_runs = (_gh_api(f"repos/{args.repo}/actions/runs"
                            f"?event=pull_request&branch={args.head_branch}&per_page=100")
                    .get("workflow_runs") or [])
        still_queued = set(runs_needing_approval(all_runs, workflows=TRIAGED_WORKFLOWS))
        leftover = sorted(r["id"] for r in runs_for_head(
            [r for r in all_runs if isinstance(r, dict) and r.get("id") in still_queued], tip))
        if leftover:
            print(f"⛔ 窗口 {wait:.0f}s 用尽，分支 tip={tip} 仍有 {len(leftover)} 个 run 停在 "
                  f"`action_required`（无 job ⇒ 无 check-run ⇒ 台账 PR 拿不到 required 的 check）："
                  f"{leftover}", file=sys.stderr)
            for rid in leftover:
                print(f"   · run {rid} → {run_url(args.repo, rid)}"
                      f"（人工出口：gh api -X POST repos/{args.repo}/actions/runs/{rid}/approve）",
                      file=sys.stderr)
            return 1
        print(f"✅ 窗口 {wait:.0f}s 内 tip={tip} 的审批队列已清空（本轮共 approve {len(attempted)} 个）")
        if args.json_out:
            _write(args.json_out, json.dumps(attempted, ensure_ascii=False))
        return 0

    if args.cmd == "approval-queue":
        # #5417 判据 1：**停在 action_required 的 run 必须留下可归因读数**（不许静默）。
        # 只读：本子命令**不发任何 approve**，也不碰 PR / 分支（读数不改变任何状态）。
        # ── #5649：口径统一（本子命令此前对「分支不存在」判 3，而 `reconcile` 判 0） ──────
        # 分支存在性走**唯一读数** `branch_presence()`、判定走**唯一口径表**
        # `BRANCH_PRESENCE_VERDICT`（与 `reconcile --branch` 同源）：
        #   · `absent`（**确定**不存在）⇒ 分支都没有 ⇒ **没有属于它的待批准 run** ⇒ 退 0，
        #     并打一句**可读 notice**（不许静默）：与 reconcile 的「没有可对账的台账」同判；
        #   · `unknown`（`git ls-remote` 真失败）⇒ **照旧退 3**（未跑 ≠ 通过）。
        # 注意**不是**「把无法判定放宽成通过」：放宽的只有「分支**确定**不存在」这一条。
        presence = branch_presence(args.head_branch)
        verdict = BRANCH_PRESENCE_VERDICT.get(presence)
        if verdict == 0:
            print(f"::notice::台账分支 `{args.head_branch}` 不存在 ⇒ 无待批准 run"
                  f"（与 reconcile 同口径：#5649）—— 这是**确定无内容**，不是「未跑」")
            if args.json_out:
                _write(args.json_out, json.dumps(
                    {"state": presence, "head_branch": args.head_branch, "tip": None,
                     "in_scope": [], "out_of_scope": [], "in_scope_total": 0,
                     "out_of_scope_total": 0, "stale": 0, "unaged": 0}, ensure_ascii=False))
            return 0
        if verdict is not None:
            print(f"⛔ 读不出台账分支 `{args.head_branch}` 的存在性（`git ls-remote` 失败）⇒ "
                  f"**无法判定**（不得当「没有待批准 run」读；未跑 ≠ 通过）", file=sys.stderr)
            return verdict
        try:
            all_runs = (_gh_api(f"repos/{args.repo}/actions/runs"
                                f"?event=pull_request&branch={args.head_branch}&per_page=100")
                        .get("workflow_runs") or [])
            tip = branch_tip(_gh_api(f"repos/{args.repo}/branches/{args.head_branch}"))
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            print(f"⛔ 取不到 run 列表 / 分支 tip（{exc}）⇒ **未跑 ≠ 通过**（不得当「队列为空」读）",
                  file=sys.stderr)
            return 3
        if not tip:
            print(f"⛔ 取不到台账分支 `{args.head_branch}` 的 tip ⇒ **无法判定**（不得当「没有待批准 run」读）",
                  file=sys.stderr)
            return 3
        reading = approval_queue_reading(
            all_runs, repo=args.repo, head_sha=tip,
            min_age_minutes=args.min_age_minutes, limit=max(1, args.limit))
        in_scope, out_scope = reading["in_scope"], reading["out_of_scope"]
        head = (f"#5417 审批队列读数：tip={tip}（{args.head_branch}）"
                f" · 机制面待批准 {reading['in_scope_total']} 个"
                f" · 白名单外（按设计不批）{reading['out_of_scope_total']} 个"
                f" · 陈旧推送 {reading['stale']} 个 · 年龄读不出 {reading['unaged']} 个")
        if in_scope:
            print(f"::warning::{head} —— 机制面仍有 run 停在 `action_required` ≥"
                  f"{args.min_age_minutes:.0f} 分钟 ⇒ 台账 PR 拿不到 required 的 check（必须处置）")
        else:
            print(f"::notice::{head} —— 机制面无待批准 run（台账 PR 的 check 已产出）")
        for label, entries, total in (("机制面", in_scope, reading["in_scope_total"]),
                                      ("白名单外（机制故意不批；非 required）", out_scope,
                                       reading["out_of_scope_total"])):
            for entry in entries:
                age = "年龄未知" if entry["age_minutes"] is None else f"{entry['age_minutes']} 分钟"
                print(f"   · [{label}] run {entry['id']}  {entry['name']}  {age}  → {entry['url']}")
            if total > len(entries):
                print(f"   · [{label}] …另有 {total - len(entries)} 个（清单按 --limit 截断）")
        if in_scope or out_scope:
            print("::notice::人工出口（唯一入口；机制不自动批白名单外的 run）："
                  "gh api -X POST repos/<owner>/<repo>/actions/runs/<run_id>/approve")
        if args.json_out:
            _write(args.json_out, json.dumps(reading, ensure_ascii=False))
            return 0
        return 0

    if args.cmd == "triage-follow-up":
        # 🔴 #5687：`suspect-window-deterministic` **强制跟踪**的机械落点。
        # 为什么必须在**这里**（而不是「让分诊方记得手动回填」）：`ledger_violations` 把
        # 「该类条目缺 follow_up」判成**违规** ⇒ 没有本命令时 `append` 会在第一步就 fail-closed
        # ⇒ 分流整条链死给你看 —— 正是 #5307 治过的「文档要求做、却没有合法工具做」。
        try:
            entries = json.loads(Path(args.entries).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"⛔ 读不到/解析不了条目文件 {args.entries}（{exc}）⇒ **不得**当「没有该类条目」"
                  f"继续（未跑 ≠ 通过）", file=sys.stderr)
            return 1
        if not isinstance(entries, list):
            print(f"⛔ 条目文件 {args.entries} 不是列表（形状应为 decide --entries-out 的输出）"
                  f"⇒ 拒绝继续", file=sys.stderr)
            return 1
        targets = [e for e in entries
                   if isinstance(e, dict) and e.get("kind") == SUSPECT_WINDOW_KIND
                   and (args.job is None or e.get("job") == args.job)]
        if not targets:
            print(f"ℹ️ 条目里没有 `{SUSPECT_WINDOW_KIND}` 类"
                  f"{f'（--job {args.job!r}）' if args.job else ''} ⇒ 本命令零动作"
                  f"（不建单、不写文件）")
            if args.gh_output:
                with open(args.gh_output, "a", encoding="utf-8") as fh:
                    fh.write("issue=\ncreated=0\n")
            return 0
        # 一张单服务本条 job 的全部条目（同 run 多 job ⇒ 各自一张，靠 `--job` 分派）
        job = str(targets[0].get("job") or "")
        subject = str(targets[0].get("workflow") or "")
        try:
            if args.issue is not None:
                if not (isinstance(args.issue, int) and args.issue > 0):
                    raise FollowUpError(f"--issue 必须是正整数，实际 {args.issue!r}")
                info = {"number": args.issue, "created": False,
                        "url": f"https://github.com/{args.repo}/issues/{args.issue}"}
            else:
                info = ensure_tracking_issue(args.repo, job, subject=subject)
        except (RuntimeError, FollowUpError) as exc:
            print(f"⛔ 落跟踪单失败（{exc}）⇒ **fail-closed**：该类条目必须带跟踪单，"
                  f"不许「没有单也照样记账」", file=sys.stderr)
            return 1
        try:
            changed = apply_tracking_issue(entries, info["number"])
        except FollowUpError as exc:
            print(f"⛔ {exc}", file=sys.stderr)
            return 1
        Path(args.entries).write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        verb = "新建" if info["created"] else "复用"
        print(f"::notice::🕒 {verb}窗口型疑似的跟踪单 #{info['number']}（job `{job}`）"
              f"→ {info['url']}；已注入 {len(changed)} 条条目的 follow_up")
        if args.json_out:
            _write(args.json_out, json.dumps(
                {"issue": info["number"], "created": info["created"], "job": job,
                 "changed": changed, "url": info["url"]}, ensure_ascii=False, indent=2))
        if args.gh_output:
            with open(args.gh_output, "a", encoding="utf-8") as fh:
                fh.write(f"issue={info['number']}\n")
                fh.write(f"created={1 if info['created'] else 0}\n")
        return 0

    if args.cmd == "ledger-drift":
        age = None
        if args.main_live and not args.repo:
            print("⛔ `--main-live` 必须同时给 `--repo owner/repo`（否则无从实时读 main）"
                  "⇒ 参数非法，本轮**零动作**（未跑 ≠ 通过）", file=sys.stderr)
            return 1
        try:
            if args.main_live:
                # #5310 判据①：判据（main 侧）与本 workflow 里 PR 侧的**实时**查询同一时刻。
                main_ledger = read_main_ledger_live(args.repo)
                main_source = f"live:{args.repo}@main"
            else:
                main_ledger = load_ledger(Path(args.main_file))
                main_source = f"snapshot:{args.main_file}"
            if args.branch_file:
                branch_ledger = load_ledger(Path(args.branch_file))
            else:
                branch_ledger = read_branch_ledger(args.branch)
                if branch_ledger is not None:
                    age = branch_head_age_minutes()
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"⛔ 无法判定台账漂移（{exc}）⇒ **不得**当「无漂移」读（未跑 ≠ 通过）",
                  file=sys.stderr)
            return 3
        if branch_ledger is None:
            # 分支不存在 ⇒ 没有「已记账却未落 main」的内容。**不**把它读成「main 有而分支没有」
            # （那会凭空报一堆分叉），故显式给零漂移。
            drift = {"ahead": [], "behind": [],
                     "main_total": len(ledger_keys(main_ledger)), "branch_total": 0}
            state = "no-branch"
        else:
            drift = ledger_drift(main_ledger, branch_ledger)
            state = "drift" if drift["ahead"] else "in-sync"
        drift["state"] = state
        drift["age_minutes"] = age
        drift["main_source"] = main_source
        print(f"📒 台账对账（{args.branch}）：main {drift['main_total']} 条 · "
              f"分支 {drift['branch_total']} 条 ⇒ **领先 main {len(drift['ahead'])} 条** / "
              f"落后 {len(drift['behind'])} 条"
              f"（分支 HEAD {age if age is not None else '—'} 分钟前；状态 {state}；"
              f"main 侧 = {main_source}）")
        for key in drift["ahead"]:
            print(f"   ⏳ 已记账但未落 main：{key}")
        for key in drift["behind"]:
            print(f"   ⚠️ main 有而分支没有（台账**只追加** ⇒ 这是分叉）：{key}")
        if args.json_out:
            _write(args.json_out, json.dumps(drift, ensure_ascii=False, indent=2))
        if args.gh_output:
            with open(args.gh_output, "a", encoding="utf-8") as fh:
                fh.write(f"drift={1 if drift['ahead'] else 0}\n")
                fh.write(f"ahead={len(drift['ahead'])}\n")
                fh.write(f"behind={len(drift['behind'])}\n")
                fh.write(f"state={state}\n")
                fh.write(f"age_minutes={age if age is not None else ''}\n")
                fh.write(f"main_source={main_source}\n")
        return 0

    if args.cmd == "append":
        lease = ""
        if args.align_main:
            # #5100：**推前先与 main 对齐**（并集 + 最新 main 之上重放）。失败 ⇒ 拒绝在旧基线上追加。
            try:
                info = align_with_main(args.ledger, args.branch)
            except RuntimeError as exc:
                print(f"⛔ 推前对齐失败（{exc}）⇒ **拒绝在旧基线上追加**（fail-closed，不静默）",
                      file=sys.stderr)
                return 1
            lease = info["lease"]
            print(f"🧭 推前已与 main 对齐：main {info['main_total']} 条 · "
                  f"分支 {info['branch_total']} 条 ⇒ 并集 {info['merged_total']} 条"
                  f"（基线 = origin/main；lease={'有' if lease else '无（分支尚不存在）'}）")
        if args.gh_output:
            # lease 期望值必须**在推送前**交给调用方（它决定 `--force-with-lease=<ref>:<sha>`）；
            # 没走对齐时为空串（= 分支还不存在 ⇒ 调用方用普通推送）。
            with open(args.gh_output, "a", encoding="utf-8") as fh:
                fh.write(f"lease={lease}\n")
        ledger = load_ledger(args.ledger)
        entries = json.loads(Path(args.entries).read_text(encoding="utf-8"))
        bad = ledger_violations(ledger)
        if bad:
            print("⛔ 台账自身不合规，拒绝写入：\n  - " + "\n  - ".join(bad), file=sys.stderr)
            return 1
        added, skipped = append_entries(ledger, entries)
        if not added:
            print(f"⏭️ 幂等：{len(skipped)} 条已登记（键={'/'.join(map(str, skipped[0])) if skipped else '—'}）"
                  " ⇒ 台账未改动")
            return 0
        save_ledger(args.ledger, ledger)
        print(f"📒 台账追加 {len(added)} 条"
              f"（幂等跳过 {len(skipped)} 条）→ {args.ledger}")
        return 0

    if args.cmd == "follow-up":
        # #5307：**回填路径**（此前不存在 ⇒ 台账自我死锁）。全部 fail-closed：任一项不成立
        # ⇒ 非零退出 + 明确报错，**绝不**静默无操作（静默无操作正是本单要治的形态）。
        try:
            run_id = _positive_int(args.run_id, "--run-id")
            issue = None if args.issue is None else _positive_int(args.issue, "--issue")
        except ValueError as exc:
            print(f"⛔ {exc} ⇒ 拒绝回填（fail-closed：非零退出，不静默无操作）", file=sys.stderr)
            return 1
        ledger = load_ledger(args.ledger)
        bad = ledger_violations(ledger)
        if bad:
            print("⛔ 台账自身不合规，拒绝回填（先 `selftest`）：\n  - " + "\n  - ".join(bad),
                  file=sys.stderr)
            return 1
        try:
            indices = follow_up_index(ledger, run_id, args.job)
            result = apply_follow_up(ledger, indices, issue=issue, status=args.status,
                                     fixed_by=args.fixed_by)
        except FollowUpError as exc:
            print(f"⛔ {exc}", file=sys.stderr)
            print(f"   （回填口径：{FOLLOW_UP_HOWTO}）", file=sys.stderr)
            return 1
        if result["idempotent"]:
            print(f"⏭️ 幂等：run {run_id} 的 {len(indices)} 条已是目标值 ⇒ 台账未改动"
                  f"（重复回填 = 无副作用）")
            return 0
        bad_after = ledger_violations(ledger)
        if bad_after:
            print("⛔ 回填会把台账改成不合规 ⇒ 拒绝写入：\n  - " + "\n  - ".join(bad_after),
                  file=sys.stderr)
            return 1
        save_ledger(args.ledger, ledger)
        for change in result["changed"]:
            diffs = " · ".join(
                f"{field} {change['before'][field]!r} → {change['after'][field]!r}"
                for field in ("follow_up", "status", "fixed_by")
                if change["before"][field] != change["after"][field])
            print(f"📒 entries[{change['index']}] {_key_str(change['key'])}：{diffs}")
        left = reconcile(ledger)
        print(f"✅ 已回填 {len(result['changed'])} 条（条目数现取 = {len(ledger.get('entries') or [])}，"
              f"**只改字段、未新增/删除/重排条目**）→ {args.ledger}")
        print(f"   回填后 reconcile：new_events={len(left['new_events'])} "
              f"duplicates={len(left['duplicates'])} "
              f"fixed_not_deducted={len(left['fixed_not_deducted'])}")
        return 0

    if args.cmd == "attest":
        # #5088：把**日志取证**得到的断言级事实回填进已存在条目 —— 「归因必须有凭据」的落地点。
        # 全部 fail-closed：任一不成立 ⇒ 非零退出 + 明确报错（静默无操作正是本单要治的形态）。
        try:
            run_id = _positive_int(args.run_id, "--run-id")
        except ValueError as exc:
            print(f"⛔ {exc} ⇒ 拒绝回填（fail-closed：非零退出，不静默无操作）", file=sys.stderr)
            return 1
        a1 = str(args.attempt1_assertion or "").strip()
        a2 = str(args.attempt2_assertion or "").strip()
        ev = str(args.evidence or "").strip()
        if not a1 or not a2 or not ev:
            print("⛔ `--attempt1-assertion` / `--attempt2-assertion` / `--evidence` 必须都非空 "
                  "⇒ 拒绝回填（凭据为空 = 无凭据的归因，比不归因更坏）", file=sys.stderr)
            return 1
        ledger = load_ledger(args.ledger)
        bad = ledger_violations(ledger)
        if bad:
            print("⛔ 台账自身不合规，拒绝回填（先 `selftest`）：\n  - " + "\n  - ".join(bad),
                  file=sys.stderr)
            return 1
        try:
            indices = follow_up_index(ledger, run_id, args.job)
            result = apply_attestation(ledger, indices, attempt1_assertion=a1,
                                       attempt2_assertion=a2, evidence=ev)
        except (FollowUpError, AttestError) as exc:
            print(f"⛔ {exc}", file=sys.stderr)
            print(f"   （取证与回填口径：{ATTEST_HOWTO}）", file=sys.stderr)
            return 1
        if result["idempotent"]:
            print(f"⏭️ 幂等：run {run_id} 的 {len(indices)} 条已是目标值 ⇒ 台账未改动"
                  f"（重复回填 = 无副作用）")
            return 0
        bad_after = ledger_violations(ledger)
        if bad_after:
            print("⛔ 回填会把台账改成不合规 ⇒ 拒绝写入：\n  - " + "\n  - ".join(bad_after),
                  file=sys.stderr)
            return 1
        save_ledger(args.ledger, ledger)
        for change in result["changed"]:
            print(f"📒 entries[{change['index']}] {_key_str(change['key'])}："
                  f"kind {change['before']['kind']!r} → {change['after']['kind']!r}"
                  f"（断言级事实已逐字回填；凭据={change['after']['attested_evidence']!r}）")
        print(f"✅ 已回填 {len(result['changed'])} 条的断言级事实（条目数现取 = "
              f"{len(ledger.get('entries') or [])}，**只改字段、未新增/删除/重排条目**）"
              f"→ {args.ledger}")
        return 0

    if args.cmd == "selftest":
        ledger = load_ledger(args.ledger)
        bad = ledger_violations(ledger)
        if bad:
            print("⛔ 台账不合规：\n  - " + "\n  - ".join(bad), file=sys.stderr)
            return 1
        print(f"✅ 台账自洽（条目数现取 = {len(ledger.get('entries') or [])}）")
        return 0

    if args.cmd == "report":
        ledger = load_ledger(args.ledger)
        groups = aggregate(ledger)
        rows = sorted(groups.values(),
                      key=lambda r: (-r["flaky"], -r["total"], r["job"] or ""))
        print(f"📊 flaky 台账聚合（条目数现取 = {len(ledger.get('entries') or [])}，"
              f"不同 (workflow, job) = {len(rows)}）")
        for row in rows:
            print(f"  · {row['workflow']} :: {row['job']} —— flaky={row['flaky']} "
                  f"deterministic={row['deterministic']} infra_suspect={row['infra_suspect']} "
                  f"**unknown={row['unknown']}**（不归因）· 旧口径 confirmed_failure="
                  f"{row['confirmed_failure']} · 可归因小计 attributed={row['attributed']} "
                  f"· 合计={row['total']}"
                  f"（最近 run {row['last_run_id']} @ {row['last_observed_at']}）")
        print("⚠️ 本命令**不设阈值**（不写死计数）：「同一 job 反复 flaky ⇒ 必须修根因」的"
              "判定留给消费方，按 `migao-acceptance`「随机红 = 归因层失效」开单。")
        print("⚠️ `unknown` 是**未归因**（两次都红但事实不足以判）—— **不得**并入 flaky / "
              "deterministic / confirmed_failure 任何一列做归因（#5088）；要归因先 "
              "`attest` 回填两次尝试的断言摘要。")
        if args.json_out:
            _write(args.json_out, json.dumps(
                {"entry_total": len(ledger.get("entries") or []), "groups": rows},
                ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "rerun-failed":
        # #5301 判据②：台账分支的失败 job 此前**没有任何自动重跑路径**（`decide()` 的自指守卫让
        # `flaky-triage.yml` **结构上**跳过该分支；本兜底原先只补 approve/arm）⇒ 台账 PR 撞一次
        # 确定性失败就只能人工救（实测停摆约 40 小时）。本命令把它落成**有上限的机械动作**。
        if args.branch != LEDGER_BRANCH:
            # 作用域收敛（判据④）：本命令**只**救台账分支 —— 放宽一次就可能变成「兜底替全仓重跑
            # CI」。参数非法 ⇒ 退 1（不是「无法判定」）。
            print(f"⛔ `--branch {args.branch}` 不是台账分支（{LEDGER_BRANCH}）⇒ **拒绝重跑**"
                  f"（作用域：本命令只作用于台账分支）", file=sys.stderr)
            return 1
        try:
            listing = _gh_api(f"repos/{args.repo}/actions/runs"
                              f"?event=pull_request&branch={args.branch}&per_page=100")
            tip = branch_tip(_gh_api(f"repos/{args.repo}/branches/{args.branch}"))
        except (subprocess.CalledProcessError, ValueError) as exc:
            print(f"⛔ 取不到台账分支 `{args.branch}` 的 run / tip 事实（{exc}）⇒ **无法判定**"
                  f"（未跑 ≠ 通过），本轮零动作、fail-closed", file=sys.stderr)
            return 3
        if not tip:
            # 与 `approve` 同一条纪律：**不**用「此刻最新可见的 run」代替 tip（GitHub 创建 run 是
            # 异步的）—— 陈旧 push 的 run 重跑对「PR 能否合并」零贡献，却真烧 CI 分钟。
            print(f"⛔ 无法确定台账分支 `{args.branch}` 的 tip（取不到 `commit.sha`）⇒ 不敢用"
                  f"「最新可见的推送」代替 ⇒ 本轮零动作、fail-closed（退 3）", file=sys.stderr)
            return 3
        plan = runs_needing_rerun(listing.get("workflow_runs") or [], head_branch=args.branch,
                                  workflows=TRIAGED_WORKFLOWS, head_sha=tip)
        print(f"📒 台账失败 job 兜底重跑（{args.branch} tip={tip[:12]}）：候选 {len(plan['rerun'])} 个 / "
              f"额度已用尽 {len(plan['exhausted'])} 个 / 面外 {plan['out_of_scope']} 个"
              f"（上限 {MAX_LEDGER_RERUNS} 次，绝不无限重跑）")
        done = []
        for entry in plan["rerun"]:
            try:
                jobs = (_gh_api(f"repos/{args.repo}/actions/runs/{entry['id']}/jobs")
                        .get("jobs") or [])
            except (subprocess.CalledProcessError, ValueError) as exc:
                print(f"⛔ 取不到 run {entry['id']} 的 job 事实（{exc}）⇒ **不重跑它**"
                      f"（「到底有没有失败 job」不许靠猜）⇒ 退 3", file=sys.stderr)
                return 3
            failed = [str(job.get("name")) for job in jobs if is_failed(job)]
            if not failed:
                # 与 `decide()` 同口径：conclusion=failure 但**没有任何失败 job**（workflow 级失败）
                # ⇒ `gh run rerun --failed` 无 job 可重跑。
                print(f"⏭️ run {entry['id']}（{entry['name']}）conclusion=failure 但**没有任何失败 job**"
                      f"（workflow 级失败）⇒ 无 job 可重跑")
                continue
            try:
                rerun_failed_run(args.repo, entry["id"])
            except RuntimeError as exc:
                print(f"⛔ {exc} ⇒ 台账分支的失败 job 仍**无人救**（fail-closed，不静默）", file=sys.stderr)
                return 1
            after = run_attempt_after_rerun(args.repo, entry["id"])
            before = entry["attempt"]
            if after is None:
                readback = "unknown"
                print(f"::warning::run {entry['id']} 已发出重跑，但**回读**不到 run_attempt ⇒ 读数缺失"
                      f"（不假装成功；下一轮由 `run_attempt` 事实复核：≥{before + 1} = 已重跑过）")
            elif after > before:
                readback = "advanced"
                print(f"::notice::🔁 run {entry['id']}（{entry['name']} · {args.branch}）已重跑失败 job "
                      f"{failed}：attempt {before} → {after}（上限 {MAX_LEDGER_RERUNS} 次，"
                      f"**绝不无限重跑**）")
            else:
                readback = "pending"
                print(f"::notice::🔁 run {entry['id']} 重跑已发出，回读 attempt={after}（尚未推进 = "
                      f"GitHub 的异步窗口）⇒ 下一轮按 `run_attempt` 复核，**不会**重复重跑")
            done.append({**entry, "failed_jobs": failed, "attempt_after": after, "readback": readback})
        for entry in plan["exhausted"]:
            print(f"❌ run {entry['id']}（{entry['name']}）attempt={entry['attempt']} —— **已重跑过**"
                  f"（上限 {MAX_LEDGER_RERUNS} 次）仍失败 ⇒ 确定性失败，**不再自动重跑**")
        if args.json_out:
            _write(args.json_out, json.dumps(
                {"branch": args.branch, "tip": tip, "max_reruns": MAX_LEDGER_RERUNS,
                 "rerun": done, "exhausted": plan["exhausted"],
                 "out_of_scope": plan["out_of_scope"]}, ensure_ascii=False, indent=2))
        if plan["exhausted"]:
            # 额度用尽必须**可见**（红）且**可行动** —— 静默降级正是本单要治的形态。
            print(f"::error::台账分支的失败 run 已达重跑上限（{MAX_LEDGER_RERUNS} 次）仍失败 ⇒ "
                  f"**本兜底不再自动重跑**（绝不无限重跑）。**人工出口**：① 先按「台账欠账可见性」"
                  f"步骤的清单回填 `follow-up` 跟踪单，修好后由 `flaky-triage.yml` 的下一轮追加推送"
                  f"带来**新的 run**（新 run 的 attempt=1 ⇒ 额度自然重置）；② 确需再跑一次时**由人**"
                  f"执行 `gh run rerun <run-id> --failed`（人工动作，本兜底不做）。")
            return 1
        print(f"✅ 兜底重跑完成：本轮重跑 {len(done)} 个（上限 {MAX_LEDGER_RERUNS} 次）· "
              f"额度已用尽 {len(plan['exhausted'])} 个 · 结果由下一次触发按 `run_attempt` 复核")
        return 0

    if args.cmd == "reconcile":
        if args.branch:
            # #5307 可见性：对账**台账分支**上那份台账 —— 它的 required 测试判红**没有任何人看**
            # （不在 required 集合 + flaky-triage 按自指守卫跳过该分支 + 兜底原先只补 approve/arm）。
            try:
                ledger = read_branch_ledger(args.branch)
            except (RuntimeError, ValueError) as exc:
                # #5649：退出码从**唯一口径表**取（与 `approval-queue` 同一张表 ⇒ 两边不可能两套读数）
                print(f"⛔ 读不到台账分支 `{args.branch}` 的台账（{exc}）⇒ **无法判定**"
                      f"（未跑 ≠ 通过 ⇒ 退 {BRANCH_PRESENCE_VERDICT[BRANCH_UNKNOWN]}）",
                      file=sys.stderr)
                return BRANCH_PRESENCE_VERDICT[BRANCH_UNKNOWN]
            if ledger is None:
                # `read_branch_ledger` 返回 `None` ⇔ **唯一读数**已判「**确定**不存在」
                # ⇒ 查同一张口径表（不是这里另写一个 `return 0`）。
                print(f"ℹ️ 台账分支 `{args.branch}` 不存在 ⇒ 没有可对账的台账（非欠账）")
                return BRANCH_PRESENCE_VERDICT[BRANCH_ABSENT]
        else:
            ledger = load_ledger(args.ledger)
        bad = ledger_violations(ledger)
        if bad:
            print("⛔ 台账不合规（先 `selftest`）：\n  - " + "\n  - ".join(bad), file=sys.stderr)
            return 1
        result = reconcile(ledger)
        dirty = 0
        for name, rows in result.items():
            if not rows:
                continue
            dirty += len(rows)
            print(f"❌ {name} = {len(rows)}")
            for row in rows:
                print(f"   - {row['key']}：{row['why']}")
        if dirty == 0:
            print("✅ 三态对账干净（无未登记修复路径 / 无重复计数 / 无已修未销账）")
            return 0
        # #5307 判据②：欠账必须**可行动** —— 清单（workflow / run_id / job）+ 可直接复制的回填命令。
        print(render_reconcile_report(ledger, result))
        print("⚠️ 本命令**未接 required 门禁**（照实登记）：它是**消费接口**，"
              "由后续单 / agent 按需调用 —— 判红不等于阻塞合并。")
        return 1

    return 3


if __name__ == "__main__":
    sys.exit(main())
