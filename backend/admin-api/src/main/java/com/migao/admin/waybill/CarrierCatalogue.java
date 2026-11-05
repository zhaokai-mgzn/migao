package com.migao.admin.waybill;

import java.util.List;
import java.util.Optional;

/**
 * 承运商**注册表数据**（issue #8698；口径文档 §3-5「支持多家 = 加配置而不是加流程」）。
 *
 * <p><b>唯一数据面</b>：一家承运商 = 下面 {@link #ENTRIES} 里的**一行**。新增 / 下线一家承运商
 * **只改这里**（+ 接入真实第三方时再加一个 {@link WaybillProvider} 实现 Bean），
 * 不新增任何 {@code if (carrier.equals("顺丰"))} 分支 —— 设置页与发货页的能力位都从
 * {@link CarrierRegistry} 现取，判据 {@code CarrierRegistryTest} 钉住「目录行数 = 注册表行数」。</p>
 *
 * <p>🔴 <b>本表的能力位是「产品声明」</b>，不是「已实现」：{@link CarrierRegistry} 会把声明与
 * provider 的实际实现取交集后再对外，<b>过声明（声明 true 而没实现）在 UI 上不生效</b>，
 * 且 {@code CarrierRegistryTest} 会具名判红（口径「不能声称能做而实际不能」）。</p>
 *
 * <p><b>轨迹查询编码映射</b>（口径 §3-1「取号是主线，轨迹是副产品」）：{@code trackQueryCode} 逐字
 * 对齐既有 {@code backend/ai-agent-service/app/core/logistics_trace_cache.py} 的
 * {@code COMPANY_NAME_MAP} 键（{@code SF} / {@code ZTO} / …）—— 取号落 {@code tracking_no} 之后
 * 既有轨迹工具零改动可用，本表只是那份映射在服务端的**可读副本**。
 * ⚠️ P0 **不改** Python 侧（它今天用阿里云市场的 code，另一份真值源在同文件；
 * 两边合并口径属 P1，见 PR body「没做的」）。四季安无公开取号接口，轨迹用 {@code SJA56}
 * （口径文档 §2.1 / §9 两次实测）。</p>
 *
 * <p>⚠️ 显示名与 {@code frontend/admin-web/src/lib/logistics.ts} 的
 * {@code LOGISTICS_COMPANIES} **逐字同名**（跨端契约：发货页下拉的既有候选就是这 7 家）；
 * 判据 {@code tests/unit_ci_workflows/test_waybill_carrier_registry.py} 跨文件对齐两处。</p>
 */
public final class CarrierCatalogue {

    /** 手填单号的 code（租户「没配」与「配了但未接入」都落到它）。 */
    public static final String MANUAL_CODE = "manual";

    /**
     * 一家承运商的**声明行**。
     *
     * @param code           稳定 code（租户配置里存的值）
     * @param displayName    商家可见名
     * @param logisticsType  {@code express} 快递 / {@code logistics} 物流专线
     * @param trackQueryCode 轨迹查询编码映射（{@code null} = 今天没有映射）
     * @param canCreate      产品声明：能取号（P0 全部 false —— 没接任何真实第三方）
     * @param canCancel      产品声明：能取消（P0 全部 false —— 闭环是 P4）
     * @param canTrack       产品声明：能查轨迹（P0 全部 false —— Java 侧没有轨迹 provider）
     */
    public record Entry(
            String code,
            String displayName,
            String logisticsType,
            String trackQueryCode,
            boolean canCreate,
            boolean canCancel,
            boolean canTrack) {
    }

    /**
     * 承运商登记表（**顺序即候选顺序**；与前端词表同序，快递在前、专线在后）。
     *
     * <p>P0 的 {@code canCreate/canCancel/canTrack} **一律 false**：一家都没接，
     * 全部走 manual 兜底（= 今天的手填单号）。这不是「留空」，是**如实声明**——
     * 声明 true 而没 provider 会被 {@link CarrierRegistry} 与判据同时抓住。</p>
     */
    private static final List<Entry> ENTRIES = List.of(
            new Entry(MANUAL_CODE, "手填单号", null, null, false, false, false),
            new Entry("debang", "德邦快递", "express", "DB", false, false, false),
            new Entry("sf", "顺丰速运", "express", "SF", false, false, false),
            new Entry("zto", "中通快递", "express", "ZTO", false, false, false),
            new Entry("yto", "圆通速递", "express", "YTO", false, false, false),
            new Entry("yunda", "韵达快递", "express", "YUNDA", false, false, false),
            new Entry("sto", "申通快递", "express", "STO", false, false, false),
            new Entry("sja", "四季安物流", "logistics", "SJA56", false, false, false));

    private CarrierCatalogue() {
    }

    /** 全部声明行（只读；顺序即候选顺序）。 */
    public static List<Entry> entries() {
        return ENTRIES;
    }

    /** 按 code 取**声明行**（未登记 ⇒ {@code null}：调用方负责 manual 兜底，不编默认值）。 */
    public static Entry entryOf(String code) {
        if (code == null || code.isBlank()) {
            return null;
        }
        return ENTRIES.stream().filter(e -> e.code().equals(code.trim())).findFirst().orElse(null);
    }

    /**
     * 按 code 取**只含声明位**的 {@link Carrier}（不含 provider 实际能力 ⇒ 仅供异常文案取显示名）。
     *
     * <p>⚠️ 对外能力位**必须**走 {@link CarrierRegistry}（声明 ∩ 实现），不要拿本方法去画 UI。</p>
     */
    public static Carrier find(String code) {
        Entry entry = entryOf(code);
        if (entry == null) {
            return null;
        }
        return new Carrier(entry.code(), entry.displayName(), entry.logisticsType(), entry.trackQueryCode(),
                entry.canCreate(), entry.canCancel(), entry.canTrack(),
                entry.canCreate() ? Carrier.MODE_API : Carrier.MODE_MANUAL);
    }

    /** 本 code 是否为**登记过**的承运商（租户配置写面的白名单；未登记 ⇒ 手填，不拒人）。 */
    public static boolean registered(String code) {
        return entryOf(code) != null;
    }

    /** 登记行的轨迹查询编码映射（未登记 / 无映射 ⇒ 空）。 */
    public static Optional<String> trackQueryCodeOf(String code) {
        Entry entry = entryOf(code);
        return entry == null ? Optional.empty() : Optional.ofNullable(entry.trackQueryCode());
    }
}
