"""
Validation Agent - Chat UI
Main entry point.
"""

import chainlit as cl
import asyncio
import config
from agents.devops_agent import DevOpsAgent
from agents.reporting_agent import ReportingAgent
from agents.analysis_agent import get_analysis_agent
from tools.devops_tools import find_reporting_ticket_by_baseline
from tools.devops_tools import create_and_pull_branch
from agents.compare_agent import CompareAgent
from tools.dotnet_tools import run_program, find_program_file, extract_program_name
from workflows.session_manager import get_session_manager
from agents.script_runner_agent import ScriptRunnerAgent
from utils.logger import get_logger
from utils.progress import ProgressCard
from models.session import StepStatus
from services.orchestrator import get_orchestrator, load_reporting_skill
from services.llm_service import get_llm_service
from tools.workflow_tools import register_many

logger = get_logger("app")


# ── Provider icons + display order (cosmetic, used in the model selector) ─
_PROVIDER_META = {
    "openai":    {"icon": "🟢", "label": "OpenAI",            "order": 0},
    "anthropic": {"icon": "🟠", "label": "Anthropic Claude",  "order": 1},
    "google":    {"icon": "🔵", "label": "Google Gemini",     "order": 2},
}

# Sentinel value put into the dropdown for "section header" rows. If the
# user accidentally selects one of these, on_settings_update ignores it.
_HEADER_SENTINEL_PREFIX = "__header__:"


def _provider_icon_for(provider_key: str) -> str:
    return _PROVIDER_META.get(provider_key, {}).get("icon", "⚪")


def _provider_label_for(provider_key: str, fallback: str = "") -> str:
    return _PROVIDER_META.get(provider_key, {}).get(
        "label", fallback or str(provider_key).title()
    )


def _build_model_select():
    """Build the Chainlit Select widget for the model picker.

    The dropdown is a single flat list (Chainlit doesn't support nested
    submenus in ChatSettings), but it's visually grouped by provider:

        ━━━ 🟢 OpenAI ━━━
            GPT-4.1
            GPT-5.4
        ━━━ 🟠 Anthropic Claude ━━━
            Claude Opus 4.8
            Claude Sonnet 4.6
            ...
        ━━━ 🔵 Google Gemini ━━━
            Gemini 3 Pro (preview)

    Models come from prompts/model_registry.yaml — adding/removing one
    there immediately reflects here (no code change).
    """
    from chainlit.input_widget import Select

    llm = get_llm_service()
    grouped = llm.get_models_by_provider() or {}

    # Sort providers by configured order, unknowns last.
    sorted_providers = sorted(
        grouped.items(),
        key=lambda kv: _PROVIDER_META.get(kv[0], {}).get("order", 99),
    )

    # Build dict[label -> value]. Section headers map to a sentinel value
    # so we can detect & ignore them in on_settings_update.
    items: dict[str, str] = {}
    header_idx = 0
    for provider_key, models in sorted_providers:
        if not models:
            continue
        icon = _provider_icon_for(provider_key)
        plabel = _provider_label_for(provider_key)
        header_idx += 1
        header_display = f"━━━━━━  {icon}  {plabel}  ━━━━━━"
        items[header_display] = f"{_HEADER_SENTINEL_PREFIX}{header_idx}"
        for entry in models:
            if not isinstance(entry, dict):
                continue
            mid = entry.get("id")
            if not mid:
                continue
            mlabel = entry.get("label", mid)
            display = f"        {icon}  {mlabel}"
            if display in items:
                display = f"{display}   ({mid[-12:]})"
            items[display] = mid

    current = llm.get_current_model()

    # Fallback if registry is empty for any reason
    if not items:
        items = {f"⚪  {current}": current}

    # Ensure current model is selectable even if it wasn't in the registry
    if current not in items.values():
        items[f"⚪  {current}  (from .env)"] = current

    # Initial value = the currently active model, so opening the panel
    # always reflects what's actually in use. The "Reset" button is
    # rewired client-side (public/model-picker.js) to revert to the
    # configured DEFAULT_MODEL from .env — Chainlit's built-in Reset
    # only undoes in-dialog edits, it does NOT revert to initial_value.
    # We embed the env default in the description so the JS can read it.
    import os
    default_model = os.getenv("DEFAULT_MODEL") or current

    return Select(
        id="active_model",
        label="🤖  LLM Models. Switch Any time",
        items=items,
        initial_value=current,
        description=f"Choose the model for this session. Reset → {default_model}",
    )


async def _register_chat_settings():
    """Render the gear-icon settings panel with the model selector."""
    try:
        settings = cl.ChatSettings([_build_model_select()])
        await settings.send()
    except Exception as e:
        # Never let UI sugar break the chat session.
        logger.warning(f"Could not render ChatSettings (model picker): {e}")

session_manager = get_session_manager()


# ── Handler output capture ───────────────────────────────────────────
# Wraps cl.Message.send so every message a handler sends during
# execution is silently recorded in cl.user_session["_handler_output"].
# This lets follow-up questions ("give me a summary") include the
# actual execution details (timing, comparison results, ticket numbers)
# without modifying any handler code.
_original_cl_msg_send = cl.Message.send


async def _capturing_cl_msg_send(self):
    result = await _original_cl_msg_send(self)
    try:
        buf = cl.user_session.get("_handler_output")
        if buf is not None and self.content:
            buf.append(self.content)
    except Exception:
        pass  # user_session not available (e.g. during startup)
    return result


cl.Message.send = _capturing_cl_msg_send


def _msg(key: str, **kwargs) -> str:
    """Shortcut for skill-file message lookup (see WORKFLOW_ORCHESTRATION_SKILL.md)."""
    return get_orchestrator().get_message(key, **kwargs)


