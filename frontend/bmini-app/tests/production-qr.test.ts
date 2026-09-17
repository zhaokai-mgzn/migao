// case_ids: BM-006
/**
 * 加工单二维码解析（issue #3997，M4-G-3）
 *
 * 真值源：docs/curtain-production-rules.md §5「打印加工单（含二维码）→ 工人扫码」。
 * 二维码内容由后端生成（M4-G-2 冻结契约），前端只负责**容错**取回 order_id：
 * 三种合法形态 + 非法输入一律返回 null（防呆：扫到别的二维码不能瞎猜单号去请求）。
 */
import { parseOrderIdFromQr } from '../src/utils/productionQr'

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
