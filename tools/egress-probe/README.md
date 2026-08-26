# egress-probe

**Throwaway.** Delete this directory once the question below is answered.

## The question

Signal CS can run on Supabase Postgres instead of the SQLite file, but only if
the host running the backend container is permitted to open an outbound TCP
connection to Supabase's pooler. That is a property of the network, not of the
application, so no amount of reading the code answers it.

## What it does

Opens a socket. Reports whether it opened. Exits.

It does not authenticate, does not speak a byte of the Postgres wire protocol,
and does not read `DATABASE_URL` or any other credential — so it is safe to run
anywhere, and a successful result proves reachability only, never authorisation.

It also probes a control host (`registry.npmjs.org:443`) so that "Supabase is
blocked" can be distinguished from "this network has no egress at all". Those
two results call for completely different responses and look identical without
the control.

## Running it

```sh
docker build -t egress-probe tools/egress-probe

# Both Supabase ports (5432 session/direct, 6543 transaction pooler):
docker run --rm egress-probe aws-0-<region>.pooler.supabase.com

# Or one specific endpoint:
docker run --rm egress-probe db.<project-ref>.supabase.co:5432
```

Run it **from the host that will actually run the backend**. A result from a
developer laptop says nothing about the marketplace runtime, which is the host
whose egress policy actually matters.

Exit code is `0` when every target connected and `1` otherwise.

## Reading the result

| Result | Meaning | Next step |
|---|---|---|
| Supabase OPEN | Egress is allowed | Ship the Postgres port; credentials are the next problem |
| Supabase BLOCK, control OPEN | An allowlist is blocking Supabase specifically | Ask for the pooler host to be allowlisted, or take the fallback |
| Everything BLOCK | No outbound TCP from this network at all | Re-run from the real host; this one cannot answer the question |

## The fallback

If egress cannot be opened, Postgres moves into the compose stack as a service
with a persistent volume. The application code is identical either way — the
whole port is `DATABASE_URL` plus dialect-safe column types — so this is a
deployment decision, not a rewrite.
