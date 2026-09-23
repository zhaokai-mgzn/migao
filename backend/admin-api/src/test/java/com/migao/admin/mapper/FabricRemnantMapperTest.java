// case_ids: PR-098
package com.migao.admin.mapper;

import com.migao.admin.entity.FabricRemnant;
import com.migao.admin.service.RemnantTestDb;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link FabricRemnantMapper#findMatchCandidates} 的**取数面**判据（V122 / issue #5146）—— 真库。
 *
 * <h2>为什么单测这一条查询</h2>
 * 「同缸号优先、其次同色、再先用小块」这条排序**只写在 SQL 里**（Java 侧只做「同缸号或同色」的
 * 硬底线复核）。排序写错的表现极隐蔽：推荐照样出来、金额照样算对，只是**挑错了布**
 * —— 而色差是窗帘行业最不能接受的质量事故。⇒ 排序必须有能单独变红的判据。
 *
 * <h2>判据</h2>
 * <ol>
 *   <li><b>只扫可用池</b>：`used` / `scrapped` / `customer_taken` 三种状态**都不出现在候选里**
 *       （红证：把它们改成 `available` ⇒ 立刻出现）；</li>
 *   <li><b>尺寸谓词</b>：任一条边不足 ⇒ 不在候选里；</li>
 *   <li><b>同商品</b>：别的商品的余料不出现在候选里；</li>
 *   <li><b>排序</b>：同缸号（更大）排在异缸号（更小）之前 —— 即「防色差」优先于「先用小块」；
 *       同缸号内部按长度升序（先用小块）；长度相同按 id 升序（确定性）；</li>
 *   <li><b>缸号为空的坑</b>：{@code ORDER BY (dye_lot = ?) DESC} 在 PG 上会把 NULL 排到**最前**
 *       （{@code DESC} 默认 {@code NULLS FIRST}）⇒ 正是把「优先」颠倒；本判据用「缸号为空的行不得排在同缸号行之前」钉住。</li>
 * </ol>
 */
@DisplayName("FabricRemnantMapper 匹配候选取数面（只扫可用池 + 同缸号优先排序）")
class FabricRemnantMapperTest {

