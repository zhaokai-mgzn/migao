# case_ids: MC-031
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 CI 域用例；
#   MC-031 = `\.github/cases/misc.yml` 新增的「main 侧生成物新鲜度守护腿」判据。）
r"""**main 侧生成物新鲜度守护腿**的判据（issue #5687 族的 burn-down）。

## 病灶（实测：同一天咬了两次）

`生成物新鲜度（render + diff）` 原先**只在 `pull_request` 面跑** —— 它是 `pr-check.yml` 的
`case-truth-check` job（`Case Contract (truths_ref)`）里的一个 step，而那个 job 带
`if: github.event_name == 'pull_request'`。⇒

- **main 可以先漂移**（有人改了 `.github/cases/**` 却没提交生成物）；
- **第一个撞上它的无辜 PR 会红**，且红的信息指向**那个 PR 自己的 diff** ⇒ **归因指向错误的对象**。
- 实测两例：某包在**纯检出 `origin/main`** 上复算复现（`eval_cases.py` ✅ 新鲜 / casebook ❌ 陈旧）；
  另一例归因被指到**另一个无关的 PR**，并被写进了公开记录（事后用提交级读数才发现站不住）。

这条残余**已被具名登记**在 `tests/unit_ci_workflows/test_casebook_summary_is_derived.py` 的
「明确的边界」一节（逐字：「**不覆盖 `main` 侧** …… 本形态的**起源就是「main 上先漂移、
下一个 PR 才红」**」）—— 本文件是它的 burn-down 判据。

## 本文件锁什么（每条都配「注入 ⇒ 必红」的判别力自证）

| # | 判据 | 红证（变异点 ⇒ 必红） |
|---|---|---|
| 1 | 守护腿存在，且 `on` **含 `schedule`**（`push` 会被 auto-merge 吞掉 ⇒ 只挂 push 的守护会被静默跳过）+ `workflow_dispatch` 人工入口 | 从解析后的 YAML 里删任一面 ⇒ 判据函数非空 |
| 2 | **判定本体只有一份**：`pr-check` 的生成物新鲜度步与本腿调**同一个** `scripts/generated_artifacts_freshness.py`，两侧都不许内联第二份 render+diff | 把旧的内联文本塞回任一侧 ⇒ 非空 |
| 3 | **对抗静默跳过**：渲染器 / 用例库 / 生成物缺失、渲染失败、语料为空 ⇒ **fail-closed（非零）**，不许打印「跳过」然后成功 | 把 fail-closed 分支换成 skip+return 0（**在内存里 exec 变异体**）⇒ 该分支的退出码变 0 |
| 4 | **判定对象真覆盖**：`COVERED_ARTIFACTS` 逐个**行为级**验证（只弄脏那一个 ⇒ 只有它被具名报出），且与判定本体的 `ARTIFACTS` 双向相等 | 任一侧少一条 ⇒ 非空 |
| 5 | **报错具名**：产物名 + 差量（提交版 vs 现取的行数）+ 可复制复算命令；不许「生成物不同步」这类不具名的话 | 喂一句不具名的报告文本 ⇒ 非空 |
| 6 | **告警面三件齐全**（`::error::` + step summary + 非零退出）+ 失败钩子（P1 值班 issue） | 逐条 needle 变异 ⇒ 非空 |
| 7 | **零新开闭环**：本腿登记进 `scripts/mechanism-registry.json`（含 `schedule` + 写作用域 ⇒ 未登记即红），读数步是 job 的最后一步且 `if: always()` | 删登记 / 改读数步位置 ⇒ 非空 |
| 8 | **不放宽既有门禁**：本腿不得出现在 `pr-check.yml`，不得挂 `pull_request` 面，不得进 required snapshot | 各注入一次 ⇒ 非空 |
| 9 | **覆盖面显式登记**：边界表逐条带 `face`/`reason`/`owner`/`restart`，且**第 3 条边界被行为级证明是真的** | 去掉表头 / 去掉字段 ⇒ 非空 |
| 10 | **「行数相同」不是新鲜度证据**：把 casebook 的**汇总读数整体减 1、不增减任何行**（真实现场 = `8112 行 / 8112 行，不同 4 行`）⇒ 仍必红且具名 | 把「逐字节相等」换成「**只比行数**」的内存变异体 ⇒ 同一夹具**变绿** |
| 11 | **「文件内部自洽」也不是证据**：同一夹具的分域合计**仍等于**总数（读文档看不出来）⇒ 不影响判红 | 同判据 10（同一条比较挣来的） |

## 2026-09-28 的第三例（issue #5741）：**两个各自自洽的分支合并** ⇒ 「块进了、汇总没进」

`git merge-tree --write-tree 2550bc4f4 e3d35c130` 的结果与实际落进 main 的那份 casebook **逐字节相同**
（`diff` 0 行、**零冲突**）：块 hunk 取并集（46 + 1 = 47），而**两侧同值的汇总 hunk 干净合并、不重算**
⇒ 落地的汇总读数比 `.github/cases/**` **少 1**。判据 10/11 把这次学到的两条伪装钉住：

- 伪装 ①：**行数相同**（提交版 8112 行 / 现取 8112 行 —— 拿行数当新鲜度证据会漏掉它）；
- 伪装 ②：**文件内部自洽**（分域合计 == 总数 —— 拿「读文档」当证据同样会漏掉它）。

唯一的证据只有一条：**与 `.github/cases/**` 重渲染的结果逐字节相等**。
🔴 这道题的根因在**时序**（「检查跑的那份快照 ≠ 实际落地的那份合并结果」），**不是**「少了一条判据」——
两条真出口（分支保护要求分支最新 / 落地后即时校验并阻断）登记在 `docs/wiki/CI-CD.md` 的 `FM-E18` 一节。

## 🔴 明确的边界（**不要**把本判据读成覆盖面更大）

- ❌ **两次 cron 之间「引入又修掉」的漂移**：本腿只在它跑的那一刻看 main 的当前状态
  ⇒ 观测不到从未与任何一次 run 相遇的瞬时漂移（一个周期内自愈的漂移 = 无读数）；
- ❌ **需要网络 / 密钥才能算的新鲜度**（线上静态根、ACR 镜像、OSS 对象）：本腿只判
  **仓内**派生视图，不做任何网络判定（那是 `h5-freshness-guard` / `deploy-reconcile` 的面）；
- ❌ **渲染器本身坏了导致两侧一起错**：源与生成物由**同一个渲染器**产出 ⇒ 渲染器少解析一个域时
  两侧一致 ⇒ 本腿不红。这一条**被行为级证明是真的**（见
  `test_boundary_renderer_broken_makes_both_sides_agree`），不是手写的免责声明；
  该类形态由 `tests/unit_ci_workflows/test_render_cases_domain_map.py` 的域覆盖判据承担；
- ❌ **不判 `pull_request` 面**：本腿判的是 **main 的当前状态**；PR 面那条既有判定**语义未改**
  （只被收敛到同一个判定本体）；
- ✅ **`verify-all.sh` 的 `cases_face_gate` 也已收敛到同一实现**（本包同批改：它原先内联
  `render_cases.py` + `cmp`，与 CI 面是第二份实现）⇒ 本仓「生成物新鲜度」现在**只有一处**实现，
  三张调用面 = `pr-check` 的 `Verify generated artifacts fresh (render + diff)` 步 /
  `main-freshness-guard` 的判定步 / `verify-all.sh gate` 的 cases 面门禁。
  本地↔CI 的 parity 由 `tests/unit_ci_workflows/test_verify_all_gate_parity.py` 继续钉住
  （它已被同批改成锚在单一实现上）。
- ❌ **不覆盖 `drift_audit.py::check_generated` 那条并行口径**：它是**基线 + 面内/面外**
  口径（`new_drift_out_of_scope` 不翻状态），本腿是无条件口径；两者并存**有意为之**
  （本包不改它 —— 改它 = 动第四条面 + 一批既有判据），但**登记为残余**：同一事实在本仓
  仍有**两条**判定路径（一条带基线/面内豁免，一条无条件）。

## 测试方式

- **纯函数 + 行为级**混用：判定本体的可判部分都做成纯函数（喂变异体不碰磁盘）；
- 涉及「改磁盘」的红证一律**当场在内存里 `exec` 由真源码变异出来的文本**（不写坏真文件）——
  依据 `docs/wiki/CI-CD.md`「红证机具的可靠性：改磁盘文件的变异**可能不被读到**」（#5687）；
- 每条红证都注明**命中的是哪个分支**，并配「只改注释 / 不改真东西 ⇒ 不红」的对照读数。
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW_REL = ".github/workflows/main-freshness-guard.yml"
WORKFLOW = REPO / WORKFLOW_REL
SCRIPT_REL = "scripts/generated_artifacts_freshness.py"
SCRIPT = REPO / SCRIPT_REL
PR_CHECK = REPO / ".github" / "workflows" / "pr-check.yml"
VERIFY_ALL = REPO / "verify-all.sh"
MECH_REGISTRY = REPO / "scripts" / "mechanism-registry.json"
REQUIRED_SNAPSHOT = REPO / "tests" / "unit_ci_workflows" / "required_status_snapshot.json"
MECH_ID = "main-freshness-guard"
JOB_ID = "freshness"

# 同源声明（面 2 = `declaration_gate_registry.json::same_source_claims`）：本判据声称
# 「`pr-check` 的生成物新鲜度步」与「本腿的判定步」**同源**（都调 `SHARED_IMPLEMENTATION`，
# 谁也不许再内联一份 render+diff）⇒ 由
# `test_generation_freshness_judgement_has_one_shared_implementation` 承担
# （它读两侧的**真 YAML**，按 `run:` 逐条比对被调脚本 + 反向查内联实现）。
SHARED_CALLERS = (
    ".github/workflows/pr-check.yml",
    ".github/workflows/main-freshness-guard.yml",
)
SHARED_IMPLEMENTATION = SCRIPT_REL

#: 本腿**登记覆盖**的生成物（逐个行为级验证；与判定本体的 `ARTIFACTS` 双向相等才算齐）。
COVERED_ARTIFACTS = (
    "tests/agent_eval/eval_cases.py",
    "docs/testing/mibao-verification-cases.md",
)

#: 覆盖面显式登记（**覆盖不到**什么）——每条必须有 face / reason / owner / restart（未登记即红）。
UNCOVERED_FACES = (
    {
        "face": "两次 cron 之间「引入又修掉」的瞬时漂移（从未与任何一次 run 相遇）",
        "reason": "本腿只在它跑的那一刻读 main 的当前状态 ⇒ 没有观测就没有读数",
        "owner": "本腿 owner（`scripts/mechanism-registry.json` 的 main-freshness-guard 条目）",
        "restart": "若要缩短暴露窗口 ⇒ 调密 cron（成本 = 每次检出 + 一次渲染，秒级）；不引入第二套判定",
    },
    {
        "face": "需要网络 / 密钥才能算的新鲜度（线上静态根 / ACR 镜像 / OSS 对象）",
        "reason": "本腿只判仓内派生视图，不做任何网络判定（故意：网络腿会带来不可判态与凭据面）",
        "owner": "h5-freshness-guard / deploy-reconcile 的 owner（它们各自的登记项）",
        "restart": "若线上产物也要判 ⇒ 在那两条腿上加判据，不要往本腿塞网络调用",
    },
    {
        "face": "渲染器本身坏了导致两侧一起错（源与生成物由同一渲染器产出 ⇒ 两侧一致 ⇒ 本腿不红）",
        "reason": "判定口径 = 「渲染器现取 vs 提交版」⇒ 渲染器错时两侧同时错，差分不可见",
        "owner": "tests/unit_ci_workflows/test_render_cases_domain_map.py 的 owner（域覆盖判据）",
        "restart": "新增用例域时该域覆盖判据必须同批登记（未登记即红）",
    },
)

#: 边界表的表头锚（措辞与本文档必须同批改 —— 它就是「本节存在」的机械证据）。
BOUNDARY_HEADING = "🔴 明确的边界（**不要**把本判据读成覆盖面更大）"

#: 判定步的识别口径：`run` 里**真的把判定本体当命令跑**，判据 = ① 命令形态调用 ② 把机器可读报告
#: 落到 `--json main-freshness-report.json`。**不许**只看「文本里出现过脚本名」：失败钩子的
#: 「清零判据」段会**引用**那条命令（引用 ≠ 执行；本仓 #5346 的教训），而它恰好也带 `gh … --json`。
JUDGEMENT_REPORT = "--json main-freshness-report.json"
INVOKE_RE = re.compile(r"python3\s+scripts/generated_artifacts_freshness\.py")

#: 本腿的**检查名**（出现在 `pr-check.yml` 里 = 有人把它折进 PR 门禁 ⇒ 报告型 ≠ required）。
GUARD_CHECK_NAME = "Main Freshness Guard (生成物新鲜度)"

#: 判红报告必须同时含有的三类要素（缺任何一类 = 不具名）。
NAMED_REPORT_NEEDLES = ("产物名", "差量", "复算命令")


# ── 工具：把真文件读成结构（变异一律在**内存对象**上做）─────────────────────────


def _doc(text: str) -> dict:
    return yaml.safe_load(text) or {}


def _dump(doc: dict) -> str:
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def _on_block(doc: dict) -> dict:
    """`on:` 在 YAML 1.1 里会被解析成布尔键 `True` ⇒ 两种键都认（不写死一种）。"""
    for key in ("on", True):
        block = doc.get(key)
        if isinstance(block, dict):
            return block
    return {}


def _on_key(doc: dict):
    """`on:` 在 YAML 1.1 里是布尔键 `True` ⇒ 返回**真实键**（变异时要写回同一个键）。"""
    for key in ("on", True):
        if isinstance(doc.get(key), dict):
            return key
    raise AssertionError("取不到 `on:` 块（workflow 结构变了 ⇒ 判据需同步）")


def _steps(doc: dict) -> list[dict]:
    job = (doc.get("jobs") or {}).get(JOB_ID) or {}
    return [s for s in (job.get("steps") or []) if isinstance(s, dict)]


def _run_texts(doc: dict) -> list[str]:
    """**所有** job 的 `run:` 文本（不限定 job id —— pr-check 的 job 不叫 `freshness`）。"""
    out: list[str] = []
    for job in (doc.get("jobs") or {}).values():
        for step in (job.get("steps") or []):
            if isinstance(step, dict):
                out.append(str(step.get("run") or ""))
    return out


def _invokes_judgement_body(run: str) -> bool:
    """该步是否**真的把判定本体当命令跑**（不是只在 `--why` / 「清零判据」文案里引用那条命令）。"""
    return bool(INVOKE_RE.search(run)) and JUDGEMENT_REPORT in run


def _workflow_doc() -> dict:
    return _doc(WORKFLOW.read_text(encoding="utf-8"))


def _pr_check_doc() -> dict:
    return _doc(PR_CHECK.read_text(encoding="utf-8"))


def _script_source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _load_script():
    """把判定本体当模块加载（**不复制它的任何逻辑**）。"""
    spec = importlib.util.spec_from_file_location("migao_generated_artifacts_freshness", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"加载不了 {SCRIPT_REL}（本判据无从判定 ⇒ 大声失败）")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _exec_mutant(mutant_src: str):
    """**在内存里**执行变异体源码，返回它的模块对象。

    这是「改磁盘文件的变异可能不被读到」（`docs/wiki/CI-CD.md`）的正解：
    变异体**直接作为判据入参**（exec 的就是变异文本），不经过磁盘、也不经过任何缓存。
    ⚠️ 必须**注册进 `sys.modules`**：`@dataclass` 处理类时要 `sys.modules[cls.__module__].__dict__`
    （不注册 ⇒ `NoneType has no attribute __dict__`，那是夹具的缺陷、不是被测实现的缺陷）。
    """
    import types

    name = "migao_freshness_mutant"
    module = types.ModuleType(name)
    module.__file__ = str(SCRIPT)
    sys.modules[name] = module
    exec(compile(mutant_src, "<freshness-mutant>", "exec"), module.__dict__)  # noqa: S102 - 判据夹具
    return module


def _mutate(src: str, old: str, new: str) -> str:
    assert old in src, f"变异锚点不存在（被测实现已漂移）：{old!r}"
    mutated = src.replace(old, new, 1)
    assert mutated != src, "变异没生效（红证会是空断言）"
    return mutated


# ── 夹具仓库：真渲染器 + 真用例库 + 真生成物（漂移在**源**或**产物**上制造）───────


_RENDERER_DEPS = ("render_cases.py", "yaml_light.py", "cases_yaml.py")


def _build_repo(root: Path, *, drift_source: bool = False, corrupt: tuple[str, ...] = (),
                broken_renderer: bool = False) -> Path:
    """建一个可判定的夹具仓库。

    - `drift_source=True`：改**用例库**（某条用例的 title）而**不重渲染** ——
      这就是今天那两次真实漂移的形态（源动了、生成物没跟）；
    - `corrupt=(<生成物路径>,)`：只弄脏那一个生成物（用于逐产物覆盖验证）；
    - `broken_renderer=True`：换成一个「永远输出提交版副本」的坏渲染器
      —— 用来**行为级证明**「渲染器坏了 ⇒ 两侧一起错 ⇒ 本腿不红」这条边界是真的。
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / ".github").mkdir(exist_ok=True)
    for name in _RENDERER_DEPS:
        shutil.copy2(REPO / ".github" / name, root / ".github" / name)
    shutil.copytree(REPO / ".github" / "cases", root / ".github" / "cases")
    for rel in COVERED_ARTIFACTS:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text((REPO / rel).read_text(encoding="utf-8"), encoding="utf-8")

    if drift_source:
        target = root / ".github" / "cases" / "misc.yml"
        text = target.read_text(encoding="utf-8")
        opener = 'title: "'
        i = text.index(opener) + len(opener)
        j = text.index('"\n', i)
        target.write_text(text[:j] + "（夹具漂移）" + text[j:], encoding="utf-8")

    for rel in corrupt:
        target = root / rel
        target.write_text(target.read_text(encoding="utf-8") + "\n# 夹具：这一行只存在于提交版\n",
                          encoding="utf-8")

    if broken_renderer:
        (root / ".github" / "render_cases.py").write_text(
            "import shutil, sys\n"
            "argv = sys.argv\n"
            "shutil.copyfile('tests/agent_eval/eval_cases.py', argv[argv.index('--out-eval') + 1])\n"
            "shutil.copyfile('docs/testing/mibao-verification-cases.md', argv[argv.index('--out-md') + 1])\n",
            encoding="utf-8")
    return root


