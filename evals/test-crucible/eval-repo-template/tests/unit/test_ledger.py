"""Ledger behaviour."""

from ledgerlite.ledger import Ledger

def test_post_and_balance_case_0():
    ledger = Ledger()
    assert ledger.post("assets", 0) == 0
    assert ledger.balance("assets") == 0
    assert ledger.entry_count() == 1

def test_post_and_balance_case_1():
    ledger = Ledger()
    assert ledger.post("assets", 3) == 3
    assert ledger.balance("assets") == 3
    assert ledger.entry_count() == 1

def test_post_and_balance_case_2():
    ledger = Ledger()
    assert ledger.post("assets", 6) == 6
    assert ledger.balance("assets") == 6
    assert ledger.entry_count() == 1

def test_post_and_balance_case_3():
    ledger = Ledger()
    assert ledger.post("assets", 9) == 9
    assert ledger.balance("assets") == 9
    assert ledger.entry_count() == 1

def test_post_and_balance_case_4():
    ledger = Ledger()
    assert ledger.post("assets", 12) == 12
    assert ledger.balance("assets") == 12
    assert ledger.entry_count() == 1

def test_post_and_balance_case_5():
    ledger = Ledger()
    assert ledger.post("assets", 15) == 15
    assert ledger.balance("assets") == 15
    assert ledger.entry_count() == 1

def test_post_and_balance_case_6():
    ledger = Ledger()
    assert ledger.post("assets", 18) == 18
    assert ledger.balance("assets") == 18
    assert ledger.entry_count() == 1

def test_post_and_balance_case_7():
    ledger = Ledger()
    assert ledger.post("assets", 21) == 21
    assert ledger.balance("assets") == 21
    assert ledger.entry_count() == 1

def test_post_and_balance_case_8():
    ledger = Ledger()
    assert ledger.post("assets", 24) == 24
    assert ledger.balance("assets") == 24
    assert ledger.entry_count() == 1

def test_post_and_balance_case_9():
    ledger = Ledger()
    assert ledger.post("assets", 27) == 27
    assert ledger.balance("assets") == 27
    assert ledger.entry_count() == 1

def test_post_and_balance_case_10():
    ledger = Ledger()
    assert ledger.post("assets", 30) == 30
    assert ledger.balance("assets") == 30
    assert ledger.entry_count() == 1

def test_post_and_balance_case_11():
    ledger = Ledger()
    assert ledger.post("assets", 33) == 33
    assert ledger.balance("assets") == 33
    assert ledger.entry_count() == 1

def test_post_and_balance_case_12():
    ledger = Ledger()
    assert ledger.post("assets", 36) == 36
    assert ledger.balance("assets") == 36
    assert ledger.entry_count() == 1

def test_post_and_balance_case_13():
    ledger = Ledger()
    assert ledger.post("assets", 39) == 39
    assert ledger.balance("assets") == 39
    assert ledger.entry_count() == 1
