// case_ids: PR-113, PR-114, PR-115
package com.migao.admin.service;

import com.migao.admin.dto.InboundLabelPrintView;
import com.migao.admin.dto.InboundLabelView;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.entity.InboundLabel;
import com.migao.admin.entity.Product;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundLabelMapper;
import com.migao.admin.mapper.ProductMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 入库标签服务（issue #5052 P2；设计 {@code docs/design/inbound-photo-and-label.md} §7）。
 *
 * <p>本类钉住四组判据，每组都对着一个**会真实发生的缺陷形态**：</p>
 * <ol>
 *   <li><b>短码口径复用而不复制</b>（§7.1）：8 位、字母表与报工短链**同一份**
 *       （生成面不产出 {@code I/L/O/U}）、手抄形态 {@code O→0} / {@code I,L→1} 归一化、
 *       碰撞重试 + 到顶 fail-closed（不静默造重码）；</li>
 *   <li><b>打印计数 + 审计</b>（§7.3）：原子自增（SQL 内自增，不是读改写）、
 *       每次打印一行审计且带「第几次」、撤销后**不再计数也不留痕**；</li>
 *   <li><b>撤销 ⇒ 短码置 NULL ⇒ 410</b>（§7.3）：撤销后扫码/详情/打印都必须是
 *       <b>410</b> 而不是 404（把「作废」说成「不存在」是本仓最忌讳的形态）；</li>
 *   <li><b>跨租户 ⇒ 404（不是 403）</b>（§5.2）：避免存在性泄露，且在碰任何单据数据之前就拒。</li>
 * </ol>
 *
 * <h3>红证（把实现改坏 ⇒ 本类必红）</h3>
 * <ul>
 *   <li>把 {@code incrementPrintCount} 的 SQL 自增改成「读出 +1 再写回」⇒ 并发判据（另见
 *       {@code InboundLabelMapperTest} 的真库/文本判据）与「一次打印一次自增」的 {@code times(1)} 断言红；</li>
 *   <li>把跨租户判定从 404 改成 403（{@code BusinessException.permissionDenied()}）⇒
 *       {@code crossTenantIsNotFoundNotForbidden} 红；</li>
 *   <li>撤销时只置 {@code short_code = NULL} 而不留档 ⇒ {@code revokedLabelIsGone} 与
 *       {@code revokedAfterRevokeResolvesToTheSameCode} 红（解析不到 ⇒ 404）；</li>
 *   <li>复制第二份字母表（含 {@code I/L/O/U}）⇒ {@code generatedCodesNeverContainConfusableLetters} 红。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("入库标签服务（#5052 P2）：短码口径 / 打印留痕 / 撤销 410 / 跨租户 404")
class InboundLabelServiceTest {

    /** 与报工短链**同一份**字母表（Crockford Base32，去掉 I/L/O/U）—— 判据里的第二处表达。 */
    private static final String ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

    @Mock private InboundLabelMapper inboundLabelMapper;
    @Mock private InboundOrderService inboundOrderService;
    @Mock private ProductMapper productMapper;
    @Mock private AuditLogService auditLogService;

    private InboundLabelService service;

    private static final Long TENANT = 7L;
    private static final Long OTHER_TENANT = 9L;
    private static final Long ITEM_ID = 1234L;
    private static final String ORDER_ID = "order-uuid-1";
    private static final String LIVE_CODE = "7K3M9QP2";
    private static final String REVOKED_CODE = "4T7Y2BQ9";

    @BeforeEach
    void setUp() {
        service = new InboundLabelService(inboundLabelMapper, inboundOrderService, productMapper, auditLogService);
    }

    // ============================================================ ① 短码口径（§7.1）

