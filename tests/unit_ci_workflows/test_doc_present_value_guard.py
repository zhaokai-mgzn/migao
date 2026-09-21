# case_ids: MC-012
"""文档**易变现值**（写死的计数 / 写死的版本）漂移守卫 —— issue #5082。

## 病根：修法是「改数字」而不是「改机制」⇒ 两个先例双双复发

`README.md` / `docs/wiki/Home.md` / `docs/wiki/Frontend.md` 是新人、新会话第一眼读的**技术栈真值**。
历次修法都是「把错数字改成对的数字」，于是：

* **Taro 版本**：上一轮修的是 README，`docs/wiki/Frontend.md` 又长出 `Taro 3.6`，
  而同页紧邻的 bmini-app 小节写 4.2.1 —— 实测 `frontend/mini-app/package.json` 与
  `frontend/bmini-app/package.json` 的 `@tarojs/taro` **都是 4.2.1**（同页自相矛盾）。
* **工具数**：上一轮 31 → 33，而 `README.md` 里写死 4 处「33 个」；实测
  `create_default_registry().get_all_tools()` 返回 **38** ⇒ 改数字只是把腐烂值换了个数。
* **同一个数字三份文档三个错值**：`README.md` / `docs/wiki/CI-CD.md` /
  `docs/wiki/gate-exemption-ledger.md` 各写一个不同的值，而 `.github/workflows/` 下的真值
  **24 小时内从 34 变 33**（一个 workflow 被删）⇒ **现值必然腐烂，且已经复发过一次**。

真值会动，写死的数字不会跟着动，而**没有任何东西会因此变红**：`scripts/drift_audit.py` 长期把
`hardcoded-count` 登记为未实装（泛化的 `~?N 条` 无零误红判据，见该脚本的 `UNIMPLEMENTED`）。

## 本守卫的形态：**登记面**上的现值一位都不许写死（取形态，不与真值等值）

`CLAIMS` 是**登记表**，一处登记 = 一处判定面：`paths` = 该现值出现在哪些文件；
`pattern` = 「写死」的形态；`truth_source` = 真值源（必须真实存在）；
`truth_hint` = 那些文件里**必须出现**的真值源指针；`bad_samples` = 逐字的历史错值
（注入红证的载荷；`bad_samples[0]` 还必须**只被本条目**命中 = 隔离性）。

| # | 判据 | 红证（怎么让它**单独**变红） | 自证测试 |
|---|---|---|---|
| C1 | 登记文件里不得出现 `pattern`（写死的现值） | 把 `19 个工作流` 注回 README ⇒ 只有 workflow-count 红 | `test_selfproof_C1_*` |
| C2 | 每个登记文件必须**指明真值源**（`truth_hint`）—— 只删数字不指源 = 空修复 | 从登记文件里删掉真值源指针 ⇒ 该条目红 | `test_selfproof_C2_*` |
| C3 | 判别力下界：登记表非空、每个 `paths` 与 `truth_source` 真实存在、每条 `pattern` 在**它自己的每个**历史错值上都命中 | 把 `pattern` 写成永不命中的正则 / 登记不存在的路径 ⇒ 红 | `test_selfproof_C3_*` |
| C4 | **隔离性注入红证**：把 A 的 `bad_samples[0]` 注入它自己的文件 ⇒ **恰好只有 A** 命中 | 该测试本身就是注入式红证（三条断言各自可红） | 同名测试 |
| C5a | 判据不得误伤历史叙事 / 区间说明 | 把历史错值包进叙事句喂给探测器 ⇒ 必须命中 | `test_selfproof_C5a_*` |
| C5b | 判据**只读**：跑完全部判定后真文件内容指纹（sha256）不变 | 让「被读面」被写一次 ⇒ 指纹差集必须非空 | `test_selfproof_C5b_*` |

**反空跑护栏**：`JUDGMENTS` ↔ `SELF_PROOF` 双向对账（`test_every_judgment_has_a_redproof`）——
新增一条判据而不写「能变红的注入」⇒ 红。红证卫生见 `migao-dev-flow` §19.1 元规则 ③：
**用内容指纹（sha256）自证，禁 mtime/size**。

## 已知边界（照实登记，别把「登记了」读成「治住了」）

* **只治登记面**：`CLAIMS` 之外写死的现值**照旧不判**（例：`docs/wiki/Home.md` 的
  `22 Controllers / 23 Services / 42 Entities / 26 条预置`、`docs/wiki/AI-Agent.md` 的 `30+ Tools`、
  `docs/wiki/CONTRACT-LEDGER.md` 的「38 个工具类」、README 的 `27 个 REST Controller` 一族、
  README 的 `Next.js 14` / `41 张表`）。这是**有意**的：泛化的 `~?N 条` 无法区分「断言当下条数」
  与「复述历史读数」，贸然全判 = 大面积误红（`scripts/drift_audit.py` 的 `hardcoded-count`
  登记里写着这条）。上面点名的几处**不属本包所有权**（文件不在白名单）或**未取证** ⇒ 另开单。
* 判据**不读真值**（只禁写死）⇒ 真值更新**不会**让它红 —— 这正是「现值不写死」要的性质；
  真值源是否存在由 C3 单独保证。
* 本判据**不在** `scripts/drift_audit.py` 的 `CHECKS` 集合里：那个集合的每条判据都要求在
  `tests/unit_ci_workflows/test_drift_audit_contract.py` 的 `REDPROOF` 表里有一条夹具，
  新增判据须同步改那张表。落在这里反而**更强**：本文件由 **required 检查**
  「ci workflow helper unit tests」（`.github/workflows/pr-check.yml` 的 `ci-workflow-tests`
  job）承载，`python -m pytest tests/unit_ci_workflows -q` **整目录**收集 ⇒ **无需改任何
  workflow 就能拦合并**；而 `Drift Audit` 不在分支保护的 required 集合里（判红照旧合）。
* ⚠️ **`scripts/drift_audit_baseline.json` 里那份「已生成」的 `_burn_down_note` 副本仍是旧读数**
  （实测仍是硬编码的存量数）：本包**不能**改那个文件 —— 它一旦被改动就触发 burn-down 硬预算
  「本 PR 净缩 ≥1 条目」（`burn_down.per_pr_min=1` / `metric=entries`，判据本体在
  `.github/case_trust_gate.py` 的 `burn_down_verdict`），而当前 54 条存量里**没有一条的修法
  落在本包白名单内**（12 个引用方文件全在 `docs/testing/**`、`.github/workflows/**`、
  `backend/**`、既有 `tests/unit_ci_workflows/test_*.py` 里）⇒ 改它必红。
  故本包修的是**生成器**（`burn-down-note-count` 那条），已生成副本随下一次带销账的
  `--regen-baseline` 一并刷新。**这一段是如实登记的边界，不是「已修」。**
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Claim:
    """一处登记 = 一处判定面。

    `bad_samples[0]` 必须是**只有本条目会命中**的形态（C4 的隔离性红证靠它）。
    """

    id: str
    paths: tuple[str, ...]
    pattern: str
    truth_source: str
    truth_hint: str
    bad_samples: tuple[str, ...]


# ⚠️ 每条 `bad_samples` 都是**逐字的历史错值**（改前真文件里的原文），不是编造的样例 ——
# 这样「红证」证的是「这条判据真能抓住那次真实缺陷」，而不是「能抓住我构造的东西」。
CLAIMS: tuple[Claim, ...] = (
    Claim(
        id="workflow-count",
        paths=("README.md", "docs/wiki/CI-CD.md", "docs/wiki/gate-exemption-ledger.md"),
        pattern=r"(?<![\w.])\d+\s*\+?\s*个?\s*(?:GitHub Actions\s*)?(?:工作流|workflow)",
        truth_source=".github/workflows",
        truth_hint="wc -l",
        bad_samples=(
            "# CI/CD（19 个工作流）",
            "## 14 个 GitHub Actions 工作流",
            "（现存 30 个 workflow **全是 `.yml`**）",
        ),
    ),
    Claim(
        id="tool-count",
        paths=("README.md", "docs/wiki/Home.md"),
        pattern=r"(?<![\w.])\d+\s*\+?\s*个?\s*(?:业务|AI)?\s*(?:工具|[Tt]ools?)",
        truth_source="backend/ai-agent-service/app/tools/registry.py",
        truth_hint="registry.py",
        bad_samples=(
            "33 Tools",
            "+ 33 个业务工具，覆盖售前咨询到售后服务全链路。",
            "- **33 个 AI 工具** — 商品搜索、订单管理",
            "+ 知识卡片(LLM WIKI) + 30+ Tools，覆盖售前→售后全链路。",
            "# Python AI 服务 (LangGraph双Agent, 30+ Tools, 知识卡片检索)",
        ),
    ),
    Claim(
        id="taro-version",
        paths=("README.md", "docs/wiki/Frontend.md", "docs/wiki/Home.md"),
        pattern=r"Taro\s+\d+(?:\.\d+)+",
        truth_source="frontend/mini-app/package.json",
        truth_hint="package.json",
        bad_samples=(
            "Taro 4.2.1",
            "## mini-app (Taro 3.6 微信小程序)",
            "技术：Taro 3.6 / React 18 / Sass / Zustand",
            "## bmini-app (Taro 4.2.1 B 端商家小程序，issue #2977)",
        ),
    ),
    Claim(
        id="spring-boot-version",
        paths=("README.md", "docs/wiki/Home.md"),
        pattern=r"Spring Boot\s+\d+(?:\.\d+)+",
        truth_source="backend/admin-api/pom.xml",
        truth_hint="pom.xml",
        bad_samples=(
            "Spring Boot 3.3.9",
            "| Admin API | Java 21 / Spring Boot 3.3.5 / MyBatis-Plus 3.5.8 |",
            "GW --> C[Admin API<br/>Java 21 · Spring Boot 3.3]",
        ),
    ),
    Claim(
        id="fastapi-version",
        paths=("README.md", "docs/wiki/Home.md"),
        pattern=r"FastAPI\s+\d+(?:\.\d+)+",
        truth_source="backend/ai-agent-service/requirements.txt",
        truth_hint="requirements.txt",
        bad_samples=(
            "FastAPI 0.141.1",
            "| AI Service | Python 3.11 / FastAPI 0.115 / LangChain 0.3.14 / LangGraph 0.2.60 |",
            "3.11 / FastAPI 0.115 / LC 0.3.14 / LG 0.2.60",
        ),
    ),
    Claim(
        id="langchain-version",
        paths=("README.md", "docs/wiki/Home.md"),
        pattern=r"(?:LangChain(?:\s+Core)?|LC)\s+v?\d+(?:\.\d+)+",
        truth_source="backend/ai-agent-service/requirements.txt",
        truth_hint="requirements.txt",
        bad_samples=(
            "LangChain Core 1.4.8",
            "LangChain 0.3.14",
            "LC 0.3.14",
        ),
    ),
    Claim(
        id="langgraph-version",
        paths=("README.md", "docs/wiki/Home.md"),
        pattern=r"(?:LangGraph|LG)\s+v?\d+(?:\.\d+)+",
        truth_source="backend/ai-agent-service/requirements.txt",
        truth_hint="requirements.txt",
        bad_samples=(
            "LangGraph 1.2.7",
            "LangGraph 0.2.60",
            "LG 0.2.60",
        ),
    ),
    Claim(
        id="burn-down-note-count",
        paths=("scripts/drift_audit.py",),
        pattern=r"存量是\s*\d+\s*条",
        truth_source="scripts/drift_audit_baseline.json",
        truth_hint="drift_audit.py --check",
        bad_samples=(
            "本门禁的存量是 65 条**跨目录**条目",
            "本门禁的存量是 54 条**跨目录**条目",
        ),
    ),
)

ALL_PATHS: tuple[str, ...] = tuple(dict.fromkeys(p for c in CLAIMS for p in c.paths))
ALL_IDS: tuple[str, ...] = tuple(c.id for c in CLAIMS)

# 判据 id ⇒ 该判据「能变红的注入」自证测试名（反空跑对账用，见 `test_every_judgment_has_a_redproof`）
JUDGMENTS: tuple[str, ...] = ("C1", "C2", "C3", "C4", "C5a", "C5b")
SELF_PROOF: dict[str, str] = {
    "C1": "test_selfproof_C1_injected_literal_reds_every_claim",
    "C2": "test_selfproof_C2_missing_truth_source_reds_every_claim",
    "C3": "test_selfproof_C3_broken_registry_reds_discriminant_guard",
    "C4": "test_C4_each_claim_has_an_isolating_injection_redproof",
    "C5a": "test_selfproof_C5a_narrative_detector_reds_on_injected_value",
    "C5b": "test_selfproof_C5b_written_surface_reds_read_only_guard",
}

# 历史叙事 / 区间说明：这些句子里的数字**不是**「声称当下条数」—— 一条都不许命中（C5a）
NARRATIVES: tuple[str, ...] = (
    "- **禁止长期不提交**：避免 142 个文件的大 PR。",
    "> 实测活锚曾指向落后 `origin/main` **42 个提交**的主工作区，**内容当时恰好一致**。",
    "- **完整业务后台** — 商品、订单、CRM、人工坐席、数据看板等 12+ 管理模块",
    "> **数量不写死**（易腐：24 小时内真值从 34 变 33）—— 现值现取。",
    "| **后端 — 管理 API** | Java + Spring Boot + MyBatis-Plus | JDK 21（版本见 pom.xml） |",
)


# ── 纯函数探测器（零 IO，只有 `_text` 读文件）────────────────────────────────

def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _sha(text: str) -> str:
    """内容指纹（**禁 mtime/size** —— 同秒同长度的改写骗得过这两者）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def match_lines(claim: Claim, text: str) -> list[tuple[int, str]]:
    return [(no, line.strip())
            for no, line in enumerate(text.splitlines(), start=1)
            if re.search(claim.pattern, line)]


