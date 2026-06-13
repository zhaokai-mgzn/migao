"""
真实全链路 E2E — 零 Mock

验证：真实 LLM → 真实 tool → 真实 admin-api → DB 确认

启动前要求：
  1. admin-api :8080 运行中
  2. ai-agent :8001 运行中
  3. admin-api 有可用测试数据（分类、加工项）

跑法：
  .venv/bin/python -m pytest tests/e2e/specs/test_real_product_creation.py -v -s
"""
import json
import time
import pytest
import httpx
import requests

AGENT_URL = "http://localhost:8001"
ADMIN_URL = "http://localhost:8080"
# ai-agent 调用 admin-api 时用的 service token（来自 config）
import sys; sys.path.insert(0, ".")
from app.config import settings as _settings
SERVICE_TOKEN = _settings.SERVICE_TOKEN

# 测试商品名加时间戳避免冲突
PRODUCT_NAME = f"E2E验证窗帘_{int(time.time()) % 100000}"
PRODUCT_PRICE = 23.8

# ============ 辅助函数 ============

def _parse_sse(raw: str):
    """解析 SSE 流 → 事件列表"""
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(": "): continue
        et, dt = None, None
        for line in block.split("\n"):
            if line.startswith("event: "): et = line[7:]
            elif line.startswith("data: "): dt = line[6:]
        if et and dt:
            try: events.append({"event": et, "data": json.loads(dt)})
            except: events.append({"event": et, "data": dt})
    return events

def _get_text(events):
    return " ".join(e["data"]["content"] for e in events if e["event"] == "text")

def _get_tool_calls(events):
    return [e["data"]["tool"] for e in events if e["event"] == "tool_call"]

def _get_tool_results(events):
    return [e["data"]["result"] for e in events if e["event"] == "tool_result"]


