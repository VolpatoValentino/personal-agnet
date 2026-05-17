from dotenv import load_dotenv
load_dotenv()

import argparse
import json
import os
from dataclasses import dataclass
from typing import Literal

import httpx
import logfire
import questionary
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from core.observability import setup_logfire

setup_logfire("personal-agent-cli", instrument_httpx=True)

console = Console()

CUSTOM_REPLY_LABEL = "Type a custom reply…"


@dataclass
class _TurnOutcome:
    status: Literal["done", "question", "error", "cancelled"]
    session_id: str | None
    question: dict | None = None  # {call_id, question, options}
    error: str | None = None


def _iter_sse_events(response: httpx.Response):
    """Yield decoded JSON payloads from a `text/event-stream` response."""
    for raw_line in response.iter_lines():
        if not raw_line:
            continue
        if not raw_line.startswith("data:"):
            continue
        payload = raw_line[len("data:"):].strip()
        if not payload:
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def _run_streamed_turn(
    client: httpx.Client,
    url: str,
    payload: dict,
    provider_name: str,
) -> _TurnOutcome:
    """Stream a single turn. Returns an outcome describing how it ended."""
    reply_chunks: list[str] = []
    session_id: str | None = payload.get("session_id")
    console.print("\n[bold magenta]Agent:[/bold magenta]")
    with client.stream("POST", url, json=payload) as response:
        if response.status_code >= 400:
            response.read()
            console.print(
                f"[bold red]API Error: {response.status_code}[/bold red]\n{response.text}"
            )
            return _TurnOutcome("error", session_id, error=f"HTTP {response.status_code}")

        with Live(Markdown(""), console=console, refresh_per_second=20, vertical_overflow="visible") as live:
            for event in _iter_sse_events(response):
                etype = event.get("type")
                if etype == "session":
                    session_id = event.get("session_id", session_id)
                elif etype == "intent":
                    intents = ", ".join(event.get("intents", [])) or "?"
                    reason = event.get("reason", "")
                    live.console.print(f"[dim]· intent: {intents} — {reason}[/dim]")
                elif etype == "text":
                    reply_chunks.append(event.get("text", ""))
                    live.update(Markdown("".join(reply_chunks)))
                elif etype == "question":
                    return _TurnOutcome(
                        status="question",
                        session_id=session_id,
                        question={
                            "call_id": event["call_id"],
                            "question": event.get("question", ""),
                            "options": event.get("options", []),
                        },
                    )
                elif etype == "awaiting_answer":
                    # Some streams emit this after `question`; harmless to ignore.
                    continue
                elif etype == "error":
                    msg = event.get("message", "unknown error")
                    live.update(Markdown("".join(reply_chunks)))
                    console.print(f"\n[bold red]Stream error: {msg}[/bold red]")
                    return _TurnOutcome("error", session_id, error=msg)
                elif etype == "done":
                    break
    return _TurnOutcome("done", session_id)


def _ask_user_via_picker(question: dict) -> tuple[Literal["answer", "custom", "cancel"], str | None]:
    """Show the agent's question as an arrow-key picker.

    Returns one of:
      - ('answer', selected_option_str)  — user picked one of the offered options
      - ('custom', typed_reply)          — user chose to type their own reply
      - ('cancel', None)                 — user hit Ctrl-C / Esc
    """
    console.print(f"\n[bold yellow]?[/bold yellow] {question['question']}")
    options = list(question.get("options") or [])
    choices = [*options, CUSTOM_REPLY_LABEL]
    selection = questionary.select(
        "Pick one:",
        choices=choices,
        use_shortcuts=True,
    ).ask()
    if selection is None:
        return "cancel", None
    if selection == CUSTOM_REPLY_LABEL:
        free = Prompt.ask("[bold cyan]Your reply[/bold cyan]")
        return "custom", free
    return "answer", selection


def _run_blocking_turn(
    client: httpx.Client,
    url: str,
    payload: dict,
    provider_name: str,
) -> _TurnOutcome:
    """Old-style request/response turn for `--no-stream` (no ask_user support)."""
    with console.status(
        f"[bold yellow]Agent ({provider_name}) is thinking and using tools...",
        spinner="dots",
    ):
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    reply = data.get("reply", "No reply received.")
    console.print("\n[bold magenta]Agent:[/bold magenta]")
    console.print(Markdown(reply))
    return _TurnOutcome("done", data.get("session_id", payload.get("session_id")))


