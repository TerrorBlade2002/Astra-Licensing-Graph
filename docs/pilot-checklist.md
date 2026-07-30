# Pilot checklist (Milestone 8)

The pilot is the first real work done in production, deliberately small. It
uses the existing environment flags and scoped data — there is no pilot
dashboard and no feature-flag table.

## Scope

Fill this in before the first real case and do not widen it mid-pilot.

| Item | Value |
| --- | --- |
| Legal entity (one) | |
| Licences in scope (small set) | |
| Jurisdictions in scope | |
| Licensing vendor (one) | |
| Bond provider (if relevant) | |
| Approved portal (at most one) | |
| Pilot users | |
| Start date / planned end date | |

Everything outside this list stays on the manual process.

## Daily routine during the pilot

- [ ] Check `GET /api/v1/operations/status` — no critical alert, fresh worker
      heartbeat, recent scheduler run
- [ ] Keep updating the existing manual tracker in parallel
- [ ] Compare every system deadline with the manual deadline
- [ ] Compare every generated packet against what would have been sent manually
- [ ] Review **every** classification result
- [ ] Review **every** outbound email before approval
- [ ] Confirm every filing was submitted by a person

## Comparison log

| Date | Case / licence | System result | Manual result | Match | Action |
| --- | --- | --- | --- | --- | --- |
| | | | | ☐ | |

## Stop conditions

Pause the pilot (disable processing flags, keep the portal readable, resume the
manual process) and investigate if any of these occur:

- [ ] Work attributed to the wrong legal entity
- [ ] An incorrect deadline or a missed statutory date
- [ ] An email sent without the required approval
- [ ] A duplicate email to a regulator or vendor
- [ ] A wrong or outdated document in a packet or upload
- [ ] Missing audit history for an action
- [ ] Any portal action beyond the approved scope

Record the stop, the cause, the fix, and the restart decision:

| Date | Stop condition | Cause | Fix | Restart approved by |
| --- | --- | --- | --- | --- |
| | | | | |

## Exit criteria

- [ ] At least one full renewal or filing completed end to end
- [ ] No unexplained difference between system and manual deadlines
- [ ] No stop condition open
- [ ] Users confident in the review, approval, and packet steps
- [ ] Process owner approves widening scope: __________________ (name, date)

Widen the scope one dimension at a time — more licences, then more
jurisdictions, then more users — checking the comparison log after each step.
