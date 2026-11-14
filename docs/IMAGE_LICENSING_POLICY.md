# Image Licensing Policy

Implemented in Phase 5 (14 Nov 2026). Rules 2 and 5 are also enforced by database constraints, so no code path can bypass them.

1. **Licence first.** Images come only from approved adapters (Wikimedia Commons, licensed stock providers, tenant-uploaded assets with declared rights). General web image search results are never downloaded for publication.
2. **Publishable requires all of:** a known licence name and licence URL, commercial use permitted, attribution text recorded (if required), and creator/provider recorded. If any is unknown, the image is stored as *reference only* and cannot be attached to a publishable article version.
3. **Edits do not change rights.** Cropping, resizing, colour changes or filters do not remove copyright obligations. Modification permission is recorded separately; documentary photos are never edited in a way that changes their meaning.
4. **Provenance is kept.** Original file, retrieval date, source URL and every processing step are stored.
5. **AI illustrations** are permitted only when no suitable licensed photograph exists. They are labelled "AI-generated illustration / एआई-निर्मित चित्रण" in the caption, never depict a real identifiable person at an event, and are never presented as documentary photographs.
6. **Charts** use only verified numbers from evidence records, with units, source and date shown on the graphic. Pie charts only for genuine parts of a whole.
7. **Takedown.** A tenant admin can withdraw any asset; withdrawal propagates to all published articles using it.

## Implementation notes (Phase 5)

- Source: Wikimedia Commons. Recognised licences: CC0, public domain, CC BY, CC BY-SA. Refused: non-commercial (NC), no-derivatives (ND, because web resizing is a modification under this policy), GFDL-only, unknown.
- Attribution text is generated as: "Title" by Author, Licence (URL), via Wikimedia Commons — and appended to the caption when an editor selects the image.
- Restrictions noted by Commons (e.g. personality rights, trademarks) are shown to editors.
- Only proportional resizes are made; no crop, no colour change; the downloaded file is kept unchanged.
- AI illustrations: only after licensed photos are reviewed; prompts use section and place only (never headline words, which can contain people's names); label stored and shown in the caption. No provider is configured yet.
