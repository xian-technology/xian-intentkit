from app.local.schema import _simplify_skill_schema


def test_simplify_skill_schema_preserves_auth_mode():
    schema = {
        "title": "X",
        "description": "Twitter skill",
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean"},
            "states": {"type": "object"},
            "auth_mode": {"type": "string", "enum": ["linked_account", "self_key"]},
            "consumer_key": {"type": "string"},
        },
    }

    simplified = _simplify_skill_schema(schema)

    assert simplified["properties"] == {
        "enabled": {"type": "boolean"},
        "states": {"type": "object"},
        "auth_mode": {"type": "string", "enum": ["linked_account", "self_key"]},
    }
