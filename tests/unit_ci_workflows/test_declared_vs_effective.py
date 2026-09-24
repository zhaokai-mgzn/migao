# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 test_realdb_failclosed.py / test_guard_parsing_is_comment_aware.py 的同款声明与
#   `.github/cases/misc.yml` MC-012 的登记。本 PR 不新建用例族。）
r"""「声明的位置」必须等于「实际生效的位置」—— 同族元守卫（issue #4185 / #4866 / #5327）。

## 病根（一类缺陷，不是三个缺陷）

`#4185`（`snapshotPathTemplate` 写在 Playwright 的 `use:` 里 ⇒ **静默忽略**，而注释宣称基线在
`__screenshots__`）、`#5327`（跨租户隔离只有 mocked 判据 ⇒ **真 SQL 从未执行**）、
`#4866`（吊销检查 `catch` 里 `return false` ⇒ Redis 异常时「默认放行」）三者的共同形态：
**「看起来有护栏 / 有真值」与「实际生效的护栏 / 真值」脱节**，而**任何门禁都不会因此变红**。

本文件把这三条形态各钉成一条**常驻判据**；判据面与台账数据在
`tests/unit_ci_workflows/declared_effective_registry.json`（与 `guard_parsing_allowlist.json` 同款口径：
**未登记即红 / 台账只许缩短 / 条数现取**）。

### 一、`silently_ignored_keys`：会被静默忽略的键位
`use:` 下的 `snapshotPathTemplate` 之类 ⇒ 命中即红。同时钉「视觉基线的**声明位置 == 生效位置**」：
基线目录与文件名由**生效模板**（声明的有效作用域模板，或 Playwright 默认模板）**算出来**，
再与磁盘上的现取文件集**逐字比对**（两个方向都比：缺一个 / 多一个都红）。模型自身也被反向验证
—— 现取文件集算不出来时**判红**（不给「模型过期还照样绿」的口子）。

### 二、`security_assertion_trust`：安全断言的可信度等级
每条安全相关断言必须登记等级（`realdb` / `mocked` / `unit`）。`mocked` 级 = 结论依赖数据访问行为
而证据只来自 mock ⇒ **必须有单号或真库对等判据**（= 降级登记）。等级声明与现取证据（真库收口
标记 / mock 标记 / 数据访问标记）不符 ⇒ 红。

### 三、`security_degradation`：安全面的降级方向
每个「`catch` 里出现布尔字面量 `return`」或「方法名含 `blacklist|revok|logout`」的 catch 块站点
必须登记方向（`fail-closed` / `fail-open`）。`fail-open` 必须有单号；登记了 `observability_required`
的站点**不许静默** —— 必须同时留 `log.error` 与 Micrometer counter，且两处字面量必须一致。

## 判据只读「代码」，不读文案
Java 侧先剥注释与字符串/字符字面量（`_strip_java`），TS 侧同理（`_strip_ts`），且**保留换行**
（偏移与行号不变）—— 否则注释里写一句「我 fail-closed」就能把判据喂绿（`migao-dev-flow` §17.3 家族）。

## 残余（照实登记，见 PR body）
① 一、的键位知识库是**人工登记**的：`use:` 之外还存在别的「会被静默忽略」的键位时，得先有人想到登记；
② 二、的判据面按**文件名**取（`CrossTenant|TenantIsolation|ConcurrentTenant|Isolation|Jwt|Revoke|Blacklist`）
   + `extra_surface` 显式登记 ⇒ 名字不含关键词的安全断言仍在面外；
③ 三、的判据面只覆盖 `security/**` + `service/AuthService.java` 里上面那两类 catch 块；其余「吞掉继续」
   的 catch（解析、取名、取 logo 等）不在面内（它们不改变「是否放行」的判定）；
④ `unit` 等级的「不涉数据访问」由代码标记（`Mapper` / `SqlSession` / `DataSource` / `@SpringBootTest` /
   `PgCluster`）反向佐证 ⇒ 标记之外的形态可能漏判（**假绿方向**，不会误伤）；
⑤ `{platform}` 面只验 `darwin` / `linux` 两个已入库平台（见台账 `platforms`）。

判据 = 本文件；一键复算：
`python3 -m pytest tests/unit_ci_workflows/test_declared_vs_effective.py -q -s`
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SELF_REL = "tests/unit_ci_workflows/test_declared_vs_effective.py"
REGISTRY_PATH = REPO_ROOT / "tests" / "unit_ci_workflows" / "declared_effective_registry.json"

#: 目录级跳过（扫描面用；`test-results/` 是 Playwright 的产物目录，不是基线）
SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".next",
        "dist",
        "build",
        "coverage",
        "test-results",
        ".venv",
        "venv",
        "__pycache__",
    }
)

#: Playwright 默认快照模板（`snapshotDir` 默认 = `testDir`）—— 只在配置**没有**在生效作用域里
#: 声明模板时使用。本仓现取基线文件名与该模型逐字相符（见 `test_baseline_files_match_effective_template`）。
DEFAULT_TEMPLATE = "{testDir}/{testFileDir}/{testFileName}-snapshots/{arg}{-projectName}{-snapshotSuffix}{ext}"

#: 受限模板模型的占位符集合（不在集合内 ⇒ 判红，不猜）
TEMPLATE_KEYS = frozenset(
    {
        "testDir",
        "testFileDir",
        "testFileName",
        "testFileBaseName",
        "arg",
        "ext",
        "projectName",
        "snapshotSuffix",
        "platform",
        "snapshotDir",
        "testFilePath",
    }
)

#: 「安全相关断言」的**文件名面**（残留②见模块 docstring）
TRUST_NAME_RULE = re.compile(r"(CrossTenant|TenantIsolation|ConcurrentTenant|Isolation|Jwt|Revoke|Blacklist)")

#: 真库收口标记（本仓单一收口：`PgCluster.startOrAbort()` / 共用夹具 `RemnantTestDb`）
REALDB_MARKERS = ("PgCluster.startOrAbort(", "RemnantTestDb")
#: mock 标记
MOCK_MARKERS = ("@Mock", "@MockBean", "Mockito.", "mock(", "@InjectMocks")
#: 数据访问标记（`unit` 等级的反向佐证）
DB_MARKERS = ("Mapper", "SqlSession", "DataSource", "@SpringBootTest", "PgCluster")

#: 降级方向判据面里的「吊销路径」方法名
REVOCATION_METHOD = re.compile(r"(blacklist|revok|logout)", re.IGNORECASE)

_ISSUE_RE = re.compile(r"#\d{3,}")
_METHOD_DECL = re.compile(r"\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:throws\s+[\w.,\s]+)?\{")
_NOT_A_METHOD = frozenset(
    {"if", "for", "while", "switch", "catch", "try", "synchronized", "do", "else", "return", "new"}
)


# ══════════════════════════════════════════════════════════════════════════════
# 一、注释 / 字符串剥离（**保留换行** ⇒ 偏移与行号不变）
# ══════════════════════════════════════════════════════════════════════════════


def _blank_char(out: list[str], index: int) -> None:
    """把该位置换成空白（**保留换行** ⇒ 剥离后偏移与行号不变）。"""
    if out[index] != "\n":
        out[index] = " "


def _scan_literal(text: str, out: list[str], start: int, quote: str, allow_newline: bool) -> int:
    """扫一个字符串/字符/模板字面量（含转义）并整段抹白，返回结束后下标。

    ⛔ 不用正则（`'\"'` 这类字符字面量会把「按引号配对」的剥离器带进级联误剥 ⇒ 括号计数失真，
    实测把 `SecurityConfig` 数出 17 个 `{` / 15 个 `}`）。
    """
    i = start
    _blank_char(out, i)
    i += 1
    while i < len(text):
        char = text[i]
        if char == "\\":
            _blank_char(out, i)
            if i + 1 < len(text):
                _blank_char(out, i + 1)
            i += 2
            continue
        if char == quote:
            _blank_char(out, i)
            return i + 1
        if char == "\n" and not allow_newline:
            return i
        _blank_char(out, i)
        i += 1
    return i


def _strip_code(text: str, *, template_literals: bool) -> str:
    """按**字符状态机**剥掉注释与字面量（Java / TS 共用；顺序即扫描顺序，不会级联误剥）。"""
    out = list(text)
    i = 0
    while i < len(text):
        char = text[i]
        if char == "/" and text.startswith("//", i):
            while i < len(text) and text[i] != "\n":
                _blank_char(out, i)
                i += 1
        elif char == "/" and text.startswith("/*", i):
            _blank_char(out, i)
            _blank_char(out, i + 1)
            i += 2
            while i < len(text) and not text.startswith("*/", i):
                _blank_char(out, i)
                i += 1
            for _ in range(2):
                if i < len(text):
                    _blank_char(out, i)
                    i += 1
        elif char == '"':
            i = _scan_literal(text, out, i, '"', allow_newline=False)
        elif char == "'":
            i = _scan_literal(text, out, i, "'", allow_newline=False)
        elif char == "`" and template_literals:
            i = _scan_literal(text, out, i, "`", allow_newline=True)
        else:
            i += 1
    return "".join(out)


def _strip_ts(text: str) -> str:
    return _strip_code(text, template_literals=True)


def _strip_java(text: str) -> str:
    return _strip_code(text, template_literals=False)


def _line_of(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1


def _block_end(text: str, open_idx: int) -> int:
    """从 `{` 起做括号配对（文本必须已剥注释与字面量，否则 JSDoc 里的花括号会把配对带偏）。"""
    depth = 0
    i = open_idx
    while i < len(text):
        char = text[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise AssertionError(f"括号未闭合（偏移 {open_idx}）—— 判据面文本被改坏或剥离器失效")
def _bracket_end(text: str, open_idx: int) -> int:
    """从 `[` / `(` 起做配对（同上，文本必须先剥离注释与字面量）。"""
    opening = text[open_idx]
    closing = {"[": "]", "(": ")"}[opening]
    depth = 0
    i = open_idx
    while i < len(text):
        char = text[i]
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise AssertionError(f"括号未闭合（偏移 {open_idx}）—— 判据面文本被改坏或剥离器失效")


def _top_level_keys(text: str, body_start: int, body_end: int) -> dict[str, int]:
    """取对象字面量**直接子级**的 `键:`（深度 > 0 的不算，避免把嵌套对象/函数体的键算进来）。"""
    keys: dict[str, int] = {}
    depth = 0
    i = body_start
    while i < body_end:
        char = text[i]
        if char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
        elif depth == 0:
            key = re.match(r"[A-Za-z_$][\w$]*\s*:", text[i:])
            if key:
                keys[key.group(0)[:-1].strip()] = i
                i += key.end()
                continue
        i += 1
    return keys


def _quoted_value(text: str, offset: int) -> str | None:
    """在**原文**的 `offset` 之后取一个字符串字面量的值（先跳空白 —— 剥离后的值全是空白）。

    ⚠️ 偏移必须取自**只吃到锚点**（`:` 或 `(`）的正则：若锚点正则自己吃掉尾随 `\\s*`，
    它会把被抹白的字面量整段吞掉 ⇒ 偏移落到下一个键上（实测踩过，取到的是 `testMatch`）。
    """
    match = re.match(r'''\s*(["'])(.*?)\1''', text[offset:], flags=re.DOTALL)
    return match.group(2) if match else None


def _js_regex_literal(text: str, offset: int) -> str | None:
    """取 JS 正则字面量（`/.../`，**只认无 flag**；带 flag ⇒ 抛错 = 判红，不猜）。"""
    i = offset
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text) or text[i] != "/":
        return None
    i += 1
    out: list[str] = []
    while i < len(text):
        char = text[i]
        if char == "\\":
            out.append(text[i : i + 2])
            i += 2
            continue
        if char == "/":
            break
        out.append(char)
        i += 1
    tail = text[i + 1 : i + 2]
    if tail.isalpha():
        raise AssertionError(f"正则字面量带 flag（{tail!r}）—— 受限模型不认，判红而不是猜")
    return "".join(out)


def _registry() -> dict[str, object]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "台账根必须是对象"
    return data


# ══════════════════════════════════════════════════════════════════════════════
# 二、Playwright 配置面：会被静默忽略的键位 + 声明位置 == 生效位置
# ══════════════════════════════════════════════════════════════════════════════


@lru_cache(maxsize=1)
def _playwright_configs() -> tuple[Path, ...]:
    """按**剪枝后的目录走查**取配置（不进 node_modules / .git / dist ⇒ 判据自身不做成本项）。"""
    found: list[Path] = []
    for root, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.startswith("playwright") and name.endswith(".config.ts"):
                found.append(Path(root) / name)
    return tuple(sorted(found))


def _use_blocks(path: Path) -> tuple[str, str, list[tuple[int, int, dict[str, int]]]]:
    """返回 (原文, 剥离后文本, [(use 块起点, 终点, 直接子级键→偏移)])。"""
    source = path.read_text(encoding="utf-8")
    stripped = _strip_ts(source)
    blocks = []
    for match in re.finditer(r"\buse\s*:\s*\{", stripped):
        open_idx = stripped.index("{", match.start())
        end = _block_end(stripped, open_idx)
        blocks.append((open_idx, end, _top_level_keys(stripped, open_idx + 1, end)))
    return source, stripped, blocks


def _effective_templates(path: Path) -> list[tuple[str, int]]:
    """生效作用域（顶层 / project 级，即**不在** `use:` 块内）声明的快照模板。"""
    source, stripped, blocks = _use_blocks(path)
    use_ranges = [(start, end) for start, end, _keys in blocks]
    found: list[tuple[str, int]] = []
    for match in re.finditer(r"\bsnapshotPathTemplate\s*:", stripped):
        if any(start <= match.start() <= end for start, end in use_ranges):
            continue  # `use:` 里的声明 ⇒ 由 test_use_block_has_no_silently_ignored_keys 判红
        value = _quoted_value(source, match.end())
        if value is None:
            raise AssertionError(f"{path} 的 snapshotPathTemplate 不是字符串字面量 ⇒ 无法判定生效位置")
        found.append((value, match.start()))
    return found


def _template_variables(path: Path, spec: Path, project: str | None, arg: str, ext: str, platform: str) -> dict[str, str]:
    config_dir = path.parent
    test_dir = _config_test_dir(path)
    test_file_dir = spec.parent.relative_to(test_dir).as_posix() if test_dir in spec.parents else "."
    return {
        "testDir": test_dir.as_posix(),
        "snapshotDir": test_dir.as_posix(),
        "testFileDir": test_file_dir,
        "testFileName": spec.name,
        "testFileBaseName": spec.stem,
        "testFilePath": spec.relative_to(test_dir).as_posix(),
        "arg": arg,
        "ext": ext,
        "projectName": project or "",
        "snapshotSuffix": platform,
        "platform": platform,
    }


def _config_test_dir(path: Path) -> Path:
    source = path.read_text(encoding="utf-8")
    stripped = _strip_ts(source)
    match = re.search(r"\btestDir\s*:", stripped)
    if not match:
        raise AssertionError(f"{path} 没有 testDir ⇒ 无法判定基线位置（判红而不是猜）")
    value = _quoted_value(source, match.end())
    if value is None:
        raise AssertionError(f"{path} 的 testDir 不是字符串字面量 ⇒ 无法判定基线位置")
    return (path.parent / value).resolve()


def _resolve_template(template: str, variables: dict[str, str]) -> str:
    """受限模板模型：只认 `TEMPLATE_KEYS` 内的占位符，不认 ⇒ 抛错（判红，不猜）。"""
    out: list[str] = []
    pos = 0
    for match in re.finditer(r"\{-?([A-Za-z]+)\}", template):
        key = match.group(1)
        if key not in TEMPLATE_KEYS:
            raise AssertionError(f"模板占位符 {{{key}}} 不在受限模型内（不猜）：{template!r}")
        out.append(template[pos : match.start()])
        out.append(("-" if match.group(0).startswith("{-") else "") + variables[key])
        pos = match.end()
    out.append(template[pos:])
    return "".join(out)


@lru_cache(maxsize=1)
def _baseline_dirs() -> tuple[Path, ...]:
    """现取的视觉基线目录（`*-snapshots` / `__screenshots__`，剪枝走查）。"""
    found: list[Path] = []
    for root, dirnames, _filenames in os.walk(REPO_ROOT):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        for name in dirnames:
            if name.endswith("-snapshots") or name == "__screenshots__":
                found.append(Path(root) / name)
    return tuple(sorted(found))


def _projects_of(path: Path) -> list[tuple[str, str | None]]:
    """取配置的 projects：[(project 名, 该项目自己的 testMatch 正则或 None)]。"""
    source, stripped, _blocks = _use_blocks(path)
    match = re.search(r"\bprojects\s*:\s*\[", stripped)
    if not match:
        return []
    open_idx = stripped.index("[", match.start())
    end = _bracket_end(stripped, open_idx)
    projects: list[tuple[str, str | None]] = []
    for block in re.finditer(r"\{", stripped[open_idx:end]):
        body_open = open_idx + block.start()
        body_end = _block_end(stripped, body_open)
        body = stripped[body_open:body_end]
        name_match = re.search(r"\bname\s*:", body)
        if not name_match:
            continue
        name = _quoted_value(source, body_open + name_match.end())
        if name is None:
            raise AssertionError(f"{path} 的 project name 不是字符串字面量")
        tm_match = re.search(r"\btestMatch\s*:", body)
        test_match = (
            _js_regex_literal(source, body_open + tm_match.end()) if tm_match else None
        )
        projects.append((name, test_match))
    return projects


def _config_test_match(path: Path) -> str | None:
    source, stripped, _blocks = _use_blocks(path)
    match = re.search(r"\btestMatch\s*:", stripped)
    return _js_regex_literal(source, match.end()) if match else None


def _owning_config(spec: Path) -> Path | None:
    owners = []
    for config in _playwright_configs():
        test_dir = _config_test_dir(config)
        if test_dir == spec.parent or test_dir in spec.parents:
            owners.append(config)
    if len(owners) > 1:
        raise AssertionError(f"{spec} 同时落在多个配置的 testDir 内，无法判定生效模板：{[str(o) for o in owners]}")
    return owners[0] if owners else None


def _screenshot_names(spec: Path) -> list[str]:
    """spec 里 `toHaveScreenshot('名')` 的**字面量**名（非字面量 ⇒ 抛错 = 判红，不猜）。"""
    source = spec.read_text(encoding="utf-8")
    stripped = _strip_ts(source)
    names: list[str] = []
    for match in re.finditer(r"\btoHaveScreenshot\s*\(", stripped):
        name = _quoted_value(source, match.end())
        if name is None:
            raise AssertionError(
                f"{spec.name} 有一处 toHaveScreenshot 的基线名不是字符串字面量 ⇒ 无法判定基线文件（判红而不是猜）"
            )
        names.append(name)
    return names


def _project_for_spec(config: Path, spec: Path) -> str | None:
    candidates = []
    for name, own_match in _projects_of(config):
        pattern = own_match or _config_test_match(config)
        if pattern is None:
            continue
        rel = spec.relative_to(REPO_ROOT).as_posix()
        for candidate in (rel, spec.relative_to(_config_test_dir(config)).as_posix()):
            if re.search(pattern, candidate):
                candidates.append(name)
                break
    if len(candidates) > 1:
        raise AssertionError(f"{spec} 命中多个 project（{candidates}）⇒ 基线文件名歧义，判红而不是猜")
    return candidates[0] if candidates else None


def _predicted_baselines(site: dict[str, object]) -> set[str]:
    """按**生效模板**算出该站点的基线文件名集合（平台逐一出）。"""
    config = REPO_ROOT / str(site["config"])
    spec = REPO_ROOT / str(site["spec"])
    dir_path = REPO_ROOT / str(site["dir"])
    declared = _effective_templates(config)
    if len(declared) > 1:
        raise AssertionError(f"{config} 在生效作用域里声明了多个 snapshotPathTemplate ⇒ 无法判定")
    template = declared[0][0] if declared else DEFAULT_TEMPLATE
    project = _project_for_spec(config, spec)
    predicted: set[str] = set()
    for name in _screenshot_names(spec):
        stem, dot, ext = name.rpartition(".")
        arg, suffix = (stem, f".{ext}") if dot else (name, "")
        for platform in site["platforms"]:  # type: ignore[union-attr]
            variables = _template_variables(config, spec, project, arg, suffix, platform)
            resolved = Path(_resolve_template(template, variables))
            if resolved.parent.resolve() != dir_path.resolve():
                raise AssertionError(
                    f"生效模板算出的目录 {resolved.parent} != 台账登记目录 {dir_path} ⇒ 声明位置与生效位置不一致"
                )
            predicted.add(resolved.name)
    return predicted


def _trust_surface() -> set[str]:
    """安全断言的可信度判据面 = 文件名面（`TRUST_NAME_RULE`）∪ 台账 `extra_surface` 的显式登记。"""
    registry = _registry()
    base = REPO_ROOT / "backend" / "admin-api" / "src" / "test" / "java"
    found = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in base.rglob("*Test.java")
        if TRUST_NAME_RULE.search(path.name) and not (SKIP_DIRS & set(path.parts))
    }
    extra = registry.get("extra_surface") or []
    assert isinstance(extra, list), "extra_surface 必须是数组"
    for entry in extra:
        found.add(str(entry["site"]))
    return found


# ══════════════════════════════════════════════════════════════════════════════
# 三、安全面的 catch 降级方向
# ══════════════════════════════════════════════════════════════════════════════


def _degradation_sources() -> tuple[Path, ...]:
    registry = _registry()
    section = registry["security_degradation"]
    assert isinstance(section, dict), "security_degradation 必须是对象"
    raw = section["surface"]
    assert isinstance(raw, list) and raw, "security_degradation.surface 必须是非空数组"
    files: set[Path] = set()
    for item in raw:
        text = str(item)
        if text.endswith("/**"):
            files.update(p for p in (REPO_ROOT / text[:-3]).rglob("*.java") if not (SKIP_DIRS & set(p.parts)))
        else:
            files.add(REPO_ROOT / text)
    return tuple(sorted(files))


def _method_bodies(stripped: str) -> list[tuple[str, int, int]]:
    """[(方法名, 方法体起点, 方法体终点)]。"""
    bodies = []
    for match in _METHOD_DECL.finditer(stripped):
        name = match.group(1)
        if name in _NOT_A_METHOD:
            continue
        open_idx = match.end() - 1
        bodies.append((name, open_idx, _block_end(stripped, open_idx)))
    return bodies


def _catch_bodies(stripped: str) -> list[tuple[str, str, str]]:
    """[(方法名, catch 体文本, 整个 catch 块文本)]。"""
    bodies = _method_bodies(stripped)
    out = []
    for match in re.finditer(r"\bcatch\s*\([^)]*\)\s*\{", stripped):
        open_idx = stripped.index("{", match.start())
        end = _block_end(stripped, open_idx)
        owners = [
            (name, start, stop)
            for name, start, stop in bodies
            if start < open_idx < stop
        ]
        if not owners:
            raise AssertionError(f"catch（偏移 {open_idx}）找不到所属方法 ⇒ 判据面坐标不可信")
        name = min(owners, key=lambda item: item[2] - item[1])[0]
        out.append((name, stripped[open_idx + 1 : end], stripped[match.start() : end + 1]))
    return out


@lru_cache(maxsize=1)
def _degradation_sites() -> dict[str, dict[str, object]]:
    """现取的降级判定站点：{`相对路径::方法名`: {catch_blocks, return_literals, bodies}}。

    面内规则（结构性，不看文案）：catch 体里出现**布尔字面量 return**（= 对「是否放行」做了默认判定），
    或所在方法名匹配 `blacklist|revok|logout`（吊销/登出路径上的吞异常）。
    """
    sites: dict[str, dict[str, object]] = {}
    for path in _degradation_sources():
        rel = path.relative_to(REPO_ROOT).as_posix()
        stripped = _strip_java(path.read_text(encoding="utf-8"))
        per_method: dict[str, list[tuple[list[str], str]]] = {}
        for method, body, whole in _catch_bodies(stripped):
            literals = re.findall(r"\breturn\s+(true|false)\s*;", body)
            if not literals and not REVOCATION_METHOD.search(method):
                continue  # 面外（残余③）
            per_method.setdefault(method, []).append((literals, whole))
        for method, entries in per_method.items():
            sites[f"{rel}::{method}"] = {
                "catch_blocks": len(entries),
                "return_literals": [lit for literals, _whole in entries for lit in literals],
                "bodies": [whole for _literals, whole in entries],
                "source": path,
            }
    return sites


def _effective_template_of(config: Path) -> tuple[str, str]:
    """生效模板 + 它的来源（`declared` / `default(Playwright)`）。"""
    declared = _effective_templates(config)
    if len(declared) > 1:
        raise AssertionError(f"{config} 在生效作用域里声明了多个 snapshotPathTemplate ⇒ 无法判定")
    if declared:
        return declared[0][0], "declared"
    return DEFAULT_TEMPLATE, "default(Playwright)"


# ══════════════════════════════════════════════════════════════════════════════
# 判据
# ══════════════════════════════════════════════════════════════════════════════


def test_playwright_config_surface_is_not_empty() -> None:
    """判据面必须取得到（取空 ⇒ 本守卫会静默空跑成绿）。"""
    configs = _playwright_configs()
    print(f"判据面（现取）：{len(configs)} 个 playwright 配置 —— {[p.relative_to(REPO_ROOT).as_posix() for p in configs]}")
    assert configs, "取不到任何 `playwright*.config.ts` ⇒ 判据面失效（会静默空跑成绿）"
    assert _baseline_dirs(), "取不到任何视觉基线目录（`*-snapshots` / `__screenshots__`）⇒ 判据面失效"


def test_use_block_has_no_silently_ignored_keys() -> None:
    """`use:` 里出现**已知会被静默忽略**的键位 ⇒ 红（issue #4185；台账 = `silently_ignored_keys`）。"""
    registry = _registry()
    entries = {str(entry["key"]): entry for entry in registry["silently_ignored_keys"]}
    assert entries, "`silently_ignored_keys` 台账为空 ⇒ 本判据会静默空跑成绿"
    problems = []
    block_count = 0
    for path in _playwright_configs():
        source, _stripped, blocks = _use_blocks(path)
        rel = path.relative_to(REPO_ROOT).as_posix()
        for _start, _end, keys in blocks:
            block_count += 1
            for key, offset in sorted(keys.items()):
                entry = entries.get(key)
                if entry is None:
                    continue
                problems.append(
                    f"{rel}:{_line_of(source, offset)}  `{key}` 写在 `use:` 里 ⇒ Playwright **静默忽略**它"
                    f"（台账：{entry['reason']}；{entry['issue']}；证据：{entry['evidence']}）"
                )
    print(f"判据面（现取）：{len(_playwright_configs())} 个配置 / {block_count} 个 `use:` 块 / 台账键位 {len(entries)} 条")
    assert not problems, (
        "声明式配置里出现**会被静默忽略**的键位（写了等于没写，而注释/README 常把它当真值）：\n"
        + "\n".join(f"  {p}" for p in problems)
        + "\n修法：① 删掉该键（若默认行为就是你要的）；或 ② 挪到**真正生效的作用域**（顶层 / project 级），"
        "并确认生效路径可被本判据复算出来。\n"
        f"台账：{REGISTRY_PATH.relative_to(REPO_ROOT).as_posix()}"
    )


