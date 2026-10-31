package com.migao.admin.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.security.ClientErrorRateLimiter;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * 浏览器端错误上报端点（issue #8203 · P0-03 的服务端一半）。
 *
 * <h3>为什么需要它</h3>
 * <p>改前四端**零前端错误上报**（{@code grep -rn "Sentry|window.onerror|unhandledrejection" frontend/*}{@code /src}
 * ⇒ 0 命中）⇒ 线上白屏「发生过多少次、在哪一页」**不可知**（不可判定 ≠ 通过）。admin-web 的
 * {@code src/lib/clientErrorReporter.ts} 把错误归一成 8 个字段发到这里；本类**只落 SLF4J 日志**
 * —— 不建表、不落库、不进 Redis、不接外部 APM（那是后续单子的事）。</p>
 *
 * <h3>公开面（{@code permitAll}）与三道闸</h3>
 * <p>它必须在**未登录**时也可用（登录页崩了也要能上报），因此挂在 {@code SecurityConfig} 的放行名单里。
 * 公开面 = 攻击面，所以三道闸**缺一不可**：</p>
 * <ol>
 *   <li><b>体积上限</b>（{@link #MAX_BODY_BYTES} = 8 KiB）：先看 {@code Content-Length}，再**有界读取**
 *       （{@link #readBounded} 最多读 {@code MAX+1} 字节）⇒ 没有声明长度的分块请求也挡得住。
 *       超限 ⇒ {@code 413}。</li>
 *   <li><b>限流</b>（{@link ClientErrorRateLimiter}）：每 IP 每分钟 {@code 30} 条 + 全局限流 ⇒ {@code 429}。
 *       刻意**不用** Redis 计数（{@code RegistrationService} 的形态）：本端点的价值恰恰在「故障时」——
 *       Redis 挂了还要不要丢错误？答案是不丢（进程内计数，实例重启清零，可接受）。</li>
 *   <li><b>字段校验</b>：白名单 8 字段 + 长度上限 + {@code source} 枚举 + {@code path} 必须是
 *       <b>不含 query / hash 的 pathname</b>（含 {@code ?}/{@code #} 直接 {@code 400} —— 那说明客户端
 *       把 token 带出来了，宁可拒收也不记进日志）。</li>
 * </ol>
 *
 * <h3>隐私边界（**硬约束**）</h3>
 * <p>采集侧（前端）就不取 PIN / token / 请求体；本类落日志前再做一次<b>模式化涂抹</b>
 * （{@link #sanitize}：JWT、{@code token=}/{@code pin=}/{@code phone=} 键值、{@code Bearer}、11 位手机号、
 * URL query 串）—— 因为第三方库抛出的 message 可能自带这些东西。判据 =
 * {@code ClientErrorControllerTest#logLineCarriesNoSecrets}（喂一杯显眼标记，断言日志里**不出现**）。</p>
 *
 * <h3>三态语义</h3>
 * <ul>
 *   <li>{@code 204} —— 收下并已落日志（<b>无响应体</b>，客户端不需要看）；</li>
 *   <li>{@code 4xx} —— 非法请求（{@code 400} 字段/JSON、{@code 413} 超体积、{@code 415} 非 JSON、
 *       {@code 429} 限流）。<b>4xx 不写业务日志</b>（否则公开面等于一个日志放大器），
 *       只在 {@code DEBUG} 留一行归因；</li>
 *   <li>不返回 {@code 5xx}：本端点自己出错不该污染服务端的 5xx 读数。</li>
 * </ul>
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class ClientErrorController {

    /** 请求体上限（8 KiB）。**与前端 8 个字段的上限同量级**：正常一单 ≈ 1.3 KiB，留足栈摘要余量。 */
    public static final int MAX_BODY_BYTES = 8 * 1024;

    /** 字段上限 —— **与 `src/lib/clientErrorReporter.ts` 的 `MAX_*` 同值**（分叉 ⇒ 前端报上来的会被 400 掉）。 */
    public static final int MAX_PATH_LENGTH = 200;
    public static final int MAX_NAME_LENGTH = 80;
    public static final int MAX_MESSAGE_LENGTH = 300;
    public static final int MAX_STACK_LENGTH = 800;
    public static final int MAX_DIGEST_LENGTH = 64;
    public static final int MAX_AT_LENGTH = 40;
    public static final int MAX_UA_LENGTH = 200;

    /** 允许的上报来源（前端 `ClientErrorSource` 的镜像）。加新值必须两边同批改。 */
    public static final List<String> ALLOWED_SOURCES =
            List.of("error-boundary", "window.onerror", "unhandledrejection");

    /** 日志里允许出现的最长单字段（超长已在上游截断，这里再兜一层；防日志被单个字段撑爆）。 */
    private static final int MAX_LOG_FIELD = 512;

    // ── 涂抹表（与前端 `REDACTIONS` **同序、同形态**：JWT → Bearer → 键值 → 手机号 → query 串）────
    private static final Pattern JWT = Pattern.compile("\\beyJ[A-Za-z0-9_-]{4,}\\.[A-Za-z0-9_-]{4,}\\.[A-Za-z0-9_-]{4,}\\b");
    private static final Pattern BEARER = Pattern.compile("\\bBearer\\s+[A-Za-z0-9._~+/=-]+", Pattern.CASE_INSENSITIVE);
    private static final Pattern KV_SECRET = Pattern.compile(
            "\\b(access_token|refresh_token|token|password|passwd|pin|phone|mobile|secret|code)=[^&\\s\"',}]*",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern CN_MOBILE = Pattern.compile("\\b1[3-9]\\d{9}\\b");
    private static final Pattern URL_QUERY = Pattern.compile("(/[A-Za-z0-9._~%/-]*)\\?[^\\s\"',}]*");

    private final ClientErrorRateLimiter rateLimiter;
    private final ObjectMapper objectMapper;

    /**
     * {@code POST /api/client-errors} —— 公开、只读语义（**只写日志**）。
     *
     * <p>刻意**不用** {@code @RequestBody}：那样 body 会先被 Jackson 整段读进内存，{@link #MAX_BODY_BYTES}
     * 就只是「事后检查」。这里自己按上限读字节 ⇒ 上限是**真的**。</p>
     */
    @PostMapping("/api/client-errors")
    public ResponseEntity<Void> report(HttpServletRequest request) throws IOException {
        long declared = request.getContentLengthLong();
        if (declared > MAX_BODY_BYTES) {
            return ResponseEntity.status(HttpStatus.PAYLOAD_TOO_LARGE).build();
        }
        if (!isAcceptableContentType(request.getContentType())) {
            return ResponseEntity.status(HttpStatus.UNSUPPORTED_MEDIA_TYPE).build();
        }
        String clientIp = resolveClientIp(request);
        if (!rateLimiter.tryAcquire(clientIp)) {
            return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS).build();
        }

        byte[] body = readBounded(request.getInputStream());
        if (body == null) {
            return ResponseEntity.status(HttpStatus.PAYLOAD_TOO_LARGE).build();
        }
        if (body.length == 0) {
            return ResponseEntity.badRequest().build();
        }

        ClientErrorRequest payload;
        try {
            payload = objectMapper.readValue(new String(body, StandardCharsets.UTF_8), ClientErrorRequest.class);
        } catch (Exception e) {
            // 非法 JSON 不打堆栈（公开面会被刷爆）；DEBUG 一行归因即可
            log.debug("CLIENT_ERROR 拒收：body 不是合法 JSON（{} 字节）", body.length);
            return ResponseEntity.badRequest().build();
        }
        if (payload == null) {
            return ResponseEntity.badRequest().build();
        }
        String invalidField = firstInvalidField(payload);
        if (invalidField != null) {
            log.debug("CLIENT_ERROR 拒收：字段不合法 field={}", invalidField);
            return ResponseEntity.badRequest().build();
        }

        // 唯一写面：一行结构化日志（字段白名单 + 逐个涂抹 + 截断）
        log.warn("CLIENT_ERROR source={} path={} name={} message={} digest={} at={} ua={} stack={}",
                sanitize(payload.source(), MAX_NAME_LENGTH),
                sanitize(payload.path(), MAX_PATH_LENGTH),
                sanitize(payload.name(), MAX_NAME_LENGTH),
                sanitize(payload.message(), MAX_MESSAGE_LENGTH),
                sanitize(payload.digest(), MAX_DIGEST_LENGTH),
                sanitize(payload.at(), MAX_AT_LENGTH),
                sanitize(payload.ua(), MAX_UA_LENGTH),
                sanitize(payload.stack(), MAX_STACK_LENGTH));
        return ResponseEntity.noContent().build();
    }

    /** 上报体（8 字段白名单；**多一个字段都不读**）。 */
    public record ClientErrorRequest(
            String path,
            String name,
            String message,
            String stack,
            String digest,
            String at,
            String ua,
            String source) {
    }

    /**
     * 返回第一个不合法字段名（合法 ⇒ {@code null}）。
     *
     * <p>⚠️ {@code path} 的 {@code ?} / {@code #} 判定是**隐私护栏**：它意味着客户端把 query（可能含 token）
     * 带出来了 —— 拒收 + 400，而不是「涂掉再记」。</p>
     */
    static String firstInvalidField(ClientErrorRequest payload) {
        if (!StringUtils.hasText(payload.source())
                || !ALLOWED_SOURCES.contains(payload.source().trim().toLowerCase(Locale.ROOT))) {
            return "source";
        }
        if (!StringUtils.hasText(payload.path())
                || !payload.path().startsWith("/")
                || payload.path().indexOf('?') >= 0
                || payload.path().indexOf('#') >= 0) {
            return "path";
        }
        if (tooLong(payload.path(), MAX_PATH_LENGTH)) return "path";
        if (!StringUtils.hasText(payload.name()) || tooLong(payload.name(), MAX_NAME_LENGTH)) return "name";
        if (!StringUtils.hasText(payload.message()) || tooLong(payload.message(), MAX_MESSAGE_LENGTH)) {
            return "message";
        }
        if (tooLong(payload.stack(), MAX_STACK_LENGTH)) return "stack";
        if (tooLong(payload.digest(), MAX_DIGEST_LENGTH)) return "digest";
        if (tooLong(payload.at(), MAX_AT_LENGTH)) return "at";
        if (tooLong(payload.ua(), MAX_UA_LENGTH)) return "ua";
        return null;
    }

    private static boolean tooLong(String value, int max) {
        return value != null && value.length() > max;
    }

    /** 接受 JSON 与 text/plain（后者给 `sendBeacon` 这类不能设置 JSON 头的调用方）；其余 415。 */
    private static boolean isAcceptableContentType(String contentType) {
        if (!StringUtils.hasText(contentType)) return true;
        String normalized = contentType.toLowerCase(Locale.ROOT);
        return normalized.startsWith("application/json") || normalized.startsWith("text/plain");
    }

    /**
     * 有界读取：最多读 {@link #MAX_BODY_BYTES} 字节。
     *
     * @return 读到的主体；**超限 ⇒ {@code null}**（且不把超出的内容读进来）
     */
    private static byte[] readBounded(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream(512);
        byte[] buffer = new byte[1024];
        int total = 0;
        while (true) {
            int read = in.read(buffer);
            if (read == -1) return out.toByteArray();
            total += read;
            if (total > MAX_BODY_BYTES) return null;
            out.write(buffer, 0, read);
        }
    }

    /**
     * 落日志前的涂抹 + 截断（顺序：先涂抹后截断；控制字符压成空格 —— 日志是一行事件）。
     */
    static String sanitize(String raw, int maxLength) {
        if (raw == null) return "-";
        String out = JWT.matcher(raw).replaceAll("[redacted-jwt]");
        out = BEARER.matcher(out).replaceAll("Bearer [redacted]");
        out = KV_SECRET.matcher(out).replaceAll("$1=[redacted]");
        out = CN_MOBILE.matcher(out).replaceAll("[redacted-phone]");
        out = URL_QUERY.matcher(out).replaceAll("$1?[redacted-query]");
        out = out.replaceAll("[\\u0000-\\u001f\\u007f]+", " ").replaceAll("\\s+", " ").trim();
        int limit = Math.min(maxLength, MAX_LOG_FIELD);
        if (out.length() > limit) {
            out = out.substring(0, limit - 1) + "…";
        }
        return out.isEmpty() ? "-" : out;
    }

    /**
     * 解析客户端 IP（与 {@code RegistrationController#resolveClientIp} **同口径**，防伪造）：
     * {@code X-Real-IP}（nginx 覆盖为真实对端）→ {@code X-Forwarded-For} 首位 → {@code remoteAddr}。
     */
    private static String resolveClientIp(HttpServletRequest request) {
        String realIp = request.getHeader("X-Real-IP");
        if (StringUtils.hasText(realIp)) return realIp.trim();
        String forwarded = request.getHeader("X-Forwarded-For");
        if (StringUtils.hasText(forwarded)) {
            String first = forwarded.split(",")[0].trim();
            if (StringUtils.hasText(first)) return first;
        }
        return request.getRemoteAddr();
    }
}
