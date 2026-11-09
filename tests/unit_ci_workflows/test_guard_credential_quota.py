# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012）
"""判定面凭据（issue #8847，2026-11-09 owner 裁定①「加凭据」）—— PAT + 内置回落 的类级判据。

## 病（一类缺陷，不是一处红）

`github.token`（Actions 安装令牌）的配额是**每仓每小时 1000 次**。本仓实测 **3 条 PR 并发**
就打穿（#8847 现场：`Contribution Gate` / `External Authorship Guard` / `Secret Scan` /
`Danger Scan` / `QA Growth Gate` **同时** `exit 3`，而 `exit 3` 是「判不了」的 fail-closed 正确语义
—— 它在 PR 上**长得和真红一模一样**，只能靠日志里的 `HTTP 403` / `x-ratelimit-remaining=0` 区分）。

修法（owner 裁定①）：给这些守卫**换高配额凭据**（用户配额 5000 次/小时，与安装令牌**不同窗口**）。
**但不能裸用 PAT**：fork PR 拿不到 secrets ⇒ 会因空 token 全红。⇒ 唯一正确形态是**回落**：

    ${{ secrets.AUTOMERGE_PAT || secrets.GITHUB_TOKEN }}

## 本文件钉的四条（每条都有注入式红证）

1. **每个内置凭据引用都带 PAT 回落**（不许出现裸 `secrets.GITHUB_TOKEN` 作为唯一来源）；
2. **回落形态是 `||`**（PAT 不许单独出现 —— 那正是 fork 全红的形态）；
3. `actions/github-script` 的评论步也走同一凭据（评论步是 403 的高发点）；
4. **凭据不许被 echo / 打日志**（public 仓的 job 日志全员可见）。

## 边界（照实登记，§19.1）

- 本判据证明「接线形态正确」，**不证明** PAT 在某个具体时刻有配额（那是运行期读数）；
- 它也不证明 fork 场景真的回落到内置（那要真跑一次 fork PR —— 本仓禁止 fork 合并，
  这条只能由「`||` 形态 + GitHub 的 secrets 不投递语义」共同保证）。
"""
from __future__ import annotations

import re
from pathlib import Path

from unit_ci_workflows.injection import inject

REPO_ROOT = Path(__file__).resolve().parents[2]
PR_CHECK = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
CONTRIBUTION = REPO_ROOT / ".github" / "workflows" / "contribution-gate.yml"

FALLBACK = "secrets.AUTOMERGE_PAT || secrets.GITHUB_TOKEN"
BUILTIN = "secrets.GITHUB_TOKEN"
PAT = "secrets.AUTOMERGE_PAT"

#: 本包覆盖的两个文件（都是**判定面**：跑的是受信实现或纯 `gh` 调用）
GUARD_FILES = (PR_CHECK, CONTRIBUTION)


def _code_lines(text: str) -> list[str]:
    """去掉整行注释后的代码行（注释里要能自由地**讲**这条纪律，见文件头）。"""
    return [l for l in text.splitlines() if not l.lstrip().startswith("#")]


def _bare_builtin_lines(text: str) -> list[str]:
    """内置凭据引用里**没有** PAT 回落的那些行（= 违反判据 1 的形态）。"""
    return [l for l in _code_lines(text) if BUILTIN in l and FALLBACK not in l]


#: 只读「有没有这枚 secret」的**存在性比较**（不是把凭据当令牌用）—— 不算裸用。
_PRESENCE_ONLY = re.compile(r"secrets\.AUTOMERGE_PAT\s*(?:!=|==)\s*''")


def _bare_pat_lines(text: str) -> list[str]:
    """PAT 引用里**没有**内置回落的那些行（= fork PR 会因空 token 全红的形态）。

    排除「存在性比较」那一类（`secrets.AUTOMERGE_PAT != ''`）：它只产出**非密布尔**，
    不是把凭据当令牌交给某个步骤（判据 5 要的正是这种读数）。
    """
    return [l for l in _code_lines(text)
            if PAT in l and FALLBACK not in l and not _PRESENCE_ONLY.search(l)]


def _token_echo_lines(text: str) -> list[str]:
    """把凭据打进日志的形态（echo / print / set -x / env 全量输出）。"""
    bad = []
    for line in _code_lines(text):
        if not re.search(r"\$\{\{\s*secrets\.|GH_TOKEN|GITHUB_TOKEN", line):
            continue
        if re.search(r"\becho\b", line) and re.search(r"\$\{?\(?(secrets\.|GH_TOKEN|GITHUB_TOKEN)", line):
            bad.append(line)
        if re.search(r"^\s*set\s+-x\b", line):
            bad.append(line)
        if re.search(r"\benv\s*\|\s*(grep|cat)\b", line):
            bad.append(line)
    return bad


def test_every_builtin_token_reference_has_the_pat_fallback():
    """判据 1：内置凭据只许作为**回落**出现，不许是唯一来源（issue #8847）。"""
    for path in GUARD_FILES:
        bare = _bare_builtin_lines(path.read_text(encoding="utf-8"))
        assert bare == [], (
            f"{path.name}：这些行仍以 `{BUILTIN}` 为唯一凭据 ⇒ 配额打穿时整条守卫 `exit 3`"
            f"（#8847 的形态）。改成 `{FALLBACK}`：\n" + "\n".join(bare)
        )


