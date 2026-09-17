package com.migao.admin.security;

import com.migao.admin.dto.ApiResponse;

import java.util.List;

/**
 * 403 权限拒绝响应体的统一构造（issue #4105 F1）。
 *
 * <p>两个入口共用一份措辞，避免漂移：</p>
 * <ul>
 *   <li>HTTP 授权入口 {@code SecurityConfig#accessDeniedHandler}：路径级拒绝，无法得知所需权限码；</li>
 *   <li>{@code @RequirePermission} 切面拒绝 → {@code GlobalExceptionHandler#handleAccessDeniedException}：
 *       携带缺失的权限码。</li>
 * </ul>
 *
 * <p>{@code suggestion} 是**给 LLM 的执行指令**，必须同时表达三件事：这是角色/权限限制、
 * **不是**参数或数据问题；**不要重试同一个工具**；如实告知用户并请管理员在「岗位权限」中授予。</p>
 */
public final class PermissionDeniedResponse {

    /**
     * 无法得知所需权限码时的泛化建议（路径级拒绝）。
     */
    static final String GENERIC_SUGGESTION =
            "这是账号的角色/权限限制，不是参数或数据问题：不要重复调用同一工具。"
                    + "请如实告知用户其账号暂无该功能权限，并请企业管理员在「岗位权限」中"
                    + "核对该账号的权限后再操作。";

    private PermissionDeniedResponse() {
    }

    /**
     * 构造 403 响应体。
     *
     * @param requiredPermission 缺失的权限码；路径级拒绝（未知所需权限码）传 {@code null}
     * @return 含 {@code error.code}/{@code error.details[requiredPermission]}/{@code suggestion} 的响应
     */
    public static ApiResponse<Void> of(String requiredPermission) {
        if (requiredPermission == null) {
            return ApiResponse.errorWithSuggestion("PERMISSION_DENIED", "权限不足", GENERIC_SUGGESTION);
        }
        ApiResponse<Void> response = ApiResponse.errorWithSuggestion("PERMISSION_DENIED",
                "权限不足，需要权限: " + requiredPermission,
                "这是账号的角色/权限限制，不是参数或数据问题：不要重复调用同一工具。"
                        + "当前账号缺少「" + requiredPermission + "」权限，请如实告知用户其账号暂无该功能权限，"
                        + "并请企业管理员在「岗位权限」中为该账号授予该权限后再操作。");
        response.getError().setDetails(List.of(
                new ApiResponse.ErrorDetail("requiredPermission", requiredPermission)));
        return response;
    }
}