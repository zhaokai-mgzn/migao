# case_ids: PR-009, PR-010, PR-021
"""改价护栏的两处残余闭环（issue #5317，涉钱面）。

## 两条残余（#5303 / PR #5311 交付方主动登记，#5317 收口）

1. **`before_price` 是模型声明，未做服务端回查** —— 护栏证明的是「**模型声称**改前是多少」，
   不是「**服务端确认**改前是多少」。口径照抄 #5314 的批次核对：`oldValue` 与 DB 当前值
   **按值核对**（数字不比字符串写法），不符即拒绝。
2. **纯文本确认放行改价** —— `base_skill._is_explicit_confirmation` 放行「确认」类短文本
   ⇒ 该路径下**无法证明确认卡已发出**（护栏只证明"确认过"，不证明"看过什么"）。
   裁定（issue #5317 评论，2026-09-24）：**涉钱面（改价）必须走 `confirmValue` 卡值**。

## 本文件的判据（每条都有能单独变红的红证，见 `TestRedProofs`）

- **判据 A（②）** 带价格事实的改价调用：文本「确认」**不得**放行门禁 —— 放行只能来自
  `_is_card_confirm_value`（用户消息逐字等于系统自产的卡值 = 真的点了卡）。
- **判据 B（②·动作面）** 参数里看不出钱的动作（批量 `execute` / `revert`，价格事实在批次行里）
  由工具**声明**入面（`card_only_actions`）：同样只认卡值。
- **判据 C（①）** 改前价必须**随请求下发**才能被服务端回查 —— 工具 payload 带 `beforePrice`
  （商品级）/ `before_price`（SKU 级）。判据 D 锁死"下发了就会被核对"。
- **判据 D（①·口径同源）** 单条与批次的价格核对是**同一实现**
  （`AgentWriteValues.sameValue`）：静态不变式 —— 两处调用点都必须引用它，
  且 `sameValue` 在 admin-api main 源码里只有**一处定义**。
- **判据 E（类级元守卫）** 注册表**现取**：任何声明了 `before_price` 参数的写工具，
  其带价格事实的调用都必须只认卡值 —— 新改价工具落地即自动进面（不靠人记得改清单）。
- **判据 F** 非改价写（改名 / 上下架 / 回补库存开关）**不得**被误伤（文本确认照旧放行）。

## 不属本判据（如实登记，不写成恒真判断凑数）

- 服务端**行为**判据（不符 ⇒ 422 且零写）在 Java 侧：
  `backend/admin-api/src/test/java/com/migao/admin/service/AgentPriceTruthRecheckTest.java`；
  本文件只锁**同一实现**这一条机械不变式（跨语言，Python 侧静态可判）。
- LLM 是否**真的**先查再改、商家是否**真的**点了卡 ⇒ 属真实评测（`migao-dev-flow` §13
  默认不跑）。
"""

import re
from pathlib import Path

import pytest

from app.graph.skills import base_skill
from app.graph.skills.base_skill import (
    _card_only_confirmation,
    _is_card_confirm_value,
    _requires_confirmation,
)
from app.graph.skills.product_skill import PRODUCT_SYSTEM_PROMPT
from app.tools.confirm_value import confirm_card_fields, confirm_value_for_fields
from app.tools.product_update import ProductUpdateTool
from app.tools.registry import get_tool_registry
from app.tools.sku_update import SkuUpdateTool

#: 改价的典型参数（#5303 的预览契约：改后价 + 改前价成对）
PRICE_ARGS = {"product_id": "遮光窗帘", "price": 199, "before_price": 168}
SKU_PRICE_ARGS = {"product_id": "遮光窗帘", "price": 150, "before_price": 168,
                  "color": "米白", "door_width": "2.8"}

REPO = Path(__file__).resolve().parents[3]
MAIN_JAVA = REPO / "backend/admin-api/src/main/java/com/migao/admin"


def _code_lines(path: Path) -> list[str]:
    """源码里**去掉注释**的行（静态不变式只看代码，防止判据被自己的文案喂绿）。"""
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("//", 1)[0]
        out.append(line)
    return out


