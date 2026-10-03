#!/usr/bin/env python3
# case_ids: MC-074
"""plaintext_credential_guard.py — 「凭据字面量留在代码里」的仓内守卫（issue #6172）。

## 病（issue #6172）

dev 内部 service token（`X-Service-Token`，64 位十六进制）以**明文**留在测试代码里：

* `backend/ai-agent-service/tests/contracts/conftest.py` —— 存量（#6172 处置）；
* `backend/ai-agent-service/tests/test_e2e_mibao_scenarios.py` —— 同一枚，随 PR #6170 处置。

**为什么 gitleaks 抓不住它**：`.github/workflows/pr-check.yml` 的 `Secret Scan (gitleaks)`
只扫 **diff 的新增行** ⇒ 存量明文**永不报警**（「能红的地方看不见它」）。本守卫因此**按现取**
扫**真源码**（工作树 / `git ls-files` 的当前内容），不钉一份手抄清单。

## 判什么（两条，各自可单独变红）

| # | 形态 | 例（**只描述形态，不写值**） |
|---|---|---|
| R1 | 凭据命名的键 = 字面量取值，且取值**够长/够像凭据** | `SERVICE_TOKEN = "<64hex>"` / `SECRET = "<40 位随机串>"` |
| R2 | 服务令牌请求头的**字面量**取值 | `"X-Service-Token": "<值>"`（空串 = 无凭据，**不判**） |

**为什么只判「字面量」**：`SERVICE_TOKEN = os.environ[...]` / `settings.SERVICE_TOKEN` /
`os.getenv("SERVICE_TOKEN", ...)` / `{"X-Service-Token": token}`（token 是参数或夹具注入的）
**一律不判** —— 它们是**正确**形态（凭据来自环境 / 调用方），判它们等于判红逼人把代码改坏。
（曾试过「R3：头引用凭据命名的常量」这一条，实测在真仓里命中 **17 处全是有意的注入形态**
（参数化夹具 / `settings.SERVICE_TOKEN` / `os.environ` 取值）⇒ **有意不做**：它判不出
「这个常量是字面量还是环境注入」，只会制造一片必须豁免的真·正确代码。
「字面量被搬进常量、再由头引用」这一形态已由 **R1 在定义处**抓住。）

## 正确的替代形态（判红时给出的出口，逐字照抄 issue #6170 的形态）

```python
SERVICE_TOKEN = os.environ.get("MIGAO_SERVICE_TOKEN", "")   # 真值由环境注入
...
headers = {"X-Service-Token": SERVICE_TOKEN} if SERVICE_TOKEN else {}   # 不设 ⇒ 不带该头
```

## 有意豁免（唯一通道：行内 `# noqa: plaintext-credential`，须带原因）

行内 pragma，写作 `# noqa: plaintext-credential :: <为什么这行可以留>`。
**为什么用行内 pragma 而不是路径台账**：豁免留在**被判的那一行旁边** ⇒ 「为什么不能改」
与被豁免对象**同生共死**（路径台账会与代码漂移，而漂移是静默的）。
只在**不是凭据**的形态上使用（如「测试名/字段名恰好叫 token」）；**真凭据不许豁免**。
`tests/unit_ci_workflows/test_plaintext_credential_guard.py` 正向核验：当前仓内**零**条豁免。

## 三态

| 态 | 退出码 | 含义 |
|---|---|---|
| `clean` | 0 | 零命中 |
| `violations` | 1 | 命中 N 条（逐条具名：`文件:行号` + 规则 + **该改用什么**） |
| `no_scan_face` | 3 | **无法判定**（扫不到任何文件 ⇒ 面不存在，**不得当 0 读**） |

## 用法

```bash
python3 .github/plaintext_credential_guard.py            # 扫工作树（判据/CI 的入口）
python3 .github/plaintext_credential_guard.py --json      # 机器可读
python3 .github/plaintext_credential_guard.py --root <dir>  # 扫指定根（测试用 tmp 面）
```

## 边界（照实登记，§19.1）

- 判的是**凭据命名 + 字面量取值**这一族；**不判**「随机字符串但名字不叫 token/secret」（会误伤哈希、
  订单号、迁移指纹等 —— 实测整仓扫描里那类噪声有上千条）。
- **不判**二进制 / 未跟踪的构建产物（`node_modules` / `.venv` / `dist` … 逐条列在 `SKIP_DIRS`）。
- **不替代** gitleaks：它是**新增行**扫描，本守卫只补「存量 + 形态」这一半。
- 判不了「这个值**是不是**真的那枚 dev token」（本仓**不许**再出现该值，不写进代码）⇒
  本守卫判的是**形态**（凭据名字 + 字面量），不是**具体值**。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRAGMA = "noqa: plaintext-credential"

# 凭据语义的键名（赋值 / 字典键 / 参数名共用同一张表）
_CRED_NAME = r"(?:service[_-]?token|api[_-]?key|access[_-]?key|secret[_-]?key|secret|password|passwd|credential)"
_CRED_NAME_RE = re.compile(_CRED_NAME, re.IGNORECASE)

# 「够像凭据」的字面量：长 / 十六进制 / base64 长串 / JWT。**短占位串不算**
# （`"test-service-token"` / `"svc-token-1"` / `""` 都不命中 —— 那是测试桩，不是凭据）。
_HEX64 = re.compile(r"^[0-9a-fA-F]{32,}$")
_LONG_RANDOM = re.compile(r"^[A-Za-z0-9_\-+/=.]{40,}$")
_JWT = re.compile(r"^eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+$")
_STR = r"""(?P<q>["'])(?P<v>[^"'\\\n]*)(?P=q)"""

# R1：`<凭据名> = "<字面量>"`（Python / Java / TS / 赋值 / 关键字参数 / 字典键）
# ⚠️ 左边界用**消费式** `[^\w]*`、不用 `(?<![A-Za-z0-9_])`：后者实测**不命中** `INJECTED_SERVICE_TOKEN = "…"`
#    （`\w` 把 `_` 算作单词字符 ⇒ 前缀 `INJECTED_` 让零宽断言永真/永不匹配，行为与直觉相反）。
#    消费式边界也没有「分隔符与名字里的 `[_-]` 争抢空白」那个坑（同一次实测踩到的）。
_R1 = re.compile(
    r"[^\w]*(?P<name>" + _CRED_NAME + r")\s*[:=]\s*" + _STR,
    re.IGNORECASE,
)
# R2：服务令牌请求头的字面量取值（空串 = 无凭据 ⇒ 由 _looks_like_credential 拒掉）
_R2 = re.compile(r"""["']X-Service-Token["']\s*[:=]\s*""" + _STR, re.IGNORECASE)

# 整行注释行（多种语言）—— 只做这一层，不做逐行剥注释：剥错了会**漏报**（比假红更坏）。
_COMMENT_LINE = re.compile(r"^\s*(#|//|\*|<!--|--|;)")
#: 本守卫自己 —— 它必须把被禁形态当**文档字符串**写出来（逐字排除，不是按目录白名单）。
SELF_PATH = os.path.abspath(__file__)

_TEXT_SUFFIXES = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".java", ".kt",
    ".sh", ".bash", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini",
    ".env", ".md", ".sql", ".properties", ".xml", ".txt",
)
_SKIP_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "dist", "build", ".next",
    "__pycache__", ".mypy_cache", ".pytest_cache", "target", ".turbo",
    ".idea", ".vscode", "coverage", "htmlcov", ".ruff_cache", ".gradle",
})
_SKIP_SUFFIXES = ("-lock.json", ".lock", ".min.js", ".min.css", ".map")