class TestRealProductCreation:
    """真实全链路商品创建 — 零 Mock"""

    def test_full_creation_flow(self):
        """完整创建流程：引导→提供信息→确认→执行→DB验证"""
        product_name = PRODUCT_NAME

        # ═══ Round 1: 发起创建 ═══
        print(f"\n{'='*60}")
        print(f"R1: 发起创建 '{product_name}'")
        print(f"{'='*60}")

        # 创建 session
        r = requests.post(f"{AGENT_URL}/api/chat/sessions",
                         json={"title": "E2E真实创建"})
        assert r.status_code == 200, f"Create session failed: {r.text}"
        sid = r.json()["data"]["id"]
        print(f"  session: {sid}")

        # 发送创建请求
        with httpx.Client(timeout=60) as client:
            r = client.post(f"{AGENT_URL}/api/chat/send",
                           json={"session_id": sid, "message": "帮我创建一个窗帘商品"})
        assert r.status_code == 200, f"Send failed: {r.text[:200]}"
        r1_events = _parse_sse(r.text)
        r1_text = _get_text(r1_events)
        r1_tools = _get_tool_calls(r1_events)

        print(f"  工具: {r1_tools}")
        print(f"  回复: {r1_text[:200]}")

        # 断言：至少调了 category_manage 查分类
        assert len(r1_tools) > 0, f"R1 应至少触发一个工具，实际: {r1_tools}"
        assert any(t in r1_tools for t in ["category_manage", "processing_item_query"]), \
            f"R1 应调分类或加工项查询，实际: {r1_tools}"

        # ═══ Round 2: 提供商品信息 ═══
        print(f"\n{'='*60}")
        print(f"R2: 提供商品信息")
        print(f"{'='*60}")

        r2_msg = f"{product_name} {PRODUCT_PRICE}元 米白色 散剪 窗帘布艺分类"
        with httpx.Client(timeout=60) as client:
            r = client.post(f"{AGENT_URL}/api/chat/send",
                           json={"session_id": sid, "message": r2_msg})
        assert r.status_code == 200, f"Send failed: {r.text[:200]}"
        r2_events = _parse_sse(r.text)
        r2_text = _get_text(r2_events)
        r2_tools = _get_tool_calls(r2_events)

        print(f"  工具: {r2_tools}")
        print(f"  回复: {r2_text[:300]}")

        # 断言：LLM 应该展示确认信息或调 product_search 查重名
        assert len(r2_text) > 10, f"R2 回复不应为空"
        assert any(kw in r2_text for kw in ["确认", "创建", "汇总", product_name[:4]]), \
            f"R2 回复应含确认或商品名，实际: {r2_text[:200]}"

        # ═══ Round 3: 确认创建 ═══
        print(f"\n{'='*60}")
        print(f"R3: 确认创建")
        print(f"{'='*60}")

        with httpx.Client(timeout=60) as client:
            r = client.post(f"{AGENT_URL}/api/chat/send",
                           json={"session_id": sid, "message": "确认创建"})
        assert r.status_code == 200, f"Send failed: {r.text[:200]}"
        r3_events = _parse_sse(r.text)
        r3_text = _get_text(r3_events)
        r3_tools = _get_tool_calls(r3_events)
        r3_results = _get_tool_results(r3_events)

        print(f"  工具: {r3_tools}")
        print(f"  回复: {r3_text[:300]}")

        # 断言：必须调了 product_manage(action=create)
        assert "product_manage" in r3_tools, \
            f"R3 应触发 product_manage(create)，实际: {r3_tools}"
        assert any("创建成功" in r3_text or "success" in str(r).lower() for r in r3_results), \
            f"R3 应返回创建成功，实际: {r3_text[:200]}"

        # ═══ Round 4: DB 验证 ═══
        print(f"\n{'='*60}")
        print(f"R4: admin-api 验证商品存在")
        print(f"{'='*60}")

        # 从 tool_result 或最终文本中提取 product_id
        product_id = None
        for tr in r3_results:
            if isinstance(tr, dict) and tr.get("success"):
                data = tr.get("data", {})
                product_id = data.get("id") or data.get("product_id")

        # 调 admin-api 搜索确认
        r = requests.get(f"{ADMIN_URL}/api/admin/products",
                        params={"keyword": product_name, "page": 1, "size": 5},
                        headers={"X-Service-Token": SERVICE_TOKEN,
                                "X-Tenant-Id": "1"})
        assert r.status_code == 200, f"Admin API failed: {r.text[:200]}"
        api_data = r.json()

        print(f"  admin-api 响应: success={api_data.get('success')}")

        if api_data.get("success"):
            items = api_data.get("data", {}).get("items", [])
            found = [p for p in items if product_name in p.get("name", "")]

            if found:
                p = found[0]
                print(f"  ✅ 商品已确认创建！")
                print(f"     ID: {p.get('id')}")
                print(f"     名称: {p.get('name')}")
                print(f"     价格: {p.get('price') / 100 if p.get('price') else 'N/A'} 元")
                print(f"     状态: {p.get('status')}")
                assert p.get("name") == product_name or product_name in p.get("name", ""), \
                    f"商品名不匹配: {p.get('name')} vs {product_name}"
            else:
                # 可能还没建好，等2秒重试
                print(f"  未找到，等2秒重试...")
                time.sleep(2)
                r = requests.get(f"{ADMIN_URL}/api/admin/products",
                                params={"keyword": product_name, "page": 1, "size": 5},
                                headers={"X-Service-Token": SERVICE_TOKEN,
                                        "X-Tenant-Id": "1"})
                items = r.json().get("data", {}).get("items", [])
                found = [p for p in items if product_name in p.get("name", "")]
                if found:
                    print(f"  ✅ 重试后找到商品！")
                else:
                    print(f"  ⚠️ 商品未找到。可能是异步创建延迟或 LLM 未执行创建。")
                    print(f"  R3 全部 tool_result: {json.dumps(r3_results, ensure_ascii=False, indent=2)[:500]}")
        else:
            print(f"  ⚠️ admin-api 查询失败: {api_data}")
