// case_ids: STK-001
package com.migao.admin.service;

import com.migao.admin.entity.Approval;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.Stocktake;
import com.migao.admin.entity.StocktakeItem;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StocktakeItemMapper;
import com.migao.admin.mapper.StocktakeMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * 盘点服务（issue #7373 段 2）—— 三件最贵的事：账面快照、差异审批闸门、调整只改数量。
 *
 * <p>每条都对应一个真实风险：</p>
 * <ol>
 *   <li><b>账面快照</b>：不留快照，事后无法解释「为什么当时判它少了 3 米」；</li>
 *   <li><b>差异必须有审批</b>：没闸门 = 谁都能把账面改成实物（也可能反过来掩盖丢失）；</li>
 *   <li><b>调整只改数量</b>：顺手改成本 ⇒ 毛利凭空变化，且没人能解释（成本口径在 P0-3）。</li>
 * </ol>
 */
@DisplayName("盘点服务：出任务快照 / 录实盘 / 差异审批闸门 / 只改数量 / 完成并发")
class StocktakeServiceTest {

    private StocktakeMapper stocktakeMapper;
    private StocktakeItemMapper itemMapper;
    private StockBatchMapper stockBatchMapper;
    private WarehouseService warehouseService;
    private ApprovalService approvalService;
    private StocktakeService service;

    private static final Warehouse WAREHOUSE = warehouse();

    private static Warehouse warehouse() {
        Warehouse w = new Warehouse();
        w.setId(1L);
        w.setTenantId(7L);
        w.setCode("WH-A");
        w.setName("门店仓");
        return w;
    }

    private static StockBatch batch(Long id, String qty) {
        StockBatch b = new StockBatch();
        b.setId(id);
        b.setTenantId(7L);
        b.setBatchNo("PC-000" + id);
        b.setWarehouse("WH-A");
        b.setQuantity(new BigDecimal(qty));
        b.setUnitCost(new BigDecimal("12.3456"));
        return b;
    }

    private static Stocktake stocktake(String status) {
        return Stocktake.builder().id("ST-1").tenantId(7L).stocktakeNo("PD20261021-0001")
                .warehouseId(1L).status(status).build();
    }

