"""パスキー管理ページと JSON API。

操作対象のユーザーは必ずサインイン済みのトークンから決める。リクエストからは受け取らない
(他人のパスキーを操作されるのを防ぐため)。
"""

from flask import Blueprint, jsonify, render_template, request

import graph_passkeys
from auth import auth

bp = Blueprint("passkeys", __name__)


def _user_id(context: dict) -> str:
    user = context["user"]
    return user.get("oid") or user["sub"]


@bp.errorhandler(graph_passkeys.GraphError)
def _handle_graph_error(error: graph_passkeys.GraphError):
    return jsonify(error=error.message), error.status_code


@bp.route("/passkeys")
@auth.login_required
def page(*, context):
    return render_template("passkeys.html", user=context["user"], title="パスキーの管理")


@bp.route("/api/passkeys")
@auth.login_required
def list_passkeys(*, context):
    graph_response = graph_passkeys.list_passkeys(_user_id(context))
    return jsonify(passkeys=graph_passkeys.summarize_passkeys(graph_response))


@bp.route("/api/passkeys/creation-options")
@auth.login_required
def creation_options(*, context):
    return jsonify(graph_passkeys.get_creation_options(_user_id(context)))


@bp.route("/api/passkeys", methods=["POST"])
@auth.login_required
def create_passkey(*, context):
    payload = request.get_json(silent=True) or {}
    if "publicKeyCredential" not in payload:
        return jsonify(error="publicKeyCredential がありません"), 400
    created = graph_passkeys.create_passkey(_user_id(context), payload)
    return jsonify(created), 201


@bp.route("/api/passkeys/<passkey_id>", methods=["DELETE"])
@auth.login_required
def delete_passkey(passkey_id, *, context):
    graph_passkeys.delete_passkey(_user_id(context), passkey_id)
    return "", 204
