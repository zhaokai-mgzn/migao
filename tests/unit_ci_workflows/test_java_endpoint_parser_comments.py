# case_ids: MC-005
"""`tool_http_attribution.java_endpoints` 的**注释掩码**判据（issue #6367 包 P2 实测的坑）。

## 这条判据要治什么（类级尺度）

`java_endpoints` 用 `_JavaParse._METHOD_RE` / `_CLASS_MAPPING_RE` 在**Java 源码文本**上找
`@PostMapping` 之类的映射注解。但本仓的 javadoc 里**逐字**写着这类注解当说明，例如
`{@code @PostMapping("/x")}`。

不剥注释 ⇒ 那些**说明**被当成**真注解** ⇒ 同一个方法多出一条**幽灵端点**。实测（issue #6367 包 P2）：

- `ImageRecognitionController` 的类文档里写了一句 `{@code @PostMapping}`
- ⇒ `/api/admin/**` 无码端点现取 **9 → 11**（多出的是**同路径的重复条**）
- ⇒ 把只许缩短的台账（`ADMIN_SCOPE_UNANNOTATED_CEILING`）**凭空顶红**，
  而报错文案会把人引向「去登记端点」这个**错误**的修法

## 两层修，两条判据

1. **掩码必须等长**：`_strip_java_comments` 早先是 `.sub(" ", text)` ⇒ 注释被**压成一个空格**，
   掩码串比原文短得多（实测 7803 → 4528 字节）⇒「在掩码串上 `finditer` 拿偏移、再拿去切**原文**」
   会整体错位（端点路径解析成空）。等长掩码后两类用法都安全。
2. **`java_endpoints` 必须在掩码串上找映射注解**（`_annotations_before` / `_class_permission`
   早就剥了，`java_endpoints` 此前漏了）。

两份判据都**注入式**：拿改过的源码文本跑**同一份**解析器（`java_sources=` 入口就是为注入存在的），
不是靠读磁盘碰运气。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_SERVICE_TESTS = REPO_ROOT / "backend" / "ai-agent-service" / "tests"
REAL_CONTROLLER = (
    REPO_ROOT
    / "backend"
    / "admin-api"
    / "src"
    / "main"
    / "java"
    / "com"
    / "migao"
    / "admin"
    / "controller"
    / "ImageRecognitionController.java"
)
REL = "com/migao/admin/controller/ImageRecognitionController.java"


def _attr():
    """装 `tool_http_attribution`（沿用既有 loader 口径；不造第二套解析器）。"""
    if str(AI_SERVICE_TESTS) not in sys.path:
        sys.path.insert(0, str(AI_SERVICE_TESTS))
    path = AI_SERVICE_TESTS / "tool_http_attribution.py"
    if "migao_tool_http_attribution" in sys.modules:
        return sys.modules["migao_tool_http_attribution"]
    spec = importlib.util.spec_from_file_location("migao_tool_http_attribution", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["migao_tool_http_attribution"] = mod
    spec.loader.exec_module(mod)
    return mod


def _live_src() -> str:
    return REAL_CONTROLLER.read_text(encoding="utf-8")


def _live_map(src: str):
    return _attr().java_endpoints(None, {REL: src})


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1：掩码**等长**（偏移可用）——这是判据 2 能成立的前提
# ══════════════════════════════════════════════════════════════════════════════

def test_strip_java_comments_is_length_preserving():
    """等长掩码：`len(strip(x)) == len(x)`，且被掩的位置在原串上**确实是注释**。

    红证：把 `_strip_java_comments` 改回 `.sub(" ", text)` ⇒ 本判据当场红
    （实测 `len` 7803 → 4528）。
    """
    attr = _attr()
    src = _live_src()
    masked = attr._strip_java_comments(src)
    assert len(masked) == len(src), (
        f"掩码必须等长，否则「掩码串偏移 → 原文切片」会错位："
        f"len(原文)={len(src)} ≠ len(掩码)={len(masked)}"
    )
    # 掩掉的位置必须落在注释/空白里（取真注释的一小段：类文档里的 `{@code @PostMapping}`）
    probe = src.find("{@code @PostMapping}")
    assert probe > 0, "实测锚点消失了（`ImageRecognitionController` 类文档里的 `{@code @PostMapping}`）"
    assert masked[probe : probe + 8] == " " * 8, "注释里的字符必须被掩成空格"
    assert "@PostMapping" not in masked[probe - 2 : probe + 20], "注释里的映射注解不得残留在掩码串里"


def test_masked_offsets_point_at_the_same_characters():
    """等长 ⇒ **同一偏移**在原文与掩码串上指同一字符（判据 2 依赖这条）。"""
    attr = _attr()
    src = _live_src()
    masked = attr._strip_java_comments(src)
    for probe, expect in (
        (src.find("public ApiResponse<"), "public ApiResponse<"),
        (src.find('"/interpret"'), '"/interpret"'),
    ):
        assert probe > 0, f"锚点未找到：{expect}"
        assert src[probe : probe + len(expect)] == expect
        # 代码里的字符**不被掩掉**（掩码只在注释位置动手）
        assert expect.split()[0] in masked[probe : probe + len(expect) + 20], (
            f"代码区被误掩：{masked[probe:probe + 40]!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 2：注释里的映射注解**不得**产出端点（幽灵端点）
# ══════════════════════════════════════════════════════════════════════════════

def test_mapping_annotation_inside_javadoc_yields_no_ghost_endpoint():
    """注入：javadoc 里写 `{@code @PostMapping}` ⇒ 端点表**不多**一条。

    红证：`java_endpoints` 在原文（而非掩码串）上 `finditer` ⇒ 本判据当场红
    （实测：`('POST','/api/admin/image-recognition')` 由 1 条变 2 条）。
    """
    src = _live_src()
    base = _live_map(src)
    key = ("POST", "/api/admin/image-recognition")
    assert len(base[key]) == 1, f"现实基线应是 1 条：{[(k, len(v)) for k, v in base.items()]}"

    injected = src.replace(
        " * 识别图片 → 结构化字段（**不落库**）。",
        " * 说明：本方法用 {@code @PostMapping}（**这句是注释，不是注解**）。",
        1,
    )
    assert injected != src, "注入未生效（自证坐标失败）⇒ 判据会空跑"
    # 注入的那句**确实**在注释里，且在**代码区**之外
    assert "本方法用 {@code @PostMapping}" in injected
    after = _live_map(injected)
    assert len(after[key]) == 1, (
        f"注释里的 `{{@code @PostMapping}}` 被当成真注解 ⇒ 幽灵端点（现取 {len(after[key])} 条）"
    )
    assert after.keys() == base.keys(), f"端点集合被注释污染：{sorted(set(after) ^ set(base))}"


def test_class_level_mapping_inside_javadoc_yields_no_ghost_endpoint():
    """注入：javadoc 里写 `{@code @RequestMapping("/bogus")}` ⇒ **不得**改类级前缀。

    红证：`_CLASS_MAPPING_RE.search(src)`（原文）会命中注释里的那句。
    """
    src = _live_src()
    injected = src.replace(
        " * 识别图片 → 结构化字段（**不落库**）。",
        ' * 说明：类级用 {@code @RequestMapping("/bogus-prefix")}（注释，不是注解）。',
        1,
    )
    assert injected != src, "注入未生效 ⇒ 判据会空跑"
    after = _live_map(injected)
    assert not any("bogus-prefix" in k[1] for k in after), (
        f"注释里的 `@RequestMapping` 污染了类级前缀：{[k for k in after if 'bogus' in k[1]]}"
    )
    assert ("POST", "/api/admin/image-recognition/interpret") in after, (
        "真端点被连带丢掉（掩码把代码也吃了）—— 不许用「少认端点」换绿"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：判别力自证（坏形态必红、好形态不红）
# ══════════════════════════════════════════════════════════════════════════════

def test_parser_still_sees_real_annotations():
    """对照组（正向）：**真**注解必须照旧被认出来 —— 防「把映射注解一律不认」的假绿。"""
    after = _live_map(_live_src())
    assert ("POST", "/api/admin/image-recognition") in after
    assert ("POST", "/api/admin/image-recognition/interpret") in after


def test_injected_real_annotation_is_seen():
    """对照组（判别力）：在**代码区**加一个真注解 ⇒ 端点表必须多一条。

    与判据 2 成对：注释里的不认、代码里的照认 ⇒ 掩码没有把判据变成空断言。
    """
    src = _live_src()
    injected = src.replace(
        '    @PostMapping("/interpret")',
        '    @PostMapping("/interpret-probe")\n'
        '    public Object probe() { return null; }\n\n'
        '    @PostMapping("/interpret")',
        1,
    )
    assert injected != src, "注入未生效 ⇒ 判据会空跑"
    after = _live_map(injected)
    assert ("POST", "/api/admin/image-recognition/interpret-probe") in after, (
        f"代码区的真注解没被认出来 ⇒ 掩码把判据变成了空断言：{sorted(after)}"
    )
