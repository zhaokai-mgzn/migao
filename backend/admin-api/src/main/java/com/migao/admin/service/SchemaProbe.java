package com.migao.admin.service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * 表存在性探针的参数判定（issue #7373 复盘：自证云环境用）—— **纯函数**。
 *
 * <h3>为什么需要它</h3>
 * <p>`MigrationRunner` 对非连接类失败是「跳过这条、继续跑」（#3270 的刻意权衡）⇒ 库里少一张表时
 * 服务照常 UP、部署 success、页面 500，而**没人知道迁移失败过**。要回答「云上到底有没有这张表」，
 * 需要一个只读探针；而探针一旦接受任意表名拼进 SQL，就变成注入口。
 *
 * <p>所以：表名必须匹配 {@code ^[a-z][a-z0-9_]{0,62}$}（PostgreSQL 标识符的保守子集），
 * 且**只查 `information_schema.tables`**（不可能被写）。非法名一律剔除并如实回报，
 * 不静默忽略 —— 「我查了你给的 3 个、其中 1 个不合法」比「查了 2 个、看着都对」更诚实。</p>
 */
public final class SchemaProbe {

    /** 保守标识符：小写字母开头，仅小写字母/数字/下划线，≤63 字符（PG 上限）。 */
    private static final Pattern SAFE_IDENTIFIER = Pattern.compile("^[a-z][a-z0-9_]{0,62}$");

    /** 一次最多查这么多张（防被人当全库扫描器用）。 */
    public static final int MAX_TABLES = 40;

    private SchemaProbe() {
    }

    /** 该表名是否可安全拼进 `information_schema.tables WHERE table_name = ?`（我们其实用参数，但判定同源）。 */
    public static boolean isSafeTableName(String table) {
        return table != null && SAFE_IDENTIFIER.matcher(table.trim()).matches();
    }

    /**
     * 解析请求里的表名清单：去重保序、剔除非法、截断到上限。
     *
     * @return 可查询的表名（保序）
     */
    public static List<String> accepted(String commaSeparated) {
        List<String> out = new ArrayList<>();
        if (commaSeparated == null || commaSeparated.isBlank()) {
            return out;
        }
        for (String raw : commaSeparated.split(",")) {
            String name = raw.trim();
            if (name.isEmpty() || !isSafeTableName(name) || out.contains(name)) {
                continue;
            }
            if (out.size() >= MAX_TABLES) {
                break;
            }
            out.add(name);
        }
        return out;
    }

    /** 被剔除的表名（如实回报，不静默吞）。 */
    public static List<String> rejected(String commaSeparated) {
        List<String> out = new ArrayList<>();
        if (commaSeparated == null || commaSeparated.isBlank()) {
            return out;
        }
        for (String raw : commaSeparated.split(",")) {
            String name = raw.trim();
            if (!name.isEmpty() && !isSafeTableName(name)) {
                out.add(name);
            }
        }
        return out;
    }

    /** 结果组装（保序：与请求同序，便于人读日志对齐）。 */
    public static Map<String, Object> report(List<String> requested, List<String> present, List<String> rejected) {
        Map<String, Object> body = new LinkedHashMap<>();
        Map<String, Boolean> presence = new LinkedHashMap<>();
        for (String table : requested) {
            presence.put(table, present.contains(table));
        }
        body.put("tables", presence);
        body.put("missing", presence.entrySet().stream()
                .filter(e -> !e.getValue()).map(Map.Entry::getKey).toList());
        body.put("rejected", rejected);
        return body;
    }
}
