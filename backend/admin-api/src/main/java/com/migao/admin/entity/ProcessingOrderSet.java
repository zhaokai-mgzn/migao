package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * 套号载体：一个加工单 × 一套 = 一行（V92，切片 ⓪ / issue #4698；设计 §2.2）。
 *
 * <p><b>一套 = 一樘窗</b>（= 一个 {@code craftLineId} 组 / 一个窗的全部部位合计一套，用户裁定
 * 2026-09-20）—— 不是一条 {@code order_items} 行。{@code set_no} = {@code {加工单号}-{3 位 set_index}}，
 * **落库冗余**（码里印的是它，扫码解析按文本查唯一索引）。</p>
 *
 * <p>{@code position_item_ids}（JSONB 部位清单）与 {@code craft_line_id} 由**分配器**
 * （切片 ⓪.5，issue #4789 / {@code ProcessingOrderSetAllocator}）写入：前者是「这套有哪几个部位」
 * 的载体（也是 V92 回填认领已有套行的**指纹**），后者是樘窗组键 —— 两者都**必须与 V92 同口径**，
 * 故由同一个分配器一并落库（不造第二份）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "processing_order_sets", autoResultMap = true)
public class ProcessingOrderSet {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String processingOrderId;

    /** 一樘窗在本加工单里的次序（1 起，3 位零填充进 {@link #setNo}）；**只增不复用**。 */
    private Integer setIndex;

    /** 可读套号 = {@code {processing_order_no}-{pad3(set_index)}}。 */
    private String setNo;

    /**
     * 樘窗组键（= 快照 {@code craftLineId}，缺省 = 该组主布行的 {@code itemId}）；**可空**
     * （存量 / 脏快照，与 {@code ProcessingOrderService.craftGroupKey} 同口径）。
     */
    private String craftLineId;

    /**
     * 本套包含的**部位行** {@code order_items.id} 数组（**有序**）。
     * 与 V92 回填的 {@code jsonb_agg(... ORDER BY ord)} 逐值一致。
     */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<String> positionItemIds;

    private Integer deleted;
}
