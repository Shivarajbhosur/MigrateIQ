"""
================================================================================
 Foundry IQ Service - Grounded Retrieval Integration
================================================================================
 Provides grounded knowledge retrieval using Azure AI Foundry IQ.
 Used across MigrateIQ reasoning steps to inject domain-specific context
 (COBOL patterns, validation rules, migration guidance) into LLM prompts.

 Track: Microsoft Agents League Hackathon 2026 - Reasoning Agents + Foundry IQ
================================================================================
"""

import os
import logging
import requests
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class FoundryIQService:
    """
    Azure AI Foundry IQ client for grounded retrieval.
    
    Used to inject grounded knowledge into reasoning steps:
      - COBOL pattern recognition
      - Validation rule lookup
      - Migration guidance generation
    """

    def __init__(self):
        self.endpoint = os.getenv("FOUNDRY_IQ_ENDPOINT", "").rstrip("/")
        self.api_key = os.getenv("FOUNDRY_IQ_API_KEY", "")
        self.timeout = int(os.getenv("FOUNDRY_IQ_TIMEOUT", "20"))
        self.enabled = bool(self.endpoint and self.api_key 
                            and "your-foundry" not in self.api_key.lower())

        if self.enabled:
            logger.info("✅ Foundry IQ service initialized: %s", self.endpoint)
        else:
            logger.warning("⚠️  Foundry IQ not configured - using fallback mode")

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def query(
        self,
        question: str,
        context: Optional[str] = None,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        Query Foundry IQ for grounded retrieval.

        Args:
            question: Natural language query.
            context: Optional context to refine retrieval.
            top_k: Number of top results to return.

        Returns:
            Dict with keys: 'answer', 'sources', 'grounded', 'success'.
        """
        if not self.enabled:
            return self._fallback_response(question)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": question,
            "context": context or "",
            "top_k": top_k,
        }

        try:
            response = requests.post(
                f"{self.endpoint}/query",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            if response.ok:
                data = response.json()
                logger.info("✅ Foundry IQ retrieved %d sources for: %s",
                            len(data.get("sources", [])), question[:60])
                return {
                    "answer": data.get("answer", ""),
                    "sources": data.get("sources", []),
                    "grounded": True,
                    "success": True,
                }
            logger.warning("Foundry IQ returned status %d", response.status_code)
        except requests.exceptions.RequestException as e:
            logger.warning("Foundry IQ request failed: %s", e)

        return self._fallback_response(question)

    def ground_reasoning_step(
        self,
        step_name: str,
        input_data: str,
    ) -> str:
        """
        Inject Foundry IQ grounded knowledge into a reasoning step.
        Returns a formatted string ready for LLM prompt injection.
        """
        result = self.query(
            question=f"Provide grounded knowledge for {step_name}",
            context=input_data[:2000],  # truncate to keep payload light
            top_k=3,
        )

        if not result["grounded"]:
            return ""

        sources_block = "\n".join(
            f"  - {s.get('title', 'Source')}: {s.get('snippet', '')[:200]}"
            for s in result.get("sources", [])
        )

        return (
            f"\n[Foundry IQ Grounded Knowledge - {step_name}]\n"
            f"{result['answer']}\n"
            f"Sources:\n{sources_block}\n"
        )

    def health_check(self) -> bool:
        """Quick check whether Foundry IQ is reachable."""
        if not self.enabled:
            return False
        try:
            r = requests.get(
                f"{self.endpoint}/health",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=5,
            )
            return r.ok
        except Exception:
            return False

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    @staticmethod
    def _fallback_response(question: str) -> Dict[str, Any]:
        """Graceful fallback when Foundry IQ is unavailable."""
        return {
            "answer": "",
            "sources": [],
            "grounded": False,
            "success": False,
            "fallback_reason": "Foundry IQ not configured or unreachable",
        }


# --------------------------------------------------------------------------- #
# Singleton accessor
# --------------------------------------------------------------------------- #
_foundry_iq_instance: Optional[FoundryIQService] = None


def get_foundry_iq() -> FoundryIQService:
    """Get singleton instance of FoundryIQService."""
    global _foundry_iq_instance
    if _foundry_iq_instance is None:
        _foundry_iq_instance = FoundryIQService()
    return _foundry_iq_instance
