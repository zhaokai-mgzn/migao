# case_ids: RG-001
"""`.github/render_cases.py` 域映射**覆盖度**判据（来源：issue #5083 的一条）。

## 病灶（形态 = 两处**静默**缺省回落）

`render_cases.py` 消费 `cases/*.yml` 的**域名**（= 文件名去后缀，`load_case_dicts` 写入
`_domain`），但两张域表只覆盖了 12 个域，其余一律走 `.get(domain, <缺省>)`：

  · `DOMAIN_TITLES.get(domain, domain)` —— 缺项 ⇒
    `docs/testing/mibao-verification-cases.md` 的章节标题直接显示**英文域名**
    （`## ui（51 case）`）。读者无法区分「这是缺映射」与「有意用英文」。
  · `SKILL_MAP.get(domain, "GENERAL")` —— 缺项 ⇒ 生成物落 `Skill.GENERAL`，
    与「**有意**映射到 GENERAL」在生成物里**逐字相同**、静态不可区分。

⇒ 判据不是「不许落 GENERAL」（那会把 12 个**正确**映射一次全判红 —— 它们是后端/单测契约域，
本就不属任何 LLM skill），而是「**不许静默**」：出现在 `.github/cases/*.yml` 的每一个域，
都必须在两张表里**显式列名**，让「新增域」这件事被迫做一个决定。

## `skill` 不是计分面（改本表**不改变任何用例的判定结果**）

`tests/agent_eval/local_runner.py` 在自建 `EvalCase` 时**硬编码** `skill=Skill.GENERAL`
并注明「域信息由 `_domain` 携带，runner 不消费 skill」；全仓无任何地方读 `EvalCase.skill`
（判据 = 本文件 `TestSkillIsNotConsumed`，它扫 `tests/agent_eval/**` 与 `tests/unit_ci_workflows/**`
的 `.skill` 读取点）。⇒ 本判据只保证生成物**可读性与枚举合法性**。

## 判据本体是纯函数（注入式红证驱动**同一份**本体）

`missing_titles` / `missing_skill_map` / `invalid_skill_values` 不读盘：测试把数据注入进去。
故「喂一个缺项域 ⇒ 判红」证明的是**这些函数能红**，而不是另写了一份会红的检查。
"""
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
sys.path.insert(0, str(REPO_ROOT / ".github"))

import render_cases  # noqa: E402

#: `Skill` 枚举真值源 = 生成物（`.github/render_cases.py` 的 `SKILL_MAP` 值写进
#: `Skill.<值>`，拼错即 `AttributeError`）。`conftest.py` 已把 `tests/agent_eval` 挂上 path。
import eval_cases  # noqa: E402

SKILL_MEMBERS = frozenset(m.name for m in eval_cases.Skill)


# ══════════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数）
# ══════════════════════════════════════════════════════════════════════════════

def domains_with_cases(cases):
    """用例实际出现的域集合（`_domain` = 文件名，由 `load_case_dicts` 写入）。"""
    return {str(c.get("_domain") or "") for c in cases} - {""}


def missing_titles(domains, titles):
    """`DOMAIN_TITLES` 未显式覆盖的域 ⇒ md 章节标题会回落成**英文域名**。"""
    return sorted(d for d in domains if d not in titles)


def missing_skill_map(domains, skill_map):
    """`SKILL_MAP` 未显式覆盖的域 ⇒ 无声回落 `GENERAL`（与有意映射不可区分）。"""
    return sorted(d for d in domains if d not in skill_map)


def invalid_skill_values(skill_map, members):
    """`SKILL_MAP` 的值必须是 `Skill` 枚举的**真实成员名**（否则生成物 `Skill.X` 未定义）。"""
    return sorted({f"{d} -> {v!r}" for d, v in skill_map.items() if v not in members})


def md_section_header(domain, titles, case_count=1):
    """复刻 `to_md` 的章节标题形态（`DOMAIN_TITLES.get(domain, domain)`）。"""
    return f"## {titles.get(domain, domain)}（{case_count} case）"


#: **原始域名**标题的形态 = 全 ASCII 小写字母/数字/连字符（中文标题不可能匹配）。
#: 用它判「md 章节回落成域名」，**不依赖域表本身**（否则 D1 修好前 D4 恒绿 = 空判据）。
RAW_DOMAIN_TITLE_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def raw_domain_titles(heads):
    """章节标题里仍是**原始域名**的那些（= `DOMAIN_TITLES` 缺映射的回落形态）。"""
    return sorted(h for h in heads if RAW_DOMAIN_TITLE_RE.match(h))


