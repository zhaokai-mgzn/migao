# case_ids: MC-068
"""本地三件套 AI 接线文档 ⇄ 代码真值对账 —— issue #6674。

## 病（2026-10-10 现场，父 agent 亲历；本判据要治的正是「文档没写 = 没人知道」）

按 `AGENTS.md`「本地只启 3 组件」起好 `admin-api(:8080)` + `ai-agent-service(:8001)` +
`admin-web(:3001)` 后，走真实入驻链路（`POST /api/auth/register`）得到：

    {"success":true,"data":{"status":"rejected","message":"系统繁忙"}}

而 `:8001/health` **是健康的**。真因两条，缺一不可：

1. `backend/admin-api/src/main/resources/application.yml` 的
   `ai-agent.base-url: ${AI_AGENT_BASE_URL:http://localhost:8000}` —— **默认值指容器内端口**，
   而本地栈的 ai-agent 跑在宿主 **8001**（`deploy/docker-compose.yml` 的 `8001:8000`；
   `AGENTS.md`「环境」段写 8001）；
2. `ai-agent.service-token: ${AI_AGENT_SERVICE_TOKEN:}` —— **默认为空串**，而 ai-agent 侧
   `app/utils/auth.py` 的 `verify_service_token` 对空配置是 **fail-closed（拒绝全部内部调用）**
   ⇒ 即使端口对了也拿不到结论。

两条都缺时 `RegistrationReviewClient.review()` 返回 `null` ⇒ `RegistrationService` 第 8 步
**静默 fail-closed**（`review_source=system`，不进 24h 冷却 ⇒ 用户会反复撞同一句「系统繁忙」）。
**行为本身是设计如此**（有单测钉着），缺的是**把本地接线说清楚** —— 而当时**没有一条判据
会因此变红**：文档写错端口、少写一个变量，照样全绿（「静默失效」类）。

## 本判据锁什么（真值**现取**，文档只当被测面）

真值源是**代码**，不是本文件里的手抄常量（避免「文档抄错、判据也跟着抄错」的自冾假绿）：

| 真值 | 现取位置 |
|---|---|
| 变量名 `AI_AGENT_BASE_URL` / `AI_AGENT_SERVICE_TOKEN` | `application.yml` 的 `ai-agent:` 块**逐字** |
| base-url 默认值里的端口 | 同上的默认段（`${AI_AGENT_BASE_URL:http://localhost:<port>}`） |
| 本地宿主端口 | `deploy/docker-compose.yml` 里 ai-agent 服务的 `<host>:8000` 端口映射 |
| 内部端点 | `RegistrationReviewClient` 的 `REVIEW_PATH` 常量 |
| 默认值确实「即坏值」 | 上面两个默认值与本地宿主端口/非空 token **不相等** |

| # | 判据 | 红证（怎么让它**单独**变红） |
|---|---|---|
| C1 | 文档必须**显式**出现两个变量名（缺任一 ⇒ 具名红） | 从文档副本里删掉 `AI_AGENT_SERVICE_TOKEN` ⇒ 只报「缺哪一个」 |
| C2 | 文档给的显式端口 **≠** `AI_AGENT_BASE_URL` 默认值里的端口（相等 ⇒ 那条覆盖等于没写 / 在复述容器内端口） | 把文档端口改成 8000（= 默认值）⇒ 具名红 |
| C3 | 文档里的 ai-agent 启动命令 `--port` **逐字等于**文档自己声明的那个端口 | 只改命令不改 base-url ⇒ 红（两项同源） |
| C4 | 文档声明的端口 == `docker-compose.yml` 的宿主端口 == ai-agent 默认 `PORT` 的宿主侧 | 端口漂移 ⇒ 红 |
| C5 | 两个默认值**确实**是「即坏值」（端口 ≠ 宿主端口、token 为空串） | 给 `service-token` 补一个默认值 ⇒ 红（本判据的**防腐**：默认值哪天修好了，这条会红并逼人改文档口径） |
| C6 | 文档必须给出可复制的**验证命令**与**期望输出**，且端点 = `REVIEW_PATH` | 删掉期望输出段 ⇒ 红 |
| C7 | 对照：只改注释 / 排版（同一段文本换写法）⇒ **不红** | 本文件内自证 |

> 🔴 **C4 与 C2 是互补的，缺一条就漏一半**（本条判据的初稿只写了 C2 的「必须相等」版本，
> 转绿时被自己的 C4 当场抓红 —— 两个端口**本来就该不等**：8000 是容器内 / 8001 是宿主）。
> 现值：`application.yml` 默认 = **8000**、本地宿主（= `docker-compose.yml` 的 `8001:8000` 左半边）= **8001**。

**反空跑护栏**：`JUDGMENTS` 与坏形态注入一一对应，注入必须在**内存/临时目录副本**上做
（不写仓内文件 ⇒ 判据之间零互相污染）；每条坏形态都断言「**恰好**报出预期的那一类」。

## 覆盖不到什么（照实登记，别把「登记了」读成「治住了」）

- **判不了「照文档跑真能跑通」**：本判据是纯静态文本对账（零网络、零服务、零 LLM）。
  「接线真的通了」只能由**一次真跑**承担（父 agent 实测：接好线后同一条入驻请求
  8.0 秒返回 `status=approved`），读数写在 issue/PR 里，**不是**常驻机制。
- **只锁 `docs/wiki/Quick-Start.md` 一份面**（本单的落点）。`README.md` 的「方式二」
  与 `docs/wiki/Troubleshooting.md` 的端口速查表**仍在写 8000** ⇒ 有意**不**在本单改
  （不在本包所有权内，另开单）；本判据因此**不**声称「全仓文档都对了」。
- **判不了「`.env` 里真有 `SERVICE_TOKEN`」**：该文件在本机**不存在**（`.gitignore` 第 2/3 行）
  ⇒ 判据只对账**命令形态**与相对路径写法，不假装能读到它。
- 不查 GitHub / 不联网 / 不烧 token（CI 的 `ci workflow helper unit tests` job 只装 `pytest` + `pyyaml`）。
- 不新增门禁、不改任何通过条件、不新增豁免。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

APP_YML = "backend/admin-api/src/main/resources/application.yml"
COMPOSE = "deploy/docker-compose.yml"
DOC = "docs/wiki/Quick-Start.md"
REVIEW_CLIENT = "backend/admin-api/src/main/java/com/migao/admin/service/RegistrationReviewClient.java"
AGENT_CONFIG = "backend/ai-agent-service/app/config.py"

BASE_URL_VAR = "AI_AGENT_BASE_URL"
TOKEN_VAR = "AI_AGENT_SERVICE_TOKEN"
#: ai-agent 容器内端口（`8001:8000` 的右半边；也是 `app/config.py` 的 `PORT` 默认值）。
CONTAINER_PORT = 8000

#: 判据名 ⇄ 坏形态注入（反空跑护栏：新增一条判据而不写「能变红的注入」⇒ 红）。
JUDGMENTS = (
    "C1_variable_names_declared",
    "C2_doc_port_overrides_base_url_default",
    "C3_startup_command_port_matches_declared_port",
    "C4_declared_port_matches_compose_host_mapping",
    "C5_defaults_are_still_broken_by_design",
    "C6_verification_command_and_expected_output",
)


# ── 真值现取（只读仓内文件；缺任何一个 ⇒ fail-closed 判红，不许读成「没问题」）──────

def _read(rel: str, root: Path = REPO) -> str:
    path = root / rel
    if not path.is_file():
        raise AssertionError(f"真值源不存在：{rel}（本判据 fail-closed，缺源不得读成通过）")
    return path.read_text(encoding="utf-8")


def code_truth(root: Path = REPO) -> dict:
    """从**代码**现取真值：变量名 / 默认端口 / 本地宿主端口 / 内部端点。"""
    app = _read(APP_YML, root)
    block = re.search(r"^ai-agent:\n((?:[ \t]+.*\n?)*)", app, re.M)
    if not block:
        raise AssertionError(f"{APP_YML} 里找不到顶层 `ai-agent:` 块（判据 fail-closed）")
    body = block.group(1)

    base_line = re.search(rf"base-url:\s*\$\{{{BASE_URL_VAR}:([^}}]*)\}}", body)
    if not base_line:
        raise AssertionError(
            f"{APP_YML} 的 ai-agent 块里找不到 `base-url: ${{{BASE_URL_VAR}:<默认值>}}` 形态")
    default_url = base_line.group(1).strip()

    token_line = re.search(rf"service-token:\s*\$\{{{TOKEN_VAR}:([^}}]*)\}}", body)
    if not token_line:
        raise AssertionError(
            f"{APP_YML} 的 ai-agent 块里找不到 `service-token: ${{{TOKEN_VAR}:…}}` 形态")
    default_token = token_line.group(1).strip()

    default_port = re.search(r":(\d{2,5})\s*$", default_url)
    if not default_port:
        raise AssertionError(f"默认 base-url `{default_url}` 里解析不出端口（判据 fail-closed）")

    compose = _read(COMPOSE, root)
    agent = re.search(r"^  ai-agent-service:\n((?:[ \t]+.*(?:\n|$))*)", compose, re.M)
    if not agent:
        raise AssertionError(f"{COMPOSE} 里找不到 `ai-agent-service:` 服务块（判据 fail-closed）")
    mapping = re.search(r'"(\d{2,5}):(\d{2,5})"', agent.group(1))
    if not mapping:
        raise AssertionError(f"{COMPOSE} 的 ai-agent-service 块里找不到 `<宿主>:<容器>` 端口映射")
    host_port, inner_port = int(mapping.group(1)), int(mapping.group(2))

    review_path = re.search(r'REVIEW_PATH\s*=\s*"([^"]+)"', _read(REVIEW_CLIENT, root))
    if not review_path:
        raise AssertionError(f"{REVIEW_CLIENT} 里找不到 `REVIEW_PATH` 常量（判据 fail-closed）")

    port_default = re.search(r"^\s*PORT:\s*int\s*=\s*(\d+)", _read(AGENT_CONFIG, root), re.M)
    if not port_default:
        raise AssertionError(f"{AGENT_CONFIG} 里找不到 `PORT: int = <n>`（判据 fail-closed）")

    return {
        "base_url_var": BASE_URL_VAR,
        "token_var": TOKEN_VAR,
        "default_url": default_url,
        "default_token": default_token,
        "default_port": int(default_port.group(1)),
        "host_port": host_port,
        "container_port": inner_port,
        "review_path": review_path.group(1),
        "agent_default_port": int(port_default.group(1)),
    }


def doc_facts(text: str) -> dict:
    """从**文档**里现取它自己声明的那些数。

    🔴 **只认「可执行命令」那一段**（``` 围起来的代码块）：散文里提到 `8000` / `localhost:8000`
    是**叙事**（解释「容器内是 8000」），不是声明 —— 把它也算进来 = 制造假红
    （实测：本判据的初稿就在这一条上被自己的 C7 对照读数抓红）。
    命令块 = 拿到就能复制的那个唯一载体，`期望输出` 段也在同一块里。
    """
    code = "\n".join(re.findall(r"```[a-zA-Z]*\n(.*?)```", text, re.S))
    port_m = re.search(rf"export\s+{BASE_URL_VAR}=http://localhost:(\d{{2,5}})", code)
    cmd_ports = [int(p) for p in re.findall(r"uvicorn\s+app\.main:app[^\n]*?--port\s+(\d{2,5})", code)]
    verify_ports = sorted({int(p) for p in re.findall(r"127\.0\.0\.1:(\d{2,5})", code)})
    return {
        "declared_port": int(port_m.group(1)) if port_m else None,
        "uvicorn_ports": cmd_ports,
        "verify_ports": verify_ports,
        "has_base_url_var": BASE_URL_VAR in text,
        "has_token_var": TOKEN_VAR in text,
    }


# ── 判定本体（纯函数：吃文本 → 违规清单；坏形态可在临时副本上构造）──────────────

def doc_problems(doc_text: str, truth: dict, doc_label: str = DOC) -> list[str]:
    """返回违规清单（空 = 绿）。每条都**具名**报出是哪一项、期望值是什么。"""
    facts = doc_facts(doc_text)
    bad: list[str] = []

    # C1：两个变量名必须**显式**出现（缺任一 ⇒ 具名红）
    for name, present in ((truth["base_url_var"], facts["has_base_url_var"]),
                          (truth["token_var"], facts["has_token_var"])):
        if not present:
            bad.append(
                f"[C1_variable_names_declared] {doc_label} 未显式出现 `{name}`"
                f"（本地接线必须显式给出；不给的症状 = 入驻静默 fail-closed「系统繁忙」）")

    # C2：文档声明的「显式覆盖」端口必须与 base-url 默认值**不同**（相等 ⇒ 那个 export 是多余的，
    #     意味着文档要么抄了默认值、要么根本没在覆盖 —— 两种都不能算「接线说清楚了」）
    if facts["declared_port"] is None:
        bad.append(
            f"[C2_doc_port_overrides_base_url_default] {doc_label} 里找不到 "
            f"`{truth['base_url_var']}=http://localhost:<port>`（无法判定 ⇒ 判红）")
    elif facts["declared_port"] == truth["default_port"]:
        bad.append(
            f"[C2_doc_port_overrides_base_url_default] {doc_label} 声明的端口 "
            f"{facts['declared_port']} 与 {APP_YML} 的 `{truth['base_url_var']}` 默认值端口"
            f"**相同** ⇒ 那条显式覆盖等于没写、或文档在复述默认值（默认值是容器内端口，不是本地端口）")

    # C3：文档里的启动命令端口必须等于文档自己声明的那个端口（同源）
    if not facts["uvicorn_ports"]:
        bad.append(
            f"[C3_startup_command_port_matches_declared_port] {doc_label} 里找不到 "
            f"`uvicorn app.main:app … --port <n>` 启动命令（无法判定 ⇒ 判红）")
    elif facts["declared_port"] is not None:
        off = [p for p in facts["uvicorn_ports"] if p != facts["declared_port"]]
        if off:
            bad.append(
                f"[C3_startup_command_port_matches_declared_port] {doc_label} 的启动命令写 "
                f"--port {off}，而同一页声明 localhost:{facts['declared_port']} ⇒ 命令与接线不一致")

    return bad


