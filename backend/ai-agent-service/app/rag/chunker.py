"""
AI 智能客服系统 - 布艺行业文档分块器

针对布艺/窗帘行业文档定制分块策略：
- FAQ 文档：按 Q&A 对分块
- 产品文档：按产品段落分块
- 尺寸指南：按表格/段落分块
- 通用文档：按段落 + 重叠窗口分块
"""

import re
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from loguru import logger


@dataclass
class Chunk:
    """文档分块数据类"""
    content: str                    # 分块文本内容
    metadata: Dict[str, Any]        # 元数据
    chunk_id: str = ""             # 分块唯一 ID
    embedding: Optional[List[float]] = field(default=None, repr=False)
    
    def __post_init__(self):
        if not self.chunk_id:
            self.chunk_id = str(uuid.uuid4())


class FabricChunker:
    """布艺行业文档分块器
    
    针对布艺行业文档的特殊结构进行优化：
    - 面料属性、加工工艺、安装方法、保养说明等语义边界
    - 支持 Markdown 和纯文本格式
    - 保留标题、章节、文档类型等元数据
    """
    
    # 文档结构标记模式（用于识别标题和章节）
    SECTION_PATTERNS = [
        r'^#{1,3}\s+(.+)$',           # Markdown 标题（# ## ###）
        r'^【(.+)】$',                # 中文方括号标题
        r'^第[一二三四五六七八九十]+[章节部分].+$',  # 章节标记（第一章、第二节等）
        r'^\d+\.\s+(.+)$',           # 数字编号标题（1. 标题）
        r'^[一二三四五六七八九十]+[、.](.+)$',  # 中文编号（一、标题）
    ]
    
    # 布艺行业语义边界关键词
    BOUNDARY_KEYWORDS = [
        # 面料属性
        '材质', '面料', '成分', '克重', '门幅', '缩水率', '遮光率', '透光率',
        # 规格尺寸
        '规格', '尺寸', '宽度', '高度', '长度', '米数',
        # 功能特点
        '功能', '特点', '特性', '优点', '适用场景', '适用范围',
        # 加工工艺
        '加工', '工艺', '打孔', '挂钩', '折边', '包边', '韩折', '罗马杆', '轨道',
        # 安装方法
        '安装', '步骤', '方法', '教程', '指南',
        # 保养说明
        '清洗', '保养', '洗涤', '晾晒', '收纳', '维护', '注意事项',
        # 价格相关
        '价格', '单价', '加工费', '费用', '计价',
    ]
    
    # FAQ 问题模式
    FAQ_PATTERNS = [
        r'^Q[:：]\s*(.+)$',           # Q: 问题
        r'^问[:：]\s*(.+)$',          # 问: 问题
        r'^【问】\s*(.+)$',           # 【问】问题
        r'^(\d+)\.\s*(.+?)[?？]$',    # 1. 问题?
    ]
    
    # FAQ 答案模式
    ANSWER_PATTERNS = [
        r'^A[:：]\s*(.+)$',           # A: 答案
        r'^答[:：]\s*(.+)$',          # 答: 答案
        r'^【答】\s*(.+)$',           # 【答】答案
    ]
    
    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        min_chunk_size: int = 100,
        max_chunk_size: int = 800,
    ):
        """
        初始化分块器
        
        Args:
            chunk_size: 目标分块大小（字符数）
            chunk_overlap: 相邻分块重叠大小
            min_chunk_size: 最小分块大小
            max_chunk_size: 最大分块大小
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        
        # 编译正则表达式
        self._section_regex = [re.compile(pattern, re.MULTILINE) for pattern in self.SECTION_PATTERNS]
        self._faq_question_regex = [re.compile(pattern, re.MULTILINE) for pattern in self.FAQ_PATTERNS]
        self._faq_answer_regex = [re.compile(pattern, re.MULTILINE) for pattern in self.ANSWER_PATTERNS]
    
    def chunk_document(
        self,
        content: str,
        doc_type: str = "general",
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        将文档内容分块
        
        Args:
            content: 文档文本内容
            doc_type: 文档类型（faq / product / guide / general）
            metadata: 文档元数据（title, category, product_id 等）
            
        Returns:
            list of {"content": str, "metadata": dict, "chunk_id": str}
        """
        if not content or not content.strip():
            logger.warning("Empty content provided to chunk_document")
            return []
        
        metadata = metadata or {}
        
        # 根据文档类型选择分块策略
        if doc_type == "faq":
            chunks = self._chunk_faq(content, metadata)
        elif doc_type == "product":
            chunks = self._chunk_product(content, metadata)
        elif doc_type == "guide":
            chunks = self._chunk_guide(content, metadata)
        else:
            chunks = self._chunk_general(content, metadata)
        
        logger.info(f"Document chunked into {len(chunks)} chunks (type: {doc_type})")
        return chunks
    
    def _chunk_faq(self, content: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """FAQ 文档分块：按 Q&A 对分块"""
        chunks = []
        lines = content.split('\n')
        
        current_question = None
        current_answer_lines = []
        current_section = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 检查是否是问题
            is_question = False
            for pattern in self._faq_question_regex:
                match = pattern.match(line)
                if match:
                    # 保存之前的 Q&A 对
                    if current_question and current_answer_lines:
                        answer = '\n'.join(current_answer_lines).strip()
                        chunk_content = f"Q: {current_question}\nA: {answer}"
                        chunk_metadata = {
                            **metadata,
                            "chunk_type": "faq_pair",
                            "question": current_question,
                            "section": current_section,
                        }
                        chunks.append(self._create_chunk(chunk_content, chunk_metadata))
                    
                    current_question = match.group(1) if match.groups() else line
                    current_answer_lines = []
                    is_question = True
                    break
            
            if not is_question:
                # 检查是否是章节标题
                is_section = False
                for pattern in self._section_regex:
                    if pattern.match(line):
                        current_section = line
                        is_section = True
                        break
                
                if not is_section and current_question:
                    # 这是答案的一部分
                    current_answer_lines.append(line)
        
        # 处理最后一对 Q&A
        if current_question and current_answer_lines:
            answer = '\n'.join(current_answer_lines).strip()
            chunk_content = f"Q: {current_question}\nA: {answer}"
            chunk_metadata = {
                **metadata,
                "chunk_type": "faq_pair",
                "question": current_question,
                "section": current_section,
            }
            chunks.append(self._create_chunk(chunk_content, chunk_metadata))
        
        # 如果没有识别到 Q&A 格式，回退到通用分块
        if not chunks:
            return self._chunk_general(content, {**metadata, "doc_type": "faq"})
        
        return chunks
    
    def _chunk_product(self, content: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """产品文档分块：按产品属性段落分块"""
        # 首先按结构分割
        sections = self._split_by_structure(content)
        
        chunks = []
        for section in sections:
            # 提取章节标题
            section_title = self._extract_section_title(section)
            
            # 按语义边界进一步分割
            blocks = self._split_by_semantic_boundary(section)
            
            for block in blocks:
                # 控制块大小
                sub_chunks = self._split_by_size(block)
                
                for sub_chunk in sub_chunks:
                    if len(sub_chunk) >= self.min_chunk_size:
                        chunk_metadata = {
                            **metadata,
                            "chunk_type": "product_info",
                            "section_title": section_title,
                        }
                        chunks.append(self._create_chunk(sub_chunk, chunk_metadata))
        
        # 如果没有分块成功，回退到通用分块
        if not chunks:
            return self._chunk_general(content, {**metadata, "doc_type": "product"})
        
        return chunks
    
    def _chunk_guide(self, content: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """指南文档分块：按步骤/表格分块"""
        # 首先按结构分割
        sections = self._split_by_structure(content)
        
        chunks = []
        for section in sections:
            section_title = self._extract_section_title(section)
            
            # 尝试按步骤分割（步骤 1、步骤 2 或 1. 2. 等）
            step_pattern = re.compile(r'(?:步骤\s*|[（(]?\d+[)）]\.?\s*)([^\n]+)')
            steps = step_pattern.split(section)
            
            if len(steps) > 2:  # 有分割出步骤
                for i in range(1, len(steps), 2):
                    step_title = steps[i].strip() if i < len(steps) else ""
                    step_content = steps[i+1].strip() if i+1 < len(steps) else ""
                    
                    if step_content:
                        full_content = f"{step_title}\n{step_content}" if step_title else step_content
                        
                        # 控制大小
                        sub_chunks = self._split_by_size(full_content)
                        for sub_chunk in sub_chunks:
                            if len(sub_chunk) >= self.min_chunk_size:
                                chunk_metadata = {
                                    **metadata,
                                    "chunk_type": "guide_step",
                                    "section_title": section_title,
                                    "step_title": step_title,
                                }
                                chunks.append(self._create_chunk(sub_chunk, chunk_metadata))
            else:
                # 没有明显步骤，按语义边界分割
                blocks = self._split_by_semantic_boundary(section)
                for block in blocks:
                    sub_chunks = self._split_by_size(block)
                    for sub_chunk in sub_chunks:
                        if len(sub_chunk) >= self.min_chunk_size:
                            chunk_metadata = {
                                **metadata,
                                "chunk_type": "guide_section",
                                "section_title": section_title,
                            }
                            chunks.append(self._create_chunk(sub_chunk, chunk_metadata))
        
        if not chunks:
            return self._chunk_general(content, {**metadata, "doc_type": "guide"})
        
        return chunks
    
    def _chunk_general(self, content: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """通用文档分块：按段落 + 重叠窗口分块"""
        # 首先按结构分割
        sections = self._split_by_structure(content)
        
        chunks = []
        for section in sections:
            section_title = self._extract_section_title(section)
            
            # 按句子分割并组合
            sub_chunks = self._split_by_sentences_with_overlap(section)
            
            for i, sub_chunk in enumerate(sub_chunks):
                if len(sub_chunk) >= self.min_chunk_size:
                    chunk_metadata = {
                        **metadata,
                        "chunk_type": "general",
                        "section_title": section_title,
                        "chunk_index": i,
                    }
                    chunks.append(self._create_chunk(sub_chunk, chunk_metadata))
        
        # 如果分块太少，尝试更细粒度的分割
        if len(chunks) < 2 and len(content) > self.max_chunk_size:
            # 强制按大小分割
            forced_chunks = self._split_by_size(content)
            chunks = []
            for i, chunk_text in enumerate(forced_chunks):
                chunk_metadata = {
                    **metadata,
                    "chunk_type": "general_forced",
                    "chunk_index": i,
                }
                chunks.append(self._create_chunk(chunk_text, chunk_metadata))
        
        return chunks
    
    def _split_by_structure(self, text: str) -> List[str]:
        """按文档结构标记分割"""
        lines = text.split('\n')
        sections = []
        current_section = []
        
        for line in lines:
            is_heading = any(
                pattern.match(line.strip())
                for pattern in self._section_regex
            )
            
            if is_heading and current_section:
                section_text = '\n'.join(current_section).strip()
                if section_text:
                    sections.append(section_text)
                current_section = [line]
            else:
                current_section.append(line)
        
        # 最后一个 section
        if current_section:
            section_text = '\n'.join(current_section).strip()
            if section_text:
                sections.append(section_text)
        
        return sections if sections else [text]
    
    def _split_by_semantic_boundary(self, text: str) -> List[str]:
        """按语义边界关键词细化分块"""
        # 查找语义边界关键词的位置
        boundaries = []
        for keyword in self.BOUNDARY_KEYWORDS:
            for match in re.finditer(keyword, text):
                # 确保关键词在段落开始位置
                pos = match.start()
                # 往前找最近的换行符或段落开始
                line_start = text.rfind('\n', 0, pos)
                if line_start == -1:
                    line_start = 0
                else:
                    line_start += 1
                
                # 检查关键词是否在行首附近
                prefix = text[line_start:pos].strip()
                if not prefix or prefix in ['-', '*', '•', '·']:
                    boundaries.append(line_start)
        
        if not boundaries:
            return [text]
        
        boundaries = sorted(set(boundaries))
        
        # 按边界分割
        blocks = []
        prev_pos = 0
        for pos in boundaries:
            if pos > prev_pos:
                block = text[prev_pos:pos].strip()
                if block:
                    blocks.append(block)
                prev_pos = pos
        
        # 最后一块
        last_block = text[prev_pos:].strip()
        if last_block:
            blocks.append(last_block)
        
        return blocks if blocks else [text]
    
    def _split_by_size(self, text: str) -> List[str]:
        """按固定大小分割文本"""
        if len(text) <= self.max_chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + self.max_chunk_size
            
            if end >= len(text):
                chunks.append(text[start:].strip())
                break
            
            # 尝试在句子边界分割
            search_text = text[start:end]
            sentence_end = max(
                search_text.rfind('。'),
                search_text.rfind('！'),
                search_text.rfind('？'),
                search_text.rfind('\n')
            )
            
            if sentence_end > self.min_chunk_size:
                end = start + sentence_end + 1
            
            chunks.append(text[start:end].strip())
            start = end - self.chunk_overlap
        
        return chunks
    
    def _split_by_sentences_with_overlap(self, text: str) -> List[str]:
        """按句子分割并添加重叠"""
        # 按句子分割
        sentences = re.split(r'(?<=[。！？\n])', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if not sentences:
            return [text]
        
        chunks = []
        current_chunk = []
        current_size = 0
        
        for sentence in sentences:
            sentence_size = len(sentence)
            
            if current_size + sentence_size > self.max_chunk_size and current_chunk:
                # 保存当前块
                chunk_text = ''.join(current_chunk)
                chunks.append(chunk_text)
                
                # 计算重叠部分
                overlap_text = ''
                overlap_size = 0
                for s in reversed(current_chunk):
                    if overlap_size + len(s) <= self.chunk_overlap:
                        overlap_text = s + overlap_text
                        overlap_size += len(s)
                    else:
                        break
                
                # 开始新块，包含重叠部分
                current_chunk = [overlap_text, sentence]
                current_size = len(overlap_text) + sentence_size
            else:
                current_chunk.append(sentence)
                current_size += sentence_size
        
        # 最后一块
        if current_chunk:
            chunks.append(''.join(current_chunk))
        
        return chunks
    
    def _extract_section_title(self, text: str) -> Optional[str]:
        """提取章节标题"""
        lines = text.split('\n')
        for line in lines[:3]:  # 检查前3行
            line = line.strip()
            for pattern in self._section_regex:
                match = pattern.match(line)
                if match:
                    return match.group(1) if match.groups() else line
        return None
    
    def _create_chunk(self, content: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """创建分块字典"""
        chunk_id = f"chunk_{metadata.get('document_id', 'unknown')}_{str(uuid.uuid4())[:8]}"
        return {
            "chunk_id": chunk_id,
            "content": content.strip(),
            "metadata": metadata,
        }


# 便捷函数
def chunk_document(
    content: str,
    doc_type: str = "general",
    metadata: Optional[Dict[str, Any]] = None,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> List[Dict[str, Any]]:
    """
    便捷的文档分块函数
    
    Args:
        content: 文档文本内容
        doc_type: 文档类型（faq / product / guide / general）
        metadata: 文档元数据
        chunk_size: 分块大小
        chunk_overlap: 重叠大小
        
    Returns:
        分块列表
    """
    chunker = FabricChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return chunker.chunk_document(content, doc_type, metadata)
