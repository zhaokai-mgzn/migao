package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.MaterialLabels;
import com.migao.admin.dto.ProcessingOrderGenerateRequest;
import com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.entity.Supplier;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.SupplierMapper;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Duration;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.temporal.ChronoUnit;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;
import com.migao.admin.service.ProcessingRouteResolver.RouteKey;
import com.migao.admin.service.ProcessingRouteResolver.RouteResolution;
import static com.migao.admin.service.ProcessingOperationWeaver.processingItemNames;
import static com.migao.admin.service.ProcessingOperationWeaver.renumberSeq;
import static com.migao.admin.service.ProcessingOperationWeaver.specialOptions;

import static com.migao.admin.service.ProcessingOrderService.*;

/**
 * 加工单**部位 payload 构造**单元（issue #8725 第二档切片，从 {@link ProcessingOrderService} **纯搬运**）。
 *
 * <p><b>单一职责</b>：快照行 ⇒ 部位列表（部位名 / 定位键 / 工序序列）+ 逐工序应做数量（qty / qty_source），
 * 并把多部位的路线来源 roll-up 成一条（{@link #worstResolution} + {@link #severity}）。
 * <b>不写库</b>（唯一的外呼是算料引擎 {@link ProductionOperationQtyClient}，与切片前同一处、同一时点）。</p>
 *
 * <p>搬运口径：方法体、注释、异常码、日志文案**一字未改**。</p>
 */
class ProcessingPositionPayloadBuilder {

    /** 日志类别**必须**仍是 {@code ProcessingOrderService}：既有判据与运维告警按该 logger
     * 取事件（{@code ProcessingOrderRouteSourceTest} 就挂在它上面）—— 换类别 = 可观测面回退。*/
    private static final org.slf4j.Logger log =
            org.slf4j.LoggerFactory.getLogger(ProcessingOrderService.class);

    private final ProductionOperationQueryService productionOperationQueryService;
    private final ProductionOperationQtyClient productionOperationQtyClient;
    /** 路线解析（无状态；本类只消费它的派生键与路线）。 */
    private final ProcessingRouteResolver routeResolver;
    /** 条件工序编织（无状态）。 */
    private final ProcessingOperationWeaver weaver;

    ProcessingPositionPayloadBuilder(ProductionOperationQueryService productionOperationQueryService,
                                     ProductionOperationQtyClient productionOperationQtyClient) {
        this.productionOperationQueryService = productionOperationQueryService;
        this.productionOperationQtyClient = productionOperationQtyClient;
        this.routeResolver = new ProcessingRouteResolver(productionOperationQueryService);
        this.weaver = new ProcessingOperationWeaver(productionOperationQueryService);
    }


