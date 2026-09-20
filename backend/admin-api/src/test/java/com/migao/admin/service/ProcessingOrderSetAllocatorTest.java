// case_ids: PG-018
package com.migao.admin.service;

import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper.ProcessingOrderSetRow;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 新单的套号分配器（切片 ⓪.5，issue #4789；设计 {@code docs/design/set-code-and-scan-loop.md}
 * §2.1 / §2.4 / §14.1）。
 *
 * <p><b>为什么这组断言必须存在</b>：设计 §2.4 给了 {@code allocate_set_index} 的算法，§11.3 给了
 * 存量回填的伪码，但 §14 的切片 ①~⑤ **没有一片认领「新单」的分配** ⇒ 落码时无人认领该动作
 * （#4725 实测：{@code processing_order_sets} 只有 V92 的回填在写）⇒ 新单无 {@code set_no}
 * ⇒ 码无从生成 ⇒ 二维码按钮对新单是空的、工人 H5 扫不到。本类是那个缺片的落码。</p>
 *
 * <p><b>红证（改前实测输出见 PR body / {@code acceptance/2026-09-20/4789-set-no-allocator/}）</b>：
 * ① **真库红**（本地 PG 16，逐字 DDL + 逐字 SQL）：改前（不跑分配器）⇒
 * {@code processing_order_sets} **0 行**、扫码 {@code selections} **空**、实例行 {@code set_no} 全空；
 * 改后 ⇒ 2 行套（1 樘窗 = 1 套）、扫码清单有 (套 × 部位)、部位码可直扫；
 * ② **注入式红证**（{@link #guardIsNotVacuousInjectedNumberPoolBreaksTheAssertion}）：
 * 把号池上界读数注入成 0 ⇒ 编号断言必红（判据不恒真）。</p>
 *
 * <p><b>本测试是行为断言，不是桩断言</b>：分组/编号/幂等判定走**真实实现**，只 mock Mapper。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProcessingOrderSetAllocator 新单套号分配（切片 ⓪.5）")
class ProcessingOrderSetAllocatorTest {

    private static final Long TENANT = 1L;
    private static final String PO_ID = "po-4789";
    private static final String PO_NO = "JG-20260920-0001";

    @Mock
    private ProcessingOrderSetMapper orderSetMapper;

    private ProcessingOrderSetAllocator allocator() {
        return new ProcessingOrderSetAllocator(orderSetMapper);
    }

    private ProcessingOrder po() {
        return ProcessingOrder.builder()
                .id(PO_ID)
                .tenantId(TENANT)
                .processingOrderNo(PO_NO)
                .deleted(0)
                .build();
    }

    /** 快照行（只落分组要用的三个键；其余键与本判据无关）。 */
    private static Map<String, Object> row(String itemId, String craftLineId, String componentRole) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("itemId", itemId);
        if (craftLineId != null) {
            entry.put("craftLineId", craftLineId);
        }
        if (componentRole != null) {
            entry.put("componentRole", componentRole);
        }
        entry.put("processingItems", List.of(Map.of("name", "韩褶")));
        return entry;
    }

    /** 一樘「布 + 纱 + 帘头」（同 craftLineId）+ 一樘独立窗（无 craftLineId）。 */
    private static List<Map<String, Object>> twoWindowsSnapshot() {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        snapshot.add(row("i-1", "cl-A", null));
        snapshot.add(row("i-2", "cl-A", "纱"));
        snapshot.add(row("i-3", "cl-A", null));
        snapshot.add(row("i-9", null, null));
        return snapshot;
    }

    @Test
    @DisplayName("一樘窗（布+纱+帘头）⇒ 1 行套 + set_no = {单号}-001（**一套 = 一樘窗**，不是 3 行）")
    void oneWindowAllocatesOneSetWithDesignNumberFormat() {
        when(orderSetMapper.lockSetsOfOrder(TENANT, PO_ID)).thenReturn(List.of());
        when(orderSetMapper.selectMaps(any())).thenReturn(List.of(java.util.Collections.singletonMap("set_index", null)));
        when(orderSetMapper.selectList(any())).thenReturn(List.of(
                setRow("s-1", 1, PO_NO + "-001", "cl-A")));

        List<ProcessingOrderSet> sets = allocator().ensureSets(po(), twoWindowsSnapshot(), TENANT);

        assertThat(sets).hasSize(1);
        assertThat(sets.get(0).getSetNo()).isEqualTo(PO_NO + "-001");
    }

    @Test
    @DisplayName("落库的 set_index / set_no / craft_line_id / position_item_ids 逐值符合设计口径")
    void insertCarriesDesignColumns() {
        when(orderSetMapper.lockSetsOfOrder(TENANT, PO_ID)).thenReturn(List.of());
        when(orderSetMapper.selectMaps(any())).thenReturn(List.of(java.util.Collections.singletonMap("set_index", null)));
        when(orderSetMapper.selectList(any())).thenReturn(List.of());

        allocator().ensureSets(po(), twoWindowsSnapshot(), TENANT);

        ArgumentCaptor<ProcessingOrderSetRow> captor =
                ArgumentCaptor.forClass(ProcessingOrderSetRow.class);
        verify(orderSetMapper, times(2)).insertIgnoreConflict(captor.capture());
        List<ProcessingOrderSetRow> rows = captor.getAllValues();

        // 樘窗组顺序 = 快照出现次序（§11.3）；编号 1 起、3 位零填充（§2.1）
        assertThat(rows.get(0).setIndex()).isEqualTo(1);
        assertThat(rows.get(0).setNo()).isEqualTo(PO_NO + "-001");
        assertThat(rows.get(0).craftLineId()).isEqualTo("cl-A");
        // 有序部位清单（V92 的 jsonb_agg(... ORDER BY ord) 同形）；配布边被吸收的形态见下一条
        assertThat(rows.get(0).positionItemIdsJson()).isEqualTo("[\"i-1\",\"i-2\",\"i-3\"]");
        assertThat(rows.get(1).setIndex()).isEqualTo(2);
        assertThat(rows.get(1).setNo()).isEqualTo(PO_NO + "-002");
        // 无 craftLineId ⇒ 回落本行 itemId（各自成樘窗，不并组）
        assertThat(rows.get(1).craftLineId()).isEqualTo("i-9");
        assertThat(rows.get(1).positionItemIdsJson()).isEqualTo("[\"i-9\"]");
    }

    @Test
    @DisplayName("配布边行被同组主布行吸收 ⇒ 不独立成窗，且不进 position_item_ids（与 V92 同口径）")
    void absorbedEdgeRowDoesNotFormOwnWindow() {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        snapshot.add(row("i-1", "cl-A", null));
        snapshot.add(row("i-2", "cl-A", "配布边"));
        when(orderSetMapper.lockSetsOfOrder(TENANT, PO_ID)).thenReturn(List.of());
        when(orderSetMapper.selectMaps(any())).thenReturn(List.of(java.util.Collections.singletonMap("set_index", null)));
        when(orderSetMapper.selectList(any())).thenReturn(List.of());

        allocator().ensureSets(po(), snapshot, TENANT);

        ArgumentCaptor<ProcessingOrderSetRow> captor =
                ArgumentCaptor.forClass(ProcessingOrderSetRow.class);
        verify(orderSetMapper, times(1)).insertIgnoreConflict(captor.capture());
        assertThat(captor.getValue().positionItemIdsJson()).isEqualTo("[\"i-1\"]");
    }

    @Test
    @DisplayName("幂等：已有 live 套行 ⇒ 一行都不插、不重编号（**历史单零变化**）")
    void existingSetsAreNeverTouched() {
        ProcessingOrderSet historical = setRow("poset-v92-abc", 7, PO_NO + "-007", "cl-A");
        when(orderSetMapper.lockSetsOfOrder(TENANT, PO_ID)).thenReturn(List.of(historical));

        List<ProcessingOrderSet> sets = allocator().ensureSets(po(), twoWindowsSnapshot(), TENANT);

        assertThat(sets).containsExactly(historical);
        assertThat(sets.get(0).getSetIndex()).as("不重编号").isEqualTo(7);
        assertThat(sets.get(0).getSetNo()).as("不改号").isEqualTo(PO_NO + "-007");
        verify(orderSetMapper, never()).insertIgnoreConflict(any());
        verify(orderSetMapper, never()).selectMaps(any());
    }

    @Test
    @DisplayName("只增不复用：MAX(set_index) 的查询**不带 deleted = 0**（软删行仍占号，§2.4 规则 1）")
    void numberPoolIsMonotonicAcrossSoftDelete() {
        when(orderSetMapper.lockSetsOfOrder(TENANT, PO_ID)).thenReturn(List.of());
        // 号池上界 = 2（含软删行）⇒ 下一个必须是 3，不是 1
        when(orderSetMapper.selectMaps(any())).thenReturn(List.of(Map.of("set_index", 2)));
        when(orderSetMapper.selectList(any())).thenReturn(List.of());

        allocator().ensureSets(po(), List.of(row("i-1", null, null)), TENANT);

        ArgumentCaptor<ProcessingOrderSetRow> captor =
                ArgumentCaptor.forClass(ProcessingOrderSetRow.class);
        verify(orderSetMapper).insertIgnoreConflict(captor.capture());
        assertThat(captor.getValue().setIndex()).isEqualTo(3);
        assertThat(captor.getValue().setNo()).isEqualTo(PO_NO + "-003");
    }

    @Test
    @DisplayName(">999 樘窗 ⇒ 显式拒绝（BusinessException），不静默截断、且**一行都不插**")
    void overNineHundredNinetyNineIsExplicitlyRejected() {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        for (int i = 0; i < 1000; i++) {
            snapshot.add(row("i-" + i, null, null));
        }
        when(orderSetMapper.lockSetsOfOrder(TENANT, PO_ID)).thenReturn(List.of());

        assertThatThrownBy(() -> allocator().ensureSets(po(), snapshot, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("超过 999 套上限");
        verify(orderSetMapper, never()).insertIgnoreConflict(any());
    }

    @Test
    @DisplayName("快照为空 ⇒ 不猜、不分配（与 V92「解析失败 ⇒ 跳过该单」同口径）")
    void emptySnapshotAllocatesNothing() {
        when(orderSetMapper.lockSetsOfOrder(TENANT, PO_ID)).thenReturn(List.of());

        assertThat(allocator().ensureSets(po(), List.of(), TENANT)).isEmpty();

        verify(orderSetMapper, never()).insertIgnoreConflict(any());
    }

    @Test
    @DisplayName("并发保护：先锁该单号池（`SELECT … FOR UPDATE`）再读 MAX —— 锁必须先于号池上界查询")
    void locksOrderNumberPoolBeforeReadingMax() {
        when(orderSetMapper.lockSetsOfOrder(TENANT, PO_ID)).thenReturn(List.of());
        when(orderSetMapper.selectMaps(any())).thenReturn(List.of(Map.of("set_index", 0)));
        when(orderSetMapper.selectList(any())).thenReturn(List.of());

        allocator().ensureSets(po(), List.of(row("i-1", null, null)), TENANT);

        var order = org.mockito.Mockito.inOrder(orderSetMapper);
        order.verify(orderSetMapper).lockSetsOfOrder(eq(TENANT), eq(PO_ID));
        order.verify(orderSetMapper).selectMaps(any());
        order.verify(orderSetMapper).insertIgnoreConflict(any());
    }

    @Test
    @DisplayName("分组口径与 V92 同源：无 processingItems 的行不成窗；组顺序 = 快照次序")
    void rowsWithoutProcessingItemsDoNotFormWindows() {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        Map<String, Object> noItems = new LinkedHashMap<>();
        noItems.put("itemId", "i-x");
        snapshot.add(noItems);
        snapshot.add(row("i-2", "cl-B", null));
        when(orderSetMapper.lockSetsOfOrder(TENANT, PO_ID)).thenReturn(List.of());
        when(orderSetMapper.selectMaps(any())).thenReturn(List.of(java.util.Collections.singletonMap("set_index", null)));
        when(orderSetMapper.selectList(any())).thenReturn(List.of());

        allocator().ensureSets(po(), snapshot, TENANT);

        ArgumentCaptor<ProcessingOrderSetRow> captor =
                ArgumentCaptor.forClass(ProcessingOrderSetRow.class);
        verify(orderSetMapper, times(1)).insertIgnoreConflict(captor.capture());
        assertThat(captor.getValue().craftLineId()).isEqualTo("cl-B");
    }

    /**
     * **判据不许恒真**（注入式红证，{@code migao-acceptance} 的「不会红的断言 = 空断言」）。
     *
     * <p>判据 = {@link #numberPoolIsMonotonicAcrossSoftDelete} 里那句
     * {@code assertThat(captor.getValue().setIndex()).isEqualTo(3)}。</p>
     *
     * <p>注入点 = **号池上界读数**（`SELECT MAX(set_index)` 的返回值）：这是唯一能让「MAX+1」退化成
     * 「复用已删号」的输入。把同一份快照在**真实现**上跑两遍 —— 一遍喂真上界 2、一遍喂注入值 1 ——
     * 断言两次得到的编号**确实不同**（= 那句断言对号池读数敏感，不是恒真的）。</p>
     */
    @Test
    @DisplayName("注入式红证：把号池上界读数注入成 1 ⇒ 编号断言必红（判据不恒真）")
    void guardIsNotVacuousInjectedNumberPoolBreaksTheAssertion() {
        int realNumber = allocatedSetIndexFor(List.of(Map.of("set_index", 2)));
        int injectedNumber = allocatedSetIndexFor(List.of(Map.of("set_index", 0)));

        assertThat(realNumber).as("真上界 2 ⇒ 分配 3").isEqualTo(3);
        assertThat(injectedNumber)
                .as("注入上界 0 ⇒ 分配 1；与 3 不等 ⇒ numberPoolIsMonotonicAcrossSoftDelete 会红")
                .isEqualTo(1);
        assertThat(realNumber)
                .as("两次读数必须产生**不同**结果（否则那句断言是恒真的）")
                .isNotEqualTo(injectedNumber);
    }

    /** 用真实现跑一次分配，返回它实际写出的 `set_index`（注入红证用）。 */
    private int allocatedSetIndexFor(List<Map<String, Object>> maxRows) {
        ProcessingOrderSetAllocator fresh = new ProcessingOrderSetAllocator(orderSetMapper);
        when(orderSetMapper.lockSetsOfOrder(TENANT, PO_ID)).thenReturn(List.of());
        when(orderSetMapper.selectMaps(any())).thenReturn(maxRows);
        when(orderSetMapper.selectList(any())).thenReturn(List.of());
        fresh.ensureSets(po(), List.of(row("i-1", null, null)), TENANT);
        ArgumentCaptor<ProcessingOrderSetRow> captor =
                ArgumentCaptor.forClass(ProcessingOrderSetRow.class);
        verify(orderSetMapper, org.mockito.Mockito.atLeastOnce()).insertIgnoreConflict(captor.capture());
        return captor.getValue().setIndex();
    }

    private static ProcessingOrderSet setRow(String id, int setIndex, String setNo, String craftLineId) {
        return ProcessingOrderSet.builder()
                .id(id)
                .tenantId(TENANT)
                .processingOrderId(PO_ID)
                .setIndex(setIndex)
                .setNo(setNo)
                .craftLineId(craftLineId)
                .deleted(0)
                .build();
    }
}