def _looks_like_credential(value: str) -> bool:
    """值像「真凭据」而不是测试桩 / 环境引用 / 空串。"""
    if not value:
        return False
    if _HEX64.match(value) or _JWT.match(value):
        return True
    return bool(_LONG_RANDOM.match(value))


def _is_environment_reference(line: str, name_end: int) -> bool:
    """`= os.environ[...]` / `= os.getenv(...)` / `= settings.<NAME>` ⇒ 环境注入，正确形态。

    只看赋值右侧的第一个 token：是**调用 / 属性访问**（而不是字符串字面量）即豁免。
    """
    rest = line[name_end:]
    return bool(re.match(r"\s*(?:os\.(?:environ|getenv)|getenv|env\.|settings\.|self\.|System\.getenv)", rest))


class Finding:
    __slots__ = ("path", "lineno", "rule", "name", "line")

    def __init__(self, path: str, lineno: int, rule: str, name: str, line: str):
        self.path, self.lineno, self.rule, self.name, self.line = path, lineno, rule, name, line

    def as_dict(self) -> dict:
        return {"path": self.path, "line": self.lineno, "rule": self.rule,
                "name": self.name, "snippet": self.line.strip()[:160]}

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: [{self.rule}] {self.name}"


def _scan_line(rel: str, lineno: int, line: str) -> list[Finding]:
    """单行判定（纯函数，供测试在内存里做变异注入）。"""
    if PRAGMA in line or _COMMENT_LINE.match(line):
        return []
    # 只剥 Python 系的行尾 `#` 注释（少数几类文本里 `#` 不是注释符 ⇒ 可能假剥 ⇒ 只可能**漏报**，
    # 不会假红；本仓的期望形态里 `#` 注释占绝大多数）。
    code = line if not rel.endswith((".py", ".sh", ".yml", ".yaml", ".toml", ".cfg", ".ini")) \
        else line.split("#", 1)[0]
    findings: list[Finding] = []
    for m in _R1.finditer(code):
        if _looks_like_credential(m.group("v")) and not _is_environment_reference(code, m.end("name")):
            findings.append(Finding(rel, lineno, "R1-credential-literal", m.group("name"), line))
    for m in _R2.finditer(code):
        if _looks_like_credential(m.group("v")):
            findings.append(Finding(rel, lineno, "R2-service-token-header-literal", "X-Service-Token", line))
    return findings


