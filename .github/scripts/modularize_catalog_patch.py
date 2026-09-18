from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXTRACTOR = ROOT / "toolchain/codex_wire_audit/extractors/responses_server_response.py"


def remove_section(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + text[end + 1 :]


def main() -> None:
    text = EXTRACTOR.read_text(encoding="utf-8")

    constants = (
        '\nCATALOG_VARIANT_IDENTITY_AWARE = "identity_aware"\n'
        'CATALOG_VARIANT_ETAG_ONLY = "etag_only"\n'
        'CATALOG_VARIANT_UNKNOWN = "unknown"\n'
    )
    if constants not in text:
        raise SystemExit("catalog variant constants did not match")
    text = text.replace(constants, "", 1)

    text = remove_section(text, "def _catalog_variant(", "\ndef _brace_body")
    text = remove_section(
        text,
        "def _validate_catalog_sources(",
        "\ndef _check_response_model_authority",
    )
    text = remove_section(
        text,
        "def _models_catalog_contract(",
        "\ndef _server_channels_contract",
    )

    import_marker = "from ..models import SourceFile, SourceSnapshot\n"
    imports = (
        import_marker
        + "from .responses_server_catalog import models_catalog_contract\n"
        + "from .responses_server_catalog import validate_catalog_sources\n"
    )
    if import_marker not in text:
        raise SystemExit("extractor import marker did not match")
    text = text.replace(import_marker, imports, 1)
    text = text.replace(
        "catalog_complete, catalog_variant = _validate_catalog_sources(",
        "catalog_complete, catalog_variant = validate_catalog_sources(",
        1,
    )
    text = text.replace(
        '"models_catalog_invalidation": _models_catalog_contract(catalog_variant),',
        '"models_catalog_invalidation": models_catalog_contract(catalog_variant),',
        1,
    )

    EXTRACTOR.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
