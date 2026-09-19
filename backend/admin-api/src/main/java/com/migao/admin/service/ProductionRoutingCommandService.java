package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.entity.ProductionRoutingVersion;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import com.migao.admin.mapper.ProductionRoutingVersionMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
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
     * 条件工序规则的**触发维闭词表**（与 V71 的 {@code CHECK (trigger_kind IN (...))} 同口径，
     * issue #4616）。{@code shaped} 是表结构预留、**无种子行** ⇒ **不在**本集合（收到即 422）。
     */
    private static final Set<String> TRIGGER_KINDS = Set.of("craft", "option", "processing_item");

    /** 规则动作（路线编排档）：插入 / 移除（与读面 {@code ROUTE_ACTIONS} 同口径）。 */
    private static final Set<String> ACTIONS = Set.of("insert", "remove");

    private static final String TRIGGER_KIND_OPTION = "option";
    private static final String TRIGGER_KIND_CRAFT = "craft";
    private static final String TRIGGER_KIND_PROCESSING_ITEM = "processing_item";

    /**
     * 新路线的默认适用帘种集合（取值域同 {@code production_operation_positions.position}）。
     *
     * <p>为什么给默认而不是要求必填：V71/V72 种子路线就是「一条主线适用全部三种帘种」，
     * 前端「新建路线」也只需要先给个名字 ⇒ 强制填三元素数组只是摩擦。
     * 要收窄适用范围的商家可显式给 {@code positions}。</p>
     *
     * <p>issue #4614：与新增工序的默认「适用部位」是**同一份**（引用
     * {@link ProductionOperationQueryService#BASELINE_POSITIONS}）—— 各写一份必然漂移。</p>
     */
    private static final List<String> DEFAULT_POSITIONS = ProductionOperationQueryService.BASELINE_POSITIONS;

    private final ProductionRouteTemplateMapper productionRouteTemplateMapper;
    private final ProductionRoutingVersionMapper productionRoutingVersionMapper;
    private final ProductionOperationMapper productionOperationMapper;
    private final ProductionOperationQueryService productionOperationQueryService;
    /** 规则表（issue #4567 起本类也写它：特殊选项对客单价 —— 只写一列，见该 mapper 的 default 方法）。 */
    private final ProductionRouteRuleMapper productionRouteRuleMapper;
    /**
     * 加工项目录（issue #4616）：{@code trigger_kind='processing_item'} 的触发值必须**存在于目录**
     * （触发键 = 订单行 {@code processingInfo.processingItems[].name}，精确相等 ⇒ 目录里没有就永不命中）。
     */
    private final ProcessingItemMapper processingItemMapper;

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
        // 落库**前**归一为逻辑名（issue #4609）：老 bundle / 脚本 / 任何客户端传变体名（`精裁-布`）
        // 都污染不了主线 —— 主线一旦存变体名，实例化按逻辑名建键就查不到 ⇒ 该道工序被**静默丢掉**。
        List<String> mainline = normalizeMainline(stringList(body == null ? null : body.get("mainline")));
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
        // 与 createRouting 同一份口径：落库前归一为逻辑名（issue #4609，见 normalizeMainline）。
        List<String> mainline = normalizeMainline(stringList(body.get("mainline")));
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
        // ⚠️ 必须**显式写列**（issue #4608），不得写成 `setDeleted(1); updateById(template);`：
        // MP 全局逻辑删除（application.yml 的 mybatis-plus.global-config.db-config.logic-delete-field=deleted）
        // 会把逻辑删除字段从 updateById 的 SET 子句里**剔除** ⇒ deleted 永不落库，而调用仍返回成功
        // = 删除静默 no-op（用户实测「提示成功但数据还在」）。显式 .set(...) 绕过字段剔除，
        // 同时保住审计字段 updated_at（「谁在什么时候删的」是排查工序错配的唯一证据）。
        productionRouteTemplateMapper.update(null, new LambdaUpdateWrapper<ProductionRouteTemplate>()
                .eq(ProductionRouteTemplate::getId, id)
                .set(ProductionRouteTemplate::getDeleted, 1)
                .set(ProductionRouteTemplate::getUpdatedAt, OffsetDateTime.now()));
        log.info("删除工艺路线: tenantId={}, routingId={}, name={}", tenantId, template.getId(), template.getName());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", template.getId());
        result.put("deleted", true);
        return result;
    }

    /**
     * 软删条件工序规则（{@code DELETE /route-rules/{id}}，issue #4587 ④）。
     *
     * <p><b>为什么无硬护栏</b>：规则只影响「插一道工序 / 删一道工序 / 覆盖计件系数」——
     * 删错了重加即可（与路线的「删默认 ⇒ 建单全 fail-closed」不同，规则没有那种不可逆后果）。
     * 但**仍不物理删**：{@code deleted=1} 让「谁在什么时候删掉了哪条规则」留得下证据
     * （排查工序顺序错时它是唯一线索，与路线/信号同口径）。</p>
     *
     * <p>不存在 / 跨租户 / 已软删 ⇒ <b>404</b>（与 {@code PUT /route-rules/{id}/customer-unit-price}
     * 同口径：已软删的行不该再被写面寻址）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> deleteRouteRule(String id, Long tenantId) {
        ProductionRouteRule rule = id == null ? null : productionRouteRuleMapper.selectById(id);
        if (rule == null || !tenantId.equals(rule.getTenantId())
                || !Integer.valueOf(0).equals(rule.getDeleted())) {
            throw BusinessException.notFound("条件工序规则");
        }
        // 同 deleteRouting：显式写列（issue #4608）—— updateById 会把 deleted 从 SET 里剔除 ⇒ 静默 no-op。
        productionRouteRuleMapper.update(null, new LambdaUpdateWrapper<ProductionRouteRule>()
                .eq(ProductionRouteRule::getId, id)
                .set(ProductionRouteRule::getDeleted, 1)
                .set(ProductionRouteRule::getUpdatedAt, OffsetDateTime.now()));
        log.info("软删条件工序规则: tenantId={}, ruleId={}, trigger={}",
                tenantId, rule.getId(), rule.getTriggerValue());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", rule.getId());
        result.put("deleted", true);
        return result;
    }

    // ══════════════════ 特殊选项对客单价（元/套，issue #4567）══════════════════

    /**
     * 改**特殊选项**的对客单价（{@code PUT /route-rules/{id}/customer-unit-price}，**元/套**）。
     *
     * <p><b>两套账不互读</b>（设计 §4.1）：本方法是**对客售价**账（{@code production_route_rules}
     * 的元/套列）的唯一写点；工人**计件**账是 {@code production_operations.unit_price} /
     * {@code production_route_rules.factor}，由 {@link ProductionOperationCommandService} 写 ——
     * 本方法**只** {@code SET} 那一列 + {@code updated_at}，绝不碰 {@code factor}。</p>
     *
     * <p><b>护栏（逐条 {@code error.details}，不静默）</b>：</p>
     * <ul>
     *   <li>行不存在 / 非本租户 / 已软删 ⇒ <b>404</b>（{@code BusinessException.notFound}）；</li>
     *   <li>该行 {@code trigger_kind != 'option'} ⇒ <b>422</b> —— **只有特殊选项按套计价**，
     *       工艺变体（{@code craft}）不按套收费（写了也会被取价侧忽略 ⇒ 商家以为改了、其实没生效）；</li>
     *   <li>价必须 ≥ 0 且**最多两位小数**、非数值 ⇒ <b>422</b>（列是 {@code NUMERIC(12,2)}：
     *       静默四舍五入会让「我填的 6.005」变成 6.01 而无人知道）；</li>
     *   <li>{@code null} / 空串 ⇒ <b>允许</b> = 显式改回**未定价**（语义是「还没定价」而不是 0 元）。</li>
     * </ul>
     *
     * @return 更新后的规则展示形态（与读面 {@code GET /route-rules} 的单项**同构**）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> updateRuleCustomerUnitPrice(String id, Map<String, Object> body, Long tenantId) {
        ProductionRouteRule rule = id == null ? null : productionRouteRuleMapper.selectById(id);
        if (rule == null || !tenantId.equals(rule.getTenantId())
                || !Integer.valueOf(0).equals(rule.getDeleted())) {
            throw BusinessException.notFound("条件工序规则");
        }
        if (!"option".equals(rule.getTriggerKind())) {
            throw BusinessException.validationError("只有特殊选项按套计价（工艺变体不按套收费）",
                    List.of(BusinessException.detail("trigger_kind",
                            String.format("这条规则的触发维是「%s」，不是特殊选项（option）—— "
                                    + "工艺变体按工序单价计件，不按套收费", rule.getTriggerKind()))),
                    "只给 trigger_kind='option' 的规则定价（读面 GET /api/admin/production/route-rules 带 trigger_kind）");
        }
        Object raw = body == null ? null : body.get("customer_unit_price");
        BigDecimal price = optionalCustomerPrice(raw);

        productionRouteRuleMapper.updateCustomerUnitPrice(rule.getId(), tenantId, price);
        log.info("改特殊选项对客单价: tenantId={}, ruleId={}, value={}", tenantId, rule.getId(), price);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", rule.getId());
        result.put("trigger_kind", rule.getTriggerKind());
        result.put("trigger_value", rule.getTriggerValue());
        result.put("customer_unit_price", price);
        return result;
    }

    /**
     * 新建**条件工序规则**（issue #4616 起端点**通用化**：`trigger_kind` ∈ 闭词表
     * `craft` / `option` / `processing_item`；缺省 = `option`，老调用方行为一字不变）。
     *
     * <p><b>为什么必须通用化（用户裁定 2026-09-19）</b>：「现在的问题是**没有入口往条件工序规则中
     * 添加新的工艺和加工项**」—— 端点此前把 {@code triggerKind("option")} **写死** ⇒ 商家新增一个
     * 工艺（如「罗马帘」）或加工项（如「拼接」）之后**没有办法**让它在订单里插/删工序 ⇒ 该订单
     * **静默少工序**（加工单与商家配置不一致，且不报错）。</p>
     *
     * <p><b>护栏（逐条 {@code error.details}，一次报全，不静默）</b>：</p>
     * <ul>
     *   <li>{@code trigger_kind} 不在闭词表 ⇒ <b>422</b>（{@code shaped} 是 V71 的表结构预留、
     *       **无种子行** ⇒ 收到即拒，不静默落一行没人消费的规则）；</li>
     *   <li>{@code trigger_value} **必须存在于对应词表**：{@code craft} ⇒ 活跃**工艺词表**
     *       （{@code production_crafts}）；{@code processing_item} ⇒ **加工项目录**
     *       （{@code processing_items}）；{@code option} ⇒ 特殊选项名（**可新建**，无词表）——
     *       不存在/已停用 ⇒ <b>422</b>（触发键查不到 ⇒ 规则永远不命中 = 商家以为配了、加工单上没有）；</li>
     *   <li>{@code customer_unit_price} **只允许 {@code trigger_kind='option'}**（craft/加工项行必须
     *       为空，否则 422）—— 「两套账不互读」的既有边界（工艺变体按工序单价**计件**、特殊选项按
     *       **套**对客收费），**不许放宽**；</li>
     *   <li>{@code action} ∈ {@code insert} / {@code remove}；{@code operation} / {@code after_operation}
     *       用**逻辑工序名**（复用既有校验）；{@code remove} 不接受锚点；</li>
     *   <li>目标工序 / 锚点不在工序库 ⇒ <b>422</b>（规则命中后插不进来 = 黑洞，V72 种子同款护栏）；</li>
     *   <li>同一条「kind + 触发值 + 动作 + 目标工序」已存在 ⇒ <b>409</b>
     *       （对齐 DB 唯一索引 {@code uk_production_route_rules_tenant_trigger_operation}）；</li>
     *   <li>单价：可空（= 未定价 ≠ 0）；非数值 / 负数 / 超两位小数 ⇒ <b>422</b>（同
     *       {@link #updateRuleCustomerUnitPrice} 的口径）。</li>
     * </ul>
     *
     * <p><b>反向护栏（本单冻结）</b>：缺 {@code trigger_kind} ⇒ **默认 {@code option}** ——
     * 老调用方 / 老 bundle 的 body（只有 {@code trigger_value} 等）行为**一字不变**。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> createRouteRule(Map<String, Object> body, Long tenantId) {
        String triggerKind = optionalText(body == null ? null : body.get("trigger_kind"));
        if (triggerKind == null) {
            triggerKind = TRIGGER_KIND_OPTION;   // 反向护栏：老调用方一字不变
        }
        String triggerValue = requiredText(body == null ? null : body.get("trigger_value"), "trigger_value");
        // 落库前**归一**（issue #4643，与主线 #4609 同一范式）：规则表存的是**逻辑工序名**
        // （矩阵行键 / 主线同口径），而 API / 脚本 / 老 bundle 可以传变体名（`精裁-布`）——
        // 原样落库 ⇒ 读面回传变体名 ⇒ 规则表 / 删除确认文案上屏两套名。归一表只有
        // `normalizeOperationName` 一份（**不在此另存映射**）；幂等：逻辑名再归一不变。
        String operation = productionOperationQueryService.normalizeOperationName(
                requiredText(body == null ? null : body.get("operation"), "operation"));
        String afterOperation = productionOperationQueryService.normalizeOperationName(
                optionalText(body == null ? null : body.get("after_operation")));
        String action = optionalText(body == null ? null : body.get("action"));
        if (action == null) {
            action = "insert";   // 反向护栏：老调用方只有 insert（端点此前写死 insert）
        }
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        if (!TRIGGER_KINDS.contains(triggerKind)) {
            details.add(BusinessException.detail("trigger_kind", String.format(
                    "触发类型「%s」不在取值域内（只能是 工艺 craft / 特殊选项 option / 加工项 processing_item）"
                            + "—— `shaped` 是表结构预留、没有规则行可落，故不收", triggerKind)));
        }
        if (!ACTIONS.contains(action)) {
            details.add(BusinessException.detail("action", String.format(
                    "动作「%s」不在取值域内（只能是 insert 插入 / remove 移除）", action)));
        }
        if (TRIGGER_KINDS.contains(triggerKind) && !triggerValueExists(triggerKind, triggerValue, tenantId)) {
            details.add(BusinessException.detail("trigger_value", triggerValueMissingReason(triggerKind, triggerValue)));
        }
        // 两套账不互读：对客单价只属于特殊选项（craft / 加工项行必须为空）
        boolean hasPrice = optionalText(body == null ? null : body.get("customer_unit_price")) != null;
        if (hasPrice && !TRIGGER_KIND_OPTION.equals(triggerKind)) {
            details.add(BusinessException.detail("customer_unit_price", String.format(
                    "对客单价（元/套）只属于**特殊选项**（trigger_kind='option'）—— 「%s」触发的规则按工序单价"
                            + "**计件**（给工人），两套账不互读，这条规则不能带对客单价",
                    TRIGGER_KINDS.contains(triggerKind) ? triggerKind : "该类型")));
        }
        if ("remove".equals(action) && afterOperation != null) {
            details.add(BusinessException.detail("after_operation",
                    "「移除」动作没有锚点（锚点只对「插入」有意义）—— 请清掉 after_operation，或把动作改成 insert"));
        }
        if (!logicalOperationExists(operation, tenantId)) {
            details.add(BusinessException.detail("operation", String.format(
                    "工序库里没有「%s」—— 规则指向一道不存在的工序 ⇒ 命中后插不进来，这条规则等于黑洞",
                    operation)));
        }
        if (afterOperation != null && !logicalOperationExists(afterOperation, tenantId)) {
            details.add(BusinessException.detail("after_operation", String.format(
                    "锚点工序「%s」不在工序库里 ⇒ 插不到它后面（会落到末尾，与商家预期不符）", afterOperation)));
        }
        if (!details.isEmpty()) {
            throw BusinessException.validationError("条件工序规则校验未通过", details,
                    "按上面每一条改：触发类型 / 触发值 / 动作 / 目标工序 / 锚点 / 对客单价 —— 全部合规后重试");
        }
        BigDecimal price = optionalCustomerPrice(body == null ? null : body.get("customer_unit_price"));

        for (ProductionRouteRule existing : productionOperationQueryService.routeRules(tenantId)) {
            if (Objects.equals(existing.getTriggerKind(), triggerKind)
                    && Objects.equals(existing.getTriggerValue(), triggerValue)
                    && Objects.equals(existing.getAction(), action)
                    // 存量行可能是变体名（旧前端写进来的）⇒ 比对**归一后**的工序名：
                    // 否则「精裁-布」与「精裁」被当成两条规则、落两条逻辑上重复的规则
                    // （DB 唯一索引按原文比，拦不住）。只影响比较，不写库、不动其它字段。
                    && Objects.equals(productionOperationQueryService.normalizeOperationName(
                            existing.getOperation()), operation)) {
                throw BusinessException.conflict(
                        String.format("「%s」触发的规则已存在（同一条「%s %s」的规则）",
                                triggerValue, actionText(action), operation),
                        "要换目标工序 / 锚点请先停用旧规则（查看入口 GET /api/admin/production/route-rules）；"
                                + "特殊选项改单价请用 PUT /api/admin/production/route-rules/{id}/customer-unit-price");
            }
        }

        Integer priority = optionalInt(body == null ? null : body.get("priority"));
        ProductionRouteRule row = ProductionRouteRule.builder()
                .tenantId(tenantId)
                .triggerKind(triggerKind)
                .triggerValue(triggerValue)
                .position(optionalText(body == null ? null : body.get("position")))
                .action(action)
                .operation(operation)
                .afterOperation(afterOperation)
                .priority(priority != null ? priority : nextRulePriority(tenantId))
                .customerUnitPrice(price)
                .status("active")
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .deleted(0)
                .build();
        productionRouteRuleMapper.insert(row);
        log.info("新建条件工序规则: tenantId={}, kind={}, value={}, action={}, operation={}, price={}",
                tenantId, triggerKind, triggerValue, action, operation, price);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", row.getId());
        result.put("trigger_kind", row.getTriggerKind());
        result.put("trigger_value", row.getTriggerValue());
        result.put("action", row.getAction());
        result.put("operation", row.getOperation());
        result.put("after_operation", row.getAfterOperation());
        result.put("priority", row.getPriority());
        result.put("customer_unit_price", price);
        return result;
    }

    /**
     * 新建**特殊选项**（{@code trigger_kind='option'} + {@code action='insert'}，issue #4570）——
     * 保留为 {@link #createRouteRule} 的**薄壳**：对外行为（含缺省 {@code trigger_kind} ⇒ option）
     * 一字不变，实现只有一份（issue #4616 通用化后不再有第二条创建路径）。
     */
    public Map<String, Object> createOptionRule(Map<String, Object> body, Long tenantId) {
        return createRouteRule(body, tenantId);
    }

    /** 触发值是否存在于对应词表（craft ⇒ 活跃工艺词表；processing_item ⇒ 加工项目录；option ⇒ 无词表，恒真）。 */
    private boolean triggerValueExists(String triggerKind, String triggerValue, Long tenantId) {
        if (TRIGGER_KIND_OPTION.equals(triggerKind)) {
            return true;   // 特殊选项名**可新建**（现状即如此）：没有第二份词表可查
        }
        if (TRIGGER_KIND_CRAFT.equals(triggerKind)) {
            return productionOperationQueryService.activeCraftNames(tenantId).contains(triggerValue);
        }
        List<ProcessingItem> items = processingItemMapper.selectList(
                new LambdaQueryWrapper<ProcessingItem>()
                        .eq(ProcessingItem::getTenantId, tenantId)
                        .eq(ProcessingItem::getDeleted, 0)
                        .eq(ProcessingItem::getStatus, "active"));
        if (items == null) {
            return false;
        }
        return items.stream().anyMatch(item -> Objects.equals(item.getName(), triggerValue));
    }

    /** 触发值不在词表时的**可行动**理由（逐 kind 说清去哪儿建）。 */
    private static String triggerValueMissingReason(String triggerKind, String triggerValue) {
        if (TRIGGER_KIND_CRAFT.equals(triggerKind)) {
            return String.format("工艺词表里没有活跃的「%s」—— 触发键查不到 ⇒ 这条规则永远不命中"
                    + "（商家以为配了、加工单上却没有），请先在「工艺词表」建这个工艺", triggerValue);
        }
        if (TRIGGER_KIND_PROCESSING_ITEM.equals(triggerKind)) {
            return String.format("加工项目录里没有活跃的「%s」—— 触发键 = 订单里的加工项名（**精确相等**），"
                    + "目录里没有就永远不命中，请先在「加工项管理」建这个加工项", triggerValue);
        }
        return String.format("触发值「%s」不可用", triggerValue);
    }

    private static String actionText(String action) {
        return "remove".equals(action) ? "移除" : "插入";
    }

    /** 新规则的默认优先级 = 本租户现有**最大优先级 + 10**（保证排在最后生效，顺序确定）。 */
    private int nextRulePriority(Long tenantId) {
        int max = 0;
        for (ProductionRouteRule rule : productionOperationQueryService.routeRules(tenantId)) {
            if (rule.getPriority() != null && rule.getPriority() > max) {
                max = rule.getPriority();
            }
        }
        return max + 10;
    }

    /**
     * 该**逻辑工序名**是否在该租户工序库里存在。
     *
     * <p>库里存的是**变体名**（{@code 精裁-布}），而规则表 {@code operation} 存的是**逻辑名**
     * （{@code 精裁}）⇒ 两态都接受：先按原样查库（部位无关的裸逻辑名，如 {@code 外帘打卷}），
     * 再按 {@link ProductionOperationQueryService#normalizeOperationName} 归一后比对。</p>
     */
    private boolean logicalOperationExists(String logicalName, Long tenantId) {
        return logicalOperationExistsIn(logicalName,
                productionOperationQueryService.operationsByName(tenantId).keySet());
    }

    /**
     * 该**逻辑工序名**是否在该租户工序库里有行 —— **唯一一份**存在性判据（规则写面与主线护栏共用）：
     * ① 库里有同名裸行（部位无关工序，如 {@code 外帘装袋}）；或 ② 库里有任一变体归一后等于它
     * （{@code 精裁-布} / {@code 精裁-纱} ⇒ {@code 精裁}）。归一表只有 {@code normalizeOperationName} 一份。
     */
    private boolean logicalOperationExistsIn(String logicalName, Set<String> libraryNames) {
        if (libraryNames.contains(logicalName)) {
            return true;
        }
        return libraryNames.stream().anyMatch(
                name -> logicalName.equals(productionOperationQueryService.normalizeOperationName(name)));
    }

    /**
     * 主线**落库前归一**：每一项按 {@link ProductionOperationQueryService#normalizeOperationName}
     * 换成逻辑工序名（{@code 精裁-布} → {@code 精裁}）。归一表只有这一份，**不在此另存映射**。
     *
     * <p>为什么必须在落库前（issue #4609）：主线是实例化的输入，而实例化按**逻辑名**建适用性矩阵的键
     * ⇒ 主线里存了变体名，那道工序在生成加工单时**查不到、被静默丢掉**（商家加了工序、加工单里没有，
     * 且无任何报错）。写面归一后，任何客户端 / 老 bundle / 脚本都污染不了主线。</p>
     */
    private List<String> normalizeMainline(List<String> mainline) {
        List<String> normalized = new ArrayList<>(mainline.size());
        for (String name : mainline) {
            normalized.add(productionOperationQueryService.normalizeOperationName(name));
        }
        return normalized;
    }

    /** 可空整数（`null` / 空串 ⇒ `null`；非整数 ⇒ 422）。 */
    private static Integer optionalInt(Object value) {
        String text = value == null ? "" : String.valueOf(value).trim();
        if (text.isEmpty()) {
            return null;
        }
        try {
            return Integer.valueOf(text);
        } catch (NumberFormatException e) {
            throw BusinessException.validationError("优先级必须是整数",
                    List.of(BusinessException.detail("priority", "优先级必须是整数")),
                    "填一个整数（越大越晚生效），或留空由系统排在最后");
        }
    }

    /** 可空文本（`null` / 空白 ⇒ `null`）。 */
    private static String optionalText(Object value) {
        String text = value == null ? null : String.valueOf(value).trim();
        return text == null || text.isEmpty() ? null : text;
    }

    /**
     * 对客单价解析（**只**给特殊选项用）：{@code null} / 空串 ⇒ {@code null}（= 未定价）；
     * 非数值 / 负数 / 超过两位小数 ⇒ 422 逐条理由。
     *
     * <p>为什么用 {@code setScale(2, UNNECESSARY)} 而不是 {@code round}：前者在「填了 6.005」时
     * **抛异常**（商家知道自己填多了），后者静默变成 6.01（改了钱且无人知道）。</p>
     */
    private static BigDecimal optionalCustomerPrice(Object value) {
        String text = value == null ? "" : String.valueOf(value).trim();
        if (text.isEmpty()) {
            return null;
        }
        BigDecimal price;
        try {
            price = new BigDecimal(text);
        } catch (NumberFormatException e) {
            throw BusinessException.validationError("单价必须是数字",
                    List.of(BusinessException.detail("customer_unit_price",
                            "单价必须是数字（元/套）；要表示「还没定价」请传 null 或空串，**不要**传 0")),
                    "填一个 ≥ 0 且最多两位小数的金额，或传 null 表示未定价");
        }
        if (price.signum() < 0) {
            throw BusinessException.validationError("单价不能为负",
                    List.of(BusinessException.detail("customer_unit_price", "单价不能为负（元/套）")),
                    "填一个 ≥ 0 的金额，或传 null 表示未定价");
        }
        try {
            return price.setScale(2, RoundingMode.UNNECESSARY);
        } catch (ArithmeticException e) {
            throw BusinessException.validationError("单价最多两位小数",
                    List.of(BusinessException.detail("customer_unit_price",
                            "单价最多两位小数（列是 NUMERIC(12,2)）—— 不接受静默四舍五入，请自己改到两位")),
                    "把单价改到最多两位小数后重试");
        }
    }

    /**
     * 主线护栏（**唯一一份**：新建与改主线共用）。违规**一次报全**，每条带
     * {@code field}（{@code mainline} / {@code mainline[i]} / {@code must_finish}）。
     *
     * <p><b>输入口径（issue #4609）</b>：调用方落库前已把每一项按
     * {@link ProductionOperationQueryService#normalizeOperationName} **归一为逻辑名**
     * （见 {@link #normalizeMainline}）⇒ 本方法只面对**逻辑名**，存在性也按逻辑名判
     * （{@link #logicalOperationExistsIn}：库里有同名裸行，或库里有任一变体归一后等于它）。</p>
     */
    private void validateMainline(List<String> mainline, Long tenantId) {
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        if (mainline.isEmpty()) {
            details.add(BusinessException.detail("mainline", "主线不能为空：一条路线至少要有 1 道工序"));
        }
        Map<String, ProductionOperation> library = activeOperationsByName(tenantId);
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
            // 调用方（createRouting / updateRouting）落库前已按同一份归一表把每一项归一为逻辑名
            // （issue #4609），故这里 `name` 与 `logicalName` 一般相同；判重仍按归一后的键，
            // 保证「同一道工序的两种写法」永远不会同时进主线（否则实例化出两道 ⇒ 工人按两遍单价拿钱）。
            String logicalName = productionOperationQueryService.normalizeOperationName(name);
            if (!seen.add(logicalName)) {
                // ⚠️ 文案**不回显原始输入**，也不得拼变体名（`name + "-布"` / `"-纱"`）—— issue #4647 / D3(a)：
                // 本页护栏理由区**直接渲染** `details[].message`（`routings/page.tsx` 的
                // `routingGuardReasons(e)` → `reasons.map(...)`，而 `describeRoutingGuard` 只加前缀、**不删内容**）
                // ⇒ 拼进去的变体名会**原样上屏**（复验实测产出「精裁-布」/「精裁-纱」）。
                // 改说**根因**（两条指向同一道逻辑工序）+ 处置，商家据此能自己认出来是哪两条。
                details.add(BusinessException.detail(field,
                        String.format("工序「%s」重复出现：同一道工序在一条路线里只能出现一次"
                                        + "（否则工人按两遍单价拿钱）。⚠️ 这两条指向**同一道逻辑工序**"
                                        + "（读时归一后同名「%s」）—— 去掉一条即可；"
                                        + "部位不用写进工序名，它在下面勾选",
                                name, logicalName)));
                continue;
            }
            // 存在性判据按**逻辑名**（issue #4609）：工序库存的是**变体名**（`精裁-布`），
            // 而主线存的是逻辑名（`精裁`）⇒ 判据 = ① 库里有同名裸行（部位无关工序，如 `外帘装袋`）
            // 或 ② 库里有任一变体归一后等于它（`精裁-布` / `精裁-纱` ⇒ `精裁`）。
            // ⚠️ 改前这里只按 `variantNameOf(逻辑名, null, catalog)` 反查 ⇒ **逻辑名一律查不到**
            // （部位无关工序才查得到）⇒ 前端改成写逻辑名后，保存会被自己拒掉（「工序不存在」）。
            ProductionOperation op = library.get(logicalName);
            if (op == null && !logicalOperationExistsIn(logicalName, library.keySet())) {
                details.add(BusinessException.detail(field,
                        String.format("工序「%s」在工序库中不存在或已停用：请先在「工序库」新增该工序，或从库里已有的工序里选", name)));
                continue;
            }
            if (op != null && Boolean.TRUE.equals(op.getIsMustFinish())) {
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

    // ══════════════════════ 信号映射写面**已退役**（issue #4452）══════════════════════
    //
    // `POST/PUT/DELETE /production/route-signals` 三个端点**已删除**（连同本类的
    // `createSignal` / `updateSignal` / `deleteSignal` 与三条护栏 validateSignalUniqueness /
    // nextPriority / findSignal / allSignals）。
    //
    // 为什么退役：`production_route_signals` 是「关键词 → 名词」的**对照表** + `contains` 文本匹配，
    // 匹配源是**自由文本**（加工项名 / options / 商品名 / 销售方式）。它不表达业务逻辑，
    // 且判据绑在「研发改的常量表」上而加工项目录是**商家可自定义的业务数据**
    // ⇒ 商家每加一个自定义名就多一分静默错配（craft-routing-customization.md §4 P2 实证：
    // 纱帘订单拿到布帘 11 道工序，工序与工资全错）。
    //
    // issue #4452 起：部位维改走 `componentRole` 受控枚举 / V63 `curtain_type` 列，
    // 工艺维改走加工项的**显式声明** `processing_items.craft_hint`；
    // 信号表**降级为存量单兜底**（表不删 —— 存量单仍需派生），故读面 `GET /route-signals` 暂留。
    // ⇒ 让商家继续往兜底表里加行，只会让「已经不该被读的判据」继续增长，故写面先退场。

    // ══════════════════════════════ 读取 / 版本账 ══════════════════════════════

    private ProductionRouteTemplate findRouting(String id, Long tenantId) {
        ProductionRouteTemplate template = id == null ? null : productionRouteTemplateMapper.selectById(id);
        if (template == null || !tenantId.equals(template.getTenantId())
                || !Integer.valueOf(0).equals(template.getDeleted())) {
            throw BusinessException.notFound("工艺路线");
        }
        return template;
    }

    /** 全部未软删路线模板（含 disabled：重名判据要覆盖停用行，否则会撞 DB 唯一索引）。 */
    private List<ProductionRouteTemplate> allRoutings(Long tenantId) {
        List<ProductionRouteTemplate> rows = productionRouteTemplateMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteTemplate>()
                        .eq(ProductionRouteTemplate::getTenantId, tenantId)
                        .eq(ProductionRouteTemplate::getDeleted, 0));
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
     * <p><b>只写新模型的三列</b>：{@code routing_id} = {@code production_route_templates.id}
     * （V85 / #4581 起该列的外键就指向新表）、{@code operations} = 变更后的有序主线、
     * {@code operation_count} = 主线道数。</p>
     *
     * <p><b>为什么不再传 {@code curtainType} / {@code craft}</b>：新结构里路线**没有部位×工艺维**
     * （工艺已降为 {@code production_route_rules} 的触发键）⇒ 这两列**只承载历史行**。
     * 旧实现无条件传 {@code null}，而 V60 的两列是 {@code NOT NULL} ⇒ 每行 INSERT 都被 PG 拒
     * ⇒ 新建路线 / 改主线**恒 500**（P0，issue #4581；V85 已把两列放开为可空）。</p>
     */
    private void appendVersion(ProductionRouteTemplate template, Long tenantId, List<String> mainline) {
        productionRoutingVersionMapper.insert(ProductionRoutingVersion.builder()
                .tenantId(tenantId)
                .routingId(template.getId())
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
