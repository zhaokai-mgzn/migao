# case_ids: MC-045
"""RBAC 单一真值源 **I4**：四个**真写**端点改挂写码 + 快照等价回填（跟踪单 issue #5699）。

设计真值源 = `docs/design/rbac-single-source.md` 的 §3.4 问题 2（I4 的来源）与 §4 的 P4 行；
**裁定**（人类 2026-09-27，选 A「新造专用写码」）= 把守码对齐到**写**码 `production:execute`，
并把它授予**今日持旧守卫码**的四个岗位 ⇒ **角色面零 403、别处零外溢**。

## 本判据判什么（逐条都有红证）

| 断言 | 形态 |
|---|---|
| 四个端点的**生效码** == `production:execute` | 逐条现取（`build_world().all_eps`），未登记/陈旧都红 |
| 它们是**方法级覆盖**（类级仍是**读**码 `order:list`） | 逐条现取 `ep.class_permission` —— 证明「写动作此前只由读码把守」这个**改前事实** |
| **零外溢**：生效码 == 新码的端点**恰好**是这四条 | 现取集合相等（多一处 ⇒ 红） |
| **角色面零 403**：`持旧码的岗位集 == 持新码的岗位集`（种子 ∪ 回退两来源） | 两侧都**现取** `code_holders()`；不等 ⇒ 报出「谁今天能过、改后过不去」 |
| 新码在目录里 + 在四个岗位的 seed/fallback 里 | 目录/两处口径逐值 |
| 新码**不出现在**菜单节点、也不被任何 B 端 Agent 工具声明 | 现取菜单码列 + 工具源码扫描（Agent 面零变化） |
| **快照等价回填**的三条谓词逐字在场（严格 JSON 数组 / 含旧码 / 不含新码） | `V138` 的 `UPDATE` 语句文本；丢掉「含旧码」 ⇒ **红**（那是「给更多人开门」） |

## 覆盖面边界（照实登记）

① 本判据算**声明面 + 注解面**，不是运行时授权（本机无真库/无 admin-api 环境 —— 设计 §6.1）；
② 快照面只覆盖 `users.permissions` 这一种快照形态（`user_roles` 关联、租户自建岗位、运行期新建账号**不在面内**）；
③ **员工快照的存量面**不可从仓内读（`UNCOVERED_FACES` 同款）：回填谓词的正确性由判据守，
   「生产库上有多少行命中」只能接真库用 `V138` 文件头给出的**只读事前/事后 SQL**复核。
"""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RBAC_DIR = REPO_ROOT / "rbac"
MANIFEST_PATH = RBAC_DIR / "manifest.json"
DERIVE_PATH = RBAC_DIR / "derive.py"
GENERATOR_PATH = RBAC_DIR / "generate_migration.py"
PARITY_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"

#: I4 的**唯一真值源**（本表）：四个真写端点 + 改前/改后守卫码。判据逐条对现取。
I4_CODE = "production:execute"
I4_ALIGNED: dict[str, dict[str, str]] = {
    "POST /api/admin/production/orders/{}/instantiate": {
        "code_before": "order:list",
        "code_after": I4_CODE,
        "what": "建加工单（工序实例化）",
    },
    "POST /api/admin/production/orders/{}/operations/{}/report": {
        "code_before": "order:list",
        "code_after": I4_CODE,
        "what": "扫码报工",
    },
    "POST /api/admin/production/orders/{}/print": {
        "code_before": "order:list",
        "code_after": I4_CODE,
        "what": "打印计数（`print_count` 落库）",
    },
    "POST /api/admin/production/orders/{}/ship": {
        "code_before": "order:list",
        "code_after": I4_CODE,
        "what": "发货（流转订单状态 + 落单号）",
    },
}

#: 今日持旧守卫码、因而**必须**同时持新码的岗位（`admin` 恒 `*`，不逐条列）。
I4_TARGET_ROLES = ("customer_service", "finance", "operator", "sales")


