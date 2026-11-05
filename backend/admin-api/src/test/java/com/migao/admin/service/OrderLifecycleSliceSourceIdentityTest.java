// case_ids: MC-201
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link OrderService} 生命周期族切片（issue #8191，P2-1d）的<b>搬运逐字节一致</b>判据。
 *
 * <p><b>对象</b>：拆分前的门面源码（{@code origin/main} 2,268 行）随判据入库，
 * {@code backend/admin-api/src/test/resources/order-lifecycle/OrderService.baseline.txt}，
 * sha256 钉死在本类里 ⇒ 基线被改（哪怕一个字符）当场红。</p>
 *
 * <p><b>三条断言</b>：① 每个搬走的方法体（含签名，到配对右括号）必须**原样**出现在
 * {@link OrderLifecycleService}；② 门面里**一处都不许留**同一段方法体（否则就是两份实现）；
 * ③ 具名的 3 处跨类限定必须**恰好**出现 —— 多一处少一处都红（防止「悄悄改了别的东西」也防止
 * 「限定被顺手撤掉」）。</p>
 *
 * <p><b>为什么这条判据会红</b>：把搬走的方法体改动一行（分支 / 话术 / 金额口径 / 顺序）⇒ 断言 ① 红；
 * 把实现搬回门面（或复制一份回去）⇒ 断言 ② 红；给某个方法多改一处调用形态 ⇒ 断言 ③ 红。
 * 判别力自证见本类末：在内存里改一个字符 / 把方法体塞回门面源，`bodyMatches` 必须各自判假。</p>
 *
 * <p><b>复算</b>：{@code cd backend/admin-api && ./mvnw -Dtest=OrderLifecycleSliceSourceIdentityTest test}。</p>
 */
@DisplayName("#8191 P2-1d 搬运逐字节一致：生命周期族 15 个方法体原样在 OrderLifecycleService、门面零残留")
class OrderLifecycleSliceSourceIdentityTest {

    private static final Path MAIN = Path.of("src", "main", "java", "com", "migao", "admin");
    private static final Path ORDER_SERVICE = MAIN.resolve("service/OrderService.java");
    private static final Path LIFECYCLE_SERVICE = MAIN.resolve("service/OrderLifecycleService.java");
    private static final String BASELINE_RESOURCE = "/order-lifecycle/OrderService.baseline.txt";

    /** 拆分前门面（2,268 行）的 sha256 —— 基线被改一个字符即红。 */
    private static final String BASELINE_SHA256 =
            "acf0cae156dd37c8a0fab114c0699e0d40b0b40f78663a50b75d7b13b11a564b";
    private static final int BASELINE_LINES = 2268;

    /**
     * 搬走的方法（声明前缀逐字）。顺序 = 搬运清单，不是装饰：漏一个 ⇒ 那族就有一份实现留在门面里，
     * 而「拆分后既有测试仍然绿」不具备发现它的判别力。
     */
    private static final List<String> MOVED = List.of(
            "void updateOrderStatus(",
            "void notifyOrderStatusChanged(",
            "int transitionStatusAtomic(",
            "void confirmPayment(",
            "boolean isProcessingReadyForShip(",
            "void assertProcessingCompletedBeforeShip(",
            "void revertProducingToConfirmed(",
            "void cancelOrder(",
            "void refundOrder(",
            "String resolveShipperName(",
            "void upsertLogistics(",
            "shipWithLogistics(String orderId, String trackingNo, String logisticsCompany) {",
            "shipWithLogistics(String orderId, String trackingNo, String logisticsCompany,",
            "String currentLogisticsCompany(",
            "boolean shipOrderIfApplicable(");

    /**
     * 具名的跨类限定（**白名单**）：搬运时只允许这几处文本差异，且必须逐处兑现。
     *
     * <p>为什么必须具名而不是「忽略空白」：这三处是**唯一**能解释「方法体为什么不是 100% 相同」的东西
     * —— 一旦允许模糊比对，判据就退化成「大致一样」，而「大致一样」抓不到 `!=` 写成 `==`。</p>
     */
    private static final Map<String, Map<String, String>> QUALIFICATIONS = new LinkedHashMap<>();

