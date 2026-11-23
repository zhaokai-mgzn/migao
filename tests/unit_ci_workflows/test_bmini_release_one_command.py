# case_ids: MC-344
r"""B 端小程序「发一版 = 一条命令」的判据（issue #9069）。

## 病（2026-11-23 用户裁定「不碰C端，先把B端做夯实」；1.0.2 发出去时的形态）

发一版 = **三步手打 + 三处人肉记忆**：`./scripts/cut-release.sh` → `bmini-experience.sh build --env prod`
→ `bmini-experience.sh upload --version X.Y.Z`。三处靠人记：

| # | 形态 | 当时为什么没红 |
|---|---|---|
| 1 | **顺序即安全顺序**（先 cut、再 build、再 upload），记反一次就发错包 | 三步各自都能跑通，没有任何东西检查它们**按这个顺序**发生过 |
| 2 | **生产包只在部署机构建 + 上传**（2026-11-23 用户裁定）。本机误跑产出指向 `localhost` 的漂移包（1.0.1 就是这么废的：真机 `request:fail errcode:-102`） | 本机 `build:weapp` 照样成功、上传照样成功；错的地址只有真机才暴露 |
| 3 | **上传后 `TOTAL` 读数人手抄进 docs 发布记录表**，抄错没人知道 | 抄写是纯人工动作，没有任何判据 |

## 本文件锁什么（判据本体 = `scripts/bmini-release.sh`；每条都能单独变红）

| # | 判据 | 执行点 |
|---|---|---|
| ① | **机器闸门**：本机身份必须等于 `ssh -G <别名>` 解析出的 `HostName`（别名缺省 `migao-deploy`，**禁写死 IP**）；非部署机 ⇒ 具名拒绝 + 三个出口 + **一步都不往下走**；读数拿不到（ssh 配置不可读）⇒ 退 **3**，不冒充拒绝 | `::test_machine_gate_refuses_before_doing_anything` / `::test_machine_gate_passes_when_the_identity_matches` / `::test_machine_gate_is_undecidable_when_the_reading_is_unavailable` |
| ② | **顺序闸门**：`origin/release` ⊆ `origin/main`（复算 = `cut-release.sh --check`，退 2 即旁路）⇒ 具名拒绝，**且绝不自动 cut**（远端 release ref 逐字不变）；`origin/release` 不存在 ⇒ 拒绝；**本检出 HEAD ≠ `origin/release`** ⇒ 拒绝（2026-11-21「停在旧特性分支构建」的形态）；工作区有未提交改动 ⇒ 拒绝；取不到远端 ⇒ 退 **3** | `::test_bypassed_release_line_is_a_named_refusal_and_never_cuts` / `::test_checkout_not_on_the_release_line_is_refused` / `::test_dirty_worktree_is_refused` / `::test_missing_release_branch_is_refused` / `::test_unreachable_origin_is_undecidable` |
| ③④ | **构建 + 上传前断言（复用，不自造）**：构建归 `bmini-experience.sh build --env prod`，断言归 `deploy/scripts/bmini-assert-dist.sh`；断言不过（含**不可判定**）⇒ **一次上传都不发生**（`npx` 桩没被调用）；顺序实测 = `npm → assert → assert → assert → npx`（构建内断言 / 本脚本的上传前断言 / upload 自己的断言） | `::test_assert_failure_blocks_the_upload` / `::test_a_drifted_dist_detected_by_the_pre_upload_assert_blocks_the_upload` / `::test_ordering_is_build_then_asserts_then_upload` |
| ⑤ | **上传**：版本号必须**显式给**（`--upload` 缺 `--version` ⇒ 退 2，且不构建、不上传；形态非 `X.Y.Z` ⇒ 退 2） | `::test_upload_requires_an_explicit_version` |
| ⑥ | **回读 + 可粘贴行**：从上传日志抓 `TOTAL` 字节，打印一行**可直接粘贴**进 docs 发布记录表的 Markdown 行（版本 / 时间 / 部署机 alias / `origin/release` sha / TOTAL / dist / 比值）；比值必须落在「预算文件 `calibration` 台账比值 ±3%」⇒ **越界 = 警告并退 3**（不静默通过）；抓不到 TOTAL ⇒ 退 3 | `::test_upload_prints_a_pasteable_record_row` / `::test_ratio_out_of_band_exits_3` / `::test_missing_total_in_the_log_is_undecidable` |
| ⑦ | **默认安全**：不带 `--upload` 时只做 ①~④ 并打印「未上传」；**不产出**记录行（没有 TOTAL 就不猜读数） | `::test_default_run_builds_and_asserts_but_never_uploads` |
| ⑧ | **单一来源（类级元守卫的实例面）**：脚本里**不出现**域名常量 / 上限常量（常量只许在 `bmini-experience.sh` 与 `deploy/scripts/bmini-dist-budget.json`）；`cut-release.sh` 的**唯一**调用形态是 `--check`（永不自动 cut）；比值尺度**现读**预算文件 ⇒ 篡改台账即判红（证明不是另存了一份尺子） | `::test_script_reuses_instead_of_reimplementing` / `::test_ratio_band_is_read_from_the_budget_not_hardcoded` |
| ⑨ | **文档接线**：`docs/deployment/bmini-experience-release.md` 必须指向一条命令，且**底层三步仍在**（cut / build / upload 三条命令 + 发布记录表 + 部署机裁定都不得被删） | `::test_docs_point_at_the_one_command_and_keep_the_three_steps` |

## 沙箱怎么造（零网络 / 零真构建 / 零真上传 / 零 LLM）

* **git 侧是真的**：沙箱里有一个 `origin.git`（bare）+ 一个检出，发布线/主线的相对关系按用例摆位
  ⇒ `cut-release.sh --check` 的三态（0/2/3）由**真脚本**给出，不是 mock；
* **构建与上传是桩**：`npm` / `npx` 桩写一棵 weapp 形状的 dist（含域名、页面、4KB padding）并把调用
  记进**同一个** marker 日志（顺序判据靠它）；`assert` 用**代理脚本**转发到**真断言脚本**（只多记一行
  日志 —— 它既是探针，又能按需在第 N 次调用前注入漂移，见判据 ④）；
* **机器闸门的读数可注入**：`MIGAO_BMINI_HOST_ID`（本机身份）+ `MIGAO_BMINI_SSH_CONFIG`（ssh 配置）
  是**读数**的口子，不是「跳过闸门」的开关 —— 缺省读真机（`scutil` / `hostname` / `~/.ssh/config`）。

## 边界（照实登记）

- 没有执行任何真实上传 / 发布（部署机登录态不在研发机上）：真通道行为（devtools 打印 `TOTAL` 的
  真实形态、私钥通道不打印 `TOTAL`）由**日志桩**覆盖；真机复跑与首个 1.0.3 发布记录是**人工待办**。
- 判不了「产物能不能跑起来」、也判不了微信后台的域名白名单 / 提审状态（那边是外部后台状态）。
- 机器闸门是**防误跑**、不是权限边界：它读的是人用的同一份 ssh 配置，改自己的 ssh 配置就能让它认
  （这与「改脚本」等价，别当安全控制用）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bmini_dist import (  # noqa: E402  （夹具 / 预算读取口与体积判据同一份）
    ASSERT_SCRIPT,
    BUDGET_JSON,
    CAP_BYTES,
    EXPERIENCE_SCRIPT,
    REPO_ROOT,
    TEST_ORIGIN,
    tree_bytes,
)

RELEASE_SCRIPT = REPO_ROOT / "scripts" / "bmini-release.sh"
CUT_RELEASE = REPO_ROOT / "scripts" / "cut-release.sh"
DOCS = REPO_ROOT / "docs" / "deployment" / "bmini-experience-release.md"
PROD_ORIGIN = "https://app.cytda.com"

#: 沙箱里「部署机」与「本机」的身份读数（真机上缺省读 scutil / hostname，别写死 IP）。
DEPLOY_HOST = "bmini-deploy-box"          # 部署机的 HostName / LocalHostName（测试用）
OTHER_HOST = "some-dev-laptop"            # 一台普通开发机
DEPLOY_ALIAS = "migao-deploy"             # 人与脚本共用的 SSH 别名（**不写死 IP**）

#: 桩 dist 里的 padding：让字节合计进到 4 位数（真产物 1.4MB；`TOTAL` 的抓取要求 ≥4 位数字）。
PADDING_BYTES = 4096

STUB_NPM = f"""#!/bin/bash
set -u
printf 'npm\\n' >> "${{STUB_LOG}}"
printf 'TARO_APP_API_URL=%s\\nTARO_APP_AI_API_URL=%s\\nTARO_APP_PUBLIC_APP_ORIGIN=%s\\n' \\
  "${{TARO_APP_API_URL:-}}" "${{TARO_APP_AI_API_URL:-}}" "${{TARO_APP_PUBLIC_APP_ORIGIN:-}}" \\
  > "${{STUB_NPM_MARKER}}"
