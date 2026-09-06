/**
 * 测试环境全局 setup
 *
 * 在测试框架安装之前运行（setupFiles）
 * 注意：此处不可使用 beforeEach/describe 等 Jest 全局 API
 */

// 全局 TextEncoder/TextDecoder (jsdom 环境可能缺失)
if (typeof globalThis.TextEncoder === 'undefined') {
  const { TextEncoder, TextDecoder } = require('util')
  globalThis.TextEncoder = TextEncoder
  globalThis.TextDecoder = TextDecoder
}
