package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 入库单列表行（V111，issue #5034）—— 含明细聚合（行数 / 总数量）。
 *
 * <p>字段名与 {@code InboundOrderQueryMapper.selectOrderLines} 的 SELECT 别名一一对应
 * （MyBatis 按列别名映射到属性名）。</p>
 */
@Data
public class InboundOrderLine {

    private String id;

    /** 入库单号 RK-yyyyMMdd-NNNN */
    private String inboundNo;

    private String supplier;

    private String supplierDocNo;

    private String warehouse;

    private LocalDate inboundDate;

    /** draft / posted / cancelled */
    private String status;

    private BigDecimal totalAmount;

    private String remark;

    private OffsetDateTime postedAt;

    private String postedBy;

    private OffsetDateTime createdAt;

    /** 明细行数（聚合） */
    private Integer itemCount;

    /** 明细总数量（聚合） */
    private Integer totalQuantity;
}
