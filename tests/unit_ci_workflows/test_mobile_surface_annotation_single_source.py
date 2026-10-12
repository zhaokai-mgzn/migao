# case_ids: MC-091
"""手机端可见面标注**只有一份真值**（issue #6759）—— 治「前端/注解里偷偷抄第二张『码 → 手机端面』表」。

## 病根（一类缺陷，不是一个缺陷）

「勾这个权限码 = 员工手机上多一个入口」这件事的真值**只有一处**：
`backend/admin-api/src/main/java/com/migao/admin/service/MobileSurfaces.java` 的 `ALL` + `TABS`
（手机端菜单的**服务端投影**，issue #6570 / #6574 的用户 2026-10-08 裁定「走 B」）。

而本单的需求是「在权限树上**标注**手机端可见面」—— 最容易走偏的落法就是**在前端另抄一张表**
（`'inbound:view' => '入库过账'` 之类）：它当时看着是对的，之后任何一个面被重命名 / 改读码 /
下架，**前端与手机端就会各说各话，而且不会有任何东西变红**（`migao-dev-flow` §19 的
「不会红的判据」形态）。

⇒ 本判据把「**真值只有一份**」变成机械判据（三条，各自可单独变红）：

| # | 判什么 | 红形态 |
|---|---|---|
| 1 | 手机端面名**只**出现在那一个服务端真值源里 | 在别的 Java 文件里新写一张「码 → 面名」表 ⇒ 具名红 |
| 2 | `rbac/manifest.json` 的 `menus.controller` ⇄ 动作节点台账 ⇄ 服务端真值源**三向相等** | 只改 `MenuController`（或只改台账 / 清单）⇒ 具名红，**报出是哪一个节点、差在哪** |
| 3 | `frontend/admin-web/src/**` 里**没有任何文件**同时出现「手机端面名」与「读该面的权限码」（除测试夹具外） | 前端抄一张映射表 ⇒ 具名红（谁、哪个面名） |

### 判据 3 的口径与边界（**照实登记**）

- 面名清单是**现取**的（从判据 1 那个真值源解析），不是写死的：真值源改一次，本判据的射程跟着改。
- ⚠️ 实测教训（**照实登记**）：判据自己的**正文与红证夹具里会不可避免地**出现「面名 + 读码」的
  并排文本（红证必须构造一个「抄了一张表」的坏形态）⇒ **判据 3 / 判据 1 的扫描面刻意排除
  判据自身**：判据 1 只扫 `backend/admin-api/src/main/java`（Python 判据不参与），
  判据 3 只扫生产前端源码（`frontend/**/tests/**` 的夹具是「模拟服务端下发的语料」，不参与打包，
  **有意放行**）。不排除就会**读进自己的举例而永久判红** —— MC-034 记录过的同款坑。
- 剥注释后判定（`test_rbac_single_source_manifest.py::strip_for`，**同一份实现**，不另写一套）——
  这样「只在注释里提一句」不会被判成第二份真值（对照读数见 `test_guard_discriminates_bad_shapes`）。
- **射程 = `frontend/admin-web/src/**` 的 `.ts` / `.tsx`**（含 `frontend/worker-h5` 与
  `frontend/bmini-app`：两者都不该长第二张表，但那两端的既有台账不在本单射程，
  属实红时按 `migao-dev-flow` §30 开单，不在这里放宽）。
- 判不来（如实登记）：**运行时**才能看出的第二份真值（如把面名存进 localStorage 再读）；
  以及「服务端下发的面名被前端**改写**」（如加了后缀）—— 前者形态上不存在，后者由
  `frontend/admin-web/tests/unit/components/TreeCheckbox.test.tsx` 的逐字断言兜住。

### 判据的判别力（自带红证，不读磁盘）

每条判据都是**纯函数**（输入 = 源码文本 / 台账 dict），红证在内存里构造坏形态直接喂进去；
另有「只改注释 ⇒ 不红」的对照读数。
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_CI_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
FRONTEND_SRC = REPO_ROOT / "frontend" / "admin-web" / "src"
MOBILE_SURFACES_JAVA = (
    REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/MobileSurfaces.java"
)
MENU_CONTROLLER_JAVA = (
    REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java"
)
MANIFEST_PATH = REPO_ROOT / "rbac" / "manifest.json"
PARITY_GUARD = UNIT_CI_DIR / "test_agent_permission_parity.py"
ISOMORPHIC_GUARD = UNIT_CI_DIR / "test_menu_three_sources_are_isomorphic.py"
MANIFEST_GUARD = UNIT_CI_DIR / "test_rbac_single_source_manifest.py"

if str(UNIT_CI_DIR) not in sys.path:
    sys.path.insert(0, str(UNIT_CI_DIR))

#: 前端源码面（判据 3）—— `.ts` / `.tsx`（`src/**` 下不存在别的会被打包进 UI 的类型）。
FRONTEND_SUFFIXES = (".ts", ".tsx")
#: 测试夹具（模拟**服务端下发**的语料）不在「前端第二份真值」的射程内 —— 它们不参与打包。
FRONTEND_EXCLUDED_DIR_PARTS = ("__tests__", "tests", "node_modules")


# ══════════════════════════ 共享解析实现（**复用**，不另写第二套） ══════════════════════════


def _load_module(name: str, path: Path):
    """按路径加载既有守卫模块（与 `rbac/generate_readings.py` 同款纪律：先注册 `sys.modules`）。"""
    if name in sys.modules:
        return sys.modules[name]
    assert path.is_file(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"无法为 {path} 建立加载器（fail-closed）"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _strip_for(suffix: str, text: str) -> str:
    """剥注释（**唯一实现**在 `test_rbac_single_source_manifest.py::strip_for`）。"""
    return _load_module("migao_rbac_manifest_guard", MANIFEST_GUARD).strip_for(suffix, text)


def _parse_controller_nodes(text: str) -> dict[str, str | None]:
    """`MenuController` 的**变量声明**节点表（`名称 → 码`）—— 复用既有解析器。

    为什么必须是它（而不是新写一条正则）：`test_agent_permission_parity.py::_iter_menu_controller`
    是「`MenuController` 节点表」的**唯一**解析点（`rbac/generate_readings.py` 的
    `menus.controller` 段也靠它）。再写一条 = 同一事实两套解析（`migao-dev-flow` §23 的 G 族）。
    """
    parity = _load_module("migao_rbac_parity_guard", PARITY_GUARD)
    return dict(parity._iter_menu_controller(text))


# ══════════════════════════ 判据 1：真值只有一份 ⇒ 面名只在真值源里 ══════════════════════════

#: 手机端面的声明形态：`new Surface("key", "中文名", route|null, 读码|null)`。
#: ⚠️ 必须锚 `new Surface(`（**带括号**）—— 类名 `MobileSurfaces` 的结尾也是 `Surfaces`
#: ⇒ 只写 `Surface\(` 会命中它自己（实测：`MobileSurfaces(` 被当成一个面）。
_SURFACE_DECL = re.compile(
    r'new\s+Surface\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*(?:"[^"]*"|null)\s*,\s*(?:"([^"]*)"|null)\s*\)'
)

#: 「**第二份面清单**」的形态锚：`new Surface(` 或 `new Surface"`（后者覆盖拼接 / 别名写法）。
#: 现取真语料命中 = **1 处**（就是真值源自己，实测）。
_SECOND_SOURCE_SHAPE = re.compile(r'new\s+Surface\s*[("]')


def mobile_surface_map(java_src: str) -> dict[str, list[str]]:
    """`MobileSurfaces.java` → `读码 → [面中文名…]`（纯函数；无码的面不进索引）。

    fail-closed：解析出 0 个面 ⇒ 抛错（判据不许空跑通过）。
    """
    out: dict[str, list[str]] = {}
    for _key, title, code in _SURFACE_DECL.findall(java_src):
        if not code:
            continue
        titles = out.setdefault(code, [])
        if title not in titles:
            titles.append(title)
    assert out, (
        "`MobileSurfaces.java` 解析出 0 个带读码的面 ⇒ 判据会空跑（fail-closed）；"
        "若面清单的声明形态变了，请同批改本判据的 `_SURFACE_DECL`"
    )
    return out


def stray_surface_title_problems(java_files: dict[str, str], source_path: str) -> list[str]:
    """真值源之外的 Java 文件里**不得**出现同一份「面名 + 读码」的声明（纯函数）。

    `java_files` = `{仓库相对路径: 源码}`；`source_path` = 真值源（豁免自己）。

    ⚠️ **判别形态刻意窄**：必须同时命中「**面构造形态**」（`new Surface(` + 字符串）与一个
    **面中文名**。为什么不能只看「出现了面名 + 读码」：`MenuController` 的菜单名里就有
    「智能派单」（= 面名），而它同时含 `processing:view` —— 那是**菜单**，不是手机端面的
    第二份声明（实测：宽口径在真语料上误报 `MenuController` 与 `AuthService` 两处）。
    """
    truth = mobile_surface_map(java_files[source_path])
    titles = {t for ts in truth.values() for t in ts}
    problems: list[str] = []
    for rel in sorted(java_files):
        if rel == source_path:
            continue
        body = _strip_for(".java", java_files[rel])
        if not _SECOND_SOURCE_SHAPE.search(body):
            continue
        hit_titles = sorted(t for t in titles if f'"{t}"' in body)
        if hit_titles:
            problems.append(
                f"`{rel}` 里出现了**面构造形态** + 手机端面名 {hit_titles} —— 手机端可见面的真值"
                f"只有一处（`{source_path}` 的 `new Surface(...)`），别处**不许**再声明一份"
                "（任何一张第二份映射表都会随真值源漂移而无人发现）"
            )
    return problems


# ══════════════════════════ 判据 3：前端没有第二张表 ══════════════════════════

#: 判据 3 的扫描面：**`frontend/admin-web/src/**`（生产源码）**。
#: ⚠️ **`frontend/bmini-app` 有意不在本判据的扫描面内**（照实登记，不粉饰）：
#: 那一端**已经**有一张「面 → 读码」台账（`frontend/bmini-app/src/utils/adminPermission.ts` 的
#: `ADMIN_SURFACES`，由 `frontend/bmini-app/tests/admin-surfaces-guard.test.ts` 与
#: `MobileSurfaces` 逐值比对守着）—— 它**早于**本单存在、设计上就是端侧镜像，本单**一字未改**它。
#: 把它纳进来会让判据在存量上永久判红（=把「存量债」当成「本单引入」），属于 §23.7 的 A 族误判。
#: 重启条件：bmini 若要新增**第二张**「面 → 读码」表，必须走它自己的守卫（BM-046 判据 5）。
FRONTEND_SCAN_ROOT = REPO_ROOT / "frontend" / "admin-web" / "src"
#: 测试夹具（模拟**服务端下发**的语料）不在「前端第二份真值」的射程内 —— 它们不参与打包。
FRONTEND_EXCLUDED_DIR_PARTS = ("__tests__", "tests", "node_modules")


def derived_surface_titles(surface_titles: set[str], menu_titles: set[str]) -> list[str]:
    """`面中文名` − `PC 菜单项名` = **只可能是手机端面**的那些名字（纯函数）。

    为什么必须先做这个减法：`MobileSurfaces` 的面名里天然有几个与 PC 菜单项**同名**
    （「智能派单」既是菜单项也是手机端面）⇒ 拿它当指纹会命中 `config/menu.ts` 自己的
    `permissionCode` 表（实测误报）。减完之后剩下的（如「入库过账 / 计件工资报表」）
    **再也无法解释成菜单名** ⇒ 出现在别处就是手机端面的第二份抄写。
    """
    return sorted(surface_titles - menu_titles)


def frontend_mapping_problems(
    files: dict[str, str],
    derived_titles: list[str],
    surface_codes: set[str],
) -> list[str]:
    """`admin-web/src/**` 里**不得**出现「**只可能是手机端面**的名字 + 手机端读码」的同文件共现。

    为什么不是「源码里出现面名就红」：真值源在**服务端**，前端拿到的面名一律来自
    `GET /api/admin/menus` 的 `mobileTitles`（客户端应答）⇒ 前端源码里出现面名是**预期**的。
    该红的形态是「**把面名与读码写死在同一处**」= 一张映射表（issue #6759 的第一红线）。
    """
    problems: list[str] = []
    for rel in sorted(files):
        body = _strip_for(Path(rel).suffix, files[rel])
        titles = sorted(t for t in derived_titles if f"'{t}'" in body or f'"{t}"' in body)
        codes = sorted(c for c in surface_codes if f"'{c}'" in body or f'"{c}"' in body)
        if titles and codes:
            problems.append(
                f"`{rel}` 同时出现**只可能是手机端面**的名字 {titles} 与手机端读码 {codes} ⇒ 疑似前端"
                "自备「码 → 手机端面」映射表（第二份会漂的真值）；前端只许渲染服务端下发的 "
                "`mobileTitles`（唯一渲染实现 = frontend/admin-web/src/lib/mobile-surface-label.ts）"
            )
    return problems


#: 声音点（reverse 自证）：前端确实有**唯一一处**渲染实现 —— 它必须存在且只有一处。
RENDERER_REL = "frontend/admin-web/src/lib/mobile-surface-label.ts"


# ══════════════════════════ 判据 2：清单 ⇄ 台账 ⇄ 真值源 三向相等 ══════════════════════════


def action_node_registration_problems(
    controller_nodes: dict[str, str | None],
    action_node_codes: dict[str, dict[str, str]],
    manifest_controller: dict[str, str | None],
    live_extra_labels: set[str],
) -> list[str]:
    """条目**双向**对账（纯函数）：登记未兑现 / 现取未登记 都判红。

    `live_extra_labels` = 树上「不是菜单项」的那些节点名（本判据不自己判「哪些是动作节点」——
    那是 `ACTION_NODES` / `ACTION_NODE_CODES` 的口径），这里只做**两侧一致性**：
    · 台账里每条的 `code` 必须 == 服务端真值源里同名节点的码；
    · 台账里每条的名字必须在真值源里存在（否则是陈旧登记 ⇒ 销账，不许挂着）；
    · 真值源 ⇄ `rbac/manifest.json` 的 `menus.controller` 逐值相等（**动作节点更要**逐值相等：
      它们不带 `path`，清单是它们进入「单一真值源」的唯一通道）。
    """
    problems: list[str] = []
    for label, entry in sorted(action_node_codes.items()):
        if label not in controller_nodes:
            problems.append(
                f"动作节点台账登记了『{label}』，但 `MenuController` 的节点表里没有它 ⇒ "
                "陈旧登记（销账或补节点，不许挂着：挂着会让下一次真回归静默通过）"
            )
            continue
        live = controller_nodes[label]
        if entry.get("code") != live:
            problems.append(
                f"动作节点台账『{label}』的码 = {entry.get('code')!r} ≠ 服务端真值源现取 {live!r}"
                "（涨跌都要同 PR 更新 `tests/unit_ci_workflows/test_rbac_derived_pages.py` 的 "
                "`ACTION_NODE_CODES`）"
            )
    for label in sorted(live_extra_labels):
        if label not in action_node_codes:
            problems.append(
                f"服务端真值源多出**未登记**的动作码节点『{label}』⇒ 未登记即红"
                "（要么它是菜单项，要么去 `ACTION_NODE_CODES` / `ACTION_NODES` 登记理由）"
            )
    for label, code in sorted(controller_nodes.items()):
        if label not in manifest_controller:
            problems.append(
                f"`rbac/manifest.json` 的 `menus.controller` 缺节点『{label}』（服务端真值源里有它）"
                " ⇒ 跑 `python3 rbac/generate_readings.py` 并同批更新清单（清单是单一真值源的声明面）"
            )
        elif manifest_controller[label] != code:
            problems.append(
                f"`rbac/manifest.json` 的 `menus.controller['{label}']` = {manifest_controller[label]!r}"
                f" ≠ 服务端真值源现取 {code!r}"
            )
    for label in sorted(manifest_controller):
        if label not in controller_nodes:
            problems.append(
                f"`rbac/manifest.json` 的 `menus.controller` 登记了『{label}』，但服务端真值源里没有它"
                " ⇒ 陈旧（销账）"
            )
    return problems


# ══════════════════════════ 语料装载（只读） ══════════════════════════


def _repo_java_files() -> dict[str, str]:
    root = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"
    return {str(p.relative_to(REPO_ROOT)): p.read_text(encoding="utf8") for p in sorted(root.rglob("*.java"))}


def _frontend_files() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(FRONTEND_SCAN_ROOT.rglob("*")):
        if p.suffix not in FRONTEND_SUFFIXES:
            continue
        if any(part in FRONTEND_EXCLUDED_DIR_PARTS for part in p.parts):
            continue
        out[str(p.relative_to(REPO_ROOT))] = p.read_text(encoding="utf8")
    assert out, f"前端源码面（{FRONTEND_SCAN_ROOT}）解析出 0 个文件 ⇒ 判据会空跑（fail-closed）"
    return out


def _pc_menu_titles() -> set[str]:
    """PC 侧边栏菜单项名（**复用**三源同构守卫的解析器 `_parse_frontend`，不另写一套）。"""
    iso = _load_module("migao_menu_isomorphic_guard", ISOMORPHIC_GUARD)
    front = iso._parse_frontend((REPO_ROOT / "frontend/admin-web/src/config/menu.ts").read_text(encoding="utf8"))
    return {name for _key, _group, items in front for name in items}


def _manifest_controller() -> dict[str, str | None]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf8"))["menus"]["controller"]


def _tree_extra_labels() -> set[str]:
    """树上「不是菜单项」的组内节点名（= `MenuController` 组内多出来的那些）。

    复用**三源同构守卫**的解析器（`_parse_controller` + `_parse_frontend`）与它的
    `ACTION_NODES` 台账 —— 「哪些节点是动作节点」的口径在那边，本判据不另判一次。
    """
    iso = _load_module("migao_menu_isomorphic_guard", ISOMORPHIC_GUARD)
    controller = iso._parse_controller(MENU_CONTROLLER_JAVA.read_text(encoding="utf8"))
    frontend = iso._parse_frontend((REPO_ROOT / "frontend/admin-web/src/config/menu.ts").read_text(encoding="utf8"))
    front_by_key = {key: names for key, _name, names in frontend}
    extra: set[str] = set()
    for key, _name, names in controller:
        head = front_by_key.get(key, [])
        extra.update(names[len(head):])
    return extra


# ══════════════════════════ 判据本体（真语料） ══════════════════════════


def test_mobile_surface_truth_lives_in_exactly_one_java_file() -> None:
    """判据 1：手机端面名**只**出现在 `MobileSurfaces.java` 里。"""
    source_path = str(MOBILE_SURFACES_JAVA.relative_to(REPO_ROOT))
    problems = stray_surface_title_problems(_repo_java_files(), source_path)
    assert problems == [], "手机端可见面真值出现了第二份：\n  - " + "\n  - ".join(problems)


def test_frontend_has_no_code_to_mobile_surface_table() -> None:
    """判据 3：`admin-web` **没有**自备「码 → 手机端面」映射表（面名与读码同文件共现即红）。"""
    surfaces = mobile_surface_map(MOBILE_SURFACES_JAVA.read_text(encoding="utf8"))
    titles = {t for ts in surfaces.values() for t in ts}
    derived = derived_surface_titles(titles, _pc_menu_titles())
    assert derived, (
        "「面名 − PC 菜单名」差分出 0 个 ⇒ 判据 3 会空跑（fail-closed）；"
        f"现取面名 = {sorted(titles)} —— 若真值源改名请同批核本判据"
    )
    files = _frontend_files()
    problems = frontend_mapping_problems(files, derived, set(surfaces))
    assert problems == [], "前端疑似自备手机端映射表：\n  - " + "\n  - ".join(problems)
    # 声音点 ①：唯一渲染实现必须还在（否则「没有第二份表」是空真 —— 前端可能干脆不渲染了）
    assert (REPO_ROOT / RENDERER_REL).is_file(), (
        f"手机端标注的唯一渲染实现 `{RENDERER_REL}` 不在了 ⇒ 判据 3 变成空真（无法归因）"
    )
    # 声音点 ②：扫描面与差分都要有可复算读数（现取，不写死数字会漂的那种断言）
    print(f"判据 3 扫描面 = {len(files)} 个 admin-web 源文件；`只可能是手机端面`的名字 = {derived}")


def test_mobile_surface_annotation_is_wired_to_the_menu_endpoint() -> None:
    """接线判据：`GET /api/admin/menus` 返回的必须是**已标注**的那棵树（不是裸 `MENU_TREE`）。

    形态级（服务端源码文本）：接口返回的那个常量必须由 `annotateMobileTitles(...)` 产出 ——
    有人把 `getMenuTree()` 改回返回裸树 ⇒ 当场红（否则「标注」只存在于单元测试的想象里）。
    """
    src = _strip_for(".java", MENU_CONTROLLER_JAVA.read_text(encoding="utf8"))
    m = re.search(r"return\s+ApiResponse\.success\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", src)
    assert m, "`MenuController` 里找不到 `return ApiResponse.success(<常量>)`（解析失配 ⇒ 红，不得静默跳过）"
    served = m.group(1)
    assert served != "MENU_TREE", (
        "`GET /api/admin/menus` 返回的是裸 `MENU_TREE` ⇒ 手机端标注根本没接线"
        "（判据必须看见 `annotateMobileTitles` 的产物）"
    )
    assert f"{served} = annotatedMenuTree()" in src or f"annotateMobileTitles(" in src, (
        f"送出的常量 `{served}` 与 `annotateMobileTitles(...)` 没有可判定的接线关系 ⇒ 同步本判据"
    )


def test_action_nodes_are_registered_in_both_ledgers_and_the_manifest() -> None:
    """判据 2：动作节点台账（两份）+ `rbac/manifest.json` + 服务端真值源**四向一致**。"""
    derived = _load_module("migao_rbac_derived_guard", REPO_ROOT / "tests/unit_ci_workflows/test_rbac_derived_pages.py")
    controller_nodes = _parse_controller_nodes(MENU_CONTROLLER_JAVA.read_text(encoding="utf8"))
    problems = action_node_registration_problems(
        controller_nodes, derived.ACTION_NODE_CODES, _manifest_controller(), _tree_extra_labels()
    )
    assert problems == [], "动作节点登记四向不一致：\n  - " + "\n  - ".join(problems)


# ══════════════════════════ 判别力自证（内存构造坏形态；红证不读磁盘） ══════════════════════════


def test_guard_discriminates_bad_shapes() -> None:
    """三种坏形态各自判红 + 一种对照（只改注释）不红 —— 判据本身不许退化成绿。"""
    truth_src = MOBILE_SURFACES_JAVA.read_text(encoding="utf8")
    source_rel = str(MOBILE_SURFACES_JAVA.relative_to(REPO_ROOT))
    surfaces = mobile_surface_map(truth_src)
    titles = {t for ts in surfaces.values() for t in ts}
    codes = set(surfaces)
    derived = derived_surface_titles(titles, _pc_menu_titles())
    # 夹具用的面名 / 读码**现取**（不写死字面量：写死的第一版在真值源改名后会静默失效）
    sample_title = derived[0]
    sample_code = next(c for c in sorted(codes) if sample_title in surfaces[c])

    # ── 判据 1 的红证：在**另一个** Java 文件里抄一张「面构造 + 面名」的表 ──
    bad_copy = (
        "package com.migao.admin.service;\n"
        "class Sneaky {\n"
        '  Surface s = new Surface("k", "' + sample_title + '", null, "' + sample_code + '");\n'
        "}\n"
    )
    fake_tree = {source_rel: truth_src, "backend/admin-api/src/main/java/com/migao/admin/service/Sneaky.java": bad_copy}
    assert stray_surface_title_problems(fake_tree, source_rel), "判据 1 对『别处抄一张面清单』不红 ⇒ 空断言"
    # 对照读数 ①：**只有面名、没有面构造形态**的 Java 文件 ⇒ 不红（判据 1 不是「见到面名就红」）
    clean_java = (
        "package com.migao.admin.service;\n"
        "class Clean {\n"
        '  String ref = "' + sample_code + '";\n'
        "}\n"
    )
    assert stray_surface_title_problems({source_rel: truth_src, "x/Clean.java": clean_java}, source_rel) == [], (
        "判据 1 对「只引用读码、没有面构造形态」的文件误报 ⇒ 射程过宽"
    )
    # 对照读数：**只把面名写进注释** ⇒ 不红（剥注释是同一份实现）
    comment_only_java = (
        "package com.migao.admin.service;\n"
        "class Sneaky {\n"
        "  // 举例：" + sample_title + " 与 " + sample_code + "\n"
        "}\n"
    )
    assert stray_surface_title_problems({source_rel: truth_src, "x/Sneaky.java": comment_only_java}, source_rel) == [], (
        "剥注释失效 ⇒ 判据 1 会被注释喂红"
    )

    # ── 判据 3 的红证：前端一张映射表 ──
    bad_front = {
        "frontend/admin-web/src/config/mobile-map.ts": (
            "export const M = { '" + sample_code + "': '" + sample_title + "' }\n"
        )
    }
    got = frontend_mapping_problems(bad_front, derived, codes)
    assert got and "mobile-map.ts" in got[0], "判据 3 对『前端抄一张映射表』不红 ⇒ 空断言"
    # 对照读数 ①：**只改注释** ⇒ 不红
    comment_only = {
        "frontend/admin-web/src/config/x.ts": (
            "// 举例：" + sample_title + " 与 " + sample_code + "\n"
            "const render = (node) => node.mobileTitles\n"
        )
    }
    assert frontend_mapping_problems(comment_only, derived, codes) == [], "剥注释失效 ⇒ 判据 3 会被注释喂红"
    # 对照读数 ②：**面名与读码各自独立出现**（不共现）⇒ 不红 —— 这条证明判据 3 不是「见到面名就红」
    split_files = {
        "frontend/admin-web/src/a.ts": "export const CODE = '" + sample_code + "'\n",
        "frontend/admin-web/src/b.ts": "export const T = '" + sample_title + "'\n",
    }
    assert frontend_mapping_problems(split_files, derived, codes) == [], "判据 3 对「各自独立出现」误报 ⇒ 射程过宽"

    # ── 判据 2 的红证（双向） ──
    controller = {"加工单操作": "processing:update", "新增员工": "employee:create"}
    good_ledger = {
        "加工单操作": {"code": "processing:update"},
        "新增员工": {"code": "employee:create"},
    }
    manifest = {"加工单操作": "processing:update", "新增员工": "employee:create"}
    assert action_node_registration_problems(controller, good_ledger, manifest, set(good_ledger)) == []
    # ① 台账里的码被改（只改一处）⇒ 红
    drifted = json.loads(json.dumps(good_ledger))
    drifted["加工单操作"]["code"] = "processing:manage"
    assert action_node_registration_problems(controller, drifted, manifest, set(good_ledger)), "台账码漂移不红 ⇒ 空断言"
    # ② 真值源多出一个**未登记**的动作节点 ⇒ 红（「只改 MenuController 不登记台账」的红证）
    grew = dict(controller, 入库单操作="inbound:create")
    assert action_node_registration_problems(grew, good_ledger, manifest, set(good_ledger) | {"入库单操作"}), "未登记新节点不红 ⇒ 空断言"
    # ③ 清单缺一项 / 值不等 ⇒ 红（「只改源码不重生成清单」的红证）
    assert action_node_registration_problems(controller, good_ledger, {"加工单操作": "processing:update"}, set(good_ledger)), "清单缺节点不红 ⇒ 空断言"
    assert action_node_registration_problems(controller, good_ledger, dict(manifest, 新增员工="employee:list"), set(good_ledger)), "清单值不等不红 ⇒ 空断言"
    # ④ 陈旧登记（台账里有、真值源没有）⇒ 红
    assert action_node_registration_problems({"新增员工": "employee:create"}, good_ledger, manifest, set(good_ledger)), "陈旧登记不红 ⇒ 空断言"

    # ── 解析器自证：真语料上解析出来的面清单不许为空（否则上面三条都在空跑） ──
    assert "processing:view" in surfaces and "inbound:view" in surfaces, (
        f"真语料解析出的手机端面读码 = {sorted(surfaces)} ⇒ 至少缺 issue #6759 涉及的两个面，判据在空跑"
    )
    assert titles == {"智能派单", "入库过账", "售后处理", "计件工资报表", "生产待办", "数据", "坐席"}, (
        f"真值源现取的面名 = {sorted(titles)} ⇒ 与预期不符时请核 `MobileSurfaces`（本断言是判据 1/3 射程的自证）"
    )
    assert derived == ["入库过账", "售后处理", "坐席", "数据", "生产待办", "计件工资报表"], (
        f"「面名 − PC 菜单名」现取 = {derived} ⇒ 与预期不符时请核 `menu.ts` 的菜单名（判据 3 的射程就是它）"
    )
    assert _tree_extra_labels(), "树上解析不出任何『组内多出的节点』 ⇒ 判据 2 会空跑（fail-closed）"
