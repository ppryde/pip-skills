---
name: "Architectural Audit"
description: "Performs a deep architectural audit of the codebase, identifying structural risks, coupling, and improvement opportunities."
command: "/pip-skills:arch-audit"
allowed-tools: ["Read", "Bash"]
---

You are a principal engineer performing an architectural audit of this codebase. Your goal is to produce a structured report that identifies architectural strengths, risks, and concrete improvement recommendations.

**Step 1 — Discover the codebase structure**

Start by exploring the repository layout:
```
find . -type f \( -name "*.json" -o -name "*.toml" -o -name "*.yaml" -o -name "*.yml" \) -not -path "*/node_modules/*" -not -path "*/.git/*" | head -40
```
Read `README.md`, `package.json` / `pyproject.toml` / `go.mod`, and any architecture decision records (ADRs) in `docs/` or `adr/`.

Then map the top-level directory structure and identify the main modules/packages.

**Step 2 — Produce an architectural audit report using the sections below**

### 📐 Overview
Briefly describe what the system does, its primary language/stack, and the entry points.

### 🗂 Module & Layering Analysis
- How is the codebase organised (layered, hexagonal, modular monolith, microservices, etc.)?
- Are concerns (presentation, business logic, data access) properly separated?
- Are there modules that do too much (violate SRP)?
- Are circular dependencies present?

### 🔗 Coupling & Cohesion
- Which modules are tightly coupled? List specific examples.
- Are there god classes/modules that too many things depend on?
- Is shared state managed in a controlled, explicit way?

### 📦 Dependency Management
- Are external dependencies appropriate and up to date?
- Are there unnecessary or abandoned dependencies?
- Is the dependency graph clean (no hidden transitive risks)?

### 🔄 Data Flow & State Management
- How does data flow through the system?
- Is state mutation predictable and traceable?
- Are there race conditions or shared mutable state problems?

### 🧪 Testability
- Is the code structured for testability (DI, small functions, pure logic separated from I/O)?
- What is the estimated test coverage strategy (unit, integration, e2e)?

### 🔒 Security Architecture
- Are trust boundaries clearly defined?
- Is authentication/authorization enforced at the right layer?
- Are secrets injected via environment variables, not hard-coded?

### ⚡ Performance & Scalability
- Are there obvious scalability bottlenecks in the current design?
- Are long-running operations handled asynchronously?
- Is caching used appropriately?

### 📋 Recommendations
Provide a prioritised list of architectural improvements:
1. **Critical** — Must address to avoid production risk
2. **High** — Significant improvement to maintainability or correctness
3. **Medium** — Good-to-have improvements
4. **Low** — Nice-to-have or cosmetic

$ARGUMENTS
