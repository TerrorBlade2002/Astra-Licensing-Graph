# Cloudflare R2 document storage

SharePoint remains the governed repository of record. R2 exists so document
content has somewhere safe to live when SharePoint is unavailable or not yet
provisioned — production forbids the filesystem backend, and an outage should
not stop licensing work.

Switching backends changes **where bytes are stored**, not how documents are
governed. The catalog, approval lifecycle, version history, hashes, and access
rules are unchanged; every document still goes through the same review.

## Provisioned

| Item | Value |
| --- | --- |
| Account | `astraglobal247@gmail.com` (`fca70e2a0201ba8c149d3c7ad1978e95`) |
| Bucket | `astra-licensing-documents` |
| Created | 2026-07-30 |
| Endpoint | `https://<account-id>.r2.cloudflarestorage.com` |

Recreate with:

```bash
npx wrangler r2 bucket create astra-licensing-documents
```

## Credentials

R2 uses S3-compatible credentials, created in the Cloudflare dashboard under
**R2 → Manage R2 API Tokens**. Create a token scoped to *Object Read & Write*
for this bucket only — not an account-wide token.

The token screen shows an **Access Key ID** and a **Secret Access Key**. The
secret is displayed once. Put both directly into the deployment's variable
editor; they must never be committed, pasted into chat, or added to any
frontend variable.

| Variable | Value |
| --- | --- |
| `EVIDENCE_STORAGE_BACKEND` | `r2` |
| `R2_ACCOUNT_ID` | Cloudflare account ID |
| `R2_BUCKET` | `astra-licensing-documents` |
| `R2_ACCESS_KEY_ID` | from the token screen |
| `R2_SECRET_ACCESS_KEY` | from the token screen |

Set them on `backend`, `worker`, and `browser-worker` — every service that
writes evidence. The frontend needs none of them.

Startup refuses to run with `EVIDENCE_STORAGE_BACKEND=r2` unless all four are
present, so a half-configured store fails at deploy rather than at the moment
a document is uploaded.

## Behaviour

- Uploads stream: content is hashed while it is written, so the recorded
  SHA-256 is of the bytes actually stored.
- The size limit is enforced mid-stream; an oversized object is abandoned
  before it completes rather than deleted afterwards.
- A failed part aborts the multipart upload, so no partial object is left
  behind to look like a complete evidence record.
- Object keys are validated: a traversal segment is rejected rather than
  normalised.
- Storage URIs are recorded as `r2://<bucket>/<key>`.

## Verifying

```bash
curl -s "$BACKEND_URL/api/v1/integrations/storage/status"
```

Reports the active backend, the bucket, and whether credentials are present.
It never returns a key, a secret, or a signed URL.

The portal shows the same information on the documents page, so an operator
can tell at a glance whether they are looking at a SharePoint-backed or
R2-backed repository.

## Switching back to SharePoint

Set `EVIDENCE_STORAGE_BACKEND=sharepoint` and redeploy. Documents already
written to R2 keep their `r2://` URIs and stay readable as long as the R2
variables remain configured; new content goes to SharePoint. There is no
automatic migration of existing objects between backends.
