# case_ids: MC-394
"""企微「可信域名」校验：**一条通用规则服务所有商户**（issue #9358）。

## 病灶（2026-11-28 实测，不是假想）

企微给**每个商户的自建应用**各生成一个 `WW_verify_<随机串>.txt`，并且**全部要求放在同一个域名根**
（我们的 `migaozn.com`）。第一版把它当静态资源塞进 `frontend/admin-web/public/` ⇒
**每加一个商户 = 一次前端构建 + 部署**。把 O(商户数) 的人工塞进交付链，是产品级错误，
不是「操作麻烦一点」。

## 为什么可以「零文件」

实测（企微真文件逐字节对照）：

```
文件名  WW_verify_mRPj5ZGvHWQrpeer.txt
body    mRPj5ZGvHWQrpeer          ← 内容恒等于文件名里的随机串
```

⇒ nginx 一条正则 `^/WW_verify_([A-Za-z0-9]{8,64})\\.txt$` 直接把捕获串当 body 返回，
**任意商户、零操作、零部署**。

## 判据（每条都能单独变红）

1. `migaozn.com` 段（apex）有该正则 location，且 `default_type text/plain` + `return 200 $1`；
2. **不许写成 `^/.*\\.txt$`**：那会劫持同段其它 `.txt` 面（把边界写死的反面样本）；
3. `app.migaozn.com` 段既有的「根下单段 `.txt` → try_files =404」规则**未被本改动影响**
   （两段各管各的：apex 是校验文件，app 是小程序校验文件 + 静态根）；
4. 红证：把该 location 从配置里摘掉 ⇒ 判据 1 具名红（证明它判的是**现取配置**，不是常量）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NGINX = REPO / "deploy" / "swas" / "nginx.conf"

PATTERN = r"^/WW_verify_([A-Za-z0-9]{8,64})\.txt$"


def _conf() -> str:
    assert NGINX.is_file(), f"找不到 {NGINX}"
    return NGINX.read_text(encoding="utf-8")


def _server_blocks(conf: str) -> list[str]:
    """切出每个 `server { … }` 段（花括号配平）。照抄 MC-125 那个已经跑通的实现。"""
    blocks: list[str] = []
    for m in re.finditer(r"\bserver\s*\{", conf):
        i = conf.index("{", m.start())
        depth, j = 0, i
        while j < len(conf):
            if conf[j] == "{":
                depth += 1
            elif conf[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blocks.append(conf[i + 1:j])
    return blocks


def _apex_block(conf: str) -> str:
    for body in _server_blocks(conf):
        m = re.search(r"server_name\s+([^;]+);", body)
        if m and "migaozn.com" in m.group(1).split() and "listen 443" in body:
            return body
    raise AssertionError("migaozn.com（apex）的 443 server 段找不到")


def _verify_location(block: str) -> dict | None:
    m = re.search(r"location\s+~\s+\^/WW_verify_\(\[A-Za-z0-9\]\{8,64\}\)\\\.txt\$\s*\{(.*?)\}", block, re.DOTALL)
    if not m:
        return None
    body = m.group(1)
    return {
        "body": body,
        "content_type": "text/plain" in body,
        "returns_capture": bool(re.search(r"return\s+200\s+\$1\s*;", body)),
    }


def test_apex_serves_any_ww_verify_code():
    """判据 1：apex 段有通用规则，返回体 = 文件名里的串。"""
    loc = _verify_location(_apex_block(_conf()))
    assert loc is not None, (
        "migaozn.com 段缺 `WW_verify_<随机串>.txt` 的通用 location ⇒ "
        "每个商户的校验文件都得手工放进镜像再部署（issue #9358 的原始形态）"
    )
    assert loc["content_type"], "该 location 没声明 `default_type text/plain`（企微按纯文本比对）"
    assert loc["returns_capture"], "该 location 没把捕获串当 body 返回（`return 200 $1;`）"


def test_pattern_is_not_a_wildcard():
    """判据 2：边界必须收紧 —— 不许 `^/.*\\.txt$`（会劫持同段其它 `.txt` 面）。"""
    block = _apex_block(_conf())
    assert not re.search(r"location\s+~\s+\^/\.\*\\\.txt\$", block), (
        "发现 `^/.*\\.txt$` 这类通配：会把 apex 段其它 `.txt` 请求一并劫持（含将来新增的面）"
    )
    assert PATTERN.replace("([A-Za-z0-9]{8,64})", "([A-Za-z0-9]{8,64})") in block, (
        "边界不是 `WW_verify_` + 8–64 位字母数字（写宽 = 劫持，写窄 = 新商户的串可能不匹配）"
    )


def test_app_block_rule_is_untouched():
    """判据 3：`app.migaozn.com` 段既有语义不受影响（两段各管各的）。"""
    conf = _conf()
    app = None
    for b in _server_blocks(conf):
        m = re.search(r"server_name\s+([^;]+);", b)
        if m and "app.migaozn.com" in m.group(1).split() and "listen 443" in b:
            app = b
            break
    assert app is not None, "app.migaozn.com 段找不到"
    assert "try_files" in app and "=404" in app, (
        "app 段既有的 `try_files … =404`（缺失必须 404，不许回落 SPA）不见了 —— 那是 MC-125 的判据"
    )


def test_red_proof_removing_the_rule_is_named():
    """判据 4·红证：把通用 location 摘掉 ⇒ 判据 1 必须失败（不是恒绿）。"""
    conf = _conf()
    start = conf.index("    location ~ ^/WW_verify_")
    brace = conf.index("{", start)
    depth, j = 0, brace
    while j < len(conf):
        if conf[j] == "{":
            depth += 1
        elif conf[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    mutated = conf[:start] + conf[j + 1:]
    assert mutated != conf, "红证前提不成立：没能把该 location 摘掉"
    loc = _verify_location(_apex_block(mutated))
    assert loc is None, "摘掉之后仍然解析到了该 location ⇒ 解析面不可信（判据会是恒真）"
