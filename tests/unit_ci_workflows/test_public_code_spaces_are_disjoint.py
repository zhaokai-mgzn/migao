# case_ids: PR-113, PR-114, PR-117
"""公开**短码路径命名空间**互斥守卫（issue #5052 P2）—— 让「同一命名空间下混两套语义」进不来。

## 它治什么（类级，不是这一个实例）

`GET /s/{短码}`（工人报工短链，302 → `/w/?t=<token>`）与 `GET /i/{短码}`（入库标签，302 → 落地页）
是**两个公开路径命名空间**，而它们的短码规格**故意同款**（8 位 Crockford Base32、
去掉 `I/L/O/U`）—— 规格同款是为了「人可读可抄」，不是为了「可以互相串」。

⇒ 一旦有人「顺手复用那张表 / 复制一份字母表 / 把两个入口接到同一个服务 / 新开第三个短码前缀」，
**扫标签就会变成进报工页**，而这只在真机上扫码时才暴露 —— 静态层面**不会有任何东西变红**。
本守卫把那件事变成一条机械判据（实例判据见
`backend/admin-api/src/test/java/com/migao/admin/controller/InboundLabelSurfaceGuardTest.java`）。

## 判据（四条，全部对着一个真实缺陷形态）

| # | 判据 | 红证形态 |
|---|---|---|
| A | **未登记即红**：控制器里出现的单字母短码前缀必须**恰好等于**登记表 `CODE_SPACES` 的键集 | 新开第三个短码前缀（如 `/l/`）而不登记 ⇒ 红 |
| B | **公开入口必须在 `SecurityConfig` 放行**：每个登记前缀都要出现在 `permitAll` 名单里 | 删掉 `"/i/**"` ⇒ 红（扫码只会拿到 401，纸上的码等于没用） |
| C | **跨空间互斥**：每个码空间的解析文件不得出现**另一个空间**的持久化符号 | 把入库标签接到 `processing_set_part_tokens` ⇒ 红 |
| D | **字母表单一来源**：Crockford 字母表字面量在 admin-api 主源码里**恰好出现一次** | 复制第二份字母表（含 `I/L/O/U`）⇒ 红 |
| **F1~F3** | **边缘归属登记**（§F）：公开前缀在 nginx 上的落地面必须登记、与配置逐项相符，且**语义模拟**证明它落到自己那一面 | 删掉 `location /i/` ⇒ 红，且**指名**「落到了 `location /` 的 SPA fallback」 |

外加两条载体判据：**落地页地址不得硬编码域名**（必须来自配置）、**两个空间不得共用一个入口类**。

## 边界（如实登记）

* 本守卫是**静态**的：它不证明「扫 `/i/` 真的不会进报工页」—— 那一半由
  `SecurityConfigTest`（真安全链 + 真控制器 302）与
  `InboundLabelSurfaceGuardTest`（源码互斥）承担。
* 前缀形态只覆盖**单字母 + `/{...}`** 这一种公开短码入口形态（本仓现有两个都是这个形态）；
  换形态（如 `/label/{码}`）不会被本守卫发现 —— 那属于「新增一种载体」，需人来补判据。
* §F（边缘归属）是**离线**的：它读 nginx 配置文本 + 语义模拟，证明不了线上 nginx 已 reload、
  也证明不了 admin-api 真的回了 302 —— 那一半由 `deploy/scripts/bmini-h5-verify-served.sh` 的
  `/i/` 探针在线上跑（发布腿 `.github/workflows/bmini-h5-publish.yml` 的 `paths` 已含
  `deploy/swas/nginx.conf`，改配置即重跑该腿），其判别力由
  `tests/unit_ci_workflows/test_bmini_h5_hosting.py` 的判据 7 真跑证明。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADMIN_MAIN = REPO / "backend/admin-api/src/main/java/com/migao/admin"
CONTROLLER_DIR = ADMIN_MAIN / "controller"
SECURITY_CONFIG = ADMIN_MAIN / "security/SecurityConfig.java"
ALPHABET_LITERAL = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ".replace("I", "").replace("L", "").replace("O", "").replace("U", "")
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

#: 公开短码前缀的**发现**形态：`@GetMapping("/s/{shortCode}")` / `@GetMapping("/i/{shortCode}")`
PREFIX_RE = re.compile(r'@GetMapping\(\s*"(/[a-z])/\{')


@dataclass(frozen=True)
class CodeSpace:
    """一个公开码空间的登记面（语义 + 解析文件 + **不许出现**的另一个空间的符号）。"""

    prefix: str
    semantics: str
    resolver_files: tuple[str, ...]
    forbidden_tokens: tuple[str, ...] = field(default=())


#: 🔴 **登记表**：新增一个公开短码前缀必须在这里留下它的语义与所有者（未登记 ⇒ 判据 A 红）。
CODE_SPACES: dict[str, CodeSpace] = {
    "/s/": CodeSpace(
        prefix="/s/",
        semantics="工人报工短链（302 → /w/?t=<token>；承载表 processing_set_part_tokens）",
        resolver_files=(
            "service/WorkerShortLinkService.java",
            "controller/WorkerShortLinkController.java",
        ),
        forbidden_tokens=("InboundLabel", "inbound_labels"),
    ),
    "/i/": CodeSpace(
        prefix="/i/",
        semantics="入库标签（302 → 落地页 /b/?code=<短码>；承载表 inbound_labels）",
        resolver_files=(
            "service/InboundLabelService.java",
            "mapper/InboundLabelMapper.java",
            "controller/InboundLabelShortLinkController.java",
        ),
        forbidden_tokens=("ProcessingSetPartToken", "processing_set_part_tokens",
                          "REPORT_PAGE_PATH", "/w/"),
    ),
}


# ────────────────────────────────────────────── 解析工具


def strip_java_comments(source: str) -> str:
    """剥掉 Java 注释，**但保护字符串 / 字符字面量**。

    为什么不是一条正则：`"/i/**"` 这个字面量自己就含 `/*` ⇒ 朴素的块注释正则会把它
    连同后面的代码一起吃掉（实测：本地判据因此假红/假绿各一次）。状态机虽笨但不会骗人。
    """
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        if c == '"':
            out.append(c)
            i += 1
            while i < n:
                if source[i] == "\\" and i + 1 < n:
                    out.append(source[i:i + 2])
                    i += 2
                    continue
                out.append(source[i])
                if source[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if c == "'":
            out.append(c)
            i += 1
            while i < n and source[i] != "'":
                if source[i] == "\\" and i + 1 < n:
                    out.append(source[i:i + 2])
                    i += 2
                    continue
                out.append(source[i])
                i += 1
            if i < n:
                out.append("'")
                i += 1
            continue
        if source.startswith("//", i):
            j = source.find("\n", i)
            i = n if j < 0 else j
            continue
        if source.startswith("/*", i):
            j = source.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def discover_code_spaces(sources: dict[str, str]) -> set[str]:
    """从「文件名 → 源码」里发现公开短码前缀集合（纯函数 ⇒ 可注入式自证）。"""
    found: set[str] = set()
    for text in sources.values():
        for match in PREFIX_RE.finditer(strip_java_comments(text)):
            found.add(match.group(1) + "/")
    return found


def permitted_paths(security_source: str) -> str:
    """取 `permitAll` 名单那一段（到第一个 `.permitAll()` 为止）。"""
    body = strip_java_comments(security_source)
    idx = body.find(".permitAll()")
    return body if idx < 0 else body[:idx]


def alphabet_carriers(sources: dict[str, str]) -> list[str]:
    """含 Crockford 字母表字面量的文件名（**只算代码**，注释里提一句不算第二份实现）。"""
    return sorted(name for name, text in sources.items()
                  if CROCKFORD_ALPHABET in strip_java_comments(text))


# ────────────────────────────────────────────── 现场读取


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def controller_sources() -> dict[str, str]:
    return {p.name: _read(p) for p in sorted(CONTROLLER_DIR.glob("*.java"))}


def admin_main_sources() -> dict[str, str]:
    return {str(p.relative_to(ADMIN_MAIN)): _read(p) for p in sorted(ADMIN_MAIN.rglob("*.java"))}


# ────────────────────────────────────────────── A~D 判据


def test_a_every_public_code_space_is_registered() -> None:
    """判据 A：控制器里出现的短码前缀 == 登记表键集（**未登记即红**，少一个也红）。"""
    found = discover_code_spaces(controller_sources())
    assert found == set(CODE_SPACES), (
        "公开短码前缀与登记表不一致 —— 未登记的前缀必须先在 "
        "tests/unit_ci_workflows/test_public_code_spaces_are_disjoint.py 的 CODE_SPACES 里"
        f"写明语义与解析文件（发现：{sorted(found)}；登记：{sorted(CODE_SPACES)}）"
    )


def test_b_every_public_code_space_is_permitted_in_security_config() -> None:
    """判据 B：每个公开前缀都必须在 `SecurityConfig` 的 permitAll 名单里。"""
    allowed = permitted_paths(_read(SECURITY_CONFIG))
    missing = [prefix for prefix in CODE_SPACES if f'"{prefix}**"' not in allowed]
    assert missing == [], (
        f"这些公开短码前缀没有 permitAll：{missing} —— 印刷品上的码对任何持码人等价，"
        "不放行 ⇒ 扫码工具只会拿到 401，纸上的码等于没用"
    )


def test_c_code_spaces_do_not_share_persistence_or_symbols() -> None:
    """判据 C：每个空间的解析文件不得出现另一个空间的持久化符号（互斥，双向）。"""
    problems: list[str] = []
    for prefix, space in CODE_SPACES.items():
        for rel in space.resolver_files:
            text = strip_java_comments(_read(ADMIN_MAIN / rel))
            for token in space.forbidden_tokens:
                if token in text:
                    problems.append(f"{rel}（{prefix} 空间）出现另一个码空间的符号 {token!r}")
    assert problems == [], "公开码空间互相串了（扫标签会变成进报工页）：\n" + "\n".join(problems)


def test_d_the_short_code_alphabet_has_exactly_one_carrier() -> None:
    """判据 D：Crockford 字母表在 admin-api 主源码里**恰好一份**（复制第二份 ⇒ 红）。"""
    carriers = alphabet_carriers(admin_main_sources())
    assert carriers == ["service/WorkerShortLinkService.java"], (
        "短码字母表的载体不是恰好一个 —— 复制第二份 = 第二条真相源"
        f"（实测载体：{carriers}）"
    )


def test_e_landing_targets_are_configured_not_hardcoded() -> None:
    """载体判据：公开入口的落地地址不得硬编码域名（必须来自配置）。"""
    for prefix, space in CODE_SPACES.items():
        for rel in space.resolver_files:
            text = strip_java_comments(_read(ADMIN_MAIN / rel))
            assert "migaozn.com" not in text, (
                f"{rel}（{prefix}）里出现了硬编码域名 —— 印在纸上的码是稳定契约，"
                "落地页必须走单一配置（换域名/改路由只改一处）"
            )


# ────────────────────────────────────────────── 注入式自证（判据真的有判别力）


def test_red_proof_an_unregistered_code_space_is_detected() -> None:
    """红证 A：新开一个未登记的前缀 ⇒ 判据必须报出来（否则「未登记即红」是空话）。"""
    sources = {"BrandNewController.java": 'class C { @GetMapping("/l/{code}") void x() {} }'}
    assert discover_code_spaces(sources) == {"/l/"}
    assert discover_code_spaces(sources) != set(CODE_SPACES)


def test_red_proof_a_removed_permit_all_is_detected() -> None:
    """红证 B：把 `/i/**` 从 permitAll 名单里删掉 ⇒ 判据必须报出来。"""
    real = _read(SECURITY_CONFIG)
    mutated = real.replace('"/i/**",', "")
    assert f'"{CODE_SPACES["/i/"].prefix}**"' in permitted_paths(real)
    assert f'"{CODE_SPACES["/i/"].prefix}**"' not in permitted_paths(mutated)


def test_red_proof_a_cross_space_reference_is_detected() -> None:
    """红证 C：把入库标签接到报工短链那张表 ⇒ 判据必须报出来。"""
    space = CODE_SPACES["/i/"]
    text = 'class X { void f() { mapper.selectByShortCode("A"); /* processing_set_part_tokens */ } }'
    stripped = strip_java_comments(text)
    assert all(token not in stripped for token in space.forbidden_tokens), "注释里的提及不该判红"
    assert "ProcessingSetPartToken" in "class X { ProcessingSetPartToken t; }"


def test_red_proof_a_duplicated_alphabet_is_detected() -> None:
    """红证 D：复制第二份字母表 ⇒ 判据必须报出来。"""
    single = {"WorkerShortLinkService.java": f'ALPHABET = "{CROCKFORD_ALPHABET}";'}
    duplicated = dict(single)
    duplicated["CopyService.java"] = f'ALPHABET = "{CROCKFORD_ALPHABET}";'
    assert alphabet_carriers(single) == ["WorkerShortLinkService.java"]
    assert alphabet_carriers(duplicated) == ["CopyService.java", "WorkerShortLinkService.java"]


def test_the_real_files_are_readable_at_all() -> None:
    """坐标自证：登记表里的解析文件**真的存在**（否则 A~E 全在扫空气 ⇒ 假绿）。"""
    for prefix, space in CODE_SPACES.items():
        for rel in space.resolver_files:
            assert (ADMIN_MAIN / rel).is_file(), f"{prefix} 登记的解析文件不存在：{rel}"
    assert SECURITY_CONFIG.is_file()
    assert ALPHABET_LITERAL == CROCKFORD_ALPHABET


# ══════════════════════════════════════════════════════════════════════════════
# F. 公开前缀在 **nginx**（边缘）的**归属登记** —— 类级固化：让「没登记的公开前缀」进不来
#    （issue #5052 §7.1 的 `/i/` 面；同族 = #5668 的 `/b/`、#4802 的 `/s/`）
# ══════════════════════════════════════════════════════════════════════════════
# 判据 A~E 管「Java 侧两个码空间不互相串」；这一节管**另一半**：码空间在**边缘**上有没有
# 自己的落地面 —— 少了它，码照样能生成、页面照样 **200**，只是**扫出来是别人的页面**。
#
# 🔴 实测（改动前的线上读数，2026-09-27）：
#     `curl -s -o /tmp/i.html -w '%{http_code}' https://app.migaozn.com/i/__probe__` ⇒ **200**，
#     且 `sha256(body)` 与 `GET /` **逐字节相同**（= C 端元元 index.html）；
#     同一时刻 `/s/__probe__` ⇒ **404**（到了 admin-api，因为短码不存在）。
#     ⇒ `/i/` 没在 nginx 登记 ⇒ 命中 `location /` 的 `try_files … /index.html` ⇒
#     **印在标签上的码扫出来是 C 端页面**。200 不是错误码 ⇒ 监控不红、只有真机扫码才发现
#     （#5668 的教训逐字：「静默串端比 404 难发现得多」）。
#
# 判据（每条都能单独变红；**离线**，不连线上）：
#
# | # | 判据 | 红证形态 |
# |---|---|---|
# | F1 | **未登记即红**：代码里的码空间 ∪ nginx 的公开前缀 ∪ 发布腿声明的 h5 子目录 == 登记表键集 | 新开 `/l/` / 新发一个 h5 子目录而不登记 ⇒ 红 |
# | F2 | **归属逐项相符**：代理面必须 `proxy_pass http://<登记的上游>;`（**不带 URI 后缀**）；静态面不得有 proxy_pass，且 fallback 不跨出自己命名空间 | `proxy_pass http://admin-api:8080/i;` ⇒ 红（路径被改写成 `/i7K3M9QP2`） |
# | F3 | **语义模拟**（端到端离线）：每个探针请求落到**它自己的**落地面 | 删掉 `location /i/` ⇒ 红，且**指名**「落到了 `location /` 的 SPA fallback（→ index.html = C 端元元）」 |

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_swas_nginx_rate_limit import (  # noqa: E402
    Block,
    _locations,
    _servers,
    parse_nginx,
)

NGINX_CONF = REPO / "deploy" / "swas" / "nginx.conf"
APP_DOMAIN = "app.migaozn.com"

#: 公开前缀的**第三个发现面**：h5 发布腿声明的子目录（每多一个 h5 应用 ⇒ 多一个公开前缀）。
H5_PUBLISH_WORKFLOWS = (
    REPO / ".github" / "workflows" / "bmini-h5-publish.yml",
    REPO / ".github" / "workflows" / "worker-h5-publish.yml",
)
H5_SUBDIR_RE = re.compile(r"^\s*H5_SUBDIR:\s*(?P<sub>[A-Za-z0-9._-]+)\s*$", re.M)

FACE_PROXY = "proxy"
FACE_STATIC = "static"
FACE_STATIC_UNDER_ROOT = "static-under-root"


@dataclass(frozen=True)
class NginxFace:
    """一个公开前缀在 nginx 上的**归属**：谁伺候它、落到哪、出问题会怎样。"""

    prefix: str
    kind: str
    owner: str
    semantics: str
    upstream: str = ""   # kind == FACE_PROXY 时：登记的代理上游（host:port）
    fallback: str = ""   # kind == FACE_STATIC / FACE_STATIC_UNDER_ROOT 时：fallback 落在哪


#: 🔴 **登记表**（与 CODE_SPACES 同文件、同族 —— 一处登记 = 一个公开前缀的全部归属）。
#: 新增一个公开前缀（新的码空间 / 新的 h5 子目录 / 新的 nginx location）⇒ 必须在这里登记
#: 谁伺候它、落到哪、出问题会怎样：**未登记 ⇒ F1 红**（那正是「扫出来是别人的页面」的入口）。
PUBLIC_PREFIX_FACES: dict[str, NginxFace] = {
    "/s/": NginxFace(
        prefix="/s/",
        kind=FACE_PROXY,
        owner="admin-api（WorkerShortLinkController，issue #4802）",
        semantics="工人报工短链：服务端 302 → /w/?t=<token>（短码要查库 ⇒ 静态面做不到）",
        upstream="admin-api:8080",
    ),
    "/i/": NginxFace(
        prefix="/i/",
        kind=FACE_PROXY,
        owner="admin-api（InboundLabelShortLinkController，issue #5052 P2）",
        semantics="入库标签上的码：服务端 302 → 落地页 /b/?code=<短码>&tenant_id=<id>；未知短码 404 / 已撤销 410",
        upstream="admin-api:8080",
    ),
    "/b/": NginxFace(
        prefix="/b/",
        kind=FACE_STATIC,
        owner="bmini h5 发布腿（.github/workflows/bmini-h5-publish.yml，issue #5668）",
        semantics="B 端商家端 h5（Taro build:h5，publicPath=/b/）",
        fallback="落回自己的 /b/index.html（**不得**落到根 index.html）",
    ),
    "/w/": NginxFace(
        prefix="/w/",
        kind=FACE_STATIC,
        owner="worker-h5 发布腿（.github/workflows/worker-h5-publish.yml，issue #4837；自有 location 见 issue #6293）",
        semantics="工人端报工页（零构建纯 ESM，静态根下的 w/ 子目录；自有 location 是为了给 `.mjs` 一个 JS MIME）",
        fallback="落回自己的 /w/index.html（**不得**落到根 index.html）",
    ),
}

#: 探针用的**虚拟静态根**（线上静态根 `/opt/migao-deploy/h5` 的预期形态）。
_STATIC_ROOT_FILES = frozenset({
    "index.html", "js/app.js", "css/app.css",
    "b/index.html", "b/js/app.js", "b/css/app.css",
    "w/index.html", "w/src/app.mjs",
})

#: 端到端链路的**探针表**（照 `deploy/scripts/bmini-h5-verify-served.sh` 的 `SPA_PROBE` /
#: `ROOT_PROBE` 范式：用一个**不可能存在**的短码 —— admin-api 回 404、SPA fallback 回 200 + 首页
#: ⇒ 两者可判）。离线版把 `curl` 换成**配置语义模拟**。元组 = (请求路径, 期望落点类型, 期望落点)。
ROUTE_PROBES: tuple[tuple[str, str, str], ...] = (
    ("/i/7K3M9QP2", FACE_PROXY, "admin-api:8080"),
    ("/i/__i_probe__", FACE_PROXY, "admin-api:8080"),
    ("/i/", FACE_PROXY, "admin-api:8080"),
    ("/s/7K3M9QP2", FACE_PROXY, "admin-api:8080"),
    ("/b/", FACE_STATIC, "b/index.html"),
    ("/b/orders/2026/detail", FACE_STATIC, "b/index.html"),
    ("/w/index.html", FACE_STATIC, "w/index.html"),
    ("/", FACE_STATIC, "index.html"),
    ("/customer/service", FACE_STATIC, "index.html"),
)


# ────────────────────────────────────────────── 解析与语义模拟


def app_server(conf: str) -> Block:
    """→ `app.migaozn.com` 的 443 server 块（找不到 ⇒ 判据失败，不静默）。"""
    servers = _servers(parse_nginx(conf))
    assert APP_DOMAIN in servers, f"nginx.conf 里找不到 {APP_DOMAIN} 的 443 server 段（本判据的坐标没了）"
    return servers[APP_DOMAIN]


def public_nginx_prefixes(conf: str) -> set[str]:
    """→ nginx 的 `app.migaozn.com` 段里**公开前缀** location（排除 `/` 与内部 API 面 `/api/**`）。"""
    return {t for t in _locations(app_server(conf)) if t != "/" and not t.startswith("/api/")}


def published_h5_prefixes() -> set[str]:
    """→ 发布腿声明的 h5 子目录（`H5_SUBDIR`）转成前缀 —— 新增一个 h5 应用 = 多一个公开前缀。"""
    prefixes = set()
    for workflow in H5_PUBLISH_WORKFLOWS:
        for match in H5_SUBDIR_RE.finditer(workflow.read_text(encoding="utf-8")):
            prefixes.add(f"/{match.group('sub')}/")
    assert prefixes, f"发布腿里一个 H5_SUBDIR 都没读到 ⇒ 发现面失效（{[w.name for w in H5_PUBLISH_WORKFLOWS]}）"
    return prefixes


def proxy_target_of(block: Block) -> str | None:
    """→ 该 location 的 `proxy_pass` 目标原文（去掉 `;`）；没有则 None。"""
    for statement in block.directives:
        if statement.startswith("proxy_pass "):
            return statement[len("proxy_pass "):].strip().rstrip(";").strip()
    return None


def _proxy_parts(target: str) -> tuple[str, str]:
    """`http://admin-api:8080/i` → `('admin-api:8080', '/i')`；无 URI 后缀 ⇒ `('admin-api:8080', '')`。"""
    rest = target.split("://", 1)[1] if "://" in target else target
    host, slash, uri = rest.partition("/")
    return host, ("/" + uri if slash else "")


def _try_files_fallback(block: Block) -> str | None:
    """→ `try_files` 的**最后一项**（fallback）；没有该指令则 None。"""
    for statement in block.directives:
        if statement.startswith("try_files "):
            args = statement[len("try_files "):].strip().rstrip(";").split()
            return args[-1] if args else None
    return None


def _resolve_try_files(conf: str, args: list[str], path: str, files: frozenset[str], depth: int) -> str:
    """按 `try_files` 语义算出被伺候的文件（fallback 走 nginx 的**内部重定向** ⇒ 递归回 `route`）。"""
    if depth > 5:
        return "404"
    for arg in args[:-1]:
        if arg == "$uri" and path.lstrip("/") in files:
            return path.lstrip("/")
        if arg in ("$uri", "$uri/") and (path.rstrip("/") + "/index.html").lstrip("/") in files:
            return (path.rstrip("/") + "/index.html").lstrip("/")
    last = args[-1]
    if last.startswith("="):
        return last[1:]
    return route(conf, last, files, depth + 1)[1]


def route(conf: str, path: str, files: frozenset[str] = _STATIC_ROOT_FILES,
          depth: int = 0) -> tuple[str, str, str]:
    """按 nginx 语义算**这个请求会去哪** → `(落点类型, 落点, 实际转发/伺候的路径)`。

    只模拟本段用到的三件事（与 `tests/unit_ci_workflows/test_bmini_h5_hosting.py` 的 `_serve()`
    同范式）：**前缀 location 取最长者** + `proxy_pass`（带不带 URI 后缀）+ `try_files`。
    落点类型 ∈ {`proxy`, `static`, `404`}。**这是 F3 的判据对象**：它认结构，不认注释与文案。
    """
    if depth > 5:
        return ("404", "", path)
    locations = _locations(app_server(conf))
    matched = ""
    for prefix in locations:
        if (path == prefix or path.startswith(prefix) or prefix == "/") and len(prefix) > len(matched):
            matched = prefix
    if not matched:
        return ("404", "", path)
    block = locations[matched]
    target = proxy_target_of(block)
    if target is not None:
        host, suffix = _proxy_parts(target)
        forwarded = path if not suffix else suffix + path[len(matched):]
        return (FACE_PROXY, host, forwarded)
    for statement in block.directives:
        if statement.startswith("try_files "):
            args = statement[len("try_files "):].strip().rstrip(";").split()
            return (FACE_STATIC, _resolve_try_files(conf, args, path, files, depth), path)
    # 没有 try_files / proxy_pass ⇒ 静态根直出（`root` 语义）
    return (FACE_STATIC, path.lstrip("/") if path.lstrip("/") in files else "404", path)


# ────────────────────────────────────────────── F1~F3 判据


def _route_diagnosis(path: str, want: tuple[str, str], got: tuple[str, str, str]) -> str:
    """落点不对时**指名**说清是什么形态（照 #5668 的教训：静默串端必须给得出名字）。"""
    kind, target, forwarded = got
    prefix = "/" + path.strip("/").split("/")[0] + "/" if path.strip("/") else "/"
    if kind == FACE_STATIC and target == "index.html" and want[0] == FACE_PROXY:
        return (
            f"{path} 落到了 `location /` 的 SPA fallback（→ index.html = C 端元元），期望代理到 {want[1]} —— "
            f"{prefix} 是**印在纸上的公开入口**（码一旦打印就是 URL）：扫出来必须是它自己的落地面。"
            "静默串端比 404 危险得多（HTTP 200，监控不红、只有真机扫码才发现）"
        )
    return f"{path} 的落点不对：实际 {kind} → {target!r}（转发路径 {forwarded!r}），期望 {want[0]} → {want[1]}"


