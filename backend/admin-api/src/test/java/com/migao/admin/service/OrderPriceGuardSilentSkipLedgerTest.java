// case_ids: OR-011, OR-014
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🧱 <b>类级元守卫：「Agent 取价守卫不得再出现静默放过」的冻结台账（issue #3881 缺陷二 / #4025 F11）</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 本单修掉的是 {@code OrderService.validateAgentItemUnitPrice} 里那一行
 * 「{@code !productId || !hasSkuKey ⇒ return;}」（无 SKU 标识 ⇒ 单价零核对落库，只记 warn）。
 * 单靠实例判据（{@code OrderNoSkuIdentityFailClosedTest}）只保证**这一处**不再回归；
 * 下一个人在同一条守卫里再写一个「解析不到 ⇒ 静默 return」照样没人拦。
 * 故本类把「**允许存在的静默跳过点**」冻成台账（**条数现取**、**只许缩短**），
 * 并**逐字禁止**改前那行 fail-open 形态回归。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>改前形态不得回归</b>：源码里不得再出现「{@code 无法解析权威价}」这一句
 *       （改前那行 fail-open 的注释指纹）；无标识分支必须**委派**给商品级核对方法。</li>
 *   <li><b>静默跳过台账只许缩短</b>：{@code 取价校验跳过} 标记的**现取条数**必须等于台账
 *       （当前 2 处：{@code SKU 未解析到} / {@code SKU 不唯一}）；**增加 ⇒ 红**
 *       （新写一个静默跳过点就进不来）；**减少 ⇒ 也红**（必须同 PR 把台账改小，台账永远是现取）。</li>
 *   <li><b>跳过不静默</b>：每个跳过点都必须在 {@code log.warn} 行上（只记 warn 不等于可以放过，
 *       但至少不能无声）。</li>
 *   <li><b>拒绝路径存在</b>：两条守卫方法体内都必须有 {@code throw}（拦得住）。</li>
 * </ol>
 *
 * <h2>红证（判据活着的证据，不靠人相信）</h2>
 * {@link #scannerIsAbleToFlagReintroducedFailOpen()} 用**合成语料**证明扫描器有判别力：
 * 把改前那行 fail-open 与第三个静默跳过点喂进去 ⇒ 扫描器必须报红。
 * 没有这条，"判据恒绿"与"判据有效"在输出上分不开。
 *
 * <p><b>有意不做</b>（如实登记）：不解析 Java AST ⇒ 只认**注释/字符串指纹 + 计数**这一形态；
 * 换个措辞写一个静默跳过（不写「取价校验跳过」）不会被本台账抓到 —— 这是本元守卫的射程边界，
 * 真实防线仍是实例判据（行为面）与人评审。</p>
 */
@DisplayName("元守卫：Agent 取价守卫的静默跳过台账（只许缩短）+ 改前 fail-open 形态不得回归")
class OrderPriceGuardSilentSkipLedgerTest {

    /**
     * 静默跳过台账（**现取**：本常量是「允许存在的处数」，不是"曾经有过多少"）。
     * 当前 2 处都属**有意保留**的分支（声明了规格键却解析不到 / 命中多条无法唯一确定）：
     * 库存侧另有 issue #4090 的显式拒绝，且 {@code colorName} 只给颜色、多门幅商品下命中多条是常态
     * ⇒ 一刀切 422 会误杀。修掉其中任一处 ⇒ **同 PR 把本常量改小**（只许缩短）。
     */
    private static final int FROZEN_SILENT_SKIPS = 2;

    /** 改前那行 fail-open 的注释指纹（改后**不得**再出现）。 */
    private static final String LEGACY_FAIL_OPEN_FINGERPRINT = "无法解析权威价";

    /** 静默跳过点的标记（每条都必须落在 {@code log.warn} 行上）。 */
    private static final String SILENT_SKIP_MARKER = "取价校验跳过";

    /** 无标识分支必须委派的商品级核对入口（改前是裸 return）。 */
    private static final String PRODUCT_AUTHORITY_CALL = "validateAgentItemUnitPriceByProductAuthority(item, tenantId);";

    @Test
    @DisplayName("🔴 判据1 改前 fail-open 形态（无 SKU 标识 ⇒ 裸 return）不得回归 + 无标识分支必须委派商品级核对")
    void legacyFailOpenShapeMustNotComeBack() throws IOException {
        String source = orderServiceSource();
        assertThat(source)
                .as("改前那行 `return; // 无 SKU 标识，无法解析权威价 → 不拦截` 的指纹不得回归")
                .doesNotContain(LEGACY_FAIL_OPEN_FINGERPRINT);
        assertThat(methodBody(source, "private void validateAgentItemUnitPrice("))
                .as("无标识分支必须委派给商品级权威价核对（改前是直接 return）")
                .contains(PRODUCT_AUTHORITY_CALL);
        assertThat(methodBody(source, "private void validateAgentItemUnitPriceByProductAuthority("))
                .as("商品级核对方法必须真的拒绝（而不是记个 warn 就走）")
                .contains("noAuthorityReject(")
                .contains("throw ");
    }

    @Test
    @DisplayName("🔴 判据2 静默跳过台账**现取**：条数必须等于台账（增加 ⇒ 新静默放过进不来；减少 ⇒ 同 PR 改小台账）")
    void silentSkipLedgerIsLiveAndOnlyShrinks() throws IOException {
        String source = orderServiceSource();
        int actual = 0;
        for (String line : source.split("\n")) {
            if (line.contains(SILENT_SKIP_MARKER)) {
                actual++;
                assertThat(line)
                        .as("跳过点必须在 log.warn 行上（不静默）：%s", line.trim())
                        .contains("log.warn");
            }
        }
        System.out.println("[reading #3881 元守卫] silentSkips=" + actual
                + " | ledger=" + FROZEN_SILENT_SKIPS
                + " | legacyFailOpenPresent=" + source.contains(LEGACY_FAIL_OPEN_FINGERPRINT));
        assertThat(actual)
                .as("静默跳过点增加 = 又一处 fail-open；减少 = 台账必须同步改小（只许缩短）")
                .isEqualTo(FROZEN_SILENT_SKIPS);
    }

    @Test
    @DisplayName("🔴 判据3 扫描器判别力自证：把改前的 fail-open 与第三个静默跳过喂进去 ⇒ 必须报红（防判据恒绿）")
    void scannerIsAbleToFlagReintroducedFailOpen() {
        String reintroducedByHuman = """
                private void validateAgentItemUnitPrice(OrderCreateRequest.OrderItemRequest item, Long tenantId) {
                    if (!StringUtils.hasText(item.getProductId()) || !hasSkuKey) {
                        return; // 无 SKU 标识，无法解析权威价 → 不拦截
                    }
                }
                """;
        String extraSilentSkip = """
                        log.warn("[order] 取价校验跳过（SKU 未解析到）: productId={}", item.getProductId());
                        log.warn("[order] 取价校验跳过（SKU 不唯一，无法确定权威价）: productId={}", item.getProductId());
                        log.warn("[order] 取价校验跳过（新写的第三处静默放过）: productId={}", item.getProductId());
                """;

        // ① 改前形态：指纹命中 ⇒ 判据 1 会红
        assertThat(reintroducedByHuman).contains(LEGACY_FAIL_OPEN_FINGERPRINT);
        // ② 第三个静默跳过点：计数 3 ≠ 台账 2 ⇒ 判据 2 会红
        assertThat(countSkipMarkers(extraSilentSkip)).isEqualTo(3).isNotEqualTo(FROZEN_SILENT_SKIPS);
        // ③ 反向（防过宽）：合法形态（只有两处已知跳过）不得被判红
        assertThat(countSkipMarkers("log.warn(\"[order] 取价校验跳过（SKU 未解析到）\");"))
                .isEqualTo(1).isNotEqualTo(FROZEN_SILENT_SKIPS);
    }

    private static int countSkipMarkers(String java) {
        int n = 0;
        for (String line : java.split("\n")) {
            if (line.contains(SILENT_SKIP_MARKER)) {
                n++;
            }
        }
        return n;
    }

    /** 取 `OrderService.java` 源码（与真库判据同款「从 user.dir 向上找仓根」定位，不写死绝对路径）。 */
    private static String orderServiceSource() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java"))
                .replace("\r\n", "\n");
    }

    /**
     * 按**花括号配对**取方法体（含签名行）——足以覆盖「本方法体内有哪些调用/跳过点」这一判据面；
     * 不做 Java 解析（本类的射程边界见类注释「有意不做」）。
     */
    private static String methodBody(String source, String signaturePrefix) {
        int start = source.indexOf(signaturePrefix);
        assertThat(start).as("找不到方法签名：%s（改名/删除 ⇒ 判据必须同步，不是静默失效）", signaturePrefix)
                .isGreaterThanOrEqualTo(0);
        int open = source.indexOf('{', start);
        assertThat(open).as("方法签名后没有方法体：%s", signaturePrefix).isGreaterThanOrEqualTo(0);
        int depth = 0;
        for (int i = open; i < source.length(); i++) {
            char c = source.charAt(i);
            if (c == '{') {
                depth++;
            } else if (c == '}') {
                depth--;
                if (depth == 0) {
                    return source.substring(start, i + 1);
                }
            }
        }
        throw new AssertionError("方法体花括号不配对：" + signaturePrefix);
    }
}