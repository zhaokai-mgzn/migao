"""跨轮注入块族（`system_prompt` 里那几段「拦下 → 回放真值 → 告诉模型怎么改」）的单一真值源。

从 `base_skill.py` 搬出，issue #8725。

## 单一职责

每个函数都是**同一个形状**：`async def X_block(tool_name, args, tool_call, session_id, skill_name, …)`
→ 命中则返回 `(tool_call, result_str, result_dict)` 三元组（拦下并回放真值），否则 `None`（放行）。
六段：用量/褶皱倍数（`_quantity_choice_block`）· 表单预填保真（`_form_prefill_fidelity_block`）·
掩码手机号写入（`_masked_phone_write_block`）· 写工具缺参恢复（`_write_input_recovery_block`）·
卡片循环（`_card_loop_block`）· 以及它们在 `system_prompt` 侧的装配（`_inject_write_input_recovery`）。

另有三个**共用小件**：`_accepted_param_names` / `user_supplied_param` / `RECOGNIZABLE_INPUT_PARAMS`（缺参识别）、
`card_fingerprint`（卡片指纹，判「同一张卡重发」）、`_PREFILL_FIDELITY_FIELDS` / `_QUANTITY_*`（词表）。

## 依赖方向（单向）

```text
base_skill.py ──(re-export)──▶ injection_blocks.py ──(顶层 import)──▶ phone_masking.py
```

`extract_sms_code` 仍定义在 `base_skill.py`（`_remember_sms_code` 与它同族）⇒ 本模块**调用期**取，
不写成模块顶层 import（那会 `base_skill → 本模块 → base_skill` 的**加载期**成环）。

## ⚠️ patch 缝：`logger` 调用期绑定（同 `order_flow_guard.py`，见该文件说明）

## 搬运纪律

函数体是原 `base_skill.py` 对应行的**逐字副本**（`ast` 边界切片），唯一机械改动 = 2 行 patch 前导
（外加 `user_supplied_param` 里取 `extract_sms_code` 的那行调用期 import）。
"""
import json

from app.graph.skills.phone_masking import (
    KNOWN_ADDRESS_KEY, KNOWN_RAW_PHONES_KEY,
    _is_customer_role, _is_mask_shaped, _known_raw_phones, _norm_ws, _phone_args,
    mask_variants, raw_phones_in,
)


def _accepted_param_names(tool) -> frozenset | None:
    """工具 execute() 接受的参数名集合；None = 接受任意参数（**kwargs）或无法反射。

    为什么需要（issue #3361，CI 实证 run 34703192730）：
        [tool-exec] order_create ERROR: OrderCreateTool.execute() got an unexpected
        keyword argument 'action'
    LLM 会把**别家工具的字段**顺手带过来（`aftersale_create` / `after_sales_manage`
    都有 `action`，而 `order_create` 没有）→ TypeError → tool_execution_failed →
    模型重试两次才成功（CH-010/OR-014 抖动的真因，单条用例白跑 200-400s）。
    参数被 schema 挡住却仍被传，属"模型层幻觉参数"，代码层拦掉并留警告是唯一稳的解法。
    """
    import inspect as _inspect
    cached = getattr(_accepted_param_names, "_cache", None)
    if cached is None:
        cached = _accepted_param_names._cache = {}
    # 缓存键用"模块+限定名"：仅用类名时，测试里同名替身/同名内部类会互相串味
    # （实测：两个测试各自定义的 class T 共享缓存 → 参数被误丢弃）
    key = f"{type(tool).__module__}.{type(tool).__qualname__}"
    if key in cached:
        return cached[key]
    names = None
    try:
        sig = _inspect.signature(tool.execute)
        accepted = set()
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            if param.kind is _inspect.Parameter.VAR_KEYWORD:
                names = None          # 有 **kwargs → 不做净化
                break
            if param.kind in (_inspect.Parameter.POSITIONAL_OR_KEYWORD,
                              _inspect.Parameter.KEYWORD_ONLY):
                accepted.add(name)
        else:
            accepted.discard("context")   # context 由调用方单独传
            names = frozenset(accepted)
    except (TypeError, ValueError):
        names = None
    cached[key] = names
    return names


