package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 行业生产种子模板目录项（issue #4361 交付物 2）。
 *
 * <p>对应 {@code GET /api/admin/production/seed-templates} 的列表项（契约冻结，前端包 #4363 按此消费）。
 * 形态照 {@link KnowledgeTemplateInfo}（知识库行业模板的既有范式）——同一类「平台预置模板」
 * 在两个域里长得一样，前端能复用同一套 tab/卡片交互。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ProductionSeedTemplateInfo {

    /** 模板 id（= 目录文件名，如 curtain）；apply 端点的路径参数 */
    private String templateId;

    /** 受控行业 code（curtain / other，见 {@code IndustryCodes}） */
    private String industry;

    /** 展示名 */
    private String name;

    /** 模板版本（内容变更时递增，供前端提示「模板已更新」） */
    private Integer version;

    /** 说明（含 provenance 提示：单价多为占位/推算值） */
    private String description;

    /** 模板内工序数 */
    private Integer operationCount;

    /** 模板内路线数 */
    private Integer routingCount;

    /** 模板内「特殊选项 → 条件工序」数 */
    private Integer optionCount;
}
