# case_ids: PG-070
"""类级元守卫（issue #6222）：**列表读端点的分页入参准入**不许漏（漏了必红）。

## 病（本单的形态 = 同一缺陷散在 N 个入口）

`GET /api/admin/orders?page=1&size=-5` ⇒ 200 + `data.total=0` + 整页行（359）。
机制：MyBatis-Plus 的 `PaginationInnerInterceptor` 把**负数 `size`** 当「不分页」信号
（不查 count、不追加 LIMIT）⇒ 行数不设上界、`total` 停在默认 0。
**它不是订单面独有的**（实测 after-sales 5 行 / stock-ledger 389 行同款）。
而分页入口有**两个族**、**没有共同基类**（`@RequestParam long size` 的控制器方法 + 各自带
`page`/`size` 字段的查询 DTO）⇒ 只修一处 = 没修。

## 修法与之配套的守卫（本文件）

修法 = **单点准入**：`com.migao.admin.validation.PaginationParamGate`
（判定本体）+ `com.migao.admin.security.PaginationParamInterceptor`
（`preHandle` 取参委派）+ `com.migao.admin.config.WebConfig` 注册到 `/api/**`。
=> 「同一份闸、同一个 HTTP 参数名白名单」，逐个控制器/DTO 各写一份**不存在**。

本守卫把那条口径变成机械判据：**所有**「按 `page`/`size` 分页的控制器方法」必须逐条落在
`pagination_param_gate_ledger.json` 里 ⇒ 新加一个分页端点而没登记 ⇒ **当场红并具名**
（这正是「漏改一个入口就重犯」的机制化出口）。

## 判据（六条，任一不成立 ⇒ 红；条数一律**现取**，不写死）

1. **扫描面为空 ⇒ fail-closed**：现取到的分页控制器方法数为 0 ⇒ 红
   （防「正则失效 / 目录改名 ⇒ 空集比空集恒等」的假绿）。
2. **未登记即红**：现取集合 ⊄ 台账 ⇒ 逐个具名报出（新分页端点必须登记）。
3. **台账不许有幽灵条目**：台账 ⊆ 现取集合（端点被删/改名 ⇒ 红，台账只许缩短）。
4. **每条必须写出为什么它被单点闸覆盖**：`source`（`@RequestParam` 字面量 / 查询 DTO 字段）
   与 `why` 都非空；`source=<DTO 类名>` 的条目必须**机械可核**：
   `dto_family` 里的 DTO 文件真存在、且真有 `private Long size;` 声明。
5. **接线不许消失**：`gated_by` 三个锚（闸本体 / 拦截器 / 注册点）必须都是**存在的仓内文件**
   且 `requires` 文本逐字出现 ⇒ 谁删掉注册或改名 ⇒ 红。
6. **判别力自证**：五种坏形态（新增未登记入口 / 幽灵条目 / 缺 why / DTO 声明被删 / 接线锚失效）
   在**内存变异**下各自判红，且**只改注释 ⇒ 不红**（对照读数）。

## 覆盖边界（照实登记，§19.1）

- **只认字面形态**：`@RequestParam(...) page/size`（含跨行注解）与**无注解的裸参数**
  `long page, long size`（DTO 的 `@ModelAttribute` 形态）。注解掉行 / 常量拼接 /
  自定义 `HandlerMethodArgumentResolver` 造的参数名**不在分辨率内**（会漏报，不会误报）。
- **`source` 指向的 DTO 字段与 HTTP 参数名的一致性不在此机械判**（实测
  `ProductQueryRequest.productId` 对 `@RequestParam productCode` ⇒ 属性名≠参数名的形态真实存在）；
  改口径的出口是**在 DTO 上加 `@JsonProperty`/显式 setter 时人写 `why`**（同 §28.2.2 的取舍），
  而 HTTP 参数名一侧由单点闸在**取参层**兜住（与 DTO 如何绑无关）。
- **不覆盖**「不经 HTTP 层直接调 service」的内部调用（审计 / 定时任务 / 内部 recompute）——
  那属另一条兜底线，不在本单射程。
- 本守卫**不跑** Java 测试（只读源码文本），**不替代**三条实例判据
  （`PaginationParamGateTest` / `PaginationParamGateEndpointTest` / `PaginationParamGateWiringTest`）。
"""

