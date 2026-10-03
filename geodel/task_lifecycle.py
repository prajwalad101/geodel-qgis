def task_is_active(task):
    try:
        return bool(task and task.isActive())
    except RuntimeError:
        return False


def cancel_task(task):
    try:
        if task_is_active(task):
            task.cancel()
    except RuntimeError:
        pass


def disconnect_signal(signal, callback):
    try:
        signal.disconnect(callback)
    except (TypeError, RuntimeError):
        pass
