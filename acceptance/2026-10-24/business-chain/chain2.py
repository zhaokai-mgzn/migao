#!/usr/bin/env python3
"""MIGAO 核心业务全链路真跑 v2（本地 :8090 + 云 dev DB，租户 46）。

链路：下单 → 确认收款 → 加工单（自动生成）→ 工序实例 → 派工/开工 → 报工 → 完工
      → 质检 → 发货 → 发货单 → 售后 → 看板/财务读数
每步判据 = 服务端落库后回读。零 LLM。
"""
import json, sys, time, urllib.request, urllib.error

B = "http://127.0.0.1:8090"
PHONE, CODE = "13900001025", "123456"
RES = []


def req(m, p, body=None, tok=None):
    d = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + p, data=d, method=m)
    r.add_header("Content-Type", "application/json")
    if tok:
        r.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
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


def D(resp):
    return resp[1].get("data") if isinstance(resp[1], dict) else None


def err(resp):
    return json.dumps(resp[1], ensure_ascii=False)[:300]


st, b = req("POST", "/api/auth/sms/login", {"phone": PHONE, "code": CODE})
tok = D((st, b))["accessToken"]
step("00 登录", bool(tok), f"tenant={D((st,b))['user']['tenantId']} {D((st,b))['user']['nickname']}")

st, r = req("GET", "/api/admin/products?page=1&size=20", tok=tok)
prods = (D((st, r)) or {}).get("items") or []
prod = next((p for p in prods if float(p.get("price") or p.get("basePrice") or 0) > 0), None)
step("01 商品读取", bool(prod), f"{prod.get('name')} price={prod.get('price') or prod.get('basePrice')}")

suffix = str(int(time.time()))[-6:]
price = float(prod.get("price") or prod.get("basePrice") or 199)
st, r = req("POST", "/api/admin/orders", {
    "customerName": f"全链路客{suffix}", "customerPhone": f"13977{suffix}",
    "customerAddress": "上海市浦东新区张江高科技园区", "logisticsType": "express",
    "logisticsCompany": "顺丰速运", "remark": f"chain2-{suffix}",
    "items": [{"productId": prod.get("id"), "productName": prod.get("name"), "quantity": 2,
               "unitPrice": price, "subtotal": round(price * 2, 2),
               "processingInfo": {"sellingMethod": "bulk_cut", "doorWidth": "2.8", "processingFee": 15,
                                  "processingItems": [{"id": "proc_item_1", "name": "锁边", "quantity": 2, "unit": "米"}]}}],
}, tok=tok)
order = D((st, r)) or {}
oid, ono = order.get("id"), order.get("orderNo")
step("02 下单落库", st == 200 and bool(oid), f"orderNo={ono} amount={order.get('totalAmount')}")
if not oid:
    print(err((st, r))); sys.exit(1)

st, r = req("PUT", f"/api/admin/orders/{oid}/payment", {}, tok=tok)
st2, r2 = req("GET", f"/api/admin/orders/{oid}", tok=tok)
ostatus = (D((st2, r2)) or {}).get("status")
step("03 确认收款", st == 200 and ostatus == "confirmed", f"回读 status={ostatus}")

# 加工单（下单自动生成？没有则显式生成）
def find_porder():
    s, rr = req("GET", "/api/admin/processing-orders?page=1&size=100", tok=tok)
    dd = D((s, rr))
    rows = dd.get("items") if isinstance(dd, dict) else (dd or [])
    return next((x for x in (rows or []) if x.get("orderId") == oid or x.get("orderNo") == ono), None)

porder = find_porder()
gen_msg = "下单即自动生成"
if not porder:
    s, rr = req("PUT", f"/api/admin/orders/{oid}/urgency", {"isUrgent": True}, tok=tok)
    s2, rr2 = req("POST", "/api/admin/processing-orders/generate", {"orderIds": [oid]}, tok=tok)
    gen_msg = f"urgency={s} generate={s2} {json.dumps(D((s2, rr2)), ensure_ascii=False)[:200]}"
    porder = find_porder()
step("04 加工单生成", bool(porder), f"{gen_msg} → {({k: porder.get(k) for k in ('processingOrderNo','status','id')} if porder else None)}")
if not porder:
    print(err((st, r))); sys.exit(1)
pid = porder["id"]

st, r = req("POST", f"/api/admin/production/orders/{oid}/instantiate", {}, tok=tok)
step("05 工序实例化", st == 200, f"operation_count={(D((st,r)) or {}).get('operation_count')}")

st, r = req("GET", f"/api/admin/production/orders/{oid}/operations", tok=tok)
od = D((st, r)) or {}
positions = od.get("positions") or []
allops = [op for p in positions for op in (p.get("operations") or [])]
step("06 工序清单", len(allops) > 0,
     f"positions={len(positions)} operations={len(allops)} 首工序={[(o.get('logical_name'), o.get('qty'), o.get('unit')) for o in allops[:4]]}")

# 开工
for action, label in (("issue", "07 加工单派发(issue)"), ("start", "08 开工(start)")):
    st, r = req("PATCH", f"/api/admin/processing-orders/{pid}", {"action": action}, tok=tok)
    cur = (D((st, r)) or {}).get("status")
    step(label, st == 200, f"status={st} 回读={cur}" + ("" if st == 200 else f" {err((st,r))}"))

