# case_ids: DA-023, MC-051
"""🔴 **跨语言接线判据**（`migao-dev-flow` §28.2「判据本体绿 ≠ 接线在」）—— issue #6347 **Part B**

## 这条判据补的是哪一半

`tests/test_briefing_product_health.py::TestFilteredSkusAreNotMisattributed` 与
`tests/test_tools_briefing_query.py` 的两条，判的是**判据本体**：给一份（我手写的）快照 ⇒ 引擎与
工具必须把「有 SKU 但商品不在售」说对。**但本单的缺陷横在两种语言之间** —— 事实由 Java 装配层
（`DailyBriefingService.assembleSkuRows`）写进 `row_meta.skus`，由 Python 引擎
（`app/briefing/product_health.py`）读出来。两处各写一份夹具的话，**键名 / 嵌套形态 / 值类型**
分叉时两侧的判据**照样全绿**，而线上已经坏了 —— 正是本单「空数组被读成没有 SKU」的同族形态。

⇒ 本文件**只吃服务端真正吐出的 JSON**（`tests/fixtures/snapshot_skus_filtered_out.json`，
由 `DailyBriefingServiceTest#dumpSnapshotForTheCrossLanguageWiringJudge` 落盘后原样拷来，
见该 fixture 的 `_how_to_refresh`），并走**真消费路径**（`briefing_query.render_view_result` +
真 `ToolContext`，即 `BriefingQueryTool(view="product_health")` 唯一的那段段落）。

## 判据与红证

| # | 判据 | 会怎么红 |
|---|---|---|
| 1 | 真 JSON 里 `row_meta.skus` 的**过滤计数**被引擎读成过滤事实 | Java 侧不再透出 `rows_before_filter` ⇒ `available=False` ⇒ 红 |
| 2 | 真 JSON 下 `skus` 来源的三个字段落 `not_on_sale`（不是 `wired` / `not_wired`） | 引擎摘掉过滤分支 ⇒ `wired` ⇒ 红（实测见 PR body 的红证段） |
| 3 | 真 JSON 下**消息**（模型唯一输入源）说清原因与出路、且不含归因错误表述 | 去掉 `_filtered_reason` 那段 ⇒ 缺失/命中禁用词 ⇒ 红 |
| 4 | fixture 自证是「服务端 JSON」而不是我手写的：行数组为空**且**过滤事实在 | 谁把 fixture 改成手写形态（没有 `rows_before_filter`）⇒ 红 |

`WIRING_UNDER_TEST` 声明见下（照 `migao-dev-flow` §28.2.1：测接线的判据必须显式声明被守的接线锚）。
⚠️ **边界（照实登记）**：本声明**不**在 `tests/unit_ci_workflows/wiring_claims_ledger.json` 的机械射程内
（那条守卫只扫 `tests/unit_ci_workflows/**` 出现声明标记的文件）⇒ 它在本台账里属**人为登记**，
不是「未登记即红」。本文件另用判据 4 自证 fixture 的来路。
"""

import json
import re
from pathlib import Path

import pytest

from app.briefing.product_health import (
    FORBIDDEN_ATTRIBUTIONS,
    INCOMPLETE,
    NOT_ON_SALE,
    _RECOVERABLE_STATUSES,  # noqa: PLC2701 —— Part A 的合法状态集合（逐字对齐的靶子）
)
from app.tools.base import ToolContext
from app.tools.briefing_query import BriefingQueryTool, render_view_result

#: 被守的**接线锚**（`<仓库相对路径>::<符号>`；`::` 右边是该文件的真实符号 —— 摘掉它 ⇒ 判据 3 具名红）
WIRING_UNDER_TEST = "backend/ai-agent-service/app/briefing/product_health.py::_filtered_reason"

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "snapshot_skus_filtered_out.json"
REPO_ROOT = Path(__file__).resolve().parents[3]

#: 真 `ToolContext`（`render_view_result` 的入参）：租户原样回显 —— 与 `BriefingQueryTool` 调用点同形
CONTEXT = ToolContext(tenant_id=25, user_id="u-25", session_id="s-25", role="admin",
                      permissions=["dashboard:view"])

#: 本单用户原话点名的归因错误表述（消息里一次都不许出现）
MISATTRIBUTIONS = tuple(FORBIDDEN_ATTRIBUTIONS) + ("建议先确认商品规格",)


@pytest.fixture(scope="module")
def real_snapshot():
    """服务端真正吐出的快照 JSON（fixture 缺失 ⇒ fail-closed 红，不静默跳过）。"""
    if not FIXTURE.is_file():
        raise AssertionError(
            f"跨语言 fixture 缺失：{FIXTURE}（fail-closed）—— 生成方式见其 `_how_to_refresh`"
        )
    return json.loads(FIXTURE.read_text(encoding="utf8"))


