"""Memory use of a worker process (macOS phys_footprint via libproc) and the indexer memory limit setting."""
import ctypes
import ctypes.util
import functools
import os
import sys

RUSAGE_INFO_V2 = 2
MB = 1048576
DEFAULT_LIMIT_MB = 2048


class RusageInfoV2(ctypes.Structure):
    """struct rusage_info_v2 from <libproc.h>; the whole structure must be present so the kernel never writes past it."""
    _fields_ = [("ri_uuid", ctypes.c_uint8 * 16)] + [(name, ctypes.c_uint64) for name in (
        "ri_user_time", "ri_system_time", "ri_pkg_idle_wkups", "ri_interrupt_wkups", "ri_pageins",
        "ri_wired_size", "ri_resident_size", "ri_phys_footprint", "ri_proc_start_abstime",
        "ri_proc_exit_abstime", "ri_child_user_time", "ri_child_system_time", "ri_child_pkg_idle_wkups",
        "ri_child_interrupt_wkups", "ri_child_pageins", "ri_child_elapsed_abstime",
        "ri_diskio_bytesread", "ri_diskio_byteswritten")]


@functools.lru_cache(maxsize=None)
def _libproc():
    lib = ctypes.CDLL(ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib")
    lib.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    lib.proc_pid_rusage.restype = ctypes.c_int
    return lib


def footprint_mb(pid):
    """Physical footprint of a process in MB, or None when unknown. RSS is not used because compression
    and swap lower it while the process still holds memory."""
    if sys.platform != "darwin" or pid is None: return None
    try:
        info = RusageInfoV2()
        if _libproc().proc_pid_rusage(int(pid), RUSAGE_INFO_V2, ctypes.byref(info)) != 0: return None
        return int(info.ri_phys_footprint) // MB
    except Exception:
        return None


def limit_mb(env=None):
    """SCREEN_CONTEXT_INDEXER_MAX_MB as a positive int; the default when unset, invalid, or not positive."""
    env = os.environ if env is None else env
    try: value = int(env.get("SCREEN_CONTEXT_INDEXER_MAX_MB", ""))
    except (TypeError, ValueError): return DEFAULT_LIMIT_MB
    return value if value > 0 else DEFAULT_LIMIT_MB
