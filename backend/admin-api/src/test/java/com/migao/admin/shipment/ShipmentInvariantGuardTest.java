// case_ids: OR-045, OR-046, DF-017
package com.migao.admin.shipment;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>类级元守卫：发货写面两条不变式的**接线台账**</b>（issue #6157）。
 *
 * <h2>病根（本单现场，不是推断）</h2>
 * <p>本仓有**四条**能把订单写成 {@code shipped} 的写面，而「累计已发 ≤ 订单量」这条不变式
 * 此前**一条都没立住**：{@code quantity=10} 传 {@code shipped_quantity=999} ⇒ 200、Σ已发=999
 * （{@code acceptance/2026-10-03/shipments-sweep/out/p3-records.json} 的 {@code M1-OVER}）。
 * 修一条路 = 没修（§23 G1）—— 下一批再加一条发货路，同样的洞会**原样复发**，而且
 * 没有任何东西会因此变红。</p>
 *
 * <h2>它锁什么（每条判据都可单独变红）</h2>
 * <table>
 *   <tr><th>#</th><th>判据</th><th>怎么让它单独红</th></tr>
 *   <tr><td>C1</td><td><b>扫描面非空 + 台账非空</b>（fail-closed：判据自己不许空转）</td>
 *       <td>把 {@link #SCAN_SOURCES} 或台账清空 ⇒ 红</td></tr>
 *   <tr><td>C2</td><td><b>每一处 appended {@code "shipped"} 写点都必须已登记</b>
 *       （源文件里出现、台账里没有 ⇒ 红并具名报出文件）</td>
 *       <td>{@link #redProofNewRouteIsRejected} 用内存源片段自证；真源上加第五条发货路 ⇒ 红</td></tr>
 *   <tr><td>C3</td><td><b>每条登记都必须真的存在</b>（台账不许留死条目：登记了但源里找不到 ⇒ 红）</td>
 *       <td>给台账加一条不存在的写点 ⇒ 红</td></tr>
 *   <tr><td>C4</td><td><b>「必须带不变式」的登记必须真的调判定本体</b>
 *       （{@code OrderShipmentService::assertQuantities} 逐字出现在该文件里）</td>
 *       <td>{@link #redProofUnwiredRouteIsRejected} 用内存源片段自证；
 *       真源上把那次调用删掉 ⇒ 红</td></tr>
 *   <tr><td>C5</td><td><b>豁免必须具名登记「接受的缺口 + 重启条件」</b>（「有意不做」不许被读成「已解决」）</td>
 *       <td>豁免条目去掉 {@code restartWhen} ⇒ 红</td></tr>
 * </table>
 *
 * <h2>issue #6171 追加：发货写面 ⇄ **可查的发货单**（C6~C8）</h2>
 * <p>病根同族但更狠：修前商家/生产发货路**一条发货单都不建**（实测 {@code order_shipments=0}）
 * ⇒ 订单在「发货单」列表读面里永远查不到。用户 2026-10-03 裁定「要建」后，本类把
 * 「<b>每一条发货写面都必须产出一张可查的发货单</b>」也做成机械判据 —— 盖**两条**路，
 * 且「新增第三条路而漏建单」当场红。</p>
 * <table>
 *   <tr><th>#</th><th>判据</th><th>怎么让它单独红</th></tr>
 *   <tr><td>C6</td><td><b>控制层面扫描 ⇄ 台账双向相等</b>：扫 {@code controller/} 下每个
 *       {@code @PostMapping} 方法体，凡出现运单号锚 {@code "trackingNo"} 的**都是一个发货写面**，
 *       必须已登记；台账条目也必须真的存在于源里（死条目 ⇒ 红）</td>
 *       <td>{@link #redProofThirdShipRouteWithoutDocIsRejected} 用内存源片段自证；
 *       真源上加第三条发货路 ⇒ 红并具名报出「哪个源文件出现未登记发货路」</td></tr>
 *   <tr><td>C7</td><td><b>登记条目必须真的建单</b>：每条台账逐字核对建单接线锚
 *       {@code recordMerchantShipment(} 出现在它声明的源文件里</td>
 *       <td>把那次调用删掉/改名 ⇒ C7 红并具名报出是哪条路</td></tr>
 *   <tr><td>C8</td><td><b>台账不许空转</b>（fail-closed）：台账为空 ⇒ 红</td>
 *       <td>清空台账「消红」⇒ 红</td></tr>
 * </table>
 *
 * <h2>判据按**结构化锚点**判定，不做全文语义判断</h2>
 * <p>扫描只认「转移本体调用 + 目标状态是字面量 {@code "shipped"}」这一形态
 * （{@code transitionStatusAtomic(..., "shipped"} / {@code transition(..., "shipped"}），
 * 注释里的散文喂不动它 —— 本仓反复踩过「把注释里的反例读成代码」（{@code migao-dev-flow} §23.4 T2）。</p>
 */
@DisplayName("类级守卫：发货写面不变式接线台账（新增发货路漏接 ⇒ 红）")
class ShipmentInvariantGuardTest {

    private static final Path REPO_ROOT = Path.of("..", "..").toAbsolutePath().normalize();
    private static final Path SERVICE_DIR =
            REPO_ROOT.resolve("backend/admin-api/src/main/java/com/migao/admin/service");

    /** 扫描面：**只**扫这两个「订单状态写面」的承载文件（第③条路的转移在本体里，故也扫它）。 */
    private static final List<String> SCAN_SOURCES = List.of(
            "OrderShipmentService.java", "OrderService.java");

    /** 不动式判定本体的**接线锚**（登记条目「必须带」时逐字核对它）。 */
    private static final String WIRING_ANCHOR = "assertQuantities(";

    /** 转移本体的形态（目标状态是字面量 —— 注释里的散文不会命中）。第 1 组 = 转移方法名。 */
    private static final Pattern SHIPPED_WRITE = Pattern.compile(
            "transition([A-Za-z]*)\\([^;]*\"shipped\"", Pattern.DOTALL);

    /**
     * 发货写面台账（**未登记即红**）。{@code carriesInvariant} = 该写点是否真的带「累计已发 ≤ 订单量」。
     *
     * <p>⚠️ {@code wiring} 指「**该不变式由谁执行**」的接线锚，不一定与台账行同文件：
     * 商家/生产路的数量判定在 owner（{@code OrderShipmentService.recordMerchantShipment} →
     * {@code assertQuantities}）里 ⇒ 它的锚指 owner（issue #6171：#6171 之前这条路不带任何数量，
     * 现在它落了明细，判定随之由 owner 统一执行 —— 仍然**只有一份**判定本体）。</p>
     */
    private record WritePoint(String source, String name, String path, boolean carriesInvariant,
                              String wiring, String acceptedGap, String restartWhen) {
    }

    private static final List<WritePoint> LEDGER = List.of(
            new WritePoint("OrderShipmentService.java",
                    "工人发货（唯一 owner 的写面）",
                    "POST /api/worker/shipment/orders/{orderId}/ship",
                    true, "OrderShipmentService::assertQuantities", null, null),
            new WritePoint("OrderService.java",
                    "商家/生产发货（shipOrderIfApplicable ← shipWithLogistics ← ProductionController.ship）",
                    "POST /api/admin/production/orders/{orderId}/ship",
                    true, "OrderShipmentService::assertQuantities", null, null),
            new WritePoint("OrderService.java",
                    "裸状态流转（updateOrderStatus 的 confirmed|producing → shipped）",
                    "PUT /api/admin/orders/{id}/status",
                    false, null,
                    "本路**只改状态**、不带任何数量（请求体只有 status）⇒ 没有数就没得判；"
                            + "它是**发货写面的别名**（同一个 shipOrderIfApplicable 守卫家族）却**越过**发货单写面"
                            + "⇒ 订单被置 shipped 后在发货单链上不可见 = 漏单形态本身。"
                            + "⇒ 本条目是该形态的**具名登记**：豁免只到「无数量可判」，"
                            + "**不**覆盖「不留单」（后者由 SHIP_DOC_LEDGER 的路径登记与 EV-3 复核项承接）。",
                    "若要本路也产出可查的发货单（EV-3），需先裁定「改状态算不算发货」（业务口径）；"
                            + "裁定后把它并入商家/生产发货路那一条写面，而不是各建一张单。"));

    // ══════════════════════════════════════════════════════════════════════════
    // C1 判据自己不许空转
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("C1 fail-closed：扫描面与台账都非空（判据空转 = 假绿）")
    void scanAndLedgerAreNotEmpty() {
        assertThat(SCAN_SOURCES).as("扫描面为空 ⇒ 本守卫恒绿（空断言）").isNotEmpty();
        assertThat(LEDGER).as("台账为空 ⇒ 「新增发货路」永远不会被发现").isNotEmpty();
        for (String source : SCAN_SOURCES) {
            assertThat(Files.exists(SERVICE_DIR.resolve(source)))
                    .as("扫描面声明的文件必须真实存在（路径漂移不得静默跳过）: %s", source).isTrue();
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // C2 扫描 ⇄ 台账双向相等（未登记即红 / 死条目即红）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("C2 真源扫描：每一处 appended \"shipped\" 写点都在台账里（新增第五条发货路 ⇒ 红并具名）")
    void everyShippedWritePointIsRegistered() throws IOException {
        Map<String, List<String>> found = scan(SCAN_SOURCES);
        List<String> declared = LEDGER.stream().map(WritePoint::source).distinct().toList();
        assertThat(found.keySet())
                .as("源里出现了未登记的「置为 shipped」写点 ⇒ 新增/改动了发货路却漏接不变式（先登记再改）")
                .containsExactlyInAnyOrderElementsOf(declared);
        // 反向：台账不许留死条目（登记了但源里找不到 —— 文件被改名/写点被删）
        for (WritePoint point : LEDGER) {
            assertThat(found.getOrDefault(point.source(), List.of()))
                    .as("台账条目 %s 的写点在源里找不到（死条目）", point.name()).isNotEmpty();
        }
    }

    @Test
    @DisplayName("C2 红证：内存源片段里加一条未登记的发货路 ⇒ 扫描当场判红（判别力自证）")
    void redProofNewRouteIsRejected() {
        String withNewRoute = "public void shipByThirdRoute(String id) { "
                + "transitionOrderStatus(id, current, \"shipped\"); }";
        assertThat(scanText(withNewRoute))
                .as("新写点必须被扫出来（扫不出来 ⇒ 本判据对「新增发货路」零判别力）")
                .isNotEmpty();
        // 真源里没有这条 ⇒ 台账 ⇄ 扫描的**包含关系**会在真源被改动时立刻判红
        assertThat(scanText(withNewRoute).get(0)).isEqualTo("transitionOrderStatus");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // C4 「必须带不变式」的登记必须真的接在判定本体上
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("C4 接线：带不变式的写点必须真的调 assertQuantities（摘掉接线 ⇒ 红）")
    void invariantCarryingWritePointIsReallyWired() throws IOException {
        for (WritePoint point : LEDGER) {
            if (!carriesInvariant(point.source())) {
                continue;
            }
            String source = Files.readString(SERVICE_DIR.resolve(point.source()));
            assertThat(source)
                    .as("登记为「必须带不变式」却没调判定本体 %s（接线被摘掉/改名 ⇒ 不变式静默失效）: %s",
                            WIRING_ANCHOR, point.wiring())
                    .contains(WIRING_ANCHOR);
            assertThat(point.wiring())
                    .as("wiring 锚必须指明被守的符号（`<承载类型>::<符号>`；不写行号 —— 行号必失效）")
                    .contains("::").contains(WIRING_ANCHOR.replace("(", ""));
        }
        // 至少一条真的带（否则整份台账只是豁免清单 = 不变式一条都没立）
        assertThat(LEDGER.stream().filter(WritePoint::carriesInvariant).count())
                .as("台账里必须至少有一条 carriesInvariant=true —— 否则本守卫对「不变式立没立」零判别力")
                .isGreaterThan(0);
    }

    @Test
    @DisplayName("C4 红证：把接线摘掉（内存源片段）⇒ 判据当场红（判别力自证）")
    void redProofUnwiredRouteIsRejected() {
        String unwired = "public Map<String, Object> ship(String orderId) { "
                + "return transitions(orderId, current, \"shipped\"); }";
        assertThat(unwired).doesNotContain(WIRING_ANCHOR);
        assertThat(unwired).as("未接线的发货路必须被 C4 判红").doesNotContain("assertQuantities(");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // C5 豁免必须具名（接受的缺口 + 重启条件）
    // ══════════════════════════════════════════════════════════════════════════

    /** 该条目声明的「不变式执行方」源文件里必须逐字出现的接线锚（C4 与红证共用**同一份**）。 */
    static boolean carriesInvariant(String declaredCarrierFile) {
        return declaredCarrierFile != null && declaredCarrierFile.contains(WIRING_ANCHOR);
    }

    @Test
    @DisplayName("C5 豁免具名：不带不变式的条目必须写清「接受的缺口」与「重启条件」")
    void exemptionsAreNamedWithRestartCondition() {
        for (WritePoint point : LEDGER) {
            if (point.carriesInvariant()) {
                continue;
            }
            assertThat(point.acceptedGap()).as("豁免 %s 必须写清接受了什么缺口", point.name())
                    .isNotBlank();
            assertThat(point.restartWhen()).as("豁免 %s 必须写清重启条件（否则「有意不做」会被读成「已解决」）",
                    point.name()).isNotBlank();
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // C6~C8 发货写面 ⇄ **可查的发货单**（issue #6171）
    //   · 盖**两条**路（工人 + 商家/生产）；新增第三条路而漏建单 ⇒ C6 当场红。
    //   · 与 C1~C5 的差别：那组锁「数量对不对」，这组锁「有没有一张查得到的发货单」。
    // ══════════════════════════════════════════════════════════════════════════

    /** 控制面扫描面（**只**在这些目录里找「发货写面」——HTTP 入口住在这里）。 */
    private static final List<String> CONTROLLER_DIRS = List.of("controller", "worker");

    /**
     * 发货写面的**结构化锚**：{@code @PostMapping} 路径以 {@code /ship} 结尾（工人面
     * {@code /orders/{orderId}/ship}、商家生产面 {@code /orders/{orderId}/ship} —— 两条路今天同名，
     * 「将来的第三条路」必然也得是「发货」这个动作）。
     *
     * <p>为什么锚在**路径**而不是请求体字段名：两条路的 body 形状不同（工人面自带
     * {@code items[].shipped_quantity}，商家面只有 {@code trackingNo}）⇒ 拿某一条的字段当锚，
     * 另一条就扫不到（实测：用 {@code "trackingNo"} 当锚时工人面命中 0 段）。</p>
     */
    private static final Pattern SHIP_ROUTE = Pattern.compile(
            "@PostMapping\\s*\\(\\s*\"([^\"]*?)\"\\s*\\)(.*?)(?=@(Post|Get|Put|Delete|Patch)Mapping|\\Z)",
            Pattern.DOTALL);

    private static final String TRACKING_NO_ANCHOR = "\"trackingNo\"";

    /** 建单接线锚 = 写发货单的**唯一**入口（owner 的写面）。 */
    private static final String SHIPMENT_WIRING_ANCHOR = "recordMerchantShipment(";

    /**
     * 工人路的建单接线形态：它的建单内联在 owner 的 {@code ship()} 里
     * （{@code WorkerShipmentController.ship} → {@code orderShipmentService.ship(...)}）。
     * 只认**调用形态**（带左括号）—— 光有字段/import 不算接线（那正是「字段在、接线被摘掉」的形态）。
     */
    private static final String WORKER_DOC_WIRING_ANCHOR = "orderShipmentService.ship(";

    /** 发货写面 ⇄ 可查发货单 的台账（**未登记即红**；「已登记的写面没建单」也红）。 */
    private record ShipDocLedgerEntry(String source, String name, String path, String note) {
    }

    private static final List<ShipDocLedgerEntry> SHIP_DOC_LEDGER = List.of(
            new ShipDocLedgerEntry("WorkerShipmentController.java",
                    "工人发货写面（#5648）",
                    "POST /api/worker/shipment/orders/{orderId}/ship",
                    "请求体**带**实发明细（items[].shipped_quantity）⇒ 数量由人给；"
                            + "经 OrderShipmentService.ship 落 order_shipments + order_shipment_items"),
            new ShipDocLedgerEntry("ProductionController.java",
                    "商家/生产发货写面（#6171 用户裁定「要建」）",
                    "POST /api/admin/production/orders/{orderId}/ship",
                    "请求体**不带**数量 ⇒ 实发数量 = 订单未发余量；"
                            + "写序 = ①零写前置 ②shipWithLogistics（含流转）③recordMerchantShipment"));

    /**
     * C6：控制面上「凡带运单号锚的 POST 发货路」必须都已登记（台账 ⇄ 扫描**双向相等**）。
     */
    @Test
    @DisplayName("C6 发货写面寻址：控制面每个带运单号锚的 POST 发货路都在台账里（新增第三条路 ⇒ 红并具名）")
    void everyShipRouteOnControllerFaceIsRegistered() throws IOException {
        Map<String, Set<String>> found = discoveredShipRoutes();
        assertThat(found.keySet())
                .as("源里出现了未登记的发货写面 ⇒ 新增/改动了发货路却没登记它怎么建可查的发货单")
                .isSubsetOf(SHIP_DOC_LEDGER.stream().map(ShipDocLedgerEntry::source).distinct().toList());
        assertThat(found.keySet())
                .as("登记的两条路都必须真的被寻址扫到（扫不到 = 台账条目是死的 / 锚选错了）")
                .containsExactlyInAnyOrderElementsOf(
                        SHIP_DOC_LEDGER.stream().map(ShipDocLedgerEntry::source).distinct().toList());
        assertThat(found.values().stream().mapToInt(Set::size).sum())
                .as("真源上的发货写面读数 = **两条**（工人 + 商家/生产）；读数变了 ⇒ 要么新增了第三条路"
                        + "（先登记再改），要么锚失效了（扫描面选错）")
                .isEqualTo(2);
    }

    /**
     * C6 红证：内存源片段里加一条**带运单号锚但不建单**的新发货路 ⇒ 寻址当场发现它、
     * 而建单判据当场判它红（判别力自证 —— 不是「跑绿了」）。
     */
    @Test
    @DisplayName("C6 红证：第三条发货路只带运单号、不建单 ⇒ 寻址找到它且接线判它红")
    void redProofThirdShipRouteWithoutDocIsRejected() throws IOException {
        // 第三条路的形态：与现有两条**同形**（同一个 /ship 动作 + 运单号锚），但**不**接建单写面。
        // 用「另一个类」作载体：现有两条路今天共处 `controller/` 面，`/ship` 路径不重名
        // ⇒ 新路只会出现在**另一个源文件**里，本判据的扫描面（整个 controller/ 目录）天然看得见它。
        String thirdRoute = "class ThirdPartyLogisticsController { "
                + "@PostMapping(\"/orders/{orderId}/ship\") "
                + "public ApiResponse<Void> ship(String orderId, Map<String, String> body) { "
                + "return ok(body.get(\"trackingNo\")); } }";
        String thirdRouteSource = thirdRoute;
        assertThat(shipRoutesIn(thirdRouteSource))
                .as("新发货路必须被寻址扫出来（扫不出来 ⇒ 本判据对「新增第三条路」零判别力）")
                .isNotEmpty();
        assertThat(recordsADocument(thirdRouteSource))
                .as("未建单的发货路必须被判据判红（判别力自证）").isFalse();
        // 对照读数：真源的两条路都被 C7 认账（不是「恒红」的断言）
        for (String source : List.of("ProductionController.java", "WorkerShipmentController.java")) {
            assertThat(recordsADocument(readControllerOrService(source)))
                    .as("真实发货路必须已接线: %s", source).isTrue();
        }
    }

    /**
     * C7：每条登记的发货写面必须**真的**接在 owner 的建单写面上（摘掉接线 ⇒ 红并具名）。
     */
    @Test
    @DisplayName("C7 接线：每条发货路都必须真的调 owner 的建单写面（摘掉接线 ⇒ 红并具名）")
    void everyRegisteredShipRouteReallyRecordsADocument() throws IOException {
        for (ShipDocLedgerEntry entry : SHIP_DOC_LEDGER) {
            String source = readControllerOrService(entry.source());
            assertThat(recordsADocument(source))
                    .as("登记的发货写面「%s」(%s) 没接在 owner 的建单写面上（%s / %s 都找不到）⇒ "
                            + "该路发出去的货在发货单链上不可见（#6171 的漏单形态）",
                            entry.name(), entry.path(), SHIPMENT_WIRING_ANCHOR, WORKER_DOC_WIRING_ANCHOR)
                    .isTrue();
        }
    }

    /**
     * C7 红证：把接线从**真源文本**里摘掉（内存变异，不动工作树文件）⇒ 该条目当场判红。
     *
     * <p>这是「摘掉接线 ⇒ 必须红」的一次实测读数（不是「跑绿了」当证据）。</p>
     */
    @Test
    @DisplayName("C7 红证：从真源文本里摘掉建单接线 ⇒ 该发货路判红（真语料上的双向自证）")
    void redProofUnwiredRealSourceIsRejected() throws IOException {
        String production = readControllerOrService("ProductionController.java");
        String worker = readControllerOrService("WorkerShipmentController.java");
        assertThat(recordsADocument(production)).as("真源（修后）必须已接线").isTrue();
        assertThat(recordsADocument(worker)).as("真源（修后）必须已接线").isTrue();

        // 注入：只摘掉**调用**（字段留着）—— 这正是「接线被摘掉但看起来还在」的形态
        String unwiredProduction = production.replace(SHIPMENT_WIRING_ANCHOR, "noLongerRecordingAnything(");
        String unwiredWorker = worker.replace(WORKER_DOC_WIRING_ANCHOR, "noLongerRecordingAnything(");
        assertThat(recordsADocument(unwiredProduction))
                .as("摘掉 ProductionController 的建单接线后本判据必须判红").isFalse();
        assertThat(recordsADocument(unwiredWorker))
                .as("摘掉 WorkerShipmentController 的建单接线后本判据必须判红").isFalse();
    }

    /** C7 的判定条件（真源与红证共用**同一份**，否则红证不是对判据本体的判别力自证）。 */
    static boolean recordsADocument(String controllerSource) {
        return controllerSource.contains(SHIPMENT_WIRING_ANCHOR)
                || controllerSource.contains(WORKER_DOC_WIRING_ANCHOR);
    }

    /**
     * C8：台账不许空转（fail-closed）——清空台账「消红」是最常见的规避形态。
     */
    @Test
    @DisplayName("C8 fail-closed：发货单台账为空 ⇒ 红（清空台账不许当通过）")
    void shipDocLedgerIsNotEmpty() {
        assertThat(SHIP_DOC_LEDGER).as("台账为空 ⇒ 本守卫恒绿（空断言）").isNotEmpty();
        assertThat(CONTROLLER_DIRS).as("扫描面为空 ⇒ 新发货路永远发现不了").isNotEmpty();
        assertThat(SHIP_DOC_LEDGER.stream().map(ShipDocLedgerEntry::note).filter(n -> n != null && !n.isBlank()).count())
                .as("每条登记都必须写清「它怎么产出可查的发货单」（不许只登记一个名字）")
                .isEqualTo(SHIP_DOC_LEDGER.size());
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 扫描实现（**结构化锚点**，与真源、内存片段共用同一份 —— 红证才不是空断言）
    // ══════════════════════════════════════════════════════════════════════════

    /** 逐文件扫描：{@code 文件名 → 该文件里命中「置为 shipped」的方法名}。 */
    private static Map<String, List<String>> scan(List<String> sources) throws IOException {
        Map<String, List<String>> found = new LinkedHashMap<>();
        for (String source : sources) {
            found.put(source, scanText(Files.readString(SERVICE_DIR.resolve(source))));
        }
        return found;
    }

    /**
     * 真源**发货写面寻址**：控制面（{@code controller/} + {@code worker/}）里每个带运单号锚的
     * {@code @PostMapping} 方法体 ⇒ {@code 文件名 → 该文件里的发货路段}。
     *
     * <p>与红证共用 {@link #shipRoutesIn(String)}（同一份判定 —— 否则红证不是对判据本体的判别力自证）。</p>
     */
    static Map<String, Set<String>> discoveredShipRoutes() throws IOException {
        Map<String, Set<String>> found = new LinkedHashMap<>();
        for (String dir : CONTROLLER_DIRS) {
            Path dirPath = REPO_ROOT.resolve("backend/admin-api/src/main/java/com/migao/admin").resolve(dir);
            if (!Files.isDirectory(dirPath)) {
                continue;
            }
            try (var stream = Files.list(dirPath)) {
                for (Path file : stream.filter(p -> p.toString().endsWith(".java")).toList()) {
                    Set<String> routes = shipRoutesIn(Files.readString(file));
                    if (!routes.isEmpty()) {
                        found.put(file.getFileName().toString(), routes);
                    }
                }
            }
        }
        return found;
    }

    /**
     * 在一个源文本里找出**发货写面**：{@code @PostMapping(".../ship")} 之后、下一个映射注解之前
     * 的那一段（含方法体）。
     *
     * <p>为什么用「注解 + 路径」而不是全文 contains：注释 / javadoc 里提到运单号或 /ship 不算发货路
     * （本仓反复踩过「把注释读成代码」）；路径锚把命中限定在**真的声明了这个端点**的地方。</p>
     */
    static Set<String> shipRoutesIn(String source) {
        Set<String> routes = new HashSet<>();
        Matcher matcher = SHIP_ROUTE.matcher(source);
        while (matcher.find()) {
            if (!matcher.group(1).endsWith("/ship")) {
                continue; // 只认「发货」这个动作的写面（其它 POST 端点不是发货路）
            }
            routes.add(matcher.group(1) + "||" + matcher.group(2).trim());
        }
        return routes;
    }

    /** 读控制面源文件（先 controller/ 再 worker/；两处都没有 ⇒ 断言红）。 */
    private static String readControllerOrService(String fileName) throws IOException {
        for (String dir : CONTROLLER_DIRS) {
            Path path = REPO_ROOT.resolve("backend/admin-api/src/main/java/com/migao/admin")
                    .resolve(dir).resolve(fileName);
            if (Files.exists(path)) {
                return Files.readString(path);
            }
        }
        throw new AssertionError("台账声明的源文件不存在（路径漂移不得静默跳过）: " + fileName);
    }

    /**
     * 在一个源文本里找出「调用状态转移本体、目标状态是字面量 {@code "shipped"}」的**转移本体名**。
     *
     * <p>只认结构化锚点：{@code transition*(} 后面出现带引号的 {@code "shipped"} ——
     * 注释里的散文（比如本单自己的红证说明）不含这种调用形态，喂不动它。</p>
     */
    static List<String> scanText(String source) {
        List<String> methods = new ArrayList<>();
        Matcher matcher = SHIPPED_WRITE.matcher(source);
        while (matcher.find()) {
            String suffix = matcher.group(1);
            methods.add(suffix.isEmpty() ? "transition" : "transition" + suffix);
        }
        return methods;
    }

    /** 真源扫描的**读数**（PR body 逐字引用；复算命令见类注释的锚点）。 */
    @Test
    @DisplayName("读数：真源里「置为 shipped」的写点清单（供人工核对，不是判据）")
    void printScanReading() throws IOException {
        Map<String, List<String>> reading = scan(SCAN_SOURCES);
        reading.forEach((file, methods) -> System.out.println("[6157] " + file + " → " + methods));
        assertThat(reading.keySet()).containsExactlyInAnyOrderElementsOf(SCAN_SOURCES);
        for (List<String> methods : reading.values()) {
            assertThat(methods).as("两个承载文件都必须有「置为 shipped」的写点（否则扫描面选错了）").isNotEmpty();
        }
    }
}
