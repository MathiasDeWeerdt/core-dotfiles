# Software inventory and vulnerability triage

## From artifact to decision

1. Identify the assessed build by image digest, release artifact hash or revision plus lockfile hash. A source checkout can include development dependencies and omit files from the deployed image. Record the OS distribution, architecture, package ecosystem and cataloger warnings.
2. Generate or obtain the SBOM. Keep its schema, inventory tool version, timestamp and component identifiers. A missing package may reflect limited cataloger coverage. A package URL identifies a component. A file path can distinguish multiple installed copies. [Syft SBOM guide](https://oss.anchore.com/docs/guides/sbom/) · [CycloneDX specification](https://www.cyclonedx.org/specification/overview/)
3. Match the affected package and build with the **distribution or vendor advisory**. Check the fixed revision, backports, vulnerable feature, runtime use, exposure and owner. Record the scanner database time. Treat supplier VEX as an assertion with an issuer, product identity, status, justification and date. Check that it covers this build. [CycloneDX VEX](https://www.cyclonedx.org/capabilities/vex/)
4. Record technical severity, exploitation evidence and business priority separately. FIRST CVSS v4.0 supplies severity and its vector. CISA KEV records known exploitation. FIRST EPSS estimates exploitation probability over the next 30 days. Save the EPSS score date and distinguish the probability from its percentile. An unlisted CVE or missing score leaves uncertainty. Use the organization's exposure, criticality and remediation policy to set action and due date. [CVSS](https://www.first.org/cvss/v4.0/) · [CISA KEV data](https://github.com/CISAGov/kev-data) · [EPSS](https://www.first.org/epss/)

## Inspect a supplied artifact

Work in the approved evidence directory. Use new output paths outside the assessed input tree. These examples assume the installed Syft and Trivy support the listed options. The example scan uses the existing Trivy database. Populate the database separately if needed, then record its update timestamp with `trivy --version`. A failed or stale database lookup needs a coverage limitation. Third-party SBOMs can omit vendor-specific package metadata that improves Trivy matching. [Trivy SBOM support](https://trivy.dev/docs/latest/target/sbom/) · [Air-gap operation](https://trivy.dev/docs/latest/advanced/air-gap/)

```sh
SYFT_CHECK_FOR_APP_UPDATE=false syft scan dir:./release-tree -o cyclonedx-json=inventory.cdx.json &&
jq -e 'if ((.components // []) | length) == 0 then error("No top-level components. Check input and cataloger coverage.") else {format:.bomFormat, schema:.specVersion, top_level_components:(.components|length)} end' inventory.cdx.json &&
trivy sbom --scanners vuln --offline-scan --skip-db-update --skip-java-db-update \
  --disable-telemetry --skip-version-check --skip-vex-repo-update --format json --output matches.json inventory.cdx.json &&
jq -r '[.Results[]?.Vulnerabilities[]?] | group_by(.Severity)[] | [.[0].Severity,length] | @tsv' matches.json
```

If the inventory check fails, stop before using the scan summary. For example, a malformed lockfile can produce an empty SBOM with a successful Syft exit. Compare the component list against known packages in this build. The summary counts scanner matches. A single CVE can appear in multiple packages or locations. First verify that cataloging found the expected package types and that the scanner processed them. A zero count on an unrecognized artifact is inconclusive.

For a client-provided KEV snapshot, use the CVE from the finding and inspect the catalog date as well as the matching row. The lookup runs locally.

```sh
jq --arg id "$cve_id" '{catalogVersion,dateReleased,matches:[.vulnerabilities[] | select(.cveID==$id) | {cveID,dateAdded,requiredAction}]}' kev.json
```

For remediation, bind the retest to the replacement artifact digest. Verify that the vulnerable component was removed, updated or covered by a justified mitigation. Record the scanner and database version again. A changed database alone can change the result for identical artifact bytes.

## Build provenance and CI/CD

For a released binary or image, compare its digest with the attestation subject. Validate the attestation using the expected signer or workload identity, repository, builder and workflow. Inspect the source revision and build inputs covered by the attestation. Record how deployment selects that artifact. A valid signature establishes the identity and integrity claims encoded in the attestation. Dependency safety and review of the build configuration need separate evidence. [SLSA 1.2](https://slsa.dev/spec/v1.2/) · [GitHub artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
