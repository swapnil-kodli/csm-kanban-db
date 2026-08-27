#!/usr/bin/env python3
"""Throwaway egress probe: can this environment open a socket to Supabase?

The Signal CS Postgres port is blocked on one unanswered question — whether the
host running the container is allowed to make outbound TCP connections to
Supabase's pooler. That is a property of the network the container runs on, not
of the application, and it cannot be inferred from anything inside the app. So
this probe does exactly one thing: open a socket, say whether it opened, exit.

It deliberately does NOT:
  - authenticate, or send a single Postgres protocol byte
  - read DATABASE_URL, or touch any credential
  - install psycopg, SQLAlchemy or anything else

A TCP handshake is the whole question. If the socket opens, egress is allowed
and the credentials are the next problem; if it does not, no connection string
would have helped and the compose-Postgres fallback is the answer.

Delete this directory once the question is settled. It is scaffolding.

Usage
-----
    docker build -t egress-probe tools/egress-probe
    docker run --rm egress-probe db.<ref>.supabase.co
    docker run --rm egress-probe aws-0-<region>.pooler.supabase.com:5432

Exit code is 0 when every target connected, 1 otherwise, so CI or a shell
`&&` can act on it.
"""
from __future__ import annotations

import os
import socket
import sys
import time

TIMEOUT = float(os.getenv("PROBE_TIMEOUT", "8"))

# Both Supabase paths, because they fail differently and the distinction
# matters: 5432 is the session pooler / direct connection, 6543 is the
# transaction pooler, and an allowlist can permit one and not the other.
DEFAULT_PORTS = (5432, 6543)

# A target known to be reachable, so "everything failed" can be told apart from
# "the sandbox has no egress at all". Without a control, a total blackout looks
# identical to a Supabase-specific block.
CONTROL = ("registry.npmjs.org", 443)


def parse(target: str) -> list[tuple[str, int]]:
    if ":" in target:
        host, _, port = target.rpartition(":")
        return [(host, int(port))]
    return [(target, p) for p in DEFAULT_PORTS]


def probe(host: str, port: int) -> tuple[bool, str, float]:
    started = time.monotonic()
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        return False, f"DNS did not resolve: {exc.strerror or exc}", time.monotonic() - started

    last = "no address returned"
    for family, socktype, proto, _canon, addr in infos:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(TIMEOUT)
        try:
            sock.connect(addr)
            return True, f"connected to {addr[0]}", time.monotonic() - started
        except socket.timeout:
            last = f"timed out after {TIMEOUT:g}s (packets dropped, not refused)"
        except OSError as exc:
            last = f"{type(exc).__name__}: {exc}"
        finally:
            sock.close()
    return False, last, time.monotonic() - started


def main(argv: list[str]) -> int:
    targets: list[tuple[str, int]] = []
    for raw in argv[1:]:
        targets.extend(parse(raw))
    if not targets:
        print("usage: probe.py <host[:port]> [host[:port] ...]", file=sys.stderr)
        print("       e.g. aws-0-ap-south-1.pooler.supabase.com", file=sys.stderr)
        return 2

    print(f"egress probe · timeout {TIMEOUT:g}s · no credentials read\n")

    ok = True
    for host, port in targets:
        reached, detail, elapsed = probe(host, port)
        mark = "OPEN " if reached else "BLOCK"
        print(f"  [{mark}] {host}:{port}  ({elapsed:.2f}s)  {detail}")
        ok = ok and reached

    reached, detail, elapsed = probe(*CONTROL)
    print(f"\n  [{'OPEN ' if reached else 'BLOCK'}] control {CONTROL[0]}:{CONTROL[1]}"
          f"  ({elapsed:.2f}s)  {detail}")

    names = ", ".join(sorted({h for h, _ in targets}))
    print()
    if ok:
        print(f"VERDICT: outbound TCP to {names} is allowed from this host.")
        print("         NOTE: this proves reachability only. It does not prove TLS")
        print("         completes — an intercepting proxy can accept the socket and")
        print("         still fail certificate verification — and it proves nothing")
        print("         about credentials. Both are separate, later questions.")
    elif reached:
        print(f"VERDICT: this host has egress, but not to {names}. Something is")
        print("         allowlisting specific destinations. Either get these hosts")
        print("         added, or take a route that does not need them.")
    else:
        print("VERDICT: no outbound TCP at all from here, not even the control.")
        print("         This probe cannot answer the question from this network;")
        print("         run it from the host that will actually run the backend.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
