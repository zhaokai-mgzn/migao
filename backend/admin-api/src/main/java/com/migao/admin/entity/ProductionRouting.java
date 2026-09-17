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

import java.time.OffsetDateTime;

/**
 * 工艺路线模板（issue #3995，M4-G-2）
 * 对应表：production_routings（V49）。部位 × 工艺 → 基准工序序列。
 * 与 ai-agent-service app/production/routing.py 的 ROUTINGS 同构（M4-G-1）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_routings", autoResultMap = true)
public class ProductionRouting {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 部位/帘种：布帘/纱帘/帘头 */
    private String curtainType;

    /** 工艺：韩褶/打孔/四爪钩/穿杆/平幔 */
    private String craft;

    /** 工序名有序序列（JSONB 数组） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object operations;

    /** active / disabled */
    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
