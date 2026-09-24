# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`deploy/scripts/swas-deploy-ci.sh` bootstrap 的**并发隔离**守卫 —— issue #4625。

## 缺陷（2026-09-19 实测，非推断）

`deploy-admin-api` / `deploy-ai-agent-service` / `deploy-frontend` **三个 workflow 共用**
同一个 SWAS 实例，同一次 push（`1d30c6cc`）会**并发**触发它们。三者都要先跑 bootstrap
（拉源码 tar → 解压 → 装 `deploy.sh` → 执行），而旧 bootstrap 把**共享固定路径**当工作区：

```bash
rm -rf /tmp/migao-src && mkdir -p /tmp/migao-src && curl … -o /tmp/migao-src.tar.gz && \
  tar xzf /tmp/migao-src.tar.gz -C /tmp/migao-src --strip-components=1 && \
  cp /tmp/migao-src/deploy/swas/deploy.sh /opt/migao-deploy/deploy.sh && bash …
```

同刻两个 run 的实测输出（均为 `Output` 字段 base64 解出）：

- `run 35458389055`（frontend，17:32:11Z）→ `cp: cannot stat '/tmp/migao-src/deploy/swas/deploy.sh': No such file or directory`
- `run 35458382449`（ai-agent，17:32:04Z）→ `rm: cannot remove '/tmp/migao-src/frontend/mini-app': Directory not empty`
- 而 `run 35458375984`（admin-api，17:31:56Z）**成功** ⇒ **随机一端失败、线上前端落后一个版本**。

两个共享面各自都会红：① 共享源码目录（A 的 `rm -rf` 删掉 B 刚解压的树 ⇒ B 的 `cp` 找不到文件）；
② 共享 `deploy.sh` 目标（`cp` 是**截断+写入**，并发时另一个 run 的 `bash` 可能读到**写了一半**的脚本）。

`deploy.sh` **内部**确实有 flock，但它**只覆盖 deploy.sh 自己** —— bootstrap 这一段**没有锁**，
竞态窗口正是它。所以「flock 会串行化」不能当作 bootstrap 可以共享路径的理由。

## 本文件锁什么

1. **静态判据**：从脚本里**逐字解析出** `BOOTSTRAP=` 的取值（多行续行 + 去转义），断言
   无共享固定路径 / 有 `mktemp` 唯一目录 / 装 deploy.sh 走「临时名 + `mv -f`」/ 退出码透传；
2. **注入式红证**：往临时副本塞回旧写法 ⇒ 同一组判据**必须判红**（且每条判据各自可独立判红）；
3. **反空跑锚点**：脚本扫不到 / `BOOTSTRAP` 解析不出 ⇒ **显式失败**（不是"通过"）；
4. **本地并发复现**（不依赖真实云、不联网）：用**脚本里那段真实命令**（只把 `${IMAGE_TAG}` 代入、
   把 `curl` 换成喂本地 tar 的桩）在**共享 TMPDIR** 下并发跑两次 —— 旧写法**必踩**、新写法**不踩**；
5. **原子替换的判别力**：读者并发读 `deploy.sh` 时，`cp` 形态**必见撕裂**、`mv` 形态**必不见**。

## 夹具自己的命名空间（#5344）

第 4 条（并发复现）必须构造"另一个 run 删掉共享目录"。旧实现直接操作**机器级**固定路径
`/tmp/migao-src*` ⇒ **并发跑同一文件的另一个 pytest 会话**就是那个"另一个 run"：
它的清理会落进本会话 victim 的 `curl → tar` 窗口（`curl` 刚写下 tar、`tar` 还没读），
victim 的 `&&` 链当场断掉、`cp` 窗口永不出现 ⇒ 判据红在**夹具失效**上
（本机 3 并发 ×3 轮实测 **6/9 红**，形态恒为 `断言 mark.exists()`）。
那是**测试工装自己的竞态**，不是被测对象 ⇒ 夹具改用**按进程隔离**的命名空间
（`NS_SRC` / `NS_TAR`，`-<pid>` 后缀），且**清理前先等产生方退出**（`_clean_shared_namespace`）。
被判的脚本文本仍按**字面**判 `/tmp/migao-src*`（静态判据一格未松）。