def _build_rich_history(
    tool: str | None,
    args: str,
    baseline: str | None,
    handler_output: list[str] | None = None,
) -> str:
    """Build a rich conversation history entry after a tool execution.

    Combines three data sources so the LLM can answer follow-up questions
    accurately:
      1. Which tool was called and with what arguments
      2. Session state (step-by-step status from SessionManager)
      3. Actual handler output messages captured during execution
    """
    if not tool:
        return "Responded with a conversational answer (no tool was called)."

    parts = [f"Executed tool '{tool}'"]
    if args:
        parts[0] += f" with args '{args}'"
    if baseline:
        parts[0] += f" for baseline {baseline}"

    # ── Actual handler output (captured via _capturing_cl_msg_send) ──
    if handler_output:
        combined = "\n---\n".join(handler_output[-20:])
        # Cap total size to avoid bloating context.
        if len(combined) > 5000:
            combined = combined[-5000:]
        parts.append(f"Execution output:\n{combined}")

    # ── Session state enrichment ─────────────────────────────────────
    if baseline:
        try:
            summary = session_manager.get_session_summary(baseline)
            steps = summary.get("steps", {})
            completed = summary.get("completed", 0)
            failed = summary.get("failed", 0)
            total = summary.get("total_steps", 0)
            next_step = summary.get("next_step")

            parts.append(
                f"Session state: {completed}/{total} steps completed"
                + (f", {failed} failed" if failed else "")
                + (f". Next pending step: {next_step}" if next_step else ". All steps done!")
            )

            step_lines = []
            for step_name, status in steps.items():
                icon = {"completed": "✅", "failed": "❌", "pending": "⏳", "running": "🔄"}.get(status, "⏳")
                step_lines.append(f"  {icon} {step_name}: {status}")
            if step_lines:
                parts.append("Step details:\n" + "\n".join(step_lines))
        except Exception:
            pass  # Session not found — skip enrichment.

    return "\n".join(parts)

@cl.on_chat_start
async def on_chat_start():
    # Chainlit fires this on every websocket connect — including browser
    # refreshes and network reconnects, not just true "new chat" clicks.
    # We mark the user_session the first time we render the welcome so
    # subsequent reconnects (within `session_timeout` from
    # `.chainlit/config.toml`) are silent and keep all in-memory state
    # (agentic_history, chat_history, active program/baseline). A real
    # reset only happens when the user clicks "New Chat" in the UI
    # (which `confirm_new_chat = true` already guards).
    if cl.user_session.get("welcomed"):
        logger.info("Chat session reconnected — preserving state, no welcome")
        return

    logger.info("New chat session started")
    cl.user_session.set("welcomed", True)

    # Render the ⚙ settings panel with the model selector (non-blocking,
    # purely additive — does not change existing welcome flow).
    await _register_chat_settings()

    # Welcome markdown lives in prompts/welcome.md (referenced from the
    # skill file as `ui.welcome_file`). The orchestrator loads and caches
    # it at startup, so this is a pure in-memory lookup per session.
    welcome = get_orchestrator().get_welcome_text()
    await cl.Message(content=welcome).send()


@cl.on_chat_resume
async def on_chat_resume(thread):
    # Fires when Chainlit's data layer resumes a previous thread (e.g. user
    # navigates back into a saved chat). We deliberately do nothing here:
    # the user is continuing an existing conversation, so re-rendering the
    # welcome or resetting any session state would be wrong.
    logger.info("Chat session resumed — no welcome, state preserved")
    cl.user_session.set("welcomed", True)
    # Re-render the settings panel so the model picker is still available
    # on resumed sessions (Chainlit drops widget state on reconnect).
    await _register_chat_settings()


@cl.on_settings_update
async def on_settings_update(settings: dict):
    """Apply UI changes from the ⚙ settings panel.

    Currently handles only the model selector. We intentionally keep this
    handler tiny and defensive so it can never break a chat session.
    """
    new_model = (settings or {}).get("active_model")
    if not new_model:
        return

    # Ignore clicks on the "━━━ Provider ━━━" section header rows.
    if isinstance(new_model, str) and new_model.startswith(_HEADER_SENTINEL_PREFIX):
        await cl.Message(
            content=(
                "ℹ️ That's a **section header**, not a model. "
                "Open the ⚙ settings panel again and pick an indented "
                "model name underneath the header."
            ),
            author="System",
        ).send()
        return

    llm = get_llm_service()
    previous = llm.get_current_model()
    if new_model == previous:
        return

    try:
        llm.set_model(new_model)
        cl.user_session.set("active_model", new_model)
        logger.info(f"User switched model: {previous} → {new_model}")
    except Exception as e:
        logger.error(f"Failed to switch model to {new_model}: {e}")
        await cl.Message(
            content=f"⚠️ Could not switch model to `{new_model}`: {e}",
            author="System",
        ).send()


@cl.on_message
async def on_message(message: cl.Message):
    content = message.content.strip()
    logger.info(f"Received: {content}")

    # All routing is driven by prompts/WORKFLOW_ORCHESTRATION_SKILL.md
    # via services/orchestrator.py.  Adding a new command requires only a
    # skill-file entry plus a registered handler — no edits in this file.
    orchestrator = get_orchestrator()

    # ── Conversation memory ──────────────────────────────────────────
    # Retrieve prior turns so the LLM can resolve references like
    # "it", "now load", "that baseline".  Stored per Chainlit session.
    agentic_history = cl.user_session.get("agentic_history") or []

    # Start collecting handler output so follow-up questions can
    # reference the actual execution details (timing, results, etc.).
    cl.user_session.set("_handler_output", [])

    result = await orchestrator.agentic_dispatch(content, conversation_history=agentic_history)

    # Retrieve captured handler output and stop collecting.
    handler_output = cl.user_session.get("_handler_output") or []
    cl.user_session.set("_handler_output", None)

    # Append this turn to history.  Each turn is a user message +
    # a rich assistant summary (including actual handler output) so the
    # LLM can answer follow-up questions accurately.
    agentic_history.append({"role": "user", "content": content})
    if result:
        tool = result.get("tool")
        args = result.get("args", "")
        baseline = result.get("baseline")
        # Only include handler output for tool executions, not for
        # LLM text responses (which would just duplicate content).
        output = handler_output if tool else None
        summary = _build_rich_history(tool, args, baseline, output)
        agentic_history.append({"role": "assistant", "content": summary})

    # Cap history to avoid unbounded growth (matches skill-file config).
    max_turns = 20  # store pairs; the LLM receives max_history_turns from this
    cl.user_session.set("agentic_history", agentic_history[-(max_turns * 2):])



