package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 新路线模型的**只读**消费面（issue #4500 = 母单 #4423 的 P2c）：部位价目矩阵 + 规则区。
 *
 * <p>供 P3 前端（#4433）渲染「工序库的部位价目矩阵」与「统一规则区」—— 两个域的**读面**
 * 此前不存在（实测：规则/部位价目无端点），前端无数据可渲染。</p>
 *
 * <table>
 *   <caption>两个投影</caption>
 *   <tr><th>方法</th><th>数据源</th><th>形状</th><th>顺序</th></tr>
 *   <tr><td>{@link #operationPositions}</td><td>{@code production_operation_positions}（V71 84 行）</td>
 *       <td>{@code {operation, position, unit_price, applicable}}</td><td>{@code (operation, position)}</td></tr>
 *   <tr><td>{@link #routeRules}</td><td>{@code production_route_rules}（V71 26 条）</td>
 *       <td>10 键（见 {@code ruleView}）</td><td>{@code (priority, id)}</td></tr>
 * </table>
 *
 * <p><b>只读</b>：本类只有 SELECT，端点也只有 GET。写面（改价/增删规则）留 v1b —— 与「商家配置面
 * v1b」同批，不在 #4500。</p>
 *
 * <p><b>顺序为什么在 Java 侧显式排序</b>（不是 `ORDER BY`）：`logical_name` / `position` 是中文，
 * `ORDER BY` 的结果随 DB collation 变（C / en_US / ICU 三种排序各不相同）⇒ 同一份数据在不同环境
 * 得到不同顺序，前端每次刷新都可能换序。显式比较器把顺序钉成**环境无关**的确定值，且让
 * 「顺序」这条判据在单测里**可执行**（mocked mapper 返回乱序 ⇒ 断言可红）。</p>
 *
 * <p><b>行过滤只有三个条件</b>（租户 / 软删 / 停用）+ 规则表的 {@code action IN (insert, remove)}：
 * 任何额外的值过滤（如「只返回 applicable=true」）都会让矩阵/规则区**少行**，而「明确不做」
 * 与「没定价」必须在界面上可区分（#4433 判据 2）⇒ 84 格整份呈现。</p>
 *
 * <p><b>为什么 `action='factor'` 不在本端点</b>：V72 把旧 {@code production_option_factors} 的计件
 * 系数档搬进了同一张规则表（{@code action='factor'}），但那是**计件系数**（实例化路径消费），
 * 不是「工艺变体 ∪ 特殊选项」的路线编排规则（P3 统一规则区只呈现「插入 after X / 移除」）。
 * 混在一起会让 26 条口径失真、且形状里没有 {@code factor} 列可承载它。</p>
 *
 * <p><b>与实例化读面的关系</b>：{@code ProductionOperationQueryService}（P2b / issue #4459）也读这两张表
 * （{@code operationPositions} / {@code routeRules}），但那是**实例化用**的读面：返回**实体**、
 * 规则**不过滤** {@code action}（实例化需要 {@code factor} 计件系数档）、顺序交给 SQL {@code ORDER BY}。
 * 本类是**展示用**的读面，契约有三处不同，故不合并：① 形状 = issue #4500 冻结的键（规则项 10 键、
 * **不含** {@code factor}）；② 过滤 = 只呈现**路线编排档**（{@code insert}/{@code remove}，26 条口径）；
 * ③ 顺序 = Java 侧显式排序（见上，环境无关）。「怎么读这两张表」在 Mapper 层是同一条（同一组
 * 租户/软删/停用条件），差异只在投影 —— 合并会把「实例化契约」与「展示契约」耦成一处，
 * 任何一侧改口径都会静默改另一侧语义。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionRoutingReadService {

    /** 本端点呈现的规则动作 = 路线编排（{@code insert} / {@code remove}）。 */
    private static final List<String> ROUTE_ACTIONS = List.of("insert", "remove");

    /**
     * **套级**作用域取值（{@code production_operations.scope}，V67 / issue #4384 A1）——
     * 「每樘窗一次」。issue #4676 的**两层分区**判据就是它（设计 §4.2：用既有字段、不新造概念）。
     */
    private static final String SCOPE_SET = "set";

    private final ProductionOperationPositionMapper productionOperationPositionMapper;
    private final ProductionRouteRuleMapper productionRouteRuleMapper;
    /**
     * 工序库读面 —— **逻辑名 ↔ 变体名映射的唯一来源**（issue #4587 ①）。
     *
     * <p>为什么不在此另写一份推导：{@code variantNameOf} 已封装「帘头回落布帘变体」
     * （V54 的 {@code 帘头×平幔} 逐字引用 {@code 精裁-布}/{@code 布三边}）与「部位无关工序裸名兜底」
     * 两套口径；另写一份 ⇒ 前端看到的变体名与实例化算的工序**可能不是同一道**
     * （显示的单位/单价/必完全错，且没有任何东西会变红）。</p>
     */
    private final ProductionOperationQueryService productionOperationQueryService;
    /**
     * 加工项目录（issue #4616）：{@code trigger_kind='processing_item'} 的触发值取值域 ——
     * 规则创建弹窗要「按类型从对应词表取、不手输」，而加工项名**只有**目录这一份来源。
     */
    private final ProcessingItemMapper processingItemMapper;

    /**
     * 条件工序规则创建弹窗的**触发值取值域**（issue #4616）。
     *
     * <p>用户裁定：「现在的问题是**没有入口往条件工序规则中添加新的工艺和加工项**」。入口一开，
     * 弹窗的「触发值」就必须**按类型从对应词表取**（不手输）—— 手输一个词表里没有的名字 =
     * 建一条永远不命中的规则（商家以为配了、加工单上却没有）。</p>
     *
     * <p>{@code crafts} = 活跃工艺词表（{@code production_crafts}，此前**没有任何读端点**）；
     * {@code processing_items} = 活跃加工项目录（触发键 = 订单行的加工项名，精确相等）。
     * {@code options}（特殊选项）**不在此列** —— 选项名按现状**可新建**（没有第二份词表），
     * 前端给的是既有规则里出现过的选项名 + 允许手输。</p>
     *
     * @return {@code {crafts:[…], processing_items:[…]}}（零行 ⇒ 空数组，**不发明**默认值）
     */
    public Map<String, Object> triggerOptions(Long tenantId) {
        List<ProcessingItem> items = processingItemMapper.selectList(
                new LambdaQueryWrapper<ProcessingItem>()
                        .eq(ProcessingItem::getTenantId, tenantId)
                        .eq(ProcessingItem::getDeleted, 0)
                        .eq(ProcessingItem::getStatus, "active")
                        .orderByAsc(ProcessingItem::getName));
        List<String> processingItems = new ArrayList<>();
        if (items != null) {
            for (ProcessingItem item : items) {
                if (item.getName() != null && !processingItems.contains(item.getName())) {
                    processingItems.add(item.getName());
                }
            }
        }
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("crafts", productionOperationQueryService.activeCraftNames(tenantId));
        view.put("processing_items", processingItems);
        return view;
    }

    /**
     * 工序**一口价**列表（去部位化，issue #4883）：一道**逻辑工序** = 一行。
     *
     * <p>矩阵的物理键仍是 {@code (逻辑工序, 部位)}（V71 的种子行是三源收敛的冻结产物、
     * bootstrap 路径不跑迁移链 ⇒ 删行会让 bootstrap 与迁移链终态分叉）⇒ 本读面在**读时**
     * 按逻辑工序收敛为一行，收敛规则 = {@link ProductionOperationQueryService#collapseToLogical}
     * （与**实例化侧**、**补价侧**共用同一份实现，避免第二份口径漂移）。</p>
     *
     * @return 10 键/行（issue #4500 冻结 4 键 + issue #4587 追加 {@code id} 与 5 键变体元数据；
     *         issue #4622 去掉 {@code variant_name}），按 `logical_name` 稳定排序；
     *         收敛行的 `unit_price` 为 `null` ⇒ **未定价**（与「价 0 元」可区分）。
     *         变体查不到 ⇒ 5 键全 `null`（**不猜**）
     */
    public List<Map<String, Object>> operationPositions(Long tenantId) {
        List<ProductionOperationPosition> rows = productionOperationPositionMapper.selectList(
                new LambdaQueryWrapper<ProductionOperationPosition>()
                        .eq(ProductionOperationPosition::getTenantId, tenantId)
                        .eq(ProductionOperationPosition::getDeleted, 0)
                        .eq(ProductionOperationPosition::getStatus, "active"));
        List<ProductionOperationPosition> ordered =
                ProductionOperationQueryService.collapseToLogical(rows == null ? List.of() : rows);
        // 工序库一次取回、循环内复用（避免 N+1）：变体元数据的读取口径与实例化侧同一份
        Map<String, Map<String, Object>> catalog = productionOperationQueryService.operationsByName(tenantId);
        List<Map<String, Object>> items = new ArrayList<>();
        for (ProductionOperationPosition row : ordered) {
            items.add(positionView(row, variantName(row, catalog), catalog));
        }
        return items;
    }

    /**
     * **两层分区**（issue #4676 = 设计 {@code docs/design/public-operations-and-craft-ui.md} §3.2/§4.2；
     * 行来源修正 = issue #4729）：
     * 按**既有** {@code scope} 分区（**不新造概念**）——
     * {@code scope='set'} ⇒ {@code delivery}（打包发货：打包 / 打卷 / 装袋 / 发货）；
     * 其余（{@code 'position'} 或 {@code null}）⇒ {@code operations}（工序：裁剪 / 车位 / 后整 / 质检）。
     *
     * <p>⚠️ <b>分区判据是 {@code scope}，不是「有没有矩阵格」</b>：判据换成格 ⇒ 一道交付工序在
     * 某部位没有格时会**整行消失**（#4674 形态：表格里有、抽屉里空、无处可删）。</p>
     *
     * <p>🔴 <b>{@code delivery} 段的行来源 = 工序库的 {@code scope='set'} 行
     * （{@code production_operations}），<u>不是</u>矩阵行</b>（issue #4729 修正；独立验收 #4677 的 P1-2）：
     * 原实现遍历 {@link #operationPositions}（**只读矩阵表**）⇒ <b>零矩阵格</b>的套级工序在
     * {@code delivery} 段<b>一行都没有</b>（实测 {@code PROBE delivery operations = [打包]}）⇒
     * 该形态下【打包发货】层无行、无 {@code 管理▸}、抽屉打不开。设计要求（#4675 §7 第 7 条 /
     * #4677 四条约束）是「<b>第二层的行不依赖矩阵格</b>」—— 现状只在渲染层成立（前端手造行时才成立）。
     * 零格 ⇒ <b>仍有一行</b>，价态给 {@code no_applicable_position}（4 态之一，语义一字不改）。</p>
     *
     * <p>两段的<b>并集是全集</b>：{@code operations} = 矩阵行里<b>不属于</b>交付工序集合的那些
     * （含 {@code scope=null} 的安全方向 —— 变体查不到 ⇒ 落工序层，不落交付层）。</p>
     *
     * <p><b>交付环节的「一列价」= 显式规则（设计 §4.5 方案 A），绝不用「删格」实现</b> ——
     * 见 {@link #deliveryView}。删格会让该交付工序在缺格的部位单里**静默消失**
     * （{@code ProcessingOrderService.buildRoute}：{@code applicable == null ⇒ continue}）
     * ⇒ 少一道活、少一笔计件钱（设计 F1 红线）。</p>
     *
     * @return {@code {operations:[<10 键矩阵行，与 GET /operation-positions 同形>],
     *         delivery:[<9 键一列价行>]}}；两段都按 {@code operation} 稳定序（工序层复用
     *         {@link #operationPositions} 的排序；交付层按**归一后的逻辑工序名**排 —— 与矩阵行键
     *         同一把尺，不依赖 DB collation）
     */
    public Map<String, Object> operationLayers(Long tenantId) {
        List<Map<String, Object>> rows = operationPositions(tenantId);
        // 交付工序集合 = **工序库**的 `scope='set'` 行（归一为逻辑名 —— 与矩阵行键同一把尺）。
        // 一次取回、循环内复用（与 operationPositions 同一份目录读面，避免 N+1）。
        Map<String, Map<String, Object>> catalog = productionOperationQueryService.operationsByName(tenantId);
        Map<String, Map<String, Object>> deliveryCatalog = new LinkedHashMap<>();
        for (Map.Entry<String, Map<String, Object>> entry : catalog.entrySet()) {
            if (SCOPE_SET.equals(entry.getValue().get("scope"))) {
                deliveryCatalog.put(productionOperationQueryService.normalizeOperationName(entry.getKey()),
                        entry.getValue());
            }
        }
        // 矩阵格按**逻辑工序名**归拢（与上面同一把尺）；不属于交付工序集合的格落 `operations`
        Map<String, List<Map<String, Object>>> cellsByOperation = new LinkedHashMap<>();
        List<Map<String, Object>> operations = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            String operation = String.valueOf(row.get("operation"));
            if (deliveryCatalog.containsKey(operation)) {
                cellsByOperation.computeIfAbsent(operation, k -> new ArrayList<>()).add(row);
            } else {
                operations.add(row);
            }
        }
        List<Map<String, Object>> delivery = new ArrayList<>();
        deliveryCatalog.entrySet().stream()
                .sorted(Map.Entry.comparingByKey())
                .forEach(entry -> delivery.add(deliveryView(entry.getKey(),
                        cellsByOperation.getOrDefault(entry.getKey(), new ArrayList<>()),
                        entry.getValue())));
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("operations", operations);
        view.put("delivery", delivery);
        return view;
    }

    /**
     * 交付环节的**一列价**行（显式规则 = 设计 §4.5 方案 A：**保留矩阵格、在读面聚合成一列**）。
     *
     * <p>取值口径 = 该工序**所有 {@code applicable=TRUE} 格**的 {@code unit_price}，逐条规则：</p>
     * <ol>
     *   <li>全部相同 ⇒ {@code price_state="priced"} + {@code price=该价}；</li>
     *   <li>有 {@code NULL} ⇒ {@code price_state="unpriced"} + {@code price=null}
     *       —— <b>未定价 ≠ ¥0.00</b>，且**不得**回落工序库行价（设计 F4/U6：
     *       {@code production_operations.unit_price} 是 {@code NOT NULL DEFAULT 0} ⇒
     *       回落会把「未定价」变成「真 0 元」，工人白干）；</li>
     *   <li>不相同 ⇒ {@code price_state="multiple_prices"} + {@code price=null} +
     *       {@code different_price_count=不同价的个数}（**不静默取第一个**，设计 B7）；</li>
     *   <li>一格 {@code applicable=TRUE} 都没有 ⇒ {@code price_state="no_applicable_position"}。</li>
     * </ol>
     *
     * <p>⚠️ 本方法**只读矩阵格**（{@code production_operation_positions}）的**价**，**不读**
     * {@code production_operations.unit_price} —— 「工序库行价兜底」是**实例化路径**
     * （{@code ProcessingOrderService.buildRoute}）的既有语义，其触发条件是
     * 「格存在 + {@code applicable=TRUE} + 价 {@code NULL}」，且回落值是 **0**（设计 F4）。
     * 本层不复制那条兜底：读面的「未定价」必须与「¥0.00」可区分。</p>
     *
     * <p><b>零格（{@code cells} 为空）是正当形态</b>（issue #4729）：行由工序库给出（见
     * {@link #operationLayers}），该工序可能一个矩阵格都没有 ⇒ 仍出 9 键行、价态
     * {@code no_applicable_position}；行尾元数据（单位 / 分组 / 必完）回落**工序库行**
     * （{@code library}）—— 那是工序自身的元数据，不是价（价**绝不**回落，见上）。</p>
     *
     * @param library 该工序的工序库元数据（{@code scope='set'} 那一行）；格里的元数据优先，
     *                缺格时用它兜底（否则零格行的「单位 / 必完」全空 = 界面上多一列 `—`）
     */
    private Map<String, Object> deliveryView(String operation, List<Map<String, Object>> cells,
                                            Map<String, Object> library) {
        Set<BigDecimal> prices = new LinkedHashSet<>();
        List<String> applicablePositions = new ArrayList<>();
        boolean unpriced = false;
        for (Map<String, Object> cell : cells) {
            if (!Boolean.TRUE.equals(cell.get("applicable"))) {
                continue;
            }
            applicablePositions.add(String.valueOf(cell.get("position")));
            Object price = cell.get("unit_price");
            if (price == null) {
                unpriced = true;
            } else {
                prices.add(new BigDecimal(String.valueOf(price)));
            }
        }
        String priceState;
        BigDecimal price = null;
        if (applicablePositions.isEmpty()) {
            priceState = "no_applicable_position";
        } else if (unpriced) {
            priceState = "unpriced";
        } else if (prices.size() == 1) {
            priceState = "priced";
            price = prices.iterator().next();
        } else {
            priceState = "multiple_prices";
        }
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("operation", operation);
        view.put("scope", SCOPE_SET);
        view.put("unit", firstNonNull(cells, "unit", library, "unit"));
        view.put("group", firstNonNull(cells, "group", library, "group"));
        view.put("is_must_finish", firstNonNull(cells, "is_must_finish", library, "is_must_finish"));
        view.put("price", price);
        view.put("price_state", priceState);
        view.put("different_price_count", "multiple_prices".equals(priceState) ? prices.size() : 0);
        view.put("applicable_positions", applicablePositions);
        return view;
    }

    /**
     * 行尾元数据（{@code unit} / {@code group} / {@code is_must_finish}）取该工序**首个非 null** 的格；
     * 一格都没有（或格上全 null）⇒ 回落**工序库行**（issue #4729：零格行也要有单位 / 必完）。
     *
     * <p>各格不一致时逐个列出属**界面**口径（设计 §4.1 元素 5），不在本层发明第二套。</p>
     */
    private static Object firstNonNull(List<Map<String, Object>> cells, String key,
                                       Map<String, Object> library, String libraryKey) {
        for (Map<String, Object> cell : cells) {
            if (cell.get(key) != null) {
                return cell.get(key);
            }
        }
        return library == null ? null : library.get(libraryKey);
    }

    /**
     * **单行**展示形态（写面 {@code PUT /operation-positions/{id}} 的响应与读面**共用同一份** ——
     * 两处各拼一份必然漂移，而前端拿同一个 TS 类型渲染两者）。
     *
     * @param row 已带最新值的矩阵格（写面就地改过 {@code unitPrice}/{@code applicable}）
     */
    public Map<String, Object> positionRowView(Long tenantId, ProductionOperationPosition row) {
        Map<String, Map<String, Object>> catalog = productionOperationQueryService.operationsByName(tenantId);
        return positionView(row, variantName(row, catalog), catalog);
    }

    /** 该格实际落到**工人端那道工序**的变体名（查不到 ⇒ {@code null}，**不猜**）。 */
    private String variantName(ProductionOperationPosition row,
                               Map<String, Map<String, Object>> catalog) {
        return productionOperationQueryService.variantNameOf(
                row.getLogicalName(), row.getPosition(), catalog);
    }

    /**
     * 规则区：工艺变体 ∪ 特殊选项（**26 条** = 工艺 10 + 选项 16，母单 #4423 冻结数字）。
     *
     * @return 10 键（见 {@link #ruleView}），按 `(priority, id)` 稳定排序 ——
     *         **顺序敏感**（规则应用顺序决定工序序列），而 priority 撞档时「谁先」由 id 定
     */
    public List<Map<String, Object>> routeRules(Long tenantId) {
        List<ProductionRouteRule> rows = productionRouteRuleMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteRule>()
                        .eq(ProductionRouteRule::getTenantId, tenantId)
                        .eq(ProductionRouteRule::getDeleted, 0)
                        .eq(ProductionRouteRule::getStatus, "active")
                        .in(ProductionRouteRule::getAction, ROUTE_ACTIONS));
        List<ProductionRouteRule> ordered = rows == null ? new ArrayList<>() : new ArrayList<>(rows);
        ordered.sort(Comparator.comparing(ProductionRouteRule::getPriority)
                .thenComparing(ProductionRouteRule::getId));
        List<Map<String, Object>> items = new ArrayList<>();
        for (ProductionRouteRule row : ordered) {
            items.add(ruleView(row));
        }
        return items;
    }

    /**
     * 部位价目格展示形态（**唯一**的整形点）。
     *
     * <p>⚠️ {@code operation} 取 {@code logical_name}（**逻辑工序名**：精裁/三边/韩褶…），
     * **不是** {@code production_operations.name}（那边仍是旧名 精裁-布/布三边…）。矩阵的行键
     * 是逻辑名 —— 取错会让前端按 35 个旧名渲染出「一行一道工序」的旧形态。</p>
     *
     * <p><b>后 5 键 = 逻辑名 ↔ 变体工序的映射（issue #4587 ①，母单 #4586 的「中间那座桥」）</b>：
     * 每行回答「该逻辑工序 × 该部位**实际落到工人端的那道工序**是谁、单位/分组/作用域/必完是什么」。
     * 前端此前拿不到这层映射 ⇒ 不敢显示单位/单价/必完（主线 chips 上只有名字两套恰好一致的
     * {@code 外帘打卷} 才显示 {@code 套 · ¥1.00}，其余 6 道什么都不显示）。</p>
     *
     * <p>⚠️ <b>不返回变体名</b>（{@code variant_name}，issue #4622 = goal「web 面工序命名统一」阶段 3）：
     * 它是**当前**工序库的旧名（{@code production_operations.name}，如 {@code 布三边} / {@code 精裁-布}），
     * 而 web 面只用**一套工序名** = 逻辑工序名（{@code operation}）+ 部位（{@code position}）
     * ⇒ 该键**从响应里去掉**（不是「返回了但前端不渲染」—— 键在响应里就仍是 web 可见的旧口径）。
     * 逻辑名 ↔ 变体的**寻址**能力不减：{@code variant_operation_id} 仍在（抽屉的 {@code PUT/DELETE}
     * 与 provenance 按它定位），单位/分组/作用域/必完 4 键仍在。
     * ⚠️ 与 #4621 的「只加不改」裁定不冲突：那条针对**历史快照键**（{@code operation} /
     * {@code operation_name} = 工人端**当时**的快照名，历史读面必须保留），而本键是**当前**库口径。</p>
     *
     * <p>⚠️ 变体查不到（如 {@code logo条 × 纱帘} 在库里没有该变体）⇒ 5 键**全 null**，
     * 且键**必须保留**（前端按固定键集读；省掉键 = 前端渲染 undefined）。
     * {@code id}（issue #4587 追加）= 矩阵格自身的主键，是格内改价
     * {@code PUT /operation-positions/{id}} 的**寻址键**（不返回 ⇒ 改价无法落地）。</p>
     */
    private Map<String, Object> positionView(ProductionOperationPosition row, String variantName,
                                             Map<String, Map<String, Object>> catalog) {
        // 该格对应的工人端工序元数据（查不到 ⇒ null：不猜单位/不猜必完）
        Map<String, Object> variant = variantName == null ? null : catalog.get(variantName);
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", row.getId());
        view.put("operation", row.getLogicalName());
        view.put("position", row.getPosition());
        view.put("unit_price", row.getUnitPrice());
        view.put("applicable", row.getApplicable());
        view.put("variant_operation_id", variant == null ? null : variant.get("id"));
        view.put("unit", variant == null ? null : variant.get("unit"));
        view.put("group", variant == null ? null : variant.get("group"));
        view.put("scope", variant == null ? null : variant.get("scope"));
        view.put("is_must_finish", variant == null ? null : variant.get("is_must_finish"));
        return view;
    }

    /**
     * 规则项展示形态（**唯一**的整形点；`position` / `after_operation` 可为 null = 不限部位 / 追加末尾）。
     *
     * <p>{@code customer_unit_price}（V77，**元/套**）只对 {@code trigger_kind='option'} 的
     * **特殊选项**行有意义 —— 行业口径是「选项按**套**收费」（拼2次 / 防翘扣 一类）。
     * ⚠️ {@code NULL} = **未定价**，与 {@code 0}（定价为 0 元）是两件事：前端**不得**把它
     * 渲染成 {@code ¥0.00}（未定价 ≠ 0 元，仓库硬纪律）。非 {@code option} 行（{@code craft}
     * 等工艺变体）**一律** {@code NULL} —— 工艺变体不按套计价。</p>
     *
     * <p>本方法**不**做任何取价 / 回退：不读 {@code production_option_factors}、不做 contains
     * 匹配、不按 trigger_value 拼键 —— 值原样取自 {@code production_route_rules.customer_unit_price}。</p>
     */
    private Map<String, Object> ruleView(ProductionRouteRule row) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", row.getId());
        view.put("trigger_kind", row.getTriggerKind());
        view.put("trigger_value", row.getTriggerValue());
        view.put("position", row.getPosition());
        view.put("action", row.getAction());
        // 读时**归一**（issue #4643，与 #4632 的 `templateView` 同范式）：写面已归一新写入的值，
        // 但**存量行**可能是变体名（旧前端 / 脚本写进来的 `精裁-布`）⇒ 读面也必须兜住，
        // 否则界面照旧上屏变体名。只归一、**不写库**（库里仍可回溯当时存的是什么）、
        // 顺序与其它字段一字不动；归一表只有 `normalizeOperationName` 一份。
        view.put("operation", productionOperationQueryService.normalizeOperationName(row.getOperation()));
        view.put("after_operation",
                productionOperationQueryService.normalizeOperationName(row.getAfterOperation()));
        view.put("priority", row.getPriority());
        view.put("status", row.getStatus());
        view.put("customer_unit_price", row.getCustomerUnitPrice());
        return view;
    }
}