def violations_C1(claim: Claim, texts: dict[str, str]) -> list[str]:
    """C1：登记面上写死的现值（返回可读的定位串）。"""
    return [f"    {rel}（行 {no}）：{line}"
            for rel in claim.paths
            for no, line in match_lines(claim, texts[rel])]


def missing_C2(claim: Claim, texts: dict[str, str]) -> list[str]:
    """C2：登记文件里缺真值源指针的文件（只删数字不指源 = 空修复）。"""
    return [rel for rel in claim.paths if claim.truth_hint not in texts[rel]]


def discriminant_problems(claims: tuple[Claim, ...],
                          exists: Callable[[str], bool]) -> list[str]:
    """C3：登记表判别力下界（非空 / 判定面真实存在 / 形态抓得住自己的历史错值）。"""
    problems: list[str] = []
    if not claims:
        return ["登记表为空 ⇒ C1 退化成空断言（一条现值都没在判）"]
    seen: set[str] = set()
    for claim in claims:
        if claim.id in seen:
            problems.append(f"条目 id 重复：{claim.id}（重复的登记位只会有一条生效）")
        seen.add(claim.id)
        if not claim.bad_samples:
            problems.append(f"{claim.id} 没有历史错值 ⇒ 无法证明该判据会红")
        for sample in claim.bad_samples:
            if not re.search(claim.pattern, sample):
                problems.append(
                    f"{claim.id} 的形态 `{claim.pattern}` 抓不到自己的历史错值：{sample!r}")
        for rel in claim.paths:
            if not exists(rel):
                problems.append(f"{claim.id} 登记的判定面 `{rel}` 不存在或为空 ⇒ 该条目判定面为 0")
        if not exists(claim.truth_source):
            problems.append(f"{claim.id} 的真值源 `{claim.truth_source}` 不存在")
    return problems


