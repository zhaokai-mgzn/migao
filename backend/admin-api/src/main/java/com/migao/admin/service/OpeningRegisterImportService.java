package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.InboundOrderCreateRequest;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.dto.OpeningImportReport;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductSkuMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.CellStyle;
import org.apache.poi.ss.usermodel.Font;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.usermodel.WorkbookFactory;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * 期初建账（批次建账/初始化入口）的 **Excel 批量导入器**（issue #5153）。
 *
 * <h2>这个类只做三件事，且**一行库存都不自己写**</h2>
 * <ol>
 *   <li><b>解析</b>（POI 已在 admin-api 的依赖里，同族先例 {@code ProductService.importProducts}）；
 *   </li>
 *   <li><b>逐行校验并出报告</b> —— 数值判据**不在这里重写**，一律调
 *       {@link InboundOrderService#requireItemNumbers}（全仓唯一一处：下限 + 1 位小数 + 单价）；</li>
 *   <li><b>调服务层</b> {@code create} + {@code post} 把整批落成一张**期初入库单**。</li>
 * </ol>
 *
 * <h2>🔴 为什么必须走服务层（#5149 §3.6.3 的显式禁令，不是风格偏好）</h2>
 * {@code stock_batches.quantity} 是 {@code NUMERIC(12,1)}，PG 对**超过 scale 的写入按四舍五入
 * 落库且不报错**（{@code 2.75} → {@code 2.8}；V115 与 {@link StockQuantity} 的 javadoc 都逐字登记过）。
 * ⇒ 一个「自己读单元格、自己换算、直写 SQL」的导入器 = **静默截断/虚增，且没有任何东西会因此变红**。
 * 本类的机械判据（`tests/unit_ci_workflows/test_inbound_opening_register.py` 用**去注释后的源码**断言）：
 * 本文件里**不得**出现 {@code setScale} / {@code RoundingMode} / {@code toStockScaleByCeiling} /
 * {@code intValue()} / {@code (long)} / {@code getNumericCellValue} —— 只把**原始值**交给服务层。
 *
 * <h2>🔴 为什么不用订单侧的 {@code toStockScaleByCeiling} 归一（#5149 §3.6.2）</h2>
 * 那是**订单侧**口径（向上进位，模拟裁床用料）。期初/批次余量属**库存类输入** ⇒ 用它每条最多
 * 虚增 {@code +0.099m} = **系统性虚增资产**（用户裁定「不能损失客户」）。误用会被真库判据的
 * 注入式红证测出来：`2.71` 走进位方向得 `2.8`，比四舍五入方向多 `0.1` 米/条。
 *
 * <h2>为什么复用 `source='opening'` / `import_run_id` 而不新造</h2>
 * 两者都是 V117（issue #5148）已落好的既有件（列 + 唯一索引 + CHECK 约束）⇒ 本类只**用**它们：
 * 期初批次因此与正常入库批次**字段面逐字一致**（后续派工扣减 / 余量 / 分布 / 对账零特例分支），
 * 且同一份导入重跑**不会**建出第二张单（两张都过账 = 库存加两次）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OpeningRegisterImportService {

    /**
     * 模板列序（A~F）—— 表头的**首行**与 {@link #parseRows} 的列下标**同源**（改这里就同时改了
     * 模板与解析，不会出现「模板多一列、解析少一列」的静默错位）。
     *
     * <p>列面只覆盖**建账必需 + 旧系统可带过来的事实**：货号（挂到 SKU 上）、剩余米数、
     * 缸号、旧系统批次号、入库单价、备注。**覆盖不到的**（如实登记）：原始入库量 / 原始入库日期
     * （见 V118 文件头「有损项」）、每卷米数、仓库、供应商（期初单是整单级字段，可用建单接口补填）。</p>
     */
    static final List<String> HEADERS =
            List.of("货号*", "剩余米数*", "缸号", "旧系统批次号", "入库单价", "备注");

    private static final int COL_SKU_CODE = 0;
    private static final int COL_QUANTITY = 1;
    private static final int COL_DYE_LOT = 2;
    private static final int COL_LEGACY_NO = 3;
    private static final int COL_UNIT_COST = 4;
    private static final int COL_REMARK = 5;

    /** {@code inbound_orders.import_run_id} 是 {@code VARCHAR(128)} —— 超长当场拒绝，不把 DB 的 22001 透传成 500 */
    private static final int MAX_RUN_ID = 128;

    private final InboundOrderService inboundOrderService;
    private final ProductSkuMapper productSkuMapper;

    // ============================================================ 模板

    /**
     * 建账模板（.xlsx）：第 1 个工作表 = 表头**且只有表头**（不放示例行 —— 示例行会和真数据一样
     * 被解析成批次，那是「下载模板原样上传就建出一批假账」）；第 2 个工作表 = 填写说明。
     */
    public byte[] template() {
        try (Workbook workbook = new XSSFWorkbook()) {
            Sheet sheet = workbook.createSheet("期初建账");
            CellStyle bold = workbook.createCellStyle();
            Font font = workbook.createFont();
            font.setBold(true);
            bold.setFont(font);
            Row header = sheet.createRow(0);
            for (int i = 0; i < HEADERS.size(); i++) {
                Cell cell = header.createCell(i);
                cell.setCellValue(HEADERS.get(i));
                cell.setCellStyle(bold);
                sheet.setColumnWidth(i, 20 * 256);
            }
            Sheet notes = workbook.createSheet("填写说明");
            String[] lines = {
                    "① 一行 = 一个批次（= 一个 SKU + 一批布）。同一个货号有多批，就写多行。",
                    "② 货号*：必填，商品 SKU 的货号（本租户内必须唯一对应一个 SKU）。",
                    "③ 剩余米数*：必填，填**现在实物还剩多少米**（不是当初进了多少米）；最多 1 位小数，"
                            + "如 0.5 可以、2.755 不行（系统不做静默取整）。",
                    "④ 缸号 / 旧系统批次号：可空，都是**外部事实**，原样登记（旧系统批次号不会冒充系统批次号）。",
                    "⑤ 入库单价：可空；留空 = 这批布料成本未知（数量照记，不猜 0）。",
                    "⑥ 整份文件**全或无**：只要有 1 行不通过，就一行都不建账；按报告改好后用"
                            + "**同一次导入标识**重跑即可，不会重复建账。",
            };
            for (int i = 0; i < lines.length; i++) {
                notes.createRow(i).createCell(0).setCellValue(lines[i]);
            }
            notes.setColumnWidth(0, 100 * 256);
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            workbook.write(out);
            return out.toByteArray();
        } catch (Exception e) {
            throw BusinessException.validationError("生成建账模板失败：" + e.getMessage());
        }
    }

    // ============================================================ 导入

    /**
     * 批量建账：解析 → 逐行校验 → **全或无**建单 → 过账。
     *
     * <p><b>必须带 {@code importRunId}</b>（fail-closed）：没有幂等键就不许上批量导入 ——
     * 重跑（网络重试 / 双击 / 刷新后重交）会建出第二张单，两张都过账就是**库存加两次**。</p>
     */
    public OpeningImportReport importOpening(MultipartFile file, String importRunId,
                                             Long tenantId, String operator) {
        String runId = requireRunId(importRunId);
        if (file == null || file.isEmpty()) {
            throw BusinessException.validationError("请选择要导入的 Excel 文件（.xlsx，可用「下载模板」得到）");
        }
        List<OpeningImportReport.Row> rows = parseRows(file, tenantId);
        OpeningImportReport report = new OpeningImportReport(runId, rows);

        if (rows.isEmpty()) {
            report.setMessage("文件里没有数据行（第 1 行是表头）—— 请用「下载模板」得到的模板填写后重试");
            return report;
        }
        if (report.getFailCount() > 0) {
            // 全或无：一行不通过 ⇒ 一行都不写（部分成功会让「修好后重跑」变成重复建账，见 DTO javadoc）
            report.setMessage("共 " + report.getTotal() + " 行，" + report.getFailCount()
                    + " 行未通过校验 ⇒ **未建账**（一行都没写、库存一分未动）—— "
                    + "按下面逐行原因改好后，用**同一次导入标识**重跑即可");
            log.info("期初建账导入校验未通过，未建账: tenant={}, importRunId={}, total={}, fail={}",
                    tenantId, runId, report.getTotal(), report.getFailCount());
            return report;
        }

        InboundOrderCreateRequest req = new InboundOrderCreateRequest();
        req.setSource(InboundOrder.SOURCE_OPENING);
        req.setImportRunId(runId);
        req.setRemark("期初建账（批次初始化导入）");
        req.setItems(rows.stream().map(OpeningRegisterImportService::toItem).toList());

        InboundOrderResponse order = inboundOrderService.create(req, tenantId, operator);
        report.setOrderId(order.getId());
        report.setInboundNo(order.getInboundNo());
        report.setStatus(order.getStatus());

        if (InboundOrder.STATUS_POSTED.equals(order.getStatus())) {
            // 幂等命中：这次运行**早已**建账过账过（`create` 直接返回既有那张）
            report.setCreated(false);
            report.setMessage("这次导入运行已经建过账（单号 " + order.getInboundNo()
                    + "）—— 幂等命中：**没有**重复建单、**没有**重复加库存（这是重跑的正确结果）");
            log.info("期初建账重跑命中既有单据（未重复加库存）: tenant={}, importRunId={}, inboundNo={}",
                    tenantId, runId, order.getInboundNo());
            return report;
        }
        if (!InboundOrder.STATUS_DRAFT.equals(order.getStatus())) {
            // 既有草稿被作废 ⇒ 不能原地复活（V111：冲销走新单据，不删/不改历史）
            throw BusinessException.conflict(
                    "这次导入运行的单据（单号 " + order.getInboundNo() + "）状态为「" + order.getStatus()
                            + "」，不能继续建账",
                    "已作废的导入运行不可复用：请用**新的**导入标识重新导入（作废单不再被改写）");
        }

        InboundOrderResponse posted = inboundOrderService.post(order.getId(), tenantId, operator);
        report.setCreated(true);
        report.setStatus(posted.getStatus());
        report.setMessage("已建账并过账：单号 " + posted.getInboundNo() + "，共 " + report.getTotal()
                + " 个批次（库存已加、批次号已生成、旧系统批次号已登记）");
        log.info("期初建账完成: tenant={}, importRunId={}, inboundNo={}, rows={}, operator={}",
                tenantId, runId, posted.getInboundNo(), report.getTotal(), operator);
        return report;
    }

    /** 明细行 = 报告行里已校验通过的字段（数值**原样**交给服务层，导入器不做任何归一） */
    private static InboundOrderCreateRequest.Item toItem(OpeningImportReport.Row row) {
        InboundOrderCreateRequest.Item item = new InboundOrderCreateRequest.Item();
        item.setProductId(row.getProductId());
        item.setSkuId(row.getSkuId());
        item.setQuantity(row.getQuantity());
        item.setUnitCost(row.getUnitCost());
        item.setDyeLot(row.getDyeLot());
        item.setLegacyBatchNo(row.getLegacyBatchNo());
        return item;
    }

    /**
     * 幂等键准入：空白 ⇒ 拒（**没有幂等键就不许上批量导入**）。
     *
     * <p>超长也拒：{@code import_run_id} 是 {@code VARCHAR(128)}，让 DB 的 22001 冒成 500
     * 对用户毫无可行动信息。</p>
     */
    private static String requireRunId(String importRunId) {
        String value = StringUtils.hasText(importRunId) ? importRunId.trim() : null;
        if (value == null) {
            throw BusinessException.validationError(
                    "批量建账必须带「导入标识」（幂等键）：重跑同一份文件时，同一个标识只会建一次账");
        }
        if (value.length() > MAX_RUN_ID) {
            throw BusinessException.validationError(
                    "导入标识过长（最多 " + MAX_RUN_ID + " 字符），当前 " + value.length() + " 字符");
        }
        return value;
    }

    // ============================================================ 解析

    private List<OpeningImportReport.Row> parseRows(MultipartFile file, Long tenantId) {
        try (Workbook workbook = WorkbookFactory.create(file.getInputStream())) {
            Sheet sheet = workbook.getSheetAt(0);
            if (sheet == null || sheet.getLastRowNum() < 1) {
                return List.of();
            }
            Row header = sheet.getRow(sheet.getFirstRowNum());
            String firstHeader = header == null ? null : cellText(header, COL_SKU_CODE);
            if (firstHeader == null || !firstHeader.contains("货号")) {
                // 防「上传了别的表」（商品导入表 / 随便一个 xlsx）：列错位会静默把数字填到错误的语义上
                throw BusinessException.validationError(
                        "表头第一列必须是「货号」（当前：" + firstHeader + "）—— "
                                + "请用「下载模板」得到的模板填写");
            }
            List<OpeningImportReport.Row> rows = new ArrayList<>();
            for (int i = sheet.getFirstRowNum() + 1; i <= sheet.getLastRowNum(); i++) {
                Row row = sheet.getRow(i);
                if (row == null || isBlankRow(row)) {
                    continue;
                }
                rows.add(parseRow(row, i + 1, tenantId));
            }
            return rows;
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.warn("解析期初建账 Excel 失败: {}", e.getMessage());
            throw BusinessException.validationError(
                    "解析 Excel 失败（请用 .xlsx 模板，且不要改动表头）：" + e.getMessage());
        }
    }

    private OpeningImportReport.Row parseRow(Row row, int rowNo, Long tenantId) {
        OpeningImportReport.Row out = new OpeningImportReport.Row();
        out.setRowNo(rowNo);
        String skuCode = cellText(row, COL_SKU_CODE);
        String dyeLot = cellText(row, COL_DYE_LOT);
        String legacyNo = cellText(row, COL_LEGACY_NO);
        String quantityText = cellText(row, COL_QUANTITY);
        String unitCostText = cellText(row, COL_UNIT_COST);
        out.setSkuCode(skuCode);
        out.setDyeLot(dyeLot);
        out.setLegacyBatchNo(legacyNo);

        if (skuCode == null) {
            out.fail("货号不能为空（批次必须挂在 SKU 上）");
            return out;
        }
        List<ProductSku> skus = productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .eq(ProductSku::getSkuCode, skuCode));
        if (skus == null || skus.isEmpty()) {
            out.fail("货号「" + skuCode + "」在本租户下不存在（批次必须挂在已存在的 SKU 上）");
            return out;
        }
        if (skus.size() > 1) {
            out.fail("货号「" + skuCode + "」在本租户下对应 " + skus.size()
                    + " 个 SKU，无法唯一确定 —— 请联系管理员核对货号");
            return out;
        }
        ProductSku sku = skus.get(0);
        out.setSkuId(sku.getId());
        out.setProductId(sku.getProductId());

        BigDecimal quantity;
        BigDecimal unitCost;
        try {
            quantity = decimalOrNull(quantityText, "剩余米数");
            unitCost = decimalOrNull(unitCostText, "入库单价");
        } catch (NumberFormatException e) {
            out.fail("第 " + rowNo + " 行" + e.getMessage());
            return out;
        }
        try {
            // 数值判据**只有一处**（`InboundOrderService.requireItemNumbers`）：下限 > 0 米 +
            // 最多 1 位小数（超 1 位小数**显式拒绝**）+ 单价 > 0。这里不复制任何一条口径。
            out.setQuantity(InboundOrderService.requireItemNumbers(quantity, unitCost,
                    "第 " + rowNo + " 行剩余米数", "第 " + rowNo + " 行入库单价"));
        } catch (BusinessException e) {
            out.fail(e.getMessage());
            return out;
        }
        out.setUnitCost(unitCost);
        out.setOk(true);
        return out;
    }

    /** 空/形如 {@code "12.5"} 的小数字符串；空白 ⇒ {@code null}（缺失与 0 不是一回事） */
    private static BigDecimal decimalOrNull(String text, String label) {
        if (text == null) {
            return null;
        }
        try {
            return new BigDecimal(text);
        } catch (NumberFormatException e) {
            // 抛出时把「是哪个字段、原文是什么」带上，报告里才有可行动信息
            throw new NumberFormatException(label + "「" + text + "」不是数字");
        }
    }

    /**
     * 单元格 → **原始文本**。
     *
     * <p>⚠️ 数值单元格**不走** {@code double}：{@code getNumericCellValue()} 是 {@code double}，
     * 再 {@code (long)} 一截就把 {@code 0.5} 变成 {@code 0}（同族缺陷见
     * {@code ProductService} 里 Excel 库存那句「`(int) getCellNumericValue` 把 60.5 截成 60
     * 且不留痕迹」的登记）。这里用 {@link BigDecimal#valueOf(double)} 的十进制定点表示
     * （{@code 2.75} → {@code "2.75"}），**保留用户真正填进去的位数**，好让服务层的精度闸门
     * 有真值可判。</p>
     */
    private static String cellText(Row row, int col) {
        Cell cell = row.getCell(col);
        if (cell == null) {
            return null;
        }
        String text = switch (cell.getCellType()) {
            case STRING -> cell.getStringCellValue();
            case NUMERIC -> BigDecimal.valueOf(cell.getNumericCellValue()).toPlainString();
            case BOOLEAN -> String.valueOf(cell.getBooleanCellValue());
            case FORMULA -> cell.getCellFormula();
            default -> null;
        };
        if (text == null) {
            return null;
        }
        String trimmed = text.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    private static boolean isBlankRow(Row row) {
        for (int col = 0; col <= COL_REMARK; col++) {
            if (cellText(row, col) != null) {
                return false;
            }
        }
        return true;
    }
}
