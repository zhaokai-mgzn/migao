"""术语表**单一真值源**守卫（issue #4454）。

## 病根

「AI 听不懂行话」是**知识问题**，不是后端派生问题：顾客/商家说「韩式褶」「纳米圈」时，
prompt 里没有「说法 → 内部参数」的对照，AI 就把**顾客原话**落进 `craft`
（`OrderLineCraftFields` 只搬运、不做枚举校验）⇒ 工序路线按 `部位 × 工艺` 索引取不到
⇒ 加工单与计件工资全错（V58 实证：纱帘订单拿到布帘的 11 道工序）。

## 本文件锁什么

**单一真值源**：`docs/curtain-production-rules.md` §8「术语表（AI 词汇底座，跨模块统一）」
里的两行（`工艺 / 安装工艺`、`四爪钩 / 四叉钩`）是**权威源**；
两条下单采集 prompt 的「术语映射」段（C 端 `customer_order` 内联 + B 端 `prompts/order.md`）
必须与它**逐条一致**，且**不得**出现真值源之外的映射。

判据（每条都能红）：
1. §8 两行可解析 ⇒ 得到 {内部值: {口语说法…}}（真值源被改坏/删行 ⇒ 红）；
2. 两条 prompt 的**表格数据行逐字相同**（各自漂移 ⇒ 红）；
3. 每行的口语说法 ⊆ 真值源（prompt 自创术语 ⇒ 红）；
4. 真值源的每个口语说法都出现在 prompt 里（漏抄 ⇒ 红）；
5. 两维度都在（部位：布帘/纱帘/帘头；工艺：韩褶/打孔/穿杆/平幔/四爪钩⇒韩褶）⇒ 缺维度红；
6. 两段都声明「与 §8 同源、不得自行增改」（防有人把段落改成第二份真值源）；
7. **知识卡片**（`knowledge-templates/curtain/template.json`）内置同一条行业知识
   ⇒ 缺条目红；其 keywords 覆盖 §8 的口语说法（`knowledge_search` 是 title/keywords/
   question/answer 的 LIKE 检索 ⇒ 命中即「可检索到」）。

## 为什么不是空断言

判据 3/4 是**双向包含**：任一侧漂移都会红（只查「prompt 有 §8 的东西」会漏掉
「prompt 自创了一个 §8 没有的术语」这一半）。判据 6 防「把 prompt 段落改成新的真值源」
（那会让 §8 变成装饰）。红证见本文件 `test_guard_self_evident_*`（注入式自证）。
"""
# case_ids: OR-037
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TRUTH_SOURCE = REPO_ROOT / "docs" / "curtain-production-rules.md"
B_ORDER_PROMPT = (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph"
                  / "skills" / "references" / "prompts" / "order.md")
KNOWLEDGE_TEMPLATE = (REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources"
                      / "knowledge-templates" / "curtain" / "template.json")

TERM_SECTION_HEAD = "## 术语映射"
SECTION_END_RE = re.compile(r"^## ", re.M)

# 真值源 §8 里承载**工艺词汇**的两行（判据 1 的锚点）。
TRUTH_CRAFT_ROW = "工艺 / 安装工艺"
TRUTH_HOOK_ROW = "四爪钩 / 四叉钩"

# 工艺维度的合法内部值（真值源 §8 工艺行 + 四爪钩行的裁定目标）。
CANONICAL_CRAFT_VALUES = {"韩褶", "打孔", "穿杆", "平幔", "四爪钩"}
# 部位维度的合法内部值（真值源 §8「部位 / 帘种」行）。
CANONICAL_PART_VALUES = {"布帘", "纱帘", "帘头"}
# 两段必须带的同源声明（判据 6）。
SINGLE_SOURCE_NOTICE = "curtain-production-rules.md` §8 同源"


def _section(text: str, head: str) -> str:
    """取 `head` 开头的段（到下一个 `## ` 为止）。缺失 ⇒ 抛 AssertionError（红，不静默跳过）。"""
    i = text.find(head)
    assert i >= 0, f"找不到段落 {head!r}（段落被删/改名 ⇒ 本守卫失效，判红）"
    m = SECTION_END_RE.search(text, i + len(head))
    return text[i:(m.start() if m else len(text))]


