def test_agent_account_fields_and_key_fragments_are_redacted_but_keys_stay():
    from l4.redact import Redactor

    text = '{"chatgptAccountId":"acct-9f","orgName":"Acme Inc","signature": "AbC=="} sk-proj-***abcd'
    out = Redactor({}).redact_text(text)
    assert "acct-9f" not in out and "Acme" not in out and "AbC" not in out and "***abcd" not in out
    assert '"chatgptAccountId":"[REDACTED:agent-field]"' in out


# --- the agent-field shape stops at a line end (own-test-repair, L4-IMP-091, SCN-IMP-479) ---------------------


def test_a_json_field_is_redacted_on_one_line_and_inside_a_json_string():
    from l4.redact import Redactor

    plain = Redactor({}).redact_text('{"signature": "AbCdEf==", "n": 1}')
    nested = Redactor({}).redact_text(r'{"output": "{\"signature\":\"AbCdEf==\",\"n\":1}"}')
    assert "AbCdEf" not in plain and '"signature": "[REDACTED:agent-field]"' in plain
    assert "AbCdEf" not in nested and r"\"signature\":\"[REDACTED:agent-field]\"" in nested


def test_an_agent_field_opener_with_no_closer_on_its_line_leaves_the_following_lines_alone():
    from l4.redact import Redactor

    for end in ("\n", "\r\n", "\r"):
        text = f'    value = f()  # see the "signature": "{end}    assert value == expected{end}    # a closing "{end}'
        assert Redactor({}).redact_text(text) == text  # nothing hidden, nothing changed