def _run(repo: Path, *extra: str) -> tuple[int, str, dict]:
    """真跑判定本体（`subprocess`），返回 `(rc, 输出, 机器可读报告)`。"""
    report_path = Path(repo) / "freshness-report.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--window", "5",
         "--json", str(report_path), *extra],
        capture_output=True, text=True, cwd=str(repo), timeout=900,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return proc.returncode, out, report


@pytest.fixture(scope="module")
def drifted_repo(tmp_path_factory) -> Path:
    """源动过、生成物没跟的夹具（模块级：渲染一次，多个判据共用）。"""
    return _build_repo(tmp_path_factory.mktemp("drift") / "repo", drift_source=True)


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1：守护腿存在 + 触发面（含 schedule）
# ══════════════════════════════════════════════════════════════════════════════


def trigger_problems(doc: dict) -> list[str]:
    """**纯函数**：触发面必须齐备，且 `schedule` 是**不可缺**的那一面。"""
    on = _on_block(doc)
    problems: list[str] = []
    if "schedule" not in on:
        problems.append(
            "缺 `on.schedule` —— `push` 会被 auto-merge 吞掉（issue #3113/#5001：被 GITHUB_TOKEN "
            "合并的 auto-merge 不产生 push 事件）⇒ 只挂 push 的守护腿**多数合并根本不会跑**（静默跳过）")
    if "workflow_dispatch" not in on:
        problems.append("缺 `on.workflow_dispatch` —— 排障 / 复跑没有人工入口")
    if "push" not in on:
        problems.append("缺 `on.push`（branches: [main]）—— 漂移落到 main 的当场没有触发面")
    return problems


