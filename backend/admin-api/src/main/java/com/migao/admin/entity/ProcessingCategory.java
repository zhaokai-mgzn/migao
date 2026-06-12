package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 加工分类实体类
 * 对应表：processing_categories
 * 说明：窗帘加工、窗帘配件、纱窗加工、卷帘加工等分类
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("processing_categories")
public class ProcessingCategory {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String name;

    private Integer sortOrder;

    private String status;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
