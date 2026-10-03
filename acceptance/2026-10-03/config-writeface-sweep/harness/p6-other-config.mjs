// P6：**其余配置写面**横切扫描（宁多勿少：枚举到的每一个配置写面都罩一块）
//
// 覆盖（发现方式 = 枚举 `backend/admin-api/src/main/java/com/migao/admin/controller/*.java` 的
//   @Put/@Post/@Delete 映射 + `frontend/admin-web/src/lib/api.ts` 的写面函数，逐个筛出「配置类」）：
//   ① 加工费组合 pricing（POST/PUT/DELETE /processing-fee-combinations）
//   ② 算料公式租户级配置（PUT /production/craft-calc-config，全量替换）
//   ③ 裁高（定高）配置（PUT /production/cutting-height-config，全量替换）
//   ④ 工人端页面开关（PUT /worker-page-config，全量替换）
//   ⑤ 小件用料尺寸表（PUT /production/remnants/small-item-specs，全量替换）
//   ⑥ 加工项（POST/PUT/DELETE /processing-items）
//   ⑦ 店铺设置（PUT /admin/settings，部分更新）
//   ⑧ 租户 AI 配置（PUT /admin/tenant/ai-config，部分更新）
import { api, psql, one, log, Recorder, waitService } from './lib.mjs'
import { T, snapshot, diff, changedKeys, overreach, declaredAudit, fmt, canonStr, login, nowCST, restoreTo, verifyClean, probe, claimsFor } from './sweep.mjs'
import { PREFIX, RUN, residue, sweepLeftovers } from './setup.mjs'

let token, R
const get = async (p) => (await api('GET', p, { token })).json?.data
const put = async (p, body) => { const r = await api('PUT', p, { token, body }); return { status: r.status, json: r.json } }
const post = async (p, body) => { const r = await api('POST', p, { token, body }); return { status: r.status, json: r.json } }

