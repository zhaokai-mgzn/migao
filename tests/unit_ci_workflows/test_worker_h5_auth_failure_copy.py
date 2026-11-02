# case_ids: MC-012, PG-065, BM-045
"""工人端 H5 **登录失败文案**的类级元守卫（AGENTS.md 铁律 8「类级固化」，issue #6747）。

## 病根（实测，不是推断）

车间现场端 `frontend/worker-h5/`（线上 `https://app.migaozn.com/w/`）登录页在**认证失败**时
把服务端**已经给出的确定原因**说成泛化话术，或干脆只给一句判定、不说该干什么：

| # | 场景 | 改前屏上（逐字） | 为什么要紧 |
|---|---|---|---|
| a | `401 AUTH_FAILED`（实测「工号或 PIN 不正确」） | `工号或 PIN 不正确` | 只有判定、**没有动作** ⇒ 工人只能来问人 |
| b | `401` 但响应体没带可读原因 / 非 JSON | `登录已失效，请重新用工号 + PIN 登录` | 对**刚按下登录按钮**的工人是错归因：他没"失效"，他是**打错了** |
| c | 任何非 401 失败且响应体没 message | `操作没成功（请再试一次；若反复如此请找管理员）` | 「**请再试一次**」⇒ 打了错 PIN 的工人**反复重试**，而不是去核对工号 / PIN |

生产实测（2026-10-11，可复制；数据集单一源 = `frontend/worker-h5/tests/worker-h5-6747-login-payloads.mjs`）::

    curl -s -X POST https://app.migaozn.com/api/worker/login -H 'Content-Type: application/json' \\
      -d '{"workerNo":"wuitest","pin":"wrongpin","enterpriseCode":"migao"}'
    # 401 {"success":false,"error":{"code":"AUTH_FAILED","message":"工号或 PIN 不正确"},…}

现场风险 = 「文案把工人引向错误的动作」：本批（客户试用前 UI 收尾 P1–P29）的口径是
**服务端已有的确定原因要透给用户**、**不许归因给用户能感知不到的原因**。

## 本守卫锁什么（全部按**源文本**判，不跑 Node —— CI 的 `ci-workflow-tests` 腿没有 Node）

1. **实现里那条通道存在**：`frontend/worker-h5/src/api.mjs` 里 401 的 `AUTH_FAILED` 分流
   （`payload?.error?.code === AUTH_FAILED`）**带**认证话术（`authFailureMessage(...)`）；
2. **改前的病态行不得回来**：`?? '登录已失效，请重新用工号 + PIN 登录'` 这个 401 兜底字面
   一旦重新出现在 401 通道里，就是 (b) 那个错归因形态 ⇒ 判红（#6747 之后它只剩在
   「非 AUTH_FAILED 且服务端给了 message」的对照路径上）；
3. **服务端真值与前端兜底判定同源**：`api.mjs` 里那句兜底判定必须与**生产响应体**里的
   `message` 逐字相同（不许前端自己发明第二句）；
4. **判据真的接上去**：`frontend/worker-h5/tests/worker-h5-6747-auth-failed-copy.test.mjs`
   必须存在、必须声明 `case_ids:`、且 `.github/workflows/worker-h5-tests.yml` 的
   `node --test frontend/worker-h5/tests/*.test.mjs` 必须覆盖它（glob 认 `*.test.mjs`
   ⇒ 文件名形态本身就是接线判据）；
5. **判别力自证（注入式）**：把**改前的三种形态**分别注入真实的 `api.mjs` 文本 ⇒
   检查器必须各自判红；未注入的真实文件必须判绿（正反对照，杜绝"不会红的空断言"）；
6. **判据不许写共享扫描面**（issue #8415，flake 根因）：套件里**任何**判据都不得把变异注入**写回仓库工作树** ——
   `ci workflow helper unit tests` 用 `-n 4` 并行（`.github/workflows/pr-check.yml` 的
   `python -m pytest tests/unit_ci_workflows … -n 4`），一次「临时写回 + 还原」会让**同期**读同一个文件的判据
   读到变异体。实测（本包）：`-n 2` 只挑本条与 `test_injection_unwired_case_file_is_red` ⇒ **39/40 红**，
   报错逐字 = `worker-h5-tests.yml 不再跑 node --test …`（即判据 ⑤ 读到**别人写进去的**变异体）；
   台账里另有一条同源受害读数（run `39927788364`：`test_worker_h5_ci_wiring.py::test_red_proof_continue_on_error[step]`
   与本条**同一次**失败 —— 两条判据读的是同一份 workflow）。
   ⇒ 变异一律走**文本参数**（`copy_defects(…, workflow_text=…)`），且落地类级元守卫
   `test_no_guard_mutates_the_repo_tree_in_place`：AST 扫描 `tests/unit_ci_workflows/*.py` 的仓内写操作，
   **未登记即红**、台账**只许缩短**（判别力另有注入式自证）。

**已知边界（照实登记）**：本守卫判的是**源文本形态**，不是"那段代码跑起来会输出什么"——
后者由实例判据 `frontend/worker-h5/tests/worker-h5-6747-auth-failed-copy.test.mjs`（真跑到
`createApi().login()` 的 401 路径）在 `worker-h5 unit tests (node --test)` 腿上承担；
两侧互指、不互为副本（本守卫**不执行** node）。

类级元守卫（第 6 条）判的同样是**形态**，不是「他到底想不想写盘」：射程内的接收者形态是
①模块级「仓内路径」名字 ②表达式里出现 `REPO_ROOT` / `__file__`。**不在射程**（如实登记）：
路径经函数参数 / 变量拼接后再传、行内 `<表达式>.replace(…)` / `rename(…)`（`str.replace` 假阳性太多，
只对「仓内路径名字」这一档判）；也不判「他写了盘之后有没有还原」——**写本身就是共享写面**。
"""
from __future__ import annotations

