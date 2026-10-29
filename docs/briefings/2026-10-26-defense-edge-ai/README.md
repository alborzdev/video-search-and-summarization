# Vision AI for Defense

Updated 26 October 2026 to match the requested high-level scenario overview.

- Illustrated PDF: four pages, five scenario concepts. The three main scenarios use screenshots captured from the actual VSS Defense workspace.
- Editable Word: same four-page scope.
- Text-only PDF: one-page summary.

The document avoids runtime/model tables, benchmarks, deployment-readiness discussion and the rejected titles. `content.json` maintains the text; `build_brief.py` builds the files. No app source, simulation or model services were changed. The UI-only development helper was used to start the stopped VSS UI for screenshots, with the Spark guard active. The document removes the booth section and gives aircraft inspection and border security their own illustrated descriptions.

## Research behind the additional options

Aircraft exterior inspection is supported by the official 307th Bomb Wing account of drone imagery feeding aircraft-surface anomaly analysis:
https://www.afgsc.af.mil/News/Article-Display/Article/3849653/307th-bomb-wing-jets-get-innovative-treatment/
Original official DVIDS publication:
https://www.dvidshub.net/news/476928/307th-bomb-wing-jets-get-innovative-treatment
The Air Force page's indexed content was rechecked; its direct fetch returned 403. The earlier source review is preserved in `isaacsim-6/docs/defense-market-survey/drone-asset-inspection-evidence.md`.

Border security replaces the earlier patrol-comparison concept at the user's request. The scenario shows camera-based person/vehicle detection, movement tracking, defined-boundary alerts and operator review in VSS. GAO's February 2026 report documents CBP's increased use of land-based surveillance systems, including day/night cameras and autonomous towers with software that distinguishes people and vehicles:
https://files.gao.gov/reports/GAO-26-107501/index.html
This supports the application category, not a claim that CTI has fielded a border system. The illustration depicts a remote desert border access road; the cited report covers northern-border deployment and demonstrates the wider technology use. The brief does not infer a person's legal status from appearance or movement.

Pegasus framework reference:
https://pegasussimulator.github.io/PegasusSimulator/
No executed Isaac Sim 6 compatibility test is claimed by this document.

## Visual sources and checks

The main visuals are actual browser screenshots of the Defense workspace at `http://127.0.0.1:3001/?workspace=defense`, captured in Presentation Mode on 26 October 2026:

- `assets/vss-drone-inspection.png`: first-pass and closer inspection views.
- `assets/vss-site-security.png`: storage-area boundary crossing and event sequence.
- `assets/vss-vehicle-awareness.png`: rear and side views with camera-position diagram.
- `assets/vss-drone-survey.png`: survey view retained as a supporting capture, not included in the brief.

These screens were captured in Design preview. Their illustrative imagery and example-event labels remain visible; they are screenshots of the implemented UI, not claims of live defense inference or real field footage.

`assets/aircraft-inspection.png` and `assets/border-security.png` are new AI-generated scenario illustrations, labeled as illustrations in the document. The generated originals remain in the chat's generated_images directory. Unused draft assets remain preserved.

All four illustrated PDF pages were rendered and visually inspected for image placement, readable headings, text bounds and footer clearance. The editable Word document was converted with LibreOffice and confirmed to contain four pages. The text-only PDF fits one page.

The border-security revision updates the shared content, page-four heading, PDF, Word and text-only summary. The former patrol-change asset is preserved but no longer referenced by the deliverables. The image-generation prompt is saved in `assets/border-security-prompt.txt`; the built-in image generation tool was used.
