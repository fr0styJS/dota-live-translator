"""Dota-only audio capture: WASAPI process loopback (Windows 10 build 20348+).

Captures audio rendered by one process *and its children* only. No virtual cable,
no audio rerouting, no reboot: Dota keeps playing through the headset while other
apps (Discord, music, browsers) are not captured at all.

Mirrors microsoft/Windows-classic-samples -> Samples/ApplicationLoopback:
  * ActivateAudioInterfaceAsync("VAD\\Process_Loopback", IID_IAudioClient, blob)
  * VT_BLOB carrying AUDIOCLIENT_ACTIVATION_PARAMS (PROCESS_LOOPBACK, include tree)
  * Initialize(SHARED, LOOPBACK | AUTOCONVERTPCM | SRC_DEFAULT_QUALITY)
    with the only format the mixer client accepts: 44.1 kHz, 16-bit, stereo
  * drain IAudioCaptureClient packets, convert to float32 mono @ 16 kHz

Public API
  start_process_capture(exe_name, emit, log=print) -> Supervisor
  selftest(seconds, exe_name)   # prints RMS per second, for manual checks
"""
import ctypes
import threading
import time

import numpy as np

try:
  import comtypes
  from comtypes import COMMETHOD, COMObject, GUID, HRESULT, IUnknown
except Exception as exc:  # pragma: no cover - import guard
  raise ImportError("comtypes is required: pip install comtypes") from exc

VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2

VT_BLOB = 65
CAPTURE_SR = 44100
CAPTURE_CH = 2
CAPTURE_BITS = 16
BYTES_PER_FRAME = CAPTURE_CH * CAPTURE_BITS // 8  # 4


class WAVEFORMATEX(ctypes.Structure):
  _pack_ = 1
  _fields_ = [("wFormatTag", ctypes.c_ushort),
              ("nChannels", ctypes.c_ushort),
              ("nSamplesPerSec", ctypes.c_uint32),
              ("nAvgBytesPerSec", ctypes.c_uint32),
              ("nBlockAlign", ctypes.c_ushort),
              ("wBitsPerSample", ctypes.c_ushort),
              ("cbSize", ctypes.c_ushort)]


class _BLOB(ctypes.Structure):
  _fields_ = [("cbSize", ctypes.c_ulong),
              ("pBlobData", ctypes.POINTER(ctypes.c_ubyte))]


class PROPVARIANT(ctypes.Structure):
  _fields_ = [("vt", ctypes.c_ushort),
              ("wReserved1", ctypes.c_ushort),
              ("wReserved2", ctypes.c_ushort),
              ("wReserved3", ctypes.c_ushort),
              ("blob", _BLOB)]


class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
  _fields_ = [("TargetProcessId", ctypes.c_uint32),
              ("ProcessLoopbackMode", ctypes.c_int)]


class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
  _fields_ = [("ActivationType", ctypes.c_int),
              ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS)]


