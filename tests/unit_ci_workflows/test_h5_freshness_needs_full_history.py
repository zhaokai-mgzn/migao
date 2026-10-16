# case_ids: MC-113
r"""**跑需要真实历史的脚本 ⇒ checkout 必须 `fetch-depth: 0`** 的类级元守卫（issue #7073）。

## 病灶（逐字读数，不是推断）

`.github/workflows/c-end-h5-publish.yml` 的 `actions/checkout@v7` **没有 `with: fetch-depth: 0`**
⇒ 默认 `fetch-depth: 1`（浅克隆）⇒ 那里跑的 `scripts/h5_freshness_guard.py` 用
`git log -1 --format=%cI <ref> -- frontend/mini-app` 算「源码最近改动」时，浅克隆里只有 1 个提交
⇒ 它拿到的是 **HEAD 自己的提交时间**（`git log` 在只有一个提交时不判路径）。

| 面 | 读数 |
|---|---|
| CI run `38971606256`（`schedule` / sha `2f4b8b84b`）判「陈旧」 | 线上 `2026-10-09T14:15Z` 早于「源码最近改动」`2026-10-16T16:18Z` |
| 真值（全 history 复算） | `2026-10-08T03:20:02Z`（`9ebdf73d8`）⇒ 线上**新鲜**（宽限 6h，差 34.9h） |
| `2026-10-16T16:18Z` 是谁 | **= `2f4b8b84b`（HEAD）自己的提交时间** ⇒ 浅克隆的签名 |
| 同一份判据的另一条腿 `.github/workflows/h5-freshness-guard.yml` | `fetch-depth: 0`（在）⇒ 不红 |

⇒ 同一条腿**每天 cron 恒判红一次**（`53 18 * * *`），而线上是新鲜的 —— **真信号被淹**。

## 本文件锁什么（每条都能单独变红）

| # | 判据 | 红证（注入 ⇒ 必红） |
|---|---|---|
| 1 | **未登记即红**：凡 `.github/workflows/*.yml` 的任一 job 的步里出现 `canonical_scripts` 登记的脚本，该 job 必须有一个 `fetch-depth` = 该脚本要求的 checkout 步，或在 `exemptions` 里**逐字登记** | 摘掉真实文件里的 `fetch-depth: 0` ⇒ `test_c_end_h5_publish_checkout_has_full_history` 判红并**具名**该 workflow+job |
| 2 | **台账不许空转（fail-closed）**：`exemptions` 必须是对象 —— `null` / 列表 / 字符串（= 形态退化）⇒ 红（`problems()` 报「清单形态坏」） | `test_ledger_shape_is_fail_closed` 喂 5 种坏形态 |
| 3 | **台账未被兑现即红（只许缩短）**：`exemptions` 的每条必须指向**真在跑该判据**的 workflow；现取 **0 条**（`EXEMPTION_CAP_FROZEN`）⇒ 想把豁免写进来，上限先不放宽 | `test_exemption_table_only_shrinks`：登记新条目（清单变长/未被兑现）⇒ 判红 |
| 4 | **判别力自证**：①摘掉 depth ②在另一条腿加一个跑该判据的 step 而不给 depth ③把豁免表清空 ⇒ 三种坏形态**各自判红**，且报错**具名**（哪个 workflow / 哪个 job / 差什么） | `TestDiscriminatingPower` 三条 |
| 5 | **只改注释 / 加一条无关的腿 ⇒ 不红**（负控） | 同一组判据喂「只改注释」的文档 ⇒ 无问题 |

**真值坐标**：判据读的是**真实** `.github/workflows/c-end-h5-publish.yml` 的 YAML（不是副本、不是文本 grep ——
「引用 ≠ 实现」，同族 `FM-A11`：本 workflow 的提示文本里就写着 `h5_freshness_guard.py`）。
文件名带 `h5` 是**具名偏差**（如实登记）：本判据的**面**是通用的（任何登记进
`h5_script_checkout_depth_ledger.json::canonical_scripts` 的脚本都受同一把锁），名字只是它出生的地方。

## 边界（照实登记，别把「登记了」读成「治住了」）

- 本判据只判**结构**（checkout 步的 `with.fetch-depth`），**不判**「CI 上那个 job 真的检出了全 history」
  —— 后者由 `scripts/h5_freshness_guard.py` 自己的浅克隆自证（`_is_shallow`）在**运行时**兜住（判据在
  `tests/unit_ci_workflows/test_h5_freshness_guard.py::test_shallow_clone_is_unknown_not_stale`）。
- **不判**「别的脚本在浅克隆下也读不到历史」：只裁登记进 `canonical_scripts` 的那几个；一个新脚本
  要有它自己的登记（未登记 = 本判据**看不见**它，这是有意取舍：不做「扫全部脚本调 git」的语义一刀切）。
- ❌ **不读 `git show origin/main:<path>`**：CI 的 `ci workflow helper unit tests` job 是 `fetch-depth: 1`
  ⇒ 那种写法会因**错的原因**变绿/变红（先例：`tests/unit_ci_workflows/test_guard_no_mutable_ref_baseline.py`）。
"""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
LEDGER_PATH = Path(__file__).resolve().parent / "h5_script_checkout_depth_ledger.json"

