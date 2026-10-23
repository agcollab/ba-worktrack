"""Sign-in, lockout, CSRF, roles and passwords."""
from app.models import AuditLog, User
from app.security import decode_access_token, hash_password, verify_password
from tests.conftest import PASSWORD, form, login


def test_password_is_hashed(people):
    assert people["asha"].hashed_password != PASSWORD
    assert verify_password(PASSWORD, people["asha"].hashed_password)
    assert not verify_password("wrong", people["asha"].hashed_password)


def test_login_sets_httponly_cookie_and_audits(client, people, db):
    login(client, "asha@test.com")
    assert decode_access_token(client.cookies.get("access_token")) == people["asha"].id
    assert client.get("/").status_code == 200
    assert db.query(AuditLog).filter_by(action="auth.login").count() == 1


def test_email_is_case_insensitive(client, people):
    login(client, "ASHA@test.com")


def test_wrong_password_is_rejected(client, people):
    client.get("/login")
    response = client.post("/login", data={"email": "asha@test.com", "password": "nope",
                                           "csrf_token": client.cookies.get("csrf_token")})
    assert response.status_code == 401
    assert "incorrect" in response.text


def test_account_locks_after_five_failures(client, people, db):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    for _ in range(5):
        client.post("/login", data={"email": "ben@test.com", "password": "bad", "csrf_token": token})
    response = client.post("/login", data={"email": "ben@test.com", "password": PASSWORD, "csrf_token": token})
    assert response.status_code == 401
    assert "locked" in response.text.lower()
    db.expire_all()
    assert db.get(User, people["ben"].id).locked_until is not None


def test_login_is_rate_limited(client, people):
    client.get("/login")
    token = client.cookies.get("csrf_token")
    codes = [client.post("/login", data={"email": "x@test.com", "password": "bad", "csrf_token": token}).status_code
             for _ in range(12)]
    assert 429 in codes


def test_post_without_csrf_token_is_refused(client, people):
    login(client, "asha@test.com")
    response = client.post("/tasks", data={"project_id": people["pay"].id, "title": "No token"})
    assert response.status_code == 403


def test_ba_cannot_open_admin_pages(client, people):
    login(client, "asha@test.com")
    for path in ("/admin/users", "/admin/audit", "/integrations", "/projects/new"):
        assert client.get(path).status_code == 403, path


def test_admin_menu_only_for_admins(client, people):
    login(client, "asha@test.com")
    assert "/admin/users" not in client.get("/").text
    client.post("/logout", data=form(client))
    login(client, "admin@test.com")
    assert "/admin/users" in client.get("/").text


def test_logout_clears_the_cookie(client, people):
    login(client, "asha@test.com")
    client.post("/logout", data=form(client))
    assert client.get("/", follow_redirects=False).status_code == 303


def test_admin_creates_user_who_must_change_password(client, people, db):
    login(client, "admin@test.com")
    response = client.post("/admin/users", data=form(client, email="new@test.com", full_name="New Person",
                                                    password="Temp-passw0rd", roles=["BA"]),
                           follow_redirects=False)
    assert response.status_code == 303
    new = db.query(User).filter_by(email="new@test.com").one()
    assert new.must_change_password and new.role_names == ["BA"]
    assert db.query(AuditLog).filter_by(action="user.create").count() == 1

    client.post("/logout", data=form(client))
    client.get("/login")
    response = client.post("/login", data={"email": "new@test.com", "password": "Temp-passw0rd",
                                           "csrf_token": client.cookies.get("csrf_token")}, follow_redirects=False)
    assert response.headers["location"].startswith("/profile")


def test_admin_resets_password_and_unlocks(client, people, db):
    people["ben"].failed_logins = 3
    db.commit()
    login(client, "admin@test.com")
    client.post(f"/admin/users/{people['ben'].id}/reset-password", data=form(client, new_password="Brand-new-pass1"))
    db.expire_all()
    ben = db.get(User, people["ben"].id)
    assert verify_password("Brand-new-pass1", ben.hashed_password)
    assert ben.failed_logins == 0 and ben.must_change_password


def test_admin_cannot_deactivate_self(client, people):
    login(client, "admin@test.com")
    response = client.post(f"/admin/users/{people['admin'].id}/active", data=form(client), follow_redirects=False)
    assert response.status_code == 303  # back with an error message
    assert "flash" in response.cookies or "flash" in response.headers.get("set-cookie", "")


def test_deactivated_user_cannot_sign_in(client, people, db):
    people["ben"].is_active = False
    db.commit()
    client.get("/login")
    response = client.post("/login", data={"email": "ben@test.com", "password": PASSWORD,
                                           "csrf_token": client.cookies.get("csrf_token")})
    assert response.status_code == 401
    assert "deactivated" in response.text


def test_change_own_password(client, people, db):
    login(client, "asha@test.com")
    client.post("/profile/password", data=form(client, current_password=PASSWORD, new_password="Another-pass9",
                                              confirm_password="Another-pass9"))
    db.expire_all()
    assert verify_password("Another-pass9", db.get(User, people["asha"].id).hashed_password)


def test_weak_password_is_rejected(client, people, db):
    login(client, "asha@test.com")
    before = people["asha"].hashed_password
    client.post("/profile/password", data=form(client, current_password=PASSWORD, new_password="short",
                                              confirm_password="short"))
    db.expire_all()
    assert db.get(User, people["asha"].id).hashed_password == before


def test_open_redirect_is_blocked(client, people):
    client.get("/login")
    response = client.post("/login", data={"email": "asha@test.com", "password": PASSWORD, "next": "//evil.com",
                                           "csrf_token": client.cookies.get("csrf_token")}, follow_redirects=False)
    assert response.headers["location"] == "/"


def test_hash_password_uses_salt():
    assert hash_password("same-password-1") != hash_password("same-password-1")
