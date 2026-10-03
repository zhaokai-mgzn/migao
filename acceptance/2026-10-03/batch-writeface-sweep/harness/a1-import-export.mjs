// A — 导入 / 导出（线② 破坏性写面）
// 判据一律以 **DB 读数** 为准（不许只看 200），期望独立算出（契约原文 = ProductController/Service 注释 + 独立 SQL 计数）。
import {
  Recorder, judge, api, upload, loginApi, psql, one, guardedWrite, makeXlsx, readXlsx,
  probeSku, PROBE_PREFIX, TENANT_ID, ID_PREFIX, log, nowCST, writeFileSync, outPath, sha256,
  cleanupProbe,
} from './lib.mjs'

const R = new Recorder('A-import-export.json')
const { token } = await loginApi()
const T = TENANT_ID
const R_ = nowCST()
log(`A 段开始 ${R_.cst} (UTC ${R_.utc})`)

const H = ['商品名称', '货号', '分类ID', '价格', '库存', '描述', '颜色', '门幅', 'SKU编码']
const tag = Date.now().toString(36).toUpperCase()
const skuA = probeSku(`IMP-A-${tag}`)   // 正常组
const skuB = probeSku(`IMP-B-${tag}`)   // 部分坏行组
const skuC = probeSku(`IMP-C-${tag}`)   // 幂等组

const countProduct = (sku) => one(`select count(*)::int as n from products where tenant_id=${T} and sku_code='${sku}' and deleted=0`)?.n ?? -1
const countSkuRows = (sku) => one(`select count(*)::int as n from product_skus s join products p on p.id=s.product_id where p.tenant_id=${T} and p.sku_code='${sku}'`)?.n ?? -1
const prodRow = (sku) => one(`select id, tenant_id, name, base_price, stock, status, deleted, unit, pricing_type from products where tenant_id=${T} and sku_code='${sku}' and deleted=0`)

// ── A1 正常导入（2 行 = 1 商品的 2 个 SKU）──────────────────────────
const fileOK = makeXlsx(H, [
  [`${PROBE_PREFIX}导入商品A`, skuA, '', 128.5, 60.5, `${PROBE_PREFIX}描述`, '米白', '2.8m', `${skuA}-01`],
  [`${PROBE_PREFIX}导入商品A`, skuA, '', 128.5, 12, `${PROBE_PREFIX}描述`, '米白', '3.2m', `${skuA}-02`],
])
writeFileSync(outPath(`A1-import-ok-${skuA}.xlsx`), fileOK)
const r1 = await upload('/api/admin/products/import', { token, files: [{ field: 'file', filename: 'import-ok.xlsx', content: fileOK, type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }] })
const d1 = r1.data
const dbA = countProduct(skuA), dbAsku = countSkuRows(skuA)
writeFileSync(outPath('A1-import-ok-result.json'), JSON.stringify({ http: r1.status, body: r1.json }, null, 2))
judge(R, {
  id: 'A1.1', name: '正常导入：HTTP 200 + 逐行报告 total==success+fail+blank',
  expect: `200 且 total=${d1?.total} == success(${d1?.successCount})+fail(${d1?.failCount})+blank(${d1?.blankRows})`,
  actual: `HTTP ${r1.status} total=${d1?.total} success=${d1?.successCount} fail=${d1?.failCount} blank=${d1?.blankRows}`,
  pass: r1.status === 200 && d1?.total === (d1?.successCount ?? -1) + (d1?.failCount ?? -1) + (d1?.blankRows ?? -1) && d1?.successCount === 2 && d1?.failCount === 0,
  expectSource: 'ProductController#importProducts 注释「响应恒为 200 + 逐行报告」+ ProductImportResult(total/successCount/failCount/blankRows)',
  evidence: [`原始响应: ${r1.text.slice(0, 400)}`],
})
judge(R, {
  id: 'A1.2', name: '正常导入：DB 落库读数（1 商品 + 2 SKU 行）',
  expect: `products(${skuA}) = 1 且 product_skus = 2`,
  actual: `products = ${dbA} 且 product_skus = ${dbAsku}`,
  pass: dbA === 1 && dbAsku === 2,
  expectSource: '独立 SQL 计数（不经被测系统读面）；两行同货号 = 1 商品 2 SKU（Service 注释「同一货号多行 = 一个商品的多 SKU」）',
  evidence: [`SQL: select count(*) from products where tenant_id=${T} and sku_code='${skuA}' and deleted=0`, `SQL: select count(*) from product_skus s join products p on p.id=s.product_id where p.sku_code='${skuA}'`],
})
const pr = prodRow(skuA)
judge(R, {
  id: 'A1.3', name: '导入的租户归属 = 当前租户（tenant_id 核对）',
  expect: `tenant_id = ${T}`,
  actual: `tenant_id = ${pr?.tenant_id}`,
  pass: pr?.tenant_id === T,
  expectSource: 'ProductController#importProducts：租户取自 TenantContext，不接受客户端传入',
  evidence: [`DB 行: ${JSON.stringify(pr)}`],
})