async def handle_chat(content: str):
    """Route a free-form natural-language message to the chat agent.

    Maintains a small per-session history and the last detected program /
    baseline so multi-turn conversations stay coherent. Never raises — all
    errors degrade to a user-visible message.
    """
    # Lazy import keeps app start-up fast and avoids a hard dependency on the
    # chat prompt files being present until the feature is first used.
    from agents.chat_agent import ChatTurn, get_chat_agent

    history_raw = cl.user_session.get("chat_history") or []
    history = [
        ChatTurn(role=item.get("role", "user"), content=item.get("content", ""))
        for item in history_raw
        if isinstance(item, dict)
    ]
    active_program = cl.user_session.get("chat_active_program")
    active_baseline = cl.user_session.get("chat_active_baseline")

    # Stream tokens into a live Chainlit message (ChatGPT/Copilot style).
    # The message is created empty, then each token is appended via
    # `stream_token` as it arrives from the LLM. The final content is
    # whitespace-trimmed before the closing update.
    msg = cl.Message(content="")
    await msg.send()

    try:
        agent = get_chat_agent()
        response = await agent.chat_stream(
            user_message=content,
            history=history,
            active_program=active_program,
            active_baseline=active_baseline,
            on_token=msg.stream_token,
        )
        reply_text = response.text
        program_name = response.program_name
        baseline_name = response.baseline_name
    except Exception as exc:
        logger.error(f"Chat agent error: {exc}")
        reply_text = (
            f"❌ Chat assistant error: `{exc}`\n\n"
            "Existing commands (`help`, `list`, `validate`, ...) still work."
        )
        program_name = active_program
        baseline_name = active_baseline

    # Persist conversation state (cap history at 12 messages).
    history_raw.append({"role": "user", "content": content})
    history_raw.append({"role": "assistant", "content": reply_text})
    cl.user_session.set("chat_history", history_raw[-12:])
    if program_name:
        cl.user_session.set("chat_active_program", program_name)
    if baseline_name:
        cl.user_session.set("chat_active_baseline", baseline_name)

    # Final trim + flush: replaces streamed content with the canonical,
    # whitespace-trimmed reply so any trailing tokens / partial chunks
    # are normalised before the message is sealed.
    msg.content = (reply_text or "").strip()
    await msg.update()


async def handle_help():
    help_text = """
# 📖 Help

## Step Commands
| Command | Step | Description |
|---------|------|-------------|
| `copy <baseline>` | 1 | Copy baseline files |
| `load <baseline>` | 2 | Load data to DB |
| `branch <baseline>` | 3a | Create branch from master |
| `run <baseline>` | 3b | Run C# code (dotnet run) |
| `unload <baseline>` | 5 | Unload from DB |
| `compare <baseline>` | 6 | Compare output files |
| `report <baseline>` | 7 | Generate report |
| `finalize <baseline>` | 8 | Push code & create PR |

## Other Commands
| Command | Description |
|---------|-------------|
| `validate <baseline>` | Run all steps |
| `status <baseline>` | Show progress |
| `reset <baseline>` | Reset all steps |
| `list` | List all sessions |

## Example
"""
    await cl.Message(content=help_text).send()


async def handle_list():
    sessions = session_manager.list_sessions()
    
    if not sessions:
        await cl.Message(content=_msg("list.empty")).send()
        return
    
    lines = [_msg("list.header")]
    for baseline in sessions:
        summary = session_manager.get_session_summary(baseline)
        status = "✅ Done" if summary['is_done'] else f"🔄 {summary['completed']}/{summary['total_steps']}"
        lines.append(f"- `{baseline}` ({summary['group']}) - {status}")
    
    await cl.Message(content="\n".join(lines)).send()


async def handle_status(baseline: str):
    if not baseline:
        await cl.Message(content=_msg("usage.status")).send()
        return
    
    status_display = session_manager.format_status_display(baseline)
    await cl.Message(content=status_display).send()


async def handle_reset(baseline: str):
    if not baseline:
        await cl.Message(content=_msg("usage.reset")).send()
        return
    
    session = session_manager.get_session(baseline)
    session.reset_all()
    await cl.Message(content=_msg("reset.success", baseline=baseline)).send()


async def handle_copy(baseline: str):
    """Step 1: Copy baseline from G: to C:"""
    if not baseline:
        await cl.Message(content=_msg("usage.copy")).send()
        return
    
    # Get session and agent
    session = session_manager.get_session(baseline)
    agent = ScriptRunnerAgent(session)

    # Run blocking operation in thread pool with a live progress card
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(
        None,
        lambda: asyncio.run(agent.run_step_1_copy())
    )

    async with ProgressCard(
        "Step 1: Copy Baseline", baseline, interval=10, eta_seconds=120
    ) as card:
        await card.wait_for(future, status="Copying input files...")
        success, message = await future
        if success:
            await card.complete("Copy complete")
        else:
            await card.fail(message or "Failed")

    if success:
        await cl.Message(content=_msg("copy.success", baseline=baseline)).send()
    else:
        await cl.Message(content=_msg("copy.failure", error=message)).send()

