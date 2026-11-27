# case_ids: PR-004
"""PR-004 的**同源等价**判据：`product_detail` 与 `inventory_manage(action=query)` 是同一份库存事实。

## 立案理由（issue #9280，run 46002922920）

PR-004 的期望原来是写死的 `inventory_manage(action=query)`，而模型改走
`product_search + product_detail` 后回了同样的数（1000.0 米）却被判红。**改期望之前必须先证等价**
（否则就是"跑分不好看就把断言放宽"）。本文件把"等价"从一句注释变成机器判据 —— 三个面：

| # | 判据 | 红的意义 |
|---|---|---|
| 1 | 两条路线打的是**同一个 admin-api 端点**（`/api/admin/products/{id}`） | 换了端点 ⇒ 「同源」不再成立，期望必须收回 |
| 2 | 两侧的库存数字都由 `stock_semantics.product_stock_summary()` 从 **SKU 明细**现算，且都**不**直读商品级 `data["stock"]` | 有人让某一路改读派生冗余列 ⇒ 两条路线数字会分叉 |
| 3 | 用例的合格集**恰好**是这两条（且 `inventory_manage` 只许 `action=query`） | 放宽被扩到**非同源**路线（`batch_stock_query` 批次余量 / `low_stock_alert` 阈值清单）⇒ 当场红 |

判据 3 是「防以后随便放宽」的机械闸门：本单只允许放宽到**同源**路线，其余一律留在集外。

## 旁证（为什么不选"让模型必须走 inventory_manage"，即修 prompt 那条路）

两者取数**逐字相同**：`product_detail` 的 `f"/api/admin/products/{resolved_id}"` 与
`inventory_manage._query_inventory` 的 `f"/api/admin/products/{product_id}"` 是同一端点，
拿到 `data["skus"]` 后都走 `product_stock_summary()`（`STOCK_AUTHORITY = "sku"`，
产物 `stock_source = "sku_sum"`）。库存真值是 SKU 级（商品级 `products.stock` 是派生冗余列，
实测 311/497 与 SKU 汇总不一致）⇒ 模型走 detail 并没有绕过口径，`product_detail` 反而多给了
逐 SKU 拆分。**结论：修 prompt 去禁一条等价路线只会增加噪声**（下一次它换个角度又问一遍）。
"""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools"

PRODUCT_DETAIL = TOOLS_DIR / "product_detail.py"
INVENTORY_MANAGE = TOOLS_DIR / "inventory_manage.py"
STOCK_SEMANTICS = TOOLS_DIR / "stock_semantics.py"
PRODUCT_CASES = REPO_ROOT / ".github" / "cases" / "product.yml"

#: 「商品库存」的 admin-api 读面（两条路线必须逐字相同）。
PRODUCT_READ_PATH = '"/api/admin/products/{'

#: 同源聚合函数（商品库存数字的**唯一**入口，见 `stock_semantics.py` 模块 docstring）。
STOCK_AGGREGATOR = "product_stock_summary("

#: 直读后端**商品级** `data["stock"]` 的形态（派生冗余列，任何工具都不许采信）。
_PRODUCT_LEVEL_STOCK_RE = re.compile(
    r"""data\s*(?:\.get\(\s*["']stock["']|\[\s*["']stock["']\s*\])""")


def _code_only(path: Path) -> str:
    """源码去掉 `#` 注释行（注释里会**引用**禁忌形态 —— 例如 product_detail 的
    「不复用后端商品级 `data["stock"]`」，文本扫描会把"说明禁忌"读成"犯了禁忌"）。"""
    return "\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines()
                     if not ln.lstrip().startswith("#"))


def test_both_routes_hit_the_same_admin_api_endpoint():
    """判据 1：同源的第一条 —— 同一个端点（不是"另一个库存接口"）。"""
    for path in (PRODUCT_DETAIL, INVENTORY_MANAGE):
        assert PRODUCT_READ_PATH in _code_only(path), (
            f"{path.name} 不再调用 {PRODUCT_READ_PATH}… ⇒ PR-004 的「两条路线同源」前提失效，"
            "期望必须收回成单一路线（别让放宽活过它的事实基础）")


def test_both_routes_derive_stock_from_sku_details_only():
    """判据 2：两侧库存都走 `product_stock_summary()`（SKU 级权威），都不直读商品级列。"""
    for path in (PRODUCT_DETAIL, INVENTORY_MANAGE):
        code = _code_only(path)
        assert STOCK_AGGREGATOR in code, (
            f"{path.name} 不再用 {STOCK_AGGREGATOR}…) 取库存 ⇒ 商品库存口径分叉（#4038 的唯一入口）")
        assert _PRODUCT_LEVEL_STOCK_RE.search(code) is None, (
            f"{path.name} 直读了后端**商品级** `data[\"stock\"]`（派生冗余列，实测 311/497 与 "
            "SKU 汇总不一致）⇒ 该路线的数字与 SKU 汇总是两回事，PR-004 不能再把两者当等价")

    semantics = _code_only(STOCK_SEMANTICS)
    assert 'STOCK_AUTHORITY = "sku"' in semantics
    assert "sku_sum" in semantics


def _pr004_case() -> dict:
    doc = yaml.safe_load(PRODUCT_CASES.read_text(encoding="utf-8"))
    return next(c for c in doc["cases"] if c["id"] == "PR-004")


def _branches(expectation: object) -> list:
    raw = str(expectation.get("tool") or "") if isinstance(expectation, dict) else str(expectation)
    return [p.strip() for p in re.split(r"\s+or\s+", raw, flags=re.IGNORECASE) if p.strip()]


def test_case_accepts_exactly_the_two_same_source_routes():
    """判据 3：合格集**恰好**是这两条同源路线（多一条/少一条都红）。

    这是「不许随便放宽」的机械闸门：`batch_stock_query`（批次余量/省料分布）与
    `inventory_manage(action=low_stock_alert)`（阈值 ≤100 的 SKU 清单）都**不是**
    「该商品 SKU 库存合计」，一律留在集外。
    """
    case = _pr004_case()
    branches = _branches(case["expectations"][0])
    assert branches == ["product_detail", "inventory_manage(action=query)"], (
        f"PR-004 的合格路线被改了：{branches} —— 只允许「同源」两条，"
        "新增路线必须先证明它与 SKU 库存合计同源（本文件判据 1+2）")
    assert case["data_checks"] == ["库存数量 = SUM(SKU 库存)（两条合格路线都由 product_stock_summary 现算，见上）"]
