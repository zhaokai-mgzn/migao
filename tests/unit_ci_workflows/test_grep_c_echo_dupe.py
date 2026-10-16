# case_ids: MC-109
"""`grep -c` 配 `|| echo "0"` 会捕获成**两行** ⇒ `[ … -gt 0 ]` 报 `integer expression expected`
（issue #7022）。

## 病（真机，2026-10-16；不是推断）

PR #7012 的 `Clear stale needs-changes label` **每次都报 `success`**，而那个过期标签
**从来没被摘掉**过。job 日志逐字：

```
/home/runner/work/_temp/<uuid>.sh: line 2: [: 0
0: integer expression expected
✅ 无需清除（标签不存在）
```

⚠️ 最后那行是关键：它把「判据崩了」说成了「标签不存在」—— **绿着但没干活**。

根因（`.github/workflows/pr-check.yml` 的 `Remove review/needs-changes` 步）：

```bash
HAS_LABEL=$(gh pr view "$PR_NUMBER" --json labels --jq '.labels[].name' 2>/dev/null \
            | grep -c 'review/needs-changes' || echo "0")
if [ "$HAS_LABEL" -gt 0 ]; then … else echo "✅ 无需清除（标签不存在）"; fi
```

`grep -c` 在**找不到**时**已经打印 `0`** 且**退出码 1** ⇒ `|| echo "0"` **再追加一行**
⇒ `HAS_LABEL` 是 `$'0\\n0'`（两行），不是 `0`。于是 `[ "$HAS_LABEL" -gt 0 ]` 在**解析时**就报错，
`if` 走 else 分支 ⇒ **永远"标签不存在"** ⇒ 永不摘标签。

**为什么潜伏至今**：这条缺陷**不会**让 job 变红 —— 报错的那条 `[` 在两个命令的 `set -e`
覆盖之外，且处在 `if` 的条件上下文里（条件里的失败**不**触发 `-e`）⇒ 只能靠
「标签**该消失**却没消失」观察到。**「绿着但没干活」是本仓点名的空跑形态。**

## 本文件锁什么（两条判据，各有**能单独变红**的注入点）

| # | 判据 | 取法（结构化，**不读散文**） | 拒绝什么 | 怎么红 |
|---|---|---|---|---|
| A | **工作区零残留**：`.github/workflows/**` 里不得再出现「`grep -c` 输入 + 其后 200 字符内 `\\|\\| echo`」的形态 | YAML **按行**取 `run:` 正文（不需要解析出 YAML 标量；逐行看得见就够），剥引号与注释后正则匹配 | 同族缺陷复发（新增一处即红） | 把任一处的 `\\|\\| true` 改回 `\\|\\| echo "0"` ⇒ 当场红并**具名**报出 `文件:行` |
| B | **台账只许非增 + 不许清空**：`grep_c_echo_instances_ledger.json` 记录**已修**的实例，条数 ≤ 冻结上限且非空 | 台账 JSON + 本文件的 `LEDGER_ENTRIES_FROZEN` | ① 台账被清空「消红」② 台账条目**涨**到冻结上限之上 | 删光台账条目 ⇒ 红；往台账里塞第 3 条 ⇒ 红 |

判据 A 的**判别力自证**（③）在内存里对四种形态各自判红/放行，含**两个逐字取自真语料的
正向夹具**（`case-draft` 的 `grep -cP … || echo "0"` 与 `pr-check` 的**带单引号**那种）
与**四个负向夹具**（仓内既有的正确写法 `|| true`、引号内提及、无回退的裸 `grep -c`）。
没有这一条的话，「扫不到任何东西」与「扫了但没违规」**无法区分** —— 那正是空跑形态。

## 为什么判据 A 值得存在（而不是"改完两处就算了"）

同一形态在本仓**咬过两次**且**同一晚**：`pr-check` 的标签自愈（本单）与 `case-draft` 的
`HAS_TRUTH`（同一个 bug，只是下游恰好没用 `-gt`）。**能落成机械守卫的那一半就不要靠纪律**：
`grep -c` 的退出码语义是**稳定**的（无命中 ⇒ 打印 `0` + rc 1），所以这个形态**可以**被静态扫掉。

## 边界（照实登记，§19.1）

- **射程只到 `.github/workflows/**`**：全仓 shell 脚本现取**零**同形态命中
  （`deploy/scripts/*-h5-publish-ci.sh` 里那三处 `grep -m1 … || echo '(缺 TARGET 行)'` 是
  **另一回事** —— `-m1` **不带 `-c`**，无命中时**不打印数字**，`|| echo` 是**有意**的兜底文案），
  故**不**扫脚本面（扫了就要处理 `-m1` / `-l` 等语义分支，收益为零而假阳性风险非零）。
- **不判"下游有没有把它当数字用"**：判据只认「`grep -c` + `|| echo`」这个**形态**本身。
  理由：形态已经**无条件**是错的 —— `grep -c` 总是打印数字，`|| echo` 只会**多加一行**；
  两行值**无论**下游做什么（算术比较 / 字符串比较 / 原样透传）都是坏值。
  ⇒ 不需要（也无法可靠地）做「下游用法」分析。
- **不扫引号内的提及**：`echo "grep -c a || echo 0"` 这类**说明文字**不算违规（实测负向夹具 0 命中）
  —— 与 `.github/growth_gate.py::_prose_spans` 同族口径（**注释/字符串里的例子不是代码**）。
- 本判据**不改任何门禁的通过条件、不新增豁免**。

## 判据 = 本文件；用例 = `MC-109`
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
LEDGER = pathlib.Path(__file__).resolve().parent / "grep_c_echo_instances_ledger.json"

# 台账条数的**冻结上限**（「只许缩短」的机械判据：写在**本文件**里 ⇒ 数据文件改不动它）
LEDGER_ENTRIES_FROZEN = 2

# `grep -c`（可带 `-r`/`-P` 等前置短选项与 `-cP` 这种合并形态）
GREP_C = re.compile(r"\bgrep\s+(?:-[A-Za-z]+\s+)*-c(?:[A-Za-z]+)?\b")
# `|| echo`（这一族缺陷的判别特征）
OR_ECHO = re.compile(r"\|\|\s*echo\b")
# 向后看多远找 `|| echo`
WINDOW = 200


def _unquoted(text: str) -> str:
    """把引号内的内容与**行注释**抹成等长空格，返回**同长度**的骨架。

    ⇒ 引号里的「提及」（`echo "grep -c a || echo 0"`）不会命中；
    而**引号外的** `||`（`… | grep -c 'x' || echo "0"` —— `'x'` 被抹掉、`||` 保留）照样命中。
    比"先算转义再剥引号"简单得多，且对本形态足够：
    `grep -c` 的判别特征（`||` 在引号**外**）不受引号内单引号字面量的影响。

    ⚠️ **行注释也必须抹掉**（`#` 起的 shell 注释）：本判据的修法注释里**逐字写了**
    「不要写成 `… | grep -c 'x' || echo "0"`」—— 不剥注释的话，这条**说明**会被当成违规实例，
    判据当场假红（**实测踩到**）。这与 `.github/growth_gate.py::_prose_spans` 处理弱断言、
    以及 issue #7007 里 `lucide-mock-closure-guard` 的同款坑是**同一条定式**：
    **凡是「扫描源码找形状」的工具，先剥注释再匹配 —— 注释里的例子不是代码。**

    剥法：引号内已抹成空格 ⇒ 骨架里第一个 `#` 必定是**引号外**的注释起点（shape 无需转义感知）。
    """
    out: list[str] = []
    i, quote = 0, ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                out.append("  ")
                i += 2
                continue
            if ch == quote:
                quote = ""
            out.append(" ")
        else:
            if ch in "\"'":
                quote = ch
                out.append(" ")
            else:
                out.append(ch)
        i += 1
    skeleton = "".join(out)
    # 剥行注释：引号内已抹成空格 ⇒ 第一个 `#` 就是引号外的注释起点
    hash_at = skeleton.find("#")
    if hash_at >= 0:
        skeleton = skeleton[:hash_at] + " " * (len(skeleton) - hash_at)
    return skeleton


def find_grep_c_echo_hits(text: str) -> list[dict]:
    """→ 命中清单 `[{line, snippet, raw}]`（**行号 1-based**）。"""
    hits: list[dict] = []
    for no, line in enumerate(text.split("\n"), 1):
        skeleton = _unquoted(line)
        for m in GREP_C.finditer(skeleton):
            if OR_ECHO.search(skeleton[m.end():m.end() + WINDOW]):
                hits.append({"line": no, "snippet": line.strip(), "raw": line})
                break
    return hits


def scan_workflows(directory: pathlib.Path = WORKFLOW_DIR) -> list[dict]:
    """扫全部 workflow。读不到文件 ⇒ 抛出（fail-closed：不允许退化成「零违规」）。"""
    if not directory.is_dir():
        raise ValueError(f"workflow 目录不存在：{directory}（fail-closed，不许当成「零违规」）")
    files = sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])
    if not files:
        raise ValueError(f"{directory} 下零个 workflow 文件（fail-closed，不许当成「零违规」）")
    out: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:  # pragma: no cover - 环境异常
            raise ValueError(f"无法读取 {f}（{e.__class__.__name__}）") from e
        for hit in find_grep_c_echo_hits(text):
            hit["path"] = str(f.relative_to(REPO_ROOT))
            out.append(hit)
    return out


def load_ledger(path: pathlib.Path = LEDGER) -> dict:
    if not path.is_file():
        raise ValueError(f"台账缺失：{path}（fail-closed）")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"台账损坏：{path}（{e.__class__.__name__}）") from e


# ────────────────────────────── 判据 A ──────────────────────────────

def test_workflows_have_no_grep_c_echo_instances():
    """判据 A：`.github/workflows/**` 里零残留（新增一处即红，具名报出）。"""
    hits = scan_workflows()
    assert hits == [], (
        "workflow 里出现「grep -c … || echo」形态（issue #7022）：\n"
        + "\n".join(f"  {h['path']}:{h['line']}  {h['snippet'][:110]}" for h in hits)
        + "\n\n修法：`grep -c` 本来就**总是**打印数字 ⇒ 把 `|| echo \"0\"` 换成 `|| true`"
        "（`set -e` 下 grep 无命中会返回 1，必须留一个回退）。"
    )


# ─────────────────────── 判据 A 的判别力自证 ───────────────────────

def test_detector_has_discriminating_power():
    """③ 判别力自证：四种形态在内存里各自判红/放行，且刀口对着**真语料**。"""
    # 正向：逐字取自真语料（case-draft 的 -cP 形态 / pr-check 的带单引号形态）
    positive = {
        "case-draft 原形态": 'HAS_TRUTH=$(echo "$BODY" | grep -cP "a|b" || echo "0")',
        "pr-check 原形态": "HAS_LABEL=$(gh pr view \"$P\" --json labels --jq '.labels[].name' | grep -c 'review/needs-changes' || echo \"0\")",
    }
    for name, text in positive.items():
        assert find_grep_c_echo_hits(text), f"正向夹具未命中（判别力失效）：{name}"

    # 负向：仓内既有的**正确**写法与四类不应命中的形态
    negative = {
        "已在用的 || true": 'X=$(printf "a\\n" | grep -c zzz || true)',
        "引号内的提及（说明文字）": 'echo "grep -c foo || echo 0"',
        "无回退的裸 grep -c": 'N=$(grep -c . "$f")',
        "grep -m1 + 兜底文案（不带 -c）": 'die "缺行：$(grep -m1 \'^T=\' <<<"$L" || echo \'(缺 T 行)\')"',
    }
    for name, text in negative.items():
        assert not find_grep_c_echo_hits(text), f"负向夹具被误判（假阳性）：{name}"


def test_scanner_is_not_vacuous():
    """语料下限 + fail-closed：读不到 workflow / 零文件 ⇒ 必须**出声**，不许静默变绿。"""
    files = [*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")]
    assert len(files) >= 20, f"workflow 语料过少（{len(files)}）—— 扫描面被收窄了？"
    # 注入一个不存在的目录 ⇒ 必须**抛**，而不是返回空清单（否则"没东西可判"会被读成绿）
    # ⚠️ 用 `pytest.raises` 而不是 `try/except: pass` —— 后者里的裸 `pass` 会被
    # `.github/growth_gate.py` 的弱断言扫描判为**弱断言形态**（`^\s*pass\s*$`，实测踩到一次）。
    with pytest.raises(ValueError, match="fail-closed"):
        scan_workflows(REPO_ROOT / "no-such-workflow-dir")


# ────────────────────────────── 判据 B ──────────────────────────────

def test_ledger_only_shrinks_and_is_never_emptied():
    """判据 B：台账记录**已修**的实例，条数 ≤ 冻结上限且非空。"""
    data = load_ledger()
    entries = data.get("instances")
    assert isinstance(entries, list), "台账缺 `instances` 列表"
    assert entries, "台账**不许清空**（清空不能消红 —— 它记录的是本缺陷的实例面）"
    assert len(entries) <= LEDGER_ENTRIES_FROZEN, (
        f"台账条目涨到 {len(entries)} > 冻结上限 {LEDGER_ENTRIES_FROZEN}："
        "新增条目 = 本形态又在仓库里出现了一次，应先修掉而不是登记"
    )
    # 每条必须四要素齐全（幽灵条目即红）
    for e in entries:
        for key in ("path", "line", "form", "fixed_to", "issue"):
            assert e.get(key) not in (None, ""), f"台账条目缺 `{key}`：{e}"
        assert e["issue"] == 7022, f"台账条目的 issue 不是本单：{e}"


def test_ledger_entry_paths_exist():
    """台账不许指向幽灵文件（否则「已修」是空话）。"""
    for e in load_ledger()["instances"]:
        p = REPO_ROOT / e["path"]
        assert p.is_file(), f"台账指向不存在的文件：{e['path']}"
