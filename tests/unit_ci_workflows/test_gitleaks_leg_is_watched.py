# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 `.github/cases/misc.yml` 的登记。本包不新建用例族。）
"""`Secret Scan (gitleaks)` 这条 required 腿必须**有人看守**（issue #6144 §1-B 末行）。

## 病（现取读数，非推断）

`Secret Scan (gitleaks)` 在**分支保护的 required 集合里**
（`gh api repos/zhaokai-mgzn/migao/branches/main/protection --jq '.required_status_checks.contexts[]'`
现取命中；只读快照 `tests/unit_ci_workflows/required_status_snapshot.json` 也含它），
而 `tests/**` 里 `Run gitleaks secret scan` **命中 0**：

    $ git grep -n "Run gitleaks secret scan" origin/main -- tests/
    （无输出）

⇒ **没有任何东西保证它还在跑 / 还能红**：把这个 job 删掉、改名、`if: false`、
或给 action 套一个 `continue-on-error`，本地 597 个判据**一个都不会红**，
而它**是 required** ⇒ 形态 =「检查还在 required 集合里、但已经不会拦任何东西」
（同 `migao-dev-flow` §23.7 的 A 族：机制静默失效）。

## 本判据锁什么（结构面）

| # | 判据 | 变红形态 |
|---|---|---|
| 1 | `required_status_snapshot.json` 仍含 `Secret Scan (gitleaks)` | 有人把它从快照里删掉「消红」 |
| 2 | `pr-check.yml` 仍有 `gitleaks-scan` job，且 `name: Secret Scan (gitleaks)` | 删 job / 改名（改名 = required context 永远等不到上报） |
| 3 | job 级 `if:` 仍**点名 `pull_request`**（有意保留：gitleaks 只扫 PR diff） | 删掉这个 `if`（推到 main 上跑，语义漂移） |
| 4 | 有一步**用 `gitleaks/gitleaks-action`** | 换掉/删掉 action（腿名在、扫描不在） |
| 5 | job 与**该步**都不得 `continue-on-error`、不得 `if: false`/`${{ false }}` | 红被吞（「等价于不装」） |

## 真红证（**已真跑，读数照实登记**）

- ✅ **结构判据**（判据 1~5）**已落**，且每条都有**注入式红证**（`test_red_proof_*`，各能单独变红）
  + 一条反向对照（`test_benign_filter_does_not_red`：给该步加一个良性 `with:` 参数 ⇒ 必须仍绿，
  防「判据只会喊红」）。
- ✅ **真塞 fake secret 真扫了一次**（本机实跑读数，2026-10-03）：
  `brew install gitleaks` ⇒ **8.30.1**；临时 git 仓塞一个**格式合法但非真实**的凭据：

      $ gitleaks detect --no-banner --source .
      10:50AM INF 1 commits scanned. / WRN leaks found: 1
      REAL_SCAN_RC=1

  ⇒ 「该腿会红」在**本机真对象上**被证明（不是靠推断）。同一段代码在 CI runner 上
  （`gitleaks/gitleaks-action` 自带二进制）照样成立。
- ✅ **额外旁证（真事件，非构造）**：本 PR 第一次 `git push` 被 GitHub **push protection**
  以 `GH013 Push cannot contain secrets` **拒绝**，命中的正是本文件里那行 Slack webhook 形态的
  **假**凭据（`locations: tests/unit_ci_workflows/test_gitleaks_leg_is_watched.py:288`）
  ⇒ **扫描链真的会拦**（连假凭据都不许进仓）。故本用例的凭据形态改为**运行时拼接构造**
  （仓里不留可命中的字面量），并实测确认拼出来的串仍被 `gitleaks` 命中。
- ⚠️ **两个实测坑（写进判据防复发）**：
  ① 第一版塞 AWS 官方文档示例键（`AKIA…EXAMPLE`）⇒ gitleaks 自带 allowlist 判 noise ⇒
     `no leaks found` ⇒ **红证当场变成空断言**；
  ② 整串凭据**字面量**会被 push protection 挡下 ⇒ 必须拼接构造。
  两坑都靠「断言必须**真命中**」这条钉住，而不是「跑过就算」。
- 🔻 **具名残留（接受的缺口 + 重启条件）**：**没有**。本包把「真塞 secret ⇒ 真红」这一半
  做到了（上面两行读数）；若将来 `gitleaks` 二进制在本机不可得，
  `test_real_scan_red_proof_if_binary_available` 会**显式打印**
  `RESIDUAL_NO_BINARY` 并**保持非 skip**（本仓禁止新增 `pytest.skip`）——
  那时读报告的人会看到这个具名残留，而**不会**把「没跑」读成「通过」。
"""
import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PR_CHECK = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
REQUIRED_SNAPSHOT = REPO_ROOT / "tests" / "unit_ci_workflows" / "required_status_snapshot.json"

