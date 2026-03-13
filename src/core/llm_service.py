"""
LLM service for generating responses using multiple models.
"""
import logging
from typing import Callable, Dict, List, Optional, Tuple

from google import genai
from google.genai import types

from src.config.settings import get_settings


logger = logging.getLogger(__name__)

# Error indicators in responses
ERROR_INDICATORS = frozenset([
    "[client missing]",
    "[empty response]",
    "[gemini api]",
    "quota",
    "permission",
    "model not found",
])


class LLMService:
    """Service for LLM response generation."""
    
    FALLBACK_MODELS = ("gemini-2.5-flash",)
    
    def __init__(self):
        self._client: Optional[genai.Client] = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize Gemini client."""
        settings = get_settings()
        if not settings.gemini.api_key:
            logger.warning("Gemini API key not configured")
            return
        
        try:
            self._client = genai.Client(api_key=settings.gemini.api_key)
        except Exception as e:
            logger.error("Failed to initialize LLM client: %s", e)
    
    @property
    def is_available(self) -> bool:
        """Check if the LLM service is available."""
        return self._client is not None
    
    def get_available_models(self) -> Dict[str, str]:
        """Get dictionary of available models."""
        settings = get_settings()
        return dict(settings.available_models)
    
    def generate_single_response(
        self,
        model_name: str,
        query: str,
        context: str = "",
        feedback_notes: str = "",
    ) -> str:
        """
        Generate response from a single model.
        
        Args:
            model_name: Model ID (e.g., 'gemini-2.5-pro')
            query: User query
            context: Context information
            feedback_notes: Additional notes from feedback
            
        Returns:
            Generated response text
        """
        prompt = self._build_prompt(query, context, feedback_notes)
        return self._call_gemini(model_name, prompt)
    
    def _build_prompt(self, query: str, context: str, feedback_notes: str) -> str:
        """Build the prompt from query and context."""
        if context and context.strip():
            return f"""You are a helpful QA Assistant with access to knowledge sources.

Context Information:
{context}

User Query: {query}

Please provide a comprehensive and accurate answer. Use the context if it's relevant to the query, otherwise answer based on your general knowledge. Always provide helpful information regardless of whether the context is directly relevant.

{feedback_notes}"""
        else:
            return f"""You are a helpful QA Assistant. 

User Query: {query}

Please provide a comprehensive and accurate answer based on your knowledge. Be helpful and informative.

{feedback_notes}"""
    
    def _call_gemini(
        self,
        model_name: str,
        prompt: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Call Gemini API with fallback handling.
        
        Args:
            model_name: Primary model to use
            prompt: The prompt text
            progress_callback: Optional callback for progress updates
            
        Returns:
            Response text
        """
        if not self._client:
            return "[Client Missing] Gemini client not initialized"
        
        def update_progress(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)
            logger.debug(msg)
        
        update_progress(f"Calling {model_name} API...")
        response = self._try_gemini_model(model_name, prompt)
        
        # Try fallbacks if response is unusable
        if self._is_unusable(response):
            for fallback in self.FALLBACK_MODELS:
                if fallback != model_name:
                    update_progress(f"Trying fallback: {fallback}...")
                    response = self._try_gemini_model(fallback, prompt)
                    if not self._is_unusable(response):
                        break
        
        return response
    
    def _try_gemini_model(self, model_name: str, prompt: str) -> str:
        """Try calling a specific Gemini model."""
        try:
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)]
                )
            ]
            
            config = types.GenerateContentConfig(
                temperature=0.1,
                top_p=0.8,
                top_k=40,
            )
            
            response = self._client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            
            # Extract text from response
            if hasattr(response, "text") and response.text:
                return response.text
            
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, "content") and hasattr(candidate.content, "parts"):
                    parts = candidate.content.parts
                    if parts and hasattr(parts[0], "text") and parts[0].text:
                        return parts[0].text
            
            return "[No Content] Model response was empty or invalid"
            
        except Exception as e:
            logger.error("Error calling %s: %s", model_name, e)
            return f"[Error] {model_name}: {str(e)}"
    
    def _is_unusable(self, text: str) -> bool:
        """Check if a response is unusable."""
        if not text:
            return True
        
        lowered = text.lower()
        if any(indicator in lowered for indicator in ERROR_INDICATORS):
            return True
        
        return len(text.strip()) < 10
    
    def generate_multiple_responses(
        self,
        selected_models: Dict[str, str],
        query: str,
        context: str = "",
        feedback_notes: str = "",
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, str]:
        """
        Generate responses from multiple models.
        
        Args:
            selected_models: Dict mapping display names to model IDs
            query: User query
            context: Context information
            feedback_notes: Additional feedback notes
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dict mapping display names to responses
        """
        responses = {}
        total = len(selected_models)
        
        for i, (display_name, model_id) in enumerate(selected_models.items(), 1):
            if progress_callback:
                progress_callback(f"Processing model {i}/{total}: {display_name}")
            
            response = self.generate_single_response(model_id, query, context, feedback_notes)
            responses[display_name] = response
        
        return responses
    
    def aggregate_responses(
        self,
        responses: Dict[str, str],
        query: str,
        use_fast_aggregation: bool = True,
    ) -> str:
        """
        Aggregate multiple model responses.
        
        For fast aggregation, returns the first valid response.
        
        Args:
            responses: Dict of model responses
            query: Original query
            use_fast_aggregation: If True, use quick selection instead of synthesis
            
        Returns:
            Aggregated/selected response
        """
        if not responses:
            return "No responses to aggregate."
        
        # Filter valid responses
        valid = {k: v for k, v in responses.items() if not self._is_unusable(v)}
        
        if not valid:
            return "All models failed to generate valid responses."
        
        if len(valid) == 1:
            return list(valid.values())[0]
        
        # Fast aggregation: prefer Flash model or first valid
        if use_fast_aggregation:
            flash_responses = {k: v for k, v in valid.items() if "flash" in k.lower()}
            if flash_responses:
                return list(flash_responses.values())[0]
        
        return list(valid.values())[0]
