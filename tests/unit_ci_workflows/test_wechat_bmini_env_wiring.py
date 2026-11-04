# case_ids: MC-193
"""B 端小程序（bmini）凭据：**部署环境接线 + 缺失显式告警**（issue #8196 的 ① 面）。

## 治的形态

A 档「扫普通链接二维码打开小程序」要求 admin-api 能换 bmini 的 openid / 手机号 ⇒
部署环境必须拿到两个凭据。改前三个面**都没有真值**：`application.yml` 是空占位
（`${WECHAT_BMINI_APPID:}`）、部署侧没人说该放哪儿、
`git grep WECHAT_BMINI -- backend/admin-api/src/main/java` = **0 命中**（缺了也没人吭声）。
现场形态不是报错，而是 B 端员工小程序登录 fail-closed 回「系统繁忙」，而 admin-api 看起来完全健康。

## 判据（每条都能单独变红）

| # | 判据 | 红证（怎么让它单独变红） |
|---|---|---|
| 1 | `application.yml` 的 `wechat.bmini.appid/secret` 绑到这两个 env 名，且**默认值为空** | 改掉变量名 / 给个非空默认 ⇒ 具名红（默认值非空 = 缺省悄悄变成某个值） |
| 2 | 变量名**入仓、值不入仓**：`backend/admin-api/.env.example` 逐名声明、值为空 | 删一行 / 填上值 ⇒ 具名红 |
| 3 | 真实注入面 = admin-api 的 `env_file: .env.admin-api`；compose 的 `environment` **不得**出现这两个名 | 摘掉 `env_file` ⇒ 红；加 `NAME: ${NAME:-}` ⇒ 红（environment 优先级**高于** env_file，插值读不到 `.env.admin-api` ⇒ 真值被覆盖成空串） |
| 4 | 全仓**不许出现**这两个变量的**值**（空 / 占位符 / `${…}` 引用放行） | 任一处写成字面值 ⇒ 具名红（判别力自证内建） |
| 5 | 启动期告警**接线**在 `WechatService`：`@PostConstruct` 打在该方法上、判两个字段、只有 `log.warn`、**不 throw** | 删注解 / 把字段判漏一个 / 换成 throw ⇒ 红 |
| 6 | 部署文档有「部署接线」节：两个 env 名 / 值的落点 / 一条可复算回读命令 / 缺省行为 | 删任一要素 ⇒ 具名红 |

## 边界（照实登记）

- 本文件判**接线形态**与**源码接线是否存在**；「两个都空 ⇒ 告警、两个都给 ⇒ 安静、半配 ⇒ 点名那个」
  的**行为**由 `backend/admin-api/src/test/java/com/migao/admin/service/WechatServiceBminiWiringTest.java`
  真跑（logback `ListAppender`）。本文件**不跑**别人的测试（那会让「未登记即红」退化成跑全量）。
- **判不了**：服务器 `.env.admin-api` 里**真的有值吗** —— 凭据是外部输入（用户侧提供），
  这里只钉住「变量名入仓 / 值不入仓 / 注入面正确」，可复算的回读命令写在部署文档里。
- 值扫描按**文本后缀**取面（markdown / YAML / Java / Python / shell / properties / conf / txt 等），
  二进制 / 大目录（`.git` / `node_modules` / `target` …）/ 超大文件跳过（边界登记在代码里）。
- 本文件**不改任何门禁的通过条件、不新增豁免**。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
APP_YML = REPO / "backend" / "admin-api" / "src" / "main" / "resources" / "application.yml"
ENV_EXAMPLE = REPO / "backend" / "admin-api" / ".env.example"
COMPOSE = REPO / "deploy" / "swas" / "docker-compose.yml"
DEPLOY_DOC = REPO / "docs" / "deployment" / "wechat-mini-program-qr.md"
WECHAT_SERVICE = (
    REPO
    / "backend"
    / "admin-api"
    / "src"
    / "main"
    / "java"
    / "com"
    / "migao"
    / "admin"
    / "service"
    / "WechatService.java"
)

#: 服务器侧 env 文件：**凭据值的唯一合法落点**（不入仓；admin-api 的 `env_file`）。
SERVER_ENV_FILE = ".env.admin-api"

#: `wechat.bmini.appid` 之类的绑定串（`${VAR:默认}`）
BINDING_RE = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?P<default>:[^}]*)?\}")

#: 告警方法签名（接线锚；行为判据在 Java 侧）
WARN_METHOD = "public void logBminiCredentialWarningIfMissing()"


# ── 真值现取：名字从 application.yml 读，不在判据里抄第二份 ──────────────────

def _application_yml() -> dict:
    data = yaml.safe_load(APP_YML.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{APP_YML.name} 不是 YAML 映射 —— 判据取不到真值（不是「通过」）"
    return data


def bmini_bindings() -> dict[str, str]:
    """键（`APPID` / `SECRET`）→ 绑定串原文。"""
    wechat = _application_yml().get("wechat") or {}
    bmini = wechat.get("bmini") or {}
    return {"APPID": str(bmini.get("appid", "")), "SECRET": str(bmini.get("secret", ""))}


def env_names() -> dict[str, str]:
    """键 → 环境变量名；绑定串形态不对 ⇒ 当场判红（不静默返回空串）。"""
    names: dict[str, str] = {}
    problems: list[str] = []
    for key, raw in bmini_bindings().items():
        match = BINDING_RE.search(raw)
        if match is None:
            problems.append(
                f"wechat.bmini.{key.lower()} 不是 `${{VAR:默认}}` 形态（现取 {raw!r}）—— 部署 env 名取不到"
            )
            continue
        names[key] = match.group("name")
    assert problems == [], "\n".join(problems)
    return names


def _env_name_list() -> list[str]:
    names = env_names()
    return [names["APPID"], names["SECRET"]]


# ── 判据 1：application.yml 的绑定（空默认才允许「缺失也能启动」）────────────

def test_application_yml_binds_both_env_names_with_empty_default():
    names = env_names()
    problems: list[str] = []
    for key, raw in bmini_bindings().items():
        expected = f"WECHAT_BMINI_{key}"
        if names.get(key) != expected:
            problems.append(
                f"wechat.bmini.{key.lower()} 绑到了 {names.get(key)!r}，期望 {expected} —— "
                "部署侧写的就是这个 env 名，两边必须逐字一致"
            )
        if not raw.strip().endswith(":}"):
            problems.append(
                f"wechat.bmini.{key.lower()} 的默认值不是空（现取 {raw!r}）—— "
                "缺省会悄悄变成某个值，等于把「没配」伪装成「配了」"
            )
    assert problems == [], "\n".join(problems)


# ── 判据 2：变量名入仓、值不入仓（.env.example 是运维唯一能看到的清单）──────

def test_env_template_declares_the_names_and_leaves_them_empty():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()

    problems: list[str] = []
    for name in _env_name_list():
        if name not in values:
            problems.append(
                f"{ENV_EXAMPLE.name} 没有 {name} —— 变量名没入仓，运维不知道该配哪两个"
            )
        elif values[name] != "":
            problems.append(
                f"{ENV_EXAMPLE.name} 的 {name} 带了值 —— 凭据**只许**放服务器 {SERVER_ENV_FILE}，"
                "仓库里只能留空占位"
            )
    assert problems == [], "\n".join(problems)


# ── 判据 3：真实注入面 = env_file；compose environment 不得覆盖成空 ─────────

def compose_wiring_problems(compose: dict, names: list[str]) -> list[str]:
    """admin-api 的凭据注入面检查（空清单 = 通过）。

    🔴 **为什么不许写进 `environment`**：compose 的 `environment` 优先级**高于** `env_file`，
    而 `${VAR:-}` 的插值只读服务器 shell / 项目 `.env`，**读不到** `.env.admin-api`
    ⇒ 变量不在 shell 里时解析为空串，把 env_file 里的真值**覆盖成空**。
    这个形态 2026-08-30 已在 `AI_AGENT_SERVICE_TOKEN` 上出过事（commit `988e490f0` 把它删掉了）。
    """
    problems: list[str] = []
    admin = (compose.get("services") or {}).get("admin-api") or {}

    env_files = admin.get("env_file")
    if isinstance(env_files, str):
        env_files = [env_files]
    env_files = [str(item) for item in (env_files or [])]
    if SERVER_ENV_FILE not in env_files:
        problems.append(
            f"admin-api 没有 `env_file: {SERVER_ENV_FILE}`（现取 {env_files}）—— "
            "那是服务器侧凭据进容器的**唯一**注入面"
        )

    env = admin.get("environment") or {}
    if not isinstance(env, dict):
        problems.append(f"admin-api.environment 形态变了（现取 {type(env).__name__}）—— 判据读不到")
        return problems
    for name in names:
        if name in env:
            problems.append(
                f"admin-api 的 environment 出现 {name} —— compose 的 environment 优先级**高于** env_file，"
                f"`${{…:-}}` 插值读不到 {SERVER_ENV_FILE} ⇒ 会把真值**覆盖成空串**"
                "（2026-08-30 同一形态已在 AI_AGENT_SERVICE_TOKEN 上出过事）。"
                f"凭据请只投 {SERVER_ENV_FILE}"
            )
    return problems


def test_admin_api_receives_the_credentials_through_env_file_only():
    names = _env_name_list()
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8")) or {}
    assert compose_wiring_problems(compose, names) == []

    # 判别力自证（内存注入，坏形态各自判红并**点名**；否则本判据是恒真的）
    good = {
        "services": {
            "admin-api": {"env_file": SERVER_ENV_FILE, "environment": {"TZ": "Asia/Shanghai"}}
        }
    }
    assert compose_wiring_problems(good, names) == []

    for name in names:
        overridden = {
            "services": {
                "admin-api": {
                    "env_file": SERVER_ENV_FILE,
                    "environment": {"TZ": "Asia/Shanghai", name: "${" + name + ":-}"},
                }
            }
        }
        found = compose_wiring_problems(overridden, names)
        assert len([item for item in found if name in item]) == 1, (
            f"把 {name} 加进 environment 后判据没点名它（判据没牙）：{found}"
        )

    missing_env_file = {"services": {"admin-api": {"environment": {"TZ": "Asia/Shanghai"}}}}
    found = compose_wiring_problems(missing_env_file, names)
    assert len([item for item in found if SERVER_ENV_FILE in item]) == 1, (
        f"摘掉 env_file 后判据没点名它（判据没牙）：{found}"
    )


# ── 判据 4：全仓不许出现凭据的**值** ──────────────────────────────────────

#: 出现即算「写成值」的右边形态之外，这些都只是**占位 / 引用**，放行
PLACEHOLDER_PREFIXES = ("<", "'", '"', "`", "$", "…")

TEXT_SUFFIXES = {
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".java",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
    ".js",
    ".properties",
    ".conf",
    ".txt",
}

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "target",
    ".next",
    "__pycache__",
    "test-results",
    "playwright-report",
}

MAX_TEXT_BYTES = 512 * 1024


def credential_value_problems(text: str) -> list[str]:
    """返回「把 bmini 凭据写成了字面值」的说明（空清单 = 干净）。

    取值前先剔掉 `${…}` 包装（那是**变量引用**，不是值），再看变量名后面跟的到底是什么：
    空 / 占位符（`<…>` / 引号 / `$…`）放行，其余一律算**值入库**。
    """
    problems: list[str] = []
    for line in text.splitlines():
        bare = re.sub(r"\$\{[^}]*\}", "", line)
        match = re.search(r"WECHAT_BMINI_(?:APPID|SECRET)\s*[:=]\s*(?P<rhs>.*)$", bare)
        if match is None:
            continue
        rhs = match.group("rhs").strip()
        if rhs == "" or rhs.startswith(PLACEHOLDER_PREFIXES):
            continue
        problems.append(
            f"把 bmini 凭据写成了字面值（{rhs[:12]}…）—— 凭据只许放服务器 {SERVER_ENV_FILE}，不许入库"
            f"：{line.strip()[:120]}"
        )
    return problems


def _text_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        for name in filenames:
            path = Path(dirpath) / name
            if name != ".env" and not name.startswith(".env.") and path.suffix not in TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_TEXT_BYTES:
                    continue
            except OSError:
                continue
            yield path


def test_no_bmini_credential_value_is_committed():
    problems: list[str] = []
    scanned = 0
    for path in _text_files(REPO):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        relative = path.relative_to(REPO).as_posix()
        problems += [f"{relative}：{item}" for item in credential_value_problems(text)]

    if scanned == 0:
        problems.append("一个文本文件都没扫到 —— 值扫描退化成空跑（看不到 ≠ 干净）")
    assert problems == [], "\n".join(problems[:20])

    # 判别力自证：三种「写成值」必须判红（拼接构造，免得本文件自己命中扫描）；
    # 三种占位 / 引用形态必须放行 —— 否则判据退化成恒真或恒假
    assert len(credential_value_problems("WECHAT_BMINI_" + "SECRET=" + "abcd1234efgh5678")) == 1
    assert len(credential_value_problems("WECHAT_BMINI_" + "APPID: " + "wx1234567890abcdef")) == 1
    assert len(credential_value_problems("WECHAT_BMINI_" + "APPID=" + "wx1234567890abcdef")) == 1
    assert credential_value_problems("WECHAT_BMINI_APPID=") == []
    assert credential_value_problems("WECHAT_BMINI_APPID: ${WECHAT_BMINI_APPID:-}") == []
    assert credential_value_problems("grep -q '^WECHAT_BMINI_SECRET=' .env.admin-api") == []


# ── 判据 5：启动期告警接线（行为在 Java 侧，这里只钉「有没有接上」）───────

def _method_body(text: str, signature: str) -> str:
    """取方法体（花括号配平）；取不到 ⇒ 空串（调用点判红）。"""
    start = text.find(signature)
    if start < 0:
        return ""
    brace = text.find("{", start + len(signature))
    if brace < 0:
        return ""
    depth = 0
    for index in range(brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1:index]
    return ""


def test_startup_warning_is_wired_and_cannot_block_startup():
    text = WECHAT_SERVICE.read_text(encoding="utf-8")
    body = _method_body(text, WARN_METHOD)

    problems: list[str] = []
    if body == "":
        problems.append(
            "WechatService 里找不到启动期告警方法 logBminiCredentialWarningIfMissing() —— "
            "「缺失时显式告警」这半不存在（改前 backend/admin-api/src/main/java 里 `WECHAT_BMINI` 零命中）"
        )
    else:
        if re.search(r"\bthrow\b", body):
            problems.append(
                "告警方法里出现 throw —— 缺失会变成**启动失败**，把「A 档不可用」放大成「整站不可用」"
            )
        if "log.warn" not in body:
            problems.append("告警方法没有 log.warn —— 缺失会被静默吞掉")
        for field in ("bminiAppId", "bminiAppSecret"):
            if field not in body:
                problems.append(f"告警方法没有判 {field} —— 半配（只给一个）不会被发现")

    at = text.find("@PostConstruct")
    if at < 0:
        problems.append("WechatService 没有 @PostConstruct —— 告警不会在启动期自动跑一次（只能靠人调）")
    elif WARN_METHOD not in text[at : at + 600]:
        problems.append(
            "最近的 @PostConstruct 不在告警方法上 —— 那等于没接进生命周期（判据按源码锚点取，不是猜）"
        )
    assert problems == [], "\n".join(problems)


# ── 判据 6：部署文档把「接线 + 回读 + 缺省行为」写在一处 ────────────────────

def test_deployment_doc_covers_wiring_read_back_and_default_behavior():
    text = DEPLOY_DOC.read_text(encoding="utf-8")
    problems: list[str] = []
    for must in ["部署接线", SERVER_ENV_FILE, "printenv", "只告警", "照常启动", *_env_name_list()]:
        if must not in text:
            problems.append(
                f"{DEPLOY_DOC.name} 的「部署接线」节缺「{must}」—— "
                "env 名 / 值的落点 / 回读命令 / 缺省行为必须写在同一处（别让人去别处拼）"
            )
    assert problems == [], "\n".join(problems)
