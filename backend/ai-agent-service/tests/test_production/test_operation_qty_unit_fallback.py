"""应做数量的两处边界（issue #4228）——「未知单位」与「非正数」都不许静默变成真值。

病根（两处都在 `backend/ai-agent-service/app/production/routing.py`）：
① **未知单位静默走「米」分支**：`_qty_for` 的收尾一行是无条件 `_pick(METER_KEYS, 1)`（注释写「米」），
   于是 `帘头制作`（`unit=个`）喂 `{fabric_meters: 12.3}` 算出 **12.3 个**（实测）——
   而端点层 `qty_and_source` 对同一输入给 1.0 ⇒ 值/标签**分叉**，「唯一算料真相源」当场不成立；
② **`_pick` 认显式 0**：`{fabric_meters: 0}` ⇒ `qty=0.0`（标签还报 `fabric_meters` ⇒ 冒称
   「该键直接供数」）⇒ `done_qty ≥ qty` 恒真 ⇒ 工序一开始就算完成（**假完工**）。

裁定（用户 2026-09-25，见 #4228 / #5496）：
① 「个 / 件」类单位**归固定值 1**并**显式登记**（`FIXED_ONE_UNITS`）为「引擎不产出该量 ⇒ 兜底 1」。
   ⚠️ 这是**兜底口径、不是真值**：真值源 `docs/curtain-production-rules.md` §4（计件）没给「个」的
   数量口径，§2 只把「个 / 件」列进单位取值域 ⇒ 一「个」是多少**本仓无从判定**（待客户确认）；
② `_qty_for` 对**非正数**（含 `0` 与负数）一律**兜底 1**，与 docstring 红线「缺键一律兜底 1、绝不落 0」一致；
③ 两处都必须与 #4208 端点层**已有的三态 `qty_source` 口径**一致（键名 / `<键名>_x6` / `fallback`）
   —— **不新造第二套来源标记**：值一律由 `_qty_for` 给出，标签只在「真有键供数」时报键名。

红证（改前实跑 = **真断言失败**，非收集失败；逐字读数见 PR body，被测 commit `4d3141080`）：
- ① `_qty_for("帘头制作", {"fabric_meters": 12.3})` ⇒ 改前 `12.3`（`assert 12.3 != 12.3` 红）；
- ② `qty_and_source("精裁-布", {"fabric_meters": 0})` ⇒ 改前 `(0.0, "fabric_meters")`
  （`assert (0.0, 'fabric_meters') == (1.0, 'fallback')` 红）。

类级固化（AGENTS.md 第 8 条：修一处 ≠ 修一类）：
- `TestQtyForAndLabelAgree` —— **逐工序 × 逐 calc_info** 普查「值 = 直调 `_qty_for`」+「标签 ∈ 三态」+
  「报 fallback ⇔ 值为兜底 1」。改前 `帘头制作` 就是分叉形态（值 12.3 / 标签 fallback）⇒ 本类红；
- `TestUnitRegistrationCensus` —— `OPERATION_CATALOG` 出现的**每个**单位都必须登记
  （`KNOWN_QTY_UNITS` 有口径 / `FIXED_ONE_UNITS` 兜底 1），**未登记即红**；登记为兜底的单位
  **不得**有候选键；未登记单位的行为本身仍 fail-safe（兜底 1）。
"""
# case_ids: PP-012

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.production.routing import (
    DIRECT_QTY_KEYS,
    FIXED_ONE_UNITS,
    HOLE_ESTIMATE_SUFFIX,
    HOLE_KEYS,
    HOLE_PER_METER,
    KNOWN_QTY_UNITS,
    OPERATION_CATALOG,
    _qty_for,
    _qty_keys_for_unit,
    qty_and_source,
)

ENDPOINT = "/api/internal/production/operation-qty"

#: 「个 / 件」类（引擎不产出数量的单位）在库里的**实际**工序（改前全部按米算出 12.3 个）
FIXED_ONE_OPERATIONS = tuple(
    op for op, meta in OPERATION_CATALOG.items() if meta["unit"] in FIXED_ONE_UNITS
)

