// case_ids: PG-045
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.service.ProductionScanCompleteService;
import com.migao.admin.service.ProductionScanService;
import com.migao.admin.service.ProductionService;
import com.migao.admin.service.WorkerCuttingHeightService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import java.io.IOException;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 一体机裁高端点（{@code GET /api/worker/production/cutting-height}，母单 #5161）的**HTTP 层**契约 +
 * 「不写机器」的**结构守卫**。
 *
 * <p>四条判据（每条都能红）：</p>
 * <ol>
 *   <li><b>无工人 session ⇒ 401 且不进服务层</b>（工人路径上「谁」没有第二条来源，不降级）；</li>
 *   <li><b>有 session ⇒ 200</b>，服务被调用的实参 = (扫码内容, **服务端**判定的租户) —— 前端伪造不了；</li>
 *   <li>🔴 <b>本包任何路径都不写机器</b>：控制器/服务源码里没有串口 / Modbus / 寄存器 / 蓝牙写面
 *       （用户 2026-09-29 裁定①「下发先不做」）；红证：在服务里加一行 {@code SerialPort} ⇒ 红；</li>
 *   <li>🔴 <b>该端点只有 GET</b>（只读面）＋ <b>工人面零商家权限码</b>（{@code permissions=[]} 的工人
 *       加 {@code @RequirePermission} 只会恒 403）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("一体机裁高端点契约 + 不写机器守卫（母单 #5161）")
class WorkerProductionCuttingHeightTest {

    private static final Long TENANT = 1L;
    private static final String TOKEN = "7K3M9QP2";
    private static final String PATH = "/api/worker/production/cutting-height";

    private static final String CONTROLLER_SRC =
            "com/migao/admin/controller/WorkerProductionController.java";
    private static final String SERVICE_SRC =
            "com/migao/admin/service/WorkerCuttingHeightService.java";

    /** 🔴 机器写面的词表（源码里出现任一 ⇒ 说明「不写机器」这条被破坏）。 */
    private static final List<String> MACHINE_WRITE_TOKENS = List.of(
            "serialport", "jserialcomm", "gnu.io", "javax.comm", "modbus",
            "navigator.serial", "bluetooth", "writeblecharacteristic", "registervalue");

    @Mock
    private ProductionService productionService;
    @Mock
    private WorkerSessionService workerSessionService;
    @Mock
    private ProductionScanService productionScanService;
    @Mock
    private ProductionScanCompleteService productionScanCompleteService;
    @Mock
    private WorkerCuttingHeightService workerCuttingHeightService;

    private MockMvc mockMvc;

