# Evidence

The retained Thor run passed in 1.858648 seconds against the healthy official
VSS 3.2.1 RT-VLM image with the read-only Thor `AssetManager` overlay active.
The run used zero model requests and left the main RT-VLM catalog pristine.

At a one-MiB isolated cap, storage pressure evicted exactly the oldest idle
asset and invoked the removal callback once. With the remaining asset locked,
an overflowing upload was removed and returned production `ServerBusy` status
503 while preserving the locked asset. A separate `ASSET_MAX_AGE_HOURS=0.001`
process expired exactly the old idle asset while preserving both an old locked
asset and a fresh asset. Both isolated catalogs and temporary roots were empty
afterward; the main asset statistics, model inventory, runtime health, image,
restart count, and OOM state were unchanged.

No resource identifiers, credentials, prompts, semantic output, Warehouse
sample data, VSS Agent calls, stream mutations, or core lifecycle action are
retained in this evidence.
