#!/usr/bin/env python3
"""deploy-reconcile 漂移判据的「构建输入面」—— **唯一取值源**（issue #7034）。

## 病（现取读数，不是推断）

`deploy-reconcile.yml` 的漂移判据 ② 原先只问一件事：「自上次成功部署的 commit 起，
`${svc_path}`（该服务的应用代码目录）有没有改动」。应用代码没动 ⇒ 判
`✅ 无漂移：… 无代码改动` ⇒ **不补部署**，还会 `watchdog_note … deployed`
**自动关闭值守单**。

而 `builtAt` / `sha` 这类**构建期烘焙进镜像的身份字段**，取值源在**部署腿自己的 workflow**
（`Resolve build identity` 步）。2026-10-16 实测（issue #7029 的现场）：只改
`.github/**` + `deploy/scripts/**` 的修复合入 main 后，对账判 `deployed`
（`无漂移：自 fbbb798（上次成功部署）起 backend/admin-api 无代码改动`），
而同一时刻线上 `GET /api/version` 的 `builtAt` 仍是空串 ⇒ **修复没上线，告警面却报绿并关单**。

⇒ **「CI 改好了」被读成「线上兑现了」**。本文件把「哪些变更算构建输入」收成一处，
workflow 只调用它（判据 = `tests/unit_ci_workflows/test_reconcile_build_inputs.py`）。

## 判定口径（对每条腿 L：workflow `W`、服务代码路径 `P`）

`P` 由调用行给出（应用代码，既有行为不变）。**构建输入 = 满足下列任一条的仓内路径**：

1. **`W` 自身** —— `Resolve build identity` / `--build-arg` / 部署与自证步骤都写在 `W` 里
   ⇒ 改 `W` 就是改「构建什么、以什么身份构建、部署后怎么自证」。
2. **构建配方与发货驱动** —— `deploy/swas/deploy.sh`（服务器侧 `docker build` 的
   context/Dockerfile/`--build-arg` + compose/nginx 应用面）与决定「发哪个 commit 的什么」的
   `deploy/scripts/*` 驱动脚本。
3. **线上自证（verification）脚本** —— 改了判据本体，**旧部署的绿不再是新判据的绿**；
   只有真跑一次部署腿，新判据才在线上跑过（#7029 的形态正是「判据修好了、线上没兑现」）。
4. **腿 `uses:` 的可复用验收 workflow** —— 同上，属于「我们对线上形态说的那句话」。

**有意不收**（逐条带理由，见 `NOT_BUILD_INPUTS`）：凭据登录辅助、以及**有自己常驻触发面**的
旁观判据 —— 它们既不进产物、也不靠本腿兑现，且失败是**当场红**而不是静默假绿。

## 方向（issue #7034 的硬要求）

**多算不算错，少算才是假绿。** 但**不许**扩成「任何文件变动都算」：判据只看上面四类面 ——
`docs/**` 之类的无关改动照旧判「无漂移」（负控见判据文件的 `test_unrelated_docs_change_is_not_drift`），
否则这条腿会永远红、并每次空转一次生产重建。

## 用法（workflow 的唯一调用面）

    python3 .github/scripts/reconcile_build_inputs.py <腿>

stdout = **空格分隔**的 git pathspec（含 `<svc_path>`，供调用方直接 `pathspec+=( $out )`）。
取不到 / 腿名不认识 ⇒ 退出码 **3** 且**不打印任何 pathspec** ⇒ 调用方按旧口径判定并出
`::warning::`（与 `scripts/deploy_reconcile_state.sh` 的「载不进就弃权」同一形态：
**还轮不到我** 不许让机制停摆 —— 本腿的 checkout 是 `ref: main`，新增本文件的那个 PR 里它不在检出里）。

⚠️ **路径里不许出现空白**（调用方按空白切分）：`test_cli_contract` 现取集合上钉死这一条。
"""
from __future__ import annotations

import sys

