package com.migao.admin.service;

import com.migao.admin.entity.ProductionCraft;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteTemplate;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 工序路线**新结构**的测试夹具（P2b，issue #4459 = 母单 #4423）。
 *
 * <h2>为什么单独一个类</h2>
 * 消费路径切到新结构后，实例化的工序来源是「路线模板 + 规则表 + 部位价目 + 工序库」四层，
 * 而多个测试文件（{@code ProcessingOrderServiceTest} / {@code ProcessingOrderRouteSourceTest} /
 * {@code ProductionOperationQueryServiceTest} / {@code ProcessingRoutingCommandServiceTest}）
 * 都要造这四层 ⇒ 各写一份必然漂移（且漂移的那一份不会变红）。
 *
 * <h2>夹具的口径（与真值源同源，不是平行真值）</h2>
 * <ul>
 *   <li>{@link #catalog()} —— 工序库行**逐字取自 V54/V56/V58 种子**（分组/单位/单价/必完/开始标记），
 *       与真值源 {@code routing.py::OPERATION_CATALOG} 同值；</li>
 *   <li>{@link #canonicalPositions()} —— 部位价目**从路线序列派生**（某部位路线里出现的逻辑工序
 *       ⇒ {@code applicable=true} + 该道工序的单价；其余 {@code false}）。
 *       之所以派生而不是抄 84 行：夹具只覆盖 3 条路线（11 + 10 + 6 道）用到的工序，
 *       抄全量矩阵会带进一堆本夹具没有库行的逻辑工序 ⇒ {@code missing_operations} 假红；</li>
 *   <li>{@link #rules()} —— 规则表**逐条抄自 V71/V72 种子的 26 行**（工艺变体 10 + 特殊选项 16），
 *       工序名与锚点都是逻辑名；</li>
 *   <li>{@link #mainline()} —— 规范主线 9 道（{@code ROUTE_MAINLINE_STEPS}）。</li>
 * </ul>
 *
 * <p>⚠️ 本夹具**不实现**「怎么展开路线」—— 展开语义只在
 * {@code ProcessingOrderService.buildRoute}（与 {@code routing.py::build_route_v2} 逐字一致）。
 * 夹具只提供**输入**。</p>
 */
public final class RoutingModelFixture {

    private RoutingModelFixture() {
    }

    /** 规范主线（9 道，不含工艺槽位）—— 与 {@code routing.py::ROUTE_MAINLINE_STEPS} 逐字同源。 */
    public static List<String> mainline() {
        return List.of("精裁", "三边", "熨烫", "定型", "复烫", "车被",
                "外帘打卷", "打包", "外帘装袋", "外帘发货");
    }

    /** 默认路线模板名（与 V71/V72 种子逐字一致）。 */
    public static final String TEMPLATE_NAME = "窗帘工序路线（默认）";

    // ── 布料基础路线（issue #4529，包 F）──
    /** 第 4 个部位（布料单专用）。 */
    public static final String FABRIC_POSITION = "布料";
    /** 布料路线模板名（与 V79 / schema.sql 种子逐字一致）。 */
    public static final String FABRIC_TEMPLATE_NAME = "布料工序路线";
    /** 布料主线（2 道）：`配料` → `打包`。 */
    public static final List<String> FABRIC_MAINLINE = List.of("配料", "打包");

    /** 套级工序（{@code scope='set'}，V67 / issue #4384 A1 + V79 / #4529 的 `打包`）。 */
    public static final Set<String> SET_SCOPE_OPERATIONS =
            Set.of("外帘打卷", "外帘装袋", "外帘发货", "打包");

    /**
     * 全部 35 条旧变体（{@code {旧工序名, 分组, 单位, 单价, 必完, 开始标记}}）：与 V54/V56/V58 种子逐字同源。
     *
     * <p>覆盖**全部**逻辑工序名（28 个）—— 否则「逻辑名 → 变体名」解析不到 ⇒
     * {@code buildRoute} 会把该道登记进 {@code missing_operations} ⇒ 假红。</p>
     */
    private static final String[][] LEGACY_VARIANTS = {
            {"精裁-布", "裁剪", "米", "0.4", "false", "true"},
            {"精裁-纱", "裁剪", "米", "0.4", "false", "true"},
            {"裁剪-布", "裁剪", "米", "0.4", "false", "false"},
            {"裁剪-纱", "裁剪", "米", "0.4", "false", "false"},
            {"布三边", "车位", "米", "0.4", "false", "false"},
            {"纱三边", "车位", "米", "0.4", "false", "false"},
            {"韩褶-布", "车位", "折", "0.4", "false", "false"},
            {"韩褶-纱", "车位", "折", "0.4", "false", "false"},
            {"上车布-布", "车位", "米", "0.5", "false", "false"},
            {"上车布-纱", "车位", "米", "0.5", "false", "false"},
            {"打孔-布", "车位", "孔", "0.15", "false", "false"},
            {"打孔-纱", "车位", "孔", "0.15", "false", "false"},
            {"拼1次-布", "车位", "幅", "0.8", "false", "false"},
            {"拼2次-布", "车位", "幅", "1.2", "false", "false"},
            {"拼3次-布", "车位", "幅", "1.6", "false", "false"},
            {"花边-布", "车位", "米", "0.6", "false", "false"},
            {"铅坠-布", "车位", "米", "0.3", "false", "false"},
            {"接高-布", "车位", "幅", "1.0", "false", "false"},
            {"帘头制作", "车位", "个", "2.0", "false", "false"},
            {"熨烫-布", "后道", "米", "0.35", "false", "false"},
            {"定型-布", "后道", "米", "0.4", "false", "false"},
            {"复烫-布", "后道", "米", "0.35", "false", "false"},
            {"布帘车被", "后道", "米", "0.4", "false", "false"},
            {"外帘打卷", "后道", "套", "1.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "false", "false"},
            {"质检", "后道", "套", "1.5", "false", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"},
            {"绑带-布", "其他", "套", "0.5", "false", "false"},
            {"抱枕", "其他", "个", "2.0", "false", "false"},
            {"腰靠垫", "其他", "个", "2.0", "false", "false"},
            {"绑带-纱", "其他", "套", "0.5", "false", "false"},
            {"logo条-布", "车位", "米", "0.6", "false", "false"},
            {"立边-布", "车位", "米", "0.5", "false", "false"},
            {"扣环-布", "车位", "个", "0.3", "false", "false"},
            {"防翘扣-布", "车位", "个", "0.2", "false", "false"},
    };

    /** 旧工序名 → 部位（测试侧推导；部位无关的工序返回 null）。 */
    static String positionOfLegacy(String name) {
        return switch (name) {
            case "精裁-布" -> "布帘";
            case "精裁-纱" -> "纱帘";
            case "裁剪-布" -> "布帘";
            case "裁剪-纱" -> "纱帘";
            case "布三边" -> "布帘";
            case "纱三边" -> "纱帘";
            case "韩褶-布" -> "布帘";
            case "韩褶-纱" -> "纱帘";
            case "上车布-布" -> "布帘";
            case "上车布-纱" -> "纱帘";
            case "打孔-布" -> "布帘";
            case "打孔-纱" -> "纱帘";
            case "拼1次-布" -> "布帘";
            case "拼2次-布" -> "布帘";
            case "拼3次-布" -> "布帘";
            case "花边-布" -> "布帘";
            case "铅坠-布" -> "布帘";
            case "接高-布" -> "布帘";
            case "帘头制作" -> "帘头";
            case "熨烫-布" -> "布帘";
            case "定型-布" -> "布帘";
            case "复烫-布" -> "布帘";
            case "布帘车被" -> "布帘";
            case "绑带-布" -> "布帘";
            case "绑带-纱" -> "纱帘";
            case "logo条-布" -> "布帘";
            case "立边-布" -> "布帘";
            case "扣环-布" -> "布帘";
            case "防翘扣-布" -> "布帘";
            default -> null;
        };
    }

    /** 一条路线序列：{@code {工序名, 分组, 单位, 单价, is_must_finish, is_start_marker}}。 */
    public static final String[][] V54_BULIAN_HANZHE = {
            {"精裁-布", "裁剪", "米", "0.4", "false", "true"},
            {"布三边", "车位", "米", "0.4", "false", "false"},
            {"韩褶-布", "车位", "折", "0.4", "false", "false"},
            {"上车布-布", "车位", "米", "0.5", "false", "false"},
            {"熨烫-布", "后道", "米", "0.35", "false", "false"},
            {"定型-布", "后道", "米", "0.4", "false", "false"},
            {"复烫-布", "后道", "米", "0.35", "false", "false"},
            {"布帘车被", "后道", "米", "0.4", "false", "false"},
            {"外帘打卷", "后道", "套", "1.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    public static final String[][] V54_BULIAN_DAKONG = {
            {"精裁-布", "裁剪", "米", "0.4", "false", "true"},
            {"布三边", "车位", "米", "0.4", "false", "false"},
            {"打孔-布", "车位", "孔", "0.15", "false", "false"},
            {"熨烫-布", "后道", "米", "0.35", "false", "false"},
            {"定型-布", "后道", "米", "0.4", "false", "false"},
            {"复烫-布", "后道", "米", "0.35", "false", "false"},
            {"布帘车被", "后道", "米", "0.4", "false", "false"},
            {"外帘打卷", "后道", "套", "1.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    public static final String[][] V58_SHALU_DAKONG = {
            {"精裁-纱", "裁剪", "米", "0.4", "false", "true"},
            {"纱三边", "车位", "米", "0.4", "false", "false"},
            {"打孔-纱", "车位", "孔", "0.15", "false", "false"},
            {"外帘打卷", "后道", "套", "1.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    /** 条件工序/规则会用到的额外工序库行（V56 / V58 种子里的那几道）。 */
    private static final String[][] EXTRA_OPERATIONS = {            {"拼1次-布", "车位", "幅", "0.8", "false", "false"},
            {"花边-布", "车位", "米", "0.6", "false", "false"},
            {"帘头制作", "车位", "个", "2.0", "false", "false"},
            {"绑带-布", "其他", "套", "0.5", "false", "false"},
            {"抱枕", "其他", "个", "2.0", "false", "false"},
            {"logo条-布", "车位", "米", "0.6", "false", "false"},
            {"立边-布", "车位", "米", "0.5", "false", "false"},
            {"扣环-布", "车位", "个", "0.3", "false", "false"},
            {"防翘扣-布", "车位", "个", "0.2", "false", "false"},
            {"铅坠-布", "车位", "米", "0.3", "false", "false"},
            {"接高-布", "车位", "幅", "1.0", "false", "false"},
            {"拼2次-布", "车位", "幅", "1.2", "false", "false"},
            {"拼3次-布", "车位", "幅", "1.6", "false", "false"},
            {"绑带-纱", "其他", "套", "0.5", "false", "false"}};

    /**
     * 布料路线的两道工序（issue #4529）：{@code {工序名, 分组, 单位, 单价, 必完, 开始标记}}。
     * 与 V79 / schema.sql / {@code routing.py::OPERATION_CATALOG} 逐字同源（单位 = 米 / 套）。
     */
    private static final String[][] FABRIC_OPERATIONS = {
            {"配料", "后道", "米", "0.0", "false", "false"},
            {"打包", "后道", "套", "0.0", "false", "false"},
    };

    // ══════════════════════════ 工序库 ══════════════════════════

    /** 该租户工序库按名索引（{@code operationsByName} 的返回形态）。 */
    public static Map<String, Map<String, Object>> catalog() {
        Map<String, Map<String, Object>> views = new LinkedHashMap<>();
        for (String[] row : LEGACY_VARIANTS) {
            views.put(row[0], meta(row[0], row[1], row[2], row[3], row[4], row[5]));
        }
        // 三条路线的逐字元数据覆盖（必完/开始标记/单价以 V54/V58 种子为准）
        for (String[][] table : List.of(V54_BULIAN_HANZHE, V54_BULIAN_DAKONG, V58_SHALU_DAKONG,
                EXTRA_OPERATIONS, FABRIC_OPERATIONS)) {
            for (String[] row : table) {
                views.put(row[0], meta(row[0], row[1], row[2], row[3], row[4], row[5]));
            }
        }
        return views;
    }

    /** 该租户工序库的实体行（{@code ProductionOperationQueryServiceTest} 的 mapper 桩用）。 */
    public static List<ProductionOperation> operationEntities(Long tenantId) {
        List<ProductionOperation> rows = new ArrayList<>();
        int sort = 1;
        for (String[][] table : List.of(LEGACY_VARIANTS, V54_BULIAN_HANZHE, V54_BULIAN_DAKONG,
                V58_SHALU_DAKONG, EXTRA_OPERATIONS, FABRIC_OPERATIONS)) {
            for (String[] row : table) {
                rows.add(ProductionOperation.builder()
                        .id("op-" + row[0]).tenantId(tenantId).name(row[0]).groupName(row[1])
                        .unit(row[2]).unitPrice(new BigDecimal(row[3]))
                        .isMustFinish(Boolean.parseBoolean(row[4]))
                        .isStartMarker(Boolean.parseBoolean(row[5]))
                        .sortOrder(sort++).status("active").deleted(0)
                        .scope(SET_SCOPE_OPERATIONS.contains(row[0]) ? "set" : "position")
                        .build());
            }
        }
        return rows;
    }

    private static Map<String, Object> meta(String name, String group, String unit, String unitPrice,
                                            String mustFinish, String startMarker) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("group", group);
        view.put("unit", unit);
        view.put("unit_price", new BigDecimal(unitPrice));
        view.put("is_must_finish", Boolean.parseBoolean(mustFinish));
        view.put("is_start_marker", Boolean.parseBoolean(startMarker));
        // 作用域 = V67 终态（三道外帘 = set，其余 = position）—— 实例化侧据此判「每樘窗一次」
        view.put("scope", SET_SCOPE_OPERATIONS.contains(name) ? "set" : "position");
        return view;
    }

    // ══════════════════════════ 部位价目 ══════════════════════════

    /**
     * 部位价目 + 适用性（**从路线序列派生**）：某部位的路线里出现的逻辑工序 ⇒
     * {@code applicable=true} + 该道工序的单价；其余逻辑工序 ⇒ {@code applicable=false}。
     */
    public static List<ProductionOperationPosition> canonicalPositions(Long tenantId) {
        Map<String, String[][]> routes = new LinkedHashMap<>();
        routes.put("布帘", V54_BULIAN_HANZHE);
        routes.put("纱帘", V58_SHALU_DAKONG);
        Map<String, String[]> priceByLogicalPosition = new LinkedHashMap<>();
        Set<String> allLogical = new LinkedHashSet<>();
        for (Map.Entry<String, String[][]> entry : routes.entrySet()) {
            for (String[] row : entry.getValue()) {
                String logical = logicalName(row[0]);
                allLogical.add(logical);
                priceByLogicalPosition.putIfAbsent(logical + "×" + entry.getKey(), row);
            }
        }
        // 布帘专属的额外工序（打孔路线之外的：定型/复烫/车被 已在上面）
        for (String[] row : V54_BULIAN_DAKONG) {
            String logical = logicalName(row[0]);
            allLogical.add(logical);
            priceByLogicalPosition.putIfAbsent(logical + "×布帘", row);
        }
        List<ProductionOperationPosition> rows = new ArrayList<>();
        for (String logical : allLogical) {
            for (String position : List.of("布帘", "纱帘", "帘头")) {
                String[] hit = priceByLogicalPosition.get(logical + "×" + position);
                rows.add(ProductionOperationPosition.builder()
                        .id("opp-" + logical + "-" + position).tenantId(tenantId)
                        .logicalName(logical).position(position)
                        .unitPrice(hit == null ? null : new BigDecimal(hit[3]))
                        .applicable(hit != null)
                        .status("active").deleted(0)
                        .build());
            }
        }
        // 第 4 个部位（布料，issue #4529）：只有 `配料`/`打包` 适用，且**未定价**（unit_price = null
        // = 「适用但未定价」）—— 与 `applicable=false` 的「不适用」在数据上可区分。
        for (String logical : List.of("配料", "打包")) {
            rows.add(ProductionOperationPosition.builder()
                    .id("opp-" + logical + "-" + FABRIC_POSITION).tenantId(tenantId)
                    .logicalName(logical).position(FABRIC_POSITION)
                    .unitPrice(null).applicable(true)
                    .status("active").deleted(0)
                    .build());
        }
        return rows;
    }

    /** 规范部位价目（84 行 = 28 逻辑工序 × 3 部位）：与 V71 种子 / routing.py::OPERATION_POSITION_PRICES 逐行同值。 */
    public static List<ProductionOperationPosition> canonicalPositions84(Long tenantId) {
        String[][] rows = {
                {"精裁", "布帘", "0.4", "true"},
                {"精裁", "纱帘", "0.4", "true"},
                {"精裁", "帘头", "0.4", "true"},
                {"裁剪", "布帘", "0.4", "true"},
                {"裁剪", "纱帘", "0.4", "true"},
                {"裁剪", "帘头", "0.4", "true"},
                {"三边", "布帘", "0.4", "true"},
                {"三边", "纱帘", "0.4", "true"},
                {"三边", "帘头", "0.4", "true"},
                {"韩褶", "布帘", "0.4", "true"},
                {"韩褶", "纱帘", "0.4", "true"},
                {"韩褶", "帘头", "0.4", "true"},
                {"上车布", "布帘", "0.5", "true"},
                {"上车布", "纱帘", "0.5", "true"},
                {"上车布", "帘头", null, "false"},
                {"打孔", "布帘", "0.15", "true"},
                {"打孔", "纱帘", "0.15", "true"},
                {"打孔", "帘头", "0.15", "true"},
                {"拼1次", "布帘", "0.8", "true"},
                {"拼1次", "纱帘", null, "false"},
                {"拼1次", "帘头", null, "false"},
                {"拼2次", "布帘", "1.2", "true"},
                {"拼2次", "纱帘", null, "false"},
                {"拼2次", "帘头", null, "false"},
                {"拼3次", "布帘", "1.6", "true"},
                {"拼3次", "纱帘", null, "false"},
                {"拼3次", "帘头", null, "false"},
                {"花边", "布帘", "0.6", "true"},
                {"花边", "纱帘", null, "false"},
                {"花边", "帘头", null, "false"},
                {"铅坠", "布帘", "0.3", "true"},
                {"铅坠", "纱帘", null, "false"},
                {"铅坠", "帘头", null, "false"},
                {"接高", "布帘", "1.0", "true"},
                {"接高", "纱帘", null, "false"},
                {"接高", "帘头", null, "false"},
                {"帘头制作", "布帘", null, "false"},
                {"帘头制作", "纱帘", null, "false"},
                {"帘头制作", "帘头", "2.0", "true"},
                {"熨烫", "布帘", "0.35", "true"},
                {"熨烫", "纱帘", null, "false"},
                {"熨烫", "帘头", null, "false"},
                {"定型", "布帘", "0.4", "true"},
                {"定型", "纱帘", null, "false"},
                {"定型", "帘头", "0.4", "true"},
                {"复烫", "布帘", "0.35", "true"},
                {"复烫", "纱帘", null, "false"},
                {"复烫", "帘头", null, "false"},
                {"车被", "布帘", "0.4", "true"},
                {"车被", "纱帘", null, "false"},
                {"车被", "帘头", null, "false"},
                {"外帘打卷", "布帘", "1.0", "true"},
                {"外帘打卷", "纱帘", "1.0", "true"},
                {"外帘打卷", "帘头", "1.0", "true"},
                {"外帘装袋", "布帘", "1.0", "true"},
                {"外帘装袋", "纱帘", "1.0", "true"},
                {"外帘装袋", "帘头", "1.0", "true"},
                {"质检", "布帘", "1.5", "true"},
                {"质检", "纱帘", "1.5", "true"},
                {"质检", "帘头", "1.5", "true"},
                {"外帘发货", "布帘", "1.0", "true"},
                {"外帘发货", "纱帘", "1.0", "true"},
                {"外帘发货", "帘头", "1.0", "true"},
                {"绑带", "布帘", "0.5", "true"},
                {"绑带", "纱帘", "0.5", "true"},
                {"绑带", "帘头", null, "false"},
                {"抱枕", "布帘", "2.0", "true"},
                {"抱枕", "纱帘", "2.0", "true"},
                {"抱枕", "帘头", "2.0", "true"},
                {"腰靠垫", "布帘", "2.0", "true"},
                {"腰靠垫", "纱帘", "2.0", "true"},
                {"腰靠垫", "帘头", "2.0", "true"},
                {"logo条", "布帘", "0.6", "true"},
                {"logo条", "纱帘", null, "false"},
                {"logo条", "帘头", null, "false"},
                {"立边", "布帘", "0.5", "true"},
                {"立边", "纱帘", null, "false"},
                {"立边", "帘头", null, "false"},
                {"扣环", "布帘", "0.3", "true"},
                {"扣环", "纱帘", null, "false"},
                {"扣环", "帘头", null, "false"},
                {"防翘扣", "布帘", "0.2", "true"},
                {"防翘扣", "纱帘", null, "false"},
                {"防翘扣", "帘头", null, "false"},
        };
        List<ProductionOperationPosition> plan = new ArrayList<>();
        for (String[] row : rows) {
            plan.add(ProductionOperationPosition.builder()
                    .id("opp-" + row[0] + "-" + row[1]).tenantId(tenantId)
                    .logicalName(row[0]).position(row[1])
                    .unitPrice(row[2] == null ? null : new BigDecimal(row[2]))
                    .applicable(Boolean.parseBoolean(row[3]))
                    .status("active").deleted(0).build());
        }
        return plan;
    }

    /** 旧结构的 9 条「(部位 × 工艺) 展开路线」冻结期望（真值源 routing.py::ROUTINGS 逐字快照）。 */
    public static final String[][] LEGACY_ROUTINGS = {
            {"布帘", "韩褶", "精裁-布,布三边,韩褶-布,上车布-布,熨烫-布,定型-布,复烫-布,布帘车被,外帘打卷,外帘装袋,外帘发货"},
            {"布帘", "打孔", "精裁-布,布三边,打孔-布,熨烫-布,定型-布,复烫-布,布帘车被,外帘打卷,外帘装袋,外帘发货"},
            {"布帘", "四爪钩", "精裁-布,布三边,上车布-布,熨烫-布,布帘车被,外帘打卷,外帘装袋,外帘发货"},
            {"布帘", "穿杆", "精裁-布,布三边,熨烫-布,布帘车被,外帘打卷,外帘装袋,外帘发货"},
            {"纱帘", "韩褶", "精裁-纱,纱三边,韩褶-纱,外帘打卷,外帘装袋,外帘发货"},
            {"纱帘", "打孔", "精裁-纱,纱三边,打孔-纱,外帘打卷,外帘装袋,外帘发货"},
            {"纱帘", "四爪钩", "精裁-纱,纱三边,上车布-纱,外帘打卷,外帘装袋,外帘发货"},
            {"纱帘", "穿杆", "精裁-纱,纱三边,外帘打卷,外帘装袋,外帘发货"},
            {"帘头", "平幔", "精裁-布,布三边,帘头制作,定型-布,外帘打卷,外帘装袋,外帘发货"},
    };

    // ══════════════════════════ 规则表 ══════════════════════════

    /**
     * 规则表 26 行（**逐条抄自 V71/V72 种子**）：工艺变体 10 + 特殊选项 16。
     * 字段序：{@code {trigger_kind, trigger_value, position|NULL, action, operation, after|NULL, priority}}。
     */
    private static final String[][] RULES = {
            {"craft", "韩褶", "NULL", "insert", "韩褶", "三边", "10"},
            {"craft", "韩褶", "布帘", "insert", "上车布", "韩褶", "20"},
            {"craft", "打孔", "NULL", "insert", "打孔", "三边", "30"},
            {"craft", "四爪钩", "NULL", "insert", "上车布", "三边", "40"},
            {"craft", "四爪钩", "NULL", "remove", "定型", "NULL", "50"},
            {"craft", "四爪钩", "NULL", "remove", "复烫", "NULL", "60"},
            {"craft", "穿杆", "NULL", "remove", "定型", "NULL", "70"},
            {"craft", "穿杆", "NULL", "remove", "复烫", "NULL", "80"},
            {"craft", "平幔", "NULL", "insert", "帘头制作", "三边", "90"},
            {"craft", "平幔", "NULL", "remove", "复烫", "NULL", "100"},
            {"option", "拼1次", "NULL", "insert", "拼1次", "三边", "110"},
            {"option", "拼2次", "NULL", "insert", "拼2次", "三边", "120"},
            {"option", "拼3次", "NULL", "insert", "拼3次", "三边", "130"},
            {"option", "加花边", "NULL", "insert", "花边", "三边", "140"},
            {"option", "加铅块", "NULL", "insert", "铅坠", "三边", "150"},
            {"option", "接高", "NULL", "insert", "接高", "精裁", "160"},
            {"option", "双眼皮接高", "NULL", "insert", "接高", "精裁", "170"},
            {"option", "余料做绑带", "NULL", "insert", "绑带", "车被", "180"},
            {"option", "布绑带", "NULL", "insert", "绑带", "车被", "190"},
            {"option", "余料做帘头", "NULL", "insert", "帘头制作", "三边", "200"},
            {"option", "抱枕", "NULL", "insert", "抱枕", "外帘打卷", "210"},
            {"option", "纱绑带", "NULL", "insert", "绑带", "车被", "220"},
            {"option", "加logo条", "NULL", "insert", "logo条", "三边", "230"},
            {"option", "加立边", "NULL", "insert", "立边", "三边", "240"},
            {"option", "扣环", "NULL", "insert", "扣环", "三边", "250"},
            {"option", "防翘扣", "NULL", "insert", "防翘扣", "三边", "260"}};

    /** 规则表（26 行；{@code id} 用 {@code rr-<priority>} 的确定性命名，保证 {@code (priority, id)} 稳定）。 */
    public static List<ProductionRouteRule> rules(Long tenantId) {
        List<ProductionRouteRule> rows = new ArrayList<>();
        for (String[] row : RULES) {
            rows.add(ProductionRouteRule.builder()
                    .id("rr-" + row[6]).tenantId(tenantId)
                    .triggerKind(row[0]).triggerValue(row[1])
                    .position("NULL".equals(row[2]) ? null : row[2])
                    .action(row[3]).operation(row[4])
                    .afterOperation("NULL".equals(row[5]) ? null : row[5])
                    .priority(Integer.valueOf(row[6]))
                    .status("active").deleted(0)
                    .build());
        }
        return rows;
    }

    /** 计件系数档（{@code action='factor'}；一分为二 → ×1.7 平摊档，V59/V72 种子）。 */
    public static List<ProductionRouteRule> factorRules(Long tenantId) {
        return List.of(ProductionRouteRule.builder()
                .id("rr-factor-1").tenantId(tenantId)
                .triggerKind("option").triggerValue("一分为二").position(null)
                .action("factor").operation(null).afterOperation(null)
                .priority(300).factor(new BigDecimal("1.7"))
                .status("active").deleted(0)
                .build());
    }

    /** 规则表 + 系数档（调用方多数场景要的就是这一份）。 */
    public static List<ProductionRouteRule> rulesWithFactors(Long tenantId) {
        List<ProductionRouteRule> rows = new ArrayList<>(rules(tenantId));
        rows.addAll(factorRules(tenantId));
        return rows;
    }

    // ══════════════════════════ 路线模板 ══════════════════════════

    /**
     * 默认路线模板（主线 9 道，适用 **布帘/纱帘**，{@code is_default=TRUE}）。
     *
     * <p>适用帘种刻意**不含帘头**：镜像旧桩的形态（旧桩只有 布帘×韩褶 / 布帘×打孔 / 纱帘×打孔
     * 三条路线 ⇒ 帘头订单走 T2 回落）。「该部位没有模板 ⇒ 回落默认模板」这条链由此可判。</p>
     */
    public static ProductionRouteTemplate defaultTemplate(Long tenantId) {
        return ProductionRouteTemplate.builder()
                .id("rt-default").tenantId(tenantId).name(TEMPLATE_NAME).isDefault(true)
                .positions(List.of("布帘", "纱帘"))
                .mainline(mainline())
                .status("active").deleted(0)
                .build();
    }

    /** 默认路线模板（适用**三部位**，parity 用例用：真实种子就是三部位共用一条主线）。 */
    public static ProductionRouteTemplate defaultTemplateAllPositions(Long tenantId) {
        return ProductionRouteTemplate.builder()
                .id("rt-default").tenantId(tenantId).name(TEMPLATE_NAME).isDefault(true)
                .positions(List.of("布帘", "纱帘", "帘头"))
                .mainline(mainline())
                .status("active").deleted(0)
                .build();
    }

    /** 布料路线模板（issue #4529）：`positions=["布料"]` / `mainline=["配料","打包"]` / 非默认。 */
    public static ProductionRouteTemplate fabricTemplate(Long tenantId) {
        return ProductionRouteTemplate.builder()
                .id("rt-fabric").tenantId(tenantId).name(FABRIC_TEMPLATE_NAME).isDefault(false)
                .positions(List.of(FABRIC_POSITION))
                .mainline(FABRIC_MAINLINE)
                .status("active").deleted(0)
                .build();
    }

    // ══════════════════════════ 归一（与生产同源的一份，仅供夹具用） ══════════════════════════

    /** 旧工序名 → 逻辑工序名（35 条；与 {@code routing.py::OPERATION_LOGICAL_NAMES} 逐字同源）。 */
    private static final Map<String, String> LOGICAL = logicalNames();

    public static String logicalName(String operationName) {
        return LOGICAL.getOrDefault(operationName, operationName);
    }

    public static Map<String, String> logicalNames() {
        Map<String, String> names = new LinkedHashMap<>();
        names.put("精裁-布", "精裁");
        names.put("精裁-纱", "精裁");
        names.put("裁剪-布", "裁剪");
        names.put("裁剪-纱", "裁剪");
        names.put("布三边", "三边");
        names.put("纱三边", "三边");
        names.put("韩褶-布", "韩褶");
        names.put("韩褶-纱", "韩褶");
        names.put("上车布-布", "上车布");
        names.put("上车布-纱", "上车布");
        names.put("打孔-布", "打孔");
        names.put("打孔-纱", "打孔");
        names.put("拼1次-布", "拼1次");
        names.put("拼2次-布", "拼2次");
        names.put("拼3次-布", "拼3次");
        names.put("花边-布", "花边");
        names.put("铅坠-布", "铅坠");
        names.put("接高-布", "接高");
        names.put("帘头制作", "帘头制作");
        names.put("熨烫-布", "熨烫");
        names.put("定型-布", "定型");
        names.put("复烫-布", "复烫");
        names.put("布帘车被", "车被");
        names.put("外帘打卷", "外帘打卷");
        names.put("外帘装袋", "外帘装袋");
        names.put("质检", "质检");
        names.put("外帘发货", "外帘发货");
        names.put("绑带-布", "绑带");
        names.put("抱枕", "抱枕");
        names.put("腰靠垫", "腰靠垫");
        names.put("绑带-纱", "绑带");
        names.put("logo条-布", "logo条");
        names.put("立边-布", "立边");
        names.put("扣环-布", "扣环");
        names.put("防翘扣-布", "防翘扣");
        return Map.copyOf(names);
    }

    /**
     * 逻辑工序名 + 部位 → 该租户库里的变体名（与生产 {@code ProductionOperationQueryService.variantNameOf}
     * 的三步规则**逐字同款**：部位后缀 → 帘头回落 {@code -布} → 裸逻辑名）。
     *
     * <p>⚠️ 夹具**必须**与生产同一套规则：否则「实例 = 库」的断言会退化成自证
     * （夹具换名 ⇒ 生产解析不到 ⇒ missing_operations ⇒ 假红）。规则本身的判据在
     * {@code ProductionOperationQueryServiceTest}（含 35 条旧名的往返判据）。</p>
     */
    public static String variantNameOf(String logicalName, String position,
                                Map<String, Map<String, Object>> catalogByName) {
        if (logicalName == null || catalogByName == null) {
            return null;
        }
        String suffix = "布帘".equals(position) ? "-布" : "纱帘".equals(position) ? "-纱"
                : "帘头".equals(position) ? "-帘" : null;
        if (suffix != null) {
            if (catalogByName.containsKey(logicalName + suffix)) {
                return logicalName + suffix;
            }
            String prefix = "布帘".equals(position) ? "布" : "纱帘".equals(position) ? "纱" : null;
            if (prefix != null && catalogByName.containsKey(prefix + logicalName)) {
                return prefix + logicalName;
            }
            if ("布帘".equals(position) && catalogByName.containsKey("布帘" + logicalName)) {
                return "布帘" + logicalName;
            }
            if (!"-布".equals(suffix) && catalogByName.containsKey(logicalName + "-布")) {
                return logicalName + "-布";
            }
        }
        return catalogByName.containsKey(logicalName) ? logicalName : null;
    }

    /** 工艺词表行（默认工艺桩用）。 */
    public static ProductionCraft defaultCraft(Long tenantId, String name) {
        return ProductionCraft.builder()
                .id("pc-default").tenantId(tenantId).name(name).isDefault(true)
                .status("active").deleted(0)
                .build();
    }
}
