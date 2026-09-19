package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.entity.ProductionRoutingVersion;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
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

    /**
     * 新路线的默认适用帘种集合（取值域同 {@code production_operation_positions.position}）。
     *
     * <p>为什么给默认而不是要求必填：V71/V72 种子路线就是「一条主线适用全部三种帘种」，
     * 前端「新建路线」也只需要先给个名字 ⇒ 强制填三元素数组只是摩擦。
     * 要收窄适用范围的商家可显式给 {@code positions}。</p>
     */
    private static final List<String> DEFAULT_POSITIONS = List.of("布帘", "纱帘", "帘头");

    private final ProductionRouteTemplateMapper productionRouteTemplateMapper;
    private final ProductionRoutingVersionMapper productionRoutingVersionMapper;
    private final ProductionOperationMapper productionOperationMapper;
    private final ProductionRouteSignalMapper productionRouteSignalMapper;
    private final ProductionOperationQueryService productionOperationQueryService;

    // ══════════════════════════ 路线模板：新建 / 改 / 删（P2b，issue #4459）══════════════════════════
    //
    // 写面自 P2b 起落在 **production_route_templates**（新结构）：路线 = **一条具名主线**
    // （逻辑工序名）+ 适用帘种集合 + 默认标记。旧 `production_routings`（部位×工艺 展开快照）
    // 的活跃行已由 V73 软删 ⇒ 再往它写就是往**死表**写（写进去没人读，商家改了不生效且不报错）。
    //
    // 工艺不再参与「选哪条路线」（它只触发 production_route_rules）⇒ 本类的 body 从
    // `{curtain_type, craft, operations}` 改为 `{name, positions, mainline, is_default, status}`。

    /**
     * 新建路线模板（{@code POST /routings}）。
     *
     * <p>{@code mainline} 可缺省 = **初版空主线**（前端流程 = 先建路线再逐道选工序）；
     * 给了主线就按 {@link #validateMainline} 全量校验（与改主线同一份护栏，不复制第二份）。</p>
     *
     * <p><b>护栏（issue #4432 正文 §三，逐条 {@code error.details}）</b>：同租户活跃路线不得重名（409）/
     * 主线引用工序库中不存在的工序拒 / 重复工序拒 / 至少一道必完工序 / {@code is_default=true} ⇒
     * 把既有默认降级（**恰一条默认**：DB 部分唯一索引
     * {@code uk_production_route_templates_tenant_default} 保证 ≤1，不降级会撞索引变 500）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> createRouting(Map<String, Object> body, Long tenantId) {
        String name = requiredText(body == null ? null : body.get("name"), "name");
        List<String> mainline = stringList(body == null ? null : body.get("mainline"));
        List<String> positions = stringList(body == null ? null : body.get("positions"));
        if (!mainline.isEmpty()) {
            validateMainline(mainline, tenantId);
        }
        for (ProductionRouteTemplate existing : allRoutings(tenantId)) {
            if (Objects.equals(existing.getName(), name)) {
                throw BusinessException.conflict(
                        String.format("工艺路线「%s」已存在", name),
                        "请直接编辑既有路线，或换一个路线名（查看入口 GET /api/admin/production/routings）");
            }
        }
        boolean isDefault = Boolean.TRUE.equals(body == null ? null : body.get("is_default"));
        if (isDefault) {
            demoteCurrentDefault(tenantId, null);
        }

        ProductionRouteTemplate template = ProductionRouteTemplate.builder()
                .tenantId(tenantId)
                .name(name)
                .isDefault(isDefault)
                .positions(positions.isEmpty() ? DEFAULT_POSITIONS : positions)
                .mainline(mainline)
                .status(body != null && body.containsKey("status")
                        ? requiredStatus(body.get("status")) : "active")
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .deleted(0)
                .build();
        productionRouteTemplateMapper.insert(template);
        appendVersion(template, tenantId, mainline);
        log.info("新建工艺路线: tenantId={}, name={}, 主线={} 道, isDefault={}",
                tenantId, name, mainline.size(), isDefault);
        return productionOperationQueryService.templateView(template);
    }

    /**
     * 改路线（{@code PUT /routings/{id}}，部分更新：只写 body 里出现的字段）。
     *
     * <p><b>body 扩展（issue #4459 §1③）</b>：{@code {name?, is_default?, mainline?, positions?, status?}}。
     * 护栏逐条（全部 422 + {@code error.details}）：</p>
     * <ul>
     *   <li><b>改名只改 {@code name}</b> —— 不给 {@code mainline} 就**不动序列**（改一个名字不该顺带
     *       重写计件工资的输入）；</li>
     *   <li><b>{@code is_default} 恰一条</b> —— 设为 true 时把既有默认降级（同事务，避开部分唯一索引）；</li>
     *   <li><b>{@code is_default:false} ⇒ 422</b> —— 「取消默认」会让该租户**零默认** ⇒ 建单全 fail-closed
     *       （改默认请对另一条置 true）；</li>
     *   <li><b>停用默认路线 ⇒ 422</b> —— 同上，停用它等于把租户变成零默认；</li>
     *   <li>主线护栏与新建共用一份（{@link #validateMainline}）。</li>
     * </ul>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> updateRouting(String id, Map<String, Object> body, Long tenantId) {
        ProductionRouteTemplate template = findRouting(id, tenantId);
        List<String> mainline = stringList(body.get("mainline"));
        if (body.containsKey("mainline")) {
            validateMainline(mainline, tenantId);
        }
        List<String> previous = stringList(template.getMainline());

        if (body.containsKey("name")) {
            String name = requiredText(body.get("name"), "name");
            for (ProductionRouteTemplate other : allRoutings(tenantId)) {
                if (!Objects.equals(other.getId(), template.getId()) && Objects.equals(other.getName(), name)) {
                    throw BusinessException.conflict(
                            String.format("工艺路线「%s」已存在", name),
                            "换一个路线名（查看入口 GET /api/admin/production/routings）");
                }
            }
            template.setName(name);
        }
        if (body.containsKey("positions")) {
            List<String> positions = stringList(body.get("positions"));
            if (positions.isEmpty()) {
                throw BusinessException.validationError("positions 不能为空（一条路线至少要说明它适用哪些帘种）");
            }
            template.setPositions(positions);
        }
        if (body.containsKey("is_default")) {
            if (!Boolean.TRUE.equals(body.get("is_default"))) {
                throw BusinessException.validationError("is_default 不能置为 false",
                        List.of(BusinessException.detail("is_default",
                                "取消默认会让该租户没有默认路线 ⇒ 缺信号订单建单全部 fail-closed；"
                                        + "改默认请对另一条路线置 is_default=true（它会自动把当前默认降级）")),
                        "把要作为默认的那条路线 PUT is_default=true");
            }
            demoteCurrentDefault(tenantId, template.getId());
            template.setIsDefault(true);
        }
        if (body.containsKey("status")) {
            String status = requiredStatus(body.get("status"));
            if ("disabled".equals(status) && Boolean.TRUE.equals(template.getIsDefault())) {
                throw BusinessException.validationError("默认路线不能停用",
                        List.of(BusinessException.detail("status",
                                "停用默认路线 ⇒ 该租户零默认 ⇒ 缺信号订单建单全部 fail-closed；"
                                        + "请先把另一条设为默认，再停用这条")),
                        "先把另一条路线 PUT is_default=true，再停用这条");
            }
            template.setStatus(status);
        }
        if (body.containsKey("mainline")) {
            template.setMainline(mainline);
        }
        template.setUpdatedAt(OffsetDateTime.now());
        productionRouteTemplateMapper.updateById(template);

        List<String> after = stringList(template.getMainline());
        if (!previous.equals(after)) {
            appendVersion(template, tenantId, after);
            log.info("改工艺路线主线: tenantId={}, routingId={}, {} 道 -> {} 道",
                    tenantId, template.getId(), previous.size(), after.size());
        }
        return productionOperationQueryService.templateView(template);
    }

    /**
     * 删路线（{@code DELETE /routings/{id}}，**软删** {@code deleted=1}）。
     *
     * <p>护栏（issue #4432 正文 §三）：<b>删默认 ⇒ 422</b>（删了就是零默认 ⇒ 建单全 fail-closed）；
     * <b>删最后一条 ⇒ 422</b>（同因）。</p>
     *
     * <p>为什么不物理删：派生读的是 {@code deleted=0 AND status=active}，软删后这条立刻不参与选路；
     * 而「谁在什么时候删掉了哪条路线」在排查工序错配时是唯一的证据（与信号映射同口径）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> deleteRouting(String id, Long tenantId) {
        ProductionRouteTemplate template = findRouting(id, tenantId);
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        if (Boolean.TRUE.equals(template.getIsDefault())) {
            details.add(BusinessException.detail("is_default",
                    "默认路线不能删：删了该租户就没有默认路线 ⇒ 缺信号订单建单全部 fail-closed。"
                            + "请先把另一条设为默认，再删这条"));
        }
        List<ProductionRouteTemplate> all = allRoutings(tenantId);
        if (all.size() <= 1) {
            details.add(BusinessException.detail("id",
                    "这是该租户最后一条工艺路线：删了就没有任何路线可用 ⇒ 一张加工单也生成不了。"
                            + "请先新建另一条路线"));
        }
        if (!details.isEmpty()) {
            throw BusinessException.validationError("删除工艺路线未通过校验（" + details.size() + " 条问题）",
                    details, "先把另一条路线设为默认（PUT is_default=true），或先新建一条路线");
        }
        template.setDeleted(1);
        template.setUpdatedAt(OffsetDateTime.now());
        productionRouteTemplateMapper.updateById(template);
        log.info("删除工艺路线: tenantId={}, routingId={}, name={}", tenantId, template.getId(), template.getName());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", template.getId());
        result.put("deleted", true);
        return result;
    }

    /**
     * 主线护栏（**唯一一份**：新建与改主线共用）。违规**一次报全**，每条带
     * {@code field}（{@code mainline} / {@code mainline[i]} / {@code must_finish}）。
     *
     * <p>主线存的是**逻辑工序名**（与 {@code OPERATION_LOGICAL_NAMES} 值域一致），
     * 但商家在界面上看到的是工序库里的**变体名**（{@code 精裁-布}）⇒ 校验时两态都接受：
     * 先按原样查库，查不到再按 {@code variantNameOf} 反查（避免「界面上选得出、后端说不存在」）。</p>
     */
    private void validateMainline(List<String> mainline, Long tenantId) {
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        if (mainline.isEmpty()) {
            details.add(BusinessException.detail("mainline", "主线不能为空：一条路线至少要有 1 道工序"));
        }
        Map<String, ProductionOperation> library = activeOperationsByName(tenantId);
        Map<String, Map<String, Object>> catalog = productionOperationQueryService.operationsByName(tenantId);
        Set<String> seen = new LinkedHashSet<>();
        boolean anyMustFinish = false;
        for (int i = 0; i < mainline.size(); i++) {
            String name = mainline.get(i);
            String field = "mainline[" + i + "]";
            if (!StringUtils.hasText(name)) {
                details.add(BusinessException.detail(field, "工序名不能为空"));
                continue;
            }
            // ⚠️ 判重键必须是**归一后的逻辑名**，不是原始字符串（issue #4520）。
            // 主线里合法出现两种写法：逻辑名（`精裁`，种子/矩阵的行键）与工序库变体名（`精裁-布`，
            // `production_operations.name` / 「添加工序」选择器）。它们是**同一道工序**，但**字符串不同**
            // ⇒ 按原始字符串判重会放行 `["精裁", …, "精裁-布"]` ⇒ 实例化出两道 `精裁`
            // ⇒ **工人按两遍单价拿钱**。归一口径复用 P2b 的 `normalizeOperationName`
            // （**不在此另存映射表** —— 那就是第二份口径，本仓明令禁止）。
            String logicalName = productionOperationQueryService.normalizeOperationName(name);
            if (!seen.add(logicalName)) {
                details.add(BusinessException.detail(field,
                        String.format("工序「%s」重复出现：同一道工序在一条路线里只能出现一次"
                                        + "（否则工人按两遍单价拿钱）。⚠️ 注意「%s」与它的另一种写法"
                                        + "（如「%s」/「%s」）是**同一道工序**，归一名都是「%s」",
                                name, name, name + "-布", name + "-纱", logicalName)));
                continue;
            }
            ProductionOperation op = library.get(name);
            if (op == null) {
                // 逻辑名（新结构的书写形态）⇒ 反查该租户库里的变体名
                String variant = productionOperationQueryService.variantNameOf(
                        productionOperationQueryService.normalizeOperationName(name), null, catalog);
                op = variant == null ? null : library.get(variant);
            }
            if (op == null) {
                details.add(BusinessException.detail(field,
                        String.format("工序「%s」在工序库中不存在或已停用：请先在「工序库」新增该工序，或从库里已有的工序里选", name)));
                continue;
            }
            if (Boolean.TRUE.equals(op.getIsMustFinish())) {
                anyMustFinish = true;
            }
        }
        if (!mainline.isEmpty() && !anyMustFinish && details.isEmpty()) {
            // 只有当主线本身合法时才单独报这条（否则用户会同时看到「工序不存在」与「缺少必完工序」，
            // 而后者在前者修好前根本无从判断 —— 那才是噪音）
            details.add(BusinessException.detail("must_finish",
                    "主线中至少要有 1 道必完工序：必完工序全绿是加工单完工判定的唯一依据，一道都没有 ⇒ 这张单永远完不了工"));
        }
        if (!details.isEmpty()) {
            throw BusinessException.validationError(
                    String.format("工艺路线主线未通过校验（%d 条问题）", details.size()),
                    details,
                    "逐条修好后重新提交；工序库目录查看入口 GET /api/admin/production/operations-catalog");
        }
    }

    /**
     * 把该租户当前的默认路线降级（**恰一条默认**的不变式）。
     *
     * <p>必须在**同事务**里先降级再提升：DB 的部分唯一索引
     * {@code uk_production_route_templates_tenant_default} 只允许一行 {@code is_default AND deleted=0}
     * ⇒ 先提升会当场撞索引（500），先降级才是原子切换。</p>
     *
     * @param keepId 例外（不改动它自己）
     */
    private void demoteCurrentDefault(Long tenantId, String keepId) {
        for (ProductionRouteTemplate other : allRoutings(tenantId)) {
            if (Objects.equals(other.getId(), keepId) || !Boolean.TRUE.equals(other.getIsDefault())) {
                continue;
            }
            other.setIsDefault(false);
            other.setUpdatedAt(OffsetDateTime.now());
            productionRouteTemplateMapper.updateById(other);
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

    private ProductionRouteTemplate findRouting(String id, Long tenantId) {
        ProductionRouteTemplate template = id == null ? null : productionRouteTemplateMapper.selectById(id);
        if (template == null || !tenantId.equals(template.getTenantId())
                || !Integer.valueOf(0).equals(template.getDeleted())) {
            throw BusinessException.notFound("工艺路线");
        }
        return template;
    }

    private ProductionRouteSignal findSignal(String id, Long tenantId) {
        ProductionRouteSignal row = id == null ? null : productionRouteSignalMapper.selectById(id);
        if (row == null || !tenantId.equals(row.getTenantId())
                || !Integer.valueOf(0).equals(row.getDeleted())) {
            throw BusinessException.notFound("信号映射");
        }
        return row;
    }

    /** 全部未软删路线模板（含 disabled：重名判据要覆盖停用行，否则会撞 DB 唯一索引）。 */
    private List<ProductionRouteTemplate> allRoutings(Long tenantId) {
        List<ProductionRouteTemplate> rows = productionRouteTemplateMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteTemplate>()
                        .eq(ProductionRouteTemplate::getTenantId, tenantId)
                        .eq(ProductionRouteTemplate::getDeleted, 0));
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

    /**
     * 追加一行版本账（路线变更留痕：路线是计件工资与完工判定的唯一输入）。
     *
     * <p>V71 的版本表沿用旧路线的 {@code curtain_type} / {@code craft} 两列（历史形态）；
     * 新结构里路线**没有部位×工艺维**（工艺已降为规则触发键）⇒ 两列留 {@code null}
     * （列本身可空；改列需新迁移，不在本单）。</p>
     */
    private void appendVersion(ProductionRouteTemplate template, Long tenantId, List<String> mainline) {
        productionRoutingVersionMapper.insert(ProductionRoutingVersion.builder()
                .tenantId(tenantId)
                .routingId(template.getId())
                .curtainType(null)
                .craft(null)
                .operations(mainline)
                .operationCount(mainline.size())
                .createdAt(OffsetDateTime.now())
                .deleted(0)
                .build());
    }

    // ══════════════════════════════ 解析工具 ══════════════════════════════

    /**
     * JSON 数组 → 有序字符串列表（{@code null} / 非数组 ⇒ **空列表**）。
     *
     * <p>与旧 {@code operations(body)} 的差别：那个用 {@code null} 区分「没给这个字段」与
     * 「给了空数组」（改序列必须给全量）；本类改用 {@code body.containsKey(...)} 做这个区分
     * （部分更新语义：{@code {name?, is_default?, mainline?}} 只写出现的字段）⇒ 本方法只管**取值**。</p>
     */
    private static List<String> stringList(Object raw) {
        List<String> names = new ArrayList<>();
        if (raw instanceof List<?> list) {
            for (Object item : list) {
                if (item != null) {
                    names.add(String.valueOf(item).trim());
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
