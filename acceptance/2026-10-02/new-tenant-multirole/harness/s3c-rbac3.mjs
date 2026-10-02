// 阶段 3c：RBAC 收口（第三轮）
//   ① 找到**真正合法**的建单载荷（第一轮的载荷被 422 挡下 ⇒ 越权实验不可判）
//   ② 用合法载荷重做判别性实验：有码=建成、无码=403（这才叫「权限切面在跑」的直证）
//   ③ 补齐另外两处路由守卫缺口的实测：/agent-workspace/human-sessions、/notifications
import { chromium, Recorder, log, newContext, shot, api, loginApi, me, psql, saveCtx, loadCtx,
         waitService, sleep, WEB } from './lib.mjs'

const R = new Recorder('s3c-rbac3.json')
const ctx = loadCtx()

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const admin = await loginApi(ctx.adminPhone)
  saveCtx({ adminToken: admin.token })
  log('== 阶段3c：RBAC 收口 ==')

  const base = {
    customerName: `权限探测客户${Date.now().toString().slice(-5)}`,
    customerPhone: '13000000000',
    customerAddress: '权限探测地址',
  }
  const variants = [
    { name: 'v1 姓名+电话+地址+明细', body: { ...base, items: [{ productName: '探测商品', quantity: 1, unitPrice: 1 }] } },
    { name: 'v2 明细补 productId', body: { ...base, items: [{ productId: '00000000-0000-0000-0000-000000000001', productName: '探测商品', quantity: 1, unitPrice: 1 }] } },
    { name: 'v3 加 userId/金额', body: { ...base, userId: '00000000-0000-0000-0000-000000000002', actualAmount: 1, items: [{ productName: '探测商品', quantity: 1, unitPrice: 1 }] } },
  ]
  let validBody = null
  for (const v of variants) {
    const res = await api('POST', '/api/admin/orders', { token: admin.token, body: v.body })
    const msg = res.json?.error?.message || res.json?.message || res.text.slice(0, 160)
    R.pass('RBAC3-01', `建单载荷探测：${v.name}`, `HTTP ${res.status}｜${msg}`, ['POST /api/admin/orders'])
    if (res.status === 200 && res.json?.data?.id) {
      validBody = v.body
      await api('DELETE', `/api/admin/orders/${res.json.data.id}`, { token: admin.token })
      R.pass('RBAC3-02', `命中合法载荷：${v.name}`, `HTTP 200 建成订单（已清理）；后端受理 ⇒ 该载荷可作判别性实验输入`, [])
      break
    }
  }

  if (validBody) {
    // ── 判别性实验：同一份**合法**载荷，按「有没有 order:create」分流 ──
    const adminRes = await api('POST', '/api/admin/orders', { token: admin.token, body: { ...validBody, customerName: base.customerName + 'A' } })
    if (adminRes.json?.data?.id) await api('DELETE', `/api/admin/orders/${adminRes.json.data.id}`, { token: admin.token })
    R.pass('RBAC3-03', '判别性实验：管理员（恒全权）', `合法载荷 → HTTP ${adminRes.status}（期望 200）`, ['POST /api/admin/orders'])

    for (const e of ctx.employees || []) {
      const has = (e.perms || []).includes('order:create')
      const res = await api('POST', '/api/admin/orders', { token: e.token, body: { ...validBody, customerName: `${base.customerName}${e.roleCode.slice(0, 3)}` } })
      const id = res.json?.data?.id
      if (id) await api('DELETE', `/api/admin/orders/${id}`, { token: admin.token })
      const ok = has ? res.status === 200 : res.status === 403
      ok
        ? R.pass('RBAC3-03', `判别性实验：${e.pos}`, `持 order:create=${has} → HTTP ${res.status}${id ? '（建成，已清理）' : ''} ⇒ 与权限码一致`, ['POST /api/admin/orders 合法载荷'])
        : R.fail('RBAC3-03', `判别性实验：${e.pos}`, `持 order:create=${has} → HTTP ${res.status}${id ? '（建成，已清理）' : ''}；期望 ${has ? 200 : 403}｜响应=${(res.json?.error?.message || res.text).slice(0, 140)}`)
    }
  } else {
    R.fail('RBAC3-02', '命中合法载荷', '三种载荷均未通过校验，无法做判别性实验；各载荷报错见上')
  }

  // ── 路由守卫缺口实测（三处：入库单 / 在线接待 / 通知中心）──
  const targets = [
    ['/inbound-orders', 'inbound:view'],
    ['/agent-workspace/human-sessions', 'agent:session'],
    ['/notifications', null],
  ]
  for (const [route, code] of targets) {
    const cand = (ctx.employees || []).find((e) => code && !(e.perms || []).includes(code))
    if (!cand) {
      R.skip('RBAC3-04', `路由守卫缺口实测：${route}`, `无「缺 ${code}」的样本身份`)
      continue
    }
    const browser = await chromium.launch({ headless: true })
    const { page } = await newContext(browser)
    const apiCalls = []
    page.on('response', (r) => {
      const u = r.url()
      if (u.includes('/api/admin/') && u.includes(route.split('/')[1] || '')) apiCalls.push(`${r.status()} ${u.split('/api')[1].slice(0, 60)}`)
    })
    try {
      const { loginUi } = await import('./lib.mjs')
      await loginUi(page, { mode: 'employee', identifier: `${cand.username}@${ctx.tenantCode}`, password: ctx.finalPwd })
      await page.goto(WEB + route, { waitUntil: 'domcontentloaded', timeout: 30000 })
      await sleep(2500)
      const deniedPage = await page.getByText('无权访问该页面').first().isVisible().catch(() => false)
      const body = (await page.evaluate(() => document.body.innerText)).replace(/\n/g, ' ')
      const shotPath = await shot(page, `s3c-guard-${route.replace(/\//g, '-')}`)
      const err = await page.locator('code').first().innerText().catch(() => '')
      deniedPage
        ? R.pass('RBAC3-04', `路由守卫：${route}`, `${cand.pos}（缺 ${code}）被 403 页拦截（提示缺 ${err.trim()}）`, [shotPath])
        : R.fail('RBAC3-04', `路由守卫：${route}`,
            `${cand.pos}（缺 ${code}）**未被** 403 页拦截；页面文本=${body.slice(0, 180)}；接口调用=${apiCalls.join(' | ') || '未捕获'}`,
            [shotPath, `对照：frontend/admin-web/src/app/(dashboard)/layout.tsx 的 ROUTE_PERMISSION_MAP`])
    } catch (e) {
      R.fail('RBAC3-04', `路由守卫探针异常：${route}`, String(e).slice(0, 250))
    } finally {
      await browser.close()
    }
  }

  const s = R.summary()
  log(`== 阶段3c 完成：pass=${s.pass} fail=${s.fail} skip=${s.skip}`)
}

main().catch((e) => { R.fail('RBAC3-FATAL', '阶段3c 致命错误', String(e).slice(0, 400)); process.exitCode = 1 })