import ast
import re
import warnings
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API = REPO_ROOT / "frontend" / "worker-h5" / "src" / "api.mjs"
PAYLOADS = REPO_ROOT / "frontend" / "worker-h5" / "tests" / "worker-h5-6747-login-payloads.mjs"
CASE_FILE = REPO_ROOT / "frontend" / "worker-h5" / "tests" / "worker-h5-6747-auth-failed-copy.test.mjs"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "worker-h5-tests.yml"

#: 改前 401 通道里那句**错归因**兜底（病灶 b）——413 字符以内的形态；它是本守卫要挡住的对象。
PRE_FIX_401_FALLBACK = "?? '登录已失效，请重新用工号 + PIN 登录'"

#: 病灶 a 的形态：401 通道里**只有**服务端 message、没有认证话术。
PRE_FIX_401_PLAIN = "new Error(payload?.error?.message ?? '登录已失效，请重新用工号 + PIN 登录')"

#: 病灶 c 的形态：登录面失败落到泛化重试话术。
GENERIC_RETRY = "操作没成功（请再试一次；若反复如此请找管理员）"


def _api_text() -> str:
    return API.read_text(encoding="utf-8")


def _strip_comments(code: str) -> str:
    """剥掉块注释与行注释 —— **讲沿革的注释不算屏面文案**（同 `worker-h5-6738-*` 用例的口径）。

    🔴 必需，不是洁癖：本单的文档注释里**逐字引用了改前那两句病灶文案**（那是"病根"证据），
    不剥 ⇒ 检查器把注释当成代码，真实文件被自己的注释判红（实测踩过）。
    """
    code = re.sub(r"/\*[\s\S]*?\*/", "", code)
    return re.sub(r"^\s*(//|\*|/\*).*$", "", code, flags=re.M)


def _api_code() -> str:
    """`api.mjs` 的**代码**（剥注释）。"""
    return _strip_comments(_api_text())