# ── 三条镜像腿共用的驱动面（`deploy/swas/deploy.sh` 的 `service_context_of` 对三条腿都成立）──
_IMAGE_DRIVER = (
    (
        "deploy/swas/deploy.sh",
        "服务器侧构建配方 + 应用面：docker build 的 context/Dockerfile/--build-arg 与 "
        "compose/nginx 的 cp+up+reload 全在这份里 ⇒ 改它，三条镜像腿的产物形态都可能变",
    ),
    (
        "deploy/scripts/swas-deploy-ci.sh",
        "CI→SWAS 的发货驱动：决定 BUILD_SERVICE / BUILD_SHA / 配置 ref 与下发给服务器的那串命令",
    ),
    (
        "deploy/scripts/swas_deploy_running_tag.sh",
        "部署后「线上到底在跑哪个 tag」的复核判据 —— 改它等于改「这次部署算不算成功」",
    ),
)

#: 腿名 → 构建输入清单（逐条带理由）。腿名 = `deploy-reconcile.yml` 里 `reconcile_one` 的第一个参数。
BUILD_INPUTS: dict[str, tuple[tuple[str, str], ...]] = {
    "admin-api": (
        (
            ".github/workflows/deploy-admin-api.yml",
            "本腿的定义：Resolve build identity（BUILT_AT/SHA 的**取值源**，issue #7029 就修在这里）、"
            "--build-arg、dispatch 语义 —— 改它就必须重建身份面",
        ),
        (
            ".github/workflows/smoke-test.yml",
            "本腿 post-deploy 的 P0 验收腿（`uses:`）：改验收断言，只有真跑一次部署腿才被兑现",
        ),
        *_IMAGE_DRIVER,
        (
            "deploy/scripts/served-version-verify.sh",
            "线上身份自证（GET /api/version 的 sha + builtAt）：改判据本体后旧部署的绿不再成立，"
            "必须重跑一次才在线上跑过",
        ),
        (
            "deploy/scripts/prod-security-headers.sh",
            "线上安全头自证（只读判据）：同上 —— 判据一改就得区分「旧部署的绿」与「新判据的绿」",
        ),
    ),
    "ai-agent-service": (
        (
            ".github/workflows/deploy-ai-agent-service.yml",
            "本腿的定义：Resolve build identity / --build-arg / 线上自证步骤",
        ),
        (
            ".github/workflows/smoke-test.yml",
            "本腿 post-deploy 的 P0 验收腿（`uses:`），同上",
        ),
        *_IMAGE_DRIVER,
    ),
    "admin-web": (
        (
            ".github/workflows/deploy-frontend.yml",
            "本腿的定义：Resolve build identity / --build-arg / 线上自证步骤",
        ),
        *_IMAGE_DRIVER,
        (
            "deploy/scripts/admin-web-version-probe.sh",
            "线上身份自证（GET /version.json 的 sha + builtAt；前端腿的 builtAt 现为 \"unknown\"，"
            "同一类病）—— 改它必须重跑一次才在线上跑过",
        ),
    ),
    "worker-h5": (
        (
            ".github/workflows/worker-h5-publish.yml",
            "本腿的定义（发布链路 + 发布后身份断言），改它就要重发一次才算兑现",
        ),
        (
            "deploy/swas/h5-publish-remote.sh",
            "远端执行体：发布逻辑本身（改了它，公告的发布形态就变了）",
        ),
        (
            "deploy/scripts/swas-h5-publish-ci.sh",
            "CI 侧发布驱动：决定推哪些产物、给远端哪些参数",
        ),
        (
            "deploy/scripts/worker-h5-verify-served.sh",
            "线上产物身份自证：改它同样是「判据改了、线上没跑过」的假绿面",
        ),
    ),
    "bmini-h5-hosting": (
        (
            ".github/workflows/bmini-h5-publish.yml",
            "本腿的定义（发布链路 + 发布后身份/不串端断言）",
        ),
        (
            "deploy/bmini-h5/**",
            "h5 传输载体（Dockerfile）：产物怎么从 CI 到实例就写在它里面",
        ),
        (
            "deploy/swas/bmini-h5-publish-remote.sh",
            "远端执行体：发布逻辑本身",
        ),
        (
            "deploy/scripts/bmini-h5-publish-ci.sh",
            "CI 侧发布驱动",
        ),
        (
            "deploy/scripts/bmini-h5-verify-served.sh",
            "线上产物身份 + 不串端自证",
        ),
    ),
    "c-end-h5": (
        (
            ".github/workflows/c-end-h5-publish.yml",
            "本腿的定义（手动发布 gate + `scripts/h5_freshness_guard.py` 的调用面）",
        ),
        (
            "deploy/scripts/c-end-h5-dist-push.sh",
            "发布链路第一层：把 CI 构建的 dist 推成不可变 sha（远端按 sha 取回）",
        ),
        (
            "deploy/scripts/c-end-h5-publish-ci.sh",
            "CI 侧发布驱动：对账 dispatch 出去的 run 走这条（只报告、不发布）",
        ),
        (
            "deploy/scripts/c-end-h5-verify-served.sh",
            "线上产物身份自证",
        ),
    ),
}

