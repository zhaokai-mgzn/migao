#!/usr/bin/env python3
"""
render_cases.py — 用例契约渲染器（case-contract 单一源的两端）

输入 : cases/*.yml（唯一行为用例源，schema 见 design/16-case-contract.md）
输出 :
  1. eval_cases.py              — 生成物，供 local_runner.py 导入（兼容期）
  2. mibao-verification-cases.md — 生成物，人读 casebook

★ 生成物禁止手改：改用例 → 改 cases/*.yml → 重新渲染。
  头部均有 GENERATED 标记；与源不一致时以 cases/*.yml 为准。

用法:
  python3 render_cases.py --cases seed/migao/cases \
      --out-eval tests/agent_eval/eval_cases.py \
      --out-md docs/testing/mibao-verification-cases.md
"""
import argparse
import os
import re
import sys

GENERATED_HEADER = "# GENERATED FILE — DO NOT EDIT\n" \
                   "# 源: cases/*.yml（case-contract 单一源）\n" \
                   "# 重新生成: python3 render_cases.py --cases <dir> --out-eval <py> --out-md <md>\n"

# 域 → 旧 eval_cases Skill 枚举（生成物兼容 local_runner 的导入面）
SKILL_MAP = {
    "order": "ORDER",
    "product": "PRODUCT",
    "processing": "PRODUCT",
    "category": "PRODUCT",
    "aftersales": "AFTERSALES",
    "customer": "CUSTOMER",
    "cross": "CROSS",
    "chat": "MULTI_TURN",
    "defense": "GENERAL",
    "hr": "GENERAL",
    "settings": "GENERAL",
    "data": "GENERAL",
}

TIER_MAP = {"smoke": "SMOKE", "normal": "NORMAL", "edge": "EDGE", "adversarial": "ADVERSARIAL"}

DOMAIN_TITLES = {
    "order": "订单域", "product": "商品域", "processing": "加工项域", "category": "分类域",
    "aftersales": "售后域", "customer": "客户域", "hr": "人事域", "settings": "设置域",
    "data": "数据域", "chat": "对话边界域", "cross": "跨域", "defense": "防御域",
}


def _yaml():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (here, os.path.join(here, "..", "qa"), os.path.join(here, "..", "..", ".github")):
        if d not in sys.path:
            sys.path.insert(0, d)
    from yaml_light import load_file
    return load_file


def load_case_dicts(cases_dir):
    """读 cases/*.yml → [case_dict]，每个 dict 附带 _file 域名。"""
    load_file = _yaml()
    cases = []
    for fn in sorted(os.listdir(cases_dir)):
        if not fn.endswith(".yml"):
            continue
        domain = fn[:-4]
        data = load_file(os.path.join(cases_dir, fn))
        for c in data.get("cases") or []:
            c = dict(c)
            c["_domain"] = domain
            cases.append(c)
    return cases


def filter_by_persona(cases, persona: str):
    """按归属 agent 过滤用例（issue #2855）。

    persona 字段取值：mibao / xiaobu / ""(缺省=双端)。
    - 跑 mibao 时：跳过 persona=="xiaobu" 的用例（C 端专属，B 端必挂）
    - 跑 xiaobu 时：跳过 persona=="mibao" 的用例（B 端专属，C 端必挂）
    - persona 为空/其它：双端都跑（向后兼容）
    """
    persona = (persona or "").strip().lower()
    if persona not in ("mibao", "xiaobu"):
        return list(cases)
    # 跑 mibao 排除 xiaobu 专属；跑 xiaobu 排除 mibao 专属；未标记(both)双端保留
    other = "xiaobu" if persona == "mibao" else "mibao"

    def _p(c):
        v = c.get("persona") if isinstance(c, dict) else getattr(c, "persona", "")
        return (v or "").strip().lower()

    return [c for c in cases if _p(c) != other]


# ── 期望断言 → 旧 eval 的字符串形态 ──

def exp_to_str(e):
    if isinstance(e, str):
        return e
    tool = e.get("tool", "")
    args = e.get("args") or {}
    if not args:
        return tool
    parts = []
    for k, v in args.items():
        if isinstance(v, list):
            parts.append(f"{k}=[{', '.join(str(x) for x in v)}]")
        else:
            parts.append(f"{k}={v}")
    return f"{tool}({', '.join(parts)})"


