# case_ids: PR-010, PR-011, OR-014
"""商品**改价复位**必须真的生效、且失败必须可见（issue #3807）。

## 为什么需要这条守卫（病灶）

`restore_product()`（评测的数据隔离：写类用例跑完把商品改回原样）曾经发：

```python
await c.patch(f"{ADMIN_API}/api/admin/agent/products/{pid}", json={"price": price})
```

而 admin-api 的接收端 DTO `AgentProductUpdateRequest` **只有 `basePrice`**
（`ProductResponse.getPrice()` 只是 `return basePrice` 的只读派生）：
Jackson 忽略未知属性 → `basePrice = null`（= 不修改）→ **`hasUpdate=false` → 直接返回当前商品
（HTTP 200 + success）**。

⇒ 复位**静默空转**，而且**只看 status_code 抓不到**（返回 200）。实证：种子「遮光窗帘」
¥168 被 `PR-010`（「把价格改成 198」）改掉后，此后全场读到 **198**，两次判定跑独立复现
（顺序依赖 / 幽灵 delta 来源）。

## 本文件锁三条

1. 请求体字段名 = **`basePrice`**（对齐后端 DTO，而不是"看着像"的 `price`）；
2. 复位后**回读校验**：写不进去（含"字段名没人认"这种 200 假成功）⇒ 必须报
   `PRECONDITION_NOT_RESTORED`，不许静默；
3. 复位失败**进结论**：`completion_verdict` 单列 `restore_failures` 并阻塞（fail-closed）。

## 红证（自带，不依赖真实服务）

| 断言 | 红证 |
|---|---|
| ①②③ | 把 `lr.PRODUCT_PRICE_FIELD` 换回旧值 `"price"`（= 修前形态）⇒ `test_regression_*` 转红：无回读校验时"2xx 但价格没变"完全不可见，正是本单的病灶本体 |

（用模块常量而不是复制一份实现：翻转常量就是"退回修前代码"，因此这条红证不会随着
实现演进而失效。）
"""
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner_product_restore", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")


class _FakeProducts:
    """最小商品服务桩：只认 `basePrice`（**与后端 DTO 同契约**）。

    故意**忽略未知字段**（Jackson 的默认行为）—— 这正是"发 `price` 也能拿到 200"的原因，
    也是"只查 status_code 抓不到"的原因。桩必须复刻这个语义，否则红证是假的。
    """

    def __init__(self, price=168.0, pid="prod_eval_blackout", patch_status=200):
        self.price = float(price)
        self.pid = pid
        self.patch_status = patch_status
        self.patch_bodies = []
        self.get_calls = 0

    def item(self):
        return {"id": self.pid, "name": "遮光窗帘", "basePrice": self.price,
                "price": self.price}

    def _client(self, server):
        class _C:
            async def __aenter__(self_):
                return self_

            async def __aexit__(self_, *a):
                return False

            async def get(self_, url, headers=None, params=None, timeout=None):
                server.get_calls += 1
                return _Resp(200, {"data": {"items": [server.item()]}})

            async def patch(self_, url, headers=None, json=None, timeout=None):
                server.patch_bodies.append(json)
                if server.patch_status >= 300:
                    return _Resp(server.patch_status, {"error": "boom"})
                # 契约：只有 `basePrice` 会被写；未知字段被忽略（= 静默 no-op）
                if "basePrice" in (json or {}):
                    server.price = float(json["basePrice"])
                return _Resp(200, {"data": server.item()})

        return _C


def _patch_client(monkeypatch, server):
    monkeypatch.setattr(lr.httpx, "AsyncClient", server._client(server))


async def _snapshot(server, monkeypatch):
    _patch_client(monkeypatch, server)
    return await lr.snapshot_product("tok", "遮光窗帘")


