// case_ids: DF-010, DF-011
package com.migao.admin.service;

import com.migao.admin.config.OssConfig;
import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import com.aliyun.oss.OSS;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.stereotype.Service;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.Arrays;
import java.util.List;
import java.util.function.Function;

import static com.migao.admin.service.UploadGuardFixtures.HOSTILE_INPUT_DOC;
import static com.migao.admin.service.UploadGuardFixtures.PNG_MAGIC;
import static com.migao.admin.service.UploadGuardFixtures.hostileInputs;
import static com.migao.admin.service.UploadGuardFixtures.probe;
import static com.migao.admin.service.UploadGuardFixtures.realFile;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * {@code FileStorageService} 的**准入模板契约**与存储实现族的**同源元守卫**（issue #6208）。
 *
 * <h3>守的形态（本单的「类级」那一半）</h3>
 * <p>#6208 的根因不是「OSS 少写了一行」，而是**同一语义的护栏在实现之间分叉**：
 * {@code LocalFileStorageService#safeResolve}（422）与 {@code OssService#generateObjectKey}（零校验 ⇒ 500）。
 * 只修 OSS 那一处 = 没修 —— 下一个存储实现（第三家云 / 内存实现 / 测试替身）会照原样再分叉一次。</p>
 *
 * <p>两级判据：</p>
 * <ol>
 *   <li><b>结构面</b>：准入校验只从 {@code FileStorageService#upload} 这一个口子过
 *       （模板方法，且是**真默认实现**）；每个实现**不得**再私自声明
 *       {@code upload(MultipartFile, String)} 把它盖掉；每个实现都必须实现 {@code doUpload}
 *       且是可注入的 {@code @Service}。</li>
 *   <li><b>行为面</b>：同一份恶意语料 × 两个实现 ⇒ **拒绝语义逐条同源**
 *       （断言本身即判据，分叉即红并具名报出差在哪一条输入上）。</li>
 * </ol>
 *
 * <p>端到端副作用（不落 OSS / 不落盘）与故障机理红证由 {@code UploadInputGuardTest} 承担；
 * 护栏自身的判据由 {@code UploadGuardTest} 承担。</p>
 */
@DisplayName("FileStorageService：准入模板契约 + 存储实现护栏同源（#6208）")
class FileStorageServiceTest {

    private static final String BUCKET = "ai-customer-service-admin-dev";

    // ==================================================== 结构面：唯一口子

    @Test
    @DisplayName("upload 必须是接口默认实现（准入校验的唯一口子），不是抽象方法")
    void uploadIsADefaultMethodOnTheInterface() {
        var upload = findMethod(FileStorageService.class, "upload");

        assertThat(upload)
                .as("准入校验必须落在接口的默认实现里 —— 抽象方法会让每个实现各写一份（本单根因）")
                .isPresent();
        assertThat(upload.get().isDefault())
                .as("FileStorageService#upload 必须是 default 方法（模板方法：先校验、再 doUpload）")
                .isTrue();
        assertThat(upload.get().getDeclaringClass()).isEqualTo(FileStorageService.class);
    }

    @Test
    @DisplayName("任何实现都不得覆盖 upload（覆盖即绕过统一准入校验）")
    void noImplementorOverridesUpload() {
        for (Class<?> impl : storageImplementations()) {
            boolean overridesUpload = Arrays.stream(impl.getDeclaredMethods())
                    .anyMatch(m -> "upload".equals(m.getName()) && m.getParameterCount() == 2);

            assertThat(overridesUpload)
                    .as("%s 不得自己声明 upload(MultipartFile, String) —— 那正是 #6208 的护栏分叉形态；"
                            + "落库动作请实现 doUpload", impl.getSimpleName())
                    .isFalse();
        }
    }

    @Test
    @DisplayName("每个实现都必须实现 doUpload（具体、非抽象）")
    void everyImplementorImplementsDoUpload() {
        for (Class<?> impl : storageImplementations()) {
            var doUpload = findMethod(impl, "doUpload");
            assertThat(doUpload)
                    .as("%s 必须实现 doUpload(MultipartFile, String)", impl.getSimpleName())
                    .isPresent();
            assertThat(Modifier.isAbstract(doUpload.get().getModifiers()))
                    .as("%s 的 doUpload 必须是具体实现", impl.getSimpleName())
                    .isFalse();
        }
    }

    @Test
    @DisplayName("每个实现都是可注入的 @Service（统一口子不会拦一个永远不会被注入的实现）")
    void everyImplementorIsASpringBean() {
        for (Class<?> impl : storageImplementations()) {
            assertThat(AnnotatedElementUtils.hasAnnotation(impl, Service.class))
                    .as("%s 必须是 @Service", impl.getSimpleName())
                    .isTrue();
        }
    }

    @Test
    @DisplayName("OssService 保持可 new 的 (OSS, OssConfig) 构造（既有单测与切片上下文依赖它）")
    void ossServiceKeepsConstructorSignature() {
        assertThat(OssService.class.getConstructors())
                .as("既有的 new OssService(ossClient, ossConfig) 与 OssEmptyConfigContextTest 的上下文扫描都依赖它")
                .anySatisfy(ctor -> assertThat(ctor.getParameterTypes()).containsExactly(OSS.class, OssConfig.class));
    }

    // ==================================================== 行为面：同源（元守卫）

    @Test
    @DisplayName("元守卫：同一份恶意语料 × 两个实现 ⇒ 拒绝语义逐条同源（分叉即红并具名）")
    void rejectionSemanticsAreSharedAcrossImplementations() {
        OssService oss = newOss();
        LocalFileStorageService local = new LocalFileStorageService();

        List<String> divergences = divergentHostileInputs(
                h -> probe(() -> oss.upload(h.file().get(), h.directory())),
                h -> probe(() -> local.upload(h.file().get(), h.directory())));

        assertThat(divergences)
                .as("护栏分叉（同一语义不同实现给出不同类拒绝）—— 每条都是「改一处不修一类」的入口：%s",
                        HOSTILE_INPUT_DOC)
                .isEmpty();
    }

    @Test
    @DisplayName("判别力自证：把「私自覆盖 upload 的裸落库实现」放进对照 ⇒ 同源判据当场红 (控制组)")
    void theMetaGuardIsAbleToFailOnAForkedImplementation() {
        OssService guarded = newOss();
        FileStorageService forked = new StorageWithoutAnyGuard(newOssClient());

        List<String> divergences = divergentHostileInputs(
                h -> probe(() -> guarded.upload(h.file().get(), h.directory())),
                h -> probe(() -> forked.upload(h.file().get(), h.directory())));

        assertThat(divergences)
                .as("控制组必须判红 —— 否则「同源」只是恒绿的文案")
                .isNotEmpty();
        assertThat(divergences)
                .as("分叉必须具名到具体那条**恶意输入**（越界目录 / 穿越 / 超限 / 伪装类型）")
                .anySatisfy(d -> assertThat(d).contains("越界目录 ../../l2evil"));
    }

    // ==================================================== 夹具

    private static List<Class<?>> storageImplementations() {
        return List.of(OssService.class, LocalFileStorageService.class);
    }

    private static List<String> divergentHostileInputs(Function<UploadGuardFixtures.HostileInput,
            UploadGuardFixtures.Outcome> first,
                                                        Function<UploadGuardFixtures.HostileInput,
                                                                UploadGuardFixtures.Outcome> second) {
        List<String> out = new java.util.ArrayList<>();
        for (UploadGuardFixtures.HostileInput hostile : hostileInputs()) {
            UploadGuardFixtures.Outcome a = first.apply(hostile);
            UploadGuardFixtures.Outcome b = second.apply(hostile);
            if (!a.isSameClassAs(b)) {
                out.add(hostile.label() + " → " + a.describe() + " / " + b.describe());
            }
        }
        return out;
    }

    private static OssService newOss() {
        return new OssService(newOssClient(), newOssConfig());
    }

    private static OSS newOssClient() {
        return org.mockito.Mockito.mock(OSS.class);
    }

    private static OssConfig newOssConfig() {
        OssConfig config = new OssConfig();
        config.setEndpoint("oss-cn-hangzhou.aliyuncs.com");
        config.setAccessKeyId("test-key");
        config.setAccessKeySecret("test-secret");
        config.setUrlPrefix("https://admin.migaozn.com");
        config.setBucketName(BUCKET);
        config.setPermanentBucketName(BUCKET);
        config.setTemporaryBucketName("ai-customer-service-chat-dev");
        return config;
    }

    private static java.util.Optional<Method> findMethod(Class<?> type, String name) {
        return Arrays.stream(type.getDeclaredMethods())
                .filter(m -> name.equals(m.getName()) && m.getParameterCount() == 2)
                .findFirst();
    }

    @Test
    @DisplayName("控制组形态自证：StorageWithoutAnyGuard 确实覆盖了 upload 且会裸落库")
    void theControlGroupIsReallyAForkedImplementation() {
        assertThat(Arrays.stream(StorageWithoutAnyGuard.class.getDeclaredMethods())
                .anyMatch(m -> "upload".equals(m.getName()) && m.getParameterCount() == 2))
                .as("控制组必须真的覆盖 upload（否则它证明不了判据有判别力）")
                .isTrue();

        StorageWithoutAnyGuard forked = new StorageWithoutAnyGuard(newOssClient());
        assertThatThrownBy(() -> forked.upload(realFile("ok.png", "image/png", PNG_MAGIC), "../../l2evil"))
                .as("裸落库路径必须真的把越界目录一路带进 objectKey（= #6208 的 500 机理）")
                .isInstanceOf(IllegalArgumentException.class);
    }

    /**
     * 裸落库的「零护栏」实现（复刻 issue #6208 的 OSS 侧原貌：directory 原样拼进 objectKey）。
     *
     * <p><b>为什么不 extends OssService</b>：{@code OssEmptyConfigContextTest} 用
     * {@code FilterType.ASSIGNABLE_TYPE} 按类路径扫描 {@code OssService} 的子类 ——
     * 继承它的测试夹具会被当成 bean 拉进那个隔离上下文，把 OSS 降级契约测红（实测踩过一次）。</p>
     *
     * <p>mock 也照真 SDK 的 objectKey 契约抛（key 不得以 {@code /} 开头、不得含 {@code ../}）——
     * 默认「照单全收」会掩盖实测的 500 故障形态。</p>
     */
    private static final class StorageWithoutAnyGuard implements FileStorageService {

        private final OSS ossClient;

        StorageWithoutAnyGuard(OSS ossClient) {
            this.ossClient = ossClient;
        }

        @Override
        public UploadedFileInfo upload(org.springframework.web.multipart.MultipartFile file, String directory) {
            // 覆盖掉接口的模板方法 —— 这正是「谁都没接护栏」的那一类实现
            return doUpload(file, directory);
        }

        @Override
        public UploadedFileInfo doUpload(org.springframework.web.multipart.MultipartFile file,
                                         String normalizedDirectory) {
            // 与 OssService#generateObjectKey 同一形状；日期段写死 —— 测试替身不引入第二个时间口径
            // （业务时间只经 BusinessClock，见 BusinessClockTestSourceGuardTest）
            String name = file.getOriginalFilename() == null ? "x.png" : file.getOriginalFilename();
            String extension = name.substring(name.lastIndexOf('.'));
            String objectKey = normalizedDirectory + "/1970/01/01/"
                    + java.util.UUID.randomUUID().toString().replace("-", "") + extension;
            if (objectKey.startsWith("/") || objectKey.contains("../")) {
                throw new IllegalArgumentException("InvalidObjectKey: " + objectKey);
            }
            return UploadedFileInfo.builder().url(objectKey).build();
        }

        @Override
        public void delete(String fileUrl) {
        }

        @Override
        public String getStorageType() {
            return "oss-bare";
        }
    }
}
