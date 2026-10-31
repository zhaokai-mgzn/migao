# case_ids: MC-121
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/部署结构类 L0 不变式挂在 misc 域的 MC-* 用例上；
#   本单新增 MC-121「四域共用证书的自动续期 + 到期判红 + 一次性兜底」，见 .github/cases/misc.yml。）
r"""TLS 证书到期判红 / 续期 / cron 加固的常驻判据（issue #8201，P0）。

## 病（主会话在服务器上核实到的读数，2026-10-31）

四个域名（`api` / `ai-api` / `app` / `migaozn.com`）共用**同一张** Let's Encrypt 证书
（`CN=migaozn.com`，`notAfter=Nov 27 10:29:18 2026 GMT`，SAN 含 admin/ai-api/api/app/merchant/migaozn/ops/www）。
「仓内无续期机制」只是**一半**真话 —— **宿主有 cron**，但它每天在失败：

```
0 3 * * * certbot renew --quiet --webroot -w /opt/migao-deploy/certbot-www \
  --post-hook 'cd /opt/migao-deploy && docker compose restart nginx >/dev/null 2>&1' \
  >> /var/log/certbot-renew.log 2>&1
```

三条失败原因（逐条都在本文件里有承载体）：
① 主证书 `migao` 的 HTTP-01 必失败 —— SAN 里的 `admin.migaozn.com` **没有 A 记录**；
② 陈旧 lineage `api.migaozn.com` 的 renewal conf 是 `authenticator=manual` + `pref_challs=dns-01`，
   与 cron 全局的 `--webroot` 冲突 ⇒ 每天一条 `None of the preferred challenges are supported`；
③ 失败**没有任何告警**（日志里的红字没人看），而 `--post-hook` 用的是 `restart nginx`（整断，不是 reload）。

## 判据面（每条都带会红的注入）

| # | 判据 | 红证 |
|---|---|---|
| 1 | `deploy/scripts/tls-expiry-check.sh` 正常态 ⇒ 0，且输出四域的 notAfter / 剩余天数 / 复算命令 | 阈值判定被写成恒真 ⇒ 必红（见 2/3） |
| 2 | 临期（<21 天）⇒ **1**；过期 ⇒ **1** | 把阈值比较删掉 / 方向写反 ⇒ 必红 |
| 3 | 取不到 / 解析不了 ⇒ **3**（不可判定**不得当 0**） | 退化成 0 ⇒ 必红 |
| 4 | 证书 SAN 不覆盖被查域名 ⇒ **1**（具名「不匹配」） | 摘掉 SAN 校验 ⇒ 必红 |
| 5 | `certbot certificates` 的 lineage 读数：两个 lineage 都报，**nginx 未使用的要标出来**；renewal conf 与 webroot 冲突要具名 | 摘掉 used/renew_hazard 读数 ⇒ 必红 |
| 6 | `tls-renew.sh`：`--dry-run` 必须把 `--dry-run` 传给 certbot 且**不 reload**；续期成功才 reload；无到期证书 ⇒ 幂等 noop 且不 reload | 反向（失败也 reload / dry-run 就 reload）⇒ 必红 |
| 7 | `tls-renew.sh --install-cron`：幂等写 `/etc/cron.d/migao-tls-renew`；**检测到既有 `certbot renew` crontab 条目 ⇒ 不安装并出声**（避免双跑），加 `--replace-legacy-cron` 才备份+替换；日志落 file、退出码非零 | 无 guard 直接双写 ⇒ 必红 |
| 8 | 接线：`.github/workflows/post-merge-verify.yml` 的 main 侧接 `tls-expiry-check.sh`，**在 `if: failure()` 出口之前**，`exit 3` 不许归一化成 0，并指向 runbook | 摘掉该步 / 挪到出口之后 / 把 3 变 0 ⇒ 必红 |
| 9 | `deploy/swas/deploy.sh` 幂等安装宿主 cron（`--install-cron`），且**只在 `/opt/migao-deploy/tls-renew.sh` 在盘上时**才装（回滚到旧 tag 时 `src/` 里没这个文件，不许因此让部署 abort） | 无条件 `cp` ⇒ 回滚部署当场红 |

## 覆盖边界（照实登记）

- 判据**不联网**：`openssl` / `certbot` / `docker` / `crontab` 全部是 PATH 垫片 ⇒ 证的是
  「脚本在给定输入下会做什么」，**不是**「线上真的这么回」。
- 判据**不执行**真实续期 / 重签 / DNS 变更（用户边界：执行留给人工确认）。
- 「宿主 cron 真的每天跑了」只能事后看 `/var/log/migao-tls-renew.log`（runbook 的验证明细）。
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "deploy" / "scripts" / "tls-expiry-check.sh"
RENEW = REPO / "deploy" / "scripts" / "tls-renew.sh"
SWAS_DEPLOY = REPO / "deploy" / "swas" / "deploy.sh"
WORKFLOW = REPO / ".github" / "workflows" / "post-merge-verify.yml"
RUNBOOK = REPO / "docs" / "deployment" / "tls-renewal.md"
NGINX_CONF = REPO / "deploy" / "swas" / "nginx.conf"

#: 线上真读数（`openssl s_client … | openssl x509 -noout -dates`，2026-10-31 现取）。
LIVE_NOT_AFTER = "Nov 27 10:29:18 2026 GMT"
LIVE_SAN = (
    "DNS:admin.migaozn.com, DNS:ai-api.migaozn.com, DNS:api.migaozn.com, DNS:app.migaozn.com, "
    "DNS:merchant.migaozn.com, DNS:migaozn.com, DNS:ops.migaozn.com, DNS:www.migaozn.com"
)
DEFAULT_DOMAINS = ["api.migaozn.com", "ai-api.migaozn.com", "app.migaozn.com", "migaozn.com"]

#: 垫片 `openssl`：按子命令吐固定文本（被测脚本只读它的 stdout，不关心真证书）。
FAKE_OPENSSL = r"""#!/usr/bin/env bash
set -uo pipefail
sub="${1:-}"
if [ "$sub" = "s_client" ]; then
  if [ "${FAKE_SCLIENT_FAIL:-0}" = "1" ]; then
    echo "connect: Connection refused" >&2
    exit 1
  fi
  printf -- '-----BEGIN CERTIFICATE-----\nMIIBfakepem\n-----END CERTIFICATE-----\n'
  exit 0