#: 普查用的 calc_info（覆盖米/折/孔/幅/套各候选键 + 空 + 兼容别名 + 非正数）
CALC_INFOS = (
    {},
    {"fabric_meters": 12.3},
    {"meters": 12.3},
    {"pleat_count": 24},
    {"holes": 72},
    {"panels": 2},
    {"set_count": 1},
    {"fabric_meters": 0},
    {"pleat_count": 0},
    {"holes": 0, "fabric_meters": 12.3},
    {"fabric_meters": -5},
)

#: 三态 `qty_source` 的合法取值（键名 / `<键名>_x6` / fallback）——**不新造第二套来源标记**
ALLOWED_SOURCES = (
    set(DIRECT_QTY_KEYS)
    | {"holes", "fallback", "panels", "set_count", "meters"}
    | {f"{key}{HOLE_ESTIMATE_SUFFIX}" for key in ("fabric_meters", "meters")}
)


@pytest.fixture
def client():
    """本地 TestClient（同 `test_operation_qty.py`：只 patch 实际存在的生命周期依赖）。"""
    from fastapi.testclient import TestClient

    with patch("app.utils.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.database.close_db", new_callable=AsyncMock), \
         patch("app.utils.redis_client.init_redis", new_callable=AsyncMock), \
         patch("app.utils.redis_client.close_redis", new_callable=AsyncMock):
        from app.main import create_app
        with TestClient(create_app()) as c:
            yield c


def _post(client, positions, token=settings.SERVICE_TOKEN):
    headers = {} if token is None else {"X-Service-Token": token}
    return client.post(ENDPOINT, headers=headers, json={"positions": positions})


def _first_position(resp):
    body = resp.json()
    assert body["success"] is True
    return body["data"]["positions"][0]


# ══════════════════════════════════════════════════════════════════════════
# ① 未知单位（「个 / 件」）：固定 1，**不再静默落到「米」分支**
# ══════════════════════════════════════════════════════════════════════════

class TestUnknownUnitNeverFallsIntoMeterBranch:

    def test_ge_unit_operation_is_one_not_fabric_meters(self):
        """**红证 ①**：`帘头制作` + `{fabric_meters: 12.3}` ⇒ **不是** 12.3 个（改前实测 12.3）。"""
        qty = _qty_for("帘头制作", {"fabric_meters": 12.3})
        assert qty != 12.3, f"「个」类工序按米算出了 {qty} 个 ⇒ 仍静默走「米」分支"
        assert qty == 1.0

    def test_every_fixed_one_operation_is_one(self):
        """库里所有「个 / 件」类工序：任何 calc_info 下都恒 1（没有「按米折算」这一说）。"""
        assert FIXED_ONE_OPERATIONS, "前提不成立：库里没有「个 / 件」类工序，本用例失去对象"
        for operation in FIXED_ONE_OPERATIONS:
            for calc_info in CALC_INFOS:
                assert _qty_for(operation, calc_info) == 1.0, (
                    f"{operation}（{OPERATION_CATALOG[operation]['unit']}）"
                    f" 在 {calc_info} 下应兜底 1"
                )

    def test_label_is_fallback_not_a_key_name(self):
        """登记为「引擎不产出」的单位 ⇒ 标签恒 `fallback`（**不得**冒称某键直接供数）。"""
        for operation in FIXED_ONE_OPERATIONS:
            assert qty_and_source(operation, {"fabric_meters": 12.3}) == (1.0, "fallback")

    def test_endpoint_reports_one_and_fallback(self, client):
        """端点层反向护栏（改前已绿）：HTTP 200 + 1.0 + fallback —— 修复不得把它改坏。"""
        resp = _post(client, [{
            "position_name": "帘头",
            "operations": ["帘头制作"],
            "calc_info": {"fabric_meters": 12.3},
        }])
        assert resp.status_code == 200
        pos = _first_position(resp)
        assert pos["qty_by_operation"] == {"帘头制作": 1.0}
        assert pos["qty_source_by_operation"] == {"帘头制作": "fallback"}


