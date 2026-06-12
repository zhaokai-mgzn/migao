package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 跟进状态响应 DTO
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class FollowStatusResponse {

    private String orderId;
    private String followStatus;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime updatedAt;
}
