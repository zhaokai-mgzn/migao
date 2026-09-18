package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.Map;
import java.util.Set;

/**
 * 工序库**写面**（issue #4204，P1）：唯一入口 = PUT /api/admin/production/operations/{id}。
 *
 * <p><b>为什么单独一个类而不是塞进 {@link ProductionOperationQueryService}</b>：那个类自述
 * 「只读边界」且只有 SELECT（切库后的工序来源读它）；把写操作塞进去会让「谁在改工序库」
 * 变得不可 grep。读写分开，写面只有本类。</p>
 *
 * <p><b>单价版本化口径（冻结契约，真值源 §2/§4）</b>：改价 = 同一事务里写两处 ——
 * ① {@code production_operations.unit_price}（新单实例化的取值源）；
 * ② {@code production_operation_price_versions} 追加一行（当前价 = 最新版本行，构成调价账）。
 * {@code processing_position_operations.unit_price} 是**生成时的快照**，本类**永不**写它：
 * 调价只影响新报工，历史报工按当时价（逐笔可追溯）。</p>
 *
 * <p><b>权限</b>：端点声明方法级 {@code processing:manage}（类级 {@code order:list} 是读口径，
 * 覆盖不了写操作）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionOperationCommandService {

    /** 工序状态取值（V49 `status VARCHAR(16) DEFAULT 'active'`：active / disabled）。 */
    private static final Set<String> STATUSES = Set.of("active", "disabled");

    /**
     * 工序作用域取值（V67 `scope VARCHAR(16) NOT NULL DEFAULT 'position'`，issue #4384 A1）：
     * {@code position} = 部位级（每部位一次）/ {@code set} = 套级（**每樘窗一次**）。
     *
     * <p>用户裁定（2026-09-19）「套级工序先按每樘窗一次实现，打卷是否每帘一次**留成可配**」
     * ⇒ 本常量 + 下方校验就是「可配」的落码形态；闭词表与迁移 V67 的列注释同口径
     * （自创第三值会让读面/实例化侧的口径分裂）。</p>
     */
    private static final Set<String> SCOPES = Set.of("position", "set");

    /** 缺省作用域 = 部位级（与 V67 的列默认值同口径；默认 set 会把新建工序静默去重）。 */
    private static final String DEFAULT_SCOPE = "position";

    private final ProductionOperationMapper productionOperationMapper;
    private final ProductionOperationPriceVersionMapper priceVersionMapper;
    private final ProductionOperationQueryService productionOperationQueryService;

    /**
     * 更新工序（部分更新：只写 body 里出现的字段；未出现的字段保持原值）。
     *
     * @param body 可含 unit_price / is_must_finish / is_start_marker / status / unit /
     *             group_name / sort_order / scope（scope = 部位级 position / 套级 set，issue #4384 A1）
     * @return 更新后的工序（形态 = {@link ProductionOperationQueryService#operationView}，与目录项同构）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> update(String id, Map<String, Object> body, Long tenantId) {
        ProductionOperation op = productionOperationMapper.selectById(id);
        if (op == null || !tenantId.equals(op.getTenantId()) || !Integer.valueOf(0).equals(op.getDeleted())) {
            throw BusinessException.notFound("工序");
        }
        // 改价前的单价必须先留存：下面 op 会被就地改成新值（用于响应），改完再比就恒等 ⇒ 版本账永空
        BigDecimal previousPrice = nz(op.getUnitPrice());
        // 只带变更字段的部分实体（updateById 忽略 null ⇒ 不在 body 里的列一律不碰）
        ProductionOperation partial = ProductionOperation.builder()
                .id(op.getId())
                .updatedAt(OffsetDateTime.now())
                .build();
        BigDecimal newPrice = null;
        if (body != null) {
            if (body.containsKey("unit_price")) {
                newPrice = decimal(body.get("unit_price"), "unit_price");
                if (newPrice.signum() < 0) {
                    throw BusinessException.validationError("unit_price 不能为负");
                }
                partial.setUnitPrice(newPrice);
                op.setUnitPrice(newPrice);
            }
            if (body.containsKey("unit")) {
                String unit = requiredText(body.get("unit"), "unit");
                partial.setUnit(unit);
                op.setUnit(unit);
            }
            if (body.containsKey("group_name")) {
                String group = requiredText(body.get("group_name"), "group_name");
                partial.setGroupName(group);
                op.setGroupName(group);
            }
            if (body.containsKey("status")) {
                String status = requiredText(body.get("status"), "status");
                if (!STATUSES.contains(status)) {
                    throw BusinessException.validationError("status 仅支持 active/disabled");
                }
                partial.setStatus(status);
                op.setStatus(status);
            }
            if (body.containsKey("scope")) {
                // 作用域可配（issue #4384 A1）：用户裁定「套级先按每樘窗一次实现，打卷是否每帘一次
                // 留成可配」⇒ 商家必须能改这一档。校验同 status 口径（闭词表 + 可读理由）。
                String scope = scope(body.get("scope"));
                partial.setScope(scope);
                op.setScope(scope);
            }
            if (body.containsKey("sort_order")) {
                int sortOrder = decimal(body.get("sort_order"), "sort_order").intValue();
                partial.setSortOrder(sortOrder);
                op.setSortOrder(sortOrder);
            }
            if (body.containsKey("is_must_finish")) {
                boolean mustFinish = bool(body.get("is_must_finish"), "is_must_finish");
                partial.setIsMustFinish(mustFinish);
                op.setIsMustFinish(mustFinish);
            }
            if (body.containsKey("is_start_marker")) {
                boolean startMarker = bool(body.get("is_start_marker"), "is_start_marker");
                partial.setIsStartMarker(startMarker);
                op.setIsStartMarker(startMarker);
            }
        }
        int rows = productionOperationMapper.updateById(partial);
        if (rows == 0) {
            throw BusinessException.notFound("工序");
        }
        // 单价真的变了才追加版本行（同价重复提交是幂等空操作，不制造无意义的调价账）
        if (newPrice != null && newPrice.compareTo(previousPrice) != 0) {
            priceVersionMapper.insert(ProductionOperationPriceVersion.builder()
                    .tenantId(tenantId)
                    .operationId(op.getId())
                    .unitPrice(newPrice)
                    .createdAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
            log.info("工序调价: operationId={}, name={}, {} -> {}",
                    op.getId(), op.getName(), previousPrice, newPrice);
        }
        return productionOperationQueryService.operationView(op);
    }

    /**
     * 新增工序（issue #4308 交付物 4：{@code POST /api/admin/production/operations}）。
     *
     * <p><b>为什么必须有这个端点</b>：商家要建自己的路线，得先有工序可选 —— 而此前
     * {@code production_operations} 的**唯一写方是 V54/V56 种子 SQL**（全仓对
     * {@code productionOperationMapper} 零写调用），非 1 号租户连一道工序都建不出来
     * （见 #4316）。本端点是「企业设置工艺路线」的前置。</p>
     *
     * <p><b>单价版本账首行同事务写</b>：与 {@link #update} 的「当前价 = 最新版本行」口径一致 ——
     * 新工序若只写 {@code unit_price} 而不写版本行，「当前价 = 最新版本行」对它就**不成立**
     * （迁移 V55 的回填正是为消灭这种不一致）。</p>
     *
     * <p><b>不发明行业数据</b>：本端点只落**商家给的值**，不给任何默认单价/默认工序名
     * （猜出来的单价会直接算成工人工资，见 issue #4261）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> create(Map<String, Object> body, Long tenantId) {
        String name = requiredText(body == null ? null : body.get("name"), "name");
        BigDecimal unitPrice = decimal(body.get("unit_price"), "unit_price");
        if (unitPrice.signum() < 0) {
            throw BusinessException.validationError("unit_price 不能为负");
        }
        // 重名判据覆盖**停用/软删之外**的全部行：唯一索引是 (tenant_id, name) WHERE deleted=0，
        // 只比活跃行会让「同名停用行」撞 DB 索引 ⇒ 500 而不是可行动错误。
        Long sameName = productionOperationMapper.selectCount(new LambdaQueryWrapper<ProductionOperation>()
                .eq(ProductionOperation::getTenantId, tenantId)
                .eq(ProductionOperation::getDeleted, 0)
                .eq(ProductionOperation::getName, name));
        if (sameName != null && sameName > 0) {
            throw BusinessException.conflict("工序「" + name + "」已存在",
                    "同名工序只能有一条：改它的单价/状态，或换一个工序名（目录查看入口 GET /api/admin/production/operations-catalog）");
        }
        String status = body.containsKey("status") ? requiredText(body.get("status"), "status") : "active";
        if (!STATUSES.contains(status)) {
            throw BusinessException.validationError("status 仅支持 active/disabled");
        }

        ProductionOperation op = ProductionOperation.builder()
                .tenantId(tenantId)
                .name(name)
                .groupName(body.containsKey("group_name")
                        ? requiredText(body.get("group_name"), "group_name") : "其他")
                .position(optionalText(body.get("position")))
                .scope(body.containsKey("scope") ? scope(body.get("scope")) : DEFAULT_SCOPE)
                .unit(body.containsKey("unit") ? requiredText(body.get("unit"), "unit") : "米")
                .unitPrice(unitPrice)
                .isMustFinish(body.containsKey("is_must_finish")
                        && bool(body.get("is_must_finish"), "is_must_finish"))
                .isStartMarker(body.containsKey("is_start_marker")
                        && bool(body.get("is_start_marker"), "is_start_marker"))
                .sortOrder(body.containsKey("sort_order")
                        ? decimal(body.get("sort_order"), "sort_order").intValue() : 0)
                .status(status)
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .deleted(0)
                .build();
        productionOperationMapper.insert(op);
        // 单价版本账首行（同事务）：使「当前价 = 最新版本行」对新工序同样成立
        priceVersionMapper.insert(ProductionOperationPriceVersion.builder()
                .tenantId(tenantId)
                .operationId(op.getId())
                .unitPrice(unitPrice)
                .createdAt(OffsetDateTime.now())
                .deleted(0)
                .build());
        log.info("新增工序: tenantId={}, name={}, unit={}, unitPrice={}", tenantId, name, op.getUnit(), unitPrice);
        return productionOperationQueryService.operationView(op);
    }

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    private static String optionalText(Object value) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
    }

    private static String requiredText(Object value, String field) {
        String text = value == null ? null : String.valueOf(value).trim();
        if (!StringUtils.hasText(text)) {
            throw BusinessException.validationError(field + " 不能为空");
        }
        return text;
    }

    /**
     * 作用域取值校验（issue #4384 A1）：只允许 {@code position}（部位级）/ {@code set}（套级，
     * 每樘窗一次），非法值**拒绝并给可读理由**（与 {@code status} 同口径）。
     *
     * <p><b>为什么必须校验而不是「存什么算什么」</b>：{@code scope} 是**实例化侧的分支判据**
     * （A2 按它决定「每樘窗一次」还是「每部位一次」）。一个错别字（如 {@code SET} / {@code 套级}）
     * 会静默落库，读面照原样返回、前端下拉认不出、去重判据恒不命中 ⇒ **双付病根原地复活且无任何东西变红**。</p>
     */
    private static String scope(Object value) {
        String text = requiredText(value, "scope");
        if (!SCOPES.contains(text)) {
            throw BusinessException.validationError("scope 仅支持 position/set（position=部位级，set=套级）");
        }
        return text;
    }

    private static boolean bool(Object value, String field) {
        if (value instanceof Boolean b) {
            return b;
        }
        String text = value == null ? null : String.valueOf(value).trim();
        if ("true".equalsIgnoreCase(text)) {
            return true;
        }
        if ("false".equalsIgnoreCase(text)) {
            return false;
        }
        throw BusinessException.validationError(field + " 必须是布尔值");
    }

    private static BigDecimal decimal(Object value, String field) {
        if (value == null) {
            throw BusinessException.validationError(field + " 不能为空");
        }
        if (value instanceof BigDecimal decimal) {
            return decimal;
        }
        if (value instanceof Number number) {
            return new BigDecimal(number.toString());
        }
        try {
            return new BigDecimal(String.valueOf(value).trim());
        } catch (NumberFormatException e) {
            throw BusinessException.validationError(field + " 必须是数字");
        }
    }
}
