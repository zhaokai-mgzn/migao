# case_ids: RG-001
"""casebook 字段可见性：用例**声明**的字段必须在人读账本里看得见（issue #3968 ①）。

## 病灶（一类，不是一个）

`docs/testing/mibao-verification-cases.md` 由 `.github/render_cases.py::to_md` 生成，而
`to_md` 只渲染它**记得**渲染的字段 ⇒ 声明了却看不见的字段**没有任何东西会报**：

- `persona`（单端标注，84 条）：读账本的人（含 AI）看不出「这条只跑一条腿」，
  于是把单端用例当双端讨论「跨腿覆盖」——**issue #3968 的原始误判就是这个**；
- `namespaces`（资源互斥清单，58 条）：看不出「这条与谁争同一资源」（同键 ⇒ runner 自动串行），
  会把串行后的结果读成覆盖不足（或反过来）；
- 同类的还有 `precondition`（96 条，运行期前置断言：它不成立时红绿**不可归因于 agent**）、
  `preconditions`（散文前置，2 条）、`forbidden_card_text`（卡面禁用文案，3 条）——
  一并随本包补渲染（铁律 11：同族问题默认同包收敛）。

前例 = **#3836** 给 `pre_clean` 补渲染（同一处、同一形态）⇒ 本包照它的写法补，
**不自创第二套渲染结构**（前缀风格沿用 `清理:` / `复位:` 那一族）。

## 判据（三层：登记闭包 / 逐条可见 / 一条声明一行）

1. **登记闭包**（类级元守卫）：`cases/*.yml` 里**声明过**（非空）的每一个顶层字段，
   必须落在本文件的三个台账之一 —— `RENDERED_AS_LINE`（有自己的行）/
   `RENDERED_ELSEWHERE`（在标题、溯源行等处可见）/ `NOT_RENDERED`（有意不渲染 + 理由）。
   **未登记即红** ⇒ 以后新增一个用例字段，作者必须做一次**决定**（渲染它，或写明为什么不渲染），
   而不是让它在账本里静默消失 —— 这正是本缺陷类得以存在的机制。
   台账条目还须**活着**（仍有用例声明它），否则是僵尸登记（同族：drift / case-trust 的台账口径）。
2. **逐条可见**：`RENDERED_AS_LINE` 的每个字段，凡有用例声明，该用例的 casebook 区块里必须
   出现对应前缀的行；`persona` / `namespaces` 另按**值**逐个核对（端标注的值、每个命名空间 token）。
3. **一条声明 = 一行**（`ONE_LINE_PER_DECLARATION` / `ONE_LINE_PER_CASE`）：本包新补的字段，
   渲染行数必须符合契约。这条判据有**实测红**：`precondition` 有 **14** 条是散文形态
   （值本身是 `str`），若渲染器直接 `for x in value` 迭代，一条散文前置会被按**字符**拆成
   3223 行 —— 「渲染了」在肉眼上仍成立，账本却已被字符行淹没（本包实测踩到并修掉）。

## 真值源（只用用例库单一源）

声明侧一律经 `render_cases.load_case_dicts(.github/cases)`（与渲染器**同一**装载器、
**同一** `_as_items` 归一语义），避免本判据自造第二份「什么算一条声明」的口径。

## 红证（本仓库验收协议要求「每条断言都要有红证」）

- **回放红**（`TestRedProof.test_replaying_the_pre_fix_casebook_reports_every_declaring_case`）：
  把**修复前**的 casebook（= 提交版逐字段剥掉新增前缀的行）喂给同一份判据本体
  ⇒ 必须逐个字段报出**全部**声明该字段的用例 —— 证明判据不是恒真。
- **构造红**：注入声明了**未登记**字段的用例 ⇒ 判据 1 必红；注入「一条声明被拆成多行」
  （字符行 / 合并行被拆开）的区块 ⇒ 判据 3 必红；把某一条用例的 `端:` 行单独抹掉
  ⇒ 判据 2 必须**只**报那一条。
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
CASEBOOK_PATH = REPO_ROOT / "docs" / "testing" / "mibao-verification-cases.md"
sys.path.insert(0, str(REPO_ROOT / ".github"))

import render_cases  # noqa: E402


# ── 台账（三桶；三桶的键集必须恰好覆盖「声明过的字段」⇒ 未登记即红）─────────────
#: ① 有自己的行：用例字段 → casebook 行前缀（`to_md` 逐字段渲染）。
#: 前缀取**语义稳定**的一段（如 `命名空间` / `禁词`），措辞微调不应判红；
#: 但**前缀与字段的绑定**是契约：改渲染前缀 ⇒ 这里必须同步（判据会红）。
RENDERED_AS_LINE: dict[str, str] = {
    "persona": "端: ",
    "expectations": "期望: ",
    "data_checks": "数据: ",
    "user_inputs": "你: ",
    "pre_clean": "清理: ",
    "post_clean": "复位: ",
    "precondition": "前置: ",
    "preconditions": "前置(散文): ",
    "namespaces": "命名空间",
    "order_before": "时序: ",
    "forbidden_text": "禁词",
    "forbidden_card_text": "禁卡文: ",
    "forbidden_interact": "禁卡轮: ",
    "arg_values": "入参值: ",
    "forbidden_tools": "全程禁用: ",
    "want_text": "必须: ",
    "required_args": "必填: ",
    "forbidden_args": "禁参: ",
    "must_succeed": "必须成功: ",
    "must_fail": "必须失败: ",
    "amount_verify": "金额: ",
    "db_verify": "落库: ",
    "output_verify": "产出: ",
    "post_session": "会话后: ",
    "auto_fill": "载荷(全场可用): ",
    "skip_reason": "跳过: ",
}
#: ② 在别处可见（不是「没渲染」，只是不占自己的行）。带 `VALUE_VISIBLE_IN_BLOCK` 的逐条核对**值**。
RENDERED_ELSEWHERE: dict[str, str] = {
    "id": "区块标题 `### <id>. <title> <tier 图标>`",
    "title": "同上",
    "tier": "区块标题末尾的 tier 图标（🟢 smoke / 🔵 normal / 🟡 edge / 🔴 adversarial，图例在文首）",
    "tags": "区块末 `溯源: … ｜ tags: …` 行",
    "merge_log": "区块末 `溯源: …` 行",
    "truths_ref": "区块末 `真值: …` 行（无 truths_ref 的用例落「真值: ⚠️ 缺口」）",
    "_domain": "章节标题 `## <域中文名>（N case）`",
}
#: ② 桶里逐条核对**值**的字段（其余只登记去向 —— 未固化项见 PR body）。
VALUE_VISIBLE_IN_BLOCK: tuple[str, ...] = ("id", "title", "tags")
#: ③ 有意不渲染（台账：**只许缩短** —— 某字段改成渲染后必须从本表删除，判据会因「已渲染却仍登记」判红）。
NOT_RENDERED: dict[str, str] = {
    "traces": "证据链（测试文件 / CI workflow 名）：由 `.github/cases/README.md` 的 7 条纪律与 "
              "`tests/unit_ci_workflows/test_eval_evidence_chain.py` 守卫；逐条印会与 `真值:` / "
              "`溯源:` 行混淆（那两行是**引用**，不是人读断言）",
    "legacy_id": "迁移期旧 ID 映射（`eval L001` 之类），只有生成物 `eval_cases.py` 的 runner 兜底查找用；"
                 "人读账本以 `### <ID>.` 标题为准",
    "domains": "跨域**过滤**标签（`.github/` 侧消费）；人读账本按章节（= 源文件名 `_domain`）+ `tags` 行定位，"
               "逐条印 483 次是纯噪声",
    "debug_permissions": "夹具层身份注入旗标（服务端 DEBUG-only 的 `X-Debug-Permissions`）；"
                         "行为语义由该用例的 `merge_log` 与 `你:` 轮说明",
    "debug_user": "同 `debug_permissions`（夹具层多身份注入）",
}
#: ④ 本包（issue #3968）新补字段的**行数契约**（必须是 ① 桶的子集 ⇒ 同时受「逐条可见」约束）：
#: · 一条声明 = 一行（行数 == 声明项数）；
ONE_LINE_PER_DECLARATION: dict[str, str] = {k: RENDERED_AS_LINE[k] for k in (
    "persona", "precondition", "preconditions", "forbidden_card_text")}
#: · 同一用例的全部声明**合并一行**（行数 == 1）——`namespaces` 是多 token 的互斥组，读起来是一句话。
ONE_LINE_PER_CASE: dict[str, str] = {k: RENDERED_AS_LINE[k] for k in ("namespaces",)}
#: ④ 桶全体（回放红证按它剥离 = 还原修复前的 casebook）。
NEW_FIELD_PREFIXES: dict[str, str] = {**ONE_LINE_PER_DECLARATION, **ONE_LINE_PER_CASE}


# ── 判据本体（纯函数；真实断言与红证跑的是**同一份**实现，不会漂移）─────────────
def case_blocks(md: str) -> dict[str, str]:
    """casebook → `{用例 ID: 该用例的区块正文（含 `### <ID>.` 标题行）}`。

    标题行**计入**区块：`id` / `title` / `tier` 的可读形态就长在那里（② 桶的可见面）。
    """
    blocks: dict[str, list[str]] = {}
    cur: str | None = None
    for line in md.splitlines():
        if line.startswith("#"):
            m = re.match(r"^###\s+(\S+?)\.\s", line)
            cur = m.group(1) if m else None
        if cur is not None:
            blocks.setdefault(cur, []).append(line)
    return {k: "\n".join(v) for k, v in blocks.items()}


def declared_cases(cases, key: str):
    """声明了该字段（值非空）的用例。"""
    return [c for c in cases if c.get(key)]


def declared_field_names(cases) -> set[str]:
    """用例库里**声明过**（非空）的顶层字段名集合。"""
    return {k for c in cases for k, v in c.items() if v not in (None, "", [], {})}


def registered_field_names() -> set[str]:
    """三桶登记的全部字段名。"""
    return set(RENDERED_AS_LINE) | set(RENDERED_ELSEWHERE) | set(NOT_RENDERED)


def unregistered_fields(cases) -> list[str]:
    """被声明却没登记去向的字段（判据 1 的靶子）。"""
    return sorted(declared_field_names(cases) - registered_field_names())


def zombie_ledger_entries(cases) -> list[str]:
    """登记了却**没有任何用例声明**的字段（僵尸登记；台账只许缩短的机械形态）。"""
    return sorted(registered_field_names() - declared_field_names(cases))


def _lines_with_prefix(md: str, cid: str, prefix: str) -> list[str]:
    return [ln for ln in case_blocks(md).get(cid, "").splitlines() if ln.startswith(prefix)]


def unrendered_declaring_cases(cases, md: str, prefix_by_key: dict[str, str]) -> dict[str, list[str]]:
    """`{字段: [缺该行前缀的用例 ID]}` —— 判据 2（逐条可见）的靶子。"""
    blocks = case_blocks(md)
    out: dict[str, list[str]] = {}
    for key, prefix in prefix_by_key.items():
        missing = [c["id"] for c in declared_cases(cases, key)
                   if not any(ln.startswith(prefix) for ln in blocks.get(c["id"], "").splitlines())]
        if missing:
            out[key] = missing
    return out


def missing_declared_values(cases, md: str) -> dict[str, list[str]]:
    """判据 2 的值级核对：`persona` 的值、每个 `namespaces` token 必须出现在对应行上。"""
    out: dict[str, list[str]] = {}
    for c in declared_cases(cases, "persona"):
        head = f"{RENDERED_AS_LINE['persona']}{render_cases._one_line(c['persona'])}"
        if not any(ln.startswith(head) for ln in case_blocks(md).get(c["id"], "").splitlines()):
            out.setdefault("persona", []).append(c["id"])
    for c in declared_cases(cases, "namespaces"):
        ns_lines = _lines_with_prefix(md, c["id"], RENDERED_AS_LINE["namespaces"])
        missing_tokens = [render_cases._one_line(t) for t in render_cases._as_items(c["namespaces"])
                          if not any(t in ln for ln in ns_lines)]
        if missing_tokens:
            out.setdefault("namespaces", []).append(f"{c['id']}（缺 {missing_tokens}）")
    return out


def expected_line_count(key: str, case: dict) -> int:
    """该用例该字段**应**渲染的行数（④ 桶的行数契约）。"""
    if key in ONE_LINE_PER_CASE:
        return 1
    return len(render_cases._as_items(case[key]))


def line_count_mismatches(cases, md: str, prefix_by_key: dict[str, str]) -> dict[str, list[str]]:
    """判据 3：`{字段: ["<用例ID> 声明 N 项却渲染 M 行"]}`。"""
    out: dict[str, list[str]] = {}
    for key, prefix in prefix_by_key.items():
        bad = [
            f"{c['id']} 声明 {len(render_cases._as_items(c[key]))} 项却渲染 "
            f"{len(_lines_with_prefix(md, c['id'], prefix))} 行（应 {expected_line_count(key, c)} 行）"
            for c in declared_cases(cases, key)
            if len(_lines_with_prefix(md, c["id"], prefix)) != expected_line_count(key, c)
        ]
        if bad:
            out[key] = bad
    return out


def strip_lines(md: str, prefixes) -> str:
    """剥掉以任一前缀开头的行（红证用：把 casebook 还原成修复前的形态）。"""
    return "\n".join(ln for ln in md.splitlines()
                     if not any(ln.startswith(p) for p in prefixes))


def blank_persona_line_of(md: str, cid: str) -> str:
    """只抹掉**某一条**用例的 `端:` 行（红证用：证明判据按用例归因，不是整表糊判）。"""
    out, inside = [], False
    for line in md.splitlines():
        if line.startswith("#"):
            inside = line.startswith(f"### {cid}.")
        if inside and line.startswith(RENDERED_AS_LINE["persona"]):
            continue
        out.append(line)
    return "\n".join(out)


def load_cases():
    return render_cases.load_case_dicts(str(CASES_DIR))


def load_casebook() -> str:
    return CASEBOOK_PATH.read_text(encoding="utf-8")


# ── 判据 1：登记闭包（类级元守卫）────────────────────────────────────────────
class TestFieldLedgerIsClosed:
    def test_every_declared_field_is_registered(self):
        assert unregistered_fields(load_cases()) == [], (
            "这些用例字段被声明、却在 casebook 里**没有任何去向登记**（正是 issue #3968 的病灶形态："
            "字段在账本上静默消失）。请选一个出口：`RENDERED_AS_LINE`（给它一行）/ "
            "`RENDERED_ELSEWHERE`（说明它在哪里可见）/ `NOT_RENDERED`（写明为什么不渲染）"
        )

    def test_ledger_entries_are_alive(self):
        assert zombie_ledger_entries(load_cases()) == [], (
            "台账里有**无任何用例声明**的僵尸条目（登记了就不管 ⇒ 台账失真）⇒ 从对应桶删掉"
        )

    def test_new_field_prefixes_are_subset_of_line_bucket(self):
        assert set(NEW_FIELD_PREFIXES) <= set(RENDERED_AS_LINE), (
            "④ 桶（行数契约）必须是 ① 桶的子集，否则行数判据会绕过可见性判据"
        )

    def test_ledger_is_not_vacuous(self):
        cases = load_cases()
        assert len(cases) > 100, f"用例库只加载到 {len(cases)} 条 —— 装载器或路径坏了，判据会真空通过"
        for key, _prefix in NEW_FIELD_PREFIXES.items():
            assert declared_cases(cases, key), (
                f"没有任何用例声明 `{key}` ⇒ 该字段的可见性判据无对象（空断言）"
            )


# ── 判据 2 / 3：逐条可见 + 行数契约 ─────────────────────────────────────────
class TestDeclaredFieldsAreVisibleInCasebook:
    def test_every_declared_line_field_has_its_line(self):
        assert unrendered_declaring_cases(load_cases(), load_casebook(), RENDERED_AS_LINE) == {}, (
            "这些用例声明了字段、casebook 区块里却没有对应的行（读账本的人据此误判）"
        )

    def test_declared_values_are_visible(self):
        assert missing_declared_values(load_cases(), load_casebook()) == {}, (
            "端标注的值 / 命名空间 token 没出现在对应行上（行在、值不在 = 看不出是哪一端、和谁互斥）"
        )

    def test_elsewhere_visible_values_are_present(self):
        cases, md = load_cases(), load_casebook()
        blocks = case_blocks(md)
        for key in VALUE_VISIBLE_IN_BLOCK:
            missing = [f"{c['id']}（{key}={value}）"
                       for c in declared_cases(cases, key)
                       for value in render_cases._as_items(c[key])
                       if str(value) not in blocks.get(c["id"], "")]
            assert missing == [], f"② 桶登记为「在别处可见」的 `{key}` 实际不可见：{missing}"

    def test_line_count_contract_holds(self):
        assert line_count_mismatches(load_cases(), load_casebook(), NEW_FIELD_PREFIXES) == {}, (
            "行数不符合契约（典型：散文值被按**字符**迭代 ⇒ 一条前置渲染成上千行字符行；"
            "或多 token 的互斥组被拆成多行）"
        )

    def test_casebook_parser_is_not_vacuous(self):
        cases = load_cases()
        blocks = case_blocks(load_casebook())
        ids = [c["id"] for c in cases]
        assert set(ids) <= set(blocks), (
            "casebook 里找不到这些用例的区块（解析器坏了 ⇒ 可见性判据会真空通过）："
            f"{sorted(set(ids) - set(blocks))[:10]}"
        )


# ── 红证（常驻判别性检验，不是一次性人工验证）───────────────────────────────
class TestRedProof:
    def test_replaying_the_pre_fix_casebook_reports_every_declaring_case(self):
        """回放红：把新增行剥掉（= 修复前的 casebook）⇒ 判据必须报出**全部**声明该字段的用例。"""
        cases = load_cases()
        pre_fix = strip_lines(load_casebook(), NEW_FIELD_PREFIXES.values())
        assert pre_fix != load_casebook(), "剥离未生效 ⇒ 红证实验无效（前缀表与生成物脱节了？）"

        violations = unrendered_declaring_cases(cases, pre_fix, NEW_FIELD_PREFIXES)
        assert set(violations) == set(NEW_FIELD_PREFIXES), (
            f"剥掉新增行后判据没有逐个字段报红 ⇒ 可见性判据是空断言。实际 violations={sorted(violations)}"
        )
        for key in NEW_FIELD_PREFIXES:
            expected = sorted(c["id"] for c in declared_cases(cases, key))
            assert sorted(violations[key]) == expected, (
                f"`{key}` 漏报/多报：判据没把**全部**声明者算进来（期望 {len(expected)} 条）"
            )

    def test_char_explosion_is_reported(self):
        """构造红：一条声明被拆成多行（散文值按字符迭代的**实测**形态）⇒ 行数判据必红。"""
        cases = [{"id": "RG-999", "precondition": ["本用例是接口契约用例"]}]
        exploded = "### RG-999. 假用例 🔵\n```\n" + "\n".join(
            f"{RENDERED_AS_LINE['precondition']}{ch}" for ch in "本用例是接口契约用例") + "\n```"
        violations = line_count_mismatches(cases, exploded, {"precondition": RENDERED_AS_LINE["precondition"]})
        assert violations == {"precondition": ["RG-999 声明 1 项却渲染 10 行（应 1 行）"]}, (
            f"字符行形态未被判据认出 ⇒ 行数契约是空断言。实际 {violations}"
        )

    def test_split_mutex_group_is_reported(self):
        """构造红：多 token 的互斥组被拆成多行（同一行契约的反方向）⇒ 必红。"""
        cases = [{"id": "RG-997", "namespaces": ["customer_phone:1", "product_name:X"]}]
        split = "### RG-997. 假用例 🔵\n```\n" + "\n".join(
            f"{RENDERED_AS_LINE['namespaces']}: {n}" for n in cases[0]["namespaces"]) + "\n```"
        violations = line_count_mismatches(cases, split, {"namespaces": RENDERED_AS_LINE["namespaces"]})
        assert violations.get("namespaces"), f"拆行形态未被判据认出：{violations}"

    def test_injected_unregistered_field_is_reported(self):
        """构造红：用例声明了一个未登记字段 ⇒ 登记闭包判据必红。"""
        cases = load_cases() + [{"id": "RG-998", "title": "假用例", "brand_new_field": ["x"]}]
        assert "brand_new_field" in unregistered_fields(cases), (
            "未登记字段没被判红 ⇒ 「未登记即红」是空断言（新字段仍会静默消失在账本里）"
        )

    def test_blanking_one_case_line_reports_exactly_that_case(self):
        """构造红（判据 2 本体）：只抹掉**一条**用例的 `端:` 行 ⇒ 必须只报那一条。"""
        cases = load_cases()
        victim = declared_cases(cases, "persona")[0]["id"]
        violations = unrendered_declaring_cases(
            cases, blank_persona_line_of(load_casebook(), victim), {"persona": RENDERED_AS_LINE["persona"]})
        assert violations == {"persona": [victim]}, (
            f"抹掉 `{victim}` 的端标注行后判据没精确归因（应只报这一条）：{violations}"
        )