# Development host policy

The accepted development baseline is Python 3.13 managed by uv on Windows, Linux, or WSL2. Git is useful but doctor treats missing Git/uv diagnostics explicitly. A GPU, Docker, WSL, Make, database, service manager, and network connection at runtime are not required.

Run dependency resolution only when the ticket authorizes it. Normal tests and CLI commands are offline. Keep the repository, virtual environment, artifact root, and temporary wheel-verification environment separate; never configure tests against the user home or a production path.

The optional NVIDIA probe uses only discovered `nvidia-smi`, a short timeout, and bounded output. Absence, unsupported hardware, or timeout is nonblocking and must not trigger installation of GPU software.
