package com.migao.admin.worker;

import java.util.ArrayList;
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
 *
 * <h3>两层页集（issue #6788）</h3>
 * <ol>
 *   <li><b>企业级</b>（{@code worker_page_configs} 单行/租户）：本企业工人端开哪几页 —— <b>天花板</b>；</li>
 *   <li><b>工人档案级</b>（{@code users.worker_pages}，可空）：这位工人<b>再收窄</b>到哪几页 ——
 *       <b>不是</b>授权、也与 {@code users.permissions} <b>不同格</b>。{@code NULL} = <b>未收窄 =
 *       跟随企业设置</b>（2026-10-13 用户裁定：默认零回归）。</li>
 * </ol>
 * <p>实际下发 = {@link #effectiveFor}：企业页 ∩ 个人收窄 —— 企业关掉的页，逐人勾了也<b>不</b>出现。</p>
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

    // ════════════════════════════════════════════════════════════════════════════
    // 工人档案级收窄（issue #6788）—— 读侧归一 / 求交 / 写侧校验
    // ════════════════════════════════════════════════════════════════════════════

    /**
     * 读侧归一工人档案上的收窄值（{@code users.worker_pages}）。
     *
     * <p>三态：{@code null} = <b>未收窄</b>（跟随企业设置）· 非空集 = 收窄到这几页 ·
     * 空集 = 显式「一页都不给」。<b>未知键一律裁掉</b> ⇒ 脏数据只会让工人少看一页（可见性面可接受），
     * 绝不超出企业页集；形态不对（非数组 / 元素非字符串）⇒ 当<b>未收窄</b>（fail-open，
     * 与工人端 {@code effectivePages} 的「读不到就全开」同口径：不因存储异常把活挡在外面）。</p>
     */
    public static Set<String> restrictedOrNull(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return null;
        }
        Set<String> out = new LinkedHashSet<>();
        for (Object item : list) {
            if (item instanceof String key && ALL.contains(key)) {
                out.add(key);
            }
        }
        return out;
    }

    /**
     * 本工人实际可看到的页面集（<b>唯一判据</b>）：企业页 ∩ 个人收窄。
     *
     * <p>红证：取并集 / 以个人为准 ⇒ 企业关掉的页又冒出来 ⇒
     * {@code WorkerPagesTest#workerRestrictionNeverWidensTheEnterpriseSet} 红。</p>
     *
     * @param tenantPages 企业级页面集（{@code WorkerPageConfigService.pagesFor}）
     * @param workerPages {@code users.worker_pages} 原值（{@code null} = 未收窄）
     */
    public static List<String> effectiveFor(List<String> tenantPages, Object workerPages) {
        List<String> tenant = tenantPages == null ? List.of() : tenantPages;
        Set<String> restricted = restrictedOrNull(workerPages);
        if (restricted == null) {
            return List.copyOf(tenant);
        }
        List<String> out = new ArrayList<>();
        for (String page : tenant) {
            if (restricted.contains(page)) {
                out.add(page);
            }
        }
        return out;
    }

    /**
     * 写侧校验 + 归一（供 {@code WorkerAdminService} 组装 422 的 {@code error.details}）。
     *
     * <p>规则：{@code null} = 未收窄（合法）· 必须是数组 · 每项是闭词表内的字符串（未知键<b>点名下标</b>）·
     * 不得重复 · 允许空数组（= 显式一页都不给）。</p>
     *
     * @return {@code errors} 非空 ⇒ 调用方抛 422（本次写入整体不生效，没有部分更新）；
     *         {@code pages} = 归一后的收窄集（保留请求顺序、去重），{@code errors} 为空时可信
     */
    public static Validation validateRestriction(Object raw) {
        if (raw == null) {
            return new Validation(null, List.of());
        }
        List<Map.Entry<String, String>> errors = new ArrayList<>();
        if (!(raw instanceof List<?> list)) {
            errors.add(Map.entry("workerPages", "必须是数组（如 [\"report\",\"cut_calc\"]）"));
            return new Validation(null, errors);
        }
        List<String> pages = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        int index = 0;
        for (Object item : list) {
            String field = "workerPages[" + index + "]";
            // 非字符串**不**做 String.valueOf 兜底：那会把 数字/对象 静默变成一个不存在的页面键
            if (!(item instanceof String key)) {
                errors.add(Map.entry(field, "必须是页面键字符串，合法页面键：" + ALL));
                index++;
                continue;
            }
            String page = key.trim();
            if (!ALL.contains(page)) {
                errors.add(Map.entry(field, "不是工人端页面键：" + page + "（合法页面键：" + ALL
                        + "；未知键会被静默忽略 ⇒ 商家以为设了却没设）"));
            } else if (!seen.add(page)) {
                errors.add(Map.entry(field, "页面键重复：" + page));
            } else {
                pages.add(page);
            }
            index++;
        }
        return new Validation(pages, errors);
    }

    /** 写侧校验结果：{@code pages}（归一后的收窄集，可为 {@code null} = 未收窄）+ {@code errors}（逐条理由）。 */
    public record Validation(List<String> pages, List<Map.Entry<String, String>> errors) {

        /** 无非法项。 */
        public boolean ok() {
            return errors.isEmpty();
        }
    }
}