async def handle_branch(baseline: str):
    """Step 3a: Create branch and pull to local"""
    if not baseline:
        await cl.Message(content=_msg("usage.branch")).send()
        return
    
    # Show starting message
    await cl.Message(content=_msg("branch.starting", baseline=baseline)).send()
    
    try:
        # Get session and create agent
        session = session_manager.get_session(baseline)
        agent = DevOpsAgent(session)
        
        # Run via agent
        loop = asyncio.get_event_loop()
        success, result = await loop.run_in_executor(
            None,
            agent.run_step_3a_branch
        )
        
        if success:
            branch_name = result.get("branch_name", "")
            branch_url = result.get("branch_url", "")
            ticket_id = result.get("ticket_id")
            ticket_url = result.get("ticket_url", "")
            
            # Build ticket link if available
            ticket_link = ""
            if ticket_id and ticket_url:
                ticket_link = f"\n• 🎫 [Ticket {ticket_id}]({ticket_url})"
            
            summary = f"""✅ **Step 3a: Complete!**

Branch ready for `{baseline}`

**What was done:**
• ✅ Branch created/verified
• ✅ Code pulled to local
• ✅ Ready to run

**Links:**
• 🔗 [Branch: {branch_name}]({branch_url}){ticket_link}

**Next Steps:**
• Run `run {baseline}` (Step 3b)"""

            await cl.Message(content=summary).send()
        else:
            error_msg = result.get("message", "Unknown error")
            await cl.Message(content=f"❌ **Step 3a: Failed**\n\n{error_msg}").send()
            
    except Exception as e:
        await cl.Message(content=f"❌ **Step 3a: Unexpected Error**\n\n```\n{str(e)}\n```").send()
        logger.error(f"Unexpected error in handle_branch: {e}")

async def handle_run(baseline: str):
    """Step 3b: Run C# program"""
    if not baseline:
        await cl.Message(content=_msg("usage.run")).send()
        return
    
    from tools.dotnet_tools import extract_program_name, find_program_file
    
    program_name = extract_program_name(baseline)

    # Check if program exists first
    found, path_or_msg = find_program_file(program_name)
    if not found:
        await cl.Message(content=f"❌ **Step 3b: Program Not Found**\n\n{path_or_msg}\n\n💡 Create the program first, then run again.").send()
        return

    try:
        # Get session and create agent
        session = session_manager.get_session(baseline)
        agent = ScriptRunnerAgent(session)

        # Run via agent with a live progress card
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            None,
            agent.run_step_3b_run
        )

        async with ProgressCard(
            f"Step 3b: Run {program_name}", baseline, interval=15, eta_seconds=180
        ) as card:
            await card.wait_for(future, status=f"Executing `{path_or_msg}`...")
            success, result = await future
            if success:
                await card.complete("Run complete")
            else:
                err = (result.get("error_info") or {}).get("error_message", "Failed")
                await card.fail(err)
        
        if success:
            # Get output preview
            output_text = result.get("output") or ""
            output_preview = output_text[:1500] if output_text else "No output"
            if len(output_text) > 1500:
                output_preview += "\n... (truncated)"
            
            # Check for warnings
            error_info = result.get("error_info") or {}
            warnings = error_info.get("warnings", [])
            warning_text = ""
            if warnings:
                warning_text = f"\n\n**Warnings ({len(warnings)}):**\n```\n" + "\n".join(warnings[:5]) + "\n```"
            
            summary = f"""✅ **Step 3b: Complete!**

Program `{program_name}` executed successfully.
{warning_text}

**Output:**
**Next Steps:**
• Run `unload {baseline}` (Step 5)
• Then `compare {baseline}` (Step 6)"""
            
            await cl.Message(content=summary).send()
        else:
            error_info = result.get("error_info") or {}
            error_type = error_info.get("error_type", "unknown")
            error_msg = error_info.get("error_message", "Unknown error")
            stack_trace = error_info.get("stack_trace", "")
            sql_error = error_info.get("sql_error", "")
            exit_code = result.get("exit_code", 1)
            
            # Build error display
            error_display = f"**Error Type:** `{error_type}`\n\n"
            
            if sql_error:
                error_display += f"**SQL Error:**\n```\n{sql_error}\n```\n\n"
            
            if error_msg:
                error_display += f"**Message:**\n```\n{error_msg}\n```\n\n"
            
            if stack_trace:
                error_display += f"**Stack Trace:**\n```\n{stack_trace}\n```\n\n"
            
            summary = f"""❌ **Step 3b: Failed**

Program `{program_name}` failed.

{error_display}

**Next Steps:**
• Fix the error manually
• Or click "Analyse with AI" for automated analysis
• Then run `run {baseline}` again"""
            
            # Create AI analysis button
            actions = [
                cl.Action(
                    name="analyse_with_ai",
                    payload={
                        "baseline": baseline,
                        "program_name": program_name,
                        "error_message": error_msg,
                        "error_type": error_type,
                        "stack_trace": stack_trace,
                        "exit_code": exit_code
                    },
                    label="🤖 Analyse with AI"
                )
            ]
            
            await cl.Message(content=summary, actions=actions).send()
            
    except Exception as e:
        await cl.Message(content=f"❌ **Step 3b: Unexpected Error**\n\n```\n{str(e)}\n```").send()
        logger.error(f"Unexpected error in handle_run: {e}")   
        
        

async def handle_load(baseline: str):
    """Step 2: Load data to DB"""
    if not baseline:
        await cl.Message(content=_msg("usage.load")).send()
        return
    
    # Show starting message
    msg = cl.Message(content=_msg("load.starting", baseline=baseline))
    await msg.send()
    
    
    await asyncio.sleep(0.5)
    
    # Get session and run agent
    session = session_manager.get_session(baseline)
    agent = ScriptRunnerAgent(session)
    
    success, message = await agent.run_step_2_load()
    
    if success:
        await cl.Message(content=_msg("load.success", baseline=baseline)).send()
    else:
        await cl.Message(content=_msg("load.failure", error=message)).send()
 


