# case_ids: OR-016, OR-011
"""order_create 规格键族 ↔ 服务端库存匹配读取点（跨语言契约，issue #4090）。

**红证（issue #4090）**：唯一生产者 `order_create` 只能产出**字符串族**
（`skuCode/colorName/sellingMethod/doorWidth` —— `product_detail._format_skus` 既不返回
`color_id` 也不返回 `skuId`），而服务端 `OrderService.matchSkuId` 原先只认 **ID 族**
（`skuId`，或 `colorId+sellingMethod+doorWidth`）⇒ **键族不相交** ⇒ 库存校验 / 扣减 / 销量
三处同时静默跳过（顾客下单成功、SKU 库存不动、销量不涨、无任何失败信号）。

修法两侧同时收口：
1. **服务端**（Java）：`matchSkuId` 改读字符串族（`product_skus.sku_code / color_name` 就是
   同一行上的原值），并把「声明了 SKU 身份却定位不到」改成**显式拒绝**（fail-closed）；
2. **工具侧**（本文件锁的）：把模型**真能拿到**的 ID 族键 `skuId`（`product_detail` 的
   `skus[].id`）在 schema 里声明出来并教模型优先传它 —— 原先 schema 声明的 `colorId`
   在 `product_detail` 里**根本不存在**（模型只能臆造），既是幻觉源也让 ID 族不可达。

判据（零 LLM / 零网络）：
- ① **键族必须相交**：至少一个 SKU 身份键既由工具产出、又被服务端读取（不相交 ⇒ 红）；
- ② **声明的键必须可得**：能在 `product_detail` 输出里找到取值来源（`colorId` 是唯一例外，
  必须在描述里显式标明「product_detail 不返回」）；
- ③ **负例**：两侧任一退回修前形态（服务端只读 ID 族 / schema 不声明 `skuId` / 声明拿不到的键）
  ⇒ 判据必红（证明这条判据不会永远绿）。

Java 解析口径复用既有跨端契约测试的 `_method_body`（不造第三套）。
"""
from __future__ import annotations

import ast
import copy
import re
from pathlib import Path

from app.tools.order_create import OrderCreateTool

from tests.test_employee_field_consumption_contract import _method_body

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ORDER_SERVICE = _REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java"
_PRODUCT_DETAIL = _REPO_ROOT / "backend/ai-agent-service/app/tools/product_detail.py"
_ORDER_CREATE_SRC = _REPO_ROOT / "backend/ai-agent-service/app/tools/order_create.py"

# 规格键（`processing_info` 内的销售规格字段，不含加工项/加工费）
_SPEC_KEYS = ("skuId", "skuCode", "colorId", "colorName", "sellingMethod", "doorWidth")
# SKU 身份键：能指名「选了哪个 SKU」的键（属性键单独出现不能定位 SKU）
_IDENTITY_KEYS = ("skuId", "skuCode", "colorId", "colorName")
# 属性键：售卖方式 / 门幅（服务端按 SkuNotation 归一化比较）
_ATTRIBUTE_KEYS = ("sellingMethod", "doorWidth")
# product_detail `_format_skus` 输出键 → `processing_info` 规格键（工具描述里承诺的取值来源）
_PRODUCT_DETAIL_SOURCES = {
    "sku_code": "skuCode",
    "color_name": "colorName",
    "selling_method": "sellingMethod",
    "door_width": "doorWidth",
    "id": "skuId",
}
# product_detail 不返回、因此**不可得**的键（Agent 路径不得教模型去填）——描述里必须显式标注
_UNOBTAINABLE = {"colorId": "product_detail 不返回"}

# 修前（issue #4090）服务端 `matchSkuId` 的读取点：只认 ID 族（负例复现用）
_PRE_FIX_SERVER_KEYS = {"skuId", "colorId", "sellingMethod", "doorWidth"}


def _match_sku_id_body() -> str:
    """服务端库存匹配方法体（issue #4090 的单一判据所在）。"""
    assert _ORDER_SERVICE.is_file(), f"找不到 admin-api 源码: {_ORDER_SERVICE}"
    return _method_body(_ORDER_SERVICE.read_text(encoding="utf-8"),
                        "private Long matchSkuId(OrderItem item, String actionLabel)")