    private static RemnantTestDb db;
    private static FabricRemnantMapper mapper;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        db = RemnantTestDb.start();
        mapper = db.mapperOf(FabricRemnantMapper.class);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (db != null) {
            db.stop();
        }
    }

    @Test
    @DisplayName("🔴 判据1 只扫可用池：used / scrapped / customer_taken 都不出现在候选里")
    void onlyAvailableRemnantsAreCandidates() throws Exception {
        clearRemnants();
        db.insertRemnant("ORD-5147-M1", "PC-5147-M1", RemnantTestDb.DYE_LOT, FabricRemnant.KIND_WIDTH,
                "3.0", "0.3", FabricRemnant.STATUS_USED);
        db.insertRemnant("ORD-5147-M2", "PC-5147-M1", RemnantTestDb.DYE_LOT, FabricRemnant.KIND_WIDTH,
                "3.0", "0.3", FabricRemnant.STATUS_SCRAPPED);
        long taken = db.insertRemnant("ORD-5147-M3", "PC-5147-M1", RemnantTestDb.DYE_LOT,
                FabricRemnant.KIND_WIDTH, "3.0", "0.3", FabricRemnant.STATUS_CUSTOMER_TAKEN);

        List<FabricRemnant> candidates = candidates("0.5", "0.2");
        assertThat(candidates).as("🔴 三种非可用状态一个都不许进候选（客户带走的余料归客户）").isEmpty();

        // 红证：把客户带走那块改成 available ⇒ 立刻出现在候选里（证明上面那条不是恒真）
        db.exec("UPDATE fabric_remnants SET status = 'available' WHERE id = " + taken);
        assertThat(candidates("0.5", "0.2")).hasSize(1);
        db.exec("UPDATE fabric_remnants SET status = 'customer_taken' WHERE id = " + taken);
    }

    @Test
    @DisplayName("判据2/3 尺寸谓词与同商品：任一条边不足、或别的商品的余料 ⇒ 都不在候选里")
    void sizePredicateAndProductScope() throws Exception {
        clearRemnants();
        db.insertRemnant("ORD-5147-M4", "PC-5147-M2", RemnantTestDb.DYE_LOT, FabricRemnant.KIND_WIDTH,
                "3.0", "0.3", FabricRemnant.STATUS_AVAILABLE);
        // 别的商品：product_id 不同 ⇒ 换颜色/门幅的另一匹布，不可能互相替代
        db.exec("INSERT INTO products (id, tenant_id, name) VALUES ('acc-5147-other', "
                + RemnantTestDb.TENANT_ID + ", '另一匹布')");
        db.exec("INSERT INTO fabric_remnants (tenant_id, piece_seq, source_order_no,"
                + " source_processing_order_no, source_batch_no, dye_lot, product_id, sku_code,"
                + " piece_kind, length_m, width_m, status) VALUES (" + RemnantTestDb.TENANT_ID
                + ", 1, 'ORD-5147-M5', 'JG-ORD-5147-M5', 'PC-5147-M5', 'LOT-5147',"
                + " 'acc-5147-other', 'SKU-OTHER', 'width', 3.0, 0.3, 'available')");

        assertThat(candidates("3.5", "0.2")).as("长边不足 ⇒ 无候选").isEmpty();
        assertThat(candidates("0.5", "0.5")).as("宽边不足 ⇒ 无候选").isEmpty();
        assertThat(candidates("0.5", "0.2").stream().map(FabricRemnant::getProductId).distinct().toList())
                .as("候选只含本商品（不跨商品匹配）").containsExactly(RemnantTestDb.PRODUCT_ID);
    }

    @Test
    @DisplayName("🔴 判据4/5 排序：同缸号（更大）先于异缸号（更小）；同缸号内按长度升序；缸号为空不得插队")
    void orderingPutsSameDyeLotFirstThenSmallest() throws Exception {
        clearRemnants();
        // 同缸号两块：3.0×0.3 与 2.6×0.3；异缸号一块**更小**的 2.4×0.3；缸号为空一块 2.2×0.3
        db.insertRemnant("ORD-5147-M6", "PC-5147-M6", RemnantTestDb.DYE_LOT, FabricRemnant.KIND_WIDTH,
                "3.0", "0.3", FabricRemnant.STATUS_AVAILABLE);
        db.insertRemnant("ORD-5147-M7", "PC-5147-M7", RemnantTestDb.DYE_LOT, FabricRemnant.KIND_WIDTH,
                "2.6", "0.3", FabricRemnant.STATUS_AVAILABLE);
        db.insertRemnant("ORD-5147-M8", "PC-5147-M8", "LOT-OTHER", FabricRemnant.KIND_WIDTH,
                "2.4", "0.3", FabricRemnant.STATUS_AVAILABLE);
        db.insertRemnant("ORD-5147-M9", "PC-5147-M9", null, FabricRemnant.KIND_WIDTH,
                "2.2", "0.3", FabricRemnant.STATUS_AVAILABLE);

        List<FabricRemnant> ordered = candidates("2.0", "0.2");
        assertThat(ordered).as("四块都装得下 ⇒ 全在候选里").hasSize(4);
        // 期望序 = ①同缸号那一档在前（档内按长度升序 ⇒ 2.6 在 3.0 之前）
        //          ②异缸号与空缸号在后（档内同样按长度升序 ⇒ 2.2 在 2.4 之前，且**空缸号不得插队**）
        // ⇒ 「同缸号」这一档**胜过了**「先用小块」：2.4 / 2.2 比 2.6 还小，却排在后面。
        assertThat(ordered.stream().map(FabricRemnant::getSourceBatchNo).toList())
                .as("🔴 同缸号优先于「先用小块」；同缸号内部先用小块；空缸号不因 PG 的 NULLS FIRST 插到最前")
                .containsExactly("PC-5147-M7", "PC-5147-M6", "PC-5147-M9", "PC-5147-M8");
        assertThat(ordered.get(0).getDyeLot()).isEqualTo(RemnantTestDb.DYE_LOT);
        assertThat(ordered.get(0).getLengthM()).isEqualByComparingTo(new BigDecimal("2.6"));
        assertThat(ordered.get(1).getDyeLot()).isEqualTo(RemnantTestDb.DYE_LOT);
        assertThat(ordered.get(1).getLengthM()).isEqualByComparingTo(new BigDecimal("3.0"));
        assertThat(ordered.get(2).getLengthM()).as("异缸号档内同样按长度升序（2.2 在 2.4 之前）")
                .isEqualByComparingTo(new BigDecimal("2.2"));
        assertThat(ordered.get(2).getDyeLot()).as("空缸号既不算同缸号也不算异缸号 ⇒ 与异缸号同档").isNull();
        assertThat(ordered.get(3).getDyeLot()).as("异缸号那块（比同缸号两块都小）仍排在**整档同缸号之后**")
                .isEqualTo("LOT-OTHER");
    }

    /** 用例间隔离：本类共用一个真库 ⇒ 每个用例先清空余料，避免断言依赖执行顺序。 */
    private static void clearRemnants() throws Exception {
        db.exec("DELETE FROM fabric_remnants WHERE tenant_id = " + RemnantTestDb.TENANT_ID);
    }

    /** 以「本商品 + 同缸号 + 同色」为上下文查候选（与 `RemnantService` 的取数口径同参数）。 */
    private static List<FabricRemnant> candidates(String needLength, String needWidth) {
        return mapper.findMatchCandidates(RemnantTestDb.TENANT_ID, RemnantTestDb.PRODUCT_ID,
                RemnantTestDb.DYE_LOT, RemnantTestDb.SKU_CODE,
                new BigDecimal(needLength), new BigDecimal(needWidth));
    }
}
