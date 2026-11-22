// case_ids: MC-012, DF-011
package com.migao.admin.config;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.migao.admin.service.FileStorageService;
import com.migao.admin.service.LocalFileStorageService;
import com.migao.admin.service.OssService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.boot.actuate.autoconfigure.health.HealthEndpointAutoConfiguration;
import org.springframework.boot.actuate.health.CompositeHealth;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthComponent;
import org.springframework.boot.actuate.health.HealthEndpoint;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.assertj.AssertableApplicationContext;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.FilterType;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 上传存储形态的**启动期护栏**（集群 P0-3；缺陷背景 = `docs/deployment/cluster-readiness-audit.md` 的 P0-3）。
 *
 * <h3>缺陷（修前）</h3>
 * <p>{@code LocalFileStorageService} 把文件写本地磁盘，多实例下「写 A 读 B ⇒ 404」，
 * 而且**启动期没有任何提示** —— 故障面要到用户点开图片才出现，看起来像「文件丢了」。</p>
 *
 * <h3>本文件钉什么（每条都会红）</h3>
 * <ol>
 *   <li><b>显式多实例 + 缺 OSS ⇒ 上下文启动失败</b>，报文命中关键词
 *       （{@code 多实例部署必须配置 OSS} / {@code MIGAO_REPLICAS} / 缺哪个凭据 / 文档路径）；</li>
 *   <li><b>单实例（默认） + 缺 OSS ⇒ 维持现状启动</b>，并且**恰好一条 WARN** 说明「仅限单实例」
 *       —— 既不许拒绝启动（单实例是合法形态），也不许一声不响；</li>
 *   <li><b>OSS 齐备 ⇒ 启动成功且读数 {@code storage=oss}</b>（{@code /actuator/health} 的
 *       {@code uploadStorage} 条目；同一读数另有 {@code /api/version/storage}，见
 *       {@code VersionControllerTest}）；</li>
 *   <li><b>实例数配错不许当单实例放行</b>（非整数 / {@code <1} ⇒ fail-closed）：判不出来 = 不许启动。</li>
 * </ol>
 *
 * <p>为什么用 {@link ApplicationContextRunner} 而不是起整机：本判据要的是「**Spring 上下文真的起不来**」，
 * 而不是「某个方法返回了 false」—— 但整机需要 DB/Redis；切片只加载 OSS/存储/自检这几个 bean，
 * 与既有 {@code OssEmptyConfigContextTest} 同一手法（同族判据不另立一套装配方式）。</p>
 */
@DisplayName("上传存储启动自检（集群 P0-3）：多实例缺 OSS fail-close / 单实例 WARN / OSS ⇒ storage=oss")
class StorageDeploymentSelfCheckTest {

    /** 只扫存储相关 bean，避免把 Mapper/Controller 等无关依赖拉进上下文。 */
    @Configuration
    @ComponentScan(
            basePackageClasses = {OssConfig.class, StorageDeploymentSelfCheck.class,
                    OssService.class, LocalFileStorageService.class},
            useDefaultFilters = false,
            includeFilters = @ComponentScan.Filter(
                    type = FilterType.ASSIGNABLE_TYPE,
                    classes = {OssConfig.class, OssService.class, LocalFileStorageService.class,
                            StorageDeploymentSelfCheck.class, StorageHealthIndicator.class}))
    static class StorageSliceConfig {
    }

    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void attachLogCapture() {
        appender = new ListAppender<>();
        appender.start();
        ((ch.qos.logback.classic.Logger) LoggerFactory.getLogger(StorageDeploymentSelfCheck.class))
                .addAppender(appender);
    }

    @AfterEach
    void detachLogCapture() {
        ((ch.qos.logback.classic.Logger) LoggerFactory.getLogger(StorageDeploymentSelfCheck.class))
                .detachAppender(appender);
    }

    private ApplicationContextRunner runner() {
        return new ApplicationContextRunner()
                .withUserConfiguration(StorageSliceConfig.class)
                // 健康端点走真实 actuator 自动配置：判据要说的是「/actuator/health 里读得到」，
                // 不是「某个方法返回了对的字符串」
                .withConfiguration(AutoConfigurations.of(HealthEndpointAutoConfiguration.class))
                .withPropertyValues(
                        "management.endpoints.web.exposure.include=health",
                        "management.endpoint.health.show-details=always");
    }

    private ApplicationContextRunner noOss(ApplicationContextRunner runner) {
        return runner.withPropertyValues(
                "aliyun.oss.endpoint=",
                "aliyun.oss.access-key-id=",
                "aliyun.oss.access-key-secret=");
    }