from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
CONTROLLER_ROOT = "backend/admin-api/src/main/java/com/migao/admin/controller"
LEDGER_REL = "tests/unit_ci_workflows/pagination_param_gate_ledger.json"
MIN_WHY = 20

#: 方法签名起始（≥4 格缩进）—— 逐行扫描 + 花括号配平定界（比「单行签名」近似更稳）
_SIG_START = re.compile(
    r"^\s{4,}(?:(?:public|private|protected|static|final|synchronized|abstract|default)\s+)*"
    r"(?:[\w$<>\[\],.?]+\s+)+(\w+)\s*\(",
    re.M,
)
_CTRL = {"if", "for", "while", "switch", "catch", "synchronized", "new", "return", "do", "else",
         "try", "record", "class", "interface", "enum"}
#: `@RequestParam(...)` 注解块（允许跨行）
_RP = re.compile(r"@RequestParam\s*\(([^)]*)\)", re.S)
_RP_NAME = re.compile(r'name\s*=\s*"([^"]+)"|value\s*=\s*"([^"]+)"')
#: 一个**注解参数**的完整形态（注解 + 注解实参 + 修饰注解 + 类型 + 参数名）——
#: 参数名**只从声明里取**（`@RequestParam(defaultValue = "1") long page` ⇒ `page`），
#: 绝不从注解实参里猜（`defaultValue = "1"` 的尾词是 `"1"`，按它判会全漏）。
_RP_PARAM = re.compile(
    r"@RequestParam\s*(?:\([^)]*\))?\s*(?:@\w+\s*)*"
    r"(?:final\s+)?[\w$<>\[\],.?]+\s+(\w+)\s*[,)]",
    re.S,
)
#: 已知「按 page/size 分页」的查询 DTO 族（**白名单**：只有它们算「分页入口」；
#: 本仓的 `HttpServletRequest` 也以 Request 结尾 ⇒ 不能按名字后缀泛判，否则全是假红）
_DTO_PARAM = re.compile(
    r"(?<![\w.])(ProductQueryRequest|ProcessingItemQueryRequest|NotificationQueryRequest)\s+\w+\s*[,)]"
)
#: DTO 里的分页字段声明（本守卫机械核的那一半）
_DTO_SIZE_FIELD = re.compile(r"private\s+Long\s+size\s*(=|;)")


class _Method:
    """一个控制器方法的现取读数。"""

    def __init__(self, path: str, name: str, damage: int, params: list[str], dto_types: list[str]):
        self.path = path
        self.name = name
        self.damage = damage        # 仅用于诊断排序（不做断言）
        self.params = params        # 分页用到的 HTTP 参数名（page/size）
        self.dto_types = dto_types  # 查询 DTO 形参类型

    @property
    def key(self) -> str:
        return f"{self.path}::{self.name}"


def _split_methods(text: str) -> list[tuple[str, str]]:
    """把源码切成 (方法名, 方法体文本)。签名可跨行 —— 故先按签名起点切，再按花括号配平。

    返回的顺序即源码顺序；每个方法体 = 从签名起点到配平结束。
    """
    out: list[tuple[str, str]] = []
    for match in _SIG_START.finditer(text):
        name = match.group(1)
        if name in _CTRL:
            continue
        open_idx = text.find("{", match.start())
        if open_idx < 0:
            continue
        depth = 0
        k = open_idx
        while k < len(text):
            ch = text[k]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out.append((name, text[match.start():k + 1]))
    return out


