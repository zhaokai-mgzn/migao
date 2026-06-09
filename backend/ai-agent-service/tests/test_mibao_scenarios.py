"""
米宝能力自动化测试

覆盖核心场景，每次部署后自动跑，发现问题自动修复。
用法: .venv/bin/python tests/test_mibao_scenarios.py
环境变量:
  AI_SERVICE_URL: 默认 http://localhost:8001
  TEST_TOKEN: 测试用 JWT (无则跳过需认证的场景)
  TEST_IMAGE: 测试图片路径
"""

import asyncio, json, os, re, sys, time, traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import httpx

# ── 配置 ──
AI_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")
TOKEN = os.getenv("TEST_TOKEN", "")
TEST_IMG = os.getenv("TEST_IMAGE", str(Path.home() / "Downloads" / "微信图片_20260606145132_363_16.jpg"))
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"} if TOKEN else {"Content-Type": "application/json"}


@dataclass
class Result:
    name: str
    passed: bool = False
    detail: str = ""
    duration: float = 0


results: list[Result] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    results.append(Result(name=name, passed=condition, detail=detail))
    icon = "✅" if condition else "❌"
    print(f"  {icon} {name}" + (f": {detail}" if not condition and detail else ""))
    return condition


# ═══════════════════════════════════════════════════════
# 测试场景
# ═══════════════════════════════════════════════════════

async def _send_msg(client, sid, msg, images=None, timeout=60):
    """发送消息并返回SSE文本"""
    body = {"session_id": sid, "message": msg}
    if images:
        body["images"] = images
    r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=timeout)
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    return _read_sse(r.text), None


async def _create_session(client):
    """创建会话，返回session_id"""
    r = await client.post(f"{AI_URL}/api/chat/sessions", json={"platform": "web"}, headers=HEADERS)
    data = r.json()
    # 兼容多种响应格式: data.id, data.session_id, id
    d = data.get("data", {}) or {}
    sid = d.get("id") or d.get("session_id") or data.get("id") or data.get("session_id")
    return sid


async def scenario_image_to_product(client: httpx.AsyncClient):
    """场景: 完整图片创建商品流程 (多轮P&E)"""
    print("\n📸 场景: 完整图片创建商品")

    if not TOKEN:
        return check("完整创建流程", False, "无TOKEN")
    if not os.path.exists(TEST_IMG):
        return check("完整创建流程", False, f"图片不存在: {TEST_IMG}")

    t_total = time.time()

    # Step 1: 上传图片
    with open(TEST_IMG, "rb") as f:
        files = {"files": (os.path.basename(TEST_IMG), f, "image/jpeg")}
        r = await client.post(f"{AI_URL}/api/chat/upload-image", files=files,
                               headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})
    if r.status_code != 200:
        return check("①图片上传", False, f"HTTP {r.status_code}")
    img_url = r.json().get("data", {}).get("files", [{}])[0].get("url", "")
    check("①图片上传", bool(img_url))

    # Step 2: 创建会话
    sid = await _create_session(client)
    if not sid:
        return check("②会话创建", False)
    check("②会话创建", True)

    # Step 3: 先让Vision分析图片(不带创建指令), 再发创建指令
    text, err = await _send_msg(client, sid, "分析这张图片", images=[img_url], timeout=60)
    if err:
        return check("③Vision分析", False, err)
    check("③Vision分析", len(text) > 50, f"{len(text)}字")

    # Step 3b: 发送创建指令（Vision结果已在上下文）
    text, err = await _send_msg(client, sid, "创建这个商品", timeout=90)
    if err:
        return check("④创建指令", False, err)
    elapsed = time.time() - t_total
    check("④创建指令", len(text) > 20, f"{len(text)}字 {elapsed:.1f}s")

    # 验证 Vision 质量
    has_colors = "颜色" in text or "色" in text
    no_tags = "[工具返回]" not in text and "[推断]" not in text
    no_summary = not re.findall(r'等\d+[色种]', text)
    check("⑤颜色完整", has_colors and no_summary, "包含颜色且未总结" if has_colors and no_summary else "颜色丢失或被总结")

    # Step 4: 回复销售属性
    text, err = await _send_msg(client, sid, "价格23.8元每米，库存1000件，货号TEST001，售卖方式散剪和整卷都要，门幅2.8米和3.2米", timeout=60)
    if err:
        return check("⑥销售属性", False, err)
    check("⑥销售属性", len(text) > 10, f"{len(text)}字")

    # Step 5: 选择分类 (回复编号1)
    if "分类" in text or "编号" in text:
        text, err = await _send_msg(client, sid, "1", timeout=60)
        if err:
            return check("⑦选择分类", False, err)
        check("⑦选择分类", len(text) > 10, f"{len(text)}字")
    else:
        check("⑦选择分类", False, "未出现分类选择提示")

    # Step 6: 确认创建
    if "确认" in text or "创建" in text:
        text, err = await _send_msg(client, sid, "确认，创建商品", timeout=60)
        if err:
            return check("⑧确认创建", False, err)
        success = "成功" in text or "创建" in text or "已" in text
        check("⑧确认创建", success and "错误" not in text, f"{len(text)}字")
    else:
        check("⑧确认创建", False, "未出现确认提示")

    total_elapsed = time.time() - t_total
    check("⑨总耗时", total_elapsed < 120, f"{total_elapsed:.0f}s")

    # 验证: 响应时间合理
    check("响应速度", elapsed < 30, f"{elapsed:.1f}s")


