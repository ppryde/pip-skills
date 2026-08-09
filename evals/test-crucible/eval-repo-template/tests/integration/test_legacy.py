"""Legacy endpoint tests.

Kept for the v1 API, which is still deployed to two customers.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("darwin") or sys.platform.startswith("linux"),
    reason="requires the legacy fixture server",
)

def test_legacy_v1_endpoint_0(api_client):
    api_client.put("legacy-0", 0)
    assert api_client.get("legacy-0") == 0

def test_legacy_v1_endpoint_1(api_client):
    api_client.put("legacy-1", 1)
    assert api_client.get("legacy-1") == 1

def test_legacy_v1_endpoint_2(api_client):
    api_client.put("legacy-2", 2)
    assert api_client.get("legacy-2") == 2

def test_legacy_v1_endpoint_3(api_client):
    api_client.put("legacy-3", 3)
    assert api_client.get("legacy-3") == 3

def test_legacy_v1_endpoint_4(api_client):
    api_client.put("legacy-4", 4)
    assert api_client.get("legacy-4") == 4

def test_legacy_v1_endpoint_5(api_client):
    api_client.put("legacy-5", 5)
    assert api_client.get("legacy-5") == 5

def test_legacy_v1_endpoint_6(api_client):
    api_client.put("legacy-6", 6)
    assert api_client.get("legacy-6") == 6

def test_legacy_v1_endpoint_7(api_client):
    api_client.put("legacy-7", 7)
    assert api_client.get("legacy-7") == 7

def test_legacy_v1_endpoint_8(api_client):
    api_client.put("legacy-8", 8)
    assert api_client.get("legacy-8") == 8

def test_legacy_v1_endpoint_9(api_client):
    api_client.put("legacy-9", 9)
    assert api_client.get("legacy-9") == 9

def test_legacy_v1_endpoint_10(api_client):
    api_client.put("legacy-10", 10)
    assert api_client.get("legacy-10") == 10

def test_legacy_v1_endpoint_11(api_client):
    api_client.put("legacy-11", 11)
    assert api_client.get("legacy-11") == 11
