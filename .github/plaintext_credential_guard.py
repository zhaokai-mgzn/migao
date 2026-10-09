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

## R3：验收产物 / 测试面上的**裸** token 字面量（issue #6303）

`acceptance/**` 的机器产物按惯例要**提交进仓库**，而 R1 是「**凭据命名的键** = 字面量」——
**键名不叫 service token 的产物它一条也抓不到**（现取实测，三种真实形态全部漏判）：

| 产物里的形态（键名） | R1/R2 | 为什么漏 |
|---|---|---|
| `"tokenA": "ey…"` | 不判 | 键名 `tokenA` 不匹配 `_CRED_NAME` |
| `"accessToken": "ey…"` | 不判 | 同上 |
| `"service_token": "ey…"` | 不判 | 键名匹配，但 **`_R1` 的左右边界吃不下键的闭引号**（`"service_token":` 里 `"` ∉ `\w`，`[^\w]*` 只能消费一处） |

风险：**一条 `git add acceptance/` 就把活 JWT 推上远端**（2026-10-04 实测 `race-sweep/out/fixtures.json`
落着登录后的真 token）—— gitleaks 只扫 **diff 新增行** ⇒ 存量永不报警，正是本守卫存在的理由。

**判据形态（只判**裸** JWT，不判「长随机串」）**：三段 base64url、点分，且**去掉固定头 `ey`+`J` 之后
仍 ≥ `_R3_MIN_BODY` 个字符**。这条「**除固定头之外没有足够熵 ⇒ 不成立**」的判据是**刻意**的：

- `method-notes.md` 里那句**文档截断举例**（固定 JWT 头 + `…`）⇒ **不判**（它后面没有第二段，也够不着长度门）；
- 三段假 token（每段几十字符）⇒ **判**（合成样本见判据文件）。

射程 = `acceptance/**` 与 `tests/**` 的 `.json` / `.log` / `.md`（issue #6303 点名的产物面）+ 运行态
会话存储的**可见**名（`.session.json` / `.store.json` —— 它们本该走 `.gitignore`，被跟踪了就是机制失效）。
**射程外**：`.mjs` 等**写盘装置**（harness 源码）与 `docs/**` —— 本规则不替 `.gitignore` 做兜底，
未覆盖的形态**有意登记**在下面「边界」里（不粉饰成"已覆盖"）。

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
  订单号、迁移指纹等 —— 实测整仓扫描里那类噪声有上千条）。**唯一例外 = R3**（issue #6303）：它把
  `acceptance/**`/`tests/**` 的产物面上的**裸 JWT** 也算进来 —— 那条不靠键名，靠「**三段点分 + 去头后
  仍有 ≥ `_R3_MIN_BODY` 字符**」的**结构**判据（长度门是防「文档里截断举例」误报的那一半）。
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
from functools import lru_cache

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

# R3（issue #6303）：`acceptance/**` / `tests/**` 的**产物面**上「裸 JWT 字面量」。
# 判据 = **结构**（三段点分）+ **长度门**（去掉固定头后仍 ≥ _R3_MIN_BODY）——
# 「除固定头之外没有足够熵 ⇒ 不成立」，故文档里的**截断举例**（`ey…` + `…`）**不判**（防误报）。
# ⚠️ 固定头**拆开拼**：本文件也是被判对象之一 ⇒ 不许出现连续的 `ey`+`J` 字面量（自洽，同 pr_body_guard 的 R3）。
# ⚠️ **不**用 `_JWT` 本体：它按 `^…$` 锚在「整行恰好是一个 JWT」上，产物里的形态是
# `"tokenA": "ey…"` ⇒ 锚定式判据在**引用处**永不命中（现取实测：三种真实键名全部漏判）。
_JWT_HEAD = "ey" + chr(74) + "[A-Za-z0-9_\\-]*"   # chr(74) == 'J'（拆开写 ⇒ 本文件自身不含连续固定头）
_R3_MIN_BODY = 40
_R3 = re.compile(
    "(" + _JWT_HEAD + r")\.[A-Za-z0-9_\-]+\.([A-Za-z0-9_\-]{" + str(_R3_MIN_BODY) + ",})")

