#!/usr/bin/env python3
"""线① harness 的 JWT 铸造器（PyJWT + 与 :8001 的 JWT_PUBLIC_KEY 配对的私钥）。

为什么不用 Node 侧 openssl 拼签名：实测 openssl dgst base64url 拼出的签名被
PyJWT 自身验签判 InvalidSignatureError（同样的输入用 PyJWT 签就通过）⇒ 拼装细节
不可靠。改用唯一事实源（PyJWT）铸造，避免"工装自己错、却把被测系统判红"的假红。

用法：echo '<claims-json>' | python3 mint_jwt.py [keyfile]
输出：一行 JWT
"""
import json
import os
import sys
from pathlib import Path

import jwt

claims = json.loads(sys.stdin.read() or "{}")
keyfile = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/migao-keys/jwt-private.pem")
if keyfile == "-":
    # 现场生成一把「另一把」RSA 私钥（异钥签名夹具用，不落盘）
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
else:
    key = Path(keyfile).read_text()

print(jwt.encode(claims, key, algorithm="RS256"))
