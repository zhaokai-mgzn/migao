// case_ids: PR-005, AS-006, PR-004
// 库存台账落账语义（issue #4055）：delta 恒等于 after-before、operator 解析、
// 「只记真实变化」的比对落账、只读查询的租户隔离与过滤。
// 不变式（同 SKU 相邻两行首尾相接）另见 StockLedgerTest（真实服务 + 内存账本装配）。

package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import com.migao.admin.security.SecurityUser;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * StockLedgerService 单元测试（issue #4055）。
 * 覆盖：落账行字段、delta 由 before/after 推出（不接受调用方传入）、operator 解析、
 * 比对落账只记真实变化、查询的租户隔离/过滤/分页。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("StockLedgerService 库存台账（issue #4055）")
class StockLedgerServiceTest {

    private static final Long TENANT_ID = 1L;
    private static final String PRODUCT_ID = "prod-1";

    @Mock private StockLedgerMapper stockLedgerMapper;
    @Mock private ProductSkuMapper productSkuMapper;

    private StockLedgerService stockLedgerService;

    @BeforeEach
    void setUp() {
        // LambdaQueryWrapper 需要 TableInfo 缓存（mock 环境不自动初始化）
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, StockLedger.class);
        TableInfoHelper.initTableInfo(assistant, ProductSku.class);
        stockLedgerService = new StockLedgerService(stockLedgerMapper, productSkuMapper);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    // ======================== 落账 ========================

    @Test
    @DisplayName("record —— 写入行的 before/after/delta 三者自洽，reason/refNo/note/tenant 原样落库")
    void recordWritesSelfConsistentRow() {
        StockLedger row = captureRecorded(() -> stockLedgerService.record(
                TENANT_ID, PRODUCT_ID, 100L, "SKU-100", 30, 20,
                StockLedger.REASON_MANUAL, null, "报损"));

        assertThat(row.getTenantId()).isEqualTo(TENANT_ID);
        assertThat(row.getProductId()).isEqualTo(PRODUCT_ID);
        assertThat(row.getSkuId()).isEqualTo(100L);
        assertThat(row.getSkuCode()).isEqualTo("SKU-100");
        assertThat(row.getBeforeQty()).isEqualTo(30);
        assertThat(row.getAfterQty()).isEqualTo(20);
        assertThat(row.getDelta()).as("delta 必须由 after-before 推出").isEqualTo(-10);
        assertThat(row.getReason()).isEqualTo(StockLedger.REASON_MANUAL);
        assertThat(row.getRefNo()).isNull();
        assertThat(row.getNote()).isEqualTo("报损");
        assertThat(row.getCreatedAt()).as("created_at 必须落值（时间轴是对账的一部分）").isNotNull();
    }

    @Test
    @DisplayName("record —— 订单/工单流水带 refNo（无单据号就答不出「哪一单改的」）")
    void recordKeepsRefNo() {
        StockLedger row = captureRecorded(() -> stockLedgerService.record(
                TENANT_ID, PRODUCT_ID, 100L, "SKU-100", 20, 22,
                StockLedger.REASON_AFTERSALES, "AS-20260918-0001", "退货回补"));

        assertThat(row.getReason()).isEqualTo(StockLedger.REASON_AFTERSALES);
        assertThat(row.getRefNo()).isEqualTo("AS-20260918-0001");
        assertThat(row.getDelta()).isEqualTo(2);
    }

    @Test
    @DisplayName("record —— operator 取登录用户名；无认证上下文降级 system（不落空值）")
    void recordResolvesOperator() {
        SecurityUser user = new SecurityUser("user-1", TENANT_ID, "13800138000",
                List.of("admin"), List.of(new SimpleGrantedAuthority("ROLE_admin")));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(user, null, user.getAuthorities()));

        StockLedger withAuth = captureRecorded(() -> stockLedgerService.record(
                TENANT_ID, PRODUCT_ID, 100L, "SKU-100", 10, 12,
                StockLedger.REASON_MANUAL, null, "盘点"));
        assertThat(withAuth.getOperator()).isEqualTo("13800138000");