def _py_repr(s):
    if not isinstance(s, str):
        return repr(s)
    # 优先用双引号（eval 原文风格），含双引号时用单引号
    if '"' in s and "'" not in s:
        return "'" + s + "'"
    if "'" in s and '"' not in s:
        return '"' + s + '"'
    return repr(s)


def to_eval_py(cases):
    """cases → eval_cases.py 文本（与旧 eval_cases.py 同一导入面）。"""
    out = [GENERATED_HEADER, "",
           "from dataclasses import dataclass, field",
           "from typing import List, Optional",
           "from enum import Enum",
           "", "",
           "class Difficulty(Enum):",
           '    SMOKE = "smoke"       # 冒烟，必须 100% 通过',
           '    NORMAL = "normal"     # 正常流程',
           '    EDGE = "edge"         # 边缘情况',
           '    ADVERSARIAL = "adversarial"  # 对抗性，弱 LLM 可能挂',
           "", "",
           "class Skill(Enum):",
           '    PRODUCT = "product"',
           '    ORDER = "order"',
           '    AFTERSALES = "aftersales"',
           '    CUSTOMER = "customer"',
           '    CROSS = "cross"',
           '    MULTI_TURN = "multi_turn"',
           '    GENERAL = "general"',
           "", "",
           "@dataclass",
           "class EvalCase:",
           "    id: str",
           "    title: str",
           "    skill: Skill",
           "    difficulty: Difficulty",
           "    # 每轮可为 str（纯文本）或 dict（{text, images[]} 带图消息，issue #2794）",
           "    user_inputs: List[str]",
           "    expectations: List[str]",
           '    data_checks: List[str]',
           '    skip_reason: str = ""',
           '    legacy_id: str = ""',
           "    tags: List[str] = field(default_factory=list)",
           '    persona: str = ""   # 归属 agent: mibao / xiaobu / ""(双端)，issue #2855',
           '    order_before: List[str] = field(default_factory=list)   # 时序断言 "A before B"（跨轮，acceptance-protocol §3.1）',
           '    forbidden_text: List[str] = field(default_factory=list) # final_text 反模式词，命中即失败（§3.4 幻觉式撤回/报错文案）',
           '    forbidden_tools: List = field(default_factory=list) # 全程禁用工具断言（任何轮都不得调用；must_succeed 的镜像，issue #3544 收口批）',
            '    want_text: List[str] = field(default_factory=list) # final_text 正向关键词，全缺即失败（§3.4 正反关键词双轨）',
           '    required_args: List[dict] = field(default_factory=list) # 必填参数断言（create 缺 specifications/加工项价格即失败，§3.2）',
    '    forbidden_args: List[dict] = field(default_factory=list) # 禁止参数断言（隔离/越权下限：如物流工具不得接受快递单号，issue #3270）',
            '    must_succeed: List[dict] = field(default_factory=list) # 写工具成功断言（至少成功一次；"调了≠成了"，§3.2/issue #3361）',
            '    must_fail: List[dict] = field(default_factory=list) # 必须失败断言（零成功调用；must_succeed 的镜像，issue #3544 收口批）',
            '    amount_verify: List[dict] = field(default_factory=list) # 金额正确性断言（单价接地/小计/总额，§3.2/issue #3365）',
            '    db_verify: List[dict] = field(default_factory=list) # 落库层验证（创建后查 admin-api 断言价格=确认价，§3.2/issue #3056）',
            '    output_verify: List[dict] = field(default_factory=list) # 产出侧断言（工具计算结果 payload，如算料用布量/spec公式，issue #3367）',
            '    pre_clean: List[dict] = field(default_factory=list) # 评测前数据清理（写类 case 自我污染防线）',
            '    post_session: List[dict] = field(default_factory=list) # 会话关闭后落库断言（user_memories 只在 close 时 flush，issue #3357）',
           '    debug_user: str = ""   # 多身份评测：以哪个 DEBUG 顾客身份跑（如 debug_customer_new，issue #3391）',
           '    form_prefill: List[dict] = field(default_factory=list) # form 卡预填断言（老客户收货信息自动带出，issue #3397）',
           '    forbidden_card_text: List = field(default_factory=list) # 卡片内容反模式（卡里不得出现「用量/倍数」等把金额翻倍的框架，issue #3402）',
           '    namespaces: List[str] = field(default_factory=list) # 全局命名空间声明（<kind>:<值>，如 customer_phone:13800138000）；两条用例有交集 → 自动串行（issue #3781 并行污染隔离）',
           '    precondition: List[dict] = field(default_factory=list) # 运行期前置断言（order_count_for_phone：运行期间订单数不得增长；不成立则判「前置不成立」而非行为失败，issue #3781）',
            '    auto_fill: dict = field(default_factory=dict) # **用例级**表单载荷（全场可用）：让客户信息脱离轮次位置（issue #3804）',
           "", ""]

    for c in cases:
        cid = c.get("id", "")
        skill = SKILL_MAP.get(c.get("_domain", ""), "GENERAL")
        tier = TIER_MAP.get(c.get("tier", "normal"), "NORMAL")
        out.append(f"# ── {cid} [{tier}] {c.get('title', '')}（源: cases/{c.get('_domain')}.yml）──")
        out.append(f'_CASE_{c.get("id", "?").replace("-", "_")} = EvalCase(')
        out.append(f"    id={_py_repr(cid)},")
        out.append(f"    legacy_id={_py_repr(c.get('legacy_id', ''))},")
        out.append(f"    title={_py_repr(c.get('title', ''))},")
        out.append(f"    skill=Skill.{skill},")
        out.append(f"    difficulty=Difficulty.{tier},")
        out.append(f"    user_inputs={c.get('user_inputs') or []!r},")
        exps = [exp_to_str(e) for e in (c.get("expectations") or [])]
        out.append(f"    expectations={exps!r},")
        out.append(f"    data_checks={c.get('data_checks') or []!r},")
        out.append(f"    skip_reason={_py_repr(c.get('skip_reason', ''))},")
        out.append(f"    tags={c.get('tags') or []!r},")
        out.append(f"    persona={_py_repr(c.get('persona', ''))},")
        # 多身份评测（issue #3391）：C 端 case 可声明以哪个 debug 用户身份跑
        out.append(f"    debug_user={_py_repr(c.get('debug_user', ''))},")
        out.append(f"    form_prefill={_py_repr(c.get('form_prefill') or [])},")
        out.append(f"    forbidden_card_text={_py_repr(c.get('forbidden_card_text') or [])},")
        if c.get("order_before"):
            out.append(f"    order_before={c.get('order_before')!r},")
        if c.get("forbidden_text"):
            out.append(f"    forbidden_text={c.get('forbidden_text')!r},")
        if c.get("forbidden_tools"):
            out.append(f"    forbidden_tools={c.get('forbidden_tools')!r},")
        if c.get("want_text"):
            out.append(f"    want_text={c.get('want_text')!r},")
        if c.get("required_args"):
            out.append(f"    required_args={c.get('required_args')!r},")
        if c.get("forbidden_args"):
            out.append(f"    forbidden_args={c.get('forbidden_args')!r},")
        if c.get("must_succeed"):
            out.append(f"    must_succeed={c.get('must_succeed')!r},")
        if c.get("must_fail"):
            out.append(f"    must_fail={c.get('must_fail')!r},")
        if c.get("amount_verify"):
            out.append(f"    amount_verify={c.get('amount_verify')!r},")
        if c.get("db_verify"):
            out.append(f"    db_verify={c.get('db_verify')!r},")
        if c.get("output_verify"):
            out.append(f"    output_verify={c.get('output_verify')!r},")
        if c.get("pre_clean"):
            out.append(f"    pre_clean={c.get('pre_clean')!r},")
        if c.get("post_session"):
            out.append(f"    post_session={c.get('post_session')!r},")
        # 全局命名空间声明 + 运行期前置断言（issue #3781）：只在声明时落字面量，
        # 未声明的用例走 dataclass 默认（缺省 = 不参与隔离/不设前置，保持既有行为不变）
        if c.get("namespaces"):
            out.append(f"    namespaces={c.get('namespaces')!r},")
        if c.get("precondition"):
            out.append(f"    precondition={c.get('precondition')!r},")
        # 用例级表单载荷（issue #3804）：只在声明时落字面量，未声明的用例走 dataclass 默认
        # （缺省 = 无 case 级载荷，行为与旧版逐字一致）
        if c.get("auto_fill"):
            out.append(f"    auto_fill={c.get('auto_fill')!r},")
        out.append(")")
        out.append("")

    refs = ", ".join(f'_CASE_{c.get("id", "?").replace("-", "_")}' for c in cases)
    out.append("ALL_CASES = (")
    for c in cases:
        out.append(f"    _CASE_{c.get('id', '?').replace('-', '_')},")
    out.append(")")
    out.append("")
    out.append("def get_active_cases() -> List[EvalCase]:")
    out.append("    return [c for c in ALL_CASES if not c.skip_reason]")
    out.append("")
    out.append("def get_smoke_cases() -> List[EvalCase]:")
    out.append("    return [c for c in ALL_CASES if c.difficulty == Difficulty.SMOKE and not c.skip_reason]")
    out.append("")
    out.append("def get_adversarial_cases() -> List[EvalCase]:")
    out.append("    return [c for c in ALL_CASES if c.difficulty == Difficulty.ADVERSARIAL and not c.skip_reason]")
    out.append("")
    out.append("def print_summary():")
    out.append("    active = get_active_cases()")
    out.append('    print(f"评测用例总数: {len(active)} (跳过 {len(ALL_CASES) - len(active)})")')
    out.append('    print(f"  冒烟: {len(get_smoke_cases())}")')
    out.append('    print(f"  正常: {len([c for c in active if c.difficulty == Difficulty.NORMAL])}")')
    out.append('    print(f"  对抗: {len(get_adversarial_cases())}")')
    out.append('    for skill in Skill:')
    out.append('        cs = [c for c in active if c.skill == skill]')
    out.append("        if cs:")
    out.append('            print(f"\\n## {skill.value}")')
    out.append("            for c in cs:")
    out.append('                print(f"  [{c.difficulty.value.upper():4}] {c.id}: {c.title}")')
    out.append("")
    out.append('if __name__ == "__main__":')
    out.append("    print_summary()")
    return "\n".join(out) + "\n"