async def handle_unload(baseline: str):
    """Step 5: Unload from DB"""
    if not baseline:
        await cl.Message(content=_msg("usage.unload")).send()
        return
    
    # Show starting message
    msg = cl.Message(content=_msg("unload.starting", baseline=baseline))
    await msg.send()
    
    
    await asyncio.sleep(0.5)
    
    # Get session and run agent
    session = session_manager.get_session(baseline)
    agent = ScriptRunnerAgent(session)
    
    success, message = await agent.run_step_5_unload()
    
    if success:
        await cl.Message(content=_msg("unload.success", baseline=baseline)).send()
    else:
        await cl.Message(content=_msg("unload.failure", error=message)).send()


async def handle_compare(baseline_name: str):
    """Handle Step 6: Compare output."""
    if not baseline_name:
        await cl.Message(content=_msg("usage.compare")).send()
        return
    
    session = session_manager.get_session(baseline_name)
    agent = CompareAgent(session)

    # Word-popup warning shown once before the live progress card
    await cl.Message(content=_msg("compare.word_popup_note")).send()

    try:
        # Run compare in executor with a live progress card
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            None,
            agent.run_step_6_compare
        )

        async with ProgressCard(
            "Step 6: Compare Output", baseline_name, interval=15, eta_seconds=180
        ) as card:
            await card.wait_for(future, status="Comparing & generating report...")
            success, result = await future
            if success:
                await card.complete("Compare complete")
            else:
                await card.fail(result.get("message") or "Compare failed")
        
        await cl.Message(content=f"❌ **Step 6: Compare Failed**\n\n{result.get('message')}").send()

        if not success:
            await cl.Message(content=f"❌ **Step 6: Compare Failed**\n\n{result.get('message')}").send()
            return
        
        # Build result message
        all_pass = result.get("all_pass", False)
        csv_pass = result.get("after_csv_pass", 0)
        csv_fail = result.get("after_csv_fail", 0)
        root_pass = result.get("root_mixed_pass", 0)
        root_fail = result.get("root_mixed_fail", 0)
        failed_files = result.get("failed_files", [])
        report_path = result.get("report_path", "")
        
        if all_pass:
            # All passed - no approval needed
            content = f"""✅ **Step 6: Compare Complete**

**Baseline:** `{baseline_name}`

**Results:**
├── AFTER CSV: {csv_pass} pass, {csv_fail} fail ✅
└── Root Mixed: {root_pass} pass, {root_fail} fail ✅

All files match! No differences found.

**Next:** Run `finalize {baseline_name}` (Step 8)"""
            
            await cl.Message(content=content).send()
        else:
            # Differences found - need approval
            failed_list = "\n".join([f"• {f}" for f in failed_files]) if failed_files else "• See report for details"
            
            content = f"""⚠️ **Step 6: Differences Found**

**Baseline:** `{baseline_name}`

**Results:**
├── AFTER CSV: {csv_pass} pass, {csv_fail} fail {"✅" if csv_fail == 0 else "⚠️"}
└── Root Mixed: {root_pass} pass, {root_fail} fail {"✅" if root_fail == 0 else "⚠️"}

**Differences in:**
{failed_list}

**Report:** `{report_path}`

Please review the report and confirm:"""
            
            # Create action buttons
            actions = [
                cl.Action(name="compare_acceptable", payload={"baseline": baseline_name}, label="✅ Acceptable"),
                cl.Action(name="compare_not_acceptable", payload={"baseline": baseline_name}, label="❌ Not Acceptable")
            ]
            
            await cl.Message(content=content, actions=actions).send()
            
    except Exception as e:
        await cl.Message(content=f"❌ **Step 6: Unexpected Error**\n\n```\n{str(e)}\n```").send()
        logger.error(f"Unexpected error in handle_compare: {e}")


@cl.action_callback("compare_acceptable")
async def on_compare_acceptable(action: cl.Action):
    """Handle acceptable button click."""
    baseline_name = action.payload.get("baseline")
    session = session_manager.get_session(baseline_name)  ##session manager stores
    agent = CompareAgent(session)
    
    success, message = agent.mark_acceptable()
    
    await cl.Message(content=f"""✅ **Step 6: Complete**

Differences marked as **acceptable**.

**Next:** Run `finalize {baseline_name}` (Step 8)""").send()


@cl.action_callback("compare_not_acceptable")
async def on_compare_not_acceptable(action: cl.Action):
    """Handle not acceptable button click."""
    baseline_name = action.payload.get("baseline")
    session = session_manager.get_session(baseline_name)  
    agent = CompareAgent(session)
    
    success, message = agent.mark_not_acceptable()
    
    await cl.Message(content=f"""❌ **Step 6: Not Acceptable**

Differences marked as **not acceptable**.

**Action needed:**
1. Review the differences in report
2. Fix the code
3. Run `run {baseline_name}` to re-test
4. Run `compare {baseline_name}` again

_(Future: AI Analysis will suggest fixes)_""").send()


