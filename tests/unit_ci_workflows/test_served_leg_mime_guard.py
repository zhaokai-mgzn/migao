# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI / 部署接线类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
r"""发布自检腿的 **MIME 判据** 类级守卫（issue #6293）—— 让「字节全对、浏览器照样白屏」进不来。

## 病（实测 2026-10-04，云测试环境）

`GET https://app.migaozn.com/w/src/app.mjs` → **200 `application/octet-stream`**：nginx 的基础
`mime.types` 只有 `js`、**没有 `mjs`** ⇒ 落到 `default_type`（本镜像 = octet-stream）⇒ 浏览器按 HTML
规范**拒绝执行 module script**（`Strict MIME type checking is enforced for module scripts`）⇒
工人端 H5 与一体机页**整页白屏**。

🔴 **它绿着上线，是因为四条发布自检腿里一条 MIME 判据都没有**：它们只判「状态码 200 + 字节哈希与仓库
一致」—— **字节全对，浏览器照样跑不起来**。同刻单变量对照：`.css` → `text/css`、`.js` →
`application/javascript` 都正常 ⇒ 只缺 `.mjs` 一条映射。

## 本守卫锁什么（每条都能单独变红；红证全在内存里，零网络）

| # | 判据 | 红证（注入式） |
|---|---|---|
| 1 | **每条发布自检腿都带 MIME 判据**（现取 `deploy/scripts/*-verify-served.sh`，**不写死清单**）：① 声明 JS MIME 白名单 ② 声明有**判别力**（收下合法 JS MIME、拒掉 octet-stream/css/html）③ 真的**调用**了它 ④ 有「取不到就判红」的 fail-closed 分支 | 删掉调用 ⇒ 具名判红；把白名单写成恒真（`.*`）⇒ 判红；删掉空集分支 ⇒ 判红 |
| 2 | **空集 fail-closed**：一条腿都取不到 ⇒ 判红（绝不静默通过） | 注入空腿集 ⇒ 判红 |
| 3 | **nginx：`.mjs` 必须落在 JS MIME 上，且不许用 `types {}`** —— 该块在 nginx 里是**替换**而不是合并继承表 ⇒ 会一并冲掉 `text/css` / `application/javascript` | 删掉 `default_type` 那行 ⇒ 判红；改成 octet-stream ⇒ 判红；注入 `types {}` ⇒ 判红 |
| 4 | **接线判据（覆盖）**：带 JS MIME 的 location 必须**真的覆盖**本仓 `frontend/worker-h5/src/*.mjs`（防「判据绿、规则没覆盖」） | 把 location 前缀 `/w/` 改成 `/x/` ⇒ 判红 |
| 5 | **域级兜底未被改**：`app.migaozn.com` 的 server 块**直接**指令里不得有 `default_type`（域级一改就波及**所有**未知扩展名） | 注入 server 级 `default_type` ⇒ 判红 |
| 6 | **只改注释不动结论**（对照读数） | 真语料上加一行注释 ⇒ **不**红 |

## 边界（照实登记，§19.1）

- 本守卫判**结构**（判据在位 / 映射在位 / 覆盖到位），**判不了**「线上 nginx 是否已 reload」与
  「线上响应头现在到底是什么」—— 那是发布自检腿的活体断言（`worker-h5-verify-served.sh` ⑥）的面。
- 也判不了基础 `mime.types` 的内容（本机没有 nginx）⇒ 本守卫只保证「本仓的配置把兜底类型设成了 JS」，
  不保证云上镜像的 `mime.types` 里没有把 `mjs` 映射到别的类型（那种情况下 `default_type` 不生效，
  但 `mjs` 也不会是 octet-stream ⇒ 浏览器仍可执行）。
- 本守卫**不改**任何门禁的通过条件、不新增豁免。
"""
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "deploy" / "scripts"
NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
WORKER_SRC = REPO_ROOT / "frontend" / "worker-h5" / "src"
WORKER_PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "worker-h5-publish.yml"
APP_DOMAIN = "app.migaozn.com"

#: WHATWG 认可的 JS MIME 家族（`text/javascript` 与 `application/javascript` 都合法 ⇒
#: 判据必须是「属于白名单」而不是「等于某个字面量」，否则会在**正确**的部署上误红）。
JS_MIME = re.compile(r"^(application|text)/(x-)?(java|ecma)script([0-9.]+)?$", re.I)
#: 白名单的**判别力**样本：必须收下 / 必须拒掉。
MUST_ACCEPT = ("application/javascript", "text/javascript", "application/x-javascript")
MUST_REJECT = ("application/octet-stream", "text/css", "text/html", "", "javascript")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_swas_nginx_rate_limit import (  # noqa: E402
    Block,
    _locations,
    _servers,
    parse_nginx,
    walk,
)

