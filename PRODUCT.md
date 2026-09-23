# WIND AGENT
<!-- impeccable:product-schema 1 -->

## Platform
web

## Stack
Delegated: the user requested autonomous implementation of the final plan. Python, FastAPI and Streamlit
were retained from that plan. All operation is local; no paid hosting or new API registrations.

## Users
The HackAlemAI team and reviewers checking hourly forecasts for two specified wind turbines.
An operational dispatcher is an intended future user, not a confirmed deployed customer.

## Product Purpose
Replay daily 48-hour forecasts from genuine archived weather runs, with normalized active line-side power,
explicit origins, model cutoffs, source files, measured validation and honest missing actuals.

## Operating Context
Windows laptop demonstration. XLSX history ends January 2026. No February power actuals.
The user authorized Asia/Almaty/start-of-interval assumptions for MVP testing pending organizer confirmation.

## Capabilities and Constraints
No MW conversion or physical hub height claims. Free NOAA GFS source. Existing OpenAI/NVIDIA credits only.
LLM plans allowlisted actions; numerical forecasts never come from an LLM.
Strict export stays blocked while scientific metadata are unconfirmed.

## Evidence on Hand
Two original XLSX files and the official task PDF. Verified coordinates from the PDF map links.
Real weather bytes and time headers are cached with checksums. Validation results appear only after execution.

## Product Principles
Explain each forecast's origin; distinguish missing data from zero; show assumptions alongside results;
preserve reproducibility; keep normal operation available without a paid language model.

## Design delegation
The user explicitly requested completion without further participation except essential external credentials.
Visual choices and a code-led implementation are delegated. No generated decoration or paid design assets are needed.
Russian interface; laptop-first, responsive layout. This is a declared design assumption.
