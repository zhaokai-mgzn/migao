# case_ids: PR-013, OR-017, CH-010
"""C 端能力覆盖守卫（issue #3367）。

为什么需要：C 端评测面此前是**手工维护**的 18 条用例 —— 能力加了、用例没加，
没有任何机制会发现。实证：`curtain_calc`（算料报价，布艺行业核心能力）的用例
PR-013 被写成**不带 persona 的 B 端档位** + skip_reason 挂起 → C 端该能力
**零覆盖**（只有单测覆盖公式，没有真实 LLM 链路证据），而 CI 一片绿。

本守卫把「C 端 skill 的工具全集」与「C 端用例的断言」对齐：
**任何 C 端工具若没有任何用例断言它，就报红** —— 要么补用例，要么显式登记进
`INTERNAL_NO_CASE`（并写清为什么不需要链路级用例）。

工具全集**从源码解析**（不 import app.*：本目录是零依赖测试，CI 的
unit_ci_workflows job 只装了 pytest+pyyaml；app 侧依赖 langchain 装不上）。
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))   # 复用运行器的选择语义

from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
SKILLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"

# C 端（小布）skill 的工具常量 —— 新增 C 端 skill 时必须登记到这里，
# 否则它的工具不会被本守卫纳入（这是有意的：新增能力面要显式过一次评审）。
CUSTOMER_SKILL_TOOL_CONSTS = (
    "CUSTOMER_ORDER_TOOLS",
    "CUSTOMER_AFTERSALES_TOOLS",
    "CUSTOMER_GENERAL_TOOLS",
    "CUSTOMER_KNOWLEDGE_TOOLS",
    "CUSTOMER_PRODUCT_TOOLS",
    "CUSTOMER_QUOTE_TOOLS",
)

# 允许"没有链路级用例断言"的工具：必须逐条写明理由（这道门是防遗忘，不是防写用例）
# 目前**为空**（issue #3397）：原先豁免的两个工具已由 OR-023 真实断言 ——
#   · `customer_address_query`：老客户收货信息自动带出（预填体验本身就是顾客诉求）；
#   · `validate_input`：写前校验（confirm → validate_input → order_create 协议中的必需步骤）。
# 豁免名单会**掩盖回归**（工具失去用例断言时不会报红），故覆盖到位后立即清空；
# 将来确实无独立业务语义的工具才登记，并写明理由。
INTERNAL_NO_CASE: dict = {}


# ── 共享层守卫的**分端声明**（issue #3404 人工提醒固化）────────────────────────
# 背景：B 端（米宝/客服）与 C 端（小布）共用同一个 `base_skill.py` —— 两端卡片由同一个
# `interact` 工具产出。若 C 端语义守卫不声明分端，就会误伤 B 端（实测：数量口径守卫会拦
# B 端店员代客下单的"用量"选项、预填守卫会拦客服改客户资料的表单）。
# 规则：`base_skill.py` 里每个 `*_block` 拦截守卫**必须二选一**：
#   ① 声明分端（函数体内调用 `_is_customer_role`）—— C 端语义守卫；
#   ② 登记进 `UNIVERSAL_BLOCK_GUARDS` 并写明理由 —— 通用数据/协议完整性守卫（两端都该生效）。
# 这样"新加守卫忘了分端"会在 PR 阶段变红，而不是等到 B 端出问题才发现。
UNIVERSAL_BLOCK_GUARDS = {
    "_write_input_recovery_block":
        "缺参等待期拦的是'注定失败的重复写'，与端无关：B 端同样不该在欠参时反复重发确认卡",
    "_card_loop_block":
        "同一张卡重复下发是两端共有的循环缺陷（内容指纹已按实质内容判定）",
    "_masked_phone_write_block":
        "掩码/填充手机号写库是数据完整性缺陷：B 端顾客的号码写错同样是错",
}


# 写工具（有副作用的）：断言它们就必须同时断言成功，否则"调了≠成了"的假绿会重现
WRITE_TOOLS = frozenset({
    "order_create", "aftersale_create", "human_handoff",
    "product_update", "order_update", "customer_update",
})


def _customer_tools() -> set:
    tools: set = set()
    for path in sorted(SKILLS_DIR.glob("customer*.py")):
        src = path.read_text(encoding="utf-8")
        for const in CUSTOMER_SKILL_TOOL_CONSTS:
            m = re.search(re.escape(const) + r"\s*=\s*\[(.*?)\]", src, re.S)
            if m:
                tools.update(re.findall(r'"([a-z_]+)"', m.group(1)))
    return tools


def _all_tool_constants() -> set:
    """全部 skill（含 B 端）的工具常量并集 —— 断言词汇表的工具部分。"""
    tools: set = set()
    for path in sorted(SKILLS_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"([A-Z_]+_TOOLS)\s*=\s*\[(.*?)\]", src, re.S):
            tools.update(re.findall(r'"([a-z_]+)"', m.group(2)))
    return tools


def _asserted_tools(case: dict) -> set:
    """用例断言到的工具名（expectations / must_succeed / order_before）。

    **按已知工具全集做词匹配**，而不是解析 YAML 结构 —— 首版用
    `re.match(r"\s*([a-z_]+)", entry)` 取首词，结果 `yaml_light` 把 `expectations`
    里的块状条目读成**多行原始字符串**（`'- tool: human_handoff\n    data_checks:…'`），
    首词落到 `send`/`create` 上 → `writes` 恒为空 → **守卫恒绿（假守卫，M84 变异实证）**。
    改法：拿工具全集去文本里找词边界命中，对 dict/字符串/多行块都成立。
    """
    known = _customer_tools()
    out = set()

    def scan(entry):
        if isinstance(entry, dict):
            t = entry.get("tool")
            if t:
                out.add(str(t))
            return
        text = str(entry)
        for name in known:
            if re.search(r"(?<![a-z_])" + re.escape(name) + r"(?![a-z_])", text):
                out.add(name)

    for e in case.get("expectations") or []:
        scan(e)
    for key in ("must_succeed", "required_args", "forbidden_args"):
        for e in case.get(key) or []:
            scan(e)
    for spec in case.get("order_before") or []:
        scan(spec)
    return out


class TestXiaobuCapabilityCoverage:
    def _measured_cases(self) -> list:
        """**运行器真正会跑**的 C 端集合（normal 档 = 每日回归）。

        为什么不能用 `persona == xiaobu` 了事（issue #3367 覆盖审计踩到）：
          - `skip_reason` 非空的不跑（CH-030/031/032 就是被 skip 的纯前端用例）；
          - smoke 档在 CI 里**没人跑**（xiaobu-acceptance 派发的是 normal）
            → 只看 persona 会把"从不执行的用例"算成覆盖，得出"已覆盖"的假结论；
          - 双端用例只要期望工具都在小布能力集内也会被选进来（select_cases_for_persona）。
        这里直接复用运行器的选择语义，保证"覆盖统计的面 = 真正被测的面"。
        """
        from eval_case_filter import select_cases_for_persona
        sel = select_cases_for_persona(load_case_dicts(str(CASES_DIR)), "xiaobu")
        return [c for c in sel if str(c.get("tier") or "").strip().lower() == "normal"]

    def _xiaobu_asserted(self) -> set:
        out = set()
        for c in self._measured_cases():
            out |= _asserted_tools(c)
        return out

    def test_every_customer_tool_is_covered_or_justified(self):
        tools = _customer_tools()
        assert len(tools) >= 10, f"C 端工具解析异常（只解析到 {len(tools)} 个）：{sorted(tools)}"
        measured = self._measured_cases()
        assert len(measured) >= 15, f"C 端 normal 档只剩 {len(measured)} 条，选择语义可能坏了"
        asserted = self._xiaobu_asserted()
        uncovered = sorted(t for t in tools if t not in asserted and t not in INTERNAL_NO_CASE)
        assert not uncovered, (
            "以下 C 端能力在评测里零覆盖（补用例，或登记进 INTERNAL_NO_CASE 并写明理由）：\n  "
            + "\n  ".join(f"{t}" for t in uncovered)
        )

    def test_internal_allowlist_entries_are_real_tools(self):
        """豁免表不能挂空名（防"改名后豁免悄悄失效"）—— 要么是真实工具，要么删掉。"""
        tools = _customer_tools()
        stale = sorted(t for t in INTERNAL_NO_CASE if t not in tools)
        assert not stale, f"INTERNAL_NO_CASE 里的 {stale} 已不是 C 端工具，应删除"

    def test_expectations_resolve_to_known_vocabulary(self):
        """断言必须落在**已知词汇表**里，否则就是一条"死断言"（issue #3367）。

        为什么需要：`yaml_light` 是手写解析器，缩进/换行写坏时**不会报错**，只会把
        `- tool: human_handoff` 与后面一行粘成一个值（本轮实测：手工变异把 YAML 弄坏后
        解析成 `{'tool': 'human_handoff    data_checks:'}`，工具名对不上任何真实工具）。
        这类"解析悄悄坏掉"的危害是双向的：既可能让用例恒红（把解析问题报成 Agent 能力问题），
        也可能让覆盖率统计失真（本轮我就先被它骗过一次）。
        词汇表 = 工具全集 + 语义 token；支持 `A or B` 与 `tool(args=…)` 形态。
        """
        known = _customer_tools() | _all_tool_constants()
        # 评测器支持的语义 token（见 local_runner.check_expectation）：
        #   direct_reply → 该轮无工具调用且有文本；success=true → 该轮无 error
        semantic = {"direct_reply", "success"}
        bad = []
        for c in self._measured_cases():
            for key in ("expectations", "must_succeed"):
                for e in c.get(key) or []:
                    text = e.get("tool") if isinstance(e, dict) else str(e)
                    if not text:
                        bad.append(f"{c['id']}.{key}: 空条目")
                        continue
                    for part in re.split(r"\s+or\s+", str(text)):
                        token = re.match(r"\s*([a-z_]+)", part.strip())
                        name = token.group(1) if token else ""
                        if name in known or name in semantic:
                            continue
                        bad.append(f"{c['id']}.{key}: 无法解析出已知断言 {str(e)[:60]!r}")
        assert not bad, (
            "以下断言不在已知词汇表里（YAML 可能写坏，或用了新 token 却没登记）：\n  "
            + "\n  ".join(bad)
        )

    def test_write_tool_cases_assert_success(self):
        """C 端写用例必须同时断言**写成功**（issue #3367 覆盖审计）。

        「调了」≠「成了」：只断言工具名时，返回 success=false / tool_not_found 也判绿。
        issue #3361 已在 order_create 上实证（tool_not_found 而用例 100%）。
        本次审计发现 **5 条 human_handoff 用例**（C 端最大能力族：转人工）全部缺成功断言 ——
        而它们的业务价值（工作台可见/可回复、AI 上下文透传）完全建立在会话真的落库之上。
        """
        missing = []
        for c in self._measured_cases():
            writes = _asserted_tools(c) & WRITE_TOOLS
            if not writes:
                continue
            ok = set()
            for e in c.get("must_succeed") or []:
                t = e.get("tool") if isinstance(e, dict) else str(e)
                if t:
                    ok.add(t)
            for t in sorted(writes):
                if t not in ok:
                    missing.append(f"{c['id']} 断言了 {t} 但没有 must_succeed")
        assert not missing, (
            "以下 C 端写用例只有'调了'没有'成了'（补 must_succeed）：\n  " + "\n  ".join(missing)
        )

    def test_curtain_calc_is_covered(self):
        """算料报价是布艺行业核心能力，必须有链路级用例（issue #3367 的实证缺口）。"""
        assert "curtain_calc" in self._xiaobu_asserted(), (
            "curtain_calc 又变成零覆盖了（PR-013 的 persona: xiaobu 是否被误删？）"
        )


