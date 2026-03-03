# Law Agent Contract Review

- **Document type:** `nda`
- **Overall risk:** `med`
- **Findings by severity:** high=0, med=1, low=0

## Summary

A mutual confidentiality agreement (NDA) between JATO Dynamics Limited and MANTARAV DIGITAL INFORMATION TECHNOLOGY CONSULTANCY - SOLE PROPRIETORSHIP L.L.C., governing the treatment of confidential information exchanged for discussions and evaluation of JATO's products and services.

## Findings

- **CL-002 | MED | Governing law and jurisdiction are England and Wales, not Delaware, New York, or California as required by the playbook.**
  - Why: The agreement specifies the laws of England and Wales and English courts, which does not align with the preferred U.S. jurisdictions in the playbook.
  - Excerpt: `The laws of England and Wales govern this agreement and its construction.`
  - Recommendation: Request to change governing law and jurisdiction to Delaware, New York, or California, or add an alternative that meets mutual interests.
  - Citations: 43c8a86b416e_EMB_Global_Convox_-_NDA__1___1_.pdf, 890cfb63a88f_EMB_Global_Convox_-_NDA__1___1_.pdf
  - Suggested edit: This Agreement is governed by the laws of Delaware, and any action may be brought in state or federal courts located in Wilmington, Delaware.

## Assumptions

- 'Client' determined from signature details and company info provided in the signature block.
- Parties extracted from both the named fields and the executed signature section.
- The primary effective date is assumed as 2026-02-09, matching signatures and audit trail.
- Governing law is England and Wales as specified in the General provisions.
- Input may contain concentrated personal data. Review output handling carefully.

## Missing Information Questions

- Are there any side letters or amendments not included in this text?
- Is this agreement intended to be mutual or one-way for confidentiality and indemnity obligations?

## Disclaimer

This output is an AI-assisted review and is not legal advice.
