// case_ids: DF-010, DF-011
package com.migao.admin.service;

import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.web.multipart.MultipartFile;

import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.function.Supplier;

/**
 * 上传护栏判据的**共用夹具与语料**（issue #6207 / #6208）。
 *
 * <p>语料只有**一份**：{@link #hostileInputs()} 同时喂给
 * {@code UploadGuardTest}（护栏自身）、{@code FileStorageServiceTest}（两个实现的拒绝语义同源）
 * 与 {@code UploadInputGuardTest}（端到端副作用）—— 这就是「护栏同源」在测试侧的可执行形态。</p>
 */
final class UploadGuardFixtures {

    /** PNG 魔数。 */
    static final byte[] PNG_MAGIC = {(byte) 0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A};
    /** JPEG 魔数（SOI + APP0 前两字节）。 */
    static final byte[] JPEG_MAGIC = {(byte) 0xFF, (byte) 0xD8, (byte) 0xFF, (byte) 0xE0};
    /** GIF87a 魔数。 */
    static final byte[] GIF_MAGIC = {'G', 'I', 'F', '8', '7', 'a'};
    /** PDF 魔数。 */
    static final byte[] PDF_MAGIC = {'%', 'P', 'D', 'F', '-'};

    /** 路径穿越候选（明文 / 绝对路径 / 百分号编码 / 反斜杠 / 嵌套）。 */
    static final List<String> TRAVERSAL_DIRECTORIES = List.of(
            "../../l2evil",
            "../evil",
            "/etc/evil",
            "..%2f..%2fevil",
            "a/../../evil",
            "..\\..\\evil");

    static final String HOSTILE_INPUT_DOC =
            "越界目录 ×5 / 嵌套与反斜杠穿越 ×2 / 声明图片非图片 / 扩展名内容不符 / 超限 / 空文件";

    private UploadGuardFixtures() {
    }

    /** 一个可用作「合法上传」的真魔数文件。 */
    static MockMultipartFile realFile(String name, String contentType, byte[] magic) {
        return new MockMultipartFile("file", name, contentType, bytes(magic, 64));
    }

    /** 把 {@code magic} 补零到 {@code totalLength}（用于构造超限文件）。 */
    static byte[] bytes(byte[] magic, int totalLength) {
        byte[] out = new byte[totalLength];
        System.arraycopy(magic, 0, out, 0, Math.min(magic.length, totalLength));
        return out;
    }

    /** 恶意输入语料：一份，两个实现共用。 */
    static List<HostileInput> hostileInputs() {
        return List.of(
                hostile("越界目录 ../../l2evil", () -> realFile("a.png", "image/png", PNG_MAGIC), "../../l2evil"),
                hostile("越界目录 ../evil", () -> realFile("a.png", "image/png", PNG_MAGIC), "../evil"),
                hostile("绝对路径目录 /etc/evil", () -> realFile("a.png", "image/png", PNG_MAGIC), "/etc/evil"),
                hostile("编码形态目录 ..%2f..%2fevil",
                        () -> realFile("a.png", "image/png", PNG_MAGIC), "..%2f..%2fevil"),
                hostile("嵌套穿越目录 a/../../evil",
                        () -> realFile("a.png", "image/png", PNG_MAGIC), "a/../../evil"),
                hostile("反斜杠穿越目录 ..\\..\\evil",
                        () -> realFile("a.png", "image/png", PNG_MAGIC), "..\\..\\evil"),
                hostile("回折但不出根的目录 images/../../evil（两实现都不得把它当越界）",
                        () -> realFile("a.png", "image/png", PNG_MAGIC), "images/../../evil"),
                hostile("声明图片但内容为文本",
                        () -> new MockMultipartFile("file", "fake.png", "image/png",
                                "not a png".getBytes(java.nio.charset.StandardCharsets.UTF_8)), "images"),
                hostile("扩展名与内容不符（.png + PDF 字节流）",
                        () -> new MockMultipartFile("file", "x.png", "image/png", bytes(PDF_MAGIC, 64)), "images"),
                hostile("6MB 超限图片",
                        () -> new MockMultipartFile("file", "big6.png", "image/png",
                                bytes(PNG_MAGIC, 6_291_525)), "images"),
                hostile("空文件",
                        () -> new MockMultipartFile("file", "empty.png", "image/png", new byte[0]), "images"));
    }

    static HostileInput hostile(String label, Supplier<MultipartFile> file, String directory) {
        return new HostileInput(label, file, directory);
    }

    /** 一次实测的归口：{@code null} 状态码 = 5xx / 非业务异常。 */
    static Outcome probe(java.util.concurrent.Callable<UploadedFileInfo> call) {
        try {
            return Outcome.of(call.call());
        } catch (BusinessException e) {
            return Outcome.of(e);
        } catch (Exception e) {
            return new Outcome(null, e.getClass().getSimpleName());
        }
    }

    /** 返回拒绝时的 {@link BusinessException}；被接受（或非业务异常）⇒ {@code null}。 */
    static BusinessException orNull(java.util.concurrent.Callable<UploadedFileInfo> call) {
        try {
            call.call();
            return null;
        } catch (BusinessException e) {
            return e;
        } catch (Exception e) {
            return null;
        }
    }

    /** 恶意输入一条（label 用于判红时具名指认）。 */
    record HostileInput(String label, Supplier<MultipartFile> file, String directory) {
    }

    /** 一次实测结果。 */
    record Outcome(Integer status, String code) {

        static Outcome of(UploadedFileInfo ignored) {
            return new Outcome(200, "OK");
        }

        static Outcome of(BusinessException e) {
            return new Outcome(e.getHttpStatus(), e.getCode());
        }

        /** 同一类 = 同一个状态码家族（4xx / 5xx）+ 同一个错误码；5xx 与 200 都算分叉。 */
        boolean isSameClassAs(Outcome other) {
            if (status == null || other.status == null) {
                return Objects.equals(status, other.status);
            }
            return status / 100 == other.status / 100 && Objects.equals(code, other.code);
        }

        String describe() {
            return status == null ? "5xx?" : status + "/" + code;
        }
    }

    /** 读全部内容（仅用于夹具自检）。 */
    static byte[] readAll(MultipartFile file) throws java.io.IOException {
        try (InputStream in = file.getInputStream()) {
            return in.readAllBytes();
        }
    }
}