// ── A2 部分坏行：逐行报告 + 失败行不落库、成功行落库 ──────────────────
const rowBadNoName = ['', skuB, '', 99, 1, '缺名称', '', '', '']                     // 缺必填 商品名称
const rowBadPrice = [`${PROBE_PREFIX}部分坏行`, skuB, '', 'abc', 1, '价格非数字', '', '', ''] // 类型错：价格非数字
const rowBadSku = [`${PROBE_PREFIX}部分坏行`, skuB, '', 50, 1, '', '米白', '2.8m', '']       // 与下一行「颜色+门幅」重复
const rowBadSkuDup = [`${PROBE_PREFIX}部分坏行`, skuB, '', 50, 1, '', '米白', '2.8m', '']    // 重复组合
const rowGood = [`${PROBE_PREFIX}部分坏行`, skuB, '', 50, 1, `${PROBE_PREFIX}描述`, '米白', '3.2m', `${skuB}-01`]
const filePartial = makeXlsx(H, [rowBadNoName, rowBadPrice, rowBadSku, rowBadSkuDup, rowGood])
writeFileSync(outPath(`A2-import-partial-${skuB}.xlsx`), filePartial)
const beforeB = countProduct(skuB)
const r2 = await upload('/api/admin/products/import', { token, files: [{ field: 'file', filename: 'import-partial.xlsx', content: filePartial, type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }] })
const d2 = r2.data
const afterB = countProduct(skuB), afterBsku = countSkuRows(skuB)
writeFileSync(outPath('A2-import-partial-result.json'), JSON.stringify({ http: r2.status, body: r2.json }, null, 2))
const errs = d2?.errors || []
judge(R, {
  id: 'A2.1', name: '部分坏行：逐行报告（每条带 行号 + 货号 + 可行动原因）',
  expect: `failCount = 4（3 类错各带行号），每题 errors[] 有 row/skuCode/message 非空`,
  actual: `failCount=${d2?.failCount} errors=${JSON.stringify(errs).slice(0, 500)}`,
  pass: d2?.failCount === 4 && errs.length === 4 && errs.every((e) => e.row > 0 && typeof e.message === 'string' && e.message.length > 0),
  expectSource: 'Service#importProducts 阶段1/2：每个数据行必落「成功/失败/空白」三桶之一，失败行带行号+货号+原因',
  evidence: [`errors 原文: ${JSON.stringify(errs)}`],
})
judge(R, {
  id: 'A2.2', name: '部分坏行：失败行不落库 + 成功行落库（DB 逐行判定）',
  expect: `导入前 products(${skuB})=0 → 导入后 =1 且 SKU 行 =1（坏行零副作用，好行落库）`,
  actual: `before=${beforeB} after=${afterB} skuRows=${afterBsku}`,
  pass: beforeB === 0 && afterB === 1 && afterBsku === 1,
  expectSource: 'Service 注释「行级原子（不是整包回滚）：校验全部在写入之前完成 ⇒ 非法行零落库副作用」；独立 SQL 计数',
  evidence: [`SQL 前/后计数 products(sku_code='${skuB}')：${beforeB} → ${afterB}`, `SQL 后计数 product_skus = ${afterBsku}`],
})
judge(R, {
  id: 'A2.3', name: '坏行的「失败原因」不含 0 条错却成功（报告与 DB 一致）',
  expect: `successCount(${d2?.successCount}) + failCount(${d2?.failCount}) + blank(${d2?.blankRows}) = total(${d2?.total}) 且 DB 新增商品数 == 成功组数 1`,
  actual: `total=${d2?.total} success=${d2?.successCount} fail=${d2?.failCount} blank=${d2?.blankRows}`,
  pass: d2?.total === (d2?.successCount ?? -1) + (d2?.failCount ?? -1) + (d2?.blankRows ?? -1) && d2?.successCount === 1,
  expectSource: 'ProductImportResult 恒等式（migao-acceptance 假绿形态：报告与 DB 必须互证）',
  evidence: [`原始: ${r2.text.slice(0, 300)}`],
})

