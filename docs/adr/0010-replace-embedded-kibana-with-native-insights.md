---
status: accepted
---

# Replace embedded Kibana with native Insights

The customer-facing product will replace the embedded Kibana iframe with a native CTAILabs Insights interface. Elasticsearch may remain an internal store, but the browser will consume a stable analytics API expressed in Alerts, Events, metrics, and Evidence rather than Elasticsearch queries or saved Kibana objects. Insights will provide a curated universal baseline, optional scenario metrics, configurable Insight Cards, and an Evidence-linked Operational Briefing without becoming a general-purpose dashboard builder.
