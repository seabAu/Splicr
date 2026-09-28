# The browser interface

React (Vite) frontend for the local Python API. **No Node at runtime** --
Vite builds static files into `../narrator/webui`, and the Python server
serves them. One process, one runtime, nothing extra to install alongside
the app.

## Building

    npm install
    npm run build

Then, from the project root:

    python -m narrator web

which prints a URL containing a session token and opens it.

## Developing

    npm run dev                     # in web/
    python -m narrator web --no-browser   # in another terminal

The dev server proxies `/api` to the Python server on port 8765, so URLs
are identical in development and in the shipped build.

## Why not Next.js

Next is a *server* framework: SSR, its own API routes, its own Node
process. For a tool installed and run locally none of that applies -- there
is no SEO, no server rendering benefit, and the API is Python, so Next's
API routes would be dead weight. It would mean shipping and running two
runtimes for no gain. Plain React with Vite builds to static files the
Python server already serves.

## The token

The API can browse the filesystem and start processes, so "local" is not
the same as "safe" -- any page open in your browser can make requests to
127.0.0.1. A token is minted when the server starts and handed over in the
URL; `api.js` moves it into `sessionStorage` and strips it from the
address bar so it isn't left in history.

`EventSource` cannot set headers, so the log stream passes the token as a
query parameter instead. That is a real browser constraint, not a
shortcut; the server checks it the same constant-time way.

## Structure

| File | What it does |
| --- | --- |
| `api.js` | Every call to the backend, plus token handling and the SSE subscription with its polling fallback. |
| `SettingsForm.jsx` | Generated from `/api/schema`. Adding a field to `render_config.py` makes it appear here with the right control, range and description -- it is never hand-written. |
| `FileBrowser.jsx` | The backend browses the filesystem on the page's behalf, since a browser can't hand over a path. |
| `JobLog.jsx` | Live progress. Streams by default, falls back to polling if the stream drops -- a dropped connection must not look like a hung render. |
| `Components.jsx` | What's installed, what it unlocks, and an Install button for anything that can install itself. |
| `Dialogue.jsx` | Turn a document into a two-host script, edit it by hand, then render it with a voice per host. |
| `Providers.jsx` | Your own LLM endpoints and keys, with staged verification. |
| `Library.jsx` | Past documents with their saved settings. Loading one puts its cfg straight back in the form. |
| `Publish.jsx` | Take picker, episode details, feed publishing, chapters, and channel settings. |
| `Pronunciation.jsx` | Search Kokoro's dictionary, see what any word actually sounds like now, and override it. |
| `Convert.jsx` | Format, quality, rate, channels, and splitting by length or size. |
| `JobList.jsx` | Searchable history. Filters run on the server; a row's log is fetched only when it is opened. Past jobs survive a restart. |
| `App.jsx` | The one workflow wired together: choose a document, set options, generate, watch it, see the take. |

## What this slice deliberately does not cover

The timeline, voice studio and audiogram layout are still desktop-only
(engine setup now has a web equivalent). This exists to prove the shape end to end --
schema-driven form, validation, job with streaming progress, real output
on disk -- on the smallest surface that exercises every hard part. The
desktop app keeps working while the rest is built out.
