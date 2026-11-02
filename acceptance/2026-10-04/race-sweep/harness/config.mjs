// 线③ 并发竞态 —— 钉死的环境口径（BRIEF §1/§4.3）
export const T_A = Number(process.env.TENANT_ID || 25)          // 米高测试环境（本线命名空间：race-sweep-A）
export const PHONE_A = process.env.ADMIN_PHONE || '13800138000'
export const T_B_NAME = '米高测试环境-隔离对照'
export const PHONE_B = '13800138001'
export const REGISTER_INDUSTRY = '布艺纺织'
export const SMS_CODE = process.env.SMS_CODE || '123456'
export const API = process.env.API_BASE || 'https://api.migaozn.com'
export const PROBE = 'race-sweep'        // 探针前缀：所有自建对象名/货号/单号都带它
export const FIX = new URL('./fixtures.json', import.meta.url).pathname
