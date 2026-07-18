package com.migao.admin.dto.agent;

import lombok.Data;

import java.util.List;

/**
 * Agent 专用加工项操作请求。
 * 用于 PATCH /api/admin/agent/products/{id}/processing-items。
 * 增删语义：add 仅插入不存在的，remove 仅删除存在的（幂等）。
 */
@Data
public class AgentProcessingItemActionRequest {

    /** 操作类型：add（新增）或 remove（删除） */
    private String action;

    /**
     * 加工项 ID 列表。
     * 可混合传入 UUID 字符串 / 加工项名称 / 序号（1-based）。
     * 服务端统一解析为真实 UUID。
     */
    private List<String> itemIds;
}
