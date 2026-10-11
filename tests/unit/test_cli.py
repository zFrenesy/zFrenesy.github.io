import json
import shutil
from pathlib import Path

from rp.cli import main
from rp.identity.ids import is_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FOLDER = FIXTURES / "contribution-folder"


def fingerprint(capsys, folder):
    assert main(["fingerprint", str(folder)]) == 0
    return json.loads(capsys.readouterr().out)["scientific_fingerprint"]


def test_validate(capsys, tmp_path):
    assert main(["validate", str(FIXTURES / "records" / "valid")]) == 0
    assert "14 of 14 files valid" in capsys.readouterr().out
    assert main(["validate", str(FIXTURES / "records" / "invalid" / "problem" / "norway-scalar.yaml")]) == 1
    assert "yaml.ambiguous_scalar" in capsys.readouterr().out
    assert main(["validate", str(tmp_path)]) == 1  # nothing to validate is a failure, not a pass


def test_validate_with_explicit_type(capsys, tmp_path):
    target = tmp_path / "anything.yaml"
    shutil.copy(FIXTURES / "records" / "valid" / "problem" / "derived.yaml", target)
    assert main(["validate", "--type", "problem", str(target)]) == 0
    assert main(["validate", "--type", "contribution", str(target)]) == 1


def test_fingerprint_changes_with_one_byte(capsys, tmp_path):
    folder = tmp_path / "c"
    shutil.copytree(FOLDER, folder)
    before = fingerprint(capsys, folder)
    assert before == fingerprint(capsys, FOLDER)
    path = folder / "files" / "attempt.tex"
    data = bytearray(path.read_bytes())
    data[-2] ^= 1
    path.write_bytes(bytes(data))
    assert fingerprint(capsys, folder) != before


def test_fingerprint_refuses_undeclared_files_and_symlinks(capsys, tmp_path):
    folder = tmp_path / "c"
    shutil.copytree(FOLDER, folder)
    (folder / "files" / "notes.txt").write_text("not declared")
    assert main(["fingerprint", str(folder)]) == 1
    assert "manifest.undeclared_file" in capsys.readouterr().err
    (folder / "files" / "notes.txt").unlink()
    (folder / "files" / "link.tex").symlink_to(folder / "files" / "attempt.tex")
    assert main(["fingerprint", str(folder)]) == 1
    assert "manifest.symlink" in capsys.readouterr().err


def test_id_new(capsys):
    assert main(["id", "new", "person"]) == 0
    assert is_id(capsys.readouterr().out.strip(), "person")


def test_fingerprint_reports_bad_yaml_without_a_traceback(capsys, tmp_path):
    assert main(["fingerprint", str(tmp_path)]) == 1
    (tmp_path / "contribution.yaml").write_text("title: yes\n")
    assert main(["fingerprint", str(tmp_path)]) == 1
    assert "yaml.ambiguous_scalar" in capsys.readouterr().err