def _card_value_of_card_for(args: dict) -> str:
    """模型真发卡时，卡片回传的 confirmValue（与门禁比对的是同一个值）。"""
    return confirm_value_for_fields(confirm_card_fields(args))


class TestCardOnlyConfirmation:
    """判据 A/B：涉钱面只认卡值 —— 文本「确认」不再放行。"""

    def test_text_confirm_does_not_release_product_price_write(self):
        assert _requires_confirmation(ProductUpdateTool(), PRICE_ARGS, "确认") is True

    def test_text_confirm_does_not_release_sku_price_write(self):
        assert _requires_confirmation(SkuUpdateTool(), SKU_PRICE_ARGS, "确认") is True

    def test_generous_text_forms_do_not_release_either(self):
        """把常见「像确认」的文本全试一遍：一条都不许放行改价。"""
        for text in ("确认", "确定", "好的", "可以", "OK", "确认无误", "确认改价"):
            assert _requires_confirmation(ProductUpdateTool(), PRICE_ARGS, text) is True, text

    def test_card_click_is_the_only_release(self):
        """放行链 = 用户消息**逐字等于**卡值（系统自产）⇒ 只有点卡能命中。"""
        card = _card_value_of_card_for(PRICE_ARGS)
        assert card.startswith("确认") is True, "卡值形态变了：门禁的精确匹配基准随之失效"
        assert _is_card_confirm_value(card, card) is True

        # 卡值本身仍然过不了「文本确认」这道闸（长值 + 精确匹配才是它的放行形态）：
        # ⇒ 门禁恒拦，放行只剩 react_turn 的卡值精确匹配这一条路。
        assert _requires_confirmation(ProductUpdateTool(), PRICE_ARGS, card) is True

    def test_batch_execute_and_revert_are_card_only(self):
        """批量 execute/revert：参数里只有 batch_id（钱在批次行里）⇒ 由工具声明入面。"""
        tool = get_tool_registry().get_tool("product_batch_update")
        assert _requires_confirmation(
            tool, {"action": "execute", "batch_id": "b1"}, "确认批量改价 2 条") is True
        assert _requires_confirmation(
            tool, {"action": "revert", "batch_id": "b1"}, "确认") is True

    def test_batch_preview_stays_exempt(self):
        """preview 只落一条 preview 批次、不碰商品数据 ⇒ 必须保持豁免（否则两段确认死锁）。"""
        tool = get_tool_registry().get_tool("product_batch_update")
        assert _requires_confirmation(
            tool, {"action": "preview", "batch_type": "product_price"},
            "已选商品：遮光窗帘、北欧风窗帘") is False


class TestNonPriceWritesUnaffected:
    """判据 F：只改名字/状态/开关的写调用，文本确认照旧放行（不误伤）。"""

    @pytest.mark.parametrize("args", [
        {"product_id": "p1", "name": "新名"},
        {"product_id": "p1", "status": "off_sale"},
        {"product_id": "p1", "allow_return_restock": True},
        {"product_id": "p1", "description": "换个描述"},
    ])
    def test_non_price_write_accepts_text_confirm(self, args):
        assert _requires_confirmation(ProductUpdateTool(), args, "确认") is False

    def test_non_price_write_still_requires_some_confirmation(self):
        assert _requires_confirmation(ProductUpdateTool(), {"product_id": "p1", "name": "新名"},
                                      "帮我改一下名字") is True