    /**
     * 实例化 payload：快照行 → 部位 → **工序库**里的基准工序序列 → **算料引擎**给出的应做数量。
     *
     * <p>部位名 = 加工产物名[+色号]（同行多套据此区分）—— 见类注释「部位语义」节：
     * 部位名落到产品名，而路线键由 {@link #deriveRouteKey} **直读**订单工艺规格（存量单才派生）。</p>
     *
     * <p><b>樘窗绑组（issue #4354 引入，issue #4387 语义扩展）</b>：{@code craftLineId} 标识
     * **同一樘窗（一个窗户）** —— 它是套级工序（#4384）与加工费樘窗级（#4386）的**归属层级**。
     * 部位 = {@code order_items} 行 = 一件帘（布帘 / 纱帘 / 帘头）⇒
     * **布行与纱行各自成部位**（同组不合并），只有 {@code componentRole=配布边} 的行
     * **不独立成部位**（否则一扇窗被算成两扇：褶数/开数/幅数/工序/计件全部翻倍）。
     * 组内只有配布边行时它仍自成部位（不静默丢窗）。</p>
     *
     * <p><b>定型开关（issue #4354，设计文档 §4.7）</b>：{@code isShaped=false} ⇒ 从基准序列里
     * 剔除 {@link #UNSHAPED_REMOVED_OPERATIONS}（真值源 §10 登记的「唯一尚未接线」项），
     * 与 {@code routing.py::build_routing} 同序（在条件工序插入之前）。</p>
     *
     * <p><b>应做数量（qty，issue #4208）</b>：库路线只给单位/单价，不给数量；数量的唯一真值源是
     * 算料引擎（{@code routing.py::_qty_for}），由 {@link ProductionOperationQtyClient} 逐部位问取。
     * 此前退化为**该部位的订单数量**（走查实测：一张数量=3 的加工单，11 道工序全显示 3.00 ⇒
     * 「韩褶-布」显示 **3 折**）—— 那是本单要治的缺陷，**已删除该回退**：算料服务不可用 ⇒
     * {@link ProductionOperationQtyClient#ERR_OPERATION_QTY_UNAVAILABLE} fail-closed 中止生成，
     * 绝不静默用订单数量顶替。</p>
     *
     * <p><b>不落 0</b>：缺键兜底 1 由端点负责（应做 0 ⇒ 报工的 {@code done_qty ≥ qty} 恒真 ⇒ 假完工）。</p>
     *
     * <p><b>{@code qty_source}</b>（实例表新增列）：逐工序记录口径来源（键名 = 算料输出 /
     * {@code <键名>_x6} = 有依据的估算 / {@code fallback} = 真兜底），供页面与排查区分
     * 「算料输出」与「兜底」—— 兜底不再静默。</p>
     */
    @SuppressWarnings("unchecked")
    PositionPayload buildPositionPayload(List<Map<String, Object>> snapshot, Long tenantId) {
        List<Map<String, Object>> positions = new ArrayList<>();
        // 与 positions **同序**：回填 qty/qty_source 时按位取，不靠部位名（同商品同色号的两行会重名）
        List<List<Map<String, Object>>> operationRows = new ArrayList<>();
        List<Map<String, Object>> request = new ArrayList<>();
        // 多部位 roll-up 用（V60）：逐部位记 (route_key, route_source)，最后取最需关注的一条
        List<RouteResolution> resolutions = new ArrayList<>();
        // 新结构读面（P2b，issue #4459）：规则表 / 部位价目 / 工序库都极小，**一次取回**本租户的
        // 全部活跃行，逐部位在内存里过滤 —— 避免「每道工序一次查询」的 N+1。
        // 规则表里历史遗留的 `action='factor'` 计件系数档**已无消费者**（issue #4589：系数退场），
        // 新迁移已把它们软删；本方法只按 `insert`/`remove` 构造序列。
        List<ProductionRouteRule> rules = productionOperationQueryService.routeRules(tenantId);
        List<ProductionOperationPosition> priceRows =
                productionOperationQueryService.operationPositions(tenantId);
        Map<String, Map<String, Object>> catalog =
                productionOperationQueryService.operationsByName(tenantId);
        // 樘窗绑组（issue #4354 引入，issue #4387 语义扩展）：组键 = `craftLineId`（缺省 ⇒ 本行 itemId ⇒ 各自成组）
        Set<String> groupsWithMainRow = groupsWithMainRow(snapshot);
        // 套级工序的承载体（issue #4384 A2）：每个樘窗组只挑一行（主布行）—— 见 setLevelKeeperItemIds
        Set<String> setLevelKeepers = setLevelKeeperItemIds(snapshot, groupsWithMainRow);
        for (Map<String, Object> entry : snapshot) {
            if (!(entry.get("processingItems") instanceof List<?>)) {
                continue;
            }
            if (isAbsorbedEdgeRow(entry, groupsWithMainRow)) {
                // 配布边行并入同组的主布部位 ⇒ **不独立成部位**（否则一扇窗被算成两扇：
                // 褶数/开数/幅数/工序/计件全部翻倍）。该行自身的货号/米数仍在快照里可展示。
                continue;
            }
            // 本行是否承载所在樘窗的套级工序（= 该组的主布行）。
            // `itemId` 恒非空（`buildSnapshot` 无条件落 `order_items.id` = 主键）⇒ 用它做承载标识。
            boolean keepsSetLevel = setLevelKeepers.contains(str(entry.get("itemId")));
            RouteKey key = routeResolver.deriveRouteKey(entry, tenantId);
            RouteResolution resolution = routeResolver.resolveRoute(key, tenantId, entry, rules, priceRows, catalog);
            resolutions.add(resolution);
            Map<String, Object> route = resolution.route();
            List<Map<String, Object>> operations = new ArrayList<>();
            for (Map<String, Object> step : (List<Map<String, Object>>) route.get("operations")) {
                // 套级工序（issue #4384 A2）：同一樘窗只落一次（挂该组主布行的部位名）。
                // 判据 = 库里带出的 `scope`（逐字取库）——**不硬编码工序名**（商家改了库要生效）。
                if (!keepsSetLevel && SCOPE_SET.equals(str(step.get("scope")))) {
                    continue;
                }
                Map<String, Object> operation = new LinkedHashMap<>();
                // ⚠️ `operation` = **工人端快照名**（变体名 `精裁-布`）：历史数据与其它消费者仍要读它，
                // **一字不动**；**web 界面不得渲染该键**（issue #4621）—— 界面显示下面的
                // `logical_name` + `position`（读时派生、**不写库**）。
                operation.put("operation", step.get("operation"));
                // 显示名派生键**从路线步骤逐字带出**（不在此另推一份 ⇒ 不会与路线读面漂移）
                operation.put("logical_name", step.get("logical_name"));
                operation.put("position", step.get("position"));
                // 分组/单位/单价/开始标记**逐字取库**（不猜、不补默认值）。
                // 🔴 `is_must_finish` **不再带出**（#4961）：概念已退场 ⇒ payload 里去掉该键
                // （实例化侧 parseSpecs 也不再读它；列保留为历史载体，见 V107 迁移）。
                operation.put("group", step.get("group"));
                operation.put("unit", step.get("unit"));
                operation.put("unit_price", step.get("unit_price"));
                operation.put("is_start_marker", step.get("is_start_marker"));
                operations.add(operation);
            }
            // 定型接线（issue #4354，设计文档 §4.7）：`isShaped=false` ⇒ 剔除 定型 / 复烫
            // （真值源 §10 登记的「唯一尚未接线」项）。**严格布尔 false** 才生效，且必须在条件工序
            // 插入**之前** —— 与 routing.py::build_routing 逐字同序（否则以这两道为锚点的条件工序
            // 会因锚点消失而落到末尾，与 Python 的落位不一致）。
            // P2b（issue #4459）：判据从旧工序名（定型-布/复烫-布）换成**逻辑名**（定型/复烫）——
            // 新结构里序列元素就是逻辑名。新模型给 `shaped` 预留了规则触发类型但**不种行**，
            // 故本开关仍是代码侧接线（与 routing.py::build_route_v2 的现状一致）。
            if (Boolean.FALSE.equals(entry.get("isShaped"))) {
                // 判据用**逻辑名**比较：实例里的工序名是库里的**变体名**（定型-布/复烫-布），
                // 而新结构的序列元素是逻辑名（定型/复烫）⇒ 比较前先归一。
                operations.removeIf(operation -> UNSHAPED_REMOVED_OPERATIONS.contains(
                        productionOperationQueryService.normalizeOperationName(
                                String.valueOf(operation.get("operation")))));
            }
            // 特殊选项（issue #4230）/ 加工项（issue #4577）：插条件工序 → 重排 seq → 落计件系数
            List<String> options = specialOptions(entry);
            List<String> processingItems = processingItemNames(entry);
            // ⚠️ 部位取**实际使用路线**的部位（`route.curtain_type`），不是 `entry.curtainType`：
            // 派生路径下 entry 可能没有该键（存量单），而 T2 回落时实际部位是默认模板的部位
            // ⇒ 拿 entry 的值会让「逻辑名 → 变体名」解析不到（部位为 null）⇒ 条件工序误判为缺工序。
            String routePositionOfEntry = str(route.get("curtain_type"));
            if (!options.isEmpty() || !processingItems.isEmpty()) {
                weaver.insertConditionalOperations(operations, options, processingItems, rules, tenantId, entry,
                        catalog, routePositionOfEntry);
            }
            renumberSeq(operations);
            String productName = str(entry.get("productName"));
            String colorName = str(entry.get("colorName"));
            String positionName = productName == null ? "未命名部位"
                    : (colorName == null ? productName : productName + " " + colorName);
            Map<String, Object> position = new LinkedHashMap<>();
            position.put("position_name", positionName);
            // 主定位键（V69，issue #4388 / #4373 裁定）：`order_item_id` = 该快照行对应的 order_items 行，
            // `position_kind` = 可读定位（哪一件帘）。`position_name` 是**展示名**，同商品同色号的两个窗
            // 会同名 ⇒ 只有这一对键能唯一定位实例（读面分组、算料按行取、报工/计件归属都靠它）。
            position.put("order_item_id", str(entry.get("itemId")));
            position.put("position_kind", str(entry.get("curtainType")));
            position.put("operations", operations);
            positions.add(position);
            operationRows.add(operations);
            request.add(qtyRequest(entry, positionName, operations));
        }
        if (positions.isEmpty()) {
            return new PositionPayload(positions, null, null, null);
        }
        fillQty(positions, operationRows, request);
        RouteResolution worst = worstResolution(resolutions);
        return new PositionPayload(positions,
                worst == null ? null : worst.routeKey(),
                worst == null ? null : worst.routeRequestedKey(),
                worst == null ? null : worst.routeSource());
    }




