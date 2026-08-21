import pytest

import routers.document as document_module


@pytest.fixture(autouse=True)
def tmp_upload_dir(monkeypatch, tmp_path):
    """Redirect all file uploads in this test module into a throwaway tmp folder."""
    monkeypatch.setattr(document_module, "UPLOAD_DIR", str(tmp_path))
    return tmp_path


def test_upload_file_success(app_client, auth_headers, sample_pdf_bytes):
    """Uploading a valid PDF as an authenticated user returns 201 with the document's metadata."""
    headers = auth_headers(email="uploader@example.com", password="Passw0rd")

    resp = app_client.post(
        "/document/upload-file",
        headers=headers,
        files={"file": ("invoice.pdf", sample_pdf_bytes, "application/pdf")},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["original_name"] == "invoice.pdf"
    assert body["file_type"] == "pdf"
    assert body["message"] == "File uploaded successfully"


def test_upload_file_requires_auth(app_client, sample_pdf_bytes):
    """POST /document/upload-file rejects requests without a bearer token."""
    resp = app_client.post(
        "/document/upload-file",
        files={"file": ("invoice.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 401


def test_upload_file_rejects_disallowed_content_type(app_client, auth_headers):
    """Uploading a non-PDF content type is rejected with a 400."""
    headers = auth_headers(email="uploader2@example.com", password="Passw0rd")

    resp = app_client.post(
        "/document/upload-file",
        headers=headers,
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_file_rejects_oversized_file(app_client, auth_headers):
    """Uploading a PDF larger than the 10MB limit is rejected with a 400."""
    headers = auth_headers(email="uploader3@example.com", password="Passw0rd")
    oversized = b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024 + 1)

    resp = app_client.post(
        "/document/upload-file",
        headers=headers,
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )
    assert resp.status_code == 400


def test_my_files_returns_only_current_users_documents(app_client, auth_headers, sample_pdf_bytes):
    """GET /document/my-files returns only the authenticated user's own uploaded documents."""
    headers_a = auth_headers(email="usera@example.com", password="Passw0rd")
    headers_b = auth_headers(email="userb@example.com", password="Passw0rd")

    app_client.post(
        "/document/upload-file", headers=headers_a,
        files={"file": ("a.pdf", sample_pdf_bytes, "application/pdf")},
    )
    app_client.post(
        "/document/upload-file", headers=headers_b,
        files={"file": ("b.pdf", sample_pdf_bytes, "application/pdf")},
    )

    resp_a = app_client.get("/document/my-files", headers=headers_a)
    assert resp_a.status_code == 200
    body_a = resp_a.json()
    assert body_a["total"] == 1
    assert body_a["files"][0]["original_name"] == "a.pdf"


def test_my_files_empty_for_new_user(app_client, auth_headers):
    """GET /document/my-files returns an empty list for a user who hasn't uploaded anything."""
    headers = auth_headers(email="nofiles@example.com", password="Passw0rd")

    resp = app_client.get("/document/my-files", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "files": []}


def test_edit_document_replaces_file_and_marks_update(app_client, auth_headers, sample_pdf_bytes):
    """Editing an owned document replaces its file, name, and marks its process status as UPDATE."""
    headers = auth_headers(email="editor@example.com", password="Passw0rd")
    upload = app_client.post(
        "/document/upload-file", headers=headers,
        files={"file": ("original.pdf", sample_pdf_bytes, "application/pdf")},
    )
    document_id = upload.json()["id"]

    resp = app_client.put(
        f"/document/edit/{document_id}", headers=headers,
        files={"file": ("updated.pdf", sample_pdf_bytes, "application/pdf")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["original_name"] == "updated.pdf"
    assert body["process_status"] == "UPDATE"


def test_edit_document_not_found_returns_404(app_client, auth_headers, sample_pdf_bytes):
    """Editing a document id that doesn't exist returns a 404."""
    headers = auth_headers(email="editor2@example.com", password="Passw0rd")

    resp = app_client.put(
        "/document/edit/999999", headers=headers,
        files={"file": ("x.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 404


def test_edit_document_owned_by_another_user_returns_404(app_client, auth_headers, sample_pdf_bytes):
    """A user cannot edit a document uploaded by a different user — treated the same as not-found."""
    headers_a = auth_headers(email="owner_a@example.com", password="Passw0rd")
    headers_b = auth_headers(email="owner_b@example.com", password="Passw0rd")

    upload = app_client.post(
        "/document/upload-file", headers=headers_a,
        files={"file": ("mine.pdf", sample_pdf_bytes, "application/pdf")},
    )
    document_id = upload.json()["id"]

    resp = app_client.put(
        f"/document/edit/{document_id}", headers=headers_b,
        files={"file": ("hijack.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 404


def test_edit_document_rejects_disallowed_content_type(app_client, auth_headers, sample_pdf_bytes):
    """Editing a document with a replacement file of a disallowed content type is rejected with a 400."""
    headers = auth_headers(email="editor3@example.com", password="Passw0rd")
    upload = app_client.post(
        "/document/upload-file", headers=headers,
        files={"file": ("original.pdf", sample_pdf_bytes, "application/pdf")},
    )
    document_id = upload.json()["id"]

    resp = app_client.put(
        f"/document/edit/{document_id}", headers=headers,
        files={"file": ("bad.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400
