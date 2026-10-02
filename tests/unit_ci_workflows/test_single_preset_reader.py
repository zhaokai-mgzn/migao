# case_ids: MC-012, MC-028
"""**唯一**预设读取口径（S4 / issue #6020 之后）：读预设内容只许走 `preset_corpus`。

WIRING_UNDER_TEST = "tests/unit_ci_workflows/preset_corpus.py::preset_root"

## 病（实测，2026-10-02）

S4 把预设内容迁到预设仓后，业务仓里长出了**三份**「读预设内容」的实现：

| 实现 | 位置 | 形态 |
|---|---|---|
| ① 唯一口径 | `tests/unit_ci_workflows/preset_corpus.py` | 本仓 → git 基线 → 镜像 |
| ② 随手抄一份 | `tests/unit_ci_workflows/test_dev_mode_failure_modes.py` | 自己拼前缀 + 自己枚举基线 + 自己拼镜像候选 |
| ③ 又一份 | `tests/unit_ci_workflows/test_skill_load_surface.py` | 同上 |

② 的镜像候选 = 镜像根 / (剥掉前缀后的相对路径)，而镜像（= 预设仓检出）的布局是**仓根即预设根**
⇒ **镜像那一路从未命中**（现取：`mirror/migao/skills/...` 不存在、`mirror/skills/...` 存在）。
它当时仍是绿的，只因为 git 回退里还留着「旧布局的历史提交」（预设被删之前的那几个）
—— 「绿」是**别人**（历史对象）替它撑着的。

## 判据

| # | 判据 | 会怎么红 |
|---|---|---|
| 1 | 扫描 `tests/**` + `scripts/**`（排除唯一口径与**已登记残余**），不得再出现「自己剥前缀 / 自己拼镜像候选来读预设」的实现 | 新增第二份口径 ⇒ 具名报出文件:行 |
| 2 | 残余台账**只许缩短**：条数**现取**（不是写死）、且每条仍**真**命中同一套判据 | 残余被修掉却不清账 ⇒ 红；台账给不存在的形态盖章 ⇒ 红 |
| 3 | 台账不许空转 | 清空台账「消红」⇒ 红 |
| 4 | 判别力自证（注入式红证 + 控制形态） | 把**旧实现**原样放进被扫目录 ⇒ 必红；改成借口径 / 移除 ⇒ 不报（双向对照） |
| 5 | 唯一口径的**镜像那一路**必须真命中（夹具驱动，**排除历史 refs**） | 镜像候选算错（如多剥一层 `migao/`）⇒ `preset_root()` 返回 None ⇒ 红 |

## 不判（如实登记边界，§19.1）

- **不判**「镜像只在最后兜底」这类**语义**分歧：那是 `preset_corpus` 的设计决策（本仓 → 基线 → 镜像），
  本文件只判「镜像那一层**可达**」；
- **不判**镜像 / 基线内容是否**新鲜**（那是 `scripts/preset-anchor-check.sh` 与 `test_agent_presets_guard.py` 的面）；
- **判不了**「把镜像候选路径算错、但从不剥前缀」的孤立写法（形态学判据不做语义一刀切）——
  该形态由判据 5（行为面）在**能触到镜像时**兜住，两者互补；
- 「残余」这一档**不是豁免**：它逐条在 `single_reader_residuals.json` 里具名 + 写明理由，且台账**只许缩短**。
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from unit_ci_workflows import preset_corpus as pc  # noqa: E402

#: 被扫目录（**唯一口径**所在目录同样被扫 ⇒ 「唯一口径」是靠具名放行，不是靠目录外法权）。
SCAN_DIRS = ("tests", "scripts")
#: **唯一**口径的本体（它有权定义前缀与候选）—— 具名放行，不靠路径猜。
EXEMPT_UNIQUE_SOURCE = "tests/unit_ci_workflows/preset_corpus.py"
RESIDUALS_LEDGER_REL = "tests/unit_ci_workflows/single_reader_residuals.json"

#: 前缀名形态（**裸**名 = 自己定义 / 自己拼；`X.PRESET_PREFIX` 这类限定名 = 借口径，不算）。
PREFIX_NAME_RE = r"\b(?:PRESET_PREFIX\w*|PRESET_BASELINE_PREFIX)\b"

#: 正则射程 = 「**先剥掉预设前缀 / 枚举基线 / 拼镜像候选，再拿它去读文件**」这一族。
#: 每条都要求行内同时出现**前缀记号**与**一个真实读取动作**（或一次前缀剥除 / 路径拼接）⇒ 句式上锚定，
#: 避免把「文档里提到这个路径」「台账锚里写着它」误报（实测：台账字面量与 16 处锚都不命中）。
LINE_PATTERNS: tuple[tuple[str, str], ...] = (
    # P1 前缀剥除：`rel[len(PRESET_PREFIX):]` 这类下标切法
    ("strip-prefix-index", r"\[[^\]]*" + PREFIX_NAME_RE + r"[^\]]*\]"),
    # P2 前缀剥除：`lstrip` / `removeprefix` / `replace(PRESET_PREFIX, ...)`
    ("strip-prefix-call", r"\._?(?:lstrip|removeprefix|replace)\([^)]*" + PREFIX_NAME_RE),
    # P3 前缀常量 + 读取动作
    ("prefix-const-then-read",
     PREFIX_NAME_RE + r"[^\n;#]{0,140}"
     r"\b(?:read_text|is_file|exists|open|rglob|glob|ls-tree|show|cat-file|is_dir)\b"),
    # P4 `git … ls-tree/show/cat-file` 收在预设前缀上
    ("git-read-of-prefix",
     r"\b(?:ls-tree|cat-file|show)\b[^\n]{0,140}" + PREFIX_NAME_RE),
    # P5 前缀常量参与路径拼接（`repo / PRESET_PREFIX_IN_REPO`）
    ("prefix-in-path-join", r"[/+]\s*(?:\w+\s*/\s*)*" + PREFIX_NAME_RE),
    # P6 前缀常量参与 startswith（`x.startswith(PRESET_PREFIX + "skills/")`）
    ("prefix-startswith", r"\.startswith\([^)]*" + PREFIX_NAME_RE),
)

#: 跨行形态（前缀常量与 startswith / 下标切法被换行拆开时兜底）。
SYNTACTIC_PATTERNS: tuple[str, ...] = (
    r"startswith\([^)]*" + PREFIX_NAME_RE,
    r"\[[^\]]*len\(\s*" + PREFIX_NAME_RE + r"\s*\)",
)

#: **冻结计数**：当前登记的残余条数（只许缩短 —— 修掉一条就必须同批减一）。
#: 现取 = 1（`scripts/drift_audit.py`，`allowed_by_design`）；**集成时** `test_dev_mode_failure_modes.py`
#: 与 `test_agent_presets_guard.py` 两条已随本次收口删除（它们已不再命中扫描面）。
RESIDUALS_FROZEN = 1


# ──────────────────────────────────────────────────────────────────────────────
# 纯函数层：扫描器（判据吃「文件内容」，红证当场在 tmp 目录里构造，不碰真语料）
# ──────────────────────────────────────────────────────────────────────────────

def _code_lines_and_spans(text: str) -> tuple[set[int], dict[int, list[tuple[int, int]]]]:
    """→ (含**真代码 token** 的行号集, {行号: [字符串字面量的字符区间]})。

    🔴 为什么必须走 tokenize：本文件与 `preset_corpus.py` 的行文里都**逐字引用**过那种形态
    （教材 / docstring）。纯文本扫描会把「讲解」读成「第二份口径」（假红）。
    tokenize 把「字符串 / 注释」与「代码」分开 ⇒ 这一族假红结构性消失（判据 4 的红证也才可信）。
    """
    code_lines: set[int] = set()
    spans: dict[int, list[tuple[int, int]]] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                            tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
                continue
            code_lines.add(tok.start[0])
            code_lines.add(tok.end[0])
            if tok.type == tokenize.STRING:
                for ln in range(tok.start[0], tok.end[0] + 1):
                    spans.setdefault(ln, []).append((tok.start[1], tok.end[1]))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        code_lines = set(range(1, text.count("\n") + 2))          # 解析不了 ⇒ 退化成全扫（fail-loud）
    return code_lines, spans


def _blank_strings(line: str, spans: list[tuple[int, int]]) -> str:
    """按**字符区间**把该行的字符串字面量清空（保留引号占位）——字符串里的字面形态是讲解。"""
    out = line
    for start, end in sorted(spans, reverse=True):
        out = out[:start] + '""' + out[end:]
    return out


def _is_delegating(line: str) -> bool:
    """前缀名**全是限定名**（`preset_corpus.PRESET_PREFIX_IN_REPO`）⇒ 借口径，不算第二份。

    只要出现**裸**前缀名（自己定义 / 自己拼），这一行就进扫描面。
    """
    hits = list(re.finditer(PREFIX_NAME_RE, line))
    return bool(hits) and all(m.start() > 0 and line[m.start() - 1] == "." for m in hits)


def scan_text(text: str) -> list[tuple[int, str, str]]:
    """→ [(行号, 行文本, 形态名)]（只看**真代码 token**；注释 / 字符串字面量 / 教材不进扫描面）。"""
    code_lines, spans = _code_lines_and_spans(text)
    lines = text.split("\n")
    hits: list[tuple[int, str, str]] = []
    for n, line in enumerate(lines, 1):
        if n not in code_lines or line.lstrip().startswith("#"):
            continue
        blanked = _blank_strings(line, spans.get(n, []))
        if _is_delegating(blanked):
            continue
        for name, pat in LINE_PATTERNS:
            if re.search(pat, blanked):
                hits.append((n, line.strip(), name))
                break
    for pat in SYNTACTIC_PATTERNS:
        for m in re.finditer(pat, text):
            n = text.count("\n", 0, m.start()) + 1
            if n > len(lines) or any(h[0] == n for h in hits):
                continue
            line = lines[n - 1]
            if n not in code_lines or line.lstrip().startswith("#"):
                continue
            blanked = _blank_strings(line, spans.get(n, []))
            if not _is_delegating(blanked):
                hits.append((n, line.strip(), "prefix-syntactic"))
    return hits


def scan_corpus(root: Path, *, dirs: tuple[str, ...] = SCAN_DIRS) -> list[tuple[str, int, str, str]]:
    """→ [(仓库相对路径, 行号, 行文本, 形态名)]（具名可归因）。"""
    out: list[tuple[str, int, str, str]] = []
    for d in dirs:
        base = root / d
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.py")):
            rel = f.relative_to(root).as_posix()
            for n, line, name in scan_text(f.read_text(encoding="utf-8", errors="ignore")):
                out.append((rel, n, line, name))
    return out


def residual_entry_for(rel: str) -> dict | None:
    """台账里该文件的残余条目（没有 ⇒ None）。"""
    ledger = json.loads((REPO_ROOT / RESIDUALS_LEDGER_REL).read_text(encoding="utf-8"))
    for e in ledger.get("residuals", []):
        if e.get("path") == rel:
            return e
    return None


def unregistered_hits(root: Path) -> list[tuple[str, int, str, str]]:
    """→ 未被具名登记（且不是唯一口径）的命中 —— 判据 1 的具名输出。"""
    return [h for h in scan_corpus(root)
            if h[0] not in (EXEMPT_UNIQUE_SOURCE,) and residual_entry_for(h[0]) is None]


# ──────────────────────────────────────────────────────────────────────────────
# 判据 1~4：类级守卫（第二份口径进不来）
# ──────────────────────────────────────────────────────────────────────────────

def test_no_second_preset_reader_in_repo() -> None:
    """判据 1：仓内不得再出现第二份「自己剥前缀 / 自己枚举基线 / 自己拼镜像候选」的读取实现。"""
    bad = unregistered_hits(REPO_ROOT)
    assert bad == [], (
        "发现**第二份**预设读取口径（读预设内容只许走 `tests/unit_ci_workflows/preset_corpus.py`）：\n"
        + "\n".join(f"  - {rel}:{n} [{name}] {line[:120]}" for rel, n, line, name in bad)
        + "\n出口（可行动）：改成 `from unit_ci_workflows import preset_corpus` 后调 `preset_text` / "
          "`preset_path` / `preset_root`；确属不能合并的残余 ⇒ 在 "
          f"`{RESIDUALS_LEDGER_REL}` 里**具名登记**并写明理由（台账**只许缩短**）。"
    )


def test_residuals_ledger_is_shortenable_and_really_hits() -> None:
    """判据 2：残余台账条数**现取**（不写死）+ 每条仍**真**命中同一套判据（给不存在的形态盖章 ⇒ 红）。"""
    ledger = json.loads((REPO_ROOT / RESIDUALS_LEDGER_REL).read_text(encoding="utf-8"))
    residuals = ledger.get("residuals") or []
    assert len(residuals) <= RESIDUALS_FROZEN, (
        f"残余条数 {len(residuals)} > 冻结上限 {RESIDUALS_FROZEN} —— 台账**只许缩短**"
    )
    hit_paths = {rel for rel, *_ in scan_corpus(REPO_ROOT)}
    for e in residuals:
        rel = str(e.get("path", ""))
        assert (REPO_ROOT / rel).is_file(), f"台账登记的文件不存在：{rel}"
        assert rel in hit_paths, (
            f"台账给 `{rel}` 盖了「残余」章，但它**不**命中同一套判据（形态已消失 / 写错了对象）"
        )
        assert str(e.get("reason") or "").strip(), f"{rel}：残余必须写明理由（否则它就是豁免）"


def residual_state_problems(ledger: dict, hit_paths: set[str]) -> list[str]:
    """台账**状态机**判据（纯函数，红证可内存构造）：

      · 每条必须有**具名状态**（三态之一）——没有状态 = 没写处置方式 ⇒ 红；
      · 三条语义各自的「必然退休」判据：一旦它**不再命中扫描面**（= 已被迁移 / 修掉）
        ⇒ **必须**从台账删除（`state` 不豁免）——这就是「只许缩短」的牙齿。
    """
    allowed = {"in_flight", "awaiting_migration", "allowed_by_design"}
    bad: list[str] = []
    for e in ledger.get("residuals") or []:
        rel, state = str(e.get("path", "")), e.get("state")
        if state not in allowed:
            bad.append(f"{rel}：`state`={state!r} 不在 {sorted(allowed)} 里（没写处置方式 = 豁免）")
        if rel not in hit_paths:
            bad.append(f"{rel}：已不再命中扫描面（迁移 / 修掉了？）⇒ **必须**从台账删除（state={state}）")
    return bad


def test_residual_states_are_declared_and_must_retire() -> None:
    """判据 2b：残余必须写明**处置状态**；且**一旦不再命中就必须清账**（多留一条 ⇒ 红）。"""
    ledger = json.loads((REPO_ROOT / RESIDUALS_LEDGER_REL).read_text(encoding="utf-8"))
    hit_paths = {rel for rel, *_ in scan_corpus(REPO_ROOT)}
    assert residual_state_problems(ledger, hit_paths) == [], (
        "残余台账状态判据未过：\n  " + "\n  ".join(residual_state_problems(ledger, hit_paths)))
    # 注入式红证（①②③ 三种坏形态在内存里各自判红）
    stale = json.loads(json.dumps(ledger))
    stale["residuals"][0]["path"] = "tests/unit_ci_workflows/conftest.py"   # 存在但**不命中**形态 ⇒ 已退休
    assert any("不再命中扫描面" in p for p in residual_state_problems(stale, hit_paths)), stale
    nostate = json.loads(json.dumps(ledger))
    nostate["residuals"][0].pop("state", None)
    assert any("`state`" in p for p in residual_state_problems(nostate, hit_paths)), nostate
    extra = json.loads(json.dumps(ledger))
    extra["residuals"].append({"path": "tests/unit_ci_workflows/some_reader.py", "state": "in_flight",
                              "reason": "凭空多一条"})
    assert len(extra["residuals"]) > RESIDUALS_FROZEN, "多出来的条目必须同时触发判据 2 的上限（只许缩短）"


def test_residuals_ledger_cannot_be_emptied() -> None:
    """判据 3：台账不许空转（清空「消红」⇒ 红）——与判据 2 的冻结计数互为牙印。"""
    ledger = json.loads((REPO_ROOT / RESIDUALS_LEDGER_REL).read_text(encoding="utf-8"))
    assert (ledger.get("residuals") or []), (
        "残余台账被清空 ⇒ 判据 2 的「只许缩短」退化成空跑（fail-closed）"
    )


#: 红证标本 = 旧实现的原样片段（**拼接构造**，避免扫描器把这行自己当成违规实现）。
_FIXTURE_STAGED = "PRESET_" + "PREFIX_IN_REPO"
_RED_PROOF_FIXTURE = '''\
import subprocess
from pathlib import Path

{PREFIX} = ".agent-presets/migao/"
BASELINE = ("origin/main", "HEAD")


def preset_text(rel: str) -> str | None:
    inner = rel[len({PREFIX}):]
    mirror = Path.home() / "migao-dev-preset-anchor"
    if (mirror / inner).is_file():
        return (mirror / inner).read_text(encoding="utf-8")
    for ref in BASELINE:
        proc = subprocess.run(["git", "show", f"{{ref}}:{{rel}}"], capture_output=True, text=True)
        if proc.returncode == 0:
            return proc.stdout
    return None


def preset_files(repo: Path):
    rels = [x for x in subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"],
                                      capture_output=True, text=True).stdout.splitlines()
            if x.startswith({PREFIX})]
    local = repo / {PREFIX}
    return rels, local
'''

#: 红证 **控制形态**：把前缀名限定到唯一口径上（`pc.PRESET_PREFIX_IN_REPO`）⇒ 必须**不**报。
_DELEGATING_CONTROL = '''\
from unit_ci_workflows import preset_corpus as pc


def preset_text(rel: str) -> str | None:
    return pc.preset_text(rel[len(pc.PRESET_PREFIX_IN_REPO):])
'''


def test_guard_has_discriminating_power(tmp_path: Path) -> None:
    """判据 4（**注入式红证**，双向对照）：旧实现进被扫目录 ⇒ 必红；改成借口径 / 移除 ⇒ 不报。"""
    staged = tmp_path / "tests" / "unit_ci_workflows"
    staged.mkdir(parents=True)
    injected = staged / "second_reader.py"
    rel = "tests/unit_ci_workflows/second_reader.py"

    injected.write_text(_RED_PROOF_FIXTURE.format(PREFIX=_FIXTURE_STAGED), encoding="utf-8")
    injected_hits = [h for h in scan_corpus(tmp_path) if h[0] == rel]
    assert injected_hits, "注入的旧实现**没被**判据 4 抓到 ⇒ 守卫是空断言"
    assert {h[3] for h in injected_hits} >= {"strip-prefix-index", "prefix-startswith"}, injected_hits
    assert any(h[0] == rel for h in unregistered_hits(tmp_path)), "注入形态没被「未登记即红」判出"

    injected.write_text(_DELEGATING_CONTROL, encoding="utf-8")           # 控制形态：借口径 ⇒ 不报
    assert [h for h in scan_corpus(tmp_path) if h[0] == rel] == [], (
        "改成 `pc.PRESET_PREFIX_IN_REPO`（唯一口径的限定名）后仍报 ⇒ 守卫会把正主也咬死（假红）"
    )

    injected.unlink()                                                    # 反向对照：移除 ⇒ 不报
    assert scan_corpus(tmp_path) == [], "移除注入后仍报 ⇒ 扫描器在误报（对照读数必须为空）"

    # 标本自证：唯一口径本体自己**必须**命中形态（否则红证标本与真实形态已经漂了 ⇒ 判据 4 是空断言）
    canonical = (REPO_ROOT / EXEMPT_UNIQUE_SOURCE).read_text(encoding="utf-8")
    assert scan_text(canonical), "唯一口径本体没命中任何形态 ⇒ 红证标本与真实形态已经漂了"


def test_guard_does_not_flag_registered_residual_twice() -> None:
    """对照读数：已登记残余不重复出现在「未登记」清单里（台账真的生效）。"""
    ledger = json.loads((REPO_ROOT / RESIDUALS_LEDGER_REL).read_text(encoding="utf-8"))
    registered = {str(e.get("path")) for e in ledger.get("residuals") or []}
    assert registered, "台账为空 ⇒ 本条对照无从判定"
    flagged = {rel for rel, *_ in unregistered_hits(REPO_ROOT)}
    assert flagged & registered == set(), f"已登记的残余仍被判为未登记：{sorted(flagged & registered)}"


# ──────────────────────────────────────────────────────────────────────────────
# 判据 5：唯一口径的**镜像那一路**必须真命中（夹具驱动；排除历史 refs ⇒ 修前必红）
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def mirror_only_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """**真布局**镜像夹具 + 一个「只有单提交、没有预设」的隔离仓（= 排除历史 refs）。

    · 镜像布局 = **仓根即预设根**（`preset.yml` + `skills/migao-dev-flow/SKILL.md`）—— 与本机
      镜像 `~/migao-dev-preset-anchor` 一致（**没有** `migao/` 那一层）；
    · 隔离仓 = `git init` + 一次提交（预设的历史在它里面**不存在**）；
    · 只改**环境**（`REPO_ROOT` / `PRESET_MIRROR` / 缓存），**不复制任何读取实现** ⇒ 判的是生产代码路径。
    """
    mirror = tmp_path / "preset-mirror"
    (mirror / "skills" / "migao-dev-flow").mkdir(parents=True)
    (mirror / "preset.yml").write_text("name: migao\n", encoding="utf-8")
    (mirror / "skills" / "migao-dev-flow" / "SKILL.md").write_text(
        "---\nname: migao-dev-flow\ndescription: fixture\n---\n正文\n", encoding="utf-8")
    (mirror / "skills" / "migao-dev-flow" / "CHANGELOG.md").write_text(
        "- v1.0.0（2026-10-02 夹具）：控制形态\n", encoding="utf-8")

    isolated = tmp_path / "isolated-repo"
    isolated.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=isolated, check=True)
    (isolated / "placeholder.txt").write_text("no preset content here\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(isolated), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(isolated), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "-m", "single commit, no presets"], check=True)

    monkeypatch.setattr(pc, "REPO_ROOT", isolated)
    monkeypatch.setattr(pc, "PRESET_MIRROR", mirror)
    monkeypatch.setattr(pc, "_CACHE", [])
    yield mirror, isolated


def test_mirror_route_is_hit_when_history_is_gone(mirror_only_env) -> None:
    """判据 5（**修前必红、修后必绿**）：**排除历史 refs** 后，「镜像读取」仍必须命中。"""
    mirror, _isolated = mirror_only_env
    root = pc.preset_root()
    assert isinstance(root, Path), (
        "镜像那一路没命中（返回 None）—— 夹具的布局就是预设仓布局（仓根即预设根），"
        "算错候选路径（例如多剥一层 `migao/`）就必然落到这里"
    )
    assert root == mirror, f"取到的不是夹具镜像：{root}"
    text = pc.preset_text("skills/migao-dev-flow/SKILL.md")
    assert text and "migao-dev-flow" in text, (
        "镜像里读不到技能正文 ⇒ 依赖它的判据会 fail-closed 判红（这正是本包要消灭的形态）"
    )
