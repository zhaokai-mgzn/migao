package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 套号载体：一个加工单 × 一套 = 一行（V92，切片 ⓪ / issue #4698；设计 §2.2）。
 *
 * <p><b>一套 = 一樘窗</b>（= 一个 {@code craftLineId} 组 / 一个窗的全部部位合计一套，用户裁定
 * 2026-09-20）—— 不是一条 {@code order_items} 行。{@code set_no} = {@code {加工单号}-{3 位 set_index}}，
 * **落库冗余**（码里印的是它，扫码解析按文本查唯一索引）。</p>
 *
 * <p>本实体只映射**读面用到的列**（切片 ① 消费面：套号 / 序号 / 归属校验）。
 * {@code position_item_ids}（JSONB 部位清单）与 {@code craft_line_id} 本切片**无消费者**
 * ⇒ 不映射（映射了也没有调用方，且要额外引入 JSONB typeHandler）—— 需要时再按迁移列补。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("processing_order_sets")
public class ProcessingOrderSet {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String processingOrderId;

    /** 一樘窗在本加工单里的次序（1 起，3 位零填充进 {@link #setNo}）；**只增不复用**。 */
    private Integer setIndex;

    /** 可读套号 = {@code {processing_order_no}-{pad3(set_index)}}。 */
    private String setNo;

    private Integer deleted;
}