    /**
     * 樘窗绑组（issue #4354 引入，issue #4387 语义扩展）：同一樘窗（一个窗户）的多行用
     * {@code craftLineId} 绑成一组；组键只用于判定**配布边行**是否可被吸收 ——
     * **不是**「组内只保留一个部位」（布行 + 纱行同组时各成一个部位，见
     * {@link #buildPositionPayload} 的「樘窗绑组」节）。
     *
     * <p><b>组键</b> = 本行 {@code craftLineId}；缺省 ⇒ 本行 {@code itemId}。
     * 后者让「配布边行填**主布行的行标识**」（order_create 工具描述教的形态）也能对齐 ——
     * 两个不同行的 {@code itemId} 天然不等 ⇒ **没有 {@code craftLineId} 的行永远各自成组**，
     * 即「缺键时行为逐字不变」（存量单兼容）。</p>
     *
     * @return 组内**存在**可作主布的行（有加工项且角色非 {@link #COMPONENT_ROLE_EDGE}）的组键集合
     */
    static Set<String> groupsWithMainRow(List<Map<String, Object>> snapshot) {
        Set<String> groups = new LinkedHashSet<>();
        for (Map<String, Object> entry : snapshot) {
            if (!(entry.get("processingItems") instanceof List<?>) || isEdgeRow(entry)) {
                continue;
            }
            String groupKey = craftGroupKey(entry);
            if (groupKey != null) {
                groups.add(groupKey);
            }
        }
        return groups;
    }


