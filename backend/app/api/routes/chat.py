"""
Chat route.
Exposes a text API for the unified chatbot brain,
proxying RAG search to the portfolio service on port 8000.
"""

from __future__ import annotations

import httpx
import time
import uuid
from typing import Optional, List
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from app.config.settings import get_settings
from app.observability.logging import get_logger
from app.providers.llm import get_llm_provider
from app.providers.llm.base import Message

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/voice", tags=["chat"])
settings = get_settings()


class ChatMessage(BaseModel):
    role: str  # 'user' or 'model' / 'assistant'
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    session_id: Optional[str] = None
    mode: str = "general"
    model_override: Optional[str] = None


async def _fetch_rag_context(query: str) -> str:
    """Fetch matching CV/profile context from the local portfolio backend on port 8000."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            url = f"http://127.0.0.1:8000/api/v1/portfolio/rag/playground"
            resp = await client.get(url, params={"query": query})
            if resp.status_code == 200:
                chunks = resp.json()
                if chunks:
                    return "\n\n".join([
                        f"Source: {c['chunk_title']} (Relevance Score: {c['similarity']:.2f})\n{c['content']}"
                        for c in chunks
                    ])
    except Exception as exc:
        log.warning("Failed to fetch RAG context from portfolio service", error=str(exc))
    return "No specific profile context retrieved."


@router.post("/chat")
async def chat(request: ChatRequest, client_request: Request):
    """
    Unified text chatbot endpoint.
    Retrieves RAG knowledge from the portfolio service, grounds the Gemini prompt,
    generates response, and matches the portfolio API schema.
    """
    start_time = time.time()
    session_id = request.session_id or str(uuid.uuid4())

    # 1. Fetch grounding context
    context_str = await _fetch_rag_context(request.message)

    # 2. Build system instruction prompt (matches voice twin prompt guidelines)
    system_instruction = f"""
You are Addy, the AI Twin of Adarsh Singh, representing him in a conversation with a visitor (like a recruiter, hiring manager, client, or project stakeholder) on his personal portfolio website.

Your Guidelines:
1. Introduce yourself as "Addy, Adarsh's AI Twin". Speak in the first person ("I", "my", "me") as Adarsh Singh's digital replica. Maintain a professional, positive, innovative, and highly persuasive tone that represents a top-tier engineer.
2. Answer questions accurately and truthfully based on the provided knowledge base:
   - Weaknesses: Answer in a persuasive, constructive engineering-focused style.
   - Freelancing / Services: Confirm that Adarsh is available for freelance projects and technical consulting! Adarsh provides full-stack web development with cloud deployment (Vercel, AWS, Oracle VPS, GCP, Cloudflare), Autonomous AI Agent systems, Custom Chatbot integrations with RAG, and Shopify custom development. Invite them to get in touch on the [Contact Page](/contact) or email hello@adarshsingh.in.
   - Projects & Demos: Provide exact links when asked for code/demos (e.g. EMIVO live demo at https://emivo.vercel.app/, GitHub repos at https://github.com/Adarsh-Singh07).
3. If a question is about me (my experience, projects, or background) and you cannot find the answer in the provided knowledge base, you MUST start your response with the tag `[UNANSWERED]` followed by a polite explanation that you don't have that detail in your current portfolio knowledge base, but share relevant adjacent info or invite them to drop a message on the [Contact Page](/contact).
4. If the visitor wants to contact me, collect their Name, Email Address, and Message. Once collected, append this tag to the end of the response: `[SAVE_LEAD: name=<Name>|email=<Email>|message=<Message>]`.
5. Keep your responses concise, readable, and structured. Use bullet points or short paragraphs. Avoid long blocks of text.

Here is my official CV & Portfolio Knowledge Base context:
{context_str}
"""

    # 3. Format message history for LLM provider
    messages = []
    for msg in request.history:
        role = "assistant" if msg.role in ["model", "assistant"] else "user"
        messages.append(Message(role=role, content=msg.content))

    # 4. Invoke LLM provider
    try:
        provider = get_llm_provider(settings, provider_name="gemini")
        # Run chat stream and gather response
        response_text = ""
        async for chunk in provider.stream_chat(
            messages=messages + [Message(role="user", content=request.message)],
            system_prompt=system_instruction,
            max_tokens=settings.gemini_max_tokens,
        ):
            response_text += chunk

        latency = int((time.time() - start_time) * 1000)

        # 5. Build trace dictionary matching portfolio requirements
        trace = {
            "model_used": settings.gemini_model,
            "latency_ms": latency,
            "tokens_input": len(system_instruction.split()) + len(request.message.split()),  # simple estimation
            "tokens_output": len(response_text.split()),
            "cost_est": 0.0,
        }

        # 6. Check if lead should be saved/emailed
        # (This parsing mirrors what portfolio does, returning the clean text to frontend)
        return {
            "response": response_text,
            "session_id": session_id,
            "message_id": f"msg_{uuid.uuid4().hex[:12]}",
            "trace": trace,
        }

    except Exception as exc:
        log.error("Failed unified chat execution", error=str(exc))
        raise HTTPException(status_code=500, detail=f"AI generation failed: {exc}")
