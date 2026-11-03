"""生图等待上限「单一权威 + 三层派生」守卫（issue #7731）。

病（2026-10-25 生产实测）：界面承诺「约 40 秒」，两次读数实测 **121s / 145s**；三层超时各写一份
（前端 210000ms / admin-api 200000ms / ai-agent 180s）⇒ 改一层忘一层：前端先放弃而后端还在跑、
后端比供应商正常耗时还短（长尾被掐断时图已在供应商侧生成、照计费，商家却拿不到）。

口径（本守卫钉的）：
- **唯一权威** = ai-agent `app/config.py` 的 `IMAGE_GEN_TIMEOUT`（唯一真正等供应商的一层）；
- admin-api **不写**读超时常量：生成前从 `/api/internal/images/deadline` 现取（取不到 ⇒ 不设上限，
  不擅自给一个比供应商更紧的数）；
- 前端 **不写**生图超时字面量：等待上限经 admin-api 的 `estimated_deadline_ms` 派生；
- 页面文案的「最长约 N 分钟」由该值算出；「通常多久」来自实测区间（121~145s）。

判别力自证：把任一层改回硬编码 / 把旧承诺写回文案 ⇒ 对应用例判红并具名（见 test_guard_*）。
"""
# case_ids: MC-136

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AI_CONFIG = ROOT / "backend/ai-agent-service/app/config.py"
AI_INTERNAL = ROOT / "backend/ai-agent-service/app/api/internal.py"
AI_ENV_EXAMPLE = ROOT / "backend/ai-agent-service/.env.example"
ADMIN_CLIENT = (
    ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/ProductImageClient.java"
)
ADMIN_CONTROLLER = (
    ROOT / "backend/admin-api/src/main/java/com/migao/admin/controller/ProductImageController.java"
)
WEB_API = ROOT / "frontend/admin-web/src/lib/api.ts"
WEB_IMAGE_API = ROOT / "frontend/admin-web/src/lib/api-product-image.ts"
WEB_PANEL = ROOT / "frontend/admin-web/src/components/products/ProductImageAI.tsx"

#: 三层接线路径（ai-agent 内部端点 ⇄ admin-api 常量；admin-api 控制器 ⇄ 前端调用）。
DEADLINE_ENDPOINT = "/api/internal/images/deadline"
ESTIMATE_PATH = "/api/admin/products/ai-images/estimate"


def _text(path: Path) -> str:
    assert path.is_file(), f"守卫的扫描面缺文件：{path.relative_to(ROOT)}（判据不许静默空跑）"
    return path.read_text(encoding="utf-8")


def hardcoded_timeout_ms(text: str) -> list[int]:
    """代码里**硬编码的生图超时**（deadline 量级，≥ 10s）：`TIMEOUT_MS = 200_000` / `timeout: 210000`。

    连接超时（3s 量级）不是 deadline，不在射程内 —— 那是本层自己的网络参数，不是等供应商的上限。
    """
    found = re.findall(
        r"(?:timeout(?:_ms)?\s*[:=]\s*|setReadTimeout\(\s*)(\d[\d_]{4,})", text, re.I
    )
    return [value for value in (int(x.replace("_", "")) for x in found) if value >= 10_000]


def promise_literals(text: str) -> list[str]:
    """文案里**写死**的等待承诺（旧口径的「约 N 秒」「约 N~M 分钟」这类会打脸的数字）。"""
    return re.findall(
        r"(?:约|通常|最长约)\s*\d+(?:\s*[~\-到]\s*\d+)?\s*(?:秒|分钟)", text
    )


def authority_seconds() -> int:
    """唯一权威 deadline（秒）：ai-agent `IMAGE_GEN_TIMEOUT` 的默认值。"""
    m = re.search(r"^\s*IMAGE_GEN_TIMEOUT:\s*int\s*=\s*(\d+)", _text(AI_CONFIG), re.M)
    assert m, "config.py 找不到 IMAGE_GEN_TIMEOUT 的默认值（唯一权威必须有唯一定义）"
    return int(m.group(1))


def measured_seconds() -> tuple[int, int]:
    """面板里登记的实测区间（秒）——「通常多久」的唯一事实来源。"""
    m = re.search(
        r"MEASURED_IMAGE_SECONDS\s*=\s*\{\s*min:\s*(\d+),\s*max:\s*(\d+)\s*\}",
        _text(WEB_PANEL),
    )
    assert m, "面板缺实测区间常量 MEASURED_IMAGE_SECONDS（「通常多久」必须来自实测）"
    return int(m.group(1)), int(m.group(2))


def test_ai_agent_is_the_single_authority():
    """三层里只有 ai-agent 一处 deadline 定义；`.env.example` 不再写第二份活值。"""
    authority = authority_seconds()
    assert authority >= 180, (
        f"权威 deadline 只有 {authority}s：必须覆盖实测 121~145s 的长尾（旧值 180 只余 ~20%）"
    )
    assert authority <= 600, f"权威 deadline {authority}s 过长：面板会给出不合理的「最长约」"

    scanned = (
        _text(AI_CONFIG) + _text(AI_INTERNAL) + _text(ADMIN_CLIENT)
        + _text(WEB_API) + _text(WEB_IMAGE_API)
    )
    definitions = re.findall(r"IMAGE_GEN_TIMEOUT:\s*(?:int|float)\s*=", scanned)
    assert len(definitions) == 1, (
        f"三层里出现了 {len(definitions)} 处 deadline 定义（只允许 config.py 一处）："
        "其它层应经端点/下发字段派生"
    )
    assert not re.search(r"^\s*IMAGE_GEN_TIMEOUT=", _text(AI_ENV_EXAMPLE), re.M), (
        ".env.example 又写了一份活值：默认值只留在 config.py，knob 用注释登记"
    )


