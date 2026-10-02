# case_ids: MC-065
"""米宝「导航类」指引真值源（issue #5989 · P1）—— 登记表镜像 `menu.ts` + 权限码真值 + 默认拒绝 + 角色裁剪 + citation + **禁止编步骤**。

## 本文件判什么（逐条对应 issue #5989 的必做判据）

| # | 判据（判据函数） | 红证（注入式，见 `TestEveryJudgementCanGoRed`） |
|---|---|---|
| 1 | 登记项引用的**菜单路径真的存在**于 `menu.ts`（`problems_paths_exist`） | 改一条 `path` 成假路径 / 删一个节点 / 换顺序 ⇒ 红 |
| 1b | 登记表**双向覆盖** `menu.ts` 的导航节点（`problems_coverage`） | 删节点 / 加登记项 ⇒ 红 |
| 2 | 登记项声明的**权限码是真码**（`problems_codes_real`，复用 `test_agent_permission_parity.parse_catalog`） | 改一条码成目录里没有的码 ⇒ 红 |
| 3 | **未登记 ⇒ 不答/不返回猜的**（`problems_default_deny`，fail-closed） | 把「未命中」改成「猜第一条」⇒ 红 |
| 4 | **按角色裁剪**：只按服务端会话 `permissions` 过滤；**不读任何 role**（`problems_role_trim` + 签名判据） | 去掉裁剪 / 给 `build_navigation_answer` 加 role 形参 ⇒ 红 |
| 5 | **citation 可溯**（登记项 → 菜单节点）；未登记时如实说明未登记（`problems_citation`） | 摘掉「菜单节点」/ 给未登记项编假 citation ⇒ 红 |
| 6 | 🔴 **禁止编步骤**：结构与文本两层（`problems_no_steps_surface` / `problems_no_step_wording`） | 往 `data` 加 `steps` / 从 `message` 构造点摘掉步骤禁令 ⇒ 红 |
| 6b | 别名必须是**登记菜单名的一部分**（`problems_aliases_grounded`） | 换成自由同义词 ⇒ 红 |

## 🔴 硬约束：本文件**跑在没装 ai-agent 依赖的解释器里**（issue #5989 的一条新盲区，实测踩到）

CI 的 `ci workflow helper unit tests` job **只装 `pytest pyyaml`**（同 job 日志里既有 skip 逐字写着
「当前解释器缺 ai-agent 依赖（fastapi/pytest_asyncio/pytest_cov）……静态判据仍生效」）⇒
**本文件不得 import 任何 `app.*` 运行时模块**（`app.tools.*` 会拉 `pydantic` / `langchain_core`；
实测直接 6 failed，本地全绿、CI 全红）。

⇒ 本文件的每一条都必须是**静态**的：解析源码文本（AST / 正则）+ 执行**零依赖**的纯函数
（`app/context/menu_navigator.py` 只依赖标准库 ⇒ 按路径加载它**是允许的**，它不是"ai-agent 运行时依赖"）。
**需要真 import 的行为级判据**（工具真跑一遍的返回形状、`visible_nodes` 的角色裁剪）一律放
`backend/ai-agent-service/tests/test_nav_guide.py`（那里有依赖）—— 两处**不重复**同一断言：
本文件判「源码里有没有这件事」，那份判「跑起来是不是这样」。

## 复用而不造第二套（§17.3）

- **`menu.ts` 解析器** = `tests/unit_ci_workflows/test_agent_permission_parity.parse_menu_ts_nodes`
  （按**路径**动态加载 —— 本文件与它在同一层 `tests/`，`from` 不可达，故走 `spec_from_file_location`）；
- **权限目录解析器** = 同模块的 `parse_catalog`（两处目录**逐值相等**也由它核）；
- **权限判定口径** = `app.context.menu_navigator.has_permissions`，与 `page_registry.has_permissions` /
  `frontend/admin-web/src/lib/menu-nav.ts` 的 `hasPermission` 同族（`*` 通配 / 无码不设限）。

## 明确不在本文件射程（照实登记）

- **工具真跑的行为面**（`execute` 的 `success`/`error` 口径、`data` 键运行时形状、按 role 不变性）
  ⇒ `backend/ai-agent-service/tests/test_nav_guide.py`；
- **LLM 是否真的引用了 citation / 是否真的没编步骤**（行为面）—— 按 `migao-dev-flow` §13.2 映射到
  `.github/cases/misc.yml` 的 MC-065 走评测；本文件判的是**结构面**（真值源、裁剪、citation、无 steps 字段），
  即「可追溯、不可编」的**必要条件**；
- **P2（主动新手引导）的推送面**：本包只提供 `visible_nodes` / `nodes_for_feature` 接口，**不判推送**。
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

import pytest

REPO_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / ".github" / "cases").is_dir()
)
AI_SERVICE = REPO_ROOT / "backend" / "ai-agent-service"
MENU_TS = REPO_ROOT / "frontend" / "admin-web" / "src" / "config" / "menu.ts"
NAV_MODULE = AI_SERVICE / "app" / "context" / "menu_navigator.py"
NAV_TOOL = AI_SERVICE / "app" / "tools" / "nav_guide.py"
PARITY_TEST = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"
REGISTRATION_SERVICE = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin" / "service" / "RegistrationService.java"
PERMISSION_SERVICE = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin" / "service" / "PermissionService.java"
# 工具面的**静态**判据输入（本 job 只装 pytest/pyyaml ⇒ 一律扫源码，不 import `app.*`）
REGISTRY_SOURCE = AI_SERVICE / "app" / "tools" / "registry.py"
FACADE_SOURCE = AI_SERVICE / "app" / "tools" / "__init__.py"
GENERAL_SKILL_SOURCE = AI_SERVICE / "app" / "graph" / "skills" / "general_agent.py"

#: 步骤类反模式（禁止 LLM 编步骤的机械落点）：`message` / `suggestion` / `data` 的文本面。
#:
#: ⚠️ **受控词表**：只放「**要求模型去做步骤**」的祈使/枚举词，**不**放中性名词
#: （如 `操作步骤`）—— 因为**如实否认**的那句话逐字就是「我没有步骤级指引 / 不得扩写成操作步骤」，
#: 把中性名词也当反模式 ⇒ **判据被自己的文案喂红**（`migao-dev-flow` §17.3）。
#: 本判据的真正承载体是**结构**判据 6a（`data` 键白名单里没有 `steps`）：工具**没有能力**
#: 返回步骤；这条文本面判据只是补「文案里也别写成步骤」。
STEP_WORDS: Tuple[str, ...] = (
    "第一步", "第二步", "第三步", "步骤如下", "点击", "点一下", "先点",
    "然后点", "最后点", "按下", "按钮", "输入框", "下拉框", "依次",
)

#: `data` 的键白名单（**结构面**判据 6）：多一个键就红 ⇒ `steps` 这类字段进不来。
ALLOWED_DATA_KEYS = frozenset(
    {"registered", "featureId", "label", "pages", "deniedMenuNames", "citation"}
)
ALLOWED_PAGE_KEYS = frozenset({"menuGroup", "menuName", "path", "requiredPermission"})

#: 未登记问题的样本（默认拒绝判据的输入面）。
UNREGISTERED_QUESTIONS: Tuple[str, ...] = (
    "米宝你能帮我做什么",
    "帮我看看这个怎么弄",
    "这些数字是什么意思",
    "",
    "皮料怎么算价",
    # issue #6062：**这里必须放「一个已登记说法都不含」的问句**（判据 3 的新前置臂会机械核它）。
    # 「怎么导出订单 Excel」原先在这张表里，而 #6062 给「订单列表」登记了口语说法「订单」
    # ⇒ 它现在**有**登记项（返回订单列表页 + 如实说没有步骤级指引 = 导航类的正确回答）。
    # 这不是放宽判据：判据 3 仍逐条核「未登记 ⇒ 零路径零码 + 如实告知」，只是把**样本**换成
    # 真的不含任何说法的问句 —— 顺手把「样本表自己过期」这一类做成机械前置（见下）。
    "日程怎么安排",
)


# ══════════════════════════════════════════════════════════════════════════════
# 夹具：对账守卫模块 / 被测模块 / menu.ts 节点 / 权限目录
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def parity():
    """按路径加载对账守卫模块（复用它的 `menu.ts` / 权限目录解析器，**不造第二套**）。"""
    name = "migao_parity_for_nav"
    if name in sys.modules:
        return sys.modules[name]
    assert PARITY_TEST.is_file(), f"被判据复用的解析器不存在：{PARITY_TEST}（路径漂移 ⇒ 红）"
    sys.path.append(str(REPO_ROOT / "tests"))
    spec = importlib.util.spec_from_file_location(name, PARITY_TEST)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def nav():
    """按路径加载被测模块（`ai-agent-service` 根不在本仓根的 sys.path 上）。"""
    name = "migao_menu_navigator_under_test"
    if name in sys.modules:
        return sys.modules[name]
    assert NAV_MODULE.is_file(), f"被测模块不存在：{NAV_MODULE}（路径漂移 ⇒ 红）"
    # `menu_navigator` 只依赖标准库（**不是** ai-agent 运行时依赖）⇒ 本 job 里按路径加载它是安全的；
    # `sys.path` 只是为了让它按 `__name__` 正常完成（模块内部不再 import 别的东西）。
    sys.path.insert(0, str(AI_SERVICE))
    spec = importlib.util.spec_from_file_location(name, NAV_MODULE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def menu_ts_nodes(parity):
    assert MENU_TS.is_file(), f"菜单单一源不存在：{MENU_TS}（路径漂移 ⇒ 红，不得静默跳过）"
    nodes = parity.parse_menu_ts_nodes(MENU_TS.read_text(encoding="utf8"))
    assert nodes, "menu.ts 解析出 0 个节点 ⇒ 判据会空跑（fail-closed）"
    return nodes


@pytest.fixture(scope="module")
def catalog(parity):
    """权限目录（两处）—— `CATALOG_UNDER_TEST` 的夹具投影（**同一份读数**，不读两遍）。"""
    reg, perm = CATALOG_UNDER_TEST
    assert reg and perm, "权限目录解析出 0 条 ⇒ 判据会空跑（fail-closed）"
    return reg, perm


def _load_catalog() -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """现读两处权限目录（复用 `test_agent_permission_parity.parse_catalog`，不造第二套）。"""
    parity = _load_parity_module()
    for path in (REGISTRATION_SERVICE, PERMISSION_SERVICE):
        assert path.is_file(), f"权限目录文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    return parity.parse_catalog(
        REGISTRATION_SERVICE.read_text(encoding="utf8"),
        PERMISSION_SERVICE.read_text(encoding="utf8"),
    )


def _load_parity_module() -> Any:
    """按路径加载对账守卫模块（`menu.ts` / 权限目录解析器的**同一个**实现）。"""
    name = "migao_parity_for_nav"
    if name in sys.modules:
        return sys.modules[name]
    assert PARITY_TEST.is_file(), f"被判据复用的解析器不存在：{PARITY_TEST}（路径漂移 ⇒ 红）"
    sys.path.append(str(REPO_ROOT / "tests"))
    spec = importlib.util.spec_from_file_location(name, PARITY_TEST)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


#: 现读的两处权限目录（模块级常量：对照读数也要用同一份）。
CATALOG_UNDER_TEST = _load_catalog()


def _load_mutated(tmp_path: Path, mutate: Callable[[str], str]) -> Any:
    """把被测模块源码注入变异后**真跑一遍**（注入式红证的地基）。

    为什么必须在**内存/副本**里执行而不是「改真文件再还原」：判据与红证要能同批跑，
    且不动仓内文件（`migao-dev-flow` §23 G7 的前提自证）。

    ⚠️ 变异可能让模块**导入期自检**失败（那是 fail-closed 的正常表现）⇒ 调用方可以用
    `pytest.raises(MenuNavigatorError)` 把它当作**红读数**（本文件有这种用法）。
    """
    source = NAV_MODULE.read_text(encoding="utf8")
    mutated = mutate(source)
    assert mutated != source, "注入**未生效**（源码逐字未变）⇒ 红证是空断言"
    path = tmp_path / f"menu_navigator_mutated_{abs(hash(mutated)) % 10**8}.py"
    path.write_text(mutated, encoding="utf8")
    name = f"migao_nav_mutated_{abs(hash(mutated)) % 10**8}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ══════════════════════════════════════════════════════════════════════════════
# 判据本体（**纯函数**：真模块与注入模块走同一份判据 —— §28.2「判据绿 ≠ 接线在」）
# ══════════════════════════════════════════════════════════════════════════════


def problems_paths_exist(mod, menu_ts_nodes) -> List[str]:
    """判据 1：`MENU_TREE` 每一列的取值都来自 `menu.ts`（路径 / 菜单名 / 权限码）。"""
    out: List[str] = []
    ts_by_path = {n.path: n for n in menu_ts_nodes}
    for node in mod.MENU_TREE:
        ts = ts_by_path.get(node.path)
        if ts is None:
            out.append(
                f"登记项引用的菜单路径 {node.path!r}（节点「{node.label}」）在 config/menu.ts 里**不存在**"
                " —— 未登记的路径就是「编出来的页面」（fail-closed：改登记表或改 menu.ts）"
            )
            continue
        if ts.name != node.label:
            out.append(f"{node.path}：登记菜单名「{node.label}」≠ menu.ts 的「{ts.name}」")
        if (ts.code or "") != node.permission_code:
            out.append(f"{node.path}：登记权限码 {node.permission_code!r} ≠ menu.ts 的 {ts.code!r}")
    return out


def problems_coverage(mod, menu_ts_nodes) -> List[str]:
    """判据 1b：`menu.ts` 的导航节点集 ⇄ `MENU_TREE` 的**双向相等** + 顺序锁定。

    ⚠️ `parse_menu_ts_nodes` 也产出**组头**（无 `path` 的节点，值是 `None`）⇒ 导航节点集 =
    它里面 `path` 非 `None` 的那部分（**不另写第二个解析器**，只做投影）。
    """
    out: List[str] = []
    ts_paths = [n.path for n in menu_ts_nodes if n.path]
    declared = [n.path for n in mod.MENU_TREE]
    only_declared = sorted(set(declared) - set(ts_paths))
    only_ts = sorted(set(ts_paths) - set(declared))
    if only_declared or only_ts:
        out.append(
            "MENU_TREE 与 menu.ts 的导航节点集不相等（新增/删除菜单项必须同批登记）："
            f" 只在 MENU_TREE={only_declared}；只在 menu.ts={only_ts}"
        )
    if declared != ts_paths:
        out.append("MENU_TREE 的顺序与 menu.ts 的渲染顺序不同（一级项插在哪个组之后是信息架构的一部分）")
    locked = tuple((n.group, n.label, n.path, n.permission_code) for n in mod.MENU_TREE)
    if mod.MENU_TREE_ORDER_LOCKED != locked:
        out.append("MENU_TREE_ORDER_LOCKED 与 MENU_TREE 不一致（判据锚漂移 ⇒ 注入式红证会变成空断言）")
    return out


def problems_codes_real(mod, catalog) -> List[str]:
    """判据 2：每个非空权限码都在 `RegistrationService` / `PermissionService` 的目录里。"""
    out: List[str] = []
    reg, perm = catalog
    if reg != perm:
        out.append("两处权限目录不相等（`RegistrationService` vs `PermissionService`）—— 先修目录")
    known = set(reg) | set(perm)
    for node in mod.MENU_TREE:
        if node.permission_code and node.permission_code not in known:
            out.append(
                f"{node.path} 的权限码 {node.permission_code!r} 不在权限目录里 ⇒ 该节点对**所有**岗位"
                "恒不可见（#4203 同族坑：有码没人持有 = 零菜单入口）"
            )
    no_code = {n.path for n in mod.MENU_TREE if not n.permission_code}
    if no_code != {"/notifications"}:
        out.append(
            f"无权限码的节点集变了：{sorted(no_code)} —— 新增无码节点 = 对全员可见，必须显式登记"
        )
    return out


def problems_default_deny(mod) -> List[str]:
    """判据 3：未登记的问题 ⇒ `registered is False`、**零路径零码**，且如实说明未登记。

    ⚠️ **样本表的前置自断言**（issue #6062）：表里每条问句都必须**一个已登记说法都不含** ——
    否则「未登记」这个读数与它声称的对象不是同一个（样本过期），判据会**因错的原因**变红/变绿。
    #6062 给菜单名登记了口语说法后，「怎么导出订单 Excel」含了「订单」⇒ 已按此口径移出该表。
    """
    out: List[str] = []
    known_aliases = sorted({a for feature in mod.NAV_FEATURES for a in feature.aliases})
    for question in UNREGISTERED_QUESTIONS:
        contaminated = [a for a in known_aliases if a and a in question]
        if contaminated:
            out.append(
                f"未登记样本 {question!r} 含了已登记的说法 {contaminated} ⇒ 样本过期"
                "（它现在**有**登记项）—— 判据 3 会因错的原因判红，请换一条真的不含任何说法的问句"
            )
    for question in UNREGISTERED_QUESTIONS:
        answer = mod.build_navigation_answer(question, ["*"])
        if answer.registered:
            out.append(f"未登记的问题 {question!r} 竟然被判「有登记项」⇒ 猜了")
            continue
        payload = answer.to_data()
        if payload["pages"]:
            out.append(f"未登记的问题 {question!r} 返回了页面路径：{payload['pages']}")
        if payload["featureId"]:
            out.append(f"未登记的问题 {question!r} 返回了 featureId={payload['featureId']!r}")
        if mod.NAV_NOT_REGISTERED_NOTICE not in answer.render():
            out.append(f"未登记的问题 {question!r} 的回答里没有如实告知常量")
    for feature in mod.NAV_FEATURES:
        hit = mod.resolve_feature(feature.label)
        if hit is None or hit.feature_id != feature.feature_id:
            out.append(
                f"{feature.feature_id}：连自己的功能名「{feature.label}」都命中不了"
                f"（命中到 {getattr(hit, 'feature_id', None)!r}）—— 别名撞车或登记表退化了"
            )
    if len(mod.NAV_FEATURES) < 15:
        out.append(f"登记项只有 {len(mod.NAV_FEATURES)} 条 ⇒ 判据疑似空转（fail-closed）")
    return out


def problems_role_trim(mod) -> List[str]:
    """判据 4：裁剪**只**看会话权限 —— 无权 ⇒ 不泄露路径/码，但 citation 仍可溯。"""
    out: List[str] = []
    blind = mod.build_navigation_answer("工艺配置在哪", ["order:list"])
    if blind.registered is not True:
        out.append("「工艺配置」是已登记功能，无权角色也应拿到 registered=True（只是看不到页面）")
    if blind.granted:
        out.append("无权角色竟拿到 granted 节点 ⇒ 裁剪失效（越权面）")
    if not blind.denied:
        out.append("裁剪把登记节点整个弄丢了（既不在 granted 也不在 denied）⇒ 判据会空跑")
    blob = json.dumps(blind.to_data(), ensure_ascii=False)
    if "/production/routings" in blob:
        out.append("无权角色的载荷里出现了页面路径 ⇒ 越权面")
    if "production:view" in blob:
        out.append("无权角色的载荷里出现了权限码 ⇒ 越权面")
    if "登记项 #production-process" not in blind.to_data()["citation"]:
        out.append("无权角色的 citation 不可溯（必须仍然引登记项 → 菜单节点）")
    for feature in mod.NAV_FEATURES:
        answer = mod.build_navigation_answer(feature.label, ["*"])
        if answer.denied:
            out.append(f"{feature.feature_id}：`*` 通配角色竟有看不到的登记节点")
    if list(inspect.signature(mod.build_navigation_answer).parameters) != ["query", "permissions"]:
        out.append(
            "`build_navigation_answer` 的形参不是 (query, permissions) ⇒ "
            "裁剪可能被 role 之类**客户端可伪造**的入参影响（与 page_registry 同纪律）"
        )
    return out


CITATION_NOT_REGISTERED = "登记项：（无）—— 未命中「功能 → 页面 → 权限」登记表"


def problems_citation(mod, source: str) -> List[str]:
    """判据 5：citation 必须**引登记项 → 菜单节点**；未登记 ⇒ 如实说明「（无）」。

    ⚠️ 「citation 落在 source 里」是**结构必要条件**（`render()` 把 citation 拼进 message）。
    真正的运行时读数（某条回答的 citation 逐字形态）在
    `backend/ai-agent-service/tests/test_nav_guide.py` 判（本 job 跑不起来工具）。
    """
    out: List[str] = []
    answer = mod.build_navigation_answer("商品管理在哪", ["product:list"])
    citation = answer.to_data()["citation"]
    if citation != "登记项 #products → 菜单节点 一级项「商品管理」":
        out.append(f"citation 不可溯到「登记项 → 菜单节点」：{citation!r}")
    node = mod.menu_node(mod.STANDALONE_GROUP, "商品管理")
    if node is None:
        out.append("`menu_node(STANDALONE_GROUP, '商品管理')` 查不到 —— 登记表被改坏了")
    if mod.menu_node("no-such-group", "商品管理") is not None:
        out.append("未登记节点竟返回了节点对象（默认拒绝失效）")
    literals = _module_string_literals(source)
    # citation 的两段模板逐字锚（f-string 的静态片段就是字符串字面量 ⇒ AST 拿得到）
    if "登记项 #" not in literals:
        out.append("源码里找不到 citation 左端模板字面量「登记项 #」⇒ 无法从答案追回登记项")
    if " → 菜单节点 " not in literals:
        out.append("源码里找不到 citation 右端模板字面量「 → 菜单节点 」⇒ 无法从答案追回菜单节点")
    if "登记项：（无）—— 未命中「功能 → 页面 → 权限」登记表" not in literals:
        out.append("未登记时的 citation 文案（「登记项：（无）…」）不在源码的字符串字面量里")
        out.append(
            "`menu_navigator.py` 源码里找不到「登记项 #…→ 菜单节点 …」的拼装 ⇒ "
            "citation 的**可追溯形态**在本文件里判不了（要么被删了，要么改了）"
        )
    if "self.citation" not in source:
        out.append("citation 没有被拼进回答（`self.citation` 在源码里不出现）⇒ 答案不可追溯")
    return out


def problems_no_steps_surface(mod) -> List[str]:
    """判据 6（**结构面**）：`data` 的键白名单 —— `steps` 这类字段**结构上**进不来。

    两段：① **源码字面量**（`to_data()` 的 `return {…}` 字典键集，AST 取）—— 想加字段就必须在这里加键；
    ② **运行时键集**（跑一遍 `to_data()` 看现取键集；纯标准库，本 job 可跑）。
    ② 覆盖 `pages` 里每个页面项的键（① 只看最外层）。
    """
    out: List[str] = []
    outer, inner = _to_data_literal_keys(_nav_module_source())
    extra_outer = sorted(outer - ALLOWED_DATA_KEYS)
    if extra_outer:
        out.append(
            f"`NavigationAnswer.to_data()` 的最外层载荷多出未登记的键 {extra_outer} —— "
            "`steps` / 操作说明 / 图文一律不得进这个载荷"
        )
    extra_inner = sorted(inner - ALLOWED_PAGE_KEYS)
    if extra_inner:
        out.append(f"`to_data()` 的页面项多出未登记的键 {extra_inner}")
    for feature in mod.NAV_FEATURES:
        payload = mod.build_navigation_answer(feature.label, ["*"]).to_data()
        extra = sorted(set(payload) - ALLOWED_DATA_KEYS)
        if extra:
            out.append(f"{feature.feature_id}：data 多出未登记的键 {extra}")
        for page in payload["pages"]:
            page_extra = sorted(set(page) - ALLOWED_PAGE_KEYS)
            if page_extra:
                out.append(f"{feature.feature_id}：页面项多出未登记的键 {page_extra}")
    unregistered = mod.build_navigation_answer("随便问点什么", ["*"]).to_data()
    extra = sorted(set(unregistered) - ALLOWED_DATA_KEYS)
    if extra:
        out.append(f"未登记回答的 data 多出未登记的键 {extra}")
    return out


def _nav_module_source() -> str:
    """`app/context/menu_navigator.py` 的源码文本（**静态判据的唯一输入**）。"""
    assert NAV_MODULE.is_file(), f"真值源源码不存在：{NAV_MODULE}（路径漂移 ⇒ 红，不得静默跳过）"
    return NAV_MODULE.read_text(encoding="utf8")


def _nav_tool_source() -> str:
    """`app/tools/nav_guide.py` 的源码文本（**静态判据的唯一输入** —— 本 job 不 import 它）。"""
    assert NAV_TOOL.is_file(), f"工具源码不存在：{NAV_TOOL}（路径漂移 ⇒ 红，不得静默跳过）"
    return NAV_TOOL.read_text(encoding="utf8")


def _nav_tool_class_attrs() -> dict:
    """AST 反解 `NavGuideTool` 类体里的字面量赋值（`read_only` / `required_permissions` / `name` / …）。

    **为什么不用 import**：CI 的 `ci workflow helper unit tests` job 只装 `pytest pyyaml` ⇒
    `app.tools.*` 会拉 `pydantic` / `langchain_core` ⇒ `ModuleNotFoundError`（本地绿、CI 红，实测踩到）。
    """
    tree = ast.parse(_nav_tool_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "NavGuideTool":
            out: dict = {}
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                ):
                    try:
                        out[stmt.targets[0].id] = ast.literal_eval(stmt.value)
                    except ValueError:
                        out[stmt.targets[0].id] = None   # 非字面量（如 `parameters` 的 dict 也算字面量）
            return out
    raise AssertionError("`app/tools/nav_guide.py` 里找不到 `class NavGuideTool` ⇒ 判据会空跑（fail-closed）")


def _dict_literal_keys(node: ast.Dict) -> set:
    """字典字面量的**字符串键集**（非字符串键**具名**报出，不静默丢）。"""
    keys: set = set()
    for k in node.keys:
        if k is None:
            continue          # `**other` 展开：结构上取不到字面量 ⇒ 由调用方另判
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.add(k.value)
        else:
            keys.add(f"<非字符串键：{ast.dump(k)[:40]}>")
    return keys


def _to_data_literal_keys(source: str) -> Tuple[set, set]:
    """`NavigationAnswer.to_data()` 的两层键集：`(最外层 return {…} 的键, 页面项字典的键)`。

    这是**结构面**判据 6 的机械落点：`steps` 这类字段想进来，就必须在字面量里出现一个新键。
    ⚠️ 找不到最外层 `return {…}` ⇒ **直接抛**（fail-closed，不许静默返回空集恒绿）。
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "to_data":
            continue
        returns = [st for st in ast.walk(node) if isinstance(st, ast.Return)]
        assert returns, "`to_data()` 里没有 `return`（函数体被改坏）⇒ 判据会空跑"
        top = [r for r in returns if isinstance(r.value, ast.Dict)]
        assert top, "`to_data()` 的 `return` 不是字典字面量 ⇒ 结构面判据会空跑（fail-closed）"
        outer = _dict_literal_keys(top[0].value)
        inner: set = set()
        for sub in ast.walk(top[0].value):
            if isinstance(sub, ast.Dict) and sub is not top[0].value:
                inner |= _dict_literal_keys(sub)
        return outer, inner
    raise AssertionError("`NavigationAnswer.to_data()` 不存在 ⇒ 结构面判据会空跑（fail-closed）")