def test_effective_snapshot_template_is_platform_aware() -> None:
    """生效作用域里声明的快照模板**必须带平台占位符**（否则双平台基线互相覆盖，issue #4185 判据 3①）。"""
    registry = _registry()
    platform_keys = [str(item) for item in registry["platform_placeholders"]]
    problems = []
    for path in _playwright_configs():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for template, offset in _effective_templates(path):
            source = path.read_text(encoding="utf-8")
            if not any(key in template for key in platform_keys):
                problems.append(
                    f"{rel}:{_line_of(source, offset)}  生效模板 {template!r} 不含平台占位符 {platform_keys}"
                    " ⇒ darwin / linux 基线会**互相覆盖**（本仓两个平台各有基线）"
                )
    assert not problems, "生效的快照模板必须平台感知：\n" + "\n".join(f"  {p}" for p in problems)


def test_baseline_sites_are_registered() -> None:
    """现取基线目录 == 台账（未登记 / 陈旧双向都红；台账只许缩短）。"""
    registry = _registry()
    registered = {str(entry["dir"]) for entry in registry["baseline_sites"]}
    live = {path.relative_to(REPO_ROOT).as_posix() for path in _baseline_dirs()}
    problems = []
    for extra in sorted(live - registered):
        problems.append(f"{extra}：现取基线目录**未登记** ⇒ 基线挪位/新增必须同批登记（含它的生效模板与平台集合）")
    for stale in sorted(registered - live):
        problems.append(f"{stale}：台账条目**已陈旧**（该目录已不存在）⇒ 只许缩短，删掉该条目")
    print(f"[燃尽锚点 baseline_sites] 台账={len(registered)} / 现取={len(live)} —— {sorted(live)}")
    assert not problems, "基线目录与台账不一致：\n" + "\n".join(f"  {p}" for p in problems)