def fired_claims(path: str, text: str, claims: tuple[Claim, ...]) -> set[str]:
    """C4：该文本在 `path` 上命中了哪些条目（隔离性判据用它，期望恰好一个）。"""
    return {c.id for c in claims if path in c.paths and re.search(c.pattern, text)}


def narrative_hits(line: str, claims: tuple[Claim, ...]) -> set[str]:
    """C5a：一行叙事文本被哪些条目命中（期望空集）。"""
    return {c.id for c in claims if re.search(c.pattern, line)}


def fingerprint_drift(paths: tuple[str, ...], read: Callable[[str], str],
                      mutate: Callable[[], None] | None = None) -> dict[str, tuple[str, str]]:
    """C5b：跑一轮判定前后的**内容指纹**差集（`mutate` 是它的注入口，供自证用）。"""
    before = {p: _sha(read(p)) for p in paths}
    if mutate is not None:
        mutate()
    after = {p: _sha(read(p)) for p in paths}
    return {p: (before[p], after[p]) for p in paths if before[p] != after[p]}


def _texts(claim: Claim) -> dict[str, str]:
    return {rel: _text(rel) for rel in claim.paths}


def _run_all_judgments() -> None:
    for claim in CLAIMS:
        texts = _texts(claim)
        violations_C1(claim, texts)
        missing_C2(claim, texts)