    @BeforeEach
    void setUp() {
        // Lambda 缓存：`LambdaUpdateWrapper` 需要 MyBatis-Plus 的实体元数据（纯单测里没有容器 ⇒ 手工建一次）。
        // 踩过的坑：不建则抛 `MybatisPlus can not find lambda cache for this entity` —— 那不是业务失败。
        com.baomidou.mybatisplus.core.MybatisConfiguration configuration =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, ""), Stocktake.class);
        stocktakeMapper = Mockito.mock(StocktakeMapper.class);
        itemMapper = Mockito.mock(StocktakeItemMapper.class);
        stockBatchMapper = Mockito.mock(StockBatchMapper.class);
        warehouseService = Mockito.mock(WarehouseService.class);
        approvalService = Mockito.mock(ApprovalService.class);
        service = new StocktakeService(stocktakeMapper, itemMapper, stockBatchMapper,
                warehouseService, approvalService, new com.migao.admin.time.BusinessClock());
        when(warehouseService.require(1L)).thenReturn(WAREHOUSE);
    }

    @Test
    @DisplayName("出任务：账面数取自**当刻**批次量，逐批次落明细")
    void openSnapshotsBookQty() {
        when(stocktakeMapper.selectList(any())).thenReturn(List.of());
        when(stockBatchMapper.selectList(any())).thenReturn(List.of(batch(10L, "100"), batch(11L, "50")));

        var view = service.open(1L, "月末盘点", null);

        assertThat(view.getStatus()).isEqualTo("counting");
        assertThat(view.getItems()).hasSize(2);
        assertThat(view.getItems().get(0).getBookQty()).isEqualByComparingTo("100");
        Mockito.verify(itemMapper, Mockito.times(2)).insert(any(StocktakeItem.class));
    }

    @Test
    @DisplayName("同一仓已有进行中的盘点 ⇒ 拒（谁的结果算数必须由系统回答）")
    void openRejectsSecondOpenStocktake() {
        when(stocktakeMapper.selectList(any())).thenReturn(List.of(stocktake("counting")));

        assertThatThrownBy(() -> service.open(1L, null, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("进行中的盘点");
    }

    @Test
    @DisplayName("录实盘：差异 = 实盘 − 账面，落库带回读数")
    void recordComputesDiff() {
        when(stocktakeMapper.selectById("ST-1")).thenReturn(stocktake("counting"));
        StocktakeItem item = StocktakeItem.builder().id(1L).stocktakeId("ST-1").batchId(10L)
                .batchNo("PC-00010").bookQty(new BigDecimal("100")).build();
        when(itemMapper.selectList(any())).thenReturn(List.of(item));
        when(itemMapper.updateById(org.mockito.ArgumentMatchers.<StocktakeItem>any())).thenReturn(1);

        Map<Long, BigDecimal> counts = new HashMap<>();
        counts.put(10L, new BigDecimal("97"));
        service.record("ST-1", counts);

        assertThat(item.getCountedQty()).isEqualByComparingTo("97");
        assertThat(item.getDiffQty()).as("盘亏 3 米").isEqualByComparingTo("-3");
    }

    @Test
    @DisplayName("录实盘：负数实盘拒（未数就不录，不许填 0 或负数）")
    void recordRejectsNegative() {
        when(stocktakeMapper.selectById("ST-1")).thenReturn(stocktake("counting"));
        when(itemMapper.selectList(any())).thenReturn(List.of(StocktakeItem.builder()
                .id(1L).stocktakeId("ST-1").batchId(10L).batchNo("PC-00010")
                .bookQty(new BigDecimal("100")).build()));

        Map<Long, BigDecimal> counts = new HashMap<>();
        counts.put(10L, new BigDecimal("-1"));
        assertThatThrownBy(() -> service.record("ST-1", counts))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("必须 ≥ 0");
    }

    @Test
    @DisplayName("🔴 有差异但没有已通过的盘点差异审批 ⇒ 完成时**直接拒**（写面拒绝，不是前端提示）")
    void completeRejectsDiffWithoutApproval() {
        when(stocktakeMapper.selectById("ST-1")).thenReturn(stocktake("counting"));
        when(itemMapper.selectList(any())).thenReturn(List.of(StocktakeItem.builder()
                .id(1L).stocktakeId("ST-1").batchId(10L).batchNo("PC-00010")
                .bookQty(new BigDecimal("100")).countedQty(new BigDecimal("97"))
                .diffQty(new BigDecimal("-3")).build()));
        when(approvalService.consume(eq(Approval.TYPE_STOCKTAKE_DIFF), anyString(), any(), any()))
                .thenReturn(null);

        assertThatThrownBy(() -> service.complete("ST-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("必须")
                .hasMessageContaining("stocktake_diff");
    }

    @Test
    @DisplayName("🔴 有差异且有审批 ⇒ 调整批次数量，且**不动成本**（盘点不是成本重估）")
    void completeAppliesDiffAndKeepsCost() {
        when(stocktakeMapper.selectById("ST-1")).thenReturn(stocktake("counting"));
        when(itemMapper.selectList(any())).thenReturn(List.of(StocktakeItem.builder()
                .id(1L).stocktakeId("ST-1").batchId(10L).batchNo("PC-00010")
                .bookQty(new BigDecimal("100")).countedQty(new BigDecimal("97"))
                .diffQty(new BigDecimal("-3")).build()));
        when(approvalService.consume(eq(Approval.TYPE_STOCKTAKE_DIFF), anyString(), any(), any()))
                .thenReturn("AP-1");
        StockBatch batch = batch(10L, "100");
        when(stockBatchMapper.selectById(10L)).thenReturn(batch);
        when(stockBatchMapper.updateById(org.mockito.ArgumentMatchers.<StockBatch>any())).thenReturn(1);
        when(stocktakeMapper.update(any(), any())).thenReturn(1);

        service.complete("ST-1");

        assertThat(batch.getQuantity()).as("盘亏后 = 97").isEqualByComparingTo("97");
        assertThat(batch.getUnitCost()).as("🔴 成本快照一字不动").isEqualByComparingTo("12.3456");
    }

    @Test
    @DisplayName("没有差异 ⇒ 直接完成（不逼人审批「账实相符」）")
    void completeWithoutDiffNeedsNoApproval() {
        when(stocktakeMapper.selectById("ST-1")).thenReturn(stocktake("counting"));
        when(itemMapper.selectList(any())).thenReturn(List.of(StocktakeItem.builder()
                .id(1L).stocktakeId("ST-1").batchId(10L).batchNo("PC-00010")
                .bookQty(new BigDecimal("100")).countedQty(new BigDecimal("100"))
                .diffQty(BigDecimal.ZERO).build()));
        when(stocktakeMapper.update(any(), any())).thenReturn(1);

        service.complete("ST-1");

        Mockito.verify(approvalService, Mockito.never()).consume(any(), any(), any(), any());
    }

    @Test
    @DisplayName("还有批次没录 ⇒ 拒（没数不等于「数了正好一样」）")
    void completeRejectsUncountedLines() {
        when(stocktakeMapper.selectById("ST-1")).thenReturn(stocktake("counting"));
        when(itemMapper.selectList(any())).thenReturn(List.of(StocktakeItem.builder()
                .id(1L).stocktakeId("ST-1").batchId(10L).batchNo("PC-00010")
                .bookQty(new BigDecimal("100")).build()));

        assertThatThrownBy(() -> service.complete("ST-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("没录实盘");
    }

    @Test
    @DisplayName("调整后为负 ⇒ 拒（盘亏不能把库存调成负数）")
    void completeRejectsNegativeResult() {
        when(stocktakeMapper.selectById("ST-1")).thenReturn(stocktake("counting"));
        when(itemMapper.selectList(any())).thenReturn(List.of(StocktakeItem.builder()
                .id(1L).stocktakeId("ST-1").batchId(10L).batchNo("PC-00010")
                .bookQty(new BigDecimal("10")).countedQty(BigDecimal.ZERO)
                .diffQty(new BigDecimal("-10")).build()));
        when(approvalService.consume(eq(Approval.TYPE_STOCKTAKE_DIFF), anyString(), any(), any()))
                .thenReturn("AP-1");
        // 期间别人把账面数改小了 ⇒ 再减就成负数
        when(stockBatchMapper.selectById(10L)).thenReturn(batch(10L, "5"));

        assertThatThrownBy(() -> service.complete("ST-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("负数");
    }

    @Test
    @DisplayName("完成时 CAS 落空（别人先完成了）⇒ 明确报错，不静默覆盖")
    void completeLosesCas() {
        when(stocktakeMapper.selectById("ST-1")).thenReturn(stocktake("counting"));
        when(itemMapper.selectList(any())).thenReturn(List.of(StocktakeItem.builder()
                .id(1L).stocktakeId("ST-1").batchId(10L).batchNo("PC-00010")
                .bookQty(new BigDecimal("100")).countedQty(new BigDecimal("100"))
                .diffQty(BigDecimal.ZERO).build()));
        when(stocktakeMapper.update(any(), any())).thenReturn(0);

        assertThatThrownBy(() -> service.complete("ST-1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("刚被别人完成");
    }
}
