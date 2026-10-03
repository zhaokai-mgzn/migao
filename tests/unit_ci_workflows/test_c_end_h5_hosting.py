# case_ids: MC-046
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式挂 MC-012；
#   本单是**新的一类**（C 端 H5 静态根落地面 + 「手动才发布」的触发面契约），按用例号顺延取 MC-046
#   （取号时**三轮**现取：写侧 = MC-039 → rebase 后被 main 上的 #5731 占 → 改 MC-040/041
#    又被在飞分支占 ⇒ 定 MC-046；口径 = main 已占 ∪ 在飞分支已占 之后的下一个空号）。）
r"""C 端小布 H5（`frontend/mini-app` 的 `build:h5` 产物）**静态根落地面**的常驻判据（issue #4184）。

## 病根（开工前现取复算，2026-09-27）

| 件 | 读数 |
|---|---|
| `curl -sI https://app.migaozn.com/js/app.js` 的 `Last-Modified` | `Sun, 30 Aug 2026 06:54:48 GMT`（比 `frontend/mini-app` 最近改动早 **28 天**） |
| 对照 B 端 `curl -sI https://app.migaozn.com/b/index.html` | `Sun, 27 Sep 2026 …`（今天的新构建） |
| `grep -rln '/opt/migao-deploy' .github/workflows/`（建腿前） | **0 命中** ⇒ C 端**没有任何部署通路** |
| ⇒ 结论 | 线上落后 28 天，而**没有任何东西会因此变红**（「C 端已部署」一直被当真） |

## 本守卫锁什么（每条都带注入式红证，见 `TestRedProofs`）

1. **通路存在**：`deploy/swas/c-end-h5-publish-remote.sh`（**发布逻辑单一出处**）、
   `deploy/scripts/c-end-h5-publish-ci.sh`（CI 包装）、`deploy/scripts/c-end-h5-verify-served.sh`
   （落地面断言）、`.github/workflows/c-end-h5-publish.yml` 四件齐备，且 workflow 的发布步骤调的是
   **那一份**远端执行体（不许把命令内联进 workflow 另写一份）；
2. 🔴 **合并本 PR 不会自动发布**（用户 2026-09-27 裁定 B）：`on.push.paths` **恰好**只含
   `frontend/mini-app/**`（不含 `deploy/**`，也不含 workflow 自身）**且**发布链路（发布/落地面断言两步）
   的 `if` 必须**逐字**要求 `github.event_name == 'workflow_dispatch'` **与** `inputs.publish == 'true'`
   ⇒ 对账面的兜底 dispatch（`workflow_dispatch`，不带 input）也**不会**发布；
   非手动触发时那条闸**判红并给出可复制命令**（不是静默 success —— 否则对账会把它读成「已发布」）；
3. 🔴 **红线：发布不得删除/覆盖 `w/`（工人端，线上有工人在用）与 `b/`（商家端）**：
   ① 结构层——`w` `b` 是远端脚本的**保留前缀**（`H5_RESERVED_PREFIXES`），既不许进产物顶层条目、
      也不许进托管清单；② 产物层——本腿 `index.html` 不许引用 `/<保留前缀>/…`；
   ③ 自证层——发布前后逐子树的**规范化摘要**与各自的 `index.html` 单文件哈希必须**逐字相等**
      （CI 包装侧四条读数缺一即判红）；
4. **首次发布由人签字**：远端脚本对「无人认领的根」判 `TAKEOVER_REQUIRED`（exit 2）并打印将要替换的
   条目；CI 包装**不带**任何能绕过它的开关（它带 `H5_TAKEOVER_FIRST_PUBLISH=1` 只是为了让
   「已登记过的根」不再触发该闸 —— 清单不在线上时它照样接管不了、`InvocationStatus` 非 Success ⇒ 判红）；
5. **判据本体（新鲜度）翻成 gate**（同批）：`scripts/h5_freshness_guard.py` **默认**判红
   （`::error::` + exit 2），`--no-gate` 才是报告型；`h5-freshness-guard.yml` 的 dispatch 输入
   是**反向**的 `no_gate`，且 **⛔ 无 cron**（用户 2026-09-21 裁定，未被推翻）、
   `workflow_run` 清单里新增了本腿（发布完成后立刻重判）；
6. **对账面同批接线**（FM-E3）：`deploy-reconcile.yml` 有新腿 `c-end-h5`（走漂移判据 ②），
   且它在 `test_swas_deploy_ci_hardening.py::SVC_TO_DEPLOY_WORKFLOW` 登记册里；本腿**触发面 ≠ 对账面**
   的那两条缺口（发布链路自身的两个文件）逐条登记在 `reconcile_trigger_paths_ledger.json`，
   并标 `never_in_trigger`（= 明文禁止「把它们加进触发面来消账」这条出路）；
7. **行为层（沙箱跑真脚本）**：在 `tmp_path` 造一个「静态根」沙箱（含 `w/`、`b/` 与一个清单外的
   `robots.txt`）⇒ 真跑远端执行体：首次发布必须先要 `--takeover-first-publish`（否则什么都别动）、
   发布后 `w/` `b/` `robots.txt` **逐字节不变**、幂等、陈旧托管条目被收敛、越界/缺根/坏清单一律拒绝。

**⚠️ 本文件刻意分两层**：结构层读**真 YAML / 真脚本文本**（注入式红证）；行为层**真跑**
`deploy/swas/c-end-h5-publish-remote.sh`（本地目录直达，**不联网、不碰真实静态根**，沙箱在 `tmp_path`）。
「测试测的是另一份实现」这个形态结构上不可能出现。

## 边界（照实登记，别把「登记了」读成「治住了」）

- **本文件不验证线上**：真实发布（SWAS RunCommand + `curl https://app.migaozn.com`）由
  `.github/workflows/c-end-h5-publish.yml` 在**人手动触发**时跑；首次发布**尚未发生** ⇒
  `/` 的 `last-modified` 是否变化**没有**在本机取证（属「没跑」，不是「通过」）。
- 本机**没有** nginx / docker / aliyun CLI ⇒ 证明不了 `nginx -t`、也跑不了 `RunCommand` 那一段
  （`c-end-h5-publish-ci.sh` 的云调用只是结构判据的对象）。
- **覆盖面之外**（如实登记）：SWAS 静态根里除托管清单外的其它内容（例如 `robots.txt`、证书挑战目录）、
  nginx 层（本腿不改 `nginx.conf`，`location /` 的 fallback 由既有判据承担）、CDN 缓存、
  `/w/` `/b/` 之外的其它子目录（若将来出现第四条腿，它不在本文件的 `H5_RESERVED_PREFIXES` 判据里）、
  **回滚路径**（远端脚本只在**拷贝失败**时回滚，回滚前备份在本机 `mktemp` 目录里、随进程退出删除 ⇒
  「发布成功后发现问题」没有回滚动作，只能再发一次上一版）。
"""
from __future__ import annotations

import copy
import hashlib
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "c-end-h5-publish.yml"
REMOTE_SCRIPT = REPO_ROOT / "deploy" / "swas" / "c-end-h5-publish-remote.sh"
CI_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "c-end-h5-publish-ci.sh"
VERIFY_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "c-end-h5-verify-served.sh"
FRESHNESS_SCRIPT = REPO_ROOT / "scripts" / "h5_freshness_guard.py"
FRESHNESS_WF = REPO_ROOT / ".github" / "workflows" / "h5-freshness-guard.yml"
RECONCILE_WF = REPO_ROOT / ".github" / "workflows" / "deploy-reconcile.yml"
RECONCILE_LEDGER = REPO_ROOT / "tests" / "unit_ci_workflows" / "reconcile_trigger_paths_ledger.json"

WORKFLOW_NAME = "c-end-h5-publish.yml"
# 兜底面（`FM-E17` 收口口径）：cron 的**单一真值**在台账里，判据两边互钉
FALLBACK_LEDGER = REPO_ROOT / "tests" / "unit_ci_workflows" / "publish_leg_fallback_ledger.json"
WORKFLOW_DISPLAY_NAME = "Publish C-end H5 (app.migaozn.com 根)"
JOB = "publish"
PUBLISH_SCRIPT = "deploy/scripts/c-end-h5-publish-ci.sh"
# 🔴 第三层（#6095）：把 CI 构建出来的 dist 推成不可变 sha 的那条腿（孤儿单提交 → h5-dist）
DIST_PUSH_SCRIPT = "deploy/scripts/c-end-h5-dist-push.sh"
DIST_BRANCH = "h5-dist"
# 发布步的**产物 ref** 唯一合法来源 = dist 推送步的 step output（禁漂移 ref）
DIST_OUTPUT_REF = "steps.dist.outputs.sha"
# `git commit-tree` 的**不可替代形态**：不给 `-p` ⇒ 无父 ⇒ 孤儿（每次 force-push 只 1 个提交）
DIST_COMMIT_FORM = "git commit-tree \"$TREE\""
# 🔴 第四层（#6095 / run 37081920188）：孤儿提交必须**显式带身份** —— CI runner 上没有可用身份，
#   git 兜底出来的 name 是空串 ⇒ `fatal: empty ident name (for <runner@…>) not allowed`（exit 128）。
DIST_IDENT_NAME = "github-actions[bot]"
DIST_IDENT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
DIST_IDENT_FORM = 'GIT_AUTHOR_NAME="$IDENT_NAME" GIT_AUTHOR_EMAIL="$IDENT_EMAIL" \\'
# 「我在哪个仓 / 往哪推」不许由环境决定（同族：脚本继承了运行环境）
DIST_ENV_UNSET_FORM = "unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR"
VERIFY_SERVED = "deploy/scripts/c-end-h5-verify-served.sh"
MINI_APP_GLOB = "frontend/mini-app/**"
STATIC_ROOT = "/opt/migao-deploy/h5"
MANIFEST = ".migao-c-end-h5-manifest.json"
RESERVED = ("w", "b")
STRAY_GLOBS = ("deploy/**",)

# 发布链路自身的两个文件**永远不许**进 `on.push.paths`（见 ledger 的 `never_in_trigger`）
CHAIN_FORBIDDEN_IN_TRIGGER = (".github/workflows/c-end-h5-publish.yml", PUBLISH_SCRIPT,
                             DIST_PUSH_SCRIPT)

# 模式判定步（**唯一**决定「会不会发布」的地方）：它必须逐字包含这两条判据
MODE_STEP = "Resolve mode"
GATE_EVENT = "github.event_name"
GATE_INPUT = "inputs.publish"
MODE_PUBLISH = 'echo "mode=publish" >> "$GITHUB_OUTPUT"'
MODE_NOTIFY = 'echo "mode=notify" >> "$GITHUB_OUTPUT"'
PUBLISH_IF = "steps.mode.outputs.mode == 'publish'"
NOTIFY_IF = "steps.mode.outputs.mode != 'publish'"

DESTRUCTIVE_RE = re.compile(r"(rm\s+-[A-Za-z]*[rf][A-Za-z]*\b|--delete\b|-delete\b)")


# ── 读盘 / YAML（缺失即判据失败，不静默）──────────────────────────────────────

def _read(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): _file_sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def _on_key(wf: dict):
    """yaml 会把裸 `on:` 解析成布尔 True 键（同 test_bmini_h5_hosting.py 的处理）。"""
    return "on" if "on" in wf else True


def _triggers(wf: dict) -> dict:
    value = wf.get("on")
    if value is None:
        value = wf.get(True)
    return value if isinstance(value, dict) else {}


def _steps(wf: dict) -> list:
    job = (wf.get("jobs") or {}).get(JOB) or {}
    steps = job.get("steps")
    return steps if isinstance(steps, list) else []


def _run_text(step) -> str:
    return str((step or {}).get("run") or "")


def _if_text(step) -> str:
    return str((step or {}).get("if") or "")


def _live_lines(text: str) -> str:
    """只保留**非整行注释**的行，返回 `\n` 连接的可执行文本。

    口径与 `_unsanctioned_destructive_lines` 逐字一致：**只跳过整行注释**（`lstrip()` 后以 `#` 开头），
    **绝不**按 `#` 截断行（朴素截断会让字符串里的 `#` 吃掉行尾 ⇒ 假绿）。
    ⚠️ 为什么需要它：本文件的判据**必须能引用被判红的串**（否则讲课的注释会把自己判红）——
    实测自伤：注释里逐字写「`cat 远端脚本`」这一句就让本判据在真语料上判红。
    代价（照实登记）：**行尾注释里的裸串不算** ⇒ 若有人把内联写法**整行注释掉**，
    本判据不报 —— 但那行**不会执行**，不是本判据要拦的对象。
    """
    return "\n".join(
        raw for raw in text.splitlines()
        if raw.strip() and not raw.lstrip().startswith("#")
    )


def _unsanctioned_destructive_lines(text: str) -> list:
    """破坏性语句必须只指向受守卫的目标或自建临时目录（源码层红线）。

    ⚠️ 注释处理口径（`tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py` 同族）：
    **只跳过整行注释**，**绝不**按 `#` 截断行 —— 朴素截断会让字符串里的 `#` 吃掉行尾（假绿）。
    """
    hits = []
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if not DESTRUCTIVE_RE.search(raw):
            continue
        # 白名单（与 test_bmini_h5_hosting.py 同口径）：自建临时目录 / 变量名明确的临时文件
        # ⚠️ `$STATIC_ROOT/$name` 只出现在**受清单约束**的删除上（`$name` 来自
        #    `MANAGED ∩ 磁盘现值`，首次发布为空集）⇒ 它是本腿唯一的写盘删除动作。
        if any(tok in raw for tok in ("$TARGET", "$WORK", "$BACKUP", "$out_file", "$STATIC_ROOT/$name")):
            continue
        hits.append(raw.strip())
    return hits


# ── 结构层：发布腿（纯函数 + 注入式红证）────────────────────────────────────

def _repo_live_lines(rel: str, src: str | None = None) -> list:
    """取某个链路脚本的可执行行（去空行 / 去整行注释）—— 与 `_live_lines` 同口径。

    `src` 可注入（脚本层红证要把**变异后**的文本喂进同一条判据；不给时读磁盘）。
    """
    if src is None:
        p = REPO_ROOT / rel
        if not p.is_file():
            return []
        src = p.read_text(encoding="utf-8")
    return [raw for raw in src.splitlines() if raw.strip() and not raw.lstrip().startswith("#")]