def test_admin_api_derives_the_read_timeout_from_the_authority():
    """admin-api 没有自己的生图读超时常量；deadline 从 ai-agent 端点现取。"""
    client = _text(ADMIN_CLIENT)
    assert "GENERATE_READ_TIMEOUT_MS" not in client, (
        "admin-api 又写死了 GENERATE_READ_TIMEOUT_MS：应经 /images/deadline 现取"
    )
    assert hardcoded_timeout_ms(client) == [], (
        f"admin-api 出现硬编码超时字面量：{hardcoded_timeout_ms(client)}"
    )
    assert f'DEADLINE_PATH = "{DEADLINE_ENDPOINT}"' in client, (
        f"admin-api 的 deadline 端点常量与 ai-agent 不一致（缺 {DEADLINE_ENDPOINT}）"
    )
    assert "applyReadTimeout(deadlineMs())" in client, "生成前没有按上游 deadline 设置读超时"
    assert "readTimeoutFor(long deadlineMs)" in client, "读超时不是从上游 deadline 派生"
    assert "TRANSFER_MARGIN_MS" in client, "读超时缺少传输余量（上游 deadline 之外的空间）"

    internal = _text(AI_INTERNAL)
    assert '@router.get("/images/deadline")' in internal, "ai-agent 没有提供 deadline 端点"
    assert "settings.IMAGE_GEN_TIMEOUT * 1000" in internal, (
        "deadline 端点没有现取 settings.IMAGE_GEN_TIMEOUT（又写了一个常量？）"
    )


def test_frontend_derives_the_wait_from_the_same_authority():
    """前端没有生图超时字面量；等待上限经 admin-api 的 estimated_deadline_ms 派生。"""
    api = _text(WEB_API)
    image_api = _text(WEB_IMAGE_API)
    assert "210000" not in api and "210000" not in image_api, (
        "前端又把 210000 写回来了（应与权威 deadline 同源）"
    )
    assert hardcoded_timeout_ms(api) == [] and hardcoded_timeout_ms(image_api) == [], (
        f"前端出现硬编码生图等待字面量：{hardcoded_timeout_ms(api) + hardcoded_timeout_ms(image_api)}"
    )
    # api.ts 是 loc ratchet 的冻结文件：实现必须住在拆分文件里，api.ts 只做转出
    assert "from './api-product-image'" in api, "api.ts 没有从拆分文件转出商品图 API"
    assert f"'{ESTIMATE_PATH}'" in image_api, f"商品图 API 模块没有读 {ESTIMATE_PATH}"
    assert "estimated_deadline_ms" in image_api, "前端没有消费 admin-api 下发的等待上限"
    assert "imageGenTimeoutMs" in image_api, "前端等待上限不是由下发的上限派生"

    controller = _text(ADMIN_CONTROLLER)
    assert '@GetMapping("/estimate")' in controller, "admin-api 没有 /estimate 端点"
    assert "estimated_deadline_ms" in controller, "admin-api 没有下发 estimated_deadline_ms"


def test_copy_states_the_measured_range_and_derives_the_ceiling():
    """文案按实测说、上限由权威 deadline 算出；不写死乐观数字，超 30 秒有进度提示。"""
    panel = _text(WEB_PANEL)
    assert promise_literals(panel) == [], (
        f"面板出现写死的等待承诺（应改为实测区间 + 由权威上限算出的「最长约」）：{promise_literals(panel)}"
    )
    low, high = measured_seconds()
    assert low < high, f"实测区间不成立：{low}~{high}s"
    assert high < authority_seconds(), (
        f"实测长尾 {high}s 已逼近/超过权威 deadline {authority_seconds()}s："
        "应该改 deadline 而不是把文案改得更乐观"
    )
    assert "typicalRangeText(" in panel, "文案没有用实测区间（「通常多久」写死了？）"
    assert "deadlineText(" in panel, "文案的「最长约」没有由权威上限算出"
    assert "还在生成" in panel and "SLOW_HINT_AFTER_S" in panel, (
        "生成超过 30 秒没有补「还在生成」（2 分钟里只剩一个转圈）"
    )


def test_guard_discriminates_the_three_bad_shapes():
    """判别力自证：三种坏形态（三层硬编码 / 文案写死）必须被同一批扫描器抓到。"""
    # ① 三层任一改回硬编码 ⇒ 命中
    assert hardcoded_timeout_ms(
        "static final int GENERATE_READ_TIMEOUT_MS = 200_000;"
    ) == [200_000]
    assert hardcoded_timeout_ms("factory.setReadTimeout(180_000);") == [180_000]
    assert hardcoded_timeout_ms("request.post(url, payload, { timeout: 210000 })") == [210_000]
    # ② 文案写死乐观数字 ⇒ 命中；模板串（${...}）不误伤
    assert promise_literals("约 40 秒") == ["约 40 秒"]
    assert promise_literals("共 8 张，约 2~4 分钟") == ["约 2~4 分钟"]
    assert promise_literals("单张通常 ${typicalRangeText()}") == []
    # ③ 对照：连接超时（3s 量级）不是 deadline，不误伤
    assert hardcoded_timeout_ms("private static final int CONNECT_TIMEOUT_MS = 3_000;") == []
