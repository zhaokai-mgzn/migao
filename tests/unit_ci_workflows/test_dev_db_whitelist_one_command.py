# case_ids: MC-092
r"""云 dev DB 白名单：**一条命令**（幂等 / 只追加 / fail-closed / 不泄漏）+ 起栈入口预检（issue #6789）。

## 病（症状与处置之间**没有机械连线**，且手工合并旧列表会误删他人 IP）

本机公网 IP 不在 RDS 白名单 ⇒ 本地起栈失败，第一现场却是 `admin-api` 的 7403 行 Spring 栈：

    Caused by: org.postgresql.util.PSQLException: 尝试连线已失败。
    Caused by: java.net.SocketTimeoutException: Connect timed out

而预设 §10 里本来就有这件事，形态是**三条手工命令 + 手工合并旧列表**（`ModifySecurityIps` 是**整体覆盖**语义
⇒ 手拼旧列表这一步就是「误删他人 IP」的入口）。2026-10-13 现场：`dev_local` 组堆了 **21 条**历次开发 IP
（那堆本身就是「同一动作反复做过很多次」的化石），本次用 `--ModifyMode Append` 追加到 **22** 条。

## 本文件判什么（全部用**桩**真跑脚本，零云资源写入）

| # | 判据 | 会怎么红 |
|---|---|---|
| 1 | **幂等**：IP 已在 `dev_local` ⇒ 正常模式 exit 0 且 `ModifySecurityIps` **调用次数 = 0** | 每次都调 Modify ⇒ 红 |
| 2 | **只追加**：不在列 + 显式 `--yes` ⇒ Modify 参数含 `--ModifyMode Append`、`--SecurityIps` **恰为新 IP**（不手拼旧列表），且**只有 `dev_local` 收到改动** | 退化成整体覆盖（传旧列表 / 用 `Overwrite`）或动了 `default` ⇒ 红 |
| 3 | **默认只诊断**：不在列且未给 `--yes` ⇒ 非零退出、**零** Modify 调用、文案点名处置命令 | 静默写云资源 / 静默成功 ⇒ 红 |
| 4 | **fail-closed**：`aliyun` 缺失 / Describe 失败 / Modify 失败 / 追加后回读读不到 / TCP 复测不可达 ⇒ **各自**非零退出 | 任一形态 exit 0 ⇒ 红 |
| 5 | **不泄漏**：桩 `.env` 里放**哨兵密码**，脚本全部输出（stdout+stderr，含失败路径）不得含它 | 打印凭据 ⇒ 红 |
| 6 | **`--check` 只读**：任何形态下都**不产生** Modify 调用；在列且可达 ⇒ exit 0、不在列 ⇒ 非零 | `--check` 偷偷写 / 恒 0 ⇒ 红 |
| 7b | **业务路由自检（起栈后）**：桩 dev 对 `(dashboard)` 组路由回 **404** ⇒ 输出含「`.next`」+ 可行动命令、非零退出、**没开始跑 spec**；可达 ⇒ 正常继续 | 泛化「产品大面积挂」⇒ 红 |
| 7 | **起栈入口预检（接线 + 时序）**：`scripts/ui_smoke_merchant.sh` 在启动 admin-api **之前** TCP 探 RDS；桩 `nc` 不可达 ⇒ wrapper **非零退出**、输出含 `dev-db-whitelist.sh`、**不含** `PSQLException`、且**没走到**起栈 | 预检被摘掉 / 挪到起栈之后 ⇒ 红 |
| 7c | **顺序判据的锚是「结构锚」**（issue #6802）：启动行 = `backend/admin-api` + `mvnw spring-boot:run` 的**代码行**（`LAUNCH_LINE_RE`），注释行不算；定位不到 ⇒ fail-closed 且**具名**（`ordering_verdict`）。负控：预检块**之前**插含「启动 admin-api」的注释 ⇒ **不变**；块后插代码 ⇒ 仍绿；正控：块整块移到启动行**之后** ⇒ 红且报「之后」；启动行被注释掉 ⇒ 红 | 退回 `text.find("启动 admin-api")`（文本首现）⇒ 注释负控红 |
| 8 | **判别力自证（注入式，实跑）**：`Append`→`Overwrite` / 删掉整段 `--ModifyMode` 参数 / 摘掉预检块 ⇒ 同名判据**当场红**；还原 ⇒ 绿；**只改注释** ⇒ 不红 | 判据恒绿（空断言）⇒ 红 |
| 9 | **类级元守卫**：① `--ModifyMode Append` 承载体**唯一**（只许 `scripts/dev-db-whitelist.sh` 一处）② 覆盖语义（`Overwrite`）禁入 ③ 空数组展开必须写 `${A[@]+"${A[@]}"}`（bash 3.2 + `set -u`，issue #6777）④ **同族位置锚**：`tests/unit_ci_workflows/test_*.py` 里「中文/注释级文案当结构位置」的形态必须逐条登记（判据 = `tests/unit_ci_workflows/test_cjk_position_anchor_guard.py`） | 再抄一份命令 / 引入覆盖语义 / 裸展开空数组 / 新写一处中文位置锚而不登记 ⇒ 红 |

## 边界（照实登记，§19.1）

- ⛔ **不真调 `aliyun`、不真改云资源**：`ALIYUN_BIN` / `NC_BIN` 全走桩；`--check` 的真跑读数见 PR body。
- ❌ **判不了**「真 RDS 上白名单到底写进去没有」（那要真云）；本文件钉的是**参数与分支语义**
  （只追加 / 不覆盖 / 失败出声），真语料绿证 = issue #6789 的一次实测（TaskId 713392864 / 21→22 条 / nc succeeded）。
- ❌ **预检只覆盖 `scripts/ui_smoke_merchant.sh`**（issue 判据写明的入口）；别的入口未接线（有意的最小射程）。
- ❌ `nc` 的桩是**行为桩**：按参数返回成功/失败，不建真 TCP 连接 ⇒ 钉的是「分支走对了」，不是「网络真心可达」。
- ❌ `_run_smoke` 只跑到预检为止（依赖准备 / 起栈 / spec 都不进射程），故不真装依赖、不起服务。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "scripts"
SCRIPT = SCRIPT_DIR / "dev-db-whitelist.sh"
SMOKE = SCRIPT_DIR / "ui_smoke_merchant.sh"

#: 本判据**枚举**的 shell 语料（射程**有意只到 `scripts/`**，不按它枚举全仓）。
#: ⇒ 按 `tests/unit_ci_workflows/guard_scope_ledger.json` 的出口②以 `kind=mentions` 入册
#: （`kind=scans` 的契约是「`GUARD_SCOPE` == 全语料普查 == 全仓」）；全仓 `*.sh` 的射程守卫 =
#: `tests/unit_ci_workflows/test_scripts_bash32_var_brace.py`。
#: ⚠️ 教训（本单 CI 实测）：**新增测试文件会进「扫语料 / 入册」这类类级判据的射程** ——
#: 挑本地验证集时不能只按自己文件名挑，要连同「会读到本文件」的守卫一起跑（同族先例 issue #6774）。
SHELL_CORPUS_GLOB = "*.sh"

#: 桩 `.env` 里的哨兵密码 —— 出现在任何输出里就是泄漏
SENTINEL_PW = "SENTINEL_PW_zz6789"
IP = "203.0.113.77"
DEFAULT_GROUP_IPS = "10.0.0.1/32,10.0.0.2/32"
DEV_LOCAL_OTHER = "198.51.100.5/32,198.51.100.6/32"
STUB_HOST = "pgm-bp1stub0000stub-pub.pg.rds.aliyuncs.com"

#: 起 admin-api 那一行的**结构锚**（issue #6802）：只认**代码行**里的「进 `backend/admin-api` + 跑 `mvnw spring-boot:run`」这一对特征。
#: ⛔ **不许**退回 `text.find("启动 admin-api")` —— 那是**文本首现**：`#6790` 的 ai-agent 配置块注释里有一句
#: 「⇒ 启动 admin-api 时**显式传**这两个变量」，比真正的启动行更靠前 ⇒ 判据判红，而报错把归因指成「顺序写错了」
#: （真因 = 注释里出现了一个词）。同族 = issue #5323「把原文当代码读」，本处形态是「把原文当**代码位置**读」。
LAUNCH_LINE_RE = re.compile(
    r'^[ \t]*\([ \t]*cd[ \t]+"[^"]*\bbackend/admin-api\b"[^\n]*\bmvnw[ \t]+spring-boot:run\b',
    re.MULTILINE,
)

#: 判据 7/8 的**注释负控**样本（issue #6802）：注释里逐字含「启动 admin-api」。
#: 它不是启动行（`#` 起行、无 `mvnw spring-boot:run`）⇒ 顺序判定必须**不受它影响**。
PRELAUNCH_DECOY_COMMENT = "# ⇒ 启动 admin-api 时显式传这两个变量（ai-agent 配置块现场，#6790）\n"

#: 预检块的两条 marker（**块边界的锚**；`find` 的**首现**语义在此是有意的 —— marker 只出现一次）。
PREFLIGHT_MARKER = "# ── 1.5 云 dev DB 预检"
STACK_MARKER = "# ── 2. 起栈"

#: Modify 调用台账行里记录「被改动的分组」
MODIFY_RE = re.compile(r"--DBInstanceIPArrayName (\S+)")
#: 空数组裸展开（bash 3.2 + `set -u` ⇒ unbound variable，issue #6777）
BARE_EMPTY_EXPANSION_RE = re.compile(r'(?<!\+)"\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}"')


# ── 纯函数：文本扫描（类级元守卫的判别力靠它们自己可测） ────────────────────────

def code_lines(text: str) -> str:
    """剥掉整行注释后的**代码面**（判据不许吃自己的说明文字）。"""
    return "\n".join(ln for ln in text.split("\n") if not ln.strip().startswith("#"))


def modify_modes(text: str) -> list:
    """真**调用参数**里的 `--ModifyMode <值>` 逐值（进度文案里的同名字符串不算）。"""
    return re.findall(r'--ModifyMode\s+(\w+)(?:\s|$)', code_lines(text))


def bare_empty_expansions(text: str) -> list:
    """裸 `"${A[@]}"`（未加 `+` 保护）逐处 —— **注释行不算**，否则判据吃自己的说明文字。"""
    hits = []
    for line in text.split("\n"):
        if line.strip().startswith("#"):
            continue
        hits.extend(BARE_EMPTY_EXPANSION_RE.findall(line))
    return hits


def preflight_block(text: str) -> str:
    """`ui_smoke_merchant.sh` 的云 dev DB 预检块（marker 取不到 ⇒ 空串，调用方 fail-closed）。

    块边界用**显式 marker 常量**（`PREFLIGHT_MARKER` / `STACK_MARKER`）—— 这两条 marker 在脚本里
    **只出现一次**，故 `find` 的首现语义在这里是有意的；会被喂红的是**位置比较**那一侧（见
    `preflight_ordering_ok`）。
    """
    start = text.find(PREFLIGHT_MARKER)
    if start < 0:
        return ""
    end = text.find(STACK_MARKER, start)
    if end < 0:
        return ""
    return text[start:end]


def launch_line_spans(text: str) -> list:
    """起 admin-api 的**结构锚**（issue #6802）：`LAUNCH_LINE_RE` 命中行的 `(起, 止)`，**注释行不算**。

    「只认代码行」正是本判据的判别力所在：注释里逐字出现「启动 admin-api」不改变命中集
    （`#6790` 的 ai-agent 配置块就是这么把旧判据喂红的）。
    """
    spans = []
    for m in LAUNCH_LINE_RE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        if text[line_start:m.start()].strip().startswith("#"):
            continue  # 整行注释：不是启动行
        spans.append((line_start, text.find("\n", m.end())))
    return spans


def ordering_verdict(text: str) -> str:
    """判据 7 的**可归因**出口：返回 `""` = 绿；否则返回**具名**原因（定位不到什么 / 差多少）。

    ⚠️ 比较的是「**预检 marker 的位置** vs **启动行行首的位置**」—— 两个都是**块/行的起点**；
    若拿块尾去比（或只比「块在不在」），「把块整体挪到启动行之后」这一形态就判不出来
    （实测踩过：只改 marker 位置会判绿，必须整块移动才复现判别力）。
    """
    block_at = text.find(PREFLIGHT_MARKER)
    if block_at < 0:
        return f"找不到预检块：marker {PREFLIGHT_MARKER!r} 取不到 —— fail-closed"
    spans = launch_line_spans(text)
    if not spans:
        return ("找不到**启动行**结构锚（`backend/admin-api` + `mvnw spring-boot:run` 的代码行）"
                "—— fail-closed")
    launch_at = spans[0][0]
    if block_at > launch_at:
        return f"预检块在启动行**之后**（block@{block_at} > launch@{launch_at}）—— 顺序即价值"
    return ""


def preflight_ordering_ok(text: str) -> bool:
    """预检块必须在**真正的启动行**之前（顺序即价值）。

    定位用**结构锚**（`LAUNCH_LINE_RE`），⛔ **不用** `text.find("启动 admin-api")` ——
    后者取的是**文本首现**，一句注释就能把它顶到预检块之前（issue #6802 的实际误伤现场；
    同族 = #5323）。定位失败一律 **fail-closed**（判 False），失败原因见 `ordering_verdict()`。
    """
    return ordering_verdict(text) == ""


def route_check_block(text: str) -> str:
    """`ui_smoke_merchant.sh` 的业务路由自检块（防「陈旧 `.next`」被读成产品故障）。"""
    start = text.find("# ── 2.5 业务路由自检")
    if start < 0:
        return ""
    end = text.find("  exit 1\nfi\n", start)
    if end < 0:
        return ""
    return text[start:end + len("  exit 1\nfi\n")]


def route_check_ordering_ok(text: str) -> bool:
    """自检必须在 admin-web ready **之后**、跑 spec **之前**。"""
    block = route_check_block(text)
    if not block:
        return False
    ready = text.find("✓ admin-web ready")
    spec = text.find("执行冒烟 spec")
    if ready < 0 or spec < 0:
        return False
    pos = text.find(block)
    return ready < pos < spec


# ── 桩 ──────────────────────────────────────────────────────────────────────

_FAKE_NC = """#!/bin/sh
# 行为桩：按参数返回成功/失败，**不建真连接、不碰云资源**（缺省可达）
case "$1" in
  -G) shift 2 2>/dev/null || true ;;
