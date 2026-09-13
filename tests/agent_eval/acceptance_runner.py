"""
真实环境验收 runner（issue #2801 澄清能力真实验收）

与 agent-eval local_runner 的区别：
- 捕获完整 SSE 事件：text / tool_call / tool_result / interactive（choice/confirm/form
  澄清卡！）/ error / done —— 验收必须看到澄清卡是否弹出
- 真实登录：mibao 用线上万能码登录；xiaobu 用 X-Debug-Role: customer
- 支持每轮 text + images（真实图片 URL）
- 输出结构化验收记录（每轮：用户输入 → AI 文本 / 工具 / 澄清卡）

用法（打线上真实端点）：
    PERSONA=mibao python3 tests/agent_eval/acceptance_runner.py <场景json>
    PERSONA=xiaobu python3 tests/agent_eval/acceptance_runner.py <场景json>

场景 JSON 格式：
    {"id": "C-01", "title": "纯图找同款", "domain": "product",
     "rounds": [{"text": "", "images": ["https://..."]}, {"text": "确认", "images": []}]}
"""
import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import httpx


def _load_local_runner():
    """复用 local_runner 的**前端点卡协议**（choice_card_answer 等）。

    为什么要复用而不是各写一份：卡片作答协议（单选发 label / 多选发 `前缀+labels` /
    confirm 发 confirmValue）是前端 `InteractiveMessage.tsx` 的语义，已被 local_runner
    实现并校准过。验收 runner 若自带一份，两份必然随迭代漂移 —— 而"harness 答错卡"
    正是本项目反复踩过的坑（OR-017 死循环）。
    """
    path = Path(__file__).resolve().parent / "local_runner.py"
    spec = importlib.util.spec_from_file_location("migao_local_runner_for_acceptance", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_LR = _load_local_runner()

AI_API = os.environ.get("AI_API_URL", "https://ai-api.migaozn.com")
ADMIN_API = os.environ.get("ADMIN_API_URL", "https://api.migaozn.com")
PHONE = os.environ.get("TEST_PHONE", "13800138000")
BYPASS_CODE = os.environ.get("TEST_CODE", "123456")
PERSONA = os.environ.get("PERSONA", "mibao").strip().lower()


async def login() -> str:
    """mibao：真实登录拿 token；xiaobu：空字符串走 X-Debug-Role"""
    if PERSONA == "xiaobu":
        return ""
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{ADMIN_API}/api/auth/sms/login",
                         json={"phone": PHONE, "code": BYPASS_CODE}, timeout=15)
        return r.json()["data"]["accessToken"]


def _headers(token: str) -> dict:
    if PERSONA == "xiaobu":
        return {"X-Debug-Role": "customer"}
    return {"Authorization": f"Bearer {token}"}


async def send(session_id: str, token: str, text: str, images=None) -> dict:
    """发送一轮消息，捕获完整事件"""
    body = {"session_id": session_id, "message": text}
    if images:
        body["images"] = images
    result = {
        "text": "", "tool_calls": [], "tool_results": [],
        "interactive": [], "cards": [], "error": None, "done": False,
    }
    async with httpx.AsyncClient(timeout=120) as c:
        async with c.stream("POST", f"{AI_API}/api/chat/send",
                            headers=_headers(token), json=body) as resp:
            current = None
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("event:"):
                    current = line[6:].strip()
                elif line.startswith("data:"):
                    ds = line[5:].strip()
                    if ds == "[DONE]":
                        break
                    try:
                        p = json.loads(ds)
                    except json.JSONDecodeError:
                        continue
                    if current == "text":
                        result["text"] += p.get("content", "")
                    elif current == "tool_call":
                        result["tool_calls"].append({"name": p.get("tool", ""), "args": p.get("args", {})})
                    elif current == "tool_result":
                        result["tool_results"].append(p)
                    elif current == "interactive":
                        result["interactive"].append(p)
                    elif current == "card":
                        result["cards"].append(p)
                    elif current == "error":
                        result["error"] = str(p)
                    elif current == "done":
                        result["done"] = True
                    current = None
    return result