def to_md(cases):
    """cases → mibao-verification-cases.md 人读 casebook。"""
    by_domain = {}
    for c in cases:
        by_domain.setdefault(c["_domain"], []).append(c)

    lines = [
        "# 米宝 B端 全覆盖验证 Case（生成物）",
        "",
        "> ⚠️ 本文件由 `render_cases.py` 从 `cases/*.yml` 生成，禁止手改。",
        "> 单一源：`ershen/seed/migao/cases/`（部署副本 `.github/cases/`）。",
        "> 启动服务后按序执行；每轮 Case 独立。tier：🟢 smoke / 🔵 normal / 🔴 adversarial。",
        "",
    ]
    icons = {"smoke": "🟢", "normal": "🔵", "edge": "🟡", "adversarial": "🔴"}

    for domain in sorted(by_domain):
        lines.append(f"## {DOMAIN_TITLES.get(domain, domain)}（{len(by_domain[domain])} case）")
        lines.append("")
        for c in by_domain[domain]:
            icon = icons.get(c.get("tier", "normal"), "⚪")
            lines.append(f"### {c['id']}. {c['title']} {icon}")
            lines.append("```")
            for msg in c.get("user_inputs") or []:
                if isinstance(msg, dict):
                    _t = msg.get("text", "")
                    _imgs = msg.get("images") or []
                    # 语义化标注：这些 dict 轮是"协议轮"（harness 自动作答/换会话），
                    # 不是用户真说了什么——之前一律渲染成「[📷 纯图片 x0]」，
                    # 读文档的人会把自动作答误读成用户发了空图。
                    _tags = []
                    if msg.get("new_session"):
                        # 跨会话轮（issue #3357）：先关当前会话再开新会话（触发记忆 flush）
                        _tags.append("🔁 新会话")
                    if msg.get("auto_respond"):
                        _tags.append("🤖 按上一轮卡片作答")
                    if msg.get("auto_select"):
                        _tags.append("🤖 选第一个选项")
                    if msg.get("auto_fill"):
                        _tags.append("🤖 自动填表")
                    if msg.get("repeat_until"):
                        # repeat_until 轮也是「协议轮」：harness 每轮按"有卡答卡/被问验证码
                        # 就供码/否则发 fallback"作答，直到目标工具成功（issue #3538）。
                        # 此前无 text 且无上述标签 → 渲染成「你: (空)」，casebook 读不出
                        # 这轮在干什么（OR-021/CH-033/PR-016/PR-021 均此形态）。
                        _ru = msg["repeat_until"] or {}
                        _tags.append(
                            f"🔁 按目标工具重复直至成功：{_ru.get('tool_called', '?')}"
                            f"，最多 {_ru.get('max', '?')} 次")
                    if _imgs:
                        _tags.append(f"📷 附 {len(_imgs)} 图")
                    suffix = (" [" + " ".join(_tags) + "]") if _tags else ""
                    lines.append(f"你: {_t}{suffix}" if _t else f"你: {suffix.strip() or '(空)'}")
                else:
                    lines.append(f"你: {msg}")
            for e in (c.get("expectations") or []):
                lines.append(f"期望: {exp_to_str(e)}")
            for d in (c.get("data_checks") or []):
                lines.append(f"数据: {d}")
            for ob in (c.get("order_before") or []):
                lines.append(f"时序: {ob}")
            for ft in (c.get("forbidden_text") or []):
                lines.append(f"禁词: {ft}")
            for ftl in (c.get("forbidden_tools") or []):
                _ftl_tool = ftl if isinstance(ftl, str) else (ftl or {}).get("tool")
                _ftl_act = "" if isinstance(ftl, str) else ((ftl or {}).get("action") or "")
                lines.append(f"全程禁用: {_ftl_tool}({_ftl_act})" if _ftl_act
                             else f"全程禁用: {_ftl_tool}")
            for wt in (c.get("want_text") or []):
                lines.append(f"必须: {wt}")
            for ra in (c.get("required_args") or []):
                lines.append(f"必填: {ra.get('tool')}({ra.get('action', '')}) 字段 {', '.join(ra.get('fields') or [])}")
            for fa in (c.get("forbidden_args") or []):
                lines.append(f"禁参: {fa.get('tool')}({fa.get('action', '')}) 不得含 {', '.join(fa.get('fields') or [])}")
            for ms in (c.get("must_succeed") or []):
                _ms_tool = ms if isinstance(ms, str) else ms.get("tool")
                _ms_act = "" if isinstance(ms, str) else (ms.get("action") or "")
                lines.append(f"必须成功: {_ms_tool}({_ms_act})" if _ms_act else f"必须成功: {_ms_tool}")
            for mf in (c.get("must_fail") or []):
                _mf_tool = mf if isinstance(mf, str) else mf.get("tool")
                _mf_act = "" if isinstance(mf, str) else (mf.get("action") or "")
                _mf_head = f"必须失败: {_mf_tool}({_mf_act})" if _mf_act else f"必须失败: {_mf_tool}"
                # `args` 值级作用域（issue #3689 / #3702）：只印 `工具(action)` 会让人读账本
                # （mibao-verification-cases.md）**看不到到底在匹配什么值** —— 账本失真。
                # 风格与同函数的 `必填: … 字段 …` / `禁参: … 不得含 …` 一致（限定词接在同行）。
                _mf_scope = ", ".join(
                    f"{k}={v}" for k, v in ((mf.get("args") or {}) if isinstance(mf, dict) else {}).items())
                lines.append(f"{_mf_head} 值级作用域: {_mf_scope}" if _mf_scope else _mf_head)
            for av in (c.get("amount_verify") or []):
                lines.append(f"金额: {av.get('tool', 'order_create')} 「{av.get('product_name', '')}」 → {'; '.join(av.get('checks') or [])}")
            for dv in (c.get("db_verify") or []):
                # 结构化核对器（无 checks 串，如 after_sales_ticket #3544）也要可读：
                # 否则 casebook 只剩 "fetch None → "，新断言在文档里完全不可见。
                _dv_parts = dv.get("checks")
                if not _dv_parts:
                    _dv_parts = [f"{k}={v}" for k, v in dv.items() if k != "fetch"]
                _dv_head = f" {dv['name']}" if dv.get("name") else ""
                lines.append(f"落库: {dv.get('fetch')}{_dv_head} → {'; '.join(map(str, _dv_parts))}")
            for ov in (c.get("output_verify") or []):
                # 产出侧断言（#3544：PP-006/PR-021 假绿升级用的就是它）此前未渲染 → 补齐；
                # action 一并渲染：多 action 工具的作用域是这条断言的关键信息（漏读会误判）
                _ov_exp = "; ".join(f"{k}=={v}" for k, v in (ov.get("expect") or {}).items())
                _ov_act = f"({ov['action']})" if ov.get("action") else ""
                lines.append(f"产出: {ov.get('tool')}{_ov_act} → {_ov_exp}")
            for ps in (c.get("post_session") or []):
                lines.append(f"会话后: {ps.get('fetch')}({ps.get('agent_type', 'xiaobu')}) → {'; '.join(ps.get('checks') or [])}")
            if c.get("auto_fill"):
                # 用例级载荷（issue #3804）：读 casebook 的人必须知道"顾客信息全场可用"，
                # 否则会以为载荷只挂在某几轮（旧形态的位置依赖正是红/绿由发卡时机决定的根因）
                _af = ", ".join(f"{k}={v}" for k, v in c["auto_fill"].items())
                lines.append(f"载荷(全场可用): {_af}")
            if c.get("skip_reason"):
                lines.append(f"跳过: {c['skip_reason']}")
            lines.append("```")
            if c.get("truths_ref"):
                lines.append(f"真值: {', '.join(c['truths_ref'])}")
            elif c.get("merge_log") and "缺口" in str(c.get("merge_log", "")):
                lines.append("真值: ⚠️ 缺口（见对应模板 ⚠️ 注释）")
            lines.append(f"溯源: {c.get('merge_log', '')} ｜ tags: {', '.join(c.get('tags') or [])}")
            lines.append("")

    # 覆盖统计
    from collections import Counter
    tier_cnt = Counter(c.get("tier", "normal") for c in cases)
    active = [c for c in cases if not c.get("skip_reason")]
    lines.append("---")
    lines.append("")
    lines.append("## 覆盖统计（生成）")
    lines.append("")
    lines.append(f"- 用例总数：{len(cases)}（活跃 {len(active)}，跳过 {len(cases) - len(active)}）")
    lines.append(f"- tier 分布：smoke {tier_cnt.get('smoke', 0)} / normal {tier_cnt.get('normal', 0)} / adversarial {tier_cnt.get('adversarial', 0)}")
    for domain in sorted(by_domain):
        lines.append(f"- {DOMAIN_TITLES.get(domain, domain)}：{len(by_domain[domain])}")
    gaps = [c for c in cases if not c.get("truths_ref")]
    if gaps:
        lines.append("")
        lines.append("### 真值缺口用例（truths_ref 为空，已在模板 ⚠️ 注释标注）")
        for c in gaps:
            lines.append(f"- {c['id']}: {c.get('title', '')}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description="case-contract 渲染器（YAML → eval_cases.py + casebook）")
    p.add_argument("--cases", required=True, help="用例库目录（cases/*.yml）")
    p.add_argument("--out-eval", required=True, help="eval_cases.py 输出路径")
    p.add_argument("--out-md", required=True, help="mibao-verification-cases.md 输出路径")
    args = p.parse_args(argv)

    cases = load_case_dicts(args.cases)
    if not cases:
        print(f"❌ {args.cases} 下无用例文件", file=sys.stderr)
        return 1

    py = to_eval_py(cases)
    with open(args.out_eval, "w", encoding="utf-8") as f:
        f.write(py)
    print(f"✓ eval_cases.py → {args.out_eval}（{len(cases)} 条）")

    md = to_md(cases)
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✓ casebook → {args.out_md}（{len(cases)} 条）")

    # 自检：生成物可导入（防渲染出语法错误）
    ns = {}
    exec(compile(py, "<generated eval_cases.py>", "exec"), ns)
    assert len(ns["ALL_CASES"]) == len(cases), "ALL_CASES 数量与源不一致"
    assert ns["get_smoke_cases"]() and ns["get_adversarial_cases"](), "冒烟/对抗子集为空"
    print(f"✓ 生成物自检通过（ALL_CASES={len(ns['ALL_CASES'])}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
