# case_ids: OR-014, OR-021, OR-025, AS-009, CH-013, CH-014
"""行为映射门禁「守卫族 → 用例」**类级元守卫**（issue #3786）—— L0 静态锁，秒级零 LLM。

## 病根（实测读数，不是推断）

`tests/agent_eval/behavior_mapping.py` 决定「改哪些文件 → 跑哪些用例」。PR #3785 改的是
`backend/ai-agent-service/app/graph/skills/base_skill.py` 里**能力自我否定族**的守卫
（否定形态覆盖 + 回锁目标改为注册表事实），要恢复的行为面就是 **OR-014**
（`order_create` 真实可达时会话自称「落单不归我管 / 不具备提交能力」⇒ `no_success(order_create)`）；
而同一 diff 喂给映射纯函数推出的是：

    persona=mibao  档位=full  用例=CH-013,CH-014,CH-015,DF-011,DF-012  门禁=blocking
    命中规则：…app/graph/skills/base_skill\\.py → CH-013,CH-014,CH-015
              …|guard\\.py|defense|injection|inject（含 base_skill） → DF-011,DF-012

⇒ **OR-014 不在集里**：改了该守卫族的**唯一承载用例**的修复面，却不会跑到那条用例
= §13.3（修复必须重放）在**映射层**的漏洞，与 #3725 / #3837 同族（「改了 X，门禁一条 X 的用例都没跑」）。

## 为什么"补一条映射"不算修（本文件存在的理由）

`base_skill.py` 是**多个守卫族共用的载体**（转人工族 / 防御族 / 能力自我否定族 / 能力可达性族）。
#3786 的病根不是"漏写了 OR-014 这一处"，而是**没有任何判据把「守卫族」与「它该跑哪些用例」
这两份声明对照起来** —— 于是下一次换一个族，同一个病会原样复发（#3571 族已复发 6 次）。
本文件把这条对照变成机械判据，四段（**凡条数一律现取，不写死**）：

| # | 判据 | 取法（结构化，不读散文） | 回归时会怎么红 |
|---|---|---|---|
| 1 | **家族登记处现取**：以 `base_skill.py` 为被测对象（对它 `ast.parse`）、且在一个集合/元组/列表字面量里点名 **≥2 个**该文件模块级符号的测试文件 = 守卫族登记文件 | 普查 `tests/**` + `backend/ai-agent-service/tests/**` 的 `*.py` | 新增/退场一个登记文件 ⇒ 与 `GUARD_FAMILY_REGISTRIES` 不等 ⇒ 红（**未登记即红**，两个方向都判） |
| 2 | **家族 → 用例 未映射即红**：每个家族在头部 `# case_ids:` 声明的用例里，**至少一条**必须被「改载体」的映射选中，且来源 = `rules` | `.github/growth_gate.py:extract_case_ids()`（**复用**用例 ID 声明的唯一解析口径，不另写正则）+ `map_changed_files_with_source` | 删掉 OR-014 那条映射 ⇒ 能力自我否定族零射程 ⇒ 红（#3786 红证 ①，实跑过） |
| 3 | **反向查空**：映射表 / 兜底网里任一条目解析不到**真实存在**的用例 ID ⇒ 红 | 用例单一源 `.github/cases/**`（`render_cases.load_case_dicts`） | 把某个 ID 写成 `OR-999` ⇒ 红（#3786 红证 ②，实跑过） |
| 4 | **判据自身不空转**：普查结果非空、家族用例 ID 集合非空且真实存在 | 同上 | 普查形态失效（一条都发现不了）⇒ 红，而不是"绿着但没跑" |

## 不重复实现的（A6「别人已落同族守卫就撤下自己的」）

- **锚点是否存在**：各登记文件自己就 fail-closed（例：`test_denial_guard_or014_invariants.py`
  的 `_VOCAB_TUPLES` 取不到即 `AssertionError`）⇒ 本文件只用锚点名做**形态识别**，不再实现一遍。
- **用例是否跑得动**（persona / `skip_reason`）：`test_behavior_mapping_tool_coverage.py` 与
  `test_behavior_gate_reachability.py` 已承担；本文件判据 3 只回答「ID 是否存在」。

## 已知边界（如实登记，不假装覆盖）

- 判据 1 只认两种**结构化形态**：① 文件里出现对载体的 `ast.parse`（源片段含 `BASE_SKILL` /
  `base_skill`）；② 集合字面量里 ≥2 个字符串常量**逐字等于**载体的模块级符号名。
  ⇒ 只用 `read_text` 做文本匹配、或把锚点名拼进 f-string / 变量的登记文件**不在面内**
  （假绿方向，不会误伤别人）；剪枝 = `__pycache__` / `.venv` / `venv` / `site-packages` /
  `node_modules` / `.next` / `dist` / `build`。
- 判据 2 是「**每族 ≥1 条**」而非「声明的全集都进映射」—— **有意为之**：把登记文件声明的
  全部 ID 灌进规则桶，会让每个改 `base_skill.py` 的 PR 吃一整套真实 LLM 用例，与 #3551
  「规则过宽 ⇒ 假阻塞红」直接冲突。族与载体的**逐条**对应仍由各登记文件自己的断言 + 
  `backend/ai-agent-service/tests/test_behavior_mapping.py::TestBaseSkillRules` 的实例断言承担。
- **没有机械锁**会拦住"在载体里新写一个守卫族却不建登记文件"——那时判据 1 的普查看不到它
  （它不满足形态 ①②）。这条与 `test_guard_scope_declaration.py` 的残余同族（照实登记）。
"""
import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