def _fmt_tool(t: dict) -> str:
    args = t.get("args") or {}
    return f"  🔧 {t['name']}({json.dumps(args, ensure_ascii=False)[:200]})"


def _fmt_interactive(i: dict) -> str:
    comp = i.get("component") or i.get("type")
    title = i.get("title", "")
    opts = i.get("options")
    if opts:
        labels = [o.get("label", "") for o in opts][:6]
        return f"  🃏 [澄清卡 choice] {title} → {' | '.join(labels)}"
    fields = i.get("fields")
    if fields:
        return f"  🃏 [确认卡 confirm] {title} → {json.dumps(fields, ensure_ascii=False)[:200]}"
    return f"  🃏 [{comp}] {title}"


SUPPORTED_CHECK_TYPES = {
    "tool_called", "tool_not_called", "no_error", "card_shown",
    "ai_text_contains", "ai_text_not_contains",
}


def _round_scope(rounds: list, ref: str) -> list:
    """按 `ref: R3` 取轮次；`*`/缺省 = 全轮。轮次锚定是协议点名的必需项 ——
    「任意一轮命中即过」会让"顺序错/该轮没做"看起来正常。"""
    ref = str(ref or "*").strip().upper()
    if ref in ("", "*", "ALL"):
        return list(rounds or [])
    m = ref.lstrip("R")
    if not m.isdigit():
        return list(rounds or [])
    want = int(m)
    return [r for r in (rounds or []) if r.get("round") == want]


def evaluate_checks(checks: list, rounds: list) -> list:
    """执行 L1/L2 断言，返回违规列表 [{check, level, detail}]。

    UA（体验类）条目**不在这里判**（协议铁律 4：由 AI 用户代理判定），
    由 `ua_items()` 单独列出交给 AI 判定。
    """
    issues = []
    for chk in checks or []:
        if not isinstance(chk, dict):
            issues.append({"check": chk, "level": "L1", "detail": f"配置非字典: {chk!r}"})
            continue
        level = str(chk.get("level") or "L1").upper()
        if level == "UA":
            continue
        ctype = str(chk.get("type") or "")
        expect = str(chk.get("expect") or "")
        scope = _round_scope(rounds, chk.get("ref"))
        if ctype not in SUPPORTED_CHECK_TYPES:
            issues.append({"check": chk, "level": level,
                           "detail": f"不支持的断言类型 {ctype!r}（不得静默跳过）"})
            continue
        if not scope:
            issues.append({"check": chk, "level": level,
                           "detail": f"ref={chk.get('ref')!r} 没有对应轮次（锚点写错？）"})
            continue

        if ctype == "no_error":
            bad = [r for r in scope if r.get("error")]
            if bad:
                issues.append({"check": chk, "level": level,
                               "detail": f"R{bad[0]['round']} 出现错误: {str(bad[0]['error'])[:120]}"})
            continue

        if ctype in ("tool_called", "tool_not_called"):
            hits = [(r["round"], t.get("name")) for r in scope for t in (r.get("tools") or [])
                    if expect and expect in str(t.get("name") or "")]
            if ctype == "tool_called" and not hits:
                issues.append({"check": chk, "level": level,
                               "detail": f"期望调用 {expect}，实际未调用（轮次 {[r['round'] for r in scope]}）"})
            if ctype == "tool_not_called" and hits:
                issues.append({"check": chk, "level": level,
                               "detail": f"{expect} 被调用了（R{hits[0][0]}）—— 不允许发生"})
            continue

        if ctype == "card_shown":
            hits = [r["round"] for r in scope
                    for iv in (r.get("interactive") or [])
                    if expect and expect in str(iv.get("type") or iv.get("component") or "")]
            if not hits:
                issues.append({"check": chk, "level": level,
                               "detail": f"期望出现 {expect} 卡片，实际没有"})
            continue

        texts = [str(r.get("ai_text") or "") for r in scope]
        joined = "\n".join(texts)
        if ctype == "ai_text_contains" and expect not in joined:
            issues.append({"check": chk, "level": level,
                           "detail": f"回复未出现「{expect}」（轮次 {[r['round'] for r in scope]}）"})
        if ctype == "ai_text_not_contains" and expect in joined:
            hit = next(r["round"] for r in scope if expect in str(r.get("ai_text") or ""))
            issues.append({"check": chk, "level": level,
                           "detail": f"R{hit} 回复出现禁词「{expect}」"})
    return issues