def _server_read_spec_keys() -> set[str]:
    """服务端从 processingInfo 读取的规格键集合（`info.get("x")`）。"""
    return set(re.findall(r'info\.get\("([^"]+)"', _match_sku_id_body()))


def _product_detail_sku_keys() -> set[str]:
    """product_detail `_format_skus` 输出的 sku 字段集合（`"x": sku.get(...)` 的键）。"""
    body = _method_body(_PRODUCT_DETAIL.read_text(encoding="utf-8"),
                        "def _format_skus(self, skus: list) -> list:")
    return set(re.findall(r'"([a-z_]+)":\s*sku\.get\(', body))


def _spec_schema_properties() -> dict:
    return OrderCreateTool.parameters["properties"]["items"]["items"] \
        ["properties"]["processing_info"]["properties"]


def _declared_spec_keys(schema_properties: dict | None = None) -> set[str]:
    props = _spec_schema_properties() if schema_properties is None else schema_properties
    return {k for k in props if k in _SPEC_KEYS}


def _obtainable_spec_keys() -> set[str]:
    """`product_detail` 真能提供的规格键（跨端键名映射后）。"""
    return {_PRODUCT_DETAIL_SOURCES[k] for k in _product_detail_sku_keys()
            if k in _PRODUCT_DETAIL_SOURCES}


def _producible_spec_keys(schema_properties: dict | None = None) -> set[str]:
    """工具**真能产出**的规格键：schema 声明 ∩ 有取值来源。

    声明了但 `product_detail` 不产出的键（`colorId`）不算「能产出」—— 模型无从取值，
    只会臆造（这正是修前 ID 族不可达的成因）。
    """
    return _declared_spec_keys(schema_properties) & _obtainable_spec_keys()


def key_family_violations(server_keys: set[str], producible_keys: set[str]) -> list[str]:
    """键族判据（纯函数，便于负例注入口）：返回违规清单（空 = 通过）。

    ① 身份键族不相交 ⇒ 服务端所需的身份键工具都产不出（或工具产出的服务端都不读）
    ⇒ 库存路径不可达（修前形态：工具产出 `skuCode/colorName`，服务端只读 `skuId/colorId`）；
    ② 工具产出的属性键服务端不读 ⇒ 属性归一化口径与消费点脱节。
    """
    violations: list[str] = []
    if not (set(_IDENTITY_KEYS) & server_keys & producible_keys):
        violations.append(
            "键族不相交：没有任何 SKU 身份键既由工具产出、又被服务端 matchSkuId 读取 "
            f"（服务端读 {sorted(server_keys & set(_IDENTITY_KEYS))}，"
            f"工具产出 {sorted(producible_keys & set(_IDENTITY_KEYS))}）"
            " ⇒ 库存校验/扣减/销量会被静默跳过（issue #4090）"
        )
    for key in _ATTRIBUTE_KEYS:
        if key in producible_keys and key not in server_keys:
            violations.append(f"{key}: 工具产出该属性键，但服务端不读取它（归一化口径无消费点）")
    return violations


def unobtainable_declarations(schema_properties: dict, obtainable_keys: set[str]) -> list[str]:
    """声明的规格键里**拿不到**且**未标注不可得**的键（幻觉源）清单。"""
    red: list[str] = []
    for key, schema in schema_properties.items():
        if key not in _SPEC_KEYS or key in obtainable_keys:
            continue
        marker = _UNOBTAINABLE.get(key)
        if not marker or marker not in schema.get("description", ""):
            red.append(key)
    return red


# ── ① 键族必须相交（红证：修前形态必红） ─────────────────────────────────────


def test_spec_key_families_intersect():
    """工具产出的规格键族与服务端读取的规格键族必须相交（当前代码必须通过）。"""
    violations = key_family_violations(_server_read_spec_keys(), _producible_spec_keys())
    assert violations == [], f"规格键族违规: {violations}"


