package com.migao.admin.service;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 不合格**原因字典**（issue #7197 的 ①）。
 *
 * <h3>为什么要有字典</h3>
 * <p>旧形态 {@code quality_inspections.reason} 是**自由文本**（「布面污渍」/「脏」/「污渍」会被算成
 * 三个不同原因）⇒ 缺陷 Top 分布、帕累托、按原因筛选**在结构上都做不了**。所以：
 * 判定 ≠ 合格时**必须**先选一个字典项（本类），{@code reason} 降级为**自由补充**（可空）。</p>
 *
 * <h3>口径（不得偏离）</h3>
 * <ul>
 *   <li><b>字典是服务端唯一真值源</b>：录入面（{@code GET /api/admin/quality-inspections/reasons}）
 *       与校验面（{@link QualityCheckService}）读的是**同一份** {@link #items()} —— 前端不另造一份会漂的表；</li>
 *   <li><b>有序</b>（{@link LinkedHashMap}）：录入界面按此顺序摆短语按钮，{@code other}（其它）**必须在最后**
 *       —— 它是兜底而不是首选；</li>
 *   <li><b>存量不清洗</b>：老记录的 {@code reason_code} 为 {@code null}、{@code reason} 保持原文
 *       （不猜归类、不回填、不改写）⇒ 读面如实区分「字典项」与「未归类的自由文本」；</li>
 *   <li><b>不按租户可配</b>：本单只落**全局**六项（用户 2026-10-18 的 P2 单里「按租户可配」属后续切片，
 *       做成可配先要一张字典表 + 配置面，超出「先让统计能算」的射程）。</li>
 * </ul>
 */
public final class QualityReasonDictionary {

    /** 兜底项：选它表示「不属于上面任何一类」，{@code reason} 里应当写清到底是什么。 */
    public static final String OTHER = "other";

    /**
     * code → 商家面中文名（**有序**，直接决定录入界面的按钮顺序）。
     *
     * <p>取值形态复用本表既有的小写 ASCII 习惯（与 {@code inspection_result} 的 {@code pass/rework/scrap} 同族）；
     * 中文名是**商家面文案**，不给内部标识上屏（§31 P3）。</p>
     */
    private static final Map<String, String> ITEMS;

    static {
        Map<String, String> items = new LinkedHashMap<>();
        items.put("fabric_stain", "布面污渍");
        items.put("fabric_hole", "布料破洞");
        items.put("color_diff", "色差");
        items.put("size_mismatch", "尺寸不符");
        items.put("stitching_defect", "走线不良");
        items.put(OTHER, "其它");
        ITEMS = Collections.unmodifiableMap(items);
    }

    /** 字典全量（有序、只读）—— 校验面与录入面**同一份**。 */
    public static Map<String, String> items() {
        return ITEMS;
    }

    /** 是否是字典项（{@code null} / 空串 / 未知值 ⇒ {@code false}；调用方据此决定 422）。 */
    public static boolean contains(String code) {
        return code != null && ITEMS.containsKey(code);
    }

    /** 字典项的中文名；未知值如实 {@code null}（**不猜**、不返回 code 冒充中文）。 */
    public static String label(String code) {
        return code == null ? null : ITEMS.get(code);
    }

    /** 录入界面用：{@code [{code, label}]}（有序，与 {@link #items()} 同源）。 */
    public static List<Map<String, Object>> options() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map.Entry<String, String> entry : ITEMS.entrySet()) {
            Map<String, Object> option = new LinkedHashMap<>();
            option.put("code", entry.getKey());
            option.put("label", entry.getValue());
            out.add(option);
        }
        return out;
    }

    /** 报错文案用：{@code 布面污渍 / 布料破洞 / 色差 / 尺寸不符 / 走线不良 / 其它}。 */
    public static String labels() {
        return String.join(" / ", ITEMS.values());
    }

    private QualityReasonDictionary() {
    }
}
