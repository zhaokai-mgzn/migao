# case_ids: MC-011
"""QA Growth Gate 豁免清单「活性」守卫 —— **死豁免一律不得留在表里**（2026-09-17 收紧）。

## 病根（用户方向性指令：门禁的豁免口子尽量收紧；**收紧 = 减少能免检的面**）

`.github/qa-exemptions.yml` 是 **required** 门禁（pr-check 的 QA Growth Gate）的数据驱动后门：
`growth_gate.classify_file` **先**判 `is_exempt`，命中即 `kind="exempt"` ⇒ 规则判定整段跳过
（既不算 pass 也不算 block，`blocker_count` 不增、PR 评论只显示「🔓 豁免」）。
它此前有 **53** 条，且**仓库内没有任何守卫**：条目可以是死的、理由可以过期、目标文件可以
早已不存在 —— 没有任何东西会因此变红（复算命令见下）。

两类**死条目**（本守卫判据）：

1. **僵尸**：pattern 匹配不到任何现存文件（文件/目录已删）。它唯一的现实作用是给
   「同名文件未来被重建」预埋一张**免检券**；
2. **冗余**：pattern 盖住的文件走 `tech-stack.yml` 规则本来就是 `pass` / `auto_pass`
   ⇒ 该条**零作用**。危害是**滞后爆发**：配套测试被删/改名之后，规则侧会转成 `block`，
   而豁免侧仍然放行 ⇒ 缺测门禁被**静默**撑回原样，且没有任何东西变红。

## 本守卫判什么（纯静态、零 LLM、不依赖 origin/main、**不写死易变数字**）

对 `qa-exemptions.yml` 的**每一条** pattern 复算「它是否在做实事」：用 `_glob_match` 求出它
盖住的现存文件集合 → 逐文件跑 `is_auto_pass` / `match_rule` / `find_existing_tests`
（**复用 growth_gate 的既有纯函数，不复制平行实现**）⇒ 只要存在一个文件的判定是 `block`
或 `unmatched`，该条就是**活的**；全是 `pass`/`auto_pass`，或零命中 ⇒ **死条目** ⇒ 红。

判据是**结构不变式**而非阈值：没有「最多 N 条豁免」这类数字（写死易变数字会随迭代腐烂，
见 `migao-dev-flow` §19.2③）。本文件也不断言豁免条数——它只断言「不许有死条目」。

## 红证（注入式，见 TestInjectionNonVacuity）

对**真实数据**双向注入：把一条**僵尸** pattern（指向不存在的路径）和一条**冗余** pattern
（指向一个已有配套测试的文件）各喂进同一个判据 ⇒ 必须**都被判死**；再把一条**活**条目
（如 `frontend/admin-web/src/components/ui/Badge.tsx`，其规则侧判定是 `block`）喂进去
⇒ 必须**不被判死**。两向都判得动，证明判据既不是「永远红」也不是「永远绿」的空判据。

⚠️ 本文件自身会被 CI 的 `--check-weak` 扫描（新增测试文件），因此正文不得出现字面弱断言
模式（存在性断言 / 恒真断言 / 空 `pass`）—— 断言一律写成「可判定的具体事实」。
"""
import importlib.util
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"
EXEMPTIONS_YML = REPO_ROOT / ".github" / "qa-exemptions.yml"
TECH_STACK_YML = REPO_ROOT / ".github" / "tech-stack.yml"

# 枚举仓库文件时跳过的目录（体积/生成物，与门禁判定无关）
_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "dist", "build", "target",
    ".next", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache",
}

_VERDICT_LIVE = ("block", "unmatched")


