package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
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
    /** 部位价目 + 适用性矩阵（issue #4614：新增工序要同时建矩阵行，否则新工序在界面上无处可见）。 */
    private final ProductionOperationPositionMapper productionOperationPositionMapper;
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
        // issue #4614（**存量孤儿接入路径**）：body 带 positions ⇒ 只**补**缺失的矩阵行。
        // 校验先于写入（与新增路径同一份 `requestedPositions` / `rejectUnknownPositions`）。
        List<String> positions = null;
        List<ProductionOperationPosition> existingRows = List.of();
        if (body != null && body.containsKey("positions")) {
            positions = requestedPositions(body.get("positions"));
            existingRows = tenantMatrixRows(tenantId);
            rejectUnknownPositions(positions, existingRows);
            // 冻结判据：矩阵行只在 deleted=0 **AND status='active'** 的工序上补（停用工序接部位 =
            // 建出一批读面看不见的行，商家会以为「接了但没生效」）。
            if (!"active".equals(op.getStatus())) {
                throw BusinessException.validationError("工序「" + op.getName()
                        + "」当前是停用状态：停用工序不接部位（先启用它，再接部位）");
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
        Map<String, Object> view = productionOperationQueryService.operationView(op);
        if (positions != null) {
            Map<String, Integer> counts = attachPositions(tenantId, op, positions, existingRows);
            view.put("created_positions", counts.get("created"));
            view.put("skipped_positions", counts.get("skipped"));
            log.info("存量工序接入部位: tenantId={}, operationId={}, name={}, positions={}, created={}, skipped={}",
                    tenantId, op.getId(), op.getName(), positions, counts.get("created"), counts.get("skipped"));
        }
        return view;
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
     *
     * <p><b>issue #4614：为什么还要能同时建矩阵行</b>——用户实测原话「这个新增按钮，无法新增工序」：
     * 本端点此前**只写 {@code production_operations}**，而「工艺项」表**只按矩阵行渲染**
     * （{@code GET /operation-positions}）⇒ 新建的工序**在界面上无处可见**、连定价入口都没有
     * （原「工序库明细」表已随 #4588 取消）。故 body 增可选 {@code positions}：
     * 给了就**同一事务**为每个部位插一行矩阵行（{@code logical_name} = 工序名的**归一逻辑名**，
     * 复用 {@link ProductionOperationQueryService#normalizeOperationName}；{@code unit_price} =
     * 本次填的计件单价）。**不给 {@code positions} ⇒ 行为一字不变**（老调用方/脚本不受影响）。</p>
     *
     * <p><b>幂等</b>：同 {@code (tenant_id, logical_name, position)} 已有未软删行 ⇒ **跳过**
     * （**不覆盖**商家改过的价），并在响应里**如实报数**
     * （{@code created_positions} / {@code skipped_positions}）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> create(Map<String, Object> body, Long tenantId) {
        String name = requiredText(body == null ? null : body.get("name"), "name");
        BigDecimal unitPrice = decimal(body.get("unit_price"), "unit_price");
        if (unitPrice.signum() < 0) {
            throw BusinessException.validationError("unit_price 不能为负");
        }
        // issue #4642：**旧形态工序名不许建**（拒绝，不归一）。病根 = 同一个请求里
        // `name` 原样落库、而 `attachPositions` 用归一后的逻辑名建矩阵行 ⇒ **同一道工序在库里两名并存**
        // （库里 `布三边` + 矩阵行 `三边`），且 `name` 会经目录/孤儿弹窗上屏（变体名泄漏）。
        // 为什么选**拒绝**而不是归一：`布三边` 归一成 `三边` 会与**既有** `三边` 行撞唯一索引
        // `uk_production_operations_tenant_name`（⇒ 500 或建出重复/半成品），拒绝才与「一套名字」一致。
        rejectVariantOperationName(name);
        // issue #4614：positions 给了才建矩阵行。**校验先于写入**（与 status/scope 同口径）——
        // 部位写错一个不该先落一行工序库再回滚。
        List<String> positions = null;
        List<ProductionOperationPosition> existingRows = List.of();
        if (body != null && body.containsKey("positions")) {
            positions = requestedPositions(body.get("positions"));
            existingRows = tenantMatrixRows(tenantId);
            rejectUnknownPositions(positions, existingRows);
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
        Map<String, Object> view = productionOperationQueryService.operationView(op);
        if (positions != null) {
            Map<String, Integer> counts = attachPositions(tenantId, op, positions, existingRows);
            view.put("created_positions", counts.get("created"));
            view.put("skipped_positions", counts.get("skipped"));
        }
        log.info("新增工序: tenantId={}, name={}, unit={}, unitPrice={}, positions={}",
                tenantId, name, op.getUnit(), unitPrice, positions);
        return view;
    }

    /**
     * 按部位**补建**矩阵行 —— issue #4614 的**唯一**实现（新增路径 {@link #create} 与存量接入路径
     * {@link #update} 共用；**严禁写第二份**：口径分叉就是又一次「工艺项表 / 路线下拉两边不一致」）。
     *
     * <p>语义 = **只补不改**：{@code (tenant_id, logical_name, position)} 已有行 ⇒ **跳过**
     * （不覆盖商家改过的价、不删任何已有行）。新建行的 {@code unit_price} 取该工序**当前的计件单价**
     * （{@code null} 就落 {@code null} = 「做但未定价」，商家在「工艺项」表里就地定价；
     * **不发明单价** —— 猜出来的价会直接算成工人工资）。</p>
     *
     * @return {@code {created, skipped}}（如实报数，供响应与 toast 直接引用，前端不自行推算）
     */
    private Map<String, Integer> attachPositions(Long tenantId, ProductionOperation op,
                                                 List<String> positions,
                                                 List<ProductionOperationPosition> existingRows) {
        String logicalName = productionOperationQueryService.normalizeOperationName(op.getName());
        Set<String> already = new LinkedHashSet<>();
        for (ProductionOperationPosition row : existingRows) {
            if (logicalName.equals(row.getLogicalName())) {
                already.add(row.getPosition());
            }
        }
        int created = 0;
        int skipped = 0;
        for (String position : positions) {
            if (already.contains(position)) {
                // 幂等：商家改过的价必须原样留着（覆盖 = 把工价刷回工序库的值，工人工资当场变）
                skipped++;
                continue;
            }
            productionOperationPositionMapper.insert(ProductionOperationPosition.builder()
                    .tenantId(tenantId)
                    .logicalName(logicalName)
                    .position(position)
                    .unitPrice(op.getUnitPrice())
                    .applicable(true)
                    .status("active")
                    .createdAt(OffsetDateTime.now())
                    .updatedAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
            created++;
        }
        return Map.of("created", created, "skipped", skipped);
    }

    /**
     * 该租户矩阵里的**全部未软删行**（issue #4614）。一次取回、同时服务两件事：
     * ① 值域 —— 「矩阵里出现的部位 ∪ 基线三部位」（与前端 {@code positionOptions} 同口径）；
     * ② 幂等 —— 同 {@code (logical_name, position)} 已有行就跳过。
     *
     * <p>⚠️ 判据必须用 {@code deleted = 0}（**与唯一索引
     * {@code uk_production_operation_positions_tenant_name_position … WHERE deleted = 0} 同域**）：
     * 只比 {@code status='active'} 会漏掉停用行 ⇒ insert 撞索引 ⇒ 500 而不是可行动错误
     * （同本类重名判据「必须覆盖停用行」的既有教训）。</p>
     */
    private List<ProductionOperationPosition> tenantMatrixRows(Long tenantId) {
        List<ProductionOperationPosition> rows = productionOperationPositionMapper.selectList(
                new LambdaQueryWrapper<ProductionOperationPosition>()
                        .eq(ProductionOperationPosition::getTenantId, tenantId)
                        .eq(ProductionOperationPosition::getDeleted, 0));
        return rows == null ? List.of() : rows;
    }

    /**
     * {@code positions} 取值（issue #4614）：必须是**非空数组**，元素去重保序（空串**留到校验里报**，
     * 不在这里静默丢掉）。
     *
     * <p>显式空数组 ⇒ 422 而不是静默 no-op：那等于「建出一道在界面上无处可见的工序」
     * —— 正是本单要治的病（与 {@code createRouting} 的空 {@code positions} 同口径）。</p>
     */
    private static List<String> requestedPositions(Object raw) {
        if (!(raw instanceof List<?> list)) {
            throw BusinessException.validationError("positions 必须是数组（如 [\"布帘\",\"纱帘\"]）");
        }
        if (list.isEmpty()) {
            throw BusinessException.validationError(
                    "positions 不能为空（至少勾一个适用部位，否则新工序不会出现在「工艺项」表里）");
        }
        List<String> out = new ArrayList<>();
        for (Object item : list) {
            String text = item == null ? "" : String.valueOf(item).trim();
            if (!out.contains(text)) {
                out.add(text);
            }
        }
        return out;
    }

    /**
     * 部位值域校验（issue #4614）：值域 = **该租户矩阵里出现的部位 ∪ 基线三部位**
     * （{@link ProductionOperationQueryService#BASELINE_POSITIONS}）—— 与前端「新增」对话框的
     * 「适用部位」勾选项**同一份口径**，前端勾得出的后端就必须收得下。
     *
     * <p>空串 / 未知部位 ⇒ **一次报全**（422 + {@code error.details} 逐条，照既有 422 形态）。
     * 不校验的代价：一个笔误（{@code 布廉}）会静默落库并在「工艺项」表里长出一列谁也认不出的部位。</p>
     */
    private static void rejectUnknownPositions(List<String> positions,
                                               List<ProductionOperationPosition> existingRows) {
        Set<String> known = new LinkedHashSet<>(ProductionOperationQueryService.BASELINE_POSITIONS);
        for (ProductionOperationPosition row : existingRows) {
            if (StringUtils.hasText(row.getPosition())) {
                known.add(row.getPosition());
            }
        }
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        for (String position : positions) {
            if (!StringUtils.hasText(position)) {
                details.add(BusinessException.detail("positions",
                        "适用部位不能为空（空串会在「工艺项」表里长出一列无名部位）"));
            } else if (!known.contains(position)) {
                details.add(BusinessException.detail("positions", String.format(
                        "未知部位「%s」：只接受矩阵里已有的部位（%s）或基线三部位（%s）",
                        position, String.join("/", known),
                        String.join("/", ProductionOperationQueryService.BASELINE_POSITIONS))));
            }
        }
        if (!details.isEmpty()) {
            throw BusinessException.validationError(
                    "新增工序未通过校验（" + details.size() + " 条问题）", details,
                    "把「适用部位」改成矩阵里已有的部位（或基线三部位）后重试");
        }
    }

    /**
     * 软删工序（{@code DELETE /api/admin/production/operations/{id}}，issue #4587 ③）。
     *
     * <p><b>为什么软删而不是物理删</b>：历史报工（{@code production_work_logs}）与工序实例
     * （{@code processing_position_operations}）仍按工序名引用它 —— 物理删会让「这道工序当时按什么价
     * 算的」永远答不出来（与路线/信号软删同口径）。</p>
     *
     * <p><b>三条护栏一次报全</b>（422 + {@code error.details:[{field,message}]}，不是报第一条就返回）：</p>
     * <ol>
     *   <li>{@code routing} —— 被**活跃路线主线**引用（按逻辑名**或**变体名命中；主线存的是逻辑名，
     *       但写面两种写法都收）⇒ 报出路线名，让商家知道「先改哪条主线」；</li>
     *   <li>{@code route_rule} —— 被**活跃规则**的 {@code operation} 或 {@code after_operation} 命中
     *       ⇒ 报出触发名（工艺/选项），让商家知道「先删/改哪条规则」；</li>
     *   <li>{@code operation_position} —— 被**矩阵行**引用（该变体对应的 {@code (逻辑名, 部位)} 行里
     *       任一 {@code applicable=true}）⇒ 报出部位，让商家知道「先在哪个部位设为不做」。</li>
     * </ol>
     *
     * <p>⚠️ 护栏 3 必须**遍历全部命中格**：一个变体可能被多格引用 —— {@code 帘头} 会回落
     * {@code 布帘} 变体（{@code 三边 × 帘头} 与 {@code 三边 × 布帘} 都指向 {@code 布三边}），
     * 部位无关的工序（{@code 外帘打卷}）更是**一格多部位**。只看一格 ⇒ 删完别的格变成
     * 「指向不存在工序」的悬空引用（而矩阵读面的 5 键会静默全 null）。</p>
     *
     * <p>已软删 ⇒ <b>200 幂等 no-op</b>（不报 404：调用方要的是「它现在不在活跃集里」，已经满足）。</p>
     *
     * <p>⚠️ <b>本方法必须是「工序软删」的**唯一落点**</b>：{@code tests/unit_ci_workflows/
     * test_logic_delete_write_shape.py} 的锚点按**第一个名为 {@code delete} 的方法**取体
     * （issue #4608 的显式写列守卫）—— 把它挪到别的方法后面会让守卫**失锚**（CI 红）。
     * 带 {@code detachPositions} 的入口见 {@link #deleteDetaching(String, Long)}。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> delete(String id, Long tenantId) {
        ProductionOperation op = id == null ? null : productionOperationMapper.selectById(id);
        if (op == null || !tenantId.equals(op.getTenantId())) {
            throw BusinessException.notFound("工序");
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", op.getId());
        result.put("deleted", true);
        result.put("detached_positions", 0);
        if (Integer.valueOf(1).equals(op.getDeleted())) {
            return result;
        }
        String variantName = op.getName();
        String logicalName = productionOperationQueryService.normalizeOperationName(variantName);
        // issue #4642：护栏文案一律用**逻辑名**（`logicalName`）—— 它是 web 面唯一显示口径。
        // 库口径变体名（`variantName`）只用于**判据**（主线/规则里两种写法都收、矩阵按变体名寻址），
        // **不得**出现在 `error.details[].message` 里：前端 `variant-delete-reasons` 逐条渲染这些文案，
        // 用变体名就等于把 `布三边` 送上商家屏（同 P1 的泄漏路径）。
        // 「到底是哪条库行」的辨识度由**部位集合/分组**补足（见护栏③的 `logicalName × position`）。
        // 护栏①主线 / ②规则：与一键版本**共用同一份判据**（`operationReferenceGuards`）。
        List<ApiResponse.ErrorDetail> details = operationReferenceGuards(tenantId, logicalName, variantName);
        // ③ 矩阵行（**遍历全部命中格**：帘头回落布帘变体 / 部位无关工序一格多部位）。
        // ⚠️ 命中格**先整份收进列表**（不管 applicable）：它是三处的**同一份判据** ——
        // 护栏③（applicable=true ⇒ 拦）、一键摘格（把这些格设为不做）、级联软删（把这些行删掉）。
        // 三处各写一遍必然漂移（一处改了另两处忘改 ⇒ 要么拦不住、要么摘不干净、要么删不干净）。
        List<ProductionOperationPosition> matchingCells = matchingCells(tenantId, variantName);
        for (ProductionOperationPosition row : matchingCells) {
            if (!Boolean.TRUE.equals(row.getApplicable())) {
                continue;
            }
            details.add(BusinessException.detail("operation_position", String.format(
                    "工序「%s」还挂在部位价目矩阵的「%s × %s」格上且该格是「做」—— 先在该部位设为「不做」，再删它",
                    logicalName, row.getLogicalName(), row.getPosition())));
        }
        if (!details.isEmpty()) {
            throw BusinessException.validationError(
                    "删除工序未通过校验（" + details.size() + " 条问题）", details,
                    "按每条理由处理：先改主线 / 先删改那条规则 / 先在对应部位设为不做");
        }
        OffsetDateTime now = OffsetDateTime.now();
        // 级联软删矩阵行（issue #4665 C：删工序要「删干净」）—— 见 `cascadeSoftDeleteCells` 的说明
        result.put("deleted_positions", cascadeSoftDeleteCells(tenantId, matchingCells, now));
        // ⚠️ 必须**显式写列**（issue #4608），不得写成 `op.setDeleted(1); updateById(op);`：
        // MP 全局逻辑删除会把逻辑删除字段从 updateById 的 SET 子句里**剔除** ⇒ deleted 永不落库，
        // 而调用仍返回成功 = 删除静默 no-op（用户实测「提示成功但数据还在」）。
        // 显式 .set(...) 绕过字段剔除，同时保住审计字段 updated_at（「谁在什么时候删的」的唯一证据）。
        productionOperationMapper.update(null, new LambdaUpdateWrapper<ProductionOperation>()
                .eq(ProductionOperation::getId, id)
                .set(ProductionOperation::getDeleted, 1)
                .set(ProductionOperation::getUpdatedAt, now));
        log.info("软删工序: tenantId={}, operationId={}, name={}, 级联软删矩阵行={}",
                tenantId, op.getId(), op.getName(), result.get("deleted_positions"));
        return result;
    }

    /**
     * 一键「**设为不做并删除**」（issue #4665 A；用户实测「无法删除，而且没有地方设置做于不做」）。
     *
     * <p><b>与 {@link #delete(String, Long)} 的唯一差别</b>：护栏③「矩阵格是『做』」**可一键满足** ——
     * 同一事务里先把命中的格设为 {@code applicable=false}（价强制清空，与 V71 列口径一致），
     * 再软删工序 + **级联软删矩阵行**（#4665 C：删干净）。前端**只发一次**请求 ⇒ **没有**
     * 「第一步成功、第二步失败」的中间态。</p>
     *
     * <p><b>护栏不放宽</b>（本单硬要求）：护栏①<b>活跃路线主线</b>与②<b>活跃规则</b>**照样拦**
     * （主线涉及车间顺序，必须人工确认）；且**先判护栏、后摘格** ⇒ 被拦时**一格都不摘**。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> deleteDetaching(String id, Long tenantId) {
        ProductionOperation op = id == null ? null : productionOperationMapper.selectById(id);
        if (op == null || !tenantId.equals(op.getTenantId())) {
            throw BusinessException.notFound("工序");
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", op.getId());
        result.put("deleted", true);
        result.put("detached_positions", 0);
        if (Integer.valueOf(1).equals(op.getDeleted())) {
            return result;
        }
        String variantName = op.getName();
        String logicalName = productionOperationQueryService.normalizeOperationName(variantName);
        // ⚠️ 护栏①/② **与两参版本同一份判据**（`operationReferenceGuards`）—— 不许在这里少判一条；
        // 护栏③（矩阵格是「做」）**不判** = 本按钮要一键满足的那一条。
        List<ApiResponse.ErrorDetail> details = operationReferenceGuards(tenantId, logicalName, variantName);
        if (!details.isEmpty()) {
            throw BusinessException.validationError(
                    "删除工序未通过校验（" + details.size() + " 条问题）", details,
                    "按每条理由处理：先改主线 / 先删改那条规则 / 先在对应部位设为不做");
        }
        List<ProductionOperationPosition> matchingCells = matchingCells(tenantId, variantName);
        // 一键摘格：**先判护栏、后摘格** ⇒ 被拦时一格都不摘。写形态复用矩阵写面同一份
        // （`updatePriceAndApplicable`：不做 ⇒ 价强制清空，与「明确不做 ⇒ 不报价」同口径）。
        OffsetDateTime now = OffsetDateTime.now();
        int detached = 0;
        for (ProductionOperationPosition row : matchingCells) {
            if (!Boolean.TRUE.equals(row.getApplicable())) {
                continue;
            }
            productionOperationPositionMapper.updatePriceAndApplicable(
                    row.getId(), tenantId, null, false, now);
            detached++;
        }
        result.put("detached_positions", detached);
        if (detached > 0) {
            log.info("一键摘格（设为不做）: tenantId={}, operationId={}, cells={}", tenantId, id, detached);
        }
        result.put("deleted_positions", cascadeSoftDeleteCells(tenantId, matchingCells, now));
        // 显式写列（同 `delete`：不走 updateById —— MP 会剔除该字段 ⇒ 静默 no-op，issue #4608）
        productionOperationMapper.update(null, new LambdaUpdateWrapper<ProductionOperation>()
                .eq(ProductionOperation::getId, id)
                .set(ProductionOperation::getDeleted, 1)
                .set(ProductionOperation::getUpdatedAt, now));
        log.info("软删工序（一键摘格）: tenantId={}, operationId={}, name={}, 级联软删矩阵行={}",
                tenantId, op.getId(), op.getName(), result.get("deleted_positions"));
        return result;
    }

    /**
     * **级联软删**属于该工序的矩阵行（issue #4665 C：删工序要「删干净」），返回删了几行。
     *
     * <p>工序软删后矩阵行若还在，{@code GET /operation-positions} 照旧返回它（读面过滤只有
     * 租户 + {@code deleted=0} + {@code status='active'}，**不看它挂的那道工序是否已删**）⇒
     * 工艺项表格里那一行**照旧显示** = 用户实测「依然删不干净」。判据与护栏③/一键摘格**同一份**
     * （{@code matchingCells}，含帘头回落 / 一格多部位）；写形态**显式写列**（{@code softDelete}：
     * {@code deleted=1} + {@code updated_at} —— 不走 {@code updateById}，那是 #4608 的静默 no-op）。</p>
     *
     * <p><b>一次事务</b>：影响 0 行（并发下已被别人删掉）⇒ <b>fail-closed</b> 抛 422 让整个事务回滚，
     * 不留「工序删了、行还在」的半完成态。</p>
     */
    private int cascadeSoftDeleteCells(Long tenantId, List<ProductionOperationPosition> matchingCells,
                                       OffsetDateTime now) {
        int cascadeDeleted = 0;
        for (ProductionOperationPosition row : matchingCells) {
            if (productionOperationPositionMapper.softDelete(row.getId(), tenantId, now) == 0) {
                throw BusinessException.validationError(
                        "删除工序未通过校验（1 条问题）",
                        List.of(BusinessException.detail("operation_position", String.format(
                                "部位价目矩阵的「%s × %s」格在删除过程中被改动，请刷新后重试",
                                row.getLogicalName(), row.getPosition()))),
                        "刷新页面后重试");
            }
            cascadeDeleted++;
        }
        return cascadeDeleted;
    }

    /**
     * 删除工序的护栏①（活跃路线主线）/②（活跃规则）—— 两参版本与一键版本**共用同一份判据**
     * （不许在某一处少判一条）。
     *
     * <p>文案一律用**逻辑名**（issue #4642）：它是 web 面唯一显示口径，库口径变体名不得上屏
     * （前端 {@code variant-delete-reasons} 逐条渲染这些 message）。</p>
     */
    private List<ApiResponse.ErrorDetail> operationReferenceGuards(Long tenantId, String logicalName,
                                                                   String variantName) {
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        // ① 活跃路线主线（逻辑名或变体名命中；每条路线只报一次）
        for (ProductionRouteTemplate template : productionOperationQueryService.routeTemplates(tenantId)) {
            List<String> mainline = productionOperationQueryService.mainlineOf(template);
            if (!mainline.contains(logicalName) && !mainline.contains(variantName)) {
                continue;
            }
            details.add(BusinessException.detail("routing", String.format(
                    "工序「%s」还在活跃路线「%s」的主线里 —— 先改主线（把它从该路线去掉），再删它",
                    logicalName, template.getName())));
        }
        // ② 活跃规则（operation 或 after_operation 命中；报触发名）
        for (ProductionRouteRule rule : productionOperationQueryService.routeRules(tenantId)) {
            if (!hitsOperation(rule.getOperation(), logicalName, variantName)
                    && !hitsOperation(rule.getAfterOperation(), logicalName, variantName)) {
                continue;
            }
            details.add(BusinessException.detail("route_rule", String.format(
                    "工序「%s」被活跃规则「%s → %s」引用（目标工序或锚点）—— 先删或改那条规则，再删它",
                    logicalName, rule.getTriggerValue(), rule.getOperation())));
        }
        return details;
    }

    /** 规则里的工序名是否指向被删工序（逻辑名或变体名任一命中；主线/规则两处同一判据）。 */
    private static boolean hitsOperation(String value, String logicalName, String variantName) {
        return value != null && (value.equals(logicalName) || value.equals(variantName));
    }

    /**
     * 该变体在矩阵里引用的**全部**格（issue #4665）。
     *
     * <p><b>为什么单独抽一个方法</b>：它是护栏③（格是「做」⇒ 拦）、一键摘格（把这些格设为不做）
     * 与级联软删（把这些行删掉）的**同一份判据** —— 三处各写一遍必然漂移
     * （一处改了另两处忘改 ⇒ 要么拦不住、要么摘不干净、要么删不干净）。
     * 「遍历全部命中格」的口径也留在这里：{@code 帘头} 会回落 {@code 布帘} 变体
     * （{@code 三边 × 帘头} 与 {@code 三边 × 布帘} 都指向 {@code 布三边}），部位无关的工序
     * （{@code 外帘打卷}）更是**一格多部位** ⇒ 只看一格会留下悬空引用。</p>
     *
     * <p>⚠️ **不过滤 {@code applicable}**：级联软删要连「已经设为不做」的格一起删
     * （否则用户把格设为不做再删工序 ⇒ 那一行照旧留在表格里 = 「删不干净」）；是否「算引用」
     * 由调用方按 {@code applicable} 自行判断。</p>
     */
    private List<ProductionOperationPosition> matchingCells(Long tenantId, String variantName) {
        Map<String, Map<String, Object>> catalog = productionOperationQueryService.operationsByName(tenantId);
        List<ProductionOperationPosition> cells = new ArrayList<>();
        for (ProductionOperationPosition row : productionOperationQueryService.operationPositions(tenantId)) {
            if (!variantName.equals(productionOperationQueryService.variantNameOf(
                    row.getLogicalName(), row.getPosition(), catalog))) {
                continue;
            }
            cells.add(row);
        }
        return cells;
    }

    /**
     * 新增工序时**拒绝带部位后缀的工序名**（issue #4642；文案改判 = issue #4647 / D2）。
     *
     * <p>两条判据（命中任一 ⇒ **422 + {@code error.details:[{field,message}]} 逐条**，文案用商家语言）：</p>
     * <ol>
     *   <li><b>已登记旧名</b>：走**既有** {@link ProductionOperationQueryService#normalizeOperationName}，
     *       归一后**不等于自身**即命中（35 条旧名：{@code 精裁-布} / {@code 布三边} / {@code 布帘车被}…）；</li>
     *   <li><b>部位后缀形态</b>：名字以 {@code -布} / {@code -纱} / {@code -帘} 结尾 ⇒ 命中。
     *       部位词表是**闭**的（布 / 纱 / 帘）⇒ 后缀形态可判定。</li>
     * </ol>
     *
     * <p>🔴 <b>判据 2 的文案不得说「是旧形态」</b>（issue #4647 / D2 实测）：{@code 定制-布} /
     * {@code 工艺-布} **不在** 35 条归一表里 ⇒ 它们**不是**旧形态，只是恰好以 {@code -布} 结尾。
     * 文案说「是旧形态」是**事实错误**；准确表述 = 「工序名不要带部位后缀」。判据 1 命中时
     * 可以照实说「已登记为旧名」。</p>
     *
     * <p><b>{@code 罗马帘-穿杆} 的取舍（明确登记）</b>：它**放行** —— 后缀是 {@code -穿杆}，
     * 不是部位后缀；而「名字以部位后缀结尾」是一个**形态判据**，不依赖归一表 ⇒ 对已登记与未登记
     * 的工序名**一视同仁**（{@code xx-布} / {@code xx-纱} / {@code xx-帘} 一律拒）。
     * 代价（如实登记）：商家仍能建出与既有工序**同逻辑名**的第二行（{@code 罗马帘-穿杆} 与
     * {@code 罗马帘穿杆} 归一后都是自身 ⇒ 两名并存）—— 这**不是本判据**能判的（它需要查库比逻辑名），
     * 属**另一个**判据的范围；本单**不扩大**判据（issue #4647 明示：要扩大先报）。
     * 边界由测试钉住：{@code ProductionOperationCommandServiceTest} 的
     * 「#4647 部位后缀边界」一组（该拒的拒 / 该放的放）。</p>
     *
     * <p><b>合法自定义名照常可建</b>（{@code 测试22} / {@code 罗马帘穿杆} / {@code 外帘打卷}）。</p>
     */
    private void rejectVariantOperationName(String name) {
        String logicalName = productionOperationQueryService.normalizeOperationName(name);
        boolean isVariant;
        if (name.equals(logicalName)) {
            // 归一后等于自身 ⇒ 不是**已登记**的旧名。仍要拒「名字 + 部位后缀」的**未登记**写法：
            // 部位词表是**闭**的（布 / 纱 / 帘）⇒ 后缀形态可判定，且对已登记 / 未登记**一视同仁**
            // （`定制-布` 不在归一表里，但它同样把部位编进了名字 ⇒ 同样拒）。
            isVariant = name.endsWith("-布") || name.endsWith("-纱") || name.endsWith("-帘");
        } else {
            // 归一后变了 ⇒ 该名字**是**归一表里的旧形态（`布三边` / `布帘车被` / `精裁-布`）。
            // 判据直接来自**既有** `normalizeOperationName`（不新造第二份表）—— 「归一后不等于自身」
            // 就是「它被登记为旧名」的可执行定义，无需再查库。
            isVariant = true;
        }
        if (!isVariant) {
            return;
        }
        // ⚠️ 文案**必须与判据一致**（issue #4647 / D2）：判据 1 命中（归一后变了）才是「已登记为旧名」；
        // 判据 2 命中的名字（`定制-布` / `工艺-布`）**不在**归一表里 ⇒ 说它「是旧形态」是事实错误。
        String why = name.equals(logicalName)
                ? "工序名不要带部位后缀（`-布` / `-纱` / `-帘`）"
                : "工序名不要带部位（「" + name + "」已登记为旧名）";
        throw BusinessException.validationError(
                why,
                java.util.List.of(new ApiResponse.ErrorDetail("name",
                        "工序名不要带部位后缀（`-布` / `-纱` / `-帘`）；部位在下方勾选 —— "
                                + "名字与部位是两件事，带部位的名字会让同一道工序在库里存成两名")),
                "把名字改成不带部位的逻辑工序名（如「三边」），部位在下方勾选");
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