async def test_restore_sends_basePrice_and_verifies_by_readback(monkeypatch):
    """正例：种子 168 → 某用例改成 198 → 复位 ⇒ 请求体是 basePrice、读回已是种子值。"""
    server = _FakeProducts(price=168.0)
    pid = await _snapshot(server, monkeypatch)
    assert pid == server.pid
    server.price = 198.0                       # 模拟 PR-010「把价格改成 198」
    msg = await lr.restore_product("tok", pid)
    assert server.patch_bodies == [{"basePrice": 168.0}], (
        f"复位请求体不是 basePrice（后端 DTO 只认它）：{server.patch_bodies} —— "
        f"发 price 会被 Jackson 忽略 ⇒ 静默空转")
    assert server.price == 168.0, "复位没有真的写回"
    assert msg.startswith("✅"), f"复位成功却没给出可见结果：{msg!r}"


async def test_restore_is_visible_when_readback_still_mismatched(monkeypatch):
    """② 回读不符 ⇒ 必须报 `PRECONDITION_NOT_RESTORED`（不许静默）。

    红证：把字段名换回旧值（= 修前代码）⇒ 本用例转红 —— 旧实现"2xx 但价格没变"完全不可见。
    """
    monkeypatch.setattr(lr, "PRODUCT_PRICE_FIELD", "price")
    server = _FakeProducts(price=168.0)
    pid = await _snapshot(server, monkeypatch)
    server.price = 198.0
    msg = await lr.restore_product("tok", pid)
    assert server.price == 198.0, "桩应当忽略未知字段 price（复刻 Jackson 语义）"
    assert msg.startswith("PRECONDITION_NOT_RESTORED"), (
        f"复位空转必须可见（旧实现发 price → 200 → 静默）：{msg!r}")


async def test_restore_visible_on_http_error(monkeypatch):
    """① 非 2xx ⇒ 同样必须可见（不许"失败没人看"）。"""
    server = _FakeProducts(price=168.0, patch_status=500)
    pid = await _snapshot(server, monkeypatch)
    msg = await lr.restore_product("tok", pid)
    assert msg.startswith("PRECONDITION_NOT_RESTORED"), msg
    assert "500" in msg


async def test_snapshot_prefers_basePrice_authoritative_key(monkeypatch):
    """快照取值必须取**写路径的权威字段** `basePrice`（不是只读派生 `price`）。"""
    server = _FakeProducts(price=168.0)
    _patch_client(monkeypatch, server)
    # 让两个键不一致（模拟 getPrice() 将来语义漂移），权威值必须赢
    orig_item = server.item

    def _item_with_divergent_price():
        it = orig_item()
        it["basePrice"] = 168.0
        it["price"] = 999.0
        return it

    server.item = _item_with_divergent_price
    pid = await lr.snapshot_product("tok", "遮光窗帘")
    assert lr._saved_states[pid][lr.PRODUCT_PRICE_FIELD] == 168.0, lr._saved_states[pid]


async def test_missing_snapshot_price_is_visible(monkeypatch):
    """没有快照价格时也必须出声（否则"以为复位了"）。"""
    server = _FakeProducts(price=168.0)
    _patch_client(monkeypatch, server)
    lr._saved_states[server.pid] = {"basePrice": None, "name": "遮光窗帘"}
    msg = await lr.restore_product("tok", server.pid)
    assert msg.startswith("PRECONDITION_NOT_RESTORED"), msg


def test_restore_failure_enters_the_verdict():
    """③ 复位失败**进结论**：单列 `restore_failures` 并让 ok=False（fail-closed）。"""
    ok_case = {"case_id": "PR-010", "score": 1.0, "classification": "pass",
               "restore": ["✅ 价格已复位：商品 prod_eva → 168.0（回读一致）"]}
    bad_case = {"case_id": "PR-011", "score": 1.0, "classification": "pass",
                "restore": ["PRECONDITION_NOT_RESTORED: 价格复位未生效 —— 商品 prod_eva 回读 198.0"]}
    v1 = lr.completion_verdict([ok_case], ())
    assert v1["ok"] is True and v1["restore_failures"] == []
    v2 = lr.completion_verdict([ok_case, bad_case], ())
    assert v2["ok"] is False, "复位失败没有阻塞结论 —— 『前置未复位』又一次静默了"
    assert v2["restore_failures"] == ["PR-011"], v2
    assert "前置未复位" in v2["reason"], v2["reason"]