rm -rf dist
mkdir -p dist/pages/home
printf '{{"pages":["pages/home/index"]}}' > dist/app.json
printf 'const ORIGIN = "%s";\\n' "${{STUB_DIST_ORIGIN:-}}" > dist/app.js
printf '// page\\n' > dist/pages/home/index.js
printf '<view/>\\n' > dist/pages/home/index.wxml
printf '{{}}\\n' > dist/pages/home/index.json
head -c {PADDING_BYTES} /dev/zero | tr '\\\\0' 'x' > dist/padding.bin
find dist -type f -exec cat {{}} + | wc -c | tr -d ' ' > "${{STUB_DIST_BYTES}}"
exit 0
"""

#: `npx` 桩 = 上传通道。`STUB_NPX_MODE`：exact（TOTAL == dist，比值在带内）/ double（比值越界）/ silent（没有 TOTAL 行）。
STUB_NPX = """#!/bin/bash
set -u
printf 'npx\\n' >> "${STUB_LOG}"
printf '%s\\n' "$*" > "${STUB_NPX_MARKER}"
case "${STUB_NPX_MODE:-exact}" in
  silent) exit 0 ;;
esac
bytes=$(cat "${STUB_DIST_BYTES}")
if [ "${STUB_NPX_MODE:-exact}" = "double" ]; then bytes=$(( bytes * 2 )); fi
printf '✔ upload\\nTOTAL %s\\n' "$bytes"
exit 0
"""

#: `assert` 代理：记一行日志（顺序判据），按需在第 N 次调用前注入漂移（证明这道闸门**真的会拦**），
#: 然后**转发到真断言脚本**（判据本体不变，探针不改判）。
SPY_ASSERT = """#!/bin/bash
set -u
printf 'assert\\n' >> "${STUB_LOG}"
n=$(grep -c '^assert$' "${STUB_LOG}")
if [ "${STUB_TAMPER_ON:-0}" = "$n" ]; then
  printf 'const DRIFT = "http://localhost:8080";\\n' >> "${1}/app.js"
