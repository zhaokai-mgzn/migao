package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.User;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.TenantOwnedResource;
import com.migao.admin.service.ProductionOperationQueryService;
import com.migao.admin.service.WorkerAdminService;
import com.migao.admin.worker.WorkerPages;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
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
     * 逻辑工序目录（issue #7749）：工人档案「绑定工序」下拉的**唯一**选项来源。
     *
     * <p>🔴 为什么不在前端直接读 {@code /api/admin/production/operations-catalog}：那个端点挂
     * {@code production:view}（生产域读码），而工人档案在人事域（{@code employee:list}）——
     * 让「能管工人档案、不能看生产配置」的岗位点开下拉却 403，等于把功能按权限腰斩。
     * 这里只回**逻辑工序名 + 分组**（不含单价/矩阵），与写侧校验（`hasLogicalOperation`）同一份口径。</p>
     */
    private final ProductionOperationQueryService productionOperationQueryService;

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
     * 可绑定的**逻辑工序**目录（issue #7749）：{@code {total, operations:[{name, group, variants}]}}。
     *
     * <p>权限：{@code employee:list}（与工人列表同码 —— 这是档案面板的选项来源，不是生产配置读面）。
     * 只含活跃工序；同一道活在库里按部位拆成的多行（{@code 韩褶-布} / {@code 韩褶-纱}）归并成
     * 一个逻辑名（用户 2026-10-25 选定的粒度）。</p>
     */
    @GetMapping("/operations")
    @RequirePermission("employee:list")
    public ApiResponse<Map<String, Object>> listWorkerOperations() {
        return ApiResponse.success(
                productionOperationQueryService.logicalOperations(TenantContext.getTenantId()));
    }

    /**
     * 建工人档案：Body {@code {"workerNo":"W-1001","name":"张三","pin":"246810",
     * "workerOperation":"韩褶"}}。
     *
     * <p>权限：{@code employee:create}。工号租户内唯一，冲突 ⇒ 409 + 明确文案（不是 500）；
     * PIN 由服务端 BCrypt 编码后落 {@code users.password_hash}，与工人登录侧同一套比对。
     * {@code workerOperation} 可省 ⇒ 不绑定（= 扫码后自己选工序的旧行为）；填了但不在本租户工序库
     * ⇒ 422 + 可行动出口。</p>
     */
    @PostMapping
    @RequirePermission("employee:create")
    public ApiResponse<Map<String, Object>> createWorker(@RequestBody Map<String, Object> body) {
        User worker = workerAdminService.createWorker(
                text(body, "workerNo"), text(body, "name"), text(body, "pin"),
                body == null ? null : body.get("workerPages"),
                text(body, "workerOperation"));
        return ApiResponse.success(toWorkerView(worker));
    }

    /**
     * 设/清这位工人**绑定的工序**（issue #7749）：Body {@code {"workerOperation":"韩褶"}}。
     *
     * <p>{@code workerOperation} 可省 / 为 {@code null} / 空白 ⇒ <b>清空绑定</b>（= 回到
     * 「系统推断 + 工序选择器」的旧行为）。非法工序名 ⇒ 422 + 可行动出口，零写入。
     * 权限：{@code employee:create}（与建号／页面收窄同档写权限）。</p>
     */
    @PutMapping("/{id}/operation")
    @RequirePermission("employee:create")
    @TenantOwnedResource("worker")
    public ApiResponse<Map<String, Object>> updateWorkerOperation(@PathVariable String id,
                                                                  @RequestBody(required = false) Map<String, Object> body) {
        User worker = workerAdminService.updateWorkerOperation(
                id, body == null ? null : text(body, "workerOperation"));
        return ApiResponse.success(toWorkerView(worker));
    }

    /**
     * 设工人**工人端页面收窄**（issue #6788，用户 2026-10-13 裁定）：Body {@code {"workerPages":["report","cut_calc"]}}。
     *
     * <p>{@code workerPages} 可省 / 为 {@code null} ⇒ <b>清回收窄</b>（= 不限制，看全部页面）。
     * 权限：{@code employee:create}（与建号／重置 PIN 同档写权限）。
     * 未知页面键 / 非数组 / 重复键 ⇒ 422 + 逐条理由（{@code error.details}），**不静默忽略**。</p>
     */
    @PutMapping("/{id}/pages")
    @RequirePermission("employee:create")
    @TenantOwnedResource("worker")
    public ApiResponse<Map<String, Object>> updateWorkerPages(@PathVariable String id,
                                                              @RequestBody(required = false) Map<String, Object> body) {
        User worker = workerAdminService.updateWorkerPages(id, body == null ? null : body.get("workerPages"));
        return ApiResponse.success(toWorkerView(worker));
    }

    /**
     * 重置工人 PIN：Body {@code {"pin":"246810"}}；<b>pin 可省</b>（服务端随机生成 6 位）。
     *
     * <p>权限：{@code employee:create}（与建号同档写权限）。响应体**只含新 PIN 明文**（唯一一次下发面），
     * 库里仍是 BCrypt 哈希 —— 原 PIN 读不出来（不可逆），所以出口是「重置 + 展示新值」而不是「查看」。</p>
     */
    @PutMapping("/{id}/pin")
    @RequirePermission("employee:create")
    @TenantOwnedResource("worker")
    public ApiResponse<Map<String, Object>> resetPin(@PathVariable String id,
                                                     @RequestBody(required = false) Map<String, Object> body) {
        String newPin = workerAdminService.resetPin(id, text(body, "pin"));
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("pin", newPin);
        return ApiResponse.success(data);
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
        // 工人端页面收窄（issue #6788）：null = 未收窄（不限制）⇒ 前端据此显示「全部」。
        // 库里存的是**原样 JSON 文本**（见 User#workerPages 的「为什么不用 JacksonTypeHandler」），
        // 归一后按数组下发（脏值 ⇒ null = 未收窄，与读侧 fail-open 同口径）。
        Set<String> restricted = WorkerPages.normalizeStored(worker.getWorkerPages());
        view.put("workerPages", restricted == null ? null : List.copyOf(restricted));
        // 绑定的逻辑工序（issue #7749 / #7766）：null = 不设工序（出入库/仓库等岗位）⇒ 前端显示「不设工序」。
        view.put("workerOperation", worker.getWorkerOperation());
        view.put("createdAt", worker.getCreatedAt() == null ? null : worker.getCreatedAt().toString());
        return view;
    }
}