def _module_string_literals(source: str) -> set:
    """模块里所有**字符串字面量**的集合（用于核「某个告知文案逐字在源码里」）。"""
    return {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def problems_no_step_wording(source: str) -> List[str]:
    """判据 6（**源码文本面**）：工具源码（含**注入模型**的 `description` 与各 `message`/`suggestion`
    构造点）里不得出现受控步骤词。

    ⚠️ 这里判的是**源码**而不是"跑出来的回复"：本 job 没有 ai-agent 依赖，跑不起来。
    「跑起来的回复里也没有步骤词」由 `backend/ai-agent-service/tests/test_nav_guide.py` 判（不重复）。
    """
    out: List[str] = []
    hits = sorted({w for w in STEP_WORDS if w in source})
    if hits:
        out.append(
            f"`app/tools/nav_guide.py` 的源码里出现步骤词 {hits} —— 该文件的散文字面量会进模型上下文；"
            "第一批**只做导航类**：禁止把工具返回扩写成操作步骤（用户裁定 2026-10-02）"
        )
    return out


def problems_aliases_grounded(mod) -> List[str]:
    """判据 6b：说法必须是某个被登记菜单名（**或本功能 `label` 的括注**）的一部分
    ⇒ 说法表不可能退化成同义词词典。

    issue #6062 把接地面对齐到 `label`：`label` 的括注承载两件事 —— ① 菜单名与口语的落差
    （「发货单（出库）」）② **无独立导航目标的**操作（「员工管理（员工开账号）」）。
    这**不放宽**判据的实质：`label` 仍在本模块（人登记），不是 `menu.ts` 的任意文本。
    """
    out: List[str] = []
    for feature in mod.NAV_FEATURES:
        labels = set()
        for group, label in feature.node_keys:
            node = mod.menu_node(group, label)
            if node is None:
                out.append(f"{feature.feature_id}：引用了不存在的菜单节点 {(group, label)}")
                continue
            labels.add(node.label)
        if not feature.aliases:
            out.append(f"{feature.feature_id}：aliases 为空 ⇒ 这条登记永远匹配不到")
        for alias in feature.aliases:
            if not any(
                alias in label or label in alias for label in labels | {feature.label}
            ):
                out.append(
                    f"{feature.feature_id}：说法 {alias!r} 与登记菜单名 {sorted(labels)} /"
                    f" 功能名 {feature.label!r} 都无包含关系"
                    " ⇒ 说法表正在退化成同义词词典（禁止自由匹配）"
                )
    return out


# ──────────────────────────────────────────────────────────────────────────────
# issue #6062 新增的三条**类级**判据（治「真值源覆盖不足」，与既有八条不重复）
#
# 病（实测 2026-10-02 B 端真实评测 `normal` 档）：`nav_guide!nav_not_registered ×1`，
# 用户输入「怎么给员工开账号」⇒ 登记面里**没有这条说法** ⇒ agent 只能含糊其辞。
# 这不是「agent 不听话」，是**登记面覆盖不足**；三条判据把同类缺口堵在门外。
# ──────────────────────────────────────────────────────────────────────────────


def problems_nodes_without_hit_alias(mod) -> List[str]:
    """判据 7：**每个菜单节点至少有一条说法能命中它**（否则那个页面用户永远问不到）。

    判法：这条说法必须**逐字出现在它所属节点的菜单名里**（= 用户问菜单名时能命中）。
    语义层只登记「`menu.ts` 的菜单名也能命中」的那条，是「该页面可达」的**必要条件**：
    没有它，`resolve_feature` 对该页的菜单名必然未命中（最长命中无从谈起）。
    """
    out: List[str] = []
    declaring: dict = {}
    for feature in mod.NAV_FEATURES:
        for group, label in feature.node_keys:
            node = mod.menu_node(group, label)
            if node is None:
                continue
            for alias in feature.aliases:
                if alias and alias in node.label:
                    declaring.setdefault(node.label, []).append(feature.feature_id)
    for node in mod.MENU_TREE:
        if node.label not in declaring:
            out.append(
                f"菜单节点「{node.label}」（{node.path}）**没有任何说法能命中它** ⇒ 用户永远问不到"
                "（给它的登记项补一条**逐字等于菜单名**的说法；menu.ts 改菜单名要同批改）"
            )
    return out


def _maximal_aliases(mod) -> List[Tuple[str, str]]:
    """有资格进 `has_prefix` 分支的说法 = 不在**同一功能**里被更长说法盖住的那些。

    为什么先做这一步（**可达性的推导**）：`resolve_feature` 对同一功能取**最长**命中
    ⇒ 若 a 是 b 的子串且 a/b 同属一个功能，凡是命中 a 的 `has_prefix` 查询也必然命中 b
    ⇒ a 永远不可能是该功能的**决定性**说法。
    """
    aliases = [(f.feature_id, a) for f in mod.NAV_FEATURES for a in f.aliases]
    return [
        (owner, alias)
        for owner, alias in aliases
        if not any(
            other_owner == owner and alias in other_alias and alias != other_alias
            for other_owner, other_alias in aliases
        )
    ]


def problems_shadowed_aliases(mod) -> List[str]:
    """判据 8：**没有空登记（死条目）** —— 每条说法都必须**能解出它自己的功能**。

    判法（与 `resolve_feature` 的最长命中口径**逐字同源**）：对每条说法取
    `has_prefix` 分支 = 「含它 + 在别的功能里含一个更长说法」的问句；它不命中任何功能
    （或命中的不是自己）⇒ 这条说法**永远解不出自己** ⇒ 空登记。
    """
    out: List[str] = []
    maximal = _maximal_aliases(mod)
    for owner, alias in maximal:
        siblings = [a for o, a in maximal if o == owner and a != alias]
        if any(s in alias for s in siblings):
            continue          # 同功能内有别的说法能同样长度命中这句 ⇒ 不是死条目
        hit_fid = getattr(mod.resolve_feature(alias), "feature_id", None)
        if hit_fid == owner:
            continue
        longer = sorted(f"{o}#{a}" for o, a in maximal if o != owner and a in alias)
        out.append(
            f"{owner} 的说法 {alias!r} 是**空登记**：问「{alias}」时解到 {hit_fid!r}"
            f"（别的功能的更长说法 {longer} 抢先命中，或歧义）"
            " ⇒ 登记了但**永远解不出自己的功能**，删掉它或换成不与别家成子串的说法"
        )
    return out


def problems_feature_map_sync(mod, menu_ts_nodes) -> List[str]:
    """判据 9：「说法」⇄ `menu.ts` 的镜像必须一致（页面增删时判据要跟着红，不许静默漂移）。

    双向：
    ① **每个** `menu.ts` 导航节点都要有登记项以它为主节点（缺 ⇒ 该页问不到）；
    ② **每个**登记项的主节点都要在 `menu.ts` 里（多 ⇒ 编出来的页面），且它的菜单名那条说法
       必须**逐字等于** `menu.ts` 的 `name`（改名而不同批改登记表 ⇒ 静默漂移）。
    """
    out: List[str] = []
    ts_names = {n.name for n in menu_ts_nodes if n.path}
    registered: dict = {}
    for feature in mod.NAV_FEATURES:
        for group, label in feature.node_keys:
            node = mod.menu_node(group, label)
            if node is None:
                continue
            if not any(a == node.label for a in feature.aliases):
                out.append(
                    f"{feature.feature_id}：登记了节点「{node.label}」却**没有**一条说法逐字等于"
                    " 该菜单名 ⇒ 用户问菜单名时命中不了这一页（menu.ts 改名要同批改登记表）"
                )
            registered.setdefault(node.label, feature.feature_id)
    only_ts = sorted(ts_names - set(registered))
    if only_ts:
        out.append(f"menu.ts 里这些菜单项**没有任何登记项**（页面用户问不到）：{only_ts}")
    only_reg = sorted(set(registered) - ts_names)
    if only_reg:
        out.append(f"登记项引用的菜单名在 menu.ts 里不存在（编出来的页面）：{only_reg}")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 判据本体在**真对象**上的读数（未注入 ⇒ 必须全绿 —— 对照读数）
# ══════════════════════════════════════════════════════════════════════════════


class TestJudgementsOnRealObject:
    def test_judgement_1_paths_exist(self, nav, menu_ts_nodes, capsys):
        problems = problems_paths_exist(nav, menu_ts_nodes)
        with capsys.disabled():
            print(f"\n[MC-065] 判据 1 paths_exist problems={len(problems)}")
        assert problems == []

    def test_judgement_1b_coverage_and_order(self, nav, menu_ts_nodes, capsys):
        problems = problems_coverage(nav, menu_ts_nodes)
        with capsys.disabled():
            print(f"[MC-065] 判据 1b coverage problems={len(problems)}"
                  f" | MENU_TREE={len(nav.MENU_TREE)} menu.ts={len(menu_ts_nodes)}")
        assert problems == []

    def test_judgement_2_codes_are_real(self, nav, catalog, capsys):
        problems = problems_codes_real(nav, catalog)
        with capsys.disabled():
            print(f"[MC-065] 判据 2 codes_real problems={len(problems)} | 目录={len(catalog[0])} 码")
        assert problems == []

    def test_judgement_3_default_deny(self, nav, capsys):
        problems = problems_default_deny(nav)
        with capsys.disabled():
            print(f"[MC-065] 判据 3 default_deny problems={len(problems)}"
                  f" | NAV_FEATURES={len(nav.NAV_FEATURES)}")
        assert problems == []

    def test_judgement_4_role_trim(self, nav, capsys):
        problems = problems_role_trim(nav)
        with capsys.disabled():
            print(f"[MC-065] 判据 4 role_trim problems={len(problems)}")
        assert problems == []

    def test_judgement_5_citation(self, nav, capsys):
        problems = problems_citation(nav, _nav_module_source())
        with capsys.disabled():
            print(f"[MC-065] 判据 5 citation problems={len(problems)}")
        assert problems == []

    def test_judgement_6a_no_steps_surface(self, nav, capsys):
        problems = problems_no_steps_surface(nav)
        with capsys.disabled():
            print(f"[MC-065] 判据 6a no_steps_surface problems={len(problems)}")
        assert problems == []

    def test_judgement_6b_no_step_wording_in_source_and_notice(self, nav, capsys):
        """判据 6 的**源码/文案面**（运行时回复面在 `backend/ai-agent-service/tests/test_nav_guide.py`）。"""
        problems = problems_no_step_wording(_nav_tool_source())
        with capsys.disabled():
            print(f"[MC-065] 判据 6b no_step_wording(source) problems={len(problems)}")
        assert problems == []
        # 归属自证（不是恒真空断言）：受控词表真的会命中一个**故意写的**样本
        assert problems_no_step_wording("第一步：点击左侧菜单。") != [], (
            "受控步骤词表对本样本不敏感 ⇒ 判据退化成恒真空断言（先修词表）"
        )
        # 「问怎么做 ⇒ 如实说没有步骤级指引」的承载体（常量）必须在源码里
        guess_literals = [
            lit
            for lit in _module_string_literals(_nav_module_source())
            if "**不要**猜测页面，**不要**按猜测的页面口径作答。" in lit
        ]
        assert guess_literals, "登记表模块里没有「不要猜测页面」的如实告知口径字面量"
        assert any("不确定" in lit for lit in guess_literals), (
            "未登记告知口径里没有「（我）不确定」—— 用户裁定的第三句口径缺了"
        )

    def test_judgement_6c_aliases_grounded(self, nav):
        assert problems_aliases_grounded(nav) == []

    def test_judgement_7_every_node_has_a_hit_alias(self, nav):
        """判据 7（issue #6062）：每个菜单节点至少一条说法能命中它（那个页面问得到）。"""
        problems = problems_nodes_without_hit_alias(nav)
        assert problems == []

    def test_judgement_8_no_shadowed_alias(self, nav):
        """判据 8（issue #6062）：没有空登记 —— 每条说法都能解出它自己的功能。"""
        problems = problems_shadowed_aliases(nav)
        assert problems == []

    def test_judgement_9_feature_map_syncs_with_menu_ts(self, nav, menu_ts_nodes):
        """判据 9（issue #6062）：说法 ⇄ `menu.ts` 镜像双向一致（页面增删/改名 ⇒ 红）。"""
        problems = problems_feature_map_sync(nav, menu_ts_nodes)
        assert problems == []

    def test_measured_failure_common_phrasing_resolves(self, nav):
        """🔴 **实测失败样例**（2026-10-02 B 端真实评测 `normal` 档 `nav_guide!nav_not_registered ×1`）：
        用户输入「怎么给员工开账号」在修复前 ⇒ `resolve_feature` 返回 `None` ⇒ agent 只能含糊其辞。
        修后 ⇒ 命中 `employees`，答案给出**页面位置**且**不含任何操作步骤**。
        """
        for question in ("怎么给员工开账号", "那我要怎么才能给员工开账号？"):
            hit = nav.resolve_feature(question)
            assert hit is not None and hit.feature_id == "employees", (
                f"「{question}」仍未登记 ⇒ 用户问不到（实测失败的复现）"
            )
        answer = nav.build_navigation_answer("怎么给员工开账号", ["employee:list"])
        payload = answer.to_data()
        assert [p["path"] for p in payload["pages"]] == ["/employees"]
        assert payload["citation"] == "登记项 #employees → 菜单节点 菜单组「员工管理」"
        assert "employees" in payload["featureId"]
        # 同一句问句必须仍然**不含步骤**（结构面：键白名单里没有 steps；文本面：无受控步骤词）
        assert set(payload) == ALLOWED_DATA_KEYS
        rendered = answer.render()
        assert not [w for w in STEP_WORDS if w in rendered], "导航答案里出现步骤词"

    def test_p2_interface_is_available(self, nav):
        """**P2 预留接口**（本包只提供，不判推送）：这一页有什么 + 哪些角色能看。"""
        all_paths = {n.path for n in nav.visible_nodes(["*"])}
        assert all_paths == {n.path for n in nav.MENU_TREE}
        visible = {n.path for n in nav.visible_nodes(["order:list", "dashboard:view"])}
        assert visible == {"/orders", "/shipments", "/notifications", "/dashboard", "/briefing"}
        nodes = nav.nodes_for_feature("production-process")
        assert [(n.path, n.permission_code) for n in nodes] == [("/production/routings", "production:view")]
        assert nav.nodes_for_feature("no-such-feature") == ()


# ══════════════════════════════════════════════════════════════════════════════
# 注入式红证：每条判据都要能红（§23 G7 前提自证：注入生效 + 判据看见新对象）
# ══════════════════════════════════════════════════════════════════════════════


class TestEveryJudgementCanGoRed:
    def test_judgement_1_red_on_fake_path(self, nav, menu_ts_nodes, tmp_path, capsys):
        mutated = _load_mutated(
            tmp_path,
            lambda s: s.replace(
                'MenuNode("production-center", "工艺配置", "/production/routings", "production:view")',
                'MenuNode("production-center", "工艺配置", "/production/wrong", "production:view")',
            ),
        )
        ts_paths = {n.path for n in menu_ts_nodes}
        assert "/production/wrong" not in ts_paths, "前提自证失败：注入的假路径竟然真的在 menu.ts 里"
        problems = problems_paths_exist(mutated, menu_ts_nodes)
        with capsys.disabled():
            print(f"\n[MC-065][红证1] 假路径 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 1 没看见注入的假路径 ⇒ 空断言"
        assert problems_paths_exist(nav, menu_ts_nodes) == [], "对照：真模块必须绿"

    def test_judgement_1b_red_on_missing_node(self, nav, tmp_path, capsys):
        """删掉一条登记节点 ⇒ **导入期自检**当场拦下（fail-closed 的正面读数）。

        ⚠️ 这条注入的**红读数**是「模块 import 就抛 `MenuNavigatorError`」（登记表自检的分内事），
        不是判据函数的输出 —— 两者都在下面显式给出，不混为一谈。
        """
        # 红读数 = 「模块 import 就抛 `MenuNavigatorError`」—— 读数与**抛的是哪一个**都记下来
        caught: Optional[BaseException] = None
        try:
            _load_mutated(
                tmp_path,
                lambda s: s.replace(
                    '    MenuNode("trade-center", "订单列表", "/orders", "order:list"),\n', ""
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 读数就是「抛了什么」
            caught = exc
        with capsys.disabled():
            print(f"[MC-065][红证1b] 删节点 ⇒ 导入期自检抛 {type(caught).__name__}: {str(caught)[:90]}")
        assert "订单列表" in str(caught), (
            f"删掉登记节点后**没有**被具名拦下（caught={caught!r}）⇒ fail-closed 失效"
        )

    def test_judgement_1b_red_on_coverage_gap(self, nav, tmp_path, capsys):
        """判据本体（`problems_coverage`）在**内存桩**上的判别力：缺节点 / 多节点 / 换序都红。"""
        def _node(path, group="g", label="l", code=""):
            return type("N", (), {"path": path, "group": group, "label": label,
                                  "permission_code": code})()

        class _Stub:
            """内存替身：`problems_coverage` 只看 `MENU_TREE` 与 `MENU_TREE_ORDER_LOCKED`。"""

            MENU_TREE: Tuple[Any, ...] = ()
            MENU_TREE_ORDER_LOCKED: Tuple[Any, ...] = ()

        _Stub.MENU_TREE = (_node("/dashboard"), _node("/orders"))
        _Stub.MENU_TREE_ORDER_LOCKED = tuple(
            (n.group, n.label, n.path, n.permission_code) for n in _Stub.MENU_TREE
        )
        ts = [_node("/dashboard"), _node("/orders")]
        assert problems_coverage(_Stub, ts) == [], "对照：完全一致时必须绿"

        _Stub.MENU_TREE = (_node("/dashboard"),)
        _Stub.MENU_TREE_ORDER_LOCKED = tuple(
            (n.group, n.label, n.path, n.permission_code) for n in _Stub.MENU_TREE
        )
        missing = problems_coverage(_Stub, ts)
        assert any("/orders" in p for p in missing), f"缺节点没被具名报出：{missing}"

        _Stub.MENU_TREE = (_node("/orders"), _node("/dashboard"))
        _Stub.MENU_TREE_ORDER_LOCKED = tuple(
            (n.group, n.label, n.path, n.permission_code) for n in _Stub.MENU_TREE
        )
        reordered = problems_coverage(_Stub, ts)
        with capsys.disabled():
            print(f"[MC-065][红证1b] 内存桩：缺节点 {len(missing)} 条 / 换序 {len(reordered)} 条")
        assert any("顺序" in p for p in reordered), f"换序没被报出：{reordered}"
        assert problems_coverage(nav, []) != [], "对照：空的 menu.ts 节点集必须判红（防空跑）"

    def test_judgement_1b_red_on_reorder(self, nav, menu_ts_nodes, tmp_path, capsys):
        mutated = _load_mutated(
            tmp_path,
            lambda s: s.replace(
                '    MenuNode("workspace", "经营看板", "/dashboard", "dashboard:view"),\n'
                '    MenuNode("workspace", "每日简报", "/briefing", "dashboard:view"),\n',
                '    MenuNode("workspace", "每日简报", "/briefing", "dashboard:view"),\n'
                '    MenuNode("workspace", "经营看板", "/dashboard", "dashboard:view"),\n',
            ),
        )
        assert [n.path for n in mutated.MENU_TREE][:2] == ["/briefing", "/dashboard"], "前提自证失败"
        assert problems_coverage(mutated, menu_ts_nodes), "判据 1b 没看见顺序漂移 ⇒ 空断言"

    def test_judgement_2_red_on_ghost_code(self, nav, catalog, tmp_path, capsys):
        reg, perm = catalog
        mutated = _load_mutated(
            tmp_path,
            lambda s: s.replace(
                'MenuNode("org-center", "岗位权限", "/roles", "system:view")',
                'MenuNode("org-center", "岗位权限", "/roles", "ghost:code")',
            ),
        )
        assert "ghost:code" not in set(reg) | set(perm), "前提自证失败：假码竟在权限目录里"
        assert "ghost:code" in {n.permission_code for n in mutated.MENU_TREE}, "前提自证失败：假码没进登记表"
        problems = problems_codes_real(mutated, catalog)
        with capsys.disabled():
            print(f"[MC-065][红证2] 假权限码 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 2 没看见目录外的权限码 ⇒ 空断言"

    def test_judgement_3_red_on_guessing(self, nav, tmp_path, capsys):
        def mutate(source: str) -> str:
            marker = "    if not hits:\n        return None\n"
            assert marker in source, "注入锚不存在 ⇒ 红证是空断言（同步本判据）"
            return source.replace(marker, "    if not hits:\n        return NAV_FEATURES[0]\n")

        mutated = _load_mutated(tmp_path, mutate)
        assert mutated.resolve_feature("皮料怎么算价") is not None, "前提自证失败：注入没生效"
        assert nav.resolve_feature("皮料怎么算价") is None, "对照：真模块必须不命中"
        problems = problems_default_deny(mutated)
        with capsys.disabled():
            print(f"[MC-065][红证3] 未命中改成猜 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 3 没看见「猜了一条」⇒ 空断言"

    def test_judgement_4_red_on_dropping_trim(self, nav, tmp_path, capsys):
        def mutate(source: str) -> str:
            marker = "(granted if has_permissions((node.permission_code,), permissions) else denied).append(node)"
            assert marker in source, "注入锚不存在 ⇒ 红证是空断言（同步本判据）"
            return source.replace(marker, "granted.append(node)")

        mutated = _load_mutated(tmp_path, mutate)
        assert mutated.build_navigation_answer("工艺配置在哪", ["order:list"]).to_data()["pages"], "前提自证失败"
        problems = problems_role_trim(mutated)
        with capsys.disabled():
            print(f"[MC-065][红证4] 去掉裁剪 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 4 没看见越权泄露 ⇒ 空断言"

    def test_judgement_4b_red_on_role_parameter(self, nav, tmp_path, capsys):
        def mutate(source: str) -> str:
            marker = "def build_navigation_answer(query: str, permissions: Any) -> NavigationAnswer:"
            assert marker in source, "注入锚不存在 ⇒ 红证是空断言（同步本判据）"
            return source.replace(
                marker, "def build_navigation_answer(query: str, permissions: Any, role: str = \"\") -> NavigationAnswer:"
            )

        mutated = _load_mutated(tmp_path, mutate)
        assert list(inspect.signature(mutated.build_navigation_answer).parameters) == [
            "query", "permissions", "role",
        ], "前提自证失败：role 形参没加上"
        problems = problems_role_trim(mutated)
        with capsys.disabled():
            print(f"[MC-065][红证4b] 加 role 形参 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 4 没看见「裁剪可能读客户端 role」⇒ 空断言"

    def test_judgement_5_red_on_weak_citation(self, nav, tmp_path, capsys):
        def mutate(source: str) -> str:
            marker = '        return f"登记项 #{self.feature_id} → 菜单节点 {nodes}"'
            assert marker in source, "注入锚不存在 ⇒ 红证是空断言（同步本判据）"
            return source.replace(marker, '        return "依据：米宝的导航指引"')

        mutated = _load_mutated(tmp_path, mutate)
        assert "菜单节点" not in mutated.build_navigation_answer("商品管理在哪", ["product:list"]).citation
        problems = problems_citation(mutated, mutate(_nav_module_source()))
        with capsys.disabled():
            print(f"[MC-065][红证5] 摘掉菜单节点 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 5 没看见 citation 不可溯 ⇒ 空断言"

    def test_judgement_6a_red_on_steps_key(self, nav, tmp_path, capsys):
        def mutate(source: str) -> str:
            marker = '            "citation": self.citation,\n        }'
            assert marker in source, "注入锚不存在 ⇒ 红证是空断言（同步本判据）"
            return source.replace(
                marker, '            "citation": self.citation,\n            "steps": ["先点这里"],\n        }'
            )

        mutated = _load_mutated(tmp_path, mutate)
        assert set(mutated.build_navigation_answer("商品管理在哪", ["product:list"]).to_data()) - ALLOWED_DATA_KEYS == {"steps"}, "前提自证失败"
        problems = problems_no_steps_surface(mutated)
        with capsys.disabled():
            print(f"[MC-065][红证6a] data 多出 steps ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 6a 没看见注入的 steps 键 ⇒ 空断言"

    def test_judgement_6b_red_on_step_wording(self, nav, capsys):
        """红证：在**工具源码**的文本面塞一句祈使步骤 ⇒ 判据必报。

        ⚠️ 本 job 跑不了工具（无 ai-agent 依赖）⇒ 注入的是**源码文本**；
        「真跑工具的回复里也没有步骤词」由
        `backend/ai-agent-service/tests/test_nav_guide.py::TestExecuteSemantics` 判（同名两臂不重复）。
        """
        source = _nav_tool_source()
        assert problems_no_step_wording(source) == [], "对照：真源码必须绿"
        injected = source.replace(
            "用户问「怎么做」时，给导航答案 + **如实说「我没有步骤级指引」**。",
            "用户问「怎么做」时，第一步先点击左侧菜单再按下确认按钮。",
            1,
        )
        assert injected != source, "注入锚不存在 ⇒ 红证是空断言（同步本判据）"
        problems = problems_no_step_wording(injected)
        with capsys.disabled():
            print(f"[MC-065][红证6b] 源码塞步骤 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 6b 没看见注入的步骤词 ⇒ 空断言"

    def test_judgement_6c_red_on_free_synonym_self_check(self, nav, tmp_path, capsys):
        """上游（导入期自检）的那一半：把别名换成自由同义词 ⇒ **模块 import 就抛**。"""
        caught: Optional[BaseException] = None
        try:
            _load_mutated(
                tmp_path,
                lambda s: s.replace(
                    'NavFeature("orders", "订单列表（订单）", (("trade-center", "订单列表"),), ("订单列表", "订单"))',
                    'NavFeature("orders", "订单列表（订单）", (("trade-center", "订单列表"),), ("订单列表", "库存盘点"))',
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 读数就是「抛了什么」
            caught = exc
        with capsys.disabled():
            print(f"[MC-065][红证6c] 自由同义词 ⇒ 导入期自检抛 {type(caught).__name__}: {str(caught)[:90]}")
        assert "库存盘点" in str(caught), (
            f"自由同义词**没有**被具名拦下（caught={caught!r}）⇒ 别名约束失效"
        )

    def test_judgement_6c_red_on_free_synonym_judgement(self, nav, capsys):
        """下游（判据本体）的那一半：在**内存桩**上让别名不落地 ⇒ `problems_aliases_grounded` 必报。"""
        class _Stub:
            @staticmethod
            def menu_node(group, label):
                return type("N", (), {"label": label})()

        _Stub.NAV_FEATURES = (
            type(
                "F",
                (),
                {
                    "feature_id": "products",
                    "node_keys": (("(一级独立项)", "商品管理"),),
                    "label": "商品管理",
                    "aliases": ("商品管理", "库存盘点"),
                },
            )(),
        )
        problems = problems_aliases_grounded(_Stub)
        with capsys.disabled():
            print(f"[MC-065][红证6c] 内存桩自由同义词 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert any("库存盘点" in p for p in problems), f"不受菜单名约束的别名没被报出：{problems}"
        assert problems_aliases_grounded(nav) == [], "对照：真模块必须绿"

    def test_judgement_7_red_on_node_without_alias(self, nav, tmp_path, capsys):
        """判据 7 红证（issue #6062）：**加一个没有任何说法的节点** ⇒ 必须具名报出它。

        为什么用**新节点**注入：`problems_nodes_without_hit_alias` 的输入是
        「`MENU_TREE` 的每个节点 ⇄ 登记项的 aliases」，把一条登记的 aliases 摘空会被
        **导入期自检**先拦下（那是上游那一半）；要证明**判据本体**有判别力，就得构造
        「节点在、说法不在」的形态 —— 而 `MENU_TREE` 与 `MENU_TREE_ORDER_LOCKED` 被其余判据锁着，
        故这里在**内存桩**上做（与既有 `problems_coverage` 的内存桩臂同法）。
        """
        def _node(label, path):
            return type("N", (), {"group": "g", "label": label, "path": path,
                                  "permission_code": ""})()

        class _Stub:
            MENU_TREE: Tuple[Any, ...] = (_node("员工管理", "/employees"), _node("新页面", "/new-page"))
            NAV_FEATURES = (
                type("F", (), {"feature_id": "employees", "node_keys": (("g", "员工管理"),),
                               "aliases": ("员工管理",), "label": "员工管理"})(),
            )
            menu_node = staticmethod(lambda group, label: _node(label, "/x"))

        problems = problems_nodes_without_hit_alias(_Stub)
        with capsys.disabled():
            print(f"[MC-070][红证7] 无说法的节点 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert any("新页面" in p for p in problems), f"无说法的节点没被具名报出：{problems}"
        assert problems_nodes_without_hit_alias(nav) == [], "对照：真模块必须绿"

    def test_judgement_8_red_on_shadowed_alias(self, nav, tmp_path, capsys):
        """判据 8 红证（issue #6062）：**加一条被别的功能更长说法遮蔽的说法** ⇒ 必须报出。

        红证两臂（都要）：
        ① **判据本体**（内存桩）：`发货单` 功能登记 `"出库"`，另一个功能登记 `"出库管理"` ⇒ 报出；
        ② **上游自检**（真模块注入）：把别家的说法改成一个**包含**它的更长说法 ⇒ 导入期即抛
           `MenuNavigatorError`（fail-closed：空登记不生效，不是被放行）。
        """
        # ① **前置（对照）**：别的功能没有那条更长说法时 ⇒ 不是死条目
        class _Clean:
            NAV_FEATURES = (
                type("F", (), {"feature_id": "shipments", "node_keys": (("g", "发货单"),),
                               "aliases": ("发货单", "出库"), "label": "发货单（出库）"})(),
                type("F", (), {"feature_id": "other", "node_keys": (("g", "入库单"),),
                               "aliases": ("入库单",), "label": "入库单（入库）"})(),
            )

            @staticmethod
            def resolve_feature(q):
                """与 `resolve_feature` 的最长命中口径**同形**的最小版（歧义 ⇒ None）。"""
                hits = [
                    (len(a), f) for f in _Clean.NAV_FEATURES for a in f.aliases if a in q
                ]
                if not hits:
                    return None
                longest = max(n for n, _ in hits)
                winners = {f.feature_id for n, f in hits if n == longest}
                return hits[0][1] if len(winners) == 1 else None

        assert problems_shadowed_aliases(_Clean) == [], "对照：没有遮蔽时不许报红"

        # ② **坏形态**：别的功能登记了 `发货单列表`（含 `发货单`）⇒ shipments 的 `发货单` 永远赢不了
        class _Shadowed:
            NAV_FEATURES = (
                type("F", (), {"feature_id": "shipments", "node_keys": (("g", "发货单"),),
                               "aliases": ("发货单", "出库"), "label": "发货单（出库）"})(),
                type("F", (), {"feature_id": "other", "node_keys": (("g", "入库单"),),
                               "aliases": ("入库单", "发货单列表"), "label": "入库单（入库/发货单列表）"})(),
            )

            @staticmethod
            def resolve_feature(q):
                """与 `resolve_feature` 的最长命中口径**同形**的最小版（歧义 ⇒ None）。"""
                hits = [
                    (len(a), f)
                    for f in _Shadowed.NAV_FEATURES
                    for a in f.aliases
                    if a in q
                ]
                if not hits:
                    return None
                longest = max(n for n, _ in hits)
                winners = {f.feature_id for n, f in hits if n == longest}
                return hits[0][1] if len(winners) == 1 else None

        problems = problems_shadowed_aliases(_Shadowed)
        with capsys.disabled():
            print(f"[MC-070][红证8] 内存桩：被遮蔽的说法 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert any("发货单列表" in p and "shipments#发货单" in p for p in problems), (
            f"被遮蔽的说法没被报出：{problems}"
        )
        assert problems_shadowed_aliases(nav) == [], "对照：真模块必须绿"

        # ② 上游那一半：真模块里把别家的说法改长到包含它 ⇒ 导入期自检抛
        caught: Optional[BaseException] = None
        try:
            _load_mutated(
                tmp_path,
                lambda s: s.replace(
                    'NavFeature("inbound-orders", "入库单（入库）", (("inventory-center", "入库单"),), ("入库单", "入库"))',
                    'NavFeature("inbound-orders", "入库单（入库/发货单列表）", (("inventory-center", "入库单"),), ("入库单", "发货单列表"))',
                    1,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 读数就是「抛了什么」
            caught = exc
        with capsys.disabled():
            print(f"[MC-070][红证8] 上游自检 ⇒ {type(caught).__name__}: {str(caught)[:110]}")
        assert caught is not None and "发货单" in str(caught), (
            f"被遮蔽的说法**没有**被导入期自检具名拦下（caught={caught!r}）⇒ fail-closed 失效"
        )

    def test_judgement_9_red_on_mirror_drift(self, nav, menu_ts_nodes, tmp_path, capsys):
        """判据 9 红证（issue #6062）：删一个登记项 / 改一条说法与菜单名不一致 ⇒ 必须报出。"""
        class _Stub:
            NAV_FEATURES = (
                type("F", (), {"feature_id": "employees", "node_keys": (("org-center", "员工管理"),),
                               "aliases": ("员工管理",), "label": "员工管理"})(),
            )
            MENU_TREE = (
                type("N", (), {"group": "org-center", "label": "员工管理",
                               "path": "/employees", "permission_code": "employee:list"})(),
                type("N", (), {"group": "workspace", "label": "经营看板",
                               "path": "/dashboard", "permission_code": "dashboard:view"})(),
            )
            menu_node = staticmethod(
                lambda group, label: type("N", (), {"label": label, "path": "/x"})(),
            )

        problems = problems_feature_map_sync(_Stub, menu_ts_nodes)
        with capsys.disabled():
            print(f"[MC-070][红证9] 镜像漂移 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert any("经营看板" in p for p in problems), f"未登记的菜单项没被报出：{problems}"
        assert problems_feature_map_sync(nav, menu_ts_nodes) == [], "对照：真模块必须绿"

        # 另一半：登记项**没有**一条逐字等于菜单名的说法（menu.ts 改名没同批改）⇒ 也红
        class _Renamed:
            NAV_FEATURES = (
                type("F", (), {"feature_id": "employees", "node_keys": (("org-center", "员工管理"),),
                               "aliases": ("账号开通",), "label": "员工管理（账号开通）"})(),
            )
            MENU_TREE = _Stub.MENU_TREE
            menu_node = staticmethod(
                lambda group, label: type("N", (), {"label": label, "path": "/x"})(),
            )

        renamed = problems_feature_map_sync(_Renamed, menu_ts_nodes)
        with capsys.disabled():
            print(f"[MC-070][红证9] 说法与菜单名不一致 ⇒ problems={len(renamed)} :: {renamed[:1]}")
        assert any("逐字等于" in p for p in renamed), f"改名的漂移没被报出：{renamed}"

        # ③ 真模块注入：删掉一条登记项 ⇒ 导入期自检抛（那个菜单节点没人登记 = 问不到）
        caught: Optional[BaseException] = None
        try:
            _load_mutated(
                tmp_path,
                lambda s: s.replace(
                    '    NavFeature("notifications", "通知中心（消息）",'
                    ' ((STANDALONE_GROUP, "通知中心"),), ("通知中心", "消息")),\n',
                    "",
                    1,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 读数就是「抛了什么」
            caught = exc
        with capsys.disabled():
            print(f"[MC-070][红证9] 删登记项 ⇒ 上游自检 {type(caught).__name__}: {str(caught)[:110]}")
        assert caught is not None and "通知中心" in str(caught), (
            f"删掉登记项后没有被具名拦下（caught={caught!r}）⇒ fail-closed 失效"
        )

    def test_judgement_3b_red_on_stale_unregistered_sample(self, nav, monkeypatch, capsys):
        """判据 3 的**样本前置**红证（issue #6062）：样本表里出现含已登记说法的问句 ⇒ 具名报出。

        这一条治的是「**读数与它声称的对象不是同一个**」：样本自己过期（含了刚登记的说法）时，
        判据会因错的原因变红/变绿。红证 = 把一条含「订单」的问句塞回样本表 ⇒ 判据报「样本过期」。
        """
        assert problems_default_deny(nav) == [], "对照：真样本表必须绿"
        monkeypatch.setattr(
            sys.modules[__name__],
            "UNREGISTERED_QUESTIONS",
            ("怎么导出订单 Excel", "皮料怎么算价"),
        )
        problems = problems_default_deny(nav)
        with capsys.disabled():
            print(f"[MC-070][红证3b] 过期样本 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert any("样本过期" in p and "订单" in p for p in problems), (
            f"过期样本没被具名报出：{problems}"
        )

    def test_control_comment_only_change_stays_green(self, nav, menu_ts_nodes, tmp_path):
        """**对照读数**：只改一行注释 ⇒ 所有判据**仍然全绿**（判据不是「见改动就红」）。"""
        mutated = _load_mutated(
            tmp_path,
            lambda s: s.replace(
                '"""米宝「导航类」指引的真值源',
                '"""米宝「导航类」指引的真值源（本行是注入的注释）',
                1,
            ),
        )
        assert problems_paths_exist(mutated, menu_ts_nodes) == []
        assert problems_coverage(mutated, menu_ts_nodes) == []
        assert problems_codes_real(mutated, CATALOG_UNDER_TEST) == []
        assert problems_default_deny(mutated) == []
        assert problems_role_trim(mutated) == []
        assert problems_citation(mutated, _nav_module_source()) == []
        assert problems_no_steps_surface(mutated) == []
        assert problems_aliases_grounded(mutated) == []
        assert problems_nodes_without_hit_alias(mutated) == []
        assert problems_shadowed_aliases(mutated) == []
        assert problems_feature_map_sync(mutated, menu_ts_nodes) == []


# ══════════════════════════════════════════════════════════════════════════════
# 类级元守卫：工具面（注册 / 门面导出 / 只读 / 权限锚 / 纯本地 / skill 绑定）
# ══════════════════════════════════════════════════════════════════════════════


class TestToolSurface:
    """工具面（**全部静态**：本 job 没有 ai-agent 依赖 ⇒ 只扫源码；运行时行为在 `test_nav_guide.py`）。"""

    def test_tool_source_declares_read_only_and_no_permission_code(self, nav):
        attrs = _nav_tool_class_attrs()
        assert attrs.get("name") == "nav_guide", "类里没声明 `name`"
        assert attrs.get("read_only") is True, "导航指引是纯本地只读能力：`read_only` 必须为 True"
        assert attrs.get("destructive") is False
        assert attrs.get("required_permissions") == [], (
            "纯本地工具（零 admin-api 调用点）不声明权限码 —— 与 `interact` / `image_recognize` 同口径"
        )

    def test_registered_in_registry_source(self):
        """注册面（**扫源码**）：`registry.py` 里 import + register 两处，缺一不可。"""
        text = REGISTRY_SOURCE.read_text(encoding="utf8")
        assert "from app.tools.nav_guide import NavGuideTool" in text, "registry 里没有 import 行"
        assert "registry.register(NavGuideTool())" in text, "registry 里没有 register 行 ⇒ 模型不可达"

    def test_exported_from_the_facade_source(self):
        """门面面（**扫源码**）：`app/tools/__init__.py` 里 import + `__all__` 都有。"""
        text = FACADE_SOURCE.read_text(encoding="utf8")
        assert "from app.tools.nav_guide import NavGuideTool" in text, "门面里没有 import 行"
        assert '"NavGuideTool"' in text, "`__all__` 里没有 NavGuideTool ⇒ 门面完整性判据会红"

    def test_bound_to_a_b_side_skill_source(self):
        """可达性（**扫源码**）：`general` 兜底 skill 的工具清单里有它。"""
        text = GENERAL_SKILL_SOURCE.read_text(encoding="utf8")
        assert '"nav_guide"' in text, "`general_agent.py` 的 `GENERAL_TOOLS` 里没有 nav_guide ⇒ 模型不可达"

    def test_tool_module_has_no_http_call_points_static(self):
        """纯本地（**AST**）：没有 admin-api 客户端调用点，也没有 HTTP 动词调用。"""
        source = _nav_tool_source()
        assert "get_admin_api_client" not in source
        tree = ast.parse(source)
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not ({"get", "post", "put", "patch", "delete"} & calls), (
            f"nav_guide 里出现 HTTP 调用形态 {sorted(calls)} —— 它必须是纯本地工具"
        )

    def test_data_keys_and_notice_are_static_facts(self, nav):
        """判据 6 的**静态承载体**：载荷键白名单 + 「没有步骤级指引」文案都在源码里。"""
        module = _nav_module_source()
        outer, inner = _to_data_literal_keys(module)
        assert outer == set(ALLOWED_DATA_KEYS), (
            f"`to_data()` 的最外层载荷键集 = {sorted(outer)}，与白名单 {sorted(ALLOWED_DATA_KEYS)} 不等"
            " —— 新增键必须同批登记（`steps` 一律不得进这个载荷）"
        )
        assert inner == set(ALLOWED_PAGE_KEYS), (
            f"页面项键集 = {sorted(inner)}，与白名单 {sorted(ALLOWED_PAGE_KEYS)} 不等"
        )
        # 「没有步骤级指引」的**承载体在工具**的 message/suggestion 构造点（而不是登记表模块）
        assert any("没有步骤级指引" in lit for lit in _module_string_literals(_nav_tool_source())), (
            "工具源码里没有「我没有步骤级指引」的如实告知口径"
        )

    def test_tool_description_is_in_the_model_surface(self):
        """`description` 会进模型上下文 ⇒ 它也在判据 6 的射程内（扫源码即可，不必 import）。"""
        source = _nav_tool_source()
        assert "【触发】" in source and "【参数】" in source, "description 的形态变了（工具面判据会红）"
