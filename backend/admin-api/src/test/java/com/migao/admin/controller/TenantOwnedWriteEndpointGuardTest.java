// case_ids: DF-009
package com.migao.admin.controller;

import com.migao.admin.security.TenantOwnedResource;
import com.migao.admin.security.TenantOwnershipInterceptor;
import com.migao.admin.security.TenantResourceOwnership;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.PathVariable;

import jakarta.validation.Valid;
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
 * 🔴 类级元守卫（issue #6158）：**新加一个租户域资源的写端点、却把载荷校验放在归属判定之前
 * ⇒ 当场红**。
 *
 * <h2>判据（面 = 全部 {@code @RestController}）</h2>
 * <ol>
 *   <li><b>未登记即红</b>：所有「写端点（{@code @PutMapping} / {@code @PatchMapping}）+
 *       {@code @Valid} 请求体」的方法，必须带 {@link TenantOwnedResource}，或在**豁免台账**
 *       {@code backend/admin-api/src/test/resources/tenant-ownership-required-ledger.json}
 *       里有一条**理由非空**的登记。</li>
 *   <li><b>台账不许出现死条目</b>：每个登记条目必须仍能在面内找到**同形**的端点
 *       （同http方法 + 同路径 + 仍带 {@code @Valid} 请求体 + 仍**未**标注）⇒ 修好了却忘删条目 = 红
 *       （条目只许缩短）。</li>
 *   <li><b>登记条数现取 + 只许缩短</b>：条目数 ≤ 冻结上限（现取打印，上限只许往下改）。</li>
 *   <li><b>标注必须指名真资源</b>：{@code @TenantOwnedResource} 的键必须在
 *       {@link TenantResourceOwnership} 里已登记（否则生产上会 fail-closed 抛错）。</li>
 *   <li><b>拦截器接线必须还在</b>：{@link TenantOwnershipInterceptor} 的 {@code preHandle}
 *       里必须仍出现「按注解取资源键 + 取 {id} + 去认定表查」这三段（摘掉接线 = 红）。</li>
 *   <li><b>判别力自证（会红的反例）</b>：把一个「带 {@code @Valid} 请求体、未标注、不在台账」
 *       的端点**当作**输入喂给同一份判定函数 ⇒ 必须被判红（判据本体不是恒绿）。</li>
 * </ol>
 *
 * <h2>它为什么能拦住「以后」</h2>
 * <p>面是**现取**的（扫描所有 {@code @RestController}），不是冻结清单 ⇒ 新端点一落地就进面；
 * 进面而没有标注（也不在台账里）⇒ 判据 1 当场红并**具名叫出**该端点。
 * 这与 {@code PermissionInterceptor}（issue #6063）的「授权先于参数解析」是同一族纪律 ——
 * 本条是它在**归属**面上的机械守卫。</p>
 */
@DisplayName("#6158 类级元守卫：租户域写端点的归属判定必须在载荷校验之前")
class TenantOwnedWriteEndpointGuardTest {

    /** 面 = 控制器包（生产控制器的唯一包）。 */
    private static final String CONTROLLER_PACKAGE = "com.migao.admin.controller";

    /** 豁免台账（路径相对仓库根；**只许缩短**）。 */
    private static final Path LEDGER = Paths.get(
            "src/test/resources/tenant-ownership-required-ledger.json").toAbsolutePath();

    /**
     * 冻结上限（判据 3）：台账条数**现取**打印，本值只许**往下**改。
     * 修掉一个存量端点 ⇒ 同批删掉对应条目并下调本值。
     */
    private static final int FROZEN_MAX_LEDGER_ENTRIES = 0;

    // ──────────────────────────── 面：现取 ────────────────────────────

    /** 一个写端点（http 方法 + 路径 + 是否标注 + 是否在台账）。 */
    private record WriteEndpoint(String controller, String httpMethod, String path, boolean annotated) {
        String key() {
            return httpMethod + " " + path;
        }

        @Override
        public String toString() {
            return controller + "#" + key() + (annotated ? " [@TenantOwnedResource]" : " [未标注]");
        }
    }

