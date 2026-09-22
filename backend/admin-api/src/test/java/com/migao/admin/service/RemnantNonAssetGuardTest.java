// case_ids: PR-097
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>「余料不是资产」的静态守卫（issue #5146）</b>—— 余料两表**不得出现在任何库存 / 资产读面里**。
 *
 * <h2>为什么需要它（真库判据覆盖不到的那一半）</h2>
 * {@code RemnantRecoveryRealDbTest} 证明的是「**这一次**登记余料没有改动库存金额」
 * （{@code Σ product_skus.cost_amount} 逐值不变）。但另一条判据是**结构性的**：
 * 「余料台账**不出现在任何库存 / 资产读面里**」—— 它的反面形态是「某天有人给库存读面
 * 加一条 {@code LEFT JOIN fabric_remnants}」，那种改动**不会**让金额变（读面而已），
 * 于是真库判据照绿，而余料事实上已经变成了资产口径的一部分。
 *
 * ⇒ 判据落在**源码**上：生产代码里出现 `fabric_remnants` / `remnant_small_item_specs`
 * 这两个**表名**的地方，只允许是它们自己的 mapper（那是它们该在的地方）。
 *
 * <h2>判据（每条都能单独变红）</h2>
 * <ol>
 *   <li>扫描面**非空且真的看得见**：被测文件数 &gt; 0，且两个 mapper 自己**确实**命中
 *       （否则「零违规」可能只是扫描失灵 —— 空断言）；</li>
 *   <li>生产代码里引用余料两表的文件 == 恰好那两个 mapper；</li>
 *   <li>红证：往扫描函数里注入一份「库存 mapper 里 join 了余料表」的源码 ⇒ 必须被判出来。</li>
 * </ol>
 *
 * <p>扫描函数是**接收任意映射的纯函数**（同 {@code tenant-params.ts} 的 {@code findDomainViolations}
 * 范式）：守卫必须能注入一份坏源码并断言它被判出来 —— 否则「扫了但扫不出」与「根本没扫」
 * 在测试里长得一模一样。</p>
 */
@DisplayName("#5146 静态守卫：余料台账不出现在任何库存/资产读面里")
class RemnantNonAssetGuardTest {

    /** 余料的两个表名 —— 它们只允许出现在各自的 mapper 里。 */
    private static final List<String> REMNANT_TABLES = List.of("fabric_remnants", "remnant_small_item_specs");

    /**
     * 允许引用余料表名的文件 = 余料功能**自己的取数面**（两张实体 + 两个 mapper）。
     *
     * <p>实体里的 {@code @TableName("fabric_remnants")} 是它们该在的地方；除这四个文件之外，
     * 生产代码里出现这两个表名就是「余料被接进了别的读面」——那正是本守卫要拦的形态。</p>
     */
    private static final List<String> ALLOWED_FILES = List.of(
            "FabricRemnant.java", "RemnantSmallItemSpec.java",
            "FabricRemnantMapper.java", "RemnantSmallItemSpecMapper.java");

    @Test
    @DisplayName("🔴 余料两表只出现在它们自己的 mapper 里（库存/资产读面零引用）")
    void remnantTablesStayOutOfStockReadFaces() throws IOException {
        Map<String, String> sources = productionSources();
        assertThat(sources.size()).as("扫描面必须非空（0 个文件 ⇒ 下面每条都恒真）")
                .isGreaterThan(50);
        assertThat(sources.keySet()).as("扫描必须真的看得见余料 mapper（否则「零违规」是扫描失灵）")
                .contains("FabricRemnantMapper.java", "RemnantSmallItemSpecMapper.java");

        assertThat(violations(sources))
                .as("🔴 余料台账不得出现在任何库存 / 资产读面里（用户裁定：这个废布不算在企业资产了）")
                .isEmpty();
    }