    private ApplicationContextRunner withOss(ApplicationContextRunner runner) {
        return runner.withPropertyValues(
                "aliyun.oss.endpoint=oss-cn-hangzhou.aliyuncs.com",
                "aliyun.oss.access-key-id=test-ak-not-real",
                "aliyun.oss.access-key-secret=test-sk-not-real",
                "aliyun.oss.bucket-name=migao-prod-uploads-test",
                "aliyun.oss.permanent-bucket-name=migao-prod-uploads-test",
                "aliyun.oss.temporary-bucket-name=migao-prod-uploads-test");
    }

    // ───────────────────────── ① 多实例 + 缺 OSS ⇒ fail-close ─────────────────────────

    @Test
    @DisplayName("① 显式多实例（MIGAO_REPLICAS=2）+ 缺 OSS ⇒ 上下文**启动失败**，报文给可行动指引")
    void multiInstanceWithoutOssFailsClosed() {
        noOss(runner()).withPropertyValues("MIGAO_REPLICAS=2").run(ctx -> {
            assertThat(ctx)
                    .as("多实例 + 本地盘 = 「写 A 读 B 必 404」，必须在启动期拒绝（P0-3）")
                    .hasFailed();
            String failure = failureText(ctx.getStartupFailure());
            assertThat(failure)
                    .as("报错必须点名「多实例部署必须配置 OSS」+ 显式判据 + 缺哪几项 + 文档入口")
                    .contains("多实例部署必须配置 OSS")
                    .contains("MIGAO_REPLICAS=2")
                    .contains("OSS_ENDPOINT")
                    .contains(StorageDeploymentSelfCheck.DOC);
        });
    }

    @Test
    @DisplayName("①′ 只缺 endpoint（另两项在）⇒ 报错只点名缺的那一项（可行动）")
    void missingCredentialIsNamedInFailure() {
        runner().withPropertyValues(
                        "MIGAO_REPLICAS=3",
                        "aliyun.oss.endpoint=",
                        "aliyun.oss.access-key-id=ak-present",
                        "aliyun.oss.access-key-secret=sk-present")
                .run(ctx -> {
                    assertThat(ctx).hasFailed();
                    String failure = failureText(ctx.getStartupFailure());
                    assertThat(failure)
                            .as("「缺」清单必须**只**点名真缺的那项（已配齐的两项若混进来，指引会把运维带偏）")
                            .contains("（缺 OSS_ENDPOINT）")
                            .doesNotContain("（缺 OSS_ENDPOINT / ");
                });
    }

    // ───────────────────────── ② 单实例 + 缺 OSS ⇒ 启动 + 一条 WARN ─────────────────────────

    @Test
    @DisplayName("② 单实例（默认，不设 MIGAO_REPLICAS）+ 缺 OSS ⇒ 正常启动，仅 WARN 一行「仅限单实例」")
    void singleInstanceWithoutOssStartsWithOneWarning() {
        noOss(runner()).run(ctx -> {
            assertThat(ctx)
                    .as("单实例 + 本地盘是合法形态 ⇒ 不许因为本护栏拒绝启动")
                    .hasNotFailed();
            assertThat(ctx.getBean(FileStorageService.class))
                    .isInstanceOf(LocalFileStorageService.class);
            assertThat(uploadStorageHealth(ctx).getDetails())
                    .as("健康端点必须如实报 local（运维据此知道不能开第二个实例）")
                    .containsEntry("storage", "local")
                    .containsEntry("multiInstance", false)
                    .containsEntry("replicas", 1)
                    .containsEntry("ossConfigured", false);
        });

        List<ILoggingEvent> warns = appender.list.stream()
                .filter(e -> e.getLevel() == Level.WARN)
                .toList();
        assertThat(warns)
                .as("单实例 + 本地盘必须**恰好一条** WARN（多一条是噪音，零条就是本次要修的缺陷）")
                .hasSize(1);
        assertThat(warns.get(0).getFormattedMessage())
                .contains("仅限单实例")
                .contains("MIGAO_REPLICAS")
                .contains(StorageDeploymentSelfCheck.DOC);
    }

    @Test
    @DisplayName("②′ 显式 MIGAO_REPLICAS=1 + 缺 OSS ⇒ 与默认同形（不算多实例）")
    void explicitSingleReplicaIsStillSingleInstance() {
        noOss(runner()).withPropertyValues("MIGAO_REPLICAS=1").run(ctx -> {
            assertThat(ctx).hasNotFailed();
            assertThat(uploadStorageHealth(ctx).getDetails()).containsEntry("multiInstance", false);
        });
    }

    // ───────────────────────── ③ OSS 齐备 ⇒ storage=oss ─────────────────────────

