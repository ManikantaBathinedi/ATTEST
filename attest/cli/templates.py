"""Config templates for `attest init`.

These are pre-filled, heavily commented YAML files that get generated
when a user runs `attest init`. Every field has a plain-English comment
so even QA members who've never seen YAML can understand and edit them.
"""

# ---------------------------------------------------------------------------
# Template: HTTP agent (most common)
# ---------------------------------------------------------------------------

HTTP_CONFIG_TEMPLATE = """\
# ============================================================
# ATTEST Configuration
# ============================================================
# This file tells ATTEST how to connect to your agent and
# what kind of testing to do. Edit the values below.
#
# Tip: Lines starting with # are comments (ignored).
# Tip: Use ${ENV_VAR_NAME} to reference secrets from .env file.
# ============================================================

# --- Your project name (just for identification) ---
project:
  name: "{project_name}"

# --- Agent Connection ---
# Tell ATTEST where your agent is and how to talk to it.
agents:
  my_agent:
    # What kind of agent? Options: http, foundry_prompt, foundry_hosted
    type: http

    # The URL where your agent is running
    endpoint: "{endpoint}"

    # How to send messages to your agent
    request:
      method: POST           # Usually POST
      path: "{path}"         # The URL path (e.g. /chat, /api/message)
      body_template:
        # What the request body looks like.
        # {{{{input}}}} gets replaced with the test message.
        {body_key}: "{{{{input}}}}"

    # How to read the agent's response
    response:
      # Where is the response text in the JSON?
      # Examples: $.response, $.answer, $.message, $.choices[0].message.content
      content_path: "{content_path}"

    # Authentication (uncomment and fill in if your agent needs it)
    # auth:
    #   type: api_key                # Options: api_key, bearer, none
    #   header: "Authorization"
    #   prefix: "Bearer"
    #   key: "${{AGENT_API_KEY}}"    # Set AGENT_API_KEY in .env file

    # How long to wait for a response (seconds)
    timeout: 30

# --- Evaluation Settings ---
# How ATTEST judges the quality of agent responses.
evaluation:
  # Which evaluation engine to use:
  #   builtin  = Local LLM judge (needs OPENAI_API_KEY in .env)
  #   azure    = Azure AI Evaluation SDK (needs Azure setup)
  backend: builtin

  # Settings for the built-in LLM judge
  judge:
    model: "openai/gpt-4.1-mini"   # The model that judges responses
    temperature: 0.0                 # Keep at 0 for consistent results

  # Cost protection
  cost:
    max_eval_cost_per_run: 5.00     # Stop if evaluation costs exceed $5
    cache_responses: true            # Cache results to save money on reruns

# --- Where to find tests ---
tests:
  scenarios_dir: "tests/scenarios"   # Folder with YAML test scenarios
  python_tests_dir: "tests"          # Folder with Python test files

# --- Reports ---
reporting:
  output_dir: "reports"              # Where to save test reports
  formats:
    - html                           # Visual report (open in browser)
    - json                           # Machine-readable results
"""

# ---------------------------------------------------------------------------
# Template: Sample test scenario (generated alongside config)
# ---------------------------------------------------------------------------

SAMPLE_SCENARIO_TEMPLATE = """\
# ============================================================
# Sample Test Scenario
# ============================================================
# This file defines test cases for your agent.
# Each test sends a message and checks the response.
#
# Tip: Start simple, add more tests as you go.
# Tip: You don't need all fields — just 'input' is enough!
# ============================================================

name: "Basic Agent Tests"

# Which agent to test (must match a name in attest.yaml → agents)
agent: my_agent

tests:
  # --- Test 1: Simple greeting ---
  # Just check that the agent responds to hello
  - name: greeting
    input: "Hello, how can you help me?"
    assertions:
      - response_not_empty: true

  # --- Test 2: Check response quality ---
  # Send a question and evaluate the answer quality
  - name: sample_question
    input: "What can you do?"
    evaluators:
      - relevancy: {{ threshold: 0.7 }}

  # --- Test 3: Check a specific answer ---
  # Provide the expected answer and check correctness
  # - name: specific_qa
  #   input: "What is your return policy?"
  #   expected_output: "We offer a 30-day full refund."
  #   evaluators:
  #     - correctness: {{ threshold: 0.7 }}

  # --- Test 4: Check tool usage ---
  # Verify the agent calls the right tool
  # - name: tool_check
  #   input: "Track order #12345"
  #   assertions:
  #     - tool_called: track_order
  #     - response_contains: "12345"
"""

# ---------------------------------------------------------------------------
# Template: .env file
# ---------------------------------------------------------------------------

ENV_TEMPLATE = """\
# ============================================================
# ATTEST Environment Variables
# ============================================================
# Put your API keys and secrets here.
# This file should NOT be committed to git.
# ============================================================

# --- For the built-in LLM judge (picks one) ---
OPENAI_API_KEY=your-openai-key-here
# ANTHROPIC_API_KEY=your-anthropic-key-here

# --- For your agent (if it needs authentication) ---
# AGENT_API_KEY=your-agent-key-here

# --- For Azure AI Evaluation SDK (optional) ---
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_OPENAI_API_KEY=your-azure-key
# AZURE_OPENAI_DEPLOYMENT=gpt-4o
"""

# ---------------------------------------------------------------------------
# Template: Foundry agent
# ---------------------------------------------------------------------------

FOUNDRY_CONFIG_TEMPLATE = """\
# ============================================================
# ATTEST Configuration — Azure Foundry Agent
# ============================================================

project:
  name: "{project_name}"

agents:
  my_agent:
    type: foundry_hosted
    endpoint: "{endpoint}"
    auth:
      type: azure_entra
    timeout: 60

evaluation:
  backend: azure
  azure:
    project: "{azure_project}"
    model_config:
      azure_endpoint: "${{AZURE_OPENAI_ENDPOINT}}"
      azure_deployment: "gpt-4o"
  cost:
    max_eval_cost_per_run: 10.00
    cache_responses: true

tests:
  scenarios_dir: "tests/scenarios"

reporting:
  output_dir: "reports"
  formats: [html, json]
"""
