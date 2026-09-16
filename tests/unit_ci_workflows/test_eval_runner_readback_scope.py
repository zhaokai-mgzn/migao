# case_ids: AS-007, PR-019
"""落库核对器的**取值口径**：认得出真实 payload 形状 + 按"本次写的那条记录"回读（issue #3689）。

两处缺口的共同形态：**核对器认不出真实 payload 形状** → 用例要么照抄即**永久假红**，
要么写着"有覆盖"实际核对的是**另一条记录**（假绿）。两组红证分别锁住：

| 缺口 | 真实形状（file:line 已核） | 旧行为 | 红证 |
|---|---|---|---|
| ② `after_sales_ticket` 只认 `ticket_id`/`ticketId` | create 路径 payload 键是 **`id`**（`app/tools/after_sales_manage.py:359` 用 `data.get("id")`、`:369` 原样返回 `AfterSalesDetailResponse`；`AfterSalesDetailResponse.java:16-17,24` 有 `id`/`ticketNo`/`status`、**无 `ticket_id`**） | `create -> (None, {})` → AS-007 的 `db_verify` 一加就**恒红**（"找不到成功调用，判失败而非跳过"） | 合成 create payload → 必须取到引用 |
| ③ `db_verify[product_by_name]` 只按 keyword 取**首条** | 本次 create 返回 `data={"product_id":…}`（`app/tools/product_manage.py:245`）；PR-019 的商品名与种子 `prod_eval_2699` 同名同价（`fixtures/mibao_eval_seed.sql:30`） | 种子恒在 ⇒ **不管本次 create 成没成功都绿**（假绿）；`_fetch_product_configs`（`:1905`）拿不到本次新建的 id | 声明 `source` 后必须按**本次新建的 id** 回读 |

口径与已修好的同族能力**同源**（复用而非另写一套）：`_first_successful_payload`（`:3044`）
的 action 对齐 + `db_verify[processing_order]`（`:3270-3309`）的"回读键取自成功 payload，
取不到就判失败而非跳过"。

**fail-closed 是硬要求**：声明了 `source` 却找不到成功写调用 / payload 里没有回读键
→ **判红**（"断言未评估也是一种失败"），不许静默回退到 keyword 首条（那正是假绿本身）。
未声明 `source` 时**一字不改**地保持既有 keyword 语义（存量 PR-020 等不回退）。

⚠️ 本目录跑在 CI 的 `ci workflow helper unit tests` job（只装 pytest+pyyaml），
而 `local_runner` 有模块级 `import httpx` → 用下方 `_load_runner()` 的最小替身。
"""
import asyncio
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身，且一旦被调用即抛错）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()

PRODUCT_NAME = "2699系列雪尼尔窗帘面料"
CREATED_PRODUCT_ID = "prod_new_2699"      # 本次 create 返回的 id
SEED_PRODUCT_ID = "prod_eval_2699"        # 种子里的同名单（fixtures/mibao_eval_seed.sql:30）


def _round(rnd, calls, results):
    """构造一轮 `results` 条目（calls: [(tool, args)]，results: [(tool, success, data)]）。"""
    return {
        "__round": rnd,
        "tool_calls": [{"name": t, "args": a} for t, a in calls],
        "tool_results": [
            {"tool": t, "result": {"success": ok, "data": d}} for t, ok, d in results
        ],
    }


def _create_ticket_round(rnd=1, status="pending", ok=True):
    """`after_sales_manage(action=create)` 的真实回显形状（键是 `id`，不是 `ticket_id`）。"""
    data = {"id": "tkt_uuid_1", "ticketNo": "AS-20260915-9001", "ticketType": "exchange",
            "status": status, "orderId": "ord_1"} if ok else {}
    return _round(rnd, [("after_sales_manage", {"action": "create", "ticket_type": "exchange"})],
                  [("after_sales_manage", ok, data)])


# ── ② after_sales_ticket：create 路径 payload 键是 `id` ─────────────────────────

