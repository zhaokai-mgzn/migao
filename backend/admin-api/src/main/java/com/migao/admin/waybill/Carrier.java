package com.migao.admin.waybill;

/**
 * 承运商注册表的**对外一行**（issue #8698；口径文档 §3-5）。
 *
 * <p>字段就是口径文档要求的四件事：carrier code / 显示名 / 能力位 / 轨迹查询编码映射。
 * {@code mode} 是**生效形态**：{@code api} = 已接入取号（有 provider 且真的能取号）；
 * {@code manual} = 退回手填（今天所有承运商都是这个形态）。</p>
 *
 * <p>🔴 <b>能力位是「交集」不是「声明」</b>：{@code canCreate} = 目录声明 ∧ provider 实现
 * （见 {@link CarrierRegistry}）。这样「把某家声明成能做但没接 provider」在 UI 上**不会**
 * 变成一个可点的按钮 —— 判据 {@code CarrierRegistryTest} 另有专门一条盯这种过声明。</p>
 *
 * @param code          稳定 code（ASCII slug；租户配置里存的就是它）
 * @param displayName   商家可见名（与 {@code frontend/admin-web/src/lib/logistics.ts} 的词表同字）
 * @param logisticsType 物流类型（{@code express} 快递 / {@code logistics} 物流专线）
 * @param trackQueryCode 轨迹查询编码映射（既有 {@code logistics_track} 工具认的 code；{@code null} = 无映射）
 * @param canCreate     能否**真的**取号
 * @param canCancel     能否**真的**取消运单（P4 才做闭环）
 * @param canTrack      能否**真的**查轨迹
 * @param mode          生效形态：{@code api} / {@code manual}
 */
public record Carrier(
        String code,
        String displayName,
        String logisticsType,
        String trackQueryCode,
        boolean canCreate,
        boolean canCancel,
        boolean canTrack,
        String mode) {

    public static final String MODE_API = "api";
    public static final String MODE_MANUAL = "manual";

    /** 手填单号（= 今天的能力；也是所有未接入承运商的兜底形态）。 */
    public static final Carrier MANUAL = new Carrier(
            CarrierCatalogue.MANUAL_CODE, "手填单号", null, null, false, false, false, MODE_MANUAL);

    public boolean isManual() {
        return MODE_MANUAL.equals(mode);
    }
}