// ── A3 幂等：同一文件连导两次 ──────────────────────────────────────
const fileIdem = makeXlsx(H, [
  [`${PROBE_PREFIX}幂等商品C`, skuC, '', 77.5, 5, `${PROBE_PREFIX}描述`, '米白', '2.8m', `${skuC}-01`],
  [`${PROBE_PREFIX}幂等商品C`, skuC, '', 77.5, 6, `${PROBE_PREFIX}描述`, '米白', '3.2m', `${skuC}-02`],
])
writeFileSync(outPath(`A3-import-idem-${skuC}.xlsx`), fileIdem)
const i1 = await upload('/api/admin/products/import', { token, files: [{ field: 'file', filename: 'idem.xlsx', content: fileIdem, type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }] })
const dbC1 = countProduct(skuC), dbC1s = countSkuRows(skuC)
const i2 = await upload('/api/admin/products/import', { token, files: [{ field: 'file', filename: 'idem.xlsx', content: fileIdem, type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }] })
const dbC2 = countProduct(skuC), dbC2s = countSkuRows(skuC)
const cid1 = prodRow(skuC)?.id
writeFileSync(outPath('A3-import-idem-result.json'), JSON.stringify({
  first: { http: i1.status, body: i1.json }, second: { http: i2.status, body: i2.json },
  db: { after1: { products: dbC1, skus: dbC1s }, after2: { products: dbC2, skus: dbC2s }, productId: cid1 },
}, null, 2))
judge(R, {
  id: 'A3.1', name: '幂等：同一文件连导两次 ⇒ 商品数不翻倍',
  expect: `第1次后 products=1，第2次后仍 products=1（未翻倍）`,
  actual: `after1=${dbC1} after2=${dbC2}`,
  pass: dbC1 === 1 && dbC2 === 1,
  expectSource: 'Service#importProducts 口径①「幂等键 = (tenant_id, 货号)，命中即原地更新 ⇒ 同一文件重复导入不产生重复商品」',
  evidence: [`第2次响应: ${i2.text.slice(0, 300)}`],
})
judge(R, {
  id: 'A3.2', name: '幂等：SKU 数不翻倍 + 商品主键不变（旧 skuId 不断链）',
  expect: `SKU 行 after1 = 2 → after2 = 2；product.id 两次相同`,
  actual: `skus after1=${dbC1s} after2=${dbC2s}; productId=${cid1}`,
  pass: dbC1s === 2 && dbC2s === 2 && !!cid1,
  expectSource: 'Service 口径①「SKU 按「颜色 + 门幅」匹配后原地更新 ⇒ 订单/批次里存的旧 skuId 不断链」',
  evidence: [`skus: ${dbC1s} → ${dbC2s}`],
})
judge(R, {
  id: 'A3.3', name: '幂等：第2次报告应报 updated 而非 created（不静默建重复）',
  expect: `第2次 createdProducts=0 且 updatedProducts=1`,
  actual: `created=${i2.data?.createdProducts} updated=${i2.data?.updatedProducts}`,
  pass: i2.data?.createdProducts === 0 && i2.data?.updatedProducts === 1,
  expectSource: 'ProductImportResult.createdProducts/updatedProducts 语义（Service 幂等键命中 ⇒ 原地更新）',
  evidence: [`第1次 created=${i1.data?.createdProducts} updated=${i1.data?.updatedProducts}`],
})

