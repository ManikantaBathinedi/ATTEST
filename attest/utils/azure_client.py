"""Azure OpenAI client factory with keyless auth support.

Creates an AzureOpenAI client using the best available credentials:
1. API key from environment (AZURE_API_KEY_OPENAI or AZURE_API_KEY)
2. Azure Entra ID / DefaultAzureCredential (no keys needed)

Usage:
    from attest.utils.azure_client import get_azure_openai_client

    client = get_azure_openai_client()
    response = client.chat.completions.create(model="gpt-4.1-mini", ...)
"""

from __future__ import annotations

import os
from typing import Optional


def get_azure_openai_client(
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    api_version: Optional[str] = None,
):
    """Create an AzureOpenAI client using the best available auth.

    Priority:
    1. Explicit api_key parameter
    2. AZURE_API_KEY_OPENAI env var
    3. AZURE_API_KEY env var
    4. Azure Entra ID (DefaultAzureCredential → token-based, no keys)

    Args:
        endpoint: Azure OpenAI endpoint. Defaults to AZURE_API_BASE env var.
        api_key: Explicit API key. Defaults to env vars.
        api_version: API version. Defaults to AZURE_API_VERSION or "2025-04-01-preview".

    Returns:
        An AzureOpenAI client ready to use.

    Raises:
        ValueError if no endpoint is available.
    """
    from openai import AzureOpenAI

    _endpoint = endpoint or os.environ.get("AZURE_API_BASE", "")
    _version = api_version or os.environ.get("AZURE_API_VERSION", "2025-04-01-preview")

    if not _endpoint:
        raise ValueError(
            "Azure OpenAI endpoint not set. "
            "Set AZURE_API_BASE in .env or pass endpoint parameter."
        )

    # Try API key first (fastest, simplest)
    _key = api_key or os.environ.get("AZURE_API_KEY_OPENAI") or os.environ.get("AZURE_API_KEY")

    if _key:
        return AzureOpenAI(
            azure_endpoint=_endpoint,
            api_key=_key,
            api_version=_version,
        )

    # Fallback: Azure Entra ID (keyless auth)
    try:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )

        return AzureOpenAI(
            azure_endpoint=_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=_version,
        )
    except ImportError:
        raise ValueError(
            "No API key found and azure-identity not installed. "
            "Either set AZURE_API_KEY_OPENAI in .env, or install azure-identity: "
            "pip install azure-identity"
        )
    except Exception as e:
        raise ValueError(
            f"No API key found and Azure Entra ID auth failed: {e}. "
            "Set AZURE_API_KEY_OPENAI in .env, or run 'az login' first."
        )


def get_deployment_name(model: str) -> str:
    """Extract deployment name from model string.

    "azure/gpt-4.1-mini" → "gpt-4.1-mini"
    "openai/gpt-4o" → "gpt-4o"
    "gpt-4o" → "gpt-4o"
    """
    if model.startswith("azure/"):
        return model[len("azure/"):]
    if model.startswith("openai/"):
        return model[len("openai/"):]
    return model