# ── 写工具「缺参等待期」恢复回路（issue #3365，OR-017 CI 实证）──────────────
# 为什么必须有：写工具因**顾客还没给某个参数**而失败后，模型会原样重发确认卡并重复调用
# 注定失败的工具 —— 顾客点多少次「确认」都拿不到那句"请输入验证码"，生产环境里人也会卡死。
# CI run 34716531345（OR-017）轨迹即此形：R7「确认下单」→ order_create!缺少短信验证码
# → R8「确认」又一张一模一样的 confirm 卡 + 同一条错误 → R9「123456」被这张卡吃掉
# （harness 优先答卡）→ `确认死循环: confirm 卡共出现 3 次未收敛`。
# 修法与 handoff_blocked_inflight 同族：跨轮记账 + 不放行注定失败的调用 + 禁止重发同一张卡。
WRITE_INPUT_ERROR_KEY = "last_write_input_error"

# 「缺哪个参数」从**结构化字段** `ToolResult.missing_params` 来（issue #4080 T3）。
# 这里曾有一张「中文错误原文 → 参数名」的子串表 + `missing_input_param()`（`key in text`）：
# 它的唯一生产者是 `app/tools/order_create.py` 的 4 个失败点，而**错误文案改一个字**
# （"缺少"→"未提供"）判据就静默失效、且不会有任何东西变红（R5 明令禁止的形态）。
# 现在：生产者直接带 `missing_params`（+ `base.BaseTool.validate_args` 的契约失败也带），
# 消费端（本文件 2 处 + `execution/react_turn.py` 1 处）只读结构化字段 —— 表**删除**，
# 基线 4 条 → 0（R4：只许缩短，不得扩容）。
_INPUT_PARAM_LABELS: dict = {
    "sms_code": "短信验证码（4-6 位数字）",
    "items": "商品明细（名称、数量、单价）",
}


def user_supplied_param(param: str, user_msg: str) -> bool:
    """顾客这一轮的消息是否**已经补上了**所缺参数。

    只有能可靠判定的参数才返回 True（验证码：整条就是 4-6 位数字）；未知参数一律 False
    → 宁可少拦（多问一句），也不能误判成"已补齐"而放行注定失败的写调用。
    """

    from app.graph.skills.base_skill import extract_sms_code  # 调用期取，避开加载期成环
    if param == "sms_code":
        return bool(extract_sms_code(user_msg or ""))
    return False


# 只有**能从顾客单条消息可靠判定"已补齐"**的参数才允许进入等待期拦截。
# 反例：`缺少商品明细`（items）无法从一句话判断补齐与否 —— 一旦记账就会把该工具的后续
# 调用永久拦住（顾客说"就是刚才那款窗帘"也判不出来）→ 这类参数宁可不管。
RECOGNIZABLE_INPUT_PARAMS = frozenset({"sms_code"})


# ── 同一张交互卡反复下发（issue #3365，OR-017 CI 实证）──────────────────────
# 实证（run 34718498228，OR-017）：同一张「这款商品支持以下加工项，需要哪些呢？」choice 卡
# 连发 **5 次**（R2-R6），顾客每次都把一模一样的答案回给它（「已选加工项：打孔」）——
# 卡没变、答案没变、流程不前进。真人会以为系统坏了；harness 则把它读成"顾客又在答题"。
# 与确认卡同族：**同一张卡（同组件+同标题+同选项）下发第 3 次起拦下**，逼模型基于已有答案往前走。
# 为什么允许 2 次：一次正常下发 + 一次合理重问（顾客没答清/改口）是人机对话的正常形态。
CARD_EMIT_COUNTS_KEY = "card_emit_counts"
CARD_EMIT_LIMIT = 2


