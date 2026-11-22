package com.migao.admin.config;

import com.migao.admin.service.FileStorageService;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;

/**
 * 上传存储形态的**启动期自检**（集群 P0-3，审计见 `docs/deployment/cluster-readiness-audit.md`）。
 *
 * <h2>它解决什么</h2>
 * <p>未配 OSS 时 {@link com.migao.admin.service.LocalFileStorageService} 把文件写**本机磁盘**
 * （{@code uploads/}，静态面由 {@code WebConfig} 的 {@code file:uploads/} 托管）。这在单实例下自洽，
 * 但多实例下「写 A 读 B ⇒ 404 / 商品图裂 / 作业照片打不开」，而且**没有任何启动期提示** ——
 * 故障面要到用户点开图片时才出现，且看起来像「文件丢了」。本类把这条缺陷**前移到启动期**：
 *
 * <ul>
 *   <li><b>多实例 + 缺 OSS ⇒ fail-close 拒绝启动</b>（报文给可行动指引）；</li>
 *   <li>单实例 + 缺 OSS ⇒ 维持现状启动，但打**一条 WARN** 说明「本地存储，仅限单实例」；</li>
 *   <li>OSS 齐备 ⇒ INFO 一行，存储形态由 {@link StorageHealthIndicator} / {@code /api/version/storage} 暴露。</li>
 * </ul>
 *
 * <h2>「多实例」怎么判：显式环境变量，不靠猜</h2>
 * <p>唯一判据 = {@code MIGAO_REPLICAS}（默认 {@code 1}）。**刻意不用**自动猜测
 * （hostname 形态 / 容器环境变量 / 是否跑在容器里 —— 那些都会把单实例误判成多实例，或反过来漏判）：
 * 扩容时由部署面**显式**注入实例数（compose {@code deploy.replicas} / K8s {@code replicas} / 手工设 env），
 * 值 {@code >1} 即视为多实例。配置非法（非整数 / &lt;1）同样 fail-close —— 因为「判不出来」不许当成「单实例」。
 *
 * <h2>为什么不是「配了 OSS 就万事大吉」</h2>
 * <p>判据用的是 {@link OssConfig#hasCredentials()}（与 {@code OssService} 的
 * {@code @ConditionalOnExpression} 同一份口气：三项凭据都非空白）⇒ **不会**出现
 * 「自检说 OSS 已配、实际 bean 没装」的两套判据。
 */
@Slf4j
@Component
public class StorageDeploymentSelfCheck {

    /** 可行动指引指向的文档（运维改配置时唯一要读的一页）。 */
    public static final String DOC = "docs/deployment/upload-storage-and-multi-instance.md";

    /** 判定多实例的唯一显式来源；默认 1 = 单实例。 */
    public static final String REPLICAS_ENV = "MIGAO_REPLICAS";

    /** 三项凭据的环境变量名（报文里逐字给出，便于照着填）。 */
    private static final String[] CREDENTIAL_ENV = {
            "OSS_ENDPOINT", "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET"};

    private final FileStorageService fileStorageService;
    private final OssConfig ossConfig;
    private final int replicas;

    public StorageDeploymentSelfCheck(
            FileStorageService fileStorageService,
            OssConfig ossConfig,
            @Value("${" + REPLICAS_ENV + ":1}") String replicas) {
        this.fileStorageService = fileStorageService;
        this.ossConfig = ossConfig;
        this.replicas = parseReplicas(replicas);
    }

    /**
     * 启动期判定（{@code @PostConstruct}：bean 创建即执行 ⇒ 早于任何 CommandLineRunner /
     * 端口监听 / 探活 200，故障不会「先上线再爆」）。
     */
    @PostConstruct
    void check() {
        boolean ossReady = ossConfig.hasCredentials();
        if (isMultiInstance() && !ossReady) {
            throw new IllegalStateException(failClosedMessage(missingCredentials()));
        }
        if (!ossReady) {
            // 单实例：维持既有行为（本地盘可用），但把「仅限单实例」写在启动日志里。
            log.warn("上传存储 = 本地磁盘（uploads/），仅限单实例部署：{} 未设置或 =1，且未配置 OSS。"
                            + "多实例部署必须配置 OSS，否则「写 A 读 B」必 404（{}>1 且缺 OSS 时会拒绝启动）。详见 {}",
                    REPLICAS_ENV, REPLICAS_ENV, DOC);
            return;
        }
        log.info("上传存储 = OSS（bucket={}，permanent={}，temporary={}），{}={}",
                ossConfig.getBucketName(), ossConfig.getPermanentBucketName(),
                ossConfig.getTemporaryBucketName(), REPLICAS_ENV, replicas);
    }

    /** 存储形态（与接口同源：{@code oss} / {@code local}）—— 健康端点与版本端点都读它。 */
    public String storageType() {
        return fileStorageService.getStorageType();
    }

    /** 显式声明的实例数（{@code MIGAO_REPLICAS}）。 */
    public int replicas() {
        return replicas;
    }

    public boolean isMultiInstance() {
        return replicas > 1;
    }

    public boolean ossConfigured() {
        return ossConfig.hasCredentials();
    }

    /**
     * 解析 {@code MIGAO_REPLICAS}。
     *
     * <p>空 ⇒ 1（默认单实例）；非整数 / &lt;1 ⇒ <b>抛异常</b>（fail-closed）：
     * 一个写错的值若被静默当成单实例放行，护栏就正好在最需要它的时候失效。</p>
     */
    static int parseReplicas(String raw) {
        if (!StringUtils.hasText(raw)) {
            return 1;
        }
        String value = raw.trim();
        int parsed;
        try {
            parsed = Integer.parseInt(value);
        } catch (NumberFormatException e) {
            throw new IllegalStateException("非法配置：" + REPLICAS_ENV + "=" + value
                    + "（必须是 >=1 的整数；单实例请删掉这项或设为 1）。判定不了实例数时不允许启动 —— "
                    + "见 " + DOC);
        }
        if (parsed < 1) {
            throw new IllegalStateException("非法配置：" + REPLICAS_ENV + "=" + value
                    + "（必须 >=1；单实例请设为 1）。见 " + DOC);
        }
        return parsed;
    }

    private List<String> missingCredentials() {
        List<String> missing = new ArrayList<>();
        if (!StringUtils.hasText(ossConfig.getEndpoint())) {
            missing.add(CREDENTIAL_ENV[0]);
        }
        if (!StringUtils.hasText(ossConfig.getAccessKeyId())) {
            missing.add(CREDENTIAL_ENV[1]);
        }
        if (!StringUtils.hasText(ossConfig.getAccessKeySecret())) {
            missing.add(CREDENTIAL_ENV[2]);
        }
        return missing;
    }

    private String failClosedMessage(List<String> missing) {
        return "多实例部署必须配置 OSS：检测到 " + REPLICAS_ENV + "=" + replicas + "（>1），"
                + "而 aliyun.oss.endpoint / access-key-id / access-key-secret 未配齐（缺 "
                + String.join(" / ", missing) + "）。"
                + "多实例下本地上传目录是各实例私有磁盘 ⇒ 上传打到实例 A、图片读到实例 B ⇒ 404。"
                + "修复（二选一）：① 在 .env.admin-api 配齐 " + String.join(" / ", CREDENTIAL_ENV)
                + "（外加 OSS_PERMANENT_BUCKET_NAME / OSS_TEMPORARY_BUCKET_NAME）；"
                + "② 若确为单实例，把 " + REPLICAS_ENV + " 设为 1（或删掉）。详见 " + DOC;
    }
}