    static {
        QUALIFICATIONS.put("void cancelOrder(", Map.of(
                "batchStock().reverse(", "orderSharedParts.batchStock().reverse("));
        QUALIFICATIONS.put("void updateOrderStatus(", Map.of(
                "cancelOrder(id, null);", "cancelOrder(id, null, orderSharedParts);"));
        QUALIFICATIONS.put("shipWithLogistics(String orderId, String trackingNo, String logisticsCompany,",
                Map.of("new OrderShipmentOutcome(result, transitioned);",
                        "new OrderService.OrderShipmentOutcome(result, transitioned);"));
    }

    /** 事务注解必须逐字跟着方法走（搬走 5 条，一条不多一条不少）。 */
    private static final List<String> TRANSACTIONAL_METHODS = List.of(
            "void updateOrderStatus(",
            "void confirmPayment(",
            "void cancelOrder(",
            "void refundOrder(",
            "shipWithLogistics(String orderId, String trackingNo, String logisticsCompany,");

    // ────────────────────────────────────────────── 判据 0：基线本身

    @Test
    @DisplayName("基线锚点：入库的拆分前门面 sha256 与行数逐字钉死（基线被改 ⇒ 红）")
    void baselineIsThePreSplitFacade() throws Exception {
        String baseline = baseline();
        assertThat(baseline.split("\n", -1).length - 1)
                .as("基线行数必须是拆分前的 2,268 行（origin/main 实取 `git show origin/main:<path> | wc -l`）")
                .isEqualTo(BASELINE_LINES);
        assertThat(sha256(baseline))
                .as("基线 sha256 被改 ⇒ 「逐字节一致」的参照物不可信（复算：git show origin/main:<path> | shasum -a 256）")
                .isEqualTo(BASELINE_SHA256);
    }

    // ────────────────────────────────────────────── 判据 1/2：逐字节一致 + 门面零残留

    @Test
    @DisplayName("15 个方法体逐字节一致地出现在 OrderLifecycleService，且门面里一处都不许留")
    void everyMovedMethodBodyIsByteIdenticalAndLeavesNoCopyInTheFacade() throws IOException {
        String baseline = baseline();
        String facade = read(ORDER_SERVICE);
        String carrier = read(LIFECYCLE_SERVICE);

        List<String> failures = new ArrayList<>();
        for (String decl : MOVED) {
            if (!bodyMatches(baseline, facade, carrier, decl)) {
                failures.add(decl);
            }
        }
        System.out.println("[READING #8191 P2-1d 搬运] 方法数=" + MOVED.size() + " 不一致=" + failures);
        assertThat(failures)
                .as("这些方法的方法体与新载体不一致（被改写 / 没搬过去 / 门面里还留着一份）")
                .isEmpty();
    }

    @Test
    @DisplayName("具名的跨类限定必须恰好兑现（漏一处 / 多一处都红）")
    void namedQualificationsAreExactlyAsDeclared() throws Exception {
        String baseline = baseline();
        String carrier = read(LIFECYCLE_SERVICE);
        for (Map.Entry<String, Map<String, String>> entry : QUALIFICATIONS.entrySet()) {
            String body = methodBody(carrier, entry.getKey());
            assertThat(body).as("新载体里找不到方法声明：%s", entry.getKey()).isNotEmpty();
            for (Map.Entry<String, String> q : entry.getValue().entrySet()) {
                int count = count(body, q.getValue());
                assertThat(count)
                        .as("具名限定 `%s` 必须**恰好一次**出现在 %s（现取 %d 次）",
                                q.getValue().trim(), entry.getKey(), count)
                        .isEqualTo(1);
                assertThat(body).as("限定后的形态必须是 `%s`", q.getValue()).contains(q.getValue());
                assertThat(body.replace(q.getValue(), ""))
                        .as("原形态 `%s` 不许残留（否则同一句话有两个写法）", q.getKey().trim())
                        .doesNotContain(q.getKey());
            }
        }
        // 反向：不允许出现白名单之外的第二处限定差异 —— 基线侧比对已经覆盖，这里再钉一次「白名单非空」
        assertThat(QUALIFICATIONS).as("白名单被清空 ⇒ 判据变成「忽略所有差异」= 空断言").isNotEmpty();
    }