def test_negative_pre_fix_key_families_are_disjoint():
    """负例（红证复现）：两侧退回修前形态 ⇒ 判据必红。

    修前：schema 不声明 `skuId`、`colorId` 又拿不到 ⇒ 工具只能产出 `skuCode/colorName`；
    服务端只读 `skuId/colorId` ⇒ 身份键交集为空 ⇒ 库存三处静默跳过（issue #4090 实测形态）。
    """
    pre_fix_schema = {k: v for k, v in _spec_schema_properties().items() if k != "skuId"}
    violations = key_family_violations(_PRE_FIX_SERVER_KEYS, _producible_spec_keys(pre_fix_schema))
    assert any("键族不相交" in v for v in violations), (
        f"修前键族被判为通过（判据不会红 = 空断言）: 服务端={sorted(_PRE_FIX_SERVER_KEYS)} "
        f"工具产出={sorted(_producible_spec_keys(pre_fix_schema))}"
    )
    # 对照：把服务端也修好（读字符串族）后，同一条判据转绿 —— 证明红→绿是判据驱动的
    assert key_family_violations(_server_read_spec_keys(), _producible_spec_keys(pre_fix_schema)) == []


# ── ② 声明的键必须可得 ──────────────────────────────────────────────────────


def test_declared_spec_keys_are_obtainable_or_marked_unobtainable():
    """schema 声明的每个规格键都要有取值来源；`colorId` 必须显式标注不可得。"""
    obtainable = _obtainable_spec_keys()
    assert {"skuId", "skuCode", "colorName", "sellingMethod", "doorWidth"} <= obtainable, (
        f"product_detail 取值来源不完整: {sorted(obtainable)}（sku 主键在 skus[].id）"
    )
    assert unobtainable_declarations(_spec_schema_properties(), obtainable) == [], (
        "以下声明键拿不到且未标注不可得（模型只能臆造）: "
        f"{unobtainable_declarations(_spec_schema_properties(), obtainable)}"
    )


def test_sku_id_is_declared_and_taught():
    """ID 族首选键 `skuId` 必须既**声明**（schema）又**教**（描述指向 skus[].id）。

    修前：`skuId` 声明数 = 0、工具描述只说 colorName/skuCode ⇒ 模型既拿不到也没被教 ID 族，
    agent 路径永远只能产出字符串族。
    """
    properties = _spec_schema_properties()
    assert "skuId" in properties, "schema 未声明 skuId —— ID 族对 agent 不可达（issue #4090）"
    assert "skus[].id" in properties["skuId"]["description"], (
        f"skuId 描述未指向取值来源（product_detail skus[].id）: {properties['skuId']['description']}"
    )
    description = OrderCreateTool.description
    assert "skuId" in description and "skus[].id" in description, (
        "工具描述未教模型传 skuId（skus[].id）—— 声明了也用不上"
    )
    assert "colorId" in description and "不返回" in description, (
        "工具描述未提醒 colorId 不可得（product_detail 不返回）—— 幻觉源仍在"
    )


# ── ③ 负例：声明一个拿不到的键 ⇒ 判据必红 ───────────────────────────────────


def test_negative_unobtainable_declared_key_is_red():
    """负例：把 `colorId` 的描述退回修前（"颜色ID（字符串，来自商品详情）"）⇒ 判据必红。"""
    mutated = copy.deepcopy(_spec_schema_properties())
    mutated["colorId"] = {"type": "string", "description": "颜色ID（字符串，来自商品详情）"}

    red = unobtainable_declarations(mutated, _obtainable_spec_keys())
    assert red == ["colorId"], f"拿不到又未标注的声明键没有被判红: {red}"

# ══════════════════════════════════════════════════════════════════════════════
# craft spec 枚举闸门（issue #4346 包 1 · Python 生产端）
# ══════════════════════════════════════════════════════════════════════════════
# `processing_info` 是**整体透传**的（`order_create` 不重拼字段）⇒ 新键不会丢；
# 但**错值**会一路写到服务端 —— 部位/工艺错了会取到**错误工序路线**
# （实证 V58：纱帘订单拿到布帘的 11 道工序，**工序与工资全错**）。
# 故在工具侧 fail-fast：**拒绝 + 点名合法值**，让 LLM 下一轮自愈
# （沿用 `_reject_invalid_enum` 既有口径：刻意**不**做别名归一化）。
import pytest  # noqa: E402  （本段自带导入，便于与上方键族测试分段阅读）