def test_baseline_files_match_effective_template() -> None:
    """**声明位置 == 生效位置**：按生效模板算出的基线文件名，必须与磁盘现取文件集逐字相符。

    这是 issue #4185 的实例判据：配置里「声称」的路径不算数，**算得出来的那个路径**才算数。
    两个方向都比（缺一个 / 多一个都红）⇒ 模型本身也被现取文件集反向验证（模型过期不会假装绿）。
    """
    registry = _registry()
    problems = []
    for site in registry["baseline_sites"]:
        dir_path = REPO_ROOT / str(site["dir"])
        if not dir_path.is_dir():
            continue  # 陈旧条目由 test_baseline_sites_are_registered 报
        config = REPO_ROOT / str(site["config"])
        template, origin = _effective_template_of(config)
        predicted = _predicted_baselines(site)
        actual = {path.name for path in dir_path.iterdir() if path.is_file()}
        print(
            f"  {site['dir']}：生效模板来源={origin}，模板={template!r}，"
            f"算出 {len(predicted)} 个 / 现取 {len(actual)} 个"
        )
        for name in sorted(predicted - actual):
            problems.append(f"{site['dir']}：生效模板算出的基线**缺失** —— {name}")
        for name in sorted(actual - predicted):
            problems.append(
                f"{site['dir']}：有**生效模板算不出来**的文件 —— {name}"
                "（要么基线来路不明，要么本判据的模型已过期 —— 两种都不许当通过）"
            )
    assert not problems, (
        "视觉基线的「声明位置」与「实际生效位置」不一致（issue #4185 的形态：注释声称一处、断言读另一处）：\n"
        + "\n".join(f"  {p}" for p in problems)
        + "\n修法：先确认**生效**路径（本判据打印的模板就是它），再把基线放到那里 / 或把模板挪到生效作用域。"
    )


