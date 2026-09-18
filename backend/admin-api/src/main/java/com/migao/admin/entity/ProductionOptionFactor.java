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
 * 特殊选项 → 计件系数（issue #4230，v1a）
 * 对应表：production_option_factors（V59）。
 *
 * <p>系数最终落进 {@code processing_position_operations.factor}，由计件公式
 * （{@code ProductionService.aggregate}：Σ 合格数量 × 单价 × 系数）真的乘进钱 ——
 * 该列自 V49 就存在、公式也真的读它，但**此前零写方** ⇒ 恒 1.00（「少发工人钱」的完整根因链）。</p>
 *
 * <p>{@code operationName} 为空 = 该部位**全部**工序（平摊档）；非空 = 逐工序例外档
 * （例外档盖住平摊档，与真值源 {@code routing.py::factor_for} 的「后档覆盖前档」同口径）。
 * v1 只种平摊档（「一分为二 ⇒ ×1.7」，唯一的**实证**值）—— 逐工序细算档是纯推算，
 * 不拿推算值覆盖实证值（issue #4230 §2.4）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_option_factors", autoResultMap = true)
public class ProductionOptionFactor {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 特殊选项名（如「一分为二」；ERP 名 = join key，issue #4389） */
    private String optionName;

    /** 限定工序名；NULL = 该部位全部工序（平摊档） */
    private String operationName;

    /** 计件系数（乘在工序实例 factor 上） */
    private BigDecimal factor;

    /** 口径来源标注：实证 / 推算（真值源 §4 的标注口径） */
    private String source;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
