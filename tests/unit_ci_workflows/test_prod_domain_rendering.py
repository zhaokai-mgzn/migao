# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`deploy/swas/deploy.sh` **站点域名可参数化**守卫 —— 生产 `cytda.com` / 测试 `migaozn.com`。

## 病根（本单要防的形态）

生产环境（cytda.com）与测试环境（migaozn.com）共用同一份 `deploy/swas/nginx.conf`，
而该文件把域名硬编码在 5 个 `server_name` 里。若生产直接复用，nginx 会**拒绝** `cytda.com`
的请求（或落到默认 server 块），且症状是「部署成功、页面 404/502」，没有任何判据会先变红。

两条错误修法（本文件分别钉死）：

1. **再抄一份 `deploy/prod/nginx.conf`**：560 行里 400+ 行是安全口径（限流五档 / 日志脱敏 /
   HSTS / CSP / 静态缓存）。抄一份就多一处漂移面；漂移的症状恰好是「生产漏了 HSTS/限流」
   —— 静默、不可归因。⇒ 本文件钉「仓库里**只有一份** nginx.conf，且它**不含** cytda.com」。
2. **把 migaozn.com 直接改成 cytda.com**：测试环境当场断（5 个 server_name 全不匹配）⇒
   本文件钉「缺省域名仍是 migaozn.com，且缺省分支**不跑 sed**（纯拷贝 ⇒ 逐字不变）」。

## 正确形态（本文件锁什么）

- 盘上 `nginx/nginx.conf.canonical` = 仓库原文；`nginx/nginx.conf` = 渲染产物（挂进容器）。
- 域名来源：环境变量 > `/opt/migao-deploy/.env.site` > 默认 `migaozn.com`。
- 渲染 = 纯替换 `migaozn.com` → `${MIGAO_PUBLIC_DOMAIN}` ⇒ 两边不可能只改一边。
- 域名做**字符集校验**（fail-closed）：畸形值进 sed 替换串/`server_name` 前就停住。
- 构建期 `NEXT_PUBLIC_*` 默认值由同一变量派生（缺省值与改前**逐字相同**）。

判据分两类：① 静态接线（deploy.sh 里那几行必须在）；② 渲染效果（把仓库 nginx.conf 按同一
替换规则渲染后，5 个 server_name 必须全部落在 cytda.com 域内、且不残留 migaozn.com）。
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = ROOT / "deploy" / "swas" / "deploy.sh"
NGINX_CONF = ROOT / "deploy" / "swas" / "nginx.conf"

PROD_DOMAIN = "cytda.com"
TEST_DOMAIN = "migaozn.com"

# 生产必须覆盖的 6 个名字（apex + www + 4 个子域）
EXPECTED_PROD_SERVER_NAMES = {
    "cytda.com",
    "www.cytda.com",
    "api.cytda.com",
    "ai-api.cytda.com",
    "merchant.cytda.com",
    "app.cytda.com",
}


def read_deploy_sh() -> str:
    return DEPLOY_SH.read_text(encoding="utf-8")


def read_nginx_conf() -> str:
    return NGINX_CONF.read_text(encoding="utf-8")


def render_prod(conf: str) -> str:
    """与 deploy.sh 里那条 sed **同一规则**：全局替换 `migaozn.com` → `cytda.com`。"""
    return conf.replace(TEST_DOMAIN, PROD_DOMAIN)


def judge_single_source(conf: str) -> list[str]:
    """① 仓库里只有一份 nginx.conf，且它不含生产域名（防止「抄一份」的漂移修法）。"""
    v = []
    if PROD_DOMAIN in conf:
        v.append(
            f"deploy/swas/nginx.conf 里出现了 `{PROD_DOMAIN}` —— 生产域名必须靠渲染注入，"
            "不能在 canonical 配置里硬编码（否则测试环境会被带着指向生产域名）"
        )
    return v