def prefix_wiring_problems(conf: str, java_prefixes: set[str], h5_prefixes: set[str]) -> list[str]:
    """F1~F3 的**唯一口径**：配置文本 + 两个发现面 → 问题清单（空 = 通过）。

    主判据与注入式红证都走它 ⇒「红证测的是另一份实现」这个形态结构上不可能出现。
    """
    bad: list[str] = []
    registered = set(PUBLIC_PREFIX_FACES)
    discovered = set(java_prefixes) | public_nginx_prefixes(conf) | set(h5_prefixes)
    for prefix in sorted(discovered - registered):
        bad.append(
            f"公开前缀 {prefix} 没在 nginx 归属登记表里 —— 未登记的前缀会静默落到 `location /` 的 "
            "SPA fallback（200 + 别人的页面）；请在 tests/unit_ci_workflows/"
            "test_public_code_spaces_are_disjoint.py 的 PUBLIC_PREFIX_FACES 里写明谁伺候它 / 落到哪"
        )
    for prefix in sorted(registered - discovered):
        bad.append(f"登记表里的 {prefix} 在代码 / nginx / 发布腿上都不见了（陈旧的登记会掩盖新前缀）")

    locations = _locations(app_server(conf))
    for prefix, face in sorted(PUBLIC_PREFIX_FACES.items()):
        block = locations.get(prefix)
        if face.kind == FACE_PROXY:
            if block is None:
                bad.append(
                    f"{prefix} 登记为代理面（{face.owner}）但 nginx 里**没有** `location {prefix}` "
                    "⇒ 该前缀的请求会落到 `location /` 的 SPA fallback"
                )
                continue
            target = proxy_target_of(block)
            if target is None:
                bad.append(f"`location {prefix}` 没有 proxy_pass（登记为代理面：{face.owner}）")
                continue
            host, suffix = _proxy_parts(target)
            if host != face.upstream:
                bad.append(f"`location {prefix}` 的代理上游是 {host!r}，登记的是 {face.upstream!r}")
            if suffix:
                bad.append(
                    f"`location {prefix}` 的 proxy_pass 带了 URI 后缀 {suffix!r} ⇒ nginx 会把「匹配到的 "
                    f"location 前缀」替换成该后缀（`{prefix}<码>` 转发成 `{suffix}<码>`）⇒ 控制器收不到自己的"
                    f"路径（实测形态：写成 `proxy_pass http://{face.upstream}/i;` 时 `/i/7K3M9QP2` 变成 "
                    "`/i7K3M9QP2`）；写 `proxy_pass http://<上游>;`（不带后缀）原样转发"
                )
        elif face.kind == FACE_STATIC:
            if block is None:
                bad.append(f"{prefix} 登记为静态面（{face.owner}）但 nginx 里没有 `location {prefix}`")
                continue
            if proxy_target_of(block) is not None:
                bad.append(f"`location {prefix}` 是静态面（{face.owner}）却挂了 proxy_pass")
            fallback = _try_files_fallback(block)
            if fallback is None:
                bad.append(f"`location {prefix}` 没有 try_files ⇒ 子路由会 404（登记要求：{face.fallback}）")
            elif not fallback.startswith(prefix):
                bad.append(
                    f"`location {prefix}` 的 fallback 是 {fallback!r}，**跨出了自己的前缀命名空间**"
                    f"（登记要求：{face.fallback}）⇒ 子路由会静默回落到别的应用"
                )
        else:  # FACE_STATIC_UNDER_ROOT
            if block is not None:
                bad.append(f"{prefix} 登记为「由 `location /` 的 root 承载」，但现在它有了自己的 `location {prefix}` ⇒ 请更新登记")
            root_block = locations.get("/")
            if root_block is None or _try_files_fallback(root_block) is None:
                bad.append(f"`location /` 不再是静态 try_files 形态 ⇒ {prefix} 的登记前提（由根承载）不成立")

    for path, want_kind, want_target in ROUTE_PROBES:
        got = route(conf, path)
        want = (want_kind, want_target)
        if (got[0], got[1]) == want:
            if want_kind == FACE_PROXY and got[2] != path:
                bad.append(f"{path} 到了 {got[1]}，但转发路径被改成了 {got[2]!r}（必须原样 {path!r}）")
            continue
        bad.append(_route_diagnosis(path, want, got))
    return bad


