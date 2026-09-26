"""识别 target 的字段 schema 与消歧策略（issue #5321 包 1）。

🔴 **不许做成「一套字段两个页面填」**（用户裁定 2026-09-24）：`商品` 与 `订单` 是
两个不同的识别 target —— 图片形态不同（色卡/布料实拍 vs 手写单/聊天截图/旧系统单据）、
目标字段不同、**风险不同**。

| target | 图片常见形态 | 识别目标字段 |
|---|---|---|
| `product` | 色卡 / 布料实拍 / 供应商图 | 名称 / 颜色 / 材质 / 工艺 / 门幅 / 售价 |
| `order` | 手写单 / 微信聊天截图 / 旧系统单据 | 客户名 / 电话 / 地址 / 商品明细 / 数量 / 帘宽 / 帘高 |

**风险不对称**：订单侧客户信息错 ⇒ **货发错人** ⇒ 「不确定的宁可不填」的阈值更严
（见 `TARGET_POLICY` 的 `min_confidence`，以及 `recognizer.py` 对手机号形状与尺寸的硬校验）。

## 订单侧的字段为什么是「帘宽 / 帘高」而不是一个自由文本「规格」（issue #5349）

用户裁定 2026-09-24：「创建订单功能，有自动化推导参数的能力，这个**通过图片创建订单时也要能自动推导**」。
而推导链（`frontend/admin-web/src/lib/craft-calc-request.ts`）要的是**结构化数值输入** ——
宽 / 高对它 fail-closed（缺任一个就不发试算）⇒ **自由文本进不了推导函数**，这才是"图片建单推不动"的
**具体原因**（不是"推导没跑"）。

⇒ 订单侧字段表带上**推导链的原始输入**（登记在 `DERIVATION_INPUT_KEYS`），
推导照旧跑在页面 / 算料引擎 —— **识别侧不得出现第二份派生逻辑**
（`frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx` 已明写：同一真值两处推导 = 页面显示 ≠ 落库）。
"""
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class TargetField:
    """一个识别目标字段：`key` 是前后端契约键，`label` 是用户看到的中文名。"""

    key: str
    label: str
    hint: str


TARGET_FIELDS: Dict[str, Tuple[TargetField, ...]] = {
    "product": (
        TargetField("name", "商品名称", "商品标题；图上有多个名称时取最完整的一个"),
        TargetField("color", "颜色", "色号 + 颜色名，多个用顿号分隔；只抄图上写明的"),
        TargetField("material", "材质", "面料成分 / 材质（如雪尼尔、棉麻）"),
        TargetField("craft", "工艺", "工艺（如遮光、印花、提花）"),
        TargetField("door_width", "门幅", "门幅（米）；只抄图上写明的数字，不推算"),
        TargetField("price", "售价", "售价（元）；只抄图上写明的数字，不推算"),
    ),
    "order": (
        TargetField("customer_name", "客户名", "收货人 / 客户姓名，一字不差地抄"),
        TargetField("customer_phone", "电话", "11 位手机号；一位数字看不清就留空"),
        TargetField("customer_address", "地址", "收货地址；手写体潦草看不清就留空"),
        TargetField("items", "商品明细", "商品名称清单，多个用顿号分隔"),
        TargetField("quantity", "数量", "数量（米 / 套 / 件），保留图上的单位写法"),
        # 🔴 尺寸两格必须**分格**（issue #5349）：它们进的是页面的「窗宽 / 窗高」数字框 ⇒ 推导链
        #    的原始输入。hint 写「只抄写明方向的数字 + 方向不明就留空」是**第一道**消歧
        #    （手写单 `2.8×2.4` 的宽高顺序约定不统一 ⇒ 不猜顺序），`recognizer._normalise_size`
        #    是**第二道**（模型没听劝也拦得住）。
        TargetField(
            "curtain_width", "帘宽",
            "成品宽 / 窗宽（米）；**只抄图上写明「宽」的那个数字**（带单位也行）。"
            "若图上只有 `2.8×2.4` 这种**没标方向**的写法 ⇒ 本格留空，并在 reason 里说明"
            "「宽高方向不明、不猜顺序」",
        ),
        TargetField(
            "curtain_height", "帘高",
            "成品高 / 窗高（米）；**只抄图上写明「高」的那个数字**。"
            "与帘宽同一条：**方向**不明 ⇒ 留空（宁可不填）",
        ),
    ),
    # ── 发货侧（issue #5648）────────────────────────────────────────────────────
    # 用户 2026-09-26 裁定：拍照识别的是「**订单行 / 商品标签上的文字**」（不是扫箱唛上的码）
    # ⇒ 需要有自己字段面的第三个 target，而**不是**复用 `order`（那种图的客户名/电话/地址
    # 根本不在上面，整格留空只是噪声；两张图的形态与风险都不同）。
    #
    # 🔴 字段键**逐字取自既有列名**（`orders.order_no` / `order_items.product_name` /
    # `order_items.quantity` / `order_items.width` / `order_items.height`）——
    # 自造字段名 = 第二套口径（同一个「数量」在识别面叫 qty、在库里叫 quantity，
    # 迟早有人按名字对齐错）。
    "shipment": (
        TargetField("order_no", "订单号", "订单号（如 ORD-20260926-0001），一字不差地抄；看不清就留空"),
        TargetField("product_name", "商品名称", "订单行 / 商品标签上的商品名，一字不差地抄"),
        TargetField(
            "quantity", "数量",
            "这一行**实际发出**的数量（米 / 套 / 件，保留图上的单位写法）；"
            "只抄图上写明的数字，模糊/涂改/看不清 ⇒ 留空",
        ),
        TargetField(
            "width", "宽",
            "成品宽 / 窗宽（米）；**只抄图上写明「宽」的那个数字**（带单位也行）。"
            "只有 `2.8×2.4` 这种**没标方向**的写法 ⇒ 本格留空，并在 reason 里说明「方向不明、不猜顺序」",
        ),
        TargetField(
            "height", "高",
            "成品高 / 窗高（米）；**只抄图上写明「高」的那个数字**。与宽同一条：**方向**不明 ⇒ 留空",
        ),
    ),
}