def _auth_branch(code: str) -> str:
    """401 分支的源文本（`res.status === 401` 到它的 `throw` 之后第一个 `}`）。"""
    macro = "res.status === 401"
    i = code.find(macro)
    if i < 0:
        return ""
    j = code.find("throw err", i)
    if j < 0:
        return ""
    k = code.find("}", j)
    return code[i : k + 1]


def _js_string_literals(text: str) -> set[str]:
    """取**单 / 双引号**字面量集合（实现里的兜底判定只可能来自这里；反引号模板串不算）。

    🔴 刻意**不**把反引号模板串算进来：模板串里含插值（`${notice}` 之类），
    直接整体匹配会把"前端另造了一句判定"这种形态也放过（`_determination_phrases` 管那一半）。
    🔴 **纯字符串操作，不用正则**（不是洁癖）：本仓的元守卫
    `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py` 钉的正是「按引号扫源码原文取值」这一族
    —— 判据把「原文文本」当「代码」读（注释里的假声明就能喂中）。本单实测被它判红（CI run 38096003684），
    现按它给的出口改写：取值只用**字符串操作**（`split` / 索引），正则只用于**结构性**匹配（不留引号捕获组）。
    """
    lits: set[str] = set()
    for q in ("'", '"'):
        chunks = text.split(q)
        if len(chunks) >= 3:  # 奇数段 = 闭合的引号对（第 0 / 末段在引号外）
            lits.update(chunks[1:-1:2])
    return lits


def _determination_phrases(code: str) -> set[str]:
    """模板串里 `，${…}` 之前的判定短语（前端"判定 + 动作"的合成点）。

    正则**只做结构性匹配**（反引号定界 + `${` 插值起点），**不含引号捕获组**
    ⇒ 不在元守卫 `test_guard_parsing_is_comment_aware.py` 的"按引号扫原文"面内（实测判绿）。
    """
    return {m.split("，")[0].strip() for m in code.split("`") if "，${" in m}


def _production_auth_failed_message() -> str:
    """生产响应体里 `AUTH_FAILED` 的那句 `message`（用例数据集 = 逐字实测，见文件头）。

    取法 = **字符串操作**（本仓 `frontend/worker-h5/tests/worker-h5-6747-login-payloads.mjs` 的写法
    固定为一行 `error: { code: 'AUTH_FAILED', message: '<逐字>' }`）⇒ 不引第二套解析器。
    """
    text = PAYLOADS.read_text(encoding="utf-8")
    marker = "'AUTH_FAILED', message: '"
    assert marker in text, "数据集里必须有 AUTH_FAILED 的 `code` + `message` 对（生产实测响应体）"
    rest = text.split(marker, 1)[1]
    assert "'" in rest, "AUTH_FAILED 的 message 引号未闭合（数据集被改坏了）"
    return rest.split("'", 1)[0]


