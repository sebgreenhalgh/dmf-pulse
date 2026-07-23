# Canonical temporal data model

DAT-003 provides the minimum PostgreSQL 18.4 vertical slice. Persisted canonical identities use server-generated UUIDv7 values. Temporal facts carry independent closed-open business-valid and system-known ranges; as-of reads require both timestamps. Corrections retain prior rows and bind their provenance explicitly.

`dmf_pulse.database` owns engine, migration, doctor, and schema inspection boundaries. `dmf_pulse.data_model` owns strict models, SQLAlchemy tables, explicit-session repositories, fixture services, and typed errors. Imports create no connection, process, environment mutation, or filesystem write.

Use only the disposable TEST boundary documented in `docs/operations/windows_and_linux_setup.md`. No mutable `latest` rules alias, provider access, SQLite substitute, predictive data, or future ontology is part of DAT-003.