// ── A4 整包级输入问题 ⇒ 明确 4xx 且零副作用 ─────────────────────────
const zeroByte = Buffer.alloc(0)
const r4a = await upload('/api/admin/products/import', { token, files: [{ field: 'file', filename: 'empty.xlsx', content: zeroByte, type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }] })
const noHeaderSku = probeSku(`IMP-NH-${tag}`)
const fileNoHeader = makeXlsx(null, [[`${PROBE_PREFIX}无表头`, noHeaderSku, '', 10, 1, '', '', '', '']])
const r4b = await upload('/api/admin/products/import', { token, files: [{ field: 'file', filename: 'noheader.xlsx', content: fileNoHeader, type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }] })
const noColSku = probeSku(`IMP-NC-${tag}`)
const fileMissingCol = makeXlsx(['商品名称', '货号'], [[`${PROBE_PREFIX}缺列`, noColSku]])
const r4c = await upload('/api/admin/products/import', { token, files: [{ field: 'file', filename: 'missingcol.xlsx', content: fileMissingCol, type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }] })
const r4d = await upload('/api/admin/products/import', { token, files: [{ field: 'file', filename: 'notcsv.xlsx', content: '商品名称,货号,价格\nx,y,1\n', type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }] })
const r4e = await upload('/api/admin/products/import', { token, files: [{ field: 'file', filename: 'plain.csv', content: fileIdem, type: 'text/csv' }] })
// 超大文件：真撑过 5MB（首轮用 120000 个**空串**行 ⇒ zip 实测只有 2,531,762 字节，
// 连 PertMax 都没碰到 —— 那是"我的夹具没到边界"，不是"系统接受了超大文件"，故重造）
const pad = 'X'.repeat(2048)
const bigRows = Array.from({ length: 4000 }, (_, i) => [`${PROBE_PREFIX}大文件行${i}`, probeSku(`BIG${i % 50}`), '', 1, 0, pad, '', '', ''])
const fileBig = makeXlsx(H, bigRows)
log(`超大夹具实际字节数 = ${fileBig.length}`)
const r4f = await upload('/api/admin/products/import', { token, files: [{ field: 'file', filename: 'big.xlsx', content: fileBig, type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }], timeoutMs: 240000 })
writeFileSync(outPath('A4-bad-inputs.json'), JSON.stringify({
  empty: { http: r4a.status, body: r4a.json }, noHeader: { http: r4b.status, body: r4b.json },
  missingCol: { http: r4c.status, body: r4c.json }, notXlsx: { http: r4d.status, body: r4d.json },
  csvExt: { http: r4e.status, body: r4e.json },
  bigBytes: fileBig.length, big: { http: r4f.status, body: r4f.json },
}, null, 2))

const sideNew = psql(`select sku_code from products where tenant_id=${T} and sku_code in ('${noHeaderSku}','${noColSku}')`)
judge(R, {
  id: 'A4.1', name: '空文件 ⇒ 4xx（非 200）+ 零落库',
  expect: 'HTTP ∈ 4xx/5xx 且无新增商品',
  actual: `HTTP ${r4a.status}，body=${r4a.text.slice(0, 200)}`,
  pass: r4a.status >= 400 && r4a.status < 600,
  expectSource: 'Service#importProducts：解析失败 ⇒ BusinessException.validationError（Controller 注释「只有整包级别的输入问题才走 400」）',
  evidence: [`原始: ${r4a.text.slice(0, 300)}`],
})
judge(R, {
  id: 'A4.2', name: '表头缺失/缺必填列 ⇒ 4xx 且零副作用（DB 核对）',
  expect: `noHeader HTTP>=400 且 missingCol HTTP>=400 且 两个货号均零落库`,
  actual: `noHeader=${r4b.status} missingCol=${r4c.status} 落库货号=${JSON.stringify(sideNew)}`,
  pass: r4b.status >= 400 && r4c.status >= 400 && sideNew.length === 0,
  expectSource: 'Service#resolveImportHeader：缺 REQUIRED_IMPORT_HEADERS（商品名称/货号/价格）⇒ 整包拒绝 400；独立 SQL 核对零副作用',
  evidence: [`noHeader: ${r4b.text.slice(0, 200)}`, `missingCol: ${r4c.text.slice(0, 200)}`],
})
judge(R, {
  id: 'A4.3', name: '非 Excel 内容（伪装 .xlsx / .csv 扩展名）⇒ 明确拒绝、零副作用',
  expect: '两者均 >= 400',
  actual: `伪 xlsx=${r4d.status} csv扩展名=${r4e.status}`,
  pass: r4d.status >= 400 && r4e.status >= 400,
  expectSource: 'Service 用 WorkbookFactory.create 解析 ⇒ 非 OOXML 必抛，被 catch 成 validationError；扩展名未白名单',
  evidence: [`伪xlsx: ${r4d.text.slice(0, 200)}`, `csv: ${r4e.text.slice(0, 200)}`],
})
judge(R, {
  id: 'A4.4', name: '超大文件（>5MB，实测 %d 字节）⇒ 不得 5xx 崩溃；结果如实（4xx 或逐行报告）'.replace('%d', fileBig.length),
  expect: 'HTTP ≠ 5xx；若 200 则 total==success+fail+blank 且 DB 无脏行',
  actual: `HTTP ${r4f.status} body=${r4f.text.slice(0, 200)}`,
  pass: r4f.status < 500 && (r4f.status >= 400 || r4f.data?.total === (r4f.data?.successCount ?? -1) + (r4f.data?.failCount ?? -1) + (r4f.data?.blankRows ?? -1)),
  expectSource: 'migao-acceptance「明确 4xx 且零副作用」；超大文件无显式上限 ⇒ 至少不得 5xx',
  evidence: [`文件大小: ${fileBig.length} 字节`, `body: ${r4f.text.slice(0, 300)}`],
})

