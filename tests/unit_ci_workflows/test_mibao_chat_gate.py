# case_ids: BM-008
"""米宝唤出授权门的**机械判据**（issue #5642 功能⑤）。

## 用户裁定（本守卫的唯一理由，2026-09-26）

> 「管理员可以在 H5 上唤出 migao Agent 进行对话，**其他员工需要授权**才能唤出 migao Agent」

## 为什么必须有机械判据（病根）

「谁能唤出米宝」改动前**没有任何权限码在管**（`backend/ai-agent-service/app/api/chat.py` 的
`/api/chat/send` 无端点级码；`frontend/bmini-app/src/pages/chat/**` 零权限门）⇒ 本单新增码
`agent:chat` 并给出**一处**判定（`AdminGate`）。若把这个集合抄到第二处（第二个 Java 常量、
前端硬编码、第二份文档式约定），「改一处而另一端不同步」**不会有任何东西变红**
—— 同族反面教材：issue #4393 的 `craft-display` 三份副本无同步守卫。

## 三条机械判据（设计单 §2.4 / §3.3，逐条能红）

| # | 判据 | 红证形态 |
|---|---|---|
| ① **单一常量** | 全仓**代码面**语料里，三码的**字面量相邻出现**次数 == 1，且那唯一一处在 `AdminGate.java` | 在第二个文件里再抄一遍三码数组 ⇒ 计数变 2 ⇒ 红 |
| ② **前端零副本** | `frontend/bmini-app/src/**` 与 `frontend/admin-web/src/**` 的**任一文件**里，三码的**不同成员数 ≤ 1**（前端只消费服务端下发的 `capabilities.mibaoChat` 布尔位，不自己判码） | 在前端写 `hasPermission('a') && hasPermission('b')`（a/b 为三码中两个）⇒ 红 |
| ③ **码必须真在目录里** | 集合每个成员 ∈ `RegistrationService.defaultPermissions` 的码集 **∧** ∈ `PermissionService.ensureFullPermissionCatalog` 的码集 **∧** ∈ 迁移链落库 | 写一个目录里没有的码（**本单开工前的现状**就是 `agent:chat` 全仓 0 命中）⇒ 红 |

## 另三条（同一交付物的其它面，同样能红）

| # | 判据 | 红证形态 |
|---|---|---|
| ④ **迁移面**：`agent:chat` 的存量回填**只授 `admin`**（裁定⑧）+ 幂等 + 终态对账 `DO` 块 + 头部回滚 SQL | 多授一个岗位 / 去掉 `DO` 块 ⇒ 红 |
| ⑤ **服务端接线**：`AdminGate` 是唯一判定；`/api/auth/me`（`AuthService.getCurrentUser`）经**同一函数**下发能力位 | 判定改成读 `role` 字段 / 能力位恒 `true` ⇒ 红 |
| ⑥ **端侧消费**：两端都读服务端 `capabilities.mibaoChat`，且未授权态含**逐字**「需要管理员授权」+ 可行动引导（不是静默隐藏、不是 403 白屏） | 改成前端硬编码码 / 删掉引导文案 ⇒ 红 |
| ⑦ **防空跑**：语料完整 + 判据自身不在语料内 | 语料塌陷 ⇒ 红 |
| ⑧ **E2E 管理员身份 mock 保真度**：`tests/e2e/**` 里 `roles: ['admin']`（**字符串字面量**数组）的**身份**对象必须带 `capabilities.mibaoChat` | 删掉该位 ⇒ 红（**这正是本包 CI 的真实红**，见下） |

## 🔴 判据 ⑧ 的来历（**本包 CI 实测的真红，逐字登记**）

本包首轮 CI 的 job「Demo path specs (admin-web, fixture mode)」**红**：
`tests/e2e/specs/chat/chat-panel-resize.spec.ts` **7 failed**（`7 failed / 3 skipped / 50 passed`）。

**归因 = fixture 保真度，不是授权门**：`tests/e2e/fixtures.ts` 的 mock 身份写 `roles: ['admin']`
但**没有** `capabilities`（该字段是本包才引入的）⇒ 授权门读到 `undefined` ⇒
**整个对话面板不渲染** ⇒ 几何断言全红。而真实 `/api/auth/me` 对 `roles: ['admin']`
（权限恒为 `["*"]`）**就下发** `mibaoChat: true` ⇒ **mock 落后于真实契约**。

⇒ **修法 = 给身份 mock 补能力位**（**不是**放宽门、**不是**让未授权也渲染面板）。
判据 ⑧ 把这一**类**钉住：以后任何人新增一个「管理员身份 mock」而忘了能力位 ⇒ **当场红**，
不必等到某个 E2E 在几何断言上以「找不到面板」的形式报警（那种报警指向错误的方向）。

## 明确的边界（**不要**把本守卫读成覆盖面更大）

- **语料 = 代码面**（`.java` / `.py` / `.ts` / `.tsx` / `.js` / `.mjs` / `.sql` / `.sh` / `.yml` / `.yaml`）。
  `.md`（设计单 / CHANGELOG）**不在语料内** —— 文档天然要**引用**这个集合，而
  「任何内容扫描式机制都分不清『引用』与『使用』」（`migao-dev-flow` §2.2 的同族教训）
  ⇒ 判据要钉的是「**代码里**只有一处常量」。这是**口径声明**，不是给判据开后门。
- **判据自身不在语料内**（`SELF` 显式排除）—— 防 B1「判据被自己计数」。
- **判据 ① 的「剥注释」只覆盖 `.java`**：仓库的剥注释唯一实现是 `_source_parsing.java_code`（Java）
  与 `.github/danger_scan.py::strip_comment`（YAML / shell 行内注释），**没有**覆盖
  `.ts` / `.py` / `.sql` 的通用实现 ⇒ 那几类按**原文**扫描。残留：在这些语言的**注释里**写出三码相邻
  ⇒ 本判据**偏严**（多报一次），方向与门禁 fail-closed 一致（多看一眼 vs. 漏检），且**不是**假绿。
  ⚠️ 这与「判据被自己的文案喂红」同族（§23.4 T2）—— 本判据**自身**已被排除，故不受影响。
- **判据 ② 的口径是「每文件不同成员数 ≤ 1」而非「全前端不得出现任何一个」**：实测存量里  `frontend/admin-web/src/app/(dashboard)/layout.tsx` 与 `frontend/admin-web/src/config/menu.ts`
  合法地各持**一个**成员（路由门 / 菜单节点码，是**既有**页面权限面，不是本单的判定）
  ⇒ 口径取「不得**共现**」（任意两个落入同一文件 = 有人开始自己判管理员），
  否则本判据在存量上就恒红（那会让它变成「为过判据而改存量」）。
- **`agent:chat` 不是菜单项**：本单**不新增菜单节点**、**不动** `agent:session` 承载的
  「在线接待」入口 ⇒ 判据③只要求它 ∈ 目录，不要求它有菜单/工具落点
  （它是 `pages/chat` 的**访问门**，不是「能调哪些工具」）。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()

# append（**不是** insert）：只作脚本模式的兜底解析路径，避免遮蔽同名模块（与 conftest / 同目录既有守卫同款理由）。
sys.path.append(str(REPO / "tests"))

from unit_ci_workflows._source_parsing import (  # noqa: E402
    java_code,
    java_literals,
)

ADMIN_GATE = "backend/admin-api/src/main/java/com/migao/admin/security/AdminGate.java"
REGISTRATION_SERVICE = "backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java"
PERMISSION_SERVICE = "backend/admin-api/src/main/java/com/migao/admin/service/PermissionService.java"
USER_INFO_RESPONSE = "backend/admin-api/src/main/java/com/migao/admin/dto/UserInfoResponse.java"
AUTH_SERVICE = "backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java"
MIGRATIONS_DIR = "backend/admin-api/src/main/resources/db/migration"

BMINI_GATE = "frontend/bmini-app/src/components/chat/MibaoAccessGate.tsx"
BMINI_PAGE = "frontend/bmini-app/src/pages/chat/index/index.tsx"
WEB_GATE = "frontend/admin-web/src/components/business/MibaoAccessGate.tsx"
WEB_PAGE = "frontend/admin-web/src/app/(dashboard)/chat/page.tsx"

FRONTEND_ROOTS = ("frontend/bmini-app/src/", "frontend/admin-web/src/")

#: 面向前端的**逐字**文案（判据 G3；改字即红）。
NEEDS_GRANT_TEXT = "需要管理员授权"

#: 可行动引导里的关键锚（去哪授权 / 找谁）。
GRANT_GUIDE_ANCHOR = "员工管理"

#: 端侧两个**导出常量**（判据 G3 的锚点）。
#: 🔴 口径 = 「锚在常量定义上」而不是「文件里出现过这个串」：后者会被**注释 / docstring 里的
#: 引用**满足 —— 那是「引用即实例」的同族假绿（本仓已多次实证，见 `migao-dev-flow` §2.2）。
GRANT_TEXT_RE = re.compile(r"MIBAO_NEEDS_ADMIN_GRANT_TEXT\s*=\s*'([^']+)'")
GRANT_GUIDE_RE = re.compile(r"MIBAO_GRANT_GUIDE_TEXT\s*=\s*'([^']+)'")

#: 语料扩展名（**代码面**；`.md` 显式不在内，理由见模块 docstring 的边界节）。
CODE_EXTS = (".java", ".py", ".ts", ".tsx", ".js", ".mjs", ".sql", ".sh", ".yml", ".yaml")

#: 遍历剪枝（第三方 / 构建产物 / 缓存）。
EXCLUDE_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "site-packages", ".next", "dist", "build",
    "coverage", "__pycache__", ".pytest_cache", ".mypy_cache", ".turbo", "out",
})

#: 目录行（与 `tests/unit_ci_workflows/test_agent_permission_parity.py` 同源正则：取第 2 列的码）。
CATALOG_ROW_RE = re.compile(
    r'\{\s*"[^"]*",\s*"([^"]+)",\s*"[^"]*",\s*"[^"]*",\s*"[^"]*"\s*\}'
)

#: `AdminGate.ADMIN_PERMISSION_CODES = Set.of("a", "b", "c")`
ADMIN_CODES_RE = re.compile(
    r"ADMIN_PERMISSION_CODES\s*=\s*\n?\s*Set\.of\(([^)]*)\)"
)

#: 「字面量相邻」= 三个码按序出现，两两之间只隔引号 / 逗号 / 花括号 / 空白。
_ADJACENCY_SEP = r"""["'`\s,\{\}\[\]]*"""

#: E2E 面（判据 ⑧：身份 mock 的保真度）。
E2E_ROOT = "tests/e2e/"
E2E_FIXTURES = "tests/e2e/fixtures.ts"

#: **身份**里的管理员角色 —— 数组元素必须是**字符串字面量** `'admin'`。
#: ⚠️ 必须与「角色对象列表」区分开：`roles: [{ code: 'admin', name: '管理员' }]` 是
#: **员工列表行**的 DTO（不是调用者身份）⇒ 不得要求它带能力位。
#: 本判据开发时实测误伤过一次（脚本把能力位插进了 `/api/admin/users*` 的行 DTO），故收紧正则。
E2E_ADMIN_IDENTITY_RE = re.compile(
    r"roles\s*:\s*\[\s*['\"]admin['\"]\s*(?:,\s*['\"][^'\"]*['\"]\s*)*\]"
)


# ══════════════════════════════════════════════════════════════════════════════
# 一、语料
# ══════════════════════════════════════════════════════════════════════════════


def load_corpus(root: Path = REPO) -> dict[str, str]:
    """代码面语料（相对路径 → 文本）。剪枝 `EXCLUDE_DIRS`；**排除判据自身**（防 B1）。"""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            if not name.endswith(CODE_EXTS):
                continue
            path = Path(dirpath) / name
            if path.resolve() == SELF:
                continue
            try:
                out[path.relative_to(root).as_posix()] = path.read_text(encoding="utf8")
            except (UnicodeDecodeError, OSError):
                continue
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 二、解析
# ══════════════════════════════════════════════════════════════════════════════


def parse_admin_codes(gate_text: str) -> tuple[str, ...]:
    """`AdminGate.ADMIN_PERMISSION_CODES` 的成员（**判据的唯一取值口**，不写第二份字面量）。

    🔴 **先剥注释、再按词法取字面量** —— 两件都由**仓库唯一实现**做：
    `unit_ci_workflows._source_parsing` 的 `java_code`（引号感知的 Java 剥注释）与 `java_literals`
    （词法扫描，注释 / 字符串里的假声明不会被读成声明）。**不自写「按引号扫原文」的口径**：
    那种写法会被注释喂中，且被 `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py`
    的 RULE_QUOTE 判红（本判据首版就是这么被抓住的 —— 台账**只许缩短**，正确修法是改用共享实现）。
    """
    code = java_code(gate_text)
    m = ADMIN_CODES_RE.search(code)
    assert m, "`AdminGate.ADMIN_PERMISSION_CODES = Set.of(...)` 解析失配 ⇒ 判据会空跑（fail-closed）"
    codes = tuple(value for _pos, value in java_literals(m.group(1)))
    assert len(codes) == 3, (
        f"管理员权限码集合应解析出 3 个成员（裁定④逐字），实得 {len(codes)}：{codes}"
        " ⇒ 判据会空跑，同步本文件（fail-closed）"
    )
    return codes


def parse_catalog(text: str) -> frozenset[str]:
    """权限目录（`String[][]`）的**码列**。"""
    return frozenset(CATALOG_ROW_RE.findall(text))


def parse_migrations(corpus: dict[str, str]) -> dict[str, str]:
    """迁移链（文件名 → 文本），按**文件名**排序（`MigrationRunner` 的判已应用口径）。"""
    return {
        rel: text
        for rel, text in sorted(corpus.items())
        if rel.startswith(MIGRATIONS_DIR + "/") and rel.endswith(".sql")
    }


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据（纯函数：输入语料 ⇒ 问题清单，空列表 = 绿）
# ══════════════════════════════════════════════════════════════════════════════


def _scan_text(rel: str, text: str) -> str:
    """判据 ① 的扫描面：**先剥注释**（共享实现 `java_code`），再找字面量。

    ⚠️ **边界（照实登记）**：只对 `.java` 剥注释 —— 仓库的「剥注释唯一实现」是
    `_source_parsing.java_code`（Java）与 `.github/danger_scan.py::strip_comment`（YAML/shell 行内注释），
    **没有**覆盖 `.ts` / `.py` / `.sql` 的通用实现。⇒ 那几类仍按**原文**扫描：
    在这些语言的**注释里**写出三码相邻，本判据会**偏严**（多报一次），
    方向与门禁 fail-closed 一致（多看一眼 vs. 漏检）；该残留已登记进模块 docstring 的边界节。
    """
    return java_code(text) if rel.endswith(".java") else text


def problems_single_constant(corpus: dict[str, str]) -> list[str]:
    """判据 ①：全仓代码面里，三码的**字面量相邻出现**次数 == 1（且唯一那处是 `AdminGate.java`）。"""
    gate = corpus.get(ADMIN_GATE)
    if gate is None:
        return [f"`{ADMIN_GATE}` 不在语料内（路径漂移 ⇒ 判据空跑，不得静默跳过）"]
    codes = parse_admin_codes(gate)
    pattern = re.compile(_ADJACENCY_SEP.join(re.escape(c) for c in codes))
    hits = [
        rel for rel, text in sorted(corpus.items())
        for _ in pattern.finditer(_scan_text(rel, text))
    ]
    out: list[str] = []
    if len(hits) != 1:
        out.append(
            f"三码的**字面量相邻出现**共 {len(hits)} 处（应为 1）：{hits} —— "
            "集合只许有**一处**字面量（第二处 = 「改一处而另一端不同步」再也不会变红）"
        )
    elif hits[0] != ADMIN_GATE:
        out.append(f"三码字面量的唯一一处不在 `{ADMIN_GATE}` 而在 `{hits[0]}`（真值坐标漂移）")
    return out


def problems_frontend_copy(corpus: dict[str, str]) -> list[str]:
    """判据 ②：前端 `src/**` 任一文件里，三码的**不同成员数 ≤ 1**（不得共现）。"""
    gate = corpus.get(ADMIN_GATE)
    if gate is None:
        return [f"`{ADMIN_GATE}` 不在语料内（路径漂移 ⇒ 判据空跑，不得静默跳过）"]
    codes = parse_admin_codes(gate)
    out: list[str] = []
    for rel, text in sorted(corpus.items()):
        if not rel.startswith(FRONTEND_ROOTS):
            continue
        present = sorted(c for c in codes if c in text)
        if len(present) > 1:
            out.append(
                f"`{rel}` 同时出现 {len(present)} 个管理员集合成员 —— 前端**不得**自己判码，"
                "只消费服务端下发的 `capabilities.mibaoChat`"
            )
    return out


def problems_codes_in_catalog(corpus: dict[str, str]) -> list[str]:
    """判据 ③：集合每个成员 ∈ 两处目录 ∧ ∈ 迁移链落库（与既有判据 9「两处目录逐值相等」同源）。"""
    gate = corpus.get(ADMIN_GATE)
    reg = corpus.get(REGISTRATION_SERVICE)
    perm = corpus.get(PERMISSION_SERVICE)
    missing_sources = [
        rel for rel, text in (
            (ADMIN_GATE, gate), (REGISTRATION_SERVICE, reg), (PERMISSION_SERVICE, perm),
        ) if text is None
    ]
    if missing_sources:
        return [f"判据输入缺失（路径漂移 ⇒ 判据空跑）：{missing_sources}"]

    codes = parse_admin_codes(gate)
    reg_codes = parse_catalog(reg)
    perm_codes = parse_catalog(perm)
    assert reg_codes and perm_codes, "权限目录解析出 0 条 ⇒ 判据会空跑（fail-closed）"

    out: list[str] = []
    if reg_codes != perm_codes:
        out.append(
            "权限目录两处不同步（`RegistrationService` vs `PermissionService`）："
            f"差集 {sorted(reg_codes ^ perm_codes)}"
        )
    for code in codes:
        if code not in reg_codes:
            out.append(f"管理员集合成员 `{code}` 不在 `RegistrationService.defaultPermissions` 的目录里")
        if code not in perm_codes:
            out.append(f"管理员集合成员 `{code}` 不在 `PermissionService.ensureFullPermissionCatalog` 的目录里")

    # 「∈ 迁移链落库」只对**本单新增的那个成员**成立（= 授权码）：另外两个是**既有码**，
    # 它们靠建租户时的 seed 落到每个租户里，本仓**从来没有**也不需要为它们写回填迁移
    # （设计单 §3.1 末逐字登记过这件事：`employee:create` 的种子只在 Java 里）。
    # 而新增码不落迁移 ⇒ **存量租户永远拿不到它**（`ensureFullPermissionCatalog` 只在角色
    # 管理页被懒调用，`role_permissions` 更是没有任何 Java 路径会给既有岗位补）。
    gate_text = corpus[ADMIN_GATE]
    grant = re.search(r'MIBAO_CHAT_GRANT_CODE\s*=\s*"([^"]+)"', gate_text)
    assert grant, "`AdminGate.MIBAO_CHAT_GRANT_CODE` 解析失配（fail-closed）"
    grant_code = grant.group(1)
    migrations = parse_migrations(corpus)
    landed = sorted(
        rel for rel, text in migrations.items()
        if re.search(r"INSERT\s+INTO\s+permissions\b", text, re.I) and f"'{grant_code}'" in text
    )
    if not landed:
        out.append(
            f"新增的授权码 `{grant_code}` 从未被任何迁移落库 ⇒ 存量租户永远拿不到它"
            f"（迁移链共 {len(migrations)} 条；种子之外的码必须自己带一条回填）"
        )
    return out


def problems_migration_shape(corpus: dict[str, str]) -> list[str]:
    """判据 ④：`agent:chat` 的存量回填**只授 `admin`**（裁定⑧）+ 幂等 + 终态对账 + 回滚 SQL。"""
    gate = corpus.get(ADMIN_GATE)
    if gate is None:
        return [f"`{ADMIN_GATE}` 不在语料内（路径漂移 ⇒ 判据空跑，不得静默跳过）"]
    grant_code = re.search(r'MIBAO_CHAT_GRANT_CODE\s*=\s*"([^"]+)"', gate)
    assert grant_code, "`AdminGate.MIBAO_CHAT_GRANT_CODE` 解析失配（fail-closed）"
    code = grant_code.group(1)

    migrations = {
        rel: text for rel, text in parse_migrations(corpus).items() if f"'{code}'" in text
    }
    out: list[str] = []
    if len(migrations) != 1:
        out.append(
            f"含 `{code}` 落库的迁移应恰有 1 条（迁移只增不改），实得 {len(migrations)}："
            f"{sorted(migrations)}"
        )
        return out

    rel, text = next(iter(migrations.items()))
    if not re.search(r"r\.code\s*=\s*'admin'", text):
        out.append(f"`{rel}` 没有把回填**限定到 `admin` 角色**（裁定⑧：只回填 admin）")
    if re.search(r"r\.code\s*=\s*'(customer_service|operator|sales|finance|product_manager)'", text):
        out.append(f"`{rel}` 把 `{code}` 回填给了非 admin 岗位（违反裁定⑧「只回填 admin」）")
    if "ON CONFLICT" not in text:
        out.append(f"`{rel}` 缺 `ON CONFLICT ... DO NOTHING` ⇒ 不幂等（`MigrationRunner` 要求可重复执行）")
    if "WHERE NOT EXISTS" not in text:
        out.append(f"`{rel}` 缺 `WHERE NOT EXISTS` ⇒ 不幂等")
    if not re.search(r"DO\s*\$\$", text):
        out.append(f"`{rel}` 缺终态对账 `DO $$` 块 ⇒ 判据漂移时不会 fail-closed")
    if "RAISE EXCEPTION" not in text:
        out.append(f"`{rel}` 的终态对账没有 `RAISE EXCEPTION` ⇒ 对账失败不会回滚")
    if "回滚 SQL" not in text:
        out.append(f"`{rel}` 头部缺**回滚 SQL** 登记（本仓迁移无 down 机制，回滚必须写在注释里）")
    return out


def problems_server_wiring(corpus: dict[str, str]) -> list[str]:
    """判据 ⑤：唯一判定 = `AdminGate`，且 `/api/auth/me` 经**同一函数**下发能力位。"""
    out: list[str] = []
    gate = corpus.get(ADMIN_GATE)
    dto = corpus.get(USER_INFO_RESPONSE)
    auth = corpus.get(AUTH_SERVICE)
    missing = [
        rel for rel, text in (
            (ADMIN_GATE, gate), (USER_INFO_RESPONSE, dto), (AUTH_SERVICE, auth),
        ) if text is None
    ]
    if missing:
        return [f"判据输入缺失（路径漂移 ⇒ 判据空跑）：{missing}"]

    if not re.search(r'contains\("\*"\)', gate):
        out.append("`AdminGate` 没有 `\"*\"` 通配**直接判真**的分支 ⇒ role='admin' 不会自动落入（既有行为回归）")
    if "containsAll(ADMIN_PERMISSION_CODES)" not in gate:
        out.append("`AdminGate` 的判定不是 `containsAll(ADMIN_PERMISSION_CODES)` ⇒ 集合不再是「全持」语义")
    if not re.search(r"\bcanSummonMibao\s*\(", gate):
        out.append("`AdminGate` 没有对外暴露米宝唤出判定（`canSummonMibao`）")
    # 能力位必须**由这一处**算出，且出现在两个 return 分支（平台超管 / 商户管理员）
    calls = len(re.findall(r"capabilities\(capabilitiesOf\(permissions\)\)", auth))
    if calls != 2:
        out.append(f"`AuthService.getCurrentUser` 经 `capabilitiesOf(permissions)` 下发能力位的分支数为 {calls}（应为 2：平台超管 + 商户管理员）")
    if "AdminGate.canSummonMibao(permissions)" not in auth:
        out.append("`AuthService` 的能力位不是调 `AdminGate.canSummonMibao`（第二处判定 = 双真相源）")
    if "capabilities" not in dto or "mibaoChat" not in dto:
        out.append("`UserInfoResponse` 缺 `capabilities.mibaoChat`（端侧没有可用来源 ⇒ 门只能自己判码）")
    return out


def problems_frontend_consumption(corpus: dict[str, str]) -> list[str]:
    """判据 ⑥：两端都读服务端能力位，且未授权态含逐字文案 + 可行动引导（非静默隐藏 / 非 403）。"""
    out: list[str] = []
    for rel, needle in ((BMINI_PAGE, "capabilities?.mibaoChat"), (WEB_PAGE, "capabilities?.mibaoChat")):
        text = corpus.get(rel)
        if text is None:
            out.append(f"`{rel}` 不在语料内（路径漂移 ⇒ 判据空跑，不得静默跳过）")
            continue
        if needle not in text:
            out.append(f"`{rel}` 没有消费服务端下发的 `{needle}`（端侧判定来源不是单一真值）")
        if "MibaoAccessGate" not in text:
            out.append(f"`{rel}` 没有挂米宝唤出授权门（未授权者会直接进对话）")

    for rel in (BMINI_GATE, WEB_GATE):
        text = corpus.get(rel)
        if text is None:
            out.append(f"`{rel}` 不在语料内（授权门的端侧载体缺失）")
            continue
        grant = GRANT_TEXT_RE.search(text)
        if grant is None:
            out.append(f"`{rel}` 缺导出的逐字文案常量 `MIBAO_NEEDS_ADMIN_GRANT_TEXT`（判据 G3 的锚点）")
        elif grant.group(1) != NEEDS_GRANT_TEXT:
            out.append(
                f"`{rel}` 的文案常量是「{grant.group(1)}」而不是**逐字**「{NEEDS_GRANT_TEXT}」（判据 G3）"
            )
        guide = GRANT_GUIDE_RE.search(text)
        if guide is None:
            out.append(f"`{rel}` 缺导出的可行动引导常量 `MIBAO_GRANT_GUIDE_TEXT`")
        elif GRANT_GUIDE_ANCHOR not in guide.group(1):
            out.append(
                f"`{rel}` 的引导文案里没有「{GRANT_GUIDE_ANCHOR}」⇒ 用户不知道去哪授权"
                "（只给「无权限」不算可行动引导）"
            )
        if "mibao-gate-denied" not in text:
            out.append(f"`{rel}` 缺拒绝态的稳定测试锚点（`data-testid=\"mibao-gate-denied\"`）⇒ 判据无法断言「入口可见」")
    return out


def _enclosing_object(text: str, idx: int) -> str | None:
    """`idx` 之前最近的 `{` 起做括号配平 ⇒ 返回该对象字面量（配平失败 ⇒ `None`）。"""
    start = text.rfind("{", 0, idx)
    if start == -1:
        return None
    depth = 0
    for j in range(start, len(text)):
        char = text[j]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    return None


def problems_e2e_identity_fidelity(corpus: dict[str, str]) -> list[str]:
    """判据 ⑧：E2E 里**管理员身份**的 mock 必须与真实 `/api/auth/me` 同形（带能力位）。

    病根（本包 CI 实测，**真红**）：`tests/e2e/fixtures.ts` 的 mock 身份写 `roles: ['admin']`
    但**没有** `capabilities` ⇒ 授权门读到 `undefined` ⇒ **整个对话面板不渲染** ⇒
    `tests/e2e/specs/chat/chat-panel-resize.spec.ts` 7 条几何断言全红（job「Demo path specs」）。

    🔴 那是 **fixture 保真度**问题、**不是**授权门的问题：真实 `/api/auth/me` 对
    `roles: ['admin']`（权限恒为 `["*"]`）**就下发** `mibaoChat: true`（见判据 ⑤）。
    fixture 是**手写 stub**，身份字段是它的**副本** ⇒ 服务端契约一变，它就静默漂移
    （同族：`craft-display` 三份副本无守卫）。⇒ 本判据把这一类**钉在机械面上**：
    管理员身份 mock 少能力位 ⇒ 红。
    """
    out: list[str] = []
    hits = 0
    for rel, text in sorted(corpus.items()):
        if not rel.startswith(E2E_ROOT):
            continue
        for m in E2E_ADMIN_IDENTITY_RE.finditer(text):
            hits += 1
            obj = _enclosing_object(text, m.start())
            if obj is None:
                out.append(f"`{rel}`：`roles: ['admin']` 的宿主对象解析失败 ⇒ 判据会空跑（fail-closed）")
                continue
            if "capabilities" not in obj or "mibaoChat" not in obj:
                out.append(
                    f"`{rel}`：管理员身份的 mock 缺 `capabilities.mibaoChat` ⇒ "
                    "端侧读到 `undefined` ⇒ 授权门落「需要管理员授权」态（E2E 里表现为页面无面板）"
                )
    if hits == 0:
        out.append("`tests/e2e/**` 里一个管理员身份 mock 都没解析出来 ⇒ 判据会空跑（fail-closed）")
    return out


def problems_self_check(corpus: dict[str, str]) -> list[str]:
    """判据 ⑦：防空跑（语料非空 + 关键对象都在语料内 + 判据自身不在语料内）。"""
    out: list[str] = []
    if len(corpus) < 200:
        out.append(f"代码面语料只解析出 {len(corpus)} 个文件 ⇒ 语料塌了（判据会空跑）")
    for rel in (
        ADMIN_GATE, REGISTRATION_SERVICE, PERMISSION_SERVICE, USER_INFO_RESPONSE,
        AUTH_SERVICE, BMINI_GATE, BMINI_PAGE, WEB_GATE, WEB_PAGE, E2E_FIXTURES,
    ):
        if rel not in corpus:
            out.append(f"关键对象 `{rel}` 不在语料内（判据会空跑）")
    if not parse_migrations(corpus):
        out.append("迁移链解析出 0 条 ⇒ 判据 ③/④ 会空跑")
    if SELF.relative_to(REPO).as_posix() in corpus:
        out.append("判据自身出现在语料内 ⇒ 会被自己计数（B1：注入的探针被自身命中，红证变空断言）")
    return out


#: 判据表（`test_every_judgement_can_go_red` 要求**每条都有注入**，一一对应）。
JUDGEMENTS: dict[str, "callable"] = {
    "① 单一常量（三码字面量相邻出现 == 1）": problems_single_constant,
    "② 前端零副本（每文件不同成员数 ≤ 1）": problems_frontend_copy,
    "③ 码必须真在目录里（两处目录 ∧ 迁移链）": problems_codes_in_catalog,
    "④ 迁移面（只授 admin + 幂等 + 终态对账 + 回滚 SQL）": problems_migration_shape,
    "⑤ 服务端接线（唯一判定 ⇒ 能力位）": problems_server_wiring,
    "⑥ 端侧消费（能力位 + 逐字文案 + 可行动引导）": problems_frontend_consumption,
    "⑦ 防空跑（语料完整 + 判据自身不在语料内）": problems_self_check,
    "⑧ E2E 管理员身份 mock 保真度（必须带能力位）": problems_e2e_identity_fidelity,
}


# ══════════════════════════════════════════════════════════════════════════════
# 四、注入式红证（**每条判据都要有能单独变红的负向夹具**）
# ══════════════════════════════════════════════════════════════════════════════


def _inject_second_constant(corpus: dict[str, str]) -> dict[str, str]:
    """① 在第二个文件里再抄一遍三码数组（真实的「第二份真值」形态）。"""
    codes = parse_admin_codes(corpus[ADMIN_GATE])
    body = ", ".join(f'"{c}"' for c in codes)
    return {
        **corpus,
        BMINI_PAGE: corpus[BMINI_PAGE] + f"\nconst LEGACY_ADMIN_CODES = [{body}]\n",
    }


def _inject_frontend_gate_by_code(corpus: dict[str, str]) -> dict[str, str]:
    """② 前端开始**自己判码**（`hasPermission('a') && hasPermission('b')`）。"""
    codes = parse_admin_codes(corpus[ADMIN_GATE])
    expr = f"const canMibao = hasPermission('{codes[0]}') && hasPermission('{codes[1]}')\n"
    return {**corpus, WEB_PAGE: corpus[WEB_PAGE] + "\n" + expr}


def _inject_ghost_code(corpus: dict[str, str]) -> dict[str, str]:
    """③ 集合里写一个**目录里没有的码**（本单开工前的现状就是这一形态）。"""
    gate = corpus[ADMIN_GATE]
    codes = parse_admin_codes(gate)
    mutated = gate.replace(f'"{codes[2]}"', '"agent:ghost"', 1)
    assert mutated != gate, "注入锚点失配（`AdminGate` 的第三个成员没被换掉）"
    return {**corpus, ADMIN_GATE: mutated}


def _inject_wide_backfill(corpus: dict[str, str]) -> dict[str, str]:
    """④ 回填放宽到非 admin 岗位（违反裁定⑧）。"""
    migrations = {
        rel: text for rel, text in parse_migrations(corpus).items()
        if "MIBAO_CHAT_GRANT_CODE" not in text and "agent:chat" in text
    }
    assert len(migrations) == 1, f"注入锚点失配：含 agent:chat 的迁移不是 1 条：{sorted(migrations)}"
    rel, text = next(iter(migrations.items()))
    mutated = text.replace("AND r.code = 'admin'", "AND r.code IN ('admin', 'customer_service')", 1)
    assert mutated != text, "注入锚点失配（迁移里的 admin 谓词没被换掉）"
    return {**corpus, rel: mutated}


def _inject_role_based_judgement(corpus: dict[str, str]) -> dict[str, str]:
    """⑤ 判定改成读 `role` 字段（第二套身份口径，违反裁定③）。"""
    auth = corpus[AUTH_SERVICE]
    mutated = auth.replace(
        "AdminGate.canSummonMibao(permissions)",
        "\"admin\".equals(securityUser.getRoles() == null ? \"\" : securityUser.getRoles().get(0))",
        1,
    )
    assert mutated != auth, "注入锚点失配（`AdminGate.canSummonMibao(permissions)` 不在 `AuthService` 里）"
    return {**corpus, AUTH_SERVICE: mutated}


def _inject_silent_hide(corpus: dict[str, str]) -> dict[str, str]:
    """⑥ 未授权态文案退回泛化「无权限」（issue 范围 3 逐字禁止的形态）。

    注入面 = **导出常量的定义行**（不是全文首命中）—— 全文首命中会落在 JSDoc 的引用上，
    那样注入「生效了」但判据不变红，红证就成了空断言（本判据开发时实测踩过一次）。
    """
    text = corpus[WEB_GATE]
    mutated, n = GRANT_TEXT_RE.subn("MIBAO_NEEDS_ADMIN_GRANT_TEXT = '无权限'", text, count=1)
    assert n == 1 and mutated != text, "注入锚点失配（文案常量定义行没被换掉）"
    return {**corpus, WEB_GATE: mutated}


def _inject_corpus_collapse(corpus: dict[str, str]) -> dict[str, str]:
    """⑦ 防空跑判据自身的负向夹具 = 语料塌陷（模拟遍历剪枝写坏）。"""
    keep = {ADMIN_GATE}
    return {rel: text for rel, text in corpus.items() if rel in keep}


def _inject_stale_e2e_identity(corpus: dict[str, str]) -> dict[str, str]:
    """⑧ 把 E2E 管理员身份 mock 的能力位删掉（**这正是本包 CI 红的真实形态**）。"""
    text = corpus[E2E_FIXTURES]
    mutated = text.replace("capabilities: { mibaoChat: true },", "", 1)
    assert mutated != text, f"注入锚点失配（`{E2E_FIXTURES}` 的管理员身份能力位不在）"
    return {**corpus, E2E_FIXTURES: mutated}


INJECTIONS: dict[str, tuple["callable", "callable"]] = {
    "① 第二个文件里再抄一遍三码数组 ⇒ 判据 ① 红": (_inject_second_constant, problems_single_constant),
    "② 前端写 hasPermission(码) && hasPermission(码) ⇒ 判据 ② 红": (_inject_frontend_gate_by_code, problems_frontend_copy),
    "③ 集合里塞一个目录里没有的码 ⇒ 判据 ③ 红": (_inject_ghost_code, problems_codes_in_catalog),
    "④ 回填放宽到客服岗位 ⇒ 判据 ④ 红": (_inject_wide_backfill, problems_migration_shape),
    "⑤ 判定改成读 role 字段 ⇒ 判据 ⑤ 红": (_inject_role_based_judgement, problems_server_wiring),
    "⑥ 拒绝态文案退回「无权限」⇒ 判据 ⑥ 红": (_inject_silent_hide, problems_frontend_consumption),
    "⑦ 语料塌陷 ⇒ 判据 ⑦ 红": (_inject_corpus_collapse, problems_self_check),
    "⑧ 删掉 E2E 管理员身份 mock 的能力位 ⇒ 判据 ⑧ 红": (_inject_stale_e2e_identity, problems_e2e_identity_fidelity),
}


# ══════════════════════════════════════════════════════════════════════════════
# 五、用例
# ══════════════════════════════════════════════════════════════════════════════


def test_every_judgement_is_green() -> None:
    """全部判据在**当前仓库**上全绿（红 = 米宝唤出授权门已经漂移，逐条问题见断言文案）。"""
    corpus = load_corpus()
    problems = {label: fn(corpus) for label, fn in JUDGEMENTS.items()}
    bad = {label: p for label, p in problems.items() if p}
    assert bad == {}, "米宝唤出授权门判据未通过：\n" + "\n".join(
        f"  【{label}】\n    - " + "\n    - ".join(items[:12]) for label, items in bad.items()
    )


def test_every_judgement_can_go_red() -> None:
    """**每条**判据都要有能单独变红的注入（改坏必红、还原必绿）。"""
    covered = {fn for _mutate, fn in INJECTIONS.values()}
    missing = sorted(label for label, fn in JUDGEMENTS.items() if fn not in covered)
    orphan = sorted(label for label, (_m, fn) in INJECTIONS.items() if fn not in JUDGEMENTS.values())
    assert not missing and not orphan, (
        "判据表与注入表必须**互相覆盖**：缺注入 ⇒ 该判据永远不会红（空断言）；"
        "注入指向已删判据 ⇒ 红证无从归因。"
        f"\n  仅有判据、无注入：{missing}"
        f"\n  注入指向未登记的判据：{orphan}"
    )

    base = load_corpus()
    green = {label: fn(base) for label, fn in JUDGEMENTS.items()}
    assert all(not v for v in green.values()), (
        "对照组：未注入时全部判据必须全绿（否则红证无从归因）：\n"
        + "\n".join(f"  【{k}】{v[:2]}" for k, v in green.items() if v)
    )

    for label, (mutate, judgement) in INJECTIONS.items():
        mutated = mutate(base)
        assert mutated != base, f"{label}：注入没生效（锚点失配）—— 同步本判据"
        assert judgement(mutated), f"{label}：判据没有变红 ⇒ 它是空断言"
        # 撤回后复跑：变异的语料改回原样 ⇒ 该判据必须复绿（证明红的归因就是这次注入）
        assert not judgement(base), f"{label}：撤回注入后仍红 ⇒ 红的不是这次注入"
