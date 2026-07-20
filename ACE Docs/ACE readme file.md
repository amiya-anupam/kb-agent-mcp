# IBM App Connect Enterprise (ACE) — Complete Knowledge Base

> **Latest Version:** ACE v13.0.8.0 (Long-Term Support — SC3)
> **Product:** IBM App Connect Enterprise (formerly IBM Integration Bus / IIB)
> **Source:** [IBM Docs — App Connect Enterprise](https://www.ibm.com/docs/en/app-connect) | [Product Page](https://www.ibm.com/products/app-connect)
> **Last Synthesised:** July 2025 (covers ACE v13.0.1 through v13.0.8)

---

## Table of Contents

1. [Welcome & Overview](#1-welcome--overview)
2. [Core Concepts](#2-core-concepts)
   - [Integration Flows](#21-integration-flows)
   - [Integration Servers & Runtimes](#22-integration-servers--runtimes)
   - [ACE Toolkit](#23-ace-toolkit)
   - [ACE Designer (Low-Code)](#24-ace-designer-low-code)
   - [Smart Connectors & Discovery Connectors](#25-smart-connectors--discovery-connectors)
   - [App Connect MCP Server](#26-app-connect-mcp-server)
3. [AI & Agentic Capabilities](#3-ai--agentic-capabilities)
   - [AI-Assisted Development](#ai-assisted-development-designer--toolkit)
   - [App Connect MCP Server (Agentic AI)](#agentic-ai--app-connect-mcp-server)
   - [ACE AI Agent (Embedded Chat)](#ace-ai-agent-embedded-chat-preview)
4. [Deployment Options](#4-deployment-options)
   - [Container (CP4I / OpenShift)](#41-container-cp4i--openshift)
   - [VM / Traditional Deployment](#42-vm--traditional-deployment)
   - [High Availability](#43-high-availability)
5. [Licensing & Entitlements](#5-licensing--entitlements)
   - [Editions & Parts](#51-editions--parts)
   - [License Models](#52-license-models)
   - [VPC Licensing on CP4I](#53-vpc-licensing-on-cp4i)
6. [Migration](#6-migration)
   - [IIB to ACE v13](#61-iib-to-ace-v13)
   - [ACE v11/v12 to ACE v13](#62-ace-v11v12-to-ace-v13)
   - [Migration Waiver Programme](#63-migration-waiver-programme)
7. [What's New — ACE v13 Modification Packs](#7-whats-new--ace-v13-modification-packs)
8. [Seller Enablement & Customer Conversations](#8-seller-enablement--customer-conversations)
   - [Customer 101 — Basics](#81-customer-101--basics)
   - [Customer 201 — Intermediate](#82-customer-201--intermediate)
   - [Customer 301 — Advanced](#83-customer-301--advanced)
   - [ACE vs. Competitors](#84-ace-vs-competitors)
9. [Best Practices & Guidance](#9-best-practices--guidance)
10. [Frequently Asked Questions](#10-frequently-asked-questions)
11. [MQ + MFT Cross-Sell](#11-mq--mft-cross-sell)
12. [Useful Links & Resources](#12-useful-links--resources)
13. [Glossary](#13-glossary)

---

## 1. Welcome & Overview

**IBM App Connect Enterprise (ACE)** is IBM's industry-leading enterprise integration platform. It enables organisations to connect applications, data, and services across hybrid cloud and on-premises environments, without requiring deep coding expertise.

> *"IBM App Connect Enterprise integrates your business applications, data, and services across on-premises and cloud environments. It provides a low-code development experience and a scalable, flexible runtime — all within a single, unified platform."*

ACE is the modern evolution of **IBM Integration Bus (IIB)** (formerly WebSphere Message Broker), retaining full backward compatibility while introducing cloud-native capabilities, AI-powered development, and MCP-based agentic integration.

**Current release:** ACE v13.0.8.0 (quarterly mod pack cadence). The container operator release is SC3 (v13.0.0 operator — 3-year support window).

### Key Value Propositions

| Value | Detail |
|---|---|
| **Low/No-Code** | Create integrations visually via App Connect Designer with 200+ pre-built connectors |
| **AI-Powered** | AI-generated flows, AI field mapping, AI data assist, watsonx Code Assistant in Toolkit |
| **Agentic AI** | ACE MCP Server enables AI agents (Claude, Copilot, etc.) to invoke integration flows as tools; ACE AI Agent provides embedded chat in Dashboard |
| **Hybrid Connectivity** | Connects on-prem systems, cloud SaaS, APIs, MQ queues, Kafka topics, and databases |
| **Enterprise Grade** | Production-proven at thousands of enterprises globally; FIPS, TLS, and SOC 2 compliant |
| **IIB Compatibility** | Full backward compatibility with existing IIB/ACE v11/v12 message flows |
| **Flexible Deployment** | Containers (CP4I), standalone OpenShift, VMs, or hybrid — all managed from a single Dashboard |
| **Fast Time-to-Value** | 100+ tutorials, Patterns Gallery, pre-built connector library, and AI assistance reduce development time |
| **Discovery Connectors** | Toolkit-native connector nodes for Kafka, Salesforce, SAP, Azure, AWS, Pulsar, Databricks, and more |

### Architecture Snapshot

```
┌────────────────────────────────────────────────────────────────────────┐
│                     Platform UI / Management Layer                      │
│          (CP4I Platform UI or ACE Dashboard — single pane of glass)    │
├──────────────────────────┬─────────────────────────────────────────────┤
│   ACE Designer           │   ACE Toolkit                               │
│   (Low-Code / AI-Guided) │   (Pro-Code, Eclipse 4.31, Java 17 default) │
├──────────────────────────┴─────────────────────────────────────────────┤
│                     Integration Runtime (single `runtime` container)    │
│            Deploys .BAR files — Designer + Toolkit flows               │
├─────────────┬──────────────┬──────────┬────────────────────────────────┤
│ SaaS Apps   │ On-Prem Apps │ MQ       │ Kafka / Event Streams          │
│ (Salesforce,│ (SAP, DB2,   │ Queues   │ Topics (Avro, transactions)    │
│ ServiceNow) │ Oracle, etc.)│          │                                │
└─────────────┴──────────────┴──────────┴────────────────────────────────┘
          │                                       │
          ▼                                       ▼
┌──────────────────┐                  ┌──────────────────────────────────┐
│  App Connect     │                  │   ACE AI Agent (embedded chat)   │
│  MCP Server      │                  │   + MCP Server for AI agents     │
│  (tools for LLMs)│                  └──────────────────────────────────┘
└──────────────────┘
```

---

## 2. Core Concepts

### 2.1 Integration Flows

An **integration flow** (also called a **message flow**) is the fundamental unit of work in ACE. It describes how a message (data) moves from a source, through transformation/processing logic, to a target.

**Flow types:**
- **API flows** — expose internal logic as REST APIs (can be exposed as MCP tools from v13.0.7+)
- **Event-driven flows** — triggered by events from MQ, Kafka, HTTP, timers, Discovery Connector Input nodes
- **Batch flows** — process large volumes of records in bulk (Designer Batch Process available from v13.0.7+)
- **File flows** — transfer or transform file-based data (FTP, SFTP, local)
- **Database flows** — read, write, or query relational databases (PostgreSQL stored procedures with dynamic result sets from v13.0.2+)

**Flow authoring options:**

| Method | Tool | Code Level |
|---|---|---|
| Low-code visual flow editor | ACE Designer | No-code/Low-code |
| Graphical flow editor | ACE Toolkit | Pro-code |
| AI-assisted flow generation | ACE Designer + AI | No-code |
| AI watsonx Code Assistant | ACE Toolkit | Pro-code assisted |
| YAML/IaC manifests | BAR + IntegrationRuntime CR | DevOps/GitOps |

---

### 2.2 Integration Servers & Runtimes

The **Integration Server** (on-premises/VM) and **IntegrationRuntime** (containerised/Kubernetes) are the execution engines that run compiled integration flows (`.BAR` files).

**Key Kubernetes CRDs (when deployed on CP4I/OpenShift):**

| CR | Description |
|---|---|
| `IntegrationRuntime` | Main runtime CR. From v13.0.7.0-r1+: single `runtime` container for all flow types (Designer + Toolkit) |
| `IntegrationDashboard` | Monitoring dashboard for runtimes; hosts the ACE AI Agent (v13.0.7+) |
| `DesignerAuthoring` | Low-code authoring environment (App Connect Designer) |
| `SwitchServer` | Routes messages between integration servers |
| `Configuration` | Configuration objects (policies, keystores, service accounts, etc.) |

> ⚠️ **Deprecation:** `IntegrationServer` CR is deprecated as of CP4I 16.1.3+. Migrate existing deployments to `IntegrationRuntime`.

> 🆕 **Single container architecture (v13.0.7.0-r1+):** All integration runtimes — whether deploying Designer flows, Toolkit flows, or hosting MCP servers — now use a single `runtime` container. The `connectors`, `designerflows`, `designereventflows`, and `proxy` containers are no longer created. Benefits: faster startup, improved security, simplified configuration.

**VM/Traditional deployment:**
- Integration Node (formerly Broker) + Integration Server hierarchy
- Managed via `mqsicommands` / `ibmint` CLI, ACE web user interface, or REST Admin API
- Can be managed from the CP4I Platform UI via **App Connect Private Networks** (CP4I 16.2+)
- Admin interface secured by HTTPS by default in v13; `mqsi` and `ibmint` commands updated accordingly

---

### 2.3 ACE Toolkit

The **IBM App Connect Enterprise Toolkit** is the professional Eclipse-based IDE for building and testing integration flows. Updated in ACE 13 to **Eclipse 4.31** running on **Java 17** (the new default runtime).

**Capabilities:**
- Graphical message flow editor (drag-and-drop nodes)
- Built-in node library: HTTP, MQ, Kafka, File, Database, Transformation, Routing, Discovery Connector nodes, etc.
- **ESQL** editor for low-level message transformation scripting
- **Graphical Data Mapping** — visually map source to target message formats
- **Message Model editor** — define DFDL schemas and message sets
- **Built-in test harness (Flow Exerciser)** — test flows locally with simulated input; HTTPS support in Flow Exerciser from v13.0.2+
- **BAR packaging** — compile and package flows into deployable BAR files
- **Policy Project** — manage integration policies (endpoints, credentials, timeouts, MQTT, Salesforce, Pulsar, etc.)
- **Java / ESQL / XPath** transformation support
- **watsonx Code Assistant** — AI code suggestions in the Toolkit (from v13.0.4+)
- **Patterns Gallery** — over 100 pre-built patterns including AI Patterns (RAG, watsonx.ai integration from v13.0.5+)
- **Extended tutorials catalog** — 100+ tutorials on the Welcome page
- **External Directory Vault Explorer** — create, update, and delete connector credentials from within the Toolkit
- **Container Explorer View** — manage resources in an ACE certified container dashboard from the Toolkit (v13.0.3+)
- **Context Tree** — read-only tree in Flow Debugger and Flow Exerciser for Discovery Connector output data (v13.0.4+, enhanced in v13.0.5+)
- **OpenAPI import in Policy Editor** — improved usability for configuring API-based policies (v13.0.6+)

**Supported OS:** Windows, Linux, macOS (via containerised toolkit)

---

### 2.4 ACE Designer (Low-Code)

**IBM App Connect Designer** is the browser-based low-code authoring environment for creating integrations without coding. Available standalone in ACE software from v13.0.1+.

**Key capabilities:**
- **Smart Connectors / Discovery Connectors** — 200+ pre-built connectors to SaaS and enterprise systems
- **Drag-and-drop** flow editor — connect apps, transform data, add conditions and loops visually
- **AI Mapping Assist** — AI suggests field mappings between source and target applications (v13.0.4+)
- **AI Data Assist** — AI-powered data-related assistance for transformations (v13.0.4+)
- **AI flow generation** — describe the integration in natural language; AI generates the flow
- **Event-driven triggers** — start flows on new/updated/deleted records in connected apps
- **API calls** — invoke external REST APIs or expose flows as APIs
- **If/Else conditions, For-each loops** — logical constructs without coding
- **Batch processing** — insert a Batch Process node for asynchronous large-dataset operations (v13.0.7+)
- **Publish to runtime** — deploy directly from Designer to an IntegrationRuntime or ACE on CP4I
- **Account renaming** — rename connector accounts at creation time (v13.0.5+)

**DesignerAuthoring CR** (on CP4I) manages the Designer authoring environment as a managed Kubernetes workload. From v13.0.7.0-r1+, the DesignerAuthoring runtime also runs in a single `runtime` container.

---

### 2.5 Smart Connectors & Discovery Connectors

ACE has two connector paradigms:

**Smart Connectors** (Designer) — pre-built, no-code connectors available in the Designer flow editor.

**Discovery Connectors** (Toolkit + Designer) — Toolkit-native connector nodes that use the same connector backend as Designer. App Connect Designer connectors are now surfaced as "Discovery connectors" in the Toolkit, enabling Toolkit developers to use the full connector catalogue with their pro-code flows.

**Connector categories:**

| Category | Examples |
|---|---|
| CRM & Sales | Salesforce, HubSpot, Microsoft Dynamics |
| ITSM | ServiceNow, Jira, BMC Remedy |
| HR & ERP | SAP, SAP SuccessFactors (v13.0.6+), Workday, Oracle HCM, IBM Planning Analytics (v13.0.4+) |
| Collaboration | Slack, Microsoft Teams, Gmail, Office 365 |
| E-Commerce | Shopify, Magento, WooCommerce |
| Finance | Stripe, PayPal, QuickBooks |
| Storage | Box, Google Drive, OneDrive, SharePoint |
| Databases | IBM Db2, Oracle, MySQL, PostgreSQL, MSSQL, AstraDB (v13.0.6+) |
| Messaging | IBM MQ, Apache Kafka, RabbitMQ, Apache Pulsar (v13.0.6+) |
| Cloud Events | Amazon EventBridge (v13.0.4+), Azure Service Bus (v13.0.4+), Azure Cosmos DB, IBM Cloudant |
| AI/Data | Databricks (v13.0.6+), Pinecone (for RAG patterns) |
| APIs | HTTP/REST, SOAP, GraphQL |

**HTTP Proxy support for Discovery Connectors:** Growing list of connectors support HTTP proxy for on-premises deployments with strict network security. Includes Salesforce (v13.0.3+); 24 connectors support proxy as of v13.0.3.

**Connector configuration** is managed via the `Configuration` CR (on CP4I) or credential policies / external directory vault (on-premises). Each Discovery Connector type has a corresponding policy type that can store credentials encrypted in an ACE vault.

**Event Resilience policy (v13.0.7+):** Configure an Event Resilience policy on a Discovery Connector Input node so incoming events are persisted to Kafka, providing durable event processing.

---

### 2.6 App Connect MCP Server

The **App Connect MCP Server** exposes ACE integration flows as **tools** callable by AI agents using the Model Context Protocol (MCP). This enables AI agents (GitHub Copilot, Claude Desktop, IBM Bob, custom LLM apps) to invoke real-time integrations as part of their reasoning loop.

**Availability:** MCP support is available in **IBM App Connect Enterprise v13.0.7 or later**.

**Two deployment modes:**

| Mode | Description |
|---|---|
| **On-premises (Standalone ACE)** | Expose an existing ACE Integration Server as an MCP Server from the ACE Web User Interface |
| **Containers (App Connect Dashboard)** | Create and manage MCP servers from the "Model Context Protocol (MCP) servers" page in the App Connect Dashboard |

**Key docs in this folder:**
- `App Connect MCP 101.PDF` — introduction and overview
- `App Connect MCP Server One Pager.PDF` — quick-reference summary

---

## 3. AI & Agentic Capabilities

### Overview

IBM App Connect Enterprise v13 introduces a progressive set of AI-powered capabilities:

| Tier | Capability | Availability |
|---|---|---|
| AI-Assisted Dev | AI flow generation, AI mapping, AI data assist | Designer: v13.0.1+; Mapping/Data assist: v13.0.4+ |
| Pro-Code AI | watsonx Code Assistant in Toolkit | v13.0.4+ |
| AI Patterns | RAG pattern for watsonx.ai + Pinecone in Patterns Gallery | v13.0.5+ |
| Agentic Outbound | MCP Server — expose ACE REST APIs as MCP tools for AI agents | v13.0.7+ |
| Agentic Inbound | ACE AI Agent — embedded chat in Dashboard for operations | v13.0.7+ (Public Preview) |
| Connector MCP | Connectors exposed as MCP tools for AI agents | v13.0.8+ |

---

### AI-Assisted Development (Designer + Toolkit)

| Capability | Description | Version |
|---|---|---|
| **AI flow generation** | Describe your integration scenario in natural language; AI scaffolds the entire flow | v13.0.1+ |
| **AI Mapping Assist** | AI suggests source-to-target field mappings based on semantic similarity | v13.0.4+ |
| **AI Data Assist** | AI-powered data transformation suggestions inside Designer | v13.0.4+ |
| **watsonx Code Assistant** | AI code suggestions and completions in the ACE Toolkit ESQL/Java editor | v13.0.4+ |
| **AI BAR generation** | Describe the BAR file requirements; AI configures packaging and deployment artefacts | Designer |
| **AI documentation** | AI generates documentation from existing integration flows | Designer |
| **RAG Pattern** | AI Pattern in Toolkit Patterns Gallery: indexes data to Pinecone, queries via watsonx.ai for RAG | v13.0.5+ |

---

### Agentic AI — App Connect MCP Server

The **App Connect MCP Server** is ACE's entry point into the **agentic AI** paradigm. It allows any MCP-compatible AI agent to discover and invoke ACE integration flows as typed tools.

**What it does:**
- Exposes ACE REST API integration flows as **MCP tools** — callable by any MCP-compatible AI agent
- Also exposes the full App Connect **connector catalogue as MCP tools** (v13.0.8+)
- AI agents can **discover** available integration flows, **understand** their inputs/outputs via tool metadata, and **invoke** them in real-time as part of multi-step reasoning
- Enables AI agents to: create orders, retrieve customer data, trigger approvals, query inventory, and more — all through natural language

**Architecture:**

```
┌──────────────────────────────────────────────────────────────┐
│            AI Agent (Claude, Copilot, IBM Bob, Custom LLM)   │
│                                                              │
│  "What is the status of order #12345?"                       │
└───────────────────┬──────────────────────────────────────────┘
                    │ MCP Tool Call (JSON-RPC / Streamable HTTP)
                    ▼
┌──────────────────────────────────────────────────────────────┐
│              App Connect MCP Server                          │
│  (Discovers ACE flows / connectors, exposes as MCP tools)   │
│  Auth: Basic Auth or TLS (configured via CR or Dashboard)   │
└───────────────────┬──────────────────────────────────────────┘
                    │ Invokes integration flow
                    ▼
┌──────────────────────────────────────────────────────────────┐
│             ACE Integration Runtime                          │
│  (Fetches order from SAP/Oracle/custom system)              │
└──────────────────────────────────────────────────────────────┘
```

**Container CR parameters for MCP:**
- `spec.mcp.runtime.basicAuth.disabled`
- `spec.mcp.runtime.basicAuth.secretName`
- `spec.mcp.runtime.tls.disabled`
- `spec.mcp.runtime.tls.secretName`
- `spec.mcp.runtime.disabled`

**Supported AI agents:** Any MCP-compatible client (Claude Desktop, GitHub Copilot, Cursor, IBM Bob, custom LLM apps using watsonx)

**Use cases:**
- Customer service AI agent queries order status via ACE-SAP integration
- HR chatbot retrieves employee data via ACE-Workday flow
- Finance AI agent triggers invoice approval workflows via ACE-Oracle flow
- DevOps AI agent checks system health by invoking ACE monitoring flows
- AI agents use ACE connectors (Salesforce, ServiceNow, etc.) directly as MCP tools (v13.0.8+)

**Docs in this folder:** `App Connect MCP 101.PDF`, `App Connect MCP Server One Pager.PDF`

---

### ACE AI Agent (Embedded Chat — Preview)

The **IBM App Connect Enterprise Agent** is an agentic AI chat experience embedded in the App Connect Dashboard (containerised deployments). Available from **v13.0.7+ (Public Preview)**.

**Capabilities:**
- Conversational interface to query and manage your ACE deployment (e.g., "Which integration runtimes do I have in the ACE VJ namespace?")
- Real-time administrative assistance — list runtimes, describe flow behaviour, check deployment status
- Troubleshooting guidance — deep insight into configuration, deployment, and topology
- Answers general ACE product questions from IBM documentation sources
- Step-by-step guidance for operations (e.g., how to scale an IntegrationRuntime)

**Configuration:** Enabled on the Dashboard CR via:
```yaml
spec:
  agents:
    enabled: true
    customSecretName: ace-agents-configuration  # contains AI credentials
```

**Status:** Public Preview — customers are invited to join the preview and provide feedback to shape the roadmap. Access: `ibm.biz/ace-agents`

**Docs in this folder:** See ACE IBM Community blog posts on Agentic AI preview.

---

## 4. Deployment Options

### 4.1 Container (CP4I / OpenShift)

ACE on containers is the recommended modern deployment approach. Two paths:

**Path 1: ACE Certified Container (standalone on OpenShift, no CP4I)**
- Deploy the ACE Operator directly on Red Hat OpenShift
- Managed via the App Connect Dashboard and `IntegrationRuntime` CR
- Suitable for teams primarily running ACE without broader IBM integration platform needs
- Latest operator: **SC3 (v13.0.0 operator, 3-year support window)** — replaces the CD releases (v12.x) and SC2 (v12.0.x)

**Path 2: IBM Cloud Pak for Integration (CP4I)**
- Unified platform bundling ACE + MQ + API Connect + DataPower + Event Streams + Event Endpoint Management + Aspera
- Single Platform Navigator UI (control plane) across all products
- Shared VPC licensing across the integration stack
- Integration Assemblies for cross-product deployments

**Deployment on Red Hat OpenShift:**

1. Install the **IBM App Connect Operator** from the Operator Catalog
2. Create a `DesignerAuthoring` instance for low-code authoring (optional)
3. Create an `IntegrationDashboard` instance for monitoring
4. Package flows into BAR files; create `IntegrationRuntime` CRs to deploy them
5. Use `Configuration` CRs to manage credentials and policies
6. Configure MCP Server on Dashboard CR (v13.0.7+) for agentic AI

**Key features of containerised ACE:**
- GitOps-native: `IntegrationRuntime` manifests stored in Git, deployed via ArgoCD/Tekton
- Horizontal scaling: scale runtime replicas via Kubernetes HPA
- Rolling upgrades: zero-downtime updates of integration flows
- Managed by App Connect Dashboard: full lifecycle visibility (start, stop, delete, monitor)
- OADP Backup & Restore support
- **OpenTelemetry tracing** of Toolkit flows (configured on IntegrationRuntime CR)
- **Knative (Serverless) support** — deploy Designer API flows as on-demand containers
- **Topology Spread Constraints** on Dashboard and IntegrationRuntime pods (v12.14.0 operator+)
- **Custom Hostnames** for Dashboard and API via `.spec.routes` (v12.13.0 operator+)
- **JVM version selection** on IntegrationRuntime CR for backward compatibility (v12.16.0 operator+)

**New in CP4I 16.2+ / Operator SC3:**
- **App Connect Private Networks** — manage VM-based ACE runtimes from the CP4I Platform UI
- **Non-Kubernetes App Connect management** — deploy only the Platform UI on OpenShift, then manage on-prem ACE from it
- **Single `runtime` container** for all IntegrationRuntime pods (v13.0.7.0-r1+) — faster startup, simpler ops

**Supported OpenShift versions:** 4.12, 4.14, 4.15, 4.16, 4.17, 4.18, 4.19, 4.20

---

### 4.2 VM / Traditional Deployment

ACE also runs on **traditional VM infrastructure** (physical or virtualised).

**Deployment topology:**

```
Integration Node (mqsi-managed process)
  └── Integration Server 1  (runs set of BAR files)
  └── Integration Server 2  (runs different BAR files)
  └── Integration Server N
```

**Management tools:**
- `ibmint` commands — the strategic new CLI style for all new commands; supports `ibmint` style across all major operations
- `mqsicommands` — legacy CLI (still supported for core commands; updated with HTTPS security in v13)
- **ACE Web User Interface** — browser-based management dashboard; also entry point for MCP Server setup (v13.0.7+)
- **ACE REST Admin API** — programmatic management
- **ACE Toolkit** — deploy BAR files directly to running servers
- **Auto-completion** of `ibmint` commands in Bash shell (v13.0.2+)

**Key deployment considerations:**
- Supported OS: AIX, Linux, Windows, z/OS (with zCX)
- **Java 17** is the default runtime for ACE 13 (on-prem and containers)
- z/OS Container Extensions (zCX): run ACE Linux containers on z/OS hardware
- Managed File Transfer (MFT) agents run on separate JVMs but co-deploy with ACE runtimes
- Admin API/interface secured by HTTPS by default in v13

---

### 4.3 High Availability

ACE supports multiple HA patterns:

| Pattern | Description | Best For |
|---|---|---|
| **Multi-instance Integration Server** | Active/standby pair sharing a network file system | On-premises, VM |
| **Kubernetes Replicas** | Multiple `IntegrationRuntime` pods; stateless flows | Containers, CP4I |
| **Active/Active with Load Balancer** | Multiple runtime instances behind a load balancer | High-throughput, stateless |
| **MQ-backed recovery** | MQ provides persistent queue; ACE pulls from MQ after restart | Transactional flows |
| **Kafka-backed Event Resilience** | Discovery Connector Input events persisted to Kafka for durable processing | Event-driven flows (v13.0.7+) |

**HA docs in this folder:** `App Connect - High Availability.PPTX`

**Design principles for HA:**
- Keep integration flows stateless where possible
- Persist state to MQ or a database (or Kafka with Event Resilience policy), not in the integration server
- Use Kubernetes `PodDisruptionBudget` to avoid simultaneous pod failures during upgrades
- Deploy across multiple Availability Zones; use anti-affinity rules
- Use Topology Spread Constraints on IntegrationRuntime and Dashboard pods (operator v12.14.0+)

---

## 5. Licensing & Entitlements

### 5.1 Editions & Parts

IBM App Connect Enterprise is available in several editions:

| Edition | Description | Key Additions |
|---|---|---|
| **ACE Base** | Core integration runtime; full integration capabilities | — |
| **ACE + MQ Advanced Messaging** | ACE Base + IBM MQ Advanced (AMS, MFT, clustering) | MQ AMS, MFT |
| **ACE + API Management (APIC)** | ACE Base + IBM API Connect for API lifecycle | API Connect |
| **ACE + All** | Full bundle: ACE + MQ Advanced + API Connect | Everything |

**Part numbers and detailed licensing:** See `App Connect - Ultimate Guide to Entitlement, Parts and Licenses.PDF` in this folder.

---

### 5.2 License Models

| Model | Description |
|---|---|
| **PVU (Processor Value Unit)** | Traditional on-premises: licensed per core/processor (PVU table applies) |
| **Resource Value Unit (RVU)** | Capacity-based: pay for the resource capacity you consume |
| **Virtual Processor Core (VPC)** | Cloud/container: licensed per virtual core used at peak; 1:1 VPC ratio for ACE on CP4I |
| **Authorised User** | Named-user licensing for specific tooling and development scenarios |
| **Install** | Fixed-fee per installation (certain ACE standalone scenarios) |

**FAQ:** See `App Connect - Frequently Asked Questions (FAQ).PDF`
**Full guide:** See `App Connect - Ultimate Guide to Entitlement, Parts and Licenses.PDF`

---

### 5.3 VPC Licensing on CP4I

When ACE is deployed as part of CP4I:

- ACE is licensed via **CP4I VPC entitlement**
- VPC is consumed by **chargeable containers only**: `IntegrationRuntime` pods, `DesignerAuthoring` pods
- Non-chargeable: `IntegrationDashboard`, `SwitchServer`, `Configuration`, CP4I Platform UI
- **License ratio:** 1 CP4I VPC = 1 ACE VPC (no conversion required)
- The **IBM License Service** (non-chargeable) automatically reports actual VPC consumption from the cluster
- License Service data is used for compliance reporting; exportable as CSV

**Best practices for VPC optimisation:**
- Use resource `requests` (not `limits`) to right-size pods — License Service counts requests
- Use node selectors and anti-affinity to colocate chargeable pods efficiently
- Monitor consumption monthly via the License Service dashboard

---

## 6. Migration

### 6.1 IIB to ACE v13

IBM Integration Bus (IIB v9/v10) users are encouraged to migrate to ACE v13 for continued support, cloud-native capabilities, and AI features.

**Migration steps (high level):**

1. **Assess** — export IIB message flows and BAR files; identify deprecated nodes and ESQL constructs
2. **Test** — import into ACE Toolkit; run built-in unit tests and regression tests
3. **Adapt** — update deprecated nodes (e.g., `JavaCompute` node changes; certain v9 message set constructs)
4. **Validate** — use ACE's built-in migration validation tool to check compatibility
5. **Deploy** — deploy updated BAR files to ACE v13 Integration Server or IntegrationRuntime (CP4I)

**Key compatibility notes:**
- Most IIB v9/v10 flows run on ACE v13 with little or no modification
- ESQL is fully forward-compatible
- Some deprecated routing and aggregation nodes require replacement
- Java Compute nodes must use ACE v13 class libraries (Java 17)

**Docs in this folder:**
- `App Connect - Why migrate from IIB to ACE.PPTX`
- `IIB to ACE migration summary.PPTX`
- `App Connect - Migrating IIB to Ace v13.PPTX`

---

### 6.2 ACE v11/v12 to ACE v13

Customers on ACE v11 or v12 should migrate to v13 to benefit from:
- AI-powered development features (AI mapping, watsonx Code Assistant)
- MCP Server / Agentic AI support
- Discovery Connectors (Toolkit access to 200+ connector catalogue)
- App Connect Private Networks (CP4I 16.2+)
- Latest connector library updates (Apache Pulsar, AstraDB, Databricks, SAP SuccessFactors, etc.)
- z/OS Container Extensions improvements
- Extended support lifecycle (SC3 — 3-year window)
- Embedded Global Cache (replaces deprecated WebSphere eXtreme Scale)
- Single container runtime architecture for simpler operations

**Migration approach:**
- ACE v11/v12 BAR files are **directly compatible** with ACE v13 — no code changes required in most cases
- ACE 12 and ACE 13 share the same integration node/server structure and disk storage formats
- Simply redeploy existing BAR files on ACE v13 Integration Servers
- Update `IntegrationServer` CR references to `IntegrationRuntime` (if on CP4I)
- Test end-to-end before switching production traffic
- Use the modernised `mqsiextractcomponents` / `ibmint` commands for component extraction and migration

**Docs in this folder:** `App Connect - Migrating ACE v11_12 to ACE v13.PPTX`

---

### 6.3 Migration Waiver Programme

IBM offers a **migration waiver programme** to help customers still on IIB/ACE v11/v12 transition without immediate licence cost implications.

**What the waiver covers:**
- Temporary entitlement to run both old and new versions simultaneously during migration
- Defined time-bound migration window (typically 12–24 months)
- Access to IBM migration services and technical support

**Eligibility:** Active IBM Software Subscription & Support on IIB or ACE v11/v12

**Docs in this folder:** `App Connect - IBM ACE IIB Migration Waiver (April 2025).DOCX`

---

## 7. What's New — ACE v13 Modification Packs

ACE v13 follows a **quarterly modification pack** release cadence. Below is a feature summary per release.

### ACE 13.0.1.0 (September 2024)

| Feature | Description |
|---|---|
| **ACE Designer in standalone software** | Designer low-code authoring available in ACE software (not just containers) for the first time |
| **Java 17 default** | Java 17 is the default runtime for ACE 13 integration servers and Toolkit |
| **Eclipse 4.31 Toolkit** | Toolkit updated to Eclipse 4.31 |
| **Improved Toolkit UI** | Modernised look and feel; simplified node and message model creation |
| **Extended tutorials catalog** | 100+ tutorials on the Toolkit Welcome page |
| **Patterns Gallery** | New patterns framework for generating solution artefacts quickly |
| **100+ smart connectors** | Designer includes 100+ pre-built connector catalogue |
| **External Directory Vault Explorer** | Manage connector credentials from within the Toolkit |
| **mqsiextractcomponents modernised** | Replaced with new `ibmint`-style command for easier migration |

---

### ACE 13.0.2.0 (December 2024)

| Feature | Description |
|---|---|
| **Avro support on Kafka nodes** | Kafka nodes support serialising/deserialising JSON via Avro schema |
| **HTTPS in Flow Exerciser** | Flow Exerciser supports HTTPS endpoints for testing |
| **Discovery Connector Request nodes** | New discovery connector request nodes added |
| **Business Transaction Monitoring: PostgreSQL + MSSQL** | BTM now supported on Microsoft SQL Server and PostgreSQL |
| **IPv6 support** | Internet Protocol version 6 support in HTTP connector |
| **ibmint Bash auto-completion** | `ibmint` commands auto-complete in Bash shell |
| **PostgreSQL stored procedures** | Support for PostgreSQL stored procedures with dynamic result sets |
| **Designer authoring enhancements** | Various Designer UX improvements |
| **Decimal timeout on TCPIP nodes** | Support for decimal timeout values on TCPIP nodes |

---

### ACE 13.0.3.0 (March 2025)

| Feature | Description |
|---|---|
| **Embedded Global Cache** | New in-memory caching replacing deprecated WebSphere eXtreme Scale (WXS); supports replication across servers via `server.conf.yaml` |
| **Container Explorer in Toolkit** | Manage ACE certified container dashboard resources from within the Toolkit |
| **Discovery connector nodes** | New and updated Discovery Connector nodes |
| **HTTP proxy for Salesforce** | Salesforce Input/Request nodes now support HTTP proxy; 24 connectors support proxy total |
| **Domain checking in callable flows** | Domain checking capability in callable message flows |
| **HTTP Request node Retry** | New Retry properties tab on the HTTP Request node |
| **HTTPS-secured mqsi commands** | Core `mqsi` commands secured via HTTPS; `--output-uri`, `--https`, `--ssl` parameters added |
| **ACE Professional orchestration converter** | Utility to convert IBM App Connect Professional orchestrations to ACE message flows |

---

### ACE 13.0.4.0 (June 2025)

| Feature | Description |
|---|---|
| **watsonx Code Assistant in Toolkit** | AI code suggestions and completions in the Toolkit ESQL/Java editor |
| **AI Mapping Assist (Designer)** | AI suggests field mappings between source and target |
| **AI Data Assist (Designer)** | AI-powered data transformation assistance |
| **Context Trees in Toolkit** | Read-only Context Tree for Discovery Connector node output in Compute, Trace, Debugger, and Flow Exerciser |
| **Redis connections** | Support for connecting to Redis data stores |
| **MQTT v5 support** | Explicit support for MQTT protocol version 5 in MQTT Publish/Subscribe policies |
| **Kafka OpenTelemetry** | OpenTelemetry tracing support for Kafka nodes |
| **ESQL OpenTelemetry functions** | ESQL functions for emitting OpenTelemetry spans |
| **Outbound OAuth 2.0** | Bearer token / OAuth 2.0 support on REST Request and HTTP Request nodes |
| **Discovery nodes: Amazon EventBridge, Azure Service Bus** | New Discovery Input nodes; Azure Service Bus also has Request node |
| **Discovery nodes: IBM Planning Analytics** | New Discovery Request node for IBM Planning Analytics |
| **Salesforce Input — state persistence policy** | State persistence policy for Salesforce Input node |
| **webMethods Hybrid Integration** | Integration with IBM webMethods Hybrid Integration platform |
| **Embedded Global Cache upsert** | New upsert method on Embedded Global Cache for JavaCompute nodes (enhanced in v13.0.5) |

---

### ACE 13.0.5.0 (September 2025)

| Feature | Description |
|---|---|
| **Kafka Transactions** | Transactional messaging support on Kafka nodes (`read_uncommitted` / `read_committed`) |
| **Kafka Scaling** | Scale message processing across Kafka consumers |
| **Kafka Timestamp local env properties** | New local environment properties for Kafka timestamp data |
| **AI RAG Pattern (Patterns Gallery)** | New "AI Patterns" category: RAG pattern using Pinecone vector DB + watsonx.ai LLM |
| **Context tree in Flow Debugger/Exerciser** | Enhanced context tree visibility during debugging |
| **Context tree in JavaCompute** | Context tree accessible programmatically from JavaCompute nodes |
| **CONTEXTREFERENCE enhancements** | Enhancements to `CONTEXTREFERENCE` ESQL function; new `CONTEXTINVOCATIONNODE` function |
| **Upsert global cache (JavaCompute)** | `upsert` function available on global cache for JavaCompute nodes |
| **Node admin with SwitchServer and Dashboard** | Node administration integration with Switch Server and Dashboard |
| **New local env variables for REST nodes** | Additional REST node local environment variables |
| **Discovery connector nodes** | New and updated Discovery Connector nodes |
| **Designer account renaming** | Rename connector accounts at creation time in Designer |

---

### ACE 13.0.6.0 (December 2025)

| Feature | Description |
|---|---|
| **New Discovery Input nodes** | Apache Pulsar, AstraDB, Databricks, SAP SuccessFactors |
| **Retry capability for Toolkit REST Request node** | Configure retry logic on Toolkit REST Request node (`No retry`, `ECONNREFUSED`, etc.) |
| **OpenAPI import in Policy Editor** | Import OpenAPI spec to generate policy configuration |
| **Improved Policy Editor usability** | Usability improvements across Toolkit Policy Editor |
| **State Persistence Policies for Scheduler node** | Configure missed event mode and advanced scheduler settings |
| **New ACE Diagnostics Tool functions** | `traceAnalysis`, `splitTraceThreads`, `extractUserTrace`, `extractSyslogAndErrorEntries`, `activityLogAnalysis`, `splitAccountingAndStatsCSVFiles`, `parserManagerAnalysis` |
| **OAuth 2.0 on various connectors** | Outbound OAuth 2.0 expanded to more connector types |

---

### ACE 13.0.7.0 (March 2026 / SC3 Operator)

This is the SC3 operator release. Major changes:

| Feature | Description |
|---|---|
| **MCP Server — on-premises** | Expose any ACE Integration Server as an MCP Server from the ACE Web UI; existing REST APIs become MCP tools |
| **MCP Server — containers** | New "Model Context Protocol (MCP) servers" page in App Connect Dashboard to create and manage MCP servers |
| **Single `runtime` container** | All IntegrationRuntime pods now use a single container — Designer flows, Toolkit flows, and MCP server hosting all run in one container |
| **ACE AI Agent (Preview)** | Embedded agentic AI chat in App Connect Dashboard for operational assistance |
| **Designer Batch Processing** | New Batch Process node in Designer for asynchronous large-dataset operations |
| **Claim Check for Discovery Connectors** | Binary Data Handling property: `Create claim check token` or `Stream data into message tree` on Discovery Connector Request nodes |
| **Event Resilience policy** | Persist Discovery Connector Input events to Kafka for durability |
| **SASL/OAUTHBEARER on Kafka nodes** | KafkaConsumer, KafkaProducer, and KafkaRead nodes support SASL/OAUTHBEARER authentication |
| **WS-Security in Java 17** | WS-Security and WS-ReliableMessaging settings for SOAP nodes in Java 17 integration servers |
| **SC3 Operator — 3-year support** | App Connect Operator v13.0.0 with 3-year support window; replaces CD (v12.x) and SC2 (v12.0.x) releases |

---

### ACE 13.0.8.0 (June 2026 — Latest)

| Feature | Description |
|---|---|
| **Connectors as MCP tools** | App Connect connector catalogue exposed as MCP tools, giving AI agents direct governed access to enterprise applications |
| **Ongoing Discovery Connector additions** | Additional connector nodes and policy types |
| **Security and maintenance** | Ongoing security patches and runtime updates |

---

## 8. Seller Enablement & Customer Conversations

### 8.1 Customer 101 — Basics

Designed for initial conversations with customers who are new to IBM App Connect.

**Key messages:**
- ACE is IBM's flagship integration platform — connects any app, data, or service
- Works on-prem, in containers (CP4I), or hybrid — customer chooses
- Low-code Designer for business users; pro-code Toolkit for developers
- IIB customers: a natural, backward-compatible path forward; ACE 12/13 share the same architecture
- AI features reduce integration development time significantly
- ACE 13 introduces Discovery Connectors — Toolkit developers now access the same 200+ connector catalogue as Designer

**Docs in this folder:** `App Connect - Customer 101.PDF`, `App Connect - Back to Basics.PDF`

---

### 8.2 Customer 201 — Intermediate

For customers who already know ACE and want to explore advanced capabilities.

**Key topics:**
- Containerisation strategy: migrating from VM-based ACE to CP4I (or standalone OpenShift with ACE Certified Container)
- GitOps and DevOps patterns for integration flows
- Discovery Connectors: extending reach to SaaS applications from Toolkit
- Event-driven integration with IBM Event Streams (Kafka) — transactions, scaling, OAUTHBEARER auth
- MQ cross-sell: adding reliable messaging to ACE deployments
- ACE AI capabilities: AI mapping, watsonx Code Assistant, RAG Patterns Gallery

**Docs in this folder:** `App Connect - Customer 201.PPTX`

---

### 8.3 Customer 301 — Advanced

For technical architects and senior decision-makers.

**Key topics:**
- Enterprise-scale ACE architecture (multi-cluster, multi-region)
- HA and DR design patterns for ACE; Event Resilience with Kafka
- Licensing optimisation with CP4I VPC pooling
- Agentic AI integration: App Connect MCP Server deep dive (on-prem and containers); ACE AI Agent
- Unified Management across containers and VMs (App Connect Private Networks)
- Security: TLS, mutual auth, FIPS compliance, secret management (Kubernetes Secrets, Vault), HTTPS-secured admin API
- Custom node development (Java 17): extending ACE with proprietary logic
- OpenTelemetry tracing for observability; ACE Diagnostics Tool for operational analysis
- SC3 Operator: 3-year support planning

**Docs in this folder:** `App Connect - Customer 301.PPTX`

---

### 8.4 ACE vs. Competitors

| Dimension | IBM ACE v13 | MuleSoft Anypoint | Boomi AtomSphere | Dell Boomi / TIBCO |
|---|---|---|---|---|
| **Deployment** | On-prem, Container, Hybrid | Cloud-first, Hybrid | Cloud SaaS | Cloud, On-prem |
| **IIB Migration** | Native — full BAR compatibility; same architecture as ACE 12 | Migration required | Migration required | Migration required |
| **Agentic AI (Outbound)** | MCP Server GA (v13.0.7+) — expose flows + connectors as MCP tools | Preview / limited | Not available | Not available |
| **Agentic AI (Inbound)** | ACE AI Agent embedded in Dashboard (Public Preview) | Limited | Not available | Not available |
| **z/OS Support** | Native zCX | No | No | Limited |
| **MQ Integration** | Native, deep | Adapter-based | Adapter-based | Adapter-based |
| **Kafka Integration** | Native (Event Streams); transactions, Avro, OAUTHBEARER | Connector | Connector | Connector |
| **AI Development** | AI flow gen + AI mapping + AI data assist + watsonx Code Assist + RAG Patterns | Partial AI assist | Partial AI assist | Minimal |
| **Discovery Connectors** | 200+ connectors in Toolkit + Designer | Connector library | Connector library | Connector library |
| **Support Lifecycle** | SC3 — 3 years (Operator v13.0.0) | Annual subscription | Annual | Annual |
| **Licensing** | VPC / PVU / RVU flexible | Named user + capacity | Named user | Capacity-based |

**Docs in this folder:** `App Connect - ACE Solution Brief.PDF`, `App Connect - Back to Basics.PDF`

---

## 9. Best Practices & Guidance

### Integration Design Best Practices

- **Stateless flows** — avoid storing state in the integration server; use MQ or a database for durability; use Kafka + Event Resilience policy for event-driven durability
- **Error handling** — always implement `Catch` nodes and dead-letter queues (DLQs) on MQ-based flows
- **Idempotency** — design flows to safely reprocess duplicate messages (use message IDs and idempotency keys)
- **Timeout handling** — configure timeouts on all HTTP and database nodes; use the HTTP Request node Retry feature for transient failures (v13.0.3+)
- **Structured logging** — use ACE trace nodes or `UserTrace` for structured log output; integrate with OpenShift logging stack; use ACE Diagnostics Tool for offline analysis
- **Flow granularity** — prefer multiple small flows over single large monolithic flows; improves testability and maintainability
- **Policy Projects** — externalise all credentials, endpoints, and timeouts into Policy Projects / connector policies; never hardcode in flows
- **BAR file hygiene** — keep BAR files small; only include required flows; use separate BAR files per bounded context
- **Context Trees** — use Context Trees in Discovery Connector flows to inspect outputs at each step; reduces debugging time
- **Embedded Global Cache** — use for in-memory inter-server state sharing; configure replication in `server.conf.yaml`; prefer stateless flows where possible

### CP4I / Container Deployment Best Practices

- Use `IntegrationRuntime` CRs (not `IntegrationServer`) on CP4I 16.1.3+
- Target runtime version **13.0.7.0-r1 or later** to benefit from the single `runtime` container architecture
- Store `Configuration` CRs in Git for GitOps-compatible deployments
- Use Kubernetes resource `requests` correctly — License Service counts requests for VPC compliance
- Apply `PodDisruptionBudget` on production runtimes
- Configure Topology Spread Constraints to distribute pods across AZs
- Use separate namespaces per environment (dev, test, prod)
- Enable OADP Backup & Restore for disaster recovery
- Enable OpenTelemetry on `IntegrationRuntime` for distributed tracing

### Security Best Practices

- Use Kubernetes Secrets or HashiCorp Vault for all credentials; reference via `Configuration` CR or external directory vault (on-prem)
- Enable TLS for all inbound HTTP endpoints; Admin API is HTTPS by default in ACE 13
- Use mutual TLS (mTLS) for internal flow-to-flow communication
- Apply RBAC: only grant `admin` CP4I roles to operators; use `viewer` for monitoring teams
- Enable FIPS 140-2 mode for government/regulated deployments
- Audit all API flows via DataPower Gateway rate limiting and policy enforcement
- For MCP Server: configure Basic Auth or TLS secrets on the `spec.mcp.runtime.*` CR parameters; never expose MCP endpoints without authentication

**Docs in this folder:** `App Connect - Best practices and guidance for ACE on CP4I.DOCX`

---

## 10. Frequently Asked Questions

**Q: Can I run ACE without CP4I?**
Yes. ACE can be installed standalone on Linux, Windows, AIX, or z/OS. For containers, you can use ACE Certified Container on OpenShift without CP4I. CP4I provides the broader IBM integration platform experience but is not required.

**Q: Are my IIB flows compatible with ACE v13?**
In most cases, yes. IIB v9/v10 BAR files can be deployed directly to ACE v13 Integration Servers. Some deprecated nodes and specific ESQL constructs may require updates. Use the ACE Toolkit migration validator.

**Q: Are my ACE v12 flows compatible with ACE v13?**
Yes — ACE 12 and ACE 13 share the same architecture. In almost all cases, ACE v12 BAR files run directly on ACE v13 without modification.

**Q: What is the difference between ACE and IBM App Connect (SaaS)?**
IBM App Connect (SaaS, formerly App Connect on IBM Cloud) is a fully managed cloud service. ACE (App Connect Enterprise) is the self-managed, on-prem/container version. They share the Designer low-code experience and connector catalogue but differ in deployment model and capability depth.

**Q: Does ACE support API management?**
ACE can expose integration flows as REST APIs and perform basic API governance. For full API lifecycle management (developer portal, analytics, monetisation), pair ACE with **IBM API Connect** (available as a CP4I component).

**Q: Can ACE connect to Kafka/Event Streams?**
Yes. ACE has native Kafka protocol support. It can produce to and consume from Kafka topics (Event Streams or any Apache Kafka). Kafka flows support transactions, Avro schema, SASL/OAUTHBEARER auth, OpenTelemetry tracing, and message scaling as of v13.0.5.

**Q: What is the App Connect MCP Server?**
It is an ACE feature (v13.0.7+) that exposes integration flows (and connectors from v13.0.8+) as MCP-protocol tools, allowing AI agents (Claude, GitHub Copilot, IBM Bob, etc.) to invoke real-time integrations as part of their AI reasoning chains. See Section 3 for full details.

**Q: What is the ACE AI Agent?**
It is an embedded agentic AI chat experience inside the App Connect Dashboard (containerised). Currently in Public Preview. It provides conversational assistance for operational tasks — listing runtimes, describing flows, troubleshooting, answering product questions.

**Q: How is ACE licensed on CP4I?**
ACE is licensed via CP4I VPCs (Virtual Processor Cores). Chargeable containers include `IntegrationRuntime` and `DesignerAuthoring` pods. License Service automatically tracks consumption. See Section 5 for full details.

**Q: Is there a migration waiver for IIB customers?**
Yes. IBM offers a time-bound migration waiver allowing customers to run both IIB and ACE v13 simultaneously during transition. See `App Connect - IBM ACE IIB Migration Waiver (April 2025).DOCX` for current terms.

**Q: What is the new Embedded Global Cache?**
Introduced in v13.0.3, the Embedded Global Cache replaces the deprecated WebSphere eXtreme Scale (WXS) for in-memory data caching. It is configured in `server.conf.yaml` and supports replication across ACE integration servers without requiring a third-party product.

**Q: What is the SC3 Operator?**
SC3 (Support Cycle 3) is the App Connect Operator release (v13.0.0) launched in March 2026 with a 3-year support window. It replaces both the CD releases (v12.x) and SC2 (v12.0.x). It ships with ACE v13 runtime and introduces the single `runtime` container architecture.

**Docs in this folder:** `App Connect - Frequently Asked Questions (FAQ).PDF`

---

## 11. MQ + MFT Cross-Sell

IBM App Connect and IBM MQ are **complementary products** that together deliver a complete integration and messaging platform.

### Why ACE + MQ?

| Scenario | ACE Role | MQ Role |
|---|---|---|
| System-to-system integration | Routes and transforms data between systems | Provides guaranteed delivery of messages between ACE and target systems |
| File transfer integration | Triggers flows on file arrival; processes file content | MFT (Managed File Transfer) moves files reliably with audit trail |
| Event-driven microservices | Subscribes to MQ queues; triggers downstream APIs/services | Persists events in queues; decouples producers and consumers |
| Hybrid cloud bridge | Connects cloud-native apps to on-prem legacy systems | MQ provides the reliable transport layer across network boundaries |

### MQ + MFT Cross-Sell Positioning

- **MFT + ACE = complete file integration** — MFT handles reliable file movement; ACE processes file content
- **MQ + ACE = transactional integration** — MQ provides assured delivery; ACE performs transformation and routing
- Most large ACE deployments already use MQ; if a customer only has ACE, MQ is a high-probability add-on
- **IBM MQ 9.4.4** (Oct 2025): Native HA & Cross-Region Replication on Linux; IBM MQ as a Service on AWS; IBM MQ Agent (AI-powered, via watsonx.ai)

**Docs in this folder:**
- `App Connect - IBM ACE for MQ+MFT.PPTX`
- `Client Leave Behind MQ+MFT Crossell.PDF`
- `IBM ACE for MQ+MFT.PPTX`

---

## 12. Useful Links & Resources

### Official Documentation

| Resource | Link |
|---|---|
| IBM App Connect Enterprise Docs (v13) | https://www.ibm.com/docs/en/app-connect/13.0.x |
| ACE What's New v13 | https://www.ibm.com/docs/en/app-connect/13.0.x?topic=overview-whats-new-in-version-130 |
| New function — ACE 13.0 Modification Packs | https://www.ibm.com/docs/en/app-connect/13.0.x?topic=wniv1-new-function-added-in-app-connect-enterprise-130-modification-packs |
| ACE on CP4I Docs | https://www.ibm.com/docs/en/cloud-paks/cp-integration (App Connect section) |
| Integration Runtime Reference | https://www.ibm.com/docs/en/app-connect/13.0.x?topic=resources-integration-runtime-reference |
| MCP in ACE Docs | https://www.ibm.com/docs/en/app-connect/13.0.x?topic=tools-what-is-mcp |
| Using ACE AI Agent | https://www.ibm.com/docs/en/app-connect/13.0.x?topic=dashboard-using-app-connect-enterprise-agent |
| ACE 13.0 Release Notes | https://www.ibm.com/support/pages/ibm-app-connect-enterprise-130-release-notes |
| IBM Support Portal | https://www.ibm.com/support |
| IBM ACE Fix Central | https://www.ibm.com/support/fixcentral |
| IBM ACE Product Page | https://www.ibm.com/products/app-connect |

### Learning & Community

| Resource | Link |
|---|---|
| IBM Community — App Connect Blog | https://community.ibm.com (search "App Connect") |
| ACE 13.0.x Release Blog Posts | https://community.ibm.com/community/user/blogs/ben-thompson1 |
| ACE Operator Release Blogs | https://community.ibm.com/community/user/blogs/rob-convery1 |
| IBM Developer — App Connect | https://developer.ibm.com/components/app-connect/ |
| IBM TechXchange Community | https://community.ibm.com |
| ACE GitHub (samples & labs) | https://github.com/ot4i |
| IBM Redbooks — ACE | https://www.redbooks.ibm.com (search "App Connect Enterprise") |
| ACE Agents Preview | https://ibm.biz/ace-agents |

**Docs in this folder:** `App Connect Useful Links.PDF`

---

## 13. Glossary

| Term | Definition |
|---|---|
| **ACE** | IBM App Connect Enterprise — the enterprise integration platform |
| **IIB** | IBM Integration Bus — the predecessor to ACE (v9, v10) |
| **BAR** | Broker Archive — compiled, deployable package of integration flows |
| **Integration Flow** | A message flow that routes, transforms, and processes data between systems |
| **Integration Server** | The runtime process that executes integration flows (on-prem) |
| **IntegrationRuntime** | The Kubernetes CR for running ACE flows on CP4I/OpenShift; from v13.0.7.0-r1+ uses a single `runtime` container |
| **Designer** | The browser-based low-code authoring environment; available in ACE software from v13.0.1+ |
| **Toolkit** | The Eclipse 4.31-based pro-code IDE; runs on Java 17 by default |
| **Smart Connector** | A pre-built, managed no-code connection available in Designer |
| **Discovery Connector** | Toolkit-native connector node that uses the Designer connector backend; Toolkit access to the 200+ connector catalogue |
| **MCP** | Model Context Protocol — open protocol (JSON-RPC + Streamable HTTP) for AI agents to invoke tools/services |
| **MCP Server** | The ACE component that exposes integration flows and connectors as MCP-callable tools (v13.0.7+) |
| **ACE AI Agent** | Agentic AI chat embedded in the App Connect Dashboard for operational assistance (Public Preview, v13.0.7+) |
| **ESQL** | Extended SQL — ACE's transformation scripting language |
| **DFDL** | Data Format Description Language — ACE's schema language for legacy data formats |
| **Policy Project** | An ACE project type for externalising configuration (endpoints, credentials, connector policies) |
| **Embedded Global Cache** | In-memory caching capability (v13.0.3+) replacing deprecated WebSphere eXtreme Scale |
| **RAG Pattern** | Retrieval-Augmented Generation — AI Pattern in the Toolkit Patterns Gallery using Pinecone + watsonx.ai |
| **VPC** | Virtual Processor Core — the licensing unit for ACE on CP4I |
| **PVU** | Processor Value Unit — the licensing unit for on-premises ACE |
| **MFT** | Managed File Transfer — reliable, auditable file movement (part of MQ Advanced) |
| **CP4I** | IBM Cloud Pak for Integration — the OpenShift-based integration platform |
| **OADP** | OpenShift API for Data Protection — Kubernetes-native backup and restore |
| **zCX** | z/OS Container Extensions — run Linux containers on z/OS hardware |
| **LTS / SC3** | Long-Term Support Cycle 3 — App Connect Operator v13.0.0, 3-year support window (launched March 2026) |
| **SC2** | Long-Term Support Cycle 2 — App Connect Operator v12.0.x (now superseded by SC3) |
| **CD** | Continuous Delivery — previous rapid-release operator track (v12.x), replaced by SC3 |
| **GitOps** | A deployment approach where all configuration is stored in Git and applied declaratively |
| **OpenTelemetry** | Open standard for distributed tracing; supported on Toolkit flows via `IntegrationRuntime` CR and on Kafka nodes (v13.0.4+) |
| **Context Tree** | Read-only in-memory tree populated by Discovery Connector nodes; accessible in subsequent nodes, debugger, and exerciser (v13.0.4+) |
| **Event Resilience policy** | Policy configurable on Discovery Connector Input nodes to persist incoming events to Kafka (v13.0.7+) |
| **Claim Check** | Pattern for handling large binary payloads in Discovery Connector Request nodes (v13.0.7+) |
| **watsonx Code Assistant** | IBM AI coding assistant integrated into the ACE Toolkit for ESQL/Java (v13.0.4+) |

---

> **Document notes:** This knowledge base synthesises content from the ACE documentation files in this folder and from [IBM Documentation](https://www.ibm.com/docs/en/app-connect) (crawled July 2025, covering ACE v13.0.1–v13.0.8). For the latest official information, always refer to the IBM Documentation and the specific PDFs, PPTXs, and DOCXs in this directory.

---

*Made with IBM Bob*

---

<!-- KB:AUTO-INDEX:START -->

## 📁 Folder Index

> **26 files** &nbsp;|&nbsp; _Last indexed: 20 Jul 2026 10:17_

| File | Type | Size | Last Modified | Summary |
|---|---|---|---|---|
| `App Connect - ACE Solution Brief.PDF` | PDF | 107.9 KB | 2026-07-15 | IBM App Connect Enterprise is an AI-powered integration platform that unifies apps, APIs, and data across hybrid environments to streamline automat... |
| `App Connect - Agentic AI Client Presentation.PDF` | PDF | 921.5 KB | 2026-06-11 | IBM App Connect Enterprise introduces an agentic AI client that uses conversational AI and real-time intelligence to optimize and modernize enterpr... |
| `App Connect - Agentic AI Client Presentation.PPTX` | PPTX | 9.9 MB | 2026-07-15 | PPTX file |
| `App Connect - Agentic AI leave behind.PDF` | PDF | 123.2 KB | 2026-06-11 | IBM App Connect Enterprise introduces agentic AI tools, including MCP and multiple AI agents, to enhance integration operations with insights, guid... |
| `App Connect - Back to Basics.PDF` | PDF | 1.5 MB | 2026-07-15 | The document introduces IBM App Connect Enterprise v12, explaining its role in solving integration challenges by connecting siloed applications, en... |
| `App Connect - Best practices and guidance for ACE on CP4I.DOCX` | DOCX | 30.6 KB | 2026-07-15 | provides guidance for ACE on CP4I, addressing customer concerns about increased resource requirements and licensing changes when migrating from tra... |
| `App Connect - Customer 101.PDF` | PDF | 3.2 MB | 2026-06-11 | The document outlines IBM App Connect Enterprise's purpose, target audience, and structure, focusing on its role in enterprise application integrat... |
| `App Connect - Customer 201.PPTX` | PPTX | 34.3 MB | 2026-07-15 | PPTX file |
| `App Connect - Customer 301.PPTX` | PPTX | 115.2 MB | 2026-07-15 | PPTX file |
| `App Connect - Frequently Asked Questions (FAQ).PDF` | PDF | 4.5 MB | 2026-07-15 | The document provides a comprehensive list of frequently asked questions about IBM App Connect Enterprise, covering deployment options, product fea... |
| `App Connect - High Availability.PPTX` | PPTX | 633.6 KB | 2026-07-15 | PPTX file |
| `App Connect - IBM ACE IIB Migration Waiver (April 2025).DOCX` | DOCX | 32.0 KB | 2026-07-15 | The document outlines instructions for submitting a migration waiver request for IBM App Connect Enterprise/IIB, including required details, approv... |
| `App Connect - Migrating ACE v11_12 to ACE v13.PPTX` | PPTX | 6.2 MB | 2026-07-15 | PPTX file |
| `App Connect - Migrating IIB to Ace v13.PPTX` | PPTX | 16.1 MB | 2026-07-15 | PPTX file |
| `App Connect - Ultimate Guide to Entitlement, Parts and Licenses.PDF` | PDF | 1.5 MB | 2026-07-15 | The document outlines IBM App Connect's licensing models, product parts, pricing, trade-up options, and support details for various deployment envi... |
| `App Connect - Why migrate from IIB to ACE.PPTX` | PPTX | 19.9 MB | 2026-07-15 | PPTX file |
| `App Connect MCP 101.PDF` | PDF | 1.4 MB | 2026-06-11 | The document explains how IBM App Connect and Model Context Protocol address the lack of operational, business, and system context in AI models wit... |
| `App Connect MCP Server One Pager.PDF` | PDF | 105.3 KB | 2026-06-11 | The document outlines how IBM App Connect Enterprise enables secure, governed AI app integrations through controlled access, data compliance, polic... |
| `App Connect Seller Enablement.PPTX` | PPTX | 74.2 MB | 2026-07-15 | PPTX file |
| `App Connect Useful Links.PDF` | PDF | 128.1 KB | 2026-07-15 | The document provides useful links for IBM App Connect, including documentation, community resources, fix packs, and support information for variou... |
| `Client Leave Behind MQ+MFT Crossell.PDF` | PDF | 109.2 KB | 2026-07-15 | The document discusses how IBM App Connect integrates with MQ and Sterling MFT to enable real-time data processing and automation, overcoming the l... |
| `IBM ACE for MQ+MFT.PPTX` | PPTX | 3.7 MB | 2026-07-15 | PPTX file |
| `IBM App Connect Client Leave Behind.PDF` | PDF | 80.0 KB | 2026-06-11 | IBM App Connect Enterprise addresses integration challenges in the AI era by unifying legacy systems, hybrid cloud workloads, and AI models through... |
| `IIB to ACE migration summary.PPTX` | PPTX | 176.5 KB | 2026-07-15 | PPTX file |
| `Introduction to App Connect Enterprise Toolkit.PPTX` | PPTX | 89.5 MB | 2026-07-15 | PPTX file |
| `Marketing Business Plan App Connect.PDF` | PDF | 346.4 KB | 2026-07-15 | The document outlines a marketing business plan template compendium, covering product positioning, market analysis, customer segmentation, competit... |

<!-- KB:AUTO-INDEX:END -->
