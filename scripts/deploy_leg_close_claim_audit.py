#!/usr/bin/env python3
# case_ids: MC-012
r"""`[deploy-leg]` 清零声明的**类级元守卫**（issue #7075）。

## 病（逐字现场，不要转述）

`scripts/deploy_leg_failure_reaction.sh` 的 `clear_leg()` 走**状态兜底**那条路（`why` 不含 `success`）
时把 `gh issue close --reason` 传成了 **`not_planned`（下划线）**，而 gh 只认 **`not planned`（空格）**
⇒ `gh` 在**参数解析阶段**就报 `invalid argument "not_planned" for "-r, --reason" flag`，
而那一行被 `|| :` 咽掉，下一行**照样**打印「✅ … 自动关闭值守单 #N」。

实测读数（本脚本的 `check-claims` 就是为这条形态写的）：

```
$ gh run view 38979620458 --log | grep 自动关闭          # 23:07:52Z 那一轮
✅ 腿 worker-h5 已收敛 ⇒ 自动关闭值守单 #7025（… 状态=`deployed` …）
$ gh issue view 7025 --json state -q .state             # 同一条腿、同一分钟
OPEN
```

## 判据（三态；`check-claims` 与 `check-static` 两个子命令）

| 子命令 | 判什么 | 三态 |
|---|---|---|
| `check-claims` | **「清零注释已写『自动关闭』」与「该单真是 CLOSED」必须一致** —— 现取**开放**的 `[deploy-leg]` 单，逐条核注释里有没有那句清零语；有 ⇒ 违规并具名 | `0` 一致 / `1` 违规 / `3` 无凭据或读不到（**判不了，不许读成 0**） |
| `check-static` | **离线**结构判据：动作脚本里每一个 `--reason` 实参都必须在 gh 的取值枚举内（枚举现取 `gh issue close --help`，取不到才退回内置清单），且清零路径必须**有具名失败出口** | `0` 合规 / `1` 违规 / `3` 判不了 |

`show-ledger` 打印存量清单（`--json` 为机器读数），台账 = `tests/unit_ci_workflows/deploy_leg_close_claims_ledger.json`。

## 为什么是「查开放单」而不是「查全部单」

清零声明**只可能**出现在它自己刚开的单上，而「声明了却没关」的形态**必然**表现为
「单仍 OPEN 且带着声明」⇒ 只查开放单就精确覆盖该形态，且 API 面有界（不翻历史）。
反过来，一条 CLOSED 的单**不构成**任何怀疑（可能是人工关的 / 可能是修好之后关的）
⇒ **不**对它判红（本判据不为历史背书，只裁「当下自称已关却没关」）。

## 边界（照实登记）

- **判不了「谁该被关」**：本判据只判「声明与状态矛盾」，**不**主张「所有开放的 `[deploy-leg]` 都该关」。
- **`--limit` 有界**：开放单超过 `MAX_ISSUES` ⇒ 判 `3`（**判不了**），不假装查全了。
- **不写任何远端状态**：全程只读（`gh issue list` / `gh issue close --help`）；关单动作在动作脚本里。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
#: 动作脚本（**唯一**改远端的那一侧；本脚本只读它）。
ACTION_SCRIPT = REPO_ROOT / "scripts" / "deploy_leg_failure_reaction.sh"
#: 存量台账（冻结快照：**只许缩短**；条数由判据侧同值常量把守）。
LEDGER = REPO_ROOT / "tests" / "unit_ci_workflows" / "deploy_leg_close_claims_ledger.json"

#: 值守单一族的**严格**标题前缀（`[deploy-leg·假红]` 那类同族子标题**不在**本判据射程内）。
TITLE_PREFIX = "[deploy-leg] "
#: 清零声明句的锚点。**取最短可辨识片段**：动作脚本里 `自动关闭值守单 #N`（宣称已关）与
#: `**未关**值守单 #N` / `关单失败` 那两条出声句都含「值守单」⇒ 锚更长反而会把出声句误认成声明
#: （本包实测）。⇒ 锚 = `自动关闭`，并由判据钉住「失败出口的文案**不得**含它」。
CLAIM_MARKER = "自动关闭"
#: gh 的取值枚举（**现取优先**；`gh` 不在场 / 读不到帮助时退回这一份，并在读数里声明）。
FALLBACK_REASONS = ("completed", "not planned", "duplicate")
#: 枚举横幅的正则（`gh issue close --help` 的逐字形态：`{completed|not planned|duplicate}`）。
ENUM_RE = re.compile(r"\{([a-z |]+)\}")
#: 开放单取数上限：到顶 ⇒ 判「判不了」（不假装查全）。
MAX_ISSUES = 200
#: 无凭据 / 读不到时的**具名**读数（照 `tests/unit_ci_workflows/test_case_id_claims.py` 的 `TOKEN_ENVS` 口径）。
TOKEN_ENVS = ("GITHUB_TOKEN", "GH_TOKEN")
REPO_ENV = "GITHUB_REPOSITORY"


def _fail(msg: str) -> None:
    print(f"❌ {msg}")


def _cant(msg: str) -> None:
    print(f"⚠️ 判定不了：{msg}")


# ── 取值枚举（离线：读 `gh issue close --help`，不联网、不需要凭据）────────────────

def gh_reason_enum(gh: str = "gh") -> tuple[list[str], str]:
    """gh 接受的 `--reason` 取值 + 来源读数（`("gh 现取", …)` / `("内置清单", …)`）。"""
    exe = shutil.which(gh) or ""
    if exe:
        try:
            out = subprocess.run([exe, "issue", "close", "--help"], capture_output=True,
                                 text=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            out = None
        if out is not None and out.returncode == 0:
            text = out.stdout + out.stderr
            for line in text.splitlines():
                if "--reason" not in line:
                    continue
                m = ENUM_RE.search(line)
                if m:
                    values = [v.strip() for v in m.group(1).split("|") if v.strip()]
                    # 保序去重（`{completed|not planned|duplicate}` → 三项）
                    seen: list[str] = []
                    for v in values:
                        if v not in seen:
                            seen.append(v)
                    return seen, "gh issue close --help 现取"
    return list(FALLBACK_REASONS), "内置清单（gh 不在场 / 读不到帮助）"


# ── 结构判据（纯离线）──────────────────────────────────────────────────────────

def action_reason_values(text: str) -> list[str]:
    """动作脚本里 `--reason` 的**实参取值**（`"$var"` 记为变量名 —— 由调用方解析定值）。"""
    text = _strip_comments(text)
    out: list[str] = []
    for m in re.finditer(r"--reason[ \t]+(\S+)", text):
        raw = m.group(1)
        if raw.startswith('"$') and raw.endswith('"'):
            out.append(raw[2:-1])
        elif raw.startswith('$'):
            out.append(raw[1:])
        else:
            out.append(raw.strip('"\''))
    return out


def _strip_comments(text: str) -> str:
    """去掉整行注释（`#` 起头）—— 注释里**引用**坏取值不算违规（本仓反「引用即实例」的既有口径）。"""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def _parse_string_list(items: str) -> list[str]:
    """把「shell 字符串字面量序列」拆成逐个取值（`"not planned" 'a b'` ⇒ `["not planned", "a b"]`）。

    ⚠️ **手写扫描，不用「引号定界捕获组的正则」**：那种「按引号扫原文取值」的口径会被注释 /
    docstring 里的引号喂中（类级守卫 = `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py`
    的 RULE_QUOTE，**台账只许缩短、不许为新命中加条目**）。这里的输入是**已在 shell 语法里
    的**字面量序列（不是源代码），所以按字符逐个走、遇引号开闭 + 认反斜杠转义即可。
    """
    out: list[str] = []
    i = 0
    while i < len(items):
        ch = items[i]
        if ch not in "\"'":
            i += 1
            continue
        i += 1
        buf: list[str] = []
        while i < len(items) and items[i] != ch:
            if items[i] == "\\" and i + 1 < len(items):
                i += 1
            buf.append(items[i])
            i += 1
        if i >= len(items):
            break               # 引号没闭合（畸形输入）⇒ 丢掉这一段，不抛异常（判据会因此判红，不静默）
        i += 1                  # 吃掉收尾引号
        value = "".join(buf)
        if "\n" not in value:
            out.append(value)
    return out


def assignment_values(text: str, var: str) -> list[str]:
    """`var=…`（标量或**数组**）的取值集合 —— 两种形态都收：

    * `var="literal"` / `var=literal`（取到行尾）；
    * `var=("literal" …)`（bash 数组，**跨行**；取值含空格时这是唯一能无歧义表达清单的形态）。

    ⚠️ 取值**本身可能带空格**（`not planned`），所以**不能**按空白切词、也**不能**用 `tr` 当分隔符
    （`tr` 是逐字符映射 ⇒ `tr ' ' '\\n'` 会把 `not planned` 切成两行；本包实测踩过）。
    """
    source = _strip_comments(text)
    m = re.search(rf'^[ \t]*(?:declare[ \t]+-a[ \t]+)?{re.escape(var)}=\(', source, re.M)
    if m:
        start = m.end() - 1
        end = source.find(")", start)
        return _parse_string_list(source[start + 1:end if end != -1 else len(source)])
    m = re.search(rf'^[ \t]*(?:local[ \t]+)?{re.escape(var)}=(".*"|[^\n]*)', source, re.M)
    if not m:
        # ⚠️ bash 惯用形态 `local a="$1" b="$2" close_reason=""`（**多个赋值挤在一行**）：
        #    `local` 与目标变量之间还有别的 `名=值` 对 ⇒ 上面的锚接不到它（本包实测：
        #    「解不出定值」把合法脚本误判成违规）。这里按 `名=值` 逐对扫，取目标变量的那一对。
        for line in source.splitlines():
            if not re.match(r"^[ \t]*(local|declare)[ \t]", line):
                continue
            pair = re.search(rf'(?:^|[ \t]){re.escape(var)}=(".*"|[^ \t]*)', line)
            if pair:
                m = pair
                break
    if not m:
        return []
    raw = m.group(1).strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return [raw[1:-1]]
    return [raw.strip('"\'')]


def guard_block(source: str, var: str) -> str:
    """`var` 的 **fail-closed 闸门**正文（`case " ${ENUM[*]} " in` 块；没有 ⇒ 空串）。

    ⚠️ 锚在**固定形态**上：`case " ${<清单变量>[*]} " in` —— 清单是数组、取值可能含空格，
    所以唯一无歧义的「整值匹配」写法就是这个（`*" $var "*`）。改形态 ⇒ 这里读空 ⇒ 判据红
    （宁可判红也不许静默放过：`tests/unit_ci_workflows/test_deploy_leg_failure_reaction.py`
    有一条注入式用例专测「闸门被摘掉 ⇒ 判红」）。
    """
    m = re.search(r'case[ \t]+" \$\{(\w+)\[\*\]\} "', source)
    if not m:
        return ""
    start = source.find("esac", m.end())
    block = source[m.start():start if start != -1 else len(source)]
    # ⚠️ 认的是**那个匹配臂**（`*" $var "*`），不是「块里提到过 $var」：块尾的 `::warning::`
    #    里也会引用同一个变量 ⇒ 只看「提到」会把「臂被摘掉」判成「闸门还在」（本包实测）。
    return block if f'*" ${var} "*' in block else ""


def static_problems(text: str, allowed: list[str]) -> list[str]:
    """结构判据本体（**纯函数**：给定脚本正文与枚举，返回违规清单）。"""
    problems: list[str] = []
    source = _strip_comments(text)
    for value in action_reason_values(text):
        if value in allowed:
            continue
        # 变量实参 ⇒ 解析它的**全部赋值出口**（标量 / 数组 / 常量引用），逐个核；
        # 解不出来 = 判不了 ⇒ 按违规计（fail-closed）。
        resolved = assignment_values(text, value)
        if not resolved:
            problems.append(
                f"`--reason ${value}`：解不出定值（既不是枚举字面量，也没有 `{value}=…` 赋值）"
                f" ⇒ fail-closed 判违规（枚举现取 = {allowed}）"
            )
            continue
        # 显式 fail-closed 闸门：某条出口把非法取值拦在调用之前并具名出声 ⇒ 它**不是**违规出口。
        guarded = bool(guard_block(source, value))
        if "" in resolved:
            if guarded:
                resolved = [v for v in resolved if v]
            else:
                problems.append(
                    f"`--reason ${value}` 存在**空取值**出口且没有 fail-closed 闸门 ⇒ gh 会拒绝该调用"
                    f"（枚举 = {allowed}）"
                )
        bad = sorted({v for v in resolved if v and v not in allowed})
        if bad:
            problems.append(
                f"`--reason ${value}` 的赋值集里含**枚举外取值** `{bad}`（现取赋值 = {sorted(set(resolved))}，"
                f"枚举 = {allowed}）"
            )
    # 清零路径必须**有具名失败出口**：既不许 `|| :` 吞掉 close 的 rc，也不许无条件宣称已关。
    if "issue close" in _strip_comments(text):
        if not re.search(r"if[ \t]+ghc[ \t]+issue[ \t]+close", text):
            problems.append(
                "动作脚本的关单调用没有 `if ghc issue close …` 形态 ⇒ 失败不再有承接面"
                "（判据 2：不许静默）"
            )
        if re.search(r"ghc[ \t]+issue[ \t]+close[^\n]*\|\|[ \t]*:", text):
            problems.append("动作脚本的关单调用带 `|| :` ⇒ 失败被咽掉（判据 2：不许静默）")
    return problems


# ── 记录判据（需要 GitHub 只读 API / 凭据）──────────────────────────────────────

def token_from_env(env: dict) -> str:
    for name in TOKEN_ENVS:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return ""


def repo_from_env(env: dict) -> str:
    return (env.get(REPO_ENV) or "").strip()


def claim_comments(comments: list) -> list[dict]:
    """注释里带清零声明句的那些（只读 `body`；形状不认的元素按「没有声明」计 —— 漏判只会漏一个对象）。"""
    out = []
    for c in comments or []:
        if isinstance(c, dict) and CLAIM_MARKER in str(c.get("body") or ""):
            out.append({"author": str((c.get("author") or {}).get("login") or ""),
                        "createdAt": str(c.get("createdAt") or "")})
    return out


def claim_violations(issues: list) -> list[dict]:
    """**纯函数**：给定 issues（含 `state` / `comments`），返回「声明了却没关」的具名清单。"""
    bad = []
    for it in issues or []:
        if not isinstance(it, dict):
            continue
        claims = claim_comments(it.get("comments"))
        if not claims:
            continue
        state = str(it.get("state") or "").upper()
        if state == "CLOSED":
            continue
        bad.append({"number": it.get("number"), "state": state or "（未知）",
                    "title": str(it.get("title") or ""), "claims": claims})
    return bad


def _gh_json(gh: str, args: list[str], token: str, repo: str) -> tuple[object | None, str]:
    env = dict(os.environ)
    env["GH_TOKEN"] = token
    cmd = [gh, *args]
    if repo:
        cmd += ["--repo", repo]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"`gh {' '.join(args)}` 起不来：{exc}"
    if proc.returncode != 0:
        return None, f"`gh {' '.join(args)}` rc={proc.returncode}：{(proc.stderr or proc.stdout).strip()[:300]}"
    try:
        return json.loads(proc.stdout or "null"), ""
    except json.JSONDecodeError as exc:
        return None, f"`gh {' '.join(args)}` 的输出不是 JSON：{exc}"


def check_claims(gh: str = "gh", env: dict | None = None) -> int:
    """三态：`0` 一致 / `1` 违规（具名） / `3` 判不了。"""
    env = os.environ if env is None else env
    token = token_from_env(env)
    repo = repo_from_env(env)
    if not token:
        _cant(f"没有 API 凭据（环境变量 {'/'.join(TOKEN_ENVS)} 都为空）⇒ 读不到 `[deploy-leg]` 单的"
              f"注释面 —— **这不是「声明与状态一致」**")
        return 3
    issues, err = _gh_json(gh, ["issue", "list", "--state", "open", "--limit", str(MAX_ISSUES),
                                "--search", f"{TITLE_PREFIX.strip()} in:title",
                                "--json", "number,title,state,comments"], token, repo)
    if err or not isinstance(issues, list):
        _cant(f"列开放单失败（{err or '响应不是数组'}）⇒ 清零声明面**这一轮没判**")
        return 3
    if len(issues) >= MAX_ISSUES:
        _cant(f"开放单数达到取数上限 {MAX_ISSUES} ⇒ 可能还有下一页，覆盖面不完整")
        return 3
    scoped = [i for i in issues if str(i.get("title") or "").startswith(TITLE_PREFIX)]
    bad = claim_violations(scoped)
    total_claims = sum(1 for i in scoped if claim_comments(i.get("comments")))
    if not bad:
        print(f"✅ 清零声明与单据状态一致：开放 `{TITLE_PREFIX.strip()}` 单 {len(scoped)} 张"
              f"（其中 {total_claims} 张带清零声明；`{CLAIM_MARKER}` 出现在**开放**单上的：0 张）")
        return 0
    _fail(f"清零注释宣称「自动关闭」，而单**没有**关（{len(bad)} 张）—— 假绿（issue #7075）：")
    for b in bad:
        first = b["claims"][0]
        _fail(f"  #{b['number']} state={b['state']} «{b['title'][:60]}»"
              f" · 声明 {len(b['claims'])} 条，最早 {first['createdAt']}"
              f"；复算：`gh issue view {b['number']} --json state -q .state`")
    return 1


def check_static(script: Path = ACTION_SCRIPT, gh: str = "gh") -> int:
    """三态：`0` 合规 / `1` 违规 / `3` 判不了（脚本读不到 / 枚举取不到）。"""
    if not script.is_file():
        _cant(f"动作脚本不在场（{script}）⇒ 结构判据没有对象")
        return 3
    allowed, source = gh_reason_enum(gh)
    if not allowed:
        _cant("取不到 gh 的 `--reason` 取值枚举 ⇒ 结构判据没有对照面")
        return 3
    problems = static_problems(script.read_text(encoding="utf-8"), allowed)
    if problems:
        _fail(f"关单取值 / 静默面违规（{len(problems)} 条；枚举来源 = {source}）：")
        for p in problems:
            _fail(f"  {p}")
        return 1
    print(f"✅ 关单取值全在枚举内（来源 = {source}；枚举 = {allowed}）且清零路径有具名失败出口")
    return 0


# ── 判据 4（issue #9056）：「异常关闭 `[deploy-leg]` 单」必须带「本次真的发生了部署」的自证 ──
# 病（现场 run 45010592767，`schedule`）：`Skip if already built` 命中 ⇒ `Deploy to SWAS` 整段
# **skipped**，而 **job / run 结论 = success** ⇒ 清零判据「该腿下一次 `conclusion=success`」被
# **一次没部署的空转 run** 满足，而线上仍是旧镜像。⇒ 本判据判两件事，两件都会红：
#   ① **静态结构**：动作脚本里**每一个** `ghc issue close` 调用，都必须落在带了
#      「自证调用 + `if ! … ; then return …` 拒绝分支」的函数里，且脚本里有具名读数
#      `skip 非 deployed`；实现体必须把 `DEPLOY_EXECUTED=1` 当**唯一**放行依据（不许只看 rc）。
#   ② **行为夹具**（这条才是「skip 不许冒充 deployed」的真正判别力）：拿两份 jobs 语料跑实现体 ——
#      部署步 `success` ⇒ rc 0 + `DEPLOY_EXECUTED=1`；部署步 `skipped` ⇒ rc 1 + `DEPLOY_EXECUTED=0`。
#      静态读文本分不清「`skipped` 出现在匹配里」与「`skipped` 被当成已部署」，所以必须真跑。
# 三态：`0` 合规 / `1` 违规（具名） / `3` 判不了（动作脚本或实现体不在场 / 夹具跑不起来）。
ATTEST_IMPL = REPO_ROOT / ".github" / "scripts" / "deploy_leg_deploy_attest.py"
#: 关单前置的**具名读数**（调用方必须真的打出来 —— 否则「拒绝关单」在日志里不可见）。
SKIP_NOT_DEPLOYED = "skip 非 deployed"
#: 自证调用面的两种形态（助手函数名 / 实现体文件名）。
ATTEST_CALL_HINTS = ("deploy_attested", "deploy_leg_deploy_attest")
#: 助手函数必须出现的**强度**锚点：只有 `DEPLOY_EXECUTED=1` 才放行（rc=0 单独不算）。
ATTEST_PASS_MARK = "DEPLOY_EXECUTED=1"


def shell_functions(text: str) -> dict[str, tuple[int, int]]:
    """bash **顶层**函数 → `(起行, 止行)`（1-based，`name() {` … 首个列首 `}`）。

    ⚠️ 只用手写扫描 + **不含引号捕获组**的正则：本仓类级守卫
    `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py` 的 RULE_QUOTE 禁止
    「按引号扫源码原文取值」的形态（那种写法会被注释/字符串里的引号喂中）。
    """
    out: dict[str, tuple[int, int]] = {}
    lines = text.splitlines()
    start_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)[ \t]*\{")
    name, start = "", 0
    for no, line in enumerate(lines, 1):
        if not name:
            m = start_re.match(line)
            if m:
                name, start = m.group(1), no
            continue
        if line.rstrip() == "}":
            out[name] = (start, no)
            name = ""
    if name:                                   # 花括号没闭合：按到文件尾算（fail-closed 由调用方判）
        out[name] = (start, len(lines))
    return out


def _attest_gate_is_wired(body: str) -> bool:
    """函数体里是否有「自证不成立 ⇒ 提前 return」的分支（单行守卫或短块两种形态都收）。"""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        if not any(h in line for h in ATTEST_CALL_HINTS):
            continue
        if "!" not in line:
            continue
        window = lines[i:i + 4]
        if any("return" in w and not w.lstrip().startswith("#") for w in window):
            return True
    return False


def skip_close_problems(text: str) -> list[str]:
    """**纯函数**：给定动作脚本正文，返回「关单路径漏带部署自证」的违规清单（issue #9056）。"""
    problems: list[str] = []
    funcs = shell_functions(text)
    lines = text.splitlines()
    closes = [(no, line) for no, line in enumerate(lines, 1)
              if "issue close" in line and not line.lstrip().startswith("#")]
    #: 🔴 豁免面（**唯一**一条，且是语义上不成立的那类）：以 `duplicate` 关单 = 关掉**重复**单、
    #: 保留主单（`converge_duplicate_issues`）⇒ 它**不**宣称「已收敛/已部署」，因此不要求部署自证。
    #: 除它以外的每一条关闭路径都必须自证（宁可判红，也不许为「省一条豁免」把收敛声明面放宽）。
    exempt = "duplicate"
    scoped = [(no, line) for no, line in closes if f"--reason {exempt}" not in line]
    if not scoped:
        return [f"动作脚本里找不到**会宣称收敛**的 `ghc issue close` 调用（只有 `--reason {exempt}` 的重复单收敛）"
                " ⇒ 判据对象没了（fail-closed）"]
    for no, line in closes:
        if f"--reason {exempt}" in line:
            continue
        owner = ""
        for name, (start, end) in funcs.items():
            if start <= no <= end:
                owner = name
                break
        if not owner:
            problems.append(
                f"第 {no} 行的 `issue close` 不在任何顶层函数里 ⇒ 无法判定它带没带自证（fail-closed）"
            )
            continue
        start, end = funcs[owner]
        body = "\n".join(lines[start - 1:end])
        if not any(h in body for h in ATTEST_CALL_HINTS):
            problems.append(
                f"`{owner}` 会关 `[deploy-leg]` 单，但没有「本次真的发生了部署」的自证调用"
                f"（{ATTEST_CALL_HINTS[0]} / {ATTEST_CALL_HINTS[1]}.py）⇒ skip 空转可冒充已部署（issue #9056）"
            )
            continue
        if not _attest_gate_is_wired(body):
            problems.append(
                f"`{owner}` 调了自证，但没有「自证不成立 ⇒ **不关单**」的分支"
                f"（需要 `if ! {ATTEST_CALL_HINTS[0]} …; then return …`）"
            )
    helper = funcs.get(ATTEST_CALL_HINTS[0])
    if not helper:
        problems.append(
            f"找不到自证助手 `{ATTEST_CALL_HINTS[0]}()` ⇒ 关单前的自证没有承载面"
        )
    else:
        helper_body = "\n".join(lines[helper[0] - 1:helper[1]])
        if ATTEST_PASS_MARK not in helper_body:
            problems.append(
                f"`{ATTEST_CALL_HINTS[0]}` 没有把 `{ATTEST_PASS_MARK}` 当放行依据"
                f"（只看 rc 时，实现体把 skip 判成 0 也照样关单）"
            )
        if "return 1" not in helper_body:
            problems.append(
                f"`{ATTEST_CALL_HINTS[0]}` 没有失败出口（`return 1`）⇒ 自证不成立时无从拒绝关单"
            )
    if SKIP_NOT_DEPLOYED not in text:
        problems.append(
            f"动作脚本里没有具名读数 `{SKIP_NOT_DEPLOYED}` ⇒ 拒绝关单在日志里不可见"
            "（读者会以为它没跑，而不是「被自证挡住了」）"
        )
    return problems


