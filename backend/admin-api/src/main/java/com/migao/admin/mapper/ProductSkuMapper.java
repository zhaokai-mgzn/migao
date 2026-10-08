package com.migao.admin.mapper;

import com.migao.admin.entity.ProductSku;
import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.math.BigDecimal;
import java.util.Map;

/**
 * 商品SKU Mapper 接口
 *
 * <p><b>数量参数一律 {@link BigDecimal}（V115 / issue #5063）</b>：库存列已由 {@code INTEGER}
 * 升级为 {@code NUMERIC(12,1)}（1 位小数 = 0.1 米粒度）。这里<b>不得</b>再出现 {@code int} /
 * {@code intValue()} 形参 —— 传 {@code int} 会强迫调用方在边界上取整，而那种取整是静默的
 * （买 2.7 米扣 2 米、0.7 米凭空消失），正是本单要治的形态。
 * 「多少位小数算合法」的唯一判据在 {@code com.migao.admin.service.StockQuantity}。</p>
 */
@Mapper
public interface ProductSkuMapper extends BaseMapper<ProductSku> {

    /**
     * 🔴 <b>扣库存的唯一入口（issue #6299）：一条带下限谓词的原子条件更新 + {@code RETURNING} 取变更前后</b>。
     *
     * <p><b>为什么是这个形态</b>（不是"看着优雅"）：</p>
     * <ul>
     *   <li><b>判断与写入同一条语句</b>：谓词 {@code COALESCE(stock,0) >= #{quantity}} 由 PG
     *       在<b>行锁下重估</b> ⇒ 两单并发时只有一个能改到，另一个拿 0 行（返回 {@code null}）
     *       ⇒ 调用方显式失败。<b>改前</b>是
     *       {@code SET stock = GREATEST(COALESCE(stock,0) - qty, 0)}——<b>无下限谓词 + 静默钳 0</b>：
     *       并发下两单都改到、库存被钳到 0，调用方从返回值上<b>根本看不出「扣不动」</b>
     *       （实测：库存 10 米、两单各 8 米并发确认收款 ⇒ {@code [200,200]}、库存 {@code 10.0→0.0}，
     *       少扣 6 米且无任何 4xx —— {@code acceptance/2026-10-04/replay-postdeploy/race/probe-write-raw.json::cases.W4}）。</li>
     *   <li><b>台账读数与扣减同源</b>：{@code RETURNING ceil(stock + qty) AS beforeQuantity, stock AS afterQuantity}
     *       —— 这两个值是<b>同一条语句在同一行锁下</b>取的，调用方拿它落
     *       {@code stock_ledger_entries} ⇒ 并发下台账仍首尾相接。若让调用方另取快照
     *       （{@code SELECT stock}）再比对，两单会读到<b>同一个 before</b>（同基、链断裂，
     *       见 issue #6300 的同族现场读数）。</li>
     *   <li><b>与既有同族形态一致</b>：{@code OrderMapper.autoCompleteShippedOrders} 同款
     *       （{@code @Select} + CTE + {@code RETURNING}）。</li>
     * </ul>
     *
     * <p>🔴 <b>为什么是 {@code @Select} + CTE 而不是 {@code @Update}</b>（实测，不是口味）：
     * MyBatis 的 {@code @Update} <b>只接受 int/long/boolean/void 返回类型</b> —— 想要
     * {@code RETURNING} 的行，声明 {@code Map} 会当场抛
     * {@code BindingException: unsupported return type}。把
     * {@code WITH updated AS (UPDATE … RETURNING …) SELECT … FROM updated} 写成 {@code @Select}
     * 就同时拿到两样东西：<b>仍然只有一条 SQL 语句</b>（PG 的 CTE 里 UPDATE 与 SELECT 同一快照、
     * 同一事务），且返回类型受支持。</p>
     *
     * <p>{@code GREATEST} 钳 0 <b>已删除</b>：它把「扣不动」静默变成「扣到 0」，正是超卖的掩盖物
     * （{@code migao-dev-flow} §23：修一处形态必须同时删掉掩盖它的写法）。</p>
     *
     * <p>🔴 <b>{@code @InterceptorIgnore(tenantLine = "true")} + <u>显式</u> {@code tenant_id = #{tenantId}}</b>
     * —— <b>不是</b>口味问题，是实测约束：MyBatis-Plus 3.5.16 的多租户拦截器进入
     * {@code processSelect} 后会走 {@code WithItem.getSelect()}，而 CTE 里包着的是 {@code UPDATE}
     * （{@code ParenthesedUpdate}）⇒ 当场抛
     * {@code ClassCastException: ParenthesedUpdate cannot be cast to ParenthesedSelect}
     * （本单第一版实测：真库判据整类红）。这与 {@code OrderMapper.autoCompleteShippedOrders}
     * （issue #6262 实测撞到同一处）的处置**同源**：关掉改写 + 把租户条件<b>写出来</b>，
     * 少一层「条件到底加没加」的不可见性。</p>
     *
     * @param tenantId 只动本租户（多租户隔离的**显式**条件，配合 {@code @InterceptorIgnore}）
     * @return 扣减成功 ⇒ {@code beforeQuantity}/{@code afterQuantity}/{@code skuCode}
     *         （键名即列名别名）；<b>库存不足（0 行）⇒ {@code null}</b> —— 调用方必须显式失败
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("WITH updated AS ("
            + "UPDATE product_skus SET stock = COALESCE(stock, 0) - #{quantity} "
            + "WHERE id = #{skuId} AND tenant_id = #{tenantId} AND COALESCE(stock, 0) >= #{quantity} "
            + "RETURNING sku_code AS \"skuCode\", "
            + "          CEIL(stock + #{quantity}) AS \"beforeQuantity\", "
            + "          stock AS \"afterQuantity\""
            + ") SELECT \"skuCode\", \"beforeQuantity\", \"afterQuantity\" FROM updated")
    Map<String, Object> deductStock(@Param("skuId") Long skuId, @Param("quantity") BigDecimal quantity,
                                   @Param("tenantId") Long tenantId);

    @Update("UPDATE product_skus SET stock = COALESCE(stock, 0) + #{quantity} " +
            "WHERE id = #{skuId}")
    int restoreStock(@Param("skuId") Long skuId, @Param("quantity") BigDecimal quantity);

    /**
     * 入库：加库存 + 写移动加权平均成本 + 记最近批次号（V111，issue #5034）。
     *
     * <p><b>均价由调用方（{@code InboundOrderService}）算好后传入</b>，不在 SQL 里重算 ——
     * 加权平均的公式只有一处实现（{@code InboundOrderService.movingAverage}），
     * 落库值与落台账的成本快照**必然同源**；两边各写一份公式迟早会漂移，
     * 而漂移的表现是「台账里的 avg_cost_after 与 SKU 上的 avg_cost 不一致」——
     * 一条只在事后对账时才看得见的账实不符。</p>
     *
     * <p>均价是<b>条件更新</b>：{@code newAvgCost IS NULL}（本行未记单价且此前无均价）时
     * 保持 NULL —— 不用 0 冒充「成本为零」。{@code cost_amount} 只在均价非 NULL 时算。</p>
     *
     * <p><b>每个 {@code newAvgCost} 绑定都必须带 {@code jdbcType=NUMERIC}（issue #5975）</b>：
     * {@code CASE WHEN ? IS NULL} 里的 {@code ?} <b>没有列 / cast 作为类型锚点</b> —— 实参为
     * <b>NULL</b> 时 PG 收到的是 <i>unspecified</i> 类型参数，直接抛
     * {@code ERROR: could not determine data type of parameter $3} ⇒ {@code BadSqlGrammarException}
     * ⇒ 接口 500。而「新 SKU 首次入库 + 明细不记单价」（入库页明示允许留空）恰好<b>必然</b>
     * 走 null 实参（{@code InboundOrderService.movingAverage} 在无进价且此前无均价时原样返回
     * {@code beforeAvg} = NULL）⇒ 商家按页面提示操作时，新 SKU 的第一次过账必然失败。
     * 显式 jdbcType 让 PG 拿到参数类型，不再依赖推断。真库判据 =
     * {@code com.migao.admin.service.ProductSkuReceiveStockNullCostRealDbTest}。</p>
     *
     * @param newAvgCost 变更后的移动加权平均成本（null = 成本仍未知）
     * @param tenantId   只动本租户（多租户隔离的**显式**条件，配合 {@code @InterceptorIgnore}）
     * @return 入库成功 ⇒ {@code beforeQuantity}/{@code afterQuantity}（变更前/后的库存，
     *         由<b>同一条语句</b>的 {@code RETURNING} 给出，见 issue #6300）；**0 行 ⇒ {@code null}**
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("WITH updated AS ("
            + "UPDATE product_skus SET "
            + "stock = COALESCE(stock, 0) + #{quantity}, "
            + "avg_cost = #{newAvgCost,jdbcType=NUMERIC}, "
            + "cost_amount = CASE WHEN #{newAvgCost,jdbcType=NUMERIC} IS NULL THEN NULL "
            + "                   ELSE ROUND((COALESCE(stock, 0) + #{quantity}) * #{newAvgCost,jdbcType=NUMERIC}, 4) END, "
            + "latest_batch_no = #{batchNo} "
            + "WHERE id = #{skuId} AND tenant_id = #{tenantId} "
            + "RETURNING CEIL(stock - #{quantity}) AS \"beforeQuantity\", "
            + "          stock AS \"afterQuantity\""
            + ") SELECT \"beforeQuantity\", \"afterQuantity\" FROM updated")
    Map<String, Object> receiveStock(@Param("skuId") Long skuId, @Param("quantity") BigDecimal quantity,
                                     @Param("newAvgCost") BigDecimal newAvgCost, @Param("batchNo") String batchNo,
                                     @Param("tenantId") Long tenantId);

    @Update("UPDATE product_skus SET sales_count = COALESCE(sales_count, 0) + #{quantity} " +
            "WHERE id = #{skuId}")
    void increaseSalesCount(@Param("skuId") Long skuId, @Param("quantity") BigDecimal quantity);

    @Update("UPDATE product_skus SET sales_count = GREATEST(COALESCE(sales_count, 0) - #{quantity}, 0) " +
            "WHERE id = #{skuId}")
    void decreaseSalesCount(@Param("skuId") Long skuId, @Param("quantity") BigDecimal quantity);
}
