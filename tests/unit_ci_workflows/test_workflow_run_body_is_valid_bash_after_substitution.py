# case_ids: MC-108
"""**workflow 的 `run:` 正文「表达式替换后必须是合法 bash」+「`${{ github.<prop> }}` 必须真实存在」**（issue #7029）。

## 病（真机，2026-10-16；不是推断）

`deploy-admin-api` run `38856179423`（head `250db08`）逐字：

```
RUN_STARTED_AT:                                              ← env 的值是**空的**（runner 在跑脚本前打印）
  echo "::error::… 它必须来自 context \\`\\\\`（本步 env）；…"       ← **替换后**的渲染正文
/home/runner/work/_temp/<uuid>.sh: line 9: unexpected EOF while looking for matching ``'
##[error]Process completed with exit code 2.
```

⇒ **两个独立缺陷叠在一起**：

1. `${{ github.run_started_at }}` 里的 `run_started_at` **不是**合法的 `github` 上下文属性
   （官方属性表 40 个里没有它）⇒ Actions 把它解成**空串**（不报错、不告警）；
2. 那句报错文案里「转义反引号 + 表达式」在**空替换**之后只剩一个**裸露的反引号**
   ⇒ bash 在**解析阶段**就死（exit 2）⇒ 新加的 `if [ -z … ]; then … exit 1; fi` **一次都没跑过**。

⇒ 那次红**不是**判据在说「取值源没接」（那会 exit 1），而是**脚本自己崩了**：
**判据的面被自己的文案毁掉，归因被指向错的对象**。

## 本文件的两条类级判据（跑**全仓所有 workflow 的每个 `run:`**，不是只盯自己那两个文件）

| # | 判据 | 为什么是它 |
|---|---|---|
| A | `run:` 正文把 `${{ … }}` 替换成**空串**（未知属性/空值的忠实模型）与**哨兵值**后，`bash -n` 必须干净 | **这条如果当时就有，本次故障不会发生** |
| B | `${{ github.<prop> }}` 的 `<prop>` 必须落在**官方属性白名单**（冻结清单 + 出处 + 复算命令）内 | `run_started_at` 不在其中 ⇒ 本次病灶必红 |

两条各有**注入式自证**（把当时的坏形态注回去 ⇒ 必须红；未注入的对照臂 ⇒ 不红）。
没有自证的话，「扫不到任何东西」也能恒绿 —— 那正是本仓点名的**空跑形态**。

同族第三条（`$GITHUB_*` **环境变量**命名空间：编造的名字必须判红）在
`tests/unit_ci_workflows/test_served_version_verify.py::test_workflow_run_bodies_never_expand_undefined_github_env_literals`
（它早于本文件存在）。**三个命名空间合起来**才封得住「猜名字」这件事：
环境变量面（`$GITHUB_*`）× 上下文属性面（`${{ github.* }}`）× 脚本可解析面（替换后仍是合法 bash）。

## 边界（照实登记，不粉饰）

- **空替换是「最坏值」模型**：它证「**空**值不会让脚本崩」，**不证**「非空值不会让脚本崩」
  （如未加引号的取值里带空格/引号）。哨兵臂**部分**覆盖后者 —— 哨兵是**刻意保守**的无特殊字符值
  （`X_SENTINEL_X`），以免引入假阳性（现取全仓 0 假阳性：空臂只命中病灶那 2 处）。
- **白名单只覆盖 `github.*` 命名空间**：`steps.*` / `needs.*` / `inputs.*` / `matrix.*` / `env.*`
  **不在射程内**（没有可冻结的权威属性表）。`github[...]` 方括号取值形态**显式判红**
  （那不是「白名单外」，而是**绕过点名的形态** ⇒ 要求改用点号形态）。
- **注释也算在内**：`run:` 正文里的 shell 注释**是**正文的一部分（Actions 一样会替换其中的表达式）
  ⇒ 注释里提到一个不存在的属性同样会被判红（这是**有意**的：注释里写错名字会把下一个人带沟里）。

## 判据 = 本文件；用例 = `MC-108`
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# `${{ … }}`（Actions 表达式）。取值用**花括号定界**，**不用引号定界的捕获组** ——
# 后者属本仓元守卫要求登记的形态（issue #6750），本文件不引入。
EXPR_RE = re.compile(r"\$\{\{(.*?)\}\}", re.S)

# `github` 上下文的**官方属性白名单**（冻结清单）。
#
# 出处：github/docs `content/actions/reference/workflows-and-actions/contexts.md`
#       的 `## \`github\` context` 一节（现取 **40** 个属性）。
# 复算命令（与下面这份清单逐项对齐；改了清单必须重跑它）：
#   curl -s https://raw.githubusercontent.com/github/docs/main/content/actions/reference/workflows-and-actions/contexts.md \
#     | sed -n '/## `github` context/,/^## /p' | grep -oE 'github\.[a-z_0-9]+' | sort -u
#
# 🔴 **`run_started_at` 不在其中** —— issue #7029 就是踩了这个名字：Actions 对「不存在的属性」
#    解出**空串**（不报错、不告警）⇒ 取值静默为空而全链路没有一物会红。
GITHUB_CONTEXT_PROPS = frozenset({
    "action", "action_path", "action_ref", "action_repository", "action_status",
    "actor", "actor_id", "api_url", "artifacts", "artifacts_list",
    "base_ref", "env", "event", "event_name", "event_path",
    "graphql_url", "head_ref", "job", "path", "ref",
    "ref_name", "ref_protected", "ref_type", "repository", "repository_id",
    "repository_owner", "repository_owner_id", "retention_days", "run_attempt", "run_id",
    "run_number", "secret_source", "server_url", "sha", "token",
    "triggering_actor", "workflow", "workflow_ref", "workflow_sha", "workspace",
})

# 反空跑锚点：白名单**只许因官方文档变化而增删**。这几条是任何版本的表里都有的，
# 少了它们说明清单被清空/抄坏了（那时判据 B 会因为「白名单里什么都没有」而恒红，
# 或者反过来 —— 有人把 `run_started_at` 加进去就恒绿 ⇒ 必须锚住）。
GITHUB_CONTEXT_PROPS_ANCHORS = frozenset({
    "sha", "ref", "event_name", "run_id", "run_number", "repository", "workspace",
})

# GitHub 的替换模型：**不分引号**，一律把 `${{ … }}` 换成它的值。
PLACEHOLDER_EMPTY = ""                  # 未知属性 / 空值 = **最坏值**（忠实模型，本次病灶靠它才现形）
PLACEHOLDER_SENTINEL = "X_SENTINEL_X"   # 保守的非空值（无特殊字符 ⇒ 不引入假阳性）

# issue #7029 的**改前逐字形态**：替换后 = 「转义反引号 + 空串 + 转义反引号」⇒ 只剩后一个裸反引号 ⇒ parse 死。
REGRESSION_SNIPPET = (
    'echo "::error::RUN_STARTED_AT 为空 ⇒ 取值源未接（issue #7015）：'
    '它必须来自 context \\`\\${{ github.run_started_at }}\\`（本步 env）；不许用未定义的环境变量名"'
)


# ── 取样面：用 **YAML 解析**取 `run:` 正文（不靠缩进抠文本 —— 抠文本会在缩进变化时静默漏扫）──

def _runs_in(wf_dir: pathlib.Path) -> list[tuple[str, str, str, str]]:
    """返回 (workflow 文件名, job 名, 步名, run 正文)。"""
    out: list[tuple[str, str, str, str]] = []
    for path in sorted(wf_dir.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in (job.get("steps") or []):
                if isinstance(step, dict) and isinstance(step.get("run"), str):
                    out.append((path.name, job_name, step.get("name") or "(未命名步)", step["run"]))
    return out


def _substitute(script: str, value: str) -> str:
    return EXPR_RE.sub(value, script)


def _bash_n(script: str) -> tuple[int, str]:
    proc = subprocess.run(["bash", "-n"], input=script, capture_output=True, text=True)
    return proc.returncode, (proc.stderr or "").strip()


def _unparsable(substitution: str, wf_dir: pathlib.Path | None = None) -> list[str]:
    """替换成 `substitution` 后 `bash -n` 不过的 `run:` ⇒ 具名（workflow / job / 步名 / bash 原文）。"""
    bad: list[str] = []
    for wf, job, step, run in _runs_in(wf_dir or WORKFLOW_DIR):
        rc, err = _bash_n(_substitute(run, substitution))
        if rc != 0:
            first = err.splitlines()[0] if err else "(无 stderr)"
            bad.append(f"{wf} :: {job} :: {step} :: bash -n rc={rc} :: {first}")
    return bad


def _context_prop_offenders(wf_dir: pathlib.Path | None = None) -> list[str]:
    """`${{ github.<prop> }}` 里不在白名单的 `<prop>`（含 `github[...]` 方括号绕道形态）。"""
    bad: list[str] = []
    for wf, job, step, run in _runs_in(wf_dir or WORKFLOW_DIR):
        for match in EXPR_RE.finditer(run):
            expr = match.group(1)
            if "github[" in expr:
                bad.append(f"{wf} :: {job} :: {step} :: `github[...]` 方括号取值形态（绕过白名单点名）")
                continue
            for prop in re.findall(r"github\.([A-Za-z_][A-Za-z0-9_]*)", expr):
                if prop not in GITHUB_CONTEXT_PROPS:
                    bad.append(f"{wf} :: {job} :: {step} :: github.{prop}")
    return bad


# ── 判据 A：替换后必须是合法 bash ────────────────────────────────────────────

def test_every_run_body_stays_valid_bash_after_expression_substitution():
    """🔴 判据 A（issue #7029）：**每条 `run:` 正文**在表达式替换成空串/哨兵值后都必须过 `bash -n`。

    为什么两个替换值都要跑：空串是「未知属性 / 空值」的忠实模型（本次病灶只有它能现形），
    哨兵值覆盖「非空值」那一半（刻意保守，避免假阳性）。
    """
    offenders = _unparsable(PLACEHOLDER_EMPTY) + _unparsable(PLACEHOLDER_SENTINEL)
    assert not offenders, (
        "下列 workflow 的 `run:` 正文在**表达式替换后**不是合法 bash ⇒ 该步会在**解析阶段**就死"
        "（exit 2），步内任何自检/判据都**没有机会执行**（issue #7029 的形态；"
        "真机读数：`bash: line 9: unexpected EOF while looking for matching \\``\\''）:\n  "
        + "\n  ".join(offenders)
        + "\n⇒ 修法：文案里不要出现裸反引号/`${{ }}`；需要给读者看的表达式用**纯文本**写成"
          "「当前取值源 = …」。【先把注错的那行贴进 `bash -n` 复现，再改】"
    )


def test_expression_substitution_guard_has_teeth(tmp_path):
    """**判别力自证**（注入式）：把改前逐字形态注回去 ⇒ 判据 A 必须红；未注入的对照臂 ⇒ 不红。

    没有这一条，判据 A 可以「因为扫不到任何东西」而恒绿（本仓点名的空跑形态）。
    """
    source = (WORKFLOW_DIR / "deploy-admin-api.yml").read_text(encoding="utf-8")
    anchor = "          SHA=$(git rev-parse HEAD)"
    assert source.count(anchor) == 1, "注入锚点漂了（解算步的 SHA 行不再唯一）⇒ 本自证是空跑"
    injected = source.replace(anchor, anchor + "\n          " + REGRESSION_SNIPPET, 1)
    assert injected != source, "注入没生效 ⇒ 本自证是空跑"

    victim_dir = tmp_path / "workflows"
    victim_dir.mkdir()
    (victim_dir / "deploy-admin-api.yml").write_text(injected, encoding="utf-8")

    found = _unparsable(PLACEHOLDER_EMPTY, victim_dir)
    assert found, (
        "注入「转义反引号 + 表达式」的**改前逐字形态**却**没**被判据 A 报出 ⇒ 守卫不具判别力"
        "（本自证正是「如果当时有这条判据，故障不会发生」的证明）"
    )
    assert any("unexpected EOF" in line for line in found), (
        f"报出了，但理由不是「反引号未配对」⇒ 判据钉错了东西：{found}"
    )

    # 对照臂：未注入的本树 ⇒ 不报（否则判据 A 是假阳性源）
    assert not _unparsable(PLACEHOLDER_EMPTY, WORKFLOW_DIR), (
        "对照臂：未注入的本树被报出解析失败 ⇒ 判据 A 有假阳性"
    )


# ── 判据 B：`${{ github.<prop> }}` 必须在官方白名单里 ────────────────────────

def test_github_context_properties_used_in_run_bodies_exist():
    """🔴 判据 B（issue #7029）：`run:` 正文里用到的 `${{ github.<prop> }}` 必须在官方属性表内。

    Actions 对**不存在的属性**解出**空串**（不报错、不告警）⇒ 那是「猜名字」的隐形地雷：
    issue #7015 猜的是环境变量名 `GITHUB_RUN_STARTED_AT`，issue #7029 猜的是属性名 `github.run_started_at`，
    两次都静默取到空串。⇒ 本判据把「属性名必须真实存在」变成一条会红的断言。
    """
    offenders = sorted(set(_context_prop_offenders()))
    assert not offenders, (
        "下列 `${{ github.<prop> }}` 的 `<prop>` **不在**官方 `github` 上下文属性表（40 个）里"
        "⇒ Actions 解出**空串**、不报错也不告警（issue #7029 的病灶）:\n  "
        + "\n  ".join(offenders)
        + "\n⇒ 要么改用真实属性（复算清单见本文件顶部命令），要么改成**不依赖名字**的取值"
          "（例如 `builtAt` 用 runner 时钟 `date -u +%Y-%m-%dT%H:%M:%SZ`）。"
    )


def test_github_context_property_allowlist_is_anchored():
    """反空跑：白名单必须**含**那几个任何版本都有的属性（防被清空 / 被抄坏 / 被顺手加进编造的名字）。"""
    missing = sorted(GITHUB_CONTEXT_PROPS_ANCHORS - GITHUB_CONTEXT_PROPS)
    assert not missing, (
        f"官方属性白名单缺了锚点属性 {missing} ⇒ 说明这份清单被改坏了（它必须与官方表逐项对齐）"
    )
    assert "run_started_at" not in GITHUB_CONTEXT_PROPS, (
        "有人把 `run_started_at` 加进了白名单 ⇒ 判据 B 对本次病灶**恒绿**（白名单只许因官方文档变化而增删）"
    )


def test_github_context_property_guard_has_teeth(tmp_path):
    """**判别力自证**（注入式）：把 `${{ github.run_started_at }}` 注回去 ⇒ 判据 B 必须红。"""
    source = (WORKFLOW_DIR / "deploy-admin-api.yml").read_text(encoding="utf-8")
    anchor = "          SHA=$(git rev-parse HEAD)"
    assert source.count(anchor) == 1, "注入锚点漂了 ⇒ 本自证是空跑"
    injected = source.replace(
        anchor, anchor + '\n          echo "取值源 = ${{ github.run_started_at }}"', 1
    )
    assert injected != source, "注入没生效 ⇒ 本自证是空跑"

    victim_dir = tmp_path / "workflows"
    victim_dir.mkdir()
    (victim_dir / "deploy-admin-api.yml").write_text(injected, encoding="utf-8")

    found = _context_prop_offenders(victim_dir)
    assert any("github.run_started_at" in line for line in found), (
        f"注入编造的 context 属性却**没**被判据 B 报出 ⇒ 守卫不具判别力；实得 {found}"
    )
    assert not _context_prop_offenders(WORKFLOW_DIR), (
        "对照臂：未注入的本树被报出白名单外属性 ⇒ 判据 B 有假阳性"
    )


# ── 形态守卫：两个判据的取样面本身不能是空跑 ────────────────────────────────

def test_guard_really_scans_the_run_bodies():
    """反空跑：取样面必须真的覆盖到全仓的 `run:` 正文（否则上面两条判据是「扫了个空气」）。"""
    runs = _runs_in(WORKFLOW_DIR)
    assert len(runs) >= 100, f"只扫到 {len(runs)} 个 run 正文 ⇒ 取样面塌了（YAML 解析口径变了？）"
    wf_names = {r[0] for r in runs}
    for must in ("deploy-admin-api.yml", "deploy-frontend.yml", "pr-check.yml"):
        assert must in wf_names, f"取样面漏了 {must} ⇒ 判据没覆盖到该腿"
    with_expr = sum(1 for r in runs if "${{" in r[3])
    assert with_expr >= 20, f"含表达式的 run 正文只有 {with_expr} 个 ⇒ 判据 A/B 的替换面塌了"
