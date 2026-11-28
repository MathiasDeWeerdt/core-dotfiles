# Tool map

| Supplied artifact | Tool | What to record |
| --- | --- | --- |
| Packet capture | capinfos and TShark | Capture duration, interfaces, truncation and the frame number for each observation. Use a saved capture with name resolution disabled. |
| Service inventory XML | xmllint | Scan completion, source, port-state counts and any aggregated states. Record the Nmap version used by the producer. |
| Certificate and trust bundle | OpenSSL | Expected hostname, verification time, purpose, trust anchors and chain result. |
| OpenAPI JSON, HAR or saved proxy history | jq, ZAP or Burp Suite | Match the saved exchange to its route, role, response and build. Passive findings cover the traffic available to the tool. |
| Supplied source tree | Semgrep | Use reviewed local rules. Record their revision, analyzed languages and skipped files. Confirm each finding in the affected code. |
| Release tree or SBOM | Syft and Trivy | Component identity, artifact digest, catalog warnings, scanner database timestamp and vendor fix status. |
| SCAP content or results | OpenSCAP | Use `oscap info supplied.xml` to identify the document type, benchmark and profiles. In a result file, distinguish evaluated rules, errors and rules outside the selected profile. |
| Windows policy exports and audit events | Existing policy and event records | Match the effective policy, host role and event collection window. Use a protected reference for any sensitive fields. |

Record the tool and package version on the host that produced the result. A different viewer can help interpret a file, but its version only describes that review step.
