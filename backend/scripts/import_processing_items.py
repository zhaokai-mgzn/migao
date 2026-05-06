#!/usr/bin/env python3
"""
窗帘行业加工项（Processing Items）测试数据导入脚本
通过 admin-api 创建加工分类和加工项
"""

import json
import time
from typing import Dict, List, Optional
import requests

BASE_URL = "http://localhost:8080"
HEADERS = {
    "X-Service-Token": "25c6dcbe8f5987638a87741441b0e001d633529d50e2f29df7dcc954b888846b",
    "X-Tenant-Id": "tenant_default",
    "Content-Type": "application/json",
}

MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds


def api_post(path, data, retries=MAX_RETRIES):
    url = f"{BASE_URL}{path}"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, headers=HEADERS, json=data, timeout=10)
            result = resp.json()
            if result.get("success"):
                return result.get("data")
            else:
                print(f"  [ERROR] {path} attempt {attempt}: {result}")
                if attempt < retries:
                    time.sleep(RETRY_DELAY)
        except Exception as e:
            print(f"  [EXCEPTION] {path} attempt {attempt}: {e}")
            if attempt < retries:
                time.sleep(RETRY_DELAY)
    return None


def api_get(path):
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        result = resp.json()
        if result.get("success"):
            return result.get("data")
    except Exception as e:
        print(f"  [EXCEPTION] GET {path}: {e}")
    return None


# ── 加工分类定义 ──────────────────────────────────────────────
CATEGORIES = [
    {"name": "打孔加工", "sortOrder": 1},
    {"name": "折边加工", "sortOrder": 2},
    {"name": "挂钩加工", "sortOrder": 3},
    {"name": "定型加工", "sortOrder": 4},
    {"name": "特殊工艺", "sortOrder": 5},
    {"name": "辅料加工", "sortOrder": 6},
]


def build_items(category_map):
    """根据分类 ID 构建加工项列表"""
    return [
        # ── 打孔加工 ──
        {
            "name": "纳米圈打孔",
            "categoryId": category_map.get("打孔加工"),
            "pricingMethod": "per_meter",
            "unitPrice": 8,
            "unit": "米",
            "description": "窗帘顶部纳米圈打孔加工，适用于罗马杆安装",
            "options": [
                {"name": "圈色", "values": ["银色", "金色", "黑色"], "default": "银色"}
            ],
            "processingDays": 2,
        },
        {
            "name": "四爪钩打孔",
            "categoryId": category_map.get("打孔加工"),
            "pricingMethod": "per_piece",
            "unitPrice": 2,
            "unit": "个",
            "description": "四爪钩打孔加工，适用于轨道安装",
            "options": [
                {"name": "钩型", "values": ["普通", "加强"], "default": "普通"}
            ],
            "processingDays": 1,
        },
        {
            "name": "韩式S钩打孔",
            "categoryId": category_map.get("打孔加工"),
            "pricingMethod": "per_piece",
            "unitPrice": 3,
            "unit": "个",
            "description": "韩式S钩打孔加工，造型美观",
            "processingDays": 1,
        },
        # ── 折边加工 ──
        {
            "name": "单折边",
            "categoryId": category_map.get("折边加工"),
            "pricingMethod": "per_meter",
            "unitPrice": 5,
            "unit": "米",
            "description": "窗帘单层折边处理",
            "processingDays": 1,
        },
        {
            "name": "双折边",
            "categoryId": category_map.get("折边加工"),
            "pricingMethod": "per_meter",
            "unitPrice": 8,
            "unit": "米",
            "description": "窗帘双层折边处理，更加平整美观",
            "processingDays": 2,
        },
        {
            "name": "包边处理",
            "categoryId": category_map.get("折边加工"),
            "pricingMethod": "per_meter",
            "unitPrice": 10,
            "unit": "米",
            "description": "窗帘边缘包边处理，提升质感",
            "options": [
                {"name": "包边布料", "values": ["同色", "撞色"], "default": "同色"}
            ],
            "processingDays": 2,
        },
        # ── 挂钩加工 ──
        {
            "name": "四爪钩安装",
            "categoryId": category_map.get("挂钩加工"),
            "pricingMethod": "per_piece",
            "unitPrice": 1.5,
            "unit": "个",
            "description": "四爪钩安装，适用于轨道式窗帘杆",
            "processingDays": 1,
        },
        {
            "name": "S钩安装",
            "categoryId": category_map.get("挂钩加工"),
            "pricingMethod": "per_piece",
            "unitPrice": 2,
            "unit": "个",
            "description": "S型挂钩安装，简洁易用",
            "processingDays": 1,
        },
        {
            "name": "罗马杆环安装",
            "categoryId": category_map.get("挂钩加工"),
            "pricingMethod": "per_piece",
            "unitPrice": 3,
            "unit": "个",
            "description": "罗马杆环安装，适用于罗马杆窗帘",
            "processingDays": 1,
        },
        # ── 定型加工 ──
        {
            "name": "普通定型",
            "categoryId": category_map.get("定型加工"),
            "pricingMethod": "per_meter",
            "unitPrice": 6,
            "unit": "米",
            "description": "普通蒸汽定型处理，保持窗帘垂感",
            "processingDays": 3,
        },
        {
            "name": "高温定型",
            "categoryId": category_map.get("定型加工"),
            "pricingMethod": "per_meter",
            "unitPrice": 10,
            "unit": "米",
            "description": "高温定型处理，效果持久不变形",
            "processingDays": 5,
        },
        {
            "name": "免烫定型",
            "categoryId": category_map.get("定型加工"),
            "pricingMethod": "per_area",
            "unitPrice": 15,
            "unit": "平方米",
            "description": "免烫定型处理，洗后免烫自然垂顺",
            "processingDays": 3,
        },
        # ── 特殊工艺 ──
        {
            "name": "LG工艺",
            "categoryId": category_map.get("特殊工艺"),
            "pricingMethod": "fixed",
            "unitPrice": 50,
            "unit": "件",
            "description": "LG特殊加工工艺，提升窗帘整体品质",
            "processingDays": 7,
        },
        {
            "name": "刺绣工艺",
            "categoryId": category_map.get("特殊工艺"),
            "pricingMethod": "per_area",
            "unitPrice": 30,
            "unit": "平方米",
            "description": "精美刺绣加工，可定制花纹图案",
            "processingDays": 10,
        },
        {
            "name": "印花工艺",
            "categoryId": category_map.get("特殊工艺"),
            "pricingMethod": "per_area",
            "unitPrice": 20,
            "unit": "平方米",
            "description": "数码印花加工，色彩丰富图案清晰",
            "processingDays": 5,
        },
        # ── 辅料加工 ──
        {
            "name": "铅坠安装",
            "categoryId": category_map.get("辅料加工"),
            "pricingMethod": "per_meter",
            "unitPrice": 3,
            "unit": "米",
            "description": "窗帘底部铅坠安装，增加垂感",
            "processingDays": 1,
        },
        {
            "name": "魔术贴安装",
            "categoryId": category_map.get("辅料加工"),
            "pricingMethod": "per_meter",
            "unitPrice": 4,
            "unit": "米",
            "description": "魔术贴安装，方便拆卸清洗",
            "processingDays": 1,
        },
        {
            "name": "窗幔制作",
            "categoryId": category_map.get("辅料加工"),
            "pricingMethod": "fixed",
            "unitPrice": 80,
            "unit": "件",
            "description": "窗幔定制制作，提升窗帘装饰效果",
            "processingDays": 5,
        },
    ]