def card_fingerprint(args: dict) -> str:
    """交互卡指纹：组件 + 标题 + **选项标签**。

    为什么必须含选项：选项变了就是另一张卡（顾客换了商品/规格后重新确认），
    只按标题去重会把这种正常重发误拦（实测 CH-010 的加工项卡标题会变、OR-014 的选项会变）。
    """
    if not isinstance(args, dict):
        return ""
    comp = str(args.get("component") or "")
    if not comp:
        return ""
    # ── confirm 卡：按**内容**取指纹，不按标题措辞（issue #3397，CI 实证）──
    # 实测（run 34751749165，OR-023）：同一张确认卡被模型换了措辞重发
    # （`请确认订单信息` ×7 / `请确认您的订单信息` ×2）→ 按标题做指纹会当成两张不同的卡，
    # "同一张卡第 3 次起拦下"的守卫漏判 → 顾客被反复要求确认同一件事（确认死循环），
    # 写操作被拖着不落库。改按 **fields 内容**（商品/总价/收货信息…）取指纹后，
    # 「内容相同 = 同一张卡」与人的直觉一致；而**内容真变了**（改数量 3→4、总价变）
    # 就是合法的另一张卡，指纹不同、照常放行。
    if comp == "confirm":
        vals = []
        for f in (args.get("fields") or [])[:12]:
            if isinstance(f, dict):
                vals.append(f"{f.get('label')}={f.get('value')}")
        body = "、".join(vals)[:200]
        cv = str(args.get("confirmValue") or "")[:60]
        return f"confirm|{body}|{cv}" if body or cv else "confirm|"
    title = str(args.get("title") or "").strip()
    labels = []
    for opt in (args.get("options") or [])[:12]:
        if isinstance(opt, dict):
            labels.append(str(opt.get("label") or opt.get("value") or ""))
        else:
            labels.append(str(opt))
    return "|".join([comp, title, "、".join(labels)])[:200]


def _clear_write_input_error(full: dict) -> dict:
    out = dict(full or {})
    out.pop(WRITE_INPUT_ERROR_KEY, None)
    return out


# ── 收货信息表单预填必须**逐字保真**（issue #3397，实测 run 34750771576）──────────
# 实证：OR-023 老客户下单，库里地址 `浙江省杭州市西湖区文三路 1 号 1 幢 101 室`，
# 模型预填成 `浙江省杭州市西湖区文三路 100 号`（库里/会话里都没有这个地址）——
# 顾客若不逐字核对就提交，订单会寄到错地址；号码被改写（尤其掩码值回流）更严重
# （掩码号会静默写库，issue #3379/#3386 同族）。
# 判据：表单预填的收货字段，若会话里已有**已知真值**且与预填值不一致（忽略空白），
# 且该值**不是顾客本条消息自己给的** → 拦下并回放真值，逼模型逐字复制。
_PREFILL_FIDELITY_FIELDS = {
    "customer_address": (KNOWN_ADDRESS_KEY, "收货地址"),
    "customer_phone": (KNOWN_RAW_PHONES_KEY, "手机号"),
    "receiver_phone": (KNOWN_RAW_PHONES_KEY, "手机号"),
}


# ── 顾客已报购买数量时，禁止用"用量/褶皱倍数"再问一遍（issue #3402，C-A1 实证）──
# 实证（run 34753219595，主路径 C-A1）：
#   R4 用户「数量 3 米」→ Agent 发 `choice: 请选择窗帘用量 → 3米（¥528）| 6米（¥1056，推荐）`
# —— 顾客说的 3 米就是买 3 米布；Agent 当成窗宽按褶皱倍数算成 6 米，**还标为"推荐"**（2 倍钱）。
# 这张多余卡还每轮吃掉一次交互 → C-A1 的 repeat_until 用完仍未落单（order_create 未调用）。
# 同一个认知错误的**第三个出口**（工具层 #3395、入参层 #3394 已修），故在**产出层（卡片）**拦。
# 判据（保守，只在"确凿的多收钱形态"上触发）：
#   ① 顾客消息里报过**购买数量**（「数量 3 米」「买 2.5 米布」…，且不是"窗宽/窗高"语义）；
#   ② 卡片选项里出现该数量的 **≥2 倍**（2×/3×…，容差 1%）；
#   ③ 卡片标题或选项文字用了「用量 / 褶皱倍数 / 倍数」这类框架。
# 顾客自己要求加倍（「褶皱饱满一点」「用量加倍」）→ 放行。
_QUANTITY_FRAME_WORDS = ("用量", "褶皱倍数", "褶皱", "倍数", "用布量")
_QUANTITY_INTENT = r"(?:数量|买|要|购|来|下单|做)\s*([0-9]+(?:\.[0-9]+)?)\s*米"
_QUANTITY_PLAIN = r"([0-9]+(?:\.[0-9]+)?)\s*米(?:布)?"
_DIMENSION_SEMANTIC = ("窗宽", "窗高", "宽", "高", "门幅", "尺寸")