def ua_items(checks: list) -> list:
    """列出待 AI 用户代理判定的 UA 条目（协议铁律 4：禁止写"待人工"，也禁止机器假装判过）。"""
    return [c for c in (checks or [])
            if isinstance(c, dict) and str(c.get("level") or "").upper() == "UA"]


def resolve_action(rd: dict, rounds: list) -> str:
    """把剧本动作翻译成本轮实际要发的消息。

    支持 `{"click": "first_option"|"confirm"}`（点卡，按前端协议作答），
    取不到卡时用 `fallback` 文本（真实顾客遇到没卡就说话）。
    """
    if "click" not in rd:
        return str(rd.get("text") or "")
    last = (rounds or [{}])[-1] if rounds else {}
    cards = last.get("interactive") or []
    by_comp = {}
    for iv in cards:
        by_comp.setdefault(str(iv.get("type") or iv.get("component") or ""), iv)
    kind = str(rd.get("click") or "")
    if kind == "auto":
        # 有什么卡答什么卡（优先级与评测 harness 一致：confirm > choice > form）
        # —— 剧本不能依赖"卡一定按我写的顺序出现"：卡的顺序随模型变化，
        # 固定 click 会把**剧本错位**报成**产品问题**（本 session C-A1 实测）。
        if "confirm" in by_comp:
            val = str(by_comp["confirm"].get("confirmValue") or "").strip()
            if val:
                return val
        if "choice" in by_comp:
            answer = _LR.choice_card_answer(by_comp["choice"])
            if answer:
                return answer
        if "form" in by_comp:
            values = {}
            for f in (by_comp["form"].get("formFields") or []):
                key = str((f or {}).get("key") or "")
                if not key:
                    continue
                val = (f or {}).get("value")
                values[key] = "" if val is None else val
            if values:
                return "__FORM__|" + json.dumps(values, ensure_ascii=False)
        return str(rd.get("fallback") or rd.get("text") or "")
    if kind == "confirm" and "confirm" in by_comp:
        val = str(by_comp["confirm"].get("confirmValue") or "").strip()
        if val:
            return val
    if kind in ("first_option", "choice") and "choice" in by_comp:
        card = by_comp["choice"]
        answer = _LR.choice_card_answer(card)
        if answer:
            return answer
    return str(rd.get("fallback") or rd.get("text") or "")


def tool_called_in(rounds: list, tool: str) -> bool:
    """该工具是否已被成功/已调用过（供 `repeat_until` 的达成判定）。"""
    if not tool:
        return False
    return any(
        tool in str(t.get("name") or "")
        for r in (rounds or [])
        for t in (r.get("tools") or [])
    )


def repeat_wanted(rd: dict, rounds: list) -> tuple:
    """`repeat_until` 判定 → (是否继续重复, 还要几轮 / max)。

    协议动机（issue #3379 剧本方差）：剧本轮数固定，而 agent 卡序与轮数随模型变化 ——
    实测 C-A1 有时 8 轮内走不到下单，同代码同剧本交替出现红/绿。
    把"轮数"从**剧本假设**变成**产品事实**：目标未达成 → 继续合作；达成 → 停。
    """
    spec = (rd or {}).get("repeat_until")
    if not isinstance(spec, dict):
        return False, 0
    max_n = int(spec.get("max") or 5)
    want = str(spec.get("tool_called") or "")
    return (not tool_called_in(rounds, want)), max_n


def wants_new_session(rd: dict) -> bool:
    """`{"session": "new"}` = 顾客换个窗口/新开会话回来（验收剧本必需的真实动作）。"""
    return str((rd or {}).get("session") or "").strip().lower() == "new"


