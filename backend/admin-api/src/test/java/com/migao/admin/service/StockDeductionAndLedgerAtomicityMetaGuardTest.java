// case_ids: OR-062, PR-123

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
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🧱 <b>类级元守卫（issues #6299 / #6300）：库存「扣减」与「记账」两条纪律，必须现取清单 + 未合规即红</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 本单修的是<b>两处</b>形态，而两处的共性只有一个：<b>把「判断/取值」和「写入」拆成了两条语句</b>。
 * <ul>
 *   <li><b>#6299 扣减侧</b>：{@code deductStock} 的 SQL 曾是
 *       {@code SET stock = GREATEST(COALESCE(stock,0) - #{quantity}, 0)} —— <b>无下限谓词 + 静默钳 0</b>；
 *       调用方拿它当「扣成功」用（返回 {@code int} 但没人看行数）。并发下两单都放行、库存被钳到 0
 *       ⇒ <b>超卖且无任何 4xx</b>。下一个入口（新的扣减/出库/占用方法）照样写一遍，没有任何东西会红。</li>
 *   <li><b>#6300 记账侧</b>：{@code stockLedgerService.record(…)} 的 {@code beforeQty/afterQty}
 *       曾是<b>读快照</b>（先 {@code SELECT stock}）—— 与同方法里的原子自增混用 ⇒ 并发下台账两行同基、
 *       链断裂（净增量仍对，<b>只看库存查不出来</b>）。</li>
 * </ul>
 * ⇒ 本守卫把两条纪律钉成机械判据：<b>清单现取</b>（扫描源码，不写死表）、<b>未合规即红且具名</b>。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>扫描器非空跑自证</b>：① 现取「扣减型写面」候选集必须包含 {@code ProductSkuMapper#deductStock}；
 *       ② 现取「落台账的库存变更方法」必须同时出现在 {@code OrderService} 与 {@code InboundOrderService}。
 *       候选集为空 / 少了核心对象 ⇒ 先红（形态被改名不是「通过」，而是「判据失明」）。</li>
 *   <li><b>扣减必须有下限谓词且不得静默钳 0</b>：凡 SQL 里出现 {@code stock = <表达式> - <表达式>} 的
 *       写面（= 扣减入口，<b>现取</b>），必须① 含 {@code COALESCE(stock, 0) >= #{…}} 下限谓词；
 *       ② <b>不得</b>含 {@code GREATEST(}（钳 0 = 把「扣不动」静默变成「扣到 0」）。</li>
 *   <li><b>扣减的 0 行必须被处理</b>：扣减型 mapper 方法的调用点所在方法体必须含受影响行数判定
 *       （{@code == 0} / {@code != 0} / …）—— 本单的新形态里「0 行」表现为返回 {@code null}，
 *       故 {@code == null} 同样算（判定形态见 {@code ROWCOUNT_CHECK}）。</li>
 *   <li><b>台账 before/after 必须来自原子语句</b>：落台账的库存变更方法里，每一次
 *       {@code record(…)} 的实参<b>不得</b>读自快照（{@code X.getStock()}）；且该调用所在方法体必须有
 *       原子取值锚（{@code RETURNING} 或逐字声明 {@code atomic-ledger: true}）。</li>
 *   <li><b>两个本单对象的最小钉</b>：{@code deductStock} 写面 SQL 必须同时含下限谓词与 {@code RETURNING}；
 *       {@code OrderService} 不得再出现快照式落台账（{@code snapshotForLedger}）；且
 *       {@code StockChange} <b>只能</b>由 mapper 的 {@code RETURNING} 行映射构造
 *       （类型上堵死「从读快照构造」这条路）。</li>
 *   <li><b>判别力自证</b>：用<b>合成语料</b>在内存里跑与真实源码<b>同一套</b>判定本体 ——
 *       「无下限谓词」「GREATEST 钳 0」「0 行未处理」「快照读落台账」四种坏形态各自判红，
 *       合规语料判绿。没有这条，「判据恒绿」与「判据有效」在结果列上长得一样。</li>
 * </ol>
 *
 * <p>⚠️ 本判据读<b>源码文本</b>（不做 AST）—— 本仓既有形态（{@code OrderAutoCompleteSqlGuardTest} 同款）。
 * 代价：它只能证明「这几个字在方法体里」；<b>行为面由真库并发判据承担</b>：
 * {@code OrderConfirmPaymentStockRaceRealDbTest}（#6299）与
 * {@code InboundPostLedgerChainRaceRealDbTest}（#6300）—— 三者缺一不可
 * （{@code migao-dev-flow} §28.2：判据本体绿 ≠ 接线在）。</p>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：① 形态判据换措辞可绕过（真实防线仍是各自的实例判据）；
 * ② 「原子性」的判定锚是 {@code RETURNING} / 声明式 pragma —— 别的原子手法（如
 * {@code SELECT … FOR UPDATE} 再读）会被判红（<b>有意</b>：本仓口径就是 RETURNING 一条语句）；
 * ③ 本守卫<b>不</b>判 {@code avg_cost} 的并发正确性（本单未修，已在 PR body 登记为未固化项）；
 * ④ 本守卫不改任何门禁的通过条件、不新增豁免。</p>
 */
@DisplayName("🧱 类级元守卫（#6299/#6300）：扣减必须有下限谓词 + 台账必须用原子语句读数（未合规即红）")
class StockDeductionAndLedgerAtomicityMetaGuardTest {

    /** 模块根（Surefire 的工作目录 = {@code backend/admin-api}）。 */
    private static final String MODULE = "backend/admin-api";
    private static final String MAIN = MODULE + "/src/main/java/com/migao/admin";
    private static final String MAPPER_DIR = MAIN + "/mapper";
    private static final String SERVICE_DIR = MAIN + "/service";

    private static final String PRODUCT_SKU_MAPPER = MAPPER_DIR + "/ProductSkuMapper.java";
    private static final String ORDER_SERVICE = SERVICE_DIR + "/OrderService.java";
    private static final String INBOUND_ORDER_SERVICE = SERVICE_DIR + "/InboundOrderService.java";
    private static final String STOCK_CHANGE = SERVICE_DIR + "/StockChange.java";

    /** 本单的两个核心对象（缺一 ⇒ 判据失明，当场红）。 */
    private static final String TARGET_DEDUCT_MAPPER = "ProductSkuMapper.java#deductStock";

    // ────────────────────────────────────────────── 形态

    /** SET 子句（`UPDATE x SET … ` 到 `WHERE` 之间）—— 只在这一段上判「加减」，免得被 RETURNING 里的算式误判。 */
    private static final Pattern SET_CLAUSE = Pattern.compile(
            "(?i)\\bSET\\b(.*?)\\bWHERE\\b", Pattern.DOTALL);
    /** SET 子句里「stock = … - …」= 扣减型入口（现取，不写死方法名表）。 */
    private static final Pattern DEDUCT_STOCK_WRITE = Pattern.compile(
            "stock\\s*=\\s*[^;]*?\\s-\\s*\\#\\{", Pattern.CASE_INSENSITIVE);
    /** 受影响行数的判定（本单新形态下「0 行」表现为返回 null，故 null 判定同样算）。 */
    private static final Pattern ROWCOUNT_CHECK = Pattern.compile("==\\s*0|!=\\s*0|<\\s*1|>\\s*0|==\\s*null|!=\\s*null");
    /** 快照读属性（`X.getStock()`）—— 落台账时**不得**用它当 before/after。 */
    private static final Pattern SNAPSHOT_READ = Pattern.compile("\\.getStock\\s*\\(\\s*\\)");
    /** 原子取值锚：一条 SQL 同时取「变更前/变更后」。 */
    private static final String ATOMIC_SQL_ANCHOR = "RETURNING";
    /** 声明式锚（方法体注释里逐字写出）—— 给「原子取值发生在被调方」的方法用。 */
    private static final String ATOMIC_PRAGMA = "atomic-ledger: true";
    private static final Pattern RECORD_CALL = Pattern.compile("(?<!\\w)record\\s*\\(");
    /** 落台账的库存变更方法（现取：方法名带库存变更/落台账语义）。 */
    private static final Pattern LEDGER_METHOD = Pattern.compile(
            "(deductSkuStock|restoreSkuStock|recordAtomicStockChange|post)\\s*\\(");

    // ────────────────────────────────────────────── 判据 1~3：真语料

    @Test
    @DisplayName("判据 1+2+3：扣减入口必须同时有「下限谓词」「不钳 0」「0 行被处理」（清单现取）")
    void everyStockDeductionHasLowerBoundPredicate() throws IOException {
        Path root = repoRoot();
        List<MapperMethod> writes = collectStockDeductMethods(root.resolve(MAPPER_DIR));
        Set<String> deductNames = new LinkedHashSet<>();
        List<String> violations = new ArrayList<>();
        for (MapperMethod m : writes) {
            deductNames.add(m.display());
            violations.addAll(deductViolations(m.sql(), m.display()));
        }
        // 调用方必须看受影响行数（0 行 / null = 库存不够 ⇒ 必须显式失败，不许静默继续）
        for (Path service : serviceSources(root)) {
            for (MapperMethod m : writes) {
                if (!read(service).contains(m.name() + "(")) {
                    continue;
                }
                for (String body : methodBodiesContaining(read(service), m.name() + "(")) {
                    if (!ROWCOUNT_CHECK.matcher(body).find()) {
                        violations.add(service.getFileName() + " 里调用 " + m.name()
                                + " 的方法体没有受影响行数判定（0 行会被当成扣成功）");
                    }
                }
            }
        }

        System.out.println("[#6299/#6300 类级守卫] 现取扣减入口=" + deductNames
                + " 服务侧扫描面=" + serviceSources(root).size() + " 个文件");

        assertThat(deductNames).as("扫描器必须真的看见本单的核心对象（形态被改名 ⇒ 判据失明要当场暴露）")
                .contains(TARGET_DEDUCT_MAPPER);
        assertThat(violations).as("每个扣库存入口都必须带下限谓词、不钳 0、且调用方看受影响行数").isEmpty();
    }

    @Test
    @DisplayName("判据 4+5：落台账的库存变更方法必须用原子取值（禁快照读）；两个本单对象逐条钉住")
    void ledgerBeforeAfterComeFromAtomicStatement() throws IOException {
        Path root = repoRoot();
        List<MapperMethod> atomicMappers = collectStockDeductMethods(root.resolve(MAPPER_DIR)).stream()
                .filter(m -> m.sql().toUpperCase().contains(ATOMIC_SQL_ANCHOR))
                .toList();

        List<String> violations = new ArrayList<>();
        Set<String> checked = new LinkedHashSet<>();
        for (Path service : List.of(root.resolve(ORDER_SERVICE), root.resolve(INBOUND_ORDER_SERVICE))) {
            String source = read(service);
            List<String> bodies = ledgerEntryBodies(source);
            if (bodies.isEmpty()) {
                violations.add(service.getFileName().toString() + " 里找不到任何落台账的库存变更方法（扫描器失明）");
            }
            for (String body : bodies) {
                checked.add(service.getFileName().toString() + "::" + bodyName(body));
                violations.addAll(ledgerViolations(service.getFileName().toString(), body));
            }
        }

        System.out.println("[#6299/#6300 类级守卫] 现取含原子取值的写面=" + atomicMappers.stream()
                .map(MapperMethod::display).toList() + " 落台账库存变更方法=" + checked);

        assertThat(checked).as("扫描器必须真的看见两个本单对象（改名/挪位置 ⇒ 判据失明要当场暴露）")
                .anySatisfy(s -> assertThat(s).contains("InboundOrderService.java"))
                .anySatisfy(s -> assertThat(s).contains("OrderService.java"));
        assertThat(violations).as("台账 before/after 必须来自原子语句（快照读 = 并发下同基、链断裂）").isEmpty();
        assertThat(atomicMappers).as("必须至少有一个写面用 RETURNING 取「变更前/变更后」（否则上面那条判据无从谈起）")
                .isNotEmpty();
    }

    @Test
    @DisplayName("判据 5（本单的钉）：deductStock 写面含下限谓词 + RETURNING + 无 GREATEST；台账不再走快照")
    void coreDeductSqlIsConditionalAndReturnsBeforeAfter() throws IOException {
        Path root = repoRoot();
        List<MapperMethod> writes = collectStockDeductMethods(root.resolve(MAPPER_DIR));
        List<MapperMethod> deductSql = writes.stream()
                .filter(m -> m.name().startsWith("deductStock"))
                .toList();

        assertThat(deductSql).as("ProductSkuMapper 必须有 deductStock 写面（改名 ⇒ 判据失明）").isNotEmpty();
        for (MapperMethod m : deductSql) {
            System.out.println("[#6299/#6300 类级守卫] deductStock 写面 SQL = " + m.sql());
            assertThat(m.sql()).as("判断与写入必须同一条语句：WHERE … AND COALESCE(stock, 0) >= #{quantity}")
                    .contains("COALESCE(stock, 0) >= #{quantity}");
            assertThat(m.sql()).as("必须 RETURNING 回「变更前/变更后」，台账才可能链式相接")
                    .contains(ATOMIC_SQL_ANCHOR);
            assertThat(m.sql().toUpperCase()).as("GREATEST 钳 0 已删除（它掩盖超扣）").doesNotContain("GREATEST");
        }

        String orderService = read(root.resolve(ORDER_SERVICE));
        assertThat(codeOnly(orderService)).as("订单扣减入口必须由 SQL 的返回值落台账（不再读快照）")
                .doesNotContain("snapshotForLedger");
        assertThat(orderService).as("台账读数必须来自唯一入口 recordAtomicStockChange（它带 atomic-ledger 声明）")
                .contains("recordAtomicStockChange");
        assertThat(orderService).as("落台账必须直接用原子语句给出的 StockChange，而不是自己读库存")
                .contains("StockChange.from(productSkuMapper.deductStock(");

        String inbound = read(root.resolve(INBOUND_ORDER_SERVICE));
        assertThat(inbound).as("入库过账的台账 before/after 必须来自 receiveStock 的 RETURNING")
                .contains("StockChange.from(productSkuMapper.receiveStock(");

        String stockChange = read(root.resolve(STOCK_CHANGE));
        assertThat(stockChange).as("StockChange 只能由 mapper 的 RETURNING 行映射构造（类型上堵死「从读快照构造」）")
                .contains("static StockChange from(Map<String, Object> row)");
        assertThat(stockChange).as("StockChange 不得提供读快照的构造入口")
                .doesNotContain(ATOMIC_SQL_ANCHOR + "SNAPSHOT", "selectById");
    }

    // ────────────────────────────────────────────── 判据 6：判别力自证（合成语料）

    @Test
    @DisplayName("判据 6·判别力自证：四种坏形态在合成语料上各自判红；合规语料不红")
    void guardHasDiscriminatingPower() {
        String compliantSql = "UPDATE product_skus SET stock = stock - #{quantity} "
                + "WHERE id = #{skuId} AND COALESCE(stock, 0) >= #{quantity} RETURNING stock";
        String badPredicateSql = "UPDATE product_skus SET stock = stock - #{quantity} "
                + "WHERE id = #{skuId} RETURNING stock";
        String clampedSql = "UPDATE product_skus SET stock = GREATEST(COALESCE(stock, 0) - #{quantity}, 0) "
                + "WHERE id = #{skuId} AND COALESCE(stock, 0) >= #{quantity} RETURNING stock";

        assertThat(deductViolations(compliantSql, "合成.合规")).as("合规语料不得判红（否则每次改动都会被自己的文案喂红）")
                .isEmpty();
        assertThat(deductViolations(badPredicateSql, "合成.无谓词")).as("坏形态 ①：无下限谓词 ⇒ 必须红").isNotEmpty();
        assertThat(deductViolations(clampedSql, "合成.钳0")).as("坏形态 ②：GREATEST 钳 0 ⇒ 必须红").isNotEmpty();

        String goodCaller = "    private void deductSkuStock(OrderItem item) {\n"
                + "        Map<String, Object> r = productSkuMapper.deductStock(1L, qty);\n"
                + "        if (r == null) {\n"
                + "            throw BusinessException.validationError(\"库存不足\");\n"
                + "        }\n"
                + "    }\n";
        String badCaller = "    private void deductSkuStock(OrderItem item) {\n"
                + "        productSkuMapper.deductStock(1L, qty);\n"
                + "    }\n";
        assertThat(rowcountViolations(goodCaller, "deductStock")).as("合规调用方不得判红").isEmpty();
        assertThat(rowcountViolations(badCaller, "deductStock")).as("坏形态 ③：0 行未处理 ⇒ 必须红").isNotEmpty();

        String goodLedger = "    private void recordAtomicStockChange(StockChange change) {\n"
                + "        // atomic-ledger: true\n"
                + "        stockLedgerService.record(1L, p, id, c, change.beforeQuantity(), change.afterQuantity(),"
                + " \"inbound\", no, n);\n"
                + "    }\n";
        String badLedger = "    private void recordAtomicStockChange(Long id, BigDecimal qty) {\n"
                + "        BigDecimal beforeQty = productSkuMapper.selectById(id).getStock();\n"
                + "        stockLedgerService.record(1L, p, id, c, beforeQty, beforeQty.add(qty), \"inbound\", no, n);\n"
                + "    }\n";
        assertThat(ledgerViolations("Good.java", goodLedger)).as("合规台账写法不得判红").isEmpty();
        assertThat(ledgerViolations("Bad.java", badLedger))
                .as("坏形态 ④：before/after 读自快照 ⇒ 必须红").isNotEmpty();
    }

    // ────────────────────────────────────────────── 判定本体（真语料与合成语料**同一套**）

    /** 扣减写面的两条纪律（真语料给整条 SQL，合成语料给片段 —— 同一套判定）。 */
    private static List<String> deductViolations(String sql, String display) {
        Matcher set = SET_CLAUSE.matcher(sql);
        String clause = set.find() ? set.group(1) : sql;
        List<String> violations = new ArrayList<>();
        if (!sql.contains(">=")) {
            violations.add(display + " 无下限谓词（并发下会扣成负数 / 需靠 GREATEST 钳 0 掩盖）");
        }
        if (sql.toUpperCase().contains("GREATEST")) {
            violations.add(display + " 用了 GREATEST 钳 0 —— 把「扣不动」静默变成「扣到 0」");
        }
        return violations;
    }

    /** 调用方纪律：方法体里出现该 mapper 调用时，必须有受影响行数判定。 */
    private static List<String> rowcountViolations(String serviceSource, String mapperMethod) {
        List<String> violations = new ArrayList<>();
        for (String body : methodBodiesContaining(serviceSource, mapperMethod + "(")) {
            if (!ROWCOUNT_CHECK.matcher(body).find()) {
                violations.add("调用 " + mapperMethod + " 却未判受影响行数");
            }
        }
        return violations;
    }

    /** 台账纪律：一次 {@code record(} 调用的 before/after 不得读自快照，且所在方法体要有原子锚。 */
    private static List<String> ledgerViolations(String fileName, String methodBody) {
        List<String> violations = new ArrayList<>();
        String atomic = methodBody.contains(ATOMIC_PRAGMA) ? ATOMIC_PRAGMA
                : (methodBody.contains(ATOMIC_SQL_ANCHOR) ? ATOMIC_SQL_ANCHOR : null);
        boolean sawRecord = false;
        for (String call : recordCalls(methodBody)) {
            sawRecord = true;
            if (SNAPSHOT_READ.matcher(call).find()) {
                violations.add(fileName + " 的台账行 before/after 读自快照：" + oneLine(call));
            }
        }
        if (sawRecord && atomic == null) {
            violations.add(fileName + " 的落台账方法体里没有原子取值锚（RETURNING / " + ATOMIC_PRAGMA + "）");
        }
        return violations;
    }

    // ────────────────────────────────────────────── 解析工具

    private record MapperMethod(String sourceFile, String name, String sql) {
        String display() {
            return sourceFile + "#" + name;
        }
    }

    /** 扫 mapper 目录，取所有「写 product_skus.stock 且是减法（扣减）」的方法及其 SQL 文本。 */
    private static List<MapperMethod> collectStockDeductMethods(Path mapperDir) throws IOException {
        assertThat(mapperDir).as("mapper 扫描面必须真实存在（路径漂移 ⇒ 判红，不是空跑通过）").exists();
        List<MapperMethod> found = new ArrayList<>();
        for (Path file : javaFiles(mapperDir)) {
            for (MapperMethod m : mapperMethods(read(file))) {
                if (isStockDeduct(m.sql())) {
                    found.add(new MapperMethod(file.getFileName().toString(), m.name(), m.sql()));
                }
            }
        }
        return found;
    }

    /** 该写面是否为「扣减」：只在 SET 子句里判 `stock = … - …`（RETURNING 里的算式不算）。 */
    private static boolean isStockDeduct(String sql) {
        Matcher set = SET_CLAUSE.matcher(sql);
        String clause = set.find() ? set.group(1) : sql;
        return DEDUCT_STOCK_WRITE.matcher(clause).find();
    }

    /**
     * 从源码里抽出 {@code @Update/@Select} 注解方法的「方法名 + SQL 文本」。
     * SQL 文本 = 注解括号内所有字面量拼接（与 {@code OrderAutoCompleteSqlGuardTest} 同款抽取口径）。
     */
    private static List<MapperMethod> mapperMethods(String source) {
        List<MapperMethod> methods = new ArrayList<>();
        Matcher annotation = Pattern.compile("@(Update|Select)\\s*\\(").matcher(source);
        while (annotation.find()) {
            int start = annotation.end() - 1;
            int end = matchingParen(source, start);
            if (end < 0) {
                continue;
            }
            String sql = literalsOf(source.substring(start, end));
            // 方法名：注解之后第一处**行首**声明处的标识符 —— 声明可能跨行（`Map<String, Object>\n deductStock(`），
            // 故取「行首非注解内容」到「第一个 `(`」之间最后一段标识符；注解尾巴（@InterceptorIgnore(...)）被
            // 字符类排除（它含 `=` / `"`）。
            String tail = source.substring(end, Math.min(source.length(), end + 400));
            Matcher decl = Pattern.compile("(?m)^\\s*(?:@[^\\n]*\\n\\s*)*([\\w$<>,.\\[\\]\\s]+?)\\s*\\(")
                    .matcher(tail);
            if (decl.find()) {
                String signature = decl.group(1).trim();
                Matcher word = Pattern.compile("([\\w$]+)\\s*$").matcher(signature);
                if (word.find()) {
                    methods.add(new MapperMethod("<synthetic>", word.group(1), sql));
                }
            }
        }
        return methods;
    }

    private static String literalsOf(String block) {
        StringBuilder sql = new StringBuilder();
        Matcher literals = Pattern.compile("\"((?:[^\"\\\\]|\\\\.)*)\"").matcher(block);
        while (literals.find()) {
            sql.append(literals.group(1)).append(' ');
        }
        return sql.toString().trim();
    }

    /**
     * 现取「落台账的库存变更」方法体（不写死表）：方法名带库存变更/落台账语义，且体内出现
     * 落台账调用或 {@link #ATOMIC_PRAGMA} 声明。订单腿的落台账调用在私有助手
     * {@code recordAtomicStockChange} 里，故方法名锚也认它（跨文件通吃）。
     */
    private static List<String> ledgerEntryBodies(String source) {
        List<String> bodies = new ArrayList<>();
        Matcher m = LEDGER_METHOD.matcher(source);
        while (m.find()) {
            int brace = source.indexOf('{', m.end());
            if (brace < 0) {
                continue;
            }
            int close = matchingBrace(source, brace);
            if (close < 0) {
                continue;
            }
            String body = source.substring(m.start(), close + 1);
            if (RECORD_CALL.matcher(body).find() || body.contains(ATOMIC_PRAGMA)) {
                bodies.add(body);
            }
        }
        return bodies;
    }

    private static String bodyName(String body) {
        Matcher m = Pattern.compile("^\\s*(?:\\w+\\s+)*(\\w+)\\s*\\(").matcher(body);
        return m.find() ? m.group(1) : oneLine(body);
    }

    /**
     * 剥掉块注释与行注释后再判（否则注释里提一句禁词就能把判据喂红/喂绿 —— 本仓
     * {@code migao-dev-flow} §17.3「判据被自己的文案喂红」同族）。
     * 例外：{@link #ATOMIC_PRAGMA} 本身就是**注释形态的声明**，故判定前先把它换成哨兵。
     */
    private static String codeOnly(String source) {
        return source.replace(ATOMIC_PRAGMA, "ATOMIC_LEDGER_PRAGMA")
                .replaceAll("(?s)/\\*.*?\\*/", "")
                .replaceAll("(?m)//.*$", "")
                .replace("ATOMIC_LEDGER_PRAGMA", ATOMIC_PRAGMA);
    }

    private static String trimLines(String text) {
        return text.lines().map(String::trim).collect(java.util.stream.Collectors.joining("\n"));
    }

    private static int matchingParen(String text, int openIndex) {
        return matchingDelimiter(text, openIndex, '(', ')');
    }

    private static int matchingBrace(String text, int openIndex) {
        return matchingDelimiter(text, openIndex, '{', '}');
    }

    private static int matchingDelimiter(String text, int openIndex, char open, char close) {
        int depth = 0;
        boolean inString = false;
        boolean inChar = false;
        for (int i = openIndex; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c == '\\') {
                i++;
                continue;
            }
            if (inString || inChar) {
                if (inString && c == '"') {
                    inString = false;
                } else if (inChar && c == '\'') {
                    inChar = false;
                }
                continue;
            }
            if (c == '"') {
                inString = true;
                continue;
            }
            if (c == '\'') {
                inChar = true;
                continue;
            }
            if (c == open) {
                depth++;
            } else if (c == close) {
                depth--;
                if (depth == 0) {
                    return i;
                }
            }
        }
        return -1;
    }

    /** 取出含指定锚的「方法体」（锚前回退到声明起点，锚后按花括号配平到方法结束）。 */
    /**
     * 取含指定锚的<b>最小包围方法体</b>：先把源码里所有「{…}」配对区间摊平，再对每个锚选包含它的最小区间。
     * <b>不用启发式找声明行</b>（那个写法在「锚落在形参里」与「锚落在方法体里」两种形态下会取错区间，
     * 本单实测踩过），配平区间是结构事实。
     */
    private static List<String> methodBodiesContaining(String source, String anchor) {
        String text = trimLines(source);
        List<int[]> spans = new ArrayList<>();
        for (int i = 0; i < text.length(); i++) {
            if (text.charAt(i) != '{') {
                continue;
            }
            int close = matchingBrace(text, i);
            if (close > i) {
                spans.add(new int[]{i, close});
            }
        }
        List<String> bodies = new ArrayList<>();
        Matcher m = Pattern.compile(Pattern.quote(anchor)).matcher(text);
        while (m.find()) {
            int[] best = null;
            for (int[] span : spans) {
                if (span[0] >= m.start() || span[1] <= m.end()) {
                    continue;
                }
                if (best == null || span[1] - span[0] < best[1] - best[0]) {
                    best = span;
                }
            }
            if (best != null) {
                bodies.add(text.substring(best[0], best[1] + 1));
            }
        }
        return bodies;
    }

    private static List<String> recordCalls(String text) {
        List<String> calls = new ArrayList<>();
        Matcher m = RECORD_CALL.matcher(text);
        while (m.find()) {
            int close = matchingParen(text, m.end() - 1);
            if (close > 0) {
                calls.add(text.substring(m.start(), close + 1));
            }
        }
        return calls;
    }

    private static List<Path> serviceSources(Path root) throws IOException {
        assertThat(root.resolve(SERVICE_DIR)).as("service 扫描面必须真实存在").exists();
        return javaFiles(root.resolve(SERVICE_DIR));
    }

    private static List<Path> javaFiles(Path dir) throws IOException {
        try (Stream<Path> walk = Files.walk(dir)) {
            return walk.filter(p -> p.toString().endsWith(".java")).sorted().toList();
        }
    }

    private static String read(Path path) throws IOException {
        assertThat(path).as("判据的扫描面必须真实存在（路径漂移 ⇒ 判红，不是空跑通过）").exists();
        return Files.readString(path, StandardCharsets.UTF_8);
    }

    private static String oneLine(String text) {
        String flat = text.replaceAll("\\s+", " ").trim();
        return flat.length() > 140 ? flat.substring(0, 140) + "…" : flat;
    }

    private static Path repoRoot() {
        Path root = Path.of(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve(MODULE + "/pom.xml"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 " + MODULE + "/pom.xml（否则判据会空跑）").isNotNull();
        return root;
    }
}
