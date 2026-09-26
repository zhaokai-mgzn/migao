package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.User;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.WorkerAdminService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 工人档案管理（issue #4869）：`POST /api/admin/workers`（建号）+ `GET /api/admin/workers`（列表）。
 *
 * <p><b>为什么新开一条路径而不是改 {@code POST /api/admin/users}</b>：员工创建路径强制 phone 非空、
 * 会走岗位解析与权限快照、并关联 {@code user_roles} —— 那是**员工**语义。工人不是员工
 * （零菜单权限、无登录用户名、不进管理后台），塞进去只会让两边都失真；新路径把语义写清楚，
 * 既有员工路径**一字未动**。</p>
 *
 * <p><b>权限码复用员工域（{@code employee:create} / {@code employee:list}）</b>，不新增权限码：
 * 新增一个 {@code worker:create} 要走迁移 + 全租户回填岗位默认权限（否则已注册租户的管理员
 * 全部变 403），而工人在产品上就是「人事管理」的一部分 ⇒ 复用是正确取舍，不是省事。</p>
 *
 * <p><b>安全面（不新造第二套判定）</b>：本控制器落在 {@code /api/admin/**} 面内 ⇒ 与员工管理
 * 走**同一道**门禁 —— {@code SecurityConfig.adminApiAuthorizationManager()} 的
 * {@code ADMIN_API_REJECTED_ROLES}（{@code customer} / {@code agent} / <b>{@code worker}</b>）
 * 对工人身份一律拒绝；细粒度由方法级 {@code @RequirePermission} 承担。
 * 判据 = {@code AdminWorkerControllerTest#endpointsSitInsideTheGuardedAdminSurface} +
 * {@code AdminApiWorkerRoleGateTest} + {@code SecurityConfigTest#authorization_workerRole_cannotAccessWorkerEndpoints}。</p>
 *
 * <p><b>停用／启用不另造端点</b>：复用既有 {@code PUT /api/admin/users/{id}/status}
 * （前端 {@code workerApi.setWorkerStatus} 调的就是它）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/workers")
@RequiredArgsConstructor
public class AdminWorkerController {

    private final WorkerAdminService workerAdminService;

    /**
     * 列工人档案（与员工列表分开，工人不会混进员工列表）。
     *
     * <p>GET {@code /api/admin/workers?page=1&size=10&keyword=W-1001&status=active}；权限：{@code employee:list}</p>
     */
    @GetMapping
    @RequirePermission("employee:list")
    public ApiResponse<PageResponse<Map<String, Object>>> listWorkers(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String status) {
        PageResponse<User> result = workerAdminService.listWorkers(page, size, keyword, status);
        List<Map<String, Object>> items = result.getItems().stream()
                .map(AdminWorkerController::toWorkerView)
                .collect(Collectors.toList());
        return ApiResponse.success(PageResponse.of(result.getTotal(), result.getPage(), result.getSize(), items));
    }

    /**
     * 建工人档案：Body {@code {"workerNo":"W-1001","name":"张三","pin":"246810"}}。
     *
     * <p>权限：{@code employee:create}。工号租户内唯一，冲突 ⇒ 409 + 明确文案（不是 500）；
     * PIN 由服务端 BCrypt 编码后落 {@code users.password_hash}，与工人登录侧同一套比对。</p>
     */
    @PostMapping
    @RequirePermission("employee:create")
    public ApiResponse<Map<String, Object>> createWorker(@RequestBody Map<String, Object> body) {
        User worker = workerAdminService.createWorker(
                text(body, "workerNo"), text(body, "name"), text(body, "pin"));
        return ApiResponse.success(toWorkerView(worker));
    }

    /**
     * 读一个字符串字段：非字符串（如把工号写成数字）当**缺失**处理
     * ⇒ 由服务端给 422 的明确文案，而不是把 {@code ClassCastException} 抛成 500。
     */
    private static String text(Map<String, Object> body, String key) {
        Object value = body == null ? null : body.get(key);
        return value instanceof String s ? s : null;
    }

    /** 档案视图：**绝不**包含 passwordHash / PIN（响应里没有任何口令字段）。 */
    private static Map<String, Object> toWorkerView(User worker) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", worker.getId());
        view.put("workerNo", worker.getWorkerNo());
        view.put("name", worker.getNickname());
        view.put("role", worker.getRole());
        view.put("status", worker.getStatus());
        view.put("createdAt", worker.getCreatedAt() == null ? null : worker.getCreatedAt().toString());
        return view;
    }
}