def build_report(sc: dict, checks: list, issues: list, sha: str, date: str) -> str:
    """按协议 §4.2 生成报告骨架（五项齐全；UA 判定由 AI 用户代理填写）。"""
    ua = ua_items(checks)
    lines = [
        f"# 验收报告 {sc.get('id')} {sc.get('title')} {date} sha={sha}",
        "## 结论",
        "- 待填（L1/L2 机器结论 + UA 用户代理判定汇总后给出）",
        "## 验收矩阵",
        "| 场景 | L1 | L2 | UA | 结果 | 证据引用 |",
        "|---|---|---|---|---|---|",
        f"| {sc.get('id')} | {'见下' if checks else '-'} | {'见下' if checks else '-'} "
        f"| {len(ua)} 条待判 | {'待判' if not issues else '有违规'} | |",
        "## 问题清单",
    ]
    if issues:
        lines.append("| # | 级别 | 问题 | 证据（轮次/原文） | 对应 case | 修复 PR |")
        lines.append("|---|---|---|---|---|---|")
        for i, it in enumerate(issues, 1):
            lines.append(f"| {i} | P1 | {it['detail']} | {it['check']} | | |")
    else:
        lines.append("（L1/L2 无违规）")
    lines += [
        "## 复核验收抽验（独立 AI 视角，零人工）",
        "| 抽验项 | 证据位置 | 复核结论 | 与主验收一致性 |",
        "|---|---|---|---|",
        "## 沉淀记录",
        "| 问题 | 新增/修改 case | case 有效性验证（旧失败重放 fail / 修复重放 pass） |",
        "|---|---|---|",
    ]
    return "\n".join(lines)


async def _new_session(token: str) -> str:
    """新建会话（线上偶发失败重试 2 次）"""
    session_id = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient() as c:
                r = await c.post(f"{AI_API}/api/chat/sessions",
                                 headers=_headers(token), json={}, timeout=15)
                session_id = r.json()["data"]["id"]
            if session_id:
                break
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(1.0)
    return session_id


async def _close_session(token: str, session_id: str) -> None:
    """关闭会话（协议 §2.2 生命周期：换窗口前必须把旧会话关掉，否则它留在系统里
    既是脏数据、也让"关闭后才落库"的数据（记忆）无从验证）。失败只告警不中断。"""
    if not session_id:
        return
    try:
        async with httpx.AsyncClient() as c:
            await c.put(f"{AI_API}/api/chat/sessions/{session_id}/close",
                        headers=_headers(token), timeout=15)
    except Exception as e:
        print(f"  ⚠️ 会话关闭失败 {session_id}: {type(e).__name__}: {e}")


async def run_scenario(sc: dict, token: str) -> dict:
    """跑一个场景（多轮），返回完整记录。

    支持剧本的真实动作：
      · `{"click": "first_option"|"confirm"}` → 按前端协议点卡（取不到卡用 fallback 文本）
      · `{"session": "new"}` → 关掉当前会话、新开一个（顾客换个窗口回来）
    """
    session_id = await _new_session(token)
    sessions = [session_id]

    rounds = []
    _spec = list(sc.get("rounds", []))
    i = 0
    while i < len(_spec):
        rd = _spec[i]
        if wants_new_session(rd):
            await _close_session(token, session_id)
            session_id = await _new_session(token)
            sessions.append(session_id)
        # repeat_until（issue #3379）：目标未达成就继续以"协作型顾客"的方式答卡，
        # 达成立即停；走满 max 也停（缺口交由剧本断言如实报出，绝不无限循环）。
        keep_going, budget = repeat_wanted(rd, rounds)
        # 墙钟上限（issue #3379）：`max` 只限**轮数**，但单轮可能极慢（模型长思考/SSE 卡住）
        # —— 首版实测把验收步骤拖到 13min+ 仍未结束（CI 上被迫取消两次）。
        # 轮数与时间**双上限**，任一到达即停，缺口交由断言如实报出。
        _deadline_ts = time.monotonic() + float(os.environ.get("ACCEPTANCE_REPEAT_BUDGET_S", "240"))
        repeat = 0
        while True:
            text = resolve_action(rd, rounds)
            images = rd.get("images") or []
            res = await send(session_id, token, text, images)
            rounds.append({
                "round": len(rounds) + 1,
                "session": session_id,
                "user_text": text,
                "user_images": len(images),
                "ai_text": res["text"],
                "tools": res["tool_calls"],
                "interactive": res["interactive"],
                "error": res["error"],
                "spec_index": i,
            })
            await asyncio.sleep(0.6)
            if not keep_going:
                break
            repeat += 1
            if tool_called_in(rounds, str((rd.get("repeat_until") or {}).get("tool_called") or "")):
                break
            if repeat >= budget:
                print(f"  ⏹ repeat_until 达轮数上限 max={budget}（目标未达成，交断言报出）", flush=True)
                break
            if time.monotonic() >= _deadline_ts:
                print(f"  ⏹ repeat_until 达墙钟上限 "
                      f"{os.environ.get('ACCEPTANCE_REPEAT_BUDGET_S', '240')}s（目标未达成）",
                      flush=True)
                break
        i += 1

    return {"id": sc["id"], "title": sc["title"], "domain": sc.get("domain", ""),
            "scenario": {"checks": sc.get("checks") or []},
            "sessions": sessions, "rounds": rounds}


