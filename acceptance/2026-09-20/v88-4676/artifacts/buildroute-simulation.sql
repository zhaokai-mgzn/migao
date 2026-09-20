\pset pager off
\echo '=== 35 格版（设计稿谓词 NOT IN (''裁剪'')）终态 ==='
select 'tenant '||tenant_id||' 退场='||count(*) filter (where deleted=1)||' 存活='||count(*) filter (where deleted=0)
  from production_operation_positions group by tenant_id order by tenant_id;
select '布料主线 = '||mainline::text from production_route_templates where tenant_id=1 and name='布料工序路线';
\echo '--- 模拟 buildRoute：布料单逐步查 applicable（无格 ⇒ applicable==null ⇒ 静默 continue）---'
with ml(step,ord) as (
  select value, ordinality from jsonb_array_elements_text(
    (select mainline from production_route_templates where tenant_id=1 and name='布料工序路线')) with ordinality)
select ml.ord||'. '||ml.step||' × 布料 → '||coalesce(
  (select case when p.applicable then 'applicable=TRUE  ✅ 实例化'
               else 'applicable=FALSE ❌ 被滤掉' end
     from production_operation_positions p
    where p.tenant_id=1 and p.logical_name=ml.step and p.position='布料' and p.deleted=0),
  '无格 ⇒ applicable=null ❌ 静默 continue')
from ml order by ml.ord;
with ml(step,ord) as (
  select value, ordinality from jsonb_array_elements_text(
    (select mainline from production_route_templates where tenant_id=1 and name='布料工序路线')) with ordinality)
select '👉 布料单实际实例化工序数 = '||count(*) from ml
 where exists (select 1 from production_operation_positions p
                where p.tenant_id=1 and p.logical_name=ml.step and p.position='布料'
                  and p.deleted=0 and p.applicable);
