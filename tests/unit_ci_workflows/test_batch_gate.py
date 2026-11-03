# case_ids: MC-012, MC-132
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012；本单新增的
#   auto-merge arm 面另挂 MC-132，见 .github/cases/misc.yml）
r"""批次统一验证入口 `scripts/batch-gate.sh` 的实例判据（issue #6012；#6055 / PR #6056 补就绪前置判定）。

## 治的形态（2026-10-02 17:24–17:29 CST 现场，读数现取）

机器级重活锁：1 个 `gate` 持锁、**7 个 gate 在跑**（6 个排队：已等 40 / 31 / 20 / 12 / 7 / 2 分钟）、
最高排队读数 `已等 2354s / 上限 2400s`；`load average` **21.6 / 43.6 / 61.3**（8 核）。
⇒ 类级病 = **「每个包各自跑一遍全量」× 「本机只装得下一份全量」**。
排他锁治的是 CPU 争用，治不了**份数**；本判据守的是份数。

#6055 补的第二半（PR #6056）：**份数**治住之后，**「时机」**成了现取缺口 —— `#6003` / `#6005` 这类
**与 base 冲突（GitHub 侧 DIRTY）** 的包被拉进批次 ⇒ 集成结果必然红、且红在**别人**身上
（面级归因指向错误对象）⇒ 白烧一次全量。⇒ 那一次全量**之前**逐包判「就绪」（无冲突 + PR checks 全绿），
**任一不就绪 ⇒ 拒绝**（exit 3，不跑全量）。

#6212 补的第三半（**时机**本身也会烂）：`--require-ready` 要求**非 draft**（draft 的 leg 不全 ⇒ pending），
而 `.github/workflows/automerge.yml` 恰在「非 draft」时 arm 原生 auto-merge —— 实测 2026-10-03：
转 ready → arm **17 秒**、arm → 合并 **4 分 26 秒** ⇒ 集成侧还没跑那一次全量，包就已经被合进 main
（#6206 现场踩中，那一次批次全量被跳过）。`gh pr merge --disable-auto` **不是**可靠控制：一次 push 触发的
`synchronize` 会让 `automerge.yml` **重新 arm**（#4829 实证）；`block/merge` 标签也拦不住**已 arm** 的
auto-merge。⇒ 把「**已 arm**」并入**同一个**就绪判定（三态 `0/1/3`），并给可复制的**解除 + 回读**命令
（回读与判定用**同一个**探针 ⇒ 两处口径不可能漂移）。

## 判据（每条都能单独变红）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | N 个包 ⇒ 那一次全量**恰好被调用 1 次** | 有人把 gate 挪进 merge 循环（退回「每包一次」）⇒ 调用数 = N |
| 2 | 调用数**不随 N 增长**（2 包 / 3 包都得 1） | 同上；这条是 1 的**判别力**对照（N 变而读数不变才叫「统一」） |
| 3 | 红 ⇒ 面级归因点到**碰该面的包**，且不把面外包算进来 | 归因退化成「把所有包都列一遍」/ 指认错包 ⇒ 红 |
| 4 | 分支不存在 ⇒ exit **3**（无法判定）且**没跑** gate | 把「读不到分支」读成「绿」或照跑一次 ⇒ 红 |
| 5 | 整合冲突 ⇒ exit **1**、**没跑** gate、**具名**冲突分支 | 冲突也照跑 gate（把「没跑」记成「跑过」）⇒ 红 |
| 6 | 跑完不残留 worktree（本命令自建的那份自己收） | 临时集成 worktree 堆积 ⇒ 红 |
| 7 | 包与 base **有冲突（DIRTY）** ⇒ 拒绝（exit 3）、**没跑** gate、给同步出口 | 不判冲突就把它拉进批次（#6003/#6005 的形态）⇒ 红 |
| 8 | PR 有 `fail` / `pending` ⇒ 拒绝（exit 3）、**没跑** gate | 把「CI 未绿」当就绪 ⇒ 红 |
| 11 | **`skipping` 不是红** ⇒ 该包仍就绪、那一次全量照跑（且只跑一次） | 把 `skipping` 并回红（#6216 的形态）⇒ 单模块包**恒不就绪** ⇒ 红 |
| 11' | **`state=CANCELLED`**（非 required，如 force-push 后陈旧 run）⇒ 与 skipping 同侧、不挡批次 | 把非 required 的 cancel 当红 ⇒ rebase 过的包恒不就绪 ⇒ 红 |
| 11'' | 桶名叫 `cancel` 但 **`state=FAILURE`** ⇒ **仍是红**、拒绝 | 把 `cancel` **整族**放行（「一律放行」的假修）⇒ 红 |
| 9 | **没有对应的 open PR** ⇒ 拒绝（exit 3）、**没跑** gate | 把「没开 PR」当就绪 ⇒ 红 |
| 10 | `gh` **在**但调用失败（无凭据/断网）⇒ **fail-closed 拒绝**（exit 3）+ 具名「无法判定 ≠ 就绪」 | 把「取不到 PR 状态」静默当就绪（fail-open）⇒ 红 |
| 10' | `gh` **不在 PATH**（PATH 桩驱动）⇒ 同上，且走「gh 不存在」具名分支 | 只有环境「碰巧没有 gh」才成立 ⇒ CI 上永远走不到（空断言）⇒ 红 |
| 11 | `--require-ready` **默认开启**（不传开关也判） | 默认值被改成 off ⇒ 判 11 红（沙箱里无 gh ⇒ 期望 fail-closed 却跑了 gate） |
| 12 | `--no-require-ready` ⇒ 跑，但**必须打印**「未跑（--no-require-ready）—— 这不是「就绪」」 | 逃生口静默跳过（看起来和「就绪」一样）⇒ 红 |
| 16 | **已 arm 原生 auto-merge** 的包 ⇒ 拒绝（exit 3）、**没跑** gate、印成 ❌（明确不就绪）+ PR 号 + `enabledAt` | 把「已 arm」当就绪（#6212 的形态：跑全量期间被秒合）⇒ 红 |
| 17 | **未 arm** ⇒ 该包就绪、那一次全量照跑（且只跑一次） | 把「未 arm」也判不就绪 ⇒ 批次恒启动不了（反向假红）⇒ 红 |
| 18 | `autoMergeRequest` **读不到**（空 stdout / 非 JSON / 字段缺失 / gh 调用失败）⇒ **fail-closed**（exit 3）+ ❓ + 具名 | 把「读不到」当「未 arm」（fail-open）⇒ 红 |
| 19 | 出口**可复制且含本次 PR 号**：解除 `gh pr merge <PR> --disable-auto` + **回读** `--check-arm <PR>` | 出口缺一条 / 印了别的 PR 号 ⇒ 红 |
| 20 | `--check-arm` 回读三态（仍 arm ⇒ **1** / 未 arm ⇒ **0** / 读不到 ⇒ **3**）且**幂等**（连跑两次逐字节一致） | 回读静默放行 / 把读不到当已解除 / 非幂等 ⇒ 红 |
| 21 | **集成工作区缺 `node_modules` 且本批命中前端面** ⇒ **具名「环境缺失」+ exit 3**（无法判定，**不是**红）且**没跑** gate | 缺依赖也照跑 ⇒ 前端腿 fail-closed 一片 ❌、面级归因把矛头指向某个包（issue #6834 的**假红**）⇒ 红 |
| 22 | **负控**：缺 `node_modules` 但本批**不**命中那两个面 ⇒ **不拦**、那一次全量照跑（且只跑一次） | 把「缺依赖」做成无条件拒绝 ⇒ 本来能跑的批次被拦（新的假红）⇒ 红 |
| 23 | `--install-deps` ⇒ 在**集成工作区**的模块目录里真跑 `npm ci`，备妥后再跑**一次** gate；**备妥失败仍 fail-closed**（具名 + exit 3 + 没跑 gate） | 装失败静默继续（把环境问题记成代码问题）/ 装失败被当成通过 / 装到主检出上 ⇒ 红 |
| 24 | **类级元守卫**：依赖表的模块集合必须 **==** `verify-all.sh` 里探 `node_modules` 的模块集合；表内每个探针名都必须在 `verify-all.sh` 里出现 | 任一侧新增/改名（gate 多探一个模块、或表里少一个探针）⇒ 备妥判定与 gate 不再同源 ⇒ 红 |
| 25 | **注入式红证**：把 `deps_missing()` 的探针循环删掉 ⇒ 判据 21 必红 | 删掉检测后判据 21 仍绿 ⇒ 那是空断言 ⇒ 红 |

## 注入式红证（`test_mutations_turn_the_suite_red`，§28.1 出口①）

判据 7~20 都能**单独**变红这件事，不是靠"这些断言写得很细"，而是**注入式实测**：
把真脚本复制进临时沙箱 → 做 9 处**定向变异**（存量 5 处 + #6212 的 4 处；每处断言唯一命中，
命中数 0 或 >1 即判红 = 变异没生效）→ 各自跑一次 → **必须命中具名断言读数**。
⇒ 判据不是空断言：变异体真红。本单新增的 4 处见 `MUTATIONS` 的第 6~9 项（逐条对应判据 16 / 18 / 20 / 19）。

判据 21~23（集成工作区的**依赖备妥**，issue #6834）走**同一套注入式红证**，载体是单独的一条判据 25
（`test_removing_the_deps_probe_turns_criterion_21_red`）：把 `deps_missing()` 的探针循环删掉 ⇒ 缺依赖
却「判不出缺口」⇒ 照跑那一次全量并 exit 0 ⇒ 判据 21 的三条读数（exit 3 / 没跑 gate / 具名「环境缺失」）
同时落空。注入方式与两段读数**写进 PR body**（§28.1 出口①）。

## 隔离（为什么这些判据是安全的）

全部在**自足临时仓库**里跑（`git init` + 桩 `verify-all.sh` + 桩 `gh`），**不碰共享检出、不跑真全量**：
判据造的是自己那几个分支与 worktree，`--base` 显式指向临时仓库的 `main`
（默认 `origin/main` 在临时仓库里不存在 —— 这正是「不许悄悄依赖环境」的形态）。
判据 1~6 走「未跑就绪判定」这条路（**显式** `--no-require-ready`）：
它们判的是**份数 / 归因 / 三态**，沙箱里既没有 remote 也没有真 PR ⇒ 就绪判定必然 fail-closed，
与本组判题无关（不是「为了让绿而关掉」—— 逃生口是脚本的**唯一**口子，且它必打印未跑声明）。
**判据 7~15 一律走真默认路径**（不传逃生口）。

⚠️ **两个环境相关的坑（CI 实测，2026-10-02）**：
① 「`gh` 不存在」这条路只能靠 **PATH 桩**驱动（把 `gh` 从 PATH 里摘干净）—— **不许**指望 CI 上没有 gh
（实测 runner 上 gh 是装着的、只是没凭据 ⇒ 走的是「gh 调用失败」那条分支）；
② 因此本文件对这两条**分别**判：`gh` 在但调用失败（挂桩 gh）与 `gh` 不在 PATH（`_slim_path`），
两条都断**语义 + 三态**（`❓ 无法判定` + 具名「无法判定 ≠ 就绪」+ exit 3 + 一次全量都没跑）。

⚠️ **DIRTY 的分支怎么造**（实测教训）：只在分支上改一行、而 base 没动那份文件 ⇒ `merge-tree` 是**快进**、
**退出码 0** —— 那**不是**冲突。真 DIRTY 的形态 = **分支切出后 main 前进了同一行**（`chapters-dirty`）；
第一版判据正是用了「快进分支」当 DIRTY，才把「不判冲突」的变异体放了过去。

## 边界（照实登记，§19.1）

- 桩替换了真 `verify-all.sh`：本判据**不判**真 gate 的通过条件（那是 `test_verify_all_*` 的事），
  只判**调用份数 / 归因 / 三态 / 就绪前置**这几件事；
- 桩替换了 `gh`：本判据**不判** `gh` 的真语义（真 API 的限流 / 权限 / 字段漂移**不在面内**），
  只判「拿到三种读数时脚本怎么处置」；
- 归因本身是**面级映射**：判据只锁「面内唯一候选时点名它、面内多候选时不指认唯一真凶」，
  不判「真凶确实是它」（那需要失败日志级语义，本仓没有该能力）；
- 判据不覆盖「就绪判定与真跑 gate 之间 base 前进」的竞态（`merge-tree` 是**快照**判定）；
- 本判据**不改**任何门禁的通过条件、不新增豁免。
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import uuid

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_REL = "scripts/batch-gate.sh"
SCRIPT_SRC = REPO / SCRIPT_REL

#: 桩 `verify-all.sh`：把「被调用了几次」写成可计数的读数（= 本判据的主读数）。
#: 退出码与失败项由环境变量注入 ⇒ 同一个桩既能演绿也能演红。
STUB = """#!/usr/bin/env bash
echo "call" >> "${BATCH_GATE_STUB_LOG:?}"
echo "变更集：1 个文件（桩）"
echo "✅ QA Growth Gate 预检"
if [ -n "${BATCH_GATE_STUB_EXTRA:-}" ]; then eval "${BATCH_GATE_STUB_EXTRA}"; fi
exit "${BATCH_GATE_STUB_RC:-0}"
"""

#: 桩 `gh`：让就绪判定的两种读数（PR 列表 / checks 桶）可注入。
#: 只识别脚本真会用的那两条子命令；其余一律非零（**不静默给数** —— 静默给数就是假绿方向）。
GH_STUB = """#!/usr/bin/env bash
echo "${1:-} ${2:-} ${3:-} ${4:-} ${5:-} ${6:-} ${7:-}" >> "${BATCH_GATE_GH_LOG:?}"
mode="${BATCH_GATE_GH_MODE:?}"
if [ "${1:-}" = "pr" ] && [ "${2:-}" = "list" ]; then
  case "$mode" in
    # 真 gh 在「无匹配 PR」时输出 `[]`（空数组）。**空 stdout** 是另一码事
    # （= 取不到读数 ⇒ 脚本按「无法判定」fail-closed；见 `_gh_json_pick` 的空白输入分支）。
    no-pr) printf '[]\n'; exit 0 ;;
    offline) echo "error: could not resolve host: api.github.com" >&2; exit 1 ;;
    *) printf '[{"number": %s}]\n' "${BATCH_GATE_GH_PR:-6801}"; exit 0 ;;
  esac
