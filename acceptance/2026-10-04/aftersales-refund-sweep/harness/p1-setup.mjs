// p1-setup —— 建本包的**探针夹具**：一个可退款的已确认订单 + 一条带 skuId 的明细（含回补开关两侧的商品）
// 用法：API_BASE=http://127.0.0.1:8080 node p1-setup.mjs
//
// 为什么走真实 API 而不是 SQL 插行：本线测的就是**写面**（建单/确认收款/退款/售后完结），
// 用 SQL 造单会让「扣库存 / 落台账 / 算实收」这些前置事实失去可信来源。
import { writeFileSync, existsSync } from 'node:fs'
import {
  adminToken, createProbeProduct, createProbeOrder, orderRow, skuStock, ledgerRowsFor,
  outPath, log, nowCST, Recorder, psql, one, cents, fmtQty, qtyEq, TENANT_ID, api, registerProbe, PROBE_PREFIX, uniq,
} from './lib.mjs'

const R = new Recorder('B1-setup.json')
const { token, via } = await adminToken()
log(`鉴权成功（via=${via}）`)
writeFileSync(outPath('.token'), String(token))

// ───────────────────────── 前置：探针商品分类（租户 25 是空库 ⇒ 必须自建）─────────────────────────
// 为什么必须自建：`POST /api/admin/products` 的 categoryId 是**必填**（实测缺 ⇒ 422「分类ID不能为空」），
// 而新租户**零分类**（`categories` 表 0 行；`RegistrationService` 只种角色/权限/岗位，不种商品分类）。
// 因此「本租户零分类 ⇒ 走 API 建商品不可达」本身是一条**独立读数**（见 LB1-SETUP-category-gap），
// 而不是用 SQL 造商品绕过 —— 分类走**真实 API** 建，并登记进探针注册表（收尾随注册表清理）。
// ⚠️ 判据必须**命名空间化**（BRIEF 纪律 8）：只能看**本线自己**的命名域（`PROBE_PREFIX` 前缀）。
//    实测踩过（本线自曝的**假绿**）：首版写 `select … from categories where status='active'`，
//    而租户 25 里当时**已经有别线留下的 4 条 `线A验收链分类-*`** ⇒ 该判据「绿」但**对本线探针毫无判别力**。
//    改成只看本线前缀后：初始 0 条 ⇒ 判 fail（真值），且探针分类是**本线自建**的。
const cats0 = psql(`select id, name from categories where tenant_id=${TENANT_ID} and status='active' and name like '${PROBE_PREFIX}%' order by created_at limit 3`)
const catsForeign = psql(`select id, name from categories where tenant_id=${TENANT_ID} and status='active' and name not like '${PROBE_PREFIX}%' order by created_at limit 5`)
let probeCategoryId = cats0[0]?.id ?? null
let categoryProbe = null
if (!probeCategoryId) {
  const cname = `${PROBE_PREFIX}分类-${uniq()}`
  const cr = await api('POST', '/api/admin/categories', { token, body: { name: cname, status: 'active' } })
  probeCategoryId = cr.data?.id ?? null
  categoryProbe = { requested: cname, status: cr.status, text: cr.text.slice(0, 300), id: probeCategoryId }
  if (probeCategoryId) registerProbe('category', probeCategoryId, `${PROBE_PREFIX}分类（探针）`)
}
const catsAfter = psql(`select id, name, status from categories where tenant_id=${TENANT_ID} and status='active' and name like '${PROBE_PREFIX}%' order by created_at limit 3`)