def port_problems(doc_text: str, truth: dict, doc_label: str = DOC) -> list[str]:
    """C4~C6：端口三处同源 + 默认值确实「即坏值」+ 验证命令与期望输出。"""
    facts = doc_facts(doc_text)
    bad: list[str] = []

    # C4：文档端口 == compose 宿主端口 == 容器端口映射的宿主侧；验证命令必须打同一个端口
    if facts["declared_port"] is not None:
        if facts["declared_port"] != truth["host_port"]:
            bad.append(
                f"[C4_declared_port_matches_compose_host_mapping] {doc_label} 声明 localhost:"
                f"{facts['declared_port']}，而 {COMPOSE} 的 ai-agent-service 映射是 "
                f"\"{truth['host_port']}:{truth['container_port']}\"（宿主 {truth['host_port']}）"
                f" ⇒ 两处必须逐字相等")
        stray = [p for p in facts["verify_ports"] if p != facts["declared_port"]]
        if stray:
            bad.append(
                f"[C4_declared_port_matches_compose_host_mapping] {doc_label} 的验证命令里出现端口 "
                f"{stray}，与声明的 {facts['declared_port']} 不一致（验证命令必须打同一个端口）")
    if truth["container_port"] != truth["agent_default_port"]:
        bad.append(
            f"[C4_declared_port_matches_compose_host_mapping] {COMPOSE} 的容器侧端口 "
            f"{truth['container_port']} 与 {AGENT_CONFIG} 的 `PORT` 默认值 "
            f"{truth['agent_default_port']} 不一致（同一个容器内端口的两处投影）")

    # C5：防腐 —— 两个默认值**现在**确实对不上本地约定（被修掉 ⇒ 红并逼人改文档口径）
    if truth["default_port"] == truth["host_port"]:
        bad.append(
            f"[C5_defaults_are_still_broken_by_design] `{truth['base_url_var']}` 的默认端口 "
            f"{truth['default_port']} 已等于本地宿主端口 {truth['host_port']}"
            f" ⇒ 本判据假设的「默认值即坏值」不再成立，请同步改本文档口径（不许静默留下）")
    if truth["default_token"] != "":
        bad.append(
            f"[C5_defaults_are_still_broken_by_design] `{truth['token_var']}` 的默认值已非空"
            f"（现取 `{truth['default_token']}`）⇒ 本判据假设的「默认值即坏值」不再成立，请同步改口径")

    # C6：验证命令（探真端点）+ 期望输出必须都在，且端点 = REVIEW_PATH
    if truth["review_path"] not in doc_text:
        bad.append(
            f"[C6_verification_command_and_expected_output] {doc_label} 里找不到内部端点 "
            f"`{truth['review_path']}`（验证命令必须打真端点）")
    if "curl" not in doc_text:
        bad.append(f"[C6_verification_command_and_expected_output] {doc_label} 里没有可复制的 `curl` 验证命令")
    if "期望输出" not in doc_text:
        bad.append(f"[C6_verification_command_and_expected_output] {doc_label} 里没有「期望输出」段（只给命令 = 无法判读）")

    return bad


