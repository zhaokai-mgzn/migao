// case_ids: MC-012, DF-011
package com.migao.admin.controller;

import com.migao.admin.config.OssConfig;
import com.migao.admin.config.StorageDeploymentSelfCheck;
import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.service.FileStorageService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * {@code GET /api/version/storage} —— **上传存储形态**读面的契约（集群 P0-3，issue #9026）。
 *
 * <h3>它治什么</h3>
 * <p>多实例下「写 A 读 B ⇒ 404」的排查第一问 = 「这台实例的图片写在哪」。生产 nginx 屏蔽
 * {@code /actuator/**}，所以这个读面必须挂在 {@code /api/} 前缀下（放行名单见 {@code SecurityConfig}）。
 *
 * <h3>本文件钉什么（每条都会红）</h3>
 * <ol>
 *   <li><b>形态如实报</b>：{@code storage=local} + 单实例 ⇒ {@code multiInstance=false}/{@code replicas=1}；
 *       {@code storage=oss} + 多实例 ⇒ {@code multiInstance=true}/{@code replicas=N}；</li>
 *   <li><b>未装配 ⇒ 四项 {@code unknown}</b>，**不猜 {@code local}**（猜错会掩盖 P0-3 的真故障面）；</li>
 *   <li><b>不泄露凭据</b>：响应里不许出现 AccessKey / secret / endpoint / bucket（本端点无鉴权）；</li>
 *   <li><b>只读</b>：{@code POST} ⇒ 405。</li>
 * </ol>
 *
 * <p>装配面的判据（多实例缺 OSS ⇒ 上下文起不来 / 单实例一条 WARN / 健康端点 {@code storage=oss}）
 * 在 {@code StorageDeploymentSelfCheckTest}；两处**不重复**同一个断言。</p>
 */
@DisplayName("存储形态读面 /api/version/storage（集群 P0-3）：形态如实 / 未装配 unknown / 不泄露 / 只读")
class StorageStatusControllerTest extends BaseControllerTest {

    private static final String URL = "/api/version/storage";

    private MockMvc mvcWith(StorageDeploymentSelfCheck check) {
        return buildMockMvc(new StorageStatusController(providerOf(check)));
    }

    /** 装配一个可选的存储形态自检 bean（{@code null} ⇒ provider 取不到 ⇒ 端点报 unknown）。 */
    private static ObjectProvider<StorageDeploymentSelfCheck> providerOf(
            StorageDeploymentSelfCheck check) {
        StaticListableBeanFactory factory = new StaticListableBeanFactory();
        if (check != null) {
            factory.addBean("storageDeploymentSelfCheck", check);
        }
        return factory.getBeanProvider(StorageDeploymentSelfCheck.class);
    }

    /** 造一个存储形态自检（只读 {@code storageType()}；不跑 {@code @PostConstruct} 的启动判定）。 */
    private static StorageDeploymentSelfCheck storageCheck(
            String storageType, boolean ossConfigured, String replicas) {
        OssConfig ossConfig = new OssConfig();
        if (ossConfigured) {
            ossConfig.setEndpoint("oss-cn-hangzhou.aliyuncs.com");
            ossConfig.setAccessKeyId("test-ak-not-real");
            ossConfig.setAccessKeySecret("test-sk-not-real");
            ossConfig.setBucketName("migao-prod-uploads-probe");
        }
        FileStorageService storage = new FileStorageService() {
            @Override
            public UploadedFileInfo doUpload(MultipartFile file, String directory) {
                throw new UnsupportedOperationException("读面不落盘");
            }

            @Override
            public void delete(String fileUrl) {
                // 读面不删文件
            }

            @Override
            public String getStorageType() {
                return storageType;
            }
        };
        return new StorageDeploymentSelfCheck(storage, ossConfig, replicas);
    }

    @Test
    @DisplayName("① 本地盘 + 单实例 ⇒ storage=local / multiInstance=false / replicas=1 / ossConfigured=false")
    void reportsLocalForSingleInstance() throws Exception {
        mvcWith(storageCheck("local", false, "1"))
                .perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.storage").value("local"))
                .andExpect(jsonPath("$.multiInstance").value("false"))
                .andExpect(jsonPath("$.replicas").value("1"))
                .andExpect(jsonPath("$.ossConfigured").value("false"));
    }

    @Test
    @DisplayName("② OSS + 多实例 ⇒ storage=oss / multiInstance=true（运维据此判「可上多实例」）")
    void reportsOssForMultiInstance() throws Exception {
        mvcWith(storageCheck("oss", true, "3"))
                .perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.storage").value("oss"))
                .andExpect(jsonPath("$.multiInstance").value("true"))
                .andExpect(jsonPath("$.replicas").value("3"))
                .andExpect(jsonPath("$.ossConfigured").value("true"));
    }

    @Test
    @DisplayName("③ 未装配自检 bean ⇒ 四项都报 unknown（不猜 local —— 猜错会掩盖 P0-3 真故障）")
    void reportsUnknownWhenNotWired() throws Exception {
        mvcWith(null)
                .perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.storage").value("unknown"))
                .andExpect(jsonPath("$.multiInstance").value("unknown"))
                .andExpect(jsonPath("$.replicas").value("unknown"))
                .andExpect(jsonPath("$.ossConfigured").value("unknown"));
    }

    @Test
    @DisplayName("④ 字段面恰好 4 个、全是字符串：加字段就是泄露面变了（本判据会红）")
    void responseHasExactlyTheFourWhitelistedKeys() throws Exception {
        MvcResult result = mvcWith(storageCheck("oss", true, "2"))
                .perform(get(URL))
                .andExpect(status().isOk())
                .andReturn();
        @SuppressWarnings("unchecked")
        java.util.Map<String, Object> body = objectMapper.readValue(
                result.getResponse().getContentAsString(), java.util.LinkedHashMap.class);

        assertThat(body.keySet())
                .as("字段白名单 = storage/multiInstance/replicas/ossConfigured；加了新字段必须重新过一遍「会不会泄露」")
                .containsExactly("storage", "multiInstance", "replicas", "ossConfigured");
        assertThat(body.values()).allSatisfy(v -> assertThat(v).isInstanceOf(String.class));
    }

    @Test
    @DisplayName("⑤ 不泄露凭据：响应里没有 AccessKey / secret / endpoint / bucket")
    void doesNotLeakCredentials() throws Exception {
        MvcResult result = mvcWith(storageCheck("oss", true, "2"))
                .perform(get(URL))
                .andExpect(status().isOk())
                .andReturn();
        String body = result.getResponse().getContentAsString();

        // 显眼标记来自 storageCheck(...) 里填的 endpoint / AK / secret / bucket
        for (String forbidden : List.of("test-ak-not-real", "test-sk-not-real",
                "oss-cn-hangzhou", "migao-prod-uploads-probe")) {
            assertThat(body)
                    .as("存储形态读面是无鉴权面：出现 %s 形态的内容 ⇒ 泄露面超了", forbidden)
                    .doesNotContain(forbidden);
        }
    }

    @Test
    @DisplayName("⑥ 只读：POST ⇒ 405（读面不给写面）")
    void isReadOnly() throws Exception {
        mvcWith(storageCheck("local", false, "1"))
                .perform(post(URL).contentType(APPLICATION_JSON).content("{}"))
                .andExpect(status().isMethodNotAllowed());
    }
}
