package com.migao.admin.controller;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 「线上跑的是哪个 build」的**可判读面**（issue #6951）。
 *
 * <h3>为什么需要它</h3>
 * <p>部署形态下 {@code /actuator/health} 与 {@code /actuator/info} 被 nginx 屏蔽
 * （{@code deploy/swas/nginx.conf} 的 {@code location ~ ^/(actuator|v3/api-docs|swagger-ui)(/|$)} ⇒ 404），
 * 而 {@code /api/**} 是放行面 ⇒ 探活面**不等于**探版本面：线上只能探到「服务活着」
 * （实测 {@code POST /api/auth/sms/send} 空体 ⇒ 422），探不到「跑的是哪个 build」。</p>
 *
 * <p>判据消费方 = {@code deploy/scripts/served-version-verify.sh}（部署腿在部署后断言
 * 「线上 sha == 本次部署的 sha」，不一致 ⇒ 具名判红）。</p>
 *
 * <h3>真值来源：**构建期注入**，不是运行时现算</h3>
 * <p>部署形态下容器里**没有 {@code .git}**（C′ 服务器侧构建的构建上下文是 codeload 归档树，
 * 运行时镜像里也不带源码）⇒ 任何运行时 {@code git rev-parse} 都是错的。
 * 三个值由 CI/部署时经 {@code docker build --build-arg} 注入
 * （{@code deploy/swas/deploy.sh} 的 C′ 构建段）；rollback 路径（拉 ACR 预构建镜像）下则是
 * 「**镜像自身的不可变身份**」—— 镜像里烘焙的就是它构建时的那次部署真值。</p>
 *
 * <h3>公开（无鉴权）与它**不**泄露什么</h3>
 * <p>本端点挂在 {@code permitAll}（{@code SecurityConfig}）：它要能被**未鉴权**的探针读到
 * （与 {@code /actuator/health} 同级的对外读面）。响应体**只有** 5 个字段：
 * {@code app} / {@code sha} / {@code tag} / {@code builtAt} / {@code servedAt} ——
 * <b>不含</b>主机名 / 路径 / 环境变量 / 依赖版本 / 配置 / 任何业务字段。
 * 判据 = {@code tests/unit_ci_workflows/test_served_version_verify.py} 的「字段白名单」判据
 * （加了新字段就判红 ⇒ 必须重新过一遍「它会不会泄露」）。</p>
 *
 * <h3>三态语义（消费方必须照此判，不许把「取不到」当「一致」）</h3>
 * <ul>
 *   <li>{@code sha} 非空且与期望一致 ⇒ 线上**就是**这次构建；</li>
 *   <li>{@code sha} 非空但不一致 ⇒ **判红**（这正是本端点存在的理由）；</li>
 *   <li>{@code sha} 为空（老镜像没有注入面 / 非部署形态启动）⇒ 消费方判**探不到**
 *       （{@code exit 3}），**不得**判绿、也不得判红 —— 那是另一次修复。</li>
 * </ul>
 */
@Slf4j
@RestController
public class VersionController {

    /** 构建期注入的提交 sha（完整 40 位 hex；未注入 ⇒ 空串 ⇒ 消费方判「探不到」）。 */
    private final String sha;

    /** 构建期注入的镜像 tag（{@code sha-<7hex>} 或显式回滚的 tag；仅供人读与归因）。 */
    private final String tag;

    /** 构建期注入的构建时刻（ISO-8601；异常形态**原样**报出，不猜、不吞）。 */
    private final String builtAt;

    private final Environment environment;

    // ⚠️ 占位符写**环境变量原名**（不写 `migao.build.sha` 那种点号形态）：本仓的既有形态是
    //    `application.yml` 里 `${RDS_HOST:…}` 直引环境变量 ⇒ 这条路径**不依赖** Spring Boot 的
    //    环境变量宽松绑定（relaxed binding）是否覆盖 `@Value` 解析 —— 少一个"可能不成立"的假设。
    public VersionController(
            @Value("${MIGAO_BUILD_SHA:}") String sha,
            @Value("${MIGAO_BUILD_TAG:}") String tag,
            @Value("${MIGAO_BUILT_AT:}") String builtAt,
            Environment environment) {
        this.sha = sha == null ? "" : sha.trim();
        this.tag = tag == null ? "" : tag.trim();
        this.builtAt = builtAt == null ? "" : builtAt.trim();
        this.environment = environment;
    }

    /**
     * {@code GET /api/version} —— 只读、无需鉴权、nginx 已放行（{@code /api/} 前缀）。
     *
     * <p>字段顺序固定（{@code LinkedHashMap}）⇒ 人读日志与探针 grep 都稳定。</p>
     */
    @GetMapping(value = "/api/version", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Map<String, String>> version() {
        Map<String, String> body = new LinkedHashMap<>();
        body.put("app", appName());
        body.put("sha", sha);
        body.put("tag", tag);
        body.put("builtAt", builtAt);
        body.put("servedAt", OffsetDateTime.now(ZoneId.of("Asia/Shanghai"))
                .format(DateTimeFormatter.ISO_OFFSET_DATE_TIME));
        if (sha.isEmpty()) {
            // 「没跑」必须长得像「没跑」：注入面缺失时部署腿会判 exit 3（探不到），
            // 但**日志里要说清是为什么**（否则下一个人只会看到「线上 sha 是空串」）。
            log.warn("MIGAO_BUILD_SHA 未注入（非部署形态启动？）⇒ /api/version 报不出构建身份，"
                    + "部署腿的 served-version 判据会判「探不到」(exit 3)");
        }
        return ResponseEntity.ok(body);
    }

    /** 应用名（{@code spring.application.name}）；取不到 ⇒ 空串（消费方可据此判「不是这个服务」）。 */
    private String appName() {
        String name = environment.getProperty("spring.application.name", "");
        return name == null ? "" : name.trim();
    }
}
