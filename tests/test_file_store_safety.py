import pytest

from gently.core.file_store import FileStore, _read_yaml


def _new_store(tmp_path):
    store = FileStore(tmp_path / "store")
    store.create_session("s1", name="safety")
    return store


@pytest.mark.parametrize("embryo_id", ["../outside", "..\\outside", "bad:name", "trailing."])
def test_embryo_id_rejects_unsafe_path_components(tmp_path, embryo_id):
    store = _new_store(tmp_path)

    with pytest.raises(ValueError, match="embryo_id"):
        store.register_embryo("s1", embryo_id)

    assert not (store.root / "outside").exists()


def test_prediction_path_uses_validated_embryo_id(tmp_path):
    store = _new_store(tmp_path)

    with pytest.raises(ValueError, match="embryo_id"):
        store.store_prediction(
            run_id=1,
            session_id="s1",
            embryo_id="../outside",
            timepoint=0,
            predicted_stage="early",
        )

    assert not (store.root / "outside").exists()


def test_read_yaml_refuses_python_object_tags(tmp_path):
    path = tmp_path / "unsafe.yaml"
    path.write_text(
        "value: !!python/object/apply:builtins.eval ['1 + 1']\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Refusing to load unsafe YAML"):
        _read_yaml(path)
