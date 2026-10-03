# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI / 用例库结构类 L0 不变式统一挂 MC-012
#   —— 本判据与本目录 `test_case_seed_truth*.py` / `test_case_trust_gate.py` 同族：
#   守的是「用例库这个**台账**与仓库实际状态是否一致」，不新造用例族。）
"""用例库点名的**测试方法名**必须真实存在于仓库（issue #6147）。

## 病灶（一类缺陷，不是一个缺陷）

`.github/cases/*.yml` 的 `data_checks` 是将来做**红证**的人唯一能依赖的锚：它逐条写着
「这条判据的证据 = `<某测试类>`「`<某测试方法>`」」。而现行门禁**照不到**方法名这一层：

- `Case Contract (truths_ref)` 只校验 `truths_ref` 能解析；
- `Case Trust` 规则 G/引用新鲜度只看**文件名 / 行号**（裸文件名 + `:行号`）；
- `CASE-TRUST-PROSE-TEST-REF-GHOST`（#5196，判据 = `.github/assertion_taxonomy.py::prose_test_ref_audit`）
  只判「散文点名的**测试类 / 文件**是否有同名文件」—— 实测读数（本单现取）：全库 **幽灵名 0 条**。

⇒ 散文可以点名一个**根本不存在的方法**而无人发现（#6147 实锚：`processing-order.yml` 的 PG-020
写 `createWithoutPositionsKeepsLegacyBehaviour` / `updateWithoutPositionsKeepsLegacyBehaviour`，
而真名是 `createWithoutPositionsStillCreatesTheSinglePriceRow` /
`updateWithoutPositionsOnDisabledOperationLeavesTheMatrixAlone`）。后果不是「少一条断言」，
而是**这条判据的红证重跑不起来**（用例库与现实脱节 —— 铁律 7 / #5196 的原话）。

## 判据（全部**按现取**，不抄手写清单 —— 抄清单就是第二个会腐烂的台账）

| # | 判什么 | 语料（现取） | 红证 |
|---|---|---|---|
| 1 | **引用面**：`.github/cases/*.yml` 里**「」点名**的 camelCase 记号，必须能解析到真名 | `「([^「」]+)」` ∩ `^[a-z][A-Za-z0-9_]{4,80}$` | 把 PG-020 的证据改回旧名 ⇒ 指名报出 `文件:行 → 幽灵名 → 建议去哪找` |
| 2 | **真名面**：Java `void <name>(` + Python `def test_*(`（后端测试树 ∪ 仓根 `tests/`）+ 前端测试文件 basename / stem | `backend/*/src/test/**/*.java`、`backend/*/tests/**/*.py`、`tests/**/*.py`、`frontend/*/tests/**`、`frontend/*/e2e/**` | 真名面解析不到 ⇒ 判据 7 fail-closed（**不许**退化成「幽灵 0 条」的假绿） |
| 3 | **定域**：`「」` 里**是值不是名**的记号（如 `「producing」` / `「shipments」`）不判 —— 定域谓词 = 「该记号在测试文件里出现过」∨ `test_` 前缀 | `repo_index()` 的 `test_identifiers` | 改回「只看形状」⇒ 实测 2 条值字面量假红；收紧形状谓词 ⇒ 实测 6 个**真测试名**被误挡（见台账 `value_shaped`） |
| 4 | **豁免台账只许缩短 + 条目活着**：每条须在**当前**语料里仍出现（销账即删），条数 ≤ 本文件冻结上限 | `case_prose_test_names_ledger.json` | 台账挂一条已不出现的名字 ⇒ 红；加第 8 条 ⇒ 红 |
| 5 | **空转防护**：引用面不得为空（判据被正则改坏 ⇒ 不许静默通过） | 同上 | 引用面 0 条 ⇒ 红 |
| 6 | **判别力自证**：同一份判定本体喂内存夹具（真名 / 幽灵名 / 值字面量 / `test_` 前缀蛇形名 / 只改注释）+ **真语料上的内存变异** | 内存构造 + 真文件文本 | 幽灵名不红、值字面量被误判、注入没生效 ⇒ 红 |
| 7 | **语料非空自证** | 探针路径必须解析到文件 | 目录改名 / 真名面消失 ⇒ 红（fail-closed） |

## 豁免台账 = `case_prose_test_names_ledger.json`（数据文件，**diff 里看得见**）

`exemptions` 逐条登记「名字在仓里不存在」的引用：必须有 `kind`（`tests` / `value_shaped`）/ `file` /
`name` / `cases` / `case` / `issue` / `owner` / `reason` / `counterpart` / `criterion`
—— **判据不因登记而放弃**：它只是把「本单改不完的存量」显式钉住（铁律 8 的豁免台账形态），
`frozen_cap` 只许降不许升。`kind=tests` = 真·找不到现名的**测试名**引用（清账 = 补测 / 改判）；
`kind=value_shaped` = **定域残余**（该记号是值、不是测试名 —— 这与「拼错名」在本判据里形状相同、
静态不可区分，故只能登记，理由逐条写在条目里）；两种条目的清账方式见各自 `criterion`。

## 边界（照实登记，**不是**「已覆盖」）

- **射程 = 「」点名的 camelCase 记号**：`.github/cases/**` 里 `「」` 实际只用来引测试方法名**与少量值字面量**
  （本单现取：203 个 camel 记号，修完剩台账那 7 条）。所以**没被 `「」` 包起来的名字不在面内**
  —— 例如前端用例块名（`㉕-②`）与散文里的反引号符号（那种形态里既有生产常量如
  `` `ProductionOperationQueryService.normalizeOperationName` `` 也有测试名，形态不可区分）。
  用**散文**当判据会逼出「改措辞消红」的纸面修复（#5196 的 `_EXT_ALIASES` 已记过同族取舍）。
- 只判**方法 / 函数级测试名**：测试**文件**级引用由既有的
  `CASE-TRUST-PROSE-TEST-REF-GHOST`（判据 = `.github/assertion_taxonomy.py::prose_test_ref_audit`）负责
  —— 两把尺子判**不同粒度**，不互为副本（#5196 的 `counterexample` 读数仍由那边守着）。
- 真名面是**词法**取值（`void` / `def test_` 的形态），不做编译：形如测试名的**生产**方法
  （helper / 同文件私有方法）会被算作「存在」⇒ 这是**假绿方向**（漏检），不会误伤。
- **定域谓词的漏检方向**（照实登记，见台账 `uncovered_faces` 第 4 条）：一个「既拼错、又从未在测试
  文件里出现过、且不带 `test_` 前缀」的记号会落在面外 —— 这是本判据**有意接受**的取舍（收紧会把
  6 个真测试名误挡）。
- 前端真名面只有**文件 basename / stem**；前端用例块名（`describe` / `it` 文案）**不在面内**
  （本单现取：语料里没有一条引用了块名）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_CI_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
CASES_DIR = REPO_ROOT / ".github" / "cases"
LEDGER_PATH = UNIT_CI_DIR / "case_prose_test_names_ledger.json"

if str(UNIT_CI_DIR) not in sys.path:  # 共享解析实现（`_source_parsing`）的唯一家
    sys.path.insert(0, str(UNIT_CI_DIR))

import _source_parsing as SP  # noqa: E402  （判据面唯一一份「引号感知」的词法走查）

#: 真名面的**探针路径**（判据 6 fail-closed 用：解析不到 ⇒ 语料面没了 ⇒ 不许静默绿）。
JAVA_TEST_GLOB = "backend/*/src/test/**/*.java"
PY_TEST_GLOBS = ("backend/*/tests/**/*.py", "tests/**/*.py")
FRONTEND_TEST_GLOBS = ("frontend/*/tests/**/*.ts", "frontend/*/tests/**/*.tsx",
                       "frontend/*/tests/**/*.js", "frontend/*/tests/**/*.mjs",
                       "frontend/*/e2e/**/*.ts", "frontend/*/e2e/**/*.tsx")

#: 引用面：**「」点名** 的 camelCase 记号（用例库的实际引法；见 docstring 边界）。
QUOTED = re.compile(r"「([^「」\n]{1,120})」")
#: 名字形状：首字母小写的 camelCase / snake_case（排除「布帘」「OK」这类非名字）。
NAME_SHAPE = re.compile(r"^[a-z][A-Za-z0-9_]{4,80}$")
#: Python 测试名（**确定**是测试名：`test_` 前缀 + snake_case）—— CPython 侧不靠 `test_` 命名约定？
PY_TEST_NAME = re.compile(r"^test_[a-z0-9_]+$")
#: `「」` 在语料里**两种用途都有**（测试名 + 少量生产符号值，如「producing」/「shipments」）⇒ 定域靠
#: 「这个记号**在测试文件里出现过**吗」（见过 ⇒ 是有人引的测试名域；没见过 ⇒ 散文 / 生产符号值）。
#: 这条使「测试名**拼错** / 已改名 / 从未存在」仍然红（真名与拼错的记号都不在索引里 ⇒ 不丢判据），
#: 而纯散文词不再假红。残余（漏检方向，照实登记在台账 `uncovered_faces`）：一个**既拼错又从未在
#: 测试文件里出现过**的「生产符号形态」记号不在面内。
IDENT_SHAPE = re.compile(r"^[a-z][A-Za-z0-9_]{4,80}$")
#: 真名面的词法取法（不编译；见 docstring 边界）。
JAVA_METHOD = re.compile(r"\bvoid\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PY_TEST_DEF = re.compile(r"^[ \t]*def\s+(test_[A-Za-z0-9_]*)\s*\(", re.MULTILINE)

#: 豁免台账的**冻结上限**（只许缩短；加一条 = 判据红）。
EXEMPTION_CAP_FROZEN = 7
#: 台账条目的两种形态：`tests` = 真·找不到现名的**测试名**引用（清账 = 补测 / 改判）；
#: `value_shaped` = 定域残余（该记号是**值**、不是测试名，见台账各自的 reason）。
EXEMPTION_KINDS = ("tests", "value_shaped")


# ══════════════════════════════════════════════════════════════════════════════
# 一、判定本体（纯函数 —— 判据与红证喂**同一份**实现）
# ══════════════════════════════════════════════════════════════════════════════

def iter_quoted_names(text: str):
    """`「」` 点名的**名字形状**记号（`(名字, 出现次数)`，按首次出现排序）。"""
    seen: dict[str, int] = {}
    for m in QUOTED.finditer(text):
        token = m.group(1).strip()
        if NAME_SHAPE.match(token):
            seen[token] = seen.get(token, 0) + 1
    return sorted(seen.items())


def in_scope(token: str, test_identifiers) -> bool:
    """记号是否落在「测试名」域（判据 1 的**定域**谓词；理由见 `IDENT_SHAPE` 上的注释）。"""
    return ("_" in token and PY_TEST_NAME.match(token)) or token in test_identifiers


def resolve_token(token: str, real_names) -> bool:
    """记号能否解析到真名（**精确**同名；同族归一的范围见 docstring 边界）。"""
    return token in real_names


def scan(unverified_maps, real_names, test_identifiers=frozenset()):
    """逐语料扫「引用了仓里不存在的测试方法名」：`[(相对路径, 行号, 记号, 出现次数)]`。

    纯函数（**唯一输入是文本 + 两个名字集合**）⇒ 红证可以在内存里喂夹具，不碰真仓。
    `test_identifiers` 只做**定域**（是不是在测试名域），`real_names` 才做**判定**（这个名字真在不在）
    —— 两者分开，是为了让「测试名拼错 / 已改名 / 从未存在」照样红（见 `IDENT_SHAPE` 注释）。
    """
    findings = []
    for rel in sorted(unverified_maps):
        text = unverified_maps[rel]
        for token, count in iter_quoted_names(text):
            if not in_scope(token, test_identifiers):
                continue
            if resolve_token(token, real_names):
                continue
            line = text[:text.index("「" + token)].count("\n") + 1
            findings.append((rel, line, token, count))
    return findings


def finding_message(finding, real_names) -> str:
    """**可行动**报错：哪个用例 → 哪一行 → 引用了哪个不存在的名字 → 建议去哪找真名。"""
    rel, line, token, count = finding
    hint = _nearest_names(token, real_names)
    return (
        f"{rel}:{line} → 引用了**仓里不存在**的测试方法名「{token}」（本文件出现 {count} 次）\n"
        f"    → 该用例的红证**重跑不起来**。修法二选一（**不许为凑绿删引用**）：\n"
        f"      ① 改名到真名（先 `grep -rn 'void {token}\\|def {token}' backend frontend` 核）；\n"
        f"      ② 确属「找不到现名对应」⇒ 登记进 {LEDGER_PATH.name} 的 exemptions"
        f"（带 issue / owner / counterpart / criterion，且上限只许下降）。\n"
        f"    → 名字相近的真名候选：{hint}"
    )


def _nearest_names(token: str, real_names, limit: int = 5):
    """报错里的「建议去哪找真名」：按**公共 token** 交集给候选（确定性、不猜语义）。"""
    parts = {p for p in re.split(r"[^A-Za-z]+", token) if len(p) > 2}
    scored = []
    for name in real_names:
        shared = len({p for p in re.split(r"[^A-Za-z]+", name) if len(p) > 2} & parts)
        if shared:
            scored.append((shared, len(name), name))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    return [n for _s, _l, n in scored[:limit]] or ["（无 —— 该能力可能整体退场，见台账 counterpart）"]


# ══════════════════════════════════════════════════════════════════════════════
# 二、语料装载（按现取）
# ══════════════════════════════════════════════════════════════════════════════

def load_cases():
    """`.github/cases/*.yml` ⇒ `{仓库相对路径: 文本}`（缺目录 ⇒ fail-closed，**不是**静默空集）。"""
    if not CASES_DIR.is_dir():
        raise AssertionError(f"用例库目录不存在：{CASES_DIR} —— 本判据 fail-closed（空集比空集是恒等，那种绿是假绿）")
    out = {}
    for path in sorted(CASES_DIR.glob("*.yml")):
        out[path.relative_to(REPO_ROOT).as_posix()] = path.read_text(encoding="utf-8")
    if not out:
        raise AssertionError(f"{CASES_DIR} 下没有任何 *.yml —— 语料面为空，本判据无从判定（fail-closed）")
    return out


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INDEX_CACHE: dict = {}


def repo_index():
    """`(real_names, test_identifiers)` —— 真名面 + 测试文件里出现过的**标识符**全量（进程内缓存）。

    - `real_names`（判定用）：Java `void <name>(` 声明 ∪ Python `def test_*(` 声明 ∪ 前端测试文件名；
    - `test_identifiers`（定域用）：后台测试树里**出现过的**标识符（声明、调用、字符串字面量都算）。

    第二条为什么必要：`「」` 在语料里同时用于**测试名**与少量**生产符号值**（`「producing」` /
    `「shipments」` 是 ON CONFLICT 判定式与菜单路径里的值）⇒ 只看形状会假红。用「这个记号在测试
    文件里出现过吗」定域即可：真名（含拼错名）通常至少在某处出现过，而纯散文 / 生产值不会。
    """
    if "index" not in _INDEX_CACHE:
        real: set[str] = set()
        seen: set[str] = set()
        for path in REPO_ROOT.glob(JAVA_TEST_GLOB):
            code = SP.java_code(path.read_text(encoding="utf-8", errors="ignore"))
            real.update(JAVA_METHOD.findall(code))
            seen.update(_IDENTIFIER.findall(code))
            for _pos, lit in SP.java_literals(path.read_text(encoding="utf-8", errors="ignore")):
                seen.update(_IDENTIFIER.findall(lit))
        for pattern in PY_TEST_GLOBS:
            for path in REPO_ROOT.glob(pattern):
                text = path.read_text(encoding="utf-8", errors="ignore")
                real.update(PY_TEST_DEF.findall(text))
                seen.update(_IDENTIFIER.findall(text))
        for pattern in FRONTEND_TEST_GLOBS:
            for path in REPO_ROOT.glob(pattern):
                real.add(path.name)
                real.add(path.stem)
        _INDEX_CACHE["index"] = (real, seen)
    return _INDEX_CACHE["index"]


def load_ledger():
    """豁免台账（缺文件 ⇒ fail-closed）。"""
    if not LEDGER_PATH.exists():
        raise AssertionError(f"豁免台账不存在：{LEDGER_PATH} —— 本判据 fail-closed（缺台账 = 豁免无人管）")
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def case_ids_of(rel: str, token: str):
    """台账条目的**对账辅助**：记号出现在哪些用例 id 里（报错/复核用）。"""
    doc = yaml.safe_load((REPO_ROOT / rel).read_text(encoding="utf-8")) or {}
    out = []
    for case in doc.get("cases") or []:
        blob = json.dumps(case, ensure_ascii=False)
        if "「" + token + "」" in blob:
            out.append(str(case.get("id")))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据
# ══════════════════════════════════════════════════════════════════════════════

def test_referenced_test_names_exist_or_are_registered():
    """判据 1 + 3：`「」` 点名的测试方法名必须真实存在，否则**必须**在台账里登记。"""
    cases = load_cases()
    real, identifiers = repo_index()
    ledger = load_ledger()
    exempted = {(e["file"], e["name"]) for e in ledger["exemptions"]}

    findings = scan(cases, real, identifiers)
    assert findings, (
        "引用面为空 —— **判据被改坏了**（`.github/cases/*.yml` 里一个 `「」` 测试名记号都没扫到）："
        "这不是「全绿」，是「没跑」。请先核 QUOTED / NAME_SHAPE / in_scope 三条谓词。"
    )

    orphan = [f for f in findings if (f[0], f[2]) not in exempted]
    lines = [finding_message(f, real) for f in orphan]
    assert not orphan, (
        f"用例库点名了 {len(orphan)} 处**仓里不存在**的测试方法名（issue #6147 的类级守卫；"
        f"判据 = tests/unit_ci_workflows/test_case_prose_test_names.py）\n"
        + "\n".join(lines)
    )


def test_exemption_ledger_only_shrinks_and_entries_stay_alive():
    """判据 3：台账**只许缩短**（条数 ≤ 冻结上限）+ 每条必须在**当前**语料里仍出现。"""
    ledger = load_ledger()
    exemptions = ledger["exemptions"]
    assert len(exemptions) <= EXEMPTION_CAP_FROZEN, (
        f"豁免台账条数 {len(exemptions)} > 冻结上限 {EXEMPTION_CAP_FROZEN}："
        "本台账**只许缩短**（铁律 8）—— 新增豁免必须先在 PR body 说明并改冻结上限，不许静默加条目。"
    )

    cases = load_cases()
    real, identifiers = repo_index()
    live = {(f[0], f[2]) for f in scan(cases, real, identifiers)}
    stale = [f"{e['file']}「{e['name']}」" for e in exemptions if (e["file"], e["name"]) not in live]
    assert not stale, (
        f"台账里有 {len(stale)} 条**已不再出现**（名字已改真 / 引用已删）的豁免 ⇒ 陈旧条目必须当场销账：\n  "
        + "\n  ".join(stale)
    )

    required = {"kind", "file", "name", "cases", "case", "issue", "owner", "reason", "counterpart", "criterion"}
    for e in exemptions:
        missing = required - set(e)
        assert not missing, f"台账条目缺字段 {sorted(missing)}：{e}"
        assert e["kind"] in EXEMPTION_KINDS, (
            f"台账条目 kind={e['kind']!r} 不在 {EXEMPTION_KINDS} 里 —— "
            "`tests` = 找不到现名的测试名引用；`value_shaped` = 值字面量的定域残余。"
        )
        actual = case_ids_of(e["file"], e["name"])
        assert actual == list(e["cases"]), (
            f"台账条目 {e['file']}「{e['name']}」的 cases 字段 = {e['cases']}，"
            f"而现取该名字出现在 {actual}（台账与用例库脱节 ⇒ 当场红）"
        )


def test_real_name_surface_is_non_empty():
    """判据 6：真名面 / 语料面**必须非空**（fail-closed；否则判据退化成恒绿）。"""
    real, identifiers = repo_index()
    assert len(real) > 1000, f"真名面只解析出 {len(real)} 个名字 —— 语料面可能已消失（不许静默绿）"
    assert len(identifiers) > 10000, f"测试标识符索引只解析出 {len(identifiers)} 个 —— 同上"
    assert JAVA_METHOD.findall("void x() {}") and PY_TEST_DEF.findall("    def test_x():\n")
    assert load_cases(), "语料面为空"


def test_scan_discriminates_injected_ghost():
    """判据 5：同一份判定本体喂内存夹具 —— 幽灵名红、真名绿、生产符号值 / 散文不红。"""
    real = {"createWithoutPositionsStillCreatesTheSinglePriceRow", "updateSetsScope"}
    identifiers = real | {"producing", "shipments", "createWithoutPositionsKeepsLegacyBehaviour"}

    ghost = {"x.yml": "  - \"证据：FooTest「createWithoutPositionsKeepsLegacyBehaviour」\""}
    found = scan(ghost, real, identifiers)
    assert [(f[0], f[2]) for f in found] == [("x.yml", "createWithoutPositionsKeepsLegacyBehaviour")]
    msg = finding_message(found[0], real)
    assert "x.yml:1" in msg and "createWithoutPositionsKeepsLegacyBehaviour" in msg and "候选" in msg, msg

    real_ref = {"x.yml": "  - \"证据：FooTest「createWithoutPositionsStillCreatesTheSinglePriceRow」\""}
    assert scan(real_ref, real, identifiers) == [], "真名被误判成幽灵 ⇒ 判据无判别力"

    scope_guard = {"x.yml": "  - \"FooTest「updateSetsScope」+ 序列「producing」+ 路径「shipments」\""}
    assert [f[2] for f in scan(scope_guard, real, identifiers)] == ["producing", "shipments"], (
        "定域只挡「测试文件里从没出现过的散文词」；`producing` / `shipments` 这类**值字面量**"
        "落在面内是**有意**的 ⇒ 真语料里由台账 `value_shaped` 条目登记（见真语料自证那条）"
    )
    stories = {"x.yml": "  - \"**为什么**：这里只是散文，`shipmentReports` 也只是个普通词\""}
    assert scan(stories, real, identifiers) == [], (
        "测试文件里没出现过的散文词不该被读成测试名引用（定域谓词失效 ⇒ 会逼出改措辞消红的纸面修复）"
    )

    snake_case = {"x.yml": "  - \"pytest：tests/unit_ci_workflows/test_ghost_name.py「test_v77_is_never_run」\""}
    assert [(f[2]) for f in scan(snake_case, real, identifiers)] == ["test_v77_is_never_run"], (
        "`test_` 前缀的 python 测试名**不靠**测试标识符索引定域 —— 拼错名必须照红"
    )

    comment_only = {"x.yml": "# 注释里提一句 createWithoutPositionsKeepsLegacyBehaviour 不算引用\n"}
    assert scan(comment_only, real, identifiers) == [], "注释里的名字被读成引用（判据把「原文」当「引用」）"
    # 注释里出现**不存在的**测试名同样不报（语料 = YAML 解析出的字符串值，不是原文）
    comment_only_ghost = {"x.yml": "# 「notARealTestNameAtAll」\n"}
    assert scan(comment_only_ghost, real, identifiers) == [], "注释里的名字被读成引用"


def test_scan_flags_an_injection_into_the_real_corpus():
    """判据 6（**真语料**上的双向自证）：内存变异 ⇒ 具名红；不注入 ⇒ 只剩台账那几条；注入必须先自证生效。"""
    rel = ".github/cases/processing-order.yml"
    real, identifiers = repo_index()
    text = load_cases()[rel]
    ledger = load_ledger()
    exempted = {e["name"] for e in ledger["exemptions"] if e["file"] == rel}
    baseline = scan({rel: text}, real, identifiers)
    assert {f[2] for f in baseline} == exempted, (
        f"真语料上的命中必须**恰好等于**台账豁免面；现取 {sorted(f[2] for f in baseline)} "
        f"vs 台账 {sorted(exempted)}"
    )

    mutated = text.replace(
        "createWithoutPositionsStillCreatesTheSinglePriceRow",
        "createWithoutPositionsKeepsLegacyBehaviour", 1)
    assert mutated != text, "注入没生效（自证：变异必须先真的改到文本）"
    injected = [f for f in scan({rel: mutated}, real, identifiers) if f[2] not in exempted]
    assert [f[2] for f in injected] == ["createWithoutPositionsKeepsLegacyBehaviour"], injected
    assert rel in finding_message(injected[0], real)

    # 反向对照：**删掉**一条引用（而不是改名）⇒ 台账那条当场变陈旧（判据 3 会红）
    dropped = text.replace("「findRoutingScopeFollowsTheLibraryRow」", "", 1)
    assert dropped != text
    assert "findRoutingScopeFollowsTheLibraryRow" not in {f[2] for f in scan({rel: dropped}, real, identifiers)}
