"""
Embedding service for text vectorization.
"""
import logging
from typing import List, Optional

from google import genai
from google.genai import types

from src.config.settings import get_settings
from src.core.base import EmbeddingVector, ServiceError


logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating text embeddings using Gemini API."""
    
    def __init__(self):
        self._client: Optional[genai.Client] = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize the Gemini client."""
        settings = get_settings()
        if not settings.gemini.api_key:
            logger.warning("Gemini API key not configured - embedding service unavailable")
            return
        
        try:
            self._client = genai.Client(api_key=settings.gemini.api_key)
        except Exception as e:
            logger.error("Failed to initialize embedding client: %s", e)
            self._client = None
    
    @property
    def is_available(self) -> bool:
        """Check if the embedding service is available."""
        return self._client is not None
    
    def embed_text(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding for a text string.
        
        Args:
            text: The text to embed
            
        Returns:
            List of floats representing the embedding, or None if failed
        """
        if not self._client:
            logger.error("Embedding client not initialized")
            return None
        
        try:
            result = self._client.models.embed_content(
                model="text-embedding-004",
                contents=[
                    types.Content(
                        parts=[types.Part.from_text(text=text)]
                    )
                ]
            )
            return result.embeddings[0].values
        except Exception as e:
            logger.error("Error embedding text: %s", e)
            return None
    
    def embed_text_as_vector(self, text: str) -> Optional[EmbeddingVector]:
        """
        Generate embedding and wrap in EmbeddingVector.
        
        Args:
            text: The text to embed
            
        Returns:
            EmbeddingVector or None if failed
        """
        values = self.embed_text(text)
        return EmbeddingVector.from_list(values)
    
    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Embed multiple texts.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embeddings (None for failed items)
        """
        if not self._client:
            logger.error("Embedding client not initialized")
            return [None] * len(texts)
        
        results = []
        for text in texts:
            results.append(self.embed_text(text))
        return results