@cl.action_callback("analyse_with_ai")
async def on_analyse_with_ai(action: cl.Action):
    baseline = action.payload.get("baseline")
    program_name = action.payload.get("program_name")
    error_message = action.payload.get("error_message", "Unknown error")
    error_type = action.payload.get("error_type", "unknown")
    stack_trace = action.payload.get("stack_trace")
    exit_code = action.payload.get("exit_code", 1)

    await cl.Message(content=f"""🤖 **AI Analysis Started**

**Program:** `{program_name}`
**Baseline:** `{baseline}`

⏳ Analyzing error and searching for similar fixes...
This may take 30-60 seconds.""").send()

    try:
        analysis_agent = get_analysis_agent()

        suggestion = await analysis_agent.analyze_runtime_error(
            baseline_name=baseline,
            program_name=program_name,
            error_message=error_message,
            exit_code=exit_code,
            stack_trace=stack_trace
        )

        if suggestion.confidence >= 70:
            confidence_emoji = "🟢"
            confidence_text = "High"
        elif suggestion.confidence >= 50:
            confidence_emoji = "🟡"
            confidence_text = "Medium"
        else:
            confidence_emoji = "🔴"
            confidence_text = "Low"
        
        similar_fixes_text = ""
        if suggestion.similar_fixes_used:
            similar_fixes_text = "\n**📚 Similar Past Fixes Found:**\n"
            for fix in suggestion.similar_fixes_used[:3]:
                similar_fixes_text += f"• PR #{fix.pr_id}: `{fix.baseline}`\n"

        code_section = ""
        if suggestion.original_code and suggestion.suggested_code:
            code_section = (
                "\n---\n\n"
                "**❌ Original Code:**\n"
                "```csharp\n"
                + suggestion.original_code +
                "\n```\n\n"
                "**✅ Suggested Fix:**\n"
                "```csharp\n"
                + suggestion.suggested_code +
                "\n```\n"
            )

        review_warning = ""
        if suggestion.requires_manual_review:
            review_warning = "\n⚠️ **Manual review recommended** (confidence below 70%)\n"

        line_info = ""
        if suggestion.line_number:
            line_info = f"\n**Line Number:** {suggestion.line_number}"
    
        result_message = f"""🤖 **AI Analysis Complete**

**Program:** `{program_name}`
**Baseline:** `{baseline}`
**Confidence:** {confidence_emoji} {suggestion.confidence}% ({confidence_text})
{review_warning}
---

**🔍 Root Cause:**
{suggestion.root_cause}

---

**📋 Analysis:**
{suggestion.explanation}

---

**📁 File to Fix:** `{suggestion.file_to_fix}`{line_info}
{code_section}
---

**🏷️ Fix Type:** `{suggestion.fix_type}`
{similar_fixes_text}
---

**📝 Additional Notes:**
{suggestion.additional_notes or "None"}

---

**Next Steps:**
1. Review the suggested fix above
2. Apply changes to: `{suggestion.file_to_fix}`
3. Run `run {baseline}` to test the fix
4. If still fails, click "Re-analyse" for another suggestion"""
        
        session = analysis_agent.get_session(baseline)
        attempt_info = ""
        if session:
            attempt_info = f" (Attempt {session.current_attempt}/{session.max_attempts})"

        actions = [
            cl.Action(
                name="retry_analysis",
                payload={
                    "baseline": baseline,
                    "program_name": program_name,
                    "error_message": error_message,
                    "stack_trace": stack_trace
                },
                label=f"🔄 Re-analyse{attempt_info}"
            ),
            cl.Action(
                name="mark_fix_applied",
                payload={
                    "baseline": baseline,
                    "program_name": program_name,
                    "file_to_fix": suggestion.file_to_fix
                },
                label="✅ Fix Applied - Run Again"
            )
        ]

        await cl.Message(content=result_message, actions=actions).send()

    except Exception as e:
        logger.error(f"AI Analysis error: {e}")
        await cl.Message(content=f"""❌ **AI Analysis Failed**

**Error:** `{str(e)}`

**Possible Causes:**
• EnsoAI API not configured (check .env)
• COBOL source not found in knowledge base
• Network/API timeout

**Fallback Steps:**
1. Review the error manually
2. Check COBOL source for expected behavior
3. Compare with similar programs
4. Fix and run `run {baseline}` again

**Debug:**
• Check logs for details
• Verify ENSO_AI_API_URL and ENSO_AI_API_KEY in .env""").send()


@cl.action_callback("retry_analysis")
async def on_retry_analysis(action: cl.Action):
    baseline = action.payload.get("baseline")
    program_name = action.payload.get("program_name")
    error_message = action.payload.get("error_message", "Unknown error")
    stack_trace = action.payload.get("stack_trace")

    await cl.Message(content=f"""🔄 **Re-analysing...**

**Program:** `{program_name}`

⏳ Trying a different approach...""").send()

    try:
        analysis_agent = get_analysis_agent()
        session = analysis_agent.get_session(baseline)

        if session and not session.can_retry:
            await cl.Message(content=f"""⚠️ **Maximum Attempts Reached**

**Program:** `{program_name}`
**Attempts:** {session.current_attempt}/{session.max_attempts}

The AI has tried {session.max_attempts} different approaches without success.

**Recommendation:**
• Review all previous suggestions
• Manual investigation required
• Consider creating a bug ticket

**Previous Attempts Summary:**
{session.get_failed_fixes_summary()}""").send()
            return

        suggestion = await analysis_agent.retry_analysis(
            baseline_name=baseline,
            new_error_message=error_message,
            stack_trace=stack_trace
        )
        
        if suggestion.confidence >= 70:
            confidence_emoji = "🟢"
        elif suggestion.confidence >= 50:
            confidence_emoji = "🟡"
        else:
            confidence_emoji = "🔴"

        session = analysis_agent.get_session(baseline)
        attempt_text = f"Attempt {session.current_attempt}/{session.max_attempts}" if session else ""

        code_section = ""
        if suggestion.original_code and suggestion.suggested_code:
            code_section = (
                "\n**❌ Original Code:**\n"
                "```csharp\n"
                + suggestion.original_code +
                "\n```\n\n"
                "**✅ Suggested Fix:**\n"
                "```csharp\n"
                + suggestion.suggested_code +
                "\n```\n"
            )

        result_message = f"""🤖 **Re-Analysis Complete** ({attempt_text})

**Program:** `{program_name}`
**Confidence:** {confidence_emoji} {suggestion.confidence}%

---

**🔍 Root Cause:**
{suggestion.root_cause}

---

**📁 File to Fix:** `{suggestion.file_to_fix}`
{code_section}
---

**📝 Notes:**
{suggestion.additional_notes or "None"}

---

**Next Steps:**
1. Apply this fix to: `{suggestion.file_to_fix}`
2. Run `run {baseline}` to test"""
        
        actions = []

        if session and session.can_retry:
            actions.append(
                cl.Action(
                    name="retry_analysis",
                    payload={
                        "baseline": baseline,
                        "program_name": program_name,
                        "error_message": error_message,
                        "stack_trace": stack_trace
                    },
                    label=f"🔄 Try Again ({session.current_attempt}/{session.max_attempts})"
                )
            )

        actions.append(
            cl.Action(
                name="mark_fix_applied",
                payload={
                    "baseline": baseline,
                    "program_name": program_name,
                    "file_to_fix": suggestion.file_to_fix
                },
                label="✅ Fix Applied - Run Again"
            )
        )

        await cl.Message(content=result_message, actions=actions).send()

    except ValueError as e:
        await cl.Message(content=f"""⚠️ **No Previous Analysis Found**

Run `run {baseline}` first to trigger an error, then click "Analyse with AI".""").send()

    except Exception as e:
        logger.error(f"Re-analysis error: {e}")
        await cl.Message(content=f"""❌ **Re-analysis Failed**

**Error:** `{str(e)}`

**Try:**
• Run `run {baseline}` again to get fresh error
• Then click "Analyse with AI" """).send()


