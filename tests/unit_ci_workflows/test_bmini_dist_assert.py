# case_ids: BM-068
r"""B 端小程序 weapp 产物断言 + 体验版发布入口 + CI 接线的判据（issue #8980）。

## 病（2026-11-21 首次手工发体验版，AppID `wx6ee2f682c1b4822c`）

| # | 形态 | 当时为什么没红 |
|---|---|---|
| 1 | **生产常量靠人手记**：`TARO_APP_API_URL` / `TARO_APP_AI_API_URL` / `TARO_APP_PUBLIC_APP_ORIGIN` 少给一个，产物静默烘进测试域（或 `http://localhost:8080`） | 上传照样成功、微信照样收包；只有真机**运行时**连不上，而开发者工具勾了「不校验合法域名」时连那个错都看不见 |
| 2 | **体积没有闸门**：本地构建不报，只在上传那一刻由微信报错（当时记的「主包 2,079,753 / 上限 2,097,152」后来复现不出来 ⇒ 见 `test_bmini_dist_budget.py` 的口径证据链，#8981） | 判据只认 dist 字节，且当时没人钉口径 |
| 3 | **上传命令靠临时拼**：项目目录 / appid / 版本号 / 通道每次现敲 | 换机器、换人就得重来；顺序（先构建、`assert`、再上传）全靠人记得 |

## 本文件锁什么（每条都能单独变红；判据本体 = `deploy/scripts/bmini-assert-dist.sh`）

| # | 判据 | 红证（本文件实跑） |
|---|---|---|
| 1 | **结构**：`app.json` 的 `pages` 非空、`app.js` 在、每页 `.js`/`.wxml`/`.json` 齐备（`.wxss` **允许缺省**） | 删掉某页的 `.wxml` ⇒ 退 1；`app.json` 整个拿掉 ⇒ 退 1 |
| 2 | **域名策略**：`prod` ⇒ `migaozn.com` 0 次、`cytda.com` ≥1、**无 `localhost`**；`test` ⇒ 反向 | prod 模式喂含 `migaozn.com` 的树 ⇒ 退 1；只给了 label origin 而 API 仍 localhost ⇒ 退 1（**前两条抓不住这一形态**，故单列） |
| 3 | **体积**：主包 ≤ 单包上限 − 主包预留、每个分包 ≤ 单包上限、总包 ≤ 总包上限；常量**唯一来源** = `deploy/scripts/bmini-dist-budget.json`（issue #8979 / #8981） | 主包顶过预算 1 字节 ⇒ 退 1 且打印归因（哪个包 / 超多少 / 最大文件 / 复算命令） |
| 4 | **不可判定 ≠ 通过**：dist 不存在 / 空目录 ⇒ 退 **3**（`0` 不许冒充） | 对不存在的目录跑 ⇒ 退 3 |
| 5 | **发布入口的顺序即安全顺序**：`scripts/bmini-experience.sh upload` **先断言、后上传**；断言红 ⇒ 一次上传都不发生（`npx` / 开发者工具 CLI 的桩**没被调用**） | 沙箱里给一份测试域产物 + `--env prod` ⇒ 退 1 且 `npx` 桩的标记文件不存在 |
| 6 | **注入的常量是哪一个**（不靠读源码）：`build --env prod` ⇒ 三个 `TARO_APP_*` 全是 `https://app.cytda.com`；`--env test` ⇒ 全是 `https://app.migaozn.com` | 沙箱里桩掉 `npm`，把三个环境变量写进标记文件后逐值断言（改错一个 ⇒ 红） |
| 7 | **上传命令的形态**（不是「跑过就算」）：`miniprogram-ci` 通道必须用 `--upload-version` —— ⚠️ 它的 CLI 里 `--version` 是「显示版本号」的**布尔开关**，写成 `--version 1.0.0` 会被吞掉 | 桩掉 `npx` 记参数 ⇒ 断言 `--appid` / `--project-path` / `--private-key-path` / `--upload-version` 四件齐备且版本号逐字 |
| 8 | **接线判据**：`.github/workflows/bmini-app.yml` 里真的有一个 step 调本脚本，且 ① `--env test`（CI 构建不注入生产常量）② 排在 `npm run build:weapp` **之后** ③ 与构建步同一个 `if:`（否则「构建被跳过、断言照跑」= 拿不存在的 dist 判红） ④ 不带 `continue-on-error` / `|| true` | `bmini_assert_wiring_problems()` 对真语料判空；五条注入式变异（摘掉 step / 改成 prod / 挪到构建前 / 加 `continue-on-error` / 摘掉 `if`）各自判非空 |

## 边界（照实登记）

- 判的是**本仓 dist 的字节**，不是微信后台的包体读数：微信按自己的规则统计主包/分包，本脚本目前无分包
  （#8979 未落地）⇒ 直接断言 dist 全量；分包引入后须按 `app.json` 的 `subPackages[].root` 剔除（偏严方向）。
- 判不了「产物能不能跑起来」（要真机 / 模拟器），也判不了微信后台的「服务器域名」白名单 ——
  后者是仓库侧无从取证的外部状态，已在 `docs/deployment/bmini-experience-release.md` 的前置条件里写明。
- 「实例判据对**真实构建产物**判绿」在 CI 侧由 `bmini-app` workflow 自己的那一步承担（同一条命令、同一份实现）；
  本文件用**同形 fixture** 覆盖绿/红两侧，故不需要在本机跑一次 `taro build`（那是分钟级重活，不该进单测）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bmini_dist import (  # noqa: E402  （预算常量 + 夹具的唯一来源，issue #8981）
    ASSERT_SCRIPT,
    BUDGET_JSON,
    CAP_BYTES,
    EXPERIENCE_SCRIPT,
    MAIN_LIMIT_BYTES,
    REPO_ROOT,
    build_dist,
    pad_dist_to,
    run_assert,
)

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "bmini-app.yml"

# 🔴 上限常量**只**来自 `deploy/scripts/bmini-dist-budget.json`（issue #8981：以前这里抄了一遍
# `2097152` / 90% 闸门，于是脚本被改宽时判据跟着假绿）。读口令 = `_bmini_dist.py`。
ASSERT_CALL = "deploy/scripts/bmini-assert-dist.sh"
WEAPP_BUILD_CMD = "npm run build:weapp"
APPID = "wx6ee2f682c1b4822c"

PROD_ORIGIN = "https://app.cytda.com"
TEST_ORIGIN = "https://app.migaozn.com"

DEFAULT_PAGE = "pages/home/index"


# ── 夹具（`build_dist` / `run_assert` / `pad_dist_to`）住在 `_bmini_dist.py` ─────────
# 与判据 `test_bmini_dist_budget.py` 共用同一份：两处各造一份 ⇒ 迟早各判一件事。


# ── 判据 1~4：断言本体（绿 / 红 / 不可判定 三态分开）──────────────────────────
@pytest.mark.parametrize(
    ("env_name", "body"),
    [("prod", PROD_ORIGIN), ("test", TEST_ORIGIN)],
)
def test_green_on_a_weapp_shaped_tree(tmp_path: Path, env_name: str, body: str):
    """绿：域名与 env 一致、结构齐备、体积远低于闸门 ⇒ 退 0。"""
    dist = build_dist(tmp_path / "dist", body=body)
    proc = run_assert(dist, env_name)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "❌" not in proc.stdout


def test_prod_rejects_test_domain_leak(tmp_path: Path):
    """红证①（issue 的核心形态）：prod 模式喂含 `migaozn.com` 的产物 ⇒ 必须红。"""
    dist = build_dist(tmp_path / "dist", body="https://app.migaozn.com")
    proc = run_assert(dist, "prod")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "migaozn.com" in proc.stdout


def test_prod_rejects_missing_prod_domain(tmp_path: Path):
    """红证①的对照臂：产物里一个 cytda 都没有（常量一个都没注入）⇒ 也必须红。"""
    dist = build_dist(tmp_path / "dist", body="https://api.example.com")
    proc = run_assert(dist, "prod")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "cytda.com" in proc.stdout


def test_prod_rejects_localhost_leftover(tmp_path: Path):
    """红证（只注入 2/3 件套的形态）：cytda 有、migaozn 无，但 API 仍是 localhost ⇒ 必须红。

    前两条判据在这一形态上**都会绿**（label origin 给了 cytda ⇒ migaozn=0、cytda≥1），
    所以这一条是独立判据，不是「顺手加的」。
    """
    dist = build_dist(tmp_path / "dist", body=PROD_ORIGIN)
    with (dist / "app.js").open("a", encoding="utf-8") as fh:
        fh.write('const API_BASE_URL = "http://localhost:8080";\n')
    proc = run_assert(dist, "prod")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "localhost" in proc.stdout


def test_test_env_rejects_prod_domain_leak(tmp_path: Path):
    """反向：test 模式喂含 `cytda.com` 的产物（把生产常量注进了测试包）⇒ 必须红。"""
    dist = build_dist(tmp_path / "dist", body=PROD_ORIGIN)
    proc = run_assert(dist, "test")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "cytda.com" in proc.stdout


@pytest.mark.parametrize("ext", ["wxml", "js", "json"])
def test_missing_page_file_is_red(tmp_path: Path, ext: str):
    """红证②：删掉某页的一个页文件 ⇒ 必须红（`.wxss` 不在射程内 = 允许缺省）。"""
    dist = build_dist(tmp_path / "dist", omit=(f"{DEFAULT_PAGE}.{ext}",))
    proc = run_assert(dist, "test")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert f"{DEFAULT_PAGE}.{ext}" in proc.stdout


def test_missing_app_json_is_red(tmp_path: Path):
    """dist 在、但 app.json 没了 ⇒ 结构判红（不是「不可判定」）。"""
    dist = build_dist(tmp_path / "dist")
    (dist / "app.json").unlink()
    proc = run_assert(dist, "test")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "app.json" in proc.stdout


def test_empty_pages_list_is_red(tmp_path: Path):
    """pages 为空数组 ⇒ 红（没有页面可访问，不是「结构没问题」）。"""
    dist = build_dist(tmp_path / "dist", pages=())
    proc = run_assert(dist, "test")
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_oversized_package_is_red_and_prints_top_entries(tmp_path: Path):
    """红证③：把主包顶过预算 ⇒ 红，且必须**可归因**（哪个包 / 超多少字节 / 最大的文件 / 复算命令）。"""
    dist = build_dist(tmp_path / "dist", extra_bytes=MAIN_LIMIT_BYTES)
    proc = run_assert(dist, "test")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = proc.stdout
    assert "主包" in out, out
    assert "超预算" in out, "没说出超了多少字节"
    assert str(MAIN_LIMIT_BYTES) not in out  # 读数带千分位（人读）；机器可复算的是常量文件
    assert "padding.bin" in out, "没指出主包里最大的文件（无从下手）"
    assert "复算" in out and "bmini-dist-budget.json" in out, "没给出常量出处 / 复算命令"


def test_at_the_gate_is_green_and_one_byte_over_is_red(tmp_path: Path):
    """边界语义 = 「主包 + 预留 ≤ 上限」（#8979 要的是 **≥**300KB 余量）：

    恰好等于预算 ⇒ 绿（余量恰好等于预留）；再多 1 字节 ⇒ 红。
    """
    at_limit = pad_dist_to(build_dist(tmp_path / "dist"), MAIN_LIMIT_BYTES)
    proc = run_assert(at_limit, "test")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    over = pad_dist_to(build_dist(tmp_path / "dist-over"), MAIN_LIMIT_BYTES + 1)
    proc = run_assert(over, "test")
    assert proc.returncode == 1, "边界没有从严：比预算多 1 字节仍判绿"


@pytest.mark.parametrize("shape", ["absent", "empty", "not_a_dir"])
def test_undecidable_shapes_exit_3(tmp_path: Path, shape: str):
    """红证④（三态分离）：dist 不存在 / 空目录 / 不是目录 ⇒ **退 3**，绝不当 0 读。"""
    if shape == "absent":
        dist = tmp_path / "never-built"
    elif shape == "empty":
        dist = tmp_path / "empty"
        dist.mkdir()
    else:
        dist = tmp_path / "a-file"
        dist.write_text("not a dir", encoding="utf-8")
    proc = run_assert(dist, "test")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "3" in proc.stderr  # 出声：退出码与原因都要看得见


@pytest.mark.parametrize(
    ("args", "expect_rc"),
    [
        ((), 2),  # 缺 dist 位置参数
        (("--env", "staging"), 2),  # env 取值非法
        (("--nope",), 2),  # 未知参数
    ],
)
def test_usage_errors_exit_2(tmp_path: Path, args: tuple[str, ...], expect_rc: int):
    dist = build_dist(tmp_path / "dist")
    cmd = ["bash", str(ASSERT_SCRIPT)]
    if args:
        cmd += list(args)
        if "--env" in args or "--nope" in args:
            cmd.append(str(dist))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == expect_rc, proc.stdout + proc.stderr


def test_both_scripts_parse():
    """两个脚本都必须语法成立（`bash -n`）—— 语法坏了的闸门等于没有闸门。"""
    for script in (ASSERT_SCRIPT, EXPERIENCE_SCRIPT):
        assert script.is_file(), f"缺少 {script}"
        proc = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{script}: {proc.stderr}"


def test_wechat_readout_is_equivalence_not_a_fold_factor(tmp_path: Path):
    """体积段的**口径交代**（#8981 的收口）：把等价读数与出处照实打出来，**不**再按 ×1.425 折算。

    #8981 当初的结论（dist 1,459,140 ↔ 微信后台 2,079,753 ≈ ×1.425）在本仓与部署机上都找不到
    可复算的产物（部署机四份产物 + devtool 日志全量核对过）⇒ 登记为**不可复现读数**。
    实测等价（2026-11-23 部署机：dist 1,465,245 → devtools TOTAL 1,461,748，比值 **0.998**）
    ⇒ 判据直接判 dist 字节（偏严方向），**不叠系数**：叠了会把闸门压到 ≈1.47MB、制造假红。
    """
    dist = build_dist(tmp_path / "dist")
    proc = run_assert(dist, "test")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "微信口径" in proc.stdout, "口径交代没打出来（读数不可复算）"
    assert "1.425" not in proc.stdout, "按 ×1.425 折算的假读数回流了（它凭空算出 9,170 字节余量）"


# ── 判据 5~7：发布入口的行为（沙箱里桩掉 npm / npx，零网络、零真构建）──────────
STUB_NPM = """#!/bin/bash
set -u
printf 'TARO_APP_API_URL=%s\\nTARO_APP_AI_API_URL=%s\\nTARO_APP_PUBLIC_APP_ORIGIN=%s\\n' \\
  "${TARO_APP_API_URL:-}" "${TARO_APP_AI_API_URL:-}" "${TARO_APP_PUBLIC_APP_ORIGIN:-}" \\
  > "${STUB_NPM_MARKER}"