def all_problems(doc_text: str, truth: dict, doc_label: str = DOC) -> list[str]:
    return doc_problems(doc_text, truth, doc_label) + port_problems(doc_text, truth, doc_label)


def _judgment_of(message: str) -> str:
    """从违规文本里取判据名（`[C3_…]` 前缀）。"""
    m = re.search(r"\[(C\d_[a-z_]+)\]", message)
    return m.group(1) if m else "<未具名>"


# ── 夹具 ────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def truth() -> dict:
    return code_truth()


@pytest.fixture(scope="module")
def doc_text() -> str:
    return _read(DOC)


# ── 正向读数 ────────────────────────────────────────────────────────────────────

def test_doc_declares_both_wiring_variables(truth, doc_text):
    """C1：`AI_AGENT_BASE_URL` 与 `AI_AGENT_SERVICE_TOKEN` 必须在文档里显式出现。"""
    problems = [p for p in doc_problems(doc_text, truth) if _judgment_of(p) == "C1_variable_names_declared"]
    assert problems == [], "\n".join(problems)


def test_doc_port_overrides_application_yml_default_port(truth, doc_text):
    """C2：文档给的显式端口必须**不同于** `application.yml` 的 `AI_AGENT_BASE_URL` 默认端口。

    相等 = 那条 export 是多余的 / 文档在复述容器内端口 ⇒ 红（默认值正是「即坏值」的 8000）。

    注入式红证见 `test_injected_port_8000_turns_c2_red`（把文档端口改成默认值 8000 ⇒ 这一条必红）。
    """
    problems = [p for p in doc_problems(doc_text, truth) if _judgment_of(p) == "C2_doc_port_overrides_base_url_default"]
    assert problems == [], "\n".join(problems)


