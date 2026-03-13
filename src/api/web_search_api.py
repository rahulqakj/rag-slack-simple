"""
Web search API using Gemini search tools.
"""
import logging
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

from src.config.settings import get_settings


logger = logging.getLogger(__name__)


class WebSearchAPI:
    """API client for web search using Gemini search tools."""
    
    SEARCH_MODEL = "gemini-2.0-flash-exp"
    DEFAULT_MAX_RESULTS = 3
    
    def __init__(self, max_results: int = DEFAULT_MAX_RESULTS):
        self.max_results = max_results
        self._client: Optional[genai.Client] = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize the Gemini client."""
        settings = get_settings()
        if not settings.gemini.api_key:
            logger.warning("Gemini API key not configured")
            return
        
        try:
            self._client = genai.Client(api_key=settings.gemini.api_key)
        except Exception as e:
            logger.error("Failed to initialize search client: %s", e)
    
    @property
    def is_available(self) -> bool:
        """Check if the search client is available."""
        return self._client is not None
    
    def _generate_search_content(self, prompt: str) -> Any:
        """Generate content with search tools."""
        return self._client.models.generate_content(
            model=self.SEARCH_MODEL,
            contents=[
                types.Content(parts=[types.Part.from_text(prompt)])
            ],
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
    
    def _parse_search_results(
        self,
        response_text: str,
        query: str,
        source_type: str = "Web",
    ) -> List[Dict[str, Any]]:
        """Parse search results from response text."""
        results = []
        lines = response_text.split("\n")
        current_result: Dict[str, Any] = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith("Title:") or (line.startswith("**") and line.endswith("**")):
                if current_result:
                    results.append(current_result)
                    current_result = {}
                current_result["title"] = line.replace("Title:", "").replace("**", "").strip()
                current_result["source"] = f"{source_type} (Gemini Search)"
            elif line.startswith("URL:") or line.startswith("Source:"):
                current_result["url"] = line.replace("URL:", "").replace("Source:", "").strip()
            elif line and not line.startswith("Search") and len(line) > 10:
                content = current_result.get("content", "")
                current_result["content"] = (content + " " + line).strip()[:500]
        
        if current_result:
            results.append(current_result)
        
        # Fallback if no structured results
        if not results:
            base_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            if source_type == "News":
                base_url = f"https://news.google.com/search?q={query.replace(' ', '+')}"
            elif source_type == "Images":
                base_url = f"https://images.google.com/search?q={query.replace(' ', '+')}"
            
            results.append({
                "source": f"{source_type} (Gemini Search)",
                "title": f"{source_type} results for: {query}",
                "content": response_text[:500] + "..." if len(response_text) > 500 else response_text,
                "url": base_url,
            })
        
        return results[:self.max_results]
    
    def search_web(self, query: str) -> List[Dict[str, Any]]:
        """Search the web using Gemini's built-in search capability."""
        if not self._client:
            logger.error("Search client not initialized")
            return []
        
        try:
            prompt = (
                f"Search the web for information about: {query}. "
                f"Provide {self.max_results} relevant results with source URLs and detailed content."
            )
            
            response = self._generate_search_content(prompt)
            
            if response.candidates and response.candidates[0].content:
                content_text = response.candidates[0].content.parts[0].text
                return self._parse_search_results(content_text, query, "Web")
            
            return []
            
        except Exception as e:
            logger.error("Error searching web: %s", e)
            return [{
                "source": "Web (Fallback)",
                "title": f"Search: {query}",
                "content": f"Unable to perform web search at this time. Query was: {query}",
                "url": "",
            }]
    
    def search_news(self, query: str) -> List[Dict[str, Any]]:
        """Search for articles."""
        if not self._client:
            logger.error("Search client not initialized")
            return []
        
        try:
            prompt = (
                f"Search for recent article about: {query}. "
                f"Provide {self.max_results} recent articles with sources and dates."
            )
            
            response = self._generate_search_content(prompt)
            
            if response.candidates and response.candidates[0].content:
                content_text = response.candidates[0].content.parts[0].text
                return self._parse_search_results(content_text, query, "Article")
            
            return []
            
        except Exception as e:
            logger.error("Error searching news: %s", e)
            return []
    
    def search(self, query: str, max_results: int = 3) -> List[Dict[str, Any]]:
        """Alias for search_web with custom max_results."""
        original_max = self.max_results
        self.max_results = max_results
        results = self.search_web(query)
        self.max_results = original_max
        return results