class IActivateAudioInterfaceAsyncOperation(IUnknown):
  _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
  _methods_ = [
    COMMETHOD([], HRESULT, "GetActivateResult",
              (["out"], ctypes.POINTER(HRESULT), "activateResult"),
              (["out"], ctypes.POINTER(ctypes.POINTER(IUnknown)), "activatedInterface")),
  ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
  _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
  _methods_ = [
    COMMETHOD([], HRESULT, "ActivateCompleted",
              (["in"], ctypes.POINTER(IActivateAudioInterfaceAsyncOperation), "activateOperation")),
  ]


class IAgileObject(IUnknown):
  """Marks the completion handler agile.

  ActivateAudioInterfaceAsync rejects a non-agile completion handler with
  E_ILLEGAL_METHOD_CALL (0x8000000E) because the callback is delivered from an
  MTA worker thread.
  """
  _iid_ = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
  _methods_ = []


class IAudioClient(IUnknown):
  _iid_ = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
  _methods_ = [
    COMMETHOD([], HRESULT, "Initialize",
              (["in"], ctypes.c_int, "ShareMode"),
              (["in"], ctypes.c_uint32, "StreamFlags"),
              (["in"], ctypes.c_longlong, "hnsBufferDuration"),
              (["in"], ctypes.c_longlong, "hnsPeriodicity"),
              (["in"], ctypes.POINTER(WAVEFORMATEX), "pFormat"),
              (["in"], ctypes.POINTER(GUID), "AudioSessionGuid")),
    COMMETHOD([], HRESULT, "GetBufferSize",
              (["out"], ctypes.POINTER(ctypes.c_uint32), "pNumBufferFrames")),
    COMMETHOD([], HRESULT, "GetStreamLatency",
              (["out"], ctypes.POINTER(ctypes.c_longlong), "phnsLatency")),
    COMMETHOD([], HRESULT, "GetCurrentPadding",
              (["out"], ctypes.POINTER(ctypes.c_uint32), "pNumPaddingFrames")),
    COMMETHOD([], HRESULT, "IsFormatSupported",
              (["in"], ctypes.c_int, "ShareMode"),
              (["in"], ctypes.POINTER(WAVEFORMATEX), "pFormat"),
              (["out"], ctypes.POINTER(ctypes.POINTER(WAVEFORMATEX)), "ppClosestMatch")),
    COMMETHOD([], HRESULT, "GetMixFormat",
              (["out"], ctypes.POINTER(ctypes.POINTER(WAVEFORMATEX)), "ppDeviceFormat")),
    COMMETHOD([], HRESULT, "GetDevicePeriod",
              (["out"], ctypes.POINTER(ctypes.c_longlong), "phnsDefault"),
              (["out"], ctypes.POINTER(ctypes.c_longlong), "phnsMinimum")),
    COMMETHOD([], HRESULT, "Start"),
    COMMETHOD([], HRESULT, "Stop"),
    COMMETHOD([], HRESULT, "Reset"),
    COMMETHOD([], HRESULT, "SetEventHandle", (["in"], ctypes.c_void_p, "eventHandle")),
    COMMETHOD([], HRESULT, "GetService",
              (["in"], ctypes.POINTER(GUID), "riid"),
              (["out"], ctypes.POINTER(ctypes.POINTER(IUnknown)), "ppv")),
  ]


class IAudioCaptureClient(IUnknown):
  _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
  _methods_ = [
    COMMETHOD([], HRESULT, "GetBuffer",
              (["out"], ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)), "ppData"),
              (["out"], ctypes.POINTER(ctypes.c_uint32), "pNumFramesToRead"),
              (["out"], ctypes.POINTER(ctypes.c_uint32), "pdwFlags"),
              (["out"], ctypes.POINTER(ctypes.c_uint64), "pu64DevicePosition"),
              (["out"], ctypes.POINTER(ctypes.c_uint64), "pu64QPCPosition")),
    COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], ctypes.c_uint32, "NumFramesRead")),
    COMMETHOD([], HRESULT, "GetNextPacketSize",
              (["out"], ctypes.POINTER(ctypes.c_uint32), "pNumFramesInNextPacket")),
  ]


class _CompletionHandler(COMObject):
  _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

  def __init__(self):
    super().__init__()
    self.done = threading.Event()
    self.hr = None
    self.client = None

  def ActivateCompleted(self, operation):
    try:
      hr, punk = operation.GetActivateResult()
      self.hr = int(hr) if hr is not None else None
      if self.hr == 0 and punk is not None:
        self.client = punk.QueryInterface(IAudioClient)
    except BaseException as exc:  # never raise into COM
      self.hr = exc
    finally:
      self.done.set()
    return 0