def judge_deploy_sh_wiring(text: str) -> list[str]:
    """② deploy.sh 的接线：域名来源、默认值、校验、canonical 落盘、渲染、构建参数派生。"""
    v = []
    if "MIGAO_PUBLIC_DOMAIN=${MIGAO_PUBLIC_DOMAIN:-migaozn.com}" not in text:
        v.append(
            "deploy.sh 缺 `MIGAO_PUBLIC_DOMAIN=${MIGAO_PUBLIC_DOMAIN:-migaozn.com}` —— "
            "缺省值必须是 migaozn.com（测试环境逐字不变的唯一依据）"
        )
    if ".env.site" not in text:
        v.append("deploy.sh 缺 `.env.site` 覆盖口（生产机靠它写 MIGAO_PUBLIC_DOMAIN=cytda.com）")
    if 'cp src/deploy/swas/nginx.conf ./nginx/nginx.conf.canonical' not in text:
        v.append("deploy.sh 没有把仓库原文落成 `nginx/nginx.conf.canonical`（渲染输入缺失）")
    if 'sed "s/migaozn\\.com/${MIGAO_PUBLIC_DOMAIN}/g" ./nginx/nginx.conf.canonical' not in text:
        v.append("deploy.sh 缺渲染那一条 sed（或规则与测试不一致）")
    if 'cp -f ./nginx/nginx.conf.canonical ./nginx/nginx.conf' not in text:
        v.append("deploy.sh 缺「缺省域名 = 纯拷贝」分支（默认路径必须与改前逐字相同）")
    if "*[!a-z0-9.-]*" not in text:
        v.append("deploy.sh 缺域名字符集校验（畸形值会进 sed 替换串 / server_name ⇒ 在 nginx -t 才炸）")
    for legacy in (
        "NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL:-https://api.migaozn.com}",
        "NEXT_PUBLIC_AI_API_BASE_URL=${NEXT_PUBLIC_AI_API_BASE_URL:-https://ai-api.migaozn.com}",
        "NEXT_PUBLIC_COOKIE_DOMAIN=${NEXT_PUBLIC_COOKIE_DOMAIN:-.migaozn.com}",
        "NEXT_PUBLIC_BMINI_H5_URL=${NEXT_PUBLIC_BMINI_H5_URL:-https://app.migaozn.com/b/}",
    ):
        if legacy in text:
            v.append(f"构建参数仍有硬编码默认值：`{legacy}`（必须由 MIGAO_PUBLIC_DOMAIN 派生）")
    if "https://api.${MIGAO_PUBLIC_DOMAIN}" not in text:
        v.append("构建参数 `NEXT_PUBLIC_API_BASE_URL` 的缺省值没有由 MIGAO_PUBLIC_DOMAIN 派生")
    if ".${MIGAO_PUBLIC_DOMAIN}" not in text:
        v.append("构建参数 `NEXT_PUBLIC_COOKIE_DOMAIN` 的缺省值没有由 MIGAO_PUBLIC_DOMAIN 派生")
    return v


def judge_rendered_server_names(conf: str) -> list[str]:
    """③ 渲染效果：6 个 server_name 行、6 个名字，全部落在 cytda.com 域内。"""
    v = []
    rendered = render_prod(conf)
    if TEST_DOMAIN in rendered:
        v.append(f"渲染后仍残留 `{TEST_DOMAIN}`（替换规则漏了不带前导点的形态？）")
    lines = [
        ln for ln in rendered.splitlines()
        if re.match(r"^\s*server_name\s+", ln)
    ]
    if len(lines) != 6:
        v.append(f"渲染后的 server_name 行数 = {len(lines)}，期望 6（:80 两个面 + :443 四个面）")
    names: set[str] = set()
    for ln in lines:
        head = ln.strip()
        if head.endswith(";"):
            head = head[:-1]
        names.update(head.split()[1:])
    if names != EXPECTED_PROD_SERVER_NAMES:
        missing = EXPECTED_PROD_SERVER_NAMES - names
        extra = names - EXPECTED_PROD_SERVER_NAMES
        v.append(
            f"渲染后的 server_name 集合不符：缺 {sorted(missing)} / 多 {sorted(extra)}"
        )
    return v


def judge_rendering_is_pure_substitution(conf: str) -> list[str]:
    """④ 渲染只能是替换：除 `migaozn.com`→`cytda.com` 外，逐行不得有任何差异。"""
    v = []
    rendered = render_prod(conf)
    expected = conf.replace(TEST_DOMAIN, PROD_DOMAIN)
    if rendered != expected:
        v.append("渲染结果与「纯替换」不一致（说明渲染引入了替换之外的改写）")
    if rendered.count("\n") != conf.count("\n"):
        v.append("渲染改变了行数（不该发生）")
    return v


def test_repo_has_single_nginx_source() -> None:
    assert judge_single_source(read_nginx_conf()) == []


def test_deploy_sh_wires_domain_parameterization() -> None:
    assert judge_deploy_sh_wiring(read_deploy_sh()) == []


def test_default_domain_is_still_test_domain() -> None:
    text = read_deploy_sh()
    assert ":-migaozn.com}" in text, "缺省域名被改掉了 ⇒ 测试环境会被带着指向生产域名"
    assigned = [
        ln.strip() for ln in text.splitlines()
        if ln.strip().startswith("MIGAO_PUBLIC_DOMAIN=") and not ln.strip().startswith("#")
    ]
    assert all("cytda.com" not in ln for ln in assigned), (
        f"deploy.sh 里出现了硬编码的生产域名赋值：{assigned} —— 生产域名只能来自 .env.site/环境变量"
    )


def test_rendered_server_names_cover_prod_domains() -> None:
    assert judge_rendered_server_names(read_nginx_conf()) == []


def test_rendering_is_pure_substitution() -> None:
    assert judge_rendering_is_pure_substitution(read_nginx_conf()) == []


