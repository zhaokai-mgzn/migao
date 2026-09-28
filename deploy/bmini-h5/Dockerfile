# B 端 h5 产物的**传输载体**（不是运行镜像）—— issue #5668
#
# 本镜像只做一件事：把 CI 构建出来的 `frontend/bmini-app/dist/` **原样**搬到 SWAS 实例上，
# 由 `deploy/swas/bmini-h5-publish-remote.sh` 用 `docker cp` 取出来，再落到静态根的子目录 `b/`。
#
# ## 为什么用镜像搬静态产物（不是"顺手"选的，是被两边的约束逼出来的）
#
# | 约束 | 实测读数 |
# |---|---|
# | SWAS 实例上**没有** node 工具链 | 实例只跑 docker compose（`deploy/swas/docker-compose.yml`）；产物必须在 CI 里构建 |
# | 产物必须**按 `/b/` 前缀**构建 | `frontend/bmini-app/config/index.ts` 的 `h5.publicPath` 读 `TARO_APP_H5_PUBLIC_PATH`；默认 `'/'` 会引用 `/js/app.js` = **C 端的包**（静默串端） |
# | 「线上字节 == 本仓库产物字节」是**身份断言** | 发布腿必须搬**那一份**构建产物，不能在实例上二次构建（不同 node/webpack 环境下字节不保证一致） |
# | CI → 实例的既有通道 | ① `aliyun swas-open RunCommand`（命令体上限 64KB，装不下 ~1.3MB 产物）② **ACR 镜像**（实例已在用：compose 里三个服务的镜像都从这里拉）⇒ 只有 ② 可行 |
#
# ⇒ 镜像里只有 `/dist`（构建产物），没有运行时、没有入口点；取出来即用。
# 上下文由 workflow 显式给成 `frontend/bmini-app/dist`（**不**给 `frontend/bmini-app`，
# 否则 700MB+ 的 `node_modules` 会被打进构建上下文）。
#
# ⚠️ 本文件**逐行都是注释或合法指令**：Dockerfile 里裸写散文会被当成指令 ⇒
# `dockerfile parse error on line N: unknown instruction: …`（实测踩到：首次发布的
# `Pack product into transport image and push` 步骤就是这么红的，本机没有 docker 二进制 ⇒
# 只有 CI 能发现）。常驻判据 = tests/unit_ci_workflows/test_bmini_h5_hosting.py 的
# `test_dockerfile_lines_are_all_comments_or_instructions`（含注入式红证）。
FROM alpine:3.20
COPY . /dist
