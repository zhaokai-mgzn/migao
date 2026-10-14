# case_ids: UI-061, UI-062, UI-063
"""打印**介质矩阵**守卫（issue #5651）—— 让「又一个 A4 模板」式蔓延进不来。

## 病根（实测，不是推断）

客户现行四种单据里，MIGAO 只有两种半；而销售单的介质是**三联纸**（针式点阵 + 连续纸 +
压感复写）—— 实测 `三联` / `针式` / `压感` / `连续纸` **全仓 0 命中**，即**零支持**。
介质若不显式分层，新单据只会**再抄一份 A4 模板**：抄出来的那份 `@page` 与字段映射
**没有任何东西**会拦住它漂移（纸面尺寸错 = 打废纸、字段错 = 账实不符，两者都不出声）。

## 冻结口径（四条判据，逐条可红）

| # | 判据 | 红证（怎么让它**单独**变红） |
|---|---|---|
| C1 | **登记表非空 + 路径存在 + 介质 id 在矩阵里**（路径漂移不得静默跳过） | 清空登记表 / 改坏路径 / 写一个矩阵里没有的介质 id ⇒ 红 |
| C2 | 每份受管单据的 `@page` **逐字等于**矩阵里它声明的介质（不许各写一份） | 把 `pageSize` 改一位（`A4`→`A3`）或让单据自写 `@page { size: A5 }` ⇒ 该单据红 |
| C3 | **未声明介质的可打印单据 ⇒ 红**（扫 `src/**` 的门户式单据：`createPortal` + `-print-area`） | 新增一个带 `createPortal` + `*-print-area` 的组件但不登记 ⇒ 红 |
| C4 | **待实测登记必须存在**：非 `measured` 的介质要有非空 `pendingMeasurements`（且 ≥3 条） | 删掉三联纸的 `pendingMeasurements` ⇒ 红 |
| C5 | **单份字段映射**：每张单据的列清单（有序标签串）在 `src/**` 里**恰好出现在一个文件** | 把销售单的列清单复制一份（如「A4 版」）⇒ 红 |
| C6 | 注入式红证 + **内容指纹**自证（禁 mtime / size，issue #4260） | 注入未生效 ⇒ 红（红证自己是空断言） |

⚠️ **判据按「去注释后的代码」判定**：各单据的文件头都**用注释解释**这些坑（会写出反例），
按原文判定会把解释性注释判成违规 = 假红。故本文件自带字符串感知的注释剥离器。

⚠️ **C5 为什么用「列清单的有序标签串」而不是 grep 组件名**：介质是**参数**，同一个单据换介质
**不该**长出第二个组件；而「抄一份映射」在文本上必然留下**同一串有序列名**。判据不认文件名、
只认那串列名 ⇒ 改名绕过无效（改名后列名串照样被数到 2 个文件）。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "frontend" / "admin-web" / "src"
MATRIX_JSON = SRC / "lib" / "print-media.json"

#: 受管**可打印单据**登记表：（文件, 申报的介质 id）
#: 🔴 新增任何门户式打印单据都必须在这里登记介质（C3 会扫出未登记者）——
#: 「这张单据印在什么纸上」是**必答项**，不是注释里的一句话。
PRINT_DOCS: tuple[tuple[str, str], ...] = (
    ("frontend/admin-web/src/components/orders/ShipmentDoc.tsx", "a4"),
    ("frontend/admin-web/src/components/orders/QuotationDoc.tsx", "a4"),
    ("frontend/admin-web/src/components/orders/ProcessingDoc.tsx", "a4"),
    ("frontend/admin-web/src/components/orders/SalesDoc.tsx", "continuous-241x140"),
    ("frontend/admin-web/src/components/production/TaskCardPrint.tsx", "label-50x60"),
)

#: 单份字段映射：（单据名, 实现文件, 有序列清单）
#: 列清单**全仓只许出现在一个文件里** —— 介质是参数，不是复制粘贴（issue #5651 核心架构要求）。
SINGLE_PROJECTION: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "加工单",
        "frontend/admin-web/src/components/orders/ProcessingDoc.tsx",
        ("品名", "货号", "颜色", "门幅", "尺寸", "数量", "组件", "批号", "备注"),
    ),
    (
        "销售单",
        "frontend/admin-web/src/components/orders/SalesDoc.tsx",
        ("序号", "品名", "货号", "颜色", "门幅", "数量", "单位", "单价", "金额"),
    ),
)

# ── C7 的判据面（issue #6869）─────────────────────────────────────────────────
#: 纸面「商品 SKU 身份」的**唯一读取口**（`frontend/admin-web/src/lib/order-item-sku.ts`）
ITEM_SKU_READER = "orderItemSku("
#: 纸面「物流方式」的**唯一读取口**（`frontend/admin-web/src/lib/logistics.ts`）
FREIGHT_READERS: tuple[str, ...] = ("freightText(", "logisticsTypeText(")
#: 响应里**不存在**的键（在打印单据里直接读 ⇒ 纸面那一列恒空；issue #6869 的根因）
PHANTOM_ITEM_FIELDS: tuple[str, ...] = ("item.productCode", "item.color")
#: 「这份单据印商品明细行」的形态标记（两条同时出现才算）
_ITEM_TABLE_MARKERS: tuple[str, ...] = ("items.map(", "<DocTd")

#: 门户式打印单据的形态（判据 C3 的扫描依据）：`createPortal` + `-print-area` 容器类
_PORTAL_RE = re.compile(r"createPortal\s*\(")
_PRINT_AREA_RE = re.compile(r"['\"`][a-zA-Z0-9_-]*-print-area\b")
#: `@page { size: X; margin: Y; }` 字面量（唯一合法写法 = 与矩阵逐字一致）
_PAGE_LITERAL_RE = re.compile(r"@page\s*\{\s*size:\s*([^;]+);\s*margin:\s*([^;]+);\s*\}")
#: 介质矩阵读取口调用：`printPageRule('a4')`（字面量形式 —— 单据只印一种纸）
_PAGE_RULE_CALL_RE = re.compile(r"printPageRule\(\s*'([a-z0-9-]+)'\s*\)")
#: 介质矩阵读取口调用：`printPageRule(media)`（**参数化**形式 —— 同一单据可切介质）
_PAGE_RULE_PARAM_RE = re.compile(r"printPageRule\(\s*([A-Za-z_$][\w$]*)\s*\)")
#: 剥注释时要跳过的文件（二进制 / 大文件）与扫描范围
_TS_SUFFIXES = (".ts", ".tsx")
_SKIP_DIRS = {"node_modules", ".next", "coverage", "dist", "build"}


def _read(rel: str) -> str:
    """读一个受管文件；**不存在 ⇒ 直接失败**（路径漂移不得退化成静默跳过 = 空跑通过）。"""
    path = REPO_ROOT / rel
    if not path.is_file():
        raise AssertionError(f"受管文件不存在：{rel} —— 路径漂移 / 文件被删 ⇒ 红（**不得**静默跳过）")
    return path.read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    """剥掉 `//` 与 `/* */` 注释（**字符串字面量内的不剥**，含模板串）。

    各单据的文件头**用注释解释**这些坑（会写出反例式的 `@page` / 列清单），
    按原文判定会把解释性注释判成违规 —— 那是假红，会逼人删掉解释性注释。
    （与 `test_print_doc_convention_guard.py` 的同类实现各自独立：本守卫在 CI 里与它同批收集，
    共享实现会引入「谁先 import 谁生效」的隐式耦合。）
    """
    out: list[str] = []
    i, n = 0, len(src)
    quote: str | None = None
    while i < n:
        ch = src[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
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


def _matrix() -> dict[str, dict]:
    """介质矩阵（真值源 = `frontend/admin-web/src/lib/print-media.json`）。"""
    if not MATRIX_JSON.is_file():
        raise AssertionError(f"介质矩阵不存在：{MATRIX_JSON.relative_to(REPO_ROOT)} ⇒ 判据无从判定（红）")
    data = json.loads(MATRIX_JSON.read_text(encoding="utf-8"))
    media = data.get("media")
    if not isinstance(media, list) or not media:
        raise AssertionError("介质矩阵 `media` 为空 ⇒ 本守卫会**空跑通过**（判据必须能判红）")
    return {str(spec.get("id")): spec for spec in media}


def _src_files() -> list[Path]:
    """`src/**` 下的 TS/TSX 文件（跳过构建产物目录）。"""
    files: list[Path] = []
    for path in sorted(SRC.rglob("*")):
        if not path.is_file() or path.suffix not in _TS_SUFFIXES:
            continue
        if _SKIP_DIRS & set(path.parts):
            continue
        files.append(path)
    return files


# ── 判据本体（纯函数，便于注入式红证）─────────────────────────────────────────

def _doc_page_problems(rel: str, media_id: str, code: str, matrix: dict[str, dict]) -> list[str]:
    """C2：单据的 `@page` 必须与矩阵里它申报的介质**同源**（三种合法写法，见下）。

    写法 A `printPageRule('a4')` —— 单据只印一种纸（尺寸天然同源）；
    写法 B 自写 `@page { size: X; margin: Y; }` —— 允许，但必须与矩阵**逐字一致**
           （钉等价：防「改矩阵不跟着改」的第二份真值漂移）；
    写法 C `printPageRule(media)` —— **参数化**（同一单据可切介质，issue #5651 的架构目标）：
           此时申报的介质必须是**组件的缺省介质**（字面量出现在该文件里），介质取值域由
           `PrintMediaId` 类型收口、切换后字段映射不变由 TS 用例判（`SalesDoc.test.tsx`）。
    """
    problems: list[str] = []
    spec = matrix.get(media_id)
    if spec is None:
        return [f"申报的介质 `{media_id}` 不在矩阵里（{sorted(matrix)}）—— 未登记的介质 = 纸型无人负责"]
    want_size = str(spec.get("pageSize", "")).strip()
    want_margin = str(spec.get("pageMargin", "")).strip()

    literal = _PAGE_LITERAL_RE.search(code)
    calls = _PAGE_RULE_CALL_RE.findall(code)
    if calls:
        # 写法 A：由矩阵生成 ⇒ 尺寸天然同源，只校验 id 一致
        for called in calls:
            if called != media_id:
                problems.append(
                    f"单据用 `printPageRule('{called}')` 生成 @page，与登记介质 `{media_id}` 不一致"
                )
        return problems
    if _PAGE_RULE_PARAM_RE.search(code):
        # 写法 C：参数化 —— 申报的介质必须是缺省值（改了缺省却不改登记 ⇒ 红）
        if f"'{media_id}'" not in code and f'"{media_id}"' not in code:
            problems.append(
                f"单据用 `printPageRule(<变量>)` 参数化介质，但文件里找不到登记介质 `{media_id}` "
                "的字面量（= 缺省介质与登记不一致）"
            )
        return problems
    if literal is None:
        problems.append(
            "找不到 `@page` 声明，也找不到 `printPageRule(...)` 调用 —— "
            "「印在什么纸上」没法判定（未声明介质 ⇒ 红）"
        )
        return problems
    # 写法 B：自写字面量 —— 必须与矩阵逐字一致
    got_size, got_margin = literal.group(1).strip(), literal.group(2).strip()
    if got_size != want_size:
        problems.append(
            f"`@page` 尺寸 `{got_size}` 与矩阵里 `{media_id}` 的 `{want_size}` 不一致"
            f"（{rel} 自写了一份纸型 ⇒ 改矩阵不会跟着改，纸面尺寸会静默错）"
        )
    if got_margin != want_margin:
        problems.append(
            f"`@page` 边距 `{got_margin}` 与矩阵里 `{media_id}` 的 `{want_margin}` 不一致"
        )
    return problems


def _pending_problems(matrix: dict[str, dict]) -> list[str]:
    """C4：非 `measured` 的介质**必须**登记待实测清单（否则「通用参数」会被读成实测值）。"""
    problems: list[str] = []
    for media_id, spec in sorted(matrix.items()):
        if str(spec.get("measurement")) == "measured":
            continue
        pending = spec.get("pendingMeasurements")
        if not isinstance(pending, list) or len(pending) < 3:
            problems.append(
                f"介质 `{media_id}` 的 measurement={spec.get('measurement')!r}，"
                f"但待实测清单只有 {len(pending) if isinstance(pending, list) else '非列表'} 条（要求 ≥3）"
                "—— 真机参数拿不到时**必须显式登记**，不许把推定值写成实测值"
            )
            continue
        for item in pending:
            if not str(item).strip():
                problems.append(f"介质 `{media_id}` 的待实测清单里有空条目")
    # 反向：标了 `measured` 却留着待实测项 ⇒ 「待实测」会退化成永久标签
    for media_id, spec in sorted(matrix.items()):
        if str(spec.get("measurement")) == "measured" and spec.get("pendingMeasurements"):
            problems.append(f"介质 `{media_id}` 标了 measured 却仍留着待实测项 ⇒ 二者必须一致")
    return problems


def _projection_hits(columns: tuple[str, ...], files: dict[str, str]) -> list[str]:
    """C5：列清单的有序标签串**出现在哪些文件**（返回值 = 文件相对路径列表）。

    匹配的是「按顺序出现的那串列名」，允许中间夹引号 / 逗号 / 空白 / 换行 ——
    与组件把它写成数组还是多行无关；**复制一份映射必然留下第二处命中**。
    """
    pattern = re.compile(
        r"['\"`]" + r"['\"`]\s*,\s*['\"`]".join(re.escape(label) for label in columns) + r"['\"`]"
    )
    hits: list[str] = []
    for rel, code in sorted(files.items()):
        if pattern.search(code):
            hits.append(rel)
    return hits


# ── C1：登记表非空 + 路径存在 + 介质 id 在矩阵里 ───────────────────────────────

def test_c1_registry_is_not_vacuous_and_points_at_real_media():
    """C1：登记表非空、每个登记路径存在、每个申报的介质 id 在矩阵里。"""
    assert len(PRINT_DOCS) >= 5, (
        f"受管可打印单据清单被缩短到 {len(PRINT_DOCS)} 条 ⇒ 本守卫会空跑通过（判据必须能判红）"
    )
    matrix = _matrix()
    for rel, media_id in PRINT_DOCS:
        _read(rel)  # 不存在 ⇒ 抛错（不静默跳过）
        assert media_id in matrix, (
            f"`{rel}` 申报的介质 `{media_id}` 不在介质矩阵里（现有：{sorted(matrix)}）"
        )
    for name, rel, columns in SINGLE_PROJECTION:
        _read(rel)
        assert len(columns) >= 7, f"{name} 的列清单短得不像一张单据（{len(columns)} 列）—— 判据会失去判别力"


# ── C2：每份受管单据的 @page 逐字等于矩阵 ──────────────────────────────────────

def test_c2_every_print_doc_page_rule_matches_the_media_matrix():
    """C2：`@page` 逐字等于矩阵里那份介质 —— 单据不许各写一份纸型。"""
    matrix = _matrix()
    offenders: list[str] = []
    for rel, media_id in PRINT_DOCS:
        for problem in _doc_page_problems(rel, media_id, _strip_comments(_read(rel)), matrix):
            offenders.append(f"{rel}: {problem}")
    assert offenders == [], (
        "可打印单据的 `@page` 与**介质矩阵**不一致（issue #5651）：介质是**参数**，"
        "不是各写一份的副本 —— 单据自写纸型时，改矩阵不会跟着改（纸面尺寸错 = 打废纸）：\n  "
        + "\n  ".join(offenders)
        + "\n修法：单据改用 `printPageRule('<介质id>')`（`src/lib/print-media.ts`），"
        "或让字面量与 `src/lib/print-media.json` 逐字一致"
    )


# ── C3：未声明介质的可打印单据 ⇒ 红（防「又一个 A4 模板」）──────────────────────

def test_c3_new_portaled_print_docs_must_declare_a_media():
    """C3：扫 `src/**` 的门户式打印单据（`createPortal` + `-print-area`），逐个必须在登记表里。"""
    registered = {rel for rel, _ in PRINT_DOCS}
    unregistered: list[str] = []
    seen: list[str] = []
    for path in _src_files():
        code = _strip_comments(path.read_text(encoding="utf-8"))
        if not (_PORTAL_RE.search(code) and _PRINT_AREA_RE.search(code)):
            continue
        rel = str(path.relative_to(REPO_ROOT))
        seen.append(rel)
        if rel not in registered:
            unregistered.append(rel)
    assert unregistered == [], (
        "发现**未声明介质**的门户式打印单据（issue #5651「新增可打印单据必须声明介质」）：\n  "
        + "\n  ".join(unregistered)
        + "\n修法：在该单据里用 `printPageRule('<介质id>')` 生成 `@page`，并在 "
        "`tests/unit_ci_workflows/test_print_media_matrix_guard.py` 的 `PRINT_DOCS` 登记"
        "（介质在 `src/lib/print-media.json` 里定义）"
    )
    assert len(seen) >= 4, (
        f"扫描只看到 {len(seen)} 份门户式单据（预期 ≥4：发货单 / 报价单 / 加工单 / 销售单 + 洗水码）"
        " ⇒ 扫描口径已失效，C3 正在**空跑通过**"
    )


# ── C4：待实测登记必须存在 ────────────────────────────────────────────────────

def test_c4_pending_field_measurements_must_be_registered():
    """C4：非 `measured` 的介质必须有非空待实测清单（且 ≥3 条）。"""
    problems = _pending_problems(_matrix())
    assert problems == [], (
        "介质矩阵里的**待实测登记**不成立（issue #5651：真机参数拿不到 ⇒ 通用参数 + **显式登记**，"
        "不许编造精确值）：\n  " + "\n  ".join(problems)
    )
    tri = _matrix().get("continuous-241x140") or {}
    assert str(tri.get("pageSize")).strip() == "241mm 140mm", (
        f"三联纸纸型被改了或该介质被删：{tri.get('pageSize')!r} ≠ 用户 2026-09-26 裁定的 `241mm 140mm`（两等分）"
    )
    assert str(tri.get("technology")) == "dot-matrix", (
        f"三联纸的打印技术被改了：{tri.get('technology')!r} ≠ `dot-matrix`（针式点阵，用户裁定）"
    )
    assert int(tri.get("carbonCopies") or 0) == 3, (
        f"三联纸的复写份数被改了：{tri.get('carbonCopies')!r} ≠ 3（三联 = 一次打印复写三份）"
    )


# ── C5：单份字段映射（介质是参数，不是副本）───────────────────────────────────

def test_c5_each_doc_has_exactly_one_field_projection():
    """C5：每张单据的列清单在 `src/**` 里**恰好出现在一个文件**（复制一份 ⇒ 红）。"""
    files = {
        str(path.relative_to(REPO_ROOT)): _strip_comments(path.read_text(encoding="utf-8"))
        for path in _src_files()
    }
    problems: list[str] = []
    for name, owner, columns in SINGLE_PROJECTION:
        hits = _projection_hits(columns, files)
        if hits != [owner]:
            problems.append(
                f"{name}的列清单（{' | '.join(columns)}）在 src 下命中 {len(hits)} 个文件：{hits}"
                f"（要求**恰好** 1 个 = `{owner}`）"
            )
    assert problems == [], (
        "同一单据出现了**第二份字段映射**（issue #5651：介质是**参数**，不是复制粘贴出来的页面）：\n  "
        + "\n  ".join(problems)
        + "\n修法：删掉副本，让另一个介质版本复用同一份映射（把介质做成 prop / 参数）"
    )


# ── C6：注入式红证 + 内容指纹自证 ─────────────────────────────────────────────

def _fingerprint(text: str) -> str:
    """内容指纹（issue #4260 红证卫生：**禁 mtime / size** —— 它们会被同秒写入骗过）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_c6_injected_regressions_are_red():
    """C6：往副本里注入四类回归，判据必须**各自**判红；并用内容指纹自证注入生效。"""
    matrix = _matrix()

    # ── 注入 A（C2）：把单据调用的介质 id 改成矩阵里**不存在**的（写法 A 的判别面）──
    rel, media_id = "frontend/admin-web/src/components/orders/QuotationDoc.tsx", "a4"
    code = _strip_comments(_read(rel))
    assert _doc_page_problems(rel, media_id, code, matrix) == [], (
        f"`{rel}` 原文件本应干净（C2 已单独判）—— 这里先红说明判据或预期已变"
    )
    bad_id = code.replace("printPageRule('a4')", "printPageRule('a5')", 1)
    assert _fingerprint(bad_id) != _fingerprint(code), "注入 A 未生效（内容指纹相同）"
    assert _doc_page_problems(rel, media_id, bad_id, matrix), (
        "介质 id 写成矩阵外的值却**没判红** ⇒ C2 是空判据"
    )

    # ── 注入 A2（C2 的**写法 B** 分支）：合成样本，保证「字面量必须与矩阵逐字一致」这条分支
    #    不会因为树里暂时没人用写法 B 就退化成空判据（issue #5914：五份单据已全部走写法 A）──
    literal_doc = "const css = `@page { size: A4; margin: 12mm; }`"
    assert _doc_page_problems("(合成样本)", media_id, literal_doc, matrix) == []
    drifted = {**matrix, "a4": {**matrix["a4"], "pageSize": "A3"}}
    assert _fingerprint(json.dumps(drifted, sort_keys=True)) != _fingerprint(
        json.dumps(matrix, sort_keys=True)
    ), "注入后介质矩阵指纹未变（**禁 mtime/size**）"
    assert _doc_page_problems("(合成样本)", media_id, literal_doc, drifted), (
        "纸型漂移后判据**没判红** ⇒ C2 的写法 B 分支是空判据"
    )

    # ── 注入 B（C2）：单据不再声明任何纸型（删掉 @page 与 printPageRule 调用）──
    no_page = _PAGE_LITERAL_RE.sub("", _PAGE_RULE_CALL_RE.sub("", code))
    assert _fingerprint(no_page) != _fingerprint(code), "注入 B 未生效（内容指纹相同）"
    assert _doc_page_problems(rel, media_id, no_page, matrix), "单据不声明纸型却**没判红** ⇒ 空判据"

    # ── 注入 C（C4）：删掉三联纸的待实测登记 ──
    stripped = {
        **matrix,
        "continuous-241x140": {**matrix["continuous-241x140"], "pendingMeasurements": []},
    }
    assert _pending_problems(stripped), "删掉待实测登记后判据**没判红** ⇒ C4 是空判据"

    # ── 注入 D（C5）：把销售单的列清单**复制一份**到另一个文件（模拟「再写一个 A4 版」）──
    files = {
        str(path.relative_to(REPO_ROOT)): _strip_comments(path.read_text(encoding="utf-8"))
        for path in _src_files()
    }
    _, owner, columns = SINGLE_PROJECTION[1]
    assert _projection_hits(columns, files) == [owner], "原树本应恰好命中一处 —— 判据或预期已变"
    copied = dict(files)
    copied["frontend/admin-web/src/components/orders/SalesDocA4.tsx"] = (
        "export const COLUMNS = [" + ", ".join(f"'{c}'" for c in columns) + "]\n"
    )
    hits = _projection_hits(columns, copied)
    assert len(hits) == 2, f"复制一份字段映射后命中数应为 2（实际 {hits}）⇒ C5 是空判据"