/** 全量替换类写面：读回当前配置 → 只改一个键 → 判据 = 只有该键变（且 HTTP 200 真的写了）。 */
async function replaceProbe(id, name, path, pick, ctxName, { unwrap = (x) => x, send = null, extraAllowed = [] } = {}) {
  const raw = await get(path)
  if (!raw) { R.skip(id, name, `读面 ${path} 无数据 ⇒ 本环境该写面不可达（如实登记）`); return null }
  const body = JSON.parse(JSON.stringify(unwrap(raw)))
  const changed = pick(body)
  if (changed === null) { R.skip(id, name, `无法从读面形态构造「只改一个键」的 payload（读面=${canonStr(raw).slice(0, 220)}）`); return null }
  const r = await probe(R, {
    id, name,
    note: { request: `PUT ${path} body=<读面全量 + 只改 1 个键：${Object.keys(changed).join(',')}>（**全量替换**写面 ⇒ 判据按「只允许被改的那个键变化」收窄）`, extraAllowed },
    payloadKeys: Object.keys(changed),
    context: { configName: ctxName || path },
    act: async () => put(path, send ? send(body) : body),
  })
  // 🔴 附加断言：写面必须真的 **HTTP 200**（否则「允许集合为空」可能是「请求根本没被接受」= 假绿）
  if (!r.skipped) {
    const okHttp = (r.res?.status ?? 0) >= 200 && (r.res?.status ?? 0) < 300
    R.add(`${id}-http`, `${name} · 写面真的被接受（HTTP 2xx）`, okHttp ? 'pass' : 'fail',
      `HTTP ${r.res?.status}${r.res?.json?.success === false ? '；resp=' + JSON.stringify(r.res.json.error || r.res.json).slice(0, 200) : ''}`)
  }
  return r
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  R = new Recorder('p6-other-config.json')
  token = await login()
  const t0 = nowCST()
  log(`=== P6 其余配置写面 开始 ${t0.cst}（UTC ${t0.utc}）run=${RUN} ===`)
  const lo = await sweepLeftovers(token)
  R.pass('W6-L0', '清场：历史残留同前缀对象', `清理 ${lo.done.length} 条：${lo.done.join(' | ') || '（无）'}`)

  const created = { items: [], fees: [] }
  try {
    // ───────── ① 加工费组合（先自建加工项 ⇒ 组合的特征名必须在目录里真有）─────────
    const cat = one(`select id from processing_categories where tenant_id=${T} and coalesce(deleted,0)=0 limit 1`)
    let seedItemId = null
    if (cat?.id) {
      const seedName = `${PREFIX}组合料${RUN}`
      const si = await post('/api/admin/processing-items', { name: seedName, categoryId: cat.id, unit: '米' })
      const srow = one(`select id, name from processing_items where tenant_id=${T} and name='${seedName}' limit 1`)
      if (srow) { seedItemId = srow.id; created.items.push(srow.id); log(`[seed-item] ${seedName} HTTP ${si.status} id=${srow.id}`) }
    }
    const comboKey = `${PREFIX}组合${RUN}`
    const c1 = await post('/api/admin/production/processing-fee-combinations',
      { items: [seedItemId ? (one(`select name from processing_items where id='${seedItemId}'`)?.name) : comboKey], unit_price: 3.5, sort_order: 99 })
    const feeRow = one(`select id, composition_key, items::text as items, unit_price::text as up, status, coalesce(deleted,0) as del
        from processing_fee_combinations where tenant_id=${T} and composition_key like '%${RUN}%' order by created_at desc limit 1`)
    if (feeRow) {
      created.fees.push(feeRow.id)
      R.pass('W6-01', '加工费组合写面：POST 新建（自建自清；特征名取自自建加工项 ⇒ 目录里真有）', `HTTP ${c1.status}；行=${canonStr(feeRow)}`)
      await probe(R, {
        id: 'W6-02', name: '加工费组合写面：只改 unit_price',
        note: { request: `PUT /api/admin/production/processing-fee-combinations/${feeRow.id} body={"unit_price":4.25}` },
        payloadKeys: ['unit_price'],
        context: { feeId: feeRow.id, feeKey: feeRow.composition_key },
        act: async () => put(`/api/admin/production/processing-fee-combinations/${feeRow.id}`, { unit_price: 4.25 }),
      })
      await probe(R, {
        id: 'W6-03', name: '加工费组合写面：只改 sort_order',
        note: { request: `PUT /api/admin/production/processing-fee-combinations/${feeRow.id} body={"sort_order":7}` },
        payloadKeys: ['sort_order'],
        context: { feeId: feeRow.id, feeKey: feeRow.composition_key },
        act: async () => put(`/api/admin/production/processing-fee-combinations/${feeRow.id}`, { sort_order: 7 }),
      })
      await probe(R, {
        id: 'W6-04', name: '加工费组合写面：DELETE（软删语义 status=disabled）',
        note: { request: `DELETE /api/admin/production/processing-fee-combinations/${feeRow.id}` },
        payloadKeys: ['status', 'deleted'],
        context: { feeId: feeRow.id, feeKey: feeRow.composition_key },
        act: async () => { const r = await api('DELETE', `/api/admin/production/processing-fee-combinations/${feeRow.id}`, { token }); return { status: r.status, json: r.json } },
      })
    } else {
      R.skip('W6-01', '加工费组合写面：POST 新建', `HTTP ${c1.status}；resp=${JSON.stringify(c1.json).slice(0, 250)} ⇒ 本环境不可达（如实登记）`)
    }

    // ───────── ② 算料公式配置（全量替换）─────────
    await replaceProbe('W6-05', '算料公式配置写面：只改 margin_multi（全量替换；+0.01）',
      '/api/admin/production/craft-calc-config',
      (b) => { if (typeof b.margin_multi !== 'number') return null; b.margin_multi = Number((Number(b.margin_multi) + 0.01).toFixed(4)); return { margin_multi: b.margin_multi } },
      'craft-calc-config', { unwrap: (x) => (x && x.config ? x.config : x) })
    // ───────── ③ 裁高配置（全量替换）─────────
    await replaceProbe('W6-06', '裁高配置写面：只改 rounding.digits（+1；全量替换）',
      '/api/admin/production/cutting-height-config',
      (b) => {
        if (!b.rounding || typeof b.rounding.digits !== 'number') return null
        // 值域 0..3（服务端校验）；取一个与当前**不同且在域内**的值
        const next = b.rounding.digits === 3 ? 1 : b.rounding.digits + 1
        b.rounding.digits = next
        return { 'rounding.digits': next }
      },
      // ⚠️ 该租户**原本没有** `cutting_height_configs` 行（读面 `source=default`）⇒ 全量替换写面会**首建一行**。
      //    这是该写面的固有语义（首建），不是副作用 ⇒ 显式声明放行（并把首建这个事实记进证据）。
      'cutting-height-config', { unwrap: (x) => (x && x.config ? x.config : x), extraAllowed: ['cutting_height_configs.*', 'cutting_height_configs.rounding', 'cutting_height_configs.items', 'cutting_height_configs.rounding.digits'] })
    // ───────── ④ 工人端页面开关（全量替换）─────────
    await replaceProbe('W6-07', '工人端页面开关写面：只改 pages（全量替换；body 只收 {pages}）',
      '/api/admin/worker-page-config',
      (b) => { if (!Array.isArray(b.pages)) return null; const p = [...b.pages]; p.reverse(); b.pages = p; return { pages: b.pages } },
      'worker-page-config', { unwrap: (x) => ({ pages: Array.isArray(x?.pages) ? x.pages : [] }) })
    // ───────── ⑤ 小件用料尺寸表（全量替换）─────────
    await replaceProbe('W6-08', '小件用料尺寸表写面：items=[]（清空 = 回到未配置；全量替换）',
      '/api/admin/production/remnants/small-item-specs',
      (b) => { if (!Array.isArray(b.items)) return null; b.items = []; return { items: [] } },
      'remnant-small-item-specs')

    // ───────── ⑥ 加工项（新建 → 改名 → 删除）─────────
    if (cat?.id) {
      const itemName = `${PREFIX}加工项${RUN}`
      const i1 = await post('/api/admin/processing-items', { name: itemName, categoryId: cat.id, unit: '米' })
      const item = one(`select id, name, unit, status, coalesce(deleted,0) as del from processing_items where tenant_id=${T} and name='${itemName}' limit 1`)
      if (item) {
        created.items.push(item.id)
        R.pass('W6-09', '加工项写面：POST 新建（自建自清）', `HTTP ${i1.status}；行=${canonStr(item)}；categoryId=${cat.id}`)
        await probe(R, {
          id: 'W6-10', name: '加工项写面：只改 name（改名）',
          note: { request: `PUT /api/admin/processing-items/${item.id} body={"name":"${PREFIX}加工项改${RUN}"}` },
          payloadKeys: ['name'],
          context: { itemId: item.id, itemName: item.name },
          act: async () => put(`/api/admin/processing-items/${item.id}`, { name: `${PREFIX}加工项改${RUN}` }),
        })
        await probe(R, {
          id: 'W6-11', name: '加工项写面：只改 unit',
          note: { request: `PUT /api/admin/processing-items/${item.id} body={"unit":"个"}` },
          payloadKeys: ['unit'],
          context: { itemId: item.id, itemName: item.name },
          act: async () => put(`/api/admin/processing-items/${item.id}`, { unit: '个' }),
        })
        await probe(R, {
          id: 'W6-12', name: '加工项写面：DELETE（删除）',
          note: { request: `DELETE /api/admin/processing-items/${item.id}` },
          payloadKeys: ['deleted'],
          context: { itemId: item.id, itemName: item.name },
          act: async () => { const r = await api('DELETE', `/api/admin/processing-items/${item.id}`, { token }); return { status: r.status, json: r.json } },
        })
      } else {
        R.skip('W6-09', '加工项写面：POST 新建', `HTTP ${i1.status}；resp=${JSON.stringify(i1.json).slice(0, 250)} ⇒ 本环境不可达（如实登记）`)
      }
    } else {
      R.skip('W6-09', '加工项写面：新建', `本租户没有可用的 processing_categories 行 ⇒ 无法构造合法 payload（如实登记）`)
    }

    // ───────── ⑦ 店铺设置（部分更新）─────────
    const st = await get('/api/admin/settings')
    const stKey = st && Object.keys(st).find((k) => typeof st[k] === 'string' && k.toLowerCase().includes('name'))
    if (st && stKey) {
      const same = st[stKey]
      await probe(R, {
        id: 'W6-13', name: `店铺设置写面：只改 ${stKey}（部分更新；值同原值 ⇒ 允许集合应为空）`,
        note: { request: `PUT /api/admin/settings body={"${stKey}":"<原值>"}` },
        payloadKeys: [stKey],
        context: { settingsKey: stKey, settingsValue: String(same) },
        act: async () => put('/api/admin/settings', { [stKey]: same }),
      })
    } else {
      R.skip('W6-13', '店铺设置写面：部分更新', `读面 /api/admin/settings 无「名字类字符串键」（读面键=${st ? Object.keys(st).join(',') : 'null'}）⇒ 本环境不可构造（如实登记）`)
    }

    // ───────── ⑧ 租户 AI 配置（部分更新）─────────
    const ai = await get('/api/admin/tenant/ai-config')
    if (ai && typeof ai === 'object') {
      const k = Object.keys(ai).find((x) => typeof ai[x] === 'string' && ai[x].length > 0)
      if (k) {
        await probe(R, {
          id: 'W6-14', name: `租户 AI 配置写面：只改 ${k}（部分更新；值同原值 ⇒ 允许集合应为空）`,
          note: { request: `PUT /api/admin/tenant/ai-config body={"${k}":"<原值>"}` },
          payloadKeys: [k],
          context: { aiKey: k, aiValue: String(ai[k]) },
          act: async () => put('/api/admin/tenant/ai-config', { [k]: ai[k] }),
        })
      } else R.skip('W6-14', '租户 AI 配置写面', `读面无可复用的字符串键（键=${Object.keys(ai).join(',')}）⇒ 如实登记`)
    } else {
      R.skip('W6-14', '租户 AI 配置写面', `读面 /api/admin/tenant/ai-config 无数据 ⇒ 如实登记`)
    }
  } finally {
    try {
      // 自清：加工项 + 加工费组合
      for (const id of created.items) { const r = await api('DELETE', `/api/admin/processing-items/${id}`, { token }); log(`[cleanup-item] ${id} HTTP ${r.status}`) }
      for (const id of created.fees) { const r = await api('DELETE', `/api/admin/production/processing-fee-combinations/${id}`, { token }); log(`[cleanup-fee] ${id} HTTP ${r.status}`) }
      const leftItems = psql(`select id from processing_items where tenant_id=${T} and name like '${PREFIX}%' and coalesce(deleted,0)=0`)
      // ⚠️ 该端点的「删除」语义 = `status=disabled`（`deleted` 仍为 0，行保留可回溯）⇒ 残留按 status 判
      const leftFees = psql(`select id, composition_key, status, coalesce(deleted,0) as del from processing_fee_combinations
          where tenant_id=${T} and composition_key like '%${RUN}%' and coalesce(deleted,0)=0 and coalesce(status,'active') <> 'disabled'`)
      const res = residue()
      leftItems.length === 0 && leftFees.length === 0 && res.aliveTotal === 0
        ? R.pass('W6-98', '零残留读数：自建对象存活数 = 0',
            `加工项存活=${leftItems.length}；加工费组合存活=${leftFees.length}；前缀对象存活=${res.aliveTotal}；存活明细=${res.aliveSummary}`)
        : R.fail('W6-98', '零残留读数', `加工项=${JSON.stringify(leftItems)}；费用组合=${JSON.stringify(leftFees)}；存活明细=${res.aliveSummary}`)
    } catch (e) { R.fail('W6-98', '探针自清', String(e).slice(0, 300)) }
  }
  const t1 = nowCST()
  R.pass('W6-90', '时间戳（+08 口径）', `开始 ${t0.cst} / 结束 ${t1.cst}（UTC: ${t0.utc} → ${t1.utc}）`)
  log(`P6 summary=${JSON.stringify(R.summary())} at ${t1.cst}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
