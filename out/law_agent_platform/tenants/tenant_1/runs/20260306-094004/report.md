# Law Agent Contract Review

- **Document type:** `nda`
- **Overall risk:** `high`
- **Findings by severity:** high=1, med=1, low=0

## Summary

A mutual NDA between Eagles Communication Consultancy (ECC) and another party (company or individual) for the purpose of evaluating a potential business relationship. Covers confidentiality obligations, indemnity, term, liability, notices, assignment, and governing law.

## Findings

- **CL-007 | HIGH | Uncapped and one-sided liability for breachonly applies to the Company/Individual, not ECC.**
  - Why: Clause exposes the Company/Individual to uncapped liability for all losses suffered by ECC. Playbook requires mutual, capped liability with narrow carve-outs.
  - Excerpt: `COMPANY or INDIVIDUAL / PERSON shall be legally liable... and compensate ECC against its loss...`
  - Recommendation: Revise so liability is mutual, subject to a cap (fees paid in prior 12 months), with carve-outs for fraud, willful misconduct, breach of confidentiality.
  - Citations: 190fc965ae05_Mutual_NDA_-_Girnar_Soft____EMB_Global.docx__1__signed__1_.pdf, 351656a9d59d_Mutual_NDA_-_Girnar_Soft____EMB_Global.docx__1__signed__1_.pdf, aaf537eff8fb_NDA_EMB_Brainvire_-_with_BVI_comments.docx
  - Suggested edit: Except for fraud, willful misconduct, or breach of confidentiality, each party's aggregate liability will not exceed fees paid or payable in the 12 months before the claim, and shall apply mutually to both parties.
- **CL-006 | MED | Assignment is prohibited except as otherwise provided, but no allowance for assignment with consent.**
  - Why: Playbook requires that assignment be allowed with prior written consent (not unreasonably withheld), and with exception for merger/sale with notice. This clause does not explicitly allow assignment upon consent or in a change-of-control event.
  - Excerpt: `no party may assign, sub-contract or deal...under this Agreement...`
  - Recommendation: Update to permit assignment with prior written consent and an exception for merger or sale of substantially all assets with notice, per company standard.
  - Citations: 351656a9d59d_Mutual_NDA_-_Girnar_Soft____EMB_Global.docx__1__signed__1_.pdf, aaf537eff8fb_NDA_EMB_Brainvire_-_with_BVI_comments.docx, b3c1460c0595_NDA_EMB_Brainvire_-_with_BVI_comments.docx
  - Suggested edit: Neither party may assign this Agreement without prior written consent of the other party, except to a successor in connection with merger or sale of substantially all assets with written notice.

## Assumptions

- Second party's name and details are not filled in the provided text; assumed template form.
- Signature blocks specify factual signatory details needed for execution.
- Document is clearly marked as a Non-Disclosure Agreement (NDA).
- Input may contain concentrated personal data. Review output handling carefully.

## Missing Information Questions

- Are there any side letters or amendments not included in this text?
- Is this agreement intended to be mutual or one-way for confidentiality and indemnity obligations?

## Disclaimer

This output is an AI-assisted review and is not legal advice.