def test_trust_surface_is_registered() -> None:
    """安全相关断言的**可信度等级**未登记 ⇒ 红（issue #5327 的形态：证据强度没人登记过）。"""
    registry = _registry()
    entries = {str(entry["site"]) for entry in registry["security_assertion_trust"]}
    surface = _trust_surface()
    assert surface, "可信度判据面取空 ⇒ 本判据会静默空跑成绿"
    unregistered = sorted(surface - entries)
    print(f"[燃尽锚点 security_assertion_trust] 判据面={len(surface)} / 台账={len(entries)}")
    assert not unregistered, (
        "安全相关断言**未登记可信度等级**：\n"
        + "\n".join(f"  {p}" for p in unregistered)
        + "\n修法（二选一）：① 补**真库**判据后登记 `trust=realdb`；"
        "② 登记 `trust=mocked`（或 `unit`）+ `reason` + **单号**或**真库对等判据**。"
        "台账只许缩短，不许加兜底条目。\n"
        f"台账：{REGISTRY_PATH.relative_to(REPO_ROOT).as_posix()}"
    )


def test_trust_ledger_entries_are_live() -> None:
    """台账条目必须对应现取判据面上的文件（陈旧 ⇒ 红；台账只许缩短）。"""
    registry = _registry()
    registered = {str(entry["site"]) for entry in registry["security_assertion_trust"]}
    surface = _trust_surface()
    stale = sorted(registered - surface)
    assert not stale, (
        "可信度台账条目**已陈旧**（该文件已不在判据面上：改名 / 删除 / 移出安全面）⇒ 删掉条目：\n"
        + "\n".join(f"  {p}" for p in stale)
    )


