"""The app starts, static files are served and the health check reports the database."""


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_home_redirects_to_login_when_signed_out(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_static_files_are_served(client):
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/vendor/htmx.min.js").status_code == 200


def test_api_docs_page_exists(client):
    assert client.get("/docs").status_code == 200


def test_security_headers(client):
    response = client.get("/login")
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
