// case_ids: OR-045, OR-046, DF-017
package com.migao.admin.shipment;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
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
     * 发货写面台账（**未登记即红**）。`carriesInvariant` = 该写点是否真的带「累计已发 ≤ 订单量」。
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
                    false, null,
                    "本路**不建发货单**（不落 order_shipment_items）⇒ 没有「实发数量」可判 —— 这不是漏接，"
                            + "是既有的**有意**设计：发货写面（含实发明细）全归 issue #5648 的工人面"
                            + "（ShipmentController 类注释、print-media-matrix §6 逐字）。"
                            + "⇒ 本路今天**结构上无法**承载「累计已发 ≤ 订单量」；它的缺口（订单置 shipped 后"
                            + "在发货单链上不可见 = 漏单）已由本单登记，见 acceptedGap。",
                    "若要本路也承载实发数量，需先裁定「商家发货要不要建发货单 + 实发数量从哪来」"
                            + "（业务口径，涉单据与对账）⇒ 裁定后把本条目改为 carriesInvariant=true "
                            + "并接上 OrderShipmentService::assertQuantities。"),
            new WritePoint("OrderService.java",
                    "裸状态流转（updateOrderStatus 的 confirmed|producing → shipped）",
                    "PUT /api/admin/orders/{id}/status",
                    false, null,
                    "本路**只改状态**、不带任何数量（请求体只有 status）⇒ 与上一条同因：没有数就没得判。"
                            + "它与上一条合起来 = 「任何把订单置为 shipped 的写面都可能不留发货单」这个族级缺口。",
                    "同「商家/生产发货」条目：先裁定商家侧要不要建发货单，再决定本路是否并入同一条写面。"));

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
            if (!point.carriesInvariant()) {
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