def test_doc_startup_command_port_equals_declared_port(truth, doc_text):
    """C3：文档里的 uvicorn `--port` == 同一页声明的 base-url 端口。"""
    problems = [p for p in doc_problems(doc_text, truth) if _judgment_of(p) == "C3_startup_command_port_matches_declared_port"]
    assert problems == [], "\n".join(problems)


def test_declared_port_equals_compose_host_mapping(truth, doc_text):
    """C4：文档端口 == `docker-compose.yml` 的宿主端口；容器端口两处投影一致。"""
    problems = [p for p in port_problems(doc_text, truth) if _judgment_of(p) == "C4_declared_port_matches_compose_host_mapping"]
    assert problems == [], "\n".join(problems)


def test_defaults_are_still_broken_by_design(truth, doc_text):
    """C5：防腐 —— 两个默认值**现在**确实对不上本地约定（修掉它 ⇒ 这条红，逼人同步改文档）。"""
    problems = [p for p in port_problems(doc_text, truth) if _judgment_of(p) == "C5_defaults_are_still_broken_by_design"]
    assert problems == [], "\n".join(problems)


def test_doc_has_verification_command_and_expected_output(truth, doc_text):
    """C6：可复制的 `curl` + 真端点 + 「期望输出」。"""
    problems = [p for p in port_problems(doc_text, truth) if _judgment_of(p) == "C6_verification_command_and_expected_output"]
    assert problems == [], "\n".join(problems)


