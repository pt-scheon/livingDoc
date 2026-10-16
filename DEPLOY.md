# Deploying LivingDoc

LivingDoc is one container (API + website) with a SQLite database in `/data`. Three things matter for a public site:

1. **Set `LIVINGDOC_ADMIN_PASSWORD`.** Without it everything is open to whoever finds the URL. Use a long passphrase.
2. **Serve over HTTPS.** Every host below does this for you. Session cookies are marked `Secure` automatically behind HTTPS.
3. **Keep `/data` on a persistent volume.** Free tiers that wipe the disk on redeploy will lose the shop's data.

Check the host's current pricing yourself: plans and free-tier limits change.

## Option A: Render (simplest, dashboard only)

1. Push this repo to GitHub.
2. Render dashboard → **New → Blueprint** → choose the repo. It reads `render.yaml` (Docker service, 1 GB disk at `/data`, health check `/api/health`).
3. When asked, type a value for `LIVINGDOC_ADMIN_PASSWORD`.
4. Wait for the deploy; open the `https://….onrender.com` URL and sign in.

The persistent disk needs a paid instance. If you deploy without a disk (free plan) the demo works, but data resets on every deploy.

## Option B: Fly.io

```bash
fly launch --no-deploy --copy-config          # keep fly.toml; pick a unique app name
fly volumes create livingdoc_data --size 1 --region bom
fly secrets set LIVINGDOC_ADMIN_PASSWORD='your long passphrase'
fly deploy
```

## Option C: Your own server (any VPS)

```bash
git clone <repo> && cd livingdoc
cp .env.example .env && nano .env              # set LIVINGDOC_ADMIN_PASSWORD
docker compose up -d --build                   # listens on :8000
```

Put Caddy (automatic HTTPS) in front, for example `Caddyfile`:

```
shop.example.com {
    reverse_proxy localhost:8000
}
```

## After it is live

- Open the URL, sign in, and check **Today**. The first start loads demo data (a sample shop). Delete the demo items and entries you do not want, or start from a fresh volume with your own notes.
- The shop's public page is `https://<your-host>/shop.html?s=<slug>`. It stays hidden until you publish it under **Be found**.
- Scanners and scripts: `curl -H "Authorization: Bearer $LIVINGDOC_ADMIN_PASSWORD" -d '{"events":[…]}' https://<host>/api/scanner/events`.
- Optional AI for Hindi/Gujarati notes: set `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (any OpenAI-compatible service).
- Backups: copy `/data/livingdoc.db` (use `sqlite3 livingdoc.db ".backup out.db"` while running). The proof-signing key lives in that file, so guard backups like a password.
- Changing the password signs everyone out.

## Limits to know

- One shared owner password, no per-user accounts or roles.
- SQLite on one container: fine for a shop or a few branches, not a large chain. Run a single instance.
- The login rate limit is kept in memory, so it resets when the container restarts.
