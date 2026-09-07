package com.migao.admin.config;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Component;

import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * C 端租户域名解析器（issue #3011）
 *
 * 客户颁发形态：<tenantId>.app.migaozn.com，租户 id 绑定在域名上。
 * 解析优先级：
 *   1. X-Tenant-Id 请求头（nginx 按子域名注入并以 proxy_set_header 覆盖客户端同名头，防伪造）
 *   2. Host 头正则 ^(\d+)\.app\.migaozn\.com$（本地直连/无网关场景兜底）
 *   3. 均无 → Optional.empty()（调用方决定拒绝或走兼容期兜底）
 */
@Component
public class TenantDomainResolver {

    /** nginx/网关注入的租户头 */
    public static final String TENANT_HEADER = "X-Tenant-Id";

    /** 租户子域名格式：<tenantId>.app.migaozn.com */
    private static final Pattern TENANT_SUBDOMAIN =
            Pattern.compile("^(\\d+)\\.app\\.migaozn\\.com$", Pattern.CASE_INSENSITIVE);

    /**
     * 从请求解析租户 id。
     *
     * @param request HTTP 请求
     * @return 解析出的租户 id；无法识别返回 empty
     */
    public Optional<Long> resolve(HttpServletRequest request) {
        // 1. 网关头（nginx 注入，信任）；仅接受纯数字，防注入
        String header = request.getHeader(TENANT_HEADER);
        Optional<Long> headerTenant = parseNumeric(header);
        if (headerTenant.isPresent()) {
            return headerTenant;
        }

        // 2. Host 子域名兜底：<tenantId>.app.migaozn.com
        Matcher matcher = TENANT_SUBDOMAIN.matcher(request.getServerName());
        if (matcher.matches()) {
            return Optional.of(Long.valueOf(matcher.group(1)));
        }

        return Optional.empty();
    }

    private Optional<Long> parseNumeric(String value) {
        if (value == null || value.isBlank()) {
            return Optional.empty();
        }
        String trimmed = value.trim();
        if (!trimmed.matches("\\d+")) {
            return Optional.empty();
        }
        try {
            return Optional.of(Long.valueOf(trimmed));
        } catch (NumberFormatException e) {
            return Optional.empty();
        }
    }
}