class TestPriceFactIsSentToTheServer:
    """判据 C：改前价必须下发（不下发 ⇒ 服务端无从回查，护栏只防漏填不防填错）。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("module_path,tool_cls,kwargs,kw_wire", [
        ("app.tools.product_update", ProductUpdateTool,
         {"product_id": "p1", "price": 199, "before_price": 168}, "beforePrice"),
    ])
    async def test_product_update_sends_before_price(self, module_path, tool_cls, kwargs, kw_wire):
        from unittest.mock import AsyncMock, patch

        client = AsyncMock()
        client.patch = AsyncMock(return_value={"success": True, "data": {}})
        context = _admin_context()
        with patch(f"{module_path}.get_admin_api_client", return_value=client):
            result = await tool_cls().execute(context, **kwargs)

        assert result.success is True
        sent = client.patch.await_args.kwargs["json_data"]
        assert sent[kw_wire] == 168, f"改前价未下发（服务端无从回查）：{sent}"

    @pytest.mark.asyncio
    async def test_sku_update_sends_before_price(self):
        from unittest.mock import AsyncMock, patch

        client = AsyncMock()
        client.patch = AsyncMock(return_value={"success": True, "data": {}})
        with patch("app.tools.sku_update.get_admin_api_client", return_value=client):
            result = await SkuUpdateTool().execute(_admin_context(), **SKU_PRICE_ARGS)

        assert result.success is True
        sent = client.patch.await_args.kwargs["json_data"]
        assert sent["before_price"] == 168, f"改前价未下发（服务端无从回查）：{sent}"


class TestSingleSourceOfTheServerRecheck:
    """判据 D：单条与批次的价格核对是**同一实现**（防两处投影，§17.3）。"""

    def test_shared_comparator_defines_same_value_once(self):
        """`sameValue` 在 admin-api main 源码里只有**一处定义**（唯一实现）。"""
        definitions = []
        for path in sorted(MAIN_JAVA.rglob("*.java")):
            for line in _code_lines(path):
                if re.search(r"\bboolean\s+sameValue\s*\(", line):
                    definitions.append(f"{path.relative_to(REPO)}: {line.strip()}")
        assert len(definitions) == 1, f"价格核对出现了第二份实现：{definitions}"
        assert "AgentWriteValues.java" in definitions[0], definitions

    def test_both_paths_call_the_shared_comparator(self):
        """两处调用点都引用它：批次 create（#5314）+ 单条商品/SKU 改价（#5317）。"""
        batch = _code_lines(MAIN_JAVA / "service/AgentBatchService.java")
        product = _code_lines(MAIN_JAVA / "service/ProductService.java")
        assert any("AgentWriteValues.sameValue(" in line for line in batch), \
            "批次路径没有走共享实现（= 又立了第二套口径）"
        single_calls = [line for line in product if "AgentWriteValues.sameValue(" in line]
        assert len(single_calls) >= 2, \
            f"单条改价路径（商品级 + SKU 级）必须都走共享实现，实测 {len(single_calls)} 处"

    def test_no_local_price_comparison_left_in_the_two_services(self):
        """两处都不得再留「自己拿声明的改前值与当前值比一遍」的代码。

        形态判据 = `compareTo(...)` 且操作数是**声明的改前值**（`beforePrice` / `oldValue`）；
        与 ZERO 的合法性校验（"改后价不能为负"）不算 —— 那是另一件事，不是第二套核对口径。
        """
        for name in ("service/AgentBatchService.java", "service/ProductService.java"):
            offenders = [line.strip() for line in _code_lines(MAIN_JAVA / name)
                         if "compareTo(" in line
                         and any(k in line for k in ("beforePrice", "getOldValue()", "oldValue"))]
            assert offenders == [], f"{name} 里还有本地的改前值比对：{offenders}"

    def test_shared_comparator_is_value_based_not_string_based(self):
        """口径 = 按**值**比对（数字不比字符串写法）：10.0 与 10.00 是同一个价。"""
        src = "\n".join(_code_lines(MAIN_JAVA / "service/AgentWriteValues.java"))
        assert "compareTo(" in src, "共享实现丢了按值比对（退回字符串写法比较即漂移）"
        assert "toPlainString" not in src, "共享实现不得靠字符串写法归一（那是第二套口径）"


