// case_ids: UI-082
//
// 生成官网分享图 `frontend/admin-web/public/og-image.png`（1200×630，issue #6665 第 3 条）。
//
// 为什么需要一个**可复算**的生成器（而不是随手丢一张图进 public/）：
// `(corporate)/layout.tsx` 的 `og:image` 声明了 1200×630 的尺寸 —— 图片与声明必须逐值一致，
// 否则各平台抓到的预览图会被裁得莫名其妙。本脚本零依赖（只用 node:zlib）、输出可复算
// （同参数连跑两次逐字节一致），改文案重跑一条命令即可。
//
// 中文标题用**内嵌点阵字形**（16×16，放大 10 倍）—— 脚本无字体依赖，也就不会因为
// 换机器 / 缺字体而产出不一样的东西；配一张真实的品牌构图（暖黑底 + 三团柔光 + 织金 Logo）。
//
// 用法：node scripts/gen-og-image.mjs   （在 frontend/admin-web 目录下跑）
import { deflateSync } from 'node:zlib'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const WIDTH = 1200
const HEIGHT = 630
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'og-image.png')

/** 背景：官网 Hero 同源的暖黑底 + 靛蓝 / 陶土 / 织金三团柔光。 */
const BG = [0x14, 0x18, 0x22]
const GLOWS = [
  { x: 1000, y: 96, r: 430, rgb: [0x48, 0x61, 0x8f], a: 0.5 }, // primary-500 靛蓝
  { x: 260, y: 210, r: 380, rgb: [0xcc, 0x80, 0x56], a: 0.2 }, // accent-400 陶土
  { x: 700, y: 640, r: 380, rgb: [0xd4, 0x88, 0x06], a: 0.28 }, // gold-600 织金
]
const GOLD = [0xd4, 0x88, 0x06]
const WHITE = [0xf5, 0xf2, 0xec]
const MUTED = [0xb8, 0xaa, 0x94] // neutral-400

const clamp255 = (v) => (v < 0 ? 0 : v > 255 ? 255 : Math.round(v))

/** 画布：先铺底色，再叠三团径向柔光。 */
function makeCanvas() {
  const px = new Uint8Array(WIDTH * HEIGHT * 3)
  for (let y = 0; y < HEIGHT; y++) {
    for (let x = 0; x < WIDTH; x++) {
      let r = BG[0]
      let g = BG[1]
      let b = BG[2]
      for (const glow of GLOWS) {
        const d = Math.hypot(x - glow.x, y - glow.y)
        if (d >= glow.r) continue
        const w = Math.pow(1 - d / glow.r, 2) * glow.a
        r += (glow.rgb[0] - r) * w
        g += (glow.rgb[1] - g) * w
        b += (glow.rgb[2] - b) * w
      }
      const i = (y * WIDTH + x) * 3
      px[i] = clamp255(r)
      px[i + 1] = clamp255(g)
      px[i + 2] = clamp255(b)
    }
  }
  return px
}

function fillRect(px, x0, y0, w, h, rgb, alpha = 1) {
  for (let y = Math.max(0, y0); y < Math.min(HEIGHT, y0 + h); y++) {
    for (let x = Math.max(0, x0); x < Math.min(WIDTH, x0 + w); x++) {
      const i = (y * WIDTH + x) * 3
      px[i] = clamp255(px[i] + (rgb[0] - px[i]) * alpha)
      px[i + 1] = clamp255(px[i + 1] + (rgb[1] - px[i + 1]) * alpha)
      px[i + 2] = clamp255(px[i + 2] + (rgb[2] - px[i + 2]) * alpha)
    }
  }
}

/** 16×16 点阵字形（`#` = 落笔）。只放本图用到的三个字，避免引入字体依赖。 */
const CJK = {
  // 观：左「又」+ 右「见」
  观: [
    '................',
    '.###...........',
    '...#.......####.',
    '....#.....#....#',
    '....#.....#....#',
    '.#...#....#....#',
    '.#...##...####.#',
    '.#....#...#....#',
    '.#...##...#....#',
    '.#..#.#...#....#',
    '.#.#..#...####.#',
    '.##....#........',
    '.#.....#........',
    '................',
    '................',
    '................',
  ],
  // 星：上「日」+ 下「生」
  星: [
    '................',
    '................',
    '..###.....###...',
    '..#.#..#..#.#...',
    '..###.....###...',
    '..#.#..#..#.#...',
    '..###.....###...',
    '................',
    '................',
    '.#..#..#..#..#..',
    '.#..#..#..#..#..',
    '.##############.',
    '.....#.....#....',
    '...#########....',
    '.....#.....#....',
    '.....#.....#....',
  ],
  // 台：上「厶」+ 下「口」
  台: [
    '................',
    '................',
    '.......##.......',
    '......#..#......',
    '.....#....#.....',
    '....######......',
    '...#......#.....',
    '..#........#....',
    '................',
    '...##########...',
    '...#........#...',
    '...#........#...',
    '...#........#...',
    '...##########...',
    '................',
    '................',
  ],
}