# ── C7：纸面「商品身份」与「物流方式」必须走唯一读取口（issue #6869）───────────────
#
# 病灶（用户 2026-10-14 逐字）：「缺了商品 sku 的信息」+「货运 express · 顺丰速运，
# 不要用英文，人家看不懂」。两处的根因是同一形态：**纸面各自读了一个不该读的键**——
#   ① 货号/颜色读 `item.productCode` / `item.color`，而 `OrderItemResponse` 里**没有这两个键**
#      （真字段 = `skuCode`，颜色在 `processingInfo.colorName`）⇒ 纸面那两列恒空、
#      且**没有任何东西会红**（测试夹具自己造了幽灵字段）；
#   ② 货运直接拼后端枚举 `logisticsType`（`express`）⇒ 给客户的纸上印英文内部值。
# ⇒ 判据把「读哪个口」钉死：**换一份会漂的写法**（新单据复制一段取数）当场红。

def _identity_problems(rel: str, code: str) -> list[str]:
    problems: list[str] = []
    for needle in PHANTOM_ITEM_FIELDS:
        if needle in code:
            problems.append(
                f"`{rel}` 直接读 `{needle}` —— 该键**不在** `OrderItemResponse` 里"
                f"（响应真字段是 `skuCode` / `processingInfo.colorName`）⇒ 纸面那一列恒空"
            )
    if all(marker in code for marker in _ITEM_TABLE_MARKERS) and ITEM_SKU_READER not in code:
        problems.append(
            f"`{rel}` 印商品明细行却没过唯一读取口 `{ITEM_SKU_READER}`"
            "（品名 / 货号 / 颜色 / 门幅 一律走 `lib/order-item-sku.ts`）"
        )
    return problems