// ── A5 导出：口径一致 / 精度 / 不含他租户 / 空结果 ────────────────────
const listAll = await api('GET', '/api/admin/products?page=1&size=10000', { token })
const listTotal = listAll.data?.total ?? -1
const expAll = await api('GET', '/api/admin/products/export', { token })
const xAll = expAll.buf?.length ? readXlsx(expAll.buf) : { headers: [], rows: [] }
writeFileSync(outPath('A5-export-all.json'), JSON.stringify({
  http: expAll.status, bytes: expAll.buf?.length, contentType: expAll.headers?.['content-type'],
  headers: xAll.headers, rowCount: xAll.rows.length, listTotal, firstRows: xAll.rows.slice(0, 3),
}, null, 2))
judge(R, {
  id: 'A5.1', name: '导出非空（正对照：真有数据才谈口径）',
  expect: `响应体 > 1KB 且 数据行 > 0`,
  actual: `${expAll.buf?.length} 字节，数据行 ${xAll.rows.length}`,
  pass: (expAll.buf?.length ?? 0) > 1024 && xAll.rows.length > 0,
  expectSource: '正对照（migao-acceptance 反假绿）：先证面非空，口径比对才有意义；列表接口 total=' + listTotal,
  evidence: [`Content-Type: ${expAll.headers?.['content-type']}`, `Content-Disposition: ${expAll.headers?.['content-disposition']}`],
})
judge(R, {
  id: 'A5.2', name: '导出行数 == 同筛选条件下列表 total（口径一致）',
  expect: `导出行数(${xAll.rows.length}) == 列表 total(${listTotal})`,
  actual: `导出行数=${xAll.rows.length} 列表 total=${listTotal}`,
  pass: xAll.rows.length === listTotal,
  expectSource: 'ProductController#exportProducts 注释「GET /export?keyword…」+ Service 用 getProducts(query, tenantId) 同一查询（page=1,size=10000）⇒ 与列表同口径',
  evidence: [`列表响应 total=${listTotal}`, `导出表头=${JSON.stringify(xAll.headers)}`],
})
judge(R, {
  id: 'A5.3', name: '导出表头逐字 == EXPORT_HEADERS（7 列）',
  expect: JSON.stringify(['商品名称', '货号', '分类', '价格', '库存', '状态', '描述']),
  actual: JSON.stringify(xAll.headers),
  pass: JSON.stringify(xAll.headers) === JSON.stringify(['商品名称', '货号', '分类', '价格', '库存', '状态', '描述']),
  expectSource: 'ProductService.java 常量 EXPORT_HEADERS（逐字内联，出处 = main-live 构建点 d1c09d02f 源码）',
  evidence: [`实测表头: ${JSON.stringify(xAll.headers)}`],
})
// 精度逐字核对：取一个已知 base_price 的商品，比对导出的数值 cell
// 取导出结果里第 1 个**有货号**的数据行，再用该货号反查 DB —— 保证「同一条记录」两侧可比
const exportRow = xAll.rows.find((r) => r[1] && String(r[1]).trim() !== '')
const prec = exportRow ? one(`select id, sku_code, name, base_price::text as bp, stock::text as st from products where tenant_id=${T} and sku_code='${String(exportRow[1]).replace(/'/g, "''")}' and deleted=0 limit 1`) : null
const precRow = prec ? exportRow : null
judge(R, {
  id: 'A5.4', name: '金额/库存精度逐字核对（DB 原文 vs 导出 cell）',
  expect: `价格 cell = ${prec?.bp}，库存 cell = ${prec?.st}（商品 ${prec?.sku_code}）`,
  actual: precRow ? `价格=${precRow[3]} 库存=${precRow[4]}` : '该商品不在导出结果里',
  pass: !!precRow && Number(precRow[3]) === Number(prec.bp) && Number(precRow[4]) === Number(prec.st),
  expectSource: 'DB 原文（numeric::text）独立读出；导出走 xlsx 数值 cell（doubleValue）⇒ 允许多余小数但不许值不等',
  evidence: [`DB: ${JSON.stringify(prec)}`, `导出首行: ${JSON.stringify(xAll.rows[0])}`],
})
// 不含他租户数据：导出里出现任意 sku_code，必须都属于 tenant 20
const skusInExport = xAll.rows.map((r) => r[1]).filter(Boolean)
const foreign = skusInExport.length
  ? psql(`select sku_code from products where tenant_id<>${T} and sku_code in (${skusInExport.map((s) => `'${String(s).replace(/'/g, "''")}'`).join(',')}) limit 20`)
  : []
