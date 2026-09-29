package com.migao.admin.worker;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 工人端**页面开关**的闭词表与默认值（V141，母单 #5161）—— <b>全仓唯一来源</b>。
 *
 * <h3>它回答什么</h3>
 * <p>工人端 H5 / 车间一体机上**出现哪些页面**（报工页 / 订单页 / 裁高计算器 / 发货页）。</p>
 *
 * <h3>🔴 它不是权限码（本类的存在就是为了把这件事钉在代码里）</h3>
 * <p>工人端身份（{@code role=worker}）的 {@code permissions} <b>恒为 {@code []}</b>
 * （{@code WorkerSessionService} 只签发 {@code roles=["worker"]}、{@code permissions=[]}），
 * 工人可达面恒为 {@code /api/worker/**}，{@code /api/admin/**} 对 {@code worker} 一律 403
 * （{@code SecurityConfig.ADMIN_API_REJECTED_ROLES}）。</p>
 * <p>⇒ <b>禁止</b>把这里的页面码写进 {@code users.permissions}，也<b>禁止</b>让
 * {@link com.migao.admin.service.WorkerPageConfigService} 参与任何授权判定 —— 本表只决定
 * 「页面上看不看得见」，服务端对每个工人都仍然按同一套授权判。</p>
 *
 * <h3>缺行 = 默认全开</h3>
 * <p>默认集合只在 {@link #defaultPages()} <b>一处</b>；库里再种一份 = 第二份会漂的默认值
 * （同族先例：{@code CuttingHeightDefaults} / {@code craft_calc_configs}）。</p>
 */
public final class WorkerPages {

    /** 页面键：报工（扫码领活 / 完工）。 */
    public static final String REPORT = "report";

    /** 页面键：订单（订单与套号明细）。 */
    public static final String ORDER = "order";

    /** 页面键：裁高计算器（与商家端「裁高配置」同一个算面）。 */
    public static final String CUT_CALC = "cut_calc";

    /** 页面键：发货。 */
    public static final String SHIPMENT = "shipment";

    /**
     * 合法页面键的<b>闭词表</b>（缺页/未知页 ⇒ 422 逐条理由；拼错的键会被静默忽略 = 商家以为改了却没改）。
     *
     * <p>顺序 = 工人端默认的页面顺序（读面原样回给前端，前端不再自己排一遍）。</p>
     */
    public static final Set<String> ALL = Set.copyOf(new LinkedHashSet<>(List.of(
            REPORT, ORDER, CUT_CALC, SHIPMENT)));

    private WorkerPages() {
    }

    /** 默认页面集合（缺行读面回的那一份 = 全部页面）。每次调用返回新列表，调用方不许改共享实例。 */
    public static List<String> defaultPages() {
        return List.of(REPORT, ORDER, CUT_CALC, SHIPMENT);
    }

    /** 页面键 → 商家面可读名称（配置面板按它渲染勾选项；键是机器码，名称是人话）。 */
    public static Map<String, String> labels() {
        Map<String, String> labels = new LinkedHashMap<>();
        labels.put(REPORT, "报工");
        labels.put(ORDER, "订单");
        labels.put(CUT_CALC, "裁高计算器");
        labels.put(SHIPMENT, "发货");
        return labels;
    }
}