rm -rf dist
mkdir -p dist/pages/home
printf '{"pages":["pages/home/index"]}' > dist/app.json
printf 'const ORIGIN = "%s";\\n' "${STUB_DIST_ORIGIN:-}" > dist/app.js
printf '// page\\n' > dist/pages/home/index.js
printf '<view/>\\n' > dist/pages/home/index.wxml
printf '{}\\n' > dist/pages/home/index.json
exit 0
"""

STUB_NPX = """#!/bin/bash
set -u
printf '%s\\n' "$*" > "${STUB_NPX_MARKER}"
exit 0
"""


class Sandbox:
    """一棵**最小仓树**：两个真脚本 + 一个 bmini-app 目录 + `npm`/`npx` 桩。

    为什么复制脚本而不是直接跑仓内那份：两个脚本都用 `BASH_SOURCE` 推导 ROOT
    ⇒ 复制到临时仓里，它们就会在沙箱内构建/断言/上传（零网络、不碰真 dist）。
    """

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "repo"
        (self.root / "deploy" / "scripts").mkdir(parents=True)
        (self.root / "scripts").mkdir()
        shutil.copy2(ASSERT_SCRIPT, self.root / ASSERT_CALL)
        # 包体预算的**唯一来源**也必须在沙箱里（脚本按 BASH_SOURCE 找同级目录，issue #8981）：
        # 少了它，体积判据当场判红 —— 那正是「没有常量就没有闸门」该有的行为。
        shutil.copy2(BUDGET_JSON, self.root / "deploy" / "scripts" / BUDGET_JSON.name)
        shutil.copy2(EXPERIENCE_SCRIPT, self.root / "scripts" / "bmini-experience.sh")
        self.app_dir = self.root / "frontend" / "bmini-app"
        (self.app_dir / "node_modules").mkdir(parents=True)
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
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.npm_marker = tmp_path / "npm-called.txt"
        self.npx_marker = tmp_path / "npx-called.txt"
        self._write_stub("npm", STUB_NPM)
        self._write_stub("npx", STUB_NPX)

    def _write_stub(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    @property
    def dist(self) -> Path:
        return self.app_dir / "dist"

    def env(self, *, stub_dist_origin: str = PROD_ORIGIN) -> dict[str, str]:
        env = os.environ.copy()
        env.pop("MINIPROGRAM_UPLOAD_KEY", None)
        env["PATH"] = f"{self.bin}{os.pathsep}{env.get('PATH', '')}"
        env["STUB_NPM_MARKER"] = str(self.npm_marker)
        env["STUB_NPX_MARKER"] = str(self.npx_marker)
        env["STUB_DIST_ORIGIN"] = stub_dist_origin
        return env

    def run(self, *args: str, env: dict[str, str] | None = None):
        return subprocess.run(
            ["bash", str(self.root / "scripts" / "bmini-experience.sh"), *args],
            cwd=self.root,
            env=env if env is not None else self.env(),
            capture_output=True,
            text=True,
            timeout=180,
        )


def test_upload_refuses_when_the_assert_fails(tmp_path: Path):
    """判据 5（红臂）：产物是测试域、却按 `--env prod` 上传 ⇒ 退 1，且**一次上传都没发生**。"""
    box = Sandbox(tmp_path)
    build_dist(box.dist, body=TEST_ORIGIN)
    key = tmp_path / "private.key"
    key.write_text("not-a-real-key", encoding="utf-8")
    proc = box.run("upload", "--version", "1.0.0", "--env", "prod", "--key", str(key))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "migaozn.com" in (proc.stdout + proc.stderr)  # 红在域名策略上，不是别的原因
    assert not box.npx_marker.exists(), "断言没过却调用了上传通道（顺序即安全顺序被破坏）"


def test_upload_reaches_miniprogram_ci_with_the_verified_flags(tmp_path: Path):
    """判据 5 的对照臂 + 判据 7：产物合规 ⇒ 走到 miniprogram-ci，且参数面逐件正确。

    ⚠️ 这一条同时钉住一个真实陷阱：miniprogram-ci CLI 的 `--version` 是「显示版本号」的布尔开关，
    上传版本号只能走 `--upload-version`；写成 `--version 1.0.0` 会被吞掉（版本号不上传）。
    """
    box = Sandbox(tmp_path)
    build_dist(box.dist, body=PROD_ORIGIN)
    key = tmp_path / "private.key"
    key.write_text("not-a-real-key", encoding="utf-8")
    proc = box.run("upload", "--version", "1.2.3", "--env", "prod", "--key", str(key))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert box.npx_marker.is_file(), "对照臂失败：沙箱里的上传通道桩没被调用"
    call = box.npx_marker.read_text(encoding="utf-8")
    assert "miniprogram-ci@2" in call and "upload" in call
    assert f"--appid {APPID}" in call
    assert "--project-path" in call and "--private-key-path" in call
    assert "--upload-version 1.2.3" in call
    assert "--version 1.2.3" not in call, "用了 miniprogram-ci 的 --version（它是显示版本号的布尔开关）"


def test_upload_requires_an_explicit_version(tmp_path: Path):
    """版本号必须显式给（不自动递增、不猜）—— 缺了就是用法错误（退 2），不是「随便发一个」。"""
    box = Sandbox(tmp_path)
    build_dist(box.dist, body=PROD_ORIGIN)
    proc = box.run("upload", "--env", "prod")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not box.npx_marker.exists()


@pytest.mark.parametrize(("env_name", "expected"), [("prod", PROD_ORIGIN), ("test", TEST_ORIGIN)])
def test_build_injects_the_three_constants(tmp_path: Path, env_name: str, expected: str):
    """判据 6：`build --env X` 注入的三个 `TARO_APP_*` 逐值正确（桩掉 npm，读环境变量）。"""
    box = Sandbox(tmp_path)
    proc = box.run("build", "--env", env_name, env=box.env(stub_dist_origin=expected))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert box.npm_marker.is_file(), "构建步没有被调用"
    injected = dict(
        line.split("=", 1)
        for line in box.npm_marker.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert injected.get("TARO_APP_API_URL") == expected
    assert injected.get("TARO_APP_AI_API_URL") == expected
    assert injected.get("TARO_APP_PUBLIC_APP_ORIGIN") == expected
    assert box.npx_marker.exists() is False  # build 不许上传


# ── 判据 8：CI 接线（脚本写了没人跑 = 假绿）────────────────────────────────────
def bmini_assert_wiring_problems(workflow_text: str) -> list[str]:
    """把「接线是否真的存在且真会拦」做成纯函数（可对**注入的文本**判红，见下）。"""
    try:
        doc = yaml.safe_load(workflow_text) or {}
    except yaml.YAMLError as exc:  # 解析不了 ⇒ 无法判定接线 ⇒ 判红，不静默放行
        return [f"bmini-app.yml 不是合法 YAML：{exc}"]
    jobs = doc.get("jobs") or {}
    calls: list[tuple[str, int, dict, list]] = []
    for job_id, job in jobs.items():
        steps = (job or {}).get("steps") or []
        for idx, step in enumerate(steps):
            run = step.get("run") or ""
            if ASSERT_CALL in run:
                calls.append((job_id, idx, step, steps))
    if not calls:
        return [f"没有任何 step 调用 {ASSERT_CALL}（脚本写了但没人跑 = 假绿）"]

    problems: list[str] = []
    for job_id, idx, step, steps in calls:
        run = step.get("run") or ""
        if "--env test" not in run:
            problems.append(f"{job_id}: 产物断言没用 --env test（CI 构建不注入生产常量 ⇒ 产物是测试域）")
        if "|| true" in run:
            problems.append(f"{job_id}: 产物断言带 `|| true` ⇒ 红了也不拦")
        if step.get("continue-on-error") in (True, "true"):
            problems.append(f"{job_id}: 产物断言带 continue-on-error ⇒ 红了也不拦")
        build_idx = [i for i, s in enumerate(steps) if WEAPP_BUILD_CMD in (s.get("run") or "")]
        if not build_idx:
            problems.append(f"{job_id}: 找不到 `{WEAPP_BUILD_CMD}` 步 ⇒ 断言跑在什么产物上不可判定")
            continue
        if idx < build_idx[0]:
            problems.append(f"{job_id}: 产物断言（第 {idx} 步）排在 weapp 构建（第 {build_idx[0]} 步）之前")
        build_if = (steps[build_idx[0]].get("if") or "").strip()
        if (step.get("if") or "").strip() != build_if:
            problems.append(
                f"{job_id}: 产物断言的 `if:` 与 weapp 构建步不一致（构建被跳过时断言仍会跑，"
                f"拿不存在的 dist 判红）"
            )
    return problems


def test_workflow_runs_the_assert_after_the_weapp_build():
    """接线判据：真语料必须无问题（脚本存在 + workflow 真的调了它 + 顺序/条件/env 都对）。"""
    assert ASSERT_SCRIPT.is_file(), f"缺少判据本体 {ASSERT_SCRIPT}"
    problems = bmini_assert_wiring_problems(WORKFLOW.read_text(encoding="utf-8"))
    assert problems == [], "\n".join(problems)


def _mutate(mutator) -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")) or {}
    mutator(doc)
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def _assert_steps(doc: dict) -> list[dict]:
    return [
        step
        for job in (doc.get("jobs") or {}).values()
        for step in ((job or {}).get("steps") or [])
        if ASSERT_CALL in (step.get("run") or "")
    ]


def _drop_assert_step(doc: dict) -> None:
    for job in (doc.get("jobs") or {}).values():
        job["steps"] = [
            s for s in (job or {}).get("steps") or [] if ASSERT_CALL not in (s.get("run") or "")
        ]


def _switch_to_prod(doc: dict) -> None:
    for step in _assert_steps(doc):
        step["run"] = step["run"].replace("--env test", "--env prod")


def _move_before_build(doc: dict) -> None:
    for job in (doc.get("jobs") or {}).values():
        steps = job.get("steps") or []
        moved = [s for s in steps if ASSERT_CALL in (s.get("run") or "")]
        rest = [s for s in steps if ASSERT_CALL not in (s.get("run") or "")]
        build_idx = next(
            (i for i, s in enumerate(rest) if WEAPP_BUILD_CMD in (s.get("run") or "")), 0
        )
        job["steps"] = rest[:build_idx] + moved + rest[build_idx:]


def _add_continue_on_error(doc: dict) -> None:
    for step in _assert_steps(doc):
        step["continue-on-error"] = True


def _drop_if(doc: dict) -> None:
    for step in _assert_steps(doc):
        step.pop("if", None)


@pytest.mark.parametrize(
    "mutator",
    [
        _drop_assert_step,
        _switch_to_prod,
        _move_before_build,
        _add_continue_on_error,
        _drop_if,
    ],
    ids=[
        "drop-the-step",
        "env-prod-in-ci",
        "moved-before-build",
        "continue-on-error",
        "if-dropped",
    ],
)
def test_wiring_judge_has_teeth(mutator):
    """判别力自证：五种「写了但没用」的变异各自必须判红（否则上面那条就是恒绿）。"""
    problems = bmini_assert_wiring_problems(_mutate(mutator))
    assert problems, f"变异 {mutator.__name__} 没有被判红 —— 接线判据是恒绿的"
