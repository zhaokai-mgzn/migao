"""商品图生成（issue #7335）：样图 → 百炼图生图。

与 `app/vision/` 同族的「AI 辅助」能力，但**只生成图片、不写任何业务数据**：
调用方（admin-api）拿到 OSS 永久 URL 后，是否采用仍由商家在页面上点按钮决定。

公开面只有两个符号（包级契约见 `tests/test___init__.py`）：
`KINDS`（用途白名单）与 `generate_product_image`（生成内核，行为由 `tests/test_generator.py` 覆盖）。
"""

from app.images.generator import KINDS, generate_product_image

__all__ = ["KINDS", "generate_product_image"]
