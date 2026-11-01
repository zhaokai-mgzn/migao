// case_ids: MIG-004

package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 客户 Excel 解析器边界（issue #8295）。
 *
 * <p>只验确定性解析：任意表头、空表头补位、数字手机号不转科学计数法、样本最多 5 行、
 * 行数/空表/非 Excel 显式拒绝。AI 不参与本层。</p>
 */
class CustomerImportParserTest {

    private final CustomerImportParser parser = new CustomerImportParser();

    @Test
    void parsesArbitraryHeadersAndSamples() throws Exception {
        List<String> headers = List.of("购货单位", "联系方式", "送货地点", "备注");
        List<List<String>> rows = List.of(
                List.of("张三布行", "13800138000", "绍兴市柯桥区", "老客户"),
                List.of("李四纺织", "13900139000", "杭州市余杭区", "")
        );
        MockMultipartFile file = xlsx("customers.xlsx", headers, rows);

        ParsedCustomerSheet sheet = parser.parse(file);

        assertThat(sheet.headers()).containsExactly("购货单位", "联系方式", "送货地点", "备注");
        assertThat(sheet.totalRows()).isEqualTo(2);
        assertThat(sheet.rows().get(0)).containsExactly("张三布行", "13800138000", "绍兴市柯桥区", "老客户");
        assertThat(sheet.rows().get(1).get(3)).isEmpty();
        assertThat(CustomerImportParser.samples(sheet.rows())).hasSize(2);
    }

    @Test
    void blankHeaderGetsColumnFallbackAndNumericPhoneStaysPlain() throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            Sheet sheet = workbook.createSheet("客户");
            Row header = sheet.createRow(0);
            header.createCell(0).setCellValue("客户名称");
            header.createCell(1); // 空表头
            header.createCell(2).setCellValue("手机号");
            Row data = sheet.createRow(1);
            data.createCell(0).setCellValue("张三布行");
            data.createCell(1).setCellValue("备注");
            data.createCell(2).setCellValue(13800138000D);
            workbook.write(out);

            ParsedCustomerSheet parsed = parser.parse(new MockMultipartFile(
                    "file", "customers.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", out.toByteArray()));

            assertThat(parsed.headers()).containsExactly("客户名称", "列2", "手机号");
            assertThat(parsed.rows().get(0)).containsExactly("张三布行", "备注", "13800138000");
        }
    }

    @Test
    void samplesCapAtFive() throws Exception {
        List<List<String>> rows = new ArrayList<>();
        for (int i = 0; i < 8; i++) {
            rows.add(List.of("客户" + i, "1380013800" + i));
        }
        ParsedCustomerSheet sheet = parser.parse(xlsx("customers.xlsx",
                List.of("客户名称", "手机号"), rows));

        assertThat(sheet.totalRows()).isEqualTo(8);
        assertThat(CustomerImportParser.samples(sheet.rows())).hasSize(5);
    }

    @Test
    void rejectsEmptyAndNonExcel() {
        assertThatThrownBy(() -> parser.parse(new MockMultipartFile("file", "empty.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", new byte[0])))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("请上传");

        assertThatThrownBy(() -> parser.parse(new MockMultipartFile("file", "customers.csv",
                "text/csv", "a,b".getBytes())))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("仅支持");
    }

    @Test
    void rejectsTooManyRows() throws Exception {
        List<List<String>> rows = new ArrayList<>();
        for (int i = 0; i < 2001; i++) {
            rows.add(List.of("客户" + i));
        }
        MockMultipartFile file = xlsx("customers.xlsx", List.of("客户名称"), rows);

        assertThatThrownBy(() -> parser.parse(file))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("2000");
    }

    private static MockMultipartFile xlsx(String name, List<String> headers, List<List<String>> rows)
            throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            Sheet sheet = workbook.createSheet("客户");
            Row header = sheet.createRow(0);
            for (int i = 0; i < headers.size(); i++) {
                header.createCell(i).setCellValue(headers.get(i));
            }
            for (int r = 0; r < rows.size(); r++) {
                Row row = sheet.createRow(r + 1);
                for (int c = 0; c < headers.size(); c++) {
                    List<String> values = rows.get(r);
                    row.createCell(c).setCellValue(c < values.size() ? values.get(c) : "");
                }
            }
            workbook.write(out);
            return new MockMultipartFile("file", name,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", out.toByteArray());
        }
    }
}
