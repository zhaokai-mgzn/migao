// case_ids: AU-001, BM-002
/**
 * 退场元守卫：B 端员工登录**不得**回到「微信授权手机号 + openid 免密」那条路（issue #5485）
 *
 * ## 为什么需要这一层
 *
 * `POST /api/auth/bmini/login` 已废弃（调用会拿到明确拒绝 + 引导文案，不是 404），
 * 员工登录统一为「用户名@企业编码 + 密码」。但旧链路的关键字面量散落在
 * `utils/auth.ts` / 登录页 / store 三处 —— **只改一处**、或日后有人「顺手加回手机号一键登录」，
 * 单元测试仍会全绿，而产品行为已经退回旧口径（这就是「修一个实例 ≠ 修这一类」）。
 * 本守卫把这条路的**关键字面量**变成会红的判据。
 *
 * ## 判据（扫 `src/**` 全部 .ts/.tsx，非抽样、非白名单）
 *
 * | 字面量 | 射程 | 理由 |
 * |---|---|---|
 * | `/api/auth/bmini/login` | 整个 `src/**` | 废弃端点；再次出现＝旧入口复活 |
 * | `phoneCode` | 整个 `src/**` | 微信手机号授权动态令牌，只为旧链路存在 |
 * | `getPhoneNumber` | 仅 `src/pages/auth/login/**` | 登录页的授权按钮/回调 |
 *
 * **射程为何只到登录页**：`src/services/userService.ts` 的 C 端手机号绑定
 * （`POST /api/auth/mini/bind-phone`）是**另一条链路**，不在本单射程内（如实登记，不假装全覆盖）。
 *
 * **判据只盯代码、不盯注释**（`stripComments`）：注释里写清「这条路径已退场、端点已废弃」是
 * 应有的文档，而本仓已有同类教训 —— 文本匹配型判据会被自己的文案喂红（把禁忌形态写进注释也判红），
 * 那种红是**假红**；去掉注释后，真正复活旧链路（字符串/属性/标识符）照样必红。
 *
 * 语料非空 + 含登录页两项前置断言保证本判据**不会空跑**（路径写错 ⇒ 红，而不是静默通过）。
 * 判据自身（本文件在 `tests/` 下）不在语料内，故模式字面量不会自我命中。
 */
import * as fs from 'fs'
import * as path from 'path'

const SRC_DIR = path.resolve(__dirname, '../src')

/** 去掉注释后的代码文本（判据只判代码，不判解释性文案） */
function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '') // 块注释 / JSDoc / JSX 注释
    .replace(/(^|[^:])\/\/.*$/gm, '$1') // 行注释（`[^:]` 避开 http:// 这类 URL）
}

/** `src/**` 下全部 .ts/.tsx 的相对路径（POSIX 分隔符） */
function sourceFiles(): string[] {
  const walk = (dir: string): string[] =>
    fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) return walk(full)
      return /\.tsx?$/.test(entry.name) ? [full] : []
    })

  return walk(SRC_DIR).map((f) => path.relative(SRC_DIR, f).split(path.sep).join('/'))
}

/** 代码里命中 `pattern` 的文件（可选：只查某个相对目录前缀内） */
function hits(pattern: RegExp, scopePrefix = ''): string[] {
  return sourceFiles()
    .filter((rel) => rel.startsWith(scopePrefix))
    .filter((rel) => pattern.test(stripComments(fs.readFileSync(path.join(SRC_DIR, rel), 'utf8'))))
}

const CORPUS = sourceFiles()

describe('B 端员工登录退场守卫（issue #5485）', () => {
  it('语料非空且含登录页（判据不会空跑）', () => {
    // 实测语料 = src/** 全部 .ts/.tsx（当前 70+ 个）；阈值只用于"路径写错就红"
    expect(CORPUS.length).toBeGreaterThan(20)
    expect(CORPUS).toContain('pages/auth/login/index.tsx')
  })

  it('全包不得引用废弃端点 /api/auth/bmini/login', () => {
    expect(hits(/\/api\/auth\/bmini\/login/)).toEqual([])
  })

  it('全包不得残留 phoneCode（微信手机号授权令牌入参）', () => {
    expect(hits(/phoneCode/)).toEqual([])
  })

  it('登录页不得出现 getPhoneNumber 授权（按钮/回调）', () => {
    expect(hits(/getPhoneNumber/, 'pages/auth/login/')).toEqual([])
  })
})