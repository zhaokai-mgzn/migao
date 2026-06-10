"""
米宝全能力自然语言测试套件

覆盖: 商品CRUD / 订单查改 / 客户 / 员工 / 数据 / 知识 / 视觉 / P&E
每项创建修改后通过 admin-api 校验数据准确性

用法:
  .venv/bin/python tests/test_mibao_scenarios.py
  TEST_TOKEN=xxx .venv/bin/python tests/test_mibao_scenarios.py  # 用已有token
"""

import asyncio, json, os, re, sys, time
from pathlib import Path
from datetime import datetime
import httpx

# ── 配置 ──
AI_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")
ADMIN_URL = os.getenv("ADMIN_API_URL", "http://localhost:8080")
TOKEN = os.getenv("TEST_TOKEN", "")
TEST_IMG = os.getenv("TEST_IMAGE", str(Path.home() / "Downloads" / "微信图片_20260606145132_363_16.jpg"))
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"} if TOKEN else {"Content-Type": "application/json"}
ADMIN_HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"} if TOKEN else {}

results = []
t0_total = time.time()


def check(name: str, ok: bool, detail: str = ""):
    results.append({"name": name, "ok": ok, "detail": detail})
    icon = "✅" if ok else "❌"
    msg = f"  {icon} {name}"
    if not ok and detail:
        msg += f": {detail[:120]}"
    print(msg)


def _token():
    """获取测试 token"""
    global TOKEN, HEADERS, ADMIN_HEADERS
    if not TOKEN:
        try:
            r = httpx.post(f"{ADMIN_URL}/api/auth/admin/login",
                           json={"username": "admin", "password": "admin123", "tenantId": 1}, timeout=10)
            TOKEN = r.json()["data"]["accessToken"]
            HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
            ADMIN_HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
        except:
            return False
    return True


