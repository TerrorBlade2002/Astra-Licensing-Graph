# Human handoff workflow

Human handoffs persist a pause without keeping a worker lease or database lock open. Supported handoffs include login, terms, MFA, CAPTCHA, sensitive field, attestation, signature, payment, final submit, portal error, and unexpected page.

The assigned person accepts the handoff using their own Astra identity and their own authorized portal account. Login, terms, MFA, CAPTCHA, and other browser-bound handoffs remain tied to the original session owner. A different person cannot inherit that session.

Generic browser handoffs are not complete when a user clicks “done.” A new reconciliation job verifies the resulting reviewed page contract. Attestation, payment, and final submission use dedicated evidence APIs and cannot be completed through the generic endpoint.

Declining or allowing a handoff to expire blocks the run. A worker never waits synchronously for a person. Passwords, one-time codes, CAPTCHA content, payment data, signatures, cookies, tokens, and browser state must never be entered into Astra.

