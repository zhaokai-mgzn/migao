package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.worker.WorkerPages;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 工人端**页面目录**只读端点（issue #6828）：{@code GET /api/admin/worker-pages}。
 *
 * <h3>它回答什么</h3>
 * <p>「工人端一共有哪几个页面、各自叫什么」—— 商家面配置工人**逐人菜单**时的**选项来源**。</p>
 *
 * <h3>为什么要有这个端点（而不是让前端自己写一份页名）</h3>
 * <p>企业级页面开关（{@code GET/PUT /api/admin/worker-page-config}）随整层移除（issue #6828），
 * 而旧代码里「可选页 + 人话名」正是从它的读面借的
 * （{@code frontend/admin-web/src/components/employees/WorkerProfilesPanel.tsx}）。
 * 若让前端自己维护这 4 个键与中文名，就是**第二份会漂的真值**（#6788 验收标准 6 明禁）
 * ⇒ 目录仍由服务端给，且直接取自 {@link WorkerPages} 这一处闭词表。</p>
 *
 * <h3>权限</h3>
 * <p>读面挂生产域**读码** {@code production:view}（与工人档案读面同码）。本面**只读** ——
 * 页面的开放范围由每位工人档案上的收窄决定（{@code PUT /api/admin/workers/{id}/pages}）。</p>
 *
 * <p>🔴 本控制器不签发任何权限、不参与授权判定：工人 session 的 {@code permissions} 恒为 {@code []}。</p>
 */
@RestController
@RequestMapping("/api/admin/worker-pages")
@RequiredArgsConstructor
@RequirePermission("production:view")
public class WorkerPageCatalogController {

    /** 全部工人端页面键 + 商家面人话名（{@code data = {pages, labels}}）。 */
    @GetMapping
    public ApiResponse<Map<String, Object>> catalog() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("pages", WorkerPages.defaultPages());
        data.put("labels", WorkerPages.labels());
        return ApiResponse.success(data);
    }
}
