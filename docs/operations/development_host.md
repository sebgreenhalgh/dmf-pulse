# Development host policy

The development baseline is Python 3.13 managed by uv on Windows, Linux, or WSL2. Git is required for governed review evidence. Docker Compose and the pinned PostgreSQL 18.4 image are required for DAT-003 integration/acceptance; normal package imports, configuration, rules scoring, and non-database tests remain service-free.

Use only the disposable localhost TEST database, fake `changeme` credential, and explicit `DMF_ENVIRONMENT=TEST` boundary. Keep the repository, virtual environment, artifact root, database volume, and temporary wheel-verification environment separate. Always remove the DAT-003 volume after acceptance. No production host, credential, user-home test path, provider network, GPU framework, or long-running service is permitted.

The optional NVIDIA diagnostic remains discovery-only, bounded, and nonblocking.
