# case_ids: MC-012
"""「自毁式真值主张」（断言最高迁移版本号 == 常量）机械守卫（issue #5166）。

## 病灶（2026-09-22 同一批新代码里**连出三次**，每次都靠后一个单顺手修掉）

断言「**最高迁移版本号 == 常量**」的写法，在**下一个迁移一出现**时必然变红，且**报错文案把人指向
错误行动**——新增迁移的人看到「V118 不是最高版本号（当前最大 V119）」会以为**自己的迁移写错了**；
而最省事的"修法"就是把断言改松或删掉，那正是本仓明令禁止的形态。

| # | 出处（仓库相对全路径，不写行号） | 原写法 | 被谁触发 |
|---|---|---|---|
| ① | `backend/admin-api/src/test/java/com/migao/admin/mapper/StockBatchConsumptionMapperTest.java` | `versions.get(size - 1) == 116` | #5148 的 V117 |
| ② | `tests/unit_ci_workflows/test_inbound_opening_register.py` | `max(versions) == 118` | #5158 的 V119 |
| ③ | #5158 自己新写的文件 | 同款 | 自查后一并改 |

## 正确写法（本仓既有先例，见 `_GUIDANCE`，命中时逐字打印）

```python
assert max(versions) >= N                      # 不主张「我是最大的」
assert len([v for v in versions if v >= N]) == len({v for v in versions if v >= N})   # 本档及以后无重复
```
⚠️ **只查本档及以后**：仓库存量里 **V29 / V33 各有两份**（历史遗留）⇒ 全量查重会对历史假红。

## 判据（每条都能单独变红）

| # | 判据 | 在哪 |
|---|---|---|
| 1 | 注入真实违规（Python / Java）⇒ 红并指名文件与行；删除注入 ⇒ 恢复绿 | `test_injected_violation_is_red_and_named` |
| 2 | **反假红**：保留 7 处「不要这么写」的**反面教材**注释 ⇒ 绿；**去掉排除逻辑** ⇒ 当场变红 | `test_counterexample_prose_is_kept_and_green` / `test_dropping_noncode_exclusion_turns_counterexamples_red` |
| 3 | 正确写法（`>=` + 本档及以后无重复）与无关 `max(...)` 主张 ⇒ 不误报 | `test_legit_forms_stay_green` |
| 4 | 覆盖边界登记（`NOT_COVERED`）**带死亡条件**：谁补上了 ⇒ 那条断言当场变红 | `test_registered_gaps_are_still_gaps` |
| 5 | 每条形态各有一条能单独变红的红证（新增形态不配红证 ⇒ 红） | `test_every_pattern_has_a_red_proof` |
| 6 | 存量零违规（**零容忍、无 burn-down 白名单**） | `test_real_tree_has_zero_violations` |

## 能抓什么 / 抓不到什么（**如实登记，不把"抓不到"伪装成"已覆盖"**）

**能抓**（每条形态各有一条能**单独**变红的注入红证，见 `CORPUS`；`test_every_pattern_has_a_red_proof`
钉住「形态没有红证 ⇒ 红」）：

| 形态 id | 形态 | 样例（节选） |
|---|---|---|
| `eq_rhs_const` | 最大值表达式在 `==` 左侧 | `assert max(versions) == 117` / `assert migration_versions[-1] == 117` / `assert sorted(versions)[-1] == 117` / `assert max_version == 117` / `assertTrue(versions.get(versions.size() - 1) == 116)` |
| `eq_lhs_const` | 常量在左侧 | `assert 117 == max(versions)` |
| `helper_const_first` | 断言助手：常量在前 | `self.assertEqual(117, max(versions))` / `assertEquals(116, versions.get(versions.size() - 1))` / `assertEquals(119, Collections.max(migrationVersions))` / `assertEquals(116, versions[versions.size() - 1])` |
| `helper_const_last` | 断言助手：常量在后 | `self.assertEqual(max(versions), 117)` |
| `assertj_isequalto` | AssertJ 相等断言 | `assertThat(versions.get(versions.size() - 1)).isEqualTo(116)` / `assertThat(Collections.max(migrationVersions)).isEqualTo(119)` |
| `assertj_last` | AssertJ 取末元素 | `assertThat(versions).last().isEqualTo(116)` |

**跨行也抓**（`assert max(\n versions\n) == 117`、Java 的链式换行断言）：判定跑在**折叠成单行**的
「只含代码」文本上，行号由位置映射反查（见 `_collapse`）。

**抓不到 / 有意不抓**（逐条登记在 `NOT_COVERED`，由 `test_registered_gaps_are_still_gaps` 钉住 ——
**该表有死亡条件**：谁把某条补上了，那条断言**当场变红**，逼他更新本表）：

| 形态 | 为什么现在抓不到 / 为什么不抓 |
|---|---|
| `top = max(versions); assert top == 118` | **变量间接取值**：中转变量名不含 version / migration ⇒ 要数据流分析，本守卫是文本层 |
| `def _highest(vs, n): assert max(vs) == n` | **自定义断言助手**：集合与常量都成了形参 ⇒ 同族但看不到 |
| `assertEquals(118, versions.stream()...max().orElseThrow())` | **Java Stream 归约**：`max()` 无参，与 `Optional` 流式写法在文本层不可区分 |
| `assert len(versions) == 119` | **有意不抓**：同病灶的**另一主张**（条数 ≠ 最大值），与「正好落了 N 条版本行」这类**合法**断言同形 ⇒ 抓它 = 制造假红 |
| `assert max(versions) <= 118` | **有意不抓**：`<=` 作为「上界 sanity bound」是合法写法，文本层与自毁主张不可区分（取舍口径同本仓弱断言门禁对 `toBeTruthy` 的处置） |

**覆盖面**（`test_surface_is_locked` 钉住）：扫 `SURFACE` 四个 glob；**前端测试面
（`frontend/**/*.test.tsx`）有意未扫** —— 迁移版本号主张是后端 / admin-api 面的形态，纳入会让
glob 与登记脱节。
⚠️ 另有一条**元层面**的边界：本守卫只判「文本层能看见的形态」。**任意正则 / 文本匹配都会误伤**
（实测：一条不加限定的 `isEqualTo(1\\d\\d)` 正则会命中 `ProductionServiceTest.java` 的
`assertThat(result.get("progress_percent")).isEqualTo(100)` —— 那是真断言）⇒ 本守卫用
「标识符名里必须含 version / migration」把**操作数**卡住（见 `_VER`），并把无关 `max(row) == 3`
写进 `LEGIT` 负控。

## 🔴 为什么"排除注释 / docstring"是本单的核心（不是锦上添花）

本仓那 7 处反面教材**就写在注释 / docstring 里**，而且它们**应该**存在（它们是"不要这么写"的论据）。
一条只会文本匹配的守卫会把它们**判红** —— 这正是 `migao-dev-flow` §17.3 点名过的
「**判据被自己的文案喂红 / 喂绿**」（该节已实证六条）。⇒ 本守卫只在**真代码**上判定：
`_py_code_only` 用标准库 `tokenize` 把注释 / 字符串字面量（含 docstring）遮蔽成等长空白，
`_java_code_only` 遮蔽 `//` `/* */` / 字符串 / 文本块。红证见判据 2 与
`test_exclusion_is_load_bearing_on_guard_own_fixtures`（**本文件自己的夹具**也验证了这条防线在承重）。
"""
from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 扫描面（相对仓库根）。按语言分文件：Python 走 `tokenize`，Java 走同族的遮蔽器。
SURFACE: tuple[str, ...] = (
    "tests/**/*.py",              # 迁移形态判据的主战场
    "backend/**/src/test/**/*.java",   # admin-api 的迁移形态判据
    "scripts/**/*.py",            # 同类「真值主张」脚本面
    ".github/**/*.py",            # CI 判据脚本面
)
_LANG_BY_SUFFIX = {".py": "py", ".java": "java"}

