import { readXlsx, readFileSync, makeXlsx, fmtQty } from './lib.mjs'
const x = readXlsx(readFileSync('/tmp/l2export.xlsx'))
console.log('parts=', x.parts.join(','))
console.log('headers=', JSON.stringify(x.headers))
console.log('rows=', x.rows.length)
console.log('row0=', JSON.stringify(x.rows[0]))
// 自写 xlsx 回读（红证：读器不空转）
const mine = makeXlsx(['a','b'],[['x',1],['y',2.5]])
const m = readXlsx(mine)
console.log('selfwrite headers=', JSON.stringify(m.headers), 'rows=', JSON.stringify(m.rows))
