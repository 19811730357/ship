"""Credentials stay in the user-authorized CSV, not source or displayed settings."""
import pytest

from src.billing_agent.integrations import OSSAdapter


def settings(path):
    return {"OSS_CREDENTIALS_FILE": str(path), "OSS_ENDPOINT": "https://oss-cn-shanghai.aliyuncs.com",
            "OSS_BUCKET": "ocr-phy"}


def test_oss_can_load_an_explicit_credentials_csv(tmp_path):
    path = tmp_path / "AccessKey.csv"
    path.write_text("AccessKey ID,AccessKey Secret\ntest-id,test-secret\n", encoding="utf-8-sig")
    adapter = OSSAdapter(environ=settings(path))
    assert adapter.is_configured()
    assert adapter.access_key_id == "test-id"
    assert adapter.access_key_secret == "test-secret"
    assert adapter.credentials_source == "csv"


def test_explicit_environment_pair_takes_priority_without_opening_csv(tmp_path):
    adapter = OSSAdapter(environ={**settings(tmp_path / "missing.csv"),
        "OSS_ACCESS_KEY_ID": "env-id", "OSS_ACCESS_KEY_SECRET": "env-secret"})
    assert adapter.is_configured()
    assert adapter.access_key_id == "env-id"
    assert adapter.credentials_source == "environment"


def test_partial_environment_pair_is_not_mixed_with_another_accounts_csv(tmp_path):
    path = tmp_path / "AccessKey.csv"
    path.write_text("AccessKey ID,AccessKey Secret\ncsv-id,csv-secret\n", encoding="utf-8")
    adapter = OSSAdapter(environ={**settings(path), "OSS_ACCESS_KEY_ID": "env-id"})
    assert not adapter.is_configured()
    assert "同时" in adapter.configuration_error


def test_bad_credentials_file_reports_configuration_without_echoing_values(tmp_path):
    path = tmp_path / "AccessKey.csv"
    path.write_text("wrong,schema\nprivate-value,private-secret\n", encoding="utf-8")
    adapter = OSSAdapter(environ=settings(path))
    assert not adapter.is_configured()
    assert "private" not in adapter.configuration_error


def test_oss_upload_denial_preserves_safe_status_and_does_not_expose_key(tmp_path, monkeypatch):
    path = tmp_path / "invoice.png"
    path.write_bytes(b"test")
    class Denied(Exception):
        status = 403
        code = "AccessDenied"
        details = {"Message": "You have no right to access this object because of bucket acl."}
    class Bucket:
        def put_object(self, *args, **kwargs):
            raise Denied("private-key-must-not-be-echoed")
    adapter = OSSAdapter(environ={"OSS_ACCESS_KEY_ID": "id", "OSS_ACCESS_KEY_SECRET": "secret",
        "OSS_ENDPOINT": "https://objects.example", "OSS_BUCKET": "test"})
    monkeypatch.setattr(adapter, "_get_bucket", lambda: Bucket())
    with pytest.raises(RuntimeError) as caught:
        adapter.upload_file(str(path), "billing-ocr/test/invoice.png")
    assert caught.value.metadata["storage_status"] == 403
    assert caught.value.metadata["storage_code"] == "AccessDenied"
    assert caught.value.metadata["object_created"] is False
    assert "private-key" not in str(caught.value)
    assert "403" in str(caught.value)
