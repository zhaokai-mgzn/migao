package com.migao.admin.security;

// case_ids: BM-027
import jakarta.servlet.FilterChain;
import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.util.Collections;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;

/**
 * {@link SameOriginOriginHeaderFilter} 的判据（issue #5721）。
 *
 * <p>每条都对着一个**实测过的线上事实**：</p>
 * <ul>
 *   <li>「同源请求也带 Origin」⇒ 不摘掉就会被 CORS 判成跨域（线上 403 `Invalid CORS request`，
 *       前端只看到 `Load failed`）；</li>
 *   <li>「本地开发是**真跨域**（页面 :3001 → 接口 :8080）」⇒ 摘错了会让本地 admin-web 拿不到
 *       ACAO 而全挂 —— 这是本类最危险的误伤方向，单独一条钉住。</li>
 * </ul>
 */
class SameOriginOriginHeaderFilterTest {

    private final SameOriginOriginHeaderFilter filter = new SameOriginOriginHeaderFilter();

    /** 跑一遍过滤器，返回**下游真正收到**的那个请求（不预设它一定是包装对象）。 */
    private HttpServletRequest downstreamRequest(MockHttpServletRequest request) throws Exception {
        AtomicReference<HttpServletRequest> seen = new AtomicReference<>();
        FilterChain chain = (req, res) -> seen.set((HttpServletRequest) req);
        filter.doFilter(request, new MockHttpServletResponse(), chain);
        return seen.get();
    }

    /** 线上形态：nginx 把外部视角注进来（Host/X-Forwarded-Proto），浏览器带来自己的 Origin。 */
    private MockHttpServletRequest behindNginx(String host, String origin) {
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/auth/employee/login");
        request.setServerName(host);
        request.setServerPort(8080);
        request.addHeader("Host", host);
        request.addHeader("X-Forwarded-Proto", "https");
        if (origin != null) {
            request.addHeader("Origin", origin);
        }
        return request;
    }

    @Test
    @DisplayName("同源请求（页面与接口同一个 app.migaozn.com）⇒ 摘掉 Origin，不再被判成跨域")
    void stripsSameOriginWhenBehindProxy() throws Exception {
        HttpServletRequest downstream = downstreamRequest(behindNginx("app.migaozn.com", "https://app.migaozn.com"));

        assertNull(downstream.getHeader("Origin"), "同源请求的 Origin 必须摘掉（否则 403 Invalid CORS request）");
        assertEquals(Collections.emptyList(), Collections.list(downstream.getHeaders("Origin")));
        // 按名字遍历时也不该再看见它（否则下游换个 API 读就又看见了）
        assertEquals(Collections.emptyList(),
                Collections.list(downstream.getHeaderNames()).stream()
                        .filter(name -> "origin".equalsIgnoreCase(name)).toList());
        // 其余头一字不动
        assertEquals("https", downstream.getHeader("X-Forwarded-Proto"));
    }

    @Test
    @DisplayName("默认端口等价：https://app.migaozn.com:443 与不带端口是同一个源")
    void stripsSameOriginWithExplicitDefaultPort() throws Exception {
        HttpServletRequest downstream = downstreamRequest(behindNginx("app.migaozn.com", "https://app.migaozn.com:443"));

        assertNull(downstream.getHeader("Origin"));
    }

    @Test
    @DisplayName("显式 X-Forwarded-Port 时按它判定（代理不在默认端口上也能认对）")
    void honoursForwardedPort() throws Exception {
        MockHttpServletRequest samePort = behindNginx("app.migaozn.com", "https://app.migaozn.com:8443");
        samePort.addHeader("X-Forwarded-Port", "8443");
        assertNull(downstreamRequest(samePort).getHeader("Origin"));

        MockHttpServletRequest otherPort = behindNginx("app.migaozn.com", "https://app.migaozn.com:9443");
        otherPort.addHeader("X-Forwarded-Port", "8443");
        assertEquals("https://app.migaozn.com:9443", downstreamRequest(otherPort).getHeader("Origin"),
                "端口不同的源不是同源 ⇒ Origin 必须原样保留（交回 CORS 白名单判定）");
    }

    @Test
    @DisplayName("真跨域（admin-web 的 www.migaozn.com）⇒ Origin 原样保留，白名单语义不变")
    void keepsCrossOrigin() throws Exception {
        HttpServletRequest downstream = downstreamRequest(behindNginx("api.migaozn.com", "https://www.migaozn.com"));

        assertEquals("https://www.migaozn.com", downstream.getHeader("Origin"));
    }

    @Test
    @DisplayName("🔴 本地开发（无 forwarded 头，页面 :3001 → 接口 :8080）必须**保持跨域**，否则 admin-web 本地全挂")
    void keepsLocalDevCrossPortRequest() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/auth/sms/login");
        request.setScheme("http");
        request.setServerName("localhost");
        request.setServerPort(8080);
        request.addHeader("Host", "localhost:8080");
        request.addHeader("Origin", "http://localhost:3001");

        HttpServletRequest downstream = downstreamRequest(request);

        assertEquals("http://localhost:3001", downstream.getHeader("Origin"),
                "同 host 不同 port 是**真跨域**（浏览器口径）—— 摘掉它会让本地 admin-web 拿不到 ACAO");
    }

    @Test
    @DisplayName("无 Origin（GET / curl / 服务端调用）⇒ 原样透传，连包装都不做")
    void passesThroughWhenNoOrigin() throws Exception {
        MockHttpServletRequest request = behindNginx("app.migaozn.com", null);

        assertSame(request, downstreamRequest(request));
    }

    @Test
    @DisplayName("Origin: null（沙箱 iframe）不是同源 ⇒ 原样保留，交回原有 CORS 判定")
    void keepsNullOrigin() throws Exception {
        HttpServletRequest downstream = downstreamRequest(behindNginx("app.migaozn.com", "null"));

        assertEquals("null", downstream.getHeader("Origin"));
    }

    @Test
    @DisplayName("包装只发生在被摘掉的那条路径上（跨域请求不被无谓地包装）")
    void doesNotWrapCrossOriginRequest() throws Exception {
        MockHttpServletRequest cross = behindNginx("api.migaozn.com", "https://www.migaozn.com");

        assertSame(cross, downstreamRequest(cross));
        assertNotSame(cross, downstreamRequest(behindNginx("app.migaozn.com", "https://app.migaozn.com")));
    }
}