fi
if [ "${1:-}" = "pr" ] && [ "${2:-}" = "view" ]; then
  # ⚠️ 「未 arm」是**默认**：存量判据（fail / pending / all-green / …）都只关心 checks 面，
  # 本分支若默认给「已 arm」，它们会全体红在 arm 面上 —— 那会把存量判据变成在测新面（假红）。
  case "$mode" in
    armed)        printf '{"autoMergeRequest":{"enabledAt":"2026-10-03T07:48:04Z","mergeMethod":"SQUASH"}}\n' ;;
    unarmed)      printf '{"autoMergeRequest":null}\n' ;;
    arm-missing)  printf '{}\n' ;;          # 字段**整个缺失**（不是 null）⇒ 无法判定
    arm-empty)    : ;;                      # 空 stdout ⇒ 无法判定
    arm-nonjson)  printf 'not json at all\n' ;;
    arm-offline)  echo "error: could not resolve host: api.github.com" >&2; exit 1 ;;
    *)            printf '{"autoMergeRequest":null}\n' ;;
  esac
  exit 0
fi
if [ "${1:-}" = "pr" ] && [ "${2:-}" = "checks" ]; then
  case "$mode" in
    fail)    printf '[{"name":"ci workflow helper 判据集","state":"FAILURE","bucket":"fail"},{"name":"QA Growth Gate","state":"SUCCESS","bucket":"pass"}]\n' ;;
    cancel)  printf '[{"name":"Post-Merge Verify (定向跑判据面)","state":"CANCELLED","bucket":"cancel"},{"name":"QA Growth Gate","state":"SUCCESS","bucket":"pass"}]\n' ;;
    # 真失败但桶名叫 cancel（负向对照：state=FAILURE ⇒ **必须仍是红**，不许被 cancel 整族放行）
    cancel-fail) printf '[{"name":"某被取消桶名的真失败腿","state":"FAILURE","bucket":"cancel"},{"name":"QA Growth Gate","state":"SUCCESS","bucket":"pass"}]\n' ;;
    # 真实形态（issue #6216 的现场取数：#6213 实际 = 26 pass / 6 skipping / 1 cancel）：
    # 本仓 CI 按变更面**有意跳过**无关腿（`E2E 面判定`/`bmini H5 面判定`/`mini-app 面判定`）。
    skipping) printf '[{"name":"QA Growth Gate","state":"SUCCESS","bucket":"pass"},{"name":"admin-api unit tests","state":"SUCCESS","bucket":"pass"},{"name":"E2E quality gate","state":"SKIPPED","bucket":"skipping"},{"name":"xiaobu H5 visual regression","state":"SKIPPED","bucket":"skipping"},{"name":"bmini-app build (h5 + weapp)","state":"SKIPPED","bucket":"skipping"}]\n' ;;
    pending) printf '[{"name":"ci workflow helper 判据集","state":"PENDING","bucket":"pending"}]\n' ;;
    none)    printf '[]\n' ;;
    nonjson) printf 'not json at all\n' ;;
    offline) echo "error: could not resolve host: api.github.com" >&2; exit 1 ;;
    *)       printf '[{"name":"QA Growth Gate","state":"SUCCESS","bucket":"pass"},{"name":"Case Trust Gate","state":"SUCCESS","bucket":"pass"}]\n' ;;
  esac
  exit 0
