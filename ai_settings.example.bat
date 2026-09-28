@echo off
REM ---------------------------------------------------------------
REM  Optional settings for the "Ask a question" box.
REM
REM  1. Copy this file to  ai_settings.bat  (same folder).
REM  2. Fill in ONE of the blocks below and save.
REM  3. Start the app with run_web.bat.
REM
REM  ai_settings.bat is in .gitignore: your key stays on your machine.
REM  Never send the filled-in file to anyone.
REM ---------------------------------------------------------------

REM --- Option A: Claude (Anthropic API, needs API credit at console.anthropic.com)
REM set OPENAI_API_KEY=sk-ant-...
REM set OPENAI_BASE_URL=https://api.anthropic.com/v1
REM set IFC_NLQ_MODEL=claude-haiku-4-5-20251001
REM Only if your key is not scoped to a workspace:
REM set ANTHROPIC_WORKSPACE_ID=wrkspc_...

REM --- Option B: OpenAI
REM set OPENAI_API_KEY=sk-...
REM set IFC_NLQ_MODEL=gpt-4o-mini

REM --- Option C: OpenRouter (one key, many models)
REM set OPENROUTER_API_KEY=sk-or-...