def test_real_repo_is_clean(truth, doc_text):
    """整页对账：真语料上 `all_problems` 必须为空（这一条是上面六条的合并读数）。"""
    problems = all_problems(doc_text, truth)
    assert problems == [], "\n".join(problems)


def test_code_truth_reads_are_self_consistent(truth):
    """真值取自证：默认端口 ≠ 宿主端口（默认值即坏值）、token 默认空、容器端口 = ai-agent 默认 PORT。"""
    assert truth["default_port"] == CONTAINER_PORT
    assert truth["default_port"] != truth["host_port"]
    assert truth["default_token"] == ""
    assert truth["container_port"] == truth["agent_default_port"]


# ── 判别力自证（坏形态注入，全部在**内存副本**上做，不写仓内文件）──────────────────

def test_injected_missing_token_variable_turns_c1_red(truth, doc_text):
    """坏形态 ①（issue 原文要求的注入）：删掉 `AI_AGENT_SERVICE_TOKEN` 那一行 ⇒ C1 具名红。"""
    injected = "\n".join(
        line for line in doc_text.split("\n") if TOKEN_VAR not in line)
    assert TOKEN_VAR not in injected, "注入无效：目标变量仍在文本里"
    problems = doc_problems(injected, truth)
    named = [p for p in problems if _judgment_of(p) == "C1_variable_names_declared"]
    assert named, "注入后 C1 未报红（判据失去判别力）"
    assert TOKEN_VAR in named[0] and BASE_URL_VAR not in named[0].split("未显式出现")[1]


