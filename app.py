import os
import requests
from flask import Flask, render_template
from identity.flask import Auth
import app_config

app = Flask(__name__)
app.config.from_object(app_config)

auth = Auth(
        app,
        authority=app.config["AUTHORITY"],
        client_id=app.config["CLIENT_ID"],
        client_credential=app.config["CLIENT_SECRET"],
        redirect_uri=app.config["REDIRECT_URI"]
)

@app.route("/")
@auth.login_required
def index(*, context):
    return render_template(
            'index.html',
            user=context['user'],
            title="Flask Web App Sample",
            )

