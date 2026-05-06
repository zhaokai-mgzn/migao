#!/usr/bin/env python3
"""
Import product2.xlsx data into admin-api.
Handles strict OOXML format by manually parsing ZIP/XML.
"""

import json
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional

import requests

# ── Config ──────────────────────────────────────────────────────────────────
API_BASE = "http://localhost:8080"
HEADERS = {
    "X-Service-Token": "25c6dcbe8f5987638a87741441b0e001d633529d50e2f29df7dcc954b888846b",
    "X-Tenant-Id": "tenant_default",
    "Content-Type": "application/json",
}
EXCEL_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "previews" / "product2.xlsx"
BATCH_LOG_INTERVAL = 50  # print progress every N products


# ── Excel parsing (strict OOXML) ───────────────────────────────────────────
def col_letter_to_index(col: str) -> int:
    """Convert column letter(s) to 0-based index. A->0, B->1, ..., Z->25, AA->26."""
    result = 0
    for ch in col.upper():
        result = result * 26 + (ord(ch) - ord('A') + 1)
    return result - 1


def parse_cell_ref(ref: str):
    """Return (col_index, row_number) from a cell reference like 'A1'."""
    m = re.match(r"([A-Z]+)(\d+)", ref)
    if not m:
        return None, None
    return col_letter_to_index(m.group(1)), int(m.group(2))


def parse_excel(path: Path) -> List[Dict]:
    """Parse strict OOXML xlsx, return list of row dicts with keys A-F."""
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()

        # ── shared strings ──────────────────────────────────────────────
        shared_strings: list[str] = []
        ss_path = next((n for n in names if n.endswith("sharedStrings.xml")), None)
        if ss_path:
            tree = ET.parse(zf.open(ss_path))
            root = tree.getroot()
            ns = re.match(r"\{(.+?)\}", root.tag)
            ns_uri = ns.group(1) if ns else ""
            ns_map = {"s": ns_uri} if ns_uri else {}
            for si in root.findall("s:si", ns_map) if ns_map else root:
                texts = []
                for t_el in si.iter():
                    if t_el.tag.endswith("}t") or t_el.tag == "t":
                        if t_el.text:
                            texts.append(t_el.text)
                shared_strings.append("".join(texts))

        # ── sheet1 ──────────────────────────────────────────────────────
        sheet_path = next(
            (n for n in names if re.search(r"worksheets/sheet1\.xml$", n, re.I)),
            None,
        )
        if not sheet_path:
            raise FileNotFoundError("sheet1.xml not found in xlsx")

        tree = ET.parse(zf.open(sheet_path))
        root = tree.getroot()
        ns = re.match(r"\{(.+?)\}", root.tag)
        ns_uri = ns.group(1) if ns else ""
        ns_map = {"s": ns_uri} if ns_uri else {}

        rows_data: dict[int, dict[int, str]] = {}

        for row_el in root.iter("{%s}row" % ns_uri if ns_uri else "row"):
            for c_el in row_el:
                tag = c_el.tag
                if not (tag.endswith("}c") or tag == "c"):
                    continue
                ref = c_el.get("r")
                if not ref:
                    continue
                col_idx, row_num = parse_cell_ref(ref)
                if col_idx is None:
                    continue

                cell_type = c_el.get("t", "")
                v_el = None
                for child in c_el:
                    if child.tag.endswith("}v") or child.tag == "v":
                        v_el = child
                        break

                if v_el is None or v_el.text is None:
                    continue

                raw = v_el.text.strip()
                if cell_type == "s":
                    idx = int(raw)
                    value = shared_strings[idx] if idx < len(shared_strings) else raw
                else:
                    value = raw

                rows_data.setdefault(row_num, {})[col_idx] = value

    # Build structured rows (skip header row 1)
    col_keys = {0: "name", 1: "spec", 2: "category", 3: "unit", 4: "price", 5: "product_type"}
    result = []
    for row_num in sorted(rows_data):
        if row_num <= 1:
            continue  # skip header
        cells = rows_data[row_num]
        row = {}
        for col_idx, key in col_keys.items():
            row[key] = cells.get(col_idx, "").strip() if col_idx in cells else ""
        if row.get("name"):
            result.append(row)
    return result


