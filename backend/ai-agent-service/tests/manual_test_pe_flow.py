"""
手动测试：图片创建商品全链路 P&E 流程
用法: .venv/bin/python tests/manual_test_pe_flow.py
"""
import asyncio, httpx, json

BASE = "http://localhost:8001"
CHAT = f"{BASE}/api/chat/send"
UPLOAD = f"{BASE}/api/chat/upload-image"
H = {}  # DEBUG 模式免 token

async def send(sid, msg, imgs=None):
    """发送消息，返回 (text, tools, new_sid)"""
    body = {"message": msg}
    if sid:
        body["session_id"] = sid
    if imgs:
        body["images"] = imgs
    text, tools, new_sid = "", [], sid
    async with httpx.AsyncClient(timeout=180) as c:
        async with c.stream("POST", CHAT, json=body, headers=H) as r:
            if r.status_code != 200:
                raw = await r.aread()
                print(f"  ERROR {r.status_code}: {raw[:300]}")
                return text, tools, sid
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    d = json.loads(line[6:])
                except:
                    continue
                if "content" in d:
                    text += d.get("content", "")
                if d.get("tool"):
                    tools.append(d["tool"])
                # done 事件包含 session_id
                if d.get("session_id"):
                    new_sid = d["session_id"]
    return text, tools, new_sid


async def main():
    # 1. 上传图片
    img = "/Users/zhaokai/Downloads/微信图片_20260606145132_363_16.jpg"
    async with httpx.AsyncClient(timeout=30) as c:
        with open(img, "rb") as f:
            r = await c.post(UPLOAD, files={"files": ("test.jpg", f, "image/jpeg")})
        img_url = r.json()["data"]["files"][0]["url"]
    print(f"[1] 图片上传: {img_url[:80]}...")

    # 2. Turn 1: 图片 + "帮我创建商品"（不传 session_id，自动创建）
    t1, tools1, sid = await send("", "帮我创建这个商品", [img_url])
    print(f"[2] Turn 1: {t1[:200]}...")
    print(f"    Tools: {tools1}")

    # 3. Turn 2: 回复商品信息（模拟用户填了 form）
    t2, tools2, sid = await send(sid, "商品名称：色卡样本册，价格：199元，描述：高端布艺色卡展示册")
    print(f"\n[3] Turn 2: {t2[:300]}...")
    print(f"    Tools: {tools2}")

    # 4. Turn 3: 选分类
    t3, tools3, sid = await send(sid, "选第一个")
    print(f"\n[4] Turn 3: {t3[:300]}...")
    print(f"    Tools: {tools3}")

    # 5. 汇总
    all_tools = tools1 + tools2 + tools3
    all_text = t1 + t2 + t3
    print(f"\n{'='*60}")
    print(f"总工具调用: {all_tools}")
    print(f"product_manage: {'product_manage' in all_tools}")
    print(f"category_manage: {'category_manage' in all_tools}")
    if "product_manage" in all_tools:
        print("✅ 商品创建成功！")
    elif any("抱歉" in t or "错误" in t or "无法" in t for t in [t1, t2, t3]):
        print("❌ 出现错误，检查：")
        for i, t in enumerate([t1, t2, t3], 1):
            if "抱歉" in t or "错误" in t:
                print(f"  Turn {i}: {t[:200]}")
    else:
        print("⚠️ 未完成，可能需要更多回合")

if __name__ == "__main__":
    asyncio.run(main())
