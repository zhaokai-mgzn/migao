# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   「CI workflow 结构由 pytest 单测验证」是 misc.yml 里已登记的形态）
r"""`diff_to_test` 映射产出的路径必须**真的会被 pytest 收集**（issue #5353，L0 零 LLM）。

## 病灶（本仓已独立踩中 ≥4 次：production / clarification / vision / suggestions）

`.github/tech-stack.yml` 的规则模板是 `tests/test_{1}.py` 这类**字符串插值**，`{1}` 取的是
pattern 正则的捕获组。一旦捕获组**跨 `/`**（`(.+)`），插值出来的路径就带子目录：

    backend/ai-agent-service/app/suggestions/x.py  --兜底-->  tests/test_suggestions/x.py

而 `backend/ai-agent-service/pytest.ini` 的 `python_files = test_*.py` **只收 basename 带
`test_` 前缀的文件** ⇒ 那条路径**永远不被收集**。三种后果（危险度升序）：

1. 映射**静默失效**：改源文件时配对测试不进变更集，PR 评论照样报绿；
2. 门禁判 `BLOCKED` 并**指示你去建那条路径** —— 照着建就得到
   「**门禁绿 + 测试永不运行**」，而建的人以为自己在修问题
   （`production` / `clarification` / `vision` / `suggestions` 四处规则注释逐字写明了本坑
   = 同一个坑已被独立踩中至少 4 次）；
3. 同族变体：映射指到 `pytest.ini` `addopts --ignore=` 里的文件
   （`tests/test_llm_pipeline.py` 即活例）—— 磁盘上**有**这个文件，但 pytest **从不收集**它，
   于是「门禁看得见」与「测试真会跑」再次脱节。

## 本守卫判什么（纯静态、零 LLM、不读 `origin/main`、**复用 growth_gate 的实现**）

判据一律走 `.github/growth_gate.py` 的既有纯函数（`compile_rules` / `match_rule` /
`expand_test_names` / `find_existing_tests`），**不写第二份映射实现**（同一真值两处推导 =
本仓既有教训）；「可收集」的口径**只有一个源** = `backend/ai-agent-service/pytest.ini`
（`python_files` + `addopts` 里的 `--ignore=`）。

| 判据 | 断言 | 反例输入（改这一处即红） |
|---|---|---|
| `test_fallback_rule_expands_to_collectable_paths` | 兜底规则对**任意深度**的探测路径都只展开出可收集路径 | 把兜底 pattern 换回 `app/(.+)\.py`（见 `TestInjectionNonVacuity`） |
| `test_every_app_dir_has_explicit_rule_or_registered_fallback` | `app/` 下每个含 `.py` 的目录：要么有**非兜底**规则命中，要么在 `_FALLBACK_RELIANT_DIRS` 登记 | 新增一个未登记的目录 + 源文件 |
| `test_every_source_file_mapping_is_collectable` | 每个现存 `app/**/*.py` 命中的规则，其**全部**候选模板都可收集 | 恢复 `production` 的第二条模板 `tests/test_production/{1}.py` |
| `test_every_source_file_is_gate_visible_or_registered` | 每个现存源文件：映射能解析到**磁盘上存在且会被收集**的测试，或在 `_NO_TEST_REGISTRY` 显式登记「无测试」+ 理由 | 新增一个无测试的源文件而不登记 |
| `test_no_test_registry_entries_are_alive` | 登记表**自带死亡条件**：文件必须存在、理由非空、且映射确实解析不到可收集的测试 | 给已有配套测试的文件补一条登记（如 `backend/ai-agent-service/app/main.py`） |
| `test_fallback_reliant_dirs_are_real_and_needed` | 登记表**不许有僵尸**：目录必须存在且确实靠兜底承接 | 登记一个不存在/已被显式规则接管的目录 |
| `test_issue_5353_instances_resolve_to_their_real_tests` | issue #5353 点名的每一个实例，映射必须**指到那条真实存在的测试**（逐条逐字比对，不是「有就行」） | 删掉 `app/core/` 的显式规则 ⇒ 实例退回不可见 |
| `test_burn_down_anchor_matches_current_ledger` | 两张台账的**条数**与锚点逐字相等 ⇒ 涨跌都要同 PR 改锚（§23.1 G2：只许缩短） | 往任一张登记表加一条而不动锚点 |

## 本单**新发现**的第三形态（修的时候顺手证的，不是设计出来的）

`production` / `clarification` / `vision` 三条规则原有一条 `tests/test_<dir>/{1}.py` 模板：
它对任何源文件都展开成**不带 `test_` 前缀**的路径（pytest 永不收集）；更要紧的是对
`app/<dir>/__init__.py` 它会命中 `tests/test_<dir>/__init__.py` —— 磁盘上**有**这个文件，
于是门禁报 **pass**，而 pytest **从不收集**它 ⇒ 那三个 `__init__.py` 的「绿」是假的。
三条模板已删（production / clarification / vision），三个文件如实转为 `BLOCKED`
并登记进 `_NO_TEST_REGISTRY`。

## 两张登记表都不是「豁免面」（防白名单化）

`_FALLBACK_RELIANT_DIRS` / `_NO_TEST_REGISTRY` **门禁（`growth_gate`）根本不读它们** ——
它们只把「**有意的**选择」与「**没人注意到的**缺口」区分开：

- 有意的：`app/middleware/` 依赖兜底（该目录无专门测试，兜底产出的
  `tests/test_logging_middleware.py` 可收集、也正是将来该放的位置）；
- 没人注意到的：新目录 / 新源文件 —— 判据对它们**必须变红**，并**指名处置**
  （去 `.github/tech-stack.yml` 补显式规则，**不是**去建那条不可收集的路径）。

顺带：登记 ≠ 免检。被登记的文件**改动时门禁照样要求补测试** —— 登记只声明「此刻确实没有
测试」这个事实为真，并用死亡条件保证它不会永远为真。

## 已知残留（照实登记，§19.1）

- 只判「**可收集 + 门禁可见**」，**不判「测试真的覆盖了这个模块」** —— 后者要读测试内容，
  非零成本且本单范围外（issue #5353 明确「不重写整个测试映射体系」）；
- 只覆盖 `language: python` 的 ai-agent-service 模块：java 的 `**/test/**{1}Test.java`
  与 typescript 的 glob 不走 pytest 收集口径，本判据不适用；
- 注入（红证）是**变异式**的：在内存里换掉 pattern / 加一个假目录名，不改仓库文件、不跑 pytest。

⚠️ 本文件自身会被 CI 的 `--check-weak` 扫描（新增测试文件），故正文不得出现字面弱断言模式。
"""