    @Test
    @DisplayName("5 条 @Transactional（rollbackFor = Exception.class）逐字跟着方法搬走，门面委托一条都不加")
    void transactionalAnnotationsMovedWithTheMethods() throws Exception {
        String facade = read(ORDER_SERVICE);
        String carrier = read(LIFECYCLE_SERVICE);
        String annotation = "@Transactional(rollbackFor = Exception.class)";

        for (String decl : TRANSACTIONAL_METHODS) {
            assertThat(declarationWithAnnotations(carrier, decl))
                    .as("搬走的方法必须带着事务注解（事务边界变化 = 行为变化）：%s", decl)
                    .contains(annotation);
            // issue #8681 第六批：门面的转发已**退休** ⇒ 门面侧这一条从「不许加事务注解」**加强**为
            // 「一处声明都不许有」（转发长回来就是两层嵌套语义，且那时本判据会当场红而不是空转）。
            assertThat(declarationWithAnnotations(facade, decl))
                    .as("门面既不许加事务注解、也不许把这个入口的声明长回来（两层嵌套语义变化）：%s", decl)
                    .isEmpty();
        }
        assertThat(countStandaloneLines(carrier, annotation))
                .as("新载体里独立成行的事务注解必须恰好 5 条（多一条 = 顺手给别人加了事务；"
                        + "javadoc 里的 {@code ...} 引用不算）")
                .isEqualTo(TRANSACTIONAL_METHODS.size());
    }

    // ────────────────────────────────────────────── 判别力自证

    @Test
    @DisplayName("判别力自证：改一个字符 / 把方法体塞回门面 / 撤掉具名限定 ⇒ bodyMatches 各自判假")
    void guardHasDiscriminatingPower() throws Exception {
        String baseline = baseline();
        String facade = read(ORDER_SERVICE);
        String carrier = read(LIFECYCLE_SERVICE);
        String decl = "void cancelOrder(";

        // 对照读数：真语料必须判真
        assertThat(bodyMatches(baseline, facade, carrier, decl))
                .as("真语料必须判真（否则下面三条注入证不出判别力）")
                .isTrue();

        // ① 新载体里改一个字符（话术）
        String mutatedCarrier = carrier.replace("当前状态不允许取消", "当前状态不允许取消!");
        assertThat(mutatedCarrier).as("注入必须真的生效（锚点漂移会让本条变成空断言）").isNotEqualTo(carrier);
        assertThat(bodyMatches(baseline, facade, mutatedCarrier, decl))
                .as("新载体改一个字符 ⇒ 必须判假")
                .isFalse();

        // ② 把同一段方法体塞回门面
        //   🔴 锚点 = **类声明**，不是某个具体方法的签名：issue #8681 第六批把门面的 cancelOrder 转发删掉之后，
        //   按方法签名定位的注入会**静默失配**（replace 不命中）⇒ 把「注入没生效」误读成「判据没牙」。
        //   类声明不会随某个入口退休而消失，且注入后门面里确实多出一份实现 ⇒ 断言仍具判别力。
        String bodyInCarrier = methodBody(carrier, decl);
        String baselineForm = bodyInCarrier.replace("orderSharedParts.batchStock().reverse(", "batchStock().reverse(");
        String launderedFacade = facade.replace("public class OrderService extends ServiceImpl<OrderMapper, Order> {",
                "public class OrderService extends ServiceImpl<OrderMapper, Order> {\n" + baselineForm);
        assertThat(launderedFacade).as("注入必须真的生效").isNotEqualTo(facade);
        assertThat(bodyMatches(baseline, facade, carrier, decl)).isTrue();
        assertThat(bodyMatches(baseline, launderedFacade, carrier, decl))
                .as("门面里复制一份实现 ⇒ 必须判假（两份口径）")
                .isFalse();

        // ③ 撤掉具名限定（把新载体改回基线的原形态）
        String unqualified = carrier.replace("orderSharedParts.batchStock().reverse(", "batchStock().reverse(");
        assertThat(unqualified).as("注入必须真的生效").isNotEqualTo(carrier);
        assertThat(bodyMatches(baseline, facade, unqualified, decl))
                .as("具名限定被撤掉 ⇒ 方法体与基线不再「只差白名单里的那一处」⇒ 必须判假")
                .isFalse();
    }

    // ────────────────────────────────────────────── 解析件