class TestServerSnapshotWiring:
    """真 JSON → 真消费路径：把「服务端写的键」与「引擎读的键」钉成同一件事。"""

    def test_fixture_really_came_from_the_server(self, real_snapshot):
        """判据 4：fixture 是**服务端形态**（空行数组 + 过滤事实），不是手写夹具。"""
        meta = real_snapshot["row_meta"]["skus"]

        assert real_snapshot["skus"] == [], "fixture 必须是「过滤后为空」的真形态"
        assert meta["count"] == 0
        assert meta["rows_before_filter"] == 10, (
            "服务端必须透出过滤前读数（fixture 里没有它 ⇒ 要么 fixture 被手写覆盖，要么 Java 侧不再透出）"
        )
        assert meta["filtered_by_status"] == {"active": 10}
        assert len(meta["filtered_product_ids"]) == 8

    def test_engine_reads_the_server_filter_fact(self, real_snapshot):
        """判据 1：引擎必须**真的**从服务端 JSON 里读出过滤事实（键名/形态一致）。"""
        result = render_view_result("product_health", real_snapshot, CONTEXT).data

        assert result["not_on_sale"]["available"] is True, (
            "引擎读不出过滤事实 ⇒ 服务端写的键与引擎读的键分叉了（本文件存在的原因）"
        )
        assert result["not_on_sale"]["rows_before_filter"] == 10
        assert result["not_on_sale"]["filtered_count"] == 10
        assert result["not_on_sale"]["filtered_by_status"] == {"active": 10}

    def test_skus_sourced_fields_are_not_on_sale_not_missing(self, real_snapshot):
        """判据 2：真读数下三个 SKU 来源字段落 `not_on_sale`；退货率（另一对行数组）不受影响。"""
        result = render_view_result("product_health", real_snapshot, CONTEXT).data

        assert result["count"] == 0
        for field in ("sales_count", "stock", "gross_margin"):
            entry = result["fields"][field]
            assert entry["status"] == NOT_ON_SALE, (
                f"{field} 实得 {entry['status']} —— 空数组被读成了「没问题」（本单的误归因根源）"
            )
            assert entry["reason"], "not_on_sale 必须带原因（不变式不给本态开例外）"
        assert result["fields"]["return_rate"]["status"] == INCOMPLETE, (
            "退货率的来源是**另一对**行数组 ⇒ 不受 SKU 过滤影响（逐字段可分）；本 fixture 里它是"
            " incomplete 而非 wired —— 因为装配层刻意**不猜**多商品订单的退货归属（`returns` 有一行"
            " product_id 为 null），这正是「两种不完整必须分开说」在本读数里的另一个实例"
        )

    def test_message_states_cause_and_exit_without_misattribution(self, real_snapshot):
        """判据 3：**消息**（模型的唯一输入源）说清原因 + 出路，且不含归因错误表述。"""
        message = render_view_result("product_health", real_snapshot, CONTEXT).message or ""

        # 用户口径 1：有 N 个 SKU（M 个商品）因未上架未纳入
        for needle in ("10 个 SKU", "8 个商品", "商品未上架", "过滤前"):
            assert needle in message, f"消息缺少「{needle}」：{message}"
        # 用户口径 2：出路对症（active 不在状态机内 ⇒ 上架会被拒 ⇒ 先改回 off_sale/draft）
        for needle in ("active", "上架动作会被拒", "off_sale", "draft"):
            assert needle in message, f"消息缺少出路「{needle}」：{message}"
        # 用户口径 3：禁用表述
        for forbidden in MISATTRIBUTIONS:
            assert forbidden not in message, f"消息出现归因错误表述「{forbidden}」：{message}"

    @pytest.mark.asyncio
    async def test_tool_path_is_the_same_code_path(self, real_snapshot, monkeypatch):
        """真**工具入口**走一遍：`BriefingQueryTool(view="product_health")` 只多一层 HTTP 取数，
        之后与上面直调的是**同一段**代码（`render_view_result`）—— 判据在本文件里两处读数必须一致。"""
        class _Client:
            async def get(self, *args, **kwargs):
                return {"success": True, "data": real_snapshot}

        monkeypatch.setattr("app.tools.briefing_query.get_admin_api_client", lambda: _Client())
        direct = render_view_result("product_health", real_snapshot, CONTEXT)

        result = await BriefingQueryTool().execute(context=CONTEXT, view="product_health")

        assert result.success is True
        assert result.message == direct.message, (
            "工具入口与直调必须逐字同一条消息（否则「接在真入口上」这句话就没有证据）"
        )
        assert result.data["not_on_sale"] == direct.data["not_on_sale"]

    def test_wiring_anchor_is_real(self):
        """`WIRING_UNDER_TEST` 的右半边必须在真文件里逐字存在（摘线 ⇒ 本判据红）。"""
        path, symbol = WIRING_UNDER_TEST.split("::")
        assert (REPO_ROOT / path).is_file(), f"接线锚的文件不存在：{path}"
        assert symbol in (REPO_ROOT / path).read_text(encoding="utf8"), f"接线锚的符号不存在：{symbol}"
        # 顺带：Python 侧的「合法状态」集合必须与 Part A 的单一真值源一致（跨语言，逐字）
        java = (REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java"
                ).read_text(encoding="utf8")
        block = java[java.index("private static final Map<String, List<String>> STATUS_TRANSITIONS"):
                     java.index("PRODUCT_STATUS_LABELS")]
        assert set(re.findall(r'STATUS_TRANSITIONS\.put\("(\w+)"', block)) == \
            set(_RECOVERABLE_STATUSES), (
                "Python 侧 `_RECOVERABLE_STATUSES` 与 Java 侧状态机键集不一致 ⇒ 出路会说过时的话"
            )
