# Source and rights

- The original `KernelOriginAuthorizer`, origin validation, and local validation harness in this repository are authored by **dhtfish98** and licensed under this repository's MIT license.
- Jupyter Server is an unbundled runtime dependency and a research reference. Its source and rights remain with the IPython and Jupyter Development Teams under BSD-3-Clause. Reference: [fixed upstream commit](https://github.com/jupyter-server/jupyter_server/commit/f8169d721a0e0abb9ca27266c83db5a3a09e29d7) and [its LICENSE](https://github.com/jupyter-server/jupyter_server/blob/f8169d721a0e0abb9ca27266c83db5a3a09e29d7/LICENSE).
- The fixed commit shows that the kernel WebSocket calls the authorizer for `execute` on `kernels` before acquiring the kernel connection. The Jupyter identity provider accepts token input from a URL or authorization header and skips its origin check for token-authenticated requests. This is a documented research boundary for the additional local policy, not an allegation of an upstream defect.
- `ipykernel` and test-client dependencies are installed from their own distributions at validation time; their code is not copied into this repository.

No third-party source code, assets, or license text is incorporated into this project's original package. Dependency licenses remain with their respective owners and are not re-attributed.
