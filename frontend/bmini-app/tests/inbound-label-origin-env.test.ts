// case_ids: BM-010, MC-012
/**
 * 入库标签二维码的 **origin**：构建期可覆盖 + **缺省逐字不变** + 写读同源（issue #8942）
 *
 * ## 治的形态（已验收确认的生产缺陷）
 *
 * origin 曾写死成 `https://app.migaozn.com`（`frontend/bmini-app/src/utils/inbound/truth.ts`），
 * 而生产落地面是 `app.cytda.com` ⇒ **生产打印出来的标签把扫码请求送到测试服务器**；
 * 页面上一切正常，只有工人扫了才会发现。手工改常量又会把**测试环境**的产物一起改掉
 * （测试产物必须逐字不变）⇒ 只能做成**构建期覆盖**（`TARO_APP_PUBLIC_APP_ORIGIN`）。
 *
 * ## 四条判据（每条都能单独变红）
 *
 * | # | 判据 | 红证（怎么让它单独红） |
 * |---|---|---|
 * | O1 | 缺省（不设 env）⇒ origin 与整条码内容**逐字**还是 `https://app.migaozn.com/i/<短码>` | 把缺省值改成别的域名 ⇒ 红 |
 * | O2 | 设 `TARO_APP_PUBLIC_APP_ORIGIN` ⇒ 码内容跟着走成 `<origin>/i/<短码>`（`inboundLabelCodeUrl` / `labelCodePayload` 两条路） | 常量没读 env / 读错 env 名 ⇒ 红 |
 * | O3 | **写读同源**：覆盖 origin 后，解析侧（`classifyScannedCode` / `classifyManualCode`）认**新** origin 的 `/i/`、`/s/` | 解析侧另写一份域名 ⇒ 红 |
 * | O4 | **构建期接线**：`config/index.ts` 的 `defineConstants` 登记了该键、且缺省回落**空串**（否则 CI 无 `.env` ⇒ 产物残留 `process.env` ⇒ 浏览器端白屏，issue #2693） | 摘掉该键 / 把回落写成别的域名 ⇒ 红 |
 *
 * ⚠️ **语料读面**：O4 读的是**源码文本**（`config/index.ts` 在 jest 里不被执行）——
 * 故 O4 的判定函数自带**注入式红证**（键改名 / 回落改成写死域名 ⇒ 同一函数必须报问题），
 * 不让它退化成"永远绿"的文本断言（`migao-dev-flow` §34.18.3：判据本身要能红）。
 *
 * ⚠️ **模块必须重载**：两个常量都在**模块体**里读 `process.env`（构建期替换的语义）⇒
 * 改 `process.env` 后必须 `jest.isolateModules` 重新 require，否则读到的是第一次加载的缓存值。
 */
import fs from 'fs'
import path from 'path'

const REPO_ROOT = path.resolve(__dirname, '..')
const DEFAULT_ORIGIN = 'https://app.migaozn.com'
const PROD_ORIGIN = 'https://app.cytda.com'
const ENV_KEY = 'TARO_APP_PUBLIC_APP_ORIGIN'

interface InboundModules {
  truth: typeof import('../src/utils/inbound/truth')
  shortCode: typeof import('../src/utils/inbound/shortCode')
  codeSpace: typeof import('../src/utils/inbound/codeSpace')
}

/**
 * 按给定 env **重新加载**被测模块。
 * `origin === null` ⇒ 删掉该 env（= 缺省构建的等价形态；同时清掉开发机 shell 里可能存在的同名变量）。
 */
function loadInboundModules(origin: string | null): InboundModules {
  const bag = process.env as unknown as Record<string, string | undefined>
  const previous = bag[ENV_KEY]
  if (origin === null) delete bag[ENV_KEY]
  else bag[ENV_KEY] = origin

  let loaded: InboundModules | undefined
  jest.isolateModules(() => {
    loaded = {
      truth: require('../src/utils/inbound/truth'),
      shortCode: require('../src/utils/inbound/shortCode'),
      codeSpace: require('../src/utils/inbound/codeSpace'),
    }
  })

  if (previous === undefined) delete bag[ENV_KEY]
  else bag[ENV_KEY] = previous

  if (!loaded) throw new Error('模块重载失败：jest.isolateModules 回调没执行（判据会假绿）')
  return loaded
}

/**
 * O4 的判定函数（纯函数，便于注入式红证）。
 * 登记形态必须**逐字**是「键 + `JSON.stringify(process.env.TARO_APP_PUBLIC_APP_ORIGIN || '')`」：
 * 缺省空串是刻意的 —— 它让 `truth.ts` 的 `|| 'https://app.migaozn.com'` 生效，
 * 如果把回落写成写死域名，缺省性就偷偷搬到了 config 里（两处真值 = 漂移）。
 */
