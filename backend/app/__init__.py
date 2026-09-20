"""Flask application factory."""

from __future__ import annotations

import uuid

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from .config import settings
from .observability.logging import bind, clear, configure, get_logger

log = get_logger(__name__)


def create_app() -> Flask:
    config = settings()
    configure(config.log_level)

    app = Flask(__name__)

    from .api.errors import RequestError
    from .api.evidence import bp as evidence_bp
    from .api.vogent_functions import bp as functions_bp
    from .api.vogent_webhooks import bp as webhooks_bp
    from .persistence.repositories import CrossOrganizationAccess

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

    @app.errorhandler(RequestError)
    def _request_error(exc: RequestError):
        # Log the reason, never the presented token or the body that failed to parse.
        log.info("vogent.function.rejected", reason_code=exc.reason, http_status=exc.status)
        return jsonify({"error": exc.reason, "request_id": g.get("request_id")}), exc.status

    @app.errorhandler(CrossOrganizationAccess)
    def _cross_organization(exc: CrossOrganizationAccess):
        # Refusing another practice's dial is a correct answer, not a server fault.
        log.info("request.rejected", reason_code="organization_mismatch", http_status=403)
        return jsonify({"error": "organization_mismatch", "request_id": g.get("request_id")}), 403

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        # Flask's own 404s and 405s are answers, not failures; the catch-all below
        # would otherwise turn every unknown route into a 500.
        status = exc.code or 500
        log.info("request.rejected", reason_code=exc.name, http_status=status)
        return jsonify({"error": exc.name, "request_id": g.get("request_id")}), status

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        log.info("request.failed", error_type=type(exc).__name__, http_status=500)
        return jsonify({"error": "internal_error", "request_id": g.get("request_id")}), 500

    @app.get("/healthz")
    def _root_health():
        return jsonify({"ok": True, "git_sha": config.git_sha}), 200

    return app