def _load(mod_name: str, path: Path):
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    assert path.is_file(), f"被复用的模块不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec and spec.loader, f"无法为 {path} 建立加载器（fail-closed）"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_derive():
    return _load("migao_rbac_derive_i4", DERIVE_PATH)


def load_generator():
    return _load("migao_rbac_generate_migration_i4", GENERATOR_PATH)


def load_parity_guard():
    return _load("migao_rbac_parity_i4", PARITY_GUARD)


def load_manifest() -> dict:
    return load_derive().load_manifest(MANIFEST_PATH)


def i4_migration_text() -> str:
    generator = load_generator()
    rel = next(r for r in generator.ARTIFACTS if "production_execute" in r)
    path = REPO_ROOT / rel
    assert path.is_file(), f"`{rel}` 不存在 ⇒ I4 的存量侧没有物化（{path}）"
    return path.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# 判据（纯函数）
# ══════════════════════════════════════════════════════════════════════════════


def aligned_problems(world, manifest: dict, parity) -> list[str]:
    """四条对齐 + 零外溢 + 角色面零 403 + Agent/菜单面零变化。"""
    derive = load_derive()
    out: list[str] = []
    tables = derive.role_tables(manifest)
    live: dict[str, list[str]] = {}
    for (verb, path), eps in world.all_eps.items():
        for ep in eps:
            code = ep.permission
            if code:
                live.setdefault(code, []).append(f"{verb} {path}")

    for key, entry in sorted(I4_ALIGNED.items()):
        verb, _, url = key.partition(" ")
        eps = world.all_eps.get((verb, url))
        if not eps:
            out.append(f"`{key}` 在端点表里找不到 ⇒ 台账陈旧（端点改名/删除必须同批改台账）")
            continue
        codes = {ep.permission for ep in eps}
        if entry["code_after"] not in codes:
            out.append(
                f"`{key}` 的生效码现取 {sorted(c for c in codes if c)} —— 不含 `{entry['code_after']}` ⇒ "
                "I4 的改码没落地（或被回退）"
            )
        class_codes = {ep.class_permission for ep in eps}
        if entry["code_before"] not in class_codes:
            out.append(
                f"`{key}` 的**类级**码现取 {sorted(c for c in class_codes if c)} —— 不含 "
                f"`{entry['code_before']}` ⇒ 台账记的「改前守卫码」与现取不符（那条「写动作只由读码把守」"
                "的改前事实必须可复核）"
            )

    # 零外溢：生效码 == 新码的端点集**恰好**是台账四条
    live_new = set(live.get(I4_CODE, []))
    registered = set(I4_ALIGNED)
    for extra in sorted(live_new - registered):
        out.append(
            f"`{I4_CODE}` 还挂着**台账之外**的端点 `{extra}` ⇒ 越界（新码只许把守台账里的这四条写端点）"
        )
    for stale in sorted(registered - live_new):
        out.append(f"台账里的 `{stale}` 现取生效码不是 `{I4_CODE}` ⇒ 陈旧/漏改")

    # 角色面零 403：持旧码的岗位集 == 持新码的岗位集（两来源分别算）
    before = sorted(derive.code_holders(I4_ALIGNED[next(iter(I4_ALIGNED))]["code_before"], *tables))
    after = sorted(derive.code_holders(I4_CODE, *tables))
    if before != after:
        only_before = sorted(set(before) - set(after))
        only_after = sorted(set(after) - set(before))
        out.append(
            f"角色面出现差额 ⇒ 「今天能过、改后被 403」或「今天不能过、改后能过」："
            f"今天能过改后过不去 {only_before}；今天过不去改后能过 {only_after}（before={before} after={after}）"
        )

    # 目录 + 两处口径（seed / fallback）逐值
    if I4_CODE not in manifest["codes"]["registration"]:
        out.append(f"`{I4_CODE}` 不在清单目录里（新码必须进目录，否则端点注解引用的是不存在的码）")
    if manifest["codes"]["names"].get(I4_CODE) != "生产执行":
        out.append(f"`{I4_CODE}` 的名称列现取 {manifest['codes']['names'].get(I4_CODE)!r} ≠ '生产执行'")
    for role in I4_TARGET_ROLES:
        for face in ("seed", "fallback"):
            codes = manifest["roles"][face].get(role) or []
            if I4_CODE not in codes:
                out.append(
                    f"`{role}` 的 `roles.{face}` 里没有 `{I4_CODE}` ⇒ "
                    "该岗位今天靠旧读码过这四个端点，改后会被 403（现场停线形态）"
                )

    # Agent 面 / 菜单面：新码一处都不许出现（那是「多开一扇门」）
    for key, text in sorted(world.sources.items()):
        if key.startswith("tool:") and I4_CODE in text:
            out.append(f"B 端 Agent 工具 `{key}` 声明了 `{I4_CODE}` ⇒ Agent 面被顺带放宽（本单不做）")
    return out


