"""A Lynxce account is shown by nickname, else a masked phone or email, never an id."""

from octop.infra.auth.lynxce_cloud import display_name


def test_nickname_wins_then_masked_contact() -> None:
    assert display_name({"id": "u1", "displayName": " Alison. "}) == "Alison."
    assert display_name({"id": "u1", "nickname": "小明"}) == "小明"
    assert display_name({"id": "u1", "phone": "+86 138-0013-8000"}) == "861****8000"
    assert display_name({"id": "u1", "phone": "13800138000"}) == "138****8000"
    assert display_name({"id": "u1", "email": "alison@example.com"}) == "al***@example.com"
    assert display_name({"id": "u1", "phone": "12"}) is None
    assert display_name({"id": "u1"}) is None