判据本体读的是**脚本当前文本**，不是"与某个历史版本等值"（§18.3：不读可变引用）。
"""
import os
import re
import shutil
import subprocess
import tarfile
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "deploy" / "scripts" / "swas-deploy-ci.sh"

# 旧写法的两处共享固定路径（issue #4625 现象的直接来源）——**静态判据按字面读真脚本**，不要改。
SHARED_SRC = "/tmp/migao-src"
SHARED_TAR = "/tmp/migao-src.tar.gz"

# ── 碰撞夹具自己的命名空间（#5344）────────────────────────────────────────────
# 病根（本机 3 并发 ×3 轮实测 6/9 红）：夹具直接操作**机器级**固定路径 ⇒ **并发跑同一文件的
# 另一个 pytest 会话**（别的 worktree、或还在跑旧版代码的会话）就是那个"另一个 run"，
# 它的 `rm -rf` / `unlink` 会落进本会话 victim 的 `curl → tar` 窗口 ⇒ victim 的 `&&` 链断掉、
# `cp` 窗口永不出现 ⇒ 判据红在**夹具失效**上。**这是工装自己的竞态**，修法三条：
#   ① **命名空间按进程隔离**（`-<pid>`）⇒ 非协作的并发会话根本碰不到它（锁做不到这点：
#      别的 worktree 里的旧版代码不会来抢锁）；
#   ② **清理前先等产生方退出**（`_clean_shared_namespace` ⇒ `_wait_for_producers`）——
#      不许"删完再让子进程写"；
#   ③ victim 无论成败都先等/杀干净（`_terminate_producer`），不泄漏产生方。
NS_SRC = f"{SHARED_SRC}-{os.getpid()}"
NS_TAR = f"{SHARED_SRC}-{os.getpid()}.tar.gz"

_PRODUCERS: list = []          # 本进程向该命名空间写入过的产生方（Popen）


def _localize(cmd: str) -> str:
    """把**夹具构造出来的命令串**里的机器级固定路径重写到本进程唯一的命名空间。

    只重写夹具造的命令（`check_bootstrap` / `inject_old_bootstrap` 判的仍是**脚本文本**原文，
    其中的 `/tmp/migao-src*` 照旧按字面判红）。形态一格未改：旧写法仍是"跨 run 共享的**固定**
    路径"、新写法仍是 `mktemp -d` —— 只是不再与**别的 pytest 会话**抢同一个目录。
    """
    return cmd.replace(SHARED_SRC, NS_SRC)


def _wait_for_producers(timeout: float = 60.0) -> list:
    """**清理命名空间之前**必须等所有产生方退出（#5344 判据 1）。

    返回"实际等了谁"（pid 列表；空 = 当时确实没有活着的产生方）—— 留这个返回值是为了让
    "等过"与"没等"**长得不一样**（零动作也要能自证）。
    """
    waited = []
    for p in list(_PRODUCERS):
        if p.poll() is None:
            waited.append(p.pid)
            p.wait(timeout=timeout)
    _PRODUCERS.clear()
    return waited


def _clean_shared_namespace() -> list:
    """清掉本进程命名空间的残留：**先等产生方退出，再删**（顺序就是判据本身）。"""
    waited = _wait_for_producers()
    shutil.rmtree(NS_SRC, ignore_errors=True)
    Path(NS_TAR).unlink(missing_ok=True)
    return waited


def _terminate_producer(p) -> None:
    """确保产生方退出（失败路径也要）—— 超时先 `kill` 再 `wait`，不留活着的写者。"""
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait(timeout=10)

# 旧 bootstrap（**逐字内联**，取自 issue #4625 与本 PR 之前的脚本；内联而不是
# `git show origin/main:…` —— 后者会随合并变成"修复后"文本 ⇒ 判据自红，§18.3）
OLD_BOOTSTRAP = (
    'BOOTSTRAP="${REGISTRY_SETUP}rm -rf /tmp/migao-src && mkdir -p /tmp/migao-src && '
    'curl -fsSL --retry 3 https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main '
    '-o /tmp/migao-src.tar.gz && tar xzf /tmp/migao-src.tar.gz -C /tmp/migao-src '
    '--strip-components=1 && cp /tmp/migao-src/deploy/swas/deploy.sh '
    '/opt/migao-deploy/deploy.sh && bash /opt/migao-deploy/deploy.sh ${IMAGE_TAG}"'
)

BOOTSTRAP_RE = re.compile(r'^BOOTSTRAP="', re.M)


# --------------------------------------------------------------------------
# 解析：从脚本文本里取 BOOTSTRAP 的取值
# --------------------------------------------------------------------------

def _unescape_sh_double_quoted(body: str) -> str:
    """把 shell 双引号串里的转义还原（`\\$(…)` → `$(…)`、`\\"` → `"`）。"""
    out = []
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            out.append(body[i + 1])
            i += 2
        else:
            out.append(body[i])
            i += 1
    return "".join(out)


def escape_sh_double_quoted(s: str) -> str:
    """把求值后的命令**转义回**脚本里的双引号串形态（供"注入点必须存在"这类断言用）。"""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")


def _bootstrap_span(text: str):
    """定位 `BOOTSTRAP="…"` 的 **(起, 止, 原始串体)**。

    ⚠️ 不能用非贪婪 `".*?"` —— 串体里有大量**转义引号**（`\\"\\$SRC\\"`），
    非贪婪匹配会在第一个 `\\"` 的引号处提前收尾 ⇒ 解析出半截命令（实测踩到，会让并发
    复现夹具整个失效）。故按「反斜杠跳过下一字符」逐个扫到**真正的收尾引号**。
    """
    m = BOOTSTRAP_RE.search(text)
    assert m, (
        '扫不到 `BOOTSTRAP="…"` 赋值 —— 要么脚本被改名/改写，要么判据的解析式已过期。\n'
        "反空跑锚点：这里必须显式失败，**不许**退化成「没扫到 ⇒ 通过」。"
    )
    i = m.end()
    body_start = i
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            break
        i += 1
    assert i < len(text), "BOOTSTRAP 的双引号串没有收尾引号（脚本语法已坏）"
    return m.start(), i + 1, text[body_start:i]


def extract_bootstrap(text: str) -> str:
    """取 `BOOTSTRAP="…"` 的**求值后**取值（支持多行续行）。解析不出 ⇒ 显式报红。"""
    _, _, raw = _bootstrap_span(text)
    return _unescape_sh_double_quoted(raw.replace("\\\n", ""))


def read_script() -> str:
    assert SCRIPT.is_file(), f"反空跑锚点：目标脚本不存在 → {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def inject_old_bootstrap(text: str) -> str:
    """把新 bootstrap 换成旧写法（红证用）。"""
    start, end, raw = _bootstrap_span(text)
    assert _unescape_sh_double_quoted(raw).strip(), "注入前解析出的 bootstrap 是空串"
    return text[:start] + OLD_BOOTSTRAP + text[end:]


# --------------------------------------------------------------------------
# 静态判据（可复用于红证：传入被注入的文本）
# --------------------------------------------------------------------------

def check_bootstrap(text: str) -> str:
    """bootstrap 并发隔离的**全部静态判据**。违规即断言失败；返回解析出的命令。"""
    cmd = extract_bootstrap(text)

    # ① 不得出现任何跨 run 共享的固定路径
    for shared in (SHARED_SRC, SHARED_TAR):
        assert shared not in cmd, (
            f"bootstrap 里仍有共享固定路径 {shared} —— 三个 workflow 共用同一台 SWAS，"
            "同一次 push 的并发 run 会互相 rm -rf / 读到半成品（issue #4625）。"
        )
    assert "/tmp/migao" not in cmd, "bootstrap 里出现 /tmp/migao* 前缀的固定路径（共享面）"

    # ② 必须有 per-run 唯一路径
    assert re.search(r"\bmktemp\s+-d\b", cmd), "bootstrap 未用 `mktemp -d` 建 per-run 唯一源码目录"
    assert re.search(r"\bmktemp\b", cmd), "bootstrap 未用 `mktemp` 建 per-run 唯一临时包"

    # ③ 装 deploy.sh 必须「先写临时名再 mv -f」（原子替换，读者永不见半成品）
    assert re.search(r"\bmv\s+-f\b", cmd), "bootstrap 装 deploy.sh 未走 `mv -f` 原子替换"
    assert not re.search(r"\bcp\b[^&;|]*?\s/opt/migao-deploy/deploy\.sh\b", cmd), (
        "bootstrap 仍用 `cp` 直接写 /opt/migao-deploy/deploy.sh（截断+写入，非原子）"
    )

    # ④ 必须保留远端退出码：rc=$? → 清理 → exit $rc
    assert re.search(r"\brc=\$\?", cmd), "bootstrap 未捕获 deploy.sh 的退出码（rc=$?）"
    assert re.search(r"\bexit\s+\$rc\b", cmd), "bootstrap 未用 `exit $rc` 透传退出码（失败会被吞掉）"
    idx = cmd.index("bash /opt/migao-deploy/deploy.sh")
    tail = cmd[idx:]
    assert "rc=$?" in tail and "exit $rc" in tail, (
        "退出码捕获/透传必须发生在 `bash /opt/migao-deploy/deploy.sh` **之后**（否则捕获的是别的命令）"
    )

    # ⑤ 收尾清理自己的临时产物
    assert re.search(r'rm\s+-rf\s+"?\$SRC"?', cmd), "bootstrap 收尾未清理自己的源码临时目录"
    assert re.search(r'rm\s+-rf\s+"?\$SRC"?\s+"?\$TAR"?', cmd), (
        "bootstrap 收尾未一并清理临时 tar 包"
    )

    # ⑥ 本地要展开的两个变量必须保持原样（转义纪律）
    assert "${REGISTRY_SETUP}" in cmd, "`${REGISTRY_SETUP}` 应保持本地展开（不得转义）"
    assert "${IMAGE_TAG}" in cmd, "`${IMAGE_TAG}` 应保持本地展开（不得转义）"
    return cmd


# --------------------------------------------------------------------------
# 1. 反空跑锚点
# --------------------------------------------------------------------------

def test_script_exists_and_bootstrap_is_parseable():
    """扫不到目标文件 / 解析不出 BOOTSTRAP ⇒ 显式失败（**不是**"通过"）。"""
    cmd = extract_bootstrap(read_script())
    assert cmd.strip(), "解析出的 bootstrap 是空串 —— 判据会退化成空断言"
    assert "codeload.github.com/zhaokai-mgzn/migao/tar.gz" in cmd, (
        "bootstrap 里找不到源码下载 URL ⇒ 解析到的多半不是真正的 bootstrap"
    )
    assert "/opt/migao-deploy/deploy.sh" in cmd, "bootstrap 里找不到 deploy.sh 安装路径"


def test_missing_script_fails_loudly(tmp_path):
    """目标脚本不存在 ⇒ 反空跑锚点必须报红（不是静默通过）。"""
    missing = tmp_path / "nope.sh"
    assert not missing.exists()
    with pytest.raises(AssertionError):
        assert missing.is_file(), f"反空跑锚点：目标脚本不存在 → {missing}"


def test_unparseable_text_fails_loudly():
    """文本里没有 BOOTSTRAP 赋值 ⇒ 解析必须报红，不得静默返回空串。"""
    with pytest.raises(AssertionError):
        extract_bootstrap("#!/bin/bash\necho hello\n")


# --------------------------------------------------------------------------
# 2. 静态判据（真脚本）
# --------------------------------------------------------------------------

def test_bootstrap_has_no_shared_fixed_path():
    text = read_script()
    check_bootstrap(text)
    assert SHARED_SRC not in text, f"整份脚本仍出现共享固定路径 {SHARED_SRC}"
    assert SHARED_TAR not in text, f"整份脚本仍出现共享固定路径 {SHARED_TAR}"


def test_bootstrap_uses_per_run_unique_paths():
    cmd = extract_bootstrap(read_script())
    assert "SRC=$(mktemp -d)" in cmd, "源码目录必须是 `SRC=$(mktemp -d)`（per-run 唯一）"
    assert "TAR=$(mktemp)" in cmd, "临时包必须是 `TAR=$(mktemp)`（per-run 唯一）"
    assert '"$TAR"' in cmd and '"$SRC"' in cmd, "唯一路径必须被加引号使用"


def test_deploy_sh_install_is_atomic():
    cmd = extract_bootstrap(read_script())
    assert re.search(
        r'cp\s+"\$SRC"/deploy/swas/deploy\.sh\s+\S*\.deploy\.sh\.new\s*&&\s*'
        r'mv\s+-f\s+\S*\.deploy\.sh\.new\s+/opt/migao-deploy/deploy\.sh\s*&&\s*'
        r'bash\s+/opt/migao-deploy/deploy\.sh',
        cmd,
    ), (
        "装 deploy.sh 的形态必须是 `cp \"$SRC\"/deploy/swas/deploy.sh <临时名> && "
        "mv -f <临时名> /opt/migao-deploy/deploy.sh && bash /opt/migao-deploy/deploy.sh`"
    )


# --------------------------------------------------------------------------
# 3. 注入式红证（旧写法 ⇒ 必红；且每条判据各自可独立判红）
# --------------------------------------------------------------------------

def test_injected_old_bootstrap_turns_guard_red():
    """往临时副本塞回旧写法 ⇒ 同一组判据必须判红（红证）。"""
    real = read_script()
    check_bootstrap(real)  # 前提：真脚本先绿
    broken = inject_old_bootstrap(real)
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError) as exc:
        check_bootstrap(broken)
    assert SHARED_SRC in str(exc.value), (
        f"注入旧写法后报红原因应点名共享路径，实际：{str(exc.value)[:200]}"
    )


@pytest.mark.parametrize(
    "old,new,label,expect",
    [
        ("SRC=$(mktemp -d)", "SRC=/tmp/migao-src", "共享源码目录", SHARED_SRC),
        ("TAR=$(mktemp)", "TAR=/tmp/migao-src.tar.gz", "共享临时包", SHARED_TAR),
        (
            "mv -f /opt/migao-deploy/.deploy.sh.new /opt/migao-deploy/deploy.sh",
            "cp /opt/migao-deploy/.deploy.sh.new /opt/migao-deploy/deploy.sh",
            "非原子替换",
            "mv -f",
        ),
        # 只吞掉退出码（保留清理）—— 验证"退出码透传"判据独立可红
        ("rc=$?;", "", "吞掉退出码", "rc=$?"),
        ("exit $rc", "exit 0", "退出码被写死", "exit $rc"),
    ],
)
def test_each_criterion_can_turn_red_independently(old, new, label, expect):
    """**每条判据都要有自己的红证**（不会红的断言 = 空断言）。

    注入发生在脚本**原文**上 ⇒ 注入点必须按双引号串转义后的形态匹配。
    """
    real = read_script()
    raw_old, raw_new = escape_sh_double_quoted(old), escape_sh_double_quoted(new)
    assert raw_old in real, f"[{label}] 注入点已漂移（判据过期）：{raw_old!r}"
    broken = real.replace(raw_old, raw_new)
    assert broken != real, f"[{label}] 注入未生效"
    with pytest.raises(AssertionError) as exc:
        check_bootstrap(broken)
    assert expect in str(exc.value), (
        f"[{label}] 报红原因应点名 `{expect}`，实际：{str(exc.value)[:200]}"
    )


# --------------------------------------------------------------------------
# 4. 本地并发复现（不依赖真实云 / 不联网）—— 本单最有说服力的红证
# --------------------------------------------------------------------------

CURL_STUB = """#!/bin/bash
# 桩 curl：不联网，把夹具 tar 复制到 -o 指定路径；记录调用（证明每个 run 的 -o 目标不同）
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) shift ;;
  esac
