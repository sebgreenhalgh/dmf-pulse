# Dependency review

No dependency was added. `pyproject.toml` and `uv.lock` are unchanged from the immutable base.
The implementation uses Decimal, standard-library enumeration and existing Pydantic/Typer/PyYAML
plus accepted Stage-11/12 modules. PyMC, NumPyro, LightGBM, XGBoost, scikit-learn, PyDTS and new
dataframe frameworks are absent. P3 is therefore truthfully `DEPENDENCY_NOT_APPROVED`.