class TestSharedGuardPersonaScope:
    """共享层守卫必须**显式声明分端**（issue #3404 人工提醒固化）。

    B/C 两端共用 `base_skill.py`：两端卡片由同一个 `interact` 工具产出。C 端语义守卫
    若不声明分端就会误伤 B 端（实测：数量口径守卫拦 B 端店员代客下单的"用量"选项、
    预填守卫拦客服改客户资料的表单）。本守卫把"分端"从"记得写"变成"**必须写**"。
    """

    SKILL_SRC = SKILLS_DIR / "base_skill.py"

    def _block_guards(self):
        """源码里所有**拦截守卫入口**（函数名以 `_block` 结尾）的函数名 + 函数体。

        ⚠️ 两点口径（都是被自己的守卫抓出来后固化的）：
          · 签名**可能跨行**（本项目守卫参数较长）——首版正则要求 `):` 同行，
            导致一个都没解析出来（"未解析到"断言抓到了这个空转风险）；
          · 只认**以 `_block` 结尾**的入口函数（`_quantity_choice_block` 等）；
            像 `_masked_phone_block_result` 这类**响应构造函数**不是"决定是否拦"的地方，
            不纳入分端声明（首版宽匹配把它也抓进来了，属口径不准）。
        """
        src = self.SKILL_SRC.read_text(encoding="utf-8")
        guards = {}
        for m in re.finditer(r"^(?:async )?def (_\w*_block)\(", src, re.M):
            name = m.group(1)
            # 从签名起找到第一个以 ':' 结尾的行（跳过跨行的参数列表）
            i = src.find("\n", m.end())
            if i < 0:
                continue
            while i >= 0 and not src[m.end():i].rstrip().endswith(":"):
                i = src.find("\n", i + 1)
            if i < 0:
                continue
            body_start = i + 1
            nxt = re.search(r"^(?:async )?def |^class ", src[body_start:], re.M)
            body = src[body_start: body_start + (nxt.start() if nxt else len(src))]
            guards[name] = body
        return guards

    def test_every_block_guard_declares_scope(self):
        guards = self._block_guards()
        assert guards, "未解析到任何 *_block 守卫 —— 解析口径已漂移，本守卫会空转通过"
        missing = []
        for name, body in guards.items():
            if "_is_customer_role(" in body:
                continue
            if name in UNIVERSAL_BLOCK_GUARDS:
                continue
            missing.append(name)
        assert not missing, (
            "以下拦截守卫既没声明 C 端分端（`_is_customer_role`），也未登记为通用守卫：\n  "
            + "\n  ".join(missing)
            + "\n\nB/C 共用 base_skill —— 不分端会误伤对方。请在函数体内加：\n"
              "    if not _is_customer_role(state):\n        return None\n"
              "或登记进 UNIVERSAL_BLOCK_GUARDS 并写明理由（通用数据/协议完整性）。")

    def test_universal_allowlist_entries_are_real_and_justified(self):
        guards = self._block_guards()
        for name, reason in UNIVERSAL_BLOCK_GUARDS.items():
            assert name in guards, f"UNIVERSAL_BLOCK_GUARDS 里的 {name} 已不存在（陈旧登记）"
            assert len(str(reason)) >= 12, f"{name} 的通用理由过于简略，需说明为何两端都该拦"
        # C 端语义守卫必须真的用了统一助手（防各写一套角色判断）
        for name in ("_quantity_choice_block", "_form_prefill_fidelity_block",
                     "_curtain_calc_dimension_block"):
            assert name in guards, f"{name} 不存在（改名后需同步本守卫）"
            assert "_is_customer_role(" in guards[name], f"{name} 未声明分端"


