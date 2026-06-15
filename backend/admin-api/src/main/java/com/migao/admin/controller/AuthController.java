package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.LoginRequest;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.dto.MiniLoginRequest;
import com.migao.admin.dto.RefreshTokenRequest;
import com.migao.admin.dto.SmsLoginRequest;
import com.migao.admin.dto.UserInfoResponse;
import com.migao.admin.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

/**
 * 认证控制器
 * 处理登录、登出、Token 刷新、获取当前用户信息等认证相关接口
 */
@Slf4j
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    // ======================== 账号密码登录 ========================

    /**
     * 管理后台登录 — 已禁用
     *
     * POST /api/auth/admin/login
     *
     * 密码登录入口已于 2026-06-15 禁用（#375）。
     * 请改用 POST /api/auth/sms/login（短信验证码登录）。
     *
     * @deprecated 使用短信验证码登录替代
     */
    @Deprecated
    @PostMapping("/admin/login")
    public ApiResponse<Void> adminLogin(
            @Valid @RequestBody LoginRequest request,
            HttpServletResponse response) {
        log.warn("密码登录已禁用 (#375), username={}", request.getUsername());
        throw BusinessException.authFailed("密码登录已禁用，请使用短信验证码登录");
    }

    // ======================== 短信验证码登录 ========================

    /**
     * 短信验证码登录
     *
     * POST /api/auth/sms/login
     *
     * Request: { "phone": "13800138000", "code": "123456" }
     * Response: { "success": true, "data": { "user": {...}, "token": "..." } }
     */
    @PostMapping("/sms/login")
    public ApiResponse<LoginResponse> smsLogin(
            @Valid @RequestBody SmsLoginRequest request,
            HttpServletResponse response) {
        log.info("短信验证码登录请求: phone={}", request.getPhone());
        LoginResponse loginResponse = authService.loginBySms(request.getPhone(), request.getCode(), response);
        return ApiResponse.success(loginResponse);
    }

    // ======================== 微信小程序登录（占位） ========================

    /**
     * 微信小程序登录
     *
     * POST /api/auth/mini/login
     *
     * Request: { "code": "wx.login()返回的code", "tenantId": "TENANT001" }
     * Response: { "success": true, "data": { "token": "...", "user": {...} } }
     */
    @PostMapping("/mini/login")
    public ApiResponse<LoginResponse> miniProgramLogin(
            @Valid @RequestBody MiniLoginRequest request,
            HttpServletResponse response) {
        log.info("微信小程序登录请求: tenantId={}", request.getTenantId());
        LoginResponse loginResponse = authService.miniProgramLogin(request.getCode(), request.getTenantId(), response);
        return ApiResponse.success(loginResponse);
    }

    // ======================== 微信公众号 OAuth（占位） ========================

    /**
     * 微信公众号 OAuth 授权跳转
     *
     * GET /api/auth/h5/authorize?tenant_code=TENANT001&redirect_uri=https://...
     *
     * TODO: 接入微信公众号 OAuth 2.0 接口
     */
    @GetMapping("/h5/authorize")
    public void h5Authorize(
            @RequestParam("tenant_code") String tenantCode,
            @RequestParam("redirect_uri") String redirectUri,
            HttpServletResponse response) throws Exception {
        log.info("微信公众号 OAuth 授权跳转: tenantCode={}", tenantCode);
        String oauthUrl = authService.buildWechatH5AuthorizeUrl(tenantCode, redirectUri);
        response.sendRedirect(oauthUrl);
    }

    /**
     * 微信公众号 OAuth 回调
     *
     * GET /api/auth/h5/callback?code=xxx&state=xxx
     *
     * TODO: 接入微信 OAuth 回调处理
     */
    @GetMapping("/h5/callback")
    public void h5Callback(
            @RequestParam String code,
            @RequestParam String state,
            HttpServletResponse response) throws Exception {
        log.info("微信公众号 OAuth 回调: state={}", state);
        String redirectUrl = authService.handleWechatH5Callback(code, state, response);
        response.sendRedirect(redirectUrl);
    }

    // ======================== Token 管理 ========================

    /**
     * 刷新 Token
     *
     * POST /api/auth/refresh
     */
    @PostMapping("/refresh")
    public ApiResponse<LoginResponse> refreshToken(
            @Valid @RequestBody RefreshTokenRequest request,
            HttpServletResponse response) {
        log.info("刷新 Token 请求");
        LoginResponse loginResponse = authService.refreshToken(request.getRefreshToken(), response);
        return ApiResponse.success(loginResponse);
    }

    /**
     * 登出
     *
     * POST /api/auth/logout
     *
     * 将 Token 加入 Redis 黑名单，清除 Cookie
     */
    @PostMapping("/logout")
    public ApiResponse<Void> logout(HttpServletRequest request, HttpServletResponse response) {
        log.info("登出请求");
        authService.logout(request, response);
        return ApiResponse.success();
    }

    // ======================== 用户信息 ========================

    /**
     * 获取当前登录用户信息
     *
     * GET /api/auth/me
     *
     * 需要认证，返回用户详情（含角色、权限、菜单）
     */
    @GetMapping("/me")
    public ApiResponse<UserInfoResponse> getCurrentUser() {
        UserInfoResponse userInfo = authService.getCurrentUser();
        return ApiResponse.success(userInfo);
    }
}