from behavior_mapping import (  # noqa: E402
    DEFAULT_BEHAVIOR_CASES,
    MAPPING_RULES,
    map_changed_files_with_source,
)
from growth_gate import extract_case_ids  # noqa: E402
from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"

#: 守卫族的**载体**（多个守卫族共用；家族成员定义在这里）。判据 3 的「改载体 ⇒ 该跑哪些用例」
#: 就锚在它上面。
CARRIER_REL = "backend/ai-agent-service/app/graph/skills/base_skill.py"
CARRIER = REPO_ROOT / CARRIER_REL

#: 普查面（Python 判据面）与剪枝。
SCAN_ROOTS = ("tests", "backend/ai-agent-service/tests")
SCAN_SKIP_DIRS = ("__pycache__", ".venv", "venv", "site-packages", "node_modules",
                  ".next", "dist", "build", "coverage")

#: 「是一个守卫族登记处」的**形态阈值**：一个集合字面量里点名 ≥2 个载体模块级符号。
#: 2 而非 1 = 排除"顺手提到一个符号名"的偶然命中（如某个测试文件只按名取一个函数）。
#: ⚠️ 它是**形态定义**，不是"家族条数"——家族条数与每族锚点数一律由普查/载体现取。
MIN_ANCHORS_PER_FAMILY = 2

#: 已登记的「守卫族登记文件」→ (载体, 依据)。依据必须带 issue 号（`TestGuardFamilyRegistry` 强制）。
#: ⚠️ 本表**不是用例清单**：用例 ID 现取自各登记文件头部的 `# case_ids:`（唯一声明处），
#: 不在这里手抄 —— 手抄就是又一处会腐烂的真相源。
GUARD_FAMILY_REGISTRIES = {
    "tests/unit_ci_workflows/test_denial_guard_or014_invariants.py": (
        CARRIER_REL,
        "#3786 的病根族：**能力自我否定族**（#3389/#3477/#3443/#3476/#3571 第 6 次复发的 L0 不变式）。"
        "该文件点名载体的判据词表与判据函数，头部声明 `# case_ids: OR-014` —— OR-014 是该族在本载体上"
        "**唯一**的行为承载用例，而它此前不在「改 base_skill.py」的映射集里（修 A 却验 B）。",
    ),
    "tests/unit_ci_workflows/test_capability_guard_invariants.py": (
        CARRIER_REL,
        "#3571：**能力可达性 / 转人工守卫族**。`GUARD_PREDICATES` 逐条点名载体的判据函数，头部声明"
        "OR-021/OR-025/AS-009/CH-013/CH-014 —— 其中 CH-013/CH-014 是本载体既有的映射面（并集语义）。",
    ),
}


