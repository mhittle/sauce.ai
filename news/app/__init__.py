"""News aggregator Flask app.

Flask is imported lazily inside `create_app()` so that submodules like
`app.ranking` and `app.classifier.rules` can be imported (and unit-tested)
without Flask installed.
"""


def create_app():
    from flask import Flask, g

    from .config import Config
    from .db import close_conn
    from .auth import load_user
    from .security import init_csrf
    from .ratelimit import SlidingWindowLimiter

    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(Config)
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    app.teardown_appcontext(close_conn)

    init_csrf(app)
    app.extensions["auth_limiter"] = SlidingWindowLimiter(
        app.config["AUTH_RATELIMIT_MAX"],
        app.config["AUTH_RATELIMIT_WINDOW_SECONDS"],
    )

    @app.before_request
    def _load_user():
        load_user()

    @app.context_processor
    def _inject():
        return {"current_user": getattr(g, "user", None)}

    from .routes.feed import bp as feed_bp
    from .routes.algo import bp as algo_bp
    from .routes.firehose import bp as firehose_bp
    from .routes.admin import bp as admin_bp
    from .routes.auth_routes import bp as auth_bp
    from .routes.account import bp as account_bp
    from .routes.signals import bp as signals_bp
    from .routes.reader import bp as reader_bp
    from .routes.sources import bp as sources_bp
    from .routes.story import bp as story_bp
    from .routes.saves import bp as saves_bp
    from .routes.trending import bp as trending_bp
    from .routes.search import bp as search_bp

    app.register_blueprint(feed_bp)
    app.register_blueprint(algo_bp, url_prefix="/algo")
    app.register_blueprint(firehose_bp, url_prefix="/firehose")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(account_bp, url_prefix="/account")
    app.register_blueprint(signals_bp, url_prefix="/signal")
    app.register_blueprint(reader_bp)
    app.register_blueprint(sources_bp, url_prefix="/sources")
    app.register_blueprint(story_bp)
    app.register_blueprint(saves_bp)
    app.register_blueprint(trending_bp)
    app.register_blueprint(search_bp)

    return app
