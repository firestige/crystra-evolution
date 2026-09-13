# Crystra Evolution release path

Pushing `release/next` qualifies that component commit. `release/request.json` supplies the `crystra-evolution-v<version>-rc.N` tag; `config/development-contract.json` supplies the exact independent Contracts input for both tests and the image's Workflow checker. No combination checkout or gitlink is required. The qualification authority and OCI provenance source are the component repository and SHA.

The image builds from this repository root with `.crystra-inputs/contracts` prepared from the pinned commit. Ordinary CI runs the real archive checker tests, Python 3.13/3.14, static checks and the same container build. The Python package is `crystra-evolution`; the runtime requires `CRYSTRA_EVOLUTION_CONFIG` naming an explicit JSON configuration file. Evolution remains stateless and queries Evidence over its read-only API.

Stable promotion remains a human gate. It reuses the qualified OCI digest, validates provenance and image identity, retags that digest as `crystra-evolution-v<version>`, and creates the final GitHub Release without rebuilding. Crystra candidates are not yet published; T5 completes external coordinates and release App configuration before T6 qualification.
