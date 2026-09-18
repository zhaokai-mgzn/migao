package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.ProductionSeedTemplateInfo;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ProductionSeedTemplateService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 行业生产种子模板控制器（issue #4361 交付物 2；收口 #4316）。
 *
 * <p><b>契约冻结</b>（前端包 #4363 按此消费，<b>不得改名</b>）：</p>
 * <ul>
 *   <li>{@code GET  /api/admin/production/seed-templates} → {@code [{templateId, industry, name, version, description}]}</li>
 *   <li>{@code POST /api/admin/production/seed-templates/{templateId}/apply}
 *       → {@code {created_operations, created_routings, skipped}}</li>
 * </ul>
 *
 * <p>权限统一 {@code processing:manage}（写面 —— 套用会**真的落库**工序/路线/单价）。
 * 与知识库行业模板（{@code KnowledgeTemplateController}，{@code knowledge:manage}）
 * 的差异只在权限点，形态逐条对齐（同一类「平台预置模板 → 复制为租户资产」）。</p>
 *
 * <p><b>为什么写面要单独一个 Controller 而不是塞进 {@code ProductionController}</b>：
 * 后者类级权限是 {@code order:list}（读口径，授了 4 个岗位），本端点需要 {@code processing:manage}
 * （只授 operator）。塞进去会让「套用种子」这个**不可逆的批量写**落到读权限岗位手上
 * （同 {@code ProductionController} 里打印计数沿用类级权限的那个例外正好相反 ——
 * 那是只读元数据，这是批量写）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/production/seed-templates")
@RequiredArgsConstructor
@RequirePermission("processing:manage")
public class ProductionSeedTemplateController {

    private final ProductionSeedTemplateService productionSeedTemplateService;

    /** 平台预置生产种子模板目录。 */
    @GetMapping
    public ApiResponse<List<ProductionSeedTemplateInfo>> list() {
        return ApiResponse.success(productionSeedTemplateService.listTemplates());
    }

    /**
     * 一键套用模板到当前租户（幂等：重复套用不产生第二份）。
     *
     * <p>存量租户补套入口（#4316 的补救路径）：非 1 号租户工序库/路线库为空、建单 fail-closed（422）
     * ⇒ 商家/运营在这里一键补齐，不必等研发改迁移常量。</p>
     */
    @PostMapping("/{templateId}/apply")
    public ApiResponse<Map<String, Object>> apply(@PathVariable String templateId) {
        Long tenantId = TenantContext.getTenantId();
        // 先按 id 校验存在性（未知 ⇒ 404），再按**行业**套用 —— 套用逻辑只有一份
        // （applyTemplate(tenantId, industry)），避免「按 id」与「按行业」两条路径各写一套。
        String industry = productionSeedTemplateService.industryOfTemplate(templateId);
        return ApiResponse.success(productionSeedTemplateService.applyTemplate(tenantId, industry));
    }
}
