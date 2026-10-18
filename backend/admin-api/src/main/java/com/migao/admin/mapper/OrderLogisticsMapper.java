package com.migao.admin.mapper;

import com.migao.admin.entity.OrderLogistics;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * 物流跟踪 Mapper 接口
 *
 * <p>🔴 手写 {@code @Select} 必须显式绑 autoResultMap（口径见 {@code ProcessingOrderMapper} 类注释）：
 * 否则 {@code tracking_info}（JSONB）以 JSON 字符串落到 {@code Object} 字段上。</p>
 */
@Mapper
public interface OrderLogisticsMapper extends BaseMapper<OrderLogistics> {

    /**
     * 根据订单 ID 查询物流记录
     */
    @ResultMap("mybatis-plus_OrderLogistics")
    @Select("SELECT * FROM order_logistics WHERE order_id = #{orderId} AND deleted = 0 AND tenant_id = #{tenantId} ORDER BY created_at DESC")
    List<OrderLogistics> selectByOrderId(@Param("orderId") String orderId, @Param("tenantId") Long tenantId);

    /**
     * **条件更新**一条订单的物流写面（issue #7174）—— 一次发货只有这一条写路径。
     *
     * <p><b>为什么要有它</b>：原实现是「先 {@code selectByOrderId} 看有没有行，再 insert / 整实体
     * {@code updateById}」的**读改写**。并发两次发货时，两边都读到「没有行」⇒ 都 insert ⇒
     * 同一订单出现**两条**物流记录（列表重复、后续 {@code getById} 取到哪条不确定）。
     * 现在改成「**先条件更新，影响行数为 0 才建行**」：更新是一条带 {@code (tenant_id, order_id, deleted=0)}
     * 谓词的 UPDATE，影响行数就是「这一行当时是否存在」的**原子读数**，不再依赖先读后写。</p>
     *
     * <p><b>只写本次请求显式给的列</b>（与 {@code OrderLogisticsWriter} 的「显式才覆盖」口径同一件事）：
     * 承运商与运单号必写；发货人 / 物流类型 / 发货方式只在传入非空时覆盖（{@code NULLIF} 把空串也当"没说"），
     * 缺席 = 保留原值。整实体 {@code updateById} 回写会让实体里读到的旧值盖掉别处刚写的值。</p>
     *
     * <p><b>首次发货时刻（issue #6276 不变）</b>：{@code shipped_at = COALESCE(shipped_at, created_at)}
     * —— 只有为空时才补，补的值仍是建行时刻（列对列），已有值逐字不动；且与更新在同一条语句里完成，
     * 不存在"先补后回写把值盖回去"的顺序问题。</p>
     *
     * @param shipperName    空/{@code null} = 本次请求没说这件事 ⇒ 保留原值
     * @param logisticsType  同上
     * @param shippingMethod 同上
     * @return 受影响行数（0 = 该订单当前没有物流行 ⇒ 调用方负责建行）
     */
    @Update("UPDATE order_logistics SET "
            + "logistics_company = #{logisticsCompany}, tracking_no = #{trackingNo}, "
            + "shipper_name = COALESCE(NULLIF(#{shipperName}, ''), shipper_name), "
            + "logistics_type = COALESCE(NULLIF(#{logisticsType}, ''), logistics_type), "
            + "shipping_method = COALESCE(NULLIF(#{shippingMethod}, ''), shipping_method), "
            + "status = COALESCE(status, 'in_transit'), "
            + "shipped_at = COALESCE(shipped_at, created_at), "
            + "updated_at = NOW() "
            + "WHERE order_id = #{orderId} AND tenant_id = #{tenantId} AND deleted = 0")
    int updateShippingDetails(@Param("tenantId") Long tenantId,
                              @Param("orderId") String orderId,
                              @Param("logisticsCompany") String logisticsCompany,
                              @Param("trackingNo") String trackingNo,
                              @Param("shipperName") String shipperName,
                              @Param("logisticsType") String logisticsType,
                              @Param("shippingMethod") String shippingMethod);

    /**
     * 给**缺发货时刻**的物流行补上**首次发货时刻**（issue #6276）。
     *
     * <p><b>语义（用户 2026-10-10 裁定）</b>：{@code shipped_at} = <b>首次发货时刻</b> ——
     * 不是「最近一次改物流的时刻」（那条口径已被否掉）。</p>
     *
     * <p><b>表内真值 = {@code created_at}</b>：本表的三条建行路径（
     * {@code OrderLogisticsWriter.upsert} 的 insert 分支、{@code OrderLogisticsService.createLogistics}、
     * {@code OrderController.updateLogistics} 的建行分支）都在建行那一刻写 {@code shipped_at = now()}，
     * 而 {@code created_at}（{@code FieldFill.INSERT} + 列 {@code DEFAULT NOW()}）就是同一刻 ——
     * 两者是同一事实的两种记法。故历史行（{@code shipped_at} 列尚不存在时建的）的首次发货时刻
     * 在表内**已经有真值**，无需外部输入、也无需猜。</p>
     *
     * <p>🔴 <b>只补 {@code IS NULL} 的行</b>：已有值一律逐字不动 —— 一条带谓词的条件 UPDATE 承担这条不变量
     * （不是「先读再判」）。且赋值右侧取的是**该行自己的** {@code created_at}（列对列），
     * 不取 {@code now()}、也不取调用方的时钟 ⇒ 无论多少条路径/多少个实例同时调它，
     * 补出来的值恒等于建行时刻（第二次调用 0 行）。</p>
     *
     * <p>调用点必须在同一行的 {@code updateById} <b>之前</b>（否则实体里的旧 {@code shipped_at}
     * 会把刚补的值盖回去）。租户由 {@code TenantLineInnerInterceptor} 与本方法的显式
     * {@code tenant_id} 谓词双重约束（同 {@code selectByOrderId} 口径）。</p>
     *
     * @return 本次真正补到的行数（0 = 无需补 / 已经补过）
     */
    @Update("UPDATE order_logistics SET shipped_at = created_at "
            + "WHERE order_id = #{orderId} AND tenant_id = #{tenantId} AND deleted = 0 AND shipped_at IS NULL")
    int backfillShippedAtIfAbsent(@Param("orderId") String orderId, @Param("tenantId") Long tenantId);
}