# ── ⑤ admin-web 的**构建期**域名接线（issue #8941）─────────────────────────────
#
# 病根（本段要防的形态）：只把域名参数化进前端源码 = **假交付**。`NEXT_PUBLIC_*` 是**构建期
# 文本替换**：生产构建必须真的收到 `NEXT_PUBLIC_SITE_DOMAIN=cytda.com`，否则产物里的商家登录
# 跳转 / canonical / sitemap 仍是缺省测试域 —— 而构建、部署、页面全绿，只有用户被送去别的站。
#
# 三处必须**同源**，缺一处就断链：
#   ① `deploy/swas/deploy.sh` 把它作为 `--build-arg` 透传，缺省值由 `MIGAO_PUBLIC_DOMAIN` 派生；
#   ② `frontend/admin-web/Dockerfile` 声明 `ARG`（否则 `--build-arg` 无处落地、docker 静默忽略）；
#   ③ `Dockerfile` 再 `ENV` 透传（缺省值 = 测试域 ⇒ 缺省域名下产物与改前逐字相同）。
FE_SITE_DOMAIN_VAR = "NEXT_PUBLIC_SITE_DOMAIN"
ADMIN_WEB_DOCKERFILE = ROOT / "frontend" / "admin-web" / "Dockerfile"
#: 期望的透传形态：缺省值由**同一个** `MIGAO_PUBLIC_DOMAIN` 派生（缺省域名下 = migaozn.com）
FE_SITE_DOMAIN_BUILD_ARG = (
    f'--build-arg "{FE_SITE_DOMAIN_VAR}=${{{FE_SITE_DOMAIN_VAR}:-${{MIGAO_PUBLIC_DOMAIN}}}}"'
)
#: 期望的 deploy.sh 整行（红证按同一字面量删/改，避免「变异没落上」的空跑）
FE_SITE_DOMAIN_BUILD_ARG_LINE = f"    _build_args+=({FE_SITE_DOMAIN_BUILD_ARG})"


def read_admin_web_dockerfile() -> str:
    return ADMIN_WEB_DOCKERFILE.read_text(encoding="utf-8")


def judge_admin_web_site_domain_wiring(deploy: str, dockerfile: str) -> list[str]:
    """⑤ deploy.sh 透传 + Dockerfile ARG/ENV 三处同源（任一处缺失 ⇒ 生产构建拿不到域名）。"""
    v: list[str] = []
    # ① deploy.sh 的透传：缺省值必须由 MIGAO_PUBLIC_DOMAIN 派生（缺省域名下逐字 = migaozn.com）
    if FE_SITE_DOMAIN_BUILD_ARG not in deploy:
        v.append(
            f"deploy.sh 没有透传 `{FE_SITE_DOMAIN_BUILD_ARG}` —— "
            f"生产构建收不到站点域名，前端参数化变成假交付（产物里仍是 {TEST_DOMAIN}）"
        )
    # ② Dockerfile 的 ARG 缺省值 = 测试域（与 deploy.sh 的有效默认值同源；两处都在就必须一致）
    m = re.search(rf"^ARG {re.escape(FE_SITE_DOMAIN_VAR)}=(\S+)$", dockerfile, re.M)
    if not m:
        v.append(
            f"frontend/admin-web/Dockerfile 缺 `ARG {FE_SITE_DOMAIN_VAR}=…` —— "
            "`--build-arg` 没有落点（docker 对未声明的 build-arg 静默忽略）"
        )
    elif m.group(1) != TEST_DOMAIN:
        v.append(
            f"Dockerfile 的 `ARG {FE_SITE_DOMAIN_VAR}` 缺省值 {m.group(1)!r} 不是 {TEST_DOMAIN!r} —— "
            "缺省域名下产物会与改前不同（测试环境在跑，不许有行为变化）"
        )
    # ③ Dockerfile 的 ENV 透传（ARG 只进 RUN 的 shell；`next start` 与构建脚本读的是 ENV）
    if not re.search(rf"^ENV {re.escape(FE_SITE_DOMAIN_VAR)}=\$\{{{re.escape(FE_SITE_DOMAIN_VAR)}\}}$", dockerfile, re.M):
        v.append(
            f"Dockerfile 缺 `ENV {FE_SITE_DOMAIN_VAR}=${{{FE_SITE_DOMAIN_VAR}}}` —— "
            "只声明 ARG 不会把它变成构建进程可见的环境变量"
        )
    return v


def test_admin_web_site_domain_is_wired_into_the_server_side_build() -> None:
    assert judge_admin_web_site_domain_wiring(read_deploy_sh(), read_admin_web_dockerfile()) == []


def test_admin_web_site_domain_default_follows_the_domain_source() -> None:
    """缺省值必须**派生自** MIGAO_PUBLIC_DOMAIN（不是另写一个测试域字面量）。"""
    m = re.search(
        rf'--build-arg "{re.escape(FE_SITE_DOMAIN_VAR)}=\$\{{{re.escape(FE_SITE_DOMAIN_VAR)}:-'
        rf'(\$\{{MIGAO_PUBLIC_DOMAIN\}})\}}"',
        read_deploy_sh(),
    )
    expr = m.group(1) if m else ""
    assert expr == "${MIGAO_PUBLIC_DOMAIN}", (
        f"{FE_SITE_DOMAIN_VAR} 的缺省值表达式是 {expr!r}，不是由 `${{MIGAO_PUBLIC_DOMAIN}}` 派生 —— "
        "两处域名来源会各自漂移"
    )
    assert expr.replace("${MIGAO_PUBLIC_DOMAIN}", TEST_DOMAIN) == TEST_DOMAIN


