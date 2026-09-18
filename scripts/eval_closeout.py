#!/usr/bin/env python3
"""eval_closeout — 判定档「跑后收口核对」固化（issue #4258）。

## 病根

对 6~7 个 run 做收口核对时**反复手写同一套逻辑**（`/tmp/verify-eval-batch.sh`，
run `35256153429` / `35264687083` / `35268148590` / `35273366357` / `35274766286` /
`35295494688` / `35308430491`）。每次都要人工读 summary + 比对历史，且极易把
**「通过但被 fail-closed 阻塞」**（例：`score==1.0` 的放行条目因跨 run 复发进
`systemic_recurrence`）与**「真失败」**混读 —— **#4207 就是这类事故的登记**。
入库后「读结论」从**人工**变成**可复算**。

## 与邻居的边界（**不重复造轮子**）

`tests/agent_eval/acceptance_runner.py` 是**剧本式活体验收**（打线上端点抓 SSE/卡片）；
本脚本只消费**已经落盘**的跑后产物（`eval-summary-*.json` + run 步骤 JSON），
两者用途不同、互补。`flake_history.py` / `eval_slot_status.sh` 管**派发前**，
本脚本管**跑后**。

## 用法

    # 离线（**单测与复核走这条**：不打任何 GitHub API）
    eval_closeout.py --summary eval-summary-mibao.json --summary <dir> \\
                     [--steps-json run-steps.json] \\
                     [--baseline-summary <path>] [--case-ids "OR-011,OR-016"] [--json]

    # 运行时（走 gh 取 artifact + 步骤；需要 gh 已登录）
    eval_closeout.py --run 35295494688 [--baseline-run 35274766286]

## 四段输出

① **三查** —— 步骤级（`Run <persona>` / `判定` 是否 skipped + **抑制/取消留档步骤是否跑了**）+
   产物级（summary 能否解析）+ 新鲜度（`run_key.sha` / `tier` / `policy_version`）；
② **completion 按桶分解** —— **动态枚举** `set(completion) - NON_BLOCKING_VERDICT_KEYS`，
   **不写死桶名清单**（#4245 正在并行新增 `case_asset_failures`；写死 ⇒ 合并后必漏桶），
   并按 #4207 把「未通过条数（score<1）」与「阻塞条数（fail-closed）」**分开呈现**；
③ **逐条收口判据** —— 本批用例清单 × 两腿 × 基线对照；
④ **P0 类判别性判据** —— `replayed=True` 计数（以**证据原文出现次数**为准；历史口径
   `35256153429=0 / 35264687083=11 / 35295494688=8 / 35308430491=0` 可复算）。

## 退出码（与 `scripts/red_proof.py` / `.github/scripts/eval_slot_status.sh` 同族三态）

- `0` = **可判通过**（已评测、无阻塞桶）
- `1` = **判红**（已评测、有阻塞桶）
- `3` = **无法判定**（未评测 / 步骤信息缺失 / 产物缺失不可读）——
  「看不了」不得当「没问题」；**抑制/取消留档步骤一旦跑了 ⇒ 直接判「本 run 未评测」并停**
  （未评测的 run 没有可分解的桶，继续输出就是造结论）。

## 落码状态登记（照实，别把「脚本存在」读成「有门禁」）

- **未接 CI**：现为人工 / 结论档收口环节调用；防回退锁见
  `tests/unit_ci_workflows/test_eval_closeout.py`（5 组判据，各有红证）。
- 目录说明（**与 issue 原文的差异**，照实登记）：issue 写「与 `flake_history.py` /
  `eval_slot_status.sh` 同一目录」，但这两个真实路径是 `.github/scripts/`
  （issue 原文的 `scripts/…` 本身不准确）；本批并行修复的文件所有权禁止本包改
  `.github/**` ⇒ 落在 `scripts/eval_closeout.py`。**是否迁入 `.github/scripts/` 待主会话裁定。**
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# ── 口径常量（单一事实源）──────────────────────────────────────────────────────

#: `completion` 里的**非阻塞**键：ok/reason 是元信息；`flake_released` 是**放行集**
#: （门禁口径 `_COMPLETION_RELEASED_CLASSES` = `llm-noise`，只放行随机波动）；
#: total/passed 是计数；`failure_reasons` 是 #3708 附加的 ID→首要原因映射（**不是桶**）。
#: ⚠️ **其余一切都是阻塞桶** —— 由 `blocking_buckets()` 动态枚举，**故意不写桶名清单**。
NON_BLOCKING_VERDICT_KEYS = frozenset({
    "ok", "reason", "flake_released", "total", "passed", "failure_reasons",
})

REPLAYED_RE = re.compile(r"replayed\s*=\s*true", re.I)
SUPPRESS_MARKER_RE = re.compile(r"被抑制(记录|留档)")
CANCEL_MARKER_RE = re.compile(r"被取消(记录|留档)")
RUN_STEP_RE = re.compile(r"^Run\s+(\S+)\s")
VERDICT_STEP_RE = re.compile(r"^判定（")
LEG_IN_JOB_RE = re.compile(r"(mibao|xiaobu)")

SUPPRESS_HEADER = "## ⏭️ 本 run 未评测（不是结论）"
UNKNOWN_HEADER = "## ❓ 无法判定 —— 本 run 未评测 / 证据不足（不是结论）"
SKIPPED = ("skipped", "none", "")


class CloseoutUndecidable(Exception):
    """**无法判定**（产物/步骤缺失或不可读）—— 「看不了」不得当「没问题」（退出码 3）。"""


# ── 纯函数层（可单测；CLI 只是薄壳）────────────────────────────────────────────

def blocking_buckets(completion: dict) -> dict:
    """阻塞桶 = `completion` 里**除非阻塞键外的一切**（**动态枚举**，不写死桶名）。

    #4245 新增桶（`case_asset_failures`）之后，本函数**不需要任何改动**就会把它算进去；
    反过来，写死桶名清单的实现在它合并后必然漏桶（防回退锁见单测 ③）。
    """
    return {k: list(v or []) for k, v in (completion or {}).items()
            if k not in NON_BLOCKING_VERDICT_KEYS}


def count_replayed(summary: dict) -> dict:
    """`replayed=True` 计数 —— **P0 类判别性判据**（issue #4258 第四段）。

    语义：幂等键回放（`order_create(replayed=True …)`）在本次跑的证据里出现了几次。
    计数取**证据原文出现次数**（不是命中用例数）：实测 `35295494688` mibao 腿是
    **3 条用例 / 4 次出现**，把两者混成一个数就会与历史口径（`0/11/8/0`）对不上。

    只扫用例条目 —— 实测全文件扫描与"逐用例扫描"结果**逐值相同**（顶层无该串），
    故取更窄、更可解释的后者。
    """
    occurrences, case_ids = 0, []
    for c in (summary.get("cases") or []):
        n = len(REPLAYED_RE.findall(json.dumps(c, ensure_ascii=False)))
        if n:
            occurrences += n
            case_ids.append(str(c.get("id")))
    return {"occurrences": occurrences, "case_ids": case_ids}


def _step_state(steps: list, pattern) -> str | None:
    """某一步的结论（第一个命名命中者）；没有该步骤 ⇒ None。"""
    for s in (steps or []):
        if pattern.search(str(s.get("name") or "")):
            return str(s.get("conclusion") or "").lower() or "none"
    return None


def _ran(conclusion) -> bool:
    """留档步骤是否**真跑过**（`skipped` / 缺失都不算）。"""
    return str(conclusion or "").lower() not in SKIPPED


def check_steps(run_meta: dict | None) -> dict:
    """① 三查的**步骤级**（纯函数）。

    判据（fail-closed，顺序即优先级）：
      ① **抑制/取消留档步骤一旦跑了 ⇒ 未评测**（任何 job 里都算 —— 评测 job 的
         `被抑制记录`／`被取消记录` 与结论 job 的 `被抑制留档`／`被取消留档` 是两处通道）；
      ② job 结论 `cancelled` ⇒ 未评测（实测 run `34855662092`：`判定` 步骤**是 failure**
         而非 skipped（#3761 之前的行为）⇒ 只看"判定 skipped"抓不到取消）；
      ③ `Run <persona>` 被 skipped/缺失 ⇒ 未评测；
      ④ `判定` 被 skipped ⇒ 未评测；
      ⑤ 完全拿不到步骤 ⇒ **无法判定**（不是「通过」）。
    """
    jobs = (run_meta or {}).get("jobs") or []
    status = (run_meta or {}).get("status")
    if not jobs:
        return {"state": "unknown", "reason": "无步骤信息（gh 不可用 / 未提供 --steps-json）",
                "legs": {}, "markers": [], "run_conclusion": None, "run_status": status}
    if status and status != "completed":
        return {"state": "unknown", "reason": f"run 尚未跑完（status={status}）",
                "legs": {}, "markers": [], "run_conclusion": None, "run_status": status}

    legs, markers, cancelled_jobs = {}, set(), []
    for job in jobs:
        steps = job.get("steps") or []
        jname = str(job.get("name") or "")
        for s in steps:
            sname = str(s.get("name") or "")
            for label, pattern in (("抑制", SUPPRESS_MARKER_RE), ("取消", CANCEL_MARKER_RE)):
                m = pattern.search(sname)
                # 留档步骤在**两处**通道都留档（评测 job 的「被抑制记录」/「被取消记录」、
                # 结论 job 的「被抑制留档」/「被取消留档」）⇒ 按命中的标记去重，名字只留标记本身。
                if m and _ran(s.get("conclusion")):
                    markers.add((label, m.group(0)))
        if str(job.get("conclusion") or "").lower() == "cancelled":
            cancelled_jobs.append(jname)
        run_step_name = None
        for s in steps:
            m = RUN_STEP_RE.match(str(s.get("name") or ""))
            if m:
                run_step_name = m.group(1)
                break
        if run_step_name is None:
            continue
        legs.setdefault(run_step_name, {
            "job": jname, "job_conclusion": job.get("conclusion"),
            "run_step": _step_state(steps, RUN_STEP_RE),
            "verdict_step": _step_state(steps, VERDICT_STEP_RE),
            "suppress_step": _step_state(steps, SUPPRESS_MARKER_RE),
            "cancel_step": _step_state(steps, CANCEL_MARKER_RE),
        })

    base = {"legs": legs, "markers": sorted(markers),
            "run_conclusion": (run_meta or {}).get("conclusion"), "run_status": status}
    hits = sorted({k for k, _ in markers})
    if hits:
        who = "、".join(
            f"{k}（{', '.join(n for kk, n in sorted(markers) if kk == k)}）" for k in hits)
        return {**base, "state": "not_evaluated",
                "reason": f"{who}留档步骤**已运行** ⇒ 本次没有评测、没有结论"}
    if cancelled_jobs:
        return {**base, "state": "not_evaluated",
                "reason": f"job 被取消（{', '.join(cancelled_jobs)}）⇒ 本次没有评测、没有结论"}
    if not legs:
        return {**base, "state": "unknown", "reason": "未识别到任何评测腿（`Run <persona>` 步骤）"}
    for persona, rec in sorted(legs.items()):
        if not _ran(rec["run_step"]) or rec["run_step"] is None:
            return {**base, "state": "not_evaluated",
                    "reason": f"{persona}：`Run {persona} …（真实 LLM）` 未执行"
                              f"（conclusion={rec['run_step']}）⇒ 未评测"}
        if not _ran(rec["verdict_step"]) or rec["verdict_step"] is None:
            return {**base, "state": "not_evaluated",
                    "reason": f"{persona}：`判定` 步骤未执行"
                              f"（conclusion={rec['verdict_step']}）⇒ 未评测"}
    return {**base, "state": "evaluated", "reason": "评测腿均已执行且判定步骤已运行"}


def _persona_of(summary: dict) -> str:
    rk = summary.get("run_key") or {}
    return str(rk.get("persona") or summary.get("label") or "?")


def _leg_view(summary: dict) -> dict:
    completion = summary.get("completion") or {}
    buckets = blocking_buckets(completion)
    blocking = sorted({str(c) for ids in buckets.values() for c in ids})
    failed = [str(c.get("id")) for c in (summary.get("cases") or [])
              if c.get("score", 0) < 1.0]
    rk = summary.get("run_key") or {}
    return {
        "ok": bool(completion.get("ok")),
        "reason": completion.get("reason") or "",
        "buckets": buckets,
        "blocking": blocking,
        "failed": failed,
        "released": list(completion.get("flake_released") or []),
        "sha": str(rk.get("sha") or ""),
        "tier": rk.get("tier"), "policy_version": rk.get("policy_version"),
        "executed_count": rk.get("executed_count"),
        "total": summary.get("total"), "passed": summary.get("passed"),
        "source": summary.get("__source") or "",
        "replayed": count_replayed(summary),
    }


def _legs_of(summaries, label) -> dict:
    legs = {}
    for s in summaries or []:
        if not isinstance(s, dict):
            raise CloseoutUndecidable(f"{label}：产物不是 JSON 对象（{type(s).__name__}）")
        legs[_persona_of(s)] = _leg_view(s)
    return legs


def _case_states(legs: dict, cid: str) -> dict:
    out = {}
    for persona, leg in legs.items():
        if cid in leg["blocking"]:
            out[persona] = {"state": "未收口",
                            "buckets": [k for k, ids in leg["buckets"].items() if cid in ids]}
        elif cid in leg["failed"]:
            out[persona] = {"state": "未收口", "buckets": ["（未通过但不在任何阻塞桶）"]}
        else:
            out[persona] = {"state": "已收口", "buckets": []}
    return out


def closeout(summaries, steps, baseline=None, case_ids=None) -> dict:
    """跑后收口核对（纯函数）。

    `summaries` / `baseline` = 已解析的 `eval-summary-*.json` dict 列表；
    `steps` = `gh run view --json jobs,…` 的结果（或 None）；`case_ids` = 本批用例清单。
    """
    info = check_steps(steps)
    if info["state"] != "evaluated":
        return {"state": info["state"], "state_reason": info["reason"], "steps": info,
                "legs": {}, "baseline_legs": {}, "case_rows": [], "case_list": [],
                "case_source": "", "replayed_total": 0, "blocking_total": 0,
                "red_legs": [], "exit_code": 3}

    legs = _legs_of(summaries, "本次产物")
    baseline_legs = _legs_of(baseline, "基线产物")
    if not legs:
        raise CloseoutUndecidable("已有步骤信息但**一个产物都没有** ⇒ 无法判定（禁止假绿）")

    explicit = [c.strip() for c in (case_ids or []) if c and c.strip()]
    if explicit:
        case_list, source = explicit, f"--case-ids（{len(explicit)} 条）"
    else:
        pool = set()
        for group in (legs, baseline_legs):
            for leg in group.values():
                pool |= set(leg["blocking"])
        case_list = sorted(pool)
        source = f"阻塞桶并集（{len(case_list)} 条）"

    rows = []
    for cid in case_list:
        now = _case_states(legs, cid)
        was = _case_states(baseline_legs, cid)
        unclosed = [p for p, v in now.items() if v["state"] == "未收口"]
        if not unclosed:
            verdict = ("本批已收口" if any(v["state"] == "未收口" for v in was.values())
                       else "已收口")
        elif not baseline_legs:
            verdict = "未收口（无基线参照）"
        elif any(v["state"] == "未收口" for v in was.values()):
            verdict = "仍未收口"
        else:
            verdict = "新增未收口"
        rows.append({"case_id": cid, "legs": now, "baseline": was, "verdict": verdict})

    blocking_total = sum(len(leg["blocking"]) for leg in legs.values())
    replayed_total = sum(leg["replayed"]["occurrences"] for leg in legs.values())
    red_legs = sorted(p for p, leg in legs.items() if not leg["ok"])
    return {
        "state": "evaluated", "state_reason": info["reason"], "steps": info,
        "legs": legs, "baseline_legs": baseline_legs,
        "case_rows": rows, "case_list": case_list, "case_source": source,
        "blocking_total": blocking_total, "replayed_total": replayed_total,
        "red_legs": red_legs, "exit_code": 1 if red_legs else 0,
    }


# ── 渲染（四段 + 明确抬头）──────────────────────────────────────────────────────

def _fmt_sha(sha: str) -> str:
    return f"{sha[:8]}…" if sha else "（缺 run_key.sha）"


def render(res: dict) -> str:
    """把 `closeout()` 的结果渲染成四段文本（人读）。"""
    out = ["════════ 判定档跑后收口核对（issue #4258）════════", ""]
    if res["state"] != "evaluated":
        out.append(SUPPRESS_HEADER if res["state"] == "not_evaluated" else UNKNOWN_HEADER)
        out.append("")
        out.append(f"理由：{res['state_reason']}")
        out.append("")
        out.append("**已停在此处**：没有结论的 run 没有可分解的桶、也没有可收口的条目 —— "
                   "继续输出就是造结论（未评测的 run 不是结果）。")
        out.append("退出码 3（0 可判通过 / 1 判红 / 3 无法判定）")
        return "\n".join(out)

    info, legs = res["steps"], res["legs"]

    out.append("── ① 三查（步骤级 / 产物级 / 新鲜度）──")
    for persona, rec in sorted(info["legs"].items()):
        out.append(f"  [步骤级] {persona}：Run {persona}=`{rec['run_step']}`；"
                   f"判定=`{rec['verdict_step']}`；抑制留档=`{rec['suppress_step']}`；"
                   f"取消留档=`{rec['cancel_step']}`；job=`{rec['job_conclusion']}`")
    for persona, leg in sorted(legs.items()):
        if leg["source"]:
            out.append(f"  [产物级] {persona}：{leg['source']} 可解析"
                       f"（total={leg['total']} passed={leg['passed']}）")
        else:
            out.append(f"  [产物级] {persona}：可解析（total={leg['total']} "
                       f"passed={leg['passed']}）")
    missing = sorted(set(info["legs"]) - set(legs))
    for persona in missing:
        out.append(f"  [产物级] ⚠️ {persona}：**无产物**（步骤显示已评测却没 artifact）")
    shas = {p: leg["sha"] for p, leg in legs.items()}
    uniq = {s for s in shas.values() if s}
    for persona, leg in sorted(legs.items()):
        out.append(f"  [新鲜度] {persona}：run_key.sha={_fmt_sha(leg['sha'])} "
                   f"tier={leg['tier']} policy_version={leg['policy_version']} "
                   f"executed_count={leg['executed_count']}")
    out.append(f"  [新鲜度] 两腿 sha {'一致' if len(uniq) <= 1 else '**不一致**'}："
               f"{', '.join(f'{p}={_fmt_sha(s)}' for p, s in sorted(shas.items()))}")
    out.append("")

    out.append("── ② completion 按桶分解（**动态枚举桶键**；不按会漏计的「未通过列表」，#4207）──")
    for persona, leg in sorted(legs.items()):
        out.append(f"  [{persona}] completion.ok={str(leg['ok']).lower()}  "
                   f"阻塞={len(leg['blocking'])} 条  未通过条数={len(leg['failed'])}"
                   f"（score<1；⚠️ 会漏计 fail-closed 阻塞条目 —— #4207）")
        for key, ids in leg["buckets"].items():
            out.append(f"      · {key}={len(ids)} {ids}")
        out.append(f"      · 放行（非阻塞）flake_released={len(leg['released'])} "
                   f"{leg['released']}")
    out.append("")

    out.append("── ③ 逐条收口判据（本批用例清单 × 两腿 × 基线对照）──")
    out.append(f"  用例清单来源：{res['case_source']}")
    for row in res["case_rows"]:
        cells = []
        for persona in sorted(set(row["legs"]) | set(row["baseline"])):
            v = row["legs"].get(persona)
            cur = (f"{v['state']}({','.join(v['buckets'])})" if v and v["buckets"]
                   else (v["state"] if v else "未跑"))
            b = row["baseline"].get(persona)
            if row["baseline"]:
                cur += f" 基线={b['state'] if b else '未跑'}"
            cells.append(f"{persona}={cur}")
        out.append(f"  {row['case_id']:<10} {'  '.join(cells)}  → {row['verdict']}")
    out.append("")

    out.append("── ④ P0 类判别性判据：replayed=True 计数（以**证据原文出现次数**为准）──")
    for persona, leg in sorted(legs.items()):
        r = leg["replayed"]
        out.append(f"      · {persona}={r['occurrences']} 次出现 / {len(r['case_ids'])} 条用例 "
                   f"{r['case_ids']}")
    out.append(f"      合计={res['replayed_total']} 次出现"
               f"（跨 run 对比请与人工核对结论并排登记）")
    out.append("")

    out.append("── 判定 ──")
    if res["exit_code"] == 0:
        out.append(f"  ✅ 已评测，无阻塞（两腿 completion.ok=true；"
                   f"退出码 0）")
    else:
        out.append(f"  ❌ 已评测，判红：阻塞 {res['blocking_total']} 条，"
                   f"completion.ok=false 的腿：{', '.join(res['red_legs'])}（退出码 1）")
    return "\n".join(out)


def as_json(res: dict) -> dict:
    """机读形态（去掉内部 `__source` 噪音，桶与计数全保留）。"""
    return {k: v for k, v in res.items() if k != "steps"} | {"steps": res.get("steps")}


# ── 产物加载 + gh 取数（**离线入口不碰 gh**）────────────────────────────────────

def expand_summary_paths(paths) -> tuple:
    """`--summary` 可以是文件或目录（目录**递归**取 `eval-summary-*.json`）。

    递归是必需的（不是顺手）：`gh run download <id> -D <dest>` 把每个 artifact 解到
    `<dest>/<artifact-name>/` 子目录下，只 glob 顶层会得到「0 个产物 ⇒ 无法判定」。
    """
    files, missing = [], []
    for raw in paths or []:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.rglob("eval-summary-*.json")))
        elif p.is_file():
            files.append(p)
        else:
            missing.append(str(p))
    return files, missing


def load_summaries(paths) -> list:
    files, missing = expand_summary_paths(paths)
    if missing:
        raise CloseoutUndecidable(f"产物缺失/不可读：{', '.join(missing)}")
    out = []
    for f in files:
        try:
            data = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception as e:                                   # noqa: BLE001
            raise CloseoutUndecidable(f"产物解析失败（{e.__class__.__name__}）：{f}") from e
        if not isinstance(data, dict):
            raise CloseoutUndecidable(f"产物不是 JSON 对象：{f}")
        data["__source"] = str(f)
        out.append(data)
    if not files:
        raise CloseoutUndecidable("没有匹配到任何产物（--summary 目录下无 eval-summary-*.json）")
    return out


def fetch_run(run_id) -> tuple:
    """运行时入口：走 `gh` 取步骤 + artifact（**单测绝不走这条**）。"""
    try:
        meta = subprocess.run(
            ["gh", "run", "view", str(run_id),
             "--json", "conclusion,status,headSha,event,jobs"],
            capture_output=True, text=True, check=True).stdout
    except Exception as e:                                       # noqa: BLE001
        raise CloseoutUndecidable(f"gh run view {run_id} 失败（{e.__class__.__name__}）") from e
    dest = Path(tempfile.mkdtemp(prefix=f"eval-closeout-{run_id}-"))
    try:
        subprocess.run(["gh", "run", "download", str(run_id), "-D", str(dest)],
                       capture_output=True, text=True, check=True)
    except Exception as e:                                       # noqa: BLE001
        raise CloseoutUndecidable(f"gh run download {run_id} 失败（{e.__class__.__name__}）") from e
    return json.loads(meta), dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="判定档跑后收口核对（issue #4258）：三查 + 桶分解 + 逐条判据 + replayed 计数")
    ap.add_argument("--summary", action="append", default=[],
                    help="eval-summary-*.json 路径或目录（可重复；离线入口）")
    ap.add_argument("--steps-json", help="`gh run view --json jobs,…` 的输出文件（离线入口）")
    ap.add_argument("--baseline-summary", action="append", default=[],
                    help="基线 run 的产物（可重复）")
    ap.add_argument("--case-ids", help="本批用例清单（逗号分隔）；缺省 = 阻塞桶并集")
    ap.add_argument("--run", help="运行时入口：run id（走 gh 取步骤 + artifact）")
    ap.add_argument("--baseline-run", help="基线 run id（走 gh）")
    ap.add_argument("--json", action="store_true", help="机读输出")
    args = ap.parse_args(argv)

    try:
        steps = None
        summaries = load_summaries(args.summary) if args.summary else []
        baseline = load_summaries(args.baseline_summary) if args.baseline_summary else []
        if args.steps_json:
            steps = json.loads(Path(args.steps_json).read_text(encoding="utf-8"))
        if args.run:
            steps, dest = fetch_run(args.run)
            if not args.summary:
                summaries = load_summaries([str(dest)])
        if args.baseline_run:
            _bmeta, bdest = fetch_run(args.baseline_run)
            if not args.baseline_summary:
                baseline = load_summaries([str(bdest)])
        case_ids = args.case_ids.split(",") if args.case_ids else None
        res = closeout(summaries, steps, baseline, case_ids)
    except CloseoutUndecidable as e:
        print(UNKNOWN_HEADER)
        print()
        print(f"理由：{e}")
        print()
        print("**已停在此处**：没有结论的 run 没有可分解的桶、也没有可收口的条目。")
        print("退出码 3（0 可判通过 / 1 判红 / 3 无法判定）")
        return 3

    print(json.dumps(as_json(res), ensure_ascii=False, indent=2) if args.json else render(res))
    return res["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