#: 命中时**逐字**打印的正确写法指引（issue #5166 正文的「正确口径」，先例可查）。
_GUIDANCE = """\
「最高迁移版本号 == 常量」是**自毁式真值主张**：下一个迁移一出现就必红，且报错文案把人指向错误行动。
正确写法（照抄，本仓既有先例）：
  Python： assert max(versions) >= N                      # 不主张「我是最大的」
          assert len([v for v in versions if v >= N]) == len({v for v in versions if v >= N})
  Java  ： assertThat(versions).contains(N);
          assertThat(versions.stream().filter(v -> v >= N).toList()).doesNotHaveDuplicates();
⚠️ 只查「**本档及以后**」——仓库存量里 V29 / V33 各有两份（历史遗留）⇒ 全量查重会历史假红。
先例：tests/unit_ci_workflows/test_inbound_order_idempotency.py（`>= 117`）、
      backend/admin-api/src/test/java/com/migao/admin/mapper/StockBatchConsumptionMapperTest.java
      （`doesNotHaveDuplicates`）。"""


class Unparseable(Exception):
    """源码无法词法化 ⇒ **不许静默跳过**（跳过 = 该文件永久免疫，见 `UNPARSEABLE_ALLOWED`）。"""


# ══════════════════ ① 非代码区遮蔽（本守卫唯一的假红防线） ══════════════════

def _blank(chunk: str) -> str:
    """等长空白（**保留 `\\n`**）：位置不变 ⇒ 可反查行号；换行保留 ⇒ 遮蔽区内不会跨行拼接。"""
    return re.sub(r"[^\n]", " ", chunk)


_NONCODE_TOKENS = {tokenize.COMMENT, tokenize.STRING} | {
    getattr(tokenize, _name)
    for _name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")   # 3.12+ 才拆 f-string
    if hasattr(tokenize, _name)
}