# ══════════════════════════════════════════════════════════════════════════
# ② 非正数（显式 0 / 负数）：一律兜底 1，标签如实报 fallback
# ══════════════════════════════════════════════════════════════════════════

class TestNonPositiveQtyFallsBackToOne:

    def test_zero_fabric_meters_is_one_not_zero(self):
        """**红证 ②**：`{fabric_meters: 0}` ⇒ `(1.0, "fallback")`（改前 `(0.0, "fabric_meters")`）。"""
        assert qty_and_source("精裁-布", {"fabric_meters": 0}) == (1.0, "fallback")
        assert _qty_for("精裁-布", {"fabric_meters": 0}) == 1.0

    def test_negative_fabric_meters_is_one(self):
        """负数同理（数量没有负值这个取值；负值入账比 0 更糟）。"""
        assert qty_and_source("精裁-布", {"fabric_meters": -5}) == (1.0, "fallback")
        assert _qty_for("精裁-布", {"fabric_meters": -5}) == 1.0

    def test_zero_pleat_count_is_one(self):
        """「折」类（韩褶）：显式 0 褶 ⇒ 兜底 1（**不是** 0 折 ⇒ 假完工）。"""
        assert qty_and_source("韩褶-布", {"pleat_count": 0}) == (1.0, "fallback")

    def test_zero_panels_and_set_count_are_one(self):
        """「幅」/「套」类（引擎待补键）：显式 0 ⇒ 兜底 1。"""
        assert qty_and_source("拼1次-布", {"panels": 0}) == (1.0, "fallback")
        assert qty_and_source("外帘装袋", {"set_count": 0}) == (1.0, "fallback")

    def test_zero_holes_falls_through_to_estimate_or_one(self):
        """「孔」类的 0 孔视同缺键：退到「按米估算」②（有米数）或真兜底 ③（无米数）。"""
        assert qty_and_source("打孔-布", {"holes": 0, "fabric_meters": 12.3}) == (
            12.3 * HOLE_PER_METER, f"fabric_meters{HOLE_ESTIMATE_SUFFIX}",
        )
        assert qty_and_source("打孔-布", {"holes": 0}) == (1.0, "fallback")
        assert qty_and_source("打孔-布", {"holes": 0, "meters": 0}) == (1.0, "fallback")

    def test_key_order_still_skips_to_next_usable_key(self):
        """首个键非正数 ⇒ 读下一个可用键（双读兼容不得因加正数判据而失效）。"""
        assert qty_and_source("精裁-布", {"fabric_meters": 0, "meters": 4.5}) == (4.5, "fallback")

    def test_endpoint_zero_is_never_done_qty(self, client):
        """端点层：`{fabric_meters: 0, pleat_count: 0}` ⇒ 全 1.0 + fallback（HTTP 仍 200）。"""
        resp = _post(client, [{
            "position_name": "布艺遮光帘A 米白",
            "operations": ["精裁-布", "韩褶-布"],
            "calc_info": {"fabric_meters": 0, "pleat_count": 0},
        }])
        assert resp.status_code == 200
        pos = _first_position(resp)
        assert pos["qty_by_operation"] == {"精裁-布": 1.0, "韩褶-布": 1.0}
        assert pos["qty_source_by_operation"] == {"精裁-布": "fallback", "韩褶-布": "fallback"}


# ══════════════════════════════════════════════════════════════════════════
# 类级固化 A：值（`_qty_for`）与标签（三态）**逐工序 × 逐 calc_info 不得分叉**
#
# 改前的分叉形态：`帘头制作` 值 12.3（走米分支）/ 标签 fallback（无候选键）——
# 两个字段各说各话，「唯一算料真相源」当场不成立。本条即那次分叉的类级判据。
# ══════════════════════════════════════════════════════════════════════════