def attest_verdict(attest: Path, conclusion: str, workdir: Path) -> tuple[int, str]:
    """跑实现体的 CLI 拿 `(rc, 输出)`（离线：`ATTEST_JOBS_FILE` 夹具 ⇒ **一次 gh 都不调**）。"""
    jobs = {"jobs": [{"name": "build-and-deploy", "steps": [
        {"name": "Skip if already built (schedule reconcile)", "conclusion": "success"},
        {"name": "Deploy to SWAS (测试环境)", "conclusion": conclusion}]}]}
    fixture = workdir / f"jobs-{conclusion or 'none'}.json"
    workdir.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in TOKEN_ENVS}
    env["ATTEST_JOBS_FILE"] = str(fixture)
    try:
        proc = subprocess.run([sys.executable, str(attest), "--run-id", "0"],
                              capture_output=True, text=True, timeout=120, env=env,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, f"实现体起不来：{exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def other_close_paths(script: Path = ACTION_SCRIPT) -> list[str]:
    """**类级**：任何**别的**脚本里也出现「关 `[deploy-leg]` 单」⇒ 它也得带同一条自证。

    扫描面 = `scripts/**/*.sh` 与 `.github/scripts/**/*.sh`（**关单动作在本仓只由 bash 发起**；
    Python 侧唯一的 `gh issue close` 文本在**本判据自己的**文档里 ⇒ 扫 `.py` 只会命中自己）。
    边界（照实登记）：若将来出现 shell 之外的第二条关闭路径，本函数看不见 ⇒ 那条由评审兜。
    """
    problems: list[str] = []
    roots = [REPO_ROOT / "scripts", REPO_ROOT / ".github" / "scripts"]
    for root in roots:
        for path in sorted(root.glob("*.sh")):
            if path.resolve() == script.resolve():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "issue close" not in _strip_comments(text):
                continue
            if "[deploy-leg]" not in text and "LEG_TITLE_PREFIX" not in text:
                continue
            problems.append(
                f"`{path.relative_to(REPO_ROOT)}` 也关 `[deploy-leg]` 单，但不在自证面里 ⇒ 第二条关闭路径"
                f"（类级：新关闭面必须同批接自证，issue #9056）"
            )
    return problems


def check_skip_close(script: Path = ACTION_SCRIPT, attest: Path = ATTEST_IMPL) -> int:
    """三态：`0` 合规 / `1` 违规（具名） / `3` 判不了（脚本或实现体不在场）。"""
    if not script.is_file():
        _cant(f"动作脚本不在场（{script}）⇒ 「关单前自证」没有判据对象")
        return 3
    if not attest.is_file():
        _cant(f"自证实现体不在场（{attest}）⇒ 判不了「skip 会不会冒充 deployed」")
        return 3
    problems = skip_close_problems(script.read_text(encoding="utf-8"))
    problems += other_close_paths(script)
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        ok_rc, ok_out = attest_verdict(attest, "success", Path(td))
        skip_rc, skip_out = attest_verdict(attest, "skipped", Path(td))
    if ok_rc != 0 or ATTEST_PASS_MARK not in ok_out:
        problems.append(
            f"行为夹具：部署步 `success` 应判已部署（rc=0 且含 `{ATTEST_PASS_MARK}`），"
            f"现取 rc={ok_rc} ⇒ 自证在「真部署」上也会拒绝关单（会把值守单永久挂住）"
        )
    if skip_rc != 1 or "DEPLOY_EXECUTED=0" not in skip_out:
        problems.append(
            f"行为夹具：部署步 `skipped` 必须判**未部署**（rc=1 且含 `DEPLOY_EXECUTED=0`），"
            f"现取 rc={skip_rc} ⇒ **skip 冒充 deployed**（issue #9056 本单要治的形态）"
        )
    if problems:
        _fail(f"关单自证面违规（{len(problems)} 条）：")
        for p in problems:
            _fail(f"  {p}")
        return 1
    print(f"✅ 每条关闭路径都带部署自证（{SKIP_NOT_DEPLOYED}），且实现体把 "
          f"`skipped` 判成未部署、`success` 判成已部署（行为夹具 rc=0/1 双向）")
    return 0


def show_ledger(as_json: bool = False) -> int:
    if not LEDGER.is_file():
        _cant(f"存量台账不在场（{LEDGER}）")
        return 3
    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    entries = data.get("entries") or []
    print(f"存量（{data.get('kind', '?')}）：{len(entries)} 条（只许缩短）")
    for e in entries:
        print(f"  #{e.get('number')} {e.get('state')} —— {e.get('reason', '')[:100]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="[deploy-leg] 清零声明的类级元守卫（issue #7075，只读）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-claims", help="声明与状态一致性（需只读凭据；无凭据 ⇒ rc=3）")
    sub.add_parser("check-static", help="离线结构判据（取值枚举 + 具名失败出口）")
    sub.add_parser("check-skip-close",
                   help="关单前的「本次真的发生了部署」自证（静态结构 + 行为夹具，issue #9056）")
    p = sub.add_parser("show-ledger", help="打印存量清单")
    p.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    if ns.cmd == "check-claims":
        return check_claims()
    if ns.cmd == "check-static":
        return check_static()
    if ns.cmd == "check-skip-close":
        return check_skip_close()
    return show_ledger(ns.json)


if __name__ == "__main__":
    sys.exit(main())