def _dist_delivery_problems(wf, wf_src=None, dist_src=None, ci_src=None) -> list:
    """🔴 **dist 送达通路**（issue #6095 第三层）的接线判据。

    病（run 37078030820 / sha `d4babbf17`）：`Build H5` 的产物 `frontend/mini-app/dist/**`
    **不在 git 里**（`git ls-tree -r origin/main --name-only frontend/mini-app/dist` = 0 个文件），
    而远端唯一的取回通道是「按不可变 sha 从 codeload 取 tarball」⇒ 远端**必然**
    `❌ 发布源里没有 index.html`。判据四件事：
      ① 链路**存在**：`deploy/scripts/c-end-h5-dist-push.sh` 在仓里、且它有独立判据文件；
      ② 链路**被接线**：workflow 里 `build:h5` 之后有 step 真跑它，且发布步逐字消费它的 step output；
      ③ 取回 ref **是不可变 sha**：脚本产出 40 位十六进制 commit 对象名（`git commit-tree` 无父），
         且**不出现**任何取回分支名的形态（`codeload…/refs/heads/…` / `h5-dist` 当取回 ref）；
      ④ 断言**不许被摘掉**：`identity` 判据仍在（`[ "$REMOTE_INDEX_SHA" = "$LOCAL_SHA" ]`）。
    """
    problems: list = []
    if dist_src is None:
        if not (REPO_ROOT / DIST_PUSH_SCRIPT).is_file():
            problems.append(
                f"🔴 缺 `{DIST_PUSH_SCRIPT}` —— CI 构建的 dist 到不了服务器"
                "（远端只会拿到源码 tarball，里面没有 dist/index.html）"
            )
        else:
            dist_src = (REPO_ROOT / DIST_PUSH_SCRIPT).read_text(encoding="utf-8")
    if wf_src is None:
        wf_src = _read(WORKFLOW_PATH)
    steps = _steps(wf)
    push_steps = [s for s in steps if DIST_PUSH_SCRIPT in _run_text(s)]
    build_steps = [s for s in steps if "npm run build:h5" in _run_text(s)]
    if len(push_steps) != 1:
        problems.append(
            f"🔴 workflow 里必须有且只有 1 个跑 `{DIST_PUSH_SCRIPT}` 的 step（把 CI 构建的 dist 送出去），"
            f"实际 {len(push_steps)} —— 摘掉它 ⇒ 远端取回的还是源码 tarball ⇒ 发布**永远**失败"
            "（run 37078030820 的形态）"
        )
    if push_steps and build_steps and steps.index(push_steps[0]) < steps.index(build_steps[0]):
        problems.append(
            f"step `{push_steps[0].get('name')}` 排在 `npm run build:h5` **之前** ⇒ 推出去的是上一次的产物"
            "（发布内容单一源被破坏）"
        )
    if push_steps and PUBLISH_IF not in _if_text(push_steps[0]):
        problems.append(
            f"🔴 step `{push_steps[0].get('name')}` 的 `if` 缺 `{PUBLISH_IF}` ⇒ 非发布模式下也会把 dist 推出去"
        )
    # 接线点：发布步拿到的必须是 **dist 推送步的 step output**（不可变 sha），不是 `$GITHUB_SHA`
    if not push_steps or len(push_steps) == 1:
        publish_steps = [s for s in steps if PUBLISH_SCRIPT in _run_text(s)]
        for step in publish_steps:
            run = _run_text(step)
            if DIST_OUTPUT_REF not in run:
                problems.append(
                    f"🔴 step `{step.get('name')}` 没有消费 `{DIST_OUTPUT_REF}`"
                    "（发布腿按不可变 sha 取回产物）—— 摘掉它 ⇒ 取回的又是源码 tarball"
                )
            if "${{ github.sha }}" in run:
                problems.append(
                    f"🔴 step `{step.get('name')}` 的 run 里出现 `${{{{ github.sha }}}}`（源码 commit）"
                    "—— 它的 tarball 里**没有** dist/，正是 run 37078030820 的失败形态"
                )
    # 权限面：推分支需要 `contents: write`（workflow 级；不放大到其它面）
    if (wf.get("permissions") or {}).get("contents") != "write":
        problems.append(
            "🔴 workflow 缺 `permissions: contents: write` ⇒ 推 dist 分支会被拒（而失败发生在推送那一刻，"
            "离根因很远）"
        )
    # 形态判据（**可执行行**，注释里讲课不算）：
    #   · 取回 ref 不许是分支名；
    #   · **孤儿**不许被改成有父（`commit-tree … -p <parent>` ⇒ 分支历史每次发布都涨一份 MB 级产物）
    live = _repo_live_lines(DIST_PUSH_SCRIPT, dist_src)
    for raw in live:
        if "commit-tree" in raw and " -p " in raw:
            problems.append(
                f"🔴 `{DIST_PUSH_SCRIPT}` 的可执行行给 `commit-tree` 加了父提交（`-p`）：`{raw.strip()}`"
                " —— 那样每次发布都会往分支历史里加一份 MB 级产物（孤儿单提交是**不胀历史**的机械载体）"
            )
    live_text = "\n".join(live)
    # 🔴 **孤儿提交必须显式带身份**（#6095 第四层；run 37081920188：CI runner 上没有可用身份
    #    ⇒ `fatal: empty ident name` ⇒ exit 128）。这条与下面的行为级判据**互为补强**：
    #    静态这条会在**任何**改动路径上当场点名，行为级那条证明它**真的**解掉了 CI 的条件。
    if DIST_IDENT_FORM not in live_text:
        problems.append(
            f"🔴 `{DIST_PUSH_SCRIPT}` 的可执行行里没有**显式身份**（`{DIST_IDENT_FORM}`）—— "
            "CI runner 上没有作者/提交者身份源 ⇒ `git commit-tree` 报 `empty ident name`"
            "（#6095 第四层，run 37081920188 实测 exit 128）"
        )
    if DIST_ENV_UNSET_FORM not in live_text:
        problems.append(
            f"🔴 `{DIST_PUSH_SCRIPT}` 没有清掉调用方的「我在哪个仓」环境（`{DIST_ENV_UNSET_FORM}`）—— "
            "`GIT_DIR` / `GIT_WORK_TREE` 会把「在哪个仓上造提交、往哪个远端推」交给环境决定"
        )
    body = _dist_ref_shape_problems(live_text)
    problems.extend(f"🔴 `{DIST_PUSH_SCRIPT}` 的{hit}" for hit in body)

    # —— 🔴🔴 **两个 ref 各司其职**（issue #6095 第五层；run 37084280991）——
    # 病：引导按**产物 ref** 取执行体 ⇒ 取回的 tarball 里只有 17 个 dist 文件、**没有远端脚本**
    #     ⇒ `bash: …/c-end-h5-publish-remote.sh: No such file or directory`（远端 Failed）。
    # 这条静态判据让「一个 ref 干两件事」在任何改动路径上当场点名；组合层的**行为**判据
    # （`TestTwoRefsCombination`：真造两个提交、真取回、真执行）证明它**真的**解得开 CI。
    ci_live = "\n".join(_repo_live_lines(CI_SCRIPT, ci_src))
    if BOOT_SCRIPT_REF_FORM not in ci_live:
        problems.append(
            f"🔴 `{CI_SCRIPT}` 的引导没有按**执行体 ref**（`{BOOT_SCRIPT_REF_FORM}`）取回远端脚本 —— "
            "按产物 ref 取会拿到「只有 dist 文件」的 tarball ⇒ 远端 `No such file or directory`（#6095 第五层）"
        )
    if BOOT_PRODUCT_REF_FORM in ci_live:
        problems.append(
            f"🔴 `{CI_SCRIPT}` 的引导**按产物 ref**（`{BOOT_PRODUCT_REF_FORM}`）取远端脚本 —— "
            "产物 ref 的 tarball 里没有 `deploy/swas/c-end-h5-publish-remote.sh`（这正是第五层的形态）"
        )
    if CI_PUBLISH_PRODUCT_REF_FORM not in ci_live:
        problems.append(
            f"🔴 `{CI_SCRIPT}` 没有把**产物 ref** 传给远端（缺 `{CI_PUBLISH_PRODUCT_REF_FORM}` 的可执行行）—— "
            "远端 `stage_product()` 就没有取产物的 ref 了"
        )
    return problems


def _dist_ref_shape_problems(live_text: str) -> list:
    """取回 ref 的**形态**判据（**单一实现**：常驻判据与注入式红证跑的是同一条规则）。

    坏形态 = 「按分支名取回」（`codeload…/refs/heads/…` 或 `tar.gz/$BRANCH`）—— 分支名会漂，
    取回的产物就不一定是「本次 CI 构建的那份」。
    """
    hits = []
    for raw in live_text.splitlines():
        drifting = (
            re.search(r'codeload\.github\.com/\S*refs/heads/', raw)
            or "tar.gz/$BRANCH" in raw
            or re.search(r'tar\.gz/\$\{?[A-Za-z_]*BRANCH', raw)
        )
        if drifting:
            hits.append(
                f"可执行行里出现「按**分支名**取回」的形态：`{raw.strip()}`"
                " —— 取回 ref 必须是不可变 sha（分支名会漂）"
            )
    return hits


