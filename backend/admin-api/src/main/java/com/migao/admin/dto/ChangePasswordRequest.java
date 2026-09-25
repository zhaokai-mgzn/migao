package com.migao.admin.dto;

import lombok.Data;

/**
 * 自助改密请求（issue #5485：{@code POST /api/auth/password/change}）。
 *
 * <p>与 {@code PUT /api/admin/settings/password} 的既有请求体同形（旧密码 + 新密码），
 * 但本端点是**首登强制改密**的出口：只需认证、成功后清除 {@code must_change_password}。
 */
@Data
public class ChangePasswordRequest {

    /** 原密码 */
    private String oldPassword;

    /** 新密码（策略：≥8 位且同时含字母与数字；不满足 → 422 明确文案） */
    private String newPassword;
}