/** 建「商品 + 已确认订单」一组夹具；restock 控制 allow_return_restock。 */
async function fixture(tag, { allowRestock, stock = 100, qty = 2, unitPrice = 100 }) {
  const p = await createProbeProduct(token, { allowRestock, stock, price: unitPrice, tag, categoryId: probeCategoryId })
  if (!p.ok) return { ok: false, step: 'product', resp: p.resp, body: p.body }
  const o = await createProbeOrder(token, {
    productId: p.productId, productName: p.name, skuId: p.skuId, skuCode: p.skuCode,
    colorId: p.colorId, qty, unitPrice, tag,
  })
  if (!o.ok) return { ok: false, step: 'order', resp: o.resp, body: o.body, product: p }
  const row = orderRow(o.orderId)
  const sku = skuStock(p.skuId)
  return { ok: true, tag, allowRestock, product: p, order: o, orderRow: row, skuAfter: sku, qty, unitPrice }
}

const out = { at: nowCST(), via, fixtures: {} }
// ① 回补开关**开**侧：allow_return_restock = true（退货完结应回补库存）
out.fixtures.restockOn = await fixture('RESTOCKON', { allowRestock: true })
// ② 回补开关**关**侧：allow_return_restock = false（默认；退货完结库存零变化）
out.fixtures.restockOff = await fixture('RESTOCKOFF', { allowRestock: false })
// ③ 退款金额专用（不回补，避免库存噪声干扰判据）
out.fixtures.refund = await fixture('REFUND', { allowRestock: false, qty: 2, unitPrice: 150 })

writeFileSync(outPath('B1-fixtures.json'), JSON.stringify(out, null, 2))

// ── 夹具自证：期望由**本包独立算式**给出，不读产品读面 ──
for (const [name, f] of Object.entries(out.fixtures)) {
  if (!f.ok) { R.fail(`LB1-SETUP-${name}`, `夹具 ${name}`, `建夹失败于 ${f.step}: ${f.resp?.status} ${f.resp?.text?.slice(0, 200)}`, []); continue }
  const expectTotal = (cents(f.unitPrice) * BigInt(f.qty))
  const totalOk = qtyEq(f.orderRow.total_amount, fmtQty(expectTotal))
  const expectStock = cents(100) - cents(f.qty)   // 确认收款扣 2 ⇒ 100-2 = 98
  const stockOk = qtyEq(f.skuAfter.stock, fmtQty(expectStock))
  const confirmOk = f.order.confirmResp?.json?.success === true
  const statusOk = f.orderRow.status === 'confirmed'
  const pass = totalOk && stockOk && confirmOk && statusOk
  R.add(`LB1-SETUP-${name}`, `夹具 ${name}（商品+已确认订单）`, pass ? 'pass' : 'fail',
    `orderNo=${f.orderRow.order_no} status=${f.orderRow.status} 实收=${f.orderRow.actual_amount} 总额=${f.orderRow.total_amount} 明细后 SKU 库存=${f.skuAfter.stock}`,
    [`期望来源: 本包独立算式 —— 单价 ${f.unitPrice} × 数量 ${f.qty} = ${fmtQty(expectTotal)}；库存 100 − ${f.qty} = ${fmtQty(expectStock)}`,
     `确认收款响应: ${JSON.stringify(f.order.confirmResp?.json).slice(0, 200)}`,
     `产品侧商品 id=${f.product.productId} skuId=${f.product.skuId} allow_return_restock=${f.allowRestock}`,
     `订单 id=${f.order.orderId} 幂等键域: 无（本夹具不经幂等层）`],
    { fixture: name, orderId: f.order.orderId, orderNo: f.orderRow.order_no, productId: f.product.productId, skuId: f.product.skuId })
}

// ── 扣减台账自证（确认收款应落 reason=order 行，delta=-2）──
const ro = out.fixtures.restockOn
if (ro.ok) {
  const led = psql(`select id, delta, before_qty, after_qty, reason, ref_no from stock_ledger_entries
                    where tenant_id=${TENANT_ID} and ref_no='${ro.orderRow.order_no}' and sku_id=${ro.product.skuId}`)
  const d = led[0]?.delta
  R.add('LB1-SETUP-ledger', '确认收款落扣减台账（order 腿）', (led.length === 1 && qtyEq(d, '-2.000')) ? 'pass' : 'fail',
    `台账行数=${led.length} delta=${d} before=${led[0]?.before_qty} after=${led[0]?.after_qty} ref_no=${led[0]?.ref_no}`,
    ['期望来源: 本包独立算式 —— 确认收款扣 2 米 ⇒ 台账恰一行 delta = −2.000（before 100 → after 98）',
     `原始行: ${JSON.stringify(led)}`])
}

