import importlib.util
import sys

from opiha.common import REPO


def test_export_preserves_tags_and_replaces_nested_credentials(tmp_path):
    spec = importlib.util.spec_from_file_location("deployed_yaml_export", REPO / "scripts/export-deployed-yaml.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    source = tmp_path / "source"
    source.mkdir()
    (source / "configuration.yaml").write_text(
        "automation: !include automations.yaml\n"
        "wifi:\n  password: !secret wifi_password\n"
        "api:\n  encryption:\n    key: test-credential\n"
        "triggers:\n  - webhook_id: private-webhook\n"
        "env_vars:\n  - name: CUSTOM_SETTING\n    value: private-env-value\n"
    )
    (source / "secrets.yaml").write_text("password: never-export")
    destination = tmp_path / "public"
    required = module.export(source, destination)
    text = (destination / "configuration.yaml").read_text()
    assert "test-credential" not in text and "private-webhook" not in text and "private-env-value" not in text
    assert "!include" in text and "automations.yaml" in text and "wifi_password" in text
    assert required == {"configuration_api_encryption_key", "configuration_triggers_0_webhook_id",
                        "configuration_env_vars_0_value"}
    assert not (destination / "secrets.yaml").exists()