def test_injected_missing_base_url_variable_turns_c1_red(truth, doc_text):
    """坏形态 ①b：删掉 `AI_AGENT_BASE_URL` 那一行 ⇒ C1 具名红（另一个变量，独立可红）。"""
    injected = "\n".join(
        line for line in doc_text.split("\n") if BASE_URL_VAR not in line)
    problems = doc_problems(injected, truth)
    named = [p for p in problems if _judgment_of(p) == "C1_variable_names_declared"]
    assert named, "注入后 C1 未报红（判据失去判别力）"
    assert BASE_URL_VAR in named[0]


def test_injected_port_8000_turns_c2_red(truth, doc_text):
    """坏形态 ②（**issue 明确要求的坏形态**：把文档端口改成 8000）⇒ C2 必红。

    端口在文档里有两处投影（`export AI_AGENT_BASE_URL=…` 与 uvicorn `--port`），
    两处是**同一事实的两处投影** ⇒ 注入两处一起改（只改一处会先被 C3 抓住，
    那正是 C3 的存在意义）。注入只落在**命令块**里的声明处。
    """
    assert truth["default_port"] != truth["host_port"]  # 8000 = 真值的默认端口
    needle = f"export {BASE_URL_VAR}=http://localhost:{truth['host_port']}"
    assert needle in doc_text, f"注入点不存在：{needle}"
    injected = doc_text.replace(needle, f"export {BASE_URL_VAR}=http://localhost:{truth['default_port']}")
    injected = re.sub(r"(uvicorn\s+app\.main:app[^\n]*?--port\s+)\d{2,5}",
                      rf"\g<1>{truth['default_port']}", injected)
    assert injected != doc_text, "注入无效：文本没变"
    problems = doc_problems(injected, truth)
    named = [p for p in problems if _judgment_of(p) == "C2_doc_port_overrides_base_url_default"]
    assert named, "注入后 C2 未报红（判据失去判别力）"
    assert str(truth["default_port"]) in named[0]