def _exists(rel: str) -> bool:
    target = REPO / rel
    if target.is_dir():
        return any(target.iterdir())
    return target.is_file() and bool(target.read_text(encoding="utf-8").strip())


# ── 主判据（跑在真文件上）───────────────────────────────────────────────────

@pytest.mark.parametrize("claim", CLAIMS, ids=lambda c: c.id)
def test_C1_registered_site_writes_no_literal_present_value(claim):
    """C1：登记过的易变现值位**一律不许写死**（写死 = 下一个腐烂源，issue #5082）。"""
    found = violations_C1(claim, _texts(claim))
    assert found == [], (
        f"文案 {claim.id} 写死了易变现值（真值会动、写死的不会动，而没人会因此变红）。\n"
        + "\n".join(found)
        + f"\n改法：**现取**或附**可复算命令**，并指明真值源 {claim.truth_source}"
          f"（照 #4751 范式：易变数字不写真值）。守卫登记表见本文件 CLAIMS（{claim.id}）。")


@pytest.mark.parametrize("claim", CLAIMS, ids=lambda c: c.id)
def test_C2_registered_site_names_its_truth_source(claim):
    """C2：每个登记文件必须**指明真值源** —— 否则「删掉数字」等于读者再也拿不到这个量。"""
    missing = missing_C2(claim, _texts(claim))
    assert missing == [], (
        f"文案 {claim.id} 的登记文件没有指明真值源（{claim.truth_hint!r}）：{missing}\n"
        f"删数字不是修法 —— 必须同时写清「以 {claim.truth_source} 为准」或给出复算命令。")


