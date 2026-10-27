// case_ids: OR-071
package com.migao.admin.controller;

import com.migao.admin.security.RequirePermission;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 打印流水面的**结构守卫**（issue #7902）—— 让「打印入口另立权限码」与「路径撞车」进不来。
 *
 * <h3>为什么需要它（这两件事都能静默上线）</h3>
 * <ol>
 *   <li><b>写面另立权限码 ⇒ 现网岗位全体 403</b>：打印入口本来就在订单详情页，能看详情的人就该能打。
 *       若给 {@code POST} 挂一个 `order:print` 之类的新码，种子岗位里没有人持它 ⇒ 商家点「打印」当场 403，
 *       而单测（不起 Spring 上下文）与页面渲染（按钮还在）都不会红。本类把「生效码 == order:detail」
 *       钉成源码判据：新增方法级覆盖 / 改类级码 ⇒ 红。</li>
 *   <li><b>路径撞车 ⇒ 启动期才炸 / 打到别的处理器</b>：{@code OrderController} 已有
 *       {@code GET /api/admin/orders/{id:[0-9a-fA-F-]+}} 通配。本面必须挂在
 *       <b>更深的静态段</b> {@code /print-logs} 上，且全仓只有**一个**控制器映射这条路径
 *       （两个控制器各映射一半 = 同一命名空间两套语义）。</li>
 * </ol>
 *
 * <h3>红证</h3>
 * <ul>
 *   <li>把类级码改成 {@code order:list} ⇒ 判据 1 红；</li>
 *   <li>在某个方法上加 {@code @RequirePermission("order:create")} ⇒ 判据 1 红（生效码取方法级优先）；</li>
 *   <li>把路径改成 {@code /api/admin/orders/{orderId}/print}（少一层静态段）或复制到第二个控制器 ⇒ 判据 2/3 红。</li>
 * </ul>
 */
@DisplayName("打印流水面结构守卫（#7902）：生效权限码 / 路径面 / 唯一映射")
class PrintLogSurfaceGuardTest {

    private static final Class<?> CONTROLLER = PrintLogController.class;
    private static final String EXPECTED_CODE = "order:detail";
    private static final String EXPECTED_PATH = "/api/admin/orders/{orderId}/print-logs";

    // ============================================================ ① 生效权限码

    @Test
    @DisplayName("🔴 两个端点的**生效**权限码都是 order:detail（写面同码：打印入口本来就在订单详情页）")
    void bothEndpointsResolveToOrderDetail() {
        List<Method> mapped = mappedMethods();
        assertThat(mapped).as("本面只该有两个端点（POST 登记 / GET 列表）").hasSize(2);
        for (Method method : mapped) {
            assertThat(effectiveCode(method))
                    .as("%s 的生效权限码", method.getName())
                    .isEqualTo(EXPECTED_CODE);
        }
    }

    @Test
    @DisplayName("🔴 不新造权限码：类级恰好一条 @RequirePermission，值就是 order:detail")
    void theClassLevelAnnotationIsTheOnlyCodeDeclaration() {
        List<String> codes = new ArrayList<>();
        if (CONTROLLER.isAnnotationPresent(RequirePermission.class)) {
            codes.add(CONTROLLER.getAnnotation(RequirePermission.class).value());
        }
        for (Method method : CONTROLLER.getDeclaredMethods()) {
            if (method.isAnnotationPresent(RequirePermission.class)) {
                codes.add(method.getAnnotation(RequirePermission.class).value());
            }
        }
        assertThat(codes).containsExactly(EXPECTED_CODE);
    }

    // ============================================================ ② 路径面

