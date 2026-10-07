# case_ids: MC-005
"""岗位目录读端点的**权限注解守卫**（issue #5980；口径真值源 `docs/wiki/RBAC.md` 的
「权限注解面审计（issue #4727）」与「放行策略现状」分支 ③）。

## 这一条判据要治什么（类级尺度，不是只修一处）

`docs/wiki/RBAC.md` 逐字登记：`/api/admin/**` 门禁的**分支 ③** = 「**没有 `@RequirePermission`
的端点 = 对所有商户员工开放**（含零权限岗位）」。⇒ 一个**读**端点只要漏加注解，它对**全部 9 个身份**
（含 0 权限的自定义岗位）返回 200，而**没有任何东西会变红** —— 这正是 #4727 的审计对象，
也是 issue #5980 的现场（`GET /api/admin/roles` 与 `GET /api/admin/roles/all` 均无注解）。

issue #5980 只修了那两条端点。**本条判据做的是类级固化**：把 AdminRoleController 的**全部端点**
钉成一张**逐条现取**的台账 —— 将来有人给这个（或另一个商户可见的）controller 加一个读端点
却忘了加注解，**当场红**，不必等下一个人来审计。

## 判什么（六条，逐条可归因）

1. **controller 里每个端点的生效码必须登记在台账里**（未登记即红；台账只管这一个 controller）；
2. **登记 = 声明**：台账里**声明 `@RequirePermission`** 的条目，其现取生效码必须**非空**且**逐字等于**登记值
   （注解被删 / 被改成别的码 ⇒ 红）；
   ⚠️ 台账的 `exempt` 面**只许缩短**：issue #5980 之前它是三条 `GET`，落地后**必须为空** ——
   把它改回 `exempt`（「把注解摘回去」）⇒ 红；
3. **端点级豁免台账**：`GET /api/admin/roles{,/all,/{}}` 三条必须**在场**且带 `view` 码（漏掉一条 ⇒ 红）——
   这是「岗位下拉 / 岗位权限页回显仍有码可依」的**最低保证**（只许收紧，不许整条删除）；
4. **码必须在权限目录里**（`RegistrationService` 的种子目录；码名字打错 ⇒ 该端点对所有人恒 403 ⇒ 红）；
5. **austere 面的元判据**：`/api/admin/**` 面上「无任何生效码」的端点**总数**必须 **≤ ADMIN_SCOPE_UNANNOTATED_CEILING**
   （现取、只许缩短）—— 对照组读数写进台账，让「沉默放行」的存量**可见**；
6. **判别力自证**：五种坏形态在**内存构造的源码**上各自判红 + 「只改注释 ⇒ 不红」的对照。

## 覆盖面边界（照实登记，不粉饰）

- **只裁 `AdminRoleController`**：`/api/admin/**` 上其余无码端点由**既有**台账管
  （`tests/unit_ci_workflows/test_agent_permission_parity.py` 的判据 8 + `UNANNOTATED_ENDPOINTS`，
  逐条带理由）—— 本条判据**不复制**那份台账（同一事实两处登记 = 又一处并行真值）；
- **判「注解面」不判运行时授权**：本机无真库 / 无 admin-api 环境（与 #4727 的审计同口径）；
  运行时行为面由 `backend/admin-api/src/test/java/com/migao/admin/security/SecurityConfigTest.java`
  的身份级用例承担（该文件同 PR 补了 9 身份读数）；
- **`@RequirePermission` 的合法取值不设白名单**：只要求「在权限目录里」（第 4 条），不判「该用哪个码」
  —— 选码是产品裁定（本条判据不替人做决定）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_SERVICE = REPO_ROOT / "backend" / "ai-agent-service"
JAVA_MAIN = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"
CONTROLLER_DIR = JAVA_MAIN / "com" / "migao" / "admin" / "controller"
ROLE_CONTROLLER_FILE = "com/migao/admin/controller/AdminRoleController.java"
ATTRIBUTION_PATH = AI_SERVICE / "tests" / "tool_http_attribution.py"
PARITY_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"
LEDGER_PATH = REPO_ROOT / "tests" / "unit_ci_workflows" / "admin_role_read_surface_ledger.json"

REGISTRATION_SERVICE = CONTROLLER_DIR.parent / "service" / "RegistrationService.java"
PERMISSION_SERVICE = CONTROLLER_DIR.parent / "service" / "PermissionService.java"

#: 端点级豁免台账的**冻结下限**（issue #5980 落地的三条读码）。**只许收紧**：
#: 少一条（把注解摘回去 / 把端点改回无码）⇒ 红。
ROLE_READ_ENDPOINTS: dict[str, str] = {
    "GET /api/admin/roles": "system:view",
    "GET /api/admin/roles/all": "employee:list",
    "GET /api/admin/roles/{}": "system:view",
}

#: `/api/admin/**` 面上「无任何生效码」的端点**总数**现取上限（只许缩短；对照读数写进台账）。
#:
#: 10 → 11（issue #6367 包 P2，2026-10-05）：新增 `POST /api/admin/image-recognition/interpret`，
#: 与既有 `POST /api/admin/image-recognition` **同族**（一个入口覆盖 `product:create` / `order:create`
#: 两种写码 ⇒ `@RequirePermission` 表达不了分叉 ⇒ 命令式 `PermissionInterceptor.requirePermission(...)`），
#: 在「按注解统计」的口径下**本条是实打实 +1** —— 已按本判据报错提示登记进既有台账
#: `test_agent_permission_parity.py::UNANNOTATED_ENDPOINTS`（逐条带理由 + 机械兜底
#: `ImageRecognitionInterpretControllerTest`），此处只把**读数上限**跟到现值。
#: 🔴 这是**显式放宽**（diff 里看得见）、不是放宽判定：超出上限照旧红；
#: 修法（让本判据认得命令式动态校验 ⇒ 这两个端点连同同类能一起从「无码」面里摘出去，
#: 上限随之退回 10 甚至更低）见 issue #6378；未落地前**不得再涨**。
#: 11 → 14（issue #6486 包 1，2026-10-07）：新增 `AgentScheduledTaskController` 的
#: `POST/GET/DELETE /api/admin/agent/scheduled-tasks` —— 米宝**定时提醒**的**自助**端点
#: （商家给自己建/查/取消待办；收件人取自认证上下文，读写都只碰自己的行）⇒ 与既有
#: `NotificationController` 的**自助**端点同款：**有意不加细粒度码**（加码等于把自助功能
#: 锁给持码角色），已按本判据的报错提示登记进既有台账
#: `test_agent_permission_parity.py::UNANNOTATED_ENDPOINTS`（逐条带理由）。
#: 🔴 与 #6367 同款的**显式放宽**（diff 里看得见）、不是放宽判定：超出上限照旧红。
#: 退回路径：这 3 条若能表达成注解式（例如引入「自助」语义码、或把自助面移出 `/api/admin/**`），
#: 读数应随之退回 11；在此之前**不得再涨**。
ADMIN_SCOPE_UNANNOTATED_CEILING = 14

# ══════════════════════════════════════════════════════════════════════════════
# 一、共用的静态归属机具（**不造第二套解析器**：issue #3570 的教训）
# ══════════════════════════════════════════════════════════════════════════════


def _load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    assert path.is_file(), f"被判据引用的机具不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ATTR = _load_module("migao_role_guard_attribution", ATTRIBUTION_PATH)
PARITY = _load_module("migao_role_guard_parity", PARITY_GUARD)


def _controller_sources() -> dict[str, str]:
    """`{相对 java 根路径: 源码}` —— 与 `_endpoint_index` / `_java_sources_from` **同一口径**。"""
    return {
        f"com/migao/admin/controller/{p.relative_to(CONTROLLER_DIR).as_posix()}": p.read_text(
            encoding="utf8"
        )
        for p in sorted(CONTROLLER_DIR.rglob("*.java"))
    }


def _index(java_sources: dict[str, str]):
    return ATTR.JavaEndpointIndex(java_sources=java_sources)


def _live_sources() -> dict[str, str]:
    """实盘源码（只读；本判据**不** fetch、不写任何文件）。"""
    srcs = _controller_sources()
    srcs["java:service/RegistrationService.java"] = REGISTRATION_SERVICE.read_text(encoding="utf8")
    srcs["java:service/PermissionService.java"] = PERMISSION_SERVICE.read_text(encoding="utf8")
    return srcs


def _ledger() -> dict:
    assert LEDGER_PATH.is_file(), f"台账不存在：{LEDGER_PATH}（路径漂移 ⇒ 红）"
    return json.loads(LEDGER_PATH.read_text(encoding="utf8"))


def _role_endpoints(index) -> dict[str, object]:
    """AdminRoleController 的端点表：`"VERB path" → JavaEndpoint`。"""
    out: dict[str, object] = {}
    for (verb, path), eps in sorted(index.endpoints().items()):
        for ep in eps:
            if ep.controller == ROLE_CONTROLLER_FILE:
                out[f"{verb} {path}"] = ep
    return out


def _control_admin_unannotated(index) -> int:
    """对照读数：`/api/admin/**` 面上「无任何生效码」的端点总数（只报告，不判对错）。"""
    return sum(
        1
        for eps in index.endpoints().values()
        for ep in eps
        if ep.permission is None and ep.path.startswith("/api/admin")
    )


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据主体（判据 1~5）
# ══════════════════════════════════════════════════════════════════════════════


def guard_problems(java_sources: dict[str, str], ledger: dict | None = None) -> list[str]:
    """全部问题（返回空 list = 绿）。注入式红证就是替换 `java_sources` / `ledger`。"""
    out: list[str] = []
    index = _index(java_sources)
    live = _role_endpoints(index)
    assert live, "AdminRoleController 一个端点都没解析出来 ⇒ 判据会空跑（fail-closed）"
    led = ledger if ledger is not None else _ledger()
    entries = led.get("entries", [])
    assert entries, "台账 `entries` 为空 ⇒ 判据会空跑（fail-closed）"
    by_key = {e["endpoint"]: e for e in entries}

    # 判据 1 + 2：controller 每个端点都必须登记；登记条目的码必须与现取一致
    for key in sorted(live):
        ep = live[key]
        entry = by_key.get(key)
        if entry is None:
            out.append(
                f"AdminRoleController 端点 `{key}` 未登记进 {LEDGER_PATH.name} —— "
                "新增端点必须显式登记它要哪把码（漏加注解 = 对全部商户员工开放，见 RBAC 分支 ③）"
            )
            continue
        decision = entry.get("decision")
        if decision == "exempt":
            out.append(
                f"端点 `{key}` 在台账里被声明为 `exempt`（有意不加码）—— "
                "issue #5980 落地后该面必须为空（只许缩短）：有意放行必须由代码里的其余机制承担，"
                "不得把注解摘回去"
            )
            continue
        if decision not in ("annotated",):
            out.append(f"端点 `{key}` 的台账 `decision` 非法（实测 `{decision!r}`）")
            continue
        if not ep.permission:
            out.append(
                f"端点 `{key}` 台账声明 `annotated`（码 = `{entry.get('effective_code')}`）"
                " 但**现取生效码为 None** —— 注解被删/被移走 ⇒ 该端点对所有商户员工开放"
            )
            continue
        if ep.permission != entry.get("effective_code"):
            out.append(
                f"端点 `{key}` 的生效码漂移：台账 `{entry.get('effective_code')}` ≠ 现取 `{ep.permission}`"
            )

    # 判据 2b：反向 —— 台账条目必须都能对应到现值（陈旧 / 幽灵登记 ⇒ 红）
    for key in sorted(by_key):
        ep = live.get(key)
        if ep is None:
            out.append(f"台账条目 `{key}` 已无对应端点（陈旧登记必须删除）")
            continue
        if ep.controller != by_key[key].get("controller"):
            out.append(
                f"台账条目 `{key}` 的 controller 与现取不一致："
                f"`{by_key[key].get('controller')}` ≠ `{ep.controller}`"
            )

    # 判据 3：端点级豁免台账（三条读码必须在场且逐值正确）
    for key, code in ROLE_READ_ENDPOINTS.items():
        ep = live.get(key)
        if ep is None:
            out.append(f"岗位目录读端点 `{key}` 在 controller 里已不存在（登记陈旧必须删除）")
            continue
        if ep.permission != code:
            out.append(f"岗位目录读端点 `{key}` 的生效码 ≠ `{code}`（实测 `{ep.permission}`）")

    # 判据 4：码必须在权限目录里
    catalog = set(PARITY.parse_catalog(
        java_sources["java:service/RegistrationService.java"],
        java_sources["java:service/PermissionService.java"],
    )[0])
    assert catalog, "权限目录解析为空 ⇒ 判据会空跑（fail-closed）"
    for key in sorted(live):
        code = live[key].permission
        if code and code not in catalog:
            out.append(f"端点 `{key}` 的生效码 `{code}` 不在权限目录里（拼错 ⇒ 该端点对所有角色恒 403）")

    # 判据 5：对照读数只许缩短（不达上限不红；超上限 ⇒ 红 —— 「沉默放行」的存量不许增长）
    live_unannotated = _control_admin_unannotated(index)
    if live_unannotated > ADMIN_SCOPE_UNANNOTATED_CEILING:
        out.append(
            f"`/api/admin/**` 无码端点现取 {live_unannotated} > 上限 {ADMIN_SCOPE_UNANNOTATED_CEILING}"
            " —— 新增的沉默放行必须登记进既有台账（判据 8 的 `UNANNOTATED_ENDPOINTS`）而不是涨这个数"
        )
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据
# ══════════════════════════════════════════════════════════════════════════════


class TestAdminRoleReadSurface:
    def test_role_endpoints_are_annotated_and_registered(self):
        """判据 1~5：admin 侧岗位目录端点的注解面 + 台账双向对账。"""
        problems = guard_problems(_live_sources())
        assert not problems, "岗位目录读端点守卫判红：\n" + "\n".join(f"  - {p}" for p in problems)

    def test_ledger_records_the_control_reading(self):
        """台账里的对照读数必须与现取一致（否则「报告型读数」会静默陈旧）。"""
        ledger = _ledger()
        live = _control_admin_unannotated(_index(_live_sources()))
        assert ledger.get("admin_scope_unannotated_count") == live, (
            f"台账对照读数 {ledger.get('admin_scope_unannotated_count')} ≠ 现取 {live}"
            "（存量只许缩短；缩短后请把台账读数调低）"
        )
        assert live <= ADMIN_SCOPE_UNANNOTATED_CEILING

    def test_role_endpoint_codes_are_in_the_catalog(self):
        """判据 4 的正向对照：三条读码逐条在权限目录里（码名拼错 ⇒ 恒 403）。"""
        srcs = _live_sources()
        catalog = set(PARITY.parse_catalog(
            srcs["java:service/RegistrationService.java"],
            srcs["java:service/PermissionService.java"],
        )[0])
        for key, code in ROLE_READ_ENDPOINTS.items():
            assert code in catalog, f"`{key}` 要求的 `{code}` 不在权限目录里"


# ══════════════════════════════════════════════════════════════════════════════
# 四、判别力自证（内存注入；红证只在内存副本上跑，不动仓内文件）
# ══════════════════════════════════════════════════════════════════════════════


def _mutate(srcs: dict[str, str], key: str, old: str, new: str, times: int = 1) -> dict[str, str]:
    out = dict(srcs)
    assert out[key].count(old) >= times, f"注入点不存在：{key} / {old!r}（注入必须先自证生效）"
    out[key] = out[key].replace(old, new, times)
    return out


def _add_endpoint(srcs: dict[str, str], marker: str, block: str) -> dict[str, str]:
    out = dict(srcs)
    assert marker in out[ROLE_CONTROLLER_FILE]
    out[ROLE_CONTROLLER_FILE] = out[ROLE_CONTROLLER_FILE].replace(marker, block + marker, 1)
    return out


class TestGuardDiscriminates:
    def test_unannotated_new_endpoint_is_red(self):
        """坏形态 ①：新增一个**读**端点却忘了加注解（本单要治的形态）。"""
        srcs = _add_endpoint(
            _live_sources(),
            "    /**\n     * 创建角色",
            '    @GetMapping("/draft-preview")\n    public ApiResponse<List<Role>> draftPreview() {\n'
            "        return ApiResponse.success(List.of());\n    }\n\n",
        )
        problems = guard_problems(srcs)
        assert any("draft-preview" in p and "未登记" in p for p in problems), problems

    def test_removing_an_annotation_is_red(self):
        """坏形态 ②：把已落地的注解删掉（回退到 issue #5980 修前形态）。"""
        key = "com/migao/admin/controller/AdminRoleController.java"
        srcs = _mutate(
            _live_sources(),
            key,
            '    @GetMapping("/all")\n    @RequirePermission("employee:list")',
            '    @GetMapping("/all")',
        )
        problems = guard_problems(srcs)
        assert any("/api/admin/roles/all" in p and "生效码为 None" in p for p in problems), problems

    def test_stale_ledger_entry_is_red(self):
        """坏形态 ③：台账多出一条现取不存在的端点（陈旧 / 幽灵登记）。"""
        ledger = _ledger()
        ledger["entries"] = ledger["entries"] + [
            {"endpoint": "GET /api/admin/roles/ghost", "controller": ROLE_CONTROLLER_FILE,
             "decision": "annotated", "effective_code": "system:view"}
        ]
        problems = guard_problems(_live_sources(), ledger)
        assert any("已无对应端点" in p and "ghost" in p for p in problems), problems

    def test_code_typo_is_red(self):
        """坏形态 ④：注解里的码拼错（对所有人恒 403；静态面只看得见「不在目录里」）。"""
        srcs = _mutate(
            _live_sources(),
            "com/migao/admin/controller/AdminRoleController.java",
            '@RequirePermission("employee:list")',
            '@RequirePermission("employee:lst")',
        )
        problems = guard_problems(srcs)
        assert any("employee:lst" in p for p in problems), problems

    def test_readding_exempt_is_red(self):
        """坏形态 ⑤：把端点重新标成 `exempt`（有意放行面只许缩短）。"""
        ledger = _ledger()
        for e in ledger["entries"]:
            if e["endpoint"] == "GET /api/admin/roles/all":
                e["decision"] = "exempt"
                e["effective_code"] = None
        problems = guard_problems(_live_sources(), ledger)
        assert any("exempt" in p for p in problems), problems

    def test_comment_only_change_does_not_fire(self):
        """对照读数：只改散文（注释）⇒ 不红（守卫不被自己的文案喂红）。"""
        srcs = _mutate(
            _live_sources(),
            "com/migao/admin/controller/AdminRoleController.java",
            "// issue #5246（审计裁定「该放行」）",
            "// issue #5980 收紧注记（本行**只是注释**；改它不得让守卫变红）",
        )
        assert guard_problems(srcs) == []
