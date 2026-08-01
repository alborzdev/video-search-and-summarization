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

The official schema code block canonicalizes to `0ad42822136283bb458b51f5d7f1b44d0332193df509b5319d42f82d1b8da5dd`;
the checked-in SpatialAI schema canonicalizes to
`96db66f32f714ddc84ffa55c4283d71d85f2cb2d4e356c04af98afd371970a97`.
The mismatch is structural rather than serialization-only: the local document
has 75 additional `errorMessage` members. Removing only members with that exact
key yields `a00f2230fde4639ace8efe4754be176c67c8beca0d13d6b146d88b23b6e88229`
for both documents. This establishes matching validation-rule projections for
the executor's Draft 7 validation lane, while preserving the exact-document
identity mismatch.

The package binds, but does not emit, the shared runtime-evidence shape. Static
observations include source digests before and after inspection, byte/file/time
bounds, ownership, and cleanup postconditions. External development lanes and
reference-only performance numbers resolve only to `not_applicable`; missing
file-only host collectors resolve to `blocked`.

The isolated inventory file SHA-256 after the schema-identity classification is
`91e3d97b2cce9c08e1e42e9ee9df793c6fd8b265a68f9eb3c64e35604ad300d3`.
Package validation, Ruff, and 20 isolated unit tests returned zero failures.
Those checks establish package consistency only; they do not establish VSS
runtime behavior or current capability status.