_H5_SUBDIR_RE = re.compile(r"^\s*H5_SUBDIR:\s*(?P<sub>[A-Za-z0-9._-]+)\s*$", re.M)
_JS_MIME_DECL_RE = re.compile(r"""^JS_MIME_RE=['"](?P<pattern>.+?)['"]\s*$""", re.M)
_JS_MIME_CALL_RE = re.compile(r"""\bjs_mime_ok\s+["']""")
_EMPTY_GUARD_RE = re.compile(r"""if \[ -z [^\]]*\]; then\s*\n\s*bad\s+["']""")


# ── 第 1/2 条：发布自检腿必须自带 MIME 判据（现取集合，未带即红）────────────────


def leg_files() -> list[Path]:
    """现取的发布自检腿集合（**不写死清单**：将来新增一条腿 = 自动纳入本守卫）。"""
    return sorted(SCRIPTS_DIR.glob("*-verify-served.sh"))


def whitelist_problems(pattern: str) -> list[str]:
    """白名单的**判别力**：收下合法 JS MIME + 拒掉「不是 JS MIME」的那几种形态。"""
    try:
        rx = re.compile(pattern, re.I)
    except re.error as exc:  # 白名单本身不是可编译正则 ⇒ 判据会恒真/恒假
        return [f"声明的白名单 {pattern!r} 不是可编译的正则：{exc}"]
    bad = [f"白名单 {pattern!r} **漏收**了合法 JS MIME {ct!r} ⇒ 正确部署上会误红" for ct in MUST_ACCEPT if not rx.match(ct)]
    bad += [f"白名单 {pattern!r} **误收**了非 JS MIME {ct!r} ⇒ 判据对这类坏形态恒真（空断言）" for ct in MUST_REJECT if rx.match(ct)]
    return bad


def leg_problems(name: str, text: str) -> list[str]:
    """一条腿的 MIME 判据是否**真的在**（认结构，不认注释文案）。"""
    bad: list[str] = []
    decl = _JS_MIME_DECL_RE.search(text)
    if decl is None:
        bad.append(f"{name}: 没有声明 JS MIME 白名单（`JS_MIME_RE='…'`）⇒ 这条腿**没有** MIME 判据")
    else:
        bad += [f"{name}: {item}" for item in whitelist_problems(decl.group("pattern"))]
    if _JS_MIME_CALL_RE.search(text) is None:
        bad.append(
            f"{name}: 声明了白名单但**没有任何调用点**（`js_mime_ok \"$ct\"`）⇒ 判据没接在断言流程上"
        )
    if _EMPTY_GUARD_RE.search(text) is None:
        bad.append(
            f"{name}: 没有「取不到就判红」的 fail-closed 分支（`if [ -z … ]; then bad \"…\"`）⇒ "
            "判据可能**空跑却全绿**（这正是本单的病根形态）"
        )
    return bad


def all_problems(legs: list[Path] | None = None, conf: str | None = None) -> list[str]:
    """本守卫的**唯一口径**：主判据与注入式红证都走它（⇒「红证测的是另一份实现」结构上不可能）。"""
    files = leg_files() if legs is None else legs
    bad: list[str] = []
    if not files:
        bad.append(
            f"{SCRIPTS_DIR} 下一条 `*-verify-served.sh` 都取不到 ⇒ 本守卫会**静默空跑**（fail-closed，不许当通过）"
        )
    for path in files:
        bad += leg_problems(path.name, path.read_text(encoding="utf-8"))
    bad += nginx_problems(
        NGINX_CONF.read_text(encoding="utf-8") if conf is None else conf, worker_mjs_urls()
    )
    return bad


# ── 第 3/4/5 条：nginx 侧的 `.mjs` 映射 + 覆盖 + 域级兜底未被改 ──────────────────


def worker_mjs_urls() -> list[str]:
    """→ 工人端 module script 的**线上 URL 路径**（现取：本仓 `src/*.mjs` × 发布腿声明的 `H5_SUBDIR`）。

    任一侧取不到 ⇒ 返回空表（调用方据此判红 ⇒ fail-closed，不静默通过）。
    """
    mjs = sorted(WORKER_SRC.glob("*.mjs"))
    try:
        sub = _H5_SUBDIR_RE.search(WORKER_PUBLISH_WORKFLOW.read_text(encoding="utf-8"))
    except OSError:
        return []
    if not mjs or sub is None:
        return []
    return [f"/{sub.group('sub')}/src/{p.name}" for p in mjs]


def app_server(conf: str) -> Block | None:
    """→ `app.migaozn.com` 的 443 server 块（找不到 ⇒ None，调用方判红、不静默）。"""
    return _servers(parse_nginx(conf)).get(APP_DOMAIN)


