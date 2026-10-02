# case_ids: MC-062
"""类级元守卫（issue #5983 铁律 8）：**列表页写按钮漏接权限**进不来。

病（#5983）：`(dashboard)/**/page.tsx` 的页面守卫取的是**读**码（`order:list` / `product:list` /
`inbound:view` …）⇒ 无写码的岗位也能进页面；而列表页上的「新增/新建…」按钮若不按写码显隐，
用户点进建单/建品页、填完表单**提交时才 403**（"白点一下"，按钮级权限未生效）。

判据（每条都会**具名**报出是哪个文件、哪一行）：
  1. **零命中 ⇒ 红**（fail-closed）：扫描面一个写按钮都找不到时判据自己失效了，不许静默绿。
  2. **未登记即红**：某页出现新增/新建类写按钮，文件里**没有** `hasPermission(...)` 引用，
     且不在豁免台账 `list_page_write_button_ledger.json` 里 ⇒ 红（这就是本单要防的形态）。
  3. **陈旧即红（台账只许缩短）**：台账条目对应的文件
     · 已经不存在 / 已经没有写按钮 / 已经接上 `hasPermission` ⇒ 红，必须删条目。
  4. **超预算即红**：条目数 > 冻结上限 `frozen_max_entries` ⇒ 红（新增豁免必须在 PR 里显式说明）。
  5. **判别力自证**：五种坏形态在**内存语料**上各自判红，另有一条**对照** ——
     合规语料 + 空台账 ⇒ **不红**（判据不许被自己的文案喂红）。

⚠️ 边界（如实登记）：判据只认「**整行就是**一个新增/新建标签」的 JSX 文本（可选前缀一个图标标签），
即本仓列表页按钮的既有写法（`<Plus … />\n新增商品`）。写在 JSX 表达式里（`{x ? '编辑' : '新建'}`）、
字符串里、或行内还跟着别的文字的形态**不在射程内**（本仓现取无此写法）；判据也判不了「该页**该不该**
有写码」（那是后端 `@RequirePermission` 与岗位矩阵的事）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = REPO_ROOT / "frontend" / "admin-web" / "src" / "app" / "(dashboard)"
LEDGER_PATH = Path(__file__).resolve().parent / "list_page_write_button_ledger.json"

# 「整行 = 一个新增/新建标签」（可选前缀一个自闭合/开标签，如 `<Plus className="…" /> 新建知识卡片`）
CREATE_LABEL_RE = re.compile(r"^\s*(?:<[^>]*>\s*)?(新增|新建)[^\s<>{}\"']*\s*$")
# 文件里任何一处 `hasPermission('x:y')` / `hasPermission("x:y")`（双引号一起认，避免写法漂移漏判）
GATE_RE = re.compile(r"hasPermission\(\s*[\"']([a-z_]+):([a-z_]+)[\"']")


def create_label_hits(source: str) -> list[tuple[int, str]]:
    """返回 [(行号, 标签文本)] —— 整行形态的新增/新建写按钮。"""
    hits: list[tuple[int, str]] = []
    for idx, line in enumerate(source.splitlines(), start=1):
        m = CREATE_LABEL_RE.match(line)
        if m:
            hits.append((idx, line.strip()))
    return hits


def scannable_pages() -> list[Path]:
    """扫描面 = `(dashboard)/**/page.tsx`，**排除** `…/new/page.tsx`（那是建单/建品**页本身**，不是列表页）。"""
    return sorted(p for p in DASHBOARD_DIR.rglob("page.tsx") if p.parent.name != "new")


def real_pages() -> dict[str, str]:
    return {p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf-8") for p in scannable_pages()}


def load_ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def problems(pages: dict[str, str], ledger: dict) -> list[str]:
    """纯函数：语料 + 台账 → 问题清单（空 = 通过）。所有分支都**具名**。"""
    out: list[str] = []
    entries = ledger.get("entries", [])
    budget = ledger.get("frozen_max_entries")
    if not isinstance(budget, int):
        out.append("台账缺 `frozen_max_entries`（冻结上限）—— 判据无法判「只许缩短」⇒ 红")
        return out

    ledger_paths: list[str] = []
    for entry in entries:
        path = entry.get("path", "")
        ledger_paths.append(path)
        if not entry.get("reason", "").strip():
            out.append(f"台账条目缺 `reason`（豁免必须写明理由）：{path or '<空 path>'}")
        if path not in pages:
            out.append(
                f"陈旧台账条目：{path!r} 不在扫描面（文件被删 / 改名 / 不在 (dashboard)/**/page.tsx）⇒ 请删条目"
            )

    if len(entries) > budget:
        out.append(
            f"台账 {len(entries)} 条 > 冻结上限 {budget} 条 —— 台账**只许缩短**；"
            "确需新增豁免时应在 PR 里显式说明并抬上限（本判据刻意让这一步看得见）"
        )

    total_hits = 0
    for path, source in sorted(pages.items()):
        hits = create_label_hits(source)
        total_hits += len(hits)
        if not hits:
            continue
        gated = bool(GATE_RE.search(source))
        if gated:
            if path in ledger_paths:
                out.append(
                    f"陈旧台账条目：{path} 已经接上 hasPermission(...) ⇒ 请从台账删掉该条（台账只许缩短）"
                )
            continue
        if path in ledger_paths:
            continue
        lines = ", ".join(f"{ln}:{label}" for ln, label in hits)
        out.append(
            f"未登记的写按钮：{path} 出现新增/新建类按钮（{lines}），"
            "但文件内没有 hasPermission(...) 引用、也不在豁免台账里 —— "
            "按 #5983 的范式应加 `const canWrite = hasPermission('<域>:create')` 并在无码时不渲染该按钮"
        )

    if total_hits == 0:
        out.append(
            "扫描面零命中（一个新增/新建按钮都没找到）—— 判据自己失效了（选择器 / 目录漂移），"
            "fail-closed 判红，不许静默绿"
        )
    return out


# ────────────────────────────── 真语料上的判据 ──────────────────────────────

def test_real_dashboard_pages_have_no_unregistered_write_button():
    pages = real_pages()
    assert len(pages) > 0, f"扫描面为空：{DASHBOARD_DIR}（目录 / 路径漂移 ⇒ 判据失效）"
    found = sorted(p for p, src in pages.items() if create_label_hits(src))
    assert len(found) > 0, f"零命中：扫描面 {len(pages)} 个 page.tsx 里没有识别出任何写按钮（判据失效）"
    print(f"[#5983] 扫描面 {len(pages)} 页；识别出写按钮的页面 {len(found)} 个：")
    for p in found:
        print(f"    · {p}")
    assert problems(pages, load_ledger()) == []


def test_three_fixed_pages_really_gate_their_write_button():
    """实例面（本单修的三页）：三张写码必须**逐字**出现在各自文件里（防「改回裸按钮但正好在台账里」）。"""
    pages = real_pages()
    expected = {
        "frontend/admin-web/src/app/(dashboard)/orders/page.tsx": "order:create",
        "frontend/admin-web/src/app/(dashboard)/products/page.tsx": "product:create",
        "frontend/admin-web/src/app/(dashboard)/inbound-orders/page.tsx": "inbound:create",
    }
    for path, code in expected.items():
        assert path in pages, f"{path} 不在扫描面"
        codes = {f"{a}:{b}" for a, b in GATE_RE.findall(pages[path])}
        assert code in codes, f"{path} 未接写码 {code}（实取 {sorted(codes)}）"


def test_ledger_budget_and_shape():
    ledger = load_ledger()
    assert ledger["frozen_max_entries"] == len(ledger["entries"]), (
        "冻结上限与当前条数不等：台账**只许缩短** ⇒ 修完一页必须同批把上限一起往下调"
    )
    assert 0 < ledger["frozen_max_entries"] <= 20, "上限必须是个**现取**出来的小数字，不是摆设"


# ──────────────────────── 判别力自证（内存语料，含对照） ────────────────────────

def _ledger(entries, budget=None):
    return {"frozen_max_entries": budget if budget is not None else len(entries), "entries": entries}


GOOD = {"frontend/admin-web/src/app/(dashboard)/products/page.tsx": "  const canWrite = hasPermission('product:create')\n  新增商品\n"}


def test_injected_bad_corpora_are_named():
    # ① 未登记即红（本单的缺陷形态：裸按钮、无 hasPermission、台账里也没有）
    bare = {"frontend/admin-web/src/app/(dashboard)/orders/page.tsx": "          新增订单\n"}
    p = problems(bare, _ledger([]))
    assert any("未登记的写按钮" in x and "orders/page.tsx" in x for x in p), p

    # ② 登记了就放过（豁免是台账的**正当**用途）
    assert problems(bare, _ledger([{"path": "frontend/admin-web/src/app/(dashboard)/orders/page.tsx", "reason": "存量"}])) == []

    # ③ 陈旧即红（已接码却还留在台账里 ⇒ 必须删条目）
    p = problems(GOOD, _ledger([{"path": "frontend/admin-web/src/app/(dashboard)/products/page.tsx", "reason": "存量"}]))
    assert any("已经接上 hasPermission" in x for x in p), p

    # ④ 台账条目指向不在扫描面的文件 ⇒ 红
    p = problems(GOOD, _ledger([{"path": "frontend/admin-web/src/app/(dashboard)/gone/page.tsx", "reason": "存量"}]))
    assert any("陈旧台账条目" in x and "gone/page.tsx" in x for x in p), p

    # ⑤ 超预算即红（只许缩短）
    p = problems(bare, {"frozen_max_entries": 0, "entries": [{"path": "frontend/admin-web/src/app/(dashboard)/orders/page.tsx", "reason": "存量"}]})
    assert any("只许缩短" in x for x in p), p

    # ⑥ 零命中即红（选择器 / 目录漂移 ⇒ fail-closed）
    p = problems({"frontend/admin-web/src/app/(dashboard)/dashboard/page.tsx": "export default function P() {}\n"}, _ledger([]))
    assert any("零命中" in x for x in p), p

    # ⑦ 缺 reason 即红
    p = problems(bare, _ledger([{"path": "frontend/admin-web/src/app/(dashboard)/orders/page.tsx", "reason": "  "}]))
    assert any("缺 `reason`" in x for x in p), p


def test_control_compliant_corpus_with_empty_ledger_is_green():
    """对照：合规语料 + 空台账 ⇒ **不红**（判据不许被自己的文案喂红 —— 注释里的「新增商品」不算按钮）。"""
    corpus = {
        "frontend/admin-web/src/app/(dashboard)/products/page.tsx": (
            "// 说明：本页的「新增商品」按钮按 product:create 显隐\n"
            "  const canWrite = hasPermission('product:create')\n"
            "        {canWrite && (\n"
            "          <Button onClick={() => router.push('/products/new')}>\n"
            "            <Plus className=\"w-4 h-4 mr-1.5\" />\n"
            "            新增商品\n"
            "          </Button>\n"
            "        )}\n"
        ),
        "frontend/admin-web/src/app/(dashboard)/dashboard/page.tsx": "export default function P() { return null }\n",
    }
    assert problems(corpus, _ledger([])) == []