class TestTriggerFaces:
    def test_guard_leg_exists_and_has_the_required_faces(self):
        jobs = (_workflow_doc().get("jobs") or {})
        assert JOB_ID in jobs, (
            f"{WORKFLOW_REL} 里找不到 job `{JOB_ID}` —— 守护腿被改名/删除 ⇒ 本判据与它一起失锚（需同批改）")
        assert trigger_problems(_workflow_doc()) == [], "\n".join(trigger_problems(_workflow_doc()))

    @pytest.mark.parametrize("face", ["schedule", "workflow_dispatch", "push"])
    def test_dropping_any_trigger_face_turns_it_red(self, face):
        """**红证（判据 1）**：逐面从解析后的 YAML 里删掉 ⇒ 判据函数非空（各自能单独变红）。"""
        doc = _workflow_doc()
        mutated = dict(doc)
        mutated["on"] = {k: v for k, v in _on_block(doc).items() if k != face}
        assert trigger_problems(mutated) != [], f"删掉 `{face}` 之后判据没红 ⇒ 空断言"

    def test_comment_only_change_does_not_turn_red(self):
        """**对照读数**：只往 YAML 里加一段注释（不改任何触发面）⇒ **不**红（判据读结构，不读原文）。"""
        doc = _workflow_doc()
        assert trigger_problems(doc) == [], "基线本身应当绿"
        text = WORKFLOW.read_text(encoding="utf-8") + "\n# 只加一行注释（不改结构）\n"
        assert trigger_problems(_doc(text)) == [], "只改注释却判红 ⇒ 判据在读原文（#5323 的形态）"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 2：判定本体只有一份（pr-check 面与 main 面调同一个脚本）
# ══════════════════════════════════════════════════════════════════════════════

#: 旧的内联实现文本（**红证夹具**：把它塞回任一侧 ⇒ 判据必须红）。
INLINE_LEGACY_IMPL = (
    "python3 .github/render_cases.py --cases .github/cases "
    "--out-eval tests/agent_eval/eval_cases.py "
    "--out-md docs/testing/mibao-verification-cases.md\n"
    "git diff --exit-code -- tests/agent_eval/eval_cases.py "
    "docs/testing/mibao-verification-cases.md\n"
)


def shared_implementation_problems(pr_doc: dict, guard_doc: dict) -> list[str]:
    """**纯函数**：两侧都必须调同一个判定本体，且两侧都不许内联第二份 render+diff。"""
    problems: list[str] = []
    for label, doc in ((SHARED_CALLERS[0], pr_doc), (SHARED_CALLERS[1], guard_doc)):
        runs = _run_texts(doc)
        if not any(SHARED_IMPLEMENTATION in r for r in runs):
            problems.append(f"{label} 没有调用判定本体 {SHARED_IMPLEMENTATION}"
                            "（同一事实两处实现 ⇒ 必然漂移）")
        for r in runs:
            if ".github/render_cases.py" in r and "git diff --exit-code" in r:
                problems.append(f"{label} 里又出现了内联的 render + git diff（第二份实现）")
    if not problems:
        guard_runs = [r for r in _run_texts(guard_doc) if _invokes_judgement_body(r)]
        if not any(re.search(r"exit\s+\"?\$\{?RC", r) for r in guard_runs):
            problems.append("本腿的判定步没有把判定本体的退出码带出去（跑而不判 = 假绿）")
    return problems


def test_generation_freshness_judgement_has_one_shared_implementation():
    """🔴 **同源声明的判据**（`SHARED_CALLERS` 上方注释的承诺由本函数承担）。

    ⚠️ 必须是**模块级** `def`：`declaration_gate_registry.json::same_source_claims` 的 `criterion`
    只按 `^def <name>(` 解析（同族判据的既有形态）—— 写成类方法会被判「死判据」而卡合并。
    """
    problems = shared_implementation_problems(_pr_check_doc(), _workflow_doc())
    # 第三张调用面 = `verify-all.sh` 的 `cases_face_gate()`（本地预检；原先也内联一份 render+cmp）
    local = VERIFY_ALL.read_text(encoding="utf-8")
    assert f"python3 {SHARED_IMPLEMENTATION}" in local, (
        f"`verify-all.sh` 的 cases 面门禁没有调单一实现 {SHARED_IMPLEMENTATION}（本地与 CI 不同源）")
    assert problems == [], "\n".join(problems)


class TestOneSharedImplementation:
    def test_putting_the_inline_impl_back_turns_it_red(self):
        """**红证（判据 2）**：把旧的内联 render+diff 塞回任一侧 ⇒ 判据函数非空。

        命中的分支 = `shared_implementation_problems` 的第二条循环（内联实现检测）。
        """
        for label, key in ((SHARED_CALLERS[0], "pr"), (SHARED_CALLERS[1], "guard")):
            doc = _pr_check_doc() if key == "pr" else _workflow_doc()
            hit = False
            for job in (doc.get("jobs") or {}).values():
                for step in (job.get("steps") or []):
                    if isinstance(step, dict) and SHARED_IMPLEMENTATION in str(step.get("run") or ""):
                        step["run"] = INLINE_LEGACY_IMPL
                        hit = True
            assert hit, f"变异点失配：{label} 里找不到调用判定本体的步（红证不得是空断言）"
            other = _workflow_doc() if key == "pr" else _pr_check_doc()
            pair = (doc, other) if key == "pr" else (other, doc)
            assert shared_implementation_problems(*pair) != [], f"{label} 塞回内联实现后判据没红 ⇒ 空断言"

    def test_dropping_the_exit_code_propagation_turns_it_red(self):
        """**红证（判据 2 的第三条腿）**：摘掉 `exit ${RC}` ⇒ 非空（「跑而不判」的形态）。"""
        doc = _workflow_doc()
        hit = False
        for step in _steps(doc):
            run = str(step.get("run") or "")
            if SHARED_IMPLEMENTATION in run and "exit" in run:
                step["run"] = re.sub(r'exit\s+"\$\{RC\}"', "true", run, count=1)
                # ⚠️ **累积**：后面的步不命中不得把前面的命中覆盖掉（本判据第一版就栽在这）
                hit = hit or (step["run"] != run)
        assert hit, "变异点失配：找不到 `exit \"${RC}\"`（红证不得是空断言）"
        assert shared_implementation_problems(_pr_check_doc(), doc) != [], "摘掉退出码传播后判据没红 ⇒ 空断言"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：对抗「静默跳过」—— 缺依赖 / 渲染失败 ⇒ fail-closed