def copy_defects(
    api_text: str,
    auth_failed_message: str,
    workflow_text: str | None = None,
) -> list[str]:
    """把「登录失败文案」这一类的坏形态判红（纯函数，便于注入式自证）。

    :param api_text: `frontend/worker-h5/src/api.mjs` 的源文本（真实文件或注入后的副本）
    :param auth_failed_message: 生产 `AUTH_FAILED` 响应体里的 `message`（逐字）
    :param workflow_text: 判据 ⑤ 读的 workflow 源文本。**缺省 = 读真实文件**
        （= 生产判定路径，由 `test_real_source_has_no_login_failure_copy_defect` 走）；
        注入式用例**必须**显式传文本 —— 它**绝不**写真实文件（issue #8415：写回 + 还原与 CI 的
        `-n 4` 并行冲突 ⇒ 同期读该文件的判据读到变异体，实测两条不同判据同时判红）。
    """
    problems: list[str] = []
    code = _strip_comments(api_text)
    branch = _auth_branch(code)

    # ① 401 通道存在，且它点名了服务端的 AUTH_FAILED
    if not branch:
        problems.append("api.mjs 里找不到 401 分支（`res.status === 401` + `throw err`）—— 认证失败的呈现路径没了")
    else:
        if "payload?.error?.code === AUTH_FAILED" not in branch:
            problems.append(
                "401 通道里没有 `payload?.error?.code === AUTH_FAILED` 分流（服务端点名的原因没被认出来）"
            )
        # ② 病灶 (a)：401 通道直接透 message（只有判定、没有动作）
        if PRE_FIX_401_PLAIN in branch or "authFailureMessage(" not in branch:
            problems.append("401 通道没有合成「判定 + 动作」（认证失败只剩一句话、不给可行动作）")
        # ②b 401 且响应体什么都没说时，必须靠调用方带上来的语境分辨「凭据不对 / 会话没了」
        if "credentials" not in branch:
            problems.append("401 通道缺 `credentials` 语境 ⇒ 无响应体的 401 会落回「登录已失效」错归因")

    # ③ 病灶 (c)：登录面失败落到泛化重试话术
    if GENERIC_RETRY in branch:
        problems.append(f"401 通道落到泛化重试话术「{GENERIC_RETRY}」（打了错 PIN 的工人会反复重试）")
    auth_fn = code[code.find("function authFailureMessage") : code.find("function transportMessage")]
    if GENERIC_RETRY in auth_fn:
        problems.append("`authFailureMessage` 里出现泛化重试话术（认证面不许回落到它）")

    # ④ 兜底判定必须与服务端那句**同源**（不许前端自己发明第二句）
    if auth_failed_message not in _js_string_literals(code) and auth_failed_message not in _determination_phrases(code):
        problems.append(
            f"api.mjs 的兜底判定必须与生产响应体里的 message 逐字相同（缺 {auth_failed_message!r} ⇒ 前端另造了一句）"
        )

    # ④b 登录调用必须**显式**带语境（只在分支里"提到" credentials 不算接线）
    login_call = code[code.find("'/api/worker/login'"):] if "'/api/worker/login'" in code else ""
    if "credentials: true" not in login_call[:400]:
        problems.append("`/api/worker/login` 的请求没带 `credentials: true` ⇒ 无响应体的 401 无法分辨凭据不对 / 会话没了")

    # ⑤ 判据真的接上去（实例判据存在 + case_ids + CI glob 覆盖）
    if not CASE_FILE.exists():
        problems.append(f"实例判据缺失：{CASE_FILE.relative_to(REPO_ROOT)} 不存在")
    else:
        head = CASE_FILE.read_text(encoding="utf-8").splitlines()[:50]
        if not any(ln.lstrip().startswith(('# case_ids', '// case_ids', '* case_ids', '#case_ids')) for ln in head):
            problems.append("实例判据文件前 50 行没有 `case_ids:` 声明（QA Growth Gate 会 block）")
    wf = WORKFLOW.read_text(encoding="utf-8") if workflow_text is None else workflow_text
    if "node --test frontend/worker-h5/tests/*.test.mjs" not in wf:
        problems.append("worker-h5-tests.yml 不再跑 `node --test frontend/worker-h5/tests/*.test.mjs`（实例判据会退回死文件）")

    return problems


def _mutate_plain(api_text: str, old: str, new: str) -> str:
    """注入变异（**纯字符串**替换 + 自证生效）。

    🔴 为什么不用正则：本仓元守卫 `test_guard_parsing_is_comment_aware.py` 把「按引号扫原文取值」判红
    ⇒ 凡是要替换的锚点里**含引号**的，一律走字符串操作（与 `_js_string_literals` 同一处置）。
    """
    assert old in api_text, f"变异注入点不存在（字符串未命中）：{old!r} ⇒ 该用例会退化成空断言"
    mutated = api_text.replace(old, new, 1)
    assert mutated != api_text, "变异注入没有改变文本"
    return mutated


