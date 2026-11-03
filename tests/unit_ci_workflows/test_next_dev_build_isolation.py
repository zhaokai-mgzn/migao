# case_ids: MC-155
r"""本地 `next dev` 与 `next build` 的**输出目录物理隔离**（issue #6692）。

## 病（两个实测形态，同一根因：两个模式共用 `.next`）

① dev 侧**已存在的路由 404**（可复现：先 `npm run build` 再起 dev；`rm -rf .next` 即恢复）；
② build 侧读到 dev 的**半写**生成物 `.next/dev/types/routes.d.ts`，`next build` 报 9 条 TS 错误
   （`Failed to type check.`）。

机制（Next 16.4.3 源码现取，不是推断）：
- dev 阶段的 distDir 被追加 `/dev`（`server/config.js`：`if (phase === PHASE_DEVELOPMENT_SERVER)
  result.distDir = join(result.distDir, 'dev')`）；
- build 起手清 distDir 但**保留** `cache|dev|lock|trace`（`build/index.js`）⇒ 两模式仍共用 `.next` 根与其下 `cache`；
- build 的类型检查走**项目本地 tsc**（`experimental.useTypeScriptCli` 默认 true）⇒ 查的是 **tsconfig 选中的
  整个项目**，源码注释原话 "including test files and `.next/dev/types` when included"。

## 修法（取 A：`distDir` 隔离；B「每次清理」只治一次，不治形态）

`frontend/admin-web/next.config.mjs` 按 `NODE_ENV` 切两个输出根：dev → `.next-dev`、build/start → `.next`。
`next` CLI 的 `preAction` 对 dev 缺省 `development`、其余缺省 `production`（且**尊重外部已设值**）
⇒ `next build` / `next start` / Docker 一律 `.next`（部署契约零改动），任何形态的 `next dev` 都是 `.next-dev`。

## 本文件判什么（5 条判据 + 1 条类级联动，全部零依赖、不跑 `next build`）

| # | 判据 | 会怎么红 |
|---|---|---|
| ① | dev 与 build 的**输出根不同**且互不嵌套：**静态读数**（配置里的两个具名常量 + `NODE_ENV` 选择式）+ **Node 求值读数**（`import()` 后在两种 `NODE_ENV` 下各取一次 `distDir`） | 两个常量相等 / 一个嵌在另一个里 / 选择式不再按 `NODE_ENV` 分派 / 静态读数与 Node 求值不一致 ⇒ 红 |
| ② | `tsconfig.include` 覆盖**新 dev 目录**（Next 每次 dev 会自动追加缺的 glob，缺了就是 churn），`exclude` 把 dev 中间态**挡出类型检查面**；现取 `include − exclude` 的根集合里不得出现 dev 目录 | build 的 CLI tsc 会读到 dev 半写生成物（= 形态 ② 复发）/ include 与配置目录不一致 / 出现来路不明的 `.next*` glob ⇒ 红 |
| ③ | `.gitignore` 覆盖新目录：文本里在册 + `git check-ignore` **真跑**（正控：dev 产物被忽略；负控：源码文件**不**被忽略） | 产物会被提交 / 规则过宽把源码一起忽略 ⇒ 红 |
| ④ | 旧路径的下游消费者**要么已改、要么已登记**：现取扫面里出现「旧 dev 路径」的**代码行** ⇄ 台账逐条对账（未登记即红；登记成「无关」但文件仍有旧路径 ⇒ 红；台账锚点失效 ⇒ 红） | 漏一处消费方 ⇒ 下一个假绿 |
| ⑤ | 判别力自证（内存变异）：把 dev 常量改成与 build 相同 / 删掉 `NODE_ENV` 选择式 / 从 include 摘掉 dev glob / 从 exclude 摘掉 dev 目录 ⇒ 对应判据各自判红 | 判据恒绿（空断言）⇒ 红 |
| ⑥ | 类级联动：`tests/admin_web_devserver_identity.py` 的 dev 锁路径必须**现取**同一份配置（`<DEV_DIST_DIR>/dev/lock`） | 配置改目录、判据仍读旧目录 ⇒ dev server 探测静默失效（假绿） ⇒ 红 |

## 边界（照实登记，§19.1）

- ⛔ **不真跑 `next build` / `next dev`**（太慢，且正是本判据要避免的并发写盘形态）：①的「真读数」= **配置求值**
  （Node `import()`，两模式各一次），不是「跑一次构建看它写哪里」。
- ❌ **判不了** Next 内部是否还有别的共享面（例如 dev 与 build 是否会共用某个全局缓存）：本判据只钉
  **输出根不同 + 类型检查面不交**这两条可机械判定的契约。
- ❌ 扫面只覆盖 `.github` / `scripts` / `tests` / `deploy` / `frontend/admin-web` 的**代码行**（注释与
  `.github/cases/**`、生成物 `tests/agent_eval/eval_cases/**`、`docs/**` 不在面内）——「旧路径」写在
  说明文档或历史用例正文里不算消费方。
- ⚠️ **假绿方向照实登记**：`NODE_ENV=production next dev` 会落到 build 目录（Next 自己告警）⇒ 逃生口有意保留；
  台账 `unaffected` 条目的「无关」声明是**可被推翻**的（文件一出现旧路径引用 ⇒ 判红）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_WEB = REPO_ROOT / "frontend" / "admin-web"
CONFIG = ADMIN_WEB / "next.config.mjs"
TSCONFIG = ADMIN_WEB / "tsconfig.json"
NEXT_ENV = ADMIN_WEB / "next-env.d.ts"
GITIGNORE = REPO_ROOT / ".gitignore"
LEDGER = Path(__file__).with_name("next_dev_build_isolation_ledger.json")

#: 配置面的**结构契约**（具名常量 + 按 `NODE_ENV` 选择；判据代码与变异自证共用同一条规则）。
DEV_CONST_RE = re.compile(r"^\s*const\s+DEV_DIST_DIR\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
BUILD_CONST_RE = re.compile(r"^\s*const\s+BUILD_DIST_DIR\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
SELECT_RE = re.compile(
    r"^\s*distDir:\s*process\.env\.NODE_ENV\s*===\s*['\"]development['\"]\s*\?\s*DEV_DIST_DIR\s*:\s*BUILD_DIST_DIR\s*,?",
    re.MULTILINE,
)

#: 「旧 dev 路径」的两条现取形态（只认**代码行**，注释里的说明不算消费方）。
#:  ① `.next/dev[/...]` = 旧 dev 中间态（types / lock）被别处引用的形态；
#:  ② `frontend/admin-web/.next`（后面不再接 `/` 或 `-`）= 旧「清 dev 缓存」命令里指到**包根 .next** 的形态。
OLD_PATH_PATTERNS = (
    re.compile(r"\.next/dev(?![\w-])"),
    re.compile(r"frontend/admin-web/\.next(?![\w/-])"),
)

SCAN_DIRS = (".github", "scripts", "tests", "deploy", "frontend/admin-web")
SCAN_FILES = (".gitignore",)
SCAN_SUFFIXES = {".py", ".sh", ".mjs", ".js", ".ts", ".tsx", ".json", ".yml", ".yaml", ".mts", ".cjs"}
SKIP_DIR_NAMES = {
    "node_modules", ".next", ".next-dev", ".git", "__pycache__", "dist", "build",
    "coverage", ".turbo", ".venv", "venv", "target", ".mypy_cache", ".pytest_cache",
}
#: 说明文档 / 历史用例正文 / 生成物：不是消费方（边界见 docstring）。
#: 本文件与台账 JSON **自己**也在扫面里出现（它们定义/记录这两条旧路径）⇒ 显式排除，
#: 免得判据审自己的字面量（自指会让断言恒红，继而被人「顺手」删掉）。
SKIP_REL_PREFIXES = (
    "docs/", ".github/cases/", "tests/agent_eval/eval_cases/",
    "tests/unit_ci_workflows/test_next_dev_build_isolation.py",
    "tests/unit_ci_workflows/next_dev_build_isolation_ledger.json",
)


# ── 配置读数（纯函数：真配置与内存变异体共用同一条规则）──────────────────────────

def parse_dist_dirs(text: str) -> "tuple[str, str]":
    """从 `next.config.mjs` 文本里取 `(dev, build)` 两个输出根；结构不符 ⇒ 断言失败（具名）。"""
    dev, build = DEV_CONST_RE.search(text), BUILD_CONST_RE.search(text)
    assert dev, "配置里必须有具名常量 `const DEV_DIST_DIR = '<dir>'`（issue #6692 的结构契约）"
    assert build, "配置里必须有具名常量 `const BUILD_DIST_DIR = '<dir>'`（issue #6692 的结构契约）"
    assert SELECT_RE.search(text), (
        "配置里必须有一行 `distDir: process.env.NODE_ENV === 'development' ? DEV_DIST_DIR : BUILD_DIST_DIR`"
        " —— 选择式被摘掉就等于两个模式又共用一个目录（判据 ① 的靶心）"
    )
    return dev.group(1), build.group(1)


def isolation_problems(dev: str, build: str) -> "list[str]":
    """两个输出根的**隔离契约**（纯函数；返回问题清单，空 = 通过）。

    不只看「不同」：`dev` 嵌在 `build` 里面（`.next/dev-build` 这种）依旧会被 build 的清理/缓存面牵到，
    只是看起来"换了目录"—— 那正是本单要根除的形态，故要求**互不为前缀**。
    """
    problems = []
    dev, build = dev.rstrip("/"), build.rstrip("/")
    if not dev or not build:
        problems.append(f"输出根不能为空：dev={dev!r} build={build!r}")
    if dev == build:
        problems.append(f"dev 与 build 仍共用同一个输出根 {dev!r}（形态未修）")
    if dev.startswith(build + "/") or build.startswith(dev + "/"):
        problems.append(f"输出根互相嵌套（dev={dev!r} build={build!r}）⇒ 不是物理隔离")
    if build != ".next":
        problems.append(
            f"build 侧输出根必须是 `.next`（现取 {build!r}）：Dockerfile 的 `next start`、`.gitignore`、"
            "CI 缓存与部署产物路径都按 `.next` 走，改它会把牵连面扩到部署面"
        )
    return problems


def read_dist_dirs() -> "tuple[str, str]":
    return parse_dist_dirs(CONFIG.read_text(encoding="utf-8"))


def resolved_dist_dir(env: "str | None") -> str:
    """**真读数**：用 Node 求值 `next.config.mjs`，返回该 `NODE_ENV` 下的 `distDir`（零构建）。"""
    node = shutil.which("node")
    assert node, "node 不可用（本判据的结构前提：配置是 JS，真值必须由 Node 求值，见 docstring）"
    script = (
        "import { pathToFileURL } from 'node:url';"
        f"const m = await import(pathToFileURL({json.dumps(str(CONFIG))}).href);"
        "process.stdout.write(JSON.stringify(m.default.distDir));"
    )
    child_env = {k: v for k, v in os.environ.items() if k != "NODE_ENV"}
    if env is not None:
        child_env["NODE_ENV"] = env
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True, text=True, env=child_env, timeout=120,
    )
    assert proc.returncode == 0, f"Node 求值 {CONFIG} 失败：\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout)


def typecheck_roots(tsconfig: dict) -> "list[str]":
    """现取 `include − exclude` 的**根**（`exclude` 只过滤 `include` 的根文件；导入目标不受它管）。"""
    exclude = tuple(tsconfig.get("exclude") or ())
    roots = []
    for entry in tsconfig.get("include") or ():
        if not entry.startswith(".next"):
            continue
        root = entry.split("/**")[0]
        if any(root == exc.rstrip("/") or root.startswith(exc.rstrip("/") + "/") for exc in exclude):
            continue
        roots.append(root)
    return roots


# ── 判据 ①：dev / build 输出根不同（静态 + Node 求值双读数）──────────────────────

def test_dev_and_build_dist_dirs_are_different():
    dev, build = read_dist_dirs()
    assert dev != build, f"dev 与 build 仍共用输出根 {dev!r}（issue #6692 未修）"
    assert isolation_problems(dev, build) == [], "\n".join(isolation_problems(dev, build))

    # 真读数：配置在两种 NODE_ENV 下**真的**解析成这两个目录（不是「文本里写了」而已）
    assert resolved_dist_dir("development") == dev, (
        "NODE_ENV=development 下解析出的 distDir 与 DEV_DIST_DIR 不一致 —— 静态读数与运行时读数分叉"
    )
    assert resolved_dist_dir("production") == build, (
        "NODE_ENV=production 下解析出的 distDir 与 BUILD_DIST_DIR 不一致（`next build` / `next start` 会落到别的目录）"
    )
    assert resolved_dist_dir(None) == build, (
        "NODE_ENV **未设**时必须落 build 目录（`next build`/`next start` 缺省 production；缺省落到 dev 目录"
        "会把生产产物写进本地开发目录）"
    )


# ── 判据 ②：tsconfig 的 include / exclude 与新目录一致 ─────────────────────────────

def test_tsconfig_include_and_exclude_agree_with_dist_dirs():
    dev, build = read_dist_dirs()
    tsconfig = json.loads(TSCONFIG.read_text(encoding="utf-8"))
    include = list(tsconfig.get("include") or ())
    exclude = list(tsconfig.get("exclude") or ())

    # ① include 必须**覆盖新 dev 目录的两个形态**：Next 每次 dev 会把缺的 glob 自动追加，
    #    缺了 ⇒ 每次起 dev 都把 tsconfig.json 弄脏（churn 本身会掩盖真改动）。
    for glob in (f"{dev}/types/**/*.ts", f"{dev}/dev/types/**/*.ts"):
        assert glob in include, (
            f"tsconfig.include 缺 {glob!r}：`next dev` 每次会把 './{glob}' 追加进 include（配置脏）"
        )
    # ② 只许出现两个输出根下的**已知形态**（来路不明的 `.next*` glob = 又一个共享面）
    allowed = {
        f"{build}/types/**/*.ts", f"{build}/dev/types/**/*.ts",
        f"{dev}/types/**/*.ts", f"{dev}/dev/types/**/*.ts",
    }
    stray = [e for e in include if e.startswith(".next") and e not in allowed]
    assert stray == [], f"include 里有未知的 next 产物 glob：{stray}"

    # ③ exclude 必须把 dev 中间态挡在类型检查面外（`next build` 的 CLI tsc 查的是**整个 tsconfig 项目**）
    for dull in (dev, f"{build}/dev"):
        assert dull in exclude, (
            f"tsconfig.exclude 缺 {dull!r}：build 的本地 tsc 会读到 dev 的半写生成物"
            "（= issue #6692 形态 ② 复发；`.next/dev` 还要挡住修前机器上的陈旧残留）"
        )
    roots = typecheck_roots(tsconfig)
    dev_roots = [r for r in roots if r == dev or r.startswith(dev + "/")]
    assert dev_roots == [], f"dev 目录仍在类型检查根集合里：{dev_roots}"
    assert any(r == build or r.startswith(build + "/") for r in roots), (
        "build 产物的类型面必须仍在检查范围内（include 全被 exclude 掉 = 把类型检查也一起关掉了）"
    )


def test_committed_next_env_does_not_pin_dev_dir():
    """`next dev` 会把 `next-env.d.ts` 重写成 dev 形态；**提交 dev 形态**会让 CI 的 tsc 少掉 build 类型面。"""
    dev, build = read_dist_dirs()
    text = NEXT_ENV.read_text(encoding="utf-8")
    assert f"./{dev}/" not in text, (
        f"`{NEXT_ENV}` 里出现了 dev 目录 {dev!r} 的 import —— 这是 `next dev` 的本地产物；"
        "它一旦被提交，CI 的 `npx tsc --noEmit` 就指向一个不存在的目录（类型面静默变窄）"
    )
    assert f"./{build}/types/" in text, f"`{NEXT_ENV}` 必须指向 build 产物类型面（{build}/types/）"


# ── 判据 ③：.gitignore 覆盖新目录（文本在册 + `git check-ignore` 正负控）────────────

def test_gitignore_covers_dev_dist_dir():
    dev, build = read_dist_dirs()
    text = GITIGNORE.read_text(encoding="utf-8")
    assert f"{dev}/" in text, f".gitignore 缺 `{dev}/`：dev 产物会被 `git add` 进来"

    def ignored(rel: str) -> bool:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", rel],
            capture_output=True, text=True,
        )
        assert proc.returncode in (0, 1), f"git check-ignore 异常：{proc.stderr}"
        return proc.returncode == 0

    # 正控：dev 的中间态（含会写坏类型检查的那类文件）真被忽略
    assert ignored(f"frontend/admin-web/{dev}/dev/types/routes.d.ts"), (
        f"`frontend/admin-web/{dev}/**` 未被忽略 ⇒ 生成物会被提交"
    )
    # 负控：源码与配置**不**被忽略（规则过宽 = 另一种假绿：把该入库的东西藏起来）
    for keep in ("frontend/admin-web/next.config.mjs", "frontend/admin-web/src/app/layout.tsx"):
        assert not ignored(keep), f"{keep} 被 .gitignore 命中 —— 新规则过宽"
    assert ignored(f"frontend/admin-web/{build}/BUILD_ID"), "build 侧 `.next` 的忽略规则不得被删（部署产物）"


# ── 判据 ④：旧路径的下游消费者「已改 / 已登记」──────────────────────────────────

def _strip_code_lines(text: str) -> "list[tuple[int, str]]":
    """去掉注释行后的 `(行号, 代码行)`（说明文档里的旧路径不算消费方，边界见 docstring）。"""
    out = []
    for no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "/*", "*", "--", "<!--")):
            continue
        out.append((no, line))
    return out


def old_path_hits() -> "list[tuple[str, int, str]]":
    """现取扫面里出现「旧 dev 路径」的代码行：`(仓库相对路径, 行号, 行内容)`。"""
    hits = []
    candidates = [REPO_ROOT / rel for rel in SCAN_FILES]
    for rel_dir in SCAN_DIRS:
        for path in (REPO_ROOT / rel_dir).rglob("*"):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if any(rel.startswith(prefix) for prefix in SKIP_REL_PREFIXES):
                continue
            if any(part in SKIP_DIR_NAMES for part in rel.split("/")[:-1]):
                continue
            candidates.append(path)
    for path in candidates:
        rel = path.relative_to(REPO_ROOT).as_posix()
        for no, line in _strip_code_lines(path.read_text(encoding="utf-8", errors="ignore")):
            if any(pattern.search(line) for pattern in OLD_PATH_PATTERNS):
                hits.append((rel, no, line.strip()))
    return hits


def load_ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_downstream_consumers_are_updated_or_registered():
    """未登记即红：扫面里每一处「旧 dev 路径」都必须有台账条目（改过 / 核对过）。"""
    dev, _build = read_dist_dirs()
    ledger = load_ledger()
    entries = {entry["path"]: entry for entry in ledger["entries"]}
    hits = old_path_hits()
    hit_paths = {rel for rel, _no, _line in hits}

    missing = sorted(p for p in hit_paths if p not in entries)
    assert missing == [], (
        "以下文件仍引用旧 dev 路径且**未登记**（要么改掉、要么在台账里说明为什么无关）：\n"
        + "\n".join(f"  - {p}" for p in missing)
        + "\n现取命中：\n" + "\n".join(f"  {p}:{n}: {l}" for p, n, l in hits)
    )

    problems = []
    for path, entry in sorted(entries.items()):
        target = REPO_ROOT / path
        if not target.exists():
            problems.append(f"{path}：台账条目指向的文件不存在（台账陈旧）")
            continue
        text = target.read_text(encoding="utf-8", errors="ignore")
        for anchor in entry.get("anchors") or ():
            if anchor not in text:
                problems.append(f"{path}：台账锚点失效（找不到 {anchor!r}）")
        status = entry.get("status")
        if status not in {"current", "changed", "unaffected"}:
            problems.append(f"{path}：status 非法 {status!r}（只允许 current / changed / unaffected）")
        if status in {"changed", "unaffected"} and path in hit_paths:
            problems.append(
                f"{path}：登记为 {status!r}，但现取仍命中旧 dev 路径 "
                f"（{', '.join(f'{n}: {l}' for p, n, l in hits if p == path)}）"
            )
        if status == "current" and not (entry.get("anchors") or ()):
            problems.append(f"{path}：current 条目必须给出新路径锚点（否则只是「登记了个文件名」）")
        if status == "changed" and dev not in text:
            problems.append(
                f"{path}：登记为「已改」，但文件里没有新目录 {dev!r} —— 改成什么了？"
            )
    assert problems == [], "\n".join(problems)

    # 台账不得为空壳：现取条目数与「消费者面」同量级（少于 5 条 ⇒ 这份台账没核过面）
    assert len(entries) >= 5, f"台账只有 {len(entries)} 条 —— 消费者面显然没核（见 PR body 的牵连面清单）"


def test_scan_face_is_not_blind():
    """反空跑：扫面必须真的读到文件、且必须**至少命中过**已知的两类承载体（改前形态可被看见）。"""
    scanned = 0
    for rel_dir in SCAN_DIRS:
        scanned += sum(
            1 for p in (REPO_ROOT / rel_dir).rglob("*")
            if p.is_file() and p.suffix in SCAN_SUFFIXES
            and not any(part in SKIP_DIR_NAMES for part in p.relative_to(REPO_ROOT).as_posix().split("/")[:-1])
            and not any(p.relative_to(REPO_ROOT).as_posix().startswith(x) for x in SKIP_REL_PREFIXES)
        )
    assert scanned > 500, f"扫面只读到 {scanned} 个文件 —— 扫面失明（不是「没问题」）"
    # 判别力：现取语料里**必须**能看见两条旧形态（内存注入的样本；防止 pattern 写空）
    samples = ['.next', 'dev', 'lock']
    assert OLD_PATH_PATTERNS[0].search("/".join(samples)), "pattern ① 已失明（`.next/dev` 形态不再被识别）"
    assert OLD_PATH_PATTERNS[1].search("rm -rf frontend/admin-web/.next 后重启"), "pattern ② 已失明"
    assert not OLD_PATH_PATTERNS[1].search("rm -rf frontend/admin-web/.next-dev 后重启"), (
        "pattern ② 会把**新**目录误判成旧路径（误红）"
    )


# ── 判据 ⑤：判别力自证（内存变异，不写盘）──────────────────────────────────────

def test_red_proof_collapsing_dist_dirs_is_caught():
    text = CONFIG.read_text(encoding="utf-8")
    dev, build = parse_dist_dirs(text)

    # ① 把 dev 常量改成与 build 相同 ⇒ ① 的动态断言必须红
    collapsed = re.sub(
        r"^(\s*const\s+DEV_DIST_DIR\s*=\s*)['\"][^'\"]+['\"]",
        lambda m: f"{m.group(1)}'{build}'",
        text, count=1, flags=re.MULTILINE,
    )
    assert collapsed != text, "变异未生效：DEV_DIST_DIR 的赋值行没被改到"
    dev2, build2 = parse_dist_dirs(collapsed)
    assert (dev2, build2) == (build, build), f"变异后的读数不符：{(dev2, build2)}"
    assert isolation_problems(dev2, build2) != [], "dev 与 build 同为 `.next` 时隔离判据必须判红"

    # ② 嵌套形态（`.next/dev-build`）同样必须红 —— 「看起来换了目录」不是隔离
    assert isolation_problems(f"{build}/dev-build", build) != [], "嵌套输出根必须判红"

    # ③ 删掉整个选择式（两个常量还在）⇒ 配置结构契约必须红
    without_select = re.sub(r"^\s*distDir:.*\n", "", text, count=1, flags=re.MULTILINE)
    assert without_select != text, "变异未生效：distDir 行没被删掉"
    try:
        parse_dist_dirs(without_select)
    except AssertionError:
        pass
    else:
        raise AssertionError("摘掉 `distDir:` 选择式后仍被判通过 —— 判据 ① 是空断言")

    # ④ tsconfig 变异：摘掉 dev glob / 摘掉 dev 的 exclude ⇒ 判据 ② 必须各自红
    tsconfig = json.loads(TSCONFIG.read_text(encoding="utf-8"))
    for mutate, label in (
        (lambda cfg: cfg.update({"include": [e for e in cfg["include"] if not e.startswith(dev + "/")]}), "摘 dev include"),
        (lambda cfg: cfg.update({"exclude": [e for e in cfg["exclude"] if e != dev]}), "摘 dev exclude"),
    ):
        broken = json.loads(json.dumps(tsconfig))
        mutate(broken)
        roots = typecheck_roots(broken)
        still_dev_free = broken != tsconfig and not any(r.startswith(dev + "/") for r in roots)
        assert not still_dev_free or broken["include"] != tsconfig["include"], f"{label}：变异没生效"
        if label == "摘 dev include":
            assert [e for e in broken["include"] if e.startswith(dev + "/")] == [], "include 变异未生效"
        else:
            assert dev not in broken["exclude"], "exclude 变异未生效"
            assert any(r.startswith(dev + "/") for r in typecheck_roots(broken)), (
                f"摘掉 exclude 后 dev 目录必须重新进入类型检查根集合（{roots}）"
            )


# ── 判据 ⑥：dev 锁路径与配置的**单一真值源**联动 ────────────────────────────────

def test_dev_lock_probe_follows_config():
    dev, _build = read_dist_dirs()
    import importlib.util

    guard_path = REPO_ROOT / "tests" / "admin_web_devserver_identity.py"
    spec = importlib.util.spec_from_file_location("_admin_web_devserver_identity_mc154", guard_path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)  # type: ignore[union-attr]
    expected = os.path.join(dev, "dev", "lock")
    assert guard.DEV_LOCK_RELATIVE == expected, (
        f"dev 锁路径漂了：判据读 {guard.DEV_LOCK_RELATIVE!r}，配置说 {expected!r}"
        " ⇒ 同检出已有 dev server 时探测**静默失效**（Next 16 按目录单例，换端口也起不来）"
    )
    assert str(guard.dev_lock_path(ADMIN_WEB)) == str(ADMIN_WEB / expected)