# ── 反空跑（红证）：把正确形态做坏一处，判据必须变红 ───────────────────────────
def test_red_proof_single_source() -> None:
    """把 cytda.com 硬编码进 canonical nginx.conf ⇒ ① 必须红。"""
    poisoned = read_nginx_conf() + "\n# cytda.com\n"
    assert judge_single_source(poisoned) != []


def test_red_proof_missing_canonical_copy() -> None:
    """删掉 canonical 落盘那行 ⇒ ② 必须红。"""
    broken = read_deploy_sh().replace(
        "cp src/deploy/swas/nginx.conf ./nginx/nginx.conf.canonical", ""
    )
    assert judge_deploy_sh_wiring(broken) != []


def test_red_proof_hardcoded_build_default() -> None:
    """把构建参数默认值改回硬编码 migaozn.com ⇒ ② 必须红。"""
    broken = read_deploy_sh().replace(
        "https://api.${MIGAO_PUBLIC_DOMAIN}", "https://api.migaozn.com"
    )
    assert judge_deploy_sh_wiring(broken) != []


def test_red_proof_wrong_rendering_rule() -> None:
    """渲染规则换成正则吞掉 `merchant.` ⇒ ③ 必须红（集合不符）。"""
    broken = read_nginx_conf().replace(
        "server_name migaozn.com www.migaozn.com merchant.migaozn.com;",
        "server_name migaozn.com www.migaozn.com;",
    )
    assert judge_rendered_server_names(broken) != []


def test_red_proof_site_domain_build_arg_missing() -> None:
    """删掉 `NEXT_PUBLIC_SITE_DOMAIN` 的透传行 ⇒ ⑤ 必须红（生产构建拿不到域名）。"""
    deploy = read_deploy_sh()
    broken = deploy.replace(FE_SITE_DOMAIN_BUILD_ARG_LINE, "")
    assert broken != deploy, "前提：变异必须真的落上（否则这条红证是空跑）"
    assert judge_admin_web_site_domain_wiring(broken, read_admin_web_dockerfile()) != []


def test_red_proof_site_domain_default_hardcoded() -> None:
    """把缺省值从 `MIGAO_PUBLIC_DOMAIN` 派生改回硬编码测试域 ⇒ ⑤ 必须红。"""
    deploy = read_deploy_sh()
    broken = deploy.replace(
        f"{FE_SITE_DOMAIN_VAR}:-${{MIGAO_PUBLIC_DOMAIN}}",
        f"{FE_SITE_DOMAIN_VAR}:-{TEST_DOMAIN}",
    )
    assert broken != deploy, "前提：变异必须真的落上"
    assert judge_admin_web_site_domain_wiring(broken, read_admin_web_dockerfile()) != []


def test_red_proof_dockerfile_env_missing() -> None:
    """删掉 Dockerfile 的 ENV 透传 ⇒ ⑤ 必须红（ARG 不会成为构建进程可见的环境变量）。"""
    dockerfile = read_admin_web_dockerfile()
    broken = dockerfile.replace(f"ENV {FE_SITE_DOMAIN_VAR}=${{{FE_SITE_DOMAIN_VAR}}}\n", "")
    assert broken != dockerfile, "前提：变异必须真的落上"
    assert judge_admin_web_site_domain_wiring(read_deploy_sh(), broken) != []


# ══════════════════════════════════════════════════════════════════════════════
# ⑥⑦⑧ 生产域名的**三道 fail-closed 闸门**（issue #8966 · 2026-11-21 生产事故）
#
# 病根（证据逐字见 issue #8966）：生产机上的 `/opt/migao-deploy/deploy.sh` 是 **11-18 旧版**
# （`grep -c env.site` = 0 / `grep -c NEXT_PUBLIC_SITE_DOMAIN` = 0），而第 1 段只同步
# compose / nginx，**不同步 deploy.sh 自己** ⇒ 用它部署一次 admin-web：
#   ① nginx 被渲染回 canonical 原文（`server_name migaozn.com …`，**0 处** cytda）⇒ 所有
#      `*.cytda.com` 落到 default server 被代理到 API ⇒ **全站 401**；
#   ② 镜像少一个 build-arg ⇒ 首页 / sitemap / robots 全指向测试域。
# 两处**全程零报错**：日志只有一行「站点域名：migaozn.com」——那行打的是**期望值**，不是盘上内容。
#
# 本段不写文本包含判据：把**真** `deploy.sh` 里的三个区块（`# >>> name` … `# <<< name`）抠出来
# **真跑**，用桩 `docker` / 桩盘面观察行为；每条都配**注入式红证**（先自证变异落上，再断言判红）。
# ══════════════════════════════════════════════════════════════════════════════
SELFSYNC_GATE = "deploy-selfsync"
RENDER_GATE = "nginx-domain-assert"
IMAGE_GATE = "image-domain-guard"

