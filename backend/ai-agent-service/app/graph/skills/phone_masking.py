"""手机号掩码 / 已知真值记忆的**单一真值源**（从 `base_skill.py` 搬出，issue #8725）。

## 单一职责

回答一个问题：**「这个值是不是掩码形态、本会话的真号是什么、怎么记住它」**：

| 函数 | 职责 |
|---|---|
| `raw_phones_in` / `_phone_in_text_re` | 文本里的完整手机号（惰性编译正则） |
| `mask_variants` | 真号的所有掩码形态（含「把 `****` 填成 `0`」—— 生产事故的真实落库值） |
| `_is_mask_shaped` / `_phone_args` | 掩码形态判定 + 递归收集参数里的号码字段 |
| `_remember_known_value` / `_known_raw_phones` / `_remember_raw_phones` | 已知真值的跨轮记忆（只增不减，失败不致命） |

另含三个**共用的极小判据**（被注入块族与算料守卫同时使用）：`_should_code_close_loop`（确认-执行链收口）、
`_is_customer_role`（B/C 共用面）、`_norm_ws`（比对前抹空白）。

## 依赖方向（单向）

```text
base_skill.py ──(re-export)──▶ phone_masking.py      （本模块只 import `loguru`，无 app 依赖）
injection_blocks.py ──(顶层 import)──▶ phone_masking.py
```

## ⚠️ patch 缝：`logger` 调用期绑定（同 `order_flow_guard.py`，见该文件说明）

## 搬运纪律

函数体是原 `base_skill.py` 对应行的**逐字副本**（`ast` 边界切片），唯一机械改动 = 2 行 patch 前导。
"""


# ── 写工具不得用「掩码形态」手机号（issue #3386，DB 实证静默脏数据）────────────
# 实证（run 34742490138）：CH-010 订单 `20260913384380002` 落库
# `customer_phone = 13800008000`，而用例给模型的是 `13800138000`。
# `13800008000` = `138` + `0000` + `8000` —— 正是掩码 `138****8000` 的 `****` 被**填成 0**。
# 成因链：graph 层把回复脱敏后才返回（已在本文件 §8.5 移除）→ 落库的 assistant 消息
# 就是 `138****8000` → 模型下一轮读到自己的历史，把星号填成数字 → 11 位纯数字
# **形态完全合法**（`order_create._PHONE_PATTERN = ^1[3-9]\d{9}$` 放行）→ 静默建单成功，
# 顾客收不到短信与配送联系。`validate_input` 只挡得住带 `*` 的形态，挡不住"填 0"。
# 守卫判据（不是裸格式校验，而是**与已知真号比对**）：
#   · 提交值含掩码字符 → 必拦；
#   · 提交值 == 本会话已知真号的掩码变体（`138****8000` / `13800008000` / `138xxxx8000`）
#     且顾客本人本轮没给这个号 → 拦下并回放真实号码；
#   · 会话里没有已知真号 → **不拦**（`13800008000` 本身是合法真号，无权判它是脏数据）。
# 反向约束：顾客明确给了新号码必须放行（改号是合法业务，不能拦成"下单永不成功"）。
KNOWN_RAW_PHONES_KEY = "known_raw_phones"
# 已知收货地址（issue #3397）：预填值必须逐字保真 —— 模型改写会导致**寄错地址**。
KNOWN_ADDRESS_KEY = "known_customer_address"

# 掩码**占位字符**：真手机号绝不含这些字符 → 出现即证明是掩码值（可无条件拦）。
_MASK_PLACEHOLDER_CHARS = "*＊×xX·•#"

# 模型把掩码"填成什么"的可能形态：占位符本身 + **数字 0**（本次事故的真实形态）。
# ⚠️ 与占位字符必须分开：`0` 是合法号码字符，若混进 `_MASK_PLACEHOLDER_CHARS`，
# 任何含 0 的真号都会被判成"掩码形态"（过度拦截，下单永不成功）。
_MASK_FILLER_CHARS = _MASK_PLACEHOLDER_CHARS + "0"

_PHONE_IN_TEXT_RE = None


