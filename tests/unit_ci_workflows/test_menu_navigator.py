# case_ids: MC-058
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
| 6 | 🔴 **禁止编步骤**：结构与文本两层（`problems_no_steps_surface` / `problems_no_step_wording`） | 往 `data` 加 `steps` / 改用 `render()` 塞步骤词 ⇒ 红 |
| 6b | 别名必须是**登记菜单名的一部分**（`problems_aliases_grounded`） | 换成自由同义词 ⇒ 红 |

## 复用而不造第二套（§17.3）

- **`menu.ts` 解析器** = `tests/unit_ci_workflows/test_agent_permission_parity.parse_menu_ts_nodes`
  （按**路径**动态加载 —— 本文件与它在同一层 `tests/`，`from` 不可达，故走 `spec_from_file_location`）；
- **权限目录解析器** = 同模块的 `parse_catalog`（两处目录**逐值相等**也由它核）；
- **权限判定口径** = `app.context.menu_navigator.has_permissions`，与 `page_registry.has_permissions` /
  `frontend/admin-web/src/lib/menu-nav.ts` 的 `hasPermission` 同族（`*` 通配 / 无码不设限）。

## 明确不在本文件射程（照实登记）

- **LLM 是否真的引用了 citation / 是否真的没编步骤**（行为面）—— 按 `migao-dev-flow` §13.2 映射到
  `.github/cases/misc.yml` 的 MC-058 走评测；本文件判的是**结构面**（真值源、裁剪、citation、无 steps 字段），
  即「可追溯、不可编」的**必要条件**；
- **P2（主动新手引导）的推送面**：本包只提供 `visible_nodes` / `nodes_for_feature` 接口，**不判推送**。
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import json
import os
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

# `ai-agent-service` 根不在本仓根的 `sys.path` 上（工具面判据要 import `app.*`），
# 且必须**插在** `sys.path` 前部（同名的 `app` 包不存在于仓根，故无遮蔽风险）。
sys.path.insert(0, str(AI_SERVICE))

# ⚠️ 本文件在 `tests/unit_ci_workflows/`（**不是** `ai-agent-service/tests/`）⇒ 那里 conftest 的
# 「导入 `app.*` 前注入必需环境变量」**不生效**（`Settings` 的部分字段无默认值，实例化即抛）。
# 这里只补同一份**缺失键**（`setdefault`，不覆盖任何已有值）—— 与
# `backend/ai-agent-service/tests/conftest.py` 的口径同源。
for _key, _value in (
    ("DEBUG", "true"),
    ("ADMIN_API_BASE_URL", "http://admin-api:8080"),
    ("SERVICE_TOKEN", "test-service-token"),
    ("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nTESTKEY\n-----END PUBLIC KEY-----"),
    ("LOGISTICS_API_URL", "https://wuliu.market.alicloudapi.com/kdi"),
    ("LOGISTICS_APPCODE", "test-appcode"),
    ("SSE_TIMEOUT", "300"),
    ("SSE_PING_INTERVAL", "30"),
    ("CORS_ALLOWED_ORIGINS", "http://localhost:3000"),
    ("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db"),
    ("REDIS_URL", "redis://localhost:6379/0"),
):
    os.environ.setdefault(_key, _value)

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
    "怎么导出订单 Excel",
    "米宝你能帮我做什么",
    "帮我看看这个怎么弄",
    "这些数字是什么意思",
    "",
    "皮料怎么算价",
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
    sys.path.insert(0, str(AI_SERVICE))
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
    """判据 3：未登记的问题 ⇒ `registered is False`、**零路径零码**，且如实说明未登记。"""
    out: List[str] = []
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


def problems_citation(mod) -> List[str]:
    """判据 5：citation 必须**引登记项 → 菜单节点**；未登记 ⇒ 如实说明「（无）」。"""
    out: List[str] = []
    answer = mod.build_navigation_answer("商品管理在哪", ["product:list"])
    citation = answer.to_data()["citation"]
    node = mod.menu_node(mod.STANDALONE_GROUP, "商品管理")
    if node is None:
        out.append("`menu_node(STANDALONE_GROUP, '商品管理')` 查不到 —— 登记表被改坏了")
        return out
    if citation != "登记项 #products → 菜单节点 一级项「商品管理」":
        out.append(f"citation 不可溯到「登记项 → 菜单节点」：{citation!r}")
    if "菜单节点" not in citation:
        out.append("citation 里没有「菜单节点」⇒ 无法从答案追回登记表")
    if mod.menu_node("no-such-group", "商品管理") is not None:
        out.append("未登记节点竟返回了节点对象（默认拒绝失效）")
    unregistered = mod.build_navigation_answer("怎么导出订单", ["*"]).citation
    if "（无）" not in unregistered:
        out.append(f"未登记问题的 citation 没有如实说明未登记：{unregistered!r}")
    return out


