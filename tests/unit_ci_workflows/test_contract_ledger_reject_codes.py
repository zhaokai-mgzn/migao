# case_ids: PG-018
r"""契约账本「拒绝码」一致性守卫（issue #4843）。

## 病根（本单要治的静默失效形态）

`docs/wiki/CONTRACT-LEDGER.md` 是并行开发前锁定的**契约真值源**，但账本里的
「拒绝码」是**手抄副本** —— 源码里新抛一个码、账本不改，**没有任何东西会红**
（实证：`POST /api/worker/production/scan/complete` 实际可抛 3 条拒绝码，账本
「工人端扫码完成」行只登记了 `SCAN_NEEDS_SELECTION` 一条；`SET_ALREADY_COMPLETED`
与 `OPERATION_ALREADY_ADVANCED` 两条 409 **账本未登记**，#4810 源码级核实后由
issue #4843 单独登记）。危害与 #4819 的「散文抄数值」同族：账本会被后来人当成
**权威**做判定，而它说的已经不是真值。

## 判据（全部**读源**：账本行 ↔ Java 源码；本文件**不写死任何码集**）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | 账本行的**码集** == 该行落点方法**实际抛出的码集**（双向：账本多的码 / 源码多出来的码都红） | 从账本行删掉 `SET_ALREADY_COMPLETED` ⇒ 红（源码仍抛它）；源码删掉一个码而账本留着 ⇒ 红 |
| C2 | 账本声明的**状态码** == 源码真值（`BusinessException` 字面量构造的第 3 参 / 工厂方法 `validationError` 的 422） | 把账本的 `409 \`SET_ALREADY_COMPLETED\`` 改成 `422` ⇒ 红 |
| C3 | **判别力下界（反恒真）**：落点方法必须**真的**存在、必须**真的**抛过码、账本行必须**真的**登记过码；且 `SCAN_NEEDS_SELECTION` / `SET_ALREADY_COMPLETED` / `OPERATION_ALREADY_ADVANCED` 三条**各自**都要在账本行里带状态码出现 | 删掉账本那一行 ⇒ 红；把方法体清空 ⇒ 红 |
| C4 | **注入式自证**：C1/C2 的判定函数在**构造的**缺陷载荷上必须报错；同一载荷不注入 ⇒ 通过 | 见 `TestGuardSelfProof`（证明主测试的绿不是空跑） |
| C5 | **已核但有意不入账本的码要显式登记**：`NO_PENDING_OPERATION` 是同方法的第 4 个码，但当前实现下 `scan.get("operation") == null` 只有两个可达形态（旧码降级 ⇒ 更早的 `SCAN_NEEDS_SELECTION`；本套已完成 ⇒ `SET_ALREADY_COMPLETED`）⇒ 它**结构性不可达**，故不入账本。本守卫要求它在 `KNOWN_UNLEDGERED` 里**写明理由**（源码里悄悄新增第 4 条可达码 ⇒ 红，逼人重新核实） | 见 `test_no_pending_operation_is_declared_unreachable` |

## 引用纪律（本仓红线）

落点一律写**符号引用**（`类名#方法名`），**禁写** `path:行号` / 裸 `第 N 行` ——
drift 面 `ref-freshness` 与 Case Trust 规则 G 会把裸行号判红（dev-flow §16.7）。
本文件读 Java 源**按符号定位**（方法签名 + 花括号配平），不按行号。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

LEDGER = REPO / "docs" / "wiki" / "CONTRACT-LEDGER.md"
SERVICE_DIR = REPO / "backend/admin-api/src/main/java/com/migao/admin/service"
BUSINESS_EXCEPTION = REPO / "backend/admin-api/src/main/java/com/migao/admin/exception/BusinessException.java"

#: 被判的账本行（**文本锚点**，不写行号 —— 行号会随文档编辑腐烂）
SCAN_COMPLETE_ROW = "工人端扫码完成"

#: 落点映射：账本行 → [(服务类名, 方法名)]。**符号引用**，读源时按方法签名定位。
#: 为什么要显式映射：判据是「账本行的码集 == 这些方法抛出的码集」，映射本身是**判据的一部分**
#: （漏一个落点 ⇒ 漏一个码，这正是 #4843 要治的形态）。
ROW_SITES: dict[str, list[tuple[str, str]]] = {
    SCAN_COMPLETE_ROW: [
        ("ProductionScanCompleteService", "doComplete"),
        # 落点 (a)：账本按 #4843 的符号引用写 `ProductionService#applyScanComplete`，而 CAS
        # `advanceDoneQtyIfUnchanged` 的抛点在同类的**私有** `applyReport`（`applyScanComplete`
        # 只是 `@Transactional` 薄壳，**逐字**委派给它；两条报工路径共用同一份记账实现）。
        # 判据要落在**真抛点**上，故映射取 `applyReport`。
        ("ProductionService", "applyReport"),
    ],
}

#: 已核但**有意不入账本**的码：码 → 理由（空理由 ⇒ 红）。
#: `NO_PENDING_OPERATION`（422）是 `ProductionScanCompleteService#doComplete` 的第 4 个码，
#: 但 `scan.get("operation") == null` 当前只有两个可达形态：旧码降级（`granularity="order"`
#: ⇒ 更早的 `SCAN_NEEDS_SELECTION`）/ 本套已完成（⇒ `SET_ALREADY_COMPLETED`）⇒ 该分支不可达。
#: 本单只登记**已核实可达**的三条码（issue #4843 要求「只补你核实过的」）。
KNOWN_UNLEDGERED: dict[str, str] = {
    "NO_PENDING_OPERATION": (
        "结构性不可达：operation 为 null 的两个形态分别被 SCAN_NEEDS_SELECTION（旧码降级）"
        "与 SET_ALREADY_COMPLETED（本套已完成）先行拦下 —— 源码里若新增第 3 个可达形态，"
        "本守卫的码集比对会红，届时重新核实后再决定是否入账本"
    ),
}

#: `#4843` 逐条核实的真值（**只用于 C3 的「三条各自带状态码出现」下界**，不用于判 C1 ——
#: C1 的码集一律从源码读，本表**不写死**码集本身）。
REQUIRED_IN_ROW: tuple[tuple[str, int], ...] = (
    ("SCAN_NEEDS_SELECTION", 422),
    ("SET_ALREADY_COMPLETED", 409),
    ("OPERATION_ALREADY_ADVANCED", 409),
)

#: 账本行的**首个单元格**（`| **工人端扫码完成**（…） | …`）
_FIRST_CELL = re.compile(r"^\|\s*(?P<name>[^|]+?)\s*\|")
#: 账本行里以**反引号**标注的码（大写 + 下划线 + ≥4 位 —— 排除 `GRANULARITY_ORDER` 这类过短 token）
_CODE_TOKEN = re.compile(r"`([A-Z][A-Z0-9_]{3,})`")
#: 码**前**的状态码（取码前最后 60 字符里**紧邻**的 3 位数 —— 账本既有书写形态
#: `**409 \`CODE\`` / `旧码仍 **422 \`CODE\``：状态码与码之间**只允许**空白与 markdown 粗体星号）
_STATUS_BEFORE_CODE = re.compile(r"(\d{3})[\s*]*$")
#: Java 里 `new BusinessException("CODE", …)` 形态
_CODE_LITERAL = re.compile(r'new\s+BusinessException\(\s*"([A-Z][A-Z0-9_]*)"')
#: Java 里 `BusinessException.validationError(…)` 形态
_CODE_FACTORY = re.compile(r"BusinessException\.([a-zA-Z][A-Za-z0-9]*)\s*\(")
#: 工厂方法 → 状态码（从 `BusinessException` 源码读：`new BusinessException("VALIDATION_ERROR", message, 422)`）
_FACTORY_BODY = re.compile(
    r"public\s+static\s+BusinessException\s+(?P<name>\w+)\s*\([^)]*\)\s*\{(?P<body>.*?)\n\s*\}",
    re.S,
)
_FACTORY_STATUS = re.compile(r'new\s+BusinessException\(\s*"[A-Z][A-Z0-9_]*"\s*,[^;]*?,\s*(\d{3})', re.S)
_METHOD_SIG = r"^\s*(?:public|private|protected)\s+(?:static\s+)?[\w<>,.\[\]\s?]+?\s+%s\s*\([^;{]*\)\s*(?:throws\s+[\w,.\s]+)?\{"


# ── 读源（Java）────────────────────────────────────────────────────────────

def _method_body(class_name: str, method_name: str) -> str:
    """按**符号**取方法体（花括号配平）；取不到 ⇒ **直接失败**（不静默跳过）。"""
    path = SERVICE_DIR / f"{class_name}.java"
    assert path.is_file(), f"落点源码不存在：{path.relative_to(REPO)}（类被改名/搬走 ⇒ 请同步本守卫的 ROW_SITES）"
    src = path.read_text(encoding="utf8")
    hits = [m for m in re.finditer(_METHOD_SIG % re.escape(method_name), src, re.M)]
    assert len(hits) == 1, (
        f"{class_name}#{method_name} 在源码里命中 {len(hits)} 次（期望恰好 1）—— "
        "重载/改名都会让本守卫失去被测对象，请同步 ROW_SITES 与判据"
    )
    start = src.index("{", hits[0].start())
    depth = 0
    for idx in range(start, len(src)):
        if src[idx] == "{":
            depth += 1
        elif src[idx] == "}":
            depth -= 1
            if depth == 0:
                return src[start: idx + 1]
    raise AssertionError(f"{class_name}#{method_name} 的花括号不配平（源码被截断？）")


def _factory_statuses() -> dict[str, int]:
    """`BusinessException` 的工厂方法 → 状态码（**读源**，不写死 422）。"""
    src = BUSINESS_EXCEPTION.read_text(encoding="utf8")
    out: dict[str, int] = {}
    for m in _FACTORY_BODY.finditer(src):
        status = _FACTORY_STATUS.search(m.group("body"))
        if status:
            out[m.group("name")] = int(status.group(1))
    assert out, (
        "读不到 `BusinessException` 的工厂方法状态码映射（源码结构变了）—— "
        "取不到真值 ⇒ 本守卫不得静默放行"
    )
    return out


def _codes_thrown(class_name: str, method_name: str) -> dict[str, int]:
    """方法体里**实际抛出**的 `码 → 状态码`（字面量构造 + 工厂方法两种形态）。"""
    body = _method_body(class_name, method_name)
    factories = _factory_statuses()
    out: dict[str, int] = {}
    for code in _CODE_LITERAL.findall(body):
        m = re.search(
            rf'new\s+BusinessException\(\s*"{re.escape(code)}"\s*,(?P<rest>[^;]*?)\)\s*;',
            body,
            re.S,
        )
        assert m, f"读不出 {class_name}#{method_name} 里 {code} 的构造实参（源码结构变了）"
        status = re.search(r",\s*(\d{3})\s*(?:,|\))", m.group("rest"))
        out[code] = int(status.group(1)) if status else 400  # 2 参构造 = 400（BusinessException 源码真值）
    for name in set(_CODE_FACTORY.findall(body)):
        if name not in factories:
            continue  # 非「码工厂」（如 assertXxx 之类）不是抛出点
        # 该工厂在本方法里抛的码：取方法体里出现的、与该工厂同名的码常量 —— 见 _FACTORY_CODES
        for code in _FACTORY_CODES.get(name, ()):  # pragma: no cover - 由 _FACTORY_CODES 填
            if code in body:
                out[code] = factories[name]
    return out


def _factory_codes() -> dict[str, tuple[str, ...]]:
    """`BusinessException` 的工厂方法 → 它构造的码（**读源**：`new BusinessException("CODE", …)`）。"""
    src = BUSINESS_EXCEPTION.read_text(encoding="utf8")
    out: dict[str, tuple[str, ...]] = {}
    for m in _FACTORY_BODY.finditer(src):
        codes = _CODE_LITERAL.findall(m.group("body"))
        if codes:
            out[m.group("name")] = tuple(codes)
    return out


_FACTORY_CODES = _factory_codes()


# ── 读账本（markdown）──────────────────────────────────────────────────────

def _row(name: str, text: str | None = None) -> str:
    """按**首个单元格**取账本行；命中数 ≠ 1 ⇒ **直接失败**（锚点漂移不得退化成绿）。"""
    doc = text if text is not None else LEDGER.read_text(encoding="utf8")
    hits = []
    for line in doc.splitlines():
        if not line.startswith("|"):
            continue
        m = _FIRST_CELL.match(line)
        if m and name in m.group("name"):
            hits.append(line)
    assert len(hits) == 1, (
        f"账本里以「{name}」开头的行命中 {len(hits)} 条（期望恰好 1）—— "
        "行被改名/拆分/删除会让本守卫失去被测对象，请同步 SCAN_COMPLETE_ROW"
    )
    return hits[0]


def _ledger_codes(row: str) -> dict[str, int | None]:
    """账本行里的 `码 → 紧邻其前的状态码`（取不到状态码 ⇒ None，由 C2 判红）。

    只回看码前 60 字符，且取**最后一个**「3 位数 + 之后只剩空白/星号」的命中 ——
    `search` 会返回窗口里**第一个**命中（实测：`防呆⑤` 里的 `⑤` 被读成 `422` ⇒ 误判「没写状态码」）。

    ⚠️ **同一个码在行内可能出现多次**（本行的 `SCAN_NEEDS_SELECTION` 既是**声明**、又被后文
    「本行原只登记 …」**引用**一次）⇒ 只认**首个**出现（`setdefault`）：声明一定在最前，
    引用不带状态码。若取最后一次，引用会把声明的状态码顶掉 ⇒ 判据误红。
    """
    out: dict[str, int | None] = {}
    for m in _CODE_TOKEN.finditer(row):
        code = m.group(1)
        window = row[max(0, m.start() - 60): m.start()]
        hits = _STATUS_BEFORE_CODE.findall(window)
        out.setdefault(code, int(hits[-1]) if hits else None)
    return out


# ── 判定体（纯函数，供注入式自证复用）─────────────────────────────────────

def _row_drift(row: str, sites: list[tuple[str, str]]) -> list[str]:
    """C1 判定体：账本行码集 vs 落点方法实际抛出的码集（**双向**）⇒ 漂移清单。

    返回空列表 = 无漂移。抽成纯函数是**为了可注入自证**（自证直接喂构造载荷给同一个判定体，
    而不是另写一份"看起来像判据"的断言）。
    """
    drift: list[str] = []
    thrown: dict[str, int] = {}
    for class_name, method_name in sites:
        thrown.update(_codes_thrown(class_name, method_name))
    ledger = _ledger_codes(row)
    for code in sorted(set(ledger) - set(thrown)):
        drift.append(
            f"账本登记了 `{code}`，但落点方法一条都不抛它 —— "
            "账本说了源码不做的拒绝（凭空码），请核实后删码或修源码"
        )
    for code in sorted(set(thrown) - set(ledger)):
        if code in KNOWN_UNLEDGERED:
            continue
        drift.append(
            f"落点方法抛 `{code}`（{thrown[code]}），账本未登记 —— "
            "账本作为契约真值源不完整（issue #4843 的形态）"
        )
    return drift


def _status_drift(row: str, sites: list[tuple[str, str]]) -> list[str]:
    """C2 判定体：账本声明的状态码 vs 源码真值（逐条比对）。"""
    drift: list[str] = []
    thrown: dict[str, int] = {}
    for class_name, method_name in sites:
        thrown.update(_codes_thrown(class_name, method_name))
    for code, claimed in _ledger_codes(row).items():
        if code not in thrown:
            continue  # C1 已报「凭空码」
        if claimed is None:
            drift.append(f"账本登记了 `{code}` 但**没写状态码**（源码真值 {thrown[code]}）—— 状态码是契约的一部分")
        elif claimed != thrown[code]:
            drift.append(f"账本说 `{code}` = {claimed}，源码真值 = {thrown[code]}")
    return drift


# ── 主判据 ─────────────────────────────────────────────────────────────────

class TestScanCompleteRejectCodes:
    """`工人端扫码完成` 行的拒绝码契约（issue #4843）。"""

    def test_row_codes_match_source(self) -> None:
        """C1：账本行的码集 == 落点方法实际抛出的码集（双向）。"""
        drift = _row_drift(_row(SCAN_COMPLETE_ROW), ROW_SITES[SCAN_COMPLETE_ROW])
        assert drift == [], "账本行与源码漂移：\n  - " + "\n  - ".join(drift)

    def test_row_status_codes_match_source(self) -> None:
        """C2：账本声明的状态码 == 源码真值。"""
        drift = _status_drift(_row(SCAN_COMPLETE_ROW), ROW_SITES[SCAN_COMPLETE_ROW])
        assert drift == [], "状态码与源码漂移：\n  - " + "\n  - ".join(drift)

    def test_each_verified_code_is_declared_with_its_status(self) -> None:
        """C3：`#4843` 逐条核实的三条码**各自**都要在账本行里带状态码出现（判别力下界）。"""
        ledger = _ledger_codes(_row(SCAN_COMPLETE_ROW))
        missing = [
            f"`{code}`（{status}）"
            for code, status in REQUIRED_IN_ROW
            if ledger.get(code) != status
        ]
        assert not missing, (
            "账本行缺码或缺状态码：" + "、".join(missing) + " —— "
            "这正是 issue #4843 要治的缺口（账本作为契约真值源不完整）"
        )

    def test_guard_has_teeth(self) -> None:
        """C3：落点方法必须**真的**存在、**真的**抛过码（防「读不到 ⇒ 恒绿」）。"""
        for class_name, method_name in ROW_SITES[SCAN_COMPLETE_ROW]:
            thrown = _codes_thrown(class_name, method_name)
            assert thrown, (
                f"{class_name}#{method_name} 读不出任何拒绝码 —— "
                "要么源码结构变了、要么判据失去了被测对象（空面不得当绿读）"
            )

    def test_no_pending_operation_is_declared_unreachable(self) -> None:
        """C5：已核但有意不入账本的码必须写明理由（空理由 ⇒ 红）。"""
        for code, reason in KNOWN_UNLEDGERED.items():
            assert reason.strip(), f"`{code}` 登记为「不入账本」但没写理由 —— 豁免必须可复核"
        # 反向：豁免不得掩盖「源码真抛了它、账本也没有」的**可达**码
        thrown: dict[str, int] = {}
        for class_name, method_name in ROW_SITES[SCAN_COMPLETE_ROW]:
            thrown.update(_codes_thrown(class_name, method_name))
        for code in KNOWN_UNLEDGERED:
            assert code in thrown, (
                f"`{code}` 登记为「已核但有意不入账本」，但落点方法**已经不再抛它** —— "
                "该豁免已死，请从 KNOWN_UNLEDGERED 删除（死豁免会替未来的真缺口背书）"
            )


