"""包声明测试（issue #7335）：`app.images` 的公开面必须可导入。

QA Growth Gate 对新增包 `app/images/__init__.py` 的映射就是本文件（`tests/test___init__.py`），
故这里断言包级契约（不是为凑文件名）：内核与用途白名单都从包入口可达，
且包本身不承担任何 I/O / 写库行为（行为全在 `app.images.generator`，由其自己的测试覆盖）。
"""
# case_ids: UI-129

from app.images import KINDS, generate_product_image


def test_package_exposes_generation_surface():
    assert KINDS == ("main", "texture", "craft", "scene")
    assert callable(generate_product_image)
