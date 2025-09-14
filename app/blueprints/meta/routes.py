from flask import Blueprint, jsonify

meta_bp = Blueprint("meta", __name__, url_prefix="")

@meta_bp.get("/health")
def health():
    return jsonify({"status": "ok"}), 200
