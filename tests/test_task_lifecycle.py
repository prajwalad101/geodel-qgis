from geodel.task_lifecycle import cancel_task, disconnect_signal


def test_cancel_task_ignores_deleted_qgis_wrapper():
    class DeletedTask:
        def cancel(self):
            raise RuntimeError(
                "wrapped C/C++ object of type QgsTaskWrapper has been deleted"
            )

    cancel_task(DeletedTask())


def test_cancel_task_cancels_queued_task():
    class QueuedTask:
        canceled = False

        def isActive(self):
            return False

        def cancel(self):
            self.canceled = True

    task = QueuedTask()
    cancel_task(task)
    assert task.canceled


def test_disconnect_signal_ignores_missing_connection():
    class DisconnectedSignal:
        def disconnect(self, _callback):
            raise TypeError("'method' object is not connected")

    disconnect_signal(DisconnectedSignal(), lambda: None)
