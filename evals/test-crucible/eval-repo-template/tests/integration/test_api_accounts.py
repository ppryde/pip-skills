"""Integration tests for the accounts endpoints."""

def test_accounts_roundtrip_0(api_client):
    api_client.put("accounts-0", 0)
    assert api_client.get("accounts-0") == 0
    assert api_client.keys() == ["accounts-0"]

def test_accounts_roundtrip_1(api_client):
    api_client.put("accounts-1", 1)
    assert api_client.get("accounts-1") == 1
    assert api_client.keys() == ["accounts-1"]

def test_accounts_roundtrip_2(api_client):
    api_client.put("accounts-2", 2)
    assert api_client.get("accounts-2") == 2
    assert api_client.keys() == ["accounts-2"]

def test_accounts_roundtrip_3(api_client):
    api_client.put("accounts-3", 3)
    assert api_client.get("accounts-3") == 3
    assert api_client.keys() == ["accounts-3"]

def test_accounts_roundtrip_4(api_client):
    api_client.put("accounts-4", 4)
    assert api_client.get("accounts-4") == 4
    assert api_client.keys() == ["accounts-4"]

def test_accounts_roundtrip_5(api_client):
    api_client.put("accounts-5", 5)
    assert api_client.get("accounts-5") == 5
    assert api_client.keys() == ["accounts-5"]

def test_accounts_roundtrip_6(api_client):
    api_client.put("accounts-6", 6)
    assert api_client.get("accounts-6") == 6
    assert api_client.keys() == ["accounts-6"]

def test_accounts_roundtrip_7(api_client):
    api_client.put("accounts-7", 7)
    assert api_client.get("accounts-7") == 7
    assert api_client.keys() == ["accounts-7"]

def test_accounts_roundtrip_8(api_client):
    api_client.put("accounts-8", 8)
    assert api_client.get("accounts-8") == 8
    assert api_client.keys() == ["accounts-8"]

def test_accounts_roundtrip_9(api_client):
    api_client.put("accounts-9", 9)
    assert api_client.get("accounts-9") == 9
    assert api_client.keys() == ["accounts-9"]

def test_accounts_roundtrip_10(api_client):
    api_client.put("accounts-10", 10)
    assert api_client.get("accounts-10") == 10
    assert api_client.keys() == ["accounts-10"]

def test_accounts_roundtrip_11(api_client):
    api_client.put("accounts-11", 11)
    assert api_client.get("accounts-11") == 11
    assert api_client.keys() == ["accounts-11"]

def test_accounts_roundtrip_12(api_client):
    api_client.put("accounts-12", 12)
    assert api_client.get("accounts-12") == 12
    assert api_client.keys() == ["accounts-12"]
