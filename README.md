# DHIL (ظل) — Heat-Stress Prevention for Hajj and Umrah Pilgrims

**CAI461 — Agent-Based Systems | Project 2**  
**Princess Nourah bint Abdulrahman University**

## Project Overview

DHIL is a Python-based Multi-Agent System designed to help Hajj and Umrah pilgrims reduce their exposure to heat stress within the Haram precinct of Makkah, particularly older adults and individuals with health vulnerabilities.

The system retrieves live weather data, estimates a pilgrim's heat-stress risk using machine learning, and provides preventive recommendations such as drinking water, resting, visiting a cooling area, or seeking medical assistance.

DHIL integrates five cooperating agents to monitor environmental conditions, assess simulated health risks, coordinate resources, and recommend suitable walking routes.

## Agents

| Agent | Role | Technique |
|---|---|---|
| Heat Agent | Retrieves live Makkah weather using Open-Meteo, with cache, fallback, and manual override. | API client with fallback mechanisms |
| Health Agent | Estimates heat-stress risk (Low, Moderate, High, Critical) and time to High risk. | Random Forest classifier with rule-based fallback |
| Resource Agent | Finds available water, rest, cooling, and medical points. | Contract Net negotiation with station agents |
| Prevention Agent | Converts risk assessments into preventive actions and coordinates other agents. | Rule-based decisions and degraded mode |
| Route Agent | Calculates walking routes to recommended locations using the OpenStreetMap pedestrian network. | A* search with heat-aware cost |

Agents communicate through a message bus using ACL-like messages, including INFORM, REQUEST, CFP, PROPOSE, ACCEPT, REFUSE, and FAILURE.

Messages include a shared ontology, conversation IDs, and reply references to support coordination and traceability.

## Key Features

- AI-based heat-stress risk classification.
- Live weather monitoring with fallback mechanisms.
- Personalized preventive recommendations.
- Heat-aware walking route planning.
- Water, rest, cooling, and medical resource coordination.
- Contract Net negotiation among agents.
- Fault tolerance and degraded operation.
- Mobile-first bilingual interface (English and Arabic).
- Agent monitoring and ACL message logs.
- LangSmith tracing.

## Installation and Setup

### 1. Clone the Repository

```bash
git clone https://github.com/halaalhamzah/DHIL-Heat-Stress-MAS.git
cd DHIL-Heat-Stress-MAS
```

### 2. Install Dependencies

```bash
python -m pip install -r requirements.txt
```

### 3. Prepare the Required Files

Ensure that the required map files and trained model are available at the paths expected by the application.

The main project assets include:

- `data/makkah_walk.graphml`
- `data/haram_features.csv`
- `models/health_model.joblib`, if the application is configured to load the model from this directory.

If no trained model is available, the application supports training through the project's training script. Model training can also be performed manually:

```bash
python train_model.py
```

The model-loading and saving paths must be consistent with the current implementation.

### 4. Run the Application

```bash
python -m streamlit run app.py
```

Open the local URL displayed in the terminal.

## User Interface

DHIL provides a mobile-first interface designed for pilgrims, along with a monitoring view for observing the Multi-Agent System.

### Welcome and Profile

Users can select English or Arabic and enter personal information, including age, height, weight, and relevant health conditions. BMI is calculated automatically.

### Pilgrim Guide

The guide displays current heat conditions, estimated risk, preventive recommendations, and a walking map.

Users can interact with the system through actions such as:

- I drank water
- I feel unwell
- I feel better
- Walk to the suggested point
- Start or end rest
- Walk for 5, 30, or 60 minutes

### Monitor View

The monitoring interface provides:

- Live agent status.
- ACL message logs.
- Agent failure and recovery controls.
- Scenario presets.
- Resource availability and station information.

## Testing Scenarios

Three scenarios are implemented to evaluate DHIL's functionality and multi-agent interactions.

The scenarios are available in `notebooks/DHIL_clean_v2.ipynb`.

### Scenario 1 — Extreme Heat

Compares the simulated heat-stress risk of a pilgrim who follows DHIL's preventive recommendations with a pilgrim who ignores them under the same environmental conditions.

The comparison evaluates peak risk and the time spent in the Critical risk category.

### Scenario 2 — Health Agent Failure

Simulates a Health Agent failure during an ongoing journey.

When the agent becomes unavailable, the Prevention Agent switches to degraded-mode rules based on heat information from the Heat Agent, allowing the system to continue issuing preventive recommendations.

