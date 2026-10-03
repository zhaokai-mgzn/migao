// P2：**派工矩阵** —— 逐道工序 × 逐项工序设置 → 加工单准确性（L1 全机器判定）
//
// 判定口径（每条都可执行、都会红）：
//   ① 工序集合与顺序 == 期望（主线 × 部位变体 + 规则 insert/remove 落位）
//   ② 每道工序的应做数量 > 0，且 == 该单位的口径键（米←fabric_meters / 折←pleat_count / 孔←holes /
//      幅←panels / 套←1 / 个←1）
//   ③ 单价 == 逻辑工序的塌缩价（未定价必须是 NULL，**不得**回落工序库行价 0）
//   ④ 分组 / 单位 逐字取库
//   ⑤ 套级工序（scope=set）在**一樘**里只落一次（防双付）
//   ⑥ 缺部位/缺工艺 ⇒ 显式 route_source 标注（不静默）
//
// 期望来源 = **商家配置**（GET /routings 的主线 + GET /route-rules 的规则）+ 部位变体命名表
// （docs/curtain-production-rules.md §2「工序按部位分设」）。核心场景另用**手写字面期望**兜底，
// 二者不一致即以字面为准并判红（防「oracle 与实现同错」）。
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { api, loginApi, psql, one, log, OUT, waitService, Recorder } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)

// ── 部位变体表（口径 = 库/真值源「同一道工序在布/纱/帘头分设」；与 GET /operation-positions 同源）──
const V = {
  '布帘': { 精裁: '精裁-布', 裁剪: '裁剪-布', 三边: '布三边', 韩褶: '韩褶-布', 上车布: '上车布-布', 打孔: '打孔-布', 拼1次: '拼1次-布', 拼2次: '拼2次-布', 拼3次: '拼3次-布', 花边: '花边-布', 铅坠: '铅坠-布', 接高: '接高-布', 熨烫: '熨烫-布', 定型: '定型-布', 复烫: '复烫-布', 车被: '布帘车被', 绑带: '绑带-布', logo条: 'logo条-布', 立边: '立边-布', 扣环: '扣环-布', 防翘扣: '防翘扣-布' },
  '纱帘': { 精裁: '精裁-纱', 裁剪: '裁剪-纱', 三边: '纱三边', 韩褶: '韩褶-纱', 上车布: '上车布-纱', 打孔: '打孔-纱', 熨烫: '熨烫-纱', 定型: '定型-纱', 复烫: '复烫-纱', 车被: '车被-纱', 绑带: '绑带-纱' },
  '布料': { 裁剪: '裁剪-布' },
  // 部位无关的工序（帘头制作/外帘*/打包/抱枕/腰靠垫/质检）落裸名
  '_NOPOS': ['帘头制作', '外帘打卷', '外帘装袋', '外帘发货', '打包', '抱枕', '腰靠垫', '质检'],
}
V['帘头'] = { ...V['布帘'] }
const variantOf = (logical, position) => {
  const m = V[position]
  if (m && m[logical]) return m[logical]
  const cloth = V['布帘'][logical]
  if (position === '帘头' && cloth) return cloth
  return V['_NOPOS'].includes(logical) ? logical : null
}

const SET_OPS = ['外帘打卷', '打包', '外帘装袋', '外帘发货']

/** 规则应用（口径 = 商家配置的**优先级序** + insert-after-anchor / remove）。 */
function applyRules(mainline, { craft, options = [], processingItems = [] }, rules, position) {
  const isFabric = position === '布料'
  let seq = [...mainline]
  const ordered = [...rules].sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0) || String(a.id).localeCompare(String(b.id)))
  for (const r of ordered) {
    if (isFabric) continue
    const k = r.trigger_kind
    if (k === 'craft') { if (r.trigger_value !== craft) continue }
    else if (k === 'option') { if (!options.includes(r.trigger_value)) continue }
    else if (k === 'processing_item') { if (!processingItems.includes(r.trigger_value)) continue }
    else if (k === 'position') { if (!r.position) throw new Error(`规则 ${r.id} 缺 position（永不生效）`) }
    else throw new Error(`未实现的触发类型 ${k}`)
    if (r.position && r.position !== position) continue
    if (r.action === 'insert') {
      const after = r.after_operation
      const i = after == null ? -1 : seq.indexOf(after)
      if (i < 0) seq.push(r.operation)                     // 锚点不存在 ⇒ 落末尾（与实现同序）
      else seq.splice(i + 1, 0, r.operation)
    } else if (r.action === 'remove') {
      seq = seq.filter((x) => x !== r.operation)
    }
  }
  return seq
}

