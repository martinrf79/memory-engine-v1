import os

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.firestore_store import projects_collection, sessions_collection, users_collection
from app.main import app

client = TestClient(app)


def _clear_auth():
    for collection in [projects_collection, sessions_collection, users_collection]:
        collection.clear()



def test_register_login_logout_and_auth_me_flow():
    _clear_auth()

    unauthorized = client.get("/panel/projects")
    assert unauthorized.status_code == 401

    registered = client.post(
        "/auth/register",
        json={"user_id": "martin", "password": "clave-segura-123", "project": "memoria-guia"},
    )
    assert registered.status_code == 200
    assert registered.json()["authenticated"] is True
    assert "memory_engine_session" in registered.headers.get("set-cookie", "")

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    assert me.json()["user_id"] == "martin"

    projects = client.get("/panel/projects")
    assert projects.status_code == 200
    assert projects.json()["projects"][0]["project"] == "memoria-guia"

    logout = client.post("/auth/logout")
    assert logout.status_code == 200
    assert logout.json()["authenticated"] is False

    after_logout = client.get("/panel/projects")
    assert after_logout.status_code == 401



def test_invalid_login_and_expired_session_block_private_routes():
    _clear_auth()
    client.post(
        "/auth/register",
        json={"user_id": "martin", "password": "clave-segura-123", "project": "memoria-guia"},
    )
    client.post("/auth/logout")

    bad_login = client.post("/auth/login", json={"user_id": "martin", "password": "incorrecta-123"})
    assert bad_login.status_code == 401
    assert bad_login.json()["detail"] == "invalid_credentials"

    good_login = client.post("/auth/login", json={"user_id": "martin", "password": "clave-segura-123"})
    assert good_login.status_code == 200

    sessions = list(sessions_collection.stream())
    assert sessions
    for item in sessions:
        sessions_collection.document(item.id).update({"expires_at": "2000-01-01T00:00:00Z"})

    expired = client.get("/panel/projects")
    assert expired.status_code == 401



def test_project_access_isolation_for_session_user():
    _clear_auth()
    client.post(
        "/auth/register",
        json={"user_id": "martin", "password": "clave-segura-123", "project": "memoria-guia"},
    )
    client.post("/panel/projects", json={"project": "coc"})

    allowed = client.post("/panel/chat", json={"project": "memoria-guia", "book_id": "general", "message": "¿Cuál es mi color favorito?"})
    assert allowed.status_code == 200

    forbidden = client.post("/panel/chat", json={"project": "otro-proyecto", "book_id": "general", "message": "hola"})
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "project_forbidden"



def test_ui_and_auth_responses_set_safe_headers():
    _clear_auth()
    ui = client.get("/ui/")
    assert ui.status_code == 200
    assert ui.headers.get("cache-control") == "no-store, max-age=0"
    assert ui.headers.get("x-frame-options") == "DENY"

    registered = client.post(
        "/auth/register",
        json={"user_id": "martin", "password": "clave-segura-123", "project": "memoria-guia"},
    )
    assert registered.headers.get("cache-control") == "no-store, max-age=0"
    cookie = registered.headers.get("set-cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