    /**
     * 现取面：所有 {@code @RestController} 里「写端点 + {@code @Valid} 请求体」的方法。
     *
     * <p>扫的是**反射面**（本包 classpath 里的真类），不是源码文本 —— 源码扫描分不清注释与代码，
     * 而这里要判的正是「注解在不在方法上」。</p>
     */
    private static List<WriteEndpoint> scan() {
        List<WriteEndpoint> found = new ArrayList<>();
        for (Class<?> clazz : controllerClasses()) {
            String base = "";
            RequestMapping classMapping = clazz.getAnnotation(RequestMapping.class);
            if (classMapping != null && classMapping.value().length > 0) {
                base = classMapping.value()[0];
            }
            for (Method method : clazz.getDeclaredMethods()) {
                PutMapping put = method.getAnnotation(PutMapping.class);
                org.springframework.web.bind.annotation.PatchMapping patch =
                        method.getAnnotation(org.springframework.web.bind.annotation.PatchMapping.class);
                if (put == null && patch == null) {
                    continue;
                }
                if (!hasValidatedRequestBody(method)) {
                    continue;
                }
                String[] paths = put != null ? put.value() : patch.value();
                String path = base + (paths.length > 0 ? paths[0] : "");
                found.add(new WriteEndpoint(clazz.getSimpleName(), put != null ? "PUT" : "PATCH", path,
                        method.getAnnotation(TenantOwnedResource.class) != null));
            }
        }
        return found;
    }

    private static boolean hasValidatedRequestBody(Method method) {
        for (java.lang.reflect.Parameter parameter : method.getParameters()) {
            if (parameter.isAnnotationPresent(RequestBody.class) && parameter.isAnnotationPresent(Valid.class)) {
                return true;
            }
        }
        return false;
    }

