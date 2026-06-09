# 🚀 MigrateIQ — AI Validation Agent for Mainframe Modernization

[![Hackathon](https://img.shields.io/badge/Microsoft-Agents%20League%202026-purple?style=for-the-badge&logo=microsoft)](https://innovationstudio.microsoft.com/hackathons/Agents-League-Hackathon)
[![Track](https://img.shields.io/badge/Track-🧠%20Reasoning%20Agents-blueviolet?style=for-the-badge)]()
[![IQ](https://img.shields.io/badge/Powered%20by-Foundry%20IQ-00bcf2?style=for-the-badge&logo=microsoftazure)]()
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)]()
[![Chainlit](https://img.shields.io/badge/UI-Chainlit-FF6B6B?style=for-the-badge)]()
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)]()

> **Reasoning AI agent that validates mainframe-modernized code against legacy COBOL — ensuring 100% output parity in minutes, not hours.**

🏆 **Microsoft Agents League Hackathon 2026** | 🧠 **Reasoning Agents Track** | 💡 **Foundry IQ**

---

## 📹 Demo Video

🎥 **[Watch Full Demo](#)** *(link coming soon)*

> *Live demo runs on enterprise infrastructure. This repository contains the source code for review.*

---

## 🎯 The Problem

Enterprises spend **millions** migrating COBOL to modern stacks (C#, Java, Python), but post-migration defects can take **weeks** to find. Manual validation is slow, error-prone, and a top reason mainframe modernization projects fail or stall.

## 💡 The Solution

A **9-step agentic workflow** where 5 specialized AI agents collaborate to validate that modernized code produces **byte-identical output** to the original COBOL.

┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ DevOps   │───▶│ Script   │───▶│ Compare  │───▶│Reporting │───▶│ Analysis │
│ Agent    │    │ Runner   │    │ Agent    │    │ Agent    │    │ Agent    │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
│               │               │                │               │
▼               ▼               ▼                ▼               ▼
Pull PR       Build/Run       Diff vs         Generate       Reason w/
Latest        Modern Code     COBOL           Report         Foundry IQ
Baseline                       + Fix Suggest

## 🧠 Why Reasoning Agents?

- **Multi-step deterministic workflows** with conditional branching
- Each agent reasons over **COBOL semantics** (PIC clauses, REDEFINES, 88-levels, COPY books)
- **Foundry IQ** provides grounded retrieval — every claim is **cited** from COBOL source
- **Self-healing loop**: failed fixes feed back into reasoning context

## 🛠️ Key Features

| Feature | Description |
|---|---|
| 🤖 **Multi-LLM Switching** | GPT-4, Claude, Gemini swappable at runtime via Portkey gateway |
| 🎙️ **Voice Search** | Hands-free workflow control (accessibility-first) |
| 💬 **Natural Language Chat** | Ask "why did file X fail?" in plain English |
| 🌊 **Streaming Responses** | Token-by-token AI thinking visible live |
| 🎨 **Animated Dashboard** | Glass-morphism UI with workflow node visualization |
| 📊 **Live Progress Bars** | Real-time multi-agent task tracking |
| 🎉 **Celebration Animations** | Confetti on successful validation |
| 📚 **Hybrid Search** | Foundry IQ + ChromaDB for COBOL + past PR fixes |

## 🏗️ Architecture
MigrateIQ/
├── agents/              # 5 specialized AI agents
│   ├── analysis_agent.py
│   ├── chat_agent.py
│   ├── compare_agent.py
│   ├── devops_agent.py
│   ├── reporting_agent.py
│   └── script_runner_agent.py
├── services/            # Core services
│   ├── cobol_service.py
│   ├── codebase_service.py
│   ├── ingestion_service.py
│   ├── knowledge_base_service.py
│   ├── llm_service.py
│   └── orchestrator.py
├── tools/               # Agent tools
├── models/              # Pydantic data models
├── prompts/             # All prompts as markdown/yaml
├── workflows/           # 9-step orchestration
├── public/              # UI assets (CSS/JS)
└── app.py               # Chainlit entry point

## 🔧 Tech Stack

- **Frontend:** Chainlit (custom CSS/JS animations)
- **Agents:** Custom multi-agent orchestration
- **Knowledge:** Foundry IQ (cited grounding) + ChromaDB (vector search)
- **LLM Gateway:** Portkey-compatible multi-provider routing
- **Language:** Python 3.11+
- **Extensibility:** Generic `TARGET_LANGUAGE` env var (csharp/java/python)

## 🌟 Impact

- ⏱️ Validation time: **weeks → minutes**
- 🎯 Defect detection: **100% output parity verification**
- ♿ Accessibility: voice-driven UI for inclusive enterprise teams
- 🏢 Enterprise-ready: any COBOL → modern stack migration

## 🚀 Quick Start

> **Note:** Live demo runs on enterprise infrastructure. See demo video for full walkthrough.

```bash
# Clone
git clone https://github.com/Shivarajbhosur/MigrateIQ.git
cd MigrateIQ

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your values

# Run
chainlit run app.py
