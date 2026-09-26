// case_ids: PR-110, PR-111, PR-112
package com.migao.admin.controller;

import com.migao.admin.dto.WorkerInboundDraftRequest;
import com.migao.admin.dto.WorkerInboundPostRequest;
import com.migao.admin.dto.WorkerInboundRecognizeRequest;
import com.migao.admin.security.SecurityConfig;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 工人入库面的**结构守卫**（issue #5052 P1）—— 让「三条硬约束」进不来第二形态。
 *
 * <p>为什么必须是结构判据而不是运行时校验（用户裁定，设计 §5.3 硬约束 1）：
 * 「只表达入库语义」如果靠 {@code if (adjustment != null) reject}，那第二个人加一条旁路、
 * 或者某天有人「顺手支持一下手工调整」，判据就悄悄失效了。<b>字段集就是能力集</b> ——
 * 请求体里没有那个键，能力就不存在。</p>
 *
 * <h3>本类钉住的六件事（逐条可红）</h3>
 * <ol>
 *   <li><b>请求 DTO 字段集 == 允许集</b>（多一个字段就红 ⇒ 设计 §11.2 N5「结构上不可表达任意调整」）；</li>
 *   <li><b>零商家权限码</b>：控制器/服务源码里没有 {@code @RequirePermission} /
 *       {@code PermissionInterceptor} / 任何商家码（设计 §9.3 红线）；</li>
 *   <li><b>不复用商家识别端点</b>：不引用 {@code ImageRecognitionController} /
 *       {@code TARGET_PERMISSIONS}（设计 §11.2 N3 / N4）；</li>
 *   <li><b>不新造库存增减</b>：源码里没有库存/台账写方法（设计 §5.3 硬约束 2 / §11.2 N10）；</li>
 *   <li><b>路径只在 {@code /api/worker/**}</b>，且 P1 只有三个端点（P2~P5 不得顺手落进来）；</li>
 *   <li><b>工人角色仍在 {@code /api/admin/**} 的拒绝集合里</b>（零商家权限的机制底座，
 *       设计 §11.1 第 1 条；机制本体见 {@code AdminApiWorkerRoleGateTest}，本类只钉「它还在」）。</li>
 * </ol>
 */
@DisplayName("工人入库面结构守卫（#5052 P1）：字段集即能力集 / 零商家权限 / 不新造库存")
class WorkerInboundSurfaceGuardTest {

    private static final String CONTROLLER_SRC =
            "com/migao/admin/controller/WorkerInboundController.java";
    private static final String SERVICE_SRC =
            "com/migao/admin/service/WorkerInboundService.java";

    // ============================================================ ① 字段集即能力集

    @Test
    @DisplayName("🔴 三个请求 DTO 的字段集 == 允许集（多一个键 ⇒ 红）")
    void requestDtosDeclareExactlyTheAllowedFieldSet() {
        assertThat(fieldNames(WorkerInboundRecognizeRequest.class))
                .containsExactlyInAnyOrder("images", "barcode");
        assertThat(fieldNames(WorkerInboundDraftRequest.class))
                .containsExactlyInAnyOrder("productId", "skuId", "quantity", "unitCost", "dyeLot",
                        "supplier", "supplierDocNo", "warehouse", "rollLengthM", "remark");
        assertThat(fieldNames(WorkerInboundPostRequest.class))
                .containsExactlyInAnyOrder("confirmed");
    }

    @Test
    @DisplayName("🔴 结构上不可表达「任意调整」：adjustment / delta / setStock / stock / reason / operator 一个都进不来")
    void adjustmentShapedKeysCannotBeExpressedAtAll() {
        Set<String> declared = new LinkedHashSet<>();
        declared.addAll(fieldNames(WorkerInboundRecognizeRequest.class));
        declared.addAll(fieldNames(WorkerInboundDraftRequest.class));
        declared.addAll(fieldNames(WorkerInboundPostRequest.class));

        // 判据 = DTO 字段集（不是运行时校验）：这些键「被拒绝」不够，必须是「根本没有」
        assertThat(declared).doesNotContain("adjustment", "delta", "setStock", "stock", "stockDelta",
                "reason", "operator", "workerId", "tenantId", "targetType", "source", "importRunId",
                "confirmedQuantity", "override");
    }

    @Test
    @DisplayName("三个端点的路径面 == P1 的 3 个（标签位图 / 打印计数属 P2，不得顺手落进来）")
    void onlyTheThreeP1EndpointsExist() {
        Set<String> paths = new LinkedHashSet<>();
        for (Method method : WorkerInboundController.class.getDeclaredMethods()) {
            PostMapping mapping = method.getAnnotation(PostMapping.class);
            if (mapping != null) {
                paths.add(String.join(",", mapping.value()));
            }
        }
        assertThat(paths).containsExactlyInAnyOrder("/recognize", "/drafts", "/drafts/{id}/post");
    }

    // ============================================================ ②③④ 源码判据

    @Test
    @DisplayName("🔴 零商家权限码：不使用 @RequirePermission / PermissionInterceptor，也不出现任何商家码字面量")
    void workerSurfaceCarriesNoMerchantPermissionCode() throws IOException {
        for (String source : List.of(sourceOf(CONTROLLER_SRC), sourceOf(SERVICE_SRC))) {
            assertThat(source).doesNotContain("RequirePermission");
            assertThat(source).doesNotContain("PermissionInterceptor");
            assertThat(source).doesNotContain("requirePermission");
            assertThat(source).doesNotContain("inbound:view");
            assertThat(source).doesNotContain("inbound:create");
            assertThat(source).doesNotContain("product:create");
            assertThat(source).doesNotContain("order:create");
        }
    }

    @Test
    @DisplayName("🔴 不复用商家识别端点：不引用 ImageRecognitionController / TARGET_PERMISSIONS")
    void workerSurfaceDoesNotReuseTheAdminRecognitionEndpoint() throws IOException {
        for (String source : List.of(sourceOf(CONTROLLER_SRC), sourceOf(SERVICE_SRC))) {
            assertThat(source).doesNotContain("ImageRecognitionController");
            assertThat(source).doesNotContain("TARGET_PERMISSIONS");
            assertThat(source).doesNotContain("/api/admin/image-recognition");
        }
        // 复用的是**能力**（ImageRecognitionClient → ai-agent /api/internal/vision/recognize），
        // 不是那个商家人机接口 —— 识别 target 由服务端固定，客户端结构上选不了
        assertThat(sourceOf(SERVICE_SRC)).contains("ImageRecognitionClient");
    }

    @Test
    @DisplayName("🔴 不新造库存增减：源码里没有库存/台账写入方法（过账只能落到 #5045 的服务）")
    void workerSurfaceNeverWritesStockOrLedgerDirectly() throws IOException {
        for (String source : List.of(sourceOf(CONTROLLER_SRC), sourceOf(SERVICE_SRC))) {
            assertThat(source).doesNotContain("receiveStock");
            assertThat(source).doesNotContain("deductStock");
            assertThat(source).doesNotContain("restoreStock");
            assertThat(source).doesNotContain("stock_ledger_entries");
            assertThat(source).doesNotContain("StockLedgerService");
        }
        // 过账本体必须落在 #5045 的服务方法上（同一事务语义、同一批次号口径）
        assertThat(sourceOf(SERVICE_SRC)).contains("inboundOrderService.create(");
        assertThat(sourceOf(SERVICE_SRC)).contains("inboundOrderService.post(");
    }

    // ============================================================ ⑤⑥ 路径与角色

    @Test
    @DisplayName("🔴 控制器只挂在 /api/worker/inbound（不是 /api/admin/**）")
    void controllerIsMappedUnderTheWorkerPathOnly() {
        RequestMapping mapping = WorkerInboundController.class.getAnnotation(RequestMapping.class);
        assertThat(mapping).isNotNull();
        assertThat(mapping.value()).containsExactly("/api/worker/inbound");
        assertThat(mapping.value()[0]).doesNotStartWith("/api/admin");
    }

    @Test
    @DisplayName("🔴 工人角色仍在 /api/admin/** 的拒绝集合里（零商家权限的机制底座，未被人挪走）")
    void workerRoleIsStillRejectedOnTheAdminApi() throws Exception {
        Field field = SecurityConfig.class.getDeclaredField("ADMIN_API_REJECTED_ROLES");
        field.setAccessible(true);
        @SuppressWarnings("unchecked")
        Set<String> rejected = (Set<String>) field.get(null);

        assertThat(rejected).contains(WorkerSessionService.WORKER_ROLE);
        assertThat(WorkerSessionService.WORKER_ROLE).isEqualTo("worker");
        // 反向护栏：拒绝集合不是「把所有人都拒了」（那样上面那条断言恒真、且门禁失去意义）
        assertThat(rejected).doesNotContain("operator", "admin", "service");
    }

    // ============================================================ 工具

    private static List<String> fieldNames(Class<?> type) {
        List<String> names = new ArrayList<>();
        for (Field field : type.getDeclaredFields()) {
            if (!field.isSynthetic()) {
                names.add(field.getName());
            }
        }
        return names;
    }

    /** 读源码并**剥掉注释**（判据只看代码；不然一句「本类不写台账」的说明就会把自己判红）。 */
    private static String sourceOf(String relative) throws IOException {
        for (Path base : List.of(Path.of("src/main/java"), Path.of("backend/admin-api/src/main/java"))) {
            Path path = base.resolve(relative);
            if (Files.exists(path)) {
                return stripComments(Files.readString(path));
            }
        }
        throw new IOException("读不到源文件（两种工作目录都试过）: " + relative);
    }

    private static String stripComments(String source) {
        String withoutBlock = source.replaceAll("(?s)/\\*.*?\\*/", "");
        StringBuilder sb = new StringBuilder();
        for (String line : withoutBlock.split("\n", -1)) {
            int idx = line.indexOf("//");
            sb.append(idx >= 0 ? line.substring(0, idx) : line).append('\n');
        }
        return sb.toString();
    }
}
