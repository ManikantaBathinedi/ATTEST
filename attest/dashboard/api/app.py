"""ATTEST Dashboard — FastAPI backend.

API endpoints for the web dashboard. The frontend calls these to:
- Configure agents (add/edit/test connection)
- Manage test cases (create/edit/upload)
- Run tests and view results
- Manage settings (API keys, evaluation)
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, BackgroundTasks, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from attest.core.config import load_config
from attest.core.config_models import AgentConfig, AttestConfig
from attest.core.models import RunSummary, TestCase
from attest.core.runner import TestRunner
from attest.core.scenario_loader import load_scenarios

app = FastAPI(title="ATTEST Dashboard", version="0.1.0")

# Load .env at startup so API keys are available
from dotenv import load_dotenv
load_dotenv(".env", override=True)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_latest_summary: Optional[RunSummary] = None
_is_running: bool = False
_cancel_requested: bool = False
_config_path: Optional[str] = None
_run_progress: Dict[str, Any] = {"total": 0, "completed": 0, "current": "", "results": []}
# Last baseline comparison (kept so the user can download a report after the run).
_last_baseline_diffs: Dict[str, Any] = {"diffs": [], "timestamp": ""}


def set_config_path(path: Optional[str]) -> None:
    global _config_path
    _config_path = path


def _get_config_path() -> Path:
    if _config_path:
        return Path(_config_path)
    return Path("attest.yaml")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class AgentSetupRequest(BaseModel):
    name: str
    type: str = "foundry_prompt"
    endpoint: str = ""
    agent_name: Optional[str] = None
    agent_version: Optional[str] = None
    api_key: Optional[str] = None
    # HTTP-specific
    request_path: str = "/chat"
    body_key: str = "message"
    response_path: str = "$.response"
    # Multi-agent orchestrator routing (optional)
    handled_by_path: Optional[str] = None
    routing_path_path: Optional[str] = None
    # MCP-specific
    transport: str = "stdio"
    command: Optional[str] = None
    args: List[str] = []
    default_tool: Optional[str] = None
    input_arg: str = "input"


class TestCaseRequest(BaseModel):
    name: str
    suite: str = "UI Tests"
    input: str = ""
    expected_output: Optional[str] = None
    context: Optional[str] = None
    assertions: List[Dict[str, Any]] = []
    evaluators: List[str] = []
    agent: str = "default"
    type: str = "single_turn"
    conversation_script: List[Dict[str, Any]] = []
    tags: List[str] = []
    persona: Optional[str] = None
    max_turns: Optional[int] = None


class BulkTestUpload(BaseModel):
    suite_name: str = "Uploaded Tests"
    agent: str = "default"
    assertions: List[Dict[str, Any]] = []
    evaluators: List[str] = []


# ---------------------------------------------------------------------------
# Agent setup endpoints
# ---------------------------------------------------------------------------


@app.post("/api/agents")
async def save_agent(req: AgentSetupRequest):
    """Save agent configuration to attest.yaml."""
    from ruamel.yaml import YAML

    config_path = _get_config_path()
    yaml = YAML()
    yaml.preserve_quotes = True

    # Load existing or create new
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.load(f) or {}
    else:
        data = {"project": {"name": "ATTEST Project"}}

    if "agents" not in data:
        data["agents"] = {}

    # Build agent config based on type
    if req.type == "foundry_prompt":
        data["agents"][req.name] = {
            "type": "foundry_prompt",
            "endpoint": req.endpoint,
            "agent_name": req.agent_name,
            "agent_version": req.agent_version or "latest",
        }
    elif req.type == "mcp":
        mcp_cfg = {
            "type": "mcp",
            "transport": req.transport,
            "default_tool": req.default_tool,
            "input_arg": req.input_arg or "input",
        }
        if req.transport == "stdio":
            mcp_cfg["command"] = req.command
            mcp_cfg["args"] = req.args or []
        else:
            mcp_cfg["endpoint"] = req.endpoint
        data["agents"][req.name] = mcp_cfg
    elif req.type == "a2a":
        # A2A (Agent2Agent) — JSON-RPC 2.0 over HTTP.
        a2a_cfg = {"type": "a2a", "endpoint": req.endpoint}
        if req.request_path and req.request_path not in ("/chat", "/"):
            a2a_cfg["request"] = {"path": req.request_path}
        data["agents"][req.name] = a2a_cfg
    else:
        response_cfg = {"content_path": req.response_path}
        # Multi-agent orchestrator routing fields (only written when provided).
        if req.handled_by_path:
            response_cfg["handled_by_path"] = req.handled_by_path
        if req.routing_path_path:
            response_cfg["routing_path_path"] = req.routing_path_path
        data["agents"][req.name] = {
            "type": "http",
            "endpoint": req.endpoint,
            "request": {
                "path": req.request_path,
                "body_template": {req.body_key: "{{input}}"},
            },
            "response": response_cfg,
        }

    # Ensure other sections exist
    if "evaluation" not in data:
        data["evaluation"] = {"backend": "builtin", "judge": {"model": "openai/gpt-4.1-mini"}}
    if "tests" not in data:
        data["tests"] = {"scenarios_dir": "tests/scenarios"}
    if "reporting" not in data:
        data["reporting"] = {"output_dir": "reports", "formats": ["json", "html"]}

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)

    # Save API key to .env if provided
    if req.api_key:
        _save_env_key("AZURE_API_KEY", req.api_key)

    return {"message": f"Agent '{req.name}' saved to {config_path}"}


@app.post("/api/agents/test")
async def test_agent_connection(req: AgentSetupRequest):
    """Test connection to an agent without saving."""
    try:
        # Set API key in environment temporarily
        if req.api_key:
            os.environ["AZURE_API_KEY"] = req.api_key

        config = AgentConfig(
            type=req.type,
            endpoint=req.endpoint,
            agent_name=req.agent_name,
            agent_version=req.agent_version or "latest",
        )

        from attest.adapters import create_adapter
        adapter = create_adapter(config)
        await adapter.setup()

        response = await adapter.send_message("Hello, what can you help with?")
        await adapter.teardown()

        return {
            "connected": True,
            "response_preview": response.content[:200],
            "latency_ms": round(response.latency_ms),
        }

    except Exception as e:
        return JSONResponse(
            {"connected": False, "error": str(e)[:300]},
            status_code=200,  # 200 so frontend can read the error
        )


@app.post("/api/settings/apikey")
async def save_api_key(data: dict):
    """Save API key to .env file."""
    key = data.get("key", "")
    key_name = data.get("name", "AZURE_API_KEY")
    if not key:
        return JSONResponse({"error": "No key provided"}, status_code=400)

    _save_env_key(key_name, key)
    os.environ[key_name] = key
    return {"message": f"{key_name} saved to .env"}


# ---------------------------------------------------------------------------
# Test case management endpoints
# ---------------------------------------------------------------------------


@app.post("/api/testcases")
async def create_test_case(req: TestCaseRequest):
    """Create a test case and save to a YAML scenario file."""
    from ruamel.yaml import YAML

    scenarios_dir = Path("tests/scenarios")
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    # Create or append to a file named by suite
    safe_suite = req.suite.lower().replace(" ", "_").replace("/", "_")
    file_path = scenarios_dir / f"{safe_suite}.yaml"

    yaml = YAML()
    yaml.preserve_quotes = True

    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.load(f) or {}
    else:
        data = {"name": req.suite, "agent": req.agent, "tests": []}

    if "tests" not in data:
        data["tests"] = []

    # Build test entry
    test_entry = {"name": req.name, "input": req.input}

    if req.type == "conversation" and req.conversation_script:
        test_entry["type"] = "conversation"
        test_entry["script"] = req.conversation_script
        del test_entry["input"]

    if req.type == "simulation":
        test_entry["type"] = "simulation"
        if req.persona:
            test_entry["persona"] = req.persona
        if req.max_turns:
            test_entry["max_turns"] = req.max_turns

    if req.expected_output:
        test_entry["expected_output"] = req.expected_output

    if req.context:
        test_entry["context"] = req.context

    if req.assertions:
        test_entry["assertions"] = req.assertions

    if req.evaluators:
        test_entry["evaluators"] = req.evaluators

    if req.tags:
        test_entry["tags"] = req.tags

    data["tests"].append(test_entry)

    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)

    return {"message": f"Test '{req.name}' added to {file_path}", "file": str(file_path)}


@app.post("/api/testcases/generate-security")
async def generate_security_tests(data: Optional[dict] = None):
    """Generate red team / security test cases."""
    from attest.security.red_team import RedTeamGenerator

    categories = None
    if data and data.get("categories"):
        categories = data["categories"]

    generator = RedTeamGenerator(categories=categories)
    path = generator.save_to_file()
    tests = generator.generate_all()

    return {
        "message": f"Generated {len(tests)} security test cases",
        "file": path,
        "categories": generator.available_categories,
        "total": len(tests),
    }


@app.get("/api/evaluators/status")
async def evaluator_availability():
    """Check which evaluator backends are installed and configured."""
    import os

    # Check DeepEval
    deepeval_installed = False
    try:
        import deepeval
        deepeval_installed = True
    except ImportError:
        pass

    # Check Azure AI Evaluation
    azure_eval_installed = False
    try:
        import azure.ai.evaluation
        azure_eval_installed = True
    except ImportError:
        pass

    # Check RAGAS
    ragas_installed = False
    try:
        import ragas
        ragas_installed = True
    except ImportError:
        pass

    # Check Azure credentials for DeepEval
    has_azure_keys = bool(
        os.environ.get("AZURE_API_BASE")
        and (os.environ.get("AZURE_API_KEY_OPENAI") or os.environ.get("AZURE_API_KEY"))
    )
    has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))

    return {
        "deepeval": {
            "installed": deepeval_installed,
            "configured": deepeval_installed and (has_azure_keys or has_openai_key),
            "message": "" if deepeval_installed else "pip install deepeval",
        },
        "azure_eval": {
            "installed": azure_eval_installed,
            "configured": azure_eval_installed,
            "message": "" if azure_eval_installed else "pip install azure-ai-evaluation",
        },
        "ragas": {
            "installed": ragas_installed,
            "configured": ragas_installed and (has_azure_keys or has_openai_key),
            "message": "" if ragas_installed else "pip install ragas langchain-openai",
        },
        "builtin": {
            "installed": True,
            "configured": has_azure_keys or has_openai_key,
            "message": "",
        },
    }


@app.get("/api/security/categories")
async def list_security_categories():
    """List available red team attack categories."""
    from attest.security.red_team import ATTACK_PATTERNS
    return {
        "categories": [
            {"name": k, "description": v["description"], "test_count": len(v["tests"])}
            for k, v in ATTACK_PATTERNS.items()
        ]
    }


@app.post("/api/testcases/generate")
async def generate_test_cases(data: dict):
    """Auto-generate test cases using LLM based on agent description.
    
    Body: {"description": "A travel booking agent that...", "count": 5, "suite": "Generated Tests"}
    """
    description = data.get("description", "").strip()
    count = min(data.get("count", 5), 20)  # Cap at 20
    suite_name = data.get("suite", "Generated Tests")

    if not description:
        return JSONResponse({"error": "Agent description is required"}, status_code=400)

    try:
        # Call LLM directly using OpenAI SDK (same as the Foundry adapter)
        import re
        from dotenv import load_dotenv
        load_dotenv(".env", override=True)

        config = load_config(_config_path)
        model = config.evaluation.judge.model

        prompt = f"""You are a QA engineer creating test cases for an AI agent. 

