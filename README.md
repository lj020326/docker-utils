# Docker Utility Images

This repository contains multi-architecture Docker image definitions tailored for specific automation workflows, background workers, and network routing utilities within the cluster infrastructure.

---

## 📦 Image Matrix & Manifest

### 1. `nord-key-extractor`
* **Source Context:** `image/nord-key-extractor/`
* **Dockerfile:** `image/nord-key-extractor/Dockerfile`
* **Base Image:** `ubuntu:24.04`
* **Documentation:** [image/nord-key-extractor/README.md](image/nord-key-extractor/README.md)
* **Role:** A lightweight runtime workspace wrapped around the official NordVPN Linux client daemon to cleanly negotiate a WireGuard (`NordLynx`) handshake, extract configuration cryptographic keys, print parameters to stdout, and immediately exit.

### 2. `langgraph-router`
* **Source Context:** `image/langgraph-router/`
* **Dockerfile:** `image/langgraph-router/Dockerfile`
* **Base Image:** `python:3.13-slim-bookworm`
* **Role:** Production-ready container runtime environment tailored for long-running stateful multi-agent systems via LangGraph. It comes preconfigured with necessary core system utility networking tools (`dnsutils`, `iproute2`, `sshpass`) and Python execution optimizations.

### 3. `crewai-workers`
* **Source Context:** `image/crewai-workers/`
* **Dockerfile:** `image/crewai-workers/Dockerfile`
* **Base Image:** `python:3.13-slim-bookworm`
* **Role:** Autonomous background worker cluster daemon optimized to continuously execute agent logic by pulling work items directly from collaborative tracking platforms. It natively hosts the `worker_daemon.py` pipeline orchestration framework.

---

## 🚀 Build and Deployment Pipelines

Images in this repository are compiled as multi-platform structures (`linux/amd64` and `linux/arm64`) to seamlessly bridge infrastructure differences.

### GitHub Actions Automation
The repository uses a automated matrix pipeline logic (`.github/workflows/build-images.yml`) that splits compilation cycles structurally:
1. **Base Images Phase:** Resolves and builds standalone images like `nord-key-extractor` first.
2. **Dependent Images Phase:** Once base environments clear successfully, dependent downstream images such as `langgraph-router` and `crewai-workers` compile systematically.

### Local or Internal Jenkins Testing
A declarative build manifest configuration is located inside `.jenkins/docker-build-config.yml` to support automated dynamic delivery runs across internal localized workspace registries.

---

## 🛡️ Identity & Maintainer
* **Maintainer:** Lee Johnson
* **Contact:** <ljohnson@dettonville.org>
* **System Framework:** [Dettonville Cloud Infrastructure Services](https://dettonville.org)
