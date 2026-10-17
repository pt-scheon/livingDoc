# LivingDoc Frontend Pack

**The pack is the PDF:** [`LivingDoc-Frontend-Pack.pdf`](LivingDoc-Frontend-Pack.pdf), screenshots of the working app, each with a caption. The rest of this page is about the hosting zip that sits next to it.

The whole browser side of LivingDoc as one folder you can host anywhere static files are served (Netlify, GitHub Pages, nginx, an S3 bucket). No build step, no npm, no framework: plain ES modules, CSS and three HTML pages.

**Download:** [`livingdoc-frontend-pack.zip`](livingdoc-frontend-pack.zip) (rebuilt from [`/frontend`](../frontend) by `python scripts/pack_frontend.py`).
**Browse the source:** [`/frontend`](../frontend).

## What is inside
| File | Page |
|---|---|
| `index.html` + `js/` + `css/` | The owner app: Today, Stock, Money, Forecast, Trust, Be found, Feedback, Account |
| `shop.html` | The public shop page a customer sees (`shop.html?s=<slug>`), with the rating and comment form |
| `party.html` | The private page a counterparty opens from their link to see, dispute or veto what is recorded about them |
| `config.js` | One line: `window.LIVINGDOC_API` |
| `js/i18n*.js` | English, Hindi and Gujarati strings |

## Use it with the bundled backend (simplest)
Nothing to do. The backend serves `frontend/` at `/`.

## Host it separately
1. Unzip and upload the folder to your static host.
2. Edit `config.js` and set `window.LIVINGDOC_API = "https://your-api-host";`.
3. Start the backend with `LIVINGDOC_CORS_ORIGINS=https://your-frontend-origin`.

**Sign-in caveat.** The session cookie is `SameSite=Lax`, so a frontend on a *different site* from the API cannot stay signed in. Either put both behind one domain with a reverse proxy (`/` → static files, `/api` → backend), or keep the backend in open mode on a trusted network. The public shop page and the party page need no sign-in and work cross-origin.

## Rules the code keeps
User text is inserted as text nodes only (never `innerHTML` with data); the page works with JavaScript modules in any current browser; and every string exists in all three languages.