fi
echo "gh stub: 未支持的调用：$*" >&2
exit 1
"""

#: 桩 `npm`（issue #6834 判据 23）：只判「脚本有没有把**真装**委派给集成工作区的 `npm ci`」——
#: 真下载不在本判据的射程内（CI 上也不该为判据拉几百 MB）。失败形态由 `BATCH_GATE_NPM_MODE=fail` 驱动。
#: 成功形态会**造出探针可执行文件**（否则备妥后仍缺 ⇒ 脚本 fail-closed 拒绝，判据就变成在测「装不上」）。
NPM_STUB = """#!/usr/bin/env bash
echo "npm $* @ $(pwd)" >> "${BATCH_GATE_NPM_LOG:?}"
if [ "${BATCH_GATE_NPM_MODE:-ok}" = "fail" ]; then
  echo "npm ERR! 桩：装不上（判据 23 的失败形态）" >&2
  exit 1
fi
mkdir -p "$(pwd)/node_modules/.bin"
for t in tsc jest taro; do
  printf '#!/usr/bin/env bash\\nexit 0\\n' > "$(pwd)/node_modules/.bin/${t}"
  chmod +x "$(pwd)/node_modules/.bin/${t}"
done
exit 0
"""

CI_FAIL = (
    'echo "❌ ci workflow helper 判据集（本地跑 CI 同名 job） (exit 1)";'
    'echo "失败项: ci workflow helper 判据集（本地跑 CI 同名 job）"'
)


def _script_text() -> str:
    return SCRIPT_SRC.read_text(encoding="utf-8")


def _build_repo(root: pathlib.Path, script_text: str) -> pathlib.Path:
    """造一个自足临时仓库（`main` + 四个包分支 + 一对冲突分支 + 可计数桩）。

    `script_text` 参数 = **注入点**：红证用变异后的脚本文本走同一条构建路径（真对象、真运行）。
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "batch-gate@test.invalid")
    _git(root, "config", "user.name", "batch-gate-test")

    (root / "scripts").mkdir()
    dst = root / SCRIPT_REL
    dst.write_text(script_text, encoding="utf-8")
    os.chmod(dst, 0o755)
    _write(root, "verify-all.sh", STUB)
    os.chmod(root / "verify-all.sh", 0o755)
    _write(root, "backend/admin-api/A.java", "base\n")
    _write(root, "backend/ai-agent-service/c.py", "base\n")
    _write(root, "frontend/admin-web/b.ts", "base\n")
    _write(root, "frontend/bmini-app/app.tsx", "base\n")
    _write(root, "tests/unit_ci_workflows/guard_a.py", "base\n")
    # admin-web 的依赖探针**提交进 base**（issue #6834 的夹具口径）：沙箱里没有 .gitignore ⇒
    # 「提交了」= 集成 worktree 检出后**有**这些文件 = 该模块依赖已就绪。真实仓库里 node_modules
    # 是未跟踪目录（**不随 worktree 复制**，这正是本单的病根）—— 沙箱只能这样表达「已就绪」。
    # bmini-app **故意不建探针** ⇒ 它在本夹具里代表「缺依赖的前端面」（判据 21~23 / 25 用它）。
    _write_exe(root, "frontend/admin-web/node_modules/.bin/tsc")
    _commit(root, "base")

    # pkg-a 碰 ci-helper 面（tests/unit_ci_workflows/**）与 admin-api 面
    _branch_with(root, "pkg-a", "tests/unit_ci_workflows/guard_a.py", "a\n")
    _branch_with(root, "pkg-b", "frontend/admin-web/b.ts", "b\n")
    _branch_with(root, "pkg-c", "backend/ai-agent-service/c.py", "c\n")
    # pkg-bmini 碰**缺依赖**的前端面（bmini-app）⇒ 判据 21 / 23 的目标分支
    _branch_with(root, "pkg-bmini", "frontend/bmini-app/app.tsx", "bmini\n")
    # 一对必然冲突的分支（同一文件同一行两侧都改）
    _branch_with(root, "conf-a", "shared.txt", "A\n")
    _branch_with(root, "conf-b", "shared.txt", "B\n")
    # 一个**真 DIRTY** 的包：分支切出后 main 也改了同一行 ⇒ 它与 base 冲突
    # （⚠️ 「只在分支上改一行」在 merge-tree 里是**快进**、不算冲突 —— 这正是 #6003/#6005 的形态：
    #   分支切出后主线前进了。实测：`git merge-tree --write-tree --name-only main <这类分支>` 退出码 1）
    _branch_with(root, "chapters-dirty", "config/app.yml", "settings: 3\n")
    _write(root, "config/app.yml", "settings: 2\n")
    _commit(root, "main advances")
    return root


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check)


