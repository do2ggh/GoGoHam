"""Direkter Draht zum Tonsystem (PipeWire/PulseAudio) über libpulse – ab 0.10.30.1.

GoGoHam legt damit selbst virtuelle Soundkarten an und entfernt sie wieder (Module laden/
entladen), ohne das Programm ``pactl``. libpulse ist auf praktisch jedem Linux-Desktop da
(PipeWire bringt es als Ersatz mit, Qt braucht es für den Ton). Fehlt es, nimmt GoGoHam als
Notweg ``pactl``, falls vorhanden.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import shutil
import subprocess
import time

INVALID_INDEX = 0xFFFFFFFF
_READY, _FAILED, _TERMINATED = 4, 5, 6
_OP_RUNNING = 0

_IndexCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p)
_SuccessCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
_StateCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)


class _ModuleInfo(ctypes.Structure):
    _fields_ = [("index", ctypes.c_uint32), ("name", ctypes.c_char_p),
                ("argument", ctypes.c_char_p), ("n_used", ctypes.c_uint32),
                ("auto_unload", ctypes.c_int), ("proplist", ctypes.c_void_p)]


class _SampleSpec(ctypes.Structure):
    _fields_ = [("format", ctypes.c_int), ("rate", ctypes.c_uint32), ("channels", ctypes.c_uint8)]


class _ChannelMap(ctypes.Structure):
    _fields_ = [("channels", ctypes.c_uint8), ("map", ctypes.c_int * 32)]


class _CVolume(ctypes.Structure):
    _fields_ = [("channels", ctypes.c_uint8), ("values", ctypes.c_uint32 * 32)]


class _DeviceInfo(ctypes.Structure):
    """Anfang von pa_sink_info / pa_source_info (beide gleich aufgebaut bis „proplist“)."""
    _fields_ = [("name", ctypes.c_char_p), ("index", ctypes.c_uint32),
                ("description", ctypes.c_char_p), ("sample_spec", _SampleSpec),
                ("channel_map", _ChannelMap), ("owner_module", ctypes.c_uint32),
                ("volume", _CVolume), ("mute", ctypes.c_int), ("monitor", ctypes.c_uint32),
                ("monitor_name", ctypes.c_char_p), ("latency", ctypes.c_uint64),
                ("driver", ctypes.c_char_p), ("flags", ctypes.c_int),
                ("proplist", ctypes.c_void_p)]


_DeviceInfoCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(_DeviceInfo), ctypes.c_int,
                                 ctypes.c_void_p)

_ModuleInfoCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(_ModuleInfo), ctypes.c_int,
                                 ctypes.c_void_p)


def _load_lib():
    for name in (ctypes.util.find_library("pulse"), "libpulse.so.0"):
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        vp = ctypes.c_void_p
        lib.pa_mainloop_new.restype = vp
        lib.pa_mainloop_get_api.restype = vp
        lib.pa_mainloop_get_api.argtypes = [vp]
        lib.pa_mainloop_iterate.argtypes = [vp, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        lib.pa_mainloop_free.argtypes = [vp]
        lib.pa_context_new.restype = vp
        lib.pa_context_new.argtypes = [vp, ctypes.c_char_p]
        lib.pa_context_connect.argtypes = [vp, ctypes.c_char_p, ctypes.c_int, vp]
        lib.pa_context_get_state.argtypes = [vp]
        lib.pa_context_disconnect.argtypes = [vp]
        lib.pa_context_unref.argtypes = [vp]
        lib.pa_context_load_module.restype = vp
        lib.pa_context_load_module.argtypes = [vp, ctypes.c_char_p, ctypes.c_char_p, _IndexCb, vp]
        lib.pa_context_unload_module.restype = vp
        lib.pa_context_unload_module.argtypes = [vp, ctypes.c_uint32, _SuccessCb, vp]
        lib.pa_context_get_module_info_list.restype = vp
        lib.pa_context_get_module_info_list.argtypes = [vp, _ModuleInfoCb, vp]
        for fn in ("pa_context_get_sink_info_list", "pa_context_get_source_info_list"):
            getattr(lib, fn).restype = vp
            getattr(lib, fn).argtypes = [vp, _DeviceInfoCb, vp]
        lib.pa_proplist_gets.restype = ctypes.c_char_p
        lib.pa_proplist_gets.argtypes = [vp, ctypes.c_char_p]
        lib.pa_operation_get_state.argtypes = [vp]
        lib.pa_operation_unref.argtypes = [vp]
        return lib
    return None


class LibPulse:
    """Module laden/entladen über libpulse. Jede Aktion öffnet kurz eine Verbindung."""

    def __init__(self, timeout: float = 5.0):
        self.lib = _load_lib()
        self.timeout = timeout

    def available(self) -> bool:
        return self.lib is not None and self._run(lambda ctx, done: done.append(True)) is True

    def _run(self, start):
        """Verbinden, start(ctx, done) aufrufen, warten bis done gefüllt ist. Ergebnis = done[0]."""
        lib = self.lib
        if lib is None:
            return None
        ml = lib.pa_mainloop_new()
        if not ml:
            return None
        ctx = lib.pa_context_new(lib.pa_mainloop_get_api(ml), b"GoGoHam")
        done: list = []
        keep = []                                   # Rückruf-Objekte am Leben halten
        try:
            if not ctx or lib.pa_context_connect(ctx, None, 0, None) < 0:
                return None
            end = time.monotonic() + self.timeout
            started = False
            ret = ctypes.c_int(0)
            while time.monotonic() < end:
                lib.pa_mainloop_iterate(ml, 0, ctypes.byref(ret))
                st = lib.pa_context_get_state(ctx)
                if st in (_FAILED, _TERMINATED):
                    return None
                if st == _READY and not started:
                    started = True
                    keep.append(start(ctx, done))
                if done:
                    return done[0]
                time.sleep(0.002)
            return None
        finally:
            if ctx:
                lib.pa_context_disconnect(ctx)
                lib.pa_context_unref(ctx)
            lib.pa_mainloop_free(ml)
            del keep

    def load(self, module: str, args: str) -> int | None:
        def start(ctx, done):
            cb = _IndexCb(lambda _c, idx, _u: done.append(idx))
            op = self.lib.pa_context_load_module(ctx, module.encode(), args.encode(), cb, None)
            if op:
                self.lib.pa_operation_unref(op)
            else:
                done.append(INVALID_INDEX)
            return cb
        idx = self._run(start)
        return None if idx is None or idx == INVALID_INDEX else int(idx)

    def unload(self, index: int) -> bool:
        def start(ctx, done):
            cb = _SuccessCb(lambda _c, ok, _u: done.append(bool(ok)))
            op = self.lib.pa_context_unload_module(ctx, int(index), cb, None)
            if op:
                self.lib.pa_operation_unref(op)
            else:
                done.append(False)
            return cb
        return bool(self._run(start))

    def modules(self) -> list[tuple[int, str, str]]:
        found: list[tuple[int, str, str]] = []

        def start(ctx, done):
            def each(_c, info, eol, _u):
                if eol:
                    done.append(found)
                elif info:
                    i = info.contents
                    found.append((int(i.index), (i.name or b"").decode("utf-8", "replace"),
                                  (i.argument or b"").decode("utf-8", "replace")))
            cb = _ModuleInfoCb(each)
            op = self.lib.pa_context_get_module_info_list(ctx, cb, None)
            if op:
                self.lib.pa_operation_unref(op)
            else:
                done.append(found)
            return cb
        return self._run(start) or []


    def devices(self, kind: str) -> list[tuple[str, str]] | None:
        """[(Name, ALSA-Kartennummer oder "")] der Ausgänge ("sinks") bzw. Eingänge
        ("sources"); None = Tonsystem nicht erreichbar."""
        fn = {"sinks": "pa_context_get_sink_info_list",
              "sources": "pa_context_get_source_info_list"}[kind]
        found: list[tuple[str, str]] = []

        def start(ctx, done):
            def each(_c, info, eol, _u):
                if eol:
                    done.append(found)
                elif info:
                    i = info.contents
                    card = self.lib.pa_proplist_gets(i.proplist, b"alsa.card") \
                        if i.proplist else None
                    found.append(((i.name or b"").decode("utf-8", "replace"),
                                  (card or b"").decode("utf-8", "replace")))
            cb = _DeviceInfoCb(each)
            op = getattr(self.lib, fn)(ctx, cb, None)
            if op:
                self.lib.pa_operation_unref(op)
            else:
                done.append(found)
            return cb
        return self._run(start)


def devices(kind: str) -> list[tuple[str, str]] | None:
    """Ausgänge/Eingänge über libpulse (None = nicht möglich, dann pactl als Notweg)."""
    lp = LibPulse()
    return lp.devices(kind) if lp.lib is not None else None


class PactlCli:
    """Notweg: dasselbe über das Programm pactl."""

    def __init__(self, run=subprocess.run):
        self.run = run

    def available(self) -> bool:
        return shutil.which("pactl") is not None

    def load(self, module: str, args: str) -> int | None:
        r = self.run(["pactl", "load-module", module, *args.split()], capture_output=True,
                     text=True, timeout=10)
        try:
            return int((r.stdout or "").strip()) if r.returncode == 0 else None
        except ValueError:
            return None

    def unload(self, index: int) -> bool:
        r = self.run(["pactl", "unload-module", str(index)], capture_output=True, text=True,
                     timeout=10)
        return r.returncode == 0

    def modules(self) -> list[tuple[int, str, str]]:
        r = self.run(["pactl", "list", "modules", "short"], capture_output=True, text=True,
                     timeout=10)
        out = []
        for line in (r.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].isdigit():
                out.append((int(parts[0]), parts[1], parts[2] if len(parts) > 2 else ""))
        return out


def backend():
    """libpulse, wenn erreichbar – sonst pactl – sonst None."""
    lp = LibPulse()
    if lp.available():
        return lp
    cli = PactlCli()
    return cli if cli.available() else None