def _prompt_term_section(path: Path) -> str:
    return _section(path.read_text(encoding="utf-8"), TERM_SECTION_HEAD)


def _c_end_term_section() -> str:
    """C 端小布下单采集 prompt 的术语映射段（内联 L4，`SkillConfig.system_prompts`）。"""
    from app.graph.skills.customer_order_skill import CUSTOMER_ORDER_SYSTEM_PROMPT

    return _section(CUSTOMER_ORDER_SYSTEM_PROMPT, TERM_SECTION_HEAD)


def _table_data_rows(section: str) -> list:
    """段内 markdown 表格的**数据行**（跳过表头与分隔行）。"""
    rows = [ln.strip() for ln in section.splitlines()
            if ln.strip().startswith("|") and ln.strip().endswith("|")]
    data = []
    for ln in rows:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if not cells or set("".join(cells)) <= set("-: "):
            continue
        if cells[0] in ("维度",):
            continue
        data.append(cells)
    return data


def _canonical_cell(cell: str) -> str:
    """prompt 表格「内部值」单元格 → 纯内部值（取 `code` 反引号里的值）。"""
    m = re.search(r"`([^`]+)`", cell)
    return (m.group(1) if m else cell).strip()


def _truth_craft_pairs() -> dict:
    """§8 两行 → `{内部值: {口语说法…}}`（真值源解析，判据 1/3/4 的基线）。

    ⚠️ 解析**不依赖行尾标点**（`：…——` 这种形态随措辞漂移）：工艺行直接取该行里
    `` `反引号` `` 包住的 token，只保留**合法内部值**那些 ⇒ 行内其它反引号内容
    （如 `production_routings.craft`）不会污染结果。
    """
    truth = _section(TRUTH_SOURCE.read_text(encoding="utf-8"), "## 8. 术语表")
    rows = {}
    for ln in truth.splitlines():
        if not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) != 2:
            continue
        # §8 用 `**加粗**` 标关键行（如 `**配布边**`）⇒ 归一掉标记再比对键
        key = cells[0].replace("**", "").strip()
        rows[key] = cells[1]

    assert TRUTH_CRAFT_ROW in rows, (
        f"真值源 §8 缺「{TRUTH_CRAFT_ROW}」行 —— 工艺词汇没有权威源（issue #4454 补录的那行被删？）")
    assert TRUTH_HOOK_ROW in rows, f"真值源 §8 缺「{TRUTH_HOOK_ROW}」行"

    craft_row = rows[TRUTH_CRAFT_ROW]
    pairs = {}
    # 括注里「口语 A/B/C」形式的等价说法（如 `打孔`（口语 罗马圈/眼环/纳米圈））
    for tok in re.finditer(r"`([^`]+)`（([^）]*)）", craft_row):
        core = tok.group(1).strip()
        if core not in CANONICAL_CRAFT_VALUES:
            continue
        inner = tok.group(2)
        pairs.setdefault(core, set()).add(core)          # 内部值自身也是合法说法
        m_spoken = re.search(r"口语\s*([^；;）]+)", inner)
        if m_spoken:
            pairs[core].update(t.strip() for t in m_spoken.group(1).split("/")
                               if t.strip() and "`" not in t)
        # 「= X」等价说法（如 `平幔`（= 罗马帘））；**不得**把「指向主线 `韩褶`」这类
        # 交叉引用当成等价说法 ⇒ 只取不含反引号、且被标点界定的 token
        pairs[core].update(
            t for t in re.findall(r"=\s*([^\s、；;），。]+)", inner) if "`" not in t)
    assert set(pairs) >= {"韩褶", "打孔", "穿杆", "平幔"}, (
        f"§8 工艺行没解析出四个内部值（解析到 {sorted(pairs)}）—— 行格式变了？"
        f"原文：{craft_row[:160]!r}")
    assert {"韩式褶", "S钩", "调节钩"} <= pairs["韩褶"], (
        f"§8 工艺行的 `韩褶` 括注里没有口语清单（解析到 {sorted(pairs['韩褶'])}）")

    # 四爪钩行：`口语「四爪钩 / 四叉钩 / 普通挂钩」指向**主线工艺 `韩褶`**`
    # ⚠️ 必须锚到「」+ 指向（行内还有其它 `反引号` 片段，如 `布帘×四爪钩`；
    #    只写 `口语「(.+?)」` 会越过第一个 `」` 一直吃到行内后一个 `」`）。
    hook_row = rows[TRUTH_HOOK_ROW]
    m = re.search(r"口语「([^」]+)」", hook_row)
    assert m, f"§8「{TRUTH_HOOK_ROW}」行的口语清单形态变了（正则取不到）⇒ 判红"
    hooks = {t.strip() for t in m.group(1).split("/") if t.strip() and "`" not in t}
    assert hooks, f"§8「{TRUTH_HOOK_ROW}」行解析不出任何口语说法 ⇒ 判红"
    m2 = re.search(r"主线工艺\s*`([^`]+)`", hook_row)
    assert m2, f"§8「{TRUTH_HOOK_ROW}」行没写它指向哪个主线工艺 ⇒ 判红"
    target = m2.group(1)
    assert target in pairs, f"§8 四爪钩行指向的 {target!r} 不在工艺行取值里"
    pairs[target] |= hooks
    return pairs


