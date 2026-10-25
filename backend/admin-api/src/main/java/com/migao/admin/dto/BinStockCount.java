package com.migao.admin.dto;

import lombok.Data;

/**
 * 仓位在库件数（水位分子，issue #7791）—— 一条 GROUP BY 聚合，不搬整行在库数据。
 */
@Data
public class BinStockCount {

    private String binCode;

    /** 该仓位当前在库件数（= 在库行数） */
    private Integer inStockCount;
}