async def scenario_product_create_text(client: httpx.AsyncClient):
    """场景: 纯文本创建商品 → 验证P&E流程"""
    print("\n📝 场景: 文本创建商品")

    if not TOKEN:
        return check("文本创建商品", False, "无TOKEN")

    t0 = time.time()
    r = await client.post(f"{AI_URL}/api/chat/sessions", json={"platform": "web"}, headers=HEADERS)
    sid = (r.json().get("data", {}) or r.json()).get("session_id") or r.json().get("id")

    body = {"session_id": sid, "message": "创建一个窗帘商品，名称'测试窗帘'，价格28元/米，货号TEST001，分类窗帘布艺"}
    r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=60)
    text = _read_sse(r.text)
    elapsed = time.time() - t0

    check("P&E触发", "售卖方式" in text or "门幅" in text or "价格" in text or "分类" in text,
          f"响应{len(text)}字, {elapsed:.1f}s")
    check("无错误", "错误" not in text and "抱歉" not in text, text[:100] if "错误" in text else "")
    check("文本响应速度", elapsed < 25, f"{elapsed:.1f}s")


async def scenario_order_query(client: httpx.AsyncClient):
    """场景: 订单查询"""
    print("\n🔍 场景: 订单查询")

    if not TOKEN:
        return check("订单查询", False, "无TOKEN")

    r = await client.post(f"{AI_URL}/api/chat/sessions", json={"platform": "web"}, headers=HEADERS)
    sid = (r.json().get("data", {}) or r.json()).get("session_id") or r.json().get("id")

    for query, desc in [
        ("查一下最近7天的订单", "按时间查订单"),
        ("有哪些待发货的订单", "按状态查订单"),
        ("今天的订单有多少", "订单统计"),
    ]:
        body = {"session_id": sid, "message": query}
        r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=30)
        text = _read_sse(r.text)
        check(desc, "错误" not in text and "抱歉" not in text, f"{len(text)}字")


async def scenario_product_search(client: httpx.AsyncClient):
    """场景: 商品搜索"""
    print("\n🛒 场景: 商品搜索")

    if not TOKEN:
        return check("商品搜索", False, "无TOKEN")

    r = await client.post(f"{AI_URL}/api/chat/sessions", json={"platform": "web"}, headers=HEADERS)
    sid = (r.json().get("data", {}) or r.json()).get("session_id") or r.json().get("id")

    queries = [
        ("搜索窗帘商品", "关键词搜索"),
        ("查看第一个商品的详情", "查看详情"),
        ("有哪些散剪的商品", "售卖方式搜索"),
    ]
    for query, desc in queries:
        body = {"session_id": sid, "message": query}
        r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=30)
        text = _read_sse(r.text)
        check(desc, len(text) > 20 and "错误" not in text, f"{len(text)}字")


