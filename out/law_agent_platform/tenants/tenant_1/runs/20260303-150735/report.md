# Law Agent Contract Review

- **Document type:** `nda`
- **Overall risk:** `med`
- **Findings by severity:** high=0, med=1, low=0

## Summary

A mutual non-disclosure agreement (NDA) to protect confidential information shared between two parties, detailing obligations, exclusions, duration, severability, and notice requirements.

## Findings

- **CL-001 | MED | Confidentiality term is not compliant with playbook minimum duration for business confidential information.**
  - Why: Clause allows confidentiality obligations to end earlier than 3 years upon written notice from Disclosing Party, while playbook expects at least 3 years minimum duration for standard business confidential info.
  - Excerpt: `duty to hold Confidential Information in confidence shall remain in effect until the Confidential Information no longer qualifies as a trade secret or until Disclosing Party sends...`
  - Recommendation: Revise to ensure confidentiality period for standard confidential information is at least 3 years or longer as required for trade secrets, regardless of early release by Disclosing Party.
  - Citations: 43c8a86b416e_EMB_Global_Convox_-_NDA__1___1_.pdf, 890cfb63a88f_EMB_Global_Convox_-_NDA__1___1_.pdf, aaf537eff8fb_NDA_EMB_Brainvire_-_with_BVI_comments.docx
  - Suggested edit: Confidentiality obligations survive for 5 years after termination, and trade secret obligations survive for as long as the information remains a trade secret.

## Assumptions

- No party names or specific dates were provided in the contract text. Signature blocks are blank.
- The contract appears to be a standard NDA template, and no referenced organizations or individuals could be extracted.

## Missing Information Questions

- Are there any side letters or amendments not included in this text?
- Is this agreement intended to be mutual or one-way for confidentiality and indemnity obligations?

## Disclaimer

This output is an AI-assisted review and is not legal advice.
