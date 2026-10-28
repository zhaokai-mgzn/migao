package com.migao.admin.service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 裁高配置的**默认种子**（缺行时读面回的那一份）—— <b>全仓唯一来源</b>。
 *
 * <h3>v2（issue #7997；用户 2026-10-28 逐字「裁高参数是根据工序来的」「再允许一个默认公共（兜底）裁高参数」）</h3>
 *
 * <p>种子分两组（{@code scope}）：</p>
 * <ul>
 *   <li><b>工序专用</b>（{@code specific}）：用户逐字「如果有布绑带工序，则需要根据加工项韩褶还是打孔分别自动算高度」
 *       「如果有接高工序，则需要一个画线参数」⇒
 *       {@code 布绑带-韩褶 0.14}（布绑带 ∧ 韩褶）· {@code 布绑带-打孔 0.16}（布绑带 ∧ 打孔）·
 *       {@code 画线 0.145}（接高 ∨ 双眼皮接高）。三个值逐字 = 现场便签（壁达现场照片 2）。</li>
 *   <li><b>公共兜底</b>（{@code fallback}）：用户逐字「其他情况都是默认定高参数」⇒ 沿用 v1 那 6 项
 *       （包布折 / 包布孔 / 包纱折 / 包纱孔 / 布贴 / 纱贴，同名特殊选项触发）。
 *       ⚠️ 兜底组是<b>替换</b>语义：只要有一条专用项命中，整组就不参与。</li>
 * </ul>
 *
 * <p><b>改判登记（用户 2026-10-28 裁定 3-A）</b>：现场便签那三个手写值（画线 0.145 / 绑带-韩褶 0.14 /
 * 绑带-打孔 0.16）<b>自本版起进默认种子</b>，推翻 2026-09-29 裁定③（「便签手写值不进默认种子」）。
 * 开箱即用、商家可改。</p>
 *
 * <p><b>兜底组开箱不命中（照实登记，不是缺陷）</b>：{@code 包布折 / 包布孔 / 布贴 / 纱贴} 这些名字
 * <b>不在</b>观星台的特殊选项词表（真值源 {@code docs/curtain-production-rules.md}）里 ⇒ 同名匹配开箱不命中。
 * 商家要它生效，把触发条件改成自己词表里的名字（或改成加工项 / 工艺条件）即可 —— 这正是 v2 支持的多条件形态。
 * 宁可漏、不可错：给机器的值偏大是事故。</p>
 *
 * <p><b>刻意不种 {@code 纱绑带}</b>：现场便签只给了布绑带的值，凭空编纱帘的值 = 给机器的值偏大是事故
 * ⇒ 商家自建或等现场取证（重启条件 = 拿到纱绑带现场值，与便签同源）。</p>
 */
final class CuttingHeightDefaults {

    private CuttingHeightDefaults() {
    }

    /** 默认取整：保留三位小数（用户 2026-09-29 裁定⑥：机器支持三位小数，用 2.935）。 */
    static Map<String, Object> rounding() {
        Map<String, Object> rounding = new LinkedHashMap<>();
        rounding.put("mode", "half_up");
        rounding.put("digits", 3);
        return rounding;
    }

    /** 默认增量项档案（每次调用返回**新结构**：调用方会改它 / 序列化它，不许共享可变实例）。 */
    static List<Map<String, Object>> items() {
        List<Map<String, Object>> items = new ArrayList<>();
        // ① 工序专用（有专用项命中 ⇒ 兜底组整组不参与）
        items.add(item("bangdai_hanzhe", "布绑带-韩褶", "0.14", "布帘", 10, CuttingHeightCalculator.SCOPE_SPECIFIC,
                List.of(condition("option", "布绑带"), condition("craft", "韩褶"))));
        items.add(item("bangdai_dakong", "布绑带-打孔", "0.16", "布帘", 20, CuttingHeightCalculator.SCOPE_SPECIFIC,
                List.of(condition("option", "布绑带"), condition("craft", "打孔"))));
        items.add(item("huaxian", "画线", "0.145", "布帘", 30, CuttingHeightCalculator.SCOPE_SPECIFIC,
                List.of(condition("option", "接高", "双眼皮接高"))));
        // ② 公共兜底（专用项零命中时才用）—— v1 那 6 项，同名特殊选项触发
        items.add(item("baobuzhe", "包布折", "0.08", "布帘", 110, CuttingHeightCalculator.SCOPE_FALLBACK,
                List.of(condition("option", "包布折"))));
        items.add(item("baobukong", "包布孔", "0.1", "布帘", 120, CuttingHeightCalculator.SCOPE_FALLBACK,
                List.of(condition("option", "包布孔"))));
        items.add(item("baoshazhe", "包纱折", "0.08", "纱帘", 130, CuttingHeightCalculator.SCOPE_FALLBACK,
                List.of(condition("option", "包纱折"))));
        items.add(item("baoshakong", "包纱孔", "0.1", "纱帘", 140, CuttingHeightCalculator.SCOPE_FALLBACK,
                List.of(condition("option", "包纱孔"))));
        items.add(item("butie", "布贴", "0.015", "布帘", 150, CuttingHeightCalculator.SCOPE_FALLBACK,
                List.of(condition("option", "布贴"))));
        items.add(item("shatie", "纱贴", "0.01", "纱帘", 160, CuttingHeightCalculator.SCOPE_FALLBACK,
                List.of(condition("option", "纱贴"))));
        return items;
    }

    /** 默认配置（{@code source='default'} 时读面回的那一份）。 */
    static Map<String, Object> config() {
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("items", items());
        config.put("rounding", rounding());
        return config;
    }

    private static Map<String, Object> condition(String kind, String... values) {
        Map<String, Object> condition = new LinkedHashMap<>();
        condition.put("kind", kind);
        condition.put("values", List.of(values));
        return condition;
    }

    private static Map<String, Object> item(String key, String name, String value, String position, int order,
                                            String scope, List<Map<String, Object>> conditions) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", key);
        item.put("name", name);
        item.put("value", value == null ? null : new BigDecimal(value));
        item.put("direction", "add");
        item.put("height_join", false);
        item.put("scope", scope);
        item.put("position", position);     // null = 不限部位
        item.put("conditions", conditions);
        item.put("enabled", true);
        item.put("order", order);
        return item;
    }
}