    @Test
    @DisplayName("③ OSS 齐备 ⇒ 启动成功，健康端点 uploadStorage 报 storage=oss")
    void ossConfiguredReportsOss() {
        withOss(runner()).withPropertyValues("MIGAO_REPLICAS=2").run(ctx -> {
            assertThat(ctx).hasNotFailed();
            assertThat(ctx.getBean(FileStorageService.class)).isInstanceOf(OssService.class);
            assertThat(uploadStorageHealth(ctx).getDetails())
                    .as("多实例 + OSS ⇒ 唯一允许上多实例的形态")
                    .containsEntry("storage", "oss")
                    .containsEntry("multiInstance", true)
                    .containsEntry("replicas", 2)
                    .containsEntry("ossConfigured", true);
            assertThat(appender.list.stream().map(ILoggingEvent::getLevel))
                    .as("OSS 形态不得打「仅限单实例」那条 WARN")
                    .doesNotContain(Level.WARN);
        });
    }

    @Test
    @DisplayName("③′ 存储形态读数不泄露凭据（细节里只有 4 个非敏感字段）")
    void healthDetailsDoNotLeakCredentials() {
        withOss(runner()).run(ctx -> {
            Health health = uploadStorageHealth(ctx);
            assertThat(health.getDetails())
                    .as("健康细节的字段面必须恰好是判定所需的 4 项")
                    .containsOnlyKeys("storage", "multiInstance", "replicas", "ossConfigured");
            String rendered = health.getDetails().toString();
            assertThat(rendered)
                    .as("凭据 / endpoint / bucket 一个都不许进健康面（/actuator 与 /api 都无鉴权）")
                    .doesNotContain("test-ak-not-real")
                    .doesNotContain("test-sk-not-real")
                    .doesNotContain("oss-cn-hangzhou")
                    .doesNotContain("migao-prod-uploads-test");
        });
    }

    // ───────────────────────── ④ 判不出来 = 不许启动 ─────────────────────────

    @Test
    @DisplayName("④ MIGAO_REPLICAS 非整数 ⇒ fail-closed（判不出来不许当单实例放行）")
    void nonNumericReplicasFailsClosed() {
        noOss(runner()).withPropertyValues("MIGAO_REPLICAS=two").run(ctx -> {
            assertThat(ctx).hasFailed();
            assertThat(failureText(ctx.getStartupFailure()))
                    .contains("MIGAO_REPLICAS=two")
                    .contains("必须是 >=1 的整数");
        });
    }

    @Test
    @DisplayName("④′ MIGAO_REPLICAS=0 ⇒ fail-closed（0 是配错，不是「没有实例」）")
    void nonPositiveReplicasFailsClosed() {
        withOss(runner()).withPropertyValues("MIGAO_REPLICAS=0").run(ctx -> {
            assertThat(ctx).hasFailed();
            assertThat(failureText(ctx.getStartupFailure()))
                    .contains("MIGAO_REPLICAS=0")
                    .contains("必须 >=1");
        });
    }

    /**
     * 把启动失败的**整条异常链**拼成文本。
     *
     * <p>Spring 6 的 {@code BeanCreationException#getMessage()} **不再**附带
     * {@code nested exception is ...} ⇒ 只看顶层 message 会把「我们的报文」判成「没出现」
     * （实测：{@code Failed to instantiate ... Constructor threw exception}）。判据要看的是
     * 「应用启动失败时人看到的报错文本」，所以把 cause 链一起拼起来。</p>
     */
    private static String failureText(Throwable failure) {
        StringBuilder sb = new StringBuilder();
        for (Throwable t = failure; t != null; t = t.getCause()) {
            if (t.getMessage() != null) {
                sb.append(t.getMessage()).append(" | ");
            }
            if (t.getCause() == t) {
                break;
            }
        }
        return sb.toString();
    }

    // ───────────────────────── 夹具 ─────────────────────────

    /**
     * 从**真实** {@link HealthEndpoint} 里取 {@code uploadStorage} 条目。
     * 聚合端点没这条 ⇒ 断言直接红（不是「读不到就当通过」）。
     */
    private static Health uploadStorageHealth(AssertableApplicationContext ctx) {
        HealthComponent component = ctx.getBean(HealthEndpoint.class).health();
        assertThat(component)
                .as("show-details=always 时 /actuator/health 必须是聚合形态")
                .isInstanceOf(CompositeHealth.class);
        HealthComponent entry = ((CompositeHealth) component).getComponents().get("uploadStorage");
        assertThat(entry)
                .as("健康端点里必须有 uploadStorage 条目（bean 名 = 健康面的键名）")
                .isInstanceOf(Health.class);
        return (Health) entry;
    }
}
