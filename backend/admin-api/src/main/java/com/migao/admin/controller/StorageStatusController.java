package com.migao.admin.controller;

import com.migao.admin.config.StorageDeploymentSelfCheck;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * {@code GET /api/version/storage} —— **上传存储形态**的只读读面（集群 P0-3，issue #9026）。
 *
 * <h3>为什么需要它</h3>
 * <p>多实例下「上传打到实例 A、图片读到实例 B ⇒ 404」是 P0-3 的核心故障面，而排查它的第一问是
 * 「**这台实例的图片写在哪**」。{@code /actuator/health} 里已有一份读数
 * （{@code StorageHealthIndicator} 的 {@code uploadStorage} 条目），但部署形态下 nginx 把
 * {@code /actuator/**} 整段 {@code return 404}（{@code deploy/swas/nginx.conf}，与
 * {@link VersionController} 类注释同一前提）⇒ 运维在生产**读不到**它。
 * 本端点挂在 nginx 已放行的 {@code /api/} 前缀下，回答同一个问题。</p>
 *
 * <h3>为什么不塞进 {@code /api/version}</h3>
 * <p>那个端点的字段面被既有判据**冻结为 4 个**（{@code app}/{@code sha}/{@code tag}/{@code builtAt}，
 * 判据 = {@code tests/unit_ci_workflows/test_served_version_verify.py} 的字段白名单；部署腿靠它比对
 * served sha）—— 可观测性不该去动部署契约，所以另开一条路径（与 {@code /api/version/migrations} 同族）。</p>
 *
 * <h3>暴露什么 / 不暴露什么（本端点是 {@code permitAll}，泄露面必须显式受限）</h3>
 * <p>字段面**恰好 4 个**非敏感值：{@code storage}（{@code oss}/{@code local}/{@code unknown}）、
 * {@code multiInstance}、{@code replicas}、{@code ossConfigured} ——
 * <b>不含</b> endpoint / AccessKey / bucket / 本地路径 / 主机名。
 * 判据 = {@code StorageStatusControllerTest}（含「不泄露凭据」与「未装配 ⇒ unknown，不猜 local」两条）。</p>
 *
 * <p>数据源与健康端点**同一个** {@link StorageDeploymentSelfCheck}（不各算一套）。
 * 取不到（切片上下文 / 未装配）⇒ 四项都报 {@code unknown}：**不猜 local** —— 猜错会掩盖真故障。</p>
 */
@RestController
public class StorageStatusController {

    private final ObjectProvider<StorageDeploymentSelfCheck> storageSelfCheck;

    public StorageStatusController(ObjectProvider<StorageDeploymentSelfCheck> storageSelfCheck) {
        this.storageSelfCheck = storageSelfCheck;
    }

    /** {@code GET /api/version/storage} —— 只读、无需鉴权（{@code SecurityConfig} 已放行）。 */
    @GetMapping(value = "/api/version/storage", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Map<String, String>> storage() {
        Map<String, String> facts = new LinkedHashMap<>();
        StorageDeploymentSelfCheck check =
                storageSelfCheck == null ? null : storageSelfCheck.getIfAvailable();
        if (check == null) {
            // 「没装配」必须长得像「没装配」：报 unknown，不猜 local（猜错会掩盖真故障）
            facts.put("storage", "unknown");
            facts.put("multiInstance", "unknown");
            facts.put("replicas", "unknown");
            facts.put("ossConfigured", "unknown");
            return ResponseEntity.ok(facts);
        }
        facts.put("storage", check.storageType());
        facts.put("multiInstance", String.valueOf(check.isMultiInstance()));
        facts.put("replicas", String.valueOf(check.replicas()));
        facts.put("ossConfigured", String.valueOf(check.ossConfigured()));
        return ResponseEntity.ok(facts);
    }
}
