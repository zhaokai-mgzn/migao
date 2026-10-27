package com.migao.admin.dto;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/**
 * 登记一次打印（issue #7902）：一次「联合打印」= 一个请求里的 N 条文档。
 *
 * <p>⚠️ 请求体里**只有客户端真正知道的东西**（打了哪种单据、几张、哪台纸型、成功与否）；
 * 订单号 / 订单状态 / 操作人 / 租户 / 时间全部由**服务端**补齐 ——
 * 「谁打的」若允许调用方自己写，流水就没有证据价值。</p>
 */
@Data
public class PrintLogRequest {

    /** 本次打印涉及的文档（至少 1 条、至多 10 条；服务端按顺序补 batchIndex/batchSize）。 */
    private List<PrintLogItemRequest> docs = new ArrayList<>();
}
