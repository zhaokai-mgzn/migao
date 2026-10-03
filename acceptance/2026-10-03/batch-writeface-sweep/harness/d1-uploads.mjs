// D — 上传（6 个端点）+ 边界/穿越/部分失败
import {
  Recorder, judge, api, upload, loginApi, PROBE_PREFIX, ID_PREFIX, log, nowCST, writeFileSync,
  outPath, uploadsDir, listFilesRec, sha256, psql,
} from './lib.mjs'

const R = new Recorder('D-uploads.json')
const { token } = await loginApi()
log(`D 段开始 ${nowCST().cst} (UTC ${nowCST().utc})`)

// 真 PNG（1x1，base64 内联 —— 内容必须是真图片，否则"合法上传"这条自己就是假绿）
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAAMBAQAY3Y2wAAAAAElFTkSuQmCC', 'base64')
const MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const dirBefore = uploadsDir()
const filesBefore = dirBefore ? listFilesRec(dirBefore) : []
log(`本地 uploads 目录 = ${dirBefore ?? '（不存在 ⇒ 用 OSS/远端存储）'}，现有 ${filesBefore.length} 个文件`)

const EP = {
  upload: '/api/admin/files/upload',
  uploadBatch: '/api/admin/files/upload-batch',
  image: '/api/admin/upload/image',
  images: '/api/admin/upload/images',
}
const seenUrls = []

// ── D1 正对照：真 PNG 走 4 个上传端点都成功 + URL 可访问 + 字节一致 ──
const d1 = await upload(EP.upload, { token, files: [{ field: 'file', filename: `${PROBE_PREFIX}图.png`, content: PNG, type: 'image/png' }], fields: { directory: 'images' } })
let urlOk = null, urlBytes = null
if (d1.data?.url) {
  seenUrls.push(d1.data.url)
  const full = d1.data.url.startsWith('http') ? d1.data.url : 'http://127.0.0.1:8080' + d1.data.url
  const g = await fetch(full, { signal: AbortSignal.timeout(20000) }).catch((e) => ({ status: 0, arrayBuffer: async () => Buffer.alloc(0), _err: String(e) }))
  urlOk = g.status
  try { urlBytes = Buffer.from(await g.arrayBuffer()).length } catch { urlBytes = -1 }
}
writeFileSync(outPath('D1-upload-ok.json'), JSON.stringify({ http: d1.status, body: d1.json, urlStatus: urlOk, urlBytes, srcBytes: PNG.length }, null, 2))
judge(R, {
  id: 'D1.1', name: '成功路径 /files/upload：200 + 返回 URL + size 与源文件一致',
  expect: `HTTP 200，data.url 非空，data.size=${PNG.length}`,
  actual: `HTTP ${d1.status} url=${d1.data?.url} size=${d1.data?.size}`,
  pass: d1.status === 200 && !!d1.data?.url && Number(d1.data?.size) === PNG.length,
  expectSource: 'UploadController#uploadFile → FileStorageService#upload；UploadedFileInfo{id,url,name,size,type,createdAt}',
  evidence: [`响应: ${d1.text.slice(0, 300)}`],
})
judge(R, {
  id: 'D1.2', name: '成功路径：返回的 URL **可访问**且字节数与源文件一致',
  expect: `URL GET 返回 200 且 字节数=${PNG.length}`,
  actual: `HTTP ${urlOk}，字节数=${urlBytes}`,
  pass: urlOk === 200 && urlBytes === PNG.length,
  expectSource: '上传语义：返回的 URL 必须真能取回同一份内容（否则"上传成功"是纸面成功）',
  evidence: [`URL: ${d1.data?.url}`],
})
const d2 = await upload(EP.image, { token, files: [{ field: 'file', filename: `${PROBE_PREFIX}图2.png`, content: PNG, type: 'image/png' }], fields: { directory: 'images' } })
if (d2.data?.url) seenUrls.push(d2.data.url)
judge(R, {
  id: 'D1.3', name: '兼容端点 /upload/image 正对照：200 + url',
  expect: 'HTTP 200 且 data.url 非空',
  actual: `HTTP ${d2.status} url=${d2.data?.url}`,
  pass: d2.status === 200 && !!d2.data?.url,
  expectSource: 'UploadController#uploadImage（兼容旧接口）返回 Map.of("url", …)',
  evidence: [`响应: ${d2.text.slice(0, 200)}`],
})
const d3 = await upload(EP.uploadBatch, {
  token,
  files: [{ field: 'files', filename: `${PROBE_PREFIX}批1.png`, content: PNG, type: 'image/png' }, { field: 'files', filename: `${PROBE_PREFIX}批2.png`, content: PNG, type: 'image/png' }],
  fields: { directory: 'images' },
})
;(d3.data || []).forEach((x) => x?.url && seenUrls.push(x.url))
const d4 = await upload(EP.images, { token, files: [{ field: 'files', filename: `${PROBE_PREFIX}批3.png`, content: PNG, type: 'image/png' }], fields: { directory: 'images' } })
;(d4.data?.urls || []).forEach((u) => seenUrls.push(u))
judge(R, {
  id: 'D1.4', name: '批量端点 /files/upload-batch 与 /upload/images 正对照：各返回 N 条 url',
  expect: `upload-batch HTTP 200 且 2 条；upload/images HTTP 200 且 1 条`,
  actual: `upload-batch HTTP ${d3.status} 条数=${d3.data?.length}；upload/images HTTP ${d4.status} 条数=${d4.data?.urls?.length}`,
  pass: d3.status === 200 && d3.data?.length === 2 && d4.status === 200 && d4.data?.urls?.length === 1,
  expectSource: 'UploadController#uploadFiles（最多 10）/#uploadImages',
  evidence: [`upload-batch: ${d3.text.slice(0, 250)}`, `upload/images: ${d4.text.slice(0, 200)}`],
})

