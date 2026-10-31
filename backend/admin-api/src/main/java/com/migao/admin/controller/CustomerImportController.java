package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.CustomerImportAnalysis;
import com.migao.admin.dto.CustomerImportReport;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.CustomerImportService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

/**
 * 客户主数据迁移工作台接口（issue #8295）。
 *
 * <p>三个动作：分析表头（AI 映射建议）→ 试运行（只读）→ 正式导入。
 * 全部要求 {@code customer:create}（预览也会接触客户 PII，不能给只读角色）。
 * 所有解析/校验/写入在服务端完成；AI 只给映射建议，不执行导入。</p>
 */
@Slf4j
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/customers/import")
public class CustomerImportController {

    private final CustomerImportService customerImportService;

    /** 上传任意表头 Excel，返回表头/样本/AI + 确定性映射建议；不写库。 */
    @PostMapping("/analyze")
    @RequirePermission("customer:create")
    public ApiResponse<CustomerImportAnalysis> analyze(@RequestParam("file") MultipartFile file) {
        CustomerImportAnalysis analysis = customerImportService.analyze(file);
        log.info("客户导入分析: headers={}, rows={}, suggestions={}, aiDegraded={}",
                analysis.getHeaders().size(), analysis.getTotalRows(),
                analysis.getSuggestions().size(), analysis.isAiDegraded());
        return ApiResponse.success(analysis);
    }

    /** 试运行：只读校验，绝不写客户档案。 */
    @PostMapping("/preview")
    @RequirePermission("customer:create")
    public ApiResponse<CustomerImportReport> preview(
            @RequestParam("file") MultipartFile file,
            @RequestParam("mapping") String mapping,
            @RequestParam(value = "updateExisting", defaultValue = "false") boolean updateExisting) {
        CustomerImportReport report = customerImportService.preview(file, mapping, updateExisting);
        log.info("客户导入试运行: total={}, new={}, update={}, skip={}, error={}",
                report.getTotal(), report.getNewCount(), report.getUpdateCount(),
                report.getSkipCount(), report.getErrorCount());
        return ApiResponse.success(report);
    }

    /** 正式导入：逐行 create/update/skip，externalId 幂等。 */
    @PostMapping("/commit")
    @RequirePermission("customer:create")
    public ApiResponse<CustomerImportReport> commit(
            @RequestParam("file") MultipartFile file,
            @RequestParam("mapping") String mapping,
            @RequestParam(value = "updateExisting", defaultValue = "false") boolean updateExisting) {
        CustomerImportReport report = customerImportService.commit(file, mapping, updateExisting);
        log.info("客户导入提交: total={}, created={}, updated={}, skipped={}, failed={}",
                report.getTotal(), report.getCreatedCount(), report.getUpdatedCount(),
                report.getSkippedCount(), report.getFailedCount());
        return ApiResponse.success(report);
    }
}