#: 夹具：`src/`（= target ref 的仓库树）里的「新版」与盘上的「11-18 旧版」
NEW_SELF_SCRIPT = (
    "#!/bin/bash\n"
    "# target ref 同源（新版：读 .env.site + 透传 NEXT_PUBLIC_SITE_DOMAIN）\n"
    "set -euo pipefail\necho new-script\n"
)
OLD_SELF_SCRIPT = (
    "#!/bin/bash\n"
    "# 11-18 旧版（没有 .env.site、没有 NEXT_PUBLIC_SITE_DOMAIN）\n"
    "echo old-script\n"
)


def _region(name: str, text: str | None = None) -> str:
    """从**真** `deploy.sh` 抠出 `# >>> name` … `# <<< name` 之间的文本（判真文本，不手写）。"""
    src = read_deploy_sh() if text is None else text
    start_tok = f"# >>> {name}\n"
    end_tok = f"# <<< {name}\n"
    assert src.count(start_tok) == 1, f"锚点 {start_tok!r} 不唯一或不存在（判据已过期）"
    start = src.index(start_tok) + len(start_tok)
    end = src.index(end_tok, start)
    body = src[start:end]
    assert body.strip(), f"区块 {name} 是空的（抠出来的东西不可判）"
    return body


def _run_region(tmp_path: Path, work: Path, body: str, prelude: str = "",
                env_extra: dict[str, str] | None = None):
    """把抠出来的**真**文本放进最小外壳里 `bash` 真跑（`set -euo pipefail` 与部署脚本同口径）。"""
    script = work / "harness.sh"
    script.write_text(
        "#!/bin/bash\nset -euo pipefail\n" + prelude + "\n" + body, encoding="utf-8"
    )
    tmpdir = tmp_path / "tmpdir"
    tmpdir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TMPDIR": str(tmpdir), **(env_extra or {})}
    return subprocess.run(["bash", str(script)], cwd=str(work), env=env,
                          capture_output=True, text=True, timeout=120)


def _sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


# ── ⑥ deploy.sh **自同步**（盘上脚本随 target ref 走）───────────────────────────
def _selfsync_fixture(tmp_path: Path, *, src_present: bool = True) -> tuple[Path, Path]:
    work = tmp_path / "opt"
    src_dir = work / "src" / "deploy" / "swas"
    src_dir.mkdir(parents=True)
    if src_present:
        (src_dir / "deploy.sh").write_text(NEW_SELF_SCRIPT, encoding="utf-8")
    target = work / "deploy.sh"
    target.write_text(OLD_SELF_SCRIPT, encoding="utf-8")
    target.chmod(0o755)
    return work, target


def _run_selfsync(tmp_path: Path, work: Path, body: str | None = None,
                  env_extra: dict[str, str] | None = None):
    return _run_region(
        tmp_path, work, _region(SELFSYNC_GATE) if body is None else body,
        'CONFIG_REF_RESOLVED="sha-bb174db"\n', env_extra=env_extra,
    )


def _backups(work: Path) -> list[Path]:
    return sorted(work.glob("deploy.sh.bak-*"))


def judge_selfsync(proc, work: Path, target: Path, inode_before: int) -> list[str]:
    """自同步契约（正常形态 = 空清单；任何一条坏掉 ⇒ 非空，测试当场红）。"""
    v: list[str] = []
    if target.read_text(encoding="utf-8") != NEW_SELF_SCRIPT:
        v.append("盘上 deploy.sh 没有被覆盖成 `src/` 里那份（盘上版本不随 target ref 走）")
    backups = _backups(work)
    if len(backups) != 1:
        v.append(f"备份文件数量 = {len(backups)}，期望 1（{backups}）")
    elif backups[0].read_text(encoding="utf-8") != OLD_SELF_SCRIPT:
        v.append("备份里不是旧版内容（备份等于没做）")
    if target.stat().st_ino != inode_before:
        v.append("覆盖换了 inode（必须「临时文件 + `cat >` 原地写」，`mv` 会换 inode）")
    if not os.access(target, os.X_OK):
        v.append("覆盖后可执行位丢了（盘上脚本下次跑不起来）")
    if proc.returncode == 0:
        v.append("覆盖后没有当场停住（bash 按字节偏移续读，继续执行会读到错位脚本）")
    return v


def test_selfsync_installs_the_ref_script_and_keeps_a_backup(tmp_path) -> None:
    """`src/` 里是新版、盘上是旧版 ⇒ 盘上被覆盖 + 留一份旧版备份 + 打印两侧 sha256 前 8 位。"""
    work, target = _selfsync_fixture(tmp_path)
    inode_before = target.stat().st_ino
    proc = _run_selfsync(tmp_path, work)
    assert judge_selfsync(proc, work, target, inode_before) == [], (
        "自同步契约未满足：\n" + (proc.stdout + proc.stderr)
    )
    out = proc.stdout
    assert _sha8(OLD_SELF_SCRIPT) in out, f"没打印盘上旧版的 sha256 前 8 位：\n{out}"
    assert _sha8(NEW_SELF_SCRIPT) in out, f"没打印 src/ 新版的 sha256 前 8 位：\n{out}"


