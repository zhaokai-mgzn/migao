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
