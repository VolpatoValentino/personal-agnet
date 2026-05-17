import os
import logfire

_CONFIGURED = False

def scrubbing_callback(m: logfire.ScrubMatch):
    if m.path == ('attributes', 'mcp.session.id'):
        return m.value

def setup_logfire(service_name: str, *, instrument_fastapi_app=None, instrument_httpx: bool = False) -> None:
    """Configure Logfire once per process.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    token = os.getenv("LOGFIRE_TOKEN")
    send_to_logfire = "if-token-present" if token else False

    logfire.configure(
        service_name=service_name,
        send_to_logfire=send_to_logfire,
        console=logfire.ConsoleOptions(min_log_level="info"),
        scrubbing=logfire.ScrubbingOptions(),
        distributed_tracing=True
    )

    logfire.instrument_pydantic_ai()

    if instrument_fastapi_app is not None:
        logfire.instrument_fastapi(instrument_fastapi_app, capture_headers=False)

    if instrument_httpx:
        logfire.instrument_httpx(capture_all=False)

    _CONFIGURED = True
    logfire.info("logfire initialised", service=service_name, cloud_export=bool(token))