function originDefineKeyProblems(configSrc: string): string[] {
  const ok = /['"]process\.env\.TARO_APP_PUBLIC_APP_ORIGIN['"]\s*:\s*JSON\.stringify\(\s*process\.env\.TARO_APP_PUBLIC_APP_ORIGIN\s*\|\|\s*(''|"")\s*\)/.test(
    configSrc,
  )
  if (ok) return []
  return [
    `frontend/bmini-app/config/index.ts 的 defineConstants 缺 \`'process.env.${ENV_KEY}': JSON.stringify(process.env.${ENV_KEY} || '')\` ` +
      '（构建期覆盖会静默不生效；无 .env 时产物残留 process.env 还会白屏，issue #2693）',
  ]
}

describe('入库标签码 origin：构建期覆盖 + 缺省逐字不变（issue #8942）', () => {
  it('O1 缺省（不设 env）⇒ 码内容逐字 = https://app.migaozn.com/i/<短码>', () => {
    const { truth } = loadInboundModules(null)

    expect(truth.INBOUND_LABEL_CODE_ORIGIN).toBe(DEFAULT_ORIGIN)
    expect(truth.INBOUND_LABEL_CODE_PATH).toBe('/i/')
    expect(truth.inboundLabelCodeUrl('ABCD2345')).toBe('https://app.migaozn.com/i/ABCD2345')
  })

  it('O1b 缺省 ⇒ 解析侧照旧认 app.migaozn.com 的 /i/<短码>（既有产物行为不变）', () => {
    const { codeSpace } = loadInboundModules(null)
    const reading = codeSpace.classifyScannedCode('https://app.migaozn.com/i/ABCD2345')

    expect(reading.space).toBe('inbound-label')
    expect(reading.shortCode).toBe('ABCD2345')
    expect(reading.message).toBe(codeSpace.SCAN_INBOUND_MESSAGE)
  })

  it('O2 设 env ⇒ 码内容跟着走（拼串与画码两条路共用同一个常量）', () => {
    const { truth, shortCode } = loadInboundModules(PROD_ORIGIN)

    expect(truth.INBOUND_LABEL_CODE_ORIGIN).toBe(PROD_ORIGIN)
    expect(truth.inboundLabelCodeUrl('ABCD2345')).toBe('https://app.cytda.com/i/ABCD2345')
    // 扫码画码走的是 labelCodePayload（短码校验 + 拼串）⇒ 也必须跟着走
    expect(shortCode.labelCodePayload('abcd2345')).toBe('https://app.cytda.com/i/ABCD2345')
    // 脏码仍按「缺码」处置：**不**因为换了 origin 就编造一条能扫但错指向的 URL
    expect(shortCode.labelCodePayload('ABCDI234')).toBeNull()
  })

  it('O3 写读同源：覆盖 origin 后，解析侧认新 origin 的 /i/ 与 /s/', () => {
    const { codeSpace } = loadInboundModules(PROD_ORIGIN)

    const inbound = codeSpace.classifyScannedCode('https://app.cytda.com/i/ABCD2345')
    expect(inbound.space).toBe('inbound-label')
    expect(inbound.shortCode).toBe('ABCD2345')

    const wash = codeSpace.classifyManualCode('https://app.cytda.com/s/7K3M9QP2')
    expect(wash.space).toBe('wash-code')
    expect(wash.shortCode).toBe('7K3M9QP2')

    // 照实登记（迁移缺口，不在本单静默扩大范围）：解析侧只认**当前构建**的 origin ⇒
    // 切 origin 之前打印的旧 origin 标签在新构建里判 foreign（它们的二维码本身也仍指向旧环境）。
    expect(codeSpace.classifyScannedCode('https://app.migaozn.com/i/ABCD2345').space).toBe('foreign')
  })

  it('O4 构建期接线：defineConstants 登记该键且缺省回落空串（issue #2693 白屏形态）', () => {
    const configSrc = fs.readFileSync(path.join(REPO_ROOT, 'config', 'index.ts'), 'utf8')

    expect(originDefineKeyProblems(configSrc)).toEqual([])

    // 注入式红证 A：把键改名 ⇒ 同一个判定函数**必须**报问题（否则 O4 是空断言）
    const renamed = configSrc.replace(
      "'process.env.TARO_APP_PUBLIC_APP_ORIGIN':",
      "'process.env.TARO_APP_UNRELATED_KEY':",
    )
    expect(renamed).not.toBe(configSrc) // 变异没落上 ⇒ 下面那条"红"就是假的（fail-closed）
    expect(originDefineKeyProblems(renamed)).toHaveLength(1)

    // 注入式红证 B：把缺省回落改成写死另一个域名 ⇒ 同样必须报（缺省真值不许搬到 config 里）
    const hardcodedFallback = configSrc.replace(
      'process.env.TARO_APP_PUBLIC_APP_ORIGIN || \'\'',
      "process.env.TARO_APP_PUBLIC_APP_ORIGIN || 'https://app.cytda.com'",
    )
    expect(hardcodedFallback).not.toBe(configSrc)
    expect(originDefineKeyProblems(hardcodedFallback)).toHaveLength(1)
  })
})
