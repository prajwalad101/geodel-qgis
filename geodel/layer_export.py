import re
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsTask,
    QgsVectorFileWriter,
    QgsVectorFileWriterTask,
)

from .client import GeoDelError
from .config import PRODUCT_NAME


MAX_LAYERS = 20
TARGET_CRS = QgsCoordinateReferenceSystem("EPSG:4326")


class UploadArtifact:
    def __init__(self, directory, path, suffix):
        self._directory = directory
        self.path = path
        self.suffix = suffix

    def cleanup(self):
        self._directory.cleanup()


class LayerExport:
    def __init__(self, layers):
        self.layers = list(layers)
        self._error = None
        if len(self.layers) > MAX_LAYERS:
            raise GeoDelError(f"Choose no more than {MAX_LAYERS} layers.")
        for layer in self.layers:
            if not layer.isValid():
                raise GeoDelError(f'Layer "{layer.name()}" could not be read.')
            if not layer.isSpatial():
                raise GeoDelError(f'Layer "{layer.name()}" has no geometry.')
            if not layer.crs().isValid():
                raise GeoDelError(f'Layer "{layer.name()}" has no valid CRS.')

    @property
    def suffix(self):
        return ".geojson" if len(self.layers) == 1 else ".zip"

    def create_task(self, on_finished):
        directory = TemporaryDirectory(prefix="geodel-")
        root = Path(directory.name)
        artifact = UploadArtifact(directory, root / f"upload{self.suffix}", self.suffix)
        output_paths = [
            artifact.path if self.suffix == ".geojson" else root / f"{stem}.shp"
            for stem in _export_stems(self.layers)
        ]

        completed = False

        def finished(error, result=None):
            nonlocal completed
            if completed:
                return
            completed = True
            if error is None and result is None and self._error:
                error = GeoDelError(self._error)
            if error is not None or result is None:
                artifact.cleanup()
            on_finished(error, result)

        task = QgsTask.fromFunction(
            f"Prepare layers for {PRODUCT_NAME}",
            self._prepare,
            on_finished=finished,
            artifact=artifact,
            output_paths=output_paths,
        )
        driver = "GeoJSON" if self.suffix == ".geojson" else "ESRI Shapefile"
        for layer, output_path in zip(self.layers, output_paths):
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = driver
            options.fileEncoding = "UTF-8"
            options.ct = QgsCoordinateTransform(
                layer.crs(), TARGET_CRS, QgsProject.instance()
            )
            writer = QgsVectorFileWriterTask(layer, str(output_path), options)
            writer.setDescription(f"Export {layer.name()} for {PRODUCT_NAME}")
            writer.setDependentLayers([layer])
            writer.errorOccurred.connect(
                lambda code, message, layer_name=layer.name(): self._record_error(
                    code, layer_name, message
                )
            )
            task.addSubTask(
                writer, [], QgsTask.SubTaskDependency.ParentDependsOnSubTask
            )
        task.taskTerminated.connect(lambda: finished(None, None))
        return task

    def _prepare(self, task, artifact, output_paths):
        if task.isCanceled():
            return None
        if self._error:
            raise GeoDelError(self._error)
        for layer, output_path in zip(self.layers, output_paths):
            try:
                has_features = (
                    _geojson_has_features(output_path)
                    if output_path.suffix == ".geojson"
                    else output_path.stat().st_size > 100
                )
            except OSError as error:
                raise GeoDelError(
                    f'Could not inspect exported layer "{layer.name()}": {error}'
                ) from error
            if not has_features:
                raise GeoDelError(f'Layer "{layer.name()}" is empty.')

        if artifact.suffix == ".zip":
            files = sorted(
                path for path in artifact.path.parent.iterdir() if path.is_file()
            )
            if not files:
                raise GeoDelError("Layer export produced no files")
            with ZipFile(artifact.path, "w", ZIP_DEFLATED) as archive:
                for path in files:
                    if task.isCanceled():
                        return None
                    archive.write(path, path.name)
        return artifact

    def _record_error(self, code, layer_name, message):
        if (
            code != QgsVectorFileWriter.WriterError.Canceled
            and self._error is None
        ):
            detail = f": {message}" if message else ""
            self._error = f'Could not export layer "{layer_name}"{detail}'


def _geojson_has_features(path):
    pattern = re.compile(rb'"features"\s*:\s*\[')
    buffer = b""
    found = False
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8192), b""):
            buffer += chunk
            if not found:
                match = pattern.search(buffer)
                if match is None:
                    buffer = buffer[-32:]
                    continue
                buffer = buffer[match.end() :]
                found = True
            content = buffer.lstrip()
            if content:
                return content[:1] != b"]"
    raise GeoDelError("Layer export produced invalid GeoJSON")


def _export_stems(layers):
    used = set()
    stems = []
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
    for index, layer in enumerate(layers, 1):
        base = re.sub(r"[^\w.-]+", "_", layer.name()).strip("._")[:80]
        if not base:
            base = f"layer_{index}"
        if base.partition(".")[0].casefold() in reserved:
            base = f"layer_{base}"
        stem = base
        number = 2
        while stem.casefold() in used:
            suffix = f"_{number}"
            stem = f"{base[: 80 - len(suffix)]}{suffix}"
            number += 1
        used.add(stem.casefold())
        stems.append(stem)
    return stems