def print_summary_calls(path):
    """AST 层面的 `print_summary()` 调用点 → `[(lineno, 是否在 `__main__` 块内)]`。

    走 AST 而不是正则：字符串字面量 / 注释 / prose 里的同名文本**都不算**调用
    —— 否则 `render_cases.py`（它把这一行当**字符串**渲染进生成物）与本判据自己的
    文档会被误判成调用方（实测踩到）。
    """
    import ast

    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    main_lines: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.If) and "__main__" in ast.dump(node.test):
            for sub in ast.walk(node):
                if hasattr(sub, "lineno"):
                    main_lines.add(sub.lineno)
    return [
        (node.lineno, node.lineno in main_lines)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print_summary"
    ]


# ══════════════════════════════════════════════════════════════════════════════
# D1 / D2 / D3 —— 真实仓库读数（现状必须全绿）
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def real_domains():
    cases = render_cases.load_case_dicts(str(CASES_DIR))
    assert cases, "用例库读不到任何用例 —— 判据的扫描面失效（0 命中会是假绿）"
    return domains_with_cases(cases)


def test_d1_domain_titles_cover_every_domain(real_domains):
    """D1：`DOMAIN_TITLES` 显式覆盖用例库出现的每一个域。"""
    missing = missing_titles(real_domains, render_cases.DOMAIN_TITLES)
    assert not missing, (
        f"`DOMAIN_TITLES` 缺 {len(missing)} 个域：{missing} ⇒ "
        f"`docs/testing/mibao-verification-cases.md` 的这些章节标题会显示**英文域名**"
        f"（`{md_section_header(missing[0], render_cases.DOMAIN_TITLES)}`）—— "
        f"补中文标题后重新渲染生成物（`python3 .github/render_cases.py`）"
    )


def test_d2_skill_map_covers_every_domain(real_domains):
    """D2：`SKILL_MAP` 显式覆盖每一个域（不许静默回落 `GENERAL`）。"""
    missing = missing_skill_map(real_domains, render_cases.SKILL_MAP)
    assert not missing, (
        f"`SKILL_MAP` 缺 {len(missing)} 个域：{missing} ⇒ 这些域的生成物会无声落 "
        f"`Skill.GENERAL`，与「有意映射 GENERAL」静态不可区分（#5083）。"
        f"落 GENERAL 是合法**结论**，但必须是**显式**写下的一行"
    )


def test_d3_skill_map_values_are_real_enum_members():
    """D3：`SKILL_MAP` 的值都是 `Skill` 枚举成员（拼错 ⇒ 生成物导入即炸）。"""
    bad = invalid_skill_values(render_cases.SKILL_MAP, SKILL_MEMBERS)
    assert not bad, (
        f"`SKILL_MAP` 有非法值：{bad} —— 合法值只有 {sorted(SKILL_MEMBERS)}；"
        f"非法值会渲染成 `Skill.<未定义名>` ⇒ `eval_cases.py` 导入失败"
    )