def render(scenario_result: dict) -> str:
    """渲染成可读验收记录（供人工评估）"""
    lines = []
    lines.append(f"## {scenario_result['id']} [{scenario_result['domain']}] {scenario_result['title']}")
    prev_session = None
    for rd in scenario_result["rounds"]:
        img = f" [📷x{rd['user_images']}]" if rd["user_images"] else ""
        sid = rd.get("session")
        if sid and sid != prev_session:
            lines.append(f"\n> 🪟 会话: {sid}" + ("（换窗口：新会话）" if prev_session else ""))
            prev_session = sid
        lines.append(f"\n**R{rd['round']} 用户**: {rd['user_text'] or '(纯图片)'}{img}")
        for i in rd["interactive"]:
            lines.append(_fmt_interactive(i))
        for t in rd["tools"]:
            lines.append(_fmt_tool(t))
        if rd["ai_text"]:
            # 协议 §4.1：**任何一轮的 AI 原文不得省略** —— 截断会让"话术很长但没给出口"
            # 这类体验问题在证据里消失（UA 判定必须能读到全文）
            lines.append(f"  💬 {rd['ai_text']}")
        if rd["error"]:
            lines.append(f"  ⚠️ error: {rd['error']}")
    return "\n".join(lines)


async def main():
    if len(sys.argv) < 2:
        print("用法: PERSONA=mibao|xiaobu python3 acceptance_runner.py <场景json> [输出目录]")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        scenarios = json.load(f)
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    date = os.environ.get("ACCEPTANCE_DATE", "local")
    sha = os.environ.get("GITHUB_SHA", "local")[:8]
    token = await login()
    print(f"PERSONA={PERSONA} | token={'真实登录' if token else 'X-Debug-Role'}", flush=True)
    all_issues = []
    for sc in scenarios:
        print("\n" + "=" * 70)
        print(f"▶ 开始场景 {sc.get('id')}（{len(sc.get('rounds') or [])} 段）", flush=True)
        result = await run_scenario(sc, token)
        issues = evaluate_checks(sc.get("checks") or [], result["rounds"])
        result["issues"] = issues
        result["ua_pending"] = ua_items(sc.get("checks") or [])
        print(render(result))
        print(f"\nL1/L2 违规 {len(issues)} 条；UA 待 AI 用户代理判定 {len(result['ua_pending'])} 条")
        for it in issues:
            print(f"  ❌ [{it['level']}] {it['detail']}")
        all_issues += issues
        if out_dir:
            # 协议 §4.1：acceptance/<日期>/<剧本ID>/<场景ID>.transcript.md（AI 原文不得省略）
            d = out_dir
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{result['id']}.transcript.md").write_text(render(result) + "\n", encoding="utf-8")
            (d / f"{result['id']}.evidence.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            (d / f"{result['id']}.report.md").write_text(
                build_report(sc, sc.get("checks") or [], issues, sha, date) + "\n", encoding="utf-8")
        print("=" * 70)
    if out_dir:
        print(f"\n产物已写入 {out_dir}")
    print(f"\n总计 L1/L2 违规 {len(all_issues)} 条")
    sys.exit(1 if all_issues else 0)


if __name__ == "__main__":
    asyncio.run(main())