def _freight_problems(rel: str, code: str) -> list[str]:
    if "logisticsType" in code and not any(reader in code for reader in FREIGHT_READERS):
        return [
            f"`{rel}` 引用 `logisticsType` 却没走词表读取口 {list(FREIGHT_READERS)} —— "
            "纸面会把后端枚举（`express`）原样印给客户"
        ]
    return []


def test_c7_paper_identity_and_freight_go_through_the_single_reader():
    """C7：受管打印单据的「商品身份」「物流方式」必须走唯一读取口（未走 ⇒ 红）。"""
    problems: list[str] = []
    for rel, _media in PRINT_DOCS:
        code = _strip_comments(_read(rel))
        problems += _identity_problems(rel, code)
        problems += _freight_problems(rel, code)
    assert problems == [], (
        "打印单据各自读了一份会漂的取值源（issue #6869）：\n  " + "\n  ".join(problems)
    )

    # ── 判别力自证（**内存注入**，不碰真文件）：修前写法必须判红、修后写法必须判绿 ──
    before_identity = "items.map((item) => item.productCode || item.productName)"
    assert _identity_problems("(合成样本·修前)", before_identity), (
        "修前写法（读 `item.productCode`）**没判红** ⇒ C7 的幽灵字段分支是空判据"
    )
    after_identity = "const sku = orderItemSku(item); items.map(() => sku.code)"
    assert _identity_problems("(合成样本·修后)", after_identity) == [], (
        "修后写法被判红 ⇒ C7 会把合规实现喂红（假红）"
    )
    # 「印了明细行却没走读取口」这一支：两条标记同时出现才算（防只按 `items` 误判 TaskCardPrint）
    assert _identity_problems("(合成样本)", "items.map((it) => <DocTd>{it.productName}</DocTd>)"), (
        "印明细行却没过唯一读取口 **没判红** ⇒ 该分支是空判据"
    )
    assert _identity_problems("(合成样本)", "items.map((it) => it.id)") == [], (
        "不印明细行的文件被判红（如任务卡只读快照行）⇒ 该分支过宽"
    )

    before_freight = "[order.logisticsType, order.logisticsCompany].join(' · ')"
    assert _freight_problems("(合成样本·修前)", before_freight), (
        "修前写法（原样拼 `logisticsType`）**没判红** ⇒ C7 的物流分支是空判据"
    )
    after_freight = "const f = freightText(order.logisticsType, order.logisticsCompany)"
    assert _freight_problems("(合成样本·修后)", after_freight) == [], (
        "走词表的写法被判红 ⇒ C7 会把合规实现喂红（假红）"
    )

