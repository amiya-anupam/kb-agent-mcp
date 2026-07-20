# IBM Cloud Pak for Integration (CP4I) — Complete Knowledge Base

> **Latest Version:** 16.2.0 (Long-Term Support, GA: 30 June 2026)
> **Product ID (PID):** 5737-I89
> **Lifecycle Policy:** Support Cycle-Other (SC-O): Custom — up to 6 years
> **Source:** [IBM Docs Landing Page](https://www.ibm.com/docs/en/cloud-paks/cp-integration) | [Product Page](https://www.ibm.com/products/cloud-pak-for-integration)

---

## Table of Contents

1. [Welcome & Overview](#1-welcome--overview)
2. [Core Components](#2-core-components)
   - [Platform UI](#21-platform-ui)
   - [Assemblies](#22-assemblies--integration-assemblies)
   - [Automation Assets](#23-automation-assets)
   - [IBM API Connect](#24-ibm-api-connect)
   - [IBM App Connect](#25-ibm-app-connect)
   - [IBM MQ](#26-ibm-mq)
   - [IBM Event Streams](#27-ibm-event-streams)
   - [IBM Event Endpoint Management](#28-ibm-event-endpoint-management)
   - [IBM DataPower Gateway](#29-ibm-datapower-gateway)
   - [IBM Aspera HSTS](#210-ibm-aspera-hsts)
   - [End-to-End Monitoring](#211-end-to-end-monitoring)
3. [AI Capabilities — CP4I Agent](#3-ai-capabilities--cp4i-agent)
4. [Planning](#4-planning)
   - [System Requirements](#41-system-requirements)
   - [Licensing & Entitlements](#42-licensing--entitlements)
   - [Structuring Your Deployment](#43-structuring-your-deployment)
   - [Workload Placement](#44-workload-placement)
   - [Single Node OpenShift (SNO)](#45-single-node-openshift-sno)
   - [Logging Planning](#46-logging-planning)
   - [Cluster Monitoring Planning](#47-cluster-monitoring-planning)
   - [Custom Images](#48-custom-images)
   - [Disaster Recovery](#49-disaster-recovery)
   - [Additional Services](#410-additional-services)
5. [Installing](#5-installing)
   - [Overview of Installation Steps](#51-overview-of-installation-steps)
   - [Express Installation](#52-express-installation)
   - [Adding Catalog Sources & Mirroring Images](#53-adding-catalog-sources--mirroring-images)
   - [Installing Operators](#54-installing-operators)
   - [Entitlement Key](#55-entitlement-key)
   - [Deploying the Platform UI](#56-deploying-the-platform-ui)
   - [Automated Installation](#57-automated-installation)
   - [Deploying Instances](#58-deploying-instances)
   - [Installing on AKS](#59-installing-on-azure-kubernetes-service-aks)
6. [Uninstalling](#6-uninstalling)
7. [Upgrading](#7-upgrading)
8. [Using the Cloud Pak](#8-using-the-cloud-pak)
   - [Using the Platform UI](#81-using-the-platform-ui)
   - [Using the CP4I Agent](#82-using-the-cp4i-agent)
9. [Tutorials](#9-tutorials)
10. [Migrating to CP4I](#10-migrating-to-cp4i)
11. [Troubleshooting](#11-troubleshooting)
    - [Gathering Diagnostics (must-gather)](#111-gathering-diagnostics-must-gather)
    - [Common Issues & Solutions](#112-common-issues--solutions)
12. [Administering](#12-administering)
    - [Developer Reference](#121-developer-reference)
    - [OpenShift Roles & Permissions](#122-openshift-roles--permissions)
    - [Identity & Access Management (IAM)](#123-identity--access-management-iam)
    - [Hostnames & Certificates](#124-hostnames--certificates)
    - [Backup & Restore (OADP)](#125-backup--restore-oadp)
    - [Logging](#126-enabling--using-logging)
    - [OpenShift Monitoring](#127-enabling-openshift-container-platform-monitoring)
    - [IBM Instana Monitoring](#128-enabling-ibm-instana-monitoring)
    - [Cloud Pak Foundational Services](#129-configuring-cloud-pak-foundational-services)
    - [License Service Deployment](#1210-deploying-license-service)
    - [Fix Packs Between Major Releases](#1211-applying-fix-packs-between-major-releases)
    - [Usage Metrics](#1212-usage-metrics)
13. [Reference](#13-reference)
    - [Operator Reference](#131-operator-reference)
    - [Container Images](#132-container-images)
    - [Operator & Instance Versions](#133-operator--instance-versions)
    - [Cluster-Scoped Permissions](#134-cluster-scoped-permissions-for-operators)
    - [Workload Placement for Instances](#135-workload-placement-for-instances)
    - [Security Context Constraints](#136-security-context-constraints-scc)
    - [Community Resources](#137-community-resources)
    - [Glossary](#138-glossary)
14. [Regulatory Compliance](#14-regulatory-compliance)
15. [Version History & What's New](#15-version-history--whats-new)
16. [Support & Resources](#16-support--resources)
17. [Storage Planning](#17-storage-planning)
18. [High Availability](#18-high-availability)
19. [Security and Access Control](#19-security-and-access-control)
20. [IBM Kubernetes Certification](#20-ibm-kubernetes-certification)
21. [Resource Allocation](#21-resource-allocation)
22. [Unified Management](#22-unified-management)
23. [Deployment Layout Guidance](#23-deployment-layout-guidance)
24. [CP4I Packaging and Licensing Deep Dive](#24-cp4i-packaging-and-licensing-deep-dive)
25. [Business Value, ROI, and Customer Case Studies](#25-business-value-roi-and-customer-case-studies)
26. [IBM CP4I Agent — Extended Details](#26-ibm-cp4i-agent--extended-details)
27. [Integration Patterns and Use Cases](#27-integration-patterns-and-use-cases)

---

## 1. Welcome & Overview

**IBM Cloud Pak for Integration (CP4I)** is a comprehensive, container-native, self-managed integration software platform. It unifies APIs, events, messaging, files, and applications under a single control plane. Optimised for **Red Hat OpenShift**, it supports hybrid cloud deployments — on-premises, any cloud, or both.

> *"IBM Cloud Pak for Integration is a comprehensive set of software integration tools within a single, unified experience. With this toolset, you can connect your applications, data, systems, and services, across cloud or on-premises environments, as part of a managed, scalable, and secure deployment that runs on Red Hat OpenShift."*
> — IBM Documentation, Overview

### Key Value Propositions

| Value | Detail |
|---|---|
| **Single control plane** | Manage all integration workloads from one Platform UI |
| **AI-powered operations** | AI accelerates design, deployment, and day-2 operations |
| **Unified Management** | Single pane of glass across multiple clusters and VM environments |
| **Low/no-code** | Create, test, and deploy integrations with AI assistance and no coding |
| **Real-time events** | Process and respond instantly to business events |
| **Reliable messaging** | Transactional, guaranteed message delivery at enterprise scale |
| **Scalability** | Scale from single-node to large multi-node HA environments |
| **Cloud-native + traditional** | Works with container and VM deployments simultaneously |

### Architecture Snapshot

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          Platform UI                                      │
│         (Unified Management Control Plane — single pane of glass)        │
├──────────┬─────────────┬──────────┬──────────┬──────────┬────────────────┤
│ IBM API  │ IBM App     │ IBM MQ   │ IBM      │ IBM      │ IBM Aspera     │
│ Connect  │ Connect     │          │ Event    │DataPower │ HSTS           │
│          │             │          │ Streams  │Gateway   │                │
├──────────┴─────────────┴──────────┴──────────┴──────────┴────────────────┤
│                    Automation Assets  |  Assemblies                      │
├──────────────────────────────────────────────────────────────────────────┤
│                  Cloud Pak Foundational Services (Keycloak, cert-manager)│
├──────────────────────────────────────────────────────────────────────────┤
│            Red Hat OpenShift Container Platform (or AKS / CNCF K8s)     │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Components

The following table lists every component included in CP4I:

| Component | Description |
|---|---|
| **Platform UI** | Central control plane; create, manage, deploy all instances via GUI or YAML canvas |
| **Assemblies** | Connect, manage, and deploy multiple integrations as a single group |
| **Automation Assets** | Repository for storing, sharing, and reusing integration templates |
| **IBM API Connect** | Full API lifecycle: create, manage, secure, socialise, monetise APIs |
| **IBM App Connect** | Low/no-code application integration with 100s of connectors |
| **IBM MQ** | Enterprise messaging — reliable, transactional, guaranteed delivery |
| **IBM Event Streams** | Apache Kafka-based enterprise event streaming platform |
| **IBM Event Endpoint Management** | Governance and discovery portal for event-driven APIs |
| **IBM DataPower Gateway** | High-performance security gateway for APIs and integrations |
| **IBM Aspera HSTS** | Fast, secure file and data transfer at any size or speed |
| **End-to-End Monitoring** | Transaction-level tracing across multiple integration components (16.2+) |
| **CP4I Agent** | LLM-powered conversational AI for operations, health checks, and troubleshooting (16.1.3+) |

---

### 2.1 Platform UI

The Platform UI is the central control plane for all CP4I capabilities.

**Features:**
- Create, view, update, and delete instances of all CP4I components
- **Graphical canvas** — drag-and-drop components, connect them visually, then deploy as a single unit
- **Unified Management** — view and manage instances across multiple OpenShift clusters and VM-based runtimes from one window
- **Location Agent** — deployed in each remote OpenShift cluster; relays instance data back to the hub Platform UI
- **Filterable instances table** — filter by type, namespace, status; URL reflects current filters; exportable as CSV
- **Full-page create/edit layout** (16.2+) — expanded layout for improved usability on wide displays
- **Overview pane** (16.1.3+) — home-page summary of instance statuses across all managed locations; click a status to filter
- **AKS deployment** (16.1.2+) — Platform UI can be deployed on Azure Kubernetes Service
- **Keycloak SSO** — single sign-on across all CP4I UI components via managed Keycloak

**Roles:** Users must be assigned either `admin` or `viewer` role in the Platform UI.

**Non-chargeable:** Platform UI does not consume CP4I VPC entitlement (except when AI Agents are enabled — see Section 3).

---

### 2.2 Assemblies / Integration Assemblies

An **Assembly** (`IntegrationAssembly` Custom Resource) lets you define, manage, and deploy multiple integration instances as a single grouped unit.

**How it works:**
- Author on the **graphical canvas**: drag MQ queues, App Connect runtimes, API products, Kafka topics onto the canvas and connect them together
- Switch to **YAML view** to see the declarative Kubernetes manifest — store in GitOps for repeatable deployments
- **Export as template** to Automation Assets for reuse by other teams
- **Import from Automation Assets** — pull approved assets directly onto the canvas during authoring

**Key behaviours:**
- A single assembly provides a starting point that guides users through deploying all required MQ, Event Streams, App Connect, and API Connect components together
- Deployed as Kubernetes Custom Resources; compatible with GitOps tools (ArgoCD, Tekton, OpenShift Pipelines)

> ⚠️ **Deprecation note (16.1.3):** Assembly-managed instances (where the assembly operator controls instances on the user's behalf) are deprecated. Convert managed instances to independent instances and re-add them to the canvas via labels. The `IntegrationAssembly` status provides conversion instructions and commands.

---

### 2.3 Automation Assets

A **shared repository** for storing, discovering, and reusing integration assets, templates, and approved patterns across teams.

**Capabilities:**
- Store integration flows, API definitions, configuration templates
- Add any asset directly onto the App Connect canvas or Assembly canvas from the repository
- Mark assets as "**approved assets**" — policies enforce that only approved assets are deployable at runtime
- Save in-progress work as a **draft** to continue editing later
- Integration editors open automatically when editing an asset
- **Non-chargeable** — does not consume VPC entitlement

---

### 2.4 IBM API Connect

API Connect provides the full lifecycle of API management — from creation to retirement.

**Sub-components (operators and CRDs):**

| Instance Type | Description |
|---|---|
| `APIConnectCluster` | Top-level CR managing all API Connect subsystems |
| `ManagementCluster` | API Manager subsystem |
| `PortalCluster` | Developer Portal subsystem |
| `AnalyticsCluster` | API Analytics subsystem |
| `GatewayCluster` | API Gateway (DataPower) subsystem |
| **Federated API Management** | Manage multiple distributed gateways from a hub (16.2+) |
| **API Developer Portal** | Expose APIs externally to developers (16.2+) |
| **API Nano Gateway** | Small-footprint cloud-native gateway (16.2+) |

**Key capabilities:**
- **Create APIs** — open-standards API creation; model, develop, test, debug, publish; automated test generation
- **Manage APIs** — organise APIs into API products; version control; full lifecycle governance
- **Secure APIs** — built-in policies (OAuth 2.0, TLS, rate-limiting, threat protection); DataPower Gateway enforces at the edge
- **Socialise APIs** — branded self-service developer portals with community features (blogs, forums)
- **Analyse APIs** — rich usage dashboards; business value visualisation of API traffic
- **Monetise APIs** — create pricing plans and subscription tiers
- **v12 support (16.2+)** — API Connect v12 introduces API Developer Portal, Federated API Management, and API Nano Gateway as new subsystems

**Operator note:** A single API Connect operator can manage multiple API Connect instances when installed globally. Unlike other operators, the API Connect operator can only manage the latest version and upgrades previous versions automatically.

---

### 2.5 IBM App Connect

App Connect provides authoring and runtime environments for creating, testing, sharing, and deploying integration flows.

**Instance types (CRDs):**

| CR | Description |
|---|---|
| `IntegrationRuntime` | Runtime environment for deployed integration flows (replaces `IntegrationServer`) |
| `IntegrationDashboard` | Monitoring dashboard for integration runtimes |
| `DesignerAuthoring` | Low-code authoring environment (App Connect Designer) |
| `SwitchServer` | Routes messages between integration servers |
| `Configuration` | Configuration objects (policies, keystores, etc.) |

**Key capabilities:**
- **Low/no-code flows** — connect applications and data using a visual flow editor without writing code
- **Smart Connectors** — hundreds of pre-built connectors to SaaS (Salesforce, ServiceNow, etc.) and enterprise systems
- **Kafka integrations** — create, view, and deploy Kafka Topics and Kafka Users directly from Platform UI (16.1.1+)
- **App Connect Private Networks (16.2+)** — configure VM-based App Connect runtimes to be managed from the Platform UI
- **Non-Kubernetes App Connect management (16.2+)** — deploy only the Platform UI on OpenShift, then view and manage App Connect VM deployments via the Platform UI
- **GitOps-native** — deploy integration flows via CI/CD pipelines using Infrastructure as Code
- **z/OS Container Extensions (zCX)** — App Connect runs on z/OS with z/OS qualities of service
- **Backup and Restore** — OADP-based support for configurations and integration runtimes

> ⚠️ **Deprecation (16.1.3+):** `IntegrationServer` CR is deprecated; migrate to `IntegrationRuntime`.

---

### 2.6 IBM MQ

IBM MQ delivers **reliable, transactional enterprise messaging** — ensuring message delivery even under network failures or system outages.

**Instance types:**
- `QueueManager` — core CR for MQ queue managers

**Key capabilities:**
- **Queue management** — queues, topics, channels, subscriptions
- **Native HA** — active/standby pair with automatic failover (LTS in MQ V10 / CP4I 16.2)
- **Cross-Region Replication** — geo-distributed HA across regions (LTS in MQ V10)
- **MQ Advanced** — adds AMS (message-level encryption/signing), MFT (Managed File Transfer), and advanced clustering
- **MQ AI Agents (MQ V10)** — AI-powered problem-solving assistance
- **MQ-Kafka connectors** — bidirectional bridge between MQ and Kafka (Event Streams)
- **MQ Explorer / IPT / MFT Agent** — non-chargeable management tooling
- **Operator-based deployment** — operators manage multiple versions; instances are NOT auto-upgraded when operator upgrades
- **Backup & Restore** — OADP support for Queue managers

**Chargeable MQ containers** (consume VPC entitlement): `Queue Manager`, `Native HA active replicas`, `Multi-instance containers`

---

### 2.7 IBM Event Streams

IBM Event Streams is an **enterprise Apache Kafka** platform for building event-driven applications.

**Instance types (CRDs):**

| CR | Description |
|---|---|
| `KafkaCluster` | Core Kafka cluster |
| `KafkaConnect` | Kafka Connect cluster |
| `KafkaTopic` | Individual Kafka topic |
| `KafkaUser` | Kafka user with ACLs |
| `KafkaBridge` | HTTP bridge to Kafka |
| `KafkaConnector` | Individual Kafka connector |
| `KafkaRebalance` | Partition rebalancing |

**Key capabilities:**
- **Apache Kafka foundation** — Kafka brokers, ZooKeeper/KRaft, fully managed by operator
- **REST producer API** — scalable REST access for producers that can't use Kafka protocol natively
- **Geo-replication** — replicate topics across deployments for DR
- **Enterprise connectors** — MQ source/sink, Debezium CDC, HTTP sink, and third-party (Confluent) connectors
- **Schema Registry** — enforce Avro/JSON schemas across producers and consumers
- **Data lake ingestion** — connect click streams, transactions, and other sources to data lakes
- **ML integration** — feed real-time structured data into machine learning pipelines
- **Event Processing Add-On** — purchasable add-on bringing IBM Event Processing to CP4I with additional OpenShift entitlement
- **Backup & Restore** — OADP support

**Chargeable containers:** Kafka brokers (`kafka`), Geo-Replicator nodes (`georep`), MirrorMaker 2.0 (`mirrormaker2`), Kafka Connect hosted by IBM Event Automation (`connect`)

---

### 2.8 IBM Event Endpoint Management

Provides **governance, discovery, and access control** for event-driven APIs (Kafka topics).

**Instance types:**
- `EventGateway` — enforces policies for event endpoint access

**Key capabilities:**
- Describe and publish Kafka topics as discoverable, governed event endpoints
- Access control — define which applications can produce to or consume from specific topics
- Self-service discovery portal for developers to find and subscribe to event streams
- Keycloak-based authentication (consistent with other CP4I components)
- Backup & Restore via OADP

---

### 2.9 IBM DataPower Gateway

IBM DataPower is a **high-performance, security-focused gateway** for API and integration traffic.

**Instance types:**
- `DataPowerService` — DataPower gateway instance
- **API Nano Gateway** (16.2+) — lightweight cloud-native componentised gateway

**Key capabilities:**
- Enforce API security policies: OAuth 2.0, TLS mutual auth, JWT validation, rate limiting, threat protection
- Message mediation and protocol transformation (REST, SOAP, MQ, etc.)
- Deploy close to cloud-native apps (in-cluster) or in the DMZ
- **DataPower Virtual Gateway** — virtualised gateway; backup and restore supported via OADP
- **API Nano Gateway (16.2+)** — small-footprint, cloud-native gateway; create and manage from Platform UI

---

### 2.10 IBM Aspera HSTS

IBM Aspera High Speed Transfer Server (HSTS) enables **fast, secure large-file transfer** using the FASP™ protocol.

**Key capabilities:**
- Transfer files at speeds approaching full network bandwidth regardless of file size or distance
- Secure delivery with encryption in transit and at rest
- Use cases: media files, genomics data, financial records, large database exports, satellite imagery

**Deployment note:** Event Streams and Event Endpoint Management are container-only; all other CP4I capabilities (including Aspera) can be deployed in VMs **or** containers.

---

### 2.11 End-to-End Monitoring

*(Introduced in CP4I 16.2.0)*

Provides **transaction-level tracing** across multiple CP4I integration components.

**Key capabilities:**
- Trace individual transactions as they flow through multiple integration instances
- Identify performance bottlenecks across the integration estate
- Pinpoint the exact failing component in a multi-hop transaction
- Deployed via CLI; managed through the Platform UI
- Tutorial available: *Tutorial: Setting up end-to-end transaction tracing across instances*

---

## 3. AI Capabilities — CP4I Agent

CP4I 16.1.3 introduced AI Agents (GA: 25 March 2026). The full **CP4I Agent** is generally available in CP4I 16.2.

### What the Agent Does

The CP4I Agent is a conversational AI interface, powered by Large Language Models (LLMs), embedded in the Platform UI. Multiple specialised AI agents work together behind the scenes to answer questions, perform tasks, and provide operational insights.

**Agent capabilities:**

| Function | Description |
|---|---|
| **Intelligent Query Handling** | Parses natural language questions, distributes subtasks to specialist agents, compiles actionable responses |
| **Documentation Expert** | Searches CP4I product documentation and returns precise answers, avoiding manual doc searches |
| **Topology Mapping** | Understands relationships between deployed resources; provides a high-level view of the integration estate |
| **Health Checking** | Returns status of deployed instances; surfaces instances in Warning or Error states |
| **Log Analysis** | Analyses instance logs to identify errors, warnings, and anomalies |
| **Anomaly Detection** | Detects unusual patterns across the hybrid deployment landscape |
| **Upgrade Awareness** | Reports available updates for installed instances and operators |

**Example prompts:**
- *"What is the status of my MQ queue managers?"*
- *"Are there any errors in this instance's logs?"*
- *"How many resources is my instance using?"*
- *"What is Cloud Pak for Integration?"*
- *"What can I do with Automation Assets?"*

**Access:** Log in to Platform UI (admin or viewer role) → click the **AI button** at the bottom-right of the screen.

**Prerequisites:**
- IBM watsonx.ai SaaS entitlement and connection required
- Deployment is optional — admins choose to enable it
- Agents are transparent and accountable: they show what data is being analysed and why
- Charged at 5 instances per cluster = 1 CP4I VPC

**Configuration:** See [Configuring the CP4I Agent](https://www.ibm.com/docs/en/cloud-paks/cp-integration/16.1.3?topic=pak-using-cloud-pak-integration-agent)

---

## 4. Planning

### 4.1 System Requirements

Before installing, review requirements across all dimensions:

**Operating environments supported:**

| Platform | Notes |
|---|---|
| Red Hat OpenShift Container Platform | Primary supported platform; all capabilities available |
| Azure Kubernetes Service (AKS) | Platform UI only (16.1.2+); integration instances on any CNCF K8s |
| z/OS Container Extensions (zCX) | MQ, App Connect, Event Streams, EEM, Aspera, API Connect Portal/Manager |
| Any CNCF Kubernetes | Integration product container images deployable under CP4I licence |

**Key planning topics from the docs (Planning > System Requirements sub-pages):**
- `Operating environment` — supported OpenShift versions per CP4I release
- `Compute resources for development environments` — minimum CPU/RAM per operator and per instance type
- `Considerations for high availability` — cluster topology requirements for HA deployments
- `Storage considerations` — persistent storage class requirements per instance
- `Deploying multiple IBM Cloud Paks on the same OpenShift cluster` — shared Foundational Services, namespace strategy

**Storage class examples:**
- **Block storage** (`managed-premium`, default Azure) — required for MQ Queue Managers, API Connect, etc.
- **File storage** (`ocs-storagecluster-cephfs`, Red Hat OCS) — required for App Connect, Automation Assets, etc.

---

### 4.2 Licensing & Entitlements

CP4I uses a **Virtual Processor Core (VPC)** licensing model.

#### How it works
1. Each deployed capability consumes CP4I VPC entitlement according to a defined product ratio.
2. Usage is aggregated **per OpenShift cluster** as a **high-water mark** (peak usage in the period).
3. Ratios are applied **separately for production and non-production** workloads.
4. When the product ratio produces a fractional VPC, all instances of that product+ratio are summed then **rounded up** to the nearest whole number.
5. CP4I entitlements are **reusable** across different product combinations without limit, as long as total entitlement is not exceeded.

#### Production License Ratios

| Product | VPC Ratio (product VPCs : CP4I VPCs) |
|---|---|
| API Connect | 1 : 1 |
| App Connect Enterprise | 1 : 3 |
| Aspera HSTS 1 Gbps | 1 : 4 |
| DataPower | 1 : 1 |
| Event Endpoint Management | 1 : 1 |
| Event Streams | 1 : 1 |
| Event Streams (DR only) | 2 : 1 |
| MQ Advanced | 2 : 1 |
| MQ Advanced HA Replica | 10 : 1 |
| MQ Advanced Multi-instance Containers | 5 : 3 |
| MQ base | 4 : 1 |
| MQ HA Replica | 20 : 1 |
| MQ Multi-instance Containers | 10 : 3 |
| RPA Platform per Install | 1 : 2 |
| RPA Environment per Virtual Server | 1 : 1 |

#### Non-Production License Ratios

| Product | VPC Ratio (product VPCs : CP4I VPCs) |
|---|---|
| API Connect | 2 : 1 |
| App Connect Enterprise | 2 : 3 |
| Aspera HSTS 1 Gbps | 1 : 2 |
| DataPower | 2 : 1 |
| Event Endpoint Management | 2 : 1 |
| Event Streams | 2 : 1 |
| MQ Advanced | 4 : 1 |
| MQ Advanced HA Replica | 20 : 1 |
| MQ base | 8 : 1 |
| MQ HA Replica | 40 : 1 |
| MQ Multi-instance Containers | 20 : 3 |

#### Non-Chargeable Components (do NOT consume CP4I VPC)
- Cloud Pak Foundational Services
- Platform UI
- Automation Assets
- Location Agent
- App Connect: Designer, Dashboard, Connectors
- MQ: MFT Agent, IPT, Explorer

#### Platform UI with AI Agents
- Charged at **5 instances per cluster = 1 CP4I VPC**
- Typically ≤ 1 CP4I VPC per cluster is sufficient

#### Reporting Tools
- **IBM License Service** (included with CP4I) — tracks containerised VPC usage per cluster; reports every 5 minutes
- **IBM License Metric Tool (ILMT)** — tracks VM-based deployments using PVU or VPC metrics
- **License Service Reporter** — aggregates usage data from multiple clusters into a single report

#### IBM Process Mining Entitlement
Each CP4I installation of IBM Process Mining Platform includes: 3 Process Mining Processes, 20 Million Events, 1 Analyst User, 3 Business Users, 2 Task Mining Agents.

---

### 4.3 Structuring Your Deployment

**Cluster strategy:**

| Strategy | When to use |
|---|---|
| **Single cluster, all-namespaces operator** | Single environment, simpler management, one Platform UI |
| **Single cluster, per-namespace operator** | Multiple teams or environments on same cluster; isolation required |
| **Multiple clusters** | Production/non-production separation; DR; geography; compliance |

**Key rules:**
- A cluster runs a single OpenShift version — all workloads must support the same OCP version simultaneously
- **All-namespaces** operator install: single operator instance, one Platform UI, manages all namespaces
- **OwnNamespace** install: scoped to a namespace; allows multiple operator instances per cluster
- Group instances into namespaces to apply resource quotas (CPU/memory), network policies, and simplify log filtering
- Create Secrets and ConfigMaps only in the namespace where they are needed — minimum necessary access principle
- Use separate clusters for environments where performance runs or tests could affect production

---

### 4.4 Workload Placement

When workloads are deployed on OpenShift, the OpenShift scheduler places pods on cluster nodes. CP4I provides guidance for influencing this placement.

**Considerations:**
- Use **node selectors** and **taints/tolerations** to pin integration workloads to specific node types
- Use **resource quotas** per namespace to prevent one team's workloads from starving another's
- Each CP4I instance type has its own scheduling behaviour — see *Reference > Workload placement for instances* for per-instance details

---

### 4.5 Single Node OpenShift (SNO)

CP4I supports installation on **Single Node OpenShift (SNO)** clusters.

**Use case:** Development, proof-of-concept, and edge deployments where only one node is available.

**Limitations:** HA capabilities requiring multiple nodes (e.g., MQ Native HA) are not applicable in SNO environments.

---

### 4.6 Logging Planning

CP4I supports both:
- **Red Hat OpenShift cluster logging** (OpenShift Logging Operator — based on Elasticsearch/Kibana or Loki/Grafana)
- **User-defined logging solutions** — send logs to external SIEM or log aggregation platforms

Log streams to consider:
- Platform UI and operator logs
- Instance logs (per capability)
- OpenShift platform logs

See *Administering > Enabling and using logging* for configuration steps.

---

### 4.7 Cluster Monitoring Planning

Monitoring in CP4I can be done with:
1. **OpenShift Monitoring Stack** (Prometheus + Alertmanager + Grafana)
2. **IBM Instana** (observability platform; limited entitlement included with new CP4I 16.1.2+ purchases for on-premises Instana)

The OpenShift Grafana instance is read-only. To create custom dashboards, deploy an additional Grafana instance via Cloud Pak Foundational Services connected to OpenShift's Prometheus.

---

### 4.8 Custom Images

CP4I allows deploying **custom container images** for CP4I components in scenarios where custom builds are required. Documentation covers support policies and constraints for custom image usage.

---

### 4.9 Disaster Recovery

**Disaster Recovery (DR)** restores service after an unrecoverable failure affecting the main environment.

**Two approaches:**

| Approach | Description |
|---|---|
| **OADP (Velero-based)** | Backup and restore Kubernetes CRs and Persistent Volumes; supported for most CP4I operators |
| **Automation/GitOps** | Use CI/CD pipelines (ArgoCD, Tekton, OpenShift Pipelines) to redeploy from version control into a new cluster |

**OADP-supported operators (backup & restore):**
- Platform UI
- IBM App Connect (Configuration, IntegrationRuntime, IntegrationServer, SwitchServer, Dashboard, DesignerAuthoring)
- IBM MQ and MQ Advanced (QueueManager)
- IBM API Connect (all subsystems)
- IBM DataPower (DataPowerService)
- IBM Event Streams (all Kafka CRs)
- IBM Event Endpoint Management
- Automation Assets

**For operators not yet covered by OADP:** use GitOps/IaC automation to rebuild the instance configuration on a new cluster.

---

### 4.10 Additional Services

CP4I can be co-deployed with other IBM Cloud Paks on the same OpenShift cluster, sharing **Cloud Pak Foundational Services** infrastructure:
- IBM Cloud Pak for Data
- IBM Cloud Pak for AIOps
- IBM Cloud Pak for Business Automation

Planning guidance for multi-Cloud Pak deployments is provided in the documentation.

---

## 5. Installing

### 5.1 Overview of Installation Steps

A CP4I installation consists of an OpenShift (or AKS) cluster with one or more operators and one or more deployed instances.

**Main steps:**

| Step | Action |
|---|---|
| 1 | **Prepare cluster** — install a supported OpenShift or AKS cluster |
| 2 | **Mirror images** *(air-gapped only)* — mirror CP4I images to a private registry |
| 3 | **Add catalog sources** — add IBM Operator Catalog to `openshift-marketplace` |
| 4 | **Install operators** — via OpenShift console (OperatorHub) or CLI (`oc apply`) |
| 5 | **Apply entitlement key** — add IBM entitlement key as an image pull secret |
| 6 | **Deploy Platform UI** — deploy `PlatformNavigator` CR |
| 7 | **Deploy instances** — deploy individual capability instances via Platform UI or CLI |

**Catalog source YAML (example):**
```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: CatalogSource
metadata:
  name: ibm-operator-catalog
  namespace: openshift-marketplace
spec:
  displayName: "IBM Operator Catalog"
  publisher: IBM
  sourceType: grpc
  image: icr.io/cpopen/ibm-operator-catalog
  updateStrategy:
    registryPoll:
      interval: 45m
```

---

### 5.2 Express Installation

A simplified installation path for getting started quickly, using opinionated defaults. Suitable for development and evaluation environments.

---

### 5.3 Adding Catalog Sources & Mirroring Images

**Online installation:** IBM Operator Catalog auto-polls for updates every 45 minutes — no manual mirroring required.

**Air-gapped/disconnected installation:**
1. Mirror the CP4I images to a private container registry within the air-gapped network
2. Configure the cluster to pull from the private registry
3. Add catalog sources pointing to the mirrored catalog

---

### 5.4 Installing Operators

**Two modes:**
- **Via OpenShift console (OperatorHub):** Search for `CP4I`, select namespace scope, install
- **Via CLI (`oc apply`):** Create `Subscription` CRs for each required operator

**Operator subscription example (Platform UI):**
```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: ibm-integration-platform-navigator
  labels:
    backup.integration.ibm.com/component: subscription
spec:
  channel: v8.0
  name: ibm-integration-platform-navigator
  source: ibm-integration-platform-navigator-catalog
  sourceNamespace: openshift-marketplace
```

**Available operators (per CP4I 16.x):**

| Operator | Manages |
|---|---|
| `ibm-integration-platform-navigator` | Platform UI, Assembly, API, API Product, Messaging server/queue/channel/user, Policy |
| `ibm-apiconnect` | API Connect cluster + all subsystems |
| `ibm-appconnect` | App Connect (all instance types) |
| `ibm-mq` | Queue managers |
| `datapower-operator` | DataPower gateways |
| `ibm-eventstreams` | Kafka cluster + all Kafka CRs |
| `ibm-integration-asset-repository` | Automation Assets |
| `ibm-aspera-hsts-operator` | Aspera HSTS |

**Operator installation modes:**
- `AllNamespaces` — single operator instance manages all namespaces; one Platform UI per cluster
- `OwnNamespace` — scoped to a namespace; allows multiple installations per cluster

---

### 5.5 Entitlement Key

Obtain the IBM entitlement key from [My IBM](https://myibm.ibm.com/products-services/containerlibrary) and apply as an image pull secret in the namespaces where CP4I operators and instances are deployed.

---

### 5.6 Deploying the Platform UI

Deploy the `PlatformNavigator` Custom Resource after operators are installed. The Platform UI becomes the single control point for deploying and managing all other instances.

---

### 5.7 Automated Installation

Options for automated deployment:

| Option | Description |
|---|---|
| **IBM Cloud Catalog** | Auto-adds catalog sources, installs operators, deploys Platform UI and Automation Assets on IBM Cloud ROKS |
| **OpenShift Pipelines + GitOps** | Define CP4I deployment as code; deploy consistently across environments |
| **Helm Charts (AKS)** | Install CP4I operators on AKS using Helm |

---

### 5.8 Deploying Instances

Instances are deployed via the Platform UI or CLI after operators are installed.

**Via Platform UI:**
1. Log in → click **Create an instance**
2. Select the instance type tile
3. Configure via the web form (UI) or YAML
4. Optionally: select **from Automation Assets template** for pre-configured deployments
5. Share the configuration as a template back to Automation Assets

**Labelling instances:**
- Apply custom labels to instances for organisational filtering
- Labels are saved and reusable across instances

**Instance types available per operator:**

| Operator | Instance Types |
|---|---|
| CP4I | Platform UI, Assembly, API, API Product, Messaging server/queue/channel/user, Policy, Policy binding |
| IBM API Connect | API Connect cluster, API Manager, API Analytics, API Gateway, API Portal, Federated API Management |
| IBM App Connect | Configuration, Integration dashboard, Integration design, Integration runtime, Integration server, Switch server |
| IBM MQ | Queue manager |
| IBM DataPower | Enterprise gateways |
| IBM Event Streams | Kafka cluster, Kafka connect, Kafka topic, Kafka user, Kafka bridge, Kafka connector, Kafka rebalance |
| IBM Event Endpoint Management | Event Gateway |
| IBM Automation Foundation Assets | Automation assets |

---

### 5.9 Installing on Azure Kubernetes Service (AKS)

The Platform UI is installed on AKS using Helm charts. Integration instances run on any CNCF Kubernetes cluster; the AKS-hosted Platform UI manages them via the Unified Management Location Agent.

---

## 6. Uninstalling

Uninstalling CP4I involves removing in the reverse order of installation:

1. **Delete deployed instances** — delete all Custom Resources (queue managers, integration runtimes, API Connect clusters, etc.)
2. **Uninstall operators** — remove operator subscriptions and CSVs from OpenShift
3. **Remove catalog sources** — clean up `CatalogSource` objects from `openshift-marketplace`
4. **Remove secrets and pull secrets** — clean up entitlement key pull secrets
5. **Remove Foundational Services** — if no other Cloud Paks remain on the cluster

**Documentation:** [Uninstalling CP4I](https://www.ibm.com/docs/en/cloud-paks/cp-integration/16.2.0?topic=uninstalling)

---

## 7. Upgrading

### Upgrade Approach

CP4I provides an **upgrade plan** tool (available in the Platform UI and CLI) that analyses the current installation and generates a step-by-step upgrade guide.

**Upgrade sequence (major version upgrade example, e.g. 16.1.0 → 16.1.3):**

1. Apply the fix pack for the current version (if required before upgrading)
2. Upgrade OpenShift to the required version (e.g. 4.14)
3. Upgrade catalog sources (or wait for IBM Operator Catalog auto-poll)
4. Upgrade operators (via `oc patch subscription` or OperatorHub)
5. Upgrade the Platform UI
6. Upgrade instances (each instance CR is edited to trigger the upgrade)
7. Optionally upgrade OpenShift further

**Important rules:**
- Upgrade path: must upgrade sequentially — cannot skip versions (e.g., must go 2022.4 → 2023.2 → 2023.4)
- Upgrade plans are **per-cluster** — generate a plan on each cluster independently
- Operators **do not** auto-upgrade instances (exception: IBM Event Streams operator auto-upgrades its instances)
- API Connect operator **can only manage the latest version** and upgrades previous versions when detected

**Fix packs:** Apply fix packs between major releases to patch the current version before upgrading. Commands use `oc patch subscription` to change the operator channel.

**Integration Server → Integration Runtime (16.2):** The upgrade plan detects deprecated `IntegrationServer` instances and provides commands to convert them to `IntegrationRuntime`.

---

## 8. Using the Cloud Pak

### 8.1 Using the Platform UI

The Platform UI is the primary interface for day-to-day CP4I operations.

**Navigation:**
- **Instances table** — lists all deployed instances; filter by type, namespace, status; exportable as CSV
- **Overview pane** (16.1.3+) — home-page status summary; click status badges to filter instances
- **Create an instance** button — opens the instance creation wizard or YAML editor
- **Canvas view** — graphical drag-and-drop interface for Assembly authoring

**Managing instances across multiple locations (16.1.3+):**
- **Instance Locations** — define remote OpenShift clusters as managed locations
- **Location Agent** — deployed in each remote cluster; relays instance data to hub Platform UI
- Create, edit, and delete instances in any registered location from the single hub UI window
- URL reflects current filter state (e.g., `/instances?filters=type%3AQueue%2520manager`)

**Deploying from a template:**
1. Log in → Create an instance → select instance type
2. Click **Select a template from Automation Assets**
3. Browse and select a template; preview the CR YAML
4. Deploy

**Sharing a configuration as a template:**
1. Configure an instance (via form or YAML)
2. Click the overflow menu (⋮) → **Share as template**
3. Add Name, Tags (optional), and Description → click Share
4. Template is saved to Automation Assets for team reuse

---

### 8.2 Using the CP4I Agent

See [Section 3 — AI Capabilities](#3-ai-capabilities--cp4i-agent) for full details.

**Quick access:** Click the **AI button** (bottom-right of Platform UI) after configuration is complete.

---

## 9. Tutorials

CP4I documentation includes step-by-step tutorials accessible from the *Tutorials* section:

| Tutorial | Description |
|---|---|
| **End-to-end transaction tracing** | Set up End-to-End Monitoring across multiple integration instances (16.2+) |
| **API Connect basics** | Create, publish, and test a REST API |
| **App Connect integration** | Build an integration flow connecting two applications |
| **IBM MQ setup** | Deploy a queue manager and send/receive messages |
| **Event Streams with Kafka Connect** | Connect MQ source/sink, HTTP sink, Debezium CDC connectors to Event Streams |
| **Enterprise-grade integration** | Connect application components and data within and between clouds |
| **Observe and manage environments** | Use Instana and Turbonomic to monitor App Connect and MQ resources |

**External tutorials (IBM Developer):**
- [Integrate and connect application components and data](https://developer.ibm.com/tutorials/enterprise-grade-integration)
- [Observe and manage CP4I environments](https://developer.ibm.com/tutorials/observe-and-manage-ibm-cloud-pak-for-integration-environments)

---

## 10. Migrating to CP4I

The *Migrating to the Cloud Pak* section provides **transformation guides** for moving traditional VM-based integration deployments to containerised CP4I on OpenShift:

| Migration Guide | From | To |
|---|---|---|
| **Aspera HSTS transformation guide** | On-premises Aspera HSTS VM deployment | Containerised Aspera on CP4I / OpenShift |
| **API Connect transformation guide** | Traditional API Connect (appliance/VM) | API Connect on CP4I |
| **App Connect transformation guide** | App Connect Enterprise on VM | App Connect on CP4I |
| **IBM MQ transformation guide** | IBM MQ on VM | MQ Queue Manager on CP4I |
| **DataPower transformation guide** | DataPower physical appliance / virtual appliance | DataPower Virtual Gateway on CP4I |

**Key benefit of migration:** After migrating, VPC entitlements can be reallocated across any CP4I capability instance.

**Integration Server → Integration Runtime** migration (required from CP4I 16.2):
- `IntegrationServer` CR is deprecated; all instances must be converted to `IntegrationRuntime`
- The Platform UI upgrade plan provides automated detection and conversion instructions/commands

---

## 11. Troubleshooting

### 11.1 Gathering Diagnostics (must-gather)

Before opening an IBM Support case, gather diagnostic information using the **must-gather** tool.

**Prerequisites:**
- Admin permissions on the OpenShift cluster
- OpenShift CLI (`oc`) installed

**Gather CP4I-specific logs:**
```bash
oc adm must-gather --image=icr.io/cpopen/cpfs/must-gather:latest -- gather -m cp4i --params "'-h'"
```

**Gather other logs:**
- **Cloud Pak Foundational Services logs:** use the same must-gather image with foundation services params
- **OpenShift platform logs:** `oc adm must-gather` (standard OpenShift must-gather)
- **App Connect-specific logs:** see *Gathering diagnostic information* in App Connect documentation

**AI-assisted diagnostics:**
- Ask the CP4I Agent: *"Are there any errors in this instance's logs?"*
- The agent queries instance logs and surfaces issues with plain-language explanations

---

### 11.2 Common Issues & Solutions

| Issue | Cause | Solution |
|---|---|---|
| **Platform UI operator pod OOMKilled** | `ibm-integration-platform-navigator-operator` container exceeds memory limit | Increase `limits.memory` in `subscription.spec.config.resources` (e.g., to `1Gi`); do not change `requests.memory` |
| **CP4IServiceBindings blocked / wrong Foundational Services version** | Version mismatch between CP4I and Foundational Services | Upgrade Foundational Services to the required version per CP4I release notes |
| **Operators in unknown state; OLM catalog-operator restarts** | OLM processes only one operator request at a time; OLM pod crash | Delete all pods in `openshift-operator-lifecycle-manager` namespace to trigger recreation and unblock OLM |
| **OADP restore: `Cp4iServicesBinding` goes to error state** | Resource dependency ordering during restore | Follow the documented restore order; restore Foundational Services before CP4I CRs |
| **Instance PVC not bound** | Storage class not configured or unavailable | Verify storage class exists and is available; check PVC events with `oc describe pvc` |
| **Operator stuck in CrashLoopBackOff** | Dependency not satisfied; resource limits exceeded | Check operator pod logs; verify catalog sources; check resource quotas |
| **Installation failure — images not pulling** | Entitlement key pull secret missing or incorrectly applied | Re-apply the IBM entitlement key as a pull secret in the correct namespaces |
| **Upgrade fails — fix pack not applied** | Current version is not at the required fix pack level | Apply the required fix pack before running the upgrade plan |

---

## 12. Administering

### 12.1 Developer Reference

Reference documentation for developers building integrations on CP4I, including API references for Platform UI instance types and Custom Resource examples.

---

### 12.2 OpenShift Roles & Permissions

CP4I uses OpenShift RBAC. Cluster-scoped permissions are required by operators to manage Custom Resource Definitions (CRDs) across all namespaces.

**CP4I Platform UI roles:**

| Role | Capabilities |
|---|---|
| **Admin** | Full control: create, edit, delete instances; configure locations; access CP4I Agent |
| **Viewer** | Read-only access: view instances and their status; access CP4I Agent |

Fine-grained permissions per instance type are documented in the *Cloud Pak roles and permissions* topic.

---

### 12.3 Identity & Access Management (IAM)

CP4I uses **Keycloak** (managed by Cloud Pak Foundational Services) for identity and access management.

**Features:**
- Single Sign-On (SSO) across all CP4I UI components
- LDAP integration (IBM Security Directory Server, Microsoft Active Directory, PingDirectory, custom LDAP)
- Identity provider (IdP) federation for external SSO
- Two-factor authentication (2FA) support
- **Keycloak 26** supported in CP4I 16.1.2+

**Assigning roles to users:**
1. Log in to Platform UI → navigate to user management
2. Search for the user → open User Details
3. Click **Role Mapping** → **Assign role** → filter by clients → select role → Assign

**Getting initial admin password:** See *Getting the initial administrator password* in the Administering section.

---

### 12.4 Hostnames & Certificates

CP4I instances automatically generate hostnames and TLS certificates during installation. These can be replaced with custom values.

**Managed by:**
- `cert-manager` operator (installed in `cert-manager-operator` namespace)
- Keycloak operator (in `ibm-common-services` namespace)

**Custom certificate workflow:**
1. Create a Certificate or Secret resource with the custom certificate
2. Reference the secret in the instance Custom Resource
3. The operator reconciles and applies the custom certificate

---

### 12.5 Backup & Restore (OADP)

CP4I backup and restore is implemented using **Red Hat OpenShift API for Data Protection (OADP)** — a Velero-based tool for backing up and restoring Kubernetes CRs and Persistent Volumes.

**Supported components (labelled with `backup.<component>.ibm.com/component`):**

| Component | Label prefix |
|---|---|
| Platform UI | `backup.integration.ibm.com` |
| App Connect | `backup.appconnect.ibm.com` |
| IBM MQ | `backup.mq.ibm.com` |
| IBM API Connect | `backup.apiconnect.ibm.com` |
| IBM DataPower | `backup.datapower.ibm.com` |
| IBM Event Streams | `backup.eventstreams.ibm.com` |

**Label subscriptions before backup (example):**
```bash
oc label subscription ibm-integration-platform-navigator backup.integration.ibm.com/component=subscription
oc label subscription ibm-appconnect backup.appconnect.ibm.com/component=subscription
oc label subscription ibm-mq backup.mq.ibm.com/component=subscription
oc label subscription ibm-apiconnect backup.apiconnect.ibm.com/component=subscription
oc label subscription datapower-operator backup.datapower.ibm.com/component=subscription
oc label subscription ibm-eventstreams backup.eventstreams.ibm.com/component=subscription
```

---

### 12.6 Enabling & Using Logging

CP4I supports:
- **OpenShift cluster logging** — structured log collection via OpenShift Logging Operator (Elasticsearch/Kibana or Loki/Grafana)
- **User-defined logging** — forward logs to external Splunk, Elastic, or other SIEM systems via log forwarder

**Log sources to capture:**
- Platform UI and operator pod logs
- Instance logs (per capability)
- OpenShift API server and platform logs

---

### 12.7 Enabling OpenShift Container Platform Monitoring

1. Enable **user workload monitoring** in OpenShift:
   - Create `cluster-monitoring-config` ConfigMap in `openshift-monitoring` namespace
   - Set `enableUserWorkload: true`
2. Create `user-workload-monitoring-config` ConfigMap in `openshift-user-workload-monitoring` namespace to configure retention and resource limits
3. Deploy additional **Grafana** instance via Cloud Pak Foundational Services for writable dashboards
   - Connect Grafana to the OpenShift Thanos Querier endpoint using a service account token
   - Configure a Grafana datasource pointing at the Thanos Querier hostname

**Note:** The default OpenShift Grafana instance is **read-only** and does not support custom dashboard creation.

---

### 12.8 Enabling IBM Instana Monitoring

IBM Instana provides proactive, AI-powered APM monitoring for CP4I components.

**Instances supported by Instana:**
- Integration Runtime (App Connect)
- Kafka Cluster (Event Streams)
- Queue Manager (IBM MQ)
- Enterprise Gateway (DataPower)

**Deployment options:**
- **SaaS** — install only the Instana Agent Operator
- **On-premises** — install both the Instana Backend and the Instana Agent Operator

**Steps:**
1. Install Instana Backend (on-premises only)
2. Install Instana Agent Operator
3. Create an `InstanaAgent` Kubernetes resource
4. Configure the agent per capability using sensor guides in `agent.configuration_yaml`

**Entitlement:** A limited Instana monitoring entitlement is included with new purchases of CP4I 16.1.2+ for on-premises deployments.

---

### 12.9 Configuring Cloud Pak Foundational Services

Cloud Pak Foundational Services are shared services used by CP4I and other Cloud Paks on the same cluster:
- **Keycloak / Identity Manager** — SSO and IAM
- **cert-manager** — certificate lifecycle management
- **License Service** — VPC usage tracking and reporting
- **Operand Deployment Lifecycle Manager (ODLM)** — manages dependencies between operators

Configuration includes: LDAP integration, console hostname customisation, resource scaling, and multi-Cloud Pak co-deployment.

---

### 12.10 Deploying License Service

The IBM License Service is required for VPC compliance reporting in containerised environments.

- Automatically deployed with Cloud Pak Foundational Services
- Collects VPC usage data from each cluster every 5 minutes
- Generates compliance reports for IBM audits
- Use **License Service Reporter** to aggregate across multiple clusters

**Viewing reports:** Access the License Service UI via the OpenShift console or use the REST API for programmatic access.

---

### 12.11 Applying Fix Packs Between Major Releases

Fix packs deliver security patches and bug fixes without a full version upgrade.

**Applying via CLI:**
```bash
oc patch subscription <operator-name> -n openshift-operators \
  --patch '{"spec":{"channel":"v<new-channel>"}}' --type=merge
```

**Apply fix packs in this order:**
1. IBM Common Service Operator
2. IBM Cloud Databases Redis Operator (if used)
3. CP4I operator subscriptions (Platform UI, API Connect, App Connect, etc.)
4. Verify all operator pods are running before proceeding to instance upgrades

---

### 12.12 Usage Metrics

CP4I automatically reports usage metrics back to IBM for telemetry and compliance. This includes:
- Deployment metrics: number of VPCs, resources, users
- Usage metrics: number of API calls, events, interactions processed
- **No personally identifiable information (PII)** is shared
- **No actual integration content** is shared

To **disable** telemetry instrumentation, follow the instructions in the *Usage metrics* documentation topic.

---

## 13. Reference

### 13.1 Operator Reference

Comprehensive documentation on each CP4I operator:
- Guidelines for operator installation modes (AllNamespaces vs OwnNamespace)
- CRD definitions managed by each operator
- Controller reconciliation behaviour
- Compatibility with OpenShift versions

**Key operator behaviours:**
- Operators manage multiple CR versions and are backwards-compatible with previous instance versions
- When an operator is upgraded, it can manage **all existing CRs** on the cluster without auto-upgrading instances
- **Exception — IBM Event Streams**: operator auto-upgrades its instances
- **Exception — IBM API Connect**: operator manages only the latest version and auto-upgrades older CRs

---

### 13.2 Container Images

CP4I container images are hosted in the **IBM Entitled Registry** (`icr.io/cpopen/`).

- Online clusters pull directly from the registry
- Air-gapped clusters require mirroring to a private registry
- Each release ships a set of `CatalogSource` images that list available operator versions

---

### 13.3 Operator & Instance Versions

A compatibility matrix per release lists:
- The operator channel version for each CP4I capability
- The instance (CR) versions that each operator version manages
- Support status (Continuous Delivery `●` vs Support Cycle-2 `◼` vs Deprecated `⚠️`)

Available CRs per operator (example for CP4I 16.x):

| Operator | Custom Resources |
|---|---|
| `ibm-integration-platform-navigator` | PlatformNavigator, IntegrationAssembly, MessagingServer, MessagingQueue, MessagingChannel, MessagingUser |
| `ibm-apiconnect` | APIConnectCluster, ManagementCluster, PortalCluster, AnalyticsCluster, GatewayCluster |
| `ibm-appconnect` | IntegrationRuntime, IntegrationDashboard, DesignerAuthoring, SwitchServer, Configuration |
| `ibm-mq` | QueueManager |
| `datapower-operator` | DataPowerService |
| `ibm-eventstreams` | KafkaCluster, KafkaConnect, KafkaTopic, KafkaUser, KafkaBridge, KafkaConnector, KafkaRebalance |
| `ibm-integration-asset-repository` | AutomationAssets |

---

### 13.4 Cluster-Scoped Permissions for Operators

Operators require cluster-scoped permissions to manage CRDs (which are cluster-level Kubernetes objects). Documentation lists the exact `ClusterRole` and `ClusterRoleBinding` objects created by each operator.

**Principle of least privilege**: CP4I operators are designed to require only the minimum permissions necessary for their operation.

---

### 13.5 Workload Placement for Instances

Each CP4I instance type has its own pod scheduling behaviour. The reference documents per-instance:
- Default node affinity rules
- Toleration requirements
- Resources (CPU/memory) requests and limits per pod

---

### 13.6 Security Context Constraints (SCC)

**All CP4I instances run in the default `restricted` SCC** that ships with OpenShift, **except:**
- **IBM Aspera HSTS** — requires an additional privilege SCC

SCCs control what a pod can do and what resources it can access on the OpenShift node. The `restricted` SCC prevents privilege escalation and limits host-level access.

---

### 13.7 Community Resources

Links to IBM Community forums, blogs, and user groups for CP4I:
- [IBM Community — Cloud Pak for Integration](https://community.ibm.com/community/user/integration)
- Community blog for CP4I tips and best practices
- My Notifications — subscribe to important CP4I announcements and fix pack releases

---

### 13.8 Glossary

Key terms used in CP4I documentation:

| Term | Definition |
|---|---|
| **VPC** | Virtual Processor Core — the unit of measure for CP4I licensing |
| **Operator** | Kubernetes controller that manages the lifecycle of a Custom Resource |
| **Custom Resource (CR)** | A Kubernetes object defined by a CRD; represents an instance of a CP4I capability |
| **CRD** | Custom Resource Definition — extends the Kubernetes API with new object types |
| **OLM** | Operator Lifecycle Manager — manages operator installation and upgrades in OpenShift |
| **OADP** | OpenShift API for Data Protection — Velero-based backup/restore framework |
| **Foundational Services** | Shared IBM Cloud Pak infrastructure services (Keycloak, cert-manager, License Service) |
| **Platform UI** | CP4I's unified management control plane (also called Platform Navigator) |
| **Assembly** | An `IntegrationAssembly` CR grouping multiple integration instances for joint management |
| **SNO** | Single Node OpenShift — a single-node cluster for development/edge scenarios |
| **FIPS** | Federal Information Processing Standards — US government cryptography compliance standards |
| **SCC** | Security Context Constraint — OpenShift policy controlling pod privileges |
| **AKS** | Azure Kubernetes Service — Microsoft's managed Kubernetes service |
| **CNCF** | Cloud Native Computing Foundation — open source governance body; defines Kubernetes standard |
| **zCX** | z/OS Container Extensions — allows running container workloads on z/OS |
| **GitOps** | Operations managed via Git — use ArgoCD/Tekton to deploy from version control |

---

## 14. Regulatory Compliance

### FIPS 140-2
Certain components comply with Federal Information Processing Standards (FIPS) for cryptographic modules. Applicable to U.S. government and regulated deployments. Documentation covers which components are FIPS-compliant and how to enable FIPS mode.

### Two-Factor Authentication (2FA) & RBAC
Enable 2FA via Keycloak for all Platform UI users. Role-Based Access Control (RBAC) enforced via OpenShift RBAC and Platform UI roles (Admin/Viewer).

### Audit Logging
CP4I supports audit event logging for compliance and forensic review. Audit logs capture user actions, authentication events, and API calls.

### Accessibility
- IBM is committed to WCAG compliance
- Accessibility Compliance Reports (ACR/VPAT) covering WCAG, European Standard EN 301 549, and US Section 508 are available at [IBM Product Accessibility Reports](https://www.ibm.com/able/product_accessibility/)
- Accessibility features (keyboard shortcuts, screen reader support) are documented for the Platform UI and Automation Assets

### IPv6 Support
- Platform UI supports dual-stack (IPv4 + IPv6) network configurations on OpenShift
- Single-stack IPv6-only deployments are **not supported** for Platform UI

**Documentation:** [Regulatory compliance](https://www.ibm.com/docs/en/cloud-paks/cp-integration/16.2.0?topic=regulatory-compliance)

---

## 15. Version History & What's New

### CP4I 16.2.0 — Long-Term Support (GA: 30 June 2026)
**PID:** 5737-I89 | **Support Cycle:** SC-O (2.5+1+2.5) — up to 6 years

| Feature | Description |
|---|---|
| **End-to-End Monitoring** | Trace transactions across multiple integration runtimes; identify bottlenecks and failures |
| **CP4I Agent (GA)** | LLM-powered conversational AI — health checks, log analysis, documentation queries, topology mapping |
| **Unified Management for VMs** | View and manage App Connect VM deployments from the Platform UI alongside containers |
| **API Developer Portal** | Create and manage API Developer Portals from Platform UI |
| **Federated API Management** | Manage multiple distributed API runtimes and data planes from a single hub |
| **API Nano Gateway** | Cloud-native small-footprint gateway; manageable from Platform UI |
| **IBM MQ V10 LTS** | Native HA + Cross-Region Replication as LTS options; MQ AI Agents; updated MQ-Kafka connectors; enhanced cryptography |
| **App Connect Private Networks** | Configure non-Kubernetes (VM) App Connect runtimes via Platform UI |
| **API Connect v12** | Supports API Developer Portal, Federated API Management, API Nano Gateway subsystems |
| **Full-page layout** | Expanded create/edit UI across the full screen width |
| **Integration Server deprecation** | Upgrade plan detects `IntegrationServer` instances and provides conversion commands to `IntegrationRuntime` |
| **CSV export** | Download instances table as CSV |

---

### CP4I 16.1.3 (Support Cycle-2)

| Feature | Description |
|---|---|
| **AI Agents GA** (25 March 2026) | AI Agents became generally available; replaces Agent Preview |
| **Unified Management enhanced** | Full CRUD for instances on remote clusters from hub Platform UI |
| **Overview pane** | Home-page summary of instance statuses per location |
| **Assembly managed instances deprecated** | Convert to independent instances + labels |
| **Expanded Platform UI layout** | Full-page create/edit experience |
| **Upgrade plan enhancement** | Detects deprecated `IntegrationServer` instances; provides conversion guidance |

---

### CP4I 16.1.2

| Feature | Description |
|---|---|
| **Unified Management introduced** | Single Platform UI view and management across multiple OpenShift clusters |
| **AKS support** | Platform UI deployable on Azure Kubernetes Service |
| **Location Agent** | Deployed per remote cluster to relay instance data to hub Platform UI |
| **Backup & Restore extended** | OADP support added for MQ, MQ Advanced, API Connect, DataPower |
| **Confluent connectors** | Third-party Kafka Connect connectors visible in Platform UI |
| **Keycloak 26** | Updated IAM platform for CP4I |
| **Node licensing topic** | Documentation for maximising CPU usage via node licensing model |
| **IBM Instana entitlement** | Limited on-premises Instana entitlement included with new purchases |

---

### CP4I 16.1.1

| Feature | Description |
|---|---|
| **Enhanced Integration Assistant** | AI-powered integration creation assistant (later replaced by CP4I Agent) |
| **Event Processing Add-On** | IBM Event Processing available as standalone CP4I add-on with additional OCP entitlement |
| **Keycloak for EEM** | Event Endpoint Management UI uses Keycloak for consistent auth |
| **Kafka Topics/Users in Platform UI** | Create, view, and deploy Kafka Topics and Users from Platform UI |
| **Automation Assets enhancements** | Draft saving; auto-open correct editor per asset type |

---

### CP4I 16.1.0 — Long-Term Support Release

| Feature | Description |
|---|---|
| **New version naming** | Introduced 16.x.y naming convention (previously year-based, e.g. 2022.4.1) |
| **All core capabilities** | MQ, App Connect, API Connect, DataPower, Event Streams, EEM, Aspera HSTS |
| **zCX support** | Deploy on z/OS Container Extensions |
| **OADP Backup & Restore** | Initial support for App Connect, Event Streams, EEM, Automation Assets |
| **Integration Assemblies** | Assembly canvas for graphical multi-integration deployment |

---

## 16. Support & Resources

### Official Documentation

| Resource | URL |
|---|---|
| CP4I Docs (all versions) | https://www.ibm.com/docs/en/cloud-paks/cp-integration |
| CP4I 16.2.0 Docs | https://www.ibm.com/docs/en/cloud-paks/cp-integration/16.2.0 |
| CP4I 16.1.3 Docs | https://www.ibm.com/docs/en/cloud-paks/cp-integration/16.1.3 |
| CP4I Product Page | https://www.ibm.com/products/cloud-pak-for-integration |
| IBM API Connect Docs | https://www.ibm.com/docs/en/api-connect |
| IBM App Connect Docs | https://www.ibm.com/docs/en/app-connect |
| IBM MQ Docs | https://www.ibm.com/docs/en/ibm-mq |
| IBM DataPower Gateway Docs | https://www.ibm.com/docs/en/datapower-gateway |
| IBM Event Streams Docs | https://ibm.github.io/event-streams/ |
| IBM Aspera Docs | https://www.ibm.com/docs/en/aspera-on-cloud |

### Support

| Resource | URL |
|---|---|
| IBM Support Portal | https://www.ibm.com/products/cloud-pak-for-integration/support |
| Open a Support Case | https://www.ibm.com/mysupport |
| Known Issues (APARs) | https://www.ibm.com/support/pages/apar |
| IBM Entitlement Key | https://myibm.ibm.com/products-services/containerlibrary |
| CP4I Software Support Lifecycle | https://www.ibm.com/support/pages/ibm-cloud-pak-integration1620 |
| CP4I Support Lifecycle Addendum | https://www.ibm.com/support/pages/node/6955879 |

### Community & Learning

| Resource | URL |
|---|---|
| IBM Community — CP4I | https://community.ibm.com/community/user/integration |
| IBM TechXchange Community | https://community.ibm.com |
| IBM Developer — CP4I Tutorials | https://developer.ibm.com |
| IBM Training | https://www.ibm.com/training |
| My Notifications (subscribe to updates) | https://www.ibm.com/support/mynotifications |

### SaaS Complement — IBM webMethods Hybrid Integration

For organisations already using CP4I who want a managed SaaS option alongside their self-managed deployment, **IBM webMethods Hybrid Integration** extends integration capabilities to an iPaaS (Integration Platform as a Service):

- Connects apps, APIs, and B2B with centralized governance
- Reduces integration sprawl
- Usage-based licensing for cloud integrations
- Complements existing CP4I deployments rather than replacing them

---

## 17. Storage Planning

### 17.1 Persistent Volume Access Modes

CP4I components use three storage patterns:

| Mode | Description | When Used |
|---|---|---|
| **RWO (ReadWriteOnce)** | Block storage accessed by a single pod | Components with built-in replication (MQ NativeHA, API Connect, Event Streams) |
| **RWX (ReadWriteMany)** | Shared file storage accessed by multiple pods | Automation Assets, App Connect Designer |
| **S3 (Object Storage)** | Object storage via API (not mounted volumes) | App Connect Dashboard, MQ multi-instance (optional) |

> **Note:** CP4I components **do not** require raw block device storage — RWO volumes are always mounted as a filesystem directory inside the container (`volumeMode: Filesystem`).

### 17.2 Per-Component Storage Requirements

| Component | RWO (Block) | S3 (Object Storage) | RWX (File) |
|---|---|---|---|
| Platform UI | N/A (2023.4+) | N/A | N/A |
| IBM Cloud Pak Foundational Services | Required | — | — |
| IBM API Connect | Required | — | — |
| IBM MQ (Native HA) | Recommended | Optional (multi-instance only) | — |
| IBM Event Streams | Required | — | — |
| App Connect Dashboard | Recommended | Optional alternative to S3 | — |
| App Connect Designer | Required | Recommended (AI feature) | Optional alternative |
| IBM Aspera HSTS | Required | — | — |
| Automation Assets | Required | Required | — |
| Integration Server | N/A | N/A | N/A |
| DataPower | N/A | N/A | N/A |

### 17.3 Named Supported Storage Providers

**Fully supported across all capabilities:**
- OpenShift Data Foundation (ODF)
- IBM Spectrum Fusion / IBM Storage Fusion
- IBM Spectrum Scale
- IBM Storage Suite for Cloud Paks
- IBM Cloud File and Block storage
- Portworx
- IBM Spectrum Virtualize, FlashSystem, or DS8K (Block only)

**Component-specific rules:**
- **API Connect:** Any block storage except explicitly excluded; **no NFS for RWO**
- **Event Streams:** Block storage formatted as XFS or ext4; **no NFS**
- **IBM MQ:** 18 named tested file systems, 6 prohibited; provides a utility for validating file locking for multi-instance

> **New from CP4I 2023.4:** All components support any RWO storage that meets the "Required RWO characteristics" (block provider, formatted as ext4/XFS, dynamic provisioning, WaitForFirstConsumer binding mode).

### 17.4 Public Cloud Storage Options

#### AWS
| Component | AWS EBS (RWO) | AWS S3 | AWS EFS (RWX) | ODF | Portworx |
|---|---|---|---|---|---|
| Foundational Services | ✓ | — | ✓ | ✓ | ✓ |
| API Connect | ✓ | — | ✓ | ✓ | ✓ |
| MQ (Native HA) | ✓ | Optional | — | ✓ | ✓ |
| Event Streams | ✓ | — | ✓ | ✓ | ✓ |
| App Connect Dashboard | ✓ | Optional | ✓ | ✓ | ✓ |
| Aspera HSTS | ✓ | — | ✓ | ✓ | ✓ |
| Automation Assets | ✓ | ✓ | ✓ | ✓ | ✓ |

**AWS EBS volume limits per worker node:** ~11–39 volumes depending on EC2 instance type; plan accordingly for API Connect HA (requires ~40 volumes).

#### Azure
| Component | Azure Disk (RWO) | Azure Files (RWX) | ODF | Portworx |
|---|---|---|---|---|
| Foundational Services | ✓ | ✓ | ✓ | ✓ |
| API Connect | ✓ | — | ✓ | ✓ |
| MQ (Native HA) | ✓ | — | ✓ | ✓ |
| Event Streams | ✓ | — | ✓ | ✓ |
| App Connect Dashboard | ✓ (no native S3) | ✓ | ✓ | ✓ |
| Automation Assets | ✓ | ✓ | ✓ | ✓ |

### 17.5 Cross-AZ Storage Behaviour

**Key principle:** CP4I components that use RWO block storage provide **their own built-in replication** — they do NOT require cross-AZ replicated storage. You can safely use AZ-scoped block storage (e.g., AWS EBS) for components like MQ Native HA, API Connect, and Event Streams.

| Storage Provider | Block (RWO) | File (RWX) |
|---|---|---|
| OpenShift Data Foundation | Replicated across AZs | Replicated across AZs |
| AWS EBS | Scoped to single AZ | N/A |
| AWS EFS | N/A | Replicated across AZs |
| IBM Cloud Block | Scoped to single AZ | Scoped to single AZ |
| Portworx | Replicated across AZs | Replicated across AZs |

**Caution with SDS providers (ODF, Portworx) for components with built-in replication:**
- Can cause **8× data replication** (component copies × storage copies), reducing performance
- Results in **increased cross-AZ data transfer charges** (e.g., $0.01/GB on AWS)
- Requires **additional worker nodes** and ongoing SRE overhead

---

## 18. High Availability

### 18.1 HA vs. Disaster Recovery

| Concept | Purpose | Characteristics |
|---|---|---|
| **High Availability (HA)** | Maintains service during a running failure | Instantaneous failover; autonomous; cannot protect against data corruption |
| **Disaster Recovery (DR)** | Recovers after catastrophic failure | Requires human decision; RPO/RTO targets; handles full cluster loss |

**Key metrics for DR:**
- **Recovery Time Objective (RTO):** Maximum acceptable downtime
- **Recovery Point Objective (RPO):** Maximum acceptable data loss (how far back recovery goes). RPO=0 means no data loss but typically requires trade-offs in cost/performance.

### 18.2 Failure Domains

| Failure Domain | On-Premises | Public Cloud |
|---|---|---|
| Single VM | Multiple-node clusters | N/A |
| Physical host | Spread nodes across hosts/racks (DRS in VMware) | Cloud spreads by default; use Placement Groups (AWS) / Availability Sets (Azure) |
| Rack | N/A | N/A |
| Zone (Metro) | Stretch cluster (<2ms between DCs) | OCP standard install provides stretch clusters where region supports it |
| Region | Application-level HA across multiple clusters | Application-level HA across multiple clusters |

### 18.3 Implementing HA in CP4I

**Four-step approach:**
1. Deploy an HA OpenShift cluster across 3 failure domains. Label nodes using `topology.kubernetes.io/zone`.
2. Deploy CP4I components in HA configurations.
3. Develop a capacity plan accounting for degraded-infrastructure scenarios.
4. Create a Disaster Recovery (DR) plan.

**OpenShift control plane requires:** Minimum **3 control plane nodes** distributed across failure domains (quorum-based).

### 18.4 Per-Component HA Approaches

| Component | HA Approach | Min. Shared Worker Nodes |
|---|---|---|
| Platform UI | Active/active | 2 |
| Asset Repository (Automation Assets) | Service availability – Failover | 3 |
| Operations Dashboard | Store: Quorum; Config DB: Failover; Front-end: Active/Active | 3 |
| API Connect | Quorum | 3 |
| IBM MQ Native HA | Message availability – Active/standby | 3 |
| IBM MQ multi-instance | Message availability – Active/standby | 2 |
| IBM MQ cluster | Service availability – Active/active | 2 |
| Event Streams | Quorum | 3 |
| App Connect (stateful) | Failover | 2 |
| App Connect (stateless) | Active/Active | 2 |
| Aspera HSTS | Quorum | 3 |
| DataPower Gateway | Quorum | 3 |
| Keycloak (IAM) | Store: Failover; Session storage: Active/Active | 2 |

---

## 19. Security and Access Control

### 19.1 Authentication vs. Authorization

**Authentication** (Identity verification) in CP4I is handled by the **Red Hat Build of Keycloak (RHBK)**, deployed by IBM Cloud Pak Foundational Services.

**Authorization** (Permission granting) is based on **Keycloak client roles** assigned to users/groups.

### 19.2 Authentication Options

| Method | Description |
|---|---|
| **IBM-provided credentials** | Initial `integration-admin` user password auto-generated at install; accessible from OCP console or CLI |
| **Keycloak local users** | Built-in user registry for creating CP4I users without an external IdP |
| **LDAP / Active Directory** | Integrates enterprise directory via Keycloak admin console |
| **OIDC** | Connects external OpenID Connect providers via Keycloak |
| **SAML** | Connects enterprise SAML identity management via Keycloak |
| **OpenShift authentication** | Use OCP users to log into CP4I; useful if enterprise directory is already integrated with OCP |

### 19.3 Keycloak Authorization Model

**Key Concepts:**

| Term | Definition |
|---|---|
| **Realm** | Entire IAM system with its own users, groups, IdPs, roles, and clients. CP4I uses `master` and `cloudpak` realms. Make changes only in the `cloudpak` realm. |
| **Client** | Consumer of IAM services. Each CP4I instance is a Keycloak client. |
| **Roles** | Defined at client level. Assigning a role from the CP4I-wide client grants access to ALL instances; assigning from an instance-specific client grants access to that one instance only. |

**Role Assignment:** Use the RHBK user management interface to assign roles to individual users and groups.

> Before CP4I 2023.4, authorization was based purely on OpenShift RBAC namespace permissions. CP4I 2023.4 introduced Keycloak-based fine-grained authorization.

### 19.4 Validating Admission Policies (VAP)

CP4I supports Kubernetes **Validating Admission Policies** (OCP 4.17+) — a declarative alternative to validating admission webhooks.

**Use cases:**
- Enforce label requirements on resources (e.g., "resources in namespace `prod` must have an owner label")
- Limit deployment replica counts

**Resources involved:**
1. `ValidatingAdmissionPolicy` — describes the logic
2. Parameter resource — defines the detailed configuration
3. `ValidatingAdmissionPolicyBinding` — links the policy to the parameter and defines scope

**Security note:** Policy creation is **disabled by default** in CP4I because policies are cluster-scoped and can be used to block creation of any Kubernetes resource — potential for privilege escalation.

**To enable VAP in CP4I:**
1. Ensure OpenShift 4.17+
2. Ensure Platform UI 16.1.0.8+
3. Create `ClusterRole` and `ClusterRoleBinding` enabling:
   - `apiGroups: admissionregistration.k8s.io`
   - `resources: validatingadmissionpolicies` and `validatingadmissionpolicybindings`

The Platform UI supports creating/editing VAP resources, template examples, storing policies in Automation Assets, and viewing policy bindings as child objects of policies.

---

## 20. IBM Kubernetes Certification

All CP4I components undergo IBM's proprietary **IBM Kubernetes Certification** program — an annual top-to-bottom review with quarterly delta analysis.

### Certification Dimensions

| Dimension | What It Covers |
|---|---|
| **Production Grade** | Multi-cloud, storage, networking, resiliency, scalability, self-healing, recoverability |
| **Security** | Vulnerability management, limited privilege, secure access/keys/certs, network & data protection, secrets, Security & Privacy by Design |
| **Quality Assurance** | Unit/integration/system tests, availability, performance, upgrade/rollback, chaos/disruption testing, OCP version compatibility, airgap validation |
| **Lifecycle Management** | Upgrade/patch process, rollback, backup/recovery, supported Kubernetes/OCP APIs, semantic versioning, must-gather |

### Certification Stack

1. **Red Hat Image Certification** — UBI images, compatible across OCP platforms
2. **Red Hat Operator Certification** — well-formed operator structure, works in OLM catalog
3. **IBM Kubernetes Certification** — deployed topology, use of Kubernetes in OCP, ~300 criteria

### What IBM Certification is NOT
- Not a guarantee of security, availability, or performance in all environments
- Does not replace the PSIRT security process for CVEs
- Not an application function certification (remains with the product team)

---

## 21. Resource Allocation

### 21.1 Requests and Limits

Every CP4I pod has defined **resource requests** (guaranteed minimum) and **resource limits** (maximum allowed):

| Concept | Description |
|---|---|
| **CPU Request** | Minimum CPU guaranteed to the pod; used by scheduler to select a node |
| **CPU Limit** | Maximum CPU the pod can use; used for **VPC license counting** |
| **Memory Request** | Minimum memory guaranteed; pod is not evicted unless it exceeds this and there is node pressure |
| **Memory Limit** | Maximum memory; exceeding triggers pod eviction |

**All CP4I pods:** Have both CPU and Memory requests set
**CP4I pods that consume VPCs:** Have CPU limits set (required for capacity-based licensing)

### 21.2 License Counting Algorithm

1. The **vCPU capacity** of a pod = sum of CPU limits for all chargeable containers in the pod
2. If total vCPU capacity for an IBM Program on a **worker node exceeds that node's capacity**, it is capped at node capacity
3. vCPU capacity is **aggregated at cluster level** then rounded up to the nearest whole integer
4. **License ratios** are applied to convert vCPU capacity to required VPC entitlement

**Example:** An ACE production container with `resources.limits.cpu=1` consumes **3 VPCs** (ratio 1:3).
**Example:** An MQ Base production container with `resources.limits.cpu=1` consumes **0.25 VPCs** (ratio 4:1).

### 21.3 Production License Ratios

| Capability | Product VPC to CP4I License Ratio |
|---|---|
| App Connect Enterprise | 1 : 3 |
| API Connect | 1 : 1 |
| DataPower | 1 : 1 |
| MQ base | 4 : 1 |
| MQ Advanced | 2 : 1 |
| Event Streams | 1 : 1 |
| Event Endpoint Management | 1 : 1 |
| Aspera HSTS 1Gbps | 1 : 4 |

Non-production ratios are **half** of production ratios.

### 21.4 Node Placement for License Optimisation

Placing CP4I workloads on dedicated nodes enables **node-level VPC capping** — if pods' aggregate CPU limits exceed the node's total CPUs, the license requirement is capped at the node capacity.

**Example:** 6 pods with `limit.cpu=3` spread across 6 nodes of 5 CPUs each = **18 VPCs** without placement. Constrained to 3 dedicated nodes (one per AZ) = **15 VPCs** (capped at 5 per node).

**How to implement node placement:**
```bash
# 1. Label nodes
oc label node <node-name> nodeuse=cp4i

# 2. Set namespace node selector
oc annotate namespace cp4ins openshift.io/node-selector='nodeuse=cp4i'

# 3. Set cluster-wide node selector for other workloads
defaultNodeSelector: nodeuse=general
```

> **Note:** Cluster-wide node selectors are **not supported** on Red Hat OpenShift on IBM Cloud. Use taints/tolerations as an alternative.

**Other reasons for node placement:**
- Prevent "noisy neighbour" resource contention between workloads (e.g., CP4I and CP4Data)
- Separate workloads that use large amounts of ephemeral storage

---

## 22. Unified Management

### 22.1 Overview

**Unified Management** (introduced in CP4I 16.1.1) extends the CP4I Platform UI to provide a **single pane of glass** view across multiple OpenShift clusters and deployment environments.

**Key capabilities:**
- One UI window to view integration instances deployed across multiple clusters
- "New Locations" column in Platform UI shows remote clusters
- Click-through hyperlinks to drill down into the integration on the remote cluster
- Compatible with air-gapped and internal-only network environments
- Plug-and-play — connect existing clusters instantly with no reconfiguration

### 22.2 How It Works

1. Create a **Location** in the Platform UI (provide a name)
2. Apply the **Location Agent Configuration** to the remote cluster
3. The CP4I Operator handles the rest automatically

The Unified Management hub cluster and remote clusters can each be on any cloud or on-premises environment — "anywhere OpenShift runs."

### 22.3 Unified Management Roadmap

| Release | Feature |
|---|---|
| CP4I 16.1.0 | Foundation |
| CP4I 16.1.1 CD | View and Drill-Down on multiple OpenShift clusters |
| CP4I 16.1.2 CD | First Platform UI capabilities on Azure AKS; enhanced IAM/RBAC |
| CP4I 16.1.3 CD | Create, Update & Delete directly from Hub UI |
| CP4I 16.2.0 SC-2 / CD | Manage VM instances as well as Kubernetes |

> *All roadmap futures are not confirmed and subject to change.*

### 22.4 Business Impact

| Benefit | Description |
|---|---|
| Single Pane of Glass | Manage all integrations from one central UI regardless of deployment environment |
| Enhanced Visibility | Comprehensive view of all integration instances and statuses without switching systems |
| Simplified Management | Reduced complexity and operational overhead across environments |
| Integration Made Easy | Compatible with air-gapped installs and internal-only networks |

---

## 23. Deployment Layout Guidance

### 23.1 Optimal Deployment Approach

IBM recommends the following structure for CP4I deployments (guidelines, not mandatory):

| Reference | Recommendation |
|---|---|
| **R1** | Deploy a **separate cluster per environment** (development, test, production). Use OpenShift Hosted Control Plane to consolidate control planes. |
| **R2** | When using separate clusters, deploy CP4I in **all namespaces** for simplicity. Only one Platform UI per cluster when installed at cluster scope. |
| **R3** | Use a separate **OpenShift project (namespace) per logical user group** or team. Apply RBAC, resource quotas, and network policies at namespace level. |
| **R4** | Subdivide into multiple namespaces even for the same team if: (a) grouping by application/business domain, or (b) managing hundreds of instances. |
| **R5** | If installing other software alongside CP4I, consider dependency constraints (see OLM rules). |

### 23.2 Common Alternative: Shared Non-Production Cluster

When separate clusters are too resource-intensive, a shared cluster approach is viable:

| Reference | Description |
|---|---|
| **A1** | Share a cluster between non-production environments (dev + test). Understand the risks: OCP upgrades affect all namespaces simultaneously; performance testing in one namespace can affect others. |
| **A2** | In shared clusters, install CP4I operators at **namespace (project) scope** to allow independent operator versions per project. Do not install an older operator version than what already exists on the cluster. |
| **A3** | Namespace-scoped operators require a **separate Platform UI instance per project**. Each Platform UI shows only instances in its own project. |
| **A4** | Resource-intensive components (API Connect, Event Streams) may be **shared across projects** using multi-tenancy features (Provider Organizations in APIC, Topics in Event Streams) — but understand isolation limits. |

### 23.3 Operator Scope Constraints (OLM Rules)

| Rule | Description |
|---|---|
| **O1** | CRDs are cluster-scoped. Two controllers managing the same CRD type in different namespaces creates complexity and can cause unexpected errors. |
| **O2** | OLM enforces a single controller per CR type. An operator at namespace scope cannot also be at cluster scope. |
| **O3** | OLM manages dependencies with the same rules. If any dependency is at namespace scope, CP4I cannot be at cluster scope. |
| **O4** | A cluster-scoped operator has one instance managing all CRs cluster-wide. |
| **O5** | A namespace-scoped operator manages CRs only within its selected project; multiple namespace-scoped copies can coexist. |
| **O6** | CP4I operators are backwards-compatible with previous CR versions — safe to use cluster-scoped operators across different project CRs. |

---

## 24. CP4I Packaging and Licensing Deep Dive

### 24.1 What's Included in a CP4I License

**Non-Chargeable (no CP4I VPCs consumed):**
- Red Hat OpenShift (3 cores per CP4I VPC purchased — use only for CP4I components)
- IBM Cloud Pak Foundational Services
- Access Control, Metering and Licensing
- IBM Storage Fusion Essentials (12 TB of storage per cluster)
- IBM Instana self-managed — 6 months entitlement with new purchases
- Integration Assistant (watsonx Integration Assistant)
- Platform UI including Unified Management
- Integration Assemblies/Canvas
- Upgrade Readiness Checklist
- Declarative Deployment for APIs and Queues

**Chargeable (consume CP4I VPCs at defined ratios):**
- API Connect
- App Connect
- IBM MQ / MQ Advanced
- DataPower Gateway
- Event Streams
- Event Endpoint Management
- IBM Aspera HSTS

**Add-ons (entitled through CP4I VPCs separately):**
- API Calls (Aspera)
- Aspera Enterprise
- Event Processing
- webMethods (B2B/MFT use cases)
- RPA / Process Mining

### 24.2 CP4I Unique Cloud Pak Capabilities vs. Standalone

| Capability | Available Standalone | Included in CP4I Only |
|---|---|---|
| App Connect | ✓ | — |
| API Connect | ✓ | — |
| MQ, MQ Advanced | ✓ | — |
| DataPower | ✓ | — |
| Aspera | ✓ | — |
| Event Streams | — | ✓ |
| Event Endpoint Management | — | ✓ |
| Platform UI + Unified Management | — | ✓ |
| Asset Repository | — | ✓ |
| Upgrade Readiness Planner | — | ✓ |
| Integration Assemblies + Canvas | — | ✓ |
| Declarative Deployments | — | ✓ |
| Embedded OpenShift entitlement | — | ✓ |
| License flexibility (pool of VPCs) | — | ✓ |

### 24.3 License Flexibility — "Pool of Tokens"

CP4I VPCs work as a pool of integration entitlement tokens:
- **No pre-commitment required** — deploy any mix of capabilities up to total VPC pool
- **Swap freely** — move entitlement between components without IBM approval
- **Same entitlement** covers containerized (CP4I) and standalone (VM) deployments
- **Moving PVU → VPC** typically yields 40–70% additional entitlement
- **Non-production entitlement** is included (at half the production ratio)

### 24.4 Subscription vs. Perpetual Licensing

| License Type | Recommended When |
|---|---|
| **Cloud Pak Subscription** | New customer; modernizing existing footprint; growing existing footprint |
| **Incremental Cloud Pak Subscription** | Existing IBM software client with existing perpetual license |
| **S&S Upgrade to Subscription** | Existing client on Software & Subscription wanting to migrate |
| **Cloud Pak Perpetual** | ELA clients with specific perpetual requirements |

Available for purchase and deployment on **AWS Marketplace** and **Azure Marketplace** in addition to established IBM sales channels.

---

## 25. Business Value, ROI, and Customer Case Studies

### 25.1 Forrester Total Economic Impact (TEI)

| Metric | Result |
|---|---|
| Reduction in integration time | **35–55%** |
| Reduction in unplanned outages | **40–60%** |
| Time savings managing and monitoring integrations | **40–60%** |
| Reduction in labor requirements for application security engineers | **10%** |

*Source: Forrester Total Economic Impact of IBM Cloud Pak for Integration*

### 25.2 Market Context

| Statistic | Source |
|---|---|
| 75% of organizations running containerized workloads across hybrid environments | CNCF |
| API traffic growing over 30% annually | Postman State of the API Report |
| 67% of organizations delayed deployments due to Kubernetes skill challenges | Red Hat |
| High-impact outages cost a median of $2M per hour | New Relic |
| Organizations use 1,000+ applications on average, each with hundreds of dependencies | Customer Data Platform Institute |
| 75% of technology decision-makers expect technical debt to be severe by 2026; consumes ~30% of IT budgets | Forrester |
| 56% of decision-makers experience technology downtime with devastating financial/compliance impacts | Forrester |
| 95%+ of global organizations will run containerized applications in production by 2029 | Gartner |
| $30B global application container market projected by 2030 (24% CAGR) | Mordor Intelligence |

### 25.3 Customer Case Studies

#### Al Rajhi Capital (Saudi Arabia — Financial Services)
**Challenge:** Fragmented technology landscape accumulated over two decades; monolithic architecture preventing agility and scale ambitions.
**Solution:** IBM Cloud Pak for Integration with MQ, App Connect, API Connect, DataPower, and Red Hat OpenShift.
**Outcomes:**
- 40% increase in brokerage business volume
- 1,000% rise in onboarding for mutual funds
- Rose from #2 to #1 brokerage firm in Saudi Arabia

> *"IBM's technology allowed us to innovate at an unprecedented pace. International customer growth also saw a dramatic rise, with onboarding increasing 10,000%."*
> — Ghassan Lama, VP & Head of IT DevOps, Al Rajhi Capital

#### NHC — National Housing Company (Saudi Arabia — Real Estate)
**Challenge:** Sought a robust, scalable architecture to expose and consume APIs while automating workflows at scale. Trailblazers in migrating entirely to container-based applications.
**Solution:** CP4I on Red Hat OpenShift with API Connect, App Connect, MQ, and DataPower.
**Outcomes:**
- 40% decrease in time required to develop and launch new services
- 23% average reduced response time for API calls

#### Qatar Development Bank (Qatar — Banking)
**Challenge:** Modernise IT infrastructure to support containerized applications, enhance operational efficiency, and ensure security and compliance.
**Solution:** CP4I with IBM Instana and IBM Turbonomic. Migrated 164 APIs (API Connect) and 65 ACE applications, supporting 22 business-critical applications.
**Outcomes:**
- 1,773 ms average API response time
- Continuous system improvements bi-weekly with zero downtime via DevSecOps automation

#### neoleap (Saudi Arabia — Digital Payments)
**Challenge:** Increased demand for integrated and secure digital products for digital wallets, open banking, and fintech solutions.
**Solution:** CP4I with IBM API Connect, App Connect, IBM Instana, and Red Hat OpenShift.
**Outcomes:**
- 300% faster client onboarding (1 minute vs. 3 minutes by closest competitor)

> *"Because our agile integration platform is built on IBM Cloud Pak for Integration and Red Hat OpenShift, we can make continuous system improvements bi-weekly with zero downtime."*
> — neoleap spokesperson

#### Société Générale Maroc (Morocco — Banking)
**Challenge:** Reduce technical debt, resolve performance issues, ensure reliable digital services while shifting to microservices architecture.
**Solution:** CP4I with IBM MQ, IBM Instana, and IBM Guardium.
**Outcomes:** Reduced technical debt; improved performance; modern dynamic development of new digital services.

> *"IBM Cloud Pak, with its resilience and modularity, serves as a cornerstone of this transformation, providing enhanced security, optimized performance and opportunities for innovation."*
> — Adil El Kourri, CIO/COO Tech, Société Générale Maroc

#### Digital Ajman (UAE — Government)
**Challenge:** Deliver innovative digital government services through APIs and a user-friendly marketplace, navigating a vast integration architecture.
**Solution:** CP4I with API Connect and App Connect Enterprise (built with IBM Garage Services).
**Outcomes:**
- Approaching 100% digital services
- 60,000+ API calls per month and growing

### 25.4 Competitive Differentiators

| Dimension | IBM CP4I | Competitors |
|---|---|---|
| **Cloud-native architecture** | Fully container-native on OpenShift; automated pipeline deployment ready; runs on any cloud | Competitors re-engineering products to be cloud-native — "playing catch up" |
| **Breadth of capabilities** | Complete integration platform: API, event, messaging, file transfer, security | No competitor matches CP4I's capability breadth |
| **Ease of use** | No-code/low-code tooling; 1-click deployment possible; IBM Design-built UX with usability awards | Competitors (e.g., MuleSoft) positioned as more difficult to use |
| **Security** | Fully cloud-native with secure DMZ gateway; consistent policies across all integration styles | MuleSoft lacks a robust secure gateway for DMZ deployments |
| **Asset reuse** | Asset repository + Integration Assemblies for end-to-end single deployment | Competitors promote quantity of connectors, not all maintained by the vendor |
| **License flexibility** | VPC pool — move entitlements freely between capabilities | Point product licensing requires separate purchases per capability |

**Key competitors:**
- **MuleSoft (Salesforce):** Broad platform but less rich tooling; not strong on containers; much more difficult to use
- **Apigee (Google):** Focused on API Management only; limited backend connectivity; poor on building integrations
- **Kong:** Developer-focused; more suited to smaller projects
- **Hyperscaler Kafka:** Managed Kafka tied to a specific cloud; less suitable for hybrid deployments
- **Tibco:** Prior position in messaging/connectivity space eroding

---

## 26. IBM CP4I Agent — Extended Details

### 26.1 Problem Statement

| Problem | Scale |
|---|---|
| Complex integration environments across cloud and on-premises | 75% of organizations running containerized workloads across hybrid environments |
| Growing volume of APIs and runtimes | API traffic growing 30%+ annually; hundreds to thousands of APIs |
| Reactive troubleshooting and skill shortages | 67% of organizations delayed deployments due to Kubernetes skill challenges |
| High-impact outages | Median cost $2M per hour; delayed detection is a primary cause |

### 26.2 Agent Differentiators

| Differentiator | Description |
|---|---|
| **Ready-to-Go IBM-Trained AI** | Pre-trained with IBM's deep CP4I and OpenShift expertise; no setup, customization, or costly retraining required |
| **Transparent & Accountable AI** | Shows exactly what is being analyzed and why; builds trust; full auditability |
| **Flexible & Enterprise-Secure Deployment** | Runs within CP4I with full RBAC; data remains private; available on cloud or on-premises |

### 26.3 Agent Capability Details

| Agent Capability | Before | After |
|---|---|---|
| **Supervisor Agent** | Integration knowledge without container skills blocks even simple support issues | Delivers instant, version-aware insights through a unified chat interface |
| **Instance/Topology** | Users and AI agents lack visibility into what was provisioned and where | Maps integrations to Kubernetes components; full transparency on where everything runs |
| **Logs** | Kubernetes logging fragmented and volatile; difficult to detect issues across replicas | Instantly scans across replicas; surfaces errors and guides to relevant log entries |
| **Versions & Updates** | Frequent updates + inconsistent support timelines = risk and inefficiency | Delivers status reports and summaries; keeps environments compliant and current |

### 26.4 Key Benefits

| Benefit | Detail |
|---|---|
| Avoid costly downtime | Catch risks early before they escalate through intelligent monitoring |
| Continuously optimize performance | Tailored recommendations enhancing resilience and resource utilisation |
| Accelerate innovation cycles | Keep clusters current; adopt new CP4I capabilities faster |
| Resolve issues faster | AI-powered explanations and recommended actions for faster diagnosis |
| Improve governance and visibility | Surface runtime behaviour, dependencies, deprecated components |
| Scale operational excellence | Consistency across cloud and on-premises environments |
| Boost administrator productivity | AI-driven insights highlight potential issues and next steps |

### 26.5 GA Details

- **Tech Preview:** September 2025
- **GA:** March 2026
- **Access Model:** Part of CP4I platform; RBAC-controlled via OpenShift permissions
- **Deployment:** Available for both cloud-hosted and on-premises runtimes

---

## 27. Integration Patterns and Use Cases

### 27.1 Three Core Integration Patterns

#### Pattern 1: API-led Integration
*"I need to access and share information quickly and simply."*

**Use cases:**
- Enable consistent experience across digital channels
- Support data movement for cloud-native applications across multiple clouds
- Liberate data locked in mainframe and legacy systems
- 360° customer views
- Real-time experiences driven by up-to-date data

**Primary capabilities:** IBM API Connect, IBM App Connect, IBM DataPower Gateway
**Target audience:** CTO, Chief Architect (Decision Makers); IT/Enterprise Architects (Influencers)

#### Pattern 2: Event-led Integration
*"I need to discover what is happening in my business and respond quickly."*

**Use cases:**
- Detect and share business events as they happen
- Take real-time action by subscribing to events
- Access event data through APIs alongside application data
- Respond to events like fraud detection, inventory changes, customer interactions

**Primary capabilities:** IBM Event Streams, Event Endpoint Management, Event Processing
**Target audience:** Business teams accelerating customer engagements or real-time business response

#### Pattern 3: Messaging & Connectivity
*"I need to securely and reliably access and update systems of record at scale."*

**Use cases:**
- Protect transaction integrity across networks and data sources
- Ensure once-and-only-once message delivery
- Buffer demands on backend systems to smooth workload peaks
- Enable applications to scale without scaling backend systems

**Primary capabilities:** IBM MQ, IBM App Connect, IBM Aspera, IBM DataPower
**Target audience:** Businesses needing reliable, secure, at-scale data updates

### 27.2 Integration Lifecycle

CP4I supports the complete integration lifecycle:

| Phase | Actions |
|---|---|
| **Create** | Approved Assets, pattern-based deployment, opinionated defaults, template-based creation, watsonx Integration Assistant |
| **Deploy** | Graphical Canvas, Integration Assemblies, declarative deployment for APIs/Queues, approved assets enforced at deployment, Kafka components integrated into UI |
| **Operate** | Single Node OpenShift support, small platform footprint, FIPS support, IBM Storage Fusion included, Platform UI on AKS |
| **Observe** | OpenTelemetry, OpenShift Observability Operator, Instana integration, Turbonomic resource optimization |
| **Update** | OADP backup/restore, Upgrade Readiness Checklist, automated fix packs, sequential upgrade paths |

### 27.3 AI-Powered Developer Features

**Mapping Assist (App Connect Designer):**
- Pre-trained AI algorithm using semantic analysis and history of prior mappings
- Provides intelligent, customized data map suggestions at point of integration building
- Works on flat structures and complex nested mapping fields
- Company's mapping model data is private — IBM does not view or use it

**API Test Generator:**
- Generates test suites based on comparison of production workload patterns with test environments
- AI detects patterns from operational data to inspire new tests
- Ensures sufficient test coverage for complex integration solutions

**watsonx Integration Assistant:**
- Accelerates API implementation through AI-assisted creation
- Supports low-code/no-code integration flows
- Pre-built smart connectors for 100+ SaaS and on-premises systems

---

*This knowledge base was compiled from the IBM Cloud Pak for Integration official documentation at https://www.ibm.com/docs/en/cloud-paks/cp-integration (versions 16.1.0–16.2.0), IBM product pages, IBM Community blogs, IBM product announcements, and internal IBM technical presentations (CP4I Architecture and Deployment 16.1.x, CP4I Agent client presentation, CP4I Unified Management Overview, and associated sales materials). All section numbers mirror the CP4I documentation table of contents. Last updated: July 2026 (CP4I v16.2.0).*

---

<!-- KB:AUTO-INDEX:START -->

## Documents in this Folder

> **11 files** &nbsp;|&nbsp; _Auto-indexed: 16 Jul 2026 14:57_

- `CP4I Agent client presentation.PDF` &nbsp; _PDF_ &nbsp; 744.9 KB
- `CP4I Architecture and Deployment 16.1.x.PDF` &nbsp; _PDF_ &nbsp; 3.3 MB
- `CP4I Unified Management Overview.PDF` &nbsp; _PDF_ &nbsp; 1.2 MB
- `Client leave behind - CP4I Agent.PDF` &nbsp; _PDF_ &nbsp; 101.8 KB
- `Client leave behind - CP4I Unified Management.PDF` &nbsp; _PDF_ &nbsp; 81.7 KB
- `Cloud Pak for Integration  - Targeted Prospecting Sales Guide.PDF` &nbsp; _PDF_ &nbsp; 162.6 KB
- `Cloud Pak for Integration - Grab and Go Sales Prospecting Kit.PDF` &nbsp; _PDF_ &nbsp; 135.5 KB
- `IBM Cloud Pak for Integration - CP4I 101 Client Presentation Mar 2026.PDF` &nbsp; _PDF_ &nbsp; 3.1 MB
- `IBM Cloud Pak for Integration - CP4I 301 Client Presentation.PDF` &nbsp; _PDF_ &nbsp; 5.0 MB
- `IBM Cloud Pak for Integration - Seller Presentation Level 1.PDF` &nbsp; _PDF_ &nbsp; 2.0 MB
- `IBM Cloud Pak for Integration CP4I - 201 Client Presentation.PDF` &nbsp; _PDF_ &nbsp; 1.4 MB

<!-- KB:AUTO-INDEX:END -->
