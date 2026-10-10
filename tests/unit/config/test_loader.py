from pathlib import Path

import pytest

from l4.config.loader import ConfigSchemaError, load_config
from l4.exitcodes import ExitCode, L4Exit


def write_config(repo: Path, text: str) -> Path:
    path = repo / ".l4" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def messages(err: ConfigSchemaError) -> list[str]:
    return [str(issue) for issue in err.issues]


def test_missing_file_means_defaults(tmp_path: Path):
    cfg = load_config(tmp_path)
    assert cfg.tdd.mode == "strict" and cfg.version == 1


def test_empty_file_means_defaults(tmp_path: Path):
    write_config(tmp_path, "")
    assert load_config(tmp_path).forge.base_branch == "main"


def test_valid_file_overrides_defaults(tmp_path: Path):
    write_config(tmp_path, "version: 1\ntdd: {mode: guided}\nprofiles:\n  a: {adapter: codex}\n")
    cfg = load_config(tmp_path)
    assert cfg.tdd.mode == "guided" and cfg.profiles["a"].adapter == "codex"


def test_typo_reports_path_and_suggestion(tmp_path: Path):
    write_config(tmp_path, "version: 1\nverifer: {independence: none}\n")
    with pytest.raises(ConfigSchemaError) as err:
        load_config(tmp_path)
    assert messages(err.value) == ["unknown key 'verifer' at $ (did you mean 'verifier'?)"]
    assert err.value.code is ExitCode.USAGE_ERROR
    assert isinstance(err.value, L4Exit)


def test_nested_typo_in_a_dict_of_models_has_a_full_path(tmp_path: Path):
    write_config(tmp_path, "profiles:\n  judge-sol:\n    adaptr: codex\n    model: x\n")
    with pytest.raises(ConfigSchemaError) as err:
        load_config(tmp_path)
    assert messages(err.value) == ["unknown key 'adaptr' at $.profiles.judge-sol (did you mean 'adapter'?)"]


def test_unknown_key_without_close_match_has_no_suggestion(tmp_path: Path):
    write_config(tmp_path, "zzzzzz: 1\n")
    with pytest.raises(ConfigSchemaError) as err:
        load_config(tmp_path)
    assert messages(err.value) == ["unknown key 'zzzzzz' at $"]


def test_type_error_and_union_paths_are_readable(tmp_path: Path):
    write_config(tmp_path, "tdd: {mode: sloppy}\nspec: {frameworks: [openspec, svn]}\nci: {time_budget: soon}\n")
    with pytest.raises(ConfigSchemaError) as err:
        load_config(tmp_path)
    text = "\n".join(messages(err.value))
    assert "at $.tdd.mode" in text
    assert "at $.spec.frameworks[1]" in text
    assert "at $.ci.time_budget" in text
    assert "literal[" not in text and "function-" not in text


SECRET = "sk-or-v1-" + "a1B2c3D4" * 4


@pytest.mark.parametrize(
    "body",
    [
        f"profiles:\n  judge-sol:\n    api_key: {SECRET}\n",  # unknown key holding a secret
        f"harness: {{commit: {SECRET}}}\n",  # secret where a hex sha belongs
        f"gates: {{timeout: {SECRET}}}\n",  # secret where a duration belongs
        f"ci: {{time_budget: {SECRET}}}\n",  # secret where 'auto' or a duration belongs (custom validator)
        f"forge: {{branch_prefix: {SECRET}!}}\n",  # secret where a branch prefix belongs (custom validator)
        f"tdd: {{mode: {SECRET}}}\n",  # secret where a literal belongs
        f"ci: {{max_parallel_units: {SECRET}}}\n",  # secret where an int belongs
        f"{SECRET}: 1\n",  # secret as a key
    ],
)
def test_literal_secret_never_in_message(tmp_path: Path, body: str):
    write_config(tmp_path, body)
    with pytest.raises(ConfigSchemaError) as err:
        load_config(tmp_path)
    rendered = str(err.value) + repr(err.value.issues)
    assert err.value.issues
    assert SECRET not in rendered


def test_invalid_yaml_reports_position_not_content(tmp_path: Path):
    write_config(tmp_path, f"tdd: [unclosed\nsecret: {SECRET}\n  bad: : :\n")
    with pytest.raises(ConfigSchemaError) as err:
        load_config(tmp_path)
    rendered = str(err.value)
    assert SECRET not in rendered and "line" in rendered


def test_python_tags_in_yaml_are_refused(tmp_path: Path):
    write_config(tmp_path, "tdd: !!python/object/apply:os.system ['true']\n")
    with pytest.raises(ConfigSchemaError):
        load_config(tmp_path)


def test_top_level_must_be_a_mapping(tmp_path: Path):
    write_config(tmp_path, "- a\n- b\n")
    with pytest.raises(ConfigSchemaError) as err:
        load_config(tmp_path)
    assert "mapping" in str(err.value)


def test_explicit_config_path_must_exist(tmp_path: Path):
    with pytest.raises(ConfigSchemaError) as err:
        load_config(tmp_path, config_path=tmp_path / "nope.yaml")
    assert err.value.code is ExitCode.USAGE_ERROR
    assert "not found" in str(err.value)


def test_explicit_config_path_is_used(tmp_path: Path):
    other = tmp_path / "other.yaml"
    other.write_text("tdd: {mode: off}\n", encoding="utf-8")
    assert load_config(tmp_path, config_path=other).tdd.mode == "off"


def test_off_stays_a_string_not_a_yaml_1_1_boolean(tmp_path: Path):
    write_config(tmp_path, "tdd: {mode: off}\nsdd: {scope_check: off}\nlocks: {lease: 5m}\n")
    cfg = load_config(tmp_path)
    assert cfg.tdd.mode == "off" and cfg.sdd.scope_check == "off"


def test_a_custom_validator_that_echoes_its_input_is_not_printed():
    from pydantic import BaseModel, ValidationError, field_validator

    from l4.config.loader import _issues

    class Leaky(BaseModel):
        x: str

        @field_validator("x")
        @classmethod
        def check(cls, value: str) -> str:
            raise ValueError(f"bad {value!r}")

    with pytest.raises(ValidationError) as err:
        Leaky(x=SECRET)
    assert SECRET not in repr(_issues(err.value))
