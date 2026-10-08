# case_ids: PR-016
"""商品状态的**类级元守卫**（issue #6347 Part A）——让「非法状态值」这类缺陷进不来。

## 三件事（各对应一条判据）

1. **单一真值源**：商品状态的**合法集合**与**流转表**只在
   `backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java` 定义一次
   （`STATUS_TRANSITIONS` 的键集；`PRODUCT_STATUSES` 必须是它的**派生**，不是第二份字面量）；
   建品/改品入口都必须走 `requireValidStatusOrNull`（接线文本锚，不写行号）。
2. **所有写入方取值都在集合内**：扫「写入面」（文件含 `POST/PUT /api/admin/products` 端点字面量）
   里给商品 status 赋的**字符串字面量** ⇒ 必须 ⊆ 合法集合。
   *这条判据对**仓内真实语料**生效（含 `acceptance/**` 的 harness）*：
   本单的引信就是 `acceptance/2026-10-04/worker-miniapp-sweep/harness/bootstrap-chain.mjs`
   建品写 `status: 'active'`。
3. **未登记即红**：检出到的写入方文件集与台账
   `tests/unit_ci_workflows/product_status_write_sites.json` **双向相等**
   （新写入方未登记 ⇒ 红；陈旧条目 ⇒ 红 —— 台账只许缩短）。

## 边界（照实登记，§19.1）

- 只覆盖**可静态检出**的写入面：靠变量 / 函数参数下传的 status 字面量不被检出
  （那类由新加的运行期 fail-closed 准入兜底：非法值必 4xx）。
- Java 侧写入由判据 1 的接线锚 + `ProductStatusAdmissionTest` 的实例判据承担，不重复判。
- 「存量死状态行的回填口径」不在本守卫射程内（人工裁定）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = Path(__file__).resolve().parent / "product_status_write_sites.json"
PRODUCT_SERVICE_REL = "backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java"
MAIN_JAVA_DIR = REPO_ROOT / "backend/admin-api/src/main/java"

EXPECTED_STATUSES = {"draft", "under_review", "on_sale", "off_sale"}

#: 写入面 = 出现商品写端点字面量的文件（POST/PUT/PATCH /api/admin/products...）
PRODUCT_ENDPOINT = "/api/admin/products"
SCAN_EXTS = {".mjs", ".js", ".ts", ".tsx", ".py"}
#: 守卫**自身**不参与「写入方」扫描：它的判别力样本是**内存里的 synthetic 文本**，
#: 刻意含 `status: 'on_shelf'` / `status: 'active'` 这类非法字面量（那是装置，不是写入方）。
SELF_REL = "tests/unit_ci_workflows/test_product_status_single_source.py"
SKIP_DIR_NAMES = {
    ".git", "node_modules", "out", "dist", "target", ".venv", "venv",
    "__pycache__", ".next", "coverage", ".pytest_cache",
}

#: 商品专属键（决定一个对象字面量是不是**商品写 body**）。
#: 刻意不用 `unit` / `basePrice` / `productId`：它们在订单 / 加工单 / 售后对象里同样常见，
#: 会把这些对象的 `status`（processing / pending …）误判成商品状态。
PRODUCT_MARKERS_RE = re.compile(
    r"\b(pricingType|sellingMethods|doorWidths|rollLengthM|stockDeductionMode"
    r"|stockWarningThreshold|totalStock|allowReturnRestock)\b\s*:"
)
STATUS_KEY_RE = re.compile(r"""(?<![\w$])["']?status["']?\s*:""")
STR_LIT_RE = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"")
TRANSITION_RE = re.compile(r'STATUS_TRANSITIONS\.put\(\s*"([a-z_]+)"')
LABEL_BLOCK_RE = re.compile(r"PRODUCT_STATUS_LABELS\s*=\s*Map\.of\((.*?)\);", re.S)
LABEL_ENTRY_RE = re.compile(r'"([a-z_]+)",\s*"[^"]+"')
SINGLE_SOURCE_RE = re.compile(
    r"PRODUCT_STATUSES\s*=\s*Collections\.unmodifiableSet\(new LinkedHashSet<>\(STATUS_TRANSITIONS\.keySet\(\)\)\)"
)
COLLECTION_LITERAL_RE = re.compile(r"(Set|List|Map)\.of\(")


# --------------------------------------------------------------------------- #
# 检出台账（写入方）—— 检测器本体
# --------------------------------------------------------------------------- #

