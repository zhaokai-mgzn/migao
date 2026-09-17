#!/usr/bin/env python3
"""OR-029 证据①：从 fixture seed 实测（静态解析真实 DDL/DML）该商品的规格/库存/加工项真值。

不连库也能"实测"：seed 是**幂等 SQL 源**，本脚本按 SQL 的 VALUES/WHERE 事实解析，
输出 5 类真值 + 每个真值的 seed 行号，供人工/评审逐项复核。
"""
import re, sys, pathlib

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
SEED = ROOT / "tests/agent_eval/fixtures/mibao_eval_seed.sql"
SEED_C = ROOT / "tests/agent_eval/fixtures/xiaobu_eval_seed.sql"
PROD_ID = "prod_eval_2699"

def lines(p):
    return p.read_text(encoding="utf-8").splitlines()

def block(text, start_pat, end_pat="ON CONFLICT"):
    """取 start_pat 起的语句文本（到 end_pat 或分号）"""
    m = re.search(start_pat, text)
    if not m:
        return "", 0
    rest = text[m.start():]
    e = rest.find(end_pat)
    if e == -1:
        e = rest.find(";")
    return rest[:e], text[:m.start()].count("\n") + 1

def find(pat, text, label, base_line=1):
    out = []
    for i, ln in enumerate(text.splitlines(), base_line):
        if re.search(pat, ln):
            out.append((i, ln.strip()))
    return out

mb = SEED.read_text(encoding="utf-8")
xb = SEED_C.read_text(encoding="utf-8")

print("=" * 78)
print("OR-029 证据① seed 真值实测")
print(f"  源: tests/agent_eval/fixtures/mibao_eval_seed.sql (sha256 8007ed8ded0571a5…)")
print(f"      + tests/agent_eval/fixtures/xiaobu_eval_seed.sql (加工项目录)")
print(f"  锚定: origin/main@c8ae87e4 / seed blob 698aa7b77c3c0be0a467b0c7e52548f334fbdf5b")
print("=" * 78)

# ── 1. 商品 ──
prod, pl = block(mb, r"INSERT INTO products[\s\S]*?'prod_eval_2699'")
m = re.search(r"'(prod_eval_2699)',\s*1,\s*'([^']+)',\s*'([^']+)',\s*([\d.]+),\s*'[^']*',\s*'\[\]'::jsonb,\s*'\[\]'::jsonb,\s*(\d+),\s*(\d+),\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)'", mb)
print("\n【1】商品（products）")
print(f"  行号 {pl}~: id={m.group(1)} name={m.group(2)} category={m.group(3)} base_price={m.group(4)} "
      f"stock={m.group(5)} unit={m.group(8)} pricing={m.group(9)} sku_code={m.group(10)} status={m.group(7)}")

# ── 2. 规格（product_colors）──
print("\n【2】规格（product_colors）")
cb, cl = block(mb, r"INSERT INTO product_colors")
for i, ln in enumerate(cb.splitlines()):
    g = re.search(r"'prod_eval_2699',\s*'([^']+)',\s*'(#[0-9A-Fa-f]+)',\s*(\d+)", ln)
    if g:
        print(f"  行号 {cl + i}: {PROD_ID} → color_name={g.group(1)!r} hex={g.group(2)} sort={g.group(3)}")

# ── 3. SKU/库存（product_skus）──
print("\n【3】SKU 与库存（product_skus，按颜色 × bulk_cut × 2.8 生成）")
sb, sl = block(mb, r"INSERT INTO product_skus")
for i, ln in enumerate(sb.splitlines()):
    if "SELECT 1, pc.product_id" in ln:
        g = re.search(r"'([a-z_]+)',\s*'([\d.]+)',\s*p\.base_price,\s*(\d+),", ln)
        print(f"  行号 {sl + i}: selling_method={g.group(1)} door_width={g.group(2)} "
              f"price=p.base_price(=23.80) stock(每 SKU)={g.group(3)}")
    if "FROM product_colors" in ln or "WHERE pc.product_id" in ln:
        print(f"  行号 {sl + i}: {ln.strip()}")

# ── 4. 加工项目录 ──
print("\n【4】加工项目录（processing_items）")
for src, label in ((xb, "xiaobu_eval_seed.sql"), (mb, "mibao_eval_seed.sql")):
    bb, bl2 = block(src, r"INSERT INTO processing_items")
    for i, ln in enumerate(bb.splitlines()):
        g = re.search(r"\('(pi_eval_\w+)',\s*1,\s*'([^']+)',\s*'(\w+)',\s*'(\w+)',\s*([\d.]+),\s*'([^']+)'", ln)
        if g:
            print(f"  {label} 行号 {bl2 + i}: {g.group(1):22s} {g.group(2):8s} "
                  f"pricing={g.group(4):9s} unit_price=¥{g.group(5)}/{g.group(6)}")

# ── 5. 商品 ↔ 加工项关联 ──
print("\n【5】商品 ↔ 加工项关联（product_processing_items，本商品绑定了哪些加工项）")
ab, al = block(mb, r"-- 商品 ↔ 加工项关联（OR-016 的询问前提）")
bindings = []
for i, ln in enumerate(ab.splitlines()):
    g = re.search(r"\('prod_eval_2699',\s*'(pi_eval_\w+)',\s*(\d+)\)", ln)
    if g:
        bindings.append(g.group(1))
        print(f"  行号 {al + i}: {PROD_ID} → {g.group(1)} (sort={g.group(2)})")
ab2, al2 = block(mb, r"关联到 B 端常用商品")
for i, ln in enumerate(ab2.splitlines()):
    if "'pi_eval_embroidery'" in ln:
        print(f"  行号 {al2 + i}: {ln.strip()}")

# ── 6. 客户 ──
print("\n【6】客户（customer_profiles）")
kb, kl = block(mb, r"INSERT INTO customer_profiles")
for i, ln in enumerate(kb.splitlines()):
    g = re.search(r"\('(cust_eval_\w+)',\s*1,\s*'([^']+)',\s*'(\d+)'", ln)
    if g:
        print(f"  行号 {kl + i}: id={g.group(1)} nickname={g.group(2)!r} phone={g.group(3)}")
print("\n【6b】客户是否存在于 seed：")
for kw in ("赵凯", "13456000919", "张三", "13800138000"):
    hits = [i for i, ln in enumerate(mb.splitlines(), 1) if kw in ln]
    print(f"  {kw:14s} 命中 seed 行号: {hits or '（0 命中）'}")
print("=" * 78)