async def scenario_multiturn_context(client: httpx.AsyncClient):
    """场景: 多轮对话上下文保持"""
    print("\n🔄 场景: 多轮对话")

    if not TOKEN:
        return check("多轮对话", False, "无TOKEN")

    r = await client.post(f"{AI_URL}/api/chat/sessions", json={"platform": "web"}, headers=HEADERS)
    sid = (r.json().get("data", {}) or r.json()).get("session_id") or r.json().get("id")

    # Turn 1
    body = {"session_id": sid, "message": "帮我查一下订单 ORD-20260601-0001"}
    r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=30)
    t1 = _read_sse(r.text)
    check("第1轮", len(t1) > 10, f"{len(t1)}字")

    # Turn 2 - 省略主语，靠上下文
    body = {"session_id": sid, "message": "这个订单的客户是谁"}
    r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=30)
    t2 = _read_sse(r.text)
    check("第2轮上下文", len(t2) > 10, f"{len(t2)}字")

    # Turn 3
    body = {"session_id": sid, "message": "物流状态呢"}
    r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=30)
    t3 = _read_sse(r.text)
    check("第3轮上下文", len(t3) > 10, f"{len(t3)}字")


async def scenario_edge_cases(client: httpx.AsyncClient):
    """场景: 边界情况"""
    print("\n⚠️ 场景: 边界情况")

    if not TOKEN:
        return check("边界测试", False, "无TOKEN")

    r = await client.post(f"{AI_URL}/api/chat/sessions", json={"platform": "web"}, headers=HEADERS)
    sid = (r.json().get("data", {}) or r.json()).get("session_id") or r.json().get("id")

    # 单字回复
    body = {"session_id": sid, "message": "1"}
    r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=20)
    text = _read_sse(r.text)
    check("单字输入", len(text) > 0, f"{len(text)}字")

    # 空消息
    body = {"session_id": sid, "message": " "}
    r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=20)
    text = _read_sse(r.text)
    check("空消息不崩溃", r.status_code in (200, 400), f"HTTP {r.status_code}")

    # 超长消息
    body = {"session_id": sid, "message": "测试" * 500}
    r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=30)
    text = _read_sse(r.text)
    check("超长消息", r.status_code in (200, 400), f"HTTP {r.status_code}")

    # 确认/取消
    body = {"session_id": sid, "message": "确认"}
    r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=20)
    text = _read_sse(r.text)
    check("确认关键词", len(text) > 0, f"{len(text)}字")

    body = {"session_id": sid, "message": "取消"}
    r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=20)
    text = _read_sse(r.text)
    check("取消关键词", len(text) > 0, f"{len(text)}字")


# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════

def _read_sse(raw: str) -> str:
    """解析SSE响应拼接文本"""
    text = ""
    for line in raw.split("\n"):
        if line.startswith("data: "):
            try:
                d = json.loads(line[6:])
                if isinstance(d, dict):
                    text += d.get("content", d.get("text", ""))
            except json.JSONDecodeError:
                pass
    return text


# ═══════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════

async def main():
    print("╔══════════════════════════════════╗")
    print("║    🧪 米宝能力自动化测试        ║")
    print("╚══════════════════════════════════╝")
    print(f"  服务: {AI_URL}")
    print(f"  图片: {TEST_IMG if os.path.exists(TEST_IMG) else '未找到'}")
    print(f"  Token: {'已设置' if TOKEN else '未设置(仅健康检查)'}")

    # 健康检查（不需要token）
    print("\n🏥 基础检查")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{AI_URL}/health")
            check("健康检查", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as e:
        check("健康检查", False, str(e))
        print("\n❌ 服务不可用，终止测试")
        return _summary()

    if not TOKEN:
        print("\n⚠️ 未设置 TEST_TOKEN，跳过分业务场景测试")
        print("  export TEST_TOKEN='your-jwt-token'")
        return _summary()

    async with httpx.AsyncClient(timeout=90) as client:
        # 按风险等级排序
        await scenario_image_to_product(client)
        await scenario_product_create_text(client)
        await scenario_order_query(client)
        await scenario_product_search(client)
        await scenario_multiturn_context(client)
        await scenario_edge_cases(client)

    _summary()


def _summary():
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    print(f"\n{'═'*40}")
    print(f"  总计: {len(results)} 项 → {passed}✅ {failed}❌")
    print(f"{'═'*40}")

    if failed:
        print("\n❌ 失败项:")
        for r in results:
            if not r.passed:
                print(f"   - {r.name}: {r.detail}")
        sys.exit(1)
    else:
        print("\n🎉 全部通过！")


if __name__ == "__main__":
    asyncio.run(main())