Agent description: {description}

Generate exactly {count} test cases as a JSON array. Each object must have:
- "name": short snake_case name  
- "input": the user message to send to the agent
- "expected_output": what a good response should contain (1 sentence)
- "tags": array of tags like ["smoke", "regression", "edge-case", "security"]

Include a mix of: happy path, edge cases, off-topic, and negative tests.

RESPOND WITH ONLY THE JSON ARRAY. No markdown, no explanation, no code fences."""

        # Use shared Azure client (supports key + Entra ID auth)
        from attest.utils.azure_client import get_azure_openai_client, get_deployment_name

        deploy_name = get_deployment_name(model)
        client = get_azure_openai_client()
        response = client.chat.completions.create(
            model=deploy_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=4096,
        )
        raw_text = response.choices[0].message.content.strip()

        # Extract JSON array from response (handle markdown fences)
        cleaned = raw_text
        if "```" in cleaned:
            # Remove markdown code fences
            cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
            cleaned = cleaned.strip()

        json_match = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if not json_match:
            return JSONResponse({"error": f"LLM did not return valid JSON array. Got: {raw_text[:300]}"}, status_code=500)

        tests_data = json.loads(json_match.group())

        # Save to YAML
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.default_flow_style = False

        scenarios_dir = Path("tests/scenarios")
        scenarios_dir.mkdir(parents=True, exist_ok=True)
        safe_name = suite_name.lower().replace(" ", "_")
        file_path = scenarios_dir / f"{safe_name}.yaml"

        yaml_data = {"name": suite_name, "agent": "default", "tests": []}
        for t in tests_data:
            entry = {
                "name": t.get("name", f"generated_{len(yaml_data['tests'])}"),
                "input": t.get("input", ""),
            }
            if t.get("expected_output"):
                entry["expected_output"] = t["expected_output"]
            if t.get("tags"):
                entry["tags"] = t["tags"]
            if t.get("assertions"):
                entry["assertions"] = t["assertions"]
            else:
                entry["assertions"] = [{"response_not_empty": True}]
            entry["evaluators"] = ["relevancy"]
            yaml_data["tests"].append(entry)

        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f)

        return {
            "message": f"Generated {len(yaml_data['tests'])} test cases",
            "file": str(file_path),
            "suite": suite_name,
            "total": len(yaml_data["tests"]),
        }
    except Exception as e:
        return JSONResponse({"error": f"Generation failed: {str(e)[:300]}"}, status_code=500)


@app.get("/api/templates/csv")
async def download_csv_template():
    """Download a CSV template for bulk test case upload."""
    from fastapi.responses import FileResponse

    template_path = Path("templates/test_cases_template.csv")
    if template_path.exists():
        return FileResponse(
            path=str(template_path),
            media_type="text/csv",
            filename="attest_test_template.csv",
        )
    # Fallback if file missing
    from fastapi.responses import Response
    return Response(
        content="name,suite,input,expected_output,context,tags,assertions,evaluators,type,persona,max_turns\n",
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=attest_test_template.csv"},
    )


@app.get("/api/templates/jsonl")
async def download_jsonl_template():
    """Download a JSONL template for bulk test case upload (supports all test types)."""
    from fastapi.responses import FileResponse

    template_path = Path("templates/test_cases_template.jsonl")
    if template_path.exists():
        return FileResponse(
            path=str(template_path),
            media_type="application/jsonl",
            filename="attest_test_template.jsonl",
        )
    # Fallback if file missing
    from fastapi.responses import Response
    return Response(
        content='{"name":"example","suite":"My Suite","input":"Hello","assertions":[{"response_not_empty":true}]}\n',
        media_type="application/jsonl",
        headers={"Content-Disposition": "attachment; filename=attest_test_template.jsonl"},
    )


@app.post("/api/testcases/upload")
async def upload_test_data(file: UploadFile = File(...)):
    """Upload CSV or JSONL to create proper YAML test scenario files.

    CSV columns: name, suite, input, expected_output, tags, assertions, evaluators, type
    JSONL: one JSON object per line with the same fields + optional 'script' for multi-turn
    
    Tests are grouped by suite → one YAML file per suite.
    """
    scenarios_dir = Path("tests/scenarios")
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    content = (await file.read()).decode("utf-8").strip()
    filename = file.filename or "uploaded.csv"
    ext = Path(filename).suffix.lower()

    # Parse rows into test entries
    test_entries = []

    if ext == ".csv":
        import csv
        import io
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            entry = {
                "name": row.get("name", "").strip(),
                "suite": row.get("suite", "Uploaded Tests").strip(),
                "input": row.get("input", "").strip(),
                "type": row.get("type", "single_turn").strip(),
            }
            if not entry["name"]:
                continue
            # Simulation tests can have goal instead of input
            if entry["type"] == "simulation" and not entry["input"]:
                entry["input"] = row.get("goal", "").strip()
            if not entry["input"] and entry["type"] != "simulation":
                continue

            if row.get("expected_output", "").strip():
                entry["expected_output"] = row["expected_output"].strip()

            if row.get("context", "").strip():
                entry["context"] = row["context"].strip()

            if row.get("persona", "").strip():
                entry["persona"] = row["persona"].strip()

            max_turns = row.get("max_turns", "").strip()
            if max_turns:
                try:
                    entry["max_turns"] = int(max_turns)
                except ValueError:
                    pass

            # Parse tags (comma-separated)
            tags_str = row.get("tags", "").strip()
            if tags_str:
                entry["tags"] = [t.strip() for t in tags_str.split(",") if t.strip()]

            # Parse assertions (semicolon-separated, key:value)
            asserts_str = row.get("assertions", "").strip()
            if asserts_str:
                entry["assertions"] = []
                for a in asserts_str.split(";"):
                    a = a.strip()
                    if not a:
                        continue
                    if ":" in a:
                        key, val = a.split(":", 1)
                        try:
                            val = int(val)
                        except ValueError:
                            pass
                        entry["assertions"].append({key.strip(): val})
                    else:
                        entry["assertions"].append({a: True})

            # Parse evaluators (comma-separated)
            evals_str = row.get("evaluators", "").strip()
            if evals_str:
                entry["evaluators"] = [e.strip() for e in evals_str.split(",") if e.strip()]

            test_entries.append(entry)

    elif ext in (".jsonl", ".json"):
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if not obj.get("name") or (not obj.get("input") and not obj.get("script")):
                    continue
                obj.setdefault("suite", "Uploaded Tests")
                if obj.get("script"):
                    obj.setdefault("type", "conversation")
                elif obj.get("persona"):
                    obj.setdefault("type", "simulation")
                else:
                    obj.setdefault("type", "single_turn")
                test_entries.append(obj)
            except json.JSONDecodeError:
                continue
    else:
        return JSONResponse({"error": f"Unsupported file type: {ext}. Use .csv or .jsonl"}, status_code=400)

    if not test_entries:
        return JSONResponse({"error": "No valid test cases found in file. Check format."}, status_code=400)

    # Group by suite and write YAML files
    from ruamel.yaml import YAML
    yaml = YAML()
    yaml.default_flow_style = False

    suites: Dict[str, list] = {}
    for entry in test_entries:
        suite = entry.pop("suite", "Uploaded Tests")
        suites.setdefault(suite, []).append(entry)

    files_created = []
    total_tests = 0
    for suite_name, tests in suites.items():
        safe_name = suite_name.lower().replace(" ", "_").replace("/", "_")
        file_path = scenarios_dir / f"{safe_name}.yaml"

        # Load existing or create new
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.load(f) or {}
        else:
            data = {"name": suite_name, "agent": "default"}

        if "tests" not in data:
            data["tests"] = []

        # Build test entries for YAML
        for t in tests:
            test_yaml = {"name": t["name"]}

            if t.get("type") == "conversation" and t.get("script"):
                test_yaml["type"] = "conversation"
                test_yaml["script"] = t["script"]
            else:
                test_yaml["input"] = t.get("input", "")
                if t.get("expected_output"):
                    test_yaml["expected_output"] = t["expected_output"]

            if t.get("tags"):
                test_yaml["tags"] = t["tags"]
            if t.get("assertions"):
                test_yaml["assertions"] = t["assertions"]
            if t.get("evaluators"):
                test_yaml["evaluators"] = t["evaluators"]

            data["tests"].append(test_yaml)
            total_tests += 1

        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
        files_created.append(str(file_path))

    return {
        "message": f"Created {total_tests} test case(s) across {len(files_created)} suite(s)",
        "files": files_created,
        "suites": list(suites.keys()),
        "total": total_tests,
    }


@app.get("/api/testcases")
async def list_test_cases():
    """List all test cases from all scenario files."""
    try:
        config = load_config(_config_path)
        test_cases = load_scenarios(directory=config.tests.scenarios_dir)
        return {
            "total": len(test_cases),
            "test_cases": [
                {
                    "name": tc.name,
                    "suite": tc.suite,
                    "input": tc.input[:100],
                    "full_input": tc.input,
                    "type": tc.type,
                    "agent": tc.agent,
                    "assertions": len(tc.assertions),
                    "evaluators": len(tc.evaluators),
                    "evaluator_list": tc.evaluators,
                    "expected_output": tc.expected_output,
                    "conversation_script": tc.conversation_script,
                    "tags": tc.tags,
                    "persona": tc.persona,
                    "max_turns": tc.max_turns,
                }
                for tc in test_cases
            ],
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/testcases/grouped")
async def list_test_cases_grouped():
    """List all test cases grouped by suite — for the Run Tests page."""
    try:
        config = load_config(_config_path)
        test_cases = load_scenarios(directory=config.tests.scenarios_dir)

        # Group by suite
        suites: Dict[str, list] = {}
        for tc in test_cases:
            if tc.suite not in suites:
                suites[tc.suite] = []
            suites[tc.suite].append({
                "name": tc.name,
                "input": tc.input[:80],
                "type": tc.type,
                "assertions": len(tc.assertions),
                "evaluators": len(tc.evaluators),
                "tags": tc.tags,
            })

        return {"suites": suites, "total": len(test_cases)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/testcases/{suite_name}")
async def delete_test_suite(suite_name: str):
    """Delete a test suite file."""
    scenarios_dir = Path("tests/scenarios")
    for f in scenarios_dir.glob("*.yaml"):
        if f.stem == suite_name or f.stem == suite_name.lower().replace(" ", "_"):
            f.unlink()
            return {"message": f"Deleted {f.name}"}
    return JSONResponse({"error": f"Suite '{suite_name}' not found"}, status_code=404)


# ---------------------------------------------------------------------------
# Suite management endpoints
# ---------------------------------------------------------------------------


@app.get("/api/suites")
async def list_suites():
    """List tag-based suites + file-based suites.
    
    File-based suites are read directly from YAML files on disk (so empty suites show).
    Tag-based suites are derived from test case tags.
    """
    try:
        config = load_config(_config_path)
        test_cases = load_scenarios(directory=config.tests.scenarios_dir)

        # Collect all tags (tag-based suites)
        tag_suites = {}
        for tc in test_cases:
            for tag in tc.tags:
                if tag not in tag_suites:
                    tag_suites[tag] = {"name": tag, "type": "tag", "test_count": 0, "tests": []}
                tag_suites[tag]["test_count"] += 1
                tag_suites[tag]["tests"].append(tc.name)

        # Scan YAML files directly for file-based suites (includes empty ones)
        scenarios_dir = Path(config.tests.scenarios_dir)
        file_suites = {}
        if scenarios_dir.exists():
            from ruamel.yaml import YAML
            yaml_reader = YAML()
            for f in sorted(scenarios_dir.glob("*.yaml")):
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        data = yaml_reader.load(fh) or {}
                    suite_name = data.get("name", f.stem)
                    tests_list = data.get("tests", [])
                    file_suites[suite_name] = {
                        "name": suite_name,
                        "type": "file",
                        "agent": data.get("agent", "default"),
                        "test_count": len(tests_list),
                        "tests": [t.get("name", "unnamed") for t in tests_list],
                        "file": str(f),
                    }
                except Exception:
                    pass

        agents = list(config.agents.keys())

        return {
            "tag_suites": list(tag_suites.values()),
            "file_suites": list(file_suites.values()),
            "all_tags": sorted(tag_suites.keys()),
            "agents": agents,
            "total_tests": len(test_cases),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/suites/tag")
async def add_tag_to_tests(data: dict):
    """Add a tag (suite) to one or more test cases."""
    tag = data.get("tag", "").strip()
    test_names = data.get("test_names", [])

    if not tag:
        return JSONResponse({"error": "Tag name is required"}, status_code=400)
    if not test_names:
        return JSONResponse({"error": "At least one test name is required"}, status_code=400)

    scenarios_dir = Path("tests/scenarios")
    from ruamel.yaml import YAML
    yaml = YAML()
    yaml.preserve_quotes = True

    updated = 0
    for f in scenarios_dir.glob("*.yaml"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                content = yaml.load(fh) or {}

            modified = False
            for test in content.get("tests", []):
                if test.get("name") in test_names:
                    if "tags" not in test:
                        test["tags"] = []
                    if tag not in test["tags"]:
                        test["tags"].append(tag)
                        modified = True
                        updated += 1

            if modified:
                with open(f, "w", encoding="utf-8") as fh:
                    yaml.dump(content, fh)
        except Exception:
            pass

    return {"message": f"Tag '{tag}' added to {updated} test(s)"}


@app.post("/api/suites/untag")
async def remove_tag_from_tests(data: dict):
    """Remove a tag (suite) from one or more test cases."""
    tag = data.get("tag", "").strip()
    test_names = data.get("test_names", [])

    if not tag or not test_names:
        return JSONResponse({"error": "tag and test_names required"}, status_code=400)

    scenarios_dir = Path("tests/scenarios")
    from ruamel.yaml import YAML
    yaml = YAML()
    yaml.preserve_quotes = True

    removed = 0
    for f in scenarios_dir.glob("*.yaml"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                content = yaml.load(fh) or {}

            modified = False
            for test in content.get("tests", []):
                if test.get("name") in test_names and "tags" in test:
                    if tag in test["tags"]:
                        test["tags"].remove(tag)
                        modified = True
                        removed += 1

            if modified:
                with open(f, "w", encoding="utf-8") as fh:
                    yaml.dump(content, fh)
        except Exception:
            pass

    return {"message": f"Tag '{tag}' removed from {removed} test(s)"}


@app.post("/api/run/tag/{tag_name}")
async def run_by_tag(tag_name: str, request: Request, background_tasks: BackgroundTasks):
    """Run all tests with a specific tag."""
    global _is_running
    if _is_running:
        return JSONResponse({"error": "Tests are already running."}, status_code=409)
    _is_running = True
    agent_override = None
    try:
        body = await request.json()
        agent_override = body.get("agent") if body else None
    except Exception:
        pass
    background_tasks.add_task(_execute_tests, tag_filter=tag_name, agent_override=agent_override)
    return {"message": f"Running tag: {tag_name}{' with ' + agent_override if agent_override else ''}"}


@app.post("/api/suites")
async def create_suite(data: dict):
    """Create a new empty test suite."""
    suite_name = data.get("name", "").strip()
    agent = data.get("agent", "default")

    if not suite_name:
        return JSONResponse({"error": "Suite name is required"}, status_code=400)

    scenarios_dir = Path("tests/scenarios")
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    safe_name = suite_name.lower().replace(" ", "_").replace("/", "_")
    file_path = scenarios_dir / f"{safe_name}.yaml"

    if file_path.exists():
        return JSONResponse({"error": f"Suite '{suite_name}' already exists"}, status_code=409)

    from ruamel.yaml import YAML
    yaml = YAML()
    content = {"name": suite_name, "agent": agent, "tests": []}
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(content, f)

    return {"message": f"Suite '{suite_name}' created", "file": str(file_path)}


@app.put("/api/suites/{suite_name}")
async def update_suite(suite_name: str, data: dict):
    """Update suite name or agent."""
    new_name = data.get("name", suite_name)
    new_agent = data.get("agent")

    scenarios_dir = Path("tests/scenarios")
    from ruamel.yaml import YAML
    yaml = YAML()
    yaml.preserve_quotes = True

    # Find the file
    target_file = None
    for f in scenarios_dir.glob("*.yaml"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = yaml.load(fh) or {}
            if d.get("name") == suite_name or f.stem == suite_name.lower().replace(" ", "_"):
                target_file = f
                break
        except Exception:
            pass

    if not target_file:
        return JSONResponse({"error": f"Suite '{suite_name}' not found"}, status_code=404)

    with open(target_file, "r", encoding="utf-8") as fh:
        content = yaml.load(fh) or {}

    if new_name:
        content["name"] = new_name
    if new_agent:
        content["agent"] = new_agent

    with open(target_file, "w", encoding="utf-8") as fh:
        yaml.dump(content, fh)

    return {"message": f"Suite updated"}


@app.post("/api/suites/move-test")
async def move_test_to_suite(data: dict):
    """Move a test case from one suite to another."""
    test_name = data.get("test_name", "")
    from_suite = data.get("from_suite", "")
    to_suite = data.get("to_suite", "")

    if not test_name or not from_suite or not to_suite:
        return JSONResponse({"error": "test_name, from_suite, to_suite required"}, status_code=400)

    scenarios_dir = Path("tests/scenarios")
    from ruamel.yaml import YAML
    yaml = YAML()
    yaml.preserve_quotes = True

    # Find source file and extract the test
    test_entry = None
    for f in scenarios_dir.glob("*.yaml"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = yaml.load(fh) or {}
            if d.get("name") == from_suite or f.stem == from_suite.lower().replace(" ", "_"):
                tests = d.get("tests", [])
                for i, t in enumerate(tests):
                    if t.get("name") == test_name:
                        test_entry = tests.pop(i)
                        with open(f, "w", encoding="utf-8") as fh:
                            yaml.dump(d, fh)
                        break
                break
        except Exception:
            pass

    if not test_entry:
        return JSONResponse({"error": f"Test '{test_name}' not found in '{from_suite}'"}, status_code=404)

    # Add to target suite
    for f in scenarios_dir.glob("*.yaml"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = yaml.load(fh) or {}
            if d.get("name") == to_suite or f.stem == to_suite.lower().replace(" ", "_"):
                if "tests" not in d:
                    d["tests"] = []
                d["tests"].append(test_entry)
                with open(f, "w", encoding="utf-8") as fh:
                    yaml.dump(d, fh)
                return {"message": f"Moved '{test_name}' from '{from_suite}' to '{to_suite}'"}
        except Exception:
            pass

    return JSONResponse({"error": f"Target suite '{to_suite}' not found"}, status_code=404)


# ---------------------------------------------------------------------------
# Execution endpoints
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def get_status():
    return {
        "is_running": _is_running,
        "cancel_requested": _cancel_requested,
        "has_results": _latest_summary is not None or Path("reports/results.json").exists(),
        "config_loaded": _get_config_path().exists(),
        "progress": _run_progress if _is_running else None,
        "baseline_diffs": _run_progress.get("baseline_diffs"),
        "baseline_saved": _run_progress.get("baseline_saved"),
    }


@app.get("/api/results")
async def get_results():
    """Get the latest results — always reads from file for freshness.

    When the user has no real results yet, fall back to the bundled example
    results (flagged ``is_demo``) so the Results page isn't empty on first
    launch. The user can hide them with the "Remove Demo Data" button.
    """
    results_path = Path("reports/results.json")
    if results_path.exists():
        try:
            data = json.loads(results_path.read_text(encoding="utf-8"))
            return data
        except Exception:
            pass

    # Fallback: bundled demo results (unless the user dismissed them).
    if not _demo_dismissed_flag().exists():
        demo = _demo_results_path()
        if demo.exists():
            try:
                data = json.loads(demo.read_text(encoding="utf-8"))
                data["is_demo"] = True
                return data
            except Exception:
                pass

    return JSONResponse({"error": "No results yet. Run tests first."}, status_code=404)


def _demo_results_path() -> Path:
    """Path to the bundled example results that ship with the package."""
    return Path(__file__).resolve().parent.parent / "demo_results.json"


def _demo_dismissed_flag() -> Path:
    """Marker file written when the user clicks 'Remove Demo Data'."""
    return Path("reports") / ".demo_dismissed"


@app.get("/api/demo/status")
async def demo_status():
    """Report whether demo data is available and currently showing."""
    has_real = Path("reports/results.json").exists()
    dismissed = _demo_dismissed_flag().exists()
    demo_available = _demo_results_path().exists()
    return {
        "demo_available": demo_available,
        "demo_showing": demo_available and not dismissed and not has_real,
        "dismissed": dismissed,
        "has_real_results": has_real,
    }


@app.post("/api/demo/remove")
async def demo_remove():
    """Hide the bundled demo data (one-click clean slate for new users).

    Writes a marker file so the example results/history stop showing. This is
    non-destructive — it never deletes the user's own data, and demo data can
    be restored with /api/demo/restore.
    """
    Path("reports").mkdir(parents=True, exist_ok=True)
    _demo_dismissed_flag().write_text("dismissed", encoding="utf-8")
    return {"message": "Demo data hidden. The Results page now starts clean."}


@app.post("/api/demo/restore")
async def demo_restore():
    """Re-show the bundled demo data (undo 'Remove Demo Data')."""
    flag = _demo_dismissed_flag()
    if flag.exists():
        flag.unlink()
    return {"message": "Demo data restored."}


@app.delete("/api/results")
async def clear_results():
    """Delete current results file to start fresh."""
    results_path = Path("reports/results.json")
    if results_path.exists():
        results_path.unlink()
    return {"message": "Results cleared."}


@app.post("/api/run/cancel")
async def cancel_run():
    """Cancel the currently running test execution."""
    global _cancel_requested, _is_running
    if not _is_running:
        return {"message": "No run in progress."}
    _cancel_requested = True
    return {"message": "Cancellation requested. Run will stop after the current test completes."}


@app.post("/api/run")
async def run_tests(request: Request, background_tasks: BackgroundTasks):
    global _is_running
    if _is_running:
        return JSONResponse({"error": "Tests are already running."}, status_code=409)
    _is_running = True
    agent_override = None
    try:
        body = await request.json()
        agent_override = body.get("agent") if body else None
    except Exception:
        pass
    background_tasks.add_task(_execute_tests, agent_override=agent_override)
    return {"message": f"Test run started.{' Agent: ' + agent_override if agent_override else ''}"}


@app.post("/api/run/suite/{suite_name}")
async def run_suite(suite_name: str, request: Request, background_tasks: BackgroundTasks):
    """Run a specific test suite."""
    global _is_running
    if _is_running:
        return JSONResponse({"error": "Tests are already running."}, status_code=409)
    _is_running = True
    agent_override = None
    try:
        body = await request.json()
        agent_override = body.get("agent") if body else None
    except Exception:
        pass
    background_tasks.add_task(_execute_tests, suite_filter=suite_name, agent_override=agent_override)
    return {"message": f"Running suite: {suite_name}{' with ' + agent_override if agent_override else ''}"}


@app.post("/api/run/test/{test_name}")
async def run_single_test(test_name: str, request: Request, background_tasks: BackgroundTasks):
    """Run a single test by name."""
    global _is_running
    if _is_running:
        return JSONResponse({"error": "Tests are already running."}, status_code=409)
    _is_running = True
    agent_override = None
    try:
        body = await request.json()
        agent_override = body.get("agent") if body else None
    except Exception:
        pass
    background_tasks.add_task(_execute_tests, test_name_filter=test_name, agent_override=agent_override)
    return {"message": f"Running test: {test_name}{' with ' + agent_override if agent_override else ''}"}


@app.post("/api/run/benchmark")
async def run_benchmark(request: Request, background_tasks: BackgroundTasks):
    """Run a latency benchmark — repeat a test (or all tests) N times.

    Body: {"test": "name" (optional), "tag": "name" (optional), "repeat": 10}
    Measures the agent's latency distribution (p50/p95/p99) — an agent-level
    consistency check, not infrastructure load testing.
    """
    global _is_running
    if _is_running:
        return JSONResponse({"error": "Tests are already running."}, status_code=409)
    test_name = tag = None
    repeat = 10
    try:
        body = await request.json()
        test_name = body.get("test")
        tag = body.get("tag")
        repeat = max(2, min(int(body.get("repeat", 10)), 50))
    except Exception:
        pass
    _is_running = True
    background_tasks.add_task(
        _execute_tests, test_name_filter=test_name, tag_filter=tag, benchmark_repeat=repeat
    )
    scope = test_name or (f"tag:{tag}" if tag else "all tests")
    return {"message": f"Benchmarking {scope} × {repeat} runs"}


async def _execute_tests(suite_filter: Optional[str] = None, test_name_filter: Optional[str] = None, tag_filter: Optional[str] = None, agent_override: Optional[str] = None, benchmark_repeat: int = 0):
    global _latest_summary, _is_running, _run_progress, _cancel_requested
    _cancel_requested = False
    try:
        from datetime import datetime
        # Always reload config fresh (user might have changed it via UI)
        from dotenv import load_dotenv
        load_dotenv(".env", override=True)

        config = load_config(_config_path)
        test_cases = load_scenarios(directory=config.tests.scenarios_dir)

        if suite_filter:
            # Match by suite name OR by file stem (user might pass either)
            suite_lower = suite_filter.lower().replace("_", " ")
            test_cases = [
                tc for tc in test_cases
                if tc.suite == suite_filter
                or tc.suite.lower() == suite_lower
                or tc.suite.lower().replace(" ", "_") == suite_filter.lower()
            ]

        if test_name_filter:
            test_cases = [tc for tc in test_cases if tc.name == test_name_filter]

        if tag_filter:
            test_cases = [tc for tc in test_cases if tag_filter in tc.tags]

        # Override agent on all test cases if specified
        if agent_override:
            for tc in test_cases:
                tc.agent = agent_override

        # Benchmark mode: repeat each test N times to measure latency distribution.
        if benchmark_repeat and benchmark_repeat > 1:
            for tc in test_cases:
                tc.repeat = int(benchmark_repeat)

        if not test_cases:
            _is_running = False
            return

        # Initialize progress tracking
        _run_progress["total"] = len(test_cases)
        _run_progress["completed"] = 0
        _run_progress["current"] = ""
        _run_progress["results"] = []

        runner = TestRunner(config)

        # Setup adapters first
        await runner._setup_adapters(test_cases)

        # Run tests one by one with progress updates
        all_results = []
        try:
            for i, tc in enumerate(test_cases):
                if _cancel_requested:
                    _run_progress["current"] = "Cancelled"
                    break
                _run_progress["current"] = tc.name
                _run_progress["completed"] = i

                result = await runner._run_single(tc)
                all_results.append(result)

                # Update progress with latest result
                status_icon = "✅" if result.status.value == "passed" else "❌" if result.status.value == "failed" else "⚠️"
                _run_progress["results"].append({
                    "name": tc.name,
                    "status": result.status.value,
                    "icon": status_icon,
                    "latency_ms": round(result.latency_ms),
                })
                _run_progress["completed"] = i + 1
        finally:
            await runner._teardown_adapters()

        # Build summary from collected results
        from attest.core.models import RunSummary
        import uuid
        new_summary = RunSummary(
            run_id=f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        )
        for r in all_results:
            new_summary.add_result(r)

        output_dir = Path(config.reporting.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # For partial runs (single test or suite), merge into existing results
        json_path = output_dir / "results.json"
        if (suite_filter or test_name_filter or tag_filter or agent_override) and json_path.exists():
            try:
                from attest.utils.results_merge import merge_results
                existing = json.loads(json_path.read_text(encoding="utf-8"))
                new_rows = json.loads(new_summary.model_dump_json()).get("results", [])
                existing = merge_results(existing, new_rows)
                existing["timestamp"] = new_summary.timestamp.isoformat()
                json_path.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
            except Exception:
                # Fallback: just overwrite
                json_path.write_text(new_summary.model_dump_json(indent=2), encoding="utf-8")
        else:
            # Full run — write fresh
            json_path.write_text(new_summary.model_dump_json(indent=2), encoding="utf-8")

        _latest_summary = new_summary

        # Save timestamped copy (run history)
        from datetime import datetime
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        history_dir = output_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        run_id = f"run_{timestamp}"
        history_path = history_dir / f"{run_id}.json"
        history_path.write_text(new_summary.model_dump_json(indent=2), encoding="utf-8")

        # Auto-name the run by what was executed, so it's identifiable in
        # History / Compare without the user having to rename it.
        if suite_filter:
            scope = f"Suite: {suite_filter}"
        elif tag_filter:
            scope = f"Tag: {tag_filter}"
        elif test_name_filter:
            scope = f"Test: {test_name_filter}"
        else:
            scope = "All tests"
        if agent_override:
            scope += f" · {agent_override}"
        scope += f" · {new_summary.passed}/{new_summary.total}"
        try:
            labels = _load_run_labels()
            labels[run_id] = scope
            _save_run_labels(labels)
        except Exception:
            pass

        from attest.reporting.html_report import generate_html_report
        generate_html_report(new_summary, output_path=str(output_dir / "report.html"))
        generate_html_report(new_summary, output_path=str(history_dir / f"report_{timestamp}.html"))

        from attest.reporting.junit_xml import generate_junit_xml
        generate_junit_xml(new_summary, output_path=str(output_dir / "junit.xml"))

    except Exception as e:
        print(f"Dashboard run error: {e}")
    finally:
        _is_running = False


@app.get("/api/runs")
async def list_runs():
    """List all past test runs (run history)."""
    history_dir = Path("reports/history")
    if not history_dir.exists():
        return {"runs": []}

    labels = _load_run_labels()
    runs = []
    for f in sorted(history_dir.glob("run_*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            runs.append({
                "id": f.stem,
                "name": labels.get(f.stem, ""),
                "file": str(f),
                "timestamp": data.get("timestamp", ""),
                "total": data.get("total", 0),
                "passed": data.get("passed", 0),
                "failed": data.get("failed", 0),
                "duration": data.get("duration_seconds", 0),
            })
        except Exception:
            pass

    return {"runs": runs}


def _labels_path() -> Path:
    return Path("reports/history") / "labels.json"


def _load_run_labels() -> Dict[str, str]:
    """Load the run_id -> friendly-name map (empty if none saved)."""
    path = _labels_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_run_labels(labels: Dict[str, str]) -> None:
    path = _labels_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(labels, indent=2), encoding="utf-8")


@app.put("/api/runs/{run_id}/name")
async def set_run_name(run_id: str, data: dict):
    """Set (or clear) a friendly name for a run, for easy comparison later."""
    history_dir = Path("reports/history")
    if not (history_dir / f"{run_id}.json").exists():
        return JSONResponse({"error": f"Run '{run_id}' not found"}, status_code=404)

    name = (data.get("name") or "").strip()
    labels = _load_run_labels()
    if name:
        labels[run_id] = name
    else:
        labels.pop(run_id, None)  # empty name clears the label
    _save_run_labels(labels)
    return {"message": "Run name updated", "id": run_id, "name": name}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    """Get results for a specific past run."""
    history_dir = Path("reports/history")
    path = history_dir / f"{run_id}.json"
    if not path.exists():
        return JSONResponse({"error": f"Run '{run_id}' not found"}, status_code=404)

    data = json.loads(path.read_text(encoding="utf-8"))
    return data


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    """Delete a specific run from history."""
    history_dir = Path("reports/history")
    json_path = history_dir / f"{run_id}.json"
    if not json_path.exists():
        return JSONResponse({"error": f"Run '{run_id}' not found"}, status_code=404)
    json_path.unlink()
    # Also delete associated HTML report if exists
    timestamp = run_id.replace("run_", "")
    html_path = history_dir / f"report_{timestamp}.html"
    if html_path.exists():
        html_path.unlink()
    # Drop any saved name for this run
    labels = _load_run_labels()
    if labels.pop(run_id, None) is not None:
        _save_run_labels(labels)
    return {"message": f"Run '{run_id}' deleted"}


@app.delete("/api/runs")
async def delete_all_runs():
    """Delete all run history."""
    history_dir = Path("reports/history")
    if history_dir.exists():
        import shutil
        shutil.rmtree(history_dir)
        history_dir.mkdir(parents=True, exist_ok=True)
    return {"message": "All run history deleted"}


@app.get("/api/compare")
async def compare_runs(run_a: str, run_b: str):
    """Compare two runs side-by-side. Returns per-test score diffs."""
    history_dir = Path("reports/history")

    def load_run(rid):
        path = history_dir / f"{rid}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    a = load_run(run_a)
    b = load_run(run_b)
    if not a or not b:
        return JSONResponse({"error": "One or both runs not found"}, status_code=404)

    # Build lookup: scenario|agent → result
    def build_map(run_data):
        m = {}
        for r in run_data.get("results", []):
            key = r["scenario"] + "|" + r.get("agent", "default")
            m[key] = r
        return m

    map_a = build_map(a)
    map_b = build_map(b)
    all_keys = sorted(set(list(map_a.keys()) + list(map_b.keys())))

    comparisons = []
    for key in all_keys:
        ra = map_a.get(key)
        rb = map_b.get(key)
        name = key.split("|")[0]
        agent = key.split("|")[1] if "|" in key else "default"

        comp = {"name": name, "agent": agent}

        if ra and rb:
            comp["status_a"] = ra.get("status", "")
            comp["status_b"] = rb.get("status", "")
            comp["latency_a"] = ra.get("latency_ms", 0)
            comp["latency_b"] = rb.get("latency_ms", 0)

            # Compare scores
            scores_a = ra.get("scores", {})
            scores_b = rb.get("scores", {})
            all_metrics = sorted(set(list(scores_a.keys()) + list(scores_b.keys())))
            score_diffs = []
            for metric in all_metrics:
                sa = scores_a.get(metric, {}).get("score", None)
                sb = scores_b.get(metric, {}).get("score", None)
                diff = None
                if sa is not None and sb is not None:
                    diff = round(sb - sa, 3)
                score_diffs.append({"metric": metric, "score_a": sa, "score_b": sb, "diff": diff})
            comp["scores"] = score_diffs
            comp["change"] = "improved" if (comp["status_b"] == "passed" and comp["status_a"] != "passed") else "regressed" if (comp["status_a"] == "passed" and comp["status_b"] != "passed") else "same"
        elif ra:
            comp["status_a"] = ra.get("status", "")
            comp["status_b"] = "missing"
            comp["change"] = "removed"
        else:
            comp["status_a"] = "missing"
            comp["status_b"] = rb.get("status", "")
            comp["change"] = "new"

        comparisons.append(comp)

    improved = sum(1 for c in comparisons if c["change"] == "improved")
    regressed = sum(1 for c in comparisons if c["change"] == "regressed")

    return {
        "run_a": run_a, "run_b": run_b,
        "total_tests": len(comparisons),
        "improved": improved, "regressed": regressed,
        "comparisons": comparisons,
    }


@app.get("/api/trends")
async def get_trends():
    """Get score trends across all runs for the trend chart."""
    history_dir = Path("reports/history")
    if not history_dir.exists():
        return {"runs": []}

    runs = []
    for f in sorted(history_dir.glob("run_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            total = data.get("total", 0)
            passed = data.get("passed", 0)
            pass_rate = round((passed / total) * 100, 1) if total > 0 else 0

            # Avg scores across all results
            all_scores = {}
            for r in data.get("results", []):
                for metric, score_data in r.get("scores", {}).items():
                    if metric not in all_scores:
                        all_scores[metric] = []
                    if isinstance(score_data, dict) and "score" in score_data:
                        all_scores[metric].append(score_data["score"])

            avg_scores = {m: round(sum(s)/len(s), 3) for m, s in all_scores.items() if s}

            runs.append({
                "id": f.stem,
                "timestamp": data.get("timestamp", ""),
                "total": total,
                "passed": passed,
                "failed": data.get("failed", 0),
                "pass_rate": pass_rate,
                "duration": data.get("duration_seconds", 0),
                "avg_scores": avg_scores,
            })
        except Exception:
            pass

    return {"runs": runs}


@app.get("/api/download/report")
async def download_report():
    """Download the latest HTML report."""
    from fastapi.responses import FileResponse

    report_path = Path("reports/report.html")
    if not report_path.exists():
        return JSONResponse({"error": "No report available. Run tests first."}, status_code=404)

    return FileResponse(
        path=str(report_path),
        media_type="text/html",
        filename="attest_report.html",
    )


@app.get("/api/download/csv")
async def download_results_csv():
    """Download results as CSV for Excel/Google Sheets import."""
    from fastapi.responses import Response

    results_path = Path("reports/results.json")
    if not results_path.exists():
        return JSONResponse({"error": "No results yet."}, status_code=404)

    data = json.loads(results_path.read_text(encoding="utf-8"))
    results = data.get("results", [])

    # Build CSV
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header
    writer.writerow([
        "Test Name", "Suite", "Agent", "Status", "Latency (ms)",
        "Assertions Passed", "Assertions Total",
        "Scores", "Error",
    ])

    for r in results:
        assertions = r.get("assertions", [])
        passed_a = sum(1 for a in assertions if a.get("passed"))
        total_a = len(assertions)

        scores_str = "; ".join(
            f"{name}={s.get('score', 0):.2f}"
            for name, s in r.get("scores", {}).items()
        )

        writer.writerow([
            r.get("scenario", ""),
            r.get("suite", ""),
            r.get("agent", "default"),
            r.get("status", ""),
            round(r.get("latency_ms", 0)),
            passed_a,
            total_a,
            scores_str,
            r.get("error", ""),
        ])

    content = buf.getvalue()
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=attest_results.csv"},
    )


@app.get("/api/download/report/{run_id}")
async def download_run_report(run_id: str):
    """Download HTML report for a specific run."""
    from fastapi.responses import FileResponse

    timestamp = run_id.replace("run_", "")
    report_path = Path(f"reports/history/report_{timestamp}.html")
    if not report_path.exists():
        return JSONResponse({"error": f"Report for '{run_id}' not found"}, status_code=404)

    return FileResponse(
        path=str(report_path),
        media_type="text/html",
        filename=f"attest_{run_id}.html",
    )


@app.get("/api/config")
async def get_config():
    try:
        config = load_config(_config_path)
        agents = {}
        for name, agent in config.agents.items():
            agents[name] = {
                "type": agent.type,
                "endpoint": agent.endpoint,
                "agent_name": agent.agent_name,
                "agent_version": agent.agent_version,
            }

        # Get masked API key (show that it's set, not the actual value)
        api_key = os.environ.get("AZURE_API_KEY", "")
        has_key = bool(api_key)
        masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else ""

        # Check for Entra ID auth
        has_entra = False
        if not has_key:
            try:
                from azure.identity import DefaultAzureCredential
                cred = DefaultAzureCredential()
                cred.get_token("https://cognitiveservices.azure.com/.default")
                has_entra = True
            except Exception:
                pass

        # Check eval auth
        eval_key = os.environ.get("AZURE_API_KEY_OPENAI") or os.environ.get("AZURE_API_KEY", "")
        eval_base = os.environ.get("AZURE_API_BASE", "")

        return {
            "project": config.project.name,
            "agents": agents,
            "evaluation_backend": config.evaluation.backend,
            "scenarios_dir": config.tests.scenarios_dir,
            "has_api_key": has_key,
            "masked_api_key": masked_key,
            "has_entra_id": has_entra,
            "auth_method": "api_key" if has_key else ("entra_id" if has_entra else "none"),
            "eval_endpoint": eval_base,
            "has_eval_key": bool(eval_key),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/agents/current")
async def get_current_agents():
    """Get current agent configs for pre-filling the setup form."""
    try:
        config = load_config(_config_path)
        agents = []
        for name, agent in config.agents.items():
            agents.append({
                "name": name,
                "type": agent.type,
                "endpoint": agent.endpoint or "",
                "agent_name": agent.agent_name or "",
                "agent_version": agent.agent_version or "",
                "request_path": agent.request.path if agent.request else "/chat",
                "response_path": agent.response.content_path if agent.response else "$.response",
                "handled_by_path": (agent.response.handled_by_path if agent.response else None) or "",
                "routing_path_path": (agent.response.routing_path_path if agent.response else None) or "",
            })

        api_key = os.environ.get("AZURE_API_KEY", "")
        masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else ""

        return {"agents": agents, "masked_api_key": masked_key}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/agents/{agent_name}")
async def delete_agent(agent_name: str):
    """Remove an agent from attest.yaml."""
    from ruamel.yaml import YAML
    config_path = _get_config_path()
    yaml = YAML()
    yaml.preserve_quotes = True

    if not config_path.exists():
        return JSONResponse({"error": "No config file found"}, status_code=404)

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.load(f) or {}

    agents = data.get("agents", {})
    if agent_name not in agents:
        return JSONResponse({"error": f"Agent '{agent_name}' not found"}, status_code=404)

    del agents[agent_name]

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)

    return {"message": f"Agent '{agent_name}' deleted"}


@app.get("/api/settings/keys")
async def get_api_keys():
    """Get API key status for the Settings form.

    Returns only a MASKED preview of each key (never the raw secret) so the
    actual credential is not exposed to the browser. The form leaves the
    input blank when a key exists; saving with a blank input keeps the
    existing key, and typing a new value overwrites it.
    """
    def mask(val: str) -> str:
        if not val:
            return ""
        if len(val) > 12:
            return val[:6] + "\u2022" * 6 + val[-4:]
        return "\u2022" * len(val)

    azure_key = os.environ.get("AZURE_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    azure_base = os.environ.get("AZURE_API_BASE", "")

    return {
        "azure_api_key_masked": mask(azure_key),
        "openai_api_key_masked": mask(openai_key),
        "azure_api_base": azure_base,
        "has_azure_key": bool(azure_key),
        "has_openai_key": bool(openai_key),
    }


@app.get("/api/scenarios")
async def get_scenarios():
    try:
        config = load_config(_config_path)
        scenarios_dir = Path(config.tests.scenarios_dir)
        files = []
        if scenarios_dir.exists():
            for f in sorted(scenarios_dir.glob("*.yaml")) + sorted(scenarios_dir.glob("*.yml")):
                files.append({"name": f.stem, "path": str(f), "size": f.stat().st_size})
        return {"scenarios": files, "directory": str(scenarios_dir)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_env_key(key_name: str, key_value: str) -> None:
    """Save a key to the .env file."""
    env_path = Path(".env")
    lines = []

    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    # Update existing or add new
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key_name}="):
            lines[i] = f"{key_name}={key_value}"
            found = True
            break

    if not found:
        lines.append(f"{key_name}={key_value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard UI."""
    frontend_path = Path(__file__).parent / "frontend.html"
    if frontend_path.exists():
        return frontend_path.read_text(encoding="utf-8")
    return "<h1>ATTEST Dashboard</h1><p>Frontend file not found.</p>"


