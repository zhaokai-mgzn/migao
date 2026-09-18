package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouting;
import com.migao.admin.entity.ProductionRoutingVersion;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRoutingMapper;
import com.migao.admin.mapper.ProductionRoutingVersionMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 工艺路线 / 信号映射**写面**（issue #4308，P1；用户裁定 2026-09-19「支持企业设置工艺路线的自定义」）。
 *
 * <p><b>为什么单独一个类</b>：{@link ProductionOperationQueryService} 自述「只读边界」且只有 SELECT；
 * 把写操作塞进去会让「谁在改路线库」变得不可 grep（同 #4204 对工序库的处置）。读写分开，写面只有本类。</p>
 *
 * <p><b>形态边界（用户裁定，别读成「从零画路线」）</b>：本类是**参数 / 信号 / 序列可配 + 护栏**，
 * 不是「自由命名 + 拖拽编排的通用路线编辑器」。v1 = 从工序库选 + 有序序列（前端做增删/上下移）。</p>
 *
 * <p><b>为什么护栏必须逐条给理由</b>：路线是**计件工资**（Σ 报工数量 × 工序单价）与**完工判定**
 * （必完工序全绿）的唯一输入，而工序的 {@code unit} 决定应做数量读哪个算料键
 * （{@code fabric_meters} / {@code pleat_count} / …）⇒ 一条坏路线会直接算错工人工资。
 * 故所有护栏失败统一走 **HTTP 422 + {@code error.details:[{field,message}]} 逐条理由**
 * （复用既有信封字段，不新造），前端「逐条展示」有据可依；{@code message} 只做一句话摘要。</p>
 *
 * <p><b>版本账</b>：序列**真的变了**才追加 {@code production_routing_versions} 一行
 * （沿用 {@code production_operation_price_versions} 的「同值重复提交是幂等空操作」口径）——
 * 每次 PUT 都写会让账本被无意义的重复行淹没。</p>
 *
 * <p><b>权限</b>：端点声明方法级 {@code processing:manage}（类级 {@code order:list} 是读口径）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionRoutingCommandService {

    /** 路线/信号状态取值（V49/V60 `status VARCHAR(16) DEFAULT 'active'`：active / disabled）。 */
    private static final Set<String> STATUSES = Set.of("active", "disabled");

    private final ProductionRoutingMapper productionRoutingMapper;
    private final ProductionRoutingVersionMapper productionRoutingVersionMapper;
    private final ProductionOperationMapper productionOperationMapper;
    private final ProductionRouteSignalMapper productionRouteSignalMapper;
    private final ProductionOperationQueryService productionOperationQueryService;

    // ══════════════════════════════ 路线：新建 / 改序列 ══════════════════════════════

    /**
     * 新建路线（issue #4308 交付物 2 的补遗端点 {@code POST /routings}）。
     *
     * <p>{@code operations} 可缺省 = **初版空序列**（前端流程 = 先建「部位×工艺」再逐道选工序）；
     * 给了序列就按 {@link #validateSequence} 全量校验（与改序列同一份护栏，不复制第二份）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> createRouting(Map<String, Object> body, Long tenantId) {
        String curtainType = requiredText(body == null ? null : body.get("curtain_type"), "curtain_type");
        String craft = requiredText(body == null ? null : body.get("craft"), "craft");
        List<String> operations = operations(body);
        if (operations != null) {
            validateSequence(operations, tenantId);
        }
        List<String> sequence = operations == null ? List.of() : operations;

        for (ProductionRouting existing : allRoutings(tenantId)) {
            if (Objects.equals(existing.getCurtainType(), curtainType)
                    && Objects.equals(existing.getCraft(), craft)) {
                throw BusinessException.conflict(
                        String.format("工艺路线「%s×%s」已存在", curtainType, craft),
                        "请直接编辑既有路线，或换一个「部位×工艺」组合（查看入口 GET /api/admin/production/routings）");
            }
        }

        ProductionRouting routing = ProductionRouting.builder()
                .tenantId(tenantId)
                .curtainType(curtainType)
                .craft(craft)
                .operations(sequence)
                .status(body != null && body.containsKey("status")
                        ? requiredStatus(body.get("status")) : "active")
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .deleted(0)
                .build();
        productionRoutingMapper.insert(routing);
        appendVersion(routing, tenantId, sequence);
        log.info("新建工艺路线: tenantId={}, key={}×{}, 工序数={}", tenantId, curtainType, craft, sequence.size());
        return productionOperationQueryService.routingView(routing);
    }

    /**
     * 改路线序列（issue #4308 交付物 2 的主端点 {@code PUT /routings/{id}}）。
     *
     * <p>五条护栏（issue 冻结清单，逐条 {@code error.details}）：空序列拒 / 引用工序库中不存在的工序拒 /
     * 重复工序拒 / 至少一道必完工序 / seq 归一化为 1..N（存的就是有序数组，响应由
     * {@code routingView} 归一化）。**全部违规一次报全**（不是报第一条就返回）——
     * 逐条展示的前提是别让用户改一条提交一次。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> updateRouting(String id, Map<String, Object> body, Long tenantId) {
        ProductionRouting routing = findRouting(id, tenantId);
        List<String> operations = operations(body);
        if (operations == null) {
            throw BusinessException.validationError("operations 不能为空（改序列必须给出完整的有序工序名列表）");
        }
        validateSequence(operations, tenantId);

        List<String> previous = operationNames(routing.getOperations());
        routing.setOperations(operations);
        routing.setUpdatedAt(OffsetDateTime.now());
        if (body.containsKey("status")) {
            routing.setStatus(requiredStatus(body.get("status")));
        }
        productionRoutingMapper.updateById(routing);
        if (!previous.equals(operations)) {
            appendVersion(routing, tenantId, operations);
            log.info("改工艺路线序列: tenantId={}, routingId={}, {} 道 -> {} 道",
                    tenantId, routing.getId(), previous.size(), operations.size());
        }
        return productionOperationQueryService.routingView(routing);
    }

    /**
     * 序列护栏（**唯一一份**：新建与改序列共用）。违规**一次报全**，每条带
     * {@code field}（{@code operations} / {@code operations[i]} / {@code must_finish}）。
     */
    private void validateSequence(List<String> operations, Long tenantId) {
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        if (operations.isEmpty()) {
            details.add(BusinessException.detail("operations", "序列不能为空：一条路线至少要有 1 道工序"));
        }
        Map<String, ProductionOperation> library = activeOperationsByName(tenantId);
        Set<String> seen = new LinkedHashSet<>();
        boolean anyMustFinish = false;
        for (int i = 0; i < operations.size(); i++) {
            String name = operations.get(i);
            String field = "operations[" + i + "]";
            if (!StringUtils.hasText(name)) {
                details.add(BusinessException.detail(field, "工序名不能为空"));
                continue;
            }
            if (!seen.add(name)) {
                details.add(BusinessException.detail(field,
                        String.format("工序「%s」重复出现：同一道工序在一条路线里只能出现一次（否则工人按两遍单价拿钱）", name)));
                continue;
            }
            ProductionOperation op = library.get(name);
            if (op == null) {
                details.add(BusinessException.detail(field,
                        String.format("工序「%s」在工序库中不存在或已停用：请先在「工序库」新增该工序，或从库里已有的工序里选", name)));
                continue;
            }
            if (Boolean.TRUE.equals(op.getIsMustFinish())) {
                anyMustFinish = true;
            }
        }
        if (!operations.isEmpty() && !anyMustFinish && details.isEmpty()) {
            // 只有当序列本身合法时才单独报这条（否则用户会同时看到「工序不存在」与「缺少必完工序」，
            // 而后者在前者修好前根本无从判断 —— 那才是噪音）
            details.add(BusinessException.detail("must_finish",
                    "序列中至少要有 1 道必完工序：必完工序全绿是加工单完工判定的唯一依据，一道都没有 ⇒ 这张单永远完不了工"));
        }
        if (!details.isEmpty()) {
            throw BusinessException.validationError(
                    String.format("工艺路线序列未通过校验（%d 条问题）", details.size()),
                    details,
                    "逐条修好后重新提交；工序库目录查看入口 GET /api/admin/production/operations-catalog");
        }
    }

    // ══════════════════════════════ 信号映射：增 / 改 / 删 ══════════════════════════════

    /**
     * 新增信号映射（{@code POST /route-signals}）。
     *
     * <p>一行至少给出一维（{@code curtain_type} / {@code craft}）—— DB 侧另有 CHECK 兜底；
     * 两维都给 = 一个信号同时定帘种与工艺。{@code priority} 缺省 = **该用途内**最大 + 1
     * （与迁移前常量表的「顺序即优先级」同口径）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> createSignal(Map<String, Object> body, Long tenantId) {
        String signal = requiredText(body == null ? null : body.get("signal"), "signal");
        String curtainType = optionalText(body.get("curtain_type"));
        String craft = optionalText(body.get("craft"));
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        if (curtainType == null && craft == null) {
            details.add(BusinessException.detail("curtain_type",
                    "curtain_type 与 craft 至少要给一个：两个都不给 ⇒ 这行信号命中后什么都不改，是死数据"));
        }
        Integer priority = optionalInt(body.get("priority"), "priority", details);
        if (!details.isEmpty()) {
            throw BusinessException.validationError("信号映射未通过校验（" + details.size() + " 条问题）", details,
                    "给 signal 一个非空关键字，并至少指定 curtain_type 或 craft");
        }
        validateSignalUniqueness(null, signal, curtainType, craft,
                priority == null ? nextPriority(tenantId, curtainType, craft) : priority, tenantId);

        ProductionRouteSignal row = ProductionRouteSignal.builder()
                .tenantId(tenantId)
                .signal(signal)
                .curtainType(curtainType)
                .craft(craft)
                .priority(priority == null ? nextPriority(tenantId, curtainType, craft) : priority)
                .status(body.containsKey("status") ? requiredStatus(body.get("status")) : "active")
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .deleted(0)
                .build();
        productionRouteSignalMapper.insert(row);
        log.info("新增信号映射: tenantId={}, signal={}, curtainType={}, craft={}, priority={}",
                tenantId, signal, curtainType, craft, row.getPriority());
        return productionOperationQueryService.signalView(row);
    }

    /** 改信号映射（{@code PUT /route-signals/{id}}，部分更新：只写 body 里出现的字段）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> updateSignal(String id, Map<String, Object> body, Long tenantId) {
        ProductionRouteSignal row = findSignal(id, tenantId);
        String signal = body.containsKey("signal") ? requiredText(body.get("signal"), "signal") : row.getSignal();
        String curtainType = body.containsKey("curtain_type")
                ? optionalText(body.get("curtain_type")) : row.getCurtainType();
        String craft = body.containsKey("craft") ? optionalText(body.get("craft")) : row.getCraft();
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        if (curtainType == null && craft == null) {
            details.add(BusinessException.detail("curtain_type",
                    "curtain_type 与 craft 至少要留一个：两个都清空 ⇒ 这行信号命中后什么都不改，是死数据"));
        }
        Integer priority = body.containsKey("priority")
                ? optionalInt(body.get("priority"), "priority", details) : row.getPriority();
        if (!details.isEmpty()) {
            throw BusinessException.validationError("信号映射未通过校验（" + details.size() + " 条问题）", details,
                    "至少保留 curtain_type 或 craft 之一");
        }
        validateSignalUniqueness(row.getId(), signal, curtainType, craft, priority, tenantId);

        row.setSignal(signal);
        row.setCurtainType(curtainType);
        row.setCraft(craft);
        row.setPriority(priority);
        row.setUpdatedAt(OffsetDateTime.now());
        if (body.containsKey("status")) {
            row.setStatus(requiredStatus(body.get("status")));
        }
        productionRouteSignalMapper.updateById(row);
        return productionOperationQueryService.signalView(row);
    }

    /**
     * 删信号映射（{@code DELETE /route-signals/{id}}）—— **软删**（{@code deleted=1}）。
     *
     * <p>为什么不物理删：派生读的是 {@code deleted=0 AND status=active}，软删后这行立刻不参与派生；
     * 而「谁在什么时候删掉了哪条映射」在排查路线错配时是唯一的证据。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> deleteSignal(String id, Long tenantId) {
        ProductionRouteSignal row = findSignal(id, tenantId);
        row.setDeleted(1);
        row.setUpdatedAt(OffsetDateTime.now());
        productionRouteSignalMapper.updateById(row);
        log.info("删除信号映射: tenantId={}, signalId={}, signal={}", tenantId, row.getId(), row.getSignal());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", row.getId());
        result.put("deleted", true);
        return result;
    }

    /**
     * 同用途唯一 + 同用途 priority 不撞档（issue #4308）。
     *
     * <p>为什么挡 priority 撞档：派生按 {@code (priority, id)} 扫描，两行同 priority 时「谁先命中」
     * 由 uuid 决定 ⇒ 对商家**不可预测**（同一份配置在不同租户/不同重建后可能给出不同路线键）。
     * 与其留一个不可预测的静默行为，不如在写面直接拒掉（并给可行动建议）。</p>
     */
    private void validateSignalUniqueness(String selfId, String signal, String curtainType,
                                          String craft, Integer priority, Long tenantId) {
        for (ProductionRouteSignal other : allSignals(tenantId)) {
            if (Objects.equals(other.getId(), selfId) || !Objects.equals(other.getSignal(), signal)) {
                continue;
            }
            if (curtainType != null && other.getCurtainType() != null) {
                throw BusinessException.conflict(
                        String.format("信号「%s」的**帘种**映射已存在（已映射到「%s」）", signal, other.getCurtainType()),
                        "同一信号在同一用途下只能有一条映射：改那一条，或换个信号关键字");
            }
            if (craft != null && other.getCraft() != null) {
                throw BusinessException.conflict(
                        String.format("信号「%s」的**工艺**映射已存在（已映射到「%s」）", signal, other.getCraft()),
                        "同一信号在同一用途下只能有一条映射：改那一条，或换个信号关键字");
            }
        }
        if (priority == null) {
            return;
        }
        for (ProductionRouteSignal other : allSignals(tenantId)) {
            if (Objects.equals(other.getId(), selfId) || !Objects.equals(other.getPriority(), priority)) {
                continue;
            }
            boolean samePurpose = (curtainType != null && other.getCurtainType() != null)
                    || (craft != null && other.getCraft() != null);
            if (samePurpose) {
                throw BusinessException.validationError(
                        String.format("priority=%d 在同一用途下已被信号「%s」占用", priority, other.getSignal()),
                        List.of(BusinessException.detail("priority",
                                "同用途内 priority 必须唯一：撞档时「谁先命中」由内部 id 决定，对商家不可预测")),
                        "换一个 priority，或省略该字段让服务端自动取「同用途最大 + 1」");
            }
        }
    }

    /** 该用途内的下一个 priority（帘种行与工艺行**各自**排序，见 V60 迁移的「用途拆分」）。 */
    private int nextPriority(Long tenantId, String curtainType, String craft) {
        int max = 0;
        for (ProductionRouteSignal row : allSignals(tenantId)) {
            boolean samePurpose = (curtainType != null && row.getCurtainType() != null)
                    || (craft != null && row.getCraft() != null);
            if (samePurpose && row.getPriority() != null) {
                max = Math.max(max, row.getPriority());
            }
        }
        return max + 1;
    }

    // ══════════════════════════════ 读取 / 版本账 ══════════════════════════════

    private ProductionRouting findRouting(String id, Long tenantId) {
        ProductionRouting routing = id == null ? null : productionRoutingMapper.selectById(id);
        if (routing == null || !tenantId.equals(routing.getTenantId())
                || !Integer.valueOf(0).equals(routing.getDeleted())) {
            throw BusinessException.notFound("工艺路线");
        }
        return routing;
    }

    private ProductionRouteSignal findSignal(String id, Long tenantId) {
        ProductionRouteSignal row = id == null ? null : productionRouteSignalMapper.selectById(id);
        if (row == null || !tenantId.equals(row.getTenantId())
                || !Integer.valueOf(0).equals(row.getDeleted())) {
            throw BusinessException.notFound("信号映射");
        }
        return row;
    }

    /** 全部未软删路线（含 disabled：新建时的重名判据要覆盖停用行，否则会撞 DB 唯一索引）。 */
    private List<ProductionRouting> allRoutings(Long tenantId) {
        List<ProductionRouting> rows = productionRoutingMapper.selectList(
                new LambdaQueryWrapper<ProductionRouting>()
                        .eq(ProductionRouting::getTenantId, tenantId)
                        .eq(ProductionRouting::getDeleted, 0));
        return rows == null ? List.of() : rows;
    }

    private List<ProductionRouteSignal> allSignals(Long tenantId) {
        List<ProductionRouteSignal> rows = productionRouteSignalMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteSignal>()
                        .eq(ProductionRouteSignal::getTenantId, tenantId)
                        .eq(ProductionRouteSignal::getDeleted, 0));
        return rows == null ? List.of() : rows;
    }

    /** 活跃工序库按名索引（护栏用：序列里引用的工序必须**存在且活跃**）。 */
    private Map<String, ProductionOperation> activeOperationsByName(Long tenantId) {
        List<ProductionOperation> rows = productionOperationMapper.selectList(
                new LambdaQueryWrapper<ProductionOperation>()
                        .eq(ProductionOperation::getTenantId, tenantId)
                        .eq(ProductionOperation::getDeleted, 0)
                        .eq(ProductionOperation::getStatus, "active"));
        Map<String, ProductionOperation> byName = new LinkedHashMap<>();
        if (rows != null) {
            for (ProductionOperation op : rows) {
                byName.put(op.getName(), op);
            }
        }
        return byName;
    }

    /** 追加一行版本账（路线变更留痕：路线是计件工资与完工判定的唯一输入）。 */
    private void appendVersion(ProductionRouting routing, Long tenantId, List<String> operations) {
        productionRoutingVersionMapper.insert(ProductionRoutingVersion.builder()
                .tenantId(tenantId)
                .routingId(routing.getId())
                .curtainType(routing.getCurtainType())
                .craft(routing.getCraft())
                .operations(operations)
                .operationCount(operations.size())
                .createdAt(OffsetDateTime.now())
                .deleted(0)
                .build());
    }

    // ══════════════════════════════ 解析工具 ══════════════════════════════

    /** 有序工序名列表；{@code null} = body 里没给这个字段（与「给了空数组」是两回事）。 */
    @SuppressWarnings("unchecked")
    private static List<String> operations(Map<String, Object> body) {
        if (body == null || !body.containsKey("operations")) {
            return null;
        }
        Object raw = body.get("operations");
        if (!(raw instanceof List<?> list)) {
            throw BusinessException.validationError("operations 必须是工序名数组");
        }
        List<String> names = new ArrayList<>(list.size());
        for (Object item : list) {
            names.add(item == null ? null : String.valueOf(item).trim());
        }
        return names;
    }

    private static List<String> operationNames(Object raw) {
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

    private static String requiredText(Object value, String field) {
        String text = value == null ? null : String.valueOf(value).trim();
        if (!StringUtils.hasText(text)) {
            throw BusinessException.validationError(field + " 不能为空");
        }
        return text;
    }

    private static String optionalText(Object value) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
    }

    private static String requiredStatus(Object value) {
        String status = requiredText(value, "status");
        if (!STATUSES.contains(status)) {
            throw BusinessException.validationError("status 仅支持 active/disabled");
        }
        return status;
    }

    private static Integer optionalInt(Object value, String field, List<ApiResponse.ErrorDetail> details) {
        if (value == null) {
            return null;
        }
        if (value instanceof Number number) {
            return number.intValue();
        }
        try {
            return Integer.valueOf(String.valueOf(value).trim());
        } catch (NumberFormatException e) {
            details.add(BusinessException.detail(field, field + " 必须是整数"));
            return null;
        }
    }
}
