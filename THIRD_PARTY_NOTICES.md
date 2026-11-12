# Third-party notices

Original source is Apache-2.0. No upstream source, model weights, benchmark assets,
recorded media or executables are vendored.

| Distribution | Use | License |
|---|---|---|
| HTTPX | Generic VLM service client | BSD-3-Clause |
| NumPy | Action and pose mathematics | BSD-3-Clause |
| Pydantic | Configuration/contracts | MIT |
| PyYAML | Configuration | MIT |
| Pillow | PNG encoding | MIT-CMU |
| dora-rs | Optional runtime transport | MIT |
| PyArrow | Optional Arrow carriers | Apache-2.0 |
| Hatchling / Build | Packaging | MIT |
| pytest / Ruff | Development checks | MIT |

The narrow Arrow field codecs are original implementations of public Forge
message contracts. They do not copy or vendor Forge SDK modules. Contract sources:
https://github.com/PhyAgentOS/forge/tree/master/packages/msgs

LIBERO, robosuite, MuJoCo, Gateway and the generic VLM service are separately
installed components; their own licensing applies. No rights to model services
or benchmark datasets are granted by this repository. Native/transitive packages
retain their own notices; inspect uv.lock and installed distribution metadata.
