# case_ids: MC-012
"""小布 H5 视觉腿的「产物新鲜度」护栏（issue #4249）。

## 守的这颗地雷（夹具是**真文件 + 真子进程**，不 mock 判据：判据本体就是「内容指纹 vs 产物」，
mock 掉等于把被测对象换成替身 ⇒ 红证变假绿）

`tests/playwright.xiaobu.config.ts` 曾把**构建与起服务写在同一条 `webServer.command` 里**，
而本地 `reuseExistingServer: true`：

```ts
command: [ 'TARO_APP_API_URL=… TARO_APP_AI_API_URL=…',
           'npx taro build --type h5 >/dev/null 2>&1;',   // ← 构建在 webServer 命令里
           'python3 -m http.server 10086 --directory dist' ].join(' '),
reuseExistingServer: !process.env.CI,
```

只要 10086 上**已经有一个静态服务在听**（上一次跑留下的 / 另一个会话起的），Playwright 直接复用它
⇒ **整条命令一步都不执行**（含 `taro build`）⇒ 服务的是**旧 `dist/`**。
实测形态：`--update-snapshots` 跑出 `8 passed`（全绿），但基线 PNG **逐字节没变**（md5 与已提交版本相同），
而页面实际已改版 —— 「DOM 断言绿 + 截图基线被写成旧画面」两件事同时发生而**没有任何东西变红**；
错基线一旦提交，之后真实视觉回归会被它**永久放行**（假绿）。CI 侧 `CI=true` ⇒ `reuseExistingServer: false`
且构建在 workflow 里单独跑 ⇒ 不受影响 ⇒ **本地/CI 行为分叉**。

## 用例分六组（每组都要有判别力，不是「跑通就算」）

① **静态：构建与起服务解耦**（`find_build_in_webserver`）—— `webServer` 块里不得出现构建痕迹，
   且 `tests/playwright*.config.ts` **全族**都不得混写（同族核对表落成判据，不只落成散文）。
② **静态：静默复用已关闭** —— `reuseExistingServer` 必须是字面量 `false`（CI 侧本来就是 false，
   故该断言不改变 CI 行为，只堵死本地「复用旧服务」）。
③ **静态：护栏真的接进了配置** —— 配置里必须调用 `xiaobu_dist_freshness.py`，且调用点**在
   `webServer:` 之前**（配置加载期前置断言 = 起服务之前跑）；CI 走 `check`、本地走 `ensure`
   （`process.env.CI ? 'check' : 'ensure'`）⇒ **CI 侧不构建**；CI 对 `exit 3`（未判定）只告警不阻塞。
④ **运行期：陈旧必红 / 新鲜必绿**（真子进程跑 CLI）—— 源码指纹不匹配 ⇒ exit 1 且给可行动信息
   （点名重建命令）；指纹缺失 ⇒ **exit 3（未判定 ≠ 通过）**；`dist` 关键产物缺失 ⇒ exit 1。
⑤ **运行期：判据不依赖 mtime 精度**（§19.2 ③）—— 两个方向都钉住：指纹陈旧但 `dist` mtime 更新 ⇒ 仍红；
   指纹新鲜但 `dist` mtime 更旧 ⇒ 仍绿（mtime 判据在这两种形态上都会给出相反结论）。
⑥ **运行期：构建步骤本身失败必红 + 已新鲜不重建** —— 构建非零退出 ⇒ exit 1 且把构建输出尾巴带出来
   （旧写法 `>/dev/null 2>&1;` 把构建失败**吞掉**，服务照起）；产物已新鲜 ⇒ 不重建（快路径）。

## 边界（照实登记，别把「有护栏」读成「无死角」）

- 「构建退出 0 但产物逐字节不变」与「产物本来就是最新的」在**内容层不可区分**（区分只能靠 mtime，
  §19.2 ③ 明令禁止）⇒ 护栏强度 = 「构建步骤确实跑过（退出 0）+ 产物与本次指纹自洽」，
  与 `frontend/mini-app/e2e/lib/harness.js: assertDistFresh` 同强度。
- 指纹覆盖 `src/` + `config/` + 根级构建输入（`package.json` 等），**不含依赖树内容**（同 weapp 口径）。
- CI 侧无指纹（workflow 只跑 `npm run build:h5`，本包无权改 `.github/**`）⇒ CI 走 `check` 且
  「未判定」不阻塞 —— CI 的保证仍来自 workflow 的步骤顺序，**本护栏不新增 CI 侧强度**（也不改其行为）。

case_ids 口径：本测试属 **dev/CI 工具链**，与同族 `test_red_proof_guard.py`（#4260）、
`test_stranding_check.py`（#4065）沿用同一组 case id（`MC-012`）—— 仓库目前没有「开发工具链」用例族，
本 PR **未新建**用例：塞进行为用例库会污染覆盖矩阵（同族 PR 的既有裁定）。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
CONFIG = TESTS_DIR / "playwright.xiaobu.config.ts"
GUARD = TESTS_DIR / "xiaobu_dist_freshness.py"

# append（**不是** insert）：只作兜底解析路径，避免遮蔽 app/ 或 site-packages 里的同名模块。
sys.path.append(str(TESTS_DIR))

import xiaobu_dist_freshness as guard  # noqa: E402

# 「构建」在 webServer 命令里的痕迹（同族扫描用；`npm run dev` 不算构建）
BUILD_MARKERS = ("taro build", "npm run build", "build:h5", "build:weapp")


# ── 静态判据（纯文本，可对任意版本的配置文本跑 —— 红证靠它取 origin/main 的旧文本）──

def _slice_block(text: str, key: str) -> str:
    """取 `key: { … }` 括号配平的一段（跳过字符串字面量，避免被字符串里的括号带偏）。"""
    m = re.search(r"\b" + re.escape(key) + r"\s*:\s*\{", text)
    if not m:
        return ""
    depth = 0
    i = m.end() - 1
    while i < len(text):
        ch = text[i]
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < len(text) and text[i] != quote:
                i += 2 if text[i] == "\\" else 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[m.start(): i + 1]
        i += 1
    raise AssertionError(f"配置里 `{key}` 的括号未配平：{text[m.start():m.start() + 40]!r}")


def find_build_in_webserver(text: str) -> list:
    """`webServer` 块里的构建痕迹（空 = 起服务只负责服务）。"""
    block = _slice_block(text, "webServer")
    return [marker for marker in BUILD_MARKERS if marker in block]


def find_reuse_setting(text: str) -> str:
    """`reuseExistingServer` 的右值原文（空字符串 = 配置里没有这一项）。"""
    block = _slice_block(text, "webServer")
    m = re.search(r"reuseExistingServer\s*:\s*([^,\n]+)", block)
    return m.group(1).strip() if m else ""


def scan_family_webserver_builds() -> dict:
    """全族扫描：`tests/playwright*.config.ts` → 各自 webServer 块里的构建痕迹。"""
    found = {}
    for path in sorted(TESTS_DIR.glob("playwright*.config.ts")):
        found[path.name] = find_build_in_webserver(path.read_text(encoding="utf-8"))
    return found


def test_webserver_command_does_not_mix_build_and_serve():
    hits = find_build_in_webserver(CONFIG.read_text(encoding="utf-8"))
    assert hits == [], (
        f"`webServer.command` 里仍有构建痕迹 {hits} —— 本地 reuseExistingServer 会让整条命令"
        "（含构建）一步都不执行 ⇒ 静默服务旧 dist（issue #4249）。构建必须在配置加载期显式执行，"
        "webServer 只负责起静态服务。"
    )


def test_no_playwright_config_mixes_build_into_webserver():
    offenders = {name: hits for name, hits in scan_family_webserver_builds().items() if hits}
    assert offenders == {}, f"同族配置仍把构建混进 webServer 命令：{offenders}"


def test_reuse_existing_server_is_disabled():
    setting = find_reuse_setting(CONFIG.read_text(encoding="utf-8"))
    assert setting == "false", (
        f"`reuseExistingServer` = `{setting or '(缺失)'}` —— 复用外部/遗留服务时，"
        "Playwright 会跳过整条 webServer 命令（含构建），且可能服务**另一个检出**的 dist。"
        "必须显式 false：端口被占 ⇒ 报错退出（可行动），而不是静默复用。"
    )


def test_config_runs_freshness_guard_before_webserver_block():
    text = CONFIG.read_text(encoding="utf-8")
    guard_at = text.find("xiaobu_dist_freshness.py")
    webserver_at = text.find("webServer:")
    assert guard_at >= 0, "配置里没有接产物新鲜度护栏（issue #4249 的 assertDistFresh 等价物）"
    assert guard_at < webserver_at, (
        "新鲜度护栏必须写在配置加载期（`webServer:` 之前）—— 放在测试体/globalSetup 里"
        "不能保证早于静态服务启动。"
    )


def test_ci_mode_checks_without_building_and_does_not_block_on_undecidable():
    text = CONFIG.read_text(encoding="utf-8")
    assert re.search(r"process\.env\.CI\s*\?\s*'check'\s*:\s*'ensure'", text), (
        "CI 侧必须走 `check`（**不构建**，构建由 workflow 负责）而本地走 `ensure`（显式构建）"
        "—— 否则等于改了 CI 侧行为。"
    )
    assert re.search(r"status\s*===\s*3", text), (
        "CI 侧对 exit 3（未判定：无构建指纹）必须只告警不阻塞 —— 否则 CI 会因缺少本地构建指纹而假红。"
    )
    assert "'python3 -m http.server 10086 --directory dist'" in text, (
        "CI 侧「只起静态服务」的命令必须保持原样（行为等价自证）。"
    )


# ── 运行期判据（真子进程 + 真文件；夹具项目自带 src/ 与 dist/）──

def make_project(tmp_path: Path, src_body: str = "A", dist_body: str = "<html>built-from-A</html>") -> Path:
    root = tmp_path / "mini-app"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.ts").write_text(src_body, encoding="utf-8")
    (root / "dist").mkdir()
    (root / "dist" / "index.html").write_text(dist_body, encoding="utf-8")
    return root


def run_guard(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GUARD), *args],
        capture_output=True, text=True, timeout=180,
    )


def test_fresh_dist_passes(tmp_path):
    root = make_project(tmp_path)
    guard.write_stamp(root)
    r = run_guard("check", "--project", str(root))
    assert r.returncode == 0, f"新鲜产物被判红（假红）：\n{r.stdout}\n{r.stderr}"


def test_stale_source_fingerprint_is_red_with_actionable_hint(tmp_path):
    root = make_project(tmp_path)
    guard.write_stamp(root)
    (root / "src" / "app.ts").write_text("B", encoding="utf-8")  # 源码变了、dist 没重建
    r = run_guard("check", "--project", str(root))
    out = r.stdout + r.stderr
    assert r.returncode == 1, f"陈旧产物没被判红（这正是本单要治的假绿）：\n{out}"
    assert "npm run build:h5" in out, f"报错没给可行动信息（重建命令）：\n{out}"
    assert "指纹" in out, f"报错没点名判据（内容指纹）：\n{out}"


def test_dist_changed_after_build_is_red(tmp_path):
    root = make_project(tmp_path)
    guard.write_stamp(root)
    (root / "dist" / "index.html").write_text("<html>someone-else</html>", encoding="utf-8")
    r = run_guard("check", "--project", str(root))
    assert r.returncode == 1, f"产物在落指纹之后被替换却判绿：\n{r.stdout}\n{r.stderr}"


def test_missing_dist_artifact_is_red(tmp_path):
    root = make_project(tmp_path)
    guard.write_stamp(root)
    (root / "dist" / "index.html").unlink()
    r = run_guard("check", "--project", str(root))
    assert r.returncode == 1, f"关键产物缺失却判绿：\n{r.stdout}\n{r.stderr}"


def test_missing_stamp_is_undecidable_not_pass(tmp_path):
    root = make_project(tmp_path)
    r = run_guard("check", "--project", str(root))
    assert r.returncode == 3, (
        f"无构建指纹（无法判定）必须 exit 3，绝不能是 0（「看不了」不得当「没问题」）："
        f"\n{r.stdout}\n{r.stderr}"
    )


def test_verdict_does_not_depend_on_mtime(tmp_path):
    # ① 指纹陈旧，但 dist mtime 比 src 新 ⇒ 仍须红（mtime 判据会误判成「新鲜」）
    stale = make_project(tmp_path / "a")
    guard.write_stamp(stale)
    (stale / "src" / "app.ts").write_text("B", encoding="utf-8")
    now = 1_700_000_000
    os.utime(stale / "src" / "app.ts", (now, now))
    os.utime(stale / "dist" / "index.html", (now + 3600, now + 3600))
    r1 = run_guard("check", "--project", str(stale))
    assert r1.returncode == 1, f"指纹陈旧但 mtime 新 ⇒ 被 mtime 判据放行：\n{r1.stdout}\n{r1.stderr}"

    # ② 指纹新鲜，但 dist mtime 比 src 旧 ⇒ 仍须绿（mtime 判据会误判成「陈旧」）
    fresh = make_project(tmp_path / "b")
    guard.write_stamp(fresh)
    os.utime(fresh / "src" / "app.ts", (now + 3600, now + 3600))
    os.utime(fresh / "dist" / "index.html", (now, now))
    r2 = run_guard("check", "--project", str(fresh))
    assert r2.returncode == 0, f"指纹新鲜但 mtime 旧 ⇒ 被 mtime 判据误报陈旧：\n{r2.stdout}\n{r2.stderr}"


def test_source_hash_is_content_based(tmp_path):
    root = make_project(tmp_path)
    first = guard.compute_source_hash(root)["hash"]
    os.utime(root / "src" / "app.ts", (1, 1))  # 只动 mtime、内容不变
    assert guard.compute_source_hash(root)["hash"] == first, "只改 mtime 就换了指纹 ⇒ 判据退化成 mtime"
    (root / "src" / "app.ts").write_text("A2", encoding="utf-8")
    assert guard.compute_source_hash(root)["hash"] != first, "源码内容变了指纹却没变 ⇒ 判据漏报"


def test_ensure_build_failure_is_red_and_visible(tmp_path):
    root = make_project(tmp_path)
    r = run_guard("ensure", "--project", str(root), "--build-cmd", "echo BOOM >&2; exit 7")
    out = r.stdout + r.stderr
    assert r.returncode == 1, f"构建非零退出却没判红（旧写法把构建失败吞掉）：\n{out}"
    assert "构建失败" in out, f"报错没点名构建失败：\n{out}"
    assert "BOOM" in out, f"构建输出尾巴没带出来（不可行动）：\n{out}"


def test_ensure_builds_and_stamps(tmp_path):
    root = make_project(tmp_path, dist_body="<html>OLD</html>")
    build = "printf '%s' '<html>NEW</html>' > dist/index.html"
    r = run_guard("ensure", "--project", str(root), "--build-cmd", build)
    assert r.returncode == 0, f"构建成功后仍判红：\n{r.stdout}\n{r.stderr}"
    assert (root / "dist" / "index.html").read_text(encoding="utf-8") == "<html>NEW</html>"
    assert (root / "dist" / ".build-stamp.json").exists(), "构建后没落构建指纹 ⇒ 下次无法判定新鲜度"
    assert run_guard("check", "--project", str(root)).returncode == 0


def test_ensure_skips_build_when_dist_already_fresh(tmp_path):
    root = make_project(tmp_path)
    guard.write_stamp(root)
    r = run_guard("ensure", "--project", str(root), "--build-cmd", "exit 9")
    assert r.returncode == 0, (
        f"产物已新鲜却仍重建（快路径失效 ⇒ 每次跑都白构建）：\n{r.stdout}\n{r.stderr}"
    )


def test_ensure_removes_stale_stamp_before_building(tmp_path):
    # 构建失败时绝不能留下一个「声称新鲜」的旧指纹（否则下次 check 会假绿）
    root = make_project(tmp_path)
    guard.write_stamp(root)
    (root / "src" / "app.ts").write_text("B", encoding="utf-8")
    r = run_guard("ensure", "--project", str(root), "--build-cmd", "exit 5")
    assert r.returncode == 1
    assert not (root / "dist" / ".build-stamp.json").exists(), (
        "构建失败却留着旧指纹 ⇒ 下次 check 读到它 ⇒ 假绿"
    )
