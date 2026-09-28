# Optional settings for the "Ask a question" box (macOS / Linux).
#
# 1. Copy this file to  ai_settings.sh  (same folder).
# 2. Uncomment ONE block below and fill it in.
# 3. Start the app with ./run_web.sh
#
# ai_settings.sh is in .gitignore: your key stays on your machine.

# --- Option A: Claude (Anthropic API, needs API credit at console.anthropic.com)
# export OPENAI_API_KEY="sk-ant-..."
# export OPENAI_BASE_URL="https://api.anthropic.com/v1"
# export IFC_NLQ_MODEL="claude-haiku-4-5-20251001"
# Only if your key is not scoped to a workspace:
# export ANTHROPIC_WORKSPACE_ID="wrkspc_..."

# --- Option B: OpenAI
# export OPENAI_API_KEY="sk-..."
# export IFC_NLQ_MODEL="gpt-4o-mini"

# --- Option C: OpenRouter
# export OPENROUTER_API_KEY="sk-or-..."
