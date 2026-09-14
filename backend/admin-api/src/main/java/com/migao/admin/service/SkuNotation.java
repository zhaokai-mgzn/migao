package com.migao.admin.service;

/**
 * SKU 组合书写口径统一（售卖方式 / 门幅）—— issue #3621。
 *
 * <p>背景：同一语义在系统里有多种写法，各处匹配口径不一致 → 同一物理规格被判成不同组合，
 * 或"按组合回退匹配"字面命中 0 行：
 * <ul>
 *   <li>售卖方式：agent / 前端按中文业务术语传（{@code 散剪} / {@code 整卷}），
 *       库内是枚举（{@code bulk_cut} / {@code full_roll}）；</li>
 *   <li>门幅：库内是裸数值（{@code 2.8}，种子数据），agent / 前端会写带单位（{@code 2.8米}），
 *       历史数据还有更老的 {@code 门幅2.8米}。</li>
 * </ul>
 *
 * <p>本类是 Java 侧归一化口径的统一入口（{@code OrderService.matchSkuId} 组合回退复用）。
 * {@code ProductService} 的私有 {@code translateSellingMethod} / {@code normalizeDoorWidth}
 * （#3546 调价路径）与本类方法是同一口径的两份实现：该文件由并行包（#3616）独占，
 * 本包未越界改动，建议后续由 #3546 / #3616 侧改为 delegate 到本类，避免口径再次漂移。
 *
 * <p>归一化只用于<b>匹配比较</b>，不回写库内值 —— 库内两种写法都真实存在，回写会造成
 * SKU 编码 / 前端展示口径漂移（与 #3546 的同类处理一致）。
 */
final class SkuNotation {

    private SkuNotation() {
    }

    /**
     * 售卖方式归一化：中文业务标签 → 库内枚举；已是枚举则原样透传。
     * 例：{@code 散剪 → bulk_cut}、{@code 整卷 → full_roll}、{@code bulk_cut → bulk_cut}。
     */
    static String normalizeSellingMethod(String raw) {
        if (raw == null) {
            return null;
        }
        String trimmed = raw.trim();
        return switch (trimmed) {
            case "散剪" -> "bulk_cut";
            case "整卷" -> "full_roll";
            case "按片" -> "per_piece";
            case "定高" -> "fixed_height";
            case "买通" -> "buy_through";
            default -> trimmed;
        };
    }

    /**
     * 门幅归一化：{@code '门幅2.8米'} / {@code '2.8m'} / {@code ' 2.8 '} → {@code '2.8'}。
     * 只去 legacy「门幅」前缀与「米/m」后缀，不做数值换算。null / 空串返回 null。
     */
    static String normalizeDoorWidth(String raw) {
        if (raw == null) {
            return null;
        }
        String normalized = raw.trim().replaceAll("^门幅", "").replaceAll("(?i)\\s*[米m]$", "").trim();
        return normalized.isEmpty() ? null : normalized;
    }

    /**
     * 是否为同一物理门幅（双侧归一化比较）。真正不同的门幅（{@code 2.8} vs {@code 3.2}）
     * 仍然不等 —— 防归一化过宽把不同 SKU 合并。
     */
    static boolean sameDoorWidth(String a, String b) {
        String na = normalizeDoorWidth(a);
        return na != null && na.equals(normalizeDoorWidth(b));
    }
}