def _stated_purchase_quantities(messages) -> set:
    """顾客消息里明确报过的**购买数量**（米）。带尺寸语义的表述不算。"""
    import re as _re
    out: set = set()
    for m in messages or []:
        try:
            role = str(getattr(m, "type", "") or getattr(m, "role", ""))
            text = str(getattr(m, "content", "") or "")
        except Exception:
            continue
        if role not in ("human", "user") or not text:
            continue
        for pat in (_QUANTITY_INTENT,):
            for g in _re.findall(pat, text):
                try:
                    out.add(float(g))
                except (TypeError, ValueError):
                    pass
        # 无意图词但有「米布」：也算购买数量（"3 米布"）
        if "米布" in text:
            for g in _re.findall(_QUANTITY_PLAIN, text):
                try:
                    out.add(float(g))
                except (TypeError, ValueError):
                    pass
    return out


async def _quantity_choice_block(tool_name: str, args: dict, tool_call: dict,
                                 session_id: str, skill_name: str,
                                 state: dict | None = None):
    """用"用量/褶皱倍数"框架给出顾客所报数量的 ≥2 倍选项 → 拦下（3 元组），否则 None。"""

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    import re as _re
    if tool_name != "interact":
        return None
    # C 端专属守卫：判据是「**顾客**说『买 3 米』被当成窗宽」这条顾客语义
    # （B 端店员代客下单时给出"用量/褶皱"选项可能是合法业务动作）→ 只对 customer 生效。
    if not _is_customer_role(state):
        return None
    opts = (args or {}).get("options")
    if not isinstance(opts, list) or not opts:
        return None
    msgs = (state or {}).get("messages") or []
    stated = _stated_purchase_quantities(msgs)
    if not stated:
        return None
    title = str((args or {}).get("title") or "")
    texts = [title] + [
        f"{o.get('label') or ''} {o.get('value') or ''}" if isinstance(o, dict) else str(o)
        for o in opts
    ]
    joined = " ".join(texts)
    if not any(w in joined for w in _QUANTITY_FRAME_WORDS):
        return None
    # 顾客自己要求过加倍/褶皱饱满 → 放行
    for m in msgs:
        t = str(getattr(m, "content", "") or "")
        if any(k in t for k in ("加倍", "褶皱饱满", "要多一点", "用布量多点")):
            return None
    for text in texts:
        for g in _re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*米", text):
            try:
                v = float(g)
            except (TypeError, ValueError):
                continue
            for q in stated:
                if q <= 0:
                    continue
                for k in (2, 3, 4):
                    if abs(v - q * k) <= max(0.05, q * 0.01):
                        logger.warning(
                            f"[{skill_name}] 拦截「用量/褶皱」倍数选项 tool=interact "
                            f"stated={q} option={v} | session={session_id}")
                        code = "quantity_choice_pleat_multiple"
                        msg = (
                            f"顾客已经明确说了购买数量 **{q:g} 米**（这就是订单数量），"
                            f"你却在卡里给出 `{v:g} 米` 这个 **{k} 倍**选项并要求他选用量 —— "
                            f"顾客会以为要买 {v:g} 米（金额翻 {k} 倍），"
                            f"而且反复问已经回答过的事会让流程原地打转"
                            f"（实测 C-A1 因此耗尽轮数、订单没落成，issue #3402）。"
                            f"正确做法：**直接用 {q:g} 米继续**（面料单价 × {q:g} 米 = 金额），"
                            f"进入确认卡（`validate_input` → `interact(confirm)`）与短信验证码，"
                            f"不要再让他选用量/褶皱倍数。只有**顾客主动要求**加褶皱/加倍用量时才谈倍数。")
                        return (tool_call,
                                json.dumps({"success": False, "error": code, "message": msg},
                                           ensure_ascii=False),
                                {"success": False, "error": code, "message": msg})
    return None


