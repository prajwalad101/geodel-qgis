"""Own preparation, transfer and temporary files for one upload."""
from qgis.core import QgsApplication, QgsTask

from .client import GeoDelError
from .config import DEFAULT_CONFIG, PRODUCT_NAME
from .layer_export import LayerExport
from .task_lifecycle import cancel_task, disconnect_signal
from .tasks import _upload_file


class Upload:
    def __init__(self, path=None, layers=None, config=DEFAULT_CONFIG):
        self._path = path
        self._config = config
        self._export = LayerExport(layers, config) if layers else None
        self._task = None
        self._progress = None
        self._cancel_requested = False
        self._on_progress = None
        self._on_finished = None
        if self._export is None:
            try:
                size = path.stat().st_size
            except OSError as error:
                raise GeoDelError(f"Could not read upload file: {error}") from error
            if size > config.max_file_size_bytes:
                raise GeoDelError(f"File exceeds the {config.file_size_label} upload limit.")
            if size == 0:
                raise GeoDelError("File is empty.")

    @property
    def suffix(self):
        return self._export.suffix if self._export else self._path.suffix.lower()

    def start(self, filename, destination, connection_version, on_progress, on_finished):
        self.connection_version = connection_version
        self._filename = filename
        self._destination = dict(destination, config=self._config)
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._advance()

    def cancel(self):
        if self._task is None or self._cancel_requested:
            return False
        self._cancel_requested = True
        cancel_task(self._task)
        return True

    def close(self):
        self._on_progress = None
        self._on_finished = None
        self._disconnect_progress()
        # Keep ownership until the writer/transfer stops using the files.
        self.cancel()

    def _advance(self):
        try:
            preparing = bool(self._export and self._export.has_more_layers)
            if preparing:
                task = self._export.create_task(
                    lambda error, artifact=None: self._export_finished(task, error, artifact)
                )
            else:
                task = QgsTask.fromFunction(
                    f"Upload {self._filename} to {PRODUCT_NAME}",
                    _upload_file,
                    on_finished=lambda error, result=None: self._transfer_finished(task, error, result),
                    path=self._path,
                    upload_filename=self._filename,
                    **self._destination,
                )
            self._disconnect_progress()
            self._task = task

            def show_progress(value):
                # Queued progress from an earlier stage must not overwrite this one.
                if task is self._task and self._on_progress is not None:
                    self._on_progress(self, preparing, value)

            task.progressChanged.connect(show_progress)
            self._progress = (task.progressChanged, show_progress)
            show_progress(0)
            QgsApplication.taskManager().addTask(task)
        except Exception as error:
            self._finish(error, None)

    def _export_finished(self, task, error, artifact):
        if task is not self._task:
            return
        if self._cancel_requested or error is not None or artifact is None:
            self._finish(error, None)
            return
        self._path = artifact.path
        self._advance()

    def _transfer_finished(self, task, error, result):
        if task is self._task:
            self._finish(error, result)

    def _finish(self, error, result):
        self._disconnect_progress()
        self._task = None
        if self._export is not None:
            self._export.cleanup()
        if self._cancel_requested and result is None:
            error = None
        callback = self._on_finished
        self._on_progress = None
        self._on_finished = None
        if callback is not None:
            callback(self, error, result)

    def _disconnect_progress(self):
        if self._progress is not None:
            disconnect_signal(*self._progress)
            self._progress = None
