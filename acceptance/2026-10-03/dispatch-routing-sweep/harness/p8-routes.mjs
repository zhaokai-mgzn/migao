// P8：**路线设置功能**闭环（新建 / 改名 / 编辑主线顺序 / 删除 + 护栏）——每一项都要在派工结果里可验证
import { api, loginApi, psql, one, log, waitService, Recorder } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)
const BASE_PI = {
  colorName: '本白', unit: '米', sellingMethod: 'bulk_cut',
  fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 24,
  processingItems: [{ id: 'pi_base', name: '锁边', quantity: 1, unit: '米' }],
}
let token, ctx, MAIN0, DEF

async function mkProduct() {
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `路线验收分类${RUN}`, sortOrder: 1 } })
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `路线验收商品${RUN}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: cat.json?.data?.id ? 'on_sale' : 'draft', categoryId: cat.json?.data?.id,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `RTE-${RUN}` }],
    },
  })
  const productId = prod.json?.data?.id
  return { productId, skuId: one(`select id::text as id from product_skus where product_id='${productId}'`)?.id }
}

async function dispatch(tag, craft = '罗马帘') {
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `路线验收客户${RUN}`, customerPhone: '13300000007', customerAddress: '杭州市余杭区路线路 1 号',
      logisticsType: 'express', logisticsCompany: '顺丰速运',
      items: [{
        productId: ctx.productId, skuId: ctx.skuId, productName: `${tag}-${RUN}`, quantity: 1, unitPrice: 68, subtotal: 68,
        width: 2.8, height: 2.6,
        processingInfo: { ...BASE_PI, sku: ctx.skuId, curtainType: '布帘', craft },
      }],
    },
  })
  const orderId = order.json?.data?.id
  if (!orderId) return { ok: false, rows: [], msg: `建单失败 HTTP ${order.status}` }
  await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
  const gen = await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })
  const po = one(`select id, processing_order_no, route_key, route_source from processing_orders where order_id='${orderId}' order by created_at desc limit 1`)
  const rows = po ? psql(`select seq, operation_name from processing_position_operations where processing_order_id='${po.id}' order by seq`) : []
  return { ok: gen.json?.data?.[0]?.success === true, po, rows, msg: gen.json?.data?.[0]?.message || '' }
}
const names = (d) => d.rows.map((r) => r.operation_name)
const BASELINE = ['精裁-布', '布三边', '熨烫-布', '定型-布', '复烫-布', '布帘车被', '外帘打卷', '打包', '外帘装袋', '外帘发货']

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p8-routes.json')
  token = (await loginApi(PHONE)).token
  ctx = await mkProduct()
  const rs = (await api('GET', '/api/admin/production/routings', { token })).json?.data?.routings || []
  DEF = rs.find((r) => r.is_default)
  MAIN0 = [...DEF.mainline]
  log(`默认路线 ${DEF.id} / ${DEF.name}：${JSON.stringify(MAIN0)}`)

  // ── R-01：新建路线（合法）→ 读面可见 → 删除（软删）──
  let newId = null
  try {
    const c = await api('POST', '/api/admin/production/routings', {
      token, body: { name: `路线探针${RUN}`, positions: ['布料'], mainline: ['裁剪', '打包'], status: 'active' },
    })
    newId = c.json?.data?.id
    const list = (await api('GET', '/api/admin/production/routings', { token })).json?.data?.routings || []
    const seen = list.some((r) => r.id === newId)
    const del = newId ? await api('DELETE', `/api/admin/production/routings/${newId}`, { token }) : { status: 0 }
    const afterDel = one(`select coalesce(deleted,0) as del from production_route_templates where id='${newId}'`)
    c.status === 200 && seen && del.status === 200 && afterDel?.del === 1
      ? R.pass('R-01', '新建路线三态：建得出（读面可见）· 删得掉（软删生效）',
          `POST → 200（id=${newId}，读面可见=${seen}）；DELETE → ${del.status}，库内 deleted=${afterDel?.del}`,
          ['POST /api/admin/production/routings', 'GET /api/admin/production/routings', `DELETE /api/admin/production/routings/${newId}`])
      : R.fail('R-01', '新建路线三态', `POST=${c.status} 可见=${seen} DELETE=${del.status} deleted=${afterDel?.del}`)
  } catch (e) { R.fail('R-01', '新建路线三态', String(e).slice(0, 300)) }

  // ── R-05：路线「适用帘种」是否像「规则部位维」一样受闭词表保护 ──
  try {
    const bad = await api('POST', '/api/admin/production/routings', {
      token, body: { name: `路线探针非法${RUN}`, positions: ['火星帘'], mainline: [], status: 'active' },
    })
    const id = bad.json?.data?.id
    const sneaked = id ? one(`select coalesce(deleted,0) as del, positions::text as p from production_route_templates where id='${id}'`) : null
    if (id) await api('DELETE', `/api/admin/production/routings/${id}`, { token })   // 清理探针
    bad.status === 422
      ? R.pass('R-05', '路线「适用帘种」受闭词表保护（未知部位被拒）', `POST positions=['火星帘'] → HTTP 422：${(bad.json?.error?.message || '').slice(0, 100)}`,
          ['POST /api/admin/production/routings {positions:[\'火星帘\']}'])
      : R.fail('R-05', '路线「适用帘种」受闭词表保护（未知部位被拒）',
          `POST positions=['火星帘'] → **HTTP ${bad.status}**，库内落库 positions=${sneaked?.p} ⇒ 可建出**永不可能被选中**的路线（部位值域是闭的：布帘/纱帘/帘头/布料）；` +
          `同一维度在**规则**写面受闭词表保护（\`POSITION_LIMIT_VOCABULARY\` 达到 422），路线写面却没有 ⇒ 静默死配置`,
          ['POST /api/admin/production/routings {positions:[\'火星帘\']}', `SQL: select positions from production_route_templates where id='${id}'`])
  } catch (e) { R.fail('R-05', '路线适用帘种值域', String(e).slice(0, 300)) }

  // ── R-02：改名 → 派工单的 route_key 必须跟随 ──
  try {
    const newName = `窗帘工序路线（验收改名${RUN}）`
    const up = await api('PUT', `/api/admin/production/routings/${DEF.id}`, { token, body: { name: newName } })
    const d = await dispatch('R02')
    const followed = d.po?.route_key === newName
    await api('PUT', `/api/admin/production/routings/${DEF.id}`, { token, body: { name: DEF.name } })
    const d2 = await dispatch('R02b')
    const restored = d2.po?.route_key === DEF.name
    up.status === 200 && followed && restored
      ? R.pass('R-02', '路线改名 → 新加工单 route_key 跟随；还原后回到原名',
          `改名 → 加工单 ${d.po?.processing_order_no} route_key=「${d.po?.route_key}」；还原 → route_key=「${d2.po?.route_key}」`,
          [`PUT /api/admin/production/routings/${DEF.id} {name}`, `SQL: select route_key from processing_orders where id='${d.po?.id}'`])
      : R.fail('R-02', '路线改名 → route_key 跟随', `PUT=${up.status} 跟随=${followed}（实得「${d.po?.route_key}」）还原=${restored}（实得「${d2.po?.route_key}」）`)
  } catch (e) { R.fail('R-02', '路线改名闭环', String(e).slice(0, 300)) }

  // ── R-03：编辑主线顺序（定型 ↔ 复烫 对调）→ 派工顺序必须跟随 → 还原 ──
  try {
    const swapped = [...MAIN0]
    const i = swapped.indexOf('定型'), j = swapped.indexOf('复烫')
    ;[swapped[i], swapped[j]] = [swapped[j], swapped[i]]
    const up = await api('PUT', `/api/admin/production/routings/${DEF.id}`, { token, body: { mainline: swapped } })
    const back = one(`select mainline::text as m from production_route_templates where id='${DEF.id}'`)?.m || ''
    const d = await dispatch('R03')
    const expectSwapped = ['精裁-布', '布三边', '熨烫-布', '复烫-布', '定型-布', '布帘车被', '外帘打卷', '打包', '外帘装袋', '外帘发货']
    const followed = JSON.stringify(names(d)) === JSON.stringify(expectSwapped)
    await api('PUT', `/api/admin/production/routings/${DEF.id}`, { token, body: { mainline: MAIN0 } })
    const d2 = await dispatch('R03b')
    const restored = JSON.stringify(names(d2)) === JSON.stringify(BASELINE)
    up.status === 200 && followed && restored
      ? R.pass('R-03', '编辑主线顺序 → 加工单工序顺序逐字跟随；还原后回到基线顺序',
          `注入后 mainline=${back} ⇒ 派工 ${names(d).join(' → ')}；还原 ⇒ 与基线 10 道逐字相同`,
          [`PUT /api/admin/production/routings/${DEF.id} {mainline 对调 定型/复烫}`, `SQL: select mainline from production_route_templates where id='${DEF.id}'`])
      : R.fail('R-03', '编辑主线顺序 → 派工跟随', `PUT=${up.status} 跟随=${followed}（实得 ${names(d).join(',')}）还原=${restored}`)
  } catch (e) {
    await api('PUT', `/api/admin/production/routings/${DEF.id}`, { token, body: { mainline: MAIN0 } }).catch(() => {})
    R.fail('R-03', '编辑主线顺序闭环', String(e).slice(0, 300))
  }

  // ── R-04：护栏 —— 空主线 / 重复工序 / 引用幽灵工序 ──
  try {
    const a = await api('PUT', `/api/admin/production/routings/${DEF.id}`, { token, body: { mainline: [] } })
    const b = await api('PUT', `/api/admin/production/routings/${DEF.id}`, { token, body: { mainline: ['精裁', '精裁'] } })
    const c = await api('PUT', `/api/admin/production/routings/${DEF.id}`, { token, body: { mainline: ['幽灵工序X'] } })
    const all = [a.status, b.status, c.status].every((s) => s === 422)
    const kept = one(`select mainline::text as m from production_route_templates where id='${DEF.id}'`)?.m || ''
    all && kept.includes('精裁')
      ? R.pass('R-04', '主线写面三条护栏（空主线 / 重复工序 / 引用不存在工序）全部 422 且不改库',
          `空主线 ${a.status}｜重复 ${b.status}｜幽灵 ${c.status}；库内 mainline 未被改坏（${kept.slice(0, 60)}…）`,
          [`PUT /api/admin/production/routings/${DEF.id}（三种非法 mainline）`])
      : R.fail('R-04', '主线写面护栏', `空=${a.status} 重复=${b.status} 幽灵=${c.status}；库内 mainline=${kept.slice(0, 80)}`)
  } catch (e) { R.fail('R-04', '主线写面护栏', String(e).slice(0, 300)) }

  const fin = one(`select name, mainline::text as m, is_default from production_route_templates where id='${DEF.id}'`)
  log(`收尾核对：${fin?.name} is_default=${fin?.is_default} mainline=${fin?.m}（应与基线逐字相同）`)
  log(`summary=${JSON.stringify(R.summary())}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
