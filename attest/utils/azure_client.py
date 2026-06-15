"""Azure OpenAI client factory with enterprise auth support.

Creates an AzureOpenAI client using the best available credentials:
1. API key from environment (AZURE_API_KEY_OPENAI or AZURE_API_KEY)
2. Service Principal (client_id + client_secret + tenant_id)
3. Workload Identity Federation (AZURE_FEDERATED_TOKEN_FILE + AZURE_TENANT_ID + AZURE_CLIENT_ID)
4. Managed Identity (system or user-assigned)
5. Azure Entra ID / DefaultAzureCredential (CLI login, VS Code, etc.)

Usage:
    from attest.utils.azure_client import get_azure_openai_client

    client = get_azure_openai_client()
    response = client.chat.completions.create(model="gpt-4.1-mini", ...)
"""

from __future__ import annotations

import os
from typing import Optional


def _get_credential(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    tenant_id: Optional[str] = None,
):
    """Build the best available Azure credential.

    Priority:
    1. Service Principal (client_id + client_secret + tenant_id)
    2. Workload Identity Federation (federated token file in env)
    3. Managed Identity (system or user-assigned via AZURE_CLIENT_ID)
    4. DefaultAzureCredential (CLI, VS Code, env, managed identity chain)
    """
    from azure.identity import (
        ClientSecretCredential,
        DefaultAzureCredential,
        ManagedIdentityCredential,
        WorkloadIdentityCredential,
    )

    _client_id = client_id or os.environ.get("AZURE_CLIENT_ID")
    _client_secret = client_secret or os.environ.get("AZURE_CLIENT_SECRET")
    _tenant_id = tenant_id or os.environ.get("AZURE_TENANT_ID")

    # Service Principal — explicit client secret
    if _client_id and _client_secret and _tenant_id:
        return ClientSecretCredential(
            tenant_id=_tenant_id,
            client_id=_client_id,
            client_secret=_client_secret,
        )

    # Workload Identity Federation — CI/CD with federated tokens (GitHub Actions, AKS, etc.)
    federated_token_file = os.environ.get("AZURE_FEDERATED_TOKEN_FILE")
    if federated_token_file and _client_id and _tenant_id:
        return WorkloadIdentityCredential(
            tenant_id=_tenant_id,
            client_id=_client_id,
            token_file_path=federated_token_file,
        )

    # Managed Identity — Azure VMs, App Service, AKS pods
    if os.environ.get("IDENTITY_ENDPOINT") or os.environ.get("MSI_ENDPOINT"):
        if _client_id:
            return ManagedIdentityCredential(client_id=_client_id)
        return ManagedIdentityCredential()

    # DefaultAzureCredential — tries everything (CLI, VS Code, env, managed identity)
    return DefaultAzureCredential()


def get_azure_credential(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    tenant_id: Optional[str] = None,
):
    """Public accessor for the credential builder.

    Used by adapters and evaluators that need a raw credential
    (e.g., Foundry adapter, Azure AI Evaluation SDK).
    """
    from azure.identity import get_bearer_token_provider

    credential = _get_credential(client_id, client_secret, tenant_id)
    return credential


def get_azure_openai_client(
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    api_version: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    tenant_id: Optional[str] = None,
):
    """Create an AzureOpenAI client using the best available auth.

    Priority:
    1. Explicit api_key parameter
    2. AZURE_API_KEY_OPENAI env var
    3. AZURE_API_KEY env var
    4. Service Principal (client_id/secret/tenant from params or env)
    5. Workload Identity Federation (federated token file in env)
    6. Managed Identity
    7. DefaultAzureCredential (CLI login, VS Code, etc.)

    Args:
        endpoint: Azure OpenAI endpoint. Defaults to AZURE_API_BASE env var.
        api_key: Explicit API key. Defaults to env vars.
        api_version: API version. Defaults to AZURE_API_VERSION or "2025-04-01-preview".
        client_id: Service Principal client ID. Defaults to AZURE_CLIENT_ID env var.
        client_secret: Service Principal secret. Defaults to AZURE_CLIENT_SECRET env var.
        tenant_id: Tenant ID. Defaults to AZURE_TENANT_ID env var.

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

    # Fallback: Token-based auth (SP, WIF, Managed Identity, CLI, etc.)
    try:
        from azure.identity import get_bearer_token_provider

        credential = _get_credential(client_id, client_secret, tenant_id)
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
            f"No API key found and Azure identity auth failed: {e}. "
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
