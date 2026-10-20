import importlib.util
from pathlib import Path


def test_streaming_digest_detects_copy_mutation(tmp_path):
    path = Path(__file__).resolve().parents[2] / "scripts/reference_manifest.py"
    spec = importlib.util.spec_from_file_location("reference_manifest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = tmp_path / "synthetic.csv"
    fixture.write_bytes(b"S1,label\n1,0\n2,1\n")
    before = module.sha256(fixture)
    assert module.sha256(fixture) == before
    fixture.write_bytes(b"S1,label\n1,1\n2,1\n")
    assert module.sha256(fixture) != before
