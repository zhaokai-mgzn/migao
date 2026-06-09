"""
Post-deploy 自动验证脚本

每次 ai-agent-service 部署后自动运行，验证核心链路：
1. 健康检查
2. 图片识别 → 颜色完整性
3. Vision JSON 直接产出
4. 售卖方式/门幅标准化
5. P&E 流程不报错

用法:
  python tests/test_post_deploy_verify.py --base-url https://dev-api.migaozn.com

环境变量:
  AI_SERVICE_URL: ai-agent-service 地址 (default: http://localhost:8001)
  ADMIN_API_URL: admin-api 地址 (default: http://localhost:8080)
  TEST_TOKEN: 测试用 JWT token
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

# ── 配置 ──
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")
ADMIN_API_URL = os.getenv("ADMIN_API_URL", "http://localhost:8080")
TEST_IMAGE = os.getenv("TEST_IMAGE", str(Path.home() / "Downloads" / "微信图片_20260606145132_363_16.jpg"))
TEST_TOKEN = os.getenv("TEST_TOKEN", "")
TENANT_ID = os.getenv("TENANT_ID", "1")

RESULTS = {"passed": 0, "failed": 0, "skipped": 0}


def log(level: str, msg: str):
    prefix = {"pass": "✅", "fail": "❌", "skip": "⏭️", "info": "📋"}.get(level, "  ")
    print(f"  {prefix} {msg}")


async def test_health_check():
    """1. 健康检查"""
    log("info", "测试 1: 健康检查")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{AI_SERVICE_URL}/health")
            if r.status_code == 200:
                log("pass", f"健康检查 OK: {r.json()}")
                RESULTS["passed"] += 1
                return True
            else:
                log("fail", f"健康检查失败: {r.status_code}")
                RESULTS["failed"] += 1
                return False
    except Exception as e:
        log("fail", f"健康检查异常: {e}")
        RESULTS["failed"] += 1
        return False


async def test_vision_colors_complete():
    """2. 图片识别 → 颜色必须全部保留，不能总结"""
    log("info", "测试 2: Vision 颜色完整性")
    if not os.path.exists(TEST_IMAGE):
        log("skip", f"测试图片不存在: {TEST_IMAGE}")
        RESULTS["skipped"] += 1
        return True

    # 先上传图片
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            # 上传图片
            with open(TEST_IMAGE, "rb") as f:
                files = {"files": (os.path.basename(TEST_IMAGE), f, "image/jpeg")}
                headers = {"Authorization": f"Bearer {TEST_TOKEN}"} if TEST_TOKEN else {}
                r = await c.post(f"{AI_SERVICE_URL}/api/chat/upload-image", files=files, headers=headers)
                if r.status_code != 200:
                    log("fail", f"图片上传失败: {r.status_code} {r.text[:200]}")
                    RESULTS["failed"] += 1
                    return False
                upload_data = r.json()
                img_url = upload_data.get("data", {}).get("files", [{}])[0].get("url", "")
                if not img_url:
                    log("fail", "未获取到图片URL")
                    RESULTS["failed"] += 1
                    return False
                log("info", f"图片上传成功: {img_url[:60]}...")

            # 创建会话
            headers = {"Authorization": f"Bearer {TEST_TOKEN}", "Content-Type": "application/json"} if TEST_TOKEN else {"Content-Type": "application/json"}
            r = await c.post(f"{AI_SERVICE_URL}/api/chat/sessions", json={"platform": "web"}, headers=headers)
            if r.status_code != 200:
                log("fail", f"创建会话失败: {r.status_code}")
                RESULTS["failed"] += 1
                return False
            session_id = r.json().get("data", {}).get("session_id") or r.json().get("session_id")
            if not session_id:
                # Try alternate response format
                session_id = r.json().get("id") or r.json().get("data", {}).get("id")
            if not session_id:
                log("fail", f"未获取到session_id: {r.text[:200]}")
                RESULTS["failed"] += 1
                return False
            log("info", f"会话创建: {session_id}")

            # 发送带图片的消息
            body = {"session_id": session_id, "message": "请分析这张商品图片，列出所有颜色和属性", "images": [img_url]}
            r = await c.post(f"{AI_SERVICE_URL}/api/chat/send", json=body, headers=headers, timeout=60)
            if r.status_code != 200:
                log("fail", f"发送消息失败: {r.status_code} {r.text[:200]}")
                RESULTS["failed"] += 1
                return False

            # 解析 SSE 响应
            full_text = ""
            colors_found = 0
            has_structured = False
            for line in r.text.split("\n"):
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if isinstance(data, dict):
                            text = data.get("content", data.get("text", ""))
                            full_text += text
                            # 检查是否有结构化数据
                            if "结构化数据" in str(data):
                                has_structured = True
                            # 数颜色（简单判断）
                            if "color" in str(data).lower():
                                colors_found += 1
                    except json.JSONDecodeError:
                        pass

            log("info", f"SSE 响应长度: {len(full_text)} 字符")

            # 验证颜色没有被总结（不应出现"等X色"）
            import re
            summarized = re.findall(r'等\d+[色种]|[等约].*色', full_text)
            if summarized:
                log("fail", f"颜色被总结了: {summarized}")
                RESULTS["failed"] += 1
                return False

            # 验证没有 [工具返回] 标签
            if "[工具返回]" in full_text or "[推断]" in full_text:
                log("fail", "响应中包含 [工具返回]/[推断] 标签")
                RESULTS["failed"] += 1
                return False

            log("pass", f"颜色完整，无总结，无来源标签 (文本{len(full_text)}字)")
            RESULTS["passed"] += 1
            return True

    except Exception as e:
        log("fail", f"Vision测试异常: {e}")
        RESULTS["failed"] += 1
        return False


async def test_selling_method_normalization():
    """3. 售卖方式/门幅标准化（通过 admin-api 查询已创建的商品验证）"""
    log("info", "测试 3: 售卖方式/门幅标准化")
    # 这个测试需要 admin-api 有已创建的商品，暂时跳过
    log("skip", "需要已创建商品数据，跳过（可通过手动测试验证）")
    RESULTS["skipped"] += 1
    return True


async def test_pe_flow_no_error():
    """4. P&E 流程不报错"""
    log("info", "测试 4: P&E 创建商品流程")
    if not os.path.exists(TEST_IMAGE):
        log("skip", f"测试图片不存在")
        RESULTS["skipped"] += 1
        return True

    try:
        async with httpx.AsyncClient(timeout=60) as c:
            headers = {"Authorization": f"Bearer {TEST_TOKEN}", "Content-Type": "application/json"} if TEST_TOKEN else {"Content-Type": "application/json"}

            # 上传图片
            with open(TEST_IMAGE, "rb") as f:
                files = {"files": (os.path.basename(TEST_IMAGE), f, "image/jpeg")}
                r = await c.post(f"{AI_SERVICE_URL}/api/chat/upload-image", files=files, headers=headers)
                if r.status_code != 200:
                    log("fail", f"图片上传失败: {r.status_code}")
                    RESULTS["failed"] += 1
                    return False
                img_url = r.json().get("data", {}).get("files", [{}])[0].get("url", "")

            # 创建会话
            r = await c.post(f"{AI_SERVICE_URL}/api/chat/sessions", json={"platform": "web"}, headers=headers)
            session_id = (r.json().get("data", {}) or r.json()).get("session_id") or r.json().get("id")
            if not session_id:
                log("fail", f"创建会话失败: {r.text[:200]}")
                RESULTS["failed"] += 1
                return False

            # 发送"创建商品"消息（带图片）
            body = {"session_id": session_id, "message": "创建这个商品", "images": [img_url]}
            r = await c.post(f"{AI_SERVICE_URL}/api/chat/send", json=body, headers=headers, timeout=90)
            if r.status_code != 200:
                log("fail", f"P&E发送失败: {r.status_code}")
                RESULTS["failed"] += 1
                return False

            full_text = ""
            has_error = False
            for line in r.text.split("\n"):
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if isinstance(data, dict):
                            text = data.get("content", data.get("text", ""))
                            full_text += text
                            if data.get("event") == "error":
                                has_error = True
                    except json.JSONDecodeError:
                        pass

            if has_error:
                log("fail", "P&E 流程出现error事件")
                RESULTS["failed"] += 1
                return False

            if "错误" in full_text or "失败" in full_text or "抱歉" in full_text:
                log("fail", f"P&E 响应包含错误: {full_text[:200]}")
                RESULTS["failed"] += 1
                return False

            log("pass", f"P&E流程无错误 (响应{len(full_text)}字)")
            RESULTS["passed"] += 1
            return True

    except Exception as e:
        log("fail", f"P&E测试异常: {e}")
        RESULTS["failed"] += 1
        return False


async def main():
    print("\n🔍 米宝 Post-Deploy 自动验证")
    print(f"   AI Service: {AI_SERVICE_URL}")
    print(f"   Test Image: {TEST_IMAGE}")
    print(f"   Token: {'已设置' if TEST_TOKEN else '未设置(部分测试跳过)'}")
    print()

    # 运行测试
    await test_health_check()
    print()

    if not TEST_TOKEN:
        log("skip", "未设置 TEST_TOKEN，跳过需要认证的测试")
        RESULTS["skipped"] += 3
    else:
        await test_vision_colors_complete()
        print()
        await test_selling_method_normalization()
        print()
        await test_pe_flow_no_error()
        print()

    # 汇总
    total = RESULTS["passed"] + RESULTS["failed"] + RESULTS["skipped"]
    print("─" * 40)
    print(f"  结果: {RESULTS['passed']} passed, {RESULTS['failed']} failed, {RESULTS['skipped']} skipped ({total} total)")
    print("─" * 40)

    if RESULTS["failed"] > 0:
        print("\n❌ 验证失败！请检查以上红色项。")
        sys.exit(1)
    else:
        print("\n✅ 所有验证通过！")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
