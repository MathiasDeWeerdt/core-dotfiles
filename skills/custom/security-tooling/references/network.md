# Network and identity audits

| Audit question | Minimum useful inputs | What can change the conclusion |
| --- | --- | --- |
| Is a service reachable across a boundary? | Owner's allowed-flow matrix, effective firewall or cloud policy, route/NAT mapping, source zone and dated connection or flow record | Include direction, protocol, port, IPv4/IPv6 and observation point. A listener establishes local service state. A flow record adds path evidence. Sampling, asymmetric routing and missing deny logs limit conclusions. |
| Does the inventory cover the environment? | Asset inventory, existing Nmap XML, completion record, scanned ports and vantage points | A filtered port, a closed port and an omitted port have different meanings. A load balancer can mask multiple backends. Deduplicate only after reconciling addresses with stable asset IDs. [Nmap XML](https://nmap.org/book/output-formats-xml-output.html) |
| Does a Windows file service enforce the intended policy? | OS edition/build, effective client and server SMB signing requirements, session or audit evidence | Check inbound and outbound policy independently. A signed session shows negotiation on that connection. A requirement in policy establishes enforcement for that role. Signing and encryption are separate controls. [Microsoft SMB signing](https://learn.microsoft.com/en-us/windows-server/storage/file-server/smb-signing-overview) |
| Is directory traffic protected? | Effective LDAP signing and channel-binding settings, client compatibility and dated domain controller events | Record the bind mechanism, whether TLS is in use and whether the deployment is in audit or enforcement mode. A quiet log needs a known collection window and policy. [Microsoft LDAP guidance](https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/ldap-signing) |
| Is hardening consistent with the agreed baseline? | Platform-specific CIS Benchmark and profile, OS edition, configuration export and documented exceptions | Separate effective settings from defaults. Record inherited policy and sampling. Identify manual checks and errors in an automated profile report. [CIS Controls v8.1](https://www.cisecurity.org/controls/v8-1) · [Benchmarks](https://www.cisecurity.org/cis-benchmarks) |

## Read packet and inventory evidence locally

```sh
capinfos -c -a -e -l capture.pcapng
tshark -n -r capture.pcapng -q -z io,phs
xmllint --nonet --xpath 'string(/nmaprun/runstats/finished/@exit)' inventory.xml
xmllint --nonet --xpath 'count(/nmaprun/host/ports/port[state/@state="open"])' inventory.xml
```

The first two commands summarize a saved capture. The second disables name resolution. Check capture duration, interfaces, snap length and drops when recorded. Encryption, truncation and capture placement can hide application data. Keep precise frame numbers in restricted notes. The XML count includes explicitly listed open port elements. Inspect aggregated states in extraports, host discovery results and scaninfo before reporting totals. Use a trusted local XML parser with external entity substitution disabled. [capinfos manual](https://www.wireshark.org/docs/man-pages/capinfos.html) · [TShark manual](https://www.wireshark.org/docs/man-pages/tshark.html)

## Verify supplied certificate files

```sh
openssl x509 -in leaf.pem -noout -subject -issuer -dates -ext subjectAltName
openssl verify -no-CApath -no-CAstore -CAfile roots.pem -untrusted intermediates.pem \
  -purpose sslserver -verify_hostname service.example.test leaf.pem
```

Use the expected service name and the relying party's approved trust anchors. The example checks the available path, time, purpose and hostname with OpenSSL's verification rules. Review the SAN for the identifier type the client requires. For an IP identity use the IP verification option. Revocation status, deployed chain, protocol versions, cipher negotiation and the behavior of another client each need separate evidence. Note whether the certificate came from an edge or backend. [OpenSSL verification](https://docs.openssl.org/master/man1/openssl-verify/) · [TLS deployment guidance](https://www.rfc-editor.org/rfc/rfc9325) · [Service identity](https://www.rfc-editor.org/info/rfc9525/)

## Cloud network and workload controls

For a cloud trust boundary, pair the resource policy with the organization/account boundary and the applicable identity and network controls. An AWS IAM Access Analyzer external access finding identifies a policy-based path outside the configured zone of trust. Establish who used it from audit logs. Record the analyzer type, region, archive rules and collection time before making a coverage claim. [AWS IAM Access Analyzer](https://docs.aws.amazon.com/IAM/latest/UserGuide/what-is-access-analyzer.html)

For Kubernetes, inspect a supplied namespace export and the actual workload admission records. Pod Security Admission has independent enforce, audit and warn modes. Record mode, level, version, exemptions and workload creation time. A namespace label by itself cannot establish that all running workloads passed that policy. This local query reports configured Pod Security labels from a NamespaceList. Check cluster defaults and exemptions separately. [Kubernetes Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/)

```sh
jq -c '.items[] | {namespace:.metadata.name, policy:((.metadata.labels // {}) | with_entries(select(.key | startswith("pod-security.kubernetes.io/"))))}' namespaces.json
```
