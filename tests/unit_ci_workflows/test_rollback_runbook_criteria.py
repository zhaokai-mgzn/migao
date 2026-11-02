# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""回滚 Runbook 的**判据地址必须是线上真的 200 的面**（issue #8197 P1-05）。

## 病（2026-10-31 上线审计，逐字读数）

`docs/deployment/rollback.md::1. 判定需要回滚的信号` 的第一条判据是：

```bash
curl api.migaozn.com/actuator/health
```

而 `deploy/swas/nginx.conf` 把 `/actuator` **整段 404**
（`location ~ ^/(actuator|v3/api-docs|swagger-ui)` ⇒ `return 404`）⇒ 线上实测 **404**。

后果：运维按 runbook 执行，会得到「**非 200 ⇒ 判定需要回滚**」的**错误信号** ——
它**永远命中** ⇒ 要么每次都被误导（假回滚），要么学会忽略这条判据（真的坏了也不看）。
这与 `migao-acceptance` 的「不会红的断言 = 空断言」同族，只是方向相反：**恒红的判据**。

## 判据（每条都能单独变红）

| # | 判据 | 变红形态 |
|---|---|---|
| 1 | 文档里每个 `https://…` 判据地址都**已登记**在「线上 200 面」白名单里（各带归属面） | 新增一条未登记地址 ⇒ 红（登记要求：先跑自检拿 200 读数） |
| 2 | 没有一个判据地址落在 nginx 的 **404 屏蔽面**里（屏蔽面**现取** nginx.conf 的 `return 404` 正则） | 把 `/actuator/health` 写回公网判据 ⇒ 红，并**指名**是哪条 location 屏蔽了它 |
| 3 | 「判据地址必须自己先 200」的自检段存在，且自检**真的覆盖**白名单里的地址 | 删掉自检 ⇒ 红；自检里的地址与白名单分叉 ⇒ 红 |
| 4 | 第 1 节里的「健康检查」判据点名的是 `/api/version` 与 `ai-api…/health`（线上 200 面） | 换成任意公网 404 面 ⇒ 红 |
| 5 | 容器内部面（`127.0.0.1`）与公网面**分开写**，并有「这是内部面」的说明 | 把内部面混进公网判据（少一句说明）⇒ 红 |
| 6 | 注入式自证（判据 1/2/3 各自在内存变异文本上判红） | 任一注入没被检出 ⇒ 红 |

## 线上读数（登记依据，2026-10-31 实测；复算命令在文档 §1 的自检段）

```
curl -s -o /dev/null -w "%{http_code}" https://api.migaozn.com/api/version      -> 200
curl -s -o /dev/null -w "%{http_code}" https://ai-api.migaozn.com/health        -> 200
curl -s -o /dev/null -w "%{http_code}" https://merchant.migaozn.com/login       -> 200
curl -s -o /dev/null -w "%{http_code}" https://api.migaozn.com/actuator/health  -> 404   ← 改前那条判据
```

## 边界（照实登记，§19.1）

- 判据 1 的「线上 200」是**登记时的读数**，测试**不联网**（CI 上不探生产 —— 那会让 PR 取决于生产状态）。
  ⇒ 它守住的是「**不许写未登记的判据地址**」；「登记的那条今天还 200 吗」由文档 §1 的自检命令人工/值班复算。
- 它判不了「运维有没有照做」，也判不了 `/api/version` 会不会某天变成 404（那要靠 `deploy-admin-api`
  的 served-sha 断言 + 本仓的 `post-merge-verify` TLS/版本判据）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_ROOT / "docs" / "deployment" / "rollback.md"
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"

