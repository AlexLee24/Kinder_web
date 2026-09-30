# Vendored front-end libraries

Self-hosted so pages do not execute code from third-party CDNs (served as `/static/vendor/...`).
Files are copied unmodified from the npm packages; licenses are alongside.

| File | Package | SRI (sha384) |
|---|---|---|
| `aladin-3.8.2.js` | aladin-lite@3.8.2 (`dist/aladin.js`) | `sha384-/ymkiSIIZYSHUE2kIcPf4PWW4meM/MIvDZbgCurNjz4k6/Fe21cxLQ9cEn0DlBsZ` |
| `jquery-3.6.0.min.js` | jquery@3.6.0 (`dist/jquery.min.js`) | `sha384-vtXRMe3mGCbOeY7l30aIg8H9p3GdeSe4IFlP6G8JMa7o7lXvnz3GFKzPxzJdPfGK` |
| `marked-18.0.14.umd.js` | marked@18.0.14 (`lib/marked.umd.js`) | `sha384-2vpGtuKqJvFlwJqYnf/wUMuzUfhUnYBt9oay0e2yaFcq0Dh6/aEbQ8YAOeKGzlYo` |
| `purify-3.4.16.min.js` | dompurify@3.4.16 (`dist/purify.min.js`) | `sha384-a7SzOxErzJ3ZpQz0zJ32d67dSitNzPcbfybc/ykU9KJhMgZkwqfSxlhhdJRS+XGL` |

To upgrade: `npm pack <pkg>@<version>`, copy the same file with the new version in its name,
update the references and this table (`openssl dgst -sha384 -binary FILE | openssl base64 -A`).