# 需要"确认卡先行"的 C 端写工具（有副作用的写：顾客必须先看到明细卡再落库）
CONFIRM_FIRST_WRITE_TOOLS = ("order_create", "aftersale_create")


class TestWriteCasesAssertConfirmCardFirst:
    """C 端**写用例**必须断言「confirm 卡先行」（issue #3414 人工验收实证）。

    背景（run 34760653981，验收 C-A1 唯一违规）：`❌ [L1] 期望出现 confirm 卡片，实际没有`
    —— 顾客只发了一句「确认下单」，订单就被创建了；顾客**没看到明细卡**。
    而评测档当时看不见这条要求：10 条 C 端下单用例里只有 CH-010 断言了
    `interact[confirm] before order_create`。

    `order_before` 的语义（`check_order_before`）：**A 必须出现过**，且首次出现早于 B ——
    正好表达"顾客先看到明细卡、之后才落库"。故：凡是 `must_succeed` 了写工具的 C 端用例，
    都必须声明对应的 confirm 卡先行断言（否则这条产品要求就没人守）。

    ⚠️ 只认 `must_succeed`（**要求写成**的用例）；像 DF-020~023 那种把
    `order_create 未被调用` 写进 expectations 的**对抗用例**不在此列（那里根本不该有卡）。
    """

    def _xiaobu_cases(self):
        return [c for c in load_case_dicts(str(CASES_DIR))
                if (c.get("persona") or "").strip() == "xiaobu"]

    def _must_succeed_tools(self, case):
        out = []
        for spec in case.get("must_succeed") or []:
            if isinstance(spec, dict) and spec.get("tool"):
                out.append(str(spec["tool"]))
            elif isinstance(spec, str):
                out.append(spec)
        return out

    def test_every_xiaobu_write_case_asserts_confirm_card_first(self):
        missing = []
        for c in self._xiaobu_cases():
            for tool in self._must_succeed_tools(c):
                if tool not in CONFIRM_FIRST_WRITE_TOOLS:
                    continue
                ob = [str(x) for x in (c.get("order_before") or [])]
                want = f"interact[confirm] before {tool}"
                if not any(want in x for x in ob):
                    missing.append(f"{c['id']}: 缺 order_before「{want}」")
        assert not missing, (
            "以下 C 端写用例没有断言「confirm 卡先行」—— 顾客可能在没看到明细卡的情况下被下单：\n  "
            + "\n  ".join(missing)
            + "\n\n请补 `order_before: [\"interact[confirm] before <写工具>\"]`"
              "（product 要求见 customer_order_skill 第 4 步：validate_input → interact(confirm)）。")

    def test_current_backfill_is_complete(self):
        """回归网：至少这些用例已补（防止有人在批量编辑中把断言删掉）。"""
        by_id = {c["id"]: c for c in self._xiaobu_cases()}
        for cid in ("CH-010", "OR-017", "OR-018", "OR-019", "OR-020",
                    "OR-021", "OR-022", "OR-023", "OR-024"):
            ob = [str(x) for x in (by_id[cid].get("order_before") or [])]
            assert any("interact[confirm] before order_create" in x for x in ob), \
                f"{cid} 的 confirm 卡先行断言被删了"