# ══════════════════════════════════════════════════════════════════════════════


FAILCLOSED_BRANCH = """    if undecidable:
        report["problems"] = [
            f"{ERROR_PREFIX}生成物新鲜度**无法判定**（fail-closed）：{'；'.join(undecidable)}",
            f"   复算（可复制）：{recompute_command()}",
        ]
        report["error_annotation"] = error_annotation([], undecidable)
        return report
"""
SKIP_BRANCH = """    if undecidable:
        # 变异：把 fail-closed 换成「跳过然后成功」（本仓点名的「没跑长得像通过」）
        report["problems"] = ["ℹ️ 跳过生成物新鲜度校验"]
        report["verdict"] = "fresh"
        return report
"""


class TestFailClosed:
    def test_missing_renderer_is_not_green(self, tmp_path):
        """**判据 3（行为级）**：空目录（无渲染器 / 无用例库 / 无生成物）⇒ 必须**非零**。

        命中的分支 = `evaluate()` 里**渲染之前**的那段 fail-closed（三缺一即 `undecidable`）。
        """
        empty = tmp_path / "empty"
        empty.mkdir()
        rc, out, report = _run(empty)
        assert rc != 0, f"缺依赖却以 0 退出 ⇒ 正是「跳过然后成功」的形态：\n{out}"
        assert report.get("verdict") == "undecidable", report
        assert "无法判定" in out, out
        assert "无法判定" in report.get("error_annotation", ""), report.get("error_annotation")

    def test_replacing_fail_closed_with_skip_turns_it_green(self, tmp_path):
        """**红证（判据 3）**：把 fail-closed 分支换成 skip+return 0 ⇒ 同一场景**变绿**。

        ⇒ 上面那条「非零」是**这个分支挣来的**（不是恒真）。变异在**内存里** exec，
        **不碰磁盘**（#5687：「改磁盘文件的变异可能不被读到」）。
        """
        mutant = _mutate(_script_source(), FAILCLOSED_BRANCH, SKIP_BRANCH)
        assert "跳过生成物新鲜度校验" in mutant, "变异文本没进变异体（红证会是空断言）"
        empty = tmp_path / "empty2"
        empty.mkdir()
        module = _exec_mutant(mutant)
        rc = module.main(["--repo", str(empty)])
        assert rc == 0, f"把 fail-closed 换成 skip 之后仍非零（{rc}）⇒ 判别力证明不成立"

    def test_render_failure_is_not_green(self, tmp_path):
        """渲染器存在但**跑不起来**（语法坏）⇒ 非零（不是「跳过」）。"""
        repo = _build_repo(tmp_path / "broken")
        (repo / ".github" / "render_cases.py").write_text("this is not python(((\n", encoding="utf-8")
        rc, out, report = _run(repo)
        assert rc != 0, out
        assert report.get("verdict") == "undecidable", report
        assert "无法判定" in out, out


# ══════════════════════════════════════════════════════════════════════════════
# 判据 4：判定对象真覆盖（逐产物行为级）
# ══════════════════════════════════════════════════════════════════════════════


def coverage_problems(module_artifacts: list[str], registered: tuple[str, ...]) -> list[str]:
    """**纯函数**：登记表与判定本体的 `ARTIFACTS` **双向相等**（多一条 / 少一条都红）。"""
    problems: list[str] = []
    missing = sorted(set(registered) - set(module_artifacts))
    extra = sorted(set(module_artifacts) - set(registered))
    if missing:
        problems.append(f"登记了但判定本体不判（登记在说谎）：{missing}")
    if extra:
        problems.append(f"判定本体判了但**未登记**（无行为级验证的产物）：{extra}")
    return problems


class TestCoverage:
    def test_registry_matches_the_judgement_body(self):
        module = _load_script()
        assert coverage_problems([a.rel for a in module.ARTIFACTS], COVERED_ARTIFACTS) == [], \
            "\n".join(coverage_problems([a.rel for a in module.ARTIFACTS], COVERED_ARTIFACTS))

    def test_registry_mismatch_turns_it_red(self):
        """**红证（判据 4 的登记面）**：任一侧少一条 ⇒ 非空（两个方向各一次）。"""
        module = _load_script()
        real = [a.rel for a in module.ARTIFACTS]
        assert coverage_problems(real[:-1], COVERED_ARTIFACTS) != [], "本侧少了却不红 ⇒ 空断言"
        assert coverage_problems(real + ["docs/extra.md"], COVERED_ARTIFACTS) != [], "对侧多了却不红 ⇒ 空断言"

    @pytest.mark.parametrize("artifact", COVERED_ARTIFACTS)
    def test_each_registered_artifact_is_actually_judged(self, tmp_path, artifact):
        """**判据 4（行为级）**：只弄脏**那一个**产物 ⇒ 只有它被具名报出。"""
        repo = _build_repo(tmp_path / "one", corrupt=(artifact,))
        rc, out, report = _run(repo)
        assert rc == 1, f"产物陈旧却 rc={rc}：\n{out}"
        drifted = [d["artifact"] for d in report.get("drifted") or []]
        assert drifted == [artifact], f"具名报出的产物不对（实测 {drifted}）：\n{out}"
        assert artifact in report.get("error_annotation", ""), report.get("error_annotation")

    def test_drift_shape_from_the_two_real_incidents_turns_it_red(self, drifted_repo):
        """**判据 3 的靶子 = 今天真实发生过的那两次形态**：改了 `.github/cases/**` 但生成物没跟。

        （夹具在**源**上改了一条用例的 title，生成物保持提交版 ⇒ 这正是「main 先漂移」的现场。）
        """
        rc, out, report = _run(drifted_repo)
        assert rc == 1, f"源动了、生成物没跟，却 rc={rc}：\n{out}"
        drifted = sorted(d["artifact"] for d in report.get("drifted") or [])
        assert drifted == sorted(COVERED_ARTIFACTS), f"两个产物都该陈旧（实测 {drifted}）：\n{out}"

    def test_making_the_verdict_always_green_turns_that_case_green(self, drifted_repo):
        """**红证（判据 4 的承重反转）**：把「提交版 == 现取才算新鲜」换成**恒绿** ⇒ 同一夹具变绿。

        ⇒ 上一条的红来自**这条比较**（判别力证明）。
        """
        mutant = _mutate(_script_source(), "            if committed == renewed:",
                         "            if True:  # 变异：恒绿")
        module = _exec_mutant(mutant)
        rc = module.main(["--repo", str(drifted_repo)])
        assert rc == 0, f"判定换成恒绿之后仍非零（{rc}）⇒ 判别力证明不成立"

    def test_comment_only_change_in_the_source_does_not_turn_red(self, tmp_path):
        """**对照读数**：只改**注释**（YAML 注释 / 源里的说明文字）⇒ **不**红。

        判据比的是**渲染产物**，不是「文件变了没有」⇒ 注释不进渲染结果 ⇒ 读数与红证不同。
        """
        repo = _build_repo(tmp_path / "comment")
        target = repo / ".github" / "cases" / "misc.yml"
        target.write_text("# 只加一行注释（不进渲染产物）\n" + target.read_text(encoding="utf-8"),
                          encoding="utf-8")
        rc, out, report = _run(repo)
        assert rc == 0, f"只改注释却判红 ⇒ 判据在判「文件变了没有」而不是判语义：\n{out}"
        assert report.get("verdict") == "fresh", report


# ══════════════════════════════════════════════════════════════════════════════
# 判据 5：报错必须具名（产物名 + 差量 + 可复制复算命令）
# ══════════════════════════════════════════════════════════════════════════════


def named_report_problems(lines: list[str]) -> list[str]:
    """**纯函数**：判红输出必须同时含 ① 产物名 ② **数字化的**差量 ③ 可复制的复算命令。

    缺任何一类 ⇒ 不具名（今天两次归因指错方向，起因都是不具名）。
    """
    text = "\n".join(lines)
    problems: list[str] = []
    if not any(rel in text for rel in COVERED_ARTIFACTS):
        problems.append("报告没有点名**哪个产物**（不具名）")
    if not re.search(r"提交版\s*\d+\s*行\s*(?:/|vs)\s*现取\s*\d+\s*行", text):
        problems.append("报告没有给出**数字化差量**（提交版 vs 现取的行数）")
    if "python3 scripts/generated_artifacts_freshness.py" not in text:
        problems.append("报告没有给出**可复制的复算命令**")
    return problems