class TestTicketPayloadShapeRecognition:
    """工单引用的取值口径 —— create（`id`）与 update（`ticket_id`）两条路径都要认。"""

    def test_create_payload_id_is_recognized(self):
        """**红证（假红面）**：create 的真实 payload 带 `id`/`ticketNo`/`status`。

        旧实现只认 `ticket_id`/`ticketId` → 返回 `(None, {})` → AS-007 的
        `db_verify: [{fetch: after_sales_ticket, expect_status: pending}]` 一加就报
        「找不到成功调用（判失败而非跳过）」= **永久假红**（用例资产包实测探针 `create -> (None, {})`）。
        """
        rnd, data = lr._first_successful_ticket_payload(
            [_create_ticket_round()], "after_sales_manage", "pending")
        assert rnd == 1, (rnd, data)
        assert data.get("id") == "tkt_uuid_1"
        assert data.get("ticketNo") == "AS-20260915-9001"

    def test_update_payload_ticket_id_still_recognized(self):
        """向后兼容锚点：update 路径（`{ticket_id, status}`）语义一字不改（AS-004 依赖）。"""
        r = _round(3, [("after_sales_manage", {"action": "update_status"})],
                   [("after_sales_manage", True, {"ticket_id": "tkt_1", "status": "closed"})])
        rnd, data = lr._first_successful_ticket_payload([r], "after_sales_manage", "closed")
        assert rnd == 3 and data.get("ticket_id") == "tkt_1"

    def test_payload_with_bare_id_and_no_ticket_marker_is_not_a_ticket(self):
        """**假绿防线**：只有 `id` 但没有工单特征键的载荷**不得**被当成工单。

        `list` 载荷是 `{items,total,page,size}`（`after_sales_manage.py:238`）——若将来出现
        「带 id 的非工单载荷」，只认 `id` 会把核对指向一个根本不是工单的对象（"核对了错的调用"）。
        """
        r = _round(1, [("after_sales_manage", {"action": "list"})],
                   [("after_sales_manage", True, {"id": "not-a-ticket", "items": [], "total": 0})])
        assert lr._first_successful_ticket_payload([r], "after_sales_manage", "") == (None, {})

    def test_expect_status_filter_still_applies_to_create_payload(self):
        """状态过滤对新形态同样生效：create 落在 processing、期望 pending → 不选它。"""
        assert lr._first_successful_ticket_payload(
            [_create_ticket_round(status="processing")], "after_sales_manage", "pending") == (None, {})
        rnd, _ = lr._first_successful_ticket_payload(
            [_create_ticket_round(status="processing")], "after_sales_manage", "processing")
        assert rnd == 1

    def test_failed_create_payload_is_ignored(self):
        """失败的 create（`success=false`）不算证据 —— 与既有口径一致。"""
        assert lr._first_successful_ticket_payload(
            [_create_ticket_round(ok=False)], "after_sales_manage", "pending") == (None, {})


class TestDbVerifyAfterSalesTicketCreatePath:
    """`check_db_verify[after_sales_ticket]` 端到端（admin-api 用桩函数替身）。"""

    def _run(self, db_verify, results, detail):
        async def _fake(token, ref):
            return detail
        orig = lr._fetch_ticket_detail
        lr._fetch_ticket_detail = _fake
        try:
            return asyncio.run(lr.check_db_verify("tok", db_verify, results))
        finally:
            lr._fetch_ticket_detail = orig

    SPEC = [{"fetch": "after_sales_ticket", "source": "after_sales_manage",
             "expect_status": "pending"}]

    def test_create_then_persisted_pending_is_green(self):
        """AS-007 回填后的目标形态：create 成功 + 落库 status=pending → 绿。

        这是**真绿**：核对的是本次 create 返回的那张工单（不再是"找不到引用"的假红）。
        """
        assert self._run(self.SPEC, [_create_ticket_round()], {"status": "pending"}) == []

    def test_persisted_status_mismatch_is_red(self):
        """**红证**：create 回显成功但落库状态不是 pending（工具回显 ≠ 落库成功）→ 报红。"""
        issues = self._run(self.SPEC, [_create_ticket_round()], {"status": "processing"})
        assert len(issues) == 1 and "落库状态" in issues[0]

    def test_no_successful_create_is_red_not_skipped(self):
        """**红证（fail-closed）**：没有成功的 create → 判失败而非跳过（无工单可核对）。"""
        issues = self._run(self.SPEC, [_create_ticket_round(ok=False)], {"status": "pending"})
        assert len(issues) == 1 and "找不到" in issues[0] and "成功调用" in issues[0]

    def test_ticket_detail_missing_is_red(self):
        """**红证**：工单查不到（未落库）→ 报红，不许当通过。"""
        issues = self._run(self.SPEC, [_create_ticket_round()], None)
        assert len(issues) == 1 and "查不到详情" in issues[0]


