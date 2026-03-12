import os
import json
import logging
import asyncio
import ollama
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LOCAL_WORKER_MODEL = os.getenv("LOCAL_WORKER_MODEL", "qwen3-coder:30b")

async def get_model_info(model: str = LOCAL_WORKER_MODEL) -> str:
    """
    Retrieves detailed metadata for a specific Ollama model, including its native context limit and tool support.
    """
    try:
        client = ollama.AsyncClient(host=OLLAMA_BASE_URL)
        info = await client.show(model)
        model_info = info.get('modelinfo', {})
        
        # Look for context length in common architecture-specific keys
        ctx_len = None
        for key in model_info:
            if 'context_length' in key:
                ctx_len = model_info[key]
                break
        
        details = {
            "model": model,
            "supports_tools": "tools" in info.get('capabilities', []),
            "context_length": ctx_len or "unknown (defaulting to 32k)",
            "parameter_size": info.get('details', {}).get('parameter_size', 'unknown'),
            "quantization": info.get('details', {}).get('quantization_level', 'unknown'),
            "architecture": model_info.get('general.architecture', 'unknown')
        }
        return json.dumps(details, indent=2)
    except Exception as e:
        logger.error(f"Error fetching model info for {model}: {e}")
        return f"Error: Could not retrieve info for model '{model}'."

async def list_local_models() -> str:
    """
    Lists the available local Ollama models and indicates which ones support tool calling.
    """
    try:
        client = ollama.AsyncClient(host=OLLAMA_BASE_URL)
        models_info = await client.list()
        model_names = []
        if hasattr(models_info, 'models'):
            model_names = [m.model for m in models_info.models]
        elif isinstance(models_info, dict) and 'models' in models_info:
            model_names = [m.get('name') or m.get('model') for m in models_info['models']]
            
        if not model_names:
            return "No local models found in Ollama."

        # Fetch detailed info for each model to check tool support
        tasks = [client.show(m) for m in model_names]
        infos = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = []
        for name, info in zip(model_names, infos):
            if isinstance(info, Exception):
                results.append(name)
                continue
            
            capabilities = info.get('capabilities', [])
            if 'tools' in capabilities:
                results.append(f"{name} (supports tools)")
            else:
                results.append(name)
                
        return "Available local models:\n- " + "\n- ".join(results)
    except Exception as e:
        logger.error(f"Error listing Ollama models: {e}")
        return f"Error listing models: {str(e)}"
