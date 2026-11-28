# Application and API reviews

## Choose the acceptance criterion

Record the deployed build, user or service roles, tenant boundaries, relevant data classes and which controls the owner expects. Use versioned ASVS requirements as acceptance criteria. WSTG provides review scenarios. The Web Top 10 (2025) and API Top 10 (2023) help identify omissions in scope. A category label alone cannot establish a control failure. [ASVS 5.0.0](https://asvs.owasp.org/downloads/) · [WSTG 4.2](https://wstg.owasp.org/v4.2/) · [Web Top 10](https://top10.owasp.org/2025/) · [API Top 10](https://api-security.owasp.org/editions/2023/en/0x11-t10/)

| Review question | Evidence to pair | Decision |
| --- | --- | --- |
| Does each role have the intended access? | Owner's role × operation × resource matrix, server policy and existing integration-test records with synthetic accounts | Assess function, object and field permissions separately. For tenant-specific data, record both tenant contexts. ASVS v5.0.0-8.2.2 applies to object access. v5.0.0-8.2.3 applies to fields. v5.0.0-8.3.1 covers service-side enforcement. [Versioned requirements](https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0/5.0/en/0x17-V8-Authorization.md) |
| Do session and identity controls cover recovery? | IdP/client configuration, login and recovery policy, session lifetime and revocation records | Check the assurance required by the service, the enrollment and recovery paths, and what happens to existing sessions after an account change. Compare MFA choices with the organization's phishing-resistance requirement. [NIST SP 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html) |
| Does the OAuth/OIDC deployment bind tokens to the intended client and service? | Registered redirect URIs, flow type, PKCE configuration, issuer, audiences and validation code | Map each client to its flow and document exceptions such as native loopback redirects. Review access-token and ID-token handling separately. Record the validator's algorithm allowlist and trusted issuers. [OAuth security BCP](https://www.rfc-editor.org/rfc/rfc9700) · [JWT BCP](https://www.rfc-editor.org/info/rfc8725/) |
| Are sensitive operations safe across retries and failures? | Owner-approved state diagram, transaction and idempotency rules, existing integration tests and redacted event IDs | Compare the allowed state changes with stored outcomes. Check whether a failed operation committed data or queued a side effect. Include retries, cancellation and asynchronous jobs in coverage. |
| Does browser behavior match policy? | Redacted response headers, cookie attribute names, response type, route, proxy/cache configuration and browser observation | Check authenticated and anonymous responses separately. Distinguish CSP report-only from enforcement and cache policy at the browser from behavior at a shared cache. Record where TLS terminates. |
| Can defenders investigate a sensitive operation? | Correlation ID, UTC, sanitized application event, actor and collector receipt | Verify the event reached the expected sink. Review access to logs and redact secrets, session identifiers and personal data before sharing examples. [OWASP logging guidance](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) |

## Inspect supplied files

For OpenAPI JSON, this local query lists **inline operations under paths**, including the additional method map in 3.2. It excludes path metadata and vendor extensions. A referenced path item, callback or webhook needs separate coverage. Resolve references from the supplied bundle. Treat network references as external inputs. Operation-level security overrides the root value, an empty list removes the inherited requirement, and an empty security object permits an anonymous alternative. Compare the contract with deployed routes and server policy. [OpenAPI 3.2.1](https://spec.openapis.org/oas/v3.2.1.html)

```sh
jq -r '
  .paths // {} | to_entries[] | .key as $path | .value | to_entries[] |
  if .key == "additionalOperations" then
    .value | keys[] | [., $path]
  elif (.key | IN("get","put","post","delete","options","head","patch","trace","query")) then
    [(.key | ascii_upcase), $path]
  else empty end | @tsv
' openapi.json
```

For a supplied HAR, summarize status codes before reading sensitive records. This emits counts only. Preserve the ordinal or exchange ID for selected evidence in restricted notes. Burp history and ZAP passive alerts cover the traffic that passed through them. ZAP Baseline starts a spider that sends requests. Record the actual acquisition method and visited roles before reporting coverage. [Burp analysis workflow](https://portswigger.net/burp/documentation/desktop/testing-workflow/analyzing) · [ZAP passive scanner](https://www.zaproxy.org/docs/desktop/addons/passive-scanner/) · [Baseline behavior](https://www.zaproxy.org/docs/docker/baseline-scan/)

```sh
jq -r '.log.entries | group_by(.response.status)[] | [.[0].response.status,length] | @tsv' history.har
```

For code supplied for review, trace a sensitive operation from its public handler through validation, policy, data access and audit logging. With Semgrep installed, use a reviewed local rules file against the supplied tree. Record the rule revision, ignored files, scan errors and languages covered. A rule match is a candidate until a reviewer checks the code and its calling context. [Semgrep CLI](https://docs.semgrep.dev/cli-reference)