def _mutate_re(api_text: str, pattern: str, repl: str) -> str:
    """注入变异（**正则** + 自证生效）。

    🔴 为什么用正则而不是整段字面替换：字面锚点会**随格式漂移**（本单就实测踩过 ——
    源码一次换行调整就让两个注入点失配，用例从"能红"退化成"空断言"）。
    正则锚点钉的是**语义片段**（`? authFailureMessage(...)` / 兜底那句），格式动了照样命中。
    """
    mutated, n = re.subn(pattern, repl, api_text, count=1)
    assert n == 1, f"变异注入点不存在（正则未命中）：{pattern!r} ⇒ 该用例会退化成空断言"
    assert mutated != api_text, "变异注入没有改变文本"
    return mutated


# ── 真实文件：必须判绿 ────────────────────────────────────────────────────────────

def test_real_source_has_no_login_failure_copy_defect() -> None:
    problems = copy_defects(_api_text(), _production_auth_failed_message())
    assert problems == [], "登录失败文案的类级判据判红：\n  - " + "\n  - ".join(problems)


def test_production_message_is_the_single_source() -> None:
    """服务端那句被 `api.mjs` 与用例数据集**逐字共用**（两处漂移 ⇒ 红）。"""
    msg = _production_auth_failed_message()
    assert msg == "工号或 PIN 不正确", f"生产 AUTH_FAILED 的 message 逐字应为此（数据集可能被改）：{msg!r}"
    code = _api_code()
    assert msg in _js_string_literals(code) or msg in _determination_phrases(code), (
        "api.mjs 的兜底判定必须与生产响应体那句逐字相同"
    )
    payloads = PAYLOADS.read_text(encoding="utf-8")
    assert msg in payloads, "数据集必须写明生产那句（单一真值）"
    assert PRE_FIX_401_PLAIN not in _api_code(), "改前的错归因兜底不得回到 401 通道"
    assert "PIN 不能为空" in payloads and "'pin'" in payloads, "数据集必须写明 422 的逐字段形状（#6738 消费它）"


# ── 判别力自证：改前三种形态各自注入 ⇒ 必须各自判红 ──────────────────────────────

def test_injection_pre_fix_auth_failed_has_no_action_is_red() -> None:
    """病灶 (a)：401 通道改回「只透服务端 message」⇒ 必红。"""
    mutated = _mutate_re(
        _api_text(),
        r"\?\s*authFailureMessage\(payload\?\.error\)",
        "? (payload?.error?.message ?? 'x')",
    )
    problems = copy_defects(mutated, _production_auth_failed_message())
    assert problems, "把认证话术撤掉后本守卫必须判红（否则它守不住 #6747）"


def test_injection_generic_retry_on_login_face_is_red() -> None:
    """病灶 (c)：登录面失败落到泛化重试话术 ⇒ 必红。"""
    mutated = _mutate_re(
        _api_text(),
        r": \(payload\?\.error\?\.message \?\? '登录已失效，请重新用工号 \+ PIN 登录'\)",
        f": (payload?.error?.message ?? '{GENERIC_RETRY}')",
    )
    problems = copy_defects(mutated, _production_auth_failed_message())
    assert problems, "泛化重试话术回到 401 通道后本守卫必须判红"


def test_injection_frontend_invents_its_own_determination_is_red() -> None:
    """形态：前端自己发明一句判定（与服务端那句不一致）⇒ 必红。"""
    mutated = _mutate_re(_api_text(), r"`工号或 PIN 不正确，\$\{notice\}`", "`账号或密码不正确，${notice}`")
    problems = copy_defects(mutated, _production_auth_failed_message())
    assert any("逐字相同" in p for p in problems), f"前端另造判定句没被判红：{problems}"


def test_injection_login_call_without_credentials_context_is_red() -> None:
    """形态：登录请求不再带 `credentials` 语境 ⇒ 无响应体的 401 退回错归因 ⇒ 必红。"""
    mutated = _mutate_plain(_api_text(), "credentials: true,", "")
    problems = copy_defects(mutated, _production_auth_failed_message())
    assert any("credentials" in p for p in problems), f"撤掉登录语境没被判红：{problems}"


