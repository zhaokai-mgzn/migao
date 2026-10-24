-- 智能每日经营简报：企业开关**默认改为开启**（2026-10-18 用户裁定「这个开关改成默认开启」）
--
-- 口径（用户逐字：「只改默认，不动存量」）：
--   · 只改**列默认值** ⇒ 新建租户默认开；
--   · **不做任何 UPDATE** ⇒ 存量租户保持各自当前取值（想用的自己去设置里打开）。
--
-- 读面语义（DailyBriefingService）：`NULL` = 从没选过 ⇒ 按开启处理；只有显式 `false` 才熔断。
ALTER TABLE tenants ALTER COLUMN briefing_enabled SET DEFAULT TRUE;
