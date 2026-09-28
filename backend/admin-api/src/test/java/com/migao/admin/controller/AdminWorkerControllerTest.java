// case_ids: HR-002, HR-001
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.WorkerAdminService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import java.lang.reflect.Method;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人档案管理端点（issue #4869）：`POST/GET /api/admin/workers`。
 *
 * <p><b>为什么不改 `POST /api/admin/users`</b>：那条路径强制 phone 非空、会走岗位/权限快照与
 * `user_roles` 关联 —— 工人**不是员工**（无菜单权限、无登录用户名、不进后台），
 * 把它塞进员工语义只会污染两侧。本单新开一条**语义明确**的路径，权限码复用 `employee:create`
 * （不新增权限码：新增要迁移 + 全租户回填，属过度建设）。</p>
 *
 * <p><b>安全面</b>：本类断言新入口落在 `/api/admin/**` 面内且每个处理器都带 `@RequirePermission`
 * —— 即**同一道**既有门禁（`ADMIN_API_REJECTED_ROLES` 含 `worker`）覆盖它，不新造第二套判定。
 * 门禁级判据在 {@code AdminApiWorkerRoleGateTest} / {@code SecurityConfigTest}（worker 角色 ⇒ 403）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("AdminWorkerController（#4869）：建工人档案 / 列工人档案 / 权限注解")
class AdminWorkerControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private WorkerAdminService workerAdminService;

    @InjectMocks
    private AdminWorkerController adminWorkerController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(adminWorkerController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private static User worker(String id, String workerNo, String name) {
        return User.builder().id(id).tenantId(1L).workerNo(workerNo).nickname(name)
                .role("worker").status("active").createdAt(OffsetDateTime.now()).build();
    }

    @Test
    @DisplayName("建号：工号 + 姓名 + PIN ⇒ 200，且响应体**不含任何口令字段**")
    void createWorkerReturnsRedactedPayload() throws Exception {
        when(workerAdminService.createWorker("W-1001", "张三", "246810"))
                .thenReturn(worker("w-1", "W-1001", "张三"));

        mockMvc.perform(post("/api/admin/workers")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(
                                Map.of("workerNo", "W-1001", "name", "张三", "pin", "246810"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("w-1"))
                .andExpect(jsonPath("$.data.workerNo").value("W-1001"))
                .andExpect(jsonPath("$.data.name").value("张三"))
                .andExpect(jsonPath("$.data.role").value("worker"))
                .andExpect(jsonPath("$.data.passwordHash").doesNotExist())
                .andExpect(jsonPath("$.data.password").doesNotExist());

        verify(workerAdminService).createWorker("W-1001", "张三", "246810");
    }

    @Test
    @DisplayName("重复工号 ⇒ 409 + error.code=CONFLICT + 文案含工号（**不是 500**）")
    void duplicateWorkerNoReturnsConflictNotServerError() throws Exception {
        when(workerAdminService.createWorker(any(), any(), any()))
                .thenThrow(BusinessException.conflict("工号已被占用：W-1001（本企业内工号必须唯一）",
                        "换一个工号，或先在列表里找到这位工人并启用其档案"));

        mockMvc.perform(post("/api/admin/workers")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(
                                Map.of("workerNo", "W-1001", "name", "李四", "pin", "135791"))))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("CONFLICT"))
                .andExpect(jsonPath("$.error.message").value(org.hamcrest.Matchers.containsString("W-1001")));
    }

    @Test
    @DisplayName("字段缺失 ⇒ 422（服务端校验是唯一真值源，控制器不吞异常、不 500）")
    void missingFieldsReturnValidationError() throws Exception {
        when(workerAdminService.createWorker(any(), any(), any()))
                .thenThrow(BusinessException.validationError("工号不能为空"));

        mockMvc.perform(post("/api/admin/workers")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));
    }

    @Test
    @DisplayName("非字符串入参（如 workerNo 传数字）⇒ 422 而不是 500（不把 ClassCastException 抛给用户）")
    void nonStringFieldReturnsValidationError() throws Exception {
        when(workerAdminService.createWorker(any(), any(), any()))
                .thenThrow(BusinessException.validationError("工号不能为空"));

        mockMvc.perform(post("/api/admin/workers")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":1001,\"name\":\"张三\",\"pin\":\"246810\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));
    }

    @Test
    @DisplayName("列表 ⇒ 200 + items/total（工人档案独立列表，不混进员工列表）")
    void listWorkersReturnsPagedPayload() throws Exception {
        when(workerAdminService.listWorkers(anyLong(), anyLong(), any(), any()))
                .thenReturn(PageResponse.of(1L, 1L, 10L, List.of(worker("w-1", "W-1001", "张三"))));

        mockMvc.perform(get("/api/admin/workers").param("page", "1").param("size", "10"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.items[0].workerNo").value("W-1001"))
                .andExpect(jsonPath("$.data.items[0].name").value("张三"))
                .andExpect(jsonPath("$.data.items[0].passwordHash").doesNotExist());
    }

    @Test
    @DisplayName("新入口被同一道门禁覆盖：类级映射在 /api/admin/** 面内 + 每个处理器都带 @RequirePermission")
    void endpointsSitInsideTheGuardedAdminSurface() {
        RequestMapping classMapping = AdminWorkerController.class.getAnnotation(RequestMapping.class);
        assertThat(classMapping).isNotNull();
        assertThat(classMapping.value()).isNotEmpty();
        assertThat(classMapping.value())
                .as("必须落在 /api/admin/** 面内 —— 否则绕过既有门禁（ADMIN_API_REJECTED_ROLES 含 worker）")
                .allMatch(path -> path.startsWith("/api/admin/"));

        int handlers = 0;
        for (Method method : AdminWorkerController.class.getDeclaredMethods()) {
            boolean isHandler = method.isAnnotationPresent(GetMapping.class)
                    || method.isAnnotationPresent(PostMapping.class)
                    || method.isAnnotationPresent(PutMapping.class)
                    || method.isAnnotationPresent(DeleteMapping.class);
            if (!isHandler) {
                continue;
            }
            handlers++;
            RequirePermission permission = method.getAnnotation(RequirePermission.class);
            assertThat(permission)
                    .as("端点 " + method.getName() + " 必须声明 @RequirePermission（无注解 = 无细粒度闸门）")
                    .isNotNull();
            assertThat(permission.value())
                    .as("端点 " + method.getName() + " 的权限码不得为空")
                    .isNotBlank();
        }
        assertThat(handlers)
                .as("建号 + 列表两个端点是本单的交付面，缺一即红")
                .isEqualTo(2);
    }

    @Test
    @DisplayName("权限码复用既有员工域码（employee:create / employee:list），不新增权限码")
    void permissionCodesReuseEmployeeDomain() throws Exception {
        RequestMapping classMapping = AdminWorkerController.class.getAnnotation(RequestMapping.class);
        assertThat(classMapping.value()).contains("/api/admin/workers");

        Method create = AdminWorkerController.class.getDeclaredMethod("createWorker", Map.class);
        Method list = AdminWorkerController.class.getDeclaredMethod("listWorkers", long.class, long.class,
                String.class, String.class);
        assertThat(create.getAnnotation(RequirePermission.class).value()).isEqualTo("employee:create");
        assertThat(list.getAnnotation(RequirePermission.class).value()).isEqualTo("employee:list");
    }

}
