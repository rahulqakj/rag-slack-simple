"""
Advanced text chunking strategies for RAG retrieval.
"""
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class TextChunk:
    """A chunk of text with metadata."""
    content: str
    index: int
    start_char: int
    end_char: int
    
    @property
    def length(self) -> int:
        return len(self.content)


class RecursiveChunker:
    """Recursive text chunker that respects document structure."""
    
    SEPARATORS = [
        "\n\n",
        "\n",
        ". ",
        "? ",
        "! ",
        "; ",
        ", ",
        " ",
    ]
    
    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        min_chunk_size: int = 100,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
    
    def split(self, text: str) -> List[TextChunk]:
        """Split text into chunks with overlap."""
        if not text or not text.strip():
            return []
        
        text = self._normalize_text(text)
        raw_chunks = self._split_recursive(text, self.SEPARATORS)
        chunks = self._merge_and_overlap(raw_chunks, text)
        
        return chunks
    
    def split_simple(self, text: str) -> List[str]:
        """Split text and return just the content strings."""
        chunks = self.split(text)
        return [c.content for c in chunks]
    
    def _normalize_text(self, text: str) -> str:
        """Normalize whitespace while preserving structure."""
        text = re.sub(r" +", " ", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    
    def _split_recursive(
        self,
        text: str,
        separators: List[str],
    ) -> List[str]:
        """Recursively split text using progressively smaller separators."""
        if not text:
            return []
        
        if len(text) <= self.chunk_size:
            return [text]
        
        for sep in separators:
            if sep in text:
                splits = text.split(sep)
                splits = [s for s in splits if s.strip()]
                
                if len(splits) > 1:
                    return self._process_splits(splits, sep, separators)
        
        return self._force_split(text)
    
    def _process_splits(
        self,
        splits: List[str],
        separator: str,
        all_separators: List[str],
    ) -> List[str]:
        """Process splits, recursively splitting any that are too large."""
        result = []
        current_chunk = ""
        
        for split in splits:
            potential = current_chunk + separator + split if current_chunk else split
            
            if len(potential) <= self.chunk_size:
                current_chunk = potential
            else:
                if current_chunk:
                    result.append(current_chunk)
                
                if len(split) > self.chunk_size:
                    remaining_seps = all_separators[all_separators.index(separator) + 1:]
                    if remaining_seps:
                        sub_chunks = self._split_recursive(split, remaining_seps)
                        result.extend(sub_chunks)
                    else:
                        result.extend(self._force_split(split))
                    current_chunk = ""
                else:
                    current_chunk = split
        
        if current_chunk:
            result.append(current_chunk)
        
        return result
    
    def _force_split(self, text: str) -> List[str]:
        """Force split text by size when no separators work."""
        result = []
        for i in range(0, len(text), self.chunk_size):
            chunk = text[i:i + self.chunk_size]
            if chunk.strip():
                result.append(chunk)
        return result
    
    def _merge_and_overlap(
        self,
        raw_chunks: List[str],
        original_text: str,
    ) -> List[TextChunk]:
        """Merge small chunks and add overlap between chunks."""
        if not raw_chunks:
            return []
        
        merged = []
        current = ""
        
        for chunk in raw_chunks:
            if not chunk.strip():
                continue
            
            potential = current + " " + chunk if current else chunk
            
            if len(potential) <= self.chunk_size:
                current = potential
            else:
                if current:
                    merged.append(current.strip())
                current = chunk
        
        if current.strip():
            merged.append(current.strip())
        
        result = []
        text_position = 0
        
        for i, content in enumerate(merged):
            start = original_text.find(content[:50], text_position)
            if start == -1:
                start = text_position
            
            end = start + len(content)
            
            if i > 0 and self.chunk_overlap > 0:
                prev_content = merged[i - 1]
                overlap_text = prev_content[-self.chunk_overlap:]
                
                sentence_end = max(
                    overlap_text.rfind(". "),
                    overlap_text.rfind("? "),
                    overlap_text.rfind("! "),
                )
                
                if sentence_end > 0:
                    overlap_text = overlap_text[sentence_end + 2:]
                
                if overlap_text.strip():
                    content = overlap_text.strip() + " " + content
            
            chunk = TextChunk(
                content=content.strip(),
                index=i,
                start_char=start,
                end_char=end,
            )
            
            if chunk.length >= self.min_chunk_size or len(merged) == 1:
                result.append(chunk)
            
            text_position = end
        
        return result


class SemanticChunker(RecursiveChunker):
    """Enhanced chunker that keeps semantic units together."""
    
    HEADING_PATTERN = re.compile(r"^#{1,6}\s+.+$", re.MULTILINE)
    LIST_ITEM_PATTERN = re.compile(r"^[\s]*[-*•]\s+", re.MULTILINE)
    NUMBERED_LIST_PATTERN = re.compile(r"^[\s]*\d+[.)]\s+", re.MULTILINE)
    CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```", re.MULTILINE)
    
    def split(self, text: str) -> List[TextChunk]:
        """Split with semantic awareness."""
        if not text or not text.strip():
            return []
        
        text = self._normalize_text(text)
        text, code_blocks = self._extract_code_blocks(text)
        sections = self._split_by_headings(text)
        
        all_chunks = []
        for section in sections:
            section = self._restore_code_blocks(section, code_blocks)
            raw_chunks = self._split_recursive(section, self.SEPARATORS)
            chunks = self._merge_and_overlap(raw_chunks, section)
            
            offset = text.find(section[:50]) if section else 0
            for chunk in chunks:
                chunk.start_char += offset
                chunk.end_char += offset
                chunk.index = len(all_chunks)
                all_chunks.append(chunk)
        
        return all_chunks
    
    def _extract_code_blocks(self, text: str) -> Tuple[str, dict]:
        """Extract code blocks and replace with placeholders."""
        code_blocks = {}
        
        def replace_code(match):
            placeholder = f"__CODE_BLOCK_{len(code_blocks)}__"
            code_blocks[placeholder] = match.group(0)
            return placeholder
        
        text = self.CODE_BLOCK_PATTERN.sub(replace_code, text)
        return text, code_blocks
    
    def _restore_code_blocks(self, text: str, code_blocks: dict) -> str:
        """Restore code blocks from placeholders."""
        for placeholder, code in code_blocks.items():
            text = text.replace(placeholder, code)
        return text
    
    def _split_by_headings(self, text: str) -> List[str]:
        """Split text into sections by headings."""
        headings = list(self.HEADING_PATTERN.finditer(text))
        
        if not headings:
            return [text]
        
        sections = []
        last_end = 0
        
        for i, match in enumerate(headings):
            if match.start() > last_end:
                pre_content = text[last_end:match.start()].strip()
                if pre_content:
                    sections.append(pre_content)
            
            section_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            section = text[match.start():section_end].strip()
            
            if section:
                sections.append(section)
            
            last_end = section_end
        
        return sections if sections else [text]


default_chunker = SemanticChunker(
    chunk_size=800,
    chunk_overlap=150,
    min_chunk_size=100,
)


def split_text(
    text: str,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> List[str]:
    """Convenience function to split text into chunks."""
    chunker = SemanticChunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return chunker.split_simple(text)