    /**
     * 该行是否被同组的主布部位**吸收**（⇒ 不独立成部位）。
     *
     * <p>只吸收 {@code componentRole=配布边} 的行：{@code 纱} 是**独立部位**（纱帘），
     * 与主布同组时仍须各成部位。组内若只有配布边行（主布行缺加工项 / {@code craftLineId} 悬空），
     * 它**必须**自己成部位 —— 静默丢掉会让整扇窗没有工序（比双算更糟：工人拿不到工钱）。</p>
     */
    static boolean isAbsorbedEdgeRow(Map<String, Object> entry, Set<String> groupsWithMainRow) {
        if (!isEdgeRow(entry)) {
            return false;
        }
        String groupKey = craftGroupKey(entry);
        return groupKey != null && groupsWithMainRow.contains(groupKey);
    }


    /** 是否「配布边」部件行（缺省角色视为主布 ⇒ 不是配布边，存量单兼容）。 */
    static boolean isEdgeRow(Map<String, Object> entry) {
        return COMPONENT_ROLE_EDGE.equals(str(entry.get("componentRole")));
    }


    /** 绑组键：{@code craftLineId} 优先，缺省回落到本行 {@code itemId}（两者都缺 ⇒ null = 不参与绑组）。 */
    static String craftGroupKey(Map<String, Object> entry) {
        String craftLineId = str(entry.get("craftLineId"));
        return craftLineId != null ? craftLineId : str(entry.get("itemId"));
    }