def _scan_controllers(root: pathlib.Path) -> list[_Method]:
    """现取：所有「按 page/size 分页」的控制器方法。"""
    found: dict[str, _Method] = {}
    for p in sorted(root.rglob("*.java")):
        text = p.read_text(encoding="utf-8")
        if "@RestController" not in text and "@Controller" not in text:
            continue
        rel = str(p.relative_to(REPO)).replace("\\", "/")
        for name, body in _split_methods(text):
            params: list[str] = []
            for m_rp in _RP_PARAM.finditer(body):
                declared = m_rp.group(1)
                named = _RP_NAME.search(m_rp.group(0))
                http_name = (named.group(1) or named.group(2)) if named else declared
                if http_name in ("page", "size"):
                    params.append(http_name)
            dto_types = sorted(set(m.group(1) for m in _DTO_PARAM.finditer(body)))
            if params or dto_types:
                method = _Method(rel, name, 0, sorted(set(params)), dto_types)
                found.setdefault(method.key, method)
    return [found[k] for k in sorted(found)]


# ────────────────────────────── 判据本体（纯函数，可就地自证） ──────────────────────────────

def scan_face(root: pathlib.Path = REPO) -> list[_Method]:
    return _scan_controllers(root / CONTROLLER_ROOT)


def ledger_violations(face: list[_Method], ledger: dict) -> list[str]:
    """判据 1~5：返回违规清单（空 = 绿）。判据本体是纯函数 ⇒ 判别力可自证。"""
    problems: list[str] = []
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        return ["台账缺少 entries 列表（schema 漂移？）"]
    if not face:
        return ["扫描面为空（fail-closed）：分页控制器方法现取 0 条 —— 正则/目录失效即假绿"]

    actual = {m.key: m for m in face}
    registered = [e.get("key", "") for e in entries]

    # (2) 未登记即红
    for key in sorted(set(actual) - set(registered)):
        problems.append(f"未登记的分页入口: {key}（新增分页端点必须进 {LEDGER_REL}）")
    # (3) 幽灵条目
    for key in sorted(set(registered) - set(actual)):
        problems.append(f"台账幽灵条目（现取集合里没有）: {key} —— 条目被删/改名即须同步台账")

    # (4) 每条必须写出 source + why；DTO 条目机械可核
    dto_family = ledger.get("dto_family", {})
    for e in entries:
        key = e.get("key", "<无 key>")
        source = (e.get("source") or "").strip()
        why = (e.get("why") or "").strip()
        if not source:
            problems.append(f"{key}: 缺 source（@RequestParam 字面量 / 查询 DTO 字段）")
        if len(why) < MIN_WHY:
            problems.append(f"{key}: why 缺失或过短（<{MIN_WHY} 字）⇒ 等于没写理由")
        if source and source not in ("@RequestParam", "dto") and source not in dto_family:
            problems.append(f"{key}: source=`{source}` 不在 dto_family 台账里")
        if source in dto_family:
            rel_dto = dto_family[source]
            dto_path = REPO / rel_dto
            if not dto_path.is_file():
                problems.append(f"{key}: DTO 文件不存在: {rel_dto}（声明存在 ≠ 真在）")
            elif not _DTO_SIZE_FIELD.search(dto_path.read_text(encoding="utf-8")):
                problems.append(f"{key}: {rel_dto} 里找不到 `private Long size` 声明（DTO face 已被改）")

    # (5) 接线锚必须逐字存在
    for anchor in ledger.get("gated_by", []):
        rel = anchor.get("path", "")
        need = anchor.get("requires", "")
        target = REPO / rel
        if not target.is_file():
            problems.append(f"接线锚文件不存在: {rel}")
        elif need and need not in target.read_text(encoding="utf-8"):
            problems.append(f"接线锚失效: {rel} 里找不到 `{need}`（闸被摘/改名 ⇒ 无准入）")
    if not ledger.get("gated_by"):
        problems.append("gated_by 为空 ⇒ 单点闸接线无锚（fail-closed）")
    return problems


def load_ledger() -> dict:
    return json.loads((REPO / LEDGER_REL).read_text(encoding="utf-8"))


# ────────────────────────────── 判据 ──────────────────────────────

def test_scan_face_is_not_empty():
    """判据 1：扫描面为空 ⇒ fail-closed（空集比空集是恒等，那种绿是假绿）。"""
    face = scan_face()
    assert face, (
        "现取到 0 个分页控制器方法 ⇒ 扫描器失效（目录改名 / 正则腐化）——"
        "本条 **fail-closed**，绝不当「没有分页端点」读"
    )