def _iter_files(root: str):
    """扫「真源码」：有 git 就用 `git ls-files`（= 仓库里真实存在、会被提交的文件），
    否则退回 os.walk（`--root` 指向 tmp 面的测试场景）。两者都**现取**。"""
    def _keep(rel: str) -> bool:
        parts = rel.split(os.sep)
        if any(p in _SKIP_DIRS for p in parts):
            return False
        if os.path.abspath(os.path.join(root, rel)) == SELF_PATH:
            return False  # 本守卫自己：被判形态在它的文档字符串里（逐字排除，非白名单）
        if rel.endswith(_SKIP_SUFFIXES):
            return False
        return rel.endswith(_TEXT_SUFFIXES)

    if os.path.isdir(os.path.join(root, ".git")):
        try:
            out = subprocess.run(
                ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True,
            ).stdout.decode("utf-8", "replace")
            for rel in sorted(p for p in out.split("\0") if p):
                if _keep(rel):
                    yield rel, os.path.join(root, rel)
            return
        except (OSError, subprocess.CalledProcessError):
            pass  # 退化到 os.walk（不静默：下面的「面为空」会判 3）
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            if _keep(rel):
                yield rel, full


def scan(root: str = REPO_ROOT) -> tuple[list[Finding], int]:
    """返回 `(findings, scanned_file_count)`。第三个状态由调用方按 count==0 判。"""
    findings: list[Finding] = []
    count = 0
    for rel, full in _iter_files(root):
        try:
            with open(full, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        count += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            findings.extend(_scan_line(rel, lineno, line))
    return findings, count


def render(findings: list[Finding], count: int) -> str:
    if not findings:
        return f"✅ 零命中（现取扫描：{count} 个文件）—— 凭据一律走环境注入（issue #6172）"
    lines = [
        f"❌ 命中 {len(findings)} 处「凭据字面量留在代码里」（现取扫描：{count} 个文件）",
        "",
        "改用什么（issue #6170 的形态，逐字照抄）：",
        '    SERVICE_TOKEN = os.environ.get("MIGAO_SERVICE_TOKEN", "")',
        '    headers = {"X-Service-Token": SERVICE_TOKEN} if SERVICE_TOKEN else {}',
        "",
    ]
    for f in findings:
        lines.append(f"  {f.path}:{f.lineno}: [{f.rule}] {f.name}")
        lines.append(f"      {f.line.strip()[:150]}")
    lines.append("")
    lines.append("（真凭据**不许**豁免；只有「名字恰好叫 token 但不是凭据」才可在行尾加 "
                 f"`# {PRAGMA} :: <原因>`）")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="凭据字面量进仓守卫（issue #6172）")
    ap.add_argument("--root", default=REPO_ROOT, help="扫描根（默认仓库根）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    findings, count = scan(args.root)
    if count == 0:
        print(json.dumps({"status": "no_scan_face", "root": args.root}) if args.json
              else f"⚠️ 无法判定：{args.root} 下扫不到任何可判文件 ⇒ 扫描面不存在（不得当 0 读）")
        return 3
    if args.json:
        print(json.dumps({"status": "violations" if findings else "clean",
                          "scanned": count,
                          "findings": [f.as_dict() for f in findings]}, ensure_ascii=False, indent=2))
    else:
        print(render(findings, count))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
