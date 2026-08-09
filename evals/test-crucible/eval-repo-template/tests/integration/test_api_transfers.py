"""Integration tests for the transfers endpoints."""

def test_transfers_roundtrip_0(api_client):
    api_client.put("transfers-0", 0)
    assert api_client.get("transfers-0") == 0
    assert api_client.keys() == ["transfers-0"]

def test_transfers_roundtrip_1(api_client):
    api_client.put("transfers-1", 1)
    assert api_client.get("transfers-1") == 1
    assert api_client.keys() == ["transfers-1"]

def test_transfers_roundtrip_2(api_client):
    api_client.put("transfers-2", 2)
    assert api_client.get("transfers-2") == 2
    assert api_client.keys() == ["transfers-2"]

def test_transfers_roundtrip_3(api_client):
    api_client.put("transfers-3", 3)
    assert api_client.get("transfers-3") == 3
    assert api_client.keys() == ["transfers-3"]

def test_transfers_roundtrip_4(api_client):
    api_client.put("transfers-4", 4)
    assert api_client.get("transfers-4") == 4
    assert api_client.keys() == ["transfers-4"]

def test_transfers_roundtrip_5(api_client):
    api_client.put("transfers-5", 5)
    assert api_client.get("transfers-5") == 5
    assert api_client.keys() == ["transfers-5"]

def test_transfers_roundtrip_6(api_client):
    api_client.put("transfers-6", 6)
    assert api_client.get("transfers-6") == 6
    assert api_client.keys() == ["transfers-6"]

def test_transfers_roundtrip_7(api_client):
    api_client.put("transfers-7", 7)
    assert api_client.get("transfers-7") == 7
    assert api_client.keys() == ["transfers-7"]

def test_transfers_roundtrip_8(api_client):
    api_client.put("transfers-8", 8)
    assert api_client.get("transfers-8") == 8
    assert api_client.keys() == ["transfers-8"]

def test_transfers_roundtrip_9(api_client):
    api_client.put("transfers-9", 9)
    assert api_client.get("transfers-9") == 9
    assert api_client.keys() == ["transfers-9"]

def test_transfers_roundtrip_10(api_client):
    api_client.put("transfers-10", 10)
    assert api_client.get("transfers-10") == 10
    assert api_client.keys() == ["transfers-10"]

def test_transfers_roundtrip_11(api_client):
    api_client.put("transfers-11", 11)
    assert api_client.get("transfers-11") == 11
    assert api_client.keys() == ["transfers-11"]

def test_transfers_roundtrip_12(api_client):
    api_client.put("transfers-12", 12)
    assert api_client.get("transfers-12") == 12
    assert api_client.keys() == ["transfers-12"]
