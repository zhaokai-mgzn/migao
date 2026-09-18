"""
断言可信度门禁的 L0 防复发守卫（假红/假绿结构性护栏 A 层，#3483 T1 扩展格）。

## 为什么需要这组测试

`.github/assertion_taxonomy.py` 是判据的**单一源**，`.github/case_trust_gate.py` 是它的
PR 门禁外壳。两者若只被「真实用例库」间接覆盖，就有典型风险：**规则悄悄失效而无人发现**
（`migao-acceptance`「空断言」：不会红的断言 = 空断言）。

本文件的形态选择（见 `migao-acceptance`「断言形态：四种写法」）：

* **注入式红证（首选）** —— 在测试内**构造**已知缺陷形态的夹具（携带**实测载荷**，
  逐字取自 `#3832`/`#3833`/`#3559`/`#3778`/`#3822` 的现存用例与种子文件），
  断言判据函数**必报出**对应违规码。与被测真值解耦，永远有效。
* **退化守卫** —— 写工具集合/效果层集合不得为空；判据不得恒真（对**正常**用例必须**不报**）；
  基线清单不得包含「已不再违规」的项（且**只对本次 diff 涉及的用例**做这项校验，
  避免别人修好用例后门禁自己判红）。

## 红证记录（补门禁前后）

见本文件末尾 `TestRedProofRecord.test_red_proof_before_gate_is_documented` 锁定的
`.github/case-trust-redproof.md`：**补前必红 / 补后绿**的原文逐字留档，防止红证被事后改写。
"""
# case_ids: CU-003, PG-013, PR-021, CH-009, CH-016, OR-012, CH-011
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
# 工具集真值（零第三方依赖，与覆盖体检共用；见 TestDegenerateGuardRails 的 A13 不变式）
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

import assertion_taxonomy as tax  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "tests" / "agent_eval" / "fixtures"
GATE = REPO_ROOT / ".github" / "case_trust_gate.py"
BASELINE = REPO_ROOT / ".github" / "case-trust-baseline.json"
REDPROOF = REPO_ROOT / ".github" / "case-trust-redproof.md"
UNIMPLEMENTED = REPO_ROOT / ".github" / "case-trust-unimplemented.json"


def _seed_catalog():
    """真实种子真值（从两份 fixtures SQL 现算）—— 红证必须打在**真种子**上。"""
    cat = {}
    for fn in ("mibao_eval_seed.sql", "xiaobu_eval_seed.sql"):
        p = FIXTURES_DIR / fn
        assert p.exists(), f"种子文件缺失: {p}"
        for table, names in tax.extract_seed_catalog(p.read_text(encoding="utf-8")).items():
            cat.setdefault(table, set()).update(names)
    return cat


# ── 缺陷夹具（载荷逐字取自现存用例 / 种子，见每条的 issue 引用）──────────────────

def fixture_cu_003() -> dict:
    """CU-003「给客户打标签」—— 物理不可满足（#3832）。

    载荷逐字取自 `.github/cases/customer.yml` 的 CU-003（**报缺陷/未修时的形态**）：
      · expectations: customer_manage(action=add_tag)  ← 写
      · pre_clean[].tag_name = "VIP2活跃"；种子里只有 `VIP2` / `活跃`
      · pre_clean[].customer_index = 0 —— **按列表位置定位客户**（规则 e 的红证载荷；
        列表按 `created_at DESC` 排序 ⇒ 重名时点中的是别人中途造的那个客户）
      · 无效果层断言（data_checks 是纯散文，无 `success=true`）

    ⚠️ 上游已在 #3832 修好（`tag_name` 改 `VIP2`、`customer_keyword` 改手机号并去掉
    `customer_index`）—— 本夹具**刻意保留修前形态**以维持判据的判别力（新形态的回归
    由 `test_concurrent_fix_shapes_pass` 锁定）。
    """
    return {
        "id": "CU-003",
        "title": "给客户打标签",
        "expectations": [{"tool": "customer_manage", "args": {"action": "add_tag"}}],
        "data_checks": ["add_tag 真实落库（customer_profiles.tags JSONB 写入），重复标签幂等跳过"],
        "pre_clean": [{
            "type": "customer_tag_remove",
            "customer_keyword": "张三",
            "customer_index": 0,
            "tag_name": "VIP2活跃",
        }],
        "forbidden_text": [],
        "persona": "",
    }


def fixture_pg_013() -> dict:
    """PG-013「米宝加工单 LLM 行为」—— 散文禁令承载关键判据（#3833）。

    载荷取自 `.github/cases/processing-order.yml` 的 PG-013 **报缺陷当时的形态**
    （2026-09-12 新增版本）：
      · expectations 只有工具名 → **无效果层断言**
      · forbidden_text 8 条（**全程**语义，无轮次作用域）
      · 无 pre_clean（写了却不清）

    ⚠️ 与「当下 main 上的 PG-013」的差异（**刻意保留旧形态**，否则判据失去判别力）：
    main 后来给该用例补了 `order_before`（时序断言，属行为层证据 ⇒ 规则 c 已不再命中）。
    本夹具保留**缺陷当时**的字段集，用来证明「规则 c 对**该形态**会红」；
    当下 PG-013 仍违规的两条（NO-EFFECT / NO-SELF-CLEAN）由基线清单承载。

    ⚠️ 工具已**重新锚定**（#4010/A13）：原载荷用的是 `processing_order_generate`，
    该工具已于 #3917 从注册表与 skill 绑定下线 ⇒ 在 `WRITE_TOOLS` 移除它之后（这正是
    A13 的修复），夹具不再是「写用例」，本夹具承载的三条规则同时失去判别力。
    换用在册写工具 `order_manage`（同为订单域 WRITE|DESTRUCTIVE），**缺陷形态不变**
    （只证明「调用了」+ 全程禁令 + 无自清理 + 无前置自断言）。
    """
    return {
        "id": "PG-013",
        "title": "米宝加工单 LLM 行为：查询含加工项订单 → 生成加工单（真实对话）",
        "expectations": [{"tool": "order_query"}, {"tool": "order_manage"}],
        "required_args": [{"tool": "order_manage", "fields": ["order_no"]}],
        "forbidden_text": [
            "暂不支持", "功能不存在", "没有这个功能", "无加工项",
            "生成未成功", "生成失败", "无法生成加工单", "系统判定为",
        ],
        "data_checks": [
            "前置：目标环境至少存在一个「已确认且含加工项」订单（否则 order_query 为空、无法生成）——CI smoke 档不纳入，normal 档需保证前置数据",
            "生成后 processing_orders 落新行（status=generated），订单转 producing（验收以 GET /api/admin/processing-orders?keyword=<订单号> 复核）",
        ],
        "pre_clean": [],
        "persona": "",
    }


def fixture_pr_021() -> dict:
    """PR-021「单独 SKU 调价」—— 假绿：`data_checks` 无 `success=true` ⇒ 不计分（#3559）。

    载荷逐字取自 `.github/cases/product.yml` 的 PR-021：
      · expectations 只有 `sku_update`（无 args）→ 只证明「调用了」
      · data_checks =「sku_update 成功（价格落库）」—— **没有 `success=true` 关键词**
        ⇒ runner 的 `scoring_checks` 不收它 ⇒ 该条**不计分**（用例作者以为写了落库断言）
    """
    return {
        "id": "PR-021",
        "title": "单独 SKU 调价 - 修改某规格价格",
        "expectations": [{"tool": "sku_update"}],
        "data_checks": ["sku_update 成功（价格落库）"],
        "pre_clean": [],
        "forbidden_text": [],
        "persona": "",
    }


def fixture_ch_009() -> dict:
    """CH-009「interact form 表单提交注入上下文」—— 散文唯一判据（`expectations: []`）。

    载荷逐字取自 `.github/cases/chat.yml` 的 CH-009：`expectations: []` +
    3 条纯散文 data_checks（**机器计分型 = 0**）⇒ `total_exp == 0` ⇒ score 恒 1.0。
    """
    return {
        "id": "CH-009",
        "title": "interact form 表单提交注入上下文（__FORM__ 协议）",
        "expectations": [],
        "data_checks": [
            "表单字段注入本轮 LLM 上下文（不改写会话历史）",
            "日志中手机号脱敏（138****8000）",
            "payload 超限/非法 JSON 回退为普通文本处理",
        ],
        "forbidden_text": [],
        "persona": "",
    }


def fixture_ch_016() -> dict:
    """CH-016「明确业务意图不弹转人工建议卡」—— 散文唯一判据（`expectations: []`）。

    载荷逐字取自 `.github/cases/chat.yml` 的 CH-016（2 条纯散文 data_checks）。
    """
    return {
        "id": "CH-016",
        "title": "明确业务意图（下单/查单/报价）不弹转人工建议卡（防打断）",
        "expectations": [],
        "data_checks": [
            "order_query/quote 等明确业务意图即使含情绪词也不 offer（judge 白名单）",
            "正常咨询不出现 interact 建议卡片",
        ],
        "forbidden_text": [],
        "persona": "",
    }


def fixture_single_leg_unmarked() -> dict:
    """单端（纯小布工具集）用例缺 persona 标注 —— 跨腿窄跑必红（#3822）。

    工具集 `{curtain_calc}` ⊆ `eval_case_filter.XIAOBU_TOOLS`（米宝工具集无 curtain_calc）。
    """
    return {
        "id": "FAKE-PR-999",
        "title": "（注入夹具）小布算料用例但未标注 persona",
        "expectations": [{"tool": "curtain_calc"}],
        "data_checks": ["用量结果含 face_width/meters"],
        "forbidden_text": [],
        "persona": "",
    }


def codes(violations) -> set:
    return {v["code"] for v in violations}


# ⚠️ 本文件所有夹具里代表「在册写工具」的工具一律用 `order_manage`（#4010/A13）：
# 原用的 `processing_order_generate` 已于 #3917 从注册表与 skill 绑定下线 —— 在
# `WRITE_TOOLS` 移除它（A13 的修复）之后，用它当写工具的夹具会**静默失去判别力**
# （「写用例」相关规则不再命中，负例断言变成恒真）。


# ══════════════════════════════════════════════════════════════════════════════
# 一、注入式红证：已知缺陷夹具必须被判违规
# ══════════════════════════════════════════════════════════════════════════════

class TestKnownDefectFixturesAreBlocked:
    """每条夹具对应一个**已实证**的缺陷形态 —— 判据函数漏判 = 门禁空壳。"""

    def test_cu_003_unresolvable_preclean_target(self):
        """#3832：`VIP2活跃` 不在种子里 ⇒ 用例物理不可满足。"""
        v = tax.judge_case(fixture_cu_003(), catalog=_seed_catalog())
        assert "CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE" in codes(v), (
            f"CU-003 形态（pre_clean 点名种子不存在的标签）未被判违规，实际={v}"
        )
        hit = [x for x in v if x["code"] == "CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE"][0]
        assert "VIP2活跃" in hit["detail"], f"失败信息必须点名具体值，实际={hit['detail']}"
        assert hit["fix"], "失败信息必须带「怎么改」"

    def test_cu_003_also_missing_effect_assertion(self):
        """CU-003 写 add_tag，却无效果层断言（散文 data_checks 不计分）。"""
        v = tax.judge_case(fixture_cu_003(), catalog=_seed_catalog())
        assert "CASE-TRUST-NO-EFFECT-ASSERTION" in codes(v), (
            f"CU-003 写用例缺效果层断言未被判违规，实际={v}"
        )

    def test_pg_013_forbidden_text_sole_judgement(self):
        """#3833：forbidden_text 全程语义 + 无行为/效果层断言 ⇒ 单轮良性措辞即可判红。"""
        v = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        assert "CASE-TRUST-FORBIDDEN-TEXT-SOLE" in codes(v), (
            f"PG-013 形态（散文禁令单独承载）未被判违规，实际={v}"
        )

    def test_pg_013_write_case_without_self_clean(self):
        """#3800：写了写类工具却没有 pre_clean ⇒ 重试前置不等价。"""
        v = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        assert "CASE-TRUST-NO-SELF-CLEAN" in codes(v), (
            f"PG-013 写用例缺自清理未被判违规，实际={v}"
        )

    def test_pg_013_write_case_without_effect_assertion(self):
        """#3778：写用例「调用了 ≠ 成了」。"""
        v = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        assert "CASE-TRUST-NO-EFFECT-ASSERTION" in codes(v), (
            f"PG-013 写用例缺效果层断言未被判违规，实际={v}"
        )

    def test_pr_021_machine_scored_keyword_missing(self):
        """#3559：`sku_update 成功（价格落库）` 无 `success=true` ⇒ 不计分 ⇒ 假绿。"""
        case = fixture_pr_021()
        assert tax.machine_scored_data_checks(case) == [], (
            "夹具前提被破坏：该条散文 data_checks 本应**不计分**"
        )
        assert tax.scoring_assertion_count(case) == 1, "只有 1 条工具名期望参与计分"
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-NO-EFFECT-ASSERTION" in codes(v), (
            f"PR-021 形态（散文充当落库断言 ⇒ 不计分 ⇒ 假绿）未被判违规，实际={v}"
        )

    @pytest.mark.parametrize("factory", [fixture_ch_009, fixture_ch_016],
                             ids=["CH-009", "CH-016"])
    def test_prose_only_case_is_flagged(self, factory):
        """散文唯一判据（`expectations: []` + 纯散文 data_checks）⇒ 恒绿。"""
        case = factory()
        assert tax.scoring_assertion_count(case) == 0, "夹具前提：计分断言数应为 0"
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-EMPTY-ASSERTION" in codes(v), (
            f"{case['id']} 形态（散文唯一判据 ⇒ 恒绿）未被判违规，实际={v}"
        )

    def test_single_leg_without_persona_is_flagged(self):
        """#3822：纯小布工具集用例缺 persona 标注。"""
        v = tax.judge_case(fixture_single_leg_unmarked(), catalog=_seed_catalog())
        assert "CASE-TRUST-SINGLE-LEG-NO-PERSONA" in codes(v), (
            f"单端未标注 persona 未被判违规，实际={v}"
        )

    def test_all_seven_defect_fixtures_are_covered(self):
        """退化守卫：红证夹具集合不得缩水（删夹具 = 悄悄放弃一条判据）。"""
        factories = [
            fixture_cu_003, fixture_pg_013, fixture_pr_021,
            fixture_ch_009, fixture_ch_016, fixture_single_leg_unmarked,
        ]
        assert len(factories) == 6
        cat = _seed_catalog()
        blocked_codes = set()
        for f in factories:
            blocked_codes |= codes(tax.judge_case(f(), catalog=cat))
        required = {
            "CASE-TRUST-EMPTY-ASSERTION",
            "CASE-TRUST-NO-EFFECT-ASSERTION",
            "CASE-TRUST-NO-SELF-CLEAN",
            "CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE",
            "CASE-TRUST-FORBIDDEN-TEXT-SOLE",
            "CASE-TRUST-VOLATILE-LOCATOR",
            "CASE-TRUST-NO-PRECONDITION-ASSERTION",
            "CASE-TRUST-SINGLE-LEG-NO-PERSONA",
        }
        missing = required - blocked_codes
        assert not missing, f"这些规则从未被任何红证夹具触发（判据可能是空壳）：{sorted(missing)}"


