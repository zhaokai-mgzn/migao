package com.migao.admin.dto;

import lombok.Data;

/**
 * 编辑仓位请求（issue #7785）。
 *
 * <p>字段为 {@code null} = 不改；{@code remark=""} = 清空备注。占用中（有在库成品）的仓位
 * 不允许修改 {@code binCode} —— 在库行与已贴标签认的都是这个号。</p>
 */
@Data
public class WarehouseLocationUpdateRequest {

    /** 新仓位号（null = 不改；占用中禁止改） */
    private String binCode;

    /** 区域编码（null = 不改） */
    private String zoneCode;

    /** 区域名称（null = 不改） */
    private String zoneName;

    /** 备注（null = 不改；空串 = 清空） */
    private String remark;

    /** active / inactive（null = 不改） */
    private String status;
}