#: 现取（2026-10-17）：豁免台账 **0 条** ⇒ 上限冻结在 0 —— **只许缩短**。
EXEMPTION_CAP_FROZEN = 0

#: 台账必须存在的顶层键（缺任何一个 = 形态退化 ⇒ 红）。
REQUIRED_LEDGER_KEYS = ("canonical_scripts", "exemptions")


def _load_ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


# ── 判据本体（纯函数：喂内存对象 ⇒ 可被判别力自证逐条变异）────────────────────────


def _jobs(doc: dict) -> dict:
    jobs = doc.get("jobs")
    return jobs if isinstance(jobs, dict) else {}


def _steps(job: dict) -> list[dict]:
    steps = job.get("steps")
    if not isinstance(steps, list):
        return []
    return [s for s in steps if isinstance(s, dict)]


def _step_text(step: dict) -> str:
    """步的**可执行内容**（`run` + `uses`）—— 只看这里，不看 `name` / 注释（引用 ≠ 实现）。"""
    return f"{step.get('uses') or ''}\n{step.get('run') or ''}"


def _runs_script(job: dict, script: str) -> bool:
    return any(script in _step_text(s) for s in _steps(job))


def _checkout_depth(job: dict) -> int | None:
    """该 job 里 checkout 步声明的 `fetch-depth`（没声明 ⇒ `None` = GitHub 默认 1 = 浅克隆）。"""
    for step in _steps(job):
        if str(step.get("uses") or "").startswith("actions/checkout"):
            raw = (step.get("with") or {}).get("fetch-depth")
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None
    return None


