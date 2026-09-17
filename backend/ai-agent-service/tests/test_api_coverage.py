"""app/api/* 模块测试覆盖登记（tech-stack.yml「app/api/(.+).py」规则配套）

断言：每个业务 api 模块都有对应镜像测试（tests/test_<模块名>.py 或 tests/test_api_<模块名>.py），
防止新增端点无测试（issue #581 覆盖缺口族）。
"""
# case_ids: ST-011
import pathlib

API_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"
TESTS_DIR = pathlib.Path(__file__).resolve().parent

# 免测/聚合模块（无业务端点或由统一模块覆盖）
EXEMPT = {
    "__init__.py",
    "routes.py",          # 路由聚合（各模块路由已在各自镜像测试覆盖）
    "response_models.py", # 响应包装纯函数
    "sse.py",             # SSE 协议解析（由 test_api_chat_helpers 覆盖）
    "schemas.py",         # 数据 schema 纯定义
}


def test_every_api_module_has_mirror_test():
    missing = []
    for f in sorted(API_DIR.glob("*.py")):
        if f.name in EXEMPT:
            continue
        stem = f.stem
        candidates = [
            TESTS_DIR / f"test_{stem}.py",
            TESTS_DIR / f"test_api_{stem}.py",
        ]
        if not any(c.exists() for c in candidates):
            missing.append(f.name)
    assert not missing, (
        f"缺 api 模块镜像测试: {missing}（tech-stack.yml api 规则：每个业务端点模块都要有测试）"
    )
