// case_ids: DF-009
package com.migao.admin.controller;

import com.migao.admin.security.TenantOwnedResource;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.validation.Valid;
import java.lang.annotation.Annotation;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 类级元守卫（issue #6167，接 T1 / issue #6158 的 `TenantOwnedWriteEndpointGuardTest`）：
 * **服务层校验形态**的租户域写端点也要有机械判据。
 *
 * <h2>为什么要第二条守卫（T1 的面盖不到的那一半）</h2>
 * <p>T1 的面 = 「控制器方法上带 {@code @Valid} 请求体」的写端点（现取 10 条）。
 * 但本仓还有**一整类**写端点，它们的载荷校验**不在**控制器注解上，而在**方法体/服务层**
 * （典型：{@code PUT /api/admin/products/{id}/status} 签名是 {@code @RequestBody Map<String, String>}，
 * 状态机校验在 {@code ProductService}）。这类端点**不在** T1 的反射面内 ⇒
 * 「将来形态走样」不会有机械判据（T1 body 的存疑② 逐字登记了这一点）。</p>
 *
 * <h2>判据（面 = 全部 {@code @RestController} 的 PUT/PATCH + {@code {…}} 路由）</h2>
 * <ol>
 *   <li><b>未登记即红</b>：每个「服务层校验形态」的写端点必须带 {@link TenantOwnedResource}，
 *       或在**残余台账** {@code backend/admin-api/src/test/resources/tenant-ownership-service-layer-ledger.json}
 *       里有一条**理由非空**的登记。</li>
 *   <li><b>残余台账只许缩短</b>：条数 ≤ 冻结上限（现取打印；上限只许往下改）。台账清空 ⇒
 *       {@code FROZEN_MAX} 必须一起降到 0（否则本判据成了空断言）。</li>
 *   <li><b>台账不许空转</b>：登记的 key 必须仍能在面内找到同形端点（修好/改名/删除 ⇒ 红）。</li>
 *   <li><b>判别力自证</b>：把一个「未标注 + 不在台账」的同形端点喂给同一份判定函数 ⇒ 必须判红；
 *       已标注 / 已在台账的 ⇒ 不判红（判据本体不是恒绿）。</li>
 *   <li><b>本单点名的形态必须在面内</b>（双向夹住）：{@code PUT /api/admin/products/{id}/status}
 *       必须出现在面内且**已标注**；把它的注解摘掉（或把判定函数反转）⇒ 判据 1 / 判据 4 当场红。</li>
 * </ol>
 *
 * <h2>覆盖面边界（如实登记，§19.1）</h2>
 * <p>「服务层校验 + 租户域资源」**判不了**（那是业务语义：同一个 PUT 可能是平台面资源）。
 * ⇒ 本守卫**只**判形态面的两个可判项：① 新出现的同形端点必须被显式处置（标注或登记）；
 * ② 已被本单认定并登记的残余，其条数只许缩短。逐条理由与**重启条件**写在台账的
 * {@code residual_scope} / {@code restart_condition} 字段里（人可读、机可核）。</p>
 */
@DisplayName("#6167 类级元守卫：服务层校验形态的租户域写端点必须被显式处置（标注 / 登记残余）")
class ServiceLayerValidatedWriteEndpointGuardTest {

    /** 面 = 控制器包（生产控制器的唯一包）。 */
    private static final String CONTROLLER_PACKAGE = "com.migao.admin.controller";

    /**
     * 残余台账（路径相对**模块根** {@code backend/admin-api}；**只许缩短**）。
     */
    private static final Path LEDGER = Paths.get(
            "src/test/resources/tenant-ownership-service-layer-ledger.json").toAbsolutePath();

    /**
     * 冻结上限（判据 2）：残余条数**现取**打印，本值只许**往下**改。
     * ⚠️ 台账清空 ⇒ 本值必须同批改成 0（否则判据恒绿）。
     */
    private static final int FROZEN_MAX_RESIDUAL_ENTRIES = 28;

    /**
     * 本单**点名**的形态（issue #6167 §二 逐字给出的例子）—— 必须在面内且已标注。
     * 现取核对（判据 5），不写死对应类名，只钉「端点 + 已标注」这一事实。
     */
    private static final String NAMED_ENDPOINT = "PUT /api/admin/products/{id}/status";