def problems(workflow_docs: dict[str, dict], ledger: dict) -> list[str]:
    """逐条报出问题（空列表 = 全绿）。`workflow_docs` = 工作流文件名 → 解析后的 YAML 文档。"""
    out: list[str] = []
    if not str(ledger.get("_") or "").strip():
        out.append(
            f"台账 `{LEDGER_PATH.name}` 缺 `_` 自述（或为空）⇒ **清空台账 = 判红**（fail-closed）："
            "这把锁不允许被「把登记内容清掉」消掉"
        )
    for key in REQUIRED_LEDGER_KEYS:
        if key not in ledger:
            out.append(f"台账 `{LEDGER_PATH.name}` 缺顶层键 `{key}` ⇒ 形态退化（判不了「未登记即红」）")
    scripts = ledger.get("canonical_scripts")
    if not isinstance(scripts, dict) or not scripts:
        out.append(f"台账 `{LEDGER_PATH.name}` 的 `canonical_scripts` 必须是非空对象（空 ⇒ 这把锁成了空转）")
        scripts = {}
    exemptions = ledger.get("exemptions")
    if not isinstance(exemptions, dict):
        out.append(
            f"台账 `{LEDGER_PATH.name}` 的 `exemptions` 必须是**对象**（现取 {exemptions!r}）⇒ "
            "清单为空/形态退化 = 判不了覆盖，属 fail-closed"
        )
        exemptions = {}
    for wf_rel, entry in exemptions.items():
        if not isinstance(entry, dict) or not str(entry.get("why") or "").strip():
            out.append(f"豁免 `{wf_rel}` 必须有非空 `why`（登记要能被质疑 ⇒ 不许只写一句「不需要」）")

    # ① 逐 workflow × 逐 job：跑了需要真实历史的脚本 ⇒ 必须有 fetch-depth: 0（或已在台账里豁免）
    hits: dict[str, list[str]] = {}
    for wf_rel, doc in workflow_docs.items():
        for job_name, job in _jobs(doc).items():
            if not isinstance(job, dict):
                continue
            for script, spec in scripts.items():
                if not _runs_script(job, script):
                    continue
                hits.setdefault(wf_rel, []).append(job_name)
                need = spec.get("required_fetch_depth")
                if _checkout_depth(job) == need:
                    continue
                if wf_rel in exemptions:
                    continue
                out.append(
                    f"🔴 `{wf_rel}` 的 job `{job_name}` 跑了 `{script}`（判据要全 history），"
                    f"却**没有** `fetch-depth: {need}`（现取 {_checkout_depth(job)!r}）⇒ 浅克隆里 `git log` "
                    f"不判路径、直接回 HEAD，会把 HEAD 的提交时间当成「源码最近改动」而**恒判陈旧**"
                    f"（issue #7073 的假红）。出口 = 给该 checkout 步加 `with: fetch-depth: {need}`，"
                    f"或在 `{LEDGER_PATH.name}` 的 `exemptions` 里逐字登记 `why`"
                )

    # ② 台账只许缩短：豁免条目必须被兑现（该 workflow 真在跑该判据），且条数 ≤ 现取上限
    for wf_rel in exemptions:
        if wf_rel not in workflow_docs:
            out.append(f"豁免 `{wf_rel}` 不在 `.github/workflows/` 里（工作流已删/改名）⇒ 台账必须同批缩短")
        elif wf_rel not in hits:
            out.append(f"豁免 `{wf_rel}` 已不跑任何登记脚本 ⇒ 该豁免是**空转**，必须从台账里删掉（只许缩短）")
    if len(exemptions) > EXEMPTION_CAP_FROZEN:
        out.append(
            f"豁免条款数 {len(exemptions)} > 现取上限 {EXEMPTION_CAP_FROZEN}（`EXEMPTION_CAP_FROZEN`）⇒ "
            "本台账**只许缩短**：要新增豁免必须先在本判据里放宽上限并写明理由（否则「加一条豁免」= 悄悄放行）"
        )
    return out


def _docs(pattern: str = "*.yml") -> dict[str, dict]:
    return {p.name: (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) for p in sorted(WORKFLOWS_DIR.glob(pattern))}


def _fixed_docs() -> dict[str, dict]:
    """**内存里修好**的那份工作流面 —— 判别力自证/负控的对照基线。

    真实文件在 Red 阶段是红的（这正是本单要修的）⇒「其余判据的对照读数」必须在**修好后**的
    内存文档上取；真实文件的那一半由 `test_c_end_h5_publish_checkout_has_full_history` 直接盯住。
    变异注入**只在内存对象上做**（不写坏真文件；同族 `docs/wiki/CI-CD.md` 的红证机具纪律）。
    """
    docs = copy.deepcopy(_docs())
    for job in (_jobs(docs["c-end-h5-publish.yml"])["publish"], _jobs(docs["h5-freshness-guard.yml"])["h5-freshness"]):
        for step in _steps(job):
            if str(step.get("uses") or "").startswith("actions/checkout"):
                step["with"] = {"fetch-depth": 0}
    return docs


# ── 判据 1：**实例**面 —— 真文件必须全绿（红证：摘掉 `fetch-depth: 0` ⇒ 本组红且具名）────────


def test_c_end_h5_publish_checkout_has_full_history():
    """issue #7073 的**实例判据**：c-end-h5-publish 的 notify 面必须跑在**全 history** 检出上。

    红证（实跑）：把 `.github/workflows/c-end-h5-publish.yml` 第 83 行的 `with: fetch-depth: 0` 摘掉
    ⇒ 本判据报出「c-end-h5-publish.yml / job publish / 没有 fetch-depth: 0」。
    """
    wf = _docs()["c-end-h5-publish.yml"]
    found = problems({"c-end-h5-publish.yml": wf}, _load_ledger())
    assert found == [], "\n".join(found)
    # 不是空断言：两条读数都要能指认「谁跑的、检出了多少历史」
    assert _runs_script(_jobs(wf)["publish"], "scripts/h5_freshness_guard.py"), \
        "c-end-h5-publish 的 publish job 已经不跑 h5_freshness_guard.py ⇒ 本判据需同批改（面变了）"
    assert _checkout_depth(_jobs(wf)["publish"]) == 0, \
        f"检出深度必须是 0（全 history），现取 {_checkout_depth(_jobs(wf)['publish'])!r}"


