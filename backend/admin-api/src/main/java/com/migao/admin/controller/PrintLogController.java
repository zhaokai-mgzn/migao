package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PrintLogRecordResult;
import com.migao.admin.dto.PrintLogRequest;
import com.migao.admin.dto.PrintLogView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.PrintLogService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.stream.Collectors;

/**
 * 打印中心（issue #7902）：订单详情页的**打印流水**写面与读面。
 *
 * <h3>授权：写面同码 {@code order:detail}（不新造权限码）</h3>
 * <p>打印入口本来就在订单详情页 —— 能看这张单的人就该能打。「另造一个 {@code order:print}」
 * 会让现网种子岗位全体 403（没人持新码），而那个失效**不会有任何东西变红**：
 * 单测不起 Spring 上下文、页面按钮照旧渲染。判据 = {@code PrintLogSurfaceGuardTest}（反射读注解）。</p>
 *
 * <h3>路径：{@code /api/admin/orders/{orderId}/print-logs}</h3>
 * <p>比 {@code OrderController} 的 {@code GET /api/admin/orders/{id:[0-9a-fA-F-]+}} 多一层**静态段**，
 * 两者不歧义（静态段优先匹配更具体的路径）；全仓只有本控制器映射这条路径（守卫同文件判据 3）。</p>
 *
 * <h3>状态码</h3>
 * <ul>
 *   <li>入参不合法（条数 / 闭集合 / 长度 / 张数）⇒ <b>400</b>；</li>
 *   <li>订单不存在 / 非本租户 ⇒ <b>404</b>（不是 403：403 等于告诉对方「这个单存在，只是不归你」）；</li>
 *   <li>「打过但没有流水」⇒ <b>200 + 空数组</b>（空 ≠ 404，两者含义不同）。</li>
 * </ul>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/orders/{orderId}/print-logs")
@RequiredArgsConstructor
@RequirePermission("order:detail")
public class PrintLogController {

    private final PrintLogService printLogService;

    /**
     * 登记打印（一次联合打印 = 一个请求）。
     *
     * <p>{@code POST /api/admin/orders/{orderId}/print-logs}</p>
     *
     * <p>请求体只带客户端知道的事实（docs[].docType / docTitle / processingOrderId / mediaId / sheets /
     * channel / status / failReason）；订单号 / 订单状态 / 操作人 / 租户 / 时间由服务端补齐。</p>
     */
    @PostMapping
    public ApiResponse<PrintLogRecordResult> record(@PathVariable String orderId,
                                                    @RequestBody PrintLogRequest request,
                                                    HttpServletRequest httpRequest) {
        PrintLogRecordResult result = printLogService.record(
                orderId, request, TenantContext.getTenantId(), currentOperator(),
                httpRequest.getRemoteAddr(), httpRequest.getHeader("User-Agent"));
        // 日志只带订单与单据类型（UA 可能含设备指纹，不写进日志）
        log.info("[print-log] 登记打印 orderId={}, docTypes={}, rows={}",
                orderId, docTypesOf(request), result.getIds().size());
        return ApiResponse.success(result);
    }

    /**
     * 这张订单的打印流水（时间倒序）。
     *
     * <p>{@code GET /api/admin/orders/{orderId}/print-logs?limit=20}</p>
     */
    @GetMapping
    public ApiResponse<List<PrintLogView>> list(@PathVariable String orderId,
                                                @RequestParam(required = false) Integer limit) {
        return ApiResponse.success(
                printLogService.listByOrder(orderId, limit, TenantContext.getTenantId()));
    }

    /** 当前操作人（只从服务端安全上下文取；内部服务令牌 ⇒ null，服务层据 null 只留空快照）。 */
    private PrintLogService.Operator currentOperator() {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.getPrincipal() instanceof SecurityUser user) {
            return new PrintLogService.Operator(user.getUserId(), user.getDisplayName());
        }
        return null;
    }

    /** 日志用的单据类型摘要（未校验输入，仅用于一行日志）。 */
    private static String docTypesOf(PrintLogRequest request) {
        if (request == null || request.getDocs() == null) {
            return "[]";
        }
        return request.getDocs().stream()
                .map(doc -> doc == null ? "null" : String.valueOf(doc.getDocType()))
                .collect(Collectors.joining(",", "[", "]"));
    }
}
