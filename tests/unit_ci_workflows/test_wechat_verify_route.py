# case_ids: MC-125
r"""微信「扫普通链接二维码打开小程序」校验文件：**nginx 显式面 + 落位拷贝语义**（issue #8196）。

## 治的形态

微信后台要求把一个**根下随机的 `<一串字符>.txt`** 放在 `https://app.migaozn.com/<名字>.txt`。
两种坏形态都不会有任何东西变红：

1. **nginx 面漏了**：请求落进 `location /` 的 SPA fallback ⇒ **文件缺失也是 HTTP 200**，
   返回的是 C 端元元的一页 HTML —— 与「校验文件内容对不上」在现场无法区分，人眼看状态码
   还会以为"文件已经在了"（同族实证：2026-09-27 线上 `/i/<任意码>` 与 `GET /` 逐字节同哈希）。
2. **落位语义错了**：发布脚本把静态根当自己家（删别的文件 / 拷了非 `.txt` / 不幂等）
   —— 那个静态根同时是 C 端 h5 的落地面（`index.html` / `js/` / `b/` / `w/` / `terminal/`）。

## 判据（每条都能单独变红）

| # | 判据 | 红证（怎么让它单独变红） |
|---|---|---|
| 1 | `app.migaozn.com` 段有**唯一**一条正则 location，且是根下**单段** `.txt` 面：`try_files $uri =404`（无 proxy / 无 rewrite / 不回落任何 HTML） | 删掉该 location ⇒ 缺失文件变 `index.html`；把 `=404` 换成 `/index.html` ⇒ 直接回落；把正则放宽成 `^/.*\.txt$` ⇒ 劫持 `/b/…` |
| 2 | **nginx 语义模拟**：`/xxx.txt` 存在 ⇒ 200 该文件；**缺失 ⇒ 404**（**不是** `index.html`）；`/b/<子路由>` 仍回落 `b/index.html`；`/w/…` 不被劫持；根级 SPA 路由仍是 `index.html` | 同上三条注入，各自让对应断言变红 |
| 3 | **拷贝语义（真跑 deploy.sh 的那一段）**：只拷 `*.txt`；**只增/覆盖、不删**；**幂等**（连跑两次逐字节一致）；父目录 `index.html` 哈希不变 | 把 `cp -f` 换成 `rsync --delete` / 去掉 `*.txt` 过滤 ⇒ 红 |
| 4 | **跳过必须出声且不拖垮部署**：源目录不存在 / 为空 / 静态根不存在 ⇒ 退出码 `0` + 明确提示 | 静默 `exit 1` / 静默什么都不做 ⇒ 红 |
| 5 | **仓库不许编文件名/内容**：本目录不得预置任何 `*.txt`，README 必须写清「原样放进、别改名」 | 往仓里塞一个假校验文件 ⇒ 红 |

## 边界（照实登记，§19.1）

- 判的是**配置形态 + 脚本语义**（nginx 语义模拟器只覆盖本段用到的全集：正则 location 优先 +
  前缀最长匹配 + `try_files` + `index`），**不是**真 nginx 二进制；线上真值仍以部署后的
  `curl` 三连为准（README 里给了命令）。
- **不能自动化**：微信后台的规则配置 / 校验文件的真实文件名与内容（用户侧生成）、真机扫码。
- 本文件**不改任何门禁的通过条件、不新增豁免**。
"""

from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
VERIFY_DIR = REPO_ROOT / "deploy" / "swas" / "wechat-verify"
README = VERIFY_DIR / "README.md"

SERVER_NAME = "app.migaozn.com"
STATIC_ROOT = "/opt/migao-deploy/h5"

# `location <修饰符?> <spec> {` —— 修饰符只收本仓出现的形态（前缀为空 / `=` / `^~` / `~` / `~*`）。
LOCATION_RE = re.compile(
    r"^\s*location\s+(?P<mod>~\*|~|=|\^~)?\s*(?P<spec>\S+)\s*\{(?P<body>[^}]*)\}",
    re.S | re.M,
)


# ── 坐标自证：读盘（缺失即判据失败，不静默）──────────────────────────────────

def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


# ── nginx：切 server 段 / 取 location（真解析，不扫全文）────────────────────

