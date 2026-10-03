import sys
from pathlib import Path
from types import ModuleType
from zipfile import ZipFile


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in self.callbacks:
            callback(*args)


class Task:
    class SubTaskDependency:
        ParentDependsOnSubTask = object()

    def __init__(self, function=None, on_finished=None, kwargs=None):
        self.function = function
        self.on_finished = on_finished
        self.kwargs = kwargs or {}
        self.subtasks = []
        self.taskTerminated = Signal()

    @classmethod
    def fromFunction(cls, _description, function, on_finished, **kwargs):
        return cls(function, on_finished, kwargs)

    def addSubTask(self, task, _dependencies, _mode):
        self.subtasks.append(task)

    def isCanceled(self):
        return False

    def run(self):
        for task in self.subtasks:
            if not task.run():
                self.taskTerminated.emit()
                return
        try:
            result = self.function(self, **self.kwargs)
        except Exception as error:
            self.on_finished(error, None)
        else:
            self.on_finished(None, result)


class VectorFileWriter:
    class WriterError:
        Canceled = 1

    class SaveVectorOptions:
        pass


class VectorFileWriterTask:
    def __init__(self, layer, path, options):
        self.layer = layer
        self.path = Path(path)
        self.options = options
        self.errorOccurred = Signal()

    def setDescription(self, _description):
        pass

    def setDependentLayers(self, _layers):
        pass

    def run(self):
        if self.layer.error:
            self.errorOccurred.emit(2, self.layer.error)
            return False
        self.layer.export(self.path, self.options.driverName)
        return True


class Layer:
    def __init__(self, name, error=None):
        self._name = name
        self.error = error

    def name(self):
        return self._name

    def isValid(self):
        return True

    def isSpatial(self):
        return True

    def crs(self):
        return CRS("EPSG:4326")

    def export(self, path, driver):
        if driver == "GeoJSON":
            path.write_text('{"type":"FeatureCollection","features":[{}]}')
            return
        for suffix in (".shp", ".shx", ".dbf"):
            path.with_suffix(suffix).write_bytes(b"x" * 101)


class CRS:
    def __init__(self, _name):
        pass

    def isValid(self):
        return True


class Project:
    @classmethod
    def instance(cls):
        return cls()


core = ModuleType("qgis.core")
core.QgsCoordinateReferenceSystem = CRS
core.QgsCoordinateTransform = lambda *_args: object()
core.QgsProject = Project
core.QgsTask = Task
core.QgsVectorFileWriter = VectorFileWriter
core.QgsVectorFileWriterTask = VectorFileWriterTask
qgis = ModuleType("qgis")
qgis.core = core
sys.modules.setdefault("qgis", qgis)
sys.modules.setdefault("qgis.core", core)

from geodel.client import GeoDelError
from geodel.layer_export import LayerExport


def test_prepares_zipped_shapefiles_with_safe_unique_names_and_owned_cleanup():
    completed = []
    task = LayerExport([Layer("Roads"), Layer("roads"), Layer("con.txt")]).create_task(
        lambda error, artifact: completed.append((error, artifact))
    )

    task.run()

    error, artifact = completed[0]
    assert error is None
    assert artifact.suffix == ".zip"
    with ZipFile(artifact.path) as archive:
        assert archive.namelist() == [
            "Roads.dbf",
            "Roads.shp",
            "Roads.shx",
            "layer_con.txt.dbf",
            "layer_con.txt.shp",
            "layer_con.txt.shx",
            "roads_2.dbf",
            "roads_2.shp",
            "roads_2.shx",
        ]
    directory = artifact.path.parent
    artifact.cleanup()
    assert not directory.exists()


def test_reports_writer_failure_and_cleans_owned_directory():
    completed = []
    task = LayerExport([Layer("Roads", error="disk full")]).create_task(
        lambda error, artifact: completed.append((error, artifact))
    )
    directory = task.subtasks[0].path.parent

    task.run()

    error, artifact = completed[0]
    assert isinstance(error, GeoDelError)
    assert str(error) == 'Could not export layer "Roads": disk full'
    assert artifact is None
    assert not directory.exists()