def _py_code_only(text: str) -> str:
    """注释 / 字符串字面量（含 docstring）⇒ 等长空白，只留真代码。"""
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise Unparseable(f"{exc.__class__.__name__}: {exc}") from exc
    out, last = [], 0
    for tok in toks:
        if tok.type not in _NONCODE_TOKENS:
            continue
        a = starts[tok.start[0] - 1] + tok.start[1]
        b = starts[tok.end[0] - 1] + tok.end[1]
        if a < last:
            continue
        out.append(text[last:a])
        out.append(_blank(text[a:b]))
        last = b
    out.append(text[last:])
    return "".join(out)


def _java_code_only(text: str) -> str:
    """`//` 行注释 / `/* */` 块注释（含 javadoc）/ 字符串 / 文本块 / 字符字面量 ⇒ 等长空白。"""
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif text.startswith('"""', i):
            j = text.find('"""', i + 3)
            j = n if j < 0 else j + 3
        elif text[i] in "\"'":
            quote, j = text[i], i + 1
            while j < n and text[j] != "\n":
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    j += 1
                    break
                j += 1
            j = min(j, n)
        else:
            out.append(text[i])
            i += 1
            continue
        out.append(_blank(text[i:j]))
        i = j
    return "".join(out)


_CODE_ONLY = {"py": _py_code_only, "java": _java_code_only}


def _collapse(code_only: str) -> tuple[str, list[int]]:
    """把「只含代码」的文本折成单行 —— 跨行调用 / 链式断言也能被同一条正则命中。

    返回 `(折叠文本, 折叠下标 → 原文下标)`；空白的折叠不改变字符序 ⇒ 行号可靠反查。
    """
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", code_only)]
    flat = " ".join(code_only[a:b] for a, b in spans)
    back: list[int] = []
    for i, (a, b) in enumerate(spans):
        if i:
            back.append(spans[i - 1][1])          # 折叠时插入的空格 → 映射到上一段末尾
        back.extend(range(a, b))
    return flat, back


# ══════════════════ ② 形态表（「能抓什么」的单一事实源） ══════════════════
#
# 参量 = 「版本号集合」的标识符：名字里**必须**含 version / migration。
# ⚠️ **有意不做**「任意 `max(...) == N`」的泛化：那会把 `assert max(row) == 3` 这类无关主张
#    一起判红（该形态见 `LEGIT` 的 `unrelated_max`，有负控）。
_VER = r"(?<![\w.])(?=[\w.]*(?:versions?|migrations?))[\w.]+"
#: 「取最后一个元素」的下标表达式。`size` 后括号可选：Java 里是 `size()`，而本仓既有文案里
#: 的转述形态是裸 `size - 1`（两种都抓，见 `_COUNTEREXAMPLE_PROSE` 的 Java 那条红证）。
_LAST_IDX = r"[\w.]*\s*(?:\.\s*)?size\s*(?:\(\s*\))?\s*-\s*1"
#: 「最高迁移版本号」表达式族（`_VER` 里已含 lookbehind，故整体只在这里加一次）。
_MAXEXPR = (
    rf"(?:(?<![\w.])(?:Collections\s*\.\s*)?max\s*\(\s*{_VER}\s*\)"          # max(versions)
    rf"|(?<![\w.])(?:sorted\s*\(\s*{_VER}\s*\)|{_VER})\s*\[\s*-1\s*\]"       # versions[-1]
    rf"|(?<![\w.])(?:max|highest|latest|greatest|last)_versions?"            # max_version
    rf"|(?<![\w.]){_VER}\s*\.\s*get\s*\(\s*{_LAST_IDX}\s*\)"                # versions.get(size()-1)
    rf"|(?<![\w.]){_VER}\s*\[\s*{_LAST_IDX}\s*\])"                          # versions[versions.size()-1]
)
_HELPER = r"assert(?:Equals?|_equal|_equals)"

#: `(形态 id, 正则)`。正则一律**不锚定 `assert`** —— 真值主张躲在 `assertTrue(...)` / 任意表达式里
#: 也一样是主张。`\s` 允许任意空白，因为判定跑在**折叠后的单行**上（见 `_collapse`）。
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("eq_rhs_const", re.compile(rf"(?:{_MAXEXPR})\s*==\s*\d+")),
    ("eq_lhs_const", re.compile(rf"\d+\s*==\s*(?:{_MAXEXPR})")),
    ("helper_const_first", re.compile(rf"{_HELPER}\s*\(\s*\d+\s*,\s*(?:{_MAXEXPR})")),
    ("helper_const_last", re.compile(rf"{_HELPER}\s*\(\s*(?:{_MAXEXPR})\s*,\s*\d+\s*\)")),
    ("assertj_isequalto", re.compile(
        rf"assertThat\s*\(\s*(?:{_MAXEXPR})[^;]*?\)\s*\.\s*isEqualTo\s*\(\s*\d+\s*\)")),
    ("assertj_last", re.compile(
        rf"assertThat\s*\(\s*{_VER}\s*\)\s*\.\s*(?:last|getLast)\s*\(\s*\)\s*\.\s*isEqualTo\s*\(\s*\d+\s*\)")),
)


