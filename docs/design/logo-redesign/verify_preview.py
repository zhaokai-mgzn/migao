#!/usr/bin/env python3
"""Pixel-level verification of logo preview PNGs (no PIL: stdlib PNG decoder).
qlmanage pads thumbnails on a 1024x1024 canvas; we map SVG coords through the drawn bbox."""
import struct, zlib, sys

def decode_png(path):
    data = open(path, 'rb').read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'bad signature'
    pos, idat, w, h, bitd, ctype = 8, b'', 0, 0, 0, 0
    while pos < len(data):
        (ln,) = struct.unpack('>I', data[pos:pos+4])
        typ = data[pos+4:pos+8]
        chunk = data[pos+8:pos+8+ln]
        if typ == b'IHDR':
            w, h, bitd, ctype = struct.unpack('>IIBB', chunk[:10])
        elif typ == b'IDAT':
            idat += chunk
        pos += 12 + ln
    assert bitd == 8 and ctype in (2, 6), f'unsupported: bitdepth={bitd} colortype={ctype}'
    ch = 3 if ctype == 2 else 4
    raw = zlib.decompress(idat)
    stride, bpp = w * ch, ch
    rows, prev = [], bytearray(stride)
    off = 0
    for _ in range(h):
        ft = raw[off]; off += 1
        line = bytearray(raw[off:off+stride]); off += stride
        if ft == 1:
            for i in range(bpp, stride): line[i] = (line[i] + line[i-bpp]) & 255
        elif ft == 2:
            for i in range(stride): line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                a = line[i-bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i-bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i-bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        rows.append(bytes(line)); prev = line
    return w, h, ch, b''.join(rows)

def px(img, w, ch, x, y):
    i = (y * w + x) * ch
    return img[i], img[i+1], img[i+2]

def bbox(img, w, h, ch):
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        row = y * w * ch
        for x in range(w):
            i = row + x * ch
            if img[i] < 240 or img[i+1] < 240 or img[i+2] < 240:
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y
    return minx, miny, maxx, maxy

def near(rgb, exp, tol=40):
    return all(abs(a-b) <= tol for a, b in zip(rgb, exp))

results = []

def check_mark(name, path, samples_svg, scan=None):
    """48x48 mark: map SVG (2..46) tile through drawn bbox (tile is the widest/bottom-most content)."""
    w, h, ch, img = decode_png(path)
    bx0, by0, bx1, by1 = bbox(img, w, h, ch)
    s = (bx1 - bx0 + 1) / 44          # scale from tile width
    top = by1 + 1 - 44 * s            # tile top from tile bottom
    print(f'== {name} ({w}x{h}), bbox=({bx0},{by0})-({bx1},{by1}), s={s:.2f}')
    ok = True
    for label, (sx, sy), exp, tol in samples_svg:
        x, y = int(bx0 + (sx-2)*s), int(top + (sy-2)*s)
        rgb = px(img, w, ch, x, y)
        good = near(rgb, exp, tol)
        ok &= good
        print(f'   {label:20s} svg({sx},{sy}) px({x},{y}) rgb{rgb} expect~{exp} {"PASS" if good else "FAIL"}')
    if scan:
        label, x0, y0, x1, y1, cond = scan
        found = False
        for yy in range(y0, y1, 2):
            for xx in range(x0, x1, 2):
                if cond(px(img, w, ch, xx, yy)):
                    found = True; break
            if found: break
        ok &= found
        print(f'   {label:20s} region({x0},{y0})-({x1},{y1}) {"PASS" if found else "FAIL"}')
    return ok

dark = lambda rgb: max(rgb) < 120
results.append(check_mark('concept A (spark)', 'migao/docs/design/logo-redesign/preview/concept-a-spark.svg.png', [
    ('gold center dot', (24, 24), (255, 197, 61), 30),
    ('white spoke', (24, 16), (255, 255, 255), 30),
    ('tile inside blue', (10, 10), (100, 135, 255), 80),
]))
results.append(check_mark('concept B (curtain)', 'migao/docs/design/logo-redesign/preview/concept-b-curtain.svg.png', [
    ('white M center peak', (24, 18), (255, 255, 255), 30),
    ('white M left leg', (11.5, 26), (255, 255, 255), 30),
    ('tile inside blue', (10, 10), (100, 135, 255), 80),
    ('rod area light', (24, 9.8), (150, 170, 240), 90),
]))
results.append(check_mark('concept C (AI star)', 'migao/docs/design/logo-redesign/preview/concept-c-ai-star.svg.png', [
    ('gold star center', (24, 8.4), (255, 197, 61), 40),
    ('white M center spire', (24, 17.5), (255, 255, 255), 40),
    ('white M left leg', (12.5, 26), (255, 255, 255), 40),
    ('tile inside blue', (10, 10), (100, 135, 255), 80),
]))

# lockups: 190x48 drawing scaled to 1024 wide, vertically centered on square canvas
s = 1024/190
y_off = (1024 - 48*s) / 2
def LP(sx, sy):
    return int(sx*s), int(y_off + sy*s)
for name, path, center_exp in [('lockup A', 'migao/docs/design/logo-redesign/preview/lockup-a.svg.png', (255, 197, 61)),
                               ('lockup B', 'migao/docs/design/logo-redesign/preview/lockup-b.svg.png', (255, 255, 255)),
                               ('lockup C', 'migao/docs/design/logo-redesign/preview/lockup-c.svg.png', (255, 197, 61))]:
    w, h, ch, img = decode_png(path)
    ok = True
    rgb = px(img, w, ch, *LP(10, 10))
    good = near(rgb, (100, 135, 255), 80)
    ok &= good
    print(f'== {name} ({w}x{h}), s={s:.3f}  tile blue px{LP(10,10)} rgb{rgb} {"PASS" if good else "FAIL"}')
    rgb = px(img, w, ch, *LP(24, 24 if name != "lockup C" else 8.4))
    good = near(rgb, center_exp, 45)
    ok &= good
    print(f'   mark center px{LP(24, 24)} rgb{rgb} expect~{center_exp} {"PASS" if good else "FAIL"}')
    # 米高 glyphs: dark pixels in svg(60..114, 4..27)
    x0, y0 = LP(60, 4); x1, y1 = LP(114, 27)
    found_zh = any(max(px(img, w, ch, xx, yy)) < 120
                   for yy in range(y0, y1+1, 2) for xx in range(x0, x1+1, 2))
    ok &= found_zh
    print(f'   米高 dark glyphs  region({x0},{y0})-({x1},{y1}) {"PASS" if found_zh else "FAIL"}')
    # MIGAO gray letterspaced: mid-gray pixels in svg(60..118, 29..42)
    x0, y0 = LP(60, 29); x1, y1 = LP(118, 42)
    found_en = any(100 <= px(img, w, ch, xx, yy)[0] <= 190
                   for yy in range(y0, y1+1, 2) for xx in range(x0, x1+1, 2))
    ok &= found_en
    print(f'   MIGAO gray letters  region({x0},{y0})-({x1},{y1}) {"PASS" if found_en else "FAIL"}')
    results.append(ok)

# overview: 1200x560 drawn at s=1024/1200 on 1024x1024 canvas, vertically centered
w, h, ch, img = decode_png('migao/docs/design/logo-redesign/preview/overview.svg.png')
s = 1024/1200
y_off = (1024 - 560*s) / 2
def OV(sx, sy):
    return int(sx*s), int(y_off + sy*s)
print(f'== overview ({w}x{h}), s={s:.4f}, y_off={y_off:.1f}')
checks = [
    ('A gold dot', OV(200, 130+24*2.2), (255, 197, 61), 40),
    ('A tile blue', OV(200, 130+10*2.2), (100, 135, 255), 80),
    ('B curtain white', OV(600, 130+24*2.2), (255, 255, 255), 40),
    ('B tile blue', OV(600, 130+10*2.2), (100, 135, 255), 80),
    ('C gold star', OV(1000, 130+8.4*2.2), (255, 197, 61), 40),
    ('C M spire white', OV(1000, 130+17.5*2.2), (255, 255, 255), 40),
    ('header dark text', OV(600, 44), (20, 20, 20), 80),
]
for label, (x, y), exp, tol in checks:
    rgb = px(img, w, ch, x, y)
    good = near(rgb, exp, tol)
    results.append(good)
    print(f'   {label:20s} px({x},{y}) rgb{rgb} expect~{exp} {"PASS" if good else "FAIL"}')

print('\nALL PASS' if all(results) else '\nSOME CHECKS FAILED')
sys.exit(0 if all(results) else 1)