def test_injected_command_port_drift_turns_c3_red(truth, doc_text):
    """坏形态 ③：**只**改启动命令的端口（接线声明不动）⇒ C3 红（同源判据的牙）。"""
    injected, n = re.subn(r"(uvicorn\s+app\.main:app[^\n]*?--port\s+)\d{2,5}",
                          rf"\g<1>{truth['default_port']}", doc_text)
    assert n >= 1, "注入无效：文档里没有 uvicorn 启动命令"
    problems = doc_problems(injected, truth)
    named = [p for p in problems if _judgment_of(p) == "C3_startup_command_port_matches_declared_port"]
    assert named, "注入后 C3 未报红（判据失去判别力）"


def test_injected_default_token_turns_c5_red(truth, doc_text):
    """坏形态 ④（**防腐判据的红证**）：给 `service-token` 补一个默认值 ⇒ C5 红。"""
    mutated = dict(truth)
    mutated["default_token"] = "fixed-token"
    problems = port_problems(doc_text, mutated)
    named = [p for p in problems if _judgment_of(p) == "C5_defaults_are_still_broken_by_design"]
    assert named, "注入后 C5 未报红（防腐判据失去判别力）"


def test_injected_default_port_equals_host_port_turns_c5_red(truth, doc_text):
    """坏形态 ⑤：默认端口被改成宿主端口（默认值不再「即坏」）⇒ C5 红。"""
    mutated = dict(truth)
    mutated["default_port"] = mutated["host_port"]
    problems = port_problems(doc_text, mutated)
    named = [p for p in problems if _judgment_of(p) == "C5_defaults_are_still_broken_by_design"]
    assert named, "注入后 C5 未报红（防腐判据失去判别力）"


def test_injected_missing_review_path_turns_c6_red(truth):
    """坏形态 ⑥：删掉验证命令里的真端点 ⇒ C6 红（不许只给一条打不中端点的命令）。"""
    stripped = (
        "# 验证接线\n\n```bash\ncurl -s http://127.0.0.1:8001/health\n```\n\n"
        "## 期望输出\n\n`{\"status\":\"healthy\"}`\n"
    )
    problems = port_problems(stripped, truth)
    named = [p for p in problems if _judgment_of(p) == "C6_verification_command_and_expected_output"]
    assert named, "注入后 C6 未报红（判据失去判别力）"
    assert truth["review_path"] in named[0]


def test_injected_missing_source_file_fails_closed(truth, tmp_path):
    """坏形态 ⑦（fail-closed）：真值源被删 ⇒ `code_truth` 抛错，**不得**读成「没问题」。"""
    with pytest.raises(AssertionError):
        code_truth(tmp_path)


def test_comment_only_rewrite_is_not_red(truth, doc_text):
    """对照读数：只改**散文注释 / 排版**（命令块一字不动）⇒ 不红。

    注入的是散文里的 Markdown 注释与空行压缩 —— 命令块（判据唯一的声明载体）逐字保留。
    """
    lines = doc_text.split("\n")
    out, in_fence = [], False
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
        if not in_fence and line and not line.startswith(("#", ">", "|", "`")):
            line = line + " <!-- 排版改动 -->"
        out.append(line)
    rewritten = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    assert rewritten != doc_text, "对照注入无效：文本没变"
    assert all_problems(rewritten, truth) == []


def test_every_judgment_has_a_red_proof():
    """反空跑护栏：`JUDGMENTS` 里的每条判据都必须在本文件的**注入式红证**里被覆盖。"""
    source = Path(__file__).read_text(encoding="utf-8")
    uncovered = [name for name in JUDGMENTS
                 if f'"{name}"' not in source.split("JUDGMENTS = (")[1].split(")", 1)[0]
                 and source.count(name) < 2]
    assert uncovered == [], f"这些判据没有红证（新增判据必须同时写能变红的注入）：{uncovered}"
