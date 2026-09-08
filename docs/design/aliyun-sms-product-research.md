# 阿里云短信能力调研报告

> **调研日期：2026-09-07（周一）**｜调研人：MIGAO 研发调研员｜用途：评估 MIGAO 短信验证码登录与通知渠道接入阿里云方案
> **方法说明**：以阿里云官方文档（help.aliyun.com / aliyun.com 产品与价格页）一手资料为准，逐条核对原文；二手资料仅辅助并明确标注。价格、免费额度、审核/报备时长等易变信息均标注调研日期，请以阿里云控制台与最新官方文档为准。
> **结论可信度**：核心结论（产品主线、接入步骤、计费区间、频控默认值、错误码）均有官方原文支撑；个别未查到或待确认项已在文中明确标注「未查到/待确认」。

---

## 1. TL;DR 结论

1. **阿里云官方可发短信的产品就是「短信服务 SMS」**，其现行 OpenAPI 版本为 `2017-05-25`（服务地址 `dysmsapi.aliyuncs.com`）——与 MIGAO 预留代码（`com.aliyun.dysmsapi20170525.Client`、endpoint、`SendSmsRequest` 骨架）**完全吻合**，推荐以「短信服务 SMS」为主线路接入，无需更换 SDK。号码认证（一键登录）、语音服务、Chatapp、云市场第三方短信是配套/替代，不能替代国内文本短信主线。详见 [§2](#2-可发短信的阿里云产品全景) 与 [§4](#4-配套替代方案)。
2. **当前最大门槛不是技术而是资质合规**：2026 年起运营商严格执行**短信签名实名制报备**，签名来源仅认「企事业单位名 / 已注册商标名」（2026-04-27 起不再支持「已上线 APP」等来源），且要求企业资质报备——MIGAO 需要**企业实名认证 → 申请资质（约 2 个工作日审核）→ 申请签名与模板（2 小时内审核）→ 运营商报备（平均 5-7 个工作日，部分 7-10 个工作日）**。这条前置链路应在排期上留出 1-2 周。
3. **代码侧缺口明确**：`SmsService` 的防刷（60s 间隔 + 日计数 + 失败锁定）与官方防盗刷建议一致且是良好基础；缺的是真实调用启用、回执消费（MNS 队列或 HTTP 推送）、幂等与错误码处理、以及上线后**移除万能码 bypass（技术债 Issue #2616）**。完整清单见 [§5.3](#53-上线-checklist)。

---

## 2. 可发短信的阿里云产品全景

“发短信”在阿里云语境下横跨 4 类产品：**[短信服务 SMS]**（唯一原生短信产品）、**[语音服务]**（语音类触达）、**[号码认证服务]**（免短信的认证登录）、**[云市场第三方短信]** 与 **[Chatapp 消息服务/移动推送]**（易混淆项）。

| 产品 | 官方定位 / 能力 | 适用场景 | 接入方式 | 计费模式 | 开通前置条件 | 与 MIGAO 关系 |
|---|---|---|---|---|---|---|
| **短信服务 SMS — 国内文本短信**（验证码/通知/推广） | 通过 API/SDK/控制台向国内手机号发送文本短信；签名模板需审核 | B 端管理员/员工验证码登录、企业入驻注册验证码、工单/发货/预警通知（[功能特性](https://help.aliyun.com/zh/sms/product-overview/product-function-node-dysms)） | OpenAPI `2017-05-25`（`dysmsapi.aliyuncs.com`）+ 官方 SDK（[集成概览](https://help.aliyun.com/zh/sms/developer-reference/using-openapi)） | 按量梯度计费 or 套餐包；**按运营商回执状态计费**（未送达不计费）（[国内定价](https://help.aliyun.com/zh/sms/product-overview/billing-of-messages-sent-to-chinese-mainland)） | 注册 + 实名认证（发国内短信需企业认证或用他企业资质）+ 资质/签名/模板审核 + 开通服务 | **推荐主线**，与现有 dysmsapi SDK 兼容 |
| **短信服务 SMS — 国际/港澳台短信** | 向境外 200+ 国家/地区发送短信，一地一价 | 出海（C 端海外用户） | 同 OpenAPI | **发送即收费**（提交成功即计费，失败也计费）；按量 QPS 2000/秒，套餐包 QPS 30/秒（[国际定价](https://help.aliyun.com/zh/sms/product-overview/pricing-of-messages-sent-to-countries-or-regions-outside-chinese-mainland)） | 仅支持中国站账号从中国内地向境外发送 | MIGAO 当前以中国大陆手机号为主，暂不涉及 |
| **短信服务 SMS — 多媒体短信**（数字短信/卡片短信） | 富媒体（图片/视频/音频/卡片）消息（[功能特性](https://help.aliyun.com/zh/sms/product-overview/product-function-node-dysms)、[数字短信新手指引](https://help.aliyun.com/zh/sms/user-guide/get-started-with-digital-sms)） | 营销/品牌触达 | 控制台或 API | 按条计费（具体单价未查到，见 §6 易变清单） | 企业认证（个人认证不支持多媒体短信，见[使用须知](https://help.aliyun.com/zh/sms/user-guide/usage-notes)） | 非当前需求，不作为主线 |
| **语音服务（Voice Service）** | 语音验证码（SingleCallByTts）、语音通知（SingleCallByVoice）、IVR、智能外呼（[功能介绍](https://help.aliyun.com/zh/vms/product-overview/product-function-node-dyvms)） | **短信失败/老人机等场景的验证码触达兜底**、电话通知 | 独立 OpenAPI（`dyvmsapi`），与短信 SDK 不同 | 预充值按量：语音验证码 0.080 元/条起、语音通知 0.110 元/分钟起（阶梯）（[语音价格页](https://cn.aliyun.com/ntms/price/detail/dyvms)） | 企业资质与话术报备（调用语音的必要功能，见[功能介绍](https://help.aliyun.com/zh/vms/product-overview/product-function-node-dyvms)） | 可作为兜底方案，详见 [§4.1](#41-语音验证码语音通知) |
| **号码认证服务（PNVS）** | 一键登录、本机号码校验、图形认证、短信认证、融合认证（[功能](https://help.aliyun.com/zh/pnvs/product-overview/number-authentication)） | App/H5 免短信验证码登录、短信接口防盗刷前置校验 | 独立 OpenAPI（`dypnsapi`）+ 多端 SDK | 按量/套餐包：一键登录 0.050 元/次起、短信认证 0.06 元/次起、图形认证 0.006 元/次（[PNVS 定价](https://help.aliyun.com/zh/pnvs/product-overview/product-pricing)） | 实名认证后开通（企业认证要求未逐项核实，以控制台为准） | 补充登录方式候选，**微信小程序不支持一键登录**，详见 [§4.2](#42-号码认证一键登录与短信验证码对比) |
| **云市场第三方短信** | 第三方服务商入驻云市场提供的短信 API（例：[三网短信服务](https://market.aliyun.com/detail/cmapi025016)） | 短信服务 SMS 的替代采购渠道 | 各服务商自有 API | 服务商自定（通常按条套餐） | 各服务商自定 | 可作为商务对比选项，但需自担资质合规与稳定性风险，**非阿里云自有产品**（第三方资料，仅供参考） |
| **ChatAPP 消息服务**（易混淆） | 基于 WhatsApp 等海外社交媒体 Channel 的消息服务，**不是短信**（[什么是 Chatapp](https://www.alibabacloud.com/help/zh/chatapp/product-overview/what-is-chatapp-message-service)） | 海外触达 | 独立产品 | 独立计费 | — | 与国内短信无替代关系，仅提示区分 |
| **移动推送 / 消息推送**（易混淆） | App 内推送（通知栏），不走运营商短信通道（[产品页](https://www.aliyun.com/product/cps)） | App 站内通知 | 独立产品 | 独立计费 | — | MIGAO 的通知渠道设计含微信/站内/邮件/短信，推送类不在本次范围 |

> **要点**：真正能“发国内短信”且具备国内合规资质的官方主线只有**短信服务 SMS 的国内文本短信**。语音、号码认证、Chatapp 都是不同通道，云市场为第三方渠道。

---

## 3. 短信服务 SMS 深入

### 3.1 OpenAPI 版本：新版与“旧版”的关系

- 短信服务现行唯一官方 OpenAPI 版本为 **2017-05-25**，官方说明“该数字代表 API 版本号而非时间概念，展示的是**最新的 API 公开数据**，并非自 2017-05-25 后未更新”（[使用OpenAPI调试短信服务—版本说明](https://help.aliyun.com/zh/sms/developer-reference/using-openapi)）。**未查到仍在维护的旧版（如 2015/2016 时代）OpenAPI 文档**；社区流传的旧版 SDK/接口已收敛到该版本。
- 调用方式：RPC 风格，`POST/GET`，服务地址全局接入点 **`dysmsapi.aliyuncs.com`（中国站）**，V3 签名机制；推荐使用官方 SDK（`com.aliyun.dysmsapi20170525.*`），自定义 HTTP 封装“不推荐”（[集成概览](https://help.aliyun.com/zh/sms/developer-reference/using-openapi)）。
- 调用身份：阿里云账号 / **RAM 用户（推荐）** / RAM 角色（推荐），需授权如 `AliyunDysmsFullAccess`；AccessKey 用于 API 认证，“**不存在独立 token 概念**，创建 AK 无需短信资质”（[使用须知](https://help.aliyun.com/zh/sms/user-guide/usage-notes)）。
- `SendSms` 接口要点（[SendSms 文档](https://help.aliyun.com/zh/sms/developer-reference/api-dysmsapi-2017-05-25-sendsms)）：
  - 单次可向最多 **1000 个手机号**发送（相同签名、相同模板变量）；验证码类建议单条发送；不同签名/模板变量的批量用 `SendBatchSms`（单次最多 100 个）。
  - **国内短信、国际短信、多媒体短信均不支持幂等**，需业务侧做好幂等控制（MIGAO 接入时需注意重试策略）。
  - 超时建议：国内短信服务超时时间建议 ≥1s，超时后查回执状态再判断是否重试。
  - 同步返回：`Code=OK` 仅代表“提交成功”，真正送达状态要等运营商回执（见 [§3.5](#35-回执与错误码)）；返回字段含 `BizId`（发送回执 ID，可用 `QuerySendDetails` 查询）。

### 3.2 资质、签名、模板：申请流程与审核时长

`资质 → 签名 → 模板` 三道前置审核，全部通过后才能真正发出（[使用须知-审核标准](https://help.aliyun.com/zh/sms/user-guide/usage-notes)、[资质材料说明](https://help.aliyun.com/zh/sms/user-guide/qualification-application-description)）。

| 环节 | 申请前置 | 审核时长（调研日期 2026-09-07） | 关键约束 |
|---|---|---|---|
| **短信资质** | 企业/个人信息 + 证照材料 | 阿里云审核预计 **2 个工作日**；**运营商实名报备平均 5-7 个工作日，部分 7-10 个工作日**，官方不承诺时效 | 材料：加载统一社会信用代码的证照（营业执照等）、法定代表人（负责人）信息、管理员（经办人）姓名+身份证+手机号；管理员须符合运营商“**一人一企**”校验。**个人认证的自用资质无法通过签名实名制报备**，只能走“他用资质”（企业信息 + 委托授权书）或升级企业认证（[资质材料说明](https://help.aliyun.com/zh/sms/user-guide/qualification-application-description)） |
| **短信签名** | 资质审核通过 | 签名/模板预计提交后 **2 小时内**（工作时间；政府企业相关 2 个工作日）（[使用须知](https://help.aliyun.com/zh/sms/user-guide/usage-notes)） | **签名来源仅支持「企事业单位名（全称或简称）、已注册商标名」**；含义模糊的中性签名（例“客服通知/温馨提示/业务告警”——对 MIGAO 的模板名有直接影响）**不支持**；不支持个人姓名、含“测试”字样；长度 2-18 字符，不支持繁体/特殊符号（[签名规范](https://help.aliyun.com/zh/sms/user-guide/signature-specifications-1)）。同一账号**一个自然日最多申请 1 个签名**（错误码 `isv.SIGN_COUNT_OVER_LIMIT`，见 [使用须知](https://help.aliyun.com/zh/sms/user-guide/usage-notes)） |
| **短信模板** | 签名通过后 | 同上 2 小时内 | 模板分**验证码、短信通知、推广短信**三类；**验证码类签名只能发验证码模板，通用类签名可发全部类型**（错误码 `isv.SMS_SIGNATURE_SCENE_ILLEGAL`）；模板变量须符合类型规范（验证码模板变量传 4~6 位纯数字，通知类按变量长度/字符类型限制，`TemplateParam` 必须是 JSON 字符串）；单日 API 申请上限 100 个（控制台不限）（[使用须知](https://help.aliyun.com/zh/sms/user-guide/usage-notes)、[错误码](https://help.aliyun.com/zh/sms/developer-reference/api-error-codes)、[测试短信-参数排查](https://help.aliyun.com/zh/sms/user-guide/send-test-messages-1)） |

**个人 vs 企业认证的权益差异**（[使用须知-权益区别](https://help.aliyun.com/zh/sms/user-guide/usage-notes)，调研日期 2026-09-07）：

| 能力 | 企业认证用户 | 个人认证用户 |
|---|---|---|
| 国内验证码短信 | 支持 | 支持（能提供他用企业资质的个人用户） |
| 国内通知短信 | 支持 | 支持（同上） |
| 国内推广短信 | 支持 | **不支持** |
| 多媒体短信 / 国际港澳台短信 | 支持 | **不支持** |
| 签名实名制报备 | 支持 | **不可报备**（官方重要提示：仅企业资质可报备并发送，无法提供企业资质的个人用户推荐使用「短信认证」产品） |

> **对 MIGAO 的结论**：按其重要提示，“**仅企业资质才可以进行报备和发送短信**”——应默认按**企业实名认证**排期，不要依赖个人认证场景（历史“个人可发验证码”的说法已不符合现行报备政策；以阿里云最新控制台/文档为准）。

### 3.3 计费（调研日期：2026-09-07）

数据来源：[国内短信服务定价](https://help.aliyun.com/zh/sms/product-overview/billing-of-messages-sent-to-chinese-mainland)、【2026-04-20 国内短信价格调整公告】（**2026-05-20 起生效**，下表为调整后价格）（[公告原文](https://help.aliyun.com/zh/sms/product-overview/notice-on-price-adjustment-for-domestic-sms-services-2604)）。

**按量付费（梯度计费，实时计费、自动跨档）：**

| 月使用量阶梯 | 验证码&通知短信（元/条） | 推广短信（元/条） |
|---|---|---|
| 量 ≤ 10 万 | **0.045** | 0.055 |
| 10 万 < 量 ≤ 30 万 | 0.042 | 0.052 |
| 30 万 < 量 ≤ 50 万 | 0.041 | 0.051 |
| 50 万 < 量 ≤ 100 万 | 0.040 | 0.050 |
| 100 万 < 量 ≤ 300 万 | 0.039 | 0.049 |
| 量 > 300 万 | 0.038 | 0.048 |

**套餐包（有效期两年，欠费不可用）：** 1000/2000/5000 条均为 **0.05 元/条**；1.5 万条 0.047；5 万条 0.045；20 万条 0.044；50 万条 0.043；100 万条 0.042；300 万条 0.041（套餐总价 = 条数 × 单价）。

计费规则要点：
- **国内短信按运营商回执状态计费**：提交成功但回执失败（未送达）**不计费**；收到失败回执时优先退回套餐包条数（[国内定价](https://help.aliyun.com/zh/sms/product-overview/billing-of-messages-sent-to-chinese-mainland)）。
- 套餐包仅限国内文本短信，发送国内短信须由中国内地 IP 发起（错误码 `isv.DENY_IP_RANGE`：非中国内地 IP 禁止发国内短信，见 [错误码](https://help.aliyun.com/zh/sms/developer-reference/api-error-codes)）。
- **免费额度：未查到现行“每月免费条数/免费测试额度”**；官方明确“**发送测试短信是计费的**”，且仅支持最多绑定 **5 个**测试手机号（[测试短信发送](https://help.aliyun.com/zh/sms/user-guide/send-test-messages-1)）。开通服务时系统赠送的是**模板**（赠送模板），非短信条数（[使用须知](https://help.aliyun.com/zh/sms/user-guide/usage-notes)）。若控制台存在新用户权益/免费试用券，以实际为准。
- 国际/港澳台差异：**发送即收费**（提交成功即计费，返回失败同样计费，与国内回执计费规则相反）；一地一价；套餐包 QPS 30/秒、按量 QPS 2000/秒（[国际定价](https://help.aliyun.com/zh/sms/product-overview/pricing-of-messages-sent-to-countries-or-regions-outside-chinese-mainland)）。

**MIGAO 成本估算（示意，非报价）**：假设月发 2 万条（验证码 + 通知为主，主要在 ≤10 万档）→ 按量约 **0.045 × 20000 ≈ 900 元/月**；若月发 10 万条 → 进入第二档约 4200 元/月。量级稳定后可买 5 万条套餐（约 2250 元）锁定单价。验证码业务若“只发成功”验证码时 MIGAO 需自行承担已发送成本，防刷至关重要（见 §6）。

### 3.4 频率 / QPS / 内容安全限制

- **接口 QPS**：`SendSms` 单用户 **5000 次/秒**（[SendSms 文档](https://help.aliyun.com/zh/sms/developer-reference/api-dysmsapi-2017-05-25-sendsms)）；国际/港澳台按量 2000/秒、套餐包 30/秒（[国际定价](https://help.aliyun.com/zh/sms/product-overview/pricing-of-messages-sent-to-countries-or-regions-outside-chinese-mainland)）。QPS 对 MIGAO 验证码量级（分钟级个位数）远不构成瓶颈，真正瓶颈是单号码频控。
- **单号码频控（关键，官方默认值，需在控制台确认）**（[设置短信发送频率](https://help.aliyun.com/zh/sms/user-guide/configure-delivery-frequency-and-whitelist)、[错误码](https://help.aliyun.com/zh/sms/developer-reference/api-error-codes)）：
  - **验证码短信默认频控**：同签名、同号码 **每分钟 1 条、每小时 5 条、每自然日 10 条**（官方明文）。
  - **通知短信默认流控**：同签名、同模板、同号码 **每自然日 50 条**（验证码与通知频控规则不同，误用会触发不同限制）。
  - 控制台可调：验证码类“每分/每时/每日上限**最大不可超过 40 条**”，通知及推广类**最大不可超过 50 条**（仅企业用户可设置），配置后 15 分钟生效。
  - 频率限制白名单：最多 **300 个**号码，仅控制台可添加（**不支持 API 添加**）。
- **触发频控的错误表现**：`isv.BUSINESS_LIMIT_CONTROL`（见 [§3.5](#35-回执与错误码)）；另可按日/月设发送总量限额，超限 `isv.DAY_LIMIT_CONTROL` / `isv.MONTH_LIMIT_CONTROL`（[错误码](https://help.aliyun.com/zh/sms/developer-reference/api-error-codes)）。
- **内容安全与变量规则**（[错误码](https://help.aliyun.com/zh/sms/developer-reference/api-error-codes)、[测试短信-参数排查](https://help.aliyun.com/zh/sms/user-guide/send-test-messages-1)）：
  - 内容违规：`isv.SMS_CONTENT_ILLEGAL`（含禁止内容）；`isv.UNSUPPORTED_CONTENT`（繁体字/emoji/`【】〖〗m²•①★`等非常用字符会拦截）；通知模板发营销文案会报 `isv.SMS_CONTENT_MISMATCH_TEMPLATE_TYPE`。
  - 黑名单管控：`isv.BLACK_KEY_CONTROL_LIMIT`——命中退订/投诉黑名单的号码**不支持下发且无法解除**（阿里云“解除黑名单”功能已于 2023-12-28 下线）。
  - 变量：`TemplateParam` 必须是 JSON 字符串；变量名/个数必须与模板定义一致（`isv.INVALID_JSON_PARAM` / `isv.TEMPLATE_MISSING_PARAMETERS` / `isv.SMS_TEMPLATE_ILLEGAL`）；验证码模板变量为 4~6 位纯数字。
  - 短信长度 = 签名字数 + 模板字数，超长按多条计费（[使用须知](https://help.aliyun.com/zh/sms/user-guide/usage-notes)）。

### 3.5 回执与错误码

- **同步返回 ≠ 送达**：`SendSms` 返回 `Code=OK` 仅表示提交成功；送达状态需要**回执**。三种获取方式（[SendSms 文档](https://help.aliyun.com/zh/sms/developer-reference/api-dysmsapi-2017-05-25-sendsms)、[测试短信发送](https://help.aliyun.com/zh/sms/user-guide/send-test-messages-1)、[SmsReport](https://help.aliyun.com/zh/sms/developer-reference/smsreport)）：
  1. **轻量消息队列（原 MNS）消费模式**：短信服务推送 `SmsReport` 消息事件到队列（命名 `Alicom-Queue-xxx`），可配置 Ram 账号消费；`SmsReport` 字段含 `send_time / report_time / success / err_msg / err_code / phone_number / sms_size / biz_id / out_id`。
  2. **HTTP 批量推送模式**：配置回调 URL，平台批量推送（[测试短信-回执消息](https://help.aliyun.com/zh/sms/user-guide/send-test-messages-1)提及其存在；具体配置流程详见官方“回执消息配置”文档）。
  3. **被动查询/控制台**：凭 `BizId` 调 `QuerySendDetails` 查询；控制台「业务统计 > 发送记录」查看。
- **API 错误码（发送阶段，官方列表摘要）**（[国内消息API错误码](https://help.aliyun.com/zh/sms/developer-reference/api-error-codes)）：

| 错误码 | 含义 | 对 MIGAO 的处置建议 |
|---|---|---|
| `isv.BUSINESS_LIMIT_CONTROL` | 触发云通信流控限制（**针对手机号维度**，该号可能收到多平台验证码短信，即使本平台只发 1 条也可能触发） | 提示“发送过于频繁，请稍后再试”；调控制台频控阈值；开启验证码防盗刷 |
| `isv.DAY_LIMIT_CONTROL` / `isv.MONTH_LIMIT_CONTROL` | 到达控制台设置的日/月发送总量限额 | 告警 + 充值/调阈值 |
| `isv.SMS_SIGNATURE_SCENE_ILLEGAL` | 签名与模板类型不一致（如验证码签名发通知模板） | 配置侧排查签名/模板类型 |
| `isv.SMS_SIGNATURE_ILLEGAL` / `isv.SIGN_STATE_ILLEGAL` | 找不到签名 / 签名不可用 | 检查签名与模板是否审核通过、是否同账号 |
| `isv.SMS_TEMPLATE_ILLEGAL` | 模板 Code 有误或变量不匹配 | 检查 `TemplateCode`/`TemplateParam` |
| `isv.OUT_OF_SERVICE` | 余额不足业务停机 | 欠费告警（可与账单/云监控联动） |
| `isv.PRODUCT_UN_SUBSCRIPT` / `isv.PRODUCT_UNSUBSCRIBE` | 未开通对应云通信产品 | 确认已开通短信服务 |
| `isv.DENY_IP_RANGE` | 发送 IP 非中国内地 | 生产环境 IP 必须在中国内地 |
| `isv.SIGN_SOURCE_ILLEGAL` | 签名来源不符合现行规范 | 按新政策换用企事业单位名/商标名签名（[签名规范](https://help.aliyun.com/zh/sms/user-guide/signature-specifications-1)） |
| `PORT_NOT_REGISTERED` | 端口/签名尚未完成实名制报备 | **等待报备完成（5-10 个工作日），先用三网少量多次测试验证**（[错误码](https://help.aliyun.com/zh/sms/developer-reference/api-error-codes)、[测试短信](https://help.aliyun.com/zh/sms/user-guide/send-test-messages-1)） |

- 回执端（送达阶段）错误码见 [国内消息发送状态回执错误码](https://help.aliyun.com/zh/sms/developer-reference/delivery-receipt-error-codes)（如 `DELIVERED` 成功 / `CONTENT_ERROR` 无退订 / `USER_REJECT` 用户退订 / `NO_ROUTE` 无可用通道等）。

---

## 4. 配套 / 替代方案

### 4.1 语音验证码 / 语音通知

- **产品**：阿里云「语音服务」（VMS），能力含语音验证码（`SingleCallByTts`，呼叫应答后播报含验证码音频）、语音通知（`SingleCallByVoice`）、IVR、智能外呼等（[功能介绍](https://help.aliyun.com/zh/vms/product-overview/product-function-node-dyvms)）。**与短信是不同的产品/控制台/套餐，套餐互不通用**（号码认证文档明确写明其“短信认证套餐包与通用短信服务套餐包额度不互通”，语音与短信分属独立产品计费，具体互通条款以控制台为准）。
- **计费（调研日期 2026-09-07，[语音服务价格页](https://cn.aliyun.com/ntms/price/detail/dyvms)）**：预充值、按量、阶梯计费（不满一分钟按一分钟）——语音验证码 **0.080 元/条起**（≤5 万条档，随量递减至 0.050）；语音通知（含点击拨号、智能外呼通话）**0.110 元/分钟起**；另需语音号码月租。相比短信验证码 0.045 元/条，语音验证码贵约 78%，且无文本记录。
- **是否值得做短信兜底**：**有价值但优先级低**。典型兜底场景：短信被拦截/号码停机/老人机不便输入 vs 语音播报。由于按量价更高、需要额外资质/话术报备，建议**先不做主动兜底**，仅保留“验证码登录失败时的人工客服转电话确认”流程即可；若后期出现可量化的短信到达率问题（如 `isv.BUSINESS_LIMIT_CONTROL` 或运营商拦截导致用户收不到），再评估接入。

### 4.2 号码认证（一键登录）与短信验证码对比

（仅客观陈述，不替项目拍板。）

| 维度 | 号码认证 — 一键登录 | 短信验证码 |
|---|---|---|
| 交互 | 用户点击按钮，授权页显示脱敏手机号（151\*\*\*\*6600），确认即登录（[功能](https://help.aliyun.com/zh/pnvs/product-overview/number-authentication)） | 输入手机号 → 收码 → 输入验证码 |
| 计费 | **0.050 元/次起**（成功返回号码才计费；本机号码校验无论是否一致都计费）；套餐包 100 次 5 元起；**无免费测试包**（调试唤起不计费，服务端 `GetMobile` 成功返回才计费）（[PNVS 定价](https://help.aliyun.com/zh/pnvs/product-overview/product-pricing)） | 0.045 元/条起（未送达不计费） |
| 支持端 | **Android / iOS / HarmonyOS / uni-app / H5**（H5 需用户补填中间四位）；**官方支持列表未包含微信小程序**（[功能](https://help.aliyun.com/zh/pnvs/product-overview/number-authentication)） | 任何能收短信的手机 |
| 局限 | 依赖 SIM 卡 + 数据网络；双卡、WiFi 环境需降级处理；**小程序/浏览器（非 H5 认证）场景不可直接用** | 依赖短信通道，有频控与轰炸风险，需防刷 |
| 附加收益 | 不暴露发码接口，天然防短信轰炸（官方防盗刷文档明确推荐“使用一键登录认证”防批量盗刷，[验证码防盗刷](https://help.aliyun.com/zh/sms/user-guide/verification-code-scams-and-message-flooding-1)） | 兼容性广、留存短信证据 |
| 同一产品下的补充能力 | 图形认证 0.006 元/次（可做人机校验前置，替代自研滑块）；融合认证通信服务 0.042 元/次起（[PNVS 定价](https://help.aliyun.com/zh/pnvs/product-overview/product-pricing)） | — |

**对 MIGAO 的客观结论**：MIGAO 的 B 端登录在桌面浏览器 + C 端兼有微信小程序。**小程序端不在一键登录官方支持列表**，因此一键登录**不能覆盖全部现有登录入口**，只能作为 App/部分 H5 的补充登录方式；它的防轰炸特性适合登录频发的 C 端。是否引入属于产品决策，若引入建议分端灰度并保留短信验证码兜底。另外「短信认证」（PNVS 子能力，0.06 元/次起，系统预置签名模板，**对接 API 即可用、无端侧限制**）被官方作为“无法提供企业资质的个人用户”的替代推荐（[PNVS 定价](https://help.aliyun.com/zh/pnvs/product-overview/product-pricing)、[使用须知](https://help.aliyun.com/zh/sms/user-guide/usage-notes)）——注意它是预置模板的特定接口，表达自由度低，不适合作为 MIGAO 通知渠道。

---

## 5. 与 MIGAO 现状的映射与接入路线

### 5.1 已具备（复用现有代码）

| 现状 | 与官方要求对照 | 结论 |
|---|---|---|
| `SmsConfig.java`：`com.aliyun.dysmsapi20170525.Client` + `endpoint=dysmsapi.aliyuncs.com` + 配置项 `aliyun.sms.{access-key-id, access-key-secret, sign-name, template-code}`（[源码](backend/admin-api/src/main/java/com/migao/admin/config/SmsConfig.java)） | 官方全局接入点、推荐 SDK 版本完全一致（[集成概览](https://help.aliyun.com/zh/sms/developer-reference/using-openapi)） | ✅ 直接复用；建议把 AK 改为 RAM 子账号最小权限（`AliyunDysmsFullAccess`）并支持轮转，避免主账号 AK |
| `SmsService.java`：`SendSmsRequest(SignName/TemplateCode/TemplateParam{"code":...})` 预留骨架（[源码](backend/admin-api/src/main/java/com/migao/admin/service/SmsService.java)） | 与官方 SDK 示例逐字段一致（[SendSms](https://help.aliyun.com/zh/sms/developer-reference/api-dysmsapi-2017-05-25-sendsms)）；验证码模板建议单条发送（与官方建议一致） | ✅ 放开注释即可用 |
| `SmsService` 防刷：60s 发码间隔 + Redis 日计数 + 5 分钟失败锁定 + 验证码时效 + 手机号脱敏日志 | 官方防盗刷建议“验证码获取最小间隔一般限制为 60 秒”，并建议失败锁定/异常识别（[验证码防盗刷](https://help.aliyun.com/zh/sms/user-guide/verification-code-scams-and-message-flooding-1)） | ✅ 基础扎实，需按 §6 补强 |
| 设计文档：通知渠道表含 sms（工单状态变更/发货/超时预警/AI 异常预警）+「短信服务」设置页（服务商/AK-SK/签名/模板）（[admin-dashboard-design.md](docs/design/admin-dashboard-design.md)） | 与「发送方 - 签名 - 模板」模型一致 | ✅ 设置页字段与 `aliyun.sms.*` 配置直接对应 |

### 5.2 缺口（需新做）

1. **账号与资质（无代码）**：企业实名认证 → 短信服务开通 → 申请短信资质（约 2 工作日）→ 申请签名（2 小时内审核）→ 运营商签名实名制报备（5-10 工作日）→ 申请模板并审核。⚠️ **跨部门事项，需商务/法务提前准备营业执照、法人与管理员证件**（管理员须“一人一企”，见[资质材料说明](https://help.aliyun.com/zh/sms/user-guide/qualification-application-description)）。
2. **签名策略（SaaS 多租户设计决策，待拍板）**：阿里云短信按**账号维度**管理签名，推荐 MIGAO 采用**平台统一企业签名 + 统一模板**，租户差异体现在模板变量与内容（如店铺名/工单号）；若个别大租户要求自有签名，需“他用资质 + 委托授权书”单独申请（审核与报备成本高，见[签名规范](https://help.aliyun.com/zh/sms/user-guide/signature-specifications-1)）。该策略需与产品讨论后写入设计。
3. **回执消费**：新增后台消费者——轻量消息队列（原 MNS）或 HTTP 批量推送接收 `SmsReport`，落库“发送记录”，用于失败重试决策、发送成功率统计、发送记录页展示（当前设计文档已有“发送记录”页诉求）（[SmsReport](https://help.aliyun.com/zh/sms/developer-reference/smsreport)）。
4. **错误码与告警**：`isv.BUSINESS_LIMIT_CONTROL`→租户侧友好提示；`isv.OUT_OF_SERVICE`/日限额→运维告警（可接现有告警渠道）。
5. **幂等与重试**：`SendSms` 不幂等，需业务侧防重（如 Redis 一次性标记 + `OutId`/`BizId` 关联），验证码生成与发送解耦时避免重复扣费（[SendSms 文档](https://help.aliyun.com/zh/sms/developer-reference/api-dysmsapi-2017-05-25-sendsms)）。
6. **验证码类模板变量**：模板变量须符合“4~6 位纯数字”等规范，MIGAO 现有 6 位数字码格式与之一致，落地时按模板实际定义传参（[测试短信-参数排查](https://help.aliyun.com/zh/sms/user-guide/send-test-messages-1)）。
7. **多环境管理**：dev/CI 保持 bypass，但**生产必须 `sms.bypass-code` 为空（fail-closed 已具备）+ 移除硬编码 123456 逻辑（Issue #2616）**；同时 `aliyun.sms.*` 走 secrets 管理，不在配置文件明文。

### 5.3 上线 Checklist

**阶段 0 — 账号准备（商务/运维，预留 1-2 周，可并行）**
- [ ] 阿里云账号**企业实名认证**（确认主体与 MIGAO 公司一致，或规划他用资质）
- [ ] 开通短信服务；创建 **RAM 用户 + AccessKey**（最小权限 `AliyunDysmsFullAccess`），配置到 `aliyun.sms.*`
- [ ] 确认发送出口 IP 为中国内地（`isv.DENY_IP_RANGE` 规避）

**阶段 1 — 资质/签名/模板（在线操作，时效见 §3.2）**
- [ ] 提交短信资质：营业执照 + 法定代表人 + 管理员（身份证/手机号），等待审核（约 2 工作日）
- [ ] 申请签名：**企事业单位名/已注册商标名**（一个自然日 1 个名额）；触发运营商报备（5-10 个工作日）
- [ ] 申请模板：「验证码登录」验证码模板（变量 4-6 位数字）、「工单状态变更/发货通知/超时预警/AI 异常预警」通知类模板（文案注意**中性签名限制与禁发内容清单**，见[签名规范](https://help.aliyun.com/zh/sms/user-guide/signature-specifications-1)）
- [ ] 控制台绑定 5 个测试手机号；配置回执（MNS 队列或 HTTP 推送）、发送频率设置、日/月总量阈值、防盗刷监控、发送量预警

**阶段 2 — 代码改造（TDD 流程，遵守项目铁律与 case_ids）**
- [ ] 放开 `SendSms` 调用（去掉注释、以配置驱动），保持 `TemplateParam={"code":...}` 传参
- [ ] 实现回执消费者（MNS/HTTP）+ 发送记录落库与查询接口
- [ ] 错误码映射与租户侧友好提示；欠费/限额告警
- [ ] 幂等（防重发）与超时后“查回执再重试”逻辑
- [ ] 新增/修改测试文件头部声明 `# case_ids:`（QA Growth Gate 要求）

**阶段 3 — 验证与灰度上线**
- [ ] 测试短信三网验证：**移动/联通/电信各 10-20 条/天，连续 5-7 个工作日**（签名报备验证/通道激活，见[测试短信发送](https://help.aliyun.com/zh/sms/user-guide/send-test-messages-1)）
- [ ] 灰度：先开「AI 客服异常预警」等低敏通知 → 再开 B 端验证码登录 → C 端验证码登录
- [ ] **移除 bypass（Issue #2616）**：生产 `sms.bypass-code` 置空已验证 fail-closed；删除硬编码 123456 万能码路径
- [ ] 上线后观察 72h：发送成功率（回执口径）、频控触发率（`isv.BUSINESS_LIMIT_CONTROL`）、盗刷监控告警、账单成本
- [ ] 三把工具：`./verify-all.sh gate`、`./check-ui-regression.sh`；跨模块改动加 `./contract-check.sh`；PR 关联 Issue（body 写 `Closes #2616` 等）

---

## 6. 风险与注意

1. **短信轰炸 / 验证码盗刷（最高优先）**：攻击者对 `POST /api/auth/sms/send` 批量打号 → 直接烧钱 + 骚扰用户。现有 Redis 60s 频控 + 失败锁定是官方建议的基线（官方明确“验证码获取最小间隔一般限制为 60 秒”，[验证码防盗刷](https://help.aliyun.com/zh/sms/user-guide/verification-code-scams-and-message-flooding-1)），接入上线前必须补：① 图形验证码/验证码 2.0/图形认证等**人机前置校验**（官方建议“获取验证码前需先通过图形交互”）；② **IP 维度限流**（官方明文“短信服务不支持按 IP 设置黑名单”，IP 层防护必须自己做）；③ 控制台开启**验证码防盗刷监控 + 发送频率设置 + 日/月发送总量阈值**（达限额自动暂停发送）；④ 生产用 RAM 子账号 AK 并定期轮转；⑤ 异常止损预案（临时停接口/停模板）。
2. **频控衔接（现有 Redis 防刷 vs 平台频控）**：平台频控默认“验证码每分 1、每时 5、每自然日 10”（同签名同号码），触发即 `isv.BUSINESS_LIMIT_CONTROL`——**注意该限制按手机号维度累计**（含其他平台的短信），即使本平台只发 1 条也可能触发。MIGAO 的 Redis 防刷（60s 间隔 + 日计数）须**小于等于平台频控**并给出友好提示，避免用户侧“收不到码”而无感知；重新获取按钮倒计时建议与平台每分 1 条对齐。
3. **合规红线**：① 签名必须“企事业单位名/已注册商标名”，中性签名（如“客服通知”“温馨提示”）不通过，**2026-04-27 起“已上线 APP”来源不再支持**（[公告](https://help.aliyun.com/zh/sms/product-overview/domestic-sms-signatures-no-longer-support-launched-app-as-a-source)），存量此类签名会发送失败（[报备时效提示](https://help.aliyun.com/zh/sms/product-overview/important-reminder-on-reporting-time-limit-of-real-name-system-for-sms)）；② 通知模板禁止营销文案；③ 内容禁止清单长（金融推广、贷款催款等，工单催办类文案需避开营销措辞）；④ 发送失败可能源于未完成报备，错误码可能非典型，需按报备状态排查（[错误码](https://help.aliyun.com/zh/sms/developer-reference/api-error-codes)）。
4. **新国标提示（一句，不展开）**：GB/T 47746-2026《顾客联络服务 人工与智能客户服务协同要求》已于 **2026-09-01 实施**，对 AI 客服与人工客服协同（含通知触达、人机交接边界）提出合规要求，建议在 AI 客服/工单通知的产品设计评审中对照评估（标准详情见[国家标准索引](https://www.antpedia.com/standard/2079511180.html)，实施新闻见[第三方报道](https://www.szaicx.com/scdt/26391.html)，第三方资料仅供参考）。
5. **国际短信差异（若未来出海）**：发送即收费、失败也计费；且“不支持从境外向中国内地发送”（[国际定价](https://help.aliyun.com/zh/sms/product-overview/pricing-of-messages-sent-to-countries-or-regions-outside-chinese-mainland)）。
6. **易变信息清单（均以阿里云控制台/最新官方文档为准）**：国内短信单价与套餐价（2026-05-20 已调价一次）；免费额度/新用户权益（当前未查到免费条数）；资质/签名/模板审核时长与运营商报备时效；签名来源政策与频控默认值；语音与 PNVS 价格；`SmsReport` 队列/推送配置入口（[回执消息FAQ](https://help.aliyun.com/zh/sms/developer-reference/receipt-message-faq)）。

---

## 7. 参考来源列表

**官方一手来源（均已在正文引用）：**

- 短信服务产品页：[短信服务 SMS 产品页](https://www.aliyun.com/product/sms)
- 产品概述：[什么是短信服务](https://help.aliyun.com/zh/sms/product-overview/what-is-alibaba-cloud-sms)、[短信服务功能特性（消息类型）](https://help.aliyun.com/zh/sms/product-overview/product-function-node-dysms)、[计费概述](https://help.aliyun.com/zh/sms/product-overview/billing-overview)
- 使用与审核：[短信服务使用须知（权益/审核时间/申请数量/冻结）](https://help.aliyun.com/zh/sms/user-guide/usage-notes)、[资质材料说明](https://help.aliyun.com/zh/sms/user-guide/qualification-application-description)、[短信签名规范](https://help.aliyun.com/zh/sms/user-guide/signature-specifications-1)、[申请短信签名](https://help.aliyun.com/zh/sms/user-guide/create-signatures)、[设置短信发送频率](https://help.aliyun.com/zh/sms/user-guide/configure-delivery-frequency-and-whitelist)、[验证码防盗刷](https://help.aliyun.com/zh/sms/user-guide/verification-code-scams-and-message-flooding-1)、[快速测试短信发送](https://help.aliyun.com/zh/sms/user-guide/send-test-messages-1)、[数字短信新手指引](https://help.aliyun.com/zh/sms/user-guide/get-started-with-digital-sms)
- 计费与定价：[国内短信服务定价](https://help.aliyun.com/zh/sms/product-overview/billing-of-messages-sent-to-chinese-mainland)、[【2026-04-20】国内短信服务价格调整公告（2026-05-20 生效）](https://help.aliyun.com/zh/sms/product-overview/notice-on-price-adjustment-for-domestic-sms-services-2604)、[国际/港澳台短信服务定价](https://help.aliyun.com/zh/sms/product-overview/pricing-of-messages-sent-to-countries-or-regions-outside-chinese-mainland)
- 开发参考：[使用 OpenAPI 调试短信服务（版本说明/接入点/身份）](https://help.aliyun.com/zh/sms/developer-reference/using-openapi)、[SendSms - 发送短信](https://help.aliyun.com/zh/sms/developer-reference/api-dysmsapi-2017-05-25-sendsms)、[SmsReport - 回执消息（MNS 消费模式）](https://help.aliyun.com/zh/sms/developer-reference/smsreport)、[回执消息FAQ](https://help.aliyun.com/zh/sms/developer-reference/receipt-message-faq)、[国内消息API错误码](https://help.aliyun.com/zh/sms/developer-reference/api-error-codes)、[国内消息发送状态回执错误码](https://help.aliyun.com/zh/sms/developer-reference/delivery-receipt-error-codes)
- 动态与公告：[2026-04-27 国内短信签名来源不再支持“已上线APP”](https://help.aliyun.com/zh/sms/product-overview/domestic-sms-signatures-no-longer-support-launched-app-as-a-source)、[2026-02-06 签名实名制报备时效重要提示](https://help.aliyun.com/zh/sms/product-overview/important-reminder-on-reporting-time-limit-of-real-name-system-for-sms)
- 语音服务：[语音服务功能特性](https://help.aliyun.com/zh/vms/product-overview/product-function-node-dyvms)、[语音服务价格详情页](https://cn.aliyun.com/ntms/price/detail/dyvms)
- 号码认证服务（PNVS）：[号码认证功能（一键登录/本机号码校验）](https://help.aliyun.com/zh/pnvs/product-overview/number-authentication)、[号码认证服务产品计费](https://help.aliyun.com/zh/pnvs/product-overview/product-pricing)、[SDK 集成号码认证服务](https://help.aliyun.com/zh/pnvs/developer-reference/sdk-integration-overview/)
- 易混淆产品：[什么是 Chat App 消息服务](https://www.alibabacloud.com/help/zh/chatapp/product-overview/what-is-chatapp-message-service)、[移动推送产品页](https://www.aliyun.com/product/cps)

**第三方来源（辅助佐证，已标注“仅供参考”）：**

- [阿里云云市场——三网短信服务（第三方服务商商品）](https://market.aliyun.com/detail/cmapi025016)
- [GB/T 47746-2026《顾客联络服务 人工与智能客户服务协同要求》标准索引](https://www.antpedia.com/standard/2079511180.html)（标准详情页，第三方资料）
- [“我国首个 AI 客服协同国标 9 月 1 日实施”产业新闻](https://www.szaicx.com/scdt/26391.html)（第三方资料，仅供参考）
- [阿里云开发者社区——isv.BUSINESS_LIMIT_CONTROL 原因与限流排查（社区问答，第三方资料，仅供参考）](https://developer.aliyun.com/article/1751150)

**未查到 / 待确认项汇总：**

1. 国内短信**免费额度/月度免费条数**：未查到现行官方说明（测试短信亦计费）；控制台新用户权益以实际为准。
2. **多媒体短信（数字短信/卡片短信）单价**：未深查，需用时另行调研。
3. **微信小程序使用号码认证一键登录**：官方支持列表（Android/iOS/HarmonyOS/uni-app/H5）未含小程序，能否有定制方案待与阿里云确认。
4. **旧版（2015/2016 时代）短信 API**：未查到仍在维护的旧版官方文档，现行唯一版本为 2017-05-25。
5. 语音/短信**套餐互通的明文条款**：分属独立产品与控制台，PNVS 文档明确其“短信认证套餐与通用短信套餐”额度不互通；语音与短信之间的具体条款以控制台为准（未查到明文）。
6. GB/T 47746-2026 中对通知渠道/短信触达的**具体条文**：本次按要求未展开，涉及 AI 客服合规评审时需另行研读国标全文。
7. 号码认证服务的**企业认证开通要求**：未逐项核实，以控制台开通流程为准。