# ── API helpers ─────────────────────────────────────────────────────────────
def api_get(path: str, params: Optional[Dict] = None):
    resp = requests.get(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def api_post(path: str, body: dict):
    resp = requests.post(f"{API_BASE}{path}", headers=HEADERS, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Import logic ────────────────────────────────────────────────────────────
def fetch_existing_categories() -> Dict[str, str]:
    """Return {name: id} of already-existing categories."""
    mapping: Dict[str, str] = {}
    try:
        data = api_get("/api/admin/categories/tree")
        # data could be wrapped in {"data": [...]} or be a list directly
        items = data if isinstance(data, list) else data.get("data", data.get("children", []))
        if isinstance(items, list):
            for cat in items:
                if isinstance(cat, dict):
                    cname = cat.get("name", "")
                    cid = cat.get("id", "")
                    if cname and cid:
                        mapping[cname] = cid
                    # also check children
                    for child in cat.get("children", []):
                        if isinstance(child, dict) and child.get("name") and child.get("id"):
                            mapping[child["name"]] = child["id"]
    except Exception as e:
        print(f"[WARN] Failed to fetch existing categories: {e}")
    return mapping


def create_categories(category_names: List[str]) -> Dict[str, str]:
    """Create categories via API, return {name: id} mapping."""
    existing = fetch_existing_categories()
    mapping: Dict[str, str] = {}
    created = 0
    skipped = 0

    for i, name in enumerate(sorted(category_names)):
        if name in existing:
            mapping[name] = existing[name]
            skipped += 1
            print(f"  [{i+1}/{len(category_names)}] Category '{name}' already exists (id={existing[name][:8]}...)")
            continue

        body = {
            "name": name,
            "parentId": None,
            "level": 1,
            "sortOrder": i,
            "status": "active",
        }
        try:
            resp = api_post("/api/admin/categories", body)
            # extract ID from response
            cat_data = resp.get("data", resp) if isinstance(resp, dict) else resp
            cat_id = cat_data.get("id", "") if isinstance(cat_data, dict) else ""
            if not cat_id:
                # try other common response shapes
                cat_id = resp.get("id", "")
            mapping[name] = cat_id
            created += 1
            print(f"  [{i+1}/{len(category_names)}] Created category '{name}' (id={str(cat_id)[:8]}...)")
        except requests.HTTPError as e:
            # If 409 or duplicate, try to fetch again
            if e.response is not None and e.response.status_code in (409, 400):
                print(f"  [{i+1}/{len(category_names)}] Category '{name}' may already exist, refreshing...")
                refreshed = fetch_existing_categories()
                if name in refreshed:
                    mapping[name] = refreshed[name]
                    skipped += 1
                    continue
            print(f"  [ERROR] Failed to create category '{name}': {e}")
            raise

    print(f"\n[Categories] Created: {created}, Skipped (existing): {skipped}, Total mapped: {len(mapping)}")
    return mapping


def import_products(rows: List[Dict], category_map: Dict[str, str]):
    """Create products via API."""
    total = len(rows)
    success = 0
    errors = 0
    skipped_count = 0

    print(f"\n{'='*60}")
    print(f"Starting product import: {total} products")
    print(f"{'='*60}\n")

    for i, row in enumerate(rows):
        # Parse price (API requires > 0, default to 0.01 for items without price)
        try:
            price = float(Decimal(row["price"])) if row["price"] else 0.0
        except (InvalidOperation, ValueError):
            price = 0.0
        if price <= 0:
            price = 0.01

        cat_id = category_map.get(row["category"], "")
        if not cat_id and row["category"]:
            print(f"  [WARN] Row {i+1}: category '{row['category']}' not found in mapping, skipping...")
            errors += 1
            continue

        desc_parts = []
        if row["spec"]:
            desc_parts.append(f"规格：{row['spec']}")
        if row["unit"]:
            desc_parts.append(f"单位：{row['unit']}")
        if row["product_type"]:
            desc_parts.append(f"产品类型：{row['product_type']}")
        description = "，".join(desc_parts)

        body = {
            "name": row["name"],
            "categoryId": cat_id,
            "basePrice": price,
            "description": description,
            "status": "active",
        }

        try:
            api_post("/api/admin/products", body)
            success += 1
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            # Treat 409 (duplicate) as success
            if e.response is not None and e.response.status_code == 409:
                skipped_count += 1
            else:
                errors += 1
                detail = ""
                try:
                    detail = e.response.text[:200] if e.response is not None else ""
                except Exception:
                    pass
                print(f"  [ERROR] Row {i+1} '{row['name']}': HTTP {status} - {detail}")
        except Exception as e:
            errors += 1
            print(f"  [ERROR] Row {i+1} '{row['name']}': {e}")

        if (i + 1) % BATCH_LOG_INTERVAL == 0 or (i + 1) == total:
            print(f"  Progress: {i+1}/{total} ({success} ok, {skipped_count} skip, {errors} err)")

    print(f"\n{'='*60}")
    print(f"Import complete: {success} created, {skipped_count} skipped (dup), {errors} failed out of {total}")
    print(f"{'='*60}")
    return success, errors


def verify_import():
    """Quick verification: check product/category counts via API."""
    print("\n── Verification ──")
    try:
        cats = api_get("/api/admin/categories/tree")
        cat_list = cats if isinstance(cats, list) else cats.get("data", [])
        print(f"  Categories in system: {len(cat_list) if isinstance(cat_list, list) else '?'}")
    except Exception as e:
        print(f"  [WARN] Could not verify categories: {e}")

    try:
        products = api_get("/api/admin/products", params={"page": 1, "size": 1})
        if isinstance(products, dict):
            total = products.get("data", {}).get("total", products.get("total", "?"))
            print(f"  Products in system: {total}")
        else:
            print(f"  Products response: {str(products)[:200]}")
    except Exception as e:
        print(f"  [WARN] Could not verify products: {e}")


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print(f"Excel file: {EXCEL_PATH}")
    if not EXCEL_PATH.exists():
        print(f"[FATAL] File not found: {EXCEL_PATH}")
        sys.exit(1)

    # Step 1: Parse Excel
    print("\n[Step 1] Parsing Excel (strict OOXML)...")
    rows = parse_excel(EXCEL_PATH)
    print(f"  Parsed {len(rows)} data rows")

    if not rows:
        print("[FATAL] No data rows found")
        sys.exit(1)

    # Quick stats
    categories = sorted(set(r["category"] for r in rows if r["category"]))
    product_types = {}
    for r in rows:
        pt = r.get("product_type", "unknown")
        product_types[pt] = product_types.get(pt, 0) + 1
    print(f"  Unique categories: {len(categories)}")
    print(f"  Product types: {product_types}")
    print(f"  Sample: {rows[0]}")

    # Step 2: Create categories
    print(f"\n[Step 2] Creating {len(categories)} categories...")
    category_map = create_categories(categories)

    # Check all categories mapped
    unmapped = [c for c in categories if c not in category_map]
    if unmapped:
        print(f"[WARN] {len(unmapped)} categories could not be mapped: {unmapped[:5]}...")

    # Step 3: Import products
    print(f"\n[Step 3] Importing {len(rows)} products...")
    t0 = time.time()
    success, errors = import_products(rows, category_map)
    elapsed = time.time() - t0
    print(f"  Time: {elapsed:.1f}s ({len(rows)/max(elapsed,0.1):.0f} products/s)")

    # Step 4: Verify
    verify_import()

    if errors > 0:
        print(f"\n[RESULT] Completed with {errors} errors")
        sys.exit(1)
    else:
        print(f"\n[RESULT] All {success} products imported successfully!")


if __name__ == "__main__":
    main()
