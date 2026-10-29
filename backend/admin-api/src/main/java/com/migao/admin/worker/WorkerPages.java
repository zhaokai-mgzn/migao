package com.migao.admin.worker;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 工人端**页面键**的闭词表与默认值 —— <b>全仓唯一来源</b>。
 *
 * <h3>它回答什么</h3>
 * <p>工人端 H5 / 车间一体机上**出现哪些页面**（报工页 / 订单页 / 裁高计算器 / 发货页）。</p>
 *
 * <h3>🔴 它不是权限码（本类的存在就是为了把这件事钉在代码里）</h3>
 * <p>工人端身份（{@code role=worker}）的 {@code permissions} <b>恒为 {@code []}</b>
 * （{@code WorkerSessionService} 只签发 {@code roles=["worker"]}、{@code permissions=[]}），
 * 工人可达面恒为 {@code /api/worker/**}，{@code /api/admin/**} 对 {@code worker} 一律 403
 * （{@code SecurityConfig.ADMIN_API_REJECTED_ROLES}）。</p>
 * <p>⇒ <b>禁止</b>把这里的页面码写进 {@code users.permissions}。本表只决定「页面上看不看得见」，
 * 服务端对每个工人都仍然按同一套授权判。</p>
 *
 * <p>🔴 <b>例外（issue #7162，用户 2026-10-17 裁定）</b>：{@link #INSPECT}（质检）这一个键
 * <b>同时</b>是工人端质检写入的服务端**准入** —— 工人要在 H5 扫码后录质检判定，必须在其档案的
 * 页面集里有 {@code inspect}。它不是 RBAC 权限码（仍不进 {@code users.permissions}），而是
 * 「档案级能力开关」；其余键仍只是可见性。</p>
 *
 * <p>🔴 <b>质检页不在默认集合里</b>（逐人开）：未收窄（{@code null}）⇒ {@link #defaultPages()}
 * （不含 {@code inspect}）；要开就给该工人的收窄集里加上 {@code inspect}。</p>
 *
 * <h3>一层真值（issue #6828，2026-10-13 用户裁定「一步到位移除」）</h3>
 * <p>企业级页面开关（V141 / 表 {@code worker_page_configs} / 设置页「工人端页面」域）<b>已整层移除</b>
 * —— 页面集合只由**工人档案**上的 {@code users.worker_pages}（V152，issue #6788）决定：</p>
 * <ul>
 *   <li>{@code null} / 坏值 = <b>未收窄 = 全部页面</b>（fail-open：存储异常不该把工人挡在活外面）；</li>
 *   <li>非空集 = <b>收窄到这几页</b>（闭词表 {@link #ALL} 内的键；未知键按只裁不放宽的既有方向裁掉）。</li>
 * </ul>
 * <p>逐人勾选的**选项来源** = 只读目录端点 {@code GET /api/admin/worker-pages}
 * （{@link #defaultPages()} + {@link #labels()}）—— 前端因此不需要维护第二份会漂的页面清单。</p>
 *
 * <h3>默认值只在一处</h3>
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

    /**
     * 页面键：我的计件（**合计金额** + 件数 + 逐笔；issue #6767，2026-10-12 用户逐字「需要给工人看」）。
     *
     * <p>🔴 涉钱面，口径由 {@code docs/design/worker-home-menu.md} §6.3 钉死六条：金额聚合**复用**
     * 商家端计件读面的同一份实现（{@code ProductionService.aggregate}），工人面只做「当前工人 + 期间」
     * 的**过滤投影**；作用域只由 {@code X-Worker-Session-Id} 解（请求里带 {@code worker_id} 不改变结果）。</p>
     */
    public static final String PIECEWORK = "piecework";

    /** 页面键：发货（**写面** = 拍照发货 / 生成发货单）。 */
    public static final String SHIPMENT = "shipment";

    /**
     * 页面键：**待发货单**（**读面** = 全完工订单名单 + 发货标签；issue #7814）。
     *
     * <p>用户 2026-10-26（商家后台「设置工人端菜单」截图）逐字：「新增的工人菜单在这里也要能设置」。</p>
     *
     * <p>🔴 与 {@link #SHIPMENT} 是**两个能力**，不合并：拍照发货是「把这一单发出去」（写），
     * 待发货单是「车间今天能发哪些、贴哪张标签」（读）。合成一个键的后果是商家想关掉其中一个
     * 就必须两个都关（菜单开关是**显隐**，不是权限，关错了现场就没入口可用）。</p>
     */
    public static final String TO_SHIP = "to_ship";

    /**
     * 页面键：**质检**（issue #7162）—— 工人扫水洗唛进报工页后，可录入质检判定并生成「质检单」。
     *
     * <p>🔴 与其它页不同：它**同时是服务端写准入**（不在默认集合里、逐人开；见类注释）。</p>
     */
    public static final String INSPECT = "inspect";

    /**
     * 页面键：**库存修正**（issue #8104；用户 2026-10-29 逐字
     * 「手机端还要增加一个库存修正的功能，apk程序也要同步增加这个功能，允许工人对某个批次的布匹进行修正」）。
     *
     * <p>工作台第 N 张卡「库存修正」的显隐键：工人发现某批布实际剩余与系统不符时，
     * 在手机上按批次改成实测米数（写面 = `POST /api/worker/batch-stock/correction`，
     * 复用按批次盘点的唯一写面）。默认开（操作工具，与 `shipment` 同档）；商家可在工人档案上逐人关。</p>
     */
    public static final String STOCK = "stock";

    /**
     * 页面键：**返工记录**（issue #7860）—— 手机端「报返工的加工单列表」（`/w/rework.html`）。
     *
     * <p>🔴 用户 2026-10-26 裁定「在工人档案中设置过可见权限的工人」能看到：不在默认集合里、
     * 逐人开（与 {@link #INSPECT} 同款形态）。与 `inspect` 的差别：它**只是读面可见性**，
     * 报返工的写准入 = 有效工人 session（任一工序工人都能报，不看这个键）。</p>
     */
    public static final String REWORK = "rework";

    /**
     * 合法页面键的<b>闭词表</b>（缺页/未知页 ⇒ 422 逐条理由；拼错的键会被静默忽略 = 商家以为改了却没改）。
     *
     * <p>顺序 = 工人端默认的页面顺序（读面原样回给前端，前端不再自己排一遍）。</p>
     */
    public static final Set<String> ALL = Collections.unmodifiableSet(new LinkedHashSet<>(List.of(
            REPORT, PIECEWORK, ORDER, CUT_CALC, SHIPMENT, TO_SHIP, STOCK, INSPECT, REWORK)));

    private WorkerPages() {
    }

    /**
     * **默认**页面键（未收窄的工人看到的页面集合）。
     *
     * <p>🔴 {@link #INSPECT} **不在**这里（issue #7162，用户裁定「工人档案逐人开质检页」）：
     * 质检页只能通过给该工人的收窄集里加 {@code inspect} 来开放。</p>
     *
     * <p>也是只读目录端点（{@code GET /api/admin/worker-pages}）的 {@code default_pages}
     * —— 配置面据此把「未收窄」渲染成默认勾选态，前端不另抄一份默认值。可选页全集 = {@link #ALL}。</p>
     */
    public static List<String> defaultPages() {
        return List.of(REPORT, PIECEWORK, ORDER, CUT_CALC, SHIPMENT, TO_SHIP, STOCK);
    }

    /**
     * **非默认、逐人开放**的能力页（issue #7162）：不在 {@link #defaultPages()} 里，
     * 商家在工人档案上单独勾选；其中 {@link #INSPECT} 同时是服务端写准入。
     */
    public static List<String> optionalPages() {
        return List.of(INSPECT, REWORK);
    }

    /** 页面键 → 商家面可读名称（配置面板按它渲染勾选项；键是机器码，名称是人话）。 */
    public static Map<String, String> labels() {
        Map<String, String> labels = new LinkedHashMap<>();
        labels.put(REPORT, "报工");
        labels.put(PIECEWORK, "计件工资报表");
        labels.put(ORDER, "订单");
        labels.put(CUT_CALC, "裁高计算器");
        labels.put(SHIPMENT, "发货");
        labels.put(TO_SHIP, "待发货单");
        labels.put(STOCK, "库存修正");
        labels.put(INSPECT, "质检");
        labels.put(REWORK, "返工记录");
        return labels;
    }

    // ════════════════════════════════════════════════════════════════════════════
    // 工人档案级收窄（issue #6788 / 单层口径 issue #6828）—— 读侧归一 / 求值 / 写侧校验
    // ════════════════════════════════════════════════════════════════════════════

    /**
     * 读侧归一工人档案上的收窄值（{@code users.worker_pages}）—— <b>宽容解析，坏值一律当「未收窄」</b>。
     *
     * <p>三态：{@code null} = <b>未收窄</b>（看全部页面）· 非空集 = 收窄到这几页（其它一律丢弃，见下）。</p>
     *
     * <p>🔴 <b>为什么坏值当「未收窄」而不是当「一页都不给」</b>：读侧 fail-open —— 存储形态异常时
     * 把工人挡在活外面的代价，远大于「他多看见一个入口」（后者是本表设计上就接受的边界：页面可见性
     * 不是访问控制，藏起菜单 ≠ 挡住接口，见类注释）。</p>
     *
     * <p>接受两种入参：{@code List<?>}（测试 / 直连调用）与库里的**原样 JSON 文本**（{@code String}，
     * 见 {@code User#workerPages} 的「为什么不用 JacksonTypeHandler」）。</p>
     *
     * <p>🔴 <b>两种失败要分开</b>（都写在这里，免得后人合并）：</p>
     * <ul>
     *   <li><b>不是数组 / 解析不出来</b>（{@code "report"}、{@code {"report":true}}、截断的 JSON…）⇒
     *       当<b>未收窄</b>（fail-open）：存储形态异常不该把工人的活挡在外面。</li>
     *   <li><b>是数组、但一个真键都没有</b>（元素非字符串 / 全是未知键）⇒ <b>空集</b>（= 什么都不露）：
     *       这是「收窄了，但收窄到的东西都不存在」—— 若退回全开，就等于**放宽**（与「只裁不放宽」相反）。</li>
     * </ul>
     *
     * @return {@code null} = 未收窄（含解析失败）；否则 = 归一后的收窄集（**可为空集**）
     */
    public static Set<String> restrictedOrNull(Object raw) {
        List<?> list;
        if (raw instanceof List<?> l) {
            list = l;
        } else if (raw instanceof String s) {
            List<String> parsed = parseJsonArray(s);
            if (parsed == null) {
                return null;
            }
            list = parsed;
        } else {
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

    /** 工人档案列的存储形态：收窄集 → 入库 JSON 文本（{@code null} = 未收窄 = 库里 NULL）。 */
    public static String storedJson(List<String> pages) {
        return pages == null ? null : toJson(pages);
    }

    /**
     * 库里的原样文本 → 已归一集合（**只读商品**：给 {@code toWorkerView} 用，不做校验）。
     *
     * @return {@code null} = 未收窄（含脏值）
     */
    public static Set<String> normalizeStored(String storedJson) {
        return restrictedOrNull(storedJson);
    }

    private static String toJson(List<String> pages) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < pages.size(); i++) {
            if (i > 0) {
                sb.append(',');
            }
            sb.append('"').append(pages.get(i).replace("\"", "")).append('"');
        }
        return sb.append(']').toString();
    }

    /** 极简 JSON 数组解析（**零依赖**）：只认 {@code ["a","b"]} 这一种形态，其余返回 {@code null}。 */
    private static List<String> parseJsonArray(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.length() < 2 || s.charAt(0) != '[' || s.charAt(s.length() - 1) != ']') {
            return null;
        }
        List<String> out = new ArrayList<>();
        String body = s.substring(1, s.length() - 1).trim();
        if (body.isEmpty()) {
            return out;
        }
        for (String part : body.split(",")) {
            String t = part.trim();
            if (t.length() < 2 || t.charAt(0) != '"' || t.charAt(t.length() - 1) != '"') {
                return null;
            }
            out.add(t.substring(1, t.length() - 1));
        }
        return out;
    }

    /**
     * 本工人实际可看到的页面集（<b>唯一判据</b>）：未收窄 ⇒ 全部页面；收窄 ⇒ 收窄集（按闭词表顺序）。
     *
     * <p>🔴 <b>为什么归一后为空集时回落「全部页面」</b>：写面已拒空数组、也拒未知键
     * （{@link #validateRestriction}）⇒ 能走到这里的空集只有**存量脏数据**（例如 {@code ["stock"]}）。
     * 而工人端 H5 对空数组的口径是 **fail-open = 按全开运行**
     * （{@code frontend/worker-h5/src/render.mjs} 的 {@code effectivePages}：空集只可能来自「没读到权限」）
     * ⇒ 服务端若原样下发空集，端侧**反而会全开**，与服务端读数不一致。回落后两侧口径一致，
     * 且只影响这一位工人的菜单显隐（不是授权放宽，见类注释的红线）。</p>
     *
     * <p>红证：把回落去掉 ⇒ 脏数据（如 {@code ["stock"]}）下发的 {@code pages} 变成空数组 ⇒
     * {@code WorkerPagesTest#dirtyRestrictionFallsBackToAllPages} 红。</p>
     *
     * @param workerPages {@code users.worker_pages} 原值（{@code null} / 脏值 = 未收窄）
     */
    public static List<String> effectiveFor(Object workerPages) {
        Set<String> restricted = restrictedOrNull(workerPages);
        if (restricted == null) {
            return defaultPages();
        }
        List<String> out = new ArrayList<>();
        // 🔴 遍历 ALL（不是 defaultPages）：`inspect` / `rework` 不在默认集合里，却是可逐人开放的
        //    页面键。漏一个的后果不是「少显示一个入口」，而是**商家勾了、工人端什么也看不见**
        //    （2026-10-27 现场：档案勾了「返工记录」，工作台无入口，issue #7932 —— 改前这里
        //    只特判了 INSPECT，REWORK 加进闭词表时被漏掉）。
        //    遍历 ALL 同时修掉另一个口径错误：只开 rework 时 `out` 不再为空 ⇒ **不回落默认页**
        //    （改前「只开返工记录」会让工人看到六页默认菜单 = 把商家的意图反过来）。
        for (String page : ALL) {
            if (restricted.contains(page)) {
                out.add(page);
            }
        }
        return out.isEmpty() ? defaultPages() : out;
    }

    /**
     * 写侧校验 + 归一（供 {@code WorkerAdminService} 组装 422 的 {@code error.details}）。
     *
     * <p>规则：{@code null} = 未收窄（合法）· 必须是数组 · 每项是闭词表内的字符串（未知键<b>点名下标</b>）·
     * 不得重复 · <b>不得为空数组</b>。</p>
     *
     * <p>🔴 <b>为什么空数组非法</b>（与 {@link #restrictedOrNull} 的读侧宽容是**一对**）：
     * 「一页都不给」在工人端不是「什么都不显示」而是 <b>fail-open = 全开</b>
     * （{@code effectivePages} 把空数组读成「没读到权限」）⇒ 允许它等于让管理员点出一个
     * **与意图相反**的结果。产品上「让这个人别干活」的既有入口是**停用档案**
     * （{@code PUT /api/admin/users/{id}/status}），不是把页面清空 ⇒ 这里 422 并指路。</p>
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
            errors.add(Map.entry("workerPages", "必须是数组（如 [\"report\",\"cut_calc\"])"));
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
        if (errors.isEmpty() && pages.isEmpty()) {
            errors.add(Map.entry("workerPages",
                    "至少要留一个页面：一页都不留时工人端会按「没读到权限」全开运行（与意图相反）。"
                            + "要让这位工人不干活，请用「停用」而不是清空菜单"));
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