def _phone_in_text_re():
    """中国大陆手机号（数字边界）—— 惰性编译，避免模块导入期开销。"""
    global _PHONE_IN_TEXT_RE
    if _PHONE_IN_TEXT_RE is None:
        import re as _re
        _PHONE_IN_TEXT_RE = _re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
    return _PHONE_IN_TEXT_RE


def raw_phones_in(text) -> set:
    """文本里出现的**完整**手机号（用于收集"本会话已知真号"）。"""
    if not text:
        return set()
    return set(_phone_in_text_re().findall(str(text)))


def mask_variants(raw: str) -> set:
    """某个真号的所有「掩码形态」——占位符既可能保留原样，也可能被模型填成数字/字母。

    `13800138000` → {`138****8000`, `13800008000`, `138xxxx8000`, …}
    最后一项是本次事故的真实落库值，故必须包含"填 0"这一形态。
    """
    raw = str(raw or "")
    if len(raw) != 11 or not raw.isdigit():
        return set()
    return {raw[:3] + (c * 4) + raw[-4:] for c in _MASK_FILLER_CHARS}


def _is_mask_shaped(value: str) -> bool:
    """值里是否含掩码占位字符（含 `*` 的号码绝不可能是真号）。

    ⚠️ 必须同时要求"够像号码"（≥7 位数字）：字段名以 `phone` 结尾不代表值就是号码
    （`{phone_model: "iPhone X"}` 含 `X`），只看占位字符会把无关字段误判成掩码号码。
    """
    text = str(value or "")
    if sum(c.isdigit() for c in text) < 7:
        return False
    return any(c in text for c in _MASK_PLACEHOLDER_CHARS)


def _phone_args(args) -> list:
    """递归收集参数里所有「手机号字段」的 (路径, 值)，深度受限。"""
    out = []

    def _walk(node, path, depth):
        if depth > 3 or not isinstance(node, dict):
            return
        for k, v in node.items():
            key = str(k)
            here = f"{path}.{key}" if path else key
            if isinstance(v, dict):
                _walk(v, here, depth + 1)
            elif isinstance(v, (list, tuple)):
                for i, item in enumerate(v):
                    _walk(item, f"{here}[{i}]", depth + 1)
            elif key.lower().endswith("phone") and isinstance(v, str) and v.strip():
                out.append((here, v.strip()))

    _walk(args or {}, "", 0)
    return out


def user_provided_phones(state: dict | None = None, last_user_msg: str = "") -> set:
    """**顾客本人说过**的真号（本轮消息 ∪ 历史 user 消息）。

    ⚠️ 与 `_known_raw_phones` 的区别是本函数存在的全部理由：后者还并进**读工具**
    （`customer_address_query` 等）返回的号码 —— 那些号**不是顾客本轮的选择**。
    改写掩码值时只许用本函数的集合：否则「顾客要把手机号从 A 改成 B」而模型交回 A 的掩码，
    就会被静默改写成 A（= 改号失败但界面显示成功，issue #9224 的 CU-004）。
    """
    known = raw_phones_in(last_user_msg)
    for msg in (state or {}).get("messages") or []:
        try:
            role = str(getattr(msg, "type", "") or getattr(msg, "role", ""))
        except Exception:
            role = ""
        if role in ("human", "user"):
            known |= raw_phones_in(getattr(msg, "content", ""))
    return known


def rewrite_phone_args(args, mapping: dict) -> list:
    """把参数里「手机号字段」的值按 `mapping{旧值: 真号}` **就地改写**；返回 `[(路径, 旧值, 新值)]`。

    遍历口径与 `_phone_args` 逐字一致（同一个「什么算手机号字段」的判定），否则会出现
    「拦得住、改不到」的分裂：守卫看得到这个字段，改写却漏掉它 ⇒ 拦截后的重试永远失败。
    """
    out = []

    def _walk(node, path, depth):
        if depth > 3 or not isinstance(node, dict):
            return
        for k, v in list(node.items()):
            key = str(k)
            here = f"{path}.{key}" if path else key
            if isinstance(v, dict):
                _walk(v, here, depth + 1)
            elif isinstance(v, (list, tuple)):
                for i, item in enumerate(v):
                    _walk(item, f"{here}[{i}]", depth + 1)
            elif key.lower().endswith("phone") and isinstance(v, str):
                new = mapping.get(v.strip())
                if new:
                    node[k] = new
                    out.append((here, v.strip(), new))

    _walk(args or {}, "", 0)
    return out