class TestClassLevelMetaGuard:
    """判据 E：**类级**元守卫 —— 注册表现取，新改价工具自动进面（不需要人改清单）。"""

    def _write_tools(self):
        return [t for t in get_tool_registry().get_all_tools()
                if not getattr(t, "read_only", True)]

    def test_every_write_tool_declaring_before_price_is_card_only(self):
        """任何「声明了 `before_price`（= 走 #5303 改价预览契约）」的写工具，价格调用只认卡值。"""
        offenders = []
        covered = set()
        for tool in self._write_tools():
            props = ((getattr(tool, "parameters", None) or {}).get("properties") or {})
            if "before_price" not in props:
                continue
            covered.add(tool.name)
            if not _card_only_confirmation(tool, {"price": 199, "before_price": 168}):
                offenders.append(tool.name)
        assert offenders == [], f"声明了 before_price 却仍可被文本确认放行：{offenders}"
        # 防空转（判据不得因为注册表里没有改价工具而假绿）+ 实例锚定
        assert {"product_update", "sku_update"} <= covered, f"实例工具不在射程内：{covered}"

    def test_declared_card_only_actions_are_real_and_gated(self):
        """声明 `card_only_actions` 的工具：动作必须是该工具 schema 里的真实 action 且确实入面。"""
        offenders, covered = [], set()
        for tool in self._write_tools():
            actions = getattr(tool, "card_only_actions", None)
            if not actions:
                continue
            covered.add(tool.name)
            props = ((getattr(tool, "parameters", None) or {}).get("properties") or {})
            enum = (props.get("action") or {}).get("enum") or []
            for action in actions:
                if action not in enum:
                    offenders.append(f"{tool.name}: 声明的 action {action} 不在 schema enum 里")
                if not _card_only_confirmation(tool, {"action": action}):
                    offenders.append(f"{tool.name}.{action}: 声明了却没进面（门禁不认）")
        assert offenders == [], offenders
        assert "product_batch_update" in covered, f"批量工具应声明动作面入面：{covered}"

    def test_meta_guard_sees_the_single_path_tools(self):
        """元守卫的判别力自证：它真的会扫到单条改价工具（而不是空转）。"""
        scanned = [t.name for t in self._write_tools()
                   if "before_price" in (((getattr(t, "parameters", None) or {})
                                          .get("properties") or {}))]
        assert "product_update" in scanned and "sku_update" in scanned, scanned


class TestTextConfirmDoesNotRecordPriceWrite:
    """判据 A·补口：文本确认**不得**给涉钱面记「已确认」。

    否则 `react_turn` 的 `_write_was_confirmed`（读 `confirmed_write_tool`）会拿这条记录
    放行一次改价 —— 那条路径上**没有任何点击**，② 就等于没做。
    """

    class _FakeStore:
        def __init__(self, state: dict):
            self.state = dict(state)

        async def load(self, session_id):
            return dict(self.state)

        async def commit(self, session_id, full):
            self.state = dict(full)

    def _pending(self, params: dict) -> dict:
        return {"target_tool": "product_update", "target_action": "", "params": params}

    def test_pending_card_only_predicate(self):
        assert base_skill._pending_card_only(self._pending(PRICE_ARGS)) is True
        assert base_skill._pending_card_only(
            self._pending({"product_id": "p1", "name": "新名"})) is False
        # 工具查不到（陈旧/拼错的 target_tool）⇒ 不入面（无法判定该工具是否改价）
        assert base_skill._pending_card_only(
            {"target_tool": "不存在的工具", "params": PRICE_ARGS}) is False

    @pytest.mark.asyncio
    async def test_text_confirm_does_not_record_price_write(self, monkeypatch):
        from app.graph.pending_validated import PENDING_KEY

        store = self._FakeStore({PENDING_KEY: self._pending(PRICE_ARGS)})
        monkeypatch.setattr("app.memory.session_state_store.SessionStateStore", lambda: store)

        await base_skill._inject_pending_validated("SYS", {"session_id": "s1"}, "确认")

        assert "confirmed_write_tool" not in store.state, (
            "文本确认给改价记了「已确认」⇒ 下一次调用无需点卡就能放行")

    @pytest.mark.asyncio
    async def test_card_click_still_records_price_write(self, monkeypatch):
        """点卡（卡值逐字匹配）仍照旧记「已确认」—— 收窄的是文本，不是卡片。"""
        from app.graph.pending_validated import PENDING_KEY

        card = _card_value_of_card_for(PRICE_ARGS)
        store = self._FakeStore({PENDING_KEY: self._pending(PRICE_ARGS),
                                 "last_confirm_value": card})
        monkeypatch.setattr("app.memory.session_state_store.SessionStateStore", lambda: store)

        await base_skill._inject_pending_validated("SYS", {"session_id": "s1"}, card)

        assert store.state.get("confirmed_write_tool") == "product_update"

    @pytest.mark.asyncio
    async def test_text_confirm_still_records_non_price_write(self, monkeypatch):
        """非涉钱面照旧：文本确认仍记「已确认」（口径只对改价收窄）。"""
        from app.graph.pending_validated import PENDING_KEY

        store = self._FakeStore({PENDING_KEY: self._pending({"product_id": "p1", "name": "新名"})})
        monkeypatch.setattr("app.memory.session_state_store.SessionStateStore", lambda: store)

        await base_skill._inject_pending_validated("SYS", {"session_id": "s1"}, "确认")

        assert store.state.get("confirmed_write_tool") == "product_update"