def _prompt_rows_with_dims() -> dict:
    """两条 prompt 的术语映射表格数据行（判据 2/3/4/5）。"""
    return {
        "customer_order(C 端小布内联)": _table_data_rows(_c_end_term_section()),
        "prompts/order.md(B 端米宝)": _table_data_rows(
            _prompt_term_section(B_ORDER_PROMPT)),
    }


# ── 判据 1：真值源可解析，且两维度都在 ────────────────────────────────────────
def test_truth_source_glossary_is_parseable_and_covers_both_dimensions():
    pairs = _truth_craft_pairs()
    assert set(pairs) >= {"韩褶", "打孔", "穿杆", "平幔"}, (
        f"§8 工艺行没覆盖四个内部值（解析到 {sorted(pairs)}）")
    assert pairs["韩褶"] >= {"四爪钩", "四叉钩", "普通挂钩"}, (
        "§8 四爪钩行必须把「四爪钩/四叉钩/普通挂钩」指向 韩褶（V63 语义冻结）")
    assert pairs["平幔"] >= {"罗马帘"}, "§8 平幔行必须写明口语「罗马帘」"


# ── 判据 2：两条 prompt 的表格逐字相同 ────────────────────────────────────────
def test_both_prompts_share_byte_identical_table():
    rows = _prompt_rows_with_dims()
    names = list(rows)
    a, b = rows[names[0]], rows[names[1]]
    assert a, f"{names[0]} 的术语映射段没有表格数据行（段落被删？）"
    assert a == b, (
        f"两条下单采集 prompt 的术语映射表**漂移**了（{names[0]} vs {names[1]}）：\n"
        f"  {names[0]}: {a}\n  {names[1]}: {b}\n"
        f"⇒ 修法：两处同步（内容同源，只有 persona 措辞可不同）")


# ── 判据 3：每行口语说法 ⊆ 真值源（不许自创） ──────────────────────────────────
def test_prompt_terms_are_all_traceable_to_truth_source():
    pairs = _truth_craft_pairs()
    # 内部值自身也是合法「说法」（AI 从别的上下文拿到内部值时原样落参）
    allowed = set(pairs) | set().union(*pairs.values()) if pairs else set()
    for name, rows in _prompt_rows_with_dims().items():
        for dim, spoken, internal in rows:
            core = _canonical_cell(internal)
            assert core in CANONICAL_CRAFT_VALUES | CANONICAL_PART_VALUES, (
                f"{name}: 内部值 {core!r} 不是合法内部值"
                f"（工艺 {sorted(CANONICAL_CRAFT_VALUES)} / 部位 {sorted(CANONICAL_PART_VALUES)}）")
            if core in CANONICAL_PART_VALUES:
                continue
            assert core in pairs, f"{name}: 工艺内部值 {core!r} 不在真值源 §8"
            for term in (t.strip() for t in spoken.split("/")):
                if not term:
                    continue
                assert term in pairs[core], (
                    f"{name}: 口语「{term}」在真值源 §8 里**没有**映射到 {core!r}"
                    f"（§8 该值只认 {sorted(pairs[core])}）—— prompt 不得自创术语；"
                    f"要么从 prompt 删掉，要么先在 §8 补录")