from __future__ import annotations

import configparser
import copy
import fnmatch
import importlib.util
import os
import posixpath
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"
TECH_STACK_YML = REPO_ROOT / ".github" / "tech-stack.yml"
PYTEST_INI = REPO_ROOT / "backend" / "ai-agent-service" / "pytest.ini"
APP_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app"
APP_PREFIX = "backend/ai-agent-service/"

# 旧兜底 pattern（**只用于红证**）：`.+` 捕获子目录 ⇒ 展开成 `tests/test_<dir>/<name>.py`
# （子目录 + 无 `test_` 前缀）⇒ 不匹配 pytest.ini 的 `python_files` ⇒ 永不收集。
OLD_FALLBACK_PATTERN = r"backend/ai-agent-service/app/(.+)\.py"

# ── 有意依赖**兜底规则**的目录（key = `app/` 下的相对目录，"" = app 顶层）──
# 为什么要有这张表：兜底把目录压平后，同名不同目录的源文件会指向同一个测试名
# ⇒ 「靠兜底」必须是一次**有意的**选择，而不是没人注意到的默认。
_FALLBACK_RELIANT_DIRS = {
    "": "app 顶层模块（main/config/log_config）：basename 唯一，且既有配套测试就叫 "
        "tests/test_<name>.py（tests/test_main.py / tests/test_config.py）⇒ 兜底即正解",
    "cache": "目录内只有 __init__.py（纯 docstring）⇒ 无测试（见 _NO_TEST_REGISTRY）；"
             "兜底展开成 tests/test___init__.py（可收集），改动它时门禁会要求补测试",
    "middleware": "目录内只有 __init__.py（一行包注释）+ logging_middleware.py（无专门测试，"
                  "见 _NO_TEST_REGISTRY）；兜底展开成 tests/test_logging_middleware.py（可收集）",
}

