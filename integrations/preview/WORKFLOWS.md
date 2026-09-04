# Preview maintenance

## Production boundary

`commands.py` exposes `open`, `drop`, and `show`. The application adapter validates the extension against [`file-authority.json`](file-authority.json) before calling shared CoreDevice or AirDrop mechanics. Shared code still owns path containment, regular-file checks, size limits, snapshots, recipient UI, one-attempt dispatch, unlock handling, and result projection.

## File authority

Production permits `.pdf`; common JPEG, PNG, TIFF, HEIC/HEIF; and the image types declared by the iOS 26.5 Preview bundle: OpenEXR, BMP/DIB, ICO, TGA, PSD, ICNS, and JPEG 2000 extensions. Apple documentation establishes the broad PDF/image capability. Simulator bundle metadata is build-specific source authority, not proof that the installed Preview 1.0 renders every extension.

The app gate does not enlarge the private AirDrop allowlist. Both layers must admit the path. MIME sniffing, content conversion, archives, office formats, movies, EPUBs, and directory transfer are outside Preview.

## Result semantics

- `open`: exact-profile screenshot evidence proves Preview became visible.
- `drop`: a positive host callback proves only sender-side AirDrop completion.
- `show`: transfer is attempted once, then Preview is launched; neither step identifies the displayed document.

A lost response is uncertain and must not be replayed. Recipient choice and any iPad acceptance remain manual. No screenshot, filename, path, document content, device identifier, or raw response is committed as evidence.

## Physical closure

An earlier unattended PDF transfer timed out and was not replayed automatically. A later explicit manual `show` test used a fresh PDF; the operator selected the iPad and directly confirmed receipt and exact opening in Preview. This proves the PDF `show` path only on the recorded profile. Standalone `drop` and image handoff remain unverified. Promote one format only from that format's evidence; do not infer all image formats from one success.
