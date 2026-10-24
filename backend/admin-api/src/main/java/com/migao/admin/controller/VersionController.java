package com.migao.admin.controller;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

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
 * （与 {@code /actuator/health} 同级的对外读面）。响应体**只有** 4 个字段：
 * {@code app} / {@code sha} / {@code tag} / {@code builtAt} ——
 * <b>不含</b>主机名 / 路径 / 环境变量 / 依赖版本 / 配置 / 任何业务字段。
 * 判据 = {@code tests/unit_ci_workflows/test_served_version_verify.py} 与
 * {@code VersionControllerTest} 的「字段白名单」判据
 * （加了新字段就判红 ⇒ 必须重新过一遍「它会不会泄露」）。</p>
 *
 * <p>⚠️ <b>刻意没有 {@code servedAt}</b>：判据只看 {@code sha}（部署目标 = 构建身份），
 * 而任何「服务端现算的时刻」都要走全仓唯一的时钟单点 {@code BusinessClock}
 * （{@code BusinessClockSourceGuardTest} 会判红控制器里的时区字面量 / 无参 now()）
 * —— 为一个与判定无关的字段引入时钟依赖不划算；要「这个响应什么时候出的」，
 * 看 curl 侧的时间戳即可。</p>
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

    /**
     * 迁移执行器（用 {@code ObjectProvider} 延迟取：它 {@code implements CommandLineRunner}，
     * 构造期硬注入会与启动顺序纠缠；本端点只读它**已经发生**的事实）。
     *
     * <p>取不到（切片上下文 / 未装配）⇒ 端点报 `unknown`，**不报 0** —— 0 会被读成「跑了且全过」。</p>
     */
    private final org.springframework.beans.factory.ObjectProvider<com.migao.admin.config.MigrationRunner>
            migrationRunner;

    // ⚠️ 占位符写**环境变量原名**（不写 `migao.build.sha` 那种点号形态）：本仓的既有形态是
    //    `application.yml` 里 `${RDS_HOST:…}` 直引环境变量 ⇒ 这条路径**不依赖** Spring Boot 的
    //    环境变量宽松绑定（relaxed binding）是否覆盖 `@Value` 解析 —— 少一个"可能不成立"的假设。
    public VersionController(
            @Value("${MIGAO_BUILD_SHA:}") String sha,
            @Value("${MIGAO_BUILD_TAG:}") String tag,
            @Value("${MIGAO_BUILT_AT:}") String builtAt,
            Environment environment,
            org.springframework.beans.factory.ObjectProvider<com.migao.admin.config.MigrationRunner>
                    migrationRunner) {
        this.migrationRunner = migrationRunner;
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
        if (sha.isEmpty()) {
            // 「没跑」必须长得像「没跑」：注入面缺失时部署腿会判 exit 3（探不到），
            // 但**日志里要说清是为什么**（否则下一个人只会看到「线上 sha 是空串」）。
            log.warn("MIGAO_BUILD_SHA 未注入（非部署形态启动？）⇒ /api/version 报不出构建身份，"
                    + "部署腿的 served-version 判据会判「探不到」(exit 3)");
        }
        return ResponseEntity.ok(body);
    }

    /**
     * {@code GET /api/version/migrations} —— **迁移事实**（只读、只计数、无鉴权，nginx 已放行 `/api/` 前缀）。
     *
     * <p>为什么单独一个端点，而不是塞进 {@code /api/version}：后者的字段面被既有判据**冻结为 4 个**
     * （issue #6951：往响应里加任何东西都要当场红）—— 那是部署腿比对 served sha 的契约，
     * 不该为了可观测性去动它。</p>
     *
     * <p>为什么需要它：{@code MigrationRunner} 对非连接类失败是「跳过这条、继续跑」⇒ 库里少一张表时
     * 服务照常 UP、部署 success、页面 500，**没人看得见**（云上「采购单加载失败」排查时，
     * 最先要回答的就是「那几条迁移到底跑没跑」）。</p>
     */
    @GetMapping(value = "/api/version/migrations", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Map<String, String>> migrations() {
        return ResponseEntity.ok(migrationFacts());
    }

    /**
     * 迁移事实（只读、只计数）：
     * <ul>
     *   <li>{@code migrationsFailedReal} —— 真正需要修的失败条数（排除已知存量非幂等）；</li>
     *   <li>{@code migrationsFailedBenign} —— 属已知存量非幂等的条数（目标态已达成，重跑亦复现）；</li>
     *   <li>{@code migrationsAppliedByLedger} —— 本轮按台账**已应用**（跳过）的条数。</li>
     * </ul>
     *
     * <p>⚠️ 语义边界：**不参与健康判定**（与 {@code MigrationHealthIndicator} 同口径）——
     * 让探活 DOWN 会把「历史非幂等迁移每次起栈必失败」变成「整个环境打挂」，比原问题更糟。
     * 这三个数只回答一个问题：**「这次部署，迁移层干净吗」**。</p>
     */
    private Map<String, String> migrationFacts() {
        Map<String, String> facts = new LinkedHashMap<>();
        com.migao.admin.config.MigrationRunner runner = migrationRunner == null
                ? null : migrationRunner.getIfAvailable();
        if (runner == null) {
            // 「没跑」必须长得像「没跑」：不写 0（那会被读成「跑了且全过」）
            facts.put("migrationsFailedReal", "unknown");
            facts.put("migrationsFailedBenign", "unknown");
            facts.put("migrationsAppliedByLedger", "unknown");
            return facts;
        }
        facts.put("migrationsFailedReal", String.valueOf(runner.getLastFailedRealCount()));
        facts.put("migrationsFailedBenign", String.valueOf(runner.getLastFailedBenignCount()));
        facts.put("migrationsAppliedByLedger", String.valueOf(runner.getLastSkippedByLedger()));
        return facts;
    }

    /** 应用名（{@code spring.application.name}）；取不到 ⇒ 空串（消费方可据此判「不是这个服务」）。 */
    private String appName() {
        String name = environment.getProperty("spring.application.name", "");
        return name == null ? "" : name.trim();
    }
}