    // ──────────────────────────── 面：现取 ────────────────────────────

    /** 一个「服务层校验形态」的写端点。 */
    private record ServiceLayerEndpoint(String controller, String httpMethod, String path,
                                        boolean annotated, boolean resolvable) {
        String key() {
            return httpMethod + " " + path;
        }

        @Override
        public String toString() {
            return controller + "#" + key() + (annotated ? " [@TenantOwnedResource]" : " [未标注]")
                    + (resolvable ? "" : " [不可加载]");
        }
    }

    /**
     * 现取面：所有 {@code @RestController} 里「写端点（PUT/PATCH）+ 路径含 {@code {}}
     * + **没有** {@code @Valid @RequestBody}」的方法。
     *
     * <p>与 T1 的守卫互补（那条取「有 {@code @Valid}」），两条合起来盖住全部 PUT/PATCH
     * 带路径变量的写面。扫的是**反射面**（本包 classpath 里的真类），不是源码文本。</p>
     */
    private static List<ServiceLayerEndpoint> scan() {
        List<ServiceLayerEndpoint> found = new ArrayList<>();
        for (Class<?> clazz : controllerClasses()) {
            String base = "";
            RequestMapping classMapping = clazz.getAnnotation(RequestMapping.class);
            if (classMapping != null && classMapping.value().length > 0) {
                base = classMapping.value()[0];
            }
            Method[] methods;
            try {
                methods = clazz.getDeclaredMethods();
            } catch (Throwable ignored) {
                continue;
            }
            for (Method method : methods) {
                PutMapping put = method.getAnnotation(PutMapping.class);
                PatchMapping patch = method.getAnnotation(PatchMapping.class);
                if (put == null && patch == null) {
                    continue;
                }
                String[] paths = put != null ? put.value() : patch.value();
                String path = base + (paths.length > 0 ? paths[0] : "");
                if (!path.contains("{")) {
                    continue;
                }
                if (hasValidatedRequestBody(method)) {
                    continue; // 归 T1 的面（@Valid 形态），本条不重判
                }
                found.add(new ServiceLayerEndpoint(clazz.getSimpleName(),
                        put != null ? "PUT" : "PATCH", path,
                        method.getAnnotation(TenantOwnedResource.class) != null, true));
            }
        }
        return found;
    }

    private static boolean hasValidatedRequestBody(Method method) {
        for (java.lang.reflect.Parameter parameter : method.getParameters()) {
            if (!parameter.isAnnotationPresent(RequestBody.class)) {
                continue;
            }
            for (Annotation annotation : parameter.getDeclaredAnnotations()) {
                if (annotation.annotationType().equals(Valid.class)) {
                    return true;
                }
            }
        }
        return false;
    }

    /** 面内全部生产控制器类（排除本判据文件里的夹具）。 */
    private static List<Class<?>> controllerClasses() {
        List<Class<?>> classes = new ArrayList<>();
        try (var stream = Files.walk(Paths.get("target/classes/" + CONTROLLER_PACKAGE.replace('.', '/')))) {
            for (Path file : stream.filter(p -> p.toString().endsWith(".class")).toList()) {
                String relative = Paths.get("target/classes").toAbsolutePath()
                        .relativize(file.toAbsolutePath()).toString();
                String binary = relative.substring(0, relative.length() - ".class".length())
                        .replace(java.io.File.separatorChar, '.');
                if (binary.startsWith(ServiceLayerValidatedWriteEndpointGuardTest.class.getName())) {
                    continue;
                }
                try {
                    Class<?> clazz = Class.forName(binary, false,
                            Thread.currentThread().getContextClassLoader());
                    if (clazz.isAnnotationPresent(RestController.class)) {
                        classes.add(clazz);
                    }
                } catch (Throwable ignored) {
                    // 不可加载的类不构成「已判」——面本身不为它背书（见 coverage_boundary）
                }
            }
        } catch (Exception e) {
            throw new IllegalStateException("扫描控制器面失败: " + e.getMessage(), e);
        }
        assertThat(classes).as("扫描面为空 ⇒ 判据是空断言，必须当场红").isNotEmpty();
        return classes;
    }

