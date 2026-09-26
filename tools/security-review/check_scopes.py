import json
from datetime import timedelta

from asset_store_core.capabilities import Capability, Operation
from asset_store_core.errors import ValidationError
from asset_store_core.guard import _parse_alias
from asset_store_core.models import utcnow

n = 0
for partition in range(1, 301):
    prefix = f"users/{partition}/uploads"
    cap = Capability("test", Operation.READ, prefix, utcnow() + timedelta(minutes=1), "worker")
    for suffix in ["", "/file", "/nested/file"]:
        assert cap.allows(operation=Operation.READ, qualified_alias=prefix + suffix)
        n += 1
    for candidate in [
        f"users/{partition}0/uploads/file",
        f"users/{partition + 1}/uploads/file",
        f"users/{partition}/uploads2/file",
        f"results/{partition}/uploads/file",
    ]:
        assert not cap.allows(operation=Operation.READ, qualified_alias=candidate)
        n += 1
    assert not cap.allows(operation=Operation.WRITE, qualified_alias=prefix + "/file")
    n += 1
    assert not cap.allows(
        operation=Operation.READ, qualified_alias=prefix + "/file", now=cap.expires_at
    )
    n += 1
    for path in [prefix + "/../other", prefix + "/./file", prefix + "//file"]:
        try:
            _parse_alias(path)
        except ValidationError:
            pass
        else:
            raise AssertionError(path)
        n += 1
print(json.dumps({"scope_operation_expiry_and_path_checks": n, "failures": 0}))