// ── D2 边界：空文件 / 伪造扩展名 / 超限 ──
const d5 = await upload(EP.upload, { token, files: [{ field: 'file', filename: 'empty.png', content: Buffer.alloc(0), type: 'image/png' }] })
const d6 = await upload(EP.upload, { token, files: [{ field: 'file', filename: 'evil.exe', content: Buffer.from('MZ\x90\x00evil'), type: 'application/octet-stream' }] })
const big6 = Buffer.concat([PNG, Buffer.alloc(6 * 1024 * 1024, 0x41)])   // 6MB > 5MB 图片上限
const d7 = await upload(EP.upload, { token, files: [{ field: 'file', filename: 'big6.png', content: big6, type: 'image/png' }], timeoutMs: 180000 })
// 伪造扩展名 + 非图片内容（内容嗅探是否缺失）
const d8 = await upload(EP.upload, { token, files: [{ field: 'file', filename: 'fake.png', content: Buffer.from('这不是图片，是纯文本 payload'), type: 'image/png' }] })
// 伪 Content-Type 绕过图片 5MB 上限（validateFile 用 contentType 判 isImage）
const big19 = Buffer.concat([Buffer.from('%PDF-1.4\n'), Buffer.alloc(19 * 1024 * 1024, 0x42)])
const d9 = await upload(EP.upload, { token, files: [{ field: 'file', filename: 'big19.png', content: big19, type: 'application/pdf' }], timeoutMs: 300000 })
if (d8.data?.url) seenUrls.push(d8.data.url)
if (d9.data?.url) seenUrls.push(d9.data.url)
writeFileSync(outPath('D2-boundaries.json'), JSON.stringify({
  empty: { http: d5.status, body: d5.json }, exe: { http: d6.status, body: d6.json },
  big6: { http: d7.status, bytes: big6.length, body: d7.json },
  fakeContentPng: { http: d8.status, body: d8.json, srcBytes: 30 },
  pdfCtPngExt19MB: { http: d9.status, bytes: big19.length, body: d9.json },
}, null, 2))
judge(R, {
  id: 'D2.1', name: '空文件 ⇒ 明确拒绝（4xx）',
  expect: 'HTTP 4xx',
  actual: `HTTP ${d5.status} body=${d5.text.slice(0, 160)}`,
  pass: d5.status >= 400 && d5.status < 500,
  expectSource: 'FileStorageService#validateFile: file.isEmpty() ⇒ validationError("请选择要上传的文件")',
  evidence: [`响应: ${d5.text.slice(0, 200)}`],
})
judge(R, {
  id: 'D2.2', name: '伪造扩展名 .exe ⇒ 明确拒绝（4xx）',
  expect: 'HTTP 4xx',
  actual: `HTTP ${d6.status} body=${d6.text.slice(0, 160)}`,
  pass: d6.status >= 400 && d6.status < 500,
  expectSource: 'ALLOWED_EXTENSIONS 白名单（jpg/jpeg/png/gif/webp/pdf/xlsx/docx）',
  evidence: [`响应: ${d6.text.slice(0, 200)}`],
})
judge(R, {
  id: 'D2.3', name: '超限：6MB 的 .png（>5MB 图片上限）⇒ 明确拒绝',
  expect: 'HTTP 4xx',
  actual: `HTTP ${d7.status} bytes=${big6.length} body=${d7.text.slice(0, 160)}`,
  pass: d7.status >= 400 && d7.status < 500,
  expectSource: 'MAX_IMAGE_SIZE = 5MB（OssService/LocalFileStorageService 同值）',
  evidence: [`响应: ${d7.text.slice(0, 200)}`],
})
judge(R, {
  id: 'D2.4', name: '非图片内容 + .png 扩展名（内容嗅探缺失？）⇒ 实测口径登记',
  expect: `HTTP 200 表示**仅按扩展名**放行（无内容嗅探）；4xx 表示有内容校验`,
  actual: `HTTP ${d8.status} body=${d8.text.slice(0, 200)}`,
  pass: true,  // 本条的测点 = **如实登记口径**（不是"必须拒"——产品未声明内容嗅探）
  expectSource: 'validateFile 只校验扩展名 + 大小 + contentType，不做魔数校验（源码逐字）；故按实测登记',
  evidence: [`伪 PNG 内容（30 字节纯文本）⇒ HTTP ${d8.status}，url=${d8.data?.url ?? '—'}`, `🔴 若 200：任意内容可伪装 .png 上传并公开可取（登记项，非本包判红）`],
})
judge(R, {
  id: 'D2.5', name: '伪 Content-Type 绕过图片 5MB 上限（.png + application/pdf + 19MB）',
  expect: `4xx（不许用客户端自报的 Content-Type 放宽上限）或 200（登记为绕过）`,
  actual: `HTTP ${d9.status} bytes=${big19.length} body=${d9.text.slice(0, 180)}`,
  pass: d9.status >= 400 && d9.status < 500,
  expectSource: 'OssService#validateFile：isImageType(file.getContentType()) ⇒ 上限 20MB；**Content-Type 是客户端可控** ⇒ 若 200 即上限绕过',
  evidence: [`响应: ${d9.text.slice(0, 250)}`],
})