def test_selfsync_is_idempotent(tmp_path) -> None:
    """同内容再跑一次 ⇒ 不覆盖、不备份、不产生新文件（连跑两次盘面逐字节一致）。"""
    work, target = _selfsync_fixture(tmp_path)
    first = _run_selfsync(tmp_path, work)
    assert first.returncode != 0, "第一次（旧版 → 新版）必须停住"
    content_after_first = target.read_text(encoding="utf-8")
    inode_after_first = target.stat().st_ino
    backups_after_first = _backups(work)
    second = _run_selfsync(tmp_path, work)
    assert second.returncode == 0, f"同内容第二次不幂等（rc={second.returncode}）：\n{second.stdout}{second.stderr}"
    assert target.read_text(encoding="utf-8") == content_after_first, "第二次改动了盘上脚本"
    assert target.stat().st_ino == inode_after_first, "第二次换了 inode"
    assert _backups(work) == backups_after_first, f"第二次又产生了备份：{_backups(work)}"
    assert not list((tmp_path / "tmpdir").iterdir()), "第二次留下了临时文件"
    assert "同源" in second.stdout and "不覆盖、不备份" in second.stdout, second.stdout


def test_selfsync_skips_audibly_when_src_is_absent(tmp_path) -> None:
    """配置复用场景（盘上没有 `src/`）⇒ **出声跳过**、盘上脚本不动、不失败。"""
    work, target = _selfsync_fixture(tmp_path, src_present=False)
    inode_before = target.stat().st_ino
    proc = _run_selfsync(tmp_path, work)
    assert proc.returncode == 0, f"缺 src/ 时不该失败：\n{proc.stdout}{proc.stderr}"
    assert "跳过 deploy.sh 自同步" in proc.stdout, f"跳过必须出声：\n{proc.stdout}"
    assert target.read_text(encoding="utf-8") == OLD_SELF_SCRIPT, "缺 src/ 时竟改了盘上脚本"
    assert target.stat().st_ino == inode_before
    assert _backups(work) == [], "缺 src/ 时不该产生备份"


def test_red_proof_selfsync_without_backup(tmp_path) -> None:
    """红证①：把备份那行删掉 ⇒ 同一桩输入下必须判红（备份判据有判别力）。"""
    body = _region(SELFSYNC_GATE)
    broken = body.replace('cp -p "$MIGAO_DEPLOY_SELF" "$_self_bak"', ":")
    assert broken != body, "前提：变异必须真的落上"
    work, target = _selfsync_fixture(tmp_path)
    inode_before = target.stat().st_ino
    proc = _run_selfsync(tmp_path, work, body=broken)
    assert judge_selfsync(proc, work, target, inode_before) != [], "删掉备份后判据没红（判据无判别力）"


def test_red_proof_selfsync_using_mv_breaks_inode(tmp_path) -> None:
    """红证②：把原地 `cat >` 换成 `mv` ⇒ inode 变了 ⇒ 必须判红（保 inode 是可断言的）。"""
    body = _region(SELFSYNC_GATE)
    broken = body.replace('    cat "$_self_tmp" > "$MIGAO_DEPLOY_SELF"',
                          '    mv -f "$_self_tmp" "$MIGAO_DEPLOY_SELF"')
    assert broken != body, "前提：变异必须真的落上"
    work, target = _selfsync_fixture(tmp_path)
    inode_before = target.stat().st_ino
    proc = _run_selfsync(tmp_path, work, body=broken)
    assert target.stat().st_ino != inode_before, "前提：`mv` 必须真的换了 inode"
    v = judge_selfsync(proc, work, target, inode_before)
    assert any("inode" in item for item in v), f"换了 inode 却判不出：{v}"


def test_red_proof_selfsync_continues_after_overwrite(tmp_path) -> None:
    """红证③：覆盖后**不停住**（把 exit 删掉）⇒ 必须判红（那就是「半截执行」的形态）。"""
    body = _region(SELFSYNC_GATE)
    broken = body.replace("\n    exit 1\n", "\n    :\n")
    assert broken != body, "前提：变异必须真的落上"
    work, target = _selfsync_fixture(tmp_path)
    inode_before = target.stat().st_ino
    proc = _run_selfsync(tmp_path, work, body=broken)
    assert proc.returncode == 0, "前提：删掉 exit 后应当继续跑下去"
    assert judge_selfsync(proc, work, target, inode_before) != [], "覆盖后继续执行却判不出（判据无判别力）"


