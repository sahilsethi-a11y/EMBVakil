# Law Agent Contract Review

- **Document type:** `nda`
- **Overall risk:** `high`
- **Findings by severity:** high=5, med=2, low=0

## Summary

This is a mutual non-disclosure agreement (NDA) between Eagles Communication Consultancy (ECC) and another company or individual, providing for the exchange of confidential information to evaluate business opportunities. The review found several high-risk issues: the indemnity and liability provisions are one-sided (primarily favoring ECC), exposing the Company/Individual to uncapped and unilateral risk; indemnity is not mutual or capped as per company playbook; and assignment is prohibited without the flexibility typically allowed by modern standards. Some medium risks remain, such as lack of mutual reservation of rights upon termination. The governing law is UAE, which matches company preference. The contract would require significant revisions for risk balance and to comply with best practices.

## Findings

- **CL-037 | HIGH | Indemnity is one-way (only Recipient indemnifies Disclosing Party) and not mutual.**
  - Why: Playbook requires mutual indemnity with balanced scope. This clause provides only a one-way indemnity, meaning asymmetric risk for Recipient.
  - Excerpt: `The Recipient shall indemnify and keep fully indemnified the Disclosing Party at all times...`
  - Recommendation: Revise to mutual indemnity so each party indemnifies the other for standard categories (e.g., negligence, willful misconduct, breach).
  - Suggested edit: Each party will indemnify, defend, and hold harmless the other party from third-party claims arising from its negligence, willful misconduct, or breach of this Agreement.
- **CL-038 | HIGH | Indemnity provision is one-sided; only Recipient indemnifies Disclosing Party.**
  - Why: Lacks mutual indemnity. Playbook requires reciprocal indemnity to ensure balanced risk distribution between parties.
  - Excerpt: `The Recipient shall indemnify and keep fully indemnified the Disclosing Party at all times against all`
  - Recommendation: Revise to require mutual indemnity covering each party's negligence, willful misconduct, and breach, with standard defense and settlement controls.
  - Citations: 43c8a86b416e_EMB_Global_Convox_-_NDA__1___1_.pdf, 65b4db8e25f1_NDA_EMB_Convexicon.pdf, 890cfb63a88f_EMB_Global_Convox_-_NDA__1___1_.pdf
  - Suggested edit: Each party shall indemnify, defend, and hold harmless the other party against all losses or liabilities arising out of or in connection with any third-party claim to the extent caused by that party's negligence, willful misconduct, or breach of this Agreement. The indemnifying party shall have the right to control the defense and settlement of such claims, provided that no settlement imposing obligations on the indemnified party may be made without its prior written consent (not to be unreasonably withheld).
- **CL-039 | HIGH | Indemnity for open-ended costs (including legal costs) is not limited or mutual.**
  - Why: Indemnity covers all direct liabilities, costs, expenses, damages, and legal costs, but is not mutual and no liability cap is referenced, posing risk of uncapped exposure.
  - Excerpt: `direct liabilities, costs (including legal costs on an indemnity basis), expenses, damages and losses and`
  - Recommendation: Narrow indemnity to a mutual structure with liability caps or carve-outs for fraud/willful misconduct; include a balance of legal cost recovery.
  - Citations: 43c8a86b416e_EMB_Global_Convox_-_NDA__1___1_.pdf, 65b4db8e25f1_NDA_EMB_Convexicon.pdf, 890cfb63a88f_EMB_Global_Convox_-_NDA__1___1_.pdf
  - Suggested edit: Each party shall indemnify, defend, and hold harmless the other against direct liabilities, costs, and losses from third-party claims caused by that partys negligence, willful misconduct, or breach of this Agreement, subject to agreed liability caps.