        SecurityContextHolder.clearContext();
        StockLedger withoutAuth = captureRecorded(() -> stockLedgerService.record(
                TENANT_ID, PRODUCT_ID, 100L, "SKU-100", 12, 11,
                StockLedger.REASON_MANUAL, null, "报损"));
        assertThat(withoutAuth.getOperator()).isEqualTo(StockLedgerService.OPERATOR_SYSTEM);
    }

    // ======================== 比对落账（售后回补站点用） ========================

    @Test
    @DisplayName("recordChangesAgainstSnapshot —— 只记真实变化的 SKU，无变化不落行")
    void recordChangesAgainstSnapshotRecordsOnlyRealChanges() {
        Map<Long, ProductSku> before = new LinkedHashMap<>();
        before.put(100L, sku(100L, 10));
        before.put(200L, sku(200L, 5));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(sku(100L, 15), sku(200L, 5)));

        int rows = stockLedgerService.recordChangesAgainstSnapshot(
                TENANT_ID, before, StockLedger.REASON_AFTERSALES, "AS-1", "退货回补");

        assertThat(rows).isEqualTo(1);
        ArgumentCaptor<StockLedger> captor = ArgumentCaptor.forClass(StockLedger.class);
        verify(stockLedgerMapper).insert(captor.capture());
        StockLedger row = captor.getValue();
        assertThat(row.getSkuId()).isEqualTo(100L);
        assertThat(row.getBeforeQty()).isEqualTo(10);
        assertThat(row.getAfterQty()).isEqualTo(15);
        assertThat(row.getDelta()).isEqualTo(5);
        assertThat(row.getRefNo()).isEqualTo("AS-1");
    }

    @Test
    @DisplayName("recordChangesAgainstSnapshot —— 快照外的 SKU 不落账（防以 before=0 造出假变化）")
    void recordChangesAgainstSnapshotSkipsUnknownSku() {
        Map<Long, ProductSku> before = new LinkedHashMap<>();
        before.put(100L, sku(100L, 10));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(sku(100L, 10), sku(999L, 50)));

        int rows = stockLedgerService.recordChangesAgainstSnapshot(
                TENANT_ID, before, StockLedger.REASON_AFTERSALES, "AS-1", "退货回补");

        assertThat(rows).isZero();
        verify(stockLedgerMapper, org.mockito.Mockito.never()).insert(any(StockLedger.class));
    }

    @Test
    @DisplayName("snapshotSkus —— 按 skuId 建快照；空入参不发查询")
    void snapshotSkusBySkuId() {
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(sku(100L, 10), sku(200L, 5)));

        Map<Long, ProductSku> snapshot = stockLedgerService.snapshotSkus(Set.of(PRODUCT_ID));

        assertThat(snapshot).containsOnlyKeys(100L, 200L);
        assertThat(snapshot.get(100L).getStock()).isEqualTo(10);
        assertThat(stockLedgerService.snapshotSkus(List.of())).isEmpty();
    }

    // ======================== 只读查询 ========================

    @Test
    @DisplayName("getLedgerPage —— 租户隔离（SQL 段必含 tenant_id）+ 三个过滤条件 + 倒序")
    void getLedgerPageScopesByTenantAndFilters() {
        Page<StockLedger> dbPage = new Page<>(1, 20);
        dbPage.setTotal(2);
        dbPage.setRecords(List.of(
                StockLedger.builder().id(2L).skuId(100L).build(),
                StockLedger.builder().id(1L).skuId(100L).build()));
        when(stockLedgerMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(dbPage);

        PageResponse<StockLedger> response = stockLedgerService.getLedgerPage(
                TENANT_ID, 100L, PRODUCT_ID, "AS-1", 1, 20);

        assertThat(response.getTotal()).isEqualTo(2);
        assertThat(response.getItems()).extracting(StockLedger::getId).containsExactly(2L, 1L);

        ArgumentCaptor<LambdaQueryWrapper<StockLedger>> captor = wrapperCaptor();
        verify(stockLedgerMapper).selectPage(any(Page.class), captor.capture());
        String sql = captor.getValue().getSqlSegment();
        assertThat(sql).as("跨租户读 = 数据泄漏，租户条件不可省").contains("tenant_id");
        assertThat(sql).contains("sku_id").contains("product_id").contains("ref_no");
        assertThat(sql).as("台账按 id 倒序（最新在前）").contains("ORDER BY");
    }

    @Test
    @DisplayName("getLedgerPage —— 无过滤条件时仍限定租户（返回本租户全部）")
    void getLedgerPageWithoutFiltersStillScoped() {
        Page<StockLedger> dbPage = new Page<>(1, 20);
        dbPage.setTotal(0);
        dbPage.setRecords(List.of());
        when(stockLedgerMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(dbPage);

        PageResponse<StockLedger> response =
                stockLedgerService.getLedgerPage(TENANT_ID, null, null, null, 1, 20);

        assertThat(response.getItems()).isEmpty();
        ArgumentCaptor<LambdaQueryWrapper<StockLedger>> captor = wrapperCaptor();
        verify(stockLedgerMapper).selectPage(any(Page.class), captor.capture());
        String sql = captor.getValue().getSqlSegment();
        assertThat(sql).contains("tenant_id");
        assertThat(sql).doesNotContain("sku_id");
    }

    // ======================== 夹具 ========================

    /** 执行 action 并返回它插入的那一行台账（整表只有一行时最直接）。 */
    private StockLedger captureRecorded(Runnable action) {
        action.run();
        ArgumentCaptor<StockLedger> captor = ArgumentCaptor.forClass(StockLedger.class);
        verify(stockLedgerMapper, org.mockito.Mockito.atLeastOnce()).insert(captor.capture());
        List<StockLedger> all = captor.getAllValues();
        return all.get(all.size() - 1);
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private ArgumentCaptor<LambdaQueryWrapper<StockLedger>> wrapperCaptor() {
        return ArgumentCaptor.forClass((Class) LambdaQueryWrapper.class);
    }

    private static ProductSku sku(Long id, int stock) {
        ProductSku s = new ProductSku();
        s.setId(id);
        s.setTenantId(TENANT_ID);
        s.setProductId(PRODUCT_ID);
        s.setSkuCode("SKU-" + id);
        s.setStock(stock);
        s.setUpdatedAt(OffsetDateTime.now());
        return s;
    }
}