def main():
    print("=" * 60)
    print("窗帘行业加工项测试数据导入")
    print("=" * 60)

    # ── Step 1: 创建加工分类（先查已有，避免重复） ──
    print("\n[Step 1] 创建加工分类...")
    category_map = {}

    # 查询已有分类
    existing_cats = api_get("/api/admin/processing-categories")
    if existing_cats:
        for ec in existing_cats:
            category_map[ec["name"]] = ec["id"]
            print(f"  已存在分类: {ec['name']} (id={ec['id']})")

    # 创建缺失的分类
    for cat in CATEGORIES:
        if cat["name"] in category_map:
            continue
        print(f"  创建分类: {cat['name']} ...", end=" ")
        result = api_post("/api/admin/processing-categories", cat)
        if result:
            cat_id = result.get("id")
            category_map[cat["name"]] = cat_id
            print(f"✅ id={cat_id}")
        else:
            print("❌ 失败")

    if len(category_map) != len(CATEGORIES):
        print(f"\n⚠️  部分分类创建失败 ({len(category_map)}/{len(CATEGORIES)})")
        if not category_map:
            print("全部失败，退出")
            return
    else:
        print(f"\n✅ 全部 {len(CATEGORIES)} 个分类就绪")

    # ── Step 2: 创建加工项（跳过分类缺失的项） ──
    print("\n[Step 2] 创建加工项...")
    items = build_items(category_map)
    success_count = 0
    fail_count = 0
    skip_count = 0
    for item in items:
        if not item.get("categoryId"):
            print(f"  跳过加工项: {item['name']} (分类缺失)")
            skip_count += 1
            continue
        print(f"  创建加工项: {item['name']} ({item['pricingMethod']}, ¥{item['unitPrice']}/{item['unit']}) ...", end=" ")
        result = api_post("/api/admin/processing-items", item)
        if result:
            print(f"✅ id={result.get('id')}")
            success_count += 1
        else:
            print("❌ 失败")
            fail_count += 1

    print(f"\n✅ 加工项创建完成: 成功 {success_count}, 失败 {fail_count}, 跳过 {skip_count}")

    # ── Step 3: 验证 ──
    print("\n[Step 3] 验证数据...")
    cats = api_get("/api/admin/processing-categories")
    if cats:
        print(f"  加工分类数量: {len(cats)}")
        for c in cats:
            print(f"    - {c.get('name')} (id={c.get('id')}, status={c.get('status')})")

    items_resp = api_get("/api/admin/processing-items?size=50")
    if items_resp:
        records = items_resp.get("records", [])
        print(f"  加工项数量: {items_resp.get('total', len(records))}")
        for it in records:
            print(f"    - {it.get('name')} | {it.get('pricingMethod')} | ¥{it.get('unitPrice')}/{it.get('unit')} | {it.get('processingDays')}天")

    print("\n" + "=" * 60)
    print("导入完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