// ── 前置读数：空租户的商品分类缺口 + 分类写面可达性 ──
// ⚠️ 口径：这条**不是**「建夹失败」的借口，而是**独立读数** —— 期望来源 = 产品契约（categoryId 必填）
//    与入驻实现（不种分类）。它回答的是：「新租户能不能走 API 建出第一个商品」。
writeFileSync(outPath('B1-category-gap.json'), JSON.stringify({
  at: nowCST(), tenant: TENANT_ID, catsBefore: cats0, catsAfter: catsAfter, probeCategoryCreate: categoryProbe,
}, null, 2))
R.add('LB1-SETUP-category-gap', '空租户首个商品的前置缺口：本租户**本线命名域内**初始 0 个商品分类 ⇒ `POST /api/admin/products`（categoryId 必填）不可达',
  cats0.length === 0 ? 'fail' : 'pass',
  `本线命名域（前缀「${PROBE_PREFIX}」）初始 active 分类数=${cats0.length}；经真实 API 补建探针分类后=${catsAfter.length}（新建 id=${probeCategoryId}，HTTP ${categoryProbe?.status ?? '未调用'}）；同时段**其他线**的分类=${catsForeign.length} 条（${catsForeign.map((x) => x.name).join(', ') || '无'}，本线不触碰）`,
  ['期望来源: 产品契约 —— `backend/admin-api/src/main/java/com/migao/admin/dto/ProductCreateRequest.java` 的 categoryId 必填；',
   '   `backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java` 入驻只种角色/权限/岗位（无商品分类种子）；',
   '实测：`POST /api/admin/products` 缺 categoryId ⇒ 422 VALIDATION_ERROR「分类ID不能为空」（原始响应见 out/B1-fixtures.json 的 fixtures[*].resp）',
   `库内原始读数（**本线命名域**）: categories(tenant ${TENANT_ID}) 初始 ${JSON.stringify(cats0)} ⇒ 补建后 ${JSON.stringify(catsAfter)}`,
   `⚠️ 判据命名空间化（本线自曝的假绿）: 首版查「全租户 active 分类」，当时租户里已有别线留下的 ${catsForeign.length} 条（${catsForeign.map((x) => x.name).join(', ') || '无'}）⇒ 判据会**无判别力地变绿**；改为只看本线前缀后才是真读数`,
   `⚠️ 跨包隔离: 别线的分类行本线**只登记、不触碰、不删**（清理器只删本线注册表与前缀命中行）`,
   '⚠️ 影响面与归因强度: 只能断言「本租户初始零分类 ⇒ API 建商品缺前置」；**能否**由前端「商品管理」页兜住',
   '   （即新用户是否可自助建分类）不在本线射程（未做 UI 级验证）⇒ 不写更强归因。'])

// ── 前置自证：夹具用的分类可用（探针商品 categoryId 的来源）──
R.add('LB1-SETUP-category', '夹具前置：探针商品 categoryId 可达（本租户 active 分类）',
  probeCategoryId ? 'pass' : 'fail',
  `tenant ${TENANT_ID} 可用分类 id=${probeCategoryId ?? 'n/a'}（active 数=${catsAfter.length}）`,
  ['期望来源: 本包独立读数（只读库）+ 真实 API 建分类响应',
   `补建响应: ${JSON.stringify(categoryProbe)}`, `库内原始行: ${JSON.stringify(catsAfter)}`])

log(`p1-setup 完成：${JSON.stringify(R.summary())}；夹具已落 out/B1-fixtures.json`)
