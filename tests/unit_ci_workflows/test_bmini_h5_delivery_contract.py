# case_ids: MC-012, BM-027
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式挂 MC-012；
#   B 端登录页的两条入口与可读性行为面挂 BM-027。本 PR 不新建用例族。）
r"""商家端 h5（`https://app.migaozn.com/b/`）**交付契约**常驻判据（issue #5721）。

## 病根（2026-09-27 线上实测，三条，都不是推断）

| # | 读数 | 后果 |
|---|---|---|
| ① 跨域 | 发布腿注入 `TARO_APP_API_URL=https://api.migaozn.com`，而 admin-api 的 CORS 白名单不含 `https://app.migaozn.com`（也不含前端发的 `X-Client-Type` 头）⇒ 预检 `403 Invalid CORS request` | 浏览器侧 `net::ERR_FAILED`，登录页只显示 `Load failed`（Safari）/`Failed to fetch`（Chrome）；**服务端日志一条都没有**（请求根本没发出去）⇒ 极易误判成"后端挂了" |
| ② 根字号 | Taro H5 的 rem 方案只做了**编译期** `px→rem`（750 设计宽 ⇒ `1px = 1/40 rem`），而「1rem 是多少」**没有任何东西设置**（实测 `document.documentElement.style.fontSize === ''`、浏览器默认 16px 兜底） | 全端字号 = 设计值的 **40%**（标签 5.2 CSS px、页脚 4.8px、登录按钮高 19 CSS px），且**完全不随屏宽变化** |
| ③ 半尺样式 | 登录页 SCSS 按「CSS px 尺」写（12~17px 一档），全仓其余页面是「750 设计尺」（20~32px 一档） | 叠上②后登录页不可读、不可点（字段标签 5.2px） |

① 的正确形态是**同源**：`app.migaozn.com` 的 nginx 本来就代理 `/api/`→admin-api、
`/api/chat/`→ai-agent（`deploy/swas/nginx.conf`），工人端 `/w/` 正是靠这个同源面工作
（`docs/design/worker-h5-scan-and-report.md` 逐字：「页面与 `/api` 同源 ⇒ 无跨域」）。

## 本守卫锁什么（每条都能单独变红）

1. **发布腿的 API / AI 基址必须与落地面同源** —— 落地面取自同一条腿的发布后断言 step
   （`deploy/scripts/bmini-h5-verify-served.sh <BASE_URL>`），不是写死的常量字面量；
2. **h5 模板必须带响应式 root font-size 接线**：设置 `documentElement.style.fontSize`、
   监听 `resize`、有上下限，且 `DESIGN_WIDTH` 与 `frontend/bmini-app/config/index.ts` 的
   `designWidth` **相等**（两边各改各的 = 静默错位）；
3. **登录页可读性与触控下限**：两个入口的可点区域 `height ≥ 88`（≈45.8 CSS px，手指最小命中区
   44 CSS px）、输入与按钮字号 `≥ 32`（≈16.6 CSS px，输入框 < 16 时 iOS 聚焦会放大整页）；
4. 🔴 **②与③必须一致**：把 root 的下限字号代进 `值 / (baseFontSize × 2) × root`，
   结果不得 < 12 CSS px —— 否则「lower root 下限」就能让 3 的判据失去意义（判据不许被调松绕过）。
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "bmini-h5-publish.yml"
H5_INDEX_PATH = REPO_ROOT / "frontend" / "bmini-app" / "src" / "index.html"
TARO_CONFIG_PATH = REPO_ROOT / "frontend" / "bmini-app" / "config" / "index.ts"
LOGIN_SCSS_PATH = REPO_ROOT / "frontend" / "bmini-app" / "src" / "pages" / "auth" / "login" / "index.scss"
FILTER_PATH = (
    REPO_ROOT
    / "backend"
    / "admin-api"
    / "src"
    / "main"
    / "java"
    / "com"
    / "migao"
    / "admin"
    / "security"
    / "SameOriginOriginHeaderFilter.java"
)
SECURITY_CONFIG_PATH = (
    REPO_ROOT
    / "backend"
    / "admin-api"
    / "src"
    / "main"
    / "java"
    / "com"
    / "migao"
    / "admin"
    / "security"
    / "SecurityConfig.java"
)

# 与 src/index.html 脚本里的注释同源：24 设计 px ≈ 12.8 CSS px @390 宽（@375 为 12.0）
DESIGN_PX_FLOOR = 24
TOUCH_TARGET_DESIGN_PX = 88
MIN_EFFECTIVE_CSS_PX = 12.0
# Taro 的 baseFontSize 默认值（`@tarojs/taro-h5` 的 pxTransform：rem = px / (baseFontSize × 2)）
TARO_DEFAULT_BASE_FONT_SIZE = 20


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1：发布腿的 API 面与落地面同源
# ══════════════════════════════════════════════════════════════════════════════
def _workflow_env() -> dict:
    """读发布腿的 workflow 级 env（`yaml` 会把裸 `on:` 解析成布尔 True 键，这里不碰它）。"""
    data = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{WORKFLOW_PATH} 解析不出 mapping"
    env = data.get("env") or {}
    assert isinstance(env, dict), f"{WORKFLOW_PATH} 的 env 不是 mapping"
    return env


def _serving_origin() -> str:
    """落地面 origin = 发布后断言 step 传给 verify 脚本的第一个参数（不写死常量）。"""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    match = re.search(r"bmini-h5-verify-served\.sh\s+(https?://[^\s\"']+)", text)
    assert match, (
        f"{WORKFLOW_PATH} 里找不到 `bmini-h5-verify-served.sh <BASE_URL>` —— "
        "没有落地面就没有『同源』的判据对象（判据不许自己编一个 origin）"
    )
    return match.group(1)


@pytest.mark.parametrize("var", ["TARO_APP_API_URL", "TARO_APP_AI_API_URL"])
def test_h5_api_base_is_same_origin_as_landing_surface(var: str) -> None:
    """API 基址必须与落地面同源。

    红证（实跑过）：把 `TARO_APP_API_URL` 改成 `https://api.migaozn.com` ⇒ 本条红；
    删掉 `TARO_APP_AI_API_URL`（未配置时产物里 baked 的是 `http://localhost:8001`）⇒ 本条红。
    """
    env = _workflow_env()
    assert var in env, (
        f"{WORKFLOW_PATH} 的 workflow env 缺少 {var} —— "
        f"未配置时 frontend/bmini-app/src/utils/constants.ts 会兜底到 localhost（真机必然失败）"
    )
    api = str(env[var]).strip()
    serving = _serving_origin()

    api_parts = urlsplit(api)
    serving_parts = urlsplit(serving)
    assert api_parts.scheme in ("http", "https") and api_parts.netloc, (
        f"{var}={api!r} 不是绝对 URL —— 相对路径在 h5 里会打到静态根（app.migaozn.com）上，"
        "看似同源实则没经过 nginx 的 /api/ 代理"
    )
    assert (api_parts.scheme, api_parts.netloc) == (serving_parts.scheme, serving_parts.netloc), (
        f"{var}={api!r} 与落地面 {serving!r} **不同源** ⇒ 浏览器要过一次 CORS 预检，"
        "而 admin-api 的 CORS 白名单（backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java）"
        "只列了 admin-web 的几个 origin —— 2026-09-27 线上实测就是被它 403 `Invalid CORS request` 拒掉、"
        "登录页只显示 `Load failed`。落地面自己的 nginx 已代理 /api/ 与 /api/chat/ ⇒ 同源是唯一正确形态。"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 2：h5 模板的响应式 root font-size 接线
# ══════════════════════════════════════════════════════════════════════════════
def _h5_index_html() -> str:
    assert H5_INDEX_PATH.is_file(), f"缺 {H5_INDEX_PATH}"
    return H5_INDEX_PATH.read_text(encoding="utf-8")


def _script_constant(html: str, name: str) -> int:
    match = re.search(rf"\b{name}\s*=\s*(\d+)", html)
    assert match, (
        f"{H5_INDEX_PATH} 的 root font-size 脚本里找不到常量 {name} —— "
        "常量名被改掉时本判据不许静默跳过（宁缺勿滥：找不到就红）"
    )
    return int(match.group(1))


def _taro_design_width() -> int:
    text = TARO_CONFIG_PATH.read_text(encoding="utf-8")
    match = re.search(r"designWidth:\s*(\d+)", text)
    assert match, f"{TARO_CONFIG_PATH} 里找不到 `designWidth`"
    return int(match.group(1))


def test_h5_template_sets_responsive_root_font_size() -> None:
    """h5 模板必须补上 Taro rem 方案缺失的另一半（根字号 + 随屏宽变化）。

    红证（实跑过）：删掉 `frontend/bmini-app/src/index.html` 里那段脚本 ⇒ 本条红；
    把 `addEventListener('resize'` 那行删掉 ⇒ 本条红（旋转屏幕/改窗口后字号不再跟随）。
    """
    html = _h5_index_html()
    assert "document.documentElement.style.fontSize" in html, (
        f"{H5_INDEX_PATH} 没有设置 root font-size —— 这正是 2026-09-27 的病根："
        "样式编译成 rem，而 1rem 没有任何人定义 ⇒ 浏览器默认 16px 兜底，全端字号只有设计值的 40%"
    )
    assert "addEventListener('resize'" in html or 'addEventListener("resize"' in html, (
        f"{H5_INDEX_PATH} 的根字号不跟随 resize ⇒ 不满足『支持响应式，不同屏幕尺寸都好用』"
    )
    assert "clientWidth" in html, (
        f"{H5_INDEX_PATH} 的根字号没有读视口宽度 ⇒ 它是常量而不是响应式接线"
    )

    design_width = _script_constant(html, "DESIGN_WIDTH")
    base_font_size = _script_constant(html, "BASE_FONT_SIZE")
    max_width = _script_constant(html, "MAX_WIDTH")
    min_font_size = _script_constant(html, "MIN_FONT_SIZE")

    assert design_width == _taro_design_width(), (
        f"{H5_INDEX_PATH} 的 DESIGN_WIDTH={design_width} ≠ "
        f"{TARO_CONFIG_PATH} 的 designWidth={_taro_design_width()} —— 两边各改各的会静默错位"
    )
    assert base_font_size == TARO_DEFAULT_BASE_FONT_SIZE, (
        f"BASE_FONT_SIZE={base_font_size} 与 Taro 的 baseFontSize 默认值 "
        f"{TARO_DEFAULT_BASE_FONT_SIZE} 不一致 ⇒ 根字号与编译期折算系数不再是同一个来源"
    )
    assert max_width >= design_width * 0.5, (
        f"MAX_WIDTH={max_width} 太小：大屏上整个界面会被压成一条（本判据只挡住明显写错的常量）"
    )

    # 判据 4（与判据 3 联动）：最不利的根字号下，设计尺度下限字号仍须 ≥ 12 CSS px
    effective = min_font_size * DESIGN_PX_FLOOR / (base_font_size * 2)
    assert effective >= MIN_EFFECTIVE_CSS_PX, (
        f"MIN_FONT_SIZE={min_font_size} 时，{DESIGN_PX_FLOOR} 设计 px 只有 {effective:.2f} CSS px "
        f"< {MIN_EFFECTIVE_CSS_PX} —— 调小根字号下限会让『字号下限』那条判据失去意义"
        "（判据不许被调松绕过）"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：登录页的可读性与触控下限（选择器感知）
# ══════════════════════════════════════════════════════════════════════════════
def test_same_origin_filter_is_auto_registered_before_security_chain() -> None:
    """同源判定过滤器必须**真的会被注册**（而不是一个没人调用的类）。

    为什么单独一条：`SameOriginOriginHeaderFilterTest` 是直接 `new` 出来调的 ——
    它证明逻辑对，**证明不了**这个 bean 在生产里会被执行。而这条路只有「Servlet 级 +
    `@Order(HIGHEST_PRECEDENCE)`（排在 Security 链 order=-100 之前）」一种活法：
    挂进 Security 链内部就晚于 `CorsFilter`，加了 `<FilterRegistrationBean>.setEnabled(false)`
    就根本不会注册 —— 两种改法都能让所有测试照样绿，而线上回到 403。
    红证（实跑过）：删掉 `@Component` ⇒ 红；把 `@Order(Ordered.HIGHEST_PRECEDENCE)` 删掉 ⇒ 红。
    """
    assert FILTER_PATH.is_file(), f"缺 {FILTER_PATH}（同源请求会被 CORS 判成跨域 ⇒ 403）"
    text = FILTER_PATH.read_text(encoding="utf-8")
    assert "@Component" in text, (
        f"{FILTER_PATH} 不再是 Spring bean ⇒ Boot 不会把它注册成 Servlet Filter，"
        "同源 POST 又会走回 403 `Invalid CORS request`"
    )
    assert "@Order(Ordered.HIGHEST_PRECEDENCE)" in text, (
        f"{FILTER_PATH} 缺少最高优先级声明 —— 必须排在 Spring Security 链（order=-100）之前，"
        "否则它晚于 `CorsFilter`，等于没生效"
    )
    assert "SameOriginOriginHeaderFilter>" not in SECURITY_CONFIG_PATH.read_text(encoding="utf-8"), (
        f"{SECURITY_CONFIG_PATH} 里出现了本过滤器的 `FilterRegistrationBean` —— "
        "本类**刻意**走 Servlet 级自动注册（见其 javadoc）；一旦改成禁掉自动注册，"
        "它就既不在这条链里、也不在那条链里（静默失效）"
    )


def _scss_declarations(text: str) -> list[tuple[str, str, str, int]]:
    """极简 SCSS 展开：产出 `(完整选择器, 属性, 值, 行号)`。

    只处理本项目用到的形态：`//` 行注释、`{}` 嵌套、`&__x` 拼接。
    不求值 `@media` / `@include` —— 那种声明照常产出（选择器取当前栈），
    对本判据（只看 `height` / `font-size` 的数值下限）够用且不会静默漏项。
    """
    out: list[tuple[str, str, str, int]] = []
    stack: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("//", 1)[0].strip()
        while line:
            if line.startswith("}"):
                if stack:
                    stack.pop()
                line = line[1:].strip()
                continue
            opening = re.match(r"^([^{};]+?)\s*\{", line)
            if opening:
                selector = opening.group(1).strip()
                if selector.startswith("&"):
                    selector = (stack[-1] if stack else "") + selector[1:]
                elif selector.startswith("@"):
                    # @media / @include 之类：不入栈（当作透明分组），声明照常记到当前选择器上
                    selector = stack[-1] if stack else ""
                stack.append(selector)
                line = line[opening.end():].strip()
                continue
            declaration = re.match(r"^([a-zA-Z-]+)\s*:\s*([^;}]+)[;]?", line)
            if declaration:
                out.append((stack[-1] if stack else "", declaration.group(1), declaration.group(2).strip(), lineno))
                line = line[declaration.end():].strip()
                continue
            break
    return out


def _px(value: str) -> float | None:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)px", value.strip())
    return float(match.group(1)) if match else None


@pytest.fixture(scope="module")
def login_declarations() -> list[tuple[str, str, str, int]]:
    assert LOGIN_SCSS_PATH.is_file(), f"缺 {LOGIN_SCSS_PATH}"
    return _scss_declarations(LOGIN_SCSS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("selector", "prop", "floor"),
    [
        (".login-btn", "height", TOUCH_TARGET_DESIGN_PX),
        (".login-field__input", "height", TOUCH_TARGET_DESIGN_PX),
        (".login-tab", "height", TOUCH_TARGET_DESIGN_PX),
        (".login-code-btn", "height", TOUCH_TARGET_DESIGN_PX),
        (".login-btn", "font-size", 32),
        (".login-field__input", "font-size", 32),
    ],
)
def test_login_page_touch_target_and_font_floor(
    login_declarations: list[tuple[str, str, str, int]],
    selector: str,
    prop: str,
    floor: float,
) -> None:
    """登录页交互件的触控高度 / 字号下限。

    红证（实跑过）：把 `.login-btn` 的 `height` 改回 48px、或 `.login-field__input` 的
    `font-size` 改回 15px ⇒ 本条红（这两个数字正是线上 19px 高按钮 / 5.2px 标签的来源）。
    """
    values = [
        _px(value)
        for sel, name, value, _lineno in login_declarations
        if sel == selector and name == prop
    ]
    values = [v for v in values if v is not None]
    assert values, (
        f"{LOGIN_SCSS_PATH} 里找不到 `{selector} {{ {prop}: <N>px }}` —— "
        "判据对象缺席时不许当通过（改用例要连着判据一起改）"
    )
    worst = min(values)
    assert worst >= floor, (
        f"{selector} 的 {prop} 最小值为 {worst:g}px（设计尺度），低于下限 {floor:g}px。"
        f"换算：{worst:g} / 40 × root(≈20.8 @390 宽) ≈ {worst * 0.52:.1f} CSS px。"
        "触控最小命中区 44 CSS px、输入字号 ≥ 16 CSS px（否则 iOS 聚焦放大整页）"
    )
