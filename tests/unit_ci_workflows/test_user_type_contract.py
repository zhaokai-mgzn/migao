"""前端 `User` 类型 ↔ 后端 `LoginResponse.UserInfo` 契约守卫（L0：零 LLM、纯静态、秒级）

## 为什么需要这一层

C/B 两端小程序的 `User` 类型声明的是 **`auth_user` storage 里的形状**，而那个形状的唯一
生产者是 admin-api 的 `POST /api/auth/mini/login` · `POST /api/auth/bmini/login`
（`super_login`），前端 `miniAppLogin` 把响应的 `data.data.user` **原样** `JSON.stringify`
存进 storage（`frontend/mini-app/src/utils/auth.ts`）。后端全库 camelCase（`LoginResponse.
UserInfo`：`id/nickname/avatar/role/identityType/roles/tenantId/tenantName/botName`）。

历史缺陷（本守卫的起因）：`User.tenant_id` 声明为**必填 `number`**，但后端从来没有
`tenant_id` 这个字段 —— 它是 `tenantId`。⇒ `user.tenant_id` 运行时恒为 `undefined`，
而 TypeScript 认为它必然存在：**类型在骗人**，未来任何读者都踩空。更糟的是 e2e 注入
`auth_user` 时做"归一化"补了 `tenant_id` ⇒ **harness 存进去的形状与生产不同**，
真有人读 `user.tenant_id` 时 e2e 绿而生产挂 —— 标准的「证据层假绿」。

## 判据（故意不读任何"期望清单"，只读两侧源文件的事实）

`{User 里所有必填字段}` ⊆ `{LoginResponse.UserInfo 的 JSON 字段名}`。
必填 = 类型写死「一定有」⇒ 后端必须真的有；后端多出来的字段不受约束。

fail-closed：文件缺失 / 接口或内部类找不到 / 解析出空集合 —— 一律 `pytest.fail`，
绝不允许「解析失败」退化成「0 处不一致」放行。

层归属：`migao-dev-flow` §16.1 的 **L0**（契约断裂必须在提交时拦住，不靠真实 LLM 去撞）。
"""
# case_ids: UI-016, API-010, BM-001, BM-005

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# 后端登录响应的单一事实源（UserInfo 内部类 = storage 里 user 的形状）
LOGIN_RESPONSE_JAVA = (REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"
                       / "com" / "migao" / "admin" / "dto" / "LoginResponse.java")

# 消费端（两端各自一份同名类型；B 端为 mini-app 的对称复制）
USER_TYPE_FILES = {
    "C 端 mini-app": REPO_ROOT / "frontend" / "mini-app" / "src" / "types" / "index.ts",
    "B 端 bmini-app": REPO_ROOT / "frontend" / "bmini-app" / "src" / "types" / "index.ts",
}


# ── 后端：LoginResponse.UserInfo 的 JSON 字段名 ──

_FIELD_RE = re.compile(r"private\s+[\w.<>\[\],\s]+?\s+(\w+)\s*;")
_JSON_PROPERTY_RE = re.compile(r'@JsonProperty\s*\(\s*"([^"]+)"\s*\)')


def _class_body(text, class_decl):
    """返回 `class_decl`（正则）所指类的花括号内文本；找不到 → pytest.fail（fail-closed）。"""
    m = re.search(class_decl, text)
    if m is None:
        pytest.fail(f"未能在后端 DTO 中定位类声明 {class_decl!r} —— 契约守卫失去依据"
                    f"（文件格式变了就必须改守卫，禁止静默放行）：{LOGIN_RESPONSE_JAVA}")
    start = text.index("{", m.end())
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    pytest.fail(f"类声明 {class_decl!r} 的花括号不闭合（解析失败即失败，不静默放行）")


def backend_user_info_fields(java_text=None):
    """`LoginResponse.UserInfo` 的 JSON 字段名集合。"""
    if java_text is None:
        if not LOGIN_RESPONSE_JAVA.exists():
            pytest.fail(f"后端契约源文件不存在：{LOGIN_RESPONSE_JAVA}")
        java_text = LOGIN_RESPONSE_JAVA.read_text(encoding="utf-8")

    body = _class_body(java_text, r"public\s+static\s+class\s+UserInfo\b")
    fields = set()
    for line in body.split("\n"):
        # 字段上的注解（@JsonProperty("x") 会改 JSON 名）——按声明块逐行取
        prop = _JSON_PROPERTY_RE.search(line)
        m = _FIELD_RE.search(line)
        if m:
            fields.add(prop.group(1) if prop else m.group(1))

    if not fields:
        pytest.fail("未能从 LoginResponse.UserInfo 解析出任何字段 —— 解析器失效（fail-closed）")
    return fields


# ── 前端：TS `User` 接口的必填字段名 ──

_TS_MEMBER_RE = re.compile(r"^\s*(?:readonly\s+)?([A-Za-z_$][\w$]*)\s*(\??)\s*:")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def frontend_user_required_fields(ts_text=None, path=None):
    """TS `User` 接口里**必填**（无 `?`）字段名集合。"""
    if ts_text is None:
        if path is None or not path.exists():
            pytest.fail(f"前端类型源文件不存在：{path}")
        ts_text = path.read_text(encoding="utf-8")

    body = _class_body(_BLOCK_COMMENT_RE.sub("", ts_text),
                       r"export\s+interface\s+User\b")
    body = _LINE_COMMENT_RE.sub("", body)

    required = set()
    for line in body.split("\n"):
        m = _TS_MEMBER_RE.match(line)
        if m and m.group(2) != "?":
            required.add(m.group(1))

    if not required:
        pytest.fail(f"未能从 {path} 的 `User` 接口解析出任何必填字段 —— 解析器失效（fail-closed）")
    return required


def contract_violations(required, backend_fields):
    """必填但后端不存在的字段（排序稳定，便于断言与阅读）。"""
    return sorted(required - backend_fields)


# ── 判据自身的红证：注入一条后端没有的必填字段 → 必须被报出 ──

def test_checker_red_proof_injected_phantom_field():
    """注入式红证：判据不可能"永远绿"（否则本守卫是空断言）。"""
    backend = {"id", "nickname", "avatar", "tenantId"}
    assert contract_violations({"id", "nickname", "avatar", "tenantId"}, backend) == []
    assert contract_violations({"id", "nickname", "avatar", "must_not_exist"}, backend) == \
        ["must_not_exist"], "判据对「后端没有的必填字段」无反应 —— 守卫失效"


@pytest.mark.parametrize("label", sorted(USER_TYPE_FILES))
def test_required_user_fields_exist_in_backend_login_response(label):
    """前端 User 的所有必填字段，后端 LoginResponse.UserInfo 必须真的提供。"""
    path = USER_TYPE_FILES[label]
    if not path.exists():
        pytest.fail(f"{label} 类型源文件不存在：{path}")

    backend = backend_user_info_fields()
    required = frontend_user_required_fields(path=path)
    missing = contract_violations(required, backend)

    assert not missing, (
        f"{label} 的 `User` 把 {missing} 声明为**必填**，但后端 LoginResponse.UserInfo "
        f"只有 {sorted(backend)} —— 这些字段运行时恒为 undefined，而 TypeScript 认为它们必然存在。\n"
        f"  存储里 user 的形状 = 后端登录响应 data.user 的 JSON **原样**（camelCase），"
        f"禁止 snake_case 别名或前端重命名；若确实要新字段，先让后端响应提供它。"
    )
