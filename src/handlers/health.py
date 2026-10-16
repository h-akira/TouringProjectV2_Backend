"""GET /health: liveness check without an API key."""
from handlers.common import response


def handler(event, context):
    return response(200, {"status": "ok"})
