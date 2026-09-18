package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOptionFactor;
import com.migao.admin.entity.ProductionOptionRouting;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouting;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOptionFactorMapper;
import com.migao.admin.mapper.ProductionOptionRoutingMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRoutingMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 工序库 / 工艺路线**只读**消费者（issue #4116 P0-2）。
 *
 * <p>背景（取证事实）：{@code production_operations} / {@code production_routings} 自 V49 建表起
 * **零消费者、零种子** ⇒ 商家无配置入口、库里无数据、§3 工艺路线在 DB 层不可查不可展示。
 * 本类补上「可查询/可展示」这一半：读**工序库目录 + 工艺路线模板**（种子源 = V54 ∪ V56 的工序、
 * V54 ∪ V58 的路线；真值源是 {@code app/production/routing.py} 的目录/路线常量）并按展示口径整形。
 * 工序数与路线数**不在此写死**：它们随迁移漂移（V56 加过工序、V58 加过路线），
 * 写死即制造「注释与实际不符且不会变红」的假声明（issue #4259 ②）。</p>
 *
 * <p><b>只读边界（本类明确不做）</b>：本类**只有** SELECT，端点也只有 GET。工序库的写面
 * （改单价/停用/排序）在 {@link ProductionOperationCommandService}（PUT /production/operations/{id}，
 * issue #4204）—— 读写分开，写面不在本类里开口子。</p>
 *
 * <p><b>{@link #findRouting} 是「生成加工单即实例化」的工序来源</b>（issue #4116 用户裁定「现在就切」，
 * 2026-09-18）：工序实例的 seq/工序名/分组/单位/单价/必完标记**全部**来自本类读到的库行，
 * 加工项目录自此刻起**不再是**工序真值源。库中查不到路线/查不到路线引用的工序时，
 * 调用方（{@code ProcessingOrderService}）**fail-closed 中止生成**，不回退加工项目录 ——
 * 回退等于让这次切换变成装饰性的（旧路径还在 ⇒ 库为空也没人发现）。</p>
 *
 * <p><b>为什么不复用加工单侧的 {@code getOperations}</b>：那个是「某加工单**已经实例化**的工序树」，
 * 读 {@code processing_position_operations}；本类读的是**库**（工序目录 + 路线模板），
 * 二者是「模板 vs 实例」，混用一个方法会让调用方分不清拿到的是哪一层。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionOperationQueryService {

    /**
     * 「有工序、有价、**有意不消费**（等客户确认）」的工序集合（issue #4308 P4；真值源 =
     * {@code backend/ai-agent-service/app/production/routing.py::PENDING_CUSTOMER_CONFIRMATION_OPERATIONS}）。
     *
     * <p><b>这不是缺陷清单，是提问清单</b>：issue #4261 逐项登记了为什么必须问客户
     * （裁剪vs精裁是否两道 / 质检是否每单必做 / 腰靠垫归属 / 罗马帘整套工序 / 纱帘熨烫定型）——
     * 猜出来的工序与单价会**直接算成工人工资**，故一律不猜。</p>
     *
     * <p>⚠️ <b>与 routing.py 同源由测试守</b>（Java 无法 import Python）：
     * {@code ProductionRouteSignalMigrationTest} 逐字解析 {@code routing.py} 的
     * {@code frozenset} 并与本常量**双向比对**（少一道/多一道都红）。改一处不改另一处即红 ——
     * 抄一份字面量而不守，就是第二份口径。</p>
     */
    public static final Set<String> PENDING_CUSTOMER_CONFIRMATION_OPERATIONS =
            Set.of("裁剪-布", "裁剪-纱", "质检", "腰靠垫");

    private final ProductionOperationMapper productionOperationMapper;
    private final ProductionRoutingMapper productionRoutingMapper;
    /** 特殊选项 → 条件工序（issue #4230，V58）。 */
    private final ProductionOptionRoutingMapper productionOptionRoutingMapper;
    /** 特殊选项 → 计件系数（issue #4230，V58）。 */
    private final ProductionOptionFactorMapper productionOptionFactorMapper;
    /** 信号 → 路线键映射（issue #4308，V60；派生路线键的**唯一**数据源，不再是 Java 常量）。 */
    private final ProductionRouteSignalMapper productionRouteSignalMapper;

    /**
     * 工序库目录：按分组 → 排序位的稳定顺序返回全部活跃工序。
     *
     * @return {total, groups:[{group, operations:[...]}]}；工序项含
     *         {id, name, group, position, unit, unit_price, is_must_finish, is_start_marker}
     */
    public Map<String, Object> catalog(Long tenantId) {
        List<ProductionOperation> operations = productionOperationMapper.selectList(
                new LambdaQueryWrapper<ProductionOperation>()
                        .eq(ProductionOperation::getTenantId, tenantId)
                        .eq(ProductionOperation::getDeleted, 0)
                        .eq(ProductionOperation::getStatus, "active")
                        .orderByAsc(ProductionOperation::getSortOrder)
                        .orderByAsc(ProductionOperation::getName));
        List<ProductionOperation> rows = operations == null ? List.of() : operations;

        Map<String, List<Map<String, Object>>> grouped = new LinkedHashMap<>();
        for (ProductionOperation op : rows) {
            String group = op.getGroupName() == null ? "其他" : op.getGroupName();
            grouped.computeIfAbsent(group, key -> new ArrayList<>()).add(operationView(op));
        }
        List<Map<String, Object>> groups = new ArrayList<>();
        grouped.forEach((group, items) -> {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("group", group);
            entry.put("operations", items);
            groups.add(entry);
        });

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", rows.size());
        result.put("groups", groups);
        return result;
    }

    /**
     * 工艺路线模板：部位 × 工艺 → 工序序列（含每道工序的库口径单位/单价，供展示与校验）。
     *
     * @return {total, routings:[{curtain_type, craft, operations:[{seq, operation, group, unit,
     *         unit_price, is_must_finish, is_start_marker}]}]}
     */
    public Map<String, Object> routings(Long tenantId) {
        List<Map<String, Object>> items = new ArrayList<>();
        for (ProductionRouting routing : activeRoutings(tenantId)) {
            items.add(routingView(routing));
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", items.size());
        result.put("routings", items);
        return result;
    }

    /**
     * 路线单项展示形态（{@code GET /routings} 的列表项 / {@code POST} 新建 / {@code PUT} 改序列
     * 的响应**共用同一份** —— 三处各拼一份必然漂移，而前端拿同一个 TS 类型渲染三者）。
     *
     * <p>{@code seq} 在这里归一化为 1..N（它就是数组下标 + 1）：seq 是报工「越站」防呆
     * （取「seq 最大的前道」）与页面排序的唯一顺序依据。</p>
     */
    public Map<String, Object> routingView(ProductionRouting routing) {
        Map<String, ProductionOperation> catalogByName = catalogByName(routing.getTenantId());
        List<Map<String, Object>> steps = new ArrayList<>();
        int seq = 1;
        for (String operationName : operationNames(routing.getOperations())) {
            steps.add(stepView(seq++, operationName, catalogByName.get(operationName)));
        }
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("id", routing.getId());
        entry.put("curtain_type", routing.getCurtainType());
        entry.put("craft", routing.getCraft());
        entry.put("status", routing.getStatus());
        // 路线自身的 provenance（V62，issue #4361）：**与每道工序的 source 是两个层级** ——
        // 路线行说「这条序列怎么来的」（rt-v54-* = 占位待确认 / rt-v58-* = 推算），
        // 工序项说「这道工序的单价怎么来的」。两者不可互推，故都返回。
        entry.put("source", routing.getSource());
        entry.put("operation_count", steps.size());
        entry.put("operations", steps);
        return entry;
    }

    /**
     * 信号映射列表（issue #4308 交付物 3 的读面）：{@code {total, signals:[{id, signal,
     * curtain_type, craft, priority, status}]}}。
     *
     * <p>写面（POST/PUT/DELETE）在 {@link ProductionRoutingCommandService} —— 与工序库
     * 「读写分开」同口径（本类只有 SELECT）。</p>
     */
    public Map<String, Object> routeSignalList(Long tenantId) {
        List<Map<String, Object>> items = new ArrayList<>();
        for (ProductionRouteSignal signal : routeSignals(tenantId)) {
            items.add(signalView(signal));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", items.size());
        result.put("signals", items);
        return result;
    }

    /** 信号映射单项展示形态（列表项 / 写面响应共用同一份）。 */
    public Map<String, Object> signalView(ProductionRouteSignal signal) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", signal.getId());
        view.put("signal", signal.getSignal());
        view.put("curtain_type", signal.getCurtainType());
        view.put("craft", signal.getCraft());
        view.put("priority", signal.getPriority());
        view.put("status", signal.getStatus());
        return view;
    }

    /**
     * **实例化用**路线解析（issue #4116 切库，本方法是工序实例的唯一工序来源）。
     *
     * <p>与 {@link #routings}（展示口径，容错）的分工：本方法把「容错」显式化 —— 容错**只**做到
     * 「报出缺了什么」，不做到「替调用方猜」（缺失的工序不静默换默认值，而是登记进
     * {@code missing_operations} 让调用方 fail-closed）。</p>
     *
     * @return {@code {curtain_type, craft, operation_count, missing_operations, operations:[{seq,
     *         operation, group, unit, unit_price, is_must_finish, is_start_marker}]}}；
     *         **未命中该 部位×工艺 ⇒ null**（不抛：兜底到默认路线是调用方的策略，不是库的语义）
     */
    public Map<String, Object> findRouting(Long tenantId, String curtainType, String craft) {
        ProductionRouting hit = null;
        for (ProductionRouting routing : activeRoutings(tenantId)) {
            if (Objects.equals(routing.getCurtainType(), curtainType)
                    && Objects.equals(routing.getCraft(), craft)) {
                hit = routing;
                break;
            }
        }
        if (hit == null) {
            return null;
        }

        Map<String, ProductionOperation> catalogByName = catalogByName(tenantId);
        List<Map<String, Object>> steps = new ArrayList<>();
        List<String> missing = new ArrayList<>();
        int seq = 1;
        for (String operationName : operationNames(hit.getOperations())) {
            ProductionOperation op = catalogByName.get(operationName);
            if (op == null) {
                missing.add(operationName);
            }
            steps.add(stepView(seq++, operationName, op));
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("curtain_type", hit.getCurtainType());
        result.put("craft", hit.getCraft());
        result.put("operation_count", steps.size());
        result.put("missing_operations", missing);
        result.put("operations", steps);
        return result;
    }

    /**
     * 特殊选项 → 条件工序（issue #4230，**实例化用**读面）。
     *
     * <p>与 {@link #findRouting} 的分工：路线给**基准**工序序列，本表给「勾了某个特殊选项才加」的
     * **条件**工序；插在哪由 {@code after_operation} 决定（锚点不在路线中 ⇒ 追加到末尾，
     * 与真值源 {@code routing.py::_insert_after} 同款）。</p>
     *
     * <p>只返回**活跃**行（{@code status=active} + 未软删 + 同租户），按 {@code sort_order}
     * 稳定排序 —— 多选项共用同一锚点时的先后必须确定，否则同一张单两次生成会得到不同 seq。</p>
     *
     * @return 全部活跃条件工序行（调用方按本单的 specialOptions 过滤；表极小，一次取回比逐选项查省事且无 N+1）
     */
    public List<ProductionOptionRouting> optionRoutings(Long tenantId) {
        List<ProductionOptionRouting> rows = productionOptionRoutingMapper.selectList(
                new LambdaQueryWrapper<ProductionOptionRouting>()
                        .eq(ProductionOptionRouting::getTenantId, tenantId)
                        .eq(ProductionOptionRouting::getDeleted, 0)
                        .eq(ProductionOptionRouting::getStatus, "active")
                        .orderByAsc(ProductionOptionRouting::getSortOrder)
                        .orderByAsc(ProductionOptionRouting::getOptionName));
        return rows == null ? List.of() : rows;
    }

    /**
     * 特殊选项 → 计件系数（issue #4230，**实例化用**读面）。
     *
     * <p>{@code operation_name} 为空 = 该部位全部工序（平摊档）；非空 = 逐工序例外档。
     * 取用口径（在 {@code ProcessingOrderService} 里）：同一选项内**例外档盖住平摊档**，
     * 多个选项之间**相乘** —— 与真值源 {@code routing.py::factor_for} 逐字同口径
     * （相乘而非覆盖：两个独立倍率的合成；覆盖会把「一分为二 ×1.7 + 另一选项 ×2」算成 ×2）。</p>
     */
    public List<ProductionOptionFactor> optionFactors(Long tenantId) {
        List<ProductionOptionFactor> rows = productionOptionFactorMapper.selectList(
                new LambdaQueryWrapper<ProductionOptionFactor>()
                        .eq(ProductionOptionFactor::getTenantId, tenantId)
                        .eq(ProductionOptionFactor::getDeleted, 0)
                        .orderByAsc(ProductionOptionFactor::getOptionName)
                        .orderByAsc(ProductionOptionFactor::getOperationName));
        return rows == null ? List.of() : rows;
    }

    /**
     * 工序元数据按名索引（issue #4230：**条件工序**要拿分组/单位/单价/必完标记）。
     *
     * <p>与 {@link #findRouting} 的 {@code catalogByName} **同一份**读取口径
     * （不复制第二份「怎么读工序库」）。返回值里**没有 seq**：条件工序的位置由锚点决定，
     * 不是库里的固定序号 —— 调用方插完后统一重排。</p>
     */
    public Map<String, Map<String, Object>> operationsByName(Long tenantId) {
        Map<String, Map<String, Object>> views = new LinkedHashMap<>();
        catalogByName(tenantId).forEach((name, op) -> views.put(name, operationMetaView(op)));
        return views;
    }

    /**
     * 信号 → 路线键映射（V60，issue #4308，**派生用**读面）。
     *
     * <p>与迁移前 {@code ProcessingOrderService} 里两个 {@code String[][]} 常量的分工完全相同，
     * 只是数据源从「研发改的常量」换成「商家可配的库行」：命中方式仍是文本 {@code contains}，
     * {@code priority} 仍是**用途内**扫描序（帘种行与工艺行各自排序，理由见 V60 迁移注释）。</p>
     *
     * <p>只返回**活跃**行（{@code status=active} + 未软删 + 同租户），按
     * {@code (priority, id)} 稳定排序 —— 派生必须是确定性的，否则同一张单两次生成会得到不同的
     * 路线键（进而不同的工序序列与计件工资）。</p>
     */
    public List<ProductionRouteSignal> routeSignals(Long tenantId) {
        List<ProductionRouteSignal> rows = productionRouteSignalMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteSignal>()
                        .eq(ProductionRouteSignal::getTenantId, tenantId)
                        .eq(ProductionRouteSignal::getDeleted, 0)
                        .eq(ProductionRouteSignal::getStatus, "active")
                        .orderByAsc(ProductionRouteSignal::getPriority)
                        .orderByAsc(ProductionRouteSignal::getId));
        return rows == null ? List.of() : rows;
    }

    /**
     * **缺口可查**（issue #4308 交付物 5 / P4）：把「只活在代码注释里的缺口」变成商家能看见的数据。
     *
     * <p>两只清单：</p>
     * <ol>
     *   <li>{@code unrouted_operations} —— **有活跃工序但未进任何活跃路线**的工序。
     *       真值源下应为 {@code 裁剪-布 / 裁剪-纱 / 质检 / 腰靠垫} 四道，且它们**不是缺陷**：
     *       issue #4261 逐项登记了「为什么必须问客户」（裁剪vs精裁是否两道 / 质检是否每单必做 /
     *       腰靠垫归属 / 罗马帘整套工序 / 纱帘熨烫定型）⇒ 每条带
     *       {@code pending_confirmation=true}，**不要让商家/前端把它们读成「系统漏了」**。</li>
     *   <li>{@code signal_keys_without_route} —— **库里没有路线的信号组合**：逐个活跃信号行算出
     *       「只命中它时会派生的键」（另一维取默认），报出库中无该路线的那些。
     *       例：商家自建信号「罗马帘」⇒ {@code 罗马帘×韩褶} 无路线（#4261 ①，本单**不发明**该路线）。</li>
     * </ol>
     *
     * <p>口径与派生**同源**：默认维取值直接引用 {@link ProcessingOrderService#DEFAULT_CURTAIN_TYPE}
     * / {@link ProcessingOrderService#DEFAULT_CRAFT}（复制第二份必然漂移）。</p>
     */
    public Map<String, Object> routingGaps(Long tenantId) {
        List<ProductionRouting> routings = activeRoutings(tenantId);
        Set<String> routed = new LinkedHashSet<>();
        for (ProductionRouting routing : routings) {
            routed.addAll(operationNames(routing.getOperations()));
        }
        Set<String> existingKeys = new LinkedHashSet<>();
        for (ProductionRouting routing : routings) {
            existingKeys.add(routing.getCurtainType() + "×" + routing.getCraft());
        }

        List<Map<String, Object>> unrouted = new ArrayList<>();
        int pending = 0;
        for (ProductionOperation op : activeOperations(tenantId)) {
            if (routed.contains(op.getName())) {
                continue;
            }
            boolean isPending = PENDING_CUSTOMER_CONFIRMATION_OPERATIONS.contains(op.getName());
            if (isPending) {
                pending++;
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("name", op.getName());
            entry.put("group_name", op.getGroupName());
            entry.put("unit", op.getUnit());
            entry.put("unit_price", nz(op.getUnitPrice()));
            entry.put("pending_confirmation", isPending);
            entry.put("note", isPending
                    ? "有意挂起、等客户输入（issue #4261 提问清单），不是系统漏了；客户回复前不要替它编工序/单价"
                    : "该工序有价但没有任何活跃路线消费它；可经「工艺路线」页把它加进某条路线，或停用它");
            unrouted.add(entry);
        }

        List<Map<String, Object>> signalGaps = new ArrayList<>();
        for (ProductionRouteSignal signal : routeSignals(tenantId)) {
            String curtainType = signal.getCurtainType() == null
                    ? ProcessingOrderService.DEFAULT_CURTAIN_TYPE : signal.getCurtainType();
            String craft = signal.getCraft() == null
                    ? ProcessingOrderService.DEFAULT_CRAFT : signal.getCraft();
            String key = curtainType + "×" + craft;
            if (existingKeys.contains(key)) {
                continue;
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("curtain_type", curtainType);
            entry.put("craft", craft);
            entry.put("route_key", key);
            entry.put("signal", signal.getSignal());
            signalGaps.add(entry);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("unrouted_operations", unrouted);
        result.put("unrouted_operation_total", unrouted.size());
        result.put("pending_confirmation_total", pending);
        result.put("signal_keys_without_route", signalGaps);
        return result;
    }

    /**
     * 活跃工序（tenant + deleted=0 + status=active，按分组/排序位稳定返回）。
     */
    private List<ProductionOperation> activeOperations(Long tenantId) {
        List<ProductionOperation> rows = productionOperationMapper.selectList(
                new LambdaQueryWrapper<ProductionOperation>()
                        .eq(ProductionOperation::getTenantId, tenantId)
                        .eq(ProductionOperation::getDeleted, 0)
                        .eq(ProductionOperation::getStatus, "active")
                        .orderByAsc(ProductionOperation::getSortOrder)
                        .orderByAsc(ProductionOperation::getName));
        return rows == null ? List.of() : rows;
    }

    /**
     * 库中现有的路线键（`部位×工艺`，展示顺序 = 部位→工艺）。
     * 失败提示要**可行动**就必须能说出"库里有的是什么"，而不是只说"没找到"。
     */
    public List<String> routingKeys(Long tenantId) {
        List<String> keys = new ArrayList<>();
        for (ProductionRouting routing : activeRoutings(tenantId)) {
            keys.add(routing.getCurtainType() + "×" + routing.getCraft());
        }
        return keys;
    }

    /** 活跃路线（tenant_id + deleted=0 + status=active；条件压在 SQL 里而非内存过滤）。 */
    private List<ProductionRouting> activeRoutings(Long tenantId) {
        List<ProductionRouting> routings = productionRoutingMapper.selectList(
                new LambdaQueryWrapper<ProductionRouting>()
                        .eq(ProductionRouting::getTenantId, tenantId)
                        .eq(ProductionRouting::getDeleted, 0)
                        .eq(ProductionRouting::getStatus, "active")
                        .orderByAsc(ProductionRouting::getCurtainType)
                        .orderByAsc(ProductionRouting::getCraft));
        return routings == null ? List.of() : routings;
    }

    /** 工序库行按名索引（不含 status 过滤：路线引用了停用/历史工序时要能**指名报缺**，而不是当它不存在）。 */
    private Map<String, ProductionOperation> catalogByName(Long tenantId) {
        Map<String, ProductionOperation> byName = new LinkedHashMap<>();
        List<ProductionOperation> rows = productionOperationMapper.selectList(
                new LambdaQueryWrapper<ProductionOperation>()
                        .eq(ProductionOperation::getTenantId, tenantId)
                        .eq(ProductionOperation::getDeleted, 0));
        if (rows != null) {
            for (ProductionOperation op : rows) {
                byName.put(op.getName(), op);
            }
        }
        return byName;
    }

    /**
     * 工序名序列归一化：{@code production_routings.operations} 是 JSONB，MyBatis 侧经
     * {@code JacksonTypeHandler} 反序列化为 {@code List<?>}（少数路径可能回落到 JSON 文本）
     * ⇒ 两种形态都收敛成 {@code List<String>}，不让展示层各自解析一遍。
     */
    private List<String> operationNames(Object raw) {
        List<String> names = new ArrayList<>();
        if (raw instanceof List<?> list) {
            for (Object item : list) {
                if (item != null) {
                    names.add(String.valueOf(item));
                }
            }
        }
        return names;
    }

    /**
     * 工序项展示形态（目录项 / 写面 PUT 的响应**共用同一份**——两处各自拼一份必然漂移，
     * 而前端拿同一个 TS 类型渲染两者）。
     */
    public Map<String, Object> operationView(ProductionOperation op) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", op.getId());
        view.put("name", op.getName());
        view.put("group", op.getGroupName());
        view.put("position", op.getPosition());
        view.put("unit", op.getUnit());
        view.put("unit_price", nz(op.getUnitPrice()));
        view.put("is_must_finish", Boolean.TRUE.equals(op.getIsMustFinish()));
        view.put("is_start_marker", Boolean.TRUE.equals(op.getIsStartMarker()));
        // provenance（V62，issue #4361）：单价是占位值/行业推算值这件事必须**在界面上可见**
        // （用户裁定：「照铺，但 provenance 必须可见，不许静默」）。NULL = 来源未知，不冒充已知。
        view.put("source", op.getSource());
        return view;
    }

    /** 路线内一道工序：库口径单位/单价（工序库缺该工序时为 null，不猜、不用默认值顶替）。 */
    private Map<String, Object> stepView(int seq, String operationName, ProductionOperation op) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("seq", seq);
        view.put("operation", operationName);
        view.putAll(operationMetaView(op));
        return view;
    }

    /**
     * 工序的库口径元数据（路线内工序与**条件工序**共用同一份整形 —— 两处各拼一份必然漂移，
     * 而它们最终落在同一张实例表的同名列上）。
     */
    private Map<String, Object> operationMetaView(ProductionOperation op) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("group", op == null ? null : op.getGroupName());
        view.put("unit", op == null ? null : op.getUnit());
        view.put("unit_price", op == null ? null : nz(op.getUnitPrice()));
        view.put("is_must_finish", op != null && Boolean.TRUE.equals(op.getIsMustFinish()));
        view.put("is_start_marker", op != null && Boolean.TRUE.equals(op.getIsStartMarker()));
        // provenance 与目录读面**同一份口径**（两处各拼一份必然漂移，而前端拿同一个 TS 类型渲染）
        view.put("source", op == null ? null : op.getSource());
        return view;
    }

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }
}