async def _remember_known_value(session_id: str, key: str, value: str) -> None:
    """把一个**已知真值**（地址等）记进会话状态（只增不减；失败不致命）。"""

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    value = str(value or "").strip()
    if not session_id or not value:
        return
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
        cur = full.get(key) or []
        cur_list = [str(v) for v in cur] if isinstance(cur, (list, tuple, set)) else []
        if value in cur_list:
            return
        full[key] = cur_list + [value]
        await store.commit(session_id, full)
    except Exception as e:
        logger.warning(f"[known-value] 记录 {key} 失败（非致命）: {e}")


async def _known_raw_phones(session_id: str, state: dict | None = None,
                            last_user_msg: str = "") -> set:
    """本会话已知的**真实**手机号：跨轮持久化集合 ∪ 会话里顾客自己说过的号码。

    为什么要两路：顾客提供的号码在本轮消息/历史里（无需持久化），而
    `customer_order_query` 等读工具返回的号码要靠持久化跨轮带过来。
    """
    known = set()
    try:
        from app.memory.session_state_store import SessionStateStore
        full = await SessionStateStore().load(session_id) or {}
        stored = full.get(KNOWN_RAW_PHONES_KEY) or []
        if isinstance(stored, (list, tuple, set)):
            known |= {str(p) for p in stored if str(p)}
    except Exception:
        pass
    known |= raw_phones_in(last_user_msg)
    for msg in (state or {}).get("messages") or []:
        try:
            role = str(getattr(msg, "type", "") or getattr(msg, "role", ""))
        except Exception:
            role = ""
        if role in ("human", "user"):
            known |= raw_phones_in(getattr(msg, "content", ""))
    return known


async def _remember_raw_phones(session_id: str, phones) -> None:
    """把读到的真号记进会话状态（只增不减；失败不致命）。"""

    from app.graph.skills import base_skill as _base
    logger = _base.logger
    fresh = {str(p) for p in (phones or set()) if str(p)}
    if not session_id or not fresh:
        return
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
        cur = full.get(KNOWN_RAW_PHONES_KEY) or []
        merged = sorted({str(p) for p in cur if str(p)} | fresh)
        if merged == sorted({str(p) for p in cur if str(p)}):
            return
        full[KNOWN_RAW_PHONES_KEY] = merged
        await store.commit(session_id, full)
    except Exception as e:
        logger.warning(f"[phone-guard] 记录真实号码失败（非致命）: {e}")


def _should_code_close_loop(pending: dict | None, target_tool: str,
                            confirmed: bool, executed_tools) -> bool:
    """确认-执行链是否需要**代码侧收口**（issue #3410）。

    为什么抽成纯函数：条件写在 `execute_skill` 内联时**无法被单测观察到**
    （实证：变异 M207"去掉防双单判定"存活 —— 因为成功写会顺手清 pending，
    那条分支走不到）。抽出来后真值表可逐项钉住。

    条件（全部满足才收口）：
      · 存在已校验待执行写（`validate_input` 通过后落库）；
      · 目标工具名非空；
      · 顾客**已明确确认**（确认卡值精确匹配 或 文本明确确认）—— 安全性质：不得绕过确认；
      · 本轮模型**没有执行过**这个工具 —— 防双单（成功写会清 pending，失败写允许代码重试）。
    """
    if not pending or not target_tool or not confirmed:
        return False
    if target_tool in (executed_tools or set()):
        return False
    return True


def _is_customer_role(state: dict | None) -> bool:
    """本轮是否为 **C 端（顾客本人）** 身份。

    为什么必须有（B/C 共用面）：`interact` 工具与全部技能守卫都写在**共享的**
    `base_skill` 里 —— 两端卡片由同一个工具产出，守卫不分端就会互相影响
    （B 端店员代客下单、客服改客户资料的表单与 C 端顾客自助场景语义不同）。
    身份来自 `state["role"]`（= `context.role`：C 端 "customer"，B 端 "admin"/"agent"）。
    """
    return str((state or {}).get("role") or "").strip().lower() == "customer"


