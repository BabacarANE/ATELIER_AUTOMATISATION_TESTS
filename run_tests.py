import requests
import os
import time
import sqlite3
from datetime import datetime

# ─── CHARGEMENT DU .env (racine du compte) ────────────────
env_path = "/home/babacaranetest/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

# ─── CONFIG ───────────────────────────────────────────────
API_KEY   = os.environ.get("API_FOOTBALL_KEY", "")
BASE_URL  = "https://v3.football.api-sports.io"
HEADERS   = {"x-apisports-key": API_KEY}
LEAGUE_ID = 61       # Ligue 1
SEASON    = 2024
DB_PATH   = os.path.join(os.path.dirname(__file__), "metrics.db")
MAX_HISTORY = 20
# ──────────────────────────────────────────────────────────


# ─── BASE DE DONNÉES SQLite ───────────────────────────────

def init_db():
    """Crée les tables si elles n'existent pas encore."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Table des runs (chaque exécution globale)
    c.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT    NOT NULL,
            success_rate  REAL    NOT NULL,
            avg_duration  REAL    NOT NULL,
            passed        INTEGER NOT NULL,
            total         INTEGER NOT NULL
        )
    """)

    # Table des résultats détaillés (un test = une ligne)
    c.execute("""
        CREATE TABLE IF NOT EXISTS test_results (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id    INTEGER NOT NULL,
            name      TEXT    NOT NULL,
            status    TEXT    NOT NULL,
            duration  REAL    NOT NULL,
            message   TEXT,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        )
    """)

    conn.commit()
    conn.close()


def save_to_db(run_entry):
    """Insère un run et ses résultats dans la base SQLite."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Insérer le run
    c.execute("""
        INSERT INTO runs (timestamp, success_rate, avg_duration, passed, total)
        VALUES (?, ?, ?, ?, ?)
    """, (
        run_entry["timestamp"],
        run_entry["success_rate"],
        run_entry["avg_duration"],
        run_entry["passed"],
        run_entry["total"]
    ))
    run_id = c.lastrowid

    # Insérer chaque résultat de test
    for r in run_entry["results"]:
        c.execute("""
            INSERT INTO test_results (run_id, name, status, duration, message)
            VALUES (?, ?, ?, ?, ?)
        """, (run_id, r["name"], r["status"], r["duration"], r["message"]))

    # Garder seulement les MAX_HISTORY derniers runs
    c.execute("""
        DELETE FROM runs WHERE id NOT IN (
            SELECT id FROM runs ORDER BY id DESC LIMIT ?
        )
    """, (MAX_HISTORY,))

    # Nettoyer les résultats orphelins
    c.execute("""
        DELETE FROM test_results WHERE run_id NOT IN (SELECT id FROM runs)
    """)

    conn.commit()
    conn.close()
    print(f"✅ Données sauvegardées dans SQLite ({DB_PATH})")


def load_from_db():
    """Charge l'historique complet depuis SQLite."""
    if not os.path.exists(DB_PATH):
        return {"last_run": None, "history": []}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT * FROM runs ORDER BY id DESC")
    runs = c.fetchall()

    history = []
    for run in runs:
        c.execute("SELECT * FROM test_results WHERE run_id = ?", (run["id"],))
        results = [
            {
                "name":     r["name"],
                "status":   r["status"],
                "duration": r["duration"],
                "message":  r["message"]
            }
            for r in c.fetchall()
        ]
        history.append({
            "id":           run["id"],
            "timestamp":    run["timestamp"],
            "success_rate": run["success_rate"],
            "avg_duration": run["avg_duration"],
            "passed":       run["passed"],
            "total":        run["total"],
            "results":      results
        })

    conn.close()
    last_run = history[0]["timestamp"] if history else None
    return {"last_run": last_run, "history": history}


# ─── TESTS ────────────────────────────────────────────────

def run_test(name, fn):
    start = time.time()
    try:
        message = fn()
        return {"name": name, "status": "PASS", "duration": round(time.time()-start,3), "message": message or "OK"}
    except AssertionError as e:
        return {"name": name, "status": "FAIL", "duration": round(time.time()-start,3), "message": str(e)}
    except Exception as e:
        return {"name": name, "status": "ERROR","duration": round(time.time()-start,3), "message": str(e)}


def test_api_status():
    r = requests.get(f"{BASE_URL}/status", headers=HEADERS, timeout=5)
    assert r.status_code == 200, f"HTTP {r.status_code} inattendu"
    data = r.json()
    assert "response" in data, "Champ 'response' manquant"
    plan  = data["response"].get("subscription", {}).get("plan", "inconnu")
    quota = data["response"].get("requests", {}).get("limit_day", "?")
    return f"Plan: {plan} | Quota: {quota} req/jour"


