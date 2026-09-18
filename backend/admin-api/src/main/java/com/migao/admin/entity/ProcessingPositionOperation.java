package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 工序实例：加工单 × 部位 × 工序（issue #3995，M4-G-2）
 * 对应表：processing_position_operations（V49）。扫码报工的推进单元；
 * 应做数量 = 算料引擎输出，报工只确认不心算（真值源 §3）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "processing_position_operations", autoResultMap = true)
public class ProcessingPositionOperation {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String processingOrderId;

    /** 部位：布帘/纱帘/帘头/外帘 */
    private String positionName;

    /** 部位内工序顺序 */
    private Integer seq;

    private String operationName;

    /** 车间工位分组：裁剪/车位/后道/其他 */
    private String groupName;

    /** 计件单位：米/折/幅/孔/套/个 */
    private String unit;

    /** 应做数量（算料引擎输出） */
    private BigDecimal qty;

    /**
     * 应做数量的口径来源（issue #4208）：键名（{@code fabric_meters}/{@code pleat_count}/{@code holes}）
     * = 算料输出直接供数；{@code <键名>_x6} = 按每米 6 孔的有依据估算；{@code fallback} = 真兜底 1。
     * 存在的唯一理由：让「算料输出」与「兜底」在数据上可区分（兜底不静默）。
     */
    private String qtySource;

    /** 实例快照单价（调价不影响历史报工） */
    private BigDecimal unitPrice;

    /** 特殊选项计件系数（如 一分为二 ×1.7；选项名 = ERP 名，issue #4389） */
    private BigDecimal factor;

    /** 必完工序：全绿 → 加工单置 completed（生产完工；订单状态不动，issue #4117） */
    private Boolean isMustFinish;

    /** 生产开始标记 */
    private Boolean isStartMarker;

    /** pending 待做 / done 已报工 */
    private String status;

    /** 合格累计数量（仅正常报工累加） */
    private BigDecimal doneQty;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
