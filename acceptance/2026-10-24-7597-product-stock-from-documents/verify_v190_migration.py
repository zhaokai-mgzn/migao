"""V189 迁移的真库验收脚本（issue #7597）：本地起一个临时 PG ⇒ 建 schema ⇒ 造 6 种库存形态 ⇒
跑迁移两遍 ⇒ 断言「清零 / 真实单据保留 / 盘点计入 / 负数 clamp / 补偿台账行 / 幂等 / 账实一致」。

用法（需要 initdb / pg_ctl / psql 在 PATH 里）：
    python3 acceptance/2026-10-24-7597-product-stock-from-documents/verify_v190_migration.py

为什么要有它：CI 的迁移判据是**静态**的（正则 + 指纹 + 幂等文本），没有任何测试真的在 PG 上执行
V189；而这一单是**破坏性数据迁移**（用户在 issue 里明确「风险最高」）⇒ 必须有一份可重放的执行证据。
"""
import os, subprocess, sys, time, shutil, pathlib

WT = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
PGDATA = "/tmp/v189pg"
PORT = "55499"
SOCK = "/tmp/v189pg"
USER = subprocess.check_output(["whoami"], text=True).strip()

def run(cmd, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, **kw)

def psql(db, sql):
    p = run(["psql", "-h", SOCK, "-p", PORT, "-U", USER, "-d", db, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-F", "|", "-c", sql])
    if p.returncode != 0:
        print("SQL FAILED:", sql, "\n", p.stderr)
        sys.exit(1)
    return [ln for ln in p.stdout.strip().splitlines() if ln]

shutil.rmtree(PGDATA, ignore_errors=True)
assert run(["initdb", "-D", PGDATA, "-A", "trust", "-U", USER]).returncode == 0
assert run(["pg_ctl", "-D", PGDATA, "-o", f"-p {PORT} -k {SOCK} -c listen_addresses=''", "-l", "/tmp/v189pg.log", "start"]).returncode == 0
time.sleep(1)
try:
    assert run(["createdb", "-h", SOCK, "-p", PORT, "-U", USER, "v189"]).returncode == 0
    p = run(["psql", "-h", SOCK, "-p", PORT, "-U", USER, "-d", "v189", "-v", "ON_ERROR_STOP=1", "-q", "-f", f"{WT}/backend/admin-api/src/main/resources/db/init/schema.sql"])
    assert p.returncode == 0, p.stderr[-2000:]

    # ---- 夹具：5 种形态（多租户 1；schema 自带 tenants 种子）----
    psql("v189", """
    INSERT INTO products (id, tenant_id, name, stock) VALUES
      ('p1','1','手工库存商品',30), ('p2','1','入库+出库商品',100),
      ('p3','1','入库+手工调整商品',30), ('p4','1','入库+批次盘点商品',0),
      ('p5','1','无 SKU 商品',77), ('p6','1','入库不足商品',0);
    INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock) VALUES
      (101,1,'p1','2.8m',168,30),
      (102,1,'p2','2.8m',168,100),
      (103,1,'p3','2.8m',168,30),
      (104,1,'p4','2.8m',168,0),
      (106,1,'p6','2.8m',168,0);
    INSERT INTO stock_ledger_entries (tenant_id, product_id, sku_id, sku_code, delta, before_qty, after_qty, reason, note, operator) VALUES
      (1,'p2',102,'SG-102', 100,  0, 100,'inbound', '入库单 RK-1','system'),
      (1,'p2',102,'SG-102', -10,100,  90,'order',   '订单 DD-1','system'),
      (1,'p3',103,'SG-103',  50,  0,  50,'inbound', '入库单 RK-2','system'),
      (1,'p3',103,'SG-103', -20, 50,  30,'manual',  '手工调整','system'),
      (1,'p4',104,'SG-104',  20,  0,  20,'inbound', '入库单 RK-3','system'),
      (1,'p4',104,'SG-104',   5, 20,  25,'manual',  '库存盘点：批次 PC-1 盘盈 5','system'),
      (1,'p6',106,'SG-106',   5,  0,   5,'inbound', '入库单 RK-4','system'),
      (1,'p6',106,'SG-106', -12,  5,  -7,'order',   '订单 DD-2','system');
    """)

    mig = pathlib.Path(f"{WT}/backend/admin-api/src/main/resources/db/migration/V190__reset_product_stock_to_real_documents.sql").read_text()

    def apply_migration():
        p = subprocess.run(["psql", "-h", SOCK, "-p", PORT, "-U", USER, "-d", "v189", "-v", "ON_ERROR_STOP=1", "-q", "-f", "-"],
                           input=mig, text=True, capture_output=True)
        assert p.returncode == 0, p.stderr[-3000:]

    apply_migration()

    stocks = psql("v189", "SELECT id, stock FROM product_skus WHERE id IN (101,102,103,104,106) ORDER BY id")
    expect = ["101|0.0", "102|90.0", "103|50.0", "104|25.0", "106|0.0"]
    assert stocks == expect, f"SKU 库存重算不符\n得到 {stocks}\n期望 {expect}"

    prod = psql("v189", "SELECT id, stock FROM products WHERE id IN ('p1','p2','p3','p4','p5','p6') ORDER BY id")
    expect_prod = ["p1|0.0", "p2|90.0", "p3|50.0", "p4|25.0", "p5|0.0", "p6|0.0"]
    assert prod == expect_prod, f"products.stock 汇总不符\n得到 {prod}\n期望 {expect_prod}"

    rows = psql("v189", "SELECT sku_id, before_qty, after_qty, delta, reason, note FROM stock_ledger_entries WHERE note LIKE '商品不再设置库存%' ORDER BY sku_id")
    expect_rows = [
        "101|30.0|0.0|-30.0|manual|商品不再设置库存：按真实单据重算（issue #7597）",
        "102|100.0|90.0|-10.0|manual|商品不再设置库存：按真实单据重算（issue #7597）",
        "103|30.0|50.0|20.0|manual|商品不再设置库存：按真实单据重算（issue #7597）",
        "104|0.0|25.0|25.0|manual|商品不再设置库存：按真实单据重算（issue #7597）",
    ]
    assert rows == expect_rows, f"补偿台账行不符\n得到 {rows}\n期望 {expect_rows}"

    # 幂等：第二遍 0 行新增、0 行变化
    before_cnt = psql("v189", "SELECT count(*) FROM stock_ledger_entries")[0]
    apply_migration()
    after_cnt = psql("v189", "SELECT count(*) FROM stock_ledger_entries")[0]
    assert before_cnt == after_cnt, f"迁移不幂等：{before_cnt} -> {after_cnt}"
    stocks2 = psql("v189", "SELECT id, stock FROM product_skus WHERE id IN (101,102,103,104,106) ORDER BY id")
    assert stocks2 == expect, f"第二遍改动了库存：{stocks2}"

    # 链不变量：补偿行 after == 库里 stock
    bad = psql("v189", """
      SELECT e.sku_id FROM stock_ledger_entries e JOIN product_skus s ON s.id = e.sku_id
      WHERE e.note LIKE '商品不再设置库存%' AND e.after_qty <> s.stock""")
    assert bad == [], f"台账 after 与库内库存不一致：{bad}"

    print("✅ V189 真库验证通过：清零 / 真实单据保留 / 盘点计入 / 负数 clamp / 补偿行 / 幂等 / 账实一致")
finally:
    run(["pg_ctl", "-D", PGDATA, "-m", "immediate", "stop"])
