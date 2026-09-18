package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 特殊选项 → 条件工序（issue #4230，v1a）
 * 对应表：production_option_routings（V59）。
 *
 * <p>实例化加工单时：订单携带的每个 specialOption 若在此表有行，就把 {@code operationName}
 * 插到 {@code afterOperation} 之后（锚点不在该部位路线中 ⇒ 追加到末尾，与真值源
 * {@code routing.py::_insert_after} 同款）。</p>
 *
 * <p>与 ai-agent {@code app/production/routing.py} 的 {@code SPECIAL_OPTION_ROUTINGS} 同构
 * （真值源唯一，本表是其 DB 化落点；防漂移由
 * {@code ProductionOptionRoutingMigrationTest} 逐行比对守）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_option_routings", autoResultMap = true)
public class ProductionOptionRouting {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 特殊选项名（真值源 §1 的 19 项之一，如「拼1次」） */
    private String optionName;

    /** 条件工序名（production_operations.name，如「拼1次-布」） */
    private String operationName;

    /** 锚点工序名（插在它之后；不在路线中 ⇒ 追加到末尾） */
    private String afterOperation;

    private Integer sortOrder;

    /** active / disabled */
    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