    /**
     * 套级工序（{@code scope='set'}）的**承载体**：每个樘窗组只挑一行（issue #4384 **A2**）。
     *
     * <p>挑法与写侧（#4395 的 {@code resolveWindowCraftLineIds}）**同口径**：组内**第一条
     * `curtainType=布帘`** 的行（= 主布行 —— §4.8 的 `craftLineId` 口径、§5.6 R-b 的加工费也落它）；
     * 组内没有布帘（纱 + 帘头）⇒ 取**组内首行**（不猜、不丢组：静默丢组会让整樘窗没有套级工序）。</p>
     *
     * <p>只考虑**会变成部位的行**：被吸收的配布边行与无加工项的行在实例化循环里被 {@code continue}
     * 跳过 ⇒ 它们不能承载套级工序（否则套级工序会落在不存在的部位上 = 静默丢失）。</p>
     *
     * <h2>为什么挂主布行，而不是新增一个「外帘」部位行（设计裁定）</h2>
     * <ol>
     *   <li><b>部位计数口径</b>：部位 = 一行 {@code order_items}（R-a）⇒ 新增「外帘」行会让
     *       `positions` 数变成「部位数 + 1」，订单/看板/加工单按部位数展示的地方全部对不上；</li>
     *   <li><b>存量单兼容</b>：新增行会让**每一个**单行樘窗（存量单的绝大多数）多一行 ⇒
     *       与判据「不属于樘窗组 / 单行自成一组 ⇒ 行为逐字不变」冲突；</li>
     *   <li><b>先例</b>：樘窗级的东西落该组**主布行**（§5.6 R-b：加工费按樘窗一条、落主布行）；</li>
     *   <li><b>真值源 §8 的「外帘是加工单<u>打印行部位</u>」是打印粒度要求</b> ⇒ 归 #4388
     *       （定位键 {@code (order_item_id, position_kind)} + 打印粒度）；本单边界明确排除定位键；</li>
     *   <li><b>工人扫码端仍看得到</b>：扫码/详情/报工读的是**工序行**，按 {@code position_name}
     *       分组（{@code ProductionService.buildPositions}）⇒ 套级工序挂在主布行部位名下照样可见可报工。</li>
     * </ol>
     *
     * @return 各组承载体行的 {@code itemId} 集合（空快照 / 全是被吸收行 ⇒ 空集）
     */
    static Set<String> setLevelKeeperItemIds(List<Map<String, Object>> snapshot,
                                                     Set<String> groupsWithMainRow) {
        Map<String, List<Map<String, Object>>> byGroup = new LinkedHashMap<>();
        for (Map<String, Object> entry : snapshot) {
            if (!(entry.get("processingItems") instanceof List<?>) || isAbsorbedEdgeRow(entry, groupsWithMainRow)) {
                continue;
            }
            // 组键恒非空（`itemId` = order_items 主键，`buildSnapshot` 无条件落）⇒ 不存在「不参与绑组」的行；
            // 万一为空（脏快照）⇒ 该行自成一樘窗（键用行标识兜底），**不静默并组**。
            String groupKey = craftGroupKey(entry);
            byGroup.computeIfAbsent(groupKey == null ? "item:" + str(entry.get("itemId")) : groupKey,
                    k -> new ArrayList<>()).add(entry);
        }
        Set<String> keepers = new LinkedHashSet<>();
        for (List<Map<String, Object>> group : byGroup.values()) {
            Map<String, Object> keeper = group.stream()
                    .filter(row -> CURTAIN_TYPE_CLOTH.equals(str(row.get("curtainType"))))
                    .findFirst()
                    .orElse(group.get(0));
            String itemId = str(keeper.get("itemId"));
            if (itemId != null) {
                keepers.add(itemId);
            }
        }
        return keepers;
    }


    /** 多部位 roll-up：取最需关注的一条（{@link #severity}），同档取先出现者。 */
    static RouteResolution worstResolution(List<RouteResolution> resolutions) {
        RouteResolution worst = null;
        for (RouteResolution resolution : resolutions) {
            if (worst == null || severity(resolution.routeSource()) > severity(worst.routeSource())) {
                worst = resolution;
            }
        }
        return worst;
    }


    /** 部位派生 payload + 落库用的路线键/来源（V60，issue #4308）。 */
    record PositionPayload(List<Map<String, Object>> positions, String routeKey,
                                   String routeRequestedKey, String routeSource) {
    }


    /**
     * 算料请求体里的单个部位（与 ai-agent 端点冻结契约同构）。
     *
     * <p>{@code order_item_id}（V69，issue #4388）是**额外**键：端点模型（pydantic 默认 `extra` 忽略）
     * 不会因它报错，但**也不会回显** ⇒ 今天只用于「请求自描述 + 排查」（谁的数量是谁的），
     * 以及将来引擎回显后可改成按行匹配。**本单不改 ai-agent**（边界：Agent 层另单）。</p>
     */
    Map<String, Object> qtyRequest(Map<String, Object> entry, String positionName,
                                           List<Map<String, Object>> operations) {
        List<String> names = new ArrayList<>(operations.size());
        for (Map<String, Object> operation : operations) {
            names.add(String.valueOf(operation.get("operation")));
        }
        Map<String, Object> position = new LinkedHashMap<>();
        position.put("position_name", positionName);
        position.put("order_item_id", str(entry.get("itemId")));
        position.put("operations", names);
        position.put("calc_info", calcInfo(entry));
        return position;
    }


