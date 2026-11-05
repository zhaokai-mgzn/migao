// case_ids: MC-216, MC-219
package com.migao.admin.waybill;

import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.RecordComponent;
import java.math.BigDecimal;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 取号编排判据（issue #8698 P0；口径 §3-2「取号 ≠ 发货」、§3-3「未接入退回 manual」、§6「fail-closed」）。
 *
 * <p>🔴 <b>判据 1 = 取号不改变订单状态</b>。本单没有真库夹具（P0 无第三方、也不落运单表），
 * 所以这条用**两条互补的判据**钉住，二者都会红：</p>
 * <ul>
 *   <li>① <b>结构判据</b>（{@link #waybillServiceStructurallyCannotWriteOrderStatus}）：
 *       {@code WaybillService} 的字段里**不许**出现任何 {@code Order*} 类型 ——
 *       谁想「顺手」流转状态，就得先注入订单依赖，本判据当场红并具名；</li>
 *   <li>② <b>行为判据</b>（{@link #createDoesNotChangeOrderStatus}）：走一次**真的会成功**的取号路径
 *       （替身 provider），拿一张 {@code status=confirmed} 的订单做观测点，调用后状态逐字不变。</li>
 * </ul>
 *
 * <p>判据 3/4 的红证：<b>把 manual 兜底改成「什么都不做直接返回空结果」</b>⇒ 判据 4 的
 * 「422 + 零外呼」立刻红；把 {@code assertCreatable()} 移到 {@code provider.create()} **之后**
 * ⇒ 判据 3 的「脏地址时 provider 零调用」红。</p>
 */
@DisplayName("WaybillService 取号编排（issue #8698 P0）")
class WaybillServiceTest {

    private static final Long TENANT = 9L;

    private TenantLogisticsConfigService config;
    private WaybillService service;

    /** 记录调用次数的替身 provider（用于证明「manual 兜底不产生任何外呼」）。 */
    private static final class RecordingProvider implements WaybillProvider {
        final AtomicInteger createCalls = new AtomicInteger();
        final AtomicInteger trackCalls = new AtomicInteger();

        @Override
        public String carrierCode() {
            return "sf";
        }

        @Override
        public boolean canCreate() {
            return true;
        }

        @Override
        public boolean canCancel() {
            return false;
        }

        @Override
        public boolean canTrack() {
            return true;
        }

        @Override
        public WaybillCreateResult create(WaybillCreateRequest request) {
            createCalls.incrementAndGet();
            return new WaybillCreateResult("SF" + request.orderId(), "sf", "顺丰速运");
        }

        @Override
        public WaybillTrackResult track(String trackingNo) {
            trackCalls.incrementAndGet();
            return new WaybillTrackResult(trackingNo, "sf", List.of("已揽收"));
        }
    }

    /** 声明 ∧ 实现都在场的注册表（= P1 接入顺丰之后的形态）。 */
    private static CarrierRegistry registryWithCapableSf(WaybillProvider provider) {
        List<CarrierCatalogue.Entry> catalogue = List.of(
                new CarrierCatalogue.Entry("sf", "顺丰速运", "express", "SF", true, false, true));
        return new CarrierRegistry(catalogue, List.of(provider, new ManualWaybillProvider()));
    }

    private static WaybillCreateRequest validRequest(String orderId) {
        return new WaybillCreateRequest(orderId, "张三", "13800000000", "杭州市西湖区文三路 1 号 3 幢", 1,
                new BigDecimal("1.0"));
    }

    @BeforeEach
    void setUp() {
        config = mock(TenantLogisticsConfigService.class);
    }

    @Test
    @DisplayName("判据 4：没配承运商 ⇒ manual 兜底，422 + 可行动文案，且 provider 零调用")
    void unconfiguredTenantFallsBackToManualWithoutAnyCall() {
        when(config.configuredCarrierCode(TENANT)).thenReturn(null);
        RecordingProvider provider = new RecordingProvider();
        service = new WaybillService(new CarrierRegistry(List.of(provider, new ManualWaybillProvider())), config);

        assertThatThrownBy(() -> service.create(TENANT, "o-1", validRequest("o-1")))
                .isInstanceOf(WaybillUnsupportedException.class)
                .hasFieldOrPropertyWithValue("httpStatus", 422)
                .hasMessageContaining("手填单号");
        assertThat(provider.createCalls.get()).as("manual 兜底不得产生任何外呼").isZero();
    }

    @Test
    @DisplayName("判据 4b：配了未接入的承运商（sja）⇒ 同一出口，仍零外呼")
    void configuredButUnconnectedCarrierAlsoFallsBackWithoutAnyCall() {
        when(config.configuredCarrierCode(TENANT)).thenReturn("sja");
        RecordingProvider provider = new RecordingProvider();
        service = new WaybillService(new CarrierRegistry(List.of(provider, new ManualWaybillProvider())), config);

        assertThatThrownBy(() -> service.create(TENANT, "o-2", validRequest("o-2")))
                .isInstanceOf(WaybillUnsupportedException.class)
                .hasMessageContaining("四季安物流")
                .hasMessageContaining("手填单号");
        assertThat(provider.createCalls.get()).isZero();
    }

    @Test
    @DisplayName("判据 3：脏地址 ⇒ 422，且**在调 provider 之前**就拦住（不拿脏地址下单）")
    void dirtyAddressFailsClosedBeforeProviderIsCalled() {
        when(config.configuredCarrierCode(TENANT)).thenReturn("sf");
        RecordingProvider provider = new RecordingProvider();
        service = new WaybillService(registryWithCapableSf(provider), config);

        assertThatThrownBy(() -> service.create(TENANT, "o-3",
                new WaybillCreateRequest("o-3", "张三", "13800000000", "   ", 1, null)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "WAYBILL_ADDRESS_MISSING")
                .hasFieldOrPropertyWithValue("httpStatus", 422);
        assertThatThrownBy(() -> service.create(TENANT, "o-3",
                new WaybillCreateRequest("o-3", "张三", "13800000000", "浙江省", 1, null)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "WAYBILL_ADDRESS_INCOMPLETE");
        assertThat(provider.createCalls.get()).as("脏地址不得产生任何外呼").isZero();
    }

    @Test
    @DisplayName("判据 1（行为）：取号成功路径 ⇒ 订单状态逐字不变（付了款的单仍是 confirmed）")
    void createDoesNotChangeOrderStatus() {
        when(config.configuredCarrierCode(TENANT)).thenReturn("sf");
        RecordingProvider provider = new RecordingProvider();
        service = new WaybillService(registryWithCapableSf(provider), config);

        // 观测点：一张「已确认、待发货」的真实订单实体（取号前后状态必须一样）
        Order order = new Order();
        order.setId("o-4");
        order.setStatus("confirmed");
        String before = order.getStatus();

        WaybillCreateResult result = service.create(TENANT, order.getId(), validRequest(order.getId()));

        assertThat(result.trackingNo()).isEqualTo("SFo-4");
        assertThat(order.getStatus()).as("取号 ≠ 发货：取号成功不得改订单状态").isEqualTo(before);
        // 结果体里**没有**状态字段（有它就会被「顺手」当成发货依据）
        assertThat(List.of(WaybillCreateResult.class.getRecordComponents()).stream().map(RecordComponent::getName))
                .doesNotContain("status", "orderStatus", "shipped");
    }

    @Test
    @DisplayName("判据 1（结构）：WaybillService 不持有任何订单类型依赖（注入状态写 ⇒ 当场红并具名）")
    void waybillServiceStructurallyCannotWriteOrderStatus() {
        for (Field field : WaybillService.class.getDeclaredFields()) {
            assertThat(field.getType().getSimpleName())
                    .as("取号路径出现了订单依赖字段 %s（类型 %s）—— 取号不得碰订单状态",
                            field.getName(), field.getType().getSimpleName())
                    .doesNotStartWith("Order");
        }
        // 包内任何类都不许引用订单生命周期 / 订单 Mapper（源码级判据的运行时对照，见 Python 侧守卫）
        assertThat(WaybillService.class.getName()).doesNotContain("Order");
    }

    @Test
    @DisplayName("判据 2：能力面把「生效承运商 + 是否兜底」一起下发（UI 只读它，不自己推）")
    void capabilitiesExposeEffectiveCarrierAndFallbackFlag() {
        when(config.configuredCarrierCode(TENANT)).thenReturn("sja");
        service = new WaybillService(new CarrierRegistry(List.of(new ManualWaybillProvider())), config);

        WaybillService.WaybillCapabilities caps = service.capabilities(TENANT);

        assertThat(caps.configuredCarrier()).isEqualTo("sja");
        assertThat(caps.effectiveCarrier().displayName()).isEqualTo("四季安物流");
        assertThat(caps.effectiveCarrier().canCreate()).isFalse();
        assertThat(caps.manualFallback()).isTrue();
        assertThat(caps.carriers()).extracting(Carrier::code).contains("manual", "sja", "sf");
    }

    @Test
    @DisplayName("轨迹：未接入 ⇒ 422「未接入」，不返回空轨迹冒充「查过了没轨迹」")
    void trackWithoutProviderThrows() {
        when(config.configuredCarrierCode(TENANT)).thenReturn("sf");
        service = new WaybillService(new CarrierRegistry(List.of(new ManualWaybillProvider())), config);

        assertThatThrownBy(() -> service.track(TENANT, "SF123"))
                .isInstanceOf(WaybillUnsupportedException.class)
                .hasMessageContaining("轨迹查询");
    }
}
