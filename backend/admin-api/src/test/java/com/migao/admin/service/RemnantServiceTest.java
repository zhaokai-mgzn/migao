// case_ids: PR-098
package com.migao.admin.service;

import com.migao.admin.dto.RemnantViews;
import com.migao.admin.entity.FabricRemnant;
import com.migao.admin.entity.RemnantItemSize;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;

/**
 * {@link RemnantService} 的判定面判据（V122 / issue #5146）—— **真库**装配。
 *
 * <h2>为什么用真库而不是 Mockito</h2>
 * 本服务的判定**全部**建立在真实数据形态上（JSONB 的 `specialOptions`、唯一索引的原子性、
 * DB 约束对「账实一致」的钉住、`@TableLogic` 的软删语义）。Mockito 只会证明「调了哪个方法」，
 * 而列名拼错 / 约束没生效 / 幂等闸缺失在 mock 面**结构上不可见**（#5141 / #5148 的教训同族）。
 *
 * <h2>判据（互补于 {@code RemnantRecoveryRealDbTest}：那边判端到端事实账，这边判写面守卫）</h2>
 * <ol>
 *   <li><b>putSpecs：键必须是工序库里真有的工序名</b>（打错一个字 ⇒ 该行永远不会被命中 ⇒ 当场 422）——
 *       红证 = 用一个不存在的键 ⇒ 必须被拒且**零落库**；</li>
 *   <li><b>putSpecs 全量替换</b>：空数组 = 清空 = 回到未配置（不是「什么都没做」）；</li>
 *   <li><b>recover 四条 fail-closed</b>：余料不存在 / 状态不是可用 / 小件未配尺寸 / 尺寸装不下 /
 *       来源批次没记均价 —— 各自显式拒绝且错误码可判读（**寂静**是最坏的形态）；</li>
 *   <li><b>scrap 两条 fail-closed</b>：原因必填、只有可用件能报废；</li>
 *   <li><b>accrue 幂等</b>：同一加工单的同一 pieceSeq 重复登记 ⇒ **跳过**（不写第二行）；</li>
 *   <li><b>客户带走是订单级判定</b>：整单勾了「余料带回」⇒ 本次登记的行全部落
 *       {@code customer_taken}（红证：不勾 ⇒ 落 {@code available}）。</li>
 * </ol>
 */
@DisplayName("RemnantService 写面守卫（余料台账 / 小件尺寸 / 回收 / 报废）")
class RemnantServiceTest {

