package com.migao.admin.dto;

import lombok.Data;

import java.util.List;

/**
 * 生成加工单请求（issue #3340）
 */
@Data
public class ProcessingOrderGenerateRequest {

    /** 订单 ID 或订单号列表（服务端解析） */
    private List<String> orderIds;
}