# ── 显式登记「无测试」的源文件（key = 仓库相对路径，值 = 理由，必须非空）──
# 判据 3 的另一半：`app/**` 的每个源文件要么映射得到**真实存在的测试**，要么在此登记。
_NO_TEST_REGISTRY = {
    "backend/ai-agent-service/app/__init__.py":
        "整文件只有一行注释（包声明），无任何可执行语句",
    "backend/ai-agent-service/app/cache/__init__.py":
        "纯 docstring（app/cache 目前无任何实现文件）",
    "backend/ai-agent-service/app/core/__init__.py":
        "纯 re-export：__all__ 只列 app/core/{circuit_breaker,fallback,admin_api_cache} 的符号，"
        "行为由三者的 tests/unit/test_{circuit_breaker,fallback,admin_api_cache}.py 各自覆盖",
    "backend/ai-agent-service/app/middleware/__init__.py":
        "整文件只有一行注释（包声明），无任何可执行语句",
    "backend/ai-agent-service/app/middleware/logging_middleware.py":
        "**真没测试**（已核，不是「名字对不上」）：全仓仅两处以装配件形态出现"
        "（tests/unit/test_llm_exception_attribution.py 与 tests/test_error_incident.py 里的 "
        "`app.add_middleware(RequestLoggingMiddleware)`），没有任何断言其 request_id / SKIP_PATHS "
        "行为的用例；改动该文件时门禁会要求补 tests/test_logging_middleware.py",
    "backend/ai-agent-service/app/clarification/__init__.py":
        "纯 docstring（模块说明）：原先靠 tests/test_clarification/__init__.py「报绿」，"
        "但那文件 pytest **永不收集**（不带 test_ 前缀）⇒ 那是假的 pass，已随 #5353 删除该模板",
    "backend/ai-agent-service/app/log_config.py":
        "**真没测试**：setup_logging 是进程级副作用（loguru handler 装配），全仓 tests/ 零引用",
    "backend/ai-agent-service/app/production/__init__.py":
        "纯 docstring（模块说明）：原先靠 tests/test_production/__init__.py「报绿」，"
        "但那文件 pytest **永不收集** ⇒ 假的 pass，已随 #5353 删除该模板",
    "backend/ai-agent-service/app/vision/__init__.py":
        "纯 docstring（模块说明）：原先靠 tests/test_vision/__init__.py「报绿」，"
        "但那文件 pytest **永不收集** ⇒ 假的 pass，已随 #5353 删除该模板",
    "backend/ai-agent-service/app/suggestions/__init__.py":
        "纯 re-export：符号来自 app/suggestions/follow_up.py，行为由 tests/test_follow_up_suggestions.py 覆盖",
    "backend/ai-agent-service/app/tools/__init__.py":
        "纯 re-export（import + __all__）：既有豁免在 .github/qa-exemptions.yml（逐字理由："
        "Tool 模块 re-export，新增 CustomerOrderQueryTool 由 tests/test_tools_customer_order_query.py 直接覆盖）",
    "backend/ai-agent-service/app/utils/__init__.py":
        "纯 re-export：符号来自 app/utils/{database,redis_client,auth}.py，"
        "行为由各自的 tests/test_utils_*.py 覆盖",
}

# 兜底规则的探测路径（深度 1 / 2 / 3）—— 兜底必须对**任意深度**都产出可收集路径
_PROBE_DEPTHS = ("", "zz_unregistered_dir/", "zz_unregistered_dir/zz_deeper/")


# ── 夹具：复用 growth_gate 的实现（不写第二份映射） ────────────────────────────

