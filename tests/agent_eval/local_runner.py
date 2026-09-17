"""
Mibao Agent 本地评测 — 直接调 localhost chat API，采集 SSE 事件

用法:
  PRIMARY_API_KEY=sk-xxx python local_runner.py smoke     # 冒烟
  PRIMARY_API_KEY=sk-xxx python local_runner.py full      # 全量
  PRIMARY_API_KEY=sk-xxx python local_runner.py case P005 # 单条
"""

import sys, os, json, time, asyncio, re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from pathlib import Path

# CI stdout 可能默认 ascii 编码，强制 UTF-8（防中文/emoji 触发 UnicodeEncodeError）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

sys.path.insert(0, os.path.dirname(__file__))
# 模块级注入 .github（render_cases/filter_by_persona 单一源，issue #2855）——
# 保证无 --cases（ALL_CASES 生成物）路径下 main() 也能 import
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / ".github"))
from eval_cases import ALL_CASES, EvalCase, Skill, Difficulty

# Config
ADMIN_API = os.environ.get("ADMIN_API_URL", "http://localhost:8080")
AI_API = os.environ.get("AI_API_URL", "http://localhost:8001")
PHONE = os.environ.get("TEST_PHONE", "13800138000")
BYPASS_CODE = os.environ.get("BYPASS_CODE", "123456")
# CI 模式：SERVICE_TOKEN 存在时，chat/send 无 auth（DEBUG 默认用户），admin-api 用 X-Service-Token
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN", "")

# Persona：mibao（默认，B 端工作助手）/ xiaobu（C 端客服小布）
# xiaobu 模式：不带 Bearer token，通过 X-Debug-Role: customer 让 DEBUG 模式路由到小布，
# 并验证 C 端数据隔离（customer_order_query 而非 order_query）。
PERSONA = os.environ.get("PERSONA", "mibao").strip().lower()

# ── 节流 sleep（可配，issue #3361 评测提速）──
# 为什么可配：评测墙钟时间几乎全花在真实 LLM 往返上，固定 sleep 是纯额外开销 ——
# 实测 C 端 normal 单跑 19m39s（18 条），其中 ~63s 是 0.5s/轮 + 1s/用例的固定等待，
# B 端 47 条约 3min。真实 LLM 有并发限流需求，故保留"可调"而不是删除：
# CI 用 EVAL_ROUND_SLEEP=0.2 / EVAL_CASE_SLEEP=0.3，本地调试可调回 0.5/1。
def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        print(f"⚠️ {name}={raw!r} 非法，回落默认 {default}")
        return default
    return v if v >= 0 else default


ROUND_SLEEP = _env_float("EVAL_ROUND_SLEEP", 0.5)
CASE_SLEEP = _env_float("EVAL_CASE_SLEEP", 1.0)

# ── C 端用例集选择（纯逻辑拆到 eval_case_filter，issue #3266）──
# 拆出去的动机：本文件有模块级 `import httpx`，而 CI 的 ci-workflow-helper 测试 job
# 只装 pytest+pyyaml → 任何想复用「用例集选择」的测试/脚本一 import 本模块就崩。
# eval_case_filter 零第三方依赖，runner/测试/覆盖体检三处共用同一实现。
sys.path.insert(0, os.path.dirname(__file__))
from eval_case_filter import (  # noqa: E402
    XIAOBU_TOOLS,
    case_expectation_tools as _case_expectation_tools,
    case_persona as _case_persona,
    case_skip_reason as _case_skip_reason,
    select_cases_for_persona,
)


def _validate_service_token(token: str) -> str | None:
    """校验 SERVICE_TOKEN 是否纯 ASCII（HTTP header 值必须是 ASCII）。

    返回 None 表示合法；否则返回人类可读的错误说明。
    """
    if not token:
        return None
    try:
        token.encode("ascii")
        return None
    except UnicodeEncodeError:
        bad = "".join(c for c in token if ord(c) > 127)
        return (
            f"SERVICE_TOKEN 含非 ASCII 字符（{bad[:10]}），HTTP 请求头必须纯 ASCII。"
            "请检查 GitHub Secrets 的 SMOKE_SERVICE_TOKEN 值：去掉中文/空格/换行，或换成有效的服务 token。"
        )


_token_err = _validate_service_token(SERVICE_TOKEN)
if _token_err:
    print(f"❌ {_token_err}", file=sys.stderr)
    sys.exit(1)

ADMIN_HEADERS = {"X-Service-Token": SERVICE_TOKEN, "X-Tenant-Id": "1"} if SERVICE_TOKEN else {}


def _admin_headers(token: str) -> dict:
    """admin-api 认证 header：CI 模式用 X-Service-Token，本地用 Bearer"""
    return ADMIN_HEADERS if SERVICE_TOKEN else ({"Authorization": f"Bearer {token}"} if token else {})

import httpx

# ── 数据隔离：保存/恢复商品状态 ──

_saved_states: dict = {}  # {product_id: {"basePrice": ..., "name": ...}}

# 商品改价的**权威字段名**（issue #3807）：admin-api 的
# `AgentProductUpdateRequest` 只有 `basePrice`（`ProductResponse.getPrice()` 只是
# `return basePrice` 的只读派生）。旧实现发 `{"price": …}` ⇒ Jackson 忽略未知属性、
# `basePrice` 保持 null（= 不修改）⇒ **复位静默空转**：种子「遮光窗帘」¥168 被 PR-010
# 改成 198 后，此后全场读到 198（两次判定跑独立复现）。单一源：
# backend/admin-api/src/main/java/com/migao/admin/dto/agent/AgentProductUpdateRequest.java
PRODUCT_PRICE_FIELD = "basePrice"


def _safe_json(resp, default=None):
    """防御性 JSON 解析：响应非 JSON（限流/瞬断/400 HTML）时返回默认值，不中断评测。

    实测崩溃（2026-09-09）：对生产跑 normal 全量评测，中途 snapshot_product 的
    GET /api/admin/products 返回 400 HTML → r.json() 抛 JSONDecodeError →
    整个评测崩溃退出，后续用例全部未跑。评测基础设施的健壮性比单个用例
    失败更重要：任何辅助请求的非 JSON 响应都应降级（返回 None/[]），
    由后续断言与重试机制处理，而不是让一次瞬时限流毁掉整轮基线。
    """
    try:
        return json.loads(getattr(resp, "content", b""))
    except Exception:
        return default


async def snapshot_product(token: str, product_keyword: str) -> str | None:
    """保存商品当前状态，返回 product_id。

    取值键显式取 **`basePrice`**（issue #3807）：它才是写路径的权威字段
    （`AgentProductUpdateRequest.basePrice`），`ProductResponse.getPrice()` 只是
    `return basePrice` 的派生 getter。旧实现写的是 `p.get("price") or p.get("basePrice")`
    —— 一旦 `getPrice()` 语义漂移（如将来加价/含税），快照就会取到**不是写路径那个值**，
    复位随即静默错位。`price` 仅作兜底（响应里 basePrice 缺失时）。
    """
    async with httpx.AsyncClient() as c:
        h = _admin_headers(token)
        r = await c.get(f"{ADMIN_API}/api/admin/products", headers=h,
                        params={"keyword": product_keyword, "page": 1, "size": 1})
        items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
        if not items:
            return None
        p = items[0]
        pid = p["id"]
        price = p.get(PRODUCT_PRICE_FIELD)
        if price is None:
            price = p.get("price")
        _saved_states[pid] = {PRODUCT_PRICE_FIELD: price, "name": p.get("name", "")}
        return pid


async def restore_product(token: str, product_id: str) -> str:
    """恢复商品到保存的状态 —— **复位失败必须可见**（issue #3807）。

    旧实现两个缺陷，合起来让"改价永不复原"完全不可见：
      ① 请求体发 `{"price": …}` 而 DTO 只认 `basePrice` ⇒ 静默 no-op；
      ② 不检查响应状态 ⇒ 连 HTTP 错误都不留痕。
    现在：① 发权威字段 `basePrice`；② 非 2xx 即记账；③ **回读校验** —— 复位是否
    真的生效不再靠推测（"看起来复位了、其实空转"是与 pre_clean 同族的静默 no-op 面）。
    返回可读消息（含 ❌/⚠️ 前缀即表示需要处理），调用方把它计入用例结果，
    让「前置未复位」进结论而不是留在日志里。

    ⚠️ 刻意**不抛异常**：本函数在 `finally` 分支被调用，抛异常会覆盖真正的用例结果
    （把"复位失败"变成"用例崩溃"）—— 归因反而更差。故以返回值 + 调用点记账表达失败。
    """
    if product_id not in _saved_states:
        return ""
    saved = _saved_states[product_id]
    price = saved.get(PRODUCT_PRICE_FIELD)
    short = str(product_id)[:8]
    if price is None:
        return (f"PRECONDITION_NOT_RESTORED: 商品 {short} 无快照价格，跳过价格复位"
                f"（后续读价用例的基线未证实）")
    async with httpx.AsyncClient() as c:
        h = _admin_headers(token)
        r = await c.patch(f"{ADMIN_API}/api/admin/agent/products/{product_id}",
                          headers=h, json={PRODUCT_PRICE_FIELD: price}, timeout=15)
        if getattr(r, "status_code", 0) >= 300:
            return (f"PRECONDITION_NOT_RESTORED: 价格复位失败 —— 商品 {short} 应复位为 {price}，"
                    f"PATCH 返回 {r.status_code}（前置未复位，后续读价用例不可信）")
        # 回读校验：2xx ≠ 值已落地（旧 bug 正是"2xx 但字段名没人认"）
        try:
            rr = await c.get(f"{ADMIN_API}/api/admin/products", headers=h,
                             params={"keyword": saved.get("name") or "", "page": 1, "size": 20},
                             timeout=15)
            items = (_safe_json(rr, {}) or {}).get("data", {}).get("items", [])
            cur = next((p for p in items if p.get("id") == product_id), None)
        except Exception as e:
            return (f"PRECONDITION_NOT_RESTORED: 价格复位回读失败"
                    f"（{type(e).__name__}: {e}）：商品 {short} 复位结果**未证实**")
        if cur is None:
            return (f"PRECONDITION_NOT_RESTORED: 价格复位回读未命中商品 {short}"
                    f"（复位结果未证实）")
        got = cur.get(PRODUCT_PRICE_FIELD)
        if got is None:
            got = cur.get("price")
        try:
            same = got is not None and float(got) == float(price)
        except (TypeError, ValueError):
            same = str(got) == str(price)
        if not same:
            return (f"PRECONDITION_NOT_RESTORED: 价格复位未生效 —— 商品 {short} 回读 {got}，"
                    f"期望 {price}（复位字段名/契约不符）")
        return f"✅ 价格已复位：商品 {short} → {price}（回读一致）"


async def _end_session(token: str, session_id: str, debug_user: str = "",
                       debug_permissions: str = "") -> None:
    """评测会话清理（协议 §2.2）：case 结束后关闭会话，并触发长时记忆 flush。

    **主路径必须是 ai-agent 的关闭接口**（PUT {AI_API}/api/chat/sessions/{id}/close）：
    该路径 SessionService.close → SessionMemory.close_session → _flush_pending_memories，
    是记忆候选落库 user_memories 的**唯一入口**（issue #2815 会话末聚合）。

    issue #3357 复盘（清理静默失败的假绿温床）：
      旧实现打 admin-api `POST /api/admin/agent-sessions/{id}/end`，但该接口操作的是
      **人工会话表 agent_sessions**，C 端评测会话在 ai-agent 的 **sessions** 表 ——
      两表 id 不互认 → 恒 404 → 被 `except: pass` 吞掉。后果有两层：
        1. 评测会话从未真正关闭（残留 active，与"实测 8 个残留会话未关闭"吻合）；
        2. close 路径从未执行 → 记忆候选从未 flush → user_memories 恒 0 条，
           而报告一片全绿（"记忆没落库"没有任何断言看得见）。
      故：主路径换成对的接口，且失败**打 warning**（清理失败必须可见，不再静默）。
    """
    try:
        async with httpx.AsyncClient() as c:
            # 多身份用例（issue #3392）：会话属主是用例声明的身份，
            # 用默认身份关闭会 403（实测 sess_... HTTP 403）→ close 路径失效 =
            # 记忆候选不 flush（正是本函数注释里 issue #3357 修过的"静默失效"）。
            r = await c.put(f"{AI_API}/api/chat/sessions/{session_id}/close",
                            headers=_chat_headers(token, debug_user, debug_permissions),
                            timeout=15)
            if r.status_code >= 400:
                print(f"     ⚠️ 会话关闭失败 HTTP {r.status_code}: id={session_id} "
                      f"body={str(getattr(r, 'content', b''))[:120]}")
    except Exception as e:
        print(f"     ⚠️ 会话关闭异常: id={session_id} {type(e).__name__}: {e}")
    # 兼容调用已**删除**（issue #3361 顺手清理）：admin-api `agent_sessions` 是人工会话表，
    # 其主键与 ai-agent 会话 id 不互认，传 ai 会话 id 永远查不到行 —— 实测 CI 里每次调用
    # 都在 admin-api 侧留一条 `[NOT_FOUND] 客服会话不存在` 告警（死代码 + 噪音）。
    # 人工会话本身是**待人工处理的工单**，也不该由评测 harness 关闭。


# ── 前置复位直连 DB（attempt 边界的 fixture 动作，issue #3751）─────────────────
# 为什么需要 DB 直连：**"把被用例点名的对象复位回初始态"在现有 HTTP 面上做不到** ——
#   admin-api `PUT /api/admin/after-sales/{id}/status` 的 `STATUS_TRANSITIONS` 把 `closed`
#   设为**终态**（`AfterSalesTicketService.java:103-109`：`closed → Set.of()`），且关闭分支
#   只 `setClosedAt/setCloseReason`（`:501-506`）、**没有清空路径** ⇒ 首跑关掉的工单在重试前
#   无法复位 ⇒ 第 2 次尝试的前置 ≠ 第 1 次的前置（AS-004 实测：首跑已 closed + closeReason
#   残留 ⇒ 重试 agent 合理地"不再关闭" ⇒ 必红，且与首跑成因不同 → 指纹漂移 → 误判）。
#   故复位与 `scripts/eval_stack_seed.sh` 走**同一条 DB**（只是不经 psql）：seed 的初始态
#   就是真值来源（`fixtures/mibao_eval_seed.sql:302`）。
# ⚠️ 红线：复位**只允许发生在一次尝试开始之前**（attempt 边界，见 `run_suite` 的重试分支）。
#   绝不能在断言/`db_verify` 之后调用 —— 那会把本次尝试的真实产物抹掉，把真失败洗成绿。
_EVAL_DB_DSN_DEFAULT = "postgresql://app_user:%s@127.0.0.1:5432/ai_customer_service"

# seed 工单：AS-004 点名的对象（`fixtures/mibao_eval_seed.sql:302` 的 'AS-20260914-9001'）
_SEED_AFTERSALES_TICKET_NO = "AS-20260914-9001"

# 复位到 seed 初始态：状态回 pending + **清空关闭留痕**（closedAt/closeReason/internalNotes）。
# 只回状态不清留痕 = 假绿：`db_verify[after_sales_ticket]` 的
# `expect_fields_nonempty: [closedAt, closeReason]` + `expect_close_reason_contains` 会被
# **首跑残留**满足（重试即使什么都没写也可能过这条核对器）。
_RESET_AFTERSALES_TICKET_SQL = """
UPDATE after_sales_tickets
   SET status = 'pending', closed_at = NULL, close_reason = NULL,
       internal_notes = NULL, updated_at = NOW()
 WHERE tenant_id = 1 AND ticket_no = $1
RETURNING id
"""


def _eval_db_dsn() -> str:
    """前置复位用的 DB DSN（fixture 动作，非断言取数 —— `db_verify` 仍走 HTTP 产出侧）。

    取法：`EVAL_DB_URL` 优先；否则 compose 栈口径（CI 的 postgres 端口已发布到宿主，
    评测步骤已 `pip install -r backend/ai-agent-service/requirements.txt` 带上 asyncpg）。
    本地 `.env` 里的 SQLAlchemy 风格 DSN（`postgresql+asyncpg://`）会被归一 —— 直接从
    `DATABASE_URL` 抄过来也能用。
    """
    dsn = os.environ.get("EVAL_DB_URL", "").strip()
    if not dsn:
        pwd = os.environ.get("DEV_DB_PASSWORD") or "dev_password_123"
        dsn = _EVAL_DB_DSN_DEFAULT % pwd
    return dsn.replace("postgresql+asyncpg://", "postgresql://") \
              .replace("postgres+asyncpg://", "postgresql://")


async def _reset_aftersales_ticket(ticket_no: str) -> str:
    """把被点名的工单复位回 seed 初始态；返回人读消息（随结果落盘，归因可见）。

    为什么返回消息而不是静默返回 bool：复位没生效与"能力缺陷"在报告里同形是本仓库
    反复踩过的归因盲区（#3511）—— 复位失败必须能在 `eval-summary-*.json` 的
    `pre_clean` 字段里读到**为什么**（DB 不可达 / asyncpg 缺失 / 工单不在）。
    失败**不中断**评测（环境问题不该伪装成用例失败），但消息里显式写明
    "重试前置可能与首次不等价"，让结论可判。
    """
    try:
        import asyncpg  # 延迟导入：本模块的**模块级**第三方依赖仍只有 httpx
    except ImportError as e:
        return (f"未复位工单 {ticket_no}（asyncpg 不可用: {e}）"
                f"—— 若本用例首跑改变了该工单状态，重试前置将与首次不等价")
    try:
        conn = await asyncpg.connect(_eval_db_dsn(), timeout=8)
        try:
            row = await conn.fetchrow(_RESET_AFTERSALES_TICKET_SQL, ticket_no)
            if row is None:
                return (f"未复位：库里没有工单 {ticket_no}"
                        f"（栈缺 seed？见 fixtures/mibao_eval_seed.sql）")
            # 时间线同样复位（seed 只留建单那条 'created'）：首跑的 status_change 记录
            # 会让"工单详情历史"与初始态不一致（详情页/历史类断言的可比性）。
            await conn.execute(
                "DELETE FROM ticket_timeline WHERE ticket_id = $1 AND action <> 'created'",
                row["id"])
        finally:
            await conn.close()
    except Exception as e:
        return (f"未复位工单 {ticket_no}（DB 不可达/失败: {type(e).__name__}: {e}）"
                f"—— 若本用例首跑改变了该工单状态，重试前置将与首次不等价")
    return (f"已复位工单 {ticket_no} → pending（清空 closedAt/closeReason/internalNotes）")


# ── 加工单用例的前置复位（issue #3833，`#3800` 同族的新实例）─────────────────────
# 为什么需要（判定跑 34908262839 的 `PG-013`）：写类用例 `PG-013` 首跑把
# `EVAL-MB-ORD-0002` 从 `confirmed` 转成 `producing` **并生成一张加工单**
# （用例 `data_checks` 逐字写着「订单转 producing」），而 `_reset_for_retry` 按
# `pre_clean` **opt-in** ⇒ 原来没声明 = 重试前不复位 ⇒ 第 2 次尝试的 R1 只看到
# `orders=1`（首跑 2 笔）、R2 看到「这单的加工单早已生成，无需重复生成」⇒ agent
# **合理地**不再调 `processing_order_generate` ⇒ 末次必红且两次成因不同
# ⇒ 误分类 `unstable`。这与 `AS-004`（#3751）同形：现有 HTTP 面上**没有**"把订单
# 复位回未生产、并撤掉加工单"的通道（`ProcessingOrderController` 只有
# generate/list/detail/PATCH，无 delete；订单状态机也没有 producing→confirmed 的反向放行）
# ⇒ 与 seed 走**同一条 DB**（`scripts/eval_stack_seed.sh` 的 psql 之外的 asyncpg 直连）。
# ⚠️ 红线（#3800 记录过 `product_remove` 连带误删的教训）：复位**只按 `order_no` 精确匹配**
# 用例点名的那张**专用种子订单**及其加工单，禁止子串/模糊匹配 —— 否则会误伤
# `EVAL-MB-ORD-0003/0004`（PG-015/PG-016 的专用订单）等共享种子。
_SEED_PROCESSING_ORDER_NO = "EVAL-MB-ORD-0002"

# 复位到 seed 初始态：订单回 `confirmed`（`fixtures/mibao_eval_seed.sql` 的插入值）
# + 把本用例为该订单生成的加工单**软删**（`deleted = 1`）—— 走软删是与仓库既有约定一致
# 的做法，且 `uk_processing_orders_active` 唯一索引只覆盖 `deleted = 0` 的在途状态，
# 软删后重跑再生成不会撞唯一键。
_RESET_PROCESSING_ORDER_SQL = """
UPDATE processing_orders
   SET deleted = 1, updated_at = NOW()
 WHERE tenant_id = 1 AND deleted = 0
   AND order_id = (SELECT id FROM orders WHERE tenant_id = 1 AND order_no = $1)
RETURNING id
"""

_RESTORE_ORDER_STATUS_SQL = """
UPDATE orders
   SET status = 'confirmed', updated_at = NOW()
 WHERE tenant_id = 1 AND order_no = $1
RETURNING id
"""


async def _reset_processing_order(order_no: str) -> str:
    """把被点名的订单复位回 seed 初始态（`confirmed` + 无在途加工单）；返回人读消息。

    消息形态对齐 `_reset_aftersales_ticket`（#3511 归因）：失败必须能在
    `eval-summary-*.json` 的 `pre_clean` 字段里读到**为什么**，而不是与"能力缺陷"同形。
    ⚠️ 措辞红线（#3751）：**成功路径不得含「未复位」/「失败」** —— `_reset_for_retry`
    据此判"重试前置与首次不等价"，误判会把结论标成不可归因于 agent。
    """
    try:
        import asyncpg  # 延迟导入：本模块的**模块级**第三方依赖仍只有 httpx
    except ImportError as e:
        return (f"未复位订单 {order_no}（asyncpg 不可用: {e}）"
                f"—— 若本用例首跑把该订单转成了 producing，重试前置将与首次不等价")
    try:
        conn = await asyncpg.connect(_eval_db_dsn(), timeout=8)
        try:
            cleared = await conn.fetch(_RESET_PROCESSING_ORDER_SQL, order_no)
            row = await conn.fetchrow(_RESTORE_ORDER_STATUS_SQL, order_no)
            if row is None:
                # **准备型**的"目标不在位"必须进结论（#3781）：点名的种子订单不在 =
                # 用例带着**假前置**跑完 ⇒ 折进 case-level 失败，不静默放过。
                # ⚠️ 与 `_reset_aftersales_ticket` 的同名分支**有意不同**（那条只回
                # 「未复位：…」，不折进结论）—— 本类型按 #3781 的分族语义走 fail-closed；
                # 存量那条的差异已在 issue #3833 登记（不在本 PR 顺手改，避免动 AS-004 的判定）。
                return (f"{_PRECONDITION_NOT_APPLIED}: 库里没有订单 {order_no}"
                        f"（栈缺 seed？见 fixtures/mibao_eval_seed.sql）"
                        f"—— 该用例的生成前置**未复位**，结论不可归因于 agent")
        finally:
            await conn.close()
    except Exception as e:
        return (f"未复位订单 {order_no}（DB 不可达/失败: {type(e).__name__}: {e}）"
                f"—— 若本用例首跑把该订单转成了 producing，重试前置将与首次不等价")
    return (f"已复位订单 {order_no} → confirmed"
            f"（清掉 {len(cleared or [])} 张在途加工单）")


# ── pre_clean 支持的类型（**单一事实源**，issue #3781）─────────────────────────
# 为什么必须有一个显式登记表：`_run_pre_clean` 对未知 type 的旧行为是
# `return f"未知 pre_clean 类型: {_type}（跳过）"` —— 调用侧只把它当消息打印
# （`🧹 pre_clean: …`），**不进该用例的结论** ⇒ **拼错/未实现的 type = 静默跳过**：
# 数据没准备、用例照跑。这是标准的假绿温床（`migao-acceptance`「空跑：绿了但没跑」），
# 而且恰恰在"新增一个 type"时最危险 —— 新类型没被 runner 认出来就退回成"什么都没做"。
# 现在：① 本集合是唯一真值；② 未登记的 type 走 **config_error**（进用例结论）；
# ③ L0 静态不变式（`tests/unit_ci_workflows/test_eval_preclean_registry.py`）锁
# 「用例库里出现的每个 type 都必须在此登记」——拼错在 CI 直接红。
_PRECLEAN_TYPES = frozenset({
    "product_remove",          # 建品残留清理（下架→删除）
    "product_dedupe",          # 同名商品去重（保留最早创建 = 种子）
    "customer_tag_remove",     # 客户标签清理（写类 case 自我污染防线）
    "user_memories_clear",     # 用户级长期记忆清理（post_session 断言前）
    "aftersales_ticket_prepare",   # 工单复位回 seed 初始态
    "employee_reactivate",     # 员工恢复 active（支持 employee_phone 精确定位）
    "employee_remove",         # 员工删除（HR-002 产物清理；#3781 新增）
    "processing_order_reset",  # 加工单用例自清理：订单复位 confirmed + 清掉本用例生成的加工单
                               # （issue #3833，PG-013；#3800 扫描判据漏掉的新实例）
})

# ── pre_clean 的**两族语义**（issue #3791；判定跑 34865780382 的 CU-003 假红）──────
# 为什么必须分族：`_PRECONDITION_NOT_APPLIED`（#3781）的语义是「用例**依赖**的前置不在位」
# ⇒ 用例带着假前置跑完 ⇒ 结论不可归因于 agent。但**清理型**（remove/delete）的前置语义
# **相反** —— 它要求的是「该对象**不在**脏状态」：
#   · 目标本就不存在 ⇒ 前置**已满足**（no-op 即成功）⇒ **不得进结论**（至多 ℹ️）；
#   · 旧实现把这一格也标成 `_PRECONDITION_NOT_APPLIED` ⇒ **良性 no-op 被判失败**：
#     实测 run 34865780382 的 CU-003（`customer_tag_remove` 的目标标签不在目录里）被折成
#     score=0 ⇒ 它又在 `KEY_JOURNEYS_MIBAO` 里 ⇒ 整条 B 端腿 `completion.ok=false`
#     （`journey_failures=["CU-003"]`）。同一格在 #3781 之前是静默跳过、用例**通过**
#     （⑤ 的 CU-003 条目 score=1.0）⇒ 这是**过度扩大**（假红），不是修好的洞。
# 准备型（create/prepare/reactivate/dedupe/断言前置）**不受影响**：未应用**必须**进结论。
#
# 新增 type 时必须**显式选族**（L0 不变式锁死）——"目标不存在"算不算问题是由**前置语义**
# 决定的，不允许默认落到任何一边。
_PRECLEAN_CLEANUP_TYPES = frozenset({
    "product_remove",       # 建品残留清理：目标商品不存在 = 没什么可清
    "customer_tag_remove",  # 客户标签清理：标签不在目录 / 客户没这个标签 = 没什么可清
    "employee_remove",      # 员工删除（#3788，HR-002「谁造的谁清」）：首跑还没造出重名员工
                            # ⇒ **良性 no-op**。⚠️ 本任务最容易踩错的一格：把它算成
                            # "前置未应用"会**复活 HR-002/HR-003 的恒红**
                            # （`test_eval_preclean_registry.py` 有专项守卫）。
})
# ⚠️ `processing_order_reset`（#3833）**有意不在清理型**里 ⇒ 落进**准备型**：
# 它要求的是**肯定式**前置（"用例点名的那张种子订单**在**、且是 confirmed 且无加工单"），
# 与 `aftersales_ticket_prepare` 同族。清单不存在（栈缺 seed）⇒ `_PRECONDITION_NOT_APPLIED`
# ⇒ 折进用例结论，**不得**静默放过（那正是 #3781 要堵的"带着假前置跑完"）。

# 配置错误的**稳定前缀**：`_pre_clean_for_case` 据此把它们折进用例结论
# （形态对齐 `db_verify: 不支持的 fetch 配置` → 签名折叠成 `config_error(db_verify)`）。
_PRECLEAN_CONFIG_ERR = "pre_clean: 不支持的 type"

# 「**前置未应用**」的稳定标记（issue #3781，**只对准备型有意义**）。两类：
#   · `_PRECLEAN_CONFIG_ERR`      —— 夹具层配置错误（type 未知/未实现）⇒ 数据压根没准备；
#   · `_PRECONDITION_NOT_APPLIED` —— 夹具层**该在位的目标状态不存在**（员工/工单查不到）⇒
#     用例带着**假前置**跑完，旧实现只打印一行日志（`migao-acceptance`「空跑：绿了但没跑」同族）。
# 处置：折进用例结论（score=0 + 进 summary 的 `failures`，形态对齐
# `db_verify: 不支持的 fetch 配置` → `config_error(db_verify)`），并在重试边界
# 复用同一标记表达"第二次尝试的前置与首次不等价"（#3751 标记语义从"复位失败"扩到
# "前置压根没被应用"）。
# ⚠️ **清理型不适用本标记**（issue #3791）：目标不存在 = 前置**已满足**，走
# `_PRECLEAN_NOOP`（可见但不进结论）。判据由 `_classify_preclean_message` **单点**保证。
_PRECONDITION_NOT_APPLIED = "pre_clean: 前置未应用"
_PRECLEAN_BAD_MARKERS = (_PRECLEAN_CONFIG_ERR, _PRECONDITION_NOT_APPLIED)

# 清理型「目标本就不存在」的**良性 no-op** 稳定标记（issue #3791）。它**不是**坏标记：
#   · 不进结论（不在 `_PRECLEAN_BAD_MARKERS` 里）⇒ 良性清理不会被判成失败；
#   · 但必须**可见**（随 `pre_clean` 字段落盘）：#3781 的初衷是"清理防线有没有真的生效"
#     不能只靠一行日志 —— 若名字拼错（如 CU-003 的 `VIP2活跃` vs 种子目录的 `VIP2`/`活跃`），
#     本标记就是"这条用例的清理防线空转"的书面证据（见 issue #3794）。
_PRECLEAN_NOOP = "pre_clean: 清理型目标不存在（良性 no-op）"


def _cleanup_noop_message(spec: dict, detail: str) -> str:
    """清理型（remove/delete）目标不存在时的**良性 no-op** 文案（单一事实源，纯函数）。

    为什么不复用 `_PRECONDITION_NOT_APPLIED`：那是"用例**依赖**的前置不在位"（夹具层缺口）。
    清理型的前置是**否定式**的（"该对象不该在脏状态"）—— 目标不存在恰恰**满足**它。
    ⚠️ 措辞红线（#3751）：良性路径的消息不得含「未复位」/「失败」——`_reset_for_retry`
    据此判"重试前置与首次不等价"，误判会把结论标成不可归因于 agent。
    """
    return (f"{_PRECLEAN_NOOP}: {spec.get('type')} 的目标不存在（{detail}）"
            f"—— 清理型前置的目标本就不该存在，no-op 即成功 ⇒ 不进结论；"
            f"若这是**拼错的名字**（如 CU-003 的 `VIP2活跃` vs 种子目录 `VIP2`/`活跃`），"
            f"说明该用例的清理防线在空转，需登记到 issue（issue #3794）")


def _classify_preclean_message(spec: dict, msg: str) -> str:
    """按**族**归类 `_run_pre_clean_action` 的原始消息（纯函数，单点保证 #3791）。

    · 清理型（`_PRECLEAN_CLEANUP_TYPES`）：目标不存在 = **前置已满足** ⇒ 把误标的
      `_PRECONDITION_NOT_APPLIED` **降级**成 `_PRECLEAN_NOOP`（不进结论）。放在这里而不是
      只改调用点，是为了让**将来新增的清理型**不可能重新引入同一种假红。
    · 其余（准备型 + 配置错误）：**原样返回** ⇒ #3781 的成果不退化（未应用照旧进结论）。
    """
    t = str((spec or {}).get("type") or "")
    if t in _PRECLEAN_CLEANUP_TYPES and str(msg).startswith(_PRECONDITION_NOT_APPLIED):
        return _cleanup_noop_message(spec, str(msg).split(":", 2)[-1].strip())
    return msg


def preclean_specs_for_retry(case) -> list:
    """**重试前置复位的 opt-in 判据**（纯函数，issue #3751 裁定条件 3；#3833 抽出）。

    为什么抽成函数：这条判据就是"用例要不要在重试前复位"的**唯一真值**——
    `PG-013` 的假红（判定跑 34908262839）正是「没声明 `pre_clean` ⇒ 不复位 ⇒
    第 2 次尝试的前置 = 首跑改坏后的状态」。#3800 的扫描表也按同一件事分档。

    ⚠️ 抽出来的副作用是**可测**：`tests/unit_ci_workflows/test_eval_case_asset_truth.py`
    用它做「改前不等价 / 改后等价」的确定性复算（零 LLM、零栈）。
    复位动的是**共享数据**，全局复位会伤到别的用例依赖的状态 ⇒ 必须按用例 opt-in。
    """
    return list(getattr(case, "pre_clean", None) or [])


def unbacked_customer_tag_removals(cases: list, seed_tag_names) -> list:
    """声明 `customer_tag_remove.tag_name` 但**种子标签目录里没有该标签**的用例（纯函数）。

    为什么必须有一条静态不变式（#3794 的后果① + issue #3832 的复核）：
    `customer_tag_remove` 按 `tag_name` 在**标签目录**里找 id，找不到就整条清理**空转** ——
    用例声明的"写类 case 自我污染防线"从未生效，**而报告里只是一条良性 no-op**
    （#3791 之后甚至不进结论）⇒ 只能靠人逐字读 `pre_clean` 字段才发现。
    实测两次 run 都命中：`CU-003` 的 `tag_name: "VIP2活跃"` vs 种子目录 `VIP2` / `活跃`。

    ⇒ 把"声明名 ↔ 种子目录"的一致性做成**可静态审计的纯函数**（由
    `tests/unit_ci_workflows/test_eval_case_asset_truth.py` 的 L0 调用），
    让"拼错的名字"在合并前就红，而不是等到某次全量跑里偶然被读出来。

    返回人读问题串（空列表 = 全部有据）。
    """
    seed = {str(x).strip() for x in (seed_tag_names or []) if str(x).strip()}
    out = []
    for c in cases or []:
        cid = str(getattr(c, "id", "") or "?")
        for spec in (getattr(c, "pre_clean", None) or []):
            if not isinstance(spec, dict) or str(spec.get("type") or "") != "customer_tag_remove":
                continue
            name = str(spec.get("tag_name") or "").strip()
            if name and name not in seed:
                out.append(f"{cid}: pre_clean 的 tag_name={name!r} 不在种子标签目录 "
                           f"{sorted(seed)} 里 —— 该清理会结构性空转（#3794）")
    return out


def namespace_claims(case) -> set:
    """用例声明的全局命名空间键（`EvalCase.namespaces`，形态 `<kind>:<值>`）——纯函数。

    为什么是**声明式**而不是让 runner 去猜：命名空间是**用例资产的知识**
    （"我依赖哪个客户手机号 / 哪个员工姓名 / 哪个商品名"），runner 无法从工具调用可靠
    反推（同一个 `order_create` 既可以写张三的单也可以写李四的）。声明出来 ⇒ 可静态
    审计（L0 守卫：声明必须与 `user_inputs` 里的字面量对得上，防"声明了没用的键"
    导致隔离形同虚设）。
    """
    return {str(k).strip() for k in (getattr(case, "namespaces", None) or []) if str(k).strip()}


def namespace_conflict_groups(cases: list) -> dict:
    """按命名空间键分组，返回**只有一条声明**之外的争用组 `{key: [case_id, …]}`。

    为什么需要（issue #3781）：同栈并行用例互写同一全局命名空间是**假红的结构性来源**
    （HR-002 造第二个「王五」⇒ HR-003 目标不唯一；OR-016/CR-001/CH-010 在同一个手机号下
    建单 ⇒ AS-003 的"唯一目标单"前置被实时改写）。有交集的用例必须**互不重叠**。
    """
    owner: dict = {}
    for c in cases or []:
        for k in sorted(namespace_claims(c)):
            owner.setdefault(k, []).append(str(getattr(c, "id", "") or "?"))
    return {k: ids for k, ids in owner.items() if len(ids) > 1}


def needs_serial_lane(case, ns_conflicted_ids=frozenset()) -> bool:
    """用例**主体**是否必须独占执行（纯函数，便于 L0 单测与代价测量）。

    判据（issue #3361 提速第三轮 + #3781）：
      · 标签 `id_reuse`/`update`/`full_lifecycle`（商品改价类：跑前快照、跑后恢复同一批
        商品，整个用例期间都持有共享商品状态）；
      · 声明 `post_session`（断言用户级长期状态，运行中写 user_memories，而所有用例共用
        同一个评测顾客）；
      · **命名空间撞车**（`ns_conflicted_ids` 里的用例）：撞车的两条必须互不重叠，
        否则其中一条的产物会改掉另一条的前置。

    ⚠️ **不用**「声明了 pre_clean 就整体独占」：实测那是**加性**成本（C 端 OR-014 一个人
    跑 ~5.5min 把 10.2min 的评测顶到上限）——pre_clean 只是"评测前把共享数据清干净"的
    **短写动作**，真正需要隔离的只有这个动作（见 `_run_one_case` 的 pre_clean 独占窗口），
    用例主体各自建数据，可以并行。
    """
    tags = set(getattr(case, "tags", None) or [])
    return bool(tags & {"id_reuse", "update", "full_lifecycle"}) \
        or bool(getattr(case, "post_session", None)) \
        or str(getattr(case, "id", "") or "") in set(ns_conflicted_ids or ())


def serialize_seconds(cases: list, durations: dict, concurrency: int = 6) -> dict:
    """**代价模型**（纯函数，零 LLM）：估算调度方案的墙钟下界，便于把"隔离的代价"量化。

    模型（保守 = 给出下界，真实墙钟只会更长，因为还有 LLM 方差与重试尾巴）：
      · 并行道：`max(Σ并行时长 / 并发度, 最长单条)` —— 并发度槽位被占满的理想摊派；
      · 串行道：Σ串行时长 —— 串行用例**互不重叠**（这正是隔离的定义）；
      · 两者**可以重叠**（读写门的语义：读者排空即进入，不阻塞整批）⇒ 取 max。
    真实调度的 `ConcurrencyGate` 更细（并行用例持读位、串行用例持写位），本模型是它的
    上界近似；用于**比较两种方案谁更贵**足够（比值稳定，不依赖具体实现细节）。

    为什么要有它：`migao-dev-flow` §17.4 要求"不要只声明『几乎免费』"——
    PR 里写"隔离代价 X 秒"必须是算出来的，而不是感觉出来的。
    """
    ns = namespace_conflict_groups(cases)
    conflicted = {i for g in ns.values() for i in g}
    par, ser = [], []
    for c in (cases or []):
        d = float(durations.get(str(getattr(c, "id", "") or ""), 0.0) or 0.0)
        (ser if needs_serial_lane(c, conflicted) else par).append(d)
    k = max(1, int(concurrency or 1))
    parallel_s = max((sum(par) / k), (max(par) if par else 0.0))
    serial_s = sum(ser)
    return {"cases": len(cases or []), "parallel_lane": len(par), "serial_lane": len(ser),
            "conflict_groups": len(ns), "parallel_s": round(parallel_s, 1),
            "serial_s": round(serial_s, 1), "wall_s": round(max(parallel_s, serial_s), 1)}


async def _eval_find_users(client, headers, name: str = "", phone: str = "") -> list:
    """按**姓名 / 手机号**精确查员工账号（评测前置的数据层基元，issue #3781）。

    为什么单独抽出来（真实 run 34856561459 的 `HR-003` 假红铁证）：
    旧 `employee_reactivate` 的实现是 `GET /api/admin/users?page=1&size=50` 后
    `next(u for u in items if u.get("name") == name)` —— **拿第一条同名**。
    而同 run 的 `HR-002`（创建员工-开账号）会创建**第二个同名「王五」**
    （`13812345678`，种子里的是 `debug_employee_wangwu / 13700137000`）⇒
    `HR-003` 跑到 `employee_manage` 查询时 `users=2 total=2`，agent 给出**正确**的
    安全行为（「系统里有两个「王五」…我需要知道停用哪一个才能安全执行」），
    而 `employee_manage(action=toggle_status, status=disabled)` 永不成立 ⇒
    标准全量跑法下**恒红**；且 `HR-003` 在 `KEY_JOURNEYS_MIBAO` 里 ⇒
    B 端 `completion.ok` 被**永久**压住。这**不是**产品缺陷，是用例资产缺陷。

    故本基元：分页取全（`size=200`，旧实现的 50 条上限本身也会漏），
    并按 **name 精确 + phone 精确（做数字归一）** 双条件过滤 ——
    手机号是员工的**唯一**标识（`HR-008` 已按 #3568 的「显式指代」范式用手机号点名），
    用它定位可让用例对"同名残留"免疫。
    """
    want_name = str(name or "").strip()
    want_phone = re.sub(r"\D", "", str(phone or ""))
    if not want_name and not want_phone:
        return []
    out = []
    for page in (1, 2):
        r = await client.get(f"{ADMIN_API}/api/admin/users", headers=headers,
                             params={"page": page, "size": 200}, timeout=15)
        items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
        for u in items:
            if want_name and str(u.get("name") or "").strip() != want_name:
                continue
            if want_phone and re.sub(r"\D", "", str(u.get("phone") or "")) != want_phone:
                continue
            if u not in out:
                out.append(u)
        if len(items) < 200:
            break
    return out


async def _eval_remove_users(client, headers, name: str = "", phone: str = "") -> int:
    """删除匹配的员工账号（`HR-002` 产物清理专用，issue #3781）；返回删除条数。

    走 `DELETE /api/admin/users/{id}`（`AdminUserController.deleteUser` @`:268`，
    无请求体；与 `employee_manage` 的 `delete` action 同一路径与权限码
    `employee:create` —— `app/tools/employee_manage.py:_delete_user` 传的就是裸 DELETE）。
    """
    removed = 0
    for u in await _eval_find_users(client, headers, name, phone):
        uid = u.get("id")
        if not uid:
            continue
        r = await client.delete(f"{ADMIN_API}/api/admin/users/{uid}",
                                headers=headers, timeout=15)
        if r.status_code < 300:
            removed += 1
    return removed


async def _run_pre_clean(token: str, spec: dict) -> str:
    """评测前数据清理（写类 case 自我污染防线，§14.2/CU-003）——**唯一对外入口**。

    issue #3791：本入口只做一件事 —— 把动作层的结果按**族**归类
    （`_classify_preclean_message`）。清理型的"目标不存在"是良性 no-op（不进结论），
    准备型的"前置未应用"照旧进结论（#3781 不退化）。判据在**一处**，动作实现在
    `_run_pre_clean_action`（调用方/测试只需要本函数）。
    """
    return _classify_preclean_message(spec, await _run_pre_clean_action(token, spec))


async def _list_products_matching(client, token: str, keyword: str, size: int = 20) -> list:
    """按关键词列商品，并只保留**名字真的含该关键词**的项（issue #3835 抽出的**单一真相源**）。

    为什么必须只有这一份定义：服务端 `GET /api/admin/products?keyword=` 是**模糊匹配**
    （`product_search` 语义），会带上「星空全遮光窗帘」这类只沾边的名字；而 `product_remove` /
    `product_dedupe` 要的是"**同名/子串命中**"这个**精确**口径。三处（两个清理动作 +
    `_probe_product_count` 前置探针）若各写一份"怎么算命中"，就会出现"清理按子串、计数按模糊"
    的口径漂移 —— 前置断言与清理动作对不上号（`migao-dev-flow` §18 单一真相源）。

    返回原始 item 列表（order 保持服务端顺序）；调用方自行决定保留/删除。
    """
    r = await client.get(f"{ADMIN_API}/api/admin/products", headers=_admin_headers(token),
                         params={"keyword": keyword, "page": 1, "size": size}, timeout=15)
    items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
    return [p for p in items if keyword in str(p.get("name", ""))]


async def _run_pre_clean_action(token: str, spec: dict) -> str:
    """一次 pre_clean 动作的**实现体**（原始消息；族归类见 `_run_pre_clean`）。

    支持类型：
    - customer_tag_remove: 移除「customer_keyword 匹配的第 customer_index 位客户」
      上的 tag_name 标签（case 每次成功 add_tag 即污染生产数据 → 下一跑幂等拒绝，
      在 run_case 前把目标客户标签清干净，保证写流程从干净状态开始）。
    - employee_remove: 删除匹配的测试员工（`HR-002` 产物「王五/13812345678」清理）——
      **幂等**：不存在即返回 0 条（不是错误），符合"清理成功"语义。
    - employee_reactivate: 恢复被评测禁用的测试员工；**支持 employee_phone 精确定位**
      （#3781：只用姓名会命中同名残留 → 目标不确定 → 用例恒红）。

    ⚠️ 调用时机（issue #3751）：本函数是**前置**动作，只允许在**一次尝试开始之前**执行；
    `run_suite` 在首次尝试前与**每次重试前**都会调用它（attempt 边界），但绝不在
    `run_case`/`db_verify` 之后调用 —— 否则会把该次尝试的真实产物抹掉（红线）。

    ⚠️ 消息措辞红线（#3751）：`_run_one_case._reset_for_retry` 靠子串
    「未复位」/「失败」判"复位没成功" ⇒ **成功路径的消息不得含这两个词**。
    """
    _type = spec.get("type", "")
    if _type == "product_remove":
        # 清理建品测试残留（下架→删除，on_sale 不能直接删）：多次建品「测试窗帘」
        # 等残留 → 全量评测重名冲突（agent 发现已存在 → 澄清 → create 未达）。
        kw = str(spec.get("product_keyword", ""))
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            items = await _list_products_matching(c, token, kw)
            removed = 0
            for p in items:
                pid = p.get("id")
                await c.put(f"{ADMIN_API}/api/admin/products/{pid}/status", headers=h,
                            json={"status": "off_sale"}, timeout=15)
                await c.delete(f"{ADMIN_API}/api/admin/products/{pid}", headers=h, timeout=15)
                removed += 1
            return f"已清理 {removed} 个「{kw}」商品" if removed else f"无「{kw}」商品需清理"
    if _type == "product_dedupe":
        # 同名商品去重（Round 72 审计：3 件同名「遮光窗帘」¥100 是 6 个 case
        # 「确定性根因」的源头——agent 发选择卡 case 无槽位应答 → 目标工具
        # 从不执行）。按关键词清理重复：同名同价 >1 时保留最早创建（种子，
        # 加工项最全），删其余（下架→删除）。
        kw = str(spec.get("product_keyword", ""))
        price = spec.get("price")  # 可选：限定价格
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            matched = [p for p in await _list_products_matching(c, token, kw)
                       if price is None or p.get("price") == price]
            if len(matched) <= 1:
                return f"「{kw}」无重复（{len(matched)} 件），无需去重"
            # 保留最早创建的（createdAt 最小）——种子商品
            matched.sort(key=lambda p: str(p.get("createdAt") or ""))
            keeper = matched[0]
            removed = 0
            for p in matched[1:]:
                pid = p.get("id")
                await c.put(f"{ADMIN_API}/api/admin/products/{pid}/status", headers=h,
                            json={"status": "off_sale"}, timeout=15)
                await c.delete(f"{ADMIN_API}/api/admin/products/{pid}", headers=h, timeout=15)
                removed += 1
            return f"已去重「{kw}」：删 {removed} 件重复，保留种子 {keeper.get('id','')[:8]}"
    if _type == "employee_reactivate":
        # 恢复被评测禁用的测试员工（HR-003 存量状态消耗）：王五被禁用后
        # agent 合理说「已停用无需操作」→ 评测前恢复 active。
        # Round 75：查不到时重试 2 次（网络波动 _safe_json 降级返回空 →
        # 误报「不存在」跳过 → 王五未恢复 → agent 见 disabled 合理不操作 → 失败）
        # issue #3781：**加 phone 精确定位 + 多命中全恢复** ——
        #   · 只给 employee_name 时会命中同名残留（HR-002 造的第二个「王五」），
        #     旧实现 `next(...)` 取第一条 ⇒ 恢复的对象不确定 ⇒ HR-003 恒红；
        #   · `employee_phone` 一旦声明即按「姓名 ∧ 手机号」双条件定位（唯一）；
        #   · 命中多条时**全部**恢复为 active（幂等、无副作用）并如实报出条数 ——
        #     不静默取第一条（那是本 bug 的形态），也不报错中断（前置动作不该伪装成用例失败）。
        name = str(spec.get("employee_name", ""))
        phone = str(spec.get("employee_phone", "") or "")
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            targets = []
            for attempt in range(3):
                targets = await _eval_find_users(c, h, name, phone)
                if targets:
                    break
            _who = f"「{name}」" + (f"（手机号 {phone}）" if phone else "")
            if not targets:
                # #3781：**前置未应用**要进结论（旧文案「查询 3 次未命中（跳过）」只打印一行
                # ⇒ "员工没被复位"与"agent 不会停用员工"在报告里同形，本仓库踩过的形态）。
                return (f"{_PRECONDITION_NOT_APPLIED}: 员工 {_who} 查询 3 次未命中"
                        f"—— 该用例的停用前置**未复位**（栈缺 seed？见 fixtures/mibao_eval_seed.sql）")
            changed = 0
            for t in targets:
                if t.get("status") == "disabled":
                    await c.put(f"{ADMIN_API}/api/admin/users/{t.get('id')}/status",
                                headers=h, json={"status": "active"}, timeout=15)
                    changed += 1
            if not changed:
                return f"员工 {_who} 状态 {targets[0].get('status')}，无需恢复"
            if len(targets) > 1:
                return (f"已恢复 {changed}/{len(targets)} 个同名员工 {_who} 为 active"
                        f"（同名 {len(targets)} 个：声明 employee_phone 可精确定位）")
            return f"已恢复 {_who} 为 active（防存量消耗）"
    if _type == "employee_remove":
        # 删除匹配的测试员工（幂等清理；#3781）。
        # 用途：HR-002 每跑一次就往**全局命名空间**里放一个「王五/13812345678」，
        # 而 HR-003 的 pre_clean 只能改状态、**消不掉重名** ⇒ 标准全量跑法下
        # HR-003 目标不唯一 ⇒ 恒红（且它是 KEY_JOURNEY ⇒ 永久压住 B 端 completion.ok）。
        # 本类型是该病灶的**根治**：谁造的谁清（HR-002 声明 employee_remove）。
        name = str(spec.get("employee_name", ""))
        phone = str(spec.get("employee_phone", "") or "")
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            removed = await _eval_remove_users(c, h, name, phone)
        _who = f"「{name}」" + (f"（手机号 {phone}）" if phone else "")
        # ⚠️ 措辞红线：不含「未复位」/「失败」（见 docstring）
        return (f"已清理 {removed} 个测试员工 {_who}"
                if removed else f"无 {_who} 员工需清理（幂等）")
    if _type == "user_memories_clear":
        # 清掉**上一轮会话**flush 落库的长期记忆（issue #3544 收口批）：
        # `post_session[user_memories]` 断言的是「用户级长期状态」，共享/复用栈上会被上轮
        # 残留满足（或反向：上一跑的残留让本跑的"新增"判定失真）→ 评测前先清干净。
        # 端点已存在（`DELETE /api/chat/memories`，api/chat.py:2018，个保法删除权），
        # 无需新增 API/DB 直连。
        agent_type = str(spec.get("agent_type") or "xiaobu")
        async with httpx.AsyncClient() as c:
            r = await c.delete(f"{AI_API}/api/chat/memories",
                               headers=_chat_headers(token),
                               params={"agent_type": agent_type}, timeout=15)
            body = _safe_json(r, {}) or {}
            if r.status_code >= 300 or body.get("success") is False:
                return (f"清理长期记忆失败（HTTP {r.status_code}）"
                        f"—— 不计入断言，仅提示 post_session 可能受残留影响")
            return f"已清理长期记忆（agent_type={agent_type}）"
    if _type == "aftersales_ticket_prepare":
        # 把**被用例点名的**工单复位回 seed 初始态（issue #3751 前置等价性）。
        # 旧实现只保证"栈里存在 pending 工单"——`已有 N 张 pending 工单` 就直接 return
        # （run 34849029334 的 summary 原文即此），于是 AS-004 首跑把
        # `tkt_eval_as_9001`（AS-20260914-9001）关掉后，**重试**看到的是 closed ⇒
        # agent 合理地"不再关闭"（末次 trace：「这条工单不用再关了……当前已经是「已关闭」状态」）
        # ⇒ 重试必红，且两次失败成因不同 → 指纹漂移 → 旧口径误判 unstable 放行。
        # 复位对象 = 用例点名的那张（默认 seed 工单 AS-20260914-9001；`ticket_no` 可覆盖）。
        # ⚠️ 旧的"无 pending 就用真实订单建一张退款工单"回落**已移除**：本用例点名的是一张
        # **特定的**工单（`AS-20260914-9001`），建一张随机工单既满足不了用例输入，也会
        # 让 db_verify 指向别的对象（#3544/#3568 正是为消除这种不确定性才点名的）。
        # seed 工单缺失 = 栈的 seed 没装（数据层问题），如实报出来（归因可见），不静默兜底。
        ticket_no = str(spec.get("ticket_no") or _SEED_AFTERSALES_TICKET_NO)
        return await _reset_aftersales_ticket(ticket_no)
    if _type == "processing_order_reset":
        # 加工单用例的前置复位（issue #3833）：把**用例点名的那张专用种子订单**复位回
        # seed 初始态（confirmed + 清掉本用例生成的加工单）⇒ 重试前置与首跑等价。
        # 为什么这是**准备型**而不是清理型：它要求的前置是**肯定式**的
        # （"点名的订单在、且是 confirmed 且无在途加工单"）—— 订单不存在 = 栈缺 seed
        # ⇒ 必须走 `_PRECONDITION_NOT_APPLIED` 折进结论，不得静默放过（#3781）。
        # `order_no` 必填：**不做**任何子串/模糊匹配，唯一默认值是 PG-013 的专用种子订单
        # （seed 注释：「EVAL-MB-ORD-0002 = PG-013 加工单生成用」）。
        return await _reset_processing_order(
            str(spec.get("order_no") or _SEED_PROCESSING_ORDER_NO))
    if _type not in _PRECLEAN_TYPES:
        # 配置错误，**不是**静默跳过（issue #3781）：旧行为 `（跳过）` 只被打印一行，
        # 用例照跑 ⇒ "数据压根没准备"在报告里读不出来。现在走稳定前缀，由
        # `_pre_clean_for_case` 折进用例结论（score=0 + 进 summary 的 failures）。
        return (f"{_PRECLEAN_CONFIG_ERR}: {_type!r}（该用例的数据准备**未执行**，"
                f"结论不可归因于 agent）—— 合法类型见 local_runner._PRECLEAN_TYPES: "
                f"{sorted(_PRECLEAN_TYPES)}")
    # ── customer_tag_remove（登记表里的最后一个 ⇒ 落到这里即它；其余情况是
    #    "登记了但漏写实现体"，同样走配置错误，不许退回静默）──
    if _type != "customer_tag_remove":
        return (f"{_PRECLEAN_CONFIG_ERR}: {_type!r} 已登记但未实现（数据准备**未执行**）"
                f"—— 请补实现或从 _PRECLEAN_TYPES 移除")
    async with httpx.AsyncClient() as c:
        h = _admin_headers(token)
        kw = str(spec.get("customer_keyword", ""))
        idx = int(spec.get("customer_index", 0) or 0)
        r = await c.get(f"{ADMIN_API}/api/admin/customers", headers=h,
                        params={"keyword": kw, "page": 1, "size": 10}, timeout=15)
        items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
        if idx >= len(items):
            return f"客户「{kw}」索引 {idx} 不存在（共 {len(items)} 位）"
        customer = items[idx]
        cid = customer.get("id")
        r = await c.get(f"{ADMIN_API}/api/admin/customer-tags", headers=h, timeout=15)
        data = (_safe_json(r, {}) or {}).get("data") or {}
        tags = data if isinstance(data, list) else (data.get("tags") or data.get("items") or [])
        tag_id = next((t.get("id") for t in tags
                       if isinstance(t, dict) and t.get("name") == spec.get("tag_name")), None)
        if not tag_id:
            # 标签目录里没有该标签 ⇒ 本次清理**无从施加**。但本类型是**清理型**：
            # 它要求的前置是「该标签**不在**目标客户身上」—— 目录里没有它 ⇒ 前置**已满足**
            # ⇒ **良性 no-op，不得进结论**（issue #3791：旧实现标 `_PRECONDITION_NOT_APPLIED`
            # ⇒ CU-003 被折成 score=0 ⇒ 它在 `KEY_JOURNEYS_MIBAO` 里 ⇒ 压掉整条 B 端腿的 ok）。
            # 但仍**必须可见**（否则"写类 case 的自我污染防线有没有真的生效"读不出来）：
            # 名字拼错时本标记就是防线空转的书面证据（CU-003 的 `VIP2活跃` vs 种子目录的
            # `VIP2`/`活跃`，见 issue #3794）。
            return _cleanup_noop_message(spec, f"标签「{spec.get('tag_name')}」不在标签目录里")
        if tag_id in (customer.get("tags") or []):
            await c.delete(f"{ADMIN_API}/api/admin/customers/{cid}/tags/{tag_id}",
                           headers=h, timeout=15)
            who = customer.get("name") or customer.get("phone") or cid
            return f"已清理 {who} 的「{spec.get('tag_name')}」标签"
        return f"客户无「{spec.get('tag_name')}」标签，无需清理"


# ── Auth ──

async def _retry_502(desc: str, fn, *args, max_retries: int = 6, **kwargs):
    """502/连接失败重试（Round 76：多会话并发部署窗口打断评测——等待部署
    结束自愈续跑，替代直接失败退出）。纯逻辑错误（400/401/403/404）不重试。"""
    import asyncio as _asyncio
    last = None
    for attempt in range(max_retries):
        try:
            return await fn(*args, **kwargs)
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadTimeout,
                httpx.ReadError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            last = e
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code in (502, 503, 504):
                last = e
            else:
                raise
        except RuntimeError as e:
            # 上层已格式化的 502 错误（"登录失败: HTTP 502 ..." / "创建会话失败: HTTP 502"）
            if "502" in str(e) or "502" in str(getattr(e, "args", "")):
                last = e
            else:
                raise
        if attempt == max_retries - 1:
            raise last
        wait = 20 * (attempt + 1)
        print(f"  ⏳ {desc} 遇 502/网络波动（第 {attempt+1} 次）——等待 {wait}s 重试（部署窗口自愈）")
        await _asyncio.sleep(wait)
    raise last


async def login() -> str:
    """获取测试 token（CI 模式直接返回空字符串，走 SERVICE_TOKEN 无 auth）"""
    async def _do_login() -> str:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{ADMIN_API}/api/auth/sms/login",
                             json={"phone": PHONE, "code": BYPASS_CODE}, timeout=10)
            payload = _safe_json(r, {}) or {}
            access_token = (payload.get("data") or {}).get("accessToken")
            if not access_token:
                raise RuntimeError(f"登录失败: HTTP {getattr(r, 'status_code', '?')} {str(getattr(r, 'content', b''))[:200]}")
            return access_token
    # xiaobu 模式：不登录，走 DEBUG customer 身份（X-Debug-Role header 由 send 注入）
    # ⚠️ 必须先于 _retry_502：此前 502 重试重构把 return 提到短路之前，导致
    #    这两个分支变成**死代码** —— xiaobu/CI 模式仍发真实 SMS 登录，本地栈
    #    无用户时 401「该手机号未注册」，评测全部失败（issue #3270 实证）。
    if PERSONA == "xiaobu":
        return ""
    if SERVICE_TOKEN:
        return ""
    return await _retry_502("登录", _do_login)

def _case_debug_user(case) -> str:
    """用例声明的 DEBUG 身份（缺省 ""，见 `debug_user` 字段，issue #3391）。"""
    return getattr(case, "debug_user", "") or ""


def _case_debug_permissions(case) -> str:
    """用例声明的 DEBUG 权限码（缺省 "" = 不下发 `X-Debug-Permissions`，issue #4108）。

    **缺省必须与旧版逐字一致**：`""` ⇒ 不发该头 ⇒ 服务端仍给通配 `["*"]`
    ⇒ 全部存量用例行为不变（新机制只对**显式声明**的用例生效）。
    """
    return getattr(case, "debug_permissions", "") or ""


def _chat_headers(token: str, debug_user: str = "",
                  debug_permissions: str = "") -> dict:
    """ai-agent 请求头：调试身份必须显式声明（P0-3 安全加固）

    - xiaobu（C 端）：X-Debug-Role: customer（DEBUG 本地栈/CI 显式注入小布身份）
    - mibao（B 端）+ SERVICE_TOKEN（CI）：X-Debug-Role: mibao——此前不带任何头
      依赖"无 token → DEBUG 静默降级 tenant1 管理员"，服务端已 fail-closed，
      现改为显式声明管理员调试身份，语义不变（eval 仍跑 tenant1 词元通达）。
      `debug_permissions` 非空时追加 `X-Debug-Permissions`（issue #4108）：
      B 端评测默认拿到通配 `["*"]` ⇒ **权限拒绝路径在评测里不可达**；该头让
      **单条**用例以受限员工身份跑，从而产出「越权时不自旋、如实说明、给开通路径」
      的 LLM 层证据。**只在非空时下发** —— 未声明的用例与服务端既有行为逐字一致。
    - 其它（本地真实登录）：Bearer token
    """
    if PERSONA == "xiaobu":
        h = {"X-Debug-Role": "customer"}
        # 多身份评测（issue #3391）：以「无历史订单的新客」身份跑，才能覆盖
        # 「customer_address_query 未命中 → 主动收集收货信息」这条路径
        # （debug_customer_1 有历史订单，该路径原本不可达）。
        # 服务端只认 DEBUG + customer 角色 + `debug_` 前缀白名单（app/utils/auth.py）。
        if debug_user:
            h["X-Debug-User"] = debug_user
        return h
    if SERVICE_TOKEN:
        h = {"X-Debug-Role": "mibao"}
        # 评测可控权限（issue #4108）：服务端只在「DEBUG + 非 customer 调试身份」分支读它，
        # 且严格白名单（拒绝 `*`/空白/空元素），非法值整串回落通配。
        if debug_permissions:
            h["X-Debug-Permissions"] = debug_permissions
        return h
    return {"Authorization": f"Bearer {token}"} if token else {}

async def get_or_create_session(token: str, prefer_new: bool = True,
                                 debug_user: str = "",
                                 debug_permissions: str = "") -> str:
    """获取或创建会话（502 重试：部署窗口自愈）"""
    async def _do() -> str:
        async with httpx.AsyncClient() as c:
            h = _chat_headers(token, debug_user, debug_permissions)
            if prefer_new:
                r = await c.post(f"{AI_API}/api/chat/sessions", headers=h, json={}, timeout=10)
                payload = _safe_json(r, {}) or {}
                sid = (payload.get("data") or {}).get("id")
                if not sid:
                    raise RuntimeError(f"创建会话失败: HTTP {getattr(r, 'status_code', '?')} {str(getattr(r, 'content', b''))[:200]}")
                return sid
            r = await c.get(f"{AI_API}/api/chat/sessions", headers=h, timeout=10)
            sessions = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
            if sessions:
                return sessions[0]["id"]
            r = await c.post(f"{AI_API}/api/chat/sessions", headers=h, json={}, timeout=10)
            payload = _safe_json(r, {}) or {}
            sid = (payload.get("data") or {}).get("id")
            if not sid:
                raise RuntimeError(f"创建会话失败: HTTP {getattr(r, 'status_code', '?')} {str(getattr(r, 'content', b''))[:200]}")
            return sid
    return await _retry_502("创建会话", _do)

async def send_message(token: str, session_id: str, message: str, images: list = None,
                       debug_user: str = "",
                       debug_permissions: str = "") -> dict:
    """发送消息并收集 SSE 事件

    Args:
        message: 文本内容
        images: 可选图片 URL 列表（后端 ChatSendRequest.images，≤3 张，
                https:// 或 /api/files 开头）。带图时后端走多模态/vision 链路
                （图片意图澄清用例端到端验收，issue #2794）。
    """
    body = {"session_id": session_id, "message": message}
    if images:
        body["images"] = images

    async with httpx.AsyncClient(timeout=120) as c:
        h = _chat_headers(token, debug_user, debug_permissions)

        result = {
            "user_message": message,
            "images": images or [],
            "tool_calls": [],
            "tool_results": [],
            "interactive": [],  # SSE interactive 事件（卡片：choice/confirm/form，验收协议 §3.5）
            "final_text": "",
            "error": None,
            "streamed": False,
            "done": False,
        }

        current_event = None
        async with c.stream("POST", f"{AI_API}/api/chat/send",
                            headers=h,
                            json=body) as resp:
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue

                # SSE: event: <name>  or  data: <json>
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        payload = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if current_event == "text":
                        result["final_text"] += payload.get("content", "")
                        result["streamed"] = True
                    elif current_event == "tool_call":
                        tc = {
                            "name": payload.get("tool", ""),
                            "args": payload.get("args", {}),
                        }
                        result["tool_calls"].append(tc)
                    elif current_event == "tool_result":
                        result["tool_results"].append(payload)
                    elif current_event == "interactive":
                        result["interactive"].append(payload)
                    elif current_event == "error":
                        result["error"] = str(payload)
                    elif current_event == "done":
                        result["done"] = True
                    current_event = None

        return result

def _parse_expectation(exp: str) -> tuple[str, dict | None]:
    """解析 'tool(k=v, k2=[a, b])' 期望 → (工具名, args 字典)。

    纯工具名（无括号）→ (工具名, None)。args 值为列表时解析为 list。
    兼容语义描述值（复用上轮 UUID / 本月1号 / 遮光窗帘 等中文值原样保留）。
    """
    m = re.match(r"^([a-zA-Z_]\w*)\s*\((.*)\)\s*$", exp.strip())
    if not m:
        return exp.strip(), None
    tool = m.group(1)
    body = m.group(2)
    args: dict = {}
    for seg in _split_top_level(body, ","):
        seg = seg.strip()
        if not seg or "=" not in seg:
            continue
        k, _, v = seg.partition("=")
        k = k.strip()
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1]
            items = [x.strip().strip('"\'') for x in inner.split(",")]
            args[k] = [x for x in items if x != ""]
        else:
            args[k] = v.strip('"\'')
    return tool, args


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    """按最外层分隔符切分（忽略括号内逗号，如 item_ids=[1, 3, 5]）"""
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


_RE_CJK = re.compile(r"[\u4e00-\u9fff]")

# 只读查询类动作等价组（issue #2854 P0-3 回归修复，HR-004）：
# 工具 read_only_actions 常见 {list, all, detail, query, ...}，LLM 对「看角色列表/有哪些角色」
# 选择 action=all/list/query 均属业务等价合法调用——弱断言时代放行，args 收紧后不能误伤。
# 仅限只读查询语义；写操作（add/update/delete/create…）严格匹配。
_QUERY_ACTION_SYNONYMS: frozenset[str] = frozenset({
    "list", "all", "query", "detail", "get", "search", "view", "page", "list_categories",
})


def _is_query_action_equal(exp_s: str, act_s: str) -> bool:
    """只读查询类 action 是否业务等价（list≈all≈query≈detail）。"""
    return exp_s in _QUERY_ACTION_SYNONYMS and act_s in _QUERY_ACTION_SYNONYMS


def _scalar_value_matches(exp_s: str, act_s: str) -> bool:
    """标量值匹配：中文语义值仅验存在（key 已验）；bool 宽容；数字 str/int 混比；其余字面相等。"""
    if _RE_CJK.search(exp_s):
        # 中文语义描述值：仅 key 存在（旧弱断言兼容）
        return True
    if exp_s.lower() in ("true", "false"):
        # 布尔字面量大小写不敏感：用例 YAML 写 `multiSelect: true`，经 render_cases 渲染成
        # Python `True`（`exp_to_str` 的 f-string），而实际值来自 JSON（`true`）——
        # 按 `exp_s.lower()` 归一后 True/true 两种写法行为一致（run 34856561459 归因线索 #2）。
        truthy = {"true", "1"} if exp_s.lower() == "true" else {"false", "0"}
        return act_s.lower() in truthy
    try:
        return float(exp_s) == float(act_s)
    except ValueError:
        return exp_s == act_s


def _match_nested_dict(expected_dict: dict, actual_list: list) -> str | None:
    """列表内 dict 字段级匹配：期望 dict 每个字段须在某个实际 dict 中命中。

    Returns:
        None 表示命中；否则返回第一个不匹配描述。
    """
    for exp_k, exp_v in expected_dict.items():
        exp_s = str(exp_v).strip()
        # 期望字段须在至少一个实际 dict 中命中（值校验复用标量规则）
        matched = False
        for act_dict in actual_list:
            if not isinstance(act_dict, dict):
                continue
            if exp_k not in act_dict:
                continue
            act_s = str(act_dict[exp_k]).strip()
            if _scalar_value_matches(exp_s, act_s):
                matched = True
                break
        if not matched:
            return f"items[].{exp_k} expected {exp_s!r} not matched"
    return None


def _arg_mismatch_reason(actual: dict, expected: dict) -> str | None:
    """args 关键字段校验：返回第一个不匹配原因；全部匹配返回 None。

    规则（弱断言加固，issue #2854）：
    - key 必须存在于实际 args（关键字段缺失即失败）
    - 列表期望：
      * 元素为 dict → 字段级匹配（order_create items=[{sellingMethod, doorWidth}]
        每个期望 dict 的字段须在某个实际 dict 命中，值校验复用标量规则）——Phase 4
      * 元素为标量（item_ids=[打孔]）→ 实际列表必须包含期望每个元素（str 化子集）
    - 纯 ASCII 标量（action/days/price/component）：宽容相等（数字 str/int 混比、bool 大小写）
    - 含中文标量（复用上轮 UUID / 本月1号 / 遮光窗帘）：语义描述，仅校验 key 存在
      （与旧弱断言兼容，防止把语义描述期望误判为字面值）
    """
    for k, exp_val in expected.items():
        if k not in actual:
            return f"missing arg '{k}'"
        act_val = actual[k]
        if isinstance(exp_val, list):
            if not isinstance(act_val, list):
                act_val = [act_val]
            # 列表内元素为 dict → 字段级匹配（Phase 4，order_create items 结构断言）
            exp_dicts = [x for x in exp_val if isinstance(x, dict)]
            if exp_dicts:
                for exp_d in exp_dicts:
                    reason = _match_nested_dict(exp_d, act_val)
                    if reason:
                        return f"arg '{k}' {reason}"
                # 混有标量元素的，继续走子集语义
                exp_scalars = [x for x in exp_val if not isinstance(x, dict)]
                if exp_scalars:
                    exp_set = {str(x) for x in exp_scalars}
                    act_set = {str(x) for x in act_val if not isinstance(x, dict)}
                    if not exp_set.issubset(act_set):
                        return f"arg '{k}' missing {sorted(exp_set - act_set)}"
                continue
            # 纯标量列表 → 旧子集语义
            exp_set = {str(x) for x in exp_val}
            act_set = {str(x) for x in act_val}
            if not exp_set.issubset(act_set):
                return f"arg '{k}' missing {sorted(exp_set - act_set)}"
            continue
        exp_s = str(exp_val).strip()
        act_s = str(act_val).strip()
        # 只读查询类 action 等价（HR-004：list≈all≈query≈detail，业务等价不误伤）
        if k == "action" and _is_query_action_equal(exp_s.lower(), act_s.lower()):
            continue
        if _scalar_value_matches(exp_s, act_s):
            continue
        return f"arg '{k}' expected {exp_s} got {act_s}"
    return None


def _interactive_satisfies(exp_args, result: dict) -> tuple[bool, str]:
    """`interact` 期望是否可由 **SSE interactive 事件**满足（issue #3270）。

    卡片有三条发射路径，只有第一条产生 `tool_call` 事件：
      1. `interact` 工具调用 → tool_call + interactive 事件
      2. `handoff_offer` 节点（AI 主动建议转人工）→ **仅 interactive 事件**
      3. LLM 幻觉 `<interact>` XML 兜底解析 → **仅 interactive 事件**

    故 `expectations: tool: interact` 若只查 tool_calls，路径 2/3 下永不可能满足
    → 假失败（CI 实证 CH-013：行为正确却 50 分）。这里把「用户看到一张交互卡」
    作为真实语义：工具调用与 interactive 事件任一命中即可。

    exp_args 指定 `component` 时须组件类型一致（防松弛过度）；卡片 payload 里
    **带**该键时也须一致 —— 期望声明了 `multiSelect=true` 却被静默忽略就是弱断言
    （卡片是真单选的也能过；run 34856561459 PR-016 的
    `interact(component=choice, multiSelect=True)` 就是这个"看不出真伪"的形态）。
    卡片**不带**该键时保持旧行为（缺省即单选，旧用例没写该键，不得因补校验而误伤）。
    """
    cards = result.get("interactive") or []
    if not cards:
        return False, "无 interactive 事件"
    want_comp = ""
    want: dict = {}
    if isinstance(exp_args, dict):
        want_comp = str(exp_args.get("component") or "").lower()
        want = {k: v for k, v in exp_args.items() if k != "component"}
    bad_arg = ""
    for card in cards:
        comp = str(card.get("component") or card.get("type") or "").lower()
        if want_comp and comp != want_comp:
            continue
        bad = ""
        for k, exp_v in want.items():
            if k not in card:
                continue                      # 卡片未声明该键 → 维持旧行为（不额外判罪）
            act_v = card[k]
            if isinstance(act_v, bool) or isinstance(exp_v, bool):
                if _scalar_value_matches(str(exp_v), str(act_v)):
                    continue
            elif isinstance(act_v, list):
                if {str(x) for x in act_v} and str(exp_v) in {str(x) for x in act_v}:
                    continue
            elif _scalar_value_matches(str(exp_v), str(act_v)):
                continue
            bad = f"interactive 事件 arg '{k}' expected {exp_v} got {act_v}"
            break
        if bad:
            # 本轮可能下发多张同组件卡：一张不符不等于没有一张符合 → 继续看后面的卡
            # （旧实现多卡时也是"任一命中即过"，不得因补校验而变严）
            bad_arg = bad_arg or bad
            continue
        return True, f"interactive 事件命中（component={comp or '?'}）"
    if bad_arg:
        return False, bad_arg
    return False, f"interactive 事件组件不匹配（期望 {want_comp}）"


def check_expectation(result: dict, expectation: str) -> tuple[bool, str]:
    """检查一条 expectation 是否满足

    支持 OR 逻辑（'A or B'）：任一满足即通过。
    direct_reply 语义（澄清/引导形态）：该轮无 tool_calls 且有 final_text。
    组合形态如 'direct_reply or interact'（模糊意图澄清：文本引导或澄清卡均可）。
    'tool(k=v, ...)' 形态 → args 关键字段校验（issue #2854 P0-3 弱断言加固）。
    """
    exp_lower = expectation.lower()

    # 拆 OR 分支（保持向后兼容：无 or 时等价于单分支）
    parts = [p.strip() for p in expectation.split(" or ") if p.strip()]
    parts_lower = [p.lower() for p in parts]
    has_direct_part = any("direct_reply" in p for p in parts_lower)

    if has_direct_part:
        # direct_reply 分支满足：无工具调用且有文本输出
        if not result.get("tool_calls") and result.get("final_text"):
            return True, "direct reply without tool call"
        # 单值 direct_reply（无 or）→ 维持旧语义：有工具调用即失败
        if len(parts) == 1:
            return False, "expected direct_reply (no tool) but got tool calls"
        # 含 or：direct 分支未命中，继续尝试其他工具分支
        parts = [p for i, p in enumerate(parts) if "direct_reply" not in parts_lower[i]]

    # 反转断言（未被调用 / not called）优先：不受下方工具名匹配干扰
    if "未被调用" in expectation or "not called" in exp_lower:
        for tc in result["tool_calls"]:
            if tc["name"] in exp_lower:
                return False, f"tool {tc['name']} was called but should NOT be"
        return True, "tool not called as expected"

    # 检查 tool 名称 + args 关键字段（支持 OR 逻辑：A or B）
    checked_args = False
    last_args_detail = ""
    for part in parts:
        tool_name, exp_args = _parse_expectation(part)
        p_lower = part.lower()
        if exp_args is None:
            # 纯工具名（跨轮汇总子串匹配，保持向后兼容）
            # xiaobu 模式：expectation 里的 order_query 视为 customer_order_query
            want = p_lower
            if PERSONA == "xiaobu" and "order_query" in want:
                want = want.replace("order_query", "customer_order_query")
            for tn in result.get("__all_tool_names", []):
                if tn.lower() in want:
                    return True, f"tool '{tn}' matched"
            # interact 特例（issue #3270）：卡片可能仅以 interactive 事件下发
            # （handoff_offer 节点 / <interact> XML 兜底），无 tool_call。
            if "interact" in want:
                ok_iv, iv_detail = _interactive_satisfies(None, result)
                if ok_iv:
                    return True, iv_detail
            continue

        # 带 args 期望：本轮 tool_calls 里找名字匹配 + args 关键字段校验
        checked_args = True
        want = tool_name.lower()
        if PERSONA == "xiaobu" and want == "order_query":
            want = "customer_order_query"
        # interact 特例（issue #3270）：卡片可能仅以 interactive 事件下发 →
        # 用事件的 component 校验（等价于 args.component），避免假失败
        if want == "interact":
            ok_iv, iv_detail = _interactive_satisfies(exp_args, result)
            if ok_iv:
                return True, f"tool 'interact' {iv_detail}"
        if not result.get("tool_calls"):
            continue
        for tc in result["tool_calls"]:
            tc_name = str(tc.get("name") or "").lower()
            if tc_name != want and want not in tc_name:
                continue
            reason = _arg_mismatch_reason(tc.get("args") or {}, exp_args)
            if reason is None:
                return True, f"tool '{tc['name']}' matched with key args"
            last_args_detail = f"tool '{tc['name']}' matched but {reason}"

    if checked_args and last_args_detail:
        return False, last_args_detail

    # 检查 success
    if "success=true" in exp_lower or "success=true" in exp_lower:
        if not result.get("error"):
            return True, "success=true (no error)"
        return False, f"expected success but got error: {result['error']}"

    # 检查 error code
    if "error.code=" in exp_lower or "error.code =" in exp_lower:
        expected_code = re.search(r'error\.code\s*=\s*(\w+)', exp_lower)
        if expected_code:
            actual_error = str(result.get("error", ""))
            if expected_code.group(1).lower() in actual_error.lower():
                return True, f"error code matched"
            return False, f"expected error {expected_code.group(1)} but got {actual_error}"

    # 检查 suggestion
    if "suggestion" in exp_lower:
        if result.get("error"):
            return True, "error returned (suggestion may be present)"
        return False, "expected error with suggestion but got success"

    # 兜底：检查 tool 调用
    if "未被调用" in expectation or "not called" in exp_lower:
        for tc in result["tool_calls"]:
            if tc["name"] in exp_lower:
                return False, f"tool {tc['name']} was called but should NOT be"
        return True, "tool not called as expected"

    return False, f"unmatched expectation: {expectation[:80]}"


# ── 跨轮 case 级断言（acceptance-protocol §3.1/§3.4，issue #3033/#3042）──
# 「任意一轮命中即过」只能证明工具链路通，抓不到时序颠倒（confirm 卡先于加工项询问）
# 与 final_text 反模式（幻觉式撤回"尚未真正创建"）——这两类正是人工验收翻车的样本。
# v1.5（2026-09-08 工具自验证补强）：组件/语义限定时序（interact[choice:processing_items]、
# processing_ask 文本询问也算）、必填参数（create 缺 specifications/加工项价格）、
# 确认死循环、假成功——旧会话数据回放验证：A5/AS-007 旧失败现在全部可拦截。

def _parse_order_before(spec: str) -> tuple[str, str]:
    """解析时序断言 DSL（legacy）：'A before B' → (A, B)。保留兼容旧用例。"""
    parts = spec.split(" before ")
    if len(parts) != 2:
        raise ValueError(f"order_before 格式应为 'A before B'，实际: {spec!r}")
    return parts[0].strip(), parts[1].strip()


def _parse_qualified_order_before(spec: str) -> tuple:
    """解析时序断言 DSL v2：'A[comp:sem] before B[comp]' → 各段元组。

    支持形态：
      - 'interact before order_create'            （legacy 工具级）
      - 'interact[choice] before order_create'    （组件限定：choice 卡）
      - 'interact[choice:processing_items] before interact[confirm]'（加工项卡语义）
      - 'processing_ask before after_sales_manage'（语义 token：卡或文本的加工项询问）
    返回 (tool_a, comp_a, sem_a, tool_b, comp_b, sem_b)；格式错误抛 ValueError。
    """
    import re as _re
    m = _re.match(r"^([a-z_]+)(?:\[([a-z_]+)(?::([a-z_]+))?\])?\s+before\s+([a-z_]+)(?:\[([a-z_]+)(?::([a-z_]+))?\])?$",
                  spec.strip())
    if not m:
        raise ValueError(f"order_before 格式应为 'A[comp:sem] before B[comp]'，实际: {spec!r}")
    return m.groups()


def _is_processing_items_card(args: dict) -> bool:
    """choice 卡是否加工项选择卡（排除瑕疵商品等选项带 ¥ 的普通卡）。

    判定：title 含「加工项」**或「加工」**（OR-017 run 34670989760 实证：LLM 的合法
    加工项卡标题是「这款窗帘支持**加工**哦，需要帮您加上吗？」，不含「加工项」三个字
    但语义完全是加工项询问 —— 只认「加工项」会把 agent 的正确行为误判为"没问"），
    或任一 option value 以 proc_item_ 开头。
    """
    title = str((args or {}).get("title") or "")
    if not (args or {}).get("options"):
        return bool(title and ("加工项" in title or "加工" in title))
    if "加工项" in title or "加工" in title:
        return True
    return any(str(o.get("value", "")).startswith("proc_item") for o in args.get("options") or [])


# 文本形态的加工项询问 = **对象词**（说的是不是加工项）+ **询问标记**（是不是在问）。
# 为什么两条分支必须同口径（issue #3681 / 归因报告 G2 §3.3，先例 OR-017 run 34670989760）：
#   `_is_processing_items_card` 早就接受「加工项」**或「加工」**（LLM 合法卡标题
#   「这款窗帘支持**加工**哦，需要帮您加上吗？」不含三字），文本分支却要求**字面「加工项」三字**
#   —— 而用例自己声明「文本询问亦可，语义由 order_before 保证」（`.github/cases/aftersales.yml:346`）
#   ⇒ agent 用自然表述问加工项（「刺绣工艺（按面积）需要选哪种？」）被判"没问" →
#   `order_before[processing_ask …]` 报「全程未调用」→ **整例 score 0（假红温床）**。
# 口径 = 卡片分支的对象词集合（「加工项」/「加工」）+ 同族对象词「工艺」（问加工工艺同样是
#   在问加工项）**并且**必须带询问标记 —— 文本分支没有"这是 choice 卡"这种结构保证，
#   所以不能用"提到加工即算问"（那会把"加工已完成"这类陈述判成询问 → `order_before` 假绿）。
# ⚠️ 只改**口径**，不动**时机**：`processing_ask` 的时序语义（必须早于写工单）一字未改。
_PROC_ASK_OBJECT_WORDS = ("加工项", "加工", "工艺")
_PROC_ASK_INTENT_WORDS = (
    "选择", "选", "需要", "要不要", "是否", "可以", "确认", "哪种", "哪些", "什么",
    "吗", "呢", "怎么",
)
# 明确**否定/已陈述**的形态（含「加工」二字但不是询问）→ 直接判非询问。
# 为什么需要（issue #3681 反例）："该商品无可用加工项。" 含「加工项」且含「可」，
# 旧口径（任何含「加」的句子）会把它判成"问了加工项" ⇒ `order_before` 假绿。
_PROC_ASK_STATEMENT_MARKERS = (
    "无可用加工项", "没有可用加工项", "不支持任何加工", "不需要加工", "无需加工",
    "不用加工", "不加加工项", "无加工项",
)


def _processing_ask_in_round(r: dict) -> bool:
    """该轮是否包含加工项询问（卡或文本）。

    卡片分支：`_is_processing_items_card`（title 含「加工项」/「加工」，或 option 前缀 `proc_item`）。
    文本分支：与卡片分支**同口径**（见上方 `_PROC_ASK_*` 常量的理由，issue #3681 假红温床）。
    仍要求"是在问"：纯陈述（"您的订单已发货" / "加工已完成" / "该商品无可用加工项"）判 False。
    """
    for tc in r.get("tool_calls") or []:
        a = tc.get("args") or {}
        if tc.get("name", "").lower() == "interact" and a.get("component") == "choice":
            if _is_processing_items_card(a):
                return True
    text = (r.get("final_text") or r.get("text") or "")
    if not text or any(k in text for k in _PROC_ASK_STATEMENT_MARKERS):
        return False
    return (any(w in text for w in _PROC_ASK_OBJECT_WORDS)
            and any(w in text for w in _PROC_ASK_INTENT_WORDS))


def _round_call_success(r: dict, tool: str) -> list:
    """该轮里 `tool` 每次 tool_result 的成功标记（无 tool_result → 空列表 = **状态未知**）。"""
    out = []
    for st in _tool_result_status(r.get("tool_results") or []):
        if tool.lower() in str(st.get("tool") or "").lower():
            out.append(bool(st.get("ok")))
    return out


def _round_has_interactive_card(r: dict, comp: str) -> bool:
    """该轮是否**发出过**指定组件的交互卡（看 SSE `interactive` 事件，不看工具调用）。

    为什么要这条（issue #3445 实证）：卡片不一定由 `interact` **工具调用**产生 ——
    代码兜底补卡走的是"回复文本里的 `<interact>` XML"，由 `chat.py` 解析成 interactive 事件；
    顾客照样看得见、点得动（`confirmValue` 已落库、门禁放行）。
    只按工具调用判"确认卡先行"会把这种**产出正确**的流程判红（#3404 同族的机制耦合假红）。
    """
    for iv in ((r or {}).get("interactive") or []):
        got = str((iv or {}).get("type") or (iv or {}).get("component") or "")
        if got == comp:
            return True
    return False


def _round_matches_tool(r: dict, tool: str, comp: str | None, sem: str | None) -> bool:
    """该轮是否调用了限定的 `tool`（组件/语义筛选）。

    `interact[confirm]` 额外接受**卡片事件证据**（见 `_round_has_interactive_card`）：
    确认卡可能来自代码兜底（文本 XML → SSE 事件）而非工具调用。
    """
    if tool == "processing_ask":
        return bool(_processing_ask_in_round(r))
    if tool.lower() == "interact" and comp == "confirm" \
            and _round_has_interactive_card(r, "confirm"):
        return True
    for tc in r.get("tool_calls") or []:
        name = str(tc.get("name", "")).lower()
        if tool.lower() not in name:
            continue
        if tool.lower() == "interact" and comp:
            args = tc.get("args") or {}
            if args.get("component") != comp:
                continue
            if sem == "processing_items" and not _is_processing_items_card(args):
                continue
        return True
    return False


def _first_qualified_round(results: list, tool: str, comp: str | None, sem: str | None,
                           require_success: bool = False) -> int | None:
    """带组件/语义限定的首次调用轮次。

    `require_success=True`（用于时序断言的**后件**，即"真正发生的那一步"）：
    只认**成功**的那次调用（issue #3421 实证）。CH-025 里 agent 在 R4 先试了一次
    `order_create`（被「缺少短信验证码」挡回、**没有写任何东西**），R5 才发确认卡，
    R7 才真正写单 —— 若按"首次出现"判时序，就会把一次**被门禁挡回的尝试**算成"写单先于确认"，
    造出假红（顾客侧零影响：没有订单被创建）。
    顾客在意的是"确认卡必须先于**真正写单**"，故后件只看成功调用。

    状态未知时的取舍（保持向后兼容，且不放宽检测）：
      · 全轨迹都拿不到该工具的 tool_result（如单测构造的极简轨迹）→ 退回"首次出现"，旧语义；
      · 有状态信息但**从未成功** → 返回 None，即不在这里造时序违规
        （"没写成"由 `must_succeed` / `db_verify` 判，避免同一件事重复计错）。
    """
    first_any = None
    saw_status = False
    for r in results or []:
        if not _round_matches_tool(r, tool, comp, sem):
            continue
        rnd = r.get("__round")
        if first_any is None:
            first_any = rnd
        if not require_success:
            return rnd
        flags = _round_call_success(r, tool)
        if flags:
            saw_status = True
            if any(flags):
                return rnd
    if require_success:
        return None if saw_status else first_any
    return first_any


def _fmt_qualified(tool: str, comp: str | None, sem: str | None) -> str:
    if comp:
        return f"{tool}[{comp}" + (f":{sem}]" if sem else "]")
    return tool


def check_order_before(results: list, order_before: list) -> list:
    """时序断言（v2）：A 首次调用轮次必须早于 B。

    - A 全程未调用 → 违规（"未调用"）；B 未调用 → 不判时序（由 expectations 判工具缺失）；
    - 反序（B 早于 A）→ 违规，注明两轮次，便于按签名排查；
    - B 只看**成功**的那次（`require_success=True`）：被门禁挡回的写尝试不算"写了"
      —— 否则会把"试了一下被挡、随后正常确认再写单"误判成反序（issue #3421 实证）
      。注意这不放宽 #3414 的保护：**真正写单**仍必须在确认卡之后。
    """
    issues = []
    for spec in order_before or []:
        try:
            a_tool, a_comp, a_sem, b_tool, b_comp, b_sem = _parse_qualified_order_before(str(spec))
        except ValueError:
            issues.append(f"order_before: 无法解析 {spec!r}")
            continue
        ra = _first_qualified_round(results, a_tool, a_comp, a_sem)
        rb = _first_qualified_round(results, b_tool, b_comp, b_sem, require_success=True)
        a_name = _fmt_qualified(a_tool, a_comp, a_sem)
        b_name = _fmt_qualified(b_tool, b_comp, b_sem)
        if ra is None:
            issues.append(f"order_before[{a_name} before {b_name}]: 全程未调用 {a_name}")
        elif rb is not None and rb < ra:
            issues.append(f"order_before[{a_name} before {b_name}]: {a_name}(R{ra}) 晚于 {b_name}(R{rb})——应 {a_name} 先于 {b_name}")
    return issues


def confirm_card_content_key(args: dict) -> str:
    """confirm 卡的**内容键**（判"同一张卡"用事实，不用措辞）。

    与运行时守卫同源语义（`interact` 的 confirmValue 已由字段事实确定性派生，issue #3406）：
    同样的事实 ⇒ 同一个键 —— 换措辞/换标题不算新卡；事实变了（改数量 3→4）⇒ 新键。
    为什么判定层也要这样（issue #3412 实证）：旧实现按 **title** 计数，
      · OR-019「中途改数量」在 R4(3米) / R6(4米) / R7(4米) 三张卡 → 标题相同被当成"死循环"**假红**，
        而其中两张是同一批事实的确认、另一张是顾客**改了数量**后的合法重新确认；
      · 反过来，换个措辞重发的同一批事实又会**漏判**。
    """
    if not isinstance(args, dict):
        return ""
    cv = str(args.get("confirmValue") or "").strip()
    if cv:
        return cv
    facts = []
    for f in args.get("fields") or []:
        if isinstance(f, dict):
            facts.append(f"{f.get('label') or ''}={f.get('value') or ''}")
    return "；".join(sorted(facts))


def _confirm_card_excerpt(args: dict, rnd) -> str:
    """一张 confirm 卡的**原文摘要**（盲审缺陷四：复核可独立完成，不必翻作业日志）。

    附在失败信息里，使「同样的事实 ×N」可逐卡核对 —— 只报轮次/标题却看不到卡内容，
    复核者无法独立判定（实测 run 34916256903 的 PR-016 红证：trace 里 R5 用户输入
    已变，判"同样的事实"只能靠猜）。
    """
    a = args or {}
    parts = [f"R{rnd}"]
    if a.get("title"):
        parts.append(f"title={a.get('title')}")
    cv = str(a.get("confirmValue") or "").strip()
    if cv:
        parts.append(f"confirmValue={cv[:80]}")
        return " ".join(parts)
    fields = []
    for f in a.get("fields") or []:
        if isinstance(f, dict):
            fields.append(f"{f.get('label') or ''}={f.get('value') or ''}")
    if fields:
        parts.append("fields=" + "；".join(fields)[:120])
    else:
        parts.append("(无 confirmValue/fields —— 事实不可判)")
    return " ".join(parts)


def check_confirm_loop(results: list, limit: int = 3) -> list:
    """确认死循环：**同一批事实**的 confirm 卡累计出现 >= limit 次 → 违规（sess_c1fce183dae24f22）。

    正常流程同一批事实的 confirm 卡只出现 1 次；2 次以内容忍（顾客取消后重新确认）；
    >=3 次 = 死循环。**按内容而非标题**计数（issue #3412，见 `confirm_card_content_key`）。

    **「同事实」的判据**（盲审缺陷四要求写清楚）：事实键 = `confirm_card_content_key`
    —— confirmValue（与字段事实确定性同源，issue #3406），或 fields 的 `label=value`
    排序集合。两卡事实键相同 = 同一批事实（换措辞/换标题不算新卡）；事实键不同 = 不同事实
    （OR-019 实证：改数量 3→4 的三张卡标题相同、事实键不同，其中一张是合法重新确认 ⇒
    不判死循环 —— 这就是 #3412 修掉的按标题计数假红）。
    **confirmValue 与 fields 皆空（无内容卡）⇒ 退回按标题计数**（历史契约，见
    `backend/ai-agent-service/tests/test_acceptance_case_checks.py::TestConfirmLoop`
    「同标题 confirm 卡 >=3 次未收敛」）：无内容的两张卡无法区分事实，**宁可拦下
    （fail-closed）** —— 但失败信息必须**显式标注「按标题近似」**，不得把无内容卡
    冒充成「已核实的同样事实」（这正是盲审缺陷四的原文张力：trace 里看不到卡内容时，
    "同样的事实 ×3"无从复核）。

    失败信息**附上每张卡的原文摘要**（轮次 + 标题 + confirmValue/字段事实，无内容时
    如实标「无 confirmValue/fields —— 事实不可判」），使计数可独立复核。
    """
    from collections import Counter
    cnt: Counter = Counter()
    rounds: dict = {}
    titles: dict = {}
    cards: dict = {}          # 事实键 → 每张卡的原文摘要（复核证据）
    approx: dict = {}         # 事实键 → True = 无内容、按标题近似计数
    for r in results:
        for tc in r.get("tool_calls") or []:
            a = tc.get("args") or {}
            if tc.get("name", "").lower() == "interact" and a.get("component") == "confirm":
                k = confirm_card_content_key(a)
                rnd = r.get("__round")
                if not k:
                    # 无内容卡：退回按标题计数（fail-closed），但如实标记为近似
                    k = a.get("title", "(无标题)")
                    approx[k] = True
                cnt[k] += 1
                rounds.setdefault(k, []).append(rnd)
                titles.setdefault(k, a.get("title", "(无标题)"))
                cards.setdefault(k, []).append(_confirm_card_excerpt(a, rnd))
    # 报错必须带**轮次**（issue #3365 诊断补强）与**每张卡的原文摘要**（盲审缺陷四）：
    # 只说"出现 3 次"时，若打印的轨迹里一张 confirm 卡都没有（被拦/失败的 interact
    # 不产生卡事件），报错与证据对不上，归因只能靠猜——实测 OR-017 卡在这个盲区一整轮。
    return [
        f"确认死循环: confirm 卡「{titles.get(k, k)}」"
        f"{'同样的事实' if not approx.get(k) else '同批 confirm 卡（无内容，按标题近似）'}"
        f"共出现 {c} 次（R{'/R'.join(str(x) for x in rounds.get(k, []))}）未收敛；"
        f"判据=内容键 {k}；各次卡原文: {' | '.join(cards.get(k, []))}"
        for k, c in cnt.items() if c >= limit
    ]


def _card_fingerprint(args: dict) -> str:
    """交互卡指纹（component + title + 字段/选项内容）—— 用于识别"同一张卡"。

    改数量/地址后的新卡（fields/options 内容变了）指纹必然不同 → 不算重复问。
    """
    import json as _json
    a = args or {}
    comp = str(a.get("component") or "")
    title = str(a.get("title") or "")
    body = _json.dumps([a.get("fields") or [], a.get("options") or [],
                        a.get("confirmValue") or ""],
                       ensure_ascii=False, sort_keys=True)
    return f"{comp}|{title}|{body}"


def _card_answer_matchers(args: dict) -> list:
    """顾客"作答"该卡的判定函数列表（命中任一即视为已答）。

    confirm → 回 confirmValue（前端点击协议就是发这个值）；
    choice → 回某 option 的 label/value（或"已选加工项：…"多选提交）；
    form → 回 `__FORM__|{json}`。
    """
    a = args or {}
    comp = str(a.get("component") or "")
    if comp == "confirm":
        cv = str(a.get("confirmValue") or "")
        return [lambda m, cv=cv: str(m or "") == cv] if cv else []
    if comp == "choice":
        labels = {str(o.get("label") or "") for o in (a.get("options") or []) if isinstance(o, dict)}
        values = {str(o.get("value") or "") for o in (a.get("options") or []) if isinstance(o, dict)}

        def _hit(m, labels=labels, values=values):
            m = str(m or "").strip()
            return m in labels or m in values or m.startswith("已选加工项：")
        return [_hit]
    if comp == "form":
        return [lambda m: str(m or "").startswith("__FORM__|")]
    return []


def check_repeated_card_ask(results: list) -> list:
    """「同一张卡顾客**已答过**又被重问」→ 违规（issue #3477 复盘 / 断言矩阵补行）。

    背景（C-A1 R5，run 34788143133 transcript）：R2 小布**文本**问「需要一起加工吗？」→
    R3 顾客答「纳米圈打孔」→ R5 又发加工项 choice 卡 —— 同一件事问第二遍（加工项侧已由
    agent 守卫修 #3473，这里补**评测断言**，覆盖地址/数量/颜色等所有"同卡重问"）。

    与 `check_confirm_loop` 的分工：那条按"同事实 confirm ≥3 次"；本条按"同卡 + 已作答"，
    对 confirm/choice/form 三类卡都生效。**防假阳性**：
      · 顾客没答过（回的是别的）→ 模型重发同卡是等回答，合法；
      · 改数量/地址后的**新卡**（指纹不同）→ 顾客须重新确认，合法；
      · 同一轮内并发两张同卡由 `check_duplicate_cards` 管，这里不重复报。
    """
    issues = []
    cards: dict = {}   # fp -> {"round", "matchers", "answered"}
    for r in results or []:
        rnd = r.get("__round")
        # 先结算"已答"：顾客对本轮之前发出过的卡作答
        for rec in cards.values():
            if not rec["answered"] and any(
                    fn(r.get("user_message")) for fn in rec["matchers"]):
                rec["answered"] = True
        for tc in (r.get("tool_calls") or []):
            if str(tc.get("name") or "").lower() != "interact":
                continue
            a = tc.get("args") or {}
            if not a.get("component"):
                continue
            fp = _card_fingerprint(a)
            if fp in cards:
                rec = cards[fp]
                if rec["answered"]:
                    issues.append(
                        f"重复问已答过的卡(R{rnd}): 「{a.get('title') or a.get('component')}」"
                        f"在 R{rec['round']} 发过且顾客已作答，又被重问 —— 顾客要多答一遍")
                    cards.pop(fp, None)   # 同一张卡只报一次
            else:
                cards[fp] = {"round": rnd,
                             "matchers": _card_answer_matchers(a),
                             "answered": False}
    return issues


def check_duplicate_cards(results: list) -> list:
    """同一轮下发**两张同组件交互卡** → 违规（issue #3445，本地复现的重复卡缺陷）。

    为什么是缺陷：一张卡的组件只有一个"答案面"，同一轮两张同名卡内容通常**完全一致**
    （代码兜底补卡走回复文本、`interact` 工具路径走工具事件 —— 两个发射点各发一张），
    顾客看到两张一模一样的卡：点哪张、点完会不会重复提交，全凭运气。

    判据取 **SSE `interactive` 事件**（= 顾客实际收到的东西），与轨迹里的
    `cards=` 字段同源；**组件不同不算**（如先 form 收资料再 confirm 确认，那是两件事）。
    """
    issues = []
    for r in results or []:
        comps = [str(iv.get("type") or iv.get("component") or "?")
                 for iv in (r.get("interactive") or []) if isinstance(iv, dict)]
        dupes = sorted({c for c in comps if comps.count(c) > 1})
        if dupes:
            issues.append(
                f"重复交互卡(R{r.get('__round')}): 同一轮下发 [{','.join(comps)}] —— "
                f"组件 {','.join(dupes)} 出现多张，顾客会看到重复卡片（issue #3445）")
    return issues


def check_false_success(results: list) -> list:
    """假成功：前序轮报错 + 后续文本声称成功 → 违规（sess_e52cff42 类）。

    工具调用全对但用户看到的话是错的（"创建失败却答更新成功"）——验收协议 §3.4 反模式。

    2026-09-13 细化（issue #3365，CI run 34710420292 实证）：**报错 ≠ 谎报**。
    CH-010 该跑 R6 出现一次瞬时错误（R7 起自动恢复），R9 的 `order_create` 真的成功落库
    （`totalAmount=408.0` = 3×128，接地正确），末轮文本称成功 —— 这是**真话**，却被本守卫
    判红。原语义「只要前序轮报错就不许说成功」把"瞬时错误后自愈"也一并否掉了。
    新语义：报错后若**确有写操作成功**（tool_result success=true，与 must_succeed 同源），
    则声明成功不构成谎报；只有"报错且没有任何写成功"时才算假成功。
    """
    err_rounds = [r.get("__round") for r in results if r.get("error")]
    if not err_rounds:
        return []
    wrote_ok = any(st.get("ok")
                   for r in results
                   for st in _tool_result_status(r.get("tool_results") or []))
    for r in results:
        if "成功" in (r.get("final_text") or "") and any(e < r.get("__round") for e in err_rounds):
            if wrote_ok:
                print(f"     ℹ️ 假成功守卫放行(R{r.get('__round')})：前序轮报错但确有写操作成功"
                      f"（声明与现实一致）")
                return []
            return [f"假成功(R{r.get('__round')}): 前序轮报错(R{err_rounds[0]})但文本称成功"]
    return []


# 写工具（有副作用的）：判定"状态宣告是否有落地"时只认这些
_WRITE_TOOL_NAMES = frozenset({
    "order_create", "aftersale_create", "human_handoff",
    "product_update", "order_update", "customer_update",
    "after_sales_manage", "product_manage", "order_manage",
    "customer_manage", "settings_manage", "staff_manage",
})

# 「完成态」写宣告措辞（**刻意保守**）：只收**明确表示写操作已发生**的说法。
# 为什么不收"已加上/已添加"：加工项/颜色这类**草稿选择**在对话里本来就用这个措辞
# （订单要等 confirm 才写），收进来会把正常话术判红 —— 与"宁可漏报不可误报"一致；
# 那类草稿态措辞改用 prompt 约束（见 order skill 的草稿/完成态措辞约定）。
# 将来/条件语境的线索词（命中标记出现在这些语境里 → **不是**"已经发生"的完成态宣告）。
# 实证（run 34790723445，OR-023 首跑假红）原文：「…麻烦点「确认下单」哦～ 确认后我会发个短信
# 验证码给您，完成最后一步就**下单成功啦** 🎉」—— 这是**将来**语义，旧判据只做子串匹配判红；
# 假红经重试放行后进 flake 台账，把真信号一起淹掉（本守卫的既有取向是"宁可漏报不可误报"）。
_CLAIM_FUTURE_PARTICLES = ("就", "将", "会", "即可", "才能")
_CLAIM_FUTURE_CUES = ("确认后", "完成后", "提交后", "点击后", "点完", "稍后", "马上", "稍等", "然后")


def _is_future_claim(text: str, marker: str) -> bool:
    """标记词是否处在**将来/条件**语境里（那样不是"已经发生"的完成态宣告）。

    判据（局部、保守）：
      · 标记词**紧前 6 字**内出现将来助词（就/将/会/即可/才能）；或
      · 标记词**所在小句**（按句读切）里出现条件/将来线索词（确认后/完成后/稍后…）。
    已知取舍：带"就"的**过去叙述**（"点了确认后订单就提交成功了"）会被一并放行 ——
    本守卫刻意选"宁可漏报不可误报"：假红会让整个台账失去可信度（真信号被淹）。
    """
    i = str(text or "").find(marker)
    if i < 0:
        return False
    before = text[max(0, i - 6):i]
    if any(p in before for p in _CLAIM_FUTURE_PARTICLES):
        return True
    start = 0
    for j in range(i - 1, -1, -1):
        if text[j] in "。！？!?；;，,\n":
            start = j + 1
            break
    return any(c in text[start:i] for c in _CLAIM_FUTURE_CUES)


_WRITE_CLAIM_MARKERS = (
    "订单已创建", "已为您下单", "下单成功", "订单已提交", "已提交订单",
    "工单已创建", "售后单已创建", "已为您提交", "已成功提交",
    "已更新", "已修改", "已删除", "已创建",
    # 地址/规格类**完成态**措辞（issue #3440 实证形态：顾客要求改地址 → 回「已更新」）：
    # 与上面同族 —— 写工具未成功前说这些，顾客会以为变更已生效。
    "地址已改", "已改好", "已生效", "已为您更新",
)


# ── 能力误宣（"能做却说做不了"，issue #3389 / 验收 C-A1 实证）──────────────
# 实证（run 34743802010，C-A1）：顾客「确认下单」×4 轮 → 小布「**下单这个操作小布这边没法
# 直接帮您提交呢**，需要您在小程序里点一下"立即购买"」→ R9 `human_handoff(reason=
# "顾客需协助下单（智能客服无法代为提交订单）")`，整场 9 轮从未调用 `order_create`。
# 而 order_create 就是 customer_order skill 自己的写工具（OR-014/017/018/019/020 都真实落单）。
#
# 与 `check_false_success` 配对：那条管"没做却说做了"（假成功），本条管"能做却说做不了"（假无能）。
# 判据（保守，避免误报）：
#   · **必须是"施动者是 AI 自己"的否定**（我/我们/小布/智能客服/这边 + 没法/无法/不能/…）；
#     商家侧/商品侧的客观说明（"这款不支持散剪""价格不能直接改"）不在此列；
#   · 同一句内 24 字符内与**下单动作**词共现（下单/提交订单/创建订单/建单/代为下单…），顺序不限；
#   · 转人工 `reason`/`summary` 同样扫描（C-A1 R9 的实际形态）。
_AGENT_INABILITY_RE_SRC = (
    r"(?:我|我们|小布|智能客服|客服|这边)[^。！？\n]{0,8}"
    r"(?:没法|无法|不能|没办法|做不到|没有权限|无权限|没权限"
    r"|没(?:有)?[^。！？\n]{0,8}权限)"   # 「没有帮您下单的权限」（#3477：词被隔开时旧正则漏）
)
_ORDER_ACTION_WORDS = ("提交订单", "下单", "创建订单", "建单", "代为提交", "代为下单", "帮您提交", "帮您下单")
_INABILITY_WINDOW = 24


def _false_inability_hit(text: str) -> str:
    """文本里是否存在"AI 自己做不到 × 下单动作"的能力误宣；返回命中片段或空串。"""
    import re as _re
    if not text:
        return ""
    agent_re = _re.compile(_AGENT_INABILITY_RE_SRC)
    for seg in _re.split(r"[。！？\n]", str(text)):
        neg = agent_re.search(seg)
        if not neg:
            continue
        for verb in _ORDER_ACTION_WORDS:
            pos = seg.find(verb)
            if pos < 0:
                continue
            if abs(pos - neg.start()) <= _INABILITY_WINDOW:
                return seg.strip()[:80]
    return ""


def check_false_inability(results: list) -> list:
    """C 端回复不得出现"我无法提交订单"这类**能力误宣**（issue #3389）。"""
    issues = []
    for r in results or []:
        text = str(r.get("final_text") or "")
        hit = _false_inability_hit(text)
        if hit:
            issues.append(
                f"能力误宣(R{r.get('__round')}): 回复称自己做不到下单/提交订单「{hit}」—— "
                f"order_create 是本 skill 的写工具，缺参数应去查/问，不得把顾客推去小程序或转人工")
        for tc in r.get("tool_calls") or []:
            if str((tc or {}).get("name") or "") != "human_handoff":
                continue
            args = (tc or {}).get("args") or {}
            why = f"{args.get('reason') or ''} {args.get('summary') or ''}"
            hit2 = _false_inability_hit(why)
            if hit2:
                issues.append(
                    f"能力误宣(转人工理由, R{r.get('__round')}): 「{hit2}」—— "
                    f"以「自己做不到」为理由转人工属能力误宣（顾客会以为系统坏了）")
    return issues


def check_unbacked_state_claim(results: list) -> list:
    """状态宣告必须有**工具落地**（issue #3379 P2-3）。

    与 `check_false_success` 的分工：那条管"前序轮**报错**却称成功"；
    本条管"**截至本轮没有任何写操作成功**却宣称写成了" —— 两者互补。

    判据（保守，避免误报）：
      · 只认**完成态写宣告**措辞（`_WRITE_CLAIM_MARKERS`）；
      · 命中措辞的轮次，**截至该轮**（含本轮）没有任何写工具**成功** → 违规；
      · 写发生在更早轮次、本轮只是复述 → 放行；
      · 只读措辞（查到/整理/列出）与"已取消"（放弃流程，代码层清理）不在标记内。
    """
    issues = []
    wrote_ok = False
    for r in sorted(results or [], key=lambda x: x.get("__round") or 0):
        for st in _tool_result_status(r.get("tool_results") or []):
            if st.get("ok") and str(st.get("tool") or "") in _WRITE_TOOL_NAMES:
                wrote_ok = True
        text = str(r.get("final_text") or "")
        hit = next((m for m in _WRITE_CLAIM_MARKERS
                    if m in text and not _is_future_claim(text, m)), None)
        if hit and not wrote_ok:
            issues.append(
                f"状态宣告无工具落地(R{r.get('__round')}): 回复称「{hit}」，"
                f"但截至本轮没有任何写工具成功（草稿态不得用完成态措辞）")
    return issues


def _check_required_field(args: dict, field: str) -> tuple[bool, str]:
    """必填字段检查，支持多级深路径：'key' / 'list[].key' / 'list[].key.sub'。

    OR-009 实拍（Round 38）：order_create 的 sellingMethod/doorWidth/colorName
    在 items[].processing_info 嵌套层，旧实现只支持 list[].key 一级——递归解析
    剩余路径，兼容「items[].processing_info.sellingMethod」这类两级以上深路径。
    """
    if "." not in field:
        v = args.get(field)
        ok = bool(v) and (not isinstance(v, (list, dict)) or len(v) > 0)
        return ok, f"缺失或为空: {field}"
    head, _, rest = field.partition(".")
    key = head[:-2] if head.endswith("[]") else head
    v = args.get(key)
    # dict 层（如 items[].processing_info.sellingMethod 的 processing_info）→ 直接递归
    if isinstance(v, dict):
        ok, detail = _check_required_field(v, rest)
        return (True, "") if ok else (False, f"{head}.{detail}")
    if not isinstance(v, list) or not v:
        return False, f"字段 {head} 缺失或为空（应为非空列表）"
    for item in v:
        if not isinstance(item, dict):
            return False, f"{head} 元素非对象"
        ok, detail = _check_required_field(item, rest)
        if not ok:
            return False, f"{head}[].{detail}"
    return True, ""


def check_required_args(results: list, required_args: list) -> list:
    """必填参数断言：指定工具（可限定 action）的 args 必须含指定字段（支持 list[].key 深路径）。

    背景（2026-09-08 Round2 实拍）：S3 建品 create 只传加工项名称不带价格、缺 specifications
    → DB specs={}、加工项 ¥0.00——工具调用存在但数据正确性不达标，旧评测按工具名判过。
    """
    issues = []
    for req in required_args or []:
        if not isinstance(req, dict):
            issues.append(f"required_args: 配置非字典: {req!r}")
            continue
        tool = str(req.get("tool", ""))
        action = req.get("action")
        if not tool:
            issues.append(f"required_args: 配置缺 tool（该断言会被静默跳过）: {req!r}")
            continue
        if not (req.get("fields") or []):
            # 只有 tool 没有 fields = 退化成"调用过就算过"，比作者本意弱得多 →
            # 显式报错，逼作者写清要校验哪些字段（失败关闭，issue #3367）
            issues.append(
                f"required_args[{tool}]: 缺/空 fields —— 该断言会退化为「调用过即通过」，"
                f"请写明要校验的必填字段: {req!r}")
            continue
        calls = []
        for r in results:
            for tc in r.get("tool_calls") or []:
                if tool.lower() not in str(tc.get("name", "")).lower():
                    continue
                a = tc.get("args") or {}
                if action and a.get("action") != action:
                    continue
                calls.append((r.get("__round"), a))
        if not calls:
            issues.append(f"required_args: 未调用 {tool}(action={action})")
            continue
        # 调用选择器 = **"存在一次满足全部字段的调用"**（与 expectations 的「任一轮命中即过」同口径）。
        # 原实现只看**第一次**调用 ⇒ 首次调用天然不含该字段时断言恒红 ——
        # run 34856561459（B 端 normal）PR-016 实形：R1 拉加工项目录（尚无分类）无
        # applicable_category_id、R5 按已选分类过滤才带上 → 判红；而该用例 data_checks
        # 记录的口径是「processing_item_query **携带** applicable_category_id」（= 至少一次携带）。
        # 任何一次调用都不满足 → 仍红（断言不放宽）；报最可诊断的那次
        # （字段真不符 > 字段缺失，避免只看到"缺失或为空"而误判为"从没传过"）。
        reasons = []
        for rnd, args in calls:
            miss = []
            for f in req.get("fields") or []:
                ok, detail = _check_required_field(args, str(f))
                if not ok:
                    miss.append(f"required_args[{tool}.{f}](R{rnd}): {detail}")
            if not miss:
                reasons = []
                break
            reasons.append(miss)
        if reasons:
            issues.extend(
                next((m for m in reasons if not any("缺失或为空" in x for x in m)), reasons[0]))
    return issues


def check_forbidden_args(results: list, forbidden_args: list) -> list:
    """**禁止参数**断言：指定工具的 args 不得出现指定字段（required_args 的镜像）。

    背景（issue #3270 量化）：C 端 40 条用例里 29 条（72%）只断言「工具被调用」，
    最关键的下限（数据隔离/越权）要求无法机器判定 —— 例如 OR-012 的隔离铁律
    「无论 LLM 通过什么参数传快递单号都必须拒绝」此前只写在自然语义 data_checks
    里（按 acceptance-protocol §1.3 铁律，自然语义不算覆盖，不计分）。

    语义：对每次 `tool`（可限定 `action`）调用，`fields` 里的路径**都不得出现**
    （支持 `list[].key` 深路径，复用 required_args 的路径解析）。

    用例形态：
        forbidden_args:
          - tool: customer_logistics_track
            fields:
              - tracking_number        # 快递单号不得作为查询依据

    采用性与 required_args 对称，便于用例作者理解。
    """
    issues = []
    for spec in forbidden_args or []:
        if not isinstance(spec, dict):
            issues.append(f"forbidden_args: 配置非字典: {spec!r}")
            continue
        tool = str(spec.get("tool", ""))
        action = spec.get("action")
        fields = [str(f) for f in (spec.get("fields") or [])]
        # 失败关闭（issue #3367 断言层审计）：配置写错就报错，不许静默跳过 ——
        # 静默跳过会让"数据隔离/越权下限"断言变成 no-op，用例照样绿而红线没人守。
        if not tool:
            issues.append(f"forbidden_args: 配置缺 tool（该断言会被静默跳过）: {spec!r}")
            continue
        if not fields:
            issues.append(f"forbidden_args[{tool}]: 缺/空 fields（该断言会退化为 no-op）: {spec!r}")
            continue
        for r in results:
            for tc in r.get("tool_calls") or []:
                if tool.lower() not in str(tc.get("name", "")).lower():
                    continue
                args = tc.get("args") or {}
                if action and args.get("action") != action:
                    continue
                for f in fields:
                    present, _detail = _check_required_field(args, f)
                    if present:
                        issues.append(
                            f"forbidden_args[{tool}.{f}](R{r.get('__round')}): "
                            f"该参数禁止出现（越权/数据隔离风险）")
    return issues


def _tool_name_matches(name: str, tool: str) -> bool:
    """工具名是否匹配（精确或 `前缀.工具名` 命名空间形态）。

    刻意**不用子串包含**：`"order_query" in "customer_order_query"` 为真，
    会把 B 端 order_query 的调用算到 customer_order_query 头上（required_args
    的旧实现在这类同尾工具名上会误判）。这里用精确/后缀匹配，语义明确。
    """
    n, t = str(name or "").lower(), str(tool or "").lower()
    if not n or not t:
        return False
    return n == t or n.endswith("." + t)


def check_must_succeed(results: list, must_succeed: list) -> list:
    """写工具**成功**断言：声明的工具必须至少真正成功一次（「调了」≠「成了」）。

    背景（CI 实证 run 34686905546 / 34685247189，issue #3361）：
    CH-010/OR-014/OR-017 三个下单用例的 `order_create` 分别返回
    `tool_execution_failed` / `confirmation_required` / `tool_not_found`，
    用例**照样判 100%**（断言只看望工具名出现在 tool_calls 里），DB 审计里
    `orders` 一条没新增。报告长相是「下单流程正常」，事实是「一单没成交」——
    这正是 §0 复盘「AI 验收全绿、人工验收全是问题」的同款假绿。

    语义（刻意不要求"每次调用都成功"）：
      - 已存在工具结果里**至少一次** `success=true` 即通过 —— 期间被 confirm 门禁
        拦下（`confirmation_required`）属**期望内的安全行为**，只要最终成功就不算违规；
      - 一次都没成功（含从未调用）→ 违规，并把每次尝试的轮次+错误码写进详情，
        工具层失败与模型层漏调在一行里可区分。

    用例形态：
        must_succeed:
          - tool: order_create            # 下单用例必须真的建出订单
          - tool: aftersale_create
            action: create                # 可选：按 args.action 过滤

    声明 `action` 时（issue #3681，同 #3667 的同族修法）：取的是**那次调用**自己的成败
    （同轮同名调用按出现顺序对齐，见 `_round_action_result`）——同一轮里**别的 action
    成功不能顶替**（那是假绿）；对不齐的合成轨迹回退**工具级**旧语义（不猜，向后兼容）。
    """
    issues = []
    for spec in must_succeed or []:
        if isinstance(spec, str):
            spec = {"tool": spec}
        tool = str(spec.get("tool", ""))
        action = spec.get("action")
        if not tool:
            issues.append(f"must_succeed: 配置缺 tool: {spec!r}")
            continue

        attempts: list = []   # [(round, ok, error)]
        for r in results or []:
            rnd = r.get("__round")
            # 调用侧：LLM 是否发起了该工具（按 action 过滤）
            called = False
            for tc in r.get("tool_calls") or []:
                if not _tool_name_matches(tc.get("name"), tool):
                    continue
                if action and (tc.get("args") or {}).get("action") != action:
                    continue
                called = True
                break
            # 结果侧（issue #3681 / 同 #3667 的同族修法）：SSE tool_result 事件**不带 args**，
            # 所以声明 action 时必须按**同轮同名调用的出现顺序**对齐到"那一次调用"自己的结果
            # —— 否则同一工具不同 action 的成败会互相顶替，**别的 action 成功也能让
            # `must_succeed[action=X]` 通过（假绿）**。对不齐（合成轨迹）→ 回退工具级旧语义。
            if action:
                a_called, _aligned, _legacy = _round_action_result(r, tool, action)
                if not a_called:
                    continue
                if _aligned is not None:
                    _res = _aligned.get("result")
                    attempts.append((rnd, bool(_res.get("success") if isinstance(_res, dict)
                                               else False), None))
                elif _legacy is not None:
                    attempts.append((rnd, bool(_legacy), None))
                else:
                    # 发起了但没有结果事件（流中断/并发丢弃）→ 按未成功记录，不许静默当成功
                    attempts.append((rnd, False, "无结果事件"))
                continue
            matched_results = [
                st for st in _tool_result_status(r.get("tool_results") or [])
                if _tool_name_matches(st.get("tool"), tool)
            ]
            if not called and not matched_results:
                continue
            if not matched_results:
                # 发起了但没有结果事件（流中断/并发丢弃）→ 按未成功记录，不许静默当成功
                attempts.append((rnd, False, "无结果事件"))
                continue
            for st in matched_results:
                attempts.append((rnd, bool(st.get("ok")), st.get("error")))

        if any(ok for _, ok, _ in attempts):
            continue
        if not attempts:
            issues.append(
                f"must_succeed: {tool} 从未被调用 → 没有发生任何写操作"
                "（期望里的工具名出现≠工具真的跑了）")
        else:
            detail = ", ".join(
                f"R{rnd}:{err or 'failed'}" for rnd, _ok, err in attempts
            )
            issues.append(
                f"must_succeed: {tool} 共 {len(attempts)} 次调用**无一成功**（{detail}）"
                "—— 调了 ≠ 成了")
    return issues


def _args_value_matches(got, want) -> bool:
    """`must_fail.args` 的值比较（容错数字/字符串同值 + 首尾空白，其余按严格相等）。

    为什么容错（issue #3689）：用例写 YAML（`price: 23.8` / `"13800138000"`），
    而模型回显的 payload 是 JSON（可能是字符串或数字、可能带空白）——同一事实的两种形态
    不该判不匹配（不匹配 = 该次调用不算作用域内 = **假绿**：脏单落库却报"没匹配上"）。
    """
    if got == want:
        return True
    if isinstance(got, (int, float, bool)) or isinstance(want, (int, float, bool)):
        try:
            return float(got) == float(want)
        except (TypeError, ValueError):
            return False
    return str(got).strip() == str(want).strip()


def _round_scoped_call_success(r: dict, tool: str, scope: dict) -> tuple:
    """本轮里**匹配 `scope`（action / args 值级）**的调用是否有成功 → `(是否发起匹配调用, 是否成功)`。

    对齐规则与 `_round_action_result`（issue #3667/#3681）**同源**：`tool_result` 事件不带 args
    （`app/api/sse.py` 只发 `{'tool','result'}`），所以"哪个结果是哪次调用的"只能按**同轮同名调用的
    出现顺序**对齐；对齐不上（结果数 ≠ 调用数，如合成轨迹/节点重放）时回退该轮该工具的口径，
    **不猜也不静默放过**（与 `_round_action_result` 的 `legacy_ok` 回退一致）。

    `scope` 支持的键：`action`（字符串，或空 = 不限）、`args`（值级 dict，全部键都须命中）。
    """
    calls = [tc for tc in (r or {}).get("tool_calls") or []
             if _tool_name_matches((tc or {}).get("name"), tool)]
    if not calls:
        return False, False
    action = str(scope.get("action") or "")
    want_args = scope.get("args") or {}

    def _hit(tc) -> bool:
        a = (tc or {}).get("args") or {}
        if action and str(a.get("action") or "") != action:
            return False
        return all(k in a and _args_value_matches(a[k], v) for k, v in want_args.items())

    hit = [i for i, tc in enumerate(calls) if _hit(tc)]
    if not hit:
        return False, False
    results = [tr for tr in (r or {}).get("tool_results") or []
               if _tool_name_matches((tr or {}).get("tool"), tool)]
    if len(results) != len(calls):
        return True, any(_round_call_success(r, tool))
    return True, any(
        bool((results[i].get("result") or {}).get("success")) for i in hit)


def check_must_fail(results: list, must_fail: list) -> list:
    """**必须失败**断言：声明的工具（可限定 `action` / `args`）**一次都不得成功**。

    为什么与 `must_succeed` 并列（issue #3544 收口批 / OR-026「拒绝半」）：`must_succeed`
    管「业务必须真的发生」，本断言管「业务**不得**发生」——例如非法手机号下单场景，
    agent 必须被写前校验挡住：**最坏形态是"调了且成了"**（脏单落库），而
    「调了但失败了」与「压根没调」都算合格拒绝。
      · 从未调用 → **通过**（"拒绝"未必等于"尝试"；要求必须尝试是另一个断言的事，
        由 `expectations: tool` 表达）；
      · 任一成功调用 → **违规**，并把轮次+错误码之外的尝试列出来便于归因。
    条目形态：`- order_create` / `- {tool: order_create, action: create}` /
    `- {tool: order_create, args: {customer_phone: "05718886666"}}`。

    声明 `action` 时（issue #3681）：只有**该 action 那次调用**自己的成败才算数（同轮对齐，
    见 `_round_action_result`）——同轮别的 action 成功/失败都不得顶替（假绿/假红同源）。

    声明 `args` 时（issue #3689 / OR-026）：语义 =「**凡匹配该 args 的那次调用**都不得成功」——
    这是**参数值级作用域**，工具×action 粒度表达不了 OR-026 的不变式
    （「任何一次以非法号码 `05718886666` 为 `customer_phone` 的 `order_create` 都不得成功」）。
      · 旧实现**从不读 `args`** → 静默降级成工具级「全程一次都不得成功」→ 与 OR-026 自己的
        `must_succeed[order_create]` 直接冲突（用例照抄即**恒红**）；
      · 现在按 `_round_scoped_call_success` 同轮对齐到**那一次调用**（不借同轮别的调用的成败）。
      · 为什么不做轮次作用域（`rounds: [R1]`）：**值级不变式必须在任何轮都成立**
        （第 3 轮用非法号建单同样违规），而轮次下标会随卡片序列漂移而错位
        （`migao-dev-flow` §13.5 / §6.4.1 的 `repeat_until` 先例）——故不做那个更弱的口径。

    **配置 fail-closed**（"断言'未评估'也是一种失败"）：条目里出现**未支持的键**（`rounds`/拼错的
    `arg`）或 `args` 不是非空映射（`yaml_light` 会把 flow 序列读成字符串）→ **报配置错误**，
    绝不静默忽略（静默忽略的后果：断言悄悄降级/空转，报告上却"看起来有覆盖"）。

    ⚠️ 本函数**看不到工具 schema**，故「声明了 action 但该工具根本没有 action 参数」这类结构性
    配置错误由 L0 静态不变式拦（`tests/unit_ci_workflows/test_eval_assertion_action_binding.py`）——
    这里不能靠"该轮没调到该 action"判红：那是**合格通过**（从未调用 = 通过），
    反例 `order_query` 有 `"default": "list"`，模型不带 action 参数调用也合法。
    """
    issues = []
    for spec in must_fail or []:
        if isinstance(spec, str):
            spec = {"tool": spec}
        if not isinstance(spec, dict):
            issues.append(f"must_fail: 配置非字符串/字典: {spec!r}")
            continue
        tool = str(spec.get("tool") or "")
        action = str(spec.get("action") or "")
        if not tool:
            issues.append(f"must_fail: 配置缺 tool: {spec!r}（该断言会静默跳过）")
            continue
        unknown = sorted(set(spec) - {"tool", "action", "args"})
        if unknown:
            issues.append(
                f"must_fail: 条目含未支持的键 {unknown}（会被静默忽略 → 断言降级/空转）: {spec!r}"
                f"—— 支持 tool/action/args；轮次作用域未实现（值级作用域见 issue #3689）")
            continue
        want_args = spec.get("args")
        if want_args is not None and (not isinstance(want_args, dict) or not want_args):
            issues.append(
                f"must_fail: args 必须是非空映射（拿不到作用域 → 断言会空转）: {spec!r}")
            continue
        succeeded: list = []
        attempts = 0
        for r in results or []:
            rnd = r.get("__round")
            matched = [st for st in _tool_result_status(r.get("tool_results") or [])
                       if _tool_name_matches(st.get("tool"), tool)]
            if want_args:
                # 参数**值级**作用域（issue #3689 / OR-026）：只算匹配该 args 的那次调用自己。
                scoped = {"action": action, "args": want_args}
                called, ok = _round_scoped_call_success(r, tool, scoped)
                if not called:
                    continue
                attempts += 1
                if ok:
                    succeeded.append(rnd)
                continue
            if action:
                # 与 `must_succeed` 对称（issue #3681）：只有**声明 action 的那次调用**自己的成败
                # 才算数 —— 同轮别的 action 成功/失败都不得顶替（假绿/假红同源）。
                called, aligned, legacy = _round_action_result(r, tool, action)
                if not called:
                    continue
                attempts += 1
                _res = (aligned or {}).get("result")
                _ok = (bool(_res.get("success") if isinstance(_res, dict) else False)
                       if aligned is not None else bool(legacy))
                if _ok:
                    succeeded.append(rnd)
                continue
            called = any(_tool_name_matches(tc.get("name"), tool)
                         for tc in r.get("tool_calls") or [])
            if not called and not matched:
                continue
            attempts += len(matched)
            succeeded += [rnd for st in matched if st.get("ok")]
        if succeeded:
            _scope = f"(action={action})" if action else ""
            if want_args:
                _scope = (f"(action={action}, " if action else "(") + "args=" \
                    + json.dumps(want_args, ensure_ascii=False, sort_keys=True) + ")"
            _rounds = ", ".join(f"R{x}" for x in succeeded)
            issues.append(
                f"must_fail: {tool}{_scope} 在 {_rounds} **成功**了 —— 该操作必须被拒绝/不成立"
                f"（脏数据落库形态；共 {attempts} 次尝试）")
    return issues


def check_forbidden_text(results: list, forbidden_text: list) -> list:
    """final_text 反模式词：命中禁词 → 违规（幻觉式撤回/报错文案）。

    背景（2026-09-08 验收）：S3 建品 create 成功且 DB 已落库，agent 却因创建后
    即时验证查不到（索引延迟）撤回正确结论、声称"商品尚未真正创建"——工具调用全对
    但用户看到的话是错的（PR-019 用本断言拦截）。

    条目形态（**与 `check_want_text` 同构**；向后兼容：裸字符串 = 原有**全程**语义）：
      - `"无法生成加工单"`                       → 全程（所有轮 final_text）出现即违规
      - `{round: 2, text: "无法生成加工单"}`     → **只在第 2 轮**出现才算违规
      - `{round: 2, any_of: ["无加工项", …]}`   → 第 2 轮出现任一词即违规（多词禁表用这个）
      - `{any_of: ["暂不支持", …]}`              → 全程，出现任一词即违规

    为什么必须补轮次作用域（issue #3833，判定跑 34908262839 的 `PG-013` 假红）：
    全程语义把「**问答轮如实陈述**」与「**写操作轮拒绝执行**」判成同一件事 ——
    PG-013 的 R1（用户问"有没有需要加工的订单"）agent 逐单核对后如实说
    「⚠️ 20260915030240002 未见加工项，无法生成加工单」（同一轮还说了
    「✅ 可生成加工单：EVAL-MB-ORD-0002」），被全程禁令判红；而 R3 它**真的生成了**加工单
    （`processing_order_generate(results=1)`）⇒ 该用例首跑功能上完全正确，唯一红点是断言自身。
    这是 `migao-acceptance`「假红：断言实现宽于用例意图」的形态 —— 治法是把模糊的全程禁令
    收紧成「轮次 + 措辞」精确断言，**不是**把禁词删掉（真拒绝必须仍红）。
    """
    issues = []
    rounds = list(results or [])

    def _all_run_hit(word: str) -> str:
        """全程语义命中时**原样保留**旧文案（含命中的轮次）—— 归因需要轮次，
        指纹（`_failure_atom` 只取词）不受影响。"""
        for r in rounds:
            if word in str((r or {}).get("final_text") or ""):
                return f"（R{(r or {}).get('__round')}）"
        return ""

    for w in forbidden_text or []:
        spec = {"text": w} if isinstance(w, str) else (w if isinstance(w, dict) else {})
        rnd = spec.get("round")
        if rnd is not None:
            try:
                idx = int(rnd) - 1
            except (TypeError, ValueError):
                issues.append(f"forbidden_text: round 非整数（{rnd!r}）—— 配置错误")
                continue
            if idx < 0 or idx >= len(rounds):
                # 与 `want_text` 同口径：越界 = 断言永不成立（fail-closed，不静默放过）
                issues.append(
                    f"forbidden_text: round={rnd} 超出实际轮数（{len(rounds)}）"
                    f"—— 断言永不成立，请核对用例轮数")
                continue
            hay, scope = str((rounds[idx] or {}).get("final_text") or ""), f"（R{rnd}）"
        else:
            hay, scope = None, None
        if spec.get("any_of"):
            words = [str(x) for x in (spec.get("any_of") or [])]
            if not words:
                issues.append("forbidden_text: any_of 为空 —— 配置错误（会静默不检查）")
                continue
            if hay is None:
                _hits = [(x, _all_run_hit(x)) for x in words]
                _hit = next(((x, s) for x, s in _hits if s), None)
                if _hit is not None:
                    issues.append(f"forbidden_text: 回复含反模式词「{_hit[0]}」{_hit[1]}")
            else:
                _hit = next((x for x in words if x in hay), None)
                if _hit is not None:
                    issues.append(f"forbidden_text: 回复含反模式词「{_hit}」{scope}")
            continue
        word = str(spec.get("text") or "")
        if not word:
            issues.append(f"forbidden_text: 配置缺 text 且无 any_of: {spec!r}（会静默不检查）")
            continue
        if hay is None:
            _scope = _all_run_hit(word)
            if _scope:
                issues.append(f"forbidden_text: 回复含反模式词「{word}」{_scope}")
        elif word in hay:
            issues.append(f"forbidden_text: 回复含反模式词「{word}」{scope}")
    return issues


def check_want_text(results: list, want_text: list) -> list:
    """final_text 正向关键词断言：任一关键词全程未出现 → 违规。

    验收协议 §3.4：关键轮次断言回复内容 = 正向关键词 + 反模式禁词表 双轨。
    forbidden_text 只防「说了不该说的」，防不住「该说的没说」——如兜底话术
    必须含「转人工」出口、写操作完成必须声明成果（订单号/成功），
    缺失即回复不完整，与反模式同等违规。

    条目形态（向后兼容：裸字符串 = 现有全程语义）：
      - `"转人工"`                   → 全程（所有轮 final_text 拼接）必须出现
      - `{round: 2, text: "记住了"}` → **只在第 2 轮**必须出现（记忆/跨会话用例：否则 R1
                                       的回显就能把断言满足，等于没判）
      - `{any_of: ["米白", "浅灰"]}` → 任一词出现即算通过（视觉/措辞天然发散：逐词全中
                                       会把合格回答判红）
      - `{round: 3, any_of: [...]}`  → 组合（限定轮次 + 任一命中）
    """
    issues = []
    rounds = list(results or [])
    for w in want_text or []:
        spec = {"text": w} if isinstance(w, str) else (w if isinstance(w, dict) else {})
        rnd = spec.get("round")
        if rnd is not None:
            try:
                idx = int(rnd) - 1
            except (TypeError, ValueError):
                issues.append(f"want_text: round 非整数（{rnd!r}）—— 配置错误")
                continue
            if idx < 0 or idx >= len(rounds):
                issues.append(
                    f"want_text: round={rnd} 超出实际轮数（{len(rounds)}）"
                    f"—— 断言永不成立，请核对用例轮数")
                continue
            hay, scope = str((rounds[idx] or {}).get("final_text") or ""), f"（第 {rnd} 轮）"
        else:
            hay = "\n".join(str((r or {}).get("final_text") or "") for r in rounds)
            scope = "（全程）"
        if spec.get("any_of"):
            words = [str(x) for x in (spec.get("any_of") or [])]
            if not words:
                issues.append("want_text: any_of 为空 —— 配置错误（会静默不检查）")
            elif not any(x in hay for x in words):
                issues.append(f"want_text{scope}: 未出现任一正向关键词 {words}")
            continue
        word = str(spec.get("text") or "")
        if not word:
            issues.append(f"want_text: 配置缺 text 且无 any_of: {spec!r}（会静默不检查）")
        elif word not in hay:
            issues.append(f"want_text{scope}: 未出现正向关键词「{word}」")
    return issues


def check_forbidden_tools(results: list, forbidden_tools: list) -> list:
    """**全程禁用工具**断言：声明的工具（可限定 action）在**任何一轮都不得被调用**。

    为什么必须补（issue #3544 收口的假绿家族）：既有写法是把「`X 未被调用`」放进
    `data_checks`（命中计分白名单），但它的语义是「**本轮**没调用」，而计分循环是
    「任一轮满足即通过」→ **多轮用例恒真**（存量 5 条：CH-002 的
    `product_manage(action=create) 未被调用`、DF-020~023 的
    `order_create`/`aftersale_create 未被调用`）。看着在守「不得越权写」，其实什么都没守。

    与 `must_succeed` 严格对称：那个管「必须成功」，本断言管「**不得尝试**」
    （更严：调用了即违规，即使被确认门禁挡回 —— 用户说「算了，不创建了」时，
    agent 连写工具都不该发）。
    条目形态：`- order_create` 或 `- {tool: product_manage, action: create}`。
    """
    issues = []
    for spec in forbidden_tools or []:
        if isinstance(spec, str):
            spec = {"tool": spec}
        if not isinstance(spec, dict):
            issues.append(f"forbidden_tools: 配置非字符串/字典: {spec!r}")
            continue
        tool = str(spec.get("tool") or "")
        action = str(spec.get("action") or "")
        if not tool:
            issues.append(f"forbidden_tools: 配置缺 tool: {spec!r}（该断言会静默跳过）")
            continue
        for r in results or []:
            hit = next(
                (tc for tc in r.get("tool_calls") or []
                 if _tool_name_matches(tc.get("name"), tool)
                 and (not action or str((tc.get("args") or {}).get("action") or "") == action)),
                None)
            if hit is None:
                continue
            _scope = f"(action={action})" if action else ""
            issues.append(
                f"forbidden_tools: {tool}{_scope} 在 R{r.get('__round')} 被调用"
                f"（全程禁用 —— 调用即违规，即使被门禁挡回）")
            break
    return issues


def _last_round_error_verdict(results: list, expectations: list, data_checks: list) -> str | None:
    """真实验收守卫（issue #2887 验收复盘）：最后轮报错 → 用例判失败。

    背景：expectations 是「任意一轮命中即过」，图片轮报错时前面的轮次可能已命中
    success=true / tool 等 expectation，用例仍被计为通过（假验收 —— 线上
    sess_806703a2dcca4059 的图片崩溃正是类假阳性）。
    规则：最后一轮（用例终点）出现 error 事件且用例未显式预期错误
    （expectations/data_checks 含 error.code= 或 suggestion）→ 返回失败原因；
    否则返回 None。
    """
    if not results:
        return None
    last_error = results[-1].get("error")
    if not last_error:
        return None
    expected_err_markers = ("error.code", "suggestion")
    all_checks = list(expectations or []) + list(data_checks or [])
    expects_error = any(
        any(m in (str(c).lower()) for m in expected_err_markers)
        for c in all_checks
    )
    if expects_error:
        return None
    return f"最后轮报错（用例未预期错误）: {str(last_error)[:120]}"


# ── 波动分类（issue #2890：Agent Eval smoke 偶发 LLM 波动根治）──
# 目标：把「失败→人工 gh run rerun 拼人品」变成「机器判定」——
#   - llm-noise     ：第二次（新 session）通过 → 噪声，自动放行并记 flake 台账；
#   - reproducible  ：两次同指纹失败 → 确定性回归，禁止 rerun 掩盖（按签名排查）；
#   - unstable      ：两次皆败但指纹不同 → 成因不同，**默认阻塞**（见 _COMPLETION_RELEASED_CLASSES）；
#   - infra         ：失败为传输/超时/5xx → 运行级重试（workflow 已整跑重试 1 次）。
# ⚠️ 分类与**放行档**是两件事：分类回答"两次失败是不是同一件事"，放行档回答"这条红灯
# 能不能按波动放过去"。`unstable` 分类仍然准确，但它**不再**是放行档（口径变更，见下）。
_INFRA_MARKERS = (
    "transport", "connect", "timeout", "all connection attempts failed",
    " 502", " 503", " 504", "internal server error", "bad gateway",
)


def _is_infra_error(err) -> bool:
    """失败是否运行级（网络/超时/5xx）——与 LLM 波动无关，重试属于合理操作。"""
    s = str(err).lower()
    return any(m in s for m in _INFRA_MARKERS)


# ── 失败根因指纹（root-cause-stable signature，issue #3728）──────────────────
#
# 旧实现把**断言渲染文本**当指纹（`f"{exp}|{detail[:60]}"`）：同一根因只要经由不同
# 断言路径渲染、或尾随细节/组件条数不同，指纹就不同 → `_classify_attempts` 判
# `unstable` → `completion_verdict` 按「LLM 波动」**放行** → `completion.ok` 假绿。
#
# 实证（run 34846098440 / SHA 4c466d4d，`agent-eval-flakes.json` 的 PG-016）：
#   · 两次失败的第 0/1 组件**逐字相同**（`must_succeed: … 从未被调用`、
#     `output_verify[…] 找不到成功调用的结果`）—— 根因是同一个：agent
#     **从未成功调用** `processing_order_update(action=complete)`；
#   · 差异只在第 2/3 组件：一次渲染成 `unmatched expectation: …(action=complete)`，
#     另一次渲染成 `tool '…' matched but arg 'action' expected …`，且
#     `required_args: 未调用 …` 只在其中一次出现。
#   ⇒ 判 `unstable` → 按「LLM 波动」放行 → `deterministic_failures=[]` →
#     `completion.ok` 由 false 变 true。这是**系统性**的假绿通道，不止 PG-016。
#
# 现在指纹 = **结构化失败身份的集合**（规范 token，排序去重）：
#   · 归一（丢弃自由文本细节）：保留**结构身份**（断言族 → 规范 kind、工具名、
#     参数键名、case 级检查名），丢弃轮次 `(R3)`、实际值、错误正文、条数；
#   · 归并（同根因 ⇒ 同 token）：`action` 是**调用选择器**而非载荷值 ——
#     「arg 'action' 不符」「unmatched expectation: t(action=X)」「must_succeed:
#     t 从未被调用」「required_args: 未调用 t」「output_verify[t] 找不到成功调用」
#     都是同一件事：**声明的那次调用没有成功发生** → 统一成 `no_success(<tool>)`；
#   · 条数容忍：集合语义 + 上面这层归并 ⇒ 组件条数差异（3 条 vs 4 条）自然消失。
#
# 为什么仍能区分真波动（不做成常量）：**载荷层**的违反保留键名身份
# （`arg_mismatch(<tool>,<key>)` / `output_missing_field(<tool>,<key>)` /
# `db_mismatch(<fetch>,<field>)` …），与「调用从未发生」不同 token；载荷**值**、
# 轮次、错误正文属 LLM 抖动噪声，丢弃它们才不会把同一个违反点误判成发散
# （这是本次修复的正向目标，不是放宽判定）。
_TOOL = r"[a-z][a-z0-9_.]*"          # 工具名形态（小写标识符，可带命名空间点）
_CASE_LEVEL_DETAIL = "case-level check"
_LAST_ROUND_ERR_RE = re.compile(r"^最后轮报错（用例未预期错误）[:：]\s*(.*)$", re.DOTALL)
_ROUND_RE = re.compile(r"[(（]?\s*R\d+\s*[)）]?")
_LITERAL_RE = re.compile(r"「[^」]*」|'[^']*'|`[^`]*`|\"[^\"]*\"")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _generic_token(text) -> str:
    """把自由文本压成稳定 token：去轮次/字面值/数字，只留"在说什么"的形状。"""
    s = _ROUND_RE.sub("", str(text or ""))
    s = _LITERAL_RE.sub("<v>", s)
    s = _NUM_RE.sub("#", s)
    return re.sub(r"\s+", " ", s).strip()


def _generic_atom(msg: str) -> str:
    """未知断言族的兜底 token：族名 + 首个括号键。

    未知族**不能退化成原文**（原文含轮次/实际值 → 指纹不稳定，正是本次要修的洞），
    也**不能退化成常量**（所有未知族并成一个 token → 真波动被误判成确定性失败）。
    取「族名 + 首个括号键」：同族同键 ⇒ 同 token；异族/异键 ⇒ 不同 token。
    """
    s = _generic_token(msg)
    head = re.split(r"[:：（(\[,，)]", s, 1)[0].strip()
    key = ""
    m = re.match(r"^[^\[（(]*[\[（(]([^\]）)]+)", s)
    if m:
        key = m.group(1).strip()
    parts = [p for p in (head, key) if p]
    return "other(%s)" % "|".join(parts) if parts else "other(?)"


def _error_kind(err) -> str:
    """错误事件的**种类**（异常类名 / 错误码），丢弃消息正文（正文含抖动细节）。

    与 `_is_infra_error` 的分工：后者只看"是不是运行级错误"并先行分流；
    这里只回答"两次的错是不是同一类"。
    """
    head = re.split(r"[:：(\n]", str(err or ""), 1)[0].strip()
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", head or ""):
        return head
    return _generic_token(err)[:60] or "unknown"


# case 级断言消息 → 规范 token 的规则表：`(正则, 模板)`，模板里的 `{0}/{1}`
# 对应捕获组。**顺序敏感**（具体的在前，宽泛的在后）。
_CASE_ATOM_RULES = (
    # ① 「声明的调用没有（成功地）发生」簇 —— 本次修复的核心：多条渲染路径一个 token。
    #    条数差异（`required_args` 只在一侧渲染）随集合语义消失。
    (re.compile(rf"^must_succeed: ({_TOOL}) 从未被调用"), "no_success({0})"),
    (re.compile(rf"^must_succeed: ({_TOOL}) 共 \d+ 次调用"), "no_success({0})"),
    (re.compile(rf"^required_args: 未调用 ({_TOOL})\(action="), "no_success({0})"),
    (re.compile(rf"^output_verify\[({_TOOL})\].*?: 找不到成功调用的结果"), "no_success({0})"),
    (re.compile(rf"^amount_verify: 未找到 ({_TOOL}) 的成功调用"), "no_success({0})"),
    (re.compile(rf"^db_verify\[[^\]]+\]: 找不到 ({_TOOL})"), "no_success({0})"),
    # ② 断言**配置错误**（与业务行为无关，但必须可辨、稳定；不含 repr 细节）
    (re.compile(r"^must_succeed: 配置"), "config_error(must_succeed)"),
    (re.compile(r"^must_fail: 配置"), "config_error(must_fail)"),
    (re.compile(r"^must_fail: 条目含未支持的键"), "config_error(must_fail)"),
    (re.compile(r"^forbidden_tools: 配置"), "config_error(forbidden_tools)"),
    (re.compile(r"^required_args: 配置"), "config_error(required_args)"),
    (re.compile(rf"^required_args\[({_TOOL})\]: 缺/空 fields"), "config_error(required_args,{0})"),
    (re.compile(r"^forbidden_args: 配置"), "config_error(forbidden_args)"),
    (re.compile(rf"^forbidden_args\[({_TOOL})\]: 缺/空 fields"), "config_error(forbidden_args,{0})"),
    (re.compile(r"^output_verify: 配置"), "config_error(output_verify)"),
    (re.compile(rf"^output_verify\[({_TOOL})\]: 缺 expect"), "config_error(output_verify,{0})"),
    (re.compile(r"^db_verify: 配置非字典"), "config_error(db_verify)"),
    (re.compile(r"^db_verify: 不支持的 fetch"), "config_error(db_verify)"),
    (re.compile(r"^db_verify\[product_by_name\]: 缺 name"), "config_error(db_verify)"),
    (re.compile(r"^post_session: 不支持的 fetch"), "config_error(post_session)"),
    (re.compile(r"^amount_verify: 配置非字典"), "config_error(amount_verify)"),
    (re.compile(rf"^amount_verify\[({_TOOL})\]: 无法识别 checks"), "config_error(amount_verify,{0})"),
    (re.compile(r"^amount_verify: 声明了 unit_price 检查但未给 product_name"),
     "config_error(amount_verify)"),
    (re.compile(r"^form_prefill: 配置"), "config_error(form_prefill)"),
    (re.compile(r"^want_text: (?:配置|round)"), "config_error(want_text)"),
    # 轮次作用域（issue #3833）的配置错误同口径折叠：与 `want_text` 对称。
    # 「只加不改」—— 旧版 forbidden_text 从不产出这两类消息，故对存量指纹零影响。
    (re.compile(r"^forbidden_text: (?:配置|round)"), "config_error(forbidden_text)"),
    (re.compile(r"^forbidden_card_text: 空配置"), "config_error(forbidden_card_text)"),
    (re.compile(r"^order_before: 无法解析"), "config_error(order_before)"),
    # 夹具/harness 形状不兼容（issue #3803）：**必须与 agent 行为失败分属不同原子**。
    # 旧形态下这条红会被折成 `no_success(order_create)`（看着像产品不会下单），
    # 折叠后是 `harness_incompatible(form_fields_mismatch)` —— 归因一眼可辨，
    # 且"两次尝试是否同因"也按这件事判（不会与真实行为回归混为一谈）。
    (re.compile(r"^harness_incompatible\((\w+)\)"), "harness_incompatible({0})"),
    # 夹具层（pre_clean，issue #3781）：**前置未应用**必须与行为失败**分属不同根因**——
    # 它的原文里带 `pre_clean:` / `precondition` 前缀（`check_preclean_not_applied` 折入），
    # 折叠成固定 token 而非通用 token：两次尝试的原文里含用例名/号码，通用 token 会把
    # "同一件事"洗成"两次不同违反点"（→ 误判 unstable）。类型名保留（不同 type 不同根因）。
    (re.compile(r"^pre_clean: 不支持的 type: '?([A-Za-z0-9_, ]+)'?"),
     "config_error(pre_clean)"),
    (re.compile(r"^pre_clean: 前置未应用"), "precondition_not_applied(pre_clean)"),
    (re.compile(r"^PRECONDITION_NOT_APPLIED"), "precondition_not_applied(pre_clean)"),
    (re.compile(r"^PRECONDITION_NOT_RESTORED"), "precondition_not_restored(pre_clean)"),
    # 声明层前置断言（`precondition: [...]`，issue #3781 / #3835）：与 pre_clean 同族但
    # **来源不同**（一个是"复位动作没生效"，一个是"运行期观测到靶子漂移"）⇒ 固定 token
    # 里带 type，使两次尝试的"同一件事"折叠一致（值/号码/商品名不进 token）。
    (re.compile(r"^precondition\[([A-Za-z0-9_]+)\]"), "precondition_not_applied(declared:{0})"),
    # ③ 参数层：工具 + 键名 = 结构身份（值/轮次/缺失值文案丢弃）
    (re.compile(rf"^required_args\[({_TOOL})\.([^\]]+)\]"), "required_arg({0},{1})"),
    (re.compile(rf"^forbidden_args\[({_TOOL})\.([^\]]+)\]"), "forbidden_arg({0},{1})"),
    (re.compile(rf"^must_fail: ({_TOOL})"), "must_fail_violated({0})"),
    (re.compile(rf"^forbidden_tools: ({_TOOL})"), "forbidden_tool({0})"),
    # ④ 产出层：工具 + 字段名 = 结构身份（缺字段 / 值不符 分属不同根因）
    (re.compile(rf"^output_verify\[({_TOOL})\].*?: 结果里没有字段 '([^']+)'"),
     "output_missing_field({0},{1})"),
    (re.compile(rf"^output_verify\[({_TOOL})\](?:\([^)]*\))?: (\S+) 期望"),
     "output_value_mismatch({0},{1})"),
    # ⑤ 金额层
    (re.compile(rf"^amount_verify\[({_TOOL})\].*?: .*单价"), "amount_verify({0},unit_price)"),
    (re.compile(rf"^amount_verify\[({_TOOL})\].*?: .*小计"), "amount_verify({0},subtotal)"),
    (re.compile(rf"^amount_verify\[({_TOOL})\].*?: processingFee"),
     "amount_verify({0},processing_fee)"),
    (re.compile(rf"^amount_verify\[({_TOOL})\].*?: 总额"), "amount_verify({0},total)"),
    (re.compile(rf"^amount_verify\[({_TOOL})\].*?: items 为空"), "amount_verify({0},no_items)"),
    (re.compile(rf"^amount_verify\[({_TOOL})\].*?: items\[\d+\] 非对象"),
     "amount_verify({0},bad_item)"),
    (re.compile(rf"^amount_verify\[({_TOOL})\].*?: items\[\d+\] 数量/单价非数值"),
     "amount_verify({0},bad_item_value)"),
    (re.compile(r"^amount_verify: 商品「"), "amount_verify(fixture_missing_price)"),
    # ⑥ 落库层：fetch 资源 + 字段 = 结构身份（订单号/值/行数丢弃）
    (re.compile(r"^db_verify\[order_phone\]: 订单 \S+ 查不到手机号"),
     "db_missing(order_phone,phone)"),
    (re.compile(r"^db_verify\[order_phone\]: 订单 \S+ 落库手机号"),
     "db_mismatch(order_phone,phone)"),
    (re.compile(r"^db_verify\[order_phone\]: 订单 \S+ 收货人"),
     "db_mismatch(order_phone,customer_name)"),
    (re.compile(r"^db_verify\[order_phone\]: 订单 \S+ 收货地址"),
     "db_mismatch(order_phone,address)"),
    (re.compile(r"^db_verify\[order_items\]: 订单 \S+ 查不到明细"), "db_missing(order_items)"),
    (re.compile(r"^db_verify\[order_items\]: 订单 \S+ 明细里没有「([^」]+)」"),
     "db_missing(order_items,{0})"),
    (re.compile(r"^db_verify\[order_items\]: 「([^」]+)」数量"),
     "db_mismatch(order_items,quantity:{0})"),
    (re.compile(r"^db_verify\[processing_order\]: 查不到加工单"), "db_missing(processing_order)"),
    (re.compile(r"^db_verify\[processing_order\]: "), "db_mismatch(processing_order)"),
    (re.compile(r"^db_verify\[employee\]: 查不到员工"), "db_missing(employee)"),
    (re.compile(r"^db_verify\[employee\]: 落库记录里没有字段 '([^']+)'"),
     "db_missing(employee,{0})"),
    (re.compile(r"^db_verify\[employee\]: 落库字段 '([^']+)' 为空"), "db_empty(employee,{0})"),
    (re.compile(r"^db_verify\[employee\]: 落库 (\S+) 实际"), "db_mismatch(employee,{0})"),
    (re.compile(r"^db_verify\[after_sales_ticket\]: 工单 \S+ 查不到详情"),
     "db_missing(after_sales_ticket)"),
    (re.compile(r"^db_verify\[after_sales_ticket\]: 工单 \S+ 落库状态"),
     "db_mismatch(after_sales_ticket,status)"),
    (re.compile(r"^db_verify\[after_sales_ticket\]: 工单 \S+ 落库字段 (\S+) 为空"),
     "db_empty(after_sales_ticket,{0})"),
    (re.compile(r"^db_verify\[after_sales_ticket\]: 工单 \S+ 落库 closeReason"),
     "db_mismatch(after_sales_ticket,close_reason)"),
    (re.compile(r"^db_verify\[product_by_name\]"), "db_mismatch(product_by_name)"),
    # ⑦ 时序 / 文本 / 卡片 / 能力类
    (re.compile(r"^order_before\[(.+?) before .+?\]: 全程未调用"), "order_before_missing({0})"),
    (re.compile(r"^order_before\[(.+?) before .+?\]: .+?[(（]R\d+[)）] 晚于"),
     "order_before_reversed({0})"),
    (re.compile(r"^forbidden_text: 回复含反模式词「([^」]+)」"), "forbidden_text({0})"),
    (re.compile(r"^want_text.*?: 未出现任一正向关键词"), "want_text_missing(any_of)"),
    (re.compile(r"^want_text.*?: 未出现正向关键词「([^」]+)」"), "want_text_missing({0})"),
    (re.compile(r"^卡片出现禁用词「([^」]+)」"), "forbidden_card_text({0})"),
    (re.compile(r"^form_prefill\[([^\]]+)\]: 会话里没有出现任何 form 卡"),
     "form_prefill_missing({0})"),
    (re.compile(r"^form_prefill\[([^\]]+)\]: form 卡里没有字段"), "form_prefill_missing_field({0})"),
    (re.compile(r"^form_prefill\[([^\]]+)\][^(]*: 字段存在但"), "form_prefill_empty({0})"),
    (re.compile(r"^form_prefill\[([^\]]+)\][^(]*: 预填值"), "form_prefill_mismatch({0})"),
    (re.compile(r"^重复交互卡"), "duplicate_cards"),
    (re.compile(r"^重复问已答过的卡"), "repeated_card_ask"),
    (re.compile(r"^能力误宣[(（]转人工理由"), "false_inability(handoff_reason)"),
    (re.compile(r"^能力误宣"), "false_inability"),
    (re.compile(r"^状态宣告无工具落地"), "unbacked_state_claim"),
    (re.compile(r"^回复出现完整手机号"), "full_phone_leak"),
    (re.compile(r"^落库手机号"), "phone_provenance"),
    (re.compile(r"^R\d+[:：] order_create 因缺验证码失败"), "write_code_missing"),
    (re.compile(r"^R\d+[:：] order_create 因验证码失败"), "write_code_mismatch"),
    (re.compile(r"^post_session\[user_memories"), "post_session(user_memories)"),
    # 注：「确认死循环…」这类没有专属族的检查**有意不给规则**：走 `_generic_atom`
    # 保留中文族名（`other(确认死循环)`）—— 令牌既可读又稳定，且不丢归因线索。
    # ⑧ 断言自身执行失败（异常类名 = 结构身份，消息正文丢弃）
    (re.compile(r"^(.+?) 执行失败[:：] ?([A-Za-z_][A-Za-z0-9_.]*)"), "check_error({0},{1})"),
    (re.compile(r"^debug_user 前提校验执行失败"), "precondition_error(debug_user)"),
)


def _case_issue_atom(msg: str) -> str:
    """case 级断言消息（`detail == "case-level check"`）→ 规范 token。"""
    s = str(msg or "")
    for pat, tpl in _CASE_ATOM_RULES:
        m = pat.match(s)
        if m:
            return tpl.format(*m.groups())
    m = _LAST_ROUND_ERR_RE.match(s)
    if m:
        # 与 `result["last_error"]` 的 token 同形 → 同一件事只留一个身份
        return "error(%s)" % _error_kind(m.group(1))
    return _generic_atom(s)


def _expectation_tool(exp: str) -> str:
    """期望声明里的工具名（OR 分支取首个形如工具名的分支）；取不到返回空串。"""
    for part in re.split(r"\s+or\s+", str(exp or "")):
        part = part.strip()
        if re.fullmatch(_TOOL, part):
            return part.lower()
        name, args = _parse_expectation(part)
        if args is not None and re.fullmatch(_TOOL, name or ""):
            return name.lower()
    return ""


def _expectation_atom(exp: str, detail: str) -> str:
    """`expectations` 失败的渲染 → 规范 token。

    两条渲染路径归一（PG-016 实证）：
      · `unmatched expectation: t(action=x)` —— 没有任何一次调用满足声明；
      · `tool 't' matched but arg 'action' expected x got y` —— 名字对上但
        **调用选择器**不符 ⇒ 等价于「声明的那次调用没发生」；
      两者都 → `no_success(t)`。而 `action` 之外的键不符属**载荷层**违反，
      保留键名（`arg_mismatch(t,k)`）—— 与"从未调用"是不同根因。
    """
    d = str(detail or "")
    if d.startswith("unmatched expectation"):
        tool = _expectation_tool(exp)
        if tool:
            return "no_success(%s)" % tool
        return "unmatched_expectation(%s)" % (_generic_token(exp)[:60] or "?")
    if d.startswith("tool '") and " matched but " in d:
        name = d.split("'")[1] if d.count("'") >= 2 else _expectation_tool(exp)
        reason = d.split(" matched but ", 1)[1]
        m = re.match(r"missing arg '([^']+)'", reason)
        if m:
            return "arg_missing(%s,%s)" % (name, m.group(1))
        m = re.match(r"arg '([^']+)'", reason)
        if m:
            key = m.group(1)
            if key == "action":
                return "no_success(%s)" % name
            return "arg_mismatch(%s,%s)" % (name, key)
        return "arg_mismatch(%s,?)" % name
    if d.startswith("expected direct_reply"):
        return "direct_reply_expected_but_tool_calls"
    if d.startswith("expected success but got error"):
        return "success_expected_but_error"
    m = re.match(r"expected error (\S+) but got", d)
    if m:
        return "error_code_expected(%s)" % m.group(1)
    return "expectation(%s)" % (_generic_token(exp)[:60] or "?")


def _failure_atom(exp, detail) -> str:
    """一条失败渲染 `(exp, detail)` → 规范 token。"""
    e, d = str(exp or ""), str(detail or "")
    if d == _CASE_LEVEL_DETAIL or _LAST_ROUND_ERR_RE.match(e):
        return _case_issue_atom(e)
    return _expectation_atom(e, d)


def _failure_atoms(result: dict) -> frozenset:
    """一次失败尝试的**结构化失败身份集合**（`_failure_signature` 的集合形态）。

    集合形态供 `_classify_attempts` 做**包含关系**判定（指纹子集 ⇒ 共有部分稳定复现，
    AS-004 实证）；字符串形态供台账/日志人读。两者同源，不得各自实现。
    """
    atoms = set()
    for exp, detail in (result.get("failed") or []):
        atom = _failure_atom(exp, detail)
        if atom:
            atoms.add(atom)
    err = result.get("last_error")
    if err:
        atoms.add("error(%s)" % _error_kind(err))
    return frozenset(atoms)


def _failure_signature(result: dict) -> str:
    """失败指纹：**结构化失败身份**的集合（排序去重后 `||` 连接）→ 判定两次失败是否同根因。

    两次指纹一致 = 同一违反点确定性复现（`reproducible`，禁止 rerun 掩盖）；
    一个是另一个的**真子集** = 共有部分稳定复现（同样 `reproducible`，见
    `_classify_attempts` 的规则③）；其余不一致 = 各次不同违反点（`unstable`）。
    归一/归并规则与理由见本节顶部注释。
    """
    return "||".join(sorted(_failure_atoms(result)))


FLAKE_REASONS = {
    # 口径（issue #3806）：`llm-noise` = **随机**波动 —— 判据补上"跨 run 复发"这一维后，
    # "首跑必败、重试偶过"不再是噪声（同一首跑指纹在历史 run 里反复出现 ⇒ 系统性缺口，
    # 不得放行）。故 reason 文案必须写"随机"，不能只写"重试通过"（后者把确定性缺口也包进来）。
    "llm-noise": "首次失败、新 session 重试通过，且同一首跑指纹未在历史 run 复发（随机波动）",
    "reproducible": "两次同指纹失败（确定性回归，禁止 rerun 掩盖，按签名排查）",
    "unstable": "两次皆败但成因不同（无一次通过 —— 不按波动放行，默认阻塞）",
    "infra": "传输/超时/5xx（运行级，可整跑重试）",
    "no-retry-budget": "重试预算用尽，未做第二次尝试（结论未验证）",
}


def format_first_attempt_evidence(result: dict) -> str:
    """把「首跑失败、重试通过」那次的**逐轮证据**压成可打印文本（issue #3367）。

    为什么必须有：此前只留指纹（`_failure_signature`）—— 指纹回答"是什么"
    （如 `must_succeed: order_create 从未被调用`），但**不回答"停在哪一轮"**。
    实测 CH-010 首跑失败连续多跑都只有指纹，知道没调写工具却无法定位（#3367 为此单开）。
    轨迹是唯一能区分「模型收尾了」/「轮数耗尽」/「卡在应答协议轮」的证据。

    通过的尝试返回空串（避免把"通过那次的轨迹"误当成失败证据）。
    """
    if not isinstance(result, dict) or not result or result.get("score", 0) >= 1.0:
        return ""
    lines = [
        "首跑失败证据（重试放行前留痕）: "
        f"rounds={result.get('rounds')} tools={result.get('tool_calls')}"
    ]
    for exp, detail in (result.get("failed") or []):
        lines.append(f"   ❌ {str(exp)[:100]} → {str(detail)[:80]}")
    trace = result.get("round_trace") or []
    if trace:
        lines.append(f"   trace: {format_round_trace(trace)}")
    if result.get("last_error"):
        lines.append(f"   last_error: {str(result['last_error'])[:120]}")
    return "\n".join(lines)


def build_flake_entry(case_id: str, title: str, classification: str,
                      first: dict, second: dict, run_id: str, sha: str) -> dict:
    """构造 flake 台账条目（纯函数，便于单测）。

    台账是「为什么放行这条红灯」的**唯一长期证据**（issue #2890），所以它必须自带
    两次尝试的指纹：只记第二次（通过那次）的指纹时，`llm-noise` 就等于"无证据的波动"——
    实测 OR-017 连续 3 跑都是这种形态，每次都因为看不到首跑指纹而无法归因（issue #3365）。

    `released` 让台账**自证放行与否**（口径变更后 `unstable` 不再放行，靠分类名已读不出
    处置）：值与 `_COMPLETION_RELEASED_CLASSES` 同源，契约守卫锁两者一致。
    """
    return {
        "case_id": case_id,
        "title": title,
        "classification": classification,
        "reason": FLAKE_REASONS.get(classification, classification),
        "signature": _failure_signature(second),
        "first_attempt_signature": _failure_signature(first),
        "released": classification in _COMPLETION_RELEASED_CLASSES,
        "run_id": run_id,
        "sha": sha,
    }


def _classify_attempts(first: dict, second: dict) -> str:
    """两次尝试（同用例、新 session）结果的波动分类。

    规则（按序）：
      ① 首跑通过 → `pass`；② 重试通过 → `llm-noise`（唯一可放行档）；
      ③ 运行级错误 → `infra`；
      ④ 两次指纹**相同** → `reproducible`；
      ⑤ 两次指纹有**真子集**关系（`a ⊆ b` 或 `b ⊆ a`，且共有部分非空）→ `reproducible`
         —— 共有部分**稳定复现**，多挂的那条只是当次额外抖出来的（AS-004 实证：
         首败 = 「落库 closeReason 为空 + closeReason 不含期望值」两条 db_verify，
         次败 = 这两条 **+** 一条 `after_sales_manage … unmatched expectation`；
         机械按"指纹不同"判发散 ⇒ 真回归被洗成波动，且 `deterministic_failures` 漏计）；
      ⑥ 其余（两次皆败、成因不同且无包含关系）→ `unstable`（不属放行档 ⇒ 默认阻塞）。
    """
    if first.get("score", 0) >= 1.0:
        return "pass"
    if second.get("score", 0) >= 1.0:
        return "llm-noise"
    if _is_infra_error(first.get("last_error")) or _is_infra_error(second.get("last_error")):
        return "infra"
    a, b = _failure_atoms(first), _failure_atoms(second)
    if a == b:
        return "reproducible"
    # 子集规则：**共有部分必须非空**（否则 `∅ ⊆ X` 恒真 → 空指纹会吞掉一切，
    # 把"这次根本没记录到失败"洗成"稳定复现"）。
    if (a & b) and (a <= b or b <= a):
        return "reproducible"
    return "unstable"


# ── 跨 run 指纹复发：放行政策缺的那一维（issue #3806）────────────────────────
# 病灶：放行判据（`_classify_attempts` → `_COMPLETION_RELEASED_CLASSES`）只看**本次 run
# 的两次尝试** —— 「首跑失败 + 新 session 重试通过」= `llm-noise` = 放行。于是一个
# **首跑必败、重试偶过**的系统性缺口可以永远以"LLM 波动"被放行（台账是每次 run 独立
# 生成的，`released` 只是本次结论 ⇒ 同一指纹可以永远"首次出现"）。
#
# 铁证（三个真实 run 的 `agent-eval-flakes.json`，PR-016）：
#   run 34856561459 / 34865780382 / 34873715194 的首跑指纹**恒为**
#   `no_success(interact)||required_arg(processing_item_query,applicable_category_id)`
#   （首跑通过率 **0/3**），第三次却因"重试碰巧过"被判 `llm-noise` + 放行。
#   ⇒ 真随机波动的首跑指纹会漂移；**同一指纹连续跨 run 复现 ⇒ 不是随机 ⇒ 不得放行**。
#
# 本层只加**判据**，不改分类：`llm-noise` 仍是"首败+重试通过"，但它的**口径收紧为
# 「随机」波动**（同一 `(用例, 首跑指纹)` 未在历史 run 里出现过）。
#
# 历史怎么来（**不需要额外跑评测**）：flake 台账 artifact（§11 留存 30 天）由
# `.github/scripts/flake_history.py` 汇总成一份**滚动索引** artifact
# `agent-eval-flake-history`（`gh api` 列举 + `gh run download`，纯取数）。
# 无历史（本地跑 / 索引取不到 / 首次运行）时**不新增判定**（退化为现状），
# 因此本地不会因为缺历史造出假红 —— 但 CI 里只要有历史，复发就必须显式处理。
FLAKE_HISTORY_ENV = "AGENT_EVAL_FLAKE_HISTORY"
# 复发阈值：历史里出现过 **≥1** 次（= 跨 run 至少出现 2 次）即判复发。取最小阈值是
# **有意的 fail-closed**：口径收紧后 `llm-noise` 的语义就是"随机波动"，而同一指纹在
# 同一用例的首跑上连续出现已经不是随机的表现。
CROSS_RUN_RECURRENCE_MIN_PRIOR = 1


def flake_fingerprint_key(entry: dict) -> tuple:
    """复发判定的键 = `(用例, 首跑指纹)`。

    为什么带 case_id 而不是只看指纹全局：`_failure_atoms` 会把失败归一到**结构** token
    （如 `no_success(order_create)`），不同用例天然可能落到同一个 token —— 全局键会把
    一堆无关用例互相"确认"成复发（假红）。跨用例的同指纹是**信息性**信号
    （`cross_case_fingerprint_cases`），不进判定。
    """
    return (str(entry.get("case_id") or ""), str(entry.get("first_attempt_signature") or ""))


def load_flake_history(path: str) -> dict:
    """读跨 run 指纹索引；文件缺失/内容坏 → 空索引（**不报错**：历史取不到不是失败）。

    索引形态（由 `merge_flake_history` 生成）：
        {"<case_id>": {"<fingerprint>": {"runs": ["<run_id>", ...]}}}
    """
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def merge_flake_history(history: dict, entries: list, run_id: str = "") -> dict:
    """把本次台账并入索引（返回**新**索引，不改入参）。

    去重键 = run_id（同一个 run 重复并入是幂等的）；`run_id` 为空时按"本次"记一个
    占位符 —— 宁可少记一次也不能把同一份台账重复计入（重复会把"出现过 1 次"算成 2 次
    ⇒ 自己把自己判成复发）。
    """
    out = {cid: {fp: dict(info) for fp, info in (fps or {}).items()}
           for cid, fps in (history or {}).items()}
    rid = str(run_id or "unknown-run")
    for e in entries or []:
        cid, fp = flake_fingerprint_key(e)
        if not cid or not fp:
            continue
        info = out.setdefault(cid, {}).setdefault(fp, {"runs": []})
        runs = [str(x) for x in (info.get("runs") or [])]
        if rid not in runs:
            runs.append(rid)
        info["runs"] = runs
    return out


def cross_run_recurrence(entry: dict, history: dict) -> dict | None:
    """本条台账的**首跑指纹**是否已在本索引（历史 run）里出现过 → 复发证据，否则 None。

    空指纹**永不**算复发：`_failure_signature` 可能返回空串（没有失败断言也没有
    last_error 的形态），空串相等会把一批无关用例互相"确认"成复发（假红）。
    """
    cid, fp = flake_fingerprint_key(entry)
    if not cid or not fp:
        return None
    prior = ((history or {}).get(cid) or {}).get(fp)
    if not isinstance(prior, dict):
        return None
    runs = [str(x) for x in (prior.get("runs") or [])]
    if len(runs) < CROSS_RUN_RECURRENCE_MIN_PRIOR:
        return None
    return {"case_id": cid, "fingerprint": fp, "prior_runs": runs,
            "prior_count": len(runs)}


def annotate_cross_run_recurrence(results: list, ledger: list, history: dict) -> list:
    """把"跨 run 复发"标注挂到对应**结果**上（`r["cross_run_recurrence"]`）。

    为什么挂在结果上而不是另建一张表：`completion_verdict` 只吃 `results`（签名稳定，
    离线重放/单测都按它构造）—— 挂结果上则判定与台账天然一致，不需要第二份状态。
    返回被标注的条目列表（便于打印"哪些既有放行会被改判"，这是本单的红证要求）。
    """
    by_id: dict = {}
    for r in results or []:
        by_id.setdefault(str(r.get("case_id") or ""), []).append(r)
    marked = []
    for e in ledger or []:
        info = cross_run_recurrence(e, history)
        if not info:
            continue
        targets = by_id.get(info["case_id"]) or []
        if not targets:
            continue
        # 同一用例在一次 run 里只可能有一条台账条目（重试分类只做一次）
        targets[0]["cross_run_recurrence"] = info
        marked.append({**info, "classification": e.get("classification", "")})
    return marked


def flake_reason_with_recurrence(entry: dict, prior: dict | None, history_available: bool) -> str:
    """放行台账的 reason 必须**从数据生成**（盲审缺陷二）—— 不是读不到数据的模板话。

    旧实现是静态模板（`FLAKE_REASONS["llm-noise"]`）：无论真实 prior_count 是多少，
    reason 恒写「同一首跑指纹**未在历史 run 复发**（随机波动）」—— 同一证据集里
    OR-016（prior_count=2）与 PP-001（prior_count=4）的台账都与数据直接矛盾
    （实测 run 34916256903 的 `agent-eval-flakes.json`）。本函数按真实数据重写：

      · `prior` 非空（prior_count>0）⇒ 写明实际 `prior_count` 与 `prior_runs`，
        **禁止**出现「未复发」字样（跨 run 复发 ⇒ 不按波动放行）；
      · `prior` 为空且历史索引**不可得**（本地跑 / 索引取不到）⇒ 标「数据缺失」，
        不冒充「未复发」—— 没查过就说"没复发"是编数据；
      · `prior` 为空且历史已查（prior_count=0，首次出现）⇒ 维持「首次出现」措辞
        （= 放行档语义，允许"未在历史 run 复发"）。

    非 llm-noise 分类（reproducible/unstable/infra/…）不涉及「复发」claim，维持模板。
    """
    classification = str(entry.get("classification") or "")
    base = FLAKE_REASONS.get(classification, classification)
    if classification != "llm-noise":
        return base
    if prior:
        runs = ", ".join(str(x) for x in (prior.get("prior_runs") or []))
        return (
            "首次失败、新 session 重试通过；但同一首跑指纹已在历史 run 复发"
            f"（prior_count={prior.get('prior_count', 0)}，prior_runs=[{runs}]）"
            "—— 跨 run 复发，不按波动放行")
    if not history_available:
        return ("首次失败、新 session 重试通过；跨 run 复发判定数据缺失"
                "（历史指纹索引未加载），未做复发判定")
    return base


def rewrite_flake_reasons(ledger: list, history: dict, history_available: bool) -> None:
    """把台账条目的 reason 重写为**数据驱动**版本（与 `annotate_cross_run_recurrence`
    同历史口径；本函数必须在台账落盘**之前**调用，见 run_suite 的调用顺序）。
    """
    for e in ledger or []:
        e["reason"] = flake_reason_with_recurrence(
            e, cross_run_recurrence(e, history), history_available)


def cross_case_fingerprint_cases(history: dict) -> dict:
    """**信息性**：同一首跑指纹出现在多个用例上（往往是同一能力面，如 #3320 家族）。

    不进判定（键带 case_id 是为避免误判），只作为"系统性缺口"的报告线索：
    一个缺口命中多条用例时，修一处不会让它们全绿。
    """
    fp_to_cases: dict = {}
    for cid, fps in (history or {}).items():
        for fp in (fps or {}):
            if fp:
                fp_to_cases.setdefault(fp, []).append(cid)
    return {fp: sorted(cases) for fp, cases in fp_to_cases.items() if len(cases) > 1}



# ── db_verify：落库层验证（acceptance-protocol §3.2 / issue #3056 回归防线）──
# 建品加工项价格曾因 BFF ids/configs 分支被静默丢弃（45→30 且读回退掩盖），
# required_args 只查 create args 层；db_verify 在创建后查 admin-api 落库数据，
# 断言加工项价格 = 用户确认价，双保险（args 层 + 落库层）。

def _evaluate_processing_configs_check(configs: list, check: str) -> tuple[bool, str]:
    """评估落库谓词：'processingItemConfigs.<all|加工项名>.<字段><op><值>'。

    例：processingItemConfigs.all.finalPrice>0
        processingItemConfigs.刺绣工艺.finalPrice==45
    返回 (是否通过, 详情)；字段为空（价格未带入）即失败。
    """
    import re as _re
    m = _re.match(r"^processingItemConfigs\.([^.]+)\.([A-Za-z_]+)(>=|<=|==|!=|>|<)(.+)$", check.strip())
    if not m:
        return False, f"无法解析 db 检查: {check!r}"
    scope, field, op, raw_val = m.groups()
    if not configs:
        return False, f"db 检查: 商品无 processingItemConfigs（{check}）"
    targets = configs if scope == "all" else [c for c in configs if c.get("processingItemName") == scope]
    if not targets:
        return False, f"db 检查: 未找到加工项「{scope}」"
    try:
        val = float(raw_val)
    except ValueError:
        return False, f"db 检查: 值无法解析 {raw_val!r}"
    for c in targets:
        fv = c.get(field)
        if fv is None:
            return False, f"db 检查[{check}]: 字段 {field} 为空（价格未带入？）"
        fv = float(fv)
        ok = {"==": fv == val, "!=": fv != val, ">": fv > val, "<": fv < val,
              ">=": fv >= val, "<=": fv <= val}[op]
        if not ok:
            return False, f"db 检查[{check}]: {c.get('processingItemName')}.{field}={fv} 不满足 {op}{val}"
    return True, ""


async def _fetch_product_configs(token: str, name: str = "", product_id: str = "") -> list:
    """查商品库返回 `processingItemConfigs`（落库真实数据）。

    两条定位路径（issue #3689 / PR-019）：
      · `product_id` 给定时**直查该商品**（`GET /api/admin/products/{id}`）——回读键来自
        **本次成功写调用**的 payload（`product_manage(action=create)` 回
        `{"product_id":…}`，见 `app/tools/product_manage.py:245`）；
      · 否则按 `name` 关键词搜（`page/size=1` 取**首条**）——存量语义，用于商品名在库里唯一时。
    ⚠️ 为什么必须支持第一种：PR-019 建的商品名与评测种子同名同价
    （`fixtures/mibao_eval_seed.sql:30` 的 `prod_eval_2699`，¥23.80），keyword 首条命中的是
    **种子** ⇒ 不管本次 create 成没成功都绿（假绿）。按 id 回读才能真正核对"本次新建的那条"。
    """
    async with httpx.AsyncClient() as c:
        h = _admin_headers(token)
        pid = str(product_id or "").strip()
        if not pid:
            r = await c.get(f"{ADMIN_API}/api/admin/products", headers=h,
                            params={"keyword": name, "page": 1, "size": 1}, timeout=15)
            items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
            if not items:
                return []
            pid = items[0]["id"]
        rd = await c.get(f"{ADMIN_API}/api/admin/products/{pid}", headers=h, timeout=15)
        return (_safe_json(rd, {}) or {}).get("data", {}).get("processingItemConfigs") or []


# ── amount_verify：下单金额正确性断言（acceptance-protocol §3.2 / issue #3365）──
# 为什么必须有：写工具「成功」只证明订单落库了，**不证明钱算对了**。
# 实证：OR-014 的 agent 在没查过商品的情况下发出确认卡写着「遮光窗帘3米+打孔加工，合计¥95.4」，
# 而该商品真实单价 ¥168/米 —— 这类"钱算错"此前只能靠 DB 审计人眼看（审计只打印金额）。
# 本断言把三个关系变成机器判定：
#   ① unit_price == 商品库单价（**接地**：单价必须来自商品数据，不能凭记忆）
#   ② subtotal   == quantity × unit_price（明细自洽）
#   ③ total      == Σsubtotal + ΣprocessingFee（总额自洽，若结果里带总额）

def _first_successful_call(results: list, tool: str) -> tuple:
    """返回该工具**首个成功调用**的 (轮次, args, result_data)；找不到返回 (None, None, None)。

    成功判定用 tool_result 的 success（与 must_succeed 同源），避免把被门禁拦下的调用当成功。
    """
    for r in results or []:
        calls = [tc for tc in (r.get("tool_calls") or []) if _tool_name_matches(tc.get("name"), tool)]
        if not calls:
            continue
        oks = [st for st in _tool_result_status(r.get("tool_results") or [])
               if _tool_name_matches(st.get("tool"), tool) and st.get("ok")]
        if not oks:
            continue
        return r.get("__round"), (calls[0].get("args") or {}), None
    return None, None, None


def _first_successful_data(results: list, tool: str) -> dict:
    """首个**成功**调用的 `result.data`（payload：订单号/总额/明细等）。

    与 `_first_successful_call` 同源判成功（tool_result.success），但取的是 payload ——
    `_first_successful_call` 的第三位一直是 None（它只服务 amount_verify 的 args 校验），
    订单明细断言需要的是**结果里的订单号**，故单列一个取值口。
    """
    for r in results or []:
        for tr in r.get("tool_results") or []:
            if not _tool_name_matches(tr.get("tool"), tool):
                continue
            res = tr.get("result") if isinstance(tr.get("result"), dict) else {}
            if res.get("success") and isinstance(res.get("data"), dict):
                return res["data"]
    return {}


async def _fetch_product_price_truth(token: str, name: str) -> dict | None:
    """按商品名查**库价真值**：`{"price": 商品级价|None, "skus": [{color_name, sku_code, price}]}`。

    为什么不能只回**商品级价**（issue #4042，run 35243351675 @67db87ae 归因）：
    工具层接地闸门（`order_create._reject_unit_price_not_grounded` →
    `unit_price_grounding_error`）判的是「**这个价是否存在于商品库**」，且**声明了规格**
    （`processing_info.colorName/skuCode`）时按**所选 SKU 的价**判。断言侧此前只取商品级价 ⇒
    **同一场景下闸门放行、断言判红**（两处口径漂移）：
      · OR-014 在 mibao 腿判红（单价 150 ≠ 商品库 168），而同栈的 PR-021 把共享夹具
        `prod_eval_blackout` 的米白/散剪 SKU 价改成 150 且**无复位** ⇒ agent 按该规格下单
        150 = 该 SKU 的库价（闸门照常放行）⇒ 断言判成「凭记忆报价」= **假红**；
      · 同一条断言在 xiaobu 腿（无该污染，SKU 价 = 商品价 = 168）判绿 ⇒ 差异只在夹具，不在 agent。
    取不到 / 无任何单价 ⇒ None（调用方显式报「查不到单价」，不静默跳过）。
    """
    try:
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            r = await c.get(f"{ADMIN_API}/api/admin/products", headers=h,
                            params={"keyword": name, "page": 1, "size": 1}, timeout=15)
            items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
            if not items:
                return None
            pid = items[0]["id"]
            rd = await c.get(f"{ADMIN_API}/api/admin/products/{pid}", headers=h, timeout=15)
            data = (_safe_json(rd, {}) or {}).get("data", {}) or {}
            price = None
            for key in ("price", "basePrice", "base_price"):
                if data.get(key) is not None:
                    price = float(data[key])
                    break
            skus = []
            for sku in data.get("skus") or []:
                if not isinstance(sku, dict) or sku.get("price") is None:
                    continue
                try:
                    skus.append({
                        "color_name": str(sku.get("colorName") or sku.get("color_name") or ""),
                        "sku_code": str(sku.get("skuCode") or sku.get("sku_code") or ""),
                        "price": float(sku["price"]),
                    })
                except (TypeError, ValueError):
                    continue
            if price is None and not skus:
                return None
            return {"price": price, "skus": skus}
    except Exception:
        return None


def _allowed_unit_prices(truth: dict, pinfo) -> list:
    """该行**允许的单价集合**（纯函数；口径与工具层闸门同源，issue #4042）。

    · 声明了规格（`processing_info.colorName/skuCode`）且能匹配到 SKU ⇒ **该 SKU 的价**；
    · 声明了规格却匹配不到 SKU ⇒ 退化为**库价集合**（商品级 ∪ 全部 SKU）：闸门对"声明了规格
      但解析不到唯一 SKU"按配置错误拒绝，断言侧不据此判红（规格名写法差异会造成假红），
      但「必须是库里的价」这条防编造原意不变；
    · 未声明规格 ⇒ 商品级价 ∪ 全部 SKU 价（闸门同款豁免，#4011：多规格价商品不该被判死）；
    · 没有任何库价 ⇒ 返回 []（调用方已单独报「查不到单价」）。
    """
    truth = truth if isinstance(truth, dict) else {}
    lib: list = []
    p = truth.get("price")
    if isinstance(p, (int, float)):
        lib.append(float(p))
    skus = [s for s in (truth.get("skus") or []) if isinstance(s, dict)]
    sku_prices = [float(s["price"]) for s in skus if isinstance(s.get("price"), (int, float))]
    info = pinfo if isinstance(pinfo, dict) else {}
    color = str(info.get("colorName") or "")
    code = str(info.get("skuCode") or "")
    if color or code:
        matched = [float(s["price"]) for s in skus
                   if isinstance(s.get("price"), (int, float))
                   and ((code and str(s.get("sku_code") or "") == code)
                        or (color and str(s.get("color_name") or "") == color))]
        if matched:
            return matched
    return lib + sku_prices


def _ticket_ref_of(data) -> str:
    """工单引用取值（**单一实现**，防两处口径漂移）：`ticket_id`/`ticketId` → 否则工单形态的 `id`。

    为什么单列（issue #3689 / AS-007）：`_first_successful_ticket_payload` 与
    `check_db_verify[after_sales_ticket]` 都要取这个引用 —— 两处各写一份时，只改一处就会
    "筛得出载荷却提不出引用"（本次实测踩到：核对器仍报「找不到成功调用」）。
    `id` 的接受条件同 `_first_successful_ticket_payload`（须带工单特征键）。
    """
    d = data if isinstance(data, dict) else {}
    tid = str(d.get("ticket_id") or d.get("ticketId") or "").strip()
    if not tid and str(d.get("id") or "").strip() and any(
            str(d.get(k) or "").strip() for k in ("ticketNo", "ticketType", "orderId")):
        tid = str(d["id"]).strip()
    return tid


def _first_successful_ticket_payload(results: list, tool: str, expect_status: str) -> tuple:
    """首个**成功**的 `after_sales_manage` 调用里带工单引用的 payload（可选按状态过滤）。

    为什么不能直接用 `_first_successful_data`（issue #3544 / AS-004）：该函数取的是
    「第一个成功调用」的 payload，而 AS-004 的 R1 是 `list`（payload = {items,total}）
    → 拿它去核对工单落库会指向一个**根本没有 ticket_id** 的载荷。故按 payload 形状筛：
    带工单引用且（声明了 expect_status 时）`status` 相符 —— 后者能区分同一工单上的
    多次状态变更（如先 processing 后 closed），不会核对错那一次。

    工单引用的键**按两条写路径的真实形状**认（issue #3689 / AS-007）：
      · `update_status` 路径 → `ticket_id`（`app/tools/after_sales_manage.py:435`
        `data={"ticket_id":…, "status":…}`）；
      · `create` / `detail` 路径 → **`id`**（`:369`/`:281` 原样返回 admin-api 的
        `AfterSalesDetailResponse`，其字段是 `id`/`ticketNo`/`status`，
        **没有 `ticket_id`**）。旧实现只认 `ticket_id`/`ticketId` ⇒ create 形态恒返回
        `(None, {})` ⇒ AS-007 的 `db_verify[after_sales_ticket]` 一加就**永久假红**
        （"找不到成功调用（判失败而非跳过）"）。
    ⚠️ 裸 `id` **不算** 工单引用：必须同时带工单特征键（`ticketNo`/`ticketType`/`orderId`），
    否则将来出现「带 id 的非工单载荷」时会把核对指向一个根本不是工单的对象（假绿）。
    """
    for r in results or []:
        for tr in r.get("tool_results") or []:
            if not _tool_name_matches(tr.get("tool"), tool):
                continue
            res = tr.get("result") if isinstance(tr.get("result"), dict) else {}
            data = res.get("data") if res.get("success") else None
            if not isinstance(data, dict):
                continue
            tid = _ticket_ref_of(data)
            if not tid:
                continue
            if expect_status and str(data.get("status") or "").strip() != expect_status:
                continue
            return r.get("__round"), data
    return None, {}


_KNOWN_AMOUNT_CHECKS = ("unit_price", "subtotal", "processing_fee", "total")


def _normalize_amount_checks(raw) -> list | None:
    """把 `checks` 归一成列表；读不懂返回 None（调用方失败关闭）。

    为什么要归一（issue #3367 实证）：`yaml_light` 不解析 flow 序列，渲染产物里
    `checks: [unit_price, subtotal, total]` 变成**字符串**；旧代码
    `[str(x) for x in "<str>"]` 把它拆成字符列表 → 三项检查全被跳过 → 恒通过。
    金额断言静默失效比报错更危险（评测给人"钱查过了"的错觉）。
    """
    if raw is None:
        return list(_KNOWN_AMOUNT_CHECKS)
    if isinstance(raw, (list, tuple, set)):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        # '[unit_price, subtotal, total]' / "unit_price,total" / 'unit_price' 都能救
        tokens = re.findall(r"[a-z_]+", raw)
        if tokens:
            return tokens
        return None
    return None


def _canonical_processing_fee(pinfo) -> tuple:
    """按**服务端口径**算单行加工费：Σ processingItems[].unitPrice × quantity。

    Returns:
        (fee, 明细字符串) —— 没有 processingItems 列表时返回 (None, "")，调用方回退到
        模型声明的 `processingFee`（老形态：只写合计不写明细）。

    为什么不信 `processingFee` 字段（issue #3521 归因）：服务端
    `OrderService.sumProcessingFee()` → `extractProcessingItems()` 只认
    `unitPrice × quantity`（Java 侧 `brief.amount` 就是这两个字段相乘），
    **`processingFee` 字段不参与总额计算**。所以模型声明的合计与明细不一致时，
    顾客在确认卡上看到的总额 ≠ 落库/收款总额 —— 这是钱的问题，必须由断言点名。
    实证：CH-010 首跑 `总额 311.4 ≠ Σ小计71.4+加工费252.0=323.4`，
    反推正是「明细 30×8=240 落库 → 总额 311.4」而「声明的 processingFee=252」。
    """
    if not isinstance(pinfo, dict):
        return None, ""
    raw = pinfo.get("processingItems")
    if not isinstance(raw, list) or not raw:
        return None, ""
    total = 0.0
    parts = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            up = float(entry.get("unitPrice") or 0)
            qty = float(entry.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        amount = up * qty
        total += amount
        parts.append(f"{entry.get('name') or '?'} {up}×{qty}={round(amount, 2)}")
    if not parts:
        return None, ""
    return total, "、".join(parts)


async def check_amount_verify(token: str, results: list, amount_verify: list) -> list:
    """执行下单金额断言：单价接地 / 小计自洽 / 加工费一致 / 总额自洽，返回违规列表。

    用例形态：
        amount_verify:
          - tool: order_create
            product_name: "遮光窗帘"        # 用于取商品库单价（接地真值）
            tolerance: 0.01                # 金额容差（默认 0.01）
            checks: [unit_price, subtotal, processing_fee, total]
    """
    issues = []
    for spec in amount_verify or []:
        if not isinstance(spec, dict):
            issues.append(f"amount_verify: 配置非字典: {spec!r}")
            continue
        tool = str(spec.get("tool") or "order_create")
        tol = float(spec.get("tolerance", 0.01))
        checks = _normalize_amount_checks(spec.get("checks"))
        if checks is None:
            # 失败关闭（issue #3367）：读不懂检查项时**绝不静默跳过** ——
            # 静默跳过 = 金额断言变装饰品（本 bug 就是这么潜伏了多轮的）
            issues.append(
                f"amount_verify[{tool}]: 无法识别 checks={spec.get('checks')!r}"
                f"（应为列表，或形如 '[unit_price, subtotal, total]' 的字符串）")
            continue
        rnd, args, _ = _first_successful_call(results, tool)
        if args is None:
            issues.append(f"amount_verify: 未找到 {tool} 的成功调用（金额无从核对）")
            continue
        items = args.get("items") or []
        if not isinstance(items, list) or not items:
            issues.append(f"amount_verify[{tool}](R{rnd}): items 为空，金额无从核对")
            continue

        truth = None
        if "unit_price" in checks:
            name = str(spec.get("product_name") or "")
            if not name:
                issues.append("amount_verify: 声明了 unit_price 检查但未给 product_name（无法取真值）")
            else:
                truth = await _fetch_product_price_truth(token, name)
                if truth is None:
                    issues.append(f"amount_verify: 商品「{name}」在商品库查不到单价（fixture 缺数据？）")

        subtotal_sum = 0.0
        processing_sum = 0.0        # Σ 模型**声明**的 processingFee
        canonical_fee_sum = 0.0     # Σ 加工项明细（服务端权威口径 unitPrice × quantity）
        has_proc_items = False
        proc_detail = []
        fee_folded_in = False   # 变体②：小计里已含本行加工费 → total 不再加 Σfee（防双计）
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                issues.append(f"amount_verify[{tool}](R{rnd}): items[{i}] 非对象")
                continue
            try:
                qty = float(item.get("quantity") or 0)
                up = float(item.get("unit_price") or 0)
                sub = item.get("subtotal")
                sub_f = float(sub) if sub is not None else qty * up
            except (TypeError, ValueError):
                issues.append(f"amount_verify[{tool}](R{rnd}): items[{i}] 数量/单价非数值: {item!r}")
                continue
            pname = str(item.get("product_name") or "")
            pinfo = item.get("processing_info") or {}
            fee = 0.0
            if isinstance(pinfo, dict):
                try:
                    fee = float(pinfo.get("processingFee") or 0)
                    processing_sum += fee
                except (TypeError, ValueError):
                    fee = 0.0
            canon_fee, detail = _canonical_processing_fee(pinfo)
            if canon_fee is not None:
                has_proc_items = True
                canonical_fee_sum += canon_fee
                proc_detail.append(f"items[{i}]: {detail}")
            subtotal_sum += sub_f
            if "unit_price" in checks and truth is not None:
                # 只核对被声明商品的单价（多商品订单里其它行按各自商品库价另配 spec）
                if not spec.get("product_name") or str(spec["product_name"]) in pname:
                    allowed = _allowed_unit_prices(truth, pinfo)
                    if allowed and not any(abs(up - a) <= tol for a in allowed):
                        issues.append(
                            f"amount_verify[{tool}](R{rnd}): 「{pname}」单价 {up} "
                            f"不在库价集合 {sorted(allowed)}（凭记忆报价？）")
            if "subtotal" in checks:
                # 两种**合法约定**都放行（#3511 T3.2 归因，acceptance-protocol §14.2 有效性漂移）：
                #   ① 面料小计：subtotal = 数量 × 单价（服务端 canonical —— AgentOrderCreateRequest
                #      「subtotal 可选 → 服务端按 quantity × unitPrice 重算」；C 端 seed 亦为 504=3×168）
                #   ② 含加工费：subtotal = 面料小计 + 本行 processingFee（工具描述「processingFee
                #      并**计入金额**」的自然读法；B 端首跑实测 528=504+24）
                # 两式在服务端都会被规范化、用户可见结果一致 → 对合法变体判红 = 假失败。
                # 防松弛：与两式都不符（如 OR-014 历史真缺陷 ¥95.4）**仍判红**。
                base = qty * up
                matches_canonical = abs(sub_f - base) <= tol
                matches_folded = fee > 0 and abs(sub_f - (base + fee)) <= tol
                if matches_folded and not matches_canonical:
                    fee_folded_in = True
                if not (matches_canonical or matches_folded):
                    issues.append(
                        f"amount_verify[{tool}](R{rnd}): 「{pname}」小计 {sub_f} ≠ 数量{qty}×单价{up}"
                        f"（或 面料小计+本行加工费 {base + fee}）")

        if "processing_fee" in checks and has_proc_items:
            # 声明合计 vs 明细合计（服务端口径）—— 不一致就是**钱对不上**：
            # 确认卡上的总额（模型按声明值算）≠ 落库/收款总额（服务端按明细算）。
            # 单独点名该矛盾，避免被下面那条"总额不平"吞成含糊的算错（issue #3521）。
            if abs(processing_sum - canonical_fee_sum) > max(tol, 0.05):
                issues.append(
                    f"amount_verify[{tool}](R{rnd}): processingFee 声明 {processing_sum} ≠ "
                    f"Σ加工项(单价×数量) {canonical_fee_sum}"
                    f"（服务端按明细计入总额 → 顾客看到的总额与落库不一致；"
                    f"明细 {'; '.join(proc_detail)}）")

        if "total" in checks:
            # 加工费一律用**服务端口径**核对总额（无明细时回退到声明值）——
            # 用模型自造的声明值去判系统真值，会把"args 自相矛盾"误报成"总额算错"。
            fee_for_total = canonical_fee_sum if has_proc_items else processing_sum
            # 防双计（#3511）：若小计已含本行加工费（变体②），expected 不再加 Σfee。
            expected = subtotal_sum if fee_folded_in else subtotal_sum + fee_for_total
            total = None
            for r in results or []:
                if r.get("__round") != rnd:
                    continue
                for tr in r.get("tool_results") or []:
                    if not _tool_name_matches(tr.get("tool"), tool):
                        continue
                    res = tr.get("result") if isinstance(tr.get("result"), dict) else {}
                    data = res.get("data") if isinstance(res.get("data"), dict) else {}
                    for key in ("totalAmount", "total_amount", "amount"):
                        if data.get(key) is not None:
                            total = float(data[key])
                            break
            if total is None:
                # 结果里没带总额 → 用 args 侧总额兜底；都没有则显式跳过（不静默当通过）
                total = args.get("total_amount")
                total = float(total) if total is not None else None
            if total is None:
                # #3781 单独裁定（**可接受，但必须可见，不删不改判**）：走到这里要求
                # "工具结果与 `args.total_amount` **都**没有总额"，而 `amount_verify` 的
                # 存在前提是写工具**成功**且用例已声明要查 `total` ⇒ 属**latent 覆盖缺口**
                # （不是"数据没准备却照跑"，与 pre_clean 那三处不同族）。
                # 实证本 run 从未触发：全 run 两条腿 `grep -c '结果未带总额，跳过 total 检查' = 0`，
                # 11 条声明 `checks: [total]` 的用例都拿到了真实 `totalAmount`。
                # 从 ℹ️ 升为 ⚠️ 并**点名覆盖缺口**：让"总额这一次没被核对"在日志里显眼，
                # 而不是安静地少查一项（"看着查过了"）。
                print(f"     ⚠️ 覆盖缺口: amount_verify: {tool} 结果与 args 均未带总额 ⇒ 本次"
                      f"**未核对 total**（单价/小计已查）—— 该用例声明的 total 检查未生效")
            elif abs(total - expected) > max(tol, 0.05):
                issues.append(
                    f"amount_verify[{tool}](R{rnd}): 总额 {total} ≠ Σ小计{subtotal_sum}"
                    f"+加工费{fee_for_total}={expected}")
    return issues


# id 形态：UUID（带/不带连字符）或 32 位 hex —— ai-agent 的 order_create 返回的 `id`
# 实测是 **32 位 hex**（无连字符），而 admin-api `GET /orders/{id}` 的 path 正则接受
# `[0-9a-fA-F-]+`。首版只认带连字符的 UUID → 32 位 hex 被当成"订单号"去走关键词搜索
# → 搜不到 → 误报"订单查不到明细"（run 34726267496 实测的假失败）。
_ID_LIKE_RE = re.compile(r"^[0-9a-fA-F-]{20,}$")


async def _fetch_order_detail(token: str, order_ref: str) -> dict | None:
    """按订单 id（UUID/32 位 hex）或订单号查 admin-api 订单详情；查不到返回 None。

    两条路径都试：先按 id 直查（`GET /orders/{id}`），不成立再按**关键词搜订单号**
    （`GET /orders?keyword=` 拿 id 再查详情）—— 单靠任一条都会漏（实测：32 位 hex 走
    关键词搜不到；而订单号 `2026…` 不是合法 path 参数）。
    """
    ref = str(order_ref or "").strip()
    if not ref:
        return None
    try:
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            if _ID_LIKE_RE.match(ref):
                rd = await c.get(f"{ADMIN_API}/api/admin/orders/{ref}", headers=h, timeout=15)
                body = _safe_json(rd, None)
                if isinstance(body, dict) and body.get("data"):
                    return body
            r = await c.get(f"{ADMIN_API}/api/admin/orders", headers=h,
                            params={"keyword": ref, "page": 1, "size": 1}, timeout=15)
            items = (_safe_json(r, {}) or {}).get("data", {}).get("items", []) or []
            if not items:
                return None
            oid = str(items[0].get("id") or "")
            if not oid or oid == ref:
                return None
            rd = await c.get(f"{ADMIN_API}/api/admin/orders/{oid}", headers=h, timeout=15)
            body = _safe_json(rd, None)
            return body if isinstance(body, dict) and body.get("data") else None
    except Exception:
        return None


async def _fetch_ticket_detail(token: str, ticket_ref: str) -> dict | None:
    """按售后工单 id（tkt_…/UUID）或工单号（AS-…）查 admin-api 工单详情；查不到返回 None。

    与 `_fetch_order_detail` 同构（两条路径都试）：先按 id 直查
    （`GET /api/admin/after-sales/{id}`），不成立再按**关键词搜工单号**拿 id 再查详情。
    只按引用直查会漏（agent 有可能传工单号而非内部 id）。
    """
    ref = str(ticket_ref or "").strip()
    if not ref:
        return None
    try:
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            rd = await c.get(f"{ADMIN_API}/api/admin/after-sales/{ref}", headers=h, timeout=15)
            body = _safe_json(rd, None)
            if isinstance(body, dict) and body.get("data"):
                return body["data"]
            r = await c.get(f"{ADMIN_API}/api/admin/after-sales", headers=h,
                            params={"keyword": ref, "page": 1, "size": 1}, timeout=15)
            items = (_safe_json(r, {}) or {}).get("data", {}).get("items", []) or []
            if not items:
                return None
            tid = str(items[0].get("id") or "")
            if not tid or tid == ref:
                return None
            rd = await c.get(f"{ADMIN_API}/api/admin/after-sales/{tid}", headers=h, timeout=15)
            body = _safe_json(rd, None)
            return body["data"] if isinstance(body, dict) and body.get("data") else None
    except Exception:
        return None


# `output_verify.expect` 里的特殊哨兵：断言该字段**非空**（用于 warning 这类"有意为之"的文本）
OUTPUT_NONEMPTY = "__nonempty__"

# ── 员工/用户落库核对（`db_verify[employee]`，issue #3544 收口 / HR 用例包 #3593 需求）──
# 用例侧字段名 → admin-api `AdminUserController.toEmployeeMap` 实际暴露的路径。
# 为什么需要改名映射：跨层字段名不一致是这轮反复踩到的缺陷类（#3540 reason/remark、
# #3549 name/wechatNickname）—— 核对器按**用例侧口径**收参，读库时按实际路径解析，
# 并把「记录里没有这个字段」显式报出来（而不是静默判过）。
_EMPLOYEE_FIELD_ALIASES = {
    "role_code": ("role", "roles[].code"),
    "employee_name": ("name",),
    "nickname": ("name",),
}

_MISSING = object()


def _record_path_values(detail: dict, path: str):
    """按路径取值（支持 `a` 与 `a[].b` 列表展开）；路径不存在返回 `_MISSING`。

    字段存在但为 null → 返回 None（与"不存在"区分：前者是「落库为空」，后者是「读错字段」，
    两者的修法完全不同，必须能分辨 —— 同 `db_verify[order_phone]` 的「查不到手机号/未落库？」）。
    """
    cur: list = [detail]
    for part in path.split("."):
        expanded = part.endswith("[]")
        key = part[:-2] if expanded else part
        nxt: list = []
        for node in cur:
            if not isinstance(node, dict) or key not in node:
                continue
            val = node[key]
            if expanded:
                if isinstance(val, list):
                    nxt.extend(val)
            else:
                nxt.append(val)
        if not nxt:
            return _MISSING
        cur = nxt
    return cur[0] if len(cur) == 1 else cur


def _employee_lookup(detail: dict, key: str) -> tuple:
    """按用例侧字段名取值 → (是否找到, 值)。候选：字面 key → camelCase → 跨层改名。"""
    cands = [key]
    if "_" in key:
        head, *rest = key.split("_")
        cands.append(head + "".join(p.title() for p in rest))
    cands.extend(_EMPLOYEE_FIELD_ALIASES.get(key, ()))
    for cand in cands:
        val = _record_path_values(detail, cand)
        if val is not _MISSING:
            return True, val
    return False, None


def _employee_value_matches(want, got) -> bool:
    """期望值与落库值比对：任一侧是列表时按「任一元素命中」判定（roles[].code 形态）。"""
    wants = want if isinstance(want, list) else [want]
    gots = got if isinstance(got, list) else [got]
    return any(_norm_text(w) == _norm_text(g) for w in wants for g in gots)


async def _fetch_employee(token: str, emp_id: str = "", name: str = "") -> tuple:
    """按用户 id 或姓名查 admin-api 员工记录（落库真身）→ (记录 或 None, 诊断说明)。

    取数路径与写入路径同一实体：`employee_manage` 的写操作打到 `/api/admin/users/{id}`，
    读回也走 `GET /api/admin/users/{id}`（或 `?keyword=` 列表，`toEmployeeMap` 同一套字段）。
    歧义（同名多条）**不猜**：宁可判失败（宁红不假绿），把命中条数写进说明。
    """
    if not emp_id and not name:
        return None, "缺 id/name（定位不到记录）"
    try:
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            if emp_id:
                r = await c.get(f"{ADMIN_API}/api/admin/users/{emp_id}", headers=h, timeout=15)
                body = _safe_json(r, None)
                data = (body or {}).get("data") if isinstance(body, dict) else None
                if isinstance(data, dict) and data:
                    return data, ""
                return None, f"GET /api/admin/users/{emp_id} 无 data"
            r = await c.get(f"{ADMIN_API}/api/admin/users", headers=h,
                            params={"keyword": name, "page": 1, "size": 20}, timeout=15)
            items = (_safe_json(r, {}) or {}).get("data", {}).get("items", []) or []
            exact = [it for it in items if _norm_text((it or {}).get("name")) == _norm_text(name)]
            cands = exact or items
            if len(cands) == 1 and isinstance(cands[0], dict):
                return cands[0], ""
            return None, (f"keyword={name!r} 命中 {len(items)} 条（同名精确 {len(exact)} 条）"
                          f"—— 不猜，判失败")
    except Exception as e:                                      # noqa: BLE001
        return None, f"查询异常 {type(e).__name__}"


# 落库记录谓词 DSL：`<字段><==|!=|>=|<=|>|<|~><值>`（`~` = 包含，用于文本）。
# `字段!=null` 是「必须已写入」形态（null 与空串/空列表都算未落库）——
# 完成时间/关闭时间这类"该写没写"的静默缺陷就靠它抓（#3544：closedAt/closeReason 同族）。
_RECORD_CHECK_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.\[\]]*)\s*(==|!=|>=|<=|>|<|~)\s*(.+)$")


def _evaluate_record_check(record: dict, check: str) -> tuple:
    """评估一条落库记录谓词 → (是否通过, 详情)。

    字段**不存在**（读错字段/跨层改名）与字段**为 null/空**（静默忽略/未写入）给**不同**报错：
    两者修法完全不同（前者改用例字段名，后者查接收侧丢字段）。
    """
    m = _RECORD_CHECK_RE.match(str(check).strip())
    if not m:
        return False, (f"无法解析落库谓词 {check!r}"
                       f"（形如 status==completed / completedAt!=null / processor~张）")
    field, op, raw = m.groups()
    val = _record_path_values(record, field)
    if val is _MISSING:
        return False, (f"落库记录里没有字段 {field!r}（实际字段: {sorted(record)}）"
                       f"—— 读错字段/跨层改名，核对不到就不许当通过")
    if op == "!=" and raw.strip().lower() in ("null", "none", ""):
        if val is None or (isinstance(val, (str, list, dict)) and not val):
            return False, (f"落库字段 {field} 为空（期望非空）"
                           f"—— 该写没写/接收侧静默忽略（#3544 同族）")
        return True, ""
    if val is None or (isinstance(val, (str, list, dict)) and not val):
        return False, f"落库字段 {field} 为空（期望 {op}{raw}）"
    if op == "~":
        return (True, "") if _norm_text(raw) in _norm_text(val) else (
            False, f"落库字段 {field}={val!r} 不含 {raw!r}")
    got_s = str(val).strip()
    want_s = raw.strip()
    if op in ("==", "!="):
        same = _norm_text(got_s) == _norm_text(want_s)
        return (True, "") if (same == (op == "==")) else (
            False, f"落库字段 {field}={val!r} {op} {want_s!r} 不成立")
    try:
        g, w = float(val), float(want_s)
    except (TypeError, ValueError):
        return False, f"落库字段 {field}={val!r} 与 {want_s!r} 无法做数值比较"
    ok = {"<": g < w, "<=": g <= w, ">": g > w, ">=": g >= w}[op]
    return (True, "") if ok else (False, f"落库字段 {field}={g:g} 不满足 {op}{w:g}")


async def _fetch_processing_order(token: str, ref: str = "", keyword: str = "") -> tuple:
    """按加工单号/id 或关键词查 admin-api 加工单（落库真身）→ (记录 或 None, 诊断说明)。

    与 `processing_order_query` 同一读取路径（`GET /api/admin/processing-orders`，keyword 同口径，
    响应 `data` 是**裸列表**；兼容分页形态）；命中多条**不猜**（宁红不假绿）。
    """
    if not (ref or keyword):
        return None, "缺回读键（processingOrderNo/id）与 keyword（定位不到加工单）"
    try:
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            r = await c.get(f"{ADMIN_API}/api/admin/processing-orders", headers=h,
                            params={"keyword": ref or keyword}, timeout=15)
            rows = (_safe_json(r, {}) or {}).get("data")
            if isinstance(rows, dict):                 # 兼容分页形态（{items:[…]}
                rows = rows.get("items") or rows.get("list") or []
            if not isinstance(rows, list):
                return None, f"响应 data 形态异常（{type(rows).__name__}）"
            if ref:
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if (str(row.get("processingOrderNo") or "") == ref
                            or str(row.get("id") or "") == ref):
                        return row, ""
                return None, (f"keyword={ref!r} 命中 {len(rows)} 条但无 "
                              f"processingOrderNo/id == {ref!r}")
            if len(rows) == 1 and isinstance(rows[0], dict):
                return rows[0], ""
            return None, f"keyword={keyword!r} 命中 {len(rows)} 条（不猜，判失败）"
    except Exception as e:                                      # noqa: BLE001
        return None, f"查询异常 {type(e).__name__}"


async def _resolve_order_detail(token: str, data: dict):
    """由 `order_create` 的 payload 拿到 (ref, 订单详情)。

    id 与 orderNo 都当候选（ai-agent 返回 id=32 位 hex、orderNo=2026… 两者都可能是
    能被 admin-api 接受的那个形态），逐个尝试到拿到详情为止 —— 单靠任一条都会漏
    （实测：32 位 hex 走关键词搜不到；而订单号 `2026…` 不是合法 path 参数）。
    """
    cands = [str((data or {}).get("id") or ""), str((data or {}).get("orderNo") or "")]
    ref, detail = "", None
    for _c in cands:
        if not _c:
            continue
        detail = await _fetch_order_detail(token, _c)
        if detail:
            ref = _c
            break
    if not detail:
        ref = cands[0] or cands[1]
    return ref, detail


# 完整手机号（中国大陆）：加数字边界，避免把订单号里的 11 位片段误报
# （实测订单号 `20260913027050006` 含 `13027050006`，无边界正则必然误伤）
_FULL_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

_SEED_PHONES_CACHE = None


def _seed_phones() -> set:
    """种子夹具里的手机号（C 端流程复用种子订单收货信息时，号码来源就是这些）。

    缓存一次：夹具是静态文件，且在用例级并发下重复读盘没有意义。
    读不到（文件缺失）时返回空集 —— 与"用例没提供号码"叠加会让来源闭合断言判红，
    这正是想要的**fail-closed** 方向（宁可红，不可假绿）。
    """
    global _SEED_PHONES_CACHE
    if _SEED_PHONES_CACHE is None:
        phones = set()
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "fixtures", "xiaobu_eval_seed.sql")
            with open(p, encoding="utf-8") as f:
                phones = set(_FULL_PHONE_RE.findall(f.read()))
        except Exception:
            phones = set()
        _SEED_PHONES_CACHE = phones
    return _SEED_PHONES_CACHE


def filter_cases_by_ids(cases: list, wanted: str) -> tuple:
    """按 `--case-ids` 收窄用例集（迭代提速，issue #3417）。

    返回 `(保留的用例, 无法解析的 ID 列表)`。**无法解析必须由调用方报错而非静默少跑**
    —— 「跑了两条」若被当成通过，就是本仓库反复出现的假绿同族（如字段只映射了渲染器、
    没映射 CI 加载器）。ID 口径与 `--case-id` 一致：新 ID 与 legacy_id 都认。
    """
    wanted_ids = [x.strip() for x in str(wanted or "").split(",") if x.strip()]
    if not wanted_ids:
        return list(cases or []), []
    by_id = {str(getattr(c, "id", "")): c for c in (cases or [])}
    by_legacy = {str(getattr(c, "legacy_id", "") or ""): c for c in (cases or [])
                 if getattr(c, "legacy_id", "")}
    picked, missing = [], []
    for cid in wanted_ids:
        c = by_id.get(cid) or by_legacy.get(cid)
        if c is None:
            missing.append(cid)
        else:
            picked.append(c)
    return picked, missing


def check_forbidden_card_text(results: list, spec: list) -> list:
    """卡片内容反模式断言（issue #3402）：卡标题/选项/字段值不得出现指定子串。

    与 `forbidden_text`（针对回复文本）互补：**卡片是另一个产出面**，同一认知错误
    换个载体（卡 vs 文本）就能绕过只守文本的断言。C-A1 实证的形态是卡里给出
    「用量 → 6 米（推荐）」= 顾客意图的 2 倍钱，故必须有独立断言。

    spec 支持两种写法：`[{text: "用量"}]` 或 `["用量", "褶皱"]`（后者更简单，不易写错）。
    """
    issues = []
    want = []
    for item in spec or []:
        if isinstance(item, dict):
            t = str(item.get("text") or "")
        else:
            t = str(item or "")
        if t:
            want.append(t)
        else:
            issues.append(f"forbidden_card_text: 空配置（会静默不检查）: {item!r}")
    if not want:
        return issues
    for r in results or []:
        for iv in (r.get("interactive") or []):
            if not isinstance(iv, dict):
                continue
            parts = [str(iv.get("title") or "")]
            for o in (iv.get("options") or []):
                if isinstance(o, dict):
                    parts += [str(o.get("label") or ""), str(o.get("value") or "")]
                else:
                    parts.append(str(o))
            for f in (iv.get("formFields") or []):
                if isinstance(f, dict):
                    parts += [str(f.get("label") or ""), str(f.get("value") or "")]
            blob = " ".join(parts)
            for w in want:
                if w in blob:
                    issues.append(
                        f"卡片出现禁用词「{w}」(R{r.get('__round')}, "
                        f"{iv.get('type') or iv.get('component')}「{iv.get('title')}」) —— "
                        f"C-A1 实证：卡里给「用量/倍数」选项会把顾客意图的金额翻倍")
    return issues


def _norm_text(v) -> str:
    """比对前归一化空白（地址里空格差异不该判红）。"""
    return re.sub(r"\s+", "", str(v or ""))


def check_form_prefill(results: list, spec: list) -> list:
    """form 卡必须**预填**指定字段的真值（issue #3397：老客户收货信息自动带出）。

    为什么补这条断言（此前 `customer_address_query` / `validate_input` 被登记为
    "内部步骤、无独立诉求"而豁免）：
      ① 老客户下单自动带出上次收货信息是核心便利（issue #2815），此前**零断言**；
      ② 预填值必须是**原值** —— 掩码值回流会被顾客原样提交，订单用掩码建号
         （issue #3379 的真实事故形态：`validate_input({"customer_phone": "138****8000"})`）；
      ③ 新客路径（OR-022）守的是"没有历史信息要问/要收集"，这条守**反面**：
         命中历史信息时必须真的带进表单，而不是再问一遍顾客。

    spec 形如 `[{field, expect}]` / `[{field, expect_present: true}]`；失败关闭：
    找不到 form 卡、缺字段、值不符都判红（不跳过）。
    """
    issues = []
    forms = []
    for r in results or []:
        for iv in (r.get("interactive") or []):
            comp = str((iv or {}).get("type") or (iv or {}).get("component") or "")
            if comp == "form":
                forms.append((r.get("__round"), iv))
    for item in spec or []:
        if not isinstance(item, dict):
            issues.append(f"form_prefill: 配置非字典: {item!r}")
            continue
        field = str(item.get("field") or "")
        if not field:
            issues.append(f"form_prefill: 缺 field（空断言）: {item!r}")
            continue
        want = item.get("expect")
        want_present = bool(item.get("expect_present"))
        found_any = False
        hit = None
        for rnd, iv in forms:
            for f in (iv.get("formFields") or []):
                if str((f or {}).get("key") or "") == field:
                    found_any = True
                    hit = (rnd, str((f or {}).get("value") or ""))
        if not forms:
            issues.append(
                f"form_prefill[{field}]: 会话里没有出现任何 form 卡 —— 老客户收货信息没有被带进表单"
                f"（预期：customer_address_query 命中后下发预填 form）")
            continue
        if not found_any:
            issues.append(
                f"form_prefill[{field}]: form 卡里没有字段 `{field}` —— 该字段没有被预填"
                f"（预期带出历史值，实际只问了其它字段）")
            continue
        rnd, got = hit
        if want_present:
            if not got.strip():
                issues.append(f"form_prefill[{field}](R{rnd}): 字段存在但**值为空** —— 等于没预填")
            continue
        if want is not None and _norm_text(got) != _norm_text(want):
            issues.append(
                f"form_prefill[{field}](R{rnd}): 预填值 {got!r} ≠ 期望 {want!r} —— "
                f"预填必须是**真值**（掩码值会被顾客原样提交，导致订单用掩码建号）")
    return issues


_CODE_REQUEST_HINTS = ("验证码", "校验码", "短信码", "动态码", "verification code")


def _agent_asked_for_code(results: list) -> bool:
    """上一轮 agent 是否在**索要验证码**（供码时机的唯一依据）。"""
    if not results:
        return False
    text = str((results[-1] or {}).get("final_text") or "")
    return any(h in text for h in _CODE_REQUEST_HINTS)


def _code_gate_blocked(results: list) -> bool:
    """上一轮的写调用**因缺码被挡**（机器可观测的**硬**信号，issue #3430）。

    与 `_agent_asked_for_code` 分家的理由（issue #3829 / OR-026 根因，判定跑 34908262839）：
    "文字里出现验证码"是**软**信号 —— agent 解释「手机号用来接收下单验证码」也会命中，
    而它并没有在索码；硬信号则是一次**真实发生的**"码没送到"事故（写调用 success=false）。
    两者混为一谈时，软信号会无条件压过"待答 form 卡可回填"，把载荷永久饿死。
    """
    if not results:
        return False
    for st in _tool_result_status((results[-1] or {}).get("tool_results") or []):
        if st.get("ok"):
            continue
        blob = f"{st.get('error') or ''} {st.get('digest') or ''}"
        if any(h in blob for h in _CODE_REQUEST_HINTS) or "短信" in blob or "sms" in blob.lower():
            return True
    return False


def needs_verification_code(results: list) -> bool:
    """顾客这一轮**必须供码**吗：agent 在文字里索要（软），或上一轮的写调用因缺码被挡（硬）。

    为什么不能只看文字（run 34768306581 实证）：agent 每轮都**重发同一张确认卡**，
    而写调用在后台因「缺少短信验证码」失败 —— 若按"有卡先答卡"处理，harness 会一轮轮点卡、
    **验证码永远送不出去**，用例卡死（两轮 trace 的 `you=` 都是确认卡 confirmValue，
    `failed=order_create!缺少短信验证码`）。所以：**明确的索码/缺码信号优先于答卡**
    （答卡可以下一轮再做，码不供就只能原地打转）。

    ⚠️ 本函数保留"软信号也算真"的宽语义（既有调用方零变化）；**优先级裁决**在
    `resolve_repeat_turn` 里做 —— 那里才区分软/硬，见 `_code_gate_blocked`。
    """
    if _agent_asked_for_code(results):
        return True
    return _code_gate_blocked(results)


def repeat_stop_met(results: list, spec: dict) -> bool:
    """`repeat_until` 的停条件：目标工具**已经成功**调用过（issue #3430）。

    为什么要求"成功"而不是"调用过"：被门禁挡回的调用（缺验证码/缺确认）没有推进流程，
    此时停轮等于把用例钉死在失败态；只在成功（或状态未知）时才停。

    `action`（issue #3667）：可选，把停条件从**工具级**收窄到**某一次 action**。
    为什么需要（PG-016 实证 run 34821647043）：状态机三步（issue → start → complete）
    走的是**同一个** `processing_order_update`，工具级停条件在第一步就命中 →
    后两步的重复轮被整体跳过（开始加工的确认卡无人答）→ 用例只能改用 `auto_respond`
    逐轮写死（那正是 `repeat_until` 想消灭的写法）。声明 `action` 后：
    该轮必须**真的发起过**这个 action 的调用，且**对齐到的那次调用**成功才停。
    """
    want = str((spec or {}).get("tool_called") or "").strip().lower()
    if not want:
        return False
    want_action = str((spec or {}).get("action") or "").strip()
    saw_status = False
    for r in results or []:
        if want_action:
            called, aligned, _legacy = _round_action_result(r, want, want_action)
            if not called:
                continue
            if aligned is not None:
                saw_status = True
                res = aligned.get("result") if isinstance(aligned.get("result"), dict) else {}
                if res.get("success"):
                    return True
                continue
            # 对齐不了（数量不等）→ 落到下面的工具级判定（本轮已确认是目标 action 的调用）
        elif not any(want in str(tc.get("name") or "").lower()
                     for tc in (r.get("tool_calls") or [])):
            continue
        flags = _round_call_success(r, want)
        if flags:
            saw_status = True
            if any(flags):
                return True
        elif not saw_status:
            # 状态未知（无 tool_result，如合成轨迹）→ 退回"调用过即停"
            return True
    return False


def resolve_repeat_turn(results: list, opts: dict, case_form_values: dict | None = None) -> str:
    """协作型顾客的「统一一轮」：**有什么卡答什么卡 → 被问验证码就供码 → 否则说 fallback**。

    为什么需要（issue #3430 实证）：写用例的轮次表是按**某一种**卡片序列写的，而实际序列随模型
    而变（OR-021 实测 `form(R3) → choice(R4) → confirm(R7)`）。固定轮次表一旦错位，
    验证码轮就落在加工项多选卡上（顾客答非所问）→ 卡没人答、流程不前进 → 轮数耗尽时确认卡
    刚发出来就没人答它 → `order_create` 从未发生（OR-021 定向复跑 0/1）。
    验收剧本早就用 `repeat_until + click: auto` 解决过同一问题，本函数把那份语义搬到评测侧。

    Why（issue #3829 / OR-026 C 端腿判红，判定跑 34908262839 @2b8dfbc2）
    ------------------------------------------------------------------
    旧顺序把**文字里提到"验证码"**当成"在索码"，且**无条件优先于答卡** ⇒ 当 agent 卡在
    "手机号不对"这一步、每轮都解释「需要 11 位手机号**用来接收下单验证码**」时，
    harness 每轮都回 `123456`，而它**当轮刚发的那张 form 卡**（`formFields=3`，载荷完全对得上）
    永远没人答 ⇒ `__FORM__` 全场命中 **0** ⇒ `order_create`/`validate_input` 从未发生 ⇒
    用例必红，失败串还写成「agent 不会下单」（归因错人）。零 LLM 重放（真实函数）：
    8 轮全部返回 `123456`，`__FORM__` 命中 0/8。
    （现场 trace：R3/R4/R5 的 `you=` 都是 `123456`，R4/R5 的 `cards=form` 无人答；
    same-fingerprint 首跑 34865780382 复现同一形态 → `reproducible`。）
    ⇒ 治法：**软信号不再压过硬事实**。待答卡里若有**能回填的 form 卡**，先交载荷
    （顾客对着一张明确问收货信息的表单，真实行为就是把信息填进去）。
    只此一格行为改变：
      · 硬信号（写调用因缺码被挡）→ 仍**最优先**供码（语义逐字不变）；
      · 文字索码 **且无可回填 form 卡**（无卡/卡字段对不上/载荷已发过）→ 仍供码（不变）；
      · 无索码信号 → 答卡/fallback（不变）。
    """
    opts = opts or {}
    code = str(opts.get("code") or "123456")
    fallback = str(opts.get("fallback") or "确认下单")
    fv = dict(case_form_values or {})
    fv.update(opts.get("form_values") or {})
    # ① 硬信号（上一轮写调用**因缺码被挡**：一次真实发生的"码没送到"事故）**最高优先**：
    #    agent 重发确认卡 + 后台写调用缺码时，一轮轮点卡会让码永远送不出去
    #    （run 34768306581 实证：R5/R6 都是点卡 → 卡死）。此处语义与旧实现逐字一致。
    if _code_gate_blocked(results):
        return code
    if needs_verification_code(results):
        # ② 软信号（文字提到"验证码"）——**待答卡里有能回填的 form 卡时先交载荷**（issue #3829）：
        #    否则"说明性提及"会让载荷全场送不出去（OR-026 根因）。载荷只交一次：
        #    已发过同一份载荷说明 agent 没接住，此时退回供码（避免「重发同一答复」死循环，
        #    与 `resolve_auto_respond` 对 confirm/choice 的"不重复点同一张卡"同源纪律）。
        _answer = _auto_fill_form(results, fv)
        if _answer and not any(
                str((r or {}).get("user_message") or "").strip() == _answer for r in results):
            return _answer
        return code
    if pending_card_summary(results):
        # ③ 有卡答卡（confirm→confirmValue / choice→首项 / form→__FORM__|json）
        return resolve_auto_respond(results, fallback=fallback, form_values=fv, prefer_text=False)
    return fallback


def resolve_auto_select_turn(results: list, form_values: dict,
                            fallback: str = "第一个") -> str:
    """`auto_select` 轮实际要发的文本（issue #3445 复盘：别发对不上卡片的字面量）。

    语义分三档：
      ① 待答是 **choice** 卡 → 点首项（回该 option 的 value，= 前端点击协议）；
      ② 待答是 **confirm/form** 卡 → **答卡**（`resolve_auto_respond`）——
         实测（run 34789368315 OR-018 首跑）：待答是 form 卡却发字面量「第一个」，
         agent 只能反问「您说的『第一个』指的是哪一项」→ 流程变噪、
         顾客还没给码时模型自造验证码 → 首跑失败（新加的 `ai=` 让这条第一次可见）；
      ③ 无卡片 → 保留 `fallback`（默认「第一个」）：那是**答 agent 的文本提问**
         （重名澄清等场景，卡片内容由 LLM 动态生成、文本指代不稳定，故用字面量）。
    """
    text = _auto_select_first_option(results)
    if text:
        return text
    # 其余情况交给 `resolve_auto_respond`：有 confirm/form 卡 → 答卡；完全没有卡 →
    # 它自己会回 `fallback`（保持「答 agent 文本提问」的旧语义）。
    return resolve_auto_respond(results, fallback=fallback,
                                form_values=form_values, prefer_text=False)


def expand_repeat_turns(user_inputs: list) -> list:
    """把 `repeat_until` 轮展开成 N 份「运行时决定发什么」的轮次（issue #3430）。

    `max` 上限收紧到 8（run 34769925078 实测：OR-021 的协作流程把 6 轮用光后**还差一步**就
    能供码成功；跑通的用例会因停条件提前结束，不吃满上限，故放宽一档对墙钟影响很小）。
    上限仍然存在 —— 重复轮是"顾客继续配合"，不是无限重试。
    """
    out = []
    for msg in user_inputs or []:
        if isinstance(msg, dict) and isinstance(msg.get("repeat_until"), dict):
            spec = msg["repeat_until"]
            try:
                n = int(spec.get("max") or 3)
            except (TypeError, ValueError):
                n = 3
            n = max(1, min(8, n))
            opts = {k: v for k, v in msg.items() if k != "repeat_until"}
            out.extend([{"__repeat__": spec, "opts": opts} for _ in range(n)])
        else:
            out.append(msg)
    return out


# 控制轮的**专属键**（只有"要让 harness 替顾客作答"的轮才会出现这些键）。
# ⚠️ 判据只用这张表，不靠措辞（R5：判据必须建在事实/结构上）：
#   · 字符串能被 `json.loads` 解析成 dict；**且**键集 ⊆ 本表；**且**至少一个键
#   ⇒ 几乎只可能是"作者本意是控制轮、却写成了 YAML 字符串"。
# 顾客真的发一段 JSON 文本的用例不受影响（键集不在表内即放过）。
_CONTROL_TURN_KEYS = frozenset({
    "auto_select", "auto_respond", "repeat_until", "new_session", "auto_fill",
    "text", "images", "code", "fallback", "form_values", "prefer_text",
    "__repeat__", "opts",
})


def check_control_turns_declared(user_inputs: list) -> list:
    """控制轮必须以 **dict**（YAML block style）声明；写成 JSON 字符串 ⇒ 报出来。

    为什么（issue #4042 复核，实证 OR-029 —— #4053 的修法**静默失效**）：
    `run_case` 只把 **dict** 轮解释成控制轮（`isinstance(msg, dict)` →
    auto_select / auto_respond / repeat_until / new_session 分支），**字符串轮一律当纯文本
    发给 agent**。于是把控制轮写成 JSON 字符串（YAML 单引号标量，如
    `'{"auto_select": true}'`）时：
      · harness 把**字面量 JSON 文本**当顾客消息发出去（agent 只会反问"这是什么"）；
      · 卡片无人作答 ⇒ 目标写工具永不执行 ⇒ 用例**恒红**，且归因写成「agent 不写操作」。
    这是标准「声明无消费」静默失效形态（R5），且**没有任何东西会变红** —— 故在跑轮次**之前**
    折进 `case_issues`（与 `check_precondition_declared` 同族：fail-closed、不进 agent 归因）。
    """
    issues = []
    for i, msg in enumerate(user_inputs or [], 1):
        if not isinstance(msg, str):
            continue
        s = msg.strip()
        if not (s.startswith("{") and s.endswith("}")):
            continue
        try:
            parsed = json.loads(s)
        except Exception:
            continue
        if not isinstance(parsed, dict) or not parsed:
            continue
        keys = set(parsed)
        if keys <= _CONTROL_TURN_KEYS:
            issues.append(
                f"user_inputs 第 {i} 轮是**控制轮的 JSON 字符串**（键：{sorted(keys)}）—— "
                f"runner 只把 dict 轮当控制轮，字符串轮会被当**纯文本**发给 agent "
                f"⇒ 该声明静默失效（卡片无人作答、目标工具永不执行，用例恒红且归因错人）。"
                f"请改成 YAML block style 的 dict 轮")
    return issues


async def check_debug_user_precondition(token: str, case) -> list:
    """多身份用例的**前提校验**：身份覆盖必须真的生效（issue #3391，防假绿）。

    为什么必须有（首版教训，实测 run 34746134755）：身份字段只在渲染器里映射、
    CI 真正走的 YAML 装载路径漏映射 → 用例仍以 `debug_customer_1`（**有历史订单**）跑 →
    `customer_address_query` 返回 has_address=true → 用例走的是"有历史地址"路径，
    却报 ✅ 100%（DB 审计里 11 笔订单全挂 debug_customer_1，无一是新客）。
    这类假绿的信号极弱（全绿），故把前提**显式断言**：
    以该身份查「我的订单」必须为空 —— 空 = 覆盖生效（新客无历史），非空 = 覆盖没生效。
    """
    du = str(getattr(case, "debug_user", "") or "")
    if not du:
        return []
    h = {"X-Debug-Role": "customer", "X-Debug-User": du}
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{ADMIN_API}/api/admin/agent/orders/mine",
                            headers=h, params={"page": 1, "size": 5}, timeout=15)
            body = _safe_json(r, {}) or {}
            items = ((body.get("data") or {}).get("items")) or []
    except Exception as e:
        return [f"debug_user 前提校验失败（请求异常）: {type(e).__name__}: {e}"]
    if items:
        return [
            f"新客身份未生效：以 X-Debug-User={du} 查「我的订单」返回 {len(items)} 笔"
            f"（应为 0）—— 身份覆盖没透传/没生效，本用例退化成"
            f"「有历史收货信息」路径（假绿）。检查：case.debug_user 是否映射到装载链路 + "
            f"app/utils/auth.py 是否接受该头"]
    return []


# ── 用例前置的**运行期一致性断言**（issue #3781）───────────────────────────────
# 为什么需要（真实 run 34856561459 的 `AS-003`，两次独立审计在此**判分歧**）：
#   GLM-5.3-Flash 盲审判 `missing_precondition`（「13800138000 名下订单数在用例运行
#   期间还在增长：`orders=10 total=11` → `orders=13 total=13`」），另一个归因包判
#   **真产品缺陷**。两边看的是同一份证据却给出相反归因 —— 根因是**证据里没有"前置是否
#   成立"这一行**：`auto_respond` 选中的是并行用例刚建的订单，究竟是 agent 选错了、
#   还是 harness 没给一个确定的目标单，报告里读不出来。
# ⇒ 治法：让用例能**声明**自己的前置，由 harness 在**运行期**观测它是否漂移：
#   ① 尝试开始前取基线（capture）；
#   ② 尝试结束后取现值（after）；
#   ③ 漂移（`after - capture > max_growth`）→ 记一条**断言级失败**，原文形如
#      `precondition[order_count_for_phone]: … (capture=… → after=…)` —— 于是
#      「前置不成立」与「行为失败」在 summary 的 `failures` 里**形态不同、可机器分辨**，
#      不再需要靠人读日志猜（这正是两次审计分歧的治本点）。
# ⚠️ 措辞红线：成功路径的消息**不得含**「未复位」/「失败」（见 `_run_pre_clean` docstring）。
_PRECONDITION_NO_DRIFT = 0

# ── precondition type 的**唯一真相源**（issue #3835）────────────────────────────
# 键 = `precondition[].type`；值 = 该 type 的 `source` 是什么（只用于**消息措辞**，
# 让"哪个靶子坏了"在报告里一眼可读）。
# ⚠️ **未登记的 type 必须仍然 fail-closed**（`check_precondition_declared` 报 config_error，
# 不让用例带一个不生效的守卫跑）—— 新增 type 时只加这里 + 在捕获/回读点接上探针，
# **不得**放宽 `check_precondition_drift` / `check_precondition_declared` 的兜底分支。
_PRECONDITION_TYPES: dict = {
    "order_count_for_phone": "手机号名下订单数",
    "product_count_for_keyword": "名字含该关键词的商品件数",
    # 评测可控权限（issue #4108）：`source` = 用例声明的 `debug_permissions`（逗号分隔权限码）。
    # 判据**不是**"数一个共享字面量有没有漂移"，而是"**本用例的权限范围是否真的生效**"——
    # 见 `check_debug_permissions_effective`。`source` 语义与上两条一致 =「我依赖的那个
    # 不可变键」；此处那个键就是用例自己声明的权限码串（渲染器与用例**同源**）。
    "debug_permissions_effective": "本用例声明的 DEBUG 权限范围是否真的生效",
}


def precondition_capture_shape(specs: list) -> dict:
    """声明的前置断言里**需要取基线**的源（按类型）——纯函数，便于单测与静态守卫。

    当前支持（唯一真相源 = `_PRECONDITION_TYPES`）：
      · `order_count_for_phone`：`{"source": "<手机号>"}` → 基线 = 该号码名下订单总数。
      · `product_count_for_keyword`：`{"source": "<商品名关键词>"}` → 基线 = 名字**含该关键词**
        的商品件数（口径与 `product_remove`/`product_dedupe` 同一份实现
        `_list_products_matching`，**不复制第二份"怎么数商品"的定义**）。
        `source` 字段名对两种类型语义一致 =「我依赖的那个共享资源**的不可变键**」。
    返回 `{type: [source, …]}`（保序去重）。未知类型原样返回 —— 由
    `check_precondition_declared` 静态守卫判"声明了没人实现的类型"（fail-closed）。
    """
    out: dict = {}
    for s in specs or []:
        if not isinstance(s, dict):
            continue
        t = str(s.get("type") or "")
        if not t:
            continue
        out.setdefault(t, [])
        src = str(s.get("source") or "")
        if src and src not in out[t]:
            out[t].append(src)
    return out


async def _probe_phone_order_count(token: str, phone: str) -> int | None:
    """该手机号名下订单**总数**（`PageResponse.total`）；取不到返回 None。

    走 `GET /api/admin/orders?receiver=<手机号>`（`OrderController.getOrders` 的
    `receiver` 参数，服务端按收货人手机号过滤）—— 与 `AS-003` 的
    `order_query` 定位同一批订单，故"总数增长"就是该用例前置被破坏的**直接观测值**。
    返回 None = 请求/解析异常（**不**当成 0：0 会被读成"订单没了"，是另一种误判）。
    """
    if not str(phone or "").strip():
        return None
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{ADMIN_API}/api/admin/orders", headers=_admin_headers(token),
                            params={"receiver": str(phone), "page": 1, "size": 1}, timeout=15)
            body = _safe_json(r, None)
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    data = body.get("data") or {}
    total = data.get("total")
    try:
        return int(total)
    except (TypeError, ValueError):
        return None


async def _probe_product_count(token: str, keyword: str) -> int | None:
    """名字**含该关键词**的商品件数；取不到返回 None（issue #3835）。

    口径与 `product_remove`/`product_dedupe` **共用同一份实现**
    （`_list_products_matching`：服务端 keyword 模糊匹配 + 客户端 `kw in name` 精确子串）——
    这样"清理动作删的"与"前置断言数的"必定是同一批对象（§18 单一真相源）。
    返回 None = 请求/解析异常（**不**当成 0：0 会被读成"商品没了"，是另一种误判）。
    """
    if not str(keyword or "").strip():
        return None
    try:
        async with httpx.AsyncClient() as c:
            return len(await _list_products_matching(c, token, str(keyword), size=50))
    except Exception:
        return None


def check_precondition_drift(specs: list, before: dict, after: dict) -> list:
    """运行期前置一致性断言（**纯函数**，issue #3781 / #3835）——返回断言级问题串。

    `before`/`after` 形态：`{"<type>:<source>": int}`（取不到的源不入字典）。
    **两条判据**（缺任一条都会让"前置坏了"伪装成"agent 表现不好"）：
      ① **基线判据**（可选，声明 `expect: <int>` 时生效）：`before != expect` ⇒
         前置**本就不成立**（例如用例开跑时同名商品已有 2 件 —— 上一跑的残留/别人的
         运行期污染）。只看漂移会漏掉这一格：基线本来就是坏的，`after - before` 仍为 0。
      ② **漂移判据**：`after - before > max_growth`（默认 `_PRECONDITION_NO_DRIFT = 0`，
         即"运行期间**不得**新增"）⇒ 前置被**运行中的并行用例**改写。
    取不到基线/现值时**不报**（那是环境层问题，由 pre_clean 消息与 infra 通道承载；
    在这里报会把"网络抖动"伪装成"前置不成立"，正是本仓库反复踩的归因污染）。

    ⚠️ 这是**前置**断言，不是行为断言：它判的是"harness 给的靶子还在不在"，
    与 agent 对错**正交** —— 故消息里显式写出 `capture/after` 两个读数。
    消息统一以 `precondition[<type>]` 开头 ⇒ 被 `_failure_signature` 折成
    `precondition_not_applied(declared)`，与行为失败分属不同根因原子。
    """

    issues = []
    for s in specs or []:
        if not isinstance(s, dict):
            issues.append(f"precondition: 配置非字典: {s!r}（该断言会静默跳过）")
            continue
        t = str(s.get("type") or "")
        src = str(s.get("source") or "")
        if not t or not src:
            issues.append(f"precondition: 配置缺 type/source（该断言会静默跳过）: {s!r}")
            continue
        if t not in _PRECONDITION_TYPES:
            issues.append(
                f"precondition: 未知 type {t!r}（该断言会静默跳过）—— "
                f"请实现后再声明，禁止留一个不生效的守卫")
            continue
        key = f"{t}:{src}"
        b, a = before.get(key), after.get(key)
        if b is None or a is None:
            continue
        what = _PRECONDITION_TYPES[t]
        expect = s.get("expect")
        if expect is not None:
            try:
                expect_i = int(expect)
            except (TypeError, ValueError):
                issues.append(
                    f"precondition[{t}]: `expect` 非整数（该断言会静默跳过）: {expect!r}")
                continue
            if b != expect_i:
                issues.append(
                    f"precondition[{t}]: 前置**本就不成立** —— {what} {src!r} "
                    f"capture={b}，而用例声明 expect={expect_i}。本次红/绿**不可归因于 "
                    f"agent 行为**：靶子在被测事件发生**之前**就已经不是用例依赖的那个"
                    f"（典型来源：上一跑的残留、或别的用例在运行期造了同名副本，#3835）")
                continue
        try:
            max_growth = int(s.get("max_growth", _PRECONDITION_NO_DRIFT))
        except (TypeError, ValueError):
            max_growth = _PRECONDITION_NO_DRIFT
        if a - b > max_growth:
            issues.append(
                f"precondition[{t}]: 前置在本次运行期间漂移 —— {what} {src!r} "
                f"capture={b} → after={a}（允许增长 ≤{max_growth}）。本次红/绿"
                f"**不可归因于 agent 行为**：并行用例改写了本用例依赖的目标集合"
                f"（`auto_respond` 选中的可能是别人刚建的对象）")
    return issues


async def _probe_employee_absent(token: str, emp_id: str = "", name: str = "",
                                 phone: str = "") -> tuple:
    """该员工/用户是否**不存在**（负效果断言的取数基元，issue #4108）→ (bool | None, 说明)。

    · `True`  = 确认不存在（可以判绿）；
    · `False` = 存在（命中即越权产物 ⇒ 调用方判红）；
    · `None`  = **取数失败**（HTTP 异常/非 2xx）—— 调用方必须判失败，**不得**读成"不存在"：
      `_safe_json` 对非 JSON/瞬断按空结果降级，把"查不到"当"没有"会让这条断言在网络抖动时
      **静默变绿**（本仓库「环境层问题伪装成业务结论」的既有形态）。
    · `False` 的判定用**双条件**（name ∧ phone，二者都给了就都要满足）：复用
      `_eval_find_users`（`employee_remove` / `employee_reactivate` 的同一份
      「怎么定位员工」定义），**不另立第二份口径**；只给一个键时按该键匹配。
    """
    _want_name = str(name or "").strip() or str(emp_id or "").strip()
    _want_phone = str(phone or "").strip()
    if not _want_name and not _want_phone:
        return None, "缺 id/name/phone（定位不到对象）"
    try:
        async with httpx.AsyncClient() as c:
            if emp_id:
                r = await c.get(f"{ADMIN_API}/api/admin/users/{emp_id}",
                                headers=_admin_headers(token), timeout=15)
                if r.status_code >= 400:
                    return None, f"GET /api/admin/users/{emp_id} HTTP {r.status_code}"
                body = _safe_json(r, None)
                data = (body or {}).get("data") if isinstance(body, dict) else None
                if isinstance(data, dict) and data:
                    return False, f"id={emp_id} 命中"
            hits = await _eval_find_users(c, _admin_headers(token),
                                          name=str(name or ""), phone=_want_phone)
            if hits:
                return False, f"命中 {len(hits)} 条（name={name!r} phone={phone!r}）"
            return True, ""
    except Exception as e:                                       # noqa: BLE001
        return None, f"查询异常 {type(e).__name__}: {e}"


def check_precondition_declared(specs: list) -> list:
    """声明层静态一致（L0）：声明的 type 必须已有实现（fail-closed，不静默跳过）。"""
    issues = []
    for t in precondition_capture_shape(specs):
        if t not in _PRECONDITION_TYPES:
            issues.append(f"precondition: 声明的 type {t!r} 没有实现（断言会静默跳过）")
    return issues


# ── 评测可控权限的**前置自断言**（issue #4108；CI run 35259795549 的
#    `CASE-TRUST-NO-PRECONDITION-ASSERTION` × 2）────────────────────────────────
# 为什么必须有：`X-Debug-Permissions` 的生效条件是「DEBUG=true ∧ `X-Debug-Role` 非 customer
# ∧ 值过白名单」。任一条不成立（头名拼错 / 值含空格 / 角色写成 customer / 栈里 DEBUG=false）
# ⇒ 服务端**静默回落通配 `["*"]`**（`app/utils/auth.py::_debug_permissions_override`）
# ⇒ HR-009 的「越权被拒」变成「有权限所以成功」，而报告上只表现为
# `unmatched expectation`（**看起来像 agent 不干活**）—— 归因全错，正是 PG-013/CU-003 的形态。
#
# 判据必须是**否定式**的（"回落形态一律红"），而不是"等于声明值即绿"：
# 空值 / 含 `*` / 任一非法码都会让服务端整串回落 ⇒ 生效范围**不可能是**声明值 ⇒ 必红。
def check_debug_permissions_effective(specs: list, effective: str) -> list:
    """核对「用例声明的权限范围」是否真的生效（纯函数）。

    `effective` = 该用例声明的 `debug_permissions`（**值与渲染器同源**，见
    `_case_debug_permissions`）；未声明（空）时不适用 —— 由调用方跳过。
    """
    issues = []
    for s in specs or []:
        if not isinstance(s, dict) or s.get("type") != "debug_permissions_effective":
            continue
        src = str(s.get("source") or "")
        if not src:
            issues.append(
                "precondition[debug_permissions_effective]: 缺 source（声明了权限范围却没说"
                "是哪个范围 —— 断言会静默跳过）")
            continue
        if effective != src:
            issues.append(
                f"precondition[debug_permissions_effective]: 本会话**未以声明的权限范围**跑 —— "
                f"用例声明 {src!r}，实际生效 {effective!r}。"
                f"本用例考的是「该权限范围下的行为」，范围不符时它的红/绿**不可归因于被测行为**。"
                f"核对：`X-Debug-Permissions` 是否真的下发（`_case_debug_permissions` → "
                f"`_chat_headers`）+ 服务端是否回落通配（`*`/空白/空元素/非法码一律回落 `[\"*\"]`）"
                f"+ 栈是否为 DEBUG=true")
    return issues


def check_preclean_not_applied(msgs: list) -> list:
    """把 `pre_clean` 的**未应用/配置错误**折进用例结论（issue #3781）；返回断言级问题串。

    为什么必须有（假绿温床）：`_run_pre_clean` 对"type 未知/未实现"与"目标状态不存在"
    两类情况旧行为都是**返回一句话、调用侧只 print 一行** ⇒ **数据压根没准备，用例照跑**，
    且该用例的红/绿会被读成"agent 能力缺陷"。形态对齐既有
    `db_verify: 不支持的 fetch 配置` → `config_error(db_verify)`。

    判据用**稳定前缀**（`_PRECLEAN_BAD_MARKERS`）而不是宽松的"含『跳过』"：
    后者会把正常的幂等消息（如「客户无「VIP2活跃」标签，无需清理」）误判成配置错误。
    """
    return [str(m) for m in (msgs or [])
            if str(m).startswith(_PRECLEAN_BAD_MARKERS)]


_SMS_CODE_RE = re.compile(r"^\s*(?:短信验证码|验证码)?\s*[:：]?\s*(\d{4,6})\s*$")


def _declared_codes(case) -> set:
    """用例**声明**里可能发出去的验证码（含 `repeat_until.code` / `auto_respond.fallback`）。"""
    out: set = set()

    def _scan(v) -> None:
        m = _SMS_CODE_RE.match(str(v or ""))
        if m:
            out.add(m.group(1))

    for u in getattr(case, "user_inputs", None) or []:
        if isinstance(u, str):
            _scan(u)
        elif isinstance(u, dict):
            _scan(u.get("code"))
            _scan(u.get("fallback"))
            _scan(u.get("text"))
            _scan((u.get("auto_respond") or {}).get("fallback"))
    return out


def _sent_codes(results: list, before_round: int | None = None) -> set:
    """**实际发出去过**的验证码（权威口径 —— 只有它才能说"顾客给过码"）。

    `before_round` 是**必需的**时序约束（issue #3434 复盘，修正自己第一版的错）：
    失败那一刻之后才发出的码**不能**算作"顾客已经给过" ——
    否则会把"先失败 → harness 随后供码"这条**正常时序**误报成
    "顾客早给了码、agent 没带上"（第一版就是这么误判的，差一点写成 agent 缺陷）。
    """
    out: set = set()
    for r in results or []:
        rnd = (r or {}).get("__round")
        if before_round is not None and isinstance(rnd, int) and rnd >= before_round:
            continue
        m = _SMS_CODE_RE.match(str((r or {}).get("user_message") or ""))
        if m:
            out.add(m.group(1))
    return out


def _round_had_code_error(r: dict) -> bool:
    """该轮的 `order_create` 是否**因验证码**失败（缺码/码无效）。"""
    for st in _tool_result_status((r or {}).get("tool_results") or []):
        if st.get("ok"):
            continue
        if "order_create" not in str(st.get("tool") or "").lower():
            continue
        blob = f"{st.get('error') or ''} {st.get('digest') or ''}"
        if any(h in blob for h in _CODE_REQUEST_HINTS) or "短信" in blob:
            return True
    return False


def check_write_code_provenance(results: list, case) -> list:
    """写调用携带的验证码必须来自**顾客给过的码**（issue #3434）。

    为什么需要：失败只表现为 `must_succeed: order_create 共 1 次调用**无一成功**
    （缺少短信验证码）` —— 既不说明"带没带码"，也不说明"带的是不是顾客那个"，
    而 trace 里的码还被脱敏成 `***`，每次都得人肉翻日志还翻不出来。

    判定与**失败耦合**（关键，避免假红）：只有当该轮的 `order_create` **因验证码失败**时
    才检查它的参数 —— 因为 SSE 上报的是**模型原始参数**，而 agent 侧有代码补齐链路
    （`_remember_sms_code` / `_stored_sms_code`）：补上码并成功落单时，若按"原始参数里没码"
    判红，就会把**已经修好的路径**冤枉掉。于是只在"因码失败"时点名两种情形：
      ① 参数里没码 → 代码补齐链路没接上；
      ② 参数里有码但与顾客给过的都不一致 → 疑似模型自造验证码。
    只报轮次与事实，**不打印码本身**；只对 C 端（xiaobu）生效。
    """
    if not is_customer_case(case):
        return []
    declared = _declared_codes(case)
    issues = []
    for r in results or []:
        if not _round_had_code_error(r):
            continue
        rnd = (r or {}).get("__round")
        # 只认**这一轮之前**已经发出的码（时序约束见 `_sent_codes`）
        sent_before = _sent_codes(results, before_round=rnd if isinstance(rnd, int) else None)
        allowed = sent_before | declared
        for tc in (r or {}).get("tool_calls") or []:
            if "order_create" not in str((tc or {}).get("name") or "").lower():
                continue
            got = str(((tc or {}).get("args") or {}).get("sms_code") or "").strip()
            if not got:
                if sent_before:
                    issues.append(
                        f"R{rnd}: order_create 因缺验证码失败，而此时顾客**已经给过**验证码"
                        f"（{len(sent_before)} 个），调用参数里却没有 —— agent 侧代码补齐链路"
                        f"（会话记码→写工具回填）没接上（issue #3434）")
                # 顾客此刻还没给码 → 属于"先失败、随后供码"的正常时序，不在此判
                # （若之后仍无成功调用，由 must_succeed / db_verify 判）
            elif got not in allowed:
                issues.append(
                    f"R{rnd}: order_create 因验证码失败，且参数里的验证码与顾客给过/用例声明的"
                    f"**都不一致** —— 疑似模型自造验证码（issue #3434）")
            break
    return issues


_CUSTOMER_CASE_IDS_CACHE: set | None = None


def _customer_case_ids() -> set:
    """**C 端验收集**的 id 集合（与 `select_cases_for_persona` 同源，避免作用域漂移）。"""
    global _CUSTOMER_CASE_IDS_CACHE
    if _CUSTOMER_CASE_IDS_CACHE is None:
        try:
            _CUSTOMER_CASE_IDS_CACHE = {
                str(c.id) for c in select_cases_for_persona(list(ALL_CASES), "xiaobu")}
        except Exception:
            _CUSTOMER_CASE_IDS_CACHE = set()
    return _CUSTOMER_CASE_IDS_CACHE


def is_customer_case(case) -> bool:
    """该用例是否属于 **C 端验收集**（C 端专属断言的作用域判据）。

    为什么不能用"是否声明 `persona: xiaobu`"（issue #3454）：C 端集里还有 **15 条
    persona 留空（双端）**的用例（靠 #3266 工具集过滤入选，如 OR-014/PR-002/PR-003），
    它们在 C 端跑、计入通过，却会被"声明判据"整个跳过 →
    `check_phone_provenance` / `check_write_code_provenance` 对它们**从未生效**
    （"声称查过而其实没查"家族）。
    故判据与**选择函数同源**：先看它是否被选进 C 端集，其次才回退看声明。
    """
    # **只在本轮就是 C 端 run 时才有意义**：C端专属检查不应在米宝 run 上生效
    # （双端用例也会被米宝 run 选中 → 不加这道闸就会对 B 端链路误报）。
    if PERSONA != "xiaobu":
        return False
    declared = str(getattr(case, "persona", "") or "").strip()
    if declared:
        # **显式声明优先**：persona=mibao 的用例永不算 C 端（B 端链路不同，套 C 端判据会误报 ——
        # 既有用例 TestPhoneProvenance::test_mibao_persona_not_checked 正是锁这条的，
        # 首版把 id 判据放在前面 → 显式 mibao 的用例只要 id 在 C 端集里就会被误判成 C 端）。
        return declared in ("xiaobu", "both")
    # 未声明（= 双端）：以"是否被选入 C 端集"为准（issue #3454 的修法）
    cid = str(getattr(case, "id", "") or "")
    return bool(cid) and cid in _customer_case_ids()


async def check_phone_provenance(token: str, case, results: list) -> list:
    """落库手机号必须能追溯到「本用例提供 / 种子夹具」的号码（issue #3386）。

    比逐用例写 `db_verify[order_phone].expect_phone` 更结构性：**新增用例无需配置**
    就自动受保护。CH-010 的脏号码 `13800008000` 既不是用例给的 `13800138000`、
    也不是种子号码 → 本断言直接判红，不需要人肉审计 DB。
    只对 C 端（xiaobu）生效：B 端米宝给顾客建单时可能从客户档案取号（非用例提供），
    全局套用会误报。
    """
    if not is_customer_case(case):
        return []
    data = _first_successful_data(results or [], "order_create")
    if not data:
        return []          # 没写成功 → 没有落库事实可核（写没写成功由 must_succeed 管）
    supplied = set(_FULL_PHONE_RE.findall(json.dumps(
        getattr(case, "user_inputs", None) or [], ensure_ascii=False, default=str)))
    allowed = supplied | _seed_phones()
    ref, detail = await _resolve_order_detail(token, data)
    got = str(((detail or {}).get("data") or {}).get("customerPhone") or "").strip()
    if not got:
        # 查不到详情/号码 → 不在这里重复报（db_verify[order_phone] 才是"必须能查到"的断言）
        return []
    if got not in allowed:
        return [
            f"落库手机号 {got} 无法追溯到本用例提供的号码 "
            f"{sorted(supplied) or '（无）'} / 种子号码（订单 {ref}）—— "
            f"疑似掩码填充值被静默写库（如 `138****8000` 的 `****` 被模型填成 `0`），"
            f"顾客会收不到短信与配送联系（issue #3386）"]
    return []


def check_no_full_phone(results: list) -> list:
    """C 端回复不得出现**完整手机号**（issue #3379，验收发现的跨用例隐私面）。

    为什么是全局断言而不是某条用例的 forbidden_text：CH-011 只守了"订单卡片脱敏"，
    而泄露发生在**回显收货信息**这条路径（验收 C-A2 R3 给出 `13800138000`）。
    隐私面是跨用例的 —— 每条 C 端用例都该守，故做成 case 级检查（C 端运行时自动生效）。
    掩码形态 `138****8000` 与订单号/验证码都不误报（数字边界 + 只认 `1[3-9]` 开头 11 位）。
    """
    issues = []
    for r in results or []:
        text = str(r.get("final_text") or "")
        for m in _FULL_PHONE_RE.finditer(text):
            issues.append(
                f"回复出现完整手机号 {m.group()}（R{r.get('__round')}）—— C 端应脱敏为 138****8000")
    return issues


def _round_action_result(r: dict, tool: str, action: str) -> tuple:
    """本轮「声明 action 的那次调用」的结果 → `(是否发起该调用, 对齐到的 tool_result, 回退成败)`。

    为什么必须**对齐**而不是"该轮有成功就算"（issue #3667，PP-006 实证 run 34820346966）：
    同一轮里模型可以调**同名工具的多个 action**（首轮 `create_processing_item` 被拒后
    **同轮** `list_categories` 恢复成功）→ 只按工具名在该轮里取首个成功 `tool_result`
    会取到**别的 action** 的 payload（假红；字段名撞上时是假绿）。

    怎么对齐：`tool_result` 事件不带 args（`app/api/sse.py` 只发 `{'tool','result'}`），
    所以「哪个结果是哪次调用的」只能按**同轮同名调用的出现顺序** —— `tool_calls` 与
    `tool_results` 都由 `customer_service_agent` 按 `state.messages` 顺序产出
    （`tool_result` 只是入队到回合末统一 flush，**相对顺序不变**）。

    第三个返回值 `legacy_ok` = 该轮**按工具名**统计的成败，**只在数量对不齐时**
    （合成轨迹/节点重放：`called=True` 且 `aligned=None`）由调用方回退使用 —— 向后兼容旧语义，
    不猜。对齐得上时它就是"那一次自己"的成败，精度只增不减。
    """
    calls = [tc for tc in (r or {}).get("tool_calls") or []
             if _tool_name_matches((tc or {}).get("name"), tool)]
    hit = [i for i, tc in enumerate(calls)
           if str(((tc or {}).get("args") or {}).get("action") or "") == action]
    if not hit:
        return False, None, None
    results = [tr for tr in (r or {}).get("tool_results") or []
               if _tool_name_matches((tr or {}).get("tool"), tool)]
    flags = _round_call_success(r, tool)
    legacy_ok = any(flags) if flags else None
    if len(results) != len(calls):
        return True, None, legacy_ok
    own = (results[hit[0]].get("result") or {})
    return True, results[hit[0]], bool(own.get("success") if isinstance(own, dict) else False)


def _first_successful_payload(results: list, tool: str, action: str = "") -> dict:
    """首个**成功**调用的 `result.data`（可按 `args.action` 限定是**哪一次**调用）。

    为什么需要 action 限定（issue #3544 实测 run 34809483940）：`output_verify` 原先只按
    **工具名**取首个成功结果，而工具是**多 action** 的（`processing_item_manage` 的
    `list_categories` / `create_processing_item` / … 共用一个名字）→ PP-006 的
    `output_verify[name/pricingMethod]` 取到了 R2 `list_categories` 的 payload
    `{'categories': [...]}` → **假红**（真建成功的 R5 payload 从未被核对）；反之若字段名
    撞上（如都叫 `items`）就会**假绿**（核对了错的 action 还说"产出对"）。

    声明 action 时按 `_round_action_result` **对齐到那一次调用**：该 action 这次没成功
    → 换下一轮（**不借同轮别的 action 的 payload** —— 那正是 #3667 修的同轮取错）。
    """
    for r in results or []:
        if action:
            called, aligned, _legacy = _round_action_result(r, tool, action)
            if not called:
                continue
            if aligned is not None:
                res = aligned.get("result") if isinstance(aligned.get("result"), dict) else {}
                if res.get("success") and isinstance(res.get("data"), dict):
                    return res["data"]
                continue
        for tr in r.get("tool_results") or []:
            if not _tool_name_matches(tr.get("tool"), tool):
                continue
            res = tr.get("result") if isinstance(tr.get("result"), dict) else {}
            if res.get("success") and isinstance(res.get("data"), dict):
                return res["data"]
    return {}


def _payload_lookup(payload: dict, key: str) -> tuple:
    """按 `expect` 的键取值 → `(是否找到, 值)`。支持**点号路径**（`result.status`）。

    为什么需要（issue #3667 / PG-016 实证 run 34822527203）：`check_output_verify` 原先只按
    **字面顶层 key** 取值，`result.status` 这类嵌套产出**永远核不到** → 用例只能把 expect
    收敛成扁平键，**丢掉了对嵌套产出的核对能力**（而嵌套恰好是工具回显的常态：
    `processing_order_update` 的 `{action, result:{status,…}}`）。
    取值顺序：**字面 key 优先**（兼容"键名里真有点号"的 payload，不改既有语义）→ 点号逐段下钻。
    边界：只下钻**字典**路径；列表下标（`list.0.status`）暂不支持 —— 有需要时按用例反馈再加。
    """
    if key in payload:
        return True, payload[key]
    cur = payload
    for part in str(key).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
            continue
        return False, None
    return True, cur


def check_output_verify(results: list, output_verify: list) -> list:
    """断言**工具计算结果的 payload**（issue #3367）。

    与既有断言的分工：
      · `expectations: tool(args=…)` → 输入侧（用哪些参数调的）
      · `must_succeed`              → 有没有真的做成功
      · `output_verify`             → **产出侧**（算出来的数对不对）
    为什么必须补：算料报价（curtain_calc）的价值全在算出来的数上，而此前
    "用布量算错/公式选错分支"在评测里完全不可见 —— 只能断言"调了 curtain_calc"。
    数值按容差比较（默认 0.01）；字符串按相等；`__nonempty__` 断言非空。
    多 action 工具务必声明 `action:`，否则会核对到另一个 action 的 payload（#3544 实测假红）。
    失败关闭：找不到成功调用 / 缺 tool / 缺 expect / payload 缺字段 → 一律报错，不静默跳过。
    """
    issues = []
    for spec in output_verify or []:
        if not isinstance(spec, dict):
            issues.append(f"output_verify: 配置非字典: {spec!r}")
            continue
        tool = str(spec.get("tool") or "")
        expect = spec.get("expect")
        if not tool:
            issues.append(f"output_verify: 配置缺 tool（该断言会被静默跳过）: {spec!r}")
            continue
        if not isinstance(expect, dict) or not expect:
            issues.append(f"output_verify[{tool}]: 缺 expect（空断言）: {spec!r}")
            continue
        tol = float(spec.get("tolerance", 0.01))
        action = str(spec.get("action") or "").strip()
        payload = _first_successful_payload(results, tool, action)
        if not payload:
            _scope = f"(action={action})" if action else ""
            issues.append(
                f"output_verify[{tool}]{_scope}: 找不到成功调用的结果（无从核对产出）")
            continue
        for key, want in expect.items():
            found, got = _payload_lookup(payload, key)
            if not found:
                issues.append(
                    f"output_verify[{tool}]: 结果里没有字段 {key!r}（实际字段: {sorted(payload)}）")
                continue
            if want == OUTPUT_NONEMPTY:
                if not str(got or "").strip():
                    issues.append(f"output_verify[{tool}]: {key} 期望非空，实际 {got!r}")
                continue
            if isinstance(want, (int, float)) and not isinstance(want, bool):
                try:
                    if abs(float(got) - float(want)) > tol:
                        issues.append(
                            f"output_verify[{tool}]: {key} 期望 {want}，实际 {got}（差 {float(got) - float(want):+.4f}）")
                except (TypeError, ValueError):
                    issues.append(f"output_verify[{tool}]: {key} 期望数值 {want}，实际 {got!r} 非数值")
                continue
            if str(got) != str(want):
                issues.append(f"output_verify[{tool}]: {key} 期望 {want!r}，实际 {got!r}")
    return issues


async def check_db_verify(token: str, db_verify: list, results: list | None = None) -> list:
    """执行 db_verify 断言：fetch 指定资源 → 逐条评估谓词，返回违规列表。

    `results`：本用例的逐轮结果。`fetch: order_items` 需要它来取订单号
    （必须显式传，不用模块级全局 —— 隐藏状态在并发评测下是 bug 温床）。
    """
    issues = []
    for spec in db_verify or []:
        if not isinstance(spec, dict):
            issues.append(f"db_verify: 配置非字典: {spec!r}")
            continue
        fetch = str(spec.get("fetch") or "")

        if fetch == "order_phone":
            # 落库手机号断言（issue #3386）：`must_succeed` 只看调用成功、
            # `amount_verify` 只核金额、`db_verify[order_items]` 只核明细与数量 ——
            # **手机号写错全链路无感**。CI 实证（run 34742490138）：CH-010 订单
            # `20260913384380002` 落库 `customer_phone = 13800008000`（模型把掩码
            # `138****8000` 的 `****` 填成了 `0`），而用例给模型的是 `13800138000`；
            # 11 位纯数字形态完全合法 → 静默建单成功，顾客收不到短信与配送联系。
            src = str(spec.get("source") or "order_create")
            want = str(spec.get("expect_phone") or "").strip()
            if not want:
                issues.append(
                    "db_verify[order_phone]: 缺 expect_phone（拿不到期望值 → 检查会空转通过）")
                continue
            data = _first_successful_data(results or [], src)
            if not data:
                issues.append(
                    f"db_verify[order_phone]: 找不到 {src} 的成功调用（无订单可核对）—— 判失败而非跳过")
                continue
            ref, detail = await _resolve_order_detail(token, data)
            got = str(((detail or {}).get("data") or {}).get("customerPhone") or "").strip()
            if not got:
                issues.append(f"db_verify[order_phone]: 订单 {ref} 查不到手机号（未落库？）")
                continue
            if got != want:
                issues.append(
                    f"db_verify[order_phone]: 订单 {ref} 落库手机号 {got} ≠ 期望 {want}"
                    f"（掩码填充值会静默写错号码，顾客收不到短信/配送联系）")
            # 收货人/地址的**产出侧**断言（issue #3404 复盘）：只断言"过程用了 form 卡"
            # 会把用例绑死在**机制**上（Agent 用 confirm 卡的字段承载同样合法），
            # 而顾客真正在意的是**订单上的值对不对** → 这里断言落库值。
            _detail = (detail or {}).get("data") or {}
            _name = str(_detail.get("customerName") or "").strip()
            _addr = str(_detail.get("customerAddress") or "").strip()
            want_name = str(spec.get("expect_customer_name") or "").strip()
            if want_name and _norm_text(_name) != _norm_text(want_name):
                issues.append(
                    f"db_verify[order_phone]: 订单 {ref} 收货人 {_name!r} ≠ 期望 {want_name!r}")
            want_addr = str(spec.get("expect_address_contains") or "").strip()
            if want_addr and _norm_text(want_addr) not in _norm_text(_addr):
                issues.append(
                    f"db_verify[order_phone]: 订单 {ref} 收货地址 {_addr!r} 不含 {want_addr!r} —— "
                    f"老客户下单必须沿用库里的收货地址（预填/回显被改写会导致寄错）")
            continue

        if fetch == "order_items":
            # 订单明细落库断言（issue #3367）：must_succeed 只说"调用成功"、
            # amount_verify 只核对**传参**，都不回答"明细真的按行进库了吗"。
            src = str(spec.get("source") or "order_create")
            data = _first_successful_data(results or [], src)
            if not data:
                issues.append(
                    f"db_verify[order_items]: 找不到 {src} 的成功调用（无订单可核对）—— 判失败而非跳过")
                continue
            ref, detail = await _resolve_order_detail(token, data)
            items = ((detail or {}).get("data") or {}).get("items") or []
            if not items:
                issues.append(f"db_verify[order_items]: 订单 {ref} 查不到明细（未落库？）")
                continue
            by_name = {}
            for it in items:
                nm = str((it or {}).get("productName") or "")
                if nm:
                    by_name.setdefault(nm, 0)
                    try:
                        # issue #3666：order_items.quantity 已放宽为 DECIMAL(10,2)
                        # （per_meter 米数 / per_area 面积可为小数），断言用 float 保真
                        by_name[nm] += float((it or {}).get("quantity") or 0)
                    except (TypeError, ValueError):
                        pass
            for want in spec.get("expect_products") or []:
                w = str(want)
                if not any(w in nm or nm in w for nm in by_name):
                    issues.append(
                        f"db_verify[order_items]: 订单 {ref} 明细里没有「{w}」"
                        f"（实际明细: {sorted(by_name)}）")
            # 行级原始明细（issue #3392）：数量不符时**必须能看到行的形状** ——
            # 实测 OR-022 汇总数量 = 9（期望 3），但"单行 9"与"三行各 3"的修法完全不同：
            # 前者是数量值算错、后者是重复行累加（工具层已加 fail-closed 守卫）。
            # 没有这个诊断，失败信息只会说"9 ≠ 3"，排查只能靠猜。
            _lines = " + ".join(
                f"{str((it or {}).get('productName') or '?')}×{float((it or {}).get('quantity') or 0):g}"
                f"@{float((it or {}).get('unitPrice') or 0):g}"
                for it in items)
            _line_count = len(items)
            for w, q in (spec.get("expect_quantities") or {}).items():
                w = str(w)
                hit = next((n for n in by_name if w in n or n in w), None)
                if hit is None:
                    continue
                try:
                    want_q = float(q)
                except (TypeError, ValueError):
                    continue
                if by_name[hit] != want_q:
                    issues.append(
                        f"db_verify[order_items]: 「{hit}」数量 {by_name[hit]} ≠ 期望 {want_q}"
                        f"（订单明细共 {_line_count} 行: {_lines}）"
                        f"—— 行数与逐行数量能区分「数量值算错」与「重复行累加」")
            continue

        if fetch == "processing_order":
            # 加工单**落库**断言（#3544 收口 / 加工单用例包 #3589 需求）：
            # `output_verify` 只看工具**回显**的 payload，「改完真落库了吗」此前无核对能力
            # （现有 fetcher 只有 order_phone/order_items/product_by_name/employee/after_sales_ticket）。
            src = str(spec.get("source") or "processing_order_update")
            action = str(spec.get("action") or "").strip()
            checks = spec.get("checks")
            if isinstance(checks, str):
                checks = [t for t in re.split(r"[,\[\]\s]+", checks) if t]
            if not isinstance(checks, list) or not checks:
                issues.append(
                    "db_verify[processing_order]: 缺/空 checks（配置错误 —— 不核对任何字段 = 空转通过）")
                continue
            # ① 仅在**确有成功写调用**时核对（同 order_phone 口径），且回读键必须来自
            #    **声明的 action** 的成功调用 —— 直接复用 output_verify 的作用域选择器
            #    （`_first_successful_payload`），避免又踩「取到别的 action 的 payload」
            #    （#3544 实测 PP-006 的假红/假绿双面缺陷）。
            _pay = _first_successful_payload(results or [], src, action)
            if not _pay:
                _scope = f"(action={action})" if action else ""
                issues.append(
                    f"db_verify[processing_order]: 找不到 {src}{_scope} 的成功调用"
                    f"（无变更可核对）—— 判失败而非跳过")
                continue
            # ② 回读键：写调用 payload 的 processingOrderNo（或 id）→ 缺失才退回 keyword
            _ref = str(_pay.get("processingOrderNo") or _pay.get("processing_order_no")
                       or _pay.get("id") or "").strip()
            _kw = str(spec.get("keyword") or "").strip()
            if not _ref and not _kw:
                issues.append(
                    "db_verify[processing_order]: 既无回读键（成功调用 payload 的 "
                    "processingOrderNo/id）也无 keyword —— 配置错误，无从定位加工单")
                continue
            _rec, _note = await _fetch_processing_order(token, ref=_ref, keyword=_kw)
            if not _rec:
                issues.append(
                    f"db_verify[processing_order]: 查不到加工单 "
                    f"{_ref or _kw!r}（{_note or '未落库？'}）—— 判失败而非跳过")
                continue
            for _ck in checks:
                _ok, _detail = _evaluate_record_check(_rec, str(_ck))
                if not _ok:
                    issues.append(f"db_verify[processing_order]: {_detail}")
            continue

        if fetch == "employee":
            # 员工/用户**落库**断言（issue #3544 收口 / HR 用例包 #3593 需求）：
            # `must_succeed` 只证明「工具调用成功」、`required_args` 只证明「参数发对了」——
            # **接收侧静默忽略**（#3550 真身：admin-api 丢掉 phone/roleIds 仍回 200）两者都拦不住；
            # 用例的离线自检第 ⑦ 类（下发对 + success=true + 库里未变）此前会被放过。
            # 本核对器读**落库行**定胜负（产出侧，不绑定实现机制）。
            src = str(spec.get("source") or "employee_manage")
            expect_fields = spec.get("expect_fields")
            if not isinstance(expect_fields, dict) or not expect_fields:
                issues.append(
                    "db_verify[employee]: 缺/空 expect_fields（配置错误 —— 不核对任何字段 = 空转通过）")
                continue
            # 仅在**确有成功写调用**时核对（同 order_phone 口径）：没有写调用 = 没有变更事实
            _rnd, _wargs, _ = _first_successful_call(results or [], src)
            if _wargs is None:
                issues.append(
                    f"db_verify[employee]: 找不到 {src} 的成功调用（无变更可核对）—— 判失败而非跳过")
                continue
            _emp_ref = str(spec.get("id") or spec.get("name") or "")
            _emp, _note = await _fetch_employee(
                token, emp_id=str(spec.get("id") or ""), name=str(spec.get("name") or ""))
            if not _emp:
                issues.append(
                    f"db_verify[employee]: 查不到员工/用户 {_emp_ref!r}（{_note or '未落库？'}）"
                    f"—— 判失败而非跳过")
                continue
            for _k, _want in expect_fields.items():
                _found, _got = _employee_lookup(_emp, str(_k))
                if not _found:
                    issues.append(
                        f"db_verify[employee]: 落库记录里没有字段 {_k!r}"
                        f"（实际字段: {sorted(_emp)}）—— 跨层字段名不一致，核对不到就不许当通过")
                    continue
                if _got is None or (isinstance(_got, list) and not _got):
                    issues.append(
                        f"db_verify[employee]: 落库字段 {_k!r} 为空（期望 {_want!r}）"
                        f"—— 接收侧静默忽略（#3550 形态）")
                    continue
                if not _employee_value_matches(_want, _got):
                    issues.append(
                        f"db_verify[employee]: 落库 {_k} 实际 {_got!r} ≠ 期望 {_want!r} "
                        f"（员工 {_emp_ref!r}）—— 下发对 + 调用成功 + 库里没变 = 静默忽略")
            continue

        if fetch == "employee_absent":
            # **负效果**断言（issue #4108）：该员工/用户**不得存在**。
            # 为什么必须有：权限被拒的写用例，其效果层真值是**负向**的（"什么都没落库"）。
            # `must_fail` 只覆盖"没有一次成功调用"；若权限门禁**静默失效**
            # （`X-Debug-Permissions` 被回落成通配、或某天 `check_permission` 被改坏），
            # `create` 会成功 ⇒ 必须有一层读**落库真身**的断言把它判红（#3778「调用了 ≠ 成了」
            # 的反面：**没调用也可能已经成了**，只有落库层能证伪）。
            _abs_name = str(spec.get("name") or "").strip()
            _abs_phone = str(spec.get("phone") or "").strip()
            _abs_id = str(spec.get("id") or "").strip()
            if not (_abs_id or _abs_name or _abs_phone):
                issues.append(
                    "db_verify[employee_absent]: 缺 id/name/phone（定位不到对象 ⇒ 断言永远绿 = 空断言）")
                continue
            _who_abs = _abs_id or _abs_name or _abs_phone
            _found_abs, _note_abs = await _probe_employee_absent(
                token, emp_id=_abs_id, name=_abs_name, phone=_abs_phone)
            if _found_abs is None:
                # ⚠️ **查询失败 ≠ 不存在**（本仓库反复踩的「环境层问题伪装成业务结论」）：
                # `_safe_json` 对非 JSON/瞬断按空字典降级 ⇒ 若把"查不到"直接读成"没有"，
                # 这条断言会在网络抖动时**静默变绿**（假绿）。故取数异常判失败而非跳过。
                issues.append(
                    f"db_verify[employee_absent]: 查不到员工 {_who_abs!r} 的存在性"
                    f"（{_note_abs or '取数异常'}）—— 取不到真值不许当「不存在」")
                continue
            if _found_abs:
                issues.append(
                    f"db_verify[employee_absent]: 员工 {_who_abs!r} **已落库**"
                    f"（{_note_abs or '已存在'}）—— 该操作本应被权限拒绝/不成立；"
                    f"落库即越权产物（脏数据），判失败而非跳过")
            continue

        if fetch == "after_sales_ticket":
            # 售后工单落库断言（issue #3544 / AS-004 假绿升级）：AS-004 的
            # `data_checks: "closedAt/closeReason 写入"` 是自然语义、**不计分**
            # （计分白名单只认 success=true / error.code= / 未被调用，见 run_case）→
            # 「工单真的关闭了、关闭字段真的落库」从未被机器校验（工具回显 success 即可绿）。
            # 本核对器走**产出侧**（不绑定实现机制）：从 after_sales_manage 的成功调用取工单
            # 引用 → 查 admin-api 工单详情 → 断言落库 status 与关闭字段。
            src = str(spec.get("source") or "after_sales_manage")
            expect_status = str(spec.get("expect_status") or "").strip()
            if not expect_status:
                issues.append(
                    "db_verify[after_sales_ticket]: 缺 expect_status"
                    "（拿不到期望值 → 检查会空转通过）")
                continue
            _rnd, _data = _first_successful_ticket_payload(results or [], src, expect_status)
            ticket_ref = _ticket_ref_of(_data)
            if not ticket_ref:
                issues.append(
                    f"db_verify[after_sales_ticket]: 找不到 {src}(status={expect_status}) 的"
                    f"成功调用（无工单可核对）—— 判失败而非跳过")
                continue
            detail = await _fetch_ticket_detail(token, ticket_ref)
            if not detail:
                issues.append(
                    f"db_verify[after_sales_ticket]: 工单 {ticket_ref} 查不到详情（未落库？）")
                continue
            got_status = str(detail.get("status") or "").strip()
            if got_status != expect_status:
                issues.append(
                    f"db_verify[after_sales_ticket]: 工单 {ticket_ref} 落库状态 {got_status!r} "
                    f"≠ 期望 {expect_status!r} —— 工具回显成功 ≠ 落库成功")
            _nonempty = spec.get("expect_fields_nonempty") or []
            if isinstance(_nonempty, str):
                # yaml_light 不解析 flow 序列：`[closedAt, closeReason]` 会整串进来
                _nonempty = [t for t in re.split(r"[,\[\]\s]+", _nonempty) if t]
            for _f in _nonempty:
                _f = str(_f)
                if not str(detail.get(_f) or "").strip():
                    issues.append(
                        f"db_verify[after_sales_ticket]: 工单 {ticket_ref} 落库字段 {_f} 为空"
                        f"（关闭态必须写入 closedAt/closeReason；只记 internalNotes 不算关闭留痕）")
            want_reason = str(spec.get("expect_close_reason_contains") or "").strip()
            if want_reason and _norm_text(want_reason) not in _norm_text(
                    str(detail.get("closeReason") or "")):
                issues.append(
                    f"db_verify[after_sales_ticket]: 工单 {ticket_ref} 落库 closeReason "
                    f"{detail.get('closeReason')!r} 不含期望 {want_reason!r} —— "
                    f"用户点名的关闭原因必须落到 closeReason")
            continue

        if fetch != "product_by_name":
            issues.append(f"db_verify: 不支持的 fetch 配置: {spec!r}")
            continue
        name = str(spec.get("name") or "")
        # 回读**本次写的那条记录**（issue #3689 / PR-019）：声明 `source`（+`action`）时，
        # 回读键取自该次成功写调用的 payload（`product_manage(action=create)` 回
        # `{"product_id":…}`），按 id 直查 —— 与 `db_verify[processing_order]` 的回读口径同源。
        # ⚠️ 为什么不能只靠 keyword：PR-019 的商品名与种子同名同价，keyword 取首条命中的是
        # **种子** ⇒ 种子恒在 ⇒ 该断言不管本次 create 成没成功都绿（假绿，比不加更糟）。
        src = str(spec.get("source") or "")
        action = str(spec.get("action") or "")
        product_id = ""
        if src:
            _pay = _first_successful_payload(results or [], src, action)
            product_id = str(_pay.get("product_id") or _pay.get("productId")
                             or _pay.get("id") or "").strip()
            if not product_id:
                _scope = f"(action={action})" if action else ""
                issues.append(
                    f"db_verify[product_by_name]: 找不到 {src}{_scope} 的成功调用或 payload 里没有 "
                    f"product_id（回读键取自本次成功写调用）—— 判失败而非跳过"
                    f"（静默回退到 keyword 首条正是假绿本身）")
                continue
        if not product_id and not name:
            issues.append(
                f"db_verify[product_by_name]: 缺 name（拿不到商品 → 检查会空转通过）: {spec!r}")
            continue
        configs = (await _fetch_product_configs(token, product_id=product_id, name=name)
                   if product_id else await _fetch_product_configs(token, name))
        for check in spec.get("checks") or []:
            ok, detail = _evaluate_processing_configs_check(configs, str(check))
            if not ok:
                issues.append(f"db_verify[{name or product_id}]: {detail}")
    return issues


# ── post_session：会话关闭后才可观察的落库断言（issue #3357）──
# 长时记忆（user_memories）不是每轮落库：每轮只把候选累积到 session_states，
# **会话关闭时**才 flush 落库（issue #2815 会话末聚合）。因此 run_case 内的
# db_verify 时点太早——必须在 _end_session 之后查询，否则断言的是"抽取还没跑完"
# 这个时序假象，而不是记忆能力本身。
# 查询接口：GET {AI_API}/api/chat/memories（个保法查询权，仅返回当前登录用户自己的记忆）。

def _evaluate_memory_check(memories: list, check: str) -> tuple:
    """评估记忆落库谓词，返回 (是否通过, 详情)。

    支持：
      count>=1 / count==2 / count<=3      条数比较
      has_key:curtain_style               存在该 key 的记忆
      value_contains:奶油风              存在 value 含该子串的记忆
    """
    import re as _re
    c = check.strip()
    m = _re.match(r"^count\s*(>=|<=|==|!=|>|<)\s*(\d+)$", c)
    if m:
        op, raw = m.groups()
        n = int(raw)
        actual = len(memories)
        ok = {">=": actual >= n, "<=": actual <= n, "==": actual == n,
              "!=": actual != n, ">": actual > n, "<": actual < n}[op]
        if not ok:
            keys = [mem.get("key") for mem in memories]
            return False, f"{check} 不满足（实际 {actual} 条，keys={keys}）"
        return True, ""
    if c.startswith("has_key:"):
        key = c.split(":", 1)[1].strip()
        if not key:
            return False, f"无法解析 db 检查: {check!r}（has_key 后缺 key）"
        if any((mem.get("key") or "") == key for mem in memories):
            return True, ""
        keys = [mem.get("key") for mem in memories]
        return False, f"未落库记忆 key={key}（实际 keys={keys}）"
    if c.startswith("value_contains:"):
        sub = c.split(":", 1)[1].strip()
        if not sub:
            return False, f"无法解析 db 检查: {check!r}（value_contains 后缺子串）"
        if any(sub in str(mem.get("value") or "") for mem in memories):
            return True, ""
        vals = [mem.get("value") for mem in memories]
        return False, f"无记忆 value 含「{sub}」（实际 values={vals}）"
    return False, f"无法解析 db 检查: {check!r}"


async def _fetch_user_memories(token: str, agent_type: str = "xiaobu") -> list:
    """查当前登录顾客已落库的长期记忆（agent_type 维度，默认 C 端 xiaobu）。"""
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{AI_API}/api/chat/memories",
                        headers=_chat_headers(token),
                        params={"agent_type": agent_type}, timeout=15)
        payload = _safe_json(r, {}) or {}
        return ((payload.get("data") or {}).get("memories")) or []


async def check_post_session(token: str, post_session: list) -> list:
    """执行会话关闭后的落库断言：fetch 指定资源 → 逐条评估谓词，返回违规列表。"""
    issues = []
    for spec in post_session or []:
        if not isinstance(spec, dict) or spec.get("fetch") != "user_memories":
            issues.append(f"post_session: 不支持的 fetch 配置: {spec!r}")
            continue
        agent_type = spec.get("agent_type") or "xiaobu"
        try:
            memories = await _fetch_user_memories(token, agent_type)
        except Exception as e:
            issues.append(f"post_session[user_memories]: 查询失败 {type(e).__name__}: {e}")
            continue
        for check in spec.get("checks") or []:
            ok, detail = _evaluate_memory_check(memories, str(check))
            if not ok:
                issues.append(f"post_session[user_memories/{agent_type}]: {detail}")
    return issues


async def _close_and_verify_session(case, token: str, r: dict, session_id: str) -> None:
    """关闭用例会话并执行关闭后置断言（失败按用例级失败计入 r）。

    必须在 **run_case 之后、重试分类之前** 调用，使 post_session 断言与普通断言同权：
    失败 → score=0 → 走同一套重试/指纹分类（噪声放行 / 确定性回归显式标注）。
    重试路径同样必须调用（否则重试通过时 post_session 从未被执行 → 假绿）。
    """
    await _end_session(token, r.get("final_session_id") or session_id,
                       debug_user=getattr(case, "debug_user", "") or "",
                       debug_permissions=_case_debug_permissions(case))
    if not getattr(case, "post_session", None):
        return
    try:
        post_issues = await check_post_session(token, case.post_session)
    except Exception as e:
        post_issues = [f"post_session 执行失败: {type(e).__name__}: {e}"]
    if post_issues:
        print(f"     ❌ post_session 断言未通过: {post_issues}")
        r["score"] = 0.0
        r["passed"] = 0
        r["total"] = max(int(r.get("total") or 0), 1)
        r["failed"] = (r.get("failed") or []) + [
            (pi, "post-session check") for pi in post_issues
        ]


def pending_card_summary(results: list) -> str:
    """上一轮**待答卡片**的可读摘要（无卡片返回 ""），用于 `prefer_text` 诊断。

    为什么需要（issue #3421 复盘）：`prefer_text` 会**无视**待答卡片直接发文本 ——
    这是验证码轮必需的语义，但如果那一轮卡片问的是**别的问题**，顾客就等于答非所问，
    流程随即卡死（实测 CH-025 首跑：顾客被问「要哪些加工项」却回了「123456」，
    之后 3 轮空转、`order_create` 从未调用）。这种"用例配置与卡片类型对不上"的错
    **不会报错**，只会表现为随机失败 → 还被重试放行标成 `llm-noise`，把用例缺陷藏起来。
    故把待答卡片显式打出来，让"答非所问"一眼可见。

    **form 卡的字段名**一并打出（issue #3829）：字段名是"载荷能不能回填这张卡"的
    唯一判据，而它此前**只以 `formFields=3` 这样的个数**出现在 trace 里 ——
    OR-026 判红时想确认"是不是字段名对不上"却取不到证据（判定跑 34908262839 的
    `cards=form` / `formFields=3` 两处都不带 key）。本函数只在**用例失败时**打印
    （见 `run_case` 的 prefer_text_notes），所以补字段名不会污染绿跑日志。
    """
    rounds = results or []
    if not rounds:
        return ""
    parts = []
    for iv in ((rounds[-1] or {}).get("interactive") or []):
        comp = str((iv or {}).get("type") or (iv or {}).get("component") or "")
        if not comp:
            continue
        title = str((iv or {}).get("title") or "").strip()
        head = f"{comp}:{title[:24]}" if title else comp
        # form 卡：附上**字段名清单**（`#3803`/`#3829` 的归因证据 —— 零匹配时一眼可辨）
        keys = [str((f or {}).get("key") or "") for f in ((iv or {}).get("formFields") or [])]
        keys = [k for k in keys if k]
        if keys:
            head += "[" + ",".join(keys) + "]"
        parts.append(head)
    return "、".join(parts)


# ── form 卡字段名匹配（issue #3803）─────────────────────────────────────────
# 病灶（判定跑 34873715194 实证）：form 分支按**卡自己声明的 `formFields[].key`** 去交集
# `form_values`，**交集为空就 `return fallback`** —— 静默降级。于是一次"卡片形状漂移"
# （agent 因任何原因改发了另一张形状不同的 form 卡，如「补全客户信息（下单必填）」的字段
# 叫 `name`/`phone`，而用例写的是 `customer_name`/`customer_phone`）会让顾客**永远填不上表**
# ⇒ 用例必红，而失败串写成 `order_create 从未被调用` ⇒ **归因错人**（看起来像 agent 不会下单）。
#
# 两层治法：
#   ① **同义组映射**（下表，**可枚举、可单测**，不是隐式魔法）：精确同名优先，
#      精确没命中时按"卡字段所在的同义组"取载荷 —— 让更多真实卡形状能被回填；
#   ② 仍然一个都对不上时**不许静默**：返回独立签名 `harness_incompatible(form_fields_mismatch)`，
#      由 `run_case` 记为**harness/用例形状不兼容**，不写成 agent 行为失败。
#
# 映射方向以**卡声明的键**为准：`__FORM__|{json}` 的键必须是卡字段名（前端按卡字段回填）。
FORM_FIELD_GROUPS = (
    ("customer_name", "name", "receiver", "consignee", "contact_name", "contact",
     "收货人", "联系人", "姓名"),
    ("customer_phone", "phone", "mobile", "mobile_phone", "tel", "telephone",
     "contact_phone", "手机号", "手机", "电话"),
    ("customer_address", "address", "addr", "shipping_address", "delivery_address",
     "收货地址", "地址"),
    ("color", "colorName", "colour", "color_name", "颜色"),
)
FORM_FIELD_ALIASES = {k: tuple(g) for g in FORM_FIELD_GROUPS for k in g}

HARNESS_INCOMPATIBLE_PREFIX = "__HARNESS_INCOMPATIBLE__|"


def harness_incompatible(kind: str, **detail) -> str:
    """harness/用例形状不兼容的**独立签名**（issue #3803）。

    载荷是 JSON 文本而不是异常：`resolve_auto_respond` 的返回值只承载"这一轮要发什么"，
    抛异常会把整个用例炸成 exception（归因更差）。`run_case` 识别这个前缀后：
    ① 仍然发 fallback 文本（流程继续）；② 记 `harness_incompatible(...)` 独立族失败。
    """
    return HARNESS_INCOMPATIBLE_PREFIX + json.dumps({"kind": kind, **detail}, ensure_ascii=False)


def parse_harness_incompatible(text) -> dict | None:
    """识别 `harness_incompatible(...)` 签名 → dict；不是签名则 None。"""
    s = str(text or "")
    if not s.startswith(HARNESS_INCOMPATIBLE_PREFIX):
        return None
    try:
        data = json.loads(s[len(HARNESS_INCOMPATIBLE_PREFIX):])
    except Exception:
        return {"kind": "unparseable"}
    return data if isinstance(data, dict) else {"kind": "unparseable"}


def match_form_values(card_keys: list, values: dict) -> dict:
    """按**卡声明的字段名**从用例载荷里取值 → `{card_key: value}`。

    ① 精确同名优先（与旧实现逐字一致 ⇒ **正常路径零变化**，反向红证要求）；
    ② 精确没命中时用同义组（`FORM_FIELD_ALIASES`）兜底；仍未命中则跳过该字段。
    值是 `None` 的载荷视为"没给"（`__FORM__` 里塞 null 等于让前端填空）。
    """
    out: dict = {}
    vmap = {str(k): v for k, v in (values or {}).items()}
    for raw in (card_keys or []):
        key = str(raw or "")
        if not key or key in out:
            continue
        if key in vmap and vmap[key] is not None:
            out[key] = vmap[key]
            continue
        for alias in FORM_FIELD_ALIASES.get(key, ()):
            if alias in vmap and vmap[alias] is not None:
                out[key] = vmap[alias]
                break
    return out


# ── 用例资产的**载荷窗口**静态审计（issue #3804）────────────────────────────
# 病灶：载荷（客户信息）原先只声明在固定的第 4、5 轮，而 runner 回填 form 卡需要
# 「**本轮**声明了载荷」×「上一轮待答卡是 form」**同时**成立 ⇒ agent 的发卡时机
# 只要**晚一轮**，窗口就用尽、`__FORM__` 全场命中 0 ⇒ 用例必红，且失败串写成
# `order_create 从未被调用`（归因指向产品）。修法 = **用例级 `auto_fill`**（载荷脱离轮次位置）。
#
# 下面两个纯函数是那条不变式的**单一实现**（L0 `tests/unit_ci_workflows/` 与 L2
# `backend/ai-agent-service/tests/` 共用；两处各写一套就会出现"一个能填一个不能填"的鬼故事）：
#   > 若用例声明了表单载荷，则**最后一个"能作答 form 卡"的轮次**必须能交付载荷。
# 判据取"最后一个"而不是"每一个"是为了**零误报**：早先那些"答别的卡"的轮次没有载荷
# 是合法的 —— 只要**尾部**仍有窗口，agent 晚发卡也能补上。
#
# ⚠️ runner 运行时**不消费**这两个函数（它们是给守卫用的静态审计）；
# 放这里是为了不让守卫各写一份平行实现（与 `flake_history.py` 复用 runner 同款纪律）。


def declared_payload_keys(case: dict) -> set:
    """用例**声明过**的载荷字段名（= 作者预期的 form 卡字段集合）。"""
    keys = set((case.get("auto_fill") or {}).keys())
    for m in (case.get("user_inputs") or []):
        if not isinstance(m, dict):
            continue
        keys |= set(((m.get("auto_respond") or {}).get("form_values") or {}).keys())
        keys |= set((m.get("repeat_until") or {}).get("form_values") or {})
        keys |= set(m.get("form_values") or {})
        keys |= set((m.get("auto_fill") or {}).keys())
    return keys


def payload_window_audit(case: dict) -> dict:
    """单条用例的载荷窗口审计（纯函数，零网络/零 LLM）。

    Returns: {"case_id", "applies", "answer_rounds", "deliverable_rounds",
              "last_answer_round", "violation"}
    """
    expected = declared_payload_keys(case)
    result = {"case_id": case.get("id", ""), "applies": bool(expected),
              "answer_rounds": [], "deliverable_rounds": [],
              "last_answer_round": None, "violation": ""}
    if not expected:
        return result

    # 与 `run_case` 同一装配顺序：case 级 auto_fill 作基座 → 并入所有**轮级** auto_fill
    base = dict(case.get("auto_fill") or {})
    for m in (case.get("user_inputs") or []):
        if isinstance(m, dict) and isinstance(m.get("auto_fill"), dict):
            base.update(m["auto_fill"])

    for idx, turn in enumerate(expand_repeat_turns(list(case.get("user_inputs") or [])), 1):
        if not isinstance(turn, dict):
            continue                                   # 纯文本轮：作答不了卡片
        opts = turn.get("opts") or {}
        can_answer = False
        values = dict(base)
        if turn.get("__repeat__"):
            can_answer = True                          # repeat_until：有卡答卡/被问码供码
            values.update(opts.get("form_values") or {})
        elif turn.get("auto_respond"):
            spec = turn["auto_respond"] or {}
            if spec.get("prefer_text"):
                continue                               # 显式无视卡片（验证码轮）
            can_answer = True
            values.update(spec.get("form_values") or {})
        elif turn.get("auto_fill"):
            can_answer = True
            values.update(turn.get("auto_fill") or {})
        elif turn.get("auto_select"):
            can_answer = True                          # `resolve_auto_select_turn` 也答 form 卡
        if not can_answer:
            continue
        result["answer_rounds"].append(idx)
        # 卡上出现 expected 里任意字段名时，本轮能否交付载荷（与生产同函数）
        if match_form_values(sorted(expected), values):
            result["deliverable_rounds"].append(idx)

    if not result["answer_rounds"]:
        return result
    last = result["answer_rounds"][-1]
    result["last_answer_round"] = last
    if last not in result["deliverable_rounds"]:
        result["violation"] = (
            f"{result['case_id']}: 载荷窗口在最后一个可作答轮次之前用尽 —— "
            f"第 {last} 轮（可作答 form 卡）拿不到载荷；声明窗口只在 "
            f"{result['deliverable_rounds'] or '（没有任何一轮）'}。"
            f"agent 发卡时机晚一轮 ⇒ `__FORM__` 全场命中 0 ⇒ 用例必红且归因错人"
            f"（issue #3804）。修法：加**用例级** `auto_fill:`（载荷脱离轮次位置）。"
        )
    return result


def resolve_auto_respond(results: list, fallback: str, form_values: dict,
                         prefer_text: bool = False, notes: list | None = None) -> str:
    """`auto_respond` 轮：按**上一轮的待答卡片**自动作答，没有卡片则用 fallback。

    为什么要这个机制（CI 实证 run 34627856207，OR-014 / CH-010）：
    用例的 `user_inputs` 是按**某一种**流程形状写的（先选品→再加工项→再确认），
    而 agent 实际的提问顺序与卡片类型随模型而变（实测 OR-014 第 2 轮先发
    「收货信息 & 颜色」表单、第 3 轮才发加工项 choice 卡）。静态脚本对不上就卡死：
    第 4–8 轮每轮只重复 `customer_address_query`，**order_create 永不发生**。

    真实顾客不会"照着脚本说话"，而是**有什么卡就答什么卡** —— 本函数把这一真实行为
    搬进评测，使用例不再依赖某种特定提问顺序。

    优先级（按"最能推进流程"排序）：confirm > choice > form > fallback。
    - confirm → 回 `confirmValue`（前端点击协议就是发这个值），缺失时用 fallback
    - choice  → 回第一个 option 的 value（等同点击首项）
    - form    → 按 form 卡自己声明的 field key 匹配 `form_values`（精确同名优先，其次
                `FORM_FIELD_ALIASES` 同义组），拼 `__FORM__|{json}`
                （与 `_auto_fill_form` 同一协议）；**用例提供了载荷而一个字段都对不上**时
                返回独立签名 `harness_incompatible(form_fields_mismatch)` —— 不再静默
                降级成 fallback 文本（issue #3803：那会让红归因错人）

    `prefer_text=True`（用例声明 `auto_respond: {fallback: ..., prefer_text: true}`）：
    **无视待答卡片，直接发 fallback 文本**。用于"顾客这一刻就是要说这句话"的轮次 ——
    最典型是**验证码轮**：实测（run 34721434317，CH-010 首跑）第 6/7 轮声明的是「123456」，
    但两轮各有一张卡在等（choice/confirm），被 harness 吃掉 →
    顾客从未输入过验证码 → `order_create!缺少短信验证码` → 订单不落库。
    刻意做成**显式开关**而非"fallback 像验证码就自动发文本"：隐式魔法会让用例作者
    猜不到何时生效。
    """
    if prefer_text:
        # 用例显式声明"这一轮就是这句话"（如验证码轮）→ 不答卡。
        # ⚠️ 这条提示是**设计内的正常形态**（作者显式声明 prefer_text），全量档每跑打 7 条
        # （验证码轮 ×4 + 主动打岔 ×3）全是噪声 —— 故改为**只在用例失败时**打印（见 run_case）：
        # 它在失败时是第一归因线索（"harness 是不是把该答的卡吃了"），在绿跑时只是噪声。
        _pending = pending_card_summary(results)
        if _pending:
            _note = (f"R{len(results or []) + 1} prefer_text 忽略了待答卡片 [{_pending}] → "
                     f"本轮发文本 {fallback!r}（用例显式声明 prefer_text=true，属正常形态；"
                     f"若本用例失败，先看这里：卡片问的是不是同一件事）")
            if notes is not None:
                notes.append(_note)
            else:
                print(f"⚠️ {_note}")
        return fallback
    rounds = results or []
    if rounds:
        cards = rounds[-1].get("interactive") or []
        by_comp = {}
        for iv in cards:
            comp = str(iv.get("type") or iv.get("component") or "")
            by_comp.setdefault(comp, iv)

        # 同一张卡**不重复点第二次**（发过的答复不再原样重发）：
        # 模型重发同一张确认卡时，若 harness 逐轮点同一张卡，就会陷入
        # 「模型重发 → 点卡 → 模型再重发」死循环、流程永不前进（CI run 34714932015 实证：
        # CH-010 九轮下来 order_create 三次都被"缺少短信验证码"拒 —— 验证码轮全被点卡吃掉）。
        # 真实顾客点过一次不会再点同一张，而是直接说下一步需要的信息（验证码/补充信息）——
        # 这正是 fallback 的语义，故已发过的答复一律改用 fallback。
        _sent = [str(r.get("user_message") or "").strip() for r in rounds]

        def _already_sent(answer: str) -> bool:
            return bool(answer) and answer.strip() in _sent

        def _repeat_count(answer: str) -> int:
            return sum(1 for m in _sent if m and m == answer.strip())

        confirm = by_comp.get("confirm")
        if confirm is not None:
            value = str(confirm.get("confirmValue") or "").strip()
            # 同一张确认卡**最多点两次**（issue #3365 实测校准）：
            # - 点 1 次后模型若重发同一张卡，那是它**再次征询**，真实顾客会再点一下 → 允许多点 1 次；
            # - 第 3 次起改用 fallback：否则「模型重发 → 反复点卡」会把整场轮数吃光，
            #   验证码轮永远送不出去（CH-010 曾整场 order_create 全部"缺少短信验证码"）。
            # 完全禁止重复点击也不行：实测 CH-010 因此陷入「模型重发确认卡 → harness 只回文本
            # → 模型再重发」的 4 次确认死循环（被 check_confirm_loop 判红）。
            # 两次之后仍重发，则属**模型层**不收敛，交给 check_confirm_loop 如实判红。
            if _repeat_count(value) >= 2:
                return fallback
            return value or fallback

        choice = by_comp.get("choice")
        if choice is not None:
            answer = choice_card_answer(choice)
            # 选择卡同理：同一答复最多两次（首答 + 一次重申），之后走 fallback
            if answer and _repeat_count(answer) < 2:
                return answer

        form = by_comp.get("form")
        if form is not None:
            _card_keys = [str(f.get("key") or "") for f in (form.get("formFields") or [])]
            filled = match_form_values(_card_keys, form_values or {})
            if filled:
                return f"__FORM__|{json.dumps(filled, ensure_ascii=False)}"
            if form_values:
                # 用例**提供了载荷**（它期望被自动回填）而卡字段一个都对不上 ⇒ **不许
                # 静默降级**（issue #3803）：回一个独立签名，由 run_case 记为
                # "harness/用例形状不兼容"（不是 agent 行为失败），本轮仍发 fallback。
                return harness_incompatible(
                    "form_fields_mismatch",
                    card_fields=[k for k in _card_keys if k],
                    case_fields=sorted(str(k) for k in (form_values or {})),
                )

    return fallback


def _auto_fill_form(results: list, values: dict) -> str | None:
    """form 卡自动回填（OR-014 基建缺口）：检测最近一轮 interactive 的 form 卡，
    用 case 声明的字段值构造 `__FORM__|{json}` 回传（FormCard 提交协议，line 98）。

    只填 form 卡声明且 case 提供的字段；缺字段返回 None（调用方 fallback 文本）。
    匹配口径与 `resolve_auto_respond` 的 form 分支**同一处**（`match_form_values`）：
    精确同名优先 + 同义组兜底 —— 两个入口各写一套匹配，就会出现"同一个卡一张能填、
    一张不能填"的鬼故事（issue #3803 的同族风险）。
    """
    if not results:
        return None
    for iv in (results[-1].get("interactive") or []):
        comp = str(iv.get("type") or iv.get("component") or "")
        if comp != "form":
            continue
        _keys = [str(f.get("key") or "") for f in (iv.get("formFields") or [])]
        filled = match_form_values(_keys, values or {})
        if not filled:
            return None
        return f"__FORM__|{json.dumps(filled, ensure_ascii=False)}"
    return None


def choice_card_answer(card: dict) -> str:
    """按**前端真实点击协议**构造 choice 卡的答复（issue #3365）。

    协议（`frontend/admin-web/src/components/chat/InteractiveMessage.tsx`，单一事实源）：
      单选：`sendMessage(opt.label || opt.value)`        —— 发**label**（人话），不是内部 id；
      多选：`sendMessage(`${multiSelectSubmitPrefix || '已选加工项：'}${labels.join('、')}`)`
            —— 前缀由后端卡片驱动 + **label** 以「、」连接（一次性提交，不是每点一次发一条）。

    为什么必须对齐（CI run 34715428643 实证）：harness 此前一律回 `options[0].value`
    （内部 id，如 `pi_eval_punch` / `proc_item_pi_eval_punch`）→ 模型看不懂"顾客选了什么"
    → **反复重发同一张加工项卡**，六轮耗尽也没走到 order_create（用例判红，长相像能力问题）。
    """
    options = (card or {}).get("options") or []
    if not options:
        return ""
    first = options[0] if isinstance(options[0], dict) else {}
    label = str(first.get("label") or first.get("value") or first.get("text") or "").strip()
    if not label:
        return ""
    if (card or {}).get("multiSelect"):
        prefix = str((card or {}).get("multiSelectSubmitPrefix") or "已选加工项：")
        return f"{prefix}{label}"
    return label


def _auto_select_first_option(results: list) -> str | None:
    """从最近一轮 interactive choice 卡取"按前端协议"的答复（自动回放选择）。

    ChoiceCard 点击协议见 `choice_card_answer`（单选发 label、多选发 `前缀+label`）；
    choice 卡内容由 LLM 动态生成，评测用静态 user_inputs 无法预知 →
    user_inputs 的 {"auto_select": true} 让 runner 自动作答第一个选项。
    无 choice 卡返回 None（调用方 fallback 文本指代，兼容 agent 文本澄清路径）。
    """
    if not results:
        return None
    for iv in (results[-1].get("interactive") or []):
        comp = str(iv.get("type") or iv.get("component") or "")
        if comp == "choice" and iv.get("options"):
            return choice_card_answer(iv) or None
    return None


def _legacy_auto_select_first_option(results: list) -> str | None:
    """从最近一轮的 interactive choice 卡取第一个 option 的 value（自动回放选择）。

    ChoiceCard 点击协议 = onAction(opt.value)；choice 卡内容由 LLM 动态生成，
    评测用静态 user_inputs 无法预知 → user_inputs 的 {"auto_select": true} 让
    runner 自动回第一个选项。无 choice 卡返回 None（调用方 fallback 文本指代，
    兼容 agent 文本澄清路径）。
    """
    if not results:
        return None
    for iv in (results[-1].get("interactive") or []):
        comp = str(iv.get("type") or iv.get("component") or "")
        if comp == "choice" and iv.get("options"):
            first = iv["options"][0]
            return str(first.get("value") or first.get("text") or "")
    return None


def _compact_write_args(args: dict) -> dict:
    """写工具入参的**归因摘要**（issue #3394）：保留"钱/量/收件人"证据，裁掉噪音并掩码 PII。

    为什么需要：`order_create` 落库数量 9（期望 3）时，只有**入参**能区分
    「模型一次就传 9」与「重复行各 3」—— 前者改模型/草稿层，后者改工具层守卫，
    方向完全相反。实测为区分这一点多花了一整轮 CI。
    """
    if not isinstance(args, dict):
        return {}
    out: dict = {}
    for k in ("customer_name", "action", "target_action", "tool_id"):
        if args.get(k) not in (None, ""):
            out[k] = str(args[k])[:24]
    # 手机号掩码（轨迹会进 CI 日志）
    for k in ("customer_phone", "phone", "receiver_phone"):
        v = args.get(k)
        if isinstance(v, str) and len(v) >= 7:
            out[k] = v[:3] + "****" + v[-4:]
    # 商品行：名称/数量/单价/小计 —— "数量错"类问题的核心证据
    items = args.get("items")
    if isinstance(items, list):
        out["items"] = [
            {
                "name": str((it or {}).get("product_name") or "")[:24],
                "qty": (it or {}).get("quantity"),
                "unit_price": (it or {}).get("unit_price"),
                "subtotal": (it or {}).get("subtotal"),
            }
            for it in items[:6] if isinstance(it, dict)
        ]
    if args.get("sms_code"):
        out["sms_code"] = "***"
    # 算料入参（issue #3395）：curtain_calc 是**钱的输入** —— 实测模型把顾客的购买米数
    # 当窗宽、并把窗高默认成 2.7 米算出 9 米布；没有这条证据只能看到 `fabric_meters=9.0`
    # 结果摘要，看不到"它假设了什么"。故窗宽/窗高/褶皱倍数一并记录。
    if any(k in args for k in ("window_width", "window_height", "fullness")):
        for k in ("window_width", "window_height", "fullness", "fabric_width", "mounting"):
            if args.get(k) is not None:
                out[k] = args[k]
    return out


def build_round_trace(results: list) -> list:
    """构造逐轮轨迹：每轮的用户输入形态 / 工具 / 卡 / 回复摘要 / **工具成败**。

    为什么需要（issue #3270 归因层）：扁平 `tool_calls` 只说明「整场用过哪些工具」，
    无法回答**哪一轮走了哪个 Skill**——而「路由错到别的 Skill」与「Skill 没给这个
    工具」在报告里完全同形。实测 CH-012 报告为
        tools=['customer_order_query', 'human_handoff', 'aftersale_query']（4 轮）
    既可能是「R1 被路由到 customer_order（该 Skill 无 aftersale_create）」，
    也可能是「R1 路由正确但 LLM 没建单」—— 两种结论的修复方向完全相反。

    另一条同样致命的模糊：`tool_calls` 记录的是 **LLM 发起的调用**，不代表工具真的做成事。
    写工具被 confirm 门禁拦截时返回 `{"success": false, "error": "confirmation_required"}`，
    但调用名照样出现在 `tool_calls` 里 —— 「调了」与「成了」必须分开记，
    否则「写操作其实一次都没落库」会被读成「写操作正常执行」。
    故每轮另记 `results`：`{tool, ok, error}`（来自 SSE tool_result 事件）。

    设计取舍：本函数**只做事实记录，不做 Skill 推断**。Skill 工具集互不重叠，
    读轨迹者用「工具 → Skill」映射即可反推（该映射见
    docs/testing/xiaobu-eval-tooling.md，并以 app/graph/skills/*.py 为单一事实源）。
    刻意不在此处硬编码 Skill 表：local_runner 是零依赖脚本（CI 只装 httpx），
    不能 import app.*，硬编码副本必然与 skill 定义漂移。

    Returns:
        list[dict]: 每轮 {round, tools, results, cards, interactive, text, error}
    """
    trace: list[dict] = []
    for r in results or []:
        text = r.get("final_text") or ""
        trace.append({
            "round": r.get("__round"),
            # 本轮**实际发出**的用户消息（截断）。为什么必须记：协议轮（auto_respond /
            # auto_select / auto_fill）发出的不是用例静态文本，而是 harness 依上一轮卡片
            # 生成的答复（confirm 卡回 confirmValue、choice 卡回首项、form 回 __FORM__|json）。
            # 写操作被门禁拦（confirmation_required）时，「模型没拿到确认」与「harness 答错了
            # 卡」在旧轨迹里同形 —— 实测 OR-014 无法判断 R4 到底发了什么，归因只能靠猜。
            # 这条字段把「输入侧」也变成证据。
            "user": str(r.get("user_message") or "")[:60],
            "tools": [str(tc.get("name", "")) for tc in (r.get("tool_calls") or [])],
            "results": _tool_result_status(r.get("tool_results") or []),
            "cards": [str(c.get("type") or c.get("card_type") or "") for c in (r.get("cards") or [])],
            "interactive": [
                str(iv.get("type") or iv.get("component") or "")
                for iv in (r.get("interactive") or [])
            ],
            # 调用侧卡参数（issue #3365 诊断补强）：`interactive` 来自 SSE 卡事件，
            # **被拦/失败的 interact 不产生事件** → 轨迹里完全看不见，而 check_confirm_loop
            # 数的是「LLM 发起了几次 confirm 卡调用」。实测 OR-017 就卡在这个盲区：
            # 报告说 confirm 卡出现 3 次，打印的轨迹里却一张 confirm 都没有（全是 choice），
            # 归因只能靠猜。这里把每次 interact 调用的 component+title 记下来，
            # 让「想发卡」与「发出卡」都成为证据。
            "card_calls": [
                {
                    "component": str((tc.get("args") or {}).get("component") or ""),
                    "title": str((tc.get("args") or {}).get("title") or "")[:24],
                }
                for tc in (r.get("tool_calls") or [])
                if str(tc.get("name", "")).lower() == "interact"
            ],
            # 写工具**入参**（issue #3394 诊断补强）：本字段是"钱算错"类问题的唯一证据缺口。
            # 实测 OR-022/OR-021：DB 落库数量 9 与 6（期望 3），但轨迹只有 `tools=[order_create]`
            # 与结果摘要 —— 无法判断是"模型一次就传了 9"（模型/草稿层累加）还是
            # "重复行各 3"（工具层守卫可拦）。本轮为区分这一点，浪费了整整一轮 CI + 一次
            # 工具层守卫（守卫最终证明不适用：DB 明细是**单行 ×9**）。
            # 记法：只记**写工具**（数量/金额错的载体），字段按需裁剪；手机号**掩码**
            # （轨迹进 CI 日志，不该留明文）。
            "write_args": [
                {
                    "tool": str(tc.get("name", "")),
                    "args": _compact_write_args(tc.get("args") or {}),
                }
                for tc in (r.get("tool_calls") or [])
                if str(tc.get("name", "")).lower() in _WRITE_TOOL_NAMES
                or str(tc.get("name", "")).lower() == "curtain_calc"
            ],
            # 截断：轨迹用于归因，不是全文存档（全文另见 final_text / 产物）
            "text": text[:60],
            # 逐轮错误**原文**（issue #3365）：此前轨迹只打 `ERR` 标记，看不到是什么错 ——
            # 实测 CH-010 R6 报错、R7 自愈，归因时完全无从下手（容器日志里也没有对应 traceback）。
            "error": str(r.get("error"))[:120] if r.get("error") else None,
        })
    return trace


def _tool_result_status(tool_results: list) -> list:
    """把 SSE tool_result 事件压成 [{tool, ok, error, digest}]。

    `ok` 判定：结果 dict 的 `success` 为真才算成了 —— 缺失 `success` 视为未知，
    按**不成功**记录（宁可显性可疑，不可静默当成成功）。

    `digest`：结果的**极简载荷摘要**（列表给条数、标量给值），用于回答
    「工具成功了，但它返回了什么」——这是区分下面两种"卡住"的唯一证据：
      ① 工具返回空（`items=0` / `has_address=False`）→ 缺数据，改 fixture；
      ② 工具返回正常数据但 LLM 就是不往下走 → 引导层/模型层，改 prompt 或加代码兜底。
    实测 CH-012：4 轮只打 `customer_order_query`、不建单，无 digest 时无法判断是哪一种。
    """
    out = []
    for tr in tool_results or []:
        if not isinstance(tr, dict):
            continue
        res = tr.get("result") if isinstance(tr.get("result"), dict) else {}
        ok = bool(res.get("success"))
        out.append({
            "tool": str(tr.get("tool", "")),
            "ok": ok,
            "error": None if ok else str(res.get("error") or "no_success_flag"),
            "digest": _result_digest(res),
        })
    return out


# 摘要里最多展示多少个字段 / 每个值多少字符（轨迹是日志，不是全量存档）
_DIGEST_MAX_FIELDS = 6
_DIGEST_MAX_VALUE = 40


def _result_digest(res: dict) -> str:
    """结果的极简摘要：`items=2` / `has_address=True` / `error=xxx` 之类。

    只摘 `data` 的顶层字段（列表给长度、标量给值、嵌套给类型名），
    整体截断 —— 目的是让人**一眼判断"有没有数据"**，不是还原载荷。
    """
    if not isinstance(res, dict):
        return ""
    data = res.get("data")
    parts: list = []
    if isinstance(data, dict):
        for k in list(data.keys())[:_DIGEST_MAX_FIELDS]:
            v = data[k]
            if isinstance(v, (list, tuple)):
                parts.append(f"{k}={len(v)}")
            elif isinstance(v, dict):
                parts.append(f"{k}{{}}")
            elif isinstance(v, (str, int, float, bool)) or v is None:
                text = str(v)
                parts.append(f"{k}={text[:_DIGEST_MAX_VALUE]}")
            else:
                parts.append(f"{k}=<{type(v).__name__}>")
        if len(data) > _DIGEST_MAX_FIELDS:
            parts.append(f"(+{len(data) - _DIGEST_MAX_FIELDS} more)")
    elif isinstance(data, list):
        parts.append(f"list={len(data)}")
    elif data is not None:
        parts.append(str(data)[:_DIGEST_MAX_VALUE])
    if not parts:
        # 没有 data（如纯失败）：至少要能看出失败原因
        parts.append(str(res.get("error") or res.get("message") or "empty")[:_DIGEST_MAX_VALUE])
        return " ".join(parts)[:160]

    # 过长时**逐条丢弃字段**而不是整串硬截 —— 硬截会把末尾的 `(+N more)` 省略提示
    # 一起切掉，读者就分不清「结果只有这几个字段」还是「被截断了」（本函数首版即此 bug）。
    marker = ""
    if len(data) > _DIGEST_MAX_FIELDS:
        marker = f"(+{len(data) - _DIGEST_MAX_FIELDS} more)"
    fields = list(parts)
    while fields:
        candidate = " ".join(fields + ([marker] if marker else []))
        if len(candidate) <= 160:
            return candidate
        fields.pop()
    return (" ".join(parts[:1]) + (" " + marker if marker else ""))[:160]


def _mask_phones_in_text(text: str) -> str:
    """把助手回复压成**单行**并掩码手机号（轨迹会进 CI 日志，与写工具入参同纪律）。

    为什么必须压单行（本轮实测，run 34789368315）：助手回复常带换行（列表/多段），
    直接塞进轨迹会把"一格用例一行轨迹"的约定打断 —— 实测 OR-022 首跑轨迹被换行切成
    十几条日志行，`R4`/`R5` 与卡片信息交错，肉眼要拼半天（归因价值大打折扣）。
    """
    flat = " ".join(str(text or "").split())
    return _FULL_PHONE_RE.sub(lambda m: m.group()[:3] + "****" + m.group()[-4:], flat)


def format_round_trace(trace: list) -> str:
    """把逐轮轨迹压成一行，供 CI 日志按用例打印。

    失败的工具带 `!error` 后缀 —— 让「调了但没成」在日志里一眼可见
    （confirm 门禁拦截的写工具就长这样）。
    """
    parts = []
    for t in trace or []:
        bits = [f"R{t.get('round')}"]
        # 输入侧证据：本轮实际发出的消息（协议轮的答复尤其关键——见 build_round_trace）
        if t.get("user"):
            bits.append(f"you={t['user']}")
        bits.append("tools=" + (",".join(t.get("tools") or []) or "-"))
        failed = [f"{x['tool']}!{x['error']}" for x in (t.get("results") or []) if not x.get("ok")]
        if failed:
            bits.append("failed=" + ",".join(failed))
        # 成功但"没数据"同样要可见：工具通了却没内容 = 缺数据（改 fixture），
        # 与"有数据但 LLM 不往下走"（改 prompt/代码）是两种完全不同的处置。
        # **必须无条件打印**：CH-012 那种"工具全成功但流程不走"的形态没有 failed 标记，
        # 若只在失败时附带摘要，最能说明问题的那一轮反而看不到证据。
        digests = [
            f"{x['tool']}({x.get('digest')})"
            for x in (t.get("results") or [])
            if x.get("digest")
        ][:3]
        if digests:
            bits.append("data=" + ";".join(digests))
        # 写工具**入参**（issue #3394）：数量/金额错时必须能看到模型到底传了什么
        # （实测量 9 vs 期望 3 的归因靠这条，否则只能再花一轮 CI 猜）。
        wa = t.get("write_args") or []
        if wa:
            def _one(w):
                a = w.get("args") or {}
                its = a.get("items") or []
                body = "+".join(
                    f"{i.get('name')}×{i.get('qty')}@{i.get('unit_price')}" for i in its) or ""
                extra = ",".join(f"{k}={a[k]}" for k in ("customer_phone", "sms_code") if a.get(k))
                return f"{w.get('tool')}{{{body}{(';' + extra) if extra else ''}}}"
            bits.append("args=" + ",".join(_one(w) for w in wa[:3]))
        # 助手**回复片段**（issue #3445 复盘）：轨迹此前只说模型"调了什么"，不说它"说了什么"——
        # 于是"顾客答完卡、模型空转"（`tools=-`）与"模型在问别的/脚本没答它"在日志里同形，
        # 归因只能靠猜（CH-010 首跑失败即此形，最后只能记 llm-noise 重试放行）。
        # 数据本来就在 `build_round_trace` 的 `text` 字段里，只是没打印；掩码手机号（进 CI 日志）。
        _ai_text = _mask_phones_in_text(t.get("text") or "")
        if _ai_text:
            bits.append(f"ai={_ai_text}")
        if t.get("interactive"):
            _icards = [str(c) for c in t["interactive"]]
            _idup = sorted({c for c in _icards if _icards.count(c) > 1})
            # 同轮同组件多张 = 顾客看到重复卡（issue #3445）：`cards=confirm,confirm`
            # 这个指纹以前是中性字段，没人会去数 —— 标出来才看得见。
            bits.append("cards=" + ",".join(_icards) + ("(⚠️重复)" if _idup else ""))
        # 调用侧的卡（含**被拦/失败**的，那些不会出现在 cards= 里）
        cc = t.get("card_calls") or []
        if cc:
            bits.append("cardreq=" + ",".join(
                (c.get("component") or "?") + ((":" + c["title"]) if c.get("title") else "")
                for c in cc))
        if t.get("error"):
            bits.append(f"ERR({t['error'][:60]})")
        parts.append("[{}]".format(" ".join(bits)))
    return " ".join(parts)


async def run_case(case, token: str, session_id: str) -> dict:
    """运行单个评测用例（多轮对话）

    user_inputs 每轮可为 str（纯文本）或 dict（带图消息 / 自动回 choice 卡 / 跨会话）：
      {"text": "看看这个", "images": ["https://...jpg"]}      # 带图消息
      {"auto_select": true}                                    # choice 卡自动回第一个选项
      {"new_session": true, "text": "上次我说过……"}            # 先关闭当前会话再开新会话（跨会话记忆）
      {"repeat_until": {"tool_called": "order_create", "max": 4},
       "code": "123456", "fallback": "确认下单"}                # 协作型顾客：有卡答卡→被问码供码→否则确认（issue #3430）

    new_session 轮（issue #3357）：发送前先 `_end_session` 关掉当前会话（触发记忆候选
    flush 落库）并新建会话。长期记忆只在**新会话**建立 prompt 时注入，同会话内看不到
    （候选要等会话关闭才落库），所以「老客户偏好识别」这类能力必须跨会话才能判定。
    该轮**必须给 text**（空文本会发出一条空消息，属用例书写错误）。
    """
    results = []
    all_tool_names = []
    session_breaks = 0

    # 多身份用例的**前提校验**（issue #3391）：身份没生效 → 用例会静默走错路径（假绿，
    # 实测 run 34746134755 全绿但订单全挂 debug_customer_1）→ 这里先断言、并把违规
    # 计入 case_issues（跑轮次前做，1 次 HTTP 且不烧 LLM）。
    case_issues: list = []
    # prefer_text 轮"忽略了待答卡片"的诊断（issue #3421 复盘）：**只在用例失败时打印** ——
    # 该形态是作者显式声明的正常形态，绿跑时每跑会产生 7 条噪声（真信号被淹），
    # 但失败时它是第一归因线索。故先收集，判定后再决定打印。
    prefer_text_notes: list = []
    try:
        case_issues += await check_debug_user_precondition(token, case)
    except Exception as e:
        case_issues.append(f"debug_user 前提校验执行失败: {type(e).__name__}: {e}")
    # 前置断言的**声明层**一致性（issue #3781，L0/零 LLM）：声明了没实现的 type
    # ⇒ 断言会静默跳过（"看起来有覆盖"），fail-closed 报出来。
    case_issues += check_precondition_declared(getattr(case, "precondition", None) or [])
    # 评测可控权限的**前置自断言**（issue #4108）：声明的权限范围必须真的生效 ——
    # 否则服务端静默回落通配 `["*"]`，用例考的不是它声称的行为（归因全错）。
    # 纯函数、零 HTTP：`effective` 取自用例自己的声明（与 `_chat_headers` 下发值同源）。
    case_issues += check_debug_permissions_effective(
        getattr(case, "precondition", None) or [],
        _case_debug_permissions(case),
    ) if _case_debug_permissions(case) else []
    # 控制轮的**声明形态**（issue #4042）：写成 JSON 字符串 ⇒ 静默退化成纯文本轮（fail-closed 报出来）
    case_issues += check_control_turns_declared(getattr(case, "user_inputs", None) or [])

    # case 级表单值：所有 `auto_fill` 轮声明的并集 —— auto_respond 轮回答表单时复用，
    # 避免同一份收货信息在用例里重复声明（少一处漂移）
    #
    # **用例级 `auto_fill:`（issue #3804）** —— 载荷**脱离轮次位置**：
    # 旧形态把客户信息只声明在固定的第 4、5 轮（`auto_respond.form_values` 是**轮级**
    # 临时值，不可补充），而 runner 回填需要「本轮声明了载荷」×「上一轮待答卡是 form」
    # **同时**成立 ⇒ agent 的发卡时机只要**晚一轮**（实测 OR-014：R4 被产品侧兜底话术
    # 吃掉），窗口就用尽、`__FORM__` 全场命中 **0**、`order_create` 永不发生 ⇒ 用例必红
    # 且归因指向"agent 不会下单"。用例级声明让载荷在**全场任意轮**都可用。
    # 轮级 `auto_fill` 仍按原语义并入（并集），轮级 `auto_respond.form_values` 仍**只在该轮**
    # 生效（覆盖 case 级）—— 既有用例行为零变化。
    case_form_values: dict = dict(getattr(case, "auto_fill", None) or {})
    for _m in (case.user_inputs or []):
        if isinstance(_m, dict) and isinstance(_m.get("auto_fill"), dict):
            case_form_values.update(_m["auto_fill"])

    # harness/用例形状不兼容（issue #3803）：载荷字段与卡字段零匹配时**不许静默降级**，
    # 也不许把这次红记成 agent 行为失败 —— 收集成独立族，判定时单列。
    harness_incompat: list = []

    # `repeat_until` 轮展开（issue #3430）：把「协作型顾客继续配合」表达成一份轮次，
    # 由运行时按**实际卡片序列/是否被索要验证码**决定这一轮发什么（见 resolve_repeat_turn）。
    _turns = expand_repeat_turns(list(case.user_inputs or []))

    for i, msg in enumerate(_turns):
        images = []
        if isinstance(msg, dict) and msg.get("new_session"):
            await _end_session(token, session_id,
                               debug_user=getattr(case, "debug_user", "") or "",
                               debug_permissions=_case_debug_permissions(case))
            session_id = await get_or_create_session(
                token, prefer_new=True, debug_user=getattr(case, "debug_user", "") or "",
                debug_permissions=_case_debug_permissions(case))
            session_breaks += 1
        if isinstance(msg, dict) and msg.get("auto_select"):
            # choice 卡自动回放（CU-003 回归防线）：上一轮 agent 下发 choice 卡时，
            # 自动回第一个 option 的 value——ChoiceCard 点击协议 = onAction(opt.value)，
            # 而 card 内容（label/value）由 LLM 动态生成，评测用静态 user_inputs
            # 无法预知（「第一个」/「客户A」文本指代均不稳定）。
            # 无 choice 卡（agent 文本澄清路径）→ fallback「第一个」保持旧语义兼容。
            # ⚠️ 但"待答的是 confirm/form 卡"时不能再发「第一个」（对不上卡片）——
            # 见 `resolve_auto_select_turn` 的实证说明。
            text = resolve_auto_select_turn(results, case_form_values)
        elif isinstance(msg, dict) and msg.get("__repeat__"):
            # repeat_until 展开出的轮次：目标工具已成功 → 余下的重复轮直接跳过
            if repeat_stop_met(results, msg.get("__repeat__") or {}):
                continue
            text = resolve_repeat_turn(results, msg.get("opts") or {}, case_form_values)
        elif isinstance(msg, dict) and msg.get("auto_respond"):
            # 合作型用户：优先回答上一轮的待答卡片，无卡则用 fallback 文本
            spec = msg.get("auto_respond") or {}
            if not isinstance(spec, dict):
                spec = {}
            # 允许轮级 form_values 覆盖 case 级 auto_fill 声明
            form_values = dict(case_form_values)
            form_values.update(spec.get("form_values") or {})
            text = resolve_auto_respond(
                results,
                fallback=str(spec.get("fallback") or "确认"),
                form_values=form_values,
                prefer_text=bool(spec.get("prefer_text")),
                notes=prefer_text_notes,
            )
            # §3803：载荷与待答 form 卡字段零匹配 ⇒ 本轮**仍发 fallback**（流程继续），
            # 但把"形状不兼容"记成独立族 —— 不写成 agent 行为失败（归因不落在产品头上）。
            _inc = parse_harness_incompatible(text)
            if _inc is not None:
                harness_incompat.append(_inc)
                text = str(spec.get("fallback") or "确认")
            _pending = pending_card_summary(results)
            if _pending:
                # 失败时的第一归因线索（issue #3803 要求 3）：把**待答卡类型**与**本轮
                # 实际发出的内容**一起留痕，让"是脚本不吃卡/形状不匹配"与"agent 没做"
                # 一眼可分（绿跑不打印，避免每跑刷 7 条噪声 —— 见 prefer_text_notes 说明）。
                prefer_text_notes.append(
                    f"R{i + 1} 待答卡=[{_pending}] → 本轮实发 {text!r}"
                    + (f"（harness_incompatible: {_inc.get('kind')}）" if _inc else ""))
        elif isinstance(msg, dict) and msg.get("auto_fill"):
            # form 卡自动回填（OR-014 基建缺口）：agent 发 form 卡（如客户信息）
            # 时用 case 声明的字段值构造 __FORM__|{json} 回传（FormCard 提交协议）。
            # 用例级 `auto_fill`（issue #3804）作为**基座**并入：否则"声明在哪一轮"又变成
            # 决定成败的位置依赖（轮级 dict 覆盖之，保持既有用例语义）。
            _af = dict(case_form_values)
            _af.update(msg.get("auto_fill") or {})
            text = _auto_fill_form(results, _af) or "确认"
        elif isinstance(msg, dict):
            text = msg.get("text", "")
            images = msg.get("images") or []
        else:
            text = msg
        if isinstance(msg, dict) and msg.get("new_session") and not str(text).strip():
            # 用例书写错误必须响（不是 LLM 波动）：空文本会发出一条空消息，
            # 断言失败详情会指向模型，实际是 harness 输入错误。
            raise ValueError(
                f"用例 {case.id} 第 {i + 1} 轮声明了 new_session 但 text 为空"
                "——跨会话轮必须给出文本"
            )
        r = await send_message(token, session_id, text, images=images,
                               debug_user=getattr(case, "debug_user", "") or "",
                               debug_permissions=_case_debug_permissions(case))
        r["__round"] = i + 1
        r["__all_tool_names"] = [tc["name"] for tc in r["tool_calls"]]
        all_tool_names.extend(r["__all_tool_names"])
        results.append(r)

        # 简单等待，避免请求过快（可配：EVAL_ROUND_SLEEP，见文件头说明）
        if ROUND_SLEEP:
            await asyncio.sleep(ROUND_SLEEP)

    # 汇总所有轮的 tool 名称
    for r in results:
        r["__all_tool_names"] = all_tool_names

    # data_checks 中机器可判定的条目（success=true 等）计入评分（issue #2854 P0-3）
    # 自然语义的 data_checks（如「返回趋势数据」）保持原语义：仅在最后轮错误守卫中参与
    scoring_checks = list(case.expectations or [])
    for dc in (case.data_checks or []):
        dcs = str(dc).strip().lower()
        if "success=true" in dcs or "error.code=" in dcs or "未被调用" in dc or "not called" in dcs:
            scoring_checks.append(str(dc))

    # 检查 expectations + 机器可判定 data_checks
    passed_expectations = 0
    failed_expectations = []
    for exp in scoring_checks:
        passed = False
        detail = ""
        # 在每一轮的结果中检查
        for r in results:
            ok, detail = check_expectation(r, exp)
            if ok:
                passed = True
                break
        if passed:
            passed_expectations += 1
        else:
            failed_expectations.append((exp, detail))

    total_exp = len(scoring_checks)
    score = passed_expectations / total_exp if total_exp > 0 else 1.0

    # 真实验收守卫：最后轮报错 → 整体判失败（除非用例显式预期错误）
    verdict = _last_round_error_verdict(results, case.expectations, case.data_checks)
    if verdict:
        failed_expectations.append((verdict, results[-1].get("error", "")))
        score = 0.0

    # 跨轮 case 级断言（acceptance-protocol §3.1/§3.4）：时序 + final_text 反模式词
    # getattr 兜底：兼容未重新渲染的旧生成物（字段缺失按空处理，行为不变）。
    # ⚠️ 不重置 case_issues：它已承载**跑轮次前**的前提校验结果（多身份，issue #3391）。
    case_issues += check_order_before(results, getattr(case, "order_before", []) or [])
    case_issues += check_forbidden_text(results, getattr(case, "forbidden_text", []) or [])
    # 全程禁用工具（issue #3544 收口批）：`X 未被调用` 写进 data_checks 是「本轮没调用」+
    # 计分「任一轮满足即过」→ 多轮恒真；本断言把「不得尝试」变成跨轮机器判定。
    case_issues += check_forbidden_tools(results, getattr(case, "forbidden_tools", []) or [])
    case_issues += check_want_text(results, getattr(case, "want_text", []) or [])
    case_issues += check_required_args(results, getattr(case, "required_args", []) or [])
    case_issues += check_forbidden_args(results, getattr(case, "forbidden_args", []) or [])
    # 写工具成功断言（issue #3361）：期望里有写工具 ≠ 写操作真的发生。
    # 放在 required_args 之后：先证明「参数给对了」，再证明「东西真做出来了」。
    case_issues += check_must_succeed(results, getattr(case, "must_succeed", []) or [])
    # 必须失败（issue #3544 收口批）：must_succeed 的镜像 —— 「业务不得发生」也要机器可判，
    # 最坏形态是"调了且成了"（脏数据落库），而"调了但失败"/"压根没调"都算合格拒绝。
    case_issues += check_must_fail(results, getattr(case, "must_fail", []) or [])
    # 金额正确性断言（issue #3365）：写成功 ≠ 钱算对（单价接地/小计/总额）
    if getattr(case, "amount_verify", None):
        try:
            case_issues += await check_amount_verify(token, results, case.amount_verify)
        except Exception as e:
            case_issues.append(f"amount_verify 执行失败: {type(e).__name__}: {e}")
    case_issues += check_output_verify(results, getattr(case, "output_verify", []) or [])
    # form 预填断言（issue #3397）：老客户收货信息必须真的带进表单且为真值
    case_issues += check_form_prefill(results, getattr(case, "form_prefill", []) or [])
    # 卡片内容反模式（issue #3402）：卡里不得出现「用量/倍数」这类把顾客意图翻倍的框架
    case_issues += check_forbidden_card_text(
        results, getattr(case, "forbidden_card_text", []) or [])
    if PERSONA == "xiaobu":
        # 隐私面只在 C 端守：B 端客服需要真实号码联系顾客（脱敏会破坏运营）
        case_issues += check_no_full_phone(results)
        # 状态宣告落地：先在 C 端生效（B 端历史用例尚未校准，贸然全局会引入误报）
        case_issues += check_unbacked_state_claim(results)
        # 能力误宣（能做却说做不了，issue #3389）：同样先在 C 端生效
        case_issues += check_false_inability(results)
        # 重复交互卡（issue #3445）：C 端实测同轮两张 confirm 卡（两个发射点各发一张）
        case_issues += check_duplicate_cards(results)
        # 同卡重问（issue #3477 复盘）：顾客已答过又被重问 → 判红
        case_issues += check_repeated_card_ask(results)
    case_issues += check_confirm_loop(results)
    case_issues += check_false_success(results)
    if getattr(case, "db_verify", None):
        try:
            case_issues += await check_db_verify(token, case.db_verify, results)
        except Exception as e:
            case_issues.append(f"db_verify 执行失败: {e}")
    # 号码来源闭合（issue #3386）：落库手机号必须能追溯到用例给的号码/种子号码。
    # 不配在任何用例里 —— 结构性护栏，新增用例自动受保护（CH-010 的脏号码
    # `13800008000` 就是这样被发现的：既不是用例给的、也不是种子号码）。
    try:
        case_issues += await check_phone_provenance(token, case, results)
        # 验证码来源（issue #3434）：把"写调用没带码/带了别的码"点名，别只留一句
        # 「缺少短信验证码」让人肉翻日志（trace 里码还是脱敏的）
        case_issues += check_write_code_provenance(results, case)
    except Exception as e:
        case_issues.append(f"phone_provenance 执行失败: {e}")
    # harness/用例形状不兼容（issue #3803）：**独立族**，措辞必须与"agent 没做"可辨。
    # 判红仍然判红（fail-closed，不放宽任何断言），但归因落在 harness/用例形状上 ——
    # 旧形态把这种红写成 `order_create 从未被调用`，让人去查产品能力（归因错人）。
    for _inc in harness_incompat:
        case_issues.append(
            f"harness_incompatible({_inc.get('kind')}): 用例载荷字段 "
            f"{_inc.get('case_fields')} 与待答 form 卡字段 {_inc.get('card_fields')} "
            f"**零匹配** —— 本次红是 harness/用例形状不兼容，不代表 agent 行为失败"
            f"（改法：用例声明 case 级 auto_fill，或把卡字段写进 FORM_FIELD_ALIASES）")
    if case_issues:
        for ci in case_issues:
            failed_expectations.append((ci, "case-level check"))
        score = 0.0

    # prefer_text 诊断**只在失败用例上落地**（见 prefer_text_notes 的说明）：失败时它是
    # 第一归因线索（"harness 是不是把该答的卡吃了"），绿跑时打它只是噪声。
    if prefer_text_notes and (case_issues or failed_expectations):
        for _pn in prefer_text_notes:
            print(f"  ↳ {_pn}")

    # 通过用例的断言证据（盲审缺陷三）：在返回处计算一次，随结果进 summary。
    # 失败用例同样带上（evidence 是审计材料，不因红而缺）。
    _assertions_fired = _assertions_fired_summary(case, scoring_checks, results, score)

    return {
        "case_id": case.id,
        # 形状不兼容的事实随结果落盘（issue #3803）：判定层据此把它从"agent 行为失败"
        # 里分出来单列（`harness_incompatible_failures`），而不是混进确定性回归清单。
        "harness_incompatible": list(harness_incompat),
        "title": case.title,
        "difficulty": case.difficulty.value,
        "tags": case.tags,
        "rounds": len(results),
        "tool_calls": all_tool_names,
        # ── 逐轮轨迹（issue #3270 归因层）──
        # 扁平 `tool_calls` 只说「整场用了哪些工具」，无法回答**哪一轮走了哪个 Skill**，
        # 于是「路由错」与「工具没给」在报告里长得一模一样（CH-012 实测：
        # tools=['customer_order_query','human_handoff','aftersale_query'] 4 轮，
        # 究竟 R1 路由到了 customer_order 还是 customer_aftersales 无从判断）。
        # Skill 的工具集互不重叠，因此**逐轮工具名可直接反推该轮 Skill** →
        # 归因从猜升级为证据（路由层 / 工具层可区分）。
        "round_trace": build_round_trace(results),
        "passed": passed_expectations,
        "total": total_exp,
        "score": score,
        "failed": failed_expectations,
        "session_breaks": session_breaks,
        # 跨会话用例（new_session 轮）在 run_case 内换了会话：关闭与后置断言必须针对
        # **最后一个**会话（否则残留 active + 末轮记忆候选不 flush）。
        "final_session_id": session_id,
        "last_error": results[-1].get("error") if results else None,
        "final_text": results[-1].get("final_text", "")[:200] if results else "",
        # 盲审缺陷三：通过用例的断言证据 + 假绿候选标记（与 verdict 分开单列，不改 ok）
        "assertions_fired": _assertions_fired,
        "unfailable_green": _unfailable_green(
            score, scoring_checks, _assertions_fired,
            bool(getattr(case, "order_before", None))),
    }

async def run_suite(cases, label: str, classify: bool = True, retry_budget: int = None,
                    concurrency: int = 1):
    """运行一组用例

    classify（默认开，issue #2890 波动分类）：失败用例重试 1 次并判定
    llm-noise / reproducible / unstable / infra（见 _classify_attempts），
    noise 自动放行并记 flake 台账；true regressions 显式标注禁止 rerun 掩盖。

    retry_budget（issue #3361 评测提速）：整跑允许的重试次数上限，None/0 表示不限。
    为什么需要：一次重试 = 整条用例重跑（实测 CH-010/OR-014/OR-017 单条 200-400s，
    4 条失败用例吃掉 19m39s 里的 87%）。失败多的一跑里"逐条重试"是主要成本，
    但它换来的只是**分类标签**，CI 判定（_ci_verdict）只看 score —— 故可设上限：
    前 N 条失败照旧重试/分类，其余直接按首次结果计入（标签标 no-retry-budget），
    报告照样诚实（没有掩盖失败，只是不再为标签支付分钟数）。
    """
    print(f"\n{'='*60}")
    print(f"  {label}: {len(cases)} 个用例" + ("" if classify else "（--no-classify 兼容模式）"))
    print(f"{'='*60}")

    try:
        token = await login()
        print(f"✅ 登录成功")
    except Exception as e:
        print(f"❌ 登录失败: {e}")
        raise RuntimeError(f"登录失败: {e}")

    results = []
    passed_count = 0
    total_score = 0.0
    flake_ledger = []  # 台账：一次运行中「首次失败经分类放行/确认」的用例
    retries_used = 0   # 已消耗的重试次数（受 retry_budget 约束）
    budget_exhausted = False

    async def _pre_clean_for_case(case, gate) -> list:
        """执行用例声明的 pre_clean（写共享数据的**短动作**）；返回消息列表（随结果落盘）。

        issue #3361 提速第三轮：pre_clean 只需**它自身**与其它用例互斥，不必让随后的
        用例主体一起独占（后者会让慢用例变成整跑尾巴）。调用点负责提供独占窗口
        （gate.writer()），且**不能在本任务已持读位时调用** —— 那会死锁。

        为什么返回消息（#3511 归因）：pre_clean 结果此前**只 print**，于是"数据准备没生效"
        与"能力缺陷"在报告里同形 —— B 端首跑 AS-004 实测：R1 `after_sales_manage(items=0)`
        看着像 agent 不会关单，实为该用例 `pre_clean: aftersales_ticket_prepare` 未生效
        （库里 0 条工单）。返回后随用例结果落盘，归因可区分数据层与能力层
        （acceptance-protocol 五层归因：基础设施/数据层优先）。
        """
        msgs = []
        for spec in (getattr(case, "pre_clean", None) or []):
            try:
                _msg = await _run_pre_clean(token, spec)
                if _msg:
                    # 配置错误（未知/未实现的 type）走 ⚠️ 前缀 + **原样保留稳定前缀**，
                    # 由 `_run_one_case` 折进用例结论（issue #3781）——不再只是一行 🧹。
                    _is_cfg = str(_msg).startswith(_PRECLEAN_CONFIG_ERR)
                    print(f"     {'⚠️' if _is_cfg else '🧹'} pre_clean: {_msg}")
                    msgs.append(str(_msg))
            except Exception as e:
                # 失败同样入结果（此前只有 print → 归因时看不见"准备失败"）
                print(f"     ⚠️ pre_clean 失败（非致命）: {e}")
                msgs.append(f"⚠️ pre_clean 失败: {e}")
        return msgs

    _retry_lock = asyncio.Lock()

    async def _reserve_retry() -> bool:
        """判定并**占用**一个重试额度（原子）。

        并发下不能先看 `retries_used < budget` 再 `+=`：两个用例可能同时看到"还有额度"
        → 预算被突破（多跑整条用例 = 多花分钟数）。加锁后语义与串行一致：
        有额度 → 占用并返回 True；无额度 → 返回 False（不消耗、不重复打印提示）。
        """
        nonlocal retries_used, budget_exhausted
        async with _retry_lock:
            if retry_budget is not None and retries_used >= retry_budget:
                if not budget_exhausted:
                    print(f"     ⏳ 重试预算用尽（{retry_budget} 次）：后续失败用例按首次结果计入"
                          "（不再重跑，标签标 no-retry-budget）")
                    budget_exhausted = True
                return False
            retries_used += 1
            return True

    async def _run_one_case(i: int, case, pre_clean_msgs=None, attempt_scope=None,
                            reset_before_retry=None):
        """跑单个用例（会话/重试分类/打印/结果记录）。

        前置的 pre_clean 由调度器在**独占窗口**里先跑（见 `_pre_clean_for_case`），
        其消息通过 `pre_clean_msgs` 传入并**随结果落盘**（#3511：让"数据准备生效与否"
        在报告里可见，与能力缺陷可区分）。

        attempt_scope（issue #3751）：一次尝试的**执行窗口**工厂（并发门下 = `gate.reader`）。
        读位**按尝试各取一次**，不再整条用例持位 —— 这样重试前的复位（`reset_before_retry`）
        才能在**未持读位**时拿到写位；在持读位时去要写位会死锁（`ConcurrencyGate.writer`
        等 `readers == 0`）。

        reset_before_retry（issue #3751，本包核心）：**重试前把前置复位到与首次尝试等价**。
        不传 = 不复位（用例没声明 pre_clean → 不 opt-in）。调用点是**尝试边界**：
        `run_case` → `_close_and_verify_session`（含 post_session 断言）→ **然后**才复位 →
        下一次 `run_case`。⚠️ 红线：**绝不在断言/`db_verify` 之后复位本次尝试的产物** ——
        那会把真失败洗成绿；本包测试锁死「事件序列 = reset→attempt→reset→attempt」
        （尾部出现 reset 即红）。

        前置没复位成功时（DB 不可达/asyncpg 缺失/工单不在），结果里会带
        `PRECONDITION_NOT_RESTORED` 标记（随 summary 落盘）：那种情况下第二次尝试与首次
        前置**不等价**，其红/绿**不可归因于 agent**（见 issue #3751）。
        """
        nonlocal budget_exhausted
        if case.skip_reason:
            return None
        pre_clean_msgs = list(pre_clean_msgs or [])
        # 前置**未应用/配置错误**折进结论（issue #3781）：pre_clean 是夹具层动作，跑在
        # `run_case` 之前，故这里（尝试边界）把它折成 case-level 断言失败 —— 否则
        # "数据压根没准备"只会留下一行 🧹/⚠️ 日志，用例照跑并可能判绿（假绿温床）。
        _pre_clean_bad = check_preclean_not_applied(pre_clean_msgs)
        for _b in _pre_clean_bad:
            print(f"     ⛔ 前置未应用（判该用例失败）: {_b[:200]}")
        # 前置未复位的标记（初始为空；仅当"该用例声明了 pre_clean 且复位失败"时写入）
        precondition_note = ""
        if _pre_clean_bad:
            # 复用 #3751 的标记语义（从"复位失败"扩到"前置未应用"，见 #3781）：
            # 该用例的前置不成立 ⇒ 其红/绿**不可归因于 agent**。
            precondition_note = (
                "PRECONDITION_NOT_APPLIED: 夹具层前置未生效/未应用 "
                f"（{' | '.join(_pre_clean_bad)[:200]}）—— 本次结论不可归因于 agent")
        # 运行期前置一致性断言（issue #3781）：基线在这里取（= 本函数是**尝试边界**，
        # 等价于 pre_clean 的复位语义），每次尝试各自一份；见 `_precondition_snapshot`。
        _precond_specs = list(getattr(case, "precondition", None) or [])
        _precond_base: dict = {}
        _precond_base_label = ""
        _attempt_no = 0

        # 用例起始时间戳（UTC）——用于把 CI 的**路由 dump**（ai-agent 日志，带时间戳）
        # 按用例切开。没有这个锚点，日志里连续的 intent/route 行无法归属到具体用例，
        # 「某用例被路由到哪个 Skill」就只能靠猜（实测踩到：CH-013/CH-014 交错无法分辨）。
        # ⏱ 同时记单调时钟起点（issue #3761 成本可见化）：用例读秒进 summary 的 `cost`，
        # 让"这一轮贵在哪条用例/有没有重试"可读 —— 否则"评测废钱"永远不可管理。
        _t0 = time.monotonic()
        # 窗口起点同时**落进结果**（issue #3805）：这一行此前只 print 到 job 日志，
        # 没有任何取数步骤读它 —— 失败后只能按固定行数 tail，取到的是 dump 时刻的日志。
        _started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"  ⏱ {case.id} start={_started_at}")

        # 每个用例用独立 session，避免前序用例污染上下文
        session_id = await get_or_create_session(
            token, prefer_new=True, debug_user=getattr(case, "debug_user", "") or "",
            debug_permissions=_case_debug_permissions(case))

        icon = {Difficulty.SMOKE: "🟢", Difficulty.NORMAL: "🔵",
                Difficulty.EDGE: "🟡", Difficulty.ADVERSARIAL: "🔴"}.get(case.difficulty, "⚪")

        # 数据隔离：修改类用例前后保存/恢复状态。
        # 覆盖两类被改的商品：PR-009 改「遮光窗帘」（米白色遮光窗帘），PR-010 改「2699 系列雪尼尔窗帘」。
        # 之前只快照「遮光窗帘」命中错商品，导致 PR-010 改价后未被恢复。
        snapshot_pids = []
        if any(t in case.tags for t in ["id_reuse", "update", "full_lifecycle"]):
            for kw in ("2699", "遮光窗帘"):
                pid = await snapshot_product(token, kw)
                if pid and pid not in snapshot_pids:
                    snapshot_pids.append(pid)
        # 价格复位结果（issue #3807）：失败必须进结论，不能只留一行日志
        restore_msgs: list = []

        # 注：pre_clean 已移到调度器（`_pre_clean_for_case`），因为它的独占窗口必须在
        # 用例主体**之外**获取 —— 若在持读位时再去要写位会死锁（本轮实测踩到：
        # 并行任务持 reader 又请求 writer → 互等 → 跑挂）。

        async def _attempt(sid: str):
            """一次尝试（run_case + 会话关闭/后置断言）在**同一个执行窗口**内。

            为什么两者同窗口：`_close_and_verify_session` 跑 post_session 断言（读用户级
            长期状态）—— 若它与尝试不同窗口，写共享状态的串行用例可在中间插入，
            断言读到的就不是本次尝试的产物。
            """
            nonlocal _precond_base, _precond_base_label, _attempt_no
            async with (attempt_scope() if attempt_scope else _no_concurrency_scope()):
                # ① 前置基线（issue #3781）：**在 agent 跑之前**取（这就是"基线快照
                #    必须早于被测事件"那条铁律的落点 —— 取晚了会把本次产物读成基线，
                #    与 migao-acceptance「基线快照晚于被测事件」同族）。
                #    标签按"第几次进入尝试"给（不能用 r['retried']：那是**上一次**
                #    尝试返回后打的标记，在这里是滞后值）。
                _attempt_no += 1
                if _precond_specs and not _precond_base:
                    for _src in precondition_capture_shape(_precond_specs).get(
                            "order_count_for_phone", []):
                        _n = await _probe_phone_order_count(token, _src)
                        if _n is not None:
                            _precond_base[f"order_count_for_phone:{_src}"] = _n
                    for _src in precondition_capture_shape(_precond_specs).get(
                            "product_count_for_keyword", []):
                        _n = await _probe_product_count(token, _src)
                        if _n is not None:
                            _precond_base[f"product_count_for_keyword:{_src}"] = _n
                    if _precond_base:
                        _precond_base_label = ("capture" if _attempt_no == 1
                                               else f"capture(attempt{_attempt_no})")
                _r = await run_case(case, token, sid)
                # ② 前置漂移断言（只在**首次尝试**做；重试轮的前置由 pre_clean 复位过，
                #    与首次不等价，把它算进来会把"复位"误判成"漂移"）
                if _precond_specs and _precond_base and not _r.get("retried"):
                    _after = {}
                    for _src in precondition_capture_shape(_precond_specs).get(
                            "order_count_for_phone", []):
                        _n = await _probe_phone_order_count(token, _src)
                        if _n is not None:
                            _after[f"order_count_for_phone:{_src}"] = _n
                    for _src in precondition_capture_shape(_precond_specs).get(
                            "product_count_for_keyword", []):
                        _n = await _probe_product_count(token, _src)
                        if _n is not None:
                            _after[f"product_count_for_keyword:{_src}"] = _n
                    _issues = check_precondition_drift(_precond_specs, _precond_base, _after)
                    if _issues:
                        # 前置不成立 ⇒ 本用例本次尝试的判定**不可归因于 agent**：
                        # 记成断言级失败（原文进 summary 的 failures，形态可机器分辨）。
                        for _i in _issues:
                            _r["failed"].append((_i, _CASE_LEVEL_DETAIL))
                        _r["score"] = 0.0
                        _r["precondition_check"] = " · ".join(_issues)
                        print(f"     ⚠️ {case.id} 前置断言：{_issues[0][:180]}")
                    elif _precond_base:
                        _shown = "，".join(f"{k.split(':')[1]}={v}"
                                          for k, v in _precond_base.items())
                        _r["precondition_baseline"] = f"{_precond_base_label}: {_shown}"
                # 评测会话清理（协议 §2.2）+ 关闭后置断言（issue #3357）：
                # 长时记忆候选只在会话关闭时 flush 落库（issue #2815），故 user_memories
                # 断言只能在 _end_session **之后**执行；跨会话用例取 run_case 回报的最后
                # 一个会话 id（首个会话已在换会话时关闭）。
                await _close_and_verify_session(case, token, _r, sid)
                return _r

        async def _reset_for_retry() -> None:
            """重试前的**前置复位**（attempt 边界；见 `_run_one_case` docstring 的红线）。

            没声明 `pre_clean` 的用例不 opt-in（`reset_before_retry is None`）—— 全局复位会
            伤到别的用例依赖的状态（`reset_before_retry` 由调度器按用例声明注入）。
            """
            nonlocal precondition_note
            if reset_before_retry is None:
                return
            try:
                _msgs = await reset_before_retry()
                # "没复位成功"的判据（单一处）：复位消息里带**显式失败措辞**
                # —— `_reset_aftersales_ticket` 的失败消息含「未复位」，
                # `_pre_clean_for_case` 捕获异常时给的含「失败」；成功路径只说「已复位…」。
                # ⚠️ 新增 pre_clean 类型时：**成功消息不得含「未复位」/「失败」**
                # （否则会被误判成"前置未复位" → 结论被错误地标为不可归因）。
                # #3781 扩展：语义从"复位**失败**"扩到"前置**压根没被应用**"
                # —— 配置错误（type 未知/未实现）与目标状态不存在（员工/标签查不到）时，
                # 第二次尝试的前置同样 ≠ 首次 ⇒ 结论同样不可归因于 agent。
                _ok = not any(("未复位" in str(m)) or ("失败" in str(m))
                              or str(m).startswith(_PRECLEAN_BAD_MARKERS)
                              for m in (_msgs or []))
            except Exception as e:      # 复位失败不中断评测，但必须可见
                _msgs = [f"⚠️ 重试前置复位异常: {type(e).__name__}: {e}"]
                _ok = False
            _msgs = [str(m) for m in (_msgs or [])]
            pre_clean_msgs.extend(f"重试前置复位: {m}" for m in _msgs)
            for _m in _msgs:
                print(f"     🧹 重试前置复位: {_m}")
            if not _ok:
                precondition_note = (
                    "PRECONDITION_NOT_RESTORED: 第二次尝试的前置与首次不等价 "
                    f"（{' | '.join(_msgs)[:200]}）—— 本次重试结论不可归因于 agent")

        try:
            r = await _attempt(session_id)
            # 真实 LLM 评测 flaky 容错：失败用例自动重试 1 次（新 session 隔离上下文），
            # 并按指纹分类（issue #2890）：噪声放行 + 记台账；复现型/不稳定型显式标注，
            # 禁止 rerun 掩盖确定性回归。
            classification = "pass"
            # 预算判定与占用由 _reserve_retry 原子完成（并发下不会突破预算）；
            # 短路求值保证「通过用例」不占用额度。
            if r["score"] < 1.0 and classify and not await _reserve_retry():
                # 重试预算用尽：不再重跑（标签显式标注，避免"看起来已验证两遍"）
                classification = "no-retry-budget"
            elif r["score"] < 1.0 and classify:
                r_prev = r          # 首次尝试（下面会把 r 重绑成重试结果）
                # ── 前置等价性（issue #3751）：重试前把前置复位到与首次尝试等价 ──
                # 否则第 2 次尝试的前置 = 第 1 次尝试的产物（AS-004 实证：首跑已
                # closed + closeReason 残留 ⇒ 重试 agent 合理地"不再关闭" ⇒ 必红，
                # 且与首跑成因不同 → 指纹漂移 → 旧口径误判 unstable 放行）。
                # 复位是**前置**动作，只能在这次边界（上一次尝试的断言已全部跑完）发生。
                await _reset_for_retry()
                retry_sid = await get_or_create_session(
                    token, prefer_new=True, debug_user=getattr(case, "debug_user", "") or "",
                    debug_permissions=_case_debug_permissions(case))
                r2 = await _attempt(retry_sid)
                r2["retried"] = True
                classification = _classify_attempts(r, r2)
                if classification == "llm-noise":
                    # 首次尝试的失败证据必须留痕（issue #3365）：`r = r2` 之后只打印通过
                    # 那次的轨迹，「失败→重试通过」就成了无证据的"波动" —— 实测 OR-017
                    # 连续 3 跑都是这种形态，每次都因为看不到首跑指纹而无法归因。
                    _sig1 = _failure_signature(r)
                    if _sig1:
                        print(f"     ↳ 首跑失败指纹（重试放行前留痕）: {_sig1[:300]}")
                    _ev1 = format_first_attempt_evidence(r_prev)
                    if _ev1:
                        # 逐轮证据（issue #3367）：只有指纹时知道"没调写工具"却不知道停在哪
                        for _ln in _ev1.split("\n"):
                            print(f"     ↳ {_ln}")
                    r = r2
                    # 「本用例是**被放行的波动**」这件事必须**随结果走**（issue #3781）：
                    # 放行档的语义前提是"重试**通过**"⇒ 最终 `score == 1.0`，而
                    # `completion_verdict` 断言循环的第一句就是 `score >= 1.0 → continue`
                    # ⇒ 只看结果的分类永远统计不到放行条目，`completion.flake_released`
                    # **恒为空**（假字段）。台账里 `released` 为真、结论摘要却是 `[]` ——
                    # 两处口径打架。故在**唯一**知道"首败+重试通过"的位置打这个标记。
                    r["flake_released"] = True
                    flake_ledger.append(build_flake_entry(
                        case.id, case.title, "llm-noise", r_prev, r2,
                        os.environ.get("GITHUB_RUN_ID", "local"),
                        os.environ.get("GITHUB_SHA", "")[:12]))
                else:
                    # reproducible / unstable / infra：保留第二次尝试作为失败证据
                    # ⚠️ 这里曾**只** `r = r2`（issue #3805）：首跑的逐轮轨迹/断言原文/
                    #    last_error 全被丢弃，台账里只剩一个归一指纹（如
                    #    `no_success(order_create)`）⇒ 无法回答"两次是否同因、首跑停在哪一轮"
                    #    —— 而这正是 `reproducible` 这个分类**唯一**的判别依据。
                    #    现在与 llm-noise 分支同口径：首跑证据既打印也落盘（结果 + 台账）。
                    _sig1 = _failure_signature(r_prev)
                    if _sig1:
                        print(f"     ↳ 首跑失败指纹（两次同因判定依据）: {_sig1[:300]}")
                    _ev1 = format_first_attempt_evidence(r_prev)
                    if _ev1:
                        for _ln in _ev1.split("\n"):
                            print(f"     ↳ {_ln}")
                    r = r2
                    # 首跑证据随结果/台账落盘（issue #3805）：artifact 保留期内可离线复核，
                    # 不必回头翻 90 天前的 job 日志（那里也没有——见 Diagnose 的窗口切片）。
                    r["first_attempt_signature"] = _sig1
                    if _ev1:
                        r["first_attempt_evidence"] = _ev1
                    flake_ledger.append(build_flake_entry(
                        case.id, case.title, classification, r_prev, r2,
                        os.environ.get("GITHUB_RUN_ID", "local"),
                        os.environ.get("GITHUB_SHA", "")[:12]))
            elif r["score"] < 1.0 and await _reserve_retry():
                # --no-classify 兼容模式：旧的无差别单次重试（同样受重试预算约束）
                # 前置复位与 classify 路径**同一处语义**（issue #3751）：兼容模式也不能
                # 拿"首次尝试的产物"当第二次尝试的前置。
                await _reset_for_retry()
                retry_sid = await get_or_create_session(
                    token, prefer_new=True, debug_user=getattr(case, "debug_user", "") or "",
                    debug_permissions=_case_debug_permissions(case))
                r2 = await _attempt(retry_sid)
                r2["retried"] = True
                if r2["score"] >= 1.0 or r2["score"] > r["score"]:
                    # 同 classify 路径：重试救回来的话，首跑证据必须留痕（issue #3367）
                    _ev0 = format_first_attempt_evidence(r)
                    for _ln in (_ev0.split(chr(10)) if _ev0 else []):
                        print(f"     ↳ {_ln}")
                    r = r2
            r["classification"] = classification
            # pre_clean 证据（#3511）：数据准备结果随用例落盘，归因时与能力缺陷可区分
            r["pre_clean"] = pre_clean_msgs
            # 前置未复位的机器可见标记（issue #3751）：重试前置 ≠ 首次前置时，本次重试的
            # 红/绿**不可归因于 agent**（见 PR body）。随 summary 落盘 → 结论可判。
            # 前置未应用 ⇒ 判该用例失败（issue #3781）：这是**夹具层**失败，不是 agent 行为，
            # 故原文带 `pre_clean: …` 前缀（与 `db_verify: …` / `required_args: …` 同族，
            # `_failure_signature` 可折叠成 config_error/前置族，不会与行为失败混淆）。
            if _pre_clean_bad:
                for _b in _pre_clean_bad:
                    r["failed"].append((_b, _CASE_LEVEL_DETAIL))
                r["score"] = 0.0
            if precondition_note:
                r["precondition"] = precondition_note
                print(f"     ⚠️ {precondition_note}")
            # 结果不在此处 append（并发顺序不定）——由调用方按原始用例顺序回填

            status = "✅" if r["score"] >= 1.0 else "⚠️" if r["score"] >= 0.5 else "❌"
            retry_note = "（重试后通过）" if r.get("retried") and r["score"] >= 1.0 else ""
            cls_note = {
                "llm-noise": " 🎲噪声·重试放行(已记账)",
                "reproducible": " 🔬复现型回归·禁止rerun",
                "unstable": " 🧬两次皆败·成因不同(阻塞)",
                "infra": " 🌐运行级故障",
            }.get(classification, "")
            print(f"  {icon} {status} {case.id}: {case.title[:50]}{retry_note}{cls_note}")
            print(f"     rounds={r['rounds']} tools={r['tool_calls']} score={r['score']:.0%}")
            # 逐轮轨迹：失败用例必打（归因证据），通过用例仅在详细模式打（避免日志膨胀）
            if r.get("round_trace") and (r["score"] < 1.0 or os.environ.get("AGENT_EVAL_TRACE_ALL") == "1"):
                print(f"     trace: {format_round_trace(r['round_trace'])}")
            if r["failed"]:
                for exp, detail in r["failed"][:2]:
                    print(f"     ❌ {exp[:80]}")
                    print(f"        → {detail[:120]}")
            if r["last_error"]:
                print(f"     ⚠️  last_error: {str(r['last_error'])[:100]}")
        except Exception as e:
            print(f"  {icon} ❌ {case.id}: EXCEPTION: {e}")
            exc_record = {
                "case_id": case.id, "title": case.title, "difficulty": case.difficulty.value,
                "tags": case.tags, "rounds": 0, "tool_calls": [], "round_trace": [],
                "passed": 0, "total": 0, "score": 0.0,
                "failed": [(f"EXCEPTION: {e}", "case crashed")],
                "last_error": str(e), "final_text": "", "classification": "error",
                "pre_clean": pre_clean_msgs,
                # 崩溃前若已判定"前置未复位"，标记照旧落盘（结论不可归因于 agent）
                "precondition": precondition_note,
            }
            r = exc_record   # 崩溃用例同样交给调用方回填（顺序稳定）
        finally:
            # 商品改价复位（issue #3807）：**复位失败必须可见**——旧实现发错字段名
            # （`price` vs DTO 的 `basePrice`）且不看响应，复位永远空转而日志一片安静，
            # 于是种子 ¥168 被 PR-010 改成 198 后**此后全场读 198**（顺序依赖/幽灵 delta 来源）。
            # 现在把每条复位结果（含回读校验）记账进结果，失败带 `PRECONDITION_NOT_RESTORED`
            # 标记（与 #3751/#3781 同族），由 completion_verdict 折进结论。
            for pid in snapshot_pids:
                try:
                    _restore_msg = await restore_product(token, pid)
                except Exception as _re:      # 复位崩了同样不许静默
                    _restore_msg = (f"PRECONDITION_NOT_RESTORED: 价格复位异常 "
                                    f"{type(_re).__name__}: {_re}")
                if not _restore_msg:
                    continue
                restore_msgs.append(_restore_msg)
                if _restore_msg.startswith("PRECONDITION_NOT_RESTORED"):
                    print(f"     ⛔ 前置未复位（进结论）: {_restore_msg[:200]}")
                else:
                    print(f"     🧹 {_restore_msg[:160]}")
        if isinstance(r, dict) and restore_msgs:
            r["restore"] = restore_msgs
            _not_restored = [m for m in restore_msgs
                            if str(m).startswith("PRECONDITION_NOT_RESTORED")]
            if _not_restored and not r.get("precondition"):
                # 该用例结束后**共享商品价格处于未知状态** ⇒ 它自己与后续读价用例的
                # 结论都不可靠；用既有 `precondition` 通道（#3751）把这件事写进证据。
                r["precondition"] = ("PRECONDITION_NOT_RESTORED: 商品价格复位未生效 "
                                     f"（{_not_restored[0][:160]}）—— 本用例与后续读价用例结果不可信")

        if CASE_SLEEP:
            await asyncio.sleep(CASE_SLEEP)  # rate limit（可配：EVAL_CASE_SLEEP）
        # 用例级**驻留时长**（含重试与重试前置复位；含并行道的**读位排队**；
        # 不含调度器的 pre_clean 独占窗口与串行道的写位等待）——
        # issue #3761：`cost.cases` 由它聚合而来，慢用例/重试尾巴一眼可见。
        # ⚠️ 口径（issue #3793，判定跑 34865780382 实证）：这是**从入队到结束的驻留时长**，
        # **不是**单条用例自身的执行耗时 —— 并行道的读位（`EVAL_CONCURRENCY`）在 `_t0` **之后**
        # 才获取（`attempt_scope=gate.reader`），故"排队等资源"被算进来了：该 run 里
        # `PR-015=1511.2s` ≈ 整腿 `wall_clock_s=1513.2s`，`Σcases≈72900s` 是墙钟的 ~48 倍。
        # 且两条道**口径不对称**：串行道（`_serial_task`）先取 `gate.writer()` 再进本函数
        # ⇒ 它的独占等待**不计入**。要"单条真实耗时"需另加读数（本 issue 不做）。
        r["duration_s"] = round(time.monotonic() - _t0, 1)
        _finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # 用例执行窗口（issue #3805）：**证据取数的时间锚点**。
        # `print(f"⏱ {case.id} start=…")` 那一行只活在 job 日志里、且从没有任何 workflow
        # 步骤消费它 ⇒ 失败后 dump 只能按固定行数 `--tail=N` 取，取到的全是**dump 那一刻**
        # 的日志（实测 OR-014 窗口 01:20–01:47 CST，而 ai-agent 的 tail 段起点 01:48:24 ⇒
        # 整个失败窗口的证据 0 行）。把窗口写进**artifact**（summary JSON）后，Diagnose 步骤
        # 才能按窗口切片（见 .github/scripts/eval_log_windows.sh）。
        r["finished_at"] = _finished_at
        r["started_at"] = _started_at
        return r

    # ── 并行调度（issue #3361 评测提速第二轮）──
    # 实测（run 34692977836，3 片 × 6 条）：**评测本身**随并行线性变快
    # （单 job 11.6min/18 条 → 各片 5.3/7.2/1.7min/6 条，单条吞吐不变），
    # 但"另起 job"这条路把栈启动从 3.4min 抬到 12min（并发构建/拉镜像被打爆）
    # → 分片整体反而更慢（19.8min vs 15.6min）。结论：**要并行就并行用例、别并行建栈**。
    # 故：单 job + 进程内并发（Semaphore），栈只起一次。
    #
    # 隔离规则：会写**共享资源**的用例走串行道（独占，不与任何用例重叠）——
    #   ① 标签含 id_reuse/update/full_lifecycle（商品改价类，跑前后会快照/恢复同一批商品）；
    #   ② 声明 pre_clean（评测前清理共享数据）；
    #   ③ 声明 post_session（断言的是**用户级**长期状态，运行中会写 user_memories，
    #      而所有用例共用同一个评测顾客）。
    #   ④ **命名空间撞车**（issue #3781）：两条并行用例声明了同一个全局命名空间键
    #      （同一员工名 / 同一客户手机号 / 同一商品名 / 同一分类名 / 同一加工项名）。
    # 其余用例（只读查询 / 各自新建订单工单 / 纯对话）并行安全。
    #
    # ── ④ 要解决的是什么（真实 run 34856561459 的两次独立审计共同确认）──
    # 「同栈并行用例互相写同一命名空间」——**假红的结构性来源**，与 agent 能力无关：
    #   · `HR-002` 造出第二个同名「王五」⇒ `HR-003` 目标不唯一 ⇒ 恒红（铁证，见
    #     `_eval_find_users` docstring）；
    #   · `AS-003` 跑动期间「13800138000 名下订单数还在增长」（`orders=10 total=11`
    #     → `orders=13 total=13`）⇒ 其"按手机号定位唯一目标单"的前置被并行建单的用例
    #     （OR-016 / CR-001 / CH-010 都用同一个手机号）从底下改掉，审计据此判
    #     `missing_precondition`。
    # 治法：**声明 → 自动串行**（数据隔离优先，不做全局降并发）。
    # 声明的是"我依赖/写哪个全局资源"（`EvalCase.namespaces`，key 形态 `<kind>:<值>`）；
    # 两条声明有交集的用例**自动**进串行道（独立窗口持有，见下方 gate/sem 分支）。
    # 代价是**局部的**：只有真正撞车的少数用例串行，其余（绝大多数是只读查询 /
    # 纯对话 / 各建各的数据）仍并行 —— 远比"全局降到 1 并发"（评测时长 ×并发度）便宜。
    def _ns_claims(c) -> set:
        return namespace_claims(c)

    ns_conflict = namespace_conflict_groups(cases)
    ns_conflicted_ids = {cid for ids in ns_conflict.values() for cid in ids}
    _needs_serial_lane = needs_serial_lane

    indexed = [(i, c) for i, c in enumerate(cases)]
    parallel = [(i, c) for i, c in indexed if not _needs_serial_lane(c, ns_conflicted_ids)]
    serial = [(i, c) for i, c in indexed if _needs_serial_lane(c, ns_conflicted_ids)]
    results_by_idx: dict = {}

    # 命名空间撞车的**可见性**（issue #3781）：隔离动作必须能在作业日志里读到
    # "哪两条用例因为争哪个资源而被串行化" —— 否则下一个人只看到"评测变慢了"，
    # 又会去把并发调回去（本仓库"注释漂移/静默行为"家族的形态）。
    if ns_conflict:
        _lines = "；".join(f"{k} → {'/'.join(ids)}" for k, ids in sorted(ns_conflict.items()))
        print(f"🔒 命名空间隔离（同资源争用 → 自动串行，共 {len(ns_conflict)} 组）：{_lines}")
        print(f"   争用用例 {len(ns_conflicted_ids)} 条进串行道；"
              f"全量 {len(cases)} 条中 {len(parallel)} 条仍并行"
              f"（不做全局降并发 —— 见 _needs_serial_lane docstring）")

    def _reset_for(c, g, in_writer: bool):
        """该用例**重试前**的复位回调（按用例 opt-in：没声明 `pre_clean` 就返回 None）。

        为什么按用例 opt-in（issue #3751 裁定条件 3）：复位动的是**共享数据**，全局复位会
        伤到别的用例依赖的状态；只有用例自己声明了 `pre_clean`（= 它要求一份确定的前置）
        才做。
        `in_writer=True` 表示该任务**已持写位**（串行道 / 无并发门），此时**不得**再取
        `g.writer()`（`ConcurrencyGate.writer` 等 `readers == 0` 且不重入 → 死锁）。
        """
        if not preclean_specs_for_retry(c):
            return None

        async def _again():
            if in_writer:
                return await _pre_clean_for_case(c, g)
            async with g.writer():
                return await _pre_clean_for_case(c, g)

        return _again

    gate = None
    if concurrency > 1 and parallel and serial:
        # 读写门：并行用例持读位、串行用例持写位 —— 串行用例**不必等整批跑完**
        # （否则慢串行用例变成整跑尾巴，实测白等 ~7min，见 ConcurrencyGate 注释）
        gate = ConcurrencyGate(concurrency)
        print(f"⚡ 并发执行：{len(parallel)} 条并行（并发度 {concurrency}）"
              f" + {len(serial)} 条串行（独占，读者排空即进入，不阻塞整批）")

        async def _parallel_task(i, c):
            # ① pre_clean（若有）在**独占窗口**里跑 —— 必须在读位之外获取，否则自锁
            _pc = []
            if getattr(c, "pre_clean", None):
                async with gate.writer():
                    _pc = await _pre_clean_for_case(c, gate)
            # ② 主体并行：读位**每次尝试各取一次**（attempt_scope）—— 重试前的复位需要在
            #    "未持读位"时拿写位（issue #3751；整条用例持读位时取写位会死锁）
            results_by_idx[i] = await _run_one_case(
                i, c, _pc, attempt_scope=gate.reader,
                reset_before_retry=_reset_for(c, gate, in_writer=False))

        async def _serial_task(i, c):
            # 独占用例：pre_clean 与主体在**同一个**独占窗口内（不再嵌套获取）
            async with gate.writer():
                _pc = await _pre_clean_for_case(c, gate)
                results_by_idx[i] = await _run_one_case(
                    i, c, _pc, reset_before_retry=_reset_for(c, gate, in_writer=True))

        await asyncio.gather(*[_parallel_task(i, c) for i, c in parallel],
                             *[_serial_task(i, c) for i, c in serial])
    elif concurrency > 1 and parallel:
        sem = asyncio.Semaphore(concurrency)
        print(f"⚡ 并发执行：{len(parallel)} 条并行（并发度 {concurrency}）")

        gate = ConcurrencyGate(concurrency)   # 独占窗口包 pre_clean（与重试前的复位）

        async def _bounded(i, c):
            _pc = []
            if getattr(c, "pre_clean", None):
                async with gate.writer():          # 清理动作独占（此时本任务未持读位）
                    _pc = await _pre_clean_for_case(c, gate)
            # 尝试同样走读位（issue #3751）：否则**别的用例**的重试复位（写位）会与本次
            # 尝试重叠 —— 那正是"复位动共享数据"要避免的窗口。
            async with sem:
                results_by_idx[i] = await _run_one_case(
                    i, c, _pc, attempt_scope=gate.reader,
                    reset_before_retry=_reset_for(c, gate, in_writer=False))

        await asyncio.gather(*[_bounded(i, c) for i, c in parallel])
    else:
        # 串行路径（concurrency<=1，**runner 默认值**）：pre_clean 同样必须执行！
        # 修复（#3511 归因中发现的基建缺陷）：此前该分支直接 `_run_one_case`，
        # **完全跳过 pre_clean** —— 而 EVAL_CONCURRENCY 未设时默认就是 1（旧 B 端通道
        # agent-eval.yml 正是如此）→ 商品去重/员工恢复/工单准备/客户准备等数据动作
        # 静默不执行，把"数据层失败"伪装成"能力缺陷"（B 端 80 轮里反复出现的形态）。
        # 串行无需读写门（无并发重叠），故 gate 传 None；复位回调按 in_writer=True 直调
        # （没有并发就没有"复位窗口"需要独占）。
        for i, c in indexed:
            _pc = []
            if getattr(c, "pre_clean", None):
                _pc = await _pre_clean_for_case(c, None)
            results_by_idx[i] = await _run_one_case(
                i, c, _pc, reset_before_retry=_reset_for(c, None, in_writer=True))


    # 按**原始用例顺序**回填（并发不改变报告顺序，便于与历史 run 逐条对比）
    results = [results_by_idx[i] for i in sorted(results_by_idx) if results_by_idx[i] is not None]
    passed_count = sum(1 for r in results if r["score"] >= 1.0)
    total_score = sum(r["score"] for r in results)


    # ── 跨 run 指纹复发（issue #3806）：放行政策补上"跨 run"这一维 ──
    # 顺序**必须**是「先标注（用历史）→ 再把本次并入索引」：反过来会让本次 run 自己
    # 出现在"历史"里 ⇒ 首跑指纹自己把自己判成复发（假红）。
    if flake_ledger:
        try:
            _hist_path = os.environ.get(FLAKE_HISTORY_ENV, "")
            _history = load_flake_history(_hist_path) if _hist_path else {}
            _marked = annotate_cross_run_recurrence(results, flake_ledger, _history)
            # 台账 reason 从数据生成（盲审缺陷二）：prior_count/prior_runs 必须真实写进
            # reason，prior_count>0 时禁止"未复发"措辞；历史不可得时标"数据缺失"。
            # 顺序：在台账落盘（下方 6648 附近）之前调用 —— 改的是即将写入的条目本身。
            rewrite_flake_reasons(flake_ledger, _history, bool(_hist_path))
            if _marked:
                print(f"\n🔁 跨 run 复发的系统性缺口（{len(_marked)} 条，**不按波动放行**）"
                      f"—— 同一首跑指纹在历史 run 里已出现过：")
                for _m in _marked:
                    print(f"   - {_m['case_id']} [{_m.get('classification','')}] "
                          f"priors={_m['prior_count']} fp={_m['fingerprint'][:120]}")
            elif _hist_path:
                print(f"\n🔁 跨 run 指纹索引已加载（{_hist_path}）：本次无复发指纹")
            else:
                print(f"\n🔁 未提供跨 run 指纹索引（{FLAKE_HISTORY_ENV} 为空）"
                      f"—— 本次不判复发（历史取不到不等于没有；CI 由 "
                      f".github/scripts/flake_history.py 提供）")
            _cross_case = cross_case_fingerprint_cases(_history)
            if _cross_case:
                print(f"   ℹ️ 同一指纹跨**多个用例**（信息性，不进判定）：")
                for _fp, _cases in list(_cross_case.items())[:5]:
                    print(f"      {_fp[:100]} ← {', '.join(_cases)}")
            if _hist_path:
                _updated = merge_flake_history(
                    _history, flake_ledger, os.environ.get("GITHUB_RUN_ID", "local"))
                with open(_hist_path, "w", encoding="utf-8") as _hf:
                    import json as _json3
                    _json3.dump(_updated, _hf, ensure_ascii=False, indent=1)
                print(f"   ↳ 已并入本次台账 → {_hist_path}（供后续 run 判定复发）")
        except Exception as e:
            print(f"⚠️ 跨 run 复发判定失败（非致命，退化为现状）: {e}")

    # ── flake 台账（issue #2890）：落盘 + 摘要，驱动断言收敛与高波动用例治理 ──
    if classify and flake_ledger:
        try:
            import json as _json
            ledger_path = os.environ.get("AGENT_EVAL_FLAKE_LOG", "agent-eval-flakes.json")
            _prev = []
            if os.path.exists(ledger_path):
                try:
                    import json as _json2
                    with open(ledger_path, "r", encoding="utf-8") as _f:
                        _prev = _json2.load(_f)
                except Exception:
                    _prev = []
            with open(ledger_path, "w", encoding="utf-8") as _f:
                _json.dump(_prev + flake_ledger, _f, ensure_ascii=False, indent=1)
            print(f"\n⚠️ flake 台账（{len(flake_ledger)} 条本次新增）→ {ledger_path}")
            for entry in flake_ledger:
                print(f"   - {entry['case_id']} [{entry['classification']}] {entry['reason'][:46]}")
        except Exception as e:
            print(f"⚠️ 台账写入失败（非致命）: {e}")

    # ── 运行级 infra 提示 ──
    if any(r.get("classification") == "infra" for r in results):
        print("\n🌐 检测到运行级故障（传输/超时/5xx）：整跑重试是合理操作（workflow 已自动做 1 次）；")
        print("   复现型（🔬）失败【不要】rerun——签名一致即确定性回归，直接按签名排查。")

    # Summary
    n = len(results)
    avg_score = total_score / n if n > 0 else 0
    print(f"\n{'='*60}")
    print(f"  {label} 结果: {passed_count}/{n} 通过, 均分 {avg_score:.0%}")
    print(f"{'='*60}")

    # ── 工具健康度（基础设施层优先，issue #3270）──
    # 工具大面积失败时，上面那个「均分」衡量的是**后端可用性**，不是 agent 能力。
    # 不显式说出来，读数的人一定会把它当成能力分（本项目实测踩过整整一轮）。
    health = summarize_tool_health(results)
    if health["total"]:
        print(f"\n🔧 工具健康度: {format_tool_health(health)}")
    if health["infra_suspect"]:
        print("\n" + "!" * 68)
        print(f"⚠️  工具失败率 {health['rate']:.0%} ≥ 阈值 "
              f"{_TOOL_HEALTH_INFRA_THRESHOLD:.0%} —— **本轮结果不可用于能力判断**")
        print("    这是**基础设施层**问题（后端 5xx / 熔断 / schema 缺列），不是 agent 能力。")
        print("    先修环境再谈分数：查 admin-api 日志有无 500、schema 是否缺列、熔断是否打开。")
        print("!" * 68)

    # ── 完成判定（#3483 T2）：确定性失败清零 + 关键旅程全过 + 波动台账 = 完成 ──
    journey_ids = KEY_JOURNEYS_XIAOBU if PERSONA == "xiaobu" else KEY_JOURNEYS_MIBAO
    verdict = completion_verdict(results, journey_ids)
    mark = "✅ 评测完成（可下结论）" if verdict["ok"] else "⛔ 评测未完成"
    print(f"\n{mark}：{verdict['reason']}")
    if verdict["deterministic_failures"]:
        print(f"   🔬 确定性失败（必须修）: {', '.join(verdict['deterministic_failures'])}")
    if verdict["journey_failures"]:
        print(f"   🧭 关键旅程失败（不放行）: {', '.join(verdict['journey_failures'])}")
    if verdict["flake_released"]:
        print(f"   🎲 已放行波动（flake 台账）: {', '.join(verdict['flake_released'])}")

    return results


# 工具失败率达到该比例即判定「本轮结果不可用于能力判断」——错误信息见
# summarize_tool_health 的 docstring（基础设施层优先原则）。
_TOOL_HEALTH_INFRA_THRESHOLD = 0.20


def summarize_tool_health(results: list) -> dict:
    """汇总工具调用成败，判定本轮结果**能否用于能力判断**。

    为什么必须有（issue #3270 实测踩坑，代价极大）：
    C 端验收栈的 bootstrap schema 缺列（`orders.actual_amount` / `product_skus.color_name`
    …）→ admin-api 查询 500 → 工具返回「服务暂时不可用」(CIRCUIT_OPEN) → **熔断器打开**
    → 后续同类工具全部失败。报告长成「agent 不会下单/不会建售后单」，
    于是我们去改 prompt、改工具、加引导 —— 全都在**错误的层**上忙了一天。
    真因（基础设施层）只有在加了 `data=` 载荷摘要之后才浮出水面。

    `migao-acceptance` 的五层归因（数据/断言/引导/工具/模型）里，**基础设施层必须排在最前**：
    工具本身在报错时，下面四层的结论一个都不成立。本函数把这个判断**自动化**，
    避免下次再靠人眼发现。

    Returns:
        dict: {"total", "failed", "rate", "infra_suspect", "top_failures"}
              - failed 依据 `round_trace[*].results[*].ok`（缺 success 一律记失败）
              - infra_suspect=True 表示失败率超阈值 → 结果不可用于能力判断
    """
    total = failed = 0
    counter: dict = {}
    for r in results or []:
        for rnd in (r.get("round_trace") or []):
            for res in (rnd.get("results") or []):
                total += 1
                if not res.get("ok"):
                    failed += 1
                    key = f"{res.get('tool')}!{res.get('error')}"
                    counter[key] = counter.get(key, 0) + 1
    rate = (failed / total) if total else 0.0
    top = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return {
        "total": total,
        "failed": failed,
        "rate": round(rate, 4),
        "infra_suspect": bool(total) and rate >= _TOOL_HEALTH_INFRA_THRESHOLD,
        "top_failures": [{"failure": k, "count": v} for k, v in top],
    }


def format_tool_health(health: dict) -> str:
    """把工具健康度压成可读多行文本（CI 日志用）。"""
    lines = [
        f"工具调用 {health['total']} 次，失败 {health['failed']} 次"
        f"（{health['rate']:.0%}）"
    ]
    for item in health.get("top_failures") or []:
        lines.append(f"    · {item['failure']} × {item['count']}")
    return "\n".join(lines)


def _ci_verdict(results: list) -> tuple[bool, str]:
    """CI 判定（2026-09-08 假绿修复，issue #3062）：空结果 / 存在未通过 → 失败。

    背景：登录失败时 run_suite 曾返回 [] → main 判"全部通过"退出 0 → CI 假绿
    （0 用例执行却报 PASS）。零执行 = 环境/登录失败，必须显式失败。
    """
    if not results:
        return False, "0 个用例执行（疑似登录/环境失败，禁止假绿）"
    failed = [r for r in results if r.get("score", 0) < 1.0]
    if failed:
        return False, f"{len(failed)}/{len(results)} 个用例未通过"
    return True, "全部用例通过"


# ── 完成判定（#3483 T2「完成定义前置」）──
# 关键旅程 = P0 跨域核心链路：用户真会走的路，任何一条失败都不放行（即使分类 llm-noise）。
# mibao 旅程多为双端用例（B 端全量会跑）；xiaobu 旅程为 C 端专属。
# 新增旅程必须在此登记（completion_verdict 的存在性守卫在测试里锁定）。
KEY_JOURNEYS_MIBAO = (
    "OR-016", "PR-019", "PR-020", "AS-007", "FN-004",
    "HR-003", "DA-002", "CU-003", "CT-002",
)
KEY_JOURNEYS_XIAOBU = (
    "OR-012", "CH-010", "OR-017", "KN-001", "CH-008", "CH-024",
)

# 放行档（**门禁口径**，与"分类"分离）：**只有**「首次失败、新 session 重试通过」
# 才是可放行的 LLM 波动 —— 一次都没通过时没有"波动"证据，只有"这个用例当下不工作"。
#
# ⚠️ 口径变更（待裁定，见 PR）：`unstable`（两次皆败、**成因不同**）自本次起**不再放行**。
# 它只证明"两次失败不是同一件事"，**没有**证明"其中有一次是对的"；实证 OR-014
# （run 34841029062，台账 `unstable`）：一次"下单成功但金额错 168≠198"，一次
# "order_create 从未被调用" —— 2/2 都真失败，按"LLM 发散可放行"处置站不住。
# 影响面（离线重放 5 个真实 run 的 summary/flakes）：1 条历史结论翻转
# （run 34849029334 xiaobu `completion.ok` true→false，来自 OR-026）。
_COMPLETION_RELEASED_CLASSES = frozenset({"llm-noise"})


def completion_verdict(results: list, key_journey_ids: tuple = ()) -> dict:
    """评测完成判定（机器可读）——「完成定义前置」，取代「全量 100% 绿才算完」。

    旧闭环（B 端 80 轮差距分析实证）：全量复测是唯一判据，最后 5-10% 是 LLM 方差，
    追 100% 边际收益为负（三测自述「逐个校准 case 追波动边际收益递减」）。
    本判定把「可不可以下结论」变成可判定的谓词：
      - **必须处理的失败（阻塞）**：除 `llm-noise` 外的一切 score<1 ——
        reproducible / unstable / error / no-retry-budget / infra / 无分类证据。
        `unstable`（两次皆败但成因不同）**曾与 `llm-noise` 一并放行**，现改为阻塞：
        两次都没通过就没有"波动"证据（实证 OR-014：2/2 真失败，成因还不同）；
      - **关键旅程失败**（key_journey_ids 中 score<1）= P0 旅程不过 → 未完成
        （波动也不放行）；
      - **放行**：`llm-noise`（首次失败、新 session 重试通过，runner 已记入 flake 台账）
        —— 但放行口径自 #3806 起收紧为「**随机**波动」：同一 `(用例, 首跑指纹)` 在历史
        run 里出现过（`r["cross_run_recurrence"]`）⇒ **不属随机 ⇒ 不放行**，进
        `systemic_recurrence`（跨 run 复发的系统性缺口）。这是**有意的 fail-closed**：
        它会让更多用例变红，正是本单要的效果（PR-016 首跑 0/3 通过却因"重试碰巧过"被
        放行了三次）。**fail-closed 对关键旅程里的放行条目同样生效**（盲审缺陷一）：
        旅程守卫（`cid not in journey_set`）只挡"失败旅程不许当波动放行"，**不**挡
        "复发条目必须进 systemic"—— 判定循环里 `_is_recurring` 先于旅程守卫检查
        （实测 run 34916256903：OR-016 因旅程身份逃出所有桶，与本段判据冲突）。
      - **前置未复位**（#3807）：`restore` 里带 `PRECONDITION_NOT_RESTORED` 的用例 ⇒
        共享商品价格处于未知状态 ⇒ 独立进 `restore_failures` 并阻塞（与本用例 score 无关）。

    ⚠️ **放行条目为什么不能只看 `score<1`**（issue #3781，真实 run 34856561459 实证）：
    放行档的语义前提就是"重试**通过**" ⇒ 该用例的最终 `score == 1.0`。旧实现的断言
    序是「`score >= 1.0 → continue`」在前、「分类命中放行档 → 记入 `flake_released`」在后
    ⇒ **放行条目永远走不到那一句**，`completion.flake_released` 结构上**恒为 `[]`**
    （该 run：mibao `classes = pass 67 / reproducible 5 / llm-noise 6`、
    xiaobu 亦有 1 条 llm-noise，而两条腿的 `flake_released` 都是 `[]`）。
    这是**报告口径**的 bug，与放行政策无关（政策仍是 `_COMPLETION_RELEASED_CLASSES`，
    只放行 `llm-noise`，一次都没通过的一律阻塞）。

    故放行条目改为**两类来源取并集**（都指向同一件事，不会造出"没通过却放行"的新路径）：
      ① `r["flake_released"] is True` —— 真实链路里 `run_case` 在"首败 + 重试通过"
         那一刻打的标记（放行条目 `score==1.0`，走的就是这条）；
      ② `score<1` 且分类命中放行档 —— 保留旧行为，兼容离线重放 / 手工构造的 results
         （`_r("AS-007", 0.0, "llm-noise")` 这类夹具形态）。
    关键旅程的优先级不变（旅程失败连 `llm-noise` 也不放行）。

    判定不改 _ci_verdict：PR 门禁（smoke/normal 全绿）与结论档（本判定）各司其职。

    Returns:
        {"ok", "reason", "deterministic_failures", "journey_failures",
         "flake_released", "systemic_recurrence", "restore_failures", "total", "passed"}
    """
    if not results:
        return {"ok": False, "reason": "0 个用例执行（环境/登录失败，禁止假绿）",
                "deterministic_failures": [], "journey_failures": [],
                "flake_released": [], "systemic_recurrence": [], "restore_failures": [],
                "harness_incompatible_failures": [], "total": 0, "passed": 0}
    journey_set = set(key_journey_ids or ())
    deterministic, journey_fail, flake_released = [], [], []
    systemic, restore_fail, harness_bad = [], [], []

    def _is_recurring(r) -> bool:
        return bool(r.get("cross_run_recurrence"))

    for r in results:
        cid = str(r.get("case_id") or "?")
        # 前置未复位（#3807）：与本用例 score 无关 —— 它污染的是**共享资源**（商品价格），
        # 影响的是后续用例；不独立成桶的话"复位空转"永远只是一行日志。
        if any("PRECONDITION_NOT_RESTORED" in str(m) for m in (r.get("restore") or [])):
            restore_fail.append(cid)
        # harness/用例形状不兼容（#3803）：判红照旧阻塞，但**归因单列** ——
        # 不进 `deterministic_failures`（那是"agent/产品的确定性回归"清单）。
        if r.get("harness_incompatible"):
            harness_bad.append(cid)
        if r.get("score", 0) >= 1.0:
            # 重试通过的放行条目（score==1.0）在这里被捞出来——见 docstring 的 #3781 说明
            # ⚠️ 跨 run 复发**必须先于**旅程守卫判定（fail-closed 第一，盲审缺陷一）：
            # 旧断言序「flake_released and cid not in journey_set」让**关键旅程里**的
            # 放行条目（如 OR-016 ∈ KEY_JOURNEYS_MIBAO）把 `_is_recurring` 短路掉 ⇒
            # 复发条目从**所有桶**里消失（既不在 systemic 也不在 flake_released）
            # = 静默放行（实测 run 34916256903：PP-001 拦下、同构的 OR-016 放行）。
            # 判据（§16.7 结论构成）：凡 `cross_run_recurrence.prior_count>0` 且指纹同型
            # ⇒ 一律进 systemic，不因"本轮通过/旅程身份/分类 llm-noise"而放行。
            if _is_recurring(r):
                systemic.append(cid)
            elif r.get("flake_released") and cid not in journey_set:
                flake_released.append(cid)
            continue
        # ⚠️ score<1.0 的**失败路径**同样必须先判复发（盲审缺陷二，判定跑
        # 34923425338 实证）：OR-014 带 `cross_run_recurrence {prior_runs:
        # [34916256903], prior_count: 1}`，旧代码此处不查 `_is_recurring` ⇒
        # 分类 reproducible 走下方 `deterministic` 分支 ⇒ `systemic_recurrence`
        # 恒漏报该条（本轮因 det 已阻塞而无害，但构成口径不合）。判据与通过
        # 路径同一句：凡 `prior_count>0` 且指纹同型 ⇒ 一律进 systemic，
        # 不因"本轮失败/旅程身份/分类非放行"而改桶。
        if _is_recurring(r):
            systemic.append(cid)
        elif cid in journey_set:
            journey_fail.append(cid)
        elif str(r.get("classification") or "") in _COMPLETION_RELEASED_CLASSES:
            flake_released.append(cid)
        elif cid in harness_bad:
            pass          # 已单列，不重复计入"必须处理的失败"
        else:
            deterministic.append(cid)
    ok = (not deterministic and not journey_fail and not systemic
          and not restore_fail and not harness_bad)
    total = len(results)
    passed = sum(1 for r in results if r.get("score", 0) >= 1.0)
    if ok:
        parts = ["必须处理的失败=0，关键旅程全过"]
        if flake_released:
            parts.append(f"放行波动 {len(flake_released)} 条（台账，仅随机波动）")
        reason = "，".join(parts) + f"（{total} 条，{passed} 通过）"
    else:
        parts = []
        if deterministic:
            parts.append(f"必须处理的失败 {len(deterministic)} 条: {', '.join(deterministic)}")
        if journey_fail:
            parts.append(f"关键旅程失败 {len(journey_fail)} 条: {', '.join(journey_fail)}")
        if systemic:
            parts.append(f"跨 run 复发的系统性缺口 {len(systemic)} 条"
                         f"（同一首跑指纹在历史 run 反复出现，不按波动放行）: {', '.join(systemic)}")
        if restore_fail:
            parts.append(f"前置未复位 {len(restore_fail)} 条"
                         f"（共享状态未回滚，结论不可信）: {', '.join(restore_fail)}")
        if harness_bad:
            parts.append(f"harness/用例形状不兼容 {len(harness_bad)} 条"
                         f"（**不是** agent 行为失败，需改用例/harness）: {', '.join(harness_bad)}")
        reason = "；".join(parts)
    return {
        "ok": ok, "reason": reason,
        "deterministic_failures": deterministic,
        "journey_failures": journey_fail,
        "flake_released": flake_released,
        "systemic_recurrence": systemic,
        "restore_failures": restore_fail,
        "harness_incompatible_failures": harness_bad,
        "total": total, "passed": passed,
    }


# `case_issues` 折进 `failed_expectations` 时用的固定 detail（见 `run_case`）。它在 summary
# 里是纯噪音（断言原文已自带 `output_verify[...]` / `required_args:` 前缀），故序列化时不带上。
# 与那处字面量若将来漂移，代价仅是 summary 里多一句 detail —— 不影响任何判定。
_CASE_LEVEL_DETAIL = "case-level check"


def _failure_texts(result: dict) -> list:
    """用例的逐条失败原因（**断言级原文**，issue #3708「失败可归因」层）。

    为什么需要（实测代价，run 34841029062）：结论档 `eval-summary-*.json` 此前只有
    `id/score/classification/pre_clean` ⇒ `score=0` **无从定位** —— 把"确定性失败 6 条"
    分类成"真回归 / 用例缺陷 / 种子环境"只能手工挖 2705 行作业日志；而 CI 日志有保留期，
    **过期后这批失败就永久失去可归因性**。原因串 runner 本来就在构造
    （`failed_expectations` = expectations 逐条 + `case_issues` 折成的 case-level 条目），
    这里只是把它**序列化出去**（`migao-acceptance` v1.2 治法 3 / §16.2 完成定义）。

    为什么取 `failed` 而不是只取 `case_issues`：`score<1.0` ⇔ 本列表非空
    （`run_case` 里每条失败的 expectation 都 append，`case_issues` 同样折进来并在有值时
    把 score 置 0）；只取 `case_issues` 会让"期望不匹配"型失败仍只剩一个 `score=0`。
    反向同样成立 ⇒ **通过用例天然是空列表**，不产生噪音。
    """
    out = []
    for item in (result.get("failed") or []):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            exp, detail = str(item[0]), str(item[1] or "")
        else:                       # 容错：非 (断言, 详情) 二元组的形态照样可读
            exp, detail = str(item), ""
        out.append(f"{exp} → {detail}" if detail and detail != _CASE_LEVEL_DETAIL else exp)
    return out


# ── 通过用例的断言证据（盲审缺陷三：绿的不可审计性）────────────────────────────
# 病灶：summary 里通过用例只有 id/score/classification/pre_clean —— 空断言假绿天然
# **不可见**（#3778 族 + `migao-acceptance`「证据层假绿」：绿了 ≠ 断言真测过）。
# 本组函数给通过用例也落证据（最便宜、不改变判定），并把「假绿候选」单列标记。

# 效果层字段（与 `.github/assertion_taxonomy.py` 的 `EFFECT_FIELDS` 同源子集）：
# 本函数族只评估在 `_run_one_case` 里执行的这四层；`post_session` 在会话关闭后
# 单独评估，不在此列。口径一致性由 taxonomy 模块的既有锁定测试兜底。
_EFFECT_LAYER_FIELDS = ("must_succeed", "db_verify", "amount_verify", "output_verify")


def _scoring_check_is_failable(check: object) -> bool:
    """该计分断言是否**机器可证伪**（= 真可失败）；存在性/散文 = 不可失败（假绿候选）。

    判据与 `.github/assertion_taxonomy.py` 同口径（行为层 vs 裸工具名）：
      · 可失败：反向断言（未被调用/not called）、显式预期错误（error.code=）、
        效果层计分（success=true）、带 args 的 tool(k=v) 值校验、direct_reply（无工具）；
      · 不可失败（存在性/散文）：裸工具名子串匹配（如 `order_query`）等 ——
        runner 的 `check_expectation` 对纯工具名只做「出现过」的匹配（#3778：调用了≠成了）。
    """
    s = str(check or "")
    low = s.strip().lower()
    if "未被调用" in s or "not called" in low:
        return True
    if "error.code=" in low or "success=true" in low:
        return True
    if "direct_reply" in low:
        return True
    if "(" in s and ")" in s:      # tool(k=v) 形态：参数值校验，可证伪
        return True
    return False


def _assertions_fired_summary(case, scoring_checks: list, results: list, score: float) -> dict:
    """每条用例的**断言证据摘要**：哪些计分断言命中、是否可失败、效果层是否真触发。

    在 `_run_one_case` 里计算（吃 case 对象与当轮 results），随结果序列化进 summary。
    通过路径（score>=1.0 ⇒ 所有 case 级检查零 issue）下，声明过的效果层字段即
    「真触发且通过」；失败路径保守标记 False（不冒充「触发过」）。
    """
    fired = []
    for exp in scoring_checks:
        passed = any(check_expectation(r, exp)[0] for r in results)
        fired.append({"check": str(exp)[:120], "failable": _scoring_check_is_failable(exp),
                      "passed": passed})
    effect = {}
    for f in _EFFECT_LAYER_FIELDS:
        declared = bool(getattr(case, f, None))
        effect[f] = bool(declared) if score >= 1.0 else False
    return {"scoring": fired, "effect_layers": effect}


def _unfailable_green(score: float, scoring_checks: list, assertions_fired: dict,
                      has_order_before: bool = False) -> bool:
    """通过用例的**假绿候选**标记（与 verdict 分开单列，**不改 ok**）。

    判据：score>=1.0 且没有任何「可失败支撑」——
      ① 计分断言全为存在性/散文（或无任何计分断言 ⇒ score=1.0 纯构造）；
      ② 效果层（must_succeed/db_verify/amount_verify/output_verify）均未真触发。
    其余 case 级字段（forbidden_text/required_args/want_text/…）**不计**支撑
    （同 taxonomy：required_args 不算行为层证据、forbidden_text 不得单独承载、
    裸工具名期望也不算行为层证据）。

    ⚠️ `has_order_before` **已弃用，判据不再读它**（盲审判据「同 profile 必同
    标记」，判定跑 34923425338 实证）：`order_before` 时序断言**不进**
    `assertions_fired` profile ⇒ 若它参与标记，同一 profile（OR-010/OR-015/
    PG-013 逐字段相同）会得到不同标记 —— OR-015/PG-013 声明了 `order_before`
    即漏标（`if has_order_before: return False` 分支）。标记因此**只读 profile**
    （scoring 可失败性 + 效果层触发）。参数保留仅为兼容既有调用、并让红证夹具
    直陈该漏标机制；taxonomy 把 `order_before` 判为行为层，服务的是
    `forbidden_text` 禁令规则（不得单独承载）那个问题，与本标记是两回事。
    """
    if score < 1.0:
        return False
    if any(_scoring_check_is_failable(c) for c in scoring_checks):
        return False
    if any((assertions_fired.get("effect_layers") or {}).values()):
        return False
    return True


def _summary_case(result: dict, failures: list) -> dict:
    """单个用例的 summary 条目（issue #3708）。

    `failures` **只在真有失败时带上**：一个 shard 里几十条通过用例各挂一个 `"failures": []`
    就是纯刷屏噪音，而缺省语义与空数组等价（`jq` 侧 `(.failures // [])` 即可）。
    既有字段（`id/score/classification/pre_clean`）一件不少、顺序不变。

    `precondition`（issue #3751）：重试前置**未复位**时的机器可读标记
    （`PRECONDITION_NOT_RESTORED: …`）—— 缺省不带该键（同 failures 的理由）。
    该情形下第二次尝试的前置与首次不等价 ⇒ **本次结论不可归因于 agent**，
    判定/归因脚本据此把该用例排除在"行为回归"之外。
    """
    entry = {"id": result.get("case_id"), "score": result.get("score", 0),
             "classification": result.get("classification", ""),
             # pre_clean 证据（#3511）：机器可读，供归因区分"数据准备没生效"与"能力缺陷"
             "pre_clean": result.get("pre_clean") or []}
    # 用例执行窗口（issue #3805）：**证据取数的时间锚点**。写进 artifact 之后，
    # Diagnose 步骤才能按窗口切片抓容器日志（而不是固定 `--tail=N`，那个取到的是
    # dump 时刻的日志、整个失败窗口一行都没有）。
    for _k in ("started_at", "finished_at"):
        if result.get(_k):
            entry[_k] = result[_k]
    if result.get("precondition"):
        entry["precondition"] = result["precondition"]
    # 首跑证据（issue #3805）：reproducible/unstable/infra 分支曾只留归一指纹 ⇒
    # "两次是否同因、首跑停在哪一轮"不可得。现在逐轮摘要随 artifact 落盘。
    if result.get("first_attempt_signature"):
        entry["first_attempt_signature"] = result["first_attempt_signature"]
    if result.get("first_attempt_evidence"):
        entry["first_attempt_evidence"] = result["first_attempt_evidence"]
    # 商品价格复位结果（issue #3807）：复位是否真的生效必须可逐条核对，
    # 而不是"日志里静悄悄 = 复位成功"。
    if result.get("restore"):
        entry["restore"] = result["restore"]
    # harness/用例形状不兼容（issue #3803）：随 artifact 落盘，归因可机器分辨
    # （"用例/卡形状对不上"与"agent 没做"必须能分开，否则红会一直指错人）。
    if result.get("harness_incompatible"):
        entry["harness_incompatible"] = result["harness_incompatible"]
    # 跨 run 复发（issue #3806）：条目标注 —— 顶层 `completion.systemic_recurrence`
    # 给出 ID 列表，这里给出该条的指纹与历史 run，让"为什么不放行"可逐条核对。
    if result.get("cross_run_recurrence"):
        entry["cross_run_recurrence"] = result["cross_run_recurrence"]
    # 前置基线读数（issue #3781）：把"运行前该手机号名下有多少单"这一行**写进证据**，
    # 否则"前置是否成立"又一次只能靠猜 —— 那正是本次两次审计在同一份证据上判分歧的根因。
    if result.get("precondition_baseline"):
        entry["precondition_baseline"] = result["precondition_baseline"]
    if result.get("precondition_check"):
        entry["precondition_check"] = result["precondition_check"]
    # 放行波动标记（issue #3781）：条目级留痕 —— 顶层 `completion.flake_released` 给出
    # ID 列表，这里给出"该 ID 的最终 score/分类是什么"，让"为什么放行"可逐条核对
    # （缺省不带该键，同 failures：通过用例不刷屏，只有真放行的少数条目才带）。
    if result.get("flake_released"):
        entry["flake_released"] = True
    # 盲审缺陷三：通过用例的**断言证据**（计分断言命中/可失败性 + 效果层触发）与
    # 假绿候选标记。只有 `_run_one_case` 真实产出的结果才带（缺省不带该键 ——
    # 合成夹具/旧形态结果保持逐字节不变，见 test_eval_summary_attribution 的回归锚点）。
    if result.get("assertions_fired"):
        entry["assertions_fired"] = result["assertions_fired"]
    if result.get("unfailable_green"):
        entry["unfailable_green"] = True
    if failures:
        entry["failures"] = failures
    return entry


def _cost_block(results: list, elapsed_s: float) -> dict:
    """本轮评测的**成本可读信号**（issue #3761）—— "废钱"只有可读才可管理。

    为什么加（实证）：取消/失败轮拿到的是一条 ID 列表，没人知道"这轮贵在哪条用例、
    有没有重试尾巴、总共跑了多久"——于是成本决策只能靠感觉。本块把这些变成机器可读。

    字段（全部来自本轮**实测**，不估算、不编造）：
      wall_clock_s   本轮 runner 墙钟秒数（由 main 计时；测试/单跑未注入时为 null）
      cases          {用例 ID: **驻留**秒数}（含重试、重试前置复位、**并行道读位排队**；
                     不含 `pre_clean` 独占窗口与串行道写位等待；由 `_run_one_case` 记）
      avg_case_s     每条用例平均**驻留**秒数（无用例时为 null）
      slowest_cases  驻留最久的 3 条 [(ID, 秒)]，降序 —— 成本归因的入口
      retried_cases  发生过重试的用例 ID（重试 = 成本翻倍的直接来源）
      tokens         **恒为 null**：本 runner 只经 HTTP/SSE 调 ai-agent-service，
                     token 用量产生在**服务内部**（服务侧才有 LLM 客户端），runner 侧拿不到
      tokens_note    为什么是 null（不编数字）

    ⚠️ **读法（口径，issue #3793）**：`cases`/`avg_case_s`/`slowest_cases` 是**驻留时长**
    （入队 → 结束），**不是单条用例的执行耗时** —— 并行道（`EVAL_CONCURRENCY`）的读位在
    `_t0` 之后才获取 ⇒ **排队等资源的时间被计入**；且两条道不对称（串行道先取写位再计时，
    故它的独占等待不计入）。判据（判定跑 `34865780382`，B 端 mibao）：`slowest_cases` 首条
    `PR-015=1511.2s` ≈ `wall_clock_s=1513.2s`，`Σcases≈72900s` ≈ 墙钟的 48 倍，
    而同 run 里串行的 `HR-002=13.7s` / `PR-005=14.8s` 是小值 —— 即"最慢榜"实际是
    "**排队最久**榜"，把它读成"这条用例自身最慢/最贵"会误判成本归因。
    **要单条真实耗时需另加读数（本 issue 不改判定逻辑、也不加字段）。**
    """
    cases = {str(r.get("case_id") or "?"): r.get("duration_s") for r in results
             if r.get("duration_s") is not None}
    ordered = sorted(cases.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "wall_clock_s": round(elapsed_s, 1) if elapsed_s else None,
        "cases": cases,
        "avg_case_s": round(sum(cases.values()) / len(cases), 1) if cases else None,
        "slowest_cases": [[cid, secs] for cid, secs in ordered[:3]],
        "retried_cases": [str(r.get("case_id") or "?") for r in results if r.get("retried")],
        # 拿不到就是拿不到：`tokens` 恒 null，且把"为什么"写在旁边，避免下一个人
        # 把 null 当成"这轮零 token"（那正是 migao-acceptance 说的"编数字"）。
        "tokens": None,
        "tokens_note": "runner 只经 HTTP/SSE 调 ai-agent-service，LLM token 用量产生于服务内部，"
                       "runner 侧不可得（未编造）",
    }


def _git_cases_fingerprint() -> str:
    """`.github/cases` 在**本次 checkout 的 SHA** 上的 tree hash（issue #3769）。

    为什么用 git tree hash 而不是"解析 YAML 再哈希"：用例库是仓库文件，tree hash 天然是
    **内容指纹**（改一个用例就变），零依赖、两侧（runner / 派发侧守卫）用同一条命令即得同一值，
    不存在"两份解析实现漂移"的风险。取不到（浅克隆缺对象 / 非 git 环境）⇒ 返回空串，
    派发侧据此**拒绝复用**（宁可多跑一次，不可复用过期结论）。
    """
    import subprocess
    rev = os.environ.get("GITHUB_SHA") or "HEAD"
    try:
        out = subprocess.run(["git", "rev-parse", f"{rev}:.github/cases"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _run_key(results: list, label: str) -> dict:
    """verdict ledger 的键（issue #3769）——「同一件事不重复跑」的机器判据。

    用户裁定（本轮）：判定用途的评测只走**全库**跑；同一 SHA 已有结论就不许再跑。
    键 = (sha, tier, case_ids 收窄输入, 用例库指纹, 跑批策略版本, persona)：

      · `case_ids` **非空 ⇒ 键必然不同** —— 收窄跑是"定点复现/调试"，**不是**判定结论，
        不能顶替全库结论（既有教训：`--case-ids` 收窄后 summary 的 total 只反映那几条，
        拿它下"全量结论"就是假绿）；
      · `cases_fingerprint` = 用例库 tree hash（用例改了就换键）；
      · `policy_version` = 放行口径/分类/指纹实现的源码哈希（见 `eval_policy_version.py`）——
        策略变了旧结论不再等价。

    ⚠️ 只加字段：既有键一个不动（summary 的契约测试锁死）。
    """
    try:
        from eval_policy_version import policy_version
        _pv = policy_version()
    except Exception:
        _pv = "unknown"
    import hashlib
    ids = ",".join(sorted(str(r.get("case_id") or "?") for r in results))
    return {
        "sha": os.environ.get("GITHUB_SHA", "") or "local",
        "tier": label,
        # 收窄输入（本进程实际使用的 --case-ids；空串 = 全库跑 = 判定用途）
        "case_ids": os.environ.get("EVAL_CASE_IDS_INPUT", ""),
        "cases_fingerprint": _git_cases_fingerprint(),
        "executed_ids_fingerprint": hashlib.sha256(ids.encode()).hexdigest()[:16],
        "executed_count": len(results),
        "policy_version": _pv,
        "persona": PERSONA,
        # 用途（#3769 用户裁定）：determination = 判定用途（必须全库跑）；
        # debug = 定点复现/调试（**不构成判定结论**）。遥测据此把"真跑"与
        # "定点小跑"分开计数（同一个 total 数字在两处的含义完全不同）。
        "run_mode": os.environ.get("EVAL_PURPOSE", "determination"),
    }


def _evidence_window(results: list) -> dict:
    """本轮**证据窗口**（issue #3805）：全部用例里最早的 `started_at` → 最晚的 `finished_at`。

    为什么要落进 summary：容器日志的取数一直用固定 `--tail=N`（取到的是 **dump 那一刻**
    的日志），而 runner 的 `⏱ <case> start=` 锚点**从没有任何步骤消费** ⇒ 失败用例的
    执行窗口整段不可得（实测 OR-014 窗口 01:20–01:47 CST，ai-agent 的 tail 段起点 01:48:24）。
    `docker logs --since/--until` 直接吃 RFC3339 时间戳，故把窗口写进 artifact 后
    Diagnose 步骤即可切片（见 `.github/scripts/eval_log_windows.sh`）。

    时间串格式恒为 `YYYY-MM-DDTHH:MM:SS+00:00`（同长度、同时区）⇒ 字典序即时间序，
    `min`/`max` 可直接用（不需要解析，避免跨平台 date 差异）。缺乏窗口时返回 `{}`
    （调用方据此回落固定 tail，而不是造一个假窗口）。
    """
    starts = [str(r.get("started_at")) for r in (results or []) if r.get("started_at")]
    ends = [str(r.get("finished_at")) for r in (results or []) if r.get("finished_at")]
    if not starts or not ends:
        return {}
    return {"since": min(starts), "until": max(ends)}


def write_summary_json(path: str, label: str, shard: str, results: list,
                       elapsed_s: float = None) -> None:
    """写机器可读的本次运行汇总（issue #3361 分片基建）。

    为什么需要：分片后每个 job 只跑一部分用例，后续步骤（DB 审计、假绿告警）若按
    "全局应有 N 条订单"判断就会误报 —— 审计必须知道**本片是否真的跑了写用例**。
    顺带让"本次跑了什么、结果如何"可被脚本消费（报告/看板/回归对比），不必解析日志。

    **失败可归因（issue #3708）**：判红时"哪些用例 + 为什么"必须能从这份文件直接读全，
    不再依赖作业日志（日志有保留期）。故**失败用例**条目带 `failures`（断言级原文；
    通过用例不加这个键，不给几十条 `[]` 刷屏），`completion` 附加 `failure_reasons`
    （ID → 首要原因）。**纯序列化**：既有字段、`completion_verdict` 的算法与 `reason`
    原文一字未动（否则与历史 run 的对比失效）。

    字段：
      label/shard/total/passed/failed/avg_score
      order_write_cases：本片声明 must_succeed: order_create 的用例数（0 → 审计不该告警）
      write_cases_ok：其中通过的条数（通过却没落库 = 真假绿）
      cases：[{id, score, classification, pre_clean}]（+ 失败用例的 `failures`：断言级原因数组）
              （+ 重试前置未复位时的 `precondition`：#3751）
      completion：completion_verdict 的判定结果 + failure_reasons（ID → 首要原因）
      cost：本轮**成本可读信号**（#3761，见 `_cost_block`：wall_clock_s / cases / avg_case_s /
            slowest_cases / retried_cases / tokens=null+原因）—— **只加不改**既有字段
      run_key：verdict ledger 的键（#3769，见 `_run_key`：sha/tier/case_ids/cases_fingerprint/
               policy_version/persona）—— 同一键已有结论就不重复跑（**只加不改**）
    """
    import json as _json
    def _declares_order_write(r) -> bool:
        # build_round_trace/结果里不保留 case 声明，故用"该用例的工具列表含 order_create"近似
        return "order_create" in (r.get("tool_calls") or [])
    # 每条用例的失败原因（断言级原文）：用例条目与顶层 failure_reasons 共用，只算一次
    _reasons = {str(r.get("case_id") or "?"): _failure_texts(r) for r in results}
    payload = {
        "label": label,
        "shard": shard or "",
        # 本轮**证据窗口**（issue #3805）：容器的 `docker logs --since/--until` 直接吃
        # RFC3339 时间戳。取全部用例的最小起点 → 这样"整轮评测期间"的容器日志都能按
        # 时间取回，不再依赖固定行数 tail（`--tail=100` 实测只覆盖 dump 前 3 秒的
        # ai-agent 日志，而失败用例的窗口早已过去）。
        "evidence_window": _evidence_window(results),
        "total": len(results),
        "passed": sum(1 for r in results if r.get("score", 0) >= 1.0),
        "failed": sum(1 for r in results if r.get("score", 0) < 1.0),
        "avg_score": (sum(r.get("score", 0) for r in results) / len(results)) if results else 0.0,
        "order_write_cases": sum(1 for r in results if _declares_order_write(r)),
        "write_cases_ok": sum(1 for r in results
                              if _declares_order_write(r) and r.get("score", 0) >= 1.0),
        "cases": [_summary_case(r, _reasons[str(r.get("case_id") or "?")]) for r in results],
        "completion": completion_verdict(
            results, KEY_JOURNEYS_XIAOBU if PERSONA == "xiaobu" else KEY_JOURNEYS_MIBAO),
    }
    # 顶层判定**只加不改**（#3708）：`completion_verdict` 的算法/`reason` 原文一字未动
    # （与历史 run 的对比必须仍成立），只**附加** `ID → 首要原因` 映射，让"哪些用例 + 为什么"
    # 一次读全（完整原因列表在各用例条目的 `failures`；放行波动也列出，否则"为什么放行"缺证据）。
    _verdict = payload["completion"]
    _verdict["failure_reasons"] = {
        cid: (_reasons.get(cid) or [""])[0]
        for cid in (_verdict["deterministic_failures"] + _verdict["journey_failures"]
                    + _verdict["flake_released"])
    }
    # 成本块（#3761）：**只加**顶层键（既有字段/键顺序一字未动 —— 消费者
    # `report` job 的 jq 与 `TestLegacyBytesUnchanged` 都依赖这一点）。
    payload["cost"] = _cost_block(results, elapsed_s)
    # verdict ledger 的键（#3769）：同一 SHA 已有结论 ⇒ 派发侧据此拒绝重复跑。
    payload["run_key"] = _run_key(results, label)
    try:
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)
        _cost = payload["cost"]
        print(f"📊 运行汇总 → {path}（total={payload['total']} passed={payload['passed']} "
              f"order_write_cases={payload['order_write_cases']}）")
        print(f"💰 本轮成本：wall_clock={_cost['wall_clock_s']}s "
              f"avg_case={_cost['avg_case_s']}s 重试用例={len(_cost['retried_cases'])} 条 "
              f"最慢={_cost['slowest_cases'][:3]}")
    except Exception as e:
        print(f"⚠️ 汇总写出失败（非致命）: {e}")


@asynccontextmanager
async def _no_concurrency_scope():
    """一次尝试的**空执行窗口**（串行道 / 无并发门时的默认值）。

    存在意义（issue #3751）：尝试窗口在并发门下是 `ConcurrencyGate.reader`（按尝试各取
    一次读位），串行道/无门时无需任何占位 —— 用同一个调用形态（`async with scope()`）
    让 `_run_one_case` 不必分叉，避免"两条路各写一份尝试逻辑"的漂移。
    """
    yield


class ConcurrencyGate:
    """用例并发门（读写语义，issue #3361 提速第二轮）。

    为什么需要：串行道（共享资源用例）如果**等整批并行用例跑完**才开始，慢用例就变成
    整跑的尾巴 —— 实测 C 端 normal：16 条并行（并发度 3）只花 ~3min，而串行道的
    OR-014（含 pre_clean + 重试）一个人在末尾又跑了 ~7min，整段评测 10.6min 白等。

    语义：
      - `reader()`：并行用例（只读/各自新建数据）持位，最多 `max_readers` 个同时进行；
      - `writer()`：串行用例（写共享资源/断言用户级状态）独占 —— **既不与其它用例重叠，
        也不等整批跑完**（当前读者排空即进入）；
      - 写者优先（`_waiting_writers`）：串行用例一到，新读者排队，避免慢串行用例被
        源源不断的并行用例饿死。

    这是"隔离"与"墙钟"同时满足的关键：隔离要求本就是"不与其他用例重叠"，
    而不是"必须在最后跑"。
    """

    def __init__(self, max_readers: int):
        self._max_readers = max(1, int(max_readers))
        self._cond = asyncio.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @asynccontextmanager
    async def reader(self):
        async with self._cond:
            while self._writer or self._waiting_writers or self._readers >= self._max_readers:
                await self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            async with self._cond:
                self._readers -= 1
                self._cond.notify_all()

    @asynccontextmanager
    async def writer(self):
        async with self._cond:
            self._waiting_writers += 1
            try:
                while self._writer or self._readers > 0:
                    await self._cond.wait()
                self._writer = True
            finally:
                self._waiting_writers -= 1
        try:
            yield
        finally:
            async with self._cond:
                self._writer = False
                self._cond.notify_all()


def shard_cases(cases: list, shard: str) -> list:
    """按 `--shard I/N` 切分用例（issue #3361 评测提速）。

    为什么按"用例"分片而不是把并发塞进 runner：评测用例共享同一个 DB（同一批 fixture、
    同一个 debug 顾客），进程内并发会让「谁先写订单/改商品价」变成不确定 ——
    评测工具的可信度建立在**可复现**上，不能为省时间拿掉它。
    分片是**语义不变**的加速：每片跑的是同一套 runner、同一套用例，只是各自一套
    DB/栈（CI 每个 job 自带 docker 栈）→ 天然隔离，墙钟时间近似除以 N。

    切法：`cases[i::N]` 轮转分配（用例耗时未知，轮转比"前 1/N 条"更均衡 ——
    实测慢用例（403s 的 OR-014）与快用例交错分布，顺序切会把慢用例堆在一片）。

    Args:
        cases: 已按 persona/tier 过滤后的用例列表
        shard: "I/N" 形态（I 从 0 开始）；空/None/非法 → 不切片（返回原列表）

    Returns:
        该分片应跑的用例
    """
    if not shard:
        return list(cases)
    try:
        part, total = str(shard).split("/", 1)
        idx, n = int(part), int(total)
    except (ValueError, AttributeError):
        print(f"⚠️ --shard={shard!r} 非法（应为 I/N，如 0/3），忽略分片")
        return list(cases)
    if n <= 1:
        return list(cases)
    if idx < 0 or idx >= n:
        raise ValueError(f"--shard 索引越界: {shard}（I 必须在 [0, {n - 1}]）")
    return list(cases)[idx::n]


def load_cases_from_yaml(cases_dir: str) -> list:
    """从 cases/*.yml 加载用例（case-contract 单一源，替代 eval_cases.py 手写清单）。

    cases_dir 相对仓根（CI 形态: .github/cases）；yaml_light + render_cases 在 .github/ 下。
    """
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / ".github"))
    from render_cases import exp_to_str, load_case_dicts

    cases = []
    for c in load_case_dicts(cases_dir):
        cases.append(EvalCase(
            id=c.get("id", ""),
            legacy_id=c.get("legacy_id", ""),
            title=c.get("title", ""),
            skill=Skill.GENERAL,  # 域信息由 _domain 携带，runner 不消费 skill
            difficulty=Difficulty(c.get("tier", "normal")),
            user_inputs=c.get("user_inputs") or [],
            expectations=[exp_to_str(e) for e in (c.get("expectations") or [])],
            data_checks=c.get("data_checks") or [],
            skip_reason=c.get("skip_reason", ""),
            tags=c.get("tags") or [],
            persona=c.get("persona", ""),
            # 多身份评测（issue #3391）：**CI 走的是这条 YAML 装载路径**（--cases .github/cases），
            # 漏映射 = 用例仍以 debug_customer_1 跑 = 新客路径假绿（首版即踩：渲染器映射了、
            # 装载器漏了，单测只覆盖渲染器 → CI 全绿但订单全挂在 debug_customer_1 名下）。
            debug_user=c.get("debug_user", ""),
            # 评测可控权限（issue #4108）：**必须在这里映射** —— CI 走的是本 YAML 装载路径
            # （`--cases .github/cases`），不是生成物 `eval_cases.py`；漏映射 = 用例声明了
            # 受限权限却仍以通配跑 ⇒ 越权用例**静默退化成普通成功用例**（#3391/#3417 同款假绿，
            # 由 test_acceptance_case_checks 的 PROBES 逐字段守住）。
            debug_permissions=c.get("debug_permissions", ""),
            order_before=c.get("order_before") or [],
            forbidden_text=c.get("forbidden_text") or [],
            want_text=c.get("want_text") or [],
            forbidden_tools=c.get("forbidden_tools") or [],
            required_args=c.get("required_args") or [],
            forbidden_args=c.get("forbidden_args") or [],
            must_succeed=c.get("must_succeed") or [],
            must_fail=c.get("must_fail") or [],
            amount_verify=c.get("amount_verify") or [],
            db_verify=c.get("db_verify") or [],
            # 产出侧断言（issue #3367）。**这里曾经漏映射**（issue #3417 复盘）：
            # check_output_verify 有调用点、生成物 EvalCase 有字段、单测也覆盖了生成物，
            # 但 CI 走的是本函数 → PR-024「算料产出对不对」在 CI 上**从未执行过**
            # （生成物路径有效，所以本地/审查都看不出来）→ 又一例"声称查过而其实没查"。
            # 现由 test_loader_maps_every_assertion_field 按**词汇表**逐字段守住。
            output_verify=c.get("output_verify") or [],
            form_prefill=c.get("form_prefill") or [],
            forbidden_card_text=c.get("forbidden_card_text") or [],
            pre_clean=c.get("pre_clean") or [],
            post_session=c.get("post_session") or [],
            # 并行污染隔离 + 运行期前置断言（issue #3781）。**必须在这里映射**：
            # CI 走的是本装载路径（`--cases .github/cases`），不是生成物 `eval_cases.py`
            # —— 漏映射 = `namespaces` 恒为空 ⇒ 隔离静默失效（而 `precondition` 恒为空
            # ⇒ 前置断言静默不跑），两条都会**静默退化成"什么都没做"**（#3391/#3417 同款
            # 教训：渲染器映射了、装载器漏了，单测只覆盖生成物 → CI 全绿但机制没生效）。
            # `tests/test_acceptance_case_checks.py::TestAssertionVocabularyIsMappedByLoader`
            # 按词汇表逐字段守住这一格。
            namespaces=c.get("namespaces") or [],
            precondition=c.get("precondition") or [],
            # 用例级表单载荷（issue #3804）：CI 走的是本 YAML 装载路径（`--cases .github/cases`），
            # 而**不是**生成物 `eval_cases.py` —— 漏映射 = 用例声明了没人消费 = 载荷窗口
            # 仍绑死在某些轮次（"声称修了而其实没修"，与 `debug_user`/`output_verify`/
            # `namespaces` 四次同款假绿）。由
            # `tests/test_acceptance_case_checks.py::TestAssertionVocabularyIsMappedByLoader`
            # 的 PROBES 逐字段守住（新增字段不配 probe 直接红）。
            auto_fill=c.get("auto_fill") or {},
        ))
    return cases


async def main():
    import argparse
    # 本轮墙钟起点（issue #3761 成本可见化）：从进程进入 main 到写汇总，含栈外的一切
    # runner 侧耗时（用例执行 + 重试 + 重试前置复位）；**不含**栈构建与 seed（那是 workflow
    # 步骤，成本由 run 的墙钟体现）。
    _run_t0 = time.monotonic()
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=["smoke", "normal", "full", "adversarial", "case"], nargs="?", default="smoke")
    parser.add_argument("--case-id", help="单条用例 ID（支持新 ID 与 legacy_id，如 OR-002 或 O002）")
    parser.add_argument("--case-ids", default="",
                        help="逗号分隔的用例 ID 列表（**迭代提速用**）：只跑这些用例，"
                             "可在任意 tier 上叠加（如 `normal --case-ids OR-019,OR-024`）。"
                             "为什么需要：全档 30 条 ≈ 11 分钟真实 LLM；改动只需复验几条时，"
                             "这是把「下结论前的整档」与「改一行看一眼」分开的关键（issue #3417）")
    parser.add_argument("--cases", help="用例库目录（cases/*.yml）——提供时直接读 YAML（单一源）")
    parser.add_argument("--concurrency", type=int,
                        default=int(os.environ.get("EVAL_CONCURRENCY", "1")),
                        help="用例级并发度（默认 1=串行）。单 job 内并发：栈只起一次；"
                             "实测评测吞吐随并发线性提升，而「多 job 分片」会被并发建栈拖慢。")
    parser.add_argument("--max-retries", type=int, default=None,
                        help="整跑重试次数上限（默认不限）；失败多的跑可设 3 省分钟数，"
                             "超限的失败用例标 no-retry-budget 而非静默")
    parser.add_argument("--shard", default="",
                        help="分片运行 I/N（如 0/3）——CI 用多 job 并行切片，语义不变只减墙钟")
    parser.add_argument("--no-classify", action="store_true",
                        help="关闭波动分类（issue #2890 兼容开关：恢复旧的无差别单次重试，调试用）")
    args = parser.parse_args()

    if args.cases:
        cases = load_cases_from_yaml(args.cases)
        print(f"📚 用例源: {args.cases}（{len(cases)} 条，YAML 单一源）")
    else:
        cases = ALL_CASES
        print(f"📚 用例源: eval_cases.py（生成物，{len(cases)} 条）")

    # persona 归属 + C 端工具集过滤（issue #2855 / #3266）
    # mibao：跳过 C 端专属（xiaobu）用例
    # xiaobu：#2855 persona 过滤 + #3266 工具集过滤（双端用例须其断言工具全在
    #         小布能力内；B 端管理用例——断言的工具小布没有——一律排除，
    #         防「跑在错误 Agent 上还计分」的假绿）
    before = len(cases)
    cases = select_cases_for_persona(cases, PERSONA)
    if len(cases) != before:
        print(f"🧪 Persona={PERSONA}：用例集过滤后 {len(cases)}/{before} 条"
              f"（排除 {before - len(cases)} 条另一端专属/超出本端工具能力）")

    if PERSONA == "xiaobu":
        # 空集 = 评测静默假绿（issue #3062 同源）——显式报错而非退出 0
        if not cases:
            print("❌ C 端用例集为空（persona/工具集过滤后无剩余）——"
                  "禁止假绿，请检查 .github/cases/ 的 persona 声明与 C 端工具集")
            sys.exit(1)
        print(f"🧪 Persona=xiaobu：C 端用例 {len(cases)} 条")

    def smoke_cases():
        return [c for c in cases if c.difficulty == Difficulty.SMOKE and not c.skip_reason]

    def normal_cases():
        # 每日回归：normal tier（smoke 由 PR gate 跑，adversarial 由每周任务跑）
        return [c for c in cases if c.difficulty == Difficulty.NORMAL and not c.skip_reason]

    def adversarial_cases():
        return [c for c in cases if c.difficulty == Difficulty.ADVERSARIAL and not c.skip_reason]

    def active_cases():
        return [c for c in cases if not c.skip_reason]

    # 迭代提速（issue #3417）：--case-ids 只保留指定用例（与 tier/shard 正交）
    if (args.case_ids or "").strip():
        _picked, _missing = filter_cases_by_ids(cases, args.case_ids)
        if _missing:
            print(f"❌ --case-ids 里有无法解析的用例 ID: {_missing}（禁止静默少跑）")
            sys.exit(1)
        print(f"🎯 --case-ids 收窄：{len(cases)} → {len(_picked)} 条（{args.case_ids}）")
        # 记进 env 供 run_key 使用（#3769：收窄跑 ⇒ 键必然不同 ⇒ 不构成判定结论）
        os.environ["EVAL_CASE_IDS_INPUT"] = args.case_ids
        cases = _picked

    # 分片（issue #3361 评测提速）：在 tier 选择之后切片 —— 保证「每片都只跑自己那份」，
    # 且空片显式报错（0 用例 = 该片白跑，属配置错误，不做静默假绿，同 _ci_verdict 语义）
    if args.shard:
        before_shard = {
            "smoke": smoke_cases, "normal": normal_cases,
            "adversarial": adversarial_cases, "full": active_cases,
        }
        if args.suite in before_shard:
            total_before = len(before_shard[args.suite]())
            sharded = shard_cases(before_shard[args.suite](), args.shard)
            print(f"🧩 分片 {args.shard}：本片 {len(sharded)}/{total_before} 条")
            if not sharded:
                print(f"❌ 分片 {args.shard} 为空（{args.suite} 档共 {total_before} 条）"
                      "—— 空片会静默假绿，请检查分片数与用例数")
                sys.exit(1)
            cases = sharded

    try:
        if args.suite == "case":
            case = next((c for c in cases
                         if c.id == args.case_id or getattr(c, "legacy_id", "") == args.case_id), None)
            if not case:
                print(f"用例 {args.case_id} 不存在")
                sys.exit(1)
            results = await run_suite([case], f"单条 {args.case_id}", classify=not args.no_classify)
        elif args.suite == "smoke":
            results = await run_suite(smoke_cases(), "冒烟", classify=not args.no_classify,
                                      retry_budget=args.max_retries,
                                      concurrency=args.concurrency)
        elif args.suite == "normal":
            results = await run_suite(normal_cases(), "每日回归（normal）",
                                      retry_budget=args.max_retries,
                                      concurrency=args.concurrency)
        elif args.suite == "adversarial":
            results = await run_suite(adversarial_cases(), "对抗")
        elif args.suite == "full":
            results = await run_suite(active_cases(), "全量")
        else:
            results = []
    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # CI 判定（issue #3062 假绿修复）：空结果/未通过 → exit 1
    ok, msg = _ci_verdict(results)
    print(f"\n{'✅' if ok else '❌'} {msg}")

    # 机器可读汇总（分片审计/报告消费；env 未设则跳过）
    _sum_path = os.environ.get("AGENT_EVAL_SUMMARY_JSON")
    if _sum_path:
        write_summary_json(_sum_path, args.suite, args.shard, results,
                           elapsed_s=time.monotonic() - _run_t0)

    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    asyncio.run(main())