def _enclosing_object_start(text: str, idx: int) -> int | None:
    """从 `idx` 往前找**最内层**未闭合的 `{`（粗粒度：不解析字符串/注释，语料上够用）。"""
    depth = 0
    i = idx
    while i >= 0:
        ch = text[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                return i
            depth -= 1
        i -= 1
    return None


def _status_value_end(text: str, start: int) -> int:
    """status 值表达式的结束位置（顶层 `,` 或 `}`）。"""
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        i += 1
    return i


def product_status_literals(text: str) -> list[tuple[int, list[str]]]:
    """返回 `[(行号, [status 字面量, ...]), ...]` —— 只取落在**商品写 body** 里的那些。"""
    found: list[tuple[int, list[str]]] = []
    for m in STATUS_KEY_RE.finditer(text):
        end = _status_value_end(text, m.end())
        literals = [a or b for a, b in STR_LIT_RE.findall(text[m.end():end])]
        literals = [x for x in literals if x]
        if not literals:
            continue
        obj_start = _enclosing_object_start(text, m.start())
        if obj_start is None:
            continue
        if not PRODUCT_MARKERS_RE.search(text[obj_start:m.end()]):
            continue
        found.append((text.count("\n", 0, m.start()) + 1, literals))
    return found


def detected_write_sites(root: Path = REPO_ROOT) -> dict[str, list[tuple[int, list[str]]]]:
    """现取：写入面文件 → 检出到的 status 字面量位点。"""
    sites: dict[str, list[tuple[int, list[str]]]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix not in SCAN_EXTS:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if PRODUCT_ENDPOINT not in text:
                continue
            rel = str(path.relative_to(root))
            if rel == SELF_REL:
                continue
            literals = product_status_literals(text)
            if literals:
                sites[rel] = literals
    return sites


def illegal_literals(sites: dict[str, list[tuple[int, list[str]]]], legal: set[str]):
    problems = []
    for rel, per_line in sorted(sites.items()):
        for line, literals in per_line:
            bad = [x for x in literals if x not in legal]
            if bad:
                problems.append(f"{rel}:{line} {bad}")
    return problems


# --------------------------------------------------------------------------- #
# 判据
# --------------------------------------------------------------------------- #

def _product_service_text() -> str:
    return (REPO_ROOT / PRODUCT_SERVICE_REL).read_text(encoding="utf-8")


def test_legal_status_set_has_exactly_one_definition():
    """判据 1：合法集合 / 流转表只有一处定义，且入口都走同一条准入。"""
    text = _product_service_text()
    transitions = set(TRANSITION_RE.findall(text))
    label_block = LABEL_BLOCK_RE.search(text)
    if label_block is None:
        raise AssertionError("ProductService 里找不到 PRODUCT_STATUS_LABELS 定义")
    labels = set(LABEL_ENTRY_RE.findall(label_block.group(1)))

    assert transitions == EXPECTED_STATUSES, f"流转表键集变了：{sorted(transitions)}"
    assert labels == transitions, (
        f"流转表键集 {sorted(transitions)} 与中文标签键集 {sorted(labels)} 不一致 —— 合法集合被写成了两份"
    )
    assert SINGLE_SOURCE_RE.search(text), (
        "PRODUCT_STATUSES 必须由 STATUS_TRANSITIONS.keySet() 派生（单一真值源），不得另起一份字面量"
    )
    # 建品 + 改品两个入口都要走枚举准入（接线文本锚；不写行号）
    assert text.count('requireValidStatusOrNull(request.getStatus(), "商品状态 status")') == 2, (
        "createProduct / updateProduct 必须各走一次 requireValidStatusOrNull（漏一处 = 那一侧仍可落非法值）"
    )


def test_legal_status_set_is_not_redeclared_elsewhere_in_main_java():
    """判据 1b：admin-api 主源码里除 ProductService 外，不得再出现 ≥3 个状态 token 的集合字面量。"""
    offenders = []
    for path in MAIN_JAVA_DIR.rglob("*.java"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in COLLECTION_LITERAL_RE.finditer(text):
            window = text[m.end():m.end() + 400]
            tokens = {tok for tok in EXPECTED_STATUSES if f'"{tok}"' in window}
            if len(tokens) >= 3 and path.name != "ProductService.java":
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{text.count(chr(10), 0, m.start()) + 1} {sorted(tokens)}")
    assert not offenders, "商品状态集合被在 ProductService 之外又定义了一遍：\n" + "\n".join(offenders)


def test_corpus_product_status_literals_are_all_legal():
    """判据 2：**仓内真实语料**（含 acceptance/** harness）里商品 status 字面量都必须合法。"""
    legal = set(TRANSITION_RE.findall(_product_service_text()))
    problems = illegal_literals(detected_write_sites(), legal)
    assert not problems, (
        "商品 status 出现非法字面量（合法集合 = "
        + "/".join(sorted(legal))
        + "）：\n  "
        + "\n  ".join(problems)
    )


def test_write_site_registry_is_bidirectional():
    """判据 3：写入方台账 ⇄ 现取检出集 **双向相等**（未登记即红 / 陈旧条目即红）。"""
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    registered = {entry["path"] for entry in ledger["sites"]}
    assert registered, "台账为空 ⇒ fail-closed（清空台账不得把守卫变成空跑）"

    detected = set(detected_write_sites())
    unregistered = sorted(detected - registered)
    stale = sorted(registered - detected)
    assert not unregistered, (
        "检出到**未登记**的商品 status 写入方 ⇒ 请把它们登记进 "
        f"{LEDGER_PATH.name}（并在 PR body 写明取值合法）：\n  " + "\n  ".join(unregistered)
    )
    assert not stale, (
        "台账里有**已不存在**的写入方（陈旧条目）⇒ 台账只许缩短，请删除：\n  " + "\n  ".join(stale)
    )


def test_detector_discrimination_on_synthetic_text():
    """判别力自证：坏形态红、好形态绿、非商品对象不误报。"""
    cases = [
        (
            "harness 里的商品 body（非法值 ⇒ 必须检出）",
            "const b = { name: 'n', pricingType: 'fixed', basePrice: 1, status: 'on_shelf' }\n",
            ["on_shelf"],
        ),
        (
            "bootstrap-chain 形态（status:'active' ⇒ 必须检出）",
            "const prodBody = {\n  skuCode: 'X',\n  unit: '米',\n  pricingType: 'per_meter',\n"
            "  basePrice: 30.5,\n  status: 'active',\n  stock: 200,\n  doorWidths: ['2.8'],\n}\n",
            ["active"],
        ),
        (
            "合法值（检出但不判红）",
            "const b = { name: 'n', pricingType: 'fixed', status: 'on_sale' }\n",
            ["on_sale"],
        ),
        (
            "三元表达式里的两个字面量都要看",
            "const b = { unit: '米', sellingMethods: [], status: cid ? 'on_shelf' : 'draft' }\n",
            ["on_shelf", "draft"],
        ),
        (
            "分类 body（status:'active' 合法）⇒ 不是商品写入方，不得误报",
            "const cat = { name: 'n', level: 1, sort: 1, status: 'active' }\n",
            [],
        ),
        (
            "销售单 body（status:'processing'）⇒ 不得误报",
            "const o = { ticketType: 'return', description: 'x', status: 'processing' }\n",
            [],
        ),
        (
            "注释里的 status ⇒ 无商品 body 上下文，不得误报",
            "// status: 默认 draft\n",
            [],
        ),
    ]
    for title, text, expected in cases:
        got = [lit for _, lits in product_status_literals(text) for lit in lits]
        assert sorted(got) == sorted(expected), f"{title}：期望 {expected}，实得 {got}"


def test_real_corpus_injection_turns_the_guard_red():
    """真语料注入式红证：把**仓内真实文件**的合法值改回引信形态 ⇒ 检出并判非法。

    注入的自证对象 = `acceptance/2026-10-04/worker-miniapp-sweep/harness/bootstrap-chain.mjs`
    （issue #6347 点名的引信：建品写 `status: 'active'`）。
    """
    real = (
        REPO_ROOT
        / "acceptance/2026-10-04/worker-miniapp-sweep/harness/bootstrap-chain.mjs"
    ).read_text(encoding="utf-8")
    legal = set(TRANSITION_RE.findall(_product_service_text()))

    # 未注入 ⇒ 不报（反向对照）
    assert not illegal_literals({"bootstrap-chain.mjs": product_status_literals(real)}, legal)

    # 注入：把商品 body 的合法状态退回引信形态
    injected = real.replace("status: 'on_sale'", "status: 'active'", 1)
    assert injected != real, "注入未生效（没找到可注入的 status: 'on_sale'）"
    problems = illegal_literals({"bootstrap-chain.mjs": product_status_literals(injected)}, legal)
    assert problems, "注入后仍未判红 ⇒ 判据对该真实语料没有判别力"
    assert "active" in problems[0]
