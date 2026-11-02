from app.config import Settings

SAFE_PRODUCTION = dict(environment="production", secret_key="x" * 48, cookie_secure=True, staff_mfa_required=True,
                       public_base_url="https://app.kathachepta.com", smtp_host="email-smtp.ap-south-1.amazonaws.com",
                       smtp_port=587, smtp_username="ses-user", smtp_password="ses-password")


def test_a_complete_production_configuration_starts_cleanly():
    settings = Settings(**SAFE_PRODUCTION)
    assert settings.validate_for_runtime() == [] and settings.runtime_warnings() == []


def test_production_refuses_plain_http_and_development_secrets():
    problems = Settings(**{**SAFE_PRODUCTION, "public_base_url": "http://203.0.113.7",
                           "secret_key": "dev-only-secret-change-me"}).validate_for_runtime()
    assert any("KC_PUBLIC_BASE_URL" in problem for problem in problems)
    assert any("KC_SECRET_KEY" in problem for problem in problems)


def test_missing_mail_settings_warn_instead_of_blocking_the_first_deploy():
    settings = Settings(**{**SAFE_PRODUCTION, "email_enabled": True, "smtp_host": "mailpit", "smtp_username": ""})
    assert settings.validate_for_runtime() == []
    assert "sign-in codes fail" in settings.runtime_warnings()[0]
    # With email off (the pilot), nothing is sent, so no mail settings are needed.
    assert Settings(**{**SAFE_PRODUCTION, "email_enabled": False, "smtp_host": "mailpit",
                       "smtp_username": ""}).runtime_warnings() == []
    assert Settings(environment="development", smtp_host="mailpit").runtime_warnings() == []