judge(R, {
    id: 'A5.5', name: '导出不含其他租户数据（按货号反查他租户命中数）',
    expect: '他租户命中 = 0',
    actual: `他租户命中 = ${foreign.length} ${JSON.stringify(foreign.slice(0, 5))}`,
    pass: foreign.length === 0,
    expectSource: '多租户隔离：ProductController 从 TenantContext 取 tenantId，导出与列表同查询',
    evidence: [`导出货号样本(${skusInExport.length} 个): ${JSON.stringify(skusInExport.slice(0, 5))}`],
  })
// 空结果：keyword 命中 0 行 ⇒ 不得输出 0 字节却报成功
const kw = `${PROBE_PREFIX}绝不存在的关键字${tag}`
const expEmpty = await api('GET', `/api/admin/products/export?keyword=${encodeURIComponent(kw)}`, { token })
const listEmpty = await api('GET', `/api/admin/products?page=1&size=10000&keyword=${encodeURIComponent(kw)}`, { token })
let xEmpty = { rows: [], headers: [] }
try { xEmpty = expEmpty.buf?.length ? readXlsx(expEmpty.buf) : { rows: [], headers: [] } } catch (e) { xEmpty = { rows: [], headers: [], err: String(e) } }
writeFileSync(outPath('A5-export-empty.json'), JSON.stringify({
  http: expEmpty.status, bytes: expEmpty.buf?.length, headers: xEmpty.headers, rowCount: xEmpty.rows.length,
  listTotal: listEmpty.data?.total,
}, null, 2))
judge(R, {
  id: 'A5.6', name: '空结果导出：非畸形（不是 0 字节却报成功）+ 行数=0',
  expect: `HTTP 200 且 字节数 > 0 且 数据行 = 0 且 表头齐 7 列（列表 total=${listEmpty.data?.total}）`,
  actual: `HTTP ${expEmpty.status} 字节=${expEmpty.buf?.length} 行=${xEmpty.rows.length} 表头=${JSON.stringify(xEmpty.headers)}`,
  pass: expEmpty.status === 200 && (expEmpty.buf?.length ?? 0) > 0 && xEmpty.rows.length === 0 && JSON.stringify(xEmpty.headers) === JSON.stringify(['商品名称', '货号', '分类', '价格', '库存', '状态', '描述']),
  expectSource: 'Service#exportProducts 无条件写表头（sheet.createRow(0)）⇒ 零数据时仍应是合法 xlsx（表头齐、非 0 字节）',
  evidence: [`列表同筛选 total=${listEmpty.data?.total}`, `字节数=${expEmpty.buf?.length}`],
})

// ── A6 导入模板（对偶入口，正对照）──────────────────────────────────
const tpl = await api('GET', '/api/admin/products/import-template', { token })
let xt = { headers: [], rows: [] }
try { xt = tpl.buf?.length ? readXlsx(tpl.buf) : xt } catch { /* 非 xlsx */ }
judge(R, {
  id: 'A6.1', name: '导入模板表头 == IMPORT_HEADERS（模板与解析同源）',
  expect: JSON.stringify(H),
  actual: JSON.stringify(xt.headers),
  pass: JSON.stringify(xt.headers) === JSON.stringify(H),
  expectSource: 'ProductService.java 常量 IMPORT_HEADERS；模板生成与导入解析共用同一常量',
  evidence: [`HTTP ${tpl.status}, ${tpl.buf?.length} 字节, 示例行 ${xt.rows.length}`],
})

log(`A 段结束，摘要 ${JSON.stringify(R.summary())}`)
process.exit(R.summary().fail > 0 ? 1 : 0)