def _write(root: pathlib.Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_exe(root: pathlib.Path, rel: str) -> None:
    """写一个**可执行**的探针桩（`deps_missing()` 用 `-x` 判就绪，不可执行的文件不算就绪）。"""
    _write(root, rel, "#!/usr/bin/env bash\nexit 0\n")
    os.chmod(root / rel, 0o755)


def _commit(root: pathlib.Path, msg: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)


def _branch_with(root: pathlib.Path, name: str, rel: str, text: str) -> None:
    """从 `main` 切一个新分支，改一个文件，提交，再切回 `main`。"""
    _git(root, "checkout", "-q", "-b", name, "main")
    _write(root, rel, text)
    _commit(root, name)
    _git(root, "checkout", "-q", "main")


def _link_tools(sandbox: pathlib.Path) -> pathlib.Path:
    """给 sandbox 挂上**可计数的 `gh` 桩**，返回桩目录（调用方把它前置进 `PATH`）。"""
    bindir = sandbox.parent / f"ghbin-{uuid.uuid4().hex}"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(GH_STUB, encoding="utf-8")
    os.chmod(gh, 0o755)
    return bindir


@pytest.fixture
def sandbox(tmp_path: pathlib.Path) -> pathlib.Path:
    """自足临时仓库：`main` + 三个包分支 + 一对冲突分支 + 可计数的 verify-all 桩。"""
    assert SCRIPT_SRC.is_file(), f"载体不存在：{SCRIPT_REL}"
    return _build_repo(tmp_path / "repo", _script_text())


def run_batch(
    root: pathlib.Path,
    *args: str,
    stub_rc: str = "0",
    stub_extra: str = "",
    gh_mode: str | None = None,
    gh_pr: str = "6801",
    path: str | None = None,
    extra_env: dict | None = None,
):
    """跑真脚本；返回 (CompletedProcess, 桩被调用的次数, gh 桩被调用的行)。

    两种环境形态：
      - `gh_mode=<模式>`：挂**桩 gh**（`all-green` / `fail` / `pending` / `no-pr` / `offline` …），
        走**真默认路径**（判就绪）；
      - 默认（`gh_mode=None`）：给命令行**显式**加上 `--no-require-ready` —— 存量判据 1~6 在本沙箱里
        **够不到** GitHub，故走「未跑就绪判定」这条路（判的是份数/归因/三态，不是就绪）。
        ⚠️ 逃生口**只有命令行这一个**（脚本有意不做环境变量逃生口）。
        （要跑**真默认路径且什么都不传**用 `run_raw`。）
    """
    log = root.parent / f"stub-{uuid.uuid4().hex}.log"
    env = dict(os.environ)
    env.pop("MIGAO_HEAVY_WAIT", None)
    env.update({"BATCH_GATE_STUB_LOG": str(log), "BATCH_GATE_STUB_RC": stub_rc,
                "BATCH_GATE_STUB_EXTRA": stub_extra})
    gh_calls: list[str] = []
    if gh_mode is None:
        if "--no-require-ready" not in args:
            args = ("--no-require-ready", *args)
    else:
        gh_log = root.parent / f"gh-{uuid.uuid4().hex}.log"
        env.update({"BATCH_GATE_GH_MODE": gh_mode, "BATCH_GATE_GH_LOG": str(gh_log),
                    "BATCH_GATE_GH_PR": gh_pr})
        env["PATH"] = f"{_link_tools(root)}{os.pathsep}{env.get('PATH', '')}"
    if path is not None:
        env["PATH"] = path
    if extra_env:            # 判据 23：挂桩 `npm` / 注入它的读数落点（其余一律不注入）
        env.update(extra_env)
    proc = subprocess.run(
        [str(root / SCRIPT_REL), "--base", "main", *args],
        cwd=str(root), capture_output=True, text=True, env=env, timeout=180,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    if gh_mode is not None:
        gh_calls = gh_log.read_text(encoding="utf-8").splitlines() if gh_log.exists() else []
    return proc, calls, gh_calls


# ── 判据 1~6：份数 / 归因 / 三态（issue #6012；这批**不**判就绪）────────────────

def test_one_gate_for_the_whole_batch(sandbox):
    """判据 1：N 个包 ⇒ 全量**一次**（不是每包一次）。"""
    proc, calls, _ = run_batch(sandbox, "pkg-a", "pkg-b")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(calls) == 1, f"gate 被调用 {len(calls)} 次（应为 1）：{calls}"
    assert "pkg-a" in proc.stdout and "pkg-b" in proc.stdout


def test_gate_call_count_does_not_scale_with_packages(sandbox):
    """判据 2（判别力）：2 包与 3 包的调用数都是 1 —— 与「每包一次」形态可判别。"""
    _, calls2, _ = run_batch(sandbox, "pkg-a", "pkg-b")
    _, calls3, _ = run_batch(sandbox, "pkg-a", "pkg-b", "pkg-c")
    assert (len(calls2), len(calls3)) == (1, 1), f"2 包 {len(calls2)} 次 / 3 包 {len(calls3)} 次"


def test_red_attributes_to_the_package_touching_the_face(sandbox):
    """判据 3：红 ⇒ 面级归因点到碰该面的包，且不把面外包算进来。"""
    proc, calls, _ = run_batch(sandbox, "pkg-a", "pkg-b", stub_rc="1", stub_extra=CI_FAIL)
    assert proc.returncode == 1
    assert len(calls) == 1, "红的时候也只该跑一次"
    m = re.search(
        r"失败项：.*ci workflow helper.*\n\s+面：ci workflow helper.*\n\s+面内包（可能引入方）：(\S+)",
        proc.stdout,
    )
    assert m, "归因段没有按「失败项 → 面 → 面内包」的形态打印：\n" + proc.stdout
    assert m.group(1) == "pkg-a", f"面内唯一候选应是 pkg-a，实得 {m.group(1)}"
    # pkg-b 只碰 admin-web，**不**该出现在 ci-helper 面的候选里
    assert "面内包：pkg-a、pkg-b" not in proc.stdout


def test_unknown_branch_is_undecidable_and_runs_nothing(sandbox):
    """判据 4：读不到分支 ⇒ exit 3 且**没跑**（「没跑」必须长得像「没跑」）。"""
    proc, calls, _ = run_batch(sandbox, "no-such-branch")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert calls == [], f"无法判定时不该跑 gate，实得 {calls}"
    assert "无法判定" in proc.stdout + proc.stderr


def test_conflict_stops_before_the_gate(sandbox):
    """判据 5：整合冲突 ⇒ exit 1、没跑 gate、具名冲突分支。"""
    proc, calls, _ = run_batch(sandbox, "conf-a", "conf-b")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert calls == [], f"冲突时不该跑 gate，实得 {calls}"
    assert "conf-b" in proc.stdout, "冲突分支没有具名"
    assert "没有跑" in proc.stdout
    assert "conf-a" in proc.stdout


def test_in_mode_runs_in_the_existing_worktree(sandbox, tmp_path):
    """`--in <worktree>`：在既有集成工作区里只跑那一次（环境已备时的形态）。"""
    wt = tmp_path / "integration"
    _git(sandbox, "worktree", "add", "--detach", str(wt), "main")
    proc, calls, _ = run_batch(sandbox, "--in", str(wt), "pkg-a")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(calls) == 1
    assert str(wt) in proc.stdout


def test_no_worktree_left_behind(sandbox):
    """判据 6：自建的那份临时集成 worktree 跑完自己收掉。"""
    run_batch(sandbox, "pkg-a", "pkg-b")
    out = _git(sandbox, "worktree", "list", "--porcelain").stdout
    wts = [ln for ln in out.splitlines() if ln.startswith("worktree ")]
    assert len(wts) == 1, f"临时集成 worktree 残留：{out}"


def test_help_and_usage_are_actionable(sandbox):
    """出口必须真可行动：usage 写清两种形态 + 「没跑 ≠ 通过」。"""
    proc = subprocess.run([str(sandbox / SCRIPT_REL)], cwd=str(sandbox),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "只跑一次" in proc.stderr, proc.stderr
    hel = subprocess.run([str(sandbox / SCRIPT_REL), "--help"], cwd=str(sandbox),
                         capture_output=True, text=True, timeout=60)
    assert hel.returncode == 0
    assert "--in" in hel.stdout and "退出码" in hel.stdout
    # ⚠️ `--help` 必须是**整个文件头**，不许写死行数区间 —— 实测：本包给头部加了「就绪判定」段后，
    # 写死的 `sed -n '1,58p'` 把「## 退出码」**从三态正文处截断**（标题在、0/1/3 看不见），
    # 而上面只断言「退出码」三个字 ⇒ 截断**不会红**。这三条锁住「三态正文 + 新逃生口」真的可见。
    for needle in ("0 = 那一次 gate 全绿", "1 = 红", "3 = 无法判定", "--no-require-ready",
                   # 判据 21 / 23 的归因分层必须**在 --help 里可见**（issue #6834）：三态 + 具名子类 +
                   # 备妥入口。缺任一项 ⇒ 上面那条截断教训就复发了（标题在、语义看不见）。
                   "环境缺失", "代码问题", "--install-deps"):
        assert needle in hel.stdout, f"--help 被截断了（缺 {needle!r}）：{hel.stdout}"


# ── 判据 7~12：就绪前置判定（issue #6055 / PR #6056）──────────────────────────

def test_dirty_package_is_refused_before_the_gate(sandbox):
    """判据 7：包与 base 有冲突（DIRTY）⇒ 拒绝（exit 3）、没跑 gate、出口可行动。

    形态来源（2026-10-02 实测）：`#6003` / `#6005` 这类 DIRTY 包被拉进批次 ⇒ 必红且归因指向别人。
    """
    proc, calls, gh_calls = run_batch(sandbox, "chapters-dirty", gh_mode="all-green")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"不就绪时**一次全量都不该跑**，实得 {calls}"
    assert "chapters-dirty" in out, "不就绪的包没有具名"
    assert "有冲突" in out, f"没有说清哪条不满足：{out}"
    assert "sync-main.sh --rebase" in out, "没有给出同步主线的出口命令"
    assert gh_calls == [], f"冲突是离线可判的 ⇒ 不该去问 gh（省一次网络调用），实得 {gh_calls}"


def test_red_required_checks_are_refused_before_the_gate(sandbox):
    """判据 8：PR checks 有 fail ⇒ 拒绝（exit 3）、没跑 gate、提示修红。"""
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="fail")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"不就绪时不该跑 gate，实得 {calls}"
    assert "PR #6801" in out, f"没有具名到 PR：{out}"
    assert "红" in out and "先修红" in out, f"没有给出修红出口：{out}"


def test_pending_checks_are_refused_before_the_gate(sandbox):
    """判据 8'：PR checks 有 pending（未完成）⇒ 拒绝（exit 3）、没跑 gate。"""
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="pending")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"不就绪时不该跑 gate，实得 {calls}"
    assert "未完成" in out, f"没有说清 pending：{out}"


def test_skipped_checks_are_not_red_and_do_not_block_the_batch(sandbox):
    """判据 11（issue #6216）：`skipping` **不是红** ⇒ 该包仍然就绪，那一次全量照跑。

    为什么必须有这条：本仓 CI 按变更面**有意跳过**无关腿（`E2E 面判定`/`bmini H5 面判定`/
    `mini-app 面判定`，见 #6160/#6170）⇒ 任何只动单一模块的包都必然带 `skipping`。
    判定式若把 `skipping` 与 `fail` 并列，该包就**恒不就绪** ⇒ 「一批一次全量」
    （D 口径、issue #6012）**永远启动不了**（实测 #6213：26 pass / 6 skipping / 0 fail 被拒）。

    ⚠️ 断言只吃**语义 + 三态**，不吃环境特定措辞。
    """
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="skipping")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"skipping 不该导致不就绪（这就是 #6216 的形态）：{out}"
    assert len(calls) == 1, f"就绪 ⇒ 那一次全量必须跑（且只跑一次），实得 {calls}"
    assert "skipping" in out, f"skipping 不许静默（「没跑」必须长得像「没跑」）：{out}"


def test_cancelled_check_is_not_red_and_does_not_block_the_batch(sandbox):
    """判据 11'（issue #6216 的另一半）：**`state=CANCELLED`** 的腿与 skipping 同侧 ⇒ 不挡批次。

    现场取证：`Post-Merge Verify (定向跑判据面)` 在 PR 上被 auto-cancel（force-push 后陈旧 run 被取消），
    而 `gh pr checks <PR> --required` = **required 全绿**、GitHub 自身判 `mergeable=MERGEABLE`
    ⇒ 它**不挡合并**。就绪判定的本意是「这包与 main 合并是否就绪」⇒ 把非 required 的 cancel 当红
    会让「rebase 过的包」恒不就绪（与 skipping 同一类恒拒绝）。
    """
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="cancel")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"CANCELLED 不该导致不就绪：{out}"
    assert len(calls) == 1, f"就绪 ⇒ 那一次全量必须跑（且只跑一次），实得 {calls}"
    assert "cancelled" in out, f"cancel 不许静默（必须计入并打印）：{out}"


def test_genuine_failure_with_cancel_bucket_is_still_red(sandbox):
    """判据 11''（负向对照）：桶名叫 `cancel` 但 **`state=FAILURE`** ⇒ **仍是红**、拒绝。

    防的形态：把「cancel 整族」一律放行（那就是「一律放行」的假修）。判据是 **state**，不是桶名。
    """
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="cancel-fail")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"不就绪时不该跑 gate，实得 {calls}"
    assert "某被取消桶名的真失败腿" in out, f"没有具名到那条真失败：{out}"


