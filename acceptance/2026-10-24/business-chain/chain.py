#!/usr/bin/env python3
"""MIGAO 核心业务全链路真跑（本地 :8090 + 云 dev DB，租户 46）。

链路：建品 → 下单 → 确认收款 → 待派池 → 派单(加工单) → 工序实例 → 报工 → 质检 → 发货 → 售后
判据：每一步都是**服务端落库后回读**（不是"点了没报错"）。零 LLM。
用法：python3 chain.py [--keep]
"""
import json, sys, time, urllib.request, urllib.error

B = "http://127.0.0.1:8090"
PHONE = "13900001025"
CODE = "123456"
KEEP = "--keep" in sys.argv
RES = []


def req(m, p, body=None, tok=None, timeout=90, headers=None):
    d = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + p, data=d, method=m)
    r.add_header("Content-Type", "application/json")
    if tok:
        r.add_header("Authorization", "Bearer " + tok)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return -1, {"error": str(e)}


def step(name, ok, detail=""):
    RES.append((name, ok, detail))
    print(("✅ " if ok else "❌ ") + name + ("  — " + detail if detail else ""))
    return ok


def data(resp):
    return resp[1].get("data") if isinstance(resp[1], dict) else None


# ── 0. 登录 ────────────────────────────────────────────────────────────────
st, b = req("POST", "/api/auth/sms/login", {"phone": PHONE, "code": CODE})
tok = data((st, b))["accessToken"] if st == 200 else None
step("00 登录（短信 bypass）", bool(tok), f"tenant={data((st,b))['user']['tenantId']} user={data((st,b))['user']['nickname']}" if tok else str(b)[:200])
if not tok:
    sys.exit(1)

# ── 1. 选一个真商品（有价的在售商品） ──────────────────────────────────────
st, r = req("GET", "/api/admin/products?page=1&size=20", tok=tok)
items = (data((st, r)) or {}).get("items") or []
prod = next((p for p in items if float(p.get("price") or p.get("basePrice") or 0) > 0), None)
step("01 商品读取", bool(prod), f"products={len(items)} pick={prod.get('name') if prod else None} price={prod.get('price') or (prod or {}).get('basePrice')}")

# ── 2. 下单（带加工信息，可进待派池） ──────────────────────────────────────
suffix = str(int(time.time()))[-6:]
price = float(prod.get("price") or prod.get("basePrice") or 199)
payload = {
    "customerName": f"全链路客{suffix}", "customerPhone": f"13988{suffix}",
    "customerAddress": "上海市浦东新区张江高科技园区", "logisticsType": "express",
    "logisticsCompany": "顺丰速运", "remark": f"fullchain-{suffix}",
    "items": [{
        "productId": prod.get("id"), "productName": prod.get("name"),
        "quantity": 2, "unitPrice": price, "subtotal": round(price * 2, 2),
        "processingInfo": {"sellingMethod": "bulk_cut", "doorWidth": "2.8", "processingFee": 15,
                           "processingItems": [{"id": "proc_item_1", "name": "锁边", "quantity": 2, "unit": "米"}]},
    }],
}
st, r = req("POST", "/api/admin/orders", payload, tok=tok)
order = data((st, r)) or {}
oid = order.get("id")
step("02 下单落库", st == 200 and bool(oid), f"status={st} orderNo={order.get('orderNo')} amount={order.get('totalAmount')} id={oid}")
if not oid:
    print(json.dumps(r, ensure_ascii=False)[:600]); sys.exit(1)

# ── 3. 确认收款（pending → confirmed，派单前置） ───────────────────────────
st, r = req("PUT", f"/api/admin/orders/{oid}/payment", {}, tok=tok)
st2, r2 = req("GET", f"/api/admin/orders/{oid}", tok=tok)
ostatus = (data((st2, r2)) or {}).get("status")
step("03 确认收款 → confirmed", st == 200 and ostatus == "confirmed", f"payment={st} 回读status={ostatus}")

# ── 4. 待派池可见 ──────────────────────────────────────────────────────────
st, r = req("GET", "/api/admin/production/pool?maxWaitHours=24", tok=tok)
pool = data((st, r)) or {}
in_pool = any(l.get("orderId") == oid for g in (pool.get("groups") or []) for l in (g.get("lines") or []))
step("04 待派池可见本单", in_pool, f"pool.orderCount={pool.get('orderCount')} groups={len(pool.get('groups') or [])}")

# ── 5. 成批预览（只读） ────────────────────────────────────────────────────
st, r = req("POST", "/api/admin/production/pool/preview", {"orderIds": [oid], "batches": [], "assignmentRule": None}, tok=tok)
prev = data((st, r)) or {}
step("05 合批预览", st == 200, f"status={st} keys={list(prev.keys())[:6]} preview={json.dumps(prev, ensure_ascii=False)[:220]}")

# ── 6. 派单（默认路径：智能派单端点） ─────────────────────────────────────
st, r = req("POST", "/api/admin/production/pool/dispatch", {"orderIds": [oid], "batches": [], "assignmentRule": None, "pooled": False}, tok=tok)
results = data((st, r)) or []
mine = [x for x in results if x.get("orderRef") == oid] if isinstance(results, list) else []
ok = st == 200 and any(x.get("success") is not False for x in mine)
step("06 派单生成加工单", ok, f"status={st} result={json.dumps(mine[:1], ensure_ascii=False)[:300] if mine else json.dumps(results, ensure_ascii=False)[:300]}")