def test_C3_claim_registry_is_discriminating():
    """C3：登记表非空、判定面与真值源真实存在、每条形态抓得住自己的历史错值（反恒真 / 反空面）。"""
    problems = discriminant_problems(CLAIMS, _exists)
    assert problems == [], "登记表判别力不足：\n  - " + "\n  - ".join(problems)


@pytest.mark.parametrize("claim", CLAIMS, ids=lambda c: c.id)
def test_C4_each_claim_has_an_isolating_injection_redproof(claim):
    """C4：把本条目 `bad_samples[0]` 注入它自己的登记文件 ⇒ **恰好只有本条目**命中。

    三级证明：① 注入生效（指纹变了）；② 该条目会红（不是空断言）；③ 载荷**隔离**（能定位到一位）。
    注入在**内存里的文本**上做 ⇒ 真文件一个字节都不动（C5b 另证）。
    """
    rel = claim.paths[0]
    original = _text(rel)
    payload = claim.bad_samples[0]
    assert not re.search(claim.pattern, original), (
        f"注入前 {rel} 就已命中 {claim.id} ⇒ 该条目在真文件上本来就是红的（先修文案再看红证）")
    mutated = original + "\n" + payload + "\n"
    assert _sha(mutated) != _sha(original), "注入后指纹没变 ⇒ 注入未生效（红证不成立）"
    fired = fired_claims(rel, mutated, CLAIMS)
    assert fired == {claim.id}, (
        f"把 {payload!r} 注入 {rel} 后命中的条目 = {sorted(fired)}，期望恰好 {{{claim.id!r}}}\n"
        "① 命中为空 = 该判据是空断言；② 命中含别的条目 = 载荷不隔离，红证无法定位到具体一位。")