# ── 判据 4：真值源的每个口语说法都出现在 prompt 里（不许漏抄） ──────────────────
def test_prompt_covers_every_truth_source_term():
    pairs = _truth_craft_pairs()
    for name, rows in _prompt_rows_with_dims().items():
        spoken_all = set()
        for dim, spoken, internal in rows:
            if _canonical_cell(internal) in CANONICAL_CRAFT_VALUES:
                spoken_all |= {t.strip() for t in spoken.split("/") if t.strip()}
        for core, terms in pairs.items():
            for term in sorted(terms - {core}):
                assert term in spoken_all, (
                    f"{name}: 真值源 §8 的口语「{term}」（→ {core}）**漏抄**了 —— "
                    f"漏抄 = AI 听不懂这个说法（本单要治的正是这个）")


# ── 判据 5：两个维度都在（部位 + 工艺） ──────────────────────────────────────
def test_both_dimensions_present():
    for name, rows in _prompt_rows_with_dims().items():
        dims = {r[0] for r in rows}
        assert dims == {"部位", "工艺"}, f"{name}: 维度不齐（实际 {sorted(dims)}）"
        parts = {_canonical_cell(r[2]) for r in rows if r[0] == "部位"}
        crafts = {_canonical_cell(r[2]) for r in rows if r[0] == "工艺"}
        assert parts == CANONICAL_PART_VALUES, f"{name}: 部位维度不齐（{sorted(parts)}）"
        assert {"韩褶", "打孔", "穿杆", "平幔"} <= crafts, f"{name}: 工艺维度不齐（{sorted(crafts)}）"


# ── 判据 6：两段都声明单一真值源 ─────────────────────────────────────────────
def test_both_sections_declare_the_single_source():
    for name, section in (
        ("customer_order(C 端小布内联)", _c_end_term_section()),
        ("prompts/order.md(B 端米宝)", _prompt_term_section(B_ORDER_PROMPT)),
    ):
        assert SINGLE_SOURCE_NOTICE in section, (
            f"{name}: 术语映射段缺少「与 {SINGLE_SOURCE_NOTICE}」声明 —— "
            f"没有它，这段就变成**第二份真值源**（漂移无人拦）")


# ── 判据 7：知识卡片内置同一条行业知识，且 keywords 可被 LIKE 检索命中 ─────────
def _glossary_card() -> dict:
    data = json.loads(KNOWLEDGE_TEMPLATE.read_text(encoding="utf-8"))
    hits = [e for e in data.get("entries") or []
            if "术语" in str(e.get("title") or "")]
    assert hits, (
        "知识模板里没有「行业术语」条目 —— 用户点名的容器（知识卡片内置行业知识）缺内容；"
        f"文件：{KNOWLEDGE_TEMPLATE.relative_to(REPO_ROOT)}")
    return hits[0]


def test_knowledge_card_contains_industry_glossary():
    card = _glossary_card()
    haystack = " ".join(str(card.get(k) or "")
                        for k in ("title", "question", "answer", "keywords"))
    pairs = _truth_craft_pairs()
    for core, terms in pairs.items():
        assert core in haystack, f"知识卡片缺内部值「{core}」"
        for term in sorted(terms - {core}):
            assert term in haystack, f"知识卡片缺口语「{term}」（→ {core}）"
    for part in CANONICAL_PART_VALUES:
        assert part in haystack, f"知识卡片缺部位「{part}」"


def test_knowledge_card_is_retrievable_by_colloquial_query():
    """`knowledge_search` 是 title/keywords/question/answer 的 **LIKE 子串**检索
    （`KnowledgeCardService.doSearch`）⇒ 顾客原话必须作为子串出现在卡片可检索字段里。
    """
    card = _glossary_card()
    searchable = [str(card.get(k) or "") for k in ("title", "keywords", "question", "answer")]
    queries = [
        # 本单验收判据点名的两条行话
        "韩式褶", "纳米圈",
        # 其余真值源口语（逐条可检索）
        *sorted(set().union(*_truth_craft_pairs().values())
                 - set(_truth_craft_pairs())),
        # 部位维度
        *sorted(CANONICAL_PART_VALUES),
    ]
    for q in sorted(set(queries)):
        assert any(q in field for field in searchable), (
            f"knowledge_search(query={q!r}) 命中不了该卡片 —— 检索是 LIKE 子串匹配，"
            f"该词必须出现在 title/keywords/question/answer 之一")