#: 「线上真的 200 的面」白名单（**登记制**：新增判据地址必须先跑 §1 自检拿到 200 读数，再登记）
LIVE_200_ALLOWLIST: dict[str, str] = {
    "https://api.migaozn.com/api/version": "admin-api 版本面（nginx 放行 `/api/` 前缀；线上 200）",
    "https://ai-api.migaozn.com/health": "ai-agent 健康面（nginx 只屏蔽 /docs /redoc /openapi.json）",
    "https://merchant.migaozn.com/login": "admin-web 登录页（admin-web server 段 `location /`）",
}
#: 自检段的存在标记
SELF_CHECK_MARKERS = ("判据地址必须自己先 200", "自检（一条命令", "curl -s -o /dev/null -w")
#: 容器内部面的说明标记（`127.0.0.1` 那三条与公网判据是两套坐标）
INTERNAL_NOTE_MARKER = "容器内部面"

_URL_RE = re.compile(r"https://[A-Za-z0-9._-]+(?:\.[A-Za-z]{2,})?(?:/[^\s`'\"()<>，。；;]*)?")
#: 判据地址必须是**真域名 + 可选路径**（排除文档里当占位符用的 `https://…`）
_REAL_URL_RE = re.compile(r"^https://[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}(?:/\S*)?$")


def public_urls(text: str) -> set[str]:
    out: set[str] = set()
    for raw in _URL_RE.findall(text):
        url = raw.rstrip(";,.。，、")  # 命令里的 `;` / 句子里的标点不是 URL 的一部分
        if _REAL_URL_RE.match(url.lower()):
            out.add(url)
    return out


def blocked_public_prefixes(nginx_text: str) -> dict[str, str]:
    """→ {被屏蔽的前缀: 屏蔽它的 location 原文}（**现取** nginx.conf 的 `return 404` 正则 location）。"""
    out: dict[str, str] = {}
    for m in re.finditer(r"location\s+~\s+(\S+)\s*\{([^}]*)\}", nginx_text, re.S):
        pattern, body = m.group(1), m.group(2)
        if "return 404" not in body:
            continue
        if not pattern.startswith("^/("):  # 形态：^/(a|b|c)(/|$)
            continue
        alternation = re.search(r"\(([^)]*)\)", pattern)
        if not alternation:
            continue
        for part in alternation.group(1).split("|"):
            part = part.strip().replace("\\", "")
            if part:
                out[f"/{part}"] = m.group(0).splitlines()[0].strip()
    return out


def judge_runbook(text: str, nginx_text: str) -> list[str]:
    v: list[str] = []
    urls = public_urls(text)
    blocked = blocked_public_prefixes(nginx_text)

    # 判据 2：不许把判据地址写在 404 屏蔽面上
    for url in sorted(urls):
        path = "/" + url.split("/", 3)[3] if url.count("/") >= 3 else "/"
        path = path.split("?")[0]
        for prefix, where in blocked.items():
            if path == prefix or path.startswith(prefix + "/"):
                v.append(
                    f"判据地址 {url} 落在 nginx 的 404 屏蔽面 `{prefix}` 上"
                    f"（{where}）⇒ 这条判据**永远命中**（2026-10-31 线上实测 404）"
                )

    # 判据 1：登记制
    for url in sorted(urls):
        if url not in LIVE_200_ALLOWLIST:
            v.append(
                f"判据地址 {url} 没有登记在「线上 200 面」白名单里 ⇒ 先跑 §1 自检拿 200 读数，"
                "再写进 tests/unit_ci_workflows/test_rollback_runbook_criteria.py 的 LIVE_200_ALLOWLIST"
            )

    # 判据 3：自检段存在，且**覆盖**白名单
    for marker in SELF_CHECK_MARKERS:
        if marker not in text:
            v.append(f"文档里缺少自检段标记「{marker}」（判据地址必须自己先 200 这条没人守）")
    for url in LIVE_200_ALLOWLIST:
        if url not in text:
            v.append(f"自检段没有覆盖已登记的判据地址 {url}（自检与白名单分叉）")

    # 判据 4：第 1 节的健康判据点名 200 面（判据点 + 它下面缩进的子条目一起看）
    lines = text.splitlines()
    idx = next((i for i, line in enumerate(lines) if line.startswith("- 健康检查异常")), None)
    if idx is None:
        v.append("第 1 节里找不到「健康检查异常」这条判据（本判据的坐标没了）")
    else:
        block_lines = [lines[idx]]
        for follow in lines[idx + 1: idx + 8]:
            if not follow.startswith((" ", "\t")):
                break
            block_lines.append(follow)
        block = "\n".join(block_lines)
        if "/api/version" not in block:
            v.append("「健康检查异常」判据没有点名 `/api/version`（线上 200 的那条面）")
        if "ai-api.migaozn.com/health" not in block:
            v.append("「健康检查异常」判据没有点名 `ai-api.migaozn.com/health`（线上 200 的那条面）")
        if re.search(r"https://api\.migaozn\.com/actuator", block):
            v.append("「健康检查异常」判据仍在用公网 `/actuator/health`（nginx 404 面）")

    # 判据 5：内部面与公网面分开
    if INTERNAL_NOTE_MARKER not in text:
        v.append(f"文档里缺少「{INTERNAL_NOTE_MARKER}」说明（`127.0.0.1` 那三条与公网判据是两套坐标）")
    if "http://127.0.0.1:8080/actuator/health" not in text:
        v.append("§3 的容器内部健康面（`127.0.0.1:8080/actuator/health`）不见了 —— 内部面与公网面是两套坐标")
    return v