#: **有意不算构建输入**的路径 → 理由。判据会要求：① 每条确实被某条腿引用 ② 每条确实**没**被覆盖
#: （否则这条豁免是陈旧的 ⇒ 红）。
NOT_BUILD_INPUTS: dict[str, str] = {
    "scripts/acr_login.sh": (
        "纯凭据登录辅助（`docker login --password-stdin`）：既不进产物、也不出线上读数，"
        "且它坏了是部署腿**当场红** —— 不属于本单要治的「静默假绿」"
    ),
    "scripts/h5_freshness_guard.py": (
        "线上产物新鲜度的旁观判据：它有**自己的常驻触发面**（`.github/workflows/h5-freshness-guard.yml` "
        "每天跑同一份实现）⇒ 不需要靠 c-end-h5 那条腿兑现；而该腿是**手动发布**腿，"
        "为它 dispatch 只会产生一条「不发布任何东西」的红"
    ),
}


def build_inputs(svc: str) -> tuple[str, ...]:
    """该腿的构建输入 pathspec（不含 `<svc_path>`；顺序 = 登记顺序）。"""
    return tuple(path for path, _why in BUILD_INPUTS[svc])


def build_input_reasons(svc: str) -> dict:
    """该腿的构建输入 → 理由（判据与 PR body 的读数来源，不再手抄第二份）。"""
    return dict(BUILD_INPUTS[svc])


def _covered(entry: str, path: str) -> bool:
    """`entry` 是否已覆盖 `path`（git pathspec 的目录前缀 / 同路径两种形态）。"""
    return path == entry or path.startswith(entry.rstrip("/") + "/")


def pathspec(svc: str, svc_path: str, extra: str = "") -> list:
    """该腿**实际**用于 `git log … --` 的完整 pathspec（去重：被前面条目覆盖的不再重复）。

    `svc_path` / `extra` 来自 `reconcile_one` 的调用行（应用代码 + 该腿的附加包含项），
    行为与改造前一致；构建输入**追加在后** ⇒ 既有 summary 读数（`判定 pathspec：<svc_path> <extra>`）
    逐字仍是前缀（`tests/unit_ci_workflows/test_config_change_triggers_deploy.py` 依赖这一点）。

    `svc` 不在登记册里 ⇒ `KeyError`（调用方按「取不到」处理，**不许**猜）。
    """
    out: list = []
    for entry in (svc_path, *extra.split(), *build_inputs(svc)):
        if not entry:
            continue
        if any(_covered(kept, entry) for kept in out):
            continue
        out.append(entry)
    return out


def main(argv: list) -> int:
    if len(argv) != 2:
        sys.stderr.write("用法: reconcile_build_inputs.py <腿名>\n")
        return 3
    svc = argv[1]
    try:
        entries = pathspec(svc, "")
    except KeyError:
        sys.stderr.write(f"未知对账腿：{svc!r}（登记册：{sorted(BUILD_INPUTS)}）\n")
        return 3
    if not entries:  # 反空跑：拿到空集时**不许**装成「该腿没有构建输入」
        sys.stderr.write(f"{svc}: 构建输入清单为空（判据会在空集上恒真）\n")
        return 3
    sys.stdout.write(" ".join(entries) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
