// case_ids: BM-006
/**
 * 加工单二维码解析 + 深链参数解析（issue #3997 M4-G-3 / issue #4206）
 *
 * 真值源：docs/curtain-production-rules.md §5「打印加工单（含二维码）→ 工人扫码」。
 * 二维码内容由后端生成（M4-G-2 冻结契约），前端只负责**容错**取回 order_id：
 * 三种合法形态 + 非法输入一律返回 null（防呆：扫到别的二维码不能瞎猜单号去请求）。
 *
 * issue #4206 追加：`resolveOrderIdFromParams`（启动/跳转参数 → order_id），
 * 让「携带加工单号的跳转直达报工页」成立；同样**只认能解析出合法单号的参数**。
 */
import { parseOrderIdFromQr, resolveOrderIdFromParams } from '../src/utils/productionQr'

describe('parseOrderIdFromQr', () => {
  it('形态 1：裸 order_id 原样返回', () => {
    expect(parseOrderIdFromQr('CSO260915-02615')).toBe('CSO260915-02615')
    expect(parseOrderIdFromQr('  CSO260915-02615  ')).toBe('CSO260915-02615')
  })

  it('形态 2：migao://production/<order_id> 取出 order_id（带 token query 同样成立）', () => {
    expect(parseOrderIdFromQr('migao://production/CSO260915-02615')).toBe('CSO260915-02615')
    expect(parseOrderIdFromQr('migao://production/CSO260915-02615?token=abc123')).toBe(
      'CSO260915-02615',
    )
  })

  it('形态 3：带 query 的 URL 取出 order_id', () => {
    expect(parseOrderIdFromQr('CSO260915-02615?token=abc123')).toBe('CSO260915-02615')
    expect(
      parseOrderIdFromQr('https://m.migaozn.com/production/CSO260915-02615?token=abc123'),
    ).toBe('CSO260915-02615')
  })

  it('非法输入返回 null（不猜单号）', () => {
    expect(parseOrderIdFromQr('')).toBeNull()
    expect(parseOrderIdFromQr('   ')).toBeNull()
    expect(parseOrderIdFromQr('这不是加工单二维码')).toBeNull()
    expect(parseOrderIdFromQr('hello world')).toBeNull()
    expect(parseOrderIdFromQr('ab')).toBeNull()
    expect(parseOrderIdFromQr('migao://production/')).toBeNull()
    // 非 production 域的其他码（如订单码）不是加工单码
    expect(parseOrderIdFromQr('migao://order/CSO260915-02615')).toBeNull()
  })
})

/**
 * issue #4206 判据 4：跳转/启动参数 → order_id。
 *
 * 二维码本体是后端下发的裸 `qr_token`（32 位，非 URL、非 scheme）⇒ 微信原生扫码进不来
 * （需后端调微信接口，另单）。小程序内可做的部分 = **带参跳转直达报工页**：
 * `Taro.navigateTo({url: '/pages/production/index/index?order_id=…'})` 或 `?qr=…`
 * （后端 `resolveOrder` 三形态：order_id / order_no / qr_token）。
 */
describe('resolveOrderIdFromParams（深链直达）', () => {
  /**
   * 32 位 `qr_token` 形态的**假值**（后端真实 token 就是这种长度/字符集）。
   * ⚠️ 必须用低熵字面量：高熵十六进制（如 `a1b2c3…`）会被 CI 的 gitleaks
   * `generic-api-key` 规则当成密钥误报（实测：本文件 line 64 曾因此把 Secret Scan 打红，
   * Entropy 4.0 —— 而它只是测试夹具，不是凭据）。
   */
  const QR_TOKEN_FIXTURE = 'qrcodetoken0000000000000000000000'

  it('order_id / orderId 参数取出单号', () => {
    expect(resolveOrderIdFromParams({ order_id: 'CSO260915-02615' })).toBe('CSO260915-02615')
    expect(resolveOrderIdFromParams({ orderId: 'CSO260915-02615' })).toBe('CSO260915-02615')
  })

  it('qr / token 参数按二维码原串解析（含 migao:// 与 URL 形态）', () => {
    expect(resolveOrderIdFromParams({ qr: 'migao://production/CSO260915-02615?token=abc' })).toBe(
      'CSO260915-02615',
    )
    expect(resolveOrderIdFromParams({ token: QR_TOKEN_FIXTURE })).toBe(QR_TOKEN_FIXTURE)
  })

  it('无参数 / 空参数 / 非法参数一律 null（不瞎猜单号去请求）', () => {
    expect(resolveOrderIdFromParams(undefined)).toBeNull()
    expect(resolveOrderIdFromParams(null)).toBeNull()
    expect(resolveOrderIdFromParams({})).toBeNull()
    expect(resolveOrderIdFromParams({ order_id: '' })).toBeNull()
    expect(resolveOrderIdFromParams({ order_id: '这不是单号' })).toBeNull()
  })
})
