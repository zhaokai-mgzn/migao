#!/usr/bin/env python3
"""合并判定 — 单issue闭环。close:关issue。hold:加标签。block:重打needs-verification+BLOCK_LOG评论。"""
import argparse, json, os, re, subprocess, time
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/opt/youke")).resolve()
QA_RESULT_ROOT = Path(os.getenv("QA_RESULT_ROOT", "/opt/qa-results"))
MAX_BLOCK_DEPTH = 3

def _get_issue_body(iid): 
    p=subprocess.Popen(["gh","issue","view",str(iid),"--json","body"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(PROJECT_ROOT))
    out,_=p.communicate()
    try: return json.loads(out.decode()).get("body","")
    except: return ""

def _parse_contract(body): 
    m=re.search(r"<!-- CONTRACT_JSON\s*(.*?)\s*-->",body,re.DOTALL)
    if not m: return {}
    try: return json.loads(m.group(1))
    except: return {}

def _get_block_depth(iid):
    p=subprocess.Popen(["gh","issue","view",str(iid),"--comments","--json","comments"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(PROJECT_ROOT))
    out,_=p.communicate()
    try:
        max_d=0
        for c in json.loads(out.decode()).get("comments",[]):
            m=re.search(r'"block_depth"\s*:\s*(\d+)',c.get("body",""))
            if m: max_d=max(max_d,int(m.group(1)))
        return max_d+1
    except: return 1

def _log_block(iid,depth):
    p=QA_RESULT_ROOT/"block-rate.jsonl"; p.parent.mkdir(parents=True,exist_ok=True)
    with open(p,"a") as f: f.write(json.dumps({"timestamp":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"issue_id":iid,"block_depth":depth})+"\n")

def _block_alert():
    p=QA_RESULT_ROOT/"block-rate.jsonl"
    if not p.exists(): return ""
    cutoff=time.time()-7*86400; blocks,roots=0,set()
    with open(p) as f:
        for l in f:
            try:
                e=json.loads(l)
                if time.mktime(time.strptime(e["timestamp"],"%Y-%m-%dT%H:%M:%SZ"))>=cutoff: blocks+=1; roots.add(e.get("issue_id",0))
            except: pass
    if blocks>=5 and len(roots)>=3 and int(100*blocks/max(blocks,10))>30:
        return f"⚠️ Block率告警：近7天{blocks}次/{len(roots)}个issue。建议检查reviewer覆盖和业务真值质量。"
    return ""

def load_result(iid,kind):
    p=QA_RESULT_ROOT/str(iid)/f"{kind}.json"
    if not p.exists(): return None
    with open(p) as f: return json.load(f)

def judge(primary,reviewer,cloud=None):
    ps=primary.get("status","skip"); rs=reviewer.get("status","skip")
    pc=primary.get("confidence",0); rc=reviewer.get("confidence",0)
    cv=cloud.get("verdict","skip") if cloud else "skip"
    pp=ps in ("pass","pass_with_manual"); rp=rs in ("pass","pass_with_manual")
    pf=ps=="fail"; rf=rs=="fail"
    conflicts=[]
    if pp and not rp: conflicts.append("主验收通过但复核不通过（可能mock数据骗人）")
    if rp and not pp: conflicts.append("复核通过但主验收不通过（spec有bug）")
    if pc>=90 and rc<60: conflicts.append("置信度差异大（主高复低）")
    if rc>=90 and pc<60: conflicts.append("置信度差异大（复高主低）")
    if cloud and cv=="fail": conflicts.append("云验收fail")
    if cloud and cv=="fail": d,v="block","🔴 云验收fail"
    elif not conflicts and pp and rp and pc>=90 and rc>=90: d,v="close","✅ 双一致+置信度达标"
    elif not conflicts and pf and rf: d,v="hold","❌ 双失败"
    elif "skip_deployment" in str(ps): d,v="hold","⏸️ 部署类"
    elif ps=="skip" and rs=="skip": d,v="hold","⏸️ 双方跳过"
    elif rs=="manual_review": d,v="hold","👀 需人工"
    elif conflicts: d,v="block",f"⚠️ 不一致：{'; '.join(conflicts)}"
    else: d,v="block",f"⚠️ 状态不一致：主={ps} 复={rs}"
    return {"decision":d,"verdict":v,"conflicts":conflicts}

def _verdict_json(iid,judgment,primary,reviewer):
    return {"issue_id":iid,"decision":judgment["decision"],"verdict":judgment["verdict"],
        "primary":{"status":primary.get("status"),"confidence":primary.get("confidence"),"specs_pass":primary.get("specs_pass",0),"specs_total":primary.get("specs_total",0)},
        "reviewer":{"status":reviewer.get("status"),"confidence":reviewer.get("confidence"),"asserts_pass":reviewer.get("asserts_pass",0),"asserts_fail":reviewer.get("asserts_fail",0)},
        "conflicts":judgment.get("conflicts",[])}

def post_comment(iid,judgment,primary,reviewer):
    d=judgment["decision"]; icon={"close":"✅","hold":"❌","block":"⚠️"}.get(d,"❓")
    vj=json.dumps(_verdict_json(iid,judgment,primary,reviewer),ensure_ascii=False,indent=2)
    body=f"""## 🤖 AI验收报告

{icon} **决定：{d.upper()}** — {judgment['verdict']}

### 主验收 | 状态:`{primary.get('status')}` 置信度:{primary.get('confidence')}%  spec:{primary.get('specs_pass',0)}/{primary.get('specs_total',0)}
### 复核验收 | 状态:`{reviewer.get('status')}` 置信度:{reviewer.get('confidence')}%  断言:{reviewer.get('asserts_pass',0)}p/{reviewer.get('asserts_fail',0)}f
### 一致性 | {chr(10).join('- '+c for c in judgment['conflicts']) if judgment['conflicts'] else '✅ 无冲突'}

---
双AI独立证据，5层兜底

<!-- VERDICT_JSON
{vj}
-->

> 🎯 军师确认后执行: `python3 scripts/dual_verify/merge.py {iid}`
"""
    p=subprocess.Popen(["gh","issue","comment",str(iid),"--body",body],stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(PROJECT_ROOT))
    out,err=p.communicate()
    return "✅ 评论已发" if p.returncode==0 else f"❌ {err.decode('utf-8','ignore')[:200]}"

def act(iid,decision,judgment=None,primary=None,reviewer=None,issue_body=""):
    if decision=="close":
        subprocess.Popen(["gh","issue","close",str(iid),"--reason","completed"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(PROJECT_ROOT))
        subprocess.Popen(["gh","issue","edit",str(iid),"--add-label","verified/auto","--remove-label","block/dual-mismatch"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(PROJECT_ROOT))
        return "✅ close+verified/auto"

    if decision=="hold":
        subprocess.Popen(["gh","issue","edit",str(iid),"--add-label","hold/auto-fail"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(PROJECT_ROOT))
        return "⚠️ hold"

    if decision=="block":
        depth=_get_block_depth(iid)
        _log_block(iid,depth)

        if depth>=MAX_BLOCK_DEPTH:
            subprocess.Popen(["gh","issue","edit",str(iid),"--add-label","block/need-human,block/dual-mismatch","--remove-label","needs-verification"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(PROJECT_ROOT))
            melt=f"## 🛑 熔断：已打回{depth}次\n\n本issue已打回{depth}次（≥{MAX_BLOCK_DEPTH}），自动修复循环已停止。请凯总/娜总人工介入。\n\n可能原因：业务真值歧义 / reviewer验证bug / 代码与真值根本不一致。\n\n<!-- COMMENT_JSON {{\"from\":\"junshi\",\"intent\":\"circuit_breaker\",\"block_depth\":{depth}}} -->"
            subprocess.Popen(["gh","issue","comment",str(iid),"--body",melt],stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(PROJECT_ROOT))
            alert=_block_alert()
            if alert: subprocess.Popen(["gh","issue","comment",str(iid),"--body",alert],stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(PROJECT_ROOT))
            return f"🛑 熔断: issue #{iid} 打回{depth}次"

        # 同issue打回：加 block 标签 + 保留 needs-verification（Agent重新抢）
        subprocess.Popen(["gh","issue","edit",str(iid),"--add-label","block/dual-mismatch,needs-verification"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(PROJECT_ROOT))
        failed=[r.get("spec",r.get("test","")) for r in (primary.get("results",[]) if primary else []) if r.get("status")=="fail"]
        block_comment=f"""## ⚠️ 验收 Blocked（第{depth}/{MAX_BLOCK_DEPTH}次）

### 冲突
{chr(10).join('- '+c for c in (judgment.get('conflicts',[]) if judgment else [])) if (judgment and judgment.get('conflicts')) else '见验收报告'}

### 失败 spec
{chr(10).join('- `'+s+'`' for s in failed) if failed else '见验收报告'}

Agent 将重新抢此 issue 修复。第{MAX_BLOCK_DEPTH}次打回后将熔断。

<!-- BLOCK_LOG
{{"block_depth":{depth},"failed_specs":{json.dumps(failed)},"conflicts":{json.dumps(judgment.get('conflicts',[]) if judgment else [])}}}
-->"""
        subprocess.Popen(["gh","issue","comment",str(iid),"--body",block_comment],stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(PROJECT_ROOT))
        return f"🔴 block(第{depth}次) → Agent将重新抢同issue修复"

    return "noop"

def merge(iid,dry_run=False):
    primary=load_result(iid,"primary"); reviewer=load_result(iid,"reviewer"); cloud=load_result(iid,"cloud")
    if not primary or not reviewer: return {"issue_id":iid,"error":"缺少结果"}
    judgment=judge(primary,reviewer,cloud); body=_get_issue_body(iid)
    result={"issue_id":iid,**judgment}
    # --dry-run: 贴报告给军师看，但不执行 close/block/hold
    result["comment"]=post_comment(iid,judgment,primary,reviewer)
    if not dry_run:
        result["action"]=act(iid,judgment["decision"],judgment,primary,reviewer,body)
    else:
        result["action"]="dry-run: 报告已贴，军师确认后运行 merge.py 执行"
    return result

def main():
    p=argparse.ArgumentParser(); p.add_argument("issue_id",type=int); p.add_argument("--dry-run",action="store_true")
    args=p.parse_args(); print(json.dumps(merge(args.issue_id,args.dry_run),ensure_ascii=False,indent=2))

if __name__=="__main__": main()
