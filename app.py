from flask import Flask, render_template

import app_config
import passkeys
from auth import auth

app = Flask(__name__)
app.config.from_object(app_config)
auth.init_app(app)
app.register_blueprint(passkeys.bp)


@app.route("/")
@auth.login_required
def index(*, context):
    return render_template(
        "index.html",
        user=context["user"],
        title="Flask Web App Sample",
    )
