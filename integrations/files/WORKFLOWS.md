# Files maintenance

## Production boundary

The public surface is exactly `open`, `drop`, and `show`. `commands.py` delegates transport mechanics to shared core; the app package owns the decision that Files is a generic user-selected-file destination rather than a format-specific viewer. Shared AirDrop policy still restricts roots, extensions, regular files, size, snapshots, timeouts, and one-attempt dispatch.

The lab manifest is launch-only. Historical Recents, Browse, Search, typing, selector, Appium, and WDA actions are removed because no such behavior exists in the CoreDevice public adapter.

## Route research

The iOS 26.5 simulator Files bundle registers `shareddocuments://` and `smb://` and declares `public.item` and `public.folder` document types. Those facts provide build-specific research authority only.

- `shareddocuments://` has no Apple-documented stable external path grammar. It is excluded.
- Apple documents connecting to SMB servers through Files UI, not a credential-free automation URL contract. `smb://` is excluded from production and is not probed.
- CoreDevice exposes no stable exact arbitrary Files path, provider, folder, selection, or search payload.

Do not guess route syntax or synthesize provider identifiers.

## Result semantics

`open` is proven by exact-profile pixel inspection. A `drop` result by itself proves sender-side callback completion only; separate exact-profile screenshot evidence records one manually selected ZIP as received and open in the system preview. That evidence proves the generic ZIP transfer path, not Files ownership. `show` may transfer and launch Files, but neither result establishes that Files owns, displays, or selects the transferred file. Unknown post-dispatch state is uncertain and is never replayed.

No screenshot, path, filename, provider, location, file metadata, device identifier, or raw response belongs in committed evidence.

## Physical closure

The recorded standalone `drop` test meets the generic-transfer threshold for one harmless ZIP: manual recipient selection plus visible confirmation that the ZIP was received and opened in the system preview. `drop` is therefore proven and admitted for that exact profile, without proving Files ownership or other formats. Exact `show` evidence additionally requires proof that the intended file opened or became selected in Files; `show` remains candidate and `legacy-admitted`.

## Manual transfer evidence

A fresh plain-text file sent through `show` was manually selected in AirDrop and an authorized read-only screenshot confirmed the exact file open in the system preview. Files itself was not visibly established as the owning foreground app, so `show` remains candidate-boundary. A subsequent ZIP sent through standalone `drop` was also visibly received and opened in the system preview; that proves generic transfer receipt, not exact Files ownership.