class Hit(NamedTuple):
    path: str        # 仓库相对路径
    line: int
    pattern: str     # 命中的形态 id
    text: str        # 命中的原文片段


class Scan(NamedTuple):
    hits: tuple[Hit, ...]
    files: tuple[str, ...]      # 扫描到的文件（相对路径）—— 供「扫描面锁」用
    skipped: tuple[str, ...]    # 无法词法化的文件（fail-closed，见 UNPARSEABLE_ALLOWED）


def scan_file(path: Path, rel: str, *, exclude_noncode: bool = True) -> list[Hit]:
    """扫描一个文件。`exclude_noncode=False` = **去掉排除逻辑**（只在判据 2 的红证里用）。"""
    text = path.read_text(encoding="utf-8")
    lang = _LANG_BY_SUFFIX[path.suffix]
    code = _CODE_ONLY[lang](text) if exclude_noncode else text
    flat, back = _collapse(code)
    hits = [Hit(rel, text.count("\n", 0, back[m.start()]) + 1, pid, m.group(0).strip())
            for pid, rx in _PATTERNS for m in rx.finditer(flat)]
    return sorted(set(hits), key=lambda h: (h.line, h.pattern))


def scan_repo(root: Path = REPO_ROOT, *, exclude_noncode: bool = True) -> Scan:
    """扫描 `SURFACE` 全部文件。读失败 / 词法化失败一律**不静默吞**（fail-closed）。

    结果**只对仓库根**记忆化：本文件有 7 条判据要对同一棵树取读数，而全量扫描（~500 个文件）
    是这里唯一的开销来源 ⇒ 不记忆化就等于把 CI 时间乘以 7。
    ⚠️ `tmp_path` **绝不记忆化** —— 它按测试函数复用：缓存它会让同一条判据的后续参数拿到前一个
    注入的旧读数（实测：17 条注入红证当场变成假绿）。
    """
    if root != REPO_ROOT:
        return _scan_repo(root, exclude_noncode=exclude_noncode)
    key = exclude_noncode
    if key not in _SCAN_CACHE:
        _SCAN_CACHE[key] = _scan_repo(root, exclude_noncode=exclude_noncode)
    return _SCAN_CACHE[key]


def _scan_repo(root: Path, *, exclude_noncode: bool) -> Scan:
    hits: list[Hit] = []
    files: list[str] = []
    skipped: list[str] = []
    for pattern in SURFACE:
        for path in sorted(root.glob(pattern)):
            if not path.is_file() or path.suffix not in _LANG_BY_SUFFIX:
                continue
            rel = path.relative_to(root).as_posix()
            files.append(rel)
            try:
                hits.extend(scan_file(path, rel, exclude_noncode=exclude_noncode))
            except Unparseable:
                if exclude_noncode:
                    skipped.append(rel)
                else:
                    raise
    return Scan(tuple(hits), tuple(sorted(set(files))), tuple(skipped))


_SCAN_CACHE: dict[bool, Scan] = {}


def _render(hits) -> str:
    body = "\n  ".join(f"{h.path}:{h.line}: {h.text}   [{h.pattern}]" for h in hits)
    return (f"❌ 检出「自毁式真值主张」（断言最高迁移版本号 == 常量）共 {len(hits)} 处：\n  {body}\n\n"
            + _GUIDANCE)


#: 无法词法化的文件豁免表。**有死亡条件**（见 `test_unparseable_is_fail_closed_and_allowlist_has_death_condition`）：
#: 豁免的文件变得可解析 ⇒ 该条豁免已死 ⇒ 当场变红，逼人删掉它（`migao-dev-flow` §17.3 ④ 的口径）。
UNPARSEABLE_ALLOWED: frozenset[str] = frozenset()


# ══════════════════ ③ 语料：能抓（红证素材）/ 不能抓（登记）/ 合法（负控） ══════════════════