fi
if [ "$sub" = "x509" ]; then
  for arg in "$@"; do
    case "$arg" in
      -dates)
        printf 'notBefore=Aug 29 10:29:19 2026 GMT\nnotAfter=%s\n' "${FAKE_NOT_AFTER:-}"
        exit 0
        ;;
      -ext)
        printf 'X509v3 Subject Alternative Name:\n    %s\n' "${FAKE_SAN:-}"
        exit 0
        ;;
    esac
  done
  printf 'Subject: CN = migaozn.com\nX509v3 Subject Alternative Name:\n    %s\n' "${FAKE_SAN:-}"
  exit 0
fi
exit 0
"""


def _epoch(text: str) -> int:
    return int(parsedate_to_datetime(text).timestamp())


def _now_for_days(not_after: str, days: int) -> int:
    """取一个「剩余天数恰好 = days」的 now（留 1 小时余量，避开整除边界）。"""
    return _epoch(not_after) - days * 86400 - 3600


def _write_shims(tmp_path: Path, *, extra: dict[str, str] | None = None) -> Path:
    shim = tmp_path / "shim"
    shim.mkdir(exist_ok=True)
    for name, body in {"openssl": FAKE_OPENSSL, **(extra or {})}.items():
        path = shim / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    return shim


def _env(shim: Path, tmp_path: Path, **kwargs: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{shim}:{env.get('PATH', '')}"
    env.setdefault("TLS_LE_DIR", str(tmp_path / "no-letsencrypt"))
    env.setdefault("TLS_NGINX_CONF", str(NGINX_CONF))
    for key, value in kwargs.items():
        env[key] = value
    return env


def _run_check(tmp_path: Path, *, not_after: str = LIVE_NOT_AFTER, san: str = LIVE_SAN,
               days: int | None = 60, extra_env: dict[str, str] | None = None,
               args: list[str] | None = None,
               now_epoch: int | None = None) -> subprocess.CompletedProcess:
    shim = _write_shims(tmp_path)
    env = _env(shim, tmp_path, FAKE_NOT_AFTER=not_after, FAKE_SAN=san)
    if now_epoch is not None:
        env["TLS_NOW_EPOCH"] = str(now_epoch)
    elif days is not None:
        env["TLS_NOW_EPOCH"] = str(_now_for_days(not_after, days))
    env.update(extra_env or {})
    return subprocess.run(["bash", str(CHECK), *(args or [])], env=env,
                          capture_output=True, text=True, timeout=120)


# ═══════════════════════════════════════════════════════════════════════════
# 判据 1：正常态 0 + 每个域都有 notAfter / 剩余天数 / 复算命令
# ═══════════════════════════════════════════════════════════════════════════
def test_check_script_exists_and_is_executable():
    assert CHECK.is_file(), f"缺判据本体 {CHECK.relative_to(REPO)}（issue #8201）"
    assert RENEW.is_file(), f"缺续期脚本 {RENEW.relative_to(REPO)}（issue #8201）"
    assert os.access(CHECK, os.X_OK), "tls-expiry-check.sh 必须可执行（cron / runbook 直接调用）"
    assert os.access(RENEW, os.X_OK), "tls-renew.sh 必须可执行（宿主 cron 直接调用）"


def test_green_when_ample_time_and_readings_are_actionable(tmp_path):
    proc = _run_check(tmp_path, days=60)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"剩余 60 天必须退 0（实测 rc={proc.returncode}）：\n{out}"
    for domain in DEFAULT_DOMAINS:
        assert f"domain={domain}" in out, f"输出缺 {domain} 的读数：\n{out}"
    assert "status=ok" in out, f"缺 status=ok 读数：\n{out}"
    assert "days_left=60" in out, f"剩余天数必须逐域报出（期望 60）：\n{out}"
    assert LIVE_NOT_AFTER in out, f"必须原样打印 notAfter 读数：\n{out}"
    assert "复算：" in out and "openssl s_client" in out, (
        f"每个域必须给可复制的复算命令（别只给结论）：\n{out}")
    assert "TLS_EXPIRY_SUMMARY rc=0" in out, f"缺汇总行（机读）：\n{out}"


# ═══════════════════════════════════════════════════════════════════════════
# 判据 2：临期 / 过期 ⇒ 1（阈值 21 天，边界 21 绿 / 20 红）
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("days", [20, 10, 1])
def test_expiring_certificate_is_red(tmp_path, days):
    proc = _run_check(tmp_path, days=days)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, (
        f"剩余 {days} 天 < 阈值 21 天 ⇒ 必须退 1（实测 rc={proc.returncode}）：\n{out}")
    assert "status=expiring" in out, f"必须标 status=expiring：\n{out}"
    assert "TLS_EXPIRY_SUMMARY rc=1" in out, f"汇总行必须自洽（rc=1）：\n{out}"


def test_boundary_21_days_is_green(tmp_path):
    proc = _run_check(tmp_path, days=21)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        f"剩余 21 天不算「<21 天」⇒ 必须退 0（实测 rc={proc.returncode}）：\n{out}")


def test_expired_certificate_is_red_and_named(tmp_path):
    proc = _run_check(tmp_path, days=-3)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, f"已过期 ⇒ 必须退 1（实测 rc={proc.returncode}）：\n{out}"
    assert "status=expired" in out, f"必须标 status=expired：\n{out}"
    assert "已过期" in out, f"红必须可读（不是只有一个退出码）：\n{out}"


# ═══════════════════════════════════════════════════════════════════════════
# 判据 3：取不到 / 解析不了 ⇒ 3（不可判定不得当 0）
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("case", ["unreachable", "empty_not_after", "garbage_not_after"])
def test_undecidable_is_exit_3_never_green(tmp_path, case):
    extra: dict[str, str] = {}
    not_after = LIVE_NOT_AFTER
    if case == "unreachable":
        extra = {"FAKE_SCLIENT_FAIL": "1", "TLS_LE_DIR": str(tmp_path / "none")}
    elif case == "empty_not_after":
        not_after = ""
    else:
        not_after = "definitely-not-a-date"
    proc = _run_check(tmp_path, not_after=not_after, days=None, extra_env=extra,
                      now_epoch=_now_for_days(LIVE_NOT_AFTER, 60))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, (
        f"{case}：不可判定 ⇒ 必须退 3（实测 rc={proc.returncode}）—— 3 不得当 0 读：\n{out}")
    assert "status=unknown" in out, f"必须标 status=unknown：\n{out}"
    assert "无法判定" in out, f"必须明说「无法判定」（不是静默通过）：\n{out}"
    assert "TLS_EXPIRY_SUMMARY rc=3" in out, f"汇总行必须自洽（rc=3）：\n{out}"


# ═══════════════════════════════════════════════════════════════════════════
# 判据 4：SAN 不覆盖被查域名 ⇒ 1（具名不匹配）
# ═══════════════════════════════════════════════════════════════════════════
def test_hostname_mismatch_is_red_and_named(tmp_path):
    proc = _run_check(tmp_path, days=60, san="DNS:migaozn.com, DNS:www.migaozn.com")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, (
        f"SAN 不含 api/ai-api/app ⇒ 必须退 1（实测 rc={proc.returncode}）：\n{out}")
    assert "status=mismatch" in out, f"必须标 status=mismatch：\n{out}"
    assert "不匹配" in out, f"必须具名「证书域名不匹配」：\n{out}"


def test_wildcard_san_covers_one_label_only(tmp_path):
    """`*.migaozn.com` 覆盖 `api.migaozn.com`，但**不**覆盖 `migaozn.com`（只差一级标签的语义）。"""
    proc = _run_check(tmp_path, days=60, san="DNS:*.migaozn.com")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, f"裸域不在 `*.migaozn.com` 覆盖内 ⇒ 必须退 1：\n{out}"
    assert "domain=migaozn.com status=mismatch" in out, (
        f"只有裸域该判不匹配（api/ai-api/app 应被通配符覆盖）：\n{out}")


# ═══════════════════════════════════════════════════════════════════════════
# 判据 5：`certbot certificates` 的 lineage 读数（含「未使用」标记 + renewal conf 冲突）
# ═══════════════════════════════════════════════════════════════════════════
CERTBOT_CERTIFICATES = """Saving debug log to /var/log/letsencrypt/letsencrypt.log

