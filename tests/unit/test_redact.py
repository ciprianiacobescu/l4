

def test_agent_account_fields_and_key_fragments_are_redacted_but_keys_stay():
    from l4.redact import Redactor

    text = '{"chatgptAccountId":"acct-9f","orgName":"Acme Inc","signature": "AbC=="} sk-proj-***abcd'
    out = Redactor({}).redact_text(text)
    assert "acct-9f" not in out and "Acme" not in out and "AbC" not in out and "***abcd" not in out
    assert '"chatgptAccountId":"[REDACTED:agent-field]"' in out