@cl.action_callback("mark_fix_applied")
async def on_mark_fix_applied(action: cl.Action):
    baseline = action.payload.get("baseline")
    program_name = action.payload.get("program_name")
    file_to_fix = action.payload.get("file_to_fix", "")
    await cl.Message(content=f"""✅ **Fix Applied**

**File:** `{file_to_fix}`

Now re-running the program to test...""").send()
    
    await handle_run(baseline)




async def handle_report(baseline: str):
    if not baseline:
        await cl.Message(content=_msg("usage.report")).send()
        return
    
    await cl.Message(content=_msg("not_implemented.report", baseline=baseline)).send()


async def handle_finalize(baseline: str):
    if not baseline:
        await cl.Message(content=_msg("usage.finalize")).send()
        return
    
    await cl.Message(content=_msg("not_implemented.finalize", baseline=baseline)).send()


async def handle_validate(baseline: str):
    if not baseline:
        await cl.Message(content=_msg("usage.validate")).send()
        return
    
    await cl.Message(content=_msg("not_implemented.validate", baseline=baseline)).send()
    
    
    
async def handle_reporting(baseline_name: str):
    """Handle reporting command - runs all 6 steps.

    Steps 1-4 are driven by the reporting skill file
    (prompts/REPORTING_SKILL.md).  Steps 5-6 have custom post-processing
    (compare results / ticket closing) that stays inline.
    """
    if not baseline_name:
        await cl.Message(content=_msg("usage.reporting")).send()
        return

    skill = load_reporting_skill()
    session = session_manager.get_session(baseline_name)
    agent = ReportingAgent(session)
    total = skill.get("total_steps", 6)

    # Start message
    start_msg = skill.get("start_message", "").strip()
    if start_msg:
        await cl.Message(content=start_msg.format(baseline_name=baseline_name)).send()

    loop = asyncio.get_event_loop()

    # ── Steps 1-4: skill-driven loop ─────────────────────────────────
    for step_cfg in skill.get("steps", []):
        # Optional pre-message
        pre = step_cfg.get("pre_message")
        if pre:
            await cl.Message(content=pre).send()

        # Execute with ProgressCard
        handler_fn = getattr(agent, step_cfg["function"])
        future = loop.run_in_executor(None, handler_fn)

        card_title = f"Step {step_cfg['number']}/{total}: {step_cfg['title']}"
        async with ProgressCard(
            card_title, baseline_name,
            interval=step_cfg.get("progress_interval", 10),
            eta_seconds=step_cfg.get("progress_eta", 120),
        ) as card:
            await card.wait_for(
                future, status=step_cfg.get("progress_status", "Processing...")
            )
            success, result = await future
            if success:
                await card.complete(
                    step_cfg.get("progress_complete", f"{step_cfg['title']} complete")
                )
            else:
                error = _extract_step_error(result, step_cfg.get("error_path"))
                await card.fail(
                    error or step_cfg.get("progress_fail_default", "Failed")
                )

        if not success:
            error = _extract_step_error(result, step_cfg.get("error_path")) or "Unknown error"
            fail_tpl = step_cfg.get("fail", "❌ Step failed: {error}")
            await cl.Message(content=fail_tpl.format(error=error)).send()
            return

        success_tpl = step_cfg.get("success", "")
        if success_tpl:
            try:
                safe = {k: (v if v is not None else "") for k, v in result.items() if isinstance(k, str)}
                await cl.Message(content=success_tpl.format(**safe)).send()
            except (KeyError, IndexError, ValueError):
                await cl.Message(content=success_tpl).send()

    # ── Step 5: Compare (custom result handling) ─────────────────────
    cmp = skill.get("compare", {})
    cmp_pre = cmp.get("pre_message")
    if cmp_pre:
        await cl.Message(content=cmp_pre).send()

    future = loop.run_in_executor(None, agent.run_step_5_compare)

    async with ProgressCard(
        f"Step 5/{total}: Compare Output", baseline_name,
        interval=cmp.get("progress_interval", 15),
        eta_seconds=cmp.get("progress_eta", 180),
    ) as card:
        await card.wait_for(
            future, status=cmp.get("progress_status", "Comparing...")
        )
        success, result = await future
        if success:
            await card.complete(cmp.get("progress_complete", "Compare complete"))
        else:
            await card.fail(
                result.get("message") or cmp.get("progress_fail_default", "Compare failed")
            )

    if not success:
        fail_tpl = cmp.get("fail", "❌ **Step 5 Failed: Compare**\n\n{error}")
        await cl.Message(
            content=fail_tpl.format(error=result.get("message", "Unknown error"))
        ).send()
        return

    # Compare result handling
    all_pass = result.get("all_pass", False)
    csv_pass = result.get("after_csv_pass", 0)
    csv_fail = result.get("after_csv_fail", 0)
    root_pass = result.get("root_mixed_pass", 0)
    root_fail = result.get("root_mixed_fail", 0)
    failed_files = result.get("failed_files", [])
    report_path = result.get("report_path", "")

    if all_pass:
        all_pass_tpl = cmp.get("all_pass", "✅ **Step 5: Compare - All Pass!**")
        await cl.Message(content=all_pass_tpl.format(
            csv_pass=csv_pass, csv_fail=csv_fail,
            root_pass=root_pass, root_fail=root_fail,
        ).strip()).send()

        # Continue to Step 6
        await handle_reporting_step_6(baseline_name, agent, report_path)
    else:
        # Differences found - ask user
        failed_list = "\n".join([f"• {f}" for f in failed_files]) if failed_files else "• See report"
        csv_icon = "✅" if csv_fail == 0 else "⚠️"
        root_icon = "✅" if root_fail == 0 else "⚠️"

        diff_tpl = cmp.get("differences_found", "⚠️ **Step 5: Differences Found**")
        content = diff_tpl.format(
            csv_pass=csv_pass, csv_fail=csv_fail,
            root_pass=root_pass, root_fail=root_fail,
            csv_icon=csv_icon, root_icon=root_icon,
            failed_list=failed_list, report_path=report_path,
        ).strip()

        actions = [
            cl.Action(name="reporting_acceptable", payload={"baseline": baseline_name, "report_path": report_path}, label=cmp.get("acceptable_label", "✅ Acceptable")),
            cl.Action(name="reporting_not_acceptable", payload={"baseline": baseline_name, "report_path": report_path}, label=cmp.get("not_acceptable_label", "❌ Not Acceptable - Report to Validator"))
        ]

        await cl.Message(content=content, actions=actions).send()


