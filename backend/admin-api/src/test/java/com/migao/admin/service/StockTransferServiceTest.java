// case_ids: WH-001
package com.migao.admin.service;

import com.migao.admin.dto.StockTransferRequest;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StockTransferItemMapper;
import com.migao.admin.mapper.StockTransferMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 调拨服务（issue #7373 段 1）—— 即时调拨的三条约束与「缸号不丢」。
 *
 * <p>调拨对象是**一缸布**（批次的 `warehouse` 文本改成调入仓编码），不是「某 SKU 几米」：
 * 缸号（`dyeLot`）与成本（`unitCost`）随行不动，所以调拨后仍可追溯到缸。</p>
 */
@DisplayName("调拨服务：仓校验 / 可调量 / 缸号与成本随行 / 同仓拒")
class StockTransferServiceTest {

    private StockTransferMapper transferMapper;
    private StockTransferItemMapper itemMapper;
    private StockBatchMapper stockBatchMapper;
    private WarehouseService warehouseService;
    private StockTransferService service;

    private static final Warehouse FROM = warehouse(1L, "WH-A");
    private static final Warehouse TO = warehouse(2L, "WH-B");

    private static Warehouse warehouse(Long id, String code) {
        Warehouse w = new Warehouse();
        w.setId(id);
        w.setTenantId(1L);
        w.setCode(code);
        w.setName(code);
        w.setWarehouseType(Warehouse.TYPE_STORE);
        return w;
    }

    private static StockBatch batch(Long id, String warehouseCode, String qty) {
        StockBatch b = new StockBatch();
        b.setId(id);
        b.setTenantId(1L);
        b.setBatchNo("PC-20261021-000" + id);
        b.setWarehouse(warehouseCode);
        b.setQuantity(new BigDecimal(qty));
        b.setUnitCost(new BigDecimal("12.3456"));
        b.setDyeLot("LOT-777");
        b.setSkuCode("SKU-1");
        return b;
    }

    @BeforeEach
    void setUp() {
        transferMapper = Mockito.mock(StockTransferMapper.class);
        itemMapper = Mockito.mock(StockTransferItemMapper.class);
        stockBatchMapper = Mockito.mock(StockBatchMapper.class);
        warehouseService = Mockito.mock(WarehouseService.class);
        com.migao.admin.time.BusinessClock clock = new com.migao.admin.time.BusinessClock();
        service = new StockTransferService(transferMapper, itemMapper, stockBatchMapper, warehouseService, clock);
        when(warehouseService.require(1L)).thenReturn(FROM);
        when(warehouseService.require(2L)).thenReturn(TO);
        when(stockBatchMapper.updateById(org.mockito.ArgumentMatchers.<StockBatch>any())).thenReturn(1);
    }

    private static StockTransferRequest request(Long fromId, Long toId, Long batchId, String qty) {
        StockTransferRequest req = new StockTransferRequest();
        req.setFromWarehouseId(fromId);
        req.setToWarehouseId(toId);
        StockTransferRequest.Line line = new StockTransferRequest.Line();
        line.setBatchId(batchId);
        line.setQty(new BigDecimal(qty));
        req.setItems(List.of(line));
        return req;
    }

    @Test
    @DisplayName("正常调拨：批次归属仓改成调入仓，**数量与缸号一字不动**（守恒 + 可追溯）")
    void transferMovesWarehouseButKeepsQtyAndDyeLot() {
        StockBatch b = batch(10L, "WH-A", "100");
        when(stockBatchMapper.selectById(10L)).thenReturn(b);

        var view = service.transfer(request(1L, 2L, 10L, "30"), 1L);

        assertThat(b.getWarehouse()).as("归属仓改成调入仓").isEqualTo("WH-B");
        assertThat(b.getQuantity()).as("🔴 数量一字不动（守恒）").isEqualByComparingTo("100");
        assertThat(b.getDyeLot()).as("缸号随行不丢").isEqualTo("LOT-777");
        assertThat(b.getUnitCost()).as("成本随行不重算").isEqualByComparingTo("12.3456");
        assertThat(view.getStatus()).isEqualTo("completed");
        assertThat(view.getItems()).hasSize(1);
        assertThat(view.getItems().get(0).getBatchNo()).isEqualTo(b.getBatchNo());
    }

    @Test
    @DisplayName("同仓调拨拒（无意义，且会掩盖写错仓）")
    void sameWarehouseRejected() {
        assertThatThrownBy(() -> service.transfer(request(1L, 1L, 10L, "10"), 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("同一个仓");
    }

    @Test
    @DisplayName("批次不在调出仓 ⇒ 拒（写错仓 / 已调走，两种都必须拦）")
    void batchNotInFromWarehouseRejected() {
        when(stockBatchMapper.selectById(10L)).thenReturn(batch(10L, "WH-Z", "100"));

        assertThatThrownBy(() -> service.transfer(request(1L, 2L, 10L, "10"), 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不在调出仓");
    }

    @Test
    @DisplayName("可调量不足 ⇒ 拒，且提示现有量与本次量（段 1 不做负库存）")
    void overAvailableRejected() {
        when(stockBatchMapper.selectById(10L)).thenReturn(batch(10L, "WH-A", "20"));

        assertThatThrownBy(() -> service.transfer(request(1L, 2L, 10L, "20.1"), 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("可调量不足");
    }

    @Test
    @DisplayName("空明细 ⇒ 拒（不产生空转调拨单）")
    void emptyItemsRejected() {
        StockTransferRequest req = request(1L, 2L, 10L, "1");
        req.setItems(List.of());
        assertThatThrownBy(() -> service.transfer(req, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("至少");
    }

    @Test
    @DisplayName("批次不存在 ⇒ 404 语义")
    void missingBatchIsNotFound() {
        when(stockBatchMapper.selectById(99L)).thenReturn(null);
        assertThatThrownBy(() -> service.transfer(request(1L, 2L, 99L, "1"), 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("批次");
    }
}