def test_trust_level_matches_current_evidence() -> None:
    """等级声明必须与现取证据相符；`mocked` 级（= 降级）必须有单号或真库对等判据。"""
    registry = _registry()
    realdb_entries = {
        str(entry["site"]) for entry in registry["security_assertion_trust"] if str(entry["trust"]) == "realdb"
    }
    problems = []
    for entry in registry["security_assertion_trust"]:
        rel = str(entry["site"])
        path = REPO_ROOT / rel
        if not path.is_file():
            continue  # 陈旧条目由 test_trust_ledger_entries_are_live 报
        code = _strip_java(path.read_text(encoding="utf-8"))
        trust = str(entry["trust"])
        if trust == "realdb":
            if not any(marker in code for marker in REALDB_MARKERS):
                problems.append(
                    f"{rel}：登记 trust=realdb，但现取**没有**真库收口标记 {list(REALDB_MARKERS)} ⇒ 声明无证据支撑"
                )
        elif trust == "mocked":
            if not any(marker in code for marker in MOCK_MARKERS):
                problems.append(f"{rel}：登记 trust=mocked，但现取**没有** mock 标记 ⇒ 声明与代码不符")
            counterpart = str(entry.get("realdb_counterpart") or "")
            has_counterpart = bool(counterpart) and counterpart in realdb_entries
            if not _ISSUE_RE.search(str(entry.get("gap") or "")) and not has_counterpart:
                problems.append(
                    f"{rel}：mocked 级 = **可信度降级** ⇒ 必须登记**单号**（`gap`）或指向**真库对等判据**"
                    f"（`realdb_counterpart`，现取 {counterpart!r} 不在 realdb 台账里）"
                )
        elif trust == "unit":
            hits = [marker for marker in DB_MARKERS if marker in code]
            if hits:
                problems.append(
                    f"{rel}：登记 trust=unit（不涉数据访问），但现取出现数据访问标记 {hits} ⇒ 应改登记 mocked/realdb"
                )
        else:
            problems.append(f"{rel}：trust 非法（{trust!r}），只认 realdb / mocked / unit")
    assert not problems, (
        "可信度等级与现取证据不符（#5327 的病根就是「安全断言的证据强度与实际不符」）：\n"
        + "\n".join(f"  {p}" for p in problems)
    )