#: R3 的射程：产物面两个根 + 三种文本后缀（issue #6303 点名 `.json`/`.log`/`.md`）。
_R3_ROOTS = ("acceptance/", "tests/")
_R3_SUFFIXES = (".json", ".log", ".md")
#: 运行态**会话存储**的可见名 —— 它们本该被 `.gitignore` 排除，出现在被跟踪集合里就是机制失效。
_SESSION_STORE_NAMES = (".session.json", ".store.json")
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


def _comment_free_value(value: str) -> str:
    """从捕获到的取值里取「无注释、无闭引号」的那一段。

    ⚠️ 这里是**元守卫点名的 `naive-hash-cut` 形态**所在（`tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py`）：
    朴素的 `split("#")` 会把字符串**内部**的 `#` 也当注释切掉 ⇒ 那正是本仓的
    `test_guard_parsing_is_comment_aware` 要防的假绿。本函数因此**引号感知**：
    从取值开头重扫（调用方在取值前垫一个空格，**不把开引号喂进来** —— 喂进来的话闭引号
    会被记成「开引号」而让串内/串外判定整个反过来），只切**引号外**的 `#`，并去掉尾巴上的闭引号。
    """
    quote: str | None = None
    i = 0
    while i < len(value):
        ch = value[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "#":
            return value[:i].strip("\"'").strip()
        i += 1
    return value.strip("\"'").strip()


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


def _strip_py_comment(line: str) -> str:
    """剥 Python 系的行尾 `#` 注释 —— **引号感知**（字符串里的 `#` 不是注释）。

    ⚠️ 不用 `.split("#")` / `re.sub(r"#.*")` 那类**朴素截断**：字符串里的一个 `#`
    （如 `"X-Service-Token": "a#b"`）会把行尾整段吃掉 ⇒ 可能**漏判**（仓内元守卫
    `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py` 的 `naive-hash-cut`
    正是判这个形态）。字符串内的 `#` 不切；转义 `\\` 跳过下一个字符。
    """
    quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
        i += 1
    return line


def _r3_rules(rel: str, is_ignored) -> list[str]:
    """本文件在不在 R3 射程里 ⇒ 返回 `["R3-artifact-token-literal"]` 或 `[]`（issue #6303）。

    两条入口，各自独立可判：
    ① **产物面**：`acceptance/**` / `tests/**` 下的 `.json` / `.log` / `.md`；
    ② **会话存储的可见名**：任何路径上的 `.session.json` / `.store.json` —— **只判「本该被忽略
       却仍被跟踪」**（`is_ignored` 为真 ⇒ **整条规则对本文件退出**：被忽略的文件本就不会被提交，
       判它等于逼人给正常产物加豁免）；`is_ignored is None`（非 git 面 / git 不可用）⇒ 第 ② 条
       **不判**（不臆造「本该被忽略」的读数），该名下的 `.json` 仍由第 ① 条的后缀面兜住。
       改成别的名（如 `state.json`）⇒ 只剩第 ① 条覆盖（是 `.json`），**登记为边界**。
    """
    if is_ignored is not None and is_ignored(rel):
        return []                                   # 已被 .gitignore 排除 ⇒ 进不了仓，不判（两个名都不判）
    if rel.endswith(_SESSION_STORE_NAMES):
        return ["R3-artifact-token-literal"]        # 本该被排除却进来了 ⇒ 机制失效
    if rel.endswith(_R3_SUFFIXES) and rel.startswith(_R3_ROOTS):
        return ["R3-artifact-token-literal"]
    return []


def _scan_line(rel: str, lineno: int, line: str, rules: tuple[str, ...] = ("R1", "R2")) -> list[Finding]:
    """单行判定（纯函数，供测试在内存里做变异注入）。

    `rules` 决定本行适用哪几条（R3 只对产物面生效 —— 由 `_r3_rules` 现取，**不**在行内再判路径）。
    """
    if PRAGMA in line or _COMMENT_LINE.match(line):
        return []
    # 只剥 Python 系的 `#` 注释（少数几类文本里 `#` 不是注释符 ⇒ 只可能**漏判**，不会假红）。
    code = _strip_py_comment(line) if rel.endswith(
        (".py", ".sh", ".yml", ".yaml", ".toml", ".cfg", ".ini")) else line
    findings: list[Finding] = []
    if "R1" in rules:
        for m in _R1.finditer(code):
            value = _comment_free_value(" " + m.group("v"))
            if _looks_like_credential(value) and not _is_environment_reference(code, m.end("name")):
                findings.append(Finding(rel, lineno, "R1-credential-literal", m.group("name"), line))
    if "R2" in rules:
        for m in _R2.finditer(code):
            if _looks_like_credential(_comment_free_value(" " + m.group("v"))):
                findings.append(Finding(rel, lineno, "R2-service-token-header-literal", "X-Service-Token", line))
    if "R3" in rules:
        for m in _R3.finditer(code):
            body = code[m.start():].strip().strip("\"',")
            findings.append(Finding(rel, lineno, "R3-artifact-token-literal",
                                    body[:24] + "…", line))
    return findings


def _iter_files(root: str):
    """扫「真源码」：有 git 就用 `git ls-files`（= 仓库里真实存在、会被提交的文件），
    否则退回 os.walk（`--root` 指向 tmp 面的测试场景）。两者都**现取**。

    产出 `(rel, full, git_backed)` —— `git_backed` 现取（**不写死**）：只用真仓库那一次判定
    「本该被忽略却仍被跟踪」（R3 的第 ② 条入口），tmp 面上不臆造该读数。
    """
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
                    yield rel, os.path.join(root, rel), True
            return
        except (OSError, subprocess.CalledProcessError):
            pass  # 退化到 os.walk（不静默：下面的「面为空」会判 3）
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            if _keep(rel):
                yield rel, full, False


@lru_cache(maxsize=None)
def _is_git_ignored(root: str, rel: str):
    """`git check-ignore` ⇒ `True`/`False`；git 不可用 / 报错 ⇒ `None`（**不可判定**，不猜）。

    按 (root, rel) **缓存**：同一根下逐个文件判会起上千个进程 —— 而 R3 的第 ② 条入口只在
    「`.git` 在根上」（真仓）时才问，问的次数 = 命中 `.session.json`/`.store.json` 可见名的文件数（实测 0~4）。
    """
    try:
        proc = subprocess.run(["git", "check-ignore", "-q", "--no-index", "--", rel],
                              cwd=root, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode == 0


def scan(root: str = REPO_ROOT) -> tuple[list[Finding], int]:
    """返回 `(findings, scanned_file_count)`。第三个状态由调用方按 count==0 判。"""
    findings: list[Finding] = []
    count = 0
    for rel, full, git_backed in _iter_files(root):
        try:
            with open(full, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        count += 1
        ignored = (lambda r, _root=root: _is_git_ignored(_root, r)) if git_backed else None
        rules = ("R1", "R2") + (("R3",) if _r3_rules(rel, ignored) else ())
        for lineno, line in enumerate(text.splitlines(), 1):
            findings.extend(_scan_line(rel, lineno, line, rules))
    return findings, count


def render(findings: list[Finding], count: int) -> str:
    if not findings:
        return f"✅ 零命中（现取扫描：{count} 个文件）—— 凭据一律走环境注入（issue #6172）；" \
               f"验收产物 / 测试面上零裸 token（issue #6303）"
    lines = [
        f"❌ 命中 {len(findings)} 处「凭据 / token 字面量留在被跟踪文件里」（现取扫描：{count} 个文件）",
        "",
        "改用什么（issue #6170 的形态，逐字照抄）：",
        '    SERVICE_TOKEN = os.environ.get("MIGAO_SERVICE_TOKEN", "")',
        '    headers = {"X-Service-Token": SERVICE_TOKEN} if SERVICE_TOKEN else {}',
        "",
        "R3（issue #6303，验收产物 / 测试面的裸 token）⇒ 落盘前**脱敏**"
        "（`<REDACTED-JWT>`）+ 运行态会话存储交给 `.gitignore`（`git rm --cached` 掉已入库的那几个），",
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