def test_C5a_detector_does_not_fire_on_historical_narrative():
    """C5a：历史叙事 / 区间说明里的数字**不是**现值声称 —— 一条都不许命中（防误伤）。"""
    wrong = {line: sorted(narrative_hits(line, CLAIMS))
             for line in NARRATIVES if narrative_hits(line, CLAIMS)}
    assert wrong == {}, f"判据误伤历史叙事/区间说明：{wrong}"


def test_C5b_guard_is_read_only():
    """C5b：判据**只读** —— 跑完全部判定后真文件的内容指纹（sha256）逐位不变。

    这是**红证卫生**的一半（`migao-dev-flow` §19.1 元规则 ③）：取红证的动作本身不许改被测对象。
    指纹而非 mtime/size —— 同秒同长度的改写骗得过后两者。
    """
    drift = fingerprint_drift(ALL_PATHS, _text, _run_all_judgments)
    assert drift == {}, f"判据改动了真文件（内容指纹变了）：{drift}"


# ── 每条判据的「能变红的注入」自证（否则主判据的绿 = 空跑）────────────────────

@pytest.mark.parametrize("claim", CLAIMS, ids=lambda c: c.id)
def test_selfproof_C1_injected_literal_reds_every_claim(claim):
    """C1 自证：把该条目**每一个**历史错值注进它自己的第一个登记文件 ⇒ C1 必报。"""
    rel = claim.paths[0]
    base = _texts(claim)
    silent: list[str] = []
    for sample in claim.bad_samples:
        injected = dict(base)
        injected[rel] = base[rel] + "\n" + sample + "\n"
        if not violations_C1(claim, injected):
            silent.append(sample)
    assert silent == [], (
        f"C1 对 {claim.id} 的历史错值无反应（不会红的断言 = 空断言）：{silent}")


@pytest.mark.parametrize("claim", CLAIMS, ids=lambda c: c.id)
def test_selfproof_C2_missing_truth_source_reds_every_claim(claim):
    """C2 自证：把真值源指针从登记文件里抠掉 ⇒ C2 必报（证明「必须指源」这条真的在判）。"""
    texts = _texts(claim)
    stripped = {rel: text.replace(claim.truth_hint, "") for rel, text in texts.items()}
    missing = missing_C2(claim, stripped)
    assert missing == list(claim.paths), (
        f"抠掉 {claim.truth_hint!r} 后 C2 却认为这些文件都合格：{set(claim.paths) - set(missing)}"
        "（该判据对缺真值源无反应 ⇒ 空断言）")