- **CL-040 | HIGH | Indemnity is not mutual and is open-ended as to costs, covering any breach by Recipient or its Representatives.**
  - Why: Playbook requires mutual indemnity with narrow triggers. This clause gives only the Disclosing Party a right to uncapped indemnity from Recipient, but not vice versa.
  - Excerpt: `any breach of this Agreement by the Recipient or its Representatives.`
  - Recommendation: Revise for mutual and balanced indemnity (for both parties, for specific triggers only, not 'any breach') and subject to liability caps.
  - Citations: 43c8a86b416e_EMB_Global_Convox_-_NDA__1___1_.pdf, 65b4db8e25f1_NDA_EMB_Convexicon.pdf, 890cfb63a88f_EMB_Global_Convox_-_NDA__1___1_.pdf
  - Suggested edit: Each party will indemnify, defend, and hold harmless the other party from third-party claims arising from its negligence, willful misconduct, or breach of this Agreement, subject to standard liability caps.
- **CL-048 | HIGH | Uncapped and one-sided liability for breachonly applies to the Company/Individual, not ECC.**
  - Why: Clause exposes the Company/Individual to uncapped liability for all losses suffered by ECC. Playbook requires mutual, capped liability with narrow carve-outs.
  - Excerpt: `COMPANY or INDIVIDUAL / PERSON shall be legally liable... and compensate ECC against its loss...`
  - Recommendation: Revise so liability is mutual, subject to a cap (fees paid in prior 12 months), with carve-outs for fraud, willful misconduct, breach of confidentiality.
  - Citations: 190fc965ae05_Mutual_NDA_-_Girnar_Soft____EMB_Global.docx__1__signed__1_.pdf, 351656a9d59d_Mutual_NDA_-_Girnar_Soft____EMB_Global.docx__1__signed__1_.pdf, aaf537eff8fb_NDA_EMB_Brainvire_-_with_BVI_comments.docx
  - Suggested edit: Except for fraud, willful misconduct, or breach of confidentiality, each party's aggregate liability will not exceed fees paid or payable in the 12 months before the claim, and shall apply mutually to both parties.
- **CL-045 | MED | Accrued rights and remedies preserved only for Disclosing Party, not mutual.**
  - Why: Grants exclusive benefit to one party rather than both. Playbook expects mutual reservation of rights to accrued remedies.
  - Excerpt: `Termination of this Agreement shall not affect any accrued rights or remedies to which the Disclosing Party is entitled.`
  - Recommendation: Clarify that termination does not affect accrued rights or remedies of either party (not just Disclosing Party).
  - Citations: 190fc965ae05_Mutual_NDA_-_Girnar_Soft____EMB_Global.docx__1__signed__1_.pdf, 351656a9d59d_Mutual_NDA_-_Girnar_Soft____EMB_Global.docx__1__signed__1_.pdf, aaf537eff8fb_NDA_EMB_Brainvire_-_with_BVI_comments.docx
  - Suggested edit: Termination of this Agreement shall not affect any accrued rights or remedies to which either party is entitled.
- **CL-047 | MED | Assignment is prohibited except as otherwise provided, but no allowance for assignment with consent.**
  - Why: Playbook requires that assignment be allowed with prior written consent (not unreasonably withheld), and with exception for merger/sale with notice. This clause does not explicitly allow assignment upon consent or in a change-of-control event.
  - Excerpt: `no party may assign, sub-contract or deal...under this Agreement...`
  - Recommendation: Update to permit assignment with prior written consent and an exception for merger or sale of substantially all assets with notice, per company standard.
  - Citations: 351656a9d59d_Mutual_NDA_-_Girnar_Soft____EMB_Global.docx__1__signed__1_.pdf, aaf537eff8fb_NDA_EMB_Brainvire_-_with_BVI_comments.docx, b3c1460c0595_NDA_EMB_Brainvire_-_with_BVI_comments.docx
  - Suggested edit: Neither party may assign this Agreement without prior written consent of the other party, except to a successor in connection with merger or sale of substantially all assets with written notice.

## Assumptions

- Counterparty name and effective date are not filled in the template.
- ECC is based in Abu Dhabi, UAE.
- The NDA is to last 5 years from signing, with confidentiality for 3 years after early termination.
- Contact info extracted from ECC's signature block.
- Signatory for ECC is Mahmoud Sayed Ahmad.
- Input may contain concentrated personal data. Review output handling carefully.

## Missing Information Questions

- Are there any side letters or amendments not included in this text?
- Is this agreement intended to be mutual or one-way for confidentiality and indemnity obligations?

## Disclaimer

This output is an AI-assisted review and is not legal advice.
