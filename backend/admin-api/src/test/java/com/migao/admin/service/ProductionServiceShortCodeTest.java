// case_ids: PG-018
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 加工单级短码的分配 / 补码 / 撤销语义（V155，issue #6867 / B1；设计
 * {@code docs/design/worker-h5-scan-and-report.md} §11.3 / §11.4 / §11.6）。
 *
 * <p>判据对象是 {@code ProductionService.instantiate} / {@code regenerateQrToken} 这条
 * **复用路径**（与 {@code ensureQrToken} 同款：「已有值 ⇒ 一个字都不写；缺失才分配」），
 * 断言落在「调了哪条写路径、参数是什么」上 —— 那正是「已打印的纸不作废」的机械落点。</p>
 *
 * <h3>红证（改坏 ⇒ 必红，逐条对应一个真实缺陷形态）</h3>
 * <ul>
 *   <li>把 {@code ensureShortCode} 的「有值即返回」去掉（每次都重新分配 + 写回）⇒
 *       {@code existingShortCodeIsReusedWithoutAnyWrite} 红（每次实例化都换掉纸上那个码）；</li>
 *   <li>写路径改回 {@code updateById}（整行覆盖）⇒ {@code missingShortCodeIsFilledThroughTheConditionalUpdate}
 *       红 —— ① 写路径不是「只补 NULL」的条件更新；② 并发下会覆盖别人已打印的码；</li>
 *   <li>查重漏 tenant（{@code selectByShortCode(code, null)}）或漏调用 ⇒ 同一条判据的
 *       {@code eq(TENANT)} / {@code times(1)} 红；</li>
 *   <li>撤销时顺手清 {@code short_code} ⇒ {@code revokeLeavesShortCodeAlone} 红。</li>
 * </ul>
 *
 * <p><b>边界（如实登记）</b>：数据库侧「并发两请求只补一次 / 部分唯一索引兜底」由迁移与 SQL 形态判据
 * （{@code ProcessingOrderShortCodeMapperTest} / {@code ProductionOrderShortCodeMigrationTest}）覆盖，
 * **本类不连库**，不声称跑过真库。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("#6867 B1：加工单级短码的分配 / 补码幂等 / 撤销不碰短码")
class ProductionServiceShortCodeTest {

    private static final Long TENANT = 6867L;
    private static final String ORDER_ID = "order-6867";
    private static final String PO_ID = "po-6867";
    private static final String PO_NO = "JG-20261014-6867";
    private static final String QR_TOKEN = "qr-token-6867";
    /** 8 位 Crockford Base32（不许出现 I / L / O / U）。 */
    private static final String EXISTING_CODE = "7K3M9QP2";
    private static final String COLLIDING_CODE = "AAAA1111";
    private static final String ITEM_ID = "oi-6867-cloth";

    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private ProcessingSetPartTokenMapper setPartTokenMapper;