#: 每种形态至少一条**真实形状**的样例；`patterns` = 期望命中的形态 id（**恰好相等**，不多不少）。
CORPUS: dict[str, dict] = {
    "py_max_eq": {"lang": "py", "line": 3, "patterns": {"eq_rhs_const"},
                  "code": "def test_dummy():\n    versions = [116, 117]\n    assert max(versions) == 117\n"},
    "py_max_eq_reversed": {"lang": "py", "line": 3, "patterns": {"eq_lhs_const"},
                           "code": "def test_dummy():\n    versions = [116, 117]\n    assert 117 == max(versions)\n"},
    "py_subscript_last": {"lang": "py", "line": 3, "patterns": {"eq_rhs_const"},
                          "code": "def test_dummy():\n    migration_versions = [116, 117]\n    assert migration_versions[-1] == 117\n"},
    "py_sorted_last": {"lang": "py", "line": 3, "patterns": {"eq_rhs_const"},
                       "code": "def test_dummy():\n    versions = [116, 117]\n    assert sorted(versions)[-1] == 117\n"},
    "py_max_version_var": {"lang": "py", "line": 3, "patterns": {"eq_rhs_const"},
                           "code": "def test_dummy():\n    max_version = 117\n    assert max_version == 117\n"},
    "py_multiline": {"lang": "py", "line": 3, "patterns": {"eq_rhs_const"},
                     "code": "def test_dummy():\n    versions = [116, 117]\n    assert max(\n        versions\n    ) == 117\n"},
    "py_assert_equal_last": {"lang": "py", "line": 3, "patterns": {"helper_const_last"},
                             "code": "def test_dummy(self):\n    versions = [116, 117]\n    self.assertEqual(max(versions), 117)\n"},
    "py_assert_equal_first": {"lang": "py", "line": 3, "patterns": {"helper_const_first"},
                              "code": "def test_dummy(self):\n    migration_versions = [116, 117]\n    self.assertEqual(117, max(migration_versions))\n"},
    "java_get_size_minus_1": {"lang": "java", "line": 3, "patterns": {"assertj_isequalto"},
                              "code": "class V {\n    void t() {\n        assertThat(versions.get(versions.size() - 1)).isEqualTo(116);\n    }\n}\n"},
    "java_get_no_receiver": {"lang": "java", "line": 3, "patterns": {"assertj_isequalto"},
                             "code": "class V {\n    void t() {\n        assertThat(versions.get(size() - 1)).isEqualTo(116);\n    }\n}\n"},
    "java_assertEquals_get": {"lang": "java", "line": 3, "patterns": {"helper_const_first"},
                              "code": "class V {\n    void t() {\n        assertEquals(116, versions.get(versions.size() - 1));\n    }\n}\n"},
    "java_assertThat_last": {"lang": "java", "line": 3, "patterns": {"assertj_last"},
                             "code": "class V {\n    void t() {\n        assertThat(versions).last().isEqualTo(116);\n    }\n}\n"},
    "java_assertTrue_bare_eq": {"lang": "java", "line": 3, "patterns": {"eq_rhs_const"},
                                "code": "class V {\n    void t() {\n        assertTrue(versions.get(versions.size() - 1) == 116);\n    }\n}\n"},
    "java_collections_max": {"lang": "java", "line": 3, "patterns": {"assertj_isequalto"},
                             "code": "class V {\n    void t() {\n        assertThat(Collections.max(migrationVersions)).isEqualTo(119);\n    }\n}\n"},
    "java_assertEquals_collections_max": {"lang": "java", "line": 3, "patterns": {"helper_const_first"},
                                          "code": "class V {\n    void t() {\n        assertEquals(119, Collections.max(migrationVersions));\n    }\n}\n"},
    "java_multiline_chain": {"lang": "java", "line": 3, "patterns": {"assertj_isequalto"},
                             "code": "class V {\n    void t() {\n        assertThat(versions.get(versions.size() - 1))\n                .isEqualTo(116);\n    }\n}\n"},
    "java_subscript_size_minus_1": {"lang": "java", "line": 3, "patterns": {"helper_const_first"},
                                    "code": "class V {\n    void t() {\n        assertEquals(116, versions[versions.size() - 1]);\n    }\n}\n"},
}

#: **已知抓不到 / 有意不抓**的形态（如实登记）。判据见 `test_registered_gaps_are_still_gaps`：
#: 本表现在还抓不到 ⇒ 绿；**谁把它补上了（或部分补上了）⇒ 那条断言当场变红**，逼他更新本表
#: 与模块头那张表（`migao-dev-flow` §17.3 ④ 的口径）。**不许**把"抓不到"伪装成"已覆盖"。
NOT_COVERED: dict[str, dict] = {
    "via_unversioned_var": {
        "lang": "py",
        "code": "def test_dummy():\n    top = max(versions)\n    assert top == 118\n",
        "reason": "**变量间接取值**：中转变量的名字不含 version / migration ⇒ 需要数据流分析（本守卫是文本层）。"},
    "helper_with_renamed_param": {
        "lang": "py",
        "code": "def _highest(vs, n):\n    assert max(vs) == n\n",
        "reason": "**自定义断言助手**：版本号集合与常量都变成了形参 ⇒ 同族，本守卫看不到。"},
    "java_stream_max": {
        "lang": "java",
        "code": "class V {\n    void t() {\n        assertEquals(118, versions.stream().mapToInt(Integer::intValue).max().orElseThrow());\n    }\n}\n",
        "reason": "**Java Stream 归约取值**：`max()` 无参（不是 `max(versions)`），文本层与 `Optional` 流式写法不可区分。"},
    "count_claim_deliberately_out": {
        "lang": "py",
        "code": "def test_dummy():\n    assert len(versions) == 119\n",
        "reason": "**有意不抓**：`len(versions) == N` 是同一病灶的**另一主张**（条数 ≠ 最大值），"
                  "而它与「正好落了 N 条版本行」这类**合法**断言在文本层完全同形 ⇒ 抓它 = 制造假红。"},
    "upper_bound_deliberately_out": {
        "lang": "py",
        "code": "def test_dummy():\n    assert max(versions) <= 118\n",
        "reason": "**有意不抓**：`max(versions) <= N` 作为「上界 sanity bound」是合法写法，"
                  "与自毁式主张在文本层不可区分（取舍口径同本仓弱断言门禁对 `toBeTruthy` 的处置）。"},
}