# ══════════════════════════════════════════════════════════════════════════════
# 一之二、可变键定位 / 前置自断言 / 引用新鲜度（E / F / G 红证）
# ══════════════════════════════════════════════════════════════════════════════

class TestVolatileLocator:
    """规则 e：定位被测对象必须用不可变标识（主会话新发现的主机制）。"""

    def test_cu_003_position_locator_is_blocked(self):
        """红证：`CU-003` 的 `customer_index: 0`（按列表位置定位客户）。"""
        v = tax.judge_case(fixture_cu_003(), catalog=_seed_catalog())
        assert "CASE-TRUST-VOLATILE-LOCATOR" in codes(v), (
            f"按列表位置定位被测对象未被判违规，实际={v}"
        )
        hit = [x for x in v if x["code"] == "CASE-TRUST-VOLATILE-LOCATOR"][0]
        assert "customer_index" in hit["detail"], f"失败信息必须点名具体键：{hit['detail']}"
        assert "不可变" in hit["fix"], "修复指引必须说明用不可变标识"

    def test_immutable_key_passes(self):
        """不可变标识（手机号 / order_no / id）⇒ 放行。"""
        case = {
            "id": "FAKE-CU-901", "title": "（注入夹具）手机号定位",
            "expectations": [{"tool": "customer_manage", "args": {"action": "add_tag"}}],
            "must_succeed": [{"tool": "customer_manage"}],
            "precondition": "库里存在手机号 13800138000 的客户",
            "pre_clean": [{"type": "customer_tag_remove",
                           "customer_keyword": "13800138000", "tag_name": "VIP2"}],
            "persona": "mibao",
        }
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-VOLATILE-LOCATOR" not in codes(v), f"不可变标识被误伤：{v}"

    def test_user_input_ordinal_is_not_a_violation(self):
        """**关键口径**：名字/序号出现在 `user_inputs` 里是**合理**的（被测行为的一部分）。

        若判据扫 `user_inputs`，就会大面积误伤（实测全库序数/auto_select 形态 8+ 条）。
        """
        case = {
            "id": "FAKE-OR-902", "title": "（注入夹具）用户说「第一个」",
            "user_inputs": ["给张三加VIP2活跃标签", {"auto_select": True}, "确认"],
            "expectations": [{"tool": "customer_manage", "args": {"action": "add_tag"}}],
            "must_succeed": [{"tool": "customer_manage"}],
            "precondition": "库里存在客户张三",
            "pre_clean": [{"type": "customer_tag_remove",
                           "customer_keyword": "13800138000", "tag_name": "VIP2"}],
            "persona": "mibao",
        }
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-VOLATILE-LOCATOR" not in codes(v), (
            f"`user_inputs` 里的序号被当违规 —— 这会大面积误伤：{v}"
        )

    def test_name_key_positions_are_warning_level_only(self):
        """名字子串/自然键 ⇒ **警告级**（不阻塞），但必须能被识别出来（供清单跟踪）。"""
        case = {"id": "FAKE-PR-903",
                "pre_clean": [{"type": "product_dedupe", "product_keyword": "遮光窗帘"}]}
        pos = tax.name_key_positions(case)
        assert pos and pos[0][1] == "product_keyword", f"名字键未被识别：{pos}"
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-VOLATILE-LOCATOR" not in codes(v), (
            "名字键被判阻塞 —— 全库 20 条会一次全红（应降级为警告）"
        )


class TestPreconditionAssertion:
    """规则 f：多轮/写类用例必须对**自己的前置**给出可判定断言。"""

    def test_pg_013_without_precondition_is_blocked(self):
        """红证：`PG-013` 首跑后订单转 `producing`，重试前置不成立却表现成「agent 不干活」。"""
        v = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        assert "CASE-TRUST-NO-PRECONDITION-ASSERTION" in codes(v), (
            f"无前置自断言未被判违规，实际={v}"
        )

    def test_effect_layer_alone_does_not_satisfy_precondition_rule(self):
        """**防虚增**：只有 `must_succeed` / `db_verify` 不算前置自断言。

        实证：本模块初版把效果层当弱形式接受 ⇒ 「已声明」从 1 条虚增到 37 条，
        那 36 条**根本没说前置是什么**。虚增 = 判据失去判别力（空壳）。
        """
        case = {
            "id": "FAKE-PR-904", "title": "（注入夹具）只有效果层",
            "user_inputs": ["把遮光窗帘改成150元", "确认"],
            "expectations": [{"tool": "sku_update"}],
            "must_succeed": [{"tool": "sku_update"}],
            "db_verify": [{"fetch": "product_by_name", "name": "遮光窗帘",
                           "expect": {"price": 150}}],
            "pre_clean": [{"type": "product_dedupe", "product_keyword": "遮光窗帘"}],
            "persona": "mibao",
        }
        assert tax.declares_precondition(case)[0] is False, (
            "效果层被当成前置自断言 —— 判据虚增（空壳）"
        )
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-NO-PRECONDITION-ASSERTION" in codes(v)

    def test_declared_precondition_passes(self):
        """声明了前置（两种合法形态）⇒ 放行。"""
        base = {
            "id": "FAKE-PR-905", "title": "（注入夹具）已声明前置",
            "user_inputs": ["把遮光窗帘改成150元", "确认"],
            "expectations": [{"tool": "sku_update"}],
            "must_succeed": [{"tool": "sku_update"}],
            "pre_clean": [{"type": "product_dedupe", "product_keyword": "遮光窗帘"}],
            "persona": "mibao",
        }
        by_field = dict(base, precondition="库里恰有一个「遮光窗帘」商品（价格 168）")
        assert tax.declares_precondition(by_field)[0] is True
        assert "CASE-TRUST-NO-PRECONDITION-ASSERTION" not in codes(
            tax.judge_case(by_field, catalog=_seed_catalog()))

        by_machine_check = dict(base, data_checks=[
            "前置：product_search(遮光窗帘) 命中 1 条（success=true）"])
        assert tax.declares_precondition(by_machine_check)[0] is True, (
            "机器计分型 data_checks 里的前置断言未被认可"
        )
        assert "CASE-TRUST-NO-PRECONDITION-ASSERTION" not in codes(
            tax.judge_case(by_machine_check, catalog=_seed_catalog()))

    def test_prose_precondition_data_check_does_not_count(self):
        """**纯散文**前置不计分（#3559 同族）⇒ 不算前置自断言。"""
        case = {
            "id": "FAKE-PR-906", "title": "（注入夹具）散文前置",
            "user_inputs": ["把遮光窗帘改成150元", "确认"],
            "expectations": [{"tool": "sku_update"}],
            "must_succeed": [{"tool": "sku_update"}],
            "pre_clean": [{"type": "product_dedupe", "product_keyword": "遮光窗帘"}],
            "data_checks": ["前置：库里应有「遮光窗帘」商品"],
            "persona": "mibao",
        }
        assert tax.declares_precondition(case)[0] is False, (
            "纯散文前置被当成前置自断言 —— 它不计分，前置不成立时不会红"
        )

    def test_single_round_read_case_not_required(self):
        """单轮只读用例**不强制**（读不改变世界）—— 防无谓摩擦。"""
        case = {
            "id": "FAKE-OR-907", "title": "（注入夹具）单轮查询",
            "user_inputs": ["查订单列表"],
            "expectations": [{"tool": "order_query"}],
            "persona": "mibao",
        }
        assert tax.needs_precondition_assertion(case) is False
        assert "CASE-TRUST-NO-PRECONDITION-ASSERTION" not in codes(
            tax.judge_case(case, catalog=_seed_catalog()))


class TestReferenceFreshness:
    """规则 g：`path:NNN` 行号引用必须对 `origin/main` 命中（#3787 的机器化）。"""

    def test_out_of_range_line_is_blocked(self):
        """红证：行号越界（该行**不存在**）⇒ 阻塞。"""
        refs = tax.find_path_line_refs("见 `tests/agent_eval/local_runner.py:999999` 的说明")
        assert refs and refs[0]["line"] == 999999
        res = tax.check_reference_freshness(
            refs, lambda path: ["line"] * 100 if path.endswith("local_runner.py") else None)
        assert res["blocking"], f"行号越界未被判阻塞：{res}"

    def test_missing_file_is_blocked(self):
        """红证：引用了一个**不存在**的文件 ⇒ 阻塞。"""
        refs = tax.find_path_line_refs("见 `no/such/file.py:10` 的实现")
        res = tax.check_reference_freshness(refs, lambda path: None)
        assert res["blocking"], f"文件不存在未被判阻塞：{res}"

    def test_symbol_missing_from_whole_file_is_blocked(self):
        """红证：行号在范围内，但引用的**符号在该文件里完全不存在** ⇒ 阻塞。"""
        refs = tax.find_path_line_refs("见 `a/b.py:5` 的 `totally_absent_symbol`")
        res = tax.check_reference_freshness(refs, lambda path: ["x = 1"] * 50)
        assert res["blocking"], f"符号不存在未被判阻塞：{res}"

    def test_line_drift_is_warning_not_blocking(self):
        """行号漂移（符号在文件别处）⇒ **警告**（可行动：换符号锚点），不阻塞。"""
        lines = ["def other() -> None:"] * 10 + ["def _target_symbol() -> None:"] + ["pass"] * 40
        refs = tax.find_path_line_refs("见 `a/b.py:2` 的 `_target_symbol`")
        res = tax.check_reference_freshness(refs, lambda path: lines)
        assert not res["blocking"], f"行号漂移被误判阻塞：{res}"
        assert res["warnings"], f"行号漂移应报警告：{res}"

    def test_fresh_reference_passes(self):
        """引用新鲜（符号就在该行附近）⇒ 无阻塞、无警告。"""
        lines = ["x = 1", "x = 2", "def _target_symbol() -> None:", "    pass"] + ["y"] * 40
        refs = tax.find_path_line_refs("见 `a/b.py:3` 的 `_target_symbol`")
        res = tax.check_reference_freshness(refs, lambda path: lines)
        assert res == {"blocking": [], "warnings": []}, f"新鲜引用被误判：{res}"

    def test_bare_line_number_without_symbol_is_not_blocked(self):
        """**防误伤**：只写 `path:NNN`（无符号）且行号合法 ⇒ 不阻塞、不警告。

        仓库里大量正当的 `path:NNN`（如 aftersales.yml 引 `local_runner.py:2000`）
        不能因为「没写符号」被判违规。
        """
        refs = tax.find_path_line_refs("取工单引用走 `local_runner.py:2000`（只认 payload 里的 id）")
        res = tax.check_reference_freshness(refs, lambda path: ["x"] * 5000)
        assert res == {"blocking": [], "warnings": []}, f"合法裸行号被误判：{res}"

    def test_known_stale_refs_from_3787_are_flagged(self):
        """红证夹具取自 `#3787` 的**过期指引形态**（§16.5 → 实际在 §16.7）。

        `#3787` 记的 5 处是「文档指向了错误的节号」，形态 = 引用的**符号/锚点在该处不存在**。
        这里用同形态夹具（引用一个文件里根本不存在的符号）证明判据会红。
        """
        refs = tax.find_path_line_refs(
            "见 `docs/testing/eval-environments.md:86` 的 `nonexistent_anchor_3787`")
        res = tax.check_reference_freshness(
            refs, lambda path: ["# 文档"] * 200 if path.endswith(".md") else None)
        assert res["blocking"], f"#3787 同形态过期引用未被判阻塞：{res}"

    def test_gate_scans_only_new_or_changed_lines(self):
        """只扫**本次新增/改动行** —— 不把存量过期引用算到本 PR 头上。"""
        import importlib.util
        import inspect
        spec = importlib.util.spec_from_file_location("case_trust_gate", GATE)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        src = inspect.getsource(gate.check_reference_freshness_in_diff)
        assert "old_lines" in src and "continue" in src, (
            "规则 G 未做「只扫新增行」过滤 —— 会把存量过期引用算到无关 PR 头上（假红）"
        )

    def test_binary_file_in_diff_does_not_crash_the_gate(self, tmp_path, monkeypatch):
        """红证（issue #4210）：改动集含**二进制文件** ⇒ 规则 G 不得崩溃，且必须**显式登记跳过**。

        病根：`check_reference_freshness_in_diff` 对每个改动文件无条件 `read_text(encoding="utf-8")`。
        本仓的视觉回归基线就是 PNG（**UI 一改就必须更新**）⇒ `UnicodeDecodeError`
        ⇒ 整个 Case Trust Gate 以 **crash** 报红：规则 G **事实上没跑**，却把合法 PR 拦下
        （既是**假红**，又让判据在「改动集含二进制」这一整类 PR 上失效）。
        实证载体：PR #4209（小布主页改版只更新了截图基线，业务断言全绿，本 gate 9s 内崩溃）。

        判据三条（缺任一条都不算修好）：
          ① 不抛异常；
          ② 二进制文件进 `skipped_binary`（**登记**，不是静默跳过 —— 「没跑」必须长得像「没跑」）；
          ③ 跳过**只作用于不可解码的文件**：同一次调用里的**文本**文件仍照旧参与判定
             （其过期 `path:NNN` 仍判阻塞 ⇒ 跳过没有把真判据一起吞掉）。
        """
        gate = _gate_module()
        # 隔离到 tmp_path：不写仓库树、不依赖任何真实二进制资产（并发安全、可复跑）
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(gate, "_ORIGIN_LINES_CACHE", {})

        bin_rel = "assets/probe_binary_4210.png"
        bin_path = tmp_path / bin_rel
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01")

        text_rel = "notes/probe_4210.md"
        text_path = tmp_path / text_rel
        text_path.parent.mkdir(parents=True, exist_ok=True)
        # 过期引用：该文件在仓库里不存在、且不属占位符形态（`_PLACEHOLDER_PATH_RE`）⇒ 必须判阻塞
        text_path.write_text("见 `docs/absent_probe_4210.py:10` 的实现\n", encoding="utf-8")

        res = gate.check_reference_freshness_in_diff([bin_rel, text_rel], base="origin/main")

        assert res.get("skipped_binary") == [bin_rel], (
            f"二进制文件未被登记为跳过（要么崩溃、要么静默跳过）：{res.get('skipped_binary')}")
        assert text_rel not in res["skipped_binary"], (
            f"文本文件被误判为二进制而跳过 —— 跳过面过宽，会连真判据一起吞：{res}")
        assert res["blocking"], (
            f"文本文件里的过期引用未判阻塞 ⇒ 跳过把真判据一起吞掉了（假绿）：{res}")


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据不得宽到误伤（假红侧）
# ══════════════════════════════════════════════════════════════════════════════