def test_all_workflows_running_the_guard_have_full_history():
    """**类级**面：任何 workflow（含将来新增的）跑该判据 ⇒ 都要有 `fetch-depth: 0`。"""
    found = problems(_docs(), _load_ledger())
    assert found == [], "\n".join(found)


def test_the_other_leg_keeps_its_full_history_checkout():
    """**对照面**：`h5-freshness-guard.yml` 一直是 `fetch-depth: 0` —— 它不许被顺手改成浅克隆。"""
    wf = _docs()["h5-freshness-guard.yml"]
    assert _checkout_depth(_jobs(wf)["h5-freshness"]) == 0, \
        "h5-freshness-guard 的判据也读 `git log -- frontend/mini-app` ⇒ 同样需要全 history"


# ── 判据 2/3：台账形态与「只许缩短」─────────────────────────────────────────────


def test_ledger_shape_is_fail_closed():
    """台账的坏形态（缺自述/缺键/`exemptions` 非对象/`canonical_scripts` 空）**各自判红**。

    对照读数取在**修好后的内存文档**上（真实文件在 Red 阶段是红的，见 `_fixed_docs`）。
    """
    docs = _fixed_docs()
    good = _load_ledger()
    assert problems(docs, good) == [], "台账现取必须是干净的基线（本判据的对照读数）"

    for bad in ({"canonical_scripts": good["canonical_scripts"], "exemptions": {}},
                {"_": good["_"], "canonical_scripts": good["canonical_scripts"], "exemptions": None},
                {"_": good["_"], "canonical_scripts": good["canonical_scripts"], "exemptions": []},
                {"_": good["_"], "canonical_scripts": good["canonical_scripts"], "exemptions": ""},
                {"_": good["_"], "canonical_scripts": {}, "exemptions": {}},
                {}):
        found = problems(docs, bad)
        assert found, f"退化形态 {bad.get('exemptions', '<缺键>')!r} 没被判红 ⇒ 这把锁可以被「清空台账」消掉"


def test_exemption_table_only_shrinks():
    """台账**只许缩短**：现取 0 条；登记一条（未被兑现 / 超上限）⇒ 判红并具名。

    红证（issue #7073 判据 2 的 ③）：把 `EXEMPTION_CAP_FROZEN` 调大或往台账里加条目 ⇒ 本判据红。
    """
    good = _load_ledger()
    assert good["exemptions"] == {}, (
        f"现取豁免必须为空（上限冻结在 {EXEMPTION_CAP_FROZEN}）—— 现取 {good['exemptions']!r}"
    )
    assert len(good["exemptions"]) <= EXEMPTION_CAP_FROZEN
    docs = _fixed_docs()
    # ① 「加一条豁免」本身 = 放宽（现取上限 0）⇒ 红，且报出**条数与上限**
    grown = {**good, "exemptions": {"h5-freshness-guard.yml": {"why": "假装这里不需要"}}}
    found = problems(docs, grown)
    assert any(str(EXEMPTION_CAP_FROZEN) in f and "只许缩短" in f for f in found), \
        f"往台账里加豁免没被判红（现取豁免必须为空、只许缩短）：{found}"
    # ② **空转**的豁免（那条腿根本不跑该判据）⇒ 红并具名该 workflow
    idle = {**good, "exemptions": {"nightly-verification.yml": {"why": "这条腿不跑 h5 判据"}}}
    found = problems(docs, idle)
    assert any("nightly-verification.yml" in f and "空转" in f for f in found), f"空转的豁免没被判红：{found}"
    # ③ 指向**已不存在** workflow 的豁免 ⇒ 红
    ghost = {**good, "exemptions": {"no-such-workflow.yml": {"why": "x"}}}
    assert any("no-such-workflow.yml" in f for f in problems(docs, ghost)), "指向不存在 workflow 的豁免没被判红"
    # ④ 缺 `why` 的豁免 ⇒ 红（登记要能被质疑）
    empty_why = {**good, "exemptions": {"h5-freshness-guard.yml": {"why": "  "}}}
    assert problems(docs, empty_why), "没有 why 的豁免没被判红"