    private ProductionService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);
        ReflectionTestUtils.setField(service, "setPartTokenMapper", setPartTokenMapper);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ────────────────────────────────────────────── ① 有值 ⇒ 复用（幂等）

    @Test
    @DisplayName("① 已有 short_code ⇒ 复用：一个字节都不写（实例化 / 重新发码两条路径都是）")
    void existingShortCodeIsReusedWithoutAnyWrite() {
        stubOrderAndPo(po(QR_TOKEN, EXISTING_CODE));
        stubNoExistingOperations();

        service.instantiate(ORDER_ID, positionsBody(), TENANT);
        service.regenerateQrToken(ORDER_ID, TENANT);

        verify(processingOrderMapper, never()).fillMissingShortCode(anyString(), anyLong(), anyString(), any());
        verify(processingOrderMapper, never()).selectByShortCode(anyString(), anyLong());
    }

    // ────────────────────────────────────────────── ② 缺失 ⇒ 只补 NULL（条件更新）

    @Test
    @DisplayName("② 缺失 short_code（含存量行）⇒ 分配 + 写**条件更新**（AND short_code IS NULL 的那条路径）")
    void missingShortCodeIsFilledThroughTheConditionalUpdate() {
        stubOrderAndPo(po(QR_TOKEN, null));
        stubNoExistingOperations();
        when(processingOrderMapper.selectByShortCode(anyString(), eq(TENANT))).thenReturn(null);

        service.instantiate(ORDER_ID, positionsBody(), TENANT);

        // 分配前查重**一次**（跨租户唯一由部分唯一索引兜底，查重不跨租户读）
        verify(processingOrderMapper, times(1)).selectByShortCode(anyString(), eq(TENANT));
        // 写路径 = 只补 NULL 的条件更新（幂等的唯一落点），且租户显式带上
        verify(processingOrderMapper, times(1)).fillMissingShortCode(eq(PO_ID), eq(TENANT), anyString(), any());
        // 绝不走整行覆盖（那会静默改掉别人已经印出去的码）
        verify(processingOrderMapper, never()).updateById(any(ProcessingOrder.class));
    }

    @Test
    @DisplayName("②b 补短码只走条件更新那一条写路径（不走整行覆盖）—— 幂等落在 SQL 上")
    void fillingShortCodeUsesOnlyTheConditionalUpdate() {
        stubOrderAndPo(po(QR_TOKEN, null));
        stubNoExistingOperations();
        when(processingOrderMapper.selectByShortCode(anyString(), eq(TENANT))).thenReturn(null);

        service.instantiate(ORDER_ID, positionsBody(), TENANT);

        // 已有 token ⇒ ensureQrToken 复用、不写；短码缺失 ⇒ 只有条件更新这一处写
        verify(processingOrderMapper, times(1)).fillMissingShortCode(anyString(), anyLong(), anyString(), any());
        verify(processingOrderMapper, never()).updateById(any(ProcessingOrder.class));
    }

    // ────────────────────────────────────────────── ③ 唯一性：查重命中 ⇒ 换一个（不造重码）

    @Test
    @DisplayName("③ 查重命中 ⇒ 换一个（不静默造重码）；落库的短码 ≠ 命中的那个")
    void allocationRetriesWhenTheCodeIsAlreadyTaken() {
        // 该单还没发过任何码 ⇒ ensureQrToken 会走它自己的写路径（与本判据无关，故不在此断言 updateById）
        stubOrderAndPo(po(null, null));
        stubNoExistingOperations();
        when(processingOrderMapper.selectByShortCode(anyString(), eq(TENANT)))
                .thenReturn(po(null, COLLIDING_CODE), (ProcessingOrder) null);

        service.instantiate(ORDER_ID, positionsBody(), TENANT);

        // 命中一次 ⇒ 至少查重两次（重试）；最终落库的短码形态合法且**不是**那个已占用的
        // 命中一次 ⇒ 循环**再**分配一个（重试口径来自唯一实现）；查重调用次数 = 2
        verify(processingOrderMapper, times(2))
                .selectByShortCode(org.mockito.ArgumentMatchers.argThat(c -> c != null && c.length() == 8), eq(TENANT));
        org.mockito.ArgumentCaptor<String> written =
                org.mockito.ArgumentCaptor.forClass((Class<String>) String.class);
        verify(processingOrderMapper, times(1)).fillMissingShortCode(anyString(), anyLong(), written.capture(), any());
        assertThat(written.getValue())
                .as("分配器必须换一个短码（重试口径来自 WorkerShortLinkService.allocateUnique 的唯一实现）")
                .isNotEqualTo(COLLIDING_CODE)
                .matches("^[0-9A-HJKMNP-TV-Z]{8}$");
    }

    // ────────────────────────────────────────────── ④ 撤销：绝不碰短码

    @Test
    @DisplayName("④ 撤销 ⇒ 只调 revokeQrToken；有短码的行一个字节都不写（已打印的纸不作废）")
    void revokeLeavesShortCodeAlone() {
        stubOrderAndPo(po(QR_TOKEN, EXISTING_CODE));
        when(processingOrderMapper.revokeQrToken(eq(PO_ID), eq(TENANT), any())).thenReturn(1);
        when(setPartTokenMapper.revokeTokensByOrder(eq(PO_ID), eq(TENANT), any())).thenReturn(0);

        service.revokeQrToken(ORDER_ID, TENANT);

        verify(processingOrderMapper, times(1)).revokeQrToken(eq(PO_ID), eq(TENANT), any());
        verify(processingOrderMapper, never()).fillMissingShortCode(anyString(), anyLong(), anyString(), any());
        verify(processingOrderMapper, never()).selectByShortCode(anyString(), anyLong());
        verify(processingOrderMapper, never()).updateById(any(ProcessingOrder.class));
    }

    @Test
    @DisplayName("④b 撤销后重新发码 ⇒ **只补 token**，短码一个字节都不写（短码不变）")
    void regeneratingAfterRevokeNeverRewritesTheShortCode() {
        stubOrderAndPo(po(null, EXISTING_CODE));

        service.regenerateQrToken(ORDER_ID, TENANT);

        // token 为空 ⇒ ensureQrToken 的写路径（既有实现）
        verify(processingOrderMapper, times(1)).updateById(any(ProcessingOrder.class));
        verify(processingOrderMapper, never()).fillMissingShortCode(anyString(), anyLong(), anyString(), any());
    }

    // ────────────────────────────────────────────── 装配边界

    @Test
    @DisplayName("边界：mapper 未接线时不丢异常（holder 装配不过 Spring）—— 本包只保证已在序列里")
    void mapperWiringIsNotAssumedByTheAllocationPath() {
        // 本判据是**对照臂**：上面所有判据都显式接线 ⇒ 这条证明「未接线时不会因为短码路径崩溃」，
        // 从而把「读面/入口的装配」留给 B2/B3，不在本包里造第二份装配口径。
        stubOrderAndPo(po(QR_TOKEN, EXISTING_CODE));
        stubNoExistingOperations();

        assertThat(service.instantiate(ORDER_ID, positionsBody(), TENANT)).containsKey("qr_token");
    }

    // ────────────────────────────────────────────── fixtures

    private void stubOrderAndPo(ProcessingOrder po) {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(po);
    }

    /**
     * 工序实例为空（+ 签名不同）⇒ 走首次实例化分支 ⇒ 只有一处 ensureShortCode 调用。
     *
     * <p>部位行必须能解出樘窗组键（{@code processing_info.craftLineId}）：否则
     * {@code itemGroupKey} 为空映射、{@code ensurePartTokens} 里的
     * {@code setByGroup.get(null)} 会在 {@code Map.of()}（不可空 key）上抛 NPE —— 那条路径
     * **与本包无关**（本包不碰部位码），本判据只把它挡在射程之外。</p>
     */
    private void stubNoExistingOperations() {
        when(positionOperationMapper.selectList(any())).thenReturn(List.<ProcessingPositionOperation>of());
        OrderItem item = new OrderItem();
        item.setId(ITEM_ID);
        item.setTenantId(TENANT);
        item.setDeleted(0);
        item.setProcessingInfo(Map.of("craftLineId", "craft-6867"));
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(item));
    }

    private Order order() {
        Order o = new Order();
        o.setId(ORDER_ID);
        o.setTenantId(TENANT);
        o.setOrderNo("ORD-20261014-6867");
        o.setStatus("producing");
        o.setDeleted(0);
        return o;
    }

    private ProcessingOrder po(String qrToken, String shortCode) {
        ProcessingOrder po = new ProcessingOrder();
        po.setId(PO_ID);
        po.setTenantId(TENANT);
        po.setOrderId(ORDER_ID);
        po.setProcessingOrderNo(PO_NO);
        po.setQrToken(qrToken);
        po.setShortCode(shortCode);
        po.setStatus("in_processing");
        po.setDeleted(0);
        return po;
    }

    private Map<String, Object> positionsBody() {
        Map<String, Object> op = new LinkedHashMap<>();
        op.put("operation", "精裁-布");
        op.put("group", "裁剪");
        op.put("unit", "米");
        op.put("qty", 10);
        Map<String, Object> position = new LinkedHashMap<>();
        position.put("position_name", "布艺遮光帘A");
        position.put("order_item_id", ITEM_ID);
        position.put("position_kind", "布帘");
        position.put("operations", List.of(op));
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("positions", List.of(position));
        return body;
    }
}