class TestCraftSpecEnumGate:
    """craft spec 枚举闸门：拒绝别名/错值，不静默接受。"""

    @pytest.mark.parametrize(
        "pinfo, label",
        [
            ({"curtainType": "窗帘"}, "部位/帘种"),
            ({"craft": "韩式褶"}, "安装工艺"),
            ({"componentRole": "配布"}, "明细行角色"),
            ({"style": "拼色款"}, "款式"),
            ({"metersSource": "自动"}, "配布边米数来源"),
        ],
    )
    def test_invalid_craft_spec_enum_is_rejected(self, pinfo, label):
        """错值/别名必须被拒（`韩式褶` 不是库枚举 `韩褶`；归一化 = 静默给错工序）。"""
        result = OrderCreateTool._validate_processing_info(0, pinfo)
        assert result is not None, f"{label} 错值未被拦下 ⇒ 会一路写到订单"
        assert result.success is False
        assert label in (result.message or ""), "报错必须点名是哪个字段"
        assert "错误工序路线" in (result.message or ""), (
            "必须说明**该字段的真实后果**（取错工序路线）—— 默认文案只对 SKU 规格族成立"
        )
        assert result.suggestion and "请改用" in result.suggestion, "必须给可行动的 suggestion"
        assert "per_piece" not in result.suggestion, (
            "不得串味：部位/工艺的建议里不该出现计价方式的说明（会误导 LLM 自愈方向）"
        )

    def test_valid_craft_spec_passes(self):
        """合法值（与工序库枚举逐字一致）⇒ 放行。"""
        assert OrderCreateTool._validate_processing_info(0, {
            "curtainType": "纱帘",
            "craft": "打孔",
            "componentRole": "配布边",
            "style": "拼色",
            "isShaped": False,
            "metersSource": "跟随主布",
            "specialOptions": ["拼2次", "加铅块"],
        }) is None

    def test_absent_craft_spec_keys_pass(self):
        """**键缺席必须放行** —— 工艺规格是可选透传，缺省不得变成硬门槛（存量单/普通商品）。"""
        assert OrderCreateTool._validate_processing_info(0, {"sellingMethod": "bulk_cut"}) is None

    def test_schema_declares_craft_spec_keys_and_description_teaches_them(self):
        """**声明与教学必须同时存在**（issue #4346）：
        只声明不教 ⇒ LLM 不会填（等于没实现）；只教不声明 ⇒ 参数传不进来。
        """
        pi_props = OrderCreateTool.parameters["properties"]["items"]["items"][
            "properties"]["processing_info"]["properties"]
        for key in ("curtainType", "craft", "isShaped", "style", "specialOptions",
                    "componentRole", "craftLineId", "metersSource", "processingMeters"):
            assert key in pi_props, f"processing_info schema 未声明 {key} ⇒ LLM 传不进来"
        assert pi_props["craft"]["enum"] == ["韩褶", "打孔", "四爪钩", "穿杆", "平幔"], (
            "craft 枚举必须与工序库 production_routings.craft 逐字一致"
        )
        desc = OrderCreateTool.description
        for token in ("工艺规格", "componentRole", "craftLineId", "主布米数"):
            assert token in desc, f"工具描述未教「{token}」⇒ LLM 不会填这些键"


# ══════════════════════════════════════════════════════════════════════════════
# 写侧补全：工艺键 + 算料输出键（issue #4374 包 4a · 设计文档 §4.2 / §4.3 / §4.6 入口 1）
# ══════════════════════════════════════════════════════════════════════════════
# 病根：包 1（#4346）只声明了 9 个 craft 键 ⇒ 加工类型/打开方式/褶距/对花与**全部算料输出键**
# 既不在 schema、也不在「必带」指令里 ⇒ LLM 大概率不写 ⇒ 订单/加工单面**看不到**这些字段
# （缺值不渲染 ⇒ 不出错，但用户看不到）。
#
# 两条硬口径（本段判据锁的就是它们）：
# ① **声明与教学必须同时存在** —— 只声明不教 ⇒ LLM 不填；只教不声明 ⇒ 参数传不进来；
# ② **算料输出键只许原样透传** —— 唯一来源是 `curtain_calc` 输出（键名 snake_case 逐字一致，
#    设计文档 §4.5）；缺就不填，**禁止自己推算/补 0**（不发明数字）。
_CRAFT_SPEC_EXTRA_KEYS = (
    "cuttingMode", "openCount", "pleatSpacing", "hasPattern", "patternRepeat",
)
_CALC_OUTPUT_KEYS = (
    "fabric_meters", "pleat_count", "per_panel_pleats", "panels",
    "fullness", "fullness_actual", "source",
)