def test_degradation_sites_are_registered() -> None:
    """安全面 catch 的降级判定站点未登记 / 台账陈旧 ⇒ 红（未登记即红、只许缩短）。"""
    registry = _registry()
    section = registry["security_degradation"]
    entries = {str(entry["site"]) for entry in section["entries"]}  # type: ignore[index]
    live = set(_degradation_sites())
    assert live, "降级判据面取空 ⇒ 本判据会静默空跑成绿"
    problems = [f"{p}：现取站点**未登记**降级方向" for p in sorted(live - entries)]
    problems += [f"{p}：台账条目**已陈旧**（该 catch 站点已不在面内）⇒ 只许缩短" for p in sorted(entries - live)]
    print(f"[燃尽锚点 security_degradation] 台账={len(entries)} / 现取={len(live)} —— {sorted(live)}")
    assert not problems, (
        "安全面 catch 的降级方向必须登记：\n"
        + "\n".join(f"  {p}" for p in problems)
        + "\n修法：在台账 `security_degradation.entries` 登记 `direction`（fail-closed / fail-open）+ `reason`；"
        "fail-open 必须带**单号**。\n"
        f"台账：{REGISTRY_PATH.relative_to(REPO_ROOT).as_posix()}"
    )


def test_degradation_direction_matches_code() -> None:
    """登记的方向 / catch 数 / 布尔返回必须与现取代码逐字相符（把「异常 ⇒ 放行」注回去 ⇒ 必红）。"""
    registry = _registry()
    section = registry["security_degradation"]
    live = _degradation_sites()
    problems = []
    fail_open = 0
    for entry in section["entries"]:  # type: ignore[index]
        key = str(entry["site"])
        site = live.get(key)
        if site is None:
            continue  # 陈旧条目由 test_degradation_sites_are_registered 报
        direction = str(entry["direction"])
        if int(site["catch_blocks"]) != int(entry["catch_blocks"]):
            problems.append(
                f"{key}：catch 块数变了 —— 台账记 {entry['catch_blocks']}，现取 {site['catch_blocks']}"
                "（新增一处异常处置必须同批登记）"
            )
        if list(site["return_literals"]) != list(entry["return_literals"]):  # type: ignore[arg-type]
            problems.append(
                f"{key}：catch 的布尔返回变了 —— 台账记 {entry['return_literals']}，现取 {site['return_literals']}"
                "（把「异常 ⇒ 放行」注回去、或静默改方向，都走这条）"
            )
        permissive = entry.get("permissive_literal")
        literals = list(site["return_literals"])  # type: ignore[arg-type]
        if permissive and literals:
            derived = "fail-open" if any(lit == str(permissive) for lit in literals) else "fail-closed"
            if derived != direction:
                problems.append(
                    f"{key}：台账声明 direction={direction}，但按 permissive_literal={permissive!r} 推算现取是"
                    f" {derived} ⇒ 声明与代码不符"
                )
        if direction == "fail-open":
            fail_open += 1
            if not _ISSUE_RE.search(str(entry.get("issue") or "")):
                problems.append(f"{key}：fail-open（降级到「放行」）必须带**单号**（现取 {entry.get('issue')!r}）")
        elif direction != "fail-closed":
            problems.append(f"{key}：direction 非法（{direction!r}），只认 fail-closed / fail-open")
    print(f"[燃尽锚点 security_degradation] fail-open 登记条数={fail_open}（只许缩短）")
    assert not problems, "降级方向台账与现取代码不符：\n" + "\n".join(f"  {p}" for p in problems)


