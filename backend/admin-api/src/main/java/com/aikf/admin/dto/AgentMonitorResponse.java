package com.aikf.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * 人工客服监控面板数据响应 DTO
 * 用于企业内部管理人员监控客服工作台运行状态
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AgentMonitorResponse {

    private Integer onlineEmployeeCount;

    private Integer activeSessionCount;

    private Integer waitingSessionCount;

    private Integer todayTotalSessions;

    /** 今日平均响应时间（秒） */
    private Long todayAvgResponseTime;

    /** 在线员工列表 */
    private List<EmployeeStatusInfo> onlineEmployees;

    /**
     * 员工状态信息
     */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class EmployeeStatusInfo {

        private String id;

        private String name;

        private String status;

        private Integer activeSessionCount;

        private Integer maxConcurrentSessions;
    }
}
