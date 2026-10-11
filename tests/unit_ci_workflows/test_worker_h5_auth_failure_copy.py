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
   检查器必须各自判红；未注入的真实文件必须判绿（正反对照，杜绝"不会红的空断言"）。

**已知边界（照实登记）**：本守卫判的是**源文本形态**，不是"那段代码跑起来会输出什么"——
后者由实例判据 `frontend/worker-h5/tests/worker-h5-6747-auth-failed-copy.test.mjs`（真跑到
`createApi().login()` 的 401 路径）在 `worker-h5 unit tests (node --test)` 腿上承担；
两侧互指、不互为副本（本守卫**不执行** node）。
"""
from __future__ import annotations

import re
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


def copy_defects(api_text: str, auth_failed_message: str) -> list[str]:
    """把「登录失败文案」这一类的坏形态判红（纯函数，便于注入式自证）。

    :param api_text: `frontend/worker-h5/src/api.mjs` 的源文本（真实文件或注入后的副本）
    :param auth_failed_message: 生产 `AUTH_FAILED` 响应体里的 `message`（逐字）
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
    wf = WORKFLOW.read_text(encoding="utf-8")
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
    """形态：CI 的 glob 不再覆盖实例判据 ⇒ 必红（判据接不上去 = 死文件）。"""
    wf = WORKFLOW.read_text(encoding="utf-8")
    broken = wf.replace(
        "node --test frontend/worker-h5/tests/*.test.mjs",
        "node --test frontend/worker-h5/tests/worker-h5-api.test.mjs",
    )
    assert broken != wf, "变异注入没生效"
    # 直接对检查器判：把 workflow 文本替换掉（本用例只自证检查器的这一条）
    orig = WORKFLOW.read_text(encoding="utf-8")
    try:
        WORKFLOW.write_text(broken, encoding="utf-8")
        problems = copy_defects(_api_text(), _production_auth_failed_message())
    finally:
        WORKFLOW.write_text(orig, encoding="utf-8")
    assert any("node --test" in p for p in problems), f"接线断掉没被判红：{problems}"


# ── 对照读数：未注入 ⇒ 不红（防"什么都判红"） ────────────────────────────────────

def test_unmutated_source_is_green_control() -> None:
    api_text = _api_text()
    assert GENERIC_RETRY in api_text, "前置：泛化话术仍应存在于**非认证**的传输层兜底档（本单只把它从认证面挪开）"
    assert copy_defects(api_text, _production_auth_failed_message()) == []
