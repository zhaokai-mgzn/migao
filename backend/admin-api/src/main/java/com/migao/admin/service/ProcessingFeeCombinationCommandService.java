package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.ProcessingFeeCombination;
import com.migao.admin.entity.ProcessingFeeCombinationVersion;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
import com.migao.admin.mapper.ProcessingFeeCombinationVersionMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;

/**
 * 加工费组合定价**写面**（V68，issue #4386，P1；用户裁定 2026-09-19「缺乏加工费的管理模块」）。
 *
 * <p><b>两个时刻、两个角色</b>：商家在**配置时**自行组合并定价（本类 = 那个写面）；
 * 系统在**下单时**按选配结果匹配组合 → 取价 → × 加工费米数 → **一个数**。
 * 本类只做前一半 —— 计价接线（{@code OrderService.sumProcessingFee} / 下单页 / ai-agent）**不在本包**，
 * 见 issue #4386 的 follow-up 登记。</p>
 *
 * <p><b>为什么单独一个类</b>：{@link ProcessingFeeQueryService} 自述读边界且只有 SELECT；
 * 把写操作塞进去会让「谁在改加工费」不可 grep（同 #4308 对路线库的处置）。</p>
 *
 * <p><b>为什么五条护栏必须逐条给理由</b>：本表是下单侧**唯一取价源**，错价直接进订单金额。
 * 护栏失败统一走 **HTTP 422 + {@code error.details:[{field,message}]} 逐条理由**
 * （复用既有信封字段，不新造），**全部违规一次报全**（逐条展示的前提是别让用户改一条提交一次）；
 * 撞唯一键（同一组合重复定价）走 **409** —— 那是「资源已存在」，不是「参数不合法」。
 * {@code message} 只做一句话摘要。</p>
 *
 * <p><b>版本账</b>：单价**真的变了**才追加 {@code processing_fee_combination_versions} 一行
 * （同值重复提交是幂等空操作，沿用 #4308 / 单价版本账口径）—— 每次 PUT 都写会让账本被重复行淹没。</p>
 *
 * <p><b>权限</b>：端点声明方法级 {@code processing:manage}（与 #4308 同口径）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingFeeCombinationCommandService {

    /** 组合状态取值（V68 `status VARCHAR(16) DEFAULT 'active'`：active / disabled）。 */
    private static final Set<String> STATUSES = Set.of("active", "disabled");

    /** provenance 词表（与 {@code production_operations.source} / V62 逐字同口径）。 */
    private static final Set<String> SOURCES = Set.of("实证", "推算", "占位待确认");

    private final ProcessingFeeCombinationMapper combinationMapper;
    private final ProcessingFeeCombinationVersionMapper versionMapper;
    private final ProcessingItemMapper processingItemMapper;
    private final ProcessingFeeQueryService queryService;

    // ══════════════════════════════ 归一化（确定性、与书写顺序无关）══════════════════════════════

    /**
     * 选配特征集合 → **规范化组合键**。
     *
     * <p>口径（冻结，判据 2 钉住）：① 逐项 trim；② 丢空项；③ **去重**；④ 按 Unicode 码点升序排序；
     * ⑤ 以 {@code +} 连接。结果**只依赖集合内容**，与书写顺序、与数据库状态、与调用次数**全都无关**。</p>
     *
     * <p>为什么必须与顺序无关：「韩褶+打孔+定型」与「定型+打孔+韩褶」是**同一笔钱**；
     * 按书写顺序存 ⇒ 商家两次录入建出**两行** ⇒ 下单匹配命中哪一行取决于扫描顺序
     * ⇒ 同一份选配在两次下单拿到两个价（不可复现的定价）。</p>
     *
     * <p>为什么不用「库里 sort_order 序」：那会让 key 随**加工项表的改动**漂移 ——
     * 同一个已成交组合的 key 会因为商家调了一下排序而变 ⇒ 历史订单匹配不上自己的价。
     * 纯内容序是**唯一**在数据变更下仍稳定的选择。</p>
     */
    public static String compositionKey(List<String> names) {
        Set<String> unique = new TreeSet<>();
        if (names != null) {
            for (String name : names) {
                if (name != null && !name.isBlank()) {
                    unique.add(name.trim());
                }
            }
        }
        return String.join("+", unique);
    }

    // ══════════════════════════════ 新建 ══════════════════════════════

    /**
     * 新建组合定价（{@code POST /production/processing-fee-combinations}）。
     * body: {@code {items:[加工项名…], unit_price, sort_order?, source?, status?}}
     *
     * <p>五条护栏（issue #4386 冻结清单，逐条 {@code error.details}）：组合非空 /
     * 特征名合法（**且不重复**）/ {@code unit_price ≥ 0} / {@code source} 在词表内 /
     * {@code composition_key} **归一化后落库**。撞已有组合 ⇒ 409。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> createCombination(Map<String, Object> body, Long tenantId) {
        List<String> rawItems = items(body);
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        List<String> canonical = validateItems(rawItems, tenantId, details);
        BigDecimal unitPrice = requiredPrice(body == null ? null : body.get("unit_price"), details);
        String source = optionalSource(body == null ? null : body.get("source"), details);
        if (!details.isEmpty()) {
            throw BusinessException.validationError(
                    String.format("加工费组合未通过校验（%d 条问题）", details.size()),
                    details,
                    "逐条修好后重新提交；加工项目录查看入口 GET /api/admin/processing/items");
        }
        String key = compositionKey(canonical);
        rejectDuplicate(key, null, tenantId);

        ProcessingFeeCombination row = ProcessingFeeCombination.builder()
                .tenantId(tenantId)
                .compositionKey(key)
                .items(canonical)
                .unitPrice(unitPrice)
                .status(body != null && body.containsKey("status")
                        ? requiredStatus(body.get("status")) : "active")
                .sortOrder(optionalSortOrder(body == null ? null : body.get("sort_order")))
                .source(source)
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .deleted(0)
                .build();
        combinationMapper.insert(row);
        appendVersion(row, tenantId);
        log.info("新建加工费组合: tenantId={}, key={}, unitPrice={}", tenantId, key, unitPrice);
        return queryService.combinationView(row);
    }

    // ══════════════════════════════ 改单价 / 停用 ══════════════════════════════

    /**
     * 改单价 / 状态（{@code PUT /production/processing-fee-combinations/{id}}，部分更新）。
     *
     * <p>护栏：{@code unit_price ≥ 0}（改价同一条口径，不因为是 PUT 就放宽）；
     * **真的变了**才落版本账。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> updateCombination(String id, Map<String, Object> body, Long tenantId) {
        ProcessingFeeCombination row = findCombination(id, tenantId);
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        BigDecimal newPrice = body != null && body.containsKey("unit_price")
                ? requiredPrice(body.get("unit_price"), details) : row.getUnitPrice();
        String newSource = body != null && body.containsKey("source")
                ? optionalSource(body.get("source"), details) : row.getSource();
        String newStatus = body != null && body.containsKey("status")
                ? requiredStatus(body.get("status")) : row.getStatus();
        if (!details.isEmpty()) {
            throw BusinessException.validationError(
                    String.format("加工费组合未通过校验（%d 条问题）", details.size()),
                    details,
                    "单价不得为负、source 只认 实证/推算/占位待确认");
        }

        boolean priceChanged = row.getUnitPrice() == null
                ? newPrice != null : row.getUnitPrice().compareTo(newPrice) != 0;
        boolean statusChanged = !Objects.equals(row.getStatus(), newStatus);
        row.setUnitPrice(newPrice);
        row.setSource(newSource);
        row.setStatus(newStatus);
        if (body != null && body.containsKey("sort_order")) {
            row.setSortOrder(optionalSortOrder(body.get("sort_order")));
        }
        row.setUpdatedAt(OffsetDateTime.now());
        combinationMapper.updateById(row);
        if (priceChanged || statusChanged) {
            appendVersion(row, tenantId);
            log.info("改加工费组合: tenantId={}, id={}, key={}, price {} -> {}",
                    tenantId, row.getId(), row.getCompositionKey(), priceChanged ? "changed" : "same", newPrice);
        }
        return queryService.combinationView(row);
    }

    /**
     * 停用组合（{@code DELETE /production/processing-fee-combinations/{id}}）—— **软删语义**
     * （{@code status=disabled}，行保留）。
     *
     * <p>为什么不物理删：停用后这行立刻不参与匹配，而「谁在什么时候把哪个组合下架了」
     * 在排查「订单金额与昨天不同」时是唯一的证据（同 #4308 信号映射的处置）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> disableCombination(String id, Long tenantId) {
        ProcessingFeeCombination row = findCombination(id, tenantId);
        if (!"disabled".equals(row.getStatus())) {
            row.setStatus("disabled");
            row.setUpdatedAt(OffsetDateTime.now());
            combinationMapper.updateById(row);
            appendVersion(row, tenantId);
            log.info("停用加工费组合: tenantId={}, id={}, key={}", tenantId, row.getId(), row.getCompositionKey());
        }
        return queryService.combinationView(row);
    }

    // ══════════════════════════════ 护栏 ══════════════════════════════

    /**
     * 组合护栏（**唯一一份**：新建用；改价不改组合故不重复校验）。违规**一次报全**，每条带
     * {@code field}（{@code items} / {@code items[i]}）。返回归一化后的有序特征名（合法时）。
     */
    private List<String> validateItems(List<String> rawItems, Long tenantId,
                                       List<ApiResponse.ErrorDetail> details) {
        if (rawItems == null) {
            details.add(BusinessException.detail("items",
                    "items 不能为空：加工费按「选配组合」收，没有组合就没有可收的费"));
            return List.of();
        }
        if (rawItems.isEmpty()) {
            details.add(BusinessException.detail("items",
                    "组合不能为空：至少要有 1 个加工项（空组合永远匹配不到任何选配，是死数据）"));
            return List.of();
        }
        Map<String, ProcessingItem> library = queryService.activeItemsByName(tenantId);
        Set<String> seen = new LinkedHashSet<>();
        List<String> canonical = new ArrayList<>();
        for (int i = 0; i < rawItems.size(); i++) {
            String name = rawItems.get(i);
            String field = "items[" + i + "]";
            if (!StringUtils.hasText(name)) {
                details.add(BusinessException.detail(field, "加工项名不能为空"));
                continue;
            }
            if (!seen.add(name)) {
                details.add(BusinessException.detail(field, String.format(
                        "加工项「%s」重复出现：组合是**集合**，`%s+%s` 与 `%s` 归一化后是同一个键，"
                                + "重复写会让同一笔钱出现两个价", name, name, name, name)));
                continue;
            }
            if (!library.containsKey(name)) {
                details.add(BusinessException.detail(field, String.format(
                        "加工项「%s」在加工项目录中不存在或已停用：请先在「加工项管理」新增该加工项，"
                                + "或从目录里已有的加工项里选", name)));
                continue;
            }
            canonical.add(name);
        }
        return canonical;
    }

    /** 同一组合不重复定价：撞已有行（含停用行）⇒ **409**（不是 422；否则撞 DB 唯一键变 500）。 */
    private void rejectDuplicate(String compositionKey, String selfId, Long tenantId) {
        for (ProcessingFeeCombination other : allCombinations(tenantId)) {
            if (Objects.equals(other.getId(), selfId)) {
                continue;
            }
            if (Objects.equals(other.getCompositionKey(), compositionKey)) {
                throw BusinessException.conflict(
                        String.format("加工费组合「%s」已存在定价", compositionKey),
                        String.format("同一组合只能有一个价（否则下单匹配到哪一行取决于扫描顺序 ⇒ 同一份选配两个价）："
                                + "请直接编辑既有那一行（PUT /api/admin/production/processing-fee-combinations/%s），"
                                + "或改组合内容", other.getId()));
            }
        }
    }

    /** 单价护栏：缺失 / 非数值 / 负数 ⇒ 逐条理由。 */
    private static BigDecimal requiredPrice(Object value, List<ApiResponse.ErrorDetail> details) {
        if (value == null) {
            details.add(BusinessException.detail("unit_price",
                    "unit_price 不能为空：加工费单价是订单金额的直接输入，不得缺省"));
            return null;
        }
        BigDecimal price = ProcessingFeeQueryService.toDecimal(value);
        if (price == null) {
            details.add(BusinessException.detail("unit_price", "unit_price 必须是数值（元/米）"));
            return null;
        }
        if (price.compareTo(BigDecimal.ZERO) < 0) {
            details.add(BusinessException.detail("unit_price",
                    "unit_price 不得为负数：加工费是商家收的钱，负单价会把订单金额算成负数"));
            return null;
        }
        return price;
    }

    private static String optionalSource(Object value, List<ApiResponse.ErrorDetail> details) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        if (text.isEmpty()) {
            return null;
        }
        if (!SOURCES.contains(text)) {
            details.add(BusinessException.detail("source",
                    "source 只认 实证 / 推算 / 占位待确认（与工序库同词表）；未知来源就留空，不许冒充"));
            return null;
        }
        return text;
    }

    private static String requiredStatus(Object value) {
        String status = value == null ? null : String.valueOf(value).trim();
        if (!STATUSES.contains(status)) {
            throw BusinessException.validationError("status 仅支持 active/disabled");
        }
        return status;
    }

    private static Integer optionalSortOrder(Object value) {
        if (value == null) {
            return 0;
        }
        if (value instanceof Number number) {
            return number.intValue();
        }
        try {
            return Integer.valueOf(String.valueOf(value).trim());
        } catch (NumberFormatException e) {
            throw BusinessException.validationError("sort_order 必须是整数");
        }
    }

    // ══════════════════════════════ 读取 / 版本账 ══════════════════════════════

    private ProcessingFeeCombination findCombination(String id, Long tenantId) {
        ProcessingFeeCombination row = id == null ? null : combinationMapper.selectById(id);
        if (row == null || !tenantId.equals(row.getTenantId())
                || !Integer.valueOf(0).equals(row.getDeleted())) {
            throw BusinessException.notFound("加工费组合");
        }
        return row;
    }

    /** 全部未软删组合（含 disabled：重名判据要覆盖停用行，否则会撞 DB 唯一索引）。 */
    private List<ProcessingFeeCombination> allCombinations(Long tenantId) {
        List<ProcessingFeeCombination> rows = combinationMapper.selectList(
                new LambdaQueryWrapper<ProcessingFeeCombination>()
                        .eq(ProcessingFeeCombination::getTenantId, tenantId)
                        .eq(ProcessingFeeCombination::getDeleted, 0));
        return rows == null ? List.of() : rows;
    }

    /** 追加一行版本账（加工费单价是订单金额的直接输入，改价必须留痕）。 */
    private void appendVersion(ProcessingFeeCombination row, Long tenantId) {
        versionMapper.insert(ProcessingFeeCombinationVersion.builder()
                .tenantId(tenantId)
                .combinationId(row.getId())
                .compositionKey(row.getCompositionKey())
                .unitPrice(row.getUnitPrice())
                .status(row.getStatus())
                .createdAt(OffsetDateTime.now())
                .deleted(0)
                .build());
    }

    // ══════════════════════════════ 解析工具 ══════════════════════════════

    /** 特征名列表；{@code null} = body 里没给这个字段（与「给了空数组」是两回事）。 */
    @SuppressWarnings("unchecked")
    private static List<String> items(Map<String, Object> body) {
        if (body == null || !body.containsKey("items")) {
            return null;
        }
        Object raw = body.get("items");
        if (!(raw instanceof List<?> list)) {
            throw BusinessException.validationError("items 必须是加工项名数组");
        }
        List<String> names = new ArrayList<>(list.size());
        for (Object item : list) {
            names.add(item == null ? null : String.valueOf(item).trim());
        }
        return names;
    }
}
