import httpx
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.panel import Panel

console = Console()
AGENT_URL = "http://localhost:8000/agent/chat"

def main():
    console.print(Panel.fit(
        "[bold green]Personal Agent CLI[/bold green]\n"
        "Powered by Llama.cpp & Pydantic AI\n\n"
        "Type [bold red]'exit'[/bold red] or [bold red]'quit'[/bold red] to stop.",
        border_style="green"
    ))

    with httpx.Client(timeout=120.0) as client:
        while True:
            try:
                # Get user input
                user_input = Prompt.ask("\n[bold cyan]You[/bold cyan]")
                
                if user_input.strip().lower() in ["exit", "quit"]:
                    console.print("[bold yellow]Goodbye![/bold yellow]")
                    break
                if not user_input.strip():
                    continue

                # Show thinking indicator
                with console.status("[bold yellow]Agent is thinking and using tools...", spinner="dots"):
                    try:
                        response = client.post(
                            AGENT_URL, 
                            json={"message": user_input}
                        )
                        response.raise_for_status()
                        reply = response.json().get("reply", "No reply received.")
                    except httpx.ConnectError:
                        console.print("[bold red]Error: Could not connect to the Agent API.[/bold red]")
                        console.print("Make sure you have started it with [bold]make run-agent[/bold] or [bold]make run-all[/bold]")
                        continue
                    except httpx.HTTPStatusError as e:
                        console.print(f"[bold red]API Error: {e.response.status_code}[/bold red]")
                        continue
                    except Exception as e:
                        console.print(f"[bold red]Unexpected Error: {e}[/bold red]")
                        continue

                # Print response formatted as Markdown
                console.print("\n[bold magenta]Agent:[/bold magenta]")
                console.print(Markdown(reply))

            except (KeyboardInterrupt, EOFError):
                console.print("\n[bold yellow]Goodbye![/bold yellow]")
                break

if __name__ == "__main__":
    main()
