# Workspace identity flow

Phase 10 uses an approved identity gateway/BFF with a per-user API-audience token. Organization issuer, audience, gateway client/session flow and group/scope settings are not available. Normal API startup and the workspace launcher therefore remain fail-closed. The user explicitly chose this behavior in Phase 9. The templates in `config/oidc.example.json` and `config/ui.example.json` are incomplete configuration, not demo identity defaults.

Streamlit’s [authentication guide](https://docs.streamlit.io/develop/concepts/connections/authentication) distinguishes OIDC identity authentication from authorization. `st.user`, an email header or an ID token is not forwarded as an API credential. There is no token-paste box, role picker or production test identity selector.

## Protected configuration and gateway contract

The deployment owner supplies `secrets/ui.json`, matching `UiConfig`: API base URL/issuer/audience, gateway backchannel URL/issuer/assertion audience/JWKS URL, a service credential of at least 32 characters, approved login URL and bounded UI limits. All identity endpoints require HTTPS. HTTP API access is allowed only to loopback in local/test/research environments; shared deployment uses HTTPS with certificate verification. The workspace never reads database credentials, bundle locations, model files or the API artifact key.

The approved gateway authenticates users through its supported authorization-code/BFF session flow, obtains their short-lived access token for the API’s exact audience, and issues a high-entropy opaque child session handle for each workspace connection. It must strip user-supplied `X-Mule-Session`, inject exactly one trusted handle into the WebSocket connection, and prevent direct access to the UI origin. The handle alone supplies no role or subject claim.

`GatewayTokenProvider` generates a fresh random workspace binding and calls `POST {gateway_url}/resolve` over a certificate-verified, redirect-disabled backchannel. Only the protected gateway service credential goes to this endpoint. The body contains `session_handle`, `session_binding` and the requested API audience. The gateway must atomically bind a handle to its first workspace binding; another connection cannot rebind or resolve that handle. Multiple tabs need distinct child handles. Email, role and scope headers cannot replace this contract.

The successful response contains `access_token` and a signed assertion. RS256/ES256 assertions must have a unique configured JWKS key ID and these claims:

| Claim | Meaning |
| --- | --- |
| `iss`, `aud` | Configured gateway issuer and workspace assertion audience. |
| `sub` | Exact subject used by the organization API issuer for this user. |
| `exp`, `iat`, `jti` | Issued assertion, expiring within 60 seconds; gateway-owned identity. |
| `session_binding` | The exact fresh workspace binding supplied on the backchannel. |
| `api_token_sha256` | SHA-256 of the returned API access token. |
| `api_issuer`, `api_audience` | Exact configured API trust context. |
| `api_expires_at` | Actual API token expiry, at most one hour away and more than five seconds away. |

The provider validates signature, issuer, audience, time, binding, token hash and trust context before accepting the credential. It derives the issuer-bound opaque actor ID expected by the API and verifies it against authenticated `/v1/me`. The API independently validates the access token and supplies effective permissions and permission-bound scopes. A refresh cannot silently switch subjects. Tokens are held only in the server-side provider object, redacted from reprs and never put in URLs, widgets, global data caches or evidence logs.

The provider renews through the gateway at most every 30 seconds or sooner at assertion/token expiry. `POST {gateway_url}/logout` receives the same session handle/binding and service authentication; the gateway must revoke the child session and its usable token/session state. Local logout clears cached reads, pending sensitive payloads, widget state and selections even if the gateway is unavailable, and blocks automatic reuse in that UI session. Configure gateway logout/identity cookies so a new sign-in creates a fresh child handle.

The gateway is an organization service contract, not an included mock login service. Its deployment, routing, token exchange and session revocation require identity-owner integration and verification. Shared deployment remains blocked until those are supplied. Tests use explicit isolated signed fixtures and prove wrong audience, altered binding/hash, expiry, replay to another workspace and spoofed identity denial.

## FE-3 expiry recovery

On 401/expired identity the workspace clears credentials, private caches, opened case records and widgets. Only an unresolved PENDING/UNKNOWN/CONFLICT request may remain in that same server-side Streamlit session, hidden behind the login gate. Its original key, payload and actor/permission/scope/configuration fingerprint are retained; no automatic POST occurs. After a fresh gateway login, “Resume authenticated session” validates `/v1/me` again. A matching fingerprint can restore the request for an explicit same-key retry; a different actor, scope, effective permission set or trust configuration discards it. Conflict recovery refetches current case state. Explicit sign-out discards the draft; the expiry screen also offers an explicit discard/sign-out control.

Recovery is session-memory-only. A browser refresh that creates a new Streamlit session or a server restart can lose an unacknowledged draft. Durable cross-session recovery is not claimed by this foundation. The API's idempotency store remains the authority for an action that may already have committed.

The isolated `ui.mock` service signs fixture tokens with a fresh ephemeral RSA key and verifies them at its HTTP boundary. Normal runtime rejects `mock_mode`; there is no fallback after a production authentication or network error. `python -m ui.dev` binds to loopback and displays “MOCK DATA / FIXTURE IDENTITY (TEST ONLY)”. This development service cannot establish organization identity or production readiness.