def test_missing_pr_is_refused_before_the_gate(sandbox):
    """判据 9：找不到对应 open PR ⇒ 拒绝（exit 3）、没跑 gate、提示先开 PR。"""
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="no-pr")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"不就绪时不该跑 gate，实得 {calls}"
    assert "没有对应的 open PR" in out, f"没有说清「无 PR」：{out}"
    assert "先开 PR" in out, f"没有给出开 PR 的出口：{out}"


def test_gh_unavailable_fails_closed_and_says_undecidable(sandbox):
    """判据 10：**`gh` 在、但调用失败**（无凭据 / 断网 / 限流）⇒ fail-closed（exit 3）、一次全量都没跑。

    这是 CI runner 上的**真实形态**（`gh` 装着、但拿不到 PR 读数）；不许 fail-open
    （把「取不到」当成「就绪」就是本条要拦的形态）。断言只吃**语义 + 三态**，不吃环境特定措辞。
    """
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="offline")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"无法判定时不该跑 gate（fail-closed），实得 {calls}"
    assert "❓" in out, f"没有印出「无法判定」标记：{out}"
    assert "无法判定 ≠ 就绪" in out, f"没有具名「无法判定 ≠ 就绪」：{out}"
    assert "gh pr list 失败" in out, f"没有给出无法判定的现取依据（pr list 那一步）：{out}"
    # 用**逐包就绪行的形态**判 fail-open（裸 `✅` 会误伤：脚本 footer 里就有「别把 ❓ 读成 ✅」）
    assert "✅ pkg-a：" not in out, f"不许把「取不到」印成就绪（fail-open）：{out}"


#: 脚本与判据跑起来真正需要的命令（逐个软链进 slim PATH；缺一个都会当场红，不会静默降级）。
_SLIM_TOOLS = ("git", "python3", "sed", "grep", "head", "tail", "tr", "date", "mktemp", "rm",
               "cat", "dirname", "basename", "env", "sh", "bash", "sort", "uniq", "cut", "wc",
               "mkdir", "cp", "mv", "ls", "printf", "sleep")


def _slim_path(workdir: pathlib.Path) -> str:
    """造一个**真的没有 gh** 的 PATH —— 用来驱动「`gh` 不在 PATH」那条分支。

    ⚠️ **只返回软链目录**：早先的写法在末尾缀了 `/usr/bin:/bin`，而 CI runner 上 `/usr/bin/gh` 是**存在**的
    ⇒ `command -v gh` 照样命中 ⇒ 判据走的是「gh 调用失败」那条分支，却被断言成「gh 不存在」的措辞
    （CI 上**永远走不到** = 空断言形态；`--check-weak` 只扫字面串，拦不住这种）。
    """
    bindir = workdir / f"slimbin-{uuid.uuid4().hex}"
    bindir.mkdir()
    for tool in _SLIM_TOOLS:
        found = shutil.which(tool)
        if found:
            (bindir / tool).symlink_to(found)
    return str(bindir)


def run_raw(root: pathlib.Path, *args: str, path: str | None = None):
    """**什么都不注入**地跑真脚本（不挂桩 gh、不传逃生口）—— 判据 10'/11 与**红证**走这条路。

    返回 (CompletedProcess, gate 被调用次数)。
    """
    log = root.parent / f"stub-{uuid.uuid4().hex}.log"
    env = dict(os.environ)
    env.pop("MIGAO_HEAVY_WAIT", None)
    env.update({"BATCH_GATE_STUB_LOG": str(log), "BATCH_GATE_STUB_RC": "0",
                "BATCH_GATE_STUB_EXTRA": ""})
    if path is not None:
        env["PATH"] = path
    proc = subprocess.run([str(root / SCRIPT_REL), "--base", "main", *args],
                          cwd=str(root), capture_output=True, text=True, env=env, timeout=180)
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return proc, calls


def test_gh_missing_from_path_fails_closed(sandbox):
    """判据 10'：`gh` **不在 PATH** ⇒ fail-closed（exit 3）、一次全量都没跑、具名「无法判定 ≠ 就绪」。

    ⚠️ 这条路必须由 **PATH 桩**驱动（`_slim_path`）—— CI runner 上 `gh` 是**装着**的，
    靠环境「碰巧没有 gh」写断言 ⇒ 该断言在 CI 上**永远走不到**（空断言）。故先自证桩生效。
    """
    slim = _slim_path(sandbox.parent)
    assert shutil.which("gh", path=slim) is None, f"PATH 桩失效（还能找到 gh）：{slim}"
    proc, calls = run_raw(sandbox, "pkg-a", path=slim)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"gh 不在 PATH 时不该跑 gate（fail-closed），实得 {calls}"
    assert "❓" in out, f"没有印出「无法判定」标记：{out}"
    assert "无法判定 ≠ 就绪" in out, f"没有具名「无法判定 ≠ 就绪」：{out}"
    assert "gh 不存在" in out, f"PATH 桩生效时应走「gh 不存在」那条具名分支：{out}"
    # 用**逐包就绪行的形态**判 fail-open（裸 `✅` 会误伤：脚本 footer 里就有「别把 ❓ 读成 ✅」）
    assert "✅ pkg-a：" not in out, f"不许把「取不到」印成就绪（fail-open）：{out}"


def test_require_ready_is_on_by_default(sandbox):
    """判据 11：**不传任何开关**也判就绪（沙箱里没有真 PR/remote ⇒ 期望 fail-closed 拒绝、没跑 gate）。

    与判据 10' 的分别：这条判的是**默认值**（有没有开），只断三态与「没跑全量」；
    至于「无法判定具体走哪条具名分支」由 10'（gh 不在 PATH）与 10（gh 在但调用失败）各自承担。
    """
    slim = _slim_path(sandbox.parent)
    assert shutil.which("gh", path=slim) is None, f"PATH 桩失效（还能找到 gh）：{slim}"
    proc, calls = run_raw(sandbox, "pkg-a", path=slim)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"默认路径下不就绪时不该跑 gate，实得 {calls}"
    assert "就绪前置判定（--require-ready 默认开启" in out, f"默认没有开就绪判定：{out}"
    assert "❓" in out, f"默认路径没有印出「无法判定」标记：{out}"
    assert "无法判定 ≠ 就绪" in out, f"默认路径没有 fail-closed：{out}"


def test_no_require_ready_runs_but_says_it_was_skipped(sandbox):
    """判据 12：逃生口 = **显式** `--no-require-ready` ⇒ 跑 gate，但必须打印「未跑…不是就绪」。"""
    proc, calls, _ = run_batch(sandbox, "--no-require-ready", "pkg-a", "pkg-b")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert len(calls) == 1, f"逃生口下仍只跑一次全量，实得 {calls}"
    assert "--no-require-ready" in out, f"没有说明是哪条路跳过的：{out}"
    assert "这不是「就绪」" in out, f"跳过必须出声（不许静默，看起来像「就绪」）：{out}"


def test_all_ready_runs_exactly_one_gate(sandbox):
    """判据 13（正向路径不回归）：全部就绪 ⇒ 正常跑**一次** gate 并绿。"""
    proc, calls, gh_calls = run_batch(sandbox, "pkg-a", "pkg-b", gh_mode="all-green")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert len(calls) == 1, f"全绿路径下 gate 调用数应为 1，实得 {calls}"
    assert "全部 2 个包就绪" in out, f"没有打印就绪结论：{out}"
    assert "分支不存在" not in out, "就绪时不该出现任何「分支不存在」的噪声"
    # 每个包都查过 PR（两个包各一次 list + 一次 checks）
    assert len([ln for ln in gh_calls if "list" in ln]) == 2, f"gh 调用读数：{gh_calls}"


# ── 判据 16~20：**已 arm 的 auto-merge 也是「不就绪」**（issue #6212）────────────

def test_armed_auto_merge_is_refused_before_the_gate(sandbox):
    """判据 16：PR 的 auto-merge **已 arm** ⇒ 拒绝（exit 3）、**没跑** gate、印成 ❌ + PR 号 + enabledAt。

    治的形态（#6206 实测）：`--require-ready` 要求非 draft，而 `automerge.yml` 恰在非 draft 时 arm
    ⇒ 集成侧还没跑那一次全量，包就能被秒合（转 ready → arm 17 秒 → 合并 4 分 26 秒）。
    """
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="armed")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"已 arm 的包**一次全量都不该跑**（跑完它可能已被合掉），实得 {calls}"
    assert "❌ pkg-a（不就绪）" in out, f"没有印成「明确不就绪」（而不是「无法判定」）：{out}"
    assert "已 arm" in out, f"没有说清是哪条不满足：{out}"
    assert "2026-10-03T07:48:04Z" in out, f"没给出 enabledAt 现取读数：{out}"
    assert "❓ pkg-a（**无法判定 ≠ 就绪**）" not in out, f"「已 arm」是**明确不就绪**，不该退化成「无法判定」：{out}"