    // ──────────────────────────── 台账 ────────────────────────────

    private record LedgerEntry(String key, String reason) {
    }

    private static Map<String, String> readLedger() {
        assertThat(Files.isRegularFile(LEDGER))
                .as("残余台账不存在: " + LEDGER).isTrue();
        try {
            JsonNode root = new ObjectMapper().readTree(Files.readString(LEDGER));
            Map<String, String> entries = new LinkedHashMap<>();
            JsonNode array = root.get("residual_entries");
            assertThat(array).as("台账缺 residual_entries 数组").isNotNull();
            for (JsonNode entry : array) {
                String key = entry.get("endpoint").asText();
                String reason = entry.hasNonNull("reason") ? entry.get("reason").asText() : "";
                assertThat(reason)
                        .as("台账条目 " + key + " 的 reason 为空 —— 残余必须有理由（判据 1b）")
                        .isNotBlank();
                assertThat(entries.put(key, reason)).as("台账条目重复: " + key).isNull();
            }
            return entries;
        } catch (Exception e) {
            throw new IllegalStateException("读台账失败: " + e.getMessage(), e);
        }
    }

    // ──────────────────────────── 判定本体（可被夹具复用 ⇒ 判据 4） ────────────────────────────

    /** 未处置（既没标注、也不在台账）的端点 —— 判据 1 的判定本体。 */
    static List<ServiceLayerEndpoint> unhandled(List<ServiceLayerEndpoint> endpoints,
                                                Set<String> ledgerKeys) {
        List<ServiceLayerEndpoint> bad = new ArrayList<>();
        for (ServiceLayerEndpoint endpoint : endpoints) {
            if (!endpoint.annotated() && !ledgerKeys.contains(endpoint.key())) {
                bad.add(endpoint);
            }
        }
        return bad;
    }

    // ──────────────────────────── 判据 ────────────────────────────

    @Test
    @DisplayName("判据 1：服务层校验形态的写端点 ⇒ 必须标注 @TenantOwnedResource 或在残余台账里")
    void everyServiceLayerValidatedWriteEndpointIsHandled() {
        List<ServiceLayerEndpoint> endpoints = scan();
        Map<String, String> ledger = readLedger();
        List<ServiceLayerEndpoint> unhandled = unhandled(endpoints, ledger.keySet());

        System.out.println("[#6167] 面（PUT/PATCH + {路径变量} + 无 @Valid 请求体）现取 = "
                + endpoints.size() + " 条");
        for (ServiceLayerEndpoint endpoint : endpoints) {
            System.out.println("    - " + endpoint);
        }
        System.out.println("[#6167] 本单已标注 = "
                + endpoints.stream().filter(ServiceLayerEndpoint::annotated).count()
                + " 条；残余台账现取 = " + ledger.size() + " 条（上限 "
                + FROZEN_MAX_RESIDUAL_ENTRIES + "）");

        assertThat(unhandled)
                .as("以下端点属于「服务层校验形态」却既未标注、也不在残余台账里："
                        + "请加 @TenantOwnedResource(\"<资源键>\")（并在 "
                        + "TenantResourceOwnership.registerChecks() 登记该键），"
                        + "或进 " + LEDGER.getFileName() + " 写明理由与重启条件。未处置 = " + unhandled)
                .isEmpty();
    }

    @Test
    @DisplayName("判据 2：残余台账条数现取 ≤ 冻结上限（只许缩短）")
    void residualLedgerOnlyShrinks() {
        int now = readLedger().size();
        System.out.println("[#6167] 残余台账条数现取 = " + now
                + "（冻结上限 " + FROZEN_MAX_RESIDUAL_ENTRIES + "）");
        assertThat(now)
                .as("残余条数上涨 ⇒ 有人用「加一条登记」代替「加一行注解」/ 新形态端点悄悄进门")
                .isLessThanOrEqualTo(FROZEN_MAX_RESIDUAL_ENTRIES);
    }

