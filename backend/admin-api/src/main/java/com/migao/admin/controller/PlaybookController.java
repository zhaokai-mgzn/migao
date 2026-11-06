package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Playbook;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.PlaybookService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 口径卡控制器（issue #8175 一期：落卡 → 审核 → 退役）。
 *
 * <ul>
 *   <li>{@code GET  /api/admin/playbooks?state=} → 列表（默认 draft = 待审核队列）</li>
 *   <li>{@code POST /api/admin/playbooks} → 落卡（**只会落成 draft**）</li>
 *   <li>{@code POST /api/admin/playbooks/{id}/activate} → 审核通过（draft → active）</li>
 *   <li>{@code POST /api/admin/playbooks/{id}/retire} → 退役（active → retired，立即生效）</li>
 * </ul>
 *
 * <p><b>权限码为什么复用 {@code knowledge:view} / {@code knowledge:manage}</b>：口径卡是知识面的
 * 同族工件（都是「AI 只产生候选、发布权在商家」），且 Issue 的 P1 口径就是「复用现有
 * knowledge 审核闭环，不新建管道」。新增一个 {@code playbook:*} 码的代价是**没有任何岗位持有它**
 * ⇒ 接口对所有人 403（= 字段存在但功能不可达），还要同批改 RBAC 单一真值源、
 * 目录名称列、角色矩阵与生成物。**重启条件**：当需要「口径审核」与「知识审核」分权
 * （例如只允许店长审核口径）时，另开一单把码拆出来并同批补角色授权迁移。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/playbooks")
@RequiredArgsConstructor
public class PlaybookController {

    private final PlaybookService playbookService;

    /** 列表：**读**面 ⇒ 用读码（写码只留给三个 POST）。 */
    @GetMapping
    @RequirePermission("knowledge:view")
    public ApiResponse<PageResponse<Playbook>> page(
            @RequestParam(required = false) String state,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResponse.success(playbookService.page(state, page, size));
    }

    /** 落卡（只落 draft —— 审核是另一个入口，不可通过参数绕过）。 */
    @PostMapping
    @RequirePermission("knowledge:manage")
    public ApiResponse<Playbook> create(@RequestBody Playbook body) {
        return ApiResponse.success(playbookService.createDraft(body));
    }

    /**
     * 审核通过：draft → active（此后才进 prompt / 才能生成用例）。
     *
     * <p>同冲突组已有生效卡 ⇒ **默认 409**；`supersedes` = 要替换掉的旧卡，走
     * 「同一事务内先退役旧的、再激活新的」路径（issue #8175 P2）。</p>
     */
    @PostMapping("/{id}/activate")
    @RequirePermission("knowledge:manage")
    public ApiResponse<Playbook> activate(
            @PathVariable String id,
            @RequestParam(required = false) String supersedes) {
        return ApiResponse.success(playbookService.activate(id, supersedes));
    }

    /** 退役：active → retired（**立即**从所有出口消失，读面不缓存）。 */
    @PostMapping("/{id}/retire")
    @RequirePermission("knowledge:manage")
    public ApiResponse<Playbook> retire(@PathVariable String id) {
        return ApiResponse.success(playbookService.retire(id));
    }
}
