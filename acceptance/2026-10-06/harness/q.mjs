// 通用只读 SQL 探针：node q.mjs "<SQL>" [--write]
// 只读为主；--write 用于清理（写面只碰本轮探针对象）。
import { psql, psqlWrite } from './lib.mjs'

const sql = process.argv[2]
if (!sql) {
  console.error('用法: node q.mjs "<SQL>" [--write]')
  process.exit(2)
}
if (process.argv.includes('--write')) {
  const out = psqlWrite(sql)
  if (out) process.stdout.write(out)
  console.log('(write done)')
} else {
  const rows = psql(sql)
  if (!rows.length) {
    console.log('(0 行)')
  } else {
    console.log(Object.keys(rows[0]).join('\t'))
    for (const r of rows) {
      console.log(Object.values(r).map((v) => (v === null ? 'NULL' : String(v))).join('\t'))
    }
  }
}