async def handle_reporting_step_6(baseline_name: str, agent: ReportingAgent, report_path: str):
    """Handle Step 6: Close ticket."""
    skill = load_reporting_skill()
    close_cfg = skill.get("close_ticket", {})
    await cl.Message(content=close_cfg.get("pre_message", "🔄 **Step 6/6: Closing Ticket...**")).send()

    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(None, agent.run_step_6_close_ticket)
    
    success, result = await future
    ticket_id = result.get("ticket_id")
    
    if success:
        org = config.AZURE_DEVOPS_ORG
        project = config.AZURE_DEVOPS_PROJECT
        ticket_url = f"https://dev.azure.com/{org}/{project}/_workitems/edit/{ticket_id}"
        
        success_tpl = close_cfg.get("success", "✅ Ticket {ticket_id} closed!").strip()
        await cl.Message(content=success_tpl.format(
            ticket_id=ticket_id, ticket_url=ticket_url,
            baseline_name=baseline_name, report_path=report_path,
        )).send()
    else:
        fail_tpl = close_cfg.get("fail", "⚠️ **Step 6: Close Ticket**\n\n{error}").strip()
        await cl.Message(content=fail_tpl.format(
            error=result.get("message", "Could not close ticket"),
            baseline_name=baseline_name, report_path=report_path,
        )).send()


@cl.action_callback("reporting_acceptable")
async def on_reporting_acceptable(action: cl.Action):
    """Handle acceptable button click in reporting flow."""
    baseline_name = action.payload.get("baseline")
    report_path = action.payload.get("report_path", "")
    
    skill = load_reporting_skill()
    cmp = skill.get("compare", {})
    await cl.Message(content=cmp.get("acceptable_ack", "✅ Differences marked as acceptable.")).send()
    
    # Continue to Step 6
    session = session_manager.get_session(baseline_name)
    agent = ReportingAgent(session)
    
    await handle_reporting_step_6(baseline_name, agent, report_path)


@cl.action_callback("reporting_not_acceptable")
async def on_reporting_not_acceptable(action: cl.Action):
    """Handle not acceptable button click in reporting flow."""
    baseline_name = action.payload.get("baseline")
    report_path = action.payload.get("report_path", "")
    
    # Find ticket ID for display
    found, ticket_id, _ = find_reporting_ticket_by_baseline(baseline_name)
    ticket_info = f"**Ticket:** {ticket_id} (Not closed - pending fix)" if found else "**Ticket:** Not found"
    
    skill = load_reporting_skill()
    cmp = skill.get("compare", {})
    not_acceptable_tpl = cmp.get("not_acceptable", "❌ **Reporting Stopped - Issue Found**").strip()
    await cl.Message(content=not_acceptable_tpl.format(
        baseline_name=baseline_name, report_path=report_path,
        ticket_info=ticket_info,
    )).send()

def _extract_step_error(result: dict, error_path: str = None) -> str:
    """Extract error message from a reporting step result dict.

    If ``error_path`` is given (e.g. ``"error_info.error_message"``),
    traverses the nested dict first.  Always falls back to
    ``result["message"]``.
    """
    if error_path:
        node = result
        for part in error_path.split("."):
            if isinstance(node, dict):
                node = node.get(part)
            else:
                break
        if isinstance(node, str) and node:
            return node
    return result.get("message") or ""

# ─────────────────────────────────────────────────────────────────────────────
# Skill-driven handler registration
# ─────────────────────────────────────────────────────────────────────────────
# The orchestrator (services/orchestrator.py) reads
# prompts/WORKFLOW_ORCHESTRATION_SKILL.md and dispatches each user message to
# the handler registered here under the name in the skill's `handler:` field.
# Adding a new operation = add a skill entry + register a handler below.
# Existing handler functions are reused as-is — no behaviour change.
# ─────────────────────────────────────────────────────────────────────────────

register_many({
    "help":      handle_help,
    "list":      handle_list,
    "status":    handle_status,
    "reset":     handle_reset,
    "copy":      handle_copy,
    "load":      handle_load,
    "branch":    handle_branch,
    "run":       handle_run,
    "unload":    handle_unload,
    "compare":   handle_compare,
    "report":    handle_report,
    "finalize":  handle_finalize,
    "validate":  handle_validate,
    "reporting": handle_reporting,
    "chat":      handle_chat,   # natural-language fallback
})

# Eagerly initialise the orchestrator so any skill-file errors surface at
# startup rather than on the first message.
get_orchestrator()