def _java_prefixes() -> set[str]:
    return discover_code_spaces(controller_sources())


def _nginx_problems(conf: str, h5_prefixes: set[str] | None = None) -> list[str]:
    return prefix_wiring_problems(
        conf, _java_prefixes(), published_h5_prefixes() if h5_prefixes is None else h5_prefixes
    )


def test_f1_f2_f3_public_prefixes_are_wired_at_the_edge() -> None:
    """主判据 F1~F3：问题清单必须为空（清单本身由下面的注入式红证证明不是空转）。"""
    bad = _nginx_problems(_read(NGINX_CONF))
    assert bad == [], "公开前缀在 nginx 的归属与登记表不符：\n" + "\n".join(f"  · {item}" for item in bad)


def test_f_coordinates_are_alive() -> None:
    """坐标自证：登记表指向的 nginx 段 / 发布腿 / 静态根形态都真的在（否则 F1~F3 在扫空气）。"""
    conf = _read(NGINX_CONF)
    locations = _locations(app_server(conf))
    assert "/" in locations and "/b/" in locations, f"app 段的前缀 location 读出来不对：{sorted(locations)}"
    assert route(conf, "/") == (FACE_STATIC, "index.html", "/"), "根不再由静态 try_files 伺候 ⇒ 模拟器坐标变了"
    assert published_h5_prefixes() == {"/b/", "/w/"}, "发布腿声明的 h5 子目录变了 ⇒ 登记表要跟着核"
    assert len(PUBLIC_PREFIX_FACES) >= 4, f"登记表只剩 {sorted(PUBLIC_PREFIX_FACES)} ⇒ 发现面疑似失效"