class TestNamedOutput:
    def test_real_drift_report_is_named(self, drifted_repo):
        _rc, out, report = _run(drifted_repo)
        assert named_report_problems(list(report["problems"])) == [], \
            "\n".join(named_report_problems(list(report["problems"]))) + "\n\n" + out
        assert named_report_problems([report["error_annotation"]]) == [], report["error_annotation"]

    def test_unnamed_sentence_turns_it_red(self):
        """**红证（判据 5）**：把输出换成不具名的一句话 ⇒ 非空（判据在判「具名」这件事）。"""
        unnamed = ["❌ 生成物与 cases/ 单一源不同步 — 请运行 .github/render_cases.py 并提交生成物"]
        assert named_report_problems(unnamed) != [], "不具名的报告却没红 ⇒ 空断言"

    def test_delta_comes_from_real_numbers_not_a_template(self, drifted_repo):
        """差量必须是**现取**的数（同一夹具连跑两次，数字必须逐字相同且来自报告本身）。"""
        _rc1, _o1, first = _run(drifted_repo)
        _rc2, _o2, second = _run(drifted_repo)
        d1 = {d["artifact"]: d for d in first["drifted"]}
        d2 = {d["artifact"]: d for d in second["drifted"]}
        assert d1 == d2, f"同一状态两次读数不同（说明数字不是现取的）：{d1} vs {d2}"
        for rel, row in d1.items():
            assert row["committed_lines"] > 0 and row["renewed_lines"] > 0, (rel, row)
            assert row["changed_lines"] > 0, (rel, row)
            assert f"提交版 {row['committed_lines']} 行 / 现取 {row['renewed_lines']} 行" in \
                "\n".join(first["problems"]), (rel, row)

    def test_drift_window_is_readings_only_and_says_so(self, drifted_repo):
        """候选区间**只给读数、不下断言**（用提交级读数下断言正是本单要治的归因错误）。"""
        _rc, _out, report = _run(drifted_repo)
        joined = "\n".join(report["problems"])
        assert "只给读数，不下断言" in joined, joined
        assert "不是「凶手」" in joined, joined


# ══════════════════════════════════════════════════════════════════════════════
# 判据 6：告警面（::error:: + step summary + 非零退出 + 判红出口）
# ══════════════════════════════════════════════════════════════════════════════

HOOK_NEEDLES = ("gh issue create", "priority/P1", "actions/runs/", "清零判据")


def alerting_problems(doc: dict) -> list[str]:
    """**纯函数**：`test_mechanism_jobs_alerting.py` 的既有口径（真失败三件齐全）。"""
    problems: list[str] = []
    steps = _steps(doc)
    judging = [s for s in steps if _invokes_judgement_body(str(s.get("run") or ""))]
    if len(judging) != 1:
        problems.append(f"判定步必须**恰好一个**（实测 {len(judging)} 个）")
    else:
        run = str(judging[0]["run"])
        if not re.search(r"exit\s+\"?\$\{?RC", run):
            problems.append("判定步没有把退出码带出去（非零退出 = 告警面 ③）")
        if "GITHUB_STEP_SUMMARY" not in run:
            problems.append("判定步没有写 step summary（告警面 ②：失败也要有，读者才看得见全文）")
        if "::error::" not in run and "ERROR_PREFIX" not in _script_source() \
                and "::error::" not in _script_source():
            problems.append("判定本体不产生 ::error:: 注解（告警面 ①）")
    hooks = [s for s in steps if "failure()" in str(s.get("if") or "")]
    if len(hooks) != 1:
        problems.append(f"判红出口（`if: failure()`）必须**恰好一个**（实测 {len(hooks)} 个）")
    else:
        hook = hooks[0]
        text = str(hook.get("run") or "")
        for needle in HOOK_NEEDLES:
            if needle not in text:
                problems.append(f"判红出口缺 `{needle}`（定时腿没有 PR 对象 ⇒ 出口必须是 P1 值班 issue）")
        if not (hook.get("env") or {}).get("GH_TOKEN"):
            problems.append("判红出口没有声明 `GH_TOKEN` ⇒ `gh` 未认证、红而不留痕（#3834 的形态）")
    return problems


class TestAlerting:
    def test_failure_path_is_loud(self):
        problems = alerting_problems(_workflow_doc())
        assert problems == [], "\n".join(problems)

    def test_script_emits_error_annotation_on_drift(self, drifted_repo):
        """告警面 ①（行为级）：判红时 stdout 里必须有 `::error::` 且**具名**。"""
        _rc, out, report = _run(drifted_repo)
        annotation = [ln for ln in out.splitlines() if ln.startswith("::error::")]
        assert len(annotation) == 1, f"`::error::` 注解必须恰好一条（实测 {len(annotation)}）：\n{out}"
        assert named_report_problems([annotation[0]]) == [], annotation[0]

    @pytest.mark.parametrize("needle", ["exit", "GITHUB_STEP_SUMMARY", *HOOK_NEEDLES, "GH_TOKEN"])
    def test_each_alerting_element_turns_it_red(self, needle):
        """**红证（判据 6）**：逐条摘掉告警面要素 ⇒ 判据函数非空（各自能单独变红）。"""
        doc = _workflow_doc()
        hit = False
        for step in _steps(doc):
            blob = str(step.get("run") or "") + json.dumps(step.get("env") or {}, ensure_ascii=False)
            if needle == "exit" and SHARED_IMPLEMENTATION in blob:
                step["run"] = re.sub(r'exit\s+"\$\{RC\}"', "true", str(step["run"]), count=1)
                hit = True
            elif needle == "GITHUB_STEP_SUMMARY" and "GITHUB_STEP_SUMMARY" in blob:
                step["run"] = str(step["run"]).replace("GITHUB_STEP_SUMMARY", "SOMETHING_ELSE")
                hit = True
            elif needle == "GH_TOKEN" and "GH_TOKEN" in blob:
                step["env"] = {k: v for k, v in (step.get("env") or {}).items() if k != "GH_TOKEN"}
                hit = True
            elif needle in blob:
                step["run"] = str(step["run"]).replace(needle, "（已变异）")
                hit = True
        assert hit, f"变异点失配：workflow 里找不到 `{needle}`（红证不得是空断言）"
        assert alerting_problems(doc) != [], f"摘掉 `{needle}` 之后判据没红 ⇒ 空断言"

    def test_alerting_criterion_has_discriminating_power(self):
        """自证：判据函数对**明确缺件**的文档必判非空（防「恒真判据」）。"""
        doc = _workflow_doc()
        doc["jobs"][JOB_ID]["steps"] = [s for s in _steps(doc)
                                        if "failure()" not in str(s.get("if") or "")]
        assert alerting_problems(doc) != [], "去掉判红出口后判据仍为空 ⇒ 判据恒真"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 7：登记面（机制登记册 + 读数步位置）
# ══════════════════════════════════════════════════════════════════════════════


def registration_problems(registry: dict, doc: dict, workflow_rel: str = WORKFLOW_REL) -> list[str]:
    """**纯函数**：本腿必须登记（含 `schedule` + 写作用域 ⇒ 发现面命中），读数步必须是最后一步。"""
    problems: list[str] = []
    entries = [e for e in (registry.get("mechanisms") or []) if str(e.get("workflow") or "") == workflow_rel]
    if len(entries) != 1:
        problems.append(f"`scripts/mechanism-registry.json` 里必须**恰好一条**登记 {workflow_rel}"
                        f"（实测 {len(entries)} 条）—— 含 `schedule` + 写作用域的机制未登记 ⇒ 没有看门人")
        return problems
    entry = entries[0]
    if str(entry.get("job") or "") != JOB_ID:
        problems.append(f"登记项的 `job` 与现取不符（登记 {entry.get('job')!r} / 现取 {JOB_ID!r}）")
    if str(entry.get("reading") or "") != "instrumented":
        problems.append("登记项的 `reading` 必须是 `instrumented`（读数步形态）")
    steps = _steps(doc)
    emits = [i for i, s in enumerate(steps) if f"emit {entry.get('id')}" in str(s.get("run") or "")]
    if len(emits) != 1:
        problems.append(f"读数步必须**恰好一个**（实测 {len(emits)} 个）")
    else:
        i = emits[0]
        if "always()" not in str(steps[i].get("if") or ""):
            problems.append("读数步必须 `if: always()`（零动作与失败都要出声）")
        if i != len(steps) - 1:
            problems.append(f"读数步必须是 job 的**最后一步**（其后还有 {len(steps) - 1 - i} 步）")
    if entry.get("unfixed"):
        problems.append("`unfixed` 必须留白或逐条登记（本腿不编造计数读数）")
    return problems