# ── 注入式红证（自证判据真的会红，不是空断言） ────────────────────────────────
def _allowed_spoken() -> set:
    """真值源允许的「说法」集合（内部值自身 + 口语）。"""
    pairs = _truth_craft_pairs()
    return set(pairs) | set().union(*pairs.values())


def test_guard_self_evident_table_drift_is_detected():
    """把 C 端表的一行改掉 ⇒ 判据 2 必须红（证明「逐字相同」不是恒真）。"""
    section = _c_end_term_section()
    drifted = section.replace("| 工艺 | 韩式褶 / S钩 / 调节钩 | `韩褶` |",
                              "| 工艺 | 韩式褶 | `波浪褶` |")
    assert drifted != section, "注入点没命中（表格行被改过 ⇒ 本自证失效，需同步注入串）"
    assert _table_data_rows(section) != _table_data_rows(drifted), (
        "注入后表格数据行没变 ⇒ 判据 2 抓不到这次漂移（空断言）")


def test_guard_self_evident_extra_term_is_detected():
    """prompt 自创一个真值源没有的口语 ⇒ 判据 3 必须红。"""
    allowed = _allowed_spoken()
    assert "波浪褶" not in allowed, "「波浪褶」不该在真值源里（注入式自证的前提）"
    # 判据 3 的判定式：注入的「波浪褶 → 韩褶」必须被判不合法
    pairs = _truth_craft_pairs()
    assert "波浪褶" not in pairs["韩褶"], (
        "判据 3 会把注入的「波浪褶」判成合法 ⇒ 该判据失去判别力（空断言）")


def test_guard_self_evident_missing_dimension_is_detected():
    """删掉整个「部位」维度 ⇒ 判据 5 必须红。"""
    section = _c_end_term_section()
    stripped = "\n".join(ln for ln in section.splitlines()
                         if not ln.strip().startswith("| 部位 "))
    assert stripped != section, "注入点没命中（部位行被改过 ⇒ 自证失效）"
    dims = {r[0] for r in _table_data_rows(stripped)}
    assert dims == {"工艺"}, f"注入后维度应只剩工艺，实际 {sorted(dims)}"


def test_guard_self_evident_missing_notice_is_detected():
    """删掉同源声明 ⇒ 判据 6 必须红。"""
    section = _c_end_term_section()
    assert SINGLE_SOURCE_NOTICE in section
    assert SINGLE_SOURCE_NOTICE not in section.replace(SINGLE_SOURCE_NOTICE, "")


def test_guard_self_evident_missing_truth_row_is_detected():
    """删掉真值源 §8 的工艺行 ⇒ 判据 1 必须红（不是静默「解析不到就跳过」）。"""
    truth = TRUTH_SOURCE.read_text(encoding="utf-8")
    stripped = "\n".join(ln for ln in truth.splitlines()
                         if not ln.lstrip().startswith(f"| **{TRUTH_CRAFT_ROW}**"))
    assert stripped != truth, "注入点没命中（§8 工艺行被改过 ⇒ 自证失效）"
    section = _section(stripped, "## 8. 术语表")
    keys = {c.strip().replace("**", "") for c in
            (ln.strip().strip("|").split("|")[0] for ln in section.splitlines()
             if ln.strip().startswith("|"))}
    assert TRUTH_CRAFT_ROW not in keys, "注入后真值源仍含工艺行 ⇒ 自证失效"


@pytest.mark.parametrize("path", [TRUTH_SOURCE, B_ORDER_PROMPT, KNOWLEDGE_TEMPLATE])
def test_guard_paths_exist(path):
    """守卫读的文件必须在（路径打错 ⇒ fail-closed，而不是静默「通过」）。"""
    assert path.exists(), f"守卫依赖的文件不存在：{path}"
