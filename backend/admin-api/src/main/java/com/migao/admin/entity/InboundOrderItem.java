package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 入库单明细实体（issue #5034）
 * 对应表：inbound_order_items（V111）—— <b>一个 SKU 行 = 一个批次</b>（用户裁定 2026-09-23）。
 *
 * <p>批次粒度取行级而非卷级：缸号的行业粒度本就是「一批布」
 * （docs/curtain-selling-method-industry-research.md §1），卷级会要求「库存 = 卷集合求和」的模型升级，
 * 而卷长是区间值（同文件 §8.2 末明确不建议硬折算）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("inbound_order_items")
public class InboundOrderItem {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String inboundOrderId;

    /** SKU 主键（无 FK：SKU 会被硬删重建，同 {@link StockLedger#getSkuId()}） */
    private Long skuId;

    private String productId;

    /** 快照：入库时点的货号（事后改商品不影响历史单） */
    private String skuCode;

    /** 快照：颜色名 */
    private String colorName;

    /** 快照：门幅 */
    private String doorWidth;

    /**
     * **入库米数**（1 位小数：与 {@code product_skus.stock} 粒度逐字一致；V115/#5063 起支持小数米）。
     *
     * <p>🔴 本列**恒为米数**（issue #7709）：按卷录入时它由服务端算好
     * （{@code 卷数 × 卷长}，见 {@link #rollCount} / {@link #rollLengthM}），不存卷数。
     * 唯一的历史例外 = 本改动**之前**的拍照单行（{@code source=photo} 且 {@link #rollCount} 为空）——
     * 那时它存的是卷数，读面由 {@code InboundOrderService.storedMeters} 兼容（用户裁定「历史不动」）。</p>
     */
    private BigDecimal quantity;

    /** 入库单价（元/单位）；NULL = 未记单价 ⇒ 只加数量、不算成本 */
    private BigDecimal unitCost;

    /** 行金额 = quantity * unitCost；NULL 单价 ⇒ NULL（不用 0 冒充） */
    private BigDecimal amount;

    /** 本行批次号 PC-yyyyMMdd-NNNN；**过账时才写**（草稿为 NULL） */
    private String batchNo;

    /** 供应商缸号（外部事实，可空；**不得**用 batchNo 冒充） */
    private String dyeLot;

    /**
     * 旧系统批次号（外部事实，可空；V118 / issue #5153）。
     *
     * <p>只允许在 {@code source=opening} 的期初建账单上填（应用层一处校验）；
     * 过账时**透传**到 {@code stock_batches.legacy_batch_no}。为什么明细行也要一列：建单（草稿）
     * 与过账是两次请求，{@code post()} 从库里回读明细行再写批次行 ⇒ 明细行不落这一列，
     * 建单时填的旧号在过账那一刻就丢了。</p>
     */
    private String legacyBatchNo;

    /**
     * 每卷米数（卷长）。
     *
     * <p>与 {@link #rollCount} **成对**才参与换算（入库米数 = 卷数 × 本值，issue #7709）；
     * 只填本值不填卷数 ⇒ 仍是「仅记录 / 打印卷标」，{@link #quantity} 本身就是米数
     * （#5034：散剪 / 尾料按米录，卷长可能只是供应商侧的事实）。</p>
     */
    private BigDecimal rollLengthM;

    /**
     * 卷数（外部事实，issue #7709；V191 加列）。
     *
     * <p>有值 ⇒ 入库米数 = 本值 × {@link #rollLengthM}（服务端唯一换算点
     * {@code InboundOrderService.metersOfRolls} 在建单时算好写进 {@link #quantity}，
     * 客户端的 quantity 不采信）；为空 ⇒ 按米录入。
     * 工人拍照单（issue #6812）的请求体「数量」本来就指卷数 ⇒ 建单时映射进本列。
     * 🔴 卷数只在这里，别在 {@link #quantity} 里再记一份（两个事实两处记 = 必然漂移）。</p>
     */
    private Integer rollCount;

    private String remark;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    /** 软删：标 @TableLogic ⇒ 查询自动带 deleted = 0（软删行不得出现在列表/详情里） */
    @TableLogic
    private Integer deleted;
}
