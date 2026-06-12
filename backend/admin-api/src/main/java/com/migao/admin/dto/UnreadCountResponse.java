package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 未读通知数响应 DTO
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class UnreadCountResponse {

    /**
     * 未读通知数量
     */
    private Long count;
}