def _load_gate():
    """从 .github/growth_gate.py 加载被测模块（零依赖，importlib 文件加载）。"""
    spec = importlib.util.spec_from_file_location("growth_gate_under_test_liveness", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _repo_files(root=REPO_ROOT):
    """仓库内全部文件的相对路径（跳过生成物目录）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return out


def _rules(gate):
    """tech-stack.yml 编译出的规则（**fail-closed**：规则源读不出/为空就大声失败）。"""
    tech, err = gate._load_yaml(str(TECH_STACK_YML))
    assert not err, f"tech-stack.yml 读不出来，本守卫无从判定（不得静默放行）：{err}"
    errors: list = []
    rules = gate.compile_rules(tech.get("modules") or [], tech.get("test_commands") or {}, errors)
    assert not errors, f"tech-stack.yml 有 {len(errors)} 条规则无法编译，判定基准不可信：{errors}"
    assert rules, "tech-stack.yml 没有任何可执行规则 —— 豁免活性无从判定（不得静默放行）"
    return rules


def _load_exemptions(gate):
    """qa-exemptions.yml 的 exemptions 列表（读不出就大声失败）。"""
    data, err = gate._load_yaml(str(EXEMPTIONS_YML))
    assert not err, f"qa-exemptions.yml 读不出来：{err}"
    return data.get("exemptions") or []


def _verdicts_for(gate, pattern, files, rules):
    """pattern 盖住的文件各自的分类结论集合；零命中 ⇒ 空集。"""
    hits = [f for f in files if gate._glob_match(f.split("/"), pattern)]
    verdicts = set()
    for f in hits:
        if gate.is_auto_pass(f):
            verdicts.add("auto_pass")
            continue
        rule = gate.match_rule(f, rules)
        if rule is None:
            verdicts.add("unmatched")
            continue
        names = gate.expand_test_names(rule, f)
        found = gate.find_existing_tests(rule, names, str(REPO_ROOT))
        verdicts.add("pass" if found else "block")
    return verdicts


def _dead_reason(gate, pattern, files, rules):
    """该 pattern 是死条目则返回原因字符串，是活条目返回空串。"""
    verdicts = _verdicts_for(gate, pattern, files, rules)
    if not verdicts:
        return "僵尸：pattern 匹配不到任何现存文件（目标已删/从未存在）"
    if all(v in ("pass", "auto_pass") for v in verdicts):
        return ("冗余：盖住的文件走 tech-stack.yml 规则本来就是 "
                f"{'/'.join(sorted(verdicts))} ⇒ 该条零作用（配套测试被删/改名后会静默撑开缺测门禁）")
    return ""


# ── ① 真判据：仓库里不许有死豁免 ──────────────────────────────────────────────

def test_no_dead_exemption_entries():
    """`qa-exemptions.yml` 的每一条都必须「在做实事」（盖住的文件本来会缺测）。

    红证：2026-09-17 收紧前实测 **24** 条死条目（2 僵尸 + 22 冗余），本断言当时必红。
    复算（打印全部死条目 + 总数）：
        python3 -m pytest tests/unit_ci_workflows/test_qa_exemptions_liveness.py -q
    """
    gate = _load_gate()
    rules = _rules(gate)
    files = _repo_files()
    exemptions = _load_exemptions(gate)

    dead = []
    for ex in exemptions:
        pat = ex.get("pattern", "")
        reason = _dead_reason(gate, pat, files, rules)
        if reason:
            dead.append(f"{pat} —— {reason}")

    assert not dead, (
        f"{len(dead)} 条**死豁免**：它们已经不减少任何检查、只留着一张免检券。"
        "处置：删掉这些条目（**收紧 = 减少能免检的面**），不要靠新增字段/子表把它做成"
        "「更复杂的白名单」。逐条如下：\n  - " + "\n  - ".join(dead)
    )


def test_exemption_list_is_parseable_and_scanned():
    """防「空转」：清单必须真读到条目，且判据真的会对它们跑一遍。

    否则 `exemptions: []` 或解析退化会让上一条断言**静默空过**（绿了但没跑）。
    """
    gate = _load_gate()
    rules = _rules(gate)
    files = _repo_files()
    exemptions = _load_exemptions(gate)

    assert exemptions, "qa-exemptions.yml 没有 exemptions 条目 —— 上一条断言会退化成空跑"
    assert files, "仓库文件枚举为空 —— 活性判据无从执行（枚举不能空转）"
    scanned = [ex.get("pattern", "") for ex in exemptions]
    assert len(scanned) == len(exemptions)
    # 至少有一条被判「活」：证明判据不是恒红（把一切都判死的判据同样是空判据）
    live = [p for p in scanned if _dead_reason(gate, p, files, rules) == ""]
    assert live, "所有豁免条目都被判死 —— 判据可能恒红（先确认豁免清单是否真被清空）"


# ── ② 注入式红证 + 负例：判据两向都判得动 ─────────────────────────────────────

class TestInjectionNonVacuity:
    """把死/活条目**分别注入**同一判据，两个方向都必须判得动。"""

    ZOMBIE = "no/such/dir/never_existed_xyz.py"
    # 冗余样本：该文件在仓库里有配套测试 ⇒ 规则侧本判 pass（2026-09-17 实测），
    # 故对它再挂一条豁免就是死条目。
    REDUNDANT = "frontend/admin-web/src/lib/api.ts"
    # 活样本：规则侧判定为 block（无配套测试）⇒ 豁免在做实事，**不得**被判死。
    LIVE = "frontend/admin-web/src/components/ui/Badge.tsx"

    def test_zombie_pattern_is_detected(self):
        gate = _load_gate()
        reason = _dead_reason(gate, self.ZOMBIE, _repo_files(), _rules(gate))
        assert "僵尸" in reason, f"零命中的 pattern 必须被判僵尸，实得 {reason!r}"

    def test_redundant_pattern_is_detected(self):
        gate = _load_gate()
        reason = _dead_reason(gate, self.REDUNDANT, _repo_files(), _rules(gate))
        assert "冗余" in reason, (
            f"盖住文件本来就 pass/auto_pass 的条目必须被判冗余，实得 {reason!r}"
        )

    def test_live_pattern_is_not_flagged(self):
        """负例（防误伤）：真正在做实事的条目**不得**被判死。"""
        gate = _load_gate()
        reason = _dead_reason(gate, self.LIVE, _repo_files(), _rules(gate))
        assert reason == "", f"活条目被判死 = 判据过宽（假红），实得 {reason!r}"