esac
exit "${NC_STUB_RC:-0}"
"""

_FAKE_ALIYUN = '''#!/usr/bin/env python3
"""`aliyun` 行为桩：只认 DescribeDBInstanceIPArrayList / ModifySecurityIps，全量记调用台账。

台账（$MOCK_STATE）：`CALL <argv…>` 每次调用 · `MODIFY <argv…>` 仅 Modify · `GROUPS <json>` 当前分组。
"""
import json
import os
import sys
from pathlib import Path

STATE = Path(os.environ["MOCK_STATE"])
GROUPS = {"default": os.environ["STUB_DEFAULT_IPS"], "dev_local": os.environ["STUB_DEV_LOCAL_IPS"]}


def load():
    if STATE.exists():
        for line in STATE.read_text().splitlines():
            if line.startswith("GROUPS "):
                GROUPS.update(json.loads(line[len("GROUPS "):]))


def note(kind, argv):
    with STATE.open("a") as fh:
        fh.write("%s %s\\n" % (kind, " ".join(argv)))


def main():
    load()
    argv = sys.argv[1:]
    note("CALL", argv)
    if not argv or argv[0] != "rds":
        print("usage: aliyun rds ...", file=sys.stderr)
        return 1
    op = argv[1]
    opts = {}
    for i, a in enumerate(argv):
        if a.startswith("--") and i + 1 < len(argv):
            opts[a] = argv[i + 1]
    if op == "DescribeDBInstanceIPArrayList":
        if os.environ.get("STUB_DESCRIBE_RC", "0") != "0":
            print("ERROR: InvalidAccessKeyId.NotFound", file=sys.stderr)
            return int(os.environ["STUB_DESCRIBE_RC"])
        items = [{"DBInstanceIPArrayName": g, "SecurityIPList": v} for g, v in GROUPS.items()]
        print(json.dumps({"Items": {"DBInstanceIPArray": items}}, ensure_ascii=False))
        return 0
    if op == "ModifySecurityIps":
        note("MODIFY", argv)
        if os.environ.get("STUB_MODIFY_RC", "0") != "0":
            print("ERROR: Forbidden.RAM", file=sys.stderr)
            return int(os.environ["STUB_MODIFY_RC"])
        grp = opts.get("--DBInstanceIPArrayName", "default")
        ips = [x.strip() for x in opts.get("--SecurityIps", "").split(",") if x.strip()]
        if opts.get("--ModifyMode") == "Append":
            GROUPS[grp] = ",".join([GROUPS.get(grp, "")] + ips).strip(",")
        else:  # 覆盖语义（本脚本禁止走这条）
            GROUPS[grp] = ",".join(ips)
        with STATE.open("a") as fh:
            fh.write("GROUPS %s\\n" % json.dumps(GROUPS))
        print('{"RequestId": "STUB-REQ", "TaskId": 0}')
        return 0
    print("unknown op: %s" % op, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
'''

# 桩 `curl`：业务路由 / 健康检查按状态码；**取公网 IP** 走 `IP_FALLBACK`（判据不碰真网络）
_FAKE_CURL = """#!/bin/sh
case "$*" in
  *checkip.amazonaws.com*|*ipinfo.io*|*ifconfig.me*)
      [ -n "${IP_FALLBACK:-}" ] || exit 1
      printf '%s' "$IP_FALLBACK"
      exit 0 ;;