async def _form_prefill_fidelity_block(tool_name: str, args: dict, tool_call: dict,
                                       session_id: str, skill_name: str,
                                       last_user_msg: str = "", state: dict | None = None):
    """form 预填值与已知真值不一致时拦下（返回 3 元组），否则放行（None）。"""

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    if tool_name != "interact":
        return None
    # C 端专属：守的是"顾客的收货信息预填"。B 端客服/商家改客户资料的表格
    # 同名 key（customer_phone/customer_address）语义不同 → 只对 customer 生效。
    if not _is_customer_role(state):
        return None
    if str((args or {}).get("component") or "") != "form":
        return None
    fields = (args or {}).get("formFields") or []
    if not isinstance(fields, list) or not fields:
        return None
    known: dict = {}
    if session_id:
        try:
            from app.memory.session_state_store import SessionStateStore
            full = await SessionStateStore().load(session_id) or {}
            for key, (store_key, _label) in _PREFILL_FIDELITY_FIELDS.items():
                vals = full.get(store_key) or []
                if isinstance(vals, (list, tuple, set)):
                    known[key] = [str(v) for v in vals if str(v)]
        except Exception:
            pass
    if not known:
        return None
    from app.utils.pii_mask import mask_pii as _mask
    last_user_norm = _norm_ws(last_user_msg)
    for f in fields:
        if not isinstance(f, dict):
            continue
        key = str(f.get("key") or "")
        if key not in _PREFILL_FIDELITY_FIELDS:
            continue
        val = str(f.get("value") or "")
        if not val.strip():
            continue
        truth_list = [v for v in (known.get(key) or []) if v]
        if not truth_list:
            continue
        got_norm = _norm_ws(val)
        if any(got_norm == _norm_ws(t) for t in truth_list):
            continue
        # 顾客本条消息自己给了这个值（合法新地址/新号码）→ 放行
        if got_norm and got_norm in last_user_norm:
            continue
        truth = truth_list[0]
        label = _PREFILL_FIDELITY_FIELDS[key][1]
        logger.warning(
            f"[{skill_name}] 拦截收货信息预填被改写 field={key} got={val[:24]!r} "
            f"truth={truth[:24]!r} | session={session_id}")
        msg = (
            f"`interact(form)` 里 `{label}` 的预填值 `{val}` 与会话中**已知的真实值**"
            f"`{truth}` 不一致 —— 预填值必须**逐字复制工具返回值**，不能自己改写"
            f"（地址被改写顾客会寄错地方；号码被改写/掩码化会静默写错订单）。"
            f"请用真值 `{label}={truth}` 重新下发这张表单；"
            f"若顾客刚刚给了新的{label}（本条消息里提到），则用顾客给的那个值。")
        code = "form_prefill_altered"
        return (tool_call, json.dumps({"success": False, "error": code, "message": msg},
                                      ensure_ascii=False),
                {"success": False, "error": code, "message": msg})
    return None


async def _masked_phone_write_block(tool_name: str, args: dict, tool_call: dict,
                                    session_id: str, skill_name: str,
                                    last_user_msg: str = "", state: dict | None = None):
    """写工具参数里是「掩码形态」手机号时拦下（返回 3 元组），否则放行（None）。"""
    pairs = _phone_args(args or {})
    if not pairs:
        return None
    known = await _known_raw_phones(session_id, state, last_user_msg) if session_id else \
        raw_phones_in(last_user_msg)
    # 顾客本人本轮明确给出的号码 = 权威来源（哪怕它长得像掩码变体也不拦）
    user_said = raw_phones_in(last_user_msg)
    for path, value in pairs:
        if _is_mask_shaped(value):
            raw = ""
            for k in known:
                if k[:3] == value[:3] and k[-4:] == value[-4:]:
                    raw = k
                    break
            return _masked_phone_block_result(
                tool_name, path, value, raw, session_id, skill_name,
                because="含掩码字符", tool_call=tool_call)
        if value in user_said:
            continue
        for k in known:
            if value in mask_variants(k):
                return _masked_phone_block_result(
                    tool_name, path, value, k, session_id, skill_name,
                    because=f"是本会话真实号码（{k}）的掩码填充形态",
                    tool_call=tool_call)
    return None


