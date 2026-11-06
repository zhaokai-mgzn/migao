// case_ids: MC-330
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * {@link ProcessingOrderReadFace} 的定点判据（issue #8770 快照/读面一档）。
 *
 * <p>与 characterization 分工：那一份冻「同一批输入 ⇒ DTO 逐字节不变」；本份钉**单元自身的契约** ——
 * 单号解析走 {@link ProcessingOrderReadFace.Owner} 回调（不复制第二份口径）、域名**即时取值**
 * （既有判据在构造之后用 {@code ReflectionTestUtils} 换域名）、列表**一次批量取数**（#4304 的 N+1 防线）。</p>
 */
@DisplayName("读面单元：回调面/域名即时取值/批量取数/只看外发/404 五格")
class ProcessingOrderReadFaceTest {

    private static final Long TENANT = 1L;

    private final ObjectMapper mapper = new ObjectMapper();
    private ProcessingOrderMapper processingOrderMapper;
    private OrderMapper orderMapper;
    private StubOwner owner;
    private ProcessingOrderReadFace readFace;

    @BeforeEach
    void setUp() {
        // `list` 走 LambdaQueryWrapper ⇒ 需要 TableInfo（同 ProcessingOrderReadFaceShortCodeTest）
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);

        processingOrderMapper = mock(ProcessingOrderMapper.class);
        orderMapper = mock(OrderMapper.class);
        owner = new StubOwner();
        readFace = new ProcessingOrderReadFace(processingOrderMapper, orderMapper, mapper, owner);
    }

    @Test
    @DisplayName("① 详情：单号解析走 Owner 回调（门面仍是唯一解析口径），映射带出扫码 URL")
    void detailResolvesThroughOwnerAndCarriesScanUrl() {
        owner.processingOrder = po("po-1", "order-001", "SC-0001");
        owner.baseUrl = "https://app.migaozn.com";
        when(orderMapper.selectById("order-001")).thenReturn(order("order-001"));

        ProcessingOrderResponse resp = readFace.getDetail("po-1", TENANT);

        assertThat(resp.getId()).isEqualTo("po-1");
        assertThat(resp.getOrderNo()).isEqualTo("ORD-order-001");
        assertThat(resp.getScanUrl()).isEqualTo("https://app.migaozn.com/o/SC-0001");
        assertThat(owner.resolveCalls).isEqualTo(1);
    }

    @Test
    @DisplayName("② 域名**即时取值**：构造之后换 base ⇒ 下一次调用立刻生效（不缓存、不复制第二份）")
    void baseUrlIsReadLiveNotCached() {
        owner.processingOrder = po("po-1", "order-001", "SC-0001");
        owner.baseUrl = "https://a.example.com";
        when(orderMapper.selectById("order-001")).thenReturn(order("order-001"));

        assertThat(readFace.getDetail("po-1", TENANT).getScanUrl())
                .isEqualTo("https://a.example.com/o/SC-0001");

        owner.baseUrl = "https://b.example.com/";
        assertThat(readFace.getDetail("po-1", TENANT).getScanUrl())
                .as("尾斜杠归一 + 换域名同批生效（拼装只此一份）")
                .isEqualTo("https://b.example.com/o/SC-0001");
    }

    @Test
    @DisplayName("③ 列表：订单**一次批量取回**（selectBatchIds 恰 1 次），绝不逐行 selectById（#4304）")
    void listBatchesOrdersInOneQuery() {
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(
                po("po-1", "order-001", "SC-0001"), po("po-2", "order-002", "SC-0002")));
        when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(
                order("order-001"), order("order-002")));

        List<ProcessingOrderResponse> rows = readFace.list(null, null, TENANT, null);

        assertThat(rows).hasSize(2);
        assertThat(rows.get(0).getOrderNo()).isEqualTo("ORD-order-001");
        verify(orderMapper, times(1)).selectBatchIds(anyCollection());
        verify(orderMapper, never()).selectById(anyString());
    }

    @Test
    @DisplayName("④ 只看外发：只留带承接方档案引用的行；**不改** mapper 返回的集合（副本过滤）")
    void outsourcedFilterKeepsOnlyRowsWithSupplier() {
        ProcessingOrder withSupplier = po("po-1", "order-001", "SC-0001");
        withSupplier.setProcessorSupplierId("sup-1");
        ProcessingOrder without = po("po-2", "order-002", "SC-0002");
        List<ProcessingOrder> source = new java.util.ArrayList<>(List.of(withSupplier, without));
        when(processingOrderMapper.selectList(any())).thenReturn(source);
        when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(
                order("order-001"), order("order-002")));

        List<ProcessingOrderResponse> rows = readFace.list(null, null, TENANT, true);

        assertThat(rows).hasSize(1);
        assertThat(rows.get(0).getProcessorSupplierId()).isEqualTo("sup-1");
        assertThat(source).as("过滤必须产出副本：不原地裁剪 mapper 的集合（同请求的第二个读面会读到被裁过的表）")
                .hasSize(2);
    }

    @Test
    @DisplayName("⑤ 详情：没有加工单但订单存在 ⇒ 返回 null（前端走「生成加工单」态，issue #3887）；两者都没有 ⇒ 404")
    void detailDistinguishesMissingProcessingOrderFromMissingOrder() {
        owner.processingOrder = null;
        owner.order = order("order-001");
        assertThat(readFace.getDetail("order-001", TENANT)).isNull();

        owner.order = null;
        assertThatThrownBy(() -> readFace.getDetail("order-missing", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("加工单");
    }

    // ── 夹具 ───────────────────────────────────────────────────────────────

    private static ProcessingOrder po(String id, String orderId, String shortCode) {
        return ProcessingOrder.builder()
                .id(id).tenantId(TENANT).orderId(orderId)
                .processingOrderNo("JG-20261106-0001")
                .status("issued").shortCode(shortCode)
                .build();
    }

    private static Order order(String id) {
        return Order.builder().id(id).tenantId(TENANT).orderNo("ORD-" + id).customerName("张三").build();
    }

    /** 门面回调面的替身（只做「门面会做什么」的最小模拟，**不复制**门面实现）。 */
    private static final class StubOwner implements ProcessingOrderReadFace.Owner {
        private ProcessingOrder processingOrder;
        private Order order;
        private String baseUrl = "https://app.migaozn.com";
        private int resolveCalls;

        @Override
        public ProcessingOrder resolveProcessingOrder(String rawId, Long tenantId) {
            resolveCalls++;
            return processingOrder;
        }

        @Override
        public Order resolveOrder(String rawId, Long tenantId) {
            return order;
        }

        @Override
        public String scanBaseUrl() {
            return baseUrl;
        }
    }
}
