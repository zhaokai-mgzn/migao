# case_ids: MC-074
"""`plaintext_credential_guard.py` 的 L0 判据（issue #6172）。

## 本文件判什么

`.github/plaintext_credential_guard.py` 是「凭据字面量留在代码里」的仓内守卫
（gitleaks 只扫**新增行** ⇒ 存量明文永不报警，本守卫按**现取**扫真源码）。这里给它两层判据：

1. **真语料**：当前仓（真源码）必须**零命中** —— 这是「修复真的落地了」的那一半
   （改前读数 = 命中 2 处，见 PR body 的「## 红证」）。
2. **注入式红证 + 判别力自证**：造出被判形态 ⇒ **当场红并具名**；造出**正确形态**
   （环境注入 / 参数化夹具 / 空串）⇒ **不红**（反向对照，防「判红逼人把代码改坏」）。

## 有意不做（照实登记，§19.1）

- **不判**「随机字符串但名字不叫 token/secret」（会误伤哈希 / 订单号 / 迁移指纹 ——
  实测整仓扫描里那类噪声上千条）。
- **不判**「这个值是不是那枚 dev token」—— 本仓**不许**再出现该值，本判据也不写它的值；
  判的是**形态**（凭据名 + 字面量），不是**具体值**。
- 二进制 / 构建目录不在面内（守卫的 `SKIP_DIRS` 逐条具名）。
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


def _synthetic(rel: str, body: str) -> str:
    """在内存里对真·判定函数做注入（不落进本仓）。"""
    return guard._scan_line(rel, 1, body)


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
