"""Asynchronous OpenGL timestamp collection for the runtime benchmark."""
from collections import deque

import raylib as gl


class GpuTimeline:
    def __init__(self):
        signatures = {
            "GenQueries": "void(*)(int, unsigned *)",
            "DeleteQueries": "void(*)(int, const unsigned *)",
            "QueryCounter": "void(*)(unsigned, unsigned)",
            "GetQueryObjectiv": "void(*)(unsigned, unsigned, int *)",
            "GetQueryObjectui64v": "void(*)(unsigned, unsigned, unsigned long long *)",
        }
        for name, signature in signatures.items():
            address = gl.rlGetProcAddress(("gl" + name).encode("ascii"))
            if address == gl.ffi.NULL:
                raise RuntimeError(f"OpenGL does not expose gl{name}")
            setattr(self, name, gl.ffi.cast(signature, address))
        self.pending = deque()
        self.available = gl.ffi.new("int *")
        self.value = gl.ffi.new("unsigned long long *")
        self.marks = None

    def start(self):
        if len(self.pending) < 64:
            self.marks = []
            self.mark("start")

    def mark(self, label):
        if self.marks is None:
            return
        gl.rlDrawRenderBatchActive()
        query = gl.ffi.new("unsigned *")
        self.GenQueries(1, query)
        self.QueryCounter(query[0], 0x8E28)  # GL_TIMESTAMP
        self.marks.append((label, query))

    def finish(self, frame):
        if self.marks is not None:
            self.mark("composite")
            self.pending.append((frame, self.marks))
            self.marks = None

    def collect(self, wait=False):
        while self.pending:
            frame, marks = self.pending[0]
            self.GetQueryObjectiv(marks[-1][1][0], 0x8867, self.available)
            if not wait and not self.available[0]:  # GL_QUERY_RESULT_AVAILABLE
                break
            last = None
            values = {}
            for label, query in marks:
                self.GetQueryObjectui64v(query[0], 0x8866, self.value)  # GL_QUERY_RESULT
                stamp = self.value[0]
                if last is not None:
                    values[label] = values.get(label, 0.0) + (stamp - last) / 1e6
                last = stamp
                self.DeleteQueries(1, query)
            frame["gpu_ms"] = values
            self.pending.popleft()