done
printf '%s\n' "$out" >> "$CURL_LOG"
cp "$STUB_TARBALL" "$out"
"""

# 桩 cp（victim 用）：**真 cp 的语义不变**（真删真拷），只把「另一个 run 已经 `rm -rf` 掉共享
# 源码目录」这个真实竞态**确定化**：
#   ① 进入 `cp` 窗口 ⇒ touch `$CP_WINDOW_MARK`（测试据此知道"cp 正要开始"）
#   ② 等 `$GO`（测试此时才真正删掉共享源码目录）—— 保证删除一定发生在"cp 已开始"之后
#   ③ 再走真 `cp` ⇒ 源码没了 ⇒ 报错形态与线上一致
# 为什么不用 `sleep` / 让两个完整 bootstrap 自然重叠（都实测踩过，方向会反转）：
#   · 纯 `sleep` 凑时序 ⇒ 两个 run 根本不重叠，旧写法"也绿"；
#   · 让两个 bootstrap 自然并发 ⇒ killer 自己随后会 `tar xzf` **把源码树重新解出来**，
#     victim 晚一点查就又能 `cp` 成功（实测 5 次里红 2 次，是 flake 而不是判据）。
#   ⇒ 这里把"删除"这一步**显式**放在 victim 的 `cp` 窗口中间：竞态窗口就是被测对象本身。
SLOW_CP_STUB = """#!/bin/bash
for a in "$@"; do
  case "$a" in
    */deploy/swas/deploy.sh)
      : > "$CP_WINDOW_MARK"
      while [ ! -e "$GO" ]; do sleep 0.01; done
      ;;
  esac