def test_injection_unwired_case_file_is_red() -> None:
    """形态：CI 的 glob 不再覆盖实例判据 ⇒ 必红（判据接不上去 = 死文件）。

    🔴 变异**只进文本参数**（issue #8415 的根因修法）：写回真实 workflow 会让 `-n 4` 下的**同期**
    判据读到变异体 —— 本条原实现在 `-n 2` 下实测 39/40 红（红的是**别的**判据），故不再落盘。
    """
    wf = WORKFLOW.read_text(encoding="utf-8")
    broken = wf.replace(
        "node --test frontend/worker-h5/tests/*.test.mjs",
        "node --test frontend/worker-h5/tests/worker-h5-api.test.mjs",
    )
    assert broken != wf, "变异注入没生效"
    problems = copy_defects(_api_text(), _production_auth_failed_message(), workflow_text=broken)
    assert any("node --test" in p for p in problems), f"接线断掉没被判红：{problems}"
    assert WORKFLOW.read_text(encoding="utf-8") == wf, "变异注入泄漏到真实文件了（判据会与并行腿互相打架）"


# ── 对照读数：未注入 ⇒ 不红（防"什么都判红"） ────────────────────────────────────

def test_unmutated_source_is_green_control() -> None:
    api_text = _api_text()
    assert GENERIC_RETRY in api_text, "前置：泛化话术仍应存在于**非认证**的传输层兜底档（本单只把它从认证面挪开）"
    assert copy_defects(api_text, _production_auth_failed_message()) == []


# ── 负控：**合法**文案改写 ⇒ 必须不红（防"什么都判红"） ──────────────────────────────

def test_injection_legal_copy_rewording_is_green_control() -> None:
    """合法改写（仍「判定 + 动作」、仍逐字保留服务端那句）⇒ 本判据**不许**红。

    与 `test_injection_pre_fix_auth_failed_has_no_action_is_red` 构成**正反对照**：
    前者证明它抓得到真缺陷，后者证明它抓的**不是**「文案变过」本身。
    """
    mutated = _mutate_re(
        _api_text(),
        r"const notice = '[^']*'",
        "const notice = '请核对工号与 PIN 后再试一次'",
    )
    assert copy_defects(mutated, _production_auth_failed_message()) == []


# ── 类级元守卫：判据不许把变异注入写回仓库工作树（issue #8415 的**根因**，不是这一处） ────────────
#
# 病：`test_injection_unwired_case_file_is_red` 原实现把 workflow **写回真实文件**再还原。
#     套件是 `-n 4` 并行跑的 ⇒ 「写回」窗口内任何读同一文件的判据都读到变异体。
#     实测：`-n 2` 只挑本条与它 ⇒ **39/40 红**；CI 台账 run 39927788364 里
#     `test_worker_h5_ci_wiring.py::test_red_proof_continue_on_error[step]` 与本条**同一次**失败。
# 治法：**类级** —— 套件里任何「写仓内路径」的判据都必须登记；未登记即红、台账只许缩短。

#: **允许**在套件运行期写仓内路径的存量（只许缩短；每条必须写清为什么**不是**共享写面）。
REPO_WRITE_ALLOWLIST: dict[tuple[str, str], str] = {
    ("test_bmini_mobile_typography_floor.py", "_regen"): (
        "人工重生成入口（`python3 tests/unit_ci_workflows/test_bmini_mobile_typography_floor.py --regen`）："
        "只从 `__main__` 分派，pytest 收集 / 运行期**走不到** ⇒ 不在 `-n 4` 的共享写面里"
    ),
}

#: 判为「写盘」的 `Path` 方法 / `os`·`shutil` 函数名（两组分开：同名 `open` 要另判模式）。
#: 🔴 `replace` / `rename` **另列**：`str.replace` 到处都有（实测本仓 4 处 `str(...).replace('\\','/')`），
#: 只认「接收者是**仓内路径名字**」那一档（行内表达式的 `Path.replace` 落进下面的已知边界）。
_MUTATING_ATTRS = frozenset({"replace", "rename"})
_WRITE_ATTRS = frozenset({
    "write_text", "write_bytes", "unlink", "touch", "mkdir", "rmdir",
    "symlink_to", "chmod",
})
_WRITE_FUNCS = frozenset({
    "open", "remove", "unlink", "rename", "replace", "rmdir",
    "copy", "copy2", "copyfile", "move",
})
#: 值表达式里出现这两个之一 ⇒ 该模块级名字**指向仓内路径**（`REPO_ROOT` 常量 / 判据自身 `__file__`）。
_REPO_MARKERS = ("REPO_ROOT", "__file__")
#: `open(…)` 的模式串里出现这些 ⇒ 写（否则是读，不算共享写面）。
_WRITE_MODES = ("w", "a", "x", "+")


