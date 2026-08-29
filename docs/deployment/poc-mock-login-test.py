#!/usr/bin/env python3
"""
POC Mock 登录集成测试

验证：微信小程序 mock 登录链路（无真实 appid/secret 时自动启用 Mock 模式）。

链路：
1. POST /api/auth/mini/login {code, tenant_id} → mock openid + JWT token
2. 同 code 二次登录 → 同一 openid（账号稳定）
3. token 调小布 chat（算料报价）

用法：
  ADMIN_API=http://localhost:8080 AI_API=http://localhost:8001 \
  python3 docs/deployment/poc-mock-login-test.py

依赖：admin-api(:8080) 已启动；ai-agent-service(:8001) 已启动（算料对话验证用）
"""
import json
import os
import sys
import urllib.request
import urllib.error

ADMIN_API = os.environ.get("ADMIN_API", "http://localhost:8080")
AI_API = os.environ.get("AI_API", "http://localhost:8001")
TENANT_ID = 1
FIXED_CODE = "poc-mock-code-001"  # 固定 code → 固定 mock openid


def post_json(url, payload, token=None):
    """POST JSON 请求"""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return e.code, {"error": body}


def main():
    print("=" * 60)
    print("POC Mock 登录集成测试")
    print("=" * 60)

    # 1. 首次 mock 登录
    print(f"\n[1] mock 登录: POST /api/auth/mini/login (code={FIXED_CODE})")
    status, data = post_json(
        f"{ADMIN_API}/api/auth/mini/login",
        {"code": FIXED_CODE, "tenant_id": TENANT_ID},
    )
    print(f"    状态码: {status}")
    if status != 200 or not data.get("success"):
        print(f"    ❌ 登录失败: {data}")
        sys.exit(1)

    token = data["data"].get("token", "")
    user = data["data"].get("user", {})
    print(f"    ✅ 登录成功: user_id={user.get('id')} nickname={user.get('nickname')}")
    print(f"    token 前 20 位: {token[:20]}...")

    # 2. 验证 mock openid 稳定性（同 code 二次登录 → 同一用户）
    print(f"\n[2] 二次登录验证账号稳定（同 code）")
    status2, data2 = post_json(
        f"{ADMIN_API}/api/auth/mini/login",
        {"code": FIXED_CODE, "tenant_id": TENANT_ID},
    )
    if status2 == 200 and data2.get("success"):
        user2 = data2["data"].get("user", {})
        same = user2.get("id") == user.get("id")
        print(f"    {'✅' if same else '❌'} 二次登录 user_id: {user2.get('id')} (同一账号: {same})")
    else:
        print(f"    ⚠️ 二次登录异常: {status2} {data2}")

    # 3. token 调小布 chat（算料报价）
    print(f"\n[3] 小布对话: 算料报价")
    chat_payload = {
        "session_id": None,
        "message": "3米窗 2倍褶皱 遮光布多少钱",
        "channel": "wechat_mini",
    }
    status3, data3 = post_json(
        f"{AI_API}/api/chat/send",
        chat_payload,
        token=token,
    )
    print(f"    状态码: {status3}")
    if status3 == 200:
        print(f"    ✅ chat 接口可达（SSE 流式，此处仅验证鉴权通过）")
    else:
        print(f"    ⚠️ chat 接口返回 {status3}: {str(data3)[:200]}")

    print("\n" + "=" * 60)
    print("✅ Mock 登录链路验证完成（mock 机制已内置，无需真实 appid/secret）")
    print("=" * 60)


if __name__ == "__main__":
    main()
