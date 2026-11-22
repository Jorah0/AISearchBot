"""The CAPTCHA auto-solver integration (pass 57, policy 17.2): integrates the AI captcha bypass library
to solve CAPTCHAs using local Ollama models as the primary method of solving.

This module connects to the existing captcha.py functionality and adds support for:
- Local Ollama vision models as the primary solver
- Integration with the existing solver chain 
- Proper error handling and fallback mechanisms
"""
import os
import re
import base64
from typing import List, Optional, Dict, Any

from . import ai, db, settings
from .captcha import _prompt, _answer, _kind_action, _can_drive, _drives_by_click


def solve_captcha_local_ollama(image_data: bytes, captcha_type: str, hint: str = "") -> Optional[str]:
    """
    Solve a CAPTCHA using local Ollama models as primary method.
    
    Args:
        image_data: Raw image data (bytes)
        captcha_type: Type of CAPTCHA to solve
        hint: Hint text for the solver
        
    Returns:
        The solution answer or None if failed
    """
    # Get available vision models from local Ollama using the same approach as ai.py
    if "ollama" not in ai.available():
        return None
    
    try:
        # Use the same approach as ai.py for getting local vision models
        ids = [m for m in ai.list_models("ollama") if m and not re.search(r"embed|coder|codellama", m, re.I)]
    except (Exception, SystemExit):
        return None
    
    # Filter for vision-capable models using the same logic as the existing code
    _VISION_HINTS = re.compile(r"vision|vl|llava|gemma.*\d+.*b|moondream|llama.*\d+.*b.*vision|pixtral|granite3", re.I)
    vision = [m for m in ids if _VISION_HINTS.search(m)]
    if not vision:
        # If no vision models found, try all models
        vision = ids
    
    # Use the existing prompt logic from captcha.py
    prompt = _prompt(captcha_type, hint)
    
    # Try each vision model in order until one succeeds
    for model in vision:
        try:
            # Use the existing ask_image function but with local Ollama as provider
            answer = ai.ask_image(
                prompt=prompt,
                image=image_data,
                provider="ollama",
                model=model
            )
            
            # Normalize the answer using existing logic from captcha.py
            normalized = _answer(captcha_type, answer)
            if normalized is not None:
                return answer
                
        except Exception as e:
            # If this model fails, try the next one
            continue
    
    return None


def solve_captcha_fallback(image_data: bytes, captcha_type: str, hint: str = "") -> Optional[str]:
    """
    Fallback to primary AI provider if local Ollama models aren't available or failed.
    
    Args:
        image_data: Raw image data (bytes)
        captcha_type: Type of CAPTCHA to solve
        hint: Hint text for the solver
        
    Returns:
        The solution answer or None if failed
    """
    try:
        prompt = _prompt(captcha_type, hint)
        answer = ai.ask_image(
            prompt=prompt,
            image=image_data,
            provider=ai.vision_provider(),
            model=None  # Use default model for the provider
        )
        return answer
    except Exception:
        return None


def solve_captcha(page) -> Dict[str, Any]:
    """
    Solve CAPTCHA using local Ollama models as primary method.
    
    This integrates with the existing captcha.solve() function but prioritizes 
    local Ollama vision models over other providers.
    """
    try:
        info = page.captcha()
    except Exception:
        info = None
        
    if not info:
        return {"result": "unavailable", "type": "", "attempts": 0, "reason": "no visible challenge"}
    
    kind = str(info.get("type") or "unknown")
    
    # Check if we can drive this kind
    if not _can_drive(kind):
        return {"result": "unavailable", "type": kind, "attempts": 0,
                "reason": f"Lodestar does not drive {kind} checks: solve it in the agent window, then press Continue"}
    
    # Try to solve using local Ollama models first
    image_data = info.get("screenshot") or b""
    hint = info.get("hint") or ""
    
    try:
        # First try local Ollama models
        answer = solve_captcha_local_ollama(image_data, kind, hint)
        
        # If that failed, fallback to primary provider
        if answer is None:
            answer = solve_captcha_fallback(image_data, kind, hint)
        
        if answer is not None:
            # Perform the action on the page
            action = _kind_action(kind)
            if action == "click" and _drives_by_click(kind):
                # One-click widget: just click
                page.captcha_do(kind, "click")
            else:
                # Use the AI answer
                normalized_answer = _answer(kind, answer)
                if normalized_answer is not None:
                    page.captcha_do(kind, normalized_answer)
            
            # Check if it's solved
            try:
                if page.captcha_solved():
                    # Determine which model was used for reporting
                    model_used = "ollama" if solve_captcha_local_ollama(image_data, kind, hint) is not None else ai.vision_provider()
                    return {"result": "solved", "type": kind, "attempts": 1,
                            "reason": "solved by the AI", "model": model_used}
            except Exception:
                pass
            
        # If we get here, it means the answer was not processed or the check wasn't cleared
        return {"result": "failed", "type": kind, "attempts": 1,
                "reason": f"the local AI tried once and the check is still pending"}
                
    except Exception as e:
        return {"result": "failed", "type": kind, "attempts": 1,
                "reason": f"error solving CAPTCHA: {str(e)[:100]}"}