_mmdevapi = ctypes.WinDLL("mmdevapi.dll")
_ActivateAudioInterfaceAsync = ctypes.WINFUNCTYPE(
  HRESULT,
  ctypes.c_wchar_p,
  ctypes.POINTER(GUID),
  ctypes.POINTER(PROPVARIANT),
  ctypes.POINTER(IUnknown),
  ctypes.POINTER(ctypes.POINTER(IActivateAudioInterfaceAsyncOperation)),
)(("ActivateAudioInterfaceAsync", _mmdevapi))


def _find_pid(exe_name: str) -> int | None:
  import psutil
  want = exe_name.lower()
  for p in psutil.process_iter(["pid", "name"]):
    try:
      if (p.info.get("name") or "").lower() == want:
        return int(p.info["pid"])
    except (psutil.NoSuchProcess, psutil.AccessDenied):
      continue
  return None


def _resample_16k(x: np.ndarray, sr: int) -> np.ndarray:
  """Anti-aliased decimation to 16 kHz. Good enough for ASR, no extra deps."""
  if sr == 16000 or len(x) < 2:
    return x.astype(np.float32, copy=False)
  k = int(round(sr / 16000))
  if k > 1:
    n = len(x) // k * k
    if n >= k:
      x = x[:n].reshape(-1, k).mean(axis=1)
      sr = sr / k
  if abs(sr - 16000) < 1:
    return x.astype(np.float32, copy=False)
  n_out = max(1, int(len(x) * 16000 / sr))
  return np.interp(np.linspace(0, len(x) - 1, n_out),
                   np.arange(len(x)), x).astype(np.float32)


def _activate_client(pid: int):
  """Block until the process-loopback IAudioClient for `pid` is activated."""
  params = AUDIOCLIENT_ACTIVATION_PARAMS(
    AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK,
    AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(ctypes.c_uint32(pid),
                                       PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE))
  pv = PROPVARIANT()
  pv.vt = VT_BLOB
  pv.blob.cbSize = ctypes.sizeof(params)
  pv.blob.pBlobData = ctypes.cast(ctypes.pointer(params),
                                  ctypes.POINTER(ctypes.c_ubyte))

  handler = _CompletionHandler()
  op = ctypes.POINTER(IActivateAudioInterfaceAsyncOperation)()
  hr = _ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
                                    ctypes.byref(IAudioClient._iid_),
                                    ctypes.byref(pv), handler, ctypes.byref(op))
  if hr != 0:
    raise OSError(f"ActivateAudioInterfaceAsync failed hr=0x{hr & 0xFFFFFFFF:08X}")
  if not handler.done.wait(10.0):
    raise TimeoutError("process loopback activation timed out")
  try:
    op.Release()
  except Exception:
    pass
  if handler.hr != 0:
    if isinstance(handler.hr, BaseException):
      raise handler.hr
    raise OSError(f"activation result hr=0x{int(handler.hr) & 0xFFFFFFFF:08X}")
  if handler.client is None:
    raise OSError("activation returned no IAudioClient")
  return handler.client


def open_capture(pid: int, emit, log=print) -> IAudioClient:
  """Start a capture stream for `pid` (and its child processes). Returns client."""
  try:
    comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
  except OSError:
    # thread already initialized (S_FALSE / RPC_E_CHANGED_MODE): the handler is
    # agile, so activation still succeeds from an STA thread.
    pass
  client = _activate_client(pid)

  fmt = WAVEFORMATEX()
  fmt.wFormatTag = 1  # WAVE_FORMAT_PCM
  fmt.nChannels = CAPTURE_CH
  fmt.nSamplesPerSec = CAPTURE_SR
  fmt.wBitsPerSample = CAPTURE_BITS
  fmt.nBlockAlign = BYTES_PER_FRAME
  fmt.nAvgBytesPerSec = CAPTURE_SR * BYTES_PER_FRAME
  fmt.cbSize = 0

  flags = (AUDCLNT_STREAMFLAGS_LOOPBACK
           | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
           | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY)
  client.Initialize(AUDCLNT_SHAREMODE_SHARED, flags, 0, 0, ctypes.byref(fmt), None)

  cap = client.GetService(ctypes.byref(IAudioCaptureClient._iid_))
  cap = cap.QueryInterface(IAudioCaptureClient)
  client.Start()
  return client, cap, emit, log


