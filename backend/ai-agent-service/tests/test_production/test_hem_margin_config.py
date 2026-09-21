# case_ids: OR-041
"""「上下卷边」`hem_margin` 进**算料配置键** —— issue #4976 包 1b。

用户 2026-09-21 对 issue #4940 的两条路选了 **B**：**让上下卷边可配**（此前它是硬编码常量
`curtain_calc.HEM_MARGIN`，商家没有任何入口）。

## 为什么值得单独一包（而不是顺手加一列）

`HEM_MARGIN` 在引擎里有 **5 处**消费点，且分属**两条公式**：
- **定高可行性**（`成品高 + 卷边 ≤ 门幅`）—— 决定走定高买宽还是回落定宽买高（**米数会变**）；
- **定宽买高每幅长**（`每幅长 = 成品高 + 卷边`，+ 花距）；
- **折数法两支**（同样用每幅长）；
- **罗马帘**（`(宽 + 包边) × (高 + 卷边)`）；
- **自动特征「超高」的判据**（`成品高 + 卷边 > 门幅`，issue #4976 包 1a 新增）。

⇒ 「有的地方走配置、有的地方仍走常量」= 同一张单两套口径（本仓最忌的形态）。
本包的判据 4 就是钉这个：**全部消费点**都必须走 `cfg["hem_margin"]`。

## 判据（每条都能单独判红）

| # | 判据 | 红证 |
|---|---|---|
| 1 | 键进 `DEFAULT_CRAFT_CALC_CONFIG`，且默认值 == 模块常量 `HEM_MARGIN` | 默认值写成别的数 ⇒ 红 |
| 2 | **缺省逐值不变**：不传配置 ⇒ 与今天逐值相同（回归不变量） | 默认值改 0.4 ⇒ 红 |
| 3 | **配置生效**：改 `hem_margin` ⇒ 定高可行性 / 每幅长 / 超高判定随之变 | 任一处仍用常量 ⇒ 红 |
| 4 | **五处消费点全部走 cfg**（静态：`HEM_MARGIN` 在函数体里只能出现在**默认值定义**处） | 留一处用常量 ⇒ 红 |
| 5 | 护栏：`0` / 负数 / 非数 ⇒ `ValueError`（端点 400，**不静默回退默认值**） | 静默回退 ⇒ 红 |
| 6 | 键进 `_POSITIVE_CONFIG_KEYS`（与 Java `NUMERIC_KEYS` 同集合，跨源守卫钉住） | 漏登记 ⇒ 红 |

⚠️ **前端副本不动**：`frontend/admin-web/src/lib/craft-auto-features.ts` 仍持有一份 `HEM_MARGIN`
（下单页「超高」判定用它，跨语言守卫 `test_hem_margin_cross_language_drift.py` 钉住）。
本包让**引擎侧**可配 ⇒ 前端与租户配置之间出现**已知偏差**（商家改了卷边、下单页仍按默认判），
**由包 2（判定移到服务端）收口** —— 照实登记在 PR 描述里，不假装没有。
"""

import re
from pathlib import Path

import pytest

from app.tools import curtain_calc

ENGINE_SRC = Path(__file__).resolve().parents[2] / "app" / "tools" / "curtain_calc.py"
FIXED_HEIGHT = "定高买宽"


def _names(features):
    return [f["name"] for f in features]


class TestKeyRegistration:
    """判据 1 / 6：键登记与默认值。"""

    def test_default_equals_the_module_constant(self):
        # 注入：把默认值写成 0.4（而常量仍 0.3）⇒ 红（「默认值有两个落点」）
        assert curtain_calc.DEFAULT_CRAFT_CALC_CONFIG["hem_margin"] == curtain_calc.HEM_MARGIN

    def test_key_is_registered_as_positive_scalar(self):
        # 注入：漏登记 ⇒ 0/负数会被静默接受 ⇒ 红
        assert "hem_margin" in curtain_calc._POSITIVE_CONFIG_KEYS

    def test_missing_config_row_still_gets_the_default(self):
        cfg = curtain_calc.resolve_craft_calc_config(None)
        assert cfg["hem_margin"] == curtain_calc.HEM_MARGIN


class TestDefaultPathUnchanged:
    """判据 2：缺省逐值不变（回归不变量）。"""

    def test_fixed_height_feasibility_unchanged(self):
        # 成品高 2.5 + 卷边 0.3 = 2.8 ≤ 门幅 2.8 ⇒ 仍走定高买宽（与改前同）；双开 ⇒ 余量 0.3
        quote = curtain_calc.build_quote(
            window_width=6.6, window_height=2.5, mounting="s_hook",
            craft_tier="standard", open_count=2, fabric_width=2.8,
        )
        assert quote["formula_used"] == "fixed_height_pleats"
        assert quote["fabric_meters"] == 13.3

    def test_over_height_verdict_unchanged(self):
        assert _names(curtain_calc.detect_auto_features(
            window_width=1.6, window_height=2.6, fabric_width=2.8, cutting_mode=FIXED_HEIGHT,
        )) == ["超高"]


