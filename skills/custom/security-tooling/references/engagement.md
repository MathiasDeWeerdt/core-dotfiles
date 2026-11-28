# Engagement, evidence and retest

## Choose the framework for the question

| Purpose | Reference | What to record |
| --- | --- | --- |
| Plan an assessment | NIST SP 800-115 (2008) | Use its planning and rules-of-engagement material for owner, boundaries, permitted activities, incident contact, reporting and handling. Use current product guidance for technical settings. [NIST SP 800-115](https://csrc.nist.gov/pubs/sp/800/115/final) |
| Explain which business outcomes a gap affects | NIST CSF 2.0 and the organization's Current and Target Profiles | Record the affected outcome, asset, owner and remediation decision. A sample of technical controls supports a bounded conclusion. [NIST CSF](https://www.nist.gov/cyberframework) |
| Assess a platform or application | A product-specific CIS Benchmark or versioned ASVS requirement | Record edition, selected profile or level, applicability and tested population. A CIS Controls safeguard, a Benchmark setting and an ASVS requirement serve different purposes. [CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks) · [ASVS](https://asvs.owasp.org/) |
| Payment-card engagement | The applicable PCI DSS edition and the customer's defined cardholder data environment | Confirm scope, dependencies, segmentation assumptions, assessor role and expected deliverables with the owner. Use the standard's applicable testing procedures for the contracted work. [PCI SSC document library](https://www.pcisecuritystandards.org/document_library/) |

## Make control coverage visible

Use one row per control and relevant context, such as build, role, tenant or network zone. Define the denominator. If 8 of 12 in-scope flows have usable records and 2 of those 8 fail, report 6 pass, 2 fail and 4 unassessed. A tool error, denied log access or truncated capture can make a result inconclusive. Give the reason. The [notes template](../assets/assessment-notes.md) separates scope, coverage, evidence and findings.

Give each finding a stable ID. Record the expected behavior, exact observation, affected asset/build, strongest alternative explanation, confidence, impact, owner and retest criterion. Merge repeated observations only when the boundary, control failure and remediation owner match. Keep each affected instance and its evidence. Separate false positive, duplicate, accepted risk and fixed. They imply different follow-up.

## Protect and bind evidence

Put original files in the approved restricted store. Use opaque references, redacted derivatives and precise locators in ordinary notes. Review HAR headers and bodies, URLs with query parameters, screenshots, PCAP comments, embedded decryption secrets and scanner output before disclosure. When the agreement specifies retention, record the expiry and owner. A checksum checks byte identity. Establish provenance with source, acquisition time and custodian.

For findings that will be handed over or retested, the optional checker reads a local JSON register and a protected evidence directory. It streams each referenced file once, checks its SHA-256 and binds the finding ID, asset ID, claim, retest criterion, file names, locators and expected hashes into a review fingerprint. It prints IDs and status. It does not inspect the meaning of the evidence. Use a reviewed redacted file if raw evidence cannot be read in the assessment environment.

Example register shape. Replace the example digest with the value from the actual artifact.

```json
{
  "version": 1,
  "findings": [{
    "id": "F-003",
    "asset": "edge-prod",
    "claim": "The supplied edge certificate was expired at the time of observation.",
    "criterion": "The deployed certificate is within its validity period at retest.",
    "evidence": [{
      "file": "tls/edge-summary.txt",
      "locator": "certificate validity, lines 3-4",
      "sha256": "REPLACE_WITH_64_LOWERCASE_HEX_DIGITS"
    }]
  }]
}
```

```sh
sha256sum protected/tls/edge-summary.txt
node "$skill/scripts/check-evidence.mjs" findings.json protected
```

On first review the checker prints a fingerprint and reports “awaiting review.” Inspect the cited location, compare it with the claim, and record that fingerprint as `reviewedAgainst` on the finding. A later check reports a changed file, unavailable evidence or a review that predates a change to the claim, retest criterion or evidence binding. Keep the old register with the original report when evidence changes. Exit 0 means all bindings match a recorded review. Exit 1 identifies outstanding review work. Exit 2 indicates invalid input. The checker covers the claim and criterion stored in the register. Compare any separately edited report against that wording. A reviewer's signature or access-control system is a separate trust decision.

On retest, record the new build, vantage point, expected result and observed result. Compare them with the original. If the affected route disappeared or the account changed, establish equivalence or leave the result inconclusive.
