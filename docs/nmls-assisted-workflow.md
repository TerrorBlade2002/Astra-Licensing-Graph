# NMLS assisted workflow

The NMLS adapter is a supervised boundary for reviewed MU1, MU2 company-preparation, MU3, and renewal workflows. It is not a credential vault or filing bot.

1. A portal administrator registers the exact NMLS hostname, reviews current terms and security constraints, and approves a limited automation level.
2. An administrator activates a fixture-tested `nmls-assisted` adapter version and authorizes individual users for specific entities and filing types.
3. An analyst creates a run from a Milestone 6 case in `SUBMISSION_PENDING`, pinning the approved form and packet.
4. The assigned operator starts an isolated session and personally completes login, MFA, CAPTCHA, and terms handoffs.
5. Astra enters only reviewed fields, uploads only current approved entity-matched documents, and captures portal validation.
6. A reviewer approves the exact pre-submission snapshot.
7. A signatory personally completes any attestation or signature. A payment approver reviews the fee and pays outside Astra.
8. An authorized person performs the final submit action. Astra records and reconciles the resulting evidence without retrying an ambiguous action.

Submission evidence moves the compliance case to submitted-to-regulator or submitted-to-vendor and creates a follow-up deadline. It does not mark a license renewed, an obligation satisfied, or a filing accepted.