Found the following certs:
  Certificate Name: migao
    Serial Number: 04aa
    Key Type: RSA
    Domains: migaozn.com www.migaozn.com api.migaozn.com ai-api.migaozn.com app.migaozn.com
    Expiry Date: 2026-11-27 10:29:18+00:00 (VALID: 27 days)
    Certificate Path: /etc/letsencrypt/live/migao/fullchain.pem
    Private Key Path: /etc/letsencrypt/live/migao/privkey.pem
  Certificate Name: api.migaozn.com
    Serial Number: 05bb
    Key Type: RSA
    Domains: api.migaozn.com
    Expiry Date: 2026-11-12 08:00:00+00:00 (VALID: 12 days)
    Certificate Path: /etc/letsencrypt/live/api.migaozn.com/fullchain.pem
    Private Key Path: /etc/letsencrypt/live/api.migaozn.com/privkey.pem

"""

FAKE_CERTBOT = ("#!/usr/bin/env bash\n"
                "set -uo pipefail\n"
                'if [ "${1:-}" = "certificates" ]; then\n'
                "  cat <<'CERTEOF'\n"
                + CERTBOT_CERTIFICATES +
                "CERTEOF\n"
                "  exit 0\n"
                "fi\n"
                'if [ "${1:-}" = "renew" ]; then\n'
                "  printf '%s\\n' \"${FAKE_RENEW_OUTPUT:-No renewals were attempted.}\"\n"
                '  exit "${FAKE_RENEW_RC:-0}"\n'
                "fi\n"
                "exit 0\n")


def _lineage_fixture(tmp_path: Path) -> Path:
    le = tmp_path / "etc-letsencrypt"
    (le / "renewal").mkdir(parents=True, exist_ok=True)
    (le / "live" / "migao").mkdir(parents=True, exist_ok=True)
    (le / "live" / "api.migaozn.com").mkdir(parents=True, exist_ok=True)
    (le / "renewal" / "migao.conf").write_text(
        "[renewalparams]\nauthenticator = webroot\nwebroot_path = /opt/migao-deploy/certbot-www\n"
        "pref_challs = http-01,\n", encoding="utf-8")
    (le / "renewal" / "api.migaozn.com.conf").write_text(
        "[renewalparams]\nauthenticator = manual\npref_challs = dns-01,\n", encoding="utf-8")
    return le


def test_lineage_readings_mark_unused_and_renew_conflict(tmp_path):
    le = _lineage_fixture(tmp_path)
    shim = _write_shims(tmp_path, extra={"certbot": FAKE_CERTBOT})
    env = _env(shim, tmp_path, FAKE_NOT_AFTER=LIVE_NOT_AFTER, FAKE_SAN=LIVE_SAN,
               TLS_LE_DIR=str(le), TLS_NOW_EPOCH=str(_now_for_days(LIVE_NOT_AFTER, 27)))
    proc = subprocess.run(["bash", str(CHECK)], env=env, capture_output=True, text=True, timeout=120)
    out = proc.stdout + proc.stderr
    assert "TLS_LINEAGE name=migao" in out, f"必须逐 lineage 报读数：\n{out}"
    assert "TLS_LINEAGE name=migao" in out and "used=yes" in out, (
        f"nginx 正在用的 lineage（live/migao/fullchain.pem）必须标 used=yes：\n{out}")
    assert "TLS_LINEAGE name=api.migaozn.com" in out and "used=no" in out, (
        f"未被 nginx 使用的 lineage 必须标出来（used=no）：\n{out}")
    assert "authenticator=manual" in out or "renew_hazard=" in out, (
        f"renewal conf 与 webroot 冲突（manual + dns-01 vs --webroot）必须具名：\n{out}")
    assert "TLS_LINEAGE_SUMMARY" in out, f"缺 lineage 汇总行：\n{out}"


def test_lineage_readings_absent_off_host_are_not_silent(tmp_path):
    """CI runner 上没有 `/etc/letsencrypt` ⇒ 必须明说「未在宿主机上」，且**不**因此判 3。"""
    proc = _run_check(tmp_path, days=60, extra_env={"TLS_LE_DIR": str(tmp_path / "none")})
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"域名面全绿时不得因缺 lineage 读数判红（rc={proc.returncode}）：\n{out}"
    assert "TLS_LINEAGE_SUMMARY" in out and "skipped" in out, (
        f"缺 lineage 读数必须出声（skipped），不许静默：\n{out}")


# ═══════════════════════════════════════════════════════════════════════════
# 判据 6：tls-renew.sh 的 dry-run / 成功才 reload / 幂等 noop
# ═══════════════════════════════════════════════════════════════════════════
FAKE_DOCKER = r"""#!/usr/bin/env bash
set -uo pipefail
printf '%s\n' "docker $*" >> "${FAKE_DOCKER_LOG:?}"
if [ "${1:-}" = "compose" ]; then
  exit "${FAKE_RELOAD_RC:-0}"