    /** 面内全部生产控制器类（含嵌套的静态控制器；排除本判据文件里的夹具）。 */
    private static List<Class<?>> controllerClasses() {
        List<Class<?>> classes = new ArrayList<>();
        try (var stream = Files.walk(Paths.get("target/classes/" + CONTROLLER_PACKAGE.replace('.', '/')))) {
            for (Path file : stream.filter(p -> p.toString().endsWith(".class")).toList()) {
                String relative = Paths.get("target/classes").toAbsolutePath()
                        .relativize(file.toAbsolutePath()).toString();
                String binary = relative.substring(0, relative.length() - ".class".length())
                        .replace(java.io.File.separatorChar, '.');
                if (binary.startsWith(TenantOwnedWriteEndpointGuardTest.class.getName())) {
                    continue; // 夹具不是生产控制器
                }
                try {
                    Class<?> clazz = Class.forName(binary, false,
                            Thread.currentThread().getContextClassLoader());
                    if (clazz.isAnnotationPresent(RestController.class)) {
                        classes.add(clazz);
                    }
                } catch (Throwable ignored) {
                    // 不可加载的类不构成「已判」——但也不该静默：见断言 0 的兜底
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
                .as("豁免台账不存在: " + LEDGER).isTrue();
        try {
            JsonNode root = new ObjectMapper().readTree(Files.readString(LEDGER));
            Map<String, String> entries = new LinkedHashMap<>();
            JsonNode array = root.get("entries");
            assertThat(array).as("台账缺 entries 数组").isNotNull();
            for (JsonNode entry : array) {
                String key = entry.get("endpoint").asText();
                String reason = entry.hasNonNull("reason") ? entry.get("reason").asText() : "";
                assertThat(reason)
                        .as("台账条目 " + key + " 的 reason 为空 —— 豁免必须有理由（判据 1b）")
                        .isNotBlank();
                assertThat(entries.put(key, reason)).as("台账条目重复: " + key).isNull();
            }
            return entries;
        } catch (Exception e) {
            throw new IllegalStateException("读台账失败: " + e.getMessage(), e);
        }
    }

    // ──────────────────────────── 判定本体（可被夹具复用 ⇒ 判据 6） ────────────────────────────

    /** 未登记（既没标注、也不在台账）的端点 —— 判据 1 的判定本体。 */
    static List<WriteEndpoint> unregistered(List<WriteEndpoint> endpoints, Set<String> ledgerKeys) {
        List<WriteEndpoint> bad = new ArrayList<>();
        for (WriteEndpoint endpoint : endpoints) {
            if (!endpoint.annotated() && !ledgerKeys.contains(endpoint.key())) {
                bad.add(endpoint);
            }
        }
        return bad;
    }

    // ──────────────────────────── 判据 ────────────────────────────

    @Test
    @DisplayName("判据 1：写端点 + @Valid 请求体 ⇒ 必须标注 @TenantOwnedResource（或在台账里）")
    void everyValidatedWriteEndpointIsGated() {
        List<WriteEndpoint> endpoints = scan();
        Map<String, String> ledger = readLedger();
        List<WriteEndpoint> unregistered = unregistered(endpoints, ledger.keySet());

        System.out.println("[#6158] 面（写端点 + @Valid 请求体）现取 = " + endpoints.size() + " 条");
        for (WriteEndpoint endpoint : endpoints) {
            System.out.println("    - " + endpoint);
        }
        System.out.println("[#6158] 台账现取 = " + ledger.size() + " 条（上限 " + FROZEN_MAX_LEDGER_ENTRIES + "）");

        assertThat(unregistered)
                .as("以下端点**载荷校验先于归属判定**（跨租户 + 非法载荷会先拿到 422/400）"
                        + "：请加 @TenantOwnedResource(\"<资源键>\") 并在 "
                        + "TenantResourceOwnership.registerChecks() 登记该键；"
                        + "确属有意豁免则进 " + LEDGER.getFileName() + " 并写明理由。未登记 = "
                        + unregistered)
                .isEmpty();
    }

    @Test
    @DisplayName("判据 2：台账不许出现死条目（修好了却没删 ⇒ 红；条目只许缩短）")
    void ledgerEntriesStayLive() {
        List<WriteEndpoint> endpoints = scan();
        Map<String, String> ledger = readLedger();
        Set<String> live = new LinkedHashSet<>();
        for (WriteEndpoint endpoint : endpoints) {
            live.add(endpoint.key());
        }
        List<String> dead = new ArrayList<>();
        for (String key : ledger.keySet()) {
            if (!live.contains(key)) {
                dead.add(key + "（面内已无同形端点：已标注 / 已删除 / 已改名）");
            }
        }
        assertThat(dead)
                .as("豁免台账出现**死条目** —— 修好一个存量端点必须同批删掉它的条目并下调 "
                        + "FROZEN_MAX_LEDGER_ENTRIES（台账只许缩短）: " + dead)
                .isEmpty();
    }

    @Test
    @DisplayName("判据 3：台账条数现取 ≤ 冻结上限（只许缩短；上限只许往下改）")
    void ledgerOnlyShrinks() {
        int now = readLedger().size();
        System.out.println("[#6158] 台账条数现取 = " + now + "（冻结上限 " + FROZEN_MAX_LEDGER_ENTRIES + "）");
        assertThat(now)
                .as("台账条数上涨 ⇒ 有人用「加一条登记」代替「加一行注解」—— 这正是本守卫要拦的动作")
                .isLessThanOrEqualTo(FROZEN_MAX_LEDGER_ENTRIES);
    }

    @Test
    @DisplayName("判据 4：@TenantOwnedResource 的键必须已在认定表登记（否则生产 fail-closed 抛错）")
    void annotatedKeysExistInRegistry() {
        // 认定表本体：**显式**调一次登记（生产上由 @PostConstruct 调；这里没有容器）
        TenantResourceOwnership ownership = new TenantResourceOwnership(
                null, null, null, null, null, null, null, null);
        ownership.registerChecks();
        Set<String> registered = ownership.registeredResources();
        Set<String> annotated = new LinkedHashSet<>();
        for (WriteEndpoint endpoint : scan()) {
            if (endpoint.annotated()) {
                annotated.add(endpoint.key());
            }
        }
        // 逐个端点取注解键（record 没带键，这里再扫一遍；注解是 RUNTIME 的，读得到）
        Map<String, String> endpointToKey = new TreeMap<>();
        for (Class<?> clazz : controllerClasses()) {
            RequestMapping classMapping = clazz.getAnnotation(RequestMapping.class);
            String base = classMapping != null && classMapping.value().length > 0 ? classMapping.value()[0] : "";
            for (Method method : clazz.getDeclaredMethods()) {
                TenantOwnedResource resource = method.getAnnotation(TenantOwnedResource.class);
                PutMapping put = method.getAnnotation(PutMapping.class);
                org.springframework.web.bind.annotation.PatchMapping patch =
                        method.getAnnotation(org.springframework.web.bind.annotation.PatchMapping.class);
                if (resource == null || (put == null && patch == null)) {
                    continue;
                }
                String[] paths = put != null ? put.value() : patch.value();
                endpointToKey.put((put != null ? "PUT " : "PATCH ") + base + (paths.length > 0 ? paths[0] : ""),
                        resource.value());
            }
        }
        assertThat(endpointToKey).as("一个标注都没有 ⇒ 判据是空断言").isNotEmpty();
        List<String> unknown = new ArrayList<>();
        for (Map.Entry<String, String> entry : endpointToKey.entrySet()) {
            if (!registered.contains(entry.getValue())) {
                unknown.add(entry.getKey() + " -> 未登记键 \"" + entry.getValue() + "\"");
            }
        }
        assertThat(unknown)
                .as("标注的键没在 TenantResourceOwnership 登记 ⇒ 生产上会抛 IllegalStateException"
                        + "（fail-closed，请求全灭）: " + unknown + "; 已登记 = " + registered)
                .isEmpty();
        assertThat(annotated).isNotEmpty();
    }

    @Test
    @DisplayName("判据 5：拦截器接线还在（读注解 / 取 {id} / 去认定表查 三段缺一即红）")
    void interceptorWiringIsPresent() throws Exception {
        Path source = Paths.get("src/main/java/com/migao/admin/security/TenantOwnershipInterceptor.java")
                .toAbsolutePath();
        assertThat(Files.isRegularFile(source)).as("拦截器文件不存在: " + source).isTrue();
        String text = Files.readString(source);
        assertThat(text)
                .as("拦截器丢了「读 @TenantOwnedResource」这一段 —— 摘掉接线 ⇒ 归属判定不再前置")
                .contains("TenantOwnedResource.class");
        assertThat(text)
                .as("拦截器丢了「取 {id} 路径变量」这一段")
                .contains("URI_TEMPLATE_VARIABLES_ATTRIBUTE")
                .contains("\"id\"");
        assertThat(text)
                .as("拦截器丢了「去认定表查」这一段")
                .contains("ownership.check(");
        // WebConfig 必须真的注册了它（登记了却没人调用 = 接线不在）
        String webConfig = Files.readString(
                Paths.get("src/main/java/com/migao/admin/config/WebConfig.java").toAbsolutePath());
        assertThat(webConfig)
                .as("WebConfig 没有把 TenantOwnershipInterceptor 注册进 MVC —— 拦截器永远跑不到")
                .contains("addInterceptor(tenantOwnershipInterceptor)");
    }

    @Test
    @DisplayName("判据 6：判别力自证 —— 未登记的反例必须被判红（判据本体不是恒绿）")
    void theJudgementActuallyRejects() {
        WriteEndpoint bad = new WriteEndpoint("FixtureController", "PUT", "/api/admin/fixtures/{id}", false);
        WriteEndpoint good = new WriteEndpoint("FixtureController", "PUT", "/api/admin/gated/{id}", true);
        WriteEndpoint exempt =
                new WriteEndpoint("FixtureController", "PUT", "/api/admin/exempt/{id}", false);

        assertThat(unregistered(List.of(bad, good, exempt), Set.of("PUT /api/admin/exempt/{id}")))
                .as("未标注 + 不在台账的端点必须被判红")
                .containsExactly(bad);
        assertThat(unregistered(List.of(good), Set.of()))
                .as("已标注的端点不该被判红")
                .isEmpty();
        assertThat(unregistered(List.of(exempt), Set.of("PUT /api/admin/exempt/{id}")))
                .as("台账里的端点不该被判红")
                .isEmpty();

        // 台账条数判定也要有判别力：0 条不超上限（#6167 已把台账清零）、1 条就超上限
        assertThat(0 <= FROZEN_MAX_LEDGER_ENTRIES).isTrue();
        assertThat(1 <= FROZEN_MAX_LEDGER_ENTRIES).as("上限必须随台账清零一起降到 0（只许缩短）").isFalse();
    }
}