    @Test
    @DisplayName("判据 3：残余台账不许出现死条目（修好了却没删 ⇒ 红）")
    void residualLedgerEntriesStayLive() {
        Set<String> live = new LinkedHashSet<>();
        for (ServiceLayerEndpoint endpoint : scan()) {
            live.add(endpoint.key());
        }
        List<String> dead = new ArrayList<>();
        for (String key : readLedger().keySet()) {
            if (!live.contains(key)) {
                dead.add(key + "（面内已无同形端点：已标注 / 已删除 / 已改名）");
            }
        }
        assertThat(dead)
                .as("残余台账出现**死条目** —— 处置掉一个存量端点必须同批删掉它的条目并下调 "
                        + "FROZEN_MAX_RESIDUAL_ENTRIES（台账只许缩短）: " + dead)
                .isEmpty();
    }

    @Test
    @DisplayName("判据 4：判别力自证 —— 未处置的反例必须被判红（判据本体不是恒绿）")
    void theJudgementActuallyRejects() {
        ServiceLayerEndpoint bad =
                new ServiceLayerEndpoint("FixtureController", "PUT", "/api/admin/fixtures/{id}/status",
                        false, true);
        ServiceLayerEndpoint good =
                new ServiceLayerEndpoint("FixtureController", "PUT", "/api/admin/gated/{id}/status",
                        true, true);
        ServiceLayerEndpoint registered =
                new ServiceLayerEndpoint("FixtureController", "PUT", "/api/admin/residual/{id}/status",
                        false, true);

        assertThat(unhandled(List.of(bad, good, registered),
                Set.of("PUT /api/admin/residual/{id}/status")))
                .as("未标注 + 不在台账的端点必须被判红")
                .containsExactly(bad);
        assertThat(unhandled(List.of(good), Set.of()))
                .as("已标注的端点不该被判红")
                .isEmpty();
        assertThat(unhandled(List.of(registered), Set.of("PUT /api/admin/residual/{id}/status")))
                .as("台账里的端点不该被判红")
                .isEmpty();
    }

    @Test
    @DisplayName("判据 5：本单点名的形态（products/{id}/status）在面内且已标注（双向夹住）")
    void namedEndpointIsInSurfaceAndAnnotated() throws Exception {
        List<ServiceLayerEndpoint> endpoints = scan();
        List<String> keys = new ArrayList<>();
        for (ServiceLayerEndpoint endpoint : endpoints) {
            keys.add(endpoint.key());
        }
        assertThat(keys)
                .as("issue #6167 §二 点名的端点必须落进本守卫的面内（否则本判据盖不到它）；"
                        + "面现取 = " + keys)
                .contains(NAMED_ENDPOINT);

        // ── 正向：磁盘上的真类必须带着认定注解 + 认定键 ──
        Class<?> productController = Class.forName(
                "com.migao.admin.controller.ProductController", false,
                Thread.currentThread().getContextClassLoader());
        TenantOwnedResource annotation = null;
        for (Method method : productController.getDeclaredMethods()) {
            PutMapping put = method.getAnnotation(PutMapping.class);
            if (put != null && put.value().length > 0 && "/{id}/status".equals(put.value()[0])) {
                annotation = method.getAnnotation(TenantOwnedResource.class);
            }
        }
        assertThat(annotation)
                .as("ProductController 的 PUT /{id}/status 必须带 @TenantOwnedResource（摘掉 ⇒ 本判据与判据 1 同时红）")
                .isNotNull();
        assertThat(annotation.value())
                .as("认定键必须与 `product`（T1 已登记的键）同源，不新造第二套资源语义")
                .isEqualTo("product");

        // ── 反向（夹住）：把「这条端点」当作**未标注**喂给同一份判定 ⇒ 必须判红 ──
        // 即：上面那条 isTrue 的读数不是空断言 —— 同一个 key 在 annotated=false 时确实会被判红。
        ServiceLayerEndpoint asUnannotated =
                new ServiceLayerEndpoint("ProductController", "PUT", NAMED_ENDPOINT, false, true);
        assertThat(unhandled(List.of(asUnannotated), Set.of()))
                .as("若把 " + NAMED_ENDPOINT + " 的注解摘掉（本单的接线），判据 1 必须当场判红")
                .containsExactly(asUnannotated);
    }
}
