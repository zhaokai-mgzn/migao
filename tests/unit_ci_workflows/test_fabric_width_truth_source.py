"""门幅**真值源唯一**守卫（issue #4746）：前端不得自带一份引擎端点的硬编码门幅。

## 为什么需要这条（本单的静默失效形态）

门幅在仓里有**两处口径**（#4877 改判：**前端「缺省门幅」已删除** —— 旧三处口径表的前端缺省那一行作废）：

| 口径 | 值 | 来源 | 谁在读 |
|---|---|---|---|
| 商品/SKU 门幅（**权威**） | 商品可配（种子 2.8；窄幅布 1.4） | 商品 `doorWidths` ⇒ `product_skus.door_width` | 下单页判定 `parseDoorWidth()` / 规则 `resolveCutPlan()`、SKU 定位 / 加工费组合键 |
| 引擎**端点**门幅 | 3.2 | `backend/ai-agent-service/app/api/internal.py::_FABRIC_WIDTH`（**硬编码**，其注释「商家手工下单页当前没有门幅字段」**已过期**） | 商家手工下单页试算通路 |

⇒ 同一张单：前端按 SKU 门幅判「超宽/超高」（**进加工费组合键**），引擎按 3.2 算分幅
⇒ **可能不一致**（组合键匹配到的加工费与实际算料对不上）；提示文案里「引擎实际按哪种算」
也会**说错**。**权威 = SKU/商品门幅**；引擎侧改为**接收**该值是**分叉 #4652**
（本单不动 ai-agent）—— 所以这里钉住的是「前端**不抄**引擎那份硬编码」：
抄一份 = 前端又出现一个**会漂移的第二口径**（本仓 #4656 同族）。

## 判据（机械）

1. 前端门幅真值源模块 `lib/craft-auto-features.ts`（**去注释后**）不得出现引擎端点硬编码门幅值的
   **字面量** —— 值从 `internal.py::_FABRIC_WIDTH` 读出，**不写死**（引擎改了值，抄进前端即红）；
2. 门幅的**取值点唯一**：规则 `door-width-plan.ts`、下单页都必须经 `parseDoorWidth()` 取门幅
   （任一处再写一份门幅解析 ⇒ 红）。⚠️ issue #5035 起前端本地判定/提示实现
   （`detectAutoFeatures` / `detectAutoFeatureNotices`）**已删除**（判定 #5019 / 提示 #5036 /
   算例 #5043 包 2a 都搬到服务端）⇒ 取值点只剩规则面与下单页；**另加死亡条件**（判据 4）钉住它们不得回来；
3. **反向守卫**（#4877）：缺省门幅**不得**回来（`DEFAULT_DOOR_WIDTH` / `resolveDoorWidth` 出现即红）
   —— 解析不到 ⇒ 判定面**不判**并显式告知（`missing-door-width`）、规则面 `undecidable`。
4. **识别 → 建行 面**（issue #5345，判据 5）：不得出现门幅标识符（`fabricWidth` / `fabric_width`）
   —— 门幅的唯一来源是**所选 SKU**（`line.selectedSku.doorWidth`，页面经 `parseDoorWidth` 取）。

## 红证（注入式，逐条可注入）

- 在 `craft-auto-features.ts` 里加 `const ENGINE_TRIAL_WIDTH = 3.2` ⇒ 判据 1 红；
- 把 `door-width-plan.ts` 里的 `parseDoorWidth(...)` 换成写死的 `2.8` ⇒ 判据 2 红（⚠️ issue #5035：原先举的 `detectAutoFeatureNotices` 已退场，红证必须指向**还在的**取值点）；
- 把缺省门幅写回去（`export const DEFAULT_DOOR_WIDTH = 2.8` / 解析回退到默认值）⇒ 判据 3 红。
- 在识别/建行面（`lib/order-line-match.ts` / `lib/image-recognize.ts` / `components/image-recognize/**`）
  写一句 `const fabricWidth = 2.8` ⇒ 判据 5 红（扫描器判别力见 `_fabric_width_identifiers` 的自证断言）。

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
PLAN_TS = REPO / "frontend/admin-web/src/lib/door-width-plan.ts"


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
        "（issue #4746 / 同族 #4656）。解析不到的处置 = **不判**（issue #4877 已删除前端缺省门幅）。"
    )


def test_door_width_has_single_value_source():
    """判据 2/3：门幅解析点唯一（经 `parseDoorWidth()`）+ **缺省门幅不得回来**。

    ⚠️ issue #4877 改判：前端**不再持有缺省门幅**（`DEFAULT_DOOR_WIDTH` / `resolveDoorWidth` 已删除）
    —— SKU 未携带门幅 ⇒ `parseDoorWidth()` 返回 `None` ⇒ 判定面**不判**并在界面显式告知
    （`missing-door-width`）、规则面（`door-width-plan.ts::resolveCutPlan`）返回 `undecidable`。
    旧口径「静默按缺省门幅判超高/超宽」= 要替换掉的错误做法。
    """
    lib = LIB_TS.read_text(encoding="utf8")
    # ⚠️ issue #5035：原先这里遍历 `detectAutoFeatures` / `detectAutoFeatureNotices` 的导出体
    # —— 那两个函数**已随实现删除**（判定/提示/算例都搬到服务端），故本循环退场；
    # **判据强度不放宽**：另加判据 4（死亡条件）钉住它们不得回到前端。
    # ⚠️ issue #5043 包 2b：规则面已迁服务端 ⇒ 前端 `door-width-plan.ts` **退场**，
    # 取值点只剩下单页（`page.tsx` 的 `parseDoorWidth`）。判据强度不放宽（仍要求经该函数取值）。
    for path in (PAGE_TSX,):
        assert "parseDoorWidth(" in path.read_text(encoding="utf8"), (
            f"{path.name} 没有经 `parseDoorWidth()` 取门幅 —— 页面/规则自解析门幅数值 = 第二份口径"
            "（issue #4746 / #4877）"
        )
    assert "DEFAULT_DOOR_WIDTH" not in lib and "resolveDoorWidth" not in lib, (
        "缺省门幅又回来了（`DEFAULT_DOOR_WIDTH` / `resolveDoorWidth`）—— issue #4877 已改判："
        "解析不到 ⇒ 不判（`missing-door-width`）+ 规则面 `undecidable`，不得回退任何默认门幅"
    )
    # 判据 4（**死亡条件**，issue #5035）：前端本地判定/提示实现**已删除** ——
    # 一旦被重新导出，就说明「前端又持了一份与租户配置脱钩的第二份判据」（§17.3 ④ 的形态：
    # 判据要能证明旧做法**没有回来**）。
    for gone in ("detectAutoFeatures", "detectAutoFeatureNotices"):
        assert f"export function {gone}" not in lib and f"export const {gone}" not in lib, (
            f"`{gone}` 又回到了前端 —— issue #5019 / #5036 已把判定与提示搬到服务端；"
            "前端再持一份 = 第二份口径（与租户配置脱钩，商家改过配置后两边会算出不同的键）"
        )


# ── 判据 5（issue #5345）· 识别 → 建行 面不得出现门幅标识符 ────────────────────
#: 识别 → 「匹配候选 → 选品 → 建订单行」面（**glob 面**：新增识别 / 选品文件自动进扫描集，不需要登记）。
#: ⚠️ **下单页不在面内**：它是门幅的**合法取值点**（`calcInputOf` 经 `parseDoorWidth` 从所选 SKU 取
#: 后随试算请求下发）—— 页面侧由上面的判据 2 钉住「必须经 `parseDoorWidth()`」。
RECOGNIZE_FACE_GLOBS = (
    "frontend/admin-web/src/lib/image-recognize.ts",
    "frontend/admin-web/src/lib/order-line-match.ts",
    "frontend/admin-web/src/lib/agent-page-fill.ts",
    "frontend/admin-web/src/components/image-recognize/*.tsx",
)
#: 豁免台账（**现取**：今天为空 ⇒ 面内任何一处出现门幅标识符都是红）；**只许缩短**（见下条断言）
RECOGNIZE_FACE_FABRIC_WIDTH_EXEMPT: tuple = ()

_FABRIC_WIDTH_IDENT = re.compile(r"\bfabricWidth\b|\bfabric_width\b")


def _fabric_width_identifiers(src: str) -> list:
    """面内**代码**里的门幅标识符（去注释后 —— 注释里解释纪律不算违规，§17.3 同族）。"""
    return [m.group(0) for m in _FABRIC_WIDTH_IDENT.finditer(_strip_comments(src))]


def _recognize_face_files() -> list:
    files = []
    for pattern in RECOGNIZE_FACE_GLOBS:
        files.extend(sorted(REPO.glob(pattern)))
    return files


def test_recognition_to_line_face_has_no_fabric_width_identifier():
    """判据 5（issue #5345）：识别 / 选品 / 建行面**不得**持有门幅。

    #5349 的交付方登记的边界逐字：**门幅从图片到推导仍未接线 —— 唯一来源是所选 SKU**。
    识别侧一旦出现门幅（识别值 / 写死 / 缺省），就造出了**第二个来源** ⇒ 与那条登记直接冲突
    （同族：判据 1 的引擎端点硬编码、判据 3 的前端缺省门幅）。
    """
    face = _recognize_face_files()
    assert face, "识别 → 建行 面的 glob 一条都没命中（面变了：本守卫必须能读到被测面）"
    offenders = []
    for path in face:
        rel = str(path.relative_to(REPO))
        hits = _fabric_width_identifiers(path.read_text(encoding="utf8"))
        if hits and rel not in RECOGNIZE_FACE_FABRIC_WIDTH_EXEMPT:
            offenders.append(f"{rel}: {hits}")
    assert not offenders, (
        "识别 → 建行 面里出现了门幅标识符：\n  " + "\n  ".join(sorted(offenders)) + "\n"
        "门幅的**唯一来源**是所选 SKU（`line.selectedSku.doorWidth`，页面经 `parseDoorWidth` 取）——"
        "识别侧再持一份（识别值 / 写死 / 缺省）= 第二个会漂移的来源（issue #5345 判据 5）。\n"
        "复现命令：grep -nE 'fabricWidth|fabric_width' "
        "frontend/admin-web/src/lib/{image-recognize,order-line-match,agent-page-fill}.ts "
        "frontend/admin-web/src/components/image-recognize/*.tsx"
    )


def test_fabric_width_face_exemption_ledger_only_shrinks():
    """豁免必带**死亡条件**：台账里点名的文件若已无命中 ⇒ 红（台账只许缩短，铁律 8 / §23 G2）。"""
    stale = [
        rel
        for rel in RECOGNIZE_FACE_FABRIC_WIDTH_EXEMPT
        if not _fabric_width_identifiers((REPO / rel).read_text(encoding="utf8"))
    ]
    assert stale == [], (
        f"豁免台账里的文件已不再出现门幅标识符，必须从 `RECOGNIZE_FACE_FABRIC_WIDTH_EXEMPT` 删行：{stale}"
        "（豁免没有死亡条件 ⇒ 台账只会变长，判据随之失效）"
    )


def test_fabric_width_face_scanner_has_discriminating_power():
    """注入式红证：扫描器**真能**认出注入（且**不**被注释里的同名文案喂红 ⇒ 判据有判别力）。"""
    assert _fabric_width_identifiers("const fabricWidth = 2.8\n") == ["fabricWidth"]
    assert _fabric_width_identifiers("params.fabric_width = doorWidth\n") == ["fabric_width"]
    assert _fabric_width_identifiers("// 门幅不经本面：fabricWidth 由页面从 SKU 取\n") == []
    assert _fabric_width_identifiers("const width = 2.8\n") == []
