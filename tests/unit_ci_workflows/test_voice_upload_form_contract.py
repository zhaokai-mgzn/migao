# case_ids: UI-007, API-012
"""语音上传 `formData` 键集 ⊆ 转写端点签名键集（issue #3735）。

## 病根（已核验）

两端 `voice.ts` 的 `transcribeFile()` 上传音频时把 `tenant_id` 写进 `formData`，
而 `backend/ai-agent-service/app/api/asr.py` 的 `transcribe_audio()` 签名只有
`audio`（`File(...)`）+ `language`（`current_user: Depends(get_current_user)` ⇒ **租户从 JWT 取**）
⇒ `tenant_id` 是**无效载荷**：后端根本不读它，却会让后来读代码的人以为「上传要带租户」。

复算（只读，走 `origin/main` 的 git 对象）：

    git grep -n "tenant_id" origin/main -- frontend/mini-app/src/utils/voice.ts frontend/bmini-app/src/utils/voice.ts

## 判据（对象是**真源文件**，不是副本；键集关系是**集合包含**，不是存在性）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | 两端 `formData` 的**键集 ⊆** 端点签名里**客户端可传**的字段集 | 往任一端 `formData` 加回 `tenant_id`（或任何未在签名里的键）⇒ 必红（实测读数见下方「实跑红证」） |
| C2 | 解析**非空且钉死**：端点签名 == `{audio, language}`、每端 `formData` 键集含 `language` | 后端**新增/改名**客户端字段、`formData` 被清空或改名 ⇒ 必红（防「解析失效 ⇒ 恒真」空断言） |
| C3 | 两端 `voice.ts` 与 `asr.py` 都在（路径漂移 ⇒ 红，**不是**静默跳过） | 删/移动任一文件 ⇒ 必红 |

**为什么用 `ast` 解析后端**：不执行 `asr.py`（它 import dashscope / fastapi，判据不该唤起网络与三方依赖），
只读签名；`Depends(...)` 的参数不是客户端字段（剔除），`File(...)` 绑定的参数名就是 multipart 字段名。

**实跑红证（本判据合并前实测，非构造）**：改前（两端 `formData` 仍带 `tenant_id`）跑本文件
`test_form_data_keys_subset_of_signature` ⇒ **FAILED**，报 `extra=['tenant_id']`；
删掉该键后同一条 ⇒ passed。C2/C3 与注入式红证（`TestInjectedRedProofs`）同 PR 一起跑。

## 未固化（照实登记）

- `name: 'audio'`（multipart **文件字段名**）与签名里 `File(...)` 那一个参数的一致性**未纳入本判据**
  （本判据只覆盖 `formData` 的文本字段键集）。
- **射程现取 = `VOICE_TS` 两项**（两个 Taro 客户端的 `formData` 字面量）。`admin-web` 走的是另一形态
  （`frontend/admin-web/src/lib/api.ts` 的 `transcribeAudio()` 用 `FormData.append('audio', …)` +
  `?language=` 查询参数，**本判据不解析该形态**）⇒ 它已合规但**不受本判据守护**；新增调用方须同 PR
  登记进来（无机械锁会拦住漏登记）。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 两端语音工具（`transcribeFile()` 的 `formData` 唯一真相源）
VOICE_TS: tuple[str, ...] = (
    "frontend/mini-app/src/utils/voice.ts",
    "frontend/bmini-app/src/utils/voice.ts",
)

#: 转写端点（客户端可传字段的真相源）
ASR_PY = "backend/ai-agent-service/app/api/asr.py"

#: 端点函数名（改名 ⇒ C3/C2 红，不是静默跳过）
ASR_FUNC = "transcribe_audio"

#: 端点签名里**客户端可传**的字段集（钉死：后端字段面变化 = 有意的红，须同 PR 更新此处）
SIGNATURE_KEYS = frozenset({"audio", "language"})

#: `formData: { ... }` 字面量
_FORM_DATA_RE = re.compile(r"formData\s*:\s*\{(?P<body>.*?)\}", re.S)
#: 对象字面量的顶层键（一行一键，本仓两端同形）
_TS_KEY_RE = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*:", re.MULTILINE)


def _read(rel: str) -> str:
    """读取仓内文件（缺失 ⇒ 抛错 = 红：路径漂移不许是静默跳过）。"""
    path = REPO_ROOT / rel
    assert path.is_file(), f"{rel}: 文件不存在（路径漂移 ⇒ 本判据 fail-closed，不是通过）"
    return path.read_text(encoding="utf-8")


def _callee_name(call: ast.Call) -> str:
    """调用的最末段名字（`Depends` / `fastapi.Depends` 都取 `Depends`）。"""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def signature_fields(source: str, where: str = ASR_PY) -> set[str]:
    """`transcribe_audio` 签名里**客户端可传**的字段名（剔除 `Depends(...)` 依赖参数）。"""
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == ASR_FUNC
    ]
    assert matches, (
        f"{where}: 找不到 `async def {ASR_FUNC}`（改名/删函数）⇒ 本判据 fail-closed，不是通过"
    )
    fn = matches[0]
    args = fn.args.args
    defaults = list(fn.args.defaults)
    offset = len(args) - len(defaults)
    fields: set[str] = set()
    for index, arg in enumerate(args):
        default = defaults[index - offset] if index >= offset else None
        if isinstance(default, ast.Call) and _callee_name(default) == "Depends":
            continue  # JWT / 依赖注入参数：客户端传不了，也不算「要传的字段」
        fields.add(arg.arg)
    assert fields, f"{where}: 端点签名解析出 0 个字段 ⇒ fail-closed，不是通过"
    return fields


def form_data_keys(source: str, where: str) -> set[str]:
    """`voice.ts` 里 `formData: { ... }` 的键集（解析不到 / 空 ⇒ fail-closed 抛错）。"""
    match = _FORM_DATA_RE.search(source)
    assert match, f"{where}: 找不到 `formData: {{...}}` 字面量 ⇒ fail-closed，不是通过"
    keys = set(_TS_KEY_RE.findall(match.group("body")))
    assert keys, f"{where}: `formData` 解析出 0 个键 ⇒ fail-closed，不是通过"
    return keys


def subset_violations(voice_source: str, asr_source: str, where: str) -> list[str]:
    """C1 的判定内核（v 参数化以便注入式红证双向验证）：返回违规说明清单，空 = 通过。"""
    fields = signature_fields(asr_source)
    extra = sorted(form_data_keys(voice_source, where) - fields)
    if not extra:
        return []
    return [
        f"{where}: `formData` 键 {extra} 不在端点 `{ASR_FUNC}` 的客户端字段 {sorted(fields)} 里"
        f" —— 后端不读该键（租户来自 JWT），属无效载荷（issue #3735）"
    ]


@pytest.mark.parametrize("rel", VOICE_TS + (ASR_PY,))
def test_contract_sources_exist(rel: str) -> None:
    """C3：真源文件都在（路径漂移 ⇒ 红，不是静默跳过）。"""
    assert (REPO_ROOT / rel).is_file(), f"{rel}: 不存在 —— 判据对象漂移，须同 PR 修正射程"


def test_form_data_keys_subset_of_signature() -> None:
    """C1（承重）：两端 `formData` 键集 ⊆ 端点客户端字段集。"""
    asr_source = _read(ASR_PY)
    problems: list[str] = []
    for rel in VOICE_TS:
        problems.extend(subset_violations(_read(rel), asr_source, rel))
    assert not problems, "语音上传带了后端读不到的键：\n" + "\n".join(problems)


def test_signature_and_form_data_vocabulary_is_pinned() -> None:
    """C2：解析非空且钉死 —— 否则 C1 会退化成空断言（解析失效仍恒绿）。"""
    fields = signature_fields(_read(ASR_PY))
    assert fields == set(SIGNATURE_KEYS), (
        f"{ASR_PY}: `{ASR_FUNC}` 的客户端字段现取 = {sorted(fields)}，"
        f"与钉死的 {sorted(SIGNATURE_KEYS)} 不同 —— 后端字段面变了："
        f"请同 PR 更新 SIGNATURE_KEYS 与两端 `formData`，不要让 C1 悄悄失去判别力"
    )
    for rel in VOICE_TS:
        keys = form_data_keys(_read(rel), rel)
        assert "language" in keys, (
            f"{rel}: `formData` 现取键集 {sorted(keys)} 不含 `language` —— "
            f"键集被清空/改名后 C1 会恒真，故此处 fail-closed"
        )


class TestInjectedRedProofs:
    """注入式红证：把病灶 / 解析失效形态注入**内存副本**，判定内核必须相应变红（或变绿）。"""

    def test_tenant_id_injection_turns_red(self) -> None:
        """把 #3735 的病灶注回去 ⇒ C1 必红（`tenant_id` 不在签名里）。"""
        rel = VOICE_TS[0]
        source = _read(rel).replace(
            "formData: {",
            "formData: {\n      tenant_id: String(tenantId),",
            1,
        )
        violations = subset_violations(source, _read(ASR_PY), rel)
        assert violations, "注入 `tenant_id` 后判据仍绿 ⇒ C1 是空断言"
        assert "tenant_id" in violations[0], violations[0]

    def test_unknown_key_injection_turns_red(self) -> None:
        """任意未在签名里的键 ⇒ C1 必红（类级：不只盯 `tenant_id` 这一个名字）。"""
        rel = VOICE_TS[1]
        source = _read(rel).replace("formData: {", "formData: {\n      shop_id: '1',", 1)
        violations = subset_violations(source, _read(ASR_PY), rel)
        assert violations, "注入未登记键 `shop_id` 后判据仍绿 ⇒ C1 只做了形状匹配"

    def test_missing_form_data_block_fails_closed(self) -> None:
        """`formData` 字面量消失 ⇒ 解析 fail-closed（红），不是静默通过。"""
        rel = VOICE_TS[0]
        stripped = _FORM_DATA_RE.sub("body", _read(rel))
        with pytest.raises(AssertionError, match="找不到"):
            form_data_keys(stripped, rel)

    def test_renamed_endpoint_fails_closed(self) -> None:
        """端点函数改名 ⇒ 签名解析 fail-closed（红），不是返回空集后恒绿。"""
        renamed = _read(ASR_PY).replace(f"async def {ASR_FUNC}(", "async def transcribe_audio_v2(", 1)
        with pytest.raises(AssertionError, match=ASR_FUNC):
            signature_fields(renamed)

    def test_backend_side_widening_stays_green(self) -> None:
        """反方向：后端**新增**客户端字段（不动前端）时 C1 必须仍绿 —— 证明它不是「恒红」。

        用**内存构造**的合法前端做反向验证（不借现取树）⇒ 真实树处于何种状态都不影响本条的判别力。
        """
        widened = _read(ASR_PY).replace(
            "    language: Optional[str] = None,",
            "    language: Optional[str] = None,\n    hotwords: Optional[str] = None,",
            1,
        )
        assert "hotwords" in signature_fields(widened), "注入未生效（锚点已漂移）⇒ 本条红证无效"
        legal_client = "Taro.uploadFile({ url, filePath, name: 'audio', formData: { language: 'zh' } })"
        assert not subset_violations(legal_client, widened, "in-memory"), (
            "后端新增字段后 C1 变红 ⇒ 判据方向反了（要求的是 formData ⊆ 签名）"
        )