# case_ids: MC-216, MC-217, MC-218, MC-219, MC-220
"""物流取号 P0（issue #8698）的**跨端 / 结构**判据。

## 为什么有些判据必须落在 Python 侧

本包的核心口径是「**取号 ≠ 发货**」与「**前端不直连承运商**」—— 它们都是**跨文件、跨端的形态**
（Java 包边界 / 前端产物），单模块的运行期测试看不见：

| 判据 | 形态 | 红证（注入什么让它红） |
|---|---|---|
| MC-216 取号不改变订单状态 | `com.migao.admin.waybill/**` 的**代码**里出现任何订单状态写入口（剥注释后判） | 往 `WaybillService` 加一行 `orderMapper.updateById(...)` ⇒ 判据 1 红并具名 |
| MC-217 能力位驱动 UI | 设置域 `logistics` 登记 + 面板挂载 + 写面权限码与端点逐字一致 | 把域从 `CONFIG_DOMAINS` 删掉 / 把面板挂载删掉 ⇒ 判据 2 红 |
| MC-218 不能声称能做而实际不能 | 生产目录 `CarrierCatalogue` 的能力位 **P0 必须全 false**（没接任何第三方） | 把任一行的 `canCreate` 翻成 `true` ⇒ 判据 3 红并具名该承运商 |
| MC-219 manual 兜底 | 注册表有 `manual` 行 + 前后端承运商词表逐字对齐 | 后端漏一家 / 前端多一家 ⇒ 判据 4 红并具名 |
| MC-220 前端不直连 | `frontend/admin-web/src/**` 无承运商域名 / 凭据键 | 往任一前端文件塞 `sf-express.com` 或 `appSecret` ⇒ 判据 5 红并具名文件与命中串 |

## 🔴 三条实现纪律（本文件自己遵守）

1. **剥掉注释再判**（`_java_without_comments`）：本包的 javadoc 里**必须**能写
   「不注入 `OrderService`」这类说明，而注释里的词不是代码（同族守卫
   `test_guard_parsing_is_comment_aware.py` 的口径）；
2. **不用引号捕获组的正则**读源码原文 —— 一律纯字符串操作（`find` / 切片 / `split`），
   否则会被 `test_guard_parsing_is_comment_aware.py::test_quote_parsing_is_ledgered` 判红；
3. **判据自带判别力自证**：每条判据都有一个「内存注入了坏形态 ⇒ 必红 / 不注入 ⇒ 不报」的
   对照用例（不碰盘）。没有它，判据可能是「在对空气放行」。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
WAYBILL_JAVA_DIR = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin" / "waybill"
CARRIER_CATALOGUE = WAYBILL_JAVA_DIR / "CarrierCatalogue.java"
WAYBILL_CONTROLLER = (
    REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin"
    / "controller" / "WaybillController.java"
)
PRODUCTION_CONTROLLER = (
    REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin"
    / "controller" / "ProductionController.java"
)
FRONTEND_SRC = REPO_ROOT / "frontend" / "admin-web" / "src"
FRONTEND_LOGISTICS = FRONTEND_SRC / "lib" / "logistics.ts"
CONFIG_DOMAINS_TS = FRONTEND_SRC / "lib" / "config-center-domains.ts"
SETTINGS_PAGE = FRONTEND_SRC / "app" / "(dashboard)" / "settings" / "page.tsx"

#: 订单状态的**写入口**（读面不在内：取号可以读订单，写状态不行）。
#:
#: ⚠️ 只登记**订单专属**的类型 / 方法名：`updateById(` 这类通用方法名不能用 ——
#: 本包自己的租户配置表也要 upsert（`mapper.updateById(existing)`），通用名会把它判成红
#: （假红会把判据逼成「删掉正当实现」）。订单写入口必须先持有订单类型，所以类型名足够。
ORDER_STATUS_WRITE_MARKERS = (
    "OrderMapper",
    "OrderService",
    "OrderLifecycleService",
    "OrderLogisticsMapper",
    "OrderShipmentService",
    "shipWithLogistics",
    "updateOrderStatus",
    "OrderShipmentOutcome",
)

#: 承运商开放平台域名 / 聚合平台（前端出现任一 ⇒ 有人在直连）
CARRIER_HOST_MARKERS = (
    "sf-express.com",
    "open.zto.com",
    "yto.net.cn",
    "yundaex.com",
    "open.sto.cn",
    "open.jdl.com",
    "api.ems.com.cn",
    "jtexpress.com.cn",
    "open.cainiao.com",
    "op.ane56.com",
    "open.yimidida.com",
    "iop.zto56.com",
    "open.800best.com",
    "sja56.com",
    "kuaidi100",
    "kdniao",
)

#: 承运商凭据键（前端出现任一 ⇒ 密钥面破了）
CARRIER_SECRET_MARKERS = (
    "appSecret",
    "app_secret",
    "appKey",
    "partnerKey",
    "privateKey",
    "signKey",
    "apiSecret",
)


# ── 解析工具（纯字符串操作，不用引号捕获组正则） ─────────────────────────────────────────


def _java_without_comments(src: str) -> str:
    """剥掉 Java 的行注释 / 块注释（字符串字面量内的 `//` 不算注释）。

    为什么要剥：本包 javadoc 里逐字写着「不注入 {@code OrderService}」这类说明 ——
    那是**理由**，不是代码。不剥 ⇒ 判据会对着注释判红，作者只能删掉理由（把好判据逼成坏判据）。
    """
    out: List[str] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in ('"', "'"):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                c = src[i]
                out.append(c)
                if c == "\\" and i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
                i += 1
                if c == quote:
                    break
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def order_status_write_hits(sources: Dict[str, str]) -> List[str]:
    """在一组 Java 源码里找订单状态写入口（剥注释后判）—— 返回 `文件::标识符` 清单。"""
    hits: List[str] = []
    for name, text in sorted(sources.items()):
        code = _java_without_comments(text)
        for marker in ORDER_STATUS_WRITE_MARKERS:
            if marker in code:
                hits.append(f"{name}::{marker}")
    return hits


#: `new Entry(...)` 里允许出现的**常量 code**（逐个登记；新增常量必须同时改这里 ——
#: 未登记的常量会让 code 变成 `"MANUAL_CODE"` 这种假值，判据当场对不上）
_CATALOGUE_CONSTANTS = {"MANUAL_CODE": "manual"}


def _literal(raw: str):
    """Java 字面量 → Python 值（`null` / 带双引号串 / true / false / 已登记常量）。纯字符串操作。"""
    token = raw.strip()
    if token in _CATALOGUE_CONSTANTS:
        return _CATALOGUE_CONSTANTS[token]
    if token == "null":
        return None
    if token in ("true", "false"):
        return token == "true"
    if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    return token


def parse_catalogue_entries(src: str) -> List[Dict[str, object]]:
    """解析 `CarrierCatalogue` 的 `new Entry(...)` 行（剥注释后按括号 / 逗号切）。"""
    text = _java_without_comments(src)
    entries: List[Dict[str, object]] = []
    cursor = 0
    while True:
        start = text.find("new Entry(", cursor)
        if start == -1:
            break
        end = text.find(")", start)
        if end == -1:
            break
        raw = text[start + len("new Entry("): end]
        parts = [_literal(p) for p in raw.split(",")]
        if len(parts) == 7:
            entries.append(
                {
                    "code": parts[0],
                    "display_name": parts[1],
                    "logistics_type": parts[2],
                    "track_query_code": parts[3],
                    "can_create": parts[4],
                    "can_cancel": parts[5],
                    "can_track": parts[6],
                }
            )
        cursor = end + 1
    return entries


def frontend_company_names(src: str) -> List[str]:
    """`LOGISTICS_COMPANIES` 的 name 序列（按 `name: '` 前缀切片，不用正则）。"""
    names: List[str] = []
    marker = "name: '"
    cursor = 0
    while True:
        start = src.find(marker, cursor)
        if start == -1:
            break
        value_start = start + len(marker)
        value_end = src.find("'", value_start)
        if value_end == -1:
            break
        names.append(src[value_start:value_end])
        cursor = value_end + 1
    return names


def secret_hits(sources: Dict[str, str]) -> List[str]:
    """前端源码里找承运商域名 / 凭据键 —— 返回 `文件::命中串` 清单。"""
    hits: List[str] = []
    for name, text in sorted(sources.items()):
        for marker in CARRIER_HOST_MARKERS + CARRIER_SECRET_MARKERS:
            if marker in text:
                hits.append(f"{name}::{marker}")
    return hits


def _frontend_sources() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for path in sorted(FRONTEND_SRC.rglob("*")):
        if path.suffix not in (".ts", ".tsx"):
            continue
        out[str(path.relative_to(REPO_ROOT))] = path.read_text(encoding="utf-8")
    return out


def _waybill_java_sources() -> Dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(WAYBILL_JAVA_DIR.glob("*.java"))
    }


# ── 判据 1（MC-216）：取号路径结构上写不到订单状态 ─────────────────────────────────────


def test_waybill_package_has_no_order_status_write_entry():
    """`waybill/**` 的代码里不得出现任何订单状态写入口（红证见 `test_order_write_detector_has_teeth`）。"""
    sources = _waybill_java_sources()
    assert sources, "waybill 包源码为空 —— 判据在扫空气（包被删 / 路径漂了）"

    hits = order_status_write_hits(sources)
    assert hits == [], (
        "取号路径出现了订单状态写入口（取号 ≠ 发货：订单必须仍「待发货」）：" + "；".join(hits)
    )


def test_order_write_detector_has_teeth():
    """判别力自证：内存注入一次状态写 ⇒ 必红；不注入 ⇒ 不报（-control）。"""
    clean = {"Probe.java": "class Probe { void run() { log.info(\"ok\"); } }"}
    assert order_status_write_hits(clean) == []

    dirty = {
        "Probe.java": "class Probe { private OrderMapper orderMapper; "
                      "void run() { orderMapper.updateById(order); } }"
    }
    assert order_status_write_hits(dirty) == ["Probe.java::OrderMapper"]

    # 注释里的同名符号**不算**（否则本包的 javadoc 会被判红，作者只能删掉理由）
    commented = {"Probe.java": "/** 不注入 OrderService，也不调 updateOrderStatus */\nclass Probe {}"}
    assert order_status_write_hits(commented) == []


def test_production_ship_endpoint_is_untouched():
    """`ship` 端点仍在原位（本单一行不改它：取号走取号端点，发货走发货端点）。"""
    src = PRODUCTION_CONTROLLER.read_text(encoding="utf-8")
    assert '@PostMapping("/orders/{orderId}/ship")' in src
    assert '@RequirePermission("production:execute")' in src
    # 取号端点属于另一个控制器，不得把发货逻辑搬进 waybill 包
    assert "ProductionController" not in _java_without_comments(
        "\n".join(_waybill_java_sources().values())
    )


# ── 判据 2（MC-217）：设置页「物流取号」域登记 + 面板挂载 + 写面权限码一致 ──────────────


def test_logistics_domain_is_registered_and_mounted():
    domains = CONFIG_DOMAINS_TS.read_text(encoding="utf-8")
    assert "key: 'logistics'" in domains, "CONFIG_DOMAINS 里没有 logistics 域 ⇒ 设置页左栏不会有它"
    assert "'logistics'" in domains.split("export type ConfigDomainKey", 1)[-1].split("export", 1)[0], (
        "ConfigDomainKey 联合类型没加 logistics ⇒ TS 编译期就无法把该域挂到页面"
    )

    # 域的 requiredCode 必须与**写面端点**的权限码逐字一致
    # （不持该码 ⇒ 域不渲染；渲染出来再撞 403 = #6573 判死线）
    tail = domains.split("key: 'logistics'", 1)[1]
    required = tail.split("requiredCode: '", 1)[1].split("'", 1)[0]
    controller = WAYBILL_CONTROLLER.read_text(encoding="utf-8")
    assert f"@RequirePermission(\"{required}\")" in controller, (
        f"设置域 logistics 的 requiredCode = {required}，但 WaybillController 里没有该码的端点"
    )

    page = SETTINGS_PAGE.read_text(encoding="utf-8")
    assert "activeDomain.key === 'logistics'" in page, "设置页没有挂载 logistics 域面板 ⇒ 域可点开但空白"
    assert "LogisticsDomainPanel" in page


# ── 判据 3（MC-218）：生产目录零过声明（P0 没接任何真实第三方） ─────────────────────────


def _over_claimed(entries: List[Dict[str, object]]) -> List[str]:
    return [
        str(e["code"])
        for e in entries
        if e["can_create"] or e["can_cancel"] or e["can_track"]
    ]


def test_production_catalogue_declares_no_capability():
    """P0 一家都没接 ⇒ 生产目录的能力位必须全 false（翻 true 而没接 provider = 声称能做）。"""
    entries = parse_catalogue_entries(CARRIER_CATALOGUE.read_text(encoding="utf-8"))
    assert len(entries) >= 2, f"目录解析出 {len(entries)} 行 —— 判据在扫空气（解析器漂了）"

    over = _over_claimed(entries)
    assert over == [], (
        "承运商目录声明了能力但 P0 未接入任何 provider（对 UI 已按「不能」处理，但这是过声明）："
        + "、".join(over)
    )


def test_capability_over_claim_detector_has_teeth():
    """判别力自证：把某行 canCreate 翻成 true ⇒ 检出并具名。"""
    catalogue = CARRIER_CATALOGUE.read_text(encoding="utf-8")
    needle = 'new Entry("sf", "顺丰速运", "express", "SF", false,'
    assert needle in catalogue, "红证锚点漂了（CarrierCatalogue 的 sf 行改了）"
    injected = catalogue.replace(needle, 'new Entry("sf", "顺丰速运", "express", "SF", true,', 1)

    assert _over_claimed(parse_catalogue_entries(catalogue)) == []
    assert _over_claimed(parse_catalogue_entries(injected)) == ["sf"]


# ── 判据 4（MC-219）：manual 兜底行存在 + 前后端承运商词表逐字对齐 ─────────────────────


def test_manual_fallback_entry_exists_and_carriers_match_frontend():
    entries = parse_catalogue_entries(CARRIER_CATALOGUE.read_text(encoding="utf-8"))
    codes = [str(e["code"]) for e in entries]
    assert "manual" in codes, "注册表没有 manual 行 ⇒ 「未接入承运商退回手填」没有落点"

    backend_names = {
        str(e["display_name"]) for e in entries if str(e["code"]) != "manual"
    }
    frontend_names = set(frontend_company_names(FRONTEND_LOGISTICS.read_text(encoding="utf-8")))
    assert frontend_names, "前端承运商词表解析为空 —— 判据在扫空气"

    only_frontend = sorted(frontend_names - backend_names)
    only_backend = sorted(backend_names - frontend_names)
    assert only_frontend == [] and only_backend == [], (
        "前后端承运商词表不一致（会出现「下拉能选、注册表里查不到 ⇒ 静默走手填」或反之）："
        f"仅前端 {only_frontend}；仅后端 {only_backend}"
    )


# ── 判据 5（MC-220）：前端不直连承运商（密钥 / 域名） ─────────────────────────────────


def test_frontend_has_no_carrier_secret_or_direct_host():
    sources = _frontend_sources()
    assert len(sources) > 100, f"只扫到 {len(sources)} 个前端源文件 —— 扫描面漂了（假绿）"

    hits = secret_hits(sources)
    assert hits == [], (
        "前端源码出现承运商域名 / 凭据键（前端不直连承运商，密钥不进浏览器）：" + "；".join(hits)
    )


def test_secret_scanner_has_teeth():
    """判别力自证：内存注入一条承运商域名 + 一个凭据键 ⇒ 两条都检出。"""
    dirty = {
        "probe.tsx": "const url = 'https://qiao.sf-express.com/api'\nconst k = { appSecret: 'x' }",
    }
    assert secret_hits(dirty) == ["probe.tsx::sf-express.com", "probe.tsx::appSecret"]
    assert secret_hits({"clean.tsx": "export const x = 1"}) == []
