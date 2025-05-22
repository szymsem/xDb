from fastapi.testclient import TestClient
from main import app

def test_root():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "Welcome to the Crypto API"}

def test_register_and_login():
    client = TestClient(app)
    # Rejestracja
    resp = client.post("/api/auth/register", params={
        "username": "testuser",
        "password": "testpass",
        "email": "testuser@example.com"
    })
    assert resp.status_code == 200

    # Logowanie
    resp = client.post("/api/auth/login", data={
        "username": "testuser",
        "password": "testpass"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data

def test_create_portfolio_and_get_details():
    client = TestClient(app)
    # Rejestracja i logowanie
    client.post("/api/auth/register", params={
        "username": "portfoliotest",
        "password": "portfoliotest",
        "email": "portfoliotest@example.com"
    })
    resp = client.post("/api/auth/login", data={
        "username": "portfoliotest",
        "password": "portfoliotest"
    })
    token = resp.json()["access_token"]

    # Tworzenie portfela
    resp = client.post(
        "/api/portfolios/",
        params={"name": "Test Portfolio"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    portfolio_id = resp.json()["id"]

    # Pobieranie szczegółów portfela
    resp = client.get(
        f"/api/portfolios/{portfolio_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["portfolio"]["name"] == "Test Portfolio"

def test_send_test_email(monkeypatch):
    # Mockowanie wysyłki e-maila
    async def fake_send_email_notification(*args, **kwargs):
        return None

    from services import notification_service
    monkeypatch.setattr(notification_service, "send_email_notification", fake_send_email_notification)

    client = TestClient(app)
    client.post("/api/auth/register", params={
        "username": "mailtest",
        "password": "mailtest",
        "email": "mailtest@example.com"
    })
    resp = client.post("/api/auth/login", data={
        "username": "mailtest",
        "password": "mailtest"
    })
    token = resp.json()["access_token"]

    resp = client.post(
        "/api/notifications/test?subject=Test&message=Hello",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "test email sent"