# ══════════════════════════════════════════════════════════════════════════════
# 纯函数（注入式红证用 —— 与被测真值解耦）
# ══════════════════════════════════════════════════════════════════════════════
def _module_symbols(src: str) -> set:
    """源码的**模块级符号**（函数 / 类 / 赋值目标）—— 判据 1 的现取真值。"""
    tree = ast.parse(src)
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def _anchor_names(src: str, symbols: set) -> set:
    """源码的集合/元组/列表字面量里**逐字等于载体模块级符号名**的字符串。"""
    tree = ast.parse(src)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            for elt in node.elts:
                if (isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        and elt.value in symbols):
                    found.add(elt.value)
    return found


def _parses_carrier(src: str) -> bool:
    """该源码是否**对载体做 AST 解析**（= 以它为被测对象，而不是只在散文里提到它）。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "parse"):
            seg = ast.get_source_segment(src, node) or ""
            if "BASE_SKILL" in seg or "base_skill" in seg:
                return True
    return False


def discover_guard_family_files(symbols: set, roots=SCAN_ROOTS, repo_root=REPO_ROOT) -> list:
    """普查「守卫族登记文件」→ 排序后的仓根相对路径（**现取**，不写死清单）。

    形态判据（两条都要满足）：① 对载体 `ast.parse`；② 集合字面量里 ≥`MIN_ANCHORS_PER_FAMILY`
    个字符串常量逐字等于载体模块级符号名。普查根缺失 ⇒ **报错**（fail-closed：不允许"扫不到就通过"）。
    """
    out = []
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            raise AssertionError(f"普查根不存在：{base}（fail-closed，不静默跳过）")
        for path in sorted(base.rglob("*.py")):
            if any(part in SCAN_SKIP_DIRS for part in path.parts):
                continue
            try:
                src = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if "base_skill" not in src:      # 廉价预筛（判据 ② 本就要求逐字命中符号名）
                continue
            if not _parses_carrier(src):
                continue
            if len(_anchor_names(src, symbols)) >= MIN_ANCHORS_PER_FAMILY:
                out.append(path.relative_to(repo_root).as_posix())
    return sorted(out)


def unregistered_family_files(discovered, registered) -> list:
    """普查发现但**未登记**的登记文件（⇒ 未登记即红）。"""
    return sorted(set(discovered) - set(registered))


def stale_family_registrations(discovered, registered) -> list:
    """已登记但**不再符合形态**的条目（⇒ 登记腐烂即红，反向同判）。"""
    return sorted(set(registered) - set(discovered))


def families_without_mapped_case(registries, mapping_fn, declared_ids_fn) -> list:
    """家族 → 用例 的零射程清单 → `[(家族文件, 声明的用例, 映射来源, 实得用例), ...]`。

    判据 = *"该家族声明的用例里，至少一条要被「改载体」的映射选中，且来源必须是 `rules`"*
    —— 两条都可被注入样本触发：① 一条都没选中；② 选中了但来自兜底网（无因果、失败只报告）。
    """
    gaps = []
    for rel in sorted(registries):
        declared = list(declared_ids_fn(rel))
        selected, source = mapping_fn([CARRIER_REL])
        if not set(declared) & set(selected) or source != "rules":
            gaps.append((rel, declared, source, list(selected)))
    return gaps


def reverse_lookup_gaps(rules, default_cases, known_ids) -> list:
    """映射表 + 兜底网里**解析不到真实用例**的 ID（⇒ 反向查空，死锚点即红）。"""
    referenced = {cid for _pattern, cids in rules for cid in cids} | set(default_cases)
    return sorted(referenced - set(known_ids))


# ══════════════════════════════════════════════════════════════════════════════
# 仓库真值装载
# ══════════════════════════════════════════════════════════════════════════════
def _carrier_symbols() -> set:
    if not CARRIER.is_file():
        raise AssertionError(f"守卫族载体不存在：{CARRIER_REL}（fail-closed）")
    return _module_symbols(CARRIER.read_text(encoding="utf-8"))


def _known_case_ids() -> set:
    return {str(c.get("id") or "") for c in load_case_dicts(str(CASES_DIR))}


def _declared_family_case_ids(rel: str) -> list:
    """家族登记文件头部声明的用例 ID（复用 `growth_gate.extract_case_ids` —— 唯一解析口径）。"""
    return list(extract_case_ids(str(REPO_ROOT / rel)))


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1 + 4：家族登记处现取（未登记即红 / 登记腐烂即红 / 不空转）
# ══════════════════════════════════════════════════════════════════════════════
class TestGuardFamilyRegistry:
    """「谁是守卫族登记处」必须与**普查事实**逐字相等（两个方向都判）。"""

    @pytest.mark.parametrize("rel", sorted(GUARD_FAMILY_REGISTRIES))
    def test_registered_file_exists(self, rel):
        """代表性路径必须真的存在（防退化成凭空文件名 —— 那样本守卫恒绿）。"""
        assert (REPO_ROOT / rel).is_file(), (
            f"已登记的守卫族登记文件不存在：{rel} —— 请更新 GUARD_FAMILY_REGISTRIES"
        )

    @pytest.mark.parametrize("rel", sorted(GUARD_FAMILY_REGISTRIES))
    def test_registered_entry_cites_evidence(self, rel):
        """每条登记都要带可追溯依据（issue 号），防退化成"魔数清单"。"""
        carrier, why = GUARD_FAMILY_REGISTRIES[rel]
        assert carrier == CARRIER_REL, f"{rel} 的载体声明为 {carrier}，本判据只支持 {CARRIER_REL}"
        import re
        assert re.search(r"#\d+", why), f"{rel} 的依据没有可追溯引用（issue 号）：{why!r}"

    def test_discovered_family_set_equals_registry(self):
        """普查 == 登记（**条数现取**）：未登记即红，登记了却不再符合形态也红。"""
        symbols = _carrier_symbols()
        discovered = discover_guard_family_files(symbols)
        unregistered = unregistered_family_files(discovered, GUARD_FAMILY_REGISTRIES)
        stale = stale_family_registrations(discovered, GUARD_FAMILY_REGISTRIES)
        assert unregistered == [], (
            "以下文件是**守卫族登记处**（以 base_skill.py 为被测对象、点名 ≥"
            f"{MIN_ANCHORS_PER_FAMILY} 个该文件模块级符号），但没登记进 GUARD_FAMILY_REGISTRIES "
            f"⇒ 该族的用例射程无人对照（#3786 形态）：{unregistered}\n"
            "修法：把它登记进 GUARD_FAMILY_REGISTRIES，并保证它声明的用例里**至少一条**"
            "出现在「改 base_skill.py」的映射集里（MAPPING_RULES）。"
        )
        assert stale == [], (
            f"以下登记条目已不再符合「守卫族登记处」形态（文件删了/改名了/不再点名载体符号）：{stale}\n"
            "修法：从 GUARD_FAMILY_REGISTRIES 删除，或在文件里恢复结构化的锚点清单。"
        )

    def test_discovery_is_not_vacuous(self):
        """判据自身不空转：普查必须真的发现家族，且发现集里含本单点名的那个族。"""
        discovered = discover_guard_family_files(_carrier_symbols())
        assert discovered, (
            "守卫族普查**一条都没发现** —— 形态判据（ast.parse 载体 + ≥"
            f"{MIN_ANCHORS_PER_FAMILY} 个符号名）已失效，本文件会变成恒绿的空断言"
        )
        denial = "tests/unit_ci_workflows/test_denial_guard_or014_invariants.py"
        assert denial in discovered, (
            f"普查未发现能力自我否定族的登记文件 {denial}（实得 {discovered}）—— "
            "该族的用例射程又回到无人对照的状态（#3786）"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 2：家族 → 用例**未映射即红**（本文件的核心产出）
# ══════════════════════════════════════════════════════════════════════════════
class TestGuardFamilyIsMappedToCases:
    """每个守卫族在「改载体」的映射里必须**至少有一条**自己的用例（#3786 的类级判据）。"""

    def test_every_family_has_at_least_one_mapped_case(self):
        gaps = families_without_mapped_case(
            GUARD_FAMILY_REGISTRIES, map_changed_files_with_source,
            _declared_family_case_ids)
        assert gaps == [], (
            "以下守卫族在「改 `" + CARRIER_REL + "`」的映射里**零射程**"
            "（= 改了该族的守卫，它自己的用例一条都不会跑；#3786 的病根形态）：\n"
            + "\n".join(f"  · {rel}：声明 {declared} ｜ 映射来源={source} ｜ 实得 {selected}"
                        for rel, declared, source, selected in gaps)
            + "\n修法：在 `tests/agent_eval/behavior_mapping.py` 的 `MAPPING_RULES` 里给该族的载体"
              "补一条规则（来源必须是 `rules` —— 兜底网与本改动无因果），见 issue #3786。"
        )

    @pytest.mark.parametrize("rel", sorted(GUARD_FAMILY_REGISTRIES))
    def test_family_declares_case_ids(self, rel):
        """家族必须声明用例 ID（空声明 = 空断言，判据 2 会退化成恒真）。"""
        declared = _declared_family_case_ids(rel)
        assert declared, (
            f"{rel} 头部没有 `# case_ids:` 声明（前 50 行内）—— 家族↔用例的对照失去输入"
        )

    @pytest.mark.parametrize("rel", sorted(GUARD_FAMILY_REGISTRIES))
    def test_family_declared_cases_exist(self, rel):
        """家族声明的用例 ID 必须真实存在（否则判据 2 永远无法满足 = 假红/死判据）。"""
        known = _known_case_ids()
        missing = [cid for cid in _declared_family_case_ids(rel) if cid not in known]
        assert missing == [], (
            f"{rel} 声明的用例不在 `.github/cases/` 单一源里：{missing}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：映射表**反向查空**（任一条目解析不到真实用例 ID ⇒ 红）
# ══════════════════════════════════════════════════════════════════════════════
class TestMappingTableHasNoDeadCaseIds:
    """映射表指向不存在的用例 = 死锚点（看着有射程、实际选不中任何东西）。"""

    def test_no_dead_case_id_in_mapping_rules_or_default_net(self):
        known = _known_case_ids()
        dead = reverse_lookup_gaps(MAPPING_RULES, DEFAULT_BEHAVIOR_CASES, known)
        assert dead == [], (
            f"`MAPPING_RULES` / `DEFAULT_BEHAVIOR_CASES` 里有解析不到真实用例的 ID：{dead}\n"
            f"（用例单一源 = `.github/cases/**`，本次装载 {len(known)} 条）\n"
            "修法：改成真实存在的用例 ID，或删掉该条死锚点；复核命令：\n"
            "  python3 -c \"import sys;sys.path[:0]=['.github','tests/agent_eval'];"
            "import behavior_mapping as b;print(b.MAPPING_RULES)\""
        )

    def test_known_case_set_is_not_vacuous(self):
        """反向查空必须真的在查东西：家族点名的用例在单一源里查得到。"""
        known = _known_case_ids()
        assert "OR-014" in known, (
            "用例单一源里查不到 OR-014 —— 要么用例被删/改名，要么装载失败；"
            "此时上一条判据会变成恒绿的空断言"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 注入式红证（`migao-acceptance`：不会红的断言 = 空断言）
# ══════════════════════════════════════════════════════════════════════════════
class TestCheckerActuallyFires:
    """证明上面三段判据**都会红**（注入样本与被测真值解耦，永远有效）。"""

    def test_fires_when_a_family_has_zero_mapped_cases(self):
        """判据 2 的核心形态：注入**修前真实行为**（base_skill 映射里没有 OR-014）。"""
        prefix_behavior = lambda _paths: (  # noqa: E731
            ["CH-013", "CH-014", "CH-015", "DF-011", "DF-012"], "rules")
        gaps = families_without_mapped_case(
            GUARD_FAMILY_REGISTRIES, prefix_behavior, _declared_family_case_ids)
        assert [rel for rel, _d, _s, _sel in gaps] == [
            "tests/unit_ci_workflows/test_denial_guard_or014_invariants.py"], (
            f"修前行为（OR-014 不在映射里）应只让**能力自我否定族**报缺口，实测 {gaps}"
        )
        assert gaps[0][1] == ["OR-014"], f"缺口家族的声明用例集不对：{gaps[0][1]}"

    def test_fires_when_the_family_case_lands_in_the_default_net(self):
        """判据 2 的第二形态：ID 恰好在兜底网里（集合成员对上了）但**来源不是 rules**。

        这是最容易骗过守卫的形态：只看"ID 在不在结果里"会判绿，而因果性（强信号 vs 只报告）已经丢了。
        """
        net_behavior = lambda _paths: (["OR-014"], "default_net")  # noqa: E731
        gaps = families_without_mapped_case(
            {"tests/unit_ci_workflows/test_denial_guard_or014_invariants.py": (CARRIER_REL, "#3786")},
            net_behavior, _declared_family_case_ids)
        assert [rel for rel, _d, _s, _sel in gaps] == [
            "tests/unit_ci_workflows/test_denial_guard_or014_invariants.py"], (
            f"来源非 rules（兜底网）却未报缺口：{gaps}"
        )
        assert gaps[0][2] == "default_net"

    def test_fires_on_a_dead_case_id(self):
        """判据 3 的核心形态：映射到**不存在**的用例 ID ⇒ 必红。"""
        known = {"OR-014", "CH-013"}
        rules = [(r"x", ["OR-014", "OR-999"])]
        assert reverse_lookup_gaps(rules, ["CH-013"], known) == ["OR-999"], (
            "死锚点（OR-999）未被反向查空报出"
        )
        # 反向：全是真 ID 时必须是干净的（否则上一条判据就是恒红噪声）
        assert reverse_lookup_gaps(rules, ["CH-013"], known | {"OR-999"}) == []

    def test_fires_on_an_unregistered_family_file(self):
        """判据 1 的核心形态：普查发现而**未登记** ⇒ 必红（两个方向都判）。"""
        discovered = ["tests/unit_ci_workflows/test_a_guard.py",
                      "tests/unit_ci_workflows/test_b_guard.py"]
        registered = {"tests/unit_ci_workflows/test_a_guard.py": (CARRIER_REL, "#3786")}
        assert unregistered_family_files(discovered, registered) == [
            "tests/unit_ci_workflows/test_b_guard.py"], "未登记的家族文件未被报出"
        assert stale_family_registrations(
            ["tests/unit_ci_workflows/test_a_guard.py"],
            registered | {"tests/unit_ci_workflows/test_c_gone.py": (CARRIER_REL, "#3786")},
        ) == ["tests/unit_ci_workflows/test_c_gone.py"], "已腐烂的登记条目未被报出"