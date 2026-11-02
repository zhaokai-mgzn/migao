# 观星台终端安装包的**传输载体**（不是运行镜像）—— issue #8195
#
# 本镜像只做一件事：把发布腿生成好的载荷目录（exe / apk / latest.json / latest-android.json）
# **原样**搬到 SWAS 实例上，由 `deploy/swas/terminal-publish-remote.sh` 用 `docker cp` 取出来，
# 再落到静态根的子目录 `terminal/`。
#
# ## 为什么用镜像搬二进制（不是"顺手"选的，是被两边的约束逼出来的）
#
# | 约束 | 实测读数 |
# |---|---|
# | SWAS 实例上**没有**构建工具链 | 实例只跑 docker compose（`deploy/swas/docker-compose.yml`）；exe/apk 必须在 CI 侧产出 |
# | 安装包是**二进制**，不能进命令内容 | `RunCommand` 的 `CommandContent` 上限 16 KB（发布腿自己在发起云调用前断言，见 `deploy/scripts/terminal-publish-ci.sh`） |
# | 「线上字节 == release 里的字节」是**身份断言** | 发布腿必须搬**那一份**下载产物，不能在实例上重新打包（重打包后 sha256 必然不同，终端会拒绝更新） |
# | CI → 实例的既有通道 | ① `RunCommand`（16 KB，装不下几 MB 安装包）② **ACR 镜像**（实例已在用）⇒ 只有 ② 可行 |
#
# ⇒ 镜像里只有 `/dist`（载荷），没有运行时、没有入口点；取出来即用。
# 上下文由 workflow 显式给成「prepare 生成的那个载荷目录」（**不**给仓库根 —— 那会把整个仓库打进构建上下文）。
#
# ⚠️ 本文件**逐行都是注释或合法指令**：Dockerfile 里裸写散文会被当成指令 ⇒
# `dockerfile parse error on line N: unknown instruction: …`（本机没有 docker 二进制 ⇒ 只有 CI 能发现）。
# 常驻判据 = tests/unit_ci_workflows/test_terminal_release_leg.py 的
# `test_transport_dockerfile_lines_are_all_comments_or_instructions`（含注入式红证）。
FROM alpine:3.20
COPY . /dist
