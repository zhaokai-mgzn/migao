# case_ids: MC-392
"""依赖工具链钉住（issue #9343）：Node/npm 版本漂移进不来的**类级**守卫。

## 病灶（2026-11-28 实测，不是理论风险）

仓库里**零钉**：无 `.nvmrc`、无 `engines`、无 `.npmrc`。而 CI 的 admin-web 腿跑 Node 22
（npm 10），开发机/子代理跑 Node 24（npm 11）⇒ 两边重算 `package-lock.json` 的结果**不同**：

- `node_modules/vitest/node_modules/@vitest/mocker` 声明 `msw: ^2.4.9`
  ⇒ **npm 10** 要求 lock 里有**嵌套**的 `msw@2.15.0` 条目；
- **npm 11 会把它删掉**（解析口径变了）。

后果实测：8 个 dependabot PR 全部卡死 2 小时，`npm ci` 逐字报
`Missing: msw@2.15.0 from lock file`；而这些 PR 的 lock 正是 dependabot（较新 npm）重算的。
⇒ 这不是某个 PR 的问题，是「工具链没钉 + 两端 npm 大版本不同」的结构性缺口。

## 判据（每条都带红证，恒绿=没判据）

1. `.nvmrc` 存在且等于 CI 腿用的 major（现取 24）；
2. `frontend/admin-web/package.json` 的 `engines.node` / `engines.npm` 与 `.nvmrc` 同 major；
3. `.npmrc` 有 `engine-strict=true` —— 让「用错 npm 版本」**当场失败**，而不是悄悄产出坏 lock；
4. **凡是用 `npm ci` 装 `frontend/admin-web` 的 workflow job，node-version 必须等于 `.nvmrc`**
   （漂移的真身就在这里：一条腿留在旧版本，它就会拒收新 lock）；
5. 红证：把某条腿的 node-version 注入成旧版本 ⇒ 判据 4 具名红（文件 + job）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"


def _nvmrc_major() -> str:
    raw = (REPO / ".nvmrc").read_text(encoding="utf-8").strip()
    assert raw, ".nvmrc 为空（空值不是「不限」）"
    return raw.lstrip("v").split(".")[0]


def _admin_web_engines() -> dict:
    data = json.loads((REPO / "frontend" / "admin-web" / "package.json").read_text(encoding="utf-8"))
    engines = data.get("engines")
    assert isinstance(engines, dict) and engines, (
        "frontend/admin-web/package.json 缺 engines ⇒ 用错 node/npm 版本不会报错，会悄悄写坏 lock"
    )
    return engines


def _jobs_running_npm_ci_on_admin_web(root: Path) -> list[tuple[str, str, str | None]]:
    """返回 [(workflow 文件, job 名, node-version 原值)] —— 只挑真装 admin-web 的 job。"""
    hits: list[tuple[str, str, str | None]] = []
    for wf in sorted(root.glob("*.yml")):
        job = None
        buf: dict[str, list[str]] = {}
        for line in wf.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if m:
                job = m.group(1)
                buf.setdefault(job, [])
            elif job:
                buf[job].append(line)
        for name, body in buf.items():
            text = "\n".join(body)
            if "npm ci" not in text:
                continue
            if "frontend/admin-web" not in text:
                continue
            m = re.search(r"node-version:\s*'?\"?([0-9]+)", text)
            hits.append((wf.name, name, m.group(1) if m else None))
    return hits


def test_nvmrc_pins_the_ci_major_and_engines_agree():
    """判据 1+2：`.nvmrc` 与 `engines` 同 major（现取 24 / npm 11）。"""
    major = _nvmrc_major()
    engines = _admin_web_engines()
    assert f">={major}" in engines["node"].replace(" ", ""), (
        f"engines.node={engines['node']} 与 .nvmrc={major} 不同 major ⇒ 两端仍会各算一份 lock"
    )
    npm_major = re.search(r"([0-9]+)", engines["npm"].replace(" ", "")).group(1)
    assert npm_major == "11", (
        f"engines.npm={engines['npm']}：Node 24 自带 npm 11；写 10 会让本机装不上依赖或产出被 CI 拒收的 lock"
    )


def test_npmrc_makes_a_wrong_toolchain_fail_loudly():
    """判据 3：没有 engine-strict，用错 npm 版本只是一条警告 ⇒ 坏 lock 照样进库。"""
    text = (REPO / ".npmrc").read_text(encoding="utf-8")
    assert re.search(r"^engine-strict\s*=\s*true\s*$", text, re.MULTILINE), (
        ".npmrc 缺 engine-strict=true：`npm install` 在错版本下会静默产出坏 lock（issue #9343 的真因）"
    )


def test_every_admin_web_npm_ci_leg_uses_the_pinned_node():
    """判据 4：装 admin-web 的每条腿都必须跟 `.nvmrc` 同 major。"""
    major = _nvmrc_major()
    hits = _jobs_running_npm_ci_on_admin_web(WORKFLOWS)
    assert len(hits) >= 5, f"只找到 {len(hits)} 条装 admin-web 的腿，少于现取的 5 条 ⇒ 判据面缩水了"
    drifted = [(f, j, v) for (f, j, v) in hits if v != major]
    assert not drifted, (
        "这些腿装的 Node 与 .nvmrc=" + major + " 不一致，它们会拒收新 lock（issue #9343）: "
        + ", ".join(f"{f}:{j}=node{v}" for f, j, v in drifted)
    )


def test_red_proof_a_stale_leg_is_named(tmp_path):
    """判据 5·红证：把一条腿注入成旧版本 ⇒ 判据 4 必须**具名**红（不是恒绿）。"""
    wf = tmp_path / "fake.yml"
    wf.write_text(
        "jobs:\n  build:\n    steps:\n      - uses: actions/setup-node@v7\n"
        "        with:\n          node-version: '22'\n"
        "      - run: npm ci\n        working-directory: frontend/admin-web\n",
        encoding="utf-8",
    )
    hits = _jobs_running_npm_ci_on_admin_web(tmp_path)
    assert hits == [("fake.yml", "build", "22")], f"解析面没抓到这条腿: {hits}"
    assert hits[0][2] != _nvmrc_major(), "红证前提不成立：注入的旧版本恰好等于 .nvmrc"

def _dockerfiles_building_admin_web(root: Path | None = None) -> list[tuple[str, str]]:
    """返回 [(Dockerfile 相对路径, FROM node:<major>)] —— 只挑真装 admin-web 依赖的镜像。

    ⚠️ 为什么要单独判这一条（2026-11-28 血的教训）：把 CI 腿抬到 Node 24 时**漏了 Dockerfile**，
    而 `deploy-frontend.yml` 是**服务器侧构建**（`FROM node:20-alpine` ⇒ npm 10）⇒ 镜像内的
    `npm ci` 读不了 npm 11 重算的 lock ⇒ `admin-web:sha-<7>` 镜像**未产出** ⇒ 部署整腿失败
    （逐字：`服务器侧构建失败（rc=1）—— 镜像 … 未产出`）。CI 全绿但**交付断了**，
    所以这条必须和腿面一样进判据，否则同类漏网还会发生。
    """
    hits: list[tuple[str, str]] = []
    base = root or REPO
    for df in sorted(base.rglob("Dockerfile")):
        if "node_modules" in df.parts:
            continue
        text = df.read_text(encoding="utf-8")
        if "frontend/admin-web" not in text and df.parent.name != "admin-web":
            continue
        m = re.search(r"^FROM\s+node:([0-9]+)", text, re.MULTILINE)
        if m:
            hits.append((str(df.relative_to(base)), m.group(1)))
    return hits


def test_admin_web_dockerfile_uses_the_pinned_node():
    """判据 6：**服务器侧构建**的镜像也必须跟 `.nvmrc` 同 major（否则镜像产不出 = 交付断）。"""
    major = _nvmrc_major()
    hits = _dockerfiles_building_admin_web()
    assert hits, "没找到构建 admin-web 的 Dockerfile ⇒ 判据面缩水了（服务器侧构建是本仓的交付路径）"
    drifted = [(f, v) for f, v in hits if v != major]
    assert not drifted, (
        f"这些 Dockerfile 的 node 与 .nvmrc={major} 不一致，其中的 `npm ci` 会拒收当前 lock（issue #9343）: "
        + ", ".join(f"{f}=node{v}" for f, v in drifted)
    )


def test_red_proof_a_stale_dockerfile_is_named(tmp_path):
    """判据 6 的红证：把 admin-web 的 Dockerfile 注入成 `FROM node:20-alpine` ⇒ 必须**具名**红。"""
    d = tmp_path / "frontend" / "admin-web"
    d.mkdir(parents=True)
    (d / "Dockerfile").write_text("FROM node:20-alpine\nRUN npm ci\n", encoding="utf-8")
    hits = _dockerfiles_building_admin_web(tmp_path)
    assert hits == [("frontend/admin-web/Dockerfile", "20")], f"解析面没抓到: {hits}"
    assert hits[0][1] != _nvmrc_major(), "红证前提不成立：注入的版本恰好等于 .nvmrc"
