# case_ids: MC-012, UI-061
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012；
#   UI-061 = 本单新增的「手机端入口二维码」用例，见 .github/cases/ui.yml。）
r"""「手机端入口」二维码的**单一真值**与**缺配置不画假码**常驻判据（issue #5668）。

## 为什么要有这条判据（不是纸上规范）

二维码的内容 = **B 端 h5 的地址**。这个地址一旦在源码里被抄成第二份，就会出现
「改了发布落位、二维码还指着旧地址」这种**没有任何东西会红**的形态（用户扫了打不开）。
同族反面教材在案：`craft-display` 的三份副本（issue #4393）。
对称地，**缺配置时画一个假码**比不画更坏：用户扫出白屏/别的站点，而页面上一切看起来正常
（同族判据：洗水码「缺码不画假码」）。

## 判据（每条都能单独变红）

1. **前端源码里没有硬编码域名**（`app.migaozn.com` 一族）：未登记即红（`ALLOWED_DOMAIN_SITES`
   是**空**字典 —— 今天没有任何合法例外；将来真有例外必须登记并写理由）。
2. **地址只有一个读取点**：`NEXT_PUBLIC_BMINI_H5_URL` 只允许在
   `frontend/admin-web/src/lib/bmini-h5-url.ts` 里读；组件必须经 `getBminiH5Url()` 取，
   不许自己读 `process.env`（否则又是"多处取值 ⇒ 换一处忘一处"）。
3. **二维码内容取自该单一值**：`value={bminiH5Url}`（不许拼字符串、不许写死域名）。
4. **缺配置不画假码**（结构层）：`{bminiH5Url ? (…) : (…)}` 的**真分支**里才有 `QRCodeSVG`，
   假分支渲染「未配置」且**一个 svg 都没有**。行为层的孪生判据在
   `frontend/admin-web/tests/unit/pages/settings.test.tsx`（UI-061 的 5 格）。
5. **发布链在案**（否则功能在线上静默缺失）：`Dockerfile` 的 `ARG`+`ENV`、
   `deploy-frontend.yml` 的 `--build-arg`、`.env.example` 的说明三者都在；
   任一环缺失 ⇒ 镜像里没有这个值 ⇒ 设置页永远显示「未配置」（而没人会发现）。

## 边界（照实登记）

- 判据读的是**源码文本/结构**，不是运行结果 —— 行为层由 vitest（UI-061）承担；
  两边**判定口径有意一致**（都不许画假码），但本文件证明不了渲染行为，反之亦然。
- `NEXT_PUBLIC_*` 的构建期替换语义（Next 把 `process.env.NEXT_PUBLIC_X` 文本替换成字面量）
  不在判据面内：它由"值确实出现在构建产物里"这条**运行期**事实承担（CI 的 admin-web 腿 + 浏览器）。
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_WEB_SRC = REPO_ROOT / "frontend" / "admin-web" / "src"
SETTINGS_PAGE = ADMIN_WEB_SRC / "app" / "(dashboard)" / "settings" / "page.tsx"
URL_HELPER = ADMIN_WEB_SRC / "lib" / "bmini-h5-url.ts"
ENV_EXAMPLE = REPO_ROOT / "frontend" / "admin-web" / ".env.example"
DOCKERFILE = REPO_ROOT / "frontend" / "admin-web" / "Dockerfile"
DEPLOY_FRONTEND = REPO_ROOT / ".github" / "workflows" / "deploy-frontend.yml"

ENV_VAR = "NEXT_PUBLIC_BMINI_H5_URL"
#: 唯一允许读该环境变量的文件（仓库相对路径）—— 单一真值的落点
SOLE_READER = "frontend/admin-web/src/lib/bmini-h5-url.ts"
#: 前端源码里的硬编码域名：**未登记即红**。今天没有合法例外（要加必须在这里写理由）。
ALLOWED_DOMAIN_SITES: dict[str, str] = {}
DOMAIN_RE = re.compile(r"\bapp\.migaozn\.com\b")

#: 前端源码面（`src/**` + bmini 的构建配置）—— 测试夹具与 e2e 脚本不在面内（它们不是用户可达配置）
SOURCE_FACES = (
    REPO_ROOT / "frontend" / "admin-web" / "src",
    REPO_ROOT / "frontend" / "bmini-app" / "src",
    REPO_ROOT / "frontend" / "bmini-app" / "config",
)


def _read(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def _source_files() -> list[Path]:
    out: list[Path] = []
    for face in SOURCE_FACES:
        if face.is_dir():
            out.extend(sorted(p for p in face.rglob("*") if p.is_file() and p.suffix in {".ts", ".tsx", ".js", ".jsx"}))
    return out


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:  # 变异样本可能在 tmp 里
        return path.name


def _strip_comments(text: str) -> str:
    """把**注释**内容抹成空格（保留行结构），字符串字面量原样保留。

    为什么必须做这一步（本仓踩过多次的同族坑）：判据按文本匹配 ⇒ **注释里的域名也算命中**
    ⇒ 判据会被自己的文档喂红（`migao-dev-flow` §23.4 T2）。而"源码里不得硬编码域名"要管的是
    **代码路径**（字符串/JSX 属性），不是散文。
    ⚠️ 不能简单地按 `//` 切：`'https://app.migaozn.com/b/'` 里也有 `//` ⇒ 那样会把**真命中**
    也切掉（假绿）。故这里带字符串状态机：注释内的内容抹掉，字符串内的内容保留。
    """
    out = []
    i, n = 0, len(text)
    state = "code"  # code | line_comment | block_comment | ' | " | `
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line_comment"
                out.append("  ")
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                out.append("  ")
                i += 2
                continue
            if ch in "'\"`":
                state = ch
            out.append(ch)
        elif state == "line_comment":
            if ch == "\n":
                state = "code"
                out.append(ch)
            else:
                out.append(" ")
        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
        else:  # 字符串内
            if ch == "\\":
                out.append(ch)
                if nxt:
                    out.append(nxt)
                i += 2
                continue
            if ch == state:
                state = "code"
            out.append(ch)
        i += 1
    return "".join(out)


def _hardcoded_domain_sites(files=None) -> list[str]:
    """前端**代码**里出现硬编码 `app.migaozn.com` 的位置（仓库相对路径:行号；注释不算）。"""
    files = _source_files() if files is None else files
    hits = []
    for path in files:
        rel = _rel(path)
        if rel in ALLOWED_DOMAIN_SITES:
            continue
        text = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
        for i, line in enumerate(text.splitlines(), 1):
            if DOMAIN_RE.search(line):
                hits.append(f"{rel}:{i}: {line.strip()[:120]}")
    return hits


def _env_var_readers(files=None) -> list[str]:
    """真读 `process.env.NEXT_PUBLIC_BMINI_H5_URL` 的文件（**注释不算、JSX 文案不算**）。"""
    files = files if files is not None else sorted(ADMIN_WEB_SRC.rglob("*"))
    needle = f"process.env.{ENV_VAR}"
    hits = []
    for path in files:
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        rel = _rel(path)
        if rel == SOLE_READER:
            continue
        if needle in _strip_comments(path.read_text(encoding="utf-8", errors="replace")):
            hits.append(rel)
    return hits


def _entry_branches(src: str) -> dict:
    """切出「手机端入口」卡片里那个三元的两个分支（结构层判据 3/4 的判据对象）。"""
    m = re.search(
        r"\{bminiH5Url \? \(\n(?P<yes>.*?)\n\s*\) : \(\n(?P<no>.*?)\n\s*\)\}",
        src,
        re.S,
    )
    return {"yes": m.group("yes"), "no": m.group("no")} if m else {}


def _problems(page_src=None, helper_src=None, dockerfile=None, workflow=None, env_example=None, files=None) -> list:
    page_src = _read(SETTINGS_PAGE) if page_src is None else page_src
    helper_src = _read(URL_HELPER) if helper_src is None else helper_src
    dockerfile = _read(DOCKERFILE) if dockerfile is None else dockerfile
    workflow = _read(DEPLOY_FRONTEND) if workflow is None else workflow
    env_example = _read(ENV_EXAMPLE) if env_example is None else env_example
    problems: list = []

    if page_src is None:
        problems.append("frontend/admin-web/src/app/(dashboard)/settings/page.tsx 缺失")
    if helper_src is None:
        problems.append(f"{SOLE_READER} 缺失 —— 地址没有单一读取点")
    elif ENV_VAR not in helper_src:
        problems.append(f"{SOLE_READER} 必须读 `{ENV_VAR}`（单一真值）")

    for hit in _hardcoded_domain_sites(files):
        problems.append(f"前端源码里出现硬编码域名（未登记即红）：{hit}")
    for rel in _env_var_readers(files if files is not None else None):
        problems.append(f"`{ENV_VAR}` 只允许在 {SOLE_READER} 里读，实际又被 {rel} 读了 —— 单一真值被破坏")

    if isinstance(page_src, str):
        if "getBminiH5Url()" not in page_src:
            problems.append("设置页必须经 `getBminiH5Url()` 取地址（不许自己读 process.env）")
        if f"process.env.{ENV_VAR}" in page_src:
            problems.append("设置页不得直接读 process.env（破坏单一读取点）")
        if "import { QRCodeSVG } from 'qrcode.react'" not in page_src:
            problems.append("设置页必须用既有依赖 qrcode.react 的 QRCodeSVG 画码")
        branches = _entry_branches(page_src)
        if not branches:
            problems.append("找不到「手机端入口」的 `{bminiH5Url ? (…) : (…)}` 三元（判据 3/4 的判据对象）")
        else:
            if "QRCodeSVG" not in branches["yes"]:
                problems.append("有值分支里没有 QRCodeSVG —— 配了地址却不画码")
            if "value={bminiH5Url}" not in branches["yes"]:
                problems.append("二维码内容必须逐字取自 `bminiH5Url`（value={bminiH5Url}）")
            if "QRCodeSVG" in branches["no"]:
                problems.append("**假码**：无值分支里出现了 QRCodeSVG（缺配置时不许画码）")
            if 'data-testid="bmini-h5-unconfigured"' not in branches["no"]:
                problems.append("无值分支必须给出明确的「未配置」锚点（data-testid=bmini-h5-unconfigured）")
            if "未配置" not in branches["no"]:
                problems.append("无值分支必须逐字说明「未配置」（不许静默什么都不画）")

    if isinstance(dockerfile, str):
        if not re.search(rf"^ARG {ENV_VAR}=", dockerfile, re.M):
            problems.append(f"Dockerfile 缺 `ARG {ENV_VAR}=…`（缺省值兜底）")
        if not re.search(rf"^ENV {ENV_VAR}=\$\{{{ENV_VAR}\}}", dockerfile, re.M):
            problems.append(f"Dockerfile 缺 `ENV {ENV_VAR}=${{{ENV_VAR}}}`（构建期 baked into JS）")
    if isinstance(workflow, str):
        if f"--build-arg {ENV_VAR}=" not in workflow:
            problems.append(f"deploy-frontend.yml 缺 `--build-arg {ENV_VAR}=…`（镜像里将没有这个值 ⇒ 页面永远显示未配置）")
    if isinstance(env_example, str):
        if not re.search(rf"^{ENV_VAR}=", env_example, re.M):
            problems.append(f".env.example 缺 `{ENV_VAR}=` 一行（本地开发看不到这个配置的存在）")
    return problems


def test_real_single_source_and_wiring_have_no_problems():
    problems = _problems()
    assert problems == [], "手机端入口的单一真值/接线判据不通过：\n  - " + "\n  - ".join(problems)


def test_qr_entry_is_on_the_settings_page_and_keeps_existing_tabs():
    """判据：入口落在「设置 / 企业设置」页，且既有四个 tab 一个不少（只加不改）。"""
    src = _read(SETTINGS_PAGE)
    assert isinstance(src, str)
    for label in ("基本设置", "AI 客服设置", "参数总览", "通知设置"):
        assert f"label: '{label}'" in src, f"既有 tab `{label}` 不见了（本单只加卡片，不动导航）"
    for testid in ('data-testid="bmini-h5-entry"', 'data-testid="bmini-h5-qr"', 'data-testid="bmini-h5-unconfigured"'):
        assert testid in src, f"设置页缺 {testid}"
    assert "手机浏览器扫码使用米宝商家端" in src, "缺那行说明（用户要知道扫了干什么）"


def test_mutations_are_all_detected(tmp_path):
    """注入式红证：把实现改坏 ⇒ 判据必须红（证明上面几条不是空断言）。"""
    page = _read(SETTINGS_PAGE)
    helper = _read(URL_HELPER)
    dockerfile = _read(DOCKERFILE)
    workflow = _read(DEPLOY_FRONTEND)
    assert isinstance(page, str) and isinstance(helper, str)

    # ① 硬编码域名：往前端源码里塞一行写死的地址
    polluted = tmp_path / "polluted.ts"
    polluted.write_text("export const BMINI = 'https://app.migaozn.com/b/'\n", encoding="utf-8")
    # ② 第二个读取点：另一个文件也读这个环境变量
    second_reader = tmp_path / "second-reader.ts"
    second_reader.write_text(f"export const x = process.env.{ENV_VAR}\n", encoding="utf-8")
    src_files = [polluted, second_reader]

    # ③ 假码：把 QRCodeSVG 挪进无值分支（缺配置也画一个）
    fake_qr = page.replace(
        '<QRCodeSVG value={bminiH5Url} size={112} title={bminiH5Url} data-testid="bmini-h5-qr" />', ""
    ).replace(
        '<p className="text-sm text-neutral-500" data-testid="bmini-h5-unconfigured">',
        '<p className="text-sm text-neutral-500" data-testid="bmini-h5-unconfigured">'
        '<QRCodeSVG value="" data-testid="bmini-h5-qr" />',
    )
    assert fake_qr != page, "变异注入未生效（找不到 QRCodeSVG 那一行）"

    mutations = {
        "前端源码里硬编码域名": dict(files=src_files),
        "Dockerfile 去掉 ENV": dict(dockerfile=dockerfile.replace(f"ENV {ENV_VAR}=${{{ENV_VAR}}}\n", "")),
        "deploy-frontend 去掉 --build-arg": dict(
            workflow=workflow.replace(f"            --build-arg {ENV_VAR}=${{{{ secrets.{ENV_VAR} || 'https://app.migaozn.com/b/' }}}} \\\n", "")
        ),
        "把二维码挪进无值分支（画假码）": dict(page_src=fake_qr),
        "二维码内容改成硬编码（不取配置值）": dict(
            page_src=page.replace(
                "value={bminiH5Url} size={112} title={bminiH5Url}",
                'value="https://app.migaozn.com/b/" size={112} title="https://app.migaozn.com/b/"',
            )
        ),
        "设置页自己读 process.env（绕过单一读取点）": dict(
            page_src=page.replace("const bminiH5Url = getBminiH5Url()", f"const bminiH5Url = process.env.{ENV_VAR} || ''")
        ),
    }
    undetected = []
    for name, kwargs in mutations.items():
        if len(_problems(**kwargs)) == 0:
            undetected.append(name)
    assert undetected == [], f"这些变异**没有被判红**（= 空断言）：{undetected}"


def test_the_scan_faces_are_not_empty():
    """判据的前提：扫描面真的扫到了文件（面空了会让上面几条静默通过）。"""
    files = _source_files()
    assert len(files) > 50, f"前端源码面只扫到 {len(files)} 个文件 —— 扫描面疑似失效（空跑成绿）"
    assert any(str(p).endswith("settings/page.tsx") for p in files), "扫描面里没有设置页 —— 面配错了"