def test_every_paginated_entry_is_registered():
    """判据 2~5：未登记 / 幽灵 / 缺理由 / DTO 声明丢失 / 接线锚失效 ⇒ 逐条具名报出。"""
    problems = ledger_violations(scan_face(), load_ledger())
    assert not problems, "分页入参准入的类级元守卫判红：\n  - " + "\n  - ".join(problems)


def test_dto_family_is_not_empty_and_checked():
    """判据 4b：DTO 族台账不许空转（本单实测三个 DTO 各带独立 page/size、无共同基类）。"""
    dto_family = load_ledger().get("dto_family", {})
    assert dto_family, "dto_family 为空 ⇒ DTO face 无覆盖（fail-closed）"
    for name, rel in dto_family.items():
        path = REPO / rel
        assert path.is_file(), f"dto_family[{name}] 指向不存在的文件: {rel}"
        assert _DTO_SIZE_FIELD.search(path.read_text(encoding="utf-8")), (
            f"dto_family[{name}] 的 {rel} 里没有 `private Long size` —— DTO face 变了，台账须同步"
        )


def test_guard_discriminates():
    """判据 6：判别力自证 —— 五种坏形态各自判红；只改注释**不红**（对照读数）。"""
    face = scan_face()
    ledger = load_ledger()
    assert not ledger_violations(face, ledger), "前提：真语料必须先绿（否则下面的变异读数不可解释）"

    # ① 新增未登记入口
    injected = face + [_Method(
        "backend/admin-api/src/main/java/com/migao/admin/controller/NewThingController.java",
        "listNewThing", 0, ["page", "size"], [])]
    assert any("未登记的分页入口" in p for p in ledger_violations(injected, ledger)), "① 新增入口未判红"

    # ② 幽灵条目（台账里多一条现取集合里没有的）
    ghost = json.loads(json.dumps(ledger))
    ghost["entries"].append({"key": "backend/admin-api/src/main/java/.../GhostController.java::ghost",
                             "source": "@RequestParam",
                             "why": "这是一条幽灵条目，现取集合里不存在，必须判红（本条用于判别力自证）。"})
    assert any("幽灵条目" in p for p in ledger_violations(face, ghost)), "② 幽灵条目未判红"

    # ③ 缺 why
    thin = json.loads(json.dumps(ledger))
    thin["entries"][0]["why"] = "太短"
    assert any("why 缺失或过短" in p for p in ledger_violations(face, thin)), "③ 缺理由未判红"

    # ④ DTO 声明被删（把 DTO 里的 private Long size 去掉）
    dto_name = next(iter(ledger["dto_family"]))
    dto_rel = ledger["dto_family"][dto_name]

    real_read = pathlib.Path.read_text
    dto_path = REPO / dto_rel

    def fake_read_text(self, *a, **k):
        if self == dto_path:
            return real_read(self, *a, **k).replace("private Long size", "private Long pageSize")
        return real_read(self, *a, **k)

    pathlib.Path.read_text = fake_read_text
    try:
        assert any("找不到 `private Long size`" in p for p in ledger_violations(face, ledger)), \
            "④ DTO 声明被删未判红"
    finally:
        pathlib.Path.read_text = real_read

    # ⑤ 接线锚失效（注册点里找不到 requires 文本）
    broken = json.loads(json.dumps(ledger))
    broken["gated_by"][0]["requires"] = "这段文本全仓都不存在_用于判别力自证"
    assert any("接线锚失效" in p for p in ledger_violations(face, broken)), "⑤ 接线锚失效未判红"

    # 对照：只改注释 / 只改措辞 ⇒ 不红（守卫不被自己的文案喂红）
    commented = json.loads(json.dumps(ledger))
    commented["what"] = commented["what"] + "（本句是注释性措辞，不应影响判定）"
    assert not ledger_violations(face, commented), "对照：只改措辞不该判红"
