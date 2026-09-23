package com.migao.admin.config;

import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 把**最近一轮迁移的结果**暴露到 {@code /actuator/health} 的 details 里（issue #4517）。
 *
 * <h2>它解决什么</h2>
 * 本仓对**非连接类**迁移失败是「跳过这一条、继续跑后面的」（{@link MigrationRunner}，issue #3270
 * 的刻意权衡）⇒ 「迁移全过」与「有迁移被跳过」在**部署期不可区分**：应用照常 UP、探活 200、
 * 部署腿 success，而故障面后移到业务 500。
 *
 * <p>本会话已**三次**因此付出代价：{@code V74}（issue #4501，载体打在不存在的列上 ⇒ 回填从未发生）、
 * {@code V72}（issue #4514，引用 {@code f.sort_order} ⇒ 整份回滚）、以及由 V72 引发的
 * 「**云测试环境生成加工单对所有订单 500**」—— 而**部署一直是 success**。</p>
 *
 * <h2>⚠️ 为什么**恒 UP**（不熔断）</h2>
 * 若迁移失败让健康检查变 {@code DOWN}，那 {@link MigrationRunner#isKnownBenignLegacy} 里那几条
 * **每次起栈必失败**的历史非幂等迁移（目标态已由 {@code backend/admin-api/src/main/resources/db/init/schema.sql} 达成）
 * 就会把**整个环境打挂** —— 那是比原问题更糟的故障。
 * ⇒ 本类**只暴露事实**，健康判定**不含**迁移失败；是否 fail 部署由 owner 在部署腿上裁定。
 *
 * <p>另注：本仓迁移是「**全有或全无**」（{@code jdbc.execute(整个文件)} 是一个隐式事务，
 * 文件里任何一条失败 ⇒ 整份回滚）⇒ 看到某文件出现在 {@code failed_migrations} 里，
 * 含义是「**它一条都没生效**」，不是「它跑了一部分」。</p>
 */
@Component("migrationHealth")
public class MigrationHealthIndicator implements HealthIndicator {

    private final MigrationRunner migrationRunner;

    public MigrationHealthIndicator(MigrationRunner migrationRunner) {
        this.migrationRunner = migrationRunner;
    }

    @Override
    public Health health() {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("failed_migrations", migrationRunner.getLastFailedMigrations());
        details.put("failed_real_count", migrationRunner.getLastFailedRealCount());
        details.put("failed_known_benign_count", migrationRunner.getLastFailedBenignCount());
        details.put("skipped_by_ledger_count", migrationRunner.getLastSkippedByLedger());
        // ⚠️ 恒 UP：见类注释「为什么恒 UP（不熔断）」。
        //    failed_migrations 非空**不是**健康问题，是**可观测**问题 —— 让部署腿去判。
        return Health.up().withDetails(details).build();
    }
}
