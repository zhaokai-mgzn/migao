/**
 * 生成 TabBar 占位图标
 * 使用纯 Node.js 生成简单的 PNG 图标（无需外部依赖）
 *
 * 生成 6 个图标：chat / chat-active / sessions / sessions-active / profile / profile-active
 * 尺寸 81x81，格式 PNG
 */

const fs = require('fs')
const path = require('path')

const ASSETS_DIR = path.join(__dirname, '..', 'src', 'assets', 'tabbar')

// 最小可用 PNG：使用简单色块
// PNG 结构：signature + IHDR + IDAT + IEND
function createPNG(width, height, r, g, b, a) {
  // PNG Signature
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])

  // IHDR chunk
  const ihdrData = Buffer.alloc(13)
  ihdrData.writeUInt32BE(width, 0)
  ihdrData.writeUInt32BE(height, 4)
  ihdrData[8] = 8  // bit depth
  ihdrData[9] = 6  // color type: RGBA
  ihdrData[10] = 0 // compression
  ihdrData[11] = 0 // filter
  ihdrData[12] = 0 // interlace
  const ihdr = createChunk('IHDR', ihdrData)

  // Raw image data: for each row, filter byte (0) + RGBA pixels
  const rowSize = 1 + width * 4
  const rawData = Buffer.alloc(rowSize * height)
  for (let y = 0; y < height; y++) {
    const offset = y * rowSize
    rawData[offset] = 0 // filter: none
    for (let x = 0; x < width; x++) {
      const px = offset + 1 + x * 4
      rawData[px] = r
      rawData[px + 1] = g
      rawData[px + 2] = b
      rawData[px + 3] = a
    }
  }

  // Compress with zlib (deflate)
  const zlib = require('zlib')
  const compressed = zlib.deflateSync(rawData)
  const idat = createChunk('IDAT', compressed)

  // IEND
  const iend = createChunk('IEND', Buffer.alloc(0))

  return Buffer.concat([signature, ihdr, idat, iend])
}

function createChunk(type, data) {
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length, 0)
  const typeBuffer = Buffer.from(type, 'ascii')
  const crcData = Buffer.concat([typeBuffer, data])
  const crc = crc32(crcData)
  const crcBuffer = Buffer.alloc(4)
  crcBuffer.writeUInt32BE(crc >>> 0, 0)
  return Buffer.concat([length, typeBuffer, data, crcBuffer])
}

// CRC32 (PNG standard)
function crc32(buf) {
  let crc = 0xffffffff
  for (let i = 0; i < buf.length; i++) {
    crc ^= buf[i]
    for (let j = 0; j < 8; j++) {
      if (crc & 1) {
        crc = (crc >>> 1) ^ 0xedb88320
      } else {
        crc = crc >>> 1
      }
    }
  }
  return (crc ^ 0xffffffff) >>> 0
}

// 创建带简单图案的图标
function createIconWithShape(width, height, fgR, fgG, fgB, shape) {
  const zlib = require('zlib')
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])
  const ihdrData = Buffer.alloc(13)
  ihdrData.writeUInt32BE(width, 0)
  ihdrData.writeUInt32BE(height, 4)
  ihdrData[8] = 8
  ihdrData[9] = 6
  const ihdr = createChunk('IHDR', ihdrData)

  const rowSize = 1 + width * 4
  const rawData = Buffer.alloc(rowSize * height)
  const cx = width / 2
  const cy = height / 2

  for (let y = 0; y < height; y++) {
    const offset = y * rowSize
    rawData[offset] = 0
    for (let x = 0; x < width; x++) {
      const px = offset + 1 + x * 4
      let inside = false

      if (shape === 'chat') {
        // 聊天气泡：圆角矩形 + 小三角
        const bx = cx - 22, by = cy - 20, bw = 44, bh = 34
        const inRect = x >= bx && x < bx + bw && y >= by && y < by + bh
        const triDist = y >= by + bh && y < by + bh + 8 && x >= cx - 6 && x < cx + 2 && (y - by - bh) < (x - cx + 6)
        inside = inRect || triDist
      } else if (shape === 'list') {
        // 列表图标：三条横线
        const lines = [cy - 14, cy, cy + 14]
        inside = lines.some(ly => Math.abs(y - ly) <= 2 && x >= cx - 20 && x <= cx + 20)
        // 小圆点
        const dots = lines.map(ly => ({ x: cx - 26, y: ly }))
        inside = inside || dots.some(d => Math.hypot(x - d.x, y - d.y) <= 3)
      } else if (shape === 'profile') {
        // 人物头像：圆 + 半圆身体
        const headR = 11
        const inHead = Math.hypot(x - cx, y - (cy - 10)) <= headR
        const bodyR = 20
        const inBody = Math.hypot(x - cx, y - (cy + 25)) <= bodyR && y < cy + 20
        inside = inHead || inBody
      }

      if (inside) {
        rawData[px] = fgR
        rawData[px + 1] = fgG
        rawData[px + 2] = fgB
        rawData[px + 3] = 255
      } else {
        rawData[px] = 0
        rawData[px + 1] = 0
        rawData[px + 2] = 0
        rawData[px + 3] = 0 // transparent
      }
    }
  }

  const compressed = zlib.deflateSync(rawData)
  const idat = createChunk('IDAT', compressed)
  const iend = createChunk('IEND', Buffer.alloc(0))
  return Buffer.concat([signature, ihdr, idat, iend])
}

// 确保目录存在
fs.mkdirSync(ASSETS_DIR, { recursive: true })

const icons = [
  { name: 'chat.png',              shape: 'chat',    r: 153, g: 153, b: 153 },
  { name: 'chat-active.png',       shape: 'chat',    r: 47,  g: 84,  b: 235 },
  { name: 'sessions.png',          shape: 'list',    r: 153, g: 153, b: 153 },
  { name: 'sessions-active.png',   shape: 'list',    r: 47,  g: 84,  b: 235 },
  { name: 'profile.png',           shape: 'profile', r: 153, g: 153, b: 153 },
  { name: 'profile-active.png',    shape: 'profile', r: 47,  g: 84,  b: 235 },
]

icons.forEach(({ name, shape, r, g, b }) => {
  const png = createIconWithShape(81, 81, r, g, b, shape)
  const filepath = path.join(ASSETS_DIR, name)
  fs.writeFileSync(filepath, png)
  console.log(`✓ ${name} (${png.length} bytes)`)
})

console.log('\n图标生成完成！')
