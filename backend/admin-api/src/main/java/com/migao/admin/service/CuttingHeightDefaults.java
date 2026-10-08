package com.migao.admin.service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 裁高配置的**默认种子**（缺行时读面回的那一份）—— <b>全仓唯一来源</b>。
 *
 * <p>种子逐字 = 壁达 ERP 现场「下发数据到生产机器」弹窗里那 7 个增量项
 * （照片实证，见设计单 §1.4）：{@code 包布折 0.08} · {@code 包布孔 0.1} · {@code 包纱折 0.08} ·
 * {@code 包纱孔 0.1} · <b>{@code 画线}（有项无值）</b> · {@code 布贴 0.015} · {@code 纱贴 0.01}。</p>
 *
 * <p><b>命中口径</b>：默认按「**同名匹配**」——{@code hit.trigger_value} 逐字等于订单上的
 * 特殊选项名（{@code processingInfo.specialOptions[]}）即命中。⚠️ 照实说明：观星台的特殊选项词表
 * （真值源 {@code docs/curtain-production-rules.md}）里并没有「包布折 / 包布孔 / 布贴 / 纱贴 / 画线」
 * 这五个名字 ⇒ 这份种子**开箱不会命中任何东西**，等商家把触发值改成自己词表里的名字（或现场取证拿到
 * 壁达那批「选项 ↔ 扩展项」对应行）才生效。这是**有意**的：宁可漏、不可错（给机器的值偏大是事故）。</p>
 *
 * <p><b>画线一项刻意留空值</b>（{@code value = null}）：壁达那边它就是"有项无值"（现场因此要在机器上贴便签），
 * 我们**不替它编一个数**、也**不静默按 0 算** —— 命中而未配置取值的项会进预览的 {@code misses}
 * （{@code reason=unresolved}）。</p>
 *
 * <p>⚠️ 现场便签上的三个手写值（画线 +0.145 / 绑带-韩褶 +0.14 / 绑带-打孔 +0.16）
 * <b>不进</b>这份种子（用户 2026-09-29 裁定③）；需要时由商家在配置里自建条目，不改代码。</p>
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
        items.add(item("baobuzhe", "包布折", "0.08", "布帘", 10));
        items.add(item("baobukong", "包布孔", "0.1", "布帘", 20));
        items.add(item("baoshazhe", "包纱折", "0.08", "纱帘", 30));
        items.add(item("baoshakong", "包纱孔", "0.1", "纱帘", 40));
        items.add(item("huaxian", "画线", null, null, 50));
        items.add(item("butie", "布贴", "0.015", "布帘", 60));
        items.add(item("shatie", "纱贴", "0.01", "纱帘", 70));
        return items;
    }

    /** 默认配置（{@code source='default'} 时读面回的那一份）。 */
    static Map<String, Object> config() {
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("items", items());
        config.put("rounding", rounding());
        return config;
    }

    private static Map<String, Object> item(String key, String name, String value, String position, int order) {
        Map<String, Object> hit = new LinkedHashMap<>();
        hit.put("trigger_kind", "option");
        hit.put("trigger_value", name);     // 同名匹配（设计单 §2.2 裁定）
        hit.put("position", position);      // null = 不限部位
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", key);
        item.put("name", name);
        item.put("value", value == null ? null : new BigDecimal(value));
        item.put("direction", "add");
        item.put("height_join", false);
        item.put("hit", hit);
        item.put("hit_expr", null);
        item.put("enabled", true);
        item.put("order", order);
        return item;
    }
}