def test_d4_generated_md_sections_use_titles_not_raw_domains():
    """D4：生成物 md 的章节标题已经是中文标题（防「改了域表没重渲染」）。"""
    md = (REPO_ROOT / "docs" / "testing" / "mibao-verification-cases.md").read_text(encoding="utf-8")
    heads = set(re.findall(r"^## (.+?)（\d+ case）$", md, re.M))
    assert heads, "md 里找不到任何章节标题 —— 判据的扫描面失效（0 命中会是假绿）"
    raw = raw_domain_titles(heads)
    assert not raw, (
        f"md 章节标题仍是**英文域名**：{raw} ⇒ 生成物过期或域表未生效；"
        f"跑 `python3 .github/render_cases.py --cases .github/cases "
        f"--out-eval tests/agent_eval/eval_cases.py "
        f"--out-md docs/testing/mibao-verification-cases.md` 重渲染并提交"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 注入式红证 —— 每条判据都必须能**单独**变红
# ══════════════════════════════════════════════════════════════════════════════

class TestInjectionRedProofs:
    """喂变异输入 ⇒ 判据必须红。没有这一组，「全绿」可能只是判据恒真。"""

    def test_inject_unknown_domain_reds_d1(self):
        """注入一个不在 `DOMAIN_TITLES` 里的新域 ⇒ D1 红。"""
        domains = {"order", "brand-new-domain"}
        missing = missing_titles(domains, render_cases.DOMAIN_TITLES)
        assert missing == ["brand-new-domain"], (
            "D1 对未知域**不敏感** ⇒ 它是恒真判据（新增域会静默落到英文标题）"
        )

    def test_unknown_domain_header_really_shows_english(self):
        """端到端：真调 `to_md`，断言未知域的章节标题**确实**回落成英文域名。"""
        cases = [{"id": "ZZ-001", "title": "t", "tier": "normal", "_domain": "brand-new-domain",
                  "user_inputs": ["u"]}]
        md = render_cases.to_md(cases)
        assert "## brand-new-domain（1 case）" in md, (
            "`to_md` 对未知域的标题形态变了 —— D1 的红证前提（回落成英文域名）不成立，"
            "请按实际形态更新本红证:\n" + md
        )
        assert "## brand-new-domain（1 case）" not in render_cases.to_md(
            [{**cases[0], "_domain": "order"}]
        ), "已知域的标题应当用中文标题而非域名 —— 否则「回落」不再是可判定的信号"

    def test_inject_unknown_domain_reds_d2(self):
        """注入一个不在 `SKILL_MAP` 里的新域 ⇒ D2 红。"""
        missing = missing_skill_map({"order", "brand-new-domain"}, render_cases.SKILL_MAP)
        assert missing == ["brand-new-domain"], (
            "D2 对未知域**不敏感** ⇒ 它没有判别力（新增域仍会静默落 GENERAL）"
        )

    def test_inject_bad_skill_value_reds_d3(self):
        """注入一个拼错的 skill 值 ⇒ D3 红。"""
        bad = invalid_skill_values(
            {"order": "ORDER", "typo-domain": "ORDERS"}, SKILL_MEMBERS
        )
        assert bad == ["typo-domain -> 'ORDERS'"], (
            "D3 对非法枚举值**不敏感** ⇒ 生成物 `Skill.ORDERS` 会炸在运行期而不是静态侧"
        )

    def test_inject_stale_md_reds_d4(self):
        """注入一份标题仍是英文域名的 md ⇒ D4 的判定形态必须红。"""
        stale = "## ui（51 case）\n\n### UI-001. x\n"
        heads = set(re.findall(r"^## (.+?)（\d+ case）$", stale, re.M))
        assert raw_domain_titles(heads) == ["ui"], (
            "D4 对「标题仍是英文域名」的 md **不敏感** ⇒ 生成物过期时不会红"
        )
        # 负控：中文标题不得被误判成域名（否则 D4 会对修好后的生成物假红）
        assert raw_domain_titles({"前端 UI 域", "订单域", "覆盖统计（生成）"}) == []


# ══════════════════════════════════════════════════════════════════════════════
# 前提守卫：`skill` 真的不被消费（否则 D1~D4 的「无计分影响」结论就不成立）
# ══════════════════════════════════════════════════════════════════════════════

class TestSkillIsNotConsumed:
    """「改域表不影响任何用例判定」这个结论必须**可判红**，不许只是一句注释。

    判据 = 在 `tests/agent_eval/**` 与 `tests/unit_ci_workflows/**` 里搜 `EvalCase.skill`
    的**读取点**。`local_runner.py` 自建 `EvalCase` 时写 `skill=Skill.GENERAL`（写入，不是读取）
    —— 构造关键字参数不算消费，故按「`.skill` 属性读取」判。

    **实测现状（全仓唯一的消费点）**：`tests/agent_eval/eval_cases.py` 的 `print_summary()`
    里 `cs = [c for c in active if c.skill == skill]` —— 但该函数**只被本文件的
    `if __name__ == "__main__":` 调用**，全仓无其它调用方（判据 = 本文件
    `test_print_summary_has_no_callers`）⇒ `skill` 不进 runner / CI 的任何判定路径。
    ⇒ 域映射改动**无计分功能影响**；若将来出现新的读取点（如 runner 开始按 skill 过滤），
    本判据红。
    """

    SCAN_DIRS = ("tests/agent_eval", "tests/unit_ci_workflows")
    #: `.skill` 属性读取形态（`case.skill` / `c.skill` / `getattr(..., "skill")`）。
    READ_RE = re.compile(r"\.skill\b|getattr\([^)]*[\"']skill[\"']")
    #: 允许名单：只放**非消费**的读取（逐条给出理由）。
    ALLOWED: dict[str, str] = {
        "tests/agent_eval/eval_cases.py": (
            "生成物自带的 `print_summary()` 调试打印（仅 `__main__` 可达、无调用方）"
            "—— 见 `test_print_summary_has_no_callers`"
        ),
    }

    def test_no_skill_reads_outside_allowlist(self):
        me = Path(__file__).resolve()
        hits = []
        for d in self.SCAN_DIRS:
            root = REPO_ROOT / d
            assert root.is_dir(), f"扫描面 {d} 不存在 —— 扫不到东西的判据是假绿"
            for f in sorted(root.rglob("*.py")):
                if f.resolve() == me:
                    continue  # 判据自己的正则/docstring 里必然出现该形态，不是消费点
                rel = f.relative_to(REPO_ROOT).as_posix()
                if rel in self.ALLOWED:
                    continue
                for line in f.read_text(encoding="utf-8").splitlines():
                    code = line.split("#", 1)[0]
                    if self.READ_RE.search(code):
                        hits.append(f"{rel}: {code.strip()}")
        assert not hits, (
            "`EvalCase.skill` 出现了**新的读取点** ⇒ 本文件「改域表无计分影响」的结论不再成立，"
            "须重新评估域映射改动的运行期影响（并更新 `SKILL_MAP` 注释与本允许名单）：\n  "
            + "\n  ".join(hits)
        )

    def test_print_summary_has_no_callers(self):
        """允许名单的**死亡条件**：`print_summary()` 一旦有了调用方，豁免即失效（须重评）。

        判据走 **AST**（不是正则）：字符串字面量 / 注释 / prose 里的 `print_summary()` 都不算，
        只有真实 `Call` 节点才算。`eval_cases.py` 自己的
        `if __name__ == "__main__": print_summary()` 不算 —— 那正是本豁免所述的那一次调用。
        """
        offenders, missing = [], []
        for rel in ("tests/agent_eval/eval_cases.py", ".github/render_cases.py",
                    "tests/agent_eval/local_runner.py"):
            path = REPO_ROOT / rel
            if not path.is_file():
                missing.append(rel)
                continue
            for lineno, in_main in print_summary_calls(path):
                if rel == "tests/agent_eval/eval_cases.py" and in_main:
                    continue
                offenders.append(f"{rel}:{lineno}")
        assert not missing, (
            f"扫描对象不存在：{missing} —— 判据的扫描面失效（0 命中会是假绿）"
        )
        assert not offenders, (
            "`print_summary()` 在 `__main__` 块之外被调用了 ⇒ 它不再是「仅 `__main__` 可达的"
            "调试打印」，`skill` 开始进入真实路径 ⇒ 必须重评域映射改动的功能影响并撤本豁免：\n  "
            + "\n  ".join(offenders)
        )

    def test_caller_guard_can_actually_fail(self, tmp_path):
        """红证：把调用移出 `__main__` 块 ⇒ 上面那条判据的判定形态必须命中。"""
        src = tmp_path / "fake_eval_cases.py"
        src.write_text(
            "def print_summary():\n    return 1\n\n\nprint_summary()\n", encoding="utf-8"
        )
        # 非 `__main__` 下的调用 ⇒ 必须被抓到
        assert print_summary_calls(src) == [(5, False)], (
            "判定本体对自己写的注入样本不命中 ⇒ 上一条判据是恒真的空断言"
        )
        # 负控：`__main__` 块内的调用 + 字符串字面量里的同名文本都不得算（否则会假红）
        src.write_text(
            'def print_summary():\n    return 1\n\n\nif __name__ == "__main__":\n'
            '    s = "print_summary()"\n    print_summary()\n',
            encoding="utf-8",
        )
        assert print_summary_calls(src) == [(7, True)], (
            "字符串字面量里的 `print_summary()` 被当成调用了 ⇒ 判据会假红（必须走 AST 而非正则）"
        )

    def test_guard_can_actually_fail(self):
        """红证：注入一行 `.skill` 读取 ⇒ 上面那条判据的判定形态必须命中。"""
        injected = "    return c.skill == Skill.ORDER  # 注入"
        assert self.READ_RE.search(injected.split("#", 1)[0]), (
            "读取点正则对自己写的注入样本不命中 ⇒ 上一条判据是恒真的空断言"
        )
        # 负控：构造关键字参数（写入）**不得**被误判成读取，否则判据会把合规代码判红。
        assert not self.READ_RE.search("        skill=Skill.GENERAL,  # 域信息由 _domain 携带"), (
            "写入形态 `skill=...` 被误判为读取 ⇒ 判据会假红，必须收紧正则"
        )
