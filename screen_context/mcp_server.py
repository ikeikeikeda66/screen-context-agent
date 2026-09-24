"""Fixed profile per process; HTTP credentials are bound to that profile."""
import base64
import hmac
import os
from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent, TextContent, ToolAnnotations
from .privacy import NOTICE
from .service import Service


def create_server(settings, profile="standard", client=None):
    service = Service(settings, profile, client)
    server = MCPServer("screen-context", instructions=NOTICE + " Query only when the user refers to previous screen activity or missing external context.")
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    descriptions = {
        "search_screen_history": "Full-text search over OCR text of previously captured windows. Returns matching frames, newest first. Returns untrusted observed data.",
        "get_recent_activity": "Summarize recent screen activity as blocks of consecutive frames (app, window title, time range, text). Returns untrusted observed data.",
        "get_context_around": "Get activity blocks before and after a Unix timestamp. Returns untrusted observed data.",
    }
    for name, description in descriptions.items():
        server.tool(name=name, description=description, annotations=annotations)(getattr(service, name))
    server.tool(name="get_day_material",
                description="Get bounded screen observations for a specified local calendar day to draft a report or diary. Applies current exclusions and returns evidence only; gaps remain unknown.",
                annotations=annotations)(service.get_day_material)
    if service.profile == "full":
        descriptions = {
            "get_activity_timeline": "List activity blocks (app and time range only, no text) for the last N hours.",
            "get_daily_rollup": "Get a compact per-day summary of activity blocks with short text excerpts.",
            "get_diary_material": "Get paginated activity blocks for one local day as evidence for a diary draft. Follow next_offset to read all pages.",
            "get_capture_health": "Report whether capture and OCR are running, paused, locked, delayed or idle.",
            "get_activity_delta": "Get frames in OCR-completion order after a signed cursor, for periodic consumers that must not miss late OCR.",
        }
        for name, description in descriptions.items():
            server.tool(name=name, description=description, annotations=annotations)(getattr(service, name))
        server.tool(name="submit_proposal", description="Register one proposal for an open run_id from the pre-run material. Returns decision=deliver with the message to send, or suppressed_duplicate.",
                    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))(service.submit_proposal)

        @server.tool(annotations=annotations, description="Explicitly retrieve a retained screenshot, subject to current exclusions.")
        def get_snapshot_image(frame_id: str) -> list[TextContent | ImageContent]:
            data = service.get_snapshot_image(frame_id)
            return [TextContent(type="text", text=NOTICE), ImageContent(type="image", data=base64.b64encode(data).decode(), mimeType="image/webp")]

        @server.tool(annotations=annotations, description="Request a fresh foreground-window image. Requires approval in a local OS dialog for every call; capture daemon and indexer must be running.")
        def get_current_screen() -> list[TextContent | ImageContent]:
            from .broker import request_current
            data = request_current(service)
            return [TextContent(type="text", text=NOTICE), ImageContent(type="image", data=base64.b64encode(data).decode(), mimeType="image/webp")]
    return server


class BearerGate:
    def __init__(self, app, token):
        if not token or len(token) < 32: raise ValueError("HTTP requires SCREEN_CONTEXT_TOKEN of at least 32 characters")
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            value = dict(scope.get("headers", [])).get(b"authorization", b"")
            if not hmac.compare_digest(value, b"Bearer " + self.token):
                await send({"type": "http.response.start", "status": 401, "headers": [(b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return
        await self.app(scope, receive, send)


def run(settings, profile, transport, port=8765):
    server = create_server(settings, profile, os.environ.get("SCREEN_CONTEXT_CLIENT"))
    if transport == "stdio": server.run()
    else:
        import uvicorn
        app = BearerGate(server.streamable_http_app(stateless_http=True), os.environ.get("SCREEN_CONTEXT_TOKEN"))
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