# ── ⑦ 渲染后 fail-closed 断言（`server_name` 必须含站点域名）─────────────────────
def _run_render_gate(tmp_path: Path, *, conf_text: str, domain: str, body: str | None = None):
    work = tmp_path / "opt"
    (work / "nginx").mkdir(parents=True)
    (work / "nginx" / "nginx.conf").write_text(conf_text, encoding="utf-8")
    proc = _run_region(
        tmp_path, work, _region(RENDER_GATE) if body is None else body,
        f'MIGAO_PUBLIC_DOMAIN="{domain}"\nCONFIG_REF_RESOLVED="sha-bb174db"\n',
    )
    return proc, proc.stdout + proc.stderr


def judge_render_gate(proc, out: str) -> list[str]:
    """渲染断言的契约：0 处站点域名 ⇒ 非零退出 + 可归因（清单）+ 可行动（中止部署）。"""
    v: list[str] = []
    if proc.returncode == 0:
        v.append("`server_name` 里 0 处站点域名，脚本却 exit 0（「只打一行就继续」的静默失效点回来了）")
    if "server_name" not in out:
        v.append("判红时没有打印当前 server_name 清单（不可归因）")
    if "中止部署" not in out:
        v.append("判红时没有可行动的出口（中止部署）")
    return v


def test_render_gate_passes_when_rendered_server_names_carry_the_site_domain(tmp_path) -> None:
    """正确形态：按同一替换规则渲染成 cytda ⇒ 断言通过（不许把正常部署判红）。"""
    proc, out = _run_render_gate(tmp_path, conf_text=render_prod(read_nginx_conf()), domain=PROD_DOMAIN)
    assert proc.returncode == 0, out
    assert "✅ nginx.conf 自证" in out, out


def test_render_gate_goes_red_when_rendered_config_reverts_to_the_test_domain(tmp_path) -> None:
    """注入：站点域名 = cytda，而盘上渲染产物仍全是 migaozn（旧脚本「纯 cp canonical」分支）⇒ 必须红。"""
    stale = read_nginx_conf()
    assert f"server_name {TEST_DOMAIN}" in stale, "前提：桩盘面必须真的还在测试域（否则这条是空跑）"
    proc, out = _run_render_gate(tmp_path, conf_text=stale, domain=PROD_DOMAIN)
    assert judge_render_gate(proc, out) == [], out


def test_red_proof_render_gate_without_exit(tmp_path) -> None:
    """红证：把断言里的 `exit 1` 删掉（= 改前「只打印一行就继续」）⇒ 同一桩输入必须判红。"""
    body = _region(RENDER_GATE)
    broken = body.replace("\n  exit 1\n", "\n  :\n")
    assert broken != body, "前提：变异必须真的落上"
    proc, out = _run_render_gate(tmp_path, conf_text=read_nginx_conf(), domain=PROD_DOMAIN, body=broken)
    assert judge_render_gate(proc, out) != [], "没了 exit 竟还是判红（判据的判别力来路不明）"


# ── ⑧ 构建后产物断言（产物不得含测试域）─────────────────────────────────────
STUB_DOCKER_SH = r"""#!/bin/bash
printf '%s\n' "$*" >>"${STUB_DOCKER_LOG:-/dev/null}"
case "$1" in
  create) echo "cid-stub-1"; exit 0 ;;
  cp)
    if [ "${STUB_CP_MISSING:-0}" = "1" ]; then exit 1; fi
    _src=${2#*:}
    cp "${STUB_ARTIFACT}" "${3%/}/$(basename "$_src")" || exit 1
    exit 0 ;;
  *) exit 0 ;;
esac
"""


def _run_image_gate(tmp_path: Path, *, artifact_text: str, domain: str,
                    cp_missing: bool = False, body: str | None = None):
    work = tmp_path / "opt"
    work.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "docker"
    stub.write_text(STUB_DOCKER_SH, encoding="utf-8")
    stub.chmod(0o755)
    artifact = tmp_path / "artifact.body"
    artifact.write_text(artifact_text, encoding="utf-8")
    prelude = (
        '_svc="admin-web"\n'
        'LOCAL_IMAGE_REF="acr.example.com/ns/admin-web:sha-bb174db"\n'
        'TAG="sha-bb174db"\n'
        f'MIGAO_PUBLIC_DOMAIN="{domain}"\n'
    )
    proc = _run_region(
        tmp_path, work, _region(IMAGE_GATE) if body is None else body, prelude,
        env_extra={
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "STUB_ARTIFACT": str(artifact),
            "STUB_CP_MISSING": "1" if cp_missing else "0",
            "STUB_DOCKER_LOG": str(tmp_path / "docker.log"),
        },
    )
    return proc, proc.stdout + proc.stderr


def judge_image_gate(proc, out: str) -> list[str]:
    v: list[str] = []
    if proc.returncode == 0:
        v.append("产物含测试域 migaozn.com，脚本却 exit 0（域名被烤进产物的静默形态回来了）")
    if "migaozn.com" not in out:
        v.append("判红时没有点名命中的测试域（不可归因）")
    if "中止部署" not in out:
        v.append("判红时没有可行动的出口（中止部署）")
    return v