class TestGuardSelfProof:
    """C4 注入式自证：**同一个判定体**在构造的缺陷载荷上必须报错，否则主测试的绿是空跑。

    ⚠️ 自证必须复用被测判定体（`_row_drift` / `_status_drift`）—— 另写一份"看起来像判据"的
    断言只能证明「那段新代码会红」，证明不了主判据会红（`migao-acceptance`：不会红的断言 = 空断言）。
    """

    def _row_text(self) -> str:
        return _row(SCAN_COMPLETE_ROW)

    def test_clean_payload_passes(self) -> None:
        """反向：真实账本行 ⇒ 两个判定体都不得报漂移（证明红由注入引起）。"""
        row = self._row_text()
        sites = ROW_SITES[SCAN_COMPLETE_ROW]
        assert _row_drift(row, sites) == [], "真实账本行被判成漂移 ⇒ 判据误红"
        assert _status_drift(row, sites) == [], "真实账本行的状态码被判成漂移 ⇒ 判据误红"

    def test_c1_detects_missing_code_in_ledger(self) -> None:
        """C1 自证①：把 `SET_ALREADY_COMPLETED` 从账本行删掉 ⇒ 同一判定体必须报出来。

        载荷形态 = 逐字内联的真实片段删码后拼接（不读 `origin/main` —— 可变引用会让判据自红，
        dev-flow §18.3）。
        """
        sites = ROW_SITES[SCAN_COMPLETE_ROW]
        assert "SET_ALREADY_COMPLETED" in self._row_text(), "前提变了：账本行里没有该码，请同步本守卫"
        payload = self._row_text().replace("`SET_ALREADY_COMPLETED`", "`已删码`")
        drift = _row_drift(payload, sites)
        assert any("SET_ALREADY_COMPLETED" in d for d in drift), (
            f"删掉 `SET_ALREADY_COMPLETED` 后判定体没报出来：{drift} ⇒ C1 是空断言"
        )

    def test_c1_detects_code_source_no_longer_throws(self) -> None:
        """C1 自证②（反向）：账本登记一个源码**不抛**的码 ⇒ 判定体必须报「凭空码」。

        载荷形态 = 真实账本行 + 内联注入一条**构造的**码（不读 `origin/main` —— 可变引用会让
        判据自红，dev-flow §18.3）。为什么不用「少传一个落点」来构造：`OPERATION_ALREADY_ADVANCED`
        在**两个**落点都抛（这正是 #4843 登记 (a)/(b) 两条的原因）⇒ 少传一个落点**不是**缺陷载荷。
        """
        row = self._row_text()
        sites = ROW_SITES[SCAN_COMPLETE_ROW]
        phantom = "PHANTOM_CODE_4843"
        assert phantom not in row
        payload = row.rstrip(" |") + f" 另：**418 `{phantom}`**（构造的凭空码） |"
        drift = _row_drift(payload, sites)
        assert any(phantom in d for d in drift), (
            f"账本登记凭空码 `{phantom}` 后判定体没报出来：{drift} ⇒ C1 反向判据失效"
        )

    def test_c2_detects_wrong_status(self) -> None:
        """C2 自证：把账本的 `409` 改成 `422` ⇒ 同一判定体必须报状态码漂移。"""
        sites = ROW_SITES[SCAN_COMPLETE_ROW]
        row = self._row_text()
        payload = row.replace("**409 `SET_ALREADY_COMPLETED`**", "**422 `SET_ALREADY_COMPLETED`**")
        assert payload != row, "前提变了：账本行的书写形态改了（找不到 `**409 \\`CODE\\`**`），请同步本守卫"
        drift = _status_drift(payload, sites)
        assert any("SET_ALREADY_COMPLETED" in d for d in drift), (
            f"把状态码改成 422 后判定体没报出来：{drift} ⇒ C2 是空断言"
        )

    def test_c3_anchor_drift_fails_loudly(self) -> None:
        """C3 自证：账本行被删/改名 ⇒ `_row` 必须**失败**（不静默空跑）。"""
        import pytest

        with pytest.raises(AssertionError):
            _row(SCAN_COMPLETE_ROW, text="| **别的行** | `X` |\n")
