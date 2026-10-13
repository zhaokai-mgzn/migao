// case_ids: OR-062, PR-121, PR-123

package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🧱 <b>类级元守卫（issue #6816）：{@code ProductSkuMapper} 里库存变更语句的 {@code RETURNING}
 * 不得对「变更前/后库存」取整 —— 未登记即红、台账只许缩短。</b>
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 本单修的是<b>两处</b>取整（{@code receiveStock} / {@code deductStock}），而两处的共性只有一个：
 * <b>把可精确表示的库存读数喂给了「取整」函数</b>。库存列自 V115（issue #5063）起是
 * {@code NUMERIC(12,1)}（0.1 米粒度），{@code CEIL}/{@code FLOOR}/{@code ROUND} 在这里没有语义
 * —— 它把精确读面变成「最多偏 0.9 的整数」，而 {@code StockLedger.delta = after − before}
 * 会跟着偏小（现场读数：67.2 米入库记成 {@code 68.0 → 68.2 / delta 0.2}）。
 *
 * <p>⇒ 光删掉这两处 {@code CEIL} 不够：<b>下一个新增的库存写面（出库 / 占用 / 盘点 / 冲销）
 * 照样可以写一遍 {@code CEIL}</b>，而没有任何东西会红。本守卫把它钉成机械判据：
 * <b>清单现取</b>（扫源码，不写死方法名表）、<b>未登记即红且具名</b>、
 * <b>登记台账只许缩短</b>（{@code REGISTERED_TOTAL} = 现取条数的上界；数错工程师说了不算，机器说了算）。</p>
 *
 * <h2>判据道（每条都会红）</h2>
 * <ol>
 *   <li><b>台账口径自证（防"只在守卫里"）</b>：{@code REGISTERED_TOTAL}（显式钉住的条数上界）
 *       ≥ 从源码现取的 {@code ROUND(} 条数 —— 源码里新增一条取整而没登记 ⇒ 红（"怎么改会红"见类注释末）。</li>
 *   <li><b>未登记即红 + 数值判据</b>：库存变更语句的 {@code RETURNING} 里每条
 *       {@code CEIL(}/{@code FLOOR(}/{@code ROUND(} 都必须在台账里逐字登记，且
 *       {@code "beforeQuantity"} 表达式<b>必须</b>是精确的 {@code stock −/+ #{quantity}}
 *       —— 台账<b>不得</b>用登记把 before/after 的取整洗白。</li>
 *   <li><b>扫描器不失明 + 台账不许空转</b>：现取的库存变更语句必须包含本单的
 *       {@code ProductSkuMapper#receiveStock} 与 {@code #deductStock}；台账为空也没东西红
 *       = 守卫空转 ⇒ 当场红（fail-closed）。</li>
 *   <li><b>判别力自证</b>：用合成语料证明「新写面加 {@code CEIL} 未登记」「显式把库存读数登记掉」
 *       两种坏形态各自判红，而合规语料不红 —— 没有这条，「守卫恒绿」与「守卫有效」在结果列上
 *       长得一样。</li>
 * </ol>
 *
 * <h2>怎么改会红（可复制命令）</h2>
 * <ol>
 *   <li><b>同一个缺陷复发</b>：把 {@code ProductSkuMapper#receiveStock} 的
 *       {@code RETURNING stock - #{quantity} AS "beforeQuantity"} 改回
 *       {@code RETURNING CEIL(stock - #{quantity}) AS "beforeQuantity"} ⇒ 判据 2 红并具名报出
 *       {@code before_qty-rounding-registry 未登记: ProductSkuMapper.java#receiveStock →(取整表达式)}；
 *       同一条改动也会让真库判据 {@code LedgerBeforeQuantityPrecisionRealDbTest} 红。</li>
 *   <li><b>新增一个取整的库存写面</b>（例如给 {@code ProductSkuMapper} 加一个
 *       {@code UPDATE product_skus SET stock = stocks + #{qty} … RETURNING ROUND(stock) …}）⇒ 判据 1+2 红。</li>
 *   <li><b>把 before/after 的取整"登记掉"以消红</b>：往 {@code ROUNDED_EXPRESSION_REGISTRY}
 *       里加一条 {@code "product_skus SET stock 表达式"} ⇒ 判据 2 的数值判据红
 *       （before 表达式不含 {@code #{quantity}} ⇒ 取不精确）。</li>
 * </ol>
 *
 * <p>⚠️ 本判据读<b>源码文本</b>（不做 AST）—— 与 {@code StockDeductionAndLedgerAtomicityMetaGuardTest}
 * 同款。代价：它只能证明「这几个字在语句里」；<b>行为面由真库判据承担</b>：
 * {@code LedgerBeforeQuantityPrecisionRealDbTest}（#6816）——
 * {@code migao-dev-flow} §28.2：判据本体绿 ≠ 接线在。</p>
 *
 * <p><b>边界（如实登记，§19.1）</b>：① 登记台账是<b>冻结快照</b>（{@code REGISTERED_TOTAL} 只许缩短）；
 * ② 形态判据换措辞（例如把取整写成 {@code CAST(x AS INT)}）可绕过 —— 真实防线仍是真库判据；
 * ③ 射程只到 {@code ProductSkuMapper}（其它 mapper 的库存写面不在本单射程内，未固化）；
 * ④ <b>只钉「给出了变更前读数」的那一族</b>（语句里出现 {@code "beforeQuantity"} 别名）——
 * 没走 {@code RETURNING} 的库存写面（如 {@code restoreStock} 的既有 {@code @Update}）不在射程内；
 * ⑤ 判据读的是 {@code ProductSkuMapper.java} <b>单个文件</b>（本类的合成语料里也含
 * {@code RETURNING CEIL(…)} 形态 —— 若哪天把射程扩成「扫 mapper 目录」，本类会被自己的语料喂红，
 * 扩射程时必须先把合成语料挪出被扫面）；⑥ 本守卫<b>不</b>改任何门禁的通过条件、不新增豁免。</p>
 */
@DisplayName("🧱 类级元守卫（#6816）：库存 RETURNING 不得对 before/after 取整（未登记即红）")
class LedgerBeforeQuantityRoundingMetaGuardTest {

    /** 模块根（Surefire 的工作目录 = {@code backend/admin-api}）。 */
    private static final String MODULE = "backend/admin-api";
    private static final String PRODUCT_SKU_MAPPER = MODULE + "/src/main/java/com/migao/admin/mapper/ProductSkuMapper.java";

    /** 被约束对象（缺一 ⇒ 判据失明，当场红）。 */
    private static final String TARGET_MAPPER = "ProductSkuMapper.java";
    private static final Set<String> TARGET_METHODS = Set.of("receiveStock", "deductStock");

    /**
     * 🔒 <b>取整表达式登记台账（冻结快照，只许缩短）</b>：现取到的每条
     * {@code CEIL(}/{@code FLOOR(}/{@code ROUND(} 都必须在这里逐字登记，否则判红。
     *
     * <p>登记粒度 = 那条取整表达式的<b>可检索前缀</b>（逐字出现在 SQL 里）。本单（#6816）修完后的唯一登记条
     * 是 {@code ROUND((} —— {@code receiveStock} 里 {@code cost_amount} 的成本金额舍入：
     * 它有语义（金额舍入到 4 位小数、列类型 {@code NUMERIC(16,4)} 逼出来的），且<b>不</b>在
     * {@code beforeQuantity}/{@code afterQuantity}（数量语义）的取值面上。</p>
     * <p>⚠️ <b>登记不是免死金牌</b>：往这张表里加 {@code CEIL(} 也<b>不</b>能让库存读数的取整变绿 ——
     * before/after 只认精确算式，那由判据 3 独立判（见类注释「怎么改会红」③）。</p>
     */
    private static final Set<String> ROUNDED_EXPRESSION_REGISTRY = Set.of(
            "ROUND((");

    /** 现取台账条数的上界（同上：只许缩短；源码里多出一条未登记 ⇒ 判据 1 红）。 */
    private static final int REGISTERED_TOTAL = 1;

    /** 被登记的合法取整表达式（登记名）——同时用于合成语料自证。 */
    private static final String REGISTERED_ROUND = "ROUND((";

    // ────────────────────────────────────────────── 形态

    /** SQL 字符串里「库存变更」的锚：一条 UPDATE product_skus（SET 子句可能写在属性里，故只认这两样）。 */
    private static final Pattern STOCK_MUTATION = Pattern.compile(
            "(?i)UPDATE\\s+product_skus\\b[\\s\\S]*?\\bSET\\b");
    /** 库存读数的别名（缺陷就是打在这两个别名上的取整函数）。 */
    private static final String BEFORE_ALIAS = "\"beforeQuantity\"";
    private static final String AFTER_ALIAS = "\"afterQuantity\"";
    /** 三种取整函数（本仓口径：库存读数一个都不许用）。 */
    private static final Pattern ROUNDING_CALL = Pattern.compile("(?i)\\b(CEIL|FLOOR|ROUND)\\s*\\(");
    /** 库存读数的合法算式：`stock <+/-> #{quantity}`（精确值，不做任何取整）。 */
    private static final Pattern EXACT_STOCK_ARITHMETIC = Pattern.compile(
            "stock\\s*(?:[,()]|\\d|\\s)*[-+]\\s*#\\{quantity\\}");

    // ────────────────────────────────────────────── 判据 1+2+3：真语料

    @Test
    @DisplayName("判据 1+2：ProductSkuMapper 库存 RETURNING 的取整必须已登记；before 表达式必须精确")
    void stockReturningRoundingMustBeRegistered() throws IOException {
        List<MapperStatement> statements = stockMutations(read(mapperFile()));
        assertThat(statements).as("扫描器必须真的看见库存变更语句（形态被改名 ⇒ 判据失明要当场暴露）")
                .isNotEmpty();

        Set<String> targets = new LinkedHashSet<>();
        List<String> violations = new ArrayList<>();
        for (MapperStatement s : statements) {
            if (s.statementText().contains(BEFORE_ALIAS)) {
                targets.add(s.methodName());
            }
            violations.addAll(roundingViolations(s, ROUNDED_EXPRESSION_REGISTRY));
        }

        System.out.println("[#6816 类级守卫] 现取库存变更语句=" + statements.stream()
                .map(MapperStatement::display).toList()
                + " 登记台账=" + ROUNDED_EXPRESSION_REGISTRY + " 上界=" + REGISTERED_TOTAL);

        assertThat(targets).as("扫描器必须看见本单的两个对象（改名/挪位 ⇒ 判据失明）")
                .containsAll(TARGET_METHODS);
        assertThat(violations).as("库存 RETURNING 的取整必须逐条登记；before/after 只许精确算式").isEmpty();
    }

    @Test
    @DisplayName("判据 1（现取口径自证）：源码现取的取整条数 ≤ 登记条数上界 ⇒ 新增取整未登记即红")
    void roundingCountDoesNotGrowBeyondRegistry() throws IOException {
        List<MapperStatement> statements = stockMutations(read(mapperFile()));
        int live = countRegisteredRounding(statements);
        int total = Math.max(live, ROUNDED_EXPRESSION_REGISTRY.size());

        System.out.println("[#6816 类级守卫] 取整条数现取=" + live
                + " 登记条数=" + ROUNDED_EXPRESSION_REGISTRY.size() + " 上界=" + REGISTERED_TOTAL);

        assertThat(total)
                .as("冻结上界只许缩短：源码 + 台账现取的取整条数必须 ≤ " + REGISTERED_TOTAL
                        + "（新增取整写面 ⇒ 先登记并说明语义，再同步本上界）—— 现取=" + live)
                .isLessThanOrEqualTo(REGISTERED_TOTAL);
        assertThat(ROUNDED_EXPRESSION_REGISTRY)
                .as("台账不许空转（fail-closed）：空台账 = 这条判据没有约束对象")
                .isNotEmpty();
    }

    @Test
    @DisplayName("判据 3（核心钉）：本单两个对象的 RETURNING 必须逐字给出精确的 stock ± #{quantity}")
    void beforeQuantityExpressionIsExactArithmetic() throws IOException {
        List<MapperStatement> statements = stockMutations(read(mapperFile()));
        for (MapperStatement s : statements) {
            // 只钉「给出了库存变更前读数」的那一族：任何 RETURNING 了 "beforeQuantity" 的写面都必须精确；
            // 没有 RETURNING 的写面（如 restoreStock 的既有 @Update）不在本判据射程内 —— 已在类注释登记
            if (!s.statementText().contains(BEFORE_ALIAS)) {
                continue;
            }
            System.out.println("[#6816 类级守卫] " + s.methodName() + " 的 before/after 表达式 = "
                    + s.beforeExpression() + " | " + s.afterExpression());
            assertThat(s.beforeExpression())
                    .as(s.methodName() + " 的 before_qty 必须是精确的 stock ∓ #{quantity}（不许 CEIL/FLOOR/ROUND）")
                    .containsPattern(EXACT_STOCK_ARITHMETIC);
            assertThat(s.afterExpression())
                    .as(s.methodName() + " 的 after_qty 必须是变更后的精确库存读数")
                    .contains("stock");
            assertThat(ROUNDING_CALL.matcher(s.returningText()).find())
                    .as(s.methodName() + " 的 RETURNING 不得含任何取整函数 —— before_qty 的取整会让"
                            + " delta = after − before 偏小（issue #6816）；唯一登记的例外是成本金额取整"
                            + "（cost_amount，金额语义），它也不在 RETURNING 的库存读数片段上")
                    .isFalse();
        }
    }

    // ────────────────────────────────────────────── 判据 4：判别力自证（合成语料）

    @Test
    @DisplayName("判据 4·判别力自证：新写面加 CEIL/FLOOR/ROUND 未登记 ⇒ 红；登记把库存读数洗白 ⇒ 红；合规 ⇒ 绿")
    void guardHasDiscriminatingPower() {
        // 合规：精确算式 + 已登记的成本金额取整
        String compliant = "UPDATE product_skus SET stock = stock + #{quantity}, "
                + "cost_amount = ROUND((stock + #{quantity}) * #{newAvgCost}, 4) "
                + "WHERE id = #{skuId} RETURNING stock - #{quantity} AS \"beforeQuantity\", "
                + "stock AS \"afterQuantity\"";
        // 坏形态 ①：新增写面把 before 取整（未登记）
        String ceilUnregistered = "UPDATE product_skus SET stock = stock - #{quantity} "
                + "WHERE id = #{skuId} RETURNING CEIL(stock + #{quantity}) AS \"beforeQuantity\", "
                + "stock AS \"afterQuantity\"";
        String floorUnregistered = "UPDATE product_skus SET stock = stock - #{quantity} "
                + "WHERE id = #{skuId} RETURNING FLOOR(stock + #{quantity}) AS \"beforeQuantity\", "
                + "stock AS \"afterQuantity\"";
        String roundUnregistered = "UPDATE product_skus SET stock = stock + #{quantity} "
                + "WHERE id = #{skuId} RETURNING ROUND(stock - #{quantity}, 1) AS \"beforeQuantity\", "
                + "stock AS \"afterQuantity\"";
        // 坏形态 ②：把 before 的取整"登记掉"（登记了 CEIL，仍必须红 —— 登记不是免死金牌）
        String washed = "UPDATE product_skus SET stock = stock - #{quantity} "
                + "WHERE id = #{skuId} RETURNING CEIL(stock + #{quantity}) AS \"beforeQuantity\", "
                + "stock AS \"afterQuantity\"";

        assertThat(roundingViolations(parse("compliant", compliant), ROUNDED_EXPRESSION_REGISTRY))
                .as("合规语料不得判红（否则每次改动都会被自己的文案喂红）").isEmpty();
        assertThat(roundingViolations(parse("ceil", ceilUnregistered), ROUNDED_EXPRESSION_REGISTRY))
                .as("坏形态 ①：CEIL 未登记 ⇒ 必须红").isNotEmpty();
        assertThat(roundingViolations(parse("floor", floorUnregistered), ROUNDED_EXPRESSION_REGISTRY))
                .as("坏形态 ①b：FLOOR 未登记 ⇒ 必须红").isNotEmpty();
        assertThat(roundingViolations(parse("round", roundUnregistered), ROUNDED_EXPRESSION_REGISTRY))
                .as("坏形态 ①c：新增 ROUND 未登记 ⇒ 必须红").isNotEmpty();
        assertThat(roundingViolations(parse("washed", washed), Set.of("CEIL(")))
                .as("坏形态 ②：把 before 的取整登记掉也必须红（库存读数只认精确算式）").isNotEmpty();

        // 计数的判别力：合成语料上现取条数必须真的数出来（不是恒 0 的假判据）
        assertThat(countRegisteredRounding(List.of(parse("compliant", compliant),
                parse("ceil", ceilUnregistered), parse("floor", floorUnregistered),
                parse("round", roundUnregistered))))
                .as("合成语料上现取取整条数必须真的数出来").isEqualTo(4);

        assertThat(ROUNDED_EXPRESSION_REGISTRY).as("真语料登记台账必须含那条成本金额取整（否则真语料判据会红）")
                .contains(REGISTERED_ROUND);
    }

    // ────────────────────────────────────────────── 判定本体（真语料与合成语料**同一套**）

    /**
     * 一条库存变更语句的取整违规清单（真语料整条 SQL / 合成语料片段 —— 同一套判定）。两条判据：
     * <ol>
     *   <li><b>库存读面（数量语义）不得含任何取整函数</b>：before/after 的取值面 = 最后一个
     *       {@code RETURNING} 之后的整段 —— 小数库存下 {@code CEIL}/{@code FLOOR}/{@code ROUND}
     *       都会让 {@code delta = after − before} 失真（issue #6816）。</li>
     *   <li><b>未登记即红</b>：语句里出现取整函数却没有任何一条 {@code ROUNDED_EXPRESSION_REGISTRY}
     *       登记名逐字落在语句文本里 ⇒ 红 —— 新增取整（成本金额以外的语义）必须先登记。</li>
     * </ol>
     */
    private static List<String> roundingViolations(MapperStatement s, Set<String> registry) {
        List<String> violations = new ArrayList<>();
        String returning = s.returningText();
        Matcher call = ROUNDING_CALL.matcher(returning);
        if (call.find()) {
            violations.add(s.display() + " 的 RETURNING 里对库存读面用了取整函数 " + call.group(1)
                    + "( —— 小数库存下 delta = after − before 会失真（issue #6816）；"
                    + "库存读数只许精确算式 stock ∓ #{quantity}");
        }
        if (ROUNDING_CALL.matcher(s.statementText()).find() && !isRegistered(s, registry)) {
            violations.add(s.display() + " 的语句里出现取整表达式，但没有任何登记名逐字出现在语句里"
                    + " —— 未登记即红：请在 ROUNDED_EXPRESSION_REGISTRY 登记该表达式并说明它的语义"
                    + "（现取登记名 = " + ROUNDED_EXPRESSION_REGISTRY + "）");
        }
        return violations;
    }

    /** 该语句的取整是否已登记：登记名必须逐字出现在语句文本里。 */
    private static boolean isRegistered(MapperStatement s, Set<String> registry) {
        for (String entry : registry) {
            if (s.statementText().contains(entry)) {
                return true;
            }
        }
        return false;
    }

    /** 现取条数：语句里有取整函数就算一条（与登记条数同口径）。 */
    private static int countRegisteredRounding(List<MapperStatement> statements) {
        int count = 0;
        for (MapperStatement s : statements) {
            if (ROUNDING_CALL.matcher(s.statementText()).find()) {
                count++;
            }
        }
        return count;
    }

    // ────────────────────────────────────────────── 解析工具

    /** 一条 mapper 写面：方法名 + 语句全文（各属性拼接后的 SQL）+ before/after 表达式。 */
    private record MapperStatement(String sourceFile, String methodName, String sql) {
        /** 语句全文（登记名逐字比对用）。 */
        String statementText() {
            return sql;
        }

        String display() {
            return sourceFile + "#" + methodName;
        }

        String beforeExpression() {
            return expressionOf(BEFORE_ALIAS);
        }

        String afterExpression() {
            return expressionOf(AFTER_ALIAS);
        }

        /** 最后一个 `RETURNING` 之后的整段（库存读数取值面）。 */
        private String returningText() {
            int at = sql.lastIndexOf("RETURNING");
            return at < 0 ? "" : sql.substring(at).replaceAll("\\s+", " ").trim();
        }

        /**
         * 某个库存读数别名的表达式片段（`stock + #{quantity}` / `stock`）。
         * 两侧边界都<b>按别名逐字定位</b>：右边界 = 本别名，左边界 = 上一列名的
         * {@code AS "上一别名"}。CTE 形态里别名在 {@code RETURNING} 与外层 {@code SELECT}
         * 里各出现一次，只取最后一次（本判据第一版取第一个，抓到的是外层列清单 —— 实测踩到）。
         */
        private String expressionOf(String alias) {
            Matcher aliasAt = Pattern.compile("AS\\s*" + Pattern.quote(alias)).matcher(sql);
            if (!aliasAt.find()) {
                return "";
            }
            int start = sql.lastIndexOf("RETURNING", aliasAt.start());
            String fragment = sql.substring(start < 0 ? 0 : start, aliasAt.start());
            // 左边界 = 本片段里最后一个列别名（`AS "skuCode", ` / 无则取 RETURNING 之后）：
            // 用「AS + 空格 + 双引号」形态逐字定位，避免把 COALESCE(stock, 0) 里的逗号当切点
            int cut = 0;
            Matcher marker = Pattern.compile("AS\\s*\"").matcher(fragment);
            while (marker.find()) {
                int quoteEnd = fragment.indexOf('"', marker.end());
                cut = quoteEnd < 0 ? marker.end() : quoteEnd + 1;
            }
            return fragment.substring(cut).replaceFirst("(?i)^\\s*RETURNING\\s*", "")
                    .replaceFirst("^[\\s,]+", "")
                    .replaceAll("\\s+", " ").trim();
        }

    }

    /** 合成语料 → 判定本体可直接吃的语句（sourceFile 固定为合成名，避免与真语料混淆）。 */
    private static MapperStatement parse(String label, String sql) {
        return new MapperStatement("合成." + label, label, sql);
    }

    /**
     * 扫 {@code ProductSkuMapper.java}：一个 {@code @Select}/{@code @Update} 注解 → 一条语句，
     * 方法名取紧随其后的 {@code public/private … 名字(} ；语句 SQL 取注解字符串里所有
     * {@code "…"} 字面量（本仓形态是 `"…" + "…"` 拼接，与 §23「清单现取」口径同源）。
     */
    private static List<MapperStatement> stockMutations(String source) {
        List<MapperStatement> found = new ArrayList<>();
        String[] annotations = source.split("@(?:Select|Update)");
        for (int i = 1; i < annotations.length; i++) {
            String block = annotations[i];
            String sql = stringLiterals(block);
            if (!STOCK_MUTATION.matcher(sql).find()) {
                continue;
            }
            found.add(new MapperStatement(TARGET_MAPPER, methodName(block), sql));
        }
        return found;
    }

    /**
     * 注解块里的方法名：<b>先整段抹掉字符串字面量</b>（SQL 字面量里也有 `(`，不抹掉会在 SQL 文本里
     * 误抓出一个"方法名" —— 本判据第一版实测踩到），再取第一个 `名字(`。
     */
    private static String methodName(String annotationBlock) {
        String withoutLiterals = annotationBlock.replaceAll("\"(?:[^\"\\\\]|\\\\.)*\"", " \"\" ");
        Matcher decl = Pattern.compile("([a-zA-Z_$][\\w$]*)\\s*\\(").matcher(withoutLiterals);
        return decl.find() ? decl.group(1) : "<未知方法>";
    }

    /**
     * 取一段 Java 文本里的字符串字面量并拼接（SQL 是 `"a" + "b"` 形态）。
     * ⚠️ <b>字面量内部的行首缩进要压平、字面量之间只留一个空格</b>：属性里的换行缩进会插进
     * SQL 中间，把 {@code AS "beforeQuantity"} 与它前面的表达式割开（本判据第一版实测踩到）。
     */
    private static String stringLiterals(String text) {
        StringBuilder sb = new StringBuilder();
        Matcher m = Pattern.compile("\"((?:[^\"\\\\]|\\\\.)*)\"").matcher(text);
        while (m.find()) {
            if (sb.length() > 0) {
                sb.append(' ');
            }
            sb.append(m.group(1).replace("\\\"", "\"").trim());
        }
        return sb.toString();
    }

    /** 仓根（Surefire 的 cwd = 模块目录或仓根，两种都兼容）。 */
    private static Path repoRoot() {
        Path root = Path.of("").toAbsolutePath();
        while (root != null && !Files.exists(root.resolve(MODULE))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 " + MODULE + "（工作目录 = " + Path.of("").toAbsolutePath() + "）")
                .isNotNull();
        return root;
    }

    private static Path mapperFile() {
        return repoRoot().resolve(PRODUCT_SKU_MAPPER);
    }

    private static String read(Path path) throws IOException {
        assertThat(path).as("被约束对象必须真实存在（路径漂移 ⇒ 判红，不是空跑通过）").exists();
        return Files.readString(path, StandardCharsets.UTF_8);
    }
}
