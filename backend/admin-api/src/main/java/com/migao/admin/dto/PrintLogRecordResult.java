package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 登记打印的回执（issue #7902）：这次落了几行、落在什么时刻。
 *
 * <p>为什么回 {@code ids}：一次联合打印会落 N 行，前端「撤销 / 重打」需要指认**这一批**
 * （批号的另一种表达 = 这 N 个 id 共享同一个 {@code batchId}）；只回计数就只能猜。</p>
 */
@Data
@AllArgsConstructor
public class PrintLogRecordResult {

    /** 本次落库的流水 id（顺序与请求里的 docs 一致）。 */
    private List<String> ids;

    /** 本次打印的登机时刻（服务端时间，同一批共用）。 */
    private OffsetDateTime printedAt;
}