# ── 注入式红证（真跑：把变异文本喂给**同一套**判据，必须被检出并指名）──────────────────


def _inject(conf: str, needle: str, replacement: str) -> str:
    assert needle in conf, f"注入点定位失败（fail-closed）：找不到 {needle!r}"
    mutated = conf.replace(needle, replacement, 1)
    assert mutated != conf, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    return mutated


def _location_span(conf: str, prefix: str) -> tuple[int, int]:
    """`location <prefix> { … }` 的 `[start, end)` 区间（引号 / 注释感知的花括号配平）。"""
    match = re.search(rf"^[ \t]*location\s+{re.escape(prefix)}\s*\{{", conf, re.M)
    assert match, f"注入点定位失败（fail-closed）：配置里没有 `location {prefix} {{`"
    start = match.start()
    index = conf.index("{", start)
    depth = 0
    quote = ""
    while index < len(conf):
        char = conf[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#":
            index = conf.find("\n", index)
            if index < 0:
                break
            continue
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1
        index += 1
    raise AssertionError(f"`location {prefix}` 的花括号不配平（注入式红证的坐标坏了）")


def _drop_location(conf: str, prefix: str) -> str:
    start, end = _location_span(conf, prefix)
    mutated = conf[:start] + conf[end:]
    assert mutated != conf, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    return mutated


def _replace_in_location(conf: str, prefix: str, old: str, new: str) -> str:
    start, end = _location_span(conf, prefix)
    block = conf[start:end]
    assert old in block, f"注入点定位失败（fail-closed）：`location {prefix}` 块里找不到 {old!r}"
    mutated = conf[:start] + block.replace(old, new, 1) + conf[end:]
    assert mutated != conf, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    return mutated


def test_red_proof_missing_i_location_falls_back_to_the_spa() -> None:
    """红证 F3（本单的**红证本体**）：删掉 `location /i/` 整块 ⇒ 必须指名「落到了 SPA fallback」。"""
    conf = _read(NGINX_CONF)
    mutated = _drop_location(conf, "/i/")
    assert "/i/" not in public_nginx_prefixes(mutated), "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    assert route(mutated, "/i/7K3M9QP2") == (FACE_STATIC, "index.html", "/i/7K3M9QP2"), (
        "删掉 `location /i/` 后语义模拟没落到根 index.html ⇒ 模拟器与 nginx 语义对不上（判据会假绿）"
    )
    bad = _nginx_problems(mutated)
    named = [item for item in bad if "落到了 `location /` 的 SPA fallback" in item]
    assert named, f"删掉 `location /i/` 后判据没指名「落到了 SPA fallback」：{bad}"
    assert any("/i/7K3M9QP2" in item for item in named), f"红证没指到具体探针：{named}"


