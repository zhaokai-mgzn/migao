package com.migao.admin.security;

// case_ids=[DF-016]

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.AbstractResource;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;
import org.springframework.core.io.UrlResource;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.function.Function;
import java.util.jar.JarEntry;
import java.util.jar.JarOutputStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * classpath 密钥加载必须**从打包后的 jar 里读得到**（issue #8976 ②-a）。
 *
 * <h2>病（2026-11-21 生产实测）</h2>
 * admin-api 的 RSA 密钥有两条取值路：`JWT_*_PEM`（PEM 内容）与 `jwt.private-key/public-key`
 * （资源路径，默认 `classpath:rsa/*.pem`）。生产把 `JWT_*` 环境变量去掉、想退回 classpath 兜底时，
 * 启动直接报「JWT RSA 密钥加载失败」——镜像跑的是 Spring Boot 可执行 jar，资源在
 * {@code jar:nested:/app/app.jar/!BOOT-INF/classes/rsa/public.pem} 这类**嵌套 URL** 下：
 * 那里没有「文件」可指（`getFile()` 必失败），`Resource#exists()` 也不是「内容读不读得到」的判据。
 * ⇒ **兜底本身是坏的**，实际只剩 `file:` 一条路（fail-closed 是好的，但兜底不该坏）。
 *
 * <h2>本文件判什么（每条都能单独变红）</h2>
 * <ol>
 *   <li><b>嵌套 jar 形态</b>：资源 {@code exists()=false}、{@code getFile()} 抛 ⇒ 密钥仍必须加载成功
 *       （判据落在「签出来的 token 能验回去」上，不只看字段非空）；</li>
 *   <li><b>真 jar</b>：用 {@link JarOutputStream} 打一个含 {@code rsa/*.pem} 的 jar，用
 *       {@code jar:file:…!/rsa/public.pem} 形式的 {@link UrlResource} 加载 ⇒ 必须成功
 *       （用例自证：同一个 URL 的 {@code getFile()} 必须抛 —— 否则这条用例退化成「文件路径」）；
 *       {</li>
 *   <li><b>不依赖 exists()</b>：Mockito 桩 {@code exists()=false} + 可读流 ⇒ 加载成功，且
 *       {@code verify(never()).exists()}（有人把 {@code if (resource.exists())} 加回来 ⇒ 当场红）；</li>
 *   <li><b>fail-closed 没丢</b>：流读不到 ⇒ {@code IllegalStateException}（**不许**静默回退 HS256 /
 *       静默跳过）；</li>
 *   <li><b>负控</b>：内容不是 PEM ⇒ 同样 fail-fast（说明上一条的绿不是「什么都放行」）。</li>
 * </ol>
 *
 * <h2>本机读数（本机无 maven ⇒ 用等价的直调 runner，2026-11-21，可复算）</h2>
 * 修后 **5/5 PASS**；把被测实现换回 `origin/main` 那一份（先问 `Resource#exists()`）⇒
 * {@code loadsKeysFromStreamOnlyResource} / {@code doesNotDependOnResourceExists} **当场红**（2 failed）
 * —— 即这两条不是空断言（红证读数逐字：`JWT RSA 密钥加载失败`）。
 * ⚠️ 编译期还抓到一条：`ResourceLoader` **不是函数接口**（`getResource` + `getClassLoader` 都抽象），
 * 用 lambda 会直接编不过 ⇒ 本文件用显式匿名实现。
 *
 * <h2>边界（照实登记）</h2>
 * 不启 Spring 容器、不真起容器、不打包 maven 产物：判据在 JVM 内构造「嵌套 jar / 真 jar」两种资源形态
 * ——它证明的是<strong>加载器只靠流</strong>，不证明某个具体镜像里的 jar 布局。打包面另由
 * {@code tests/unit_ci_workflows/test_swas_jwt_same_source.py} 静态钉住（`rsa/*.pem` 必须随
 * `src/main/resources` 进 jar，且不得被 pom 的资源过滤排除）。
 */
class JwtTokenProviderClasspathResourceTest {

    private static final String PUBLIC_LOCATION = "classpath:rsa/public.pem";
    private static final String PRIVATE_LOCATION = "classpath:rsa/private.pem";

    private static String classpathText(String path) throws IOException {
        try (InputStream in = JwtTokenProviderClasspathResourceTest.class.getResourceAsStream(path)) {
            assertThat(in).as("测试用 classpath 资源应存在: %s", path).isNotNull();
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    /** 按 `@Value` 注入后的样子装好 provider 并走 `init()`（= 生产启动路径）。 */
    private static JwtTokenProvider providerFor(ResourceLoader loader) {
        JwtTokenProvider provider = new JwtTokenProvider(loader);
        ReflectionTestUtils.setField(provider, "privateKeyPath", PRIVATE_LOCATION);
        ReflectionTestUtils.setField(provider, "publicKeyPath", PUBLIC_LOCATION);
        ReflectionTestUtils.setField(provider, "accessTokenExpiration", 7200L);
        ReflectionTestUtils.setField(provider, "refreshTokenExpiration", 2592000L);
        provider.init();
        return provider;
    }

    /** 只可读流、不可当文件看的资源（= 嵌套 jar 里那一类）。 */
    private static Resource streamOnly(String content) {
        return new AbstractResource() {
            @Override
            public String getDescription() {
                return "stream-only resource (nested jar shape)";
            }

            @Override
            public boolean exists() {
                return false;
            }

            @Override
            public InputStream getInputStream() {
                return new ByteArrayInputStream(content.getBytes(StandardCharsets.UTF_8));
            }

            @Override
            public File getFile() {
                throw new UnsupportedOperationException("nested jar 里没有文件可指");
            }
        };
    }

    /** `ResourceLoader` **不是**函数接口（`getResource` + `getClassLoader` 都是抽象的）⇒ 显式实现。 */
    private static ResourceLoader loader(Function<String, Resource> byLocation) {
        return new ResourceLoader() {
            @Override
            public Resource getResource(String location) {
                return byLocation.apply(location);
            }

            @Override
            public ClassLoader getClassLoader() {
                return JwtTokenProviderClasspathResourceTest.class.getClassLoader();
            }
        };
    }

    private static ResourceLoader fixed(String publicPem, String privatePem) {
        return loader(location -> PUBLIC_LOCATION.equals(location) ? streamOnly(publicPem) : streamOnly(privatePem));
    }

    @Test
    @DisplayName("嵌套 jar 形态（exists()=false / 无 File）也能加载 classpath 密钥并完成签名验签")
    void loadsKeysFromStreamOnlyResource() throws Exception {
        JwtTokenProvider provider = providerFor(fixed(classpathText("/rsa/public.pem"), classpathText("/rsa/private.pem")));

        String token = provider.generateAccessToken("user-8976", 1L, "tester", List.of("admin"));

        assertThat(token).isNotBlank();
        assertThat(provider.validateToken(token)).isTrue();
    }

    @Test
    @DisplayName("打包后的 jar（jar:…!/rsa/*.pem）里读 classpath 资源必须成功")
    void loadsKeysFromPackagedJar(@TempDir Path tempDir) throws Exception {
        String publicPem = classpathText("/rsa/public.pem");
        String privatePem = classpathText("/rsa/private.pem");
        Path jar = tempDir.resolve("app.jar");
        try (JarOutputStream out = new JarOutputStream(Files.newOutputStream(jar))) {
            for (String[] entry : new String[][]{{"rsa/public.pem", publicPem}, {"rsa/private.pem", privatePem}}) {
                out.putNextEntry(new JarEntry(entry[0]));
                out.write(entry[1].getBytes(StandardCharsets.UTF_8));
                out.closeEntry();
            }
        }

        ResourceLoader jarLoader = loader(location -> {
            try {
                return new UrlResource("jar:" + jar.toUri() + "!/" + location.substring("classpath:".length()));
            } catch (IOException e) {
                throw new IllegalStateException(e);
            }
        });

        // 用例自证：这是**真 jar**、不是文件路径（否则本用例退化成「文件能读」，没有判别力）
        Resource packed = jarLoader.getResource(PUBLIC_LOCATION);
        assertThatThrownBy(packed::getFile)
                .as("jar: URL 的 getFile() 必须失败 —— 否则本用例证明不了「嵌套/归档形态」")
                .isInstanceOf(IOException.class);

        JwtTokenProvider provider = providerFor(jarLoader);
        String token = provider.generateAccessToken("user-8976", 1L, "tester", List.of("admin"));

        assertThat(provider.validateToken(token)).isTrue();
    }

    @Test
    @DisplayName("不得再依赖 Resource#exists()（加回 exists() 闸门 ⇒ 嵌套 jar 场景当场红）")
    void doesNotDependOnResourceExists() throws Exception {
        Resource publicResource = mock(Resource.class);
        Resource privateResource = mock(Resource.class);
        when(publicResource.exists()).thenReturn(false);
        when(privateResource.exists()).thenReturn(false);
        when(publicResource.getInputStream())
                .thenReturn(new ByteArrayInputStream(classpathText("/rsa/public.pem").getBytes(StandardCharsets.UTF_8)));
        when(privateResource.getInputStream())
                .thenReturn(new ByteArrayInputStream(classpathText("/rsa/private.pem").getBytes(StandardCharsets.UTF_8)));
        ResourceLoader mockLoader = mock(ResourceLoader.class);
        when(mockLoader.getResource(PUBLIC_LOCATION)).thenReturn(publicResource);
        when(mockLoader.getResource(PRIVATE_LOCATION)).thenReturn(privateResource);

        JwtTokenProvider provider = providerFor(mockLoader);

        assertThat(provider.validateToken(provider.generateAccessToken("u", 1L, "t", List.of("admin")))).isTrue();
        verify(publicResource, never()).exists();
        verify(privateResource, never()).exists();
    }

    @Test
    @DisplayName("流读不到 ⇒ fail-fast（IllegalStateException），不得静默降级")
    void failsFastWhenResourceUnreadable() {
        Resource unreadable = new AbstractResource() {
            @Override
            public String getDescription() {
                return "unreadable resource";
            }

            @Override
            public InputStream getInputStream() throws IOException {
                throw new FileNotFoundException("BOOT-INF/classes/rsa/public.pem (No such file or directory)");
            }
        };

        assertThatThrownBy(() -> providerFor(loader(location -> unreadable)))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("JWT RSA");
    }

    @Test
    @DisplayName("负控：资源在、但不是 PEM ⇒ 同样 fail-fast（说明上一条不是「什么都放行」）")
    void failsFastOnNonPemContent() {
        assertThatThrownBy(() -> providerFor(fixed("not a pem", "not a pem")))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("JWT RSA");
    }
}