def menu_and_pages_problems(manifest: dict, present: dict) -> list[str]:
    """新码不许出现在任何菜单节点码列里（可见面零变化）。"""
    out = []
    for source, nodes in sorted(present.get("menu_node_codes", {}).items()):
        del source, nodes
    for label, nodes in sorted(present.items()):
        if label in ("menu_node_codes", "menu_controller_codes", "auth_menu_codes"):
            for name, code in sorted(dict(nodes).items()):
                if code == I4_CODE:
                    out.append(f"菜单源 `{label}` 的节点『{name}』用了 `{I4_CODE}` ⇒ 可见面被改（本单只改写面）")
    return out


def snapshot_backfill_problems(sql: str) -> list[str]:
    """快照等价回填的**三条谓词**必须逐字在场（丢掉「含旧码」⇒ 那是给更多人开门）。"""
    out: list[str] = []
    marker = "UPDATE users"
    if marker not in sql:
        return ["`V138` 里没有快照回填的 `UPDATE users` 语句 ⇒ 有权限快照的账号会在这四个端点 403"]
    stmt = sql[sql.index(marker):]
    stmt = stmt[: stmt.index(";")]
    if "permissions ~ '" not in stmt:
        out.append("快照回填缺**严格 JSON 数组**谓词（`permissions ~ '…'`）⇒ 脏数据上 `::jsonb` 会炸")
    if f"'%\"{I4_ALIGNED[next(iter(I4_ALIGNED))]['code_before']}\"%'" not in stmt:
        out.append(
            "快照回填缺**「含旧守卫码」**前置条件 ⇒ 它会去动「今天本来就过不去」的账号 = "
            "**放宽**（设计 §2.9 的窄例外只覆盖旧码在场的快照）"
        )
    if f"NOT LIKE '%\"{I4_CODE}\"%'" not in stmt:
        out.append("快照回填缺**「不含新码」**谓词 ⇒ 不幂等（第二遍会把码追加两次）")
    return out


def all_problems(world, manifest: dict, present: dict, parity, sql: str | None = None) -> list[str]:
    out = aligned_problems(world, manifest, parity)
    out += menu_and_pages_problems(manifest, present)
    out += snapshot_backfill_problems(sql if sql is not None else i4_migration_text())
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 断言（正例 + 红证 + 对照）
# ══════════════════════════════════════════════════════════════════════════════


def _world_and_present():
    derive, parity = load_derive(), load_parity_guard()
    sources = parity._source_map()
    world = parity.build_world(sources)
    present = derive.page_present(parity, sources)
    return world, present, parity


def test_i4_is_green_on_the_current_tree():
    world, present, parity = _world_and_present()
    problems = all_problems(world, load_manifest(), present, parity)
    assert problems == [], "I4 判据未通过：\n" + "\n".join(f"  - {p}" for p in problems)


