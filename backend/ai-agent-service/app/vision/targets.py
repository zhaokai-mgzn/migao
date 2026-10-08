"""识别 target 的字段 schema 与消歧策略（issue #5321 包 1）。

🔴 **不许做成「一套字段两个页面填」**（用户裁定 2026-09-24）：`商品` 与 `订单` 是
两个不同的识别 target —— 图片形态不同（色卡/布料实拍 vs 手写单/聊天截图/旧系统单据）、
目标字段不同、**风险不同**。

| target | 图片常见形态 | 识别目标字段 |
|---|---|---|
| `product` | 色卡 / 布料实拍 / 供应商图 | 名称 / 颜色 / 材质 / 工艺 / 门幅 / 售价 |
| `order` | 手写单 / 微信聊天截图 / 旧系统单据 | 客户名 / 电话 / 地址 / 商品明细 / 数量 / 帘宽 / 帘高 |
| `inbound`（issue #5052 P1） | **上游标签**（布卷 / 包装上原有的、带 SKU 信息的标签） | 品名 / 色号 / 米数 / 条码原文 |

**风险不对称**：订单侧客户信息错 ⇒ **货发错人** ⇒ 「不确定的宁可不填」的阈值更严
（见 `TARGET_POLICY` 的 `min_confidence`，以及 `recognizer.py` 对手机号形状与尺寸的硬校验）。

## 入库侧（`inbound`）为什么是**第三个** target 而不是复用 `product`（issue #5052 P1）

① **图片形态不同** —— 上游标签是一张**印刷标签**（品名 + 色号 + 米数 + 条码），
不是色卡 / 布料实拍；② **风险不同** —— 这一格的读数经工人确认后**直接进库存**
（`InboundOrderService.post` 加 SKU 库存 + 落 `stock_ledger_entries`），
米数错 = 账实不符 ⇒ 取**严**档（0.85，与订单侧同档，不跟商品侧的 0.60）；
③ **下游判据不同** —— 识别出的**品名 + 色号必须命中既有 `product_skus`**
（`docs/design/inbound-photo-and-label.md` §6.3 的 SKU 匹配门禁：零命中 ⇒ 拒绝入库、
**不自动建品**），命中判定在 admin-api 侧**读库**完成，识别侧只负责「抄清楚」。

⚠️ **本 target 不带推导链输入**（不是订单那种「驱动算料推导的结构化数值」）⇒
按既有类级元守卫登记进 `TARGETS_WITHOUT_DERIVATION` 台账
（`frontend/admin-web/tests/unit/lib/image-recognize-derivation-equivalence.test.ts`）。

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
    #: 🔴 **图上有这一格吗？**（issue #6386，2026-10-05 真跑验收发现）
    #:
    #: `False` = 图上**根本不会有**这类格子（它是**文案**不是**事实**）⇒
    #: ① vision 的字段表里**不给它**（模型连「可以编这一格」的机会都没有 ——
    #:    光靠提示词求它「只抄图上写明的」，实测**无效**：模型照样编出
    #:    `name="常青藤系列窗帘面料色卡"` 与一整段 `description`，还自己给出
    #:    `reason="图片未给出该字段"` —— 自相矛盾的值）；
    #: ② 该格的值**只能**由 `[米宝解读]` 给（`deep_channel.INTERPRETABLE_KEYS`），
    #:    绝不允许 `[图片识别]` 直填（那会把「猜的」标成「抄的」）。
    #:
    #: 判据 = `tests/test_vision/test_copy_vs_infer.py`（实例 + 类级元守卫）。
    recognizable: bool = True


TARGET_FIELDS: Dict[str, Tuple[TargetField, ...]] = {
    "product": (
        # 商品名是**文案**不是图上的事实（真跑实测：模型会编出「常青藤系列窗帘面料色卡」这种
        # 看起来很合理的标题并顶 `[图片识别]` 标）⇒ 用户 2026-10-05 裁定「B：让黄金策推、标 `[米宝解读]`」。
        TargetField("name", "商品名称", "商品标题；图上有多个名称时取最完整的一个",
                    recognizable=False),
        TargetField("color", "颜色", "色号 + 颜色名，多个用顿号分隔；只抄图上写明的"),
        TargetField("material", "材质", "面料成分 / 材质（如雪尼尔、棉麻）"),
        TargetField("craft", "工艺", "工艺（如遮光、印花、提花）"),
        TargetField("door_width", "门幅", "门幅（米）；只抄图上写明的数字，不推算"),
        TargetField("price", "售价", "售价（元）；只抄图上写明的数字，不推算"),
        # 2026-10-05（issue #6362）：**商品描述文案** —— 用户逐字「然后把商品描述的文案也要生成一份」。
        # 落点是建品页**既有**富文本区（`ProductFormData.description`，提交链路已通）⇒ **不新增落库字段**。
        # 🔴 它是**推理产物**、不是图上的事实：本格**不参与**识别直填，只由 `[米宝解读]` 填值
        #（见 `deep_channel.INTERPRETABLE_KEYS`）—— hint 据此要求「不得编造图上没有的硬事实」，
        # 推测性表述必须带「约 / 可选」这类措辞（与 issue #6362 的内容口径同一处）。
        TargetField(
            "description",
            "商品描述",
            "商品描述文案（HTML 片段）：贴近图上信息 + 行业常识（材质 / 工艺 / 适用场景 / "
            "清洗与安装提示）；不得编造图上没有的硬事实（价格 / 门幅数字 / 认证 / 产地），"
            "推测性表述用「约 / 可选」这类措辞",
            recognizable=False,
        ),
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
        # 🔴 客户在图上写明的**工艺要求**（issue #5794）—— 用户口径：「如果用户是根据图片下单的，
        #    就需要根据图中客户要求来决定工艺规格和加工项选择了，**不能选错**」。
        #    ⚠️ 三格都是**结构化键**（不是「客户要求」一段自由文本）：自由文本进不了勾选控件
        #    （同 #5349 的教训 —— 识别侧只负责「抄清楚」，派生/选中照旧跑在页面与引擎）。
        #    ⚠️ 三格**不进** `DERIVATION_INPUT_KEYS`：它们不是推导链的输入，而是**勾选面的要求**。
        TargetField(
            "open_count", "打开方式",
            "客户写明的开数：单开 / 双开 / 三开 / 四开（写 1 / 2 / 3 / 4 也行）。"
            "**只抄写明的那一档**；没写 / 写不清 ⇒ 留空",
        ),
        TargetField(
            "style", "款式",
            "客户写明的款式：**单色** 或 **拼色**（写「双拼」「双拼色」也算拼色）。"
            "没写 ⇒ 留空",
        ),
        TargetField(
            "processing_items", "加工项",
            "客户写明的加工要求（如 韩褶（图上写「韩折」也归韩褶）、打孔、穿杆、平幔、定型、加铅块、接高…），"
            "多个用顿号分隔；**只抄写明的那几项**，没写 ⇒ 留空（不要替客户联想）",
        ),
    ),
    # 入库侧（issue #5052 P1）：上游标签 → 工人确认 → 库存。⚠️ 字段键**不与**前两个 target 重叠
    # （「一套字段两个页面填」的机械判据见 tests/test_vision/test_targets.py）。
    "inbound": (
        TargetField("product_name", "品名", "标签上的商品名称；只抄图上写明的，不推算、不联想"),
        TargetField("color_name", "色号", "色号 + 颜色名（如「01 米白」）；一位看不清就留空"),
        TargetField("quantity_meters", "米数",
                    "标签上的米数（只抄数字，不要单位）；布卷标签常写「60.5」这种 1 位小数。"
                    "图上没有米数 ⇒ 留空"),
        TargetField("barcode", "条码原文",
                    "标签上条码 / 二维码**旁边的人可读数字**，一字不差地抄；"
                    "只有图形没有可读数字 ⇒ 留空（**不要**猜条码内容）"),
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
    # 🔴 `inbound`（#5052 P1）与 `shipment`（#5648）**各自**都不与任何 target 共享键，
    # 但两者合并后 `product_name` 相交 —— 这是**合并态才出现的新交互**（两个分支各自绿、
    # 合起来被本判据抓到，实测 `AssertionError: [('inbound','shipment','product_name')]`）。
    # 与 `quantity` 同族：**同一列名、两个不同的事实** ——
    # `inbound.product_name` = 上游布卷标签上的品名（收货对象），
    # `shipment.product_name` = 订单行 / 商品标签上的商品名（发货对象）。
    # 两者都逐字取自既有列名（`order_items.product_name` / 商品名），**不许自造第二套口径**。
    "product_name": ("inbound", "shipment"),
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
#:
#: ⚠️ **2026-09-29 追加（issue #5794）**：订单侧新增的三格**客户要求**（`open_count` / `style` /
#: `processing_items`）**刻意不进本表** —— 它们不是推导链的输入，而是**勾选面的显式要求**
#: （识别只负责「抄清楚客户写了什么」；工艺规格与加工项由页面按图**选中**，不由识别替引擎推导）。
DERIVATION_INPUT_KEYS: Dict[str, Tuple[str, ...]] = {
    "order": ("curtain_width", "curtain_height"),
}

#: 「**参考**字段」登记表（issue #6529）—— 置信度不足时**不采纳为值**，但把图上原文
#: 以 `reference` 原样带出去，**只读参考**（展示 + 查目录），**永不进表单**。
#:
#: 为什么是它（而不是"放宽订单侧阈值"）：`items`（商品明细）在页面上的**唯一消费方**是
#: 「按名称**查目录** ⇒ 给候选 ⇒ **商家点选** ⇒ 才建订单行」（issue #5345）——
#: 一个读错的明细**不会变成单里的值**，只会变成一次检索词；而把它整格丢掉，商家就连
#: 「图上写的这个型号在目录里查不到」都听不到（用户 2026-10-08 实证：同图在黄金策会话里
#: 说得出「没有匹配的商品」，建单页却一片沉默，issue #6529）。
#: 反面对照：客户名 / 电话 / 地址 / 帘宽 / 帘高**不在此表** —— 它们的值直接进单据与推导链
#: （错填 = 货发错人 / 米数错），必须保持「置信度不足 ⇒ 连原文都不给」。
#:
#: 🔴 本表 ⇄ 行为**双向**由 `backend/ai-agent-service/tests/test_vision/test_recognizer.py`
#: 的 `TestReferenceOnlyFields` 钉住（未登记的键**不得**带 `reference`；登记了的键低于阈值
#: 必须**带着原文**返回）；前端消费侧的键集由
#: `frontend/admin-web/src/lib/order-line-match.ts::REFERENCE_ONLY_FIELD_KEYS` 声明，
#: 并由 `tests/unit/lib/order-line-match.test.ts` 的类级守卫与本表逐字对齐（改名漂移 ⇒ 红）。
REFERENCE_KEYS: Dict[str, Tuple[str, ...]] = {
    "order": ("items",),
}

# 每个 target 的消歧策略。
#
# `min_confidence` = **采纳下限**：低于它一律**留空 + 给理由**（错填比留空贵得多）。
# 订单侧 0.85 严于商品侧 0.60 —— 同一个 0.70 的置信度，商品留、订单弃。
# 入库侧同样取 0.85（issue #5052 P1）：这一格经工人确认后**直接进库存 + 落台账**，
# 米数抄错就是账实不符 ⇒ 与订单侧同档严，不跟商品侧的 0.60。
TARGET_POLICY: Dict[str, Dict[str, float]] = {
    "product": {"min_confidence": 0.60},
    "order": {"min_confidence": 0.85},
    # 发货侧 0.90 **严于**订单侧：订单侧认错 ⇒ 客户信息错（货发错人）；
    # 发货侧认错 ⇒ **数量/规格错**（少发、多发、发错规格），而那是已经出了车间的既成事实
    # —— 追回来比改一张单贵得多。⇒ 宁可留空让工人手输。
    "shipment": {"min_confidence": 0.90},
    "inbound": {"min_confidence": 0.85},
}

# 人类可读的「哪一侧」——进留空理由，让商家看得懂为什么这格没填。
TARGET_SIDE_LABEL: Dict[str, str] = {
    "product": "商品侧",
    "order": "订单侧",
    "shipment": "发货侧",
    "inbound": "入库侧",
}


def field_keys(target_type: str) -> Tuple[str, ...]:
    return tuple(f.key for f in TARGET_FIELDS[target_type])