def test_degradation_observability_is_not_silent() -> None:
    """登记了 `observability_required` 的站点**不许静默**：必须留 `log.error` + counter，且字面量一致。"""
    registry = _registry()
    section = registry["security_degradation"]
    observability = section["observability"]  # type: ignore[index]
    keyword = str(observability["keyword"])  # type: ignore[index]
    metric = str(observability["metric"])  # type: ignore[index]
    live = _degradation_sites()
    problems = []
    for entry in section["entries"]:  # type: ignore[index]
        if not entry.get("observability_required"):
            continue
        key = str(entry["site"])
        site = live.get(key)
        if site is None:
            continue
        for whole in site["bodies"]:  # type: ignore[union-attr]
            if "log.error(" not in whole:
                problems.append(f"{key}：异常路径没有 `log.error` ⇒ **静默降级**")
            if "meterRegistry.counter(" not in whole:
                problems.append(f"{key}：异常路径没有 `meterRegistry.counter` ⇒ 没有可观测读数")
            if not re.search(r"_UNAVAILABLE_KEYWORD\b", whole):
                problems.append(f"{key}：异常路径没带上登记的关键词常量（{keyword}）")
    for rel in observability["sites"]:  # type: ignore[index]
        text = REPO_ROOT / str(rel)
        source = text.read_text(encoding="utf-8")
        code = _strip_java(source)
        for const, expected in (
            ("BLACKLIST_CHECK_UNAVAILABLE_KEYWORD", keyword),
            ("BLACKLIST_CHECK_UNAVAILABLE_METRIC", metric),
        ):
            match = re.search(rf"\b{const}\s*=", code)
            if not match:
                problems.append(f"{rel}：缺少常量 {const}（可观测读数的字面量必须显式登记）")
                continue
            value = _quoted_value(source, match.end())
            if value != expected:
                problems.append(f"{rel}：{const} 现取值 {value!r} != 台账登记 {expected!r}（两处不许各自演化）")
    assert not problems, (
        "降级读数缺失或与台账不一致（#4866 要求「不许静默」）：\n" + "\n".join(f"  {p}" for p in problems)
    )


