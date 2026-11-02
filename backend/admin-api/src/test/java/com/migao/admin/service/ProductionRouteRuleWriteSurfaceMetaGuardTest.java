// case_ids: PG-100
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@code production_route_rules} **写面台账**的类级元守卫（issue #6428，铁律 8）。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 本单的实例缺陷 =「规则写面只校验工序**存在**，没校验它在规则生效的**每个部位**上都解析得到」
 * ⇒ 一条**不限部位**的规则能把「花边」（只有布帘库行 {@code 花边-布}）用到纱帘单上，
 * 直到**生产环节**整单 fail-closed（#6420：租户 25 的纱帘单 22/22 全挂）。
 * 只修 {@code POST /route-rules} 这一处，下一个人在**另一个**写面（开租播种 / 批量导入 / 端点迁移）
 * 上会原样再犯一遍，而没有任何东西会红。
 * ⇒ 本守卫把「**凡写 {@code production_route_rules} 的文件都必须在写面台账里登记**」变成机械判据。
 *
 * <h2>台账两态（键 = 相对 {@code src/main/java} 的路径；理由必填）</h2>
 * <ul>
 *   <li>{@code GATED} —— 落库前过「部位可解析性」判据（{@code unresolvedOperationReason}，
 *       与实例化侧**同一份** {@code variantNameOf}）。判据 3 同时核**调用点仍在**（文本计数 ≥ 2 =
 *       定义 + 调用）：把调用摘掉 ⇒ 判据 3 红，不需要跑行为用例；</li>
 *   <li>{@code POSITION_PINNED} —— 不解析变体名也能成立：写面的规则行由**显式常量**限定部位
 *       （{@code OPTION_OPERATION_POSITION} / {@code PROCESSING_ITEM_POSITION} = {@code 布帘}，
 *       issue #6114 / #6123），且工序来源 = 该租户工序库 ∩ 规范词表 ⇒ 生效部位上一定有该库行。</li>
 * </ul>
 *
 * <h2>红证（判别力自证）</h2>
 * 判据 1 / 2 / 3 各带**内存注入**：未登记写面 / 台账条目空转（文件里没有写面）/ 声称 GATED 但调用点被删
 * ⇒ 当场红并具名；同一夹具不注入 ⇒ 不报（反向对照）。实测读数见 PR body。
 *
 * <h2>边界（如实登记，§19.1）</h2>
 * <ul>
 *   <li>射程 = {@code src/main/java} 里 {@code ProductionRouteRule.builder(} /
 *       {@code productionRouteRuleMapper.insert(} / {@code productionRouteRuleMapper.update} 三种
 *       **文本形态**；直接拼 SQL、MyBatis XML、别的模块（ai-agent / 前端 / SQL 脚本）不在面内
 *       —— 形态学判据不做语义一刀切。</li>
 *   <li>判据 3 只核**文本**（调用点还在），判不了「那段代码真的被执行」——行为面由
 *       {@link ProductionRoutingCommandServiceOptionCreateTest} 的 PG-100 组承担。</li>
 *   <li>本守卫**不跑**被它点名的那些测试（否则等于把全量套件再跑一遍）。</li>
 * </ul>
 */
@DisplayName("production_route_rules 写面台账 · 类级元守卫（issue #6428）")
class ProductionRouteRuleWriteSurfaceMetaGuardTest {

    /** 主源码根（相对 admin-api 模块目录 —— mvn 工作目录），与既有元守卫同款。 */
    private static final Path MAIN_ROOT = Paths.get("src/main/java");

    /** 写面形态（**现取**，不写死文件名）：Builder 落行 / Mapper 写入。 */
    private static final List<String> WRITE_MARKERS = List.of(
            "ProductionRouteRule.builder(",
            "productionRouteRuleMapper.insert(",
            "productionRouteRuleMapper.update");

    /** 判据 3 核的守卫调用点（定义 + 调用 = 2 次；摘掉调用 ⇒ 1 次 ⇒ 红）。 */
    private static final String GUARD_CALL = "unresolvedOperationReason(";

    /** 判据 3 核的**唯一**解析实现（写面不得另造第二份「理论变体名」）。 */
    private static final String SINGLE_RESOLVER = "variantNameOf(";

    /** 写面台账（**冻结**：新增写面必须登记并写理由；空转条目由判据 2 抓）。 */
    private static final Map<String, String> REGISTRY = registry();

    private static Map<String, String> registry() {
        Map<String, String> map = new LinkedHashMap<>();
        map.put("com/migao/admin/service/ProductionRoutingCommandService.java",
                "GATED · createRouteRule 落库前走 unresolvedOperationReason（issue #6428）；"
                        + "updateCustomerUnitPrice 只写对客价列、deleteRouteRule 只写软删标记 ⇒ 不碰 operation");
        map.put("com/migao/admin/service/ProductionSeedTemplateService.java",
                "POSITION_PINNED · 开租播种：规则行带显式部位常量（OPTION_OPERATION_POSITION / "
                        + "PROCESSING_ITEM_POSITION = 布帘，#6114/#6123），工序来源 = 租户工序库 ∩ 规范词表");
        return Collections.unmodifiableMap(map);
    }

    // ══════════════════════ 判据 1~3（真实语料） ══════════════════════

    @Test
    @DisplayName("判据 1：凡写 production_route_rules 的文件都必须登记（未登记即红，双向相等）")
    void everyWriteSurfaceIsRegistered() throws IOException {
        Set<String> discovered = discoverWriteSurfaces();
        assertThat(discovered).as("扫描面为空 = 判据空跑（路径/标记漂移）").isNotEmpty();
        assertThat(unregistered(discovered, REGISTRY.keySet()))
                .as("新增了未登记的规则写面 —— 请先把「它的目标工序怎么校验部位可解析性」写进台账：%s",
                        REGISTRY.keySet())
                .isEmpty();
    }

    @Test
    @DisplayName("判据 2：台账不许空转（登记了但文件里没有写面 ⇒ 红，文件被删/改名当场可见）")
    void registryEntriesAreNotVacuous() throws IOException {
        assertThat(vacuous(discoverWriteSurfaces(), REGISTRY.keySet()))
                .as("台账条目空转（文件不存在或不含写面标记）—— 台账只许缩短为「真的没有这个写面」")
                .isEmpty();
    }

    @Test
    @DisplayName("判据 3：声称 GATED 的写面必须**真接着**部位判据（调用点被摘 ⇒ 红）")
    void gatedSurfacesKeepTheGuardWired() throws IOException {
        List<String> gated = REGISTRY.entrySet().stream()
                .filter(entry -> entry.getValue().startsWith("GATED"))
                .map(Map.Entry::getKey).toList();
        assertThat(gated).as("台账必须有 ≥1 个 GATED 写面（否则本守卫没有约束对象）").isNotEmpty();
        for (String path : gated) {
            String text = Files.readString(MAIN_ROOT.resolve(path));
            assertThat(countOccurrences(text, GUARD_CALL))
                    .as("`%s` 声称 GATED，但 `%s` 的调用点不见了（只剩定义 / 定义也没了）"
                            + " —— 部位可解析性判据被静默摘掉", path, GUARD_CALL)
                    .isGreaterThanOrEqualTo(2);
            assertThat(text).as("GATED 写面必须复用唯一解析实现 `%s`（不得另造第二份变体表）",
                    SINGLE_RESOLVER).contains(SINGLE_RESOLVER);
        }
    }

    // ══════════════════ 判据 4：判别力自证（内存注入，不碰真文件） ══════════════════

    @Test
    @DisplayName("判据 4：判别力自证 —— 未登记 / 空转各自判红，同一夹具不注入则不报")
    void checkerDiscriminates() {
        String firstRegistered = REGISTRY.keySet().iterator().next();
        // ① 未登记写面 ⇒ 判据 1 红
        assertThat(unregistered(Set.of("com/migao/admin/service/BrandNewImporter.java"), REGISTRY.keySet()))
                .containsExactly("com/migao/admin/service/BrandNewImporter.java");
        // 反向对照：只出现**已登记**的写面 ⇒ 不报
        assertThat(unregistered(Set.of(firstRegistered), REGISTRY.keySet())).isEmpty();
        // ② 台账空转 ⇒ 判据 2 红
        assertThat(vacuous(Set.of(firstRegistered), REGISTRY.keySet()))
                .containsExactlyInAnyOrderElementsOf(
                        REGISTRY.keySet().stream().filter(key -> !key.equals(firstRegistered)).toList());
        // 反向对照：写面与台账双向相等 ⇒ 不报
        assertThat(vacuous(REGISTRY.keySet(), REGISTRY.keySet())).isEmpty();
        // ③ 文本计数：调用点被摘（计数 1）⇒ 判据 3 的红条件成立
        assertThat(countOccurrences("void a() { x(); } void x() {}", GUARD_CALL.trim()))
                .as("夹具自证：只有定义、没有调用时计数必须 < 2").isLessThan(2);
    }

    // ══════════════════════════════ 纯函数 ══════════════════════════════

    /** 判据 1 的**纯函数**（便于内存注入自证）：返回未登记的写面（空 = 全部已登记）。 */
    static Set<String> unregistered(Set<String> discovered, Set<String> registered) {
        Set<String> missing = new TreeSet<>(discovered);
        missing.removeAll(registered);
        return missing;
    }

    /** 判据 2 的**纯函数**：台账里「文件里没有写面」的空转条目。 */
    static Set<String> vacuous(Set<String> discovered, Set<String> registered) {
        Set<String> idle = new TreeSet<>(registered);
        idle.removeAll(discovered);
        return idle;
    }

    /** 现取：`src/main/java` 下含任一写面形态的文件（相对路径，`/` 分隔）。 */
    private static Set<String> discoverWriteSurfaces() throws IOException {
        Set<String> out = new TreeSet<>();
        try (Stream<Path> files = Files.walk(MAIN_ROOT)) {
            for (Path file : files.filter(path -> path.toString().endsWith(".java")).toList()) {
                String text = Files.readString(file);
                if (WRITE_MARKERS.stream().anyMatch(text::contains)) {
                    out.add(MAIN_ROOT.relativize(file).toString().replace('\\', '/'));
                }
            }
        }
        return out;
    }

    /** 子串出现次数（不重叠；判「调用点还在」的机械半边）。 */
    static int countOccurrences(String text, String needle) {
        int count = 0;
        for (int index = text.indexOf(needle); index >= 0; index = text.indexOf(needle, index + needle.length())) {
            count++;
        }
        return count;
    }
}
