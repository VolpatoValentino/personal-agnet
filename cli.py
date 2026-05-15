from dotenv import load_dotenv
load_dotenv()

import argparse
import json

import httpx
import logfire
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from api.app.observability import setup_logfire

setup_logfire("personal-agent-cli", instrument_httpx=True)

console = Console()


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
) -> tuple[str | None, str | None]:
    """Stream a single turn, rendering text deltas live. Returns (reply, session_id)."""
    reply_chunks: list[str] = []
    session_id: str | None = payload.get("session_id")
    console.print("\n[bold magenta]Agent:[/bold magenta]")
    with client.stream("POST", url, json=payload) as response:
        if response.status_code >= 400:
            response.read()
            console.print(
                f"[bold red]API Error: {response.status_code}[/bold red]\n{response.text}"
            )
            return None, session_id
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
                elif etype == "error":
                    live.update(Markdown("".join(reply_chunks)))
                    console.print(f"\n[bold red]Stream error: {event.get('message')}[/bold red]")
                    return None, session_id
                elif etype == "done":
                    break
    return "".join(reply_chunks), session_id


def _run_blocking_turn(
    client: httpx.Client,
    url: str,
    payload: dict,
    provider_name: str,
) -> tuple[str | None, str | None]:
    """Old-style request/response turn for `--no-stream`."""
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
    return reply, data.get("session_id", payload.get("session_id"))


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
    args = parser.parse_args()

    base = "agent" if args.local else "google_agent"
    provider_name = "Local Llama.cpp" if args.local else "Google AI Studio"
    endpoint = "chat" if args.no_stream else "chat/stream"
    AGENT_URL = f"http://localhost:8000/{base}/{endpoint}"

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

    with httpx.Client(timeout=None) as client:
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

                payload: dict = {"message": user_input}
                if session_id is not None:
                    payload["session_id"] = session_id

                with logfire.span(
                    "cli.user_turn",
                    provider=provider_name,
                    message_length=len(user_input),
                    session_id=session_id,
                    stream=not args.no_stream,
                ):
                    try:
                        if args.no_stream:
                            _, new_sid = _run_blocking_turn(client, AGENT_URL, payload, provider_name)
                        else:
                            _, new_sid = _run_streamed_turn(client, AGENT_URL, payload, provider_name)
                        if new_sid:
                            session_id = new_sid
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