def _workflow_problems(wf, remote_src=None, ci_src=None, verify_src=None, wf_src=None,
                       dist_src=None) -> list:
    """⚠️ `wf_src` 必须可注入：否则「workflow 里内联第二份发布逻辑」这类**文本层**变异会去读磁盘原文
    ⇒ 变异永远看不见（实测：该变异漏判过一次）。"""
    if wf_src is None:
        wf_src = _read(WORKFLOW_PATH)
    if remote_src is None:
        remote_src = _read(REMOTE_SCRIPT)
    if ci_src is None:
        ci_src = _read(CI_SCRIPT)
    if verify_src is None:
        verify_src = _read(VERIFY_SCRIPT)
    problems: list = []

    if not remote_src:
        problems.append("远端执行体 deploy/swas/c-end-h5-publish-remote.sh 缺失 —— 发布逻辑没有单一出处")
    if not ci_src:
        problems.append("CI 发布脚本 deploy/scripts/c-end-h5-publish-ci.sh 缺失")
    if not verify_src:
        problems.append("落地面断言脚本 deploy/scripts/c-end-h5-verify-served.sh 缺失")

    on = _triggers(wf)
    if not on:
        problems.append("workflow 没有可识别的 on 触发器")
        return problems

    if wf.get("name") != WORKFLOW_DISPLAY_NAME:
        problems.append(
            f"workflow name 变了（现取 {wf.get('name')!r}）—— 它被 h5-freshness-guard.yml 的 "
            f"`workflow_run.workflows` 按**名字**引用，改名会让新鲜度判据不再被发布结果触发"
        )

    push = on.get("push") if isinstance(on.get("push"), dict) else {}
    if "main" not in (push.get("branches") or []):
        problems.append(f"push 触发面缺 main：{push.get('branches')}")
    paths = [str(p) for p in (push.get("paths") or [])]
    if paths != [MINI_APP_GLOB]:
        problems.append(
            f"🔴 on.push.paths 必须**恰好**只有 {MINI_APP_GLOB!r}，实际 {paths} —— "
            f"多一条（`deploy/**` / workflow 自身 / 别的目录）就意味着**改它就会跑这条腿**，"
            f"而它是发布腿（用户裁定 B：合并建通路的 PR 不许触发布）"
        )
    for forbidden in CHAIN_FORBIDDEN_IN_TRIGGER:
        if forbidden in paths:
            problems.append(
                f"🔴 on.push.paths 含发布链路自身 {forbidden} ⇒ 改链路即触发发布腿"
                f"（且 `{DIST_PUSH_SCRIPT}` 这类链路面文件被明文禁止靠加进触发面消账）"
            )
    for glob in STRAY_GLOBS:
        if glob in paths:
            problems.append(f"🔴 on.push.paths 含 {glob!r}（本 PR 的变更集落在 deploy/** ⇒ 会命中）")

    # —— 兜底面：`push` 在本仓会被吞 ⇒ 必须有 `schedule`（且 cron 与台账声明逐字一致）——
    # 真值只有一份（台账 `publish_leg_fallback_ledger.json`），判据从那里取 cron 再回到 YAML 里比对；
    # 取不到台账 ⇒ 判红（不是「跳过」）。
    schedule = on.get("schedule")
    crons = [str(e.get("cron")) for e in schedule if isinstance(e, dict)] if isinstance(schedule, list) else []
    if not crons:
        problems.append(
            "🔴 缺 `schedule` 兜底面：`push` 被 `GITHUB_TOKEN` 合并吞掉时这条腿**不会跑且无红**"
            "（FM-E17 口径；兜底面只报告不发布，见 notify 步）"
        )
    else:
        try:
            ledger = json.loads(FALLBACK_LEDGER.read_text(encoding="utf-8"))
            declared = next(
                (leg.get("fallback", {}).get("cron") for leg in ledger.get("legs", [])
                 if leg.get("file") == WORKFLOW_NAME), None
            )
        except Exception as exc:                     # 台账读不出来 ⇒ 宁可红，不猜
            declared = None
            problems.append(f"兜底面台账读不出来（{FALLBACK_LEDGER.name}）：{exc}")
        if declared is None:
            problems.append(f"台账 `{FALLBACK_LEDGER.name}` 里没有 {WORKFLOW_NAME} 的 `fallback.cron` 声明")
        elif declared not in crons:
            problems.append(f"兜底面 cron 与台账脱钩：台账声明 `{declared}`，现取 {crons}")
    if "pull_request" in on or "pull_request_target" in on:
        problems.append("不得有 pull_request 触发：本 workflow 写的是**线上静态根**，PR 分流内容不该有机会落上去")

    # —— 手动面：workflow_dispatch 的 `publish` 输入（默认 false）——
    dispatch = on.get("workflow_dispatch")
    if not isinstance(dispatch, dict):
        problems.append("缺 workflow_dispatch（人手动发布的唯一入口）")
    else:
        inputs = dispatch.get("inputs") or {}
        publish_input = inputs.get("publish") if isinstance(inputs, dict) else None
        if not isinstance(publish_input, dict):
            problems.append("workflow_dispatch 缺 `publish` 输入（这是「手动才发布」的签字开关）")
        else:
            if publish_input.get("type") != "boolean":
                problems.append(f"`publish` 输入必须是 boolean，实际 {publish_input.get('type')!r}")
            if publish_input.get("default") is not False:
                problems.append(
                    f"🔴 `publish` 输入默认值必须是 **false**（= 不发布），实际 {publish_input.get('default')!r} "
                    f"—— 默认 true 会让一次误 dispatch / 对账兜底 dispatch 直接发布"
                )

    # —— 发布链路两步的 if：逐字要求 workflow_dispatch + publish==true ——
    publish_steps = [s for s in _steps(wf) if PUBLISH_SCRIPT in _run_text(s)]
    verify_steps = [s for s in _steps(wf) if VERIFY_SERVED in _run_text(s)]
    build_steps = [s for s in _steps(wf) if "build:h5" in _run_text(s) and "npm run build:h5" in _run_text(s)]
    if len(publish_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个跑 {PUBLISH_SCRIPT} 的 step，实际 {len(publish_steps)}")
    if len(verify_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个跑 {VERIFY_SERVED} 的落地面断言 step，实际 {len(verify_steps)}")
    if len(build_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个 `npm run build:h5` step（产物必须在 CI 构建），实际 {len(build_steps)}")
    # ⚠️ 闸的口径（**模式判定 + 逐 step 消费**，两处都要钉）：
    #    ① 判定步 `Resolve mode` 是唯一决定「会不会发布」的地方 ⇒ 它必须逐字含两条判据
    #       （`github.event_name` 是 workflow_dispatch **且** `inputs.publish` 为 true）并**双向**写 mode；
    #    ② **写盘 / 依赖构建 / 落地面断言**的三步（build:h5 / 发布 / 断言）必须逐字 `if: <mode == 'publish'>`
    #       ⇒ 就算有人把判定步改成恒 publish，仍然要靠这个 if 才能发布（纵深防线）。
    mode_steps = [s for s in _steps(wf) if MODE_STEP in str(s.get("name") or "")]
    if len(mode_steps) != 1:
        problems.append(f"必须有且只有 1 个「{MODE_STEP}」step（模式判定 = 唯一决定会不会发布的地方），实际 {len(mode_steps)}")
    else:
        mode_run = _run_text(mode_steps[0])
        for token in (GATE_EVENT, GATE_INPUT, MODE_PUBLISH, MODE_NOTIFY,
                      "gh workflow run c-end-h5-publish.yml"):
            if token not in mode_run:
                problems.append(f"模式判定步的 run 缺 `{token}`")
        if str(mode_steps[0].get("id") or "") != "mode":
            problems.append(f"模式判定步的 `id` 必须是 `mode`（下游 if 引用它），实际 {mode_steps[0].get('id')!r}")
        if mode_steps[0].get("continue-on-error"):
            problems.append("模式判定步带 continue-on-error ⇒ 红被吞")

    # 顺序：模式判定步必须**排在**任何消费它的 step 之前（否则 `steps.mode.outputs.mode` 恒为空 ⇒ 全跳过）
    all_steps = _steps(wf)
    if mode_steps:
        mi = all_steps.index(mode_steps[0])
        for step in publish_steps + build_steps + verify_steps:
            if all_steps.index(step) < mi:
                problems.append(
                    f"step `{step.get('name')}` 排在模式判定步**之前** ⇒ 它引用的 "
                    f"`{PUBLISH_IF}` 恒为空（该步会被静默跳过：发布腿变成永远不发布）"
                )

    # 写盘的那一步：必须逐字消费 mode
    for step in publish_steps:
        if PUBLISH_IF not in _if_text(step):
            problems.append(
                f"🔴 step `{step.get('name')}` 的 `if` 缺 `{PUBLISH_IF}` ⇒ 这条发布腿可能在**非发布模式**下发布"
            )
    # 构建 / 落地面断言：同样只在 publish 模式跑（否则 notify 模式会空跑构建或在没发布时假绿/假红）
    for step in build_steps + verify_steps:
        if PUBLISH_IF not in _if_text(step):
            problems.append(f"step `{step.get('name')}` 的 `if` 缺 `{PUBLISH_IF}`（非发布模式不该跑它）")
    for step in publish_steps + verify_steps + build_steps + mode_steps:
        cond = _if_text(step)
        if step.get("continue-on-error"):
            problems.append(f"step `{step.get('name')}` 带 continue-on-error ⇒ 红被吞")
        if "|| true" in _run_text(step):
            problems.append(f"step `{step.get('name')}` 带 `|| true` ⇒ 红被吞")
        if cond.strip().lower() in ("false", "0"):
            problems.append(f"step `{step.get('name')}` 的 if 恒假 ⇒ 红被吞")

    # —— notify 面：**唯一**会因为「线上落后」判红的地方 + 必须给出可复制命令 ——
    notify_steps = [s for s in _steps(wf) if "Notify" in str(s.get("name") or "")]
    if len(notify_steps) != 1:
        problems.append(f"缺「Notify」step（兜底面必须能报出「线上落后」，否则 cron 是空转），实际 {len(notify_steps)}")
    else:
        nt = notify_steps[0]
        if NOTIFY_IF not in _if_text(nt):
            problems.append(f"Notify 步的 `if` 必须是 `{NOTIFY_IF}`（只在非发布模式跑）")
        nrun = _run_text(nt)
        for token in ("::error::", "gh workflow run c-end-h5-publish.yml",
                      "scripts/h5_freshness_guard.py", "--ref origin/main", 'exit "$rc"'):
            if token not in nrun:
                problems.append(f"Notify 步的 run 缺 `{token}`（判红 / 可复制命令 / 事实基准 / 「没跑≠通过」）")
        if nt.get("continue-on-error"):
            problems.append("Notify 步带 continue-on-error ⇒ 线上落后也不会红（兜底面变空转）")

    # —— env：目标 / 清单 / 保留前缀 ——
    env = wf.get("env") or {}
    if env.get("H5_STATIC_ROOT") != STATIC_ROOT:
        problems.append(f"env.H5_STATIC_ROOT 必须是 {STATIC_ROOT}，实际 {env.get('H5_STATIC_ROOT')!r}")
    if env.get("H5_MANIFEST") != MANIFEST:
        problems.append(f"env.H5_MANIFEST 必须是 {MANIFEST!r}，实际 {env.get('H5_MANIFEST')!r}")
    if str(env.get("H5_RESERVED_PREFIXES") or "").split() != list(RESERVED):
        problems.append(
            f"🔴 env.H5_RESERVED_PREFIXES 必须是 {' '.join(RESERVED)!r}（w 工人端 / b 商家端），"
            f"实际 {env.get('H5_RESERVED_PREFIXES')!r}"
        )

    # —— 单一实现：workflow 只调 CI 包装，不内联发布命令 ——
    wf_text = wf_src or ""
    for token in ("H5_PUBLISH_SHA=", "codeload.github.com", "assert_target_safe", "H5_RESERVED_PREFIXES="):
        if token in wf_text:
            problems.append(f"workflow 里出现 `{token}` ⇒ 发布逻辑被内联了第二份（必须只调 {PUBLISH_SCRIPT}）")

    # —— 🔴 SWAS 命令内容上限（issue #6095）：远端执行体**不许**进命令内容 ——
    # 病（run 37075737625 / sha f3e49752f）：把远端执行体整份内联进 `RunCommand` 的
    # `--command-content` ⇒ 越过 `CommandContent` 上限 ⇒ **每次**发布都 `400 CmdContent.ExceedLimit`
    # （线上产物因此陈旧 33 天）。下面钉三件事：
    #   ① 上限常量**带出处**（官方文档链接，口径不许靠猜）；
    #   ② 组装段**不得**内联远端脚本（形态判据：不含远端脚本的特征行，也不用 `cat` 读它）；
    #   ③ 组装后有**字节数前置断言**（超限 ⇒ 本机判红，不是云上 400）。
    #
    # ⚠️ 本节的 token 扫描一律走 `_live_lines`（**去掉整行注释**）⇒ 讲解本病灶的注释不会把自己判红
    #    （同族先例：test_guard_parsing_is_comment_aware.py）。判据是**控件**，形状是代码不是说明文字。
    if ci_src:
        ci_live = _live_lines(ci_src)
        inline_call = "cat " + '"$REMOTE_SCRIPT"'
        if inline_call in ci_live:
            problems.append(
                f"🔴 CI 脚本又出现 `cat 远端脚本`（`{inline_call}`）—— 远端执行体被内联进 SWAS 命令内容"
                "（#6095：它会随脚本增长越过 CommandContent 上限，每次发布都 400）"
            )
        for token in ("assert_target_safe() {", "compute_new_top_level() {", "apply_publish() {",
                      "需要 `--takeover-first-publish`"):
            if token in ci_live:
                problems.append(
                    f"🔴 CI 脚本的**可执行行**里出现远端执行体的特征行 `{token}` —— 命令内容不许含远端脚本全文"
                    "（判据：命令内容只做「按 sha 取回执行体并执行」）"
                )
        for token in ("COMMAND_CONTENT_LIMIT_BYTES", "COMMAND_CONTENT_LIMIT_SOURCE"):
            if token not in ci_src:
                problems.append(f"CI 脚本缺命令内容上限常量 `{token}`（#6095）")
        if "help.aliyun.com" not in ci_live:
            problems.append("命令内容上限**没有出处**（可执行行须带官方文档链接，口径不许靠猜）")
        for token in ("COMMAND_CONTENT_BYTES=", '"$COMMAND_CONTENT_BYTES" -ge "$COMMAND_CONTENT_LIMIT_BYTES"'):
            if token not in ci_live:
                problems.append(f"CI 脚本缺命令内容的字节数前置断言 `{token}`（超限必须在**本机**判红）")
        # 取回通道 = **既有已证明可用**的那一条，且**按不可变 sha**（不许取 main 的最新 ⇒ 会漂移）
        # ⚠️ 扫描面 = **组装段**（`REMOTE_FETCH=` 那一行 + `COMMAND_CONTENT=` 赋值块）——
        #    「按分支取回」这条判据的对象是**引导本体**；整脚本扫描会被别处（例如讲解本纪律的
        #    注释 / 别段代码）误伤，判据就开始吃自己项目的文案（实测：注释变异对照假红）。
        m = re.search(
            r"^REMOTE_FETCH=.*?^COMMAND_CONTENT=.*?^\$REMOTE_FETCH --apply\"",
            ci_src, re.M | re.S,
        )
        bootstrap = m.group(0) if m else ci_live
        # ⚠️ 用正则而不是逐字串：在 shell 里可能被拆成拼接形态（`tar.gz/'"$SCRIPT_SHA"'`，
        #    即单引号 + 双引号拼接）⇒ 逐字比对会把**合法**写法判红。判的是「URL 尾巴上跟的是
        #    **执行体 ref** 这个变量」这件事本身（#6095 第五层：它**不能**是产物 ref）。
        if not re.search(r'tar\.gz/["\']{0,2}\$\{?SCRIPT_SHA', bootstrap):
            problems.append(
                "引导必须按**执行体 ref**（不可变 sha）从 codeload 取回远端执行体"
                "（`tar.gz/$SCRIPT_SHA`；用产物 ref 取会拿到「只有 dist 文件」的 tarball ⇒ "
                "远端 `No such file or directory`）"
            )
        if "refs/heads/" in bootstrap:
            problems.append("引导里出现按分支取（`refs/heads/…`）—— 取回通道必须按不可变 sha，否则与 CI 构建漂移")
        if "raw.githubusercontent.com" in ci_live:
            problems.append("引导用了 raw.githubusercontent.com —— 杭州机房实测超时，必须走 codeload")
        if "未做任何发布动作" not in ci_live:
            problems.append("引导取不到执行体时缺**具名失败**出口（不许静默半成品发布）")

    # —— CI 包装脚本：五条承重断言（逐字形态，不是「提到过这个词」）——
    if ci_src:
        for token in (
            'grep -q "^TARGET=$EXPECTED_TARGET$"',
            '[ "$REMOTE_INDEX_SHA" = "$LOCAL_SHA" ]',
            'grep -q "^PROTECTED_UNCHANGED=1$"',
            'grep -q "^ASSET_REFS_ROOT_SCOPED=1$"',
            '[ "$STATUS" = "Success" ] || die',
        ):
            if token not in ci_src:
                problems.append(f"CI 脚本缺少验收断言（逐字形态）`{token}`")
        if "PUBLISHED_INDEX_SHA256" not in ci_src:
            problems.append("CI 脚本缺少发布自证标记 `PUBLISHED_INDEX_SHA256`")
        # 保留子树的四个读数键是**按前缀循环拼出**的（`PROTECTED_${p}_BEFORE_SHA256` 等），
        # 故这里断言**拼法**逐字在案，而不是断言某一个具体前缀的字面量。
        for key in ("PROTECTED_${p}_BEFORE_SHA256", "PROTECTED_${p}_AFTER_SHA256",
                    "PROTECTED_${p}_BEFORE_INDEX_SHA256", "PROTECTED_${p}_AFTER_INDEX_SHA256"):
            if key not in ci_src:
                problems.append(f"CI 脚本缺少保留子树读数键的拼法 `{key}`")
        if 'LOCAL_INDEX="$DIST_DIR/index.html"' not in ci_src:
            problems.append("CI 脚本必须把 `frontend/mini-app/dist/index.html` 作为身份基准（产物单一源）")
        # 保留子树的四条读数必须真的被解析（写了变量不用 = 空断言）
        if 'PROTECTED_${p}_BEFORE_SHA256' not in ci_src or 'PROTECTED_${p}_AFTER_SHA256' not in ci_src:
            problems.append("CI 脚本没有逐条解析保留子树的 BEFORE/AFTER 读数（红线不可判）")
        for line in _unsanctioned_destructive_lines(ci_src):
            problems.append(f"CI 脚本里有未限定目标的破坏性语句（红线）：{line}")

    # —— 远端执行体：三组守卫函数 + 保留前缀 + 接管闸 ——
    if remote_src:
        for token in ("assert_target_safe() {", "assert_no_reserved_refs() {", "load_managed() {",
                      "compute_new_top_level() {", "compute_replacement() {", "apply_publish() {"):
            if token not in remote_src:
                problems.append(f"远端脚本必须定义 {token}")
        # 删除范围必须是「上一次清单 ∩ 磁盘现值」——这条是红线一（绝不删静态根）的机械载体
        for token in ("MANAGED_TOP_LEVEL_DELETE", "compute_replacement() {", "DELETE=") :
            if token not in remote_src:
                problems.append(f"远端脚本缺删除范围读数/机制 `{token}`")
        for token in ("TAKEOVER_REQUIRED" if False else "需要 `--takeover-first-publish`", "PROTECTED_", "MANAGED_TOP_LEVEL_DELETE"):
            if token not in remote_src:
                problems.append(f"远端脚本缺 `{token}`（首次发布的签字闸 / 保留子树自证 / 删除范围读数）")
        if "H5_RESERVED_PREFIXES" not in remote_src:
            problems.append("远端脚本没有保留前缀机制（红线二的结构层）")
        # 红线二结构层的**fail-closed 落点**：产物顶层出现保留前缀 ⇒ 立刻 die（不是「跳过它继续发」）
        if 'is_reserved "$name" && die' not in remote_src:
            problems.append("远端脚本的「产物顶层出现保留前缀 ⇒ die」这一步不见了（红线二结构层失效）")
        if 'is_reserved "$name" && die' not in remote_src or 'die "清单里出现保留前缀' not in remote_src:
            problems.append("远端脚本的「清单被保留前缀污染 ⇒ die」这一步不见了（红线二结构层失效）")
        for line in _unsanctioned_destructive_lines(remote_src):
            problems.append(f"远端脚本里有未限定目标的破坏性语句（红线）：{line}")

    # —— 🔴 dist 送达通路（issue #6095 第三层）：CI 构建的产物必须**真的**到得了远端 ——
    problems.extend(_dist_delivery_problems(wf, wf_src, dist_src, ci_src))

    return problems


# ── 命令内容上限（issue #6095）：**真跑组装段**（注入夹具）的字节判据 ─────────
# 结构层的 token 扫描（`_workflow_problems`）判「形态」；本节判**读数**：真的把脚本跑起来，
# 读它打印出来的命令内容与字节数。两节互补：形态容易被绕过（换个写法），读数不会。
# **执行体 ref**（= CI 跑的那个源码 commit；含 `deploy/swas/c-end-h5-publish-remote.sh`）
CI_SHA = "f3e49752fa140dd6af4da6b75948e541f90c76da"
# **产物 ref**（= `h5-dist` 上只含 dist 的孤儿单提交）；**刻意与 `CI_SHA` 不同** ——
# 第五层的病灶就是夹具把它们当成了同一个（于是两侧的桩都绕过了对方的假设）。
CI_DIST_SHA = "0b7a1c3d5e6f408192a3b4c5d6e7f8091a2b3c4d"
# 引导**必须**按执行体 ref 取回（这两个字符串是同一件事的正反两面，判据与红证共用）
BOOT_SCRIPT_REF_FORM = 'tar.gz/\'"$SCRIPT_SHA"\''
BOOT_PRODUCT_REF_FORM = 'tar.gz/\'"$SHA"\''
# 远端取产物用的变量（**不许**被换成执行体 ref）
CI_PUBLISH_PRODUCT_REF_FORM = "export H5_PUBLISH_SHA=$SHA"
CI_INSTANCE = "b23c69e599524b1da719734f72e6a0e3"
CI_REGION = "cn-hangzhou"
# 组装预算（**设计判据**，不是上限）：真实读数 ~795 字节。取 1024 当「有没有人把大块文本
# 拼回命令内容」的报警线 —— 它离上限（16384）很远，触发它的一定是**结构**退化，不是文案变长。
COMMAND_BUDGET_BYTES = 1024


def _ci_stub(tmp_path: Path, ci_src: str | None = None) -> Path:
    """把 CI 脚本放进一个**结构完整的**临时检出（脚本自身算出的 `dist/` 路径要能过前置断言）。

    目录形状必须与真检出一致（`<root>/deploy/scripts/…`）—— 脚本用 `$(dirname $0)/../..` 求根，
    所以这里**不复制** `frontend/mini-app/dist` 的真产物（那是 CI 的 `npm run build:h5` 的活儿），
    只造满足前置断言的最小桩。
    """
    root = tmp_path / "checkout"
    (root / "deploy" / "scripts").mkdir(parents=True)
    (root / "frontend" / "mini-app" / "dist" / "js").mkdir(parents=True)
    dst = root / "deploy" / "scripts" / CI_SCRIPT.name
    dst.write_text(ci_src if ci_src is not None else CI_SCRIPT.read_text(encoding="utf-8"),
                   encoding="utf-8")
    (root / "frontend" / "mini-app" / "dist" / "index.html").write_text("<html>stub</html>\n", encoding="utf-8")
    return dst


def _run_ci_script(dst: Path, remote: Path, extra_env: dict | None = None,
                   dist_sha: str = CI_DIST_SHA):
    """真跑 CI 脚本的**组装段**（`H5_PRINT_COMMAND_CONTENT=1`）—— 不联网、不发起任何云调用。

    返回 `(proc, content, reported_bytes)`：`content` 是**标记之间**的那份命令内容
    （`say` 的前言走 stdout，不能混进来 —— 否则字节读数会随前言文案漂移）。
    """
    env = dict(os.environ)
    env.update({
        "H5_PRINT_COMMAND_CONTENT": "1",
        "H5_REMOTE_SCRIPT_PATH": str(remote),
        "GITHUB_SHA": CI_SHA,
    })
    env.update(extra_env or {})
    # ⚠️ 显式 `encoding="utf-8", errors="replace"`：CI 脚本会打印中文，而本机 locale 下
    #    子进程（如 curl）的错误文本可能不是 UTF-8 ⇒ 不显式指定会在某些机器上**解码崩**（假红）。
    # 第 5 参数 = **产物 ref**（#6095 第五层起**必须**显式给：源码 commit 不再被当产物 ref 回落）
    proc = subprocess.run(
        ["bash", str(dst), CI_INSTANCE, CI_REGION, "", "", dist_sha],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120,
    )
    # BEGIN 标记在 **stdout** 上（命令内容也走 stdout；`say` 的前言在它前面）⇒ 从标记切到行尾。
    content = ""
    if "COMMAND_CONTENT_BEGIN\n" in proc.stdout:
        content = proc.stdout.split("COMMAND_CONTENT_BEGIN\n", 1)[1]
        if content.endswith("\n"):
            content = content[:-1]
    m = re.search(r"^COMMAND_CONTENT_BYTES=(\d+)$", proc.stderr, re.M)
    return proc, content, int(m.group(1)) if m else None


def _tiny_remote(tmp_path: Path) -> Path:
    f = tmp_path / "tiny-remote.sh"
    f.write_text("#!/bin/bash\n# 夹具：极小远端执行体\necho ok\n", encoding="utf-8")
    return f


class TestCommandContentLimit:
    """`COMMAND_CONTENT` 的**读数**判据（issue #6095）：与远端脚本大小解耦 + 超限本机判红 + 取不到就具名判红。

    四条：① 解耦（超大夹具 ⇒ 读数不变）② 带不可变 sha（不是「取 main 的最新」）
    ③ 超限 ⇒ 本机判红（注入式）③′ 取不到执行体 ⇒ 非零 + 具名原因 ④ 变异（内联写法回来）⇒ 判红。
    """

    def test_assembled_command_is_decoupled_from_the_remote_script_size(self, tmp_path):
        """① 命令内容**不含**远端执行体全文，且字节数远在上限之下。

        红证：把远端脚本换成一个 20 KB 的「超大夹具」⇒ 读数**不变**（解耦成立）；
        若有人把远端脚本内联回来，同一个夹具会让读数涨到 20 KB+ 并被下面的上限闸判红。
        """
        dst = _ci_stub(tmp_path)
        tiny = _tiny_remote(tmp_path)
        big = tmp_path / "big-remote.sh"
        big.write_text("#!/bin/bash\n" + ("# 超大夹具行：把命令内容顶上去\n" * 900), encoding="utf-8")
        assert big.stat().st_size > 20000, "超大夹具没造出来（判据没有判别力）"

        p_tiny, c_tiny, b_tiny = _run_ci_script(dst, tiny)
        p_big, c_big, b_big = _run_ci_script(dst, big)
        assert p_tiny.returncode == 0, f"组装段跑不起来：\n{p_tiny.stderr}"
        assert p_big.returncode == 0, f"组装段跑不起来：\n{p_big.stderr}"
        assert c_tiny and c_big, "没拿到命令内容（打印段的标记变了？）"
        # 脚本自报的字节数必须等于**它真打印出来的那份内容**的字节数（自证，不是自报自话）
        assert b_tiny == len(c_tiny.encode("utf-8")), f"自报 {b_tiny} ≠ 实测 {len(c_tiny.encode('utf-8'))}"
        assert b_big == len(c_big.encode("utf-8")), f"自报 {b_big} ≠ 实测 {len(c_big.encode('utf-8'))}"
        assert b_tiny == b_big, (
            f"命令内容随远端脚本大小变化（{b_tiny} → {b_big} 字节）⇒ 远端执行体又被内联进命令内容"
        )
        assert b_big < COMMAND_BUDGET_BYTES, (
            f"组装出的命令内容 {b_big} 字节 ≥ 预算 {COMMAND_BUDGET_BYTES} —— 大块文本又进了命令内容"
        )
        # 形态判据（在**真读数**上再钉一遍）：远端脚本的特征行一个都不许出现
        for token in ("assert_target_safe() {", "compute_new_top_level() {", "apply_publish() {",
                      "需要 `--takeover-first-publish`"):
            assert token not in c_big, f"命令内容里出现远端脚本全文的特征行：{token}"

    def test_bootstrap_carries_the_immutable_sha(self, tmp_path):
        """② 引导按**不可变 sha** 取回执行体（不是「取 main 的最新」⇒ 会与 CI 构建漂移）。"""
        dst = _ci_stub(tmp_path)
        proc, content, _ = _run_ci_script(dst, _tiny_remote(tmp_path))
        assert proc.returncode == 0, proc.stderr
        assert f"https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/{CI_SHA}" in content, (
            "引导里没有按不可变 sha 取回执行体（codeload + tar.gz/<sha>）"
        )
        assert "refs/heads/" not in content, "引导里出现按分支取（应只按不可变 sha）"
        assert "raw.githubusercontent.com" not in content, "引导用了 raw（杭州机房实测超时）"
        # 语义不放宽：远端拿到的仍是这四个环境变量 + `--apply`
        for token in ('export H5_STATIC_ROOT=/opt/migao-deploy/h5',
                      f"export H5_PUBLISH_SHA={CI_DIST_SHA}",
                      "export H5_MANIFEST=.migao-c-end-h5-manifest.json",
                      'export H5_RESERVED_PREFIXES="w b"',
                      "export H5_TAKEOVER_FIRST_PUBLISH=1"):
            assert token in content, f"命令内容缺语义：{token}"
        assert "--apply" in content, "命令内容没把 --apply 传给远端执行体（会用 dry-run 静默什么都不发）"
        assert "未做任何发布动作" in content, "引导取不到执行体时没有具名失败出口"

    def test_over_limit_command_content_fails_locally_with_named_reading(self, tmp_path):
        """③ **注入式红证**：命令内容超限 ⇒ 本机判红 + 具名读数（不是云上 `SDKError 400`）。

        注入方式（§28.1 出口①）+ 复算命令：

            H5_PRINT_COMMAND_CONTENT=1 H5_REMOTE_SCRIPT_PATH=/tmp/tiny-remote.sh \
              H5_COMMAND_CONTENT_LIMIT_BYTES=200 GITHUB_SHA=<sha> \
              bash deploy/scripts/c-end-h5-publish-ci.sh <instance> cn-hangzhou

        ⇒ rc=1 + stderr 含「命令内容 N 字节 / 上限 M 字节」。上限是**可注入的**（`H5_COMMAND_CONTENT_LIMIT_BYTES`）
        ⇒ 不必真造一个超限的真脚本（那样会把「解耦」这个结论反过来）。
        """
        dst = _ci_stub(tmp_path)
        proc, content, _ = _run_ci_script(dst, _tiny_remote(tmp_path), {"H5_COMMAND_CONTENT_LIMIT_BYTES": "200"})
        assert proc.returncode != 0, "超限竟然没判红（空断言）：\n" + proc.stdout
        assert "命令内容超限" in proc.stderr, f"判红报文不具名：\n{proc.stderr}"
        assert "字节 / 上限" in proc.stderr, f"判红报文没给「N 字节 / 上限 M 字节」读数：\n{proc.stderr}"
        assert "help.aliyun.com" in proc.stderr, "判红报文没给出上限的**出处**（链接）"
        assert content == "", "判红前就把超限的命令内容打出去了（不许把它带出去）"

    def test_bootstrap_fails_closed_when_it_cannot_fetch(self, tmp_path):
        """③′ 取不到执行体 ⇒ **非零退出 + 具名原因**（不是「静默半成品发布」）。

        注入方式（§28.1 出口①）：把引导里 URL 的不可变 sha 换成 40 个 `0`（目录不存在 ⇒ 真 404）。
        ⚠️ 这条**必须在真跑里钉**：引导是**引号嵌套的一行**，读代码看不出 `curl` 失败会不会被吞掉
        （实测教训：`curl … | tar xz` 的管道退出码只取末命令 ⇒ curl 404 时 tar 退 0、
        **失败被吞**，随后 bash 去执行不存在的文件 ⇒ 只剩一句没有归因的 127）。
        """
        dst = _ci_stub(tmp_path)
        proc, content, _ = _run_ci_script(dst, _tiny_remote(tmp_path))
        assert proc.returncode == 0 and content, proc.stderr
        assert "未做任何发布动作" in content, "引导取不到执行体时没有具名失败出口"
        # 真跑：坏 sha ⇒ 期望非零退出 + 具名报文
        bad = tmp_path / "bad-sha.sh"
        bad.write_text(content.replace(CI_SHA, "0" * 40) + "\n", encoding="utf-8")  # 执行体 ref 取不到
        got = subprocess.run(["bash", str(bad)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=300)
        assert got.returncode != 0, "取不到执行体竟然退 0（静默半成品发布）"
        assert "未做任何发布动作" in got.stderr, (
            f"失败没有具名归因（看不出是引导取不到执行体）：\n{got.stderr}"
        )

    def test_inline_mutation_is_detected(self, tmp_path):
        """④ 变异 ⇒ 必红：把「内联远端脚本」的旧写法放回可执行行 ⇒ 结构判据当场判红。"""
        live = _live_lines(_read(CI_SCRIPT) or "")
        inline = live.replace(
            "COMMAND_CONTENT_BYTES=",
            'leak=$(cat "$REMOTE_SCRIPT")\nCOMMAND_CONTENT_BYTES=',
            1,
        )
        assert inline != live, "变异注入未生效（找不到可执行锚点）"
        assert _live_lines(inline) != live, "变异没进入可执行行（注入写进了注释？）"
        assert "cat " + '"$REMOTE_SCRIPT"' in _live_lines(inline)
        problems = _workflow_problems(_load_workflow(), ci_src=inline.replace("\n", chr(10)))
        assert any("内联进 SWAS 命令内容" in x for x in problems), (
            f"把内联写法放回可执行行竟没判红（空断言）：{problems}"
        )


class TestCiSideInjectedValuesAndMessages:
    """CI 侧两个「出问题时最需要读的那句话」面：注入白名单 + 报错文案**不被 bash 吃掉**。

    两条都是本包第四层同批扫出的（issue #6095 第四层 / run 37081920188 的连带面）：
      ① `H5_PUBLISHED_COMMIT` 是本包**新加**的环境变量，且它会被**拼进 SWAS 命令内容** ——
         而该文件对**其它**每个注入值都有字符集白名单（`SHA` / `STATIC_ROOT` / `MANIFEST` /
         `RESERVED_PREFIXES`）⇒ 新值不豁免同一道闸（否则「注入防线」只覆盖老的那几个值）；
      ② 报错文案里写了**裸反引号**（想打行内代码标记）⇒ bash 把它们当**命令替换执行**：
         `line 195: refs/heads/*: No such file or directory` / `main: command not found`，
         并**吃掉文案里的行内代码** —— 而这句正是「DIST_SHA 传错」时唯一可读的出口。
         类级判据在 `test_scripts_bash32_var_brace.py`（判据 6，全仓射程）；**这里钉行为面**。
    """

    def _run_ci(self, tmp_path, sha: str, extra_env: dict | None = None, dst: Path | None = None):
        dst = dst or _ci_stub(tmp_path)
        env = {
            **os.environ,
            "H5_PRINT_COMMAND_CONTENT": "1",
            "H5_REMOTE_SCRIPT_PATH": str(_tiny_remote(tmp_path)),
            "GITHUB_SHA": CI_SHA,
            **(extra_env or {}),
        }
        return subprocess.run(
            ["bash", str(dst), CI_INSTANCE, CI_REGION, "", "", sha],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120,
        )

    def test_wrong_length_dist_sha_dies_with_a_clean_readable_message(self, tmp_path):
        """① 坏长度 ⇒ 本机具名判红，且文案**干净**（不含命令替换咬出来的噪音）。"""
        proc = self._run_ci(tmp_path, "a" * 45)
        assert proc.returncode != 0, f"45 位 DIST_SHA 竟被接受：\n{proc.stdout}"
        assert "DIST_SHA 必须是 40 位十六进制" in proc.stderr, f"判红不具名：\n{proc.stderr}"
        for noise in ("command not found", "No such file or directory"):
            assert noise not in proc.stderr, (
                f"报错文案被 bash 当命令执行了（`{noise}`）—— 文案里的反引号没转义：\n{proc.stderr}"
            )
        # 行内代码**原样**留在文案里（被吃掉就是「错误信息少了一半」）
        assert "refs/heads/*" in proc.stderr and "h5-dist" in proc.stderr, (
            f"文案里的行内代码被命令替换吃掉了：\n{proc.stderr}"
        )

    def test_bare_backtick_mutation_reproduces_the_noisy_message(self, tmp_path):
        """①′ **注入式红证**：把反引号转义撤掉 ⇒ 同一分支立刻吐出 `command not found` 噪音。"""
        dst = _ci_stub(tmp_path)
        src = dst.read_text(encoding="utf-8")
        mutant = src.replace("\\`refs/heads/*\\`、\\`h5-dist\\`、\\`main\\`",
                             "`refs/heads/*`、`h5-dist`、`main`")
        assert mutant != src, "变异注入未生效（找不到转义后的反引号锚点）"
        # 断言变异**落到了目标文案**（不是靠窗口启发式：那段文案会随迭代增长）
        assert "`refs/heads/*`、`h5-dist`、`main`" in mutant, "变异没进入目标文案"
        dst.write_text(mutant, encoding="utf-8")
        proc = self._run_ci(tmp_path, "a" * 45, dst=dst)
        assert proc.returncode != 0
        assert "command not found" in proc.stderr or "No such file or directory" in proc.stderr, (
            f"撤掉转义后竟没有命令替换噪音（那条断言是空断言）：\n{proc.stderr}"
        )

    def test_empty_executor_ref_dies_with_a_clean_named_message(self, tmp_path):
        """⑤ 执行体 ref 缺失 ⇒ 具名判红，且文案**干净**（不含命令替换噪音）。

        ⚠️ 这段文案**真的**踩过一次：`请给 `H5_PUBLISHED_COMMIT`` 里那对反引号忘了转义
        ⇒ bash 去执行 `H5_PUBLISHED_COMMIT` ⇒ 报错分支凭空多出一行 `command not found`、
        且文案被吃掉一块。抓到它的是**类级判据 6**（全仓 `*.sh` 射程）—— 这条行为判据把它钉在这一层。
        """
        proc = self._run_ci(tmp_path, CI_DIST_SHA, {"H5_PUBLISHED_COMMIT": "", "GITHUB_SHA": ""})
        assert proc.returncode != 0, f"执行体 ref 为空竟被放行：\n{proc.stdout}"
        assert "执行体 ref 为空" in proc.stderr, f"判红不具名：\n{proc.stderr}"
        for noise in ("command not found", "No such file or directory"):
            assert noise not in proc.stderr, f"文案被 bash 当命令执行了（`{noise}`）：\n{proc.stderr}"
        assert "H5_PUBLISHED_COMMIT" in proc.stderr, f"文案里的行内代码被吃掉了：\n{proc.stderr}"

    def test_published_commit_must_be_a_commit_sha_or_empty(self, tmp_path):
        """② 新加的注入值 `H5_PUBLISHED_COMMIT` 必须过同一道白名单（空 = 人工排障，允许）。"""
        bad = self._run_ci(tmp_path / "bad", "a" * 40, {"H5_PUBLISHED_COMMIT": "main; rm -rf /"})
        assert bad.returncode != 0, f"注入式坏值竟被放行：\n{bad.stdout}"
        assert "H5_PUBLISHED_COMMIT 非法" in bad.stderr, f"判红不具名：\n{bad.stderr}"
        short = self._run_ci(tmp_path / "short", "a" * 40, {"H5_PUBLISHED_COMMIT": "deadbeef"})
        assert short.returncode != 0 and "长度不是 40" in short.stderr, f"短值竟被放行：\n{short.stderr}"
        empty = self._run_ci(tmp_path / "empty", "a" * 40, {"H5_PUBLISHED_COMMIT": ""})
        assert empty.returncode == 0, f"空值（人工排障）被拒了：\n{empty.stderr}"
        good = self._run_ci(tmp_path / "good", "a" * 40, {"H5_PUBLISHED_COMMIT": "b" * 40})
        assert good.returncode == 0 and "export H5_PUBLISHED_COMMIT=" + "b" * 40 in good.stdout, (
            f"40 位十六进制没进命令内容：\n{good.stdout}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 组合层：**引导取执行体** 与 **远端取产物** 必须是两个不同的 ref（#6095 第五层）
# ═══════════════════════════════════════════════════════════════════════════════
#
# 事故（run 37084280991 / sha `c22514360`）：第三层把命令内容的第 5 参数换成**产物 ref** 之后，
# 引导**也**按它取 codeload tarball ⇒ 那个 tarball 里只有 **17 个 dist 文件**、**没有远端脚本**
# ⇒ `bash: /tmp/tmp.XXXX/deploy/swas/c-end-h5-publish-remote.sh: No such file or directory`
#   （远端 `InvocationStatus=Failed`，线上产物照旧陈旧）。
#
# ⚠️ 为什么前四层的判据全都放它过去了（本节要补的就是这个盲区）：
#   · 第三层的桩演练把「远端执行」**打桩**了（只验产物到达 + 按 sha 取回有 index.html，
#     从没真去取回**执行体**并执行）；
#   · 第二层的桩演练当时还没有「产物 ref ≠ 源码 commit」这个形态。
#   ⇒ 两侧各自的假设都成立，**组合**不成立。这与 #6095 第三/四层同族：
#     「每一块的判据都绿，拼起来错」—— 所以判据必须落在**组合**上（真取回 + 真执行）。


def _orphan_commit_with_paths(work: Path, paths: list) -> str:
    """在 `work` 里用**临时索引**造一个只含 `paths` 的孤儿提交（返回 sha）。"""
    index = work.parent / f"{work.name}-idx"
    env = {
        **os.environ,
        "GIT_INDEX_FILE": str(index),
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }
    subprocess.run(["git", "init", "-q"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "read-tree", "--empty"], cwd=work, env=env, check=True, capture_output=True)
    subprocess.run(["git", "add", "-f", *paths], cwd=work, env=env, check=True, capture_output=True)
    tree = subprocess.run(["git", "write-tree"], cwd=work, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()
    return subprocess.run(["git", "commit-tree", tree, "-m", "fixture"],
                          cwd=work, env=env, check=True, capture_output=True, text=True).stdout.strip()


def _two_ref_fixture(tmp_path: Path) -> dict:
    """**一个裸仓、两个 ref**（= 生产拓扑）：

    · `refs/heads/main` = **执行体 ref**（含 `deploy/swas/c-end-h5-publish-remote.sh` 的提交）；
    · `refs/heads/h5-dist` = **产物 ref**（由**真** `c-end-h5-dist-push.sh` 产出的孤儿单提交）。
    """
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True, capture_output=True)

    src_work = tmp_path / "src-work"
    (src_work / "deploy" / "swas").mkdir(parents=True)
    (src_work / "deploy" / "swas" / REMOTE_SCRIPT.name).write_bytes(REMOTE_SCRIPT.read_bytes())
    s_sha = _orphan_commit_with_paths(src_work, ["deploy"])
    subprocess.run(["git", "push", "-q", str(origin), f"{s_sha}:refs/heads/main"],
                   cwd=src_work, check=True, capture_output=True)

    (tmp_path / "emptyhome").mkdir(exist_ok=True)
    prod = tmp_path / "ci-checkout"
    (prod / "frontend" / "mini-app" / "dist" / "js").mkdir(parents=True)
    (prod / "frontend" / "mini-app" / "dist" / "index.html").write_text(
        '<!doctype html><title>双 ref 桩产物</title><script defer src="/js/app.js"></script>',
        encoding="utf-8")
    (prod / "frontend" / "mini-app" / "dist" / "js" / "app.js").write_text("// two-ref stub\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=prod, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=prod, check=True, capture_output=True)
    push = subprocess.run(["bash", str(REPO_ROOT / DIST_PUSH_SCRIPT), "frontend/mini-app/dist", DIST_BRANCH],
                          cwd=prod, env=_dist_push_env(prod), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)
    assert push.returncode == 0, push.stdout + push.stderr
    d_sha = _pushed_sha(push)
    assert d_sha != s_sha, "夹具里两个 ref 撞成同一个对象（夹具不成立）"
    return {"origin": origin, "S": s_sha, "D": d_sha, "prod": prod}


def _archive_at(repo: Path, sha: str, dest: Path) -> None:
    """`git archive <sha>` + `tar x`（= 引导 / 远端 `curl tar.gz/<sha>` + `tar xzf` 的等价物）。"""
    arch = subprocess.run(["git", "archive", "--format=tar", sha], cwd=str(repo), capture_output=True)
    assert arch.returncode == 0, arch.stderr
    dest.mkdir(parents=True, exist_ok=True)
    tar = subprocess.run(["tar", "xf", "-", "-C", str(dest)], input=arch.stdout, capture_output=True)
    assert tar.returncode == 0, tar.stderr


def _two_ref_drill(tmp_path: Path, fx: dict, ci_src: str | None = None) -> dict:
    """**组合判据（单一实现）**：跑真组装段 → 解析两个 ref → **真取回**两棵 tarball → 逐条对账。

    返回观测字典（含 `problems`）。
    """
    dst = _ci_stub(tmp_path, ci_src=ci_src)
    proc, content, _ = _run_ci_script(dst, REMOTE_SCRIPT, dist_sha=fx["D"],
                                      extra_env={"H5_PUBLISHED_COMMIT": fx["S"], "GITHUB_SHA": fx["S"]})
    assert proc.returncode == 0, proc.stderr
    out: dict = {"content": content, "problems": []}
    m = re.search(r"tar\.gz/([0-9a-f]{0,40})", content)
    out["boot"] = m.group(1) if m else ""
    m2 = re.search(r"export H5_PUBLISH_SHA=([0-9a-f]{0,40})", content)
    out["product"] = m2.group(1) if m2 else ""

    if out["boot"] != fx["S"]:
        out["problems"].append(
            f"引导取回的 ref 不是**执行体 ref**：{out['boot'] or '(缺)'} ≠ {fx['S']}"
            "（取回了产物 ref ⇒ 那个 tarball 里没有远端脚本）"
        )
    if out["product"] != fx["D"]:
        out["problems"].append(
            f"远端取产物的 ref 不是**产物 ref**：{out['product'] or '(缺)'} ≠ {fx['D']}"
        )
    if out["boot"] and out["boot"] == out["product"]:
        out["problems"].append(
            "两个 ref 被写成同一个（#6095 第五层病灶形态）—— 一个 ref 干不了两件事"
        )

    # 真取回：① 执行体 ref 必须**确实含**远端脚本 ② 产物 ref 必须**确实含** index.html
    out["exec_dir"] = tmp_path / "fetch-exec"
    _archive_at(fx["origin"], out["boot"] or fx["S"], out["exec_dir"])
    out["executor"] = out["exec_dir"] / "deploy" / "swas" / REMOTE_SCRIPT.name
    out["executor_present"] = out["executor"].is_file()
    if not out["executor_present"]:
        out["problems"].append(
            f"按引导 ref 取回的 tarball 里**没有** `deploy/swas/{REMOTE_SCRIPT.name}`"
            " ⇒ 远端会 `No such file or directory`"
        )
    out["prod_dir"] = tmp_path / "fetch-prod"
    _archive_at(fx["origin"], out["product"] or fx["D"], out["prod_dir"])
    out["dist_dir"] = out["prod_dir"] / "frontend" / "mini-app" / "dist"
    out["index_present"] = (out["dist_dir"] / "index.html").is_file()
    if not out["index_present"]:
        out["problems"].append(
            "按产物 ref 取回的 tarball 里**没有** `frontend/mini-app/dist/index.html`"
            "（源码 tarball 里没有 dist ⇒ 远端会「发布源里没有 index.html」）"
        )
    return out


def _run_fetched_executor(r: dict, tmp_path: Path, fx: dict) -> tuple:
    """**真执行**「按执行体 ref 取回的那份远端脚本」：产物用取回的 dist、静态根用沙箱。

    桩只桩「云调用」这一层（远端脚本本身不调云）；「取回并执行」这一段是真的。
    """
    root = _make_static_root(tmp_path, manifest=True)
    env = dict(os.environ)
    env["H5_STATIC_ROOT"] = str(root)
    env["H5_PUBLISH_SHA"] = fx["D"]              # 产物 ref（只用于溯源/审计）
    env["H5_PUBLISHED_COMMIT"] = fx["S"]         # 源码 commit（= 执行体 ref）
    proc = subprocess.run(
        ["bash", str(r["executor"]), "--from-dir", str(r["dist_dir"]), "--apply"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=180, cwd=str(REPO_ROOT),
    )
    return root, proc


class TestTwoRefsCombination:
    """🔴 第五层（#6095；run 37084280991）：引导按**执行体 ref** 取脚本、远端按**产物 ref** 取产物。

    判据落在**组合**上：真造两个提交（一个含脚本、一个只含 dist）→ 真跑组装段 → 真 `git archive`
    取回两棵 tarball → 真执行取回的执行体。注入式红证 = 把两个 ref 写成同一个（本次形态）。
    """

    def test_two_refs_are_distinct_and_each_carries_what_it_must(self, tmp_path):
        """① 组合成立：引导 ref 含脚本、产物 ref 含 index.html、两者**不同**，且能真的发布一次。"""
        fx = _two_ref_fixture(tmp_path)
        r = _two_ref_drill(tmp_path, fx)
        assert r["problems"] == [], "组合判据不通过：\n  - " + "\n  - ".join(r["problems"])
        assert r["boot"] == fx["S"] and r["product"] == fx["D"], f"{r['boot']} / {r['product']}"
        assert r["boot"] != r["product"]
        # 「一个 ref 干两件事」在**对象层**就不可能：产物 ref 里没有 `deploy/`，
        # 执行体 ref 里没有 `frontend/mini-app/dist/`
        assert not (r["prod_dir"] / "deploy").exists(), "产物 ref 里竟然有 deploy/（夹具不成立）"
        assert not (r["exec_dir"] / "frontend" / "mini-app" / "dist").exists(), (
            "执行体 ref 里竟然有 dist/（那第三层的病灶就不存在了 —— 夹具不成立）"
        )
        # 真执行：取回的执行体 + 取回的产物 ⇒ 发布成功，且清单里两个 ref 各就各位
        root, proc = _run_fetched_executor(r, tmp_path, fx)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (root / "index.html").is_file(), "取回并执行后产物没落位"
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        assert manifest["published_dist_ref"] == fx["D"], manifest
        assert manifest["published_commit"] == fx["S"], manifest

    def test_same_ref_injection_reproduces_the_remote_failure(self, tmp_path):
        """② **注入式红证**：把引导的 URL 改回产物 ref（= 本次事故形态）⇒ 判红 + 复现远端那句报错。"""
        fx = _two_ref_fixture(tmp_path)
        src = CI_SCRIPT.read_text(encoding="utf-8")
        mutant = src.replace(BOOT_SCRIPT_REF_FORM, BOOT_PRODUCT_REF_FORM)
        assert mutant != src and BOOT_SCRIPT_REF_FORM not in mutant, "变异注入未生效"
        r = _two_ref_drill(tmp_path, fx, ci_src=mutant)
        assert r["problems"], "两个 ref 写成同一个竟没判红（= 空断言）"
        assert any("执行体 ref" in p for p in r["problems"]), r["problems"]
        assert r["boot"] == fx["D"] and r["product"] == fx["D"], "变异没让引导改用产物 ref"
        assert not r["executor_present"], "取回的 tarball 里竟然有远端脚本（夹具不成立）"
        # 复现 CI 那句：bash 去执行取回目录里**不存在**的脚本（远端 `InvocationStatus=Failed`）
        got = subprocess.run(["bash", str(r["executor"])], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        assert got.returncode != 0, "执行不存在的脚本竟然成功"
        assert "No such file or directory" in (got.stdout + got.stderr), (
            f"没复现出 CI 那句报错：\n{got.stdout}\n{got.stderr}"
        )

    def test_product_ref_injection_is_caught(self, tmp_path):
        """③ **注入式红证**：把 `H5_PUBLISH_SHA` 也改成执行体 ref ⇒ 判红（源码 tarball 里没有 dist）。"""
        fx = _two_ref_fixture(tmp_path)
        src = CI_SCRIPT.read_text(encoding="utf-8")
        mutant = src.replace(CI_PUBLISH_PRODUCT_REF_FORM, "export H5_PUBLISH_SHA=$SCRIPT_SHA")
        assert mutant != src and CI_PUBLISH_PRODUCT_REF_FORM not in mutant, "变异注入未生效"
        r = _two_ref_drill(tmp_path, fx, ci_src=mutant)
        assert r["problems"], "产物 ref 漂到执行体 ref 竟没判红（= 空断言）"
        assert any("产物 ref" in p for p in r["problems"]), r["problems"]
        assert not r["index_present"], "源码 tarball 里竟然有 dist/index.html（夹具不成立）"

    def test_audit_fields_never_conflate_the_two_refs(self, tmp_path):
        """④ 审计面：`published_commit`（源码）与 `published_dist_ref`（产物）**不许互相顶替**。

        病史：清单里曾写 `published_commit or sha`（`sha` = 产物 ref）⇒ 没给源码 commit 时，
        清单会把**产物 ref** 标成「源码 commit」—— 又一个两个 ref 混用的出口。
        """
        fx = _two_ref_fixture(tmp_path)
        r = _two_ref_drill(tmp_path, fx)
        assert r["problems"] == [], r["problems"]
        root, proc = _run_fetched_executor(r, tmp_path, fx)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        assert manifest["published_commit"] != manifest["published_dist_ref"], (
            f"两个审计字段被写成同一个值（{manifest['published_commit']}）⇒ 归因不了"
        )


class TestDistDeliveryWiring:
    """🔴 **CI 构建的 dist 到不到得了服务器**（issue #6095 第三层）—— 逐条可单独变红。

    病（run 37078030820 / sha `d4babbf17`）：`Build H5` 的产物不在 git 里（`dist/` 被 `.gitignore`），
    而远端只按不可变 sha 取 tarball ⇒ **必然** `❌ 发布源里没有 index.html`。
    本类钉四件事：① 链路存在且被接线 ② 取回 ref 是不可变 sha（禁漂移 ref）
    ③ 注入式红证（摘掉推送步 / 把 ref 改成 `refs/heads/main` ⇒ 必红） ④ 端到端桩演练
    （真推一次 → 远端按那个 sha 取回 → 真有 index.html）。
    """

    def test_real_workflow_wires_the_dist_push(self):
        """① 真语料：链路存在 + 被真 workflow 接线（跑的是**真** YAML，不是夹具）。"""
        wf = _load_workflow()
        assert _dist_delivery_problems(wf) == [], (
            "dist 送达通路的接线判据不通过：\n  - " + "\n  - ".join(_dist_delivery_problems(wf))
        )
        # 反向自证：判据在**假夹具**上也要绿 ⇒ 上面那条绿不是「判据恒绿」造成的
        assert _dist_delivery_problems(_wf_with_dist_push_step()) == []

    def test_publish_step_consumes_the_immutable_dist_sha(self):
        """② 取回 ref = **不可变 sha**（dist 推送步的 step output），**不是** `$GITHUB_SHA`。"""
        wf = _load_workflow()
        steps = _steps(wf)
        publish = [s for s in steps if PUBLISH_SCRIPT in _run_text(s)]
        assert len(publish) == 1, f"发布步不是恰好 1 个：{len(publish)}"
        run = _run_text(publish[0])
        assert DIST_OUTPUT_REF in run, f"发布步没有消费 `{DIST_OUTPUT_REF}`：\n{run}"
        assert "${{ github.sha }}" not in run, (
            "发布步用的是 `${{ github.sha }}`（源码 commit）—— 它的 tarball 里没有 dist/（run 37078030820）"
        )
        push = [s for s in steps if DIST_PUSH_SCRIPT in _run_text(s)]
        assert len(push) == 1 and str(push[0].get("id") or "") == "dist", (
            f"dist 推送步必须恰好 1 个且 `id: dist`（下游 if / step output 靠它引用），"
            f"实际 {len(push)} 个 / id={push[0].get('id') if push else None!r}"
        )
        # 发布步必须**排在**推送步之后（否则 step output 恒为空 ⇒ 发布腿取不到产物）
        assert steps.index(publish[0]) > steps.index(push[0]), "发布步排在 dist 推送步之前（step output 恒空）"

    def test_dist_push_script_pushes_an_orphan_commit_and_reports_the_sha(self):
        """③ 推送脚本的**形态**：孤儿单提交（无 `-p`）+ 输出 40 位 sha + 不出现分支取回形态。"""
        live = _repo_live_lines(DIST_PUSH_SCRIPT)
        assert live, f"读不到 `{DIST_PUSH_SCRIPT}` 的可执行行"
        joined = "\n".join(live)
        assert DIST_COMMIT_FORM in joined, (
            f"缺少 `{DIST_COMMIT_FORM}` —— 若改成普通 `git commit`，产出的是**有父**的提交 ⇒ 每次发布往分支历史加一份 MB 级产物"
        )
        assert "refs/heads/$BRANCH" in joined, "推送目标必须是 `refs/heads/$BRANCH`（专用分支）"
        assert "H5_DIST_SHA=$SHA" in joined, "脚本必须把 sha 打到 stdout（workflow 靠它取 step output）"
        assert "ls-remote" in joined, "推送后没有再读一次远端（无法自证产物真的到达远端）"
        for raw in live:
            assert "refs/heads/main" not in raw, f"可执行行里出现 main 分支：`{raw.strip()}`"
            assert "codeload.github.com" not in raw, (
                "推送脚本不该出现 codeload 取回形态（取回在发布腿那一侧，且必须按不可变 sha）"
            )

    def test_publish_script_refuses_a_drifting_ref(self, tmp_path):
        """③′ 发布腿**只接受 40 位十六进制**（`refs/heads/main` / 分支名连格式都过不去）。"""
        dst = _ci_stub(tmp_path)
        env = {
            "H5_PRINT_COMMAND_CONTENT": "1",
            "H5_REMOTE_SCRIPT_PATH": str(_tiny_remote(tmp_path)),
            "GITHUB_SHA": CI_SHA,
        }
        for drifting in ("refs/heads/main", "h5-dist"):
            got = subprocess.run(
                ["bash", str(dst), CI_INSTANCE, CI_REGION, "", "", drifting],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, **env}, timeout=120,
            )
            assert got.returncode != 0, f"漂移 ref '{drifting}' 竟被接受：\n{got.stdout}"
            assert "DIST_SHA" in got.stderr, f"判红报文没有点名 DIST_SHA：\n{got.stderr}"

    def test_identity_assertion_still_present_after_the_change(self):
        """④ 单一源的承重断言**还在**（发布内容 = 本次构建 ⇒ 不许被这层改动摘掉）。"""
        ci_src = _read(CI_SCRIPT) or ""
        assert '[ "$REMOTE_INDEX_SHA" = "$LOCAL_SHA" ]' in ci_src, "identity 断言不见了（发布内容单一源被破坏）"
        assert 'LOCAL_INDEX="$DIST_DIR/index.html"' in ci_src, "身份基准不再是 CI 构建的 dist/index.html"
        assert "export H5_SRC_SUBPATH=$DIST_SUBPATH" in ci_src, (
            "命令内容没有把远端取回子路径指到 `frontend/mini-app/dist`（远端仍会在 frontend/mini-app 下找 index.html）"
        )

    def test_injected_red_proofs_for_the_new_wiring(self):
        """③ **注入式红证**（§28.1 出口①）：摘掉推送步 / 把 ref 换成漂移 ref ⇒ 判据必红。"""
        # 红证 A：摘掉 dist 推送步（发布步还在 ⇒ step output 恒空）
        no_push = _wf_with_dist_push_step()
        no_push["jobs"][JOB]["steps"] = [
            s for s in no_push["jobs"][JOB]["steps"] if DIST_PUSH_SCRIPT not in _run_text(s)
        ]
        problems = _dist_delivery_problems(no_push)
        assert problems, "摘掉 dist 推送步竟然没判红（判据是空断言）"
        assert any(DIST_PUSH_SCRIPT in p for p in problems), f"判红没有点名推送步：{problems}"

        # 红证 B：发布步不再消费 step output（退回 `$GITHUB_SHA`）
        back_to_source = _wf_with_dist_push_step()
        for s in back_to_source["jobs"][JOB]["steps"]:
            if PUBLISH_SCRIPT in _run_text(s):
                s["run"] = f'bash {PUBLISH_SCRIPT} "$I" "$R" "$AK" "$SK" "${{{{ github.sha }}}}"'
        problems = _dist_delivery_problems(back_to_source)
        assert any(DIST_OUTPUT_REF in p for p in problems), f"发布步退回源码 sha 竟没判红：{problems}"
        assert any("github.sha" in p for p in problems), f"没有点名 `github.sha` 这个坏形态：{problems}"

        # 红证 C：把取回 ref 改成漂移 ref（`refs/heads/main`）—— **可执行行**注入，判据必红
        live = "\n".join(_repo_live_lines(DIST_PUSH_SCRIPT))
        assert "refs/heads/$BRANCH" in live
        drifting = live.replace(
            'git push --force "$GIT_REMOTE" "$SHA:$PUSH_REF"',
            'curl -fsSL "https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main" -o "$TMP_DIR/x.tgz"',
        )
        drifting += "\n" + 'URL="https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main"'
        drifting += "\n" + 'URL2="https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/$BRANCH"'
        assert drifting != live, "变异注入未生效（找不到推送锚点）"
        # 复用**同一份**形态判据（把变异后的可执行文本喂进去）—— 不重写第二份规则
        problems = _dist_ref_shape_problems(drifting)
        assert problems, "把取回 ref 改成 `refs/heads/main` 竟没判红（形态判据是空断言）"
        assert any("refs/heads" in x for x in problems), f"判红没有点名漂移形态：{problems}"
        # 反向对照：未注入 ⇒ 不报（判据不是因为别的原因恒红）
        assert _dist_ref_shape_problems(live) == []


# ── 无 ambient 身份的推送夹具（第四层：CI runner 的条件）────────────────────────
#
# ⚠️ **为什么必须有这一节**（本包实测的教训）：`git commit-tree` 需要作者/提交者身份，而
#    - **CI runner**：没有全局/仓内身份，系统 GECOS 也是空的 ⇒ git 兜底出的 name 是空串
#      ⇒ `fatal: empty ident name (for <runner@…>) not allowed`（run 37081920188，exit 128）；
#    - **开发机**：git 会用 GECOS + hostname **自动兜一个非空身份** ⇒ 同一脚本**本机绿、CI 红**。
#    ⇒ 「用本机的 git 跑一遍」**证明不了 CI 会过**（这正是第四层漏掉的那一半）。
#    夹具做法（确定性、跨平台一致）：空 `HOME` + `GIT_CONFIG_GLOBAL/SYSTEM=/dev/null`
#    （无任何身份来源）+ 把 `GIT_AUTHOR_NAME`/`GIT_COMMITTER_NAME` **显式置空**
#    （把「本机自动兜底」这条路也堵掉 —— 不置空的话，开发机上永远复现不出 CI 的那条报错）。


def _dist_push_fixture(tmp_path: Path, *, name: str = "push") -> tuple[Path, Path]:
    """造「检出（含 dist）+ 本地裸远端（已配成 `origin`）+ 空 HOME」——零联网、零 ambient 身份。

    ⚠️ **刻意不设** `user.name` / `user.email`（旧版桩演练设了 ⇒ 它继承了一个 CI 上不存在的身份，
    于是**证明不了 CI 会过**：那正是第四层的形态）。
    """
    root = tmp_path / name
    origin = root / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True, capture_output=True)
    checkout = root / "checkout"
    dist = checkout / "frontend" / "mini-app" / "dist"
    (dist / "js").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><title>桩产物</title><script defer src="/js/app.js"></script>', encoding="utf-8"
    )
    (dist / "js" / "app.js").write_text("// stub built by the drill\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=checkout, check=True, capture_output=True)
    (root / "emptyhome").mkdir()
    return checkout, origin


def _dist_push_env(checkout: Path, *, hostile_repo_env: bool = False) -> dict:
    """**无 ambient 身份**的环境（+ 可选：敌意的 `GIT_DIR`/`GIT_WORK_TREE`，指向另一个仓）。"""
    root = checkout.parent
    env = {
        "PATH": os.environ["PATH"],                 # git / coreutils（CI runner 同样由 PATH 提供）
        "HOME": str(root / "emptyhome"),            # 空 HOME ⇒ 没有 ~/.gitconfig
        "GIT_CONFIG_GLOBAL": os.devnull,            # 显式：不读全局配置
        "GIT_CONFIG_SYSTEM": os.devnull,            # 显式：不读系统配置
        "GIT_TERMINAL_PROMPT": "0",                 # 无 tty 时不挂住
        "GIT_AUTHOR_NAME": "",                      # 复现 runner 的那一半：name 解出来是空串
        "GIT_COMMITTER_NAME": "",
        "GITHUB_SHA": CI_SHA,                       # 写进提交信息（可追溯到源码 commit）
    }
    if hostile_repo_env:
        decoy = root / "decoy"
        (decoy / "other").mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=decoy, check=True, capture_output=True)
        env["GIT_DIR"] = str(decoy / ".git")
        env["GIT_WORK_TREE"] = str(decoy)
    return env


def _run_dist_push(checkout: Path, *, script: Path | None = None, env: dict | None = None):
    """按 **CI 的调用形态**跑推送脚本：cwd = 检出根、参数 = 仓内相对路径。"""
    return subprocess.run(
        ["bash", str(script or (REPO_ROOT / DIST_PUSH_SCRIPT)), "frontend/mini-app/dist", DIST_BRANCH],
        cwd=str(checkout), env=env or _dist_push_env(checkout),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )


def _pushed_sha(proc) -> str:
    m = re.search(r"^H5_DIST_SHA=([0-9a-f]{40})$", proc.stdout, re.M)
    assert m, f"脚本没有输出 40 位 sha：\n{proc.stdout}\n{proc.stderr}"
    return m.group(1)


def _commit_ident(repo: Path, sha: str) -> tuple[str, str]:
    """取该提交的 author / committer 身份行（逐字）。"""
    out = subprocess.run(["git", "cat-file", "-p", sha], cwd=str(repo),
                         capture_output=True, text=True, encoding="utf-8").stdout
    author = next((ln for ln in out.splitlines() if ln.startswith("author ")), "")
    committer = next((ln for ln in out.splitlines() if ln.startswith("committer ")), "")
    return author, committer


def test_dist_pipeline_end_to_end_stub_drill(tmp_path):
    """🔴 **端到端桩演练**（不联网、不碰真机器）：真推一次 → 按那个 sha 取回 → 真有 index.html。

    这是「判据绿 ≠ 接线在」（§28.2）的**行为面**那一半：判据只能看形态，而这里真跑了
    `git commit-tree` + `git push` + `git archive`（= 远端 `tar` 解包那一步的等价物），
    证明「CI 构建产物经 git 到达一处能被取回的地方」这条链在**对象层**是通的。
    ⚠️ 边界：`git archive` **不是** GitHub codeload（不验 codeload 对孤儿提交的可用性），
    真发布也没跑（生产触发权在人手里）—— 两条都在 PR body 的「未固化 / 边界」里照实登记。
    """
    # ⚠️ **无 ambient 身份**下跑（`_dist_push_env`）：本机靠 GECOS 自动兜身份，不显式置空就
    #    永远复现不出 runner 的那条 `empty ident name` ⇒ 旧版桩演练因此**证明不了 CI 会过**。
    checkout, origin = _dist_push_fixture(tmp_path)
    proc = _run_dist_push(checkout)
    assert proc.returncode == 0, f"（无 ambient 身份）推送桩演练失败：\n{proc.stdout}\n{proc.stderr}"
    sha = _pushed_sha(proc)

    # ① 远端那个分支上**就是这个** sha（自证：产物真的到达远端）
    got = subprocess.run(["git", "ls-remote", str(origin), f"refs/heads/{DIST_BRANCH}"],
                         capture_output=True, text=True, encoding="utf-8")
    assert got.stdout.split()[0] == sha, f"远端分支不是这个 sha：{got.stdout!r}"

    # ② 它是**孤儿**：远端对象图里 `sha` 恰好 1 个提交、且**没有父**（不胀历史的机械判据）
    await_repo = tmp_path / "verify"
    subprocess.run(["git", "clone", "-q", "--bare", str(origin), str(await_repo)], check=True, capture_output=True)
    count = subprocess.run(["git", "rev-list", "--count", sha], capture_output=True, text=True,
                           encoding="utf-8", cwd=str(await_repo)).stdout.strip()
    assert count == "1", f"该 sha 的历史长度是 {count}（不是孤儿单提交 ⇒ 会胀历史）"
    parents = subprocess.run(["git", "rev-list", "--parents", "-1", sha], capture_output=True, text=True,
                             encoding="utf-8", cwd=str(await_repo)).stdout.split()
    assert len(parents) == 1, f"提交有父：{parents}"

    # ③ 身份**可追溯**（不是「谁在 runner 上就是谁」）：作者/提交者都必须是那个显式 bot 身份
    author, committer = _commit_ident(await_repo, sha)
    expected_ident = f"{DIST_IDENT_NAME} <{DIST_IDENT_EMAIL}>"
    assert expected_ident in author, f"author 不是显式 bot 身份：{author!r}（期望含 {expected_ident}）"
    assert expected_ident in committer, f"committer 不是显式 bot 身份：{committer!r}"

    # ④ 按那个 sha 取回（= 远端 `curl tar.gz/<sha>` + `tar xzf` 的等价物）⇒ dist/index.html 真在里面
    archive = subprocess.run(["git", "archive", "--format=tar", sha], capture_output=True, cwd=str(await_repo))
    assert archive.returncode == 0, archive.stderr
    unpack = tmp_path / "unpack"
    unpack.mkdir()
    tar = subprocess.run(["tar", "xf", "-", "-C", str(unpack)], input=archive.stdout, capture_output=True)
    assert tar.returncode == 0, tar.stderr
    src = unpack / "frontend" / "mini-app" / "dist"
    assert (src / "index.html").is_file(), (
        f"按 sha 取回后找不到 frontend/mini-app/dist/index.html（远端那句 `发布源里没有 index.html` 会复发）："
        f"{sorted(str(p.relative_to(unpack)) for p in unpack.rglob('*'))}"
    )
    assert (src / "js" / "app.js").read_text(encoding="utf-8") == "// stub built by the drill\n"


class TestDistPushIdentityIndependence:
    """🔴 第四层（run 37081920188）：**推送步骤继承了运行环境** ⇒ CI 上 `Prepare dist ref` 挂掉。

    病 = `git commit-tree` 需要身份，CI runner 上没有身份源、系统 GECOS 为空 ⇒
    `fatal: empty ident name (for <runner@…>) not allowed`（exit 128）；而开发机 git 会自动兜一个
    非空身份 ⇒ **本机绿、CI 红**（旧版桩演练的盲区）。同族：#6113（剔除继承来的 `MIGAO_HEAVY_L*`）。
    本类钉两件事：① 无 ambient 身份下**必须绿**（且身份可追溯）② 身份/环境隔离一旦被摘掉 ⇒ **必红**。
    """

    def test_push_succeeds_without_ambient_git_identity(self, tmp_path):
        """① 无 ambient 身份（空 HOME + 无全局/系统配置 + name 置空）⇒ **rc=0** 且身份可追溯。"""
        checkout, origin = _dist_push_fixture(tmp_path)
        proc = _run_dist_push(checkout)
        assert proc.returncode == 0, (
            f"无 ambient 身份下推送失败（= CI 上 `Prepare dist ref` 会红）：\n{proc.stdout}\n{proc.stderr}"
        )
        sha = _pushed_sha(proc)
        remote = subprocess.run(["git", "ls-remote", str(origin), f"refs/heads/{DIST_BRANCH}"],
                                capture_output=True, text=True, encoding="utf-8").stdout
        assert remote.split()[0] == sha, f"远端分支不是这个 sha：{remote!r}"
        author, committer = _commit_ident(origin, sha)
        assert f"{DIST_IDENT_NAME} <{DIST_IDENT_EMAIL}>" in author, f"author 不可追溯：{author!r}"
        assert f"{DIST_IDENT_NAME} <{DIST_IDENT_EMAIL}>" in committer, f"committer 不可追溯：{committer!r}"

    def test_removing_the_explicit_identity_reproduces_the_ci_failure(self, tmp_path):
        """② **注入式红证**：把显式身份摘掉 ⇒ 必须在同一夹具下复现 CI 那条报错（不是「我觉得会红」）。"""
        src = _read(REPO_ROOT / DIST_PUSH_SCRIPT) or ""
        i = src.find("SHA=$(GIT_AUTHOR_NAME=")
        j = src.find(DIST_COMMIT_FORM, i)
        assert i > 0 and j > i, "注入锚点找不到（脚本的显式身份写法变了？）"
        mutant = src[:i] + "SHA=$(" + src[j:]
        assert mutant != src, "变异注入未生效"
        assert DIST_IDENT_FORM not in mutant, "变异没把显式身份摘掉"
        path = tmp_path / "mut-no-identity.sh"
        path.write_text(mutant, encoding="utf-8")

        checkout, _origin = _dist_push_fixture(tmp_path)
        proc = _run_dist_push(checkout, script=path)
        assert proc.returncode != 0, (
            f"摘掉显式身份竟然还能推成功（判据是空断言；说明夹具没有复现 runner 的条件）：\n{proc.stdout}"
        )
        assert "empty ident name" in proc.stderr, (
            f"判红报文不是 CI 上那条 `empty ident name`（夹具没复现 runner 条件）：\n{proc.stderr}"
        )

    def test_hostile_repo_env_is_ignored_and_the_unset_line_is_load_bearing(self, tmp_path):
        """③ `GIT_DIR`/`GIT_WORK_TREE` 指向**另一个仓**时：必须无视它；摘掉那行 ⇒ 必红。"""
        checkout, origin = _dist_push_fixture(tmp_path, name="hostile")
        hostile = _dist_push_env(checkout, hostile_repo_env=True)
        proc = _run_dist_push(checkout, env=hostile)
        assert proc.returncode == 0, (
            f"敌意 GIT_DIR/GIT_WORK_TREE 下推送失败（环境没被隔离）：\n{proc.stdout}\n{proc.stderr}"
        )
        sha = _pushed_sha(proc)
        remote = subprocess.run(["git", "ls-remote", str(origin), f"refs/heads/{DIST_BRANCH}"],
                                capture_output=True, text=True, encoding="utf-8").stdout
        assert sha in remote, f"产物没推到**本检出**对应的远端（环境把它带偏了）：{remote!r}"

        # 注入式红证：摘掉 `unset GIT_DIR …` ⇒ 同一个敌意环境下判红（且是**具名**判红）
        src = _read(REPO_ROOT / DIST_PUSH_SCRIPT) or ""
        mutant = src.replace(DIST_ENV_UNSET_FORM + "\n", "", 1)
        assert mutant != src and DIST_ENV_UNSET_FORM not in mutant, "变异注入未生效"
        path = tmp_path / "mut-no-unset.sh"
        path.write_text(mutant, encoding="utf-8")
        checkout2, _origin2 = _dist_push_fixture(tmp_path, name="hostile-mut")
        proc2 = _run_dist_push(checkout2, script=path, env=_dist_push_env(checkout2, hostile_repo_env=True))
        assert proc2.returncode != 0, (
            f"摘掉 `{DIST_ENV_UNSET_FORM}` 后竟仍成功 —— 那行不是承重的（判据是空断言）：\n{proc2.stdout}"
        )
        assert "不在检出内" in proc2.stderr, f"判红不具名：\n{proc2.stderr}"

    def test_static_form_is_pinned_by_the_wiring_guard(self):
        """④ 形态面：**接线判据**也必须点名这两件事（静态这条与行为级两条互为补强）。"""
        wf = _load_workflow()
        assert _dist_delivery_problems(wf) == []
        src = _read(REPO_ROOT / DIST_PUSH_SCRIPT) or ""
        for mutant, marker in (
            (src.replace(DIST_IDENT_FORM + "\n", "", 1), "没有**显式身份**"),
            (src.replace(DIST_ENV_UNSET_FORM + "\n", "", 1), "没有清掉调用方的"),
        ):
            assert mutant != src, "变异注入未生效"
            problems = _dist_delivery_problems(wf, dist_src=mutant)
            assert any(marker in p for p in problems), (
                f"摘掉这条形态竟没判红（期望含 {marker!r}）：{problems}"
            )


def _wf_with_dist_push_step() -> dict:
    """只给**接线判据**用的假 workflow 夹具（不发任何东西、不读云、不联网）。

    除了「dist 推送步 ↔ 发布步」这一对，其余形状与真 workflow 一致（`id: mode` / 两个 if /
    step output）。判据面 `_dist_delivery_problems` 只读 pending 的接线，**不评价**别的语义
    ⇒ 这样注入「摘掉推送步」才是**干净**的红证（不会被无关判据一起红掉）。
    """
    return {
        "name": WORKFLOW_DISPLAY_NAME,
        "permissions": {"contents": "write"},
        "jobs": {
            JOB: {
                "steps": [
                    {"name": "Resolve mode（publish vs notify）", "id": "mode", "run": 'echo "mode=publish" >> "$GITHUB_OUTPUT"'},
                    {"name": "Build H5 (publicPath='/', API 同源)", "if": PUBLISH_IF, "run": "npm run build:h5"},
                    {"name": f"Prepare dist ref ({DIST_BRANCH})", "id": "dist", "if": PUBLISH_IF,
                     "run": f"bash {DIST_PUSH_SCRIPT}"},
                    {"name": "Publish c-end h5 to SWAS", "if": PUBLISH_IF,
                     "run": f'bash {PUBLISH_SCRIPT} "$I" "$R" "$AK" "$SK" "${{{{ {DIST_OUTPUT_REF} }}}}"'},
                ]
            }
        },
    }


def _load_workflow() -> dict:
    text = _read(WORKFLOW_PATH)
    if text is None:
        pytest.fail(
            f"{WORKFLOW_PATH.relative_to(REPO_ROOT)} 不存在 —— C 端 H5 又回到「没有任何部署通路」"
            "（issue #4184 的形态本身）。删本 workflow 必须同时给出替代接线。"
        )
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def test_real_publish_leg_has_no_problems():
    problems = _workflow_problems(_load_workflow())
    assert problems == [], "发布接线判据不通过：\n  - " + "\n  - ".join(problems)


class TestRedProofs:
    """每条判据都要能单独变红（变异 ⇒ 必红），并附「只改注释 ⇒ 不红」对照。"""

    def _mutations(self, wf) -> dict:
        def add_deploy_glob(mut):
            _triggers(mut)["push"]["paths"].append("deploy/**")

        def add_self_path(mut):
            _triggers(mut)["push"]["paths"].append(".github/workflows/c-end-h5-publish.yml")

        def add_pull_request(mut):
            _triggers(mut)["pull_request"] = {"paths": [MINI_APP_GLOB]}

        def publish_default_true(mut):
            _triggers(mut)["workflow_dispatch"]["inputs"]["publish"]["default"] = True

        def drop_dispatch_face(mut):
            _triggers(mut).pop("workflow_dispatch")

        def drop_gate_on_publish(mut):
            for step in _steps(mut):
                if PUBLISH_SCRIPT in _run_text(step):
                    step.pop("if", None)

        def gate_only_event(mut):
            for step in _steps(mut):
                if PUBLISH_SCRIPT in _run_text(step):
                    step["if"] = GATE_EVENT

        def silence_gate(mut):
            for step in _steps(mut):
                if MODE_STEP in str(step.get("name") or ""):
                    step["continue-on-error"] = True

        def drop_gate_step(mut):
            mut["jobs"][JOB]["steps"] = [
                s for s in _steps(mut) if MODE_STEP not in str(s.get("name") or "")
            ]

        def mode_always_publish(mut):
            """把模式判定改成恒 publish（= 闸失效）。"""
            for step in _steps(mut):
                if MODE_STEP in str(step.get("name") or ""):
                    step["run"] = 'echo "mode=publish" >> "$GITHUB_OUTPUT"'

        def notify_always_green(mut):
            """notify 步不再会因为「线上落后」判红（兜底面变空转）。"""
            for step in _steps(mut):
                if "Notify" in str(step.get("name") or ""):
                    step["run"] = "echo 'nothing to see here'"

        def drop_schedule(mut):
            _triggers(mut).pop("schedule")

        def retarget_cron(mut):
            _triggers(mut)["schedule"] = [{"cron": "0 0 * * *"}]

        def mode_step_last(mut):
            """把模式判定步挪到最后 ⇒ 所有消费它的 step 都拿不到 mode。"""
            steps = mut["jobs"][JOB]["steps"]
            mode = [s for s in steps if MODE_STEP in str(s.get("name") or "")][0]
            steps.remove(mode)
            steps.append(mode)

        def retarget_root(mut):
            mut["env"]["H5_STATIC_ROOT"] = "/opt/migao-deploy"

        def drop_reserved(mut):
            mut["env"].pop("H5_RESERVED_PREFIXES", None)

        def reserved_only_w(mut):
            mut["env"]["H5_RESERVED_PREFIXES"] = "w"

        def drop_publish_step(mut):
            mut["jobs"][JOB]["steps"] = [s for s in _steps(mut) if PUBLISH_SCRIPT not in _run_text(s)]

        def drop_verify_step(mut):
            mut["jobs"][JOB]["steps"] = [s for s in _steps(mut) if VERIFY_SERVED not in _run_text(s)]

        def silence_verify(mut):
            for step in _steps(mut):
                if VERIFY_SERVED in _run_text(step):
                    step["continue-on-error"] = True

        def drop_dist_push_step(mut):
            """摘掉「把 CI 构建的 dist 推出去」那步（#6095 第三层）。"""
            mut["jobs"][JOB]["steps"] = [
                s for s in _steps(mut) if DIST_PUSH_SCRIPT not in _run_text(s)
            ]

        def publish_uses_source_sha(mut):
            """发布步退回 `$GITHUB_SHA`（源码 commit —— 它的 tarball 里没有 dist/）。"""
            for s in _steps(mut):
                if PUBLISH_SCRIPT in _run_text(s):
                    s["run"] = (
                        f'bash {PUBLISH_SCRIPT} "${{{{ env.SWAS_INSTANCE_ID }}}}" '
                        f'"${{{{ env.SWAS_REGION }}}}" "$AK" "$SK" "${{{{ github.sha }}}}"'
                    )

        def inline_remote_logic(mut):
            """把远端脚本的活儿内联进 workflow（= 出现第二份发布实现）。"""
            for step in _steps(mut):
                if PUBLISH_SCRIPT in _run_text(step):
                    step["run"] = step["run"] + "\n          H5_PUBLISH_SHA=abc1234\n"

        def rename_workflow(mut):
            mut["name"] = "publish c-end h5"

        return {
            "触发面加 deploy/**（合并本 PR 即发布）": add_deploy_glob,
            "触发面加 workflow 自身": add_self_path,
            "给发布腿加 pull_request 触发": add_pull_request,
            "publish 输入默认改成 true": publish_default_true,
            "删掉 workflow_dispatch（人的入口）": drop_dispatch_face,
            "发布步骤去掉 if（任何触发都会发）": drop_gate_on_publish,
            "发布步骤 if 只判 event 不判 publish": gate_only_event,
            "模式判定步 continue-on-error": silence_gate,
            "删掉模式判定步": drop_gate_step,
            "模式判定恒 publish（闸失效）": mode_always_publish,
            "notify 步不再因落后判红（兜底面空转）": notify_always_green,
            "删掉 schedule 兜底面": drop_schedule,
            "改 cron（与台账声明脱钩）": retarget_cron,
            "把模式判定步挪到最后": mode_step_last,
            "把静态根改成上层目录": retarget_root,
            "去掉保留前缀（w/b 不再受保护）": drop_reserved,
            "保留前缀只剩 w（b 失去保护）": reserved_only_w,
            "删掉发布步": drop_publish_step,
            "删掉落地面断言步": drop_verify_step,
            "落地面断言 continue-on-error": silence_verify,
            "workflow 里内联第二份发布逻辑": inline_remote_logic,
            "摘掉 dist 推送步（CI 产物到不了服务器）": drop_dist_push_step,
            "发布步退回源码 sha（$GITHUB_SHA）": publish_uses_source_sha,
            "改 workflow name（新鲜度 workflow_run 失联）": rename_workflow,
        }

    def test_every_workflow_mutation_is_detected(self):
        wf = _load_workflow()
        undetected = []
        for name, mutate in self._mutations(wf).items():
            mutant = copy.deepcopy(wf)
            mutate(mutant)
            # 文本层判据（「不许内联第二份实现」）必须看到**变异后的文本** ⇒ 由对象重新序列化得到
            mutant_src = yaml.safe_dump(mutant, allow_unicode=True, sort_keys=False)
            if len(_workflow_problems(mutant, wf_src=mutant_src)) == 0:
                undetected.append(name)
        assert undetected == [], f"这些变异**没有被判红**（= 空断言）：{undetected}"

    def test_comment_only_edit_does_not_turn_red(self):
        """对照：**只改注释** ⇒ 不红（判据读结构，不吃自己的说明文字）。"""
        original = _read(WORKFLOW_PATH) or ""
        annotated = original.replace(
            "on:\n", "# 注释：本腿只在手动授权时发布（publish=true），合并不会发布\non:\n", 1
        )
        assert annotated != original, "变异注入未生效（找不到 on: 锚点）"
        loaded = yaml.safe_load(annotated)
        assert _workflow_problems(loaded) == [], "只加一行注释竟判红（判据在吃自己的文案）"

    def test_script_mutations_are_all_detected(self):
        ci_src = _read(CI_SCRIPT)
        remote_src = _read(REMOTE_SCRIPT)
        assert isinstance(ci_src, str) and isinstance(remote_src, str), "发布脚本缺失 ⇒ 无法做脚本层红证"

        no_identity = ci_src.replace('[ "$REMOTE_INDEX_SHA" = "$LOCAL_SHA" ]', "true")
        assert no_identity != ci_src, "变异注入未生效（找不到产物身份断言）"
        no_protected = ci_src.replace('grep -q "^PROTECTED_UNCHANGED=1$"', "true")
        assert no_protected != ci_src, "变异注入未生效（找不到保留子树自证断言）"
        no_reserved_parse = ci_src.replace('PROTECTED_${p}_AFTER_SHA256', "PROTECTED_dropped_AFTER_SHA256")
        assert no_reserved_parse != ci_src, "变异注入未生效（找不到保留子树的 AFTER 读数解析）"
        root_delete = ci_src + '\nrm -rf "$STATIC_ROOT/"\n'
        remote_root_delete = remote_src + '\nrm -rf "$STATIC_ROOT"\n'
        drop_reserved_check = remote_src.replace('is_reserved "$name" && die', 'true')
        assert drop_reserved_check != remote_src, "变异注入未生效（找不到保留前缀的 fail-closed 行）"

        dist_push_src = _read(REPO_ROOT / DIST_PUSH_SCRIPT) or ""
        assert dist_push_src, f"读不到 {DIST_PUSH_SCRIPT} ⇒ 无法做第三层的脚本层红证"
        # 红证：取回 ref 改成**会漂**的分支名（`refs/heads/main`）
        drifting_ref = dist_push_src.replace(
            "git push --force \"$GIT_REMOTE\" \"$SHA:$PUSH_REF\"",
            'FETCH_URL="https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main"',
        ) + "\n" + 'FETCH_URL2="https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/$BRANCH"' 
        assert drifting_ref != dist_push_src, "变异注入未生效（找不到推送锚点）"
        # 红证：把孤儿单提交换成**普通提交**（有父 ⇒ 每次发布都往分支历史加一份 MB 级产物）
        non_orphan = dist_push_src.replace(DIST_COMMIT_FORM, 'git commit-tree "$TREE" -p "$SHA"')
        assert non_orphan != dist_push_src, "变异注入未生效（找不到 commit-tree 锚点）"

        # 第五层（组合层）：两个 ref 各司其职 —— 两种「混用」形态都必须被判红
        boot_uses_product_ref = ci_src.replace(BOOT_SCRIPT_REF_FORM, BOOT_PRODUCT_REF_FORM)
        assert boot_uses_product_ref != ci_src, "变异注入未生效（找不到引导 URL 的执行体 ref）"
        product_ref_drifted = ci_src.replace(CI_PUBLISH_PRODUCT_REF_FORM,
                                             "export H5_PUBLISH_SHA=$SCRIPT_SHA")
        assert product_ref_drifted != ci_src, "变异注入未生效（找不到远端产物 ref 的 export）"

        samples = {
            "CI：去掉「线上哈希 == 本次构建」断言": (ci_src, no_identity),
            "CI：去掉保留子树自证断言": (ci_src, no_protected),
            "CI：不再解析保留子树的 AFTER 读数": (ci_src, no_reserved_parse),
            "CI：新增未限定目标的删除": (ci_src, root_delete),
            "远端：新增未限定目标的删除": (remote_src, remote_root_delete),
            "远端：去掉「产物顶层出现保留前缀 ⇒ die」": (remote_src, drop_reserved_check),
            "CI：引导改回按**产物 ref** 取执行体（#6095 第五层形态）": (ci_src, boot_uses_product_ref),
            "CI：远端产物 ref 漂成执行体 ref（两个 ref 混用的反向）": (ci_src, product_ref_drifted),
        }
        undetected = []
        for name, (src, mutant) in samples.items():
            kwargs = {"ci_src": mutant} if src is ci_src else {"remote_src": mutant}
            if len(_workflow_problems(_load_workflow(), **kwargs)) == 0:
                undetected.append(name)
        # 第三层：dist 推送脚本的两种坏形态（`dist_src` 槽 = 该脚本面）
        for name, mutant in (("dist 推送：取回 ref 改成 refs/heads/main", drifting_ref),
                             ("dist 推送：孤儿单提交换成普通提交", non_orphan)):
            assert mutant != dist_push_src, f"{name} 的变异没生效"
            if len(_workflow_problems(_load_workflow(), dist_src=mutant)) == 0:
                undetected.append(name)
        assert undetected == [], f"这些脚本变异**没有被判红**（= 空断言）：{undetected}"

    def test_script_comment_only_edit_does_not_turn_red(self):
        """对照：脚本里**只加注释** ⇒ 不红（含把破坏性语句写进注释的形态）。"""
        remote_src = _read(REMOTE_SCRIPT) or ""
        annotated = remote_src.replace(
            "set -euo pipefail\n",
            "set -euo pipefail\n# 说明：本脚本绝不 rm -rf $STATIC_ROOT（这句是注释，不是动作）\n",
            1,
        )
        assert annotated != remote_src
        assert _workflow_problems(_load_workflow(), remote_src=annotated) == []


# ── 对账面 / 登记面 ─────────────────────────────────────────────────────────

def test_reconcile_has_the_c_end_leg_and_it_is_registered():
    """FM-E3：触发面与对账面**同批**接线；腿必须同时进登记册（条数派生，不写死）。"""
    reconcile = _read(RECONCILE_WF) or ""
    assert "reconcile_one c-end-h5 c-end-h5-publish.yml frontend/mini-app" in reconcile, (
        "deploy-reconcile.yml 里没有 c-end-h5 腿 ⇒ 改 frontend/mini-app 而 push 被 auto-merge 吞掉时"
        "**静默不发布**（#5001 同族）"
    )
    registry = _read(REPO_ROOT / "tests" / "unit_ci_workflows" / "test_swas_deploy_ci_hardening.py") or ""
    assert '"c-end-h5": "c-end-h5-publish.yml"' in registry, (
        "腿没有进 SVC_TO_DEPLOY_WORKFLOW 登记册 ⇒ `T1`（逐服务调用数 == 登记册条目数）会红"
    )
    # issue #5935 把它从**写死的 6** 改成**现取**：`--seen` 的取值范围 = 状态机脚本从
    # `reconcile_one` 调用算出的腿数（`$SEEN`）—— 写死的话，新加一条腿时读数不会自己跟上
    # （读数与事实不一致就是 #5264 的形态；现在「跟着腿数走」由代码结构保证，不再靠人记得改）。
    assert '--seen "${SEEN:-0}"' in reconcile, (
        "存活读数的 `--seen` 必须由 `$SEEN` 现取（腿数从 `reconcile_one` 调用算出），"
        "不许写死成 6 —— 写死就是 #5264 的形态"
    )
    assert 'SEEN=$((SEEN + 1))' in (REPO_ROOT / "scripts" / "deploy_reconcile_state.sh").read_text(
        encoding="utf-8"), "`$SEEN` 必须在状态机脚本里按腿逐个累加（不是别处另算一份）"


def test_reconcile_leg_dispatches_are_safe_manual_only():
    """对账的兜底 dispatch 也**不会**发布：workflow_dispatch 不带 input ⇒ 闸判红说明（不是发布）。"""
    wf = _load_workflow()
    inputs = _triggers(wf)["workflow_dispatch"]["inputs"]
    assert inputs["publish"]["default"] is False, "publish 默认不是 false ⇒ 对账 dispatch 会直接发布"
    publish_steps = [s for s in _steps(wf) if PUBLISH_SCRIPT in _run_text(s)]
    assert len(publish_steps) == 1
    assert PUBLISH_IF in _if_text(publish_steps[0]), "发布步骤没有消费 `mode == 'publish'`"
    mode = [s for s in _steps(wf) if MODE_STEP in str(s.get("name") or "")]
    assert len(mode) == 1 and GATE_INPUT in _run_text(mode[0]), "模式判定步没有读 `inputs.publish`"


def test_chain_files_are_registered_as_never_in_trigger():
    """发布链路自身的两个文件必须挂台账 + `never_in_trigger`（明文禁止「加进触发面消账」）。"""
    import json

    ledger = json.loads(RECONCILE_LEDGER.read_text(encoding="utf-8"))
    marks = {str(e["path"]): bool(e.get("never_in_trigger")) for e in ledger["entries"] if e.get("svc") == "c-end-h5"}
    for path in CHAIN_FORBIDDEN_IN_TRIGGER:
        assert path in marks, f"{path} 没有登记进缺口台账（未登记即红）"
        assert marks[path] is True, (
            f"{path} 的台账条目缺 `never_in_trigger: true` ⇒ 台账会把「加进触发面」当成合法消账路子，"
            f"而那正是本单禁止的（合并即发布）"
        )
    triggers = [str(p) for p in _triggers(_load_workflow())["push"]["paths"]]
    for path in CHAIN_FORBIDDEN_IN_TRIGGER:
        assert path not in triggers, f"{path} 出现在 on.push.paths 里（与 never_in_trigger 矛盾）"


# ── 新鲜度判据翻 gate（同批）───────────────────────────────────────────────

def test_freshness_guard_defaults_to_gate():
    """默认判红：陈旧 ⇒ `::error::` + exit 2（`--no-gate` 才是报告型）。"""
    text = _read(FRESHNESS_SCRIPT) or ""
    assert 'level = "warning" if not args.gate else "error"' in text, (
        "陈旧分支的输出等级不再由 gate 决定（翻红被撤掉了？）"
    )
    assert '"--no-gate", dest="gate", action="store_false"' in text, (
        "缺 `--no-gate`（默认判红的反向开关）"
    )
    assert text.count('if verdict == "stale" and args.gate:') == 1, "陈旧分支的判红出口不见了"
    assert "EXIT_STALE = 0" not in text and "EXIT_STALE, EXIT_UNKNOWN = 0, 1, 2, 3" in text, (
        "退出码常量被改动（EXIT_STALE 必须仍是 2）"
    )


def test_freshness_guard_still_has_no_cron_and_keeps_three_states():
    """⛔ 无 cron（用户 2026-09-21 裁定未被推翻）；三态分离（取不到读数 ≠ 新鲜）。"""
    wf = yaml.safe_load(_read(FRESHNESS_WF) or "")
    on = _triggers(wf if isinstance(wf, dict) else {})
    assert "schedule" not in on, "h5-freshness-guard 加了 schedule/cron（用户 2026-09-21 裁定：⛔ 无 cron）"
    assert WORKFLOW_DISPLAY_NAME in (on.get("workflow_run", {}) or {}).get("workflows", []), (
        f"workflow_run.workflows 里没有 {WORKFLOW_DISPLAY_NAME!r} ⇒ 本腿发布完成后不会立刻重判新鲜度"
    )
    inputs = (on.get("workflow_dispatch") or {}).get("inputs") or {}
    assert "no_gate" in inputs and inputs["no_gate"].get("default") is False, (
        "dispatch 面必须是反向开关 `no_gate`（默认 false = 判红）；旧的 `gate` 语义会让默认退回告警"
    )
    text = _read(FRESHNESS_SCRIPT) or ""
    assert 'return "unknown"' in text and "EXIT_UNKNOWN, EXIT_OK" not in text, "三态判定被改动"
    assert "def judge(" in text and 'if live is None:' in text and 'if source is None:' in text, (
        "三态分离（取不到线上读数 / 取不到源码改动 ⇒ unknown）被削弱"
    )


def test_freshness_workflow_passes_no_gate_only_when_asked():
    """workflow 只在显式勾 `no_gate` 时传 `--no-gate`（默认不传 ⇒ 判红）。"""
    wf = yaml.safe_load(_read(FRESHNESS_WF) or "")
    runs = "\n".join(_run_text(s) for s in ((wf.get("jobs") or {}).get("h5-freshness") or {}).get("steps") or [])
    assert 'GATE_FLAG="--no-gate"' in runs, "不再组装 `--no-gate`（反向开关没接线）"
    assert 'GATE_FLAG="--gate"' not in runs, "还在组装 `--gate`（旧语义 ⇒ 默认退回只告警）"


# ── 行为层：沙箱里真跑远端脚本（不联网、不碰真实静态根）──────────────────────

def _make_static_root(tmp_path: Path, manifest: bool = False, stale_chunk: bool = False) -> Path:
    """造「线上根」的沙箱：C 端旧产物 + **工人端 `w/`** + **商家端 `b/`** + 一个清单外的文件。"""
    root = tmp_path / "h5"
    (root / "js").mkdir(parents=True)
    (root / "css").mkdir()
    (root / "index.html").write_text("<!doctype html><title>C 端旧产物</title>", encoding="utf-8")
    (root / "js" / "app.js").write_text("// C 端旧 app.js", encoding="utf-8")
    (root / "css" / "app.css").write_text(".c-end-old{}", encoding="utf-8")
    (root / "w" / "src").mkdir(parents=True)
    (root / "w" / "index.html").write_text("<!doctype html><title>工人端</title>", encoding="utf-8")
    (root / "w" / "src" / "app.mjs").write_text("// worker app", encoding="utf-8")
    (root / "b" / "js").mkdir(parents=True)
    (root / "b" / "index.html").write_text("<!doctype html><title>商家端</title>", encoding="utf-8")
    (root / "b" / "js" / "app.js").write_text("// bmini app", encoding="utf-8")
    (root / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")
    if stale_chunk:
        (root / "chunk").mkdir()
        (root / "chunk" / "850.js").write_text("// 上一版留下的", encoding="utf-8")
    if manifest:
        import json
        managed = ["css", "index.html", "js"] + (["chunk"] if stale_chunk else [])
        (root / MANIFEST).write_text(json.dumps({"managed_top_level": managed}), encoding="utf-8")
    return root


def _make_dist(tmp_path: Path, ref: str = "/js/app.js", app_js: str = "// C 端新 app.js") -> Path:
    dist = tmp_path / "dist"
    (dist / "js").mkdir(parents=True, exist_ok=True)
    (dist / "css").mkdir(exist_ok=True)
    (dist / "index.html").write_text(
        f'<!doctype html><title>米高窗帘 · 小布智能助手</title><script defer src="{ref}"></script>'
        '<link href="/css/app.css" rel="stylesheet">',
        encoding="utf-8",
    )
    (dist / "js" / "app.js").write_text(app_js, encoding="utf-8")
    (dist / "css" / "app.css").write_text(".c-end-new{}", encoding="utf-8")
    return dist


def _run_remote(root: Path, dist: Path = None, *args: str, env_extra: dict | None = None):
    env = dict(os.environ)
    env["H5_STATIC_ROOT"] = str(root)
    env.pop("H5_PUBLISH_FROM_DIR", None)
    env.pop("H5_PUBLISH_SHA", None)
    if env_extra:
        env.update(env_extra)
    cmd = ["bash", str(REMOTE_SCRIPT)]
    if dist is not None:
        cmd += ["--from-dir", str(dist)]
    cmd += list(args)
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=180, cwd=str(REPO_ROOT),
    )


def test_sandbox_first_publish_requires_explicit_takeover(tmp_path):
    """首次发布：根上有无人认领的条目 ⇒ 拒绝（exit 2）、**什么都不改**，并打印将要替换的计划。"""
    root = _make_static_root(tmp_path)
    before = _tree(root)
    proc = _run_remote(root, _make_dist(tmp_path), "--apply")
    assert proc.returncode == 2, f"无人认领的根竟被接管（rc={proc.returncode}）：\n{proc.stdout}\n{proc.stderr}"
    assert "无人认领" in proc.stderr and "--takeover-first-publish" in proc.stderr, proc.stderr
    assert "PLANNED_ACTIONS_BEGIN" in proc.stdout, "拒绝时必须打印将要替换的条目（让人看清再决定）"
    assert _tree(root) == before, "拒绝路径上静态根被改动（红线）"

    # dry-run（默认）同样不写盘
    proc = _run_remote(root, _make_dist(tmp_path))
    assert proc.returncode == 2, f"dry-run 也应在「无人认领」上拒绝：{proc.stdout}"
    assert _tree(root) == before, "dry-run 改动了静态根"


def test_sandbox_publish_preserves_w_and_b_and_manifest_only_subtree(tmp_path):
    """🔴 本单最重要的一条：发布后 `w/` `b/` 与清单外文件**逐字节不变**，托管条目被替换。"""
    root = _make_static_root(tmp_path, manifest=True, stale_chunk=True)
    dist = _make_dist(tmp_path, app_js="// C 端新 app.js v2")
    w_before, b_before = _tree(root / "w"), _tree(root / "b")
    robots_before = _file_sha(root / "robots.txt")

    proc = _run_remote(root, dist, "--apply")
    assert proc.returncode == 0, f"发布失败：\n{proc.stdout}\n{proc.stderr}"

    # ① 身份：线上 index.html == 本次产物
    assert _file_sha(root / "index.html") == _file_sha(dist / "index.html")
    assert (root / "js" / "app.js").read_text(encoding="utf-8") == "// C 端新 app.js v2"
    # ② 陈旧托管条目被收敛（幂等的另一半）
    assert not (root / "chunk").exists(), "上一次托管的陈旧条目没有被收敛"
    # ③ 🔴 红线：w/ b/ 与清单外文件逐字节不变
    assert _tree(root / "w") == w_before, "工人端 w/ 被改动（红线）"
    assert _tree(root / "b") == b_before, "商家端 b/ 被改动（红线）"
    assert _file_sha(root / "robots.txt") == robots_before, "清单外文件被改动（红线）"
    # ④ 自证读数必须在输出里，且 BEFORE == AFTER（逐字）
    for p in RESERVED:
        before = re.search(rf"^PROTECTED_{p}_BEFORE_SHA256=(.+)$", proc.stdout, re.M)
        after = re.search(rf"^PROTECTED_{p}_AFTER_SHA256=(.+)$", proc.stdout, re.M)
        ib = re.search(rf"^PROTECTED_{p}_BEFORE_INDEX_SHA256=(.+)$", proc.stdout, re.M)
        ia = re.search(rf"^PROTECTED_{p}_AFTER_INDEX_SHA256=(.+)$", proc.stdout, re.M)
        assert all(isinstance(m, re.Match) for m in (before, after, ib, ia)), f"缺 {p} 的自证读数：\n{proc.stdout}"
        assert before.group(1).strip() == after.group(1).strip(), f"{p}/ 摘要前后不一致"
        assert ib.group(1).strip() == ia.group(1).strip(), f"{p}/index.html 哈希前后不一致"
        assert ib.group(1).strip() == _file_sha(root / p / "index.html")
    assert "PROTECTED_UNCHANGED=1" in proc.stdout
    assert "ROOT_INDEX_BEFORE_SHA256=" in proc.stdout and "ROOT_INDEX_AFTER_SHA256=" in proc.stdout


def test_sandbox_publish_is_idempotent(tmp_path):
    """连跑两次：**托管内容**逐字节一致；清单里除时间戳外的字段也一致（幂等的另一半）。"""
    import json

    root = _make_static_root(tmp_path, manifest=True)
    dist = _make_dist(tmp_path)
    first = _run_remote(root, dist, "--apply")
    assert first.returncode == 0, first.stdout + first.stderr
    # ⚠️ 清单**有意**写 `written_at_utc`（每轮发布的时间戳）⇒ 逐字节比较它会把「幂等」判成不幂等；
    #    故先摘掉清单比托管内容，再单独比清单里那三个**稳定**字段。
    tree = {k: v for k, v in _tree(root).items() if k != MANIFEST}
    m1 = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    second = _run_remote(root, dist, "--apply")
    assert second.returncode == 0, second.stdout + second.stderr
    assert {k: v for k, v in _tree(root).items() if k != MANIFEST} == tree, "连跑两次托管内容不一致（不幂等）"
    m2 = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    for key in ("managed_top_level", "published_index_sha256"):
        assert m1[key] == m2[key], f"清单的 `{key}` 在两次发布之间变了（{m1[key]!r} → {m2[key]!r}）"


def test_sandbox_refuses_product_that_references_the_other_apps(tmp_path):
    """产物层：index.html 引用 `/b/`（别的应用的命名空间）或相对路径 ⇒ 拒绝，且根不动。"""
    for ref, marker in (("/b/js/app.js", "别的应用"), ("./js/app.js", "相对路径")):
        root = _make_static_root(tmp_path / f"case-{abs(hash(ref))}", manifest=True)
        before = _tree(root)
        proc = _run_remote(root, _make_dist(tmp_path / f"d-{abs(hash(ref))}", ref=ref), "--apply")
        assert proc.returncode == 3, f"坏引用 {ref!r} 竟被发布：\n{proc.stdout}"
        assert marker in proc.stderr, f"判红信息里找不到 {marker!r}：{proc.stderr}"
        assert _tree(root) == before, f"拒绝 {ref!r} 时静态根被改动（红线）"


def test_sandbox_refuses_reserved_prefix_in_product_and_in_manifest(tmp_path):
    """结构层两条：产物顶层出现 `w/` ⇒ 拒绝；清单被污染（含 `w`）⇒ 拒绝。"""
    dist = _make_dist(tmp_path)
    (dist / "w").mkdir(exist_ok=True)
    (dist / "w" / "index.html").write_text("<!doctype html><title>伪装成工人端</title>", encoding="utf-8")
    root = _make_static_root(tmp_path / "r1", manifest=True)
    w_before = _tree(root / "w")
    proc = _run_remote(root, dist, "--apply")
    assert proc.returncode == 3, f"产物顶层的保留前缀竟被接受：\n{proc.stdout}"
    assert "保留前缀" in proc.stderr, proc.stderr
    assert _tree(root / "w") == w_before, "工人端被产物覆盖（红线）"

    import json
    root2 = _make_static_root(tmp_path / "r2")
    (root2 / MANIFEST).write_text(json.dumps({"managed_top_level": ["css", "index.html", "js", "w"]}), encoding="utf-8")
    w_before2 = _tree(root2 / "w")
    proc = _run_remote(root2, _make_dist(tmp_path / "d2"), "--apply")
    assert proc.returncode == 3, f"被污染的清单竟被按它删除：\n{proc.stdout}"
    assert _tree(root2 / "w") == w_before2, "按被污染的清单删除了工人端（红线）"


def test_sandbox_refuses_unsafe_targets_and_unreadable_manifest(tmp_path):
    """目标守卫：软链 / 不存在的根 / `/` / 坏清单 ⇒ 拒绝（fail-closed，且不新建目录）。"""
    dist = _make_dist(tmp_path)

    link = tmp_path / "link"
    real = _make_static_root(tmp_path / "real")
    link.symlink_to(real)
    proc = _run_remote(link, dist, "--apply")
    assert proc.returncode != 0 and "软链" in proc.stderr, f"软链静态根竟被接受：{proc.stdout}{proc.stderr}"

    absent = tmp_path / "nope" / "h5"
    proc = _run_remote(absent, dist, "--apply")
    assert proc.returncode != 0 and "不存在" in proc.stderr, f"不存在的根竟被接受：{proc.stdout}{proc.stderr}"
    assert not absent.exists(), "拒绝路径上不许建目录"

    proc = _run_remote(Path("/"), dist, "--apply")
    assert proc.returncode != 0 and "不能是 /" in proc.stderr, f"`/` 竟被接受：{proc.stdout}{proc.stderr}"

    root = _make_static_root(tmp_path / "r4")
    (root / MANIFEST).write_text("not json", encoding="utf-8")
    before = _tree(root)
    proc = _run_remote(root, dist, "--apply")
    assert proc.returncode != 0 and "读不出来" in proc.stderr, f"坏清单竟被接受：{proc.stdout}{proc.stderr}"
    assert _tree(root) == before, "坏清单路径上静态根被改动"


def test_sandbox_dry_run_by_default_changes_nothing(tmp_path):
    """默认 dry-run：打印计划、`PROTECTED_UNCHANGED=not-evaluated`、静态根逐字节不变。"""
    root = _make_static_root(tmp_path, manifest=True)
    before = _tree(root)
    proc = _run_remote(root, _make_dist(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY_RUN=1" in proc.stdout and "PROTECTED_UNCHANGED=not-evaluated" in proc.stdout
    assert _tree(root) == before, "dry-run 改动了静态根"


def test_reserved_subtree_digest_really_moves_when_touched(tmp_path):
    """红证（变异真被读到）：动一下 `w/` 里一个字节 ⇒ 两次采样必须**不再相等**。

    这条防的是「摘要恒等」这种空断言：如果 `subtree_digest()` 写坏（例如漏掉内容、只比路径），
    上面的「BEFORE == AFTER」会永远成立。这里直接对**摘要函数**做双侧取样。
    """
    root = _make_static_root(tmp_path, manifest=True)
    digest_cmd = (
        'cd "$1" && find . -type f -print0 | sort -z | while IFS= read -r -d "" f; do '
        'printf "%s  %s\\n" "${f#./}" "$(shasum -a 256 "$f" | awk \'{print $1}\')"; done '
        '| shasum -a 256 | awk \'{print $1}\''
    )

    def digest(path: Path) -> str:
        out = subprocess.run(["bash", "-c", digest_cmd, "_", str(path)], capture_output=True, text=True)
        return out.stdout.strip()

    before = digest(root / "w")
    assert before, "摘要为空 ⇒ 空断言"
    (root / "w" / "src" / "app.mjs").write_text("// worker app 被改了一个字节", encoding="utf-8")
    after = digest(root / "w")
    assert after and after != before, f"内容变了而摘要不变（摘要函数是空断言）：{before} == {after}"


# ── 落地面断言脚本自身的红/绿两面（防空断言）─────────────────────────────────

# 「上一版线上产物」的一页（08-30 那次发布的形态：结构相同、标题与注释不同 ⇒ 哈希不同）
STALE_C_END_PAGE = (
    '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"/>'
    "<title>米高窗帘 · 小布智能助手</title>"
    "<script>window.TARO_ENV = 'h5'</script>"
    '<script defer="defer" src="/js/2.js"></script>'
    '<script defer="defer" src="/js/app.js"></script>'
    '<link href="/css/app.css" rel="stylesheet"></head>'
    '<body><div id="app"></div><!-- 08-30 那版 --></body></html>'
).encode("utf-8")


class _NginxishServer:
    """一个**只实现本单用到的 nginx 语义**的本地 server（前缀 location + try_files + index）。

    `mode` 用来造四种坏形态：
      · ``ok``            —— 线上已按本单的部署生效（根 = 本次构建；`/w/` `/b/` 都是自己的产物）
      · ``stale_root``    —— 根还是**旧产物**（本单要治的形态本身：HTTP 200 但是 08-30 那版）
      · ``w_overwritten`` —— 根发布把**工人端** `/w/` 覆盖成了 C 端产物（红线）
      · ``b_overwritten`` —— 根发布把**商家端** `/b/` 覆盖成了 C 端产物（红线）
      · ``root_stray_ref``—— 根 index.html 引用了 `/b/js/app.js`（引用面串端）
      · ``root_falls_to_b`` —— 根级深层路径被 `/b/` 的 fallback 吃掉（路由面串端）
    """

    def __init__(self, root: Path, built: bytes, mode: str = "ok"):
        self.root = root
        self.built = built
        self.mode = mode
        self._server = None
        self._thread = None

    def _read(self, rel: str, default: bytes) -> bytes:
        f = self.root / rel
        return f.read_bytes() if f.is_file() else default

    def _route(self, path: str):
        c_end_built = self.built
        # 「根上是旧产物」= 线上没发布过这次的构建 ⇒ `/` 与 `/index.html` 与根级深层路径
        # 一起落到那份旧产物（三者同源，不能只让 `/` 旧、`/index.html` 新）
        c_end_old = STALE_C_END_PAGE
        w_page = self._read("w/index.html", b"<html>worker</html>")
        b_page = self._read("b/index.html", b"<html>bmini</html>")
        if path.startswith("/w/"):
            if self.mode == "w_overwritten":
                return c_end_built
            return w_page
        if path.startswith("/b/"):
            if self.mode == "b_overwritten":
                return c_end_built
            return b_page
        if self.mode == "stale_root":
            return c_end_old
        if path in ("/", "/index.html"):
            if self.mode == "root_stray_ref":
                # 直接在根页里塞一条指向**别的应用**命名空间的引用
                # （`</head>` 不在 stub 产物的字面里 ⇒ 用 rel 属性形态插入）
                return c_end_built.replace(
                    b'<link href="/css/app.css" rel="stylesheet">',
                    b'<link href="/css/app.css" rel="stylesheet">'
                    b'<script defer src="/b/js/app.js"></script>',
                )
            return c_end_built
        # 根级深层路径 ⇒ `location /` 的 `try_files $uri $uri/ /index.html`
        if self.mode == "root_falls_to_b":
            return b_page
        return c_end_built

    class _Handler(http.server.BaseHTTPRequestHandler):
        server_version = "NginxishTest/1.0"

        def log_message(self, *args):
            return None

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            body = self.server.route(path)  # type: ignore[attr-defined]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def __enter__(self):
        outer = self

        class _Server(http.server.ThreadingHTTPServer):
            def route(self, path):
                return outer._route(path)

        self._server = _Server(("127.0.0.1", 0), self._Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        for _ in range(100):
            with socket.socket() as sock:
                sock.settimeout(0.2)
                if sock.connect_ex(("127.0.0.1", self._server.server_address[1])) == 0:
                    break
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        return False


def _served_root(tmp_path: Path, built: bytes, dist: Path) -> Path:
    """线上根的形态：**已发布**（根 = 本次构建） + 工人端 `w/` + 商家端 `b/`（各自的产物）。"""
    root = tmp_path / "served"
    (root / "w").mkdir(parents=True)
    (root / "b").mkdir(parents=True)
    (root / "index.html").write_bytes(built)
    (root / "js").mkdir()
    (root / "js" / "app.js").write_bytes((dist / "js" / "app.js").read_bytes())
    (root / "w" / "index.html").write_text("<!doctype html><title>工人端</title>", encoding="utf-8")
    (root / "b" / "index.html").write_text("<!doctype html><title>商家端</title>", encoding="utf-8")
    return root


def _run_verify(base_url: str, dist: Path):
    env = dict(os.environ)
    return subprocess.run(
        ["bash", str(VERIFY_SCRIPT), base_url, str(dist)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, env=env, cwd=str(REPO_ROOT),
    )


def test_verify_served_is_green_on_correct_landing(tmp_path):
    dist = _make_dist(tmp_path)
    built = (dist / "index.html").read_bytes()
    root = _served_root(tmp_path, built, dist)
    with _NginxishServer(root, built, "ok") as base:
        proc = _run_verify(base, dist)
    assert proc.returncode == 0, f"落地面断言在正确落地上竟失败：\n{proc.stdout}\n{proc.stderr}"
    assert "✅ 全部通过" in proc.stdout


@pytest.mark.parametrize(
    "mode, marker",
    [
        ("stale_root", "≠ 本仓库产物"),
        ("w_overwritten", "/w/ 返回的是"),
        ("b_overwritten", "/b/ 返回的是"),
        ("root_stray_ref", "别的应用的命名空间"),
        ("root_falls_to_b", "期望回落到**根 index.html**"),
    ],
)
def test_verify_served_is_red_on_broken_landings(tmp_path, mode, marker):
    """坏形态必须判红（否则上面的绿是空断言），且**指名**是哪条判据。"""
    dist = _make_dist(tmp_path)
    built = (dist / "index.html").read_bytes()
    root = _served_root(tmp_path, built, dist)
    with _NginxishServer(root, built, mode) as base:
        proc = _run_verify(base, dist)
    assert proc.returncode == 1, f"坏形态 {mode} 竟判绿（空断言）：\n{proc.stdout}"
    assert "❌" in proc.stdout
    assert any(marker in line for line in proc.stdout.splitlines()), (
        f"判红信息里找不到 {marker!r}（红得不具体 = 排查时看不出是哪条判据）：\n{proc.stdout}"
    )