def _masked_phone_block_result(tool_name: str, path: str, value: str, known_raw: str,
                               session_id: str, skill_name: str, because: str,
                               tool_call: dict | None = None):
    """构造拦截返回值（3 元组：tool_call, result_str, result_dict）。"""

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    import json as _json
    if known_raw:
        tail = (f"顾客的真实号码是 **{known_raw}** —— 请直接用这个完整号码重新调用 "
                f"`{tool_name}`；**不要**把 `****` 填成数字。")
    else:
        tail = (f"请先回到会话里取顾客**完整的 11 位**号码（或直接问顾客），"
                f"再用真实号码调用 `{tool_name}`。")
    msg = (f"`{tool_name}` 的参数 `{path}` 填的是**掩码形态**的手机号 `{value}`"
           f"（{because}）：掩码值不能用来建单/建工单 —— 号码错了顾客收不到短信与配送联系，"
           f"而且 11 位纯数字的掩码填充值**看起来完全合法**，会静默落库成脏数据。{tail}")
    logger.warning(
        f"[{skill_name}] 拦截掩码形态手机号 tool={tool_name} arg={path} value={value!r} "
        f"known={known_raw!r} | session={session_id}")
    code = "write_blocked_masked_phone"
    return (tool_call, _json.dumps({"success": False, "error": code, "message": msg},
                                   ensure_ascii=False),
            {"success": False, "error": code, "message": msg})


async def _write_input_recovery_block(tool_name: str, args: dict, tool_call: dict,
                                      session_id: str, skill_name: str,
                                      last_user_msg: str):
    """「缺参等待期」拦截：返回 (tool_call, result_str, result_dict) 表示拦下，None 表示放行。

    只在**同一个写工具**或**逐字重发同一张确认卡**时拦 —— 其余工具（查询/交互/换商品）
    一律放行，绝不因为一次缺参失败就把整个会话锁死。
    """

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    if not session_id:
        return None
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
    except Exception:
        return None
    flag = full.get(WRITE_INPUT_ERROR_KEY)
    if not isinstance(flag, dict):
        return None
    # 结构化优先（issue #4080 T3）：`param` 由记账方从 `missing_params` 写入；
    # 非法/缺失的 flag 一律当作「无欠参」放行（fail-open，不静默锁死工具）。
    param = flag.get("param") or ""
    if not param:
        return None
    if user_supplied_param(param, last_user_msg):
        # 顾客已补上 → 清账放行（写工具本体还要走确认门禁）
        try:
            await store.commit(session_id, _clear_write_input_error(full))
            logger.info(f"[{skill_name}] 缺参已补齐 → 清除欠参标记 param={param} | session={session_id}")
        except Exception as e:
            logger.warning(f"[{skill_name}] 欠参标记清除失败（非致命）: {e}")
        return None

    label = _INPUT_PARAM_LABELS.get(param, param)
    failed_tool = str(flag.get("tool") or "")
    reason = ""

    if tool_name == failed_tool:
        reason = (f"顾客**还没有提供**{label}：重复调用 {tool_name} 结果必然相同，"
                  f"本轮**禁止再次调用 {tool_name}**。")
    elif tool_name == "interact":
        _comp = str((args or {}).get("component") or "")
        if (_comp == "confirm"
                and str((args or {}).get("confirmValue") or "") != ""
                and str((args or {}).get("confirmValue")) == str(full.get("last_confirm_value") or "")):
            reason = (f"顾客已经确认过这张卡了，而 {failed_tool or '写工具'} 缺的是{label}："
                      f"重发**同一张确认卡**只会让顾客反复点确认（死循环），本轮禁止重发该卡。")
        else:
            # 欠参期间**任何卡片**都不发（issue #3367）：实测 CH-010 首跑里两张**不同的**卡
            # （choice/confirm）各自把"顾客要发的验证码"这一轮吃掉 → order_create 缺码失败。
            # 卡片会抢走顾客本来要打的那句话；此时唯一有用的动作是**用文本索要**。
            reason = (f"顾客还没提供{label}（{failed_tool or '写工具'} 因此无法执行）："
                      f"本轮**不要下发任何卡片**（卡会抢走顾客正要发的内容），"
                      f"直接用文本索要{label}。")

    if not reason:
        return None

    msg = (reason
           + f" 请**直接用自然语言**向顾客说明卡在哪里，并索要{label}"
           + (f"（工具原话：{flag.get('message')}）" if flag.get("message") else "。")
           + " 顾客提供后再继续原流程（不要重新走一遍商品/地址收集）。")
    logger.warning(
        f"[{skill_name}] 拦截缺参等待期的重复动作 tool={tool_name} "
        f"param={param} | session={session_id} last_msg={last_user_msg[:20]!r}"
    )
    code = "write_blocked_waiting_customer_input"
    return (tool_call, json.dumps({"success": False, "error": code, "message": msg},
                                  ensure_ascii=False),
            {"success": False, "error": code})


