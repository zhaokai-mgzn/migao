// e2e/login-redproof.js — 登录判据的**双向红证**（不需要模拟器、不需要网络）
/**
 * 为什么需要它：`migao-acceptance` 铁律「每条断言都要有红证」——
 * 登录守卫若做成恒真（永远 pass）或恒红，都等于没有守卫。本脚本用**假 mp（内存 storage）+ 可注入 fetch**
 * 同时证明两个方向：
 *   ① 有有效登录态            ⇒ **pass**（不能恒红）
 *   ② 无 / 空 / 非 JWT / 过期 ⇒ **红**（不能恒真），且注入失败时返回 LOGIN_MISSING
 *   ③ 注入成功后 storage 真的落了 4 个 key（token/user/tenant_id/auth-store 快照）
 *
 * 运行：cd frontend/mini-app && node e2e/login-redproof.js   （退出码非 0 = 红证失败）
 * 本文件不是测试文件（是红证工具），无需 case_ids。
 */
const login = require('./lib/login')

let failed = 0
const results = []

function check(name, actual, expected) {
  const ok = actual === expected
  if (!ok) failed += 1
  results.push({ name, expected, actual, ok })
  console.log(`  ${ok ? '✅' : '❌'} ${name} — expected=${JSON.stringify(expected)} actual=${JSON.stringify(actual)}`)
}

/** 假 mp：内存 storage + 记录 reLaunch，模拟 wx.setStorageSync/getStorageSync/clearStorageSync */
function fakeMp(initial = {}) {
  const store = { ...initial }
  const calls = []
  return {
    store,
    calls,
    async callWxMethod(method, ...args) {
      calls.push([method, ...args])
      if (method === 'getStorageSync') return store[args[0]] === undefined ? '' : store[args[0]]
      if (method === 'setStorageSync') {
        store[args[0]] = args[1]
        return undefined
      }
      if (method === 'clearStorageSync') {
        for (const k of Object.keys(store)) delete store[k]
        return undefined
      }
      throw new Error(`fakeMp 未实现 ${method}`)
    },
    async reLaunch(url) {
      calls.push(['reLaunch', url])
      return { path: 'pages/chat/index/index' }
    },
    async evaluate() {
      throw new Error('fakeMp 未实现 evaluate（应走 callWxMethod 分支）')
    },
  }
}

/** 造一个 JWT（只关心三段 + payload.exp，签名无所谓：判据只看结构与 exp） */
function makeJwt(exp) {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64').replace(/=+$/, '')
  return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ sub: 'u1', exp })}.sig`
}

const now = Math.floor(Date.now() / 1000)
const validJwt = makeJwt(now + 3600)
const expiredJwt = makeJwt(now - 60)
const noExpJwt = (() => {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64').replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64({ sub: 'u1' })}.sig`
})()

const okFetch = async () => ({
  ok: true,
  status: 200,
  async text() {
    return JSON.stringify({
      success: true,
      data: {
        accessToken: validJwt,
        // 键集合/取值与 2026-09-14 live 实测一致（POST app.migaozn.com/api/auth/sms/login）
        user: {
          id: 'user_admin_001',
          nickname: '赵凯',
          role: 'admin',
          identityType: 'sms',
          roles: ['admin'],
          tenantId: 1,
          tenantName: '词元通达',
          botName: '光头强',
        },
      },
    })
  },
})
const badFetch = async () => {
  throw new Error('connect ECONNREFUSED 127.0.0.1:1（红证：故意指向不可用地址）')
}

