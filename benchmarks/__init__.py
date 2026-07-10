"""Public-dataset benchmark harness for detectkit's detectors.

Dev tooling, not part of the shipped library — this directory is a top-level
sibling of ``detectkit/`` and is excluded from the built wheel by
``[tool.setuptools.packages.find]`` (which only includes ``detectkit*``).

Quantifies detection quality (F1-best, AUC-PR, point-adjusted/event F1) on
labeled public benchmarks (NAB, Yahoo S5) and an offline synthetic set, for
detectkit's statistical detectors and a benchmark-local Spectral Residual
implementation evaluated here as a measure-first gate before any decision to
ship it in the library. See ``benchmarks/README.md`` for usage.
"""