def test_unarmed_auto_merge_is_ready(sandbox):
    """判据 17（正向对照）：**未 arm** ⇒ 该包就绪、那一次全量照跑（且只跑一次）。

    这条是判据 16 的判别力对照：判定若退化成「一律不就绪」，判据 16 仍会绿 ⇒ 必须由本条抓住。
    """
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="unarmed")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert len(calls) == 1, f"未 arm ⇒ 就绪 ⇒ 应跑且只跑一次，实得 {calls}"
    assert "✅ pkg-a：" in out, f"未 arm 的包没有被印成就绪：{out}"
    assert "auto-merge 未 arm" in out, f"就绪结论没有把 arm 面摆出来（读者看不出「判过」）：{out}"


@pytest.mark.parametrize("mode", ["arm-empty", "arm-nonjson", "arm-missing", "arm-offline"])
def test_unreadable_auto_merge_fails_closed(sandbox, mode):
    """判据 18：`autoMergeRequest` **读不到** ⇒ fail-closed（exit 3）、**没跑** gate、❓ 具名。

    四种坏读数（空 stdout / 非 JSON / 字段缺失 / gh 调用失败）都必须走「无法判定」——
    **读不到≠未 arm**：它此刻可能真的已 arm，当成「就绪」就是 fail-open。
    """
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode=mode)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, f"[{mode}] {out}"
    assert calls == [], f"[{mode}] 读不到 auto-merge 状态时不该跑全量（fail-closed），实得 {calls}"
    assert "❓ pkg-a（**无法判定 ≠ 就绪**）" in out, f"[{mode}] 没有印出「无法判定」：{out}"
    assert "auto-merge 状态读不到" in out, f"[{mode}] 没具名是哪一档读不到：{out}"
    assert "✅ pkg-a：" not in out, f"[{mode}] 把「读不到」印成就绪（fail-open）：{out}"


def test_disarm_and_readback_commands_are_actionable(sandbox):
    """判据 19：出口**可复制、含本次 PR 号**（必须两条：解除 + 回读）。

    ⚠️ 用 `gh_pr="6212"`（而不是默认 6801）判「**含 PR 号**」：若实现把 PR 号写死/印错号，
    `gh pr merge 6212 --disable-auto` 与 `--check-arm 6212` 就不会同时出现 ⇒ 判据当场红。
    """
    proc, _, _ = run_batch(sandbox, "pkg-a", gh_mode="armed", gh_pr="6212")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert "gh pr merge 6212 --disable-auto" in out, f"没有给可复制的**解除**命令：{out}"
    assert "./scripts/batch-gate.sh --check-arm 6212" in out, f"没有给**当场回读**命令：{out}"
    assert "6801" not in out, f"印了别的 PR 号（说明没按现取的 PR 号拼命令）：{out}"
    assert "gh pr merge 6212 --disable-auto" in out and "--check-arm 6212" in out


def test_check_arm_readback_is_tri_state_and_idempotent(sandbox):
    """判据 20：`--check-arm` 回读 —— 仍 arm ⇒ **1**、未 arm ⇒ **0**（幂等）、读不到 ⇒ **3**。

    为什么回读必须是**独立入口**：解除（`--disable-auto`）不持久，一次 push 会重新 arm（#4829）
    ⇒ 「我跑过 disarm」不是证据；把回读做成可再跑的命令，判定与解除之间才有闭环。
    """
    armed, calls, _ = run_batch(sandbox, "--check-arm", "6212", gh_mode="armed")
    out = armed.stdout + armed.stderr
    assert armed.returncode == 1, f"仍 arm ⇒ exit 1（明确不就绪）：{out}"
    assert "仍 arm" in out and "#6212" in out, f"没有具名「仍 arm」+ PR 号：{out}"
    assert calls == [], f"回读是只读入口 ⇒ 不该跑全量，实得 {calls}"

    one, calls2, _ = run_batch(sandbox, "--check-arm", "6212", gh_mode="unarmed")
    two, _, _ = run_batch(sandbox, "--check-arm", "6212", gh_mode="unarmed")
    assert one.returncode == 0, one.stdout + one.stderr
    assert "未 arm" in one.stdout, one.stdout
    assert one.stdout == two.stdout, f"回读必须**幂等**（同一输入连跑两次逐字节一致）：\n{one.stdout}\n---\n{two.stdout}"
    assert calls2 == [], f"回读是只读入口 ⇒ 不该跑全量，实得 {calls2}"

    blind, _, _ = run_batch(sandbox, "--check-arm", "6212", gh_mode="arm-nonjson")
    out3 = blind.stdout + blind.stderr
    assert blind.returncode == 3, f"读不到 ⇒ 3（不许当 0/1 读）：{out3}"
    assert "无法判定" in out3, f"没有印出「无法判定」：{out3}"


# ── 判据 21~25：集成工作区的**依赖备妥**（issue #6834）─────────────────────────────
#
# 病灶（issue #6834 现场读数）：集成工作区 = `git worktree add` 出来的**新检出** ⇒ 没有 `node_modules`
# ⇒ 变更集命中 admin-web / bmini-app 时，`verify-all.sh gate` 的那条腿走 report_strict ⇒ fail-closed ❌
# ⇒ 整批 exit 1。**归因错**：看起来像「这批包里有人把代码改坏了」，真因是工作区没装依赖。
#
# ⚠️ 这一组**一律显式** `--no-require-ready`（`run_batch` 的默认形态）：沙箱里没有 gh，就绪判定会先
# fail-closed（exit 3）⇒ 不隔开的话「exit 3 / 没跑 gate」会**因为别的原因**成立 = 空断言（判据 21 的
# 三条读数就全部失去判别力）。故每条都另断**依赖段独有的具名读数**（「依赖备妥判定」/「环境缺失」）。

_TABLE_ROW = re.compile(r"printf '([a-z0-9-]+)\\t(frontend/([a-z0-9-]+))\\t([a-z ]+)\\n'")

#: 判据 25 的**注入点**：把探针循环换成空循环（= 「检测被删掉」的最小形态）。
_DEPS_PROBE_OLD = '  for t in $2; do [ -x "${nd}/${t}" ] || miss="${miss} ${t}"; done'
_DEPS_PROBE_NEW = '  for t in $2; do :; done  # 变异：删掉探针（判据 25 的注入点）'


