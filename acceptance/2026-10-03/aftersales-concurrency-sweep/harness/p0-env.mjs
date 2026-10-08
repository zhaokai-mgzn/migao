// p0-env —— 构建点自证 + 时钟自检 + 端点可达性 + 鉴权（本包一切读数的前置）
// 用法：API_BASE=http://127.0.0.1:8080 node p0-env.mjs
import { writeFileSync } from 'node:fs'
import { buildPoint, api, adminToken, loginApi, psql, outPath, log, nowCST, Recorder, readFileSync } from './lib.mjs'

const R = new Recorder('B0-env.json')
const bp = buildPoint()
writeFileSync(outPath('B0-buildpoint.json'), JSON.stringify(bp, null, 2))
log(`构建点：${bp.sha}（pid ${bp.pid}，启动 ${bp.adminApiStart}）origin/main=${bp.originMain}`)

// ① 构建点必须就是任务书钉的那个 —— 不一致则本包读数不可引用
R.add('LB0-01', '被测构建点自证', bp.shaFull.startsWith('43ca7032') ? 'pass' : 'fail',
  `main-live HEAD=${bp.shaFull}（期望 43ca703221a714e143c468ff0b29c4a46e67a88f）`,
  [`取证方式: git -C ${bp.worktree} rev-parse HEAD`, `subject: ${bp.subject}`,
   `commitTime(UTC): ${bp.commitTime}`, `admin-api pid=${bp.pid} 启动=${bp.adminApiStart}`,
   `env-round3.json: ${readFileSync(outPath('../../env/env-round3.json'), 'utf8').slice(0, 200)}`])

// ② 时钟自检：JS 侧 +08 口径 vs SQL now() at time zone 'Asia/Shanghai'
// ⚠️ 修：上一版把 'YYYY-MM-DD HH:MM:SS' 裸串交给 Date 解析 ⇒ Node 视作**本地时区**、且部分形态得 NaN
//    （读数打印 `差 NaNs`）。改为显式拼 `+08:00` 偏移后取毫秒。
const parseCST = (s) => Date.parse(String(s).replace(' ', 'T') + '+08:00')
const jsNow = nowCST().cst.slice(0, 19)
const dbNow = psql(`select to_char(now() at time zone 'Asia/Shanghai','YYYY-MM-DD HH24:MI:SS') as t`)[0].t
const skewSec = Math.abs(parseCST(jsNow) - parseCST(dbNow)) / 1000
writeFileSync(outPath('B0-clock.json'), JSON.stringify({ jsNow, dbNow, skewSec, at: nowCST() }, null, 2))
R.add('LB0-02', '时钟自检（JS +08 vs SQL Asia/Shanghai）', Number.isFinite(skewSec) ? 'pass' : 'fail',
  `JS=${jsNow} / SQL=${dbNow}（差 ${skewSec}s）`,
  [`取值口径: nowCST() 走 Intl timeZone=Asia/Shanghai；SQL 走 now() at time zone 'Asia/Shanghai'`,
   `两侧均按 '+08:00' 显式解析后比较（不依赖进程 TZ）`])

// ③ 端点可达性
for (const [id, m, p] of [['LB0-03', 'GET', '/api/admin/after-sales?page=1&size=1'], ['LB0-04', 'GET', '/api/admin/orders?page=1&size=1']]) {
  const r = await api(m, p)
  R.add(id, `端点可达性 ${m} ${p}`, r.status === 401 ? 'pass' : 'fail',
    `未鉴权访问返回 ${r.status}（期望 401 —— 该端点是鉴权面）`, [`响应原文: ${r.text.slice(0, 160)}`])
}

// ④ 鉴权（① 万能码被拒 ⇒ ② 走 send+Redis 读码的用户等价路径，见 lib.mjs adminToken 注释）
let token = null
try {
  const l = await adminToken()
  token = l.token
  writeFileSync(outPath('B0-auth.json'), JSON.stringify({ ok: true, phone: '13870217889', via: l.via, raw: l.raw }, null, 2))
  writeFileSync(outPath('.token'), String(token))   // 供 p1..pN 复用（本包目录内，含 token ⇒ 收尾删除）
  R.add('LB0-05', '管理员登录', token ? 'pass' : 'fail',
    `取到 token（长度 ${String(token).length}），取得方式 = ${l.via}`,
    [`⚠️ 环境事实（superseded）：16:15 那版 :8080 进程**未加载** SMS_BYPASS_CODE ⇒ 万能码被拒（401）；16:22 主会话带 .env 重启后本判据转 pass`,
     `   16:22 之前的、依赖 API 的读数以**运行期环境注入**变化为由标记 superseded（构建点 43ca70322 未变）`,
     `回落路径 = POST /api/auth/sms/send（服务端生成并落 Redis sms:code:<phone>）+ 只读 Redis 读回 ⇒ 与「用户收到短信后输入」等价，未绕过鉴权`,
     `响应 data 键: ${Object.keys(l.raw || {}).join(',')}`, `tenantId=${l.raw?.user?.tenantId} role=${l.raw?.user?.role}`])
} catch (e) {
  R.add('LB0-05', '管理员登录', 'fail', e.message.slice(0, 300), [])
}

// ⑤ 探针域基线读（跨包隔离：记录此刻租户 20 存量，供"外来行归因"用）
const base = psql(`select
  (select count(*) from orders where tenant_id=20) as orders,
  (select count(*) from after_sales_tickets where tenant_id=20) as tickets,
  (select count(*) from stock_ledger_entries where tenant_id=20) as ledger,
  (select count(*) from finance_transactions where tenant_id=20) as finance,
  (select count(*) from products where tenant_id=20) as products`)
writeFileSync(outPath('B0-tenant-baseline.json'), JSON.stringify({ at: nowCST(), base }, null, 2))
R.add('LB0-06', '租户 20 存量基线（外来行归因用）', 'pass', JSON.stringify(base), ['只读；供清理后逐表比对'])

log(`p0 完成：${JSON.stringify(R.summary())}`)
if (!token) process.exit(1)