class TestConfigTakesEffect:
    """判据 3：改 `hem_margin` ⇒ 三处结论随之变。"""

    def test_hem_margin_flips_fixed_height_feasibility(self):
        base = curtain_calc.build_quote(
            window_width=6.6, window_height=2.5, mounting="s_hook",
            craft_tier="standard", fabric_width=2.8,
        )
        # 卷边 0.5 ⇒ 2.5 + 0.5 = 3.0 > 2.8 ⇒ 回落定宽买高（**米数随之变**）
        tight = curtain_calc.build_quote(
            window_width=6.6, window_height=2.5, mounting="s_hook",
            craft_tier="standard", fabric_width=2.8, config={"hem_margin": 0.5},
        )
        # 注入：定高可行性仍用常量 ⇒ tight 与 base 同支 ⇒ 红
        assert base["formula_used"] == "fixed_height_pleats"
        assert tight["formula_used"] == "fixed_width_pleats"
        assert tight["fabric_meters"] != base["fabric_meters"]

    def test_hem_margin_changes_panel_length(self):
        # 定宽买高：每幅长 = 成品高 + 卷边 ⇒ 卷边变大 ⇒ 米数变大（其余不变）
        small = curtain_calc.build_quote(
            window_width=1.6, window_height=3.0, mounting="s_hook",
            craft_tier="standard", fabric_width=2.8, config={"hem_margin": 0.2},
        )
        big = curtain_calc.build_quote(
            window_width=1.6, window_height=3.0, mounting="s_hook",
            craft_tier="standard", fabric_width=2.8, config={"hem_margin": 0.6},
        )
        # 注入：每幅长仍用常量 ⇒ 两者相等 ⇒ 红
        assert big["fabric_meters"] > small["fabric_meters"]

    def test_hem_margin_changes_over_height_verdict(self):
        # 2.4 + 0.3 = 2.7 ≤ 2.8 ⇒ 不判；卷边 0.5 ⇒ 2.9 > 2.8 ⇒ 判超高
        assert _names(curtain_calc.detect_auto_features(
            window_width=1.6, window_height=2.4, fabric_width=2.8, cutting_mode=FIXED_HEIGHT,
        )) == []
        assert _names(curtain_calc.detect_auto_features(
            window_width=1.6, window_height=2.4, fabric_width=2.8,
            cutting_mode=FIXED_HEIGHT, config={"hem_margin": 0.5},
        )) == ["超高"]

    def test_hem_margin_changes_roman_panel(self):
        # 罗马帘：(宽 + 包边) × (高 + 卷边) —— 卷边必须走 cfg。
        # ⚠️ 直调 `calculate_fabric_meters`（`build_quote` 的罗马帘不走这条分支 ⇒ 经它测不到该消费点）
        small, _, _ = curtain_calc.calculate_fabric_meters(
            1.5, 2.0, 1.0, 2.8, mounting="roman",
            config=curtain_calc.resolve_craft_calc_config({"hem_margin": 0.2}),
        )
        big, _, _ = curtain_calc.calculate_fabric_meters(
            1.5, 2.0, 1.0, 2.8, mounting="roman",
            config=curtain_calc.resolve_craft_calc_config({"hem_margin": 0.6}),
        )
        # 注入：罗马帘那处仍用常量 ⇒ 两者相等 ⇒ 红
        assert big > small


class TestAllConsumptionPointsUseConfig:
    """判据 4：静态钉住「五处消费点全走 cfg」（防「改了三处、漏两处」）。"""

    def test_module_constant_is_only_used_as_the_default(self):
        src = ENGINE_SRC.read_text(encoding="utf-8")
        # 只看**代码**（去注释）：注释里引用常量名做说明是允许的
        code = re.sub(r"#[^\n]*", "", src)
        # 允许的两处：常量定义行 + 配置字典里那一行（**默认值的唯一落点**）
        allowed = re.compile(r'^\s*(HEM_MARGIN\s*=|"hem_margin":\s*HEM_MARGIN,)')
        uses = [
            line.strip()
            for line in code.split("\n")
            if "HEM_MARGIN" in line and not allowed.match(line)
        ]
        # 注入：把任一处消费点改回 `HEM_MARGIN` ⇒ 本断言红（列出违规行，便于定位）
        assert uses == [], (
            "`HEM_MARGIN` 只允许出现在**常量定义**与**配置字典那一行**（默认值唯一落点）；"
            f"以下位置仍在用它 ⇒ 同一张单两套口径：{uses}"
        )


class TestGuardRails:
    """判据 5：非法值 fail-closed（**不静默回退默认值**）。"""

    @pytest.mark.parametrize("bad", [0, -0.1, "abc"])
    def test_invalid_hem_margin_is_rejected(self, bad):
        with pytest.raises(ValueError):
            curtain_calc.build_quote(
                window_width=6.6, window_height=2.5, mounting="s_hook",
                craft_tier="standard", config={"hem_margin": bad},
            )
