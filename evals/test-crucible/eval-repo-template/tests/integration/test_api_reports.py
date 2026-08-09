"""Integration tests for the reports endpoints."""

def test_reports_roundtrip_0(api_client):
    api_client.put("reports-0", 0)
    assert api_client.get("reports-0") == 0
    assert api_client.keys() == ["reports-0"]

def test_reports_roundtrip_1(api_client):
    api_client.put("reports-1", 1)
    assert api_client.get("reports-1") == 1
    assert api_client.keys() == ["reports-1"]

def test_reports_roundtrip_2(api_client):
    api_client.put("reports-2", 2)
    assert api_client.get("reports-2") == 2
    assert api_client.keys() == ["reports-2"]

def test_reports_roundtrip_3(api_client):
    api_client.put("reports-3", 3)
    assert api_client.get("reports-3") == 3
    assert api_client.keys() == ["reports-3"]

def test_reports_roundtrip_4(api_client):
    api_client.put("reports-4", 4)
    assert api_client.get("reports-4") == 4
    assert api_client.keys() == ["reports-4"]

def test_reports_roundtrip_5(api_client):
    api_client.put("reports-5", 5)
    assert api_client.get("reports-5") == 5
    assert api_client.keys() == ["reports-5"]

def test_reports_roundtrip_6(api_client):
    api_client.put("reports-6", 6)
    assert api_client.get("reports-6") == 6
    assert api_client.keys() == ["reports-6"]

def test_reports_roundtrip_7(api_client):
    api_client.put("reports-7", 7)
    assert api_client.get("reports-7") == 7
    assert api_client.keys() == ["reports-7"]

def test_reports_roundtrip_8(api_client):
    api_client.put("reports-8", 8)
    assert api_client.get("reports-8") == 8
    assert api_client.keys() == ["reports-8"]

def test_reports_roundtrip_9(api_client):
    api_client.put("reports-9", 9)
    assert api_client.get("reports-9") == 9
    assert api_client.keys() == ["reports-9"]

def test_reports_roundtrip_10(api_client):
    api_client.put("reports-10", 10)
    assert api_client.get("reports-10") == 10
    assert api_client.keys() == ["reports-10"]

def test_reports_roundtrip_11(api_client):
    api_client.put("reports-11", 11)
    assert api_client.get("reports-11") == 11
    assert api_client.keys() == ["reports-11"]

def test_reports_roundtrip_12(api_client):
    api_client.put("reports-12", 12)
    assert api_client.get("reports-12") == 12
    assert api_client.keys() == ["reports-12"]
