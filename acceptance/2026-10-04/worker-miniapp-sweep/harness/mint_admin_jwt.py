#!/usr/bin/env python3
"""线A harness 的 admin JWT 铸造器（RS256，私钥 = ~/migao-keys/jwt-private.pem）。

为什么需要它：admin-api:8080 的进程**没有** SMS_BYPASS_CODE（启动时未注入 .env ⇒
`grep -c "POC 模式" api.log = 0`），短信登录拿不到码；本线要建探针工人 / 调
`/api/admin/**` 读面 ⇒ 需要一条不依赖短信的凭证。

🔴 如实登记的边界（写进 REPORT §未覆盖）：
  - 这是**自铸 JWT**（与 :8001 JWT_PUBLIC_KEY 配对的那把私钥），**不是**短信/微信登录链
    （先例：acceptance/2026-10-03/agent-service-sweep/harness/mint_jwt.py）；
  - 只用于**管理员读面 + 建探针工人**；工人写面一律走真实 `POST /api/worker/login`（工号+PIN）。
  - admin-api 的权限判定不读 JWT 里的 permissions，而是 RoleService.getUserPermissions(userId)
    查库 ⇒ 铸出来的 token 能不能建工人，取决于 userId 在库里的真实权限（这本身就是一次真判据）。

用法：python3 mint_admin_jwt.py <userId> <tenantId> [username]
"""
import json
import os
import sys
from pathlib import Path

import jwt

uid, tenant = sys.argv[1], int(sys.argv[2])
username = sys.argv[3] if len(sys.argv) > 3 else "mint"
keyfile = os.environ.get("MIGAO_JWT_KEY", os.path.expanduser("~/migao-keys/jwt-private.pem"))
key = Path(keyfile).read_text()
claims = {
    "userId": uid, "tenantId": tenant, "username": username, "roles": ["admin"],
    "permissions": ["*"], "type": "access",
}
print(jwt.encode(claims, key, algorithm="RS256"))
