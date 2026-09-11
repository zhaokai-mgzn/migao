package com.migao.admin.config;

// case_ids: MC-012, DF-011

import com.migao.admin.service.OssService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * OSS 未配置时的降级契约 —— 条件判定层（issue #3270）。
 *
 * 背景（CI 实测，2026-09-11）：
 * 本地/CI docker 栈（deploy/docker-compose.yml）**不注入任何 aliyun.oss.\* 变量**，
 * 而 application.yml 给它们**空字符串**默认值：
 *
 *     endpoint: ${OSS_ENDPOINT:}
 *     access-key-id: ${OSS_ACCESS_KEY_ID:}
 *     access-key-secret: ${OSS_ACCESS_KEY_SECRET:}
 *
 * 于是 `@ConditionalOnProperty(name = "aliyun.oss.endpoint")` **仍然成立**
 * （属性存在、值为 ""，该注解默认不排除空串）→ 走 ossClient() →
 * `OSSClientBuilder.build(endpoint="", accessKeyId=null, ...)` 抛：
 *
 *     InvalidCredentialsException: Access key id should not be null or empty
 *
 * → ossClient → ossService → uploadController 连锁失败 → Spring 上下文启动失败
 * → admin-api 容器 Exit(1) → 验收栈起不来（C 端评测 9/9 全 failure 的最后一环）。
 *
 * 本类锁定「凭据判定」契约；`OssEmptyConfigContextTest` 在真实 Spring 上下文里验证降级结果。
 */
class OssFallbackContractTest {

    // ======================== 凭据判定契约 ========================

    @Test
    @DisplayName("三项凭据齐备时 hasCredentials() 为 true")
    void hasCredentialsTrueWhenAllSet() {
        OssConfig cfg = new OssConfig();
        cfg.setEndpoint("oss-cn-hangzhou.aliyuncs.com");
        cfg.setAccessKeyId("LTAI5tTestKey");
        cfg.setAccessKeySecret("test-secret");

        assertThat(cfg.hasCredentials()).isTrue();
    }

    @Test
    @DisplayName("空串 endpoint（application.yml 默认形态）应判定为凭据不齐")
    void hasCredentialsFalseOnEmptyEndpoint() {
        OssConfig cfg = new OssConfig();
        cfg.setEndpoint("");
        cfg.setAccessKeyId("");
        cfg.setAccessKeySecret("");

        assertThat(cfg.hasCredentials())
                .as("application.yml 默认空串 —— 必须判为不齐，否则会建 client 并抛 "
                        + "InvalidCredentialsException 拖垮应用启动")
                .isFalse();
    }

    @Test
    @DisplayName("仅缺 access-key-id 也应判定为不齐")
    void hasCredentialsFalseWhenAccessKeyIdMissing() {
        OssConfig cfg = new OssConfig();
        cfg.setEndpoint("oss-cn-hangzhou.aliyuncs.com");
        cfg.setAccessKeyId("");
        cfg.setAccessKeySecret("test-secret");

        assertThat(cfg.hasCredentials()).isFalse();
    }

    @Test
    @DisplayName("仅缺 access-key-secret 也应判定为不齐")
    void hasCredentialsFalseWhenAccessKeySecretMissing() {
        OssConfig cfg = new OssConfig();
        cfg.setEndpoint("oss-cn-hangzhou.aliyuncs.com");
        cfg.setAccessKeyId("LTAI5tTestKey");
        cfg.setAccessKeySecret("");

        assertThat(cfg.hasCredentials()).isFalse();
    }

    @Test
    @DisplayName("纯空白字符不算有效凭据")
    void hasCredentialsFalseOnBlankValues() {
        OssConfig cfg = new OssConfig();
        cfg.setEndpoint("   ");
        cfg.setAccessKeyId("  ");
        cfg.setAccessKeySecret("\t");

        assertThat(cfg.hasCredentials()).isFalse();
    }

    // ======================== 空凭据下不建 client ========================

    @Test
    @DisplayName("ossClient() 必须挂在条件表达式上（空凭据时根本不注册）")
    void ossClientIsGuardedByExpression() throws NoSuchMethodException {
        var ann = OssConfig.class.getMethod("ossClient")
                .getAnnotation(ConditionalOnExpression.class);

        assertThat(ann)
                .as("ossClient() 必须条件化 —— 否则空凭据下会执行 OSSClientBuilder.build 并抛 "
                        + "InvalidCredentialsException（issue #3270 启动失败根因）")
                .isNotNull();
        assertThat(ann.value())
                .as("条件须判三项凭据非空白")
                .contains("aliyun.oss.endpoint")
                .contains("aliyun.oss.access-key-id")
                .contains("aliyun.oss.access-key-secret")
                .contains("trim()");
    }

    @Test
    @DisplayName("ossClient() 与 OssService 必须共用同一条件常量（防两处漂移）")
    void ossClientAndServiceShareSameCondition() throws NoSuchMethodException {
        String beanExpr = OssConfig.class.getMethod("ossClient")
                .getAnnotation(ConditionalOnExpression.class).value();
        String svcExpr = OssService.class.getAnnotation(ConditionalOnExpression.class).value();

        assertThat(svcExpr)
                .as("两处必须是同一常量引用 OssConfig.REQUIRE_OSS_CREDENTIALS —— "
                        + "手写两份表达式迟早漂移，导致「有 client 无 service」或反之")
                .isEqualTo(beanExpr)
                .isEqualTo(OssConfig.REQUIRE_OSS_CREDENTIALS);
    }

    // ======================== OssService 条件契约 ========================

    @Test
    @DisplayName("ossClient() 不得再用 @ConditionalOnProperty 判 endpoint 存在性")
    void ossClientShouldNotRelyOnPropertyExistence() throws NoSuchMethodException {
        var ann = OssConfig.class.getMethod("ossClient").getAnnotation(ConditionalOnProperty.class);

        assertThat(ann)
                .as("对空串恒成立的 @ConditionalOnProperty(name=...) 是本次故障根因，不得回归")
                .isNull();
    }

    @Test
    @DisplayName("OssService 不得再用 @ConditionalOnProperty（对空串恒成立）")
    void ossServiceShouldNotUseConditionalOnProperty() {
        var ann = OssService.class.getAnnotation(ConditionalOnProperty.class);

        assertThat(ann)
                .as("对空串恒成立的 @ConditionalOnProperty 是本次故障根因，不得回归")
                .isNull();
    }

    @Test
    @DisplayName("OssService 必须条件于「三项凭据非空白」（与 OssConfig.hasCredentials 对齐）")
    void ossServiceShouldBeConditionalOnCredentials() {
        var ann = OssService.class.getAnnotation(ConditionalOnExpression.class);

        assertThat(ann)
                .as("OssService 构造器注入 OSS，必须用条件把「无凭据」排除掉，"
                        + "否则空串时被注册 → 注入失败 → 应用启动失败")
                .isNotNull();
        String expr = ann.value();
        assertThat(expr)
                .as("条件须覆盖三项凭据且判非空白（空串 ≠ 已配置）")
                .contains("aliyun.oss.endpoint")
                .contains("aliyun.oss.access-key-id")
                .contains("aliyun.oss.access-key-secret")
                .contains("trim()");
    }
}
