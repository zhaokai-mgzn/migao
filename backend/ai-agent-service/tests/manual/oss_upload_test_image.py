"""上传一张测试图到云 dev OSS，产出真实用户图片形态的 URL（vision 模型可抓取）。

凭证从环境变量或 backend/ai-agent-service/.env 读取（禁止硬编码 AK/SK）。
用法: python oss_upload_test_image.py [output_key]
输出: 打印 OSS 公开 URL
"""
# case_ids: CH-021, CH-026
import base64
import hashlib
import hmac
import os
import struct
import sys
import zlib
import datetime
import urllib.request
from pathlib import Path

ENDPOINT = "oss-cn-hangzhou.aliyuncs.com"
BUCKET = "ai-customer-service-admin-dev"
KEY = sys.argv[1] if len(sys.argv) > 1 else "vision-acceptance/curtain-fabric-1.png"


def _load_credential(name):
    val = os.environ.get(name)
    if val:
        return val
    env_path = Path(__file__).resolve().parents[2] / ".env"  # backend/ai-agent-service/.env
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            k, _, v = line.partition("=")
            if k == name:
                return v.strip()
    raise SystemExit(f"缺少凭证 {name}（设置环境变量或在 backend/ai-agent-service/.env 提供）")


AK = _load_credential("OSS_ACCESS_KEY_ID")
SK = _load_credential("OSS_ACCESS_KEY_SECRET")


def make_png(width=600, height=400):
    """纯 stdlib 生成一张渐变窗帘纹理 PNG"""
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter type 0
        for x in range(width):
            r = (x * 255 // width) % 220 + 20
            g = (y * 255 // height) % 200 + 30
            b = 140 + (x // 60) % 2 * 60  # 竖条纹 → 像窗帘褶皱
            rows += bytes((r, g, b))
    raw = bytes(rows)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return png


def _ssl_ctx():
    """优先用 certifi 根证书，避免 homebrew python 缺 CA 时的 CERTIFICATE_VERIFY_FAILED"""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def oss_sign(method, date, content_type, resource):
    string_to_sign = f"{method}\n\n{content_type}\n{date}\n{resource}"
    sig = base64.b64encode(hmac.new(SK.encode(), string_to_sign.encode(), hashlib.sha1).digest())
    return sig.decode()


def main():
    png = make_png()
    content_type = "image/png"
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    resource = f"/{BUCKET}/{KEY}"
    path = f"https://{BUCKET}.{ENDPOINT}/{urllib.request.quote(KEY, safe='/')}"
    bg = _ssl_ctx()
    auth = f"OSS {AK}:{oss_sign('PUT', date, content_type, resource)}"
    req = urllib.request.Request(path, data=png, method="PUT")
    req.add_header("Authorization", auth)
    req.add_header("Date", date)
    req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=30, context=bg) as r:
        print(f"uploaded status={r.status}")
    print(f"URL={path}")
    # 校验匿名读
    with urllib.request.urlopen(path, timeout=15, context=bg) as r:
        print(f"anonymous GET status={r.status} bytes={len(r.read())}")


if __name__ == "__main__":
    main()