import re

import pytest

from medikeep_mcp.catalog import Catalog
from medikeep_mcp.config import Settings
from medikeep_mcp.server import OVERVIEW_SECTIONS, MediKeepMCP
from medikeep_mcp.skills_loader import load_skills


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.bundled()


def test_every_operation_is_cataloged(catalog):
    expected = sum(
        1
        for item in catalog.spec["paths"].values()
        for method in item
        if method in ("get", "post", "put", "patch", "delete")
    )
    assert len(catalog.operations) == expected > 500


def test_names_are_unique_and_mcp_safe(catalog):
    for name in catalog.operations:
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name), name


def test_find_by_name_signature_and_concrete_path(catalog):
    assert catalog.find("read_medications").path == "/api/v1/medications/"
    assert catalog.find("GET /api/v1/medications/").name == "read_medications"
    assert catalog.find("GET /medications").name == "read_medications"
    assert catalog.find("DELETE /api/v1/medications/42").name == "delete_medication"


def test_internal_params_hidden(catalog):
    op = catalog.find("read_patient_medications")
    assert "required_permission" not in [p.name for p in op.params]


def test_multipart_and_raw_body_detection(catalog):
    assert catalog.find("upload_entity_file").file_fields == ["file"]
    assert catalog.find("import_imaging_files").raw_body


def test_full_mode_tool_schemas(catalog):
    settings = Settings()
    settings.tool_mode = "full"
    app = MediKeepMCP(settings, catalog)
    tools = app.list_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names))
    assert len(tools) == len(catalog.operations) + len(app.helper_tools())
    delete = next(t for t in tools if t.name == "delete_medication")
    assert "confirm" in delete.input_schema["properties"]
    assert delete.annotations.destructive_hint


def test_overview_sections_exist(catalog):
    for path, _ in OVERVIEW_SECTIONS.values():
        concrete = path.replace("{pid}", "1")
        assert catalog.find(f"GET {concrete}"), path


def test_skills_reference_real_operations(catalog):
    skills = load_skills()
    assert len(skills) >= 8
    helper = {
        "medikeep_guide",
        "medikeep_whoami",
        "medikeep_list_operations",
        "medikeep_describe_operation",
        "medikeep_call",
        "medikeep_patient_overview",
        "medikeep_search_records",
        "medikeep_lab_trend",
    }
    # Field / parameter names also appear in backticks; collect them to skip.
    fields = {"save_to", "raw_file", "path_params", "patient_id", "accessible_patients"}
    for schema in catalog.spec["components"]["schemas"].values():
        fields.update((schema.get("properties") or {}).keys())
    for op in catalog.operations.values():
        fields.update(p.name for p in op.params)
    missing = []
    for skill in skills.values():
        assert skill.description, skill.name
        for token in re.findall(r"`([a-z][a-z0-9_-]+)`", skill.body):
            if "_" not in token or token in helper or token in fields:
                continue
            if token not in catalog.operations:
                missing.append(f"{skill.name}: {token}")
    assert not missing, missing
