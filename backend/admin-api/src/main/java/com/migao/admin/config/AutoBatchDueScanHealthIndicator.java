package com.migao.admin.config;

import com.migao.admin.service.AutoBatchDueScanService;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 把**到期扫描腿的心跳**暴露到 {@code /actuator/health} 的 details 里（issue #5184 判据 5）。
 *
 * <h2>它解决什么</h2>
 * 定时腿最典型的失效形态是「**静默停摆**」：cron 还挂着、应用照常 UP、探活 200、部署 success，
 * 而兜底已经不产出了 —— 于是「人工漏标不得压单」这条**保证**悄悄变成空话，
 * 没有任何东西会因此变红。本类把「这条腿活着的证据」摆到运维一眼能看到的地方：
 * {@code rounds}（轮数是否在涨）/ {@code last_success_at} / {@code last_failure_at} /
 * {@code last_scanned_tenants} / {@code last_dispatched} / {@code last_error}。
 * 与 {@code MigrationHealthIndicator}（#4517）同一范式。
 *
 * <h2>判据面（读源核过，不是推断）</h2>
 * {@code scripts/drift_audit.py} 的 {@code heartbeat} 判据**只扫 {@code .github/workflows/*.yml}
 * 里带 {@code schedule:} 的 workflow**（判定面 = 工作流，不是 JVM 里的定时任务）⇒
 * 本单的 Java 定时腿**不在那一档的判定面内**，不会自己制造一条「无心跳的调度任务」漂移。
 * 但「面外 ⇒ 天然通过」是**空过**，不是心跳可见 —— 所以心跳另走这条 actuator 面：
 * 它是**生产可见**的，且由守卫测试钉住（红证 = 去掉 details 里的时间戳 ⇒ 判据当场红）。
 *
 * <h2>⚠️ 为什么**恒 UP**（不熔断）</h2>
 * 与 {@code MigrationHealthIndicator} 同因：让「扫描腿没跑成」把 {@code /actuator/health}
 * 打成 {@code DOWN}，会把**整个环境**打挂（部署腿 / 探活 / 负载均衡一起红），
 * 那是比原问题更糟的故障。⇒ 本类**只暴露事实**；「停摆多久算故障」由观测方按
 * {@code last_success_at} 裁定（缺省关时这条腿本来就不该跑，见 {@code enabled}）。
 */
@Component("autoBatchDueScanHealth")
public class AutoBatchDueScanHealthIndicator implements HealthIndicator {

    private final AutoBatchDueScanService autoBatchDueScanService;

    public AutoBatchDueScanHealthIndicator(AutoBatchDueScanService autoBatchDueScanService) {
        this.autoBatchDueScanService = autoBatchDueScanService;
    }

    @Override
    public Health health() {
        Map<String, Object> details = new LinkedHashMap<>();
        // 关着的时候「没有心跳」是**正确状态**（这条腿本来就不该跑）⇒ 把开关本身也摆出来，
        // 免得观测方把「缺省关」读成「调度停摆」。
        details.put("enabled", autoBatchDueScanService.isEnabled());
        details.put("rounds", autoBatchDueScanService.getRounds());
        details.put("last_success_at", text(autoBatchDueScanService.getLastSuccessAt()));
        details.put("last_failure_at", text(autoBatchDueScanService.getLastFailureAt()));
        details.put("last_scanned_tenants", autoBatchDueScanService.getLastScannedTenants());
        details.put("last_dispatched", autoBatchDueScanService.getLastDispatched());
        details.put("last_error", autoBatchDueScanService.getLastError());
        // ⚠️ 恒 UP：见类注释「为什么恒 UP（不熔断）」。停摆判定留给观测方。
        return Health.up().withDetails(details).build();
    }

    /** 时间戳一律转成 ISO-8601 字符串（JSON 里可读、可比较；null = 尚未发生）。 */
    private static String text(OffsetDateTime at) {
        return at == null ? null : at.toString();
    }
}