class TestNoFalsePositivesOnCorrectShapes:
    """假红与假绿同属「断言可信度」缺陷 —— 判据必须对**正确形态**保持沉默。"""

    def test_read_action_is_not_write(self):
        """`customer_manage(action=query)` 是**读**，不得被当写用例（禁用宽正则的实证）。"""
        case = {
            "id": "FAKE-CU-900", "title": "（注入夹具）客户查询",
            "expectations": [{"tool": "customer_manage", "args": {"action": "query"}}],
            "data_checks": ["返回客户列表"],
            "persona": "mibao",
        }
        assert not tax.is_write_case(case), (
            "customer_manage(action=query) 被误判为写用例 —— 宽正则会误伤读用例"
        )
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-NO-EFFECT-ASSERTION" not in codes(v)
        assert "CASE-TRUST-NO-SELF-CLEAN" not in codes(v)

    def test_read_only_action_list_variants(self):
        """各工具的 `read_only_actions` 一律不得被当写（逐工具枚举的回归锁）。"""
        read_shapes = [
            ("customer_manage", "list"), ("customer_manage", "detail"),
            ("customer_manage", "list_tags"),
            ("after_sales_manage", "list"), ("after_sales_manage", "detail"),
            ("employee_manage", "list"), ("finance_api", "get_summary"),
            ("finance_api", "get_transactions"), ("inventory_manage", "query"),
            ("notification_manage", "list"), ("processing_item_manage", "list_categories"),
            ("role_manage", "list_permissions"), ("session_manage", "monitor"),
            ("settings_manage", "get_ai_config"), ("category_manage", "tree"),
            ("product_search", ""), ("order_query", ""), ("curtain_calc", ""),
        ]
        wrongly_write = [(t, a) for t, a in read_shapes if tax.is_write_expectation(t, {"action": a})]
        assert not wrongly_write, f"这些读形态被误判为写：{wrongly_write}"

    def test_correct_write_shape_passes(self):
        """正确形态（写 + must_succeed + pre_clean + 可解析目标）必须**全绿**。"""
        case = {
            "id": "FAKE-PR-998", "title": "（注入夹具）正确写用例",
            "expectations": [{"tool": "customer_manage", "args": {"action": "add_tag"}}],
            "must_succeed": [{"tool": "customer_manage"}],
            # precondition 是规则 f 的正当要求（写/多轮用例必须自断言前置），
            # 不是「为了变绿而加」—— 缺它不是本夹具的缺陷形态。
            "precondition": "库里存在手机号 13800138000 的客户，且未挂 VIP2 标签",
            "pre_clean": [{"type": "customer_tag_remove",
                           "customer_keyword": "13800138000", "tag_name": "VIP2"}],
            "persona": "mibao",
        }
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert v == [], f"正确形态被误伤（假红）：{v}"

    def test_namespace_only_is_accepted_but_downgraded(self):
        """`namespaces` 是**弱证据**：放行（不阻塞）但证据等级必须如实显示为弱。"""
        case = {
            "id": "FAKE-PR-997", "title": "（注入夹具）只有 namespaces",
            "expectations": [{"tool": "sku_update"}],
            "must_succeed": [{"tool": "sku_update"}],
            "namespaces": ["product:遮光窗帘"],
            "precondition": "库里存在「遮光窗帘」商品（评测前置）",
            "persona": "mibao",
        }
        assert tax.self_clean_evidence(case) == "namespaces"
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-NO-SELF-CLEAN" not in codes(v), (
            "声明了 namespaces 仍被判无自清理 —— 会与并行互斥方案冲突"
        )

    def test_forbidden_text_with_behavior_assertion_passes(self):
        """`forbidden_text` + 行为断言 ⇒ 允许（**不得**写成「凡用 forbidden_text 一律阻塞」）。"""
        case = {
            "id": "FAKE-PR-996", "title": "（注入夹具）禁令 + 效果层断言",
            "expectations": [{"tool": "order_manage"}],
            "must_succeed": [{"tool": "order_manage"}],
            "pre_clean": [{"type": "product_dedupe", "product_keyword": "遮光窗帘"}],
            "precondition": "库里存在一个已确认且含加工项的订单",
            "forbidden_text": ["无法生成加工单"],
            "persona": "mibao",
        }
        assert tax.uses_forbidden_text(case)
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-FORBIDDEN-TEXT-SOLE" not in codes(v), (
            "禁令 + 行为断言被误伤 —— 规则 c 必须允许正确用法"
        )

    def test_forbidden_text_round_scoped_passes(self):
        """已**轮次作用域**的禁令 ⇒ 允许（并发包在 runner 侧新增的能力）。"""
        case = {
            "id": "FAKE-PR-995", "title": "（注入夹具）轮次作用域禁令",
            "expectations": [{"tool": "order_manage"}],
            "must_succeed": [{"tool": "order_manage"}],
            "pre_clean": [{"type": "product_dedupe", "product_keyword": "遮光窗帘"}],
            "precondition": "库里存在一个已确认且含加工项的订单",
            "forbidden_text": [{"text": "无法生成加工单", "rounds": [2, 3]}],
            "persona": "mibao",
        }
        raw = ('  - id: FAKE-PR-995\n'
               '    forbidden_text:\n'
               '      # 轮次作用域：只在 R2/R3 生效（R1 良性措辞不算违规）\n'
               '      - text: "无法生成加工单"\n'
               '        rounds: [2, 3]\n')
        assert tax.forbidden_text_is_round_scoped(raw), "轮次作用域标注未被识别"
        v = tax.judge_case(case, catalog=_seed_catalog(), raw_text=raw)
        assert "CASE-TRUST-FORBIDDEN-TEXT-SOLE" not in codes(v)

    def test_concurrent_fix_shapes_pass(self):
        """**上游修复形态必须放行**（#3832/#3833 落地后的真实形态，2026-09-15 实测）。

        为什么单列：本门禁先合并会校验另一包的 PR。若判据把**正确修复**判红，
        就变成「门禁自己成了 blocker」（假红）。故把两个真实修复形态钉成回归用例：

        · `CU-003`（#3832）：`pre_clean.tag_name` 改为种子真有的 `VIP2`（不再悬空）；
        · `PG-013`（#3833）：① 新增 `pre_clean: [{type: processing_order_reset, order_no: …}]`
          （复位前置）；② `forbidden_text` 部分条目改为**轮次作用域**形态
          （`{round: 2, any_of: [...]}`）—— 轮次作用域已落地 ⇒ 规则 c 必须放行。
        """
        cat = _seed_catalog()
        # CU-003 修复形态：标签名对 + pre_clean 在 + 效果层断言在
        cu003 = {
            "id": "CU-003", "title": "给客户打标签",
            "expectations": [{"tool": "customer_manage", "args": {"action": "add_tag"}}],
            "must_succeed": [{"tool": "customer_manage"}],
            "precondition": "库里存在手机号 13800138000 的客户",
            "pre_clean": [{"type": "customer_tag_remove", "customer_keyword": "13800138000",
                           "tag_name": "VIP2"}],
            "persona": "mibao",
        }
        v = tax.judge_case(cu003, catalog=cat)
        assert v == [], f"CU-003 的**上游修复形态**被误伤（这会让本门禁挡住 #3832）：{v}"

        # PG-013 修复形态：processing_order_reset 自清理 + 轮次作用域禁令
        pg013_raw = (
            '  - id: PG-013\n'
            '    forbidden_text:\n'
            '      - "暂不支持"\n'
            '      - round: 2\n'
            '        any_of: ["无加工项", "无法生成加工单"]\n'
        )
        pg013 = {
            "id": "PG-013", "title": "米宝加工单 LLM 行为",
            "expectations": [{"tool": "order_query"}, {"tool": "order_manage"}],
            "must_succeed": [{"tool": "order_manage"}],
            "precondition": "库里存在订单 EVAL-MB-ORD-0002（已确认且含加工项）",
            "pre_clean": [{"type": "processing_order_reset",
                           "order_no": "EVAL-MB-ORD-0002"}],
            "forbidden_text": ["暂不支持", {"round": 2, "any_of": ["无加工项"]}],
            "persona": "mibao",
        }
        v = tax.judge_case(pg013, catalog=cat, raw_text=pg013_raw)
        assert v == [], f"PG-013 的**上游修复形态**被误伤（这会让本门禁挡住 #3833）：{v}"

    def test_unknown_new_preclean_type_is_not_blocked(self):
        """并发包**新增**的 pre_clean 类型不得被当成「目标不可解析」判红。

        为什么：`processing_order_reset` 这类新类型静态侧尚无映射 —— 那属**未实装**
        （登记在清单里），不是「用例写错了」。把「实现领先于门禁」判红 = 假红。
        """
        case = {
            "id": "FAKE-PG-900", "title": "（注入夹具）新 pre_clean 类型",
            "expectations": [{"tool": "order_manage"}],
            "must_succeed": [{"tool": "order_manage"}],
            "pre_clean": [{"type": "brand_new_type_shipped_by_another_pr", "x": "y"}],
            "persona": "mibao",
        }
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE" not in codes(v), (
            f"新类型被当成目标不可解析判红：{v}"
        )

    def test_marked_single_leg_passes(self):
        """单端用例**已标注** persona ⇒ 不报（规则 d 只要求标注存在）。"""
        case = fixture_single_leg_unmarked()
        case["persona"] = "xiaobu"
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-SINGLE-LEG-NO-PERSONA" not in codes(v)

    def test_dual_leg_case_is_not_required_to_annotate(self):
        """双端用例（工具集不 ⊆ 小布）不得被要求标注（有意不做的口径）。"""
        case = {
            "id": "FAKE-OR-900", "title": "（注入夹具）双端订单查询",
            "expectations": [{"tool": "order_query"}],
            "data_checks": ["列表含订单号"],
            "persona": "",
        }
        assert not tax.is_single_leg_by_toolset(case)
        v = tax.judge_case(case, catalog=_seed_catalog())
        assert "CASE-TRUST-SINGLE-LEG-NO-PERSONA" not in codes(v)


# ══════════════════════════════════════════════════════════════════════════════
# 三、退化守卫（防止判据变成恒真 / 恒假）
# ══════════════════════════════════════════════════════════════════════════════

