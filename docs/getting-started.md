# Getting Started

## Installation

Install labpubs with [uv](https://docs.astral.sh/uv/):

```bash
uv pip install labpubs
```

For Slack notification support:

```bash
uv pip install "labpubs[slack]"
```

## Quick Start

### 1. Create a configuration file

Create `labpubs.yaml` in your project directory:

```yaml
lab:
  name: My Research Lab
  url: https://example.edu/mylab

openalex_email: you@example.edu

database_path: ~/.labpubs/labpubs.db

researchers:
  - name: Jane Doe
    openalex_id: "A5012345678"
    orcid: "0000-0001-2345-6789"
```

### 2. Sync publications

```bash
labpubs --config labpubs.yaml sync
```

This fetches publications from all configured sources, deduplicates them, and stores the results in the local SQLite database.

### 3. List publications

```bash
labpubs --config labpubs.yaml list
labpubs --config labpubs.yaml list --researcher "Jane Doe" --year 2025
```

### 4. Export

```bash
labpubs --config labpubs.yaml export bibtex -o publications.bib
labpubs --config labpubs.yaml export json -o publications.json
```

## Python API

```python
from labpubs import LabPubs
from labpubs.config import load_config

config = load_config("labpubs.yaml")
engine = LabPubs(config)

# Get all works
works = engine.get_works()
for work in works:
    print(f"{work.title} ({work.year})")
```
