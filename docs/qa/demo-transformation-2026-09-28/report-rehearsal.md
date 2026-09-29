# Recorded answer-to-report rehearsal — September 28

Codex integrated browser, running app at http://10.88.9.12:7777/.
Continued the Home → search → selected first five seconds of Warehouse — Box
Handling journey. Query: `person carrying a box`.

Question: “Describe only the person’s visible actions in this clip. Is the box
still being held in the final frame?”

Fresh answer repeated the prior description: person carrying a box approaches
the green steps and still holds the box. The citation played to the final frame,
visibly consistent with that bounded conclusion. Screenshot:
[final frame](report-rehearsal-final-frame.png).

Reported local analysis: **15.5 seconds**. Browser observed processing at 11.223 s
and completion by 20.533 s; these are observation bounds, not exact completion
latency. One question submitted, no automatic retry.

Saved report: `509d8852-a1d7-4385-9fc1-30d5ee52a313`, titled **Tradeshow rehearsal —
box held at final frame**, low review priority, resolved. Notes identify demo
footage, the recording's old burned-in timestamp, and the limited interpretation.
Opened saved report and played retained media: video readyState 4, duration 5 s,
currentTime 5 s, ended true, error null. This confirms playback at check time,
not indefinite cache retention.

## Finding and fix

Report displayed the answer but omitted its original question. Added an escaped
Question asked section when analysis.question is nonempty. This applies to the
normal HTML report and exported briefing, including existing saved reports.
Five focused API tests passed, including export question escaping; app TypeScript
passed. Browser reload showed the actual saved question and answer together.
[Report screenshot](report-question-context.png).

## Export limitation

Activated Export briefing. Server logged the download=true endpoint HTTP 200 in
16 ms, but the integrated browser's download event timed out after 10 seconds.
No file handle was returned. Download delivery is therefore **unverified**.
API tests cover export contents and attachment headers; they do not prove browser
delivery. No duplicate report or fallback browser was created.

## Runtime scope

Before: core 31 roles, no failures, 50.28 GiB available. After inference/save:
31 roles, no failures, 49.77 GiB available. The 48 GiB guard was preserved.
No live source or model budget changes. These point checks do not qualify
sustained ingestion, long-term stability or broader answer accuracy.

## Export follow-up: clearer handoff, delivery still unverified

Retested the existing saved report using the Codex integrated browser. Keyboard
activation of Export briefing produced another HTTP 200 (10 ms server log) but
no download event within 15 seconds. The documented link downloadMedia control
also timed out. This does not establish whether the app or browser integration
is responsible. No external browser fallback was used.

The report now says **Download briefing (.html)** with an explicit download
attribute, and explains before export that the file contains the saved answer,
notes and evidence links; video playback requires the Jetson network. Actions
wrap on narrow screens. Changed **Observed facts** to **AI observations** so
unreviewed model descriptions are not presented as established facts.

After hot reload: desktop and 390×844 mobile layouts showed readable guidance
and controls without overlap or framework overlays; report console had no
errors/warnings. The existing report has a duplicate single observation, so its
separate observations section is intentionally absent; that label is covered
by the API fixtures. Five API tests and app TypeScript passed after updating the
old copy expectation. Download still returned no event after 10 seconds with
the explicit attribute: delivery remains unverified, not fixed. No inference
or runtime configuration changes. Screenshots: report-export-guidance.png and
report-export-guidance-mobile.png.
# Follow-up: reopening from Events & reports

Revisited the actual saved-report list in Codex's integrated browser. The latest
reviewed “Tradeshow rehearsal — box held at final frame” appeared first.
Its Open report link opened a new report tab using the documented locator click
(the initial keyboard activation did not create a tab). No direct URL navigation
was substituted for this link test.

Activated Play exact clip through the integrated accessibility keyboard API.
The retained video reached currentTime 5 / duration 5, readyState 4, error null.
Question, answer, review notes and evidence reference were present. Browser
warning/error log empty. Screenshot: `report-reopened-playback.png`. Closed
the completed report tab to avoid retaining another browser workload.

Download delivery remains unverified. Locator click with a 15-second download
event wait and accessibility Return with a 10-second wait both timed out.
The documented browser troubleshooting guidance supplied no further download
mechanism. No report matching its identifier/name was found in Downloads.
These observations do not establish whether the failure is the app or the
integrated browser's download support.

Checked the HTTP export separately: status 200, HTML attachment filename,
question and review notes present, absolute evidence link to the current Jetson
address, and no external asset dependencies. Receipt:
`report-export-http-check.json`. The initial diagnostic converted headers into
a case-sensitive dictionary and incorrectly reported a null Content-Disposition;
corrected the receipt using the HTTP header object's case-insensitive lookup.
This verifies the export response only, not browser file delivery. Print/PDF
and offline rendering remain unverified. No new report or inference created.
