package com.migao.admin.waybill;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 承运商**注册表**（issue #8698；口径文档 §3-5）。
 *
 * <p><b>它做三件事，且只有这三件</b>：</p>
 * <ol>
 *   <li>把 {@link CarrierCatalogue} 的登记行 + Spring 里的 {@link WaybillProvider} 合成**对外能力位**；</li>
 *   <li>crucial —— 能力位取**交集**（声明 ∧ 实现）：声明了但没 provider 的承运商对 UI 是「不能」，
 *       不是「声称能做」（口径「不能声称能做而实际不能」）；</li>
 *   <li>未登记 / 未接入的 code ⇒ 一律落到 {@link Carrier#MANUAL}（manual 兜底，**不产生任何外呼**）。</li>
 * </ol>
 *
 * <p>🔴 <b>「支持多家」= 加配置而不是加流程</b>：本类没有任何 {@code if (code.equals(...))} 分支，
 * 新增一家承运商 = 在 {@link CarrierCatalogue} 加一行（+ 接真实第三方时加一个 provider Bean）。
 * 判据 {@code CarrierRegistryTest} 用「注册表行数 = 目录行数」钉住这一点：
 * 谁想走 if/else 硬编码，就得先让这条判据变红。</p>
 *
 * <p>⚠️ 构造期对**过声明**打一条 WARN：声明能取号而没人实现，是线上最容易被误读成
 * 「按钮能点但点了报错」的形态 —— 让它至少在启动日志里可见。</p>
 */
@Slf4j
@Component
public class CarrierRegistry {

    private final List<CarrierCatalogue.Entry> catalogue;
    private final Map<String, WaybillProvider> providers;
    private final WaybillProvider manualProvider;

    /**
     * 生产装配：目录 = {@link CarrierCatalogue#entries()}，provider = 全部 Spring Bean。
     *
     * <p>🔴 必须显式 {@code @Autowired}：本类有**两个**构造器（另一个是测试用的目录注入形态）——
     * Spring 在多构造器且无注解时**选不出**装配方式，会回落到「无参构造器」并抛
     * {@code NoSuchMethodException} ⇒ 全上下文测试（{@code SecurityConfigTest}）59 条全红（实测一次）。</p>
     */
    @Autowired
    public CarrierRegistry(List<WaybillProvider> providerBeans) {
        this(CarrierCatalogue.entries(), providerBeans);
    }

    /** 测试装配（可注入一条自定义目录行，用来证明「声明 > 实现」不会漏到 UI）。 */
    CarrierRegistry(List<CarrierCatalogue.Entry> catalogue, List<WaybillProvider> providerBeans) {
        this.catalogue = List.copyOf(catalogue);
        Map<String, WaybillProvider> map = new LinkedHashMap<>();
        WaybillProvider manual = new ManualWaybillProvider();
        for (WaybillProvider provider : providerBeans) {
            map.put(provider.carrierCode(), provider);
            if (CarrierCatalogue.MANUAL_CODE.equals(provider.carrierCode())) {
                manual = provider;
            }
        }
        this.providers = Map.copyOf(map);
        this.manualProvider = manual;
        reportOverClaims();
    }

    /** 全部登记行（顺序 = 目录顺序）。 */
    public List<Carrier> carriers() {
        List<Carrier> list = new ArrayList<>(catalogue.size());
        for (CarrierCatalogue.Entry entry : catalogue) {
            list.add(effective(entry));
        }
        return List.copyOf(list);
    }

    /**
     * 把「租户配的 code」解析成**生效承运商**。
     *
     * <p>空 / 未登记 ⇒ {@link Carrier#MANUAL}（code 必然是 {@code manual}，物化为手填）；
     * 登记了但**没接入** ⇒ 该承运商自身、但 {@code mode = manual} —— 显示名仍是商家选的那家
     * （UI 突然变成「手填单号」会让人以为配置丢了），而取号能力位是 false ⇒ 服务层拒绝、不发外呼。</p>
     */
    public Carrier carrierOf(String code) {
        if (code == null || code.isBlank()) {
            return Carrier.MANUAL;
        }
        CarrierCatalogue.Entry entry = entryOf(code);
        if (entry == null) {
            log.debug("承运商 {} 未登记 ⇒ manual 兜底", code);
            return Carrier.MANUAL;
        }
        return effective(entry);
    }

    /** 本 code 是否可被租户配置选中（登记过、或显式 manual）。 */
    public boolean isKnown(String code) {
        if (code == null || code.isBlank()) {
            return false;
        }
        return CarrierCatalogue.MANUAL_CODE.equals(code) || entryOf(code) != null;
    }

    /** 解析出的生效承运商对应的 provider（manual ⇒ {@link ManualWaybillProvider}，结构上无任何外呼）。 */
    public WaybillProvider providerOf(Carrier carrier) {
        return providers.getOrDefault(carrier.code(), manualProvider);
    }

    /**
     * 过声明清单：目录声明 true、但没 provider（或 provider 自己说 false）的行。
     *
     * <p>正常应恒为空。判据 {@code CarrierRegistryTest} 直接断言它为空（红 = 有人把声明翻了 true
     * 却没接实现）；生产构造期也打 WARN，避免只靠测试发现。</p>
     */
    public List<String> overClaimed() {
        List<String> over = new ArrayList<>();
        for (CarrierCatalogue.Entry entry : catalogue) {
            WaybillProvider provider = providers.get(entry.code());
            if (declared(entry) && (provider == null
                    || !(provider.canCreate() || provider.canCancel() || provider.canTrack()))) {
                over.add(entry.code());
            }
        }
        return List.copyOf(over);
    }

    /** 本注册表的目录行（**实例目录**，不是静态目录 —— 测试注入的自定义行据此生效）。 */
    private CarrierCatalogue.Entry entryOf(String code) {
        String normalized = code.trim();
        return catalogue.stream().filter(e -> e.code().equals(normalized)).findFirst().orElse(null);
    }

    private boolean declared(CarrierCatalogue.Entry entry) {
        return entry.canCreate() || entry.canCancel() || entry.canTrack();
    }

    /** 声明 ∧ 实现：对 UI **只**暴露真的能做的事。 */
    private Carrier effective(CarrierCatalogue.Entry entry) {
        WaybillProvider provider = providers.get(entry.code());
        boolean canCreate = entry.canCreate() && provider != null && provider.canCreate();
        boolean canCancel = entry.canCancel() && provider != null && provider.canCancel();
        boolean canTrack = entry.canTrack() && provider != null && provider.canTrack();
        return new Carrier(entry.code(), entry.displayName(), entry.logisticsType(), entry.trackQueryCode(),
                canCreate, canCancel, canTrack,
                canCreate ? Carrier.MODE_API : Carrier.MODE_MANUAL);
    }

    private void reportOverClaims() {
        List<String> over = overClaimed();
        if (!over.isEmpty()) {
            log.warn("承运商注册表存在**过声明**（声明了能力但没有 provider 实现）：{} —— "
                    + "对 UI 已按「不能」处理，请补 provider 实现或把声明改回 false", over);
        }
    }
}
