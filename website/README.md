# Cerebrofy website

A static, dependency-free landing page. It draws Cerebrofy's own source code as a 3D brain, and tells the
story of the project beside it as you scroll.

```
website/
  index.html            the page (HTML, CSS and JS in one file)
  graph.js              generated: the module import graph of src/cerebrofy
  vendor/three.min.js   three.js r128 (MIT), self-hosted
  fonts/                Archivo and JetBrains Mono (SIL OFL), self-hosted
  scripts/build_graph.py
```

## Preview locally

```bash
python website/scripts/build_graph.py     # regenerate graph.js
python -m http.server -d website 8000     # then open http://localhost:8000
```

## Deploy

`.github/workflows/pages.yml` regenerates `graph.js` and publishes the folder on every push to `master` that
touches the site, the source or `pyproject.toml`. Set **Settings > Pages > Source** to **GitHub Actions** once.

## Notes

- No third-party requests: fonts and three.js are served from this folder.
- Commit site changes as `docs(site): ...` or `ci(site): ...` so semantic-release does not cut a version.
- Copy that states numbers (about 97% fewer tokens, 600k vs 10k tokens, the 130 MB model download) comes from
  the project README and should be updated when those change.