def _norm_ws(v) -> str:
    """比对前去掉所有空白（地址/号码里的空格差异不算改写）。"""
    return "".join(str(v or "").split())


# ══════════ 确认卡展示面：手机号一律掩码化（issue #9224 产品口径，2026-11-27 裁定）══════════
# 裁定原文（用户逐字）：「确认卡是否允许展示完整手机号，这个裁定是**展示脱敏后的手机号**，
# 不能完整展示」。两个**被否决**的出口（不要再回去动它们）：
#   ① 让 `interact` 的工具结果豁免脱敏（卡面直接显示完整号，等价于静默改变聊天的隐私面）；
#   ② 卡面携带 `rawValue` 真值字段（真值进模型上下文 / SSE，等价于 ① 只是显式化）。
# 正确出口 = **只改展示面**：点卡路由读 `last_confirm_value` / `pending_validated_input` 取写参数，
# **从不**从卡面 `fields` 拼参数（判据 `tests/test_card_phone_masking_9224.py`）。
#
# 为什么不能「照模型交上来的值就地打码」：模型读到的是**被脱敏过的**工具结果 ⇒ 它会把**旧号**的
# 掩码（`138****8000`）抄进卡片，而本轮真正要写的是顾客刚给的新号（`13900001111`）⇒
# 卡面展示的号与落库的号不是同一个（CU-004 现场）。故掩码以 `pending_validated_input` 的真号为锚。

#: 号码「token」字符集 = 数字 + 掩码占位符。只用于**就地替换**（保住标签与前后文），
#: **不是**第二份手机号正则 —— 形态判定一律走 `raw_phones_in` / `_is_mask_shaped`。
_PHONE_TOKEN_CHARS = frozenset("0123456789") | frozenset(_MASK_PLACEHOLDER_CHARS)


def _mask_of(raw: str) -> str:
    """真号 → 掩码形态（前 3 + `****` + 后 4）。

    与出站脱敏 `app.utils.pii_mask.mask_phone` **同形**（同一产品的掩码长相）；
    这里按字符切片，不引第三方正则。
    """
    raw = str(raw or "")
    return raw[:3] + "****" + raw[-4:] if len(raw) >= 7 else raw


def _phone_tokens(text: str) -> list:
    """把文本切成「号码字符」连续片段（数字 + 掩码占位符），用于就地替换而不吃掉前后文。"""
    out, buf = [], ""
    for ch in text:
        if ch in _PHONE_TOKEN_CHARS:
            buf += ch
        elif buf:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def mask_phone_value(value, raw_phones=()) -> tuple:
    """把一个**值**里的手机号改写成掩码形态；返回 `(新值, 是否改写)`。

    判据**只看值**（与字段名无关 —— 模型会把号放进「备注」「联系方式」这类字段）：
      · 号码形态 = `raw_phones_in(token)` 非空（完整真号）**或** `_is_mask_shaped(token)`（掩码形态）；
      · 有**唯一**「本次真正要写入的真号」（`pending_validated_input` 的号码字段）⇒ 一律改写成
        `_mask_of(该真号)`：卡面写的号必须与本轮要落库的号是**同一个**（issue #9224 的核心语义）；
      · 没有真号锚 ⇒ 完整号就地掩码，已是掩码形态的**原样保留**（幂等：掩码再掩码 = 同一串）；
      · 订单号 / 验证码等 11 位数字片段不被误伤（`1[3-9]\\d{9}` + 数字边界即 `raw_phones_in` 的口径）。
    """
    text = "" if value is None else str(value)
    if not text:
        return value, False
    truths = [p for p in dict.fromkeys(str(p) for p in (raw_phones or ()) if str(p))
              if len(p) == 11 and p.isdigit()]
    target = _mask_of(truths[0]) if len(truths) == 1 else ""
    out, changed = text, False
    for token in _phone_tokens(text):
        found = sorted(raw_phones_in(token))
        if not found and not _is_mask_shaped(token):
            continue
        new = target or (_mask_of(found[0]) if found else token)
        if new != token:
            out = out.replace(token, new)
            changed = True
    return out, changed