class TestDegenerateGuardRails:
    def test_write_tool_sets_non_empty(self):
        assert tax.WRITE_TOOLS, "写工具集合为空 ⇒ 所有写用例漏判（门禁空壳）"
        assert tax.WRITE_TOOL_ACTIONS, "写 action 集合为空 ⇒ 同上"
        assert len(tax.WRITE_TOOLS) >= 5, f"写工具集合疑似被削：{sorted(tax.WRITE_TOOLS)}"

    def test_write_tool_sets_only_name_reachable_tools(self):
        """**不变式**：写工具集合里的工具必须**真实可达**（issue #4010 / A13）。

        病根：`WRITE_TOOLS` 是**手写枚举**（本模块 header 解释过为什么必须显式枚举、
        不能用宽正则），但它与「工具是否还在」是两个各自维护的清单 ⇒ 工具下线后
        分类表照旧保留 ⇒ 出现**幽灵写工具**。实证：`processing_order_generate` /
        `processing_order_update` 已于 #3917 从注册表与 skill 绑定移除，本表仍列着。

        为什么是静默失效：`WRITE_TOOLS` 只被 `judge_case` 用来判「该用例是不是写用例」——
        多一个永不出现的工具名，既不会报错也不会让任何用例变红，只是把判据从
        「工具真实可达」悄悄变成「曾经可达」。**本表是判据源，不是历史档案。**

        真值来源：`tests/agent_eval/eval_case_filter.py`（零第三方依赖，CI helper job
        与覆盖体检共用）—— `mibao_real_toolset()` 解析米宝 skill 源码的 `*_TOOLS`，
        `XIAOBU_TOOLS` 是小布侧真值，二者并集 = `scripts/case_coverage.py::registered_tools()`
        的「两端注册表并集」，也是**用例能断言到的工具全集**。不复制清单（复制 = 双源漂移）。
        """
        from eval_case_filter import XIAOBU_TOOLS, mibao_real_toolset  # noqa: PLC0415

        reachable = set(mibao_real_toolset()) | set(XIAOBU_TOOLS)
        # 上界守卫：解析失效（源码改名/正则漂移）时不得退化成「空集 ⇒ 恒真」
        assert len(reachable) >= 30, f"工具集只解析出 {len(reachable)} 个，判据疑似空转"
        ghosts = sorted(set(tax.WRITE_TOOLS) - reachable)
        assert not ghosts, (
            f"WRITE_TOOLS 里这些工具已不可达（下线/改名后未从分类表移除）：{ghosts}"
        )
        ghost_actions = sorted(set(tax.WRITE_TOOL_ACTIONS) - reachable)
        assert not ghost_actions, f"WRITE_TOOL_ACTIONS 里这些工具已不可达：{ghost_actions}"

    def test_effect_field_set_non_empty(self):
        assert tax.EFFECT_FIELDS, "效果层集合为空 ⇒ 效果层要求恒不满足（恒红）"
        assert len(tax.EFFECT_FIELDS) >= 3
        for f in tax.EFFECT_FIELDS:
            assert tax.EFFECT_FIELD_WHY.get(f), f"效果层字段 {f} 缺「为什么算效果层」的理由"

    def test_every_rule_has_why_and_fix(self):
        """规则表不得有无理由/无修复指引的条目（否则失败信息无法行动）。"""
        bad = [r["code"] for r in tax.RULES
               if not r.get("why") or not r.get("fix") or not r.get("counterexample")]
        assert not bad, f"这些规则缺 why/counterexample/fix：{bad}"

    def test_judge_is_not_constant(self):
        """判据**不得恒真/恒假**：坏夹具必报、好夹具必不报（同一函数两种输出）。"""
        good = {
            "id": "FAKE-OK", "title": "（注入夹具）好用例",
            "expectations": [{"tool": "customer_manage", "args": {"action": "add_tag"}}],
            "must_succeed": [{"tool": "customer_manage"}],
            "precondition": "库里存在客户张三（手机号 13800138000）",
            "pre_clean": [{"type": "customer_tag_remove",
                           "customer_keyword": "13800138000", "tag_name": "VIP2"}],
            "persona": "mibao",
        }
        cat = _seed_catalog()
        assert tax.judge_case(good, catalog=cat) == [], "好夹具被判违规 ⇒ 判据恒真（假红）"
        assert tax.judge_case(fixture_pr_021(), catalog=cat), "坏夹具未判违规 ⇒ 判据恒假（空壳）"

    def test_machine_scored_marker_matches_runner_source(self):
        """机器计分口径必须与 runner 同源（防两处口径漂移 = 本模块存在的核心理由）。

        直接读 `local_runner.py` 的判据源码 —— 任一侧改了而另一侧没跟上即红。
        """
        runner = (REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(
            encoding="utf-8")
        anchor = "scoring_checks = list(case.expectations or [])"
        assert anchor in runner, (
            "local_runner 的计分断言收口锚点消失（源码已改）—— 请同步 assertion_taxonomy："
            f"按 {anchor!r} 检索"
        )
        seg = runner[runner.index(anchor): runner.index(anchor) + 800]
        for marker in tax.MACHINE_DATA_CHECK_MARKERS:
            assert marker in seg, (
                f"runner 的机器计分判据里找不到 {marker!r} —— 静态口径与运行期口径已漂移"
            )

    def test_xiaobu_toolset_source_is_forwarded_not_copied(self):
        """小布工具集必须**转发**单一源，不得在本模块复制一份平行清单。"""
        assert tax.XIAOBU_TOOLSET_SOURCE == "eval_case_filter.XIAOBU_TOOLS", (
            "小布工具集来源变了 —— 复制平行清单会造成双源漂移"
        )
        assert tax._XIAOBU_TOOLS, "小布工具集未加载 ⇒ 规则 d 静默失效"

    def test_unimplemented_entries_carry_reason_and_need(self):
        """未实装项必须写明**缺什么**（不得留空凑数），且必须带**可执行约束**四字段。

        本次收紧：只有 `why_not` + `needs` 时，「未实装」可以**永久**当借口
        （无追踪号、无到期日、无「怎么算已实装」⇒ 没有任何东西会因此变红）。
        判据本体 = `tax.judge_unimplemented`；逐条红证见 `TestUnimplementedRegistrations`。
        """
        assert tax.UNIMPLEMENTED, "未实装清单为空 —— 若确实全部落地，请显式说明"
        for item in tax.UNIMPLEMENTED:
            assert item.get("why_not") and item.get("needs"), f"未实装项缺理由/缺口：{item}"
            missing = [f for f in tax.UNIMPLEMENTED_REQUIRED_FIELDS
                       if item.get(f) in (None, "", [], {})]
            assert not missing, f"未实装项 {item.get('code')} 缺必填字段：{missing}"
            assert item.get("hit_probe") in tax.UNIMPLEMENTED_HIT_PROBES, (
                f"未实装项 {item.get('code')} 的 hit_probe 未注册（无判据的登记 = 僵尸登记）："
                f"{item.get('hit_probe')!r}"
            )

    def test_no_rule_is_registered_as_always_true(self):
        """**红线**：规则表里不得出现「恒真」实装（凑数的空壳规则）。"""
        assert all(r["implemented"] is True for r in tax.RULES), (
            "RULES 里出现 implemented=False 的条目 —— 未实装项必须放 UNIMPLEMENTED，"
            "不得留在 RULES 里当恒真规则"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 四、基线清单与「只许缩短」
# ══════════════════════════════════════════════════════════════════════════════

class TestBaselineDiscipline:
    def test_baseline_exists_and_is_shaped(self):
        assert BASELINE.exists(), (
            f"基线清单缺失：{BASELINE} —— 由 `python3 .github/case_trust_gate.py "
            f"--regen-baseline` 生成"
        )
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        assert data.get("anchor_sha"), "基线必须锚定 SHA（否则无法回答『锚定哪个 main 读的数』）"
        assert isinstance(data.get("violations"), dict), "violations 必须是 {case_id: [codes]}"
        assert data.get("rule_counts"), "必须给出逐规则计数（存疑时可核对）"
        assert data.get("regenerate_command"), "必须写明重生成命令（别人修好用例后要重生成）"

    def test_baseline_entries_have_known_codes(self):
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        known = set(tax.RULES_BY_CODE)
        bad = []
        for cid, entry in data["violations"].items():
            for code in (entry.get("codes") if isinstance(entry, dict) else entry):
                if code not in known:
                    bad.append(f"{cid}:{code}")
        assert not bad, f"基线清单里有未知违规码（规则改名后未重生成）：{bad}"

    def test_baseline_is_not_used_to_exempt_all_rules(self):
        """红线：基线不得把某条规则的**全库**用例整体豁免（那等于该规则不存在）。"""
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        counts = data.get("rule_counts") or {}
        total = data.get("case_total") or 0
        assert total > 0, "基线缺 case_total（无法判断豁免面）"
        all_exempt = [code for code, n in counts.items() if n >= total]
        assert not all_exempt, (
            f"这些规则在基线上的违规数 = 用例总数（规则形同不存在）：{all_exempt}"
        )
        # 判据不得恒绿：至少有一条规则在存量上真的报出了东西（否则基线可能被清空成空壳）
        assert any(n > 0 for n in counts.values()), (
            "基线里所有规则计数都是 0 —— 要么规则失效（恒绿），要么清单被清空"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 五、门禁脚本外壳（fail-closed + 只判 diff 命中 + 清单只许缩短）
# ══════════════════════════════════════════════════════════════════════════════

class TestGateShell:
    def _gate(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("case_trust_gate", GATE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_gate_module_exists(self):
        assert GATE.exists(), f"门禁脚本缺失：{GATE}"

    def test_gate_is_fail_closed_on_missing_seed(self):
        """fail-closed：种子真值取不到时必须**报错**，不得静默跳过该条规则。"""
        gate = self._gate()
        with pytest.raises(Exception):
            gate.load_seed_catalog(FIXTURES_DIR / "__不存在__")

    def test_gate_filters_to_changed_case_ids(self):
        """只对**被本次改动命中的用例条目**判（不阻塞存量）。"""
        gate = self._gate()
        cases = [fixture_cu_003(), fixture_pr_021()]
        changed = gate.select_changed_cases(cases, {"PR-021"})
        assert [c["id"] for c in changed] == ["PR-021"], (
            "diff 过滤失效 —— 会把未改动的存量用例也判红"
        )

    def test_gate_reports_new_violation_as_blocking(self):
        """新增用例的违规必须阻塞（不在基线里）。"""
        gate = self._gate()
        violations = tax.judge_case(fixture_pr_021(), catalog=_seed_catalog())
        judged = [{"case_id": "PR-021", "violations": violations}]
        verdict = gate.classify(judged, baseline={"violations": {}})
        assert verdict["blocking"], "新增用例的违规未阻塞 —— 门禁是空壳"
        assert verdict["passed"] == []

    def test_gate_reports_baseline_violation_as_passed(self):
        """存量违规（在基线里）放行 —— 否则第一次跑就红全库。"""
        gate = self._gate()
        violations = tax.judge_case(fixture_pr_021(), catalog=_seed_catalog())
        judged = [{"case_id": "PR-021", "violations": violations}]
        baseline = {"violations": {"PR-021": {"codes": sorted(codes(violations))}}}
        verdict = gate.classify(judged, baseline=baseline)
        assert not verdict["blocking"]
        assert verdict["passed"], "存量违规应记为 passed（放行）"

    def test_gate_partially_blocks_when_baseline_covers_only_some_codes(self):
        """基线只覆盖了部分违规码 ⇒ **未覆盖的那条**仍阻塞（防「记了一条就全放行」）。"""
        gate = self._gate()
        violations = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        assert len({v["code"] for v in violations}) >= 2, "夹具前提：PG-013 应有多条违规"
        one_code = sorted({v["code"] for v in violations})[0]
        judged = [{"case_id": "PG-013", "violations": violations}]
        verdict = gate.classify(
            judged, baseline={"violations": {"PG-013": {"codes": [one_code]}}})
        blocked_codes = {v["code"] for b in verdict["blocking"] for v in b["violations"]}
        assert blocked_codes, "基线覆盖部分违规码时，其余违规码未阻塞"
        assert one_code not in blocked_codes, "已被基线覆盖的码不应重复阻塞"

    def test_full_reconciliation_prunes_entries_outside_the_diff(self):
        """**全量对账**（#4031）：判定范围不再限于「本次 diff 命中的用例」。

        旧口径的病（#4009 裁定 1）：`stale_baseline_entries` 只看 `changed_ids ∩ 清单`，
        于是**只要没人再碰那条用例**，它记的陈旧违规码就永远躺着 = **永久豁免**
        （实测：清单建账 110 → 加规则涨到 143 → **净缩 1 条后冻结**；
        本轮实测存量陈旧码 3 条：`CH-019` / `PG-013` / `PG-015`）。

        红证形态：清单里**两条**都已「不再违规」，而本次 diff 只命中其中一条 ——
        旧口径只报 1 条（另一条永久豁免），新口径必须把**两条都**报出并阻塞。
        """
        gate = self._gate()
        baseline = {"violations": {"CU-003": {"codes": ["CASE-TRUST-NO-SELF-CLEAN"]},
                                  "PG-013": {"codes": ["CASE-TRUST-NO-EFFECT-ASSERTION"]}}}
        changed_ids = {"CU-003"}  # 本次 diff 只命中 CU-003（PG-013 谁都没碰）
        # 旧口径的**判定范围**（#4031 前；这里显式复刻 3 行旧语义以证明差异 ——
        # 复刻的是范围，不是判据：判据仍只有 `.github/assertion_taxonomy.py` 一处）
        old_scope = sorted(changed_ids & set(baseline["violations"]))
        assert old_scope == ["CU-003"], "夹具前提：旧口径只能看到 diff 命中那条"
        recon = gate.reconcile_baseline(baseline, {"CU-003": []})
        ids = [s["case_id"] for s in recon["stale"]]
        assert ids == ["CU-003", "PG-013"], (
            f"未对**全库**条目做陈旧比对（diff 外那条会变成永久豁免）：{ids}"
        )
        assert len(ids) > len(old_scope), "全量对账没比旧口径多看到任何东西 = 改动没落地"
        assert recon["blocking"], (
            "陈旧条目必须**阻塞**（#4031 的核心）—— 只告警就还是一条不会红的判据（R5）"
        )
        assert gate.PRUNE_COMMAND in recon["stale"][0]["hint"], (
            "陈旧项必须带「怎么改」（指向只删不加的 `--prune-baseline`）"
        )

    def test_full_reconciliation_blocks_entry_dropped_while_still_violating(self):
        """反向对账（R4）：`origin/main` 记着、现在**仍违规**却被删掉的条目 ⇒ 阻塞。

        为什么必须有这一条：burn-down 预算在施压让人删条目 ⇒ 没有反向对账，
        「清单只许缩短」会退化成「随便删都算缩短」= 偷偷新增豁免。
        """
        gate = self._gate()
        base = {"violations": {"PG-013": {"codes": ["CASE-TRUST-NO-PRECONDITION-ASSERTION"]}}}
        v = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        assert "CASE-TRUST-NO-PRECONDITION-ASSERTION" in codes(v), "夹具前提：该码仍命中"
        # 本 PR 把这条**仍在违规**的条目删了（清单确实变短了，但那是新增豁免）
        recon = gate.reconcile_baseline({"violations": {}}, {"PG-013": v}, base_baseline=base)
        assert [d["case_id"] for d in recon["dropped"]] == ["PG-013"], (
            f"删掉仍在违规的条目未被判红（= 新增豁免无门禁）：{recon['dropped']}"
        )
        assert recon["blocking"], "偷偷新增豁免必须阻塞"
        # 负例（R2）：删掉「已不再违规」的条目是**正确**行为，不得判成 dropped
        # （动态挑一个夹具当前确实不命中的码，避免与规则演进脱节）
        unused = next(r["code"] for r in tax.RULES if r["code"] not in codes(v))
        base2 = {"violations": {"PG-013": {"codes": [unused]}}}
        recon2 = gate.reconcile_baseline({"violations": {}}, {"PG-013": v}, base_baseline=base2)
        assert not recon2["dropped"], (
            f"已修好的条目被删是正确行为，不得判成新增豁免（假红）：{recon2['dropped']}"
        )

    def test_gate_does_not_prune_when_case_still_hits_recorded_code(self):
        """基线记的码仍命中 ⇒ 不走「陈旧移除」（未记录的新码由 classify 阻塞）。"""
        gate = self._gate()
        # PG-013 夹具当下同时报 NO-EFFECT 与 NO-PRECONDITION；基线只记了后者
        baseline = {"violations": {"PG-013": {"codes": ["CASE-TRUST-NO-PRECONDITION-ASSERTION"]}}}
        v = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        assert "CASE-TRUST-NO-PRECONDITION-ASSERTION" in codes(v), "夹具前提：应命中该码"
        recon = gate.reconcile_baseline(baseline, {"PG-013": v})
        assert recon["stale"] == [], f"仍命中原记码的用例被当成陈旧项：{recon['stale']}"
        # 而未记录的 NO-EFFECT 必须由 classify 阻塞（新增违规的口子不许松）
        verdict = gate.classify([{"case_id": "PG-013", "violations": v}], baseline=baseline)
        blocked = {x["code"] for b in verdict["blocking"] for x in b["violations"]}
        assert "CASE-TRUST-NO-EFFECT-ASSERTION" in blocked, (
            "未记录在基线里的违规码未阻塞（假绿）"
        )

    def test_gate_prunes_when_recorded_code_no_longer_hits(self):
        """「修好一条、又犯另一条」⇒ 原记码不再命中 ⇒ 必须收窄该条（清单只许缩短）。

        形态取自并发包修 CU-003 的可能结果：标签名改对了（PRECLEAN 码消失），
        但仍缺效果层断言（NO-EFFECT 是新码）—— 基线条目陈旧 + 新码阻塞，两者都要报。
        """
        gate = self._gate()
        baseline = {"violations": {"CU-003": {
            "codes": ["CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE"]}}}
        # 把标签名改对后再判（夹具当下确实还报 PRECLEAN 码）
        fixed = copy.deepcopy(fixture_cu_003())
        fixed["pre_clean"][0]["tag_name"] = "VIP2"
        v = tax.judge_case(fixed, catalog=_seed_catalog())
        assert "CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE" not in codes(v)
        recon = gate.reconcile_baseline(baseline, {"CU-003": v})
        assert [s["case_id"] for s in recon["stale"]] == ["CU-003"], (
            f"原记码不再命中却未报「清单可缩短」：{recon['stale']}"
        )
        assert recon["stale"][0]["removed_codes"] == ["CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE"]
        assert recon["blocking"], "陈旧条目必须阻塞（#4031）"

    def test_stale_baseline_entry_blocks_and_report_says_so(self):
        """**#4031 的口径反转**：陈旧基线条目从「只告警」改为**阻塞**。

        旧口径的理由（当时的实证：#3832/#3833 在修 CU-003/PG-013，基线文件同时在飞）是
        「别把修好用例的人卡在别人的文件上」。裁定 1 判定该退让的代价更大 ——
        它正是**永久豁免**的来源（没人再碰那条用例 ⇒ 永远不会被要求移除）。
        为此本包同时给出**机械修复**（`--prune-baseline`，只删不加）与**反向对账**
        （删掉仍在违规的条目同样阻塞），使「只许缩短」两侧都闭合。
        """
        gate = self._gate()
        report = gate.render_report(blocking=[], passed=[], stale=[
            {"case_id": "PG-013", "removed_codes": ["CASE-TRUST-NO-EFFECT-ASSERTION"],
             "now_codes": [], "hint": "hint"}],
            changed_ids=set(), unimplemented=[])
        assert "❌ 阻塞" in report, f"陈旧项未判阻塞：{report[:400]}"
        assert "✅ 通过" not in report
        assert "全量对账" in report or "只许缩短" in report, "报告未说明这是全量对账的结论"

    def test_unimplemented_manifest_registers_the_remaining_burn_down_gaps(self):
        """机制现状必须**照实登记**（不许把「写进技能」当「有门禁」，也不许倒过来）。

        #4031 落地后，原来那条「清单缩短无机械强制，只告警」的登记已成**假真值** ⇒
        必须换成真实残留缺口：每-PR 口径的 scope（未登记违规已 fail-closed、drift_audit 已同步）。
        同时**不得**再留着「只告警」这类与实现相反的措辞（`migao-acceptance`：
        注释漂移 = 假绿来源）。
        """
        assert UNIMPLEMENTED.exists(), f"未实装清单缺失：{UNIMPLEMENTED}"
        text = UNIMPLEMENTED.read_text(encoding="utf-8")
        for needle in ("CASE-TRUST-BURN-DOWN-SCOPE-CASE-TOUCHING-ONLY",):
            assert needle in text, f"未实装清单缺了 #4031 后的真实残留缺口登记：{needle}"
        assert "CASE-TRUST-BASELINE-PRUNING-ENFORCEMENT" not in text, (
            "旧的「无机械强制，只告警」登记未撤 —— 与实现相反，是假真值"
        )
        # #4046 已于本 PR 翻转 fail-closed ⇒ 该条**不得**再留在未实装清单里
        # （留着就是与实现相反的假真值：读者会以为「未登记违规只报告」）。
        assert "CASE-TRUST-UNREGISTERED-VIOLATION-NOT-BLOCKING" not in text, (
            "「未登记违规只报告」的未实装登记未撤 —— 该口径已 fail-closed（#4046）"
        )
        # #4045 已落地（drift_audit 改为全量对账 + burn-down 预算，判据 **import 复用** 本门禁的
        # `reconcile_baseline` / `burn_down_verdict`）⇒ 该条**不得**再留在未实装清单里
        # （留着就是与实现相反的假真值）。两份清单（JSON + `assertion_taxonomy`）必须同源。
        assert "DRIFT-AUDIT-STALE-DIFF-SCOPED" not in text, (
            "「drift_audit 仍是 diff 命中口径」的未实装登记未撤 —— 该口径已全量对账（#4045）"
        )
        assert not [u for u in tax.UNIMPLEMENTED if str(u["code"]).startswith("DRIFT-AUDIT-")], (
            f"`assertion_taxonomy.UNIMPLEMENTED` 里仍留着 drift_audit 的未实装登记："
            f"{[u['code'] for u in tax.UNIMPLEMENTED]} —— 与 `.github/case-trust-unimplemented.json` "
            f"必须同源（#4045 落地后撤登记）"
        )

    def test_gate_blocks_unknown_preclean_without_crashing(self):
        """未知 pre_clean type 不得让门禁崩（登记为未实装，不写恒真规则）。"""
        gate = self._gate()
        case = {
            "id": "FAKE-PR-994", "title": "（注入夹具）未知 pre_clean 类型",
            "expectations": [{"tool": "sku_update"}],
            "must_succeed": [{"tool": "sku_update"}],
            "pre_clean": [{"type": "totally_unknown_type", "whatever": "x"}],
            "persona": "mibao",
        }
        v = gate.judge_all([case], catalog=_seed_catalog())[0]["violations"]
        assert "CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE" not in codes(v), (
            "未知 pre_clean 被当「目标不可解析」判红 —— 那是未实装项，不是阻塞项"
        )
        assert "CASE-TRUST-NO-SELF-CLEAN" not in codes(v), (
            "声明了 pre_clean（哪怕类型未知）仍被判无自清理"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 五之二、burn-down 预算与全量对账的端到端红证（#4031 交付 2 / 3）
# ══════════════════════════════════════════════════════════════════════════════

def _gate_module():
    """按路径加载门禁模块（它是脚本不是包）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("case_trust_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 预算配置夹具：与 `.github/case-trust-baseline.json` 的 `burn_down` 同形（日期是注入用的）
# `metric=entries` = **本次收紧后的现行口径**（只认整条销账）；旧口径 `entries_or_codes`
# 只在「改前/改后对照」的用例里显式构造。
CFG = {"per_pr_min": 1, "metric": "entries", "scope": "case_touching_prs",
       "priority_prefixes": ["OR-"], "priority_deadline": "2026-10-31",
       "deadline": "2026-12-31"}


def _bd_baseline(entries: int, codes_per_entry: int = 1, cfg: dict | None = None,
                 prefix: str = "") -> dict:
    """合成一份清单（`entries` 条，每条 `codes_per_entry` 个码）—— 只喂预算裁决，不碰真库。"""
    v = {f"{prefix}C{i:03d}": {"codes": [f"CODE-{j}" for j in range(codes_per_entry)]}
         for i in range(entries)}
    out: dict = {"violations": v}
    if cfg is not None:
        out["burn_down"] = cfg
    return out


class TestBurnDownBudget:
    """burn-down 预算（#4009 裁定 1 第三条 / #4031 交付 3）。

    「每 PR 至少消 N 条 + 到期清零 + 先清 OR-*」三条**都必须能红**（R5：不会红的判据 = 空断言），
    且每条配一个负例（R2：不许拦掉本来合法的输入）。
    """

    def test_budget_blocks_when_nothing_was_burned(self):
        g = _gate_module()
        v = g.burn_down_verdict(_bd_baseline(3, cfg=CFG), _bd_baseline(3, cfg=CFG),
                                "2026-09-18", case_files_touched=True)
        assert v["blocking"], f"一条没消却不红 —— 预算形同虚设：{v}"
        assert any("预算未达标" in r for r in v["reasons"]), v["reasons"]

    def test_budget_passes_when_nothing_is_left(self):
        """负例（R2）：清单已清零 ⇒ 每-PR 最低消减不得再拦（否则成了永远不会绿的判据）。"""
        g = _gate_module()
        v = g.burn_down_verdict(_bd_baseline(1, cfg=CFG), _bd_baseline(0, cfg=CFG),
                                "2026-09-18", case_files_touched=True)
        assert not v["blocking"], v["reasons"]
        assert any("已清零" in n for n in v["notes"]), v["notes"]

    def test_budget_blocks_on_code_level_narrowing_that_old_metric_allowed(self):
        """**本次收紧的改前/改后对照（红证）**：`metric` 由 `entries_or_codes` → `entries`。

        形态：一条多码条目**收窄**（删掉其中一个码，条目本身还在）——
        这是「为绿而绿」的确切形态：豁免面（该用例仍命中违规码）**没有真的变小**，
        只是账面小了一格。

        · 旧口径 `entries_or_codes` = `max(净缩条目, 净缩码)` ⇒ 净缩码 1 ⇒ **过门禁**（改前绿）；
        · 新口径 `entries` ⇒ 净缩条目 0 ⇒ **红**（改后红），且失败文案必须点名
          「收窄不算」与「必须整条销账」。

        ⚠️ 两侧传**同一份 cfg**，否则会同时命中「配置只许收紧」那条判据，红的原因就
        不是本用例要证的口径差异了（R2：判据要能分辨自己红在哪）。
        """
        g = _gate_module()
        base = _bd_baseline(2, codes_per_entry=2, cfg=CFG)
        cur = _bd_baseline(2, codes_per_entry=2, cfg=CFG)
        cur["violations"]["C000"]["codes"] = ["CODE-0"]  # 只删一个码 = 收窄，不是销账

        old_cfg = {**CFG, "metric": "entries_or_codes"}
        old = g.burn_down_verdict(_bd_baseline(2, codes_per_entry=2, cfg=old_cfg),
                                  copy.deepcopy(cur) | {"burn_down": old_cfg},
                                  "2026-09-18", case_files_touched=True)
        assert not old["blocking"], (
            f"夹具前提：旧口径下「收窄一个码」应当过门禁（这才是被收紧的形态）：{old['reasons']}"
        )

        new = g.burn_down_verdict(base, cur, "2026-09-18", case_files_touched=True)
        assert new["blocking"], (
            f"metric=entries 下「只收窄一个码」未被拦 —— 口径没收紧：{new}"
        )
        assert any("预算未达标" in r and "收窄不算" in r for r in new["reasons"]), new["reasons"]
        assert new["net"]["entries"] == [2, 2] and new["net"]["codes"] == [4, 3], new["net"]

    def test_budget_passes_when_a_whole_entry_is_retired(self):
        """负例（R2）：**整条销账**（该用例不再命中任何码 ⇒ 条目消失）必须算达标。

        否则 `metric=entries` 会变成「永远不会绿的判据」—— 收紧口径 ≠ 拦掉合法输入。
        """
        g = _gate_module()
        v = g.burn_down_verdict(_bd_baseline(3, codes_per_entry=2, cfg=CFG),
                                _bd_baseline(2, codes_per_entry=2, cfg=CFG),
                                "2026-09-18", case_files_touched=True)
        assert not v["blocking"], v["reasons"]
        assert v["net"]["entries"] == [3, 2] and v["net"]["codes"] == [6, 4], v["net"]

    def test_budget_skips_prs_that_touch_no_case_file_but_says_so(self):
        """默认口径 `scope=case_touching_prs`：不改用例的 PR 不承担每-PR 消减，但必须**说出来**。"""
        g = _gate_module()
        v = g.burn_down_verdict(_bd_baseline(3, cfg=CFG), _bd_baseline(3, cfg=CFG),
                                "2026-09-18", case_files_touched=False)
        assert not v["blocking"], v["reasons"]
        assert any("不适用" in n for n in v["notes"]), (
            f"跳过了却不说明 —— 「没跑」必须长得像「没跑」：{v['notes']}"
        )

    def test_budget_all_prs_scope_is_available_and_blocks(self):
        """字面口径（每个 PR）是**数据开关**，不是空话：`scope=all_prs` 时同样红。"""
        g = _gate_module()
        cfg = {**CFG, "scope": "all_prs"}
        v = g.burn_down_verdict(_bd_baseline(3, cfg=cfg), _bd_baseline(3, cfg=cfg),
                                "2026-09-18", case_files_touched=False)
        assert v["blocking"], f"all_prs 口径未生效：{v}"

    def test_budget_blocks_baseline_growth(self):
        """R4：清单**增长**（= 新增豁免）必须红 —— 否则「加 10 条、消 1 条」也算达标。"""
        g = _gate_module()
        v = g.burn_down_verdict(_bd_baseline(2, cfg=CFG), _bd_baseline(4, cfg=CFG),
                                "2026-09-18", case_files_touched=False)
        assert v["blocking"], f"清单增长未判红（R4 失守）：{v}"
        assert any("增长" in r for r in v["reasons"]), v["reasons"]

    def test_priority_deadline_forces_or_entries_first(self):
        """先清 `OR-*`：优先档到期后清单里不得再有 `OR-*` 条目（且报告把它们排在最前）。"""
        g = _gate_module()
        cur = _bd_baseline(2, cfg=CFG, prefix="OR-")
        late = g.burn_down_verdict(_bd_baseline(3, cfg=CFG), cur, "2026-11-01",
                                   case_files_touched=False)
        assert late["blocking"], f"OR-* 优先档到期未判红：{late}"
        assert any("OR-" in r and "到期" in r for r in late["reasons"]), late["reasons"]
        assert late["priority_remaining"] == ["OR-C000", "OR-C001"], late["priority_remaining"]
        # 负例（R2）：还没到期 ⇒ 不得因 OR-* 判红
        early = g.burn_down_verdict(_bd_baseline(3, cfg=CFG), cur, "2026-10-30",
                                    case_files_touched=False)
        assert not early["blocking"], f"未到期就判红（假红）：{early['reasons']}"

    def test_deadline_zero_out(self):
        """到期清零：`deadline` 之后清单必须为空（有任何条目即红）；清零后不得再红。"""
        g = _gate_module()
        late = g.burn_down_verdict(_bd_baseline(2, cfg=CFG), _bd_baseline(1, cfg=CFG),
                                   "2026-12-31", case_files_touched=False)
        assert late["blocking"], f"到期未清零未判红：{late}"
        assert any("到期清零" in r for r in late["reasons"]), late["reasons"]
        done = g.burn_down_verdict(_bd_baseline(2, cfg=CFG), _bd_baseline(0, cfg=CFG),
                                   "2027-06-01", case_files_touched=False)
        assert not done["blocking"], f"已清零仍判红（假红）：{done['reasons']}"

    def test_budget_config_cannot_be_weakened(self):
        """预算**只许收紧**：per_pr_min 降低 / 到期日推后 / 优先前缀去掉 / 整块删除 ⇒ 都红。"""
        g = _gate_module()
        variants = {
            "per_pr_min 降低": {**CFG, "per_pr_min": 0},
            "deadline 推后": {**CFG, "deadline": "2027-12-31"},
            "priority_deadline 推后": {**CFG, "priority_deadline": "2027-01-31"},
            "优先前缀去掉": {**CFG, "priority_prefixes": []},
            "整块删除": None,
        }
        for name, cfg in variants.items():
            cur = _bd_baseline(2, cfg=cfg) if cfg is not None else _bd_baseline(2)
            v = g.burn_down_verdict(_bd_baseline(2, cfg=CFG), cur, "2026-09-18",
                                    case_files_touched=False)
            assert v["blocking"], f"「{name}」未被拦（预算可被自证式放宽）：{v}"

    def test_effective_config_comes_from_base_not_from_this_pr(self):
        """生效配置读 `origin/main` 那一份 ⇒ 本 PR 挪到期日改不动**本次**判定。"""
        g = _gate_module()
        base = _bd_baseline(2, cfg={**CFG, "deadline": "2026-09-30"})  # 已过期
        cur = _bd_baseline(2, cfg={**CFG, "deadline": "2099-12-31"})  # 本 PR 想推后
        v = g.burn_down_verdict(base, cur, "2026-10-05", case_files_touched=False)
        assert v["source"] == "base(origin/main)", v["source"]
        assert v["config"]["deadline"] == "2026-09-30", (
            f"生效配置来自本 PR 清单（可自证式放宽）：{v['config']}"
        )
        assert v["blocking"], f"base 的到期日已过却未判红：{v}"

    def test_budget_inactive_is_visible_not_silent(self):
        """两侧都没有 `burn_down` 块 ⇒ 未激活，但必须**打印出来**（不静默）。"""
        g = _gate_module()
        v = g.burn_down_verdict(_bd_baseline(2), _bd_baseline(2), "2026-09-18", True)
        assert not v["active"] and not v["blocking"]
        assert any("未激活" in n for n in v["notes"]), v["notes"]


class TestGateScriptEndToEnd:
    """端到端红证：真跑脚本、真退出码（函数级绿 ≠ CI 绿）。"""

    def test_script_exits_1_on_stale_entry_outside_the_diff(self, tmp_path):
        """把一条**已不再命中**的码写回清单副本 ⇒ 脚本必须 exit 1 并给出 prune 命令。

        这条同时是「改前不报 / 改后报」的可执行形态：该码所在用例**不在本次 diff 里**
        （本 PR 不改 `.github/cases/*.yml`），旧口径连判都不判（直接「未跑」+ exit 0）。

        ⚠️ **基准用 `HEAD` 而不是 `origin/main`**（首轮 CI 红的根因，实测）：
        跑本文件的 `ci workflow helper unit tests` job 是 `actions/checkout@v7` **默认浅克隆**
        （没有 `fetch-depth: 0`）⇒ `origin/main` **不存在** ⇒ 门禁在 `changed_case_files` 处
        fail-closed `exit 1`（stdout 为空）⇒ 断言「必须报出陈旧项」失败。
        本用例要证的是**账本对账**（与 diff 基准是谁无关），用 `HEAD` 既等价又不依赖浅克隆；
        真要判 `origin/main` 的那个 job（`case-trust-gate`）自己带 `fetch-depth: 0`。
        """
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        entry = data["violations"]["PG-013"]
        entry["codes"] = sorted(set(entry["codes"]) | {"CASE-TRUST-NO-EFFECT-ASSERTION"})
        tmp = tmp_path / "baseline.json"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        r = subprocess.run([sys.executable, str(GATE), "--base", "HEAD",
                            "--baseline", str(tmp)],
                           capture_output=True, text=True, cwd=str(REPO_ROOT))
        assert r.returncode == 1, (
            f"陈旧条目未让脚本 exit 1（假绿）：\nstdout={r.stdout[-1500:]}\nstderr={r.stderr[-800:]}"
        )
        assert "全量对账" in r.stdout and "--prune-baseline" in r.stdout, (
            f"stdout={r.stdout[-1500:]}\nstderr={r.stderr[-800:]}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 五之三、`metric` 只许收紧（本次收紧：entries_or_codes → entries）
# ══════════════════════════════════════════════════════════════════════════════

class TestMetricOnlyTightens:
    """`burn_down.metric` 的「只许收紧」+ 数据面锁。

    病灶：`burn_down_verdict` 原实现**只**校验 `per_pr_min` / 到期日 / 优先前缀 ——
    `metric` 维度根本没校验 ⇒ 别人可以把 `entries` **放宽回** `entries_or_codes`
    而不被拦（= 悄悄把门槛降回去，且是一条**不会红的判据**）。
    这里用**注入式红证**（把 base 配置改成更松 ⇒ 必须红）把这条补上。
    """

    def test_metric_cannot_be_relaxed_to_entries_or_codes(self):
        """注入式红证：base 的 metric=entries，当前改成 entries_or_codes ⇒ **必须红**。"""
        g = _gate_module()
        base = _bd_baseline(3, cfg=CFG)                      # CFG.metric = entries
        cur = _bd_baseline(3, cfg={**CFG, "metric": "entries_or_codes"})
        v = g.burn_down_verdict(base, cur, "2026-09-18", case_files_touched=True)
        assert v["blocking"], f"metric 被放宽回宽松档却未拦（门槛可被悄悄降回去）：{v}"
        assert any("metric" in r and "放宽" in r for r in v["reasons"]), v["reasons"]

    def test_metric_cannot_be_relaxed_to_codes(self):
        """中间档同样不许回退（`codes` < `entries`）。"""
        g = _gate_module()
        v = g.burn_down_verdict(_bd_baseline(3, cfg=CFG),
                                _bd_baseline(3, cfg={**CFG, "metric": "codes"}),
                                "2026-09-18", case_files_touched=True)
        assert v["blocking"], f"metric 由 entries 放宽为 codes 未拦：{v}"

    def test_deleting_metric_field_is_relaxation(self):
        """删掉 `metric` 字段 = 回落宽松默认档 ⇒ 同样算放宽（不许靠删字段回退）。"""
        g = _gate_module()
        cur_cfg = {k: v for k, v in CFG.items() if k != "metric"}
        v = g.burn_down_verdict(_bd_baseline(3, cfg=CFG), _bd_baseline(3, cfg=cur_cfg),
                                "2026-09-18", case_files_touched=True)
        assert v["blocking"], f"删掉 metric 字段未拦（回落到宽松默认档）：{v}"

    def test_unknown_metric_is_fail_closed(self):
        """未知/拼错的口径 ⇒ 阻塞（旧实现 `dict.get(metric, max(...))` 会静默降级成最宽松）。"""
        g = _gate_module()
        v = g.burn_down_verdict(_bd_baseline(3, cfg={**CFG, "metric": "ENTRIES"}),
                                _bd_baseline(3, cfg={**CFG, "metric": "ENTRIES"}),
                                "2026-09-18", case_files_touched=True)
        assert v["blocking"], f"未知口径未 fail-closed（写错一个字母就降门槛）：{v}"
        assert any("不是已知口径" in r for r in v["reasons"]), v["reasons"]

    def test_tightening_metric_is_allowed(self):
        """负例（R2）：把 metric 从宽松档**收紧**（entries_or_codes → entries）不得拦。"""
        g = _gate_module()
        v = g.burn_down_verdict(_bd_baseline(3, cfg={**CFG, "metric": "entries_or_codes"}),
                                _bd_baseline(3, cfg=CFG),
                                "2026-09-18", case_files_touched=True)
        assert not any("放宽" in r for r in v["reasons"]), (
            f"收紧口径被当成放宽（假红）：{v['reasons']}"
        )

    def test_live_baseline_declares_the_strict_metric(self):
        """数据面锁：生效清单必须写 `metric: entries`（防有人把口径悄悄改回宽松档）。"""
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        metric = data["burn_down"]["metric"]
        assert metric == "entries", (
            f"生效清单的口径是 {metric!r} —— 本次收紧要求 `entries`（只认整条销账）；"
            f"放宽回 `entries_or_codes` 会让「删一个码」重新算达标"
        )

    def test_report_shows_metric_in_the_headline(self):
        """报告必须打印生效口径（否则「按哪档判的」在报告里读不出来）。"""
        g = _gate_module()
        v = g.burn_down_verdict(_bd_baseline(2, cfg=CFG), _bd_baseline(2, cfg=CFG),
                                "2026-09-18", case_files_touched=True)
        text = g.render_report([], [], [], set(), [], budget=v)
        assert "metric=entries" in text, text[:400]


# ══════════════════════════════════════════════════════════════════════════════
# 五之四、未实装登记的**可执行约束**（本次收紧：字段 / 到期 / 僵尸 / 追踪单 CLOSED）
# ══════════════════════════════════════════════════════════════════════════════

class TestUnimplementedRegistrations:
    """四条判据都要能红（R5），每条配负例（R2），且「取不到」必须长得像「取不到」。

    病灶：`case-trust-unimplemented.json` 原来只有 `code/title/why_not/needs` ——
    **没有追踪号、没有到期日、没有「怎么算已实装」** ⇒ 「未实装」可以**永久**当借口。
    """

    def _g(self):
        return _gate_module()

    def _cases(self):
        return self._g().load_cases_from_dir()

    def _ctx(self, baseline=None):
        g = self._g()
        bl = baseline if baseline is not None else json.loads(
            BASELINE.read_text(encoding="utf-8"))
        return g.unimplemented_probe_context(self._cases(), bl)

    def _live_entries(self):
        return json.loads(UNIMPLEMENTED.read_text(encoding="utf-8"))["unimplemented"]

    # ── 负例：现行清单必须全绿（main 不许被自己的收紧判红）──────────────────
    def test_live_manifest_passes_all_judgements(self):
        v = tax.judge_unimplemented(self._live_entries(), today="2026-09-18",
                                    probe_context=self._ctx())
        assert v == [], f"现行未实装登记被判违规（收紧把 main 弄红了）：{v}"
        g = self._g()
        guard = g.judge_unimplemented_manifest(UNIMPLEMENTED, today="2026-09-18",
                                              cases=self._cases(),
                                              baseline=json.loads(
                                                  BASELINE.read_text(encoding="utf-8")),
                                              issue_check=False)
        assert not guard["blocking"], guard
        assert guard["sync"] == [], guard["sync"]

    # ── 红证 ①：缺任一字段 ⇒ 红，并指名缺哪个 ────────────────────────────────
    def test_missing_field_names_the_missing_field(self):
        entries = copy.deepcopy(self._live_entries())
        del entries[0]["issue"]
        v = tax.judge_unimplemented(entries, today="2026-09-18", probe_context=self._ctx())
        codes_hit = {x["code"] for x in v}
        assert tax.UNIMPLEMENTED_VIOLATION_CODES["MISSING_FIELD"]["code"] in codes_hit, v
        assert any("issue" in x["detail"] for x in v), (
            f"缺字段的报错必须**指名**缺哪个：{v}"
        )
        # 而**完整**的那几条不得被连坐（判据要能分辨自己红在哪）
        assert {x["entry"] for x in v} == {entries[0]["code"]}, v

    def test_blank_how_to_verify_is_a_missing_field(self):
        entries = copy.deepcopy(self._live_entries())
        entries[0]["how_to_verify"] = "   "  # 空串/空白 = 没写（不许用空值凑数）
        v = tax.judge_unimplemented(entries, today="2026-09-18", probe_context=self._ctx())
        assert any(x["code"] == tax.UNIMPLEMENTED_VIOLATION_CODES["MISSING_FIELD"]["code"]
                   and "how_to_verify" in x["detail"] for x in v), v

    def test_issue_must_be_a_positive_int(self):
        for bad in ("4045", 0, -3, True):
            entries = copy.deepcopy(self._live_entries())
            entries[0]["issue"] = bad
            v = tax.judge_unimplemented(entries, today="2026-09-18",
                                        probe_context=self._ctx())
            assert any(x["code"] == tax.UNIMPLEMENTED_VIOLATION_CODES["MISSING_FIELD"]["code"]
                       and "issue" in x["detail"] for x in v), (bad, v)

    # ── 红证 ②：expires 已过 ⇒ 红（非法/缺失按已到期处理）────────────────────
    def test_expired_registration_blocks(self):
        entries = copy.deepcopy(self._live_entries())
        entries[0]["expires"] = "2026-09-17"  # 昨天
        v = tax.judge_unimplemented(entries, today="2026-09-18", probe_context=self._ctx())
        assert any(x["code"] == tax.UNIMPLEMENTED_VIOLATION_CODES["EXPIRED"]["code"]
                   for x in v), f"到期未实装未判红（可以静默续期）：{v}"
        # 负例（R2）：到期日 = 今天之后 ⇒ 不得判红
        entries[0]["expires"] = "2026-09-19"
        v2 = tax.judge_unimplemented(entries, today="2026-09-18", probe_context=self._ctx())
        assert not any(x["code"] == tax.UNIMPLEMENTED_VIOLATION_CODES["EXPIRED"]["code"]
                       for x in v2), v2

    def test_malformed_expires_is_treated_as_expired(self):
        entries = copy.deepcopy(self._live_entries())
        entries[0]["expires"] = "下个月"  # 乱码 = 按已到期（fail-closed）
        v = tax.judge_unimplemented(entries, today="2026-09-18", probe_context=self._ctx())
        assert any(x["code"] == tax.UNIMPLEMENTED_VIOLATION_CODES["EXPIRED"]["code"]
                   for x in v), v
        assert tax.iso_date_or_expired("2026-13-45") == "0000-00-00"

    # ── 红证 ③：追踪单已 CLOSED ⇒ 红（网络格，注入 fetcher）──────────────────
    def test_closed_issue_blocks(self):
        g = self._g()
        entries = copy.deepcopy(self._live_entries())
        closed_no = entries[0]["issue"]
        res = g.check_unimplemented_issues(entries, fetcher=lambda n: (True, "closed")
                                           if n == closed_no else (True, "open"))
        assert [c["entry"] for c in res["closed"]] == [entries[0]["code"]], res
        assert res["unverifiable"] == [], res
        # 端到端（不碰网络）：把 fetcher 注入到外壳 → blocking
        guard = g.judge_unimplemented_manifest(
            UNIMPLEMENTED, today="2026-09-18", cases=self._cases(),
            baseline=json.loads(BASELINE.read_text(encoding="utf-8")),
            fetcher=lambda n: (True, "closed") if n == closed_no else (True, "open"))
        assert guard["blocking"], "追踪单已 CLOSED 却未阻塞（借口可以过期不销）"

    def test_missing_issue_number_is_blocking_too(self):
        """编号不存在（404 笔误）= 假借口 ⇒ 阻塞（否则 `issue: 1` 就能买永久豁免）。"""
        g = self._g()
        res = g.check_unimplemented_issues(self._live_entries(),
                                          fetcher=lambda n: (True, "missing"))
        assert len(res["closed"]) == len(self._live_entries()), res

    def test_unverifiable_issue_state_is_printed_not_passed(self):
        """三态照实读：取不到 ⇒ `unverifiable` + 报告打印「⏭️ 未跑判定 … 不是「通过」」。

        **不**因此判红（网络抖动/匿名限额不该制造假红），但**也不静默** ——
        断开网络就能绕过这条判据的口子，由「到期即红」「僵尸即红」两条零网络判据兜住。
        """
        g = self._g()
        guard = g.judge_unimplemented_manifest(
            UNIMPLEMENTED, today="2026-09-18", cases=self._cases(),
            baseline=json.loads(BASELINE.read_text(encoding="utf-8")),
            fetcher=lambda n: (False, "gh 未接线（夹具）"))
        assert not guard["blocking"], guard
        assert len(guard["unverifiable"]) == len(self._live_entries()), guard
        text = g.render_report([], [], [], set(), guard["entries"], unimpl_guard=guard)
        assert "⏭️ 未跑判定" in text and "不是「通过」" in text, text[-1200:]

    # ── 红证 ④：僵尸登记 ⇒ 红 ───────────────────────────────────────────────
    def test_zombie_registration_blocks(self):
        """口径已被修好/绕开 ⇒ 登记必须撤：探不到存活证据即红（否则永久留在清单里）。"""
        g = self._g()
        empty_ctx = g.unimplemented_probe_context([], {})   # 空用例库 + 空清单
        # drift 那条的口径在**别处**（`scripts/drift_audit.py`）⇒ 用「已复用统一对账」的
        # 源码文本把它一并置为不成立（否则本用例只证了 4/5 条探针会红）
        empty_ctx["drift_audit_source"] = "from case_trust_gate import reconcile_baseline"
        v = tax.judge_unimplemented(self._live_entries(), today="2026-09-18",
                                    probe_context=empty_ctx)
        zombies = [x for x in v if x["code"] == tax.UNIMPLEMENTED_VIOLATION_CODES["ZOMBIE"]["code"]]
        assert len(zombies) == len(self._live_entries()), (
            f"口径全不成立时仍不判僵尸：{v}"
        )
        assert all("探不到任何存活证据" in x["detail"] for x in zombies), zombies

    def test_unregistered_probe_is_a_zombie(self):
        """`hit_probe` 未注册 ⇒ 僵尸（不许用「探针永远为真」凑数）。"""
        entries = copy.deepcopy(self._live_entries())
        entries[0]["hit_probe"] = "always_true_please"
        v = tax.judge_unimplemented(entries, today="2026-09-18", probe_context=self._ctx())
        assert any(x["code"] == tax.UNIMPLEMENTED_VIOLATION_CODES["ZOMBIE"]["code"]
                   and "未注册" in x["detail"] for x in v), v

    def test_every_registered_probe_can_go_empty(self):
        """退化守卫：每条探针**在使用它的登记上**都必须能变空（否则判据不会红）。"""
        g = self._g()
        ctx_zombie = g.unimplemented_probe_context([], {})   # 空用例库 + 空清单
        ctx_zombie["drift_audit_source"] = "from case_trust_gate import reconcile_baseline"
        for item in tax.UNIMPLEMENTED:
            probe = tax.UNIMPLEMENTED_HIT_PROBES[item["hit_probe"]]
            assert probe(ctx_zombie) == [], (
                f"探针 {item['hit_probe']} 在「口径不成立」的上下文里仍非空 ⇒ 它不会红"
            )
            assert probe(self._ctx()) != [], (
                f"探针 {item['hit_probe']} 在现行库上为空 ⇒ 现行登记是僵尸（收紧会误红 main）"
            )
        # drift 探针在**读不到源码**时必须按存活处理（不许把「读不到」读成「已实装」）
        assert tax.UNIMPLEMENTED_HIT_PROBES["drift_audit_diff_scoped_stale"](
            {"cases": [], "baseline": {}, "drift_audit_source": None}), (
            "读不到 drift_audit 源码时被判成僵尸 ⇒ 会凭空判红别人的包（假红）"
        )

    def test_manifest_must_match_taxonomy(self):
        """登记清单必须与 `tax.UNIMPLEMENTED` **同源**（判据读的与人读的是一份）。"""
        g = self._g()
        entries = copy.deepcopy(self._live_entries())
        entries.append({**entries[0], "code": "FAKE-CODE-FOR-RED-PROOF"})
        issues = g.unimplemented_sync_issues(entries, tax.UNIMPLEMENTED)
        assert issues, "清单比 taxonomy 多一条却不同源报错 ⇒ 两处口径可静默分叉"
        assert "FAKE-CODE-FOR-RED-PROOF" in issues[0], issues

    def test_live_manifest_is_in_sync_with_taxonomy(self):
        """负例（R2）：现行两处必须同源（否则本包自己就先红了）。"""
        g = self._g()
        assert g.unimplemented_sync_issues(self._live_entries(), tax.UNIMPLEMENTED) == []

    # ── 端到端：真跑脚本、真退出码（函数级绿 ≠ CI 绿）────────────────────────
    def test_script_exits_1_on_missing_field_and_on_expired(self, tmp_path):
        live = json.loads(UNIMPLEMENTED.read_text(encoding="utf-8"))
        for i, (name, mutate, needle) in enumerate((
            ("缺 issue", lambda e: e.pop("issue"), "issue"),
            ("已到期", lambda e: e.update({"expires": "2026-09-17"}), "到期"),
        )):
            data = copy.deepcopy(live)
            mutate(data["unimplemented"][0])
            tmp = tmp_path / f"unimpl-{i}.json"
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            r = subprocess.run([sys.executable, str(GATE), "--base", "HEAD",
                                "--unimplemented", str(tmp), "--no-issue-check"],
                               capture_output=True, text=True, cwd=str(REPO_ROOT))
            assert r.returncode == 1, (
                f"「{name}」未让脚本 exit 1（假绿）：\nstdout={r.stdout[-1500:]}"
            )
            assert needle in r.stdout, f"「{name}」的报错未指名：\n{r.stdout[-1500:]}"
        # 负例（R2）：原样清单 ⇒ 必须 exit 0（收紧不得把现行登记判红）
        ok = subprocess.run([sys.executable, str(GATE), "--base", "HEAD",
                             "--unimplemented", str(UNIMPLEMENTED), "--no-issue-check"],
                            capture_output=True, text=True, cwd=str(REPO_ROOT))
        assert ok.returncode == 0, f"现行登记被判红：\n{ok.stdout[-2000:]}"

    def test_report_lists_the_contract_for_each_registration(self):
        """报告必须打印追踪单/到期/探针/存活证据（否则「为什么说它活着」无据可查）。"""
        g = self._g()
        guard = g.judge_unimplemented_manifest(
            UNIMPLEMENTED, today="2026-09-18", cases=self._cases(),
            baseline=json.loads(BASELINE.read_text(encoding="utf-8")), issue_check=False)
        text = g.render_report([], [], [], set(), guard["entries"], unimpl_guard=guard)
        for item in guard["entries"]:
            assert f"追踪单 #{item['issue']}" in text, text[-1500:]
            assert f"到期 {item['expires']}" in text, text[-1500:]
            assert f"僵尸判据 {item['hit_probe']}" in text, text[-1500:]
            assert "存活证据" in text and "怎么算已实装" in text, text[-1500:]
        # 「跑了」也要长得像「跑了」：核过 N 条全 OPEN 必须打印（否则与「压根没跑」同形）
        guard2 = g.judge_unimplemented_manifest(
            UNIMPLEMENTED, today="2026-09-18", cases=self._cases(),
            baseline=json.loads(BASELINE.read_text(encoding="utf-8")),
            fetcher=lambda n: (True, "open"))
        text2 = g.render_report([], [], [], set(), guard2["entries"], unimpl_guard=guard2)
        assert "追踪单状态已核" in text2 and "全部 **OPEN**" in text2, text2[-1200:]


# ══════════════════════════════════════════════════════════════════════════════
# 五之五、对账基准与被测对象对齐（本次纠偏：没碰受管面的 PR 不背别人的 prune）
# ══════════════════════════════════════════════════════════════════════════════

class TestReconcileBaseAlignment:
    """实测病灶（2026-09-18）：纯文档 PR 因 main 侧别人的 prune 被判「基线增长」= 假红。

    复现（`docs/4041-archive`，`--base origin/main`，分支零用例/零清单改动）：

    ```
    ❌ burn-down 预算（生效配置读 base(origin/main)）：…
       本次净变化：条目 135→135（+0），违规码 214→215（+1）
      · 基线**增长**了 … ⇒ 新增豁免（R4）
    ```

    判据与被测对象不对齐：分支里那份 215 码的清单是**它的分叉点状态**（一个字节没改），
    214 是 main 侧别人的 prune 结果。规则 = **未触碰受管面 ⇒ 基准取分叉点**；
    **触碰了 ⇒ 一律按 `origin/main` 比**（一个字不松）；生效**配置**永远取 `origin/main`。
    """

    def _g(self):
        return _gate_module()

    def test_touching_managed_surface_keeps_origin_main_baseline(self):
        """触碰用例库 / 豁免清单 ⇒ 基准仍是 `origin/main`（不许借此放宽）。"""
        g = self._g()
        main_base = {"violations": {"A": {"codes": ["X"]}}, "burn_down": CFG}
        for touched in ({"cases_dir": [".github/cases/x.yml"], "case_yml": [], "baseline": []},
                        {"cases_dir": [], "case_yml": [], "baseline":
                         [".github/case-trust-baseline.json"]}):
            base, name, note = g.select_reconcile_base("origin/main", touched, main_base)
            assert base is main_base, (touched, name, note)
            assert name == "base(origin/main)", name
            assert "触碰了受管面" in note, note

    def test_untouched_pr_compares_against_the_fork_point(self):
        """**红证 C②（改前红 / 改后绿）**：main 侧 prune 过清单，而本 PR 一个字节没改。

        · 改前：基准 = `origin/main`（被 prune 到更短）⇒ 分支那份「更大」⇒
          net 为负 ⇒ 报「基线**增长**了 ⇒ 新增豁免（R4）」⇒ 假红；
        · 改后：基准 = 分叉点那份（与分支自己的清单一致）⇒ net 0 ⇒ 不红。
        """
        g = self._g()
        fork = _bd_baseline(4, cfg=CFG)                       # 分叉点时 4 条
        branch = copy.deepcopy(fork)                          # 本 PR 没碰过它（照抄）
        pruned_main = _bd_baseline(3, cfg=CFG)                # main 侧别人 prune 掉 1 条

        before = g.burn_down_verdict(pruned_main, branch, "2026-09-18",
                                     case_files_touched=False)
        assert before["blocking"], (
            f"夹具前提：旧口径（基准=origin/main）应当因 main 侧 prune 判红（这才是假红）：{before}"
        )
        assert any("增长" in r for r in before["reasons"]), before["reasons"]

        after = g.burn_down_verdict(fork, branch, "2026-09-18", case_files_touched=False,
                                    config_baseline=pruned_main,     # 配置仍读 origin/main
                                    count_base="merge-base(deadbeef)")
        assert not after["blocking"], f"纠偏后仍判红（假红未修）：{after['reasons']}"
        assert after["net"]["entries"] == [4, 4] and after["net"]["codes"] == [4, 4], after["net"]
        assert after["source"] == "base(origin/main)", (
            f"生效配置必须仍读 origin/main（否则陈旧分支被按旧口径放行）：{after['source']}"
        )

    def test_fork_point_selection_uses_merge_base_when_untouched(self):
        """未触碰受管面 ⇒ 真的去读 `merge-base` 那份清单（不是嘴上说说）。"""
        g = self._g()
        base, name, note = g.select_reconcile_base(
            "HEAD", {"cases_dir": [], "case_yml": [], "baseline": []}, {"violations": {}})
        assert name.startswith("merge-base("), name
        assert "未触碰受管面" in note, note
        assert isinstance(base, dict) and base.get("violations"), (
            "分叉点清单没读到（返回了空/None ⇒ 判据会在空账本上静默通过）"
        )

    def test_merge_base_unavailable_falls_back_to_strict_and_says_so(self):
        """浅克隆取不到 merge-base ⇒ **退回严格口径**并说明（fail-closed，不偷偷放宽）。"""
        g = self._g()
        main_base = {"violations": {"A": {"codes": ["X"]}}, "burn_down": CFG}
        real = g.merge_base
        g.merge_base = lambda ref: None
        try:
            base, name, note = g.select_reconcile_base(
                "origin/main", {"cases_dir": [], "case_yml": [], "baseline": []}, main_base)
        finally:
            g.merge_base = real
        assert base is main_base and name == "base(origin/main)", (name, note)
        assert "取不到" in note and "fail-closed" in note, note

    def test_missing_fork_point_baseline_falls_back_to_strict(self):
        """分叉点上没有清单 ⇒ 退回严格口径（否则计数基准是空账本 ⇒「只许缩短」恒真）。"""
        g = self._g()
        main_base = {"violations": {"A": {"codes": ["X"]}}, "burn_down": CFG}
        real = g.load_base_baseline
        g.load_base_baseline = lambda ref: None
        try:
            base, name, note = g.select_reconcile_base(
                "origin/main", {"cases_dir": [], "case_yml": [], "baseline": []}, main_base)
        finally:
            g.load_base_baseline = real
        assert base is main_base and name == "base(origin/main)", (name, note)
        assert "退回严格口径" in note, note

    def test_deleting_an_entry_still_blocks_when_managed_surface_touched(self):
        """**红证 C①（证明没放宽）**：删掉清单里「仍在违规」的条目 ⇒ 触碰受管面 ⇒ 照旧红。

        这条是纠偏的**边界证明**：想靠删条目偷偷新增豁免，就必须动豁免清单
        ⇒ 一定落在「触碰受管面」那一侧 ⇒ 基准仍是 `origin/main` ⇒ `dropped` 照样阻塞。
        """
        g = self._g()
        v = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        assert codes(v), "夹具前提：PG-013 当下确有违规码"
        main_base = {"violations": {"PG-013": {"codes": sorted(codes(v))}}}
        base, name, _ = g.select_reconcile_base(
            "origin/main",
            {"cases_dir": [], "case_yml": [],
             "baseline": [".github/case-trust-baseline.json"]},   # 本 PR 删了条目 ⇒ 触碰
            main_base)
        assert name == "base(origin/main)"
        recon = g.reconcile_baseline({"violations": {}}, {"PG-013": v}, base)
        assert [d["case_id"] for d in recon["dropped"]] == ["PG-013"], recon
        assert recon["blocking"], "删掉仍在违规的条目未被阻塞（新增豁免无门禁）"

    def test_stale_and_unregistered_are_independent_of_the_base(self):
        """`stale` / `unregistered` **与基准无关**（只用分支自己那份 + 全库重算）⇒ 不因纠偏放松。

        三者分工：`stale`=记了却不再命中；`unregistered`=判出却没人记；`dropped`=记了却被删。
        前两条与「基准是谁」无关 ⇒ 纠偏只影响 `dropped`，而后者对「没改过清单的 PR」
        本来就**不可能**成立（它没法删掉自己没碰过的条目）。
        """
        g = self._g()
        v = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        baseline = {"violations": {"PG-013": {"codes": ["CASE-TRUST-NOT-A-REAL-CODE"]}}}
        recon = g.reconcile_baseline(baseline, {"PG-013": v}, None)
        assert recon["stale"], "陈旧条目（记的码不再命中）未被报出"
        assert recon["unregistered"], "全库判出但清单没有的码未被报出"
        assert recon["blocking"], "两条与基准无关的判据必须阻塞"


# ══════════════════════════════════════════════════════════════════════════════
# 五之六、派生读数（rule_counts / violation_case_count / case_total）必须**可修好**
# ══════════════════════════════════════════════════════════════════════════════

class TestDerivedReadings:
    """实测缺陷：`账本不自洽` 的报错指引指向 `--prune-baseline`，而它**修不好** ——
    旧实现在「无条目可删」时直接早退（不重算派生读数）⇒ 门禁照旧红，
    报错把人引到死路（排查 2 轮才发现该用 `--regen-baseline`）。

    修法：① 报错指向真能修好的入口；② `--prune-baseline` 在只删不加通道内**同时重算派生读数**；
    ③ 重算若会增长 ⇒ **拒绝写回**（fail-closed）。
    """

    def _g(self):
        return _gate_module()

    def _corrupt_in_memory(self) -> dict:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        rc = dict(data["rule_counts"])
        code = next(k for k, n in rc.items() if n > 0)
        rc[code] = rc[code] + 1                     # 只改派生读数，**不动事实**
        data["rule_counts"] = rc
        return data

    def test_integrity_blocks_on_stale_rule_counts(self):
        """红证 D①：派生读数与事实不一致 ⇒ **阻塞**（现状已红，这里锁住它不会退化）。"""
        g = self._g()
        recon = g.reconcile_baseline(self._corrupt_in_memory(), {})
        assert any("rule_counts 与 violations 不一致" in m for m in recon["integrity"]), recon
        assert recon["blocking"], "派生读数撒谎未阻塞（假读数）"

    def test_integrity_hint_points_to_a_command_that_fixes_it(self):
        """指引必须指向**能修好**的入口，并给出兜底（否则报错把人引到死路）。"""
        g = self._g()
        msg = g.reconcile_baseline(self._corrupt_in_memory(), {})["integrity"][0]
        assert g.PRUNE_COMMAND in msg, msg
        assert "会同时重算派生读数" in msg, msg
        assert g.REGEN_COMMAND in msg, msg

    def test_prune_recomputes_derived_readings_end_to_end(self, tmp_path):
        """红证 D②：真跑 `--prune-baseline` ⇒ **修好且不增长**（事实不变、读数归位）。"""
        tmp = tmp_path / "baseline.json"
        before = self._corrupt_in_memory()
        tmp.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
        gate = [sys.executable, str(GATE), "--base", "HEAD", "--baseline", str(tmp),
                "--no-issue-check"]
        red = subprocess.run(gate, capture_output=True, text=True, cwd=str(REPO_ROOT))
        assert red.returncode == 1, f"派生读数漂移未判红：\n{red.stdout[-1200:]}"
        assert "账本不自洽" in red.stdout, red.stdout[-1200:]

        fixed = subprocess.run([*gate, "--prune-baseline"], capture_output=True, text=True,
                               cwd=str(REPO_ROOT))
        assert fixed.returncode == 0, f"修复入口自己失败了：\n{fixed.stdout}\n{fixed.stderr}"
        assert "已重算派生读数" in fixed.stdout, fixed.stdout
        after = json.loads(tmp.read_text(encoding="utf-8"))
        assert after["violations"] == before["violations"], (
            "事实（violations）被改动了 —— 重算派生读数不得改变事实"
        )
        assert after["rule_counts"] == json.loads(
            BASELINE.read_text(encoding="utf-8"))["rule_counts"], "派生读数没归位"
        # ② 的加强版（用户裁定）：**逐键 diff 必须只落在三个纯派生字段上** ——
        # 口径（burn_down）与账本锚点（anchor_sha）**一个字都不许动**。
        assert after["burn_down"] == before["burn_down"], (
            f"重算派生读数夹带了口径变化：{before['burn_down']} → {after['burn_down']}"
        )
        assert after["anchor_sha"] == before["anchor_sha"], (
            f"重算派生读数夹带了锚点前移（{before['anchor_sha']} → {after['anchor_sha']}）"
            "—— 锚点前移是独立的语义变化，必须由 --regen-baseline 显式完成并打印"
        )
        changed_keys = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        assert changed_keys <= {"rule_counts", "violation_case_count", "case_total"}, (
            f"写回的键超出「纯派生字段」范围：{sorted(changed_keys)}"
        )
        assert "未改动 `burn_down` 与 `anchor_sha`" in fixed.stdout, fixed.stdout
        green = subprocess.run(gate, capture_output=True, text=True, cwd=str(REPO_ROOT))
        assert green.returncode == 0, f"修好后门禁仍红：\n{green.stdout[-1200:]}"

    def test_prune_refuses_to_write_when_recompute_would_grow(self):
        """红证 D③：重算若**会增长** ⇒ 拒绝写回（fail-closed；不许静默改变事实）。

        为什么用纯函数注入而不是端到端：`render_pruned_baseline` 只保留「既记了、现在仍命中」
        的码 ⇒ **构造上**不会增长。既然端到端造不出增长，就必须把守卫本身做成可注入的
        纯函数并单独证红 —— 否则这条守卫就是「基于口头保证的护栏」。
        """
        g = self._g()
        old = {"violations": {"A": {"codes": ["X"]}}, "case_total": 316}
        grown = {"violations": {"A": {"codes": ["X"]}, "B": {"codes": ["Y"]}}, "case_total": 316}
        assert g.derived_growth_guard(old, grown), "重算引入增长却未拒绝"
        assert g.derived_growth_guard(
            old, {"violations": {"A": {"codes": ["X", "Z"]}}, "case_total": 316}), "码数增长未被拒绝"
        assert g.derived_growth_guard(
            old, {"violations": {"A": {"codes": ["X"]}}, "case_total": 300}), (
            "case_total 变小（= 用例被删）未被拒绝"
        )
        # ③ 夹带语义变化同样必须拒绝：口径被改 / 锚点被推进（都不是「重算读数」）
        assert g.derived_growth_guard(
            {**old, "anchor_sha": "aaa"}, {**old, "anchor_sha": "bbb"}), (
            "anchor_sha 被推进却未拒绝（锚点前移会夹带在 chore 提交里悄悄发生）"
        )
        assert g.derived_growth_guard(
            {**old, "burn_down": {"per_pr_min": 1}}, {**old, "burn_down": {"per_pr_min": 0}}), (
            "burn_down 被改动却未拒绝"
        )
        # 负例（R2）：同量或收缩 ⇒ 不拦
        assert not g.derived_growth_guard(old, old)
        assert not g.derived_growth_guard(old, {"violations": {}, "case_total": 316})


# ══════════════════════════════════════════════════════════════════════════════
# 六、红证留档（防事后改写）
# ══════════════════════════════════════════════════════════════════════════════

class TestRedProofRecord:
    def test_red_proof_is_documented(self):
        assert REDPROOF.exists(), f"红证留档缺失：{REDPROOF}"
        text = REDPROOF.read_text(encoding="utf-8")
        for needle in ("补门禁之前", "补门禁之后", "RED-PROOF-BEFORE", "GREEN-PROOF-AFTER"):
            assert needle in text, f"红证留档缺少标记 {needle!r}"

    def test_red_proof_covers_every_rule_code(self):
        text = REDPROOF.read_text(encoding="utf-8")
        missing = [r["code"] for r in tax.RULES if r["code"] not in text]
        assert not missing, f"红证留档未覆盖这些规则码：{missing}"

    def test_unregistered_violation_blocks(self):
        """#4046：**未登记**违规（基线里没有、全库判出）必须**阻塞**（不再是「只报告」）。

        红证：把 `blocking` 改回 `bool(stale or dropped or integrity)` ⇒ 本用例红。
        翻转前置（存量未登记清零）：`#4078` 修 `PR-026` + 本 PR 修 `PR-025`/`PR-027`
        ⇒ 全库判出 == 清单条目数、未登记 0 条 —— 故此刻翻转不会误伤在飞 PR。
        """
        gate = _gate_module()
        v = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        assert codes(v), "夹具前提：该用例当下确有违规码"
        # 基线里**完全没有**这条用例 ⇒ 它判出的所有码都是「未登记」
        recon = gate.reconcile_baseline({"violations": {}}, {"PG-013": v})
        assert [u["case_id"] for u in recon["unregistered"]] == ["PG-013"], recon["unregistered"]
        assert recon["blocking"], (
            "未登记违规未被阻塞 —— 它会在基线外静默躺着（「不会红的判据」的另一形态）"
        )
        # 负例（R2）：全部违规都已如实入账 ⇒ **不得**判成未登记（否则全库永远红）
        recorded = {"violations": {"PG-013": {"codes": sorted({x["code"] for x in v})}}}
        recon2 = gate.reconcile_baseline(recorded, {"PG-013": v})
        assert recon2["unregistered"] == [], recon2["unregistered"]

    def test_report_says_unregistered_blocks(self):
        """报告口径必须与实现一致（不许留「只报告」这类假真值）。"""
        gate = _gate_module()
        v = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        recon = gate.reconcile_baseline({"violations": {}}, {"PG-013": v})
        text = gate.render_report([], [], recon["stale"], set(), list(tax.UNIMPLEMENTED),
                                  recon=recon)
        assert "未登记违规" in text and "阻塞" in text, text
        assert "只报告" not in text, "报告仍在说「只报告」= 与实现相反（假真值）"