def problems_no_steps_surface(mod) -> List[str]:
    """判据 6（**结构面**）：`data` 键白名单 —— `steps` 这类字段结构上进不来。"""
    out: List[str] = []
    for feature in mod.NAV_FEATURES:
        payload = mod.build_navigation_answer(feature.label, ["*"]).to_data()
        extra = sorted(set(payload) - ALLOWED_DATA_KEYS)
        if extra:
            out.append(
                f"{feature.feature_id}：data 多出未登记的键 {extra} —— "
                "`steps` / 操作说明 / 图文一律不得进这个载荷"
            )
        for page in payload["pages"]:
            page_extra = sorted(set(page) - ALLOWED_PAGE_KEYS)
            if page_extra:
                out.append(f"{feature.feature_id}：页面项多出未登记的键 {page_extra}")
    unregistered = mod.build_navigation_answer("随便问点什么", ["*"]).to_data()
    extra = sorted(set(unregistered) - ALLOWED_DATA_KEYS)
    if extra:
        out.append(f"未登记回答的 data 多出未登记的键 {extra}")
    return out


def _tool_replies(build: Callable[[str, Any], Any]) -> List[Tuple[str, Optional[str], Optional[str], Any]]:
    """真跑一遍工具 —— `build` 就是被测的 `build_navigation_answer`（真模块或注入版）。

    **接线面直连**（§28.2「判据绿 ≠ 接线在」）：把 `app.tools.nav_guide` 里那个名字换成被测函数，
    再**真跑** `NavGuideTool.execute` —— 这样「工具确实用了本模块的登记表」是被测的，
    而不是被假设的（否则注入版与工具根本没关系 ⇒ 红证恒绿）。
    """
    from unittest.mock import patch

    import app.tools.base as base_mod
    import app.tools.nav_guide as tool_mod

    tool = tool_mod.NavGuideTool()
    ctx = base_mod.ToolContext(tenant_id=1, user_id="u1", role="admin", permissions=["*"])
    questions = [f.label for f in NAV_FEATURES_OF(build)] + ["怎么导出订单", "这个怎么操作"]
    out: List[Tuple[str, Optional[str], Optional[str], Any]] = []
    with patch.object(tool_mod, "build_navigation_answer", build):
        for question in questions:
            result = asyncio.run(tool.execute(ctx, question=question))
            out.append((question, result.message, result.suggestion, result.data))
    return out


def NAV_FEATURES_OF(build: Callable[[str, Any], Any]) -> Any:
    """从被测的 `build_navigation_answer` 反查它所属模块的 `NAV_FEATURES`（注入版/真版通用）。"""
    return sys.modules[build.__module__].NAV_FEATURES


def problems_no_step_wording(mod, replies) -> List[str]:
    """判据 6（**文本面 + 接线面**）：工具的任何回答都不得出现步骤词，且不得含 steps 字段。"""
    out: List[str] = []
    if not replies:
        out.append("工具回复为空 ⇒ 判据会空跑（fail-closed）")
    for question, message, suggestion, data in replies:
        blob = json.dumps({"message": message, "suggestion": suggestion, "data": data}, ensure_ascii=False)
        for word in STEP_WORDS:
            if word in blob:
                out.append(
                    f"工具回答「{question}」里出现了步骤词「{word}」—— "
                    "第一批**只做导航类**：禁止把工具返回扩写成操作步骤（用户裁定 2026-10-02）"
                )
        if "steps" in json.dumps(data or {}, ensure_ascii=False):
            out.append(f"工具回答「{question}」的 data 里出现了 `steps` 字段")
    return out


def problems_aliases_grounded(mod) -> List[str]:
    """判据 6b：别名必须是某个被登记菜单名的一部分 ⇒ 别名表不可能退化成同义词词典。"""
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
            if not any(alias in label or label in alias for label in labels):
                out.append(
                    f"{feature.feature_id}：别名 {alias!r} 与登记菜单名 {sorted(labels)} 无包含关系"
                    " ⇒ 别名表正在退化成同义词词典（禁止自由匹配）"
                )
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 判据本体在**真对象**上的读数（未注入 ⇒ 必须全绿 —— 对照读数）
# ══════════════════════════════════════════════════════════════════════════════


