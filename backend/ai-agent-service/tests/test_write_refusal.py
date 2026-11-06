"""写路径「商品引用解析失败」话术的单元判据（issue #8788）

`app/tools/write_refusal.py` 是 `product_update` / `sku_update` 共用的**失败话术单一源**：
两条写工具都靠它把 `ProductResolution` 翻成给模型看的 `ToolResult`。它单独成文件的理由是
**语义边界**——写路径的失败必须让模型知道「什么都没改」，而三种不同的"拒绝"原因（多条候选 /
不存在 / 查询失败）对应三种**不同的下一步动作**：

| status | error | 模型下一步该做什么 |
|---|---|---|
| `ambiguous` | 商品不唯一 | 用候选问商家要哪一件（**不许**替商家挑） |
| `not_found` | 商品不存在 | 换名字搜 / 让商家确认名字（**不许**编 id） |
| `unavailable` | 商品查询失败 | 同样入参重试一次（**不许**说成"商品不存在"） |
| `unsafe_ref` | 商品引用不可用于写入 | 序号 / 无法证明唯一的 id 前缀 ⇒ 换 id 重来（**不许**原样重试） |

⇒ 本文件的判据不是"字段存在"，而是**三态话术互不相同**且每态都带「未执行修改」。

集成面（真的零写请求、写 URL 里是解析出的 id）见
`backend/ai-agent-service/tests/test_write_path_id_resolution.py`。

# case_ids: MC-252
"""

from app.tools.write_refusal import product_ref_failure
from app.utils.id_resolver import ProductResolution


def _messages() -> dict:
    """三态各取一条（`candidates` 用真实候选名，够断言到内容）。"""
    return {
        "ambiguous": product_ref_failure(
            ProductResolution("ambiguous", None, 2, ("奶油风提花布-米白", "奶油风提花布-灰蓝")),
            "奶油风提花布",
        ),
        "not_found": product_ref_failure(ProductResolution("not_found"), "不存在的窗帘XYZ"),
        "unavailable": product_ref_failure(ProductResolution("unavailable"), "2699系列雪尼尔窗帘面料"),
        "unsafe_ref": product_ref_failure(
            ProductResolution("unsafe_ref", detail="「3」是商品序号：序号按创建时间排序，增删商品后会漂移，写操作不接受序号"),
            "3",
        ),
    }


class TestAmbiguous:
    """命中多条：把**条数 + 候选**交回模型，并要求它去问商家要哪一件。"""

    def test_counts_candidates_and_says_nothing_was_written(self):
        result = _messages()["ambiguous"]

        assert result.success is False
        assert result.error == "商品不唯一"
        assert "匹配到 2 个商品" in result.message
        assert "奶油风提花布-米白" in result.message
        assert "奶油风提花布-灰蓝" in result.message
        assert "未执行修改" in result.message, "写工具必须让模型知道什么都没改"

    def test_suggestion_forbids_picking_one(self):
        result = _messages()["ambiguous"]

        assert "product_search" in result.suggestion
        assert "不会替你挑一个" in result.suggestion, "写路径的出口必须是「去问商家」，不是「挑一个改」"

    def test_candidate_count_wins_over_truncated_names(self):
        """候选名只展示前 5 个，但**条数**必须是真的（不许因为截断而少报）。"""
        result = product_ref_failure(
            ProductResolution("ambiguous", None, 7, tuple(f"候选{n}" for n in range(5))),
            "窗帘",
        )

        assert "匹配到 7 个商品" in result.message
        assert "候选4" in result.message
        assert "候选5" not in result.message


class TestNotFound:
    """不命中：带原名回去，让模型换说法搜；**不许**编 id、不许说成"多条"。"""

    def test_names_the_raw_value_and_says_nothing_was_written(self):
        result = _messages()["not_found"]

        assert result.success is False
        assert result.error == "商品不存在"
        assert "不存在的窗帘XYZ" in result.message
        assert "未执行修改" in result.message

    def test_does_not_reuse_the_ambiguous_wording(self):
        result = _messages()["not_found"]

        assert "匹配到" not in result.message, "「不命中」与「命中多条」混成一句 ⇒ 模型会反复重试同一个名称"
        assert "product_search" in result.suggestion


class TestUnavailable:
    """查询失败：**不是**「商品不存在」—— 说成不存在会让模型告诉商家"这商品没有"。"""

    def test_says_query_failed_not_missing(self):
        result = _messages()["unavailable"]

        assert result.success is False
        assert result.error == "商品查询失败"
        assert "商品不存在" not in result.message
        assert "未执行修改" in result.message
        assert "重试" in result.suggestion


class TestUnsafeRef:
    """序号 / 无法证明唯一的 id 前缀：**说清为什么不能用**，否则模型会原样重试同一个入参。"""

    def test_explains_why_the_reference_cannot_be_written(self):
        result = _messages()["unsafe_ref"]

        assert result.success is False
        assert result.error == "商品引用不可用于写入"
        assert "序号" in result.message and "漂移" in result.message
        assert "未执行修改" in result.message
        assert "product_search" in result.suggestion

    def test_detail_is_carried_verbatim_from_the_resolver(self):
        """原因文本的**单一源**在解析器（`detail`）；话术层只搬运，不另写一套。"""
        result = product_ref_failure(
            ProductResolution("unsafe_ref", detail="「d4e5f6a7」是 id 前缀，命中 2 个商品"), "d4e5f6a7")

        assert "「d4e5f6a7」是 id 前缀，命中 2 个商品" in result.message


class TestFourStatesDiffer:
    """判别力自证：四态如果话术相同，上面所有断言都会退化成一条（= 判据失明）。"""

    def test_each_status_has_its_own_error_and_message(self):
        msgs = _messages()

        assert len({m.error for m in msgs.values()}) == 4, "四种拒绝原因必须有四个不同的 error"
        assert len({m.message for m in msgs.values()}) == 4, "四种拒绝原因必须有四种不同的 message"
