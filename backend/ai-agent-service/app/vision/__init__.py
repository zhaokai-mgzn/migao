"""图片识别内核（issue #5321 包 1）—— **一个内核，两个入口**。

```
        ┌──────────────────────────────┐
        │  识别内核（服务端）            │
        │  图 → 结构化字段 + 逐字段来源   │
        └───────┬──────────────┬───────┘
                │              │
     页面入口（快通道）     Agent 入口（深通道，属包 2）
     建品/建单页按钮        米宝浮动面板
```

- 页面入口：`app/api/internal.py` 的 `POST /api/internal/vision/recognize`
  （Service Token，由 admin-api 的 `AgentVisionController` 反调）。
- **两入口共用本内核** ⇒ 保证「同一张图，两个入口给同一组字段」。
- 🔴 **不落库**：本包只产出「填哪几格」，**提交永远是人的动作**。
"""

from app.vision.pipeline import (
    image_url_hint,
    normalize_image_urls,
    rewrite_image_url,
    validate_image_url,
)
from app.vision.recognizer import (
    FIELD_MARKER,
    build_messages,
    extract_fields,
    recognize,
)
from app.vision.targets import TARGET_FIELDS, TARGET_POLICY, TargetField

__all__ = [
    "FIELD_MARKER",
    "TARGET_FIELDS",
    "TARGET_POLICY",
    "TargetField",
    "build_messages",
    "extract_fields",
    "image_url_hint",
    "normalize_image_urls",
    "recognize",
    "rewrite_image_url",
    "validate_image_url",
]