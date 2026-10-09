# case_ids: MC-074
"""`plaintext_credential_guard.py` 的 L0 判据（issue #6172）。

## 本文件判什么

`.github/plaintext_credential_guard.py` 是「凭据字面量留在代码里」的仓内守卫
（gitleaks 只扫**新增行** ⇒ 存量明文永不报警，本守卫按**现取**扫真源码）。这里给它两层判据：

1. **真语料**：当前仓（真源码）必须**零命中** —— 这是「修复真的落地了」的那一半
   （改前读数 = 命中 2 处，见 PR body 的「## 红证」）。
2. **注入式红证 + 判别力自证**：造出被判形态 ⇒ **当场红并具名**；造出**正确形态**
   （环境注入 / 参数化夹具 / 空串）⇒ **不红**（反向对照，防「判红逼人把代码改坏」）。
3. **R3 = 产物面的「裸 JWT」（issue #6303）**：`acceptance/**` / `tests/**` 的 `.json`/`.log`/`.md`
   里出现三段点分、**去固定头后仍够长**的 JWT ⇒ 红；**文档截断举例**（固定头 + `…`）⇒ **不红**
   （这条负例是本单最容易做错的地方：朴素形态判据会**误报真语料**）；另加**射程**与
   **`.gitignore` 层**两条判据（运行态会话存储不该在被跟踪集合里）。
   ⚠️ 本文件也是 R3 的扫描样本之一 ⇒ **被判形态一律拆开拼**（`"ey" + "J"`），绝不写连续固定头
   （`test_this_file_carries_no_literal_token` 正向核这一点 —— 否则本包会被**自己的守卫**喂红）。

## 有意不做（照实登记，§19.1）

- **不判**「随机字符串但名字不叫 token/secret」（会误伤哈希 / 订单号 / 迁移指纹 ——
  实测整仓扫描里那类噪声上千条）。
- **不判**「这个值是不是那枚 dev token」—— 本仓**不许**再出现该值，本判据也不写它的值；
  判的是**形态**（凭据名 + 字面量），不是**具体值**。
- 二进制 / 构建目录不在面内（守卫的 `SKIP_DIRS` 逐条具名）。
- **R3 的射程外**（如实登记）：`.mjs` 等**写盘装置**（`harness/*.mjs` 源码）与 `docs/**` ——
  本判据**不替** `.gitignore` 做兜底；`.session.json`/`.store.json` 之外的运行态名（如 `state.json`）
  只能靠「它在 `tests/**`/`acceptance/**` 且是 `.json`」那条覆盖。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = REPO_ROOT / ".github" / "plaintext_credential_guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("migao_plaintext_credential_guard", GUARD_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


guard = _load_guard()

#: 被判形态的**合成**取值（不是任何真凭据 —— 只为触发「够长/够像凭据」的形状）。
FAKE_HEX = "0" * 64
FAKE_RANDOM = "AbCdEf0123456789AbCdEf0123456789AbCdEf01"

# R3（issue #6303）的**合成**样本。⚠️ 固定头**拆开拼**：本文件自己在 R3 扫描面内
# （`tests/**` + `.md`）⇒ 写连续固定头会让 `test_real_repo_is_clean` **红在本文件上**。
_JWT_HEAD = "ey" + "JhbGciOiJSUzI1NiJ9"                     # 固定头（解出 = {"alg":"RS256"}）
_JWT_PAYLOAD = "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0"           # 声明段（合成）
_JWT_SIG = "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"    # 签名段（合成的高熵 43 字符）
FAKE_JWT = _JWT_HEAD + "." + _JWT_PAYLOAD + "." + _JWT_SIG
#: **文档截断举例**：固定头 + `…`（真语料 `acceptance/2026-10-04/env/method-notes.md` 的形态）
TRUNCATED_EXAMPLE = _JWT_HEAD + "\u2026"

_R3_RULES = ("R3",)
_ARTIFACT = "acceptance/2026-10-04/race-sweep/out/fixtures.json"


def _synthetic(rel: str, body: str, rules=("R1", "R2")) -> str:
    """在内存里对真·判定函数做注入（不落进本仓）。"""
    return guard._scan_line(rel, 1, body, rules)


# ── 判据 1：真语料零命中（修复落地的那一半） ─────────────────────────────

def test_real_repo_is_clean():
    """当前仓（真源码）零命中 —— 这一条在修复前**必须是红的**（命中 2 处）。"""
    findings, scanned = guard.scan(str(REPO_ROOT))
    assert scanned > 1000, f"扫描面太小（{scanned} 个文件）⇒ 判据等于空跑"
    assert findings == [], "命中：\n" + "\n".join(str(f) for f in findings)


def test_repo_has_no_service_token_value_left():
    """真语料零命中 + **扫描面没塌缩**（后者防「面变小 ⇒ 判据变成空跑」）。"""
    findings, scanned = guard.scan(str(REPO_ROOT))
    assert scanned > 1000, f"扫描面太小（{scanned} 个文件）⇒ 判据等于空跑"
    assert findings == [], "命中：\n" + "\n".join(str(f) for f in findings)


def test_guard_is_not_vacuous():
    """「恒绿」的守卫（永远返回空）必须**过不了**注入式用例 —— 这里正面自证判别力。"""
    assert guard._scan_line("x.py", 1, f'SERVICE_TOKEN = "{FAKE_HEX}"'), "守卫对注入形态无反应 ⇒ 空断言"


# ── 判据 2：注入式红证（会红，且具名） ───────────────────────────────────

@pytest.mark.parametrize("body,rule", [
    (f'SERVICE_TOKEN = "{FAKE_HEX}"', "R1-credential-literal"),
    (f'    service_token = "{FAKE_HEX}"', "R1-credential-literal"),
    (f'SECRET = "{FAKE_RANDOM}"', "R1-credential-literal"),
    (f'api_key: "{FAKE_HEX}"', "R1-credential-literal"),
    (f'password = "{FAKE_RANDOM}"', "R1-credential-literal"),
    (f'    "X-Service-Token": "{FAKE_HEX}",', "R2-service-token-header-literal"),
    (f"    'X-Service-Token': '{FAKE_RANDOM}',", "R2-service-token-header-literal"),
])
def test_forbidden_forms_are_flagged_by_name(body, rule):
    got = _synthetic("tests/whatever_test.py", body)
    assert [f.rule for f in got] == [rule], f"未判红 / 判错规则：{body!r} ⇒ {got}"


def test_rule_names_are_stable_and_distinct():
    """两条规则的**名字**是判据的公开面（PR body / 消费方按名字引用）⇒ 自证不变。"""
    assert guard._scan_line("x.py", 1, f'SERVICE_TOKEN = "{FAKE_HEX}"')[0].rule == "R1-credential-literal"
    assert guard._scan_line("x.py", 1, f'"X-Service-Token": "{FAKE_HEX}"')[0].rule == (
        "R2-service-token-header-literal")


# ── 判据 3：反向对照（正确形态**不许**红） ───────────────────────────────

@pytest.mark.parametrize("body", [
    # issue #6170 的形态（环境注入）
    'SERVICE_TOKEN = os.environ.get("MIGAO_SERVICE_TOKEN", "")',
    'SERVICE_TOKEN = os.environ["SERVICE_TOKEN"]',
    'service_token = os.getenv("SERVICE_TOKEN", "")',
    'self.service_token = settings.SERVICE_TOKEN',
    # 空串 = 无凭据（#6170 的「字面量留空」）
    '    "X-Service-Token": "",',
    # 参数化夹具 / 调用方注入（本仓 17 处，全部是**正确**形态）
    '    headers = {} if token is None else {"X-Service-Token": token}',
    'ADMIN_HEADERS = {"X-Service-Token": SERVICE_TOKEN, "X-Tenant-Id": "1"}',
    '    return {"X-Service-Token": config.service_token}',
    # 短占位串（测试桩，不是凭据）
    'SERVICE_TOKEN = "test-service-token"',
    'serviceToken = "svc-token-1"',
    'SECRET = ""',
    # 名字里有 token 但**不是凭据**（字段名 / 计数）
    'token_count = 3',
    '    accessTokenExpiration = 7200L',
])
def test_correct_forms_are_not_flagged(body):
    assert _synthetic("tests/whatever_test.py", body) == [], f"假红（正确形态被判）：{body!r}"


@pytest.mark.parametrize("body", [
    "# SERVICE_TOKEN = \"" + FAKE_HEX + "\"",
    "// \"X-Service-Token\": \"" + FAKE_HEX + "\",",
])
def test_comment_lines_are_not_flagged(body):
    """注释里**引用/讲解**被判形态不算违规（否则「越讲清楚越红」）。"""
    assert _synthetic("tests/whatever_test.py", body) == []


def test_pragma_is_the_only_exemption_channel():
    body = f'FAKE = "{FAKE_HEX}"  # noqa: plaintext-credential :: 名字恰好是 FAKE，不是凭据'
    assert _synthetic("x.py", body) == []
    # pragma 只豁免**它所在的那一行**
    other = _synthetic("x.py", f'SERVICE_TOKEN = "{FAKE_HEX}"')
    assert other, "pragma 把别的行一起豁免了 ⇒ 通道过宽"


def test_hash_inside_a_string_is_not_treated_as_a_comment():
    """**引号感知**（issue #5325 的同族形态）：字符串里的 `#` 不是注释 ⇒ 不许吃掉行尾。

    朴素截断（`split("#")`）会把 `"<hex>#tail"` 这行截成半截 ⇒ **漏判**。
    """
    body = f'SERVICE_TOKEN = "{FAKE_HEX}#not-a-comment"'
    assert [f.rule for f in _synthetic("x.py", body)] == ["R1-credential-literal"]
    # 行尾真注释仍要被剥掉（否则 `# 说明：SERVICE_TOKEN = "…"` 会假红）
    assert _synthetic("x.py", f'X = 1  # SERVICE_TOKEN = "{FAKE_HEX}"') == []
    # 行内注释跟在取值后面（本仓 `deploy/swas/*.sh` 就是这个形态）⇒ 认得出「值 + 注释」
    assert [f.rule for f in _synthetic("deploy/x.sh", f'SERVICE_TOKEN="{FAKE_HEX}"  # 注释')] == [
        "R1-credential-literal"]


def test_pragma_must_carry_a_reason():
    """pragma 是**描述性**的（原因写在注释里）；判据只做一条最小形态检查：pragma 与原因同行。"""
    no_reason = f'FAKE = "{FAKE_HEX}"  # noqa: plaintext-credential'
    assert _synthetic("x.py", no_reason) == []  # 形态上仍豁免
    guard_src = GUARD_PATH.read_text(encoding="utf-8")
    assert "noqa: plaintext-credential :: " in guard_src, "守卫必须示范「pragma 要带原因」的写法"


# ── 判据 4：三态 / 出口（可行动） ────────────────────────────────────────

def test_exit_code_3_when_scan_face_is_empty(tmp_path):
    """扫不到任何文件 ⇒ `3` 无法判定（**不得当 0 读**）—— 与「零命中」区分开。"""
    assert guard.scan(str(tmp_path))[1] == 0
    assert guard.main(["--root", str(tmp_path)]) == 3


def test_cli_reports_violations_with_actionable_exit(tmp_path):
    """真 CLI 上注入一整棵合成仓 ⇒ 非零 + 具名 + 给出「该改用什么」。"""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "leak_test.py").write_text(
        f'# case_ids: X-001\nSERVICE_TOKEN = "{FAKE_HEX}"\n', encoding="utf-8")
    (tmp_path / "tests" / "ok_test.py").write_text(
        'import os\nSERVICE_TOKEN = os.environ.get("MIGAO_SERVICE_TOKEN", "")\n', encoding="utf-8")
    rc = guard.main(["--root", str(tmp_path)])
    assert rc == 1, "命中却没判红"
    out = subprocess.run(
        [sys.executable, str(GUARD_PATH), "--root", str(tmp_path), "--json"],
        capture_output=True, text=True,
    )
    assert out.returncode == 1, out.stderr
    payload = json.loads(out.stdout)
    assert payload["status"] == "violations"
    assert [f["path"] for f in payload["findings"]] == [str(Path("tests") / "leak_test.py")]
    assert payload["findings"][0]["rule"] == "R1-credential-literal"
    assert payload["findings"][0]["line"] == 2, "报的行号必须与被判对象一致（可行动）"


def test_cli_clean_exit_zero(tmp_path):
    (tmp_path / "a.py").write_text(
        'X = {"X-Service-Token": ""}\n', encoding="utf-8")
    assert guard.main(["--root", str(tmp_path)]) == 0


# ── 判据 5：判别力自证（守卫本身不许退化成恒绿） ─────────────────────────
def test_guard_is_not_vacuous():
    """「恒绿」的守卫（永远返回空）必须**过不了**上面那些注入用例 —— 这里正面自证。"""
    assert guard._scan_line("x.py", 1, f'SERVICE_TOKEN = "{FAKE_HEX}"'), "守卫对注入形态无反应 ⇒ 空断言"
    assert guard.scan(str(REPO_ROOT))[1] > 1000, "扫描面塌缩 ⇒ 判据变成空跑"


# ── 判据 6：R3 = 产物面的「裸 JWT」（issue #6303） ────────────────────────
#
# 病根（现取实测）：R1 是「**凭据命名的键** = 字面量」⇒ 产物里三种真实形态**全部漏判** ——
# 判据文件用 R3 规则直接喂 `_scan_line`，证明这三种形态**能被抓住**；再证明**截断举例不被误报**。

def test_rule_names_are_stable_and_distinct_r3():
    """R3 的**名字**是判据的公开面（PR body / 消费方按名字引用）⇒ 自证不变。"""
    got = _synthetic(_ARTIFACT, '  "tokenA": "%s",' % FAKE_JWT, _R3_RULES)
    assert [f.rule for f in got] == ["R3-artifact-token-literal"], got


@pytest.mark.parametrize("line", [
    f'  "tokenA": "{FAKE_JWT}",',          # 键名不叫凭据名（R1 的射程外 —— 本单的病灶）
    f'  "accessToken": "{FAKE_JWT}",',     # 同上
    f'  "service_token": "{FAKE_JWT}",',   # 键名匹配 R1，但**闭引号**让 R1 的边界吃不下
    f"  Authorization: Bearer {FAKE_JWT}",  # 头形态
    f'{{"a": {{"b": ["{FAKE_JWT}"]}}}}',   # 深层数组里的裸串
])
def test_bare_jwt_in_artifacts_is_flagged(line):
    """产物面的**裸** JWT ⇒ 必红（且规则名稳定）。"""
    got = _synthetic(_ARTIFACT, line, _R3_RULES)
    assert [f.rule for f in got] == ["R3-artifact-token-literal"], f"未判红：{line!r}"


@pytest.mark.parametrize("line", [
    # ① 真语料 `acceptance/2026-10-04/env/method-notes.md` 的**逐字形态**（固定头 + `…`）
    "- 内含**真实 JWT**（`" + TRUNCATED_EXAMPLE + "`）——这是 harness 登录后直接落盘会话凭据。",
    # ② ASCII 省略号 / 明确占位（人类写的说明里更常见的两种）
    f"例：`{_JWT_HEAD}...`",
    f"`{_JWT_HEAD}<REDACTED-JWT>`",
    # ③ 三段但**去固定头后不够长**（占位串，不是凭据）
    f'  "tokenA": "{_JWT_HEAD}.aaaa.bbbb",',
    # ④ 只有两段（截断）
    f'  "tokenA": "{_JWT_HEAD}.{_JWT_SIG}",',
    # ⑤ 裸的固定头（连点都没有）
    f'  "jwtHeader": "{_JWT_HEAD}",',
])
def test_truncated_or_short_forms_are_not_flagged(line):
    """**防误报**（本单最容易做错的地方）：截断举例 / 说明面形态 ⇒ **不许红**。

    判据口径 = 「**除固定头之外没有足够熵**」（长度门 `_R3_MIN_BODY`）⇒ 不成立，
    **不是**「出现固定头即红」—— 后者会在真语料上误报（实测那行就在 `method-notes.md`）。
    """
    assert _synthetic(_ARTIFACT, line, _R3_RULES) == [], f"假红（截断/说明形态被判）：{line!r}"


def test_r3_scope_is_the_artifact_face_only():
    """**射程**判据：产物面两个根 + 三种后缀才判；写盘装置（`.mjs`）/ `docs/**` / 产品代码**不判**。"""
    assert guard._r3_rules(_ARTIFACT, None) == ["R3-artifact-token-literal"]
    assert guard._r3_rules("tests/unit_ci_workflows/x.md", None) == ["R3-artifact-token-literal"]
    assert guard._r3_rules("acceptance/2026-10-04/harness/run.log", None) == ["R3-artifact-token-literal"]
    # 射程外（**有意**不做兜底，登记在模块 docstring 的「有意不做」）
    assert guard._r3_rules("acceptance/2026-10-04/harness/lib.mjs", None) == []
    assert guard._r3_rules("docs/testing/x.md", None) == []
    assert guard._r3_rules("backend/ai-agent-service/tests/x.json", None) == []


def test_session_store_rule_fires_only_when_not_ignored():
    """会话存储的**可见**名（`.session.json` / `.store.json`）：**被跟踪 + 没被忽略 ⇒ 红**。

    三条读数各有分工，缺一条都会让「出口不可行动」或「读数被臆造」：
    ① `is_ignored=False`（真仓、**仍被跟踪**）⇒ 红 —— 这正是本单病灶（名字没被 `.gitignore` 覆盖）；
    ② `is_ignored=True`（已进 `.gitignore`）⇒ **整条规则对该文件退出**（否则「加了规则仍判红」=
       给出一个不可行动的出口）；
    ③ `is_ignored=None`（非 git 面 / git 不可用）⇒ 不臆造「本该被忽略」的读数；该名下的 `.json`
       **仍按产物面后缀判**（`acceptance/**/out/x.json` 是真的产物，不能因「不在 git 里」就放过）。
    """
    rel = "acceptance/2026-10-04/worker-miniapp-sweep/out/.session.json"
    assert guard._r3_rules(rel, lambda r: False) == ["R3-artifact-token-literal"]
    assert guard._r3_rules(rel, lambda r: True) == [], "已进 .gitignore 仍被判红 ⇒ 出口不可行动"
    assert guard._r3_rules(rel, None) == ["R3-artifact-token-literal"]
    # 同名文件**不在**产物面两个根下 ⇒ 不判（射程判据，与 ② 无关）
    assert guard._r3_rules("backend/x/.session.json", lambda r: False) == [
        "R3-artifact-token-literal"], "会话存储名在任何路径上都判（它本该被 .gitignore 排除）"
    assert guard._r3_rules("acceptance/x/out/fixtures.json", lambda r: False) == [
        "R3-artifact-token-literal"]


def test_gitignore_layer_excludes_runtime_session_state():
    """**.gitignore 层**（issue #6303 建议①的后半）：运行态会话存储必须**踢出被跟踪集合**。

    两层各判一次（缺一不可）：① 现取 `git check-ignore` ⇒ 名字被规则覆盖；
    ② 现取 `git ls-files` ⇒ **不再**在被跟踪集合里（只加 `.gitignore` 而不 `git rm --cached`
    是**无效**的：gitignore 管不了已入库的文件 —— 那正是本单的病）。

    ⚠️ 边界：这里只钉**当前**这两个名字 + 零条数的**现状**；`--root` 不在 git 里 ⇒ skip（不臆造）。
    """
    probe = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           cwd=str(REPO_ROOT), capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("不在 git 工作区 ⇒ 无法现取被跟踪集合（不臆造读数）")
    for rel in ("acceptance/2026-10-04/worker-miniapp-sweep/out/.session.json",
                "acceptance/2026-10-03/worker-miniapp-writeface-sweep/out/.store.json"):
        ig = subprocess.run(["git", "check-ignore", "-q", "--", rel],
                            cwd=str(REPO_ROOT), capture_output=True)
        assert ig.returncode == 0, f"{rel} 未被 .gitignore 覆盖（check-ignore 现取 rc={ig.returncode}）"
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=str(REPO_ROOT),
                             capture_output=True, text=True).stdout.split("\0")
    left = [p for p in tracked if p.endswith((".session.json", ".store.json"))]
    assert left == [], f"运行态会话存储仍在被跟踪集合里（应 `git rm --cached`）：{left}"


def test_this_file_carries_no_literal_token():
    """**自洽判据**：本文件（`.md` 也在 R3 扫描面内）不得出现连续固定头。

    它不是形式主义：`test_real_repo_is_clean` 扫的就是**本文件** —— 一旦把被判形态写成
    连续字面量，那一轮会**红在本包自己身上**。这条把「拆开拼」从口头纪律变成机械读数。
    """
    src = Path(__file__).read_text(encoding="utf-8")
    assert ("ey" + "J") not in src, "本文件含连续固定头 ⇒ 会被自己的 R3 判红（改成拆开拼）"
    assert src.count('"ey" + "J') >= 1, "拆开拼的写法一次都没有 ⇒ 本判据等于空跑（扫描面/写法变了？）"

