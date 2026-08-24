# CT AI Labs — Edge Intelligence Studio branded UI direction

Generated with the built-in image generation workflow. The existing seven-screen set is used as the structural and content reference; the supplied CT AI Labs horizontal logo is the exact brand reference.

## Emotional and product direction

- **Audience moment:** a technical buyer or operator sees a complex physical environment and needs to trust the system quickly.
- **Before → after:** uncertain and overloaded → oriented and capable.
- **Primary feeling:** capable.
- **Supporting feeling:** reassured.
- **Meaning:** “This system sees what matters, explains why, and keeps the evidence close.”
- **Desired response:** ask a question, inspect the evidence, and confidently act.

## Brand system

- CT near-black: `#050708` — primary text, dark hardware surfaces.
- CT teal: `#149A9A` — active navigation, links, focus, selected evidence, system intelligence.
- Deep teal: `#0F6F73` — accessible text accents and strong active states.
- Warm white: `#F7F7F4` — application canvas.
- Mineral mist: `#EDF3F2` — selected backgrounds and quiet information groupings.
- Cool border: `#D8E2E0` — dividers and cards.
- Healthy green: `#2E8B63` — healthy and normal states only.
- Watch amber: `#C88928` — changing or watch states.
- Attention coral: `#C95D4B` — events requiring attention, used sparingly.

The interface stays light and spacious. Teal is functional, not decorative. Use solid color and fine lines; no gradients, glows, or large teal panels. The exact supplied black-font CT AI Labs logo sits in the top of the left rail on every screen. Preserve a clean blank logo slot so the source logo can be composited exactly in production.

## Shared shell and operational improvements

- Wide 1536 × 1024 desktop application screen, no browser chrome or device frame.
- Persistent 176px left rail: exact CT AI Labs logo at top, then Home, Live, Explore, Events, Capabilities, System.
- Compact top bar: page title or breadcrumb on the left; Airport scenario switcher, local-processing status, help, and user controls on the right.
- Active navigation uses a mineral-mist background, a 3px CT teal indicator, and deep-teal icon/text.
- One consistent global command pattern: “Ask CT AI…” or a contextual “Ask about…” field.
- Status vocabulary is consistent: Normal, Changing, Watch, Attention, Healthy.
- Every conclusion stays adjacent to evidence, timestamp, location, and a compact “Why?” or provenance affordance.
- Real airport imagery is neutral and documentary. Detection overlays appear only when they help explain a conclusion.
- Avoid generic KPI-card dashboards, surveillance-wall styling, giant metrics, excessive pills, cyberpunk, neon, glassmorphism, gradients, dark police-drama aesthetics, clutter, logos other than CT AI Labs, and watermarks.

## Screen prompts

### 1. Home

Preserve the existing Home screen’s excellent five-second hierarchy while making it unmistakably CT AI Labs. Active nav: Home. Use a compact top bar with “Airport” selected and Warehouse, Retail, Sports, Custom available. Main hero is a calm “Environment Brief” with the exact operational summary from the canonical prompt, set beside one strong realistic Terminal A evidence frame. Add “Updated just now · 8 live streams · Processing locally” and small “Why this summary?” and “View evidence” affordances. Directly beneath, a wide command field “Ask CT AI about this environment…” with three example queries. Keep the four semantic Live World cards for Terminal A, Checkpoint 3, Gate A14, and Vehicle Entrance; text understanding is more prominent than video. Keep “What the system noticed” as a compact meaningful timeline. Right rail becomes “Local Edge” with 8/8 streams, GPU, memory, 38 W, 42 ms, pipelines, and “Cloud requests: 0”; it remains quiet and secondary. CT teal identifies intelligence and interaction; amber/coral only identify the two meaningful exceptions.

### 2. Live

Active nav: Live. Add a compact top-level “Environment now” summary ribbon before the six-camera grid so the operator sees the combined understanding first. Use a refined 2 × 3 grid for Terminal A, Checkpoint 3, Gate A14, Baggage Claim, Vehicle Entrance, Restricted Perimeter. Each tile shows a semantic place name, one-sentence AI observation, entity/activity counts, state, and small time freshness. Only Checkpoint 3 and Gate A14 use subtle overlays. Controls are Semantic, Overlays, Tracks, Zones; Semantic is selected in CT teal. A slim right rail called “Changes & attention” ranks only meaningful cross-camera changes and links each statement to evidence. Make clear that the cameras contribute to one model of the airport.

### 3. Explore

Active nav: Explore. Make the command field the focal point with “Ask anything that happened here”. Use the exact canonical vehicle query, answer, and derived filters. Add a compact “How this was answered” provenance affordance next to the result. Build a legible evidence-first vertical timeline where timestamps, camera, location, clip duration, and entity are visually aligned. Highlight the three over-15-minute cases in watch amber without implying danger. Keep the recent unattended-bag search. Use CT teal for query/evidence links and selection, not for large surfaces. Natural language stays first; retrieved video is visibly supporting evidence.

### 4. Investigation

Active nav: Events. Title: “Unattended Object — Gate A14”. Preserve the five-step chronological evidence story and canonical conclusion. Add a subtle qualifier around the 87% association: “Likely association · evidence-linked” and an unobtrusive “Why 87%?” control. Each row contains timestamp, camera/location, realistic frame, short explanation, and clip action. Use a single CT teal thread connecting cross-camera steps. Keep the slim evidence summary and actions Ask follow-up, View clip, Open entity, Export evidence. The tone is neutral and analytical; coral marks the unattended-object event only, not the person.

### 5. Entity / Relationship

Active nav: Explore. Header: Person #1842, current location, first observed time, and a small privacy-status control. Preserve the appearance path Parking Entrance → Terminal A → Checkpoint 3 → Gate A14 → Gate A12 with timestamps and frames. Make the relationship graph quieter and easier to understand: center Person #1842; group connected evidence into Objects, Places, Events, Cameras, and Vehicles; keep exact canonical nodes and labelled edges. Use CT teal for the selected node/path, neutral gray for context, amber only for the event node. Include “Ask about this entity” with the canonical question. Add a tiny legend for observed fact vs inferred association.

### 6. Capabilities

Active nav: Capabilities. Header: “What can this edge system understand?” and Airport Scenario selector. Preserve the left capability index and selected Semantic Video Search demo, with the red-suitcase query, answer, and three evidence frames. Keep the Vision Language Understanding and Multi-Camera Intelligence demos visible below. Improve operation with a compact “Start demo” control and a Demo Mode indicator in CT teal. Avoid marketing-card treatment: the page should feel like a working lab bench for demonstrating capabilities with live evidence.

### 7. System

Active nav: System. Header: “Running locally on the edge”. Use a tasteful hardware image, canonical metrics, and strong local-processing statement. Keep the complete pipeline, Active Workloads table, and four restrained charts. Use CT teal consistently for data traces, selected pipeline stage, and healthy local-processing proof; green is used only for Running/Healthy. Place “Cloud requests: 0” beside the local-processing statement. Add compact “Data boundary: on-device” and “Last model health check” details to strengthen buyer trust without adding dashboard clutter.
