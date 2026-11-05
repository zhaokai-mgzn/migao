// case_ids: MC-218, MC-219
package com.migao.admin.waybill;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 承运商注册表判据（issue #8698 P0；口径 {@code docs/logistics-waybill-api-research.md} §3-5）。
 *
 * <p>各条判据**都能红**，红证形态写在每条上：</p>
 * <ol>
 *   <li><b>加一家承运商 = 加一行配置</b>：注册表行数 ≡ 目录行数、code 序列逐字相等
 *       ⇒ 谁在注册表里写 {@code if (code.equals(...))} 分支，行数对不上即红；</li>
 *   <li><b>manual 兜底</b>：未登记 / 空 code ⇒ {@code manual}（手填），不是抛错、不是编一家；</li>
 *   <li>🔴 <b>不能声称能做而实际不能</b>：目录声明 {@code canCreate=true} 而没 provider ⇒
 *       对 UI 的能力位仍是 {@code false}，且 {@code overClaimed()} 具名报出该 code
 *       （红证：把生产目录任一行的 {@code canCreate} 改 true、不接 provider ⇒ 本组红）；</li>
 *   <li><b>未实现必须抛「不支持」</b>：provider 的 default 方法抛 422，不返回 {@code null} /
 *       空字符串（红证：把 default 改成 `return null` ⇒ 判据 4 红）；</li>
 *   <li><b>轨迹查询编码映射</b>：每家承运商（manual 除外）都有非空 {@code trackQueryCode}。</li>
 * </ol>
 */
@DisplayName("CarrierRegistry 承运商注册表（issue #8698 P0）")
class CarrierRegistryTest {

