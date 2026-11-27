# case_ids: HR-010, HR-014, PP-002
"""真值耦合判据：用例里的「岗位码 / 分类名 / 期望工具」必须与**代码常量、种子数据、工具面**同一份真值（issue #9220）。

## 为什么要有这个文件

2026-11-27 集中评测 `run 45979067843` 现取两条红，**都不是 agent 行为错，而是用例前提过期**：

* `HR-010`：`R2 failed=employee_manage{action=create}!角色 agent 为系统保留角色，禁止在员工管理中分配[VALIDATION_ERROR]`。
  「客服账号」在**旧**世界里用 `role: agent` 表达；`agent` 现在是**系统保留角色**
  （`backend/admin-api/src/main/java/com/migao/admin/service/UserService.java` 的
  `FORBIDDEN_USER_ROLES`），商户侧真实「客服」岗位码是 `customer_service`（`roles` 种子行）。
* `PP-002`：`you=基础加工分类下有哪些 → tools=processing_item_manage(action=list_categories)`，
  而评测栈里**没有**「基础加工」这个加工分类（`git grep 基础加工 -- '*.sql'` 0 命中）⇒
  模型只能答「没有这个分类」，`processing_item_query` 永远不被调用（与「agent 不干活」同形）。

⇒ 把「用例改动必须踩在真值上」落成**会红**的判据，而不是靠下一次真跑 LLM 才发现。

## 四条判据（每条都自带红证）

1. `HR-010` 的 create 岗位码 ∉ 源码保留集 **且** ∈ `roles` 种子（真值**现取解析**，不写死字面量）；
2. `HR-010` 的输入文案逐字点名该岗位码（文本 ⇄ 值不断链），且 `must_succeed` / `db_verify` 仍承重（未放宽）；
3. `HR-014` 逐码登记了源码保留集，且**校验先于落库**（源码顺序判据）+ 真值模板 ⇄ 源码 ⇄ 用例三向一致；
4. `PP-002` 的分类名 ∈ 评测种子分类，且期望工具 = 能返回「加工项」的那个工具（`list_categories` 只返回分类行）。

红证（本单实测，逐条见 `test_...` docstring）：把 `role` 改回 `agent` ⇒ 1 具名红；
把 `PP-002` 的 R1 改回「基础加工」⇒ 4 具名红；把期望工具换成 `processing_item_manage` ⇒ 4 具名红；
把校验挪到 `userMapper.insert` 之后 ⇒ 3 具名红。

## 纪律

本文件**不用正则**（`migao-dev-flow` §34.9-B 第 1 条：不许按引号定界从源码原文取值），一律
`split` / `in` / 索引切片；断言到**具体内容**（弱断言台账：禁 `is not None` / `len(...) > 0`）。
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

USER_SERVICE = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/UserService.java"
BOOTSTRAP_SCHEMA = REPO_ROOT / "backend/admin-api/src/main/resources/db/init/schema.sql"
EVAL_SEED = REPO_ROOT / "tests/agent_eval/fixtures/xiaobu_eval_seed.sql"
TRUTH_TEMPLATE = REPO_ROOT / ".github/templates/employee-role.yml"
ITEM_QUERY_TOOL = REPO_ROOT / "backend/ai-agent-service/app/tools/processing_item_query.py"
ITEM_MANAGE_TOOL = REPO_ROOT / "backend/ai-agent-service/app/tools/processing_item_manage.py"

CASES_DIR = REPO_ROOT / ".github/cases"


def _listed_codes(text: str, anchor: str) -> set[str]:
    """从用例/模板的散文里取**被逐码列举的**角色码集合（锚点之后、下一个分隔符之前）。

    为什么不用「某处提到该词」：散文里的**顺带提及**（例如解释「agent 是 B2C 角色」）会让
    「漏登记」判据静默变绿 —— 红证里抓到过（本单第 5 条注入曾 rc=0）。故判据取**列举段**，
    并按集合**双向相等**判（漏登记 / 多登记都红）。
    """
    tail = text.split(anchor, 1)[1]
    cut = len(tail)
    for sep in ("）", "；", "\n"):
        pos = tail.find(sep)
        if pos != -1:
            cut = min(cut, pos)   # 取**最早**的分隔符：列举段之后可能还跟着别的分隔符
    tail = tail[:cut]
    return {chunk.strip().strip("`").strip() for chunk in tail.split("/") if chunk.strip()}


def _case(yml: str, case_id: str) -> dict:
    """按 ID 取用例块；取不到即判红（用例被改名/删除时本判据必须跟着红，不许静默跳过）。"""
    doc = yaml.safe_load((CASES_DIR / yml).read_text(encoding="utf-8"))
    for case in doc["cases"]:
        if case.get("id") == case_id:
            return case
    raise AssertionError(f"{yml} 里找不到用例 {case_id} —— 用例改名/删除时必须同步本判据")


def _forbidden_user_roles() -> set[str]:
    """真值来源①：`UserService.FORBIDDEN_USER_ROLES`（系统保留角色集）—— 现取解析，不写死。"""
    text = USER_SERVICE.read_text(encoding="utf-8")
    marker = "FORBIDDEN_USER_ROLES = java.util.Set.of("
    body = text.split(marker, 1)[1].split(");", 1)[0]
    return {
        chunk.strip().strip('"')
        for chunk in body.replace("\n", " ").split(",")
        if chunk.strip()
    }


def _seeded_role_codes() -> set[str]:
    """真值来源②：bootstrap `schema.sql` 的 `INSERT INTO roles` 第四列（角色码）。"""
    text = BOOTSTRAP_SCHEMA.read_text(encoding="utf-8")
    body = text.split("INSERT INTO roles", 1)[1].split("ON CONFLICT", 1)[0]
    codes: set[str] = set()
    # `body.split("(")` 的第 1 段是列名表头，真正的行从第 2 段起。
    for row in body.split("(")[2:]:
        cols = [c.strip().strip("'") for c in row.split(")", 1)[0].split(",")]
        if len(cols) >= 4 and cols[0].startswith("role_"):
            codes.add(cols[3])
    return codes


def _category_seed_blocks() -> list[str]:
    """两处 `processing_categories` 种子语句的正文（bootstrap 建库脚本 + 评测夹具）。"""
    blocks: list[str] = []
    for path in (BOOTSTRAP_SCHEMA, EVAL_SEED):
        text = path.read_text(encoding="utf-8")
        blocks.extend(chunk.split(";", 1)[0] for chunk in text.split("INSERT INTO processing_categories")[1:])
    return blocks


def _seeded_category_names() -> set[str]:
    """种子分类名（只取含中日韩字符的字面量 —— 用来在红信息里列出「现实有哪些分类」）。"""
    names: set[str] = set()
    for block in _category_seed_blocks():
        for literal in block.split("'")[1::2]:
            if any("\u4e00" <= ch <= "\u9fff" for ch in literal):
                names.add(literal)
    return names


def test_hr010_create_role_is_a_real_assignable_position():
    """HR-010 的岗位码必须是「真实可分配岗位」：∉ 源码保留集，∈ `roles` 种子。

    红证（本单实测）：把 `arg_values` 的 `role` 写回 `agent` ⇒ 具名红（两个断言都命中：
    `agent` 在保留集里、且不在 `roles` 种子里）。
    """
    case = _case("hr.yml", "HR-010")
    specs = [
        spec for spec in case.get("arg_values") or []
        if spec.get("tool") == "employee_manage" and spec.get("action") == "create"
    ]
    assert len(specs) == 1, (
        "HR-010 必须用 `arg_values` 钉住 create 的岗位码（值级断言；"
        f"`required_args` 的存在性顶替不了值相等，issue #3823）—— 现取 {len(specs)} 条")
    role = str(specs[0]["values"]["role"])

    forbidden = _forbidden_user_roles()
    seeded = _seeded_role_codes()
    assert role not in forbidden, (
        f"HR-010 的 create 岗位 role={role!r} 属**系统保留角色**（源码 FORBIDDEN_USER_ROLES="
        f"{sorted(forbidden)}）⇒ 服务端必返 422 VALIDATION_ERROR ⇒ 本条必红"
        f"（run 45979067843 的 agent 即此形态）")
    assert role in seeded, (
        f"HR-010 的 create 岗位 role={role!r} 不在 `roles` 种子角色码里（现取：{sorted(seeded)}）"
        f"⇒ 它无法在员工管理里被分配，不是「客服账号」的真实岗位码")


def test_hr010_input_names_the_pinned_role_and_keeps_effect_assertions():
    """输入文案必须逐字点名岗位码（否则模型又会自选保留角色），且效果层断言一条未删。

    红证：把 `user_inputs[0]` 改回「帮我开个客服账号」（不带岗位码）⇒ 具名红；
    删 `must_succeed` / `db_verify` ⇒ 具名红（本单只增不减）。
    """
    case = _case("hr.yml", "HR-010")
    specs = [
        spec for spec in case.get("arg_values") or []
        if spec.get("tool") == "employee_manage" and spec.get("action") == "create"
    ]
    role = str(specs[0]["values"]["role"])
    first_input = str(case["user_inputs"][0])
    assert role in first_input, (
        f"输入文案必须逐字点名岗位码 {role!r}（如「岗位用「客服」（{role}）」）—— "
        f"只写「客服账号」会让模型又自选 {sorted(_forbidden_user_roles())} 里的码；"
        f"现取输入={first_input!r}")

    effect = [
        spec for spec in case.get("must_succeed") or []
        if spec.get("tool") == "employee_manage" and spec.get("action") == "create"
    ]
    assert len(effect) == 1, "HR-010 的 must_succeed[employee_manage(action=create)] 必须保留（正向对照的承重断言）"
    assert [item.get("fetch") for item in case.get("db_verify") or []] == ["employee"], (
        "HR-010 的 db_verify[employee]（落库行真的在，拦 #3550 的 200 假成功）必须保留")
    assert case.get("skip_reason") == "", "HR-010 不许重新登记 skip（capability 已接回，skip = 让能力零断言覆盖）"


def test_hr010_data_check_registers_the_reserved_role_rule():
    """`data_checks` 必须登记「保留角色不得分配」这条规则，且逐码覆盖源码保留集。

    红证：从 `data_checks` 里删掉 `agent` ⇒ 具名红（漏登记集合非空）。
    """
    case = _case("hr.yml", "HR-010")
    text = " ".join(str(check) for check in case["data_checks"])
    listed = _listed_codes(text, "系统保留角色（")
    forbidden = _forbidden_user_roles()
    assert listed == forbidden, (
        f"HR-010 的 data_checks 登记的保留集 {sorted(listed)} 与源码 FORBIDDEN_USER_ROLES "
        f"{sorted(forbidden)} **不等**（双向判：漏登记 / 多登记都红）—— 源码保留集变更时必须同批改判用例")
    assert "VALIDATION_ERROR" in text, "data_checks 必须点名具名错误码 VALIDATION_ERROR（不得被吞成通用失败）"
    assert "系统保留角色" in text, "data_checks 必须点明规则名「系统保留角色」"


def test_hr014_registers_every_reserved_role_with_real_evidence():
    """HR-014（保留角色被拒）必须逐码登记源码保留集，且 `traces.tests` 全是真实文件。

    红证：从源码保留集删一个码而不改用例 ⇒ 模板/用例三向比对红（见下一条）；
    把 traces 指向不存在的文件 ⇒ 具名红。
    """
    case = _case("hr.yml", "HR-014")
    text = " ".join(str(check) for check in case["data_checks"])
    listed = _listed_codes(text, "`UserService.FORBIDDEN_USER_ROLES`（")
    forbidden = _forbidden_user_roles()
    assert listed == forbidden, (
        f"HR-014 的 data_checks 登记的保留集 {sorted(listed)} 与源码 {sorted(forbidden)} **不等**"
        f"（双向判：漏登记 / 多登记都红）")
    assert "VALIDATION_ERROR" in text, "HR-014 必须点名具名错误码 VALIDATION_ERROR"

    refs = [str(ref) for ref in (case.get("traces") or {}).get("tests") or []]
    assert len(refs) >= 3, f"HR-014 必须声明执行点（traces.tests）—— backend-contract 用例没有执行点就是空断言；现取 {refs}"
    for ref in refs:
        assert (REPO_ROOT / ref).is_file(), f"HR-014 的 traces.tests 引用了不存在的文件：{ref}"
    service_test = (REPO_ROOT / "backend/admin-api/src/test/java/com/migao/admin/service/UserServiceTest.java")
    assert "系统保留角色" in service_test.read_text(encoding="utf-8"), (
        "UserServiceTest 里必须仍有「系统保留角色」的具名断言 —— 删掉它 = HR-014 的计分通道变空")


def test_reserved_role_guard_rejects_before_any_write():
    """保留角色校验必须在落库**之前**（先查后写，不落半条）。

    红证：把 `assertAssignableRoleAndPermissions(...)` 调用挪到 `userMapper.insert(user)` 之后 ⇒ 具名红。
    """
    src = USER_SERVICE.read_text(encoding="utf-8")
    marker = "assertAssignableRoleAndPermissions(role, permissions, tenantId);"
    assert src.count(marker) == 1, (
        f"`createUser` 必须（恰一次）调用保留角色/通配码/⊆ 门禁，现取 {src.count(marker)} 次"
        f"—— 删掉它 = 保留角色可以落库")
    guard = src.index(marker)
    insert = src.index("userMapper.insert(user);")
    assert guard < insert, (
        "保留角色/通配码/⊆ 门禁必须在**落库之前**（先校验后写库）—— 挪到 insert 之后 = 先落半条再回滚，"
        "HR-014 的「不落库」判据会失去对象")


def test_truth_template_lists_the_same_reserved_roles():
    """真值模板 ⇄ 源码常量必须逐码一致（三向耦合的第三侧）。

    红证：从 `.github/templates/employee-role.yml` 的 `employee-role.reserved-role-blocked` 里删掉
    一个码 ⇒ 具名红。
    """
    lines = [
        line for line in TRUTH_TEMPLATE.read_text(encoding="utf-8").splitlines()
        if "employee-role.reserved-role-blocked" in line
    ]
    assert len(lines) == 1, (
        f"真值模板里必须恰有一条 `employee-role.reserved-role-blocked`，现取 {len(lines)} 条")
    listed = _listed_codes(lines[0], "UserService.FORBIDDEN_USER_ROLES` = ")
    forbidden = _forbidden_user_roles()
    assert listed == forbidden, (
        f"真值模板登记的保留集 {sorted(listed)} 与源码 {sorted(forbidden)} **不等**"
        f"（双向判：漏登记 / 多登记都红）—— 模板与常量必须同批改")


def test_no_assignable_seeded_role_is_forbidden():
    """保留集不得吃掉商户侧可分配岗位（否则「客服」岗位开不出来 = 过度拦截）。

    红证：把 `customer_service` 加进 `FORBIDDEN_USER_ROLES` ⇒ 具名红（交集变成两个）。
    """
    forbidden = _forbidden_user_roles()
    seeded = _seeded_role_codes()
    overlap = sorted(forbidden & seeded)
    assert set(overlap) <= {"super_admin"}, (
        f"商户侧可分配岗位不得被列进保留集（现取交集 {overlap}）—— 往里塞 customer_service / operator "
        f"之类会变成「过度拦截」，HR-010 的正向对照直接失效")


def test_pp002_category_name_exists_in_seed_data():
    """PP-002 的 R1 必须点名**种子里真实存在**的加工分类。

    红证（本单实测）：把 R1 改回「基础加工分类下有哪些」⇒ 具名红（`基础加工` 不在种子分类里）。
    """
    case = _case("processing.yml", "PP-002")
    first_input = str(case["user_inputs"][0])
    category = first_input.split("分类下", 1)[0]
    seeded = _seeded_category_names()
    assert category in seeded, (
        f"PP-002 的 R1={first_input!r} 点名的分类 {category!r} 不在评测种子/建库脚本的 "
        f"processing_categories 里（现取：{sorted(seeded)}）⇒ 模型只能答「没有这个分类」，"
        f"期望工具永远不会被调用（run 45979067843 的红形态）")
    assert "加工项" in first_input, (
        "R1 必须逐字问「加工项」——否则「分类下有哪些」会把期望工具拖成分类树工具（list_categories 只有分类行）")


def test_pp002_expects_the_item_catalog_tool_and_keeps_the_operations_assertion():
    """PP-002 的期望工具必须是能返回「加工项」的那个工具，且「工序库」那条已通过的断言原样保留。

    工具面真值（现取解析）：`processing_item_query` 声明 `category_id` 参数、返回的每条记录含
    `category_name`；`processing_item_manage` 的 `list_categories` 只返回 `categories`（分类行），
    没有任何加工项字段 ⇒ 它答不了「某分类下有哪些加工项」。
    红证（本单实测）：把期望换成 `processing_item_manage(action=list_categories)` ⇒ 具名红。
    """
    case = _case("processing.yml", "PP-002")
    specs = [spec for spec in case["expectations"] if isinstance(spec, dict)]
    tools = {str(spec.get("tool")) for spec in specs}
    assert "processing_item_query" in tools, (
        f"PP-002 的 R1「分类下有哪些加工项」的期望工具必须是加工项目录查询工具 processing_item_query"
        f"（现取 expectations 工具集：{sorted(tools)}）")

    operations = [spec for spec in specs if spec.get("tool") == "operation_catalog_query"]
    assert [str((spec.get("args") or {}).get("action")) for spec in operations] == ["operations"], (
        "「工序库里有哪些工序」那条**已通过**的断言（operation_catalog_query action=operations）必须原样保留")

    query_src = ITEM_QUERY_TOOL.read_text(encoding="utf-8")
    assert '"category_id"' in query_src, "processing_item_query 必须仍声明 category_id 参数（本题的过滤面）"
    assert '"category_name"' in query_src, "processing_item_query 必须仍回传 category_name（证明它返回的是加工项行）"

    manage_src = ITEM_MANAGE_TOOL.read_text(encoding="utf-8")
    assert '"categories"' in manage_src, "processing_item_manage 的 list_categories 仍只返回 categories"
    assert "category_name" not in manage_src, (
        "processing_item_manage 里出现了 category_name —— 若它真的开始返回加工项行，本判据的前提变了，"
        "必须重新判「R1 的正解工具」（不许直接放宽断言）")