class TestQtyForAndLabelAgree:

    @pytest.mark.parametrize("calc_info", CALC_INFOS, ids=lambda c: "+".join(sorted(c)) or "empty")
    def test_value_always_equals_qty_for(self, calc_info):
        for operation in sorted(OPERATION_CATALOG):
            qty, _source = qty_and_source(operation, calc_info)
            assert qty == _qty_for(operation, calc_info), (
                f"{operation} 在 {calc_info} 下端点值与直调 `_qty_for` 分叉 ⇒ 存在第二份算料逻辑"
            )

    @pytest.mark.parametrize("calc_info", CALC_INFOS, ids=lambda c: "+".join(sorted(c)) or "empty")
    def test_label_is_one_of_the_three_states(self, calc_info):
        for operation in sorted(OPERATION_CATALOG):
            _qty, source = qty_and_source(operation, calc_info)
            assert source in ALLOWED_SOURCES, f"{operation} 报了未登记的来源标记 {source}"

    def test_no_census_value_is_non_positive(self):
        """**任何**来源标记下值都必须 > 0：数量没有「0 / 负」这个取值。

        两个方向一并钉住：改前 `{fabric_meters: 0}` ⇒ 值 0.0 却报 `fabric_meters`
        （把无效值冒称「该键直接供数」，issue #4228 ②）⇒ 本断言红。

        ⚠️ **不要**把判据写成「报 fallback ⇒ 值必为 1.0」：`meters` 是**兼容别名**
        （引擎不产出，见 `METER_KEYS` 注释），它供数时报的正是 fallback 且值是真米数
        （`({"meters": 12.3})` ⇒ `(12.3, "fallback")`，`test_operation_qty.py` 的
        `test_value_and_label_are_decoupled` 逐字钉住）—— 那条形态是**有意**的，不是缺陷。
        """
        for operation in sorted(OPERATION_CATALOG):
            for calc_info in CALC_INFOS:
                qty, source = qty_and_source(operation, calc_info)
                assert qty > 0, f"{operation} 在 {calc_info} 下给出非正数 {qty}（来源 {source}）"


# ══════════════════════════════════════════════════════════════════════════
# 类级固化 B：单位登记普查（新单位进不来）
#
# 判据 = `OPERATION_CATALOG` 出现的每个单位都必须在**两份登记表之一**里：
#   · `KNOWN_QTY_UNITS` = 引擎有数量口径（`_qty_for` 有分支 + `_qty_keys_for_unit` 有候选键）
#   · `FIXED_ONE_UNITS` = 引擎不产出该量 ⇒ **兜底 1**（有意为之，不是忘了建分支）
# 新工序带来未登记单位 ⇒ 红（不许再有第三个静默分支）。
# ══════════════════════════════════════════════════════════════════════════

class TestUnitRegistrationCensus:

    def test_every_catalog_unit_is_registered(self):
        units = {meta["unit"] for meta in OPERATION_CATALOG.values()}
        unregistered = units - set(KNOWN_QTY_UNITS) - set(FIXED_ONE_UNITS)
        assert unregistered == set(), (
            f"未登记单位 {sorted(unregistered)} —— 请在 KNOWN_QTY_UNITS（引擎有口径）"
            f"或 FIXED_ONE_UNITS（引擎不产出 ⇒ 兜底 1）里显式登记"
        )

    def test_two_registries_are_disjoint(self):
        assert set(KNOWN_QTY_UNITS) & set(FIXED_ONE_UNITS) == set()

    def test_fixed_one_units_have_no_candidate_keys(self):
        """登记为「引擎不产出」的单位**不得**有候选键（有键 ⇒ 两处口径再次分叉）。"""
        for unit in FIXED_ONE_UNITS:
            assert _qty_keys_for_unit(unit) == (), f"{unit} 不该有候选键"

    def test_known_units_all_have_candidate_keys(self):
        for unit in KNOWN_QTY_UNITS:
            assert _qty_keys_for_unit(unit) != (), f"{unit} 缺候选键"

    def test_hole_keys_are_the_only_extra_candidate_key(self):
        """「孔」的候选键 = `holes` + 米数键（按米估算那一路）；其余单位只用本单位的键。"""
        assert _qty_keys_for_unit("孔") == HOLE_KEYS + ("fabric_meters", "meters")

    def test_unregistered_unit_also_falls_back_to_one(self, monkeypatch):
        """**未登记**的单位同样兜底 1（登记只为可区分，行为本身 fail-safe）。"""
        monkeypatch.setitem(
            OPERATION_CATALOG, "假工序-未登记单位", {"group": "其他", "unit": "打", "unit_price": 0.0},
        )
        assert _qty_for("假工序-未登记单位", {"fabric_meters": 12.3}) == 1.0
        assert qty_and_source("假工序-未登记单位", {"fabric_meters": 12.3}) == (1.0, "fallback")


