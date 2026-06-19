# detectkit website

Marketing landing + documentation site for detectkit, served at
[dtk.pipelab.dev](https://dtk.pipelab.dev).

Built with [Astro](https://astro.build) + [Starlight](https://starlight.astro.build).
The brand system lives in [`brand/`](./brand) (exported from the design tool); the
theme tokens are mirrored in [`src/styles/brand.css`](./src/styles/brand.css).

## How docs get here

`docs/*.md` and `CHANGELOG.md` in the repo root stay the **single source of truth**.
At dev/build time, [`scripts/sync-docs.mjs`](./scripts/sync-docs.mjs) imports them into
`src/content/docs/` (git-ignored), injecting Starlight frontmatter (title from the
leading `# H1`) and rewriting cross-`.md` links to clean routes. Referenced config
examples (`docs/examples/*.yml`) are copied to `public/examples/` as downloads.

**Edit the docs in `docs/`, never in `website/src/content/docs/`.** To add or move a
page, update the `PAGES` map in `scripts/sync-docs.mjs` and the `sidebar` in
[`astro.config.mjs`](./astro.config.mjs).

## Develop

```bash
cd website
npm install
npm run dev      # runs sync-docs, then astro dev  → http://localhost:4321
```

## Build

```bash
npm run build    # runs sync-docs, then astro build → ./dist (static)
npm run preview  # serve ./dist locally
```

## Deploy (dtk.pipelab.dev)

The site is fully static. Two options:

**Docker / nginx** (build context = repo root, so the docs are available):

```bash
docker build -f website/Dockerfile -t detectkit-web .
docker run --rm -p 8080:80 detectkit-web
```

CI builds and pushes this image to `ghcr.io/alexeiveselov92/detectkit-web:latest`
on every push to `main` that touches `website/`, `docs/`, or `CHANGELOG.md`
(see [`.github/workflows/website.yml`](../.github/workflows/website.yml)). Point your
IaC server at that image, or build the image there.

**Plain static files**: copy `website/dist/` to any static host / nginx root.