# ── ③ db_verify[product_by_name]：按「本次成功 create 的 product_id」回读 ────────

class TestProductReadbackById:
    """声明 `source` 后，回读键必须取自**本次成功写调用**的 payload，而不是 keyword 首条。"""

    def _run(self, db_verify, results, fetcher):
        async def _fake(token, name="", product_id=""):
            return await fetcher(name, product_id)
        orig = lr._fetch_product_configs
        lr._fetch_product_configs = _fake
        try:
            return asyncio.run(lr.check_db_verify("tok", db_verify, results))
        finally:
            lr._fetch_product_configs = orig

    def _create_round(self):
        return _round(2, [("product_manage", {"action": "create", "name": PRODUCT_NAME})],
                      [("product_manage", True,
                        {"product_id": CREATED_PRODUCT_ID, "name": PRODUCT_NAME})])

    def test_source_declared_reads_back_by_created_product_id(self):
        """**红证（假绿面）**：必须按本次 create 的 `product_id` 回读，而不是 keyword 首条。

        桩函数模拟真实库：按 keyword 查到的是**种子**商品（finalPrice=30，同名同价），
        按 id 查到的才是**本次新建**（finalPrice=45）。断言 `==45`：
          · 读过 id → 绿（证明核对的是本次新建那条）；
          · 只按 keyword 首条 → 30 ≠ 45 → 红（旧行为正是这条：种子恒在 ⇒ 假绿）。
        """
        seen = {}

        async def _fetcher(name, product_id):
            seen["name"], seen["product_id"] = name, product_id
            if product_id == CREATED_PRODUCT_ID:
                return [{"processingItemName": "刺绣工艺", "finalPrice": 45}]
            return [{"processingItemName": "刺绣工艺", "finalPrice": 30}]   # 种子 prod_eval_2699

        issues = self._run([{"fetch": "product_by_name", "source": "product_manage",
                             "action": "create", "name": PRODUCT_NAME,
                             "checks": ["processingItemConfigs.刺绣工艺.finalPrice==45"]}],
                           [self._create_round()], _fetcher)
        assert issues == [], issues
        assert seen.get("product_id") == CREATED_PRODUCT_ID, seen

    def test_source_declared_without_successful_create_is_red_not_skipped(self):
        """**红证（fail-closed）**：create 没成功 → 报红，不许回退 keyword（回退即假绿）。"""
        async def _fetcher(name, product_id):
            raise AssertionError("没有成功写调用时不得发起回读")

        issues = self._run([{"fetch": "product_by_name", "source": "product_manage",
                             "action": "create", "name": PRODUCT_NAME,
                             "checks": ["processingItemConfigs.all.finalPrice>0"]}],
                           [_round(2, [("product_manage", {"action": "create"})],
                                   [("product_manage", False, {"error": "被门禁拦下"})])],
                           _fetcher)
        assert len(issues) == 1 and "成功调用" in issues[0]

    def test_source_declared_but_payload_lacks_product_id_is_red(self):
        """**红证（fail-closed）**：成功 payload 里没有 `product_id` → 报红（无从定位落库记录）。"""
        async def _fetcher(name, product_id):
            raise AssertionError("无回读键时不得发起回读")

        issues = self._run([{"fetch": "product_by_name", "source": "product_manage",
                             "action": "create", "name": PRODUCT_NAME,
                             "checks": ["processingItemConfigs.all.finalPrice>0"]}],
                           [_round(2, [("product_manage", {"action": "create"})],
                                   [("product_manage", True, {"name": PRODUCT_NAME})])],
                           _fetcher)
        assert len(issues) == 1 and "product_id" in issues[0]

    def test_legacy_path_keeps_two_positional_call_shape(self):
        """**兼容锚点（红证式）**：未声明 `source` 时对 fetcher 的调用形态必须保持
        `(token, name)` **两个位置参数**（不多传 `product_id`）。

        为什么必须锁：存量测试替身（`backend/ai-agent-service/tests/test_acceptance_case_checks.py`
        的 `fake_fetch(token, name)`）按这个签名桩 —— 多传一个 keyword 会让它抛
        `TypeError`，而 `run_case` 把异常记成 db_verify 失败 ⇒ **合规用例被误判 0 分（假红）**，
        报错信息还只是 "db_verify 执行失败: unexpected keyword argument"（本次实测踩到：
        `TestRunCaseDbVerify::test_db_verify_pass_keeps_score` 变红）。
        """
        calls = []

        async def _strict(token, name):          # 与存量替身**同签名**（不接受 product_id）
            calls.append((token, name))
            return [{"processingItemName": "刺绣工艺", "finalPrice": 45}]

        orig = lr._fetch_product_configs
        lr._fetch_product_configs = _strict
        try:
            issues = asyncio.run(lr.check_db_verify(
                "tok", [{"fetch": "product_by_name", "name": "盯防加工项价格0908",
                         "checks": ["processingItemConfigs.刺绣工艺.finalPrice==45"]}], []))
        finally:
            lr._fetch_product_configs = orig
        assert issues == [], issues
        assert calls == [("tok", "盯防加工项价格0908")], calls

    def test_without_source_keeps_legacy_keyword_semantics(self):
        """向后兼容锚点：未声明 `source` → 既有 keyword 语义一字不改（存量 PR-020 不回退）。"""
        seen = {}

        async def _fetcher(name, product_id):
            seen["name"], seen["product_id"] = name, product_id
            return [{"processingItemName": "刺绣工艺", "finalPrice": 45}]

        issues = self._run([{"fetch": "product_by_name", "name": "盯防加工项价格0908",
                             "checks": ["processingItemConfigs.刺绣工艺.finalPrice==45"]}],
                           [], _fetcher)
        assert issues == [], issues
        assert seen == {"name": "盯防加工项价格0908", "product_id": ""}, seen

    def test_legacy_missing_name_is_still_a_config_error(self):
        """向后兼容锚点：既无 `source` 也无 `name` → 仍是配置错误（不空转通过）。"""
        async def _fetcher(name, product_id):
            raise AssertionError("缺 name 时不得发起回读")

        issues = self._run([{"fetch": "product_by_name", "checks": ["processingItemConfigs.all.finalPrice>0"]}],
                           [], _fetcher)
        assert len(issues) == 1 and "name" in issues[0]

    def test_source_without_action_scopes_to_that_tool(self):
        """不声明 `action` 时按工具取首个成功 payload（与 `_first_successful_payload` 同源）。"""
        seen = {}

        async def _fetcher(name, product_id):
            seen["product_id"] = product_id
            return [{"processingItemName": "刺绣工艺", "finalPrice": 45}]

        issues = self._run([{"fetch": "product_by_name", "source": "product_manage",
                             "name": PRODUCT_NAME,
                             "checks": ["processingItemConfigs.all.finalPrice>0"]}],
                           [self._create_round()], _fetcher)
        assert issues == [] and seen.get("product_id") == CREATED_PRODUCT_ID