# ══════════════════════════════════════════════════════════════════════════
# 类级固化 C：真值源**显式登记**（条目被删 / 单位漂移 / 现取读数腐烂 ⇒ 红）
#
# 病根（issue #4228 的收尾项，关联 #5496「新增·C」）：这条口径此前**只写在代码注释里** ——
# 真值源 `docs/curtain-production-rules.md` §4「数量口径」清单里没有它 ⇒「登记在」与
# 「登记被删」在数据上**不可区分**（代码注释不会被任何判据读；`migao-dev-flow` §23.12①）。
# 本条把三件事钉成一条判据：
#   ① §4 有该口径的登记条目；② 条目里的单位集合 == 代码登记表 `FIXED_ONE_UNITS`（双向）；
#   ③ 条目里的**现取读数** == 由 `OPERATION_CATALOG` 现算的条数（数字腐烂即红，不靠人记得）。
# 与 `TestUnitRegistrationCensus`（管**代码侧**：新单位必须进登记表）互补。
# ══════════════════════════════════════════════════════════════════════════

REPO_ROOT = Path(__file__).resolve().parents[4]
TRUTH_SOURCE = REPO_ROOT / "docs" / "curtain-production-rules.md"
TRUTH_SECTION_HEADING = "## 4. 计件（工资计算）"
REGISTRY_LITERAL = re.compile(r"FIXED_ONE_UNITS\s*=\s*\(([^)]*)\)")
CENSUS_READING = re.compile(r"`unit=([^`]+)`\s*\**(\d+)\**\s*道")
REQUIRED_WORDS = ("兜底 1", "禁止", "fabric_meters", "KNOWN_QTY_UNITS")


def _truth_section(text: str) -> str:
    """真值源 §4 的正文（到下一个 `## ` 标题为止）；节缺失 ⇒ 空串（由判据报红）。"""
    start = text.find(TRUTH_SECTION_HEADING)
    if start < 0:
        return ""
    rest = text[start + len(TRUTH_SECTION_HEADING):]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def _registration_bullet(section: str) -> str:
    """§4 里**登记该口径**的那一条 bullet（含登记表符号 `FIXED_ONE_UNITS`）。"""
    hits = [b for b in re.split(r"\n(?=- )", section) if "FIXED_ONE_UNITS" in b]
    assert len(hits) == 1, (
        f"真值源 §4 必须**恰好一条**条目提到 `FIXED_ONE_UNITS`，实得 {len(hits)} 条 —— "
        f"0 条 = 口径仍只在代码注释里（issue #4228 收尾项未落）；多条 = 两份真值源。"
    )
    return hits[0]


