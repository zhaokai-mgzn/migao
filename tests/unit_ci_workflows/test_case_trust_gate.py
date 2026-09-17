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
        """未实装项必须写明**缺什么**（不得留空凑数）。"""
        assert tax.UNIMPLEMENTED, "未实装清单为空 —— 若确实全部落地，请显式说明"
        for item in tax.UNIMPLEMENTED:
            assert item.get("why_not") and item.get("needs"), f"未实装项缺理由/缺口：{item}"

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

    def test_gate_requires_baseline_pruning_only_for_diff_cases(self):
        """「已不再违规 ⇒ 必须移除」**只对本次 diff 涉及的用例**生效。

        为什么要这么窄：另一包正在修 CU-003/PG-013（#3832/#3833）。若对**全库**做
        陈旧比对，别人一修好，本门禁就会自己判红（假红），还会挡住他们的 PR。
        """
        gate = self._gate()
        baseline = {"violations": {"CU-003": {"codes": ["CASE-TRUST-NO-SELF-CLEAN"]},
                                  "PG-013": {"codes": ["CASE-TRUST-FORBIDDEN-TEXT-SOLE"]}}}
        # PG-013 被本次 PR 改了、且已不违规 ⇒ 必须要求从基线移除
        stale = gate.stale_baseline_entries(baseline, changed_ids={"PG-013"},
                                            violations_by_case={})
        assert [s["case_id"] for s in stale] == ["PG-013"], (
            f"diff 内已不再违规的项未被要求移除：{stale}"
        )
        assert stale[0]["hint"], "陈旧项必须带「怎么改」（指向重生成命令）"
        # CU-003 **不在**本次 diff 里（别人在修）⇒ 不得要求移除（避免误伤他人 PR）
        assert "CU-003" not in [s["case_id"] for s in stale], (
            "对不属本次 diff 的用例做了陈旧比对 —— 别人修好用例后门禁会自己判红"
        )

    def test_gate_does_not_prune_when_case_still_hits_recorded_code(self):
        """本次 diff 命中、且基线记的码仍命中 ⇒ 不走「陈旧移除」（未记录的新码由 classify 阻塞）。"""
        gate = self._gate()
        # PG-013 夹具当下同时报 NO-EFFECT 与 NO-SELF-CLEAN；基线只记了后者
        baseline = {"violations": {"PG-013": {"codes": ["CASE-TRUST-NO-SELF-CLEAN"]}}}
        v = tax.judge_case(fixture_pg_013(), catalog=_seed_catalog())
        assert "CASE-TRUST-NO-SELF-CLEAN" in codes(v), "夹具前提：应命中 NO-SELF-CLEAN"
        stale = gate.stale_baseline_entries(baseline, changed_ids={"PG-013"},
                                            violations_by_case={"PG-013": v})
        assert stale == [], f"仍命中原记码的用例被当成陈旧项：{stale}"
        # 而未记录的 NO-EFFECT 必须由 classify 阻塞
        verdict = gate.classify([{"case_id": "PG-013", "violations": v}], baseline=baseline)
        blocked = {x["code"] for b in verdict["blocking"] for x in b["violations"]}
        assert "CASE-TRUST-NO-EFFECT-ASSERTION" in blocked, (
            "未记录在基线里的违规码未阻塞（假绿）"
        )

    def test_gate_prunes_when_recorded_code_no_longer_hits(self):
        """「修好一条、又犯另一条」⇒ 原记码不再命中 ⇒ 必须重生成基线（清单只许缩短）。

        形态取自并发包修 CU-003 的可能结果：标签名改对了（PRECLEAN 码消失），
        但仍缺效果层断言（NO-EFFECT 是新码）—— 基线条目陈旧 + 新码阻塞，两者都要报。
        """
        gate = self._gate()
        baseline = {"violations": {"CU-003": {
            "codes": ["CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE"]}}}
        v = tax.judge_case(fixture_cu_003(), catalog=_seed_catalog())
        # 先确认夹具当下确实还报 PRECLEAN 码；把标签名改对后再判
        fixed = copy.deepcopy(fixture_cu_003())
        fixed["pre_clean"][0]["tag_name"] = "VIP2"
        v = tax.judge_case(fixed, catalog=_seed_catalog())
        assert "CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE" not in codes(v)
        stale = gate.stale_baseline_entries(baseline, changed_ids={"CU-003"},
                                            violations_by_case={"CU-003": v})
        assert [s["case_id"] for s in stale] == ["CU-003"], (
            f"原记码不再命中却未报「可缩短清单」：{stale}"
        )
        assert stale[0]["removed_codes"] == ["CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE"]
        assert stale[0]["hint"], "可缩短项必须带「怎么改」（指向重生成命令）"

    def test_stale_baseline_entry_does_not_block(self):
        """**红线（防假红）**：陈旧基线条目只**告警**，不得阻塞 —— 否则会把
        「修好用例」的人卡在 `.github/case-trust-baseline.json`（非其所有权的文件）上，
        而该文件可能正被**在飞**的基线重生成改动持有（实证：#3832/#3833 正在修
        CU-003/PG-013，基线文件同时被本门禁的 PR 创建）。

        判据：报告在「仅有陈旧项、无新增违规」时必须出现**可缩短/不阻塞本次**，
        且**不得**出现阻塞结论 —— 退出码层面由 `main()` 只按 `blocking` 决定（见上一条）。
        """
        gate = self._gate()
        report = gate.render_report(blocking=[], passed=[], stale=[
            {"case_id": "PG-013", "removed_codes": ["CASE-TRUST-NO-SELF-CLEAN"],
             "now_codes": [], "hint": "hint"}],
            changed_ids={"PG-013"}, unimplemented=[])
        assert "不阻塞本次" in report, f"陈旧项未标明「不阻塞」：{report[:400]}"
        assert "可缩短" in report
        assert "❌ 阻塞" not in report, "仅有陈旧项时报告不得判阻塞"
        assert "✅ 通过" in report

    def test_unimplemented_manifest_records_baseline_pruning_limitation(self):
        """机制现状必须照实登记：清单缩短**没有机械强制**（只告警）。

        为什么钉住：`migao-acceptance`「注释漂移 = 假绿来源」—— 若文档/清单声称
        「清单只许缩短」是**强制**的，而实现只是告警，那就是一句会误导后来者的假真值。
        """
        assert UNIMPLEMENTED.exists(), f"未实装清单缺失：{UNIMPLEMENTED}"
        text = UNIMPLEMENTED.read_text(encoding="utf-8")
        assert ("不能机械强制" in text or "无机械强制" in text or "只告警" in text), (
            "未实装清单没有登记「基线缩短无机械强制」—— 会让人误以为它是强制的"
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
