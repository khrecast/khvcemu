"""Guest heap: first-fit allocator with coalescing.

BREW's MALLOC returns zero-filled memory, and plenty of BREW code relies on
that, so every allocation (and realloc growth) is zeroed.
"""

from __future__ import annotations

import bisect

from .cpu import HEAP_BASE, HEAP_SIZE, Cpu

ALIGN = 8


class Heap:
    def __init__(self, cpu: Cpu, base: int = HEAP_BASE, size: int = HEAP_SIZE):
        self.cpu = cpu
        self.base = base
        self.size = size
        self.free_starts = [base]      # sorted
        self.free_sizes = {base: size}
        self.used: dict[int, int] = {}

    def malloc(self, n: int, zero: bool = True) -> int:
        n = max(ALIGN, (n + ALIGN - 1) & ~(ALIGN - 1))
        for i, start in enumerate(self.free_starts):
            fsz = self.free_sizes[start]
            if fsz >= n:
                del self.free_sizes[start]
                self.free_starts.pop(i)
                if fsz > n:
                    rest = start + n
                    self.free_sizes[rest] = fsz - n
                    self.free_starts.insert(i, rest)
                self.used[start] = n
                if zero:
                    self.cpu.write(start, b"\0" * n)
                return start
        return 0

    def free(self, p: int):
        n = self.used.pop(p, None)
        if n is None:
            return False
        i = bisect.bisect_left(self.free_starts, p)
        # merge with next
        if i < len(self.free_starts) and p + n == self.free_starts[i]:
            nxt = self.free_starts.pop(i)
            n += self.free_sizes.pop(nxt)
        # merge with previous
        if i > 0:
            prev = self.free_starts[i - 1]
            if prev + self.free_sizes[prev] == p:
                self.free_sizes[prev] += n
                return True
        self.free_starts.insert(i, p)
        self.free_sizes[p] = n
        return True

    def realloc(self, p: int, n: int) -> int:
        if p == 0:
            return self.malloc(n)
        if n == 0:
            self.free(p)
            return 0
        old = self.used.get(p)
        if old is None:
            return 0
        if n <= old:
            return p
        q = self.malloc(n)
        if q:
            self.cpu.write(q, self.cpu.read(p, old))
            self.free(p)
        return q

    def size_of(self, p: int) -> int:
        return self.used.get(p, 0)

    def free_bytes(self) -> int:
        return sum(self.free_sizes.values())