def _types_blocks(conf: str) -> list[str]:
    """→ 配置里**真的存在**的 `types` 块（走**剥注释**的结构解析器 ⇒ 注释里提一句不算，
    与 `test_swas_nginx_rate_limit.parse_nginx` 同一口径）。"""
    return [block.header for _path, block in walk(parse_nginx(conf)) if block.header == "types"]


def nginx_problems(conf: str, mjs_urls: list[str]) -> list[str]:
    """`.mjs` 的 MIME 修法是否**在位、可控、且真的覆盖了工人端模块脚本**。"""
    server = app_server(conf)
    if server is None:
        return [f"nginx.conf 里找不到 {APP_DOMAIN} 的 443 server 段（本判据的坐标没了）"]
    bad: list[str] = []

    if _types_blocks(conf):
        bad.append(
            "nginx.conf 里出现了 `types {}` 块 —— nginx 的该块是**替换**而不是合并继承表 ⇒ 会把继承来的 "
            "`text/css` / `application/javascript` / `text/html` 一起冲掉（本仓的 `.mjs` 修法刻意**不用**它，"
            "改用只对「表里没有的扩展名」生效的 `default_type`）；确实需要它时，请先证明它被限定在只含该"
            "扩展名的作用域，再来改本判据"
        )

    direct_default_types = [d for d in server.directives if d.startswith("default_type ")]
    if direct_default_types:
        bad.append(
            f"{APP_DOMAIN} 的 server 块**直接**设了 `{direct_default_types[0]}` —— 域级兜底一改就波及"
            "**所有**（含将来新增的）未知扩展名；`.mjs` 的映射必须限定在只住着该应用产物的那个 location 里"
        )

    js_locations: list[str] = []
    for prefix, block in _locations(server).items():
        dts = [d for d in block.directives if d.startswith("default_type ")]
        if not dts:
            continue
        mime = dts[-1].split(None, 1)[1].strip().rstrip(";")
        covered = [u for u in mjs_urls if u.startswith(prefix)]
        if JS_MIME.match(mime):
            js_locations.append(prefix)
        elif covered:
            bad.append(
                f"`location {prefix}` 覆盖了 {len(covered)} 个模块脚本（如 {covered[0]}），但它的 "
                f"`default_type = {mime!r}` **不是** JS MIME ⇒ 浏览器会拒绝执行 module script ⇒ 整页白屏"
            )

    if not js_locations:
        bad.append(
            f"{APP_DOMAIN} 的静态面里没有任何 location 把 `default_type` 设成 JS MIME ⇒ `.mjs` 会落到"
            "域级兜底（本镜像 = application/octet-stream）⇒ 浏览器拒绝执行 module script ⇒ 整页白屏"
            "（这正是 issue #6293 的形态）"
        )
    elif not mjs_urls:
        bad.append(
            "取不到工人端 module script 的线上路径（本仓 `frontend/worker-h5/src/*.mjs` 或发布腿的 "
            "`H5_SUBDIR` 一侧缺失）⇒ 覆盖判据会空跑（fail-closed，不许当通过）"
        )
    else:
        uncovered = [u for u in mjs_urls if not any(u.startswith(p) for p in js_locations)]
        if uncovered:
            bad.append(
                "这些模块脚本**不在**任何带 JS MIME 的 location 覆盖范围内（判据绿、规则没覆盖 ⇒ 白屏照旧）："
                + "、".join(uncovered)
            )
    return bad


# ── 判据（真语料）─────────────────────────────────────────────────────────────


def test_real_repo_has_no_problems():
    """主判据：真语料上问题清单必须为空（清单本身由下面的注入式红证证明不是空转）。"""
    bad = all_problems()
    assert bad == [], "发布自检腿的 MIME 判据 / nginx 的 .mjs 映射有问题：\n" + "\n".join(f"  · {i}" for i in bad)


def test_coordinates_are_live_not_scanning_air():
    """坐标自证：腿集合、`.mjs` 集合、app server 段、JS MIME location 都**真的**取到了。"""
    assert len(leg_files()) >= 3, f"只取到 {len(leg_files())} 条发布自检腿（worker / bmini / c-end 三端）"
    assert worker_mjs_urls(), "取不到工人端 module script 的线上路径 ⇒ 覆盖判据在扫空气"
    assert app_server(NGINX_CONF.read_text(encoding="utf-8")) is not None, "找不到 app.migaozn.com 的 443 server 段"


@pytest.mark.parametrize("leg", [p.name for p in leg_files()])
def test_every_leg_carries_a_working_mime_judgement(leg):
    """逐条腿正面判：白名单 + 调用点 + 空集 fail-closed 分支三者齐备。"""
    assert leg_problems(leg, (SCRIPTS_DIR / leg).read_text(encoding="utf-8")) == []


# ── 注入式红证（全在内存里；每条都先自证「变异真的生效」）────────────────────────