const remap = (seq, position) => seq.map((l) => variantOf(l, position))

// ── 场景表 ─────────────────────────────────────────────────────────────
// 每条 = 一个**独立订单**（一单一行），clean 场景只用罗马帘（无规则的工艺）以隔离「选项」影响。
const BASE_PI = {
  sku: null, colorName: '本白', unit: '米', sellingMethod: 'bulk_cut',
  fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 24, fullness: 2, fullness_actual: 2,
  // 每行**必须**至少有一个加工项（无加工项的行被 buildSnapshot 跳过 ⇒ 整单「无加工项」）。
  // 「锁边」不在任何规则触发值里 ⇒ 中性，不干扰条件工序判定。
  processingItems: [{ id: 'pi_base', name: '锁边', quantity: 1, unit: '米' }],
}
const CLOTH10 = ['精裁', '三边', '熨烫', '定型', '复烫', '车被', '外帘打卷', '打包', '外帘装袋', '外帘发货']
const ins = (seq, op, anchor) => { const i = anchor == null ? -1 : seq.indexOf(anchor); const out = [...seq]; out.splice(i + 1, 0, op); return out }
const rm = (seq, ...ops) => seq.filter((x) => !ops.includes(x))

const LITERAL = [
  { id: 'D-01', title: '布帘 × 无规则工艺（罗马帘）→ 主线十道，逐部位变体正确', pos: '布帘', craft: '罗马帘',
    expect: remap(CLOTH10, '布帘') },
  { id: 'D-02', title: '布帘 × 韩褶 → 主线 + 韩褶(三边后) + 上车布(韩褶后)', pos: '布帘', craft: '韩褶',
    expect: remap(ins(ins(CLOTH10, '韩褶', '三边'), '上车布', '韩褶'), '布帘') },
  { id: 'D-03', title: '纱帘 × 韩褶 → 纱变体逐道正确（精裁-纱/纱三边/韩褶-纱/上车布-纱/车被-纱）', pos: '纱帘', craft: '韩褶',
    expect: ['精裁-纱', '纱三边', '韩褶-纱', '上车布-纱', '熨烫-纱', '定型-纱', '复烫-纱', '车被-纱', '外帘打卷', '打包', '外帘装袋', '外帘发货'] },
  { id: 'D-04', title: '帘头 × 平幔 → 帘头复用布帘变体 + 帘头制作(三边后) + 去掉复烫', pos: '帘头', craft: '平幔',
    expect: ins(rm(['精裁-布', '布三边', '熨烫-布', '定型-布', '复烫-布', '布帘车被', '外帘打卷', '打包', '外帘装袋', '外帘发货'], '复烫-布'), '帘头制作', '布三边') },
  { id: 'D-05', title: '布料形态（saleForm=布料）→ 布料主线（裁剪→打包），不套窗帘工艺规则', pos: '布料', saleForm: '布料', craft: null,
    expect: ['裁剪-布', '打包'] },
  { id: 'D-06', title: '布帘 × 打孔 → 打孔-布(三边后)', pos: '布帘', craft: '打孔',
    expect: remap(ins(CLOTH10, '打孔', '三边'), '布帘') },
  { id: 'D-07', title: '布帘 × 穿杆 → 去掉 定型/复烫', pos: '布帘', craft: '穿杆',
    expect: rm(CLOTH10, '定型', '复烫').map((x) => variantOf(x, '布帘')) },
  { id: 'D-08', title: '布帘 × 四爪钩 → 该工艺规则已软删 ⇒ 与主线逐字相同（软删规则不得生效）', pos: '布帘', craft: '四爪钩',
    expect: remap(CLOTH10, '布帘') },
  { id: 'D-09', title: '布帘 未填部位与工艺 → 显式回落默认（route_source 标注 + 序列 = 默认工艺「韩褶」的 12 道）',
    pos: null, craft: null, expectSourceNot: 'direct',
    expect: remap(ins(ins(CLOTH10, '韩褶', '三边'), '上车布', '韩褶'), '布帘') },
  { id: 'D-10', title: '布帘 × 罗马帘 + isShaped=false → 剔除 定型/复烫（形态开关接线）', pos: '布帘', craft: '罗马帘', isShaped: false,
    expect: remap(rm(CLOTH10, '定型', '复烫'), '布帘') },
]

