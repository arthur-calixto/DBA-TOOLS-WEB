from time import monotonic


class MonitorLimitExceeded(ValueError):
    pass


def check_deadline(deadline):
    if deadline is not None and monotonic() > deadline:
        raise MonitorLimitExceeded("Tempo de processamento excede o limite permitido.")