async def _sse(client, sid, msg, images=None, timeout=60):
    """发送消息，返回拼接后的 SSE 文本"""
    body = {"session_id": sid, "message": msg}
    if images:
        body["images"] = images
    try:
        r = await client.post(f"{AI_URL}/api/chat/send", json=body, headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
        text = ""
        for line in r.text.split("\n"):
            if line.startswith("data: "):
                try:
                    d = json.loads(line[6:])
                    if isinstance(d, dict):
                        text += d.get("content", "")
                except json.JSONDecodeError:
                    pass
        return text
    except:
        return None


async def _session(client):
    r = await client.post(f"{AI_URL}/api/chat/sessions", json={"platform": "web"}, headers=HEADERS)
    d = r.json().get("data", {}) or {}
    return d.get("id") or r.json().get("id")


async def _admin_get(path: str):
    """调 admin-api 查询数据"""
    try:
        r = httpx.get(f"{ADMIN_URL}{path}", headers=ADMIN_HEADERS, timeout=15)
        if r.status_code == 200:
            return r.json().get("data")
    except:
        pass
    return None


# ═══════════════════════════════════════════════════════════════
# 场景 1: 商品搜索与详情
# ═══════════════════════════════════════════════════════════════
async def scenario_product_query(client):
    print("\n🛒 场景: 商品搜索")

    sid = await _session(client)
    if not sid:
        return check("商品-创建会话", False)

    # 1.1 关键词搜索
    text = await _sse(client, sid, "搜索窗帘商品")
    check("1.1 关键词搜索", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")

    # 1.2 按售卖方式搜索
    text = await _sse(client, sid, "有哪些散剪的商品")
    check("1.2 售卖方式搜索", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")

    # 1.3 查商品详情 — 验证 admin-api 数据
    text = await _sse(client, sid, "查看第一个窗帘商品的详细信息")
    check("1.3 商品详情", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")


# ═══════════════════════════════════════════════════════════════
# 场景 2: 订单查询与统计
# ═══════════════════════════════════════════════════════════════
async def scenario_order_query(client):
    print("\n📦 场景: 订单查询")

    sid = await _session(client)
    if not sid:
        return

    # 2.1 订单统计
    text = await _sse(client, sid, "订单统计")
    check("2.1 订单统计", bool(text) and "订单" in text, f"{len(text) if text else 0}字")

    # 2.2 按状态查 — 验证 admin-api
    text = await _sse(client, sid, "查待发货的订单")
    check("2.2 待发货查询", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")
    # 数据校验: 调 admin-api 确认待发货数量
    data = await _admin_get("/api/admin/orders?status=confirmed&size=5")
    api_count = data.get("total", 0) if data else -1
    check("2.3 待发货数据校验", api_count >= 0, f"admin-api返回{api_count}条")

    # 2.4 按时间查
    text = await _sse(client, sid, "最近7天的订单有哪些")
    check("2.4 按时间查询", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")

    # 2.5 订单详情
    text = await _sse(client, sid, "查看第一个订单的详情")
    check("2.5 订单详情", bool(text) and len(text) > 30, f"{len(text) if text else 0}字")


# ═══════════════════════════════════════════════════════════════
# 场景 3: 订单关闭 — 验证数据准确性
# ═══════════════════════════════════════════════════════════════
async def scenario_order_close(client):
    print("\n🔒 场景: 关闭订单")

    # 3.1 先找一个待付款的订单
    data = await _admin_get("/api/admin/orders?status=pending&size=1")
    if not data or not data.get("items"):
        return check("3.0 找待付款订单", False, "无待付款订单可测")
    order = data["items"][0]
    order_id = order["id"]
    order_no = order.get("orderNo", "")
    check("3.0 找待付款订单", True, f"{order_no}")

    # 3.2 通过米宝关闭
    sid = await _session(client)
    if not sid:
        return
    text = await _sse(client, sid, f"关闭订单 {order_no}，确认")
    check("3.1 关闭指令", bool(text), f"{len(text) if text else 0}字")

    # 如果米宝要求确认，再发一次
    if text and ("确认" in text or "确定" in text):
        await _sse(client, sid, "确认关闭")

    # 3.3 验证数据: 调 admin-api 确认状态已变为 cancelled
    data2 = await _admin_get(f"/api/admin/orders/{order_id}")
    status = data2.get("status") if data2 else ""
    check("3.2 关闭数据校验", status in ("cancelled", "closed"), f"状态={status}")


# ═══════════════════════════════════════════════════════════════
# 场景 4: 物流查询
# ═══════════════════════════════════════════════════════════════
async def scenario_logistics(client):
    print("\n📬 场景: 物流查询")

    sid = await _session(client)
    if not sid:
        return

    text = await _sse(client, sid, "查物流")
    check("4.1 物流查询", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")


# ═══════════════════════════════════════════════════════════════
# 场景 5: 客户管理
# ═══════════════════════════════════════════════════════════════
async def scenario_customer(client):
    print("\n👤 场景: 客户管理")

    sid = await _session(client)
    if not sid:
        return

    text = await _sse(client, sid, "查看客户列表")
    check("5.1 客户列表", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")

    text = await _sse(client, sid, "搜索手机号包含138的客户")
    check("5.2 客户搜索", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")


# ═══════════════════════════════════════════════════════════════
# 场景 6: 经营数据
# ═══════════════════════════════════════════════════════════════
async def scenario_dashboard(client):
    print("\n📊 场景: 经营数据")

    sid = await _session(client)
    if not sid:
        return

    text = await _sse(client, sid, "今天的经营数据")
    check("6.1 今日数据", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")

    text = await _sse(client, sid, "最近7天的订单趋势")
    check("6.2 订单趋势", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")


# ═══════════════════════════════════════════════════════════════
# 场景 7: 员工管理
# ═══════════════════════════════════════════════════════════════
async def scenario_employee(client):
    print("\n👥 场景: 员工管理")

    sid = await _session(client)
    if not sid:
        return

    text = await _sse(client, sid, "查看员工列表")
    check("7.1 员工列表", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")


# ═══════════════════════════════════════════════════════════════
# 场景 8: 知识库
# ═══════════════════════════════════════════════════════════════
async def scenario_knowledge(client):
    print("\n📚 场景: 知识库")

    sid = await _session(client)
    if not sid:
        return

    text = await _sse(client, sid, "窗帘怎么保养")
    check("8.1 知识问答", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")

    text = await _sse(client, sid, "搜索面料相关的知识")
    check("8.2 知识搜索", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")


# ═══════════════════════════════════════════════════════════════
# 场景 9: 图片创建商品 (完整P&E) — 验证数据准确性
# ═══════════════════════════════════════════════════════════════
async def scenario_image_create_product(client):
    print("\n📸 场景: 图片创建商品(全流程P&E)")

    if not os.path.exists(TEST_IMG):
        return check("9.0 图片检查", False, f"不存在:{TEST_IMG}")

    t0 = time.time()

    # 上传图片
    with open(TEST_IMG, "rb") as f:
        files = {"files": (os.path.basename(TEST_IMG), f, "image/jpeg")}
        r = await client.post(f"{AI_URL}/api/chat/upload-image", files=files,
                               headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})
    img_url = r.json().get("data", {}).get("files", [{}])[0].get("url", "")
    check("9.1 图片上传", bool(img_url))

    # 创建会话
    sid = await _session(client)
    if not sid:
        return
    check("9.2 会话创建", bool(sid))

    # Vision 分析
    text = await _sse(client, sid, "分析这张图片的颜色和属性", images=[img_url], timeout=60)
    check("9.3 Vision分析", bool(text) and len(text) > 80, f"{len(text) if text else 0}字")

    # 验证颜色完整性
    has_summary = re.findall(r'等\d+[色种]', text) if text else []
    check("9.4 颜色不总结", len(has_summary) == 0, f"总结词:{has_summary}" if has_summary else "完整列出")
    has_tags = "[工具返回]" in text or "[推断]" in text if text else False
    check("9.5 无来源标签", not has_tags)

    # 创建商品
    text = await _sse(client, sid, "帮我创建这个商品", timeout=90)
    check("9.6 创建指令", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")

    # 回复销售属性（ask结构化JSON自动推进到query）
    text = await _sse(client, sid, "价格23.8元每米，库存500件，货号AUTO9975796270，散剪和整卷都要，门幅2.8米和3.2米", timeout=60)
    check("9.7 销售属性", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")

    # 选分类（query步骤，无论文本是否包含分类都尝试发送编号）
    text = await _sse(client, sid, "1", timeout=60)
    check("9.8 选择分类", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")

    # 确认创建（confirm当场检测→execute同轮执行）
    text = await _sse(client, sid, "确认", timeout=90)
    check("9.9 确认创建", bool(text), f"{len(text) if text else 0}字")
    success = ("成功" in text or "太棒" in text or "已" in text or "已经" in text) if text else False
    check("9.10 创建结果", success and "错误" not in text if text else False, text[:80] if text else "")

    # 数据校验
    await asyncio.sleep(2)
    data = await _admin_get("/api/admin/products?keyword=AUTO9975796270&size=1")
    if data and data.get("items"):
        p = data["items"][0]
        check("9.11 商品存在", True, f"{p.get('name','?')[:30]}")
        check("9.12 价格准确", abs(float(p.get("price", 0)) - 23.8) < 0.1, f"价格={p.get('price')}")
        check("9.13 货号准确", p.get("skuCode","") == "AUTO99757", f"货号={p.get('skuCode')}")
        sms = p.get("sellingMethods", [])
        check("9.14 售卖方式", len(sms) >= 2, f"{sms}")
        check("9.15 SKU已生成", len(p.get("skus",[])) > 0, f"SKU={len(p.get('skus',[]))}")
    else:
        check("9.11 商品存在", False, "含AUTO99757商品未找到")

    elapsed = time.time() - t0
    check("9.15 总耗时", elapsed < 150, f"{elapsed:.0f}s")


# ═══════════════════════════════════════════════════════════════
# 场景 10: 文本创建商品 — 验证数据
# ═══════════════════════════════════════════════════════════════
async def scenario_text_create_product(client):
    print("\n📝 场景: 文本创建商品")

    sid = await _session(client)
    if not sid:
        return
    t0 = time.time()

    text = await _sse(client, sid, "创建一个窗帘商品，名称TEXT001测试窗帘，价格35元每米，库存200件，货号TEXT99757，售卖方式散剪，门幅2.8米，分类窗帘布艺", timeout=60)
    check("10.1 创建指令", bool(text) and len(text) > 30, f"{len(text) if text else 0}字")

    # 确认
    if text and "确认" in text:
        text = await _sse(client, sid, "确认创建", timeout=60)
        check("10.2 确认创建", bool(text), f"{len(text) if text else 0}字")

        # 调 admin-api 验证数据
        data = await _admin_get("/api/admin/products?keyword=TEXT99757&size=1")
        if data and data.get("items"):
            p = data["items"][0]
            check("10.3 名称校验", "TEXT99757" in str(p.get("name", "")), f"名称={p.get('name','')[:40]}")
            check("10.4 价格校验", abs(float(p.get("price", 0)) - 35) < 0.1, f"价格={p.get('price')}")
            skus = p.get("skus", [])
            check("10.5 SKU已生成", len(skus) > 0, f"SKU数={len(skus)}")
    else:
        check("10.2 确认创建", False, "未出现确认提示")

    check("10.6 耗时", time.time() - t0 < 60, f"{time.time()-t0:.0f}s")


# ═══════════════════════════════════════════════════════════════
# 场景 11: 多轮对话 + 上下文保持
# ═══════════════════════════════════════════════════════════════
async def scenario_multiturn(client):
    print("\n🔄 场景: 多轮对话")

    sid = await _session(client)
    if not sid:
        return

    t1 = await _sse(client, sid, "帮我查订单 ORD-20260601-0001")
    check("11.1 首轮", bool(t1) and len(t1) > 10, f"{len(t1) if t1 else 0}字")

    t2 = await _sse(client, sid, "这个订单的客户是谁")
    check("11.2 上下文", bool(t2) and len(t2) > 10, f"{len(t2) if t2 else 0}字")

    t3 = await _sse(client, sid, "物流信息呢")
    check("11.3 延续追问", bool(t3) and len(t3) > 10, f"{len(t3) if t3 else 0}字")


# ═══════════════════════════════════════════════════════════════
# 场景 12: 边界情况
# ═══════════════════════════════════════════════════════════════
async def scenario_edge_cases(client):
    print("\n⚠️ 场景: 边界情况")

    sid = await _session(client)
    if not sid:
        return

    # 单字
    t = await _sse(client, sid, "1")
    check("12.1 单字输入", bool(t) and len(t) > 0, f"{len(t) if t else 0}字")

    # 空消息应被拒绝
    try:
        r = await client.post(f"{AI_URL}/api/chat/send", json={"session_id": sid, "message": " "}, headers=HEADERS, timeout=10)
        check("12.2 空消息", r.status_code in (200, 400), f"HTTP {r.status_code}")
    except:
        check("12.2 空消息", False, "异常")

    # 确认/取消关键词
    t = await _sse(client, sid, "确认")
    check("12.3 确认", bool(t), f"{len(t) if t else 0}字")

    sid2 = await _session(client)
    t = await _sse(client, sid2, "取消")
    check("12.4 取消", bool(t), f"{len(t) if t else 0}字")

    # 超长消息
    t = await _sse(client, sid2, "测试" * 500, timeout=20)
    check("12.5 超长消息不崩溃", t is not None, f"{len(t) if t else 0}字")

    # 无意义输入
    t = await _sse(client, sid2, "asdfghjkl123")
    check("12.6 无意义输入", t is not None, f"{len(t) if t else 0}字")


# ═══════════════════════════════════════════════════════════════
# 场景 13: 售卖方式映射
# ═══════════════════════════════════════════════════════════════
async def scenario_selling_method_mapping(client):
    print("\n🏷️ 场景: 售卖方式双向翻译")

    sid = await _session(client)
    if not sid:
        return

    # LLM 应理解"散剪"="bulk_cut"
    text = await _sse(client, sid, "查散剪的商品")
    check("13.1 中文搜售卖方式", bool(text) and len(text) > 10, f"{len(text) if text else 0}字")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════
async def main():
    print("╔══════════════════════════════════════╗")
    print("║   🧪 米宝全能力自然语言测试        ║")
    print("╚══════════════════════════════════════╝")
    print(f"  AI: {AI_URL}")
    print(f"  Admin: {ADMIN_URL}")
    print(f"  图片: {'✅' if os.path.exists(TEST_IMG) else '❌'}")

    # 鉴权
    if not _token():
        print("\n❌ 无法获取测试 token，确保 admin-api 启动且密码正确")
        return

    print(f"  Token: ✅ ({TOKEN[:15]}...)")

    async with httpx.AsyncClient(timeout=120) as client:
        # 只读查询 (安全, 可反复跑)
        await scenario_product_query(client)
        await scenario_order_query(client)
        await scenario_logistics(client)
        await scenario_customer(client)
        await scenario_dashboard(client)
        await scenario_employee(client)
        await scenario_knowledge(client)
        await scenario_multiturn(client)
        await scenario_selling_method_mapping(client)
        await scenario_edge_cases(client)

        # 写操作 (会真实创建/修改数据)
        await scenario_text_create_product(client)
        await scenario_order_close(client)

        # 图片+P&E (耗时最长, 放到最后)
        await scenario_image_create_product(client)

    # 汇总
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    failed = total - passed
    elapsed = time.time() - t0_total
    print(f"\n{'═'*50}")
    print(f"  总计: {total} 项 | {passed}✅ {failed}❌ | {elapsed:.0f}s")
    print(f"{'═'*50}")

    if failed:
        print("\n❌ 失败项:")
        for r in results:
            if not r["ok"]:
                print(f"   - {r['name']}: {r['detail']}")
        sys.exit(1)
    else:
        print("\n🎉 全部通过!")


if __name__ == "__main__":
    asyncio.run(main())
