# case_ids: OR-029, OR-016, OR-017, CU-003, CH-010, PR-012
"""用例罐头输入点名的 seed 类实体，必须在评测栈 seed 真值里存在（issue #4064，L0 静态）。

## 病根（OR-029 / #4015 暴露的**缺陷类别**）

`OR-029` 的罐头输入曾与评测栈 seed **事实矛盾**（修前原文：规格 `2699-06 蓝灰色`、
加工项 `穿杆孔加工`/`包边处理`、自称「已有客户」的 `赵凯 13456000919` 在
`tests/agent_eval/fixtures/*.sql` 里 0 命中）⇒ **合格 agent 只能如实说"对不上"并停在澄清**
⇒ 期望链路在库层就不可满足（恒红），而报告读起来像"agent 不听话"（归因错人）。
#4053 逐项对齐了 **这一条**，但**这类缺陷没有任何常驻判据**：下一条新用例照旧可以写进
不存在的商品/规格/加工项/客户，而且**只有真跑 LLM 才会发现**（成本高、发现晚、归因错）。

本文件把「**罐头输入点名的 seed 类实体 ↔ seed 真值**」做成**纯静态、零 LLM、秒级**的判据，
随 `tests/unit_ci_workflows` 在**每个 PR** 上跑（`.github/workflows/pr-check.yml` 的
`ci workflow helper unit tests` job）。同族既有资产：`test_eval_case_asset_truth.py`（#3832）。

## 判据（结构判据，**不读散文**）

判据只对「**写死的字面量**」生效 —— issue #4064 的负例要求 R2 明确：以**运行时搜索**定位
对象的用例（不写死名字）不得被判红。因此「点名」的抽取**不靠措辞**，而靠**用例自己声明的
机器可消费槽位**（`MENTION_SLOTS` 单一表；键名即实体类，不是散文关键词）：

| 实体类 | 声明式槽位（写死字面量出现的地方） | 存在性要求 |
|---|---|---|
| 商品名 | `namespaces:product_name:` / `pre_clean[product_dedupe/product_remove].product_keyword` / `precondition[product_count_for_keyword].source` / `expectations[product_detail/product_update].product_id` / `expectations[product_search].keyword` / `db_verify[fetch=order_items].expect_products[]` / `db_verify[fetch=product_by_name].name` / `amount_verify.product_name` | 必须在 `products.name`，或由该用例自建 |
| 加工项名 | `expectations[processing_item_query].keyword` / `expectations[product_processing_item_manage].item_ids[]` / `output_verify[processing_item_manage].expect.name` / `db_verify[fetch=product_by_name].checks[processingItemConfigs.X]` | 必须在 `processing_items.name`，或由该用例创建 |
| 规格/色名 | 控制轮 `form_values.color`/`colorName` / `auto_fill.colors` | 必须在 `product_colors.color_name`（规范化 + 包含匹配），建品用例除外 |
| 客户 | `namespaces:customer_phone:` / `pre_clean[customer_tag_remove].customer_keyword` | 必须在 `customer_profiles`（姓名或手机号），除非用例显式声明它必须失败 |

**每个"泛用键"都必须由锚点定类**（`db_verify.fetch` 的取数类型 / `output_verify` 的工具 /
`pre_clean` 的类型），**不能凭键名判类**：`db_verify.name` 跨域复用 —— `HR-009/HR-010` 的
`{"fetch": "employee", "name": "李四"}` 是**员工姓名**，凭"键叫 `name`"就去商品真值集里查
= **假红**（断言实现宽于用例声明；PR #4135 的真红即此形态）。锚点表见 `declared_mentions`
上方的常量，误伤/漏判两侧都有判据（`TestSlotAnchors`）。

**栈口径不重建**：一个用例点名的商品必须在**它真的会跑的那套栈**上存在 —— 种子文件集合
复用单一源 `scripts/eval_stack_seed.sh --persona <p> --dry-run`（#3563 已把"哪个 persona 装
哪些种子"收成一处；本文件不复制那份规则）。双端用例（`persona` 为空）取两套栈的**并集**
（它可能在任一端跑；宁可宽，不造假红）。

**匹配模式（防假红 / 防假绿）**：`identity`（去空白后**相等**，用于身份类槽位）、
`color`（相等 或 字面量是某个真值色名的**子串** —— 兼容 `暖米色` ↔ `2699-03暖米色`
的前缀省略）、`lookup`（**双向包含**，只用于"搜索关键字"类槽位：`product_search.keyword`
写 `窗帘`、`item_ids` 写 `打孔` 都是**合法的部分指代**，不是身份声明）。

**结构性豁免（逐条有理由，不是白名单）**：
`自建`（#3835 形态：`pre_clean` 用 `product_remove` 自清理的自有名字 / `precondition` 声明
`expect: 0` / 建品用例仅在 `namespaces` 声明的自有名 / 建品用例按名回读自己造的产物 /
建加工项用例声明的产物名）、`否证`（用例把该字面量写进 `must_fail`/`forbidden_args` ——
它是「必须失败」的声明，**不是**存在性主张：`OR-030` 的非法手机号 `05718886666` 即此形态）。
豁免一律来自用例**自己的结构声明**，没有任何 per-case 清单。

## 未实装（照实登记，不当成"已覆盖"）

1. **数值类**（库存 `9599` vs seed `1000/500`、单价、金额自洽）—— 本轮范围裁定只落名字类，
   数值类见 issue #4064 第 2 项，**未实装**；
2. **只在自由文本里点名、且没有任何声明式槽位的实体** —— 自然语言无法可靠抽出（宁少勿假）。
   实证：修前 `OR-029` 的 `2699-06 蓝灰色`/`穿杆孔加工`/`包边处理` 只出现在输入文本里
   （修前无 `form_values` 控制轮），本判据**看不见**它们；它能报出的是同一条用例里
   **被声明**的 `13456000919`（见 `test_pre_fix_or029_is_caught_by_the_declared_customer_claim`）。
   该缺口由 `TestRegisteredGaps` 以**可执行形态**登记：缺口补上时那条测试必须先红；
3. **员工类**（`namespaces:employee_name/phone`）—— 不属本轮四类，显式跳过。

## 每条断言都有红证（`migao-acceptance`：不会红的断言 = 空断言）

红证一律**注入式**（在测试内构造改前形态/不存在实体喂给同一个判据），不用"仓库当下恰有
该缺陷"式真值主张；负例证明判据不是恒红。判别力还由 `test_checked_surface_is_not_vacuous`
（判据必须真的核对到一批写死字面量，不是"空跑通过"；当前条数见该测试的下界断言）与前提前置
共同保证。
"""
import functools
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
FIXTURES_DIR = REPO_ROOT / "tests" / "agent_eval" / "fixtures"
SEED_SCRIPT = REPO_ROOT / "scripts" / "eval_stack_seed.sh"