#: **合法写法负控**：一条都不许命中。含 4 条「反面教材写在注释 / docstring / 字符串里」的负控
#: —— 它们就是 `_COUNTEREXAMPLE_PROSE` 那 7 处在**其它文件**里的同形形态，也是判据 2 的最小复现。
LEGIT: dict[str, dict] = {
    "py_ge_not_eq": {"lang": "py",
                     "code": "def test_dummy():\n    versions = [117, 118]\n    assert max(versions) >= 118, f\"最大 V{max(versions)}\"\n"},
    "py_unique_tail": {"lang": "py",
                       "code": "def test_dummy():\n    versions = [117, 118]\n    assert len([v for v in versions if v >= 118]) == len({v for v in versions if v >= 118})\n"},
    "py_contains": {"lang": "py",
                    "code": "def test_dummy():\n    versions = [117, 118]\n    assert 118 in versions\n"},
    "py_count": {"lang": "py",
                 "code": "def test_dummy():\n    versions = [117, 118]\n    assert versions.count(118) == 1\n"},
    "unrelated_max": {"lang": "py",
                      "code": "def test_dummy():\n    row = [1, 2, 3]\n    assert max(row) == 3\n"},
    "java_contains": {"lang": "java",
                      "code": "class V {\n    void t() {\n        assertThat(versions).contains(116);\n    }\n}\n"},
    "java_doesNotHaveDuplicates": {"lang": "java",
                                   "code": "class V {\n    void t() {\n        assertThat(versions.stream().filter(v -> v >= 116).toList()).doesNotHaveDuplicates();\n    }\n}\n"},
    "java_unrelated_max": {"lang": "java",
                           "code": "class V {\n    void t() {\n        assertEquals(3, row.get(row.size() - 1));\n    }\n}\n"},
    "prose_py_comment": {"lang": "py",
                         "code": "def test_dummy():\n    # ⚠️ 不得写成 max(versions) == 118（自毁式真值主张）\n    versions = [118]\n"},
    "prose_py_docstring": {"lang": "py",
                           "code": "def test_dummy():\n    \"\"\"⚠️ **不得**写成 `max(versions) == 91`：下一个迁移一出现就自毁。\"\"\"\n    versions = [118]\n"},
    "prose_py_string": {"lang": "py",
                        "code": "MSG = \"不得写成 versions[-1] == 118\"\n"},
    "prose_java_line_comment": {"lang": "java",
                                "code": "class V {\n    void t() {\n        // ⚠️ 这里原写 `versions.get(size - 1) == 116`（「V116 是当前最大迁移号」）\n        int x = 1;\n    }\n}\n"},
    "prose_java_javadoc": {"lang": "java",
                           "code": "class V {\n    /** ⚠️ 不得写成 assertThat(versions.get(versions.size() - 1)).isEqualTo(116) */\n    void t() {}\n}\n"},
    "prose_java_text_block": {"lang": "java",
                              "code": "class V {\n    String s = \"\"\"\n        不得写成 max(versions) == 118\n        \"\"\";\n}\n"},
}

#: **反面教材（应该存在的文案）**：`(仓库相对全路径, 文本锚点)`。它们**必须留着**（它们是"不要这么写"的
#: 论据），同时守卫**必须对它们绿** —— 这两件事一起构成本单的核心判据 2。⚠️ **不写行号**（活跃文件的裸行号
#: 几分钟就失效，且本仓 Case Trust 规则 G 对裸 `文件名:行号` 判红）。
_COUNTEREXAMPLE_PROSE: tuple[tuple[str, str], ...] = (
    ("tests/unit_ci_workflows/test_inbound_opening_register.py", "原写 `max(versions) == 118`"),
    ("tests/unit_ci_workflows/test_set_code_storage_v92_migration.py", "`max(versions) == 88` 的处置"),
    ("tests/unit_ci_workflows/test_v91_baseline_operations_backfill.py", "不得**写成 `max(versions) == 91`"),
    ("tests/unit_ci_workflows/test_public_ops_v88_migration.py", "本判据原写 `max(versions) == 88`"),
    ("tests/unit_ci_workflows/test_cutting_plan_meters_migration.py", "不写 `max(versions) == 119`"),
    ("tests/unit_ci_workflows/test_deposition_total_migration.py", "不写 `max(versions) == 102`"),
    ("backend/admin-api/src/test/java/com/migao/admin/mapper/StockBatchConsumptionMapperTest.java",
     "原写 `versions.get(size - 1) == 116`"),
)

_GUARD_REL = "tests/unit_ci_workflows/test_self_destruct_assert_guard.py"


