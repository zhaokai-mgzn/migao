package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOptionFactor;
import com.migao.admin.entity.ProductionOptionRouting;
import com.migao.admin.entity.ProductionRouting;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOptionFactorMapper;
import com.migao.admin.mapper.ProductionOptionRoutingMapper;
import com.migao.admin.mapper.ProductionRoutingMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

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

    private final ProductionOperationMapper productionOperationMapper;
    private final ProductionRoutingMapper productionRoutingMapper;
    /** 特殊选项 → 条件工序（issue #4230，V58）。 */
    private final ProductionOptionRoutingMapper productionOptionRoutingMapper;
    /** 特殊选项 → 计件系数（issue #4230，V58）。 */
    private final ProductionOptionFactorMapper productionOptionFactorMapper;

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
        List<ProductionRouting> rows = activeRoutings(tenantId);
        Map<String, ProductionOperation> catalogByName = catalogByName(tenantId);

        List<Map<String, Object>> items = new ArrayList<>();
        for (ProductionRouting routing : rows) {
            List<Map<String, Object>> steps = new ArrayList<>();
            int seq = 1;
            for (String operationName : operationNames(routing.getOperations())) {
                steps.add(stepView(seq++, operationName, catalogByName.get(operationName)));
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("id", routing.getId());
            entry.put("curtain_type", routing.getCurtainType());
            entry.put("craft", routing.getCraft());
            entry.put("operation_count", steps.size());
            entry.put("operations", steps);
            items.add(entry);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", items.size());
        result.put("routings", items);
        return result;
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
     * （相乘而非覆盖：两个独立倍率的合成；覆盖会把「一分二 ×1.7 + 另一选项 ×2」算成 ×2）。</p>
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
        return view;
    }

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }
}