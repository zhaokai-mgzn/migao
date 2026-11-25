# 微信客服 AI 智能客服 — 上线与运维 Runbook

> 适用版本：PR1~PR4（表结构 / 回调 / sync / outbox / 判定 / 转人工 / 卡片降级）。
> 关联设计：`docs/design/wechat-kf-ai-customer-service.md`。

## 1. 前置条件（缺一不可）

| 项 | 要求 | 说明 |
|---|---|---|
| 企业微信主体 | **已认证** | 未认证主体 `send_msg` 返回 `fail_type=8`/相关错误 |
| 微信客服 | 已开通 | 管理后台 → 应用管理 → 微信客服 |
| 客服账号 | ≥1 个 | `open_kfid` 从客服账号详情获取 |
| 应用权限 | 微信客服 | 自建应用需勾选「微信客服」权限；第三方应用需 suite 授权 |
| 可信 IP | 已配置 | 调用 `gettoken/sync_msg/send_msg` 的出口 IP |
| 回调 URL | 可公网访问 | `https://api.migaozn.com/api/kf/callback` |
| 至少一名成员 | 已登录企微 | 否则 `fail_type=11` |

## 2. 环境变量

```bash
WECHAT_KF_ENABLED=true
WECHAT_KF_TOKEN=<回调 Token，企微后台配置的同一个值>
WECHAT_KF_ENCODING_AES_KEY=<43 位 EncodingAESKey>
WECHAT_KF_RECEIVE_ID=<自建=corpid；第三方=suiteid>
WECHAT_KF_SECRET_MASTER_KEY=<32+ 字节随机串，用于 SecretCipher 信封加密>
WECHAT_KF_SYNC_INTERVAL_MS=30000
WECHAT_KF_CLAIM_STALE_SECONDS=300
WECHAT_KF_OUTBOX_INTERVAL_MS=5000
WECHAT_KF_OUTBOX_STALE_SECONDS=120
```

- `WECHAT_KF_SECRET_MASTER_KEY` **必填**：未配置时启用即启动失败（fail-closed），不允许空密钥加密。
- 主密钥轮换：新 key 加密新凭据；旧密文用旧 key 解密（`SecretCipher` 密文内带 keyId；当前实现默认 keyId=`default`，轮换需同批迁移）。
- 回调 Token/AESKey 与企微后台**逐字一致**；不一致表现为 URL 验证 400/签名失败。

## 3. 数据库

```bash
# 迁移由 MigrationRunner 自动执行；确认两条已应用
V217__create_wechat_kf_tables.sql
V218__kf_sync_claim_and_external_msg_id.sql
```

渠道登记示例（`secret_enc` 必须用 `SecretCipher` 加密后的值，不能明文）：

```sql
INSERT INTO kf_channels (id, tenant_id, corp_id, open_kfid, auth_mode, status, secret_enc)
VALUES ('ch_001', 1, 'ww_corp_id', 'wk_open_kfid', 'self_built', 'active', 'v1:default:<base64>');
```

> 第三方应用走 `kf_suites` + `permanent_code`；本期回调按 suite 级 Token/AESKey 解密，渠道按 `corp_id + open_kfid` 反查。

## 4. 企微后台配置

1. 应用管理 → 微信客服 → 「API 接收事件」：
   - URL：`https://api.migaozn.com/api/kf/callback`
   - Token：与 `WECHAT_KF_TOKEN` 一致
   - EncodingAESKey：与 `WECHAT_KF_ENCODING_AES_KEY` 一致
2. 保存时企微会发 `GET ...?echostr=...`；服务端必须在 **1 秒**内返回明文，否则保存失败。
3. 客服账号 → 接待人员：至少一名成员已登录企微（`fail_type=11` 的根因）。
4. 可信 IP：加入 admin-api 出口 IP。

## 5. 上线步骤

