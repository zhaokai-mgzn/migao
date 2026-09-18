package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 订单明细实体类
 * 对应表：order_items
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "order_items", autoResultMap = true)
public class OrderItem {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String orderId;

    private String productId;

    private String productName;

    /**
     * 数量（issue #3666：DECIMAL(10,2)）。口径按计价方式——per_meter=米数、
     * per_set=1、per_area=宽×高（㎡，可为小数如 8.4）。
     */
    private BigDecimal quantity;

    private BigDecimal unitPrice;

    private BigDecimal width;

    private BigDecimal height;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object processingInfo;

    private BigDecimal subtotal;

    // ── 下单行要素（V62，issue #4362，S1）──────────────────────────────────────
    // 此前这些要素要么埋在 processing_info JSONB，要么只在 C 端澄清清单里被问过却不落库
    // ⇒ 加工单只能靠加工项名**猜**部位/工艺（实证 V58：纱帘订单拿到布帘的 11 道工序，
    // 工序与计件工资全错）。**全部 nullable、不设必填校验**（用户裁定「部位不是必填的」）
    // ⇒ 派生路径不退场，它是**长期兜底**（见 ProcessingOrderService.deriveRouteKey）。
    // 逐列语义见 V62__structure_order_line_craft_spec.sql 的列注释（DB 是权威）。

    /** 部位/帘种（布帘/纱帘/帘头）；工序库路线按它索引（production_routings.curtain_type） */
    private String curtainType;

    /** 安装工艺＝打褶/悬挂方式（韩褶/打孔/穿杆/平幔）；**单值**。四爪钩是加工项、不是工艺 */
    private String craft;

    /** 打开方式（开数：1 单开 / 2 对开 / 4 四开） */
    private Integer openCount;

    /** 加工类型（定高买宽 / 定宽买高） */
    private String cuttingMode;

    /** 是否定型（部位级开关；false ⇒ 加工单实例化剔除 定型-布/复烫-布） */
    private Boolean isShaped;

    /** 理论褶倍（名义倍数，如 2.00） */
    private BigDecimal fullness;

    /** 实际褶倍（由实际用料反算，如 1.86）—— 与理论褶倍**分开存**，不是冗余字段 */
    private BigDecimal fullnessActual;

    /** 褶距（米，韩褶默认 0.1） */
    private BigDecimal pleatSpacing;

    /** 总褶数（与工序应做数量口径对齐：韩褶-布 的 qty 单位＝折） */
    private Integer pleatCount;

    /** 是否对花 */
    private Boolean hasPattern;

    /** 转角（取自澄清清单窗型；影响开数与片数） */
    private String corner;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