# ── 判据 4/5：判别力自证 + 负控 ────────────────────────────────────────────────


class TestDiscriminatingPower:
    """三种坏形态**各自**判红（不是「整份文档被拒」的那种笼统红）。"""

    def test_removing_fetch_depth_from_the_instance_turns_it_red(self):
        """① 摘掉 `fetch-depth: 0` ⇒ 红，且**具名**报出 workflow + job + 差什么。"""
        wf = _docs()["c-end-h5-publish.yml"]
        for step in _steps(_jobs(wf)["publish"]):
            if str(step.get("uses") or "").startswith("actions/checkout"):
                step.pop("with", None)
        found = problems({"c-end-h5-publish.yml": wf}, _load_ledger())
        assert len(found) == 1, found
        msg = found[0]
        assert "c-end-h5-publish.yml" in msg and "publish" in msg and "fetch-depth: 0" in msg, msg
        assert "路径" in msg or "HEAD" in msg, f"报错要能归因（浅克隆为什么会算错）：{msg}"

    def test_a_new_leg_running_the_guard_without_depth_turns_it_red(self):
        """② 在**另一条腿**加一个跑该判据的 job 而不给 depth ⇒ 红（新腿进不来）。

        形态 = 有人新写一条腿「顺手也判一下新鲜度」，而 checkout 用默认（`fetch-depth: 1`）
        —— 那正是 issue #7073 的成因在**下一个**调用面上重演。
        """
        docs = _docs()
        wf = docs["h5-freshness-guard.yml"]
        _jobs(wf)["a-new-leg"] = {
            "runs-on": "ubuntu-latest",
            "steps": [
                {"uses": "actions/checkout@v7"},
                {"name": "顺手也判一下新鲜度", "run": "python3 scripts/h5_freshness_guard.py --no-gate"},
            ],
        }
        found = problems(docs, _load_ledger())
        assert any("h5-freshness-guard.yml" in f and "a-new-leg" in f and "fetch-depth: 0" in f for f in found), \
            f"新腿（不给 depth）没被判红 ⇒ 同一形态能进下一个调用面：{found}"

    def test_clearing_the_ledger_turns_it_red(self):
        """③ 把台账清空（`canonical_scripts` 空 / 删文件内容）⇒ 红（fail-closed）。"""
        docs = _docs()
        emptied = {"canonical_scripts": {}, "exemptions": {}}
        assert problems(docs, emptied), "清空 `canonical_scripts` 没判红 ⇒ 这把锁能被清空消掉"
        assert problems(docs, {}), "空台账（连键都没有）没判红"

    def test_comment_only_change_stays_green(self):
        """负控：只改注释 / 加一条**不跑该判据**的腿 ⇒ 不红（锁不该被自己的文案喂红）。"""
        docs = _fixed_docs()
        wf = docs["c-end-h5-publish.yml"]
        for step in _steps(_jobs(wf)["publish"]):
            if str(step.get("uses") or "").startswith("actions/checkout"):
                step["name"] = "注释式改动：checkout（fetch-depth: 0 只是写在这里的文字）"
        _jobs(wf)["publish"]["steps"].append({"name": "无关的腿", "run": "echo 无关"})
        assert problems(docs, _load_ledger()) == [], "只改注释 / 加无关的腿不该判红"


def test_judgement_is_pure_static_and_never_imports_git_or_network():
    """本判据**不联网、不跑 git**（CI 的这个 job 是 `fetch-depth: 1` ⇒ 绑可变引用会因错的原因变绿/红）。

    判据 = **AST 取被 import 的模块名**（不是扫原文找字符串 —— 那样本函数自己的禁忌清单就会命中自己，
    同族假绿的经典形态；先例：`tests/unit_ci_workflows/test_case_id_claims.py` 的同名判据）。
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported & {"subprocess", "urllib", "requests", "socket", "http"} == set(), \
        f"判据 import 了 `{sorted(imported)}` ⇒ 判定方式不再确定（CI 的浅克隆检出会让它改判）"