/** 点阵字：scale = 每个点几个像素。返回结束时的 x 坐标。 */
function drawCjk(px, text, x, y, scale, rgb) {
  let cx = x
  for (const ch of text) {
    const glyph = CJK[ch]
    if (!glyph) {
      cx += 17 * scale
      continue
    }
    for (let gy = 0; gy < 16; gy++) {
      for (let gx = 0; gx < 16; gx++) {
        if (glyph[gy][gx] === '#') fillRect(px, cx + gx * scale, y + gy * scale, scale, scale, rgb)
      }
    }
    cx += 17 * scale
  }
  return cx
}

/** 5×7 点阵（ASCII 标签用）。 */
const ASCII = {
  M: ['10001', '11011', '10101', '10001', '10001', '10001', '10001'],
  I: ['11111', '00100', '00100', '00100', '00100', '00100', '11111'],
  G: ['01110', '10001', '10000', '10111', '10001', '10001', '01110'],
  A: ['01110', '10001', '10001', '11111', '10001', '10001', '10001'],
  O: ['01110', '10001', '10001', '10001', '10001', '10001', '01110'],
  ' ': ['00000', '00000', '00000', '00000', '00000', '00000', '00000'],
}

function drawAscii(px, text, x, y, scale, rgb) {
  let cx = x
  for (const ch of text) {
    const glyph = ASCII[ch]
    if (!glyph) {
      cx += 6 * scale
      continue
    }
    for (let gy = 0; gy < 7; gy++) {
      for (let gx = 0; gx < 5; gx++) {
        if (glyph[gy][gx] === '1') fillRect(px, cx + gx * scale, y + gy * scale, scale, scale, rgb)
      }
    }
    cx += 6 * scale
  }
  return cx
}

/** 织金方牌 Logo（顶栏 + 三垂帘的意象；与站点 Logo 同构图、同色）。 */
function drawLogo(px, x, y, size) {
  for (let i = 0; i < size; i++) {
    for (let j = 0; j < size; j++) {
      const t = (i + j) / (2 * size)
      fillRect(px, x + i, y + j, 1, 1, [
        clamp255(GOLD[0] + 0x40 * t),
        clamp255(GOLD[1] + 0x38 * t),
        clamp255(GOLD[2] + 0x20 * t),
      ])
    }
  }
  fillRect(px, x + size * 0.14, y + size * 0.15, size * 0.72, size * 0.06, WHITE, 0.5)
  fillRect(px, x + size * 0.22, y + size * 0.3, size * 0.12, size * 0.44, WHITE, 0.92)
  fillRect(px, x + size * 0.44, y + size * 0.24, size * 0.12, size * 0.5, WHITE, 0.92)
  fillRect(px, x + size * 0.66, y + size * 0.3, size * 0.12, size * 0.44, WHITE, 0.92)
}

const px = makeCanvas()

// ── 构图（1200×630）：左上 Logo + 织金细线 + 中文主标题 + 两行说明 ──
drawLogo(px, 96, 84, 92)
drawAscii(px, 'MIGAO', 96 + 92 + 26, 84 + 30, 6, WHITE)

fillRect(px, 96, 232, 108, 8, GOLD, 0.95) // 织金短横（品牌点缀）
drawCjk(px, '观星台', 96, 268, 10, WHITE) // 16×10 = 160px 高

fillRect(px, 96, 470, 760, 22, WHITE, 0.92) // 「布艺行业的 AI 经营平台」
fillRect(px, 96, 508, 560, 22, WHITE, 0.92)
fillRect(px, 96, 566, 420, 10, MUTED, 0.75) // 脚注行

// ── PNG 编码（IHDR + IDAT + IEND，真彩 RGB） ──
function crc32(buf) {
  let c = ~0
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i]
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1))
  }
  return ~c >>> 0
}

function chunk(type, data) {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length, 0)
  const typeBuf = Buffer.from(type, 'ascii')
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0)
  return Buffer.concat([len, typeBuf, data, crc])
}

const raw = Buffer.alloc((WIDTH * 3 + 1) * HEIGHT)
for (let y = 0; y < HEIGHT; y++) {
  raw[y * (WIDTH * 3 + 1)] = 0 // filter: None
  Buffer.from(px.buffer, y * WIDTH * 3, WIDTH * 3).copy(raw, y * (WIDTH * 3 + 1) + 1)
}

const ihdr = Buffer.alloc(13)
ihdr.writeUInt32BE(WIDTH, 0)
ihdr.writeUInt32BE(HEIGHT, 4)
ihdr[8] = 8 // bit depth
ihdr[9] = 2 // color type: truecolor RGB
const png = Buffer.concat([
  Buffer.from('89504e470d0a1a0a', 'hex'),
  chunk('IHDR', ihdr),
  chunk('IDAT', deflateSync(raw, { level: 9 })),
  chunk('IEND', Buffer.alloc(0)),
])

writeFileSync(OUT, png)
console.log(`✅ ${OUT} — ${WIDTH}×${HEIGHT}, ${png.length} bytes`)