const OPTION_ANCHORS = [
  ['拼1次', '三边'], ['拼2次', '三边'], ['拼3次', '三边'], ['加花边', '三边'], ['加铅块', '三边'],
  ['接高', '精裁'], ['双眼皮接高', '精裁'], ['余料做绑带', '车被'], ['布绑带', '车被'], ['纱绑带', '车被'],
  ['余料做帘头', '三边'], ['抱枕', '外帘打卷'], ['加logo条', '三边'], ['加立边', '三边'], ['扣环', '三边'], ['防翘扣', '三边'],
]

function buildScenarios() {
  const list = [...LITERAL]
  // 逐条「选项」规则（布帘 × 罗马帘 隔离）
  for (const [opt, anchor] of OPTION_ANCHORS) {
    list.push({ id: `O-${opt}`, title: `布帘 + 特殊选项「${opt}」→ 条件工序落位（${anchor} 之后）`, pos: '布帘', craft: '罗马帘', options: [opt], anchor, optionRule: opt })
  }
  // 逐条「加工项」规则
  for (const pi of ['花边', '扣环', '接高']) {
    list.push({ id: `I-${pi}`, title: `布帘 + 加工项「${pi}」→ 条件工序落位`, pos: '布帘', craft: '罗马帘', processingItem: pi, anchor: pi === '接高' ? '精裁' : '三边', optionRule: pi })
  }
  // 套级（一樘布+纱）与多窗
  const HANZHE_CLOTH = remap(ins(ins(CLOTH10, '韩褶', '三边'), '上车布', '韩褶'), '布帘')
  const HANZHE_SHEER = ['精裁-纱', '纱三边', '韩褶-纱', '上车布-纱', '熨烫-纱', '定型-纱', '复烫-纱', '车被-纱']
  list.push({ id: 'S-01', title: '一樘布+纱（craftLineId 同组）→ 两个部位各自序列正确，套级工序只落一次（防双付）',
    multi: 'cloth-sheer', expectPerItem: [HANZHE_CLOTH, HANZHE_SHEER] })
  list.push({ id: 'S-02', title: '两樘独立窗（无 craftLineId）→ 两行各自 12 道、套级工序各落一次（合计 2 次）',
    multi: 'two-windows', expectPerItem: [HANZHE_CLOTH, HANZHE_CLOTH] })
  list.push({ id: 'S-03', title: '纱帘 + 选项「拼1次」（仅布帘有该变体）→ 须显式失败，不得静默丢工序', pos: '纱帘', craft: '罗马帘', options: ['拼1次'], expectFail: true, expectFailNames: ['拼1次'] })
  // 数量口径
  list.push({ id: 'Q-01', title: '数量口径：孔数（holes=24）恒等于报工应做数量', pos: '布帘', craft: '打孔', qtyProbe: '打孔-布' })
  // 补覆盖：纱帘侧的变体
  list.push({ id: 'D-11', title: '纱帘 × 打孔 → 打孔-纱（纱变体逐条可达）', pos: '纱帘', craft: '打孔',
    expect: ['精裁-纱', '纱三边', '打孔-纱', '熨烫-纱', '定型-纱', '复烫-纱', '车被-纱', '外帘打卷', '打包', '外帘装袋', '外帘发货'] })
  list.push({ id: 'O2-纱绑带@纱帘', title: '纱帘 + 选项「纱绑带」→ 绑带变体按部位解析成 绑带-纱', pos: '纱帘', craft: '罗马帘', options: ['纱绑带'], anchor: '车被', optionRule: '纱绑带' })
  // 仅布帘有变体的选项 × 纱帘：期望**显式失败并报出缺哪道工序**（默认配置无处可配部位维 ⇒ 商家会被卡住）
  // 选项名 ≠ 工序名（报错里指的是**逻辑工序**）：加花边→花边 / 加铅块→铅坠 / 加logo条→logo条 …
  const OPT2OP = { 拼1次: '拼1次', 拼2次: '拼2次', 拼3次: '拼3次', 加花边: '花边', 加铅块: '铅坠', 接高: '接高',
    双眼皮接高: '接高', 加logo条: 'logo条', 加立边: '立边', 扣环: '扣环', 防翘扣: '防翘扣' }
  for (const opt of ['拼1次', '加花边', '加铅块', '接高', '加logo条', '加立边', '扣环', '防翘扣']) {
    list.push({ id: `F-${opt}@纱帘`, title: `纱帘 + 选项「${opt}」→ 该工序无纱帘变体，须显式失败且指名缺的工序`, pos: '纱帘', craft: '罗马帘', options: [opt], expectFail: true, expectFailNames: [OPT2OP[opt]] })
  }
  // 部位无关的工序（抱枕）在纱帘上**应当**正常派工（与上面那批相反的一侧）
  list.push({ id: 'O2-抱枕@纱帘', title: '纱帘 + 选项「抱枕」→ 部位无关工序照常派工（不误判为缺工序）', pos: '纱帘', craft: '罗马帘', options: ['抱枕'], anchor: '外帘打卷', optionRule: '抱枕' })
  return list
}

