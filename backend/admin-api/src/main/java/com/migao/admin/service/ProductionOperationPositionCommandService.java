package com.migao.admin.service;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionOperationPositionPriceVersion;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPositionPriceVersionMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 部位价目矩阵**写面**（issue #4587 ② = 母单 #4586 包A）：
 * 唯一入口 = {@code PUT /api/admin/production/operation-positions/{id}}。
 *
 * <p><b>这一屏的价 = 给工人的「计件单价」（报工工资 = 数量 × 计件单价）</b>，
 * <b>不是</b>对客加工费 —— 对客那两本账在别处：基础加工费 = 加工项组合费用（元/米），
 * 特殊选项 = {@code production_route_rules.customer_unit_price}（元/套，V77）。
 * ⚠️ 三本账不得互读、不得混（用户裁定 2026-09-19：「工序项当前的计件单价就是满足的，
 * 包工工资在计件工资体现，算法是数量 × 计件单价」）。</p>
 *
 * <p>本类**从不读**对客那一列（上面只是文档里对照说明）—— 这条纪律由
 * {@code tests/unit_ci_workflows/test_option_fee_seed.py} 的「两套账不互读」判据守着：
 * 它**只看代码**（扫描前做 Java 词法级去注释，字符串字面量保留）⇒ 文档里写清列名是安全的
 * （issue #4595 修准了该判据；此前它是裸子串扫描，会把注释里的提及误判成越界读取）。</p>
 *
 * <p><b>状态（issue #4937 / O1 之后的终态）</b>：可写面**只剩 `unit_price` 一列** ——
 * {@code applicable}（部位适用性）已**退场**，收到该字段一律 **422 + 可行动 hint**（<b>拒绝</b>，
 * 不静默忽略）。价的两态仍在：显式传 {@code unit_price=null} ⇒ 「<b>未定价</b>」（<b>≠ 0 元</b>）；
 * 传数值 ⇒ 有价（{@code 0} 就是<b>有价 0 元</b>，与「未定价」在数据上可区分）。</p>
 *
 * <p><b>留痕（不许静默）</b>：价<b>真的变了</b>才同事务向
 * {@code production_operation_position_price_versions}（V86）追加一行 —— 本仓既有契约是
 * 「改价必须留痕」（工序价 V55 / 路线 V60 / 选项对客价 V77），矩阵价此前<b>没有账</b>。</p>
 *
 * <p><b>为什么单独一个类</b>：读面在 {@link ProductionRoutingReadService}（只有 SELECT）、
 * 工序库写面在 {@link ProductionOperationCommandService} —— 「谁在改矩阵价」必须可 grep
 * （与 #4204 的读写分开同口径）。响应形态复用读面的同一份整形（{@code positionRowView}），
 * 两处各拼一份必然漂移。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionOperationPositionCommandService {

    /** 单价小数位（列是 {@code NUMERIC(10,2)}）：超两位**拒绝**，不静默四舍五入。 */
    private static final int PRICE_SCALE = 2;

    private final ProductionOperationPositionMapper productionOperationPositionMapper;
    private final ProductionOperationPositionPriceVersionMapper priceVersionMapper;
    /** 响应形态 = ① 的单行同构（同一份 {@code positionView}，前端同一个类型渲染）。 */
    private final ProductionRoutingReadService productionRoutingReadService;
    // ⛔ issue #4937 / O1：原来的 `ProductionOperationQueryService` 依赖（#4798 的
    // 「结果态 applicable=true 必须解析得到变体工序」护栏）已**随 `applicable` 字段主体一并退休**
    // —— 判据的输入不复存在。「能解析出变体」这件事现由实例化侧的 `missing_operations` 兜底
    // （`ProcessingOrderService.buildRoute` fail-closed 并指名报缺）。

    /**
     * 矩阵格就地改价（**部分更新**：只写 body 里出现的键）。
     *
     * <p>🔴 <b>{@code applicable} 已退场（issue #4937 / O1，用户裁定 2026-09-21「不计成本的改」）</b>：
     * body 里出现 {@code applicable} ⇒ <b>422 + 可行动 hint</b>（「部位适用性已退场，不再受理该字段」），
     * <b>拒绝</b>而**不静默忽略** —— 静默 no-op 是本仓最忌的形态（调用方以为改成了「不做」，
     * 实际那格照旧参与实例化 ⇒ 工人按错工序拿钱，且**没有任何报错**）。
     * 其护栏 {@code variantOperationOf}（#4798 的「结果态 {@code applicable=true} 必须解析得到变体」）
     * 随该字段主体**一并退休** —— 判据的输入已经不复存在（且「能解析出变体」这件事已由
     * 实例化侧的 {@code missing_operations} 兜底）。</p>
     *
     * @param body 只可含 {@code unit_price}（number|null）；
     *             {@code null} 的价 = 显式改回**未定价**（≠ 0 元）
     * @return 更新后的矩阵格（形态与 {@code GET /operation-positions} 的**单行同构**）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> update(String id, Map<String, Object> body, Long tenantId) {
        ProductionOperationPosition row =
                id == null ? null : productionOperationPositionMapper.selectById(id);
        if (row == null || !tenantId.equals(row.getTenantId())
                || !Integer.valueOf(0).equals(row.getDeleted())) {
            throw BusinessException.notFound("部位价目行");
        }
        // 改价前的价必须先留存：下面 row 会被就地改成新值（用于响应），改完再比就恒等 ⇒ 版本账永空
        BigDecimal previousPrice = row.getUnitPrice();
        BigDecimal newPrice = previousPrice;
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        // ⛔ **显式拒绝**（不是静默忽略）：部位适用性已退场，不再受理该字段（issue #4937 / O1）。
        if (body != null && body.containsKey("applicable")) {
            details.add(BusinessException.detail("applicable",
                    "部位适用性已退场，不再受理该字段 —— 矩阵格只承载「这道逻辑工序的计件单价」；"
                            + "请只传 unit_price（不传 applicable）"));
        }
        if (body != null && body.containsKey("unit_price")) {
            newPrice = price(body.get("unit_price"), details);
        }
        if (!details.isEmpty()) {
            // 违规**一次报全**（不是报第一条就返回）；失败一律不落库
            throw BusinessException.validationError(
                    "部位价目更新未通过校验（" + details.size() + " 条问题）", details,
                    "单价填 ≥ 0 且最多两位小数的金额；要表示「未定价」请传 null，**不要**传 0");
        }
        int rows = productionOperationPositionMapper.updateUnitPrice(
                row.getId(), tenantId, newPrice, OffsetDateTime.now());
        if (rows == 0) {
            throw BusinessException.notFound("部位价目行");
        }
        row.setUnitPrice(newPrice);
        if (priceChanged(previousPrice, newPrice)) {
            priceVersionMapper.insert(ProductionOperationPositionPriceVersion.builder()
                    .tenantId(tenantId)
                    .positionRowId(row.getId())
                    .unitPrice(newPrice)
                    .createdAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
            log.info("部位价目调价: tenantId={}, rowId={}, {} × {} : {} -> {}",
                    tenantId, row.getId(), row.getLogicalName(), row.getPosition(),
                    previousPrice, newPrice);
        }
        return productionRoutingReadService.positionRowView(tenantId, row);
    }

    /**
     * 价**真的变了**才记账（{@code null} 与任何值都算变：改回未定价 / 不做 ⇒ 价清空）。
     *
     * <p>用 {@code compareTo} 而不是 {@code equals}：{@code 0.40} 与 {@code 0.4} 是同一个价
     * （{@code BigDecimal.equals} 按 scale 比 ⇒ 会把「同价的另一种写法」记成一次调价）。</p>
     */
    private static boolean priceChanged(BigDecimal before, BigDecimal after) {
        if (before == null || after == null) {
            return before != after;
        }
        return before.compareTo(after) != 0;
    }

    /**
     * 计件单价解析：{@code null} / 空串 ⇒ {@code null}（= 改回**未定价**，**≠ 0 元**）；
     * 非数值 / 负数 / 超过两位小数 ⇒ 记 detail（422 逐条理由）。
     *
     * <p>为什么用 {@code setScale(2, UNNECESSARY)} 而不是 {@code round}：前者在「填了 6.005」时
     * <b>抛异常</b>（商家知道自己填多了），后者静默变成 6.01（改了钱且无人知道）。</p>
     */
    private static BigDecimal price(Object value, List<ApiResponse.ErrorDetail> details) {
        String text = value == null ? "" : String.valueOf(value).trim();
        if (text.isEmpty()) {
            return null;
        }
        BigDecimal parsed;
        try {
            parsed = new BigDecimal(text);
        } catch (NumberFormatException e) {
            details.add(BusinessException.detail("unit_price",
                    "单价必须是数字（元/单位）；要表示「未定价」请传 null 或空串，**不要**传 0"));
            return null;
        }
        if (parsed.signum() < 0) {
            details.add(BusinessException.detail("unit_price",
                    "单价不能为负（这是付工人的**计件**单价，不是对客加工费）"));
            return null;
        }
        try {
            return parsed.setScale(PRICE_SCALE, RoundingMode.UNNECESSARY);
        } catch (ArithmeticException e) {
            details.add(BusinessException.detail("unit_price",
                    "单价最多两位小数（列是 NUMERIC(10,2)）—— 不接受静默四舍五入，请自己改到两位"));
            return null;
        }
    }
}
