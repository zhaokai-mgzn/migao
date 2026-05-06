#!/usr/bin/env python3
"""
清理数据库中的重复商品和分类数据。

由于 product2.xlsx 导入时部分失败后进行了第二次完整运行，
导致系统中存在重复数据。本脚本通过 admin-api 清理这些重复项。
"""

import requests
import time
from collections import defaultdict

BASE_URL = "http://localhost:8080"
HEADERS = {
    "X-Service-Token": "25c6dcbe8f5987638a87741441b0e001d633529d50e2f29df7dcc954b888846b",
    "X-Tenant-Id": "tenant_default",
    "Content-Type": "application/json",
}

PAGE_SIZE = 200


def api_get(path, params=None):
    resp = requests.get(f"{BASE_URL}{path}", headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise Exception(f"API error: {data}")
    return data["data"]


def api_delete(path):
    resp = requests.delete(f"{BASE_URL}{path}", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise Exception(f"API delete error: {data}")
    return data


def api_put(path, body):
    resp = requests.put(f"{BASE_URL}{path}", headers=HEADERS, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise Exception(f"API put error: {data}")
    return data


# ========== Step 1: 获取所有商品 ==========
def fetch_all_products():
    """分页获取所有商品"""
    all_products = []
    page = 1
    while True:
        data = api_get("/api/admin/products", {"page": page, "size": PAGE_SIZE})
        items = data.get("items", [])
        total = data.get("total", 0)
        all_products.extend(items)
        print(f"  获取商品第 {page} 页，本页 {len(items)} 条，累计 {len(all_products)}/{total}")
        if len(all_products) >= total or len(items) == 0:
            break
        page += 1
    return all_products


# ========== Step 2: 商品去重 ==========
def dedup_products():
    print("=" * 60)
    print("Step 1: 商品去重")
    print("=" * 60)

    print("\n[1/3] 获取所有商品...")
    products = fetch_all_products()
    print(f"  总计获取 {len(products)} 条商品")

    print("\n[2/3] 按名称分组，识别重复...")
    groups = defaultdict(list)
    for p in products:
        groups[p["name"]].append(p)

    to_delete = []
    for name, items in groups.items():
        if len(items) > 1:
            # 按 createdAt 排序，保留最早的
            items.sort(key=lambda x: x["createdAt"])
            keep = items[0]
            duplicates = items[1:]
            to_delete.extend(duplicates)

    dup_names = sum(1 for items in groups.values() if len(items) > 1)
    print(f"  唯一商品名称数: {len(groups)}")
    print(f"  存在重复的名称数: {dup_names}")
    print(f"  需要删除的重复商品数: {len(to_delete)}")
    print(f"  将保留的商品数: {len(products) - len(to_delete)}")

    print(f"\n[3/3] 删除 {len(to_delete)} 条重复商品...")
    deleted = 0
    errors = 0
    for i, p in enumerate(to_delete):
        try:
            api_delete(f"/api/admin/products/{p['id']}")
            deleted += 1
        except Exception as e:
            errors += 1
            print(f"  !! 删除失败 [{p['name']}] id={p['id']}: {e}")

        if (i + 1) % 100 == 0 or (i + 1) == len(to_delete):
            print(f"  进度: {i + 1}/{len(to_delete)} (成功={deleted}, 失败={errors})")

    print(f"\n商品去重完成: 删除 {deleted} 条, 失败 {errors} 条")
    return deleted


# ========== Step 3: 分类去重 ==========
def dedup_categories():
    print("\n" + "=" * 60)
    print("Step 2: 分类去重")
    print("=" * 60)

    print("\n[1/4] 获取所有分类...")
    categories = api_get("/api/admin/categories")
    print(f"  总计 {len(categories)} 个分类")

    print("\n[2/4] 获取去重后的商品（用于确认分类引用）...")
    products = fetch_all_products()
    # 统计每个 categoryId 被引用的商品数
    cat_ref_count = defaultdict(int)
    for p in products:
        if p.get("categoryId"):
            cat_ref_count[p["categoryId"]] += 1

    print(f"  当前商品数: {len(products)}")
    print(f"  被引用的分类ID数: {len(cat_ref_count)}")

    print("\n[3/4] 按名称分组，识别重复分类...")
    groups = defaultdict(list)
    for c in categories:
        groups[c["name"]].append(c)

    dup_names = sum(1 for items in groups.values() if len(items) > 1)
    print(f"  唯一分类名称数: {len(groups)}")
    print(f"  存在重复的名称数: {dup_names}")

    print("\n[4/4] 处理重复分类...")
    deleted = 0
    errors = 0
    reassigned = 0

    for name, items in groups.items():
        if len(items) <= 1:
            continue

        # 找出被商品引用最多的分类作为保留项
        items.sort(key=lambda x: (-cat_ref_count.get(x["id"], 0), x["createdAt"]))
        keep = items[0]
        duplicates = items[1:]

        # 对于每个要删除的重复分类，先把引用它的商品迁移到保留的分类
        for dup in duplicates:
            ref_count = cat_ref_count.get(dup["id"], 0)
            if ref_count > 0:
                # 需要把引用该分类的商品迁移到 keep
                migrated = migrate_products_category(products, dup["id"], keep)
                reassigned += migrated
                print(f"  迁移 [{name}]: {migrated} 个商品从 {dup['id'][:8]}... -> {keep['id'][:8]}...")

            # 删除重复分类
            try:
                api_delete(f"/api/admin/categories/{dup['id']}")
                deleted += 1
            except Exception as e:
                errors += 1
                print(f"  !! 删除分类失败 [{name}] id={dup['id']}: {e}")

    print(f"\n分类去重完成: 删除 {deleted} 个, 失败 {errors} 个, 商品迁移 {reassigned} 个")
    return deleted


def migrate_products_category(products, old_cat_id, keep_cat):
    """将引用 old_cat_id 的商品迁移到 keep_cat"""
    count = 0
    for p in products:
        if p.get("categoryId") == old_cat_id:
            try:
                api_put(f"/api/admin/products/{p['id']}", {
                    "name": p["name"],
                    "categoryId": keep_cat["id"],
                    "basePrice": p.get("basePrice") or p.get("price", 0),
                    "description": p.get("description", ""),
                    "status": p.get("status", "active"),
                })
                count += 1
            except Exception as e:
                print(f"    !! 迁移商品失败 [{p['name']}]: {e}")
    return count


# ========== Step 4: 验证结果 ==========
def verify():
    print("\n" + "=" * 60)
    print("Step 3: 验证结果")
    print("=" * 60)

    # 验证商品数量
    data = api_get("/api/admin/products", {"page": 1, "size": 1})
    product_count = data["total"]
    print(f"  商品总数: {product_count} (期望约 1930)")

    # 验证分类数量
    categories = api_get("/api/admin/categories")
    cat_count = len(categories)
    print(f"  分类总数: {cat_count} (期望约 56)")

    # 检查是否还有重复
    products = fetch_all_products()
    name_counts = defaultdict(int)
    for p in products:
        name_counts[p["name"]] += 1
    dup_products = {n: c for n, c in name_counts.items() if c > 1}
    if dup_products:
        print(f"\n  ⚠ 仍有 {len(dup_products)} 个商品名称存在重复:")
        for n, c in list(dup_products.items())[:5]:
            print(f"    - {n}: {c} 条")
    else:
        print("\n  ✓ 商品无重复")

    cat_names = defaultdict(int)
    for c in categories:
        cat_names[c["name"]] += 1
    dup_cats = {n: c for n, c in cat_names.items() if c > 1}
    if dup_cats:
        print(f"  ⚠ 仍有 {len(dup_cats)} 个分类名称存在重复")
    else:
        print("  ✓ 分类无重复")

    ok = product_count <= 1950 and cat_count <= 60 and not dup_products and not dup_cats
    print(f"\n  {'✓ 验证通过!' if ok else '⚠ 验证未完全通过，请检查'}")


if __name__ == "__main__":
    start = time.time()
    print("开始清理重复数据...\n")

    dedup_products()
    dedup_categories()
    verify()

    elapsed = time.time() - start
    print(f"\n总耗时: {elapsed:.1f} 秒")