class TestRegistration:
    def test_leg_is_registered_and_reads_out(self):
        registry = json.loads(MECH_REGISTRY.read_text(encoding="utf-8"))
        problems = registration_problems(registry, _workflow_doc())
        assert problems == [], "\n".join(problems)

    def test_dropping_the_registration_turns_it_red(self):
        """**红证（判据 7）**：删掉登记项 / 改读数步位置 / 去掉 `always()` ⇒ 各能单独变红。"""
        registry = json.loads(MECH_REGISTRY.read_text(encoding="utf-8"))
        dropped = dict(registry)
        dropped["mechanisms"] = [e for e in registry["mechanisms"]
                                 if str(e.get("workflow") or "") != WORKFLOW_REL]
        assert registration_problems(dropped, _workflow_doc()) != [], "删掉登记项却不红 ⇒ 空断言"

        doc = _workflow_doc()
        doc["jobs"][JOB_ID]["steps"] = list(_steps(doc)) + [{"name": "多余的一步", "run": "true"}]
        assert registration_problems(registry, doc) != [], "读数步不再是最后一步却不红 ⇒ 空断言"

        doc2 = _workflow_doc()
        for step in _steps(doc2):
            if f"emit {MECH_ID}" in str(step.get("run") or ""):
                step["if"] = "success()"
        assert registration_problems(registry, doc2) != [], "读数步去掉 always() 却不红 ⇒ 空断言"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 8：不放宽既有门禁（与 test_required_check_no_paths_filter.py 的关系）
# ══════════════════════════════════════════════════════════════════════════════


def gate_relaxation_problems(pr_check_text: str, snapshot_text: str, doc: dict) -> list[str]:
    """**纯函数**：本腿是**报告型**（不翻 required），且它连 `pull_request` 面都不挂。

    ⇒ `test_required_check_no_paths_filter.py` 的射程（「**上报 required 检查名**的 workflow
    不得在 `on.pull_request` 上带 `paths:` 过滤」）**结构上不适用**于本腿：
    它没有 `pull_request` 触发面，也没有 required 检查名 —— 这里把这条关系**具名钉住**，
    免得将来有人把它挂到 PR 面（那会让无辜 PR 重新变红，正是本单要消灭的观感）。
    """
    problems: list[str] = []
    # ⚠️ 口径是**结构**的：注释里点名本腿的**文件名**是合法的（那正是「为什么不折进 PR 门禁」的说明）；
    # 被判红的是「真的把它折进 PR 门禁」——`uses: ./.github/workflows/…`（可当 required 上报）或
    # 它的**检查名**出现在 pr-check 里（§23.4 T2：别被自己的文案喂红）。
    if f"uses: ./{WORKFLOW_REL}" in pr_check_text or GUARD_CHECK_NAME in pr_check_text:
        problems.append("本腿被折进 `pr-check.yml`（`uses:` 或检查名）⇒ 报告型 ≠ required"
                        "（会给所有 PR 制造噪声/误判）")
    if _on_block(doc).get("pull_request"):
        problems.append("本腿刻意**不挂** `pull_request` 面（判定基准是 main 的当前状态；挂 PR 面会把红"
                        "重新显示在无辜 PR 上，而它并不拦任何东西）")
    if "main-freshness" in snapshot_text:
        problems.append("本腿出现在 required snapshot 里 ⇒ 有人把它翻成了 required（两条前置都不满足）")
    if _on_block(doc).get("push") is None:
        problems.append("`push` 面缺失（当场红的那一面）")
    return problems


class TestDoesNotRelaxExistingGates:
    def test_leg_is_report_only_and_not_on_the_pr_face(self):
        snapshot = REQUIRED_SNAPSHOT.read_text(encoding="utf-8")
        problems = gate_relaxation_problems(PR_CHECK.read_text(encoding="utf-8"), snapshot, _workflow_doc())
        assert problems == [], "\n".join(problems)

    def test_comment_only_mention_does_not_turn_red(self):
        """**对照读数（判据 8）**：`pr-check.yml` 里**注释**提到本腿的文件名 ⇒ **不**红。

        （该文件里确实有这么一段说明 —— 它解释「为什么不把本腿折进 PR 门禁」；
        判据若读原文就会把它自己喂红，§23.4 T2。）
        """
        pr_text = PR_CHECK.read_text(encoding="utf-8") + f"\n# 参见 {WORKFLOW_REL}（只提名字）\n"
        snapshot = REQUIRED_SNAPSHOT.read_text(encoding="utf-8")
        assert gate_relaxation_problems(pr_text, snapshot, _workflow_doc()) == [], \
            "只提名字（注释）却判红 ⇒ 判据在把原文当代码读"

    @pytest.mark.parametrize("inject", ["pr_check", "pull_request", "snapshot"])
    def test_each_injection_turns_it_red(self, inject):
        """**红证（判据 8）**：三种放宽各注入一次 ⇒ 各能单独变红。"""
        pr_text = PR_CHECK.read_text(encoding="utf-8")
        snapshot = REQUIRED_SNAPSHOT.read_text(encoding="utf-8")
        doc = _workflow_doc()
        if inject == "pr_check":
            pr_text += f"\n      - uses: ./{WORKFLOW_REL}\n"
        elif inject == "pull_request":
            doc[_on_key(doc)]["pull_request"] = {"types": ["opened"]}
        else:
            snapshot = snapshot.replace("{", '{"main-freshness-guard": 1,', 1)
            assert "main-freshness" in snapshot, "snapshot 注入未生效（红证会是空断言）"
        assert gate_relaxation_problems(pr_text, snapshot, doc) != [], f"{inject} 注入后判据没红 ⇒ 空断言"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 9：覆盖面显式登记（边界表 + 「边界是真的」行为级证明）
# ══════════════════════════════════════════════════════════════════════════════


def boundary_problems(docstring: str, faces: tuple[dict, ...]) -> list[str]:
    """**纯函数**：边界必须**显式登记**（表头锚 + 每条带 face/reason/owner/restart）。"""
    problems: list[str] = []
    if BOUNDARY_HEADING not in docstring:
        problems.append(f"缺边界节标题锚：{BOUNDARY_HEADING!r}（覆盖面必须显式登记，不许含糊过去）")
    if not faces:
        problems.append("边界表为空 —— 「覆盖不到什么」必须逐条写出来")
    for i, face in enumerate(faces):
        missing = [k for k in ("face", "reason", "owner", "restart") if not str(face.get(k) or "").strip()]
        if missing:
            problems.append(f"边界表第 {i + 1} 条缺字段：{missing}")
        if "restart" in face and "restart" not in [k for k in face]:
            problems.append(f"边界表第 {i + 1} 条字段名不对")
    return problems


class TestBoundaryIsRegistered:
    def test_boundary_section_and_table_are_complete(self):
        problems = boundary_problems(__doc__ or "", UNCOVERED_FACES)
        assert problems == [], "\n".join(problems)

    def test_stripping_the_boundary_turns_it_red(self):
        """**红证（判据 9）**：去掉表头锚 / 去掉任一字段 ⇒ 各能单独变红。"""
        stripped = (__doc__ or "").replace(BOUNDARY_HEADING, "（已变异）")
        assert boundary_problems(stripped, UNCOVERED_FACES) != [], "去掉表头却不红 ⇒ 空断言"
        holed = ({k: v for k, v in UNCOVERED_FACES[0].items() if k != "restart"},) + UNCOVERED_FACES[1:]
        assert boundary_problems(__doc__ or "", holed) != [], "去掉 restart 字段却不红 ⇒ 空断言"

    def test_boundary_renderer_broken_makes_both_sides_agree(self, tmp_path):
        """🔴 **边界表的第 3 条被行为级证明是真的**（不是手写的免责声明）。

        同一个「源动过、生成物没跟」的夹具：真渲染器 ⇒ **红**；换成「永远输出提交版副本」的坏渲染器
        ⇒ **绿**（两侧一起错 ⇒ 差分不可见）⇒ 本腿**确实**覆盖不到「渲染器本身坏了」这一类。
        """
        real = _build_repo(tmp_path / "real", drift_source=True)
        rc_real, _out_real, _rep_real = _run(real)
        assert rc_real == 1, "真渲染器下应当判红（前提自证：夹具确实制造了漂移）"

        broken = _build_repo(tmp_path / "broken", drift_source=True, broken_renderer=True)
        rc_broken, out_broken, rep_broken = _run(broken)
        assert rc_broken == 0 and rep_broken.get("verdict") == "fresh", (
            f"坏渲染器下本应「两侧一致 ⇒ 绿」（这正是登记的边界）：rc={rc_broken}\n{out_broken}")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 10/11：合并产物的两种伪装 —— 「行数相同」与「文件内部自洽」
# （issue #5741 的现场：两个各自自洽的分支合并 ⇒ 块进了、汇总没进）
# ══════════════════════════════════════════════════════════════════════════════

#: casebook 的汇总节标题。「分域合计」**只在这一节里取** —— 否则正文里的 `- xx：N` 也会被数进来。
SUMMARY_HEADING = "## 覆盖统计（生成）"
TOTAL_RE = re.compile(r"- 用例总数：(\d+)（活跃 (\d+)，跳过 (\d+)）")
TIER_RE = re.compile(r"- tier 分布：smoke (\d+) / normal (\d+) / adversarial (\d+)")
DOMAIN_RE = re.compile(r"^- ([^：\n]+)：(\d+)$", re.MULTILINE)


