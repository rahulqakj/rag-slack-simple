"""
File processing utilities for document ingestion.
"""
import mimetypes
import os
import re
from io import BytesIO
from typing import Dict, List, Optional

import pandas as pd
from PyPDF2 import PdfReader
from docx import Document as DocxDocument


class LocalUploadedFile(BytesIO):
    """Wrapper to make local files behave like Streamlit UploadedFile."""
    
    def __init__(self, data: bytes, name: str, content_type: str):
        super().__init__(data)
        self.name = name
        self.type = content_type
        self.size = len(data)


class FileProcessor:
    """Utility for processing uploaded files."""
    
    MIME_PDF = "application/pdf"
    MIME_TEXT = "text/plain"
    MIME_MARKDOWN = "text/markdown"
    MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    MIME_CSV = "text/csv"
    
    SUPPORTED_TYPES = frozenset([MIME_PDF, MIME_TEXT, MIME_MARKDOWN, MIME_DOCX, MIME_CSV])
    
    MAX_FILE_SIZE_MB = 50
    
    @staticmethod
    def process_uploaded_file(uploaded_file) -> Optional[str]:
        """Process uploaded file and return text content."""
        try:
            processors = {
                FileProcessor.MIME_PDF: FileProcessor._process_pdf,
                FileProcessor.MIME_TEXT: FileProcessor._process_txt,
                FileProcessor.MIME_MARKDOWN: FileProcessor._process_txt,
                FileProcessor.MIME_DOCX: FileProcessor._process_docx,
                FileProcessor.MIME_CSV: FileProcessor._process_csv,
            }
            processor = processors.get(uploaded_file.type)
            return processor(uploaded_file) if processor else None
        except Exception:
            return None
    
    @staticmethod
    def _process_pdf(uploaded_file) -> Optional[str]:
        """Extract text from PDF file."""
        try:
            reader = PdfReader(uploaded_file)
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            return "\n".join(text_parts)
        except Exception:
            return None
    
    @staticmethod
    def _process_txt(uploaded_file) -> str:
        """Extract text from plain text file."""
        return uploaded_file.getvalue().decode("utf-8")
    
    @staticmethod
    def _process_docx(uploaded_file) -> str:
        """Extract text from DOCX file."""
        doc = DocxDocument(uploaded_file)
        return "\n".join(para.text for para in doc.paragraphs)
    
    @staticmethod
    def _process_csv(uploaded_file) -> str:
        """Convert CSV to string representation."""
        df = pd.read_csv(uploaded_file)
        return df.to_string()
    
    @staticmethod
    def split_text(text: str, chunk_size: int = 800, chunk_overlap: int = 150) -> List[str]:
        """
        Split text into overlapping chunks using semantic-aware chunking.
        
        Uses the improved SemanticChunker that:
        - Respects document structure (paragraphs, headings)
        - Preserves semantic units
        - Creates proper overlap at sentence boundaries
        
        Args:
            text: Text to split
            chunk_size: Maximum chunk size in characters (default 800 for better precision)
            chunk_overlap: Characters to overlap between chunks
            
        Returns:
            List of text chunks
        """
        from src.utils.text_chunker import split_text as semantic_split
        return semantic_split(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    
    @staticmethod
    def get_file_info(uploaded_file) -> Dict:
        """Get information about an uploaded file."""
        return {
            "name": uploaded_file.name,
            "type": uploaded_file.type,
            "size": uploaded_file.size,
            "size_mb": round(uploaded_file.size / (1024 * 1024), 2),
        }
    
    @staticmethod
    def validate_file(uploaded_file, max_size_mb: int = MAX_FILE_SIZE_MB) -> List[str]:
        """
        Validate an uploaded file.
        
        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        
        if uploaded_file.size > max_size_mb * 1024 * 1024:
            errors.append(f"File size exceeds {max_size_mb}MB limit")
        
        if uploaded_file.type not in FileProcessor.SUPPORTED_TYPES:
            errors.append(f"File type {uploaded_file.type} is not supported")
        
        return errors
    
    @staticmethod
    def create_uploaded_from_path(file_path: str) -> LocalUploadedFile:
        """Create a file-like object from a local file path."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        mime_type, _ = mimetypes.guess_type(file_path)
        content_type = mime_type or FileProcessor.MIME_TEXT
        
        with open(file_path, "rb") as fh:
            data = fh.read()
        
        return LocalUploadedFile(
            data=data,
            name=os.path.basename(file_path),
            content_type=content_type,
        )
    
    @staticmethod
    def process_local_file(file_path: str) -> Optional[str]:
        """Process a local file and return extracted text."""
        local_file = FileProcessor.create_uploaded_from_path(file_path)
        result = FileProcessor.process_uploaded_file(local_file)
        local_file.close()
        return result
