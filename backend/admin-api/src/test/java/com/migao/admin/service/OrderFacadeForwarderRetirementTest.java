// case_ids: MC-203
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 门面转发**退休**判据（issue #8681；第一批 + 第二批）：调用方迁到四个新服务之后，被删掉的转发方法
 * 不许以任何形式回来，而且**调用方不许再绕门面**。
 *
 * <p><b>第一批</b>（PR #8682）：{@code existsForCurrentTenant} / {@code resolveOrderId} /
 * {@code isProcessingReadyForShip} / {@code resolveShipperName}；<b>第二批</b>（本批）：
 * {@code getMyOrderPage}（Agent 控制器 C 端「我的订单」端点改直连 {@link OrderQueryService}）。</p>
 *
 * <p><b>为什么需要它（这条判据补的是哪一半）</b>：本批把
 * {@code existsForCurrentTenant} / {@code resolveOrderId}（→ {@link OrderQueryService}）与
 * {@code isProcessingReadyForShip} / {@code resolveShipperName}（→ {@link OrderLifecycleService}）
 * 的调用方改成直接依赖实现点，并删掉门面里的同名转发。删掉之后，原来「门面必须把这一族转出去」的
 * 接线判据就**没有对象**了 ⇒ 若只是把它们删掉，这个方向就变成**无人看管**：任何人把转发加回来、
 * 或让某个调用方重新走门面，都不会有东西变红。本类就是补上这一半。</p>
 *
 * <p><b>它判两件事（都在载体集合上判，不在某个单点上判）</b>：</p>
 * <ol>
 *   <li><b>退休面</b>：门面里不再有这 5 个方法的声明；{@code src/main} 里**没有任何**调用是经门面变量
 *       （{@code orderService.<方法>(}）走的；</li>
 *   <li><b>接线面</b>：实现点仍声明它们（防止「两边都没了」的恒绿），且**具名的消费方**逐字调用实现点
 *       —— 消费方或调用形态被改回去 ⇒ 当场红并具名。</li>
 * </ol>
 *
 * <p><b>红证方向（判别力自证内建，见末例）</b>：把任一转发方法塞回门面源 ⇒「退休面」判假；
 * 把任一消费方的调用改回门面变量 ⇒「接线面」判假。两个谓词都在内存语料上各注入一次，
 * 保证它们不是恒真/恒假。</p>
 *
 * <p><b>复算</b>：{@code cd backend/admin-api && ./mvnw -Dtest=OrderFacadeForwarderRetirementTest test}。</p>
 */
@DisplayName("#8681 P2-1e 门面转发退休：转发不许回来、调用方不许再绕门面")
class OrderFacadeForwarderRetirementTest {

    private static final Path MAIN = Path.of("src", "main", "java", "com", "migao", "admin");
    private static final Path ORDER_SERVICE = MAIN.resolve("service").resolve("OrderService.java");
    private static final Path QUERY_SERVICE = MAIN.resolve("service").resolve("OrderQueryService.java");
    private static final Path LIFECYCLE_SERVICE = MAIN.resolve("service").resolve("OrderLifecycleService.java");

    /**
     * 本批退休的转发：方法名 → 声明签名（逐字）+ 老服务实现点必在的文件 + 消费方（文件 → 必须出现的调用串）。
     *
     * <p>消费方清单是**具名白名单**而不是「扫到就算」：新增调用方时它会提醒你把这里补上（漏登记 = 红），
     * 这也是「一处行为改动背后有多个登记面」里本单该管的那一格。</p>
     */
    private static final Map<String, Retired> RETIRED = new LinkedHashMap<>();

    static {
        RETIRED.put("existsForCurrentTenant", new Retired(
                "public boolean existsForCurrentTenant(String id)",
                "security", "TenantResourceOwnership.java",
                "orderQueryService.existsForCurrentTenant("));
        RETIRED.put("resolveOrderId", new Retired(
                "public AgentOrderResolveResponse resolveOrderId(String keyword, Long tenantId)",
                "controller/agent", "AgentOrderController.java",
                "orderQueryService.resolveOrderId("));
        RETIRED.put("isProcessingReadyForShip", new Retired(
                "public boolean isProcessingReadyForShip(Order order)",
                "service", "ProductionTodoService.java",
                "orderLifecycleService.isProcessingReadyForShip("));
        RETIRED.put("resolveShipperName", new Retired(
                "public String resolveShipperName(String provided)",
                "controller", "OrderController.java",
                "orderLifecycleService.resolveShipperName("));
        // 第二批（issue #8681，P2-1e 第二批）：C 端「我的订单」端点改直连实现点。
        // 声明锚点取「返回类型 + 方法名 + 左括号」而不是整行：门面里这个签名是**跨行**的，
        // 整行锚点会被换行/缩进漂移误伤；而调用形态（`orderService.getMyOrderPage(`）不含返回类型 ⇒
        // 不会被调用串误判成声明。
        RETIRED.put("getMyOrderPage", new Retired(
                "PageResponse<OrderListResponse> getMyOrderPage(",
                "controller/agent", "AgentOrderController.java",
                "orderQueryService.getMyOrderPage("));
    }

    /**
     * 生命周期族搬走后**失去调用方**的私有死委托（issue #8681，P2-1e 顺带清理）：
     * 它们只转发、且门面里已无任何调用点 ⇒ 留着就是「看起来还在用」的假接线。
     */
    private static final List<String> DEAD_PRIVATE_FORWARDERS = List.of(
            "private void validateStockSufficient(Order order)",
            "private BigDecimal effectiveActualAmount(Order order)",
            "private void recordFinanceTransaction(Order order, String type, String remark)",
            "private void recordFinanceTransaction(Order order, BigDecimal amount, String type, String remark)",
            "private void deductStockAndIncreaseSales(String orderId)",
            "private void restoreStockAndDecreaseSales(String orderId)");

    private record Retired(String declaration, String consumerDir, String consumerFile, String consumerCall) {
    }

    // ──────────────────────────────────────────── 判据 0：扫描面非空（fail-closed）

    @Test
    @DisplayName("扫描面自证：门面 / 两个实现点 / 四个消费方文件都必须真实存在（缺一个 ⇒ 红，不是跳过）")
    void scanSurfaceExists() {
        for (Path path : List.of(ORDER_SERVICE, QUERY_SERVICE, LIFECYCLE_SERVICE)) {
            assertThat(Files.exists(path)).as("判据的载体必须真实存在（路径漂移不得静默跳过）: %s", path).isTrue();
        }
        for (Retired retired : RETIRED.values()) {
            Path consumer = MAIN.resolve(retired.consumerDir()).resolve(retired.consumerFile());
            assertThat(Files.exists(consumer)).as("具名消费方必须真实存在: %s", consumer).isTrue();
        }
        assertThat(RETIRED).as("退休清单被清空 ⇒ 本判据退化成空断言").hasSize(5);
        assertThat(DEAD_PRIVATE_FORWARDERS).as("死委托清单被清空 ⇒ 本判据退化成空断言").hasSize(6);
    }

    // ──────────────────────────────────────────── 判据 1：退休面（门面 + 全 main）

    @Test
    @DisplayName("门面里不许再有这 5 个转发方法的声明（加回来 ⇒ 具名红）")
    void facadeNoLongerDeclaresTheRetiredForwarders() throws IOException {
        String facade = Files.readString(ORDER_SERVICE, StandardCharsets.UTF_8);

        List<String> back = RETIRED.entrySet().stream()
                .filter(e -> declaresMethod(facade, e.getValue().declaration()))
                .map(Map.Entry::getKey)
                .sorted()
                .toList();

        assertThat(back).as("这些转发方法又长回门面里了（调用方应直接依赖实现点）: %s", back).isEmpty();
    }

    @Test
    @DisplayName("私有死委托不许长回来（它们已无调用点，留着 = 假接线）")
    void deadPrivateForwardersStayRetired() throws IOException {
        String facade = Files.readString(ORDER_SERVICE, StandardCharsets.UTF_8);

        List<String> back = DEAD_PRIVATE_FORWARDERS.stream()
                .filter(decl -> facade.contains(decl))
                .toList();

        assertThat(back).as("这些私有死委托又出现了（门面里没有调用方，只转发）: %s", back).isEmpty();
    }

    @Test
    @DisplayName("全 main 源码里零处「经门面变量调用这 5 个方法」（谁改回门面 ⇒ 具名红）")
    void nobodyCallsTheRetiredMethodsThroughTheFacade() throws IOException {
        Map<String, List<String>> hits = new LinkedHashMap<>();
        for (Map.Entry<String, Retired> entry : RETIRED.entrySet()) {
            String needle = "orderService." + entry.getKey() + "(";
            hits.put(needle, filesContaining(needle));
        }

        List<String> violations = hits.entrySet().stream()
                .filter(e -> !e.getValue().isEmpty())
                .map(e -> e.getKey() + " @ " + e.getValue())
                .toList();

        assertThat(violations).as("这些调用又绕回门面了（应直接调用实现点）: %s", violations).isEmpty();
    }

    // ──────────────────────────────────────────── 判据 2：接线面（实现点 + 具名消费方）

    @Test
    @DisplayName("实现点仍声明这 5 个方法（两边都没了 ⇒ 本判据会恒绿，所以先钉住这一侧）")
    void implementationSitesStillDeclareThem() throws IOException {
        String query = Files.readString(QUERY_SERVICE, StandardCharsets.UTF_8);
        String lifecycle = Files.readString(LIFECYCLE_SERVICE, StandardCharsets.UTF_8);

        assertThat(declaresMethod(query, RETIRED.get("existsForCurrentTenant").declaration()))
                .as("OrderQueryService 必须仍声明 existsForCurrentTenant（实现点不见了 ⇒ 判定会空跑）").isTrue();
        assertThat(declaresMethod(query, RETIRED.get("resolveOrderId").declaration()))
                .as("OrderQueryService 必须仍声明 resolveOrderId").isTrue();
        assertThat(declaresMethod(lifecycle, RETIRED.get("isProcessingReadyForShip").declaration()))
                .as("OrderLifecycleService 必须仍声明 isProcessingReadyForShip").isTrue();
        assertThat(declaresMethod(lifecycle, RETIRED.get("resolveShipperName").declaration()))
                .as("OrderLifecycleService 必须仍声明 resolveShipperName").isTrue();
        assertThat(declaresMethod(query, RETIRED.get("getMyOrderPage").declaration()))
                .as("OrderQueryService 必须仍声明 getMyOrderPage（第二批：实现点不见了 ⇒ 判定会空跑）").isTrue();
    }

    @Test
    @DisplayName("五个具名消费方逐字调用实现点（绕门面 / 改调用形态 ⇒ 具名红）")
    void namedConsumersCallTheImplementationSites() throws IOException {
        List<String> violations = new ArrayList<>();
        for (Map.Entry<String, Retired> entry : RETIRED.entrySet()) {
            Retired retired = entry.getValue();
            Path consumer = MAIN.resolve(retired.consumerDir()).resolve(retired.consumerFile());
            if (!Files.readString(consumer, StandardCharsets.UTF_8).contains(retired.consumerCall())) {
                violations.add(retired.consumerFile() + " 里找不到 `" + retired.consumerCall() + "`");
            }
        }

        assertThat(violations).as("这些消费方没有直连实现点（被改回门面 / 方法被改名）: %s", violations).isEmpty();
    }

    // ──────────────────────────────────────────── 判据 3：判别力自证（内存注入）

    @Test
    @DisplayName("🔴 判别力自证：内存里把转发塞回门面 / 把消费方改回门面 ⇒ 两个谓词各自判假")
    void guardHasDiscriminatingPower() {
        String facade = "public class OrderService {\n    public String resolveShipperName(String provided) { }\n}";
        assertThat(declaresMethod(facade, RETIRED.get("resolveShipperName").declaration()))
                .as("把转发塞回门面源 ⇒ 「已退休」必须判假（否则判据是恒真的空断言）").isTrue();
        assertThat(declaresMethod("public class OrderService {\n}", RETIRED.get("resolveShipperName").declaration()))
                .as("真语料形态（没有该方法）⇒ 必须判假").isFalse();

        // 第二批新增的那条是**跨行签名** ⇒ 锚点必须也能命中跨行形态（否则「加回来」不会被判红）
        String multilineFacade = "public class OrderService {\n"
                + "    public PageResponse<OrderListResponse> getMyOrderPage(long page, long size, String status,\n"
                + "                                                          Long tenantId, String userId, String userPhone) { }\n}";
        assertThat(declaresMethod(multilineFacade, RETIRED.get("getMyOrderPage").declaration()))
                .as("跨行声明的形态也必须判真（第二批的锚点是「返回类型 + 方法名 + 左括号」）").isTrue();

        // 反形态：方法名出现在**注释**里不算声明（否则别人写一句说明就把判据喂红了）
        String commented = "/** 见 OrderService.resolveShipperName 的沿革 */\npublic class OrderService {\n}";
        assertThat(declaresMethod(commented, RETIRED.get("resolveShipperName").declaration()))
                .as("注释里的同名文本不算声明").isFalse();

        String consumerThroughFacade = "String name = orderService.resolveShipperName(provided);";
        assertThat(consumerThroughFacade.contains("orderService.resolveShipperName("))
                .as("消费方绕门面的形态必须被判真（这样上一条「零处」才有判别力）").isTrue();
        String consumerDirect = "String name = orderLifecycleService.resolveShipperName(provided);";
        assertThat(consumerDirect.contains("orderService.resolveShipperName("))
                .as("直连实现点的形态必须被判假").isFalse();
    }

    // ──────────────────────────────────────────── 解析件

    /**
     * 源码里是否有该方法**声明**（不是调用、也不是注释里提一句）。
     *
     * <p>判据 = 逐字声明串出现在**剥掉注释后**的源码里。剥注释是必需的：本仓习惯在 javadoc 里写
     * 「见 {@code OrderService.xxx}」这类引用，不剥就会把**说明**当成**声明**（判据被自己的文案喂红/喂绿，
     * 同 {@code migao-dev-flow} §17.3 的反面形态）。</p>
     */
    static boolean declaresMethod(String source, String declaration) {
        return stripComments(source).contains(declaration);
    }

    /** 剥掉行注释与块注释（保留字符串字面量里的内容 —— 本判据扫的是声明形态，不判字符串）。 */
    static String stripComments(String src) {
        StringBuilder out = new StringBuilder(src.length());
        boolean inBlock = false;
        boolean inLine = false;
        for (int i = 0; i < src.length(); i++) {
            char c = src.charAt(i);
            char next = i + 1 < src.length() ? src.charAt(i + 1) : '\0';
            if (inBlock) {
                if (c == '*' && next == '/') {
                    inBlock = false;
                    i++;
                }
                continue;
            }
            if (inLine) {
                if (c == '\n') {
                    inLine = false;
                    out.append(c);
                }
                continue;
            }
            if (c == '/' && next == '*') {
                inBlock = true;
                i++;
                continue;
            }
            if (c == '/' && next == '/') {
                inLine = true;
                i++;
                continue;
            }
            out.append(c);
        }
        return out.toString();
    }

    /** 全 {@code src/main/java} 语料里，命中该字面量（剥注释后）的**仓库相对路径**集合。 */
    private static List<String> filesContaining(String needle) throws IOException {
        Path root = Path.of("src", "main", "java");
        try (Stream<Path> stream = Files.walk(root)) {
            return stream.filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> {
                        try {
                            return stripComments(Files.readString(p, StandardCharsets.UTF_8)).contains(needle);
                        } catch (IOException e) {
                            throw new IllegalStateException("读取失败： " + p, e);
                        }
                    })
                    .map(p -> root.relativize(p).toString())
                    .sorted()
                    .toList();
        }
    }

}