// ── 执行 ─────────────────────────────────────────────────────────────
export const CAT = new Map()      // 变体名 → {unit, scope, group, price}
export const PRICE = new Map()    // 逻辑名 → 塌缩价（null = 未定价）

function loadCatalog(token) {
  return api('GET', '/api/admin/production/operations-catalog', { token }).then(async (r) => {
    for (const g of r.json?.data?.groups || []) {
      for (const o of g.operations) {
        CAT.set(o.library_name, { unit: o.unit, scope: o.scope, group: o.group, name: o.name })
      }
    }
    const pos = await api('GET', '/api/admin/production/operation-positions', { token })
    for (const row of pos.json?.data || []) PRICE.set(row.operation, row.unit_price)
    const rules = await api('GET', '/api/admin/production/route-rules', { token })
    const routings = await api('GET', '/api/admin/production/routings', { token })
    const templates = new Map((routings.json?.data?.routings || []).map((t) => [t.name, t]))
    return { rules: (rules.json?.data?.rules || rules.json?.data || []).filter((x) => x.status === 'active'), templates }
  })
}

async function createProduct(token) {
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `工序验收分类${RUN}`, sortOrder: 1 } })
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `工序验收商品${RUN}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: cat.json?.data?.id ? 'on_shelf' : 'draft', categoryId: cat.json?.data?.id,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `DSP-${RUN}` }],
    },
  })
  const productId = prod.json?.data?.id
  const skuId = one(`select id::text as id from product_skus where product_id='${productId}'`)?.id
  if (!productId || !skuId) throw new Error(`商品创建失败：${prod.status} ${prod.text.slice(0, 200)}`)
  return { productId, skuId }
}

function mkItem(sc, i, ctx) {
  const pos = sc.pos
  const pi = {
    ...BASE_PI, sku: ctx.skuId,
    ...(pos ? { curtainType: pos } : {}),
    ...(sc.craft ? { craft: sc.craft } : {}),
    ...(sc.saleForm ? { saleForm: sc.saleForm } : {}),
    ...(sc.options ? { specialOptions: sc.options } : {}),
    ...(sc.processingItem ? { processingItems: [...BASE_PI.processingItems, { id: `pi_${i}`, name: sc.processingItem, quantity: 1, unit: '米' }] } : {}),
    ...(sc.isShaped === false ? { isShaped: false } : {}),
    ...(sc.craftLineId ? { craftLineId: sc.craftLineId } : {}),
    ...(sc.componentRole ? { componentRole: sc.componentRole } : {}),
  }
  return {
    productId: ctx.productId, skuId: ctx.skuId, productName: `${sc.id}-${i}`, quantity: 1, unitPrice: 68, subtotal: 68,
    width: 2.8, height: 2.6, processingInfo: pi,
  }
}

async function runScenario(token, ctx, sc, rules) {
  const items = []
  if (sc.multi === 'cloth-sheer') {
    items.push(mkItem({ ...sc, pos: '布帘', craft: '韩褶', craftLineId: 'WIN-1' }, 0, ctx))
    items.push(mkItem({ ...sc, pos: '纱帘', craft: '韩褶', craftLineId: 'WIN-1', componentRole: '纱' }, 1, ctx))
  } else if (sc.multi === 'two-windows') {
    items.push(mkItem({ ...sc, pos: '布帘', craft: '韩褶' }, 0, ctx))
    items.push(mkItem({ ...sc, pos: '布帘', craft: '韩褶' }, 1, ctx))
  } else {
    items.push(mkItem(sc, 0, ctx))
  }
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `工序验收客户${RUN}`, customerPhone: '13300000003', customerAddress: '杭州市余杭区工序路 9 号',
      logisticsType: 'express', logisticsCompany: '顺丰速运', items,
    },
  })
  const orderId = order.json?.data?.id
  if (!orderId) return { verdict: 'fail', detail: `建单失败 HTTP ${order.status} ${order.text.slice(0, 200)}` }
  await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
  const gen = await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })
  const res = gen.json?.data?.[0]
  const po = one(`select id, processing_order_no, route_key, route_source from processing_orders where order_id='${orderId}' order by created_at desc limit 1`)
  const rows = po ? psql(`select position_name, position_kind, seq, operation_name, group_name, unit,
        qty::text as qty, unit_price::text as unit_price, qty_source, set_id, is_start_marker
      from processing_position_operations where processing_order_id='${po.id}' order by position_name, seq`) : []
  return { orderId, po, gen, res, rows }
}

export function judge(sc, out, rules) {
  const problems = []
  const ok = (c, msg) => { if (!c) problems.push(msg) }
  if (sc.expectFail) {
    const msg = String(out.res?.message || out.gen?.text || '')
    // 必须是**取路/缺工序**导致的失败，不得是「无加工项」等前置缺失（那是假绿）
    const named = !sc.expectFailNames || sc.expectFailNames.every((n) => msg.includes(n))
    // **正向签名**（不是黑名单）：只认「取路/实例化阶段缺工序」这一种失败形态
    const routeFailure = /引用的工序|在工序库中不存在|无法实例化工序/.test(msg)
    if (out.res?.success === false && named && routeFailure) {
      return { problems, pass: true, note: `按预期显式失败：${msg.slice(0, 160)}` }
    }
    if (out.res?.success === false) return { problems: [`失败原因不是「缺工序/取路」，而是：${msg.slice(0, 200)}`], pass: false }
    // 若成功落单，判定该工序是否真的丢/错
    const names = out.rows.map((r) => r.operation_name)
    return { problems: [`预期显式失败，实际生成成功（工序=${names.join(',')}）—— 静默丢工序或错误取路`], pass: false }
  }
  ok(out.res?.success === true, `generate 未成功：${out.res?.message || JSON.stringify(out.gen?.json).slice(0, 200)}`)
  if (!out.po) { problems.push('未落加工单'); return { problems, pass: false } }
  // 空结果**不得**静默通过（漏工序/漏部位必须在断言里现形）
  ok((out.rows || []).length > 0, '派工结果 0 行工序实例')
  if (sc.expectSourceNot) ok(out.po.route_source !== sc.expectSourceNot, `route_source 期望非 ${sc.expectSourceNot}，实得 ${out.po.route_source}`)

  // 期望序列
  let expectedSeq = null
  if (sc.expect) expectedSeq = sc.expect
  else if (sc.multi === 'cloth-sheer') expectedSeq = { __multi: true }
  else if (sc.multi === 'two-windows') expectedSeq = { __multi: true }
  else if (sc.optionRule || sc.qtyProbe) {
    const cl = applyRules(CLOTH10, { craft: sc.craft, options: sc.options || [], processingItems: sc.processingItem ? [sc.processingItem] : [] }, rules, sc.pos)
    expectedSeq = remap(cl, sc.pos)
  }
  // 部位分组
  const byPos = new Map()
  for (const r of out.rows) {
    if (!byPos.has(r.position_name)) byPos.set(r.position_name, [])
    byPos.get(r.position_name).push(r)
  }
  if (expectedSeq && !expectedSeq.__multi) {
    ok(byPos.size === 1, `期望 1 个部位，实得 ${byPos.size}：${[...byPos.keys()].join(' / ')}`)
    const actual = out.rows.map((r) => r.operation_name)
    ok(JSON.stringify(actual) === JSON.stringify(expectedSeq),
      `工序序列不符\n      期望 ${expectedSeq.join(' → ')}\n      实得 ${actual.join(' → ')}`)
  }
  if (sc.expectPerItem) {
    const idxOf = (name) => { const m = /-(\d+) /.exec(name + ' '); return m ? Number(m[1]) : 99 }
    const ordered = [...byPos.entries()].sort((a, b) => idxOf(a[0]) - idxOf(b[0]))
    ok(ordered.length === sc.expectPerItem.length, `部位数期望 ${sc.expectPerItem.length}，实得 ${ordered.length}`)
    sc.expectPerItem.forEach((exp, i) => {
      const actual = (ordered[i]?.[1] || []).map((r) => r.operation_name)
      ok(JSON.stringify(actual) === JSON.stringify(exp),
        `第 ${i} 个部位序列不符\n      期望 ${exp.join(' → ')}\n      实得 ${actual.join(' → ')}`)
    })
  }
  if (expectedSeq?.__multi) {
    const setRows = out.rows.filter((r) => SET_OPS.includes(r.operation_name))
    const expectSets = sc.multi === 'cloth-sheer' ? SET_OPS.length : SET_OPS.length * 2
    ok(setRows.length === expectSets, `套级工序行数期望 ${expectSets}，实得 ${setRows.length}（${setRows.map((r) => r.operation_name + '@' + r.position_name).join(', ')}）`)
    ok(byPos.size === 2, `部位数期望 2，实得 ${byPos.size}`)
  }
  // 通用不变量：数量 / 单价 / 分组 / 单位 / seq
  for (const r of out.rows) {
    const c = CAT.get(r.operation_name)
    ok(!!c, `工序「${r.operation_name}」不在工序库读面（幽灵工序）`)
    if (c) {
      ok(r.unit === c.unit, `${r.operation_name} 单位不符：实例=${r.unit} 库=${c.unit}`)
      ok(r.group_name === c.group, `${r.operation_name} 分组不符：实例=${r.group_name} 库=${c.group}`)
      const wantQty = { 米: 12.3, 折: 40, 孔: 24, 幅: 2, 套: 1, 个: 1 }[c.unit]
      // 未登记单位 ⇒ **判红**（不得静默跳过数量断言）：单位值域见真值源 KNOWN_QTY_UNITS ∪ FIXED_ONE_UNITS
      ok(wantQty !== undefined, `${r.operation_name} 单位「${c.unit}」不在已知值域（米/折/孔/幅/套/个）⇒ 数量断言无从判定`)
      ok(Number(r.qty) > 0, `${r.operation_name} 应做数量为 0/空（假完工风险）`)
      if (wantQty !== undefined) ok(Math.abs(Number(r.qty) - wantQty) < 1e-6, `${r.operation_name} 数量口径不符：${r.qty}${r.unit}，期望 ${wantQty}（单位 ${c.unit}）`)
    }
    // 单价断言**必须落地**：`PRICE.get` 为 undefined = 该逻辑工序在工艺项价目读面没有行
    // （「未登记」与「未定价 null」是两回事 —— 混同会让单价断言静默跳过）
    const hasPriceRow = c ? PRICE.has(c.name) : false
    ok(hasPriceRow, `工序「${r.operation_name}」（逻辑名 ${c?.name}）在工艺项价目读面没有行 ⇒ 单价断言无从判定`)
    const expectPrice = hasPriceRow ? PRICE.get(c.name) : undefined
    if (expectPrice !== undefined) {
      const a = r.unit_price === null ? null : Number(r.unit_price)
      const b = expectPrice === null ? null : Number(expectPrice)
      ok(a === b, `${r.operation_name} 单价不符：实例=${r.unit_price} 期望=${expectPrice}（未定价必须 NULL，不得回落库价 0）`)
    }
  }
  // seq 连续（**按部位**：seq 是部位内序号；跨部位会重新从 1 起）
  for (const [pname, rows] of byPos) {
    const seqs = rows.map((r) => Number(r.seq))
    ok(seqs.every((v, i) => v === i + 1), `部位「${pname}」seq 不连续：${seqs.join(',')}`)
  }
  return { problems, pass: problems.length === 0 }
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p2-matrix.json')
  const { token } = await loginApi(PHONE)
  const { rules, templates } = await loadCatalog(token)
  log(`配置：规则 ${rules.length} 条活跃 / 路线模板 ${[...templates.keys()].join(' , ')}`)
  const ctx = await createProduct(token)
  log(`商品 ${ctx.productId} / SKU ${ctx.skuId}`)

  const scenarios = buildScenarios()
  const coverage = new Map()   // 变体名 → [场景 id]
  const results = []
  for (const sc of scenarios) {
    try {
      const out = await runScenario(token, ctx, sc, rules)
      const j = typeof out.verdict === 'string' ? { pass: false, problems: [out.detail] } : judge(sc, out, rules)
      for (const r of out.rows || []) {
        if (!coverage.has(r.operation_name)) coverage.set(r.operation_name, [])
        coverage.get(r.operation_name).push(sc.id)
      }
      results.push({ id: sc.id, title: sc.title, pass: j.pass, problems: j.problems, note: j.note,
        orderId: out.orderId, po: out.po?.processing_order_no, route_source: out.po?.route_source,
        ops: (out.rows || []).map((r) => `${r.seq}.${r.operation_name}(${r.qty}${r.unit}@${r.unit_price ?? 'NULL'}|${r.qty_source})`) })
      j.pass ? R.pass(sc.id, sc.title, `订单 ${out.orderId} 加工单 ${out.po?.processing_order_no}（${out.po?.route_source}）→ ${(out.rows || []).length} 道工序`, [`POST /api/admin/processing-orders/generate`, `SQL: select * from processing_position_operations where processing_order_id='${out.po?.id}'`])
             : R.fail(sc.id, sc.title, j.problems.join(' ｜ '), [`POST /api/admin/processing-orders/generate`, `orderId=${out.orderId}`])
    } catch (e) {
      R.fail(sc.id, sc.title, `异常：${String(e).slice(0, 300)}`)
      results.push({ id: sc.id, title: sc.title, pass: false, problems: [String(e).slice(0, 300)] })
    }
  }

  // 覆盖率：40 道工序里哪些被派工到过
  const allOps = [...CAT.keys()]
  const uncovered = allOps.filter((o) => !coverage.has(o))
  writeFileSync(join(OUT, 'p2-coverage.json'), JSON.stringify({
    totalCatalog: allOps.length, covered: coverage.size, uncovered,
    byOperation: Object.fromEntries([...coverage.entries()].sort()),
  }, null, 2))
  writeFileSync(join(OUT, 'p2-results.json'), JSON.stringify(results, null, 2))
  log(`summary=${JSON.stringify(R.summary())}`)
  log(`覆盖率：${coverage.size}/${allOps.length}；未被任何场景派工的工序 = ${uncovered.join(', ') || '（无）'}`)
}

// 仅直接运行时跑矩阵；被 import（红证复用 judge / 价目表）时不执行
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e) => { console.error(e); process.exit(1) })
}