def _handle_user_message(
    client: httpx.Client,
    url: str,
    user_input: str,
    session_id: str | None,
    *,
    use_stream: bool,
    provider_name: str,
) -> str | None:
    """Drive one user turn through to completion. Returns the session_id to use next."""
    payload: dict = {"message": user_input}
    if session_id is not None:
        payload["session_id"] = session_id

    while True:
        if use_stream:
            outcome = _run_streamed_turn(client, url, payload, provider_name)
        else:
            outcome = _run_blocking_turn(client, url, payload, provider_name)

        if outcome.session_id:
            session_id = outcome.session_id

        if outcome.status == "done":
            return session_id
        if outcome.status == "error":
            return session_id
        if outcome.status == "question":
            kind, value = _ask_user_via_picker(outcome.question or {})
            if kind == "cancel":
                console.print("[bold yellow]Cancelled — agent's question left unanswered.[/bold yellow]")
                return session_id
            payload = {"session_id": session_id}
            if kind == "answer":
                payload["answer"] = {
                    "call_id": outcome.question["call_id"],
                    "value": value,
                }
            else:  # custom — let the server treat the typed reply as the answer
                payload["answer"] = {
                    "call_id": outcome.question["call_id"],
                    "value": value or "",
                }
            # loop back to stream the resumed run


def main():
    parser = argparse.ArgumentParser(description="Personal Agent CLI")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use the local Llama model instead of Google AI Studio",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming; wait for the full reply before rendering.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("AGENT_API_HOST", "localhost"),
        help="Agent API host (default: localhost, or $AGENT_API_HOST).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("AGENT_API_PORT", "8000")),
        help="Agent API port (default: 8000, or $AGENT_API_PORT).",
    )
    args = parser.parse_args()

    base = "agent" if args.local else "google_agent"
    provider_name = "Local Llama.cpp" if args.local else "Google AI Studio"
    endpoint = "chat" if args.no_stream else "chat/stream"
    AGENT_URL = f"http://{args.host}:{args.port}/{base}/{endpoint}"

    auth_token = os.getenv("AGENT_AUTH_TOKEN", "").strip()
    auth_headers: dict[str, str] = (
        {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
    )

    console.print(Panel.fit(
        f"[bold green]Personal Agent CLI[/bold green]\n"
        f"Powered by {provider_name} & Pydantic AI"
        + ("" if args.no_stream else " (streaming)")
        + "\n\n"
        "Type [bold red]'exit'[/bold red] or [bold red]'quit'[/bold red] to stop, "
        "[bold red]'/reset'[/bold red] to start a new conversation.",
        border_style="green",
    ))

    session_id: str | None = None

    with httpx.Client(timeout=None, headers=auth_headers) as client:
        while True:
            try:
                user_input = Prompt.ask("\n[bold cyan]You[/bold cyan]")

                if user_input.strip().lower() in ["exit", "quit"]:
                    console.print("[bold yellow]Goodbye![/bold yellow]")
                    break
                if user_input.strip().lower() == "/reset":
                    session_id = None
                    console.print("[bold yellow]Conversation reset.[/bold yellow]")
                    continue
                if not user_input.strip():
                    continue

                with logfire.span(
                    "cli.user_turn",
                    provider=provider_name,
                    message_length=len(user_input),
                    session_id=session_id,
                    stream=not args.no_stream,
                ):
                    try:
                        session_id = _handle_user_message(
                            client,
                            AGENT_URL,
                            user_input,
                            session_id,
                            use_stream=not args.no_stream,
                            provider_name=provider_name,
                        )
                    except httpx.ConnectError:
                        logfire.error("cli.connect_error", url=AGENT_URL)
                        console.print("[bold red]Error: Could not connect to the Agent API.[/bold red]")
                        console.print("Make sure you have started it with [bold]make run-agent[/bold] or [bold]make run-all[/bold]")
                        continue
                    except httpx.HTTPStatusError as e:
                        logfire.error("cli.http_error", status_code=e.response.status_code, url=AGENT_URL)
                        console.print(f"[bold red]API Error: {e.response.status_code}[/bold red]")
                        continue
                    except Exception as e:
                        logfire.exception("cli.unexpected_error", error=str(e))
                        console.print(f"[bold red]Unexpected Error: {e}[/bold red]")
                        continue

            except (KeyboardInterrupt, EOFError):
                console.print("\n[bold yellow]Goodbye![/bold yellow]")
                break


if __name__ == "__main__":
    main()