# 报工（全部工序）
reported, failed = 0, []
for op in allops:
    qty = float(op.get("qty") or 1)
    s, rr = req("POST", f"/api/admin/production/orders/{oid}/operations/{op['id']}/report",
                {"worker_id": "chain-worker", "worker_name": "全链路工人",
                 "qty": qty, "qualified_qty": qty, "work_type": "normal"}, tok=tok)
    if s == 200:
        reported += 1
    else:
        failed.append((op.get("logical_name"), s, str(D((s, rr)))[:80] or err((s, rr))))
step("09 报工（全工序）", reported == len(allops), f"{reported}/{len(allops)} 成功；失败样本={failed[:3]}")

st, r = req("GET", f"/api/admin/production/orders/{oid}/piecework", tok=tok)
step("10 计件读数", st == 200, f"{json.dumps(D((st,r)), ensure_ascii=False)[:240]}")

st, r = req("PATCH", f"/api/admin/processing-orders/{pid}", {"action": "complete"}, tok=tok)
# 报工全部完成 ⇒ 服务端会**自动完工**（实测：再显式 complete 回 422「不允许从 [加工完成] 变更为 [加工完成]」）
# ⇒ 判据改成**回读最终状态**，而不是「这次 PATCH 的 code」。
s2, r2 = req("GET", f"/api/admin/processing-orders?page=1&size=100", tok=tok)
dd = D((s2, r2))
rows = dd.get("items") if isinstance(dd, dict) else (dd or [])
cur = next((x for x in (rows or []) if x.get("id") == pid), None)
pstat = (cur or {}).get("status")
step("11 完工", pstat in ("completed", "加工完成") or st == 200,
     f"回读状态={pstat}（显式 complete 返回 {st}：{str(D((st,r)))[:80] if st==200 else '已是完工态'}）")

# 质检
st, r = req("GET", "/api/admin/quality-inspections/targets?status=all&page=1&size=100", tok=tok)
td = D((st, r)) or {}
trows = td.get("items") if isinstance(td, dict) else (td or [])
mine = next((x for x in (trows or []) if x.get("order_no") == ono or x.get("order_id") == oid), None)
item_id = (mine or {}).get("order_item_id")
if item_id:
    st, r = req("POST", "/api/admin/quality-inspections", {"order_item_id": item_id, "result": "pass"}, tok=tok)
    step("12 质检录入(pass)", st == 200, f"item={item_id} resp={json.dumps(D((st,r)), ensure_ascii=False)[:180]}" + ("" if st == 200 else f" {err((st,r))}"))
else:
    step("12 质检录入(pass)", False, f"待检清单未含本单 rows={len(trows)} sample={json.dumps((trows or [])[:1], ensure_ascii=False)[:240]}")

# 发货
st, r = req("POST", f"/api/admin/production/orders/{oid}/ship",
            {"trackingNo": f"SF{suffix}8888", "logisticsCompany": "顺丰速运", "shippingMethod": "logistics",
             "logisticsType": "express", "shipperName": "全链路发货员"}, tok=tok)
sd = D((st, r)) or {}
st2, r2 = req("GET", f"/api/admin/orders/{oid}", tok=tok)
ost2 = (D((st2, r2)) or {}).get("status")
step("13 发货", st == 200 and ost2 == "shipped", f"status={st} 回读={ost2} shipment_no={sd.get('shipment_no')}" + ("" if st == 200 else f" {err((st,r))}"))

st, r = req("GET", f"/api/admin/orders/{oid}/shipments", tok=tok)
sh = D((st, r)) or []
sh = sh if isinstance(sh, list) else ((sh or {}).get("shipments") or (sh or {}).get("items") or [])
step("14 发货单", len(sh) > 0, f"count={len(sh)} no={[x.get('shipmentNo') for x in sh][:2]}")

# 售后
st, r = req("POST", "/api/admin/after-sales",
            {"orderId": oid, "ticketType": "return", "description": f"全链路回归退货{suffix}", "priority": "normal"}, tok=tok)
tk = D((st, r)) or {}
step("15 售后建单", st == 200 and bool(tk.get("id")), f"id={tk.get('id')} status={tk.get('status')} type={tk.get('ticketType')}" + ("" if st == 200 else f" {err((st,r))}"))

st, r = req("GET", "/api/admin/dashboard/stats", tok=tok)
step("16 看板统计", st == 200, f"status={st} {json.dumps(D((st,r)), ensure_ascii=False)[:200]}")
st, r = req("GET", "/api/admin/finance/reconciliation?page=1&size=5", tok=tok)
step("17 财务对账", st == 200, f"status={st} total={(D((st,r)) or {}).get('total')}")

bad = [n for n, ok, _ in RES if not ok]
print("\n===== 汇总：%d 步 · 通过 %d · 失败 %d =====" % (len(RES), len(RES) - len(bad), len(bad)))
if bad:
    print("失败步骤：" + "、".join(bad))
print(f"\n本次链路：order={oid} ({ono}) processing={porder.get('processingOrderNo')}")
sys.exit(0 if not bad else 1)
