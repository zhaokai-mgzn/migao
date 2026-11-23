"""部署沙箱的 `git` 桩（issue #9086）—— 给 `deploy/swas/deploy.sh` 的**发布线自检**补上被模拟的那一面。

## 为什么需要它

`deploy/swas/deploy.sh` 的 1.0.1 段（`# >>> release-line-assert`）会问 `git` 四件事：
`fetch origin/release` / `rev-parse`（target + release）/ `merge-base --is-ancestor` / `rev-list --count`。

既有执行式守卫（`test_swas_deploy_blue_green.py` / `test_swas_deploy_no_downgrade.py` /
`test_swas_deploy_disk_recovery.py` / `test_swas_deploy_disk_retention.py` /
`test_swas_deploy_config_pinning.py` / `test_swas_deploy_ci_hardening.py` /
`test_swas_jwt_same_source.py` / `test_swas_container_runtime.py`）跑的是**真实脚本**
（桩化 `docker` / `curl` / `flock` / `timeout` 等外部依赖）。加了这一段之后，它们里的 `git` 是**真 git**：

- 真去 `https://github.com/zhaokai-mgzn/migao` 取 release 历史（慢、依赖网络、CI 里还会抖）；
- 而沙箱用的 tag 是**假 sha**（`sha-abc1234` 这类）⇒ 永远追不到 target commit ⇒ 段内按设计
  `exit 3` 早退 ⇒ **既有断言全部被这一步拦住**（它们断言的是部署编排，不是发布线归属）。

⇒ 本模块补桩的目的不是「让判据变绿」，而是**补齐沙箱本来就该模拟的那一面**：
沙箱里假定「目标提交是 release 的祖先」（= 正常部署形态），于是既有断言一字不用改。

## 边界

- 桩只回答本段要的那几种调用；**不碰网络**、不写仓库；
- 默认 `merge-base --is-ancestor` ⇒ rc **0**（祖先）。要演「非祖先 / 判不了」的场景请用
  `test_swas_deploy_release_line.py` 自己的桩（它还带 `STUB_ANCESTOR` / `STUB_FETCH_FAIL` 等开关）：
  **本模块不承接那一族**，避免两套开关各自漂移；
- 桩遮蔽了 PATH 里的真 `git`：这些沙箱里 `deploy.sh` 是唯一会调 git 的对象（脚本其余部分不用 git）。
"""
from __future__ import annotations

from pathlib import Path

#: 沙箱里「release 的当前提交」与「本次部署目标提交」（40 位十六进制，形态与真实 sha 一致）
RELEASE_SHA = "b5e1d0c9a8f7e6d5c4b3a2918273645f4e3d2c1b"
TARGET_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

GIT_STUB = """#!/usr/bin/env bash
# 桩 git（issue #9086）：只回答 deploy.sh「发布线自检」要的几种调用，**不碰网络**
# 跳过全局选项（`--git-dir=…` / `-c key=value` 的**值**不是子命令）
cmd=""
skip=0
for a in "$@"; do
  if [ "$skip" = "1" ]; then skip=0; continue; fi
  case "$a" in
    -c) skip=1 ;;
    -*) ;;
    *) cmd=$a; break ;;
  esac
done
case "$cmd" in
  init)
    d=""
    for a in "$@"; do d=$a; done
    mkdir -p "$d"
    exit 0
    ;;
  fetch) exit 0 ;;
  rev-parse)
    obj=""
    for a in "$@"; do
      case "$a" in
        -*) continue ;;
        *) obj=$a ;;
      esac
    done
    case "$obj" in
      refs/remotes/origin/release*) echo "%(release)s"; exit 0 ;;
    esac
    echo "%(target)s"
    exit 0
    ;;
  merge-base) exit 0 ;;
  rev-list) echo 1; exit 0 ;;
esac
exit 0
""" % {"release": RELEASE_SHA, "target": TARGET_SHA}


def install(bin_dir: Path) -> Path:
    """把 `git` 桩写进沙箱的 `bin_dir`（PATH 前置目录）。返回桩文件路径。"""
    target = Path(bin_dir) / "git"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(GIT_STUB, encoding="utf-8")
    target.chmod(0o755)
    return target