# ---------------------------------------------------------------------------
# Baseline endpoints
# ---------------------------------------------------------------------------


@app.post("/api/baseline/save")
async def baseline_save(background_tasks: BackgroundTasks):
    """Run all tests and save responses as golden baselines."""
    global _is_running
    if _is_running:
        return JSONResponse({"error": "Tests are already running."}, status_code=409)
    _is_running = True
    background_tasks.add_task(_execute_baseline_save)
    return {"message": "Saving baselines..."}


async def _execute_baseline_save():
    global _is_running, _cancel_requested
    _cancel_requested = False
    try:
        from attest.utils.baseline import save_baseline

        config = load_config(_config_path)
        test_cases = load_scenarios(directory=config.tests.scenarios_dir)
        if not test_cases:
            return

        runner = TestRunner(config)
        summary = await runner.run(
            test_cases, verbose=False, parallel=1,
            should_cancel=lambda: _cancel_requested,
        )
        count = save_baseline(summary.results)
        # Store result for polling
        _run_progress["baseline_saved"] = count
    except Exception as e:
        print(f"Baseline save error: {e}")
    finally:
        _is_running = False


@app.get("/api/baseline/list")
async def baseline_list():
    """List all saved baselines."""
    baseline_dir = Path("baselines")
    if not baseline_dir.exists():
        return {"baselines": [], "total": 0}

    baselines = []
    for f in sorted(baseline_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            baselines.append({
                "file": f.name,
                "scenario": data.get("scenario", f.stem),
                "agent": data.get("agent", "default"),
                "has_tool_calls": len(data.get("tool_calls", [])) > 0,
                "content_preview": data.get("content", "")[:100],
            })
        except Exception:
            pass

    return {"baselines": baselines, "total": len(baselines)}


@app.post("/api/baseline/diff")
async def baseline_diff(background_tasks: BackgroundTasks):
    """Run tests and compare with saved baselines."""
    global _is_running
    if _is_running:
        return JSONResponse({"error": "Tests are already running."}, status_code=409)
    _is_running = True
    background_tasks.add_task(_execute_baseline_diff)
    return {"message": "Running baseline comparison..."}


async def _execute_baseline_diff():
    global _is_running, _run_progress, _cancel_requested, _last_baseline_diffs
    _cancel_requested = False
    try:
        from attest.utils.baseline import compare_with_baseline

        config = load_config(_config_path)
        test_cases = load_scenarios(directory=config.tests.scenarios_dir)
        if not test_cases:
            return

        runner = TestRunner(config)
        summary = await runner.run(
            test_cases, verbose=False, parallel=1,
            should_cancel=lambda: _cancel_requested,
        )

        diffs = []
        for result in summary.results:
            diff = compare_with_baseline(result)
            if diff is None:
                diffs.append({"scenario": result.scenario, "agent": result.agent, "status": "no_baseline"})
            else:
                entry = {
                    "scenario": result.scenario,
                    "agent": result.agent,
                    "status": "match" if diff["all_match"] else "changed",
                    "content_match": diff["content_match"],
                    "tool_calls_match": diff["tool_calls_match"],
                    "routing_match": diff["routing_match"],
                    "details": diff.get("details", ""),
                    # Full before/after for the expandable detail view + report.
                    "baseline_content": diff.get("baseline_content", ""),
                    "current_content": diff.get("current_content", ""),
                    "baseline_tools": diff.get("baseline_tools", []),
                    "current_tools": diff.get("current_tools", []),
                    "baseline_routing": diff.get("baseline_routing", []),
                    "current_routing": diff.get("current_routing", []),
                }
                diffs.append(entry)

        _run_progress["baseline_diffs"] = diffs
        _last_baseline_diffs["diffs"] = diffs
        from datetime import datetime as _dt
        _last_baseline_diffs["timestamp"] = _dt.utcnow().isoformat()
    except Exception as e:
        print(f"Baseline diff error: {e}")
    finally:
        _is_running = False


@app.delete("/api/baseline")
async def baseline_clear():
    """Delete all saved baselines."""
    import shutil
    baseline_dir = Path("baselines")
    if baseline_dir.exists():
        shutil.rmtree(baseline_dir)
    return {"message": "All baselines deleted"}


@app.get("/api/baseline/diff/latest")
async def baseline_diff_latest():
    """Return the most recent baseline comparison (for re-rendering / report)."""
    return {
        "diffs": _last_baseline_diffs.get("diffs", []),
        "timestamp": _last_baseline_diffs.get("timestamp", ""),
    }


@app.get("/api/baseline/report")
async def baseline_report():
    """Download an HTML report of the most recent baseline comparison."""
    diffs = _last_baseline_diffs.get("diffs", [])
    if not diffs:
        return JSONResponse(
            {"error": "No baseline comparison yet. Run 'Compare with Baselines' first."},
            status_code=404,
        )
    from attest.reporting.baseline_report import generate_baseline_report
    html = generate_baseline_report(diffs, timestamp=_last_baseline_diffs.get("timestamp", ""))
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": "attachment; filename=attest_baseline_comparison.html"},
    )