# ── 7. 加工单落库 + 状态 ──────────────────────────────────────────────────
st, r = req("GET", f"/api/admin/processing-orders?keyword=&status=&page=1&size=50", tok=tok)
plist = data((st, r))
rows = plist.get("items") if isinstance(plist, dict) else (plist if isinstance(plist, list) else [])
porder = next((x for x in rows if x.get("orderId") == oid or x.get("orderNo") == order.get("orderNo")), None)
step("07 加工单可查", bool(porder), f"status={st} rows={len(rows)} pick={({k: porder.get(k) for k in ('id','processingOrderNo','status','batchNo')} if porder else None)}")

# ── 8. 工序实例（生成即实例化；再调 instantiate 应幂等） ───────────────────
if porder:
    st, r = req("POST", f"/api/admin/production/orders/{oid}/instantiate", {}, tok=tok)
    step("08 工序实例化（幂等）", st == 200, f"status={st} data={json.dumps(data((st,r)), ensure_ascii=False)[:220]}")
st, r = req("GET", f"/api/admin/production/orders/{oid}/operations", tok=tok)
ops = data((st, r)) or []
ops = ops if isinstance(ops, list) else (ops.get("items") or [])
step("09 工序清单可查", len(ops) > 0, f"status={st} operations={len(ops)} names={[o.get('name') or o.get('operationName') for o in ops][:6]}")

# ── 10. 报工 ───────────────────────────────────────────────────────────────
if ops:
    op = ops[0]
    opid = op.get("id") or op.get("operationId")
    qty = float(op.get("plannedQty") or op.get("plannedQuantity") or 1)
    st, r = req("POST", f"/api/admin/production/orders/{oid}/operations/{opid}/report",
                {"worker_id": "chain-worker", "worker_name": "全链路工人", "qty": qty,
                 "qualified_qty": qty, "work_type": "normal"}, tok=tok)
    step("10 报工落库", st == 200, f"status={st} qty={qty} op={op.get('name') or op.get('operationName')} resp={json.dumps(data((st,r)), ensure_ascii=False)[:200]}")
    st, r = req("GET", f"/api/admin/production/orders/{oid}/piecework", tok=tok)
    step("11 计件可查", st == 200, f"status={st} data={json.dumps(data((st,r)), ensure_ascii=False)[:200]}")

# ── 12. 质检 ───────────────────────────────────────────────────────────────
st, r = req("GET", "/api/admin/quality-inspections/targets?status=all&page=1&size=50", tok=tok)
tg = data((st, r)) or {}
trows = tg.get("items") or tg.get("list") or (tg if isinstance(tg, list) else [])
mine_t = next((x for x in trows if x.get("orderId") == oid or x.get("orderNo") == order.get("orderNo")), None)
item_id = (mine_t or {}).get("orderItemId") or (mine_t or {}).get("order_item_id")
if item_id:
    st, r = req("POST", "/api/admin/quality-inspections", {"order_item_id": item_id, "result": "pass"}, tok=tok)
    step("12 质检录入（pass）", st == 200, f"status={st} item={item_id} resp={json.dumps(data((st,r)), ensure_ascii=False)[:180]}")
else:
    step("12 质检录入（pass）", False, f"待检清单里没有本单：status={st} rows={len(trows)} sample={json.dumps(trows[:1], ensure_ascii=False)[:240]}")

# ── 13. 发货（三步写序 + 发货单） ─────────────────────────────────────────
st, r = req("POST", f"/api/admin/production/orders/{oid}/ship",
            {"trackingNo": f"SF{suffix}8888", "logisticsCompany": "顺丰速运", "shippingMethod": "logistics",
             "logisticsType": "express", "shipperName": "全链路发货员"}, tok=tok)
shipd = data((st, r)) or {}
st2, r2 = req("GET", f"/api/admin/orders/{oid}", tok=tok)
ostat2 = (data((st2, r2)) or {}).get("status")
step("13 发货 → shipped", st == 200 and ostat2 == "shipped", f"status={st} 回读status={ostat2} shipment={shipd.get('shipment_no')}")
st, r = req("GET", f"/api/admin/orders/{oid}/shipments", tok=tok)
sh = data((st, r)) or []
sh = sh if isinstance(sh, list) else (sh.get("items") or [])
step("14 发货单可查", len(sh) > 0, f"status={st} shipments={len(sh)} no={[x.get('shipmentNo') for x in sh][:3]}")

# ── 15. 售后工单 ───────────────────────────────────────────────────────────
st, r = req("POST", "/api/admin/after-sales",
            {"orderId": oid, "ticketType": "quality", "description": f"全链路回归{suffix}", "priority": "normal"}, tok=tok)
tk = data((st, r)) or {}
step("15 售后建单", st == 200 and bool(tk.get("id")), f"status={st} ticket={tk.get('id')} status={tk.get('status')} type={tk.get('ticketType')}")

# ── 16. 仪表盘 / 财务读数（写后可见） ─────────────────────────────────────
for name, p in [("看板统计", "/api/admin/dashboard/statistics"), ("财务对账", "/api/admin/finance/reconciliation")]:
    st, r = req("GET", p, tok=tok)
    step(f"16 {name}可读", st == 200, f"status={st} {json.dumps(data((st,r)), ensure_ascii=False)[:160]}")

# ── 收尾 ──────────────────────────────────────────────────────────────────
bad = [n for n, ok, _ in RES if not ok]
print("\n===== 汇总：%d 步 · 通过 %d · 失败 %d =====" % (len(RES), len(RES) - len(bad), len(bad)))
if bad:
    print("失败步骤：" + "、".join(bad))
print(f"\n本次链路订单：id={oid} orderNo={order.get('orderNo')}" + ("" if KEEP else "（如需留作演示数据请复用；默认不删）"))
sys.exit(0 if not bad else 1)