    /**
     * 算料输入（issue #4208 Java 接线；米数判据先由 issue #4299 更正为**加工项** {@code pricingMethod}，
     * 再由 issue #4882 改为 {@link #isMeterBasedLine} 的**三段契约**）。
     *
     * <p><b>三层字段别混</b>（#4299 真库实测钉死，见 {@code acceptance/2026-09-18/4299-db-distribution/FINDINGS.md}）：</p>
     * <ul>
     *   <li>{@code sellingMethod} = <b>售卖方式</b>（真库取值：{@code bulk_cut} / {@code 散剪} /
     *       {@code full_roll} / {@code 整卷} / {@code 散剪售卖} / {@code 散剪按米} / {@code 散剪·按米购买} /
     *       {@code 散剪(bulk_cut)} / {@code cut} / {@code 散剪（按米裁剪）} / 无）—— <b>不是数量口径的来源</b>；
     *       {@code per_meter} 在该字段里一次都没出现过 ⇒ 拿它当判据<b>永不命中</b>（#4299 的病根）。</li>
     *   <li>加工项 {@code pricingMethod} = <b>加工项计价方式</b>（{@code per_meter} / {@code per_set} /
     *       {@code fixed} / {@code per_area}…）—— <b>订单行数量口径由它决定</b>，故 #4299 起它是判据字段
     *       （当时可达面 68 条订单行里命中 67 条）。⚠️ <b>#4882 起加工项目录已删该列</b> ⇒ 该键此后只可能
     *       出现在**存量订单快照**里（新单不再写），新单按「有加工项即米类」判 —— 见 {@link #isMeterBasedLine}。</li>
     *   <li>{@code products.pricing_type} = <b>商品</b>计价方式 —— 与订单行口径<b>不是同一层</b>：
     *       实测按它会漏 18/68 条（11 条商品缺失/软删 + 6 条 {@code pricing_type=fixed} 而其加工项仍按米）。</li>
     * </ul>
     * <p>{@code per_meter} 与「按米」是<b>加工项计价方式</b>的词汇，历史上被误当成售卖方式词表 ——
     * 同族混淆见前端展示表（{@code OrderDetail.tsx} / {@code OrderItemList.tsx} 把 {@code per_meter: '按米'}
     * 放进了 {@code sellingMethod} 的映射表）。</p>
     *
     * <p><b>#4882 登记：目录已无计价方式 ⇒ 新单按「有加工项即米类」</b>。用户裁定彻底删除
     * 「加工项单价」与「加工项计价方式」（{@code processing_items.pricing_method} / {@code unit_price} 两列），
     * 故判据不能再依赖目录。**有意取舍**（不是遗漏）：<b>存量无键老数据</b>的判定由「不命中」翻转为
     * 「命中米类」，理由 = #3005 行业口径（行业加工费按米计价、辅料含在加工费中）+ V83 目录 16 项
     * 历史上**全部** {@code per_meter}；翻转的代价只是「按订单行 quantity 当米数」，而不翻转的代价是
     * 米类工序兜底 1 ⇒ **假完工**（#4208 红线）。存量快照里**带** {@code pricingMethod} 键的行仍按原语义判
     * —— 含真库那条 {@code per_sqm} 刺绣散剪单的负例，不得冒充米数。</p>
     *
     * <p><b>取值</b>：命中时取<b>订单行</b> {@code quantity}（{@code OrderItem.quantity} javadoc：per_meter=米数），
     * <b>不</b>取加工项自己的 {@code quantity} —— 实测订单行 {@code 7e6f2a1c…} 订单数量 112.00
     * 而其 {@code per_meter} 加工项 quantity=1，取后者会让 112 米的单得到「应做 1 米」⇒ 报工上限 1 ⇒ 假完工。</p>
     *
     * <p><b>已知缺口（#4118，不是本方法缺陷）</b>：订单侧**从不落库算料输出** ⇒
     * {@code pleat_count}（褶数）/ {@code panels}（幅）/ {@code set_count}（套）/ {@code holes}（孔）
     * 一律取不到 ⇒ 端点在缺键时兜底 1 并在 {@code qty_source} 标 {@code fallback}。
     * 真正修法是**下单时把算料输出落库**（#4118「实际褶倍算了就丢」），届时本方法只需把透传白名单
     * 扩到那几个键即可 —— 请勿把它当 bug 反复排查。</p>
     */
    Map<String, Object> calcInfo(Map<String, Object> entry) {
        Map<String, Object> calc = new LinkedHashMap<>();
        // ① 订单侧若已存算料输出（键名与 routing.py 的 METER_KEYS/FOLD_KEYS/… 同口径）⇒ 原样透传
        for (String key : CALC_INFO_KEYS) {
            Object value = entry.get(key);
            if (value != null) {
                calc.put(key, value);
            }
        }
        // ①b 整卷出库（issue #7523）：快照键是 camelCase `rollCount`，算料口径键是 `roll_count`
        //     （与 routing.py::ROLL_KEYS 逐字同源）。缺键 ⇒ 不落（Python 侧兜底 1，绝不落 0）。
        Object rollCount = entry.get("rollCount");
        if (rollCount != null) {
            calc.put("roll_count", rollCount);
        }
        // ② 该订单行是米类（判据见 isMeterBasedLine 的三段契约）⇒ 订单行数量即米数
        if (!calc.containsKey("fabric_meters") && isMeterBasedLine(entry)) {
            Object quantity = entry.get("quantity");
            if (quantity != null) {
                calc.put("fabric_meters", quantity);
            }
        }
        // ③ 卖布行（`saleForm = 布料`，issue #4909）：按米卖布、行上**没有加工项** ⇒ ② 永不命中
        //    （`isMeterBasedLine` 第 1 段对「processingItems 缺失」判 false），而这一行的部件维是
        //    「布料」、走**布料基础路线**（V88 终态 `裁剪 → 打包`）⇒ 米类工序（裁剪）必须有米数。
        //    缺这一步 ⇒ 端点按缺键兜底 1（`qty_source=fallback`，与「算料服务没答」不可区分）
        //    ⇒ 10 米的布单只做 1 米、计件按 1 米算 —— 正是 #4208 红线要治的形态。
        //    取法与 ② 同源（**订单行 quantity 即米数**），不新增第二份口径；数量 ≤ 0（脏数据）
        //    时**不落键**：「绝不落 0」是端点的硬不变量（应做 0 ⇒ `done_qty ≥ qty` 恒真 ⇒ 假完工）。
        if (!calc.containsKey("fabric_meters") && isFabricSaleLine(entry)) {
            Object quantity = entry.get("quantity");
            if (quantity != null && new BigDecimal(String.valueOf(quantity)).signum() > 0) {
                calc.put("fabric_meters", quantity);
            }
        }
        return calc;
    }