    @Test
    @DisplayName("红证：把余料表 join 进库存读面 ⇒ 同一判据必须判红（证明上面那条不是空跑）")
    void injectedJoinIntoStockReadFaceIsCaught() {
        Map<String, String> injected = new LinkedHashMap<>();
        injected.put("FabricRemnantMapper.java", "SELECT * FROM fabric_remnants");
        injected.put("StockLedgerMapper.java",
                "SELECT e.* FROM stock_ledger_entries e LEFT JOIN fabric_remnants r ON r.id = e.id");
        assertThat(violations(injected))
                .as("红证：库存 mapper 一旦引用余料表，就必须被判出来（而余料自己的 mapper 不算）")
                .containsExactly("StockLedgerMapper.java");

        Map<String, String> specsJoin = new LinkedHashMap<>();
        specsJoin.put("ProductSkuMapper.java", "SELECT * FROM remnant_small_item_specs");
        assertThat(violations(specsJoin)).containsExactly("ProductSkuMapper.java");

        // 反向红证：**注释里**提到表名不得被判红（否则本守卫会被自己的文案喂红 —— 实测踩过）
        Map<String, String> proseOnly = new LinkedHashMap<>();
        proseOnly.put("StockLedgerService.java",
                "// 本服务不读 fabric_remnants（余料不是资产）\n/* 也不读 remnant_small_item_specs */");
        assertThat(violations(proseOnly))
                .as("注释里提到表名是正常的（判据只读代码，不读文案）").isEmpty();
        assertThat(stripComments("String s = \"fabric_remnants\"; // fabric_remnants"))
                .as("字符串字面量里的表名必须留下（否则真引用会被剥掉 = 判据失灵）")
                .contains("fabric_remnants");
    }

    // ────────────────────────────────────────────── 纯函数 + 取源

    /**
     * 违规文件清单（**接收任意映射的纯函数** —— 守卫与红证共用同一份判定）。
     *
     * <p>🔴 <b>先剥注释再扫</b>：本判据要判的是「代码里有没有把余料表接进别的读面」，
     * 而**注释里提到表名是正常且必要的**（说明「这张表不在库存读面里」本身就要写出表名）。
     * 不剥注释就会踩本仓反复复发的形态 —— <b>判据被自己的文案喂红</b>
     * （实测：本守卫首跑就被 {@code RemnantService} 的 javadoc 与 {@code StockBatchConsumptionService}
     * 的行内注释判红，而两处都没有任何 SQL 引用）。</p>
     *
     * @return 引用了余料表名、且**不是**余料功能自己的取数面的文件名
     */
    static List<String> violations(Map<String, String> sources) {
        List<String> bad = new ArrayList<>();
        for (Map.Entry<String, String> entry : sources.entrySet()) {
            if (ALLOWED_FILES.contains(entry.getKey())) {
                continue;
            }
            String code = stripComments(entry.getValue() == null ? "" : entry.getValue());
            for (String table : REMNANT_TABLES) {
                if (code.contains(table)) {
                    bad.add(entry.getKey());
                    break;
                }
            }
        }
        return bad;
    }

    /**
     * 剥掉 Java 的块注释与行注释（**判据只读代码，不读文案**）。
     *
     * <p>与 {@code .github/danger_scan.py} 的教训同族：把注释里「不得新增 X」的说明当成 X 的引用，
     * 会让守卫**判红正确的东西**。这里的取舍是：字符串字面量里的表名**照常命中**
     * （{@code @TableName("fabric_remnants")} 与 SQL 串都会留下）—— 只有注释被剥掉。</p>
     */
    static String stripComments(String source) {
        String withoutBlock = source.replaceAll("(?s)/\\*.*?\\*/", " ");
        StringBuilder out = new StringBuilder(withoutBlock.length());
        for (String line : withoutBlock.split("\n", -1)) {
            int cut = line.indexOf("//");
            out.append(cut < 0 ? line : line.substring(0, cut)).append('\n');
        }
        return out.toString();
    }

    /** 全部生产源码（文件名 → 内容）。文件名在 mapper 之间唯一 ⇒ 用简单名当键足够。 */
    private static Map<String, String> productionSources() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("backend/admin-api/src/main/java"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/java").isNotNull();
        Path base = root.resolve("backend/admin-api/src/main/java");
        Map<String, String> sources = new LinkedHashMap<>();
        try (Stream<Path> files = Files.walk(base)) {
            for (Path file : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                sources.put(file.getFileName().toString(), Files.readString(file));
            }
        }
        return sources;
    }
}