def _pi_props() -> dict:
    return OrderCreateTool.parameters["properties"]["items"]["items"][
        "properties"]["processing_info"]["properties"]


class TestCraftSpecKeyCompletion:
    """`order_create` 的工艺键与算料输出键：声明 + 教学 + 闸门（issue #4374）。"""

    def test_schema_declares_missing_craft_and_calc_keys(self):
        """缺失键必须在 schema 里**声明**（否则 LLM 传不进来 ⇒ 等于没实现）。"""
        props = _pi_props()
        for key in _CRAFT_SPEC_EXTRA_KEYS + _CALC_OUTPUT_KEYS:
            assert key in props, f"processing_info schema 未声明 {key} ⇒ LLM 传不进来"
        assert props["cuttingMode"]["enum"] == ["定高买宽", "定宽买高"], (
            "加工类型枚举 = 算料侧 `formula_used` 的两态口径（设计文档 §4.2）"
        )
        assert props["openCount"]["enum"] == [1, 2, 4], (
            "打开方式开数只认 1/2/4（单开/双开/四开）"
        )
        for key in ("pleatSpacing", "patternRepeat", "fabric_meters", "pleat_count",
                    "per_panel_pleats", "panels", "fullness", "fullness_actual"):
            assert props[key].get("minimum") == 0, f"{key} 必须声明为非负数（minimum: 0）"

    def test_description_teaches_craft_and_calc_keys(self):
        """工具描述必须**教**这些键 —— 只声明不教 ⇒ LLM 不会填。"""
        desc = OrderCreateTool.description
        for key in _CRAFT_SPEC_EXTRA_KEYS + _CALC_OUTPUT_KEYS:
            assert key in desc, f"工具描述未教「{key}」⇒ LLM 不会填"

    def test_description_requires_calc_output_passthrough(self):
        """算料输出键的来源与红线必须写进描述：原样透传 `curtain_calc` 输出，禁止自己推算。"""
        desc = OrderCreateTool.description
        assert "curtain_calc" in desc, "描述未点名算料输出的唯一来源（curtain_calc）"
        for token in ("原样透传", "不要自己推算"):
            assert token in desc, f"描述缺「{token}」⇒ LLM 会自己推算算料数字（发明数字）"
        assert "不要补 0" in desc or "不补 0" in desc, (
            "描述未说明「缺就不填、不要补 0」⇒ 缺值会被填成假数字"
        )

    def test_description_declares_source_enum_per_truth_doc(self):
        """`source` 口径必须与真值源 §8 一致（`公式计算`/`人工指定`/`客户自报`）。"""
        assert _pi_props()["source"]["enum"] == ["公式计算", "人工指定", "客户自报"], (
            "source 枚举必须与 docs/curtain-fabric-quote-rules.md §8 逐字一致"
        )
        desc = OrderCreateTool.description
        for value in ("公式计算", "人工指定", "客户自报"):
            assert value in desc, f"描述未教 source 的合法值「{value}」"

    def test_cutting_mode_and_open_count_enum_gate(self):
        """取值闸门：错值/别名一律拒绝并点名合法值（沿用 `_reject_invalid_enum` 口径）。"""
        rejected = OrderCreateTool._validate_processing_info(0, {"cuttingMode": "定高"})
        assert rejected is not None and rejected.success is False
        assert "加工类型" in (rejected.message or ""), "报错必须点名是哪个字段"
        assert "定高买宽" in (rejected.suggestion or ""), "必须给出合法值让 LLM 自愈"
        assert "错误工序路线" in (rejected.message or ""), (
            "必须说明该字段的真实后果（默认文案只对 SKU 规格族成立）"
        )

        rejected = OrderCreateTool._validate_processing_info(0, {"openCount": 3})
        assert rejected is not None and rejected.success is False
        assert "打开方式" in (rejected.message or "")
        assert "1" in (rejected.suggestion or "") and "4" in (rejected.suggestion or "")

        for bad in ("2", True):        # 字符串数字 / 布尔都不得被当成开数 2/1 静默放行
            rejected = OrderCreateTool._validate_processing_info(0, {"openCount": bad})
            assert rejected is not None and rejected.success is False, (
                f"openCount={bad!r} 被静默接受 ⇒ 取值类型口径不严"
            )

    @pytest.mark.parametrize(
        "pinfo, label",
        [
            ({"pleatSpacing": -0.1}, "褶距"),
            ({"patternRepeat": -0.5}, "花距"),
            ({"fabric_meters": -1}, "面料米数"),
            ({"pleat_count": -48}, "折数"),
            ({"per_panel_pleats": -24}, "每片折数"),
            ({"panels": -2}, "幅数"),
            ({"fullness": -2.0}, "理论褶倍"),
            ({"fullness_actual": -1.8}, "实际褶倍"),
        ],
    )
    def test_negative_numeric_calc_keys_are_rejected(self, pinfo, label):
        """数值键非负：负数一律本地拒绝（负米数/负幅数会一路写进订单）。"""
        result = OrderCreateTool._validate_processing_info(0, pinfo)
        assert result is not None, f"{label} 负数未被拦下 ⇒ 会一路写到订单"
        assert result.success is False
        assert label in (result.message or ""), "报错必须点名是哪个字段"

    def test_valid_extra_keys_pass(self):
        """合法值放行（含 0：褶距/花距可以合法为 0）。"""
        assert OrderCreateTool._validate_processing_info(0, {
            "cuttingMode": "定宽买高",
            "openCount": 2,
            "pleatSpacing": 0.1,
            "hasPattern": True,
            "patternRepeat": 0,
            "fabric_meters": 12.3,
            "pleat_count": 48,
            "per_panel_pleats": 24,
            "panels": 4,
            "fullness": 2.0,
            "fullness_actual": 1.86,
            "source": "公式计算",
        }) is None

    def test_absent_extra_keys_pass(self):
        """**键缺席一律放行** —— 算料输出/工艺规格是可选透传，缺省不得变成硬门槛。"""
        assert OrderCreateTool._validate_processing_info(0, {"sellingMethod": "bulk_cut"}) is None
        assert OrderCreateTool._validate_processing_info(
            0, {"processingItems": [{"name": "打孔", "unitPrice": 8, "quantity": 3}]}
        ) is None

    def test_parameters_stays_ast_literal(self):
        """**跨语言契约护栏**：`parameters` 必须是 `ast.literal_eval` 可求值的**字面量**。

        admin-api 的 `OrderDtoContractTest.pythonSchema` 用 CPython 的 `ast` 定位
        `class ...: parameters = {...}` 再 `literal_eval`（与运行时**同一份源码**，不抄期望值）。
        ⇒ schema 里出现任何**函数调用**（如 `enum: list(_SOURCES)`）都会让该 Java 契约测试判红，
        而本地 ai-agent 单测**不会红**（真值一致，只是形态不是字面量）—— 这正是本次踩到的形态。

        判据取**形态**（有无 `ast.Call`）而非「与 `_SOURCES` 等值」：前者是契约本身的要求，
        后者会随常量演化而腐烂（§19.2）。
        """
        tree = ast.parse(_ORDER_CREATE_SRC.read_text(encoding="utf-8"))
        assignment = next(
            (stmt for node in tree.body if isinstance(node, ast.ClassDef)
             for stmt in node.body
             if isinstance(stmt, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "parameters" for t in stmt.targets)),
            None,
        )
        assert assignment is not None, "order_create.py 里找不到 `parameters = {...}` 赋值"
        calls = [n.lineno for n in ast.walk(assignment.value) if isinstance(n, ast.Call)]
        assert calls == [], (
            f"`parameters` 里出现函数调用（行 {calls}）⇒ admin-api 的 ast.literal_eval 契约测试会判红；"
            "请改成字面量"
        )
        ast.literal_eval(assignment.value)          # 求值失败即判红（与 Java 侧同口径）
