from server import json_response


def with_error_boundary(handler, callback):
    try:
        return callback()
    except Exception as exc:
        return json_response(handler, 500, {"ok": False, "error": str(exc)})
