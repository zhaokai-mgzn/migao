package com.migao.admin.config;

import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 把**上传存储形态**暴露到 {@code /actuator/health}（集群 P0-3）。
 *
 * <p>运维只需一眼看出「这台实例的图片写在哪」：{@code storage=oss} 说明多实例安全，
 * {@code storage=local} 说明这台实例只会写自己那块磁盘（多实例下必然 404）。</p>
 *
 * <h2>{@code ⚠️ 恒 UP}（不参与健康判定）</h2>
 * <p>与 {@link MigrationHealthIndicator} 同口径：本类**只暴露事实**，不熔断。
 * 理由：单实例 + 本地盘是**合法**部署形态（本仓当前生产就是），把它判 DOWN 会把正常环境打挂；
 * 「多实例 + 缺 OSS」这一**真正**要拦的形态已经由 {@link StorageDeploymentSelfCheck} 在
 * **启动期 fail-close**（根本到不了健康检查）。</p>
 *
 * <h2>不泄露什么</h2>
 * <p>details 只有 4 个非敏感字段：{@code storage} / {@code multiInstance} / {@code replicas} /
 * {@code ossConfigured} —— <b>不含</b> endpoint / AccessKey / bucket / 本地路径。</p>
 *
 * <p>⚠️ 生产形态下 nginx 屏蔽 {@code /actuator/**}（{@code deploy/swas/nginx.conf}），
 * 所以同一份读数另有 {@code /api/version/storage}（{@code /api/} 前缀已放行）——
 * 两个面读的是**同一个** {@link StorageDeploymentSelfCheck}，不各算一套。</p>
 */
@Component("uploadStorage")
public class StorageHealthIndicator implements HealthIndicator {

    private final StorageDeploymentSelfCheck selfCheck;

    public StorageHealthIndicator(StorageDeploymentSelfCheck selfCheck) {
        this.selfCheck = selfCheck;
    }

    @Override
    public Health health() {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("storage", selfCheck.storageType());
        details.put("multiInstance", selfCheck.isMultiInstance());
        details.put("replicas", selfCheck.replicas());
        details.put("ossConfigured", selfCheck.ossConfigured());
        return Health.up().withDetails(details).build();
    }
}
