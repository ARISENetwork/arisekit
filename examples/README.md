# Examples

| Example | Purpose |
| --- | --- |
| [Autonomous generation](autonomous-generation/README.md) | Offline SCT, CPC, novel text, and international-adaptation rehearsal with resume |
| [Text benchmark example](p0-golden-path/README.md) | Reviewed authoring plan through scaffold and execution |
| [Agentic/FHIR example](agentic-fhir-golden-path/README.md) | Isolated chart tools and deterministic task scoring |
| [Multimodal example](multimodal-golden-path/README.md) | Inventoried image attachments and runtime contracts |
| [Azure FHIR authoring](azure-fhir-authoring/README.md) | Provider-connected authoring workflow and retained evidence |

Use the example's own instructions and input files. The autonomous rehearsal
uses fixture responses and does not call a provider. Provider-connected
examples have separate configuration and execution requirements.

Write new run outputs under the ignored root `outputs/` directory. Existing
tracked recordings, results, and source snapshots support historical evidence
and remain at their recorded paths.