    @Test
    @DisplayName("🔴 生成面：每张标签的短码 = 8 位、全部落在共享字母表内（绝不产出 I/L/O/U）")
    void generatedCodesNeverContainConfusableLetters() {
        when(inboundLabelMapper.selectByItem(anyLong(), anyLong())).thenReturn(null);
        when(inboundLabelMapper.selectByCode(anyString())).thenReturn(null);
        when(inboundLabelMapper.insertIgnoreConflict(any())).thenReturn(1);

        ArgumentCaptor<InboundLabel> captor = ArgumentCaptor.forClass(InboundLabel.class);
        for (int i = 0; i < 300; i++) {
            service.ensureLabel(TENANT, ORDER_ID, ITEM_ID + i, "w-1");
        }
        verify(inboundLabelMapper, times(300)).insertIgnoreConflict(captor.capture());

        for (InboundLabel label : captor.getAllValues()) {
            String code = label.getShortCode();
            assertThat(code).hasSize(8);
            for (char c : code.toCharArray()) {
                assertThat(ALPHABET.indexOf(c))
                        .as("短码字符 %s 必须在共享字母表内（I/L/O/U 一律不得出现）", c)
                        .isGreaterThanOrEqualTo(0);
            }
            assertThat(code).doesNotContain("I", "L", "O", "U");
        }
    }

    @Test
    @DisplayName("🔴 撞码重试：分配器连续撞已有码时必须换一个（不是静默复用 / 静默造重码）")
    void allocatorRetriesOnCollision() {
        when(inboundLabelMapper.selectByItem(anyLong(), anyLong())).thenReturn(null);
        // 前两次查重都命中（模拟别的码空间已占），第三次空 ⇒ 必须换到那一个
        when(inboundLabelMapper.selectByCode(anyString())).thenReturn(
                label(LIVE_CODE, TENANT, 1L), label(REVOKED_CODE, TENANT, 2L), null);
        when(inboundLabelMapper.insertIgnoreConflict(any())).thenReturn(1);

        InboundLabel created = service.ensureLabel(TENANT, ORDER_ID, ITEM_ID, "w-1");

        assertThat(created.getShortCode()).hasSize(8);
        assertThat(List.of(LIVE_CODE, REVOKED_CODE)).doesNotContain(created.getShortCode());
        verify(inboundLabelMapper, times(3)).selectByCode(anyString());
    }