def pending_write_phones(full: dict | None = None) -> list:
    """会话状态里「**本次真正要写入**的真号」（`pending_validated_input.params` 的号码字段）。

    只认它：读工具返回的历史号码**不是**本轮的选择 —— 拿它当锚就会把卡面写成旧号
    （「展示旧号、写入新号」= CU-004 的病灶）。掩码形态的值不算真号（无从还原）。
    """
    pending = (full or {}).get("pending_validated_input") or {}
    out: list = []
    for _path, value in _phone_args(pending.get("params") or {}):
        if _is_mask_shaped(value):
            continue
        for phone in sorted(raw_phones_in(value)):
            if phone not in out:
                out.append(phone)
    return out


def mask_confirm_card_fields(fields, raw_phones=()) -> list:
    """确认卡 `fields[].value` 的手机号统一掩码化（issue #9224）；返回**新的**字段结构（不改入参）。

    覆盖每个 `value`（含**嵌套** dict / list —— 模型偶尔把整块收货信息塞进一个 value，
    故 `value` 子树内的**所有**字符串叶子都过一遍掩码）。
    只动展示面：`label` 与其它键原样保留，`options[].value` 这类协议值不归本函数管。
    """
    truths = tuple(raw_phones or ())

    def _mask_whole_value(node):
        """`value` 子树内部：所有字符串叶子都掩码（含嵌在 dict / list 里的号码）。"""
        if isinstance(node, dict):
            return {k: _mask_whole_value(v) for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [_mask_whole_value(item) for item in node]
        if isinstance(node, str):
            return mask_phone_value(node, truths)[0]
        return node

    def _walk(node):
        if isinstance(node, dict):
            return {k: (_mask_whole_value(v) if str(k) == "value" else _walk(v))
                    for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [_walk(item) for item in node]
        return node

    return _walk(list(fields or []))


async def mask_confirm_card_result(tool_name: str, result_dict: dict, session_id: str) -> bool:
    """工具执行出口的确认卡整形：`fields[].value` 的手机号一律掩码（issue #9224 产品口径）。

    **就地**改 `result_dict["data"]`，并返回「是否真的改动了」——调用方据此重算 `result_str`
    （模型上下文、SSE 交互载荷、落库的 `last_card` 读的都是这一份，见
    `app/graph/skills/execution/react_turn.py` 的调用点）。只对 `interact` 的 confirm 卡生效。

    为什么不做在 `app/tools/interact.py`：`app/tools/**` 不得 import `app.graph.*`（分层守卫
    `tests/test_utils_sku_price.py::test_tools_layer_does_not_import_skill_layer`）；
    为什么不做在 `app/graph/skills/base_skill.py`：该文件是**冻结棘轮**文件（逐行只许下降，
    `tests/unit_ci_workflows/test_loc_ratchet.py`）——实现体下沉到本模块（复用件）即可，零新增行。
    失败**非致命**（卡照发），但必须留痕 —— 不许静默退化成「卡面显示真号」。
    """
    try:
        data = (result_dict or {}).get("data")
        if str(tool_name) != "interact" or not isinstance(data, dict) \
                or data.get("component") != "confirm":
            return False
        fields = data.get("fields")
        if not isinstance(fields, list) or not fields:
            return False
        full = {}
        if session_id:
            from app.memory.session_state_store import SessionStateStore
            full = await SessionStateStore().load(session_id) or {}
        masked = mask_confirm_card_fields(fields, pending_write_phones(full))
        if masked == fields:
            return False
        data["fields"] = masked
        # `confirmValue` 由字段**确定性派生**（单一派生平 `app.tools.confirm_value`，issue #4054）：
        # 字段变了必须**同一次**重算 —— 否则顾客点卡回传的仍是含真号/旧掩码的那一版，而门禁比对的
        # 是落库的 `last_confirm_value`；两处不同源就会「点了卡仍判未确认」（确认死循环）。
        from app.tools.confirm_value import confirm_value_for_fields
        _cv = confirm_value_for_fields(masked)
        if _cv:
            data["confirmValue"] = _cv
        return True
    except Exception as e:  # pragma: no cover - 整形失败不得打断主流程
        from app.graph.skills import base_skill as _base
        _base.logger.warning(f"[card-mask] 确认卡手机号掩码化失败（非致命，卡面可能未脱敏）: {e}")
        return False