def _npm_stub(workdir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """挂**可计数的 `npm` 桩**，返回 (桩目录, 读数日志)。调用方把桩目录前置进 PATH。"""
    bindir = workdir / f"npmbin-{uuid.uuid4().hex}"
    bindir.mkdir()
    log = workdir / f"npm-{uuid.uuid4().hex}.log"
    npm = bindir / "npm"
    npm.write_text(NPM_STUB, encoding="utf-8")
    os.chmod(npm, 0o755)
    return bindir, log


def _npm_env(bindir: pathlib.Path, log: pathlib.Path, mode: str = "ok") -> dict:
    return {"PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
            "BATCH_GATE_NPM_LOG": str(log), "BATCH_GATE_NPM_MODE": mode}


def test_missing_deps_on_a_frontend_face_is_named_environment_gap(sandbox):
    """判据 21（issue #6834 ①）：缺 `node_modules` + 本批命中前端面 ⇒ **具名「环境缺失」+ exit 3**、没跑 gate。

    「不是失败」必须能被**读出来**：退出码 3（不是 1）+ 输出里没有「本批未通过」这类红结论。
    """
    proc, calls, _ = run_batch(sandbox, "pkg-bmini")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"环境缺失时**一次全量都不该跑**（跑了就是把环境问题记成判据红），实得 {calls}"
    assert "依赖备妥判定" in out, f"没有走到依赖备妥判定（下面三条就成了空断言）：{out}"
    assert "环境缺失" in out, f"没有具名「环境缺失」：{out}"
    assert "无法判定" in out, f"没有说清这是「无法判定」而不是「失败」：{out}"
    assert "bmini-app" in out and "tsc" in out, f"没有具名缺的是哪个模块 / 哪个探针：{out}"
    assert "本批未通过" not in out, f"环境缺失被打成了「红」（就还是 issue #6834 的归因错）：{out}"
    assert "--install-deps" in out, f"出口没给可行动的备妥入口：{out}"
    # 出口必须**真可行动**：本命令默认结束即删工作区 ⇒ 「手动 cd 进去装」那条出口必须带 --keep，
    # 否则照抄的人 cd 到一个已被删掉（或即将被删）的目录（那是「出口不可执行」）。
    assert "--keep" in out, f"手动备妥那条出口没带 --keep（集成工作区默认结束即删）：{out}"
    assert "没跑" in out, f"「没跑」必须长得像「没跑」：{out}"


def test_missing_deps_without_a_frontend_face_runs_normally(sandbox):
    """判据 22（**负控**）：缺 `node_modules` 但本批**不**命中前端面 ⇒ 不拦、那一次全量照跑。

    夹具形态即现场形态：`bmini-app` 一直缺依赖（本夹具不建探针），而 `pkg-c` 只碰后端。
    ⚠️ 这条防的是「修成无条件拒绝」——那会把本来能跑的批次拦下来（**新的假红**）。
    """
    proc, calls, _ = run_batch(sandbox, "pkg-c")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert len(calls) == 1, f"不命中前端面时 gate 必须照跑（且只跑一次），实得 {calls}"
    assert "无需备妥" in out, f"「本次不需要备妥」必须打出来（「没判」要长得像「没判」）：{out}"
    assert "环境缺失" not in out, f"不命中前端面却被拦了（新的假红）：{out}"


def test_install_deps_runs_npm_ci_inside_the_integration_worktree(sandbox):
    """判据 23：`--install-deps` ⇒ 在**集成工作区**的模块目录里真跑 `npm ci`，备妥后再跑**一次** gate。

    读数钉三件事（任何一条不成立就说明备妥跑错了地方/跑错了命令）：
      ① 只调用一次 `npm`，argv 含 `ci` 与 `--prefer-offline`（锁文件决定内容 + 复用全局缓存）；
      ② cwd 是**集成 worktree**（路径含 `/batch-`）的 `frontend/bmini-app` —— 不是主检出
         （软链 / 在主检出上装 = issue #5930 的形态）；
      ③ 备妥后 gate 照跑一次（依赖就绪**不改变**门禁语义）。
    """
    bindir, log = _npm_stub(sandbox.parent)
    proc, calls, _ = run_batch(sandbox, "--install-deps", "pkg-bmini",
                               extra_env=_npm_env(bindir, log))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert len(calls) == 1, f"备妥成功 ⇒ 那一次全量照跑（且只跑一次），实得 {calls}"
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    assert len(lines) == 1, f"`npm` 调用读数：{lines}"
    assert " ci " in f" {lines[0]} " and "--prefer-offline" in lines[0], f"没走 npm ci：{lines[0]}"
    assert "/batch-" in lines[0], f"装到了**主检出**上（集成工作区才该装）：{lines[0]}"
    assert lines[0].rstrip().endswith("frontend/bmini-app"), f"cwd 不是缺依赖的那个模块：{lines[0]}"
    assert "依赖已备妥" in out, f"备妥结论没打印：{out}"


def test_install_deps_failure_stays_fail_closed(sandbox):
    """判据 23'（fail-closed）：`npm ci` 失败 ⇒ **具名**「环境缺失（备妥失败）」+ exit 3 + 没跑 gate。

    ⚠️ 这一条防的是最危险的退化：装不上就「照样跑」——那会把环境问题继续记成 ❌（回到本单修前的形态），
    或者更糟：把它读成通过（假绿）。
    """
    bindir, log = _npm_stub(sandbox.parent)
    proc, calls, _ = run_batch(sandbox, "--install-deps", "pkg-bmini",
                               extra_env=_npm_env(bindir, log, mode="fail"))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"备妥失败时不该跑 gate（fail-closed），实得 {calls}"
    assert "环境缺失" in out and "备妥失败" in out, f"没有具名「备妥失败」：{out}"
    assert "本批未通过" not in out, f"备妥失败被打成了红（归因错）：{out}"


def test_deps_table_stays_in_sync_with_the_gate_legs_probes():
    """判据 24（**类级元守卫**）：依赖表的模块集合 ⇄ `verify-all.sh` 里探 `node_modules` 的模块集合。

    为什么必须有这条：`batch-gate.sh` 的依赖表是 `verify-all.sh` 那两条 report_strict 腿的**镜像**。
    任一侧漂移都不会自己变红 ——
      · gate 多了一条要 node_modules 的腿（例如将来给 mini-app 加腿）而表没跟上 ⇒ 那一面**继续假红**；
      · 表里多一个模块而 gate 根本不探它 ⇒ **误拦**本来能跑的批次。
    两向都由本判据现取核对（不写死数字、不复制一份清单）。
    """
    rows = _TABLE_ROW.findall(_script_text())
    assert rows, "依赖表取不到（表被删 / 改了形态）⇒ 本元守卫会退化成空断言"
    table_modules = {mod for _name, _dir, mod, _tools in rows}
    verify_text = (REPO / "verify-all.sh").read_text(encoding="utf-8")
    probed = set(re.findall(r"frontend/([a-z0-9-]+)/node_modules", verify_text))
    assert table_modules == probed, (
        "依赖表与 verify-all.sh 的探针面不一致："
        f"表={sorted(table_modules)} / verify-all={sorted(probed)}"
        "（少一个 ⇒ 该面继续假红；多一个 ⇒ 误拦）")
    for name, _dir, _mod, tools in rows:
        for tool in tools.split():
            assert tool in verify_text, (
                f"{name} 的探针 {tool!r} 在 verify-all.sh 里找不到 ⇒ 两处已漂（备妥判定与 gate 不再同源）")
    assert "worker-h5" not in table_modules, (
        "worker-h5 零依赖（只探 node）⇒ 列进依赖表会误拦本来能跑的批次（判据 22 的反面）")


def test_removing_the_deps_probe_turns_criterion_21_red(tmp_path):
    """判据 25（**注入式红证**，§28.1 出口① / 本单判据 ④）：把探针删掉 ⇒ 判据 21 必红。

    变异体上「缺依赖」判不出来 ⇒ 照跑一次全量并 exit 0 ⇒ 判据 21 的三条读数（exit 3 / 没跑 gate /
    具名「环境缺失」）**同时落空**。⇒ 判据 21 不是空断言：删掉检测它真的会红。
    """
    assert _DEPS_PROBE_NEW not in _script_text(), "真脚本里已含变异文本（红证会变成自证）"
    mutant = _mutated_repo(tmp_path, _DEPS_PROBE_OLD, _DEPS_PROBE_NEW)
    proc, calls, _ = run_batch(mutant, "pkg-bmini")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"变异体应放行（这正是判据 21 要拦的形态）：{out}"
    assert len(calls) == 1, f"变异体应照跑那一次全量，实得 {calls}：{out}"
    assert "环境缺失" not in out, f"变异体仍报「环境缺失」⇒ 注入点没生效：{out}"


# ── 注入式红证（§28.1 出口①）：变异体必须真红 ────────────────────────────────

#: 四处**定向**变异：每处的 `old` 在真脚本里**恰好出现一次**（命中数 0 或 >1 即判红 =
#: 变异没生效，红证就成了空断言 —— 这条自证是本判据的一部分，不是注释）。
#: 每条变异对应它应当打红的那条判据（`expected`）与用来触发它的包分支（`branch`）。
MUTATIONS = [
    (
        "冲突不就绪 → 就绪",
        '    not_ready "$b" "与基准 ${BASE} 有冲突',
        '    ready_ok "$b" "与基准 ${BASE} 有冲突',
        "not_ready_became_ready",
        "chapters-dirty",
        "offline",   # 非 None ⇒ 走真就绪判定（gh_mode=None 会注入逃生口，变异体就抓不住了）
    ),
    (
        "无 PR 不就绪 → 就绪",
        '    not_ready "$b" "没有对应的 open PR',
        '    ready_ok "$b" "没有对应的 open PR',
        "not_ready_became_ready",
        "pkg-a",
        "no-pr",
    ),
    (
        "无法判定 → 就绪（fail-open：把 undecidable 整族改成 ready）",
        r"undecidable() { printf '?\t%s\t%s\n'",
        r"undecidable() { printf 'o\t%s\t%s\n'",
        "undecidable_became_ready",
        "pkg-a",
        "offline",
    ),
    (
        "就绪判定默认关（--require-ready 默认开启 → 关闭）",
        "READY=1\n",
        "READY=0\n",
        "default_off",
        "pkg-a",
        "offline",
    ),
    (
        "逃生口的「未跑」声明被摘掉（跳过变成静默）",
        '  echo "⏭️ 就绪判定未跑',
        '  : "⏭️ 就绪判定未跑',
        "skip_notice_gone",
        "pkg-a",
        None,        # 走 run_batch 的默认：显式 `--no-require-ready`
    ),
    # ── #6212 新增：auto-merge arm 面的四处定向变异（逐条对应判据 16 / 18 / 20 / 19）──────
    (
        "已 arm 不就绪 → 就绪（判据 16）",
        '    not_ready "$b" "PR #${pr} 的 auto-merge **已 arm**',
        '    ready_ok "$b" "PR #${pr} 的 auto-merge **已 arm**',
        "not_ready_became_ready",
        "pkg-a",
        "armed",
    ),
    (
        "读不到 arm ⇒ 放行（fail-open，判据 18）",
        '  elif [ "$rc" -ne 0 ]; then\n    undecidable "$b" "PR #${pr} 的 auto-merge 状态读不到',
        '  elif [ "$rc" -eq 99 ]; then\n    undecidable "$b" "PR #${pr} 的 auto-merge 状态读不到',
        "arm_undecidable_became_ready",
        "pkg-a",
        "arm-nonjson",
    ),
    (
        "回读「仍 arm」不再非零（静默放行，判据 20）",
        '    exit 1\n  fi\n  echo "  ⇒ 全部 ${#CHECK_ARMS[@]} 个 PR 未 arm',
        '    exit 0\n  fi\n  echo "  ⇒ 全部 ${#CHECK_ARMS[@]} 个 PR 未 arm',
        "check_arm_silent_pass",
        "--check-arm 6212",
        "armed",
    ),
    (
        "回读命令从出口里被摘掉（判据 19）",
        "② 当场回读（仍 arm ⇒ 非零；无法判定 ⇒ 3）：./scripts/batch-gate.sh --check-arm ${pr}",
        "② 当场回读：见 --help",
        "readback_cmd_gone",
        "pkg-a",
        "armed",
    ),
]


def _mutated_repo(tmp_path: pathlib.Path, old: str, new: str) -> pathlib.Path:
    """造一个**装了变异脚本**的沙箱（与正常沙箱同一条构建路径）—— 真对象、真运行。"""
    src = _script_text()
    hits = src.count(old)
    assert hits == 1, f"变异没生效（命中 {hits} 次，应为 1）：{old!r} ⇒ 红证就是空断言，先修变异锚点"
    assert new != old, "变异体与原文逐字相同 = 没变异"
    return _build_repo(tmp_path / f"mutant-{uuid.uuid4().hex}", src.replace(old, new, 1))


@pytest.mark.parametrize("label,old,new,expect,branch,gh_mode", MUTATIONS,
                         ids=[m[0] for m in MUTATIONS])
def test_mutations_turn_the_suite_red(sandbox, tmp_path, label, old, new, expect, branch, gh_mode):
    """判据 14：**注入式红证** —— 四处变异各自必须让对应判据真红（且报出具名读数）。

    每个变异都跑在**自己的**沙箱里；`branch` 是能走到目标分支的那个包：
      - 「冲突不就绪 → 就绪」走 `chapters-dirty`（切出后主线前进过 ⇒ 真冲突）；
      - 「无 PR 不就绪 → 就绪」必须**挂桩 gh 且 list 成功**（否则先死在「gh pr list 失败」上、
        根本走不到那条分支 —— 变异体会因为**别的**原因非零退出，红证就成了假红）；
      - 其余走 `pkg-a`。

    判红读数按 `expect` 分流（三种形态**互斥**，不许混着断 —— 混着断必然自相矛盾）：
      - `not_ready_became_ready` ⇒ 那个包被印成 **✅ <包>：<理由>**（不就绪被印成就绪）；
      - `undecidable_became_ready` ⇒ 那行被印成 **✅ pkg-a：gh pr list 失败**（fail-open 的可见形态）；
      - `default_off` ⇒ **就绪判定横幅整个不见**（连判都没判）；
      - `skip_notice_gone` ⇒ 走了逃生口却**不吭声**（「未跑…这不是「就绪」」那句没了）。

      这三条**都**会：① 不再打「⛔ 有包未通过就绪判定」；② 那一次全量**照跑**（`calls == 1`）。

      ⚠️ **不拿退出码当共同读数**：变异 A 的包真冲突 ⇒ 校验放行后会在 merge 阶段红（exit 1），
      与变异 B/C/D 的 exit 0 不同；共同读数是「就绪判定有没有再拒绝 + 全量有没有照跑」。
    """
    mutant = _mutated_repo(tmp_path, old, new)
    # ⚠️ 必须走**真默认路径**（不传 `--no-require-ready`）—— 否则脚本压根不判就绪，
    # 变异体一律「看起来绿」⇒ 这组红证就成了空断言（这不是假设：本判据第一版正是如此被抓出来的）。
    # `--check-arm` 形态的变异（判据 20）走**回读**入口 ⇒ 它的「branch」是一整串参数，不是分支名。
    args = branch.split(" ") if expect.startswith("check_arm") else (branch,)
    proc, calls, _ = run_batch(mutant, *args, gh_mode=gh_mode)
    out = proc.stdout + proc.stderr
    if expect == "readback_cmd_gone":
        # 这条变异的读数不是「放行」，而是「出口少了一条命令」⇒ **拒绝行为必须仍在**
        # （若它连拒绝也没了，说明变异打歪了、红证无效）。
        assert "⛔ 有包未通过就绪判定" in out, f"变异「{label}」改变了拒绝行为（本应只缺命令）：\n{out}"
    elif not expect.startswith("check_arm"):
        # 共同读数：就绪判定**没有再拒绝**（那句「⛔ 有包未通过就绪判定」不见了）——
        # 这几条变异都会让它消失，而**正常脚本**下判据 7~10/16/18 正是靠它变红的。
        assert "⛔ 有包未通过就绪判定" not in out, f"变异「{label}」**没被抓住**（就绪判定仍拒绝了）：\n{out}"
    # 逐条读数（**每条都必须真的择得出来**，否则这条变异是空断言）：
    if expect == "not_ready_became_ready":
        marker = f"✅ {branch}："
        assert marker in out, f"变异「{label}」没被抓住（没有把不就绪印成就绪）：\n{out}"
        assert f"❌ {branch}（不就绪）" not in out, f"变异「{label}」仍印着「不就绪」：\n{out}"
        if branch != "chapters-dirty":   # chapters-dirty 真冲突 ⇒ 校验放行后死在 merge，全量不会跑
            assert len(calls) == 1, f"变异「{label}」没被抓住（没放行）：{calls}"
    elif expect == "undecidable_became_ready":
        assert "✅ pkg-a：gh pr list 失败" in out, f"变异「{label}」没被抓住（fail-open 那行不在）：\n{out}"
        assert "❓" not in out, f"变异「{label}」仍印着「无法判定」标记：\n{out}"
        assert len(calls) == 1, f"变异「{label}」没被抓住（没放行）：{calls}"
    elif expect == "skip_notice_gone":
        # 逃生活儿口静默了 ⇒ 使用者**看不出**「这次没判就绪」（与「就绪」长得一样）
        assert "这不是「就绪」" not in out, f"变异「{label}」没被抓住（声明还在）：\n{out}"
        assert len(calls) == 1, f"变异「{label}」没被抓住（本该照跑全量）：{calls}"
    elif expect == "default_off":
        # 就绪判定**根本没跑** ⇒ 横幅不见 + 打印「未跑」声明（这与脚本自带逃生口是两回事：
        # 「默认关」下连判都不判；逃生口下会显式打印 `--no-require-ready` 那句）
        assert "就绪前置判定（--require-ready 默认开启" not in out, f"变异「{label}」没被抓住（横幅还在）：\n{out}"
        assert "⏭️ 就绪判定未跑" in out, f"变异「{label}」没被抓住（连「未跑」都没印）：\n{out}"
        assert len(calls) == 1, f"变异「{label}」没被抓住（没放行）：{calls}"
    elif expect == "arm_undecidable_became_ready":
        # fail-open 的可见形态：读不到 arm 状态却被印成 ✅（判据 18 正是断这个不出现）
        assert "✅ pkg-a：" in out, f"变异「{label}」没被抓住（读不到却印成就绪）：\n{out}"
        assert "❓" not in out, f"变异「{label}」仍印着「无法判定」标记：\n{out}"
        assert len(calls) == 1, f"变异「{label}」没被抓住（没放行）：{calls}"
    elif expect == "check_arm_silent_pass":
        # 回读「仍 arm」本该 exit 1；变异后 exit 0，而 ❌ 行还印着 ⇒ 就是「说了红却当绿」的形态
        assert proc.returncode == 0, f"变异「{label}」没生效（回读仍非零）：rc={proc.returncode}\n{out}"
        assert "❌ PR #6212（**仍 arm**" in out, f"变异「{label}」打歪了（没走到 armed 分支）：\n{out}"
        assert calls == [], f"回读是只读入口 ⇒ 不该跑全量，实得 {calls}"
    elif expect == "readback_cmd_gone":
        assert "gh pr merge 6801 --disable-auto" in out, f"变异「{label}」把**解除**命令也弄丢了：\n{out}"
        assert "--check-arm 6801" not in out, f"变异「{label}」没被抓住（回读命令还在）：\n{out}"
        assert calls == [], f"不就绪的包不该跑全量，实得 {calls}"
    else:  # pragma: no cover - 防呆：expect 写错时当场红，不静默放行
        raise AssertionError(f"未知的 expect：{expect!r}（变异表写错 ⇒ 红证无效）")


def test_control_real_script_has_no_mutation_marker(sandbox):
    """判据 15（对照读数）：真脚本里没有留下任何变异——上面那组红证不是「冲着坏脚本测的」。"""
    src = (sandbox / SCRIPT_REL).read_text(encoding="utf-8")
    for _label, old, new, _expect, _branch, _gh_mode in MUTATIONS:
        assert new not in src, f"真脚本里出现了变异后的文本（红证会变成自证）：{new!r}"
        assert old in src, f"真脚本里找不到变异锚点（红证失效）：{old!r}"