def test_pat_is_never_used_without_the_builtin_fallback():
    """判据 2：PAT 必须带 `||` 回落 —— 否则 fork PR（拿不到 secrets）全红。"""
    for path in GUARD_FILES:
        bare = _bare_pat_lines(path.read_text(encoding="utf-8"))
        assert bare == [], (
            f"{path.name}：`{PAT}` 没有 `||` 回落 ⇒ fork PR 会拿到空 token（全红）。"
            f"违反行：\n" + "\n".join(bare)
        )


def test_both_guard_workflows_actually_carry_the_high_quota_credential():
    """判据 3 的前置：两个判定面文件**真的**接上了高配额凭据（防「判据在，接线没了」）。"""
    pr = PR_CHECK.read_text(encoding="utf-8")
    cg = CONTRIBUTION.read_text(encoding="utf-8")
    # pr-check：10 处 env（External Authorship / ci-helper / 清零声明 / Case Coverage /
    # QA Growth / gitleaks ×2 / danger ack / label ×2）+ 2 处 github-script 的 github-token
    assert pr.count(FALLBACK) >= 12, f"pr-check.yml 的回落接线少了：{pr.count(FALLBACK)}"
    assert cg.count(FALLBACK) == 2, f"contribution-gate.yml 的回落接线数变了：{cg.count(FALLBACK)}"


def test_github_script_comment_steps_use_the_high_quota_credential():
    """判据 3：`actions/github-script` 的评论步显式传高配额凭据（评论步是 403 高发点）。"""
    text = PR_CHECK.read_text(encoding="utf-8")
    chunks = text.split("uses: actions/github-script@")[1:]
    assert len(chunks) == 2, f"github-script 步数变了（{len(chunks)}）⇒ 本判据可能已空跑"
    for chunk in chunks:
        head = chunk[:400]
        assert "github-token:" in head and FALLBACK in head, (
            "github-script 步没有显式给高配额凭据 ⇒ 默认吃内置令牌，限流时评论步 403：\n" + head
        )


def test_credential_source_readout_is_present():
    """凭据**来源**必须可观测：回落形态让 PAT/内置在日志里同形 ⇒ 必须有非密读数（§18.6）。

    没有这条读数时，「PAT 生效了」与「PAT 是空的、一直在回落内置」**长得一模一样** ——
    #8847 的修法就变成不可验证的。读数只能是布尔，**不许**打凭据本身。
    """
    text = CONTRIBUTION.read_text(encoding="utf-8")
    assert "secrets.AUTOMERGE_PAT != ''" in text, (
        "contribution-gate.yml 缺「凭据来源」布尔读数 ⇒ 无法判定 PAT 是否生效")
    assert "凭据来源读数" in text, "读数步被删了 ⇒ 本判据会红（不要静默删掉可观测面）"


def test_token_is_never_echoed_into_job_logs():
    """判据 4：public 仓的日志全员可见 —— 凭据不许被 echo / `set -x` / `env |` 打出来。"""
    for path in GUARD_FILES:
        bad = _token_echo_lines(path.read_text(encoding="utf-8"))
        assert bad == [], f"{path.name}：凭据可能进日志：\n" + "\n".join(bad)


# ── 注入式红证（`inject()` 保证「注入真的落上去了」，否则判据绿=空跑）──────────────


def test_red_proof_bare_builtin_is_caught():
    """红证 1：把一处的回落拆掉（只留内置）⇒ 判据 1 必须报红。"""
    text = PR_CHECK.read_text(encoding="utf-8")
    broken = inject(text, FALLBACK, BUILTIN, count=text.count(FALLBACK), where=PR_CHECK.name)
    assert broken != text, "注入未生效"
    assert _bare_builtin_lines(broken), "拆掉回落后判据 1 仍绿 ⇒ 它是空断言"


def test_red_proof_missing_fallback_is_caught():
    """红证 2：把一处的回落拆成**裸 PAT** ⇒ 判据 2 必须报红（fork 全红形态）。"""
    text = CONTRIBUTION.read_text(encoding="utf-8")
    broken = inject(text, FALLBACK, PAT, count=text.count(FALLBACK), where=CONTRIBUTION.name)
    assert _bare_pat_lines(broken), "裸 PAT 竟未被判红 ⇒ 判据 2 是空断言"


def test_red_proof_echoing_the_token_is_caught():
    """红证 3：在安全步里加一行 `echo $GH_TOKEN` ⇒ 判据 4 必须报红。"""
    text = PR_CHECK.read_text(encoding="utf-8")
    anchor = (
        "      - name: 拦截陌生账号 / fork 来源的 PR\n"
        "        env:\n"
        "          GH_TOKEN: $" + "{{ " + FALLBACK + " }}"
    )
    broken = inject(
        text,
        anchor,
        anchor + '\n        run: echo "$GH_TOKEN"',
        count=1,
        where=PR_CHECK.name,
    )
    assert _token_echo_lines(broken), "echo 凭据未被判红 ⇒ 判据 4 是空断言"
