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

import re
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
