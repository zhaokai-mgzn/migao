package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.OutboundOrder;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 出库单（V196，issue #7750）。
 *
 * <p>单号归谁由 {@code uk_outbound_orders_no} 在<b>插入那一刻</b>裁 —— 取号与占号是
 * {@link #insertIgnoreOutboundNoConflict(OutboundOrder)} 这<b>一条语句</b>（issue #8490，
 * 与入库单 {@code InboundOrderMapper#insertIgnoreInboundNoConflict} 同形态）；状态只有
 * {@code posted} 一个取值（DB CHECK），没有需要原子迁移的状态机 ⇒ 不需要手写 CAS SQL。</p>
 */
@Mapper
public interface OutboundOrderMapper extends BaseMapper<OutboundOrder> {

    /**
     * 取号 + 落库的**一条语句**（issue #8490）：单号冲突时该语句<b>不报错、返回 0 行</b>。
     *
     * <p>⚠️ {@code ON CONFLICT} 的目标必须带<b>索引谓词</b> {@code WHERE deleted = 0}：{@code uk_outbound_orders_no}
     * 是<b>部分</b>唯一索引（V196），PG 的冲突推断要求谓词匹配；{@code ON CONFLICT ON CONSTRAINT} 形态对
     * 部分唯一索引不成立（它不是 constraint）。同族先例见 {@code InboundOrderMapper#insertIgnoreInboundNoConflict}。</p>
     *
     * <p>{@code ON CONFLICT … DO NOTHING} 与「捕获 {@code DuplicateKeyException} 再重试」的差别是
     * <b>语义性</b>的：冲突时 PG 的<b>当前事务不会进入 aborted 状态</b>（该语句不报错）
     * ⇒ 可以在<b>同一个事务</b>里安全地换号重试；若靠捕获异常，PG 已把事务标记为坏
     * ⇒ 只有 {@code REQUIRES_NEW} 才救得回来，而那会把单据提前提交（后续明细行失败 ⇒ 留下半张单）。</p>
     *
     * <p>⚠️ <b>列清单显式</b>（issue #4608 纪律），且与「建单会写的列」同界：只列建单写的列 ——
     * {@code created_at} / {@code updated_at}（DB 默认 {@code NOW()}）、{@code deleted}（默认 0）不在此。
     * 新增「建单即写」的列必须同步到这里（判据 = {@code OutboundNoTakeRaceRealDbTest} 的字段回读断言）。</p>
     *
     * @return 影响行数：{@code 1} = 号归我（单据已落库）；{@code 0} = 该号刚被别的事务抢走（换候选重来）
     */
    @InterceptorIgnore(tenantLine = "true")
    @Insert("INSERT INTO outbound_orders (id, tenant_id, outbound_no, biz_category, source, warehouse_id,"
            + " warehouse, outbound_date, status, total_amount, order_id, order_no, remark, posted_at,"
            + " posted_by, created_by)"
            + " VALUES (#{o.id}, #{o.tenantId}, #{o.outboundNo}, #{o.bizCategory}, #{o.source},"
            + " #{o.warehouseId,jdbcType=BIGINT}, #{o.warehouse,jdbcType=VARCHAR}, #{o.outboundDate},"
            + " #{o.status}, #{o.totalAmount}, #{o.orderId,jdbcType=VARCHAR}, #{o.orderNo,jdbcType=VARCHAR},"
            + " #{o.remark,jdbcType=VARCHAR}, #{o.postedAt}, #{o.postedBy,jdbcType=VARCHAR},"
            + " #{o.createdBy,jdbcType=VARCHAR})"
            + " ON CONFLICT (tenant_id, outbound_no) WHERE deleted = 0 DO NOTHING")
    int insertIgnoreOutboundNoConflict(@Param("o") OutboundOrder order);
}
