# case_ids: OR-040
"""自动特征判定端点的**跨语言契约**守卫（issue #5009 = #4976 包 2b）。

## 病根（本条的来历）

前端 `craftCalcApi.autoFeatures` 的 URL 字面量 ↔ Java `AutoFeaturesController` 的
`@RequestMapping` 是**跨语言契约**，而它此前**没有任何判据** ⇒ 改路径时**文档/用例会静默说谎**。
实测（本单起草期）：代码写对了，而 `orders/new/page.tsx` 注释、`craft-auto-features.ts` 文件头、
`.github/cases/order.yml`（3 处）、`docs/wiki/CONTRACT-LEDGER.md` **全写着一条不存在的路径**
（`/api/admin/orders/craft-calc/auto-features`）—— 照着它调会 **404**，而用例库/契约账本是
**行为真值源**，写错就是真值腐烂（§19.2 ③ 同族）。人工 grep 才发现 ⇒ 必须机械化。

## 判据（全部**读源**，不硬编码「另一份路径表」）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | 前端 URL 字面量 == Java `@RequestMapping`（逐字，含 `/api` 前缀） | 任一侧改成别的路径 ⇒ 红 |
| C2 | 全仓（前端 `src` / `.github/cases/` / `docs/wiki/CONTRACT-LEDGER.md`）**不得出现**该端点的**旧/不存在**路径 | 把任一处写回 `…/craft-calc/auto-features` ⇒ 红 |
| C3 | 引擎侧内部端点路径在 Java client 与引擎 router **两侧都存在**（登记一致） | 改引擎路由而 Java 没跟 ⇒ 红 |
| C4 | 前端**不再**打试算端点的子路径（防「又挂回试算」） | 把前端 URL 改回 `…/craft-calc/auto-features` ⇒ C2 与 C4 双红 |

⚠️ **本守卫不 import 前端/Java**（跨语言）—— 照源里的字面量比对，与
`test_craft_calc_config_contract.py` / `test_hem_margin_cross_language_drift.py` 同族。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 前端 URL 字面量所在源（`craftCalcApi.autoFeatures`）
API_TS = REPO_ROOT / "frontend/admin-web/src/lib/api.ts"
#: Java 控制器（`@RequestMapping` = 真值源）
JAVA_CONTROLLER = (
    REPO_ROOT
    / "backend/admin-api/src/main/java/com/migao/admin/controller/AutoFeaturesController.java"
)
#: Java 客户端（内部端点路径）
JAVA_CLIENT = (
    REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/CraftCalcClient.java"
)
#: 引擎路由（内部端点路径的另一侧）
AGENT_ROUTER = REPO_ROOT / "backend/ai-agent-service/app/api/internal.py"

#: 该端点的**旧/不存在**路径（本单起草期写错的那条；出现即红 —— 文档/用例的真值腐烂）
STALE_ADMIN_PATH = "/api/admin/orders/craft-calc/auto-features"

#: C2 的扫描面（**文档与用例库也是行为真值源**，不只是代码）
SCANNED = (
    REPO_ROOT / "frontend/admin-web/src",
    REPO_ROOT / ".github/cases",
    REPO_ROOT / "docs/wiki/CONTRACT-LEDGER.md",
)

_INTERNAL_PATH = "/api/internal/production/auto-features"


def _frontend_admin_url() -> str:
    """前端 `craftCalcApi.autoFeatures` 打的 URL（取不到 ⇒ **直接失败**，不静默跳过）。"""
    src = API_TS.read_text(encoding="utf8")
    m = re.search(r"autoFeatures:[\s\S]{0,200}?request\.post<[\s\S]{0,120}?>\s*\(\s*'([^']+)'", src)
    assert m, (
        "api.ts 里找不到 `craftCalcApi.autoFeatures` 的 URL 字面量 —— "
        "端点被改名/搬走 ⇒ 本守卫失去判别力，必须红并同步改判"
    )
    return m.group(1)


def _java_admin_path() -> str:
    """Java `AutoFeaturesController` 的 `@RequestMapping` 值（取不到 ⇒ 直接失败）。"""
    src = JAVA_CONTROLLER.read_text(encoding="utf8")
    m = re.search(r'@RequestMapping\("([^"]+)"\)', src)
    assert m, "AutoFeaturesController 里找不到 `@RequestMapping(\"…\")` —— 真值源取不到，必须红"
    return m.group(1)


def test_frontend_url_equals_java_mapping() -> None:
    """C1：前端 URL == Java `@RequestMapping`（逐字）。"""
    frontend, java = _frontend_admin_url(), _java_admin_path()
    assert frontend == java, (
        f"跨语言契约漂移：前端 `craftCalcApi.autoFeatures` 打 {frontend!r}，"
        f"而 Java `AutoFeaturesController` 映射 {java!r} —— 两者必须逐字相同"
    )
    # 反恒真：路径必须真的指向「自动特征判定」而不是碰巧相同
    assert frontend.endswith("/auto-features"), frontend
    assert "/craft-calc/" not in frontend, (
        f"{frontend!r} 看起来又挂回了**试算**端点下 —— 判定的理由就是「试算覆盖不到四爪钩/穿杆/平幔」"
    )


def test_stale_admin_path_absent_everywhere() -> None:
    """C2：旧/不存在路径不得出现在代码、用例库、契约账本里。"""
    hits: list[str] = []
    for root in SCANNED:
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix not in (".ts", ".tsx", ".yml", ".yaml", ".md"):
                continue
            for i, line in enumerate(path.read_text(encoding="utf8").splitlines(), 1):
                if STALE_ADMIN_PATH in line:
                    hits.append(f"{path.relative_to(REPO_ROOT)}:{i}")
    # 注入：把任一处写回旧路径 ⇒ 红（下一个人照着它调会 404）
    assert not hits, "旧/不存在的端点路径仍在：\n  " + "\n  ".join(hits)


def test_internal_path_registered_on_both_sides() -> None:
    """C3：引擎侧内部端点路径在 Java client 与引擎 router 两侧都存在。"""
    client, router = JAVA_CLIENT.read_text(encoding="utf8"), AGENT_ROUTER.read_text(encoding="utf8")
    assert _INTERNAL_PATH in client, (
        f"Java `CraftCalcClient` 里找不到内部端点路径 {_INTERNAL_PATH} —— "
        "改引擎路由而 Java 没跟（或反之）⇒ 线上 404，必须红"
    )
    assert f'@router.post("{_INTERNAL_PATH.removeprefix("/api/internal")}")' in router or _INTERNAL_PATH in router, (
        f"引擎 `internal.py` 里找不到路由 {_INTERNAL_PATH} —— 真值源取不到，必须红"
    )
