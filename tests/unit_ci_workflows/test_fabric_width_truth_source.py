"""门幅**真值源唯一**守卫（issue #4746）：前端不得自带一份引擎端点的硬编码门幅。

## 为什么需要这条（本单的静默失效形态）

门幅在仓里有**三处口径**（#4746 三处口径表，逐值读源见本文件判据）：

| 口径 | 值 | 来源 | 谁在读 |
|---|---|---|---|
| 商品/SKU 门幅（**权威**） | 商品可配（种子 2.8；窄幅布 1.4） | 商品 `doorWidths` ⇒ `product_skus.door_width` | 下单页判定 `resolveDoorWidth()`、SKU 定位 / 加工费组合键 |
| 前端**缺省**门幅 | 2.8 | 算料引擎默认门幅（`curtain_calc.build_quote(fabric_width: float = 2.8)`） | SKU 未携带门幅时的判定（逐值守卫在 `craft-auto-features.test.ts`） |
| 引擎**端点**门幅 | 3.2 | `backend/ai-agent-service/app/api/internal.py::_FABRIC_WIDTH`（**硬编码**，其注释「商家手工下单页当前没有门幅字段」**已过期**） | 商家手工下单页试算通路 |

⇒ 同一张单：前端按 SKU 门幅判「超宽/超高」（**进加工费组合键**），引擎按 3.2 算分幅
⇒ **可能不一致**（组合键匹配到的加工费与实际算料对不上）；提示文案里「引擎实际按哪种算」
也会**说错**。**权威 = SKU/商品门幅**；引擎侧改为**接收**该值是**分叉 #4652**
（本单不动 ai-agent）—— 所以这里钉住的是「前端**不抄**引擎那份硬编码」：
抄一份 = 前端又出现一个**会漂移的第二口径**（本仓 #4656 同族）。

## 判据（机械）

1. 前端门幅真值源模块 `lib/craft-auto-features.ts`（**去注释后**）不得出现引擎端点硬编码门幅值的
   **字面量** —— 值从 `internal.py::_FABRIC_WIDTH` 读出，**不写死**（引擎改了值，抄进前端即红）；
2. 门幅的**取值点唯一**：`detectAutoFeatures` / `detectAutoFeatureNotices`（lib）与下单页都必须经
   `resolveDoorWidth()` 取门幅（任一处再写一份门幅解析 ⇒ 红）。

## 红证（注入式，逐条可注入）

- 在 `craft-auto-features.ts` 里加 `const ENGINE_TRIAL_WIDTH = 3.2` ⇒ 判据 1 红；
- 把 `detectAutoFeatureNotices` 里的 `resolveDoorWidth(input.doorWidth)` 换成写死的 `2.8` ⇒ 判据 2 红。

⚠️ **本守卫不检查 ai-agent 侧**（分叉 #4652 未接线）—— 引擎端点何时改为**接收** SKU 门幅，
由 #4652 收口；届时前端把该值随试算请求发出（今天发 = 静默无效：`CraftCalcRequest` 里没有该键）。
"""

# case_ids: OR-040

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
INTERNAL_PY = REPO / "backend/ai-agent-service/app/api/internal.py"
LIB_TS = REPO / "frontend/admin-web/src/lib/craft-auto-features.ts"
PAGE_TSX = REPO / "frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx"


def _strip_comments(text: str) -> str:
    """去掉 `/* … */` 与 `// …` —— 判据只认**代码**里的字面量（注释里引用真值不算抄）。"""
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"//[^\n]*", "", text)


def _engine_endpoint_fabric_width() -> str:
    """引擎端点实际用的门幅（**真值从源里读**，本守卫不写死任何数字）。"""
    m = re.search(r"^_FABRIC_WIDTH\s*=\s*([0-9.]+)", INTERNAL_PY.read_text(encoding="utf8"), re.M)
    assert m, (
        "internal.py 里找不到 `_FABRIC_WIDTH`（引擎端点门幅的口径变了："
        "若 #4652 已接线为「接收 SKU 门幅」，请同步本守卫与 craft-auto-features.ts 的登记）"
    )
    return m.group(1)


def _exported_body(src: str, func_name: str) -> str:
    """取 `export function <func_name>(…) { … }` 的函数体（到下一个顶层 `export` 为止）。"""
    m = re.search(r"export function %s\(" % re.escape(func_name), src)
    assert m, f"craft-auto-features.ts 里找不到 {func_name}（本守卫必须能读到被测面）"
    rest = src[m.start():]
    nxt = re.search(r"\nexport (?:function|interface|const|type) ", rest)
    return rest[: nxt.start()] if nxt else rest


def test_frontend_does_not_copy_engine_endpoint_fabric_width():
    """判据 1：前端门幅面不得出现引擎端点硬编码门幅值的字面量（「不许在前端再写一个 3.2」）。"""
    value = _engine_endpoint_fabric_width()
    code = _strip_comments(LIB_TS.read_text(encoding="utf8"))
    hits = [m.start() for m in re.finditer(r"(?<![\w.])%s(?![\w.])" % re.escape(value), code)]
    assert not hits, (
        f"{LIB_TS.name} 里出现引擎端点硬编码门幅 {value} 的字面量（位置 {hits}）："
        "门幅的权威是 **SKU/商品门幅**（引擎侧接线 = 分叉 #4652）；前端再抄一份 = 第二份会漂移的口径"
        "（issue #4746 / 同族 #4656）。缺省口径请用 DEFAULT_DOOR_WIDTH（它逐值锚定算料引擎默认门幅）。"
    )


def test_door_width_has_single_value_source():
    """判据 2：门幅取值点唯一 —— 推导与提示都经 `resolveDoorWidth()`，页面不自解析门幅数值。"""
    lib = LIB_TS.read_text(encoding="utf8")
    for func_name in ("detectAutoFeatures", "detectAutoFeatureNotices"):
        body = _exported_body(lib, func_name)
        assert "resolveDoorWidth(" in body, (
            f"{func_name} 没有经 `resolveDoorWidth()` 取门幅 —— 门幅的第二份解析 = 与判定/提示脱钩"
            "（issue #4746：提示文案的前提句必须与判定**同源**）"
        )
    page = PAGE_TSX.read_text(encoding="utf8")
    assert "resolveDoorWidth(" in page, (
        "下单页没有经 `resolveDoorWidth()` 取门幅 —— 页面自行解析门幅数值 = 第二份口径"
        "（issue #4746）"
    )
