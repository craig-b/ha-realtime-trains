"""Pytest configuration for the Realtime Trains integration.

The existing model/api/fixture tests load modules via importlib so they
run without Home Assistant installed. The M12 coordinator/entity/
service/diagnostics tests need the full HA package, so they use
``pytest.importorskip("homeassistant")`` to skip gracefully when HA is
not on the path (i.e. local dev without HA core checked out). In CI,
the pytest workflow mounts this integration into HA core and sets
``PYTHONPATH`` so all imports resolve.
"""

# Existing conftest is empty; HA-dependent fixtures live in the individual
# test files that need them, guarded by importorskip at the module level.
