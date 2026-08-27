# egress-probe

**Throwaway.** Delete this directory once the question below is answered.

## The question

Two integrations need outbound access to a third party, and whether the host
running the backend is permitted to open that connection is a property of the
network, not of the application — so no amount of reading the code answers it:

  Supabase Postgres   *.pooler.supabase.com on 5432 (session) and 6543 (txn)
  Gmail               accounts.google.com, oauth2.googleapis.com,
                      gmail.googleapis.com, www.googleapis.com — all on 443

The probe takes any host:port, so it answers both, and any future one.

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

# Both Supabase ports (5432 session/direct, 6543 transaction pooler are the
# default when no port is given):
docker run --rm egress-probe aws-0-<region>.pooler.supabase.com

# Gmail — every host the integration touches, all on 443:
docker run --rm egress-probe accounts.google.com:443 oauth2.googleapis.com:443 \
                             gmail.googleapis.com:443 www.googleapis.com:443
```

Run it **from the host that will actually run the backend**. A result from a
developer laptop says nothing about the marketplace runtime, which is the host
whose egress policy actually matters.

Exit code is `0` when every target connected and `1` otherwise.

## Reading the result

| Result | Meaning | Next step |
|---|---|---|
| Targets OPEN | Reachable from this host | Proceed — but see the limit below |
| Targets BLOCK, control OPEN | An allowlist is blocking those hosts specifically | Get them allowlisted, or take a route that avoids them |
| Everything BLOCK | No outbound TCP from this network at all | Re-run from the real host; this one cannot answer the question |

**What OPEN does not prove.** A TCP handshake is not a working integration. An
intercepting proxy can accept the socket and still fail certificate
verification — which is exactly what happens to `pip` and `npm` inside build
containers in some sandboxes. To confirm TLS and HTTP actually complete, follow
an OPEN result with a real unauthenticated request, e.g.

```sh
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://accounts.google.com/.well-known/openid-configuration
```

A `200` there means the path is genuinely usable. Credentials remain a separate
question after that.

## The fallback

If egress cannot be opened, Postgres moves into the compose stack as a service
with a persistent volume. The application code is identical either way — the
whole port is `DATABASE_URL` plus dialect-safe column types — so this is a
deployment decision, not a rewrite.