async def _card_loop_block(tool_name: str, args: dict, tool_call: dict,
                          session_id: str, skill_name: str):
    """同一张交互卡下发第 3 次起拦下（返回 3 元组），否则放行（None）。"""

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    if tool_name != "interact" or not session_id:
        return None
    fp = card_fingerprint(args)
    if not fp:
        return None
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
    except Exception:
        return None
    counts = full.get(CARD_EMIT_COUNTS_KEY) or {}
    if not isinstance(counts, dict):
        return None
    if int(counts.get(fp) or 0) < CARD_EMIT_LIMIT:
        return None
    comp = str((args or {}).get("component") or "")
    title = str((args or {}).get("title") or "")[:40]
    logger.warning(
        f"[{skill_name}] 拦截重复下发同一张卡 component={comp} title={title!r} "
        f"count={counts.get(fp)} | session={session_id}"
    )
    msg = (f"这张{comp}卡（「{title}」）此前已经下发给顾客并收到过回答，内容没有任何变化："
           "重复下发只会让顾客反复答同一题、流程原地打转。"
           "**本轮不要重发这张卡**：请基于顾客已经给出的信息继续下一步"
           "（信息齐了就调用对应的写工具；缺信息就用自然语言直接问那一项）。"
           "若顾客**明确要求**再看一次加工项/选项，用文本把选项列给他，不要再发卡。")
    code = "card_blocked_repeat_emission"
    return (tool_call, json.dumps({"success": False, "error": code, "message": msg},
                                  ensure_ascii=False),
            {"success": False, "error": code})


async def _inject_write_input_recovery(system_prompt: str, state: dict,
                                       last_user_msg: str) -> str:
    """把「顾客欠一个参数」注入下一轮系统提示（issue #3365）。

    只在真正待补时注入；顾客本轮已补上则顺手清账并返回原提示。
    fire-and-forget：任何异常都不抛，不破坏主流程。
    """

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    if not state.get("session_id"):
        return system_prompt
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(state["session_id"]) or {}
        flag = full.get(WRITE_INPUT_ERROR_KEY)
        if not isinstance(flag, dict):
            return system_prompt
        # 结构化优先（issue #4080 T3）：`param` 由记账方从 `missing_params` 写入；
        # 非法/缺失的 flag 一律当作「无欠参」放行（fail-open，不静默锁死工具）。
        param = flag.get("param") or ""
        if not param:
            return system_prompt
        if user_supplied_param(param, last_user_msg):
            await store.commit(state["session_id"], _clear_write_input_error(full))
            return system_prompt
        label = _INPUT_PARAM_LABELS.get(param, param)
        failed_tool = str(flag.get("tool") or "写工具")
        logger.info(
            f"[write-input-recovery] 注入索要指令 param={param} tool={failed_tool} "
            f"| session={state['session_id']}"
        )
        return (
            "【上一轮写操作失败：顾客还没提供必要信息】\n"
            f"- {failed_tool} 因缺少{label}而**没有执行**。\n"
            f"- 本轮必须用自然语言向顾客说明并**索要{label}**"
            + (f"（原话：{flag.get('message')}）" if flag.get("message") else "。") + "\n"
            f"- **禁止**再次调用 {failed_tool}（参数不全会再次失败）；"
            "- **禁止**重发上一轮的确认卡/选择卡（重发只会让顾客反复点确认，形成死循环）。\n"
            "- 顾客提供该信息后再继续原流程，不要重新收集已有的商品与地址。\n\n"
            + system_prompt
        )
    except Exception as e:
        logger.warning(f"[write-input-recovery] 注入失败（非致命）: {e}")
        return system_prompt
