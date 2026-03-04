from flask import Flask, render_template, jsonify
import os
import sys

# PythonAnywhere cherche une variable "app" dans flask_app.py
app = Flask(__name__)

# Import des fonctions SQLite depuis run_tests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_tests import load_from_db, init_db

# Initialise la DB au démarrage
init_db()

# ─── ROUTES ───────────────────────────────────────────────

@app.get("/")
def dashboard():
    """Page principale — Dashboard visuel Ligue 1."""
    metrics = load_from_db()
    return render_template("dashboard.html", metrics=metrics)

@app.get("/api/metrics")
def api_metrics():
    """Endpoint JSON — retourne tout l'historique des tests."""
    return jsonify(load_from_db())

@app.get("/run-tests")
def run_tests_now():
    """Lance les tests directement (sans subprocess)."""
    from run_tests import main
    try:
        main()
        return jsonify({"status": "Tests terminés !"})
    except Exception as e:
        return jsonify({"status": f"Erreur: {str(e)}"})

# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Utile en local uniquement
    app.run(host="0.0.0.0", port=5000, debug=True)
