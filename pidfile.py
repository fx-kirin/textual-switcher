import os


def create(pid_filepath):
    with open(pid_filepath, "wb") as f:
        pid = bytes(os.getpid())
        f.write(pid)