def _repo_path_names(tree: ast.Module) -> set[str]:
    """模块级「指向仓内路径」的名字集合（纯 AST，不引第二套解析）。"""
    names: set[str] = set()
    for node in tree.body:
        value = None
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        src = ast.unparse(value)
        if any(m in src for m in _REPO_MARKERS):
            names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def _is_repo_name(node: ast.expr, repo_names: set[str]) -> bool:
    return isinstance(node, ast.Name) and node.id in repo_names


def _write_target(call: ast.Call, repo_names: set[str]) -> ast.expr | None:
    """这次调用**写到哪**（不是读）：`<路径>.<写方法>()` / `open(path, 'w')` / `os.remove(path)` / `shutil.copy(src, dst)`。"""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in _WRITE_ATTRS:
        return func.value
    if isinstance(func, ast.Attribute) and func.attr in _MUTATING_ATTRS:
        return func.value if _is_repo_name(func.value, repo_names) else None
    if isinstance(func, ast.Name) and func.id in _WRITE_FUNCS:
        if func.id == "open":
            if not call.args:
                return None
            mode_arg: ast.expr | None = call.args[1] if len(call.args) > 1 else None
            for kw in call.keywords:
                if kw.arg == "mode":
                    mode_arg = kw.value
            mode = mode_arg.value if isinstance(mode_arg, ast.Constant) else ""
            return call.args[0] if isinstance(mode, str) and any(m in mode for m in _WRITE_MODES) else None
        if func.id in {"remove", "unlink", "rmdir"}:
            return call.args[0] if call.args else None
        return call.args[-1] if call.args else None  # copy / copy2 / copyfile / move / rename / replace
    return None


def repo_tree_writes(source: str) -> list[tuple[str, int, str]]:
    """源文本 → 「写仓内路径」的 `(所在函数, 行号, 表达式)` 清单（**纯函数**，便于注入式自证）。

    判的是**形态**：`<仓内路径名>.<写方法>(…)` / `open(<仓内路径>, 'w')` /
    `os.remove|shutil.copy2|os.replace(…, <仓内路径>)`。语法坏掉的源文本 ⇒ 空清单（不在这里当语法检查器）。
    """
    with warnings.catch_warnings():
        # 源文件里的合法 `\s` / `\.` 正则会触发 `SyntaxWarning`（不是缺陷）⇒ 别把它变成套件噪音
        warnings.simplefilter("ignore", SyntaxWarning)
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
    repo_names = _repo_path_names(tree)
    out: list[tuple[str, int, str]] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            # 归属到**最内层**函数：`<module>` 只收自己直接挂着的调用
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            if isinstance(child, ast.Call):
                target = _write_target(child, repo_names)
                hit = target is not None and (
                    _is_repo_name(target, repo_names) or any(m in ast.unparse(target) for m in _REPO_MARKERS)
                )
                if hit:
                    out.append((scope, child.lineno, " ".join(ast.unparse(child).split())))
            visit(child, inner)

    # `ast.unparse` 会重排字符串常量 ⇒ 对含 `\s` / `\.` 的源文件报 `invalid escape sequence`（噪音，不是缺陷）
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        visit(tree, "<module>")
    return out


CI_HELPER_TESTS_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"


