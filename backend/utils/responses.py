"""
Shared response-envelope helpers.

Every API response follows:
    success: {"success": true,  "message": "...", "data": {...}}
    error:   {"success": false, "message": "...", "data": null}

Some of the preserved frontend JS (assessment/enrollment/ambassador
calls) was written against an earlier `{"error": "..."}` shape and
reads `body.error` directly on failure (see apiFetch/ambApiFetch in
frontend/index.html). Rather than rewrite that frontend error-handling
path, `err()` includes BOTH `message` and `error` (same text) on
failure responses, so it satisfies the spec's envelope AND stays
backward compatible with the existing frontend.
"""
from flask import jsonify


def ok(data=None, message: str = "", status: int = 200):
    return jsonify({"success": True, "message": message, "data": data if data is not None else {}}), status


def err(message: str, status: int = 400, data=None):
    return jsonify({"success": False, "message": message, "data": data, "error": message}), status
