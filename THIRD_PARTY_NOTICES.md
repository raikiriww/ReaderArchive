# Third-Party Notices

Reader Archive uses third-party software, images, models, and tools. The
project source code is licensed under the Apache License 2.0, but third-party
components remain licensed by their original authors under their own licenses.

This file is a summary of the major runtime components. The complete dependency
sets are recorded in `backend/uv.lock` and `frontend/bun.lock`.

## Major Runtime Components

| Component | Use | License / Terms | Source |
| --- | --- | --- | --- |
| LinuxServer Chrome image | Base browser desktop image | GPL-3.0-only | https://github.com/linuxserver/docker-chrome |
| Google Chrome | Browser runtime inside the desktop image | Google Chrome Terms of Service | https://www.google.com/chrome/terms/ |
| SingleFile CLI | Web page archiving | AGPL-3.0 | https://github.com/gildas-lormeau/SingleFile |
| yt-dlp | Public video downloads | Unlicense | https://github.com/yt-dlp/yt-dlp |
| FFmpeg | Media probing, merging, and conversion | LGPL/GPL depending on build options | https://ffmpeg.org/legal.html |
| PostgreSQL | Database | PostgreSQL License | https://www.postgresql.org/about/licence/ |
| pgvector | PostgreSQL vector extension | PostgreSQL License | https://github.com/pgvector/pgvector |
| Bun | Frontend package manager and test runner | MIT, with bundled third-party components | https://github.com/oven-sh/bun |
| Node.js | Frontend build runtime | MIT | https://github.com/nodejs/node |
| uv | Python dependency management | MIT or Apache-2.0 | https://github.com/astral-sh/uv |
| Python | Runtime | Python Software Foundation License | https://docs.python.org/3/license.html |
| paraphrase-multilingual-MiniLM-L12-v2 | Semantic search model | Apache-2.0 | https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 |

## Application Dependencies

The frontend and backend package dependencies keep their original licenses.
Most are permissively licensed under MIT, Apache-2.0, BSD, or ISC terms. Some
dependencies use other open-source licenses, including LGPL, MPL, CC-BY, and
multi-license options.

Notable packages to keep in mind:

- `psycopg` and `psycopg-binary`: LGPL-3.0-only.
- `certifi`, `lightningcss`, and `tqdm`: include MPL terms.
- `tld`: MPL/GPL/LGPL multi-license options.
- `caniuse-lite`: CC-BY-4.0.
- `Bun`: MIT, with bundled third-party components.

## Container Images

This repository contains a Dockerfile and Compose configuration. If you
redistribute a built container image, the image includes third-party operating
system packages, browser components, tools, models, and application
dependencies. Preserve their license notices and review their redistribution
terms before publishing prebuilt images.

## Trademarks

Third-party names, logos, and trademarks belong to their respective owners.
Their inclusion here is for identification and compatibility only.