@lru_cache(maxsize=1)
def _live_repo_writes_cached() -> tuple[tuple[tuple[str, str], tuple[str, ...]], ...]:
    live: dict[tuple[str, str], list[str]] = {}
    for path in sorted(CI_HELPER_TESTS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        # 成本闸：两种记号**都**没出现的文件不解析（481 个文件全 `ast.parse` ≈ 1s，
        # 而本 job 是 PR 反馈的关键路径 ⇒ 粗筛省掉绝大部分解析）
        if not any(k in text for k in _WRITE_ATTRS | _MUTATING_ATTRS | _WRITE_FUNCS):
            continue
        if not any(m in text for m in _REPO_MARKERS):
            continue
        for fn, lineno, expr in repo_tree_writes(text):
            live.setdefault((path.name, fn), []).append(f"{path.name}:{lineno} {expr}")
    return tuple((key, tuple(spots)) for key, spots in sorted(live.items()))


def _live_repo_writes() -> dict[tuple[str, str], list[str]]:
    """现取：`tests/unit_ci_workflows/*.py` 里所有「写仓内路径」的 `(文件, 函数)` → 写点清单。"""
    return {key: list(spots) for key, spots in _live_repo_writes_cached()}


def test_no_guard_mutates_the_repo_tree_in_place() -> None:
    """**类级**：套件里不许有「写回仓库工作树」的判据 —— **未登记即红**。"""
    live = _live_repo_writes()
    offenders = sorted(spot for key, spots in live.items() if key not in REPO_WRITE_ALLOWLIST for spot in spots)
    assert offenders == [], (
        "判据把变异注入写回了仓库工作树（issue #8415 的根因）：`ci workflow helper unit tests` 用 `-n 4` 并行，"
        "一次临时写回会让**同期**读同一文件的判据读到变异体（实测 39/40 红，且连累另一条判据）。"
        "出口：变异只进**文本参数**（不落盘）；确需写盘 ⇒ 写 `tmp_path`；"
        "确属运行期不执行的入口 ⇒ 登记 `REPO_WRITE_ALLOWLIST` 并写明为什么不在共享写面里。\n  - "
        + "\n  - ".join(offenders)
    )


def test_repo_tree_write_allowlist_only_shrinks() -> None:
    """**只许缩短**：登记了却已不再命中真实写点的条目必须删掉（否则它会给新增写点一起背书）。"""
    live = _live_repo_writes()
    stale = sorted(f"{f}::{n}" for (f, n) in set(REPO_WRITE_ALLOWLIST) - set(live))
    assert stale == [], (
        "台账条目的写点已经不存在了 ⇒ 删掉它（台账只许缩短）。"
        "否则下一个人把同一处写回来时，这条旧账会替它放行。\n  - " + "\n  - ".join(stale)
    )


def test_repo_tree_write_judge_has_discriminating_power() -> None:
    """判别力自证：真缺陷形态（写回仓内路径）必红、**合法**形态（写 `tmp_path`）不红。"""
    defect = (
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parents[2]\n"
        "WF = REPO_ROOT / '.github' / 'workflows' / 'x.yml'\n"
        "def inject():\n"
        "    WF.write_text('broken', encoding='utf-8')\n"
    )
    assert repo_tree_writes(defect), "「写回仓内路径」的形态没被判红 ⇒ 本守卫是空断言"
    # 更隐蔽的一档：不经模块级名字，直接把表达式当接收者（本包原实现接近这一档）
    inline = (
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parents[2]\n"
        "def inject():\n"
        "    (REPO_ROOT / 'a.yml').write_text('x', encoding='utf-8')\n"
    )
    assert repo_tree_writes(inline), "行内仓内路径写法没被判红"
    legal = (
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parents[2]\n"
        "WF = REPO_ROOT / 'a.yml'\n"
        "def fine(tmp_path):\n"
        "    (tmp_path / 'x.yml').write_text('broken', encoding='utf-8')\n"
        "    WF.read_text(encoding='utf-8')   # 读仓内路径不是共享写面\n"
    )
    assert repo_tree_writes(legal) == [], f"写 tmp / 读仓内路径被误判：{repo_tree_writes(legal)}"