# ══════════════════════════════════════════════════════════════════════════
# 静态判据
# ══════════════════════════════════════════════════════════════════════════


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_rollback_criteria_are_live_200_faces():
    v = judge_runbook(_read(RUNBOOK), _read(NGINX_CONF))
    assert not v, "回滚 runbook 判据未通过：\n- " + "\n- ".join(v)


def test_nginx_actually_blocks_actuator_publicly():
    """反向锚点：`/actuator` 的 404 屏蔽必须**仍然在**（否则本判据的前提变了，要重新评估）。"""
    blocked = blocked_public_prefixes(_read(NGINX_CONF))
    assert "/actuator" in blocked, (
        "nginx.conf 里 `/actuator` 的 404 屏蔽不见了 —— 那本文件「公网 /actuator 是 404」的前提变了："
        "先复核本判据与 rollback.md 的判据地址（不要直接删判据）"
    )


# ══════════════════════════════════════════════════════════════════════════
# 注入式红证
# ══════════════════════════════════════════════════════════════════════════


def _inject(text: str, needle: str, replacement: str) -> str:
    assert needle in text, f"注入点定位失败（fail-closed）：找不到 {needle!r}"
    mutated = text.replace(needle, replacement, 1)
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    return mutated


def test_injection_blocked_public_criterion_is_caught():
    """改前形态逐字复现：把 `/actuator/health` 写回公网判据 ⇒ 必须判红并指名屏蔽面。"""
    doc = _read(RUNBOOK)
    mutated = _inject(
        doc,
        "- 部署后冒烟失败（post-deploy smoke / frontend probe）",
        "- 部署后冒烟失败（post-deploy smoke / frontend probe）\n"
        "- 健康检查异常（`curl https://api.migaozn.com/actuator/health` 非 200）",
    )
    v = judge_runbook(mutated, _read(NGINX_CONF))
    assert any("404 屏蔽面" in x and "/actuator" in x for x in v), v


def test_injection_unregistered_live_face_is_caught():
    doc = _read(RUNBOOK)
    mutated = _inject(
        doc,
        "- 用户投诉 / 关键指标异常（订单、登录、AI 对话）",
        "- 用户投诉 / 关键指标异常（订单、登录、AI 对话）\n- 随便一条未登记的面 https://api.migaozn.com/api/health",
    )
    v = judge_runbook(mutated, _read(NGINX_CONF))
    assert any("没有登记" in x and "/api/health" in x for x in v), v


def test_injection_self_check_removed_is_caught():
    doc = _read(RUNBOOK)
    mutated = _inject(doc, "判据地址必须自己先 200", "判据地址不用自检")
    v = judge_runbook(mutated, _read(NGINX_CONF))
    assert any("自检段标记" in x for x in v), v


if __name__ == "__main__":  # pragma: no cover - 手工复算入口
    raise SystemExit(pytest.main([__file__, "-q"]))