class TestPromptsTellTheModelCardOnly:
    """话术面：模型必须知道「改价只认点卡」——否则它会拿文本确认当放行条件反复重试。"""

    def test_product_prompt_states_card_only_for_price(self):
        assert "点卡" in PRODUCT_SYSTEM_PROMPT
        assert "打字「确认」" in PRODUCT_SYSTEM_PROMPT and "不算" in PRODUCT_SYSTEM_PROMPT

    def test_price_tool_descriptions_state_card_only(self):
        for tool in (ProductUpdateTool(), SkuUpdateTool()):
            assert "卡" in tool.description, tool.name


class TestRedProofs:
    """红证：每条判据都要有能**单独变红**的注入，否则它只是空断言（`migao-acceptance`）。"""

    def test_text_release_judgment_is_load_bearing(self, monkeypatch):
        """注入：把涉钱面判据换成"永远不算涉钱" ⇒ 文本确认**必须**重新放行（= 判据真的在拦）。"""
        monkeypatch.setattr(base_skill, "_card_only_confirmation", lambda *a, **k: False)

        assert _requires_confirmation(ProductUpdateTool(), PRICE_ARGS, "确认") is False
        assert _requires_confirmation(
            get_tool_registry().get_tool("product_batch_update"),
            {"action": "execute", "batch_id": "b1"}, "确认") is False

    def test_meta_guard_can_go_red(self, monkeypatch):
        """注入：抽掉某工具的 `before_price` 声明 ⇒ 它脱离射程（元守卫的判据形态可见）。"""
        tool = get_tool_registry().get_tool("product_update")
        props = dict(tool.parameters["properties"])
        props.pop("before_price")
        monkeypatch.setattr(tool, "parameters", {"type": "object", "properties": props})

        scanned = [t.name for t in get_tool_registry().get_all_tools()
                   if not getattr(t, "read_only", True)
                   and "before_price" in (((getattr(t, "parameters", None) or {})
                                           .get("properties") or {}))]
        assert "product_update" not in scanned, "注入没生效：元守卫的射程判据无从变红"

    def test_static_single_source_judgment_can_go_red(self, monkeypatch):
        """注入：把 ProductService 的调用点从共享实现改成"自己比一遍" ⇒ 判据必须变红。"""
        real = Path.read_text

        def fake_read_text(self, *a, **k):
            text = real(self, *a, **k)
            if self.name == "ProductService.java":
                text = text.replace("AgentWriteValues.sameValue(", "Objects.equals(")
            return text

        monkeypatch.setattr(Path, "read_text", fake_read_text)
        product = _code_lines(MAIN_JAVA / "service/ProductService.java")
        assert [line for line in product if "AgentWriteValues.sameValue(" in line] == []


def _admin_context():
    from app.tools.base import ToolContext
    return ToolContext(tenant_id=1, user_id="admin_001", session_id="sess",
                       role="admin", permissions=["*"])