def test_key_registry_matches_installed_playwright_types() -> None:
    """台账里的键位**必须真的不在 `use` 的类型里**（拿现装 Playwright 的 `.d.ts` 复算）。

    本机装了 Playwright（`tests/node_modules`）⇒ 逐键复算；没装 ⇒ **打印「未判定」**
    （「没跑」必须长得像「没跑」，不许静默当成绿 —— issue #5192 家族）。
    """
    types_file = REPO_ROOT / "tests" / "node_modules" / "playwright" / "types" / "test.d.ts"
    registry = _registry()
    keys = [str(entry["key"]) for entry in registry["silently_ignored_keys"]]
    if not types_file.is_file():
        print(f"未判定：本机没有 {types_file.relative_to(REPO_ROOT).as_posix()}（未装 Playwright）⇒ 键位台账未复算")
        return
    lines = types_file.read_text(encoding="utf-8").split("\n")
    decl_re = re.compile(r"^(?:export\s+)?(?:interface|type|declare)\s+([A-Za-z0-9_]+)")
    prop_re = re.compile(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\??\s*:")
    owner = None
    owners: dict[str, set[str]] = {}
    for line in lines:
        decl = decl_re.match(line)
        if decl:
            owner = decl.group(1)
        prop = prop_re.match(line)
        if prop and owner:
            owners.setdefault(prop.group(1), set()).add(owner)
    problems = []
    for key in keys:
        holders = owners.get(key)
        if not holders:
            problems.append(f"{key}：现装 Playwright 的类型里查不到这个键 ⇒ 台账条目已过期（只许缩短）")
            continue
        if "PlaywrightTestOptions" in holders:
            problems.append(
                f"{key}：现装 Playwright 把它列进了 PlaywrightTestOptions（= `use` 的选项）"
                " ⇒ 台账「写在 use: 里会被忽略」的结论已不成立，请复查后销账"
            )
    print(f"现装 Playwright 类型复算：{types_file}（台账键位 {len(keys)} 条）")
    assert not problems, "键位台账与现装 Playwright 的类型定义不符：\n" + "\n".join(f"  {p}" for p in problems)


def test_registry_entries_carry_reason_and_issue() -> None:
    """台账每条必须有 `reason`；需要单号的条目（fail-open / mocked 级）必须有 `#单号`。"""
    registry = _registry()
    problems = []
    for key_entry in registry["silently_ignored_keys"]:
        if len(str(key_entry.get("reason") or "").strip()) < 8:
            problems.append(f"silently_ignored_keys[{key_entry.get('key')}]：reason 缺失或过短")
        if not _ISSUE_RE.search(str(key_entry.get("issue") or "")):
            problems.append(f"silently_ignored_keys[{key_entry.get('key')}]：缺单号")
        if not str(key_entry.get("evidence") or "").strip():
            problems.append(f"silently_ignored_keys[{key_entry.get('key')}]：缺 evidence（怎么判它是被静默忽略的）")
    for site_entry in registry["baseline_sites"]:
        if len(str(site_entry.get("reason") or "").strip()) < 8:
            problems.append(f"baseline_sites[{site_entry.get('dir')}]：reason 缺失或过短")
        if not _ISSUE_RE.search(str(site_entry.get("issue") or "")):
            problems.append(f"baseline_sites[{site_entry.get('dir')}]：缺单号")
        if not site_entry.get("platforms"):
            problems.append(f"baseline_sites[{site_entry.get('dir')}]：缺 platforms（要验哪些平台）")
    for trust_entry in registry["security_assertion_trust"]:
        if len(str(trust_entry.get("reason") or "").strip()) < 8:
            problems.append(f"security_assertion_trust[{trust_entry.get('site')}]：reason 缺失或过短")
    for deg_entry in registry["security_degradation"]["entries"]:  # type: ignore[index]
        if len(str(deg_entry.get("reason") or "").strip()) < 8:
            problems.append(f"security_degradation[{deg_entry.get('site')}]：reason 缺失或过短")
    print(f"台账现取条数：{len(registry['silently_ignored_keys'])} + {len(registry['baseline_sites'])} + "
          f"{len(registry['security_assertion_trust'])} + {len(registry['security_degradation']['entries'])}")  # type: ignore[index]
    assert not problems, "台账条目不合规：\n" + "\n".join(f"  {p}" for p in problems)