def test_ligue1_standings():
    r = requests.get(
        f"{BASE_URL}/standings",
        headers=HEADERS,
        params={"league": LEAGUE_ID, "season": SEASON},
        timeout=5
    )
    assert r.status_code == 200, f"HTTP {r.status_code}"
    data = r.json()
    assert data.get("results", 0) > 0, "Aucun résultat retourné"
    standings = data["response"][0]["league"]["standings"][0]
    assert len(standings) >= 18, f"Seulement {len(standings)} équipes"
    for team in standings:
        assert isinstance(team["points"], int) and team["points"] >= 0, "Points invalides"
        assert isinstance(team["rank"],   int) and team["rank"]   >= 1, "Rang invalide"
    top = standings[0]["team"]["name"]
    return f"Leader: {top} | {len(standings)} équipes validées"


def test_ligue1_fixtures():
    r = requests.get(
        f"{BASE_URL}/fixtures",
        headers=HEADERS,
        params={"league": LEAGUE_ID, "season": SEASON, "last": 5},
        timeout=5
    )
    assert r.status_code == 200, f"HTTP {r.status_code}"
    fixtures = r.json().get("response", [])
    assert len(fixtures) > 0, "Aucun match retourné"
    for fix in fixtures:
        for field in ["fixture", "teams", "goals", "score"]:
            assert field in fix, f"Champ '{field}' manquant"
        for side in ["home", "away"]:
            g = fix["goals"][side]
            if g is not None:
                assert isinstance(g, int) and g >= 0, f"Score invalide: {g}"
    return f"{len(fixtures)} derniers matchs validés ✓"


def test_top_scorers():
    r = requests.get(
        f"{BASE_URL}/players/topscorers",
        headers=HEADERS,
        params={"league": LEAGUE_ID, "season": SEASON},
        timeout=5
    )
    assert r.status_code == 200, f"HTTP {r.status_code}"
    players = r.json().get("response", [])
    assert len(players) > 0, "Aucun buteur retourné"
    for p in players:
        name  = p["player"]["name"]
        goals = p["statistics"][0]["goals"]["total"]
        assert isinstance(name, str) and name, "Nom joueur invalide"
        assert isinstance(goals, int) and goals >= 0, f"Buts invalides: {goals}"
    top   = players[0]["player"]["name"]
    goals = players[0]["statistics"][0]["goals"]["total"]
    return f"Top buteur: {top} ({goals} buts)"


def test_response_time():
    start = time.time()
    r = requests.get(
        f"{BASE_URL}/fixtures",
        headers=HEADERS,
        params={"league": LEAGUE_ID, "season": SEASON, "last": 1},
        timeout=10
    )
    elapsed = round(time.time() - start, 3)
    assert r.status_code == 200, f"HTTP {r.status_code}"
    assert elapsed < 3.0, f"Trop lent: {elapsed}s (max 3s)"
    return f"Temps de réponse: {elapsed}s ✓"


# ─── RUNNER PRINCIPAL ─────────────────────────────────────

def main():
    init_db()

    print(f"\n{'='*50}")
    print(f"  Lancement des tests — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{'='*50}\n")

    tests = [
        ("🔌 Statut API",         test_api_status),
        ("🏆 Classement Ligue 1", test_ligue1_standings),
        ("⚽ Derniers matchs",     test_ligue1_fixtures),
        ("👟 Top buteurs",         test_top_scorers),
        ("⏱️  Temps de réponse",   test_response_time),
    ]

    results = []
    for name, fn in tests:
        result = run_test(name, fn)
        results.append(result)
        icon = "✅" if result["status"] == "PASS" else "❌"
        print(f"{icon} {result['name']}: {result['status']} ({result['duration']}s) — {result['message']}")

    passed       = sum(1 for r in results if r["status"] == "PASS")
    total        = len(results)
    success_rate = round((passed / total) * 100, 1)
    avg_duration = round(sum(r["duration"] for r in results) / total, 3)

    run_entry = {
        "timestamp":    datetime.now().isoformat(),
        "results":      results,
        "success_rate": success_rate,
        "avg_duration": avg_duration,
        "passed":       passed,
        "total":        total
    }

    print(f"\n{'─'*50}")
    print(f"  Résultat : {passed}/{total} tests réussis ({success_rate}%)")
    print(f"  Durée moyenne : {avg_duration}s")
    print(f"{'='*50}\n")

    save_to_db(run_entry)


if __name__ == "__main__":
    main()