    @Test
    @DisplayName("🔴 路径面 = /api/admin/orders/{orderId}/print-logs（静态段 print-logs 在变量之后，比 {id} 更深）")
    void thePathIsDeeperThanTheOrderWildcard() {
        RequestMapping classMapping = CONTROLLER.getAnnotation(RequestMapping.class);
        assertThat(classMapping).as("缺类级 @RequestMapping").isNotNull();
        assertThat(classMapping.value()).containsExactly(EXPECTED_PATH);

        for (Method method : mappedMethods()) {
            String suffix = mappingPath(method);
            assertThat(suffix).as("%s 不应再追加路径段（挂载点由类级决定）", method.getName())
                    .isIn("", EXPECTED_PATH);
        }
        // 「更深」的结构事实：静态段排在变量之后 ⇒ 不会与 GET /{id} 通配抢同一路径
        assertThat(EXPECTED_PATH.indexOf("/print-logs"))
                .isGreaterThan(EXPECTED_PATH.indexOf("{orderId}"));
    }

    @Test
    @DisplayName("🔴 全仓只有**一个**控制器映射 /print-logs，且订单控制器不认识它（无第二套语义）")
    void thePathIsMappedExactlyOnce() throws IOException {
        List<String> mappings = new ArrayList<>();
        Path controllerDir = mainJavaRoot().resolve("com/migao/admin/controller");
        try (Stream<Path> files = Files.list(controllerDir)) {
            for (Path java : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                String source = Files.readString(java);
                if (source.contains(EXPECTED_PATH)) {
                    mappings.add(java.getFileName().toString());
                }
            }
        }
        assertThat(mappings).containsExactly("PrintLogController.java");

        // 订单控制器**不得**出现这条路径的第二个挂载点（它的 /{id} 通配不得顺带吞下 print-logs）
        String orderController = Files.readString(controllerDir.resolve("OrderController.java"));
        assertThat(orderController).doesNotContain("/print-logs");
    }

    // ============================================================ ③ 结构事实

    @Test
    @DisplayName("是 @RestController（不是被 MVC 当视图解析）且注入服务（不做无服务的空壳）")
    void itIsARestControllerWiredToTheService() throws IOException {
        assertThat(CONTROLLER.isAnnotationPresent(RestController.class)).isTrue();
        String source = Files.readString(mainJavaRoot()
                .resolve("com/migao/admin/controller/PrintLogController.java"));
        assertThat(source).contains("private final PrintLogService printLogService;");
        // 日志只带 orderId / docType，不许把整段 UA（可能含指纹）写进日志
        assertThat(source).doesNotContain("getHeader(\"User-Agent\") + ");
    }

    // ============================================================ 工具

    private static List<Method> mappedMethods() {
        List<Method> mapped = new ArrayList<>();
        for (Method method : CONTROLLER.getDeclaredMethods()) {
            if (method.isAnnotationPresent(PostMapping.class) || method.isAnnotationPresent(GetMapping.class)) {
                mapped.add(method);
            }
        }
        return mapped;
    }

    /** 与 {@code PermissionInterceptor} 同一解析顺序：方法级优先，其次类级。 */
    private static String effectiveCode(Method method) {
        RequirePermission onMethod = method.getAnnotation(RequirePermission.class);
        if (onMethod != null) {
            return onMethod.value();
        }
        RequirePermission onClass = CONTROLLER.getAnnotation(RequirePermission.class);
        return onClass == null ? null : onClass.value();
    }

    private static String mappingPath(Method method) {
        PostMapping post = method.getAnnotation(PostMapping.class);
        if (post != null) {
            return String.join("/", post.value());
        }
        GetMapping get = method.getAnnotation(GetMapping.class);
        if (get != null) {
            return String.join("/", get.value());
        }
        return "";
    }

    /** 主源码根（`src/main/java` 或 `backend/admin-api/src/main/java`，取决于工作目录）。 */
    private static Path mainJavaRoot() throws IOException {
        for (Path base : List.of(Path.of("src/main/java"), Path.of("backend/admin-api/src/main/java"))) {
            if (Files.isDirectory(base.resolve("com/migao/admin"))) {
                return base;
            }
        }
        throw new IOException("找不到 admin-api 主源码根（两种工作目录都试过）");
    }
}
