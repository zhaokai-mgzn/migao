-- 企业基础信息：租户品牌与通知设置落库（幂等）
-- 此前前端「企业基础信息」页的 Logo / 通知设置仅存于前端 state，刷新即丢；
-- companyName 直接写 tenants.name，logo / 通知开关需独立列承载。
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo VARCHAR(512);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS notification_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS notification_email VARCHAR(128);