    private static final WorkerIdentity ZHANG =
            new WorkerIdentity("worker-zhang", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, "sess-1");

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        WorkerProductionController controller = new WorkerProductionController(productionService,
                workerSessionService, productionScanService, productionScanCompleteService,
                workerCuttingHeightService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("🔴 无工人 session ⇒ 401，且**不进服务层**（不降级到匿名/商家口径）")
    void withoutWorkerSessionRejected() throws Exception {
        when(workerSessionService.resolveIdentity(any())).thenReturn(null);

        mockMvc.perform(get(PATH).param("token", TOKEN))
                .andExpect(status().isUnauthorized());

        verify(workerCuttingHeightService, never()).read(any(), any());
    }

    @Test
    @DisplayName("有工人 session ⇒ 200；服务被调用的实参 = (扫码内容, 服务端判定的租户)")
    void withWorkerSessionReturnsOneScreen() throws Exception {
        when(workerSessionService.resolveIdentity("sess-1")).thenReturn(ZHANG);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("granularity", "set_position");
        data.put("positions", List.of(Map.of("position_kind", "布帘", "cutting_height", 3.028)));
        when(workerCuttingHeightService.read(TOKEN, TENANT)).thenReturn(data);

        mockMvc.perform(get(PATH).param("token", TOKEN)
                        .header(WorkerSessionService.SESSION_HEADER, "sess-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.granularity").value("set_position"))
                .andExpect(jsonPath("$.data.positions[0].cutting_height").value(3.028));

        verify(workerCuttingHeightService).read(eq(TOKEN), eq(TENANT));
    }

    @Test
    @DisplayName("🔴 不写机器：控制器/服务源码里**没有**串口 / Modbus / 寄存器 / 蓝牙写面")
    void noMachineWriteSurfaceAnywhere() throws IOException {
        for (String source : List.of(sourceOf(CONTROLLER_SRC), sourceOf(SERVICE_SRC))) {
            String lowered = source.toLowerCase(Locale.ROOT);
            for (String token : MACHINE_WRITE_TOKENS) {
                assertThat(lowered)
                        .as("「下发先不做」（用户 2026-09-29 裁定①）：出现 %s ⇒ 本包越界", token)
                        .doesNotContain(token);
            }
        }
        // 正向对照：守卫不能空转 —— 目标源码确实被读到了（读到空串/读错文件时上面恒绿）
        assertThat(sourceOf(SERVICE_SRC)).contains("WorkerCuttingHeightService");
        assertThat(sourceOf(CONTROLLER_SRC)).contains("/cutting-height");
    }

    @Test
    @DisplayName("🔴 该端点只有 GET（只读）；工人面**零商家权限码**")
    void endpointIsReadOnlyAndCarriesNoMerchantPermission() throws Exception {
        List<String> paths = new ArrayList<>();
        for (Method method : WorkerProductionController.class.getDeclaredMethods()) {
            GetMapping mapping = method.getAnnotation(GetMapping.class);
            if (mapping == null) {
                continue;
            }
            for (String value : mapping.value()) {
                if (value.contains("cutting-height")) {
                    paths.add(value);
                }
            }
        }
        assertThat(paths).as("裁高读面必须是 GET（只读）").containsExactly("/cutting-height");
        // 写动词映射一个都不许指向这个面（只读 = 结构判据，不靠约定）；
        // 正向对照：写动词映射集**非空** —— 否则下面那条是空断言（本控制器确有 POST）
        List<String> writePaths = new ArrayList<>();
        for (Method method : WorkerProductionController.class.getDeclaredMethods()) {
            writePaths.addAll(writeMappingValues(method));
        }
        assertThat(writePaths).as("守卫非空转：本控制器的写动词映射确实被枚举到").isNotEmpty();
        assertThat(writePaths).noneMatch(value -> value.contains("cutting-height"));
        assertThat(sourceOf(CONTROLLER_SRC))
                .as("工人面（permissions=[]）加 @RequirePermission 只会恒 403；准入 = 有效工人 session")
                .doesNotContain("@RequirePermission");
    }

    /** 写动词映射的路径（四种注解各自解析 —— 它们**不是** {@code RequestMapping} 的子类型，不能统一转型）。 */
    private static List<String> writeMappingValues(Method method) {
        List<String> out = new ArrayList<>();
        PostMapping post = method.getAnnotation(PostMapping.class);
        if (post != null) {
            out.addAll(List.of(post.value()));
        }
        PutMapping put = method.getAnnotation(PutMapping.class);
        if (put != null) {
            out.addAll(List.of(put.value()));
        }
        DeleteMapping delete = method.getAnnotation(DeleteMapping.class);
        if (delete != null) {
            out.addAll(List.of(delete.value()));
        }
        PatchMapping patch = method.getAnnotation(PatchMapping.class);
        if (patch != null) {
            out.addAll(List.of(patch.value()));
        }
        return out;
    }

    /**
     * 读源文件：两种工作目录都试（Maven 模块目录 / 仓库根），与
     * {@code WorkerInboundSurfaceGuardTest#sourceOf} 同款——行号不进判据，符号才是锚点。
     */
    private static String sourceOf(String relative) throws IOException {
        for (Path base : List.of(Path.of("src/main/java"), Path.of("backend/admin-api/src/main/java"))) {
            Path path = base.resolve(relative);
            if (Files.exists(path)) {
                return stripComments(Files.readString(path));
            }
        }
        throw new IOException("读不到源文件（两种工作目录都试过）: " + relative);
    }

    /** 剥注释：词表守卫只该管**代码**，否则本类的说明性注释（提到 Modbus 这类词）自己会把判据点红。 */
    private static String stripComments(String source) {
        String noBlock = source.replaceAll("(?s)/\\*.*?\\*/", " ");
        return noBlock.replaceAll("(?m)//.*$", " ");
    }
}