    /**
     * 该订单行是否是**米类**（{@code calc_info.fabric_meters} 取订单行 {@code quantity} 的判据）。
     *
     * <p>判据按 issue #4882 的**三段契约**（逐条实现，勿简化）：</p>
     * <ol>
     *   <li>{@code processingItems} 缺失 / 非 {@code List} / 为空 ⇒ {@code false}（老数据与脏数据形态，不猜）；</li>
     *   <li>若**任一项显式带 {@code pricingMethod} 键**（= 存量订单快照形态）：存在 {@code "per_meter"}
     *       ⇒ {@code true}；所有带键项都不是 {@code "per_meter"} ⇒ {@code false}
     *       —— <b>这条负例必须保住</b>：真库有一条刺绣工艺 {@code per_sqm} 的散剪单，
     *       它的订单行 quantity 不是米数，不得冒充米数（#4299 实测，order_item {@code 286229cf…}）；</li>
     *   <li>若**一项都不带 {@code pricingMethod} 键**（= #4882 之后的新单：加工项目录已无计价方式，
     *       下单入口不再写该键）⇒ {@code true}（#3005 行业口径：行业加工费**按米计价**、辅料含在加工费中；
     *       V83 目录 16 项历史上全部 {@code per_meter}）。</li>
     * </ol>
     *
     * <p><b>有意取舍（登记，不是遗漏）</b>：第 3 段把**存量无键老数据**的判定由「不命中」翻转为
     * 「命中米类」。方向是刻意的 —— 不翻转的后果是米类工序落 {@code qty_source=fallback} 兜底 1
     * ⇒ 112 米的单做 1 米 ⇒ **假完工**（#4208 红线），翻转的后果只是「按订单行 quantity 当米数」。
     * 详见 {@link #calcInfo}。</p>
     *
     * <p>不看售卖方式 {@code sellingMethod}、也不看商品级 {@code pricing_type} ——
     * 理由与实测数字见 {@link #calcInfo}。</p>
     */
    static boolean isMeterBasedLine(Map<String, Object> entry) {
        Object raw = entry.get("processingItems");
        if (!(raw instanceof List<?> items) || items.isEmpty()) {
            return false;   // ① 缺失 / 非 List / 空
        }
        boolean anyExplicitKey = false;
        for (Object item : items) {
            if (item instanceof Map<?, ?> proc && proc.containsKey("pricingMethod")) {
                anyExplicitKey = true;                          // ② 存量快照形态
                if ("per_meter".equals(str(proc.get("pricingMethod")))) {
                    return true;
                }
            }
        }
        return !anyExplicitKey;                                 // ③ 全无该键 ⇒ 新单 ⇒ 米类
    }