fi
if [ "${1:-}" = "run" ]; then
  printf '%s\n' "${FAKE_RENEW_OUTPUT:-}"
  exit "${FAKE_RENEW_RC:-0}"
fi
exit 0
"""


def _renew_env(tmp_path: Path, *, renew_output: str, renew_rc: int = 0,
               reload_rc: int = 0, with_docker: bool = True,
               with_host_certbot: bool = False) -> tuple[dict[str, str], Path, Path]:
    le = _lineage_fixture(tmp_path)
    deploy_dir = tmp_path / "opt-migao-deploy"
    (deploy_dir / "certbot-www").mkdir(parents=True, exist_ok=True)
    extras = {"docker": FAKE_DOCKER}
    if with_host_certbot:
        extras["certbot"] = FAKE_CERTBOT
    if not with_docker:
        extras.pop("docker")
    shim = _write_shims(tmp_path, extra=extras)
    log = tmp_path / "docker.log"
    log.write_text("", encoding="utf-8")
    env = _env(shim, tmp_path, TLS_LE_DIR=str(le), MIGAO_DEPLOY_DIR=str(deploy_dir),
               FAKE_DOCKER_LOG=str(log), FAKE_RENEW_OUTPUT=renew_output,
               FAKE_RENEW_RC=str(renew_rc), FAKE_RELOAD_RC=str(reload_rc),
               TLS_CERTBOT_ENGINE="host" if with_host_certbot else "docker")
    return env, log, deploy_dir


def test_renew_dry_run_passes_dry_run_and_never_reloads(tmp_path):
    env, log, _ = _renew_env(tmp_path, renew_output="The dry run was successful.", renew_rc=0)
    proc = subprocess.run(["bash", str(RENEW), "--dry-run"], env=env,
                          capture_output=True, text=True, timeout=120)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"dry-run 成功必须退 0（rc={proc.returncode}）：\n{out}"
    assert "--dry-run" in out, f"必须把 --dry-run 传给 certbot：\n{out}"
    assert "reload" not in log.read_text(encoding="utf-8"), (
        f"dry-run 不许 reload nginx（会掩盖「没真的续上」）：\n{log.read_text(encoding='utf-8')}")
    assert "TLS_RENEW_RESULT=" in out, f"缺机读结果行：\n{out}"


def test_renew_reloads_after_success_with_exec_not_restart(tmp_path):
    env, log, _ = _renew_env(tmp_path, renew_output="Congratulations, all renewals succeeded.",
                             renew_rc=0)
    proc = subprocess.run(["bash", str(RENEW)], env=env, capture_output=True, text=True, timeout=120)
    out = proc.stdout + proc.stderr
    calls = log.read_text(encoding="utf-8")
    assert proc.returncode == 0, f"续期成功且 reload 成功 ⇒ 退 0（rc={proc.returncode}）：\n{out}\n{calls}"
    assert "nginx -s reload" in calls, f"必须用 `docker compose exec -T nginx nginx -s reload`：\n{calls}"
    assert "compose restart" not in calls, f"不许退化成 restart（整断连接）：\n{calls}"
    assert "renew" in calls and "--webroot" in calls, f"必须走 webroot 续期：\n{calls}"
    assert "TLS_RENEW_RESULT=renewed" in out, f"结果行必须区分「真的续上了」：\n{out}"


def test_renew_failure_is_red_and_never_reloads(tmp_path):
    env, log, _ = _renew_env(tmp_path, renew_output="Some challenges have failed.", renew_rc=1)
    proc = subprocess.run(["bash", str(RENEW)], env=env, capture_output=True, text=True, timeout=120)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"续期失败必须非零退出（cron 才看得见）：\n{out}"
    assert "nginx -s reload" not in log.read_text(encoding="utf-8"), (
        f"续期失败不许 reload（会把「没续上」掩盖成一次成功动作）：\n{log.read_text(encoding='utf-8')}")
    assert "失败" in out and "/var/log/migao-tls-renew.log" in out, (
        f"失败必须可归因并指出日志位置：\n{out}")


def test_renew_noop_is_idempotent_and_skips_reload(tmp_path):
    env, log, _ = _renew_env(tmp_path, renew_output="No renewals were attempted.", renew_rc=0)
    first = subprocess.run(["bash", str(RENEW)], env=env, capture_output=True, text=True, timeout=120)
    second = subprocess.run(["bash", str(RENEW)], env=env, capture_output=True, text=True, timeout=120)
    calls = log.read_text(encoding="utf-8")
    assert first.returncode == 0 and second.returncode == 0, (
        f"「没有到期证书」必须幂等退 0：{first.stdout}{first.stderr} / {second.stdout}{second.stderr}")
    assert "nginx -s reload" not in calls, f"无到期证书时不必 reload：\n{calls}"
    assert "TLS_RENEW_RESULT=noop" in first.stdout, f"结果行必须是 noop：\n{first.stdout}"


def test_renew_requires_letsencrypt_dir(tmp_path):
    env, _, _ = _renew_env(tmp_path, renew_output="", renew_rc=0)
    env["TLS_LE_DIR"] = str(tmp_path / "absent")
    proc = subprocess.run(["bash", str(RENEW)], env=env, capture_output=True, text=True, timeout=120)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, f"环境不满足（无 /etc/letsencrypt）⇒ 3（不可判定，rc={proc.returncode}）：\n{out}"
    assert "无法判定" in out or "不存在" in out, f"必须明说环境不满足：\n{out}"


# ═══════════════════════════════════════════════════════════════════════════
# 判据 7：--install-cron 幂等 + 既有 crontab 条目 guard（不双跑）+ 备份替换
# ═══════════════════════════════════════════════════════════════════════════
LEGACY_CRON = (
    "0 3 * * * certbot renew --quiet --webroot -w /opt/migao-deploy/certbot-www "
    "--post-hook 'cd /opt/migao-deploy && docker compose restart nginx >/dev/null 2>&1' "
    ">> /var/log/certbot-renew.log 2>&1"
)

FAKE_CRONTAB = r"""#!/usr/bin/env bash
set -uo pipefail
if [ "${1:-}" = "-l" ]; then
  if [ -f "${FAKE_CRONTAB_IN:?}" ]; then cat "${FAKE_CRONTAB_IN}"; fi
  exit 0