def _load_gate():
    """从 `.github/growth_gate.py` 加载被测模块（零依赖，importlib 文件加载）。"""
    spec = importlib.util.spec_from_file_location("growth_gate_under_test_collectable", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tech(gate):
    """tech-stack.yml（fail-closed：读不出就大声失败，不得静默放行）。"""
    data, err = gate._load_yaml(str(TECH_STACK_YML))
    assert not err, f"tech-stack.yml 读不出来，本守卫无从判定（不得静默放行）：{err}"
    return data


def _rules(gate, tech=None):
    """编译后的规则（fail-closed：有规则被丢弃 / 规则集为空 ⇒ 判定基准不可信）。"""
    tech = _tech(gate) if tech is None else tech
    errors: list = []
    rules = gate.compile_rules(tech.get("modules") or [], tech.get("test_commands") or {}, errors)
    assert not errors, f"tech-stack.yml 有 {len(errors)} 条规则无法编译，判定基准不可信：{errors}"
    assert rules, "tech-stack.yml 没有任何可执行规则 —— 兜底/映射判据会退化成空跑"
    return rules


def _pytest_collection_surface():
    """pytest 的收集面（**唯一判据源**）：(`python_files` glob 列表, `--ignore` 前缀列表)。"""
    parser = configparser.RawConfigParser()
    parser.read(PYTEST_INI, encoding="utf-8")
    section = parser["pytest"]
    globs = section.get("python_files", "").split()
    addopts = section.get("addopts", "")
    ignores = []
    for token in addopts.split():
        if token.startswith("--ignore="):
            ignores.append(token.split("=", 1)[1].lstrip("./").rstrip("/"))
    assert globs, "pytest.ini 没有 python_files —— 收集面无从判定（不得静默放行）"
    assert ignores, "pytest.ini 的 addopts 里没有 --ignore= —— 解析口径失效，不得当作「无忽略」"
    return globs, ignores


def _collectable(test_name):
    """该测试路径**会被 pytest 收集**吗？（口径 = pytest.ini，不另立标准）"""
    globs, ignores = _pytest_collection_surface()
    normalized = test_name.lstrip("./")
    base = posixpath.basename(normalized)
    if not any(fnmatch.fnmatch(base, g) for g in globs):
        return False
    return not any(normalized == ig or normalized.startswith(ig + "/") for ig in ignores)


def _app_dirs():
    """`app/` 下**含 `.py`** 的目录（相对 app/ 的 posix 路径，"" = app 顶层），已排序。"""
    found = set()
    for dirpath, _dirnames, filenames in os.walk(APP_DIR):
        if any(f.endswith(".py") for f in filenames):
            rel = os.path.relpath(dirpath, APP_DIR).replace(os.sep, "/")
            found.add("" if rel == "." else rel)
    return sorted(found)


def _app_files():
    """`app/**/*.py` 的仓库相对路径（跳过 `__pycache__`），已排序。"""
    files = []
    for dirpath, dirnames, filenames in os.walk(APP_DIR):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(os.path.relpath(os.path.join(dirpath, fn), REPO_ROOT))
    return sorted(files)


def _probe_path(dir_rel):
    """某目录里的探测源文件路径（不落盘，仅用于问「这条目录会命中哪条规则」）。"""
    tail = f"{dir_rel}/" if dir_rel else ""
    return f"{APP_PREFIX}app/{tail}probe_module.py"


def _fallback_rule(gate, rules):
    """兜底规则 = **对未登记目录的探测路径生效的那一条**（语义定义，不写死 pattern 文本）。"""
    return gate.match_rule(_probe_path("zz_unregistered_dir"), rules)


# ── 判据实现（返回「问题清单」，空 = 通过；注入用例喂同一批函数） ──────────────

def _mapping_findings(gate, rules, paths):
    """逐路径：命中规则必须存在，且其**每一个**候选模板都必须可收集。

    为什么是「每一个」而不是「至少一个」：门禁判 `BLOCKED` 时列出的是**全部**缺失模板
    （`.github/growth_gate.py` 的 `_blocker_entry`）⇒ 只要清单里有一条不可收集路径，
    照着建就得到「门禁绿 + 测试永不运行」。
    """
    findings = []
    for path in paths:
        rule = gate.match_rule(path, rules)
        if rule is None:
            findings.append(f"{path}：无任何规则匹配（unmatched ⇒ 门禁静默跳过，不会要求任何测试）")
            continue
        bad = [n for n in gate.expand_test_names(rule, path) if not _collectable(n)]
        if bad:
            findings.append(
                f"{path}：命中的规则模板展开出**不可收集**的路径 {bad}"
                f"（pytest.ini 的 python_files 只收 test_*.py，且 addopts 的 --ignore 面不收）"
            )
    return findings


def _dir_findings(gate, rules, dirs, registry=None):
    """逐目录：必须被**非兜底**规则命中，或（命中兜底时）在 `_FALLBACK_RELIANT_DIRS` 登记。"""
    registry = _FALLBACK_RELIANT_DIRS if registry is None else registry
    fallback = _fallback_rule(gate, rules)
    assert fallback, "找不到兜底规则（对未登记目录的探测路径无规则命中）⇒ 未登记目录会静默跳过"
    findings = []
    for dir_rel in dirs:
        label = dir_rel if dir_rel else "app 顶层"
        rule = gate.match_rule(_probe_path(dir_rel), rules)
        if rule is None:
            findings.append(f"{label}：无任何规则匹配（unmatched ⇒ 门禁静默跳过）")
        elif rule["regex"].pattern == fallback["regex"].pattern and dir_rel not in registry:
            findings.append(
                f"{label}：既没有显式规则，也没有登记为「有意依赖兜底规则」"
                " ⇒ 处置 = 在 .github/tech-stack.yml 为它补一条显式规则（照 app/core/ 的写法），"
                "或确认兜底产出的路径可收集后登记进 _FALLBACK_RELIANT_DIRS"
                "（**不要**去建那条门禁报出来的不可收集路径）"
            )
    return findings


def _visibility_findings(gate, rules, files, registry=None):
    """逐源文件：映射能解析到**磁盘存在且会被收集**的测试，或已在登记表里「无测试」+ 理由。"""
    registry = _NO_TEST_REGISTRY if registry is None else registry
    findings = []
    for path in files:
        rule = gate.match_rule(path, rules)
        if rule is None:
            findings.append(f"{path}：无任何规则匹配（unmatched ⇒ 门禁静默跳过）")
            continue
        names = gate.expand_test_names(rule, path)
        live = [n for n in gate.find_existing_tests(rule, names, str(REPO_ROOT)) if _collectable(n)]
        if live:
            if path in registry:
                findings.append(
                    f"{path}：已登记「无测试」，但映射解析到了会跑的测试 {live} "
                    "⇒ 登记已死（死亡条件触发），删掉该条登记"
                )
            continue
        entry = registry.get(path)
        if not entry:
            findings.append(
                f"{path}：映射 {names} 解析不到任何**会被收集**的测试，且未登记「无测试」"
                " ⇒ 处置 = 补一条真实存在的配套测试，或在 _NO_TEST_REGISTRY 登记「无测试」+ 理由"
            )
        elif not entry.strip():
            findings.append(f"{path}：登记了「无测试」但**没写理由** ⇒ 登记表退化成一排免检券")
    return findings


def _registration_liveness_findings(gate, rules, dirs, registry=None):
    """登记表的**死亡条件/僵尸条件**：目录必须存在、确实靠兜底承接。"""
    registry = _FALLBACK_RELIANT_DIRS if registry is None else registry
    fallback = _fallback_rule(gate, rules)
    findings = []
    for dir_rel in sorted(registry):
        if dir_rel not in dirs:
            findings.append(f"_FALLBACK_RELIANT_DIRS 登记了不存在的目录（僵尸条目）：{dir_rel!r}")
            continue
        rule = gate.match_rule(_probe_path(dir_rel), rules)
        if rule is None or rule["regex"].pattern != fallback["regex"].pattern:
            findings.append(
                f"_FALLBACK_RELIANT_DIRS 登记了 {dir_rel!r}，但它已被非兜底规则接管 "
                "⇒ 登记已死（死亡条件触发），删掉该条"
            )
    return findings


# ── ① 兜底规则：任意深度都必须产出可收集路径（判据 1） ────────────────────────

def test_fallback_rule_expands_to_collectable_paths():
    r"""兜底规则对深度 1/2/3 的探测路径都必须**只**展开出可收集路径。

    红证（恢复旧兜底即红）见 `TestInjectionNonVacuity.test_old_fallback_pattern_would_be_flagged`；
    修复前实测：旧兜底 `app/(.+)\.py` 对 `app/core/circuit_breaker.py` 产出
    `tests/test_core/circuit_breaker.py`（子目录 + 无 `test_` 前缀）⇒ 本条必红。
    """
    gate = _load_gate()
    rules = _rules(gate)
    fallback = _fallback_rule(gate, rules)
    probes = [f"{APP_PREFIX}app/{depth}probe_module.py" for depth in _PROBE_DEPTHS]
    for probe in probes:
        matched = gate.match_rule(probe, rules)
        assert matched["regex"].pattern == fallback["regex"].pattern, (
            f"{probe} 没有落进兜底规则（{matched['regex'].pattern!r}）⇒ 本判据对兜底空转"
        )
    findings = _mapping_findings(gate, rules, probes)
    assert not findings, "兜底规则产出了不可收集的路径（门禁会指示人去建它）：\n  - " + "\n  - ".join(findings)


# ── ② 目录完整性：每个含 .py 的目录都要被显式接管或登记（判据 2） ──────────────

def test_every_app_dir_has_explicit_rule_or_registered_fallback():
    """`app/` 下每个含 `.py` 的目录：要么有非兜底规则命中，要么登记为「有意依赖兜底」。

    红证（新增一个无显式规则的目录 + 源文件即红）见
    `TestInjectionNonVacuity.test_unregistered_dir_would_be_flagged`。
    """
    gate = _load_gate()
    rules = _rules(gate)
    dirs = _app_dirs()
    assert len(dirs) >= 10, f"含 .py 的目录只枚举到 {len(dirs)} 个 —— 枚举可疑，判据可能空转"
    findings = _dir_findings(gate, rules, dirs)
    assert not findings, "以下目录的映射没有着落：\n  - " + "\n  - ".join(findings)


def test_fallback_reliant_dirs_are_real_and_needed():
    """兜底依赖登记表**不许有僵尸**（目录已删 / 已被显式规则接管 ⇒ 该条已死，删掉）。"""
    gate = _load_gate()
    rules = _rules(gate)
    findings = _registration_liveness_findings(gate, rules, _app_dirs())
    assert not findings, "兜底依赖登记表里有死条目：\n  - " + "\n  - ".join(findings)


# ── ③ 逐源文件：映射的每个候选模板都必须可收集（判据 1 的全仓面） ──────────────

def test_every_source_file_mapping_is_collectable():
    """每个现存 `app/**/*.py` 命中的规则，其**全部**候选模板都必须是 pytest 可收集的。

    红证：恢复 `production` 的第二条模板 `tests/test_production/{1}.py`（对任何源文件都展开成
    `tests/test_production/<name>.py` ⇒ 不带 `test_` 前缀）⇒ 本条必红。
    """
    gate = _load_gate()
    rules = _rules(gate)
    files = _app_files()
    assert len(files) >= 100, f"app/**/*.py 只枚举到 {len(files)} 个 —— 枚举可疑，判据可能空转"
    findings = _mapping_findings(gate, rules, files)
    assert not findings, "以下源文件的映射含不可收集路径：\n  - " + "\n  - ".join(findings)


# ── ④ 逐源文件：门禁可见（有真实测试）或显式登记「无测试」（判据 3） ──────────

def test_every_source_file_is_gate_visible_or_registered():
    """每个现存 `app/**/*.py`：映射解析到会被收集的测试，或在 `_NO_TEST_REGISTRY` 登记 + 理由。

    红证（无测试的新文件不登记即红）见
    `TestInjectionNonVacuity.test_unregistered_untested_file_would_be_flagged`。
    """
    gate = _load_gate()
    rules = _rules(gate)
    findings = _visibility_findings(gate, rules, _app_files())
    assert not findings, "以下源文件对门禁不可见且未登记：\n  - " + "\n  - ".join(findings)


def test_no_test_registry_entries_are_alive():
    """登记表自带**死亡条件**：文件必须存在、理由非空、且映射确实解析不到会被收集的测试。

    否则它会退化成「一排免检券」——配套测试后来补上了，登记还挂着（本仓既有教训：
    豁免/白名单没有死亡条件）。
    """
    gate = _load_gate()
    rules = _rules(gate)
    findings = _visibility_findings(gate, rules, sorted(_NO_TEST_REGISTRY))
    missing = [p for p in sorted(_NO_TEST_REGISTRY) if not (REPO_ROOT / p).is_file()]
    assert not missing, f"_NO_TEST_REGISTRY 登记了不存在的文件（僵尸条目）：{missing}"
    assert not findings, "登记表里有死条目/空理由：\n  - " + "\n  - ".join(findings)


def test_scan_is_not_vacuous():
    """防「空转」：收集面 / 目录枚举 / 源文件枚举三项都必须真的读到东西。"""
    gate = _load_gate()
    rules = _rules(gate)
    globs, ignores = _pytest_collection_surface()
    assert globs == ["test_*.py"], f"pytest.ini 的收集面变了（{globs}）⇒ 本守卫口径需同步复核"
    assert any(i.endswith("test_llm_pipeline.py") for i in ignores), (
        "pytest.ini 的 --ignore 面里没有 tests/test_llm_pipeline.py ⇒ 解析口径失效"
    )
    assert gate.match_rule(_probe_path(""), rules), "app 顶层探测路径无规则命中 —— 判据会空转"
    assert _app_dirs() and _app_files()


# ── ⑤ issue #5353 的实例判据（点名的每一格都要**指到那条真实测试**） ──────────

# 源文件 → 它**真实存在**的配套测试（逐条已核过 import，不是按文件名猜的）
_INSTANCE_EXPECTATIONS = {
    "backend/ai-agent-service/app/core/circuit_breaker.py": ["tests/unit/test_circuit_breaker.py"],
    "backend/ai-agent-service/app/core/fallback.py": ["tests/unit/test_fallback.py"],
    "backend/ai-agent-service/app/core/admin_api_cache.py": ["tests/unit/test_admin_api_cache.py"],
    "backend/ai-agent-service/app/suggestions/preference_tracker.py": ["tests/test_preference_tracker.py"],
    "backend/ai-agent-service/app/suggestions/follow_up.py": ["tests/test_follow_up_suggestions.py"],
    "backend/ai-agent-service/app/llm/router.py": ["tests/test_vision_integration.py"],
}


def test_issue_5353_instances_resolve_to_their_real_tests():
    """issue #5353 的实例：映射必须**指到那条真实存在的测试**（逐条逐字比对）。

    只断言「解析到某个测试」是不够的 —— 那正是本单的病灶形态（门禁绿，而配对测试根本
    不在变更集里）。这里逐条钉「映射能看见哪条测试」。

    红证：删掉 `app/core/` 的显式规则（或把兜底换回 `(.+)`）⇒ 前三条立刻退回不可见 ⇒ 本判据红。
    """
    gate = _load_gate()
    rules = _rules(gate)
    problems = []
    for source, expected in sorted(_INSTANCE_EXPECTATIONS.items()):
        rule = gate.match_rule(source, rules)
        names = gate.expand_test_names(rule, source) if rule else []
        visible = [n for n in gate.find_existing_tests(rule, names, str(REPO_ROOT)) if _collectable(n)] if rule else []
        invisible = [t for t in expected if t not in visible]
        if invisible:
            problems.append(f"{source} 看不见 {invisible}（映射 {names}，实得 {visible}）")
    assert not problems, "实例仍对门禁不可见：\n  - " + "\n  - ".join(problems)


def test_issue_5353_unproven_cells_are_concluded():
    """issue 里两格「未取证」的**结论**必须落在判据上，不能只活在报告里。

    - `app/suggestions/follow_up.py` → **有**真实测试（tests/test_follow_up_suggestions.py，已核 import）；
    - `app/middleware/logging_middleware.py` → **真没测试**（全仓只有两处把它当装配件 import，
      无任何断言其行为的用例）⇒ 登记进 `_NO_TEST_REGISTRY`，不是忽略、也不是「名字对不上」。
    """
    gate = _load_gate()
    rules = _rules(gate)
    entry = _NO_TEST_REGISTRY.get("backend/ai-agent-service/app/middleware/logging_middleware.py", "")
    assert "真没测试" in entry, "logging_middleware 这一格必须给出「真没测试」的结论与理由"
    assert "tests/test_follow_up_suggestions.py" in _INSTANCE_EXPECTATIONS[
        "backend/ai-agent-service/app/suggestions/follow_up.py"
    ], "follow_up 这一格必须钉住它的真实测试"
    source = "backend/ai-agent-service/app/middleware/logging_middleware.py"
    rule = gate.match_rule(source, rules)
    assert rule, f"{source} 无规则命中 ⇒ 判据会空转"
    assert not [n for n in gate.find_existing_tests(rule, gate.expand_test_names(rule, source), str(REPO_ROOT))
                if _collectable(n)], "该文件其实有会跑的测试 ⇒ 「无测试」结论已过期，删掉登记"


# ── ⑥ 燃尽靶（§23.1 G2）：台账条数**只许缩短**，涨跌都红 ─────────────────────

_ANCHOR_FALLBACK_RELIANT_DIRS = 3
_ANCHOR_NO_TEST_FILES = 12


def test_burn_down_anchor_matches_current_ledger():
    """两张台账的**条数**与锚点逐字相等 ⇒ 任何涨跌都必须在**同 PR** 里改锚并写明来由。

    口径（`migao-dev-flow` §23.1 G2）：台账**只许缩短** —— 修好一处（补上测试 / 给目录补显式
    规则）就同 PR 把锚点**下调**；上调必须能说清「为什么只能这样」。不这么钉的话，
    登记表会变成只增不减的免检券册子。

    读数（零动作也出声，§23.1 G6）：`python3 -m pytest tests/unit_ci_workflows/test_diff_to_test_collectable.py -q -s -k burn_down`
    """
    live = {
        "fallback_reliant_dirs": len(_FALLBACK_RELIANT_DIRS),
        "no_test_files": len(_NO_TEST_REGISTRY),
    }
    anchor = {
        "fallback_reliant_dirs": _ANCHOR_FALLBACK_RELIANT_DIRS,
        "no_test_files": _ANCHOR_NO_TEST_FILES,
    }
    print(f"[#5353 burn-down] 现取读数 {live} / 锚点 {anchor}")
    drifted = {k: {"live": live[k], "anchor": anchor[k]} for k in live if live[k] != anchor[k]}
    assert not drifted, (
        f"台账条数与锚点不一致：{drifted}（现取 {live} / 锚点 {anchor}）。"
        "口径 = **只许缩短**：补上测试、删掉文件、或给目录补了显式规则之后，同 PR 把锚点下调；"
        "确需上调时，把「为什么只能靠兜底 / 为什么确实无测试」写进登记表的理由里。"
    )


# ── ⑦ 注入式红证 + 负控：每条判据都判得动，且不误伤 ──────────────────────────

class TestInjectionNonVacuity:
    """把「坏输入 / 好输入」分别喂进同一批判据，两个方向都必须判得动。"""

    def test_old_fallback_pattern_would_be_flagged(self):
        """**恢复旧兜底 ⇒ 必须变红**（判据 1 的红证）。"""
        gate = _load_gate()
        mutated = _rules_with_pattern_injected(gate, OLD_FALLBACK_PATTERN)
        probes = [f"{APP_PREFIX}app/{depth}probe_module.py" for depth in _PROBE_DEPTHS]
        findings = _mapping_findings(gate, mutated, probes)
        deep = [f for f in findings if "zz_unregistered_dir" in f]
        assert deep, f"旧兜底（捕获子目录）未被判出不可收集路径，注入未生效：{findings}"

    def test_current_fallback_is_not_flagged(self):
        """负控：**现兜底**不得被判出问题（否则判据恒红 = 空判据）。"""
        gate = _load_gate()
        rules = _rules(gate)
        probes = [f"{APP_PREFIX}app/{depth}probe_module.py" for depth in _PROBE_DEPTHS]
        assert _mapping_findings(gate, rules, probes) == []

    def test_unregistered_dir_would_be_flagged(self):
        """**新增一个无显式规则的目录 ⇒ 必须变红**（判据 2 的红证）。"""
        gate = _load_gate()
        rules = _rules(gate)
        injected = _app_dirs() + ["brand_new_dir_5353"]
        findings = _dir_findings(gate, rules, injected)
        assert any("brand_new_dir_5353" in f for f in findings), (
            f"未登记目录未被判出 ⇒ 判据 2 无判别力：{findings}"
        )

    def test_registered_fallback_dir_is_not_flagged(self):
        """负控：已登记的兜底依赖目录（`middleware` / `cache` / app 顶层）不得被判出问题。"""
        gate = _load_gate()
        rules = _rules(gate)
        assert _dir_findings(gate, rules, sorted(_FALLBACK_RELIANT_DIRS)) == []

    def test_rule_taking_over_a_registered_dir_is_flagged(self):
        """死亡条件方向：目录**已被显式规则接管**时，兜底依赖登记必须判死。"""
        gate = _load_gate()
        rules = _rules(gate)
        # app/core/ 已有显式规则 ⇒ 若有人把 core 也登记进兜底依赖表，登记必须判死
        findings = _registration_liveness_findings(
            gate, rules, _app_dirs(), registry={"core": "不该存在的登记"}
        )
        assert any("core" in f for f in findings), f"已接管的目录未被判死：{findings}"

    def test_unregistered_untested_file_would_be_flagged(self):
        """**无测试的新源文件不登记 ⇒ 必须变红**（判据 3 的红证）。"""
        gate = _load_gate()
        rules = _rules(gate)
        injected = [f"{APP_PREFIX}app/core/brand_new_module_5353.py"]
        findings = _visibility_findings(gate, rules, injected)
        assert findings, "无测试且未登记的新源文件未被判出 ⇒ 判据 3 无判别力"

    def test_registered_untested_file_is_not_flagged(self):
        """负控：已登记「无测试」的源文件不得被判出问题（登记在做实事）。"""
        gate = _load_gate()
        rules = _rules(gate)
        registered = "backend/ai-agent-service/app/log_config.py"
        assert _visibility_findings(gate, rules, [registered]) == []

    def test_registry_entry_for_a_covered_file_is_flagged(self):
        """死亡条件方向：文件其实**有**会跑的配套测试时，登记必须判死（否则是免检券）。"""
        gate = _load_gate()
        rules = _rules(gate)
        covered = "backend/ai-agent-service/app/main.py"
        findings = _visibility_findings(
            gate, rules, [covered], registry={covered: "伪造的「无测试」登记"}
        )
        assert any(covered in f for f in findings), f"有配套测试的文件未被判死：{findings}"


def _rules_with_pattern_injected(gate, new_pattern):
    """把**兜底那条 pattern** 在内存里换成 `new_pattern` 后重新编译（不改仓库文件）。"""
    tech = _tech(gate)
    base_rules = _rules(gate)
    fallback_text = _fallback_rule(gate, base_rules)["regex"].pattern
    modules = copy.deepcopy(tech.get("modules") or [])
    hits = 0
    for module in modules:
        for pat in module.get("patterns") or []:
            if pat.get("pattern") == fallback_text:
                pat["pattern"] = new_pattern
                hits += 1
    assert hits == 1, f"兜底 pattern {fallback_text!r} 在 tech-stack.yml 里出现 {hits} 次（期望 1）"
    mutated = dict(tech, modules=modules)
    return _rules(gate, mutated)