#: 全部语料（含合法负控与登记缺口）—— 只给 `_inject` 取正文用。
_ALL_CORPUS: dict[str, dict] = {**CORPUS, **NOT_COVERED, **LEGIT}


def _inject(tmp_path: Path, name: str) -> Path:
    """把语料写成一个**真文件**（放进临时目录里，按真仓库的同款路径布局 ⇒ 走同一套扫描面 glob）。"""
    entry = _ALL_CORPUS[name]
    if entry["lang"] == "py":
        path = tmp_path / "tests" / "unit_ci_workflows" / f"injected_{name}.py"
    else:
        path = tmp_path / "backend" / "admin-api" / "src" / "test" / "java" / f"Injected{name}.java"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(entry["code"], encoding="utf-8")
    return path


# ══════════════════ ④ 判据 ══════════════════

def test_real_tree_has_zero_violations():
    """**零容忍**：现仓库一处违规都没有 ⇒ **不需要** burn-down 白名单（存量违规若出现 ⇒ 红，就地修）。

    防「空跑」：扫描面必须非空，且命中时打印**文件 + 行 + 正确写法指引**（不会红的断言 = 空断言）。
    """
    scan = scan_repo()
    assert len(scan.files) > 100, f"扫描面异常（只扫到 {len(scan.files)} 个文件）⇒ 本判据空跑"
    assert not scan.hits, _render(scan.hits)
    assert "max(versions) >= N" in _render([Hit("x", 1, "eq_rhs_const", "y")]), "命中提示里没有正确写法指引"


@pytest.mark.parametrize("name", list(CORPUS))
def test_injected_violation_is_red_and_named(tmp_path, name):
    """判据 1：注入一个**真实违规**（真文件）⇒ 守卫红，且**指名文件与行**；删除注入 ⇒ 恢复绿。"""
    entry = CORPUS[name]
    path = _inject(tmp_path, name)
    rel = path.relative_to(tmp_path).as_posix()
    scan = scan_repo(tmp_path)
    assert {h.pattern for h in scan.hits} == entry["patterns"], (
        f"形态 {name} 的命中集不对：{[h.pattern for h in scan.hits]}\n{_render(scan.hits)}")
    assert [(h.path, h.line) for h in scan.hits] == [(rel, entry["line"])] * len(scan.hits), (
        f"没有**指名文件与行**（期望 {rel} 第 {entry['line']} 行）：\n{_render(scan.hits)}")
    report = _render(scan.hits)
    assert rel in report and str(entry["line"]) in report and "max(versions) >= N" in report, (
        f"命中报告缺文件 / 行号 / 正确写法指引：\n{report}")
    path.unlink()
    assert scan_repo(tmp_path).hits == (), "删除注入后**没有**恢复绿 ⇒ 判定与注入无关（空断言）"


@pytest.mark.parametrize("name", list(LEGIT))
def test_legit_forms_stay_green(tmp_path, name):
    """判据 3：正确写法（`>=` + 本档及以后无重复）与无关 `max(...)` 主张 ⇒ **不得误报**。"""
    path = _inject(tmp_path, name)
    assert path.exists()
    scan = scan_repo(tmp_path)
    assert not scan.hits, f"合法写法被误报：{name}\n{_render(scan.hits)}"


def test_counterexample_prose_is_kept_and_green():
    """判据 2（绿侧）：7 处「不要这么写」的**反面教材**（注释 / docstring）**必须留着**，守卫对它们绿。

    两面都钉：① 文案还在（有人删了它 ⇒ 红：判据 2 的红证素材消失，本守卫的核心判据会退化成空跑）；
    ② 守卫对它们零命中（这一条才是"排除注释 / docstring"在承重）。
    """
    missing = [rel for rel, anchor in _COUNTEREXAMPLE_PROSE
               if anchor not in (REPO_ROOT / rel).read_text(encoding="utf-8")]
    assert not missing, f"反面教材文案丢了（判据 2 的红证素材消失）：{missing}"
    flagged = {h.path for h in scan_repo().hits} & {rel for rel, _ in _COUNTEREXAMPLE_PROSE}
    assert not flagged, f"反面教材的**注释**被判红了（判据被自己的文案喂红）：{sorted(flagged)}"


def test_dropping_noncode_exclusion_turns_counterexamples_red():
    """判据 2（红证）：**去掉排除逻辑**（让注释 / docstring 参与判定）⇒ 那 7 处反面教材**当场变红**。

    这条是「判据不是在**被自己的文案喂红**」的正面证据：红不是来自真违规，而是来自遮蔽器。
    没有它，`test_counterexample_prose_is_kept_and_green` 无法排除「本来就没命中过」的空跑情形。
    """
    raw = scan_repo(exclude_noncode=False)
    flagged = {h.path for h in raw.hits}
    anchors = {rel for rel, _ in _COUNTEREXAMPLE_PROSE}
    assert anchors <= flagged, (
        f"去掉排除逻辑后仍有反面教材没被判红 ⇒ 排除逻辑**不是**承重的那一层（红证无效）：\n"
        f"  未变红 = {sorted(anchors - flagged)}")
    assert len(raw.hits) > len(scan_repo().hits), "原始文本扫描的命中数没有变多 ⇒ 遮蔽器没起作用"


