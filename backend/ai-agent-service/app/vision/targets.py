"""识别 target 的字段 schema 与消歧策略（issue #5321 包 1）。

🔴 **不许做成「一套字段两个页面填」**（用户裁定 2026-09-24）：`商品` 与 `订单` 是
两个不同的识别 target —— 图片形态不同（色卡/布料实拍 vs 手写单/聊天截图/旧系统单据）、
目标字段不同、**风险不同**。

| target | 图片常见形态 | 识别目标字段 |
|---|---|---|
| `product` | 色卡 / 布料实拍 / 供应商图 | 名称 / 颜色 / 材质 / 工艺 / 门幅 / 售价 |
| `order` | 手写单 / 微信聊天截图 / 旧系统单据 | 客户名 / 电话 / 商品明细 / 数量 / 规格 |

**风险不对称**：订单侧客户信息错 ⇒ **货发错人** ⇒ 「不确定的宁可不填」的阈值更严
（见 `TARGET_POLICY` 的 `min_confidence`，以及 `recognizer.py` 对手机号形状的硬校验）。
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
        TargetField("spec", "规格", "规格（宽×高 / 门幅 / 颜色等）"),
    ),
}

# 每个 target 的消歧策略。
#
# `min_confidence` = **采纳下限**：低于它一律**留空 + 给理由**（错填比留空贵得多）。
# 订单侧 0.85 严于商品侧 0.60 —— 同一个 0.70 的置信度，商品留、订单弃。
TARGET_POLICY: Dict[str, Dict[str, float]] = {
    "product": {"min_confidence": 0.60},
    "order": {"min_confidence": 0.85},
}

# 人类可读的「哪一侧」——进留空理由，让商家看得懂为什么这格没填。
TARGET_SIDE_LABEL: Dict[str, str] = {
    "product": "商品侧",
    "order": "订单侧",
}


def field_keys(target_type: str) -> Tuple[str, ...]:
    return tuple(f.key for f in TARGET_FIELDS[target_type])