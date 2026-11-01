package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import lombok.extern.slf4j.Slf4j;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.CellType;
import org.apache.poi.ss.usermodel.DataFormatter;
import org.apache.poi.ss.usermodel.DateUtil;
import org.apache.poi.ss.usermodel.FormulaEvaluator;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.usermodel.WorkbookFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.InputStream;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * 客户主数据 Excel 解析器（issue #8295）。
 *
 * <p><b>只做确定性解析</b>：读第一个 sheet、第一张非空行当表头、逐行转字符串。
 * 不猜列义、不写库；列义由 AI/人工映射决定。公式取缓存值，日期走单元格格式，
 * 大整数（手机号被旧 ERP 存成数字时）用 BigDecimal 转 plain string，避免科学计数法。</p>
 *
 * <p>边界：单文件 ≤5MB、≤2000 数据行、≤64 列；超限直接 422，不静默截断。</p>
 */
@Slf4j
@Component
public class CustomerImportParser {

    private static final long MAX_FILE_BYTES = 5L * 1024 * 1024;
    private static final int MAX_ROWS = 2000;
    private static final int MAX_COLUMNS = 64;
    private static final int SAMPLE_MAX = 5;

    public ParsedCustomerSheet parse(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw BusinessException.validationError("请上传客户 Excel 文件");
        }
        if (file.getSize() > MAX_FILE_BYTES) {
            throw BusinessException.validationError("文件超过 5MB，请拆分后再导入");
        }
        String filename = file.getOriginalFilename();
        if (filename == null || filename.isBlank()) {
            throw BusinessException.validationError("无法识别文件名，请上传 .xlsx / .xls");
        }
        String lower = filename.toLowerCase(Locale.ROOT);
        if (!lower.endsWith(".xlsx") && !lower.endsWith(".xls") && !lower.endsWith(".xlsm")) {
            throw BusinessException.validationError("仅支持 .xlsx / .xls / .xlsm 文件");
        }

        try (InputStream in = file.getInputStream(); Workbook workbook = WorkbookFactory.create(in)) {
            if (workbook.getNumberOfSheets() == 0) {
                throw BusinessException.validationError("Excel 没有可用工作表");
            }
            Sheet sheet = workbook.getSheetAt(0);
            if (sheet == null) {
                throw BusinessException.validationError("Excel 没有可用工作表");
            }
            Row headerRow = firstNonEmptyRow(sheet);
            if (headerRow == null) {
                throw BusinessException.validationError("Excel 是空表，找不到表头");
            }
            int columnCount = headerRow.getLastCellNum();
            if (columnCount <= 0) {
                throw BusinessException.validationError("Excel 表头为空");
            }
            if (columnCount > MAX_COLUMNS) {
                throw BusinessException.validationError("表头超过 " + MAX_COLUMNS + " 列，请拆分后再导入");
            }

            DataFormatter formatter = new DataFormatter(Locale.CHINA);
            FormulaEvaluator evaluator = workbook.getCreationHelper().createFormulaEvaluator();
            List<String> headers = new ArrayList<>(columnCount);
            for (int c = 0; c < columnCount; c++) {
                String text = cellText(headerRow.getCell(c), formatter, evaluator);
                headers.add(StringUtils.hasText(text) ? text : "列" + (c + 1));
            }

            List<List<String>> rows = new ArrayList<>();
            for (int r = headerRow.getRowNum() + 1; r <= sheet.getLastRowNum(); r++) {
                Row row = sheet.getRow(r);
                if (row == null) {
                    continue;
                }
                List<String> values = new ArrayList<>(columnCount);
                boolean hasValue = false;
                for (int c = 0; c < columnCount; c++) {
                    String text = cellText(row.getCell(c), formatter, evaluator);
                    if (StringUtils.hasText(text)) {
                        hasValue = true;
                    }
                    values.add(text);
                }
                if (!hasValue) {
                    continue;
                }
                rows.add(values);
                if (rows.size() > MAX_ROWS) {
                    throw BusinessException.validationError("最多 " + MAX_ROWS + " 行数据，请分批导入");
                }
            }
            if (rows.isEmpty()) {
                throw BusinessException.validationError("Excel 只有表头，没有数据行");
            }
            log.info("[customer-import] parsed: tenant={}, headers={}, rows={}",
                    com.migao.admin.config.TenantContext.getTenantId(), headers.size(), rows.size());
            return new ParsedCustomerSheet(headers, rows);
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.warn("[customer-import] Excel 解析失败: {}", e.getMessage());
            throw BusinessException.validationError("Excel 解析失败，请确认文件未损坏/未加密");
        }
    }

    /** 第一个非空行当表头（容忍 Excel 顶部空行；不跳过「标题行」——那需要人工选表头，V1 不做）。 */
    private static Row firstNonEmptyRow(Sheet sheet) {
        for (int r = sheet.getFirstRowNum(); r <= sheet.getLastRowNum(); r++) {
            Row row = sheet.getRow(r);
            if (row == null) {
                continue;
            }
            for (int c = 0; c < row.getLastCellNum(); c++) {
                Cell cell = row.getCell(c);
                if (cell != null && cell.getCellType() != CellType.BLANK
                        && StringUtils.hasText(cell.toString())) {
                    return row;
                }
            }
        }
        return null;
    }

    private static String cellText(Cell cell, DataFormatter formatter, FormulaEvaluator evaluator) {
        if (cell == null) {
            return "";
        }
        CellType type = cell.getCellType();
        try {
            if (type == CellType.NUMERIC) {
                if (DateUtil.isCellDateFormatted(cell)) {
                    return formatter.formatCellValue(cell).trim();
                }
                // 旧 ERP 常把手机号/客户编码存成数字：BigDecimal + plain string 防 1.38E+10
                return BigDecimal.valueOf(cell.getNumericCellValue())
                        .stripTrailingZeros().toPlainString();
            }
            if (type == CellType.BOOLEAN) {
                return String.valueOf(cell.getBooleanCellValue());
            }
            if (type == CellType.FORMULA) {
                return formatter.formatCellValue(cell, evaluator).trim();
            }
            if (type == CellType.STRING) {
                return cell.getStringCellValue().trim();
            }
        } catch (Exception e) {
            // 公式/格式异常时退回 DataFormatter，不让单格坏值炸掉整份文件
            return formatter.formatCellValue(cell, evaluator).trim();
        }
        return "";
    }

    /** 供分析接口取样本行（最多 5 行）；页面展示用。 */
    public static List<List<String>> samples(List<List<String>> rows) {
        if (rows == null || rows.isEmpty()) {
            return List.of();
        }
        return rows.subList(0, Math.min(SAMPLE_MAX, rows.size()));
    }
}
