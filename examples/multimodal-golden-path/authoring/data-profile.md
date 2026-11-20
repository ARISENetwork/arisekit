# Data profile

_Status:_ accepted

## Source shape

`cases.synthetic.jsonl` contains one top-level object. The row maps an id,
prompt, reference response, specialty metadata, and a non-empty ordered
`attachments` list.

## Attachment inventory

The case references `attachments/synthetic-frontal.png`. The build sidecar
freezes its path, SHA-256 digest, byte size, and `image/png` media type. The
image is copied byte-for-byte into the portable package.