def summary_block(text: str) -> str:
    """casebook 的**汇总节**（`SUMMARY_HEADING` 起）。取不到 ⇒ 大声失败（夹具不许静默）。"""
    return text[text.index(SUMMARY_HEADING):]


def summary_self_consistency(text: str) -> tuple[int, int]:
    """`(总数, 分域合计)` —— 「文件内部自洽」这条伪装的机械读数。"""
    block = summary_block(text)
    total = TOTAL_RE.search(block)
    assert total, "取不到总数行（用例库渲染格式变了 ⇒ 本判据需同批改）"
    return int(total.group(1)), sum(int(m.group(2)) for m in DOMAIN_RE.finditer(block))


def make_summary_stale_in_place(text: str) -> tuple[str, dict]:
    """把 casebook 的**汇总读数整体减 1**、**不增减任何行** —— 复现 git 三方合并产出的形态。

    与真实现场**同一处**的五个数：① 该域的分域行 ② 它的分域标题（`## <域>（N case）`）
    ③ 用例总数 ④ `跳过`数 ⑤ `tier` 的 normal 数。⇒ 文本**行数不变**，且**分域合计仍等于总数**。
    """
    block = summary_block(text)
    total = TOTAL_RE.search(block)
    tier = TIER_RE.search(block)
    domains = list(DOMAIN_RE.finditer(block))
    assert total and tier and domains, "夹具锚点不在了（用例库渲染格式变了 ⇒ 本判据需同批改）"

    name, n = domains[-1].group(1), int(domains[-1].group(2))
    stale = text
    for old, new in (
        (total.group(0),
         f"- 用例总数：{int(total.group(1)) - 1}（活跃 {total.group(2)}，跳过 {int(total.group(3)) - 1}）"),
        (tier.group(0),
         f"- tier 分布：smoke {tier.group(1)} / normal {int(tier.group(2)) - 1} / adversarial {tier.group(3)}"),
        (domains[-1].group(0), f"- {name}：{n - 1}"),
        (f"## {name}（{n} case）", f"## {name}（{n - 1} case）"),
    ):
        assert old in stale, f"夹具锚点不在了：{old!r}"
        stale = stale.replace(old, new, 1)
    return stale, {"domain": name, "total": int(total.group(1)), "skipped": int(total.group(3)),
                   "normal": int(tier.group(2)), "domain_n": n}


class TestMergeUnionShape:
    """**判据 10/11**：git 三方合并产出的「块进了、汇总没进」（issue #5741 的现场形态）。"""

    def _stale_repo(self, root: Path) -> tuple[Path, dict]:
        repo = _build_repo(root)
        md = repo / COVERED_ARTIFACTS[1]
        original = md.read_text(encoding="utf-8")
        stale, readings = make_summary_stale_in_place(original)
        assert stale != original, "变异没生效（红证会是空断言）"
        assert len(stale.splitlines()) == len(original.splitlines()), "本夹具要求**行数不变**"
        md.write_text(stale, encoding="utf-8")
        return repo, readings

    def test_merge_union_shape_is_red_even_with_equal_line_count(self, tmp_path):
        """**判据 10/11（行为级）**：行数相同 + 文件内部自洽 ⇒ **仍必红且具名**。"""
        repo, readings = self._stale_repo(tmp_path / "union")
        md_text = (repo / COVERED_ARTIFACTS[1]).read_text(encoding="utf-8")
        # 伪装 ②：文件内部自洽（分域合计 == 总数）—— 真实现场就是这样，读文档看不出来
        got = summary_self_consistency(md_text)
        assert got == (readings["total"] - 1, readings["total"] - 1), \
            f"夹具没有复现「内部自洽」这条伪装（红证会是空断言）：{got}"

        rc, out, report = _run(repo)
        assert rc == 1, f"行数相同、内部自洽的合并产物没判红（rc={rc}）：\n{out}"
        rows = {d["artifact"]: d for d in report["drifted"]}
        assert COVERED_ARTIFACTS[1] in rows, f"没具名报出 casebook：{report['drifted']}"
        row = rows[COVERED_ARTIFACTS[1]]
        # 伪装 ①：行数相同（真实现场 = 提交版 8112 行 / 现取 8112 行、仅 4 行不同）
        assert row["committed_lines"] == row["renewed_lines"], (
            f"本夹具要的正是「行数相同」（实测 {row}）—— 行数不同就证不到判据 10")
        assert row["changed_lines"] >= 1, row
        assert named_report_problems(list(report["problems"])) == [], "\n".join(report["problems"])

    def test_line_count_compare_mutant_turns_that_fixture_green(self, tmp_path):
        """**红证（判据 10/11）**：把「逐字节相等」换成「**只比行数**」⇒ 同一夹具**变绿**。

        ⇒ 上一条的红是**这条比较**挣来的（判别力证明）。变异在**内存里** exec，不碰磁盘
        （依据 `docs/wiki/CI-CD.md`「改磁盘文件的变异可能不被读到」）。
        """
        repo, _readings = self._stale_repo(tmp_path / "union-mutant")
        mutant = _mutate(_script_source(), "            if committed == renewed:",
                         "            if len(committed.splitlines()) == len(renewed.splitlines()):"
                         "  # 变异：只比行数")
        module = _exec_mutant(mutant)
        rc = module.main(["--repo", str(repo)])
        assert rc == 0, f"只比行数的变异体仍判红（rc={rc}）⇒ 判据 10 的判别力证明不成立"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 12~14（台账 `FM-E22`）：**合并探测** —— 把「本树 × 基线」的**合并结果**物化出来再判一次
#   病灶 = `FM-E18` 的时序面：两个**各自新鲜**的分支合并后，块 hunk 取并集、而两侧同值的汇总 hunk
#   干净合并不重算 ⇒ **落地那份比源陈旧**，而 PR 面的新鲜度判定只看**本树**。
# ══════════════════════════════════════════════════════════════════════════════

PROBE_FACE_PATHS = (".github/cases", ".github/render_cases.py",
                    "docs/testing/mibao-verification-cases.md", "tests/agent_eval/eval_cases.py")
PROBE_STEP_NEEDLE = "--merge-probe origin/main"
PROBE_GATE_NEEDLE = "steps.probe_face.outputs.probe == 'true'"
PROBE_RE_NEEDLE = "PROBE_FACE_RE='"


def _probe_predicate(job_text: str) -> str:
    """从 job 文本里取出**路径谓词原文**（门控的触发面口径只有一处事实源）。"""
    if PROBE_RE_NEEDLE not in job_text:
        return ""
    return job_text.split(PROBE_RE_NEEDLE, 1)[1].split("'", 1)[0]


def _job_text(text: str, job_id: str) -> str:
    """该 job 的 YAML 片段（到下一个顶层 job 键为止），**去掉整行注释**（注释里的提及不算实现）。"""
    marker = f"\n  {job_id}:\n"
    if marker not in text:
        return ""
    rest = text.split(marker, 1)[1]
    end = len(rest)
    for i, line in enumerate(rest.splitlines(keepends=True)):
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            end = sum(len(x) for x in rest.splitlines(keepends=True)[:i])
            break
    body = rest[:end]
    return "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("#"))


def _job_span(text: str, job_id: str = "case-truth-check") -> tuple[int, int]:
    """该 job 在原文里的 `[start, end)` 区间（供**只在它内部**做变异用；别的 job 有同名 needle）。"""
    marker = f"\n  {job_id}:\n"
    assert marker in text, f"找不到 job `{job_id}`（结构变了）"
    start = text.index(marker)
    rest = text[start + len(marker):]
    lines = rest.splitlines(keepends=True)
    end = len(text)
    for i, line in enumerate(lines):
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            end = start + len(marker) + sum(len(x) for x in lines[:i])
            break
    return start, end


