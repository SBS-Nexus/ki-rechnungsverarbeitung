# Nexus browser authentication

Nexus browser sessions require an independently generated
`NEXUS_AUTH_SIGNING_KEY` of at least 32 random bytes in the service environment.
Missing configuration rejects authentication with HTTP 503.
Do not reuse a source-code example or a human password as this key.

The existing `sbs_<user-id>_<token>` transport shape remains compatible with
clients that store and forward tokens. Tokens are now signed, expire after
eight hours, and become invalid after password changes. Existing unsigned
tokens require a fresh login after deployment. Every protected request also
checks the current account's active, verified and administrator status.
Public registration always creates an unverified non-admin account.
Administrator provisioning remains an explicit operator action.

The router authorizes administrative operations and binds user-specific
statistics/notifications to the authenticated account. Unclassified routes
fail closed. Machine endpoints retain their separate API-key checks and
existing inference/organization policy; browser tokens do not bypass these.

Validation uses generated keys, synthetic SQLite accounts, mocked email
transports and the actual router's dependency declaration. No production
accounts, mail, AI providers or databases are used. This does not claim a full
authorization audit of every legacy web route or a production deployment.