The scenario also demonstrates agent recovery and undelivered message logging.

### Scenario 3 — Station Conflicts

Evaluates resource negotiation when rest stations are unavailable.

The scenario includes two cases:

- **Scenario 3A:** The nearest rest station is closed, and the Resource Agent negotiates with available alternatives.
- **Scenario 3B:** All rest stations are unavailable, triggering failure handling, alternative cooling-resource selection, and escalation.

The scenario demonstrates ACL-like communication and Contract Net negotiation among agents.

### Running the Scenarios

Open `notebooks/DHIL_clean_v2.ipynb` in Google Colab and execute the cells in order.

The notebook provides scenario outputs, risk visualizations, agent communication logs, and comparison results.

## LangSmith Tracing

DHIL supports optional LangSmith tracing to observe agent execution and interactions.

Each simulated step can be recorded as a `dhil_step` trace with child spans for:

- Heat Agent weather retrieval.
- Health Agent ML prediction.
- Route Agent A* search.
- Resource Agent Contract Net decisions.
- Prevention Agent rule execution.

Traces also provide information about exchanged messages and agent availability.

### Configuration

1. Create a LangSmith account and generate an API key.
2. Configure `LANGSMITH_API_KEY` as an environment variable or through a local `.streamlit/secrets.toml` file, if supported by the application.
3. Set `LANGSMITH_TRACING=true` to enable tracing.
4. Optionally configure `LANGSMITH_PROJECT`.

Tracing is optional. The Multi-Agent System can operate without a LangSmith API key.

**Never upload API keys or secret configuration files to GitHub.**

The agents are implemented as Python classes using a custom message bus. LangGraph, LangChain, and CrewAI are not used.

## Data Sources and Assumptions

| Component | Source | Data Type |
|---|---|---|
| Walking network | OpenStreetMap via OSMnx, pedestrian paths within approximately 400 m of the Kaaba | Real geographic data |
| Water and medical points | OpenStreetMap features | Real geographic data |
| Rest and cooling stations | Team-defined locations and assumptions | Simulated |
| Walkway shade | Approximation based on walkway characteristics | Simulated |
| Weather | Open-Meteo API | Live weather data |
| Health Agent training data | Synthetic pilgrim profiles and simulated environmental conditions | Synthetic |
| Heat-risk dynamics | Scientific heat-index methods and team-defined modeling assumptions | Simulation-based |

## AI Model

The Health Agent uses a Random Forest classifier trained on synthetic data.

The dataset represents simulated pilgrim profiles and changing environmental conditions. It includes personal health factors, fatigue, time since water and rest, cumulative heat exposure, and heat-index conditions.

The model predicts four simulated risk categories:

- Low
- Moderate
- High
- Critical

A rule-based fallback mechanism is available when the ML component becomes unavailable.

The risk classifications are simulation-based preventive indicators and have not been clinically validated.


## Limitations

- DHIL is a simulation-based prototype and is not intended for medical diagnosis or emergency response.
- The Health Agent uses synthetic training data and team-defined risk assumptions rather than clinically validated data.
- Resource availability, cooling effects, and shade conditions are partially simulated.
- The current system covers a limited area around the Haram in Makkah.

## Project Structure

```text
DHIL-Heat-Stress-MAS/
├── assets/
│   └── logo.png
├── data/
│   ├── makkah_walk.graphml
│   ├── haram_features.csv
│   └── health_dataset.csv
├── models/
│   └── health_model.joblib
├── notebooks/
│   ├── DHIL_clean_v2.ipynb
│   └── DHIL_mobile_v3.ipynb
├── app.py
├── ui_backend.py
├── health_agent.py
├── heat_agent.py
├── resource_agent.py
├── route_agent.py
├── prevention_agent.py
├── system.py
├── messages.py
├── tracing.py
├── health_model.py
├── generate_data.py
├── train_model.py
├── i18n.py
├── requirements.txt
└── README.md
```

## Contributors

Developed by the DHIL project team at Princess Nourah bint Abdulrahman University.

**Course:** CAI461 — Agent-Based Systems

**Project Team and Supervision:**  
- Hala Ali Alhamzah
- Aleen Khaled Aloqili
- Lama Mohammed Alsuhaibani
- Ghala Mohammed Alkahtani

Course Instructor: Dr. Eman and T. Manairh

## Credits

- Map data: © OpenStreetMap contributors (ODbL).
- Map tiles: © Esri.
- Weather data: Open-Meteo.
- Heat Index methodology: U.S. National Weather Service (NWS).