def probe_wiring_problems(pr_check_text: str) -> list[str]:
    """**纯函数**：`pr-check` 必须 ① 跑合并探测 ② **路径门控** ③ checkout 够历史 ④ 门控覆盖受管用例面。"""
    problems: list[str] = []
    job = _job_text(pr_check_text, "case-truth-check")
    if not job:
        return ["找不到 `case-truth-check` job（结构变了 ⇒ 本判据需同批改）"]
    if PROBE_STEP_NEEDLE not in job:
        problems.append(f"没有跑合并探测（缺 `{PROBE_STEP_NEEDLE}`）⇒ `FM-E18` 的时序面仍无人判")
    if "probe_face" not in job or PROBE_GATE_NEEDLE not in job:
        problems.append("合并探测没有**路径门控** ⇒ 不碰受管用例面的 PR 会替 main 侧的漂移背锅"
                        "（`FM-E4` 的归因纪律）")
    if "fetch-depth: 0" not in job:
        problems.append("本 job 的 checkout 没有 `fetch-depth: 0` ⇒ `origin/main...HEAD` / merge-base 不可得，"
                        "探测会退化为「无法判定」（新的假阻塞）")
    predicate = _probe_predicate(job)
    if not predicate:
        problems.append(f"门控没有可解析的路径谓词（缺 `{PROBE_RE_NEEDLE}`）⇒ 判不了它到底覆盖哪些面")
    else:
        rx = re.compile(predicate)
        missing = [path for path in PROBE_FACE_PATHS
                   if not (rx.search(path) or rx.search(path + "/__probe__"))]
        if missing:
            problems.append(f"触发谓词**不覆盖**这几条：{missing}（受管用例面漏一条 ⇒ 该面改动不跑探测）")
    if "git fetch --no-tags --quiet origin main" not in job:
        problems.append("探测步没有先取 `origin/main` ⇒ 取不到基线（3 = 无法判定）")
    return problems


def _git_fixture(root: Path) -> Path:
    """真 git 夹具：真渲染器 + 真用例库 + 真生成物，**真提交、真分支**（合并语义只能真验）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".github").mkdir(exist_ok=True)
    for name in _RENDERER_DEPS:
        shutil.copy2(REPO / ".github" / name, root / ".github" / name)
    shutil.copytree(REPO / ".github" / "cases", root / ".github" / "cases")
    for rel in COVERED_ARTIFACTS:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text((REPO / rel).read_text(encoding="utf-8"), encoding="utf-8")
    _git_in(root, "init", "-q", ".")
    _git_in(root, "add", "-A")
    _git_in(root, "-c", "user.email=case@example.invalid", "-c", "user.name=case", "commit", "-qm", "base")
    _git_in(root, "branch", "-m", "main")
    return root


def _git_in(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    assert proc.returncode == 0, f"夹具 git {' '.join(args)} 失败：{proc.stderr[:300]}"


def _add_one_case_and_rerender(repo: Path, new_id: str, *, at_end: bool) -> None:
    """在用例库**新增一条用例**（`at_end=False` 时插在最后一条之前）+ **重渲染** ⇒ 本侧**新鲜**。"""
    case = repo / ".github" / "cases" / "misc.yml"
    text = case.read_text(encoding="utf-8")
    i = text.rindex("\n  - id: ")
    block = text[i:]
    old_id = block.split("id: ")[1].split("\n")[0]
    block = block.replace(old_id, new_id, 1).replace('title: "', f'title: "（{new_id}）', 1)
    if not block.endswith("\n"):
        block += "\n"
    case.write_text((text + "\n" + block) if at_end else (text[:i] + "\n" + block + text[i:]),
                    encoding="utf-8")
    proc = subprocess.run([sys.executable, ".github/render_cases.py", "--cases", ".github/cases",
                           "--out-eval", COVERED_ARTIFACTS[0], "--out-md", COVERED_ARTIFACTS[1]],
                          cwd=str(repo), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[:400]


@pytest.fixture(scope="module")
def two_fresh_branches(tmp_path_factory) -> Path:
    """**两侧各自新鲜**、而**合并结果会陈旧**的真夹具（`FM-E18` 的现场形态）。"""
    repo = _git_fixture(tmp_path_factory.mktemp("probe") / "repo")
    _git_in(repo, "checkout", "-q", "-b", "pr")
    _add_one_case_and_rerender(repo, "MC-900", at_end=True)
    _git_in(repo, "commit", "-qam", "pr：新增一条并重渲染")
    _git_in(repo, "checkout", "-q", "main")
    _add_one_case_and_rerender(repo, "MC-901", at_end=False)
    _git_in(repo, "commit", "-qam", "main：新增一条并重渲染")
    _git_in(repo, "checkout", "-q", "pr")
    return repo


class TestMergeProbe:
    def test_both_sides_are_fresh_on_their_own(self, two_fresh_branches):
        """**前提自证**：两侧**各自的树**都新鲜 —— 否则测到的不是「合并结果」这一面。"""
        rc, out, report = _run(two_fresh_branches)
        assert rc == 0 and report.get("verdict") == "fresh", f"前提不成立：\n{out}"

    def test_probe_flags_the_merge_result_that_would_be_stale(self, two_fresh_branches):
        """🔴 **判据 12（行为级）**：本树新鲜 + 合并结果陈旧 ⇒ `drifted`，且**归因指对本树那一侧**。"""
        module = _load_script()
        probe = module.probe_merge(two_fresh_branches, "main")
        assert probe["verdict"] == "drifted", probe
        assert probe["tree_verdict"] == "fresh" and probe["merge_verdict"] == "drifted", probe
        joined = "\n".join(probe["problems"])
        assert "合并探测" in joined and "不同源" in joined, joined
        assert "提交版" in joined and "现取" in joined, joined          # 具名差量（与 FM-E5 同口径）
        assert "FM-E18" in probe["attribution"] and "重渲染" in probe["attribution"], probe["attribution"]

    def test_probe_on_own_branch_is_fresh(self, two_fresh_branches):
        """**对照读数**：探测自己的分支 ⇒ 合并结果 == 本树 ⇒ 新鲜（不是恒判红）。"""
        module = _load_script()
        assert module.probe_merge(two_fresh_branches, "pr")["verdict"] == "fresh"

    def test_probe_says_undecidable_when_the_base_is_missing(self, two_fresh_branches):
        """**取不到 ≠ 通过**：基线取不到 ⇒ `undecidable`（调用方按三态处理）。"""
        module = _load_script()
        probe = module.probe_merge(two_fresh_branches, "origin/does-not-exist")
        assert probe["verdict"] == "undecidable" and "取不到" in "\n".join(probe["problems"]), probe

    @pytest.mark.parametrize("ref,expect_rc", [("main", 1), ("pr", 0)])
    def test_cli_exit_codes(self, two_fresh_branches, ref, expect_rc):
        """**判据 13**：CLI 把探测结论带出去（1 = 合并结果会陈旧 / 0 = 仍新鲜）。"""
        proc = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(two_fresh_branches),
                               "--merge-probe", ref], capture_output=True, text=True, timeout=900)
        assert proc.returncode == expect_rc, proc.stdout[-800:] + proc.stderr[-400:]


class TestProbeWiring:
    def test_pr_check_runs_the_probe_with_path_gating(self):
        assert probe_wiring_problems(PR_CHECK.read_text(encoding="utf-8")) == [], \
            "\n".join(probe_wiring_problems(PR_CHECK.read_text(encoding="utf-8")))

    @pytest.mark.parametrize("mutation", ["drop_probe", "drop_gate", "drop_depth", "drop_one_path", "drop_fetch"])
    def test_each_wiring_mutation_turns_it_red(self, mutation):
        """**红证（判据 14）**：逐条破坏接线 ⇒ 各能单独变红。"""
        text = PR_CHECK.read_text(encoding="utf-8")
        if mutation == "drop_depth":
            # `fetch-depth: 0` 在**别的 job** 里也有 ⇒ 只在 `case-truth-check` 内变异
            start, end = _job_span(text)
            block = text[start:end]
            needle = "          fetch-depth: 0\n"
            assert block.count(needle) == 1, f"本 job 内锚点失配：{block.count(needle)}"
            mutated = text[:start] + block.replace(needle, "", 1) + text[end:]
        else:
            old, new = {
                "drop_probe": (PROBE_STEP_NEEDLE, "--merge-probe（已变异）"),
                "drop_gate": (f"        if: {PROBE_GATE_NEEDLE}\n", ""),
                "drop_one_path": (r"\.github/render_cases\.py|", ""),
                "drop_fetch": ("git fetch --no-tags --quiet origin main", "true  # 基线不取"),
            }[mutation]
            assert text.count(old) == 1, f"变异锚点失配（{mutation}）：{old!r} × {text.count(old)}"
            mutated = text.replace(old, new, 1)
        assert mutated != text, "变异没落到文本上（红证会是空断言）"
        assert probe_wiring_problems(mutated) != [], f"{mutation} 注入后判据没红 ⇒ 空断言"

    def test_comment_only_change_does_not_turn_red(self):
        """**对照读数**：只加注释（哪怕里面出现 needle 字样）⇒ 不红（判据读的是 job 里的真实现）。"""
        text = PR_CHECK.read_text(encoding="utf-8")
        assert probe_wiring_problems(text) == [], "基线本身应当绿"
        noisy = text.replace("  case-truth-check:\n",
                             "  case-truth-check:\n    # 注释里提到 --merge-probe origin/main 与 "
                             "steps.probe_face.outputs.probe == 'true' 都不算实现\n", 1)
        assert noisy != text and probe_wiring_problems(noisy) == [], "只加注释却判红 ⇒ 判据在读原文"