class Supervisor:
  """Keeps a process-loopback capture attached to `exe_name` while it runs."""

  def __init__(self, exe_name, emit, log=print):
    self.exe_name = exe_name
    self.emit = emit
    self.log = log
    self.last_error = None   # set when activation genuinely fails
    self.capturing = False   # True once a stream is open for a live pid
    self._stop = threading.Event()
    self._thread = threading.Thread(target=self._run, daemon=True,
                                    name="proc-loopback")

  def start(self):
    self._thread.start()
    return self

  def stop(self, timeout=3.0):
    self._stop.set()
    self._thread.join(timeout)

  def running(self) -> bool:
    return self._thread.is_alive()

  def _run(self):
    while not self._stop.is_set():
      pid = _find_pid(self.exe_name)
      if pid is None:
        self._stop.wait(1.0)
        continue
      try:
        client, cap, _emit, _log = open_capture(pid, self.emit, self.log)
        self.capturing = True
        self.last_error = None
        self.log(f"process loopback: capturing pid {pid} ({self.exe_name} + children)")
      except Exception as exc:
        self.capturing = False
        self.last_error = exc
        self.log(f"process loopback failed for {self.exe_name}: {exc!r}")
        self._stop.wait(3.0)
        continue
      try:
        self._pump(client, cap, pid)
      except Exception as exc:
        self.log(f"process loopback stream ended: {exc!r}")
      finally:
        self.capturing = False
        try:
          client.Stop()
        except Exception:
          pass
      self._stop.wait(0.5)

  def _pump(self, client, cap, pid):
    import psutil
    silent_logged = False
    while not self._stop.is_set():
      try:
        if not psutil.pid_exists(pid):
          return
      except Exception:
        return
      size = cap.GetNextPacketSize()
      got_audio = False
      while size and size > 0:
        data, frames, flags, _pos, _qpc = cap.GetBuffer()
        try:
          if frames:
            if flags & AUDCLNT_BUFFERFLAGS_SILENT:
              mono = np.zeros(frames, dtype=np.float32)
            else:
              raw = ctypes.string_at(data, frames * BYTES_PER_FRAME)
              pcm = np.frombuffer(raw, dtype=np.int16).reshape(-1, CAPTURE_CH)
              mono = (pcm.mean(axis=1) / 32768.0).astype(np.float32)
            self.emit(_resample_16k(mono, CAPTURE_SR))
            got_audio = True
        finally:
          cap.ReleaseBuffer(frames)
        size = cap.GetNextPacketSize()
      if not got_audio and not silent_logged:
        silent_logged = True  # target alive but rendering nothing: expected
      self._stop.wait(0.02)


def start_process_capture(exe_name: str, emit, log=print) -> Supervisor:
  return Supervisor(exe_name, emit, log=log).start()


def selftest(seconds: float = 6.0, exe_name: str = "dota2.exe") -> None:
  levels = []
  lock = threading.Lock()

  def emit(mono):
    with lock:
      levels.append(float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0)

  sup = start_process_capture(exe_name, emit)
  t_end = time.time() + seconds
  try:
    while time.time() < t_end:
      time.sleep(1.0)
      with lock:
        chunk, levels[:] = levels[:], []
      rms = float(np.sqrt(np.mean(np.square(chunk)))) if chunk else 0.0
      print(f"t={time.time() - (t_end - seconds):5.1f}s rms={rms:.4f} "
            f"{'AUDIO' if rms > 0.002 else 'silence'}")
  finally:
    sup.stop()


if __name__ == "__main__":
  import sys
  secs = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
  exe = sys.argv[2] if len(sys.argv) > 2 else "dota2.exe"
  selftest(secs, exe)