    private static RemnantTestDb db;
    private static RemnantService service;
    private static int seq = 0;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        db = RemnantTestDb.start();
        if (db == null) {
            Assumptions.abort("本机没有 PG 二进制（initdb/pg_ctl）⇒ 真库判据**未跑**（不是通过）");
        }
        service = db.remnantService();
    }

    @AfterAll
    static void stopRealPostgres() {
        if (db != null) {
            db.stop();
        }
    }

    // ────────────────────────────────────────────── 判据 1 / 2：小件尺寸表（可配参数）

    @Test
    @DisplayName("🔴 判据1 putSpecs：键不在工序库里 ⇒ 显式拒绝且**零落库**（红证：真有的键 ⇒ 落库）")
    void itemKeyMustExistInOperationCatalog() throws Exception {
        long before = db.scalar("SELECT COUNT(*) FROM remnant_small_item_specs WHERE tenant_id = "
                + RemnantTestDb.TENANT_ID).longValue();
        Throwable rejected = catchThrowable(() -> service.putSpecs(RemnantTestDb.TENANT_ID,
                List.of(Map.of("item_key", "绑带布", "length_m", 0.5, "width_m", 0.2))));
        assertThat(rejected).as("工序库里没有这道工序 ⇒ 配了也永远匹配不到 ⇒ 必须当场拒绝")
                .isInstanceOf(BusinessException.class);
        assertThat(((BusinessException) rejected).getMessage()).contains("工序库里没有");
        assertThat(db.scalar("SELECT COUNT(*) FROM remnant_small_item_specs WHERE tenant_id = "
                + RemnantTestDb.TENANT_ID).longValue())
                .as("拒绝必须**零落库**（不留半成品配置）").isEqualTo(before);

        // 红证：换成工序库里真有的键 ⇒ 落库且读面 configured=true
        RemnantViews.SpecsView saved = service.putSpecs(RemnantTestDb.TENANT_ID,
                List.of(Map.of("item_key", "绑带-布", "length_m", "0.5", "width_m", "0.2")));
        assertThat(saved.configured()).isTrue();
        assertThat(saved.items()).hasSize(1);
        assertThat(saved.items().get(0).itemKey()).isEqualTo("绑带-布");
        assertThat(saved.notice()).as("配了之后不得再报「未配置」").isNull();
    }

    @Test
    @DisplayName("判据2 putSpecs：全量替换 —— 空数组 = **清空**（回到未配置），不是「什么都没做」")
    void putSpecsReplacesWholesale() {
        service.putSpecs(RemnantTestDb.TENANT_ID, List.of(
                Map.of("item_key", "绑带-布", "length_m", "0.5", "width_m", "0.2"),
                Map.of("item_key", "帘头制作", "length_m", "1.2", "width_m", "0.4")));
        assertThat(service.specs(RemnantTestDb.TENANT_ID).items()).hasSize(2);

        RemnantViews.SpecsView cleared = service.putSpecs(RemnantTestDb.TENANT_ID, List.of());
        assertThat(cleared.configured()).as("清空后必须判为未配置").isFalse();
        assertThat(cleared.items()).isEmpty();
        assertThat(cleared.notice()).as("清空同样要有可见说明（不静默）").contains("未配置");

        // 反向红证：只提交一行 ⇒ 另一行必须消失（全量替换语义；逐项 upsert 会留下「以为删了其实还在」）
        service.putSpecs(RemnantTestDb.TENANT_ID, List.of(
                Map.of("item_key", "绑带-布", "length_m", "0.5", "width_m", "0.2")));
        assertThat(service.specs(RemnantTestDb.TENANT_ID).items().stream()
                .map(RemnantViews.SpecLine::itemKey).toList()).containsExactly("绑带-布");
    }

    // ────────────────────────────────────────────── 判据 3：recover 的 fail-closed

    @Test
    @DisplayName("🔴 判据3 recover：状态不对 / 未配尺寸 / 尺寸不足 / 批次没均价 ⇒ 四条各自显式拒绝")
    void recoverFailsClosedInFourWays() throws Exception {
        service.putSpecs(RemnantTestDb.TENANT_ID,
                List.of(Map.of("item_key", "绑带-布", "length_m", "2.5", "width_m", "0.2")));
        db.newBatch("PC-5147-R1", RemnantTestDb.DYE_LOT);
        long usable = db.insertRemnant("ORD-5147-R1", "PC-5147-R1", RemnantTestDb.DYE_LOT, "width",
                "3.0", "0.3", FabricRemnant.STATUS_AVAILABLE);
        long taken = db.insertRemnant("ORD-5147-R2", "PC-5147-R1", RemnantTestDb.DYE_LOT, "width",
                "3.0", "0.3", FabricRemnant.STATUS_CUSTOMER_TAKEN);
        long tiny = db.insertRemnant("ORD-5147-R3", "PC-5147-R1", RemnantTestDb.DYE_LOT, "width",
                "1.0", "0.3", FabricRemnant.STATUS_AVAILABLE);

        assertThat(codeOf(catchThrowable(() -> service.recover(RemnantTestDb.TENANT_ID, 999_999L,
                "i", "ORD-5147-R1", "绑带-布")))).isEqualTo(RemnantService.ERR_REMNANT_NOT_FOUND);
        assertThat(codeOf(catchThrowable(() -> service.recover(RemnantTestDb.TENANT_ID, taken,
                "i", "ORD-5147-R2", "绑带-布")))).isEqualTo(RemnantService.ERR_REMNANT_NOT_AVAILABLE);
        assertThat(codeOf(catchThrowable(() -> service.recover(RemnantTestDb.TENANT_ID, usable,
                "i", "ORD-5147-R1", "帘头制作")))).isEqualTo(RemnantService.ERR_REMNANT_SPEC_REQUIRED);
        assertThat(codeOf(catchThrowable(() -> service.recover(RemnantTestDb.TENANT_ID, tiny,
                "i", "ORD-5147-R3", "绑带-布")))).isEqualTo(RemnantService.ERR_REMNANT_TOO_SMALL);

        // 批次没记均价 ⇒ 回收额算不出来 ⇒ 拒绝（宁可为失败，不许估一个价）
        db.newBatch("PC-5147-NOCOST", RemnantTestDb.DYE_LOT);
        db.exec("UPDATE stock_batches SET unit_cost = NULL WHERE batch_no = 'PC-5147-NOCOST'");
        long noCost = db.insertRemnant("ORD-5147-R4", "PC-5147-NOCOST", RemnantTestDb.DYE_LOT, "width",
                "3.0", "0.3", FabricRemnant.STATUS_AVAILABLE);
        assertThat(codeOf(catchThrowable(() -> service.recover(RemnantTestDb.TENANT_ID, noCost,
                "i", "ORD-5147-R4", "绑带-布"))))
                .isEqualTo(RemnantService.ERR_REMNANT_BATCH_COST_UNKNOWN);

        // 红证：同一个可用的、装得下的、批次有均价的件 ⇒ 必须成功（否则上面四条「拒绝」没有判别力）
        RemnantViews.RemnantLine recovered = service.recover(RemnantTestDb.TENANT_ID, usable,
                "ORD-5147-R1-ITEM", "ORD-5147-R1", "绑带-布");
        assertThat(recovered.status()).isEqualTo(FabricRemnant.STATUS_USED);
        assertThat(recovered.recoveredAmount()).isEqualByComparingTo("37.500000");
    }

    @Test
    @DisplayName("判据3b recover：不写任何批次消耗行（该小件不新领料）")
    void recoverNeverWritesBatchConsumption() throws Exception {
        service.putSpecs(RemnantTestDb.TENANT_ID,
                List.of(Map.of("item_key", "绑带-布", "length_m", "2.5", "width_m", "0.2")));
        db.newBatch("PC-5147-R5", RemnantTestDb.DYE_LOT);
        long id = db.insertRemnant("ORD-5147-R5", "PC-5147-R5", RemnantTestDb.DYE_LOT, "width",
                "3.0", "0.3", FabricRemnant.STATUS_AVAILABLE);
        long rowsBefore = db.scalar("SELECT COUNT(*) FROM stock_batch_consumptions WHERE tenant_id = "
                + RemnantTestDb.TENANT_ID).longValue();
        service.recover(RemnantTestDb.TENANT_ID, id, "ORD-5147-R5-ITEM", "ORD-5147-R5", "绑带-布");
        assertThat(db.scalar("SELECT COUNT(*) FROM stock_batch_consumptions WHERE tenant_id = "
                + RemnantTestDb.TENANT_ID).longValue())
                .as("余料是已经领下来的料 ⇒ 回收**不得**新增批次消耗").isEqualTo(rowsBefore);
    }

    // ────────────────────────────────────────────── 判据 4：scrap 的 fail-closed

    @Test
    @DisplayName("判据4 scrap：原因必填 + 只有可用的能报废（客户带走的归客户，企业无权处置）")
    void scrapFailsClosed() throws Exception {
        db.newBatch("PC-5147-S1", RemnantTestDb.DYE_LOT);
        long usable = db.insertRemnant("ORD-5147-S1", "PC-5147-S1", RemnantTestDb.DYE_LOT, "end",
                "0.8", "1.4", FabricRemnant.STATUS_AVAILABLE);
        long taken = db.insertRemnant("ORD-5147-S2", "PC-5147-S1", RemnantTestDb.DYE_LOT, "end",
                "0.8", "1.4", FabricRemnant.STATUS_CUSTOMER_TAKEN);

        assertThat(catchThrowable(() -> service.scrap(RemnantTestDb.TENANT_ID, usable, "   ")))
                .as("报废必须写原因 —— 留痕要答得出「为什么」").isInstanceOf(BusinessException.class);
        assertThat(codeOf(catchThrowable(() -> service.scrap(RemnantTestDb.TENANT_ID, taken, "想报废"))))
                .isEqualTo(RemnantService.ERR_REMNANT_NOT_AVAILABLE);

        RemnantViews.RemnantLine scrapped = service.scrap(RemnantTestDb.TENANT_ID, usable, "超期未用");
        assertThat(scrapped.status()).isEqualTo(FabricRemnant.STATUS_SCRAPPED);
        assertThat(scrapped.scrapReason()).isEqualTo("超期未用");
        assertThat(codeOf(catchThrowable(() -> service.scrap(RemnantTestDb.TENANT_ID, usable, "再报废"))))
                .as("重复报废被拒（否则报废率失真）").isEqualTo(RemnantService.ERR_REMNANT_NOT_AVAILABLE);
    }

    // ────────────────────────────────────────────── 判据 5 / 6：accrue 幂等 + 客户带走

    @Test
    @DisplayName("🔴 判据5/6 accrue：同一 pieceSeq 重复登记 ⇒ 跳过；整单勾「余料带回」⇒ 全落客户带走")
    void accrueIsIdempotentAndHonoursCustomerTakeAway() throws Exception {
        long batchId = db.newBatch("PC-5147-A1", RemnantTestDb.DYE_LOT);
        RemnantService.Source source = new RemnantService.Source(batchId, "PC-5147-A1",
                RemnantTestDb.PRODUCT_ID, RemnantTestDb.SKU_ID, RemnantTestDb.SKU_CODE);
        String orderNo = "ORD-5147-A1";
        db.exec("INSERT INTO orders (id, tenant_id, order_no, status, total_amount) VALUES"
                + " ('acc-5147-o1', " + RemnantTestDb.TENANT_ID + ", '" + orderNo + "', 'confirmed', 0)");
        List<RemnantService.Draft> drafts = List.of(
                new RemnantService.Draft(1, FabricRemnant.KIND_WIDTH, new BigDecimal("3.00"),
                        new BigDecimal("0.30")),
                new RemnantService.Draft(2, FabricRemnant.KIND_END, new BigDecimal("0.80"),
                        new BigDecimal("1.40")));

        assertThat(service.accrue(RemnantTestDb.TENANT_ID, "JG-" + orderNo, orderNo, source, drafts))
                .as("首跑登记两块").isEqualTo(2);
        assertThat(service.accrue(RemnantTestDb.TENANT_ID, "JG-" + orderNo, orderNo, source, drafts))
                .as("🔴 重跑必须**跳过**（幂等闸：同一加工单的同一 pieceSeq 只登记一次）").isZero();
        assertThat(db.scalar("SELECT COUNT(*) FROM fabric_remnants WHERE source_order_no = '" + orderNo
                + "' AND status = 'available'").longValue())
                .as("没勾「余料带回」⇒ 落可用池").isEqualTo(2);

        // 红证：整单勾了「余料带回-布」⇒ 本次登记的行全部落 customer_taken（不进可用池）
        String takenOrder = "ORD-5147-A2";
        db.exec("INSERT INTO orders (id, tenant_id, order_no, status, total_amount) VALUES"
                + " ('acc-5147-o2', " + RemnantTestDb.TENANT_ID + ", '" + takenOrder
                + "', 'confirmed', 0)");
        db.exec("INSERT INTO order_items (id, tenant_id, order_id, product_id, quantity,"
                + " processing_info) VALUES ('" + takenOrder + "-ITEM', " + RemnantTestDb.TENANT_ID
                + ", 'acc-5147-o2', '" + RemnantTestDb.PRODUCT_ID + "', 2,"
                + " '{\"specialOptions\":[\"余料带回-布\"]}'::jsonb)");
        service.accrue(RemnantTestDb.TENANT_ID, "JG-" + takenOrder, takenOrder, source, drafts);
        assertThat(db.scalar("SELECT COUNT(*) FROM fabric_remnants WHERE source_order_no = '"
                + takenOrder + "' AND status = 'customer_taken'").longValue())
                .as("🔴 客户带走的余料不入可用池（行业做法 1：本来就是客户的）").isEqualTo(2);
    }

    // ────────────────────────────────────────────── 判据：seeded 小件尺寸（可配参数）读面

    @Test
    @DisplayName("判据：小件尺寸表的默认值为**空**（未配置 ⇒ 读面显式说明；不是静默空表）")
    void specsDefaultToEmptyWithAVisibleNotice() {
        service.putSpecs(RemnantTestDb.TENANT_ID, List.of());
        RemnantViews.SpecsView empty = service.specs(RemnantTestDb.TENANT_ID);
        assertThat(empty.configured()).isFalse();
        assertThat(empty.notice()).isEqualTo(RemnantService.NOTICE_SPECS_UNCONFIGURED);
        assertThat(empty.notice()).contains("不产生匹配建议");

        // 同一读面：配了行之后必须**不再**说「未配置」（否则是把已配置报成未配置）
        RemnantItemSize saved = RemnantItemSize.builder().tenantId(RemnantTestDb.TENANT_ID)
                .itemKey("帘头制作").lengthM(new BigDecimal("1.20")).widthM(new BigDecimal("0.40"))
                .operator("system").deleted(0).build();
        db.mapperOf(com.migao.admin.mapper.RemnantItemSizeMapper.class).insert(saved);
        RemnantViews.SpecsView configured = service.specs(RemnantTestDb.TENANT_ID);
        assertThat(configured.configured()).isTrue();
        assertThat(configured.notice()).isNull();
        assertThat(configured.items().stream().map(RemnantViews.SpecLine::itemKey).toList())
                .containsExactly("帘头制作");
    }

    // ────────────────────────────────────────────── 工具

    private static String codeOf(Throwable failure) {
        return failure instanceof BusinessException business ? business.getCode() : null;
    }
}