    /**
     * 用算料引擎的返回回填 {@code qty} 与 {@code qty_source}。
     *
     * <p>fail-closed 的三个细节：① 端点返回条数与请求不符 ⇒ 客户端已抛错（不在此处补位）；
     * ② 端点漏答某道工序（契约外形态）⇒ 同样抛错，**不**替它兜底 1 ——
     * 静默补值会让「算料服务没答」与「算料服务答了兜底 1」长得一模一样；
     * ③ <b>身份校验（issue #4388）</b>：条数相同 ≠ 对得上 —— 响应必须**指回请求里的那个部位**
     * （引擎契约是纯映射、保序；本断言把「靠数组位次对齐」从**隐含假设**变成**显式契约**）⇒
     * 一旦引擎重排/串位，是**显式失败**而不是把 A 窗的数量写到 B 窗上（静默错配 = 本仓最大失败模式）。</p>
     *
     * <p>⚠️ <b>已知边界（登记在 PR）</b>：引擎响应只回 {@code position_name}，**不回显行标识**
     * ⇒ **同名**部位之间仍无法靠身份区分（本断言对它们恒成立）。真正的按 {@code order_item_id}
     * 取值需要 ai-agent 端回显该键（属 Agent 侧改动，跟随单）。</p>
     */
    void fillQty(List<Map<String, Object>> positions,
                         List<List<Map<String, Object>>> operationRows,
                         List<Map<String, Object>> request) {
        List<ProductionOperationQtyClient.PositionQty> resolved = productionOperationQtyClient.resolve(request);
        if (resolved.size() != positions.size()) {
            throw new BusinessException(ProductionOperationQtyClient.ERR_OPERATION_QTY_UNAVAILABLE,
                    "算料服务返回的部位数（" + resolved.size() + "）与请求（" + positions.size() + "）不符，已中止生成加工单",
                    422,
                    "请确认 ai-agent-service 版本与 admin-api 契约一致后重新生成加工单");
        }
        for (int i = 0; i < positions.size(); i++) {
            ProductionOperationQtyClient.PositionQty answered = resolved.get(i);
            String requestedName = String.valueOf(request.get(i).get("position_name"));
            if (!requestedName.equals(answered.positionName())) {
                throw new BusinessException(ProductionOperationQtyClient.ERR_OPERATION_QTY_UNAVAILABLE,
                        "算料服务返回的部位身份与请求不符（第 " + (i + 1) + " 个：请求「" + requestedName
                                + "」，响应「" + answered.positionName() + "」），已中止生成加工单（不静默错配）",
                        422,
                        "请确认 ai-agent-service 版本与 admin-api 契约一致后重新生成加工单");
            }
            for (Map<String, Object> operation : operationRows.get(i)) {
                String name = String.valueOf(operation.get("operation"));
                BigDecimal qty = answered.qtyByOperation().get(name);
                if (qty == null) {
                    throw new BusinessException(ProductionOperationQtyClient.ERR_OPERATION_QTY_UNAVAILABLE,
                            "算料服务未返回工序「" + name + "」的应做数量，已中止生成加工单（不静默兜底）",
                            422,
                            "请确认 ai-agent-service 的算料端点已登记该工序的单位后重新生成加工单");
                }
                operation.put("qty", qty);
                operation.put("qty_source", answered.qtySourceByOperation().get(name));
            }
        }
    }


    /**
     * 部位派生的**多部位 roll-up**（V60，issue #4308 冻结口径）：{@code processing_orders} 只有单值
     * {@code route_key} / {@code route_requested_key} / {@code route_source} 列，而一张单可能有多个
     * 部位（各自一条路线）⇒ 取**最需关注**的那一条，次序 {@code default} &gt; {@code missing_route}
     * &gt; {@code partial} &gt; {@code derived}：
     * <ol>
     *   <li>{@code default}（3）—— 两维全不命中 = **零信息**下的默认路线：不知道该怎么走，
     *       错配无从预判（罗马帘订单今天就落在这一层）；</li>
     *   <li>{@code missing_route}（2）—— 知道该走哪条、库里却没有 ⇒ 走了默认路线，工序与计件工资**可能整体错**；</li>
     *   <li>{@code partial}（1）—— 只命中/只直读一维 ⇒ 键可能错，补另一维即可；</li>
     *   <li>{@code derived} / {@code direct}（0）—— 无异常。</li>
     * </ol>
     * 同档取先出现者（稳定）。逐部位明细在工序实例里，这里只回答「这张单有没有需要人看的东西」。
     *
     * <p>{@code direct}（issue #4354）与 {@code derived} **同档**：两者都不是「需要人看」的形态，
     * 故不新增档位、不改既有相对次序；混档时按行序取先出现者（与「两个 derived 之间」的既有取法一致）。</p>
     */
    static int severity(String routeSource) {
        return switch (routeSource == null ? "default" : routeSource) {
            case "derived", "direct" -> 0;
            case "partial" -> 1;
            case "missing_route" -> 2;
            default -> 3; // default 及其它未知取值：按最需关注处理（不静默降级）
        };
    }
}