def test_exclusion_is_load_bearing_on_guard_own_fixtures():
    """机制级红证：**本守卫自己的夹具**（`CORPUS` 那些写在字符串字面量里的违规样例）也是承重证据。

    关掉遮蔽 ⇒ 本文件自己被判红一片；开着 ⇒ 恰好 0 处。⇒ 「排除注释 / 字符串」不是装饰。
    """
    path = REPO_ROOT / _GUARD_REL
    raw = scan_file(path, _GUARD_REL, exclude_noncode=False)
    assert len(raw) >= 10, f"本文件的夹具没构成「自己的文案」红证素材（只有 {len(raw)} 处）⇒ 判据 2 空跑"
    assert scan_file(path, _GUARD_REL) == [], "本守卫自扫不为零（夹具把自己喂红了）"


def test_every_pattern_has_a_red_proof():
    """**新增形态必须配红证**：`_PATTERNS` 里每条形态都得有语料样例，且样例命中集**恰好**等于声明集。"""
    declared = {pid for pid, _ in _PATTERNS}
    covered = set().union(*(e["patterns"] for e in CORPUS.values()))
    assert covered == declared, f"形态与红证不匹配：缺红证 = {sorted(declared - covered)}；多余 = {sorted(covered - declared)}"
    for name, entry in CORPUS.items():
        assert entry["patterns"], f"{name} 没声明期望命中的形态 id"
        assert entry["code"].count("\n") >= entry["line"] - 1, f"{name} 的期望行号越界"


def test_registered_gaps_are_still_gaps(tmp_path):
    """判据 4：`NOT_COVERED` 是**有死亡条件的登记** —— 现在还抓不到 ⇒ 绿；谁补上了 ⇒ 本判据**当场变红**。

    不写这条，"覆盖边界"就只是注释里的一句话：下一个人既不知道这些形态**现在**确实漏着，
    也不知道自己把它补上了。⇒ 红了的修法是**更新 `NOT_COVERED` 与模块头那张表**，
    **不是**把本判据删掉。
    """
    newly_covered = []
    for name in NOT_COVERED:
        path = _inject(tmp_path, name)
        if scan_repo(tmp_path).hits:
            newly_covered.append(name)
        path.unlink()
    assert not newly_covered, (
        f"这些形态**已经**被抓到了（好消息）：{newly_covered} —— 请把它们从 `NOT_COVERED` 移进 `CORPUS`"
        f"（并同步本文件模块头那张「能抓 / 抓不到」的表），再删掉对应条目。")


def test_surface_is_locked():
    """判据 4（覆盖面登记）：扫描面 = `SURFACE` 四个 glob；**前端测试面有意未扫**（登记 + 死亡条件）。

    红色语义：谁把前端（或别的面）纳入扫描、或 glob 被改坏 ⇒ 本判据变红 ⇒ 必须同步模块头登记。
    """
    scan = scan_repo()
    assert set(scan.files) and all(p.endswith((".py", ".java")) for p in scan.files)
    assert all(p.startswith(("tests/", "backend/", "scripts/", ".github/")) for p in scan.files)
    frontend = sorted(REPO_ROOT.glob("frontend/**/*.test.tsx"))
    assert frontend, "前端测试面登记已失效：仓库里找不到任何 *.test.tsx（请重新登记覆盖面）"
    assert not [p for p in frontend if p.relative_to(REPO_ROOT).as_posix() in set(scan.files)], (
        "前端测试文件进了扫描面 ⇒ 请同步模块头的覆盖面登记（本守卫当前**有意**不扫前端："
        "迁移版本号主张是后端 / admin-api 面的形态）")


def test_unparseable_is_fail_closed_and_allowlist_has_death_condition():
    """fail-closed：无法词法化的文件**不许静默跳过**（跳过 = 该文件永久免疫）；豁免表**有死亡条件**。"""
    scan = scan_repo()
    unparseable = set(scan.skipped)
    assert not (unparseable - UNPARSEABLE_ALLOWED), f"这些文件无法词法化、未登记（不许静默跳过）：{sorted(unparseable - UNPARSEABLE_ALLOWED)}"
    assert not (UNPARSEABLE_ALLOWED - unparseable), f"这些豁免已死（文件已能解析）⇒ 请删掉豁免：{sorted(UNPARSEABLE_ALLOWED - unparseable)}"


# ══════════════════ ⑤ CLI（人可直跑，命中时打印正确写法指引） ══════════════════

if __name__ == "__main__":
    _scan = scan_repo()
    print(_render(_scan.hits) if _scan.hits else
          f"✅ 零处自毁式真值主张（扫描 {len(_scan.files)} 个文件，跳过 {len(_scan.skipped)} 个）")
    raise SystemExit(1 if _scan.hits else 0)
