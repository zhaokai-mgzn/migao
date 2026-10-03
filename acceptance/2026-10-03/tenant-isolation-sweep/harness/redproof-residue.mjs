// 红证：证明「零残留/零写入」读数**不是空断言** —— 对 B(21) 的一行做一次**可逆**改动，
// 要求 ① 指纹检出差 ② 还原后指纹回到基线。全程记录逐字读数。
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { psql, psqlWrite, log } from '../../config-writeface-sweep/harness/lib.mjs'
const OUT = fileURLToPath(new URL('../out/', import.meta.url))
const fp = (id) => psql(`select count(*)::int n, max(updated_at)::text m,
    md5(coalesce(string_agg(left(t::text,320),';' order by id::text),'')) rowfp
  from (select *, coalesce(deleted,0) as _d from products where tenant_id=21) t`)[0]
const one = psql(`select id::text as id, name from products where tenant_id=21 and coalesce(deleted,0)=0 limit 1`)[0]
const ev = []
const recs = []
const rec = (id, name, verdict, detail, evidence) => { recs.push({ id, name, verdict, detail, evidence }); log(`${verdict === 'pass' ? '✅' : '❌'} [${id}] ${name} — ${detail}`) }

const before = fp(one.id)
ev.push(`基线：products#21 行数=${before.n} max_updated=${before.m} rowfp=${before.rowfp}`)
log(ev[0])
// 注入：改名字（可逆）
psqlWrite(`update products set name='验收红证临时值' where id='${one.id}'`)
const injected = fp(one.id)
ev.push(`注入后：行数=${injected.n} max_updated=${injected.m} rowfp=${injected.rowfp}（rowfp 变=${injected.rowfp !== before.rowfp}）`)
log(ev[1])
rec('RP-RESIDUE-DETECT', '残留读数红证·注入检出', injected.rowfp !== before.rowfp ? 'pass' : 'fail',
  injected.rowfp !== before.rowfp ? '注入一次行内容改动后，指纹**确实变了** ⇒ 该读数不是空断言' : '🔴 注入后指纹未变 ⇒ 零写入读数是空断言！', ev.slice())
// 还原
psqlWrite(`update products set name='${String(one.name).replace(/'/g, "''")}' where id='${one.id}'`)
const restored = fp(one.id)
ev.push(`还原后：行数=${restored.n} max_updated=${restored.m} rowfp=${restored.rowfp}（回到基线=${restored.rowfp === before.rowfp}）；name 现值=${psql(`select name from products where id='${one.id}'`)[0].name}`)
log(ev[2])
rec('RP-RESIDUE-RESTORE', '残留读数红证·还原', restored.rowfp === before.rowfp ? 'pass' : 'fail',
  restored.rowfp === before.rowfp ? '还原后指纹逐字节回到基线（name 已复原）' : '🔴 还原未回到基线', ev.slice())
writeFileSync(OUT + 'redproof-residue.json', JSON.stringify(recs, null, 1))
