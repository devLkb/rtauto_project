#!/usr/bin/env python3
"""Run ML-Agents with the legacy ONNX exporter required by its 1.15 contract.

ax310 uses a newer CUDA PyTorch whose ``torch.onnx.export`` default is the
dynamo exporter.  That path requires onnxscript and a newer ONNX than the
versions pinned by ML-Agents 1.2.0.dev0.  ML-Agents' exporter was written for
the legacy path, so select it explicitly without changing the locked vision
and protobuf dependency set.
"""

from __future__ import annotations

import atexit
from functools import wraps
import inspect
import os
import threading

from mlagents.torch_utils import default_device, torch


_torch_onnx_export = torch.onnx.export
_onnx_export_supports_dynamo = (
    "dynamo" in inspect.signature(_torch_onnx_export).parameters
)


@wraps(_torch_onnx_export)
def _legacy_onnx_export(*args, **kwargs):
    if _onnx_export_supports_dynamo:
        kwargs.setdefault("dynamo", False)
    return _torch_onnx_export(*args, **kwargs)


torch.onnx.export = _legacy_onnx_export


# torch.set_default_device() installs a thread-local TorchFunctionMode in the
# ax310 PyTorch build. ML-Agents may create trajectory tensors in its optional
# background trainer thread, so install a non-CPU selected device mode in every
# new Python thread as well. CPU does not need this mode, and PyTorch 2.1's CPU
# implementation can corrupt its mode stack when concurrent threads install it.
_selected_device = default_device()
_torch_load = torch.load
if _selected_device.type == "cpu":
    @wraps(_torch_load)
    def _load_cuda_checkpoint_on_cpu(*args, **kwargs):
        # ML-Agents' initialize-from path calls torch.load() without a
        # map_location. The frozen 599887 checkpoint contains CUDA-tagged
        # optimizer storage, so keep its bytes immutable and remap only while
        # deserializing on CPU-only development machines.
        kwargs.setdefault("map_location", _selected_device)
        return _torch_load(*args, **kwargs)

    torch.load = _load_cuda_checkpoint_on_cpu

if _selected_device.type != "cpu":
    _thread_run = threading.Thread.run
    _device_mode_warned = False

    def _install_device_mode() -> None:
        """Install the selected device as this thread's default.

        NOT torch.set_default_device(): that helper first calls __exit__ on the
        previous global DeviceContext, and the mode stack it pops from is
        thread-local, so in a freshly started thread it is empty and the call
        raises "trying to pop from empty mode stack". The thread then dies before
        it ever runs. That surfaced the moment --num-envs went above 1
        (2026-08-30): every environment worker owns a gRPC _serve thread, all
        four died on startup, and training hung with no output at all.

        Pushing the context directly is what the original call was reaching for
        anyway - a new thread has nothing to pop by definition.
        """
        global _device_mode_warned
        try:
            from torch.utils._device import DeviceContext

            DeviceContext(_selected_device).__enter__()
        except Exception as error:  # pragma: no cover - torch internals moved
            if not _device_mode_warned:
                _device_mode_warned = True
                print(
                    "[mlagents_learn_compat] could not set the default torch device "
                    f"for new threads ({error}); tensors created off the main thread "
                    "will default to CPU.")

    @wraps(_thread_run)
    def _run_with_torch_device(self, *args, **kwargs):
        _install_device_mode()
        return _thread_run(self, *args, **kwargs)

    threading.Thread.run = _run_with_torch_device

from mlagents.trainers.learn import main  # noqa: E402


def _install_pid_file() -> None:
    """Publish the trainer PID so dg5f stop never signals forked env workers."""
    pid_file = os.environ.get("DG5F_TRAINER_PID_FILE")
    if not pid_file:
        return

    pid_directory = os.path.dirname(pid_file)
    if pid_directory:
        os.makedirs(pid_directory, exist_ok=True)
    temporary = f"{pid_file}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="ascii") as file:
        file.write(f"{os.getpid()}\n")
    os.replace(temporary, pid_file)

    def remove_own_pid_file() -> None:
        try:
            with open(pid_file, encoding="ascii") as file:
                owner = file.read().strip()
            if owner == str(os.getpid()):
                os.unlink(pid_file)
        except FileNotFoundError:
            pass

    atexit.register(remove_own_pid_file)


if __name__ == "__main__":
    _install_pid_file()
    main()
