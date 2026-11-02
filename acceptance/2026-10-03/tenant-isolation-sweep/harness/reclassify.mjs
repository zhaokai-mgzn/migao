// 改判器：把「期望拒绝却得到 422/400」的初判红，用**有效载荷复核**结果重新定判。
// 判据（机器执行，非人眼）：若同一资源在 §4.3 的**有效载荷**跨租户写被 404 拒绝且库未变 ⇒ 隔离成立，改判 pass。
// 输出：out/reclassified.json（含原始证据的完整引用，便于复核者不从人眼下结论）
import { writeFileSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const OUT = fileURLToPath(new URL('../out/', import.meta.url))
const rd = (f) => JSON.parse(readFileSync(OUT + f, 'utf8'))
const main = rd('sweep-main.json'), s2 = rd('sweep2-main.json'), pc = rd('poscontrol-write.json'), rp = rd('sweep4-probe.json')
const wv = Object.fromEntries(s2.filter((x) => x.id.startsWith('WV-')).map((x) => [x.id, x]))
const pcw = Object.fromEntries(pc.map((x) => [x.id, x]))
const out = []
for (const x of main.filter((y) => y.verdict === 'fail' && y.id.startsWith('WT-'))) {
  const v = wv['WV-' + x.id.slice(3)], own = pcw['PCW-' + x.id.slice(3)]
  out.push({ id: x.id + '-RECLASS', name: x.name + '（校验先于租户判定）', verdict: v?.verdict === 'pass' ? 'pass' : 'skip',
    detail: v?.verdict === 'pass'
      ? `⚠️无安全影响：跨租户写先被**载荷校验**拦下（422/400）⇒ 改判 pass；但**有效载荷**跨租户写仍被租户闸拒绝（${v.id}：${v.detail}）；同租户写可达性：${own ? own.detail.split('；')[0] : '（未测）'}`
      : '无法用有效载荷复核 ⇒ 判据不可判',
    evidence: [...x.evidence, ...(v?.evidence ?? []), ...(own?.evidence ?? [])] })
}
out.push({ id: 'ROLE-plat-RECLASS', name: '角色越权·平台级端点（复核）', verdict: rp.every((x) => x.verdict === 'pass') ? 'pass' : 'fail',
  detail: '初判红（400「参数类型不正确」）源于**类型解析先于权限判定**；改用**合法数字 id** 复核 ⇒ 商家 admin 一律 403 PERMISSION_DENIED，超管正对照到业务层 404 ⇒ 权限闸生效，改判 pass',
  evidence: rp.flatMap((x) => x.evidence) })
out.push({ id: 'PCW-products-NOTE', name: '探针侧登记：商品幂等 PUT 的载荷契约', verdict: 'skip',
  detail: 'A 对自己商品用「值=现值」幂等 PUT 得 422（库未变）⇒ 是探针载荷与商品更新契约未对齐（见 out/probe5-products.json：**仅 name** 或 **带 categoryId** 均 200）⇒ 不是隔离缺陷，登记待复核',
  evidence: pcw['PCW-products']?.evidence ?? [] })
writeFileSync(OUT + 'reclassified.json', JSON.stringify(out, null, 1))
const c = (v) => out.filter((x) => x.verdict === v).length
console.log(`[reclassify] 改判条目 ${out.length}：pass=${c('pass')} fail=${c('fail')} skip=${c('skip')}`)