def test_image_gate_goes_red_when_the_built_artifact_carries_the_test_domain(tmp_path) -> None:
    """注入：站点域名 = cytda，而产物（sitemap）里仍是 migaozn ⇒ 部署必须失败。"""
    poisoned = f"<url><loc>https://www.{TEST_DOMAIN}/</loc></url>"
    assert TEST_DOMAIN in poisoned, "前提：夹具必须真的含测试域（否则这条是空跑）"
    proc, out = _run_image_gate(tmp_path, artifact_text=poisoned, domain=PROD_DOMAIN)
    assert judge_image_gate(proc, out) == [], out


def test_image_gate_passes_when_the_artifact_is_clean(tmp_path) -> None:
    """正确形态：产物里全是 cytda ⇒ 通过（不许把正常构建判红）。"""
    clean = f"<url><loc>https://www.{PROD_DOMAIN}/</loc></url>"
    proc, out = _run_image_gate(tmp_path, artifact_text=clean, domain=PROD_DOMAIN)
    assert proc.returncode == 0, out
    assert "✅ 产物自证" in out, out


def test_image_gate_is_unjudgeable_when_the_artifact_cannot_be_read(tmp_path) -> None:
    """取不到产物 ⇒ **不可判定**：打印 SKIPPED、不判红，但也**绝不许判绿**。"""
    proc, out = _run_image_gate(tmp_path, artifact_text=f"<loc>https://www.{TEST_DOMAIN}/</loc>",
                                domain=PROD_DOMAIN, cp_missing=True)
    assert proc.returncode == 0, f"不可判定不该判红：\n{out}"
    assert "SKIPPED" in out and "不可判定" in out, f"不可判定必须出声：\n{out}"
    assert "✅ 产物自证" not in out, f"取不到产物却判绿了（假绿）：\n{out}"


def test_image_gate_is_inactive_on_the_test_domain(tmp_path) -> None:
    """缺省域名（测试环境）下本闸门不参与：产物含 migaozn 是**正常**的（与改前逐字相同）。"""
    proc, out = _run_image_gate(tmp_path, artifact_text=f"<loc>https://www.{TEST_DOMAIN}/</loc>",
                                domain=TEST_DOMAIN)
    assert proc.returncode == 0, out
    assert "SKIPPED" not in out and "✅ 产物自证" not in out, f"测试域下不该介入：\n{out}"


def test_red_proof_image_gate_blinded(tmp_path) -> None:
    """红证：把命中判据改成恒假（闸门变瞎）⇒ 同一份污染产物必须判红。"""
    body = _region(IMAGE_GATE)
    broken = body.replace("if grep -qF 'migaozn.com' \"$_guard_file\"; then", "if false; then")
    assert broken != body, "前提：变异必须真的落上"
    proc, out = _run_image_gate(tmp_path, artifact_text=f"<loc>https://www.{TEST_DOMAIN}/</loc>",
                                domain=PROD_DOMAIN, body=broken)
    assert judge_image_gate(proc, out) != [], "闸门变瞎却仍判红（判据的判别力来路不明）"


# ── 三道闸门的**落位顺序**（顺序错了闸门就是空转）──────────────────────────────
def judge_gate_order(text: str) -> list[str]:
    v: list[str] = []
    try:
        selfsync = text.index(f"# >>> {SELFSYNC_GATE}")
        render = text.index(f"# >>> {RENDER_GATE}")
        image = text.index(f"# >>> {IMAGE_GATE}")
    except ValueError:
        return ["三道闸门的锚点不全（判据已过期）"]
    if [selfsync, render, image] != sorted([selfsync, render, image]):
        v.append("闸门顺序不对：必须是 自同步 → 渲染断言 → 构建断言")
    if selfsync > text.index('echo "  站点域名：'):
        v.append("自同步落在渲染之后 ⇒ 本次仍由旧逻辑渲染（闸门空转）")
    if render < text.index('echo "  站点域名：'):
        v.append("渲染断言落在渲染之前 ⇒ 断言的是上一轮/不存在的产物")
    if image < text.index('if timeout "$BUILD_TIMEOUT_SECS" docker build'):
        v.append("产物断言落在构建之前 ⇒ 断言的是上一轮的镜像")
    return v


def test_the_three_gates_are_placed_in_the_only_order_that_can_work() -> None:
    assert judge_gate_order(read_deploy_sh()) == []


def test_red_proof_gate_order() -> None:
    """红证：把渲染断言的锚点挪到**渲染之前** ⇒ 顺序判据必须红。"""
    text = read_deploy_sh()
    marker = f"# >>> {RENDER_GATE}\n"
    anchor = 'if [ "$MIGAO_PUBLIC_DOMAIN" = "migaozn.com" ]; then'
    broken = text.replace(marker, "", 1).replace(anchor, marker + anchor, 1)
    assert broken != text, "前提：变异必须真的落上"
    assert broken.index(marker) < broken.index('echo "  站点域名：'), "前提：变异后锚点必须在渲染之前"
    assert judge_gate_order(broken) != []

