// case_ids: PR-113, PR-114, PR-116
package com.migao.admin.controller;

import com.migao.admin.security.SecurityConfig;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 入库标签面的**结构守卫**（issue #5052 P2）—— 让「同一路径命名空间下两套语义混用」这类缺陷进不来。
 *
 * <p>本单最值得固化的类不是某一条业务规则，而是 <b>码空间混用</b>：{@code /s/}（报工短链，
 * 302 → {@code /w/?t=<token>}）与 {@code /i/}（入库标签，302 → 落地页）是两个语义不同的
 * **公开路径命名空间**。它们的短码规格**故意同款**（8 位 Crockford Base32）⇒ 一旦有人
 * 「顺手复用那张表 / 复制一份字母表 / 把两个入口接到同一个服务」，扫标签就会变成进报工页，
 * 而**不会有任何东西变红**。本类把这条钉成源码判据（类级 meta 守卫见
 * {@code tests/unit_ci_workflows/test_public_code_spaces_are_disjoint.py}）。</p>
 *
 * <h3>钉住的八件事（逐条可红）</h3>
 * <ol>
 *   <li><b>码空间互斥</b>：标签面源码不出现报工短链的表 / 服务内部符号（{@code ProcessingSetPartToken}
 *       / {@code processing_set_part_tokens} / {@code REPORT_PAGE_PATH} / {@code "/w/"}），
 *       反向亦然（{@code WorkerShortLink*} 不出现 {@code InboundLabel} / {@code "/i/"}）；</li>
 *   <li><b>字母表单一来源</b>：Crockford 字母表字面量在全仓 admin-api 主源码里**恰好出现一次**
 *       （= {@code WorkerShortLinkService.ALPHABET}），归一化别名同理 —— 复制第二份 ⇒ 红；</li>
 *   <li><b>计数唯一写方</b>（§7.3「打印必留痕」）：{@code COALESCE(print_count…} 只在标签 Mapper 里，
 *       {@code incrementPrintCount} 只被服务层 {@code recordPrint} 调用，{@code recordPrint} 只被
 *       {@code /print} 端点调用 ⇒ **结构上不存在**第二条写计数的路径；</li>
 *   <li><b>零商家权限码</b>（§9.3 红线）：标签面 + 上传面不出现 {@code @RequirePermission} /
 *       {@code PermissionInterceptor} / 任何商家码字面量；</li>
 *   <li><b>不新造库存逻辑</b>：标签面不写库存 / 台账；</li>
 *   <li><b>落地页不硬编码域名</b>：源码里没有 {@code migaozn.com}，落地页来自 {@code @Value} 配置；</li>
 *   <li><b>公开入口已放行</b>：{@code SecurityConfig} 的 permitAll 名单里有 {@code "/i/**"}
 *       （去掉 ⇒ 扫码只会拿到 401，标签上的码等于没用 —— 行为判据见
 *       {@code SecurityConfigTest#inboundLabelShortLinkIsPublic}）；</li>
 *   <li><b>路径面**恰好一处**</b>：{@code "/i/{"} 只被一个控制器映射（两个控制器各映射一半是
 *       「两套语义在同一命名空间下」的入口形态）。</li>
 * </ol>
 */
@DisplayName("入库标签面结构守卫（#5052 P2）：码空间互斥 / 计数唯一写方 / 零商家权限码")
class InboundLabelSurfaceGuardTest {

    private static final String ALPHABET_LITERAL = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

    private static final String LABEL_SERVICE = "com/migao/admin/service/InboundLabelService.java";
    private static final String LABEL_MAPPER = "com/migao/admin/mapper/InboundLabelMapper.java";
    private static final String LABEL_CONTROLLER = "com/migao/admin/controller/WorkerInboundLabelController.java";
    private static final String SHORT_LINK_CONTROLLER =
            "com/migao/admin/controller/InboundLabelShortLinkController.java";
    private static final String UPLOAD_CONTROLLER =
            "com/migao/admin/controller/WorkerInboundUploadController.java";
    private static final String REPORT_SHORT_LINK_SERVICE =
            "com/migao/admin/service/WorkerShortLinkService.java";
    private static final String REPORT_SHORT_LINK_CONTROLLER =
            "com/migao/admin/controller/WorkerShortLinkController.java";

    // ============================================================ ① 码空间互斥

    @Test
    @DisplayName("🔴 /i/ 面绝不碰报工短链那张表（混用 ⇒ 扫标签会变成进报工页）")
    void labelSurfaceNeverTouchesTheReportShortLinkCodeSpace() throws IOException {
        for (String source : labelSurfaceSources()) {
            assertThat(source).doesNotContain("ProcessingSetPartToken");
            assertThat(source).doesNotContain("processing_set_part_tokens");
            assertThat(source).doesNotContain("REPORT_PAGE_PATH");
            assertThat(source).doesNotContain("/w/");
        }
        // 复用**生成口径**（字母表/归一化/分配器）是刻意的；复用**码表**不是
        assertThat(sourceOf(LABEL_SERVICE)).contains("WorkerShortLinkService.allocateUnique(")
                .contains("WorkerShortLinkService.normalize(");
    }

    @Test
    @DisplayName("🔴 /s/ 面绝不碰入库标签（反向互斥：报工短链入口不认识 /i/ 的码）")
    void reportShortLinkSurfaceNeverTouchesInboundLabels() throws IOException {
        for (String relative : List.of(REPORT_SHORT_LINK_SERVICE, REPORT_SHORT_LINK_CONTROLLER)) {
            String source = sourceOf(relative);
            assertThat(source).doesNotContain("InboundLabel");
            assertThat(source).doesNotContain("inbound_labels");
            assertThat(source).doesNotContain("\"/i/");
        }
    }

    // ============================================================ ② 字母表单一来源

    @Test
    @DisplayName("🔴 Crockford 字母表与归一化别名在全仓主源码里**恰好一份**（复制第二份 ⇒ 红）")
    void theShortCodeAlphabetIsDefinedExactlyOnce() throws IOException {
        List<String> carriers = new ArrayList<>();
        List<String> normalizers = new ArrayList<>();
        for (Path java : adminApiMainSources()) {
            String source = stripComments(Files.readString(java));
            if (source.contains(ALPHABET_LITERAL)) {
                carriers.add(java.getFileName().toString());
            }
            if (source.contains("replace('O', '0')")) {
                normalizers.add(java.getFileName().toString());
            }
        }
        assertThat(carriers).containsExactly("WorkerShortLinkService.java");
        assertThat(normalizers).containsExactly("WorkerShortLinkService.java");
    }

    // ============================================================ ③ 计数唯一写方（打印必留痕）

    @Test
    @DisplayName("🔴 打印必留痕：入库标签的计数自增**只有一条**写路径（Mapper ← 服务 ← /print 端点）")
    void printCountHasExactlyOneWriter() throws IOException {
        // ① 标签面内部：写 print_count 的 SQL 只在标签 Mapper 一处
        for (String relative : List.of(LABEL_SERVICE, LABEL_CONTROLLER, SHORT_LINK_CONTROLLER, UPLOAD_CONTROLLER)) {
            assertThat(sourceOf(relative))
                    .as("%s 不得自己写打印计数（计数是打印留痕的唯一来源）", relative)
                    .doesNotContain("COALESCE(print_count");
        }
        assertThat(sourceOf(LABEL_MAPPER)).contains("COALESCE(print_count, 0) + 1");

        // ② 全仓：只有标签服务调用**标签那个**自增（限定符把同名的 processing_orders 计数排除在外 ——
        //    那边的 print_count 是另一个语义、另一张表，本单一个字都不动）
        List<String> counterCallers = new ArrayList<>();
        List<String> printEndpointCallers = new ArrayList<>();
        for (Path java : adminApiMainSources()) {
            String source = stripComments(Files.readString(java));
            String name = java.getFileName().toString();
            if (source.contains("inboundLabelMapper.incrementPrintCount(")) {
                counterCallers.add(name);
            }
            if (source.contains("inboundLabelService.recordPrint(") && !name.equals("InboundLabelService.java")) {
                printEndpointCallers.add(name);
            }
        }
        assertThat(counterCallers).containsExactly("InboundLabelService.java");
        assertThat(printEndpointCallers).containsExactly("WorkerInboundLabelController.java");

        // ③ 计数与审计是**同一次调用**里的两件事（分开了就会出现「有计数没留痕」）
        assertThat(sourceOf(LABEL_SERVICE)).contains("auditLogService.recordLog(")
                .contains("InboundLabel.ACTION_PRINT");
    }

    // ============================================================ ④⑤⑥ 载体边界

    @Test
    @DisplayName("🔴 工人面的零商家权限码 + 不新造库存 + 不硬编码域名（源码判据）")
    void workerPhotoAndLabelSurfacesCarryNoMerchantPermissionCode() throws IOException {
        for (String source : labelSurfaceSources()) {
            assertThat(source).doesNotContain("RequirePermission");
            assertThat(source).doesNotContain("PermissionInterceptor");
            assertThat(source).doesNotContain("requirePermission");
            assertThat(source).doesNotContain("inbound:view");
            assertThat(source).doesNotContain("inbound:create");
            assertThat(source).doesNotContain("product:create");
            assertThat(source).doesNotContain("order:create");
            assertThat(source).doesNotContain("receiveStock");
            assertThat(source).doesNotContain("stock_ledger_entries");
            assertThat(source).doesNotContain("StockLedgerService");
            assertThat(source).doesNotContain("migaozn.com");
        }
        // 落地页地址只能来自配置（单一真相源），不能各控制器各写一份
        assertThat(sourceOf(LABEL_SERVICE)).contains("@Value(\"${migao.inbound-label.landing-path:");
    }

    @Test
    @DisplayName("🔴 标签面的三个端点与路径面（P2 只做这三件；位图端点本包不做）")
    void theLabelSurfaceHasExactlyTheP2Endpoints() throws IOException {
        String labels = sourceOf(LABEL_CONTROLLER);
        assertThat(labels).contains("\"/api/worker/inbound/labels\"")
                .contains("@GetMapping(\"/{shortCode}\")")
                .contains("@PostMapping(\"/{shortCode}/print\")");
        assertThat(sourceOf(SHORT_LINK_CONTROLLER)).contains("@GetMapping(\"/i/{shortCode}\")");
        assertThat(sourceOf(UPLOAD_CONTROLLER)).contains("\"/api/worker/inbound\"")
                .contains("@PostMapping(value = \"/upload\"");
        // 服务端位图（§7.2 原口径）已被用户改判为设备侧渲染 ⇒ 本包**不做** bitmap 端点
        for (String source : labelSurfaceSources()) {
            assertThat(source).doesNotContain("/bitmap");
        }
    }

    // ============================================================ ⑦⑧ 公开入口

    @Test
    @DisplayName("🔴 /i/** 在 SecurityConfig 里 permitAll（去掉 ⇒ 扫码只会拿到 401，纸上的码等于没用）")
    void thePublicEntryIsAllowedInSecurityConfig() throws IOException {
        // ⚠️ 这里必须读**原文**（不剥注释）：字面量 `"/i/**"` 自己就含 `/*` 两个字符，
        //    任何「块注释剥离」都会把它连同后面的代码一起吃掉（实测：剥离后本断言必假红）。
        //    代价是注释里提到该字面量也可能命中 —— 故断言用**带引号的完整字面量**，且
        //    真正的行为判据在 SecurityConfigTest（未认证请求能到达控制器）。
        String security = rawSourceOf("com/migao/admin/security/SecurityConfig.java");
        assertThat(security).contains("\"/i/**\"");
        assertThat(security).contains("\"/s/**\"");
        // permitAll 名单里两者都在**同一个** requestMatchers(...).permitAll() 段内（没有第二个名单）
        int permitAll = security.indexOf(".permitAll()");
        assertThat(permitAll).isGreaterThan(0);
        assertThat(security.substring(0, permitAll)).contains("\"/i/**\"").contains("\"/s/**\"");
        // 反向护栏：新增的公开入口**不**放宽工人与商家面的隔离（工人仍在 /api/admin/** 的拒绝集合里）
        java.util.Set<String> rejectedRoles;
        try {
            java.lang.reflect.Field rejected = SecurityConfig.class.getDeclaredField("ADMIN_API_REJECTED_ROLES");
            rejected.setAccessible(true);
            @SuppressWarnings("unchecked")
            java.util.Set<String> value = (java.util.Set<String>) rejected.get(null);
            rejectedRoles = value;
        } catch (ReflectiveOperationException e) {
            throw new IOException("ADMIN_API_REJECTED_ROLES 不见了 —— 工人零商家权限的机制底座被挪走", e);
        }
        assertThat(rejectedRoles).contains("worker").doesNotContain("operator", "admin");
    }

    @Test
    @DisplayName("🔴 \"/i/{\" 只被**一个**控制器映射（两个控制器各映射一半 = 同一命名空间两套语义）")
    void theShortLinkPathIsMappedExactlyOnce() throws IOException {
        List<String> mappers = new ArrayList<>();
        Path controllerDir = mainJavaRoot().resolve("com/migao/admin/controller");
        try (Stream<Path> files = Files.list(controllerDir)) {
            for (Path java : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                if (strippedFrom(java).contains("@GetMapping(\"/i/{shortCode}\")")) {
                    mappers.add(java.getFileName().toString());
                }
            }
        }
        assertThat(mappers).containsExactly("InboundLabelShortLinkController.java");
    }

    // ============================================================ 工具

    private static List<String> labelSurfaceSources() throws IOException {
        return List.of(sourceOf(LABEL_SERVICE), sourceOf(LABEL_MAPPER),
                sourceOf(LABEL_CONTROLLER), sourceOf(SHORT_LINK_CONTROLLER), sourceOf(UPLOAD_CONTROLLER));
    }

    private static List<Path> adminApiMainSources() throws IOException {
        try (Stream<Path> walk = Files.walk(mainJavaRoot())) {
            return walk.filter(p -> p.toString().endsWith(".java")).sorted().toList();
        }
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

    private static String sourceOf(String relative) throws IOException {
        return strippedFrom(mainJavaRoot().resolve(relative));
    }

    /** 读原文（不剥注释）—— 只给「判据对象本身就是含 `/*` 的字面量」那一条用。 */
    private static String rawSourceOf(String relative) throws IOException {
        return Files.readString(mainJavaRoot().resolve(relative));
    }

    private static String strippedFrom(Path path) throws IOException {
        return stripComments(Files.readString(path));
    }

    /** 读源码并**剥掉注释**（判据只看代码；否则一句「本类不写台账」的说明就会把自己判红）。 */
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
