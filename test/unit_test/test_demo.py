import pytest

import routers.demo as demo_module


@pytest.fixture(autouse=True)
def tmp_demo_dir(monkeypatch, tmp_path):
    """Point the demo router at a throwaway folder instead of the real faiss_store/demo."""
    monkeypatch.setattr(demo_module, "DEMO_PERSIST_DIR", str(tmp_path))
    return tmp_path


def make_fake_dataset(base_dir, name, with_index=True):
    folder = base_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    if with_index:
        (folder / "faiss.index").write_bytes(b"fake-index-bytes")
    return folder


def test_list_datasets_requires_auth(app_client):
    """GET /demo/datasets rejects requests without a bearer token."""
    resp = app_client.get("/demo/datasets")
    assert resp.status_code == 401


def test_list_datasets_returns_only_folders_with_index(app_client, auth_headers, tmp_demo_dir):
    """GET /demo/datasets lists only subfolders that actually contain a faiss.index file."""
    headers = auth_headers(email="demolister@example.com", password="Passw0rd")
    make_fake_dataset(tmp_demo_dir, "kirana_store")
    make_fake_dataset(tmp_demo_dir, "medical_store")
    make_fake_dataset(tmp_demo_dir, "not_ready_yet", with_index=False)

    resp = app_client.get("/demo/datasets", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {"datasets": ["kirana_store", "medical_store"]}


def test_list_datasets_empty_when_no_demo_dir(app_client, auth_headers, tmp_demo_dir):
    """GET /demo/datasets returns an empty list (not an error) when no dataset folders exist yet."""
    headers = auth_headers(email="demoempty@example.com", password="Passw0rd")
    # tmp_demo_dir exists but is empty — should still return an empty list, not error.
    resp = app_client.get("/demo/datasets", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"datasets": []}


def test_status_defaults_to_disabled(app_client, auth_headers):
    """A freshly signed-up user starts with demo mode disabled and no dataset selected."""
    headers = auth_headers(email="demostatus@example.com", password="Passw0rd")

    resp = app_client.get("/demo/status", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {"demo_mode_enabled": False, "demo_dataset": None}


def test_enable_requires_auth(app_client):
    """POST /demo/enable rejects requests without a bearer token."""
    resp = app_client.post("/demo/enable", json={"dataset": "kirana_store"})
    assert resp.status_code == 401


def test_enable_with_valid_dataset_updates_status(app_client, auth_headers, tmp_demo_dir):
    """Enabling a valid dataset turns demo mode on and is reflected by a subsequent status check."""
    headers = auth_headers(email="demoenable@example.com", password="Passw0rd")
    make_fake_dataset(tmp_demo_dir, "kirana_store")

    resp = app_client.post("/demo/enable", json={"dataset": "kirana_store"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["demo_mode_enabled"] is True
    assert resp.json()["demo_dataset"] == "kirana_store"

    status_resp = app_client.get("/demo/status", headers=headers)
    assert status_resp.json() == {"demo_mode_enabled": True, "demo_dataset": "kirana_store"}


def test_enable_with_invalid_dataset_rejected(app_client, auth_headers, tmp_demo_dir):
    """Enabling a dataset name that doesn't exist on disk is rejected with a 400."""
    headers = auth_headers(email="demobad@example.com", password="Passw0rd")
    make_fake_dataset(tmp_demo_dir, "kirana_store")

    resp = app_client.post("/demo/enable", json={"dataset": "not_a_real_dataset"}, headers=headers)
    assert resp.status_code == 400


def test_disable_clears_state(app_client, auth_headers, tmp_demo_dir):
    """Disabling demo mode clears both the enabled flag and the selected dataset."""
    headers = auth_headers(email="demodisable@example.com", password="Passw0rd")
    make_fake_dataset(tmp_demo_dir, "kirana_store")
    app_client.post("/demo/enable", json={"dataset": "kirana_store"}, headers=headers)

    resp = app_client.post("/demo/disable", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "message": "Demo mode disabled",
        "demo_mode_enabled": False,
        "demo_dataset": None,
    }


def test_enabling_demo_mode_is_isolated_per_user(app_client, auth_headers, tmp_demo_dir):
    """Enabling demo mode for one user has no effect on another user's demo status."""
    headers_a = auth_headers(email="isolateda@example.com", password="Passw0rd")
    headers_b = auth_headers(email="isolatedb@example.com", password="Passw0rd")
    make_fake_dataset(tmp_demo_dir, "kirana_store")

    app_client.post("/demo/enable", json={"dataset": "kirana_store"}, headers=headers_a)

    status_a = app_client.get("/demo/status", headers=headers_a).json()
    status_b = app_client.get("/demo/status", headers=headers_b).json()

    assert status_a == {"demo_mode_enabled": True, "demo_dataset": "kirana_store"}
    assert status_b == {"demo_mode_enabled": False, "demo_dataset": None}
