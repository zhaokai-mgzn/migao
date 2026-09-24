package com.migao.admin.support.fieldtruth;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/**
 * 字段级「是否有真值（= 是否存在计算逻辑）」声明 —— <b>一类病</b>的可复用载体（issue #5362）。
 *
 * <p><b>病根（实测，非推断）</b>：{@code customer_profiles} 的 RFM / 统计列
 * （{@code rScore} / {@code fScore} / {@code mScore} / {@code rfmTotalScore} / {@code totalOrders} /
 * {@code totalConsumption} / {@code totalRefundAmount} / {@code avgOrderValue} / {@code lastOrderAt} …）
 * —— schema 在、实体在、Mapper 在、Service 在、Controller 读面在，<b>唯独没有计算逻辑</b>
 * （全仓 {@code setRScore(} / {@code setAvgOrderValue(} / {@code setLastOrderAt(} 零命中）。
 * 于是数据库列的 {@code DEFAULT 0} / {@code DEFAULT 30} 就成了「真值」：页面与 Agent 拿到的
 * {@code rfmTotalScore: 0} 看起来像「这个客户 RFM 总分 0 分」、「消费 0 元」。
 * 这与 {@code product_skus.avg_cost} 早已立下的口径
 * （{@code NULL = 未知（存量库存无成本真值来源，一律不回填、不猜 0）}）是<b>同一个错</b>。
 *
 * <p><b>本枚举只定义机制</b>（声明形态 + 查询面），首个载体见 {@link CustomerProfileFieldTruth}；
 * 下一张表按「声明 + 判据」两步复用即可 —— 判据在
 * {@code backend/admin-api/src/test/java/com/migao/admin/support/fieldtruth/CustomerProfileFieldTruthGateTest.java}
 * （机械、可注入变红）。
 *
 * <p>🔴 判据两条：
 * <ol>
 *   <li><b>生产侧</b>：声明有真值 ⇒ 源码里必须存在<b>真值级</b>写入点（setter / builder / SQL {@code SET} /
 *       框架生成注解）；声明无真值 ⇒ 不得存在真值级写入点（常量占位/建档种子允许，但必须写进原因）。</li>
 *   <li><b>暴露侧</b>：声明无真值的字段不得以真值形态暴露 —— 读面一律置 {@code null}
 *       （= 未知；页面与 Agent 同受约束），遮蔽清单与声明的 {@code NO_TRUTH} 集合必须一一对应。</li>
 * </ol>
 */
public enum FieldTruth {
    /** 有真值：源码里存在真值级写入点（值来自数据 / 请求 / 时间，或由框架生成）。 */
    HAS_TRUTH,
    /** 无真值：全仓没有任何计算逻辑；值只可能来自 DB 列默认值或建档种子常量。 */
    NO_TRUTH;

    /**
     * **跨端运输名**（装配层把它放进快照，消费方按它逐字段分类）—— 小写下划线形态。
     *
     * <p>消费方（如 ai-agent 侧的具名视图 `customer_profile`）**不持有**第二份真值判断：它只认运输来的
     * 这个名字 ⇒ 两侧的词表必须逐字一致（{@code has_truth} / {@code no_truth}），改名时两侧一起红。</p>
     */
    public String wireName() {
        return name().toLowerCase(java.util.Locale.ROOT);
    }

    /** 单字段声明：真值状态 + 原因（原因 = 证据的落点，禁止「暂无」这类空话）。 */
    public record Entry(FieldTruth truth, String reason) {
        public Entry {
            if (truth == null) {
                throw new IllegalArgumentException("字段声明必须给出真值状态（HAS_TRUTH / NO_TRUTH）");
            }
            if (reason == null || reason.isBlank()) {
                throw new IllegalArgumentException("字段声明的原因不可为空 —— 它就是要消灭的「没有声明」");
            }
        }
    }

    /**
     * 一张表（= 一个实体）的字段级真值声明。
     *
     * @param entity 实体类（判据用反射校验完整性：实体每个字段都必须被声明）
     * @param table  表名
     * @param fields Java 属性名 → 声明
     */
    public record Declaration(Class<?> entity, String table, Map<String, Entry> fields) {
        public Declaration {
            fields = Map.copyOf(fields);
        }

        public Entry entry(String field) {
            return fields.get(field);
        }

        /** 未声明的字段 → {@code null}（禁静默当成「有真值」）。 */
        public FieldTruth truthOf(String field) {
            Entry e = fields.get(field);
            return e == null ? null : e.truth();
        }

        public Set<String> declaredFields() {
            return new TreeSet<>(fields.keySet());
        }

        public Set<String> noTruthFields() {
            return of(FieldTruth.NO_TRUTH);
        }

        public Set<String> hasTruthFields() {
            return of(FieldTruth.HAS_TRUTH);
        }

        /**
         * **跨端运输形态**：`{字段: {"truth": "has_truth"|"no_truth", "reason": "…"}}`（issue #5456）。
         *
         * <p>按字段名**排序**输出（{@link #declaredFields()} 是 {@link TreeSet}）⇒ 同一份声明产出逐字节
         * 相同的结果，消费方的「同一快照 ⇒ 逐字相同输出」判据因此可成立。</p>
         *
         * <p>🔴 字段集、真值侧与 {@code reason}（证据化原因）**全部现取**本声明 —— 装配层与消费方都不得
         * 另写一份（那正是「同一真值两处投影」的病灶）。消费方对「为什么这个字段没有真值」的唯一说法
         * 就是这里的 {@code reason}；而「哪些字段有真值」的唯一来源就是本声明。</p>
         */
        public Map<String, Object> payload() {
            Map<String, Object> out = new LinkedHashMap<>();
            for (String field : declaredFields()) {
                Entry entry = fields.get(field);
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("truth", entry.truth().wireName());
                item.put("reason", entry.reason());
                out.put(field, item);
            }
            return out;
        }

        private Set<String> of(FieldTruth wanted) {
            Set<String> out = new TreeSet<>();
            fields.forEach((field, entry) -> {
                if (entry.truth() == wanted) {
                    out.add(field);
                }
            });
            return out;
        }
    }
}