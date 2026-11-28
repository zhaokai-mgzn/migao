# case_ids: MC-394
"""企微「可信域名」校验：**一条通用规则服务所有商户**（issue #9358 / #9361）。

## 病灶一（2026-11-28）：O(商户数) 的人工进交付链

企微给**每个商户的自建应用**各生成一个 `WW_verify_<随机串>.txt`，全部要求放在**同一个域名根**
（我们的 `migaozn.com`）。第一版把它当静态资源塞进 `frontend/admin-web/public/` ⇒
**每加一个商户 = 一次前端构建 + 部署**。用户当场问「难道未来每个客户的证书我都需要构建后部署？」。

## 为什么可以「零文件」

实测（企微真文件逐字节对照）：

    WW_verify_mRPj5ZGvHWQrpeer.txt 的 body 逐字节 = mRPj5ZGvHWQrpeer

⇒ nginx 一条正则捕获即返回，**任意商户、零操作、零部署**。

## 病灶二（2026-11-29 00:00 实测）：正则没加引号 = **部署阻断**

含 `{`/`}` 的正则若不加引号，nginx 配置解析器把 `{` 当块起始 ⇒ 正则在 `{8,64}` 处被截断：

    [emerg] pcre2_compile() failed: missing closing parenthesis in "^/WW_verify_([A-Za-z0-9]"
    nginx: configuration file /etc/nginx/nginx.conf test failed
    ❌ nginx -t 不通过 ⇒ 已恢复 ./nginx/nginx.conf.bak-…、**未 reload**

后果：PR 的 CI **全绿**（CI 不跑 `nginx -t`），只在 `Deploy to SWAS` 炸 + 自动回滚 ⇒
每轮合并都白跑一次部署。**这类病必须由静态判据兜住**，故有判据 5。

## 判据（每条都能单独变红）

1. apex 段有该 location，`default_type text/plain` + `return 200 $1`；
2. **正则加引号**（部署阻断类，见上）；
3. 边界不许放宽成 `^/.*\\.txt$`（会劫持同段其它 `.txt` 面）；
4. `app.migaozn.com` 段既有语义（`try_files … =404`，MC-125）不受影响；
5. 红证：按花括号配平把该 location 整段摘掉 ⇒ 判据 1 具名红。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NGINX = REPO / "deploy" / "swas" / "nginx.conf"

# 期望的正则主体（引号单独判，见判据 2）
BODY_RE = r"^/WW_verify_([A-Za-z0-9]{8,64})\.txt$"


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


def _verify_location(block: str) -> dict:
    """解析该 location。`found` 表存在性，`quoted` 表正则是否被引号包起来。"""
    lines = [l for l in block.splitlines() if l.lstrip().startswith("location") and "WW_verify_" in l]
    if not lines:
        return {"found": False, "quoted": False, "body": "", "content_type": False, "returns_capture": False}
    head = lines[0]
    quoted = 'location ~ "' in head and head.rstrip().endswith('{')
    # 取该 location 的 body（到下一个同缩进的 `}` 为止）
    start = block.index(head)
    line_end = block.index("\n", start)      # 正则里的 `{8,64}` 也含 `{`，不能取第一个
    brace = block.rindex("{", start, line_end)
    depth, j = 0, brace
    while j < len(block):
        if block[j] == "{":
            depth += 1
        elif block[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    body = block[brace + 1:j]
    return {
        "found": True,
        "quoted": quoted,
        "head": head,
        "body": body,
        "content_type": "text/plain" in body,
        "returns_capture": bool(re.search(r"return\s+200\s+\$1\s*;", body)),
    }


def test_apex_serves_any_ww_verify_code():
    """判据 1：apex 段有通用规则，返回体 = 文件名里的串。"""
    loc = _verify_location(_apex_block(_conf()))
    assert loc["found"], (
        "migaozn.com 段缺 WW_verify 通用 location ⇒ 每个商户的校验文件都得手工放进镜像再部署（#9358）")
    assert loc["content_type"], "该 location 没声明 `default_type text/plain`（企微按纯文本比对）"
    assert loc["returns_capture"], "该 location 没把捕获串当 body 返回（`return 200 $1;`）"
    assert BODY_RE in loc["head"].replace('"', ""), (
        f"正则主体不是 {BODY_RE!r}（边界写宽会劫持、写窄会让新商户的串匹配不上）")


def test_regex_is_quoted_so_nginx_can_parse():
    """判据 2·**部署阻断类**：正则含 `{`/`}` 必须加引号，否则 nginx 在 `{8,64}` 处截断。"""
    loc = _verify_location(_apex_block(_conf()))
    assert loc["found"], "通用规则不在场（判据 1 已红，先修那个）"
    assert loc["quoted"], (
        "该 location 的正则没加引号：nginx 会把 `{8,64}` 的 `{` 当块起始 ⇒ "
        "`pcre2_compile() failed: missing closing parenthesis` ⇒ 部署腿整腿失败 + 自动回滚（2026-11-29 实测）")


def test_pattern_is_not_a_wildcard():
    """判据 3：边界必须收紧 —— 不许 `^/.*\\.txt$`（会劫持同段其它 `.txt` 面）。"""
    block = _apex_block(_conf())
    assert not re.search(r'location\s+~\s+"?(\^/\.\*\\\.txt\$)', block), (
        "发现通配式 `.txt` location：会把 apex 段其它 `.txt` 请求一并劫持")


def test_app_block_rule_is_untouched():
    """判据 4：`app.migaozn.com` 段既有语义不受影响（两段各管各的）。"""
    conf = _conf()
    found = ""
    for b in _server_blocks(conf):
        m = re.search(r"server_name\s+([^;]+);", b)
        if m and "app.migaozn.com" in m.group(1).split() and "listen 443" in b:
            found = b
            break
    assert "app.migaozn.com" in found, "取不到 app.migaozn.com 的 443 server 段 ⇒ 判据面本身就错了"
    assert "try_files" in found and "=404" in found, (
        "app 段既有的 `try_files … =404`（缺失必须 404，不许回落 SPA）不见了 —— 那是 MC-125 的判据")


def test_red_proof_removing_the_rule_is_named():
    """判据 5·红证：把通用 location 整段摘掉 ⇒ 判据 1 必须失败（不是恒绿）。"""
    conf = _conf()
    start = conf.index('    location ~ "^/WW_verify_')
    line_end = conf.index("\n", start)
    brace = conf.rindex("{", start, line_end)
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
    loc = _verify_location(_apex_block(mutated))
    assert not loc["found"], "摘掉之后仍然解析到了该 location ⇒ 解析面不可信（判据会是恒真）"


def test_red_proof_unquoted_regex_is_named():
    """判据 2 的红证：把引号去掉 ⇒ `quoted` 必须变假（证明判据读的是现取配置）。"""
    conf = _conf()
    unquoted = conf.replace('location ~ "^/WW_verify_([A-Za-z0-9]{8,64})\\.txt$" {',
                            "location ~ ^/WW_verify_([A-Za-z0-9]{8,64})\\.txt$ {", 1)
    assert unquoted != conf, "红证前提不成立：没能把引号去掉"
    loc = _verify_location(_apex_block(unquoted))
    assert loc["found"] and not loc["quoted"], (
        "去掉引号后 `quoted` 仍为真 ⇒ 判据 2 是恒真，兜不住「未加引号 ⇒ 部署腿炸」这类病")