1. 执行数据库迁移，确认 `kf_channels` 有渠道行。
2. 配置环境变量，重启 admin-api；确认日志无 `KF_SECRET_MASTER_KEY 未配置`。
3. `curl -X POST https://api.migaozn.com/api/internal/kf/decide -H 'X-Service-Token: ...' -d '{"tenant_id":1,"session_id":"s","state":0,"text":"你好"}'` → `AI_REPLY`。
4. 企微后台保存回调 URL，确认 `echostr` 验证通过。
5. 用测试客户发「你好」：`kf_inbox` 出现行、`kf_sync_cursor.dirty_at` 非空、30s 内 `sessions/session_messages` 出现消息。
6. 调 `/api/internal/kf/reply` 入队，确认 `kf_outbox` pending → sending → accepted，客户收到消息。
7. 发「转人工」：确认 `/api/internal/kf/decide` 返回 `ESCALATE_HUMAN`，`/transfer` 后 `agent_sessions` 出现 waiting，企微会话进入接待池。
8. 观察 24h：回调失败率、sync 延迟、outbox failed/unknown、5 条预算触发次数。

## 6. 验证清单

- [ ] URL 验证 1s 内返回明文
- [ ] 重复回调只入一行 `kf_inbox`，dirty 仍刷新
- [ ] `sync_msg` 空列表 + `has_more=1` 不死循环
- [ ] 同一 `msgid` 重复不重复落 `session_messages`
- [ ] 5 条预算：第 6 条返回 429，不发出
- [ ] `msg_send_fail` 按 `sent_msgid` 回写 failed + fail_type
- [ ] 转人工后 AI 不再回复（state=2/3）
- [ ] 工作台坐席回复能到客户微信
- [ ] 租户 A 查不到租户 B 的 kf 行

## 7. 故障处置

| 现象 | 根因 | 处置 |
|---|---|---|
| 回调 400/签名失败 | Token/AESKey 不一致 | 逐字核对企微后台与 env |
| `42001` access_token 过期 | 缓存过期/时钟漂移 | 自动刷新；检查服务器时间 |
| `95014` | 客服账号未激活/无接待人员 | 企微后台激活客服账号 |
| `48001` | 应用未授权微信客服 | 补权限/重新授权 |
| `fail_type=4` | 超 48h | 关窗口，等客户再发 |
| `fail_type=6` | 超 5 条 | 停止自动发送，转人工或等客户下一条 |
| `fail_type=8` | 主体未认证 | 商户去认证 |
| `fail_type=11` | 无成员登录企微 | 让至少一人登录 |
| `fail_type=13` | 安全限制 | 停止发送 + 告警 |
| outbox `unknown` 堆积 | 网络超时/结果未知 | 按 `msgid` 重试安全；人工核对客户是否收到 |

## 8. 观测与告警

日志关键字：
- `[kf-callback]`：验签失败、未登记渠道、inbox 落库失败
- `[kf-sync]`：claim 失败、单条落库失败、孤儿 `msg_send_fail`
- `[kf-outbox]`：send_msg 失败 errcode、unknown
- `[kf-transfer]`：trans 失败、工作台会话回滚

建议告警：
- `kf_sync_cursor.dirty_at` 超过 5 分钟未清
- `kf_outbox` pending 超过 10 分钟
- `kf_outbox` failed/unknown 10 分钟 > 20 条
- 回调 5xx 比例 > 1%

## 9. 回滚

1. `WECHAT_KF_ENABLED=false` 重启：回调/worker/outbox 全部停止（端点 404），存量数据保留。
2. 企微后台删除回调 URL，停止事件推送。
3. 如需结束进行中会话：调 `service_state/trans(4)`；`kf_session_remote.closed_at` 置位。
4. **不要删表/删迁移**：V217/V218 已进入迁移账本；回滚只停功能，不回滚 schema。

## 10. 已知限制与风险

- **卡片不支持**：米宝交互卡在微信客服降级为文本/链接/编号选项；表单需客户直接回复文字。
- **AI 判定当前是规则短路**（state/人工词/风险词），LLM 语义判定待接；高风险词命中直接转人工。
- **48h/5 条**是企微硬限制，换卡片无用；运营需接受“窗口会关”。
- **回调不保证 100%**：worker 固定 30s 拉取兜底；不要依赖“有未读”。
- **RLS 未生效**：隔离靠 MyBatis 租户拦截 + 显式 `tenant_id`；真 PG 隔离用例在 PR3 已覆盖。
- **`trans(1)` 未文档化**：MVP 只用 `trans(2)` 进接待池；人工接入由企微接待台完成。
- **access_token 进程内缓存**：多实例各自缓存；重启后首次请求会刷新。