    /**
     * 纯谓词：`decl` 的方法体在基线与新载体里**逐字节一致**（仅允许白名单里的具名限定），
     * 且门面里**不含**该段。
     */
    static boolean bodyMatches(String baseline, String facade, String carrier, String decl) {
        String baselineBody = methodBody(baseline, decl);
        String carrierBody = methodBody(carrier, decl);
        if (baselineBody.isEmpty() || carrierBody.isEmpty()) {
            return false; // fail-closed：取不到方法体不是「通过」
        }
        Map<String, String> quals = QUALIFICATIONS.get(decl);
        String normalized = carrierBody;
        if (quals != null) {
            for (Map.Entry<String, String> q : quals.entrySet()) {
                if (count(normalized, q.getValue()) != 1) {
                    return false;
                }
                String residue = normalized.replace(q.getValue(), "");
                if (residue.contains(q.getKey())) {
                    return false; // 同一句话两个写法（限定没落干净 / 多出一处原形态）
                }
                normalized = normalized.replace(q.getValue(), q.getKey());
            }
        }
        if (!normalized.equals(baselineBody)) {
            return false;
        }
        return facade == null || !facade.contains(baselineBody);
    }

    /**
     * 取名为 {@code decl}（声明前缀）的方法体（含签名，到配对右括号）。找不到 ⇒ 空串。
     *
     * <p>必须区分**声明点**与**调用点**：{@code transitionStatusAtomic} 等在多处被调用，朴素的
     * 「第一次出现」会截到一段无关代码（本仓 {@code OrderPaidAndReceivedAtWriteGuardTest} 记过同款坑）。</p>
     */
    static String methodBody(String src, String decl) {
        int from = 0;
        while (true) {
            int sig = src.indexOf(decl, from);
            if (sig < 0) {
                return "";
            }
            from = sig + 1;
            int open = decl.endsWith("{") ? sig + decl.length() - 1 : src.indexOf('{', sig);
            if (open < 0) {
                return "";
            }
            if (!decl.endsWith("{")) {
                // 声明前缀与左括号之间必须是同一段签名（不是跨方法的巧合）
                String between = src.substring(sig + decl.length(), open);
                if (between.contains(";") || between.contains("}")) {
                    continue;
                }
            }
            int depth = 0;
            for (int i = open; i < src.length(); i++) {
                char c = src.charAt(i);
                if (c == '{') {
                    depth++;
                } else if (c == '}') {
                    depth--;
                    if (depth == 0) {
                        // **只比方法体**（大括号起止）：两条门面入口的签名必然多一个门面实参
                        // （`cancelOrder(id, reason, orderService.sharedParts())` / `updateOrderStatus(..., orderService.sharedParts())`），
                        // 那是**具名**的签名变化（公开签名由接线判据另行钉住），不是实现被改写。
                        return src.substring(open, i + 1);
                    }
                }
            }
            return "";
        }
    }

    /** 取方法声明**及其上方的注解行**（用于判事务注解是否跟着方法走）。 */
    static String declarationWithAnnotations(String src, String decl) {
        int sig = src.indexOf(decl);
        if (sig < 0) {
            return "";
        }
        int lineStart = src.lastIndexOf('\n', sig) + 1;
        StringBuilder head = new StringBuilder();
        int p = lineStart;
        // 向上收集连续的注解行
        while (p > 0) {
            int prevEnd = p - 1;
            int prevStart = src.lastIndexOf('\n', prevEnd - 1) + 1;
            String line = src.substring(prevStart, prevEnd).strip();
            if (!line.startsWith("@")) {
                break;
            }
            head.insert(0, src, prevStart, prevEnd);
            p = prevStart;
        }
        return head.toString();
    }

    /** 数「独立成行（忽略缩进）」出现的次数（注解行专用：注释里提到它不算）。 */
    static int countStandaloneLines(String src, String line) {
        int n = 0;
        for (String raw : src.split("\n", -1)) {
            if (raw.strip().equals(line)) {
                n++;
            }
        }
        return n;
    }

    static int count(String src, String needle) {
        int n = 0;
        int i = src.indexOf(needle);
        while (i >= 0) {
            n++;
            i = src.indexOf(needle, i + needle.length());
        }
        return n;
    }

    private static String baseline() throws IOException {
        try (InputStream in = OrderLifecycleSliceSourceIdentityTest.class
                .getResourceAsStream(BASELINE_RESOURCE)) {
            assertThat(in).as("基线源码必须随判据入库：" + BASELINE_RESOURCE).isNotNull();
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    private static String read(Path path) throws IOException {
        assertThat(path).as("判据的扫描面必须真实存在（路径漂移 ⇒ 判红，不是空跑通过）").exists();
        return Files.readString(path, StandardCharsets.UTF_8);
    }

    private static String sha256(String text) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] bytes = digest.digest(text.getBytes(StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            sb.append(String.format("%02x", b));
        }
        return sb.toString();
    }
}