def _check_truth_source_registration(text: str) -> None:
    """真值源登记面的**唯一判据**：三处任一漂移 ⇒ AssertionError（消息给可行动出口）。"""
    bullet = _registration_bullet(_truth_section(text))

    literals = REGISTRY_LITERAL.findall(bullet)
    assert len(literals) == 1, (
        f"登记条目必须**恰好一处**写出代码侧登记表的字面赋值（`FIXED_ONE_UNITS = (…, …)`），"
        f"实得 {len(literals)} 处（0 处 = 无从机器比对；多处 = 两份登记）—— 当前条目开头：{bullet[:100]!r}"
    )
    registered = tuple(re.findall(r'"([^"]+)"', literals[0]))
    assert registered == tuple(FIXED_ONE_UNITS), (
        f"真值源登记的单位 {registered} 与代码登记表 {tuple(FIXED_ONE_UNITS)} 不一致 ⇒ "
        f"两侧必须逐值相同（改登记表就**同批**改真值源 §4）"
    )

    for word in REQUIRED_WORDS:
        assert word in bullet, (
            f"登记条目缺「{word}」—— 口径（兜底 1）/ 禁令（禁止按米读 `fabric_meters`）/ "
            f"另一侧登记表（`KNOWN_QTY_UNITS`）缺一即不可执行"
        )

    readings = {unit: int(count) for unit, count in CENSUS_READING.findall(bullet)}
    actual = {unit: sum(1 for meta in OPERATION_CATALOG.values() if meta["unit"] == unit)
              for unit in FIXED_ONE_UNITS}
    assert readings == actual, (
        f"真值源现取读数 {readings} 与 `OPERATION_CATALOG` 现算 {actual} 不一致 ⇒ "
        f"把 §4 登记条目里的 `unit=<单位> N 道` 改成现算值（读数是**现取**的，不许写死不动）"
    )


class TestTruthSourceRegistration:
    """**登记面**判据：口径必须落在真值源里，而不是只躺在代码注释里（issue #4228 收尾项）。"""

    def test_section4_registration_is_intact(self):
        """绿证：真值源 §4 的登记条目与代码登记表 / 工序库现算值三向一致。"""
        assert TRUTH_SOURCE.is_file(), f"真值源不存在：{TRUTH_SOURCE}"
        _check_truth_source_registration(TRUTH_SOURCE.read_text(encoding="utf-8"))

    def test_injected_missing_registration_is_red(self):
        """**自证①**：删掉登记条目（= 退回「只在代码注释里」）⇒ 判据必须红。"""
        text = TRUTH_SOURCE.read_text(encoding="utf-8")
        crippled = text.replace(_registration_bullet(_truth_section(text)), "- 【默】口径未登记。")
        assert crippled != text, "变异注入未生效（文本逐字未变）⇒ 本自证无判别力"
        with pytest.raises(AssertionError) as excinfo:
            _check_truth_source_registration(crippled)
        assert "FIXED_ONE_UNITS" in str(excinfo.value)

    def test_injected_unit_drift_is_red(self):
        """**自证②**：条目里的单位集合少写一个 ⇒ 必须红（防「登记表改了、真值源没跟」）。"""
        text = TRUTH_SOURCE.read_text(encoding="utf-8")
        crippled = REGISTRY_LITERAL.sub(f'FIXED_ONE_UNITS = ("{FIXED_ONE_UNITS[0]}")', text, count=1)
        assert crippled != text, "变异注入未生效（文本逐字未变）⇒ 本自证无判别力"
        with pytest.raises(AssertionError) as excinfo:
            _check_truth_source_registration(crippled)
        assert "不一致" in str(excinfo.value)

    def test_injected_census_drift_is_red(self):
        """**自证③**：现取读数被写死成别的数字 ⇒ 必须红（读数只能来自现算）。"""
        text = TRUTH_SOURCE.read_text(encoding="utf-8")
        crippled = CENSUS_READING.sub(
            lambda m: f"`unit={m.group(1)}` **{int(m.group(2)) + 1}** 道", text, count=1,
        )
        assert crippled != text, "变异注入未生效（文本逐字未变）⇒ 本自证无判别力"
        with pytest.raises(AssertionError) as excinfo:
            _check_truth_source_registration(crippled)
        assert "现取读数" in str(excinfo.value)

    def test_injected_meter_fallback_permission_is_red(self):
        """**自证④**：删掉「禁止按米折算」⇒ 必须红（只登记单位名 ≠ 登记了口径）。"""
        text = TRUTH_SOURCE.read_text(encoding="utf-8")
        crippled = text.replace("禁止", "允许")
        assert crippled != text, "变异注入未生效（文本逐字未变）⇒ 本自证无判别力"
        with pytest.raises(AssertionError) as excinfo:
            _check_truth_source_registration(crippled)
        assert "禁止" in str(excinfo.value)