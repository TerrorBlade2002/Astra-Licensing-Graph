# Deployment reference

Last verified: 2026-08-03.

## Ownership and source

| Item | Location |
| --- | --- |
| GitHub repository | [TerrorBlade2002/Astra-Licensing-Graph](https://github.com/TerrorBlade2002/Astra-Licensing-Graph) |
| Deployment branch | `main` |
| Railway account | `astraglobal247@gmail.com` |
| Railway project | [astra-licensing](https://railway.com/project/c2858170-82ee-4b51-a255-3729e1c3b724) |
| Active environment | `staging` (`5de95bc2-0cb8-4b86-87b7-ea4449333d49`) |

GitHub `main` is the source of truth. Do not commit Railway tokens, database
credentials, or application secrets; keep them in Railway Variables.

## Staging services

| Service | Public URL / check | Railway service | Config |
| --- | --- | --- | --- |
| `frontend` | [Portal](https://frontend-staging-7f87.up.railway.app); [tracker](https://frontend-staging-7f87.up.railway.app/licensing/tracker); [`/healthz`](https://frontend-staging-7f87.up.railway.app/healthz) | [Dashboard](https://railway.com/project/c2858170-82ee-4b51-a255-3729e1c3b724/service/b42887fa-8807-46aa-a258-ccdf8cbf2d14) | `/frontend/railway.json`; root `frontend`; watches `/frontend/**` |
| `backend` | [API](https://backend-staging-2030.up.railway.app); [`/health/live`](https://backend-staging-2030.up.railway.app/health/live); [`/health/ready`](https://backend-staging-2030.up.railway.app/health/ready) | [Dashboard](https://railway.com/project/c2858170-82ee-4b51-a255-3729e1c3b724/service/764e93c5-527c-4228-b7af-54d698e049d8) | `/railway.json` |
| `worker` | No public URL; inspect Railway logs and `/api/v1/operations/status` | [Dashboard](https://railway.com/project/c2858170-82ee-4b51-a255-3729e1c3b724/service/c4145f0a-f312-4bc2-978a-f0799c6da34e) | `/railway.worker.json` |
| `scheduler` | No public URL; Railway cron `*/5 * * * *` | [Dashboard](https://railway.com/project/c2858170-82ee-4b51-a255-3729e1c3b724/service/87f22cfa-4ee2-4beb-8f54-eb9036ee3fcb) | `/railway.scheduler.json` |
| `Postgres` | Private Railway network only | [Dashboard](https://railway.com/project/c2858170-82ee-4b51-a255-3729e1c3b724/service/2735f1e2-a68b-44be-a8e0-435186a7dca4) | Railway-managed database |

`browser-worker` is defined by `/railway.browser-worker.json` but is not
deployed. Enable it only after portal assistance is approved.

The portal requires sign-in with an approved Astra Microsoft account. Its
public `/healthz` endpoint does not require sign-in.

The Railway `production` environment exists, but application services are not
deployed there. Do not treat production as live or copy staging credentials
into it; follow [DEPLOYMENT.md](../DEPLOYMENT.md) and the go-live checklist.

## Deploy and verify

Normal path: merge or push to `main`. Railway deploys only services whose
repo-root watch patterns match the changed files. A documentation-only commit
is correctly reported as `SKIPPED`. GitHub auto-deploy is enabled for
`backend`, `frontend`, `worker`, and `scheduler` in staging.

Use a manual deployment only from a clean, synchronized `main` checkout:

```powershell
git fetch origin
git status --short --branch
npx -y @railway/cli@latest up -s <service> -e staging --detach --json
```

Verify after every deployment:

```powershell
npx -y @railway/cli@latest status --json
Invoke-WebRequest https://backend-staging-2030.up.railway.app/health/ready
Invoke-WebRequest https://frontend-staging-7f87.up.railway.app/healthz
```

For worker and scheduler changes, also check Railway deployment logs and
`GET /api/v1/operations/status`. Detailed variables, migrations, rollback,
backup, and go-live procedures remain in [DEPLOYMENT.md](../DEPLOYMENT.md).