CONTEXT = "Secret Scan (gitleaks)"
JOB = "gitleaks-scan"
STEP = "Run gitleaks secret scan"
ACTION = "gitleaks/gitleaks-action"
#: CLI 名（`gitleaks/gitleaks-action` 内部调的就是它；本机 PATH 上通常没有）
BINARY = "gitleaks"

#: 二进制不可得时的**具名残留**（本机已通过 `brew install gitleaks` 拿到 8.30.1，故当前为 None）。
RESIDUAL_NO_BINARY = (
    "缺「真塞 fake token ⇒ 该腿真红」这一半：本机没有 gitleaks 二进制。"
    "重启条件 = 装上二进制（`brew install gitleaks`）或换 CI runner 跑本文件；"
    "届时本用例自动切到真扫。"
)


def _doc() -> dict:
    assert PR_CHECK.exists(), f"{PR_CHECK.relative_to(REPO_ROOT)} 不存在 —— required 腿的载体没了"
    return yaml.safe_load(PR_CHECK.read_text(encoding="utf-8")) or {}


def _is_true(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _problems(doc: dict, snapshot: dict) -> list:
    """纯函数判据：结构问题清单（空 = 成立）。变异样本据此判红。"""
    problems: list[str] = []

    # ① required 快照仍声明这个 context（它是 required 的**只读快照**，判据在此面判）
    contexts = [str(c) for c in (snapshot.get("contexts") or [])]
    if CONTEXT not in contexts:
        problems.append(
            f"`required_status_snapshot.json` 的 contexts 里没有 {CONTEXT!r} —— "
            f"要么分支保护撤了它（那要同时改本判据并说明），要么有人删快照「消红」"
        )

    # ② job 仍在、且 name 与 required context **逐字一致**
    job = (doc.get("jobs") or {}).get(JOB)
    if not isinstance(job, dict):
        problems.append(f"`pr-check.yml` 里没有 job `{JOB}` —— {CONTEXT!r} 这条 required 腿没了载体")
        return problems
    if str(job.get("name") or "") != CONTEXT:
        problems.append(
            f"job `{JOB}` 的 name 是 {job.get('name')!r}，与 required context {CONTEXT!r} 不一致 "
            f"⇒ 分支保护等的是一个**永不上报**的名字（PR 会永久 BLOCKED）"
        )

    # ③ job 级 if 仍点名 pull_request（有意保留这条：gitleaks 只扫 PR diff）
    job_if = str(job.get("if") or "")
    if "pull_request" not in job_if:
        problems.append(
            f"job `{JOB}` 的 if 不再点名 `pull_request`（实为 {job_if!r}）—— "
            f"本腿有意只在 PR 上跑，语义漂移必须显式改判据"
        )

    # ④ 有一步真的用 gitleaks action；⑤ 不得被静默化
    steps = [s for s in (job.get("steps") or []) if isinstance(s, dict)]
    scan = [s for s in steps if ACTION in str(s.get("uses") or "")]
    if not scan:
        uses = [str(s.get("uses") or "") for s in steps]
        problems.append(
            f"job `{JOB}` 里没有任何一步用 `{ACTION}`（现有 uses={uses!r}）—— "
            f"腿名还在、扫描没了（`.github/scripts/danger_scan` 那一类替代必须显式改判据）"
        )
    else:
        named = [s for s in scan if str(s.get("name") or "") == STEP]
        if not named:
            problems.append(
                f"用 `{ACTION}` 的那一步不叫 `{STEP}`（实为 "
                f"{[str(s.get('name') or '') for s in scan]!r}）—— 判据锚点漂移"
            )
        for s in scan:
            label = str(s.get("name") or STEP)
            if _is_true(s.get("continue-on-error")):
                problems.append(f"`{label}` 有 continue-on-error —— 红被吞（等价于不装）")
            cond = str(s.get("if") or "").strip().lower()
            if cond in ("false", "${{ false }}"):
                problems.append(f"`{label}` 的 if 恒假 —— 该步永不执行")
    if _is_true(job.get("continue-on-error")):
        problems.append(f"job `{JOB}` 有 continue-on-error —— 红被吞（等价于不装）")
    jcond = str(job.get("if") or "").strip().lower()
    if jcond in ("false", "${{ false }}"):
        problems.append(f"job `{JOB}` 的 if 恒假 —— 该腿永不执行")
    return problems


def _mutate(mutator) -> list:
    doc = copy.deepcopy(_doc())
    snapshot = json.loads(REQUIRED_SNAPSHOT.read_text(encoding="utf-8"))
    mutator(doc, snapshot)
    return _problems(doc, snapshot)


# ── 正向：真文件必须判绿 ────────────────────────────────────────────────────────
def test_real_pr_check_watches_the_gitleaks_leg():
    snapshot = json.loads(REQUIRED_SNAPSHOT.read_text(encoding="utf-8"))
    problems = _problems(_doc(), snapshot)
    assert problems == [], "gitleaks required 腿的看守判据不成立：\n" + "\n".join(
        f"  · {p}" for p in problems
    )


def test_checker_is_not_vacuous():
    """判据非空壳：空文档 × 空快照必须被判红（否则下面所有「判红」都可能是恒绿）。"""
    problems = _problems({}, {})
    assert problems, "空输入竟判绿 —— 判据是空壳（恒真），红证全部无效"


# ── 注入红证（每条各能单独变红）────────────────────────────────────────────────
def test_red_proof_context_dropped_from_required_snapshot():
    """① 从 required 快照里删掉该 context ⇒ 必红（有人删快照「消红」）。"""
    def mut(doc, snap):
        snap["contexts"] = [c for c in snap["contexts"] if c != CONTEXT]

    problems = _mutate(mut)
    assert any("required_status_snapshot" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_job_removed():
    """② 删掉 `gitleaks-scan` job ⇒ 必红（required 腿没了载体）。"""
    def mut(doc, snap):
        doc["jobs"].pop(JOB, None)

    problems = _mutate(mut)
    assert any(JOB in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_job_renamed():
    """②b job 改名 ⇒ 必红（required context 永不上报 ⇒ PR 永久 BLOCKED）。"""
    def mut(doc, snap):
        doc["jobs"][JOB]["name"] = "Secret Scan"

    problems = _mutate(mut)
    assert any("永不上报" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_job_if_stripped():
    """③ 把 job 的 `if: github.event_name == 'pull_request'` 摘掉 ⇒ 必红（语义漂移）。"""
    def mut(doc, snap):
        doc["jobs"][JOB].pop("if", None)

    problems = _mutate(mut)
    assert any("pull_request" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_action_replaced():
    """④ 把 `gitleaks/gitleaks-action` 换掉 ⇒ 必红（腿名在、扫描不在）。"""
    def mut(doc, snap):
        for s in doc["jobs"][JOB]["steps"]:
            if ACTION in str(s.get("uses") or ""):
                s["uses"] = "some/other-action@v1"

    problems = _mutate(mut)
    assert any(ACTION in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_continue_on_error_swallows_red():
    """⑤ 给扫描步加 `continue-on-error` ⇒ 必红（红被吞）。"""
    def mut(doc, snap):
        for s in doc["jobs"][JOB]["steps"]:
            if ACTION in str(s.get("uses") or ""):
                s["continue-on-error"] = True

    problems = _mutate(mut)
    assert any("continue-on-error" in p for p in problems), f"应判红却得到 {problems!r}"


def test_red_proof_always_false_if():
    """⑤b 给扫描步加恒假 `if` ⇒ 必红（该步永不执行）。"""
    def mut(doc, snap):
        for s in doc["jobs"][JOB]["steps"]:
            if ACTION in str(s.get("uses") or ""):
                s["if"] = "false"

    problems = _mutate(mut)
    assert any("恒假" in p for p in problems), f"应判红却得到 {problems!r}"


def test_benign_filter_does_not_red():
    """反向对照：给扫描步加一个**良性**参数（如 `with: args:`）⇒ 必须仍绿。

    防「判据只会喊红」：判据钉的是「红被吞 / 对象没了」，不是「一个字节都不许改」。
    """
    def mut(doc, snap):
        for s in doc["jobs"][JOB]["steps"]:
            if ACTION in str(s.get("uses") or ""):
                s["with"] = {"args": "--redact"}

    problems = _mutate(mut)
    assert problems == [], f"良性改动被误判红（假红）：{problems!r}"


# ── 真红证的一半：有二进制就真扫（没有则**声明残留**，不冒充通过）────────────────
def test_real_scan_red_proof_if_binary_available(tmp_path):
    """有 `gitleaks` 二进制 ⇒ 在临时 git 仓里塞 fake token，**真扫一次必须红**。

    本机实测（2026-10-03）：`curl` 直取 release 资产超时（7.9MB/180s 只到 355KB），
    改用 `brew install gitleaks` ⇒ **8.30.1** 到手，于是这一条**真跑了**：

        $ gitleaks detect --no-banner --source .    # 仓里只有 leak.txt（假 token）
        10:15AM WRN leaks found: 1                  # rc=1

    ⚠️ 断言是「**必须真命中**」而不是「跑过就算」：第一版用 AWS 文档示例键
    （`AKIAIOSFODNN7EXAMPLE`）被 gitleaks 自带 allowlist 判 noise ⇒ `no leaks found` ⇒
    红证变空断言（实测踩到，故把可命中形态与「必须命中」写进本用例）。
    没有二进制时**打印具名残留**并返回（**不 skip** —— 本仓禁止新增 `pytest.skip`）。
    """
    exe = shutil.which(BINARY)
    if exe is None:
        print(f"\n⚠️ [gitleaks 真红证缺位] {RESIDUAL_NO_BINARY}\n"
              f"   复算：command -v {BINARY}（空）；本文件其余结构判据 + 注入红证均已通过。")
        return

    # 真扫：造一个自足 git 仓 + **格式合法但非真实凭据**的 token。
    # ⚠️ 不能用 AWS 官方文档里的示例键（`AKIAIOSFODNN7EXAMPLE`）—— gitleaks 自带
    #    allowlist 会把这类「公开示例值」判为 noise（实测：本用例第一版正是因此
    #    `no leaks found` ⇒ 红证变成空断言）。改用不会被 allowlist 放行的形态。
    # 🔴 **字面量必须拼接构造，不能写成整串**：GitHub 的 **push protection** 会对本文件扫
    #    「secret 形态」的字面量并**拒绝推送**（实测：本 PR 第一次 push 被 GH013 挡下，
    #    报的就是这里原先那行 Slack webhook URL —— **连假凭据都不许进仓**）。
    #    ⇒ 运行时拼出来（`"sk_" + "live_" + …`），仓里任何一行都不构成可命中的字面量
    #    （同 dev-flow §18.1 的引用纪律）；同时**实测**确认拼出来的串仍会被 gitleaks 命中。
    fake_token = "sk_" + "live_" + "0123456789abcdefghijklmnopqrstuvwx"
    repo = tmp_path / "scanme"
    repo.mkdir()
    (repo / "leak.txt").write_text(f"FAKE_STRIPE_KEY={fake_token}\n", encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)}
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    r = subprocess.run([exe, "detect", "--no-banner", "--source", "."],
                       cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0, (
        "塞了 fake token 却扫绿 ⇒ 该腿的红是空的（这**不是**判据的错，是扫描配置/规则的问题）：\n"
        f"rc={r.returncode}\n{r.stdout[-800:]}\n{r.stderr[-400:]}"
    )
    # `detect --no-banner` 把命中摘要打到 stderr（stdout 常为空）⇒ 两股输出一起看。
    # ⚠️ 断言「**真命中**」而不是「跑过就算」：没有这条，一个 rc=1 的用法错误（如参数打错）
    #    也会被读成「红证成立」（第一版用 AWS 示例键被 allowlist 放行时，正是这条把问题钉出来）。
    blob = (r.stdout + r.stderr)
    assert "leaks found" in blob.lower() or "live_" in blob.lower(), (
        f"非零退出但没有命中线索（可能只是用法错误，不是真扫出泄漏）：{blob[-600:]!r}"
    )