    /** 一个「真的能取号」的替身 provider（P1 接入后真实 provider 的形状）。 */
    private static WaybillProvider capableProvider() {
        return new WaybillProvider() {
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
                return new WaybillCreateResult("SF1234567890", "sf", "顺丰速运");
            }

            @Override
            public WaybillTrackResult track(String trackingNo) {
                return new WaybillTrackResult(trackingNo, "sf", List.of("已揽收"));
            }
        };
    }

    @Test
    @DisplayName("判据 1：注册表行数 ≡ 目录行数、code 逐字同序（硬编码分支 ⇒ 红）")
    void registryMirrorsCatalogueRowForRow() {
        CarrierRegistry registry = new CarrierRegistry(List.of(new ManualWaybillProvider()));

        assertThat(registry.carriers()).extracting(Carrier::code)
                .containsExactlyElementsOf(CarrierCatalogue.entries().stream().map(CarrierCatalogue.Entry::code).toList());
    }

    @Test
    @DisplayName("判据 1b：加一行目录 ⇒ 注册表多一家（加配置而不是加流程）")
    void addingACatalogueRowAddsOneCarrier() {
        List<CarrierCatalogue.Entry> catalogue = new java.util.ArrayList<>(CarrierCatalogue.entries());
        catalogue.add(new CarrierCatalogue.Entry("probe", "探针承运商", "express", "PROBE", false, false, false));

        CarrierRegistry registry = new CarrierRegistry(catalogue, List.of(new ManualWaybillProvider()));

        assertThat(registry.carriers()).hasSize(CarrierCatalogue.entries().size() + 1);
        assertThat(registry.carriers()).extracting(Carrier::displayName).contains("探针承运商");
        assertThat(registry.carrierOf("probe").canCreate()).isFalse();
        assertThat(registry.carrierOf("probe").mode()).isEqualTo(Carrier.MODE_MANUAL);
    }

    @Test
    @DisplayName("判据 2：未登记 / 空 code ⇒ manual 兜底（不抛错、不编一家承运商）")
    void unknownCarrierFallsBackToManual() {
        CarrierRegistry registry = new CarrierRegistry(List.of(new ManualWaybillProvider()));

        Carrier fromNull = registry.carrierOf(null);
        Carrier fromBlank = registry.carrierOf("  ");
        Carrier fromUnknown = registry.carrierOf("not-registered");

        assertThat(fromNull.code()).isEqualTo("manual");
        assertThat(fromBlank.code()).isEqualTo("manual");
        assertThat(fromUnknown.code()).isEqualTo("manual");
        assertThat(fromUnknown.canCreate()).isFalse();
        assertThat(fromUnknown.isManual()).isTrue();
    }

    @Test
    @DisplayName("判据 3：声明 canCreate=true 但没 provider ⇒ 对 UI 仍是「不能」+ 具名过声明")
    void declaredButUnimplementedNeverLeaksToUi() {
        List<CarrierCatalogue.Entry> overClaiming = List.of(
                new CarrierCatalogue.Entry("ghost", "没接的承运商", "express", "GHOST", true, false, false));
        CarrierRegistry registry = new CarrierRegistry(overClaiming, List.of(new ManualWaybillProvider()));

        Carrier ghost = registry.carrierOf("ghost");
        assertThat(ghost.canCreate()).as("声明了能力但没人实现 ⇒ 对 UI 不能谎报").isFalse();
        assertThat(ghost.mode()).isEqualTo(Carrier.MODE_MANUAL);
        assertThat(registry.overClaimed()).containsExactly("ghost");
    }

    @Test
    @DisplayName("判据 3b：声明与实现对齐 ⇒ 能力位为真（证明交集不是恒 false）")
    void declaredAndImplementedTurnsTheBitOn() {
        List<CarrierCatalogue.Entry> catalogue = List.of(
                new CarrierCatalogue.Entry("sf", "顺丰速运", "express", "SF", true, false, true));
        CarrierRegistry registry = new CarrierRegistry(catalogue, List.of(capableProvider()));

        Carrier sf = registry.carrierOf("sf");
        assertThat(sf.canCreate()).isTrue();
        assertThat(sf.canTrack()).isTrue();
        assertThat(sf.mode()).isEqualTo(Carrier.MODE_API);
        assertThat(registry.overClaimed()).isEmpty();
    }

    @Test
    @DisplayName("判据 3c：生产目录零过声明（把任一 canCreate 改 true 而不接 provider ⇒ 本判据红）")
    void productionCatalogueHasNoOverClaim() {
        CarrierRegistry registry = new CarrierRegistry(List.of(new ManualWaybillProvider()));

        assertThat(registry.overClaimed())
                .as("生产目录声明了能力却没有 provider 实现 —— 这是「声称能做而实际不能」")
                .isEmpty();
    }

    @Test
    @DisplayName("判据 4：未实现的方法抛「不支持」（422），不返回假数据")
    void unimplementedMethodsThrowInsteadOfReturningFakeData() {
        ManualWaybillProvider manual = new ManualWaybillProvider();

        assertThatThrownBy(() -> manual.create(new WaybillCreateRequest("o-1", "张三", "13800000000", "杭州市西湖区文三路 1 号", 1, null)))
                .isInstanceOf(WaybillUnsupportedException.class)
                .hasFieldOrPropertyWithValue("httpStatus", 422)
                .hasMessageContaining("手填单号");
        assertThatThrownBy(() -> manual.track("SF123"))
                .isInstanceOf(WaybillUnsupportedException.class)
                .hasMessageContaining("轨迹查询");
        assertThatThrownBy(() -> manual.cancel("SF123"))
                .isInstanceOf(WaybillUnsupportedException.class)
                .hasMessageContaining("取消运单");
    }

    @Test
    @DisplayName("判据 5：每家登记承运商都有轨迹查询编码映射（manual 除外）")
    void everyRegisteredCarrierHasATrackQueryCode() {
        for (CarrierCatalogue.Entry entry : CarrierCatalogue.entries()) {
            if (CarrierCatalogue.MANUAL_CODE.equals(entry.code())) {
                continue;
            }
            assertThat(entry.trackQueryCode())
                    .as("承运商 %s 缺轨迹查询编码映射", entry.displayName())
                    .isNotBlank();
        }
    }
}