def test_readings_are_the_expected_zero_delta():
    """**现取读数**（供 PR body 引用）：改前/改后能过的岗位集逐值相同。"""
    derive, manifest = load_derive(), load_manifest()
    tables = derive.role_tables(manifest)
    before = sorted(derive.code_holders(I4_ALIGNED[next(iter(I4_ALIGNED))]["code_before"], *tables))
    after = sorted(derive.code_holders(I4_CODE, *tables))
    assert before == after == ["admin", "customer_service", "finance", "operator", "sales"], (before, after)


def test_dropping_a_method_level_override_is_red():
    """红证：把 `instantiate` 的方法级写码注解删掉（源码文本变异）⇒ 必须报出「不含 production:execute」。"""
    derive, parity, manifest = load_derive(), load_parity_guard(), load_manifest()
    sources = parity._source_map()
    key = "java:controller/ProductionController.java"
    needle = '    @PostMapping("/orders/{orderId}/instantiate")\n    @RequirePermission("production:execute")\n'
    assert needle in sources[key], "变异注入的锚不在源码里（自证失败）"
    mutated = dict(sources)
    mutated[key] = sources[key].replace(
        needle, '    @PostMapping("/orders/{orderId}/instantiate")\n', 1
    )
    assert mutated[key] != sources[key], "变异注入未生效（自证失败）"
    world = parity.build_world(mutated)
    present = derive.page_present(parity, mutated)
    problems = all_problems(world, manifest, present, parity)
    assert any("instantiate" in p and I4_CODE in p for p in problems), f"删掉方法级写码没被判红：{problems}"
    # 同时它必须回到「写动词 + 读码」形态（判据侧的另一半由 P4 判据的台账守）
    assert any("类级" in p or "陈旧/漏改" in p for p in problems), f"陈旧分支没命中：{problems}"


def test_an_extra_endpoint_on_the_new_code_is_red():
    """红证（零外溢）：给另一个端点也挂上新码 ⇒ 必须报「台账之外的端点」。"""
    derive, parity, manifest = load_derive(), load_parity_guard(), load_manifest()
    sources = parity._source_map()
    key = "java:controller/ProductionController.java"
    needle = '    @GetMapping("/stuck-points")\n'
    assert needle in sources[key], "变异锚不在源码里（自证失败）"
    mutated = dict(sources)
    mutated[key] = sources[key].replace(
        needle, needle + f'    @RequirePermission("{I4_CODE}")\n', 1
    )
    world = parity.build_world(mutated)
    present = derive.page_present(parity, mutated)
    problems = all_problems(world, manifest, present, parity)
    assert any("台账之外" in p and "stuck-points" in p for p in problems), f"零外溢被破坏却没报出：{problems}"


def test_snapshot_backfill_predicate_is_load_bearing():
    """红证：丢掉「含旧守卫码」这条前置条件 ⇒ 必须红（那是把窄例外读成放宽）。"""
    sql = i4_migration_text()
    assert snapshot_backfill_problems(sql) == [], "前提：现取迁移的快照谓词必须合规"
    old = "'%\"order:list\"%'"
    assert old in sql
    tampered = sql.replace(f"   AND permissions LIKE {old}\n", "", 1)
    assert tampered != sql, "变异注入未生效（自证失败）"
    problems = snapshot_backfill_problems(tampered)
    assert any("含旧守卫码" in p for p in problems), f"丢掉前置条件没被判红：{problems}"


def test_comment_only_change_is_not_red():
    """**对照读数**：只改清单散文 ⇒ I4 判据不红（判的是码与谓词，不是文件变没变）。"""
    derive, parity = load_derive(), load_parity_guard()
    sources = parity._source_map()
    prose = copy.deepcopy(load_manifest())
    prose["_note"] = str(prose["_note"]) + "（只改散文的一句）"
    world = parity.build_world(sources)
    present = derive.page_present(parity, sources)
    assert all_problems(world, prose, present, parity) == [], "只改散文竟判红 ⇒ 判据在读文本而不是在读语义"