# ---------------------------------------------------------------------------
# Execution config endpoints (parallel, profile, rate limit)
# ---------------------------------------------------------------------------


@app.get("/api/execution-config")
async def get_execution_config():
    """Get current execution config (cost, cache, rate limit, profiles)."""
    try:
        config = load_config(_config_path)

        # Read profiles from raw YAML
        profiles = []
        config_path = _get_config_path()
        if config_path.exists():
            from ruamel.yaml import YAML
            yaml = YAML()
            with open(config_path, "r", encoding="utf-8") as f:
                raw = yaml.load(f) or {}
            profiles = list(raw.get("profiles", {}).keys())

        return {
            "cache_responses": config.evaluation.cost.cache_responses,
            "rate_limit": config.evaluation.cost.rate_limit,
            "max_eval_cost_per_run": config.evaluation.cost.max_eval_cost_per_run,
            "eval_samples": getattr(config.evaluation, "samples", 1),
            "foundry_upload": config.reporting.foundry_upload,
            "profiles": profiles,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/run/advanced")
async def run_tests_advanced(request: Request, background_tasks: BackgroundTasks):
    """Run tests with advanced options (parallel, profile)."""
    global _is_running
    if _is_running:
        return JSONResponse({"error": "Tests are already running."}, status_code=409)
    _is_running = True

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    agent_override = body.get("agent")
    suite_filter = body.get("suite")
    tag_filter = body.get("tag")
    parallel = min(max(int(body.get("parallel", 1)), 1), 20)
    profile = body.get("profile")

    background_tasks.add_task(
        _execute_tests_advanced,
        suite_filter=suite_filter,
        tag_filter=tag_filter,
        agent_override=agent_override,
        parallel=parallel,
        profile=profile,
    )
    msg_parts = ["Test run started"]
    if parallel > 1:
        msg_parts.append(f"parallel={parallel}")
    if profile:
        msg_parts.append(f"profile={profile}")
    if agent_override:
        msg_parts.append(f"agent={agent_override}")
    return {"message": ". ".join(msg_parts)}


async def _execute_tests_advanced(
    suite_filter=None, tag_filter=None, agent_override=None,
    parallel=1, profile=None,
):
    """Execute tests with parallel and profile support."""
    global _latest_summary, _is_running, _run_progress, _cancel_requested
    _cancel_requested = False
    try:
        from datetime import datetime
        from dotenv import load_dotenv
        load_dotenv(".env", override=True)

        config = load_config(_config_path, profile=profile)
        test_cases = load_scenarios(directory=config.tests.scenarios_dir)

        if suite_filter:
            suite_lower = suite_filter.lower().replace("_", " ")
            test_cases = [
                tc for tc in test_cases
                if tc.suite == suite_filter
                or tc.suite.lower() == suite_lower
                or tc.suite.lower().replace(" ", "_") == suite_filter.lower()
            ]

        if tag_filter:
            test_cases = [tc for tc in test_cases if tag_filter in tc.tags]

        if agent_override:
            for tc in test_cases:
                tc.agent = agent_override

        if not test_cases:
            _is_running = False
            return

        _run_progress["total"] = len(test_cases)
        _run_progress["completed"] = 0
        _run_progress["current"] = ""
        _run_progress["results"] = []

        runner = TestRunner(config)

        def _on_result(tc, r):
            status_icon = "✅" if r.status.value == "passed" else "❌" if r.status.value == "failed" else "⚠️"
            _run_progress["results"].append({
                "name": r.scenario,
                "status": r.status.value,
                "icon": status_icon,
                "latency_ms": round(r.latency_ms),
            })
            _run_progress["completed"] = len(_run_progress["results"])

        summary = await runner.run(
            test_cases,
            verbose=False,
            parallel=parallel,
            should_cancel=lambda: _cancel_requested,
            on_result=_on_result,
        )

        if _cancel_requested:
            _run_progress["current"] = "Cancelled"

        output_dir = Path(config.reporting.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / "results.json"

        # A cancelled run is partial — never let it clobber the accumulated
        # results.json. Merge the tests that did complete into the existing
        # file (keyed by scenario|agent), preserving everything else.
        if _cancel_requested and json_path.exists():
            try:
                from attest.utils.results_merge import merge_results
                existing = json.loads(json_path.read_text(encoding="utf-8"))
                new_rows = json.loads(summary.model_dump_json()).get("results", [])
                existing = merge_results(existing, new_rows)
                json_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
            except Exception:
                # If merge fails, fall back to leaving results.json untouched.
                pass
            # Don't write history/report snapshots for a partial cancelled run.
            return

        json_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
        _latest_summary = summary

        # Save timestamped copy
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        history_dir = output_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        run_id = f"run_{timestamp}"
        history_path = history_dir / f"{run_id}.json"
        history_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")

        # Auto-name the run by what was executed (identifiable in History / Compare).
        if suite_filter:
            scope = f"Suite: {suite_filter}"
        elif tag_filter:
            scope = f"Tag: {tag_filter}"
        else:
            scope = "All tests"
        if agent_override:
            scope += f" · {agent_override}"
        if profile:
            scope += f" · {profile}"
        scope += f" · {summary.passed}/{summary.total}"
        try:
            labels = _load_run_labels()
            labels[run_id] = scope
            _save_run_labels(labels)
        except Exception:
            pass

        from attest.reporting.html_report import generate_html_report
        generate_html_report(summary, output_path=str(output_dir / "report.html"))
        generate_html_report(summary, output_path=str(history_dir / f"report_{timestamp}.html"))

        from attest.reporting.junit_xml import generate_junit_xml
        generate_junit_xml(summary, output_path=str(output_dir / "junit.xml"))

    except Exception as e:
        print(f"Dashboard advanced run error: {e}")
    finally:
        _is_running = False


@app.post("/api/settings/execution")
async def save_execution_settings(data: dict):
    """Update execution settings (cache, rate limit, cost, foundry upload) in attest.yaml."""
    from ruamel.yaml import YAML

    config_path = _get_config_path()
    yaml = YAML()
    yaml.preserve_quotes = True

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.load(f) or {}
    else:
        raw = {}

    # Ensure nested structure
    if "evaluation" not in raw:
        raw["evaluation"] = {}
    if "cost" not in raw["evaluation"]:
        raw["evaluation"]["cost"] = {}
    if "reporting" not in raw:
        raw["reporting"] = {}

    if "cache_responses" in data:
        raw["evaluation"]["cost"]["cache_responses"] = bool(data["cache_responses"])
    if "rate_limit" in data:
        raw["evaluation"]["cost"]["rate_limit"] = float(data["rate_limit"])
    if "max_eval_cost_per_run" in data:
        raw["evaluation"]["cost"]["max_eval_cost_per_run"] = float(data["max_eval_cost_per_run"])
    if "eval_samples" in data:
        raw["evaluation"]["samples"] = max(1, int(data["eval_samples"]))
    if "foundry_upload" in data:
        raw["reporting"]["foundry_upload"] = bool(data["foundry_upload"])

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f)

    return {"message": "Execution settings saved"}


# ---------------------------------------------------------------------------
# Quality gates (CI policy)
# ---------------------------------------------------------------------------


@app.get("/api/settings/gates")
async def get_gates():
    """Return the configured quality-gate thresholds."""
    try:
        config = load_config(_config_path)
        g = config.gates
        return {
            "min_pass_rate": g.min_pass_rate,
            "max_failed": g.max_failed,
            "max_errors": g.max_errors,
            "max_p95_latency_ms": g.max_p95_latency_ms,
            "max_total_cost": g.max_total_cost,
            "min_avg_score": g.min_avg_score,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/settings/gates")
async def save_gates(data: dict):
    """Save quality-gate thresholds to attest.yaml. Null/blank clears a gate."""
    from ruamel.yaml import YAML
    config_path = _get_config_path()
    yaml = YAML()
    yaml.preserve_quotes = True
    raw = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.load(f) or {}

    gates = {}
    for key, cast in (
        ("min_pass_rate", float), ("max_failed", int), ("max_errors", int),
        ("max_p95_latency_ms", float), ("max_total_cost", float), ("min_avg_score", float),
    ):
        val = data.get(key)
        if val is not None and val != "":
            try:
                gates[key] = cast(val)
            except (ValueError, TypeError):
                pass
    if gates:
        raw["gates"] = gates
    elif "gates" in raw:
        del raw["gates"]  # all cleared

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f)
    return {"message": "Quality gates saved", "gates": gates}


# ---------------------------------------------------------------------------
# Notifications (webhook)
# ---------------------------------------------------------------------------


@app.get("/api/settings/notify")
async def get_notify():
    """Return the configured notification settings."""
    try:
        config = load_config(_config_path)
        n = config.notify
        return {"webhook_url": n.webhook_url or "", "on": n.on, "style": n.style}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/settings/notify")
async def save_notify(data: dict):
    """Save notification settings to attest.yaml."""
    from ruamel.yaml import YAML
    config_path = _get_config_path()
    yaml = YAML()
    yaml.preserve_quotes = True
    raw = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.load(f) or {}

    url = (data.get("webhook_url") or "").strip()
    if url:
        raw["notify"] = {
            "webhook_url": url,
            "on": data.get("on", "always"),
            "style": data.get("style", "generic"),
        }
    elif "notify" in raw:
        del raw["notify"]

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f)
    return {"message": "Notification settings saved"}