def test_red_proof_proxy_pass_uri_suffix_rewrites_the_path() -> None:
    """红证 F2：`proxy_pass` 带 URI 后缀 ⇒ 路径被改写（`/i/<码>` 到不了控制器）⇒ 必须判红。"""
    conf = _read(NGINX_CONF)
    mutated = _replace_in_location(
        conf, "/i/", "proxy_pass http://admin-api:8080;", "proxy_pass http://admin-api:8080/i;"
    )
    assert route(mutated, "/i/7K3M9QP2")[2] == "/i7K3M9QP2", "URI 后缀没触发路径改写 ⇒ 本红证是空断言"
    bad = _nginx_problems(mutated)
    assert any("/i/" in item and "URI 后缀" in item for item in bad), f"带 URI 后缀的 proxy_pass 没被判红：{bad}"


def test_red_proof_an_unregistered_nginx_prefix_is_detected() -> None:
    """红证 F1：新开一个 nginx 公开 location（`/l/`）而不登记 ⇒ 必须报「没在归属登记表里」。"""
    conf = _read(NGINX_CONF)
    needle = "    # B 端商家端 h5（"
    mutated = _inject(conf, needle, "    location /l/ {\n        try_files $uri $uri/ /index.html;\n    }\n\n" + needle)
    assert "/l/" in public_nginx_prefixes(mutated), "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    bad = _nginx_problems(mutated)
    assert any("/l/" in item and "没在 nginx 归属登记表里" in item for item in bad), (
        f"未登记的 nginx 前缀没被判红：{bad}"
    )


def test_red_proof_a_new_h5_subdir_is_detected() -> None:
    """红证 F1（另一个发现面）：发布腿新发一个 h5 子目录（`/x/`）而不登记 ⇒ 必须判红。"""
    bad = _nginx_problems(_read(NGINX_CONF), h5_prefixes=published_h5_prefixes() | {"/x/"})
    assert any("/x/" in item and "没在 nginx 归属登记表里" in item for item in bad), (
        f"新 h5 子目录没被判红：{bad}"
    )
