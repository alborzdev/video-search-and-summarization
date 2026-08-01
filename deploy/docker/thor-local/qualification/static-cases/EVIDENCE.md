# Static-case package construction record

Date: 2026-07-31

This record covers package construction and tests only. It is not current
capability evidence.

The inventory contains exactly 24 unique capability IDs: 13
Calibration/Warehouse cases and 11 pre-existing live static/configuration cases.
All are held in candidate-only state and all capability-advancement fields are
false. The optional Warehouse sample is absent from the inventory and fixture
files.

The calibration fixture set contains one operator-named valid document and two
adjacent invalid documents: one omits a required sensor field and one violates
the intrinsic-matrix shape. Files are copied into the inspection-owned private
temporary directory before validation and that directory is removed on exit.

The package binds, but does not emit, the shared runtime-evidence shape. Static
observations include source digests before and after inspection, byte/file/time
bounds, ownership, and cleanup postconditions. External development lanes and
reference-only performance numbers resolve only to `not_applicable`; missing
file-only host collectors resolve to `blocked`.

The isolated inventory file SHA-256 at construction is
`e1dca1d240408ce04d418567143c108d44d419c4c88520184a42e058608b7004`.
Package validation, Ruff, and 16 isolated unit tests returned zero failures.
Those checks establish package consistency only; they do not establish VSS
runtime behavior or current capability status.