#: **跨 target 共享的字段键**（登记表，issue #5648）。
#:
#: 用户 2026-09-24 裁定「不要做成一套字段两个页面填」⇒ 那条裁定的机械判据是「两个 target
#: 的字段表零交集」。但 `shipment` 与 `order` 在 `quantity` 上**必然同名** ——
#: 因为「数量」在库里就叫 `order_items.quantity`，而本单要求字段面与订单行**同名**
#: （不许自造第二套口径）。两者是**同一列名、两个不同的事实**：`order.quantity` = 下单数量，
#: `shipment.quantity` = 实发数量（「下单 12 米、实发 10 米」的差额正是本单要能核出来的东西）。
#:
#: ⇒ 判据改为「**未登记的共享键即红**」：共享必须逐条登记（这里），登记项**只许缩短**
#: （哪天某条不再共享了就必须删掉本行）。这样「一套字段两个页面填」仍然进不来
#: （把 shipment 整份字段表改成与 order 逐字相同 ⇒ 五格全部未登记 ⇒ 红）。
SHARED_FIELD_KEYS: Dict[str, Tuple[str, ...]] = {
    "quantity": ("order", "shipment"),
}

#: 「**驱动下游推导链的原始输入**」的登记表（issue #5349）—— 识别只产出推导的**输入**。
#:
#: 它是**双向判据的锚**（元守卫见 `frontend/admin-web/tests/unit/lib/image-recognize-derivation-equivalence.test.ts`
#: 的「类级元守卫」组）：① 这里声明了的键必须在 `TARGET_FIELDS` 里存在；
#: ② 声明了的键必须在页面侧**真接进了推导入参**（否则字段认出来也没人用）；
#: ③ 既没登记、又不带推导输入的 target 必须显式进「不喂推导链」台账 ⇒ **新 target 想溜过去就是红**。
#:
#: 为什么 order 侧只有这两个键：
#: - **宽 / 高**是推导链**唯一不可推导的原始输入**（`craftCalcParamsOf` 的 fail-closed 前置）；
#: - **门幅不在其中**：`fabric_width` 的唯一来源是**所选 SKU**（`line.selectedSku.doorWidth`，
#:   商品属性）⇒ 订单侧再放一个 `door_width` 既没有消费方、又会破坏「两个 target 零交集」的既有
#:   机械判据（用户 2026-09-24 裁定「不要做成一套字段两个页面填」）；选品归 issue #5345；
#: - **加工方式（`cuttingMode`）也不在其中**：它是 D6 **推导的产物**（倒幅 = `cuttingMode` 推导，
#:   issue #4526/#4566/#4592），识别若把它当输入填回去 = 让识别替推导决定（判据 2 会红）。
DERIVATION_INPUT_KEYS: Dict[str, Tuple[str, ...]] = {
    "order": ("curtain_width", "curtain_height"),
}

# 每个 target 的消歧策略。
#
# `min_confidence` = **采纳下限**：低于它一律**留空 + 给理由**（错填比留空贵得多）。
# 订单侧 0.85 严于商品侧 0.60 —— 同一个 0.70 的置信度，商品留、订单弃。
TARGET_POLICY: Dict[str, Dict[str, float]] = {
    "product": {"min_confidence": 0.60},
    "order": {"min_confidence": 0.85},
    # 发货侧 0.90 **严于**订单侧：订单侧认错 ⇒ 客户信息错（货发错人）；
    # 发货侧认错 ⇒ **数量/规格错**（少发、多发、发错规格），而那是已经出了车间的既成事实
    # —— 追回来比改一张单贵得多。⇒ 宁可留空让工人手输。
    "shipment": {"min_confidence": 0.90},
}

# 人类可读的「哪一侧」——进留空理由，让商家看得懂为什么这格没填。
TARGET_SIDE_LABEL: Dict[str, str] = {
    "product": "商品侧",
    "order": "订单侧",
    "shipment": "发货侧",
}


def field_keys(target_type: str) -> Tuple[str, ...]:
    return tuple(f.key for f in TARGET_FIELDS[target_type])