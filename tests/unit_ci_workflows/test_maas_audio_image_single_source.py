"""语音识别 / 商品生图的「单一来源 + 旧供应商退役」守卫（issue #7661）。

用户 2026-10-24 裁定：语音识别与商品生图切到阿里云 MaaS（token-plan），**主推理/视觉不动**，
并废弃旧百炼 key。本守卫让「改回旧形态」进不来，三条都会红：

G1 **配置默认值**（唯一真值 = `app/config.py` 的默认值，不读 `.env`）：
   `ASR_MODEL` / `IMAGE_GEN_MODELS` 与两个端点主机必须是 MaaS 形态。
G2 **旧 key 不得被当兜底**：`app/api/asr.py` 不得再出现 `PRIMARY_API_KEY` —— 那是 DeepSeek 的
   key，打到百炼只会 401，且会让「缺 key」静默变成「用错 key」（fail-closed 被架空）。
G3 **旧供应商痕迹退场**：旧模型名 `paraformer-realtime-8k-v2` / `qwen-mt-image-2.0` 不得再出现在
   配置面与生效面（豁免台账为空集，只许缩短 —— 现在就是 0 条）。**旧 host 不在此列**：注释里要能写
   「留空 = 用 SDK 默认端点」这种回滚口；生效面由 G1 反向钉（默认值必须是 MaaS host）。

反向自证（避免假绿）：把任一断言的值注入回旧形态，本文件的对应用例必红；恢复即绿。
"""
# case_ids: UI-129, API-012

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AI = ROOT / "backend" / "ai-agent-service"

MAAS_HOST = "token-plan.cn-beijing.maas.aliyuncs.com"

#: G3 的扫描面（配置面 + 生效面 + 部署面）。台账为空 ⇒ 任何一处出现旧供应商痕迹都判红。
SCANNED = (
    AI / "app" / "config.py",
    AI / "app" / "api" / "asr.py",
    AI / "app" / "images" / "generator.py",
    AI / ".env.example",
    ROOT / ".github" / "workflows" / "ai-agent-tests.yml",
    ROOT / ".github" / "workflows" / "deploy-ai-agent-service.yml",
)

#: 退役痕迹（**只许缩短**：新增条目必须先证明它不可能是活的配置）。
RETIRED = (
    "paraformer-realtime-8k-v2",
    "qwen-mt-image-2.0",
)


def _default(name: str) -> str:
    """读 `Settings` 的字段默认值（绕开 .env 与进程环境，钉住的是仓库真值）。"""
    text = (AI / "app" / "config.py").read_text(encoding="utf-8")
    m = re.search(rf"^\s*{name}:\s*str\s*=\s*\(?\s*\"([^\"]+)\"", text, re.M)
    assert m, f"config.py 里找不到 {name} 的字符串默认值"
    return m.group(1)


def test_g1_audio_and_image_defaults_point_to_maas():
    assert _default("ASR_MODEL") == "qwen-audio-3.0-realtime-plus"
    assert _default("IMAGE_GEN_MODELS") == "qwen-image-3.0-pro"
    assert MAAS_HOST in _default("ASR_WEBSOCKET_BASE_URL")
    assert "/api-ws/" in _default("ASR_WEBSOCKET_BASE_URL")
    assert MAAS_HOST in _default("IMAGE_GEN_BASE_URL")
    assert "/api/v1/services/aigc/" in _default("IMAGE_GEN_BASE_URL")


def test_g2_asr_does_not_fall_back_to_primary_key():
    src = (AI / "app" / "api" / "asr.py").read_text(encoding="utf-8")
    # 只判**代码级使用**：注释/文档里解释「不再回落」是合规的（同 §23「提及不得判红」）
    assert "settings.PRIMARY_API_KEY" not in src, (
        "asr.py 又把 PRIMARY_API_KEY（DeepSeek key）当兜底了：缺 ASR_API_KEY 必须 fail-closed"
    )
    assert "api_key = settings.ASR_API_KEY" in src


def test_g3_retired_provider_traces_are_gone():
    hits = []
    for path in SCANNED:
        text = path.read_text(encoding="utf-8")
        for token in RETIRED:
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}::{token}")
    assert hits == [], "旧供应商痕迹仍在生效面/配置面：\n" + "\n".join(hits)