def _leg_text(name: str = "worker-h5-verify-served.sh") -> str:
    return (SCRIPTS_DIR / name).read_text(encoding="utf-8")


def test_red_proof_leg_without_the_call_site_is_reported():
    text = _leg_text()
    mutated = re.sub(r'\n  if js_mime_ok "\$ct"; then.*?\n  fi\n', "\n", text, flags=re.S)
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    assert _JS_MIME_CALL_RE.search(mutated) is None, "注入后仍能搜到调用点 ⇒ 红证的前提不成立"
    problems = leg_problems("worker-h5-verify-served.sh", mutated)
    assert any("调用点" in p for p in problems), f"删掉调用点竟没判红：{problems}"


def test_red_proof_always_true_whitelist_is_reported():
    """白名单写成恒真（`.*`）⇒ 判据退化成空断言，必须红。"""
    assert whitelist_problems(".*"), "恒真白名单竟被判为有判别力"


def test_red_proof_leg_without_fail_closed_branch_is_reported():
    text = _leg_text()
    mutated = re.sub(r'if \[ -z "\$MJS_LOCAL" \]; then\s*\n\s*bad "[^"]*"\nfi\n', "", text)
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    problems = leg_problems("worker-h5-verify-served.sh", mutated)
    assert any("fail-closed" in p for p in problems), f"删掉空集分支竟没判红：{problems}"


def test_red_proof_empty_leg_set_is_reported():
    problems = all_problems(legs=[])
    assert any("静默空跑" in p for p in problems), f"空腿集竟没判红：{problems}"


def test_red_proof_nginx_without_the_mjs_mapping_is_reported():
    conf = NGINX_CONF.read_text(encoding="utf-8")
    mutated = conf.replace("        default_type application/javascript;\n", "", 1)
    assert mutated != conf, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    problems = nginx_problems(mutated, worker_mjs_urls())
    assert any("没有任何 location 把" in p for p in problems), f"删掉 .mjs 映射竟没判红：{problems}"


def test_red_proof_nginx_with_octet_stream_mapping_is_reported():
    conf = NGINX_CONF.read_text(encoding="utf-8")
    mutated = conf.replace("default_type application/javascript;", "default_type application/octet-stream;", 1)
    assert mutated != conf, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    problems = nginx_problems(mutated, worker_mjs_urls())
    assert any("不是" in p and "JS MIME" in p for p in problems), f"改成 octet-stream 竟没判红：{problems}"


def test_red_proof_nginx_types_block_is_reported():
    """`types {}` 会**替换**继承表 ⇒ 一并冲掉 css/js —— 注入它必须红。"""
    conf = NGINX_CONF.read_text(encoding="utf-8")
    mutated = conf.replace(
        "    location /w/ {\n",
        "    types { application/javascript mjs; }\n    location /w/ {\n",
        1,
    )
    assert mutated != conf, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    problems = nginx_problems(mutated, worker_mjs_urls())
    assert any("types" in p and "替换" in p for p in problems), f"注入 types 块竟没判红：{problems}"


def test_red_proof_server_level_default_type_is_reported():
    """域级兜底被改 ⇒ 波及所有未知扩展名 ⇒ 红。"""
    conf = NGINX_CONF.read_text(encoding="utf-8")
    mutated = conf.replace(
        "    root /opt/migao-deploy/h5;\n",
        "    root /opt/migao-deploy/h5;\n    default_type application/javascript;\n",
        1,
    )
    assert mutated != conf, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    problems = nginx_problems(mutated, worker_mjs_urls())
    assert any("直接" in p for p in problems), f"注入 server 级 default_type 竟没判红：{problems}"


def test_red_proof_js_location_not_covering_worker_src_is_reported():
    """接线判据：location 前缀不再覆盖 `/w/src/**` ⇒ 红（判据绿但规则没覆盖）。"""
    conf = NGINX_CONF.read_text(encoding="utf-8")
    mutated = conf.replace("    location /w/ {\n", "    location /x/ {\n", 1)
    assert mutated != conf, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    problems = nginx_problems(mutated, worker_mjs_urls())
    assert any("覆盖范围内" in p for p in problems), f"location 不再覆盖 worker 模块脚本竟没判红：{problems}"


def test_control_comment_only_edit_does_not_turn_red():
    """对照读数：只加注释 ⇒ 结论不变（守卫不被自己的文案喂红）。"""
    conf = NGINX_CONF.read_text(encoding="utf-8") + "\n# 只加一行注释（issue #6293 的对照读数）\n"
    assert nginx_problems(conf, worker_mjs_urls()) == []
    leg = _leg_text() + "\n# 只加一行注释（issue #6293 的对照读数）\n"
    assert leg_problems("worker-h5-verify-served.sh", leg) == []
