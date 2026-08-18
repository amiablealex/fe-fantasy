def test_health_reports_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_index_renders_for_anonymous_visitor(client):
    response = client.get("/")
    assert response.status_code == 200