// ── D3 路径穿越：文件名 / directory 参数 ──
const d10 = await upload(EP.upload, { token, files: [{ field: 'file', filename: '../../l2evil.png', content: PNG, type: 'image/png' }], fields: { directory: 'images' } })
if (d10.data?.url) seenUrls.push(d10.data.url)
const d11 = await upload(EP.upload, { token, files: [{ field: 'file', filename: 'ok.png', content: PNG, type: 'image/png' }], fields: { directory: '../../l2evil' } })
if (d11.data?.url) seenUrls.push(d11.data.url)
const dirAfter = uploadsDir()
const filesAfter = dirAfter ? listFilesRec(dirAfter) : []
const newFiles = filesAfter.filter((f) => !filesBefore.some((b) => b.rel === f.rel))
const escaped = newFiles.filter((f) => f.rel.includes('..') || f.rel.startsWith('l2evil'))
writeFileSync(outPath('D3-traversal.json'), JSON.stringify({
  filenameTraversal: { http: d10.status, url: d10.data?.url, name: d10.data?.name },
  directoryTraversal: { http: d11.status, url: d11.data?.url, body: d11.json },
  uploadsDir: dirAfter, newLocalFiles: newFiles, escapedFiles: escaped,
}, null, 2))
judge(R, {
  id: 'D3.1', name: '文件名穿越 ../../l2evil.png：不得写到 uploads 之外（存储名走 UUID）',
  expect: '落盘文件名不含 `..`；uploads 目录内无逃逸文件',
  actual: `HTTP ${d10.status} 返回 name=${d10.data?.name} url=${d10.data?.url}；逃逸文件=${JSON.stringify(escaped)}`,
  pass: escaped.length === 0,
  expectSource: 'LocalFileStorageService：storedFilename = UUID + ext（用户文件名只进 name 字段）；OssService：objectKey 亦为 UUID',
  evidence: [`新落盘文件: ${JSON.stringify(newFiles.slice(0, 5))}`],
})
judge(R, {
  id: 'D3.2', name: 'directory 参数穿越 ../../l2evil：存储实现必须拦住（本地实现 safeResolve / OSS 实现无校验）',
  expect: `HTTP 4xx（干净拒绝，本地实现是 422 "非法文件路径"）`,
  actual: `HTTP ${d11.status} url=${d11.data?.url} body=${d11.text.slice(0, 200)}`,
  pass: d11.status >= 400 && d11.status < 500,   // 🔴 实测 500 INTERNAL_ERROR = OSS 实现**无 directory 校验** ⇒ 登记为缺陷
  expectSource: 'LocalFileStorageService#safeResolve：normalize 后必须 startsWith(uploads 根) 否则 validationError("非法文件路径")；**OssService#generateObjectKey 无此校验**（源码逐字）',
  evidence: [`响应: ${d11.text.slice(0, 300)}`],
})

