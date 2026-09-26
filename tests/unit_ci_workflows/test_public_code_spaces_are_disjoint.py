# case_ids: PR-113, PR-114
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

外加两条载体判据：**落地页地址不得硬编码域名**（必须来自配置）、**两个空间不得共用一个入口类**。

## 边界（如实登记）

* 本守卫是**静态**的：它不证明「扫 `/i/` 真的不会进报工页」—— 那一半由
  `SecurityConfigTest`（真安全链 + 真控制器 302）与
  `InboundLabelSurfaceGuardTest`（源码互斥）承担。
* 前缀形态只覆盖**单字母 + `/{...}`** 这一种公开短码入口形态（本仓现有两个都是这个形态）；
  换形态（如 `/label/{码}`）不会被本守卫发现 —— 那属于「新增一种载体」，需人来补判据。
"""
from __future__ import annotations

import re
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
