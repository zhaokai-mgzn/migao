package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 供应商主数据（issue #7369，P0-1 段 1）。
 *
 * <p>对应表 {@code suppliers}（V170）。一行 = 一家供应商。
 * <p>⚠️ 与入库单上的 {@code supplier} 文本列**不是**同一件东西：那是单据快照，这是档案
 * （可改名、可停用、被多张单据引用）。单据侧引用 {@code supplier_id} 由段 2 落地。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("suppliers")
public class Supplier {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 供应商名称（唯一可识别口径；同一家不许录成三种写法） */
    private String name;

    private String contactName;

    private String contactPhone;

    /** 账期天数：null = 未设置；0 = 现结；正数 = 账期（0~365） */
    private Integer paymentTermsDays;

    /** active 在用 / inactive 停用（停用后不可被新单据选中，由段 2 在写面拦） */
    private String status;

    private String remark;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Boolean deleted;
}
