// 临时探针（issue #6662 判据 3 现场核实，提交前删除）—— 用应用自己编译出的 Tailwind CSS
// 复现 ProductForm 的底部固定栏（z-30）与 Modal（z-50）在同层叠上下文下的命中关系。
const { chromium } = require(process.env.PW_PATH || '@playwright/test')
const CSS_URL = 'http://127.0.0.1:3011/_next/static/chunks/src_app_globals_162hn9o.css'

;(async () => {
  const css = await (await fetch(CSS_URL)).text()
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>${css}</style>
<style>#mask{position:fixed;inset:0;background:rgba(0,0,0,.45)}</style></head>
<body>
<div id="bar" class="fixed bottom-0 left-0 right-0 z-30 bg-white/95 border-t border-neutral-200">
  <div class="max-w-6xl mx-auto flex items-center justify-between gap-3 px-6 py-3">
    <button>重置</button>
    <button id="submit" type="button">提交并上架</button>
  </div>
</div>
<div id="modal" class="fixed inset-0 z-50">
  <div id="mask" class="absolute inset-0 bg-black/45"></div>
  <div id="tracker" class="absolute inset-0 flex items-center justify-center p-4 overflow-y-auto">
    <div role="dialog" aria-modal="true" aria-label="确认离开" class="relative bg-white rounded-2xl shadow-modal w-full max-h-full flex flex-col" style="max-width:520px">
      <div class="px-6 py-4 border-b border-neutral-200 shrink-0"><h3 class="text-lg font-semibold">确认离开</h3></div>
      <div data-testid="modal-body" class="px-6 py-4 flex-1"><p class="text-sm">当前表单内容尚未保存，离开后将丢失已填写的内容。</p></div>
      <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-neutral-200 shrink-0"><button>直接退出</button><button>存草稿</button></div>
    </div>
  </div>
</div>
<script>
  window.__c = { submit: 0, mask: 0, tracker: 0, dialog: 0 }
  document.getElementById('submit').addEventListener('click', () => window.__c.submit++)
  document.getElementById('mask').addEventListener('click', () => window.__c.mask++)
  document.getElementById('tracker').addEventListener('click', () => window.__c.tracker++)
  document.querySelector('[role=dialog]').addEventListener('click', () => window.__c.dialog++)
</script>
</body></html>`

  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 980 } })
  await page.setContent(html, { waitUntil: 'load' })

  const geo = await page.evaluate(() => {
    const btn = document.getElementById('submit')
    const r = btn.getBoundingClientRect()
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2
    const hit = document.elementFromPoint(cx, cy)
    return {
      submitCenter: { x: Math.round(cx), y: Math.round(cy) },
      hitAtSubmitCenter: { tag: hit.tagName, id: hit.id, cls: String(hit.className).slice(0, 55) },
      hitIsSubmit: hit === btn,
      z: { bar: getComputedStyle(document.getElementById('bar')).zIndex, modal: getComputedStyle(document.getElementById('modal')).zIndex },
    }
  })

  // ① Playwright 真实点击「提交并上架」（带 hit-target 检查）
  let pwClick
  try { await page.click('#submit', { timeout: 2500 }); pwClick = 'ok' }
  catch (e) { pwClick = String(e).split('\n')[0].slice(0, 90) }
  const afterPw = await page.evaluate(() => ({ ...window.__c }))

  // ② 在「提交并上架」中心坐标做真实鼠标点击
  await page.mouse.click(geo.submitCenter.x, geo.submitCenter.y)
  const afterCenter = await page.evaluate(() => ({ ...window.__c }))

  // ③ 对照：点遮罩本身（弹窗内容之外，左侧空白）
  await page.mouse.click(200, 300)
  const afterMask = await page.evaluate(() => ({ ...window.__c }))

  console.log(JSON.stringify({ geo, pwClick, afterPw, afterCenter, afterMask }, null, 1))
  await browser.close()
})().catch((e) => { console.error('FAILED', e); process.exit(1) })
