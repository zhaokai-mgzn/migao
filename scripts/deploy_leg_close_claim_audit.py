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
    """把「shell 字符串字面量序列」拆成逐个取值（`"not planned" 'a b'` ⇒ `["not planned", "a b"]`）。"""
    out: list[str] = []
    for m in re.finditer(r'"([^"]*)"|\'([^\']*)\'', items):
        out.append(m.group(1) if m.group(1) is not None else m.group(2))
    return [v for v in out if "\n" not in v]


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
              f"（其中 {total_claims} 张带清零声明，均确为 CLOSED 之外的**零**张）")
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
    p = sub.add_parser("show-ledger", help="打印存量清单")
    p.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    if ns.cmd == "check-claims":
        return check_claims()
    if ns.cmd == "check-static":
        return check_static()
    return show_ledger(ns.json)


if __name__ == "__main__":
    sys.exit(main())
