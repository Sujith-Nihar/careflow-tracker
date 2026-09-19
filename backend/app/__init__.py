"""Flask application factory."""

from __future__ import annotations

import uuid

from flask import Flask, g, jsonify, request

from .config import settings
from .observability.logging import bind, clear, configure, get_logger

log = get_logger(__name__)


def create_app() -> Flask:
    config = settings()
    configure(config.log_level)

    app = Flask(__name__)

    from .api.auth import AuthError
    from .api.evidence import bp as evidence_bp
    from .api.vogent_functions import bp as functions_bp
    from .api.vogent_webhooks import bp as webhooks_bp

    app.register_blueprint(functions_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(evidence_bp)

    @app.before_request
    def _start_request() -> None:
        clear()
        g.request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        bind(request_id=g.request_id)

    @app.after_request
    def _finish_request(response):
        response.headers["X-Request-Id"] = g.get("request_id", "")
        return response

    @app.errorhandler(AuthError)
    def _auth_error(exc: AuthError):
        # Log the reason, never the presented token.
        log.info("vogent.function.rejected", reason_code=exc.reason, http_status=exc.status)
        return jsonify({"error": exc.reason, "request_id": g.get("request_id")}), exc.status

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        log.info("request.failed", error_type=type(exc).__name__, http_status=500)
        return jsonify({"error": "internal_error", "request_id": g.get("request_id")}), 500

    @app.get("/healthz")
    def _root_health():
        return jsonify({"ok": True, "git_sha": config.git_sha}), 200

    return app