// ── D4 批量部分失败语义 ──
const b1 = await upload(EP.uploadBatch, { token, files: [{ field: 'files', filename: `${PROBE_PREFIX}好.png`, content: PNG, type: 'image/png' }, { field: 'files', filename: 'bad.exe', content: Buffer.from('MZ'), type: 'application/octet-stream' }], fields: { directory: 'images' } })
;(b1.data || []).forEach((x) => x?.url && seenUrls.push(x.url))
const dirAfter2 = uploadsDir()
const filesAfter2 = dirAfter2 ? listFilesRec(dirAfter2) : []
const newAfter2 = filesAfter2.filter((f) => !filesAfter.some((b) => b.rel === f.rel))
writeFileSync(outPath('D4-batch-partial.json'), JSON.stringify({
  http: b1.status, body: b1.json, newLocalFilesAfterBatch: newAfter2,
}, null, 2))
judge(R, {
  id: 'D4.1', name: '批量部分失败（第 2 个非法）：第 1 个是否已落库/落盘 —— 如实登记语义',
  expect: `若 HTTP 4xx/5xx 但第 1 个已落盘 ⇒ 「无事务的逐文件循环」语义（登记）；若整体回滚 ⇒ 零残留`,
  actual: `HTTP ${b1.status} body=${b1.text.slice(0, 250)}；新落盘文件=${JSON.stringify(newAfter2.map((f) => f.rel))}`,
  pass: true, // 登记型判据：产品未声明批量原子性；本条的测点是**如实记录**（是否留下半成品）
  expectSource: 'UploadController#uploadFiles：for 循环逐个 upload（**无事务**，源码逐字）⇒ 预期"先成功的已落盘"',
  evidence: [`🔴 若 HTTP 4xx 而第 1 个已落盘 ⇒ 部分成功无语义反馈（登记项）`],
})

// ── D5 目录/租户隔离：不得写到公共根 ──
judge(R, {
  id: 'D5.1', name: '存储隔离：上传落点不得是公共根（本地落 uploads/{directory}/，远端落 {directory}/日期/uuid）',
  expect: '每个 URL 都含 directory 段（images/…），不是裸文件名',
  actual: `样本 URL: ${JSON.stringify(seenUrls.slice(0, 5))}`,
  // 🔴 首轮这条是**我的判据缺陷**：我写成「必须含 directory 段 **且** 不得以 uuid.ext 结尾」——
  //    后半句与「远端存 {directory}/{yyyy/MM/dd}/{uuid}{ext}」**正面冲突**（每个合法 URL 都以 uuid.ext 结尾）
  //    ⇒ 判据自相矛盾 ⇒ 假红。正确判据：URL 必须含非根 directory 段（不是 OSS bucket 根）。
  pass: seenUrls.length > 0 && seenUrls.every((u) => /\/(images|chat|files)\/\d{4}\/\d{2}\/\d{2}\//i.test(u)),
  expectSource: 'OssService#generateObjectKey = `{directory}/{yyyy/MM/dd}/{uuid}{ext}`；LocalFileStorageService url = /api/files/static/{directory}/{uuid}{ext}',
  evidence: [`共 ${seenUrls.length} 个 URL`],
})

// 清理：删除本包上传的对象（走删除端点；仅本包 url）
let delOk = 0, delFail = 0
for (const u of seenUrls) {
  const r = await api('DELETE', '/api/admin/upload/image', { token, body: { url: u } })
  if (r.status === 200) delOk++; else delFail++
}
log(`D 段上传对象清理：delete 200=${delOk} 失败=${delFail}`)
log(`D 段结束，摘要 ${JSON.stringify(R.summary())}`)
process.exit(0)