fi
exec bash "${0%/*}/bmini-assert-dist.real.sh" "$@"
"""

GIT_ENV = {
    "GIT_AUTHOR_NAME": "ci",
    "GIT_AUTHOR_EMAIL": "ci@example.com",
    "GIT_COMMITTER_NAME": "ci",
    "GIT_COMMITTER_EMAIL": "ci@example.com",
}


def _git(cwd: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(GIT_ENV)
    proc = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr}"
    return proc.stdout.strip()


def _commit(root: Path, message: str) -> str:
    """提交一次**内容有变化**的提交（git 对空提交会退 1 —— 沙箱里每次都要真的动一个文件）。"""
    marker = root / "commit-log.txt"
    previous = marker.read_text(encoding="utf-8") if marker.exists() else ""
    marker.write_text(previous + message + "\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


class Sandbox:
    """一棵**真 git** + 桩 npm/npx + 真断言（经代理）的最小仓树。

    布局（与真仓同形，脚本按 `BASH_SOURCE` 推 ROOT ⇒ 只在沙箱内动手）：
        repo/scripts/{bmini-release.sh,cut-release.sh,bmini-experience.sh}
        repo/deploy/scripts/{bmini-assert-dist.sh(代理),bmini-assert-dist.real.sh,<预算文件>}
        repo/frontend/bmini-app/{node_modules/,project.config.json}
        origin.git/  ← `release_mode` 决定 release 与 main 的相对位置
    """

    def __init__(
        self,
        tmp_path: Path,
        *,
        release_mode: str = "lags",
        dist_origin: str = PROD_ORIGIN,
        budget_tamper=None,
    ):
        self.tmp = Path(tmp_path)
        self.root = self.tmp / "repo"
        self.origin = self.tmp / "origin.git"
        self.dist_origin = dist_origin
        self.release_mode = release_mode
        self.log = self.tmp / "calls.log"
        self.npx_marker = self.tmp / "npx-called.txt"
        self.npm_marker = self.tmp / "npm-called.txt"
        self.ssh_config = self.tmp / "ssh_config"
        self.dist_bytes_file = self.tmp / "dist-bytes.txt"

        (self.root / "scripts").mkdir(parents=True)
        (self.root / "deploy" / "scripts").mkdir(parents=True)
        self.app_dir = self.root / "frontend" / "bmini-app"
        (self.app_dir / "node_modules").mkdir(parents=True)
        (self.app_dir / "node_modules" / ".keep").write_text("", encoding="utf-8")
        (self.app_dir / "project.config.json").write_text(
            json.dumps(
                {
                    "miniprogramRoot": "./dist",
                    "projectname": "bmini-app",
                    "appid": "touristappid",
                    "compileType": "miniprogram",
                    "setting": {"urlCheck": False},
                }
            ),
            encoding="utf-8",
        )
        shutil.copy2(RELEASE_SCRIPT, self.root / "scripts" / "bmini-release.sh")
        shutil.copy2(CUT_RELEASE, self.root / "scripts" / "cut-release.sh")
        shutil.copy2(EXPERIENCE_SCRIPT, self.root / "scripts" / "bmini-experience.sh")
        shutil.copy2(ASSERT_SCRIPT, self.root / "deploy" / "scripts" / "bmini-assert-dist.real.sh")
        (self.root / "deploy" / "scripts" / "bmini-assert-dist.sh").write_text(
            SPY_ASSERT, encoding="utf-8"
        )
        shutil.copy2(BUDGET_JSON, self.root / "deploy" / "scripts" / BUDGET_JSON.name)
        if budget_tamper is not None:
            # 篡改必须在**第一版提交之前**落地：否则「改台账」这一步会让工作区变脏 / HEAD 离开发布线，
            # 判据会先红在②上 —— 那样就测不到⑥的比值尺度了（也不是它该红的地方）。
            budget_file = self.root / "deploy" / "scripts" / BUDGET_JSON.name
            tampered = budget_tamper(json.loads(budget_file.read_text(encoding="utf-8")))
            budget_file.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")

        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.budget_path = self.root / "deploy" / "scripts" / BUDGET_JSON.name
        self._write_stub("npm", STUB_NPM)
        self._write_stub("npx", STUB_NPX)
        self.ssh_config.write_text(
            f"Host {DEPLOY_ALIAS}\n  HostName {DEPLOY_HOST}.local\n  User deployer\n", encoding="utf-8"
        )
        self._build_git()

    def _write_stub(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def _build_git(self) -> None:
        subprocess.run(["git", "init", "-q", "--bare", str(self.origin)], check=True,
                       capture_output=True, env={**os.environ, **GIT_ENV})
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)], check=True,
                       capture_output=True, env={**os.environ, **GIT_ENV})
        _commit(self.root, "base")
        _git(self.root, "remote", "add", "origin", str(self.origin))
        _git(self.root, "push", "-q", "origin", "main:main")

        if self.release_mode == "no-release":
            _commit(self.root, "main moves on")
            _git(self.root, "push", "-q", "origin", "main:main")
            _git(self.root, "checkout", "-q", "-B", "release", "origin/main")
            return

        # release 起点 = base（先推 release，再让 main 动）
        _git(self.root, "checkout", "-q", "-b", "release")
        _git(self.root, "push", "-q", "origin", "release:release")

        if self.release_mode == "bypass":
            # release 上出现 main 没有的提交 ⇒ 发布线被旁路
            _commit(self.root, "hotfix only on release")
            _git(self.root, "push", "-q", "origin", "release:release")
            return
        if self.release_mode == "equal":
            _commit(self.root, "main moves on")
            _git(self.root, "push", "-q", "origin", "main:main")
            _git(self.root, "push", "-q", "origin", "release:release")
            return

        # 缺省 "lags" 与 "head-main"：main 往前走一步（release 仍是 main 的祖先）
        _git(self.root, "checkout", "-q", "main")
        _commit(self.root, "main moves on")
        _git(self.root, "push", "-q", "origin", "main:main")
        if self.release_mode == "head-main":
            return  # HEAD 停在 main（≠ origin/release）
        _git(self.root, "checkout", "-q", "release")

    @property
    def dist(self) -> Path:
        return self.app_dir / "dist"

    def env(
        self,
        *,
        host_id: str | None = DEPLOY_HOST,
        ssh_config: Path | str | None = None,
        npx_mode: str = "exact",
        tamper_on: int = 0,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env.pop("MINIPROGRAM_UPLOAD_KEY", None)
        env.pop("MIGAO_BMINI_DEPLOY_SSH_ALIAS", None)
        env["PATH"] = f"{self.bin}{os.pathsep}{env.get('PATH', '')}"
        env["MIGAO_BMINI_SSH_CONFIG"] = str(
            self.ssh_config if ssh_config is None else ssh_config
        )
        if host_id is None:
            env.pop("MIGAO_BMINI_HOST_ID", None)
        else:
            env["MIGAO_BMINI_HOST_ID"] = host_id
        env["STUB_LOG"] = str(self.log)
        env["STUB_NPM_MARKER"] = str(self.npm_marker)
        env["STUB_NPX_MARKER"] = str(self.npx_marker)
        env["STUB_DIST_BYTES"] = str(self.dist_bytes_file)
        env["STUB_DIST_ORIGIN"] = self.dist_origin
        env["STUB_NPX_MODE"] = npx_mode
        env["STUB_TAMPER_ON"] = str(tamper_on)
        return env

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").split() if self.log.is_file() else []

    def run(self, *args: str, env: dict[str, str] | None = None):
        return subprocess.run(
            ["bash", str(self.root / "scripts" / "bmini-release.sh"), *args],
            cwd=self.root,
            env=env if env is not None else self.env(),
            capture_output=True,
            text=True,
            timeout=300,
        )

    def release_sha(self) -> str:
        return _git(self.origin, "rev-parse", "release")

    def upload_key(self) -> str:
        key = self.tmp / "private.key"
        key.write_text("not-a-real-key", encoding="utf-8")
        return str(key)


# ── ① 机器闸门 ────────────────────────────────────────────────────────────────
def test_machine_gate_refuses_before_doing_anything(tmp_path: Path):
    """非部署机 ⇒ 退 1、具名（两台机器的读数 + 三个出口）、且**一步都没往下走**。

    红证：本机身份 = 一台普通开发机（`OTHER_HOST`）⇒ 构建桩与上传桩都没被调用。
    """
    box = Sandbox(tmp_path)
    proc = box.run("--upload", "--version", "1.2.3", env=box.env(host_id=OTHER_HOST))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    err = proc.stderr
    assert "非部署机" in err and "拒绝执行" in err
    assert OTHER_HOST.lower() in err.lower(), "没报本机读数（判红不可归因）"
    assert f"{DEPLOY_HOST}.local" in err, "没报部署机的 HostName（判红不可归因）"
    assert "ssh " + DEPLOY_ALIAS in err, "没给出正确路径（出口不可行动）"
    assert "bmini-experience.sh build --env prod" in err, "没给出「只构建不发布」的出口"
    assert box.calls() == [], f"闸门没拦住：产生了一次构建/断言/上传调用 {box.calls()}"
    assert not box.npx_marker.exists()


def test_machine_gate_passes_when_the_identity_matches(tmp_path: Path):
    """对照臂：身份等于部署机 ⇒ `--host-assert` 退 0，且**零副作用**（不构建、不上传）。"""
    box = Sandbox(tmp_path)
    proc = box.run("--host-assert", env=box.env())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "本机就是部署机" in proc.stdout
    assert box.calls() == [], f"--host-assert 产生了副作用：{box.calls()}"


def test_machine_gate_is_undecidable_when_the_reading_is_unavailable(tmp_path: Path):
    """读数拿不到（ssh 配置读不出）⇒ 退 **3**（不可判定），不是「通过」也不是「判红」。

    `3` 与 `1` 必须分开：`1` = 「我确定它不是部署机」，`3` = 「我不知道」，后者不许当 0 读。
    """
    box = Sandbox(tmp_path)
    proc = box.run("--host-assert", env=box.env(ssh_config=tmp_path / "no-such-ssh-config"))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "不可判定" in proc.stderr
    assert "MIGAO_BMINI_SSH_CONFIG" in proc.stderr, "没给出出口（怎么让它可判定）"


# ── ② 顺序闸门 ────────────────────────────────────────────────────────────────
def test_bypassed_release_line_is_a_named_refusal_and_never_cuts(tmp_path: Path):
    """发布线被旁路（release 上有 main 没有的提交）⇒ 具名拒绝，**且远端 release ref 逐字不变**。

    这一条同时钉住「cut 是显式动作」：脚本只许调 `cut-release.sh --check`。
    """
    box = Sandbox(tmp_path, release_mode="bypass")
    before = box.release_sha()
    proc = box.run()
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "发布线被旁路" in proc.stderr, proc.stderr
    assert "./scripts/cut-release.sh" in proc.stderr, "没给出出口（显式 cut 的那条命令）"
    assert box.release_sha() == before, "脚本自己动了发布线（cut 不是显式动作了）"
    assert box.calls() == [], f"发布线不合规却已经开始构建：{box.calls()}"


def test_checkout_not_on_the_release_line_is_refused(tmp_path: Path):
    """2026-11-21 的形态：检出停在**别的地方**（这里 = main）而构建照样能跑 ⇒ 必须拒绝。

    `origin/release ⊆ origin/main` 单独成立并不够 —— 那句「从 release 构建」只有在
    **HEAD == origin/release** 时才是真的。
    """
    box = Sandbox(tmp_path, release_mode="head-main")
    proc = box.run()
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "本检出不是发布线" in proc.stderr, proc.stderr
    assert "origin/release" in proc.stderr
    assert box.calls() == [], f"检出不等于发布线却已经开始构建：{box.calls()}"


def test_dirty_worktree_is_refused(tmp_path: Path):
    """工作区有未提交改动 ⇒ 产出的包不是 origin/release 的内容 ⇒ 拒绝。"""
    box = Sandbox(tmp_path)
    (box.root / "frontend" / "bmini-app" / "project.config.json").write_text(
        '{"tampered": true}', encoding="utf-8"
    )
    proc = box.run()
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "未提交的改动" in proc.stderr, proc.stderr
    assert box.calls() == [], f"工作区不干净却已经开始构建：{box.calls()}"


def test_missing_release_branch_is_refused(tmp_path: Path):
    """`origin/release` 不存在 ⇒ 拒绝（否则「构建」会退化成「工作区是什么就发什么」）。"""
    box = Sandbox(tmp_path, release_mode="no-release")
    proc = box.run()
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "拿不到 origin/release" in proc.stderr, proc.stderr
    assert box.calls() == []


def test_unreachable_origin_is_undecidable(tmp_path: Path):
    """取不到远端 ⇒ 退 **3**（「不知道发布线在哪」不当「发布线没问题」）。"""
    box = Sandbox(tmp_path)
    _git(box.root, "remote", "set-url", "origin", str(tmp_path / "no-such-origin.git"))
    proc = box.run()
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "不可判定" in proc.stderr
    assert box.calls() == []


def test_cut_release_reports_a_missing_release_line_instead_of_a_fake_bypass(tmp_path: Path):
    """`origin/release` 不存在时，`cut-release.sh --check` 必须报「尚不存在」并退 0 —— 不许报「被旁路」。

    实测缺陷（本 PR 顺带修）：`git rev-parse <ref>` 在 ref 不存在时会把 **ref 名本身**打到 stdout
    （退出码 128 被 `|| true` 吞掉）⇒ `release_sha` 非空但不是一个 sha ⇒ 走到「旁路」分支，
    打出「发布线被旁路（origin/）」并因 `git log <sha>..origin/release` 再退 **128**。
    判据 = 退 0 + 输出含「尚不存在」，且**不**出现「被旁路」。
    """
    box = Sandbox(tmp_path, release_mode="no-release")
    proc = subprocess.run(
        ["bash", str(box.root / "scripts" / "cut-release.sh"), "--check"],
        cwd=box.root,
        env=box.env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "尚不存在" in out, out
    assert "被旁路" not in out, f"把「发布线还没建」误报成「发布线被旁路」：{out}"


# ── ③④ 构建 + 上传前断言 ──────────────────────────────────────────────────────
def test_assert_failure_blocks_the_upload(tmp_path: Path):
    """构建出的产物是测试域、却按 prod 断言 ⇒ 退 1，**上传一次都没发生**（顺序即安全顺序）。"""
    box = Sandbox(tmp_path, dist_origin=TEST_ORIGIN)
    proc = box.run("--upload", "--version", "1.2.3", "--key", box.upload_key())
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "migaozn.com" in (proc.stdout + proc.stderr), "红在域名策略上，不是别的原因"
    assert not box.npx_marker.exists(), "断言没过却调用了上传通道"


def test_a_drifted_dist_detected_by_the_pre_upload_assert_blocks_the_upload(tmp_path: Path):
    """判据 ④ 的独立红证：**上传前那道断言**真的会拦。

    做法 = 让代理脚本在**第 2 次**断言调用前把 `localhost` 写进 `app.js`（第 1 次是构建内部的断言，
    那时产物还是干净的）⇒ 本脚本的上传前断言必须当场判红，上传不发生。
    """
    box = Sandbox(tmp_path)
    proc = box.run(
        "--upload", "--version", "1.2.3", "--key", box.upload_key(), env=box.env(tamper_on=2)
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "localhost" in (proc.stdout + proc.stderr)
    assert "拒绝上传" in proc.stderr, proc.stderr
    assert not box.npx_marker.exists(), "上传前断言拦住了，却仍然上传了"


def test_ordering_is_build_then_asserts_then_upload(tmp_path: Path):
    """顺序实测（三条判据同一份 marker 日志）：`npm → assert → assert → assert → npx`。

    三次断言 = 构建内部 / **本脚本的上传前断言** / upload 自己的那道（后两道是双保险，
    断言便宜、而传错包不可逆）。少一次 ⇒ 「上传前断言」被摘掉了 ⇒ 本判据红。
    """
    box = Sandbox(tmp_path)
    proc = box.run("--upload", "--version", "1.2.3", "--key", box.upload_key())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert box.calls() == ["npm", "assert", "assert", "assert", "npx"], box.calls()


# ── ⑤ 版本号 ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("args", "note"),
    [
        (("--upload",), "缺 --version"),
        (("--upload", "--version", "1.2"), "形态不是 X.Y.Z"),
        (("--version", "1.2.3"), "给了版本号却没 --upload（漏了上传开关）"),
    ],
    ids=["missing-version", "malformed-version", "version-without-upload"],
)
def test_upload_requires_an_explicit_version(tmp_path: Path, args: tuple[str, ...], note: str):
    """版本号必须显式给、形态可判（不自动递增、不从 package.json 猜）⇒ 缺/错 = 用法错误退 2。"""
    box = Sandbox(tmp_path)
    proc = box.run(*args)
    assert proc.returncode == 2, f"{note}：期望退 2，实得 {proc.returncode}\n{proc.stdout}{proc.stderr}"
    assert "用法错误" in proc.stderr
    assert box.calls() == [], f"{note}：用法错误却已经开始干活 {box.calls()}"


# ── ⑥ 回读 + 可粘贴行 / 比值三态 ───────────────────────────────────────────────
def _record_rows(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("| ")]


def test_upload_prints_a_pasteable_record_row(tmp_path: Path):
    """上传成功后必须打印一行**可直接粘贴**进 docs 发布记录表的 Markdown 行（6 列、读数逐值可复算）。"""
    box = Sandbox(tmp_path)
    proc = box.run("--upload", "--version", "1.2.3", "--desc", "首个线上版", "--key", box.upload_key())
    assert proc.returncode == 0, proc.stdout + proc.stderr

    dist_bytes = int(box.dist_bytes_file.read_text(encoding="utf-8").strip())
    rows = _record_rows(proc.stdout)
    assert len(rows) == 1, f"应恰好有 1 行可粘贴记录，实得 {rows}"
    row = rows[0]
    assert row.count("|") == 7, f"列数不对（发布记录表是 6 列）：{row}"
    assert "| 1.2.3 |" in row
    assert DEPLOY_ALIAS in row and "origin/release" in row
    assert f"{box.release_sha()[:7]}" in row, "没把构建的那条 release sha 记进去（事后没法对账）"
    assert f"{dist_bytes:,} 字节" in row, f"dist 读数不是现取的 dist 字节合计：{row}"
    assert f"dist {dist_bytes:,} 字节" in row
    assert "1.000" in row, f"比值应为 dist÷TOTAL=1.000（TOTAL 桩给了同一份字节）：{row}"
    # 时间必须是本机可读形态（2026-11-23 15:31；时区口径见 issue #5352）
    assert any(part.strip()[:4].isdigit() and ":" in part for part in row.split("|")), row


def test_ratio_out_of_band_exits_3(tmp_path: Path):
    """比值越界（TOTAL 是 dist 的两倍）⇒ **警告并退 3**（不可判定），且**不许**把可疑行当结论输出。"""
    box = Sandbox(tmp_path)
    proc = box.run(
        "--upload", "--version", "1.2.3", "--key", box.upload_key(), env=box.env(npx_mode="double")
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "不可判定" in proc.stderr and "比值" in proc.stderr
    assert "calibration" in proc.stderr, "没指出口径台账在哪（出口不可行动）"
    assert _record_rows(proc.stdout) == [], "越界时仍把可粘贴行打到了 stdout（会被直接粘进台账）"


def test_missing_total_in_the_log_is_undecidable(tmp_path: Path):
    """上传日志里抓不到 TOTAL（例如走 `--key` 的 miniprogram-ci 通道，它不打印这个读数）⇒ 退 3，不猜。"""
    box = Sandbox(tmp_path)
    proc = box.run(
        "--upload", "--version", "1.2.3", "--key", box.upload_key(), env=box.env(npx_mode="silent")
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "TOTAL" in proc.stderr and "不可判定" in proc.stderr
    assert _record_rows(proc.stdout) == [], "抓不到读数却产出了记录行（等于编了一个数）"


# ── ⑦ 默认安全：不带 --upload 只构建 + 断言 ───────────────────────────────────
def test_default_run_builds_and_asserts_but_never_uploads(tmp_path: Path):
    """缺省档 = ①~④，明确打「未上传」，且**不产出**记录行（没有 TOTAL 就不猜读数）。"""
    box = Sandbox(tmp_path)
    proc = box.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert box.calls() == ["npm", "assert", "assert"], box.calls()
    assert not box.npx_marker.exists(), "没给 --upload 却上传了"
    assert "未上传" in proc.stdout
    assert _record_rows(proc.stdout) == [], "没上传却产出了「可粘贴发布记录行」"


# ── ⑧ 单一来源 / 不复刻判据 ───────────────────────────────────────────────────
def test_script_reuses_instead_of_reimplementing():
    """编排层**不得**复制判据：无域名常量、无上限常量、`cut-release` 只以 `--check` 出现。"""
    text = RELEASE_SCRIPT.read_text(encoding="utf-8")
    assert RELEASE_SCRIPT.is_file(), f"缺少 {RELEASE_SCRIPT}"

    # 域名常量只许住在 bmini-experience.sh（三个 TARO_APP_* 的注入点）
    for token in ("cytda", "migaozn"):
        assert token not in text, f"脚本里出现了域名常量 {token}（第二把尺子 ⇒ 与 bmini-experience.sh 会各改各的）"
    # 上限常量只许住在 deploy/scripts/bmini-dist-budget.json（判据侧由其读口读）
    for token in (str(CAP_BYTES),):
        assert token not in text, f"脚本里出现了上限常量 {token}"

    # 复用（而不是自己拼 Taro / 自己写断言）：三条被编排的脚本都得点到
    for dep in ("scripts/bmini-experience.sh", "deploy/scripts/bmini-assert-dist.sh", "cut-release.sh"):
        assert dep in text, f"没有复用 {dep}"
    # 只看**代码行**（注释 / 文档字符串里引用历史形态不算第二把尺子）
    code = [
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    ]
    for token, why in (
        ("build:weapp", "自己拼了 Taro 构建命令（常量注入会漏）"),
        ("TARO_APP_", "自己注入了 TARO_APP_* 常量（应交给 bmini-experience.sh）"),
    ):
        offenders = [line.strip() for line in code if token in line]
        assert not offenders, f"{why}：{offenders}"

    # cut 是显式动作：唯一允许的调用形态是 --check
    cut_calls = [
        line.strip()
        for line in text.splitlines()
        if 'bash "$CUT_RELEASE"' in line
    ]
    assert cut_calls, "没有调用 cut-release.sh（那「发布线 ⊆ main」就没人判了）"
    for line in cut_calls:
        assert "--check" in line, f"cut-release.sh 被以非 --check 形态调用（会自己动发布线）：{line}"


def test_ratio_band_is_read_from_the_budget_not_hardcoded(tmp_path: Path):
    """比值尺度**现读**预算文件的 `calibration` 台账：篡改台账 ⇒ 同一份产物变成「越界」退 3。

    这是「不是另存了一份尺子」的判别力自证 —— 若脚本把 0.97~1.03 抄了一份，篡改台账不会有任何反应。
    """
    def _halve_the_wechat_reading(budget: dict) -> dict:
        latest = max(budget["calibration"], key=lambda row: row["date"])
        latest["wechatBytes"] = latest["distBytes"] // 2  # 台账说「TOTAL 只有 dist 的一半」⇒ 中心比值 = 2.0
        return budget

    box = Sandbox(tmp_path, budget_tamper=_halve_the_wechat_reading)
    proc = box.run("--upload", "--version", "1.2.3", "--key", box.upload_key())
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "不可判定" in proc.stderr and "比值" in proc.stderr


# ── ⑨ 文档接线 ────────────────────────────────────────────────────────────────
def test_docs_point_at_the_one_command_and_keep_the_three_steps():
    """文档必须指向这条命令，**且底层三步仍在**（cut / build / upload + 发布记录表 + 部署机裁定不许被删）。"""
    text = DOCS.read_text(encoding="utf-8")
    assert "scripts/bmini-release.sh" in text, "docs 没指向这条命令（脚本写了没人知道 = 假绿）"
    for step in (
        "./scripts/cut-release.sh",
        "scripts/bmini-experience.sh build  --env prod",
        "scripts/bmini-experience.sh upload --version",
    ):
        assert step in text, f"底层三步之一被删了/改了形态：{step}"
    for kept in ("提审前检查清单", "发布记录", "生产包**只在部署机上构建 + 上传**"):
        assert kept in text, f"文档里既有的既有段落被删掉了：{kept}"


def test_script_parses():
    """闸门脚本自己必须语法成立（`bash -n`）—— 语法坏了的闸门等于没有闸门。"""
    proc = subprocess.run(["bash", "-n", str(RELEASE_SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