async function main() {
  console.log('【1】纯判据 resolveLoginState —— 双向（缺失/空/非法/过期 ⇒ 红；有效 ⇒ pass）')
  check('undefined ⇒ 红', login.resolveLoginState(undefined).ok, false)
  check('undefined ⇒ 带 LOGIN_MISSING 标记', login.resolveLoginState(undefined).marker, login.LOGIN_MISSING)
  check("'' ⇒ 红", login.resolveLoginState('').ok, false)
  check("'   ' ⇒ 红", login.resolveLoginState('   ').ok, false)
  check("'not-a-jwt' ⇒ 红（非三段）", login.resolveLoginState('not-a-jwt').ok, false)
  check('过期 JWT ⇒ 红', login.resolveLoginState(expiredJwt, now).ok, false)
  check('有效 JWT ⇒ pass（不能恒红）', login.resolveLoginState(validJwt, now).ok, true)
  check('无 exp JWT ⇒ pass（与产品 checkTokenValidity 一致）', login.resolveLoginState(noExpJwt, now).ok, true)
  check('有效 JWT ⇒ 无 marker', login.resolveLoginState(validJwt, now).marker, null)

  console.log('\n【2】ensureLoggedIn —— 已有登录态 ⇒ 不注入（source=storage）')
  {
    const mp = fakeMp({ [login.STORAGE.TOKEN]: validJwt })
    const r = await login.ensureLoggedIn(mp, { fetchImpl: badFetch })
    check('source', r.source, 'storage')
    check('ok', r.ok, true)
    check('未触发短信登录（fetch 未被使用即无异常）', r.marker, null)
  }

  console.log('\n【3】ensureLoggedIn —— 登录态缺失 ⇒ 注入成功（不能恒红）＋ 落 4 个 key')
  {
    const mp = fakeMp({})
    const r = await login.ensureLoggedIn(mp, { fetchImpl: okFetch })
    check('ok', r.ok, true)
    check('source', r.source, 'injected')
    check('auth_token 已落库且可用', login.resolveLoginState(mp.store[login.STORAGE.TOKEN]).ok, true)
    check('auth_user 已落库', typeof mp.store[login.STORAGE.USER], 'string')
    const storedUser = JSON.parse(mp.store[login.STORAGE.USER])
    check('auth_user 含 botName（导航名断言的数据源）', storedUser.botName, '光头强')
    // 形状镜像：接口返回的是 camelCase tenantId，**不得**被 harness 补成 snake_case tenant_id
    check('auth_user.tenantId 原样保留（camelCase，与响应一致）', storedUser.tenantId, 1)
    check('auth_user **未被补** tenant_id 字段（harness 不遮蔽产品契约不一致）', 'tenant_id' in storedUser, false)
    check(
      'auth_user 键集合 = 响应原物（多键即遮蔽）',
      Object.keys(storedUser).sort().join(','),
      'botName,id,identityType,nickname,role,roles,tenantId,tenantName'
    )
    check('tenant_id storage key = 会话租户（独立 key，非 user 字段）', mp.store[login.STORAGE.TENANT_ID], 1)
    check('auth-store 快照已落库（zustand persist）', JSON.parse(mp.store[login.STORAGE.STORE]).state.isLoggedIn, true)
    check('auth-store.state.user 与 auth_user 同形（同一份镜像）', JSON.stringify(JSON.parse(mp.store[login.STORAGE.STORE]).state.user), JSON.stringify(storedUser))
    check('注入后调用了 reLaunch', mp.calls.some((c) => c[0] === 'reLaunch'), true)
  }

  console.log('\n【4】ensureLoggedIn —— 登录态缺失且注入失败 ⇒ **红**（失败关闭，不许继续跑）')
  {
    const mp = fakeMp({})
    const r = await login.ensureLoggedIn(mp, { fetchImpl: badFetch, apiBase: 'http://127.0.0.1:1' })
    check('ok=false（红）', r.ok, false)
    check('带 LOGIN_MISSING 标记', r.marker, login.LOGIN_MISSING)
    check('reason 含定位信息（apiBase）', r.reason.includes('127.0.0.1:1'), true)
    check('storage 未被写入假 token', mp.store[login.STORAGE.TOKEN] === undefined, true)
  }

  console.log('\n【5】ensureLoggedIn —— 过期 token + 注入失败 ⇒ 红（过期不得被当已登录）')
  {
    const mp = fakeMp({ [login.STORAGE.TOKEN]: expiredJwt })
    const r = await login.ensureLoggedIn(mp, { fetchImpl: badFetch, apiBase: 'http://127.0.0.1:1' })
    check('ok=false（红）', r.ok, false)
    check('marker', r.marker, login.LOGIN_MISSING)
  }

  console.log('\n【6】clearStorage（冷环境验证用）真能清掉登录态')
  {
    const mp = fakeMp({ [login.STORAGE.TOKEN]: validJwt, [login.STORAGE.USER]: '{"id":"u1"}' })
    await login.clearStorage(mp)
    check('清空后 auth_token 为空 ⇒ 判据红', login.resolveLoginState(mp.store[login.STORAGE.TOKEN]).ok, false)
  }

  const total = results.length
  console.log(`\n=== 红证汇总：${total - failed}/${total} 通过，${failed} 失败 ===`)
  if (failed > 0) {
    console.error('❌ 登录判据红证失败：说明守卫方向性有误（可能恒真或恒红）')
    process.exit(1)
  }
  console.log('✅ 双向红证通过：有效登录态 ⇒ pass；缺失/空/非法/过期/注入失败 ⇒ LOGIN_MISSING 红')
}

main().catch((e) => {
  console.error('红证脚本异常:', e)
  process.exit(1)
})