fi
if [ "${1:-}" = "-" ]; then
  cat > "${FAKE_CRONTAB_OUT:?}"
  exit 0
fi
exit 0
"""


def _cron_env(tmp_path: Path, *, legacy: bool) -> tuple[dict[str, str], Path]:
    le = _lineage_fixture(tmp_path)
    deploy_dir = tmp_path / "opt-migao-deploy"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    script = deploy_dir / "tls-renew.sh"
    script.write_text(RENEW.read_text(encoding="utf-8"), encoding="utf-8")
    shim = _write_shims(tmp_path, extra={"crontab": FAKE_CRONTAB, "openssl": FAKE_OPENSSL})
    crontab_in = tmp_path / "crontab.in"
    crontab_in.write_text(("%s\n" % LEGACY_CRON) if legacy else "", encoding="utf-8")
    out = tmp_path / "crontab.out"
    out.write_text("", encoding="utf-8")
    cron_file = tmp_path / "etc-cron.d" / "migao-tls-renew"
    cron_file.parent.mkdir(parents=True, exist_ok=True)
    log_file = tmp_path / "var-log" / "migao-tls-renew.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    env = _env(shim, tmp_path, TLS_LE_DIR=str(le), MIGAO_DEPLOY_DIR=str(deploy_dir),
               MIGAO_TLS_ASSUME_ROOT="1", MIGAO_TLS_CRON_FILE=str(cron_file),
               MIGAO_TLS_LOG_FILE=str(log_file),
               MIGAO_TLS_RENEW_SCRIPT=str(script),
               MIGAO_TLS_BACKUP_DIR=str(tmp_path / "var-backups"),
               FAKE_CRONTAB_IN=str(crontab_in), FAKE_CRONTAB_OUT=str(out))
    return env, cron_file


def test_install_cron_refuses_when_legacy_entry_exists(tmp_path):
    env, cron_file = _cron_env(tmp_path, legacy=True)
    proc = subprocess.run(["bash", str(RENEW), "--install-cron"], env=env,
                          capture_output=True, text=True, timeout=120)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, (
        f"检测到既有 crontab 条目 ⇒ 不安装（避免同一条续期跑两遍）并退 3（rc={proc.returncode}）：\n{out}")
    assert not cron_file.exists(), f"guard 触发时**不许**写 cron 文件：{cron_file}"
    assert "--replace-legacy-cron" in out, f"必须给出解除命令（人工一步）：\n{out}"


def test_install_cron_replaces_legacy_with_backup_and_is_idempotent(tmp_path):
    env, cron_file = _cron_env(tmp_path, legacy=True)
    first = subprocess.run(["bash", str(RENEW), "--install-cron", "--replace-legacy-cron"],
                           env=env, capture_output=True, text=True, timeout=120)
    out = first.stdout + first.stderr
    assert first.returncode == 0, f"替换安装必须退 0（rc={first.returncode}）：\n{out}"
    content = cron_file.read_text(encoding="utf-8")
    assert "tls-renew.sh" in content, f"cron 文件必须调用 tls-renew.sh：\n{content}"
    assert "migao-tls-renew.log" in content or str(env["MIGAO_TLS_LOG_FILE"]) in content, (
        f"日志必须落到可观测文件：\n{content}")
    assert "certbot renew" not in env["FAKE_CRONTAB_OUT"] and "docker compose restart" not in content, (
        "旧 crontab 条目必须被移出（已备份）且新 cron 不许 restart nginx")
    assert (tmp_path / "crontab.out").read_text(encoding="utf-8") == "", (
        f"旧条目应被过滤掉：\n{(tmp_path / 'crontab.out').read_text(encoding='utf-8')}")
    backup = list(tmp_path.glob("**/*crontab*.bak")) + list((tmp_path / "var-backups").glob("*"))
    assert backup, "删除别人的 crontab 行之前必须留备份（不许静默删）"

    second = subprocess.run(["bash", str(RENEW), "--install-cron", "--replace-legacy-cron"],
                            env=env, capture_output=True, text=True, timeout=120)
    assert second.returncode == 0, f"重复安装必须幂等退 0：\n{second.stdout}{second.stderr}"
    assert cron_file.read_text(encoding="utf-8") == content, "重复安装必须逐字节相同（幂等）"
    assert "已就位" in (second.stdout + second.stderr), (
        f"第二次必须明说「已就位」（不是又装一遍）：\n{second.stdout}{second.stderr}")


def test_install_cron_requires_root_guard(tmp_path):
    env, cron_file = _cron_env(tmp_path, legacy=False)
    env.pop("MIGAO_TLS_ASSUME_ROOT", None)
    env["MIGAO_TLS_FAKE_UID"] = "1000"
    proc = subprocess.run(["bash", str(RENEW), "--install-cron"], env=env,
                          capture_output=True, text=True, timeout=120)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, f"非 root ⇒ 跳过并退 3（rc={proc.returncode}）：\n{out}"
    assert "root" in out, f"必须明说跳过原因（非 root），不许静默：\n{out}"
    assert not cron_file.exists(), "guard 触发时不许写 cron 文件"


# ═══════════════════════════════════════════════════════════════════════════
# 判据 8：workflow 接线（main 侧 + 在失败出口之前 + 3 不许归一化为 0）
# ═══════════════════════════════════════════════════════════════════════════
def _steps(doc: dict) -> list[dict]:
    out: list[dict] = []
    for job in (doc.get("jobs") or {}).values():
        if isinstance(job, dict):
            out += [s for s in (job.get("steps") or []) if isinstance(s, dict)]
    return out


def tls_wiring_problems(doc: dict) -> list[str]:
    """判据 8 的单一实现（红证 = 在内存里变异本函数的输入）。"""
    steps = _steps(doc)
    idx = [i for i, s in enumerate(steps) if "tls-expiry-check.sh" in str(s.get("run", ""))]
    if not idx:
        return ["没有一步调用 `deploy/scripts/tls-expiry-check.sh` ⇒ TLS 到期判红**脱钩**"
                "（判据本体再全，也不会有人被叫醒）"]
    step = steps[idx[-1]]
    run = str(step.get("run", ""))
    problems: list[str] = []
    if "pull_request" not in str(step.get("if", "")):
        problems.append("TLS 判红步必须只在 main 侧跑（`if:` 里要排除 `pull_request`）"
                        "—— 否则 PR 会因生产证书临期而红，归因指向错误对象")
    for needle, why in (
        ("::error::", "判红必须 `::error::`（不是 `::warning::`）"),
        ("exit 3", "`3 = 无法判定` 必须原样带出（不许归一化成 0 = 假绿）"),
        ("tls-renewal.md", "判红文案必须指向 runbook `docs/deployment/tls-renewal.md`"),
        ("tls-renew.sh", "判红文案必须给一次性命令 `deploy/scripts/tls-renew.sh`"),
    ):
        if needle not in run:
            problems.append(f"TLS 判红步缺：{why}（未见 `{needle}`）")
    hooks = [i for i, s in enumerate(steps) if "failure()" in str(s.get("if", ""))]
    if hooks and idx[-1] > hooks[0]:
        problems.append("TLS 判红步必须在 `if: failure()` 的 P1 出口**之前**"
                        "（放在之后 ⇒ 判红不产生值班单，等于静默）")
    triggers = doc.get("on") or doc.get(True) or {}
    if not triggers.get("push") and not triggers.get("schedule"):
        problems.append("承接本判红的 workflow 必须在 main 侧事件上跑（push/schedule）")
    return problems


def test_workflow_wiring_is_present():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert tls_wiring_problems(doc) == [], "\n".join(tls_wiring_problems(doc))


@pytest.mark.parametrize("mutation", ["drop_step", "move_after_hook", "normalize_exit_3", "drop_if"])
def test_wiring_removal_turns_it_red(mutation):
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = _steps(doc)
    idx = [i for i, s in enumerate(steps) if "tls-expiry-check.sh" in str(s.get("run", ""))]
    assert idx, "变异点失配：workflow 里找不到 TLS 判红步（红证不得是空断言）"
    if mutation == "drop_step":
        for job in (doc.get("jobs") or {}).values():
            if isinstance(job, dict) and job.get("steps"):
                job["steps"] = [s for s in job["steps"] if "tls-expiry-check.sh" not in str(s.get("run", ""))]
    elif mutation == "move_after_hook":
        for job in (doc.get("jobs") or {}).values():
            if not isinstance(job, dict) or not job.get("steps"):
                continue
            tls = [s for s in job["steps"] if "tls-expiry-check.sh" in str(s.get("run", ""))]
            if not tls:
                continue
            rest = [s for s in job["steps"] if "tls-expiry-check.sh" not in str(s.get("run", ""))]
            job["steps"] = rest + tls
    elif mutation == "normalize_exit_3":
        for s in _steps(doc):
            if "tls-expiry-check.sh" in str(s.get("run", "")):
                s["run"] = str(s["run"]).replace('exit "$RC"', 'exit 0').replace("exit 3", "exit 0")
    else:
        for s in _steps(doc):
            if "tls-expiry-check.sh" in str(s.get("run", "")):
                s.pop("if", None)
    assert tls_wiring_problems(doc) != [], f"{mutation} 之后判据没红 ⇒ 空断言"


# ═══════════════════════════════════════════════════════════════════════════
# 判据 9：deploy.sh 的幂等安装（且回滚到旧 tag 时不许让部署 abort）
# ═══════════════════════════════════════════════════════════════════════════
def test_deploy_sh_installs_cron_idempotently_after_nginx_reload():
    text = SWAS_DEPLOY.read_text(encoding="utf-8")
    assert "--install-cron" in text, (
        "deploy/swas/deploy.sh 必须幂等安装宿主 cron（`tls-renew.sh --install-cron`）")
    assert "[ -f ./tls-renew.sh ]" in text, (
        "安装前必须判「脚本在盘上」—— 回滚到旧 tag 时 tarball 里没有 deploy/scripts/tls-renew.sh，"
        "无条件 `cp` 会让**回滚部署**当场 abort")
    assert "[ -f src/deploy/scripts/tls-renew.sh ]" in text, (
        "同步 `src/deploy/scripts/tls-renew.sh` 必须带存在性守卫（旧 ref 没有该文件）")
    reload_at = text.find("nginx -s reload")
    install_at = text.find("--install-cron")
    assert reload_at != -1 and install_at > reload_at, (
        "cron 安装必须在 nginx 起来/reload **之后**（否则证书与 nginx 时序颠倒）")
    assert "部署不受影响" in text, "安装失败/跳过必须明说「部署不受影响」（不许静默、也不许拖垮部署）"


def test_runbook_exists_and_covers_both_repair_paths():
    assert RUNBOOK.is_file(), f"缺 runbook {RUNBOOK.relative_to(REPO)}（issue #8201 的交付物）"
    text = RUNBOOK.read_text(encoding="utf-8")
    for needle, why in (
        ("admin.migaozn.com", "必须点名根因域名（缺 A 记录 ⇒ HTTP-01 必失败）"),
        ("--expand", "路径②（不补 DNS，重签并只带可解析 SAN）必须给可复制命令"),
        ("需人裁定", "路径②改变了 SAN 集合 ⇒ 必须写明「需人裁定」，不许默认执行"),
        ("renewal/api.migaozn.com.conf", "陈旧 lineage 必须给「不删证书」的禁用方式"),
        ("tls-renew.sh --install-cron", "cron 加固必须给可复制命令"),
        ("nginx -s reload", "必须写清用 reload 而不是 restart（不整断）"),
        ("Windows", "必须写清终端影响面（Windows/Android 终端不受影响，四域 HTTPS 全受影响）"),
        ("回滚", "必须有回滚节"),
        ("复算", "必须有可复算的验证明细"),
    ):
        assert needle in text, f"runbook 缺：{why}（未见 `{needle}`）"