def test_selfproof_C3_broken_registry_reds_discriminant_guard(tmp_path):
    """C3 自证：四种坏登记各自必须被报出（空表 / 形态永不命中 / 判定面不存在 / 真值源不存在）。"""
    good = CLAIMS[0]
    no_hit = Claim(id="broken", paths=("README.md",), pattern=r"绝不出现的形态",
                   truth_source="README.md", truth_hint="x", bad_samples=("33 Tools",))
    empty_samples = Claim(id="no-samples", paths=("README.md",), pattern=r"33",
                          truth_source="README.md", truth_hint="x", bad_samples=())

    def always_exists(rel: str) -> bool:
        return True

    cases = {
        "空登记表": ((), always_exists),
        "形态永不命中": ((no_hit,), always_exists),
        "没有历史错值": ((empty_samples,), always_exists),
        "判定面不存在": ((good,), lambda rel: False),
        "真值源不存在": ((good,), lambda rel: rel != good.truth_source),
    }
    for name, (claims, exists) in cases.items():
        problems = discriminant_problems(claims, exists)
        assert problems != [], f"C3 对「{name}」这类坏登记失效（不会红 = 空断言）：{problems}"
    # 反面：合规登记（真值源与判定面都在临时目录里造出来）⇒ 必须不报
    (tmp_path / "README.md").write_text("业务工具（数量以 registry.py 为单一源）\n", encoding="utf-8")
    (tmp_path / "registry.py").write_text("x = 1\n", encoding="utf-8")
    ok = Claim(id="ok", paths=("README.md",), pattern=r"\d+ Tools",
               truth_source="registry.py", truth_hint="registry.py", bad_samples=("33 Tools",))

    def tmp_exists(rel: str) -> bool:
        return (tmp_path / rel).is_file()

    assert discriminant_problems((ok,), tmp_exists) == [], "C3 误伤了合规登记（假红）"


def test_selfproof_C5a_narrative_detector_reds_on_injected_value():
    """C5a 自证：把历史错值**包进叙事句** ⇒ C5a 的探测器必须命中（证明它不是死判据）。"""
    injected = [
        "- 上一轮 README 写的是「33 个业务工具」，实测注册表是 38 ⇒ 现值腐烂。",
        f"| 4 | 扫描 scope | 改前写死（{CLAIMS[0].bad_samples[0]}） |",
    ]
    silent = [line for line in injected if not narrative_hits(line, CLAIMS)]
    assert silent == [], f"C5a 的探测器对注入的现值无反应（空判据）：{silent}"


def test_selfproof_C5b_written_surface_reds_read_only_guard(tmp_path):
    """C5b 自证：让「被读面」真的被写一次 ⇒ 指纹差集必须非空（证明这条能红）。"""
    victim = tmp_path / "victim.md"
    victim.write_text("现值现取：见真值源。\n", encoding="utf-8")

    def read(rel: str) -> str:
        return (tmp_path / rel).read_text(encoding="utf-8")

    def touch() -> None:
        victim.write_text("现值现取：见真值源。\n改了一笔。\n", encoding="utf-8")

    assert fingerprint_drift(("victim.md",), read, None) == {}, "无写入却报了指纹漂移（假红）"
    drift = fingerprint_drift(("victim.md",), read, touch)
    assert drift != {}, "被写面发生变化却判「只读」⇒ 该判据不会红（空断言）"


def test_every_judgment_has_a_redproof():
    """反空跑：`JUDGMENTS` 与 `SELF_PROOF` 必须**双向**对上，且自证测试真实存在。

    没有这一条，将来新增一条判据而忘了写「能变红的注入」⇒ 主判据全绿也只是空跑
    （`migao-acceptance`「不会红的断言 = 空断言」）。
    """
    missing = sorted(set(JUDGMENTS) - set(SELF_PROOF))
    assert missing == [], f"判据 {missing} 没有「能变红的注入」自证，请补 SELF_PROOF 条目"
    stale = sorted(set(SELF_PROOF) - set(JUDGMENTS))
    assert stale == [], f"SELF_PROOF 里有已不存在的判据：{stale}"
    absent = sorted(j for j, name in SELF_PROOF.items() if name not in globals())
    assert absent == [], f"判据 {absent} 的自证测试函数不存在（登记指向空气）"
