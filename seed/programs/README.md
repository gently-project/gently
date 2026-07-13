# Seed research programs

Real, version-controlled research programs (not stubs) that instantiate the ELN
scientific spine (Campaign → Strain → Experiment → Hypothesis). They (a) shape a
reusable gently by building against actual cases, (b) give real notebook data to work
with, (c) anchor development to the agentic-microscopy paper. From Hari Shroff's paper
plan + collaborator notes (Richard Ikegami, danienella).

- **`stage-classification.yaml`** — Embryo developmental-stage classification — nuclear + bright-field fusion, with hatching detection
- **`temperature-hatching.yaml`** — Temperature → hatching-time distributions (K-pump thermo strain)
- **`mutant-screen.yaml`** — Mutant screen — blind genotype calling from live embryo imaging
- **`dopaminergic-outgrowth.yaml`** — Catching Outgrowth — Dopaminergic Neuronal Outgrowth in C. elegans

A loader that imports these into a fresh gently instance is part of the ELN build (FileContextStore.create_strain/experiment/hypothesis).