@app.post("/api/settings/notify/test")
async def test_notify(data: dict):
    """Send a test notification to the given webhook."""
    url = (data.get("webhook_url") or "").strip()
    if not url:
        return JSONResponse({"error": "No webhook URL provided."}, status_code=400)
    style = data.get("style", "generic")
    from attest.utils.notify import _payload
    payload = _payload(style, "✅ ATTEST test notification — your webhook is working.")
    try:
        import httpx
        r = httpx.post(url, json=payload, timeout=10)
        return {"ok": r.status_code < 400, "status": r.status_code}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


# ---------------------------------------------------------------------------
# Doctor (diagnostics)
# ---------------------------------------------------------------------------


@app.get("/api/doctor")
async def doctor_diagnostics():
    """Return a structured health check of the ATTEST setup (for the dashboard)."""
    checks = []

    def add(name, status, detail=""):
        checks.append({"name": name, "status": status, "detail": detail})

    # Config
    config = None
    try:
        config = load_config(_config_path)
        add("Configuration", "ok", "attest.yaml loaded")
    except Exception as e:
        add("Configuration", "error", str(e))

    # Agents
    if config is not None:
        if config.agents:
            add("Agents", "ok", f"{len(config.agents)} configured: {', '.join(config.agents)}")
        else:
            add("Agents", "warn", "no agents configured")

    # Scenarios
    if config is not None:
        try:
            from attest.core.scenario_loader import load_scenarios
            cases = load_scenarios(directory=config.tests.scenarios_dir)
            if cases:
                add("Test scenarios", "ok", f"{len(cases)} test(s) found")
                unknown = {c.agent for c in cases} - set(config.agents) - {"default"}
                if unknown:
                    add("Scenario agents", "warn", f"tests reference unconfigured agent(s): {', '.join(sorted(unknown))}")
            else:
                add("Test scenarios", "warn", "no scenarios found")
        except Exception as e:
            add("Test scenarios", "error", str(e))

    # Evaluator backends
    for label, module, install in (
        ("DeepEval", "deepeval", "pip install deepeval"),
        ("Azure AI Evaluation", "azure.ai.evaluation", "pip install azure-ai-evaluation"),
        ("RAGAS", "ragas", "pip install ragas langchain-openai"),
    ):
        try:
            __import__(module)
            add(f"{label} backend", "ok", "installed")
        except Exception:
            add(f"{label} backend", "warn", f"not installed ({install})")

    # Judge credentials
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_azure = bool(os.environ.get("AZURE_API_KEY_OPENAI") or os.environ.get("AZURE_API_KEY"))
    has_base = bool(os.environ.get("AZURE_API_BASE"))
    if has_openai or (has_azure and has_base):
        add("LLM judge credentials", "ok", "configured")
    elif has_base:
        add("LLM judge credentials", "warn", "endpoint set but no key — will try keyless (az login)")
    else:
        add("LLM judge credentials", "warn", "no credentials — evaluators will error")

    # Gates
    if config is not None:
        from attest.core.gates import gates_are_configured
        if gates_are_configured(config.gates):
            add("Quality gates", "ok", "configured")
        else:
            add("Quality gates", "info", "not set (optional)")

    problems = sum(1 for c in checks if c["status"] == "error")
    warnings = sum(1 for c in checks if c["status"] == "warn")
    healthy = problems == 0
    return {"healthy": healthy, "problems": problems, "warnings": warnings, "checks": checks}

