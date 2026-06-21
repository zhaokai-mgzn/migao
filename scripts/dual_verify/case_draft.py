#!/usr/bin/env python3
"""
Case 草稿反推 v4 — AI First。模板匹配 + draft 生成全部 LLM 化。
bash 仅做: gh issue view / claude --agent case-draft / gh issue comment
"""
import argparse, json, os, subprocess, sys

PROJECT_ROOT = os.getenv("PROJECT_ROOT", os.getcwd())


def generate(issue_number, feedback_comment_id=None):
    """调用 case-draft agent 生成草稿并贴到 issue。"""

    # 构造 prompt
    prompt = f"为 issue #{issue_number} 生成 case draft。读 issue 详情 → 理解业务 → 生成 DRAFT_JSON → 用 gh issue comment 贴结果。"
    if feedback_comment_id:
        prompt += f" 这是 REJECT 后重 draft。参考 REVIEW_JSON comment ID={feedback_comment_id} 的反馈修正。"

    # 调用 LLM agent
    p = subprocess.Popen(
        ["claude", "--print", "--agent", "case-draft", prompt],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT)
    )
    out, err = p.communicate(timeout=300)
    if p.returncode != 0:
        err_msg = err.decode('utf-8', 'ignore')[:500]
        print(f"❌ case-draft agent 失败: {err_msg}", file=sys.stderr)
        # fallback: 用简单模板
        fallback_draft(issue_number)
        return

    output = out.decode('utf-8', 'ignore')
    # agent 已经贴了 comment，不需要额外操作
    print(f"✅ issue #{issue_number}")
    if feedback_comment_id:
        print(f"   (REJECT redraft, 参考 feedback #{feedback_comment_id})")


def fallback_draft(issue_number):
    """极端情况：LLM 不可用时的最小兜底。"""
    body = (
        f"## 🤖 军师反推 — Case草稿 (issue #{issue_number})\n\n"
        f"⚠️ LLM 不可用，使用最小兜底模板。请人工补充 L2/L3/L4 case。\n\n"
        f"**模板**: `skip` | **真值**: 待提取\n\n"
        f"<!-- DRAFT_JSON {{\"issue_id\":{issue_number},\"template\":\"skip\","
        f"\"truths_count\":0,\"auto_asserts\":0,\"skip_template\":true}} -->\n"
    )
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--body", body],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=15
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("issue_number", type=int)
    p.add_argument("--feedback-comment", type=str, default=None,
                   help="REVIEW_JSON comment ID for re-draft")
    args = p.parse_args()
    generate(args.issue_number, args.feedback_comment)


if __name__ == "__main__":
    main()
