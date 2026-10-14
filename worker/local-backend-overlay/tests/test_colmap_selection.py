import struct
from pathlib import Path
import pytest
from forme_backend.model_worker import select_primary_model, StageFailure


def test_primary_model_uses_camera_count_not_feature_file_size(tmp_path: Path):
    first=tmp_path/'0';first.mkdir()
    (first/'images.bin').write_bytes(struct.pack('<Q',20)+b'x'*10000)
    complete=tmp_path/'1';complete.mkdir()
    (complete/'images.bin').write_bytes(struct.pack('<Q',80)+b'x'*100)
    assert select_primary_model(tmp_path)==complete


def test_no_registered_model_stops_before_dense_reconstruction(tmp_path: Path):
    with pytest.raises(StageFailure) as error:
        select_primary_model(tmp_path)
    assert error.value.code=='CAMERAS_NOT_REGISTERED'