def _server_blocks(conf: str) -> list[str]:
    """切出每个 `server { … }` 段（花括号配平）。"""
    blocks: list[str] = []
    for m in re.finditer(r"\bserver\s*\{", conf):
        i = conf.index("{", m.start())
        depth, j = 0, i
        while j < len(conf):
            if conf[j] == "{":
                depth += 1
            elif conf[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blocks.append(conf[i + 1:j])
    return blocks


def _app_block(conf: str) -> str:
    for body in _server_blocks(conf):
        if re.search(rf"server_name[^;]*\b{re.escape(SERVER_NAME)}\b", body) and "listen 443" in body:
            return body
    raise AssertionError(f"nginx.conf 里找不到 {SERVER_NAME} 的 443 server 段")


def _locations(block: str) -> list[dict]:
    out = []
    for m in LOCATION_RE.finditer(block):
        body = m.group("body")
        tf = re.search(r"try_files\s+([^;]+);", body)
        out.append(
            {
                "mod": (m.group("mod") or "").strip(),
                "spec": m.group("spec"),
                "try_files": tf.group(1).split() if tf else None,
                "proxy_pass": bool(re.search(r"proxy_pass\s+\S+;", body)),
                "rewrite": bool(re.search(r"\brewrite\s+", body)),
                "body": body,
            }
        )
    return out


#: 「根下任意**单段** `.txt`」——微信校验文件的名字由用户侧生成，仓库不可知，
#: 所以只能用正则 location（前缀 location 表达不了），且必须恰好这么窄。
WECHAT_TXT_RE = r"^/[^/]+\.txt$"


def _txt_location(block: str) -> dict | None:
    hits = [loc for loc in _locations(block) if loc["mod"] in ("~", "~*") and loc["spec"] == WECHAT_TXT_RE]
    return hits[0] if len(hits) == 1 else None


# ── nginx 语义模拟（前缀 location 取最长者；正则 location 先于前缀；try_files + index）──

def _apply_try_files(loc: dict, files: set[str], uri: str) -> tuple[int, str | None]:
    tf = loc["try_files"]
    assert tf, f"location {loc['spec']} 没有 try_files —— 缺失文件会落进默认处理器（假 200/500）"
    for token in tf:
        if token.startswith("="):
            return int(token[1:]), None
        candidate = token.replace("$uri", uri)
        if token.endswith("/"):
            # 目录：本仓的静态面全是 `index` 兜底，目录里有 index.html 才算命中
            name = candidate.strip("/") + "/index.html"
            if name in files:
                return 200, name
            continue
        name = candidate.lstrip("/")
        if name in files:
            return 200, name
    return 404, None


def _serve(block: str, files: set[str], uri: str) -> tuple[int, str | None]:
    """按 nginx 语义算 (状态码, 被伺候的文件)：**正则先于前缀**，前缀取最长者。"""
    locs = _locations(block)
    for loc in locs:
        if loc["mod"] in ("~", "~*") and re.search(loc["spec"], uri):
            return _apply_try_files(loc, files, uri)
    best = None
    for loc in locs:
        if loc["mod"]:
            continue
        if uri == loc["spec"] or uri.startswith(loc["spec"]):
            if best is None or len(loc["spec"]) > len(best["spec"]):
                best = loc
    assert best is not None, f"{SERVER_NAME} 段没有匹配 {uri} 的 location"
    return _apply_try_files(best, files, uri)


#: 探针用的**虚拟静态根**（线上静态根 `/opt/migao-deploy/h5` 的预期形态）
def _static_fs() -> set[str]:
    return {
        "index.html",
        "js/app.js",
        "css/app.css",
        "b/index.html",
        "b/js/app.js",
        "w/index.html",
        "w/src/render.mjs",
        "terminal/latest.json",
    }


# ── 判据 1 + 2：nginx 面 ───────────────────────────────────────────────────

def test_nginx_conf_exists_and_app_server_is_parseable():
    """坐标自证：能取到 app.migaozn.com 的 443 段与它的 location 集（判据本体没跑空）。"""
    conf = _read(NGINX_CONF)
    assert conf, f"缺 {NGINX_CONF.relative_to(REPO_ROOT)} —— 静态面没有真值"
    block = _app_block(conf)
    locs = _locations(block)
    assert any(loc["spec"] == "/" for loc in locs), "app 段连 `location /` 都没解析到 ⇒ 解析器或配置结构变了"


def test_wechat_txt_face_is_exactly_one_narrow_regex_location():
    """判据 1：根下 `.txt` 有**显式**面，且它不回落任何 HTML、不放宽到别的命名空间。"""
    block = _app_block(_read(NGINX_CONF))
    loc = _txt_location(block)
    assert loc is not None, (
        f"{SERVER_NAME} 段缺少根下 .txt 的显式面（`location ~ {WECHAT_TXT_RE}`）——"
        "微信校验文件缺失时会落进 SPA fallback：**HTTP 200 的一页 HTML**，与「内容对不上」无法区分"
    )
    assert loc["try_files"] == ["$uri", "=404"], (
        f"根下 .txt 的 try_files 必须是 `$uri =404`（缺失即 404、绝不回落 HTML），现取 {loc['try_files']}"
    )
    assert not loc["proxy_pass"], "根下 .txt 是静态文件，不该反代到服务端"
    assert not loc["rewrite"], "根下 .txt 不该被 rewrite（会掩盖「文件不在」）"


def test_root_spa_fallback_still_intact():
    """反向钉住：`location /` 仍是 SPA fallback —— 上面那条 404 是**新面**带来的，不是把全站改成 404。"""
    block = _app_block(_read(NGINX_CONF))
    root = [loc for loc in _locations(block) if loc["spec"] == "/" and not loc["mod"]]
    assert root, "app 段缺 `location /`"
    assert root[0]["try_files"] == ["$uri", "$uri/", "/index.html"], (
        f"`location /` 的 SPA fallback 变了（现取 {root[0]['try_files']}）—— 那会波及 C 端整站"
    )


def test_serve_root_txt_present_and_missing():
    """判据 2：文件在 ⇒ 200 该文件；**不在 ⇒ 404**（不是 index.html）。"""
    block = _app_block(_read(NGINX_CONF))
    files = _static_fs() | {"a1b2c3d4e5.txt"}

    assert _serve(block, files, "/a1b2c3d4e5.txt") == (200, "a1b2c3d4e5.txt")
    assert _serve(block, files, "/__missing__.txt") == (404, None), (
        "根下缺失的 .txt 必须 404 —— 回落 index.html 会让「校验文件不在」伪装成 200"
    )


def test_serve_does_not_hijack_namespaces():
    """判据 2：正则只吃根下单段 ⇒ `/b/…` `/w/…` `/terminal/…` 与根级 SPA 路由都不变。"""
    block = _app_block(_read(NGINX_CONF))
    files = _static_fs()

    # 根级 SPA 路由仍是 C 端 index.html（正则不匹配多段路径）
    assert _serve(block, files, "/some/c-end/route") == (200, "index.html")
    assert _serve(block, files, "/") == (200, "index.html")
    # `/b/` 里的 .txt 仍按 bmini 自己的 fallback（不是根 index.html，也不是 404）
    assert _serve(block, files, "/b/orders/x.txt") == (200, "b/index.html")
    # 工人端静态资源不受影响
    assert _serve(block, files, "/w/src/render.mjs") == (200, "w/src/render.mjs")
    assert _serve(block, files, "/terminal/latest.json") == (200, "terminal/latest.json")


def test_nginx_mutations_are_all_detected():
    """判别力自证：三种坏形态**在内存里**各自判红（判据没退化成恒真）。"""
    conf = _read(NGINX_CONF)
    block = _app_block(conf)
    files = _static_fs() | {"a1b2c3d4e5.txt"}

    # ① 删掉整条 txt 面 ⇒ 缺失文件回落 index.html
    removed = re.sub(
        rf"\n    location ~ {re.escape(WECHAT_TXT_RE)} \{{\n        try_files \$uri =404;\n    \}}\n",
        "\n",
        block,
    )
    assert removed != block, "变异注入没生效（找不到要删的那段）—— 判据会变成空断言"
    assert _serve(removed, files, "/__missing__.txt") == (200, "index.html")

    # ② 把 =404 换成 index.html ⇒ 缺失也 200 HTML
    fallback = block.replace("try_files $uri =404;", "try_files $uri /index.html;", 1)
    assert fallback != block
    assert _serve(fallback, files, "/__missing__.txt") == (200, "index.html")

    # ③ 把正则放宽成多段 ⇒ 劫持 /b/ 命名空间
    #    锚到 **location 行**（注释里也出现过同一个正则串 ⇒ 裸 replace 会打错对象、变异变空跑）
    widened = re.sub(
        rf"location ~ {re.escape(WECHAT_TXT_RE)}",
        r"location ~ ^/.*\.txt$",
        block,
        count=1,
    )
    assert widened != block
    assert _serve(widened, files, "/b/orders/x.txt") == (404, None), (
        "正则放宽到多段会让 `/b/…` 的 .txt 落到根 .txt 面 ⇒ 把 bmini 的命名空间吃掉"
    )


# ── 判据 3 + 4：落位拷贝语义（真跑 deploy.sh 的那一段）──────────────────────

BLOCK_START = "# >>> wechat-verify"
BLOCK_END = "# <<< wechat-verify"


def _deploy_block() -> str:
    text = _read(DEPLOY_SH)
    assert text, f"缺 {DEPLOY_SH.relative_to(REPO_ROOT)}"
    assert BLOCK_START in text and BLOCK_END in text, (
        f"deploy.sh 里找不到微信校验文件落位段的标记（{BLOCK_START} / {BLOCK_END}）——"
        "本判据要真跑那一段，标记是唯一锚点"
    )
    return text.split(BLOCK_START, 1)[1].split(BLOCK_END, 1)[0]


def _run_block(
    static_root: Path,
    src_dir: Path | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """真跑 deploy.sh 的落位段。

    `src_dir=None` ⇒ **不注入** `MIGAO_WECHAT_VERIFY_DIR`（判默认解析：优先 `src/deploy/swas/wechat-verify`，
    那是线上部署形态 —— 配置包解到 `src/` 后**只在那儿**存在）；`cwd` 用来造那个形态的沙箱。
    """
    script = "set -euo pipefail\n" + f"export MIGAO_STATIC_ROOT={shlex.quote(str(static_root))}\n"
    if src_dir is not None:
        script += f"export MIGAO_WECHAT_VERIFY_DIR={shlex.quote(str(src_dir))}\n"
    script += _deploy_block()
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=cwd)


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): _file_sha(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_deploy_block_has_no_destructive_actions():
    """源码层红线：落位段只许 `cp -f`，不许删除 / 同步镜像（静态根不是本段所有）。"""
    block = _deploy_block()
    code = "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("rm ", "rsync", "mv ", "--delete", "find "):
        assert forbidden not in code, f"落位段出现破坏性/范围外动作「{forbidden}」—— 静态根同时是 C 端 h5 的落地面"
    assert "cp -f" in code
    assert "*.txt" in code


def test_copy_block_copies_only_txt_and_preserves_parent(tmp_path):
    """判据 3：只拷 `.txt`、只增/覆盖、父目录 `index.html` 与别的文件逐字节不变、幂等。"""
    static_root = tmp_path / "h5"
    (static_root / "js").mkdir(parents=True)
    (static_root / "b").mkdir()
    (static_root / "index.html").write_text("<!doctype html><html>C-END</html>", encoding="utf-8")
    (static_root / "js" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (static_root / "b" / "index.html").write_text("bmini", encoding="utf-8")
    # 静态根里本来就有的 .txt（不归源目录所有）——不许被删
    (static_root / "keep.txt").write_text("keep", encoding="utf-8")

    src = tmp_path / "wechat-verify"
    src.mkdir()
    (src / "a1b2c3d4e5.txt").write_text("wechat-verify-fixture\n", encoding="utf-8")
    (src / "notes.md").write_text("不该被部署", encoding="utf-8")

    before = _snapshot(static_root)
    first = _run_block(static_root, src)
    assert first.returncode == 0, first.stderr
    assert "a1b2c3d4e5.txt" in first.stdout
    after_first = _snapshot(static_root)

    # 只增了那一个 .txt（内容逐字一致），别的文件哈希一格未变
    assert (static_root / "a1b2c3d4e5.txt").read_text(encoding="utf-8") == "wechat-verify-fixture\n"
    assert "notes.md" not in after_first, "非 .txt 不许被拷到静态根"
    assert "index.html" not in (set(after_first) - set(before)), "父目录 index.html 不许被写"
    for name in before:
        assert after_first[name] == before[name], f"{name} 被改动了（落位段越界）"

    # 幂等：同一输入连跑两次结果逐字节一致
    second = _run_block(static_root, src)
    assert second.returncode == 0, second.stderr
    assert _snapshot(static_root) == after_first, "连跑两次结果不一致 ⇒ 不幂等"


def test_copy_block_overwrites_same_name(tmp_path):
    """覆盖语义：同名文件以源为准（微信重新生成校验文件时不会留下旧的）。"""
    static_root = tmp_path / "h5"
    static_root.mkdir()
    (static_root / "a1b2c3d4e5.txt").write_text("old", encoding="utf-8")
    src = tmp_path / "wechat-verify"
    src.mkdir()
    (src / "a1b2c3d4e5.txt").write_text("new", encoding="utf-8")

    result = _run_block(static_root, src)
    assert result.returncode == 0, result.stderr
    assert (static_root / "a1b2c3d4e5.txt").read_text(encoding="utf-8") == "new"


def test_copy_block_skips_loudly_when_nothing_to_copy(tmp_path):
    """判据 4：源为空 / 源不存在 / 静态根不存在 ⇒ 退出码 0 + 出声（**不**拖垮部署）。"""
    static_root = tmp_path / "h5"
    static_root.mkdir()
    (static_root / "index.html").write_text("c-end", encoding="utf-8")
    src = tmp_path / "wechat-verify"
    src.mkdir()

    empty = _run_block(static_root, src)
    assert empty.returncode == 0, empty.stderr
    assert "还没有 *.txt" in empty.stdout
    assert _snapshot(static_root) == {"index.html": _file_sha(static_root / "index.html")}

    missing_src = _run_block(static_root, tmp_path / "nope")
    assert missing_src.returncode == 0, missing_src.stderr
    assert "跳过微信校验文件" in missing_src.stdout

    missing_root = _run_block(tmp_path / "nope-static", src)
    assert missing_root.returncode == 0, missing_root.stderr
    assert "跳过微信校验文件" in missing_root.stdout


def test_block_defaults_to_the_extracted_source_tree(tmp_path):
    """🔴 部署形态：配置包解到 `src/`（`deploy/swas/deploy.sh` 的 1.3 段）⇒ 默认必须从 `src/…` 取。

    改前这条段被放在 2.6：C′ 构建成功后 `src/` 已被删 ⇒ 永远「跳过」= **静默不落位**
    （判据会在没有 `MIGAO_WECHAT_VERIFY_DIR` 注入时把两个目录都放上、并断言只落 `src/` 那一份）。
    """
    server = tmp_path / "srv"
    extracted = server / "src" / "deploy" / "swas" / "wechat-verify"
    extracted.mkdir(parents=True)
    (extracted / "a1b2c3d4e5.txt").write_text("from-extracted-tree", encoding="utf-8")
    checkout = server / "deploy" / "swas" / "wechat-verify"
    checkout.mkdir(parents=True)
    (checkout / "from-checkout.txt").write_text("from-repo-checkout", encoding="utf-8")

    static_root = tmp_path / "h5"
    static_root.mkdir()
    result = _run_block(static_root, src_dir=None, cwd=server)

    assert result.returncode == 0, result.stderr
    assert (static_root / "a1b2c3d4e5.txt").read_text(encoding="utf-8") == "from-extracted-tree"
    assert not (static_root / "from-checkout.txt").exists(), "部署形态取的是 `src/`，不是仓检出那份（同名文件会打架）"


def test_block_skips_loudly_when_source_tree_absent(tmp_path):
    """配置复用（同 ref 重部署、盘上没有 `src/`）⇒ 出声跳过、退出 0（不拖垮部署）。"""
    server = tmp_path / "srv"
    server.mkdir()
    static_root = tmp_path / "h5"
    static_root.mkdir()

    result = _run_block(static_root, src_dir=None, cwd=server)
    assert result.returncode == 0, result.stderr
    assert "跳过微信校验文件" in result.stdout
    assert list(static_root.iterdir()) == []


# ── 判据 5：仓库不许编文件名 / 内容 ────────────────────────────────────────

def test_repo_ships_no_fake_verification_file():
    """本目录是**承接位**：不许预置任何 `*.txt`（文件名/内容由微信生成，用户侧放）。"""
    assert VERIFY_DIR.is_dir(), "缺 deploy/swas/wechat-verify/ 目录（承接位）"
    leaked = sorted(p.name for p in VERIFY_DIR.glob("*.txt"))
    assert leaked == [], f"仓库里出现了校验文件 {leaked} —— 真文件由用户在微信后台生成，仓库不许编"


def test_readme_tells_user_to_drop_the_file_verbatim():
    """README 必须写清「原样放进来、别改名/改内容」，并给出部署后的自证命令。"""
    text = _read(README)
    assert text, "缺 deploy/swas/wechat-verify/README.md —— 用户不知道该放什么"
    for must in ("原样", "不要", "deploy.sh", "404", "扫普通链接二维码"):
        assert must in text, f"README 少了关键说明「{must}」"