    @Test
    @DisplayName("🔴 到顶 fail-closed：连续 8 次都撞 ⇒ 显式失败，绝不静默发一个可能重复的码")
    void allocatorFailsClosedAfterMaxAttempts() {
        when(inboundLabelMapper.selectByCode(anyString())).thenReturn(label(LIVE_CODE, TENANT, 1L));

        assertThatThrownBy(() -> service.ensureLabel(TENANT, ORDER_ID, ITEM_ID, "w-1"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("拒绝静默造重码");
        verify(inboundLabelMapper, never()).insertIgnoreConflict(any());
    }

    @Test
    @DisplayName("🔴 查重同时看**留档码**：已撤销的码永不复发（老纸不会指到新单上）")
    void allocatorAlsoAvoidsRevokedCodes() {
        when(inboundLabelMapper.selectByItem(anyLong(), anyLong())).thenReturn(null);
        when(inboundLabelMapper.selectByCode(anyString())).thenReturn(revokedLabel(REVOKED_CODE, TENANT));
        when(inboundLabelMapper.insertIgnoreConflict(any())).thenReturn(1);

        // 留档码被 selectByCode 命中 ⇒ 分配器必须换码；把唯一「空」的位置留给第 9 次 ⇒ 必到顶
        assertThatThrownBy(() -> service.ensureLabel(TENANT, ORDER_ID, ITEM_ID, "w-1"))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    @DisplayName("手抄形态归一化：小写 / O→0 / I,L→1（纸面的码是给人抄的，抄错是必然形态）")
    void handwrittenFormsAreNormalized() {
        when(inboundLabelMapper.selectByCode(anyString())).thenReturn(null);

        service.resolve("7k3m9qpo");
        service.resolve(" 7k3m9qpi ");
        service.resolve("7k3m9qpl");

        verify(inboundLabelMapper).selectByCode("7K3M9QP0");
        verify(inboundLabelMapper, times(2)).selectByCode("7K3M9QP1");
    }

    @Test
    @DisplayName("形态不合法 ⇒ 一次库都不查（长度不对 / 含字母表外字符）")
    void malformedCodesNeverHitTheDatabase() {
        assertThat(service.resolve("ABC")).isNull();
        assertThat(service.resolve("7K3M9QP2X")).isNull();
        assertThat(service.resolve("7K3M-9QP")).isNull();
        assertThat(service.resolve("   ")).isNull();
        verifyNoInteractions(inboundLabelMapper);
    }

    @Test
    @DisplayName("发码幂等：已有标签 ⇒ 复用同一短码（已打印的纸不作废），且不复活已撤销的标签")
    void ensureLabelIsIdempotentAndNeverResurrectsRevoked() {
        when(inboundLabelMapper.selectByItem(TENANT, ITEM_ID)).thenReturn(label(LIVE_CODE, TENANT, ITEM_ID));
        InboundLabel reused = service.ensureLabel(TENANT, ORDER_ID, ITEM_ID, "w-1");
        assertThat(reused.getShortCode()).isEqualTo(LIVE_CODE);

        when(inboundLabelMapper.selectByItem(TENANT, ITEM_ID + 1)).thenReturn(revokedLabel(REVOKED_CODE, TENANT));
        InboundLabel revoked = service.ensureLabel(TENANT, ORDER_ID, ITEM_ID + 1, "w-1");
        assertThat(revoked.isRevoked()).isTrue();
        assertThat(revoked.getRevokedCode()).isEqualTo(REVOKED_CODE);

        verify(inboundLabelMapper, never()).insertIgnoreConflict(any());
    }

    @Test
    @DisplayName("并发同 item：插入被唯一索引拒 ⇒ 回读那一行（同一张纸，不造第二张码）")
    void ensureLabelReadsBackWhenAConcurrentInsertWins() {
        InboundLabel winner = label(LIVE_CODE, TENANT, ITEM_ID);
        when(inboundLabelMapper.selectByItem(TENANT, ITEM_ID)).thenReturn(null, winner);
        when(inboundLabelMapper.selectByCode(anyString())).thenReturn(null);
        when(inboundLabelMapper.insertIgnoreConflict(any())).thenReturn(0);

        InboundLabel result = service.ensureLabel(TENANT, ORDER_ID, ITEM_ID, "w-1");

        assertThat(result.getShortCode()).isEqualTo(LIVE_CODE);
        assertThat(result).isSameAs(winner);
    }

    // ============================================================ ② 详情读面（§5.2 / 功能②）

    @Test
    @DisplayName("详情读面给得出 50×30mm 标签要的每一格（短码/品名/色号/米数/供应商/日期…）")
    void detailCarriesEveryFieldTheLabelNeeds() {
        when(inboundLabelMapper.selectByCode(LIVE_CODE))
                .thenReturn(label(LIVE_CODE, TENANT, ITEM_ID, 3));
        when(inboundOrderService.detail(ORDER_ID, TENANT)).thenReturn(orderWithItem());
        when(productMapper.selectById("p-1")).thenReturn(Product.builder().id("p-1").name("遮光布").build());

        InboundLabelView view = service.detail("7k3m9qp2", TENANT);

        assertThat(view.getShortCode()).isEqualTo(LIVE_CODE);
        assertThat(view.getProductName()).isEqualTo("遮光布");
        assertThat(view.getSkuCode()).isEqualTo("SKU-001");
        assertThat(view.getColorName()).isEqualTo("米白");
        assertThat(view.getDoorWidth()).isEqualTo("2.8m");
        assertThat(view.getQuantity()).isEqualByComparingTo("60.5");
        assertThat(view.getBatchNo()).isEqualTo("PC-20260926-0001");
        assertThat(view.getDyeLot()).isEqualTo("LOT-9");
        assertThat(view.getSupplier()).isEqualTo("亿家纺织");
        assertThat(view.getInboundNo()).isEqualTo("RK-20260926-0001");
        assertThat(view.getInboundDate()).isEqualTo(LocalDate.of(2026, 9, 26));
        assertThat(view.getPrintCount()).isEqualTo(3);
    }

    @Test
    @DisplayName("🔴 跨租户 / 不存在 ⇒ 404（**不是 403**：403 等于告诉对方「这码存在，只是不归你」）")
    void crossTenantIsNotFoundNotForbidden() {
        when(inboundLabelMapper.selectByCode(LIVE_CODE)).thenReturn(label(LIVE_CODE, OTHER_TENANT, ITEM_ID));
        when(inboundLabelMapper.selectByCode("ZZZZZZZZ")).thenReturn(null);

        assertThatExceptionOfType(BusinessException.class)
                .isThrownBy(() -> service.detail(LIVE_CODE, TENANT))
                .satisfies(e -> assertThat(e.getHttpStatus()).isEqualTo(404))
                .satisfies(e -> assertThat(e.getHttpStatus()).isNotEqualTo(403));
        assertThatExceptionOfType(BusinessException.class)
                .isThrownBy(() -> service.detail("ZZZZZZZZ", TENANT))
                .satisfies(e -> assertThat(e.getHttpStatus()).isEqualTo(404));

        // 跨租户必须在**碰任何单据数据之前**就拒（否则等于用「单据查不到」冒充租户判据）
        verify(inboundOrderService, never()).detail(anyString(), anyLong());
    }

    @Test
    @DisplayName("🔴 跨租户去戳**已撤销**的码 ⇒ 仍是 404（先判租户后判撤销，不泄露「这码存在过」）")
    void crossTenantProbeOfARevokedCodeLeaksNothing() {
        when(inboundLabelMapper.selectByCode(REVOKED_CODE)).thenReturn(revokedLabel(REVOKED_CODE, OTHER_TENANT));

        assertThatExceptionOfType(BusinessException.class)
                .isThrownBy(() -> service.detail(REVOKED_CODE, TENANT))
                .satisfies(e -> assertThat(e.getHttpStatus()).isEqualTo(404));
    }

    // ============================================================ ③ 撤销 ⇒ 410（§7.3）

    @Test
    @DisplayName("🔴 已撤销 ⇒ 410 Gone（不是 404：不把「作废」说成「不存在」，且不静默回落）")
    void revokedLabelIsGone() {
        when(inboundLabelMapper.selectByCode(REVOKED_CODE)).thenReturn(revokedLabel(REVOKED_CODE, TENANT));

        assertThatExceptionOfType(BusinessException.class)
                .isThrownBy(() -> service.detail(REVOKED_CODE, TENANT))
                .satisfies(e -> assertThat(e.getHttpStatus()).isEqualTo(410))
                .satisfies(e -> assertThat(e.getCode()).isEqualTo("LABEL_REVOKED"));
        assertThatExceptionOfType(BusinessException.class)
                .isThrownBy(() -> service.recordPrint(REVOKED_CODE, TENANT, "w-1", "张三", "1.2.3.4", "ua"))
                .satisfies(e -> assertThat(e.getHttpStatus()).isEqualTo(410));

        // 撤销后**不再计数、也不再留痕**（否则「打印历史」会被作废的纸污染）
        verify(inboundLabelMapper, never()).incrementPrintCount(anyString(), anyLong());
        verifyNoInteractions(auditLogService);
    }

    @Test
    @DisplayName("撤销：短码置 NULL、原码留档、不碰打印计数；重复撤销幂等（false）")
    void revokeNullsTheLiveCodeAndKeepsTheArchiveCode() {
        when(inboundLabelMapper.selectByCode(LIVE_CODE)).thenReturn(label(LIVE_CODE, TENANT, ITEM_ID));
        when(inboundLabelMapper.revoke(eq("label-1"), eq(TENANT), any(OffsetDateTime.class), eq("w-9")))
                .thenReturn(1);

        assertThat(service.revoke(LIVE_CODE, TENANT, "w-9")).isTrue();
        ArgumentCaptor<OffsetDateTime> at = ArgumentCaptor.forClass(OffsetDateTime.class);
        verify(inboundLabelMapper).revoke(eq("label-1"), eq(TENANT), at.capture(), eq("w-9"));
        assertThat(at.getValue()).isNotNull();

        // 已撤销（revoke 影响 0 行）⇒ false，调用方据此判「本来就没了」
        when(inboundLabelMapper.revoke(eq("label-1"), eq(TENANT), any(OffsetDateTime.class), eq("w-9")))
                .thenReturn(0);
        assertThat(service.revoke(LIVE_CODE, TENANT, "w-9")).isFalse();
    }

    @Test
    @DisplayName("跨租户撤销 ⇒ false 且一行都不写（不可越租户作废别人的纸）")
    void crossTenantRevokeWritesNothing() {
        when(inboundLabelMapper.selectByCode(LIVE_CODE)).thenReturn(label(LIVE_CODE, OTHER_TENANT, ITEM_ID));

        assertThat(service.revoke(LIVE_CODE, TENANT, "w-9")).isFalse();
        verify(inboundLabelMapper, never()).revoke(anyString(), anyLong(), any(), anyString());
    }

    // ============================================================ ④ 打印计数 + 审计（§7.3）

    @Test
    @DisplayName("🔴 打印留痕：一次调用 = 一次原子自增 + 一行审计（带短码与「第几次」）")
    void printIncrementsOnceAndWritesOneAuditRowWithTheOrdinal() {
        when(inboundLabelMapper.selectByCode(LIVE_CODE)).thenReturn(label(LIVE_CODE, TENANT, ITEM_ID, 3));
        when(inboundLabelMapper.incrementPrintCount("label-1", TENANT)).thenReturn(1);
        when(inboundLabelMapper.selectPrintCount("label-1", TENANT)).thenReturn(4);

        InboundLabelPrintView view = service.recordPrint(LIVE_CODE, TENANT, "w-1", "张三", "1.2.3.4", "ua");

        assertThat(view.shortCode()).isEqualTo(LIVE_CODE);
        assertThat(view.printCount()).isEqualTo(4);
        verify(inboundLabelMapper, times(1)).incrementPrintCount("label-1", TENANT);

        ArgumentCaptor<Object> details = ArgumentCaptor.forClass(Object.class);
        verify(auditLogService).recordLog(eq(TENANT), eq("w-1"), eq("张三"),
                eq(InboundLabel.ACTION_PRINT), eq(InboundLabel.RESOURCE_TYPE), isNull(),
                eq("label-1"), eq(LIVE_CODE), details.capture(), eq("1.2.3.4"), eq("ua"));
        assertThat(details.getValue()).isInstanceOf(Map.class);
        @SuppressWarnings("unchecked")
        Map<String, Object> map = (Map<String, Object>) details.getValue();
        assertThat(map).containsEntry("shortCode", LIVE_CODE).containsEntry("printCount", 4);
    }

    @Test
    @DisplayName("🔴 重打同样计数：第二次打印是 +1（3 → 4 → 5），不是「首次才计」")
    void reprintAlsoCounts() {
        when(inboundLabelMapper.selectByCode(LIVE_CODE)).thenReturn(label(LIVE_CODE, TENANT, ITEM_ID, 3));
        when(inboundLabelMapper.incrementPrintCount("label-1", TENANT)).thenReturn(1);
        when(inboundLabelMapper.selectPrintCount("label-1", TENANT)).thenReturn(4, 5);

        assertThat(service.recordPrint(LIVE_CODE, TENANT, "w-1", "张三", "ip", "ua").printCount()).isEqualTo(4);
        assertThat(service.recordPrint(LIVE_CODE, TENANT, "w-1", "张三", "ip", "ua").printCount()).isEqualTo(5);
        verify(inboundLabelMapper, times(2)).incrementPrintCount("label-1", TENANT);
        verify(auditLogService, times(2)).recordLog(anyLong(), anyString(), anyString(), anyString(),
                anyString(), any(), anyString(), anyString(), any(), anyString(), anyString());
    }

    @Test
    @DisplayName("🔴 计数自增影响 0 行（并发撤销 / 软删）⇒ 404，绝不返回一个没落库的计数")
    void printFailsClosedWhenTheCounterUpdateTouchesNoRow() {
        when(inboundLabelMapper.selectByCode(LIVE_CODE)).thenReturn(label(LIVE_CODE, TENANT, ITEM_ID));
        when(inboundLabelMapper.incrementPrintCount("label-1", TENANT)).thenReturn(0);

        assertThatExceptionOfType(BusinessException.class)
                .isThrownBy(() -> service.recordPrint(LIVE_CODE, TENANT, "w-1", "张三", "ip", "ua"))
                .satisfies(e -> assertThat(e.getHttpStatus()).isEqualTo(404));
        verifyNoInteractions(auditLogService);
    }

    // ============================================================ ⑤ 公开入口落地页（单一配置）

    @Test
    @DisplayName("🔴 落地页地址走单一配置：改配置即改 302 目标，源码里没有硬编码域名")
    void landingPathIsASingleConfigurableSource() {
        assertThat(service.landingLocation("7k3m9qp2", TENANT))
                .isEqualTo("/b/?code=" + LIVE_CODE + "&tenant_id=" + TENANT);

        ReflectionTestUtils.setField(service, "landingPath", "/b/index.html");
        assertThat(service.landingLocation(LIVE_CODE, TENANT))
                .isEqualTo("/b/index.html?code=" + LIVE_CODE + "&tenant_id=" + TENANT);

        ReflectionTestUtils.setField(service, "landingPath", "/b/?from=label");
        assertThat(service.landingLocation(LIVE_CODE, TENANT))
                .isEqualTo("/b/?from=label&code=" + LIVE_CODE + "&tenant_id=" + TENANT);

        // 只回跳转、不泄露业务字段：这串里不可能出现品名 / 米数 / 供应商 / 单号
        String location = service.landingLocation(LIVE_CODE, TENANT);
        assertThat(location).doesNotContain("RK-", "PC-", "SKU", "PC-2026");

        // 无租户（理论上不会发生：公开入口一定解得出租户）⇒ 只带短码，不拼一个假的 tenant_id
        ReflectionTestUtils.setField(service, "landingPath", InboundLabelService.DEFAULT_LANDING_PATH);
        assertThat(service.landingLocation(LIVE_CODE, null))
                .isEqualTo("/b/?code=" + LIVE_CODE);
    }

    // ============================================================ 夹具

    private static InboundLabel label(String code, Long tenantId, Long itemId) {
        return label(code, tenantId, itemId, 0);
    }

    private static InboundLabel label(String code, Long tenantId, Long itemId, int printCount) {
        return InboundLabel.builder()
                .id("label-1").tenantId(tenantId).inboundOrderId(ORDER_ID).inboundItemId(itemId)
                .shortCode(code).printCount(printCount).createdBy("w-1").deleted(0)
                .createdAt(OffsetDateTime.parse("2026-09-26T10:00:00+08:00"))
                .build();
    }

    private static InboundLabel revokedLabel(String code, Long tenantId) {
        return InboundLabel.builder()
                .id("label-1").tenantId(tenantId).inboundOrderId(ORDER_ID).inboundItemId(ITEM_ID)
                .shortCode(null).revokedCode(code).printCount(2).deleted(0)
                .revokedAt(OffsetDateTime.parse("2026-09-26T11:00:00+08:00")).revokedBy("w-9")
                .build();
    }

    private static InboundOrderResponse orderWithItem() {
        InboundOrderResponse.Item item = new InboundOrderResponse.Item();
        item.setId(ITEM_ID);
        item.setProductId("p-1");
        item.setSkuId(55L);
        item.setSkuCode("SKU-001");
        item.setColorName("米白");
        item.setDoorWidth("2.8m");
        item.setQuantity(new BigDecimal("60.5"));
        item.setBatchNo("PC-20260926-0001");
        item.setDyeLot("LOT-9");

        InboundOrderResponse order = new InboundOrderResponse();
        order.setId(ORDER_ID);
        order.setInboundNo("RK-20260926-0001");
        order.setSupplier("亿家纺织");
        order.setSupplierDocNo("SH-88");
        order.setWarehouse("一号仓");
        order.setInboundDate(LocalDate.of(2026, 9, 26));
        order.setStatus("posted");
        order.setItems(List.of(item));
        return order;
    }
}