esac
case "$*" in
  *"/actuator/health"*) _code=200 ;;
  *"/login"*) _code=200 ;;
  *"/employees"*|*"/dashboard"*|*"/products"*) _code="${ROUTE_STUB_CODE:-200}" ;;
  *) _code=000 ;;
esac
case "$*" in
  *"%{http_code}"*) printf '%s' "$_code" ;;
esac
exit 0
"""

# 把 `ALIYUN_BIN` / `NC_BIN` 钉到桩上再 exec 真脚本（真脚本不被改动）
_RUNNER = """#!/usr/bin/env bash
set -uo pipefail
export PATH="${STUB_BIN}:${PATH}"     # 桩目录前置：`curl` 也走桩（判据不许真连网）
: "${ALIYUN_BIN:=${STUB_BIN}/aliyun}"
: "${NC_BIN:=${STUB_BIN}/nc}"
export ALIYUN_BIN NC_BIN
exec bash "$1" ${2+"$2"}
"""


class Env:
    """桩环境：桩目录 + 桩 `.env` + 桩 `aliyun`/`nc` + 调用台账。"""

    def __init__(self, root: Path, script: Path | None = None,
                 dev_local_ips: str = DEV_LOCAL_OTHER,
                 default_ips: str = DEFAULT_GROUP_IPS) -> None:
        self.root = root
        self.script = script or SCRIPT
        self.bin = root / "bin"
        self.bin.mkdir(parents=True, exist_ok=True)
        self.env_file = root / "admin-api.env"
        self.env_file.write_text(
            f"RDS_HOST={STUB_HOST}\nRDS_PORT=5432\nRDS_PASSWORD={SENTINEL_PW}\n", encoding="utf-8"
        )
        self.state = root / "mock-state.txt"
        self.state.write_text("GROUPS {}\n", encoding="utf-8")
        self._write(self.bin / "aliyun", _FAKE_ALIYUN)
        self._write(self.bin / "nc", _FAKE_NC)
        self._write(self.bin / "curl", _FAKE_CURL)   # 取公网 IP 也走桩（不许真连网）
        self._write(self.bin / "runner", _RUNNER)
        self.dev_local_ips = dev_local_ips
        self.default_ips = default_ips

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def env(self, extra: dict | None = None) -> dict:
        (self.root / "tmp").mkdir(exist_ok=True)
        env = {
            "PATH": f"{self.bin}:{os.environ.get('PATH', '')}",
            "REPO_ROOT": str(self.root),
            "ENV_FILE": str(self.env_file),
            "TMPDIR": str(self.root / "tmp"),
            "MOCK_STATE": str(self.state),
            "STUB_BIN": str(self.bin),
            "STUB_DEFAULT_IPS": self.default_ips,
            "STUB_DEV_LOCAL_IPS": self.dev_local_ips,
            "IP_FALLBACK": IP,
            "HOME": str(self.root),
        }
        env.update(extra or {})
        return env

    def run(self, *args: str, extra: dict | None = None,
            timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.bin / "runner"), str(self.script), *args],
            capture_output=True, text=True, env=self.env(extra), cwd=str(self.root), timeout=timeout,
        )

    @property
    def log(self) -> str:
        return self.state.read_text(encoding="utf-8") if self.state.exists() else ""

    def modify_calls(self) -> list:
        return [ln for ln in self.log.splitlines() if ln.startswith("MODIFY ")]

    def changed_groups(self) -> list:
        return [m.group(1) for m in (MODIFY_RE.search(ln) for ln in self.modify_calls()) if m]

    def groups_after(self) -> dict:
        for line in reversed(self.log.splitlines()):
            if line.startswith("GROUPS "):
                return json.loads(line[len("GROUPS "):])
        return {}

    def ensure_aliyun_missing(self) -> None:
        (self.bin / "aliyun").unlink()


# ── 判据 1：幂等（已在列 ⇒ 0 次 Modify） ────────────────────────────────────

def test_already_listed_is_idempotent_zero_modify(tmp_path):
    """IP 已在 `dev_local` ⇒ 正常模式 exit 0，且**一次** Modify 都不调（幂等）。"""
    env = Env(tmp_path, dev_local_ips=f"{DEV_LOCAL_OTHER},{IP}")
    proc = env.run()
    assert proc.returncode == 0, f"exit={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert env.modify_calls() == [], f"幂等被破坏，Modify 调用：{env.modify_calls()}"
    assert "幂等" in proc.stdout
    assert "Connection succeeded" in proc.stdout


# ── 判据 2：只追加（Append + 恰为新 IP + 只动 dev_local） ─────────────────────

def test_missing_ip_appends_and_never_overwrites(tmp_path):
    """不在列 + `--yes` ⇒ Append 恰为新 IP；`default` 组零改动、`dev_local` 旧条目保留。"""
    env = Env(tmp_path)
    proc = env.run("--yes")
    assert proc.returncode == 0, f"exit={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    calls = env.modify_calls()
    assert len(calls) == 1, f"Modify 调用应当恰 1 次，实际 {len(calls)}：{calls}"
    call = calls[0]
    assert "--ModifyMode Append" in call, f"必须用 Append，实际：{call}"
    assert "--DBInstanceIPArrayName dev_local" in call
    ips = re.search(r"--SecurityIps (\S+)", call)
    assert ips and ips.group(1) == IP, f"--SecurityIps 必须恰为新 IP（不得手拼旧列表）：{call}"
    assert DEV_LOCAL_OTHER not in call, "旧列表被手拼进参数 ⇒ 覆盖语义入口"
    assert env.changed_groups() == ["dev_local"], f"只许动 dev_local，实际：{env.changed_groups()}"
    groups = env.groups_after()
    assert groups["default"] == DEFAULT_GROUP_IPS, f"default 组被动了：{groups['default']}"
    assert DEV_LOCAL_OTHER in groups["dev_local"] and IP in groups["dev_local"]
    assert "回读确认" in proc.stdout and "Connection succeeded" in proc.stdout


# ── 判据 3：默认只诊断 ──────────────────────────────────────────────────────

def test_missing_ip_without_yes_writes_nothing(tmp_path):
    """不在列且未给 `--yes` ⇒ 非零退出、零 Modify、文案点名处置命令（不静默写云资源）。"""
    env = Env(tmp_path)
    proc = env.run()
    assert proc.returncode != 0
    assert env.modify_calls() == []
    combined = proc.stdout + proc.stderr
    assert "dev-db-whitelist.sh --yes" in combined
    assert IP in combined


# ── 判据 4：fail-closed 五种形态 ────────────────────────────────────────────

def test_fail_closed_aliyun_missing(tmp_path):
    env = Env(tmp_path)
    env.ensure_aliyun_missing()
    proc = env.run()
    assert proc.returncode != 0
    assert env.modify_calls() == []
    assert "白名单" in proc.stdout + proc.stderr


def test_fail_closed_describe_failure(tmp_path):
    env = Env(tmp_path)
    proc = env.run("--yes", extra={"STUB_DESCRIBE_RC": "1"})
    assert proc.returncode != 0
    assert env.modify_calls() == []


def test_fail_closed_modify_failure(tmp_path):
    env = Env(tmp_path)
    proc = env.run("--yes", extra={"STUB_MODIFY_RC": "1"})
    assert proc.returncode != 0
    assert "ModifySecurityIps" in proc.stderr


def test_fail_closed_readback_miss(tmp_path):
    """Modify 被桩吃掉（不落库）⇒ 回读读不到新 IP ⇒ 非零退出，不许静默成功。"""
    env = Env(tmp_path)
    raw = (env.bin / "aliyun").read_text(encoding="utf-8")
    (env.bin / "aliyun").write_text(raw.replace('note("MODIFY", argv)\n', 'note("MODIFY", argv)\n        return 0\n'),
                                   encoding="utf-8")
    proc = env.run("--yes")
    assert proc.returncode != 0, f"回读不一致必须出声：\n{proc.stdout}"
    assert env.modify_calls() != []


def test_fail_closed_tcp_unreachable(tmp_path):
    """白名单已含但 TCP 不可达 ⇒ 非零退出（白名单不是唯一可能根因，但不许报成功）。"""
    env = Env(tmp_path, dev_local_ips=f"{DEV_LOCAL_OTHER},{IP}")
    proc = env.run(extra={"NC_STUB_RC": "1"})
    assert proc.returncode != 0
    assert "不可达" in proc.stdout + proc.stderr


# ── 判据 5：不泄漏凭据 ──────────────────────────────────────────────────────

def test_credentials_never_leak(tmp_path):
    """桩 `.env` 里的哨兵密码不得出现在任何一次输出里（含失败路径）。"""
    outputs = []
    for i, kwargs in enumerate(({}, {"STUB_DESCRIBE_RC": "1"}, {"STUB_MODIFY_RC": "1"})):
        env = Env(tmp_path / f"leak{i}", dev_local_ips=DEV_LOCAL_OTHER)
        for args in ((), ("--check",), ("--yes",)):
            proc = env.run(*args, extra=kwargs)
            outputs.append(proc.stdout + proc.stderr)
    assert len(outputs) == 9
    for out in outputs:
        assert SENTINEL_PW not in out, "凭据泄漏进输出"


# ── 判据 6：`--check` 只读 ──────────────────────────────────────────────────

def test_check_is_readonly_and_reports_state(tmp_path):
    env = Env(tmp_path, dev_local_ips=f"{DEV_LOCAL_OTHER},{IP}")
    proc = env.run("--check")
    assert proc.returncode == 0
    assert env.modify_calls() == [], "--check 必须是只读"
    assert "已在 dev_local 组" in proc.stdout and "Connection succeeded" in proc.stdout

    env2 = Env(tmp_path / "missing")
    proc2 = env2.run("--check")
    assert proc2.returncode != 0, "--check：不在列 ⇒ 非零（0/1 语义）"
    assert env2.modify_calls() == []
    assert "dev-db-whitelist.sh --yes" in proc2.stdout + proc2.stderr


# ── 判据 7：起栈入口预检（接线 + 时序 + 无下游噪音） ──────────────────────────

def test_smoke_preflight_reports_actionable_line_not_spring_noise(tmp_path):
    """桩 `nc` 不可达 ⇒ wrapper 非零退出，输出点名处置命令、且**不含** `PSQLException` 噪音。"""
    root = _fake_worktree(tmp_path)
    proc = _run_smoke(root, nc_rc="1")
    assert proc.returncode != 0, f"预检必须挡住起栈：\n{proc.stdout}\n{proc.stderr}"
    combined = proc.stdout + proc.stderr
    assert "dev-db-whitelist.sh" in combined, "提示必须点名一条命令的处置入口"
    assert combined.count("PSQLException") == 0, "不许让下游 7403 行 Spring 栈当第一现场"
    assert combined.count("启动 admin-api") == 0, "预检必须在起 admin-api **之前**（顺序即价值）"


def test_smoke_preflight_passes_through_when_reachable(tmp_path):
    """负控：桩 `nc` 可达 ⇒ **不**打预检文案（说明判据 7 的绿不是恒绿）。"""
    root = _fake_worktree(tmp_path)
    proc = _run_smoke(root, nc_rc="0", timeout=180)
    combined = proc.stdout + proc.stderr
    assert "连不上云 dev DB" not in combined, f"可达时不得打预检失败文案：\n{combined[-800:]}"
    assert "业务路由 404" not in combined, f"路由可达时不得打缓存失败文案：\n{combined[-800:]}"


# ── 判据 7b：业务路由自检（防「陈旧 .next」被读成产品大面积故障） ──────────────

def test_smoke_route_check_catches_stale_next_cache(tmp_path):
    """桩 dev 对业务路由回 404 ⇒ 输出含「.next」+ 可行动命令、非零退出、**没开始跑 spec**。"""
    root = _fake_worktree(tmp_path)
    proc = _run_smoke(root, nc_rc="0", route_rc="404")
    assert proc.returncode != 0, f"404 必须挡住跑 spec：\n{proc.stdout}\n{proc.stderr}"
    combined = proc.stdout + proc.stderr
    assert ".next" in combined, "提示必须点名陈旧 .next 缓存"
    assert "rm -rf" in combined and "frontend/admin-web/.next" in combined, "必须给可行动命令"
    assert combined.count("执行冒烟 spec") == 0, "不许继续跑 34 旅程（那会产出 34 条假故障读数）"


def test_smoke_route_check_absent_before_web_and_spec(tmp_path):
    """接线 + 时序：自检在 admin-web ready 之后、跑 spec 之前；且本脚本**不自动**删缓存。"""
    text = SMOKE.read_text(encoding="utf-8")
    assert route_check_ordering_ok(text), "业务路由自检必须接线在 admin-web ready 与 spec 之间"
    block = route_check_block(text)
    assert "ROUTE_CHECK_404" in block
    assert "rm -rf frontend/admin-web/.next" in block, "提示必须给出可行动命令（含要清哪个缓存）"
    # 只报不动手：`rm` 只许出现在**引号里的输出文案**中，不得作为命令执行
    exec_rm = [ln for ln in code_lines(block).split("\n")
               if re.match(r'\s*rm\s', ln) or re.search(r'(^|[;&|]\s*)rm\s+-', ln)]
    assert exec_rm == [], f"只报不动手：脚本里不得执行清理动作 {exec_rm}"
    assert "404" in block and '"$code" = "404"' in block, "只把 404 算坏（307/302/200 都算路由存在）"

    # 摘掉自检块 ⇒ 接线断言必须红；只改注释 ⇒ 不红
    stripped = text.replace(block, "")
    assert route_check_block(stripped) == ""
    assert not route_check_ordering_ok(stripped), "摘掉后 ordering 必须为假（否则是空断言）"
    comment_only = text.replace("# ── 2.5 业务路由自检", "# ── 2.5 业务路由自检（注释改写）")
    assert route_check_ordering_ok(comment_only), "只改注释不得判红"


# ── 判据 8：判别力自证（注入式，实跑） ──────────────────────────────────────

def test_guard_discriminates_bad_shapes(tmp_path):
    """三种坏形态**各自**判红：覆盖语义 / 删掉 ModifyMode 参数 / 摘掉预检块；还原 ⇒ 绿。"""
    # ① Append → Overwrite：覆盖语义把既有条目删掉 ⇒ 判据 2 的断言必须红
    #    ⚠️ 注入点必须是**真调用那一行**（脚本里还有一行进度文案含同一串 ⇒ 从注释/文案注入 = 没注入）
    env = Env(tmp_path / "overwrite", script=_mutate_script(
        tmp_path, "overwrite.sh",
        "--ModifyMode Append \\", "--ModifyMode Overwrite \\",
        expect="--ModifyMode Overwrite"))
    proc = env.run("--yes")
    assert proc.returncode == 0, "（注入下脚本仍跑通，变的只是语义）"
    call = env.modify_calls()[0]
    assert "--ModifyMode Append" not in call, "注入未生效：Append 仍在"
    assert DEV_LOCAL_OTHER not in env.groups_after()["dev_local"], "覆盖语义把旧条目删了"

    # ② 删掉整段 `--ModifyMode` 参数（回到 §10 的覆盖式手拼时代）⇒ 判据 2 必须红
    env2 = Env(tmp_path / "nomode",
               script=_mutate_script(tmp_path, "nomode.sh",
                                     " --ModifyMode Append \\\n        ", " \\\n        "))
    proc2 = env2.run("--yes")
    assert proc2.returncode == 0
    assert modify_modes(env2.modify_calls()[0]) == [], "注入未生效：ModifyMode 还在"
    assert env2.groups_after()["dev_local"] == IP, "无 ModifyMode ⇒ 桩按覆盖语义处理（旧条目被删）"

    # ③ 摘掉预检块 ⇒ 接线/时序断言必须红（fail-closed 且**具名**）
    smoke = SMOKE.read_text(encoding="utf-8")
    block = preflight_block(smoke)
    assert block, "预检块 marker 取不到（接线被摘？）"
    stripped = smoke.replace(block, "")
    assert preflight_block(stripped) == ""
    assert not preflight_ordering_ok(stripped), "摘掉预检后 ordering 判定必须为假（否则判据 7 是空断言）"
    assert "找不到预检块" in ordering_verdict(stripped), ordering_verdict(stripped)

    # ④ 还原：原文必须绿；只改注释 ⇒ 不红
    assert preflight_ordering_ok(smoke), f"还原后必须绿：{ordering_verdict(smoke)}"
    comment_only = smoke.replace("# ── 1.5 云 dev DB 预检", "# ── 1.5 云 dev DB 预检（注释改写）")
    assert preflight_ordering_ok(comment_only), "只改注释不得判红"
    assert bare_empty_expansions('# "${A[@]}"\n') == [], "注释里的裸展开不算（不吃自己的说明文字）"
    assert bare_empty_expansions('echo "${A[@]}"\n') == ['"${A[@]}"']


# ── 判据 7c：顺序判据的**结构性锚** + 四条正/负控（issue #6802） ────────────────

def test_preflight_ordering_anchor_is_structural_and_comment_proof(tmp_path):
    """顺序判据按**结构锚**定位启动行 —— 注释里的同名词不再误伤（issue #6802）。

    现场（2026-10-13 合并 main）：`#6790` 的 ai-agent 配置块注释里写了「⇒ 启动 admin-api 时显式传这两个
    变量」，比真正的启动行更靠前 ⇒ 旧的 `text.find("启动 admin-api")`（**文本首现**）把启动位置指到了那行
    注释上 ⇒ 判据判红，且归因指成「你的顺序写错了」（真因 = 注释里出现了一个词）。同族 = issue #5323。
    """
    smoke = SMOKE.read_text(encoding="utf-8")
    assert preflight_ordering_ok(smoke), ordering_verdict(smoke)

    # 结构锚真的取到「代码行」（不是靠那行注释）：命中行逐字含启动特征
    spans = launch_line_spans(smoke)
    assert spans, "结构锚一行都没命中 ⇒ 判据会恒绿（fail-closed 方向相反，必须红）"
    launch_src = smoke[spans[0][0]:spans[0][1]]
    assert "backend/admin-api" in launch_src and "mvnw spring-boot:run" in launch_src, launch_src

    # 负控①（**本单核心**）：预检块**之前**插入含「启动 admin-api」的注释 ⇒ 判定**不变**（仍绿）
    # 注入点 = 预检块 marker 正上方（即 `#6790` 那种「更靠前的块」的位置）
    decoy = smoke.replace(PREFLIGHT_MARKER, PRELAUNCH_DECOY_COMMENT + PREFLIGHT_MARKER, 1)
    assert PRELAUNCH_DECOY_COMMENT in decoy, "注入未生效：注释没进去"
    assert decoy.index("启动 admin-api") < decoy.index(PREFLIGHT_MARKER), (
        "注入未生效：注释不在预检块之前")
    # 注释不得改变启动行的**命中集**（位置随插入整体后移，比的是命中行的原文）
    assert [decoy[a:b] for a, b in launch_line_spans(decoy)] == \
           [smoke[a:b] for a, b in launch_line_spans(smoke)], "注释不得改变启动行的命中集"
    assert preflight_ordering_ok(decoy), f"注释负控失败（这正是 #6802 的误伤）：{ordering_verdict(decoy)}"

    # 负控②：预检块**之后**、启动行**之前**再插一段**代码**（非注释）⇒ 判定仍绿
    mid = spans[0][0]
    between = smoke[:mid] + "echo '夹在预检与启动之间的代码' >/dev/null\n" + smoke[mid:]
    assert preflight_block(between) and preflight_ordering_ok(between), ordering_verdict(between)

    # 正控（判别力仍在）：把预检块整块切出来，重新插到启动行**之后** ⇒ 红且报「之后」
    # （块内自带 `STACK_MARKER` ⇒ `preflight_block` 仍能取出它，判红走的就是位置比较那条路径）
    block = preflight_block(smoke)
    start = smoke.index(block)
    head_at, head_end = spans[0]
    relocated = (smoke[:start] + smoke[start + len(block):head_end]
                 + block + smoke[head_end:])
    assert relocated.find(PREFLIGHT_MARKER) > relocated.find(smoke[head_at:head_end]), (
        f"注入未生效：块没被移到启动行之后"
        f"（marker@{relocated.find(PREFLIGHT_MARKER)} / launch@{relocated.find(smoke[head_at:head_end])}）")
    assert not preflight_ordering_ok(relocated), "顺序正控失败：判据已被改成恒真"
    assert "之后" in ordering_verdict(relocated), ordering_verdict(relocated)

    # fail-closed：启动行被注释掉（只剩注释里那句话）⇒ 定位不到 ⇒ 红且具名
    commented_out = smoke.replace("  ( cd \"$REPO_ROOT/backend/admin-api\"",
                                  "  # ( cd \"$REPO_ROOT/backend/admin-api\"", 1)
    assert launch_line_spans(commented_out) == [], "注入未生效：被注释掉的启动行仍被算作启动行"
    assert not preflight_ordering_ok(commented_out), "定位不到启动行必须 fail-closed（判红）"
    assert "结构锚" in ordering_verdict(commented_out), ordering_verdict(commented_out)


def _mutate_script(tmp_path: Path, name: str, old: str, new: str, expect: str = "") -> Path:
    text = SCRIPT.read_text(encoding="utf-8")
    assert old in text, f"注入锚点失配（{name}）：{old!r}"
    mutated = text.replace(old, new, 1)
    assert mutated != text, f"注入未生效（{name}）"
    if expect:
        assert expect in mutated, f"注入未生效（{name}）：产物里读不到 {expect!r}"
    p = tmp_path / name
    p.write_text(mutated, encoding="utf-8")
    p.chmod(0o755)
    return p


# ── 判据 9：类级元守卫（承载体唯一性 + 覆盖语义禁入 + bash 3.2 展开） ──────────

def test_class_level_guards_on_script_corpus():
    """一条命令只许有一处承载体；覆盖语义与裸空数组展开禁入。"""
    assert SCRIPT.exists() and os.access(SCRIPT, os.X_OK), f"缺可执行脚本：{SCRIPT}"

    corpus = sorted(SCRIPT_DIR.glob(SHELL_CORPUS_GLOB))
    assert corpus, f"语料为空（{SCRIPT_DIR}/{SHELL_CORPUS_GLOB}）⇒ 本判据恒绿（fail-closed）"
    found = {p.name for p in corpus if "--ModifyMode Append" in p.read_text(encoding="utf-8")}
    assert found == {"dev-db-whitelist.sh"}, f"`--ModifyMode Append` 承载体不唯一：{sorted(found)}"

    # 空真防空：判据 2 的锚串必须真在脚本里（否则「绿」来自「脚本里没这串」而不是「语义对」）
    script_text = SCRIPT.read_text(encoding="utf-8")
    for anchor in ("--ModifyMode Append", "--DBInstanceIPArrayName", "--SecurityIps"):
        assert anchor in script_text, f"判据锚串从脚本里消失：{anchor!r} ⇒ 上层判据已退化成空断言"

    assert "Overwrite" not in script_text, "覆盖语义禁入（误删他人 IP 的入口）"
    assert modify_modes(script_text) == ["Append"], f"脚本里的 ModifyMode 取值：{modify_modes(script_text)}"
    assert bare_empty_expansions(script_text) == [], '空数组必须写成 ${A[@]+"${A[@]}"}（bash 3.2）'

    smoke_text = SMOKE.read_text(encoding="utf-8")
    assert preflight_ordering_ok(smoke_text), "预检必须在启动 admin-api 之前"
    assert "dev-db-whitelist.sh" in preflight_block(smoke_text)
    assert route_check_ordering_ok(smoke_text), "业务路由自检必须接线（admin-web ready 后 / spec 前）"


# ── 桩 fixture：假 worktree（只放预检要读的两样 + 假 MAIN_REPO） ──────────────

def _fake_worktree(tmp_path: Path) -> Path:
    """最小假 worktree：`scripts/ui_smoke_merchant.sh` + `backend/admin-api/.env`。

    只为把预检那一段真跑起来 —— 依赖准备 / 起栈 / spec 都不进射程（预检先失败）。
    """
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "backend" / "admin-api").mkdir(parents=True)
    (root / "frontend" / "admin-web").mkdir(parents=True)
    shutil.copy2(SMOKE, root / "scripts" / "ui_smoke_merchant.sh")
    shutil.copy2(SCRIPT, root / "scripts" / "dev-db-whitelist.sh")
    (root / "backend" / "admin-api" / ".env").write_text(
        f"RDS_HOST={STUB_HOST}\nRDS_PORT=5432\nRDS_PASSWORD={SENTINEL_PW}\n", encoding="utf-8"
    )
    return root


def _run_smoke(root: Path, nc_rc: str, route_rc: str = "200",
               timeout: int = 300) -> subprocess.CompletedProcess:
    """在桩 PATH 下真跑 `ui_smoke_merchant.sh`（`nc` 行为桩；`npm`/`curl` 兜底桩防真装 / 真网络）。"""
    fake = root / "fakebin"
    fake.mkdir(exist_ok=True)
    for name in ("npm", "node", "lsof"):
        p = fake / name
        p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        p.chmod(0o755)
    # 受控 PATH：桩 `nc` / 桩 `curl` / 桩 `npm`，**外加系统基础命令的软链** ——
    # 不这样，`nc -G` / `curl` 会落回真二进制 ⇒ 真连网（判据不许有真网络依赖）。
    for tool in ("bash", "sh", "env", "sed", "grep", "head", "tr", "mktemp", "mvn"):
        real = shutil.which(tool)
        if real:
            (fake / tool).symlink_to(real)
    for name, body in (("nc", _FAKE_NC), ("curl", _FAKE_CURL)):
        p = fake / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{fake}:{env.get('PATH', '')}"
    env["NC_STUB_RC"] = nc_rc
    env["ROUTE_STUB_CODE"] = route_rc
    env["IP_FALLBACK"] = ""      # 假 worktree 里没有桩 aliyun ⇒ 本单的脚本根本跑不起来（fail-closed）
    env["MAIN_REPO"] = str(root)          # 别去碰真主仓库
    env["OUT_DIR"] = str(root / "out")
    env["REPO_ROOT"] = str(root)
    return subprocess.run(
        ["bash", str(root / "scripts" / "ui_smoke_merchant.sh")],
        capture_output=True, text=True, env=env, cwd=str(root), timeout=timeout,
    )
