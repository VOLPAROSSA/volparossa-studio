# VOLPAROSSA Studio product website

The English product page is served from [the Studio project path](https://volparossa.org/volparossa-studio/). It depicts one workshop poster on paper, in a static Silex editor, on a phone and in a browser preview. Studio's product claims link to the [hosted test record](../docs/IMPLEMENTATION_STATUS.md).

## Preview

From the repository root, run the following commands and open [the local project page](http://127.0.0.1:8786/volparossa-studio/).

```sh
python3 website/scripts/build_site.py
python3 website/scripts/check_site.py
python3 -m http.server 8786 --bind 127.0.0.1 --directory website/preview
```

The regular build uses Python's standard library and the committed assets. It verifies the shared theme against its source inventory. Preview pages carry a noindex directive. To reproduce the public build, run these commands.

```sh
python3 website/scripts/build_site.py --production --output website/dist/volparossa-studio
python3 website/scripts/check_site.py --production --output website/dist/volparossa-studio
```

## Sources and review

- [Page structure, styles and metadata](src/) and [reusable poster and editor](scripts/objects.py).
- [Art masters and attribution](masters/README.md) and [responsive files](assets/studio/). To regenerate sources at display sizes, run `python3 website/scripts/export_art.py` with Pillow installed. With the preview running and Playwright available, `node website/scripts/share_card.mjs` renders the 1200 × 630 social card.
- [Vendored central theme](vendor/volparossa-theme/) version 1.1.0, exported with `python3 scripts/export_theme.py --source-only` from central commit `991cf1638c906226574b9c21bb32c6618fc07fb7`.
- [Desktop preview](review/desktop.webp) and [mobile preview](review/mobile.webp).
- [GitHub Pages workflow](../.github/workflows/studio-website.yml). Pull requests build an independently inspectable preview. A validated website change on main, or a manual run on main, produces and deploys a project-root Pages artifact. Generated site trees are kept in the workflow artifacts.

The browser review uses the locked dependencies in this directory. While the local preview is running, run `npm --prefix website ci --ignore-scripts`, install the Playwright browsers for the desired engines, then run `QA_ENGINES=chromium npm --prefix website run qa`. Full screenshots and machine-readable results are written to `website/qa/browser/`. The checks cover the project subpath, menu and keyboard use, mobile reflow, disabled JavaScript and images, enlarged text, local assets and accessibility.