sys.path.insert(0, str(REPO_ROOT / ".github"))
from render_cases import load_case_dicts      # noqa: E402  （用例单一源加载器，零三方依赖）


# ══════════════════════════════════════════════════════════════════════════════
# 一、seed 真值：解析 fixtures SQL（真值一律来自被读系统本身，不重建命名规则）
# ══════════════════════════════════════════════════════════════════════════════
def strip_sql_comments(sql: str) -> str:
    """去掉 `--` 行注释（**引号内不算**）。

    必须剥：fixture 的行注释插在 `VALUES` 行之间（如 `-- 「白色」给到每个商品`），
    不剥则解析在注释行处断掉 ⇒ 少解析出真值 ⇒ 判据**假红**（实测漏掉 `白色`/`米白色`）。
    """
    out, i, quote = [], 0, ""
    while i < len(sql):
        ch = sql[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch == "'":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if sql[i:i + 2] == "--":
            while i < len(sql) and sql[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_top_level(s: str) -> list:
    """按**顶层**逗号切分（跳过括号/引号内的逗号）。"""
    out, buf, depth, quote = [], [], 0, ""
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch == "'":
            quote = ch
            buf.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))
    return [x.strip() for x in out]


def _statement_end(sql: str, i: int) -> int:
    """该 INSERT 语句的结尾（顶层分号；引号/括号内不算）。"""
    depth, quote = 0, ""
    while i < len(sql):
        ch = sql[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch == "'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == ";" and depth == 0:
            return i
        i += 1
    return len(sql)


def _literal(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def insert_rows(sql: str, table: str) -> list:
    """解析 `INSERT INTO <table> (cols) ... VALUES|(VALUES` 的数据行 → `[{列: 值}]`。

    覆盖 fixture 用到的**两种写法**：直接 `VALUES (...)` 与
    `INSERT ... SELECT v.a, v.b FROM (VALUES (...)) AS v(a, b)` —— 后者按**位置**对应
    INSERT 的列名表（SELECT 列表逐列取自 `v`，顺序与列名表一致）。
    别名列（`AS v(a, b, c)`）的元素是**裸标识符**，不会含引号/数字字面量 ⇒ 天然被排除。
    """
    rows = []
    for m in re.finditer(r"INSERT\s+INTO\s+" + re.escape(table) + r"\b", sql, re.I):
        stmt = sql[m.end():_statement_end(sql, m.end())]
        cm = re.match(r"\s*\(([^)]*)\)", stmt)
        if not cm:
            continue
        cols = [c.strip() for c in cm.group(1).split(",")]
        rest = stmt[cm.end():]
        anchor = None
        for v in re.finditer(r"\bVALUES\b", rest, re.I):
            if rest[v.end():].lstrip().startswith("("):
                anchor = v
                break
        if anchor is None:
            continue
        body, i = rest[anchor.end():], 0
        while i < len(body):
            while i < len(body) and body[i] in " \t\r\n,":
                i += 1
            if i >= len(body) or body[i] != "(":
                break
            depth, j, quote = 0, i, ""
            while j < len(body):
                ch = body[j]
                if quote:
                    if ch == quote:
                        quote = ""
                elif ch == "'":
                    quote = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            parts = _split_top_level(body[i + 1:j])
            if any(p[:1] == "'" or re.fullmatch(r"-?\d+(\.\d+)?", p) for p in parts):
                rows.append({c: _literal(parts[k]) for k, c in enumerate(cols) if k < len(parts)})
            i = j + 1
    return rows


def inventory_of(sql_paths) -> dict:
    """一个 seed 文件集合的**实体真值集合**（`{实体类: frozenset(真值)}`）。"""
    inv = {"product": set(), "processing_item": set(), "color": set(), "customer": set()}
    for p in sql_paths:
        sql = strip_sql_comments(Path(p).read_text(encoding="utf-8"))
        inv["product"] |= {r["name"] for r in insert_rows(sql, "products") if r.get("name")}
        inv["processing_item"] |= {r["name"] for r in insert_rows(sql, "processing_items")
                                   if r.get("name")}
        inv["color"] |= {r["color_name"] for r in insert_rows(sql, "product_colors")
                         if r.get("color_name")}
        # 客户主档 + C 端身份表（C 端栈没有 customer_profiles；身份在 users.role='customer'）
        for r in insert_rows(sql, "customer_profiles"):
            inv["customer"] |= {v for v in (r.get("phone"), r.get("wechat_nickname")) if v}
        for r in insert_rows(sql, "users"):
            if r.get("role") == "customer":
                inv["customer"] |= {v for v in (r.get("phone"), r.get("nickname")) if v}
    return {k: frozenset(v) for k, v in inv.items()}


@functools.lru_cache(maxsize=None)
def seed_files_for(persona: str) -> tuple:
    """该 persona 的评测栈会注入哪些 seed 文件（**复用单一源**，不复制规则）。"""
    proc = subprocess.run(
        ["bash", str(SEED_SCRIPT), "--persona", persona, "--dry-run"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"scripts/eval_stack_seed.sh --persona {persona} --dry-run 失败：\n{proc.stdout}\n{proc.stderr}"
    )
    files = re.findall(r"^seed:\s*(\S+_eval_seed\.sql)\s*$", proc.stdout, re.M)
    assert files, (
        f"没从 {SEED_SCRIPT.name} --persona {persona} --dry-run 的输出里解析出 seed 文件 "
        f"（实测输出：{proc.stdout!r}）—— 本判据的栈口径前提失效，必须同步本文件"
    )
    return tuple(str(REPO_ROOT / f) for f in files)


def stack_of(case: dict) -> tuple:
    """用例实际会跑的那套栈的 seed 文件。

    persona 明确（`mibao`/`xiaobu`）⇒ 该 persona 的栈；双端（空）⇒ 两套栈的**并集**
    （它可能在任一端跑；取并集是有意的**偏宽**选择：宁可放过，不造假红）。
    """
    p = (case.get("persona") or "").strip().lower()
    if p in ("mibao", "xiaobu"):
        return seed_files_for(p)
    both = seed_files_for("xiaobu") + seed_files_for("mibao")
    return tuple(dict.fromkeys(both))


@functools.lru_cache(maxsize=None)
def inventory_of_stack(stack: tuple) -> dict:
    return inventory_of(stack)


def truth_for_case(case: dict) -> dict:
    return inventory_of_stack(stack_of(case))


# ══════════════════════════════════════════════════════════════════════════════
# 二、用例侧「点名」抽取：声明式槽位 → (实体类, 字面量, 槽位, 匹配模式)
# ══════════════════════════════════════════════════════════════════════════════
def _input_dicts(case: dict) -> list:
    return [t for t in (case.get("user_inputs") or []) if isinstance(t, dict)]


def _stringify_inputs(case: dict) -> str:
    return "\n".join(t if isinstance(t, str) else json.dumps(t, ensure_ascii=False)
                     for t in (case.get("user_inputs") or []))


# ── 槽位锚点：**结构性判别依据**（取数类型 / 工具 / 前置类型），**不是键名字面** ──────
# 为什么每个"泛用键"都必须有锚点（2026-09 实证，PR #4135 的真红）：
#   `db_verify[].name` / `output_verify[].expect.name` 这类键名**跨域复用** ——
#   `HR-009/HR-010` 的 `{"fetch": "employee", "name": "李四"}` 是**员工姓名**，
#   凭"键叫 name"就去商品真值集里查 ⇒ **假红**（断言实现宽于用例声明）。
#   判据必须落在"这条取数到底读的是什么对象"上：`db_verify.fetch` 就是那个声明
#   （`product_by_name` = 商品；`employee`/`employee_absent` = 员工域，本轮范围外）。
DB_FETCH_PRODUCT = "product_by_name"      # 按名回读商品（`name` → products.name）
DB_FETCH_ORDER_ITEMS = "order_items"      # 回读订单明细（商品名在 expect_products[]）
TOOLS_ADDRESSING_PRODUCT = ("product_detail", "product_update")  # 用 product_id 指代商品
TOOL_PROCESSING_MANAGE = "processing_item_manage"                # expect.name → 加工项
TOOL_PRODUCT_PROCESSING = "product_processing_item_manage"       # item_ids[] → 加工项
TOOL_PROCESSING_QUERY = "processing_item_query"                  # keyword → 加工项
TOOL_PRODUCT_SEARCH = "product_search"                           # keyword → 商品
PRECLEAN_PRODUCT_TYPES = ("product_dedupe", "product_remove")    # product_keyword → 商品
PRECLEAN_CUSTOMER_TYPES = ("customer_tag_remove",)               # customer_keyword → 客户
PRECONDITION_PRODUCT_TYPE = "product_count_for_keyword"          # source → 商品
#: 明确**不在**本轮范围（布尔值只用于"显式跳过"，避免"扫到一半才发现"）：
NAMESPACE_EMPLOYEE_PREFIXES = ("employee_name:", "employee_phone:")
NAMESPACE_PREFIXES_JUDGED = ("product_name:", "customer_phone:")
#: 分类面清单（判 / 显式范围外）—— 出现**不在两张表里**的新形态 ⇒ `TestNoSilentSkip` 报红，
#: 不许悄悄落入盲区（盲区长得像通过，R5 禁的正是这种静默失效）
DB_FETCH_JUDGED = (DB_FETCH_PRODUCT, DB_FETCH_ORDER_ITEMS)
DB_FETCH_OUT_OF_SCOPE = ("employee", "employee_absent", "order_phone", "after_sales_ticket")
OUTPUT_VERIFY_NAME_TOOLS_JUDGED = (TOOL_PROCESSING_MANAGE,)
OUTPUT_VERIFY_NAME_TOOLS_OUT_OF_SCOPE = ()


def declared_mentions(case: dict) -> list:
    """该用例**结构性声明**的实体字面量 → `[(实体类, 字面量, 槽位, 匹配模式)]`。

    两条纪律：
    ① 只取"机器可消费"的键 —— `data_checks` / `merge_log` / `title` 等散文字段**一律不读**
       （R5：判据不建在措辞上；`TestProseIsNotASource` 把这一点做成可失败判据）；
    ② **泛用键必须由锚点决定类**（见上方常量）：`db_verify.name` 只在
       `fetch == product_by_name` 时才是商品名，否则它可能是员工/客户/工单域的字段。
    """
    out = []                                     # [(class, literal, slot, mode)]

    def add(cls, lit, slot, mode="identity"):
        if isinstance(lit, str) and lit.strip():
            out.append((cls, lit.strip(), slot, mode))

    for n in case.get("namespaces") or []:
        s = str(n)
        if s.startswith("product_name:"):
            add("product", s[len("product_name:"):], "namespaces[product_name:]")
        elif s.startswith("customer_phone:"):
            add("customer", s[len("customer_phone:"):], "namespaces[customer_phone:]")
        elif s.startswith(NAMESPACE_EMPLOYEE_PREFIXES):
            continue                              # 员工域：本轮范围外（docstring「未实装」③）

    for spec in case.get("pre_clean") or []:
        if not isinstance(spec, dict):
            continue
        if spec.get("type") in PRECLEAN_PRODUCT_TYPES:
            # 搜索关键字语义（按关键词定位对象）⇒ 允许部分指代
            add("product", spec.get("product_keyword"),
                f"pre_clean[{spec.get('type')}].product_keyword", "lookup")
        if spec.get("type") in PRECLEAN_CUSTOMER_TYPES:
            add("customer", spec.get("customer_keyword"),
                f"pre_clean[{spec.get('type')}].customer_keyword")

    for spec in case.get("precondition") or []:
        if isinstance(spec, dict) and spec.get("type") == PRECONDITION_PRODUCT_TYPE:
            add("product", spec.get("source"),
                f"precondition[{PRECONDITION_PRODUCT_TYPE}].source", "lookup")

    for spec in case.get("expectations") or []:
        if not isinstance(spec, dict):
            continue
        tool, args = str(spec.get("tool") or ""), spec.get("args")
        args = args if isinstance(args, dict) else {}
        if tool in TOOLS_ADDRESSING_PRODUCT:      # 锚点 = 工具（该工具只操作商品）
            pid = args.get("product_id")
            if isinstance(pid, str) and not pid.startswith("复用"):
                add("product", pid, f"expectations[{tool}].product_id")
            elif isinstance(pid, str) and pid.startswith("复用"):
                pass                              # 「复用上轮 UUID」：非名字面量
        kw = args.get("keyword")
        if tool == TOOL_PRODUCT_SEARCH:
            add("product", kw, f"expectations[{TOOL_PRODUCT_SEARCH}].keyword", "lookup")
        elif tool == TOOL_PROCESSING_QUERY:
            add("processing_item", kw, f"expectations[{TOOL_PROCESSING_QUERY}].keyword", "lookup")
        if tool == TOOL_PRODUCT_PROCESSING:       # 锚点 = 工具（item_ids 指向加工项）
            for key in ("item_ids", "item_names"):
                for v in args.get(key) or []:
                    add("processing_item", v, f"expectations[{tool}].{key}[]", "lookup")

    for spec in case.get("db_verify") or []:
        if not isinstance(spec, dict):
            continue
        fetch = str(spec.get("fetch") or "")
        if fetch == DB_FETCH_ORDER_ITEMS:         # 锚点 = 取数类型（订单明细里的商品名）
            for nm in spec.get("expect_products") or []:
                add("product", nm, f"db_verify[fetch={fetch}].expect_products[]")
        elif fetch == DB_FETCH_PRODUCT:           # 锚点 = 取数类型（按名回读商品）
            add("product", spec.get("name"), f"db_verify[fetch={fetch}].name")
            for chk in spec.get("checks") or []:
                m = re.search(r"processingItemConfigs\.([^.]+)\.", str(chk))
                if m and m.group(1) != "all":     # `all` 是通配选择器，不是加工项名
                    add("processing_item", m.group(1),
                        f"db_verify[fetch={fetch}].checks[processingItemConfigs.X]")
        # 其余 fetch（employee / employee_absent / order_phone / after_sales_ticket）
        # 属员工/客户/工单域：**不判**（本轮四类之外；`db_verify.name` 不是商品名的证据）

    for spec in case.get("amount_verify") or []:
        if isinstance(spec, dict):
            add("product", spec.get("product_name"), "amount_verify.product_name")

    for spec in case.get("output_verify") or []:
        if not isinstance(spec, dict) or not isinstance(spec.get("expect"), dict):
            continue
        # 锚点 = 工具：只有加工项工具的 `expect.name` 才是**加工项名**
        #（跨域同形键：`expect.name` 也可能是员工/商品/客户的名字 —— 实测 `HR-*` 域
        #  的 `db_verify.name` 即为此形态，凭键名判类 = 假红）
        if str(spec.get("tool") or "") == TOOL_PROCESSING_MANAGE:
            add("processing_item", spec["expect"].get("name"),
                f"output_verify[{TOOL_PROCESSING_MANAGE}].expect.name")

    for spec in [case.get("auto_fill")] + \
            [(t.get("auto_respond") or {}).get("form_values") for t in _input_dicts(case)] + \
            [t.get("form_values") for t in _input_dicts(case)]:
        if not isinstance(spec, dict):
            continue
        for key in ("color", "colorName"):
            add("color", spec.get(key), f"form_values.{key}", "color")
        for c in re.split(r"[、,，/]", str(spec.get("colors") or "")):
            add("color", c, "auto_fill.colors", "color")
    return out


def named_in_inputs(case: dict, literal: str) -> bool:
    """该字面量是否**真的被罐头输入点名**（去空白后包含）。"""
    return _norm(literal) in _norm(_stringify_inputs(case))


def _norm(s) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def resolves(literal: str, mode: str, truth) -> str:
    """该字面量能否被 seed 真值解析 → 命中的真值（否则空串）。"""
    lit = _norm(literal)
    if not lit:
        return ""
    for t in sorted(truth):
        nt = _norm(t)
        if lit == nt or (mode in ("color", "lookup") and lit in nt) \
                or (mode == "lookup" and nt in lit):
            return t
    return ""


# ── 结构性豁免（逐条来自用例自己的声明；无 per-case 清单）────────────────────────
SELF_MADE = "自建（用例产物）"
NEGATED = "用例声明该字面量必须失败/不得使用"


def _negated_literals(case: dict) -> set:
    """用例写进 `must_fail` / `forbidden_args` 的字面量（**否证**声明，非存在性主张）。"""
    out = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            out.add(_norm(o))

    for key in ("must_fail", "forbidden_args"):
        for spec in case.get(key) or []:
            walk(spec)
    return out


def _creates(case: dict, tool: str) -> bool:
    return any(isinstance(e, dict) and e.get("tool") == tool
               and "create" in str((e.get("args") or {}).get("action", ""))
               for e in case.get("expectations") or [])


def exemption_reason(case: dict, cls: str, literal: str, slot: str) -> str:
    """结构性豁免理由（空串 = 该字面量必须能解析到 seed 真值）。"""
    if _norm(literal) in _negated_literals(case):
        return NEGATED
    if cls == "product":
        if any(isinstance(s, dict) and s.get("type") == "product_remove"
               and s.get("product_keyword") == literal for s in case.get("pre_clean") or []):
            return SELF_MADE          # #3835 形态：pre_clean 自清理的自有名字
        if any(isinstance(s, dict) and s.get("expect") == 0
               and s.get("source") == literal for s in case.get("precondition") or []):
            return SELF_MADE          # 前置自断言「起跑前为 0 件」
        others = [m for m in declared_mentions(case)
                  if m[0] == "product" and m[1] == literal and not m[2].startswith("namespaces[")]
        if slot.startswith("namespaces[") and _creates(case, "product_manage") and not others:
            return SELF_MADE          # 建品用例仅在 namespaces 声明的自有名（PR-012 形态）
        if slot.startswith("db_verify[") and slot.endswith("].name") \
                and _creates(case, "product_manage"):
            return SELF_MADE          # 建品后按名回读**本案例造的产物**
    if cls == "processing_item":
        if slot.startswith(f"output_verify[{TOOL_PROCESSING_MANAGE}]") \
                and _creates(case, TOOL_PROCESSING_MANAGE):
            return SELF_MADE          # 建加工项用例：该名字是本案产物（PP-006 形态）
    if cls == "color" and _creates(case, "product_manage"):
        return SELF_MADE              # 建品用例的颜色由本案定义（PR-019 形态）
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据本体（纯函数；注入式红证直接喂它）
# ══════════════════════════════════════════════════════════════════════════════
def audit(cases) -> dict:
    """逐字面量处置：`checked`（判据实际核对的）/ `exempt`（结构性豁免的）。

    只统计"**被罐头输入点名**"的声明式字面量；没被输入点名的槽位不属本判据范围
    （判定域 = 「写死 + 点名」，见文件头）。
    """
    checked, exempt, covered = [], [], set()
    for case in cases:
        seen = set()
        for cls, lit, slot, mode in declared_mentions(case):
            if not named_in_inputs(case, lit):
                continue
            covered.add((case.get("id"), cls, lit))
            if (cls, lit) in seen:
                continue
            seen.add((cls, lit))
            why = exemption_reason(case, cls, lit, slot)
            row = {"case": case.get("id"), "class": cls, "literal": lit, "slot": slot}
            if why:
                exempt.append(dict(row, reason=why))
            else:
                checked.append(dict(row, mode=mode, matched=resolves(lit, mode,
                                                                     truth_for_case(case)[cls])))
    return {"checked": checked, "exempt": exempt,
            "cases_with_declared_mentions": len({c["case"] for c in checked + exempt})}


def unbacked_mentions(cases) -> list:
    """**核心判据**：被罐头输入点名、且必须在 seed 里成立、却解析不到真值的字面量。

    返回空列表 = 通过（每条违规含：用例 ID / 实体类 / 点了什么名 / 声明槽位 / 该栈的真值）。
    """
    bad = []
    for row in audit(cases)["checked"]:
        if row["matched"]:
            continue
        truth = sorted(truth_for_case(next(c for c in cases if c.get("id") == row["case"]))
                       [row["class"]])
        bad.append(dict(row, available=truth))
    return bad


def available_truth(case: dict, cls: str) -> list:
    return sorted(truth_for_case(case)[cls])


def _reason(bad: list) -> str:
    lines = [
        "❌ 这些**写死的实体名**被罐头输入点名，却不在该用例实际会跑的那套评测栈 seed 里 "
        "⇒ 库层不可满足：合格 agent 只能如实说「对不上」并停在澄清，链路物理上走不完 "
        "（= OR-029 修前的恒红形态，issue #4064；报告读起来却像「agent 不听话」）。",
        "   处置（R4/R5）：① 把罐头输入里的实体名**对齐 seed 真值**；或 ② 让用例**自建**该对象"
        "（建品/建加工项期望 + `pre_clean` 自清理 + `precondition expect: 0`，#3835 形态）；"
        "或 ③ 若该对象本就不该存在（非法值/失败路径用例），把它写进 `must_fail`/`forbidden_args`。"
        "**禁止**把它加进任何豁免清单。",
    ]
    for b in bad:
        lines.append(
            f"   · {b['case']} [{b['class']}] 点名 {b['literal']!r}"
            f"（声明于 {b['slot']}，匹配模式 {b['mode']}）\n"
            f"       该栈 seed 现有真值：{b['available']}"
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 四、断言
# ══════════════════════════════════════════════════════════════════════════════
def _all_cases() -> list:
    return load_case_dicts(str(CASES_DIR))


class TestPremises:
    """前提：真值解析得出东西、栈口径来自单一源 —— 否则下面的判据会**空跑通过**。"""

    def test_fixture_inventory_parses(self):
        inv = inventory_of([FIXTURES_DIR / "xiaobu_eval_seed.sql",
                            FIXTURES_DIR / "mibao_eval_seed.sql"])
        assert {"遮光窗帘", "北欧风窗帘", "夏日清风窗帘", "2699系列雪尼尔窗帘面料"} <= inv["product"], inv["product"]
        assert {"纳米圈打孔", "韩式波浪折边", "高温定型", "刺绣工艺"} <= inv["processing_item"], inv["processing_item"]
        # 行注释穿插在 VALUES 之间 ⇒ 不剥注释会漏掉后两条（本断言正是那条解析回归的红证）
        assert {"米白", "浅灰", "雾霾蓝", "白色", "米白色", "2699-03暖米色", "2699-01本白"} <= inv["color"], inv["color"]
        assert {"13800138000", "张三"} <= inv["customer"], inv["customer"]

    def test_seed_stack_comes_from_the_single_source(self):
        assert seed_files_for("xiaobu") == (str(FIXTURES_DIR / "xiaobu_eval_seed.sql"),), \
            seed_files_for("xiaobu")
        assert seed_files_for("mibao") == (str(FIXTURES_DIR / "xiaobu_eval_seed.sql"),
                                           str(FIXTURES_DIR / "mibao_eval_seed.sql")), \
            seed_files_for("mibao")

    def test_dual_end_case_gets_the_union_of_both_stacks(self):
        """双端用例可能在任一端跑 ⇒ 取并集（宽而不错杀）。"""
        assert stack_of({"persona": ""}) == stack_of({"persona": "mibao"})
        assert stack_of({"persona": "xiaobu"}) == (str(FIXTURES_DIR / "xiaobu_eval_seed.sql"),)

    def test_checked_surface_is_not_vacuous(self):
        """**防空跑**：判据必须真的核对到一批写死字面量，否则"全绿"毫无意义。"""
        a = audit(_all_cases())
        assert len(a["checked"]) >= 40, (
            f"判据实际只核对了 {len(a['checked'])} 条字面量 —— 抽取面塌了（槽位表被改坏/"
            f"用例库结构漂移），'绿'不构成结论")
        assert {c["class"] for c in a["checked"]} == {"product", "processing_item", "color",
                                                      "customer"}, \
            sorted({c["class"] for c in a["checked"]})


class TestEveryDeclaredMentionResolves:
    """**核心不变式**：用例库全量 —— 被点名的写死实体名必须都在该栈 seed 里成立。"""

    def test_no_case_names_an_entity_that_the_stack_seed_lacks(self):
        bad = unbacked_mentions(_all_cases())
        assert bad == [], _reason(bad)

    def test_exemptions_are_structural_and_enumerated(self):
        """豁免必须逐条带**结构性理由**（防"为了变绿"把判据放宽成无判别力）。"""
        known = {SELF_MADE, NEGATED}
        for row in audit(_all_cases())["exempt"]:
            assert row["reason"] in known, row
            assert row["slot"], row


class TestInjectionRedProofs:
    """红证（注入式）：改前形态 / 不存在的实体喂给**同一个判据** ⇒ 必须报红。"""

    def test_pre_fix_or029_is_caught_by_the_declared_customer_claim(self):
        """**修前 OR-029**（#4015 原文形态）⇒ 必须报红，且逐条说出"点了什么名"。

        修前该用例**声明**过的实体字面量只有两个：商品名（seed 里有，故不报）与
        `namespaces: customer_phone:13456000919` —— 后者自称"已有客户"却在 seed 里 0 命中。
        本判据据此把这条**恒红**用例判红（判别力证明：改后形态见下一条，判据不报）。
        """
        pre_fix = {
            "id": "OR-029", "persona": "mibao",
            "user_inputs": [
                "录订单 赵凯（13456000919）｜ 2699系列雪尼尔窗帘面料 · 2699-06 蓝灰色 · 散剪 · "
                "2.8米 · 10 米 ｜ 加工项：韩式波浪折边、穿杆孔加工、包边处理",
                "1. 2699系列雪尼尔窗帘面料｜¥23.8/米｜库存 9599",
                "已有客户",
            ],
            "namespaces": ["customer_phone:13456000919",
                           "product_name:2699系列雪尼尔窗帘面料"],
            "precondition": [{"type": "product_count_for_keyword",
                              "source": "2699系列雪尼尔窗帘面料", "expect": 1}],
            "pre_clean": [{"type": "product_dedupe",
                           "product_keyword": "2699系列雪尼尔窗帘面料", "price": 23.8}],
        }
        bad = unbacked_mentions([pre_fix])
        assert [b["literal"] for b in bad] == ["13456000919"], bad
        assert bad[0]["class"] == "customer" and bad[0]["case"] == "OR-029"
        assert bad[0]["available"], "违规条目里没带该栈的现有真值（无法照实报告）"
        # 同一条用例的**修后形态**（#4053 已对齐真值）⇒ 同一判据不报（不是恒红）
        fixed = dict(pre_fix, namespaces=["customer_phone:13800138000",
                                          "product_name:2699系列雪尼尔窗帘面料"])
        assert unbacked_mentions([fixed]) == []

    def test_injected_nonexistent_entities_of_every_class_are_reported(self):
        """四类各注入一条"点名了 fixtures 里不存在的实体"（负例见下一个类）。"""
        samples = [
            ({"id": "INJ-PROD", "persona": "mibao",
              "user_inputs": ["给张三下单，幻影窗帘 3 米"],
              "namespaces": ["product_name:幻影窗帘"],
              "pre_clean": [{"type": "product_dedupe", "product_keyword": "幻影窗帘"}]}, "product"),
            ({"id": "INJ-PROC", "persona": "mibao",
              "user_inputs": ["要穿杆孔加工"],
              "expectations": [{"tool": "processing_item_query",
                                "args": {"keyword": "穿杆孔加工"}}]}, "processing_item"),
            ({"id": "INJ-COLOR", "persona": "mibao",
              "user_inputs": ["颜色要 2699-06 蓝灰色",
                              {"form_values": {"colorName": "2699-06 蓝灰色"}}],
              "expectations": [{"tool": "order_create"}]}, "color"),
            ({"id": "INJ-CUST", "persona": "mibao",
              "user_inputs": ["给赵凯（13456000919）打标签"],
              "expectations": [{"tool": "customer_manage", "args": {"action": "add_tag"}}],
              "namespaces": ["customer_phone:13456000919"]}, "customer"),
        ]
        for case, cls in samples:
            bad = unbacked_mentions([case])
            assert [b["class"] for b in bad] == [cls], (case["id"], bad)

    def test_polarity_rule_is_not_a_blanket_exemption(self):
        """`OR-030` 形态：非法手机号靠 `must_fail` 豁免 —— 去掉那条声明即**必须**报红。

        证明豁免来自用例的**结构性否证**，而不是"凡自定义号码都放过"。
        """
        or030 = {
            "id": "OR-030", "persona": "mibao",
            "user_inputs": ["帮我给张三下单，遮光窗帘 3 米，米白，散剪 2.8 米门幅，"
                            "手机号 05718886666，不许换成别的号码"],
            "expectations": [{"tool": "validate_input"}],
            "namespaces": ["customer_phone:05718886666", "product_name:遮光窗帘"],
            "precondition": [{"type": "product_count_for_keyword",
                              "source": "遮光窗帘", "expect": 1}],
        }
        assert unbacked_mentions([dict(or030, must_fail=[
            {"tool": "order_create", "args": {"customer_phone": "05718886666"}}])]) == [], \
            "带 must_fail 的形态被误报（OR-030 会假红）"
        bad = unbacked_mentions([or030])
        assert [b["literal"] for b in bad] == ["05718886666"], bad

    def test_self_made_rule_is_not_a_blanket_exemption(self):
        """`自建` 只对**该用例自建的那一个名字**生效：换成别人的名字 ⇒ 必须报红。"""
        make = {
            "id": "INJ-SELF", "persona": "mibao",
            "user_inputs": ["创建商品，名称 自有样品帘"],
            "expectations": [{"tool": "product_manage", "args": {"action": "create"}}],
            "namespaces": ["product_name:自有样品帘"],
            "pre_clean": [{"type": "product_remove", "product_keyword": "自有样品帘"}],
            "precondition": [{"type": "product_count_for_keyword", "source": "自有样品帘",
                              "expect": 0}],
        }
        assert unbacked_mentions([make]) == []
        stolen = dict(make, pre_clean=[{"type": "product_dedupe",
                                        "product_keyword": "幻影窗帘"}],
                      user_inputs=["创建商品，名称 自有样品帘", "顺便改一下 幻影窗帘 的价格"],
                      precondition=[])
        assert [b["literal"] for b in unbacked_mentions([stolen])] == ["幻影窗帘"], \
            unbacked_mentions([stolen])


class TestSlotAnchors:
    """泛用键必须由**锚点**（取数类型 / 工具 / 前置类型）定类 —— 防跨域假红。

    实证（PR #4135 的真红，`HR-009/HR-010`）：`db_verify: {"fetch": "employee", "name": "李四"}`
    是**员工姓名**；判据若凭"键叫 `name`"就去 `products.name` 里查 ⇒ 把两条合法用例判红。
    本类两侧都钉：① 跨域不得误伤（含"改前形态会误报"的注入式红证）；
    ② 锚点不得把**真阳性**一起废掉（`fetch: product_by_name` 里点名不存在的商品仍必须报红）。
    """

    EMPLOYEE_TOOLS = ("employee_manage", "role_manage")   # 员工域工具（不携带商品身份）

    @staticmethod
    def _case(cid: str) -> dict:
        return next(c for c in _all_cases() if c["id"] == cid)

    def test_employee_db_verify_names_are_not_products(self):
        """真实用例：`HR-009/HR-010` 的 `db_verify.name='李四'` 不得被当成商品名。"""
        for cid in ("HR-009", "HR-010"):
            case = self._case(cid)
            declared = [m for m in declared_mentions(case)
                        if m[0] in ("product", "processing_item", "color")]
            assert declared == [], (cid, declared)
            assert unbacked_mentions([case]) == [], cid

    def test_unanchored_name_key_would_be_a_false_positive(self):
        """**注入式红证（改前形态）**：无条件把 `db_verify.name` 当商品 ⇒ `李四` 必被误报。

        这条证明上一测试不是"恒绿"：锚点一旦退回"凭键名判类"，同一判据立刻产出假红。
        """
        case = self._case("HR-009")
        unanchored = [("product", s.get("name"), "db_verify.name", "identity")
                      for s in case["db_verify"]]
        truth = truth_for_case(case)["product"]
        missed = [lit for _, lit, _, mode in unanchored if not resolves(lit, mode, truth)]
        assert missed == ["李四"], f"改前形态没复现误报（红证无判别力）：{missed}"

    def test_employee_domain_cases_declare_no_product_mentions(self):
        """全库扫一遍：只操作**员工域工具**的用例，一个商品/加工项/色名类点名都不该抽出。"""
        leaks = []
        for case in _all_cases():
            tools = {str(e.get("tool")) for e in case.get("expectations") or []
                     if isinstance(e, dict)}
            if tools and tools <= set(self.EMPLOYEE_TOOLS):
                leaks += [(case["id"], m) for m in declared_mentions(case)
                          if m[0] in ("product", "processing_item", "color")]
        assert leaks == [], f"员工域用例被抽出了商品域点名（跨域假红）：{leaks}"

    def test_product_by_name_fetch_still_judges(self):
        """**锚点没有废掉真阳性**：`fetch: product_by_name` 里点名不存在的实体 ⇒ 仍必报红。"""
        case = {
            "id": "INJ-ANCHOR", "persona": "mibao",
            "user_inputs": ["把 幻影窗帘 改个价", "加工项 穿杆孔加工 也要改"],
            "expectations": [{"tool": "product_update", "args": {"price": "198"}}],
            "db_verify": [{"fetch": "product_by_name", "name": "幻影窗帘",
                           "checks": ["processingItemConfigs.all.finalPrice>0",
                                      "processingItemConfigs.穿杆孔加工.finalPrice>0"]}],
        }
        got = {(b["class"], b["literal"]) for b in unbacked_mentions([case])}
        assert got == {("product", "幻影窗帘"), ("processing_item", "穿杆孔加工")}, got

    def test_order_items_fetch_still_judges(self):
        """另一条锚点同样不失真阳性：`fetch: order_items` 的 `expect_products[]`。"""
        case = {
            "id": "INJ-ITEMS", "persona": "xiaobu",
            "user_inputs": ["我买的是 幻影窗帘 3 米"],
            "expectations": [{"tool": "order_create"}],
            "db_verify": [{"fetch": "order_items", "source": "order_create",
                           "expect_products": ["幻影窗帘"]}],
        }
        assert [b["literal"] for b in unbacked_mentions([case])] == ["幻影窗帘"]

    def test_other_fetch_types_are_out_of_scope(self):
        """`employee` / `employee_absent` / `order_phone` / `after_sales_ticket` 取数**不判**。"""
        for fetch, spec in (("employee_absent", {"name": "李四", "phone": "13800009999"}),
                            ("employee", {"name": "李四", "expect_fields": {"phone": "1"}}),
                            ("order_phone", {"expect_phone": "13800138000"}),
                            ("after_sales_ticket", {"expect_status": "closed"})):
            case = {"id": f"OK-{fetch}", "persona": "mibao",
                    "user_inputs": ["帮我开个客服账号，姓名李四，手机号 13800009999"],
                    "expectations": [{"tool": "employee_manage",
                                      "args": {"action": "create"}}],
                    "db_verify": [dict(spec, fetch=fetch)]}
            assert declared_mentions(case) == [], (fetch, declared_mentions(case))
            assert unbacked_mentions([case]) == [], fetch


def _unclassified(values, judged, out_of_scope) -> list:
    return sorted(set(values) - set(judged) - set(out_of_scope) - {""})


def unclassified_db_fetches(cases) -> list:
    """未分类的 `db_verify.fetch` 取数类型（当前**不会**被判据核对 ⇒ 盲区与通过同形）。"""
    return _unclassified((str(s.get("fetch") or "") for c in cases
                          for s in c.get("db_verify") or [] if isinstance(s, dict)),
                         DB_FETCH_JUDGED, DB_FETCH_OUT_OF_SCOPE)


def unclassified_namespace_prefixes(cases) -> list:
    return _unclassified((str(n).split(":")[0] + ":" for c in cases
                          for n in c.get("namespaces") or []),
                         NAMESPACE_PREFIXES_JUDGED, NAMESPACE_EMPLOYEE_PREFIXES)


def unclassified_output_verify_name_tools(cases) -> list:
    return _unclassified((str(s.get("tool") or "") for c in cases
                          for s in c.get("output_verify") or []
                          if isinstance(s, dict) and isinstance(s.get("expect"), dict)
                          and s["expect"].get("name")),
                         OUTPUT_VERIFY_NAME_TOOLS_JUDGED,
                         OUTPUT_VERIFY_NAME_TOOLS_OUT_OF_SCOPE)


class TestNoSilentSkip:
    """**防静默**：判据"看不见"的形态必须报红，不许悄悄进盲区（R5）。

    本判据只在**已分类**的槽位上工作 —— 于是"新出现一种取数类型/工具/命名空间前缀"时的
    默认行为是**不判**（绿），而绿的形状与"真的没事"完全一样。这三条把默认行为翻过来：
    新形态要么被判、要么被显式登记为范围外，两者都没有 ⇒ 报红（并提示该怎么归类）。
    每条都带注入式红证（喂一条未分类形态 ⇒ 必报出）。
    """

    def test_every_db_verify_fetch_type_is_classified(self):
        unknown = unclassified_db_fetches(_all_cases())
        assert unknown == [], (
            f"出现了未分类的 `db_verify.fetch` 取数类型 {unknown} —— 它当前**不会**被本判据核对"
            "（盲区与通过同形）。请判定它读的是什么对象：属商品/加工项/色名/客户 ⇒ 加进 "
            "`DB_FETCH_JUDGED` 并补抽取分支；不属本轮四类 ⇒ 加进 `DB_FETCH_OUT_OF_SCOPE` 并写明理由")
        assert unclassified_db_fetches(
            [{"id": "X", "db_verify": [{"fetch": "ticket_by_no", "name": "T-1"}]}]) \
            == ["ticket_by_no"], "红证失败：未分类取数类型没被报出"

    def test_every_namespace_prefix_is_classified(self):
        unknown = unclassified_namespace_prefixes(_all_cases())
        assert unknown == [], (
            f"出现了未分类的 `namespaces` 前缀 {unknown} —— 同样的静默盲区。"
            "属本轮四类 ⇒ 加进 `NAMESPACE_PREFIXES_JUDGED`；否则显式登记为范围外")
        assert unclassified_namespace_prefixes(
            [{"id": "X", "namespaces": ["order_no:EVAL-1"]}]) == ["order_no:"], \
            "红证失败：未分类命名空间前缀没被报出"

    def test_every_output_verify_name_tool_is_classified(self):
        unknown = unclassified_output_verify_name_tools(_all_cases())
        assert unknown == [], (
            f"这些工具的 `output_verify[].expect.name` 未分类：{unknown} —— "
            "`expect.name` 跨域同形（加工项名/员工名/商品名都可能用它），凭键名判类 = 假红；"
            "请显式归类（判 or 范围外）")
        assert unclassified_output_verify_name_tools(
            [{"id": "X", "output_verify": [{"tool": "employee_manage",
                                            "expect": {"name": "李四"}}]}]) \
            == ["employee_manage"], "红证失败：未分类工具没被报出"


class TestNegativeExamples:
    """负例（R2）：合法形态**不得**被判红 —— 判据只对「写死的字面量」生效。"""

    def test_runtime_search_case_is_not_reported(self):
        """以运行时搜索定位对象（不写死名字）的用例：无可核对字面量。"""
        runtime = {
            "id": "OK-RUNTIME", "persona": "mibao",
            "user_inputs": ["有哪些缺货的商品", "帮我看看最近的订单"],
            "expectations": [{"tool": "product_search", "args": {"stock_status": "out_of_stock"}}],
        }
        assert declared_mentions(runtime) == []
        assert unbacked_mentions([runtime]) == []

    def test_partial_lookup_names_still_resolve(self):
        """搜索关键字类槽位允许**部分指代**：`打孔`→`纳米圈打孔`、`窗帘`→`遮光窗帘`。"""
        case = {
            "id": "OK-LOOKUP", "persona": "xiaobu",
            "user_inputs": ["搜窗帘", "要打孔加工"],
            "expectations": [{"tool": "product_search", "args": {"keyword": "窗帘"}},
                             {"tool": "processing_item_query", "args": {"keyword": "打孔"}}],
        }
        assert unbacked_mentions([case]) == []

    def test_color_prefix_omission_still_resolves(self):
        """色名允许省略前缀（`暖米色` ↔ `2699-03暖米色`）—— 裁定明确要求别造假红。"""
        case = {
            "id": "OK-COLOR", "persona": "mibao",
            "user_inputs": ["颜色要暖米色", {"form_values": {"colorName": "暖米色"}}],
            "expectations": [{"tool": "order_create"}],
        }
        assert unbacked_mentions([case]) == []

    def test_prose_is_not_a_source(self):
        """R5：把不存在的实体名塞进**散文字段** ⇒ 不报（判据建在结构上，不读措辞）。"""
        prose = {
            "id": "OK-PROSE", "persona": "mibao",
            "user_inputs": ["有哪些缺货的商品"],
            "expectations": [{"tool": "product_search"}],
            "data_checks": ["幻影窗帘 与 穿杆孔加工 与 赵凯 13456000919 必须存在"],
            "merge_log": "加工项 包边处理；规格 2699-06 蓝灰色；库存 9599",
            "title": "幻影窗帘 下单",
        }
        assert unbacked_mentions([prose]) == []
        # 反向：把同一批名字搬进**声明式槽位** ⇒ 立刻报红（证明上一条不是"什么都没读"）
        declared = dict(prose, namespaces=["product_name:幻影窗帘"],
                        precondition=[{"type": "product_count_for_keyword",
                                       "source": "幻影窗帘", "expect": 1}],
                        user_inputs=["搜索幻影窗帘"])
        assert [b["literal"] for b in unbacked_mentions([declared])] == ["幻影窗帘"]


class TestRegisteredGaps:
    """未实装登记（**可执行形态**）：缺口补上时，本类必须先红。"""

    def test_free_text_only_mentions_are_out_of_scope(self):
        """只在自由文本里点名、无任何声明式槽位的实体 ⇒ 本判据看不见（未实装）。

        实证（修前 OR-029）：`2699-06 蓝灰色`/`穿杆孔加工`/`包边处理` 当时只出现在输入文本里
        （无 `form_values` 轮），故**不可静态断定**它们是"点名了不存在的实体"而非普通措辞
        （同句里还有 `散剪`/`2.8米`/`10 米` 这类非实体词）。判据对的取舍是**宁少勿假**：
        不做措辞/枚举切分，只认声明式槽位。缺口实装后，本测试必须改写。
        """
        free_text = {
            "id": "GAP-FREETEXT", "persona": "mibao",
            "user_inputs": ["加工项：穿杆孔加工、包边处理；规格 2699-06 蓝灰色"],
            "expectations": [{"tool": "order_create"}],
        }
        assert declared_mentions(free_text) == []
        assert unbacked_mentions([free_text]) == []

    def test_numeric_axis_is_not_implemented(self):
        """数值类（库存/单价/金额自洽）**:未实装** —— issue #4064 第 2 项，本轮范围裁定未含。

        本测试把"没实装"钉成可执行的登记：`data_checks` 里与 seed 矛盾的 `库存 9599`
        **不会**被报出（判据不读散文，也没有数值槽位的解析）。
        """
        numeric = {
            "id": "GAP-NUMERIC", "persona": "mibao",
            "user_inputs": ["2699系列雪尼尔窗帘面料｜¥23.8/米｜库存 9599"],
            "expectations": [{"tool": "product_search"}],
            "namespaces": ["product_name:2699系列雪尼尔窗帘面料"],
        }
        assert unbacked_mentions([numeric]) == []