class TestJudgementsOnRealObject:
    def test_judgement_1_paths_exist(self, nav, menu_ts_nodes, capsys):
        problems = problems_paths_exist(nav, menu_ts_nodes)
        with capsys.disabled():
            print(f"\n[MC-058] 判据 1 paths_exist problems={len(problems)}")
        assert problems == []

    def test_judgement_1b_coverage_and_order(self, nav, menu_ts_nodes, capsys):
        problems = problems_coverage(nav, menu_ts_nodes)
        with capsys.disabled():
            print(f"[MC-058] 判据 1b coverage problems={len(problems)}"
                  f" | MENU_TREE={len(nav.MENU_TREE)} menu.ts={len(menu_ts_nodes)}")
        assert problems == []

    def test_judgement_2_codes_are_real(self, nav, catalog, capsys):
        problems = problems_codes_real(nav, catalog)
        with capsys.disabled():
            print(f"[MC-058] 判据 2 codes_real problems={len(problems)} | 目录={len(catalog[0])} 码")
        assert problems == []

    def test_judgement_3_default_deny(self, nav, capsys):
        problems = problems_default_deny(nav)
        with capsys.disabled():
            print(f"[MC-058] 判据 3 default_deny problems={len(problems)}"
                  f" | NAV_FEATURES={len(nav.NAV_FEATURES)}")
        assert problems == []

    def test_judgement_4_role_trim(self, nav, capsys):
        problems = problems_role_trim(nav)
        with capsys.disabled():
            print(f"[MC-058] 判据 4 role_trim problems={len(problems)}")
        assert problems == []

    def test_judgement_5_citation(self, nav, capsys):
        problems = problems_citation(nav)
        with capsys.disabled():
            print(f"[MC-058] 判据 5 citation problems={len(problems)}")
        assert problems == []

    def test_judgement_6a_no_steps_surface(self, nav, capsys):
        problems = problems_no_steps_surface(nav)
        with capsys.disabled():
            print(f"[MC-058] 判据 6a no_steps_surface problems={len(problems)}")
        assert problems == []

    def test_judgement_6b_no_step_wording_and_tool_wiring(self, nav):
        replies = _tool_replies(nav.build_navigation_answer)
        assert len(replies) >= 20, f"工具回复只跑了 {len(replies)} 条 ⇒ 判据疑似空转"
        # **接线面自证**：工具确实用了本模块的登记表（不是「碰巧没红」）
        registered = [q for q, _m, _s, data in replies if data and data.get("registered")]
        assert len(registered) >= 20, (
            f"工具回复里只有 {len(registered)} 条 registered=True ⇒ 工具没接上本模块的登记表"
        )
        assert problems_no_step_wording(nav, replies) == []

    def test_judgement_6c_aliases_grounded(self, nav):
        assert problems_aliases_grounded(nav) == []

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
            print(f"\n[MC-058][红证1] 假路径 ⇒ problems={len(problems)} :: {problems[:1]}")
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
        assert caught is not None, "删掉登记节点后模块竟然导入成功 ⇒ fail-closed 失效"
        with capsys.disabled():
            print(f"[MC-058][红证1b] 删节点 ⇒ 导入期自检抛 {type(caught).__name__}: {str(caught)[:90]}")
        assert "订单列表" in str(caught), f"自检抛了，但没具名到节点：{caught}"

    def test_judgement_1b_red_on_coverage_gap(self, nav, tmp_path, capsys):
        """判据本体（`problems_coverage`）在**内存桩**上的判别力：缺节点 / 多节点 / 换序都红。"""
        def _node(path, group="g", label="l", code=""):
            return type("N", (), {"path": path, "group": group, "label": label,
                                  "permission_code": code})()

        class _Stub:
            pass

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
            print(f"[MC-058][红证1b] 内存桩：缺节点 {len(missing)} 条 / 换序 {len(reordered)} 条")
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
            print(f"[MC-058][红证2] 假权限码 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 2 没看见目录外的权限码 ⇒ 空断言"

    def test_judgement_3_red_on_guessing(self, nav, tmp_path, capsys):
        def mutate(source: str) -> str:
            marker = "    if not hits:\n        return None\n"
            assert marker in source, "注入锚不存在 ⇒ 红证是空断言（同步本判据）"
            return source.replace(marker, "    if not hits:\n        return NAV_FEATURES[0]\n")

        mutated = _load_mutated(tmp_path, mutate)
        assert mutated.resolve_feature("怎么导出订单 Excel") is not None, "前提自证失败：注入没生效"
        problems = problems_default_deny(mutated)
        with capsys.disabled():
            print(f"[MC-058][红证3] 未命中改成猜 ⇒ problems={len(problems)} :: {problems[:1]}")
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
            print(f"[MC-058][红证4] 去掉裁剪 ⇒ problems={len(problems)} :: {problems[:1]}")
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
            print(f"[MC-058][红证4b] 加 role 形参 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 4 没看见「裁剪可能读客户端 role」⇒ 空断言"

    def test_judgement_5_red_on_weak_citation(self, nav, tmp_path, capsys):
        def mutate(source: str) -> str:
            marker = '        return f"登记项 #{self.feature_id} → 菜单节点 {nodes}"'
            assert marker in source, "注入锚不存在 ⇒ 红证是空断言（同步本判据）"
            return source.replace(marker, '        return "依据：米宝的导航指引"')

        mutated = _load_mutated(tmp_path, mutate)
        assert "菜单节点" not in mutated.build_navigation_answer("商品管理在哪", ["product:list"]).citation
        problems = problems_citation(mutated)
        with capsys.disabled():
            print(f"[MC-058][红证5] 摘掉菜单节点 ⇒ problems={len(problems)} :: {problems[:1]}")
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
            print(f"[MC-058][红证6a] data 多出 steps ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 6a 没看见注入的 steps 键 ⇒ 空断言"

    def test_judgement_6b_red_on_step_wording(self, nav, tmp_path, capsys):
        """**直连工具**的红证：把 `render()` 换成带步骤的文案 ⇒ 工具返回里出现步骤词。"""
        def mutate(source: str) -> str:
            marker = 'lines.append("（以上仅为导航信息；用户若要操作步骤，如实说没有步骤级指引。）")'
            assert marker in source, "注入锚不存在 ⇒ 红证是空断言（同步本判据）"
            return source.replace(marker, 'lines.append("第一步：点击左侧菜单进入。")')

        mutated = _load_mutated(tmp_path, mutate)
        replies = _tool_replies(mutated.build_navigation_answer)
        problems = problems_no_step_wording(mutated, replies)
        with capsys.disabled():
            print(f"[MC-058][红证6b] 文案塞步骤 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert problems, "判据 6b 没看见步骤词 ⇒ 空断言（工具没真的用本模块的 render？先查接线）"

    def test_judgement_6c_red_on_free_synonym_self_check(self, nav, tmp_path, capsys):
        """上游（导入期自检）的那一半：把别名换成自由同义词 ⇒ **模块 import 就抛**。"""
        caught: Optional[BaseException] = None
        try:
            _load_mutated(
                tmp_path,
                lambda s: s.replace(
                    '(("trade-center", "订单列表"),), ("订单列表", "订单列表页")',
                    '(("trade-center", "订单列表"),), ("订单列表", "库存盘点")',
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 读数就是「抛了什么」
            caught = exc
        assert caught is not None, "自由同义词竟然导入成功 ⇒ 别名约束失效"
        with capsys.disabled():
            print(f"[MC-058][红证6c] 自由同义词 ⇒ 导入期自检抛 {type(caught).__name__}: {str(caught)[:90]}")
        assert "库存盘点" in str(caught), f"自检抛了，但没具名到别名：{caught}"

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
                    "aliases": ("商品管理", "库存盘点"),
                },
            )(),
        )
        problems = problems_aliases_grounded(_Stub)
        with capsys.disabled():
            print(f"[MC-058][红证6c] 内存桩自由同义词 ⇒ problems={len(problems)} :: {problems[:1]}")
        assert any("库存盘点" in p for p in problems), f"不受菜单名约束的别名没被报出：{problems}"
        assert problems_aliases_grounded(nav) == [], "对照：真模块必须绿"

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
        assert problems_citation(mutated) == []
        assert problems_no_steps_surface(mutated) == []
        assert problems_aliases_grounded(mutated) == []


# ══════════════════════════════════════════════════════════════════════════════
# 类级元守卫：工具面（注册 / 门面导出 / 只读 / 权限锚 / 纯本地 / skill 绑定）
# ══════════════════════════════════════════════════════════════════════════════


class TestToolSurface:
    def test_no_steps_notice_is_present_on_every_tool_reply(self, nav):
        """**用户裁定的第 3 条口径**（问「怎么做」⇒ 给导航 + 如实说没有步骤级指引）必须有承载体。

        判据直接落在**工具真跑出来的回复**上（不是模块的 `render()`）—— 因为模型看到的是前者。
        """
        replies = _tool_replies(nav.build_navigation_answer)
        assert len(replies) >= 20, f"工具回复只跑了 {len(replies)} 条 ⇒ 判据疑似空转"
        for question, message, suggestion, data in replies:
            blob = f"{message or ''}{suggestion or ''}{json.dumps(data or {}, ensure_ascii=False)}"
            assert "没有步骤级指引" in blob, (
                f"工具回答「{question}」里没有「我没有步骤级指引」的如实告知口径 —— "
                "用户裁定 2026-10-02：第一步只做导航类，步骤级问题必须如实说不知道"
            )
        # 未登记的问题同样要有（它是最容易被模型「热心补步骤」的那一类）
        unregistered = [r for r in replies if r[3] and r[3].get("registered") is False]
        assert len(unregistered) >= 2, "工具回复里没有未登记样本 ⇒ 判据会空跑"
        for question, message, suggestion, _data in unregistered:
            assert "没有步骤级指引" in f"{message or ''}{suggestion or ''}"

    def test_no_step_wording_in_tool_source_either(self):
        """**更上游的一层**：工具源码里（含 `description` —— 它**也**注入模型）不得出现步骤词。

        为什么单独判它：`description` 会随工具 schema 进模型上下文 —— 在里面写「第一步…」
        同样是在把模型往编步骤上推（实测踩到：「点击」曾出现在 description 里，被本判据抓到）。
        """
        text = NAV_TOOL.read_text(encoding="utf8")
        hits = [w for w in STEP_WORDS if w in text]
        assert hits == [], (
            f"`app/tools/nav_guide.py` 的源码里出现步骤词 {hits} —— "
            "该文件的散文字面量会进模型上下文（docstring 尾部除外）"
        )

    def test_citation_is_traceable_to_a_registered_node(self, nav):
        answer = nav.build_navigation_answer("商品管理在哪", ["product:list"])
        assert answer.citation.startswith("登记项 #products → 菜单节点")
        assert nav.menu_node(nav.STANDALONE_GROUP, "商品管理").path == "/products"
        assert nav.menu_node("no-such-group", "商品管理") is None

    def test_tool_is_registered_and_read_only(self, nav):
        sys.path.insert(0, str(AI_SERVICE))
        from app.tools.registry import get_tool_registry

        tool = get_tool_registry().get_tool("nav_guide")
        assert tool is not None, "nav_guide 未注册进 `create_default_registry()` ⇒ 模型不可达"
        assert tool.read_only is True, "导航指引是纯本地只读能力：`read_only` 必须为 True"
        assert tool.destructive is False
        assert list(tool.required_permissions) == [], (
            "nav_guide 是**纯本地**工具（零 admin-api 调用点）⇒ 不声明权限码"
            "（与 `interact` / `image_recognize` 同口径，见 `LOCAL_ONLY_TOOLS`）；"
            "授权面落在**答案级**的角色裁剪上。**不要**给它挂一个码："
            "那会让 `test_agent_permission_parity` 的判据 2（工具码 ≡ 端点生效码）"
            "在空端点集上结构性不成立"
        )

    def test_trimming_is_enforced_at_the_answer_level(self, nav):
        """工具层没有码 ⇒ 授权面必须**真的**落在答案级裁剪上（不是「谁都没有」）。"""
        blind = nav.build_navigation_answer("工艺配置在哪", ["order:list"]).to_data()
        assert blind["pages"] == []
        assert "production:view" not in json.dumps(blind, ensure_ascii=False)
        granted = nav.build_navigation_answer("工艺配置在哪", ["production:view"]).to_data()
        assert [p["path"] for p in granted["pages"]] == ["/production/routings"]

    def test_tool_is_exported_from_the_facade(self):
        sys.path.insert(0, str(AI_SERVICE))
        import app.tools as facade

        assert "NavGuideTool" in facade.__all__, "未被 `app/tools` 门面导出（门面完整性判据会红）"
        assert getattr(facade, "NavGuideTool", None) is not None

    def test_tool_module_has_no_http_call_points(self):
        text = NAV_TOOL.read_text(encoding="utf8")
        assert "get_admin_api_client" not in text, "nav_guide 不得有 admin-api 调用点（真值源在仓内）"
        assert '"question"' in text, "参数里没有 question ⇒ 模型无从提问"

    def test_tool_is_bound_to_a_b_side_skill(self):
        """可达性：`general` 兜底 skill 绑了它（否则模型拿不到 ⇒ 能力谎报）。"""
        sys.path.insert(0, str(AI_SERVICE))
        from app.graph.skills.general_agent import GENERAL_TOOLS

        assert "nav_guide" in GENERAL_TOOLS, "nav_guide 没绑到任何 B 端 skill ⇒ 模型不可达"
