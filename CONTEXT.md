# CTAILabs Vision AI Showcase

The CTAILabs Vision AI Showcase demonstrates how private, local computer vision can understand real environments and help customers act on what their cameras observe. It is a CTAILabs customer experience powered by NVIDIA VSS.

## Language

**Showcase**:
The configurable, tradeshow-first CTAILabs application used to demonstrate compelling, locally operated vision AI capabilities through a credible analyst workflow.
_Avoid_: VSS UI, NVIDIA demo

**CTAILabs Vision Intelligence**:
The customer-facing name of the Showcase. It is presented as a CTAILabs product powered by NVIDIA.
_Avoid_: THOR LOCAL VSS, VSS Agent

**Scenario**:
A represented operational environment, such as a warehouse or traffic intersection, primarily defined by its connected footage and business context. The common application works across Scenarios without becoming a separate experience for each one.
_Avoid_: Custom app, separate product, tab

**Live Source**:
A real-time RTSP video stream from a simulator or physical camera. Live Sources are the primary evidence that the Showcase can analyze an operating environment.
_Avoid_: Demo feed, sample video

**Capability**:
An analyst-facing function available to a Source, such as semantic search, person tracking, or safety monitoring. Capabilities are named by what they provide rather than by the underlying model or service.
_Avoid_: Model, microservice, container

**Analytics Layer**:
A separately toggleable visual representation of live intelligence, such as boxes, tracks, zones, counts, captions, or rule indicators. Layers remain available without crowding the default video view.
_Avoid_: Debug overlay, permanent annotation

**Recorded Source**:
Archived video used for repeatable demonstrations, historical investigation, and testing. Recorded Sources complement rather than replace Live Sources.
_Avoid_: Static demo

**Fallback Source**:
A local Recorded Source prepared to preserve the Showcase workflow when a simulator or Live Source is unavailable. It is clearly identified and is never represented as live.
_Avoid_: Fake live stream, canned answer

**Scenario Template**:
An optional CTAILabs configuration that makes a Scenario easy to run by supplying sources, rules, or model adjustments that differ from the common application defaults.
_Avoid_: Custom application, industry-specific UI

**Edge Deployment**:
One NVIDIA Thor processing and providing intelligence over one or more camera streams at a physical site.
_Avoid_: Cloud deployment, single-camera demo

**Presenter**:
A CTAILabs team member who guides the Showcase through a credible Operations Analyst workflow. The Presenter is the primary user of the tradeshow application.
_Avoid_: Special demo user, admin

**Prospect**:
A potential customer who experiences the Showcase with a Presenter or explores it independently. The Prospect is its secondary user.
_Avoid_: End user, operator

**Operations Analyst**:
The portrayed operational role responsible for understanding activity, investigating events, and coordinating a response across one or more camera streams. The workflow should be credible without implying that the tradeshow build is the final production product.
_Avoid_: Deployment admin, generic user

**System Administrator**:
The user responsible for sources, rules, retention, system health, and access configuration. Administrative workflows are kept separate from the Operations Analyst experience even when authentication is not enabled in a tradeshow build.
_Avoid_: Deployment admin, presenter

**Rule**:
A reviewed and testable condition that turns observed activity into an Alert. A Rule may begin as natural-language intent but is activated only from a visible structured definition.
_Avoid_: Prompt, model instruction

## Work Areas

**Operations**:
The live workspace for monitoring cameras, current conditions, and important events across an Edge Deployment.
_Avoid_: Dashboard, home page

**Investigation**:
An evidence-backed inquiry into live or recorded activity using natural-language questions, historical search, summaries, and supporting clips across all Scenario cameras by default.
_Avoid_: Search result, chat

**Live Context**:
The explicit recent time window and camera set analyzed when the Vision Analyst answers a question about current activity. It never implies access to frames outside the stated window.
_Avoid_: Real time, now

**Management**:
The restricted workspace for connecting sources, activating rules, managing retention, and inspecting system health.
_Avoid_: Video Management, settings page

**Alert**:
A rule-triggered event requiring analyst attention and carrying supporting video evidence. An Alert progresses from New to Acknowledged to Resolved.
_Avoid_: Notification, detection

**Critical**:
An Alert severity requiring immediate response.
_Avoid_: High, urgent

**Warning**:
An Alert severity requiring timely review.
_Avoid_: Medium

**Advisory**:
An Alert severity marking a noteworthy pattern without an urgent response requirement.
_Avoid_: Low, informational

**Event**:
A time-bounded occurrence observed in one or more camera streams. An Event may be routine activity or may generate an Alert when it matches a configured rule.
_Avoid_: Alert, raw detection

**Activity Feed**:
A chronological, filterable view of Alerts and significant Events across an Edge Deployment. It excludes raw detections and diagnostic model output.
_Avoid_: Detection log, notifications

**Evidence**:
A playable clip or frame tied to a named camera and exact time range that supports an Alert, Event, or AI answer.
_Avoid_: AI response, confidence score

**Protected Evidence**:
Evidence preserved from rolling retention because it supports an unresolved Alert, Investigation, or Incident Report.
_Avoid_: Archived video, permanent recording

**Observation**:
A fact directly supported by Evidence, kept distinct from an AI-generated interpretation of what that fact may mean.
_Avoid_: Conclusion, assumption

**Vision Analyst**:
The natural-language interface for investigating live and recorded activity. It answers with Evidence-backed Observations and interpretations rather than generic chat responses.
_Avoid_: VSS Agent, chatbot

**Presentation Mode**:
A layout mode that maximizes live video, Analytics Layers, the Activity Feed, and the Vision Analyst by temporarily hiding nonessential navigation and management chrome. It changes presentation without changing data or behavior.
_Avoid_: Demo mode, fake mode

**Suggested Question**:
A contextual prompt that helps a Presenter demonstrate a configured Capability using the real Vision Analyst and current activity.
_Avoid_: Canned answer, scripted response

**Incident Report**:
An operational record built from a selected Alert or time range, containing its timeline, Observations, analyst notes, and Evidence.
_Avoid_: AI summary, chat export

**Insights**:
The Operations view for meaningful metrics and trends with direct drill-down to their underlying Events and Evidence.
_Avoid_: Dashboard, Elasticsearch view

**Insight Card**:
A curated operational metric or trend available for administrators to enable, disable, and reorder. It supports direct drill-down to its underlying Events and Evidence.
_Avoid_: Kibana panel, arbitrary visualization

**Operational Briefing**:
An Evidence-linked natural-language summary of significant measured activity over a stated time range. It summarizes supported data without inventing causes.
_Avoid_: AI opinion, executive summary

**Proof of Concept**:
A tailored engagement that applies the Showcase's capabilities to a Prospect's environment and business problem.
_Avoid_: Product purchase, generic demo