done
exec /bin/cp "$@"
"""


def _write_exe(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _make_fixture_tarball(path: Path, deploy_body: str) -> None:
    """造一个 `migao-main/deploy/swas/deploy.sh` 的 tar（配合 `--strip-components=1`）。

    真实 codeload tar 的顶层是 `migao-main/`；`--strip-components=1` 剥掉它 ⇒ 解压后
    `$SRC/deploy/swas/deploy.sh` 才是目标路径。夹具必须逐字复刻这个层级。
    """
    root = path.parent / f"_stage-{path.stem}" / "migao-main"
    stage = root / "deploy" / "swas"
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "deploy.sh").write_text(deploy_body, encoding="utf-8")
    with tarfile.open(path, "w:gz") as tf:
        tf.add(root, arcname="migao-main")


def _mkrun(tmp_path: Path, name: str, *, slow_cp: bool) -> dict:
    """一个 run 的独立目录 + 桩 bin（唯一共享面 = 父进程传进来的 `TMPDIR`）。"""
    run_dir = tmp_path / name
    run_dir.mkdir(parents=True, exist_ok=True)
    bin_dir = run_dir / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_exe(bin_dir / "curl", CURL_STUB)
    if slow_cp:
        _write_exe(bin_dir / "cp", SLOW_CP_STUB)
    # 真实服务器上 `/opt/migao-deploy` 是既有目录（不归 bootstrap 管）—— 夹具必须复刻，
    # 否则旧写法的报错会变成"目标目录不存在"，与线上形态（源码目录被删）不同。
    (run_dir / "opt-migao-deploy").mkdir(exist_ok=True)
    tarball = run_dir / "fixture.tar.gz"
    _make_fixture_tarball(tarball, "#!/bin/bash\necho stub-deploy \"$@\"\n")
    (run_dir / "curl.log").write_text("", encoding="utf-8")
    return {"dir": run_dir, "bin": bin_dir, "tarball": tarball, "log": run_dir / "curl.log"}


def _build_like_ci(run: dict, command: str) -> str:
    """把命令串里的 `${REGISTRY_SETUP}` / `${IMAGE_TAG}` **在构建期**展开 —— 与 CI 一致。

    ⚠️ 这两个变量是 CI 侧（脚本本地）展开的，**不能在子进程里靠环境变量展开**：
    bash 的**变量展开结果不会被重新当作语法解析** ⇒ `${REGISTRY_SETUP}` 若以 `&&` 结尾，
    那个 `&&` 会变成前一条命令的**字面参数**，后面的 `SRC=$(mktemp -d)` 被吞掉、`$SRC` 变空
    （实测踩到：`tar: Meaningless option: -C ''`，夹具失效会伪装成"新写法也失败"，红证方向反转）。
    """
    registry = f"printf 'stub\\n' > {run['dir']}/env.registry && "
    return (
        command.replace("${REGISTRY_SETUP}", registry)
        .replace("${IMAGE_TAG}", "sha-testtag")
        # 服务器上的安装目录要 root，测试里改指 run 自己的沙箱目录
        .replace("/opt/migao-deploy", str(run["dir"] / "opt-migao-deploy"))
    )


def _spawn(run: dict, command: str, shared_tmp: Path):
    env = {
        **os.environ,
        "PATH": f"{run['bin']}:{os.environ['PATH']}",
        "TMPDIR": str(shared_tmp),
        "STUB_TARBALL": str(run["tarball"]),
        "CURL_LOG": str(run["log"]),
        "CP_WINDOW_MARK": str(run["dir"] / "cp-window"),
        "GO": str(run["dir"] / "go"),
    }
    p = subprocess.Popen(
        # ⚠️ 必须显式给 `$0`：`bash -c <cmd>` 会把命令串的**第一个词**当成 `$0`
        # ⇒ `SRC=$(mktemp -d) && …` 的首词被吃掉，报 `bash: SRC=/tmp/…: No such file or directory`
        # （实测踩到：夹具失效会伪装成"新写法也失败"，红证方向正好反过来）。
        # `_localize`：共享固定路径重写到**本进程唯一**命名空间（#5344，见文件头）。
        ["bash", "-c", _localize(_build_like_ci(run, command)), "migao-bootstrap"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    _PRODUCERS.append(p)          # 登记产生方：清理命名空间前必须等它退出（#5344）
    return p


def _run_with_collision(tmp_path: Path, command: str, tag: str):
    """跑一个 run，并**在它的 `cp` 窗口中间**制造「另一个 run 删掉源码目录」这一步。

    步骤（确定化，不依赖时序巧合）：
      1. **先等本进程此前的产生方退出**，再清本进程命名空间的残留（#5344：清理与产生方串行）；
      2. 启动 victim，等它进入 `cp` 窗口（`cp-window` 出现 ⇒ `cp` 已开始、源码此刻**在**）；
      3. 删掉**另一个 run 会删的那个目录**：旧写法 = 跨 run 共享的固定路径（真实竞态窗口），
         新写法 = 它自己的 `mktemp -d` 目录（两者都不受 `_localize` 影响）;
      4. 放行 `cp`（`go`）⇒ 旧写法必然读不到 `deploy.sh`、新写法读自己的目录不受影响。
    """
    shared_tmp = tmp_path / f"shared-{tag}"
    shared_tmp.mkdir()
    _clean_shared_namespace()      # 清掉上一次残留（**先等产生方退出** —— 见 #5344）
    victim = _mkrun(tmp_path, f"{tag}-run", slow_cp=True)
    p = _spawn(victim, command, shared_tmp)
    mark = victim["dir"] / "cp-window"
    deadline = time.monotonic() + 60.0
    try:
        while time.monotonic() < deadline and p.poll() is None:
            if mark.exists():
                break
            time.sleep(0.01)
        assert mark.exists(), "等不到 victim 进入 `cp` 窗口 —— 复现夹具失效，不得据此宣称新写法更安全"
        # 「另一个 run 的 rm -rf」：旧写法删的就是这个共享目录（这就是 issue #4625 的竞态窗口）
        shutil.rmtree(NS_SRC, ignore_errors=True)
        (victim["dir"] / "go").touch()
        out, _ = p.communicate(timeout=60)
    finally:
        # victim 无论成败都不得留成活产生方（否则下一次清理就是"删完再让子进程写"）
        _terminate_producer(p)
    return p.returncode, out


def test_old_bootstrap_loses_source_when_another_run_rm_rf(tmp_path):
    """**旧写法**：`cp` 窗口内共享源码目录被删 ⇒ 必现线上那条 `cp: … No such file or directory`。

    这条就是 issue #4625 的本地复现（`run 35458389055` 的 `Output` 解出来正是这句）。
    """
    old_cmd = extract_bootstrap(inject_old_bootstrap(read_script()))
    rc, out = _run_with_collision(tmp_path, old_cmd, "old")
    assert rc != 0, f"旧写法在源码目录被删后仍然成功（rc={rc}）⇒ 复现夹具失效：{out[-400:]}"
    # 判据钉**机制**（`cp` 读不到共享源码目录里的 deploy.sh）而不是某个平台的措辞：
    # GNU coreutils（线上 Ubuntu）= `cp: cannot stat '<path>': No such file or directory`，
    # macOS BSD cp（本地跑测试）= `cp: <path>: No such file or directory` —— 两者都命中下式。
    # ⚠️ 路径取**夹具命名空间** `NS_SRC`（#5344 的按进程隔离）：判据是"失败的正是旧写法用的
    # 那个共享源码目录"，与它叫什么名字无关；`/tmp/migao-src` 这个**字面**仍由静态判据钉住
    # （`check_bootstrap` / `test_bootstrap_has_no_shared_fixed_path`）。
    assert f"{NS_SRC}/deploy/swas/deploy.sh" in out and "No such file or directory" in out, (
        f"旧写法的报错未复现线上形态：{out[-400:]}"
    )


def test_new_bootstrap_survives_another_run_rm_rf(tmp_path):
    """**新写法**：同样的删除动作**碰不到**它 —— 源码目录是 `mktemp -d` 的 per-run 唯一路径。

    红证方向自证：同一条删除语句、同一个夹具，只把命令串换成脚本当前文本 ⇒ 结果翻转。
    """
    new_cmd = check_bootstrap(read_script())
    rc, out = _run_with_collision(tmp_path, new_cmd, "new")
    assert rc == 0, f"新写法仍失败（rc={rc}）：{out[-600:]}"
    assert "No such file or directory" not in out, f"新写法出现 `cp` 找不到文件：{out[-400:]}"
    assert "stub-deploy sha-testtag" in out, f"新写法的 deploy.sh 没有被执行：{out[-400:]}"


def test_shared_namespace_is_process_local():
    """**类级元守卫（#5344 / §23 G1）**：碰撞夹具的共享路径必须**与本进程绑定**。

    病根 = 夹具操作**机器级**固定路径 ⇒ 并发跑同一文件的另一个 pytest 会话就是"另一个 run"
    （实测 3 并发 ×3 轮 **6/9 红**，形态恒为 `断言 mark.exists()` 失败）。
    注入式红证：把 `NS_SRC` / `NS_TAR` 注回 `SHARED_SRC` / `SHARED_TAR` ⇒ 本判据**必红**。
    """
    assert NS_SRC != SHARED_SRC and NS_TAR != SHARED_TAR, (
        f"夹具又用回了机器级固定路径（NS_SRC={NS_SRC!r}）—— 并发会话会互相 rm -rf（#5344）"
    )
    assert NS_SRC.endswith(f"-{os.getpid()}") and NS_TAR.endswith(f"-{os.getpid()}.tar.gz"), (
        f"命名空间没绑到本进程：NS_SRC={NS_SRC!r} / NS_TAR={NS_TAR!r}"
    )


def test_namespace_cleanup_waits_for_a_live_producer():
    """**类级元守卫（#5344 判据 1）**：清理夹具命名空间必须**先等产生方退出**。

    形态 = "不许删完再让子进程写"：产生方**真在写**（32MB，写完才退出）+ 显式握手
    （`started` 落盘 ⇒ "已开始写且还没退出"在**结构上**确定，余量约 10⁴ 倍 —— 不是用
    `sleep` 凑时序、也不是重试掩盖）。
    注入式红证：把 `_clean_shared_namespace()` 里的 `_wait_for_producers()` 注回"直接 rm -rf"
    ⇒ 第一条断言**必红**（`waited == []`，而当时产生方仍然活着）。
    """
    src = Path(NS_SRC)
    src.parent.mkdir(parents=True, exist_ok=True)
    payload = 32 * 1024 * 1024      # 与 `_torn_trials` 的 FILLER 同款：把"仍在写"放大到稳定可观测
    p = subprocess.Popen(
        ["bash", "-c", f'mkdir -p "{src}" && : > "{src}/started" && '
                       f'head -c {payload} /dev/zero > "{src}/payload"'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _PRODUCERS.append(p)
    try:
        deadline = time.monotonic() + 10.0
        while not (src / "started").exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert (src / "started").exists(), "产生方没起来 ⇒ 夹具失效，不得据此判绿"
        assert p.poll() is None, "产生方已退出 ⇒ 「等它退出」的前提不成立（夹具失效）"
        waited = _clean_shared_namespace()
        assert waited == [p.pid], (
            f"清理没有等产生方退出：waited={waited}，而 pid={p.pid} 当时仍在写 —— "
            "这正是 #5344 的竞态形态（删完再让子进程写）"
        )
        assert p.poll() is not None, "声明等了，却没等到它退出"
        assert not src.exists(), "命名空间没被清掉（清理入口失效）"
    finally:
        p.kill()
        p.wait(timeout=10)
        _PRODUCERS.clear()


def test_bootstrap_per_run_dirs_are_unique(tmp_path):
    """两个 run 的源码目录 / 临时包必须**各不相同**（这就是"不互相踩"的机制证据）。"""
    cmd = check_bootstrap(read_script())
    shared_tmp = tmp_path / "shared"
    shared_tmp.mkdir()
    logs = []
    for i in range(2):
        run = _mkrun(tmp_path, f"uniq-{i}", slow_cp=False)
        p = _spawn(run, cmd, shared_tmp)
        out, _ = p.communicate(timeout=60)
        assert p.returncode == 0, f"第 {i} 个 run 失败：{out[-400:]}"
        logs.append(run["log"].read_text().splitlines())
    targets = [ln for ls in logs for ln in ls]
    assert len(targets) == 2, f"桩 curl 未被调用两次：{targets}"
    assert targets[0] != targets[1], f"两个 run 的下载目标相同（{targets}）⇒ per-run 唯一性失效"
    # 收尾必须清掉自己的临时产物（不许在共享 /tmp 留垃圾）
    leftovers = list(shared_tmp.iterdir())
    assert not leftovers, f"bootstrap 收尾未清理自己的临时产物：{leftovers}"


def test_bootstrap_propagates_deploy_exit_code(tmp_path):
    """deploy.sh 失败 ⇒ bootstrap 必须**原样**返回它的退出码（本仓纪律：失败必须显式非零）。

    红证：把 `exit $rc` 换成 `exit 0` ⇒ 本测试必红（见参数化用例的「退出码被写死」格）。
    """
    cmd = check_bootstrap(read_script())
    shared_tmp = tmp_path / "shared"
    shared_tmp.mkdir()
    run = _mkrun(tmp_path, "exitcode", slow_cp=False)
    _make_fixture_tarball(run["tarball"], "#!/bin/bash\nexit 42\n")
    p = _spawn(run, cmd, shared_tmp)
    out, _ = p.communicate(timeout=60)
    assert p.returncode == 42, (
        f"deploy.sh 退出 42，bootstrap 却返回 {p.returncode} —— 退出码被吞掉了。\n输出：{out[-400:]}"
    )
    leftovers = list(shared_tmp.iterdir())
    assert not leftovers, f"bootstrap 收尾未清理自己的临时产物：{leftovers}"


# 5. 原子替换的判别力（cp 必撕裂 / mv -f 必不撕裂）
# --------------------------------------------------------------------------

FILLER = 12 * 1024 * 1024   # 放大内容差异，让 cp 的「截断+写入」窗口可稳定观测


def _install_fragment(kind: str, src: Path, dest: Path) -> str:
    """安装 deploy.sh 的片段，`$SRC` 代入 `src`、目标代入 `dest`。

    - `kind == "cp"`：旧写法（`cp` 直接覆盖目标，截断+写入）
    - `kind == "mv"`：**从真脚本里逐字解析**出的新写法（临时名 + `mv -f`）
    """
    if kind == "cp":
        return f'cp "{src}" "{dest}";'
    cmd = check_bootstrap(read_script())
    m = re.search(
        r'cp\s+"\$SRC"/deploy/swas/deploy\.sh\s+\S*\.deploy\.sh\.new\s*&&\s*'
        r'mv\s+-f\s+\S*\.deploy\.sh\.new\s+/opt/migao-deploy/deploy\.sh',
        cmd,
    )
    assert m, "解析不到新写法的安装片段（判据已过期）"
    return (
        m.group(0)
        .replace('"$SRC"/deploy/swas/deploy.sh', f'"{src}"')
        .replace("/opt/migao-deploy/deploy.sh", f'"{dest}"')
        .replace("&&", ";")
        + ";"
    )


def _torn_trials(tmp_path: Path, kind: str, trials: int = 3) -> int:
    """并发「写 deploy.sh」与「读 deploy.sh」，返回读到**半成品**的试验次数。"""
    torn = 0
    for trial in range(trials):
        run_dir = tmp_path / f"torn-{kind}-{trial}"
        run_dir.mkdir(parents=True, exist_ok=True)
        src_old = run_dir / "old-src.sh"
        src_new = run_dir / "new-src.sh"
        src_old.write_text("# OLD\n" + "A" * FILLER, encoding="utf-8")
        src_new.write_text("# NEW\n" + "B" * FILLER, encoding="utf-8")
        want_old, want_new = src_old.read_bytes(), src_new.read_bytes()
        dest = run_dir / "deploy.sh"
        dest.write_bytes(want_old)
        frag = _install_fragment(kind, src_new, dest)
        script = f"set -u\nfor i in $(seq 1 60); do {frag} done\n"
        writer = subprocess.Popen(["bash", "-c", script], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10.0
        while writer.poll() is None and time.monotonic() < deadline:
            try:
                data = dest.read_bytes()
            except OSError:
                continue
            if data != want_old and data != want_new:
                torn += 1
                break
        writer.wait(timeout=60)
    return torn


def test_cp_install_tears_and_mv_install_does_not(tmp_path):
    """装 `deploy.sh` 的**原子性**判别力：`cp` 形态必见撕裂、`mv -f` 形态必不见。

    读者模型 = 「另一个 run 正在安装的同时，`bash /opt/migao-deploy/deploy.sh` 启动」：
    读到既不是旧内容、也不是新内容的**半成品**即判撕裂。
    """
    assert _torn_trials(tmp_path, "cp") > 0, (
        "`cp` 形态在 3 次试验里一次都没被读到半成品 ⇒ 该红证没有判别力"
        "（要么文件太小、要么读者循环没跑起来），不得据此宣称 `mv` 更安全"
    )
    assert _torn_trials(tmp_path, "mv") == 0, "`mv -f` 形态出现撕裂 ⇒ 原子性不成立"
